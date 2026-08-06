from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path


FIELDNAMES = [
    "relative_path", "source_type", "provider_record_id", "provider_url",
    "matched_title", "document_number", "issue_department", "issue_date",
    "implementation_date", "timeliness", "identity_match", "fulltext_match",
    "verified_at", "evidence_sha256", "evidence_path", "note",
]


def selected_candidate(provider_evidence: list[dict]) -> tuple[str, dict] | None:
    for evidence in provider_evidence:
        provider = evidence.get("provider", "")
        selected_id = str(evidence.get("selected_record_id", ""))
        if not selected_id:
            continue
        raw = evidence.get("result")
        if provider == "PKULAW" and isinstance(raw, list):
            for item in raw:
                if str(item.get("gid", "")) == selected_id:
                    return provider, {
                        "record_id": selected_id,
                        "url": item.get("url", ""),
                        "title": item.get("title", ""),
                        "document_number": item.get("doc_no", ""),
                        "issue_department": item.get("issue_department", ""),
                        "issue_date": item.get("issue_date", ""),
                        "implementation_date": item.get("implementation_date", ""),
                        "timeliness": item.get("timeliness", ""),
                    }
        if provider == "YUANDIAN" and isinstance(raw, dict):
            for item in raw.get("data", []):
                if str(item.get("id", "")) == selected_id:
                    return provider, {
                        "record_id": selected_id,
                        "url": item.get("url", ""),
                        "title": item.get("fgmc") or item.get("title", ""),
                        "document_number": item.get("fwzh", ""),
                        "issue_department": item.get("fbbm", ""),
                        "issue_date": item.get("fbrq", ""),
                        "implementation_date": item.get("ssrq", ""),
                        "timeliness": item.get("sxx", ""),
                    }
    return None


def recover(evidence_dir: Path) -> tuple[list[dict[str, str]], list[str]]:
    selected_by_path: dict[str, dict[str, str]] = {}
    processed_paths: set[str] = set()
    for evidence_path in sorted(evidence_dir.glob("*.json")):
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        record = payload.get("record", {})
        relative_path = str(record.get("relative_path", ""))
        if not relative_path:
            raise ValueError(f"EVIDENCE_WITHOUT_RELATIVE_PATH:{evidence_path}")
        processed_paths.add(relative_path)
        selected = selected_candidate(payload.get("provider_evidence", []))
        if not selected:
            continue
        provider, candidate = selected
        recovered = {
            "relative_path": relative_path,
            "source_type": f"{provider}_VERIFIED",
            "provider_record_id": str(candidate["record_id"]),
            "provider_url": str(candidate["url"]),
            "matched_title": str(candidate["title"]),
            "document_number": str(candidate["document_number"]),
            "issue_department": str(candidate["issue_department"]),
            "issue_date": str(candidate["issue_date"]),
            "implementation_date": str(candidate["implementation_date"]),
            "timeliness": str(candidate["timeliness"]),
            "identity_match": "true",
            "fulltext_match": "false",
            "verified_at": datetime.fromtimestamp(
                evidence_path.stat().st_mtime, tz=timezone.utc
            ).isoformat(),
            "evidence_sha256": evidence_path.stem,
            "evidence_path": f"evidence/{evidence_path.name}",
            "note": "从已落盘MCP原始证据恢复；商业数据库标题精确命中。",
        }
        previous = selected_by_path.get(relative_path)
        if previous and previous["provider_record_id"] != recovered["provider_record_id"]:
            raise ValueError(f"CONFLICTING_RECOVERED_RECORD:{relative_path}")
        selected_by_path[relative_path] = recovered
    return [selected_by_path[key] for key in sorted(selected_by_path)], sorted(processed_paths)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--processed-paths", required=True, type=Path)
    args = parser.parse_args()
    rows, processed = recover(args.evidence_dir)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    with args.processed_paths.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["relative_path"])
        writer.writeheader()
        writer.writerows({"relative_path": value} for value in processed)
    print({"processed": len(processed), "verified": len(rows)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
