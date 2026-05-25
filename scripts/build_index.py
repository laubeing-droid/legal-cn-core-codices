#!/usr/bin/env python3
"""Build INDEX.md dynamically from all JSON files. Works on any platform."""
import json, os, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_meta(path):
    with open(path, "r", encoding="utf-8") as f:
        j = json.load(f)
    name = j.get("name", j.get("title", "?"))
    short = j.get("short_name", "")
    arts = j.get("article_count", len(j.get("articles", [])))
    effective = j.get("effective", j.get("promulgated", ""))
    domains = j.get("domains", [])
    return name, short, arts, effective, domains

def main():
    lines = ["# 中国法律知识库 · 完整目录", "", f"> 自动生成 · {len(sys.argv)} args", ""]
    
    total = 0
    for cat in ["laws", "interpretations", "guidance", "regulations"]:
        d = os.path.join(REPO, cat)
        if not os.path.isdir(d):
            continue
        files = sorted([f for f in os.listdir(d) if f.endswith(".json")])
        total += len(files)
        lines.append(f"## {cat} ({len(files)})")
        lines.append("")
        lines.append("| 文件 | 简称 | 条数 | 施行日期 | 领域 |")
        lines.append("|:--|:--|:--|:--|:--|")
        for fname in files:
            name, short, arts, eff, domains = load_meta(os.path.join(d, fname))
            lines.append(f"| {fname} | {short} | {arts} | {eff} | {', '.join(domains[:3])} |")
        lines.append("")
    
    lines.insert(1, f"> 总计: {total} 部法律法规及司法解释")
    
    outpath = os.path.join(REPO, "INDEX.md")
    with open(outpath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"INDEX.md written ({total} files)")

if __name__ == "__main__":
    main()
