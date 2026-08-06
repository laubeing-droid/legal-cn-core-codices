from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path


KIMI_FIELD_RE = re.compile(
    r"(?m)^(?:SXX|WJBS|WJBS_source_type)\s*:\s*.*(?:\r?\n)?"
)
EXTERNAL_STATUS_RE = re.compile(
    r"(\r?\n---[ \t]*\r?\n)status\s*:\s*[^\r\n]*(?:\r?\n)?",
    re.IGNORECASE,
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def recovery_candidates(
    current: bytes, legacy_status: str = ""
) -> list[tuple[str, bytes]]:
    text = current.decode("utf-8-sig")
    stripped = KIMI_FIELD_RE.sub("", text)
    stripped = EXTERNAL_STATUS_RE.sub(r"\1", stripped, count=1)
    candidates: list[tuple[str, bytes]] = []
    seen: set[str] = set()

    if legacy_status:
        frontmatter_end = re.search(r"\r?\n---[ \t]*\r?\n", stripped)
        if frontmatter_end:
            frontmatter = stripped[: frontmatter_end.end()]
            body = stripped[frontmatter_end.end() :]
            frontmatter = re.sub(
                r"(?m)^status\s*:\s*.*$",
                f'status: "{legacy_status}"',
                frontmatter,
                count=1,
            )
            restored_status = (frontmatter + body).replace("\r\n", "\n")
            restored_status = re.sub(
                r"\n---\n", "\n---\n\n", restored_status, count=1
            )
            candidates.append(
                (
                    "legacy_status_lf_blank_after_frontmatter",
                    restored_status.encode("utf-8"),
                )
            )

    for newline_name, newline in (("lf", "\n"), ("crlf", "\r\n")):
        normalized = stripped.replace("\r\n", "\n").replace("\n", newline)
        shapes = (
            ("plain", normalized),
            (
                "blank_after_frontmatter",
                re.sub(
                    re.escape(f"{newline}---{newline}"),
                    f"{newline}---{newline}{newline}",
                    normalized,
                    count=1,
                ),
            ),
            (
                "blank_before_frontmatter_end",
                re.sub(
                    re.escape(f"{newline}---{newline}"),
                    f"{newline}{newline}---{newline}",
                    normalized,
                    count=1,
                ),
            ),
        )
        for shape_name, candidate_text in shapes:
            for bom_name, prefix in (("", b""), ("_bom", b"\xef\xbb\xbf")):
                payload = prefix + candidate_text.encode("utf-8")
                digest = sha256_bytes(payload)
                if digest in seen:
                    continue
                seen.add(digest)
                candidates.append(
                    (f"{newline_name}_{shape_name}{bom_name}", payload)
                )
    return candidates


def recover_to_expected_hash(
    current: bytes, expected_sha256: str, legacy_status: str = ""
) -> tuple[str | None, bytes | None]:
    for strategy, candidate in recovery_candidates(current, legacy_status):
        if sha256_bytes(candidate) == expected_sha256.lower():
            return strategy, candidate
    return None, None


def load_source_metadata(
    source_records_path: Path | None,
) -> dict[str, dict[str, str | float]]:
    if source_records_path is None:
        return {}
    result: dict[str, dict[str, str | float]] = {}
    with source_records_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            value = row.get("last_write_time", "").strip()
            metadata: dict[str, str | float] = {
                "legacy_status": row.get("legacy_status", "").strip()
            }
            if value:
                metadata["mtime"] = datetime.fromisoformat(
                    value.replace("Z", "+00:00")
                ).timestamp()
            result[row["relative_path"].replace("\\", "/")] = metadata
    return result


def atomic_write(path: Path, payload: bytes, temporary_root: Path) -> None:
    temporary_root.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{sha256_bytes(str(path).encode('utf-8'))[:16]}-",
        suffix=".recovering",
        dir=temporary_root,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recover Kimi-mutated source Markdown only when baseline SHA-256 matches."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-records", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--temporary-root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    temporary_root = args.temporary_root or args.report.parent / ".recovery_tmp"

    source_metadata = load_source_metadata(args.source_records)
    report_rows: list[dict[str, str]] = []

    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    for row in rows:
        if row.get("changed_from_baseline") != "True" or row.get("has_SXX") != "True":
            continue
        relative_path = row["relative_path"].replace("\\", "/")
        source_path = args.source_root / Path(relative_path)
        expected_sha256 = row["baseline_sha256"].lower()
        current = source_path.read_bytes()
        metadata = source_metadata.get(relative_path, {})
        if sha256_bytes(current) == expected_sha256:
            strategy, recovered = "already_baseline", current
            status = "ALREADY_BASELINE"
        else:
            strategy, recovered = recover_to_expected_hash(
                current,
                expected_sha256,
                legacy_status=str(metadata.get("legacy_status", "")),
            )
            status = "MATCHED_NOT_APPLIED"
            if recovered is None:
                status = "UNMATCHED_LEFT_UNCHANGED"
        if recovered is not None and args.apply and status != "ALREADY_BASELINE":
            atomic_write(source_path, recovered, temporary_root)
            if "mtime" in metadata:
                timestamp = float(metadata["mtime"])
                os.utime(source_path, (timestamp, timestamp))
            if sha256_bytes(source_path.read_bytes()) != expected_sha256:
                raise RuntimeError(f"post-write hash mismatch: {relative_path}")
            status = "RESTORED_TO_BASELINE"
        report_rows.append(
            {
                "relative_path": relative_path,
                "expected_sha256": expected_sha256,
                "strategy": strategy or "",
                "status": status,
            }
        )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["relative_path", "expected_sha256", "strategy", "status"],
        )
        writer.writeheader()
        writer.writerows(report_rows)

    counts: dict[str, int] = {}
    for row in report_rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(counts)
    if temporary_root.exists() and not any(temporary_root.iterdir()):
        temporary_root.rmdir()
    return 0 if counts.get("UNMATCHED_LEFT_UNCHANGED", 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
