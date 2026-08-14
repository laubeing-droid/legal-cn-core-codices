#!/usr/bin/env python3
"""全库审计 - 综合版：一次遍历完成所有纯本地检查项"""
import os, re, json, hashlib, time, csv, sys
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
AGENTS_MD = os.path.join(BASE, "AGENTS.md")
HANDOFF = os.path.join(BASE, "20260807_legal-cn-core-codices_Handoff.md")

EFFECT_RE = re.compile(r'_(有效|失效|废止|已被修订|部分失效废止|尚未生效|草案)_')
TITLE_DATE_RE = re.compile(r'^(.+?)_(\d{4}-\d{2}-\d{2})_')
WJBS_RE = re.compile(r'^1\.2\.156\.3005\.6-\d{10}\d{8}\d{4}')
WZWS_RE = re.compile(r'WZWS|nurl|cfesc|challenge|javascript|验证|您需要先完成|访问验证', re.I)
YEAR_RE = re.compile(r'_(\d{4})-\d{2}-\d{2}_')
CAT_RE = re.compile(r'^(\d{2})_')

def scan_all_formal():
    """一次遍历正式目录，收集所有需要的数据"""
    results = {
        'files': [],           # (rel_path, basename, full_path)
        'sha256': {},          # rel_path -> sha256
        'effect': Counter(),   # 效力状态
        'wzws': [],            # 含WZWS的文件
        'short': [],           # 正文<200字符
        'years': Counter(),    # 年份分布
        'cats': Counter(),     # 分类分布
        'titles': {},          # rel_path -> title
        'no_effect': [],       # 无效力标记
        'content_hashes': defaultdict(list),  # hash -> [rel_paths]
    }
    
    total = 0
    t0 = time.time()
    for dp, _, fns in os.walk(FORMAL):
        for fn in fns:
            if not fn.lower().endswith(".md"):
                continue
            total += 1
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, FORMAL)
            
            # 分类
            parts = rel.split(os.sep)
            if parts:
                m = CAT_RE.match(parts[0])
                if m:
                    results['cats'][m.group(1)] += 1
            
            # 效力状态
            m = EFFECT_RE.search(fn)
            if m:
                results['effect'][m.group(1)] += 1
            else:
                results['no_effect'].append(rel)
            
            # 年份
            m = YEAR_RE.search(fn)
            if m:
                results['years'][m.group(1)] += 1
            
            # 标题
            m = TITLE_DATE_RE.match(fn)
            if m:
                results['titles'][rel] = m.group(1)
            
            # 读取内容（一次读取完成 sha256 + WZWS + 正文长度）
            try:
                with open(full, 'rb') as f:
                    raw = f.read()
                sha = hashlib.sha256(raw).hexdigest()
                results['sha256'][rel] = sha
                results['content_hashes'][sha].append(rel)
                
                text = raw.decode('utf-8', errors='replace')
                if WZWS_RE.search(text[:3000]):
                    results['wzws'].append(rel)
                if len(text.strip()) < 200:
                    results['short'].append(rel)
            except:
                pass
            
            if total % 5000 == 0:
                print(f"  扫描进度: {total} ({time.time()-t0:.0f}s)", flush=True)
    
    results['total'] = total
    return results

def check_registry(formal_sha):
    """检查 registry 一致性"""
    reg = json.load(open(REG_FILE, encoding='utf-8-sig'))
    entries = reg['entries']
    
    missing_evidence = []
    sha_mismatch = []
    url_set = set()
    url_empty = 0
    
    for e in entries:
        ep = e.get('evidence_path', '')
        if ep and not os.path.exists(os.path.join(EVID_DIR, ep)):
            missing_evidence.append(ep)
        
        src_sha = e.get('source_sha256', '')
        # source_sha256 对应的源材料路径无法直接确定，跳过逐条比对
        # 但记录有多少条有 sha256
        if not src_sha:
            sha_mismatch.append(e.get('evidence_path', ''))
        
        url = e.get('official_url', '')
        if url:
            url_set.add(url)
        else:
            url_empty += 1
    
    return {
        'total': len(entries),
        'missing_evidence': missing_evidence,
        'no_sha256': len(sha_mismatch),
        'unique_urls': len(url_set),
        'empty_urls': url_empty,
        'urls': url_set,
    }

def check_corpus_sync(formal_files):
    """检查 corpus 同步状态"""
    corpus_set = set()
    for dp, _, fns in os.walk(CORPUS):
        for fn in fns:
            if fn.lower().endswith(".md"):
                corpus_set.add(os.path.relpath(os.path.join(dp, fn), CORPUS))
    
    formal_set = set(formal_files)
    only_formal = formal_set - corpus_set
    only_corpus = corpus_set - formal_set
    
    return {
        'formal_count': len(formal_set),
        'corpus_count': len(corpus_set),
        'only_formal': len(only_formal),
        'only_corpus': len(only_corpus),
    }

def check_source_coverage(formal_titles):
    """检查源材料覆盖率（数据血缘）"""
    src_titles = {}
    for dp, _, fns in os.walk(SRC):
        for fn in fns:
            if fn.lower().endswith(".md"):
                m = TITLE_DATE_RE.match(fn)
                if m:
                    src_titles[m.group(1)] = os.path.relpath(os.path.join(dp, fn), SRC)
    
    # 正式目录标题 vs 源材料标题
    formal_t = set(formal_titles.values())
    src_t = set(src_titles.keys())
    covered = formal_t & src_t
    
    return {
        'formal_titles': len(formal_t),
        'src_titles': len(src_t),
        'covered': len(covered),
        'coverage_pct': len(covered) / max(len(formal_t), 1) * 100,
    }

def check_docs():
    """检查文档完整性"""
    docs = {
        'AGENTS.md': AGENTS_MD,
        'Handoff': HANDOFF,
        'README': os.path.join(REPO, 'README.md'),
        'memory.md': os.path.join(BASE, '.workbuddy', 'memory', 'MEMORY.md'),
    }
    found = {}
    for name, path in docs.items():
        found[name] = os.path.exists(path)
    
    # AGENTS.md 内容检查
    agents_sections = []
    if os.path.exists(AGENTS_MD):
        with open(AGENTS_MD, encoding='utf-8') as f:
            text = f.read()
        agents_sections = re.findall(r'^##\s+(.+)', text, re.M)
    
    return {
        'docs': found,
        'agents_sections': agents_sections,
    }

def check_coverage(formal_cats, formal_years):
    """覆盖率与时效性统计"""
    return {
        'cats': dict(formal_cats.most_common()),
        'years': dict(sorted(formal_years.items())),
        'year_range': (min(formal_years.keys()) if formal_years else '?',
                       max(formal_years.keys()) if formal_years else '?'),
    }

def check_invisible_chars():
    """检查文件名不可见字符"""
    inv = []
    for dp, _, fns in os.walk(FORMAL):
        for fn in fns:
            if not fn.lower().endswith(".md"):
                continue
            for ch in fn:
                if ord(ch) < 32 or ch in '\u200b\u200c\u200d\ufeff\u00a0':
                    inv.append(os.path.relpath(os.path.join(dp, fn), FORMAL))
                    break
    return inv

def main():
    print("=" * 60)
    print("全库审计 - 综合版")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # ===== 1. 正式目录全量扫描 =====
    print("\n[1/8] 正式目录全量扫描...", flush=True)
    t0 = time.time()
    formal = scan_all_formal()
    print(f"  完成: {formal['total']} 文件, {time.time()-t0:.0f}s")
    
    # ===== 2. 内容重复 =====
    print("\n[2/8] 内容重复检查...", flush=True)
    dups = {h: paths for h, paths in formal['content_hashes'].items() if len(paths) > 1}
    print(f"  重复组: {len(dups)}")
    
    # ===== 3. 文件名不可见字符 =====
    print("\n[3/8] 文件名不可见字符...", flush=True)
    inv_chars = check_invisible_chars()
    print(f"  含不可见字符: {len(inv_chars)}")
    
    # ===== 4. registry 一致性 =====
    print("\n[4/8] registry 一致性...", flush=True)
    reg_check = check_registry(formal['sha256'])
    print(f"  entries: {reg_check['total']}, 缺evidence: {len(reg_check['missing_evidence'])}")
    
    # ===== 5. corpus 同步 =====
    print("\n[5/8] corpus 同步状态...", flush=True)
    sync = check_corpus_sync(list(formal['files']))
    # 用 sha256 keys 作为文件列表
    sync = check_corpus_sync(list(formal['sha256'].keys()))
    print(f"  正式: {sync['formal_count']}, corpus: {sync['corpus_count']}")
    print(f"  仅正式: {sync['only_formal']}, 仅corpus: {sync['only_corpus']}")
    
    # ===== 6. 源材料覆盖率 =====
    print("\n[6/8] 源材料覆盖率（数据血缘）...", flush=True)
    coverage = check_source_coverage(formal['titles'])
    print(f"  覆盖率: {coverage['coverage_pct']:.1f}% ({coverage['covered']}/{coverage['formal_titles']})")
    
    # ===== 7. 文档完整性 =====
    print("\n[7/8] 文档完整性...", flush=True)
    docs = check_docs()
    for name, exists in docs['docs'].items():
        print(f"  {name}: {'✅' if exists else '❌'}")
    
    # ===== 8. 覆盖率与时效性 =====
    print("\n[8/8] 覆盖率与时效性...", flush=True)
    cov = check_coverage(formal['cats'], formal['years'])
    
    # ===== 生成报告 =====
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    report = os.path.join(BASE, f"audit_final_{ts}.md")
    
    with open(report, 'w', encoding='utf-8') as f:
        f.write(f"# 全库审计综合报告\n\n")
        f.write(f"**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write("## 1. 内容重复\n\n")
        f.write(f"- 正式 md 总数: {formal['total']}\n")
        f.write(f"- 内容重复组: **{len(dups)}** {'✅' if len(dups)==0 else '⚠️'}\n\n")
        
        f.write("## 2. 文件名不可见字符\n\n")
        f.write(f"- 含不可见字符: **{len(inv_chars)}** 个\n")
        if inv_chars:
            for p in inv_chars[:20]:
                f.write(f"  - `{p}`\n")
            if len(inv_chars) > 20:
                f.write(f"  - ... 共 {len(inv_chars)} 个\n")
        f.write("\n")
        
        f.write("## 3. 效力状态分布\n\n")
        f.write("| 状态 | 数量 |\n|---|---|\n")
        for k, v in formal['effect'].most_common():
            f.write(f"| {k} | {v} |\n")
        f.write(f"| 无法识别 | {len(formal['no_effect'])} |\n\n")
        
        f.write("## 4. WZWS 挑战页\n\n")
        f.write(f"- 含 WZWS/script 标记: **{len(formal['wzws'])}** 个\n")
        if formal['wzws']:
            for p in formal['wzws'][:20]:
                f.write(f"  - `{p}`\n")
            if len(formal['wzws']) > 20:
                f.write(f"  - ... 共 {len(formal['wzws'])} 个\n")
        f.write("\n")
        
        f.write("## 5. 正文过短\n\n")
        f.write(f"- 正文 <200 字符: **{len(formal['short'])}** 个\n\n")
        
        f.write("## 6. registry 一致性\n\n")
        f.write(f"- entries 总数: {reg_check['total']}\n")
        f.write(f"- 缺 evidence 文件: {len(reg_check['missing_evidence'])} {'✅' if len(reg_check['missing_evidence'])==0 else '⚠️'}\n")
        f.write(f"- 无 source_sha256: {reg_check['no_sha256']}\n")
        f.write(f"- 不同 official_url 数: {reg_check['unique_urls']}\n")
        f.write(f"- 空 official_url: {reg_check['empty_urls']}\n\n")
        
        f.write("## 7. corpus 同步\n\n")
        f.write(f"- 正式目录: {sync['formal_count']}\n")
        f.write(f"- repo/corpus: {sync['corpus_count']}\n")
        f.write(f"- 仅正式: {sync['only_formal']} {'✅' if sync['only_formal']==0 else '⚠️'}\n")
        f.write(f"- 仅corpus: {sync['only_corpus']} {'✅' if sync['only_corpus']==0 else '⚠️'}\n\n")
        
        f.write("## 8. 数据血缘（源材料覆盖率）\n\n")
        f.write(f"- 正式标题数: {coverage['formal_titles']}\n")
        f.write(f"- 源材料标题数: {coverage['src_titles']}\n")
        f.write(f"- 覆盖率: **{coverage['coverage_pct']:.1f}%** ({coverage['covered']}/{coverage['formal_titles']})\n\n")
        
        f.write("## 9. 文档完整性\n\n")
        for name, exists in docs['docs'].items():
            f.write(f"- {name}: {'✅' if exists else '❌'}\n")
        f.write(f"- AGENTS.md 章节: {', '.join(docs['agents_sections'][:10])}\n\n")
        
        f.write("## 10. 覆盖率与时效性\n\n")
        f.write("### 分类分布\n\n")
        f.write("| 分类 | 数量 |\n|---|---|\n")
        for k, v in cov['cats'].items():
            f.write(f"| {k} | {v} |\n")
        f.write(f"\n### 年份范围: {cov['year_range'][0]} ~ {cov['year_range'][1]}\n\n")
        f.write("| 年份 | 数量 |\n|---|---|\n")
        for k, v in list(cov['years'].items())[-20:]:  # 最近20年
            f.write(f"| {k} | {v} |\n")
    
    print(f"\n报告已写入: {report}")
    
    # 保存 URLs 供 Phase 2 使用
    urls_file = os.path.join(BASE, "audit_urls.txt")
    with open(urls_file, 'w', encoding='utf-8') as f:
        for url in sorted(reg_check['urls']):
            f.write(url + '\n')
    print(f"URLs 已写入: {urls_file} ({len(reg_check['urls'])} 个)")
    
    # 保存 WZWS 列表
    wzws_file = os.path.join(BASE, "audit_wzws.txt")
    with open(wzws_file, 'w', encoding='utf-8') as f:
        for p in formal['wzws']:
            f.write(p + '\n')
    print(f"WZWS 列表已写入: {wzws_file} ({len(formal['wzws'])} 个)")
    
    # 保存正文过短列表
    short_file = os.path.join(BASE, "audit_short.txt")
    with open(short_file, 'w', encoding='utf-8') as f:
        for p in formal['short']:
            f.write(p + '\n')
    print(f"正文过短列表已写入: {short_file} ({len(formal['short'])} 个)")
    
    print("\n" + "=" * 60)
    print("审计完成")
    print("=" * 60)

if __name__ == '__main__':
    main()
