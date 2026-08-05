"""
多源调度协调器
================
按优先级调度不同核验渠道，管理整体进度。
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from models import FileRecord, BatchCheckpoint, ProgressStats
from checkpoint import save_checkpoint, load_checkpoint, export_final_results
import config

logger = logging.getLogger(__name__)


class VerificationScheduler:
    """核验调度器：按P0→P4优先级调度渠道。"""

    def __init__(self, mcp_caller=None):
        self.mcp_caller = mcp_caller
        self.checkpoint: Optional[BatchCheckpoint] = None
        self.records: List[FileRecord] = []
        self.stats = ProgressStats()
        self._start_time = 0.0

    def load_input(self):
        """加载检查点输入和已有核验记录。"""
        # 加载批量检查点（37,564份文件的元数据）
        if config.CHECKPOINT_INPUT.exists():
            logger.info(f"加载输入检查点: {config.CHECKPOINT_INPUT}")
            with open(config.CHECKPOINT_INPUT, "r", encoding="utf-8") as f:
                data = json.load(f)

            for rec_dict in data.get("results", []):
                record = FileRecord.from_checkpoint(rec_dict)
                self.records.append(record)

            logger.info(f"加载了 {len(self.records)} 份文件记录")
        else:
            logger.error(f"输入检查点不存在: {config.CHECKPOINT_INPUT}")

        # 加载系统检查点（断点续跑）
        self.checkpoint = load_checkpoint()
        logger.info(
            f"系统检查点: 已处理 {self.checkpoint.processed_count()} 份"
        )

        # 统计总数
        self.stats.total = len(self.records)

    def run(self, phases: Optional[List[str]] = None):
        """
        执行核验流程。

        Args:
            phases: 指定要执行的阶段列表，None 表示全部
        """
        self._start_time = time.time()

        # 如果记录未加载，才加载
        if not self.records:
            self.load_input()

        if not self.records:
            logger.error("无文件可处理")
            return

        # 确定要执行的阶段
        all_phases = ["local_cross", "yuandian", "url_check", "local_gov", "wechat_case"]
        if phases:
            phases_to_run = [p for p in all_phases if p in phases]
        else:
            phases_to_run = all_phases

        logger.info(f"计划执行阶段: {phases_to_run}")

        for phase in phases_to_run:
            self._run_phase(phase)

        # 导出最终结果
        self._finalize()

    def _run_phase(self, phase: str):
        """执行单个阶段。"""
        logger.info(f"\n{'='*60}")
        logger.info(f"开始阶段: {phase}")
        logger.info(f"{'='*60}")

        self.checkpoint.current_phase = phase
        self.checkpoint.current_offset = 0

        # 筛选该阶段适用的文件
        applicable = self._filter_records_for_phase(phase)
        logger.info(f"阶段 {phase} 适用文件: {len(applicable)} 份")

        # 创建核验器
        verifier = self._create_verifier(phase)
        if verifier is None:
            logger.warning(f"无法创建核验器: {phase}，跳过")
            return

        # 执行批量核验
        batch_stats = ProgressStats(total=len(applicable))
        evidences = verifier.verify_batch(
            applicable, self.checkpoint, batch_stats
        )

        # 合并统计
        for k, v in batch_stats.by_channel.items():
            self.stats.by_channel[k] = self.stats.by_channel.get(k, 0) + v
        for k, v in batch_stats.by_status.items():
            self.stats.by_status[k] = self.stats.by_status.get(k, 0) + v
        self.stats.processed += batch_stats.processed
        self.stats.errors += batch_stats.errors

        # 保存检查点
        save_checkpoint(self.checkpoint)

        logger.info(f"阶段 {phase} 完成")
        logger.info(batch_stats.summary())

    def _filter_records_for_phase(self, phase: str) -> List[FileRecord]:
        """筛选该阶段适用的文件。"""
        applicable = []

        for rec in self.records:
            # 检查该文件是否已在当前阶段处理过
            if self.checkpoint.is_processed_in_phase(rec.local_path, phase):
                continue

            # 按渠道适用性筛选
            dir_name = rec.dir_name
            has_url = rec.has_url

            if phase == "local_cross":
                applicable.append(rec)
            elif phase == "yuandian":
                if any(dir_name.startswith(d) for d in config.LEGAL_DOC_DIRS):
                    applicable.append(rec)
            elif phase == "url_check":
                if has_url:
                    applicable.append(rec)
            elif phase == "local_gov":
                if any(dir_name.startswith(d) for d in ["05_地方立法", "06_规章"]):
                    applicable.append(rec)
            elif phase == "wechat_case":
                if any(dir_name.startswith(d) for d in config.CASE_DIRS):
                    applicable.append(rec)

        return applicable

    def _create_verifier(self, phase: str):
        """创建核验器实例。"""
        if phase == "local_cross":
            from verifiers.local_cross import LocalCrossVerifier
            return LocalCrossVerifier()
        elif phase == "yuandian":
            from verifiers.yuandian import YuandianVerifier
            return YuandianVerifier(mcp_caller=self.mcp_caller)
        elif phase == "url_check":
            from verifiers.url_check import URLCheckVerifier
            return URLCheckVerifier()
        elif phase == "local_gov":
            from verifiers.local_gov import LocalGovVerifier
            return LocalGovVerifier()
        elif phase == "wechat_case":
            from verifiers.wechat_case import WechatCaseVerifier
            return WechatCaseVerifier()
        else:
            return None

    def _finalize(self):
        """完成所有阶段后，导出结果。"""
        self.stats.elapsed_seconds = time.time() - self._start_time

        # 导出CSV
        csv_path = export_final_results(self.checkpoint, self.records)
        logger.info(f"结果已导出: {csv_path}")

        # 导出报告
        self._export_report()

        # 保存最终检查点
        save_checkpoint(self.checkpoint)

        logger.info("\n" + "="*60)
        logger.info("全部阶段完成")
        logger.info(self.stats.summary())
        logger.info("="*60)

    def _export_report(self):
        """导出Markdown进度报告。"""
        report_lines = [
            "# 法律法规库多源核验报告",
            f"",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**批处理ID**: {self.checkpoint.batch_id}",
            f"",
            f"## 总体进度",
            f"",
            f"| 指标 | 值 |",
            f"|------|-----|",
            f"| 总文件数 | {self.stats.total} |",
            f"| 已处理 | {self.stats.processed} |",
            f"| 耗时 | {self._format_time(self.stats.elapsed_seconds)} |",
            f"| 错误数 | {self.stats.errors} |",
            f"",
            f"## 渠道分布",
            f"",
        ]

        for channel, count in sorted(self.stats.by_channel.items()):
            report_lines.append(f"- **{channel}**: {count}")

        report_lines.extend([
            f"",
            f"## 状态分布",
            f"",
        ])

        for status, count in sorted(
            self.stats.by_status.items(),
            key=lambda x: -x[1]
        ):
            report_lines.append(f"- **{status}**: {count}")

        report_lines.extend([
            f"",
            f"## 已识别版本链",
            f"",
            f"共识别 {len(self.checkpoint.version_chains)} 条版本链",
        ])

        for i, chain in enumerate(self.checkpoint.version_chains[:10], 1):
            report_lines.append(
                f"- {i}. {chain.get('normalized_title', '?')} "
                f"({chain.get('count', 0)} 个版本)"
            )

        report_text = "\n".join(report_lines)
        config.REPORT_MD.write_text(report_text, encoding="utf-8")
        logger.info(f"报告已导出: {config.REPORT_MD}")

    @staticmethod
    def _format_time(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}h{m}m{s}s"
        return f"{m}m{s}s"
