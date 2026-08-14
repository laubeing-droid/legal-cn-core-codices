"""从人工入库待审区的国标 PDF 原件提取全文，供 generate_standard_assets.mjs 消费。

前置步骤（generate_standard_assets.mjs 依赖 workspace/tmp/pdfs/standard_csv_schema/*.txt）：
    python tools/extract_standard_texts.py

输出：
    workspace/tmp/pdfs/standard_csv_schema/{47229-1,47229-2,47229-3,47277}.txt
"""
import json
import sys
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:  # 兼容 PyPDF2
    from PyPDF2 import PdfReader

ENGINEERING_ROOT = Path(__file__).resolve().parent.parent
INTAKE_DIR = ENGINEERING_ROOT / "人工入库待审区" / "intake"
OUTPUT_DIR = ENGINEERING_ROOT / "workspace" / "tmp" / "pdfs" / "standard_csv_schema"

# 与 generate_standard_assets.mjs 的 standards 定义保持一致
STANDARDS = [
    {
        "id": "GBT47229.1-2026",
        "file_pattern": "GBT47229.1-2026_法律法规电子文件第1部分",
        "text": "47229-1.txt",
    },
    {
        "id": "GBT47229.2-2026",
        "file_pattern": "GBT47229.2-2026_法律法规电子文件第2部分",
        "text": "47229-2.txt",
    },
    {
        "id": "GBT47229.3-2026",
        "file_pattern": "GBT47229.1-2026_法律法规电子文件第3部分",
        "text": "47229-3.txt",
    },
    {
        "id": "GBT47277-2026",
        "file_pattern": "GBT47277-2026_数字化法律法规库",
        "text": "47277.txt",
    },
]


def main() -> int:
    if not INTAKE_DIR.is_dir():
        print(f"错误：intake 目录不存在：{INTAKE_DIR}", file=sys.stderr)
        return 1

    files = list(INTAKE_DIR.iterdir())
    used: set[str] = set()
    results = []

    for standard in STANDARDS:
        pattern = standard["file_pattern"]
        source = next(
            (
                f
                for f in files
                if f.is_file()
                and f.name.startswith(pattern)
                and f.name not in used
            ),
            None,
        )
        if source is None:
            print(f"错误：未找到标准原件 {standard['id']}（模式：{pattern}）", file=sys.stderr)
            return 1
        used.add(source.name)

        try:
            reader = PdfReader(str(source))
        except Exception as exc:  # noqa: BLE001
            print(f"错误：无法解析 {source.name}：{exc}", file=sys.stderr)
            return 1

        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(pages)
        if not text.strip():
            print(f"错误：{source.name} 未提取到文字（可能是扫描版 PDF）", file=sys.stderr)
            return 1

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUTPUT_DIR / standard["text"]
        out_path.write_text(text, encoding="utf-8")
        results.append(
            {
                "standard_id": standard["id"],
                "source": source.name,
                "pages": len(reader.pages),
                "chars": len(text),
                "output": str(out_path.relative_to(ENGINEERING_ROOT)).replace("\\", "/"),
            }
        )

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
