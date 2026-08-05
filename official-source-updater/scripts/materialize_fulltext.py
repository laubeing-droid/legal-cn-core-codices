#!/usr/bin/env python3
"""Materialize verified official full text into the ignored source workspace."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path


maximum_csv_field_size = sys.maxsize
while True:
    try:
        csv.field_size_limit(maximum_csv_field_size)
        break
    except OverflowError:
        maximum_csv_field_size //= 10


DATE_PATTERN = r"(\d{4})年(\d{1,2})月(\d{1,2})日"
CASE_NUMBER_WORDS = "一二三四五六七八九十百"
MANIFEST_FIELDS = [
    "status",
    "object_type",
    "relative_path",
    "title",
    "official_case_id",
    "publication_date",
    "official_url",
    "official_raw_sha256",
    "source_markdown_sha256",
    "note",
]
PAGE_METADATA_FIELDS = [
    "relative_path",
    "official_url",
    "final_url",
    "http_status",
    "promulgation_date",
    "document_number",
    "effective_date",
    "parse_status",
    "evidence_excerpt",
    "content_sha256",
    "raw_relative_path",
    "fetched_at",
    "error",
]


def iso_date(match: re.Match[str]) -> str:
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def extract_effective_date(text: str) -> str:
    match = re.search(rf"自\s*{DATE_PATTERN}\s*起?(?:施行|实施|执行)", text)
    return iso_date(match) if match else ""


def extract_document_number(text: str) -> str:
    head = text[:3000].replace("\u3000", " ")
    order_matches = list(re.finditer(
        r"((?:中华人民共和国)?(?:国务院|[\u4e00-\u9fff]{2,20}部)令)\s*第\s*(\d+)\s*号",
        head,
    ))
    if order_matches:
        match = order_matches[-1]
        authority = re.sub(r"^.*日", "", match.group(1))
        return re.sub(r"\s+", "", f"{authority}第{match.group(2)}号")
    split_order = re.search(
        r"((?:中华人民共和国)?国务院令)\s*\n+\s*第\s*(\d+)\s*号",
        head,
    )
    if split_order:
        return re.sub(r"\s+", "", f"{split_order.group(1)}第{split_order.group(2)}号")
    document_number = re.search(r"([\u4e00-\u9fff]{1,16}〔\d{4}〕\d+号)", head)
    return document_number.group(1) if document_number else ""


def extract_promulgation_date(text: str, fallback: str) -> str:
    head = text[:5000]
    exact_dates = []
    for line in head.splitlines():
        match = re.fullmatch(rf"\s*[（(]?{DATE_PATTERN}[）)]?\s*", line)
        if match:
            exact_dates.append(iso_date(match))
    if exact_dates:
        return exact_dates[0]
    order_dates = [
        iso_date(match)
        for match in re.finditer(
            rf"{DATE_PATTERN}(?:(?!\d{{4}}年\d{{1,2}}月\d{{1,2}}日)[^。\n]){{0,45}}?(?:令第\d+号|令\s*第\s*\d+\s*号)(?:公布|发布|修订)",
            head,
        )
    ]
    if order_dates:
        return order_dates[-1]
    parenthetical = re.match(rf"^.*?[（(]\s*{DATE_PATTERN}\s*[）)]", head, re.S)
    if parenthetical:
        return iso_date(parenthetical)
    return fallback


def normalize_title(value: str) -> str:
    return re.sub(r"[\s，。、“”‘’：《》〈〉（）()【】\[\]_-]", "", value or "")


def clean_title(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"^中华人民共和国(?:应急管理部|民政部)令（第\d+号）\s*", "", value)
    if " 煤矿重大事故隐患判定标准" in value:
        return "煤矿重大事故隐患判定标准"
    if " 未成年人救助保护机构管理暂行办法" in value:
        return "未成年人救助保护机构管理暂行办法"
    for ending in ("的通知", "的批复", "的意见"):
        position = value.find(ending)
        if position >= 0:
            return value[: position + len(ending)].replace("服 务", "服务")
    return value.replace("服 务", "服务")


def markdown_body(text: str) -> str:
    output: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if re.fullmatch(r"第[一二三四五六七八九十百千]+章.*", line):
            line = f"## {line}"
        elif re.match(r"^第[一二三四五六七八九十百千\d]+条(?:\s|$)", line):
            line = f"### {line}"
        elif re.fullmatch(r"【[^】]+】", line):
            line = f"## {line[1:-1]}"
        output.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(output)).strip()


def split_marked_cases(text: str) -> list[dict[str, str]]:
    lines = text.splitlines()
    markers = [
        index
        for index, line in enumerate(lines)
        if re.fullmatch(rf"案例(?:\d+|[{CASE_NUMBER_WORDS}]+)", line.strip())
    ]
    cases: list[dict[str, str]] = []
    for marker_index, end_index in zip(markers, markers[1:] + [len(lines)]):
        content = lines[marker_index + 1 : end_index]
        nonempty = [index for index, line in enumerate(content) if line.strip()]
        if not nonempty:
            continue
        title_index = nonempty[0]
        title = content[title_index].strip()
        second_index = next((index for index in nonempty[1:] if index > title_index), None)
        if second_index is not None and content[second_index].strip().startswith("——"):
            title += content[second_index].strip()
        body = "\n".join(content[title_index:]).strip()
        if body and re.search(r"【(?:基本案情|案例摘要|关键词|典型意义)】", body):
            cases.append({"title": title, "official_case_id": "", "body": body})
    return cases


def split_guiding_cases(text: str) -> list[dict[str, str]]:
    pattern = re.compile(
        r"(?m)^(?P<title>[^\n]+)\n\n（(?P<case_id>检例第\d+号)）\s*$"
    )
    matches = list(pattern.finditer(text))
    cases: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.start() : end].strip()
        cases.append(
            {
                "title": match.group("title").strip(),
                "official_case_id": match.group("case_id"),
                "body": body,
            }
        )
    return cases


def safe_filename(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", value)
    value = re.sub(r"\s+", " ", value).strip().rstrip(".")
    return value[:48] or "未命名"


def is_case_collection(row: dict[str, str]) -> bool:
    return (
        row.get("source_id") in {"spc_website", "spp_website"}
        and row.get("category") in {"指导性案例", "典型案例"}
    )


def clean_publisher(value: str) -> str:
    value = re.sub(r"^[\[（(]\s*|\s*[\]）)]$", "", value or "")
    return re.split(r"[,，、;；]", value, maxsplit=1)[0].strip(" '\"")


def frontmatter(fields: dict[str, str]) -> str:
    return "\n".join(
        f"{key}: {json.dumps(str(value), ensure_ascii=False)}"
        for key, value in fields.items()
    )


def write_markdown(path: Path, fields: dict[str, str], body: str) -> tuple[str, str]:
    content = f"---\n{frontmatter(fields)}\n---\n\n# {fields['title']}\n\n{markdown_body(body)}\n"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if path.exists():
        existing = hashlib.sha256(path.read_bytes()).hexdigest()
        if existing != digest:
            raise RuntimeError(f"目标源文件已存在且内容不同：{path}")
        return "ALREADY_MATERIALIZED", existing
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return "MATERIALIZED", digest


def law_classification(row: dict[str, str], title: str) -> tuple[str, str, str]:
    source_id = row["source_id"]
    category = row.get("category", "")
    publisher = clean_publisher(row.get("publisher", ""))
    if source_id == "spc_website" and category == "司法解释":
        return "1100", "最高人民法院", "02_法院系统/01_司法解释/01_最高人民法院司法解释"
    if source_id == "spp_website" and category == "司法解释":
        return "1100", "最高人民检察院", "03_检察院系统/01_司法解释/02_最高人民检察院司法解释"
    if source_id == "spp_website" and category == "规范文件":
        return "2100", "最高人民检察院", "03_检察院系统/02_检察规范性文件"
    if source_id == "national_rules_database" and category == "部门规章":
        agency = publisher or title.split("关于", 1)[0].strip()
        return "1300", agency, f"01_立法与公开行政文件/04_规章/01_部门规章/{safe_filename(agency)}规章"
    if source_id == "national_rules_database" and category == "地方政府规章":
        agency = publisher
        if agency and not agency.endswith("人民政府"):
            agency = f"{agency}人民政府"
        return "1400", agency, f"01_立法与公开行政文件/04_规章/02_地方政府规章/{safe_filename(agency)}"
    if source_id == "moj_admin_regulations":
        return "0400", "国务院", "01_立法与公开行政文件/02_行政法规"
    if title in {"集成电路布图设计保护条例", "国务院关于出境入境管理的规定"}:
        return "0400", "国务院", "01_立法与公开行政文件/02_行政法规"
    if title == "煤矿重大事故隐患判定标准":
        return "1300", "应急管理部", "01_立法与公开行政文件/04_规章/01_部门规章/应急管理部规章"
    if title == "未成年人救助保护机构管理暂行办法":
        return "1300", "民政部", "01_立法与公开行政文件/04_规章/01_部门规章/民政部规章"
    if title.startswith("国务院办公厅"):
        agency = "国务院办公厅"
    elif title.startswith("国务院"):
        agency = "国务院"
    elif title.startswith("中共中央办公厅"):
        agency = "中共中央办公厅,国务院办公厅"
    else:
        agency = title.split("关于", 1)[0].strip().replace(" ", ",")
    if source_id == "state_council_gazette" and "公开募捐平台服务管理办法" in row["title"]:
        agency = "民政部,工业和信息化部,国家广播电视总局,国家新闻出版署,国家互联网信息办公室"
    return "1700", agency, "01_立法与公开行政文件/05_公开行政规范性文件【非立法】/01_国家级"


def read_existing(formal_root: Path) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    laws: set[tuple[str, str]] = set()
    cases: set[tuple[str, str]] = set()
    with (formal_root / "legal_documents.csv").open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            raw_date = row.get("GBRQ", "")
            formatted = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}" if len(raw_date) == 8 else ""
            laws.add((normalize_title(row.get("BT", "")), formatted))
    with (formal_root / "cases.csv").open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            cases.add((normalize_title(row.get("title", "")), row.get("publication_date", "")))
    return laws, cases


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch-results", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--formal-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--page-metadata", type=Path, required=True)
    args = parser.parse_args()
    existing_laws, existing_cases = read_existing(args.formal_root)
    with args.fetch_results.open(encoding="utf-8-sig", newline="") as stream:
        fetched = list(csv.DictReader(stream))
    manifest: list[dict[str, str]] = []
    page_metadata: list[dict[str, str]] = []
    for row in fetched:
        if row.get("fetch_status") != "FULLTEXT_FETCHED":
            raise RuntimeError(f"正文未通过：{row.get('title')} {row.get('fetch_status')}")
        text_path = args.evidence_root / "normalized_text" / row["text_relative_path"]
        text = text_path.read_text(encoding="utf-8")
        if is_case_collection(row):
            cases = split_guiding_cases(text) if row["category"] == "指导性案例" else split_marked_cases(text)
            if not cases:
                raise RuntimeError(f"案例合集未拆分：{row['title']}")
            branch = (
                "03_检察院系统/04_最高人民检察院指导性案例"
                if row["category"] == "指导性案例"
                else (
                    "03_检察院系统/05_检察机关典型案例"
                    if row["source_id"] == "spp_website"
                    else "02_法院系统/10_法院官方选编及官方新媒体案例"
                )
            )
            issuing_body = "最高人民检察院" if row["source_id"] == "spp_website" else "最高人民法院"
            for case in cases:
                identity = (normalize_title(case["title"]), row["publication_date"])
                if identity in existing_cases:
                    manifest.append({
                        "status": "ALREADY_INGESTED",
                        "object_type": "case",
                        "relative_path": "",
                        "title": case["title"],
                        "official_case_id": case["official_case_id"],
                        "publication_date": row["publication_date"],
                        "official_url": row["official_url"],
                        "official_raw_sha256": row["raw_sha256"],
                        "source_markdown_sha256": "",
                        "note": "正式库已有同标题同发布日期案例",
                    })
                    continue
                suffix = f"_{case['official_case_id']}" if case["official_case_id"] else ""
                filename = f"{safe_filename(case['title'])}{suffix}_{row['publication_date']}_official-{row['record_id']}.md"
                relative = f"{branch}/{filename}"
                fields = {
                    "title": case["title"],
                    "document_type": "最高人民检察院指导性案例" if row["category"] == "指导性案例" else "典型案例",
                    "case_type": "检察案例" if row["source_id"] == "spp_website" else "最高人民法院典型案例",
                    "official_case_id": case["official_case_id"],
                    "author": issuing_body,
                    "publication_date": row["publication_date"],
                    "official_source_url": row["official_url"],
                    "official_record_id": row["record_id"],
                    "source_collection": row["title"],
                    "verification_status": "OFFICIAL_FULLTEXT_VERIFIED",
                    "official_raw_sha256": row["raw_sha256"],
                    "normalized_text_sha256": row["normalized_text_sha256"],
                    "fetched_at": row["fetched_at"],
                }
                status, digest = write_markdown(args.source_root / Path(relative), fields, case["body"])
                manifest.append({
                    "status": status, "object_type": "case", "relative_path": relative,
                    "title": case["title"], "official_case_id": case["official_case_id"],
                    "publication_date": row["publication_date"], "official_url": row["official_url"],
                    "official_raw_sha256": row["raw_sha256"], "source_markdown_sha256": digest,
                    "note": "官方合集按单案边界拆分",
                })
            continue

        title = clean_title(row["title"])
        promulgation_date = extract_promulgation_date(text, row["publication_date"])
        identity = (normalize_title(title), promulgation_date)
        if identity in existing_laws:
            manifest.append({
                "status": "ALREADY_INGESTED", "object_type": "legal_document",
                "relative_path": "", "title": title, "official_case_id": "",
                "publication_date": promulgation_date, "official_url": row["official_url"],
                "official_raw_sha256": row["raw_sha256"], "source_markdown_sha256": "",
                "note": "正式库已有同标题同公布日期文件",
            })
            continue
        category_code, agency, branch = law_classification(row, title)
        effective_date = extract_effective_date(text)
        status_label = "尚未施行" if effective_date and effective_date > date.today().isoformat() else "有效"
        document_number = extract_document_number(text)
        filename = f"{safe_filename(title)}_{promulgation_date}_{status_label}_official-{row['record_id']}.md"
        relative = f"{branch}/{filename}"
        fields = {
            "title": title,
            "FLFGDZWJFLDM": category_code,
            "author": agency,
            "promulgation_date": promulgation_date,
            "publication_date": row["publication_date"],
            "effective_date": effective_date,
            "status": status_label,
            "document_number": document_number,
            "official_source_url": row["official_url"],
            "official_record_id": row["record_id"],
            "verification_status": "OFFICIAL_FULLTEXT_VERIFIED",
            "official_raw_sha256": row["raw_sha256"],
            "normalized_text_sha256": row["normalized_text_sha256"],
            "fetched_at": row["fetched_at"],
        }
        material_status, digest = write_markdown(args.source_root / Path(relative), fields, text)
        manifest.append({
            "status": material_status, "object_type": "legal_document", "relative_path": relative,
            "title": title, "official_case_id": "", "publication_date": promulgation_date,
            "official_url": row["official_url"], "official_raw_sha256": row["raw_sha256"],
            "source_markdown_sha256": digest, "note": "官方单页全文",
        })
        page_metadata.append({
            "relative_path": relative,
            "official_url": row["official_url"],
            "final_url": row["final_url"],
            "http_status": row["http_status"],
            "promulgation_date": promulgation_date,
            "document_number": document_number,
            "effective_date": effective_date,
            "parse_status": "PARSED",
            "evidence_excerpt": f"官方正文；标题={title}",
            "content_sha256": row["raw_sha256"],
            "raw_relative_path": row["raw_relative_path"],
            "fetched_at": row["fetched_at"],
            "error": "",
        })
    write_csv(args.manifest, MANIFEST_FIELDS, manifest)
    write_csv(args.page_metadata, PAGE_METADATA_FIELDS, page_metadata)
    counts: dict[str, int] = {}
    for row in manifest:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(f"records={len(manifest)} " + " ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
