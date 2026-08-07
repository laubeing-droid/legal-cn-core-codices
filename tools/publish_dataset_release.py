#!/usr/bin/env python3
"""Publish validated datasets as a rolling latest or immutable archive release."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from prepare_dataset_release import load_validation_report, prepare_release, sha256_file


REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
MILESTONE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
ARCHIVE_PERIOD_PATTERN = re.compile(r"[0-9]{4}Q[1-4]")
SAFE_SCHEMA_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
REQUIRED_CHECK_NAME = "audit"
LATEST_TAG = "dataset-latest"
CONFIRMATION = "CREATE_IMMUTABLE_RELEASE"
METADATA_ASSETS = {"dataset-manifest.json", "release-SHA256SUMS"}


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
    return json.loads(run_command(["gh", *arguments]).stdout)


def gh_api_json(repository: str, endpoint: str, method: str, payload: dict[str, object]) -> Any:
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as stream:
        json.dump(payload, stream, ensure_ascii=False)
        payload_path = Path(stream.name)
    try:
        return gh_json(
            ["api", "--method", method, f"repos/{repository}/{endpoint}", "--input", str(payload_path)]
        )
    finally:
        payload_path.unlink(missing_ok=True)


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
        ["api", "-H", "Accept: application/vnd.github+json", f"repos/{repository}/commits/{commit_sha}/check-runs?per_page=100"]
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


def validate_release_options(args: argparse.Namespace) -> None:
    if args.release_mode not in {"latest", "quarterly", "milestone"}:
        raise ValueError("RELEASE_MODE_INVALID")
    if args.release_mode == "milestone":
        if not MILESTONE_PATTERN.fullmatch(args.milestone_name or ""):
            raise ValueError("MILESTONE_NAME_INVALID")
        if args.milestone_confirm != CONFIRMATION:
            raise ValueError("MILESTONE_CONFIRMATION_REQUIRED")
    elif args.milestone_name or args.milestone_confirm:
        raise ValueError("MILESTONE_OPTIONS_REQUIRE_MILESTONE_MODE")
    if args.archive_period and not ARCHIVE_PERIOD_PATTERN.fullmatch(args.archive_period):
        raise ValueError("ARCHIVE_PERIOD_INVALID")


def current_quarter(now: dt.datetime | None = None) -> str:
    instant = now or dt.datetime.now(dt.timezone.utc)
    return f"{instant.year}Q{((instant.month - 1) // 3) + 1}"


def release_tag(mode: str, tree_sha256: str, *, milestone_name: str = "", archive_period: str = "") -> str:
    short_hash = tree_sha256[:16]
    if mode == "latest":
        return LATEST_TAG
    if mode == "quarterly":
        period = archive_period or current_quarter()
        if not ARCHIVE_PERIOD_PATTERN.fullmatch(period):
            raise ValueError("ARCHIVE_PERIOD_INVALID")
        return f"dataset-{period}-{short_hash}"
    if mode == "milestone":
        if not MILESTONE_PATTERN.fullmatch(milestone_name):
            raise ValueError("MILESTONE_NAME_INVALID")
        return f"dataset-milestone-{milestone_name}-{short_hash}"
    raise ValueError("RELEASE_MODE_INVALID")


def schema_release_tag(schema_version: str, tree_sha256: str) -> str:
    if not SAFE_SCHEMA_PATTERN.fullmatch(schema_version):
        raise ValueError("SCHEMA_VERSION_INVALID")
    return f"dataset-schema-{schema_version}-{tree_sha256[:16]}"


def schema_archive_required(old_schema: str, new_schema: str, schema_release: dict[str, Any] | None) -> bool:
    return old_schema != new_schema or bool(schema_release and schema_release.get("isDraft"))


def release_by_tag(repository: str, tag: str) -> dict[str, Any] | None:
    last_error = ""
    for delay in (0, 2, 4, 8, 16):
        if delay:
            time.sleep(delay)
        completed = run_command(
            ["gh", "release", "view", tag, "--repo", repository, "--json", "databaseId,isDraft,tagName,url"],
            check=False,
        )
        if completed.returncode == 0:
            return json.loads(completed.stdout)
        message = f"{completed.stdout}\n{completed.stderr}".lower()
        if "release not found" in message or "not found" in message:
            return None
        last_error = completed.stderr.strip() or completed.stdout.strip()
    raise RuntimeError(f"RELEASE_LOOKUP_FAILED:{last_error}")


def release_api_payload(repository: str, tag: str) -> dict[str, Any]:
    release = release_by_tag(repository, tag)
    if release is None:
        raise RuntimeError(f"RELEASE_NOT_FOUND:{tag}")
    return gh_json(["api", "-H", "Accept: application/vnd.github+json", f"repos/{repository}/releases/{release['databaseId']}"])


def expected_asset_digests(release_directory: Path, asset_names: list[str]) -> dict[str, dict[str, object]]:
    return {
        name: {"size": (release_directory / name).stat().st_size, "digest": f"sha256:{sha256_file(release_directory / name)}"}
        for name in asset_names
    }


def verify_asset_subset(
    repository: str,
    tag: str,
    expected: dict[str, dict[str, object]],
    *,
    remote_prefix: str = "",
    exact: bool = False,
) -> None:
    last_error: RuntimeError | None = None
    for delay in (0, 2, 4, 8, 16):
        if delay:
            time.sleep(delay)
        actual = {asset["name"]: asset for asset in release_api_payload(repository, tag).get("assets", [])}
        required = {f"{remote_prefix}{name}" for name in expected}
        if exact and set(actual) != required:
            last_error = RuntimeError(f"RELEASE_ASSET_SET_MISMATCH:expected={sorted(required)}:actual={sorted(actual)}")
            continue
        if not required.issubset(actual):
            last_error = RuntimeError(f"RELEASE_ASSET_MISSING:{sorted(required - set(actual))}")
            continue
        last_error = None
        for name, metadata in expected.items():
            asset = actual[f"{remote_prefix}{name}"]
            if asset.get("size") != metadata["size"]:
                last_error = RuntimeError(f"RELEASE_ASSET_SIZE_MISMATCH:{name}")
                break
            if str(asset.get("digest") or "").lower() != metadata["digest"]:
                last_error = RuntimeError(f"RELEASE_ASSET_DIGEST_MISMATCH:{name}")
                break
        if last_error is None:
            return
    assert last_error is not None
    raise last_error


def verify_release_assets(repository: str, tag: str, expected: dict[str, dict[str, object]], **_: object) -> None:
    verify_asset_subset(repository, tag, expected, exact=True)


def verify_release_shape(repository: str, tag: str, asset_names: list[str]) -> None:
    assets = assets_by_name(repository, tag)
    if set(assets) != set(asset_names):
        raise RuntimeError(f"RELEASE_ASSET_SET_MISMATCH:expected={sorted(asset_names)}:actual={sorted(assets)}")
    for name, asset in assets.items():
        if int(asset.get("size", 0)) <= 0 or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", str(asset.get("digest") or "").lower()
        ):
            raise RuntimeError(f"RELEASE_ASSET_METADATA_INVALID:{name}")


def create_draft(repository: str, tag: str, commit_sha: str, title: str, notes_path: Path) -> None:
    run_command(
        ["gh", "release", "create", tag, "--repo", repository, "--draft", "--target", commit_sha, "--title", title, "--notes-file", str(notes_path)]
    )


def update_release(repository: str, tag: str, *, commit_sha: str, title: str, notes_path: Path, draft: bool, latest: bool) -> dict[str, Any]:
    release = release_by_tag(repository, tag)
    if release is None:
        raise RuntimeError(f"RELEASE_NOT_FOUND:{tag}")
    return gh_api_json(
        repository,
        f"releases/{release['databaseId']}",
        "PATCH",
        {
            "target_commitish": commit_sha,
            "name": title,
            "body": notes_path.read_text(encoding="utf-8"),
            "draft": draft,
            "make_latest": "true" if latest else "false",
        },
    )


def move_tag(repository: str, tag: str, commit_sha: str) -> None:
    gh_api_json(repository, f"git/refs/tags/{tag}", "PATCH", {"sha": commit_sha, "force": True})


def verify_tag_target(repository: str, tag: str, commit_sha: str) -> None:
    payload = gh_json(["api", f"repos/{repository}/git/ref/tags/{tag}"])
    if str(payload.get("object", {}).get("sha", "")).lower() != commit_sha.lower():
        raise RuntimeError("RELEASE_TAG_TARGET_MISMATCH")


def replace_draft_assets(repository: str, tag: str, release_directory: Path, asset_names: list[str]) -> None:
    payload = release_api_payload(repository, tag)
    if not payload.get("draft"):
        raise RuntimeError("RELEASE_IS_NOT_DRAFT")
    for asset in payload.get("assets", []):
        delete_asset(repository, int(asset["id"]))
    upload_assets(repository, tag, release_directory, asset_names)


def upload_assets(repository: str, tag: str, directory: Path, names: list[str]) -> None:
    run_command(["gh", "release", "upload", tag, *(str(directory / name) for name in names), "--repo", repository])


def upload_prefixed_assets(repository: str, tag: str, release_directory: Path, asset_names: list[str], prefix: str) -> None:
    with tempfile.TemporaryDirectory(dir=release_directory.parent) as directory:
        aliases = Path(directory)
        alias_names: list[str] = []
        for name in asset_names:
            alias_name = f"{prefix}{name}"
            alias = aliases / alias_name
            try:
                os.link(release_directory / name, alias)
            except OSError:
                shutil.copyfile(release_directory / name, alias)
            alias_names.append(alias_name)
        upload_assets(repository, tag, aliases, alias_names)


def rename_asset(repository: str, asset_id: int, name: str) -> None:
    payload = gh_api_json(repository, f"releases/assets/{asset_id}", "PATCH", {"name": name})
    if payload.get("name") != name:
        raise RuntimeError(f"RELEASE_ASSET_RENAME_FAILED:{asset_id}:{name}")


def delete_asset(repository: str, asset_id: int) -> None:
    run_command(["gh", "api", "--method", "DELETE", f"repos/{repository}/releases/assets/{asset_id}"])


def assets_by_name(repository: str, tag: str) -> dict[str, dict[str, Any]]:
    return {asset["name"]: asset for asset in release_api_payload(repository, tag).get("assets", [])}


def clean_interrupted_latest(repository: str, asset_names: list[str]) -> None:
    assets = assets_by_name(repository, LATEST_TAG)
    if any(name.startswith(("next-", "previous-", "rollback-")) for name in assets):
        for final_name in asset_names:
            previous = next((asset for name, asset in assets.items() if name.startswith("previous-") and name.endswith(f"--{final_name}")), None)
            current = assets.get(final_name)
            if previous:
                if current:
                    rename_asset(repository, int(current["id"]), f"rollback-recovery--{final_name}")
                rename_asset(repository, int(previous["id"]), final_name)
        assets = assets_by_name(repository, LATEST_TAG)
        for name, asset in assets.items():
            if name.startswith(("next-", "previous-", "rollback-")):
                delete_asset(repository, int(asset["id"]))


def switch_latest_assets(repository: str, expected: dict[str, dict[str, object]], run_id: str) -> None:
    next_prefix = f"next-{run_id}--"
    previous_prefix = f"previous-{run_id}--"
    names = list(expected)
    try:
        assets = assets_by_name(repository, LATEST_TAG)
        for name in names:
            rename_asset(repository, int(assets[name]["id"]), f"{previous_prefix}{name}")
        assets = assets_by_name(repository, LATEST_TAG)
        for name in names:
            rename_asset(repository, int(assets[f"{next_prefix}{name}"]["id"]), name)
        verify_asset_subset(repository, LATEST_TAG, expected)
    except BaseException as cutover_error:
        try:
            assets = assets_by_name(repository, LATEST_TAG)
            for name in names:
                previous = assets.get(f"{previous_prefix}{name}")
                current = assets.get(name)
                if previous:
                    if current:
                        rename_asset(repository, int(current["id"]), f"rollback-{run_id}--{name}")
                    rename_asset(repository, int(previous["id"]), name)
            assets = assets_by_name(repository, LATEST_TAG)
            for name, asset in assets.items():
                if name.startswith((next_prefix, previous_prefix, f"rollback-{run_id}--")):
                    delete_asset(repository, int(asset["id"]))
        except BaseException as rollback_error:
            raise RuntimeError(f"LATEST_CUTOVER_ROLLBACK_FAILED:{rollback_error}") from cutover_error
        raise RuntimeError("LATEST_CUTOVER_ROLLED_BACK") from cutover_error
    assets = assets_by_name(repository, LATEST_TAG)
    for name, asset in assets.items():
        if name.startswith(previous_prefix):
            delete_asset(repository, int(asset["id"]))


def download_manifest(repository: str, tag: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as directory:
        run_command(["gh", "release", "download", tag, "--repo", repository, "--pattern", "dataset-manifest.json", "--dir", directory, "--clobber"])
        return json.loads((Path(directory) / "dataset-manifest.json").read_text(encoding="utf-8"))


def verify_published_immutable(
    repository: str,
    tag: str,
    prepared: dict[str, object],
) -> None:
    directory = Path(str(prepared["output_directory"]))
    names = [str(name) for name in prepared["asset_names"]]
    expected = expected_asset_digests(directory, names)
    verify_release_shape(repository, tag, names)
    verify_asset_subset(
        repository,
        tag,
        {name: metadata for name, metadata in expected.items() if name not in METADATA_ASSETS},
    )
    remote_manifest = download_manifest(repository, tag)
    local_manifest = json.loads((directory / "dataset-manifest.json").read_text(encoding="utf-8"))
    if remote_manifest.get("release", {}).get("tag") != tag:
        raise RuntimeError("IMMUTABLE_MANIFEST_TAG_MISMATCH")
    for field in ("tree_sha256", "schema_version", "source_sha256sums_sha256"):
        if remote_manifest.get("dataset", {}).get(field) != local_manifest.get("dataset", {}).get(field):
            raise RuntimeError(f"IMMUTABLE_MANIFEST_MISMATCH:{field}")


def write_state_pointer(path: Path, engineering_root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.parent / f".{path.name}.staging-{uuid.uuid4().hex}"
    staging.write_text(str(engineering_root.resolve()) + "\n", encoding="utf-8", newline="\n")
    os.replace(staging, path)


def formal_tree_matches_release(formal_root: Path, manifest_path: Path) -> bool:
    if not (formal_root / "SHA256SUMS").is_file():
        return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return sha256_file(formal_root / "SHA256SUMS") == manifest["dataset"]["source_sha256sums_sha256"]


def publish_formal_tree(args: argparse.Namespace, engineering_root: Path) -> None:
    publisher = Path(__file__).resolve().parent / "publish_validated_dataset.py"
    run_command(
        [
            sys.executable,
            str(publisher),
            str(args.candidate.resolve()),
            "--target", str(args.target.resolve()),
            "--engineering-root", str(engineering_root),
            "--current-engineering-root", str(args.current_engineering_root.resolve()),
            "--source-root", str(args.source_root.resolve()),
            "--deprecated-path", str(args.deprecated_path.resolve()),
            "--replace-validated-target",
        ]
    )
    write_state_pointer(args.state_pointer.resolve(), engineering_root)


def publish_immutable(repository: str, tag: str, prepared: dict[str, object], commit_sha: str) -> str:
    release_directory = Path(str(prepared["output_directory"]))
    asset_names = [str(name) for name in prepared["asset_names"]]
    expected = expected_asset_digests(release_directory, asset_names)
    existing = release_by_tag(repository, tag)
    if existing and not existing["isDraft"]:
        verify_published_immutable(repository, tag, prepared)
        return str(existing["url"])
    if existing is None:
        create_draft(repository, tag, commit_sha, f"Dataset {tag}", Path(str(prepared["notes_path"])))
        replace_draft_assets(repository, tag, release_directory, asset_names)
    else:
        update_release(repository, tag, commit_sha=commit_sha, title=f"Dataset {tag}", notes_path=Path(str(prepared["notes_path"])), draft=True, latest=False)
        try:
            verify_release_assets(repository, tag, expected)
        except RuntimeError:
            replace_draft_assets(repository, tag, release_directory, asset_names)
    verify_release_assets(repository, tag, expected)
    update_release(repository, tag, commit_sha=commit_sha, title=f"Dataset {tag}", notes_path=Path(str(prepared["notes_path"])), draft=False, latest=False)
    published = release_by_tag(repository, tag)
    if not published or published["isDraft"]:
        raise RuntimeError("IMMUTABLE_RELEASE_PUBLICATION_NOT_CONFIRMED")
    verify_release_assets(repository, tag, expected)
    return str(published["url"])


def stage_immutable(repository: str, tag: str, prepared: dict[str, object], commit_sha: str) -> None:
    directory = Path(str(prepared["output_directory"]))
    names = [str(name) for name in prepared["asset_names"]]
    expected = expected_asset_digests(directory, names)
    existing = release_by_tag(repository, tag)
    if existing and not existing["isDraft"]:
        verify_published_immutable(repository, tag, prepared)
        return
    if existing is None:
        create_draft(repository, tag, commit_sha, f"Dataset {tag}", Path(str(prepared["notes_path"])))
    else:
        update_release(repository, tag, commit_sha=commit_sha, title=f"Dataset {tag}", notes_path=Path(str(prepared["notes_path"])), draft=True, latest=False)
    replace_draft_assets(repository, tag, directory, names)
    verify_release_assets(repository, tag, expected)


def prepare_for_tag(args: argparse.Namespace, engineering_root: Path, tag: str, directory: Path | None = None) -> dict[str, object]:
    return prepare_release(
        candidate=args.candidate,
        validation_report_path=engineering_root / "full_validation_report.json",
        output_directory=directory or args.release_directory,
        engineering_batch=engineering_root.name,
        commit_sha=args.commit_sha.lower(),
        run_id=args.run_id,
        release_tag=tag,
    )


def initialize_latest(
    args: argparse.Namespace,
    prepared: dict[str, object],
    engineering_root: Path,
    existing: dict[str, Any] | None = None,
) -> dict[str, object]:
    directory = Path(str(prepared["output_directory"]))
    names = [str(name) for name in prepared["asset_names"]]
    expected = expected_asset_digests(directory, names)
    if existing is None:
        create_draft(args.repository, LATEST_TAG, args.commit_sha.lower(), "Dataset latest", Path(str(prepared["notes_path"])))
    else:
        update_release(args.repository, LATEST_TAG, commit_sha=args.commit_sha.lower(), title="Dataset latest", notes_path=Path(str(prepared["notes_path"])), draft=True, latest=False)
    replace_draft_assets(args.repository, LATEST_TAG, directory, names)
    verify_release_assets(args.repository, LATEST_TAG, expected)
    publish_formal_tree(args, engineering_root)
    update_release(args.repository, LATEST_TAG, commit_sha=args.commit_sha.lower(), title="Dataset latest", notes_path=Path(str(prepared["notes_path"])), draft=False, latest=True)
    verify_release_assets(args.repository, LATEST_TAG, expected)
    latest = gh_json(["api", f"repos/{args.repository}/releases/latest"])
    if latest.get("tag_name") != LATEST_TAG:
        raise RuntimeError("RELEASE_NOT_LATEST")
    return {"status": "LATEST_UPDATED", "snapshot_required": True, "tag": LATEST_TAG, "tree_sha256": prepared["tree_sha256"], "release_directory": str(directory)}


def publish_latest(args: argparse.Namespace, prepared: dict[str, object], engineering_root: Path) -> dict[str, object]:
    directory = Path(str(prepared["output_directory"]))
    names = [str(name) for name in prepared["asset_names"]]
    expected = expected_asset_digests(directory, names)
    existing = release_by_tag(args.repository, LATEST_TAG)
    if existing is None:
        return initialize_latest(args, prepared, engineering_root)
    if existing["isDraft"]:
        return initialize_latest(args, prepared, engineering_root, existing)
    clean_interrupted_latest(args.repository, names)
    old_manifest = download_manifest(args.repository, LATEST_TAG)
    new_manifest = json.loads((directory / "dataset-manifest.json").read_text(encoding="utf-8"))
    old_tree = old_manifest["dataset"]["tree_sha256"]
    old_schema = str(old_manifest["dataset"].get("schema_version", ""))
    new_schema = str(new_manifest["dataset"].get("schema_version", ""))
    schema_tag = schema_release_tag(new_schema, str(prepared["tree_sha256"]))
    schema_needed = schema_archive_required(old_schema, new_schema, release_by_tag(args.repository, schema_tag))
    schema_prepared: dict[str, object] | None = None
    if schema_needed:
        schema_prepared = prepare_for_tag(args, engineering_root, schema_tag, directory.parent / f"{directory.name}-schema")
        stage_immutable(args.repository, schema_tag, schema_prepared, args.commit_sha.lower())
    payload_expected = {name: metadata for name, metadata in expected.items() if name not in METADATA_ASSETS}
    if old_tree == prepared["tree_sha256"]:
        verify_asset_subset(args.repository, LATEST_TAG, payload_expected)
        verify_release_shape(args.repository, LATEST_TAG, names)
        verify_tag_target(args.repository, LATEST_TAG, str(old_manifest["release"]["commit_sha"]))
        latest = gh_json(["api", f"repos/{args.repository}/releases/latest"])
        if latest.get("tag_name") != LATEST_TAG:
            raise RuntimeError("RELEASE_NOT_LATEST")
        if not formal_tree_matches_release(args.target.resolve(), directory / "dataset-manifest.json"):
            raise RuntimeError("LATEST_FORMAL_TREE_MISMATCH")
        if schema_prepared:
            publish_immutable(args.repository, schema_tag, schema_prepared, args.commit_sha.lower())
        return {"status": "LATEST_UNCHANGED", "snapshot_required": False, "tag": LATEST_TAG, "tree_sha256": prepared["tree_sha256"], "release_directory": str(directory)}
    next_prefix = f"next-{args.run_id}--"
    upload_prefixed_assets(args.repository, LATEST_TAG, directory, names, next_prefix)
    verify_asset_subset(args.repository, LATEST_TAG, expected, remote_prefix=next_prefix)
    publish_formal_tree(args, engineering_root)
    switch_latest_assets(args.repository, expected, args.run_id)
    move_tag(args.repository, LATEST_TAG, args.commit_sha.lower())
    update_release(args.repository, LATEST_TAG, commit_sha=args.commit_sha.lower(), title="Dataset latest", notes_path=Path(str(prepared["notes_path"])), draft=False, latest=True)
    verify_release_assets(args.repository, LATEST_TAG, expected)
    if not formal_tree_matches_release(args.target.resolve(), directory / "dataset-manifest.json"):
        raise RuntimeError("LATEST_FORMAL_TREE_MISMATCH")
    if schema_prepared:
        publish_immutable(args.repository, schema_tag, schema_prepared, args.commit_sha.lower())
    return {"status": "LATEST_UPDATED", "snapshot_required": True, "tag": LATEST_TAG, "tree_sha256": prepared["tree_sha256"], "release_directory": str(directory), "schema_release": schema_tag if schema_prepared else ""}


def publish_dataset_release(args: argparse.Namespace) -> dict[str, object]:
    validate_release_options(args)
    assert_repository(args.repository)
    assert_github_ready()
    assert_required_audit(args.repository, args.commit_sha.lower())
    engineering_root = args.engineering_root.resolve()
    report = load_validation_report(engineering_root / "full_validation_report.json")
    tree_sha256 = str(report["artifact_tree_sha256"])
    if args.release_mode == "quarterly":
        tag = release_tag("quarterly", tree_sha256, archive_period=args.archive_period)
        prepared = prepare_for_tag(args, engineering_root, tag)
        url = publish_immutable(args.repository, tag, prepared, args.commit_sha.lower())
        return {"status": "QUARTERLY_ARCHIVED", "snapshot_required": False, "tag": tag, "tree_sha256": tree_sha256, "url": url, "release_directory": str(args.release_directory.resolve())}
    prepared = prepare_for_tag(args, engineering_root, LATEST_TAG)
    milestone_tag = ""
    milestone_prepared: dict[str, object] | None = None
    if args.release_mode == "milestone":
        milestone_tag = release_tag("milestone", tree_sha256, milestone_name=args.milestone_name)
        milestone_prepared = prepare_for_tag(args, engineering_root, milestone_tag, args.release_directory.parent / f"{args.release_directory.name}-milestone")
        stage_immutable(args.repository, milestone_tag, milestone_prepared, args.commit_sha.lower())
    latest_result = publish_latest(args, prepared, engineering_root)
    if args.release_mode == "latest":
        return latest_result
    assert milestone_prepared is not None
    url = publish_immutable(args.repository, milestone_tag, milestone_prepared, args.commit_sha.lower())
    return {"status": "MILESTONE_ARCHIVED", "latest_status": latest_result["status"], "snapshot_required": latest_result["snapshot_required"], "tag": milestone_tag, "tree_sha256": tree_sha256, "url": url, "release_directory": latest_result["release_directory"]}


def parse_arguments(arguments: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-mode", choices=("latest", "quarterly", "milestone"), required=True)
    parser.add_argument("--milestone-name", default="")
    parser.add_argument("--milestone-confirm", default="")
    parser.add_argument("--archive-period", default="")
    parser.add_argument("--result-path", type=Path, required=True)
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
    return parser.parse_args(arguments)


def main() -> int:
    args = parse_arguments()
    result = publish_dataset_release(args)
    args.result_path.parent.mkdir(parents=True, exist_ok=True)
    args.result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
