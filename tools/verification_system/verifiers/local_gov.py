"""
P3 地方政府网站分批核验
========================
按城市分批验证地方政府网站上的法规文件。
不集中依赖，按城市独立处理。
"""

import logging
import re
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from .base import BaseVerifier
from models import FileRecord, VerificationEvidence
import config

logger = logging.getLogger(__name__)


def _extract_city_from_domain(domain: str) -> str:
    """从域名提取城市名。"""
    # www.sz.gov.cn → sz
    # sfj.hefei.gov.cn → hefei
    # public.zhengzhou.gov.cn → zhengzhou
    m = re.search(r"(?:www\.|sfj\.|public\.|zwgk\.|xxgk\.)?([a-z]+)\.gov\.cn", domain)
    if m:
        return m.group(1)
    return domain


class LocalGovVerifier(BaseVerifier):
    """P3 地方政府网站核验器。"""

    channel = "local_gov"
    priority = 3

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._session = None
        self._last_request_time = 0.0
        self._city_results: Dict[str, dict] = {}

    def _get_session(self):
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
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._get_min_interval():
            time.sleep(self._get_min_interval() - elapsed)
        self._last_request_time = time.time()

    def verify(self, record: FileRecord) -> VerificationEvidence:
        """对单个文件进行地方政府网站核验。"""
        url = record.official_url
        if not url or not url.startswith("http"):
            return self._make_evidence(
                status="SKIP",
                evidence_type="no_url",
                detail="文件无官方URL",
            )

        # 检查是否为地方政府网站
        parsed = urlparse(url)
        domain = parsed.netloc
        if not any(d in domain for d in [".gov.cn"]):
            return self._make_evidence(
                status="SKIP",
                evidence_type="not_local_gov",
                detail=f"非地方政府网站: {domain}",
            )

        # 限流
        self._rate_limit()

        session = self._get_session()
        try:
            response = session.head(
                url,
                timeout=config.HTTP_TIMEOUT,
                allow_redirects=True,
            )
            http_status = response.status_code
            city = _extract_city_from_domain(domain)

            if http_status == 200:
                # 记录城市访问情况
                if city not in self._city_results:
                    self._city_results[city] = {
                        "domain": domain,
                        "reachable": 0,
                        "unreachable": 0,
                        "tested": 0,
                    }
                self._city_results[city]["reachable"] += 1
                self._city_results[city]["tested"] += 1

                return self._make_evidence(
                    status="SOURCE_URL_REACHABLE",
                    evidence_type="url_reachable",
                    detail=f"地方政府网站可达: {domain} ({city})",
                    url_reachable=True,
                    http_status=http_status,
                )
            else:
                if city not in self._city_results:
                    self._city_results[city] = {
                        "domain": domain,
                        "reachable": 0,
                        "unreachable": 0,
                        "tested": 0,
                    }
                self._city_results[city]["unreachable"] += 1
                self._city_results[city]["tested"] += 1

                return self._make_evidence(
                    status="LOCAL_GOV_UNREACHABLE",
                    evidence_type=f"http_{http_status}",
                    detail=f"地方政府网站返回 {http_status}: {domain}",
                    url_reachable=False,
                    http_status=http_status,
                )

        except Exception as e:
            return self._make_evidence(
                status="LOCAL_GOV_ERROR",
                evidence_type="request_error",
                detail=f"请求失败: {str(e)[:100]}",
                url_reachable=False,
                error=str(e),
            )

    def verify_batch(
        self,
        records: list,
        checkpoint,
        stats,
    ) -> list:
        """批量核验，按城市分组输出进度。"""
        logger.info(f"[P3] 开始地方政府网站核验，共 {len(records)} 份文件")

        # 按城市分组
        city_groups: Dict[str, list] = {}
        for rec in records:
            if rec.has_url:
                parsed = urlparse(rec.official_url)
                city = _extract_city_from_domain(parsed.netloc)
                if city not in city_groups:
                    city_groups[city] = []
                city_groups[city].append(rec)

        logger.info(f"[P3] 涉及 {len(city_groups)} 个城市")

        evidences = []
        for i, rec in enumerate(records):
            if checkpoint and checkpoint.is_processed_in_phase(rec.local_path, self.channel):
                continue

            try:
                evidence = self.verify(rec)
                evidences.append(evidence)
                checkpoint.add_result(rec.local_path, evidence)
                stats.processed += 1
                self._update_stats(stats, evidence)
            except Exception as e:
                logger.error(f"[P3] 核验失败 {rec.local_path}: {e}")
                evidence = self._make_evidence(
                    status="ERROR",
                    error=str(e),
                )
                evidences.append(evidence)
                checkpoint.add_result(rec.local_path, evidence)
                stats.processed += 1
                stats.errors += 1

            # 进度输出
            if (i + 1) % 50 == 0:
                logger.info(f"[P3] 进度: {i+1}/{len(records)}")

        # 输出城市统计
        logger.info("[P3] 城市访问统计:")
        for city, info in sorted(self._city_results.items(), key=lambda x: -x[1]["tested"]):
            logger.info(
                f"  {city} ({info['domain']}): "
                f"测试 {info['tested']}，可达 {info['reachable']}，不可达 {info['unreachable']}"
            )

        return evidences
