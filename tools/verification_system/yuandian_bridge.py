"""
元典MCP桥接模块
================
通过文件交换机制，让Python脚本使用元典MCP的数据。
"""

import json
import time
from pathlib import Path
from typing import List, Dict, Optional

# 元典缓存目录
YUANDIAN_CACHE_DIR = Path("D:/legal-references/verification_system/yuandian_cache")
YUANDIAN_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 查询队列文件
QUERY_QUEUE_FILE = YUANDIAN_CACHE_DIR / "query_queue.json"
RESULT_FILE = YUANDIAN_CACHE_DIR / "results.json"


def save_queries(queries: List[Dict]):
    """保存查询队列到文件。"""
    with open(QUERY_QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queries, f, ensure_ascii=False, indent=2)
    print(f"已保存 {len(queries)} 条查询到 {QUERY_QUEUE_FILE}")


def load_results() -> Dict[str, Dict]:
    """加载已执行的结果。"""
    if RESULT_FILE.exists():
        with open(RESULT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_result(query_id: str, result: Dict):
    """保存单条查询结果。"""
    results = load_results()
    results[query_id] = result
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def batch_verify_from_cache(records: list) -> Dict[str, Dict]:
    """从缓存中批量读取元典验证结果。"""
    results = load_results()
    verified = {}

    for rec in records:
        query_id = _make_query_id(rec)
        if query_id in results:
            verified[rec.local_path] = results[query_id]

    return verified


def _make_query_id(record) -> str:
    """生成查询ID。"""
    parts = []
    if hasattr(record, 'title') and record.title:
        parts.append(record.title[:50])
    if hasattr(record, 'doc_number') and record.doc_number:
        parts.append(record.doc_number[:30])
    return "|".join(parts) if parts else record.local_path[:50]


def prepare_verification_queries(records: list, max_queries: int = 1000) -> List[Dict]:
    """准备元典验证查询队列。"""
    queries = []
    existing = load_results()

    for rec in records[:max_queries]:
        query_id = _make_query_id(rec)
        if query_id not in existing:
            queries.append({
                "id": query_id,
                "title": rec.title if hasattr(rec, 'title') else "",
                "doc_number": rec.doc_number if hasattr(rec, 'doc_number') else "",
                "local_path": rec.local_path if hasattr(rec, 'local_path') else "",
            })

    return queries
