#!/usr/bin/env python3
"""按bbbs/id比对FLK官方索引与正式区；只生成候选清单。"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

FLK_ID_RE = re.compile(r"(?i)(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])")
SPACE_RE = re.compile(r"\s+")


def read_metadata(path: Path) -> dict[str, str]:
    try:
        text = path.read_bytes()[:32_768].decode("utf-8-sig", errors="replace")
    except OSError:
        return {}
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    metadata: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line or line.startswith((" ", "\t")):
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip("'\"")
    return metadata


def normalized_title(value: str) -> str:
    return SPACE_RE.sub("", value or "")


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--official-csv", type=Path, required=True)
    parser.add_argument("--formal-dir", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    with args.official_csv.open("r", encoding="utf-8-sig", newline="") as file:
        official_rows = list(csv.DictReader(file))

    official_groups: dict[str, list[dict]] = defaultdict(list)
    for row in official_rows:
        official_id = str(row.get("bbbs") or "").strip().lower()
        if official_id:
            official_groups[official_id].append(row)

    local_groups: dict[str, list[dict]] = defaultdict(list)
    invalid_local: list[dict] = []
    for formal_dir in args.formal_dir:
        for path in formal_dir.rglob("*.md"):
            metadata = read_metadata(path)
            local_id = str(metadata.get("id") or "").strip().lower()
            if not local_id:
                match = FLK_ID_RE.search(path.name)
                local_id = match.group().lower() if match else ""
            if not local_id:
                invalid_local.append({"local_path": str(path), "reason": "缺少32位id"})
                continue
            local_groups[local_id].append(
                {
                    "id": local_id,
                    "title": metadata.get("title", ""),
                    "status": metadata.get("status", ""),
                    "date": metadata.get("date")
                    or metadata.get("publication_date", ""),
                    "local_path": str(path),
                }
            )

    official_ids = set(official_groups)
    local_ids = set(local_groups)
    official_only = [
        {
            **official_groups[official_id][0],
            "说明": "官网有、正式区无候选；须回官网详情复核后入库",
        }
        for official_id in sorted(official_ids - local_ids)
    ]
    local_only = [
        {
            **local_groups[local_id][0],
            "说明": "正式区有、官网索引无候选；不得据此认定失效",
        }
        for local_id in sorted(local_ids - official_ids)
    ]
    title_mismatches: list[dict] = []
    for common_id in sorted(official_ids & local_ids):
        official = official_groups[common_id][0]
        for local in local_groups[common_id]:
            if (
                official.get("title")
                and local.get("title")
                and normalized_title(str(official["title"]))
                != normalized_title(str(local["title"]))
            ):
                title_mismatches.append(
                    {
                        "id": common_id,
                        "official_title": official["title"],
                        "local_title": local["title"],
                        "local_path": local["local_path"],
                    }
                )

    official_duplicates = [
        {
            "bbbs": official_id,
            "count": len(rows),
            "titles": " | ".join(sorted({str(row.get("title") or "") for row in rows})),
        }
        for official_id, rows in sorted(official_groups.items())
        if len(rows) > 1
    ]
    local_duplicates = [
        {
            "id": local_id,
            "count": len(rows),
            "local_paths": " | ".join(row["local_path"] for row in rows),
        }
        for local_id, rows in sorted(local_groups.items())
        if len(rows) > 1
    ]

    official_fields = list(official_rows[0]) if official_rows else ["bbbs"]
    write_csv(
        args.output / "flk_官网有_正式区无.csv",
        official_only,
        official_fields + ["说明"],
    )
    write_csv(
        args.output / "flk_正式区有_官网无.csv",
        local_only,
        ["id", "title", "status", "date", "local_path", "说明"],
    )
    write_csv(
        args.output / "flk_同ID标题不一致.csv",
        title_mismatches,
        ["id", "official_title", "local_title", "local_path"],
    )
    write_csv(
        args.output / "flk_官网重复ID.csv",
        official_duplicates,
        ["bbbs", "count", "titles"],
    )
    write_csv(
        args.output / "flk_本地重复ID.csv",
        local_duplicates,
        ["id", "count", "local_paths"],
    )
    write_csv(
        args.output / "flk_本地缺少稳定ID.csv",
        invalid_local,
        ["local_path", "reason"],
    )

    summary = {
        "official_rows": len(official_rows),
        "official_unique_ids": len(official_ids),
        "local_unique_ids": len(local_ids),
        "common_ids": len(official_ids & local_ids),
        "official_only": len(official_only),
        "local_only": len(local_only),
        "title_mismatches": len(title_mismatches),
        "official_duplicate_ids": len(official_duplicates),
        "local_duplicate_ids": len(local_duplicates),
        "local_without_stable_id": len(invalid_local),
        "official_only_by_category": dict(
            Counter(str(row.get("flxz") or "空") for row in official_only).most_common()
        ),
        "warning": "官网索引无记录不能单独证明本地材料失效。",
    }
    (args.output / "flk_比对摘要.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
