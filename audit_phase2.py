#!/usr/bin/env python3
"""
audit_phase2.py — 效力状态审计（企查查优先，省北大法宝积分）
策略：按分类抽样标"有效"的文件，用企查查验证效力状态。
"""
import csv, json, os, re, sys, time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

BASE = Path(r"D:\Codex\1.法律工作区\legal-cn-core-codices开发区")
FORMAL = BASE / "legal-cn-core-codices"
REPO = BASE / "legal-cn-core-codices-repo"
MANIFEST = REPO / "workspace" / "工程记录" / "final_acceptance_20260807_121000_v5" / "批次清单" / "标准编码生成清单.csv"
REPORT = BASE / f"audit_phase2_{datetime.now():%Y%m%d_%H%M%S}.md"

EFFECT_RE = re.compile(r'_(有效|失效|废止|已被修订|部分失效废止|尚未生效|草案)_')
TITLE_RE = re.compile(r'^(.+?)_(\d{4}-\d{2}-\d{2})_')

lines = []
def out(s):
    print(s, flush=True)
    lines.append(s)

out(f"# Phase 2 效力状态审计报告 — {datetime.now():%Y-%m-%d %H:%M}")
out("")

# ── 收集标"有效"的文件 ──
out("## 1. 收集标'有效'的文件")
valid_files = []  # (分类, 标题, 文件名, 相对路径)
for dp, _, fns in os.walk(str(FORMAL)):
    for fn in fns:
        if not fn.lower().endswith(".md"):
            continue
        if "_有效_" not in fn:
            continue
        m = TITLE_RE.match(fn)
        if not m:
            continue
        title = m.group(1)
        rel = os.path.relpath(os.path.join(dp, fn), str(FORMAL))
        cat = rel.split(os.sep)[0][:4] if os.sep in rel else rel.split("/")[0][:4]
        valid_files.append((cat, title, fn, rel))

out(f"标'有效'文件总数: {len(valid_files)}")

# 按分类统计
cat_counts = Counter(c for c, _, _, _ in valid_files)
out("按分类分布:")
for c, n in cat_counts.most_common():
    out(f"  {c}: {n}")
out("")

# ── 抽样策略：每个分类抽 50 个 ──
SAMPLE_PER_CAT = 50
samples = []
for cat in sorted(cat_counts.keys()):
    cat_files = [(c, t, f, r) for c, t, f, r in valid_files if c == cat]
    # 优先抽标题短的（更可能精确匹配）
    cat_files.sort(key=lambda x: len(x[1]))
    samples.extend(cat_files[:SAMPLE_PER_CAT])

out(f"## 2. 抽样验证（每分类 {SAMPLE_PER_CAT} 个，共 {len(samples)} 个）")
out(f"验证方式: 企查查 → WebSearch → 北大法宝（按优先级）")
out("")

# ── 输出抽样清单供后续验证 ──
sample_path = BASE / "audit_phase2_sample.csv"
with open(sample_path, "w", encoding="utf-8-sig", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["分类", "标题", "文件名", "相对路径", "验证结果", "企查查效力", "证据来源"])
    for cat, title, fn, rel in samples:
        w.writerow([cat, title, fn, rel, "", "", ""])

out(f"抽样清单已写入: {sample_path}")
out(f"共 {len(samples)} 个待验证")
out("")

# ── 按分类输出验证指令 ──
out("## 3. 验证指令（按分类批量执行）")
out("")
for cat in sorted(cat_counts.keys()):
    cat_samples = [(t, r) for c, t, f, r in samples if c == cat]
    out(f"### {cat} ({len(cat_samples)} 个)")
    for t, r in cat_samples[:5]:
        out(f"  - {t[:60]}")
    if len(cat_samples) > 5:
        out(f"  - ... 共 {len(cat_samples)} 个")
    out("")

# ── 写报告 ──
with open(REPORT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines))
out(f"报告已写入: {REPORT}")
out("")
out("下一步: 用企查查 mcp__qcc-legal__get_legal_regulation_search 逐个验证抽样文件的效力状态")
out("        如果企查查显示'失效废止'，标记为疑似误标")
out("        企查查不确定的，用 WebSearch 查官方网站")
out("        最后才用北大法宝（省积分）")
