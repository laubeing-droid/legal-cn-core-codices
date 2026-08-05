from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

from repair_delivery_tree import expected_directory, sha256


WJBS = re.compile(r"1\.2\.156\.3005\.6-(\d{31})")
ALLOWED_TOP_LEVEL = {
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


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-records", type=Path, required=True)
    parser.add_argument("--ingest-queue", type=Path, required=True)
    parser.add_argument("--repairs", type=Path, required=True)
    parser.add_argument("--standard-coding", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    checksum_lines = (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    checksums = dict(line.split("  ", 1)[::-1] for line in checksum_lines if line)
    issues: list[dict[str, str]] = []

    def issue(code: str, path: str, detail: str = "") -> None:
        issues.append({"code": code, "path": path, "detail": detail})

    for relative in checksums:
        top = relative.split("/", 1)[0]
        if "/" in relative and top not in ALLOWED_TOP_LEVEL:
            issue("UNEXPECTED_TOP_LEVEL_DIRECTORY", relative)
        if "/" not in relative or relative == "00_法律检索导航与效力适用规则/README.md":
            path = root / Path(relative)
            if not path.is_file() or sha256(path) != checksums[relative]:
                issue("ROOT_OR_NAVIGATION_HASH_MISMATCH", relative)

    source_types = {
        row["source_relative_path"]: row.get("object_type", "")
        for row in read_csv(args.source_records)
    }
    queue = read_csv(args.ingest_queue)
    expected_paths: set[str] = set()
    path_to_source: dict[str, str] = {}
    for row in queue:
        source_relative = row["source_relative_path"]
        original = row["target_relative_path"].replace("\\", "/")
        expected, _ = expected_directory(
            source_relative, original, source_types.get(source_relative, "")
        )
        current = f"{expected}/{Path(original).name}" if expected else original
        expected_paths.add(current)
        path_to_source[current] = source_relative
        if current not in checksums:
            issue("MAPPED_TARGET_MISSING", current, source_relative)

    repair_rows = read_csv(args.repairs)
    for row in repair_rows:
        old_relative = row["from_relative_path"]
        new_relative = row["to_relative_path"]
        if (root / Path(old_relative)).exists():
            issue("OLD_PATH_STILL_EXISTS", old_relative)
        target = root / Path(new_relative)
        if not target.is_file():
            issue("REPAIR_TARGET_MISSING", new_relative)
        elif checksums.get(new_relative) != sha256(target):
            issue("REPAIR_TARGET_HASH_MISMATCH", new_relative)

    for directory in root.rglob("*"):
        if directory.is_dir() and not any(directory.iterdir()):
            issue("EMPTY_DIRECTORY", directory.relative_to(root).as_posix())

    coding_reasons = {
        row["relative_path"]: row.get("blocking_reason", "")
        for row in read_csv(args.standard_coding)
    }
    wjbs_coverage: dict[str, dict[str, int]] = {}
    wjbs_reason_counts: Counter[str] = Counter()
    for prefix in [f"0{number}_" for number in range(1, 9)]:
        paths = [
            relative
            for relative in checksums
            if relative.startswith(prefix) and relative.endswith(".md")
        ]
        present = sum(bool(WJBS.search(Path(relative).name)) for relative in paths)
        wjbs_coverage[prefix[:2]] = {
            "markdown": len(paths),
            "wjbs_present": present,
            "wjbs_missing": len(paths) - present,
        }
        for relative in paths:
            if not WJBS.search(Path(relative).name):
                source_relative = path_to_source.get(relative, "")
                detail = coding_reasons.get(source_relative, "NO_CODING_RECORD")
                if "AMBIGUOUS_INTERNAL_SEQUENCE" in detail:
                    reason = "AMBIGUOUS_INTERNAL_SEQUENCE"
                elif "ZDJGDM" in detail:
                    reason = "MISSING_AGENCY_CODE"
                elif "SXRQ" in detail or "GBRQ" in detail:
                    reason = "MISSING_DATE"
                else:
                    reason = "UNCLASSIFIED_CODING_BLOCKER"
                wjbs_reason_counts[reason] += 1
                issue("LEGAL_MARKDOWN_WJBS_MISSING", relative, detail)

    for relative in checksums:
        if relative.startswith(("10_", "80_", "81_", "82_", "89_")) and WJBS.search(
            Path(relative).name
        ):
            issue("NON_LEGAL_MATERIAL_HAS_WJBS", relative)

    legacy = "10_司法业务指导、会议纪要与公开答疑【非规范性法源】/03_法答网精选与法院业务答疑"
    if any(relative.startswith(legacy + "/") for relative in checksums):
        issue("LEGACY_MIXED_QA_PATH", legacy)

    counts = Counter(row["code"] for row in issues)
    blocking_without_wjbs = sum(
        count for code, count in counts.items() if code != "LEGAL_MARKDOWN_WJBS_MISSING"
    )
    summary = {
        "status": "PASS" if not issues else "BLOCKED",
        "checksum_rows": len(checksums),
        "mapped_records": len(queue),
        "mapped_targets_present": len(expected_paths)
        - counts.get("MAPPED_TARGET_MISSING", 0),
        "repair_rows": len(repair_rows),
        "issue_counts": dict(sorted(counts.items())),
        "non_wjbs_layout_blockers": blocking_without_wjbs,
        "wjbs_coverage": wjbs_coverage,
        "wjbs_reason_counts": dict(sorted(wjbs_reason_counts.items())),
    }
    with (output_root / "candidate_layout_issues.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as target:
        writer = csv.DictWriter(target, fieldnames=("code", "path", "detail"))
        writer.writeheader()
        writer.writerows(issues)
    (output_root / "candidate_layout_audit.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    sys.stdout.buffer.write((json.dumps(summary, ensure_ascii=False) + "\n").encode())
    return 0 if not blocking_without_wjbs else 2


if __name__ == "__main__":
    raise SystemExit(main())
