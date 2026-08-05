from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
EXCHANGE_ROOT = (SCRIPT_DIR.parent.parent / "交换候选").resolve()


DIRECTORIES = {
    "constitution": "01_宪法/01_现行宪法",
    "constitution_amendment": "01_宪法/02_宪法修正案",
    "law": "02_法律/01_法律",
    "law_interpretation": "02_法律/02_法律解释",
    "major_decision": "02_法律/03_有关法律问题和重大问题的决定",
    "law_change": "02_法律/04_修改与废止决定",
    "administrative_regulation": "03_行政法规",
    "supervisory_regulation": "04_监察法规",
    "local_regulation": "05_地方立法/01_地方性法规",
    "autonomous_regulation": "05_地方立法/02_自治条例",
    "separate_regulation": "05_地方立法/03_单行条例",
    "sez_regulation": "05_地方立法/04_经济特区法规",
    "pudong_regulation": "05_地方立法/05_浦东新区法规",
    "hainan_ftp_regulation": "05_地方立法/06_海南自由贸易港法规",
    "ministry_rule": "06_规章/01_部门规章",
    "local_government_rule": "06_规章/02_地方政府规章",
    "spc_interpretation": "07_司法解释【独立规范类型】/01_最高人民法院司法解释",
    "spp_interpretation": "07_司法解释【独立规范类型】/02_最高人民检察院司法解释",
    "joint_interpretation": "07_司法解释【独立规范类型】/03_两高联合司法解释",
    "interpretation_change": "07_司法解释【独立规范类型】/04_修改与废止决定",
    "fadawang": "10_司法业务指导、会议纪要与公开答疑【非规范性法源】/03_法答网精选",
    "spc_qa": "10_司法业务指导、会议纪要与公开答疑【非规范性法源】/04_法院业务答疑/01_最高法法律问答批次汇编",
    "other_qa": "10_司法业务指导、会议纪要与公开答疑【非规范性法源】/04_法院业务答疑/02_其他法院公开答疑",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def title_from_target(target: str) -> str:
    stem = Path(target).stem
    return re.sub(r"_\d{4}-\d{2}-\d{2}.*$|_日期不详.*$", "", stem)


def category_from_target(target: str, title: str) -> str:
    match = re.search(r"1\.2\.156\.3005\.6-(\d{4})\d{27}\.md$", target)
    if match:
        return match.group(1)
    if target.startswith("01_宪法/"):
        return "0000"
    if target.startswith("02_法律/01_") or target.startswith("02_法律/04_"):
        return "0100"
    if target.startswith("02_法律/02_"):
        return "0300"
    if target.startswith("02_法律/03_"):
        return "0200"
    if target.startswith("03_行政法规/"):
        return "0400"
    if target.startswith("04_监察法规/"):
        return "0600"
    if target.startswith("05_地方立法/"):
        if "浦东新区" in title:
            return "0902"
        if "海南自由贸易港" in title:
            return "0903"
        if "经济特区" in title:
            return "0901"
        if target.startswith(("05_地方立法/02_", "05_地方立法/03_")):
            return "0800"
        return "0700"
    if target.startswith("06_规章/01_"):
        return "1300"
    if target.startswith("06_规章/02_"):
        return "1400"
    if target.startswith("07_司法解释"):
        return "1100"
    if target.startswith("08_其他规范性文件【非立法】/01_"):
        return "1600"
    if target.startswith("08_其他规范性文件【非立法】/02_"):
        return "1700"
    if target.startswith("08_其他规范性文件【非立法】/03_"):
        return "1900"
    if target.startswith("09_司法机关其他规范性文件【非司法解释】/01_"):
        return "2000"
    if target.startswith("09_司法机关其他规范性文件【非司法解释】/02_"):
        return "2100"
    return ""


def legal_directory(category: str, title: str) -> str:
    change = bool(re.search(r"修改|废止|失效|清理", title))
    if category == "0000":
        return DIRECTORIES["constitution_amendment" if "修正案" in title else "constitution"]
    if category == "0100":
        return DIRECTORIES["law_change" if change else "law"]
    if category == "0200":
        return DIRECTORIES["major_decision"]
    if category == "0300":
        return DIRECTORIES["law_interpretation"]
    if category == "0400":
        return DIRECTORIES["administrative_regulation"]
    if category == "0600":
        return DIRECTORIES["supervisory_regulation"]
    if category == "0700":
        return DIRECTORIES["local_regulation"]
    if category == "0800":
        return DIRECTORIES["autonomous_regulation" if "自治条例" in title else "separate_regulation"]
    if category == "0901":
        return DIRECTORIES["sez_regulation"]
    if category == "0902":
        return DIRECTORIES["pudong_regulation"]
    if category == "0903":
        return DIRECTORIES["hainan_ftp_regulation"]
    if category == "1100":
        if change:
            return DIRECTORIES["interpretation_change"]
        if re.search(r"最高人民法院.*最高人民检察院|最高人民检察院.*最高人民法院|两高", title):
            return DIRECTORIES["joint_interpretation"]
        return ""
    if category == "1300":
        return DIRECTORIES["ministry_rule"]
    if category == "1400":
        return DIRECTORIES["local_government_rule"]
    return ""


def expected_directory(source: str, target: str, object_type: str) -> tuple[str, str]:
    title = title_from_target(target)
    category = category_from_target(target, title)
    if object_type == "legal_document":
        expected = legal_directory(category, title)
        return expected, category
    qa = "02_法院系统/05_法答网精选与法院业务答疑/"
    if source.startswith(f"{qa}01_法答网精选/"):
        return DIRECTORIES["fadawang"], category
    if source.startswith(f"{qa}02_最高法法律问答批次汇编/"):
        return DIRECTORIES["spc_qa"], category
    if source.startswith(f"{qa}03_其他法院公开答疑/"):
        return DIRECTORIES["other_qa"], category
    return "", category


def remove_empty_directories(root: Path) -> int:
    removed = 0
    for directory in sorted((path for path in root.rglob("*") if path.is_dir()), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()
            removed += 1
    return removed


def update_csv_paths(root: Path, moves: dict[str, str]) -> int:
    updated = 0
    for name in (
        "cases.csv",
        "case_holdings.csv",
        "case_legal_references.csv",
        "practice_references.csv",
    ):
        path = root / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8-sig")
        original = text
        for source, target in moves.items():
            text = text.replace(source, target)
        if text != original:
            path.write_text(text, encoding="utf-8-sig", newline="")
            updated += 1
    return updated


def regenerate_checksums(root: Path) -> tuple[int, str]:
    checksum_path = root / "SHA256SUMS"
    checksum_path.unlink(missing_ok=True)
    files = sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda item: item.relative_to(root).as_posix(),
    )
    lines = [f"{sha256(path)}  {path.relative_to(root).as_posix()}" for path in files]
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return len(lines), sha256(checksum_path)


def remap_checksums(
    root: Path, baseline_path: Path, moves: dict[str, str]
) -> tuple[int, str]:
    checksum_path = root / "SHA256SUMS"
    entries: dict[str, str] = {}
    for line in baseline_path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        digest, relative = line.split("  ", 1)
        remapped = moves.get(relative.replace("\\", "/"), relative.replace("\\", "/"))
        if remapped in entries:
            raise ValueError(f"校验清单路径冲突: {remapped}")
        entries[remapped] = digest

    for old_relative, new_relative in moves.items():
        expected = entries.get(new_relative)
        target = root / Path(new_relative)
        if expected is None or not target.is_file():
            raise FileNotFoundError(f"增量哈希目标缺失: {new_relative}")
        actual = sha256(target)
        if actual != expected:
            raise ValueError(f"增量哈希不一致: {new_relative}")

    navigation_relative = "00_法律检索导航与效力适用规则/README.md"
    entries[navigation_relative] = sha256(root / Path(navigation_relative))
    for formal_csv in root.glob("*.csv"):
        entries[formal_csv.name] = sha256(formal_csv)
    missing = [relative for relative in entries if not (root / Path(relative)).is_file()]
    if missing:
        raise FileNotFoundError(f"校验清单存在缺失文件，共{len(missing)}项，首项: {missing[0]}")

    lines = [f"{entries[relative]}  {relative}" for relative in sorted(entries)]
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return len(lines), sha256(checksum_path)


def write_repairs(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = (
        "source_relative_path",
        "from_relative_path",
        "to_relative_path",
        "object_type",
        "category_code",
        "disposition",
    )
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--engineering-root", type=Path, required=True)
    parser.add_argument("--source-records", type=Path, required=True)
    parser.add_argument("--ingest-queue", type=Path, required=True)
    parser.add_argument("--baseline-sha256sums", type=Path)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.fix and (EXCHANGE_ROOT not in root.parents):
        raise SystemExit("--fix只允许修改交换候选目录")

    with args.source_records.open(encoding="utf-8-sig", newline="") as source:
        object_types = {
            row["source_relative_path"]: row["object_type"]
            for row in csv.DictReader(source)
        }
    repairs: list[dict[str, str]] = []
    moves: dict[str, str] = {}
    with args.ingest_queue.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            source_relative = row["source_relative_path"]
            target_relative = row["target_relative_path"].replace("\\", "/")
            if not target_relative:
                continue
            object_type = object_types.get(source_relative, "")
            expected, category = expected_directory(source_relative, target_relative, object_type)
            current = Path(target_relative).parent.as_posix()
            if not expected or current == expected:
                continue
            new_relative = f"{expected}/{Path(target_relative).name}"
            disposition = "AUDIT_ONLY"
            if args.fix:
                source_path = root / Path(target_relative)
                target_path = root / Path(new_relative)
                if not source_path.is_file():
                    if target_path.is_file():
                        disposition = "ALREADY_MOVED"
                        moves[target_relative] = new_relative
                    else:
                        raise FileNotFoundError(
                            f"修复源文件和目标文件均不存在: {source_path} -> {target_path}"
                        )
                    repairs.append(
                        {
                            "source_relative_path": source_relative,
                            "from_relative_path": target_relative,
                            "to_relative_path": new_relative,
                            "object_type": object_type,
                            "category_code": category,
                            "disposition": disposition,
                        }
                    )
                    continue
                target_path.parent.mkdir(parents=True, exist_ok=True)
                if target_path.exists():
                    if sha256(source_path) != sha256(target_path):
                        disposition = "CONFLICT_DIFFERENT_BYTES"
                    else:
                        source_path.unlink()
                        disposition = "DEDUPLICATE_IDENTICAL_BYTES"
                        moves[target_relative] = new_relative
                else:
                    source_path.replace(target_path)
                    disposition = "MOVE"
                    moves[target_relative] = new_relative
            repairs.append(
                {
                    "source_relative_path": source_relative,
                    "from_relative_path": target_relative,
                    "to_relative_path": new_relative,
                    "object_type": object_type,
                    "category_code": category,
                    "disposition": disposition,
                }
            )

    args.engineering_root.mkdir(parents=True, exist_ok=True)
    csv_tables_updated = 0
    empty_removed = 0
    checksum_rows = 0
    checksum_sha256 = ""
    if args.fix:
        csv_tables_updated = update_csv_paths(root, moves)
        navigation = root / "00_法律检索导航与效力适用规则"
        navigation.mkdir(parents=True, exist_ok=True)
        (navigation / "README.md").write_text(
            "# 法律检索导航与效力适用规则\n\n"
            "- 01—08为法律法规及其他规范性文件；以文件标识、效力状态和来源证据共同检索。\n"
            "- 09—10、80—82、89为司法业务材料或案例，不作为立法法意义上的规范层级。\n"
            "- Markdown是检索派生载体；正式结构化数据以根目录CSV及工程批次记录为准。\n",
            encoding="utf-8",
            newline="\n",
        )
        empty_removed = remove_empty_directories(root)
        if args.baseline_sha256sums:
            checksum_rows, checksum_sha256 = remap_checksums(
                root, args.baseline_sha256sums, moves
            )
        else:
            checksum_rows, checksum_sha256 = regenerate_checksums(root)

    write_repairs(args.engineering_root / "delivery_path_repairs.csv", repairs)
    summary = {
        "mode": "FIX" if args.fix else "AUDIT_ONLY",
        "records_scanned": len(object_types),
        "misplaced": len(repairs),
        "moved": sum(row["disposition"] == "MOVE" for row in repairs),
        "already_moved": sum(
            row["disposition"] == "ALREADY_MOVED" for row in repairs
        ),
        "deduplicated": sum(
            row["disposition"] == "DEDUPLICATE_IDENTICAL_BYTES" for row in repairs
        ),
        "conflicts": sum(
            row["disposition"] == "CONFLICT_DIFFERENT_BYTES" for row in repairs
        ),
        "csv_path_tables_updated": csv_tables_updated,
        "empty_directories_removed": empty_removed,
        "checksum_rows": checksum_rows,
        "checksum_sha256": checksum_sha256,
    }
    (args.engineering_root / "delivery_path_repair_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 2 if summary["conflicts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
