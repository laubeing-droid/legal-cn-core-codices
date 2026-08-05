#!/usr/bin/env python3
"""将人民法院案例库官方索引与正式区 07 目录按案例编号对照。"""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

CASE_ID_RE = re.compile(r"20\d{2}-\d{2}-\d+-\d{3}-\d{3}")


def find_duplicate_official_case_ids(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        case_id = str(row.get("case_id") or "").strip()
        if case_id:
            grouped[case_id].append(row)
    conflicts: list[dict[str, str]] = []
    for case_id, matches in sorted(grouped.items()):
        api_ids = sorted({str(row.get("api_id") or "").strip() for row in matches})
        if len(matches) < 2 or len(api_ids) < 2:
            continue
        conflicts.append(
            {
                "case_id": case_id,
                "conflict_type": "DUPLICATE_OFFICIAL_CASE_ID",
                "row_count": str(len(matches)),
                "distinct_api_ids": "|".join(api_ids),
                "titles": "|".join(sorted({str(row.get("title") or "").strip() for row in matches})),
                "resolution_status": "MANUAL_REVIEW_REQUIRED",
            }
        )
    return conflicts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--official-csv", type=Path, required=True)
    parser.add_argument(
        "--formal-dir",
        type=Path,
        action="append",
        required=True,
        help="可重复传入多个正式目录",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    with args.official_csv.open("r", encoding="utf-8-sig", newline="") as f:
        official_rows = list(csv.DictReader(f))
    conflicts = find_duplicate_official_case_ids(official_rows)
    official = {
        str(row.get("case_id") or "").strip(): row
        for row in official_rows if str(row.get("case_id") or "").strip()
    }

    local: dict[str, str] = {}
    for formal_dir in args.formal_dir:
        for path in formal_dir.rglob("*"):
            if not path.is_file():
                continue
            match = CASE_ID_RE.search(path.name)
            if not match and path.suffix.lower() == ".md":
                try:
                    match = CASE_ID_RE.search(
                        path.read_bytes()[:32_768].decode("utf-8-sig", errors="ignore")
                    )
                except OSError:
                    pass
            if match:
                local[match.group()] = str(path)

    missing = [row for case_id, row in official.items() if case_id not in local]
    extra = [{"case_id": case_id, "local_path": path}
             for case_id, path in local.items() if case_id not in official]

    official_fields = list(official_rows[0]) if official_rows else ["case_id"]
    with (args.output / "案例库官网有_正式区无.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=official_fields)
        writer.writeheader()
        writer.writerows(missing)
    with (args.output / "案例库正式区有_官网索引无.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=["case_id", "local_path"])
        writer.writeheader()
        writer.writerows(extra)
    with (args.output / "案例库官网索引编号冲突.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        fields = [
            "case_id", "conflict_type", "row_count", "distinct_api_ids",
            "titles", "resolution_status",
        ]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(conflicts)

    print(f"official={len(official)}")
    print(f"local={len(local)}")
    print(f"official_only={len(missing)}")
    print(f"local_only={len(extra)}")
    print(f"official_index_conflicts={len(conflicts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
