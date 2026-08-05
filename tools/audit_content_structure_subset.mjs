import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";

import { extractInlineDataImages } from "./markdown_attachments.mjs";
import { extractPrimaryLegalDocumentBody } from "./legal_document_body.mjs";
import {
  duplicateContentStructureCodes,
  extractLegalContentRows,
} from "./legal_structure.mjs";

function argument(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : "";
}

function parseCsvLine(line) {
  const values = [];
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
      values.push(value);
      value = "";
    } else {
      value += character;
    }
  }
  values.push(value);
  return values;
}

function stripFrontMatter(text) {
  if (!text.startsWith("---")) return text;
  const match = /\r?\n---\s*(?:\r?\n|$)/g;
  match.lastIndex = 3;
  const end = match.exec(text);
  return end ? text.slice(end.index + end[0].length) : text;
}

function normalizeRelativePath(value) {
  return value.replaceAll("/", path.sep);
}

function normalizeDuplicateContent(value) {
  return String(value ?? "").replace(/\s+/g, "");
}

async function auditOne(sourceRoot, relativePath) {
  try {
    const sourcePath = path.join(sourceRoot, normalizeRelativePath(relativePath));
    const sourceText = (await fsp.readFile(sourcePath, "utf8")).replace(/^\uFEFF/, "");
    const sourceBody = extractInlineDataImages(stripFrontMatter(sourceText)).markdown;
    const body = extractPrimaryLegalDocumentBody(sourceBody).body;
    const rows = extractLegalContentRows(body);
    const duplicates = duplicateContentStructureCodes(rows);
    const duplicateSet = new Set(duplicates);
    const duplicateCategories = [...new Set(rows
      .filter((row) => duplicateSet.has(row.DE_02001))
      .map((row) => row.DE_02003))].sort();
    const duplicateGroups = [];
    for (const duplicateCode of duplicates) {
      const duplicateRows = rows.filter((row) => row.DE_02001 === duplicateCode);
      const normalizedContents = [...new Set(duplicateRows.map((row) => normalizeDuplicateContent(row.DE_02002)))];
      duplicateGroups.push({
        code: duplicateCode,
        categories: [...new Set(duplicateRows.map((row) => row.DE_02003))].sort(),
        occurrences: duplicateRows.length,
        identical_content: normalizedContents.length === 1,
        content_samples: normalizedContents.slice(0, 3),
      });
    }
    return {
      relative_path: relativePath,
      duplicates,
      duplicate_categories: duplicateCategories,
      identical_duplicate_groups: duplicateGroups.filter((group) => group.identical_content).length,
      divergent_duplicate_groups: duplicateGroups.filter((group) => !group.identical_content).length,
      divergent_group_samples: duplicateGroups.filter((group) => !group.identical_content).slice(0, 5),
      row_count: rows.length,
    };
  } catch (error) {
    return {
      relative_path: relativePath,
      duplicates: [],
      row_count: 0,
      error: String(error?.message ?? error),
    };
  }
}

async function main() {
  const validationArgument = argument("--validation-errors");
  const sourceRootArgument = argument("--source-root");
  const validationPath = validationArgument ? path.resolve(validationArgument) : "";
  const sourceRoot = sourceRootArgument ? path.resolve(sourceRootArgument) : "";
  const outputPath = argument("--output") ? path.resolve(argument("--output")) : "";
  if (!validationPath || !sourceRoot) {
    throw new Error("Usage: --validation-errors <csv> --source-root <dir> [--output <json>]");
  }

  const lines = fs.readFileSync(validationPath, "utf8").replace(/^\uFEFF/, "").split(/\r?\n/);
  const headers = parseCsvLine(lines.shift() ?? "");
  const pathIndex = headers.indexOf("relative_path");
  const codeIndex = headers.indexOf("error_code");
  if (pathIndex < 0 || codeIndex < 0) throw new Error("validation error CSV schema mismatch");
  const targets = [...new Set(lines
    .filter(Boolean)
    .map(parseCsvLine)
    .filter((values) => values[codeIndex] === "CONTENT_STRUCTURE_DUPLICATE")
    .map((values) => values[pathIndex])
    .filter(Boolean))];

  const results = [];
  const concurrency = 250;
  for (let offset = 0; offset < targets.length; offset += concurrency) {
    results.push(...await Promise.all(
      targets.slice(offset, offset + concurrency).map((relativePath) => auditOne(sourceRoot, relativePath)),
    ));
  }

  const remaining = results.filter((result) => result.duplicates.length && !result.error);
  const failed = results.filter((result) => result.error);
  const signatureCounts = {};
  const samples = {};
  for (const result of remaining) {
    const signature = result.duplicate_categories.join("+");
    signatureCounts[signature] = (signatureCounts[signature] ?? 0) + 1;
    if (!samples[signature]) samples[signature] = result;
  }
  const report = {
    generated_at: new Date().toISOString(),
    validation_errors: validationPath,
    source_root: sourceRoot,
    targets: targets.length,
    cleared: targets.length - remaining.length - failed.length,
    remaining: remaining.length,
    failed: failed.length,
    identical_only_files: remaining.filter((result) => result.divergent_duplicate_groups === 0).length,
    files_with_divergent_duplicates: remaining.filter((result) => result.divergent_duplicate_groups > 0).length,
    identical_duplicate_groups: remaining.reduce((sum, result) => sum + result.identical_duplicate_groups, 0),
    divergent_duplicate_groups: remaining.reduce((sum, result) => sum + result.divergent_duplicate_groups, 0),
    signatures: Object.fromEntries(Object.entries(signatureCounts).sort((a, b) => b[1] - a[1])),
    samples,
    remaining_rows: remaining,
    failed_rows: failed,
  };
  const serialized = `${JSON.stringify(report, null, 2)}\n`;
  if (outputPath) await fsp.writeFile(outputPath, serialized, "utf8");
  process.stdout.write(`${JSON.stringify({
    targets: report.targets,
    cleared: report.cleared,
    remaining: report.remaining,
    failed: report.failed,
    identical_only_files: report.identical_only_files,
    files_with_divergent_duplicates: report.files_with_divergent_duplicates,
    identical_duplicate_groups: report.identical_duplicate_groups,
    divergent_duplicate_groups: report.divergent_duplicate_groups,
    signatures: report.signatures,
    output: outputPath,
  }, null, 2)}\n`);
}

await main();
