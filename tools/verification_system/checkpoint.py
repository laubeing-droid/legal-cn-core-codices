"""
检查点管理 - 持久化、恢复、增量写入
=======================================
支持断点续跑的检查点机制，记录每份文件的核验进度和中间结果。
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import config
from models import BatchCheckpoint, ProgressStats, FileRecord


def save_checkpoint(checkpoint: BatchCheckpoint, path: Optional[Path] = None):
    """将检查点持久化到磁盘。

    采用原子写入策略：先写入临时文件，再rename。
    """
    output_path = path or config.CHECKPOINT_FILE
    tmp_path = output_path.with_suffix(".tmp")

    # 序列化时处理 set 类型
    data = {
        "batch_id": checkpoint.batch_id,
        "created_at": checkpoint.created_at,
        "updated_at": checkpoint.updated_at,
        "processed_count": checkpoint.processed_count(),
        "processed_paths": sorted(list(checkpoint.processed_paths)),
        "results": {
            k: [_evidence_to_dict(event) for event in events]
            for k, events in checkpoint.results.items()
        },
        "version_chains": checkpoint.version_chains,
        "stats": _stats_to_dict(checkpoint.stats),
        "current_phase": checkpoint.current_phase,
        "current_offset": checkpoint.current_offset,
    }

    os.makedirs(output_path.parent, exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, output_path)


def load_checkpoint(path: Optional[Path] = None) -> BatchCheckpoint:
    """从磁盘加载检查点；不存在则返回空检查点。"""
    input_path = path or config.CHECKPOINT_FILE

    if not input_path.exists():
        return BatchCheckpoint(
            batch_id=f"verify_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    checkpoint = BatchCheckpoint(
        batch_id=data.get("batch_id", ""),
        created_at=data.get("created_at", datetime.now().isoformat()),
        updated_at=data.get("updated_at", datetime.now().isoformat()),
        processed_paths=set(data.get("processed_paths", [])),
        version_chains=data.get("version_chains", []),
        stats=_dict_to_stats(data.get("stats", {})),
        current_phase=data.get("current_phase", ""),
        current_offset=data.get("current_offset", 0),
    )

    # 恢复results - 需要从字典重建为对象
    from models import VerificationEvidence
    for path_str, event_payload in data.get("results", {}).items():
        # v1检查点是path->单事件；v2是path->事件列表。
        event_dicts = event_payload if isinstance(event_payload, list) else [event_payload]
        checkpoint.results[path_str] = [
            _dict_to_evidence(event_dict) for event_dict in event_dicts
        ]

    return checkpoint


def export_final_results(checkpoint: BatchCheckpoint, records: list, output_csv: Optional[Path] = None):
    """将所有FileRecord的最新核验状态导出为CSV。

    合并checkpoint中的channel证据到FileRecord的终态判定。
    """
    import csv

    output_path = output_csv or config.RESULTS_CSV
    os.makedirs(output_path.parent, exist_ok=True)

    fieldnames = [
        "local_path", "local_sha256", "title", "doc_number",
        "issuing_body", "publication_date", "source_domain",
        "official_url", "verified_status", "fulltext_hash",
        "comparison_result", "verification_evidence", "note",
    ]

    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for rec in records:
            row = rec.to_csv_row()

            # 附上各渠道证据摘要
            evidence_lines = []
            if rec.local_path in checkpoint.results:
                for event in checkpoint.results[rec.local_path]:
                    evidence_lines.append(
                        f"[{event.channel}] {event.status} | {event.evidence_type}"
                    )
                    if event.detail:
                        evidence_lines.append(f"  detail: {event.detail}")
                    if event.error:
                        evidence_lines.append(f"  error: {event.error}")

            row["verification_evidence"] = " | ".join(evidence_lines) if evidence_lines else ""
            writer.writerow(row)

    return output_path


# === 内部辅助 ===

def _evidence_to_dict(ev) -> dict:
    """将VerificationEvidence序列化为dict。"""
    from dataclasses import asdict
    return asdict(ev)


def _dict_to_evidence(d: dict):
    """从dict恢复VerificationEvidence。"""
    from models import VerificationEvidence
    return VerificationEvidence(**d)


def _stats_to_dict(stats: ProgressStats) -> dict:
    from dataclasses import asdict
    return asdict(stats)


def _dict_to_stats(d: dict) -> ProgressStats:
    return ProgressStats(**d)
