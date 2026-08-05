import fs from "node:fs";
import path from "node:path";

const EXPECTED_HEADER = [
  "relative_path",
  "skip_code",
  "status",
  "approved_on",
  "rationale",
];
const ALLOWED_SKIP_CODES = new Set([
  "MISSING_OFFICIAL_DECISION_ORDER",
  "CONTENT_STRUCTURE_UNREPRESENTABLE",
]);
const ALLOWED_STATUSES = new Set(["ACTIVE", "INACTIVE"]);

function normalizeRelativePath(value) {
  const normalized = String(value ?? "").trim().replaceAll("\\", "/");
  if (
    !normalized
    || path.posix.isAbsolute(normalized)
    || /^[A-Za-z]:\//.test(normalized)
    || normalized.split("/").some((part) => part === "" || part === "." || part === "..")
  ) {
    throw new Error(`PUBLICATION_SKIP_INVALID_PATH:${value}`);
  }
  return normalized;
}

export function loadPublicationSkips(csvPath) {
  const lines = fs.readFileSync(csvPath, "utf8")
    .replace(/^\uFEFF/, "")
    .split(/\r?\n/)
    .filter((line) => line.trim());
  const header = (lines.shift() ?? "").split(",");
  if (JSON.stringify(header) !== JSON.stringify(EXPECTED_HEADER)) {
    throw new Error("PUBLICATION_SKIP_HEADER_MISMATCH");
  }

  const active = new Map();
  const seen = new Set();
  for (const [index, line] of lines.entries()) {
    const columns = line.split(",");
    if (columns.length !== EXPECTED_HEADER.length) {
      throw new Error(`PUBLICATION_SKIP_COLUMN_COUNT_MISMATCH:${index + 2}`);
    }
    const [rawPath, skipCode, status, approvedOn, rationale] = columns.map((value) => value.trim());
    const relativePath = normalizeRelativePath(rawPath);
    if (seen.has(relativePath)) {
      throw new Error(`PUBLICATION_SKIP_DUPLICATE:${relativePath}`);
    }
    seen.add(relativePath);
    if (!ALLOWED_SKIP_CODES.has(skipCode)) {
      throw new Error(`PUBLICATION_SKIP_CODE_INVALID:${relativePath}:${skipCode}`);
    }
    if (!ALLOWED_STATUSES.has(status)) {
      throw new Error(`PUBLICATION_SKIP_STATUS_INVALID:${relativePath}:${status}`);
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(approvedOn) || !rationale) {
      throw new Error(`PUBLICATION_SKIP_EVIDENCE_INCOMPLETE:${relativePath}`);
    }
    if (status === "ACTIVE") {
      active.set(relativePath, {
        relativePath,
        skipCode,
        status,
        approvedOn,
        rationale,
      });
    }
  }
  return active;
}

export function partitionPublicationSkips(entries, activeSkips) {
  const included = [];
  const skipped = [];
  for (const entry of entries) {
    const publicationSkip = activeSkips.get(entry.relativePath);
    if (publicationSkip) {
      skipped.push({ ...entry, publicationSkip });
    } else {
      included.push(entry);
    }
  }
  return { included, skipped };
}
