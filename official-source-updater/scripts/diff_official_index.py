#!/usr/bin/env python3
"""Create event-driven single-page verification queues from two complete official indexes."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


COMPARE_FIELDS = (
    "title",
    "publication_date",
    "category",
    "publisher",
    "official_url",
    "catalog_url",
)
EVENT_FIELDS = [
    "source_id",
    "record_id",
    "event_type",
    "official_url",
    "title",
    "publication_date",
    "old_snapshot",
    "new_snapshot",
    "request_kind",
    "verification_status",
]


def _snapshot(row: dict[str, str]) -> str:
    return json.dumps(
        {field: str(row.get(field) or "").strip() for field in COMPARE_FIELDS},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _group(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        record_id = str(row.get("record_id") or "").strip()
        if record_id:
            grouped[record_id].append(row)
    return grouped


def _event(
    source_id: str,
    record_id: str,
    event_type: str,
    row: dict[str, str],
    *,
    old_snapshot: str = "",
    new_snapshot: str = "",
) -> dict[str, str]:
    return {
        "source_id": source_id,
        "record_id": record_id,
        "event_type": event_type,
        "official_url": str(row.get("official_url") or "").strip(),
        "title": str(row.get("title") or "").strip(),
        "publication_date": str(row.get("publication_date") or "").strip(),
        "old_snapshot": old_snapshot,
        "new_snapshot": new_snapshot,
        "request_kind": "single_page" if event_type in {"NEW", "CHANGED", "CONFLICT"} else "none",
        "verification_status": "PENDING_SINGLE_PAGE" if event_type in {"NEW", "CHANGED", "CONFLICT"} else "REMOVED_FROM_INDEX",
    }


def diff_indexes(
    old_rows: list[dict[str, str]],
    new_rows: list[dict[str, str]],
    *,
    source_id: str,
    overlap_start: str = "",
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    old = _group(old_rows)
    new = _group(new_rows)
    events: list[dict[str, str]] = []

    for record_id in sorted(set(old) | set(new)):
        old_matches = old.get(record_id, [])
        new_matches = new.get(record_id, [])
        old_snapshots = {_snapshot(row) for row in old_matches}
        new_snapshots = {_snapshot(row) for row in new_matches}
        if len(new_snapshots) > 1:
            for row in new_matches:
                events.append(
                    _event(
                        source_id,
                        record_id,
                        "CONFLICT",
                        row,
                        old_snapshot="|".join(sorted(old_snapshots)),
                        new_snapshot=_snapshot(row),
                    )
                )
        elif not old_matches and new_matches:
            row = new_matches[0]
            events.append(_event(source_id, record_id, "NEW", row, new_snapshot=_snapshot(row)))
        elif old_matches and not new_matches:
            row = old_matches[0]
            events.append(_event(source_id, record_id, "REMOVED", row, old_snapshot=_snapshot(row)))
        elif old_snapshots != new_snapshots:
            row = new_matches[0]
            events.append(
                _event(
                    source_id,
                    record_id,
                    "CHANGED",
                    row,
                    old_snapshot="|".join(sorted(old_snapshots)),
                    new_snapshot=_snapshot(row),
                )
            )

    if overlap_start:
        for row in events:
            if row["event_type"] not in {"NEW", "CHANGED", "CONFLICT"}:
                continue
            match = re.search(r"\d{4}[-./]\d{2}[-./]\d{2}", row["publication_date"])
            published = match.group().replace(".", "-").replace("/", "-") if match else ""
            if not published or published < overlap_start:
                row["request_kind"] = "none"
                row["verification_status"] = "HISTORICAL_BACKFILL_CANDIDATE"

    queue = []
    for row in events:
        parsed = urlparse(row["official_url"])
        if row["request_kind"] == "single_page" and parsed.scheme in {"http", "https"} and parsed.netloc:
            queue.append(row)
    return events, queue


def write_diff(
    old_rows: list[dict[str, str]],
    new_rows: list[dict[str, str]],
    output_dir: Path,
    *,
    source_id: str,
    overlap_start: str = "",
) -> dict[str, object]:
    events, queue = diff_indexes(
        old_rows, new_rows, source_id=source_id, overlap_start=overlap_start
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, rows in (
        ("index_events.csv", events),
        ("single_page_verification_queue.csv", queue),
    ):
        with (output_dir / filename).open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=EVENT_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    (output_dir / "single_page_verification_queue.json").write_text(
        json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    counts = Counter(row["event_type"] for row in events)
    changed_common_ids = {
        row["record_id"]
        for row in events
        if row["event_type"] in {"CHANGED", "CONFLICT"}
    }
    summary = {
        "source_id": source_id,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "old_rows": len(old_rows),
        "new_rows": len(new_rows),
        "events": len(events),
        "event_counts": dict(sorted(counts.items())),
        "single_page_queue": len(queue),
        "historical_backfill_candidates": sum(
            row["verification_status"] == "HISTORICAL_BACKFILL_CANDIDATE" for row in events
        ),
        "overlap_start": overlap_start,
        "unchanged_cache_hits": len(set(_group(old_rows)) & set(_group(new_rows))) - len(changed_common_ids),
    }
    (output_dir / "index_diff_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overlap-start", default="")
    args = parser.parse_args()
    summary = write_diff(
        _read_csv(args.old),
        _read_csv(args.new),
        args.output,
        source_id=args.source,
        overlap_start=args.overlap_start,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
