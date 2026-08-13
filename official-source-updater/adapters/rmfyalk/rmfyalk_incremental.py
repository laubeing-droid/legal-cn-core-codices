#!/usr/bin/env python3
"""
人民法院案例库官方增量抓取入口。

设计边界：
- 不读取浏览器 cookie、本地存储、密码库。
- 只使用用户显式提供的 RMFYALK_TOKEN 环境变量、--prompt-token，或 config/cookies.txt。
- 默认只抓官方索引，不下载正文。
"""

from __future__ import annotations

import argparse
import csv
import getpass
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from common_paths import CONFIG_DIR, DATA_DIR, REPORT_DIR

BASE_URL = "https://rmfyalk.court.gov.cn"
SEARCH_API = f"{BASE_URL}/cpws_al_api/api/cpwsAl/search"
CONTENT_API = f"{BASE_URL}/cpws_al_api/api/cpwsAl/content"
INDEX_API = f"{BASE_URL}/cpws_al_api/api/cpwsAl/indexTongji"


def read_auth() -> tuple[str, str]:
    token = os.environ.get("RMFYALK_TOKEN", "").strip()
    if token:
        return "token", token

    cookie_file = CONFIG_DIR / "cookies.txt"
    if cookie_file.exists():
        for line in cookie_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("RMFYALK_TOKEN="):
                return "token", line.split("=", 1)[1].strip()
            if line.startswith("faxin-cpws-al-token="):
                return "token", line.split("=", 1)[1].strip()
    return "", ""


def request_json(session: requests.Session, url: str, payload: dict[str, Any]) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = session.post(url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            if str(data.get("code")) not in {"0", "200"}:
                raise RuntimeError(
                    f"API returned code={data.get('code')} msg={data.get('msg')}"
                )
            return data
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as error:
            last_error = error
            if attempt + 1 < 3:
                time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"请求失败：{url}（{last_error}）") from last_error


def make_http_session(auth_type: str, auth_value: str) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0 local-case-audit",
            "Content-Type": "application/json;charset=UTF-8",
            "Referer": f"{BASE_URL}/view/list.html",
            "Origin": BASE_URL,
        }
    )
    if auth_type == "token":
        s.headers["faxin-cpws-al-token"] = auth_value
    return s


def search_payload(page: int, size: int, category_code: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {
        "userSearchType": 1,
        "isAdvSearch": "0",
        "selectValue": "qw",
        "lib": "cpwsAl_qb",
        "sort_field": "-cpws_al_zs_date",
    }
    if category_code:
        params["case_sort_id_cpwsAl"] = category_code
    return {"page": page, "size": size, "lib": "qb", "searchParams": params}


def extract_list_items(data: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    payload = data.get("data")
    if isinstance(payload, dict):
        for key in ("datas", "list", "records", "rows", "data"):
            if isinstance(payload.get(key), list):
                total = int(payload.get("totalCount") or payload.get("total") or payload.get("rowTotal") or payload.get("count") or 0)
                return payload[key], total
    if isinstance(payload, list):
        return payload, len(payload)
    return [], 0


def normalize_item(item: dict[str, Any], category_label: str) -> dict[str, Any]:
    case_id = item.get("no") or item.get("case_no") or item.get("cpws_al_no") or item.get("record_no") or ""
    api_id = item.get("id") or item.get("cpws_al_id") or item.get("case_id") or ""
    title = item.get("title") or item.get("case_title") or item.get("cpws_al_title") or item.get("name") or ""
    return {
        "case_id": str(case_id),
        "api_id": str(api_id),
        "title": str(title),
        "category": str(item.get("cpws_al_case_sort_name") or category_label),
        "case_sort": str(item.get("cpws_al_sort_name") or ""),
        "court": str(item.get("cpws_al_slfy_name") or ""),
        "judgment_date": str(item.get("cpws_al_zs_date") or ""),
        "docket": str(item.get("cpws_al_ajzh") or ""),
        "entry_time": str(item.get("cpws_al_rk_time") or ""),
        "trial_division": str(item.get("cpws_al_ts_name") or ""),
        "raw_json": json.dumps(item, ensure_ascii=False, sort_keys=True),
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index-only", action="store_true", help="只抓官方索引，不抓正文")
    parser.add_argument("--prompt-token", action="store_true", help="在终端中隐藏输入 faxin-cpws-al-token")
    parser.add_argument("--category-mode", choices=["all", "five"], default="all", help="all=抓全部索引；five=按五类分别抓")
    parser.add_argument("--debug-response", action="store_true", help="保存每个分类第一页原始响应，便于修正字段解析")
    parser.add_argument("--size", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=0, help="调试用；0 表示不限制")
    parser.add_argument("--sleep", type=float, default=0.35)
    args = parser.parse_args()

    if args.prompt_token:
        auth_type, auth_value = "token", getpass.getpass("faxin-cpws-al-token: ").strip()
    else:
        auth_type, auth_value = read_auth()
    if not auth_value:
        raise SystemExit(
            "缺少登录凭证。优先设置 RMFYALK_TOKEN=faxin-cpws-al-token 的值；"
            f"也可写入 {CONFIG_DIR / 'cookies.txt'}"
        )

    http = make_http_session(auth_type, auth_value)
    if args.category_mode == "five":
        categories = {
            "刑事": "01",
            "民事": "02",
            "行政": "03",
            "国家赔偿": "04",
            "执行": "05",
        }
    else:
        categories = {"全部": None}

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    started = datetime.now().isoformat(timespec="seconds")

    for label, code in categories.items():
        page = 1
        while True:
            if args.max_pages and page > args.max_pages:
                break
            try:
                data = request_json(http, SEARCH_API, search_payload(page, args.size, code))
                if args.debug_response and page == 1:
                    debug_path = DATA_DIR / f"debug_response_{label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                    debug_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                items, total = extract_list_items(data)
            except Exception as exc:
                errors.append(f"{label} page={page}: {exc}")
                break
            if not items:
                break
            rows.extend(normalize_item(item, label) for item in items)
            print(f"{label} page={page} items={len(items)} total={total}")
            if total and page * args.size >= total:
                break
            page += 1
            time.sleep(args.sleep)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = DATA_DIR / f"official_index_{stamp}.csv"
    write_csv(out, rows, ["case_id", "api_id", "title", "category", "case_sort", "court", "judgment_date", "docket", "entry_time", "trial_division", "raw_json"])

    report = REPORT_DIR / f"official_index_{stamp}.md"
    unique_case_ids = {r["case_id"] for r in rows if r["case_id"]}
    report.write_text(
        "\n".join(
            [
                "# 人民法院案例库官方索引增量抓取报告",
                "",
                f"- 开始时间：{started}",
                f"- 结束时间：{datetime.now().isoformat(timespec='seconds')}",
                f"- 抓取记录数：{len(rows)}",
                f"- 唯一入库编号数：{len(unique_case_ids)}",
                f"- 输出：`{out}`",
                "",
                "## 错误",
                "",
                "\n".join(f"- {e}" for e in errors) if errors else "- 无",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"official_rows={len(rows)}")
    print(f"official_unique_case_ids={len(unique_case_ids)}")
    print(f"csv={out}")
    print(f"report={report}")
    return 1 if errors and not rows else 0


if __name__ == "__main__":
    raise SystemExit(main())
