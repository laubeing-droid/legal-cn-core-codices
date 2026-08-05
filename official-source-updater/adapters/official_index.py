#!/usr/bin/env python3
"""其余全国官方通道索引抓取器；只生成索引，不写正式区。"""

from __future__ import annotations

import argparse
import base64
import csv
import html
import io
import json
import re
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, urljoin, urlsplit, urlunsplit

import requests

FIELDS = [
    "source_id",
    "record_id",
    "title",
    "publication_date",
    "category",
    "publisher",
    "official_url",
    "catalog_url",
]
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) official-source-updater/1.0"
MOJ_CASE_ROOT_URL = "https://alk.12348.gov.cn/"
MOJ_CASE_DATABASE_IDS = {"74", "75", "76", "77"}
MOJ_BLOCK_MARKERS = (
    "您的IP最近有可疑的攻击行为",
    "系统正在维护中",
)


class AccessBlocked(RuntimeError):
    pass


def clean_text(value: object) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", "", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def fetch(
    url: str,
    *,
    retries: int = 3,
    retry_delay: float = 1.0,
    **kwargs,
) -> requests.Response:
    headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
    method = str(kwargs.pop("method", "get")).lower()
    session = kwargs.pop("session", None)
    requester = (
        session.post
        if session is not None and method == "post"
        else (
            session.get
            if session is not None
            else (requests.post if method == "post" else requests.get)
        )
    )
    response: requests.Response | None = None
    for attempt in range(retries):
        try:
            response = requester(url, headers=headers, timeout=30, **kwargs)
        except (requests.Timeout, requests.ConnectionError):
            if attempt + 1 >= retries:
                raise
            time.sleep(retry_delay * (attempt + 1))
            continue
        if response.status_code in {491, 502, 503} and attempt + 1 < retries:
            time.sleep(retry_delay * (attempt + 1))
            continue
        break
    if response is None:
        raise RuntimeError(f"请求未返回响应：{url}")
    if response.status_code in {403, 429, 491, 502, 503}:
        raise AccessBlocked(f"HTTP {response.status_code}: {url}")
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return response


def ensure_accessible(response: requests.Response, url: str) -> None:
    response.encoding = response.apparent_encoding or "utf-8"
    blocked_marker = next(
        (marker for marker in MOJ_BLOCK_MARKERS if marker in response.text),
        "",
    )
    if response.status_code in {403, 429, 502, 503} or blocked_marker:
        detail = blocked_marker or f"HTTP {response.status_code}"
        raise AccessBlocked(f"{detail}: {url}")
    response.raise_for_status()


def parse_links(page_url: str, text: str, allowed_host: str) -> list[dict]:
    rows: list[dict] = []
    pattern = re.compile(
        r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S
    )
    for match in pattern.finditer(text):
        href, body = match.groups()
        title = clean_text(body)
        url = urljoin(page_url, html.unescape(href))
        parsed_url = urlsplit(url)
        if (
            allowed_host == "gongbao.court.gov.cn"
            and parsed_url.path.lower().startswith("/details/")
        ):
            url = urlunsplit(
                (
                    parsed_url.scheme,
                    parsed_url.netloc,
                    parsed_url.path,
                    "",
                    "",
                )
            )
        if (
            not title
            or len(title) < 4
            or allowed_host not in url
            or url.lower().startswith("javascript:")
        ):
            continue
        if not re.search(r"(?:xiangqing|content|t\d{8}_\d+|detail|Article)", url, re.I):
            continue
        date_match = re.search(
            r"(20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}日?)",
            text[match.end() : match.end() + 250],
        )
        if not date_match:
            date_match = re.search(
                r"(20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}日?)",
                text[max(0, match.start() - 150) : match.start()],
            )
        path_stem = Path(urlsplit(url).path).stem
        record_id = (
            path_stem.lower()
            if re.fullmatch(r"(?i)[0-9a-f]{32}", path_stem)
            else (re.sub(r"\D", "", path_stem) or url)
        )
        rows.append(
            {
                "record_id": record_id,
                "title": title,
                "publication_date": date_match.group(1) if date_match else "",
                "category": "",
                "publisher": "",
                "official_url": url,
                "catalog_url": page_url,
            }
        )
    return rows


def unique_rows(rows: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    result: list[dict] = []
    for row in rows:
        key = (str(row.get("record_id", "")), str(row.get("official_url", "")))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _form_inputs(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for tag in re.findall(r"<input\b[^>]*>", text, re.I):
        name_match = re.search(r'\bname=["\']([^"\']+)["\']', tag, re.I)
        if not name_match:
            continue
        value_match = re.search(r'\bvalue=["\']([^"\']*)["\']', tag, re.I)
        fields[name_match.group(1)] = html.unescape(
            value_match.group(1) if value_match else ""
        )
    return fields


def discover_moj_case_landing_url(root_url: str, text: str) -> str:
    for href in re.findall(r'\bhref=["\']([^"\']+)["\']', text, re.I):
        url = urljoin(root_url, html.unescape(href))
        parsed = urlsplit(url)
        if parsed.hostname != "alk.12348.gov.cn":
            continue
        query = {key.lower(): values for key, values in parse_qs(parsed.query).items()}
        database_ids = set(
            re.findall(r"\d+", ",".join(query.get("checkdatabaseid", [])))
        )
        if MOJ_CASE_DATABASE_IDS.issubset(database_ids):
            return url
    raise AccessBlocked("司法部案例库稳定根站未发现当前仲裁案例入口")


def discover_moj_case_search_url(landing_url: str, text: str) -> str:
    form_match = re.search(r"<form\b([^>]*)>", text, re.I | re.S)
    if form_match:
        action_match = re.search(
            r'\baction=["\']([^"\']+)["\']', form_match.group(1), re.I
        )
        if action_match:
            url = urljoin(landing_url, html.unescape(action_match.group(1)))
            if urlsplit(url).hostname == "alk.12348.gov.cn":
                return url
    parsed = urlsplit(landing_url)
    path = parsed.path.rstrip("/")
    if path.lower().endswith("/searchindex"):
        path = f"{path.rsplit('/', 1)[0]}/Search"
    else:
        path = f"{path}/Search"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def parse_moj_case_rows(
    page_url: str,
    text: str,
    catalog_url: str = "",
) -> list[dict]:
    rows: list[dict] = []
    link_pattern = re.compile(
        r"<a\b([^>]*)>(.*?)</a>",
        re.I | re.S,
    )
    for match in link_pattern.finditer(text):
        attributes, body = match.groups()
        href_match = re.search(r'\bhref=["\']([^"\']+)["\']', attributes, re.I)
        if not href_match:
            continue
        href = href_match.group(1)
        url = urljoin(page_url, html.unescape(href))
        title_match = re.search(r'\btitle=["\']([^"\']+)["\']', attributes, re.I)
        title = clean_text(title_match.group(1)) if title_match else clean_text(body)
        title = re.sub(r"^\d+\s+", "", title)
        if (
            "alk.12348.gov.cn" not in url
            or not re.search(r"/(?:LawSelect/)?Detail\b", url, re.I)
            or len(title) < 4
        ):
            continue
        query = parse_qs(urlsplit(url).query)
        lowered_query = {key.lower(): values for key, values in query.items()}
        system_ids = lowered_query.get("sysid", [])
        database_ids = lowered_query.get("dbid", [])
        if system_ids and database_ids:
            record_id = f"{database_ids[0]}:{system_ids[0]}"
        elif system_ids:
            record_id = system_ids[0]
        else:
            record_id = url
        nearby = text[max(0, match.start() - 250) : match.end() + 400]
        date_match = re.search(
            r"(20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}日?)",
            clean_text(nearby),
        )
        rows.append(
            {
                "record_id": record_id,
                "title": title,
                "publication_date": date_match.group(1) if date_match else "",
                "category": "仲裁案例",
                "publisher": "司法部",
                "official_url": url,
                "catalog_url": catalog_url or page_url,
            }
        )
    return unique_rows(rows)


def moj_legal_service_cases(
    max_pages: int,
    checkpoint_path: Path | None = None,
) -> tuple[list[dict], dict]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Referer": MOJ_CASE_ROOT_URL,
        }
    )
    root = session.get(MOJ_CASE_ROOT_URL, timeout=30)
    ensure_accessible(root, MOJ_CASE_ROOT_URL)
    landing_url = discover_moj_case_landing_url(root.url, root.text)
    landing = session.get(landing_url, timeout=30)
    ensure_accessible(landing, landing_url)
    search_url = discover_moj_case_search_url(landing.url, landing.text)
    session.headers["Referer"] = landing_url
    fields = _form_inputs(landing.text)
    fields.update(
        {
            "keywords": "",
            "checkDatabaseID": "74,75,76,77",
            "pageSizeNow": fields.get("pageSizeNow") or "10",
        }
    )

    page_limit = max_pages if max_pages > 0 else 1
    rows: list[dict] = []
    previous_urls: set[str] = set()
    pages_fetched = 0
    next_page = 1
    if max_pages > 1 and checkpoint_path and checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint.get("source_id") == "moj_legal_service_case_database":
            rows = checkpoint.get("rows", [])
            previous_urls = set(checkpoint.get("previous_urls", []))
            pages_fetched = int(checkpoint.get("pages_fetched", 0))
            next_page = int(checkpoint.get("next_page", 1))

    exhausted = False
    for page in range(next_page, page_limit + 1):
        fields["pageIndexNow"] = str(page)
        response = session.post(
            search_url,
            data=fields,
            timeout=30,
        )
        ensure_accessible(response, search_url)
        page_rows = parse_moj_case_rows(
            response.url,
            response.text,
            catalog_url=landing_url,
        )
        urls = {row["official_url"] for row in page_rows}
        if not page_rows or urls == previous_urls:
            exhausted = True
            break
        previous_urls = urls
        rows.extend(page_rows)
        pages_fetched += 1
        rows = unique_rows(rows)
        if max_pages > 1 and checkpoint_path:
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            checkpoint_path.write_text(
                json.dumps(
                    {
                        "source_id": "moj_legal_service_case_database",
                        "next_page": page + 1,
                        "pages_fetched": pages_fetched,
                        "previous_urls": sorted(previous_urls),
                        "rows": rows,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        if page < page_limit:
            time.sleep(2)

    if not rows:
        raise AccessBlocked("司法部案例库新接口可访问，但未解析到仲裁案例列表")
    if exhausted and checkpoint_path:
        checkpoint_path.unlink(missing_ok=True)
    return unique_rows(rows), {
        "pages_fetched": pages_fetched,
        "mode": "full_scan" if max_pages > 1 else "incremental_latest_pages",
        "partial": not exhausted,
    }


def moj_admin_regulations(max_pages: int) -> tuple[list[dict], dict]:
    first = fetch("https://xzfg.moj.gov.cn/search2.html")
    total_match = re.search(r'id=["\']law-total["\'][^>]*value=["\'](\d+)', first.text)
    total = int(total_match.group(1)) if total_match else 0
    pages = max(1, (total + 9) // 10)
    if max_pages:
        pages = min(pages, max_pages)
    rows: list[dict] = []
    for page in range(1, pages + 1):
        response = first if page == 1 else fetch(
            f"https://xzfg.moj.gov.cn/search2.html?PageIndex={page}"
        )
        for match in re.finditer(
            r'<a[^>]+href=["\']([^"\']*detail\?LawID=(\d+))["\'][^>]*>(.*?)</a>',
            response.text,
            re.I | re.S,
        ):
            url, law_id, title = match.groups()
            rows.append(
                {
                    "record_id": law_id,
                    "title": clean_text(title),
                    "publication_date": "",
                    "category": "行政法规",
                    "publisher": "国务院办公厅、司法部",
                    "official_url": urljoin(response.url, url),
                    "catalog_url": response.url,
                }
            )
    return unique_rows(rows), {
        "official_total": total,
        "pages_fetched": pages,
        "partial": bool(max_pages and pages * 10 < total),
    }


def _rsa_header() -> str:
    try:
        from Crypto.Cipher import PKCS1_v1_5
        from Crypto.PublicKey import RSA
    except ImportError as error:
        raise RuntimeError("国家规章库适配器需要 pycryptodome") from error
    public_key = (
        "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCWGTHvPbNkzQNxTJwSZbsgHKyLl/"
        "OK11kCZNmVVSFK3lUbmHgh7Ain1gdaf7G/ETh/wQm/9BAO/U36yWPizzlwHCUcWJX"
        "BRsY10PsnYIlBXH/cjqQaEbmEghxcjdYtLtkudoMfoMDiJk+tPC7UEZd8TI2u26vtt"
        "NF++6tHi1HdeQIDAQAB"
    )
    key = RSA.import_key(
        f"-----BEGIN PUBLIC KEY-----\n{public_key}\n-----END PUBLIC KEY-----"
    )
    encrypted = PKCS1_v1_5.new(key).encrypt(
        b"f8f49ea85885466598c5261f7f8607fb"
    )
    return quote(base64.b64encode(encrypted).decode("ascii"), safe="")


def national_rules_database(max_pages: int) -> tuple[list[dict], dict]:
    endpoint = (
        "https://sousuoht.www.gov.cn/athena/forward/"
        "BD8730CDDA12515E2D9E1B21AA11C0D6"
    )
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json;charset=utf-8",
        "athenaAppKey": _rsa_header(),
        "athenaAppName": quote("规章库", safe=""),
    }
    rows: list[dict] = []
    totals: dict[str, int] = {}
    partial = False
    for category in ("部门规章", "地方政府规章"):
        page = 1
        while True:
            body = {
                "code": "18258ab0ac9",
                "preference": str(uuid.uuid4()),
                "searchFields": [
                    {
                        "fieldName": "f_202321807875",
                        "searchWord": category,
                        "searchType": "TERM",
                        "withHighLight": True,
                    }
                ],
                "sorts": [],
                "resultFields": [
                    "f_202291670697",
                    "f_202321360426",
                    "f_20232124962",
                    "f_202321807875",
                    "f_20232151076",
                    "f_202321423473",
                    "f_202328191239",
                    "f_20221110222856",
                    "doc_pub_url",
                ],
                "trackTotalHits": "true",
                "tableName": "t_1860c735d31",
                "pageSize": 100,
                "pageNo": page,
                "granularity": "ALL",
            }
            response = fetch(endpoint, method="post", json=body, headers=headers)
            payload = response.json()
            if payload.get("resultCode", {}).get("code") != 200:
                raise RuntimeError(payload.get("resultCode", {}).get("cnMsg", "接口错误"))
            data = payload["result"]["data"]
            pager = data["pager"]
            totals[category] = int(pager["total"])
            partial = partial or bool(
                max_pages and max_pages < int(pager["pageCount"])
            )
            for item in data.get("list", []):
                urls = item.get("f_20232124962") or []
                official_url = item.get("doc_pub_url") or (
                    urls[0] if isinstance(urls, list) and urls else ""
                )
                rows.append(
                    {
                        "record_id": clean_text(item.get("f_202291670697"))
                        or official_url,
                        "title": clean_text(item.get("f_202321360426")),
                        "publication_date": clean_text(item.get("f_20221110222856")),
                        "category": category,
                        "publisher": clean_text(
                            item.get("f_202328191239")
                            or item.get("f_20232151076")
                            or item.get("f_202321423473")
                        ),
                        "official_url": official_url,
                        "catalog_url": "https://www.gov.cn/zhengce/xxgk/gjgzk/index.htm",
                    }
                )
            if page >= int(pager["pageCount"]) or (max_pages and page >= max_pages):
                break
            page += 1
    return unique_rows(rows), {"official_totals": totals, "partial": partial}


def state_council_index(kind: str, max_pages: int) -> tuple[list[dict], dict]:
    source_types = {
        "state_council_policy_database": [
            ("zhengcelibrary_gw", "国务院文件"),
            ("zhengcelibrary_or", "政策解读与相关材料候选"),
        ],
        "state_council_gazette": [("zhengcelibrary_gb", "国务院公报")],
        "central_ministry_websites": [
            ("zhengcelibrary_bm", "国务院部门文件")
        ],
    }[kind]
    rows: list[dict] = []
    totals: dict[str, int] = {}
    pages_fetched = 0
    partial = False
    for source_type, category in source_types:
        page = 1
        fetched_for_type = 0
        while True:
            params = {
                "t": source_type,
                "q": "",
                "sort": "score",
                "sortType": 1,
                "searchfield": "title:content:summary",
                "p": page,
                "n": 100,
            }
            search = fetch(
                "https://sousuo.www.gov.cn/search-gov/data", params=params
            ).json()
            result = search["searchVO"]
            total = int(result["totalCount"])
            totals[category] = total
            items = result.get("listVO") or []
            for item in items:
                rows.append(
                    {
                        "record_id": clean_text(item.get("id"))
                        or item.get("url", ""),
                        "title": clean_text(item.get("title")),
                        "publication_date": clean_text(item.get("pubtimeStr")),
                        "category": category,
                        "publisher": clean_text(
                            item.get("source") or item.get("fwdw")
                        ),
                        "official_url": item.get("url", ""),
                        "catalog_url": (
                            "https://sousuo.www.gov.cn/zcwjk/policyRetrieval"
                        ),
                    }
                )
            fetched_for_type += len(items)
            pages_fetched += 1
            if (
                not items
                or fetched_for_type >= total
                or (max_pages and page >= max_pages)
            ):
                partial = partial or bool(max_pages and fetched_for_type < total)
                break
            page += 1
    return unique_rows(rows), {
        "official_totals": totals,
        "pages_fetched": pages_fetched,
        "partial": partial,
    }


def central_ministry_websites(max_pages: int) -> tuple[list[dict], dict]:
    endpoint = "https://zfwzzc.www.gov.cn/check_web/downloadTemp_downFile.action"
    command = [
        "curl.exe",
        "-sS",
        "-L",
        "--max-time",
        "60",
        "-d",
        "downames=bwmh",
        endpoint,
    ]
    process = subprocess.run(command, capture_output=True, check=False)
    if process.returncode or not process.stdout.startswith(b"PK"):
        raise AccessBlocked("政府网站基本信息库CSV下载失败")
    rows: list[dict] = []
    with zipfile.ZipFile(io.BytesIO(process.stdout)) as archive:
        for name in archive.namelist():
            if not name.lower().endswith(".csv"):
                continue
            raw = archive.read(name)
            encoding = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "gb18030"
            text = raw.decode(encoding, errors="replace")
            reader = csv.DictReader(io.StringIO(text))
            for item in reader:
                values = {clean_text(k): clean_text(v) for k, v in item.items()}
                url = next(
                    (v for v in values.values() if re.match(r"https?://", v)), ""
                )
                url = url.split(";")[0]
                title = next(
                    (
                        v
                        for k, v in values.items()
                        if any(word in k for word in ("网站名称", "单位名称", "主办单位"))
                    ),
                    "",
                )
                if title and url:
                    rows.append(
                        {
                            "record_id": url,
                            "title": title,
                            "publication_date": "",
                            "category": "国务院部门官网白名单",
                            "publisher": title,
                            "official_url": url,
                            "catalog_url": (
                                "https://zfwzzc.www.gov.cn/check_web/"
                                "databaseInfo/download"
                            ),
                        }
                    )
    if not rows:
        raise AccessBlocked("政府网站基本信息库下载成功但未解析到部委门户")
    documents, details = state_council_index(
        "central_ministry_websites", max_pages
    )
    return unique_rows(rows + documents), {
        "official_whitelist_rows": len(rows),
        **details,
    }


def static_catalog(source_id: str, max_pages: int) -> tuple[list[dict], dict]:
    settings = {
        "spc_website": (
            "court.gov.cn",
            [
                ("https://www.court.gov.cn/fabu/gengduo/16.html", 50, "司法解释"),
                ("https://www.court.gov.cn/fabu/gengduo/151.html", 11, "指导性案例"),
                ("https://www.court.gov.cn/zixun/gengduo/104.html", 50, "典型案例"),
            ],
            "最高人民法院",
        ),
        "spp_website": (
            "spp.gov.cn",
            [
                ("https://www.spp.gov.cn/spp/sfjs/index.shtml", 50, "司法解释"),
                ("https://www.spp.gov.cn/spp/gfwj/index.shtml", 50, "规范文件"),
                ("https://www.spp.gov.cn/spp/jczdal/index.shtml", 30, "指导性案例"),
                ("https://www.spp.gov.cn/spp/zgjdxal/index.shtml", 100, "典型案例"),
            ],
            "最高人民检察院",
        ),
        "spc_gazette": (
            "gongbao.court.gov.cn",
            [
                (
                    "http://gongbao.court.gov.cn/QueryArticle.html?serial_no=sfjs",
                    1000,
                    "公报司法解释",
                ),
                (
                    "http://gongbao.court.gov.cn/ArticleList.html?serial_no=al",
                    1000,
                    "公报指导性案例",
                ),
                (
                    "http://gongbao.court.gov.cn/ArticleList.html?serial_no=cpwsxd",
                    1000,
                    "公报裁判文书选登",
                ),
            ],
            "最高人民法院",
        ),
    }
    host, catalogs, publisher = settings[source_id]
    rows: list[dict] = []
    fetched = 0
    catalog_errors: list[dict[str, str | int]] = []
    catalog_session = requests.Session() if source_id == "spc_gazette" else None
    for base, declared_pages, category in catalogs:
        limit = min(declared_pages, max_pages) if max_pages else declared_pages
        previous_urls: set[str] = set()
        for page in range(1, limit + 1):
            request_kwargs: dict = {}
            if page == 1:
                url = base
                page_url = base
            elif source_id == "spc_gazette":
                parsed_base = urlsplit(base)
                url = urlunsplit(
                    (
                        parsed_base.scheme,
                        parsed_base.netloc,
                        parsed_base.path,
                        "",
                        "",
                    )
                )
                form_data = {
                    key: values[-1]
                    for key, values in parse_qs(parsed_base.query).items()
                    if values
                }
                form_data["page"] = str(page)
                request_kwargs = {
                    "method": "post",
                    "data": form_data,
                    "headers": {"X-Requested-With": "XMLHttpRequest"},
                }
                page_url = f"{base}&page={page}"
            elif "index.shtml" in base:
                url = base.replace("index.shtml", f"index_{page - 1}.shtml")
                page_url = url
            elif re.search(r"/\d+\.html$", base):
                url = re.sub(
                    r"(\d+)\.html$",
                    lambda match: f"{match.group(1)}_{page}.html",
                    base,
                )
                page_url = url
            elif "?" in base:
                url = f"{base}&page={page}"
                page_url = url
            else:
                break
            if catalog_session is not None:
                request_kwargs = {
                    **request_kwargs,
                    "session": catalog_session,
                    "retries": 6,
                    "retry_delay": 2.0,
                }
            try:
                response = fetch(url, **request_kwargs)
            except AccessBlocked as error:
                status_match = re.search(r"HTTP\s+(\d{3})", str(error))
                catalog_errors.append(
                    {
                        "url": page_url,
                        "status_code": (
                            int(status_match.group(1)) if status_match else 0
                        ),
                        "message": str(error),
                    }
                )
                break
            except requests.HTTPError as error:
                if error.response is not None and error.response.status_code == 404:
                    break
                catalog_errors.append(
                    {
                        "url": page_url,
                        "status_code": (
                            error.response.status_code
                            if error.response is not None
                            else 0
                        ),
                        "message": str(error),
                    }
                )
                break
            except requests.RequestException as error:
                catalog_errors.append(
                    {
                        "url": page_url,
                        "status_code": 0,
                        "message": str(error),
                    }
                )
                break
            page_rows = parse_links(page_url, response.text, host)
            urls = {row["official_url"] for row in page_rows}
            if not urls or (page > 1 and urls == previous_urls):
                break
            previous_urls = urls
            fetched += 1
            for row in page_rows:
                row["publisher"] = publisher
                row["category"] = category
            rows.extend(page_rows)
    if not rows and catalog_errors:
        first_error = catalog_errors[0]
        raise AccessBlocked(
            f"全部目录不可访问: {first_error['status_code']} "
            f"{first_error['url']} {first_error['message']}"
        )
    return unique_rows(rows), {
        "pages_fetched": fetched,
        "partial": bool(
            catalog_errors
            or (
                max_pages
                and any(declared_pages > max_pages for _, declared_pages, _ in catalogs)
            )
        ),
        "catalog_errors": catalog_errors,
    }


def write_output(
    output: Path, source_id: str, rows: list[dict], details: dict, complete: bool
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with (output / "official_index.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({"source_id": source_id, **row})
    meta = {
        "source_id": source_id,
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "row_count": len(rows),
        "complete": complete,
        **details,
    }
    (output / "official_index_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-pages", type=int, default=0)
    parser.add_argument("--checkpoint", type=Path)
    args = parser.parse_args()
    runners = {
        "moj_admin_regulations": moj_admin_regulations,
        "national_rules_database": national_rules_database,
        "state_council_policy_database": lambda pages: state_council_index(
            "state_council_policy_database", pages
        ),
        "state_council_gazette": lambda pages: state_council_index(
            "state_council_gazette", pages
        ),
        "central_ministry_websites": central_ministry_websites,
        "spc_website": lambda pages: static_catalog("spc_website", pages),
        "spc_gazette": lambda pages: static_catalog("spc_gazette", pages),
        "spp_website": lambda pages: static_catalog("spp_website", pages),
        "moj_legal_service_case_database": lambda pages: moj_legal_service_cases(
            pages, checkpoint_path=args.checkpoint
        ),
    }
    try:
        rows, details = runners[args.source](args.max_pages)
        complete = not details.pop("partial", False)
        write_output(args.output, args.source, rows, details, complete=complete)
        print(f"source={args.source} rows={len(rows)}")
        return 0
    except AccessBlocked as error:
        write_output(
            args.output, args.source, [], {"blocked_reason": str(error)}, complete=False
        )
        print(str(error), file=sys.stderr)
        return 20


if __name__ == "__main__":
    raise SystemExit(main())
