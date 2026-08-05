"""
P0 本地版本链互校
==================
识别同标题多日期的文件组，比对正文差异，
确认版本链关系（哪个版本废止了哪个）。
零网络依赖，纯本地操作。
"""

import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from .base import BaseVerifier
from models import FileRecord, VerificationEvidence, VersionChain
import config
from normalizer import (
    extract_body_from_md, normalize_text, compute_difference_ratio
)

logger = logging.getLogger(__name__)


def _normalize_title(title: str) -> str:
    """规范化标题，去除版本、日期、括号等信息，用于分组。"""
    t = title.strip()
    # 去除年份括号：（2021年）→ 空
    t = re.sub(r"[（(]\d{4}年[）)]", "", t)
    # 去除"修正""修订""修改"等版本词
    t = re.sub(r"[（(]?\d{4}年(?:修正|修订|修改)[）)]?", "", t)
    # 去除末尾日期
    t = re.sub(r"[_\-]\d{4}[-年]\d{1,2}[-月]?\d{1,2}[-日]?$", "", t)
    # 去除WJBS编码
    t = re.sub(r"[_\-]1\.2\.156\.\d+\.\d+.*$", "", t)
    # 去除状态词
    t = re.sub(r"[_\-](有效|已废止|已修改|尚未施行|已失效)$", "", t)
    return t.strip()


def _extract_date_from_path(local_path: str) -> str:
    """从文件名或路径提取日期。"""
    # 尝试匹配 YYYY-MM-DD 或 YYYYMMDD
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", local_path)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"_(\d{4})(\d{2})(\d{2})", local_path)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


def build_version_chains(records: List[FileRecord]) -> List[VersionChain]:
    """将文件列表按规范化标题分组，构建版本链。"""
    groups: Dict[str, List[FileRecord]] = defaultdict(list)

    for rec in records:
        norm_title = _normalize_title(rec.title) if rec.title else ""
        if not norm_title:
            norm_title = _normalize_title(rec.file_name.replace(".md", ""))

        if norm_title and len(norm_title) >= 3:
            groups[norm_title].append(rec)

    chains = []
    for norm_title, group in groups.items():
        if len(group) >= config.VERSION_CHAIN_MIN_SIZE:
            chain = VersionChain(
                normalized_title=norm_title,
                files=group,
            )
            chains.append(chain)

    return chains


class LocalCrossVerifier(BaseVerifier):
    """P0 本地版本链互校核验器。"""

    channel = "local_cross"
    priority = 0

    def verify(self, record: FileRecord) -> VerificationEvidence:
        """
        单文件核验（在批量模式下由 verify_batch 统一处理）。
        单独调用时返回 PENDING 状态。
        """
        return self._make_evidence(
            status="LOCAL_CROSS_PENDING",
            evidence_type="single_file",
            detail="本地互校需要在批量模式下与同标题文件比对",
        )

    def verify_batch(
        self,
        records: List[FileRecord],
        checkpoint,
        stats,
    ) -> List[VerificationEvidence]:
        """
        批量核验：构建版本链，逐链比对。
        覆写基类的串行默认实现。
        """
        logger.info(f"[P0] 开始本地版本链互校，共 {len(records)} 份文件")

        # 1. 构建版本链
        chains = build_version_chains(records)
        logger.info(f"[P0] 识别到 {len(chains)} 条版本链")

        evidences = []
        single_files = []  # 无版本链的独立文件

        # 2. 处理版本链
        for chain in chains:
            chain_evidences = self._verify_chain(chain, checkpoint, stats)
            evidences.extend(chain_evidences)

        # 3. 处理独立文件（无版本链）
        chained_paths = set()
        for chain in chains:
            for f in chain.files:
                chained_paths.add(f.local_path)

        for rec in records:
            if rec.local_path not in chained_paths:
                if not checkpoint.is_processed_in_phase(rec.local_path, self.channel):
                    ev = self._verify_single(rec)
                    evidences.append(ev)
                    checkpoint.add_result(rec.local_path, ev)
                    stats.processed += 1
                    self._update_stats(stats, ev)
                    single_files.append(rec)

        logger.info(f"[P0] 完成：{len(chains)} 条版本链，{len(single_files)} 个独立文件")
        return evidences

    def _verify_chain(
        self,
        chain: VersionChain,
        checkpoint,
        stats,
    ) -> List[VerificationEvidence]:
        """对一条版本链内的所有文件进行互校。"""
        evidences = []
        sorted_files = chain.sorted_by_date()

        # 对每对相邻版本比对
        for i in range(len(sorted_files)):
            rec = sorted_files[i]

            if checkpoint.is_processed_in_phase(rec.local_path, self.channel):
                continue

            # 读取本地正文
            file_path = self._resolve_file_path(rec)
            try:
                local_body = extract_body_from_md(file_path)
                local_norm = normalize_text(local_body)
            except Exception as e:
                ev = self._make_evidence(
                    status="ERROR",
                    evidence_type="read_error",
                    detail=f"无法读取文件: {e}",
                )
                evidences.append(ev)
                checkpoint.add_result(rec.local_path, ev)
                stats.processed += 1
                stats.errors += 1
                continue

            # 与前一版本比对差异
            if i > 0:
                prev_rec = sorted_files[i - 1]
                prev_file = self._resolve_file_path(prev_rec)
                try:
                    prev_body = extract_body_from_md(prev_file)
                    prev_norm = normalize_text(prev_body)
                    diff_ratio = compute_difference_ratio(local_norm, prev_norm)

                    if diff_ratio < 0.01:
                        # 几乎完全相同 → 可能是重复文件
                        ev = self._make_evidence(
                            status="LOCAL_CROSS_DUPLICATE",
                            evidence_type="near_identical",
                            detail=f"与前一版本差异率 {diff_ratio:.4f}，疑似重复",
                            difference_ratio=diff_ratio,
                        )
                    elif diff_ratio > 0.8:
                        # 差异很大 → 可能是不同法规同标题
                        ev = self._make_evidence(
                            status="LOCAL_CROSS_DIFFERENT",
                            evidence_type="large_difference",
                            detail=f"与前一版本差异率 {diff_ratio:.4f}，可能为不同法规",
                            difference_ratio=diff_ratio,
                        )
                    else:
                        # 有实质差异 → 版本更新
                        ev = self._make_evidence(
                            status="LOCAL_CROSS_VERSION_CHAIN",
                            evidence_type="version_update",
                            detail=f"版本更新，差异率 {diff_ratio:.4f}",
                            difference_ratio=diff_ratio,
                        )
                except Exception:
                    ev = self._make_evidence(
                        status="LOCAL_CROSS_SINGLE",
                        evidence_type="chain_member",
                        detail=f"版本链第 {i+1}/{len(sorted_files)} 件",
                    )
            else:
                # 第一个版本
                ev = self._make_evidence(
                    status="LOCAL_CROSS_CHAIN_HEAD",
                    evidence_type="chain_head",
                    detail=f"版本链首件，共 {len(sorted_files)} 个版本",
                )

            evidences.append(ev)
            checkpoint.add_result(rec.local_path, ev)
            stats.processed += 1
            self._update_stats(stats, ev)

        # 记录版本链信息
        chain.chain_verified = True
        chain.chain_notes = (
            f"共 {len(sorted_files)} 个版本，"
            f"日期范围 {sorted_files[0].publication_date or '?'} ~ "
            f"{sorted_files[-1].publication_date or '?'}"
        )

        # 保存到检查点
        if checkpoint:
            checkpoint.version_chains.append({
                "normalized_title": chain.normalized_title,
                "count": chain.count,
                "chain_verified": chain.chain_verified,
                "chain_notes": chain.chain_notes,
                "files": [f.local_path for f in sorted_files],
            })

        return evidences

    def _verify_single(self, rec: FileRecord) -> VerificationEvidence:
        """对无版本链的独立文件进行核验。"""
        file_path = self._resolve_file_path(rec)
        try:
            local_body = extract_body_from_md(file_path)
            local_norm = normalize_text(local_body)
            char_count = len(local_norm)

            if char_count < 10:
                return self._make_evidence(
                    status="LOCAL_CROSS_EMPTY",
                    evidence_type="empty_content",
                    detail="文件内容过短",
                )

            return self._make_evidence(
                status="LOCAL_CROSS_SINGLE",
                evidence_type="no_version_chain",
                detail=f"独立文件，无同标题版本，字符数 {char_count}",
            )
        except Exception as e:
            return self._make_evidence(
                status="ERROR",
                evidence_type="read_error",
                detail=str(e),
            )
