"""
核验基类
==========
定义核验器的统一接口、辅助方法和证据记录规范。
"""

import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional

import config
from models import FileRecord, VerificationEvidence, ProgressStats

logger = logging.getLogger(__name__)


class BaseVerifier(ABC):
    """核验器抽象基类。

    约定：
    - 每个子类实现 verify(record) → VerificationEvidence
    - verify_batch(records) 提供默认的批量串行实现
    - 子类可覆写 verify_batch 实现批优化（如本地互校的全量分组）
    """

    channel: str = ""        # 子类必须覆写
    priority: int = 99       # 子类必须覆写

    def __init__(self, legal_core_root: Optional[Path] = None):
        self.legal_core_root = legal_core_root or config.LEGAL_CORE_ROOT

    @abstractmethod
    def verify(self, record: FileRecord) -> VerificationEvidence:
        """对单个文件执行核验。"""
        ...

    def verify_batch(
        self,
        records: list,
        checkpoint,
        stats: ProgressStats
    ) -> list:
        """
        批量核验默认实现（串行）。
        返回 VerificationEvidence 列表。
        """
        evidences = []
        processed_in_batch = 0
        total = len(records)
        for i, rec in enumerate(records):
            # 检查是否已在当前渠道处理过
            if checkpoint and checkpoint.is_processed_in_phase(rec.local_path, self.channel):
                continue

            try:
                evidence = self.verify(rec)
                evidences.append(evidence)
                checkpoint.add_result(rec.local_path, evidence)

                # 更新统计
                stats.processed += 1
                self._update_stats(stats, evidence)
                processed_in_batch += 1

            except Exception as e:
                logger.error(f"核验失败 [{self.channel}] {rec.local_path}: {e}")
                evidence = VerificationEvidence(
                    timestamp=datetime.now().isoformat(),
                    channel=self.channel,
                    status="ERROR",
                    error=str(e),
                )
                evidences.append(evidence)
                checkpoint.add_result(rec.local_path, evidence)
                stats.errors += 1
                stats.processed += 1
                processed_in_batch += 1

            # 进度日志（每100个文件输出一次）
            if processed_in_batch % 100 == 0:
                logger.info(
                    f"[{self.channel}] 进度: {processed_in_batch}/{total} "
                    f"({processed_in_batch/total*100:.1f}%)"
                )

            # 限流
            if self._get_min_interval() > 0:
                time.sleep(self._get_min_interval())

        # 输出最终进度
        if processed_in_batch > 0:
            logger.info(
                f"[{self.channel}] 本批处理完成: {processed_in_batch}/{total} "
                f"({processed_in_batch/total*100:.1f}%)"
            )

        return evidences

    def _get_min_interval(self) -> float:
        """最小请求间隔（秒）。"""
        return 0.0

    def _update_stats(self, stats: ProgressStats, evidence: VerificationEvidence):
        """更新统计计数。"""
        stats.by_channel[self.channel] = \
            stats.by_channel.get(self.channel, 0) + 1
        stats.by_status[evidence.status] = \
            stats.by_status.get(evidence.status, 0) + 1

        # 更新特定计数器
        if evidence.status == "SOURCE_URL_REACHABLE":
            stats.url_reachable += 1
        elif evidence.status in ("URL_NOT_FOUND", "URL_BLOCKED", "URL_ERROR"):
            stats.url_unreachable += 1

        if "BYTE_IDENTICAL" in evidence.status:
            stats.byte_identical += 1
        elif "NORMALIZED_EQUIVALENT" in evidence.status:
            stats.normalized_equivalent += 1

        if evidence.status == "MANUAL_REVIEW_REQUIRED":
            stats.needs_manual_review += 1

    def _make_evidence(
        self,
        status: str,
        evidence_type: str = "",
        detail: str = "",
        error: str = "",
        **kwargs
    ) -> VerificationEvidence:
        """快速构造证据记录。"""
        return VerificationEvidence(
            timestamp=datetime.now().isoformat(),
            channel=self.channel,
            status=status,
            evidence_type=evidence_type,
            detail=detail,
            error=error,
            **kwargs,
        )

    def _resolve_file_path(self, record: FileRecord) -> Path:
        """将相对路径解析为完整文件系统路径。"""
        return self.legal_core_root / record.local_path

    @staticmethod
    def extract_dir_prefix(local_path: str) -> str:
        """从相对路径提取一级目录名。"""
        parts = local_path.replace("\\", "/").split("/")
        return parts[0] if parts else ""
