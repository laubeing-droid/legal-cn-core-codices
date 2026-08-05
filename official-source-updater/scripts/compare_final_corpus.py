#!/usr/bin/env python3
"""将多个官方索引合并后，对指定最终内容目录逐文件核对。"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path


OUTPUT_FIELDS = [
    "local_path",
    "title",
    "normalized_title",
    "source_relative_path",
    "local_url_count",
    "object_type",
    "current_verification_status",
    "match_status",
    "match_basis",
    "match_count",
    "matched_source_ids",
    "matched_record_ids",
    "matched_official_urls",
    "matched_publication_dates",
    "note",
]


def normalize_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", html.unescape(value or "")).strip()
    prefix = re.compile(
        r"^(?:"
        r"[（(](?:已记录|不再参照适用|现行有效|已废止|已失效)[）)]"
        r"|(?:有效|失效|废止|已废止|已失效|已修改|尚未生效|尚未施行|未知)"
        r"[_—\-\s]+"
        r")"
    )
    previous = None
    while text != previous:
        previous = text
        text = prefix.sub("", text).strip()
    return re.sub(
        r"[\s·•，。、“”‘’：《》〈〉（）()【】\[\]_\-—:：;；,]",
        "",
        text,
    ).lower()


def _front_matter_value(header: str, key: str) -> str:
    match = re.search(
        rf"(?m)^{re.escape(key)}:\s*[\"']?(.*?)[\"']?\s*$",
        header,
    )
    return match.group(1).strip() if match else ""


def local_rows(
    directories: list[Path],
    source_root: Path | None = None,
) -> list[dict]:
    rows: list[dict] = []
    seen: set[Path] = set()
    for directory in directories:
        for path in directory.rglob("*.md"):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            with path.open("r", encoding="utf-8-sig", errors="strict") as file:
                header = file.read(16000)
            title = (
                _front_matter_value(header, "title")
                or _front_matter_value(header, "案例标题")
                or path.stem
            )
            urls = sorted(
                set(re.findall(r"https?://[^\s\"'<>)\]]+", header))
            )
            source_relative_path = _front_matter_value(
                header, "source_relative_path"
            )
            if source_root and source_relative_path:
                source_path = (source_root / Path(source_relative_path)).resolve()
                try:
                    source_path.relative_to(source_root.resolve())
                except ValueError:
                    source_path = Path()
                if source_path.is_file():
                    with source_path.open(
                        "r", encoding="utf-8-sig", errors="strict"
                    ) as source_file:
                        source_header = source_file.read(24000)
                    urls = sorted(
                        set(
                            [
                                *urls,
                                *re.findall(
                                    r"https?://[^\s\"'<>)\]]+", source_header
                                ),
                            ]
                        )
                    )
            rows.append(
                {
                    "local_path": str(path),
                    "title": title,
                    "normalized_title": normalize_title(title),
                    "object_type": _front_matter_value(header, "object_type"),
                    "current_verification_status": _front_matter_value(
                        header, "verification_status"
                    ),
                    "local_urls": urls,
                    "source_relative_path": source_relative_path,
                    "local_url_count": len(urls),
                }
            )
            stable_id_text = " ".join(
                [rows[-1]["source_relative_path"], *rows[-1]["local_urls"]]
            )
            rows[-1]["local_stable_ids"] = sorted(
                set(re.findall(r"(?i)(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])", stable_id_text))
            )
            rows[-1]["local_dates"] = sorted(
                set(
                    re.findall(
                        r"(?<!\d)(?:19|20)\d{2}-\d{2}-\d{2}(?!\d)",
                        f"{path.stem} {rows[-1]['source_relative_path']}",
                    )
                )
            )
    return rows


def official_rows(paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                if row.get("bbbs"):
                    row = {
                        **row,
                        "source_id": "npc_flk",
                        "record_id": row.get("bbbs", ""),
                        "publication_date": row.get("gbrq", ""),
                        "category": row.get("flxz", ""),
                        "publisher": row.get("zdjgName", ""),
                        "official_url": (
                            "https://flk.npc.gov.cn/detail?id=" + row.get("bbbs", "")
                        ),
                        "catalog_url": "https://flk.npc.gov.cn/",
                    }
                key = (
                    row.get("source_id", ""),
                    row.get("record_id", ""),
                    row.get("official_url", ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                row["normalized_title"] = normalize_title(row.get("title", ""))
                rows.append(row)
    return rows


def _joined(matches: list[dict], key: str) -> str:
    return "|".join(sorted({row.get(key, "") for row in matches if row.get(key, "")}))


def _normalized_dates(*values: str) -> set[str]:
    dates: set[str] = set()
    for value in values:
        for year, month, day in re.findall(
            r"(?<!\d)((?:19|20)\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)",
            value or "",
        ):
            dates.add(f"{year}-{int(month):02d}-{int(day):02d}")
    return dates


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def compare_corpus(
    official_csvs: list[Path],
    formal_directories: list[Path],
    output: Path,
    source_root: Path | None = None,
) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    official = official_rows(official_csvs)
    by_title: dict[str, list[dict]] = defaultdict(list)
    by_url: dict[str, list[dict]] = defaultdict(list)
    by_record_id: dict[str, list[dict]] = defaultdict(list)
    for row in official:
        if row["normalized_title"]:
            by_title[row["normalized_title"]].append(row)
        if row.get("official_url"):
            by_url[row["official_url"]].append(row)
        if row.get("record_id"):
            by_record_id[row["record_id"].lower()].append(row)

    results: list[dict] = []
    counts = defaultdict(int)
    for local in local_rows(formal_directories, source_root=source_root):
        url_matches: list[dict] = []
        for url in local["local_urls"]:
            url_matches.extend(by_url.get(url, []))
        id_matches: list[dict] = []
        for record_id in local["local_stable_ids"]:
            id_matches.extend(by_record_id.get(record_id.lower(), []))
        title_matches = by_title.get(local["normalized_title"], [])
        if url_matches:
            matches = url_matches
            match_basis = "OFFICIAL_URL"
        elif id_matches:
            matches = id_matches
            match_basis = "OFFICIAL_STABLE_ID"
        else:
            matches = title_matches
            match_basis = "NORMALIZED_TITLE"
        deduplicated: dict[tuple[str, str, str], dict] = {}
        for row in matches:
            key = (
                row.get("source_id", ""),
                row.get("record_id", ""),
                row.get("official_url", ""),
            )
            deduplicated[key] = row
        matches = list(deduplicated.values())
        if (
            len(matches) > 1
            and match_basis == "NORMALIZED_TITLE"
            and local["local_dates"]
        ):
            local_dates = _normalized_dates(*local["local_dates"])
            dated = [
                row
                for row in matches
                if local_dates
                & _normalized_dates(
                    row.get("publication_date", ""),
                    row.get("official_url", ""),
                )
            ]
            if dated:
                matches = dated
                match_basis = "NORMALIZED_TITLE_AND_DATE"
        record_ids = {row.get("record_id", "") for row in matches}
        dates = {
            date
            for row in matches
            for date in _normalized_dates(
                row.get("publication_date", ""),
                row.get("official_url", ""),
            )
        }
        cross_source_same_item = bool(
            len(matches) > 1
            and (
                (len(record_ids) == 1 and "" not in record_ids)
                or (len(dates) == 1 and "" not in dates)
            )
        )
        if not matches:
            status = "UNMATCHED_OFFICIAL_INDEX"
            note = "已执行本批官方索引匹配；未命中不等于失效或非官方。"
            counts["unmatched"] += 1
        elif len(matches) == 1 or url_matches or id_matches or cross_source_same_item:
            status = "UNIQUE_OFFICIAL_INDEX_MATCH"
            note = (
                "官方URL命中。"
                if url_matches
                else (
                    "官方稳定ID命中。"
                    if id_matches
                    else "规范化标题及日期在本批合并官方索引中唯一确定。"
                )
            )
            counts["unique_matches"] += 1
        else:
            status = "MULTIPLE_OFFICIAL_INDEX_MATCH"
            note = "同一规范化标题命中多个官方记录，禁止自动选定。"
            counts["ambiguous_matches"] += 1
        results.append(
            {
                **local,
                "match_status": status,
                "match_basis": match_basis,
                "match_count": len(matches),
                "matched_source_ids": _joined(matches, "source_id"),
                "matched_record_ids": _joined(matches, "record_id"),
                "matched_official_urls": _joined(matches, "official_url"),
                "matched_publication_dates": _joined(matches, "publication_date"),
                "note": note,
            }
        )
    results.sort(key=lambda row: row["local_path"])
    write_csv(output / "全量文件核对结果.csv", results)
    summary = {
        "official_csvs": len(official_csvs),
        "official_rows": len(official),
        "formal_directories": len(formal_directories),
        "local_markdown": len(results),
        "unique_matches": counts["unique_matches"],
        "ambiguous_matches": counts["ambiguous_matches"],
        "unmatched": counts["unmatched"],
    }
    (output / "全量文件核对摘要.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--official-csv", type=Path, action="append", required=True)
    parser.add_argument("--formal-dir", type=Path, action="append", required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    missing = [
        str(path)
        for path in [*args.official_csv, *args.formal_dir]
        if not path.exists()
    ]
    if missing:
        parser.error("路径不存在：" + ", ".join(missing))
    summary = compare_corpus(
        args.official_csv,
        args.formal_dir,
        args.output,
        source_root=args.source_root,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
