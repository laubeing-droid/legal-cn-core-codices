"""从 gov.cn 政策库候选补抓部门规章入库（未命中候选 STRONG 类）。

流程：
1. 读更新器候选 CSV（官网有_正式区未命中候选.csv）
2. STRONG 判定（标题启发式：办法/规定/条例/细则/规则等结尾，排除个案批复/一般通知）
3. 与源材料比对，过滤已有
4. 下载官方 URL → OfficialBodyParser 提取正文（复用更新器实现）→ 标准 md → 写入源材料

正文提取与官方更新器一致（official-source-updater/scripts/fetch_fulltext_queue.py 的
OfficialBodyParser：HTMLParser 解析，忽略 nav/footer/script/style，识别 TRS_Editor 等
正文容器，取最长块）。不用正则抓 pages_content——gov.cn 有正文页/详情页两种形态，
正则非贪婪截断会混入导航面包屑。

用法：
  python tools/ingest_missed_regulations.py <候选CSV>            # 补抓新模式
  python tools/ingest_missed_regulations.py <候选CSV> --rematerialize   # 重抓已入库（修复正文污染）
"""
import csv
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "workspace", "source", "legal-references")
TMP = os.path.join(REPO, "workspace", "tmp", "gov_candidates")
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
}

# ===== 复用官方更新器的正文解析器（fetch_fulltext_queue.py 同款） =====


class OfficialBodyParser(HTMLParser):
    BLOCK_TAGS = {
        "article", "br", "dd", "div", "dl", "dt", "h1", "h2", "h3",
        "h4", "li", "main", "p", "section", "table", "td", "th", "tr",
    }
    IGNORED_TAGS = {"footer", "nav", "noscript", "script", "style"}
    CONTAINER_IDS = {"UCAP-CONTENT"}
    CONTAINER_CLASSES = {
        "TRS_Editor", "article-content", "detail", "detail_con", "txt", "wsfbh_detail_con", "zoom",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.ignored_depths: list[int] = []
        self.active: list[dict] = []
        self.completed: list[str] = []

    def _ignored(self) -> bool:
        return bool(self.ignored_depths)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.depth += 1
        if tag in self.IGNORED_TAGS:
            self.ignored_depths.append(self.depth)
        if not self._ignored():
            if tag in self.BLOCK_TAGS:
                for capture in self.active:
                    capture["parts"].append("\n")
            attributes = {name: value or "" for name, value in attrs}
            class_names = set(attributes.get("class", "").split())
            is_container = (
                attributes.get("id") in self.CONTAINER_IDS
                or bool(class_names & self.CONTAINER_CLASSES)
                or tag in {"article", "main"}
            )
            if is_container:
                self.active.append({"depth": self.depth, "parts": []})

    def handle_endtag(self, tag: str) -> None:
        if not self._ignored() and tag in self.BLOCK_TAGS:
            for capture in self.active:
                capture["parts"].append("\n")
        ending = [capture for capture in self.active if capture["depth"] == self.depth]
        for capture in ending:
            text = "".join(capture["parts"])
            text = re.sub(r"[ \t\u3000]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text)
            text = text.strip()
            if text:
                self.completed.append(text)
            self.active.remove(capture)
        if self.ignored_depths and self.ignored_depths[-1] == self.depth:
            self.ignored_depths.pop()
        self.depth = max(0, self.depth - 1)

    def handle_data(self, data: str) -> None:
        if not self._ignored():
            for capture in self.active:
                capture["parts"].append(data)


def extract_body(html: str) -> str:
    parser = OfficialBodyParser()
    parser.feed(html)
    parser.close()
    body = max(parser.completed, key=len, default="")
    if len(body) >= 100:
        return body
    return extract_body_fallback(html)


def extract_body_fallback(html: str) -> str:
    """老版详情页（无正文容器 class）：正文是裸 <p> 段落。

    定位'附件'/'现予公布'等正文起点标记后提取全部 p 标签，并截断
    尾部导航垃圾（责任编辑/扫码/版权所有等）。
    """
    start = 0
    for marker in ["附件：", "附件:", "附件\n", ">附件<", "现予公布", "现予发布"]:
        idx = html.find(marker)
        if idx > 0:
            start = idx
            break
    seg = html[start:]
    paras = re.findall(r"<p[^>]*>(.*?)</p>", seg, re.S)
    out = []
    for p in paras:
        t = re.sub(r"<[^>]+>", "", p)
        t = t.replace("&nbsp;", " ").replace("\u3000", " ")
        t = re.sub(r"[ \t]+", " ", t)
        t = t.strip()
        if len(t) >= 3:
            out.append(t)
    body = "\n".join(out)
    body = re.sub(r"\n{3,}", "\n\n", body)
    cut = re.search(r"(责任编辑|扫一扫在手机打开当前页|链接：|友情链接|全国人大|全国政协|国家监察委员会|返回顶部|版权所有|京ICP备|网站地图|联系我们)", body)
    if cut:
        body = body[:cut.start()]
    return body.strip()


def strip_page_footer(body: str) -> str:
    """截断页脚导航/链接栏残留（gov.cn 详情页尾部）。"""
    cut = re.search(
        r"(扫一扫在手机打开当前页|链接：|友情链接|全国人大|全国政协|国家监察委员会|"
        r"返回顶部|版权所有|京ICP备|网站地图|联系我们|政府网站找错|国务院部门网站|"
        r"中央人民政府门户网站|关于我们|网站声明|设为首页|加入收藏)",
        body,
    )
    if cut:
        body = body[: cut.start()]
    return body.strip()


def markdown_body(text: str) -> str:
    """章→##、条→###、【】→##，与更新器物化一致。"""
    output: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if re.fullmatch(r"第[一二三四五六七八九十百千]+章.*", line):
            line = f"## {line}"
        elif re.match(r"^第[一二三四五六七八九十百千\d]+条(?:\s|$)", line):
            line = f"### {line}"
        elif re.fullmatch(r"【[^】]+】", line):
            line = f"## {line[1:-1]}"
        output.append(line)
    return strip_page_footer(re.sub(r"\n{3,}", "\n\n", "\n".join(output)).strip())


def extract_document_number(text: str) -> str:
    head = text[:3000].replace("\u3000", " ")
    order_matches = list(re.finditer(
        r"((?:中华人民共和国)?(?:国务院|[\u4e00-\u9fff]{2,20}(?:部|总局|委员会|局|署|人民银行))令)\s*第\s*(\d+)\s*号",
        head,
    ))
    if order_matches:
        match = order_matches[-1]
        authority = re.sub(r"^.*日", "", match.group(1))
        return re.sub(r"\s+", "", f"{authority}第{match.group(2)}号")
    document_number = re.search(r"([\u4e00-\u9fff]{1,16}〔\d{4}〕\d+号)", head)
    return document_number.group(1) if document_number else ""


AUTHORITY_FULL_NAMES = {
    "证监会": "中国证券监督管理委员会",
    "中国证监会": "中国证券监督管理委员会",
    "银保监会": "中国银行保险监督管理委员会",
    "银保监": "中国银行保险监督管理委员会",
    "体育总局": "国家体育总局",
    "外汇局": "国家外汇管理局",
    "气象局": "中国气象局",
    "网信办": "国家互联网信息办公室",
    "档案局": "国家档案局",
    "人民银行": "中国人民银行",
    "商务部": "中华人民共和国商务部",
    "海关总署": "中华人民共和国海关总署",
    "民航局": "中国民用航空局",
    "发展改革委": "中华人民共和国国家发展和改革委员会",
    "发展改革": "中华人民共和国国家发展和改革委员会",
    "医保局": "国家医疗保障局",
    "检验检疫局": "国家进出口商品检验局(国家出入境检验检疫局)",
    "知识产权局": "国家知识产权局",
}


def load_agency_names() -> list[str]:
    """从制定机关代码注册表加载全部机关名（按长度降序，最长优先匹配）。"""
    p = os.path.join(REPO, "schema", "制定机关代码注册表.csv")
    names = set()
    with open(p, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            n = row.get("agency_name", "").strip()
            if n:
                names.add(n)
                # 去掉括号变体也加入（"国家进出口商品检验局(国家出入境检验检疫局)" → 两个都收）
                names.update(re.findall(r"[\u4e00-\u9fff]{3,30}", n))
    return sorted(names, key=len, reverse=True)


AGENCY_NAMES: list[str] = load_agency_names()


def extract_authority_from_body(text: str) -> str:
    """提取发布机关全称：优先文号格式，其次注册表/简称映射全文匹配。

    注意：先截掉页脚链接栏，避免把页脚"国家监察委员会|最高人民法院"等误当发布机关。
    """
    head = strip_page_footer(text)[:3000].replace("\u3000", " ")
    head = re.sub(r"\d{4}年\d{1,2}月\d{1,2}日", "", head)
    # 1) 文号格式：机关+令/公告/通告/发布/印发/发〔N〕号
    SUFFIX = r"(?:部|总局|委员会|局|署|人民银行|办公室|办公厅|会)"
    for pat in [
        rf"([\u4e00-\u9fff]{{2,20}}{SUFFIX})令",
        rf"([\u4e00-\u9fff]{{2,20}}{SUFFIX})\s*(?:公告|通告|发布|印发)",
        rf"([\u4e00-\u9fff]{{2,20}}{SUFFIX})\s*发?\s*〔?\d{{4}}〕?\d+\s*号",
    ]:
        m = re.search(pat, head)
        if m:
            name = m.group(1)
            for short, full in AUTHORITY_FULL_NAMES.items():
                if short in name:
                    return full
            # 注册表子串回查
            for full in AGENCY_NAMES:
                if name in full or full in name:
                    return full
            return name
    # 2) 注册表全文最长匹配
    for name in AGENCY_NAMES:
        if name in head:
            return name
    # 3) 简称映射全文匹配（长简称优先）
    for short, full in sorted(AUTHORITY_FULL_NAMES.items(), key=lambda x: -len(x[0])):
        if short in head:
            return full
    return ""


def extract_effective_date(text: str) -> str:
    match = re.search(rf"自\s*(\d{{4}})年(\d{{1,2}})月(\d{{1,2}})日\s*起?\s*(?:施行|实施|执行)", text)
    if not match:
        return ""
    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


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
    doc_number = extract_document_number(body)
    effective = extract_effective_date(body)
    auth = extract_authority_from_body(body) or agency
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"""---
title: "{title}"
FLFGDZWJFLDM: "1300"
author: "{auth}"
promulgation_date: "{pub_date.replace('.', '-')}"
publication_date: "{pub_date.replace('.', '-')}"
effective_date: "{effective}"
status: "{status}"
document_number: "{doc_number}"
official_source_url: "{url}"
official_record_id: "gov-content-{cid}"
verification_status: "OFFICIAL_FULLTEXT_VERIFIED"
fetched_at: "{now}"
---

# {title}

{markdown_body(body)}
"""


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python tools/ingest_missed_regulations.py <候选CSV> [--rematerialize]")
        return 1
    csv_path = sys.argv[1]
    rematerialize = "--rematerialize" in sys.argv
    rows = [r for r in csv.DictReader(open(csv_path, encoding="utf-8-sig")) if r["title"] and r["publication_date"]]

    if rematerialize:
        # 重抓已入库：只处理 gov-content- 前缀文件（本次补抓的），重下载重提取重写
        targets = []
        for dp, _, fns in os.walk(SRC):
            for fn in fns:
                if fn.lower().endswith(".md") and "gov-content" in fn:
                    url = None
                    # 从 frontmatter 拿 official_source_url（新格式）或 urls 列表（旧格式）
                    p = os.path.join(dp, fn)
                    text = open(p, encoding="utf-8").read()
                    um = re.search(r"official_source_url: \"([^\"]+)\"", text)
                    if um:
                        url = um.group(1)
                    else:
                        um2 = re.search(r"urls:\n\s*-\s*(\S+)", text)
                        if um2:
                            url = um2.group(1)
                    targets.append((p, fn, url))
        print(f"重抓目标: {len(targets)} 条 gov-content 文件")
    else:
        strong = [r for r in rows if classify_level(r["title"])[0] == "STRONG"]
        print(f"STRONG 规章类: {len(strong)}")
        known = src_titles()
        todo = [r for r in strong if not any(norm(r["title"])[:10] in s or s[:10] in norm(r["title"]) for s in known)]
        print(f"真缺（源材料无）: {len(todo)}")
        targets = [(None, None, r["official_url"], r["title"], r["publication_date"]) for r in todo]

    os.makedirs(TMP, exist_ok=True)
    ok, fail = [], []
    n = len(targets)

    def process(url: str, title: str, pub_date: str, fname: str | None, tgt_dir: str | None) -> None:
        html = fetch(url)
        body = extract_body(html)
        if len(body) < 100:
            fail.append((title, "正文过短"))
            return
        agency = pick_agency(title)
        md = make_md(title, pub_date, url, body, agency)
        if fname is None:
            d = os.path.join(SRC, "01_立法与公开行政文件", "04_规章", "01_部门规章", agency)
            os.makedirs(d, exist_ok=True)
            fn = f"{title}_{pub_date.replace('.', '-')}_有效_gov-content-{url.split('content_')[1].split('.')[0]}.md"
            fn = re.sub(r'[\\/:*?"<>|]', "_", fn)
        else:
            d = os.path.dirname(fname)
            fn = os.path.basename(fname)
            os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, fn), "w", encoding="utf-8") as f:
            f.write(md)
        ok.append(f"{title[:40]} ({len(body)}字符)")

    for i, t in enumerate(targets, 1):
        if rematerialize:
            p, fn, url = t
            if not url:
                fail.append((fn[:40], "无official_source_url"))
                continue
            # 从旧 frontmatter 拿 title / publication_date（兼容单/双引号）
            text = open(p, encoding="utf-8").read()
            tm = re.search(r'^title: "(.+)"', text, re.M) or re.search(r"^title: '(.+)'", text, re.M)
            title = tm.group(1) if tm else os.path.splitext(fn)[0].split("_")[0]
            # 日期优先从文件名取（标题_YYYY-MM-DD_效力_id.md，文件名日期是原始抓取时正确的）
            fn_date = re.search(r"_(\d{4}-\d{2}-\d{2})_", fn)
            pub_date = fn_date.group(1) if fn_date else "2026-01-01"
            if pub_date == "2026-01-01":
                pm = re.search(r'publication_date: ["\']([^"\']+)["\']', text)
                if pm:
                    pub_date = pm.group(1)
            print(f"[{i}/{n}] 重抓: {fn[:40]}...")
            try:
                process(url, title, pub_date, p, None)
            except Exception as e:  # noqa: BLE001
                fail.append((fn[:40], str(e)[:80]))
        else:
            r = t[3] if len(t) == 5 else None
            print(f"[{i}/{n}] {r['title'][:40]}...")
            try:
                process(t[2], t[3], t[4], None, None)
            except Exception as e:  # noqa: BLE001
                fail.append((t[3][:40], str(e)[:80]))

    print(f"\n成功: {len(ok)} | 失败: {len(fail)}")
    for t, why in fail[:15]:
        print(f"  ❌ {t} | {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
