import fs from "node:fs";
import readline from "node:readline";

function argument(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : "";
}

function parseCsvLine(line) {
  const fields = [];
  let value = "";
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (character === '"') {
      if (quoted && line[index + 1] === '"') {
        value += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (character === "," && !quoted) {
      fields.push(value);
      value = "";
    } else {
      value += character;
    }
  }
  fields.push(value);
  return fields;
}

async function scanCsv(filePath, requiredHeaders, role, visit) {
  const input = fs.createReadStream(filePath, "utf8");
  const lines = readline.createInterface({ input, crlfDelay: Infinity });
  let headers;
  for await (const line of lines) {
    if (!headers) {
      headers = parseCsvLine(line.replace(/^\uFEFF/, ""));
      const missingHeaders = requiredHeaders.filter((header) => !headers.includes(header));
      if (missingHeaders.length) {
        throw new Error(
          `${role}不是所需 CSV：${filePath}；缺少必需字段：${missingHeaders.join(", ")}`,
        );
      }
      continue;
    }
    if (!line) continue;
    const values = parseCsvLine(line);
    const row = Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""]));
    visit(row);
  }
  if (!headers) throw new Error(`${role}为空文件：${filePath}`);
}

const codingManifestHeaders = [
  "relative_path",
  "WJBS",
  "internal_sequence_source",
  "coding_status",
  "blocking_reason",
  "category_code",
  "agency_code",
  "promulgation_date",
  "sequence_code",
  "file_type_code",
];

function label(row) {
  if (!row) return "OUT_OF_STANDARD_SCOPE";
  if (row.coding_status === "REFERENCE_EXISTING_CANONICAL") {
    return "REFERENCE_EXISTING_CANONICAL";
  }
  if (row.coding_status === "BLOCKED" && row.WJBS) {
    return /SXX/.test(row.blocking_reason)
      ? "BLOCKED_EFFECT_METADATA"
      : "BLOCKED_WITH_WJBS";
  }
  if (row.WJBS && /DECISION|SOURCE/.test(row.internal_sequence_source)) return "WJBS_DECISION";
  if (row.WJBS) return "WJBS_UNIQUE";
  if (/ZDJGDM/.test(row.blocking_reason)) return "BLOCKED_AGENCY";
  return "BLOCKED_SEQUENCE";
}

function countLabels(paths, currentByPath) {
  const counts = new Map();
  for (const relativePath of paths) {
    const current = label(currentByPath.get(relativePath));
    counts.set(current, (counts.get(current) ?? 0) + 1);
  }
  return Object.fromEntries([...counts].sort(([left], [right]) => left.localeCompare(right)));
}

const baselinePath = argument("--baseline");
const currentPath = argument("--current");
const sourcesPath = argument("--sources");
const verificationPath = argument("--verification");
if (!baselinePath || !currentPath) {
  throw new Error(
    "需要 --baseline 和 --current，且二者必须指向批次清单/标准编码生成清单.csv。",
  );
}

const original44 = new Set();
const original1247 = new Set();
await scanCsv(baselinePath, codingManifestHeaders, "基线标准编码生成清单", (row) => {
  if (!row.WJBS) original44.add(row.relative_path);
  if (row.internal_sequence_source === "LOCAL_NORMALIZED_TITLE_ORDER") {
    original1247.add(row.relative_path);
  }
});

const currentByPath = new Map();
const allCurrentByPath = new Map();
const original1247BlockedGroups = new Map();
const canonicalWjbs = new Set();
const duplicateCanonicalWjbs = new Set();
const full = {
  rows: 0,
  canonical_rows: 0,
  canonical_with_wjbs: 0,
  canonical_missing_wjbs: 0,
  duplicate_carriers: 0,
  sequence_blockers: 0,
  agency_blockers: 0,
};
await scanCsv(currentPath, codingManifestHeaders, "当前标准编码生成清单", (row) => {
  full.rows += 1;
  allCurrentByPath.set(row.relative_path, row);
  if (original44.has(row.relative_path) || original1247.has(row.relative_path)) {
    currentByPath.set(row.relative_path, row);
  }
  if (
    original1247.has(row.relative_path)
    && !row.WJBS
    && row.coding_status !== "REFERENCE_EXISTING_CANONICAL"
    && !/ZDJGDM/.test(row.blocking_reason)
  ) {
    const key = [
      row.category_code,
      row.agency_code,
      row.promulgation_date,
      row.sequence_code,
      row.file_type_code,
    ].join("|");
    if (!original1247BlockedGroups.has(key)) original1247BlockedGroups.set(key, []);
    original1247BlockedGroups.get(key).push(row.relative_path);
  }
  if (row.coding_status === "REFERENCE_EXISTING_CANONICAL") {
    full.duplicate_carriers += 1;
    return;
  }
  full.canonical_rows += 1;
  if (row.WJBS) {
    full.canonical_with_wjbs += 1;
    if (canonicalWjbs.has(row.WJBS)) duplicateCanonicalWjbs.add(row.WJBS);
    canonicalWjbs.add(row.WJBS);
  } else {
    full.canonical_missing_wjbs += 1;
    if (/ZDJGDM/.test(row.blocking_reason)) full.agency_blockers += 1;
    else full.sequence_blockers += 1;
  }
});

const exactBodyCanonicalMatches = [];
if (sourcesPath && verificationPath) {
  const titleByPath = new Map();
  const pathsByTitle = new Map();
  await scanCsv(sourcesPath, ["relative_path", "title"], "来源记录", (row) => {
    const title = String(row.title ?? "").normalize("NFKC").replace(/[\s《》]/g, "");
    titleByPath.set(row.relative_path, title);
    if (!pathsByTitle.has(title)) pathsByTitle.set(title, []);
    pathsByTitle.get(title).push(row.relative_path);
  });
  const hashByPath = new Map();
  await scanCsv(
    verificationPath,
    ["relative_path", "normalized_text_sha256"],
    "核验结果",
    (row) => {
    hashByPath.set(row.relative_path, row.normalized_text_sha256);
    },
  );
  for (const relativePath of original1247) {
    const row = allCurrentByPath.get(relativePath);
    if (!row || row.WJBS || row.coding_status === "REFERENCE_EXISTING_CANONICAL") continue;
    const title = titleByPath.get(relativePath);
    const textHash = hashByPath.get(relativePath);
    const matches = (pathsByTitle.get(title) ?? []).filter((candidatePath) => {
      if (candidatePath === relativePath || hashByPath.get(candidatePath) !== textHash) return false;
      return Boolean(allCurrentByPath.get(candidatePath)?.WJBS);
    });
    if (matches.length) {
      exactBodyCanonicalMatches.push({
        relative_path: relativePath,
        matches: matches.map((candidatePath) => ({
          relative_path: candidatePath,
          WJBS: allCurrentByPath.get(candidatePath).WJBS,
        })),
      });
    }
  }
}

process.stdout.write(`${JSON.stringify({
  full: { ...full, duplicate_wjbs_groups: duplicateCanonicalWjbs.size },
  original44: countLabels(original44, currentByPath),
  original1247: countLabels(original1247, currentByPath),
  original1247_blocked_groups: {
    count: original1247BlockedGroups.size,
    top: [...original1247BlockedGroups]
      .sort((left, right) => right[1].length - left[1].length)
      .slice(0, 30)
      .map(([key, paths]) => ({ key, count: paths.length, samples: paths.slice(0, 6) })),
  },
  original1247_blocked_exact_body_canonical_matches: {
    count: exactBodyCanonicalMatches.length,
    rows: exactBodyCanonicalMatches.slice(0, 50),
  },
}, null, 2)}\n`);
