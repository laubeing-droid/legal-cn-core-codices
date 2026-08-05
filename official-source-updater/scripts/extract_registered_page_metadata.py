#!/usr/bin/env python3
"""Fetch only registered official URLs and extract code-bearing page metadata."""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from adapters.official_index import fetch


DATE = r"(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
ACTION_PATTERN = re.compile(
    DATE
    + r"(?P<context>(?:(?!\d{4}年\d{1,2}月\d{1,2}日)[^。；\n]){0,100}?)"
    + r"(?P<action>公布|发布|修订|修正|修改)",
)
NUMBER_PATTERN = re.compile(
    r"(?P<number>"
    r"[\u3400-\u9fffA-Za-z·]{2,50}?(?:令|公告)\s*"
    r"(?:\d{4}年)?[（(]?\s*第?\s*"
    r"[零〇一二三四五六七八九十百千万\d]+\s*号[）)]?"
    r"|[\u3400-\u9fff]{1,20}[〔\[]\d{4}[〕\]]\d+号"
    r")"
)
HEADER_NUMBER_PATTERN = re.compile(
    r"(?:发文字号|文号)\s*[:：]?\s*" + NUMBER_PATTERN.pattern,
)
DECISION_SIGNATURE_DATE_PATTERN = re.compile(
    r"(?:部\s*长|省\s*长|市\s*长|主\s*席|主\s*任|署\s*长|局\s*长|行\s*长)"
    r"[^。]{0,100}?" + DATE,
)
EFFECTIVE_PATTERN = re.compile(
    r"(?:自)?" + DATE + r"(?:起)?(?:施行|实施|执行)",
)
FIELDS = [
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


class _VisibleText(HTMLParser):
    BLOCKS = {
        "br", "div", "h1", "h2", "h3", "li", "p", "section", "td", "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.ignored += 1
        elif not self.ignored and tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.ignored:
            self.ignored -= 1
        elif not self.ignored and tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.parts.append(data)

    def text(self) -> str:
        value = "".join(self.parts).replace("\u3000", " ")
        value = re.sub(r"[ \t\r\f\v]+", " ", value)
        value = re.sub(r"\n\s*\n+", "\n", value)
        return value.strip()


def _date(match: re.Match[str]) -> str:
    return (
        f"{int(match.group('year')):04d}-"
        f"{int(match.group('month')):02d}-"
        f"{int(match.group('day')):02d}"
    )


def _excerpt(text: str, start: int, end: int) -> str:
    return re.sub(r"\s+", " ", text[max(0, start - 50) : end + 80]).strip()


def parse_official_page_metadata(html: str, _url: str = "") -> dict[str, str]:
    parser = _VisibleText()
    parser.feed(html)
    text = parser.text()
    full_head = text[:5000]
    head = full_head
    article = re.search(r"第[零〇一二三四五六七八九十百千万\d]+条", full_head)
    if article:
        head = head[: article.start()]
    candidates: list[dict[str, str | int]] = []
    for match in ACTION_PATTERN.finditer(head):
        context = match.group("context")
        number_scope = head[
            match.end("day") + 1 : min(len(head), match.end() + 140)
        ]
        number_match = NUMBER_PATTERN.search(number_scope)
        number = number_match.group("number") if number_match else ""
        if not number and "决定" in head[:1200]:
            header_number_match = HEADER_NUMBER_PATTERN.search(head[:1200])
            if header_number_match:
                number = header_number_match.group("number")
        number = re.sub(r"[（）()\s]", "", number)
        candidates.append(
            {
                "date": _date(match),
                "number": number,
                "action": match.group("action"),
                "start": match.start(),
                "end": match.end(),
            }
        )
    modification = [
        item for item in candidates if item["action"] in {"修改", "修正", "修订"}
    ]
    eligible = modification or [
        item for item in candidates if item["action"] in {"公布", "发布"}
    ]
    selected = max(eligible, key=lambda item: str(item["date"])) if eligible else None
    decision_head = "决定" in head[:1200]
    header_number_match = (
        HEADER_NUMBER_PATTERN.search(head[:1200]) if decision_head else None
    )
    signature_matches = (
        list(DECISION_SIGNATURE_DATE_PATTERN.finditer(head[:2500]))
        if header_number_match
        else []
    )
    if selected and header_number_match:
        selected["number"] = re.sub(
            r"[（）()\s]", "", header_number_match.group("number")
        )
        if signature_matches:
            signature = signature_matches[-1]
            selected["date"] = _date(signature)
            selected["start"] = signature.start()
            selected["end"] = signature.end()
    effective_matches = list(EFFECTIVE_PATTERN.finditer(full_head))
    effective = _date(effective_matches[0]) if effective_matches else ""
    evidence = ""
    if selected:
        evidence = _excerpt(head, int(selected["start"]), int(selected["end"]))
    elif effective_matches:
        evidence = _excerpt(
            full_head,
            effective_matches[0].start(),
            effective_matches[0].end(),
        )
    return {
        "promulgation_date": str(selected["date"]) if selected else "",
        "document_number": str(selected["number"]) if selected else "",
        "effective_date": effective,
        "parse_status": "PARSED" if selected else "BLOCKED_NO_PROMULGATION_EVIDENCE",
        "evidence_excerpt": evidence,
    }


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _decode_raw(raw: bytes) -> str:
    charset_match = re.search(br"charset=[\"']?([A-Za-z0-9_-]+)", raw[:4096], re.I)
    encodings = [charset_match.group(1).decode("ascii", "ignore")] if charset_match else []
    encodings.extend(["utf-8", "gb18030"])
    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace")


def registered_selection_complete(
    selected: list[dict[str, str]], completed: list[dict[str, str]]
) -> bool:
    completed_urls = {row.get("official_url", "") for row in completed}
    return all(row.get("official_url", "") in completed_urls for row in selected)


def _fetch_one(row: dict[str, str], raw_dir: Path) -> dict[str, str]:
    url = row["official_url"]
    result = {field: "" for field in FIELDS}
    result.update(relative_path=row["relative_path"], official_url=url)
    try:
        response = fetch(url, retries=2, retry_delay=0.5)
        raw = response.content
        digest = hashlib.sha256(raw).hexdigest()
        raw_name = f"{digest}.html"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / raw_name).write_bytes(raw)
        response.encoding = response.apparent_encoding or "utf-8"
        parsed = parse_official_page_metadata(response.text, response.url)
        result.update(parsed)
        result.update(
            final_url=response.url,
            http_status=str(response.status_code),
            content_sha256=digest,
            raw_relative_path=raw_name,
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as error:  # evidence row must survive every single-page failure
        result.update(
            parse_status="BLOCKED_ACCESS",
            fetched_at=datetime.now(timezone.utc).isoformat(),
            error=f"{type(error).__name__}: {error}",
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--url-field", default="official_rule_record_id")
    parser.add_argument("--only-sequence-source", default="")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--reparse-existing", action="store_true")
    parser.add_argument(
        "--reparse-containing",
        default="",
        help="When reparsing saved raw pages, only parse visible source containing this text",
    )
    args = parser.parse_args()

    with args.input.open(encoding="utf-8-sig", newline="") as stream:
        source_rows = list(csv.DictReader(stream))
    selected: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for row in source_rows:
        if (
            args.only_sequence_source
            and row.get("internal_sequence_source") != args.only_sequence_source
        ):
            continue
        url = str(row.get(args.url_field) or "").strip()
        if not url.startswith(("http://", "https://")) or url in seen_urls:
            continue
        seen_urls.add(url)
        selected.append(
            {"relative_path": row.get("relative_path", ""), "official_url": url}
        )

    existing: dict[str, dict[str, str]] = {}
    if args.output.exists():
        with args.output.open(encoding="utf-8-sig", newline="") as stream:
            existing = {
                row["official_url"]: row
                for row in csv.DictReader(stream)
                if row.get("official_url")
            }
    if args.reparse_existing:
        reparsed = 0
        for row in existing.values():
            raw_path = args.raw_dir / row.get("raw_relative_path", "")
            if not raw_path.is_file():
                continue
            decoded = _decode_raw(raw_path.read_bytes())
            if args.reparse_containing and args.reparse_containing not in decoded:
                continue
            parsed = parse_official_page_metadata(decoded, row["final_url"])
            row.update(parsed)
            reparsed += 1
        _write_csv(args.output, list(existing.values()))
        print(f"reparsed={reparsed}", flush=True)
    pending = [row for row in selected if row["official_url"] not in existing]
    completed = list(existing.values())
    with ThreadPoolExecutor(max_workers=max(1, args.max_workers)) as executor:
        futures = {
            executor.submit(_fetch_one, row, args.raw_dir): row for row in pending
        }
        for index, future in enumerate(as_completed(futures), 1):
            completed.append(future.result())
            if index % 20 == 0 or index == len(pending):
                _write_csv(args.output, completed)
                print(f"processed {index}/{len(pending)}", flush=True)
    if not pending:
        _write_csv(args.output, completed)
    parsed = sum(row.get("parse_status") == "PARSED" for row in completed)
    blocked = len(completed) - parsed
    print(
        f"registered={len(selected)} fetched={len(completed)} "
        f"parsed={parsed} blocked={blocked}"
    )
    return 0 if registered_selection_complete(selected, completed) else 2


if __name__ == "__main__":
    raise SystemExit(main())
