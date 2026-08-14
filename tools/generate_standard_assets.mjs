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

// 人工入库轻量方案：standards_manifest.json 携带 version + change_log，
// 内容未变仅刷新审计时间戳；内容变更时版本次号 +1 并追加一条变更记录。
function diffStandards(previous, next) {
  const prevById = new Map(previous.map((s) => [s.standard_id, s]));
  const nextById = new Map(next.map((s) => [s.standard_id, s]));
  const added = next
    .filter((s) => !prevById.has(s.standard_id))
    .map((s) => s.standard_id);
  const removed = previous
    .filter((s) => !nextById.has(s.standard_id))
    .map((s) => s.standard_id);
  const changed = next
    .filter((s) => {
      const prev = prevById.get(s.standard_id);
      return prev && JSON.stringify(prev) !== JSON.stringify(s);
    })
    .map((s) => s.standard_id);
  return { added, removed, changed };
}

async function writeVersionedManifest(manifest) {
  const manifestPath = path.join(schemaDir, "standards_manifest.json");
  const today = new Date().toISOString().slice(0, 10);
  let previous = null;
  try {
    const raw = await fs.readFile(manifestPath, "utf8");
    const parsed = JSON.parse(raw.replace(/^\uFEFF/, ""));
    // 兼容旧格式：裸数组视为尚无版本元数据
    previous = Array.isArray(parsed)
      ? { version: "0.0.0", change_log: [], standards: parsed }
      : parsed;
  } catch {
    previous = null;
  }

  if (!previous) {
    const payload = {
      version: "1.0.0",
      updated_at: today,
      change_log: [
        {
          version: "1.0.0",
          date: today,
          action: "INIT",
          items: manifest.map((s) => s.standard_id),
        },
      ],
      standards: manifest,
    };
    await fs.writeFile(manifestPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
    return { changed: true, version: "1.0.0" };
  }

  if (JSON.stringify(previous.standards) === JSON.stringify(manifest)) {
    // 旧格式迁移（尚无版本元数据）时，即使内容相同也要 INIT 一次；
    // 已是版本化格式则仅刷新审计时间戳。
    const needsInit = !Array.isArray(previous.change_log) || previous.change_log.length === 0;
    const payload = needsInit
      ? {
          version: "1.0.0",
          updated_at: today,
          change_log: [
            {
              version: "1.0.0",
              date: today,
              action: "INIT",
              items: manifest.map((s) => s.standard_id),
            },
          ],
          standards: manifest,
        }
      : { ...previous, updated_at: today };
    await fs.writeFile(manifestPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
    return { changed: needsInit, version: payload.version };
  }

  const { added, removed, changed } = diffStandards(previous.standards, manifest);
  const [major, minor] = previous.version.split(".").map((n) => Number(n) || 0);
  const nextVersion = `${major}.${minor + 1}.0`;
  const items = [...added, ...changed, ...removed.map((id) => `${id}(移除)`)];
  await fs.writeFile(
    manifestPath,
    `${JSON.stringify(
      {
        ...previous,
        version: nextVersion,
        updated_at: today,
        change_log: [
          ...(previous.change_log ?? []),
          { version: nextVersion, date: today, action: "UPDATE", items },
        ],
        standards: manifest,
      },
      null,
      2,
    )}\n`,
    "utf8",
  );
  return { changed: true, version: nextVersion };
}

function extractAgencyRows(text) {
  const matchIndex = text.search(/附\s*录\s*B/);
  const start = matchIndex >= 0 ? matchIndex : text.indexOf("附  录 B");
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

// 人工复核补录（发布版已含，国标PDF附录B无或名称不同）：
// 重新提取生成时必须保护，不得因重新生成而丢失或回退。
const MANUAL_AGENCY_OVERRIDES = [
  {
    agency_code_suffix: "3000",
    agency_name: "国务院反垄断委员会",
    status: "历史",
    note: "国务院设立的议事协调机构；证据 antimonopoly_committee_agency_code_evidence.md SHA-256 3f598d377b062bb08867d94b7eea19c99c94232713fe40e520460a484cbe86b7",
    source_standard: "GB/T 47229.2—2026 A.2.3(a)及表B.3",
  },
  {
    agency_code_suffix: "3000",
    agency_name: "国务院反垄断反不正当竞争委员会",
    status: "现行",
    note: "国务院设立的议事协调机构；证据 antimonopoly_committee_agency_code_evidence.md SHA-256 3f598d377b062bb08867d94b7eea19c99c94232713fe40e520460a484cbe86b7",
    source_standard: "GB/T 47229.2—2026 A.2.3(a)及表B.3",
  },
  {
    agency_code_suffix: "4040",
    agency_name: "国家医疗保障局",
    status: "现行",
    note: "司法部公开行业标准PDF表B.1复核",
    source_standard: "GB/T 47277—2026 附录B表B.1",
  },
];

function applyAgencyOverrides(rows) {
  const result = [...rows];
  const existing = new Set(rows.map((r) => `${r.agency_code_suffix}|${r.agency_name}`));
  for (const override of MANUAL_AGENCY_OVERRIDES) {
    const key = `${override.agency_code_suffix}|${override.agency_name}`;
    if (!existing.has(key)) {
      result.push({ ...override });
    }
  }
  return result.sort((a, b) => a.agency_code_suffix.localeCompare(b.agency_code_suffix));
}

async function main() {
  await fs.mkdir(schemaDir, { recursive: true });
  const standardsManifest = await buildStandardsManifest();
  const registry = {
    version: "2.3.0",
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
      authority_issued_required: false,
      allowed_source_types: [
        "AUTHORITY_ISSUED",
        "STANDARD_DERIVED_LOCAL",
      ],
      standard_derived_local_requirements: [
        "全部组成要素有来源证据",
        "严格按GB/T 47229.2—2026附录A确定性生成",
        "顺序码缺失时使用标准规定的0000",
        "内部顺序码仅在组成要素可唯一确定时生成",
        "不得使用本库流水号、日期、哈希或猜测值代替编码要素",
      ],
    },
    content_structure_segments: [2, 2, 2, 2, 4, 2, 2, 2],
  };
  const versioned = await writeVersionedManifest(standardsManifest);
  await fs.writeFile(
    path.join(schemaDir, "standard_registry.json"),
    `${JSON.stringify(registry, null, 2)}\n`,
    "utf8",
  );

  const agencyText = await fs.readFile(path.join(extractedDir, "47277.txt"), "utf8");
  const agencies = applyAgencyOverrides(extractAgencyRows(agencyText));
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
| WJBS | 不映射 | 电子文件标识；来源分为\`AUTHORITY_ISSUED\`和\`STANDARD_DERIVED_LOCAL\`，不得写入01001 |
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

工程哈希、抓取状态、冲突和人工队列只写工程记录。官方未签发WJBS时，允许在组成要素证据完整、算法确定且通过校验的前提下，按GB/T 47229.2—2026附录A生成\`STANDARD_DERIVED_LOCAL\`并进入正式数据；不得以本库流水号、日期、哈希或猜测值替代编码要素。无法确定组成要素的记录进入阻断清单，不生成伪码。
`;
  await fs.writeFile(path.join(schemaDir, "标准字段映射表.md"), mapping, "utf8");
  process.stdout.write(JSON.stringify({
    standards: standardsManifest.length,
    agency_codes: agencies.length,
    manifest_version: versioned.version,
    manifest_changed: versioned.changed,
  }));
}

main().catch((error) => {
  process.stderr.write(`${error.stack ?? error}\n`);
  process.exitCode = 1;
});
