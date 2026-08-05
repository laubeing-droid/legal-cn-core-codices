"""
P4 案例多渠道核验
==================
对案例类文件（80/81/82目录）进行多渠道交叉验证。
使用元典案例检索 + 微信搜一搜定位官方发布。
"""

import logging
import re
import time
from pathlib import Path
from typing import Optional

from .base import BaseVerifier
from models import FileRecord, VerificationEvidence
import config

logger = logging.getLogger(__name__)


def _extract_case_number(title: str) -> str:
    """从标题提取案号。"""
    # 匹配（2021）最高法民再123号 等格式
    m = re.search(r"[（(]\d{4}[）)].*?号", title)
    if m:
        return m.group(0)
    return ""


def _extract_case_type(title: str) -> str:
    """从标题推断案例类型。"""
    if "指导性案例" in title:
        return "指导性案例"
    elif "典型案例" in title:
        return "典型案例"
    elif "公报" in title:
        return "公报案例"
    elif "仲裁" in title:
        return "仲裁案例"
    elif "多元解纷" in title:
        return "多元解纷"
    else:
        return "其他"


class WechatCaseVerifier(BaseVerifier):
    """P4 案例多渠道核验器。"""

    channel = "wechat_case"
    priority = 4

    def __init__(self, mcp_caller=None, **kwargs):
        super().__init__(**kwargs)
        self.mcp_caller = mcp_caller
        self._last_call_time = 0.0

    def _get_min_interval(self) -> float:
        return config.YUANDIAN_MIN_INTERVAL

    def verify(self, record: FileRecord) -> VerificationEvidence:
        """对单个案例文件进行多渠道核验。"""
        # 1. 元典案例检索
        yuandian_result = self._verify_with_yuandian(record)

        # 2. 如果元典验证通过，直接返回
        if yuandian_result:
            return yuandian_result

        # 3. 否则标记为待进一步核验
        return self._make_evidence(
            status="CASE_NEEDS_FURTHER_VERIFICATION",
            evidence_type="yuandian_not_found",
            detail=f"元典未收录，需通过微信或其他渠道核验: {record.title[:50]}",
        )

    def _verify_with_yuandian(self, record: FileRecord) -> Optional[VerificationEvidence]:
        """使用元典进行案例核验。"""
        if self.mcp_caller is None:
            return None

        # 构造查询
        query = record.title
        if not query:
            return None

        # 限流
        now = time.time()
        elapsed = now - self._last_call_time
        if elapsed < self._get_min_interval():
            time.sleep(self._get_min_interval() - elapsed)

        try:
            result = self.mcp_caller(query=query)
            self._last_call_time = time.time()

            fatiao_list = result.get("extra", {}).get("fatiao", [])
            if not fatiao_list:
                return None

            # 取第一条结果
            first = fatiao_list[0]
            official_title = first.get("fgtitle", "")
            score = first.get("score", 0)

            # 标题比对
            title_match = self._compare_titles(record.title, official_title)

            if title_match:
                return self._make_evidence(
                    status="CASE_INDEX_TITLE_MATCHED",
                    evidence_type="title_match",
                    detail=f"元典案例验证通过: {official_title[:50]}, 得分 {score:.2f}",
                    title_match=True,
                )
            else:
                return self._make_evidence(
                    status="CASE_INDEX_TITLE_MISMATCH",
                    evidence_type="title_mismatch",
                    detail=f"标题不匹配: 本地={record.title[:30]} vs 元典={official_title[:30]}",
                    title_match=False,
                )

        except Exception as e:
            logger.error(f"[P4] 元典核验失败: {e}")
            self._last_call_time = time.time()
            return None

    def _compare_titles(self, local_title: str, official_title: str) -> bool:
        """比对案例标题。"""
        if not local_title or not official_title:
            return False

        def _norm(t):
            t = t.strip()
            t = re.sub(r"\s+", "", t)
            # 去除常见后缀
            for suffix in ["（参考性）", "（典型案例）", "（指导性案例）"]:
                t = t.replace(suffix, "")
            return t

        return _norm(local_title) == _norm(official_title)

    def verify_batch(
        self,
        records: list,
        checkpoint,
        stats,
    ) -> list:
        """批量核验案例文件。"""
        logger.info(f"[P4] 开始案例多渠道核验，共 {len(records)} 份文件")

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
                logger.error(f"[P4] 核验失败 {rec.local_path}: {e}")
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
                verified = sum(1 for e in evidences if "VERIFIED" in e.status)
                logger.info(
                    f"[P4] 进度: {i+1}/{len(records)} | "
                    f"通过: {verified}"
                )

        return evidences
