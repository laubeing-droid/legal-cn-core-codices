#!/usr/bin/env python3
"""通用官方索引与正式区标题/官方链接比对；只输出候选清单。"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


def normalize_title(value: str) -> str:
    value = re.sub(r"^(?:有效|失效|废止|已修改|尚未生效|未知)[_— -]+", "", value)
    return re.sub(r"[\s·•，。、“”‘’：《》〈〉（）()【】\[\]_-]", "", value).lower()


def local_rows(directories: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for directory in directories:
        for path in directory.rglob("*.md"):
            text = path.read_text(encoding="utf-8-sig", errors="replace")[:12000]
            title_match = re.search(
                r"(?m)^(?:title|案例标题):\s*[\"']?(.*?)[\"']?\s*$",
                text,
            )
            title = title_match.group(1).strip() if title_match else path.stem
            urls = re.findall(r"https://[^\s\"'<>)\]]+", text)
            rows.append(
                {
                    "title": title,
                    "normalized_title": normalize_title(title),
                    "official_urls": "|".join(urls),
                    "local_path": str(path),
                }
            )
    return rows


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
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

    with args.official_csv.open(encoding="utf-8-sig", newline="") as file:
        official = list(csv.DictReader(file))
    local = local_rows(args.formal_dir)
    local_titles = {row["normalized_title"] for row in local}
    official_titles = {normalize_title(row["title"]) for row in official}
    official_urls = {row["official_url"] for row in official if row["official_url"]}

    official_only = [
        {**row, "match_basis": "无规范化同标题"}
        for row in official
        if normalize_title(row["title"]) not in local_titles
    ]
    local_only = [
        {**row, "note": "官网栏目索引未命中不等于失效或非官方"}
        for row in local
        if row["normalized_title"] not in official_titles
        and not any(url in official_urls for url in row["official_urls"].split("|") if url)
    ]
    write_csv(
        args.output / "官网有_正式区未命中候选.csv",
        list(official[0].keys()) + ["match_basis"] if official else ["match_basis"],
        official_only,
    )
    write_csv(
        args.output / "正式区有_官网索引未命中复核.csv",
        ["title", "normalized_title", "official_urls", "local_path", "note"],
        local_only,
    )
    summary = {
        "official_rows": len(official),
        "local_markdown": len(local),
        "official_only_candidates": len(official_only),
        "local_only_review": len(local_only),
    }
    (args.output / "比对摘要.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
