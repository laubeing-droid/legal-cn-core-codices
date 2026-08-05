#!/usr/bin/env python3
"""Validate the approved official-WeChat registry and materialize a bounded pilot batch."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


FIELDS = [
    "account_name",
    "wechat_id",
    "biz",
    "certified_entity",
    "certification_evidence_url",
    "article_url",
    "mid",
    "idx",
    "stable_key",
    "article_title",
    "published_at",
    "identity_status",
    "last_verified_at",
    "update_mode",
    "notes",
]
OFFICIAL_EVIDENCE_SUFFIXES = (
    ".gov.cn",
    ".court.gov.cn",
    ".spp.gov.cn",
)
WECHAT_HOSTS = {"mp.weixin.qq.com", "weixin.qq.com"}


def _official_evidence_host(host: str) -> bool:
    return host == "gov.cn" or any(host.endswith(suffix) for suffix in OFFICIAL_EVIDENCE_SUFFIXES)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_and_validate_registry(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != FIELDS:
            raise ValueError("registry header does not match the required schema")
        rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]

    problems: list[str] = []
    if not rows:
        problems.append("registry is empty")
    account_counts = Counter(row["account_name"] for row in rows)
    if len(account_counts) > 5:
        problems.append("pilot exceeds five accounts")
    for account, count in account_counts.items():
        if not account:
            problems.append("account_name is empty")
        if count > 20:
            problems.append(f"{account}: pilot exceeds twenty URLs")

    stable_keys: set[str] = set()
    article_urls: set[str] = set()
    for line_number, row in enumerate(rows, start=2):
        prefix = f"line {line_number}"
        article = urlparse(row["article_url"])
        evidence = urlparse(row["certification_evidence_url"])
        if article.scheme != "https" or (article.hostname or "").lower() not in WECHAT_HOSTS:
            problems.append(f"{prefix}: unregistered WeChat article host")
        if evidence.scheme != "https" or not _official_evidence_host((evidence.hostname or "").lower()):
            problems.append(f"{prefix}: official evidence host required")
        if not row["biz"] or not row["mid"].isdigit() or not row["idx"].isdigit():
            problems.append(f"{prefix}: biz/mid/idx incomplete")
        expected_key = f"WECHAT:{row['biz']}:{row['mid']}:{row['idx']}"
        if row["stable_key"] != expected_key:
            problems.append(f"{prefix}: stable_key mismatch")
        if row["stable_key"] in stable_keys:
            problems.append(f"{prefix}: duplicate stable_key")
        stable_keys.add(row["stable_key"])
        if row["article_url"] in article_urls:
            problems.append(f"{prefix}: duplicate article_url")
        article_urls.add(row["article_url"])
        for required in ("certified_entity", "article_title", "published_at", "last_verified_at"):
            if not row[required]:
                problems.append(f"{prefix}: {required} is empty")
        if row["identity_status"] != "OFFICIAL_IDENTITY_VERIFIED":
            problems.append(f"{prefix}: identity_status is not verified")
        if row["update_mode"] != "approved_pilot_single_url":
            problems.append(f"{prefix}: update_mode is outside the approved pilot")

    if problems:
        raise ValueError("; ".join(problems))
    return rows


def build_pilot_batch(registry_path: Path, output_dir: Path, *, approved: bool) -> dict[str, object]:
    if not approved:
        raise ValueError("explicit approval is required for the WeChat pilot")
    rows = load_and_validate_registry(registry_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    task_path = output_dir / "wechat_tasks.csv"
    with task_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "approval": "USER_APPROVED_3B",
        "registry_path": str(registry_path.resolve()),
        "registry_sha256": _sha256(registry_path),
        "task_file": str(task_path.resolve()),
        "task_file_sha256": _sha256(task_path),
        "account_count": len({row["account_name"] for row in rows}),
        "task_count": len(rows),
        "network_scope": "KNOWN_SINGLE_URL_ONLY",
        "limits": {"accounts": 5, "urls_per_account": 20},
    }
    manifest_path = output_dir / "batch_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=root / "config" / "official_wechat_accounts.csv")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--approved", action="store_true")
    args = parser.parse_args()
    summary = build_pilot_batch(args.registry, args.output, approved=args.approved)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
