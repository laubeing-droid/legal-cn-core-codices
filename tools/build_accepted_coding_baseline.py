#!/usr/bin/env python3
"""Freeze source-hash-bound WJBS values from one fully validated batch."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path


csv.field_size_limit(min(sys.maxsize, 2_147_483_647))

FIELDS = [
    "source_relative_path",
    "source_sha256",
    "WJBS",
    "WJBS_source_type",
    "accepted_batch",
    "accepted_tree_sha256",
]
WJBS_PATTERN = re.compile(r"^1\.2\.156\.3005\.6-\d{31}$")
ALLOWED_SOURCE_TYPES = {"AUTHORITY_ISSUED", "STANDARD_DERIVED_LOCAL"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def build_baseline(engineering_root: Path, formal_root: Path) -> list[dict[str, str]]:
    summary = json.loads((engineering_root / "build_summary.json").read_text(encoding="utf-8"))
    validation = json.loads(
        (engineering_root / "full_validation_report.json").read_text(encoding="utf-8")
    )
    if summary.get("enumeration_mode") != "FULL_CORPUS_ENUMERATION":
        raise ValueError("ACCEPTED_BASELINE_REQUIRES_FULL_CORPUS_BUILD")
    if not summary.get("gates", {}).get("publishable_full_scope"):
        raise ValueError("ACCEPTED_BASELINE_BUILD_NOT_PUBLISHABLE")
    if validation.get("status") != "LOCAL_FULLY_VALIDATED":
        raise ValueError("ACCEPTED_BASELINE_VALIDATION_NOT_PASSED")
    tree_sha256 = validation.get("artifact_tree_sha256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", tree_sha256, re.IGNORECASE):
        raise ValueError("ACCEPTED_BASELINE_TREE_HASH_INVALID")

    source_hashes = {
        row["relative_path"]: row["source_sha256"]
        for row in read_csv(engineering_root / "source_records.csv")
    }
    published_paths = {
        row["relative_path"].replace("\\", "/")
        for row in read_csv(engineering_root / "ingest_queue.csv")
        if row.get("ingest_status") == "READY_FORMAL_LAW"
    }
    published_wjbs = {
        row["WJBS"]
        for row in read_csv(formal_root / "legal_documents.csv")
        if row.get("WJBS")
    }
    coding_path = engineering_root / "批次清单" / "标准编码生成清单.csv"
    output: list[dict[str, str]] = []
    seen: set[str] = set()
    seen_wjbs: set[str] = set()
    for row in read_csv(coding_path):
        if row.get("coding_status") != "READY" or not row.get("WJBS"):
            continue
        relative_path = row["relative_path"].replace("\\", "/")
        if relative_path not in published_paths or row["WJBS"] not in published_wjbs:
            continue
        source_sha256 = source_hashes.get(relative_path, "")
        source_type = row.get("WJBS_source_type", "")
        if relative_path in seen:
            raise ValueError(f"ACCEPTED_BASELINE_DUPLICATE_PATH:{relative_path}")
        if not re.fullmatch(r"[0-9a-f]{64}", source_sha256, re.IGNORECASE):
            raise ValueError(f"ACCEPTED_BASELINE_SOURCE_HASH_INVALID:{relative_path}")
        if not WJBS_PATTERN.fullmatch(row["WJBS"]):
            raise ValueError(f"ACCEPTED_BASELINE_WJBS_INVALID:{relative_path}")
        if source_type not in ALLOWED_SOURCE_TYPES:
            raise ValueError(f"ACCEPTED_BASELINE_SOURCE_TYPE_INVALID:{relative_path}")
        if row["WJBS"] in seen_wjbs:
            raise ValueError(f"ACCEPTED_BASELINE_DUPLICATE_WJBS:{row['WJBS']}")
        seen.add(relative_path)
        seen_wjbs.add(row["WJBS"])
        output.append({
            "source_relative_path": relative_path,
            "source_sha256": source_sha256.lower(),
            "WJBS": row["WJBS"],
            "WJBS_source_type": source_type,
            "accepted_batch": engineering_root.name,
            "accepted_tree_sha256": tree_sha256.lower(),
        })
    return sorted(output, key=lambda row: row["source_relative_path"])


def write_baseline(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engineering-root", type=Path, required=True)
    parser.add_argument("--formal-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = build_baseline(args.engineering_root.resolve(), args.formal_root.resolve())
    write_baseline(args.output.resolve(), rows)
    print(f"accepted_coding_rows={len(rows)} output={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
