import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import { validatedDecisionTitleOrder } from "./decision_order.mjs";
import { deriveFileTypeCode, deriveSequenceCode } from "./standard_metadata.mjs";

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quoted) {
      if (character === '"' && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (character === '"') {
        quoted = false;
      } else {
        field += character;
      }
    } else if (character === '"') {
      quoted = true;
    } else if (character === ",") {
      row.push(field);
      field = "";
    } else if (character === "\n") {
      row.push(field.replace(/\r$/u, ""));
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += character;
    }
  }
  if (field || row.length) {
    row.push(field.replace(/\r$/u, ""));
    rows.push(row);
  }
  const [header = [], ...body] = rows.filter((item) => item.some(Boolean));
  return body.map((values) => Object.fromEntries(header.map((name, index) => [name, values[index] ?? ""])));
}

function csvCell(value) {
  const text = String(value ?? "");
  return /[",\r\n]/u.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function writeCsv(filePath, rows, columns) {
  const lines = [columns.join(","), ...rows.map((row) => columns.map((name) => csvCell(row[name])).join(","))];
  fs.writeFileSync(filePath, `\uFEFF${lines.join("\r\n")}\r\n`, "utf8");
}

function normalizedTitle(value) {
  return String(value ?? "").normalize("NFKC").replace(/[\s《》〈〉]/gu, "").toLowerCase();
}

function frontmatter(markdown) {
  const match = String(markdown ?? "").match(/^---\s*\r?\n([\s\S]*?)\r?\n---\s*(?:\r?\n|$)/u);
  if (!match) return {};
  const result = {};
  for (const line of match[1].split(/\r?\n/u)) {
    const item = line.match(/^([^:#][^:]*):\s*(.*)$/u);
    if (!item) continue;
    result[item[1].trim()] = item[2].trim().replace(/^(['"])(.*)\1$/u, "$2");
  }
  return result;
}

function eventIdentities(value) {
  return String(value ?? "").split("|~|").filter(Boolean).map((item) => {
    const [agencyCode = "", promulgationDate = "", sequenceCode = "", categoryCode = ""] = item.split("|");
    return { agencyCode, promulgationDate, sequenceCode, categoryCode, key: item };
  });
}

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

const [sourceRootArg, candidatesArg, sourceRecordsArg, codingManifestArg, outputDirArg] = process.argv.slice(2);
if (![sourceRootArg, candidatesArg, sourceRecordsArg, codingManifestArg, outputDirArg].every(Boolean)) {
  throw new Error("USAGE: node audit_local_decision_carriers_targeted.mjs <source-root> <candidate-selection.csv> <source-records.csv> <standard-coding-manifest.csv> <output-dir>");
}

const sourceRoot = path.resolve(sourceRootArg);
const outputDir = path.resolve(outputDirArg);
const candidates = parseCsv(fs.readFileSync(path.resolve(candidatesArg), "utf8").replace(/^\uFEFF/u, ""));
const sourceRecords = parseCsv(fs.readFileSync(path.resolve(sourceRecordsArg), "utf8").replace(/^\uFEFF/u, ""));
const codingRows = parseCsv(fs.readFileSync(path.resolve(codingManifestArg), "utf8").replace(/^\uFEFF/u, ""));
const sourceById = new Map();
const sourceByTitle = new Map();
const sourceTitleByPath = new Map();
for (const row of sourceRecords) {
  if (row.legacy_id) sourceById.set(row.legacy_id, row);
  sourceTitleByPath.set(row.relative_path, row.title);
  const key = normalizedTitle(row.title);
  if (!sourceByTitle.has(key)) sourceByTitle.set(key, []);
  sourceByTitle.get(key).push(row);
}
const blockedByEvent = new Map();
for (const row of codingRows) {
  if (
    row.internal_sequence_source !== "BLOCKED_MISSING_OFFICIAL_DECISION_ORDER"
    && !String(row.blocking_reason).includes("MISSING_OFFICIAL_DECISION_ORDER")
  ) continue;
  const eventKey = [row.agency_code, row.promulgation_date, row.sequence_code, row.category_code].join("|");
  if (!blockedByEvent.has(eventKey)) blockedByEvent.set(eventKey, []);
  blockedByEvent.get(eventKey).push({
    relativePath: row.relative_path,
    title: sourceTitleByPath.get(row.relative_path) ?? "",
    eventKey,
  });
}

const auditRows = [];
const matchRows = [];
const exactPaths = new Set();
const readyAffectedPaths = new Set();
const readyStatuses = new Set([
  "LOCAL_EVIDENCE_READY",
  "LOCAL_EVIDENCE_READY_SEQUENCE_RECONCILED",
]);
for (const candidate of candidates) {
  let source = sourceById.get(candidate.bbbs);
  let matchMethod = source ? "EXACT_LEGACY_ID" : "";
  if (!source) {
    const titleMatches = sourceByTitle.get(normalizedTitle(candidate.title)) ?? [];
    if (titleMatches.length === 1) {
      [source] = titleMatches;
      matchMethod = "UNIQUE_NORMALIZED_TITLE";
    } else if (titleMatches.length > 1) {
      matchMethod = "AMBIGUOUS_NORMALIZED_TITLE";
    }
  }
  const events = eventIdentities(candidate.event_keys);
  const eventAgencies = unique(events.map((event) => event.agencyCode));
  const eventDates = unique(events.map((event) => event.promulgationDate));
  const eventSequences = unique(events.map((event) => event.sequenceCode));
  const eventBlockedRows = events.flatMap((event) => blockedByEvent.get(event.key) ?? []);
  let affectedPaths = [];
  let matchedAffectedRows = [];
  let status = "NO_LOCAL_CARRIER";
  let derivedFileType = "";
  let carrierSequenceCode = "";
  let expectedTitleCount = "";
  let extractedTitleCount = 0;
  let sourceSha256 = "";
  let evidenceOfficialUrl = source?.source_url ?? "";
  let decisionOrderValidation;
  if (source) {
    const fullPath = path.resolve(sourceRoot, source.relative_path);
    if (!fullPath.startsWith(`${sourceRoot}${path.sep}`) || !fs.existsSync(fullPath)) {
      status = "LOCAL_CARRIER_PATH_INVALID";
    } else {
      const bytes = fs.readFileSync(fullPath);
      const markdown = bytes.toString("utf8");
      sourceSha256 = crypto.createHash("sha256").update(bytes).digest("hex");
      const meta = frontmatter(markdown);
      derivedFileType = deriveFileTypeCode(meta, candidate.title);
      carrierSequenceCode = deriveSequenceCode(meta, markdown);
      const validation = validatedDecisionTitleOrder(candidate.title, markdown);
      decisionOrderValidation = validation;
      const officialUrl = source.source_url || (matchMethod === "EXACT_LEGACY_ID"
        ? `https://flk.npc.gov.cn/detail?id=${candidate.bbbs}`
        : "");
      evidenceOfficialUrl = officialUrl;
      expectedTitleCount = validation.expectedCount ?? "";
      extractedTitleCount = validation.extractedCount;
      const evidencedTitleKeys = new Set([
        normalizedTitle(candidate.title),
        ...validation.orderedTitles.map((item) => item.normalizedTitle),
      ]);
      matchedAffectedRows = eventBlockedRows.filter(
        (row) => evidencedTitleKeys.has(normalizedTitle(row.title)),
      );
      affectedPaths = unique(matchedAffectedRows.map((row) => row.relativePath));
      if (sourceSha256 !== source.source_sha256) status = "SOURCE_HASH_DRIFT";
      else if (!/^https:\/\/flk\.npc\.gov\.cn\//u.test(officialUrl)) status = "NON_OFFICIAL_CARRIER_URL";
      else if (derivedFileType !== "30") status = "NOT_DECISION_FILE_TYPE";
      else if (validation.status !== "VALID") status = validation.status;
      else if (eventAgencies.length !== 1 || eventDates.length !== 1) status = "EVENT_IDENTITY_CONFLICT";
      else if (!eventSequences.includes(carrierSequenceCode)) status = "CARRIER_SEQUENCE_MISMATCH";
      else if (!affectedPaths.length) status = "NO_BLOCKED_TARGETS";
      else status = eventSequences.length === 1
        ? "LOCAL_EVIDENCE_READY"
        : "LOCAL_EVIDENCE_READY_SEQUENCE_RECONCILED";
    }
  }
  if (readyStatuses.has(status)) {
    exactPaths.add(source.relative_path);
    for (const affectedPath of affectedPaths) {
      exactPaths.add(affectedPath);
      readyAffectedPaths.add(affectedPath);
    }
    for (const matched of matchedAffectedRows) {
      const targetKey = normalizedTitle(matched.title);
      const orderedTarget = decisionOrderValidation.orderedTitles.find(
        (item) => item.normalizedTitle === targetKey,
      );
      matchRows.push({
        bbbs: candidate.bbbs,
        decision_title: candidate.title,
        carrier_relative_path: source.relative_path,
        carrier_sequence_code: carrierSequenceCode,
        target_relative_path: matched.relativePath,
        target_title: matched.title,
        target_event_key: matched.eventKey,
        evidenced_order: targetKey === normalizedTitle(candidate.title) ? 0 : orderedTarget?.order ?? "",
        evidence_status: status,
      });
    }
  }
  auditRows.push({
    bbbs: candidate.bbbs,
    decision_title: candidate.title,
    relative_path: source?.relative_path ?? "",
    match_method: matchMethod,
    status,
    derived_file_type: derivedFileType,
    carrier_sequence_code: carrierSequenceCode,
    event_sequence_codes: eventSequences.join("|"),
    expected_title_count: expectedTitleCount,
    extracted_title_count: extractedTitleCount,
    affected_blocked_paths: affectedPaths.length,
    source_sha256: sourceSha256,
    source_url: evidenceOfficialUrl,
  });
}

fs.mkdirSync(outputDir, { recursive: true });
const auditColumns = [
  "bbbs", "decision_title", "relative_path", "match_method", "status", "derived_file_type",
  "carrier_sequence_code", "event_sequence_codes", "expected_title_count", "extracted_title_count",
  "affected_blocked_paths", "source_sha256", "source_url",
];
writeCsv(path.join(outputDir, "local_decision_carrier_audit.csv"), auditRows, auditColumns);
writeCsv(
  path.join(outputDir, "exact_revalidation_paths.csv"),
  [...exactPaths].sort((left, right) => left.localeCompare(right, "zh-CN")).map((relativePath) => ({ relative_path: relativePath })),
  ["relative_path"],
);
writeCsv(
  path.join(outputDir, "matched_affected_paths.csv"),
  [...readyAffectedPaths].sort((left, right) => left.localeCompare(right, "zh-CN")).map((relativePath) => ({ relative_path: relativePath })),
  ["relative_path"],
);
writeCsv(
  path.join(outputDir, "local_decision_matches.csv"),
  matchRows,
  [
    "bbbs", "decision_title", "carrier_relative_path", "carrier_sequence_code",
    "target_relative_path", "target_title", "target_event_key", "evidenced_order", "evidence_status",
  ],
);
const counts = Object.fromEntries(
  [...new Set(auditRows.map((row) => row.status))].sort().map((status) => [
    status,
    auditRows.filter((row) => row.status === status).length,
  ]),
);
const summary = {
  candidate_decisions: candidates.length,
  locally_matched_carriers: auditRows.filter((row) => row.relative_path).length,
  ready_decisions: auditRows.filter((row) => readyStatuses.has(row.status)).length,
  affected_blocked_paths: readyAffectedPaths.size,
  exact_revalidation_paths: exactPaths.size,
  status_counts: counts,
};
fs.writeFileSync(path.join(outputDir, "summary.json"), `${JSON.stringify(summary, null, 2)}\n`, "utf8");
process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
