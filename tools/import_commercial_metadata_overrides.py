#!/usr/bin/env python3
"""Convert accepted commercial-law registry rows into metadata overrides."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


EFFECT_CODES = {
    "现行有效": "01",
    "尚未生效": "02",
    "尚未施行": "02",
    "已被修改": "03",
    "部分废止或失效": "03",
    "已废止": "04",
    "已失效": "05",
}


def compact_date(value: str) -> str:
    value = value.strip()
    return value.replace("-", "") if len(value) == 10 else ""


def effect_code(value: str) -> str:
    return EFFECT_CODES.get(value.strip(), "")


def override_from_row(row: dict[str, str]) -> dict[str, object]:
    relative_path = row.get("relative_path", "").replace("\\", "/").strip()
    if not relative_path or relative_path.startswith("/") or ".." in relative_path.split("/"):
        raise ValueError(f"INVALID_RELATIVE_PATH:{relative_path}")
    if row.get("identity_match", "").lower() != "true":
        raise ValueError(f"IDENTITY_NOT_VERIFIED:{relative_path}")

    values: dict[str, str] = {}
    issue_date = compact_date(row.get("issue_date", ""))
    implementation_date = compact_date(row.get("implementation_date", ""))
    status_code = effect_code(row.get("timeliness", ""))
    document_number = row.get("document_number", "").strip()
    source_type = row.get("source_type", "").strip()
    if issue_date:
        values["GBRQ"] = issue_date
        values["_promulgation_source"] = source_type
    if implementation_date:
        values["SXRQ"] = implementation_date
        values["_effective_date_source"] = source_type
    if status_code:
        values["SXX"] = status_code
        values["_effect_source"] = source_type
    if document_number:
        values["FWZH"] = document_number

    return {
        "relative_path": relative_path,
        "values": values,
        "evidence": {
            "type": source_type,
            "provider_record_id": row.get("provider_record_id", "").strip(),
            "url": row.get("provider_url", "").strip(),
            "matched_title": row.get("matched_title", "").strip(),
            "timeliness_raw": row.get("timeliness", "").strip(),
            "verified_at": row.get("verified_at", "").strip(),
            "source_sha256": row.get("evidence_sha256", "").strip(),
            "note": "商业法律数据库精确身份核验；作为本地元数据补证，不冒充制定机关签发。",
        },
    }


def load_rows(paths: list[Path]) -> list[dict[str, str]]:
    by_path: dict[str, dict[str, object]] = {}
    for csv_path in paths:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                entry = override_from_row(row)
                relative_path = str(entry["relative_path"])
                previous = by_path.get(relative_path)
                if previous and previous != entry:
                    raise ValueError(f"CONFLICTING_DUPLICATE:{relative_path}")
                by_path[relative_path] = entry
    return [by_path[key] for key in sorted(by_path)]


def merge_entries(*entry_sets: list[dict[str, object]]) -> list[dict[str, object]]:
    by_path: dict[str, dict[str, object]] = {}
    for entries in entry_sets:
        for entry in entries:
            relative_path = str(entry.get("relative_path", ""))
            if not relative_path:
                raise ValueError("INVALID_RELATIVE_PATH:")
            previous = by_path.get(relative_path)
            if previous and previous != entry:
                raise ValueError(f"CONFLICTING_DUPLICATE:{relative_path}")
            by_path[relative_path] = entry
    return [by_path[key] for key in sorted(by_path)]


def load_existing_registry(path: Path | None) -> list[dict[str, object]]:
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        raise ValueError("INVALID_EXISTING_REGISTRY")
    return entries


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", action="append", required=True, type=Path)
    parser.add_argument("--existing-registry", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    payload = {
        "version": "2026-08-06",
        "policy": "IDENTITY_VERIFIED_METADATA_ONLY; ambiguous combined effect states remain empty",
        "entries": merge_entries(
            load_existing_registry(args.existing_registry),
            load_rows(args.input),
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
