#!/usr/bin/env python3
"""抓取国家法律法规数据库官方列表索引；不抓正文。"""

from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://flk.npc.gov.cn"
LIST_URL = f"{BASE_URL}/law-search/search/list"
AGGREGATE_URL = f"{BASE_URL}/law-search/index/aggregateData"
BASE_PAYLOAD = {
    "searchRange": 1,
    "sxrq": [],
    "gbrq": [],
    "searchType": 2,
    "sxx": [],
    "gbrqYear": [],
    "flfgCodeId": [],
    "zdjgCodeId": [],
    "searchContent": "",
}
FIELDS = [
    "bbbs",
    "title",
    "gbrq",
    "sxrq",
    "sxx",
    "zdjgName",
    "flxz",
    "zdjgCodeId",
    "flfgCodeId",
    "raw_json",
]


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = session.request(method, url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise RuntimeError("官网返回的不是JSON对象")
            return data
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"官网请求连续失败：{last_error}")


def fetch_index(
    output: Path,
    page_size: int,
    max_pages: int,
    sleep_seconds: float,
) -> tuple[Path, dict[str, Any]]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 official-source-updater/1.0",
            "Referer": f"{BASE_URL}/search",
            "Content-Type": "application/json;charset=UTF-8",
        }
    )

    rows: list[dict[str, Any]] = []
    total: int | None = None
    page = 1
    while True:
        payload = dict(BASE_PAYLOAD)
        payload.update({"pageNum": page, "pageSize": page_size})
        response = request_json(session, "POST", LIST_URL, payload=payload)
        if total is None:
            total = int(response.get("total") or 0)
        batch = response.get("rows") or []
        if not isinstance(batch, list):
            raise RuntimeError("官网 rows 字段不是数组")
        rows.extend(item for item in batch if isinstance(item, dict))
        print(f"flk page={page} batch={len(batch)} fetched={len(rows)} total={total}")

        if not batch or (total and len(rows) >= total):
            break
        if max_pages and page >= max_pages:
            break
        page += 1
        time.sleep(sleep_seconds)

    output.mkdir(parents=True, exist_ok=True)
    index_path = output / "flk_official_index.csv"
    with index_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        for item in rows:
            row = {field: item.get(field, "") for field in FIELDS if field != "raw_json"}
            row["raw_json"] = json.dumps(item, ensure_ascii=False, sort_keys=True)
            writer.writerow(row)

    aggregate: dict[str, Any] | None = None
    try:
        aggregate = request_json(session, "GET", AGGREGATE_URL)
    except RuntimeError as exc:
        print(f"flk aggregate warning={exc}")

    unique_ids = {
        str(item.get("bbbs") or "").strip().lower()
        for item in rows
        if str(item.get("bbbs") or "").strip()
    }
    meta = {
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "official_total": total or 0,
        "fetched_rows": len(rows),
        "unique_ids": len(unique_ids),
        "pages": page,
        "page_size": page_size,
        "complete": bool(total is not None and len(rows) >= total),
        "aggregate": aggregate,
    }
    (output / "flk_official_index_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return index_path, meta


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--max-pages", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.05)
    args = parser.parse_args()
    if args.page_size < 1 or args.max_pages < 0 or args.sleep < 0:
        parser.error("分页和等待参数不能为负数")

    index_path, meta = fetch_index(
        args.output.resolve(), args.page_size, args.max_pages, args.sleep
    )
    print(f"official_rows={meta['fetched_rows']}")
    print(f"official_unique_ids={meta['unique_ids']}")
    print(f"complete={meta['complete']}")
    print(f"csv={index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
