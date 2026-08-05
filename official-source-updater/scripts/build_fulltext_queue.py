#!/usr/bin/env python3
"""Build a bounded single-page queue from current official indexes and formal identities."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path


maximum_csv_field_size = sys.maxsize
while True:
    try:
        csv.field_size_limit(maximum_csv_field_size)
        break
    except OverflowError:
        maximum_csv_field_size //= 10


FIELDS = [
    "source_id",
    "record_id",
    "title",
    "publication_date",
    "category",
    "publisher",
    "official_url",
    "catalog_url",
    "selection_status",
]


def normalize_date(value: str) -> str:
    parts = re.findall(r"\d+", value or "")
    if len(parts) < 3:
        return ""
    return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"


def normalize_title(value: str) -> str:
    return re.sub(r"[\s·•，。、“”‘’：《》〈〉（）()【】\[\]_-]", "", value or "")


def in_update_scope(row: dict[str, str]) -> tuple[bool, str]:
    source_id = row.get("source_id", "")
    category = row.get("category", "")
    title = row.get("title", "")
    if source_id == "state_council_policy_database":
        if category != "国务院文件":
            return False, "OUT_OF_SCOPE_POLICY_MATERIAL"
    elif source_id == "state_council_gazette":
        if re.search(r"任免人员|主旨讲话", title):
            return False, "OUT_OF_SCOPE_GAZETTE_MATERIAL"
        if not re.search(r"通知|规定|条例|办法|标准|意见|批复|决定|规划|方案", title):
            return False, "OUT_OF_SCOPE_GAZETTE_MATERIAL"
    elif source_id == "spc_website":
        if category not in {"司法解释", "指导性案例", "典型案例"}:
            return False, "OUT_OF_SCOPE_SPC_MATERIAL"
    elif source_id == "spp_website":
        if category not in {"司法解释", "规范文件", "指导性案例", "典型案例"}:
            return False, "OUT_OF_SCOPE_SPP_MATERIAL"
    elif source_id == "moj_legal_service_case_database":
        if category != "仲裁案例":
            return False, "OUT_OF_SCOPE_MOJ_CASE"
    return True, ""


def select_incremental_rows(
    rows: list[dict[str, str]],
    formal_identities: set[tuple[str, str]],
    *,
    overlap_start: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    selected: list[dict[str, str]] = []
    excluded: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    normalized_formal = {
        (normalize_title(title), normalize_date(date))
        for title, date in formal_identities
    }
    canonical_spp_guiding_batches = {
        match.group(0)
        for row in rows
        if row.get("source_id") == "spp_website"
        and row.get("category") == "指导性案例"
        for match in [re.search(r"第[零〇一二三四五六七八九十百]+批指导性案例", row.get("title", ""))]
        if match
    }
    for original in rows:
        row = {field: str(original.get(field) or "").strip() for field in FIELDS[:-1]}
        row["publication_date"] = normalize_date(row["publication_date"])
        allowed, reason = in_update_scope(row)
        if not allowed:
            row["selection_status"] = reason
            excluded.append(row)
            continue
        spp_batch = re.search(
            r"第[零〇一二三四五六七八九十百]+批指导性案例", row["title"]
        )
        if (
            row["source_id"] == "spp_website"
            and row["category"] != "指导性案例"
            and spp_batch
            and spp_batch.group(0) in canonical_spp_guiding_batches
        ):
            row["selection_status"] = "DUPLICATE_PRESS_RELEASE"
            excluded.append(row)
            continue
        if not row["official_url"].startswith(("http://", "https://")):
            row["selection_status"] = "INVALID_OFFICIAL_URL"
            excluded.append(row)
            continue
        if row["official_url"] in seen_urls:
            row["selection_status"] = "DUPLICATE_OFFICIAL_URL"
            excluded.append(row)
            continue
        seen_urls.add(row["official_url"])
        bounded_undated = row["source_id"] == "moj_legal_service_case_database"
        if not bounded_undated and (
            not row["publication_date"] or row["publication_date"] < overlap_start
        ):
            row["selection_status"] = "HISTORICAL_BACKFILL_NOT_REQUESTED"
            excluded.append(row)
            continue
        identity = (normalize_title(row["title"]), row["publication_date"])
        if identity in normalized_formal:
            row["selection_status"] = "ALREADY_INGESTED"
            excluded.append(row)
            continue
        row["selection_status"] = "PENDING_SINGLE_PAGE_FULLTEXT"
        selected.append(row)
    return selected, excluded


def read_formal_identities(formal_root: Path) -> set[tuple[str, str]]:
    identities: set[tuple[str, str]] = set()
    specifications = (
        ("legal_documents.csv", "BT", "GBRQ"),
        ("cases.csv", "title", "publication_date"),
        ("practice_references.csv", "title", "publication_date"),
    )
    for filename, title_field, date_field in specifications:
        path = formal_root / filename
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                identities.add((row.get(title_field, ""), row.get(date_field, "")))
    return identities


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-index", action="append", type=Path, required=True)
    parser.add_argument("--formal-root", type=Path, required=True)
    parser.add_argument("--overlap-start", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows: list[dict[str, str]] = []
    for path in args.source_index:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows.extend(csv.DictReader(stream))
    selected, excluded = select_incremental_rows(
        rows,
        read_formal_identities(args.formal_root),
        overlap_start=args.overlap_start,
    )
    write_csv(args.output / "single_page_fulltext_queue.csv", selected)
    write_csv(args.output / "selection_exclusions.csv", excluded)
    print(f"selected={len(selected)} excluded={len(excluded)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
