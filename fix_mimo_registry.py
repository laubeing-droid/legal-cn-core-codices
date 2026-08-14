#!/usr/bin/env python3
"""
修复 Mimo 对 registry.json 的破坏性改写（2026-08-14 02:44）。

审计结论：
- Mimo 用 (agency_code, promulgation_date) 一对多映射"拍平"修复 source_sha256，
  同一天公布的多部法规全部被指向第一个文件的哈希 → 1579 条原本正确的被改坏。
- 意外收获：90 条旧值原本错配 evidence 文件哈希，Mimo 改对了（保留）。
- 恢复策略：git checkout 回到 HEAD（2001 条正确 + 89 条 evidence 错配 + 2 条未知），
  然后按 title 精确匹配源材料文件，修复 89 + 2 条。
"""

import json
import os
import hashlib
import subprocess
import sys
from pathlib import Path

BASE = Path(r"D:\Codex\1.法律工作区\legal-cn-core-codices开发区")
REPO = BASE / "legal-cn-core-codices-repo"
SRC = REPO / "workspace" / "source" / "legal-references"
REG = REPO / "schema" / "official_registry" / "decision_order_evidence" / "registry.json"
EVID = REG.parent


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(65536), b""):
            h.update(c)
    return h.hexdigest()


def build_src_index() -> dict:
    """{sha256: 绝对路径} 源材料 md 索引"""
    idx = {}
    for dp, _, fns in os.walk(SRC):
        for fn in fns:
            if not fn.lower().endswith(".md"):
                continue
            p = Path(dp) / fn
            idx[sha256_file(p)] = str(p)
    return idx


def build_ev_index() -> dict:
    """{sha256: 文件名} evidence 文件索引"""
    idx = {}
    for fn in os.listdir(EVID):
        p = EVID / fn
        if p.is_file():
            idx[sha256_file(p)] = fn
    return idx


def main() -> int:
    src_idx = build_src_index()
    ev_idx = build_ev_index()
    src_files = list(src_idx.values())

    # 1. 恢复 HEAD 版本
    subprocess.run(["git", "checkout", "--", str(REG)], cwd=REPO, check=True)
    reg = json.loads(REG.read_text(encoding="utf-8-sig"))
    entries = reg["entries"]
    print(f"已恢复 HEAD 版本，条目数: {len(entries)}")

    # 2. 分类旧值
    cat_src, cat_ev, cat_unknown = [], [], []
    for e in entries:
        sha = e.get("source_sha256", "")
        if sha in src_idx:
            cat_src.append(e)
        elif sha in ev_idx:
            cat_ev.append(e)
        else:
            cat_unknown.append(e)
    print(f"旧值分类: 源材料={len(cat_src)} / evidence={len(cat_ev)} / 未知={len(cat_unknown)}")

    # 3. 对 evidence 错配 + 未知的条目，按 title 精确匹配源材料
    def title_hits(t: str) -> list:
        """返回按匹配长度降序的源材料路径列表"""
        hits = []
        for p in src_files:
            b = Path(p).name
            if t and t[:12] in b:
                hits.append((len(t), p))
        hits.sort(key=lambda x: -x[0])
        return [p for _, p in hits]

    fixed = 0
    unfixable = []
    for e in cat_ev + cat_unknown:
        # ordered_titles 混合结构：可能是字符串列表，也可能是 {title, order} dict 列表
        titles = []
        for t in e.get("ordered_titles", []):
            if isinstance(t, str) and t.strip():
                titles.append(t)
            elif isinstance(t, dict) and t.get("title"):
                titles.append(t["title"])
        t = titles[0] if titles else ""
        hits = title_hits(t) if t else []
        if not hits:
            unfixable.append((e, t))
            continue
        best = hits[0]
        e["source_sha256"] = sha256_file(Path(best))
        fixed += 1

    # 4. 写回
    if fixed > 0:
        REG.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"按 title 修复: {fixed} 条")
    print(f"不可修复: {len(unfixable)}")
    for e, t in unfixable[:10]:
        ts = []
        for x in e.get("ordered_titles", [])[:2]:
            if isinstance(x, str):
                ts.append(x)
            elif isinstance(x, dict) and x.get("title"):
                ts.append(x["title"])
        print(f"  {e.get('agency_code','')} {e.get('promulgation_date','')}: [{t[:40]}] | {ts[1][:40] if len(ts)>1 else ''}")

    # 5. 最终验证
    reg = json.loads(REG.read_text(encoding="utf-8-sig"))
    ok = 0
    bad = 0
    for e in reg["entries"]:
        sha = e.get("source_sha256", "")
        if sha in src_idx:
            ok += 1
        else:
            bad += 1
            if bad <= 3:
                print(f"  仍不匹配: {e.get('agency_code','')} {e.get('promulgation_date','')} sha={sha[:16]}...")
    print(f"\n最终验证: 匹配源材料 {ok}/{len(reg['entries'])}，剩余 {bad}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
