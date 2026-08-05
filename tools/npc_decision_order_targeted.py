#!/usr/bin/env python3
"""仅对已被“决定内顺序缺证”阻断的全国人大法规库记录定向补证。

默认只生成候选清单；--fetch 才访问候选决定详情和 DOCX；
--apply-registry 仅合并已经通过完整关联题名与正文顺序校验的证据。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import time
import unicodedata
import urllib.parse
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree


FLK_HOST = "flk.npc.gov.cn"
DETAIL_ENDPOINT = "https://flk.npc.gov.cn/law-search/search/flfgDetails"
DOWNLOAD_ENDPOINT = "https://flk.npc.gov.cn/law-search/download/pc"
USER_AGENT = "legal-cn-core-codices-targeted-evidence/1.0"


def normalize_title(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"[\s《》〈〉]", "", text)
    text = re.sub(r"[\uff08(](?:试行|暂行)[\uff09)]$", "", text)
    return text.lower()


def normalize_agency(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"\s+", "", text)
    return text.replace("人大常委会", "人民代表大会常务委员会")


def compact_date(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))[:8]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _is_flk_source(source_url: str) -> bool:
    try:
        return urllib.parse.urlparse(source_url).hostname == FLK_HOST
    except ValueError:
        return False


def build_blocked_events(
    manifest_rows: Iterable[dict[str, str]],
    source_rows: Iterable[dict[str, str]],
) -> dict[str, dict[str, Any]]:
    source_by_path = {row.get("relative_path", ""): row for row in source_rows}
    grouped: dict[str, dict[str, Any]] = {}
    for row in manifest_rows:
        if row.get("coding_status") != "BLOCKED":
            continue
        if row.get("internal_sequence_source") != "BLOCKED_MISSING_OFFICIAL_DECISION_ORDER":
            continue
        agency_code = row.get("agency_code", "")
        promulgation_date = compact_date(row.get("promulgation_date"))
        sequence_code = row.get("sequence_code", "")
        category_code = row.get("category_code", "")
        if not re.fullmatch(r"\d{10}", agency_code):
            continue
        if not re.fullmatch(r"\d{8}", promulgation_date):
            continue
        if not re.fullmatch(r"\d{4}", sequence_code):
            continue
        relative_path = row.get("relative_path", "")
        source = source_by_path.get(relative_path, {})
        title = source.get("title", "").strip()
        if not normalize_title(title):
            continue
        event_key = "|".join((agency_code, promulgation_date, sequence_code, category_code))
        event = grouped.setdefault(
            event_key,
            {
                "event_key": event_key,
                "agency_name": row.get("agency_name", ""),
                "agency_code": agency_code,
                "promulgation_date": promulgation_date,
                "sequence_code": sequence_code,
                "category_code": category_code,
                "documents": [],
                "npc_document_count": 0,
            },
        )
        source_url = source.get("source_url", "")
        if _is_flk_source(source_url):
            event["npc_document_count"] += 1
        event["documents"].append(
            {
                "relative_path": relative_path,
                "title": title,
                "source_url": source_url,
            }
        )
    retained = {
        key: value
        for key, value in grouped.items()
        if value["npc_document_count"] > 0
    }
    for event in retained.values():
        event["documents"].sort(key=lambda item: item["relative_path"])
    return retained


def _is_decision_index_row(row: dict[str, str]) -> bool:
    classification = str(row.get("flxz", ""))
    title = str(row.get("title", ""))
    return "修改、废止的决定" in classification or bool(
        re.search(r"(?:修改|修正|废止).{0,80}(?:决定|决议)$", title)
    )


def _chinese_integer(value: str) -> int | None:
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100}
    total = 0
    current = 0
    for character in value:
        if character in digits:
            current = digits[character]
            continue
        unit = units.get(character)
        if unit is None:
            return None
        total += (current or 1) * unit
        current = 0
    return total + current


def expected_linked_title_count(decision_title: str) -> int | None:
    match = re.search(
        r"等([0-9零〇一二两三四五六七八九十百]+)(?:项|部|件)(?:地方性)?法规",
        unicodedata.normalize("NFKC", str(decision_title or "")),
    )
    if not match:
        return None
    token = match.group(1)
    return int(token) if token.isdigit() else _chinese_integer(token)


def select_decision_candidates(
    events: dict[str, dict[str, Any]],
    index_rows: Iterable[dict[str, str]],
) -> list[dict[str, Any]]:
    events_by_agency_date: dict[tuple[str, str], list[str]] = defaultdict(list)
    for event_key, event in events.items():
        lookup = (normalize_agency(event.get("agency_name")), event["promulgation_date"])
        events_by_agency_date[lookup].append(event_key)
    selected: list[dict[str, Any]] = []
    seen = set()
    for row in index_rows:
        bbbs = row.get("bbbs", "")
        if not bbbs or bbbs in seen or not _is_decision_index_row(row):
            continue
        lookup = (normalize_agency(row.get("zdjgName")), compact_date(row.get("gbrq")))
        event_keys = sorted(events_by_agency_date.get(lookup, []))
        if not event_keys:
            continue
        seen.add(bbbs)
        selected.append({**row, "event_keys": event_keys})
    return sorted(selected, key=lambda row: row["bbbs"])


def _normalize_for_position(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[\s《》〈〉“”\"'、，,。.;；：:!?！？()\[\]（）【】]", "", text)


def order_linked_titles_from_text(
    text: str,
    linked_titles: Iterable[str],
) -> list[dict[str, Any]] | None:
    titles = [str(title or "").strip() for title in linked_titles]
    keys = [normalize_title(title) for title in titles]
    if not titles or any(not key for key in keys) or len(set(keys)) != len(keys):
        return None
    normalized_text = _normalize_for_position(text)
    located: list[tuple[int, str]] = []
    for title in titles:
        position = normalized_text.find(_normalize_for_position(title))
        if position < 0:
            return None
        located.append((position, title))
    if len({position for position, _ in located}) != len(located):
        return None
    located.sort(key=lambda item: item[0])
    return [
        {"title": title, "order": order}
        for order, (_, title) in enumerate(located, start=1)
    ]


def extract_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        document_xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(document_xml)
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = []
    for paragraph in root.iter(namespace + "p"):
        runs = [node.text or "" for node in paragraph.iter(namespace + "t")]
        if runs:
            paragraphs.append("".join(runs))
    return "\n".join(paragraphs)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_registry_entry(
    event: dict[str, Any],
    detail: dict[str, Any],
    ordered_titles: list[dict[str, Any]],
    evidence_path: Path,
    registry_base: Path,
) -> dict[str, Any]:
    bbbs = str(detail.get("bbbs", ""))
    return {
        "agency_code": event["agency_code"],
        "promulgation_date": event["promulgation_date"],
        "sequence_code": event["sequence_code"],
        "decision_title": detail.get("title", ""),
        "ordered_titles": ordered_titles,
        "evidence_path": Path(
            os.path.relpath(evidence_path.resolve(), registry_base.resolve())
        ).as_posix(),
        "official_url": f"https://flk.npc.gov.cn/detail?id={urllib.parse.quote(bbbs)}",
        "source_sha256": sha256_file(evidence_path),
    }


def filter_conflicting_decision_sequences(
    entries: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[tuple[str, str, str]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        key = (
            str(entry.get("agency_code", "")),
            str(entry.get("promulgation_date", "")),
            normalize_title(entry.get("decision_title")),
        )
        grouped[key].append(entry)
    conflicts = {
        key
        for key, group in grouped.items()
        if len({entry.get("sequence_code") for entry in group}) > 1
    }
    accepted = [
        entry
        for key, group in grouped.items()
        if key not in conflicts
        for entry in group
    ]
    return accepted, conflicts


class FlkClient:
    def __init__(self, proxy: str | None, delay_seconds: float = 0.2):
        self.proxy = proxy
        self.delay_seconds = max(0.0, delay_seconds)

    def get_bytes(self, url: str, attempts: int = 2) -> bytes:
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                command = [
                    "curl.exe",
                    "--fail-with-body",
                    "--location",
                    "--silent",
                    "--show-error",
                    "--max-time",
                    "12",
                    "--user-agent",
                    USER_AGENT,
                    "--referer",
                    "https://flk.npc.gov.cn/",
                ]
                if self.proxy:
                    command.extend(["--proxy", self.proxy])
                command.append(url)
                completed = subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    timeout=15,
                )
                payload = completed.stdout
                if self.delay_seconds:
                    time.sleep(self.delay_seconds)
                return payload
            except Exception as error:  # network failures are recorded, never converted to evidence
                last_error = error
                if attempt + 1 < attempts:
                    time.sleep(1.0 * (attempt + 1))
        raise RuntimeError(str(last_error)) from last_error

    def get_json_bytes(self, url: str) -> tuple[dict[str, Any], bytes]:
        payload = self.get_bytes(url)
        parsed = json.loads(payload.decode("utf-8-sig"))
        if parsed.get("code") != 200 or not isinstance(parsed.get("data"), dict):
            raise RuntimeError(f"官方接口未返回成功数据: {parsed.get('code')} {parsed.get('msg')}")
        return parsed, payload


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _candidate_overlaps(
    candidate_title: str,
    linked_titles: list[str],
    event: dict[str, Any],
) -> tuple[int, list[str]]:
    document_keys = {normalize_title(item["title"]): item["title"] for item in event["documents"]}
    matched = []
    candidate_key = normalize_title(candidate_title)
    if candidate_key in document_keys:
        matched.append(document_keys[candidate_key])
    for title in linked_titles:
        key = normalize_title(title)
        if key in document_keys and document_keys[key] not in matched:
            matched.append(document_keys[key])
    return len(matched), matched


def _download_official_docx(client: FlkClient, bbbs: str) -> tuple[bytes, dict[str, Any], bytes]:
    query = urllib.parse.urlencode({"format": "docx", "bbbs": bbbs, "fileId": ""})
    link_json, link_payload = client.get_json_bytes(f"{DOWNLOAD_ENDPOINT}?{query}")
    signed_url = link_json["data"].get("url")
    if not isinstance(signed_url, str) or not signed_url.startswith("https://"):
        raise RuntimeError("官方下载接口未返回 HTTPS 签名地址")
    docx = client.get_bytes(signed_url)
    if not docx.startswith(b"PK\x03\x04"):
        raise RuntimeError("下载结果不是 DOCX/ZIP 字节")
    return docx, link_json, link_payload


def fetch_and_build_candidates(
    candidates: list[dict[str, Any]],
    events: dict[str, dict[str, Any]],
    output_root: Path,
    registry_base: Path,
    client: FlkClient | None,
    offline: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_dir = output_root / "raw"
    text_dir = output_root / "normalized_text"
    raw_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)
    registry_entries = []
    result_rows = []
    for ordinal, candidate in enumerate(candidates, start=1):
        bbbs = candidate["bbbs"]
        result = {
            "bbbs": bbbs,
            "decision_title": candidate.get("title", ""),
            "event_count": len(candidate.get("event_keys", [])),
            "status": "",
            "registry_entry_count": 0,
            "matched_document_count": 0,
            "detail_path": "",
            "docx_path": "",
            "docx_sha256": "",
            "error": "",
        }
        try:
            detail_query = urllib.parse.urlencode({"bbbs": bbbs})
            detail_path = raw_dir / f"{bbbs}.detail.json"
            if detail_path.exists():
                detail_payload = detail_path.read_bytes()
                detail_json = json.loads(detail_payload.decode("utf-8-sig"))
                if detail_json.get("code") != 200 or not isinstance(detail_json.get("data"), dict):
                    raise RuntimeError("已缓存详情不是成功官方响应")
            else:
                if offline:
                    result["status"] = "DETAIL_REQUIRED"
                    result_rows.append(result)
                    continue
                if client is None:
                    raise RuntimeError("缺少网络客户端")
                detail_json, detail_payload = client.get_json_bytes(f"{DETAIL_ENDPOINT}?{detail_query}")
                detail_path.write_bytes(detail_payload)
            detail = detail_json["data"]
            result["detail_path"] = detail_path.relative_to(output_root).as_posix()
            linked_titles = [
                str(item.get("title", "")).strip()
                for item in (detail.get("flfg") or [])
                if normalize_title(item.get("title"))
            ]
            expected_count = expected_linked_title_count(detail.get("title", ""))
            if expected_count is not None and len({normalize_title(title) for title in linked_titles}) != expected_count:
                result["status"] = "LINKED_TITLE_COUNT_MISMATCH"
                result["error"] = f"决定题名数量={expected_count};官方关联题名={len(linked_titles)}"
                result_rows.append(result)
                continue
            preliminary = []
            for event_key in candidate.get("event_keys", []):
                event = events[event_key]
                coverage, matched_titles = _candidate_overlaps(detail.get("title", ""), linked_titles, event)
                if coverage >= 2:
                    preliminary.append((event, coverage, matched_titles))
            if not preliminary:
                result["status"] = "NO_EVENT_OVERLAP"
                result_rows.append(result)
                continue
            docx_path = raw_dir / f"{bbbs}.docx"
            if docx_path.exists() and docx_path.read_bytes()[:4] == b"PK\x03\x04":
                docx_bytes = docx_path.read_bytes()
            else:
                if offline:
                    result["status"] = "DOCX_REQUIRED"
                    result_rows.append(result)
                    continue
                if client is None:
                    raise RuntimeError("缺少网络客户端")
                docx_bytes, link_json, link_payload = _download_official_docx(client, bbbs)
                docx_path.write_bytes(docx_bytes)
                (raw_dir / f"{bbbs}.download.json").write_bytes(link_payload)
            result["docx_path"] = docx_path.relative_to(output_root).as_posix()
            result["docx_sha256"] = hashlib.sha256(docx_bytes).hexdigest()
            text = extract_docx_text(docx_path)
            text_path = text_dir / f"{bbbs}.txt"
            text_path.write_text(text, encoding="utf-8")
            ordered_titles = order_linked_titles_from_text(text, linked_titles)
            if ordered_titles is None:
                result["status"] = "LINKED_TITLE_COVERAGE_INCOMPLETE"
                result_rows.append(result)
                continue
            for event, coverage, matched_titles in preliminary:
                entry = build_registry_entry(event, detail, ordered_titles, docx_path, registry_base)
                registry_entries.append(entry)
                result["registry_entry_count"] += 1
                result["matched_document_count"] += coverage
            result["status"] = "EVIDENCE_READY"
        except Exception as error:
            result["status"] = "BLOCKED_ACCESS_OR_PARSE"
            result["error"] = str(error)[:1000]
        result_rows.append(result)
        if ordinal % 25 == 0:
            print(f"processed={ordinal}/{len(candidates)} evidence_ready={len(registry_entries)}", flush=True)
    unfiltered_registry_entries = registry_entries
    registry_entries, sequence_conflicts = filter_conflicting_decision_sequences(unfiltered_registry_entries)
    if sequence_conflicts:
        conflict_bbbs = {
            Path(entry.get("evidence_path", "")).stem
            for entry in unfiltered_registry_entries
            if (
                str(entry.get("agency_code", "")),
                str(entry.get("promulgation_date", "")),
                normalize_title(entry.get("decision_title")),
            ) in sequence_conflicts
        }
        for row in result_rows:
            if row["bbbs"] in conflict_bbbs:
                row["status"] = "DECISION_SEQUENCE_CONFLICT"
                row["registry_entry_count"] = 0
                row["error"] = "同一官方决定匹配多个文号顺序码"
    deduplicated = {}
    for entry in registry_entries:
        key = (
            entry["agency_code"],
            entry["promulgation_date"],
            entry["sequence_code"],
            normalize_title(entry["decision_title"]),
        )
        previous = deduplicated.get(key)
        if previous and previous != entry:
            raise RuntimeError(f"同一决定生成冲突证据: {key}")
        deduplicated[key] = entry
    return list(deduplicated.values()), result_rows


def apply_registry_entries(registry_path: Path, entries: list[dict[str, Any]]) -> int:
    registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
    existing = registry.get("entries") or []
    keys = {
        (
            item.get("agency_code"),
            item.get("promulgation_date"),
            item.get("sequence_code"),
            normalize_title(item.get("decision_title")),
        )
        for item in existing
    }
    additions = []
    for entry in entries:
        key = (
            entry["agency_code"],
            entry["promulgation_date"],
            entry["sequence_code"],
            normalize_title(entry["decision_title"]),
        )
        if key not in keys:
            additions.append(entry)
            keys.add(key)
    if additions:
        registry["version"] = datetime.now(timezone.utc).date().isoformat()
        registry["entries"] = existing + additions
        _atomic_write_json(registry_path, registry)
    return len(additions)


def write_checksums(output_root: Path) -> None:
    checksum_path = output_root / "SHA256SUMS.txt"
    files = sorted(
        path
        for path in output_root.rglob("*")
        if path.is_file() and path != checksum_path
    )
    lines = [f"{sha256_file(path)}  {path.relative_to(output_root).as_posix()}" for path in files]
    checksum_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-records", type=Path, required=True)
    parser.add_argument("--official-index", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--proxy", default="http://127.0.0.1:10808")
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--max-candidates", type=int, default=0)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--apply-registry", action="store_true")
    args = parser.parse_args()
    if args.fetch and args.offline:
        parser.error("--fetch 与 --offline 不能同时使用")
    if args.apply_registry and not (args.fetch or args.offline):
        parser.error("--apply-registry 必须与 --fetch 或 --offline 同时使用")
    args.output_root.mkdir(parents=True, exist_ok=True)
    manifest_rows = read_csv(args.manifest)
    source_rows = read_csv(args.source_records)
    index_rows = read_csv(args.official_index)
    events = build_blocked_events(manifest_rows, source_rows)
    candidates = select_decision_candidates(events, index_rows)
    if args.max_candidates > 0:
        candidates = candidates[: args.max_candidates]
    selection_rows = []
    for candidate in candidates:
        selection_rows.append(
            {
                "bbbs": candidate["bbbs"],
                "title": candidate.get("title", ""),
                "gbrq": candidate.get("gbrq", ""),
                "zdjgName": candidate.get("zdjgName", ""),
                "flxz": candidate.get("flxz", ""),
                "event_count": len(candidate.get("event_keys", [])),
                "event_keys": "|~|".join(candidate.get("event_keys", [])),
            }
        )
    write_csv(
        args.output_root / "candidate_selection.csv",
        selection_rows,
        ["bbbs", "title", "gbrq", "zdjgName", "flxz", "event_count", "event_keys"],
    )
    registry_entries = []
    result_rows = []
    additions = 0
    if args.fetch or args.offline:
        client = None if args.offline else FlkClient(args.proxy or None, args.delay)
        registry_entries, result_rows = fetch_and_build_candidates(
            candidates,
            events,
            args.output_root,
            args.registry.parent,
            client,
            offline=args.offline,
        )
        _atomic_write_json(
            args.output_root / "registry_candidates.json",
            {"version": datetime.now(timezone.utc).date().isoformat(), "entries": registry_entries},
        )
        write_csv(
            args.output_root / "fetch_results.csv",
            result_rows,
            [
                "bbbs",
                "decision_title",
                "event_count",
                "status",
                "registry_entry_count",
                "matched_document_count",
                "detail_path",
                "docx_path",
                "docx_sha256",
                "error",
            ],
        )
        if args.apply_registry:
            additions = apply_registry_entries(args.registry, registry_entries)
    summary = {
        "blocked_event_count": len(events),
        "blocked_document_count": sum(len(event["documents"]) for event in events.values()),
        "decision_candidate_count": len(candidates),
        "fetched": args.fetch,
        "offline": args.offline,
        "evidence_ready_entry_count": len(registry_entries),
        "registry_addition_count": additions,
        "status_counts": dict(
            sorted(
                (
                    status,
                    sum(1 for row in result_rows if row["status"] == status),
                )
                for status in {row["status"] for row in result_rows}
            )
        ),
    }
    _atomic_write_json(args.output_root / "summary.json", summary)
    write_checksums(args.output_root)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
