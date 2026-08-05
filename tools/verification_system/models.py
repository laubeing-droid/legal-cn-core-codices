"""
数据模型 - 文件记录、核验结果、证据链
======================================
Immutable-friendly dataclasses for the verification pipeline.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Dict, List, Any


@dataclass
class FileRecord:
    """单个法规文件的完整元数据"""
    # 文件标识
    local_path: str                    # 相对路径
    local_sha256: str                  # 本地文件SHA-256

    # Front Matter 提取
    title: str = ""
    doc_number: str = ""
    issuing_body: str = ""
    publication_date: str = ""

    # 来源信息
    source_domain: str = ""
    source_type: str = ""
    official_url: str = ""

    # 状态
    current_verification_status: str = "UNKNOWN"
    new_verification_status: str = ""

    # 全文核验证据
    fulltext_hash: str = ""            # 本地正文规范化哈希
    comparison_result: str = ""
    note: str = ""

    # 内部索引
    _record_id: str = ""  # local_path的slug，用于快速查找

    @property
    def has_url(self) -> bool:
        return bool(self.official_url and self.official_url.startswith("http"))

    @property
    def dir_name(self) -> str:
        """提取一级目录名"""
        parts = self.local_path.replace("\\", "/").split("/")
        return parts[0] if parts else ""

    @property
    def file_name(self) -> str:
        """提取文件名"""
        parts = self.local_path.replace("\\", "/").split("/")
        return parts[-1] if parts else ""

    @classmethod
    def from_checkpoint(cls, record: dict) -> "FileRecord":
        return cls(
            local_path=record.get("local_path", ""),
            local_sha256=record.get("local_sha256", ""),
            title=record.get("title", ""),
            doc_number=record.get("doc_number", ""),
            issuing_body=record.get("issuing_body", ""),
            publication_date=record.get("publication_date", ""),
            source_domain=record.get("source_domain", ""),
            source_type=record.get("source_type", ""),
            official_url=record.get("official_url", ""),
            current_verification_status=record.get("current_verification_status", ""),
            new_verification_status=record.get("new_verification_status", ""),
            fulltext_hash=record.get("fulltext_hash", ""),
            comparison_result=record.get("comparison_result", ""),
            note=record.get("note", ""),
            _record_id=record.get("local_path", ""),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def to_csv_row(self) -> dict:
        return {
            "local_path": self.local_path,
            "local_sha256": self.local_sha256,
            "title": self.title,
            "doc_number": self.doc_number,
            "issuing_body": self.issuing_body,
            "publication_date": self.publication_date,
            "source_domain": self.source_domain,
            "official_url": self.official_url,
            "verified_status": self.new_verification_status or self.current_verification_status,
            "fulltext_hash": self.fulltext_hash,
            "comparison_result": self.comparison_result,
            "note": self.note,
        }


@dataclass
class VerificationEvidence:
    """单次核验的证据记录"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    channel: str = ""                  # local_cross / yuandian / url_check / local_gov / wechat_case
    status: str = ""                   # 该渠道的判定
    evidence_type: str = ""            # byte_identical / normalized_match / url_reachable / manual_review
    source_role: str = ""               # AUTHORITY_ORIGIN / OFFICIAL_CANONICAL_DATABASE / OFFICIAL_REPUBLICATION / THIRD_PARTY_CARRIER
    source_url: str = ""
    stable_id: str = ""
    official_version_token: str = ""
    attachment_fingerprint: str = ""
    official_hash: Optional[str] = None
    local_sha256: Optional[str] = None
    normalized_official_hash: Optional[str] = None
    local_normalized_hash: Optional[str] = None
    comparison_result: str = ""
    representation_completeness: str = ""
    editorial_block_status: str = ""
    index_status: str = ""
    source_run_status: str = ""
    legal_effect: str = ""
    title_match: Optional[bool] = None
    url_reachable: Optional[bool] = None
    http_status: Optional[int] = None
    page_title: Optional[str] = None
    difference_ratio: Optional[float] = None
    detail: str = ""
    error: str = ""


@dataclass
class VersionChain:
    """同标题多日期文件的版本链"""
    normalized_title: str              # 规范化标题（去除日期和版本信息）
    files: List[FileRecord] = field(default_factory=list)
    chain_verified: bool = False
    chain_notes: str = ""

    @property
    def count(self) -> int:
        return len(self.files)

    def sorted_by_date(self) -> list:
        """按日期排序"""
        return sorted(self.files, key=lambda f: f.publication_date or "")


@dataclass
class ProgressStats:
    """进度统计"""
    total: int = 0
    processed: int = 0
    by_channel: Dict[str, int] = field(default_factory=dict)
    by_status: Dict[str, int] = field(default_factory=dict)
    errors: int = 0
    url_reachable: int = 0
    url_unreachable: int = 0
    byte_identical: int = 0
    normalized_equivalent: int = 0
    needs_manual_review: int = 0
    elapsed_seconds: float = 0.0

    def summary(self) -> str:
        pct = (self.processed / self.total * 100) if self.total else 0
        m, s = divmod(int(self.elapsed_seconds), 60)
        h, m = divmod(m, 60)
        time_str = f"{h}h{m}m{s}s" if h else f"{m}m{s}s"

        lines = [
            f"进度: {self.processed}/{self.total} ({pct:.1f}%) | 耗时: {time_str}",
            f"渠道分布: {self.by_channel}",
            f"状态分布: {self.by_status}",
            f"字节一致: {self.byte_identical} | 规范化一致: {self.normalized_equivalent}",
            f"URL可达: {self.url_reachable} | 不可达: {self.url_unreachable}",
            f"异常: {self.errors} | 待人工复核: {self.needs_manual_review}",
        ]
        return "\n".join(lines)


@dataclass
class BatchCheckpoint:
    """断点续跑检查点"""
    batch_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    processed_paths: set = field(default_factory=set)
    results: Dict[str, List["VerificationEvidence"]] = field(default_factory=dict)
    version_chains: List[dict] = field(default_factory=list)
    stats: ProgressStats = field(default_factory=ProgressStats)
    current_phase: str = ""  # local_cross / yuandian / url_check / local_gov / wechat_case
    current_offset: int = 0

    def add_result(self, local_path: str, evidence: "VerificationEvidence"):
        self.processed_paths.add(local_path)
        self.results.setdefault(local_path, []).append(evidence)
        self.updated_at = datetime.now().isoformat()

    def is_processed(self, local_path: str) -> bool:
        return local_path in self.processed_paths

    def is_processed_in_phase(self, local_path: str, phase: str) -> bool:
        """检查文件是否在指定阶段已处理。"""
        if local_path not in self.results:
            return False
        return any(event.channel == phase for event in self.results[local_path])

    def processed_count(self) -> int:
        return len(self.processed_paths)
