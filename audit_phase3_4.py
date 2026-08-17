#!/usr/bin/env python3
"""
audit_phase3_4.py — Phase 3 (构建器审计) + Phase 4 (文档/测试审计)
一次性执行，输出报告。
"""
import csv, hashlib, json, os, re, shutil, subprocess, sys, time
from collections import Counter
from datetime import datetime
from pathlib import Path

# 路径全部可移植化：基于脚本位置推导工作区，工具链优先取环境变量/PATH，
# 去除硬编码本机绝对路径（pre-release 审计会拦截 C:\Users\being 泄漏）
SCRIPT_DIR = Path(__file__).resolve().parent
BASE = SCRIPT_DIR.parent
REPO = BASE / "legal-cn-core-codices-repo"
FORMAL = BASE / "legal-cn-core-codices"
NODE = os.environ.get("NODE") or shutil.which("node") or "node"
PYTHON = os.environ.get("PYTHON") or sys.executable
ENGINEERING = REPO / "workspace" / "工程记录" / "final_acceptance_20260807_121000_v5"
MANIFEST = ENGINEERING / "批次清单" / "标准编码生成清单.csv"
SOURCE = REPO / "workspace" / "source" / "legal-references"
DEPRECATED = Path(r"D:\legal-references\legal-cn-core-codices")
REPORT = BASE / f"audit_phase3_4_{datetime.now():%Y%m%d_%H%M%S}.md"

lines = []
def out(s):
    print(s, flush=True)
    lines.append(s)

def run(cmd, cwd=None, timeout=600):
    """运行命令，返回 (returncode, stdout, stderr)"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           cwd=cwd or str(REPO), timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except Exception as e:
        return -1, "", str(e)

out(f"# Phase 3 + Phase 4 审计报告 — {datetime.now():%Y-%m-%d %H:%M}")
out("")

# ══════════════════════════════════════════════════════════
# Phase 3: 构建器审计
# ══════════════════════════════════════════════════════════
out("## Phase 3: 构建器审计")
out("")

# ── 3.1 构建器语法检查 ──
out("### 3.1 构建器语法检查")
rc, so, se = run(f'"{NODE}" --check tools/build_local_csv.mjs')
if rc == 0:
    out("✅ build_local_csv.mjs 语法正确")
else:
    out(f"❌ 语法错误: {se[:200]}")
out("")

# ── 3.2 小规模构建测试（exact-path-baseline，10 个文件）──
out("### 3.2 小规模构建测试（10 个文件）")
# 生成测试基线
if MANIFEST.exists():
    with open(MANIFEST, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    test_paths = [r.get("relative_path","").strip() for r in rows[:10] if r.get("relative_path","").strip()]
    baseline_path = REPO / "_test_baseline.txt"
    with open(baseline_path, "w", encoding="utf-8") as fh:
        for p in test_paths:
            fh.write(p + "\n")

    out(f"测试基线: {len(test_paths)} 个文件")

    # 第一次构建
    out("第一次构建...")
    t1 = time.time()
    rc1, so1, se1 = run(
        f'"{NODE}" tools/build_local_csv.mjs --exact-path-baseline _test_baseline.txt --output-root _test_output',
        timeout=120
    )
    t1 = time.time() - t1
    out(f"  耗时: {t1:.1f}s | 返回码: {rc1}")
    if rc1 != 0:
        out(f"  错误: {se1[:300]}")

    # 第二次构建（幂等性测试）
    out("第二次构建（幂等性）...")
    t2 = time.time()
    rc2, so2, se2 = run(
        f'"{NODE}" tools/build_local_csv.mjs --exact-path-baseline _test_baseline.txt --output-root _test_output2',
        timeout=120
    )
    t2 = time.time() - t2
    out(f"  耗时: {t2:.1f}s | 返回码: {rc2}")

    # 比对输出
    if rc1 == 0 and rc2 == 0:
        out1 = REPO / "_test_output"
        out2 = REPO / "_test_output2"
        if out1.exists() and out2.exists():
            # 比对输出文件 hash
            files1 = sorted(str(p.relative_to(out1)) for p in out1.rglob("*") if p.is_file())
            files2 = sorted(str(p.relative_to(out2)) for p in out2.rglob("*") if p.is_file())
            if files1 == files2:
                all_same = True
                for f in files1:
                    h1 = hashlib.sha256((out1 / f).read_bytes()).hexdigest()
                    h2 = hashlib.sha256((out2 / f).read_bytes()).hexdigest()
                    if h1 != h2:
                        all_same = False
                        out(f"  ❌ 幂等性失败: {f}")
                        break
                if all_same:
                    out(f"✅ 幂等性通过: {len(files1)} 个输出文件完全一致")
            else:
                out(f"❌ 输出文件列表不一致: {len(files1)} vs {len(files2)}")
        else:
            out("⚠️ 输出目录不存在，无法比对")
    else:
        out("⚠️ 构建失败，跳过幂等性比对")

    # 清理测试输出
    for d in ["_test_output", "_test_output2"]:
        p = REPO / d
        if p.exists():
            shutil.rmtree(p)
    if baseline_path.exists():
        baseline_path.unlink()
    out("")
else:
    out("⚠️ 编码清单不存在，跳过构建测试")
out("")

# ── 3.3 registry 消费验证 ──
out("### 3.3 registry 消验验证")
if MANIFEST.exists():
    with open(MANIFEST, encoding="utf-8-sig", newline="") as fh:
        mrows = list(csv.DictReader(fh))
    blocked_before = sum(1 for r in mrows if r.get("coding_status","").strip() == "BLOCKED")
    ready_before = sum(1 for r in mrows if r.get("coding_status","").strip() == "READY")
    out(f"编码清单当前状态: READY={ready_before}, BLOCKED={blocked_before}")
    out(f"registry entries: {len(json.load(open(REPO / 'schema/official_registry/decision_order_evidence/registry.json', encoding='utf-8-sig'))['entries'])}")
    out("⚠️ registry 消费验证需要跑全量构建才能确认 BLOCKED→READY 迁移")
    out("   全量构建约需 30-60 分钟，建议单独执行")
else:
    out("⚠️ 编码清单不存在")
out("")

# ── 3.4 validate_dataset.py 语法检查 ──
out("### 3.4 validate_dataset.py 语法检查")
rc, so, se = run(f'"{PYTHON}" -m py_compile tools/validate_dataset.py')
if rc == 0:
    out("✅ validate_dataset.py 语法正确")
else:
    out(f"❌ 语法错误: {se[:200]}")
out("")

# ══════════════════════════════════════════════════════════
# Phase 4: 文档与测试审计
# ══════════════════════════════════════════════════════════
out("## Phase 4: 文档与测试审计")
out("")

# ── 4.1 文档覆盖度 ──
out("### 4.1 文档覆盖度")
DOC_CHECKS = {
    "AGENTS.md": ["目录职责", "铁律", "Git 纪律", "补证流程", "更新器边界", "审计流程"],
    "20260807_legal-cn-core-codices_Handoff.md": ["交接验收", "物理隔离", "编码纪律", "发布流程"],
}
for doc, keywords in DOC_CHECKS.items():
    doc_path = BASE / doc
    if doc_path.exists():
        text = doc_path.read_text(encoding="utf-8", errors="replace")
        found = [kw for kw in keywords if kw in text]
        missing = [kw for kw in keywords if kw not in text]
        if missing:
            out(f"⚠️ {doc}: 缺少 {missing}")
        else:
            out(f"✅ {doc}: 覆盖 {len(found)}/{len(keywords)} 项")
    else:
        out(f"❌ {doc}: 文件不存在")
out("")

# ── 4.2 审计脚本覆盖度 ──
out("### 4.2 审计脚本覆盖度")
AUDIT_COVERAGE = {
    "效力状态": ["validate_dataset.py"],
    "文件名规范": ["audit_step1_local.py"],
    "编码完整性": ["validate_dataset.py", "audit_wjbs_gate_transition.mjs"],
    "registry一致性": ["audit_step1_local.py", "official_registry.mjs"],
    "构建幂等性": ["build_local_csv.mjs"],
    "决定件序覆盖": ["audit_decision_order_coverage.mjs"],
    "WJBS门禁转换": ["audit_wjbs_gate_transition.mjs"],
    "内容结构": ["audit_content_structure_subset.mjs"],
    "候选布局": ["audit_candidate_layout.py"],
}
tools_dir = REPO / "tools"
available = set(f.name for f in tools_dir.iterdir() if f.is_file()) if tools_dir.exists() else set()
for domain, scripts in AUDIT_COVERAGE.items():
    found = [s for s in scripts if s in available]
    missing = [s for s in scripts if s not in available]
    if missing:
        out(f"⚠️ {domain}: 缺少 {missing}")
    else:
        out(f"✅ {domain}: {len(found)}/{len(scripts)} 脚本可用")
out("")

# ── 4.3 tools/ 目录完整清单 ──
out("### 4.3 tools/ 目录完整清单")
if tools_dir.exists():
    tools = sorted(f.name for f in tools_dir.iterdir() if f.is_file() and not f.name.startswith("__"))
    out(f"共 {len(tools)} 个工具文件:")
    for t in tools:
        out(f"  - {t}")
out("")

# ── 4.4 配置文件完整性 ──
out("### 4.4 配置文件完整性")
CONFIGS = [
    "schema/official_registry/decision_order_evidence/registry.json",
    "schema/standard_registry.json",
    "schema/tables.json",
    "official-source-updater/config/sources.json",
    ".github/workflows/ci.yml",
]
for cfg in CONFIGS:
    p = REPO / cfg
    if p.exists():
        sz = p.stat().st_size
        out(f"✅ {cfg} ({sz:,} bytes)")
    else:
        out(f"❌ {cfg}: 不存在")
out("")

# ── 写报告 ──
with open(REPORT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines))
print(f"\n报告已写入: {REPORT}", flush=True)
