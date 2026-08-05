"""
P2 URL可达性+标题比对
======================
验证官方URL是否可访问，获取页面标题与本地标题比对。
不做批量全文下载，只验证URL有效性。
"""

import logging
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .base import BaseVerifier
from models import FileRecord, VerificationEvidence
import config

logger = logging.getLogger(__name__)


def _extract_page_title(html: str) -> str:
    """从HTML提取<title>标签内容。"""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
    if m:
        title = m.group(1).strip()
        # 去除HTML实体
        title = re.sub(r"&[^;]+;", "", title)
        return title
    return ""


def _normalize_title_for_compare(title: str) -> str:
    """规范化标题用于比对。"""
    t = title.strip()
    # 去除网站名称后缀
    for suffix in [
        "_中华人民共和国最高人民法院",
        "_中华人民共和国最高人民检察院",
        "_中国政府网",
        "_国家市场监督管理总局",
        "-中国政府网",
        "-中华人民共和国最高人民法院",
    ]:
        if t.endswith(suffix):
            t = t[:-len(suffix)]
    # 去除空白和标点差异
    t = re.sub(r"\s+", "", t)
    return t


class URLCheckVerifier(BaseVerifier):
    """P2 URL可达性核验器。"""

    channel = "url_check"
    priority = 2

    def __init__(self, http_timeout: int = None, **kwargs):
        super().__init__(**kwargs)
        self.timeout = http_timeout or config.HTTP_TIMEOUT
        self._last_request_time = 0.0
        self._session = None

    def _get_session(self):
        """获取HTTP会话（懒加载）。"""
        if self._session is None:
            import requests
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            })
        return self._session

    def _get_min_interval(self) -> float:
        return config.HTTP_MIN_INTERVAL

    def _rate_limit(self):
        """限流。"""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._get_min_interval():
            time.sleep(self._get_min_interval() - elapsed)
        self._last_request_time = time.time()

    def verify(self, record: FileRecord) -> VerificationEvidence:
        """对单个文件进行URL可达性检查。"""
        url = record.official_url
        if not url or not url.startswith("http"):
            return self._make_evidence(
                status="SKIP",
                evidence_type="no_url",
                detail="文件无官方URL",
            )

        # 限流
        self._rate_limit()

        session = self._get_session()
        try:
            # HEAD请求检查可达性
            response = session.head(
                url,
                timeout=self.timeout,
                allow_redirects=True,
            )
            http_status = response.status_code

            if http_status == 200:
                # 可访问，尝试获取标题
                page_title = self._get_page_title(session, url)

                # 对SPA网站（如FLK）跳过标题比对
                parsed = urlparse(url)
                is_spa = any(domain in parsed.netloc for domain in [
                    "flk.npc.gov.cn",  # 国家法律法规数据库是SPA
                ])

                if is_spa:
                    return self._make_evidence(
                        status="SOURCE_URL_REACHABLE",
                        evidence_type="url_reachable_spa",
                        detail=f"URL可访问（SPA站点，跳过标题比对）: {parsed.netloc}",
                        url_reachable=True,
                        http_status=http_status,
                        title_match=None,
                    )

                # 标题比对
                title_match = False
                if page_title:
                    title_match = self._compare_titles(record.title, page_title)

                if title_match:
                    return self._make_evidence(
                        status="SOURCE_URL_REACHABLE",
                        evidence_type="url_reachable_title_match",
                        detail=f"URL可访问，标题匹配: {page_title[:50]}",
                        url_reachable=True,
                        http_status=http_status,
                        page_title=page_title,
                        title_match=True,
                    )
                else:
                    return self._make_evidence(
                        status="URL_REACHABLE_TITLE_MISMATCH",
                        evidence_type="url_reachable_title_mismatch",
                        detail=(
                            f"URL可访问但标题不匹配: "
                            f"本地={record.title[:30]} vs 页面={page_title[:30]}"
                        ),
                        url_reachable=True,
                        http_status=http_status,
                        page_title=page_title,
                        title_match=False,
                    )
            elif http_status in (301, 302, 303, 307, 308):
                # 重定向
                final_url = response.headers.get("Location", url)
                return self._make_evidence(
                    status="URL_REDIRECT",
                    evidence_type="redirect",
                    detail=f"重定向到: {final_url[:80]}",
                    url_reachable=False,
                    http_status=http_status,
                )
            elif http_status == 404:
                return self._make_evidence(
                    status="URL_NOT_FOUND",
                    evidence_type="404",
                    detail="URL返回404",
                    url_reachable=False,
                    http_status=http_status,
                )
            elif http_status in (403, 429, 500, 502, 503):
                return self._make_evidence(
                    status="URL_BLOCKED",
                    evidence_type=f"http_{http_status}",
                    detail=f"URL返回 {http_status}",
                    url_reachable=False,
                    http_status=http_status,
                )
            else:
                return self._make_evidence(
                    status="URL_UNEXPECTED_STATUS",
                    evidence_type=f"http_{http_status}",
                    detail=f"URL返回意外状态码 {http_status}",
                    url_reachable=False,
                    http_status=http_status,
                )

        except Exception as e:
            return self._make_evidence(
                status="URL_ERROR",
                evidence_type="request_error",
                detail=f"请求失败: {str(e)[:100]}",
                url_reachable=False,
                error=str(e),
            )

    def _get_page_title(self, session, url: str) -> str:
        """获取页面标题。对部分站点使用GET请求获取完整HTML。"""
        try:
            # 对需要GET才能获取标题的站点
            parsed = urlparse(url)
            needs_get = any(domain in parsed.netloc for domain in [
                "flk.npc.gov.cn", "spp.gov.cn", "court.gov.cn",
            ])

            if needs_get:
                response = session.get(url, timeout=self.timeout, allow_redirects=True)
                if response.status_code == 200:
                    # 尝试多种编码
                    for encoding in ["utf-8", "gbk", "gb2312"]:
                        try:
                            html = response.content.decode(encoding)
                            return _extract_page_title(html)
                        except UnicodeDecodeError:
                            continue
            else:
                # HEAD请求也能拿到一些标题信息
                response = session.head(url, timeout=self.timeout, allow_redirects=True)
                # 某些站点在HEAD响应中没有title，返回空
                return ""

        except Exception as e:
            logger.debug(f"[URL] 获取标题失败 {url}: {e}")

        return ""

    def _compare_titles(self, local_title: str, page_title: str) -> bool:
        """比对本地标题与页面标题。"""
        if not local_title or not page_title:
            return False

        norm_local = _normalize_title_for_compare(local_title)
        norm_page = _normalize_title_for_compare(page_title)

        # 精确匹配
        if norm_local == norm_page:
            return True

        # 包含匹配（一方包含另一方）
        if len(norm_local) >= 5 and len(norm_page) >= 5:
            if norm_local in norm_page or norm_page in norm_local:
                return True

        return False
