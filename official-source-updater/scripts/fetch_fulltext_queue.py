#!/usr/bin/env python3
"""Fetch bounded official single pages and preserve raw and normalized evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import requests

UPDATER_ROOT = Path(__file__).resolve().parent.parent
if str(UPDATER_ROOT) not in sys.path:
    sys.path.insert(0, str(UPDATER_ROOT))

from scripts.extract_registered_page_metadata import parse_official_page_metadata


QUEUE_FIELDS = [
    "source_id",
    "record_id",
    "title",
    "publication_date",
    "category",
    "publisher",
    "official_url",
    "catalog_url",
    "selection_status",
]
RESULT_FIELDS = QUEUE_FIELDS + [
    "final_url",
    "http_status",
    "fetch_status",
    "promulgation_date",
    "document_number",
    "effective_date",
    "metadata_parse_status",
    "metadata_evidence_excerpt",
    "raw_sha256",
    "normalized_text_sha256",
    "raw_relative_path",
    "text_relative_path",
    "text_length",
    "fetched_at",
    "error",
]
USER_AGENT = "Mozilla/5.0 official-source-updater/1.0"
MINIMUM_BODY_LENGTH = 200


def make_direct_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": USER_AGENT})
    return session


class OfficialBodyParser(HTMLParser):
    BLOCK_TAGS = {
        "article", "br", "dd", "div", "dl", "dt", "h1", "h2", "h3",
        "h4", "li", "main", "p", "section", "table", "td", "th", "tr",
    }
    IGNORED_TAGS = {"footer", "nav", "noscript", "script", "style"}
    CONTAINER_IDS = {"UCAP-CONTENT"}
    CONTAINER_CLASSES = {
        "TRS_Editor", "article-content", "detail", "detail_con", "txt", "wsfbh_detail_con", "zoom",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.ignored_depths: list[int] = []
        self.active: list[dict[str, object]] = []
        self.completed: list[str] = []

    def _ignored(self) -> bool:
        return bool(self.ignored_depths)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.depth += 1
        if tag in self.IGNORED_TAGS:
            self.ignored_depths.append(self.depth)
        if not self._ignored():
            if tag in self.BLOCK_TAGS:
                for capture in self.active:
                    capture["parts"].append("\n")
            attributes = {name: value or "" for name, value in attrs}
            class_names = set(attributes.get("class", "").split())
            is_container = (
                attributes.get("id") in self.CONTAINER_IDS
                or bool(class_names & self.CONTAINER_CLASSES)
                or tag in {"article", "main"}
            )
            if is_container:
                self.active.append({"depth": self.depth, "parts": []})

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self._ignored() and tag in self.BLOCK_TAGS:
            for capture in self.active:
                capture["parts"].append("\n")
        ending = [capture for capture in self.active if capture["depth"] == self.depth]
        for capture in ending:
            text = normalize_body_text("".join(capture["parts"]))
            if text:
                self.completed.append(text)
            self.active.remove(capture)
        if self.ignored_depths and self.ignored_depths[-1] == self.depth:
            self.ignored_depths.pop()
        self.depth = max(0, self.depth - 1)

    def handle_data(self, data: str) -> None:
        if self._ignored():
            return
        for capture in self.active:
            capture["parts"].append(data)


def normalize_body_text(value: str) -> str:
    value = value.replace("\u3000", " ").replace("\xa0", " ")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in value.splitlines()]
    compact: list[str] = []
    for line in lines:
        if line:
            compact.append(line)
        elif compact and compact[-1] != "":
            compact.append("")
    return "\n".join(compact).strip()


def strip_page_footer(body: str) -> str:
    """截断页脚导航/链接栏残留（gov.cn/法院/检察详情页尾部）。"""
    cut = re.search(
        r"(扫一扫在手机打开当前页|链接：|友情链接|全国人大|全国政协|国家监察委员会|"
        r"返回顶部|版权所有|京ICP备|网站地图|联系我们|政府网站找错|关于我们|网站声明|"
        r"国务院部门网站|中央人民政府门户网站|设为首页|加入收藏)",
        body,
    )
    if cut:
        body = body[: cut.start()]
    return body.strip()


def extract_official_body(html: str) -> str:
    parser = OfficialBodyParser()
    parser.feed(html)
    parser.close()
    body = max(parser.completed, key=len, default="")
    if len(body) < MINIMUM_BODY_LENGTH:
        body = _extract_legacy_detail_page(html)
    return strip_page_footer(body)


def _extract_legacy_detail_page(html: str) -> str:
    """老版 gov.cn 详情页：正文是裸 <p> 段落（无正文容器 class）。

    官方更新器原提取器只认容器（TRS_Editor 等），老版详情页提取为空。
    此处兜底：定位'附件'/'现予公布'等正文起点标记后提取全部 p 标签。
    页脚截断由 extract_official_body 统一处理（strip_page_footer）。
    """
    start = 0
    for marker in ["附件：", "附件:", "附件\n", ">附件<", "现予公布", "现予发布"]:
        idx = html.find(marker)
        if idx > 0:
            start = idx
            break
    seg = html[start:]
    paras = re.findall(r"<p[^>]*>(.*?)</p>", seg, re.S)
    out = []
    for p in paras:
        t = re.sub(r"<[^>]+>", "", p)
        t = t.replace("&nbsp;", " ").replace("\u3000", " ")
        t = re.sub(r"[ \t]+", " ", t)
        t = t.strip()
        if len(t) >= 3:
            out.append(t)
    body = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def decode_response(raw: bytes, response: requests.Response) -> str:
    del response
    return decode_saved_html(raw)


def decode_saved_html(raw: bytes) -> str:
    charset = re.search(br"charset=[\"']?([A-Za-z0-9_-]+)", raw[:8192], re.I)
    encodings = [charset.group(1).decode("ascii", "ignore")] if charset else []
    encodings.extend(["utf-8", "gb18030"])
    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace")


def safe_stem(row: dict[str, str]) -> str:
    seed = f"{row.get('source_id', '')}_{row.get('record_id', '')}".strip("_")
    stem = re.sub(r"[^0-9A-Za-z_-]+", "_", seed).strip("_")
    return stem[:120] or hashlib.sha256(row["official_url"].encode()).hexdigest()[:24]


def fetch_one(
    row: dict[str, str], raw_directory: Path, text_directory: Path
) -> dict[str, str]:
    result = {field: str(row.get(field) or "") for field in RESULT_FIELDS}
    result["fetched_at"] = datetime.now(timezone.utc).isoformat()
    session = make_direct_session()
    try:
        response = session.get(row["official_url"], timeout=45, allow_redirects=True)
        result["final_url"] = response.url
        result["http_status"] = str(response.status_code)
        response.raise_for_status()
        raw = response.content
        raw_digest = hashlib.sha256(raw).hexdigest()
        raw_directory.mkdir(parents=True, exist_ok=True)
        text_directory.mkdir(parents=True, exist_ok=True)
        suffix = ".html"
        content_type = response.headers.get("Content-Type", "").lower()
        if "pdf" in content_type or urlsplit(response.url).path.lower().endswith(".pdf"):
            suffix = ".pdf"
        raw_name = f"{safe_stem(row)}_{raw_digest[:16]}{suffix}"
        (raw_directory / raw_name).write_bytes(raw)
        result["raw_sha256"] = raw_digest
        result["raw_relative_path"] = raw_name
        if suffix == ".pdf":
            result["fetch_status"] = "PDF_REQUIRES_TEXT_EXTRACTION"
            return result
        html = decode_response(raw, response)
        body = extract_official_body(html)
        metadata = parse_official_page_metadata(html, response.url)
        result.update(
            promulgation_date=metadata["promulgation_date"],
            document_number=metadata["document_number"],
            effective_date=metadata["effective_date"],
            metadata_parse_status=metadata["parse_status"],
            metadata_evidence_excerpt=metadata["evidence_excerpt"],
        )
        if len(body) < MINIMUM_BODY_LENGTH:
            result["fetch_status"] = "CONTENT_INCOMPLETE"
            result["text_length"] = str(len(body))
            return result
        text_digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        text_name = f"{safe_stem(row)}_{text_digest[:16]}.txt"
        (text_directory / text_name).write_text(body, encoding="utf-8", newline="\n")
        result.update(
            fetch_status="FULLTEXT_FETCHED",
            normalized_text_sha256=text_digest,
            text_relative_path=text_name,
            text_length=str(len(body)),
        )
    except Exception as error:
        result["fetch_status"] = "BLOCKED_ACCESS"
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        session.close()
    return result


def reparse_saved_result(
    row: dict[str, str], raw_directory: Path, text_directory: Path
) -> dict[str, str]:
    raw_path = raw_directory / row.get("raw_relative_path", "")
    if not raw_path.is_file() or raw_path.suffix.lower() != ".html":
        return row
    html = decode_saved_html(raw_path.read_bytes())
    body = extract_official_body(html)
    metadata = parse_official_page_metadata(html, row.get("final_url", ""))
    row["text_length"] = str(len(body))
    row.update(
        promulgation_date=metadata["promulgation_date"],
        document_number=metadata["document_number"],
        effective_date=metadata["effective_date"],
        metadata_parse_status=metadata["parse_status"],
        metadata_evidence_excerpt=metadata["evidence_excerpt"],
    )
    if len(body) < MINIMUM_BODY_LENGTH:
        return row
    text_directory.mkdir(parents=True, exist_ok=True)
    text_digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    text_name = f"{safe_stem(row)}_{text_digest[:16]}.txt"
    (text_directory / text_name).write_text(body, encoding="utf-8", newline="\n")
    row.update(
        fetch_status="FULLTEXT_FETCHED",
        normalized_text_sha256=text_digest,
        text_relative_path=text_name,
        error="",
    )
    return row


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=RESULT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--reparse-incomplete", action="store_true")
    parser.add_argument("--reparse-existing", action="store_true")
    args = parser.parse_args()
    with args.queue.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    raw_directory = args.evidence_root / "raw"
    text_directory = args.evidence_root / "normalized_text"
    existing: dict[str, dict[str, str]] = {}
    if args.output.is_file():
        with args.output.open(encoding="utf-8-sig", newline="") as stream:
            existing = {
                row["official_url"]: row
                for row in csv.DictReader(stream)
                if row.get("official_url")
            }
    results: list[dict[str, str]] = []
    pending: list[dict[str, str]] = []
    for row in rows:
        saved = existing.get(row.get("official_url", ""))
        if not saved:
            pending.append(row)
            continue
        if args.reparse_existing or (
            args.reparse_incomplete and saved.get("fetch_status") != "FULLTEXT_FETCHED"
        ):
            saved = reparse_saved_result(saved, raw_directory, text_directory)
        results.append(saved)
    write_csv(args.output, results)
    with ThreadPoolExecutor(max_workers=max(1, args.max_workers)) as executor:
        futures = {
            executor.submit(fetch_one, row, raw_directory, text_directory): row
            for row in pending
        }
        for index, future in enumerate(as_completed(futures), 1):
            results.append(future.result())
            write_csv(args.output, results)
            print(f"processed={index}/{len(pending)}", flush=True)
    counts: dict[str, int] = {}
    for row in results:
        status = row["fetch_status"]
        counts[status] = counts.get(status, 0) + 1
    print(" ".join(f"{status}={count}" for status, count in sorted(counts.items())))
    return 0 if all(row["fetch_status"] == "FULLTEXT_FETCHED" for row in results) else 4


if __name__ == "__main__":
    raise SystemExit(main())
