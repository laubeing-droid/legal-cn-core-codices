import fs from "node:fs";

function parseCsv(text) {
  const rows = [];
  let row = [];
  let value = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (character === '"') {
      if (quoted && text[index + 1] === '"') {
        value += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (character === "," && !quoted) {
      row.push(value);
      value = "";
    } else if ((character === "\n" || character === "\r") && !quoted) {
      if (character === "\r" && text[index + 1] === "\n") index += 1;
      row.push(value);
      if (row.some((field) => field !== "")) rows.push(row);
      row = [];
      value = "";
    } else {
      value += character;
    }
  }
  if (quoted) throw new Error("COMPONENT_CONTEXT_CSV_UNTERMINATED_QUOTE");
  row.push(value);
  if (row.some((field) => field !== "")) rows.push(row);
  return rows;
}

export function componentKey({
  categoryCode,
  agencyCode,
  promulgationDate,
  sequenceCode,
  fileTypeCode,
}) {
  const values = [categoryCode, agencyCode, promulgationDate, sequenceCode, fileTypeCode]
    .map((value) => String(value ?? "").trim());
  return values.every(Boolean) ? values.join("|") : "";
}

export function loadComponentContext(csvPath) {
  const records = parseCsv(fs.readFileSync(csvPath, "utf8").replace(/^\uFEFF/, ""));
  const headers = records.shift() ?? [];
  const required = [
    "relative_path", "category_code", "agency_code", "promulgation_date",
    "sequence_code", "file_type_code",
  ];
  if (required.some((field) => !headers.includes(field))) {
    throw new Error("COMPONENT_CONTEXT_HEADERS_INVALID");
  }
  const owners = new Map();
  for (const values of records) {
    const row = Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""]));
    const key = componentKey({
      categoryCode: row.category_code,
      agencyCode: row.agency_code,
      promulgationDate: row.promulgation_date,
      sequenceCode: row.sequence_code,
      fileTypeCode: row.file_type_code,
    });
    if (!key || !row.relative_path) continue;
    if (!owners.has(key)) owners.set(key, new Set());
    owners.get(key).add(row.relative_path.replaceAll("\\", "/"));
  }
  return owners;
}

export function mergeComponentContexts(...contexts) {
  const merged = new Map();
  for (const context of contexts) {
    for (const [key, paths] of context) {
      if (!merged.has(key)) merged.set(key, new Set());
      for (const relativePath of paths) merged.get(key).add(relativePath);
    }
  }
  return merged;
}

export function acceptedCodingComponentContext(registry) {
  const context = new Map();
  for (const [relativePath, entry] of registry) {
    const match = /^1\.2\.156\.3005\.6-(\d{31})$/.exec(entry.WJBS);
    if (!match) continue;
    const body = match[1];
    const key = componentKey({
      categoryCode: body.slice(0, 4),
      agencyCode: body.slice(4, 14),
      promulgationDate: body.slice(14, 22),
      sequenceCode: body.slice(22, 26),
      fileTypeCode: body.slice(29, 31),
    });
    if (!context.has(key)) context.set(key, new Set());
    context.get(key).add(relativePath);
  }
  return context;
}
