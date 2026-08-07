#!/usr/bin/env python3
"""Build deterministic GitHub Release assets for one validated dataset tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
import zipfile
from pathlib import Path
from typing import Any


RELEASE_SOURCE_FILES = (
    "legal_contents.csv",
    "legal_documents.csv",
    "case_holdings.csv",
    "case_legal_references.csv",
    "cases.csv",
    "practice_references.csv",
    "legal_relations.csv",
    "legal_sources.csv",
    "SHA256SUMS",
)
COMPRESSED_SOURCE_FILES = frozenset({"legal_contents.csv", "legal_documents.csv"})
MANIFEST_NAME = "dataset-manifest.json"
RELEASE_CHECKSUMS_NAME = "release-SHA256SUMS"
RELEASE_NOTES_NAME = "release-notes.md"
HEX_64 = re.compile(r"[0-9a-f]{64}")
HEX_40 = re.compile(r"[0-9a-f]{40}")
SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9._-]+")
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def parse_candidate_checksums(path: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line:
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ValueError(f"SOURCE_SHA256SUMS_FORMAT:{line_number}")
        digest, relative_path = match.groups()
        normalized = relative_path.replace("\\", "/")
        if normalized in checksums:
            raise ValueError(f"SOURCE_SHA256SUMS_DUPLICATE:{normalized}")
        checksums[normalized] = digest
    return checksums


def write_deterministic_zip(source: Path, destination: Path) -> None:
    info = zipfile.ZipInfo(source.name, ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    with zipfile.ZipFile(
        destination,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        allowZip64=True,
    ) as archive:
        with source.open("rb") as input_file, archive.open(
            info,
            mode="w",
            force_zip64=True,
        ) as output_file:
            shutil.copyfileobj(input_file, output_file, length=1024 * 1024)


def load_validation_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("status") != "LOCAL_FULLY_VALIDATED" or report.get("blocking_counts"):
        raise ValueError("VALIDATION_NOT_ACCEPTED")
    tree_sha256 = str(report.get("artifact_tree_sha256", "")).lower()
    if not HEX_64.fullmatch(tree_sha256):
        raise ValueError("VALIDATION_TREE_SHA256_INVALID")
    table_rows = report.get("statistics", {}).get("table_rows", {})
    for name in RELEASE_SOURCE_FILES:
        if name.endswith(".csv") and not isinstance(table_rows.get(name), int):
            raise ValueError(f"VALIDATION_ROW_COUNT_MISSING:{name}")
    return report


def assert_safe_identifier(value: str, field_name: str) -> None:
    if not SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field_name}_INVALID")


def prepare_release(
    *,
    candidate: Path,
    validation_report_path: Path,
    output_directory: Path,
    engineering_batch: str,
    commit_sha: str,
    run_id: str,
) -> dict[str, object]:
    candidate = candidate.resolve()
    validation_report_path = validation_report_path.resolve()
    output_directory = output_directory.resolve()
    if not candidate.is_dir():
        raise ValueError("CANDIDATE_NOT_FOUND")
    if output_directory.exists():
        raise ValueError("RELEASE_OUTPUT_ALREADY_EXISTS")
    assert_safe_identifier(engineering_batch, "ENGINEERING_BATCH")
    assert_safe_identifier(run_id, "RUN_ID")
    commit_sha = commit_sha.lower()
    if not HEX_40.fullmatch(commit_sha):
        raise ValueError("COMMIT_SHA_INVALID")

    report = load_validation_report(validation_report_path)
    tree_sha256 = str(report["artifact_tree_sha256"]).lower()
    tag = f"dataset-{tree_sha256[:16]}"
    source_checksums_path = candidate / "SHA256SUMS"
    if not source_checksums_path.is_file():
        raise ValueError("SOURCE_SHA256SUMS_MISSING")
    candidate_checksums = parse_candidate_checksums(source_checksums_path)

    source_metadata: dict[str, dict[str, object]] = {}
    for name in RELEASE_SOURCE_FILES:
        source = candidate / name
        if not source.is_file():
            raise ValueError(f"RELEASE_SOURCE_MISSING:{name}")
        raw_sha256 = sha256_file(source)
        if name != "SHA256SUMS" and candidate_checksums.get(name) != raw_sha256:
            raise ValueError(f"SOURCE_SHA256_MISMATCH:{name}")
        source_metadata[name] = {
            "raw_size": source.stat().st_size,
            "raw_sha256": raw_sha256,
        }

    staging = output_directory.parent / f".{output_directory.name}.staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    try:
        manifest_files: list[dict[str, object]] = []
        payload_assets: list[Path] = []
        table_rows = report["statistics"]["table_rows"]
        for name in RELEASE_SOURCE_FILES:
            source = candidate / name
            if name in COMPRESSED_SOURCE_FILES:
                asset_name = f"{name}.zip"
                compression = "zip-deflate-9"
                destination = staging / asset_name
                write_deterministic_zip(source, destination)
            else:
                asset_name = name
                compression = "none"
                destination = staging / asset_name
                shutil.copyfile(source, destination)
            asset_sha256 = sha256_file(destination)
            asset_size = destination.stat().st_size
            payload_assets.append(destination)
            entry: dict[str, object] = {
                "source_name": name,
                **source_metadata[name],
                "asset_name": asset_name,
                "asset_size": asset_size,
                "asset_sha256": asset_sha256,
                "compression": compression,
            }
            if name.endswith(".csv"):
                entry["row_count"] = table_rows[name]
            manifest_files.append(entry)

        manifest = {
            "manifest_schema_version": 1,
            "dataset": {
                "schema_version": report.get("schema_version", ""),
                "validation_status": "LOCAL_FULLY_VALIDATED",
                "tree_sha256": tree_sha256,
                "source_sha256sums_sha256": source_metadata["SHA256SUMS"]["raw_sha256"],
                "engineering_batch": engineering_batch,
            },
            "release": {
                "tag": tag,
                "commit_sha": commit_sha,
                "run_id": run_id,
            },
            "files": manifest_files,
        }
        manifest_path = staging / MANIFEST_NAME
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        checksummed_assets = [*payload_assets, manifest_path]
        release_checksums_path = staging / RELEASE_CHECKSUMS_NAME
        release_checksums_path.write_text(
            "".join(
                f"{sha256_file(path)}  {path.name}\n"
                for path in sorted(checksummed_assets, key=lambda item: item.name)
            ),
            encoding="utf-8",
            newline="\n",
        )
        notes_path = staging / RELEASE_NOTES_NAME
        notes_path.write_text(
            "# 中国法律法规标准化数据集\n\n"
            f"- 数据树 SHA-256：`{tree_sha256}`\n"
            f"- Schema：`{report.get('schema_version', '')}`\n"
            f"- 工程批次：`{engineering_batch}`\n"
            f"- Workflow run：`{run_id}`\n\n"
            "两个超大表分别使用 ZIP/DEFLATE 压缩；其余正式表保持 CSV 原文件。"
            "下载后使用 `release-SHA256SUMS` 验证 Release 资产。\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(staging, output_directory)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    release_asset_names = [
        *(path.name for path in payload_assets),
        MANIFEST_NAME,
        RELEASE_CHECKSUMS_NAME,
    ]
    return {
        "status": "RELEASE_ASSETS_PREPARED",
        "tag": tag,
        "tree_sha256": tree_sha256,
        "output_directory": str(output_directory),
        "notes_path": str(output_directory / RELEASE_NOTES_NAME),
        "asset_names": release_asset_names,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--validation-report", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--engineering-batch", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    result = prepare_release(
        candidate=args.candidate,
        validation_report_path=args.validation_report,
        output_directory=args.output_directory,
        engineering_batch=args.engineering_batch,
        commit_sha=args.commit_sha,
        run_id=args.run_id,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
