"""
P1 元典MCP批量验证
====================
通过元典法律数据库交叉验证法律法规类文件。
使用MCP接口 yuandian_law_vector_search 进行语义检索。
"""

import json
import logging
import time
import hashlib
from pathlib import Path
from typing import Optional

from .base import BaseVerifier
from models import FileRecord, VerificationEvidence
import config
from normalizer import extract_body_from_md, normalize_text

logger = logging.getLogger(__name__)


class YuandianVerifier(BaseVerifier):
    """P1 元典MCP核验器。"""

    channel = "yuandian"
    priority = 1

    def __init__(self, mcp_caller=None, cache_file=None, **kwargs):
        """
        Args:
            mcp_caller: 可调用的MCP接口函数。
            cache_file: 预查询的元典结果缓存文件路径。
        """
        super().__init__(**kwargs)
        self.mcp_caller = mcp_caller
        self.cache_file = cache_file or Path(config.OUTPUT_DIR / "yuandian_cache.json")
        self._cache = {}
        self._last_call_time = 0.0
        self._load_cache()

    def _load_cache(self):
        """加载缓存。"""
        if self.cache_file.exists():
            with open(self.cache_file, "r", encoding="utf-8") as f:
                self._cache = json.load(f)
            logger.info(f"[元典] 加载缓存 {len(self._cache)} 条")

    def _get_cache_key(self, record: FileRecord) -> str:
        """生成缓存键。"""
        parts = []
        if record.title:
            parts.append(record.title)
        if record.doc_number:
            parts.append(record.doc_number)
        return "|".join(parts) if parts else record.local_path[:50]

    def verify(self, record: FileRecord) -> VerificationEvidence:
        """对单个文件进行元典核验。"""
        # 先检查缓存
        cache_key = self._get_cache_key(record)
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            return self._make_evidence(
                status=cached.get("status", "YUANDIAN_CACHED"),
                evidence_type=cached.get("evidence_type", "from_cache"),
                detail=cached.get("detail", ""),
                title_match=cached.get("title_match"),
            )

        # 缓存未命中，尝试实时查询
        if self.mcp_caller is None:
            return self._make_evidence(
                status="YUANDIAN_NO_CACHE",
                evidence_type="no_mcp_caller",
                detail=f"缓存未命中且无MCP调用器: {record.title[:30]}",
            )

        # 实时查询
        query = self._build_query(record)
        if not query:
            return self._make_evidence(
                status="SKIP",
                evidence_type="insufficient_metadata",
            )

        self._rate_limit()
        result = self._call_yuandian(query)
        fatiao_list = result.get("extra", {}).get("fatiao", [])

        if not fatiao_list:
            ev = self._make_evidence(
                status="YUANDIAN_NOT_FOUND",
                evidence_type="no_match",
            )
        else:
            first = fatiao_list[0]
            official_title = first.get("fgtitle", "")
            title_match = self._compare_titles(record.title, official_title)

            ev = self._make_evidence(
                status="INDEX_TITLE_MATCHED" if title_match else "INDEX_TITLE_MISMATCH",
                evidence_type="title_match" if title_match else "title_mismatch",
                title_match=title_match,
            )

        # 保存到缓存
        self._cache[cache_key] = {
            "status": ev.status,
            "evidence_type": ev.evidence_type,
            "title_match": ev.title_match,
            "detail": ev.detail,
        }
        self._save_cache()

        return ev

    def _build_query(self, record: FileRecord) -> str:
        """构造元典检索查询。"""
        parts = []
        if record.title:
            parts.append(record.title)
        if record.doc_number:
            parts.append(record.doc_number)
        if record.issuing_body:
            parts.append(record.issuing_body)

        return " ".join(parts[:3]) if parts else ""

    def _save_cache(self):
        """保存缓存。"""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[元典] 保存缓存失败: {e}")

    def _rate_limit(self):
        """限流。"""
        now = time.time()
        elapsed = now - self._last_call_time
        if elapsed < self._get_min_interval():
            time.sleep(self._get_min_interval() - elapsed)
        self._last_call_time = time.time()

    def _get_min_interval(self) -> float:
        return config.YUANDIAN_MIN_INTERVAL

    def _call_yuandian(self, query: str, filters: dict = None) -> dict:
        """调用元典API。"""
        if self.mcp_caller is None:
            return {"extra": {"fatiao": []}}

        self._rate_limit()
        try:
            result = self.mcp_caller(query=query, filters=filters or {})
            return result
        except Exception as e:
            logger.error(f"[元典] API调用失败: {e}")
            return {"extra": {"fatiao": []}}

    def _build_query(self, record: FileRecord) -> str:
        """构造元典检索查询。"""
        parts = []
        if record.title:
            parts.append(record.title)
        if record.doc_number:
            parts.append(record.doc_number)
        return " ".join(parts[:2]) if parts else ""

    def _compare_titles(self, local_title: str, official_title: str) -> bool:
        """比对标题是否一致。"""
        if not local_title or not official_title:
            return False
        import re
        def _norm(t):
            t = t.strip()
            t = re.sub(r"[（(]\d{4}年[）)]", "", t)
            t = re.sub(r"\s+", "", t)
            return t
        return _norm(local_title) == _norm(official_title)

    def verify_batch(
        self,
        records: list,
        checkpoint,
        stats,
    ) -> list:
        """批量核验，覆写基类以添加进度输出。"""
        logger.info(f"[P1] 开始元典批量验证，共 {len(records)} 份文件")

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
                logger.error(f"[元典] 核验失败 {rec.local_path}: {e}")
                evidence = self._make_evidence(
                    status="ERROR",
                    error=str(e),
                )
                evidences.append(evidence)
                checkpoint.add_result(rec.local_path, evidence)
                stats.processed += 1
                stats.errors += 1

            # 进度输出
            if (i + 1) % config.PROGRESS_INTERVAL == 0:
                logger.info(
                    f"[P1] 进度: {i+1}/{len(records)} | "
                    f"通过: {sum(1 for e in evidences if 'VERIFIED' in e.status)}"
                )

        return evidences
