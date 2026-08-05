#!/usr/bin/env python3
"""为全量官方索引核对创建与候选物理分离的工程记录批次。"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path


def _read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return reader.fieldnames or [], list(reader)


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _checksum_map(candidate_root: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in (candidate_root / "SHA256SUMS").read_text(
        encoding="utf-8"
    ).splitlines():
        digest, relative = line.split("  ", 1)
        checksums[relative] = digest
    return checksums


def _append_note(original: str, addition: str) -> str:
    if not original:
        return addition
    if addition in original:
        return original
    return original.rstrip("；。") + "；" + addition


def _refresh_snapshot(
    output_root: Path,
    current_dir: Path | None,
    meta_name: str,
    csv_name: str,
) -> None:
    if current_dir is None:
        return
    matches = list((output_root / "official_registry").rglob(meta_name))
    if len(matches) != 1:
        raise ValueError(f"{meta_name}目标快照数量不是1：{len(matches)}")
    destination = matches[0].parent
    shutil.copy2(current_dir / meta_name, destination / meta_name)
    shutil.copy2(current_dir / csv_name, destination / csv_name)


def _formal_source_urls(formal_root: Path | None) -> dict[str, str]:
    if formal_root is None:
        return {}
    values: dict[str, str] = {}
    for name in ("cases.csv", "practice_references.csv"):
        path = formal_root / name
        if not path.is_file():
            continue
        _, rows = _read_csv(path)
        for row in rows:
            if row.get("relative_path") and row.get("source_url"):
                values[row["relative_path"]] = row["source_url"]
    return values


def prepare_batch(
    base_engineering_root: Path,
    candidate_root: Path,
    comparison_csv: Path,
    output_root: Path,
    *,
    verified_at: str,
    formal_root: Path | None = None,
    npc_index_dir: Path | None = None,
    rules_index_dir: Path | None = None,
) -> dict:
    if output_root.exists():
        raise FileExistsError(f"工程批次目录已存在：{output_root}")
    shutil.copytree(base_engineering_root, output_root, copy_function=shutil.copy2)
    _, comparison = _read_csv(comparison_csv)
    comparison_by_source = {
        row.get("source_relative_path", ""): row
        for row in comparison
        if row.get("source_relative_path", "")
    }

    checksums = _checksum_map(candidate_root)
    manifest_path = output_root / "批次清单" / "Markdown派生清单.csv"
    manifest_fields, manifest_rows = _read_csv(manifest_path)
    manifest_updated = 0
    manifest_missing = 0
    for row in manifest_rows:
        digest = checksums.get(row.get("target_relative_path", ""))
        if not digest:
            manifest_missing += 1
            continue
        if row.get("derived_sha256") != digest:
            row["derived_sha256"] = digest
            manifest_updated += 1
    _write_csv(manifest_path, manifest_fields, manifest_rows)

    verification_path = output_root / "verification_results.csv"
    verification_fields, verification_rows = _read_csv(verification_path)
    verification_updated = 0
    for row in verification_rows:
        match = comparison_by_source.get(row.get("relative_path", ""))
        if not match:
            continue
        status = match.get("match_status", "")
        urls = [
            value
            for value in match.get("matched_official_urls", "").split("|")
            if value
        ]
        if status == "UNIQUE_OFFICIAL_INDEX_MATCH":
            if row.get("verification_status") in {
                "UNOFFICIAL_CANDIDATE",
                "UNMATCHED_OFFICIAL_INDEX",
                "SOURCE_CONFLICT",
            }:
                row["verification_status"] = "OFFICIAL_INDEX_METADATA_VERIFIED"
            if len(urls) == 1 and not row.get("official_source_url"):
                row["official_source_url"] = urls[0]
            row["identity_verified"] = "true"
            note = "2026-07-31全量官方索引唯一命中；不代表官方全文核验。"
        elif status == "MULTIPLE_OFFICIAL_INDEX_MATCH":
            if row.get("verification_status") == "UNOFFICIAL_CANDIDATE":
                row["verification_status"] = "SOURCE_CONFLICT"
            row["identity_verified"] = "false"
            note = "2026-07-31全量官方索引多重命中，禁止自动选定。"
        else:
            if row.get("verification_status") == "UNOFFICIAL_CANDIDATE":
                row["verification_status"] = "UNMATCHED_OFFICIAL_INDEX"
            note = "2026-07-31已执行全量官方索引匹配但未命中；不等于失效或非官方。"
        row["verified_at"] = verified_at
        row["note"] = _append_note(row.get("note", ""), note)
        verification_updated += 1
    _write_csv(verification_path, verification_fields, verification_rows)

    conflict_path = output_root / "conflicts.csv"
    conflict_fields, conflict_rows = _read_csv(conflict_path)
    existing = {
        (
            row.get("relative_path", ""),
            row.get("conflict_type", ""),
            row.get("other_value", ""),
        )
        for row in conflict_rows
    }
    formal_urls = _formal_source_urls(formal_root)
    conflicts_added = 0
    for match in comparison:
        source_path = match.get("source_relative_path", "")
        status = match.get("match_status", "")
        if status == "MULTIPLE_OFFICIAL_INDEX_MATCH":
            conflict = {
                "relative_path": source_path,
                "conflict_type": "MULTIPLE_OFFICIAL_INDEX_MATCH",
                "field_name": "official_record_id",
                "local_value": match.get("title", ""),
                "other_value": match.get("matched_record_ids", ""),
                "evidence": match.get("matched_official_urls", ""),
                "disposition": "RESOLVED_NO_AUTOMATIC_OVERWRITE",
            }
        elif status == "UNIQUE_OFFICIAL_INDEX_MATCH":
            matched_urls = [
                value
                for value in match.get("matched_official_urls", "").split("|")
                if value
            ]
            local_url = formal_urls.get(source_path, "")
            if len(matched_urls) != 1 or not local_url or local_url == matched_urls[0]:
                continue
            conflict = {
                "relative_path": source_path,
                "conflict_type": "SOURCE_URL_DIFFERENCE",
                "field_name": "source_url",
                "local_value": local_url,
                "other_value": matched_urls[0],
                "evidence": "本地正式表来源URL与本批唯一官方索引URL不同",
                "disposition": "RESOLVED_PRESERVE_LOCAL_SOURCE_URL",
            }
        else:
            continue
        key = (
            conflict["relative_path"],
            conflict["conflict_type"],
            conflict["other_value"],
        )
        if key not in existing:
            conflict_rows.append(conflict)
            existing.add(key)
            conflicts_added += 1
    _write_csv(conflict_path, conflict_fields, conflict_rows)

    _refresh_snapshot(
        output_root,
        npc_index_dir,
        "flk_official_index_meta.json",
        "flk_official_index.csv",
    )
    _refresh_snapshot(
        output_root,
        rules_index_dir,
        "official_index_meta.json",
        "official_index.csv",
    )
    return {
        "comparison_rows": len(comparison),
        "manifest_rows_updated": manifest_updated,
        "manifest_targets_missing": manifest_missing,
        "verification_rows_updated": verification_updated,
        "conflicts_added": conflicts_added,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-engineering-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--comparison-csv", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--verified-at", required=True)
    parser.add_argument("--formal-root", type=Path)
    parser.add_argument("--npc-index-dir", type=Path)
    parser.add_argument("--rules-index-dir", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = prepare_batch(
        args.base_engineering_root,
        args.candidate_root,
        args.comparison_csv,
        args.output_root,
        verified_at=args.verified_at,
        formal_root=args.formal_root,
        npc_index_dir=args.npc_index_dir,
        rules_index_dir=args.rules_index_dir,
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
