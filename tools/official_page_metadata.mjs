import fs from "node:fs";

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

export function loadOfficialPageMetadata(csvPath) {
  const lines = fs.readFileSync(csvPath, "utf8").replace(/^\uFEFF/, "").split(/\r?\n/);
  const headers = parseCsvLine(lines.shift() ?? "");
  const registry = new Map();
  registry.byRelativePath = new Map();
  for (const line of lines) {
    if (!line.trim()) continue;
    const values = parseCsvLine(line);
    const row = Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""]));
    if (row.parse_status !== "PARSED") continue;
    if (!/^https?:\/\//.test(row.official_url)) throw new Error("OFFICIAL_PAGE_URL_INVALID");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(row.promulgation_date)) {
      throw new Error(`OFFICIAL_PAGE_DATE_INVALID:${row.official_url}`);
    }
    if (!/^[0-9a-f]{64}$/i.test(row.content_sha256)) {
      throw new Error(`OFFICIAL_PAGE_HASH_INVALID:${row.official_url}`);
    }
    const existingUrlEvidence = registry.get(row.official_url);
    if (existingUrlEvidence) {
      const sharedPageFields = [
        "final_url",
        "promulgation_date",
        "document_number",
        "effective_date",
        "content_sha256",
      ];
      if (sharedPageFields.some((field) => existingUrlEvidence[field] !== row[field])) {
        throw new Error(`OFFICIAL_PAGE_URL_CONFLICT:${row.official_url}`);
      }
    } else {
      registry.set(row.official_url, row);
    }
    if (row.relative_path) {
      if (registry.byRelativePath.has(row.relative_path)) {
        throw new Error(`OFFICIAL_PAGE_PATH_DUPLICATE:${row.relative_path}`);
      }
      registry.byRelativePath.set(row.relative_path, row);
    }
  }
  return registry;
}

export function officialPageEvidenceForDocument(registry, relativePath, officialUrl = "") {
  return registry?.byRelativePath?.get(relativePath) ?? registry?.get(officialUrl);
}

export function applyOfficialPageMetadata(row, evidence) {
  if (!evidence) return row;
  row.GBRQ = evidence.promulgation_date.replaceAll("-", "");
  row._promulgation_source = "REGISTERED_OFFICIAL_PAGE_BODY";
  if (evidence.document_number) row.FWZH = evidence.document_number;
  if (evidence.effective_date) {
    row.SXRQ = evidence.effective_date.replaceAll("-", "");
    row._effective_date_source = "REGISTERED_OFFICIAL_PAGE_BODY";
  }
  row._official_page_evidence = JSON.stringify({
    official_url: evidence.official_url,
    final_url: evidence.final_url,
    content_sha256: evidence.content_sha256,
    evidence_excerpt: evidence.evidence_excerpt,
    fetched_at: evidence.fetched_at,
  });
  return row;
}
