from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import threading
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROVIDERS = {
    "YUANDIAN": {
        "url": "https://open.chineselaw.com/mcp/law/stream",
        "token_env": "YUANDIAN_MCP_TOKEN",
    },
    "PKULAW": {
        "url": "https://apim-gateway.pkulaw.com/mcp-law-search-service",
        "token_env": "PKULAW_MCP_TOKEN",
    },
}
VERSION_SUFFIX_RE = re.compile(
    r"[（(]\s*\d{4}(?:[^）)]*(?:修正|修订|修改)[^）)]*)?[）)]\s*$"
)
LOCAL_STATUS_SUFFIX_RE = re.compile(
    r"[（(]\s*(?:失效|已失效|废止|已废止|有效|现行有效)\s*[）)]\s*$"
)
NON_IDENTITY_RE = re.compile(r"[^0-9A-Za-z\u3400-\u9fff]+")


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip()
    normalized = normalized.replace("人大常委会", "人民代表大会常务委员会")
    normalized = LOCAL_STATUS_SUFFIX_RE.sub("", normalized)
    normalized = VERSION_SUFFIX_RE.sub("", normalized)
    return NON_IDENTITY_RE.sub("", normalized).lower()


def title_query(value: str, chunk_size: int = 4) -> str:
    compact = normalize_title(value)
    return " ".join(
        compact[index : index + chunk_size]
        for index in range(0, len(compact), chunk_size)
        if compact[index : index + chunk_size]
    )


def provider_order(promulgation_date: str) -> tuple[str, str]:
    year_match = re.match(r"^(\d{4})", promulgation_date or "")
    if not year_match or int(year_match.group(1)) < 2000:
        return "PKULAW", "YUANDIAN"
    return "YUANDIAN", "PKULAW"


def select_exact_match(
    title: str, promulgation_date: str, candidates: list[dict[str, Any]]
) -> dict[str, Any] | None:
    target = normalize_title(title)
    exact = [candidate for candidate in candidates if normalize_title(candidate.get("title", "")) == target]
    if not exact:
        return None

    target_date = (promulgation_date or "")[:10]
    target_year = target_date[:4] if re.match(r"^\d{4}", target_date) else ""
    if target_year:
        same_year = [
            candidate
            for candidate in exact
            if str(candidate.get("issue_date", ""))[:4] == target_year
        ]
        if same_year:
            exact = same_year
        elif target_date[5:] == "01-01":
            previous_year = str(int(target_year) - 1)
            exact = [
                candidate
                for candidate in exact
                if str(candidate.get("issue_date", ""))[:4] == previous_year
            ]
            if not exact:
                return None
        else:
            try:
                target_day = datetime.strptime(target_date, "%Y-%m-%d").date()
                nearby = [
                    candidate
                    for candidate in exact
                    if candidate.get("issue_date")
                    and abs(
                        (
                            datetime.strptime(
                                str(candidate["issue_date"])[:10], "%Y-%m-%d"
                            ).date()
                            - target_day
                        ).days
                    )
                    <= 120
                ]
            except (TypeError, ValueError):
                nearby = []
            if not nearby:
                return None
            exact = nearby
    exact.sort(
        key=lambda candidate: (
            candidate.get("issue_date", "")[:10] != target_date,
            candidate.get("issue_date", ""),
            candidate.get("title", ""),
        )
    )
    return exact[0]


class McpHttpClient:
    def __init__(self, provider: str, timeout: int = 120) -> None:
        config = PROVIDERS[provider]
        token = os.environ.get(config["token_env"], "").strip()
        if not token:
            raise RuntimeError(f"missing environment variable: {config['token_env']}")
        self.provider = provider
        self.url = config["url"]
        self.timeout = timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        self.request_id = 0

    def call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self.headers,
            method="POST",
        )
        with self.opener.open(request, timeout=self.timeout) as response:
            envelope = json.loads(response.read().decode("utf-8"))
        if "error" in envelope:
            raise RuntimeError(json.dumps(envelope["error"], ensure_ascii=False))
        result = envelope.get("result", {})
        if result.get("isError"):
            raise RuntimeError(json.dumps(result, ensure_ascii=False))
        return result


def _result_text(result: dict[str, Any]) -> Any:
    structured = result.get("structuredContent", {}).get("result")
    if structured is not None:
        return structured
    content = result.get("content", [])
    if not content:
        return None
    text = content[0].get("text", "")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def search_yuandian(
    client: McpHttpClient, title: str, promulgation_date: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    year = (promulgation_date or "")[:4]
    arguments: dict[str, Any] = {"fgmc": title_query(title), "top_k": 50}
    if re.fullmatch(r"\d{4}", year):
        arguments["fbrq_start"] = f"{year}-01-01"
        arguments["fbrq_end"] = f"{year}-12-31"
    result = client.call("yuandian_rh_fg_search", arguments)
    raw = _result_text(result)
    data = raw.get("data", []) if isinstance(raw, dict) else []
    candidates = [
        {
            "provider": "YUANDIAN",
            "record_id": item.get("id", ""),
            "title": item.get("fgmc") or item.get("title", ""),
            "document_number": item.get("fwzh", "") or "",
            "issue_department": item.get("fbbm", "") or "",
            "issue_date": item.get("fbrq", "") or "",
            "implementation_date": item.get("ssrq", "") or "",
            "timeliness": item.get("sxx", "") or "",
            "url": item.get("url", "") or "",
        }
        for item in data
    ]
    return candidates, {"tool": "yuandian_rh_fg_search", "arguments": arguments, "result": raw}


def search_pkulaw(
    client: McpHttpClient, title: str, promulgation_date: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    arguments: dict[str, Any] = {"text": title_query(title), "size": 50}
    result = client.call("search_article", arguments)
    raw = _result_text(result)
    data = raw if isinstance(raw, list) else []
    candidates = [
        {
            "provider": "PKULAW",
            "record_id": item.get("gid", ""),
            "title": item.get("title", ""),
            "document_number": item.get("doc_no", "") or "",
            "issue_department": item.get("issue_department", "") or "",
            "issue_date": item.get("issue_date", "") or "",
            "implementation_date": item.get("implementation_date", "") or "",
            "timeliness": item.get("timeliness", "") or "",
            "url": item.get("url", "") or "",
        }
        for item in data
    ]
    return candidates, {"tool": "search_article", "arguments": arguments, "result": raw}


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def verify_record(
    record: dict[str, str], clients: dict[str, McpHttpClient], cross_check: bool
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    selected_rows: list[dict[str, str]] = []
    evidence: list[dict[str, Any]] = []
    for provider in provider_order(record.get("promulgation_date", "")):
        try:
            if provider == "YUANDIAN":
                candidates, raw = search_yuandian(
                    clients[provider], record["title"], record.get("promulgation_date", "")
                )
            else:
                candidates, raw = search_pkulaw(
                    clients[provider], record["title"], record.get("promulgation_date", "")
                )
            selected = select_exact_match(
                record["title"], record.get("promulgation_date", ""), candidates
            )
            raw["provider"] = provider
            raw["selected_record_id"] = selected.get("record_id", "") if selected else ""
            evidence.append(raw)
            if selected:
                selected_rows.append(
                    {
                        "relative_path": record["relative_path"],
                        "source_type": f"{provider}_VERIFIED",
                        "provider_record_id": str(selected.get("record_id", "")),
                        "provider_url": str(selected.get("url", "")),
                        "matched_title": str(selected.get("title", "")),
                        "document_number": str(selected.get("document_number", "")),
                        "issue_department": str(selected.get("issue_department", "")),
                        "issue_date": str(selected.get("issue_date", "")),
                        "implementation_date": str(selected.get("implementation_date", "")),
                        "timeliness": str(selected.get("timeliness", "")),
                        "identity_match": "true",
                        "fulltext_match": "false",
                        "verified_at": datetime.now(timezone.utc).isoformat(),
                        "evidence_sha256": "",
                        "evidence_path": "",
                        "note": "商业数据库标题精确命中；不冒充制定机关官网来源。",
                    }
                )
                if not cross_check:
                    break
        except Exception as exc:  # network failures must remain traceable
            evidence.append({"provider": provider, "error": f"{type(exc).__name__}: {exc}"})
        time.sleep(0.05)
    return selected_rows, evidence


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Verify legal records through YuanDian/PKULaw MCP.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--cross-check", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    with args.input.open("r", encoding="utf-8-sig", newline="") as handle:
        records = list(csv.DictReader(handle))
    if args.limit > 0:
        records = records[: args.limit]

    if args.workers < 1 or args.workers > 8:
        raise ValueError("--workers must be between 1 and 8")
    thread_state = threading.local()

    def process_record(item: tuple[int, dict[str, str]]):
        index, record = item
        if not hasattr(thread_state, "clients"):
            thread_state.clients = {
                provider: McpHttpClient(provider) for provider in PROVIDERS
            }
        rows, evidence = verify_record(record, thread_state.clients, args.cross_check)
        return index, record, rows, evidence

    evidence_dir = args.output_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "relative_path",
        "source_type",
        "provider_record_id",
        "provider_url",
        "matched_title",
        "document_number",
        "issue_department",
        "issue_date",
        "implementation_date",
        "timeliness",
        "identity_match",
        "fulltext_match",
        "verified_at",
        "evidence_sha256",
        "evidence_path",
        "note",
    ]
    partial_registry_path = args.output_dir / "commercial_verification_registry.partial.csv"
    final_registry_path = args.output_dir / "commercial_verification_registry.csv"
    verified_rows = 0

    with partial_registry_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            results = executor.map(process_record, enumerate(records, 1))
            for index, record, rows, evidence in results:
                evidence_bytes = canonical_json_bytes(
                    {"record": record, "provider_evidence": evidence}
                )
                digest = hashlib.sha256(evidence_bytes).hexdigest()
                evidence_relative = f"evidence/{digest}.json"
                (args.output_dir / evidence_relative).write_bytes(evidence_bytes)
                for row in rows:
                    row["evidence_sha256"] = digest
                    row["evidence_path"] = evidence_relative
                    writer.writerow(row)
                    verified_rows += 1
                handle.flush()
                print(f"{index}/{len(records)} {record['relative_path']} matches={len(rows)}")
    os.replace(partial_registry_path, final_registry_path)
    print({"records": len(records), "verified_rows": verified_rows})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
