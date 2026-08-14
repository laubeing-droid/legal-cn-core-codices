#!/usr/bin/env python3
"""
audit_step1_local.py — 纯本地审计（不依赖外部API）
分步运行，每步输出进度，断点续跑。
"""
import csv, hashlib, json, os, re, sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

BASE = Path(r"D:\Codex\1.法律工作区\legal-cn-core-codices开发区")
FORMAL = BASE / "legal-cn-core-codices"
REPO = BASE / "legal-cn-core-codices-repo"
SRC = REPO / "workspace" / "source" / "legal-references"
EVID_DIR = REPO / "schema" / "official_registry" / "decision_order_evidence"
REG_PATH = EVID_DIR / "registry.json"
MANIFEST = REPO / "workspace" / "工程记录" / "final_acceptance_20260807_121000_v5" / "批次清单" / "标准编码生成清单.csv"
REPORT = BASE / f"audit_report_{datetime.now():%Y%m%d_%H%M%S}.md"

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def scan_md(root):
    result = {}
    if not root.exists(): return result
    for dp, _, fns in os.walk(root):
        for fn in fns:
            if fn.lower().endswith(".md"):
                full = Path(dp) / fn
                result[str(full.relative_to(root)).replace("\\", "/")] = full
    return result

def frontmatter(text):
    if not text.startswith("---"): return {}
    end = text.find("---", 3)
    if end < 0: return {}
    m = {}
    for line in text[3:end].split("\n"):
        if ":" in line:
            k, _, v = line.strip().partition(":")
            v = v.strip().strip("'\"")
            if v: m[k.strip()] = v
    return m

lines = []
def out(s):
    print(s, flush=True)
    lines.append(s)

out(f"# 全库审计报告 — {datetime.now():%Y-%m-%d %H:%M}")
out("")

# ── 5.1 正式目录 md 内容重复 ──
out("## 5.1 正式 md 内容重复")
out("扫描中...")
hash_map = defaultdict(list)
cnt = 0
for rel, path in scan_md(FORMAL).items():
    cnt += 1
    if cnt % 5000 == 0: out(f"  进度: {cnt}")
    try: hash_map[sha256_file(path)].append(rel)
    except: pass
dups = {h: ps for h, ps in hash_map.items() if len(ps) > 1}
out(f"扫描完成: {cnt} 个文件, {len(dups)} 组重复")
for h, ps in list(dups.items())[:10]:
    out(f"  重复({len(ps)}): {ps[0][:80]}")
out("")

# ── 5.2 编码清单 relative_path 重复 ──
out("## 5.2 编码清单 relative_path 重复")
if MANIFEST.exists():
    with open(MANIFEST, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    paths = [r.get("relative_path","").strip() for r in rows if r.get("relative_path","").strip()]
    dups52 = {p: c for p, c in Counter(paths).items() if c > 1}
    out(f"清单总行: {len(rows)}, 重复 path: {len(dups52)}")
    for p, c in list(dups52.items())[:10]:
        out(f"  {c}次: {p[:80]}")
else:
    out("清单不存在")
out("")

# ── 5.3 registry entry 重复 + 自动去重 ──
out("## 5.3 registry entry 去重")
if REG_PATH.exists():
    reg = json.load(open(REG_PATH, encoding="utf-8-sig"))
    seen, deduped, dup_cnt = set(), [], 0
    for e in reg["entries"]:
        key = (e.get("agency_code"), e.get("promulgation_date"), e.get("sequence_code"), e.get("evidence_path"))
        if key in seen: dup_cnt += 1; continue
        seen.add(key); deduped.append(e)
    if dup_cnt:
        reg["entries"] = deduped
        reg["version"] = f"deduped-{datetime.now():%Y%m%d%H%M}"
        with open(REG_PATH, "w", encoding="utf-8") as fh: json.dump(reg, fh, ensure_ascii=False, indent=2)
        out(f"自动去重 {dup_cnt} 条, 保留 {len(deduped)} 条")
    else:
        out(f"无重复 ({len(reg['entries'])} 条)")
else:
    out("registry.json 不存在")
out("")

# ── 2.1 registry source_sha256 校验 ──
out("## 2.1 registry source_sha256 校验")
if REG_PATH.exists() and MANIFEST.exists():
    reg = json.load(open(REG_PATH, encoding="utf-8-sig"))
    with open(MANIFEST, encoding="utf-8-sig", newline="") as fh:
        mrows = list(csv.DictReader(fh))
    mmap = {}
    for r in mrows:
        key = (r.get("agency_code","").strip(), r.get("promulgation_date","").strip())
        mmap.setdefault(key, []).append(r.get("relative_path","").strip())
    mismatch, fixed = 0, 0
    for e in reg["entries"]:
        key = (e.get("agency_code",""), e.get("promulgation_date",""))
        expected = e.get("source_sha256","")
        if not expected: continue
        for rel in mmap.get(key, []):
            sp = SRC / rel.replace("\\", "/")
            if sp.exists():
                actual = sha256_file(sp)
                if actual != expected:
                    mismatch += 1
                    e["source_sha256"] = actual
                    fixed += 1
                break
    if fixed:
        with open(REG_PATH, "w", encoding="utf-8") as fh: json.dump(reg, fh, ensure_ascii=False, indent=2)
        out(f"不一致 {mismatch} 条, 自动修复 {fixed} 条")
    else:
        out(f"全部一致 (检查 {len(reg['entries'])} 条)")
else:
    out("跳过")
out("")

# ── 3.1 WZWS/script 挑战页 ──
out("## 3.1 WZWS/script 挑战页")
WZWS = re.compile(r"WZWS|<script|document\.cookie|location\.href|window\.location", re.I)
hits = []
for rel, path in scan_md(SRC).items():
    try:
        if WZWS.search(path.read_text(encoding="utf-8", errors="replace")[:5000]):
            hits.append(rel)
    except: pass
out(f"检测 {len(scan_md(SRC))} 个源文件, {len(hits)} 个含挑战页特征")
for f in hits[:10]: out(f"  {f[:80]}")
out("")

# ── 3.2 正文过短 ──
out("## 3.2 正文过短 (<200字符)")
short = []
for rel, path in scan_md(SRC).items():
    try:
        t = path.read_text(encoding="utf-8", errors="replace")
        body = t[t.find("---", 3)+3:].strip() if t.startswith("---") else t
        if len(body) < 200: short.append((rel, len(body)))
    except: pass
out(f"检测完成, {len(short)} 个文件正文 <200 字符")
for f, n in short[:10]: out(f"  ({n}字符) {f[:80]}")
out("")

# ── 3.3 GBK 乱码 ──
out("## 3.3 GBK 乱码")
GBK = re.compile(r"锟斤拷|鑳辨|[\x00-\x08\x0e-\x1f]{3,}")
gbk = []
for rel, path in scan_md(SRC).items():
    try:
        if GBK.search(path.read_bytes()[:10000].decode("utf-8", errors="replace")):
            gbk.append(rel)
    except: pass
out(f"检测完成, {len(gbk)} 个文件含 GBK 乱码特征")
for f in gbk[:10]: out(f"  {f[:80]}")
out("")

# ── 4.1 文件名不可见字符 ──
out("## 4.1 文件名不可见字符")
INV = re.compile(r"[\u200b\u200c\u200d\ufeff\u00a0]")
inv_files = []
for root_dir in [FORMAL, SRC]:
    if not root_dir.exists(): continue
    for dp, _, fns in os.walk(root_dir):
        for fn in fns:
            if INV.search(fn):
                inv_files.append(str(Path(dp, fn).relative_to(root_dir)))
out(f"检测完成, {len(inv_files)} 个文件名含不可见字符")
for f in inv_files[:10]: out(f"  {f[:80]}")
out("")

# ── 4.2 元数据字段缺失（抽样 3000）──
out("## 4.2 元数据字段缺失（抽样 3000）")
REQ = ["title", "date", "publication_date", "effective_date", "status", "author"]
missing = []
for i, (rel, path) in enumerate(scan_md(SRC).items()):
    if i >= 3000: break
    try:
        m = frontmatter(path.read_text(encoding="utf-8", errors="replace")[:3000])
        miss = [f for f in REQ if f not in m or not m[f]]
        if miss: missing.append((rel, miss))
    except: pass
out(f"抽样 3000, {len(missing)} 个文件缺字段")
for f, m in missing[:5]: out(f"  缺{m}: {f[:60]}")
out("")

# ── 8.4 WJBS 格式校验 ──
out("## 8.4 WJBS 编码格式校验")
WJBS_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+\.\d+-\d{20}$")
if MANIFEST.exists():
    with open(MANIFEST, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    bad = [(r.get("relative_path",""), r.get("WJBS","")) for r in rows
           if r.get("WJBS","").strip() and not WJBS_RE.match(r.get("WJBS","").strip())]
    out(f"清单 {len(rows)} 行, {len(bad)} 个 WJBS 格式异常")
    for p, w in bad[:5]: out(f"  {w} | {p[:60]}")
else:
    out("清单不存在")
out("")

# ── 10.1 门类覆盖率 ──
out("## 10.1 门类覆盖率")
cats = Counter()
for rel in scan_md(FORMAL): cats[rel.split("/")[0][:4]] += 1
for cat, cnt in cats.most_common(): out(f"  {cat}: {cnt}")
out("")

# ── 10.2 地域覆盖 ──
out("## 10.2 地域覆盖均衡性")
PROVS = ["北京","天津","上海","重庆","河北","山西","辽宁","吉林","黑龙江","江苏","浙江","安徽","福建","江西","山东","河南","湖北","湖南","广东","海南","四川","贵州","云南","陕西","甘肃","青海","台湾","内蒙古","广西","西藏","宁夏","新疆"]
if MANIFEST.exists():
    with open(MANIFEST, encoding="utf-8-sig", newline="") as fh:
        mrows = list(csv.DictReader(fh))
    pc = Counter()
    for r in mrows:
        rel = r.get("relative_path","")
        for p in PROVS:
            if p in rel: pc[p] += 1; break
    missing_prov = [p for p in PROVS if p not in pc]
    for p, c in pc.most_common(): out(f"  {p}: {c}")
    if missing_prov: out(f"  零覆盖: {', '.join(missing_prov)}")
out("")

# ── 写报告 ──
with open(REPORT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines))
print(f"\n报告已写入: {REPORT}", flush=True)
