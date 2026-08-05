"""Fail-closed construction contracts for incremental legal-corpus verification."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


AUTHORITY_ORIGIN = "AUTHORITY_ORIGIN"
OFFICIAL_CANONICAL_DATABASE = "OFFICIAL_CANONICAL_DATABASE"
OFFICIAL_REPUBLICATION = "OFFICIAL_REPUBLICATION"
THIRD_PARTY_CARRIER = "THIRD_PARTY_CARRIER"

OFFICIAL_SOURCE_ROLES = {
    AUTHORITY_ORIGIN,
    OFFICIAL_CANONICAL_DATABASE,
    OFFICIAL_REPUBLICATION,
}


class EvidenceCache:
    """Cache official objects by stable id plus version and attachment identity."""

    def __init__(self):
        self._objects: dict[tuple[str, str, str], object] = {}

    @staticmethod
    def _key(stable_id: str, version_token: str, attachment_fingerprint: str) -> tuple[str, str, str]:
        return stable_id, version_token, attachment_fingerprint

    def put(self, stable_id: str, version_token: str, attachment_fingerprint: str, value: object) -> None:
        self._objects[self._key(stable_id, version_token, attachment_fingerprint)] = value

    def get_or_fetch(self, stable_id: str, version_token: str, attachment_fingerprint: str, fetcher):
        key = self._key(stable_id, version_token, attachment_fingerprint)
        if key not in self._objects:
            self._objects[key] = fetcher()
        return self._objects[key]


def select_incremental_records(
    records: list[dict],
    watermark: tuple[str, str],
    overlap_start: str,
    complete: bool,
) -> tuple[list[dict], tuple[str, str]]:
    """Select new/changed records inside a fixed overlap; advance only on complete runs."""
    selected = [
        record
        for record in records
        if record.get("published_at", "") >= overlap_start
        and (not record.get("known", False) or record.get("changed", False))
    ]
    if not complete or not records:
        return selected, watermark
    newest = max(
        ((record.get("published_at", ""), record.get("stable_id", "")) for record in records),
        default=watermark,
    )
    return selected, max(watermark, newest)


def derive_content_status(
    *,
    source_role: str,
    comparison_result: str = "",
    local_sha256: str = "",
    official_sha256: str = "",
    local_normalized_sha256: str = "",
    official_normalized_sha256: str = "",
    representation_completeness: str = "",
    editorial_block_status: str = "",
    document_type: str = "",
) -> str:
    """Derive a content status only from complete official text and actual hashes."""
    del document_type  # document type affects routing, not the hash equality rule.
    if representation_completeness != "COMPLETE" or editorial_block_status != "CLEAN":
        return "MANUAL_REVIEW_REQUIRED"
    if source_role not in OFFICIAL_SOURCE_ROLES:
        return "CONTENT_NOT_VERIFIED"
    if (
        comparison_result == "BYTE_IDENTICAL"
        and local_sha256
        and official_sha256
        and local_sha256 == official_sha256
    ):
        return "OFFICIAL_FULLTEXT_BYTE_IDENTICAL"
    if (
        comparison_result == "NORMALIZED_EQUIVALENT"
        and local_normalized_sha256
        and official_normalized_sha256
        and local_normalized_sha256 == official_normalized_sha256
    ):
        return "OFFICIAL_FULLTEXT_NORMALIZED_EQUIVALENT"
    return "CONTENT_NOT_VERIFIED"


def validate_change_rows(rows: list[dict]) -> list[str]:
    problems: list[str] = []
    for row in rows:
        action = row.get("action", "")
        path = row.get("path", "")
        if action in {"DELETE", "REPLACE"} and not row.get("before_sha256"):
            problems.append(f"{path}: missing before_sha256")
        if action == "REPLACE" and not row.get("after_sha256"):
            problems.append(f"{path}: missing after_sha256")
        if action in {"DELETE", "REPLACE"} and not row.get("backup_path"):
            problems.append(f"{path}: missing backup_path")
    return problems


def validate_candidate_paths(paths: list[str]) -> list[str]:
    allowed_prefixes = (
        "00_", "01_", "02_", "03_", "04_", "05_", "06_", "07_",
        "08_", "09_", "10_", "80_", "81_", "82_", "89_",
    )
    allowed_root_files = {"README.md", "SHA256SUMS"}
    problems: list[str] = []
    for path in paths:
        normalized = path.replace("\\", "/")
        if "/" not in normalized:
            if normalized not in allowed_root_files:
                problems.append(f"forbidden root file: {normalized}")
            continue
        first = normalized.split("/", 1)[0]
        if not first.startswith(allowed_prefixes):
            problems.append(f"forbidden directory: {first}")
    return problems


def assert_inherited_tree(
    baseline: dict[str, str], candidate: dict[str, str], prefixes: tuple[str, ...]
) -> list[str]:
    before = {path: digest for path, digest in baseline.items() if path.startswith(prefixes)}
    after = {path: digest for path, digest in candidate.items() if path.startswith(prefixes)}
    problems = [f"{path}: missing" for path in sorted(set(before) - set(after))]
    problems.extend(f"{path}: extra" for path in sorted(set(after) - set(before)))
    problems.extend(
        f"{path}: hash mismatch"
        for path in sorted(set(before) & set(after))
        if before[path] != after[path]
    )
    return problems


class SourceCircuitBreaker:
    def __init__(self, threshold: int):
        self.threshold = threshold
        self._blocked_counts: dict[str, int] = {}

    def record(self, source: str, blocked: bool) -> None:
        self._blocked_counts[source] = self._blocked_counts.get(source, 0) + (1 if blocked else 0)

    def allow(self, source: str) -> bool:
        return self._blocked_counts.get(source, 0) < self.threshold


@dataclass
class SourceRunState:
    index_status: str
    source_run_status: str
    local_batch_status: str = "RUNNING"
    external_increment_status: str = "RUNNING"

    def finish(self, *, blocked: bool, pending_today: int, budget_exhausted: bool = False) -> None:
        if blocked:
            self.source_run_status = "BLOCKED_ACCESS"
            self.local_batch_status = "PARTIAL_OK"
            self.external_increment_status = "PARTIAL"
        elif budget_exhausted:
            self.source_run_status = "BUDGET_EXHAUSTED"
            self.local_batch_status = "PARTIAL_OK"
            self.external_increment_status = "PARTIAL"
        elif pending_today:
            self.source_run_status = "PARTIAL"
            self.local_batch_status = "PARTIAL_OK"
            self.external_increment_status = "PARTIAL"
        else:
            self.source_run_status = "COMPLETE"
            self.local_batch_status = "COMPLETE"
            self.external_increment_status = "COMPLETE"


def build_historical_gap_tasks(stable_ids: list[str], approved: bool = False) -> list[str]:
    return list(stable_ids) if approved else []


def build_wechat_tasks(
    accounts: dict[str, list[str]], approved: bool, max_accounts: int = 5, max_per_account: int = 20
) -> list[tuple[str, str]]:
    if not approved:
        return []
    tasks: list[tuple[str, str]] = []
    for account in sorted(accounts)[:max_accounts]:
        tasks.extend((account, url) for url in accounts[account][:max_per_account])
    return tasks


def validate_wechat_session(profile_root: str, daily_profile_root: str, url: str) -> None:
    if Path(profile_root).resolve() == Path(daily_profile_root).resolve():
        raise ValueError("dedicated WeChat browser profile required")
    host = (urlparse(url).hostname or "").lower()
    if host not in {"mp.weixin.qq.com", "weixin.qq.com"}:
        raise ValueError(f"unregistered WeChat domain: {host}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest_entries(root: Path, excluded_names: tuple[str, ...] = ("SHA256SUMS", "BATCH_SHA256SUMS")) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in excluded_names
    }


def verify_manifest_entries(actual: dict[str, str], declared: dict[str, str]) -> list[str]:
    problems = [f"{path}: missing from actual" for path in sorted(set(declared) - set(actual))]
    problems.extend(f"{path}: missing from manifest" for path in sorted(set(actual) - set(declared)))
    problems.extend(
        f"{path}: hash mismatch"
        for path in sorted(set(actual) & set(declared))
        if actual[path] != declared[path]
    )
    return problems


@dataclass(frozen=True)
class BatchSeal:
    entries: dict[str, str]

    @classmethod
    def capture(cls, root: Path) -> "BatchSeal":
        return cls(manifest_entries(root))

    def verify(self, root: Path) -> bool:
        return not verify_manifest_entries(manifest_entries(root), self.entries)


def resolve_legal_effect(republication_reachable: bool, authority_effect: str) -> str:
    del republication_reachable
    return authority_effect


class RequestGuard:
    def __init__(self, allowed_urls: list[str]):
        self.allowed_urls = tuple(allowed_urls)
        self.requests: list[str] = []

    def record(self, url: str, request_kind: str) -> None:
        if request_kind != "single_page" or url not in self.allowed_urls:
            raise ValueError("only registered single-page URLs are allowed")
        self.requests.append(url)


def derive_wjbs(
    category_code: str,
    authority_code: str,
    promulgation_date: str,
    official_document_sequence: int,
    file_category: str,
) -> tuple[str, dict[str, object]]:
    """Derive a 31-character WJBS body only from complete official components."""
    if not category_code.isdigit() or len(category_code) != 4:
        raise ValueError("category_code must be four digits")
    if not authority_code.isdigit() or len(authority_code) != 10:
        raise ValueError("authority_code must be ten digits")
    if not file_category.isdigit() or len(file_category) != 2:
        raise ValueError("file_category must be two digits")
    if not isinstance(official_document_sequence, int) or not 0 <= official_document_sequence <= 9999:
        raise ValueError("official_document_sequence must be 0..9999")
    try:
        date_component = datetime.strptime(promulgation_date, "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError as error:
        raise ValueError("promulgation_date must be YYYY-MM-DD") from error
    sequence_component = f"{official_document_sequence:04d}000"
    body = category_code + authority_code + date_component + sequence_component + file_category
    if len(body) != 31:
        raise AssertionError("WJBS body length invariant violated")
    evidence = {
        "WJBS_source_type": "STANDARD_DERIVED_LOCAL",
        "category_code": category_code,
        "authority_code": authority_code,
        "promulgation_date": promulgation_date,
        "official_document_sequence": official_document_sequence,
        "file_category": file_category,
        "sequence_component": sequence_component,
    }
    return f"1.2.156.3005.6-{body}", evidence
