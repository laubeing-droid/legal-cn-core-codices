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

const provenanceFields = new Set([
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

export function mergeMetadataOverrideMaps(...registries) {
  const merged = new Map();
  merged.conflicts = [];
  for (const registry of registries) {
    for (const [relativePath, override] of registry) {
      if (!merged.has(relativePath)) {
        merged.set(relativePath, structuredClone(override));
        continue;
      }

      const current = merged.get(relativePath);
      for (const [field, supplementalValue] of Object.entries(override.values ?? {})) {
        const primaryValue = current.values[field] ?? "";
        if (!primaryValue) {
          current.values[field] = supplementalValue;
        } else if (
          supplementalValue
          && supplementalValue !== primaryValue
          && !provenanceFields.has(field)
        ) {
          merged.conflicts.push({
            relativePath,
            field,
            primaryValue,
            supplementalValue,
          });
        }
      }

      if (!("primary" in (current.evidence ?? {}))) {
        current.evidence = {
          primary: current.evidence ?? {},
          supplemental: [],
        };
      }
      current.evidence.supplemental.push(override.evidence ?? {});
    }
  }
  return merged;
}
