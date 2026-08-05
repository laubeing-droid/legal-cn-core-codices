#!/usr/bin/env python3
"""把唯一官方索引命中写入交换候选；不直接修改最终目录。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
from pathlib import Path


INCLUDED_ROOT_PREFIXES = {
    "01",
    "02",
    "03",
    "04",
    "05",
    "06",
    "07",
    "08",
    "09",
    "10",
    "80",
    "81",
    "82",
}


def _read_text_preserving_newlines(path: Path) -> str:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return file.read()


def _write_text_preserving_newlines(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        file.write(text)


def _set_front_matter_value(text: str, key: str, value: str) -> str:
    if not text.startswith("---"):
        raise ValueError("Markdown缺少Front Matter")
    newline = "\r\n" if "\r\n" in text[:1000] else "\n"
    closing = text.find(f"{newline}---{newline}", 3)
    if closing < 0:
        raise ValueError("Markdown Front Matter未闭合")
    encoded = json.dumps(value, ensure_ascii=False)
    pattern = re.compile(
        rf"(?m)^{re.escape(key)}:\s*.*(?:\r?\n|$)"
    )
    front = text[: closing + len(newline)]
    body = text[closing + len(newline) :]
    replacement = f"{key}: {encoded}{newline}"
    if pattern.search(front):
        front = pattern.sub(replacement, front, count=1)
    else:
        front += replacement
    return front + body


def _update_markdown(
    path: Path,
    row: dict,
    verified_at: str,
) -> bool:
    text = _read_text_preserving_newlines(path)
    original = text
    if row.get("current_verification_status") in {
        "UNOFFICIAL_CANDIDATE",
        "UNMATCHED_OFFICIAL_INDEX",
        "SOURCE_CONFLICT",
    }:
        text = _set_front_matter_value(
            text,
            "verification_status",
            "OFFICIAL_INDEX_METADATA_VERIFIED",
        )
    metadata = {
        "official_index_source_ids": row.get("matched_source_ids", ""),
        "official_record_ids": row.get("matched_record_ids", ""),
        "official_source_urls": row.get("matched_official_urls", ""),
        "official_index_verified_at": verified_at,
    }
    for key, value in metadata.items():
        if value:
            text = _set_front_matter_value(text, key, value)
    if text == original:
        return False
    _write_text_preserving_newlines(path, text)
    return True


def _update_url_table(
    path: Path,
    urls_by_source_path: dict[str, str],
) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows = list(reader)
        fields = reader.fieldnames or []
    if "relative_path" not in fields or "source_url" not in fields:
        return 0, 0
    updated = 0
    conflicts = 0
    for row in rows:
        official_url = urls_by_source_path.get(row["relative_path"], "")
        if not official_url:
            continue
        if not row["source_url"]:
            row["source_url"] = official_url
            updated += 1
        elif row["source_url"] != official_url:
            conflicts += 1
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return updated, conflicts


def _write_sha256sums(root: Path) -> int:
    rows: list[tuple[str, str]] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.name == "SHA256SUMS":
            continue
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append((relative, digest))
    rows.sort(key=lambda item: item[0])
    with (root / "SHA256SUMS").open("w", encoding="utf-8", newline="\n") as file:
        for relative, digest in rows:
            file.write(f"{digest}  {relative}\n")
    return len(rows)


def apply_verification(
    final_root: Path,
    comparison_csv: Path,
    candidate_root: Path,
    *,
    verified_at: str,
) -> dict:
    final_root = final_root.resolve()
    if candidate_root.exists():
        raise FileExistsError(f"候选目录已存在：{candidate_root}")
    shutil.copytree(final_root, candidate_root, copy_function=shutil.copy2)
    with comparison_csv.open(encoding="utf-8-sig", newline="") as file:
        comparison = list(csv.DictReader(file))

    markdown_updated = 0
    excluded_rows = 0
    urls_by_source_path: dict[str, str] = {}
    for row in comparison:
        if row.get("match_status") != "UNIQUE_OFFICIAL_INDEX_MATCH":
            continue
        local_path = Path(row["local_path"]).resolve()
        relative = local_path.relative_to(final_root)
        if relative.parts[0][:2] not in INCLUDED_ROOT_PREFIXES:
            excluded_rows += 1
            continue
        candidate_path = candidate_root / relative
        if _update_markdown(candidate_path, row, verified_at):
            markdown_updated += 1
        urls = [
            value
            for value in row.get("matched_official_urls", "").split("|")
            if value
        ]
        source_relative_path = row.get("source_relative_path", "")
        if len(urls) == 1 and source_relative_path:
            urls_by_source_path[source_relative_path] = urls[0]

    cases_updated, case_url_conflicts = _update_url_table(
        candidate_root / "cases.csv", urls_by_source_path
    )
    practice_updated, practice_url_conflicts = _update_url_table(
        candidate_root / "practice_references.csv", urls_by_source_path
    )
    sha256_entries = _write_sha256sums(candidate_root)
    return {
        "comparison_rows": len(comparison),
        "markdown_updated": markdown_updated,
        "excluded_rows": excluded_rows,
        "cases_source_urls_updated": cases_updated,
        "practice_source_urls_updated": practice_updated,
        "source_url_conflicts": case_url_conflicts + practice_url_conflicts,
        "sha256_entries": sha256_entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--final-root", type=Path, required=True)
    parser.add_argument("--comparison-csv", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--verified-at", required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = apply_verification(
        args.final_root,
        args.comparison_csv,
        args.candidate_root,
        verified_at=args.verified_at,
    )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
