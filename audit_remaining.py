#!/usr/bin/env python3
"""全库审计 - 剩余13项一次性完成"""
import os, re, json, hashlib, time, csv, struct
from collections import Counter, defaultdict
from datetime import datetime

BASE = r"D:\Codex\1.法律工作区\legal-cn-core-codices开发区"
FORMAL = os.path.join(BASE, "legal-cn-core-codices")
REPO = os.path.join(BASE, "legal-cn-core-codices-repo")
CORPUS = os.path.join(REPO, "corpus")
SRC = os.path.join(REPO, "workspace", "source", "legal-references")
EVID_DIR = os.path.join(REPO, "schema", "official_registry", "decision_order_evidence")
REG_FILE = os.path.join(EVID_DIR, "registry.json")
CSV_MANIFEST = os.path.join(REPO, "workspace", "工程记录", "final_acceptance_20260807_121000_v5", "批次清单", "标准编码生成清单.csv")

TITLE_DATE_RE = re.compile(r'^(.+?)_(\d{4}-\d{2}-\d{2})_')
EFFECT_RE = re.compile(r'_(有效|失效|废止|已被修订|部分失效废止|尚未生效|草案)_')
BOM_3 = b'\xef\xbb\xbf'
URL_RE = re.compile(r'https?://[^\s\)）\]】"\'<>]+')

def main():
    print("=" * 60)
    print("全库审计 - 剩余13项")
    print(f"开始: {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 60)

    results = {}

    # ===== 1.2 废止→应有效 =====
    print("\n[1/13] 1.2 废止→应有效...", flush=True)
    abandoned_valid = []
    for dp, _, fns in os.walk(FORMAL):
        for fn in fns:
            if not fn.lower().endswith(".md"): continue
            if "_废止_" in fn or "_失效_" in fn:
                abandoned_valid.append(os.path.relpath(os.path.join(dp, fn), FORMAL))
    results["1.2_废止文件数"] = len(abandoned_valid)
    print(f"  标'废止/失效'的文件: {len(abandoned_valid)}")

    # ===== 1.3 效力与清单不一致 =====
    print("\n[2/13] 1.3 效力与清单不一致...", flush=True)
    formal_effect = {}
    for dp, _, fns in os.walk(FORMAL):
        for fn in fns:
            if not fn.lower().endswith(".md"): continue
            m = EFFECT_RE.search(fn)
            if m:
                rel = os.path.relpath(os.path.join(dp, fn), FORMAL)
                formal_effect[rel] = m.group(1)
    
    manifest_effect = {}
    if os.path.exists(CSV_MANIFEST):
        with open(CSV_MANIFEST, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                rp = r.get("relative_path", "").strip()
                ec = r.get("effect_code", "").strip()
                if rp and ec:
                    manifest_effect[rp] = ec
    
    effect_mismatch = 0
    for rp, fe in formal_effect.items():
        me = manifest_effect.get(rp, "")
        if me and fe != me:
            effect_mismatch += 1
    results["1.3_效力不一致"] = effect_mismatch
    print(f"  正式md vs 清单效力不一致: {effect_mismatch}")

    # ===== 2.3 内容一致性（500抽样）=====
    print("\n[3/13] 2.3 内容一致性（500抽样）...", flush=True)
    sample_mismatch = 0
    sample_count = 0
    for dp, _, fns in os.walk(FORMAL):
        for fn in fns:
            if not fn.lower().endswith(".md"): continue
            if sample_count >= 500: break
            formal_path = os.path.join(dp, fn)
            rel = os.path.relpath(formal_path, FORMAL)
            corpus_path = os.path.join(CORPUS, rel)
            if not os.path.exists(corpus_path): continue
            try:
                h1 = hashlib.sha256(open(formal_path, "rb").read()).hexdigest()
                h2 = hashlib.sha256(open(corpus_path, "rb").read()).hexdigest()
                if h1 != h2:
                    sample_mismatch += 1
            except: pass
            sample_count += 1
        if sample_count >= 500: break
    results["2.3_内容不一致"] = sample_mismatch
    print(f"  500抽样内容不一致: {sample_mismatch}")

    # ===== 3.4 UTF-8 BOM =====
    print("\n[4/13] 3.4 UTF-8 BOM...", flush=True)
    bom_count = 0
    for dp, _, fns in os.walk(FORMAL):
        for fn in fns:
            if not fn.lower().endswith(".md"): continue
            try:
                with open(os.path.join(dp, fn), "rb") as f:
                    if f.read(3) == BOM_3:
                        bom_count += 1
            except: pass
    results["3.4_BOM文件"] = bom_count
    print(f"  UTF-8 BOM文件: {bom_count}")

    # ===== 4.2 元数据字段完整性 =====
    print("\n[5/13] 4.2 元数据字段完整性...", flush=True)
    required_fields = ["title", "date", "status", "author"]
    missing_fields = defaultdict(int)
    total_meta = 0
    for dp, _, fns in os.walk(SRC):
        for fn in fns:
            if not fn.lower().endswith(".md"): continue
            total_meta += 1
            if total_meta > 3000: break
            try:
                with open(os.path.join(dp, fn), encoding="utf-8", errors="replace") as f:
                    head = f.read(1000)
                for field in required_fields:
                    if not re.search(rf"^{field}:", head, re.M):
                        missing_fields[field] += 1
            except: pass
        if total_meta > 3000: break
    results["4.2_元数据缺失"] = dict(missing_fields)
    print(f"  抽样{total_meta}个，缺失字段: {dict(missing_fields)}")

    # ===== 4.3 日期格式一致性 =====
    print("\n[6/13] 4.3 日期格式一致性...", flush=True)
    date_bad = 0
    date_total = 0
    for dp, _, fns in os.walk(SRC):
        for fn in fns:
            if not fn.lower().endswith(".md"): continue
            date_total += 1
            if date_total > 3000: break
            try:
                with open(os.path.join(dp, fn), encoding="utf-8", errors="replace") as f:
                    head = f.read(500)
                m = re.search(r"^date:\s*['\"]?(\S+)", head, re.M)
                if m:
                    d = m.group(1).strip("'\"")
                    if not re.match(r'^\d{4}-\d{2}-\d{2}$', d):
                        date_bad += 1
            except: pass
        if date_total > 3000: break
    results["4.3_日期格式异常"] = date_bad
    print(f"  抽样{date_total}个，日期格式异常: {date_bad}")

    # ===== 4.4 机关名称一致性 =====
    print("\n[7/13] 4.4 机关名称一致性...", flush=True)
    agency_variants = defaultdict(set)
    with open(CSV_MANIFEST, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            an = r.get("agency_name", "").strip()
            if an:
                # 提取核心机关名
                core = re.sub(r"(含原.*?委员会|已变更|已撤销|已合并)", "", an).strip()
                agency_variants[core].add(an)
    
    multi_variants = {k: v for k, v in agency_variants.items() if len(v) > 1}
    results["4.4_机关名称变体"] = len(multi_variants)
    print(f"  有多个变体的机关: {len(multi_variants)}")
    for k, v in list(multi_variants.items())[:5]:
        print(f"    {k}: {v}")

    # ===== 6.2 源材料内嵌链接（抽样）=====
    print("\n[8/13] 6.2 源材料内嵌链接...", flush=True)
    all_urls = []
    url_count = 0
    for dp, _, fns in os.walk(SRC):
        for fn in fns:
            if not fn.lower().endswith(".md"): continue
            url_count += 1
            if url_count > 500: break
            try:
                with open(os.path.join(dp, fn), encoding="utf-8", errors="replace") as f:
                    text = f.read()
                urls = URL_RE.findall(text)
                all_urls.extend(urls)
            except: pass
        if url_count > 500: break
    unique_urls = set(all_urls)
    results["6.2_内嵌链接"] = f"{len(unique_urls)}个不同URL（{url_count}文件抽样）"
    print(f"  {url_count}文件抽样，{len(unique_urls)}个不同URL")

    # ===== 8.1 registry文件大小 =====
    print("\n[9/13] 8.1 registry文件大小...", flush=True)
    reg_size = os.path.getsize(REG_FILE) if os.path.exists(REG_FILE) else 0
    evid_sizes = []
    for fn in os.listdir(EVID_DIR):
        if fn.endswith(".json"):
            evid_sizes.append(os.path.getsize(os.path.join(EVID_DIR, fn)))
    results["8.1_registry"] = f"registry.json={reg_size/1024:.1f}KB, evidence={len(evid_sizes)}个/{sum(evid_sizes)/1024:.1f}KB"
    print(f"  registry.json: {reg_size/1024:.1f}KB")
    print(f"  evidence json: {len(evid_sizes)}个, {sum(evid_sizes)/1024:.1f}KB")

    # ===== 8.3 CI超时风险 =====
    print("\n[10/13] 8.3 CI超时风险...", flush=True)
    ci_yml = os.path.join(REPO, ".github", "workflows", "ci.yml")
    ci_timeout = "?"
    if os.path.exists(ci_yml):
        with open(ci_yml, encoding="utf-8") as f:
            text = f.read()
        m = re.search(r"timeout-minutes:\s*(\d+)", text)
        if m:
            ci_timeout = f"{m.group(1)}分钟"
    results["8.3_CI超时"] = ci_timeout
    print(f"  CI timeout: {ci_timeout}")

    # ===== 8.4 WJBS编码合规 =====
    print("\n[11/13] 8.4 WJBS编码合规...", flush=True)
    wjbs_bad = 0
    wjbs_total = 0
    with open(CSV_MANIFEST, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            wjbs = r.get("WJBS", "").strip()
            if not wjbs: continue
            wjbs_total += 1
            # 验证格式：1.2.156.3005.6-<10位机关码><8位日期><4位顺序码>
            if not re.match(r'^1\.2\.156\.3005\.6-\d{31}$', wjbs):
                wjbs_bad += 1
    results["8.4_WJBS不合规"] = f"{wjbs_bad}/{wjbs_total}"
    print(f"  WJBS不合规: {wjbs_bad}/{wjbs_total}")

    # ===== 10.2 地域覆盖均衡性 =====
    print("\n[12/13] 10.2 地域覆盖均衡性...", flush=True)
    province_count = Counter()
    for dp, _, fns in os.walk(FORMAL):
        for fn in fns:
            if not fn.lower().endswith(".md"): continue
            rel = os.path.relpath(os.path.join(dp, fn), FORMAL)
            parts = rel.split(os.sep)
            if len(parts) >= 2:
                cat = parts[0]
                if "地方" in cat or "05_" in cat or "06_" in cat:
                    # 尝试从路径提取省份
                    for part in parts:
                        for prov in ["北京","上海","天津","重庆","广东","江苏","浙江","山东","河北","山西",
                                     "河南","湖北","湖南","海南","陕西","辽宁","吉林","黑龙江","内蒙古",
                                     "安徽","江西","福建","广西","贵州","云南","四川","西藏","甘肃",
                                     "青海","宁夏","新疆"]:
                            if prov in part:
                                province_count[prov] += 1
                                break
    results["10.2_省份分布"] = dict(province_count.most_common())
    print(f"  地方立法/规章省份分布（前10）:")
    for k, v in province_count.most_common(10):
        print(f"    {k}: {v}")
    print(f"  最少: {province_count.most_common()[-1] if province_count else 'N/A'}")

    # ===== 10.3 断档分析 =====
    print("\n[13/13] 10.3 断档分析...", flush=True)
    year_count = Counter()
    for dp, _, fns in os.walk(FORMAL):
        for fn in fns:
            if not fn.lower().endswith(".md"): continue
            m = re.search(r'_(\d{4})-\d{2}-\d{2}_', fn)
            if m:
                year_count[m.group(1)] += 1
    
    years = sorted(year_count.keys())
    gaps = []
    for i in range(1, len(years)):
        y1, y2 = int(years[i-1]), int(years[i])
        if y2 - y1 > 1:
            gaps.append((years[i-1], years[i], year_count[years[i-1]], year_count[years[i]]))
    results["10.3_断档"] = gaps
    print(f"  年份范围: {years[0]}~{years[-1]}")
    print(f"  断档（中间缺年份）: {len(gaps)}")
    for y1, y2, c1, c2 in gaps:
        print(f"    {y1}({c1}) → {y2}({c2})")

    # ===== 生成报告 =====
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    report = os.path.join(BASE, f"audit_remaining_{ts}.md")
    with open(report, 'w', encoding='utf-8') as f:
        f.write(f"# 全库审计 - 剩余13项完成报告\n\n")
        f.write(f"**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write("## 1.2 废止→应有效\n\n")
        f.write(f"- 标'废止/失效'的文件: **{len(abandoned_valid)}** 个\n")
        f.write(f"- 需企查查验证是否真的废止（本轮未逐条验证）\n\n")
        
        f.write("## 1.3 效力与清单不一致\n\n")
        f.write(f"- 正式md vs 编码清单效力不一致: **{effect_mismatch}** 个\n\n")
        
        f.write("## 2.3 内容一致性（500抽样）\n\n")
        f.write(f"- 500抽样内容不一致: **{sample_mismatch}** 个\n\n")
        
        f.write("## 3.4 UTF-8 BOM\n\n")
        f.write(f"- BOM文件: **{bom_count}** 个\n\n")
        
        f.write("## 4.2 元数据字段完整性\n\n")
        f.write(f"- 抽样 {total_meta} 个源材料md\n")
        for field, cnt in missing_fields.items():
            f.write(f"- 缺 `{field}`: {cnt} 个 ({cnt/total_meta*100:.1f}%)\n")
        f.write("\n")
        
        f.write("## 4.3 日期格式一致性\n\n")
        f.write(f"- 抽样 {total_meta} 个，日期格式异常: **{date_bad}** 个\n\n")
        
        f.write("## 4.4 机关名称一致性\n\n")
        f.write(f"- 有多个变体的机关: **{len(multi_variants)}** 个\n")
        for k, v in list(multi_variants.items())[:10]:
            f.write(f"  - {k}: {', '.join(v)}\n")
        f.write("\n")
        
        f.write("## 6.2 源材料内嵌链接\n\n")
        f.write(f"- {url_count} 文件抽样，{len(unique_urls)} 个不同URL\n\n")
        
        f.write("## 8.1 registry文件大小\n\n")
        f.write(f"- registry.json: {reg_size/1024:.1f}KB\n")
        f.write(f"- evidence json: {len(evid_sizes)}个, {sum(evid_sizes)/1024:.1f}KB\n\n")
        
        f.write("## 8.3 CI超时风险\n\n")
        f.write(f"- CI timeout: {ci_timeout}\n\n")
        
        f.write("## 8.4 WJBS编码合规\n\n")
        f.write(f"- WJBS不合规: **{wjbs_bad}/{wjbs_total}**\n\n")
        
        f.write("## 10.2 地域覆盖均衡性\n\n")
        f.write("| 省份 | 数量 |\n|---|---|\n")
        for k, v in province_count.most_common():
            f.write(f"| {k} | {v} |\n")
        f.write("\n")
        
        f.write("## 10.3 断档分析\n\n")
        f.write(f"- 年份范围: {years[0]}~{years[-1]}\n")
        f.write(f"- 断档: {len(gaps)} 处\n")
        for y1, y2, c1, c2 in gaps:
            f.write(f"  - {y1}({c1}) → {y2}({c2})\n")
    
    print(f"\n报告: {report}")
    print("=" * 60)
    print("完成")
    print("=" * 60)

if __name__ == '__main__':
    main()
