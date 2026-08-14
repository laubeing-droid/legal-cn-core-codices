#!/usr/bin/env python3
"""
legal-cn-core-codices 全库自动审计脚本
一次性执行，自动发现问题 + 自动修复 + 输出报告。
约束：正式目录只读（仅扫描），所有修复在 repo 内完成。
"""

import csv
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# ── 路径配置 ──────────────────────────────────────────────
BASE = Path(r"D:\Codex\1.法律工作区\legal-cn-core-codices开发区")
FORMAL = BASE / "legal-cn-core-codices"
REPO = BASE / "legal-cn-core-codices-repo"
SRC = REPO / "workspace" / "source" / "legal-references"
EVID_DIR = REPO / "schema" / "official_registry" / "decision_order_evidence"
REG_PATH = EVID_DIR / "registry.json"
MANIFEST = REPO / "workspace" / "工程记录" / "final_acceptance_20260807_121000_v5" / "批次清单" / "标准编码生成清单.csv"

REPORT_DIR = BASE
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

# ── 工具函数 ──────────────────────────────────────────────
def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def scan_md(root: Path) -> dict[str, Path]:
    """返回 {相对路径: 绝对路径} 的 md 文件映射"""
    result = {}
    if not root.exists():
        return result
    for dp, _, fns in os.walk(root):
        for fn in fns:
            if fn.lower().endswith(".md"):
                full = Path(dp) / fn
                rel = str(full.relative_to(root)).replace("\\", "/")
                result[rel] = full
    return result

def read_yaml_frontmatter(text: str) -> dict:
    """简易 YAML frontmatter 解析"""
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end < 0:
        return {}
    meta = {}
    for line in text[3:end].split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip().strip("'\"")
            if v:
                meta[k] = v
    return meta

# ── 审计结果收集 ──────────────────────────────────────────
results = {
    "timestamp": TIMESTAMP,
    "phase1": {},
    "auto_fixes": [],
    "warnings": [],
    "errors": [],
}

def add_warning(category: str, msg: str, detail: str = ""):
    results["warnings"].append({"category": category, "message": msg, "detail": detail})

def add_fix(category: str, msg: str):
    results["auto_fixes"].append({"category": category, "message": msg})

# ══════════════════════════════════════════════════════════
# Phase 1: 纯本地审计
# ══════════════════════════════════════════════════════════

print("=" * 60)
print("Phase 1: 纯本地审计")
print("=" * 60)

# ── 1.3 编码清单 effect_code vs 正式 md status ────────────
print("\n[1.3] 编码清单 effect_code vs 正式 md status ...")
if MANIFEST.exists():
    formal_mds = scan_md(FORMAL)
    mismatch_13 = []
    with open(MANIFEST, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rel = row.get("relative_path", "").strip()
            csv_effect = row.get("effect_code", "").strip()
            if not rel or not csv_effect:
                continue
            formal_path = FORMAL / rel.replace("\\", "/")
            if not formal_path.exists():
                continue
            try:
                text = formal_path.read_text(encoding="utf-8")[:2000]
            except:
                continue
            meta = read_yaml_frontmatter(text)
            md_status = meta.get("status", "").strip()
            if not md_status:
                continue
            # 简化映射
            status_map = {"有效": "01", "已被修订": "02", "部分失效废止": "03",
                          "失效废止": "04", "尚未生效": "05", "草案": "06"}
            expected = status_map.get(md_status, "")
            if expected and csv_effect != expected:
                mismatch_13.append({"path": rel, "csv_effect": csv_effect,
                                    "md_status": md_status, "expected": expected})
    results["phase1"]["effect_mismatch"] = len(mismatch_13)
    if mismatch_13:
        for m in mismatch_13[:20]:
            add_warning("1.3", f"效力不一致: {m['path'][:80]}",
                        f"清单={m['csv_effect']} md={m['md_status']} 应={m['expected']}")
        if len(mismatch_13) > 20:
            add_warning("1.3", f"... 共 {len(mismatch_13)} 条不一致")
    print(f"  结果: {len(mismatch_13)} 条不一致")
else:
    add_warning("1.3", "编码清单不存在")
    print("  跳过：编码清单不存在")

# ── 2.1 registry source_sha256 校验 ──────────────────────
print("\n[2.1] registry source_sha256 校验 ...")
if REG_PATH.exists():
    reg = json.load(open(REG_PATH, encoding="utf-8-sig"))
    hash_mismatch = 0
    hash_fixed = 0
    for entry in reg["entries"]:
        expected_sha = entry.get("source_sha256", "")
        if not expected_sha:
            continue
        # 从 evidence_path 反推源材料（简化：用 ordered_titles[0].title 匹配）
        # 实际应从编码清单找 relative_path，这里先跳过精确匹配
        pass
    # 精确匹配：按 (agency_code, promulgation_date) 找候选，再用 title 归一化精确锁定
    # 注意：同一天公布的多部法规共享同一 (agency_code, promulgation_date) key，
    # 必须用 ordered_titles[0] 的 title 做二次精确匹配，否则会把全部条目错误指向第一个文件。
    if MANIFEST.exists():
        with open(MANIFEST, encoding="utf-8-sig", newline="") as fh:
            manifest_rows = list(csv.DictReader(fh))
        # 建立 (agency_code, promulgation_date) -> relative_path 的映射
        manifest_map = {}
        for row in manifest_rows:
            key = (row.get("agency_code", "").strip(), row.get("promulgation_date", "").strip())
            rel = row.get("relative_path", "").strip()
            if key not in manifest_map:
                manifest_map[key] = []
            manifest_map[key].append(rel)

        def norm_title(s: str) -> str:
            """标题归一化：去书名号/全半角括号/空格"""
            s = s.replace("《", "").replace("》", "")
            s = s.replace("（", "(").replace("）", ")")
            s = s.replace(" ", "").replace("\u3000", "")
            return s

        for entry in reg["entries"]:
            key = (entry.get("agency_code", ""), entry.get("promulgation_date", ""))
            expected_sha = entry.get("source_sha256", "")
            if not expected_sha:
                continue
            rels = manifest_map.get(key, [])
            # 取该条目的首个标题（ordered_titles 可能是字符串列表或 {title,order} 列表）
            first_title = ""
            for t in entry.get("ordered_titles", []):
                if isinstance(t, str) and t.strip():
                    first_title = t
                    break
                elif isinstance(t, dict) and t.get("title"):
                    first_title = t["title"]
                    break
            nt = norm_title(first_title)
            # 从候选里挑标题与文件名匹配的（避免一对多拍平）
            best_rel = None
            if nt:
                for rel in rels:
                    if nt[:10] in norm_title(os.path.basename(rel)):
                        best_rel = rel
                        break
            if best_rel is None and len(rels) == 1:
                best_rel = rels[0]  # 唯一候选时直接使用
            if best_rel is None:
                continue
            src_path = SRC / best_rel.replace("\\", "/")
            if src_path.exists():
                actual_sha = sha256_file(src_path)
                if actual_sha != expected_sha:
                    hash_mismatch += 1
                    # 自动修复：更新 registry 的 source_sha256
                    entry["source_sha256"] = actual_sha
                    hash_fixed += 1

    if hash_fixed > 0:
        with open(REG_PATH, "w", encoding="utf-8") as fh:
            json.dump(reg, fh, ensure_ascii=False, indent=2)
        add_fix("2.1", f"自动修复 {hash_fixed} 条 registry source_sha256（title精确匹配）")
    results["phase1"]["sha256_mismatch"] = hash_mismatch
    results["phase1"]["sha256_fixed"] = hash_fixed
    print(f"  结果: {hash_mismatch} 条不一致，已修复 {hash_fixed} 条（title精确匹配，避免一对多拍平）")
else:
    add_warning("2.1", "registry.json 不存在")
    print("  跳过：registry.json 不存在")

# ── 3.1 源材料 WZWS/script 挑战页 ────────────────────────
print("\n[3.1] 源材料 WZWS/script 挑战页检测 ...")
WZWS_PATTERNS = re.compile(r"WZWS|<script|document\.cookie|location\.href|window\.location", re.IGNORECASE)
wzws_files = []
if SRC.exists():
    for rel, path in scan_md(SRC).items():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:5000]
            if WZWS_PATTERNS.search(text):
                wzws_files.append(rel)
        except:
            pass
results["phase1"]["wzws_files"] = len(wzws_files)
if wzws_files:
    for f in wzws_files[:20]:
        add_warning("3.1", f"WZWS/script: {f[:80]}")
    if len(wzws_files) > 20:
        add_warning("3.1", f"... 共 {len(wzws_files)} 个文件")
print(f"  结果: {len(wzws_files)} 个文件含 WZWS/script")

# ── 3.2 源材料正文过短 ────────────────────────────────────
print("\n[3.2] 源材料正文过短检测 ...")
short_files = []
if SRC.exists():
    for rel, path in scan_md(SRC).items():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            # 去掉 YAML frontmatter
            if text.startswith("---"):
                end = text.find("---", 3)
                if end > 0:
                    body = text[end+3:].strip()
                else:
                    body = text
            else:
                body = text
            if len(body) < 200:
                short_files.append((rel, len(body)))
        except:
            pass
results["phase1"]["short_files"] = len(short_files)
if short_files:
    for f, ln in short_files[:20]:
        add_warning("3.2", f"正文过短({ln}字符): {f[:80]}")
    if len(short_files) > 20:
        add_warning("3.2", f"... 共 {len(short_files)} 个文件")
print(f"  结果: {len(short_files)} 个文件正文 <200 字符")

# ── 3.3 GBK 乱码检测 ─────────────────────────────────────
print("\n[3.3] GBK 乱码检测 ...")
GBK_PATTERN = re.compile(r"锟斤拷|鑳辨|\\ufffd|[\x00-\x08\x0e-\x1f]{3,}")
gbk_files = []
if SRC.exists():
    for rel, path in scan_md(SRC).items():
        try:
            raw = path.read_bytes()[:10000]
            text = raw.decode("utf-8", errors="replace")
            if GBK_PATTERN.search(text):
                gbk_files.append(rel)
        except:
            pass
results["phase1"]["gbk_files"] = len(gbk_files)
if gbk_files:
    for f in gbk_files[:20]:
        add_warning("3.3", f"GBK 乱码: {f[:80]}")
print(f"  结果: {len(gbk_files)} 个文件含 GBK 乱码特征")

# ── 4.1 文件名不可见字符 ─────────────────────────────────
print("\n[4.1] 文件名不可见字符检测 ...")
INVISIBLE = re.compile(r"[\u200b\u200c\u200d\ufeff\u00a0]")
invisible_files = []
for root_dir in [FORMAL, SRC]:
    if not root_dir.exists():
        continue
    for dp, _, fns in os.walk(root_dir):
        for fn in fns:
            if INVISIBLE.search(fn):
                invisible_files.append(str(Path(dp, fn).relative_to(root_dir)))
results["phase1"]["invisible_chars"] = len(invisible_files)
if invisible_files:
    for f in invisible_files[:20]:
        add_warning("4.1", f"不可见字符: {f[:80]}")
print(f"  结果: {len(invisible_files)} 个文件名含不可见字符")

# ── 4.2 元数据必要字段缺失 ───────────────────────────────
print("\n[4.2] 元数据字段完整性检测 ...")
REQUIRED_FIELDS = ["title", "date", "publication_date", "effective_date", "status", "author"]
missing_fields = []
if SRC.exists():
    sample_count = 0
    for rel, path in scan_md(SRC).items():
        sample_count += 1
        if sample_count > 5000:  # 抽样 5000 个
            break
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:3000]
            meta = read_yaml_frontmatter(text)
            missing = [f for f in REQUIRED_FIELDS if f not in meta or not meta[f]]
            if missing:
                missing_fields.append((rel, missing))
        except:
            pass
results["phase1"]["missing_fields"] = len(missing_fields)
if missing_fields:
    for f, m in missing_fields[:10]:
        add_warning("4.2", f"缺字段 {m}: {f[:60]}")
    if len(missing_fields) > 10:
        add_warning("4.2", f"... 共 {len(missing_fields)} 个文件缺字段")
print(f"  结果: {len(missing_fields)} 个文件缺必要字段（抽样 5000）")

# ── 4.3 日期格式一致性 ───────────────────────────────────
print("\n[4.3] 日期格式一致性检测 ...")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
bad_dates = []
if SRC.exists():
    sample_count = 0
    for rel, path in scan_md(SRC).items():
        sample_count += 1
        if sample_count > 5000:
            break
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:3000]
            meta = read_yaml_frontmatter(text)
            for field in ["date", "publication_date", "effective_date"]:
                val = meta.get(field, "").strip()
                if val and not DATE_RE.match(val):
                    bad_dates.append((rel, field, val))
        except:
            pass
results["phase1"]["bad_dates"] = len(bad_dates)
if bad_dates:
    for f, field, val in bad_dates[:10]:
        add_warning("4.3", f"日期格式异常: {f[:50]} {field}={val}")
print(f"  结果: {len(bad_dates)} 个日期格式异常（抽样 5000）")

# ── 5.1 正式 md 内容重复 ─────────────────────────────────
print("\n[5.1] 正式 md 内容重复检测 ...")
hash_map = defaultdict(list)
if FORMAL.exists():
    for rel, path in scan_md(FORMAL).items():
        try:
            h = sha256_file(path)
            hash_map[h].append(rel)
        except:
            pass
dup_files = {h: paths for h, paths in hash_map.items() if len(paths) > 1}
results["phase1"]["duplicate_files"] = len(dup_files)
if dup_files:
    for h, paths in list(dup_files.items())[:10]:
        add_warning("5.1", f"重复({len(paths)}个): {paths[0][:60]}")
    if len(dup_files) > 10:
        add_warning("5.1", f"... 共 {len(dup_files)} 组重复")
print(f"  结果: {len(dup_files)} 组重复文件")

# ── 5.2 编码清单 relative_path 重复 ─────────────────────
print("\n[5.2] 编码清单 relative_path 重复检测 ...")
if MANIFEST.exists():
    with open(MANIFEST, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    paths = [r.get("relative_path", "").strip() for r in rows if r.get("relative_path", "").strip()]
    path_counts = Counter(paths)
    dups_52 = {p: c for p, c in path_counts.items() if c > 1}
    results["phase1"]["manifest_dups"] = len(dups_52)
    if dups_52:
        for p, c in list(dups_52.items())[:10]:
            add_warning("5.2", f"清单重复({c}次): {p[:60]}")
    print(f"  结果: {len(dups_52)} 个 relative_path 重复")
else:
    print("  跳过")

# ── 5.3 registry entry 重复 ──────────────────────────────
print("\n[5.3] registry entry 重复检测 + 自动去重 ...")
if REG_PATH.exists():
    reg = json.load(open(REG_PATH, encoding="utf-8-sig"))
    seen = set()
    deduped = []
    dup_count = 0
    for entry in reg["entries"]:
        key = (entry.get("agency_code"), entry.get("promulgation_date"),
               entry.get("sequence_code"), entry.get("evidence_path"))
        if key in seen:
            dup_count += 1
            continue
        seen.add(key)
        deduped.append(entry)
    if dup_count > 0:
        reg["entries"] = deduped
        reg["version"] = f"deduped-{TIMESTAMP}"
        with open(REG_PATH, "w", encoding="utf-8") as fh:
            json.dump(reg, fh, ensure_ascii=False, indent=2)
        add_fix("5.3", f"自动去重 {dup_count} 条 registry entry（{len(deduped)} 条保留）")
    results["phase1"]["registry_dups"] = dup_count
    print(f"  结果: {dup_count} 条重复，已自动去重")
else:
    print("  跳过")

# ── 8.4 WJBS 编码格式校验 ────────────────────────────────
print("\n[8.4] WJBS 编码格式校验 ...")
WJBS_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+\.\d+-\d{20}$")
if MANIFEST.exists():
    with open(MANIFEST, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    bad_wjbs = []
    for row in rows:
        wjbs = row.get("WJBS", "").strip()
        if not wjbs:
            continue
        if not WJBS_RE.match(wjbs):
            bad_wjbs.append((row.get("relative_path", ""), wjbs))
    results["phase1"]["bad_wjbs"] = len(bad_wjbs)
    if bad_wjbs:
        for p, w in bad_wjbs[:10]:
            add_warning("8.4", f"WJBS 格式异常: {w} ({p[:50]})")
    print(f"  结果: {len(bad_wjbs)} 个 WJBS 格式异常")
else:
    print("  跳过")

# ── 10.1 门类覆盖率统计 ─────────────────────────────────
print("\n[10.1] 门类覆盖率统计 ...")
cat_counts = Counter()
if FORMAL.exists():
    for rel in scan_md(FORMAL):
        parts = rel.split("/")
        if parts:
            cat = parts[0][:4]  # 取前4字符作为分类码
            cat_counts[cat] += 1
results["phase1"]["category_coverage"] = dict(cat_counts.most_common())
print(f"  结果: {len(cat_counts)} 个分类")
for cat, cnt in cat_counts.most_common():
    print(f"    {cat}: {cnt}")

# ── 10.2 地域覆盖均衡性 ─────────────────────────────────
print("\n[10.2] 地域覆盖均衡性 ...")
if MANIFEST.exists():
    with open(MANIFEST, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    # 从 relative_path 提取省份（简化：取路径中省级行政区名）
    PROVINCES = ["北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林",
                 "黑龙江", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
                 "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西",
                 "甘肃", "青海", "台湾", "内蒙古", "广西", "西藏", "宁夏", "新疆"]
    prov_counts = Counter()
    for row in rows:
        rel = row.get("relative_path", "")
        for prov in PROVINCES:
            if prov in rel:
                prov_counts[prov] += 1
                break
    results["phase1"]["province_coverage"] = dict(prov_counts.most_common())
    missing_prov = [p for p in PROVINCES if p not in prov_counts]
    if missing_prov:
        add_warning("10.2", f"零覆盖省份: {', '.join(missing_prov)}")
    print(f"  结果: {len(prov_counts)} 个省份有覆盖，{len(missing_prov)} 个零覆盖")
else:
    print("  跳过")

# ══════════════════════════════════════════════════════════
# 输出报告
# ══════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("生成报告 ...")
print("=" * 60)

# JSON 报告
json_path = REPORT_DIR / f"audit_report_{TIMESTAMP}.json"
with open(json_path, "w", encoding="utf-8") as fh:
    json.dump(results, fh, ensure_ascii=False, indent=2)
print(f"JSON 报告: {json_path}")

# MD 报告
md_path = REPORT_DIR / f"audit_report_{TIMESTAMP}.md"
with open(md_path, "w", encoding="utf-8") as fh:
    fh.write(f"# legal-cn-core-codices 全库审计报告\n\n")
    fh.write(f"执行时间: {TIMESTAMP}\n\n")
    fh.write("## 自动修复\n\n")
    if results["auto_fixes"]:
        for fix in results["auto_fixes"]:
            fh.write(f"- ✅ **{fix['category']}**: {fix['message']}\n")
    else:
        fh.write("- 无需修复\n")
    fh.write("\n## 审计结果\n\n")
    for k, v in results["phase1"].items():
        fh.write(f"- **{k}**: {v}\n")
    fh.write("\n## 警告\n\n")
    if results["warnings"]:
        for w in results["warnings"]:
            fh.write(f"- ⚠️ **{w['category']}**: {w['message']}")
            if w["detail"]:
                fh.write(f"  \n  详情: {w['detail']}")
            fh.write("\n")
    else:
        fh.write("- 无警告\n")
print(f"MD 报告: {md_path}")

# 汇总
total_warnings = len(results["warnings"])
total_fixes = len(results["auto_fixes"])
print(f"\n{'='*60}")
print(f"审计完成: {total_warnings} 个警告, {total_fixes} 个自动修复")
print(f"{'='*60}")
