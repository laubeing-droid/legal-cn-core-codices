import json, os

law_full = r'skills\knowledge-base\law-full'

json_to_name = {
    "civil_code.json": ("中华人民共和国民法典", 1260),
    "lawyer_law.json": ("中华人民共和国律师法", 60),
    "labor_contract_law.json": ("中华人民共和国劳动合同法", 98),
    "patent_law.json": ("中华人民共和国专利法", 82),
    "civil_procedure_law.json": ("中华人民共和国民事诉讼法", 306),
    "personal_information_protection_law.json": ("中华人民共和国个人信息保护法", 74),
    "trademark_law.json": ("中华人民共和国商标法", 72),
    "copyright_law.json": ("中华人民共和国著作权法", 67),
    "company_law.json": ("中华人民共和国公司法", 266),
    "admin_litigation_law.json": ("中华人民共和国行政诉讼法", 103),
    "criminal_law.json": ("中华人民共和国刑法", 452),
    "criminal_procedure_law.json": ("中华人民共和国刑事诉讼法", 308),
    "admin_penalty_law.json": ("中华人民共和国行政处罚法", 86),
    "admin_review_law.json": ("中华人民共和国行政复议法", 90),
    "state_compensation_law.json": ("中华人民共和国国家赔偿法", 42),
    "admin_licensing_law.json": ("中华人民共和国行政许可法", 83),
    "gen_ai_interim_measures.json": ("生成式人工智能服务管理办法", 24),
    "consumer_protection_law.json": ("中华人民共和国消费者权益保护法", 63),
    "algorithm_recommendation_provisions.json": ("互联网信息服务算法推荐管理规定", 40),
    "data_security_law.json": ("中华人民共和国数据安全法", 55),
    "advertising_law.json": ("广告法", 75),
    "annual_leave_regulation.json": ("职工带薪年休假条例", 10),
    "antitrust_law.json": ("中华人民共和国反垄断法", 70),
    "anti_unfair_competition_law.json": ("中华人民共和国反不正当竞争法", 41),
    "wage_payment_rules.json": ("工资支付暂行规定", 20),
    "labor_dispute_mediation_arbitration_law.json": ("劳动争议调解仲裁法", 54),
    "labor_contract_implementation_regulation.json": ("中华人民共和国劳动合同法实施条例", 38),
    "admin_compulsion_law.json": ("中华人民共和国行政强制法", 71),
    "public_security_law.json": ("治安管理处罚法", 119),
    "admin_review_implementation_regulation.json": ("行政复议法实施条例", 77),
}

index = {"generated": "2026-05-25", "total_laws": 0, "complete": 0, "needs_update": 0, "missing": 0, "laws": []}

for jf, (name, expected) in sorted(json_to_name.items()):
    jpath = os.path.join(law_full, jf)
    if os.path.exists(jpath):
        with open(jpath, 'r', encoding='utf-8') as f:
            d = json.load(f)
        actual = d.get("article_count", 0)
        status = "complete" if actual >= expected * 0.9 else "needs_update"
        if status == "complete": index["complete"] += 1
        else: index["needs_update"] += 1
        entry = {
            "name": name, "json_file": jf, "status": status,
            "articles": actual, "expected": expected,
            "type": d.get("type", ""), "effective": d.get("effective", ""),
            "domains": d.get("domains", [])
        }
        index["laws"].append(entry)
        icon = "[OK]" if status == "complete" else "[!!]"
        print(f"{icon} {name}: {actual}/{expected} articles")

index["total_laws"] = len(index["laws"])
index["missing"] = 1  # only 九民会纪要 remaining

with open(r"skills\knowledge-base\law-index.json", "w", encoding="utf-8-sig") as f:
    json.dump(index, f, ensure_ascii=False, indent=2)

print(f"\n=== FINAL ===")
print(f"Complete: {index['complete']}, Needs Update: {index['needs_update']}, Missing: {index['missing']}")
print(f"Total JSON files: {index['total_laws']}")
if index['missing']: print(f"Remaining: 九民会纪要")
