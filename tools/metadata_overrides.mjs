import fs from "node:fs";

const allowedFields = new Set([
  "GBRQ",
  "SXRQ",
  "SHXRQ",
  "SXX",
  "ZDJGDM",
  "ZDJGMC",
  "FWZH",
  "_promulgation_source",
  "_effective_date_source",
  "_effect_source",
  "_agency_name_source",
  "_agency_code_source",
]);

export function loadMetadataOverrides(jsonPath) {
  const parsed = JSON.parse(fs.readFileSync(jsonPath, "utf8").replace(/^\uFEFF/, ""));
  const entries = new Map();
  for (const entry of parsed.entries ?? []) {
    if (!entry.relative_path || entries.has(entry.relative_path)) {
      throw new Error(`INVALID_OR_DUPLICATE_METADATA_OVERRIDE:${entry.relative_path ?? ""}`);
    }
    const values = {};
    for (const [key, value] of Object.entries(entry.values ?? {})) {
      if (!allowedFields.has(key)) throw new Error(`UNSUPPORTED_METADATA_OVERRIDE_FIELD:${key}`);
      values[key] = String(value ?? "");
    }
    entries.set(entry.relative_path, {
      values,
      evidence: entry.evidence ?? {},
    });
  }
  return entries;
}

export function applyMetadataOverride(row, override) {
  if (!override) return row;
  for (const [key, value] of Object.entries(override.values)) row[key] = value;
  return row;
}
