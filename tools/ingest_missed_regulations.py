"""从 gov.cn 政策库候选补抓部门规章入库（未命中候选 STRONG 类）。

流程：
1. 读更新器候选 CSV（官网有_正式区未命中候选.csv）
2. STRONG 判定（标题启发式：办法/规定/条例/细则/规则等结尾，排除个案批复/一般通知）
3. 与源材料比对，过滤已有
4. 下载官方 URL → 提取 pages_content 正文 → 生成标准 md → 写入源材料

用法：python tools/ingest_missed_regulations.py <候选CSV>
"""
import csv
import json
import os
import re
import sys
import urllib.request
from collections import Counter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "workspace", "source", "legal-references")
TMP = os.path.join(REPO, "workspace", "tmp", "gov_candidates")
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
}


def classify_level(title: str) -> tuple:
    """返回 (级别, 理由)。STRONG=应收规章/规范性文件。"""
    t2 = re.sub(r"[《》（）()\[\]．.。]", "", title)
    if re.search(r"(批复|复函|函)$", t2) or re.search(r"关于.*(批复|复函)的", t2):
        return "EXCLUDE", "个案批复/复函"
    if re.search(r"关于.*(开展|做好|加强|推进|组织|实施|贯彻|落实|征求).*工作的通知?$", t2):
        return "EXCLUDE", "一般工作通知"
    if re.search(r"(办法|规定|条例|细则|规则|实施办法|暂行规定|若干规定|管理规定|监督管理办法)$", t2):
        return "STRONG", "规章/规范性文件核心"
    return "OTHER", "其他"


def norm(s: str) -> str:
    return re.sub(r"[《》（）()\[\]．.。\s]", "", s)


def src_titles() -> set:
    titles = set()
    for dp, _, fns in os.walk(SRC):
        for fn in fns:
            if fn.lower().endswith(".md"):
                titles.add(norm(os.path.splitext(fn)[0]))
    return titles


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def extract_body(html: str) -> str:
    m = re.search(r'<div class="pages_content"[^>]*>(.*?)</div>\s*</div>', html, re.S)
    if not m:
        m = re.search(r'<div class="pages_content"[^>]*>(.*?)<!--', html, re.S)
    body = m.group(1) if m else html
    body = re.sub(r"<script.*?</script>", "", body, flags=re.S)
    body = re.sub(r"<style.*?</style>", "", body, flags=re.S)
    body = re.sub(r"<br\s*/?>", "\n", body)
    body = re.sub(r"</p>|</div>|</tr>|</h\d>", "\n", body)
    body = re.sub(r"<[^>]+>", "", body)
    body = re.sub(r"&nbsp;", " ", body)
    body = re.sub(r"&ldquo;|&rdquo;", "“", body)
    body = re.sub(r"&mdash;", "—", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def pick_agency(title: str) -> str:
    """从标题提取部委名做目录归类。"""
    for kw in ["海关总署", "中国人民银行", "人民银行", "工业和信息化部", "交通运输部", "市场监管总局",
               "商务部", "证监会", "体育总局", "农业农村部", "自然资源部", "住房和城乡建设部", "民航局",
               "国家发展改革委", "发展改革委", "生态环境部", "教育部", "民政部", "银保监会", "金融监管总局"]:
        if kw in title:
            return kw
    return "其他部委"


def make_md(title: str, pub_date: str, url: str, body: str, agency: str) -> str:
    m = re.search(r"content_(\d+)\.htm", url)
    cid = m.group(1) if m else "unknown"
    status = "有效"
    return f"""---
id: gov-content_{cid}
title: {title}
LinkTitle: {title}（{pub_date[:4]}）
file: {title}_{pub_date.replace('.', '')}_gov.cn.docx
author: {agency}
date: '{pub_date.replace('.', '-')}'
publication_date: '{pub_date.replace('.', '-')}'
effective_date: ''
status: {status}
group: 部门规章
categories:
  - 部门规章
tags:
  - {agency}
  - {status}
years:
  - {pub_date[:4]}年
keywords:
  - {title[:12]}
urls:
  - {url}
---

# {title}

{body}
"""


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python tools/ingest_missed_regulations.py <候选CSV>")
        return 1
    csv_path = sys.argv[1]
    rows = [r for r in csv.DictReader(open(csv_path, encoding="utf-8-sig")) if r["title"] and r["publication_date"]]

    strong = [r for r in rows if classify_level(r["title"])[0] == "STRONG"]
    print(f"STRONG 规章类: {len(strong)}")

    known = src_titles()
    todo = [r for r in strong if not any(norm(r["title"])[:10] in s or s[:10] in norm(r["title"]) for s in known)]
    print(f"真缺（源材料无）: {len(todo)}")

    os.makedirs(TMP, exist_ok=True)
    ok, fail = [], []
    for i, r in enumerate(todo, 1):
        title, url = r["title"], r["official_url"]
        print(f"[{i}/{len(todo)}] {title[:40]}...")
        try:
            html = fetch(url)
            body = extract_body(html)
            if len(body) < 100:
                fail.append((title, "正文过短"))
                continue
            agency = pick_agency(title)
            pub_date = r["publication_date"]
            md = make_md(title, pub_date, url, body, agency)
            # 目标目录：01_立法与公开行政文件/04_规章/01_部门规章/<部委>/
            tgt_dir = os.path.join(SRC, "01_立法与公开行政文件", "04_规章", "01_部门规章", agency)
            os.makedirs(tgt_dir, exist_ok=True)
            fname = f"{title}_{pub_date.replace('.', '-')}_有效_gov-content-{url.split('content_')[1].split('.')[0]}.md"
            fname = re.sub(r'[\\/:*?"<>|]', "_", fname)
            with open(os.path.join(tgt_dir, fname), "w", encoding="utf-8") as f:
                f.write(md)
            ok.append(title)
        except Exception as e:  # noqa: BLE001
            fail.append((title, str(e)[:80]))

    print(f"\n成功: {len(ok)} | 失败: {len(fail)}")
    for t, why in fail[:15]:
        print(f"  ❌ {t[:45]} | {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
