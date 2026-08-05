#!/usr/bin/env python3
"""Atomically publish a candidate only after all local gates pass."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path

from validate_dataset import validate


DEFAULT_TARGET = Path(
    r"D:\Codex\1.法律工作区\legal-cn-core-codices开发区"
    r"\legal-cn-core-codices"
)
DEFAULT_SOURCE_ROOT = (
    Path(__file__).resolve().parent.parent
    / "workspace"
    / "source"
    / "legal-references"
)


def is_empty_directory(path: Path) -> bool:
    return path.is_dir() and next(path.iterdir(), None) is None


def assert_candidate_boundary(candidate: Path) -> None:
    if (candidate / "工程记录").exists():
        raise ValueError("FINAL_ENGINEERING_MIXED")
    if (candidate / "正式数据").exists():
        raise ValueError("LEGACY_FORMAL_WRAPPER")


def assert_unvalidated_backup_path(target: Path, backup: Path) -> Path:
    resolved_target = target.resolve()
    resolved_backup = backup.resolve()
    if resolved_backup.parent != resolved_target.parent:
        raise ValueError("BACKUP_NOT_SIBLING")
    expected = rf"{re.escape(resolved_target.name)}\.rollback_\d{{8}}_\d{{6}}"
    if not re.fullmatch(expected, resolved_backup.name):
        raise ValueError("BACKUP_NAME_INVALID")
    if resolved_backup.exists():
        raise ValueError("BACKUP_ALREADY_EXISTS")
    return resolved_backup


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", type=Path)
    parser.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_TARGET,
    )
    parser.add_argument(
        "--engineering-root",
        type=Path,
        required=True,
        help="与候选物理隔离的新工程记录批次目录",
    )
    parser.add_argument(
        "--current-engineering-root",
        type=Path,
        help="替换非空最终目录时，用于复验旧最终树的旧工程记录批次目录",
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
    parser.add_argument(
        "--replace-validated-target",
        action="store_true",
        help="仅在现有冻结目标已通过全量验证时允许原子替换",
    )
    parser.add_argument(
        "--replace-unvalidated-target-with-backup",
        action="store_true",
        help="旧最终树复验不合格时，保留时间戳备份后原子替换",
    )
    parser.add_argument(
        "--unvalidated-backup",
        type=Path,
        help="不合格旧最终树的同级备份路径，格式为目标名.rollback_YYYYMMDD_HHMMSS",
    )
    args = parser.parse_args()
    candidate = args.candidate.resolve()
    target = args.target.resolve()
    engineering_root = args.engineering_root.resolve()
    current_engineering_root = (
        args.current_engineering_root.resolve()
        if args.current_engineering_root
        else None
    )
    source_root = args.source_root.resolve()
    deprecated = args.deprecated_path.resolve()
    if args.replace_validated_target and args.replace_unvalidated_target_with_backup:
        raise SystemExit("两种替换模式不能同时使用")
    if bool(args.unvalidated_backup) != args.replace_unvalidated_target_with_backup:
        raise SystemExit(
            "--replace-unvalidated-target-with-backup与--unvalidated-backup必须同时提供"
        )
    unvalidated_backup = (
        assert_unvalidated_backup_path(target, args.unvalidated_backup)
        if args.unvalidated_backup
        else None
    )
    required_target = DEFAULT_TARGET.resolve()
    if target != required_target:
        raise SystemExit(f"拒绝非冻结目标：{target}")
    if deprecated.exists():
        raise SystemExit(f"废弃路径重新出现：{deprecated}")
    if not candidate.is_dir():
        raise SystemExit(f"候选目录不存在：{candidate}")
    assert_candidate_boundary(candidate)

    preflight = validate(candidate, source_root, deprecated, engineering_root)
    print(json.dumps({
        "phase": "preflight",
        "status": preflight["status"],
        "blocking_counts": preflight["blocking_counts"],
    }, ensure_ascii=False))
    if preflight["status"] != "LOCAL_FULLY_VALIDATED":
        return 2

    staging = target.parent / f".{target.name}.staging-{uuid.uuid4().hex}"
    previous = target.parent / f".{target.name}.previous-{uuid.uuid4().hex}"
    preserve_previous = False
    if staging.exists() or previous.exists():
        raise SystemExit("原子发布临时路径碰撞")
    shutil.copytree(candidate, staging)
    staged = validate(staging, source_root, deprecated, engineering_root)
    if staged["status"] != "LOCAL_FULLY_VALIDATED":
        shutil.rmtree(staging)
        raise SystemExit("复制后的暂存树未通过复验")

    target_was_empty = target.exists() and is_empty_directory(target)
    if target.exists() and not target_was_empty:
        if not (
            args.replace_validated_target
            or args.replace_unvalidated_target_with_backup
        ):
            shutil.rmtree(staging)
            raise SystemExit("最终目录非空；未授权替换")
        if current_engineering_root is None:
            shutil.rmtree(staging)
            raise SystemExit(
                "替换非空最终目录必须提供--current-engineering-root，"
                "禁止用新候选工程清单复验旧最终树"
            )
        current = validate(
            target,
            source_root,
            deprecated,
            current_engineering_root,
        )
        print(json.dumps({
            "phase": "current_target",
            "status": current["status"],
            "blocking_counts": current["blocking_counts"],
        }, ensure_ascii=False))
        if args.replace_validated_target and current["status"] != "LOCAL_FULLY_VALIDATED":
            shutil.rmtree(staging)
            raise SystemExit("现有最终目录未通过全量验证；拒绝替换")
        if args.replace_unvalidated_target_with_backup:
            if current["status"] == "LOCAL_FULLY_VALIDATED":
                shutil.rmtree(staging)
                raise SystemExit("现有最终目录已通过验证；应使用--replace-validated-target")
            previous = unvalidated_backup
            preserve_previous = True
    target_moved = False
    try:
        if target.exists():
            os.replace(target, previous)
            target_moved = True
        os.replace(staging, target)
        postflight = validate(target, source_root, deprecated, engineering_root)
        if postflight["status"] != "LOCAL_FULLY_VALIDATED":
            os.replace(target, staging)
            if previous.exists():
                os.replace(previous, target)
                target_moved = False
            raise RuntimeError("发布后复验失败，已回滚")
        if previous.exists():
            if target_was_empty:
                previous.rmdir()
            elif not preserve_previous:
                shutil.rmtree(previous)
    except BaseException:
        if target_moved and not target.exists() and previous.exists():
            os.replace(previous, target)
        if staging.exists():
            shutil.rmtree(staging)
        raise
    print(json.dumps({
        "phase": "published",
        "status": "LOCAL_FULLY_VALIDATED",
        "preserved_previous": str(previous) if preserve_previous else "",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
