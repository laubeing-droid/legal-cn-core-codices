"""
法律法规库多源核验 - 监控脚本
==============================
查看P2/P3运行进度。
"""

import re
from pathlib import Path
from datetime import datetime

LOG_FILE = Path("D:/legal-references/verification_system/output/verification.log")

def get_progress():
    """从日志文件提取进度信息。"""
    if not LOG_FILE.exists():
        return "日志文件不存在"

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 提取P3进度
    p3_progress = []
    for line in lines:
        m = re.search(r"\[P3\] 进度: (\d+)/(\d+)", line)
        if m:
            p3_progress.append((int(m.group(1)), int(m.group(2))))

    # 提取P2状态
    p2_started = False
    p2_files = 0
    for line in lines:
        if "阶段 url_check 适用文件" in line:
            m = re.search(r"适用文件: (\d+)", line)
            if m:
                p2_files = int(m.group(1))
                p2_started = True

    # 提取最新URL检查结果
    url_results = {}
    for line in lines:
        if "URL_VERIFIED" in line or "URL_REACHABLE" in line or "URL_NOT_FOUND" in line:
            if "URL_VERIFIED" in line:
                url_results["verified"] = url_results.get("verified", 0) + 1
            elif "URL_REACHABLE" in line:
                url_results["reachable"] = url_results.get("reachable", 0) + 1
            elif "URL_NOT_FOUND" in line:
                url_results["not_found"] = url_results.get("not_found", 0) + 1

    # 构造报告
    report = []
    report.append("=" * 50)
    report.append("法律法规库多源核验 - 监控报告")
    report.append(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("=" * 50)

    if p3_progress:
        latest = p3_progress[-1]
        pct = latest[0] / latest[1] * 100 if latest[1] else 0
        report.append(f"\n[P3] 地方政府网站核验:")
        report.append(f"  进度: {latest[0]}/{latest[1]} ({pct:.1f}%)")
        report.append(f"  记录数: {len(p3_progress)}")

    if p2_started:
        report.append(f"\n[P2] URL有效性检查:")
        report.append(f"  适用文件: {p2_files}")
        if url_results:
            report.append(f"  结果: {url_results}")

    report.append("\n" + "=" * 50)
    return "\n".join(report)


if __name__ == "__main__":
    print(get_progress())
