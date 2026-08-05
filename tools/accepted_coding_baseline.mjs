import fs from "node:fs";
import path from "node:path";

import { validateWjbs } from "./standard_codes.mjs";

const REQUIRED_COLUMNS = [
  "source_relative_path",
  "source_sha256",
  "WJBS",
  "WJBS_source_type",
  "accepted_batch",
  "accepted_tree_sha256",
];

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
  if (quoted) throw new Error("ACCEPTED_CODING_BASELINE_CSV_UNTERMINATED_QUOTE");
  fields.push(value);
  return fields;
}

function wjbsParts(wjbs) {
  const match = /^1\.2\.156\.3005\.6-(\d{31})$/.exec(wjbs);
  if (!match) return null;
  const body = match[1];
  return {
    body,
    categoryCode: body.slice(0, 4),
    agencyCode: body.slice(4, 14),
    promulgationDate: body.slice(14, 22),
    sequenceCode: body.slice(22, 26),
    internalSequenceCode: body.slice(26, 29),
    fileTypeCode: body.slice(29, 31),
  };
}

export function loadAcceptedCodingBaseline(csvPath) {
  const text = fs.readFileSync(csvPath, "utf8").replace(/^\uFEFF/, "");
  const lines = text.split(/\r?\n/).filter((line) => line.trim());
  const headers = parseCsvLine(lines.shift() ?? "");
  if (REQUIRED_COLUMNS.some((column) => !headers.includes(column))) {
    throw new Error("ACCEPTED_CODING_BASELINE_HEADERS_INVALID");
  }
  const registry = new Map();
  for (const line of lines) {
    const values = parseCsvLine(line);
    const row = Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""]));
    const relativePath = row.source_relative_path.replaceAll("\\", "/");
    if (!relativePath || path.posix.isAbsolute(relativePath) || relativePath.split("/").includes("..")) {
      throw new Error(`ACCEPTED_CODING_BASELINE_PATH_INVALID:${relativePath}`);
    }
    if (!/^[0-9a-f]{64}$/i.test(row.source_sha256)) {
      throw new Error(`ACCEPTED_CODING_BASELINE_SOURCE_HASH_INVALID:${relativePath}`);
    }
    if (!/^[0-9a-f]{64}$/i.test(row.accepted_tree_sha256)) {
      throw new Error(`ACCEPTED_CODING_BASELINE_TREE_HASH_INVALID:${relativePath}`);
    }
    if (validateWjbs(row.WJBS, { sourceType: row.WJBS_source_type }).length) {
      throw new Error(`ACCEPTED_CODING_BASELINE_WJBS_INVALID:${relativePath}`);
    }
    if (registry.has(relativePath)) {
      throw new Error(`ACCEPTED_CODING_BASELINE_PATH_DUPLICATE:${relativePath}`);
    }
    registry.set(relativePath, { ...row, source_relative_path: relativePath });
  }
  return registry;
}

export function applyAcceptedCodingBaseline(entry, registry) {
  if (entry.candidate.WJBS) return false;
  const accepted = registry.get(entry.relativePath);
  if (!accepted || accepted.source_sha256.toLowerCase() !== entry.digest.toLowerCase()) return false;
  const parts = wjbsParts(accepted.WJBS);
  const row = entry.candidate;
  if (!parts || [
    [parts.categoryCode, row.FLFGDZWJFLDM],
    [parts.agencyCode, row.ZDJGDM],
    [parts.fileTypeCode, row.DE_01020],
  ].some(([acceptedValue, currentValue]) => acceptedValue !== currentValue)) {
    throw new Error(`ACCEPTED_CODING_BASELINE_COMPONENT_MISMATCH:${entry.relativePath}`);
  }
  row.GBRQ = parts.promulgationDate;
  row.DE_01014 = parts.promulgationDate;
  row._promulgation_source = "REFERENCE_ACCEPTED_CODING_BASELINE";
  row.WJBS = accepted.WJBS;
  row._sequence_code = parts.sequenceCode;
  if (Number(parts.categoryCode) <= 1500) row.DE_01001 ||= parts.body;
  entry.internalSequence = parts.internalSequenceCode;
  entry.internalSequenceSource = "REFERENCE_ACCEPTED_CODING_BASELINE";
  entry.wjbsSourceType = accepted.WJBS_source_type;
  entry.acceptedCodingEvidence = JSON.stringify({
    accepted_batch: accepted.accepted_batch,
    accepted_tree_sha256: accepted.accepted_tree_sha256,
    source_sha256: accepted.source_sha256,
  });
  return true;
}
