import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import {
  STANDARD_CODE_SETS,
  build47277FileCode,
  buildWjbs,
  isOfficialCaseId,
  validate47277FileCode,
  validateWjbs,
} from "./standard_codes.mjs";
import {
  extractInlineDataImages,
  localAttachmentReferences,
} from "./markdown_attachments.mjs";
import {
  deriveAgencyCode,
  deriveAgencyName,
  deriveCategoryCode,
  deriveCompleteDate,
  deriveEffectCode,
  deriveExplicitEffectiveDate,
  deriveFileTypeCode,
  deriveLegacyFilenameMetadata,
  deriveNationalRuleAgencyName,
  deriveSequenceCode,
  normalizeSourceDate,
  normalizeRequiredDate,
} from "./standard_metadata.mjs";
import {
  loadFlkRegistry,
  loadNationalRulesRegistry,
  mapFlkEffectCode,
  resolveFlkRecord,
  resolveNationalRuleRecord,
} from "./official_registry.mjs";
import {
  duplicateContentStructureCodes,
  extractLegalContentRows,
} from "./legal_structure.mjs";
import { extractPrimaryLegalDocumentBody } from "./legal_document_body.mjs";
import {
  finalRelativeMarkdownPath,
} from "./delivery_paths.mjs";
import { assignInternalSequenceGroup } from "./internal_sequence.mjs";
import { listMarkdownFiles } from "./file_inventory.mjs";
import {
  applyMetadataOverride,
  loadMetadataOverrides,
  mergeMetadataOverrideMaps,
} from "./metadata_overrides.mjs";
import {
  applyOfficialPageMetadata,
  loadOfficialPageMetadata,
  officialPageEvidenceForDocument,
} from "./official_page_metadata.mjs";
import {
  classifySourceContent,
  fragmentDescriptor,
} from "./content_scope.mjs";
import {
  decisionCodingForLegacyCarrier,
  decisionCodingForDocument,
  loadDecisionOrderEvidenceRegistry,
  validatedDecisionTitleOrder,
} from "./decision_order.mjs";
import {
  canonicalizeLegalVersions,
  normalizeCoreProvisionsForCarrierIdentity,
  normalizeLegalTextForIdentity,
} from "./legal_version_identity.mjs";
import {
  describeExactWjbsScope,
  loadExactPathBaseline,
  loadCurrentWjbsBlockedPaths,
  loadWjbsTargetPaths,
  resolveWjbsTargetFiles,
} from "./wjbs_target_scope.mjs";
import {
  loadPublicationSkips,
  partitionPublicationSkips,
} from "./publication_skips.mjs";
import {
  contentStructurePublicationErrors,
  formalLawPublicationDecision,
  required47277CoreFields,
} from "./publication_output.mjs";
import {
  applyAcceptedCodingBaseline,
  loadAcceptedCodingBaseline,
} from "./accepted_coding_baseline.mjs";
import {
  acceptedCodingComponentContext,
  loadComponentContext,
  mergeComponentContexts,
} from "./component_context.mjs";
import {
  fixedPollutionPattern,
  sanitizeFormalText,
} from "./formal_text.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const usage = [
  "Usage: node build_local_csv.mjs",
  "  --output-root <交换候选中的最终目录树>",
  "  --engineering-root <工程记录批次目录>",
  "  --official-page-metadata <已登记官方单页元数据CSV，必选>",
  "  --full-corpus <显式授权枚举全部源文件；不得与WJBS精确基线同时使用>",
  "  --full-corpus-purpose FINAL_ACCEPTANCE_ONLY <全量最终验收双确认；其他值拒绝运行>",
  "  --exact-path-baseline <仅处理CSV中relative_path列出的路径；专项审计输出不可发布>",
  "  --component-context-baseline <精确专项可选；既有标准编码清单，仅用于判断同组占用>",
  "  --wjbs-target-baseline <仅处理44条及LOCAL_NORMALIZED_TITLE_ORDER队列；专项审计输出不可发布>",
  "  --wjbs-blocked-baseline <仅处理当前明确缺WJBS且状态为BLOCKED的记录；专项审计输出不可发布>",
  "",
].join("\n");
if (process.argv.includes("--help") || process.argv.includes("-h")) {
  process.stdout.write(usage);
  process.exit(0);
}
const outputArgumentIndex = process.argv.indexOf("--output-root");
const outputArgument = outputArgumentIndex >= 0
  ? process.argv[outputArgumentIndex + 1]
  : "";
const engineeringArgumentIndex = process.argv.indexOf("--engineering-root");
const engineeringArgument = engineeringArgumentIndex >= 0
  ? process.argv[engineeringArgumentIndex + 1]
  : "";
const officialPageMetadataArgumentIndex = process.argv.indexOf("--official-page-metadata");
const officialPageMetadataArgument = officialPageMetadataArgumentIndex >= 0
  ? process.argv[officialPageMetadataArgumentIndex + 1]
  : "";
const exactPathBaselineArgumentIndex = process.argv.indexOf("--exact-path-baseline");
const exactPathBaselineArgument = exactPathBaselineArgumentIndex >= 0
  ? process.argv[exactPathBaselineArgumentIndex + 1]
  : "";
const componentContextArgumentIndex = process.argv.indexOf("--component-context-baseline");
const componentContextArgument = componentContextArgumentIndex >= 0
  ? process.argv[componentContextArgumentIndex + 1]
  : "";
const wjbsTargetBaselineArgumentIndex = process.argv.indexOf("--wjbs-target-baseline");
const wjbsTargetBaselineArgument = wjbsTargetBaselineArgumentIndex >= 0
  ? process.argv[wjbsTargetBaselineArgumentIndex + 1]
  : "";
const wjbsBlockedBaselineArgumentIndex = process.argv.indexOf("--wjbs-blocked-baseline");
const wjbsBlockedBaselineArgument = wjbsBlockedBaselineArgumentIndex >= 0
  ? process.argv[wjbsBlockedBaselineArgumentIndex + 1]
  : "";
const fullCorpusRequested = process.argv.includes("--full-corpus");
const fullCorpusPurposeArgumentIndex = process.argv.indexOf("--full-corpus-purpose");
const fullCorpusPurposeArgument = fullCorpusPurposeArgumentIndex >= 0
  ? process.argv[fullCorpusPurposeArgumentIndex + 1]
  : "";
const exactScopeArguments = [
  exactPathBaselineArgument,
  wjbsTargetBaselineArgument,
  wjbsBlockedBaselineArgument,
].filter(Boolean);
if (exactScopeArguments.length > 1) {
  throw new Error("精确路径基线参数不得同时使用。");
}
const exactScopeArgument = exactScopeArguments[0] ?? "";
if (fullCorpusRequested && exactScopeArgument) {
  throw new Error("--full-corpus 不得与精确路径基线同时使用。");
}
if (componentContextArgument && !exactScopeArgument) {
  throw new Error("--component-context-baseline 只能与精确路径基线同时使用。");
}
if (fullCorpusRequested && fullCorpusPurposeArgument !== "FINAL_ACCEPTANCE_ONLY") {
  throw new Error("全量枚举仅限最终验收，必须同时提供 --full-corpus-purpose FINAL_ACCEPTANCE_ONLY。");
}
if (!fullCorpusRequested && fullCorpusPurposeArgument) {
  throw new Error("--full-corpus-purpose 只能与 --full-corpus 同时使用。");
}
if (!fullCorpusRequested && !exactScopeArgument) {
  throw new Error(`必须显式选择 --full-corpus 或提供精确路径基线。禁止缺省回退到全量枚举。\n${usage.trim()}`);
}
if (!outputArgument || outputArgument.startsWith("--")) {
  throw new Error(`必须显式提供 --output-root。\n${usage.trim()}`);
}
if (!engineeringArgument || engineeringArgument.startsWith("--")) {
  throw new Error(`必须显式提供 --engineering-root。\n${usage.trim()}`);
}
if (!officialPageMetadataArgument || officialPageMetadataArgument.startsWith("--")) {
  throw new Error(`必须显式提供 --official-page-metadata。\n${usage.trim()}`);
}
const deliveryRoot = path.resolve(outputArgument);
const candidateFinalRoot = deliveryRoot;
const engineeringDir = path.resolve(engineeringArgument);
const repositoryRoot = path.resolve(scriptDir, "..");
const allowedExchangeRoot = path.resolve(scriptDir, "..", "workspace", "交换候选");
const relativeToExchangeRoot = path.relative(allowedExchangeRoot, deliveryRoot);
if (
  !relativeToExchangeRoot
  || relativeToExchangeRoot.startsWith("..")
  || path.isAbsolute(relativeToExchangeRoot)
) {
  throw new Error(`--output-root 必须是交换候选目录的直接或间接子目录：${allowedExchangeRoot}`);
}
const workspaceRoot = path.resolve(
  repositoryRoot,
  "workspace",
  "source",
  "legal-references",
);
const allowedEngineeringRoot = path.resolve(scriptDir, "..", "workspace", "工程记录");
const relativeToEngineeringRoot = path.relative(allowedEngineeringRoot, engineeringDir);
if (
  !relativeToEngineeringRoot
  || relativeToEngineeringRoot.startsWith("..")
  || path.isAbsolute(relativeToEngineeringRoot)
) {
  throw new Error(`--engineering-root 必须是工程记录目录的子目录：${allowedEngineeringRoot}`);
}
const forbiddenOutputRoots = [
  path.resolve(repositoryRoot, "corpus"),
  path.resolve(repositoryRoot, "..", "legal-cn-core-codices"),
];
if (forbiddenOutputRoots.some((candidate) =>
  candidate.localeCompare(deliveryRoot, undefined, { sensitivity: "accent" }) === 0)) {
  throw new Error("构建器只允许写交换候选；最终目录必须由原子发布器写入。");
}
const formalDir = candidateFinalRoot;
const batchDir = path.join(engineeringDir, "批次清单");
const schemaPath = path.resolve(scriptDir, "..", "schema", "tables.json");
const agencyRegistryPath = path.resolve(
  scriptDir,
  "..",
  "schema",
  "制定机关代码注册表.csv",
);
const areaRegistryPath = path.resolve(
  scriptDir,
  "..",
  "schema",
  "行政区划代码注册表_20251231.csv",
);
const metadataOverrideRegistryPath = path.resolve(
  scriptDir,
  "..",
  "schema",
  "标准元数据补证注册表.json",
);
const commercialMetadataOverrideRegistryPath = path.resolve(
  scriptDir,
  "..",
  "schema",
  "商业数据库元数据补证注册表.json",
);
const acceptedCodingBaselinePath = path.resolve(
  repositoryRoot,
  "schema",
  "accepted_coding_baseline.csv",
);
const publicationSkipRegistryPath = path.resolve(
  scriptDir,
  "..",
  "schema",
  "publication_skip_registry.csv",
);
const decisionOrderEvidenceRegistryPath = path.resolve(
  repositoryRoot,
  "schema",
  "official_registry",
  "decision_order_evidence",
  "registry.json",
);
const flkRegistryDir = path.resolve(
  repositoryRoot,
  "schema",
  "official_registry",
  "npc_flk_20260730_full",
);
const flkRegistryPath = path.join(flkRegistryDir, "flk_official_index.csv");
const flkRegistryMetaPath = path.join(flkRegistryDir, "flk_official_index_meta.json");
const nationalRulesRegistryDir = path.resolve(
  repositoryRoot,
  "schema",
  "official_registry",
  "national_rules_database_union_20260730_20260803",
);
const nationalRulesRegistryPath = path.join(
  nationalRulesRegistryDir,
  "official_index.csv",
);
const nationalRulesRegistryMetaPath = path.join(
  nationalRulesRegistryDir,
  "official_index_meta.json",
);
const sourceRootNames = fs.readdirSync(workspaceRoot, { withFileTypes: true })
  .filter((entry) => entry.isDirectory() && /^(?!90_)\d{2}_/.test(entry.name))
  .map((entry) => entry.name)
  .sort((a, b) => a.localeCompare(b, "zh-CN"));
const formalTables = new Set([
  "legal_documents.csv",
  "legal_contents.csv",
  "legal_relations.csv",
  "legal_sources.csv",
  "cases.csv",
  "case_holdings.csv",
  "case_legal_references.csv",
  "practice_references.csv",
]);
const lawRequired = ["WJBS", "FLFGDZWJFLDM", "BT", "ZDJGDM", "SXX", "SXRQ"];
const exactStandardKeys = [
  "WJBS", "FLFGDZWJFLDM", "FLBMFLDM", "BT", "TZ", "ZDJGDM", "ZDJGMC",
  "FWJGSM", "SXX", "TGJGDM", "TGJGMC", "PZJGDM", "PZJGMC", "FWZH",
  "TGRQ", "PZRQ", "GBRQ", "SXRQ", "SHXRQ", "CWRQ", "FBRQ",
];
const effectLabels = new Map([
  ["01", "有效"],
  ["02", "尚未施行"],
  ["03", "已修改"],
  ["04", "已废止"],
  ["05", "已失效"],
]);
const absolutePathPattern = /(?:^|[\s("'`])(?:[A-Za-z]:[\\/])/m;

function loadCentralAgencyRegistry(csvPath) {
  const registry = new Map();
  const lines = fs.readFileSync(csvPath, "utf8").replace(/^\uFEFF/, "").split(/\r?\n/);
  for (const line of lines.slice(1)) {
    const match = line.match(/^(\d{4}),([^,]+),/);
    if (match) registry.set(match[2].trim(), match[1]);
  }
  return registry;
}

function loadAreaRegistry(csvPath) {
  const rows = [];
  const lines = fs.readFileSync(csvPath, "utf8").replace(/^\uFEFF/, "").split(/\r?\n/);
  for (const line of lines.slice(1)) {
    const match = line.match(/^(\d{6}),([^,]+),([123]),([^,]+),/);
    if (match) {
      rows.push({
        code: match[1],
        name: match[2],
        level: Number(match[3]),
        path: match[4],
      });
    }
  }
  return rows;
}

const centralAgencyRegistry = loadCentralAgencyRegistry(agencyRegistryPath);
const areaRegistry = loadAreaRegistry(areaRegistryPath);
const metadataOverrides = mergeMetadataOverrideMaps(
  loadMetadataOverrides(metadataOverrideRegistryPath),
  loadMetadataOverrides(commercialMetadataOverrideRegistryPath),
);
const metadataOverrideConflictsByPath = new Map();
for (const conflict of metadataOverrides.conflicts ?? []) {
  const conflicts = metadataOverrideConflictsByPath.get(conflict.relativePath) ?? [];
  conflicts.push(conflict);
  metadataOverrideConflictsByPath.set(conflict.relativePath, conflicts);
}
const acceptedCodingBaseline = loadAcceptedCodingBaseline(acceptedCodingBaselinePath);
const exactComponentContext = componentContextArgument
  ? mergeComponentContexts(
      acceptedCodingComponentContext(acceptedCodingBaseline),
      loadComponentContext(path.resolve(componentContextArgument)),
    )
  : new Map();
const publicationSkips = loadPublicationSkips(publicationSkipRegistryPath);
const officialDecisionOrderEvidence = loadDecisionOrderEvidenceRegistry(
  decisionOrderEvidenceRegistryPath,
);
const officialPageMetadata = loadOfficialPageMetadata(path.resolve(officialPageMetadataArgument));

function cleanScalar(raw) {
  let value = raw.trim();
  if (
    (value.startsWith('"') && value.endsWith('"')) ||
    (value.startsWith("'") && value.endsWith("'"))
  ) {
    value = value.slice(1, -1);
  }
  if (value === "[]" || value === "{}" || value === "null" || value === "~") return "";
  return value.replace(/\\"/g, '"').replace(/''/g, "'");
}

function parseFrontMatter(text) {
  if (!text.startsWith("---")) return { present: false, meta: {}, body: text, complex: false };
  const endMatch = /\r?\n---\s*(?:\r?\n|$)/g;
  endMatch.lastIndex = 3;
  const match = endMatch.exec(text);
  if (!match) return { present: false, meta: {}, body: text, complex: true };
  const raw = text.slice(3, match.index).replace(/^\r?\n/, "");
  const body = text.slice(match.index + match[0].length);
  const meta = {};
  let currentListKey = "";
  let complex = false;
  for (const line of raw.split(/\r?\n/)) {
    const keyMatch = line.match(/^([^:#][^:]*?):\s*(.*)$/);
    if (keyMatch && !/^\s/.test(line)) {
      const key = keyMatch[1].trim();
      const value = keyMatch[2].trim();
      currentListKey = key;
      if (value.startsWith("[") && value.endsWith("]")) {
        const inner = value.slice(1, -1).trim();
        meta[key] = inner ? inner.split(",").map(cleanScalar) : [];
      } else {
        meta[key] = cleanScalar(value);
      }
      continue;
    }
    const listMatch = line.match(/^\s+-\s+(.*)$/);
    if (listMatch && currentListKey) {
      if (!Array.isArray(meta[currentListKey])) {
        meta[currentListKey] = meta[currentListKey] ? [meta[currentListKey]] : [];
      }
      meta[currentListKey].push(cleanScalar(listMatch[1]));
      continue;
    }
    if (line.trim() && /^\s/.test(line)) complex = true;
  }
  return { present: true, meta, body, complex };
}

function asText(value) {
  if (Array.isArray(value)) return value.filter(Boolean).join("；");
  if (value === undefined || value === null) return "";
  return String(value).trim();
}

function firstMeta(meta, keys) {
  for (const key of keys) {
    const value = asText(meta[key]);
    if (value) return value;
  }
  return "";
}

function firstUrl(meta) {
  const candidates = [
    meta.official_source_url,
    meta.source_url,
    meta.url,
    meta.urls,
    meta.正式链接,
    meta.栏目链接,
    meta.链接,
  ];
  for (const candidate of candidates) {
    if (Array.isArray(candidate)) {
      const found = candidate.find((item) => /^https?:\/\//i.test(String(item)));
      if (found) return String(found).trim();
    } else if (/^https?:\/\//i.test(asText(candidate))) {
      return asText(candidate);
    }
  }
  return "";
}

function standardDate(value) {
  return normalizeRequiredDate(value);
}

function dateFromRelativePath(relativePath) {
  const match = relativePath.match(
    /_(\d{4})[-]?(\d{2})[-]?(\d{2})(?:_|\.|\s|\[)/,
  );
  if (!match) return "";
  const candidate = `${match[1]}-${match[2]}-${match[3]}`;
  return deriveCompleteDate(candidate);
}

function normalizeRelative(fullPath) {
  return path.relative(workspaceRoot, fullPath).split(path.sep).join("/");
}

function displayTitle(meta, body, fullPath) {
  const fromMeta = firstMeta(meta, ["BT", "title", "案例标题", "标题", "LinkTitle"]);
  if (fromMeta) return fromMeta.replace(/^《|》$/g, "").trim();
  const heading = body.match(/^\s*#\s+(.+?)\s*$/m);
  if (heading) return heading[1].replace(/^《|》$/g, "").trim();
  return path.basename(fullPath, path.extname(fullPath))
    .replace(/\s*\[ima-[^\]]+\]\s*$/i, "")
    .replace(/_\d{4}[-]?\d{2}[-]?\d{2}.*$/, "")
    .trim();
}

function caseType(relativePath, meta) {
  const declared = firstMeta(meta, ["案例分类", "案例类别", "case_type", "案由"]);
  if (declared) return declared;
  if (relativePath.startsWith("04_")) return "仲裁案例";
  if (relativePath.startsWith("03_")) return "检察案例";
  if (relativePath.includes("/06_")) return "最高人民法院指导性案例";
  if (relativePath.includes("/07_")) return "人民法院案例库案例";
  if (relativePath.includes("/09_")) return "人民法院公报案例";
  return "法院案例";
}

function materialType(relativePath, meta) {
  const declared = firstMeta(meta, ["document_type", "材料类型", "group"]);
  if (declared) return declared;
  const branch = relativePath.split("/")[1] ?? "";
  if (/^03_/.test(branch)) return "会议纪要";
  if (/^04_/.test(branch)) return "审判业务指导文件";
  if (/^05_/.test(branch)) return "答疑";
  return "实务参考";
}

function extractOfficialCaseId(meta, text, relativePath) {
  const direct = firstMeta(meta, [
    "案例库编号",
    "入库编号",
    "official_case_id",
    "case_id",
  ]);
  if (direct && !/^ima-/i.test(direct)) return direct;
  const patterns = [
    /(?:\*\*)?入库编号[：:]\*{0,2}\s*([A-Za-z0-9-]+)/,
    /(?:\*\*)?案例库编号[：:]\*{0,2}\s*([A-Za-z0-9-]+)/,
    /【(检例第\s*0*\d+\s*号)】/,
    /\b(检例第\s*0*\d+\s*号)\b/,
    /(?:^|[（(：:\s])(指导案例\s*\d+\s*号)/m,
  ];
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match) return match[1].replace(/\s+/g, "");
  }
  const docId = firstMeta(meta, ["document_id"]);
  if (
    docId &&
    !/^ima-/i.test(docId) &&
    (relativePath.includes("/06_") || relativePath.includes("/07_"))
  ) return docId;
  return "";
}

function extractNamedSections(text, names) {
  const escaped = names.map((name) => name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
  const heading = new RegExp(
    `^#{1,6}\\s*(${escaped})\\s*$\\r?\\n([\\s\\S]*?)(?=^#{1,6}\\s+|\\Z)`,
    "gm",
  );
  const bracket = new RegExp(
    `【(${escaped})】\\s*\\r?\\n?([\\s\\S]*?)(?=\\r?\\n【[^】]+】|\\Z)`,
    "g",
  );
  const inline = new RegExp(
    `^(?:\\*\\*)?(${escaped})[：:](?:\\*\\*)?\\s*([^\\r\\n]+(?:\\r?\\n(?!\\s*(?:#|【))[^\\r\\n]+)*)`,
    "gm",
  );
  const sections = [];
  for (const regex of [heading, bracket, inline]) {
    for (const match of text.matchAll(regex)) {
      const value = match[2]
        .replace(/^\s+|\s+$/g, "")
        .replace(/\r?\n{3,}/g, "\n\n");
      if (value) sections.push({ heading: match[1].trim(), text: value });
    }
  }
  const seen = new Set();
  return sections.filter((section) => {
    const key = `${section.heading}\0${section.text}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function extractHoldingSections(text) {
  return extractNamedSections(text, [
    "裁判要旨",
    "检察要旨",
    "案例要旨",
    "要旨",
    "解纷要旨",
    "裁判摘要",
    "典型意义",
  ]);
}

function extractReferenceSections(text) {
  return extractNamedSections(text, [
    "相关法条",
    "相关规定",
    "解纷依据",
    "相关法律法规解读",
    "关联索引",
  ]);
}

function holdingType(heading) {
  if (heading.includes("检察")) return "检察要旨";
  if (heading.includes("典型意义")) return "典型意义";
  if (heading.includes("解纷")) return "解纷要旨";
  if (heading.includes("摘要")) return "裁判摘要";
  if (heading === "要旨") return "要旨";
  return heading;
}

async function listAllFiles(root) {
  const files = [];
  async function walk(current) {
    const entries = await fsp.readdir(current, { withFileTypes: true });
    entries.sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));
    for (const entry of entries) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) await walk(full);
      else if (entry.isFile()) files.push(full);
    }
  }
  await walk(root);
  return files;
}

function sha256(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}

function csvEscape(value) {
  const text = value === undefined || value === null ? "" : String(value);
  if (/[",\r\n]/.test(text)) return `"${text.replaceAll('"', '""')}"`;
  return text;
}

function csvText(columns, rows) {
  const lines = [columns.map(csvEscape).join(",")];
  for (const row of rows) {
    lines.push(columns.map((column) => csvEscape(row[column] ?? "")).join(","));
  }
  return `\uFEFF${lines.join("\r\n")}\r\n`;
}

function derivedMarkdownText(fields, sourceBody) {
  const sanitized = sanitizeFormalText(sourceBody);
  const frontMatter = Object.entries(fields)
    .map(([key, value]) => `${key}: ${JSON.stringify(String(value ?? ""))}`)
    .join("\n");
  return {
    text: `---\n${frontMatter}\n---\n\n${sanitized.text}\n`,
    transformations: JSON.stringify({
      removed_pollution_lines: sanitized.removedPollutionLines,
      removed_absolute_paths: sanitized.removedAbsolutePaths,
      removed_unsafe_control_characters: sanitized.removedUnsafeControlCharacters,
    }),
  };
}

function emptyRow(columns) {
  return Object.fromEntries(columns.map((column) => [column, ""]));
}

function lawRow(
  meta,
  body,
  relativePath,
  title,
  officialRecord,
  officialRuleRecord,
  schemaColumns,
  metadataOverride,
  officialPageEvidence,
) {
  const row = emptyRow(schemaColumns);
  const legacyFilename = deriveLegacyFilenameMetadata(relativePath);
  for (const key of exactStandardKeys) row[key] = firstMeta(meta, [key]);
  for (const field of ["TGRQ", "PZRQ", "GBRQ", "SXRQ", "SHXRQ", "CWRQ", "FBRQ"]) {
    row[field] = standardDate(row[field]);
  }
  row.FLFGDZWJFLDM ||= deriveCategoryCode(meta, relativePath);
  const officialCategory = officialRecord
    ? deriveCategoryCode({ group: officialRecord.flxz }, relativePath)
    : "";
  if (officialCategory) row.FLFGDZWJFLDM = officialCategory;
  row.BT ||= officialRecord?.title || title;
  const localAgencyName = row.ZDJGMC || deriveAgencyName(
    meta,
    relativePath,
    row.BT,
    row.FLFGDZWJFLDM,
    areaRegistry,
  );
  const localAgencyCode = row.ZDJGDM || deriveAgencyCode(
    localAgencyName,
    centralAgencyRegistry,
    areaRegistry,
    relativePath,
  );
  const officialAgencyCode = officialRecord?.zdjgName
    ? deriveAgencyCode(
      officialRecord.zdjgName,
      centralAgencyRegistry,
      areaRegistry,
      relativePath,
    )
    : "";
  const officialRuleAgencyName = deriveNationalRuleAgencyName(
    officialRuleRecord,
    areaRegistry,
    relativePath,
  );
  const officialRuleAgencyCode = officialRuleAgencyName
    ? deriveAgencyCode(
      officialRuleAgencyName,
      centralAgencyRegistry,
      areaRegistry,
      relativePath,
    )
    : "";
  if (!row.ZDJGDM && officialAgencyCode) {
    row.ZDJGMC = officialRecord.zdjgName;
    row.ZDJGDM = officialAgencyCode;
    row._agency_name_source = "NPC_FLK_OFFICIAL_INDEX";
  } else if (!row.ZDJGDM && officialRuleAgencyCode) {
    row.ZDJGMC = officialRuleAgencyName;
    row.ZDJGDM = officialRuleAgencyCode;
    row._agency_name_source = "GOV_CN_NATIONAL_RULES_INDEX";
  } else {
    row.ZDJGMC = localAgencyName;
    row.ZDJGDM = localAgencyCode;
    row._agency_name_source = localAgencyName ? "SOURCE_OR_MIGRATION_METADATA" : "";
  }
  row._agency_code_source = row.ZDJGDM
    ? (row.ZDJGDM.startsWith("000000")
      ? "GBT47277_APPENDIX_B"
      : "MCA_XZQH_20251231+GBT47277_APPENDIX_B")
    : "";
  row.FWZH ||= firstMeta(meta, [
    "document_number", "发文字号", "公布令号", "公告号", "文件号",
  ]);
  const sourceEffectiveDate = standardDate(firstMeta(meta, ["effective_date", "施行日期"]));
  row.SXRQ ||= sourceEffectiveDate;
  if (row.SXRQ) row._effective_date_source = "SOURCE_FRONTMATTER";
  row.TGRQ ||= standardDate(firstMeta(meta, ["通过日期"]));
  const sourcePromulgationDate = standardDate(firstMeta(meta, [
    "promulgation_date", "公布日期", "publication_date", "发布日期", "date",
  ]));
  row.GBRQ ||= sourcePromulgationDate;
  if (row.GBRQ) row._promulgation_source = "SOURCE_FRONTMATTER";
  if (!row.GBRQ && legacyFilename.promulgationDate) {
    row.GBRQ = standardDate(legacyFilename.promulgationDate);
    row._promulgation_source = "LEGACY_FILENAME_MIGRATION";
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(officialRecord?.gbrq ?? "")) {
    row.GBRQ = standardDate(officialRecord.gbrq);
    row._promulgation_source = "NPC_FLK_OFFICIAL_INDEX";
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(officialRecord?.sxrq ?? "")) {
    row.SXRQ = standardDate(officialRecord.sxrq);
    row._effective_date_source = "NPC_FLK_OFFICIAL_INDEX";
  }
  if (!row.SXRQ) {
    const explicitEffectiveDate = deriveExplicitEffectiveDate(body);
    if (explicitEffectiveDate) {
      row.SXRQ = explicitEffectiveDate;
      row._effective_date_source = "SOURCE_BODY_EXPLICIT_EFFECTIVE_CLAUSE";
    }
  }
  row.FBRQ ||= standardDate(firstMeta(meta, ["publication_date", "发布日期"]));
  row.SXX ||= deriveEffectCode(firstMeta(meta, ["status", "时效性"]));
  if (row.SXX) row._effect_source = "SOURCE_FRONTMATTER";
  if (!row.SXX && legacyFilename.effectCode) {
    row.SXX = legacyFilename.effectCode;
    row._effect_source = "LEGACY_FILENAME_MIGRATION";
  }
  const officialEffect = mapFlkEffectCode(officialRecord?.sxx);
  if (officialEffect) {
    row.SXX = officialEffect;
    row._effect_source = "NPC_FLK_OFFICIAL_INDEX";
  }
  if (!row.SXRQ && row.GBRQ) {
    row.SXRQ = row.GBRQ;
    row._effective_date_source = "GBT47277_DEFAULT_TO_GBRQ";
  }
  applyOfficialPageMetadata(row, officialPageEvidence);
  applyMetadataOverride(row, metadataOverride);
  row._metadata_override_evidence = metadataOverride
    ? JSON.stringify(metadataOverride.evidence)
    : "";
  row.DE_01020 ||= deriveFileTypeCode(meta, row.BT);
  const sourceUrl = firstUrl(meta);
  if (!row.DE_01021 && sourceUrl) {
    const host = new URL(sourceUrl).hostname.toLowerCase();
    if (host === "flk.npc.gov.cn") row.DE_01021 = "国家法律法规数据库";
    else if (host === "xzfg.moj.gov.cn") row.DE_01021 = "国家行政法规库";
    else if (host.endsWith("gov.cn")) row.DE_01021 = "制定机关官网";
  }
  row._sequence_code = deriveSequenceCode(
    { ...meta, document_number: row.FWZH || firstMeta(meta, ["document_number"]) },
    body,
  );
  row.DE_01001 = firstMeta(meta, ["DE_01001", "01001"]);
  row.DE_01002 = firstMeta(meta, ["DE_01002", "01002"])
    || (row.BT && row.GBRQ ? `${row.BT}（${row.GBRQ.slice(0, 4)}）` : "");
  row.DE_01003 = row.TZ;
  row.DE_01004 = row.FLFGDZWJFLDM;
  row.DE_01005 = row.FWZH;
  row.DE_01006 = row.ZDJGDM;
  row.DE_01007 = row.ZDJGMC;
  row.DE_01010 = row.PZJGDM;
  row.DE_01011 = row.PZJGMC;
  row.DE_01012 = row.TGRQ;
  row.DE_01013 = row.PZRQ;
  row.DE_01014 = row.GBRQ;
  row.DE_01015 = row.SXRQ;
  row.DE_01016 = standardDate(firstMeta(meta, ["DE_01016", "修改日期"]));
  row.DE_01017 = row.SHXRQ;
  row.DE_01018 = row.SXX;
  row.DE_01019 = sanitizeFormalText(body).text;
  row.DE_01020 ||= firstMeta(meta, ["DE_01020", "文件类型代码"]);
  row.DE_01021 ||= firstMeta(meta, ["DE_01021", "文本出处", "正式来源"]);
  row.DE_01021 ||= "第三方本地载体（待官方全文核验）";
  return row;
}

function normalizeWjbsSourceType(value) {
  const sourceType = asText(value);
  if (/^(制定机关|AUTHORITY_ISSUED)$/i.test(sourceType)) return "AUTHORITY_ISSUED";
  if (/^STANDARD_DERIVED_LOCAL$/i.test(sourceType)) return "STANDARD_DERIVED_LOCAL";
  return "";
}

function validateLawRow(row, wjbsSourceType, { fulltextAvailable = true } = {}) {
  const errors = [];
  for (const field of lawRequired) {
    if (!row[field]) errors.push({ code: "MISSING_STANDARD_FIELD", field });
  }
  if (row.WJBS) {
    for (const code of validateWjbs(row.WJBS, { sourceType: wjbsSourceType })) {
      errors.push({ code, field: "WJBS" });
    }
  }
  if (row.FLFGDZWJFLDM
      && !STANDARD_CODE_SETS.electronicDocumentCategories.includes(row.FLFGDZWJFLDM)) {
    errors.push({ code: "INVALID_CATEGORY_CODE", field: "FLFGDZWJFLDM" });
  }
  if (row.ZDJGDM && !/^\d{10}$/.test(row.ZDJGDM)) {
    errors.push({ code: "INVALID_AGENCY_CODE", field: "ZDJGDM" });
  }
  if (row.SXX && !/^(01|02|03|04|05)$/.test(row.SXX)) {
    errors.push({ code: "INVALID_EFFECT_CODE", field: "SXX" });
  }
  if (row.SXRQ && !/^\d{8}$/.test(row.SXRQ)) {
    errors.push({ code: "INVALID_EFFECTIVE_DATE", field: "SXRQ" });
  }
  const coveredBy47277 = STANDARD_CODE_SETS.gbt47277Categories.includes(
    row.FLFGDZWJFLDM,
  );
  if (coveredBy47277) {
    for (const field of required47277CoreFields({ fulltextAvailable })) {
      if (!row[field]) errors.push({ code: "MISSING_47277_CORE_ELEMENT", field });
    }
    if (row.DE_01001) {
      for (const code of validate47277FileCode(row.DE_01001)) {
        errors.push({ code, field: "DE_01001" });
      }
      if (row.WJBS && row.WJBS.slice("1.2.156.3005.6-".length) !== row.DE_01001) {
        errors.push({ code: "WJBS_FILE_CODE_MISMATCH", field: "DE_01001" });
      }
    }
  } else if (row.DE_01001) {
    errors.push({ code: "GBT47277_SCOPE_VIOLATION", field: "DE_01001" });
  }
  return errors;
}

function existingVerification(meta) {
  const raw = firstMeta(meta, [
    "verification_status",
    "核验状态",
    "在线核验",
    "source_status",
  ]);
  const exactFulltext = new Set([
    "OFFICIAL_FULLTEXT_VERIFIED",
    "OFFICIAL_CONTENT_VERIFIED_DERIVED",
  ]);
  const status = exactFulltext.has(raw)
    ? "OFFICIAL_CONTENT_VERIFIED_DERIVED"
    : "UNOFFICIAL_CANDIDATE";
  return {
    status,
    identity: exactFulltext.has(raw) ? "true" : "false",
    fulltext: exactFulltext.has(raw) ? "true" : "false",
    attachments: "false",
    effect: "false",
    officialWjbsSource: firstMeta(meta, [
      "WJBS来源", "WJBS_source", "official_wjbs_source",
    ]),
    officialWjbsVerified: "false",
    note: raw && !exactFulltext.has(raw) ? `旧字段原值：${raw}` : "",
  };
}

async function attachmentReferences(body, sourcePath) {
  const references = [];
  for (const { raw, decoded } of localAttachmentReferences(body)) {
    const resolved = path.resolve(path.dirname(sourcePath), decoded);
    const insideWorkspace = path.relative(workspaceRoot, resolved);
    const exists = !insideWorkspace.startsWith("..") && fs.existsSync(resolved);
    references.push({
      source_relative_path: normalizeRelative(sourcePath),
      attachment_reference: raw,
      attachment_relative_path: exists ? normalizeRelative(resolved) : "",
      attachment_exists: String(exists),
      attachment_sha256: exists ? sha256(await fsp.readFile(resolved)) : "",
      verification_status: exists ? "LOCAL_ATTACHMENT_PRESENT" : "MISSING_ATTACHMENT",
    });
  }
  return references;
}

async function validateCsvWithArtifactTool(csvPath, expectedRows) {
  // 纯 Node 实现的 CSV 自检（替代 @oai/artifact-tool 的 Workbook.fromCSV + inspect）：
  // 原实现仅检查前 min(expectedRows+1, 6) 行的 A1:B 值；本实现更严格——
  // 验证文件可读、表头非空、非空数据行数 ≥ expectedRows，确保写出与记录一致。
  const raw = await fsp.readFile(csvPath, "utf8");
  const text = raw.replace(/^\uFEFF/, "");
  const lines = text.split(/\r?\n/).filter((line) => line.trim() !== "");
  if (lines.length < 2) {
    throw new Error(
      `CSV 行数不足（期望至少 ${expectedRows} 行数据，实际 ${Math.max(0, lines.length - 1)} 行）: ${csvPath}`,
    );
  }
  const header = lines[0];
  if (!header || header.trim() === "") {
    throw new Error(`CSV 缺少表头: ${csvPath}`);
  }
  const dataRows = lines.length - 1;
  if (dataRows < expectedRows) {
    throw new Error(`CSV 数据行数 ${dataRows} 少于期望 ${expectedRows}: ${csvPath}`);
  }
  return {
    ok: true,
    sheet: path.basename(csvPath),
    inspection: { header_cells: header.split(",").length, data_rows: dataRows },
  };
}

async function main() {
  if (fs.existsSync(candidateFinalRoot)) {
    const existing = await fsp.readdir(candidateFinalRoot);
    if (existing.length) {
      throw new Error(`交换候选必须为空，禁止覆盖已有候选：${candidateFinalRoot}`);
    }
  }
  await fsp.mkdir(formalDir, { recursive: true });
  const navigationDirectory = path.join(
    candidateFinalRoot,
    "00_法律检索导航与效力适用规则",
  );
  await fsp.mkdir(navigationDirectory, { recursive: true });
  await fsp.writeFile(
    path.join(navigationDirectory, "README.md"),
    [
      "# 法律检索导航与效力适用规则",
      "",
      "- 01—08为法律法规及其他规范性文件；以文件标识、效力状态和来源证据共同检索。",
      "- 09—10、80—82、89为司法业务材料或案例，不作为立法法意义上的规范层级。",
      "- Markdown是检索派生载体；正式结构化数据以根目录CSV及工程批次记录为准。",
      "",
    ].join("\n"),
    "utf8",
  );
  await fsp.mkdir(engineeringDir, { recursive: true });
  await fsp.mkdir(batchDir, { recursive: true });
  const schema = JSON.parse((await fsp.readFile(schemaPath, "utf8")).replace(/^\uFEFF/, ""));
  const flkMeta = JSON.parse(
    (await fsp.readFile(flkRegistryMetaPath, "utf8")).replace(/^\uFEFF/, ""),
  );
  const flkRegistry = await loadFlkRegistry(flkRegistryPath);
  if (
    flkMeta.complete !== true
    || flkRegistry.rowCount !== flkMeta.fetched_rows
    || flkRegistry.uniqueIdCount !== flkMeta.unique_ids
  ) {
    throw new Error("国家法律法规数据库官方索引不完整或清单计数不一致。");
  }
  const nationalRulesMeta = JSON.parse(
    (await fsp.readFile(nationalRulesRegistryMetaPath, "utf8")).replace(/^\uFEFF/, ""),
  );
  const nationalRulesRegistry = await loadNationalRulesRegistry(
    nationalRulesRegistryPath,
  );
  if (
    nationalRulesMeta.complete !== true
    || nationalRulesRegistry.rowCount !== nationalRulesMeta.row_count
  ) {
    throw new Error("中国政府网国家规章库官方索引不完整或清单计数不一致。");
  }
  const schemaSourceDir = path.dirname(schemaPath);
  const schemaTargetDir = path.join(engineeringDir, "schema");
  if (path.resolve(schemaSourceDir) !== path.resolve(schemaTargetDir)) {
    await fsp.cp(schemaSourceDir, schemaTargetDir, { recursive: true, force: true });
  }
  await fsp.copyFile(
    path.resolve(scriptDir, "..", "schema", "来源注册表.json"),
    path.join(engineeringDir, "来源注册表.json"),
  );
  await fsp.cp(
    flkRegistryDir,
    path.join(engineeringDir, "official_registry", "npc_flk_20260730_full"),
    { recursive: true, force: true },
  );
  await fsp.cp(
    nationalRulesRegistryDir,
    path.join(
      engineeringDir,
      "official_registry",
      "national_rules_database_union_20260730_20260803",
    ),
    { recursive: true, force: true },
  );
  const rows = Object.fromEntries(Object.keys(schema.tables).map((name) => [name, []]));
  const validationRows = rows["validation_errors.csv"];
  const codingRows = [];
  const attachmentRows = [];
  const markdownRows = [];
  let pendingLaws = [];
  const verificationByPath = new Map();
  const emittedMarkdownTargets = new Map();
  async function emitDerivedMarkdown({
    relativePath,
    objectType,
    identifier,
    title,
    publicationDate,
    effectCode,
    categoryCode,
    agencyName,
    sourceSha256,
    verificationStatus,
    body,
  }) {
    const normalizedDate = /^\d{8}$/.test(publicationDate ?? "")
      ? `${publicationDate.slice(0, 4)}-${publicationDate.slice(4, 6)}-${publicationDate.slice(6, 8)}`
      : publicationDate;
    let targetRelativePath = finalRelativeMarkdownPath({
      relativePath,
      objectType,
      title,
      officialCaseId: objectType === "case" ? identifier : "",
      publicationDate: normalizedDate,
      effectLabel: effectLabels.get(effectCode) ?? "效力待核",
      wjbs: objectType === "legal_document" ? identifier : "",
      categoryCode,
      agencyName,
    });
    if (!targetRelativePath) {
      return "";
    }
    const existingSource = emittedMarkdownTargets.get(targetRelativePath);
    if (existingSource && existingSource !== relativePath) {
      const directory = path.posix.dirname(targetRelativePath);
      const stem = path.posix.basename(targetRelativePath, ".md");
      let ordinal = 2;
      let versionedTarget = path.posix.join(
        directory,
        `${stem}__版本待核_${ordinal}.md`,
      );
      while (emittedMarkdownTargets.has(versionedTarget)) {
        ordinal += 1;
        versionedTarget = path.posix.join(
          directory,
          `${stem}__版本待核_${ordinal}.md`,
        );
      }
      rows["conflicts.csv"].push({
        relative_path: relativePath,
        conflict_type: "TARGET_PATH_COLLISION",
        field_name: "target_relative_path",
        local_value: targetRelativePath,
        other_value: existingSource,
        evidence: "可读标题、官方编号、日期和国标编码生成同一最终路径",
        disposition: "MIGRATED_WITH_READABLE_VERSION_SUFFIX",
      });
      targetRelativePath = versionedTarget;
    }
    const targetPath = path.resolve(candidateFinalRoot, ...targetRelativePath.split("/"));
    const relativeTarget = path.relative(candidateFinalRoot, targetPath);
    if (
      !relativeTarget
      || relativeTarget.startsWith("..")
      || path.isAbsolute(relativeTarget)
      || path.extname(targetPath).toLowerCase() !== ".md"
    ) {
      throw new Error(`非法Markdown派生路径：${relativePath}`);
    }
    const derived = derivedMarkdownText({
      object_type: objectType,
      identifier,
      title,
      source_relative_path: relativePath,
      source_sha256: sourceSha256,
      verification_status: verificationStatus,
      carrier_role: "RETRIEVAL_DERIVED_MARKDOWN",
    }, body);
    await fsp.mkdir(path.dirname(targetPath), { recursive: true });
    const buffer = Buffer.from(derived.text, "utf8");
    await fsp.writeFile(targetPath, buffer);
    emittedMarkdownTargets.set(targetRelativePath, relativePath);
    markdownRows.push({
      source_relative_path: relativePath,
      target_relative_path: targetRelativePath,
      object_type: objectType,
      identifier,
      storage_key_type: objectType === "legal_document"
        ? (identifier ? "READABLE_TITLE_DATE_EFFECT_WJBS" : "READABLE_BLOCKED_SOURCE")
        : "READABLE_TITLE_OFFICIAL_ID_DATE",
      source_sha256: sourceSha256,
      derived_sha256: sha256(buffer),
      transformations: derived.transformations,
    });
    return targetRelativePath;
  }
  const files = [];
  if (exactScopeArgument) {
    const targetPaths = exactPathBaselineArgument
      ? loadExactPathBaseline(path.resolve(exactPathBaselineArgument))
      : wjbsBlockedBaselineArgument
        ? loadCurrentWjbsBlockedPaths(path.resolve(wjbsBlockedBaselineArgument))
        : loadWjbsTargetPaths(path.resolve(wjbsTargetBaselineArgument));
    files.push(...resolveWjbsTargetFiles(workspaceRoot, targetPaths));
    const scopeLabel = exactPathBaselineArgument
      ? "explicit path"
      : wjbsBlockedBaselineArgument
        ? "current WJBS blocked"
        : "WJBS 44+legacy";
    process.stdout.write(`${scopeLabel} scope: ${files.length} exact paths; full corpus enumeration skipped\n`);
  } else {
    for (const rootName of sourceRootNames) {
      const root = path.join(workspaceRoot, rootName);
      process.stdout.write(`listing ${rootName}\n`);
      const rootFiles = listMarkdownFiles(root);
      process.stdout.write(`listed ${rootName}: ${rootFiles.length}\n`);
      files.push(...rootFiles);
    }
  }
  files.sort((a, b) => a.localeCompare(b, "zh-CN"));
  const scopeDescriptor = exactScopeArgument
    ? describeExactWjbsScope(workspaceRoot, files)
    : {
        enumeration_mode: "FULL_CORPUS_ENUMERATION",
        full_corpus_enumerated: true,
        source_roots: sourceRootNames,
        source_files: files.length,
      };
  const sourceRelativePaths = new Set(files.map(normalizeRelative));

  const seenWjbs = new Map();
  const seenCaseIds = new Map();
  let processed = 0;
  for (const fullPath of files) {
    const relativePath = normalizeRelative(fullPath);
    for (const conflict of metadataOverrideConflictsByPath.get(relativePath) ?? []) {
      rows["conflicts.csv"].push({
        relative_path: relativePath,
        conflict_type: "METADATA_OVERRIDE_SOURCE_CONFLICT",
        field_name: conflict.field,
        local_value: conflict.primaryValue,
        other_value: conflict.supplementalValue,
        evidence: "标准/官方补证注册表与商业数据库补证值不一致；按证据层级保留前者。",
        disposition: "PRIMARY_STANDARD_EVIDENCE_RETAINED",
      });
    }
    if (processed % 100 === 0) {
      process.stdout.write(`processing ${processed + 1}/${files.length}: ${relativePath}\n`);
    }
    const stat = await fsp.stat(fullPath);
    const buffer = await fsp.readFile(fullPath);
    let text = "";
    let utf8Valid = true;
    try {
      text = new TextDecoder("utf-8", { fatal: true }).decode(buffer).replace(/^\uFEFF/, "");
    } catch {
      utf8Valid = false;
      text = buffer.toString("utf8").replace(/^\uFEFF/, "");
      validationRows.push({
        relative_path: relativePath,
        table_name: "source_records.csv",
        row_locator: relativePath,
        error_code: "INVALID_UTF8",
        severity: "ERROR",
        field_name: "",
        message: "源文件不是严格 UTF-8；已仅用于工程记录，需人工修复编码。",
      });
    }
    const parsed = parseFrontMatter(text);
    const meta = parsed.meta;
    const inlineDataImages = extractInlineDataImages(parsed.body);
    const sourceBody = inlineDataImages.markdown;
    const sourceAuditText = inlineDataImages.attachments.length
      ? `${JSON.stringify(meta)}\n${sourceBody}`
      : text;
    const title = displayTitle(meta, sourceBody, fullPath);
    const sourceContentClass = classifySourceContent(relativePath, title, sourceBody);
    const fulltextAvailable = sourceContentClass !== "blocked_access_content";
    const objectType = sourceContentClass === "blocked_access_content"
      ? "legal_document"
      : sourceContentClass;
    const legalProcessingBody = fulltextAvailable ? sourceBody : "";
    const primaryBodyExtraction = objectType === "legal_document"
      ? extractPrimaryLegalDocumentBody(legalProcessingBody)
      : {
          body: sourceBody,
          truncated: false,
          trailingTitle: "",
          removedLineCount: 0,
        };
    const body = primaryBodyExtraction.body;
    if (primaryBodyExtraction.truncated) {
      rows["conflicts.csv"].push({
        relative_path: relativePath,
        conflict_type: "APPENDED_LEGAL_DOCUMENTS_IN_SOURCE",
        field_name: "formal_text",
        local_value: title,
        other_value: primaryBodyExtraction.trailingTitle,
        evidence: `源Markdown正文在主文件施行条款后以分隔线拼入另一法律文件；截去${primaryBodyExtraction.removedLineCount}行，源文件保持只读。`,
        disposition: "RESOLVED_PRIMARY_DOCUMENT_ONLY_DERIVED",
      });
    }
    const digest = sha256(buffer);
    const sourceUrl = firstUrl(meta);
    const absPresent = absolutePathPattern.test(sourceAuditText);
    const thirdPartyPollution = fixedPollutionPattern.test(sourceAuditText);
    const legacyId = firstMeta(meta, [
      "id", "document_id", "文件标识", "版本标识", "bbbs", "flk_id", "案例库编号",
    ]);
    const officialLawRecord = objectType === "legal_document"
      ? resolveFlkRecord(meta, sourceUrl, title, flkRegistry)
      : null;
    const preliminaryCategoryCode = deriveCategoryCode(meta, relativePath);
    const preliminaryAgencyName = objectType === "legal_document"
      ? deriveAgencyName(
        meta,
        relativePath,
        title,
        preliminaryCategoryCode,
        areaRegistry,
      )
      : "";
    const officialRuleRecord = objectType === "legal_document"
      ? resolveNationalRuleRecord(
        title,
        preliminaryCategoryCode,
        nationalRulesRegistry,
        preliminaryAgencyName,
      )
      : null;
    const officialPageEvidence = officialPageEvidenceForDocument(
      officialPageMetadata,
      relativePath,
      officialRuleRecord?.record_id,
    );

    rows["source_records.csv"].push({
      relative_path: relativePath,
      scope: relativePath.split("/")[0],
      object_type: objectType,
      file_size: stat.size,
      last_write_time: stat.mtime.toISOString(),
      source_sha256: digest,
      utf8_valid: String(utf8Valid),
      frontmatter_present: String(parsed.present),
      legacy_id: legacyId,
      title,
      publication_date: normalizeSourceDate(firstMeta(meta, ["publication_date", "发布日期", "date"])),
      effective_date: normalizeSourceDate(firstMeta(meta, ["effective_date", "施行日期"])),
      legacy_status: firstMeta(meta, ["status", "时效性"]),
      source_url: sourceUrl,
      absolute_path_present: String(absPresent),
    });

    if (parsed.complex) {
      validationRows.push({
        relative_path: relativePath,
        table_name: "source_records.csv",
        row_locator: relativePath,
        error_code: "FRONTMATTER_PARTIAL_PARSE",
        severity: "WARNING",
        field_name: "",
        message: "Front Matter 含最小解析器不支持的复杂结构；标量与一级列表已读取。",
      });
    }
    if (absPresent) {
      validationRows.push({
        relative_path: relativePath,
        table_name: "source_records.csv",
        row_locator: relativePath,
        error_code: "ABSOLUTE_LOCAL_PATH",
        severity: "WARNING",
        field_name: "",
        message: "源正文包含 Windows 绝对路径；正式 CSV 未复制该路径。",
      });
    }
    if (thirdPartyPollution) {
      validationRows.push({
        relative_path: relativePath,
        table_name: "source_records.csv",
        row_locator: relativePath,
        error_code: "FIXED_PLATFORM_POLLUTION",
        severity: "WARNING",
        field_name: "",
        message: "源正文含平台固定污染块；正式 Markdown 已移除并在派生清单记录清洗计数。",
      });
    }
    if (inlineDataImages.attachments.length) {
      validationRows.push({
        relative_path: relativePath,
        table_name: "source_records.csv",
        row_locator: relativePath,
        error_code: "INLINE_DATA_IMAGE_EXTRACTED",
        severity: "WARNING",
        field_name: "",
        message: `源正文含 ${inlineDataImages.attachments.length} 个内嵌 Base64 图像；正式 Markdown 仅保留标签、MIME 和图像 SHA-256。`,
      });
    }

    const verification = existingVerification(meta);
    if (officialLawRecord) {
      verification.identity = "true";
      verification.effect = mapFlkEffectCode(officialLawRecord.sxx) ? "true" : "false";
      if (verification.status === "UNOFFICIAL_CANDIDATE") {
        verification.status = "OFFICIAL_INDEX_METADATA_VERIFIED";
      }
      verification.note = [
        verification.note,
        `国家法律法规数据库版本标识=${officialLawRecord.bbbs}；仅核验官方索引元数据，不代表全文核验。`,
      ].filter(Boolean).join("；");
    }
    if (officialRuleRecord) {
      verification.identity = "true";
      if (verification.status === "UNOFFICIAL_CANDIDATE") {
        verification.status = "OFFICIAL_INDEX_METADATA_VERIFIED";
      }
      verification.note = [
        verification.note,
        `中国政府网国家规章库记录=${officialRuleRecord.record_id}；仅核验官方索引元数据，不代表全文核验。`,
      ].filter(Boolean).join("；");
    }
    if (sourceContentClass === "blocked_access_content") {
      verification.fulltext = "false";
      verification.status = verification.identity === "true"
        ? "IDENTITY_METADATA_VERIFIED_FULLTEXT_MISSING"
        : "BLOCKED_ACCESS";
      verification.note = [
        verification.note,
        "源Markdown正文为WZWS或JavaScript访问挑战页；仅保留法规身份和元数据，不发布正文。",
      ].filter(Boolean).join("；");
    }
    const verificationRow = {
      relative_path: relativePath,
      WJBS: firstMeta(meta, ["WJBS"]),
      WJBS_source_type: normalizeWjbsSourceType(firstMeta(meta, [
        "WJBS来源类型", "WJBS_source_type", "official_wjbs_source_type",
      ])),
      WJBS_verified: "false",
      WJBS_component_evidence: "",
      verification_status: verification.status,
      official_source_url: sourceUrl || (
        officialLawRecord
          ? `https://flk.npc.gov.cn/detail?id=${officialLawRecord.bbbs}`
          : (officialRuleRecord?.official_url ?? "")
      ),
      official_wjbs_source: verification.officialWjbsSource,
      official_wjbs_verified: verification.officialWjbsVerified,
      identity_verified: verification.identity,
      fulltext_verified: verification.fulltext,
      attachments_verified: verification.attachments,
      effect_verified: verification.effect,
      carrier_sha256: digest,
      normalized_text_sha256: fulltextAvailable
        ? sha256(Buffer.from(
            normalizeLegalTextForIdentity(sanitizeFormalText(body).text),
            "utf8",
          ))
        : "",
      verified_at: officialLawRecord
        ? flkMeta.fetched_at
        : (officialRuleRecord ? nationalRulesMeta.fetched_at : ""),
      note: verification.note,
    };
    rows["verification_results.csv"].push(verificationRow);
    verificationByPath.set(relativePath, verificationRow);
    attachmentRows.push(
      ...inlineDataImages.attachments.map((attachment, index) => ({
        source_relative_path: relativePath,
        attachment_reference: `INLINE_DATA_IMAGE:${index + 1}:${attachment.mimeType}:${attachment.label}`,
        attachment_relative_path: "",
        attachment_exists: "true",
        attachment_sha256: attachment.sha256,
        verification_status: "SOURCE_EMBEDDED_ATTACHMENT_HASHED_NOT_PUBLISHED",
      })),
      ...await attachmentReferences(body, fullPath),
    );

    if (objectType === "legal_document") {
      const localEffect = deriveEffectCode(firstMeta(meta, ["status", "时效性"]))
        ?? deriveLegacyFilenameMetadata(relativePath).effectCode;
      const officialEffect = mapFlkEffectCode(officialLawRecord?.sxx);
      if (localEffect && officialEffect && localEffect !== officialEffect) {
        rows["conflicts.csv"].push({
          relative_path: relativePath,
          conflict_type: "OFFICIAL_INDEX_EFFECT_CONFLICT",
          field_name: "SXX",
          local_value: localEffect,
          other_value: officialEffect,
          evidence: `国家法律法规数据库版本标识=${officialLawRecord.bbbs}；抓取时间=${flkMeta.fetched_at}`,
          disposition: "USE_OFFICIAL_INDEX_METADATA",
        });
      }
      const candidate = lawRow(
        meta,
        body,
        relativePath,
        title,
        officialLawRecord,
        officialRuleRecord,
        schema.tables["legal_documents.csv"].columns,
        metadataOverrides.get(relativePath),
        officialPageEvidence,
      );
      pendingLaws.push({
        candidate,
        meta,
        body,
        relativePath,
        sourceUrl,
        digest,
        officialLawRecord,
        officialRuleRecord,
        officialPageEvidence,
        normalizedTextSha256: verificationRow.normalized_text_sha256,
        coreProvisionSha256: (() => {
          const normalized = normalizeCoreProvisionsForCarrierIdentity(body);
          return normalized ? sha256(Buffer.from(normalized, "utf8")) : "";
        })(),
        normalizedTextLength: normalizeLegalTextForIdentity(
          sanitizeFormalText(body).text,
        ).length,
        fulltextAvailable,
        sourceContentClass,
      });
    } else if (objectType === "case") {
      const extractedCaseId = extractOfficialCaseId(meta, `${body}\n${title}`, relativePath);
      const caseId = isOfficialCaseId(extractedCaseId) ? extractedCaseId : "";
      const casePublicationDate = deriveCompleteDate(firstMeta(meta, [
        "publication_date", "发布日期", "入库日期",
      ])) || dateFromRelativePath(relativePath);
      const hasFulltext = !/##\s*待补正文/.test(body) && body.trim().length > 200;
      const normalizedCaseTextHash = sha256(Buffer.from(
        body
          .replace(/^#{1,6}\s+.*$/gm, "")
          .replace(/^>\s*(?:来源|原文链接)[：:].*$/gm, "")
          .replace(/\s+/g, "")
          .normalize("NFKC"),
        "utf8",
      ));
      const duplicateCase = caseId ? seenCaseIds.get(caseId) : undefined;
      if (!duplicateCase) {
        rows["cases.csv"].push({
          official_case_id: caseId,
          title,
          case_type: caseType(relativePath, meta),
          issuing_body: firstMeta(meta, [
            "法院名称", "发布机关", "author", "case_authority", "正式来源",
          ]),
          publication_date: casePublicationDate,
          decision_date: deriveCompleteDate(firstMeta(meta, ["decision_date", "裁判日期"])),
          docket_number: firstMeta(meta, ["docket_number", "案号"]) || (body.match(/(?:\*\*)?案号[：:]\*{0,2}\s*([^\r\n]+)/)?.[1]?.trim() ?? ""),
          keywords: firstMeta(meta, ["keywords", "关键词"]),
          source_url: sourceUrl,
          relative_path: relativePath,
          content_sha256: digest,
          has_fulltext: String(hasFulltext),
        });
        const holdings = relativePath.startsWith("04_") ? [] : extractHoldingSections(body);
        holdings.forEach((section, index) => {
          rows["case_holdings.csv"].push({
            official_case_id: caseId,
            title,
            holding_type: holdingType(section.heading),
            holding_ordinal: index + 1,
            holding_text: section.text,
            source_heading: section.heading,
            relative_path: relativePath,
          });
        });
        extractReferenceSections(body).forEach((section, index) => {
          rows["case_legal_references.csv"].push({
            official_case_id: caseId,
            title,
            reference_section: section.heading,
            reference_ordinal: index + 1,
            reference_text: section.text,
            relative_path: relativePath,
          });
        });
        const caseTargetRelativePath = await emitDerivedMarkdown({
          relativePath,
          objectType: "case",
          identifier: caseId,
          title,
          publicationDate: casePublicationDate,
          sourceSha256: digest,
          verificationStatus: verificationRow.verification_status,
          body,
        });
        verificationRow.note = [
          verificationRow.note,
          caseTargetRelativePath
            ? `最终Markdown=${caseTargetRelativePath}`
            : "最终Markdown路径冲突或无适用目录，已进入工程记录。",
        ].filter(Boolean).join("；");
      }
      rows["ingest_queue.csv"].push({
        relative_path: relativePath,
        object_type: objectType,
        ingest_status: duplicateCase
          ? (duplicateCase.normalizedHash === normalizedCaseTextHash
            ? "DUPLICATE_EQUIVALENT"
            : "SOURCE_CONFLICT")
          : "READY_CASE",
        blocking_reason: duplicateCase
          ? "DUPLICATE_OFFICIAL_CASE_ID"
          : "",
        target_table: "cases.csv",
        target_relative_path: duplicateCase
          ? ""
          : (markdownRows.at(-1)?.source_relative_path === relativePath
            ? markdownRows.at(-1).target_relative_path
            : ""),
        review_note: duplicateCase
          ? `与 ${duplicateCase.relativePath} 使用同一官方编号；未重复写入正式表。`
          : (caseId
            ? "使用源文件明示的官方案例编号。"
            : "无官方编号，字段留空；未用 IMA 标识或自行编号代替。"),
      });
      if (!caseId) {
        validationRows.push({
          relative_path: relativePath,
          table_name: "cases.csv",
          row_locator: relativePath,
          error_code: "MISSING_OFFICIAL_CASE_ID",
          severity: "INFO",
          field_name: "official_case_id",
          message: "未找到官方案例编号，已留空。",
        });
      } else if (duplicateCase) {
        const equivalent = duplicateCase.normalizedHash === normalizedCaseTextHash;
        rows["conflicts.csv"].push({
          relative_path: relativePath,
          conflict_type: "DUPLICATE_OFFICIAL_CASE_ID",
          field_name: "official_case_id",
          local_value: caseId,
          other_value: duplicateCase.relativePath,
          evidence: equivalent
            ? "去除标题层级、来源尾注和空白后的正文SHA-256一致"
            : "同批本地扫描；规范化正文SHA-256不同",
          disposition: equivalent
            ? "EXCLUDED_DUPLICATE_ALIAS"
            : "BLOCKED_REVIEW_DIFFERENT_CONTENT",
        });
      } else {
        seenCaseIds.set(caseId, {
          relativePath,
          normalizedHash: normalizedCaseTextHash,
        });
      }
    } else if (objectType === "practice_reference") {
      const referencePublicationDate = deriveCompleteDate(firstMeta(meta, [
        "publication_date", "发布日期", "date",
      ])) || dateFromRelativePath(relativePath);
      rows["practice_references.csv"].push({
        title,
        material_type: materialType(relativePath, meta),
        issuing_body: firstMeta(meta, ["author", "发布机关", "制定机关"]),
        publication_date: referencePublicationDate,
        source_url: sourceUrl,
        relative_path: relativePath,
        content_sha256: digest,
        default_legal_search: "false",
      });
      const referenceTargetRelativePath = await emitDerivedMarkdown({
        relativePath,
        objectType: "practice_reference",
        identifier: "",
        title,
        publicationDate: referencePublicationDate,
        sourceSha256: digest,
        verificationStatus: verificationRow.verification_status,
        body,
      });
      rows["ingest_queue.csv"].push({
        relative_path: relativePath,
        object_type: objectType,
        ingest_status: "READY_PRACTICE_REFERENCE",
        blocking_reason: "",
        target_table: "practice_references.csv",
        target_relative_path: referenceTargetRelativePath,
        review_note: "参考材料默认不参与法规检索。",
      });
    } else if (objectType === "legal_fragment") {
      const fragment = fragmentDescriptor(relativePath);
      const directory = path.posix.dirname(relativePath);
      const hasParent = fragment
        ? [...sourceRelativePaths].some((candidatePath) => (
          path.posix.dirname(candidatePath) === directory
          && path.posix.basename(candidatePath).startsWith(`${fragment.baseTitle}_`)
          && !fragmentDescriptor(candidatePath)
        ))
        : false;
      rows["ingest_queue.csv"].push({
        relative_path: relativePath,
        object_type: objectType,
        ingest_status: hasParent
          ? "REFERENCE_EXISTING_PARENT"
          : "BLOCKED_INCOMPLETE_FRAGMENT",
        blocking_reason: hasParent
          ? "NOT_INDEPENDENT_LEGAL_DOCUMENT"
          : "FRAGMENT_WITHOUT_COMPLETE_PARENT",
        target_table: "source_records.csv",
        target_relative_path: "",
        review_note: hasParent
          ? "同一法律文件已有完整母本；分册仅保留在只读源库，不生成独立WJBS或正式Markdown。"
          : "仅有不完整分册且无完整母本；保留源文件并阻断进入正式法律目录。",
      });
    } else {
      rows["ingest_queue.csv"].push({
        relative_path: relativePath,
        object_type: objectType,
        ingest_status: "OUT_OF_SCOPE_RETAIN_SOURCE",
        blocking_reason: "NOT_ADMITTED_TO_FINAL_CONTENT_TREE",
        target_table: "source_records.csv",
        target_relative_path: "",
        review_note: "源文件保留；未因所在目录自动纳入正式发布数据。",
      });
    }
    processed += 1;
    if (processed % 100 === 0) process.stdout.write(`processed ${processed}/${files.length}\n`);
  }

  const allPendingLaws = pendingLaws;
  const pendingLawByPath = new Map(
    allPendingLaws.map((entry) => [entry.relativePath, entry]),
  );
  const publicationPartition = partitionPublicationSkips(allPendingLaws, publicationSkips);
  const codingPendingLaws = publicationPartition.included;
  const skippedPublicationLaws = publicationPartition.skipped;
  const decisionsByEvent = new Map();
  for (const decision of officialDecisionOrderEvidence) {
    const eventKey = [decision.agencyCode, decision.promulgationDate].join("|");
    if (!decisionsByEvent.has(eventKey)) decisionsByEvent.set(eventKey, []);
    decisionsByEvent.get(eventKey).push(decision);
  }
  for (const entry of codingPendingLaws) {
    const row = entry.candidate;
    applyAcceptedCodingBaseline(entry, acceptedCodingBaseline);
    if (row.WJBS) continue;
    const eventKey = [row.ZDJGDM, row.GBRQ].join("|");
    let coding = decisionCodingForDocument({
      title: row.BT,
      sequenceCode: row._sequence_code,
      categoryCode: row.FLFGDZWJFLDM,
    }, decisionsByEvent.get(eventKey) ?? []);
    if (!coding) {
      const legacyPromulgationDate = standardDate(
        deriveLegacyFilenameMetadata(entry.relativePath).promulgationDate,
      );
      coding = decisionCodingForLegacyCarrier({
        title: row.BT,
        agencyCode: row.ZDJGDM,
        carrierPromulgationDate: row.GBRQ,
        legacyPromulgationDate,
        sequenceCode: row._sequence_code,
        categoryCode: row.FLFGDZWJFLDM,
      }, officialDecisionOrderEvidence);
      if (coding) {
        row.GBRQ = coding.promulgationDate;
        row._promulgation_source = "OFFICIAL_DECISION_MATCHED_LEGACY_FILENAME_DATE";
      }
    }
    if (!coding) continue;
    row._sequence_code = coding.sequenceCode;
    entry.officialDecisionOrder = coding.officialDecisionOrder;
    entry.decisionCanonicalTitle = coding.canonicalTitle;
    entry.decisionOrderEvidence = coding.decisionOrderEvidence;
  }
  const canonicalization = canonicalizeLegalVersions(codingPendingLaws.map((entry) => ({
    relativePath: entry.relativePath,
    title: entry.decisionCanonicalTitle ?? entry.candidate.BT,
    categoryCode: entry.candidate.FLFGDZWJFLDM,
    agencyName: entry.candidate.ZDJGMC,
    agencyCode: entry.candidate.ZDJGDM,
    promulgationDate: entry.candidate.GBRQ,
    sequenceCode: entry.candidate._sequence_code,
    fileTypeCode: entry.candidate.DE_01020,
    effectiveDate: entry.candidate.SXRQ,
    effectCode: entry.candidate.SXX,
    normalizedTextSha256: entry.normalizedTextSha256,
    coreProvisionSha256: entry.coreProvisionSha256,
    normalizedTextLength: entry.normalizedTextLength,
    wjbsSourceType: entry.wjbsSourceType || normalizeWjbsSourceType(firstMeta(entry.meta, [
      "WJBS来源类型", "WJBS_source_type", "official_wjbs_source_type",
    ])),
    officialIndexMatch: Boolean(entry.officialLawRecord),
    officialRuleIndexMatch: Boolean(entry.officialRuleRecord),
    officialPageEvidence: Boolean(entry.officialPageEvidence),
  })));
  pendingLaws = canonicalization.canonical.map(
    (entry) => pendingLawByPath.get(entry.relativePath),
  );
  const duplicateLegalVersions = canonicalization.duplicates.map((duplicate) => ({
    ...duplicate,
    entry: pendingLawByPath.get(duplicate.relativePath),
    canonicalEntry: pendingLawByPath.get(duplicate.canonicalRelativePath),
  }));
  const duplicateLegalPathSet = new Set(
    duplicateLegalVersions.map((duplicate) => duplicate.relativePath),
  );

  for (const entry of pendingLaws) {
    const row = entry.candidate;
    if (row.DE_01020 !== "30") continue;
    const decisionOrderValidation = validatedDecisionTitleOrder(row.BT, entry.body);
    const orderedTitles = decisionOrderValidation.orderedTitles;
    if (!orderedTitles.length) {
      rows["conflicts.csv"].push({
        relative_path: entry.relativePath,
        conflict_type: decisionOrderValidation.status === "DECLARED_TITLE_COUNT_MISMATCH"
          ? "LOCAL_DECISION_ORDER_DECLARED_COUNT_MISMATCH"
          : "LOCAL_DECISION_ORDER_NOT_EXTRACTABLE",
        field_name: "internal_sequence_code",
        local_value: String(decisionOrderValidation.extractedCount),
        other_value: decisionOrderValidation.expectedCount == null
          ? ""
          : String(decisionOrderValidation.expectedCount),
        evidence: `源Markdown SHA-256=${entry.digest}；官方索引=${entry.sourceUrl || entry.officialLawRecord?.bbbs || "未登记"}`,
        disposition: "EXCLUDED_FROM_DECISION_ORDER_EVIDENCE",
      });
      continue;
    }
    const eventKey = [row.ZDJGDM, row.GBRQ].join("|");
    if (!decisionsByEvent.has(eventKey)) decisionsByEvent.set(eventKey, []);
    decisionsByEvent.get(eventKey).push({
      relativePath: entry.relativePath,
      categoryCode: row.FLFGDZWJFLDM,
      sequenceCode: row._sequence_code,
      decisionTitle: row.BT,
      orderedTitles,
      sourceSha256: entry.digest,
      officialUrl: entry.sourceUrl || (entry.officialLawRecord?.bbbs
        ? `https://flk.npc.gov.cn/detail?id=${entry.officialLawRecord.bbbs}`
        : ""),
    });
  }

  const documentCodeGroups = new Map();
  const reservedWjbsOwners = new Map(
    pendingLaws
      .filter((entry) => entry.candidate.WJBS)
      .map((entry) => [entry.candidate.WJBS, entry.relativePath]),
  );
  for (const entry of pendingLaws) {
    const row = entry.candidate;
    const covered = STANDARD_CODE_SETS.gbt47277Categories.includes(row.FLFGDZWJFLDM);
    entry.codeScope = covered ? "GBT47277" : (
      STANDARD_CODE_SETS.electronicDocumentCategories.includes(row.FLFGDZWJFLDM)
        ? "GBT47229_2_ONLY"
        : "UNRESOLVED"
    );
    entry.wjbsSourceType ||= normalizeWjbsSourceType(firstMeta(entry.meta, [
      "WJBS来源类型", "WJBS_source_type", "official_wjbs_source_type",
    ]));
    if (row.WJBS) {
      const bodyMatch = /^1\.2\.156\.3005\.6-(\d{31})$/.exec(row.WJBS);
      if (bodyMatch) {
        entry.internalSequence = bodyMatch[1].slice(26, 29);
        entry.officialDecisionOrder = Number(entry.internalSequence);
        entry.existingWjbsLocked = true;
        if (covered) row.DE_01001 ||= bodyMatch[1];
      }
      const lockedComponents = [
        row.FLFGDZWJFLDM,
        row.ZDJGDM,
        row.GBRQ,
        row._sequence_code,
        row.DE_01020,
      ];
      if (entry.codeScope !== "UNRESOLVED" && lockedComponents.every(Boolean)) {
        const lockedKey = lockedComponents.join("|");
        if (!documentCodeGroups.has(lockedKey)) documentCodeGroups.set(lockedKey, []);
        documentCodeGroups.get(lockedKey).push(entry);
      }
      continue;
    }
    entry.title = row.BT;
    if (!Number.isInteger(entry.officialDecisionOrder)) {
      const eventKey = [row.ZDJGDM, row.GBRQ].join("|");
      const coding = decisionCodingForDocument({
        title: row.BT,
        sequenceCode: row._sequence_code,
        categoryCode: row.FLFGDZWJFLDM,
      }, decisionsByEvent.get(eventKey) ?? []);
      if (coding) {
        row._sequence_code = coding.sequenceCode;
        entry.officialDecisionOrder = coding.officialDecisionOrder;
        entry.decisionCanonicalTitle = coding.canonicalTitle;
        entry.decisionOrderEvidence = coding.decisionOrderEvidence;
      }
    }
    const components = [
      row.FLFGDZWJFLDM,
      row.ZDJGDM,
      row.GBRQ,
      row._sequence_code,
      row.DE_01020,
    ];
    if (entry.codeScope === "UNRESOLVED" || components.some((value) => !value)) continue;
    const key = components.join("|");
    if (!documentCodeGroups.has(key)) documentCodeGroups.set(key, []);
    documentCodeGroups.get(key).push(entry);
  }
  for (const [componentGroupKey, group] of documentCodeGroups) {
    const currentGroupPaths = new Set(group.map((entry) => entry.relativePath));
    const externalComponentOwners = [...(exactComponentContext.get(componentGroupKey) ?? [])]
      .filter((relativePath) => !currentGroupPaths.has(relativePath));
    for (const assignment of assignInternalSequenceGroup(group)) {
      const entry = assignment.entry;
      const row = entry.candidate;
      if (entry.existingWjbsLocked) continue;
      const incompleteExactGroupContext = Boolean(exactScopeArgument)
        && assignment.source === "UNIQUE_COMPONENTS"
        && (!componentContextArgument || externalComponentOwners.length > 0)
        && !row.WJBS;
      entry.internalSequence = incompleteExactGroupContext ? "" : assignment.internalSequence;
      entry.internalSequenceSource = incompleteExactGroupContext
        ? "BLOCKED_INCOMPLETE_EXACT_GROUP_CONTEXT"
        : assignment.source;
      if (incompleteExactGroupContext) continue;
      if (assignment.source === "BLOCKED_AUTHORITY_ASSIGNED_INTERNAL_SEQUENCE") {
        rows["conflicts.csv"].push({
          relative_path: entry.relativePath,
          conflict_type: "AUTHORITY_ASSIGNED_INTERNAL_SEQUENCE_REQUIRED",
          field_name: "internal_sequence_code",
          local_value: Number.isInteger(entry.officialDecisionOrder)
            ? String(entry.officialDecisionOrder)
            : "",
          other_value: String(group.length),
          evidence: entry.decisionOrderEvidence || "同组件组内决定表述顺序重复，无法形成唯一内部顺序码",
          disposition: "EXCLUDED_FROM_FORMAL_STANDARD_CODE",
        });
      }
      if (!assignment.internalSequence) continue;
      const proposedWjbs = buildWjbs({
        category: row.FLFGDZWJFLDM,
        agency: row.ZDJGDM,
        promulgationDate: row.GBRQ,
        sequence: row._sequence_code,
        internalSequence: entry.internalSequence,
        fileCategory: row.DE_01020,
      });
      const reservedOwner = reservedWjbsOwners.get(proposedWjbs);
      if (reservedOwner && !duplicateLegalPathSet.has(entry.relativePath)) {
        entry.internalSequence = "";
        entry.internalSequenceSource = "BLOCKED_ACCEPTED_WJBS_COLLISION";
        rows["conflicts.csv"].push({
          relative_path: entry.relativePath,
          conflict_type: "ACCEPTED_WJBS_COLLISION",
          field_name: "WJBS",
          local_value: proposedWjbs,
          other_value: reservedOwner,
          evidence: "已验收且源哈希未变的正式WJBS占用相同编码组合",
          disposition: "BLOCKED_REVIEW",
        });
        continue;
      }
      entry.wjbsSourceType = "STANDARD_DERIVED_LOCAL";
      row.WJBS = proposedWjbs;
      reservedWjbsOwners.set(proposedWjbs, entry.relativePath);
      if (entry.codeScope === "GBT47277") {
        row.DE_01001 ||= build47277FileCode({
          category: row.FLFGDZWJFLDM,
          agency: row.ZDJGDM,
          promulgationDate: row.GBRQ,
          sequence: row._sequence_code,
          internalSequence: entry.internalSequence,
          fileType: row.DE_01020,
        });
      }
    }
  }

  for (const entry of skippedPublicationLaws) {
    const candidate = entry.candidate;
    const covered = STANDARD_CODE_SETS.gbt47277Categories.includes(candidate.FLFGDZWJFLDM);
    const codeScope = covered ? "GBT47277" : (
      STANDARD_CODE_SETS.electronicDocumentCategories.includes(candidate.FLFGDZWJFLDM)
        ? "GBT47229_2_ONLY"
        : "UNRESOLVED"
    );
    const skip = entry.publicationSkip;
    const skipStatus = `SKIPPED_FORMAL_EXPORT_${skip.skipCode}`;
    const skipWarning = `SKIPPED_${skip.skipCode}`;
    codingRows.push({
      relative_path: entry.relativePath,
      canonical_relative_path: "",
      official_version_id: entry.officialLawRecord?.bbbs ?? "",
      official_index_match: entry.officialLawRecord ? "true" : "false",
      official_effect_code: mapFlkEffectCode(entry.officialLawRecord?.sxx),
      official_rule_record_id: entry.officialRuleRecord?.record_id ?? "",
      official_rule_index_match: entry.officialRuleRecord ? "true" : "false",
      WJBS: "",
      WJBS_source_type: "",
      category_code: candidate.FLFGDZWJFLDM,
      agency_name: candidate.ZDJGMC,
      agency_name_source: candidate._agency_name_source,
      agency_code: candidate.ZDJGDM,
      agency_code_source: candidate._agency_code_source,
      promulgation_date: candidate.GBRQ,
      promulgation_source: candidate._promulgation_source,
      effective_date: candidate.SXRQ,
      effective_date_source: candidate._effective_date_source,
      effect_code: candidate.SXX,
      effect_source: candidate._effect_source,
      sequence_code: candidate._sequence_code,
      internal_sequence_code: "",
      internal_sequence_source: skipStatus,
      decision_order_evidence: "",
      metadata_override_evidence: candidate._metadata_override_evidence,
      official_page_evidence: candidate._official_page_evidence,
      accepted_coding_evidence: "",
      file_code_31: "",
      file_type_code: candidate.DE_01020,
      code_scope: codeScope,
      coding_status: "SKIPPED",
      blocking_reason: skip.skipCode,
    });
    rows["ingest_queue.csv"].push({
      relative_path: entry.relativePath,
      object_type: "legal_document",
      ingest_status: skipStatus,
      blocking_reason: skip.skipCode,
      target_table: "legal_documents.csv",
      target_relative_path: "",
      review_note: `${skip.rationale}；源文件、SHA-256及核验状态保留，不生成正式表记录或Markdown派生文件。`,
    });
    validationRows.push({
      relative_path: entry.relativePath,
      table_name: "legal_documents.csv",
      row_locator: entry.relativePath,
      error_code: skipWarning,
      severity: "WARNING",
      field_name: "WJBS",
      message: `${skip.rationale}；这是已登记的正式发布跳过项，不阻断其他合格数据。`,
    });
    const verificationRow = verificationByPath.get(entry.relativePath);
    if (verificationRow) {
      verificationRow.note = [
        verificationRow.note,
        `${skipStatus}：${skip.rationale}`,
      ].filter(Boolean).join("；");
    }
  }

  for (const duplicate of duplicateLegalVersions) {
    const { entry, canonicalEntry, canonicalRelativePath, reason } = duplicate;
    const duplicateNote = reason === "DUPLICATE_NORMALIZED_LEGAL_VERSION_OFFICIAL_METADATA_RESOLVED"
      ? `与 ${canonicalRelativePath} 的规范化正文及其余法律身份要素相同；冲突效力和施行日期字段以唯一命中的官方索引记录为准，该文件作为重复载体留痕。`
      : `与 ${canonicalRelativePath} 的法律身份要素及规范化正文SHA-256完全相同；作为重复载体留痕，不生成第二个正式法律对象。`;
    const candidate = entry.candidate;
    const canonicalCandidate = canonicalEntry.candidate;
    entry.codeScope = canonicalEntry.codeScope;
    entry.internalSequence = canonicalEntry.internalSequence;
    entry.internalSequenceSource = "REFERENCE_EXISTING_CANONICAL";
    entry.wjbsSourceType = canonicalEntry.wjbsSourceType;
    candidate.WJBS = canonicalCandidate.WJBS;
    candidate.DE_01001 = canonicalCandidate.DE_01001;
    candidate._sequence_code = canonicalCandidate._sequence_code;
    const verificationRow = verificationByPath.get(entry.relativePath);
    if (verificationRow) {
      verificationRow.WJBS = canonicalCandidate.WJBS;
      verificationRow.WJBS_source_type = canonicalEntry.wjbsSourceType;
      verificationRow.WJBS_verified = String(Boolean(canonicalCandidate.WJBS));
      verificationRow.WJBS_component_evidence = JSON.stringify({
        canonical_relative_path: canonicalRelativePath,
        duplicate_reason: reason,
        normalized_text_sha256: entry.normalizedTextSha256,
      });
      verificationRow.note = [
        verificationRow.note,
        duplicateNote,
      ].filter(Boolean).join("；");
    }
    codingRows.push({
      relative_path: entry.relativePath,
      canonical_relative_path: canonicalRelativePath,
      official_version_id: entry.officialLawRecord?.bbbs ?? "",
      official_index_match: entry.officialLawRecord ? "true" : "false",
      official_effect_code: mapFlkEffectCode(entry.officialLawRecord?.sxx),
      official_rule_record_id: entry.officialRuleRecord?.record_id ?? "",
      official_rule_index_match: entry.officialRuleRecord ? "true" : "false",
      WJBS: canonicalCandidate.WJBS,
      WJBS_source_type: canonicalEntry.wjbsSourceType,
      category_code: candidate.FLFGDZWJFLDM,
      agency_name: candidate.ZDJGMC,
      agency_name_source: candidate._agency_name_source,
      agency_code: candidate.ZDJGDM,
      agency_code_source: candidate._agency_code_source,
      promulgation_date: candidate.GBRQ,
      promulgation_source: candidate._promulgation_source,
      effective_date: candidate.SXRQ,
      effective_date_source: candidate._effective_date_source,
      effect_code: candidate.SXX,
      effect_source: candidate._effect_source,
      sequence_code: candidate._sequence_code,
      internal_sequence_code: canonicalEntry.internalSequence ?? "",
      internal_sequence_source: "REFERENCE_EXISTING_CANONICAL",
      decision_order_evidence: canonicalEntry.decisionOrderEvidence ?? "",
      metadata_override_evidence: candidate._metadata_override_evidence,
      official_page_evidence: candidate._official_page_evidence,
      accepted_coding_evidence: canonicalEntry.acceptedCodingEvidence ?? "",
      file_code_31: canonicalCandidate.DE_01001,
      file_type_code: candidate.DE_01020,
      code_scope: canonicalEntry.codeScope,
      coding_status: "REFERENCE_EXISTING_CANONICAL",
      blocking_reason: reason,
    });
  }

  for (const {
    candidate,
    meta,
    body,
    relativePath,
    digest,
    officialLawRecord,
    officialRuleRecord,
    officialPageEvidence,
    codeScope,
    codeError,
    internalSequence,
    internalSequenceSource,
    decisionOrderEvidence,
    wjbsSourceType,
    acceptedCodingEvidence,
    fulltextAvailable,
    sourceContentClass,
  }
    of pendingLaws) {
    if (duplicateLegalPathSet.has(relativePath)) continue;
    const lawErrors = validateLawRow(candidate, wjbsSourceType, {
      fulltextAvailable,
    });
    if (codeError) lawErrors.push({ code: codeError, field: "DE_01001" });
    codingRows.push({
      relative_path: relativePath,
      canonical_relative_path: "",
      official_version_id: officialLawRecord?.bbbs ?? "",
      official_index_match: officialLawRecord ? "true" : "false",
      official_effect_code: mapFlkEffectCode(officialLawRecord?.sxx),
      official_rule_record_id: officialRuleRecord?.record_id ?? "",
      official_rule_index_match: officialRuleRecord ? "true" : "false",
      WJBS: candidate.WJBS,
      WJBS_source_type: wjbsSourceType,
      category_code: candidate.FLFGDZWJFLDM,
      agency_name: candidate.ZDJGMC,
      agency_name_source: candidate._agency_name_source,
      agency_code: candidate.ZDJGDM,
      agency_code_source: candidate._agency_code_source,
      promulgation_date: candidate.GBRQ,
      promulgation_source: candidate._promulgation_source,
      effective_date: candidate.SXRQ,
      effective_date_source: candidate._effective_date_source,
      effect_code: candidate.SXX,
      effect_source: candidate._effect_source,
      sequence_code: candidate._sequence_code,
      internal_sequence_code: internalSequence ?? "",
      internal_sequence_source: internalSequenceSource ?? "",
      decision_order_evidence: decisionOrderEvidence ?? "",
      metadata_override_evidence: candidate._metadata_override_evidence,
      official_page_evidence: candidate._official_page_evidence,
      accepted_coding_evidence: acceptedCodingEvidence ?? "",
      file_code_31: candidate.DE_01001,
      file_type_code: candidate.DE_01020,
      code_scope: codeScope,
      coding_status: lawErrors.length ? "BLOCKED" : "READY",
      blocking_reason: lawErrors
        .map((error) => `${error.code}:${error.field}`)
        .join("|"),
    });
    const verificationRow = verificationByPath.get(relativePath);
    if (verificationRow && candidate.WJBS) {
      const wjbsErrors = validateWjbs(candidate.WJBS, { sourceType: wjbsSourceType });
      verificationRow.WJBS = candidate.WJBS;
      verificationRow.WJBS_source_type = wjbsSourceType;
      verificationRow.WJBS_verified = String(wjbsErrors.length === 0);
      verificationRow.WJBS_component_evidence = JSON.stringify({
        category_code: candidate.FLFGDZWJFLDM,
        agency_code: candidate.ZDJGDM,
        agency_code_source: candidate._agency_code_source,
        promulgation_date: candidate.GBRQ,
        promulgation_source: candidate._promulgation_source,
        sequence_code: candidate._sequence_code,
        internal_sequence_code: internalSequence ?? "",
        internal_sequence_source: internalSequenceSource ?? "",
        decision_order_evidence: decisionOrderEvidence ?? "",
        metadata_override_evidence: candidate._metadata_override_evidence,
        official_page_evidence: candidate._official_page_evidence,
        accepted_coding_evidence: acceptedCodingEvidence ?? "",
        file_category_code: candidate.DE_01020,
      });
      if (wjbsSourceType === "STANDARD_DERIVED_LOCAL") {
        const internalSequenceNote = internalSequenceSource === "SOURCE_DECISION_BODY_ORDER"
          ? "内部顺序码来自本地来源中公布或修改决定正文的排列次序，并保留决定文件路径证据。"
          : `内部顺序码来源：${internalSequenceSource || "已有编码要素"}。`;
        verificationRow.note = [
          verificationRow.note,
          "官方未提供WJBS；按GB/T 47229.2编码要素生成并标记为本地派生。",
          internalSequenceNote,
        ].filter(Boolean).join("；");
      }
    }
    const publicationErrors = [];
    let structureRows = [];
    let structureFailure = "";
    if (codeScope === "GBT47277" && fulltextAvailable) {
      try {
        structureRows = extractLegalContentRows(body);
        const duplicateStructureCodes = duplicateContentStructureCodes(
          structureRows,
        );
        if (duplicateStructureCodes.length) {
          structureFailure = "CONTENT_STRUCTURE_DUPLICATE";
          structureRows = [];
        }
      } catch (error) {
        structureFailure = String(error?.message || "CONTENT_STRUCTURE_PARSE_ERROR");
      }
    }
    publicationErrors.push(...contentStructurePublicationErrors({
      codeScope,
      structureRows,
      structureFailure,
    }));

    const publicationDecision = formalLawPublicationDecision({
      lawErrors,
      publicationErrors,
      fulltextAvailable,
    });
    const formalErrors = publicationDecision.formalErrors;
    const contentErrors = publicationDecision.contentErrors;
    delete candidate._sequence_code;
    delete candidate._agency_code_source;
    delete candidate._agency_name_source;
    delete candidate._promulgation_source;
    delete candidate._metadata_override_evidence;
    delete candidate._official_page_evidence;
    delete candidate._effective_date_source;
    delete candidate._effect_source;
    if (publicationDecision.publishFormal) {
      rows["legal_documents.csv"].push(candidate);
      for (const contentRow of publicationDecision.emitStructuredContents ? structureRows : []) {
        rows["legal_contents.csv"].push({
          DE_01001: candidate.DE_01001,
          ...contentRow,
        });
      }
      const lawTargetRelativePath = publicationDecision.emitMarkdown
        ? await emitDerivedMarkdown({
            relativePath,
            objectType: "legal_document",
            identifier: candidate.WJBS,
            title: candidate.BT,
            publicationDate: candidate.GBRQ,
            effectCode: candidate.SXX,
            categoryCode: candidate.FLFGDZWJFLDM,
            agencyName: candidate.ZDJGMC,
            sourceSha256: digest,
            verificationStatus: verificationRow.verification_status,
            body,
          })
        : "";
      const currentEntry = pendingLawByPath.get(relativePath);
      if (currentEntry) currentEntry.targetRelativePath = lawTargetRelativePath;
      rows["ingest_queue.csv"].push({
        relative_path: relativePath,
        object_type: "legal_document",
        ingest_status: publicationDecision.ingestStatus,
        blocking_reason: "",
        target_table: "legal_documents.csv",
        target_relative_path: lawTargetRelativePath,
        review_note: sourceContentClass === "blocked_access_content"
          ? "法规身份和元数据已核验并完成确定性编码；全文缺失，不补抓、不生成正文行或Markdown，挑战页仅留工程记录。"
          : contentErrors.length
            ? "法律元数据和WJBS已通过；全文Markdown保留，但正文结构码冲突，未生成legal_contents行，冲突留工程记录。"
            : "现有本地源文件已完成国标字段、确定性编码、正文结构和源文件SHA-256迁移；联网核验状态独立保留。",
      });
      for (const error of contentErrors) {
        validationRows.push({
          relative_path: relativePath,
          table_name: "legal_contents.csv",
          row_locator: relativePath,
          error_code: error.code,
          severity: "WARNING",
          field_name: error.field,
          message: `正文结构未物化，不影响法律元数据入库：${error.code}。`,
        });
      }
      if (seenWjbs.has(candidate.WJBS)) {
        rows["conflicts.csv"].push({
          relative_path: relativePath,
          conflict_type: "DUPLICATE_WJBS",
          field_name: "WJBS",
          local_value: candidate.WJBS,
          other_value: seenWjbs.get(candidate.WJBS),
          evidence: "同批本地扫描",
          disposition: "BLOCKED_REVIEW",
        });
      } else {
        seenWjbs.set(candidate.WJBS, relativePath);
      }
    } else {
      const missing = formalErrors
        .filter((error) => error.code === "MISSING_STANDARD_FIELD")
        .map((error) => error.field);
      rows["ingest_queue.csv"].push({
        relative_path: relativePath,
        object_type: "legal_document",
        ingest_status: publicationDecision.ingestStatus,
        blocking_reason: formalErrors
          .map((error) => `${error.code}:${error.field}`)
          .join("|"),
        target_table: "legal_documents.csv",
        target_relative_path: publicationDecision.targetRelativePath,
        review_note: missing.length
          ? `缺少国标必选字段：${missing.join("、")}；仅在编码要素完整且来源可追溯时确定性生成WJBS。`
          : "本地迁移门禁未全部通过，未进入正式表。",
      });
      for (const error of formalErrors) {
        validationRows.push({
          relative_path: relativePath,
          table_name: "legal_documents.csv",
          row_locator: relativePath,
          error_code: error.code,
          severity: "ERROR",
          field_name: error.field,
          message: error.code === "MISSING_STANDARD_FIELD"
            ? `缺少国标必选字段 ${error.field}。`
            : `字段 ${error.field} 未通过正式发布门禁：${error.code}。`,
        });
      }
    }
  }

  for (const duplicate of duplicateLegalVersions) {
    rows["ingest_queue.csv"].push({
      relative_path: duplicate.relativePath,
      object_type: "legal_document",
      ingest_status: "REFERENCE_EXISTING_CANONICAL",
      blocking_reason: duplicate.reason,
      target_table: "legal_documents.csv",
      target_relative_path: duplicate.canonicalEntry.targetRelativePath ?? "",
      review_note: duplicate.reason === "DUPLICATE_NORMALIZED_LEGAL_VERSION_OFFICIAL_METADATA_RESOLVED"
        ? `规范化正文及其余法律身份要素与 ${duplicate.canonicalRelativePath} 相同；冲突效力和施行日期字段以唯一命中的官方索引记录为准。源文件、来源ID和哈希逐份保留。`
        : `规范化正文及法律身份要素与 ${duplicate.canonicalRelativePath} 完全相同；源文件、来源ID和哈希逐份保留，正式数据仅发布一个规范对象。`,
    });
  }

  const outputs = [];
  for (const [tableName, tableSchema] of Object.entries(schema.tables)) {
    const isFormal = formalTables.has(tableName);
    const targetDir = isFormal ? formalDir : engineeringDir;
    const targetPath = path.join(targetDir, tableName);
    await fsp.writeFile(targetPath, csvText(tableSchema.columns, rows[tableName]), "utf8");
    outputs.push({
      table: tableName,
      path: targetPath,
      rows: rows[tableName].length,
      area: isFormal ? "FORMAL" : "ENGINEERING",
    });
  }

  const batchOutputs = [];
  async function writeBatchCsv(name, columns, batchRows) {
    const targetPath = path.join(batchDir, name);
    await fsp.writeFile(targetPath, csvText(columns, batchRows), "utf8");
    batchOutputs.push({ table: name, path: targetPath, rows: batchRows.length });
  }
  await writeBatchCsv(
    "标准编码生成清单.csv",
    [
      "relative_path", "canonical_relative_path", "official_version_id", "official_index_match",
      "official_effect_code", "official_rule_record_id",
      "official_rule_index_match", "WJBS", "WJBS_source_type", "category_code",
      "agency_name", "agency_name_source", "agency_code", "agency_code_source",
      "promulgation_date", "promulgation_source",
      "effective_date", "effective_date_source", "effect_code", "effect_source",
      "sequence_code", "internal_sequence_code",
      "internal_sequence_source", "decision_order_evidence",
      "metadata_override_evidence", "official_page_evidence",
      "accepted_coding_evidence",
      "file_code_31", "file_type_code", "code_scope", "coding_status",
      "blocking_reason",
    ],
    codingRows,
  );
  await writeBatchCsv(
    "来源核验状态清单.csv",
    schema.tables["verification_results.csv"].columns,
    rows["verification_results.csv"],
  );
  await writeBatchCsv(
    "附件清单.csv",
    [
      "source_relative_path", "attachment_reference", "attachment_relative_path",
      "attachment_exists", "attachment_sha256", "verification_status",
    ],
    attachmentRows,
  );
  await writeBatchCsv(
    "Markdown派生清单.csv",
    [
      "source_relative_path", "target_relative_path", "object_type", "identifier",
      "storage_key_type", "source_sha256", "derived_sha256", "transformations",
    ],
    markdownRows,
  );
  const markdownOutputs = markdownRows.map((row) => ({
    table: "Markdown",
    path: path.join(deliveryRoot, row.target_relative_path),
    rows: "",
  }));
  const rollbackRows = [
    ...outputs.filter((output) => output.area === "FORMAL"),
    ...markdownOutputs,
  ].map((output) => ({
    action: "CREATE_CANDIDATE_FILE",
    relative_path: path.relative(candidateFinalRoot, output.path).split(path.sep).join("/"),
    reverse_action: "DELETE_CANDIDATE_FILE",
    preexisting_target: "false",
  }));
  await writeBatchCsv(
    "回滚清单.csv",
    ["action", "relative_path", "reverse_action", "preexisting_target"],
    rollbackRows,
  );

  const artifactValidation = [];
  for (const output of outputs) {
    try {
      const result = await validateCsvWithArtifactTool(output.path, output.rows);
      artifactValidation.push({ table: output.table, ok: true, sheet: result.sheet });
    } catch (error) {
      artifactValidation.push({
        table: output.table,
        ok: false,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  const formalAbsolutePathHits = [];
  const formalPollutionHits = [];
  for (const tableName of formalTables) {
    const targetPath = path.join(formalDir, tableName);
    const outputText = await fsp.readFile(targetPath, "utf8");
    if (absolutePathPattern.test(outputText)) formalAbsolutePathHits.push(tableName);
    if (fixedPollutionPattern.test(outputText)) formalPollutionHits.push(tableName);
  }
  const blockedLaws = rows["ingest_queue.csv"].filter(
    (row) => row.object_type === "legal_document"
      && row.ingest_status.startsWith("BLOCKED_"),
  ).length;
  const skippedLaws = rows["ingest_queue.csv"].filter(
    (row) => row.object_type === "legal_document"
      && row.ingest_status.startsWith("SKIPPED_FORMAL_EXPORT_"),
  ).length;
  const failedArtifactTables = artifactValidation.filter((item) => !item.ok);
  const status = exactScopeArgument
    ? "TARGET_GATE_AUDIT_ONLY"
    : (blockedLaws > 0 || failedArtifactTables.length > 0 ? "PARTIAL_OK" : "PASS");
  const summary = {
    generated_at: new Date().toISOString(),
    status,
    scope: exactScopeArgument
      ? exactPathBaselineArgument
        ? "EXACT_PATH_GATE_ONLY"
        : "WJBS_TARGET_GATE_ONLY"
      : "LOCAL_ONLY",
    enumeration_mode: scopeDescriptor.enumeration_mode,
    full_corpus_enumerated: scopeDescriptor.full_corpus_enumerated,
    github_touched: false,
    source_roots: scopeDescriptor.source_roots,
    source_files: scopeDescriptor.source_files,
    outputs: outputs.map((output) => ({
      table: output.table,
      rows: output.rows,
      area: output.area,
      relative_path: path.relative(
        output.area === "FORMAL" ? candidateFinalRoot : engineeringDir,
        output.path,
      ).replaceAll("\\", "/"),
    })),
    batch_outputs: batchOutputs.map((output) => ({
      table: output.table,
      rows: output.rows,
      relative_path: path.relative(engineeringDir, output.path).split(path.sep).join("/"),
    })),
    gates: {
      schema_table_count: Object.keys(schema.tables).length,
      expected_table_count: 13,
      publishable_full_scope: !exactScopeArgument,
      blocked_legal_documents: blockedLaws,
      skipped_legal_documents: skippedLaws,
      markdown_derivatives: markdownRows.length,
      formal_absolute_path_hits: formalAbsolutePathHits,
      formal_fixed_pollution_hits: formalPollutionHits,
      artifact_tool: artifactValidation,
    },
    boundary: "法律元数据与正文分层发布：找不到全文时不补全文，确定性编码合格后进入legal_documents.csv且不生成伪正文；正文结构失败只阻断legal_contents.csv，不阻断合格法律元数据；挑战页不得作为正文；案例不赋WJBS，无官方案例编号时留空。",
  };
  await fsp.writeFile(
    path.join(engineeringDir, "build_summary.json"),
    `${JSON.stringify(summary, null, 2)}\n`,
    "utf8",
  );
  const reportLines = [
    "# 本地 CSV 首轮构建校验报告",
    "",
    `- 状态：\`${status}\``,
    `- 范围：${exactScopeArgument ? "精确路径专项门禁（不可发布）" : "本地"}；GitHub 未触碰`,
    `- 扫描 Markdown：${files.length}`,
    `- 生成 CSV：${outputs.length}`,
    `- 被国标字段或正式发布门禁阻断的法律法规：${blockedLaws}`,
    `- 已登记跳过正式编码且不阻断其他数据的法律法规：${skippedLaws}`,
    `- Markdown派生文件：${markdownRows.length}`,
    `- 正式表绝对本地路径命中：${formalAbsolutePathHits.length}`,
    `- 正式表固定平台污染命中：${formalPollutionHits.length}`,
    `- Artifact Tool 校验失败表：${failedArtifactTables.length}`,
    "",
    "## 表行数",
    "",
    "| 表 | 数据行 |",
    "| --- | ---: |",
    ...outputs.map((output) => `| ${output.table} | ${output.rows} |`),
    "",
    "## 边界",
    "",
    "- 法律法规：未满足编码必选字段不进入正式元数据表，不补造 WJBS、机关代码或分类代码。",
    "- 正文：找不到全文时不补全文、不生成伪正文；结构码失败时保留Markdown并仅跳过legal_contents结构行。",
    "- 案例：只登记源文件明示的官方编号；无编号留空，不使用 IMA 标识替代。",
    "- 仲裁案例：不把“结语和建议”当作裁判要旨。",
    "- 正文只交付Markdown派生文件，不输出DOCX、PDF、OFD或UOF；Markdown不冒充国标主交换文件。",
    "",
  ];
  await fsp.writeFile(
    path.join(engineeringDir, "validation_report.md"),
    reportLines.join("\n"),
    "utf8",
  );
  const readmePath = path.join(candidateFinalRoot, "README.md");
  await fsp.writeFile(
    readmePath,
    [
      "# 中国法律法规与官方案例本地标准化数据集",
      "",
      "- 正文载体：Markdown。",
      "- 法律法规数据元与编码：按GB/T 47229.2—2026、GB/T 47277—2026适用范围生成。",
      "- Markdown为检索派生载体，不冒充GB/T 47229.2主交换文件。",
      "- 案例不赋WJBS；无官方案例编号时保持空值。",
      "- 来源核验状态、冲突和人工队列保存在物理隔离的工程记录中。",
      "",
    ].join("\n"),
    "utf8",
  );
  const filesBeforeChecksums = await listAllFiles(candidateFinalRoot);
  const checksumLines = [];
  for (const filePath of filesBeforeChecksums) {
    const relativePath = path.relative(candidateFinalRoot, filePath).split(path.sep).join("/");
    checksumLines.push(`${sha256(await fsp.readFile(filePath))}  ${relativePath}`);
  }
  checksumLines.sort((a, b) => a.localeCompare(b, "en"));
  const checksumsPath = path.join(candidateFinalRoot, "SHA256SUMS");
  await fsp.writeFile(checksumsPath, `${checksumLines.join("\n")}\n`, "utf8");

  const manifestCandidates = await listAllFiles(candidateFinalRoot);
  const exchangeRows = [];
  for (const filePath of manifestCandidates) {
    const buffer = await fsp.readFile(filePath);
    const tableName = path.basename(filePath);
    const output = outputs.find((item) => item.path === filePath);
    exchangeRows.push({
      relative_path: path.relative(candidateFinalRoot, filePath).split(path.sep).join("/"),
      byte_size: buffer.length,
      sha256: sha256(buffer),
      row_count: output?.rows ?? (tableName.endsWith(".csv") ? "" : ""),
    });
  }
  await writeBatchCsv(
    "正式发布清单.csv",
    ["relative_path", "byte_size", "sha256", "row_count"],
    exchangeRows,
  );
  process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
}

main().then(
  () => process.exit(0),
  (error) => {
    process.stderr.write(`${error.stack ?? error}\n`);
    process.exit(1);
  },
);
