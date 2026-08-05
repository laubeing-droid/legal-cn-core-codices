"""
正文规范化模块
==================
对法规正文进行标准化处理，消除格式差异，
支持字节级哈希比对和规范化哈希比对。
"""

import hashlib
import re
from pathlib import Path
from typing import Tuple, Optional


def calculate_sha256(file_path: Path) -> str:
    """计算文件原始字节SHA-256。"""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def calculate_normalized_sha256(file_path: Path) -> str:
    """读取文件并计算规范化后的SHA-256。"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw_text = f.read()
    except UnicodeDecodeError:
        return ""
    normalized = normalize_text(raw_text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def extract_body_from_md(file_path: Path) -> str:
    """从Markdown提取正文（去除Front Matter）。"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        return ""

    fm_match = re.match(r"^---\s*\n.*?\n---\s*\n", content, re.DOTALL)
    if fm_match:
        return content[fm_match.end():]
    return content


def normalize_text(text: str) -> str:
    """
    正文规范化处理。

    规范化步骤：
    1. 去除BOM
    2. 统一换行符 → LF
    3. 去除行尾空白
    4. 折叠连续空白（空格+制表符 → 单个空格）
    5. 半角化全角空格
    6. 去除连续的空白行（保留至多一行空白）
    7. 去除首尾空白
    """

    # 1. 去除BOM
    text = text.replace("\ufeff", "")

    # 2. 统一换行 → LF
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 3. 去除行尾空白
    text = "\n".join(line.rstrip() for line in text.split("\n"))

    # 4. 折叠连续空白（行内）
    text = re.sub(r"[ \t]+", " ", text)

    # 5. 全角空格 → 半角
    text = text.replace("\u3000", " ")

    # 6. 折叠连续空白行（最多保留一行空行）
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 7. 去除首尾空白
    text = text.strip()

    return text


def normalize_text_aggressive(text: str) -> str:
    """
    激进规范化：除基础规范化外，去除所有空白字符和标点。
    用于极端情况下的相似度判定。
    """
    text = normalize_text(text)
    # 去除所有空白
    text = re.sub(r"\s+", "", text)
    # 去除常见标点
    text = re.sub(r"[，。、；：？！「」『』（）【】《》\"'—…\-,\.;:!?()\[\]{}]", "", text)
    return text


def compute_difference_ratio(text_a: str, text_b: str) -> float:
    """
    计算两个正文的差异比率。
    返回 0.0（完全相同）到 1.0（完全不同）。
    """
    import difflib
    if not text_a and not text_b:
        return 0.0
    if not text_a or not text_b:
        return 1.0

    seq = difflib.SequenceMatcher(None, text_a, text_b)
    return 1.0 - seq.ratio()


def compare_files_byte(file_path: str, official_bytes: bytes) -> Tuple[bool, str]:
    """
    字节级比对：本地文件 vs 官方原始字节。
    返回 (是否一致, 本地哈希)。
    """
    local_hash = calculate_sha256(Path(file_path))
    official_hash = hashlib.sha256(official_bytes).hexdigest()
    return local_hash == official_hash, local_hash


def compare_files_normalized(file_path: str, official_text: str) -> Tuple[bool, str]:
    """
    规范化比对：本地规范化 vs 官方规范化。
    返回 (是否一致, 本地规范化哈希)。
    """
    local_body = extract_body_from_md(Path(file_path))
    local_norm = normalize_text(local_body)
    official_norm = normalize_text(official_text)

    local_hash = hashlib.sha256(local_norm.encode("utf-8")).hexdigest()
    official_hash = hashlib.sha256(official_norm.encode("utf-8")).hexdigest()

    return local_hash == official_hash, local_hash


def is_local_superset(local_text: str, official_text: str) -> bool:
    """判断本地内容是否包含官方内容（本地是超集）。"""
    local_norm = normalize_text(local_text)
    official_norm = normalize_text(official_text)
    return official_norm in local_norm


def is_official_superset(local_text: str, official_text: str) -> bool:
    """判断官方内容是否包含本地内容（官方是超集）。"""
    return is_local_superset(official_text, local_text)
