"""
法律法规库多源核验系统 - 全局配置
=====================================
管理所有路径、阈值、限流参数和渠道优先级。
"""

import os
from pathlib import Path

# ========================
# 路径配置
# ========================

# 法律库根目录
LEGAL_CORE_ROOT = Path("D:/legal-cn-core-codices")

# 工程记录根目录
ENGINEERING_ROOT = Path("D:/legal-references")

# 本系统根目录
SYSTEM_ROOT = Path(__file__).parent

# 输入文件
CHECKPOINT_INPUT = Path(
    "D:/legal-references/90_项目任务记录/全文全量核对_20260731_221821/"
    "checkpoints/batch_checkpoint.json"
)
CSV_INPUT = Path(
    "D:/legal-references/90_项目任务记录/本地CSV数据集_20260730/"
    "工程记录/verification_results.csv"
)

# 输出目录
OUTPUT_DIR = SYSTEM_ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CHECKPOINT_DIR = SYSTEM_ROOT / "checkpoints"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

RESULTS_CSV = OUTPUT_DIR / "fulltext_verification_results.csv"
CHECKPOINT_FILE = CHECKPOINT_DIR / "verification_checkpoint.json"
REPORT_MD = OUTPUT_DIR / "verification_report.md"
LOG_FILE = OUTPUT_DIR / "verification.log"

# ========================
# 目标目录（14个）
# ========================

TARGET_DIRS = [
    "01_宪法",
    "02_法律",
    "03_行政法规",
    "04_监察法规",
    "05_地方立法",
    "06_规章",
    "07_司法解释【独立规范类型】",
    "08_其他规范性文件【非立法】",
    "09_司法机关其他规范性文件【非司法解释】",
    "10_司法业务指导、会议纪要与公开答疑【非规范性法源】",
    "80_司法部仲裁案例【参考性、非规范性法源】",
    "81_最高人民法院公开案例【非规范性法源】",
    "82_最高人民检察院公开案例【非规范性法源】",
]

# 法律法规类目录（适用元典核验）
LEGAL_DOC_DIRS = [
    "01_宪法", "02_法律", "03_行政法规", "04_监察法规",
    "05_地方立法", "06_规章",
]

# 案例类目录（适用元典案例+微信核验）
CASE_DIRS = [
    "80_司法部仲裁案例【参考性、非规范性法源】",
    "81_最高人民法院公开案例【非规范性法源】",
    "82_最高人民检察院公开案例【非规范性法源】",
]

# ========================
# 核验终态枚举
# ========================

class VerificationStatus:
    """核验终态常量"""
    # 字节一致
    BYTE_IDENTICAL = "OFFICIAL_FULLTEXT_BYTE_IDENTICAL"
    # 规范化一致
    NORMALIZED_EQUIVALENT = "OFFICIAL_FULLTEXT_NORMALIZED_EQUIVALENT"
    # 本地是超集
    LOCAL_SUPERSET = "OFFICIAL_FULLTEXT_LOCAL_SUPERSET"
    # 官方是超集
    OFFICIAL_SUPERSET = "OFFICIAL_FULLTEXT_OFFICIAL_SUPERSET"
    # 版本不匹配
    VERSION_MISMATCH = "OFFICIAL_FULLTEXT_VERSION_MISMATCH"
    # 官方全文不完整
    PARTIAL = "OFFICIAL_FULLTEXT_PARTIAL"
    # 多源冲突
    CONFLICT = "OFFICIAL_FULLTEXT_CONFLICT"
    # 访问受阻
    BLOCKED_ACCESS = "OFFICIAL_FULLTEXT_BLOCKED_ACCESS"
    # 未找到
    NOT_FOUND = "OFFICIAL_FULLTEXT_NOT_FOUND"
    # 需人工复核
    MANUAL_REVIEW = "MANUAL_REVIEW_REQUIRED"
    # 等待元数据（URL为空等）
    PENDING_URL = "PENDING_OFFICIAL_URL"
    # 仅本地互校完成
    LOCAL_CROSS_VERIFIED = "LOCAL_CROSS_VERIFIED"
    # URL已验证待全文
    URL_VERIFIED_PENDING_FULLTEXT = "URL_VERIFIED_PENDING_FULLTEXT"
    SOURCE_URL_REACHABLE = "SOURCE_URL_REACHABLE"
    CONTENT_NOT_VERIFIED = "CONTENT_NOT_VERIFIED"

    # 优先级排序（用于统计）
    PRIORITY = {
        BYTE_IDENTICAL: 1,
        NORMALIZED_EQUIVALENT: 2,
        LOCAL_SUPERSET: 3,
        OFFICIAL_SUPERSET: 4,
        VERSION_MISMATCH: 10,
        PARTIAL: 11,
        CONFLICT: 12,
        BLOCKED_ACCESS: 13,
        NOT_FOUND: 14,
        LOCAL_CROSS_VERIFIED: 20,
        URL_VERIFIED_PENDING_FULLTEXT: 30,
        SOURCE_URL_REACHABLE: 31,
        CONTENT_NOT_VERIFIED: 32,
        MANUAL_REVIEW: 50,
        PENDING_URL: 100,
    }


# ========================
# 核验渠道优先级
# ========================

CHANNEL_PRIORITY = {
    "local_cross": 0,    # P0 - 本地互校（零网络依赖）
    "yuandian": 1,       # P1 - 元典MCP核验
    "url_check": 2,      # P2 - URL有效性检查
    "local_gov": 3,      # P3 - 地方政府网站
    "wechat_case": 4,    # P4 - 微信公众号+元典案例
}

# 每个渠道适用的目录
CHANNEL_DIRS = {
    "local_cross": None,          # 所有目录
    "yuandian": LEGAL_DOC_DIRS,   # 仅法律法规类
    "url_check": None,            # 所有有URL的
    "local_gov": ["05_地方立法", "06_规章"],
    "wechat_case": CASE_DIRS,     # 仅案例类
}

# ========================
# 批处理与限流
# ========================

# 每N个文件保存一次检查点
CHECKPOINT_INTERVAL = 500

# 每N个文件输出进度
PROGRESS_INTERVAL = 500

# HTTP请求最小间隔（秒）
HTTP_MIN_INTERVAL = 2.0

# HTTP请求超时（秒）
HTTP_TIMEOUT = 30

# 最大重试次数
MAX_RETRIES = 3

# 重试退避基数（秒）
RETRY_BACKOFF = 2.0

# 元典API请求间隔
YUANDIAN_MIN_INTERVAL = 1.5

# 并发数（元典MCP建议串行）
YUANDIAN_CONCURRENCY = 1

# ========================
# 版本链检测
# ========================

# 同标题文件的最小分组大小
VERSION_CHAIN_MIN_SIZE = 2

# 同标题文件的日期差异阈值（天）
VERSION_CHAIN_MAX_DATE_DIFF = 36500  # 约100年

# ========================
# 规范化配置
# ========================


# 规范化选项
NORMALIZATION_OPTIONS = {
    "strip_whitespace": True,
    "normalize_newlines": True,
    "collapse_whitespace": True,
    "remove_bom": True,
    "normalize_fullwidth": True,
    "remove_front_matter": True,
    "strip_trailing_blank_lines": True,
}


def get_channel_for_file(dir_name: str, has_url: bool) -> list:
    """
    判定单个文件适用的核验渠道。
    返回按优先级排序的渠道列表。
    """
    channels = []

    # P0: 本地互校对所有文件适用（由调度器批量处理）
    channels.append("local_cross")

    # P1: 元典仅适用法律法规目录
    if any(dir_name.startswith(d) for d in LEGAL_DOC_DIRS):
        channels.append("yuandian")

    # P2: URL检查对有URL的文件适用
    if has_url:
        channels.append("url_check")

    # P3: 地方政府仅适用地方立法和规章
    if any(dir_name.startswith(d) for d in ["05_地方立法", "06_规章"]):
        channels.append("local_gov")

    # P4: 案例核验适用案例目录
    if any(dir_name.startswith(d) for d in CASE_DIRS):
        channels.append("wechat_case")

    # 按优先级排序
    channels.sort(key=lambda c: CHANNEL_PRIORITY.get(c, 99))
    return channels
