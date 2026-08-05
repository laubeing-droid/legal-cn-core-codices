import fs from "node:fs";
import readline from "node:readline";

const FLK_EFFECT_TO_STANDARD = new Map([
  ["3", "01"],
  ["4", "02"],
  ["2", "03"],
  ["1", "04"],
]);

function text(value) {
  if (Array.isArray(value)) return value.find((item) => String(item).trim()) ?? "";
  if (value === undefined || value === null) return "";
  return String(value).trim();
}

function normalizedId(value) {
  const result = text(value).toLowerCase();
  return result && !/\s/.test(result) ? result : "";
}

function normalizedTitle(value) {
  return text(value).normalize("NFKC").replace(/\s+/g, "");
}

function firstCsvFields(line, count) {
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
      if (fields.length === count) return fields;
    } else {
      value += character;
    }
  }
  fields.push(value);
  return fields.slice(0, count);
}

function quoteStateAfter(line, initialState) {
  let quoted = initialState;
  for (let index = 0; index < line.length; index += 1) {
    if (line[index] !== '"') continue;
    if (quoted && line[index + 1] === '"') {
      index += 1;
    } else {
      quoted = !quoted;
    }
  }
  return quoted;
}

export function mapFlkEffectCode(value) {
  return FLK_EFFECT_TO_STANDARD.get(text(value)) ?? "";
}

export function formalFulltextBlockingCode(record) {
  const status = record?.verification_status ?? "";
  if (status === "FULLTEXT_VERIFIED") return "";
  if (status === "FULLTEXT_MISMATCH") return "FULLTEXT_MISMATCH";
  if (status === "BLOCKED_ACCESS") return "FULLTEXT_BLOCKED_ACCESS";
  return "FULLTEXT_VERIFICATION_MISSING";
}

export function officialVersionIdCandidates(meta, sourceUrl = "") {
  const candidates = [];
  for (const key of [
    "id",
    "document_id",
    "文件标识",
    "版本标识",
    "bbbs",
    "flk_id",
  ]) {
    const id = normalizedId(meta?.[key]);
    if (id) candidates.push(id);
  }
  if (sourceUrl) {
    try {
      const parsed = new URL(sourceUrl);
      if (parsed.hostname.toLowerCase() === "flk.npc.gov.cn") {
        const id = normalizedId(parsed.searchParams.get("id"));
        if (id) candidates.push(id);
      }
    } catch {
      // Invalid source URLs remain an independent validation concern.
    }
  }
  return [...new Set(candidates)];
}

export function resolveFlkRecord(meta, sourceUrl, title, registry) {
  const expectedTitle = normalizedTitle(title);
  if (!expectedTitle || !registry?.byId) return null;
  for (const id of officialVersionIdCandidates(meta, sourceUrl)) {
    const records = registry.byId.get(id) ?? [];
    if (records.length !== 1) continue;
    if (normalizedTitle(records[0].title) === expectedTitle) return records[0];
  }
  return null;
}

export function cleanNationalRulesPublishers(value) {
  const raw = text(value);
  if (!raw) return [];
  const quoted = [...raw.matchAll(/'([^']+)'|"([^"]+)"/g)]
    .map((match) => (match[1] ?? match[2] ?? "").trim())
    .filter(Boolean);
  if (quoted.length) return [...new Set(quoted)];
  const unwrapped = raw.replace(/^\[/, "").replace(/\]$/, "").trim();
  return unwrapped ? [unwrapped] : [];
}

function nationalRuleCategory(categoryCode) {
  if (categoryCode === "1300") return "部门规章";
  if (categoryCode === "1400") return "地方政府规章";
  return "";
}

function normalizedNationalRulePublisher(value) {
  return text(value)
    .normalize("NFKC")
    .replace(/\s+/g, "")
    .replace(/人民政府$/u, "");
}

export function resolveNationalRuleRecord(title, categoryCode, registry, agencyName = "") {
  const category = nationalRuleCategory(categoryCode);
  const normalized = normalizedTitle(title);
  if (!category || !normalized || !registry?.byCategoryTitle) return null;
  const records = registry.byCategoryTitle.get(`${category}|${normalized}`) ?? [];
  if (records.length === 1) return records[0];
  const agency = normalizedNationalRulePublisher(agencyName);
  if (!agency) return null;
  const matches = records.filter((record) => (record.publishers ?? [])
    .some((publisher) => normalizedNationalRulePublisher(publisher) === agency));
  return matches.length === 1 ? matches[0] : null;
}

export async function loadFlkRegistry(csvPath) {
  const byId = new Map();
  const input = fs.createReadStream(csvPath, { encoding: "utf8" });
  const lines = readline.createInterface({ input, crlfDelay: Infinity });
  let header = true;
  let recordBuffer = "";
  let quoted = false;
  let rowCount = 0;
  for await (const rawLine of lines) {
    recordBuffer = recordBuffer ? `${recordBuffer}\n${rawLine}` : rawLine;
    quoted = quoteStateAfter(rawLine, quoted);
    if (quoted) continue;
    const recordLine = recordBuffer;
    recordBuffer = "";
    if (header) {
      header = false;
      continue;
    }
    if (!recordLine) continue;
    const fields = firstCsvFields(recordLine, 9);
    if (fields.length < 9) continue;
    const record = {
      bbbs: normalizedId(fields[0]),
      title: fields[1].trim(),
      gbrq: fields[2].trim(),
      sxrq: fields[3].trim(),
      sxx: fields[4].trim(),
      zdjgName: fields[5].trim(),
      flxz: fields[6].trim(),
      zdjgCodeId: fields[7].trim(),
      flfgCodeId: fields[8].trim(),
      registryRow: rowCount,
    };
    if (!record.bbbs) continue;
    if (!byId.has(record.bbbs)) byId.set(record.bbbs, []);
    byId.get(record.bbbs).push(record);
    rowCount += 1;
  }
  return {
    byId,
    rowCount,
    uniqueIdCount: byId.size,
    duplicateIdCount: [...byId.values()].filter((records) => records.length > 1).length,
  };
}

export async function loadFlkFulltextRegistry(csvPath) {
  const byVersionId = new Map();
  const byRelativePath = new Map();
  const input = fs.createReadStream(csvPath, { encoding: "utf8" });
  const lines = readline.createInterface({ input, crlfDelay: Infinity });
  let header = true;
  let recordBuffer = "";
  let quoted = false;
  let rowCount = 0;
  for await (const rawLine of lines) {
    recordBuffer = recordBuffer ? `${recordBuffer}\n${rawLine}` : rawLine;
    quoted = quoteStateAfter(rawLine, quoted);
    if (quoted) continue;
    const recordLine = recordBuffer;
    recordBuffer = "";
    if (header) {
      header = false;
      continue;
    }
    if (!recordLine) continue;
    const fields = firstCsvFields(recordLine, 13);
    if (fields.length < 13) continue;
    const record = {
      relative_path: fields[0].replace(/^\uFEFF/, "").trim(),
      bbbs: normalizedId(fields[1]),
      official_url: fields[2].trim(),
      official_file_relative_path: fields[3].trim(),
      official_carrier_sha256: fields[4].trim().toLowerCase(),
      official_text_sha256: fields[5].trim().toLowerCase(),
      local_text_sha256: fields[6].trim().toLowerCase(),
      official_text_length: fields[7].trim(),
      local_text_length: fields[8].trim(),
      official_block_coverage: fields[9].trim(),
      verification_status: fields[10].trim(),
      verified_at: fields[11].trim(),
      error: fields[12].trim(),
    };
    if (!record.relative_path || !record.bbbs) continue;
    byVersionId.set(record.bbbs, record);
    byRelativePath.set(record.relative_path.replaceAll("\\", "/"), record);
    rowCount += 1;
  }
  return { byVersionId, byRelativePath, rowCount };
}

export async function loadNationalRulesRegistry(csvPath) {
  const byCategoryTitle = new Map();
  const input = fs.createReadStream(csvPath, { encoding: "utf8" });
  const lines = readline.createInterface({ input, crlfDelay: Infinity });
  let header = true;
  let recordBuffer = "";
  let quoted = false;
  let rowCount = 0;
  for await (const rawLine of lines) {
    recordBuffer = recordBuffer ? `${recordBuffer}\n${rawLine}` : rawLine;
    quoted = quoteStateAfter(rawLine, quoted);
    if (quoted) continue;
    const recordLine = recordBuffer;
    recordBuffer = "";
    if (header) {
      header = false;
      continue;
    }
    if (!recordLine) continue;
    const fields = firstCsvFields(recordLine, 8);
    if (fields.length < 8) continue;
    const record = {
      source_id: fields[0].replace(/^\uFEFF/, "").trim(),
      record_id: fields[1].trim(),
      title: fields[2].trim(),
      publication_date: fields[3].trim(),
      category: fields[4].trim(),
      publishers: cleanNationalRulesPublishers(fields[5]),
      official_url: fields[6].trim(),
      catalog_url: fields[7].trim(),
      registryRow: rowCount,
    };
    if (!record.title || !record.category) continue;
    const key = `${record.category}|${normalizedTitle(record.title)}`;
    if (!byCategoryTitle.has(key)) byCategoryTitle.set(key, []);
    byCategoryTitle.get(key).push(record);
    rowCount += 1;
  }
  return {
    byCategoryTitle,
    rowCount,
    duplicateKeyCount: [...byCategoryTitle.values()]
      .filter((records) => records.length > 1).length,
  };
}
