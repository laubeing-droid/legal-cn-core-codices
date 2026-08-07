#!/usr/bin/env python3
"""Publish one validated dataset through a verified draft GitHub Release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from prepare_dataset_release import prepare_release, sha256_file


REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
REQUIRED_CHECK_NAME = "audit"


def run_command(arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        arguments,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"COMMAND_FAILED:{arguments[0]}:{completed.returncode}:{detail}")
    return completed


def gh_json(arguments: list[str]) -> Any:
    completed = run_command(["gh", *arguments])
    return json.loads(completed.stdout)


def assert_github_ready() -> None:
    if shutil.which("gh") is None:
        raise RuntimeError("GH_CLI_NOT_FOUND")
    if not os.environ.get("GH_TOKEN"):
        raise RuntimeError("GH_TOKEN_NOT_CONFIGURED")
    run_command(["gh", "auth", "status", "--hostname", "github.com"])


def assert_repository(value: str) -> None:
    if not REPOSITORY_PATTERN.fullmatch(value):
        raise ValueError("GITHUB_REPOSITORY_INVALID")


def assert_required_audit(repository: str, commit_sha: str) -> None:
    payload = gh_json(
        [
            "api",
            "-H",
            "Accept: application/vnd.github+json",
            f"repos/{repository}/commits/{commit_sha}/check-runs?per_page=100",
        ]
    )
    accepted = [
        check
        for check in payload.get("check_runs", [])
        if check.get("name") == REQUIRED_CHECK_NAME
        and check.get("status") == "completed"
        and check.get("conclusion") == "success"
        and check.get("app", {}).get("slug") == "github-actions"
    ]
    if not accepted:
        raise RuntimeError(f"REQUIRED_CHECK_NOT_SUCCESSFUL:{REQUIRED_CHECK_NAME}")


def release_by_tag(repository: str, tag: str) -> dict[str, Any] | None:
    completed = run_command(
        [
            "gh",
            "release",
            "view",
            tag,
            "--repo",
            repository,
            "--json",
            "databaseId,isDraft,tagName,url",
        ],
        check=False,
    )
    if completed.returncode == 0:
        return json.loads(completed.stdout)
    message = f"{completed.stdout}\n{completed.stderr}".lower()
    if "release not found" in message or "not found" in message:
        return None
    raise RuntimeError(f"RELEASE_LOOKUP_FAILED:{completed.stderr.strip()}")


def release_api_payload(repository: str, tag: str) -> dict[str, Any]:
    release = release_by_tag(repository, tag)
    if release is None:
        raise RuntimeError(f"RELEASE_NOT_FOUND:{tag}")
    return gh_json(
        [
            "api",
            "-H",
            "Accept: application/vnd.github+json",
            f"repos/{repository}/releases/{release['databaseId']}",
        ]
    )


def retarget_draft_release(repository: str, tag: str, commit_sha: str) -> None:
    release = release_by_tag(repository, tag)
    if release is None:
        raise RuntimeError(f"RELEASE_NOT_FOUND:{tag}")
    payload = gh_json(
        [
            "api",
            "--method",
            "PATCH",
            f"repos/{repository}/releases/{release['databaseId']}",
            "-f",
            f"target_commitish={commit_sha}",
        ]
    )
    if not payload.get("draft"):
        raise RuntimeError("RELEASE_IS_NOT_DRAFT")
    if str(payload.get("target_commitish", "")).lower() != commit_sha.lower():
        raise RuntimeError("RELEASE_TARGET_COMMIT_MISMATCH")


def expected_asset_digests(release_directory: Path, asset_names: list[str]) -> dict[str, dict[str, object]]:
    return {
        name: {
            "size": (release_directory / name).stat().st_size,
            "digest": f"sha256:{sha256_file(release_directory / name)}",
        }
        for name in asset_names
    }


def verify_release_assets(
    repository: str,
    tag: str,
    expected: dict[str, dict[str, object]],
) -> None:
    last_error: RuntimeError | None = None
    for delay in (0, 2, 4, 8, 16):
        if delay:
            time.sleep(delay)
        payload = release_api_payload(repository, tag)
        actual = {asset["name"]: asset for asset in payload.get("assets", [])}
        if set(actual) != set(expected):
            last_error = RuntimeError(
                "RELEASE_ASSET_SET_MISMATCH:"
                f"expected={sorted(expected)}:actual={sorted(actual)}"
            )
            continue
        last_error = None
        for name, expected_metadata in expected.items():
            asset = actual[name]
            if asset.get("size") != expected_metadata["size"]:
                last_error = RuntimeError(f"RELEASE_ASSET_SIZE_MISMATCH:{name}")
                break
            digest = str(asset.get("digest") or "").lower()
            if digest != expected_metadata["digest"]:
                last_error = RuntimeError(f"RELEASE_ASSET_DIGEST_MISMATCH:{name}")
                break
        if last_error is None:
            return
    assert last_error is not None
    raise last_error


def replace_draft_assets(
    repository: str,
    tag: str,
    release_directory: Path,
    asset_names: list[str],
) -> None:
    payload = release_api_payload(repository, tag)
    if not payload.get("draft"):
        raise RuntimeError("RELEASE_IS_NOT_DRAFT")
    for asset in payload.get("assets", []):
        run_command(
            [
                "gh",
                "api",
                "--method",
                "DELETE",
                f"repos/{repository}/releases/assets/{asset['id']}",
            ]
        )
    run_command(
        [
            "gh",
            "release",
            "upload",
            tag,
            *(str(release_directory / name) for name in asset_names),
            "--repo",
            repository,
        ]
    )


def write_state_pointer(path: Path, engineering_root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.parent / f".{path.name}.staging-{uuid.uuid4().hex}"
    staging.write_text(str(engineering_root.resolve()) + "\n", encoding="utf-8", newline="\n")
    os.replace(staging, path)


def formal_tree_matches_release(formal_root: Path, manifest_path: Path) -> bool:
    if not (formal_root / "SHA256SUMS").is_file():
        return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest["dataset"]["source_sha256sums_sha256"]
    return sha256_file(formal_root / "SHA256SUMS") == expected


def publish_dataset_release(args: argparse.Namespace) -> dict[str, object]:
    assert_repository(args.repository)
    assert_github_ready()
    assert_required_audit(args.repository, args.commit_sha.lower())
    engineering_root = args.engineering_root.resolve()
    validation_report = engineering_root / "full_validation_report.json"
    prepared = prepare_release(
        candidate=args.candidate,
        validation_report_path=validation_report,
        output_directory=args.release_directory,
        engineering_batch=engineering_root.name,
        commit_sha=args.commit_sha,
        run_id=args.run_id,
    )
    release_directory = Path(str(prepared["output_directory"]))
    asset_names = [str(name) for name in prepared["asset_names"]]
    expected = expected_asset_digests(release_directory, asset_names)
    tag = str(prepared["tag"])
    existing = release_by_tag(args.repository, tag)
    if existing and not existing["isDraft"]:
        verify_release_assets(args.repository, tag, expected)
        if not formal_tree_matches_release(args.target.resolve(), release_directory / "dataset-manifest.json"):
            raise RuntimeError("PUBLISHED_RELEASE_FORMAL_TREE_MISMATCH")
        return {
            "status": "RELEASE_ALREADY_PUBLISHED",
            "tag": tag,
            "url": existing["url"],
        }

    if existing is None:
        run_command(
            [
                "gh",
                "release",
                "create",
                tag,
                "--repo",
                args.repository,
                "--draft",
                "--target",
                args.commit_sha.lower(),
                "--title",
                f"Dataset {prepared['tree_sha256'][:12]}",
                "--notes-file",
                str(Path(str(prepared["notes_path"]))),
            ]
        )

    retarget_draft_release(args.repository, tag, args.commit_sha.lower())
    replace_draft_assets(args.repository, tag, release_directory, asset_names)
    verify_release_assets(args.repository, tag, expected)

    publisher = Path(__file__).resolve().parent / "publish_validated_dataset.py"
    run_command(
        [
            sys.executable,
            str(publisher),
            str(args.candidate.resolve()),
            "--target",
            str(args.target.resolve()),
            "--engineering-root",
            str(engineering_root),
            "--current-engineering-root",
            str(args.current_engineering_root.resolve()),
            "--source-root",
            str(args.source_root.resolve()),
            "--deprecated-path",
            str(args.deprecated_path.resolve()),
            "--replace-validated-target",
        ]
    )
    write_state_pointer(args.state_pointer.resolve(), engineering_root)
    run_command(
        [
            "gh",
            "release",
            "edit",
            tag,
            "--repo",
            args.repository,
            "--draft=false",
            "--latest",
        ]
    )
    published = release_by_tag(args.repository, tag)
    if not published or published["isDraft"]:
        raise RuntimeError("RELEASE_PUBLICATION_NOT_CONFIRMED")
    latest = gh_json(["api", f"repos/{args.repository}/releases/latest"])
    if latest.get("tag_name") != tag:
        raise RuntimeError("RELEASE_NOT_LATEST")
    verify_release_assets(args.repository, tag, expected)
    return {
        "status": "DATASET_PUBLISHED",
        "tag": tag,
        "tree_sha256": prepared["tree_sha256"],
        "url": published["url"],
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--engineering-root", type=Path, required=True)
    parser.add_argument("--release-directory", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--current-engineering-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--deprecated-path", type=Path, required=True)
    parser.add_argument("--state-pointer", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--run-id", required=True)
    return parser.parse_args()


def main() -> int:
    result = publish_dataset_release(parse_arguments())
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
