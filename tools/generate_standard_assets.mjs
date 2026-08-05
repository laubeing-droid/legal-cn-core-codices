import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { STANDARD_CODE_SETS } from "./standard_codes.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const engineeringDir = path.resolve(scriptDir, "..");
const schemaDir = path.join(engineeringDir, "schema");
const workspaceRoot = path.join(engineeringDir, "workspace");
const extractedDir = path.join(workspaceRoot, "tmp", "pdfs", "standard_csv_schema");
const intakeDir = path.join(engineeringDir, "人工入库待审区", "intake");

const standards = [
  {
    id: "GBT47229.1-2026",
    filePattern: "GBT47229.1-2026_法律法规电子文件第1部分",
    title: "法律法规电子文件 第1部分：页面格式",
    published: "20260227",
    effective: "20260901",
    text: "47229-1.txt",
  },
  {
    id: "GBT47229.2-2026",
    filePattern: "GBT47229.2-2026_法律法规电子文件第2部分",
    title: "法律法规电子文件 第2部分：技术要求",
    published: "20260227",
    effective: "20260901",
    text: "47229-2.txt",
  },
  {
    id: "GBT47229.3-2026",
    filePattern: "GBT47229.1-2026_法律法规电子文件第3部分",
    title: "法律法规电子文件 第3部分：交换接口",
    published: "20260227",
    effective: "20260901",
    text: "47229-3.txt",
    sourceFilenameIncorrect: true,
  },
  {
    id: "GBT47277-2026",
    filePattern: "GBT47277-2026_数字化法律法规库",
    title: "数字化法律法规库 编码规则及数据元",
    published: "20260331",
    effective: "20261001",
    text: "47277.txt",
  },
];

function sha256(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex").toUpperCase();
}

function csvEscape(value) {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

async function buildStandardsManifest() {
  const files = await fs.readdir(intakeDir, { withFileTypes: true });
  const manifest = [];
  for (const standard of standards) {
    const source = files.find((entry) =>
      entry.isFile() && entry.name.startsWith(standard.filePattern));
    if (!source) throw new Error(`未找到标准原件：${standard.id}`);
    const fullPath = path.join(intakeDir, source.name);
    const buffer = await fs.readFile(fullPath);
    manifest.push({
      standard_id: standard.id,
      title: standard.title,
      published_date: standard.published,
      effective_date: standard.effective,
      implementation_status: "已发布、尚未实施；本库内部提前采用",
      source_filename: source.name,
      source_filename_incorrect: Boolean(standard.sourceFilenameIncorrect),
      source_sha256: sha256(buffer),
      extracted_text: standard.text,
    });
  }
  return manifest;
}

function extractAgencyRows(text) {
  const start = text.indexOf("附  录 B");
  if (start < 0) throw new Error("未定位 GB/T 47277 附录B");
  const lines = text.slice(start).split(/\r?\n/);
  const rows = [];
  let pending = null;
  const finish = () => {
    if (!pending) return;
    const normalized = pending.parts.join(" ").replace(/\s+/g, " ").trim();
    const match = /^(.*?)(?:\s+)(现行|—)(?:\s+(.*))?$/.exec(normalized);
    if (match) {
      rows.push({
        agency_code_suffix: pending.code,
        agency_name: match[1].trim(),
        status: match[2],
        note: (match[3] ?? "").trim(),
        source_standard: "GB/T 47277—2026 附录B表B.1",
      });
      pending = null;
    }
  };
  for (const rawLine of lines) {
    const line = rawLine.replace(/\f/g, "").trim();
    if (!line || /^(GB\/T|表 B\.|机关代码|附\s*录|[0-9]{1,2})$/.test(line)) continue;
    const startMatch = /^(\d{4})\s+(.+)$/.exec(line);
    if (startMatch) {
      finish();
      pending = { code: startMatch[1], parts: [startMatch[2]] };
      finish();
      continue;
    }
    if (pending) {
      pending.parts.push(line);
      finish();
    }
  }
  finish();
  const unique = new Map();
  for (const row of rows) {
    if (unique.has(row.agency_code_suffix)) {
      throw new Error(`附录B重复机关代码：${row.agency_code_suffix}`);
    }
    unique.set(row.agency_code_suffix, row);
  }
  return [...unique.values()];
}

async function main() {
  await fs.mkdir(schemaDir, { recursive: true });
  const standardsManifest = await buildStandardsManifest();
  const registry = {
    version: "2.0.0",
    generated_from: standardsManifest.map((item) => ({
      standard_id: item.standard_id,
      source_sha256: item.source_sha256,
    })),
    categories_47229_2: STANDARD_CODE_SETS.electronicDocumentCategories,
    categories_47277: STANDARD_CODE_SETS.gbt47277Categories,
    file_categories_47229_2: STANDARD_CODE_SETS.electronicFileCategories,
    file_types_47277: STANDARD_CODE_SETS.gbt47277FileTypes,
    effect_codes: {
      "01": "有效",
      "02": "尚未施行",
      "03": "已修改",
      "04": "已废止",
      "05": "已失效",
    },
    wjbs_rule: {
      oid: "1.2.156.3005.6",
      body_length: 31,
      authority_issued_required: true,
    },
    content_structure_segments: [2, 2, 2, 2, 4, 2, 2, 2],
  };
  await fs.writeFile(
    path.join(schemaDir, "standards_manifest.json"),
    `${JSON.stringify(standardsManifest, null, 2)}\n`,
    "utf8",
  );
  await fs.writeFile(
    path.join(schemaDir, "standard_registry.json"),
    `${JSON.stringify(registry, null, 2)}\n`,
    "utf8",
  );

  const agencyText = await fs.readFile(path.join(extractedDir, "47277.txt"), "utf8");
  const agencies = extractAgencyRows(agencyText);
  const agencyColumns = [
    "agency_code_suffix",
    "agency_name",
    "status",
    "note",
    "source_standard",
  ];
  const agencyCsv = [
    agencyColumns.join(","),
    ...agencies.map((row) =>
      agencyColumns.map((column) => csvEscape(row[column])).join(",")),
  ].join("\r\n");
  await fs.writeFile(
    path.join(schemaDir, "制定机关代码注册表.csv"),
    `\uFEFF${agencyCsv}\r\n`,
    "utf8",
  );

  const mapping = `# 标准字段映射表

| GB/T 47229.2短名 | GB/T 47277数据元 | 语义 |
| --- | --- | --- |
| WJBS | 不映射 | 制定机关生成的电子文件标识；不得写入01001 |
| FLFGDZWJFLDM | 01004 | 分类代码 |
| BT | 01002 | 标题映射为“全称（公布年份）” |
| TZ | 01003 | 题注 |
| ZDJGDM | 01006 | 制定或修改机关代码 |
| ZDJGMC | 01007 | 制定或修改机关名称 |
| PZJGDM | 01010 | 批准机关代码 |
| PZJGMC | 01011 | 批准机关名称 |
| FWZH | 01005 | 发文字号 |
| TGRQ | 01012 | 通过日期 |
| PZRQ | 01013 | 批准日期 |
| GBRQ | 01014 | 公布日期 |
| SXRQ | 01015 | 施行日期 |
| SHXRQ | 01017 | 失效日期 |
| SXX | 01018 | 时效状态 |
| 无 | 01001 | 31位法律法规文件码，仅GB/T 47277覆盖的0000—1500 |
| 无 | 01016 | 修改日期 |
| 正文 | 01019 | 法律法规正文 |
| 文件类型代码 | 01020 | GB/T 47277文件类型代码 |
| 文本出处 | 01021 | 获取渠道名称，不写本机路径 |

工程哈希、抓取状态、冲突和人工队列只写工程记录。GB/T 47229.2附录A.3要求WJBS由制定机关生成；本库派生组合只可进入编码候选清单。
`;
  await fs.writeFile(path.join(schemaDir, "标准字段映射表.md"), mapping, "utf8");
  process.stdout.write(JSON.stringify({
    standards: standardsManifest.length,
    agency_codes: agencies.length,
  }));
}

main().catch((error) => {
  process.stderr.write(`${error.stack ?? error}\n`);
  process.exitCode = 1;
});
