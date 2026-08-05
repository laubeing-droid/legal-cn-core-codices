#!/usr/bin/env python3
"""Validate a generated local dataset before any atomic publication."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

csv.field_size_limit(min(sys.maxsize, 2_147_483_647))

FORMAL_TABLES = {
    "legal_documents.csv",
    "legal_contents.csv",
    "legal_relations.csv",
    "legal_sources.csv",
    "cases.csv",
    "case_holdings.csv",
    "case_legal_references.csv",
    "practice_references.csv",
}
ENGINEERING_TABLES = {
    "source_records.csv",
    "ingest_queue.csv",
    "verification_results.csv",
    "conflicts.csv",
    "validation_errors.csv",
}
ACCEPTED_VERIFICATION = {
    "STANDARD_CONFORMANT_ORIGINAL",
    "OFFICIAL_CONTENT_VERIFIED_DERIVED",
    "OFFICIAL_FULLTEXT_VERIFIED",
    "OFFICIAL_INDEX_METADATA_VERIFIED",
    "METADATA_ONLY",
    "SOURCE_CONFLICT",
    "BLOCKED_ACCESS",
    "UNOFFICIAL_CANDIDATE",
    "UNMATCHED_OFFICIAL_INDEX",
    "UNVERIFIED_LOCAL",
}
PUBLICATION_SKIP_HEADER = [
    "relative_path",
    "skip_code",
    "status",
    "approved_on",
    "rationale",
]
PUBLICATION_SKIP_RULES = {
    "MISSING_OFFICIAL_DECISION_ORDER": {
        "queue_status": "SKIPPED_FORMAL_EXPORT_MISSING_OFFICIAL_DECISION_ORDER",
        "warning_code": "SKIPPED_MISSING_OFFICIAL_DECISION_ORDER",
    },
    "CONTENT_STRUCTURE_UNREPRESENTABLE": {
        "queue_status": "SKIPPED_FORMAL_EXPORT_CONTENT_STRUCTURE_UNREPRESENTABLE",
        "warning_code": "SKIPPED_CONTENT_STRUCTURE_UNREPRESENTABLE",
    },
}
DEFAULT_SOURCE_ROOT = (
    Path(__file__).resolve().parent.parent
    / "workspace"
    / "source"
    / "legal-references"
)


def is_resolved_conflict(disposition: str) -> bool:
    return (
        disposition
        in {
            "RESOLVED",
            "EXCLUDED",
            "USE_OFFICIAL_INDEX_METADATA",
            "MIGRATED_WITH_READABLE_VERSION_SUFFIX",
            "PRIMARY_DOCUMENT_ONLY_DERIVED",
        }
        or disposition.startswith("EXCLUDED_")
        or disposition.startswith("RESOLVED_")
    )
GBT47277_CATEGORIES = {
    "0000", "0100", "0200", "0300", "0400", "0500", "0600", "0700",
    "0800", "0901", "0902", "0903", "1000", "1100", "1200", "1300",
    "1400", "1500",
}
GBT47277_FILE_TYPES = {"00", "10", "20", "30", "40"}
CASE_ID_PATTERNS = [
    re.compile(r"^(?:检例第|指导案例)\d+号$"),
    re.compile(r"^D?\d{4}(?:-\d{1,3}){3}-\d{3}$"),
    re.compile(r"^[A-Z]{5,8}\d{10}$"),
]
ABSOLUTE_PATH = re.compile(r"(?:^|[\s(\"'`])(?:[A-Za-z]:[\\/])", re.MULTILINE)
POLLUTION = re.compile(
    r"本文由律锥[·・]?\s*Legalskill|智法AI|云法律网|^\s*-\s*IMA(?:知识库|条目ID)\s*[：:]",
    re.I | re.M,
)
PERSONAL_OR_INTERMEDIATE = re.compile(
    r"Obsidian|模型摘要|向量(?:库|数据)|个人笔记|交换候选",
    re.I,
)
NON_MARKDOWN_DOCUMENT_SUFFIXES = {".docx", ".pdf", ".ofd", ".uof"}
FINAL_TOP_LEVEL_DIRECTORIES = {
    "00_法律检索导航与效力适用规则",
    "01_宪法",
    "02_法律",
    "03_行政法规",
    "04_监察法规",
    "05_地方立法",
    "06_规章",
    "07_司法解释【独立规范类型】",
    "08_其他规范性文件【非立法】",
    "09_司法机关其他规范性文件【非司法解释】",
    "10_司法业务指导、会议纪要与公开答疑【非规范性法源】",
    "80_司法部仲裁案例【参考性、非规范性法源】",
    "81_最高人民法院公开案例【非规范性法源】",
    "82_最高人民检察院公开案例【非规范性法源】",
    "89_人民法院案例库入库参考案例【本地人工更新】",
}
FINAL_TOP_LEVEL_FILES = FORMAL_TABLES | {"README.md", "SHA256SUMS"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def filesystem_path(path: Path) -> Path:
    """Return a Windows extended-length path without changing its identity."""
    if os.name != "nt":
        return path
    absolute = os.path.abspath(str(path))
    if absolute.startswith("\\\\?\\"):
        return Path(absolute)
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute.lstrip("\\"))
    return Path("\\\\?\\" + absolute)


def valid_case_id(value: str) -> bool:
    if not value:
        return True
    if re.fullmatch(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", value):
        return False
    if re.fullmatch(r"[0-9a-fA-F]{32,64}", value) or value.lower().startswith("ima-"):
        return False
    return any(pattern.fullmatch(value) for pattern in CASE_ID_PATTERNS)


def load_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    raw = path.read_bytes()
    if not raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("CSV_MISSING_UTF8_BOM")
    text = raw.decode("utf-8-sig", errors="strict")
    reader = csv.DictReader(text.splitlines(keepends=True))
    header = reader.fieldnames or []
    rows = list(reader)
    if any(None in row for row in rows):
        raise ValueError("CSV_COLUMN_COUNT_MISMATCH")
    return header, rows


def validate_legal_contents_stream(
    path: Path,
    table_schema: dict,
    parent_file_codes: set[str],
    result: Result,
) -> tuple[list[str], int, set[str]]:
    """Validate the largest formal table without materializing it in memory."""
    seen_keys: set[tuple[str, str]] = set()
    content_file_codes: set[str] = set()
    row_count = 0
    with path.open("rb") as raw:
        if raw.read(3) != b"\xef\xbb\xbf":
            raise ValueError("CSV_MISSING_UTF8_BOM")
        raw.seek(0)
        with io.TextIOWrapper(raw, encoding="utf-8-sig", errors="strict", newline="") as text:
            reader = csv.DictReader(text)
            header = reader.fieldnames or []
            if header != table_schema["columns"]:
                result.add(
                    "HEADER_MISMATCH",
                    "表头与Schema不一致",
                    table="legal_contents.csv",
                )
            for index, row in enumerate(reader, 2):
                row_count += 1
                if None in row:
                    raise ValueError("CSV_COLUMN_COUNT_MISMATCH")
                for field in table_schema.get("required", []):
                    if not row.get(field, "").strip():
                        result.add(
                            "MISSING_REQUIRED_FIELD",
                            field,
                            table="legal_contents.csv",
                            row=index,
                        )

                file_code = row.get("DE_01001", "")
                content_code = row.get("DE_02001", "")
                key = (file_code, content_code)
                if key in seen_keys:
                    result.add(
                        "DUPLICATE_PRIMARY_KEY",
                        "['DE_01001', 'DE_02001']重复1行",
                        table="legal_contents.csv",
                        row=index,
                    )
                seen_keys.add(key)
                if file_code not in parent_file_codes:
                    result.add(
                        "FOREIGN_KEY_VIOLATION",
                        "引用legal_documents.csv失败1行",
                        table="legal_contents.csv",
                        row=index,
                    )
                if not re.fullmatch(r"\d{31}", file_code):
                    result.add(
                        "INVALID_31_CODE",
                        file_code,
                        table="legal_contents.csv",
                        row=index,
                    )
                if not re.fullmatch(r"\d{18}", content_code):
                    result.add(
                        "INVALID_18_CODE",
                        content_code,
                        table="legal_contents.csv",
                        row=index,
                    )
                if file_code and content_code and len(file_code + content_code) != 49:
                    result.add(
                        "INVALID_49_CODE",
                        "",
                        table="legal_contents.csv",
                        row=index,
                    )
                if file_code:
                    content_file_codes.add(file_code)
                category = row.get("DE_02003", "")
                if category not in {"01", "02", "03", "04", "05", "06", "07", "08"}:
                    result.add(
                        "INVALID_CONTENT_CATEGORY",
                        category,
                        table="legal_contents.csv",
                        row=index,
                    )
                order = row.get("DE_02004", "")
                if order and not re.fullmatch(r"\d{1,4}", order):
                    result.add(
                        "INVALID_CONTENT_ORDER",
                        order,
                        table="legal_contents.csv",
                        row=index,
                    )
    return header, row_count, content_file_codes


def load_publication_skip_registry(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(text.splitlines(keepends=True))
    header = reader.fieldnames or []
    if header != PUBLICATION_SKIP_HEADER:
        raise ValueError("PUBLICATION_SKIP_HEADER_MISMATCH")
    rows = list(reader)
    if any(None in row for row in rows):
        raise ValueError("PUBLICATION_SKIP_COLUMN_COUNT_MISMATCH")
    return rows


def normalize_legal_text_for_identity(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"^\s*#{1,6}\s*[^\n]+\n", "", text, count=1)
    text = re.sub(
        r"\n---\s*\n(?:\s*>\s*(?:来源|原文链接)\s*[：:].*(?:\n|$))+\s*$",
        "",
        text,
    )
    return re.sub(r"\s+", "", text)


class Result:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.samples: list[dict[str, str | int]] = []

    def add(
        self,
        code: str,
        message: str,
        *,
        table: str = "",
        row: int = 0,
        count: int = 1,
    ) -> None:
        self.counts[code] += count
        if len(self.samples) < 250:
            self.samples.append(
                {"code": code, "table": table, "row": row, "message": message}
            )


def validate_publication_skips(
    registry_rows: list[dict[str, str]],
    source_rows: list[dict[str, str]],
    queue_rows: list[dict[str, str]],
    validation_rows: list[dict[str, str]],
    result: Result,
) -> None:
    active_registry: dict[str, dict[str, str]] = {}
    seen_registry_paths: set[str] = set()
    for index, row in enumerate(registry_rows, 2):
        relative_path = row.get("relative_path", "").replace("\\", "/").strip()
        skip_code = row.get("skip_code", "").strip()
        status = row.get("status", "").strip()
        if (
            not relative_path
            or relative_path.startswith("/")
            or re.match(r"^[A-Za-z]:/", relative_path)
            or any(part in {"", ".", ".."} for part in relative_path.split("/"))
        ):
            result.add(
                "PUBLICATION_SKIP_INVALID_PATH",
                relative_path,
                table="publication_skip_registry.csv",
                row=index,
            )
            continue
        if skip_code not in PUBLICATION_SKIP_RULES:
            result.add(
                "PUBLICATION_SKIP_CODE_INVALID",
                skip_code,
                table="publication_skip_registry.csv",
                row=index,
            )
            continue
        if status not in {"ACTIVE", "INACTIVE"}:
            result.add(
                "PUBLICATION_SKIP_STATUS_INVALID",
                status,
                table="publication_skip_registry.csv",
                row=index,
            )
            continue
        if relative_path in seen_registry_paths:
            result.add(
                "PUBLICATION_SKIP_DUPLICATE",
                relative_path,
                table="publication_skip_registry.csv",
                row=index,
            )
            continue
        seen_registry_paths.add(relative_path)
        if status == "ACTIVE":
            active_registry[relative_path] = row

    source_paths = {
        row.get("relative_path", "") for row in source_rows
        if row.get("relative_path", "")
    }
    expected_registry = {
        relative_path: row
        for relative_path, row in active_registry.items()
        if relative_path in source_paths
    }
    expected_paths = set(expected_registry)
    skip_queue_statuses = {
        rule["queue_status"] for rule in PUBLICATION_SKIP_RULES.values()
    }
    skip_queue_rows = [
        row for row in queue_rows
        if row.get("ingest_status", "") in skip_queue_statuses
    ]
    actual_by_path = {
        row.get("relative_path", ""): row
        for row in skip_queue_rows
        if row.get("relative_path", "")
    }
    missing = {
        relative_path
        for relative_path, registry_row in expected_registry.items()
        if relative_path not in actual_by_path
        or actual_by_path[relative_path].get("ingest_status", "")
        != PUBLICATION_SKIP_RULES[registry_row["skip_code"]]["queue_status"]
    }
    unexpected = {
        relative_path
        for relative_path, queue_row in actual_by_path.items()
        if relative_path not in active_registry
        or queue_row.get("ingest_status", "")
        != PUBLICATION_SKIP_RULES[active_registry[relative_path]["skip_code"]]["queue_status"]
    }
    if missing:
        result.add(
            "PUBLICATION_SKIP_QUEUE_MISSING",
            sorted(missing)[0],
            table="ingest_queue.csv",
            count=len(missing),
        )
    if unexpected:
        result.add(
            "PUBLICATION_SKIP_NOT_REGISTERED",
            sorted(unexpected)[0],
            table="ingest_queue.csv",
            count=len(unexpected),
        )
    for index, row in enumerate(skip_queue_rows, 2):
        if row.get("target_relative_path", "").strip():
            result.add(
                "SKIPPED_TARGET_EMITTED",
                row.get("relative_path", ""),
                table="ingest_queue.csv",
                row=index,
            )

    warnings_by_path = {
        row.get("relative_path", ""): row
        for row in validation_rows
        if row.get("error_code", "")
        in {rule["warning_code"] for rule in PUBLICATION_SKIP_RULES.values()}
        and row.get("severity", "") == "WARNING"
    }
    missing_warnings = {
        relative_path
        for relative_path, registry_row in expected_registry.items()
        if relative_path not in warnings_by_path
        or warnings_by_path[relative_path].get("error_code", "")
        != PUBLICATION_SKIP_RULES[registry_row["skip_code"]]["warning_code"]
    }
    if missing_warnings:
        result.add(
            "PUBLICATION_SKIP_WARNING_MISSING",
            sorted(missing_warnings)[0],
            table="validation_errors.csv",
            count=len(missing_warnings),
        )


EXPLICIT_STANDARD_CONTENT_STRUCTURE = re.compile(
    r"(?m)^\s*(?:#{1,6}\s*)?(?:\*\*)?"
    r"第[零〇一二三四五六七八九十百千万两0-9]+(?:编|分编|章|节|条)"
)


def validate_legal_content_coverage(
    legal_rows: list[dict[str, str]],
    content_rows: list[dict[str, str]],
    result: Result,
) -> None:
    content_file_codes = {
        row.get("DE_01001", "") for row in content_rows if row.get("DE_01001", "")
    }
    validate_legal_content_coverage_codes(legal_rows, content_file_codes, result)


def validate_legal_content_coverage_codes(
    legal_rows: list[dict[str, str]],
    content_file_codes: set[str],
    result: Result,
) -> None:
    for index, row in enumerate(legal_rows, 2):
        if (
            row.get("FLFGDZWJFLDM", "") in GBT47277_CATEGORIES
            and row.get("DE_01001", "") not in content_file_codes
            and EXPLICIT_STANDARD_CONTENT_STRUCTURE.search(row.get("DE_01019", ""))
        ):
            result.add(
                "LEGAL_CONTENT_MISSING",
                row.get("DE_01001", ""),
                table="legal_contents.csv",
                row=index,
            )


def wjbs_component_mismatches(row: dict[str, str]) -> list[str]:
    match = re.fullmatch(r"1\.2\.156\.3005\.6-(\d{31})", row.get("WJBS", ""))
    if not match:
        return []
    body = match.group(1)
    expected = {
        "FLFGDZWJFLDM": body[0:4],
        "ZDJGDM": body[4:14],
        "GBRQ": body[14:22],
        "DE_01020": body[29:31],
    }
    return [
        field
        for field, value in expected.items()
        if row.get(field, "") and row.get(field) != value
    ]


def validate_formal_law_verification(
    wjbs: str,
    verification: dict[str, str] | None,
    result: Result,
) -> None:
    if not verification:
        result.add(
            "FORMAL_VERIFICATION_RECORD_MISSING",
            wjbs,
            table="verification_results.csv",
        )
        return
    source_type = verification.get("WJBS_source_type", "")
    if verification.get("WJBS_verified") != "true":
        result.add("WJBS_PROVENANCE_MISSING", wjbs, table="verification_results.csv")
    if source_type not in {"AUTHORITY_ISSUED", "STANDARD_DERIVED_LOCAL"}:
        result.add("WJBS_SOURCE_TYPE_INVALID", wjbs, table="verification_results.csv")
    elif source_type == "AUTHORITY_ISSUED":
        if verification.get("official_wjbs_verified") != "true":
            result.add(
                "WJBS_AUTHORITY_PROVENANCE_MISSING",
                wjbs,
                table="verification_results.csv",
            )
    elif not verification.get("WJBS_component_evidence", "").strip():
        result.add(
            "WJBS_COMPONENT_EVIDENCE_MISSING",
            wjbs,
            table="verification_results.csv",
        )


def validate_formal_source_hash_chain(
    document_rows: list[dict[str, str]],
    source_rows: list[dict[str, str]],
    verification_rows: list[dict[str, str]],
    result: Result,
) -> None:
    sources_by_path = {
        row.get("relative_path", ""): row
        for row in source_rows
        if row.get("relative_path", "")
    }
    verification_by_wjbs = {
        row.get("WJBS", ""): row
        for row in verification_rows
        if row.get("WJBS", "")
    }
    for index, document in enumerate(document_rows, 2):
        wjbs = document.get("WJBS", "")
        verification = verification_by_wjbs.get(wjbs)
        if not verification:
            continue
        relative_path = verification.get("relative_path", "")
        source = sources_by_path.get(relative_path)
        if not source:
            result.add(
                "FORMAL_SOURCE_RECORD_MISSING",
                f"{wjbs}:{relative_path}",
                table="source_records.csv",
                row=index,
            )
            continue
        source_hash = source.get("source_sha256", "").lower()
        verification_hash = verification.get("carrier_sha256", "").lower()
        if (
            not re.fullmatch(r"[0-9a-f]{64}", source_hash)
            or verification_hash != source_hash
        ):
            result.add(
                "FORMAL_SOURCE_SHA256_MISMATCH",
                f"{wjbs}:{relative_path}",
                table="verification_results.csv",
                row=index,
            )
        normalized_text = normalize_legal_text_for_identity(
            document.get("DE_01019", "")
        )
        actual_text_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
        if verification.get("normalized_text_sha256", "").lower() != actual_text_hash:
            result.add(
                "FORMAL_TEXT_SHA256_MISMATCH",
                wjbs,
                table="verification_results.csv",
                row=index,
            )


def validate_candidate_layout(root: Path, result: Result) -> None:
    if (root / "工程记录").exists():
        result.add("FINAL_ENGINEERING_MIXED", "最终候选混入工程记录")
    if (root / "正式数据").exists():
        result.add("LEGACY_FORMAL_WRAPPER", "最终候选仍使用旧正式数据包装目录")
    for directory in sorted(FINAL_TOP_LEVEL_DIRECTORIES):
        if not (root / directory).is_dir():
            result.add("MISSING_FINAL_DIRECTORY", directory)
    for entry in root.iterdir() if root.is_dir() else ():
        allowed = (
            entry.name in FINAL_TOP_LEVEL_DIRECTORIES
            if entry.is_dir()
            else entry.name in FINAL_TOP_LEVEL_FILES
        )
        if not allowed:
            result.add("UNEXPECTED_FINAL_ENTRY", entry.name)


def validate_formal_carriers(
    root: Path,
    source_rows: list[dict[str, str]],
    verification_by_wjbs: dict[str, dict[str, str]],
    result: Result,
) -> None:
    for index, row in enumerate(source_rows, 2):
        if not row.get("DE_04003", ""):
            result.add(
                "FORMAL_CARRIER_VALUE_MISSING",
                row.get("DE_01001", ""),
                table="legal_sources.csv",
                row=index,
            )


def validate_markdown_only_delivery(root: Path, result: Result) -> None:
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in NON_MARKDOWN_DOCUMENT_SUFFIXES:
            result.add(
                "NON_MARKDOWN_DOCUMENT_CARRIER",
                str(path.relative_to(root)),
            )


def validate_delivery_tree_structure(root: Path, result: Result) -> None:
    legacy_mixed = (
        root
        / "10_司法业务指导、会议纪要与公开答疑【非规范性法源】"
        / "03_法答网精选与法院业务答疑"
    )
    if legacy_mixed.exists():
        result.add(
            "LEGACY_MIXED_COURT_QA_DIRECTORY",
            str(legacy_mixed.relative_to(root)),
        )
    for directory in root.rglob("*"):
        if directory.is_dir() and not any(directory.iterdir()):
            result.add("EMPTY_DELIVERY_DIRECTORY", str(directory.relative_to(root)))
    legal_roots = [
        directory
        for directory in root.iterdir()
        if directory.is_dir() and re.match(r"^0[1-9]_", directory.name)
    ]
    for legal_root in legal_roots:
        for markdown in legal_root.rglob("*.md"):
            filename_wjbs = re.search(
                r"1\.2\.156\.3005\.6-\d{31}", markdown.name
            )
            frontmatter = markdown.read_text(
                encoding="utf-8", errors="strict"
            ).split("---", 2)
            frontmatter_wjbs = None
            if len(frontmatter) == 3 and not frontmatter[0].strip():
                frontmatter_wjbs = re.search(
                    r'^identifier:\s*"?(1\.2\.156\.3005\.6-\d{31})"?\s*$',
                    frontmatter[1],
                    re.MULTILINE,
                )
            if not filename_wjbs or not frontmatter_wjbs:
                result.add(
                    "LEGAL_MARKDOWN_WJBS_MISSING",
                    str(markdown.relative_to(root)),
                )
            elif filename_wjbs.group(0) != frontmatter_wjbs.group(1):
                result.add(
                    "LEGAL_MARKDOWN_WJBS_MISMATCH",
                    str(markdown.relative_to(root)),
                )


def validate_checksums(root: Path, result: Result) -> None:
    checksum_path = root / "SHA256SUMS"
    if not checksum_path.is_file():
        result.add("SHA256SUMS_MISSING", "最终候选缺少SHA256SUMS")
        return
    declared: dict[str, str] = {}
    for line_number, line in enumerate(
        checksum_path.read_text(encoding="utf-8", errors="strict").splitlines(), 1
    ):
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            result.add("SHA256SUMS_FORMAT", line, row=line_number)
            continue
        declared[match.group(2)] = match.group(1)
    actual = {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file() and path != checksum_path
    }
    if set(declared) != set(actual):
        result.add(
            "SHA256SUMS_FILESET_MISMATCH",
            f"declared={len(declared)},actual={len(actual)}",
        )
    mismatches = sum(
        relative not in actual or sha256(actual[relative]) != expected
        for relative, expected in declared.items()
    )
    if mismatches:
        result.add("SHA256SUMS_HASH_MISMATCH", str(mismatches), count=mismatches)


def validate_markdown_derivatives(
    root: Path,
    engineering_root: Path,
    rows_by_table: dict[str, list[dict[str, str]]],
    result: Result,
) -> None:
    manifest_path = engineering_root / "批次清单" / "Markdown派生清单.csv"
    if not manifest_path.is_file():
        result.add("MARKDOWN_MANIFEST_MISSING", str(manifest_path))
        return
    try:
        _, manifest_rows = load_csv(manifest_path)
    except (UnicodeDecodeError, ValueError, csv.Error) as error:
        result.add("MARKDOWN_MANIFEST_PARSE_ERROR", str(error))
        return
    markdown_root = root.resolve()
    source_by_path = {
        row.get("relative_path", ""): row
        for row in rows_by_table.get("source_records.csv", [])
        if row.get("relative_path", "")
    }
    expected_sources = {
        row.get("relative_path", "")
        for row in rows_by_table.get("ingest_queue.csv", [])
        if row.get("target_relative_path", "")
        and row.get("ingest_status", "") != "REFERENCE_EXISTING_CANONICAL"
    }
    expected_target_by_source = {
        row.get("relative_path", ""): row.get("target_relative_path", "")
        for row in rows_by_table.get("ingest_queue.csv", [])
        if row.get("target_relative_path", "")
    }
    manifest_sources: set[str] = set()
    manifest_targets: set[str] = set()
    for index, row in enumerate(manifest_rows, 2):
        source_relative = row.get("source_relative_path", "")
        target_relative = row.get("target_relative_path", "")
        target_relative = target_relative.replace("\\", "/")
        if target_relative != expected_target_by_source.get(source_relative, ""):
            result.add(
                "MARKDOWN_QUEUE_TARGET_MISMATCH",
                target_relative,
                table="Markdown派生清单.csv",
                row=index,
            )
        filename = Path(target_relative).name
        if re.fullmatch(r"[0-9a-fA-F]{32,64}\.md", filename):
            result.add("HASH_ONLY_MARKDOWN_FILENAME", filename, row=index)
        if re.fullmatch(r"1\.2\.156\.3005\.6-\d{31}\.md", filename):
            result.add("WJBS_ONLY_MARKDOWN_FILENAME", filename, row=index)
        manifest_sources.add(source_relative)
        if target_relative in manifest_targets:
            result.add(
                "MARKDOWN_TARGET_DUPLICATE",
                target_relative,
                table="Markdown派生清单.csv",
                row=index,
            )
            continue
        manifest_targets.add(target_relative)
        target = (root / Path(target_relative)).resolve()
        try:
            target.relative_to(markdown_root)
        except ValueError:
            result.add(
                "MARKDOWN_TARGET_PATH_INVALID",
                target_relative,
                table="Markdown派生清单.csv",
                row=index,
            )
            continue
        if target.suffix.lower() != ".md" or not target.is_file():
            result.add(
                "MARKDOWN_TARGET_MISSING",
                target_relative,
                table="Markdown派生清单.csv",
                row=index,
            )
            continue
        expected_hash = row.get("derived_sha256", "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash) or sha256(target) != expected_hash:
            result.add(
                "MARKDOWN_DERIVED_SHA256_MISMATCH",
                target_relative,
                table="Markdown派生清单.csv",
                row=index,
            )
        source = source_by_path.get(source_relative)
        if not source or source.get("source_sha256", "").lower() != row.get(
            "source_sha256", ""
        ).lower():
            result.add(
                "MARKDOWN_SOURCE_SHA256_MISMATCH",
                source_relative,
                table="Markdown派生清单.csv",
                row=index,
            )
        text = target.read_text(encoding="utf-8", errors="strict")
        if ABSOLUTE_PATH.search(text):
            result.add(
                "MARKDOWN_ABSOLUTE_PATH",
                target_relative,
                table="Markdown派生清单.csv",
                row=index,
            )
        if POLLUTION.search(text):
            result.add(
                "MARKDOWN_PLATFORM_POLLUTION",
                target_relative,
                table="Markdown派生清单.csv",
                row=index,
            )
    actual_targets = {
        path.relative_to(root).as_posix()
        for path in markdown_root.rglob("*.md")
        if path.name != "README.md"
    } if markdown_root.is_dir() else set()
    if actual_targets != manifest_targets:
        result.add(
            "MARKDOWN_MANIFEST_FILESET_MISMATCH",
            f"manifest={len(manifest_targets)},actual={len(actual_targets)}",
        )
    if manifest_sources != expected_sources:
        result.add(
            "MARKDOWN_FORMAL_COVERAGE_MISMATCH",
            f"manifest={len(manifest_sources)},expected={len(expected_sources)}",
        )


def validate_official_registry_snapshots(
    engineering_root: Path, result: Result
) -> None:
    registry_root = engineering_root / "official_registry"
    specifications = (
        (
            "npc_flk",
            "flk_official_index_meta.json",
            "flk_official_index.csv",
            "fetched_rows",
            "official_total",
        ),
        (
            "national_rules_database",
            "official_index_meta.json",
            "official_index.csv",
            "row_count",
            "",
        ),
    )
    for source_id, meta_name, csv_name, count_field, total_field in specifications:
        meta_paths = list(registry_root.rglob(meta_name)) if registry_root.is_dir() else []
        if len(meta_paths) != 1:
            result.add(
                "OFFICIAL_REGISTRY_MISSING",
                f"{source_id}:{meta_name}:found={len(meta_paths)}",
            )
            continue
        meta_path = meta_paths[0]
        csv_path = meta_path.parent / csv_name
        if not csv_path.is_file():
            result.add("OFFICIAL_REGISTRY_MISSING", f"{source_id}:{csv_name}")
            continue
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8-sig"))
            _, rows = load_csv(csv_path)
        except (UnicodeDecodeError, ValueError, csv.Error, json.JSONDecodeError) as error:
            result.add("OFFICIAL_REGISTRY_PARSE_ERROR", f"{source_id}:{error}")
            continue
        if metadata.get("complete") is not True:
            result.add("OFFICIAL_REGISTRY_INCOMPLETE", source_id)
        expected_count = metadata.get(count_field)
        if not isinstance(expected_count, int) or expected_count <= 0:
            result.add(
                "OFFICIAL_REGISTRY_INVALID_COUNT",
                f"{source_id}:{count_field}={expected_count}",
            )
        elif len(rows) != expected_count:
            result.add(
                "OFFICIAL_REGISTRY_COUNT_MISMATCH",
                f"{source_id}:csv={len(rows)},meta={expected_count}",
            )
        if total_field:
            official_total = metadata.get(total_field)
            if official_total != expected_count:
                result.add(
                    "OFFICIAL_REGISTRY_TOTAL_MISMATCH",
                    f"{source_id}:{total_field}={official_total},meta={expected_count}",
                )


def validate_formal_field_types(
    rows_by_table: dict[str, list[dict[str, str]]],
    result: Result,
) -> None:
    date_fields = {
        "legal_documents.csv": {
            "TGRQ": "%Y%m%d",
            "PZRQ": "%Y%m%d",
            "GBRQ": "%Y%m%d",
            "SXRQ": "%Y%m%d",
            "SHXRQ": "%Y%m%d",
            "CWRQ": "%Y%m%d",
            "FBRQ": "%Y%m%d",
        },
        "cases.csv": {
            "publication_date": "%Y-%m-%d",
            "decision_date": "%Y-%m-%d",
        },
        "practice_references.csv": {"publication_date": "%Y-%m-%d"},
    }
    hash_fields = {
        "cases.csv": ("content_sha256",),
        "practice_references.csv": ("content_sha256",),
    }
    boolean_fields = {
        "cases.csv": ("has_fulltext",),
        "practice_references.csv": ("default_legal_search",),
    }
    url_fields = {
        "cases.csv": ("source_url",),
        "practice_references.csv": ("source_url",),
    }
    path_fields = {
        "cases.csv": ("relative_path",),
        "case_holdings.csv": ("relative_path",),
        "case_legal_references.csv": ("relative_path",),
        "practice_references.csv": ("relative_path",),
    }
    for table_name in FORMAL_TABLES:
        for index, row in enumerate(rows_by_table.get(table_name, []), 2):
            for field, date_format in date_fields.get(table_name, {}).items():
                value = row.get(field, "")
                if not value:
                    continue
                try:
                    parsed = datetime.strptime(value, date_format)
                except ValueError:
                    result.add(
                        "INVALID_FORMAL_DATE",
                        f"{field}={value}",
                        table=table_name,
                        row=index,
                    )
                    continue
                if parsed.strftime(date_format) != value:
                    result.add(
                        "INVALID_FORMAL_DATE",
                        f"{field}={value}",
                        table=table_name,
                        row=index,
                    )
            for field in hash_fields.get(table_name, ()):
                value = row.get(field, "")
                if value and not re.fullmatch(r"[0-9a-f]{64}", value):
                    result.add(
                        "INVALID_FORMAL_SHA256",
                        f"{field}={value}",
                        table=table_name,
                        row=index,
                    )
            for field in boolean_fields.get(table_name, ()):
                value = row.get(field, "")
                if value and value not in {"true", "false"}:
                    result.add(
                        "INVALID_FORMAL_BOOLEAN",
                        f"{field}={value}",
                        table=table_name,
                        row=index,
                    )
            for field in url_fields.get(table_name, ()):
                value = row.get(field, "")
                if value and urlparse(value).scheme not in {"http", "https"}:
                    result.add(
                        "INVALID_FORMAL_URL",
                        f"{field}={value}",
                        table=table_name,
                        row=index,
                    )
            for field in path_fields.get(table_name, ()):
                value = row.get(field, "")
                parts = re.split(r"[\\/]", value)
                if value and (
                    ABSOLUTE_PATH.search(value)
                    or value.startswith(("/", "\\"))
                    or ".." in parts
                ):
                    result.add(
                        "INVALID_FORMAL_RELATIVE_PATH",
                        f"{field}={value}",
                        table=table_name,
                        row=index,
                    )
            if table_name == "legal_sources.csv":
                file_type = row.get("DE_04002", "")
                if file_type and file_type not in {"OFD", "UOF", "PDF", "DOCX"}:
                    result.add(
                        "INVALID_ELECTRONIC_FILE_TYPE",
                        file_type,
                        table=table_name,
                        row=index,
                    )
            if table_name == "legal_documents.csv":
                category = row.get("FLFGDZWJFLDM", "")
                agency = row.get("ZDJGDM", "")
                if category and not re.fullmatch(r"\d{4}", category):
                    result.add(
                        "INVALID_CATEGORY_CODE",
                        category,
                        table=table_name,
                        row=index,
                    )
                if agency and not re.fullmatch(r"\d{10}", agency):
                    result.add(
                        "INVALID_AGENCY_CODE",
                        agency,
                        table=table_name,
                        row=index,
                    )


def validate(
    root: Path,
    source_root: Path,
    deprecated_path: Path,
    engineering_root: Path,
) -> dict:
    result = Result()
    validate_candidate_layout(root, result)
    schema_path = engineering_root / "schema" / "tables.json"
    if not schema_path.is_file():
        result.add("MISSING_SCHEMA", "外部工程记录缺少schema/tables.json")
        return report(root, {}, {}, result)
    schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    publication_skip_registry_path = (
        engineering_root / "schema" / "publication_skip_registry.csv"
    )
    publication_skip_rows: list[dict[str, str]] = []
    if not publication_skip_registry_path.is_file():
        result.add(
            "PUBLICATION_SKIP_REGISTRY_MISSING",
            str(publication_skip_registry_path),
        )
    else:
        try:
            publication_skip_rows = load_publication_skip_registry(
                publication_skip_registry_path
            )
        except (UnicodeDecodeError, ValueError, csv.Error) as error:
            result.add("PUBLICATION_SKIP_REGISTRY_PARSE_ERROR", str(error))
    expected = set(schema["tables"])
    if expected != FORMAL_TABLES | ENGINEERING_TABLES:
        result.add("SCHEMA_TABLE_SET_MISMATCH", "Schema不是固定8张正式表加5张工程表")

    unexpected_formal = {
        path.name for path in root.glob("*.csv")
    } - FORMAL_TABLES
    unexpected_engineering = {
        path.name for path in engineering_root.glob("*.csv")
    } - ENGINEERING_TABLES
    for name in sorted(unexpected_formal | unexpected_engineering):
        result.add("UNEXPECTED_TOP_LEVEL_CSV", name)

    rows_by_table: dict[str, list[dict[str, str]]] = {}
    table_counts: dict[str, int] = {}
    headers: dict[str, list[str]] = {}
    for table_name, table_schema in schema["tables"].items():
        table_path = (
            root / table_name
            if table_name in FORMAL_TABLES
            else engineering_root / table_name
        )
        if not table_path.is_file():
            result.add("MISSING_TABLE", str(table_path), table=table_name)
            continue
        if table_name == "legal_contents.csv":
            continue
        try:
            header, rows = load_csv(table_path)
        except (UnicodeDecodeError, ValueError, csv.Error) as error:
            result.add("CSV_PARSE_ERROR", str(error), table=table_name)
            continue
        headers[table_name] = header
        rows_by_table[table_name] = rows
        table_counts[table_name] = len(rows)
        if header != table_schema["columns"]:
            result.add("HEADER_MISMATCH", "表头与Schema不一致", table=table_name)
        for index, row in enumerate(rows, 2):
            for field in table_schema.get("required", []):
                if not row.get(field, "").strip():
                    result.add(
                        "MISSING_REQUIRED_FIELD",
                        field,
                        table=table_name,
                        row=index,
                    )

    validate_formal_field_types(rows_by_table, result)

    constraints = schema.get("constraints", {})
    for table_name, key_fields in constraints.get("primary_keys", {}).items():
        if table_name == "legal_contents.csv":
            continue
        table_rows = rows_by_table.get(table_name, [])
        seen: set[tuple[str, ...]] = set()
        duplicates = 0
        for row in table_rows:
            key = tuple(row.get(field, "") for field in key_fields)
            if key in seen:
                duplicates += 1
            seen.add(key)
        if duplicates:
            result.add(
                "DUPLICATE_PRIMARY_KEY",
                f"{key_fields}重复{duplicates}行",
                table=table_name,
                count=duplicates,
            )

    for foreign in constraints.get("foreign_keys", []):
        if foreign["table"] == "legal_contents.csv":
            continue
        child_rows = rows_by_table.get(foreign["table"], [])
        parent_rows = rows_by_table.get(foreign["references"], [])
        parent_keys = {
            tuple(row.get(field, "") for field in foreign["reference_columns"])
            for row in parent_rows
        }
        missing = sum(
            tuple(row.get(field, "") for field in foreign["columns"]) not in parent_keys
            for row in child_rows
        )
        if missing:
            result.add(
                "FOREIGN_KEY_VIOLATION",
                f"引用{foreign['references']}失败{missing}行",
                table=foreign["table"],
                count=missing,
            )

    legal_rows = rows_by_table.get("legal_documents.csv", [])
    if not legal_rows:
        result.add(
            "EMPTY_LEGAL_DOCUMENTS",
            "法规正式表为0行，不满足正式数据非空门禁",
            table="legal_documents.csv",
        )
    seen_wjbs: set[str] = set()
    for index, row in enumerate(legal_rows, 2):
        wjbs = row.get("WJBS", "")
        match = re.fullmatch(r"1\.2\.156\.3005\.6-(\d{31})", wjbs)
        if not match:
            result.add("INVALID_WJBS", wjbs, table="legal_documents.csv", row=index)
            continue
        if wjbs in seen_wjbs:
            result.add(
                "DUPLICATE_WJBS", wjbs, table="legal_documents.csv", row=index
            )
        seen_wjbs.add(wjbs)
        category = row.get("FLFGDZWJFLDM", "")
        file_code = row.get("DE_01001", "")
        if category in GBT47277_CATEGORIES:
            if not re.fullmatch(r"\d{31}", file_code):
                result.add(
                    "INVALID_47277_FILE_CODE",
                    file_code,
                    table="legal_documents.csv",
                    row=index,
                )
            elif file_code != match.group(1):
                result.add(
                    "WJBS_FILE_CODE_MISMATCH",
                    file_code,
                    table="legal_documents.csv",
                    row=index,
                )
            if file_code and file_code[-2:] not in GBT47277_FILE_TYPES:
                result.add(
                    "INVALID_47277_FILE_TYPE",
                    file_code[-2:],
                    table="legal_documents.csv",
                    row=index,
                )
        elif file_code:
            result.add(
                "GBT47277_SCOPE_VIOLATION",
                category,
                table="legal_documents.csv",
                row=index,
            )
        if row.get("SXX") not in {"01", "02", "03", "04", "05"}:
            result.add(
                "INVALID_EFFECT_CODE",
                row.get("SXX", ""),
                table="legal_documents.csv",
                row=index,
            )
        for field in wjbs_component_mismatches(row):
            result.add(
                "WJBS_COMPONENT_MISMATCH",
                field,
                table="legal_documents.csv",
                row=index,
            )

    content_file_codes: set[str] = set()
    content_path = root / "legal_contents.csv"
    if content_path.is_file():
        try:
            header, content_count, content_file_codes = validate_legal_contents_stream(
                content_path,
                schema["tables"]["legal_contents.csv"],
                {
                    row.get("DE_01001", "")
                    for row in legal_rows
                    if row.get("DE_01001", "")
                },
                result,
            )
            headers["legal_contents.csv"] = header
            table_counts["legal_contents.csv"] = content_count
        except (UnicodeDecodeError, ValueError, csv.Error) as error:
            result.add(
                "CSV_PARSE_ERROR",
                str(error),
                table="legal_contents.csv",
            )

    validate_legal_content_coverage_codes(legal_rows, content_file_codes, result)

    case_rows = rows_by_table.get("cases.csv", [])
    case_id_counts = Counter(
        row["official_case_id"] for row in case_rows if row.get("official_case_id")
    )
    invalid_case_ids = [
        value for value in case_id_counts if not valid_case_id(value)
    ]
    if invalid_case_ids:
        result.add(
            "INVALID_OFFICIAL_CASE_ID",
            invalid_case_ids[0],
            table="cases.csv",
            count=len(invalid_case_ids),
        )
    duplicate_case_ids = {key: count for key, count in case_id_counts.items() if count > 1}
    if duplicate_case_ids:
        first = next(iter(duplicate_case_ids))
        result.add(
            "DUPLICATE_OFFICIAL_CASE_ID",
            first,
            table="cases.csv",
            count=sum(count - 1 for count in duplicate_case_ids.values()),
        )

    holdings = rows_by_table.get("case_holdings.csv", [])
    bad_arbitration_holdings = sum(
        row.get("relative_path", "").startswith("04_")
        and row.get("source_heading") == "结语和建议"
        for row in holdings
    )
    if bad_arbitration_holdings:
        result.add(
            "ARBITRATION_CONCLUSION_AS_HOLDING",
            "司法部仲裁案例把结语和建议当成要旨",
            table="case_holdings.csv",
            count=bad_arbitration_holdings,
        )

    source_rows = rows_by_table.get("source_records.csv", [])
    queue_rows = rows_by_table.get("ingest_queue.csv", [])
    verification_rows = rows_by_table.get("verification_results.csv", [])
    source_paths = {row.get("relative_path", "") for row in source_rows}
    queue_paths = {row.get("relative_path", "") for row in queue_rows}
    verification_paths = {row.get("relative_path", "") for row in verification_rows}
    if not (source_paths == queue_paths == verification_paths):
        result.add(
            "SOURCE_DISPOSITION_NOT_CLOSED",
            f"source={len(source_paths)},queue={len(queue_paths)},verification={len(verification_paths)}",
        )
    validate_publication_skips(
        publication_skip_rows,
        source_rows,
        queue_rows,
        rows_by_table.get("validation_errors.csv", []),
        result,
    )
    unaccepted = Counter(
        row.get("verification_status", "")
        for row in verification_rows
        if row.get("verification_status", "") not in ACCEPTED_VERIFICATION
    )
    if unaccepted:
        result.add(
            "UNACCEPTED_VERIFICATION_STATUS",
            json.dumps(unaccepted, ensure_ascii=False),
            table="verification_results.csv",
            count=sum(unaccepted.values()),
        )

    verification_by_wjbs = {
        row.get("WJBS", ""): row
        for row in verification_rows
        if row.get("WJBS", "")
    }
    for wjbs in seen_wjbs:
        validate_formal_law_verification(
            wjbs,
            verification_by_wjbs.get(wjbs),
            result,
        )
    validate_formal_source_hash_chain(
        rows_by_table.get("legal_documents.csv", []),
        source_rows,
        verification_rows,
        result,
    )
    validate_formal_carriers(
        root,
        rows_by_table.get("legal_sources.csv", []),
        verification_by_wjbs,
        result,
    )
    validate_markdown_only_delivery(root, result)
    validate_delivery_tree_structure(root, result)
    validate_checksums(root, result)
    validate_markdown_derivatives(root, engineering_root, rows_by_table, result)

    validate_official_registry_snapshots(engineering_root, result)

    formal_flags = {
        "absolute_path": False,
        "pollution": False,
        "intermediate": False,
    }
    for table_name in FORMAL_TABLES:
        table_path = root / table_name
        if table_path.is_file():
            with table_path.open("r", encoding="utf-8-sig", errors="strict") as file:
                for line in file:
                    if not formal_flags["absolute_path"] and ABSOLUTE_PATH.search(line):
                        formal_flags["absolute_path"] = True
                    if not formal_flags["pollution"] and POLLUTION.search(line):
                        formal_flags["pollution"] = True
                    if (
                        not formal_flags["intermediate"]
                        and PERSONAL_OR_INTERMEDIATE.search(line)
                    ):
                        formal_flags["intermediate"] = True
    if formal_flags["absolute_path"]:
        result.add("FORMAL_ABSOLUTE_PATH", "正式CSV含Windows绝对路径")
    if formal_flags["pollution"]:
        result.add("FORMAL_PLATFORM_POLLUTION", "正式CSV含固定转载污染")
    if formal_flags["intermediate"]:
        result.add(
            "FORMAL_RESEARCH_OR_INTERMEDIATE_CONTENT",
            "正式CSV含研究或中间标记",
        )

    path_hash_rows = case_rows + rows_by_table.get("practice_references.csv", [])
    hash_mismatch = 0
    missing_source_path = 0
    for row in path_hash_rows:
        relative = row.get("relative_path", "")
        source_path = filesystem_path(source_root / Path(relative))
        if not source_path.is_file():
            missing_source_path += 1
            continue
        expected_hash = row.get("content_sha256", "")
        if expected_hash and sha256(source_path) != expected_hash.lower():
            hash_mismatch += 1
        source_url = row.get("source_url", "")
        if source_url and urlparse(source_url).scheme not in {"http", "https"}:
            result.add("INVALID_SOURCE_URL", source_url, count=1)
    if missing_source_path:
        result.add(
            "MISSING_SOURCE_PATH",
            str(missing_source_path),
            count=missing_source_path,
        )
    if hash_mismatch:
        result.add("SOURCE_HASH_MISMATCH", str(hash_mismatch), count=hash_mismatch)

    unresolved_conflicts = sum(
        not is_resolved_conflict(row.get("disposition", ""))
        for row in rows_by_table.get("conflicts.csv", [])
    )
    if unresolved_conflicts:
        result.add(
            "UNRESOLVED_CONFLICT",
            str(unresolved_conflicts),
            table="conflicts.csv",
            count=unresolved_conflicts,
        )

    if deprecated_path.exists():
        result.add("DEPRECATED_PATH_EXISTS", str(deprecated_path))
    forbidden_names = {
        ".git", "node_modules", "tmp", "temp", "scripts", "交换候选", "intake"
    }
    for path in root.rglob("*"):
        if path.name.lower() in {name.lower() for name in forbidden_names}:
            result.add("FORBIDDEN_OUTPUT_ENTRY", str(path.relative_to(root)))

    status_counts = Counter(row.get("ingest_status", "") for row in queue_rows)
    verification_counts = Counter(
        row.get("verification_status", "") for row in verification_rows
    )
    statistics = {
        "table_rows": table_counts,
        "ingest_status": dict(status_counts),
        "verification_status": dict(verification_counts),
        "official_case_ids": sum(bool(row.get("official_case_id")) for row in case_rows),
        "cases_pending_official_id": sum(
            not bool(row.get("official_case_id")) for row in case_rows
        ),
        "conflicts": len(rows_by_table.get("conflicts.csv", [])),
        "validation_records": len(rows_by_table.get("validation_errors.csv", [])),
    }
    return report(root, statistics, schema, result)


def report(root: Path, statistics: dict, schema: dict, result: Result) -> dict:
    status = "LOCAL_FULLY_VALIDATED" if not result.counts else "BLOCKED"
    hashes = {}
    mutable_reports = {
        root / "工程记录" / "full_validation_report.json",
        root / "工程记录" / "full_validation_report.md",
    }
    for path in sorted(root.rglob("*")):
        if path.is_file() and path not in mutable_reports:
            hashes[path.relative_to(root).as_posix()] = sha256(path)
    tree_material = "\n".join(
        f"{relative}\0{digest}" for relative, digest in sorted(hashes.items())
    ).encode("utf-8")
    return {
        "status": status,
        "root": ".",
        "schema_version": schema.get("version", "") if schema else "",
        "statistics": statistics,
        "blocking_counts": dict(result.counts),
        "blocking_samples": result.samples,
        "artifact_tree_sha256": hashlib.sha256(tree_material).hexdigest(),
        "artifact_sha256": hashes,
    }


def write_reports(engineering_root: Path, payload: dict) -> None:
    engineering_root.mkdir(parents=True, exist_ok=True)
    json_path = engineering_root / "full_validation_report.json"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# 本地标准化数据集全量验证报告",
        "",
        f"- 状态：`{payload['status']}`",
        f"- Schema：`{payload['schema_version']}`",
        "",
        "## 阻断统计",
        "",
        "| 代码 | 数量 |",
        "| --- | ---: |",
        *[
            f"| {code} | {count} |"
            for code, count in sorted(payload["blocking_counts"].items())
        ],
        "",
        "## 表行数",
        "",
        "| 表 | 数据行 |",
        "| --- | ---: |",
        *[
            f"| {table} | {count} |"
            for table, count in payload.get("statistics", {})
            .get("table_rows", {})
            .items()
        ],
        "",
    ]
    (engineering_root / "full_validation_report.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument(
        "--engineering-root",
        type=Path,
        required=True,
        help="与最终候选物理隔离的工程记录批次目录",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=DEFAULT_SOURCE_ROOT,
    )
    parser.add_argument(
        "--deprecated-path",
        type=Path,
        required=True,
        help="仅用于验证指定的禁止路径不存在；不作为读取或写入位置",
    )
    args = parser.parse_args()
    payload = validate(
        args.root.resolve(),
        args.source_root.resolve(),
        args.deprecated_path.resolve(),
        args.engineering_root.resolve(),
    )
    write_reports(args.engineering_root.resolve(), payload)
    compact = {
        "status": payload["status"],
        "schema_version": payload["schema_version"],
        "statistics": payload["statistics"],
        "blocking_counts": payload["blocking_counts"],
        "blocking_samples": payload["blocking_samples"][:20],
        "artifact_count": len(payload["artifact_sha256"]),
        "artifact_tree_sha256": payload["artifact_tree_sha256"],
    }
    sys.stdout.buffer.write((json.dumps(compact, ensure_ascii=False) + "\n").encode("utf-8"))
    return 0 if payload["status"] == "LOCAL_FULLY_VALIDATED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
