import fs from "node:fs";
import path from "node:path";

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

export function loadExactPathBaseline(baselinePath) {
  const lines = fs.readFileSync(baselinePath, "utf8")
    .replace(/^\uFEFF/, "")
    .split(/\r?\n/)
    .filter(Boolean);
  if (!lines.length) throw new Error(`精确路径基线为空：${baselinePath}`);
  const headers = parseCsvLine(lines[0]);
  const relativePathIndex = headers.indexOf("relative_path");
  if (relativePathIndex < 0) {
    throw new Error(`精确路径基线缺少字段：relative_path`);
  }
  const targets = new Set();
  for (const line of lines.slice(1)) {
    const relativePath = parseCsvLine(line)[relativePathIndex] ?? "";
    if (relativePath) targets.add(relativePath.replaceAll("\\", "/"));
  }
  if (!targets.size) throw new Error(`精确路径基线没有目标记录：${baselinePath}`);
  return targets;
}

export function loadWjbsTargetPaths(baselinePath) {
  const lines = fs.readFileSync(baselinePath, "utf8")
    .replace(/^\uFEFF/, "")
    .split(/\r?\n/)
    .filter(Boolean);
  if (!lines.length) throw new Error(`WJBS专项基线为空：${baselinePath}`);
  const headers = parseCsvLine(lines[0]);
  const required = ["relative_path", "WJBS", "internal_sequence_source"];
  const missing = required.filter((header) => !headers.includes(header));
  if (missing.length) {
    throw new Error(`WJBS专项基线缺少字段：${missing.join(", ")}`);
  }
  const indexes = Object.fromEntries(required.map((header) => [header, headers.indexOf(header)]));
  const targets = new Set();
  for (const line of lines.slice(1)) {
    const values = parseCsvLine(line);
    const relativePath = values[indexes.relative_path] ?? "";
    const wjbs = values[indexes.WJBS] ?? "";
    const internalSequenceSource = values[indexes.internal_sequence_source] ?? "";
    if (!relativePath) continue;
    if (!wjbs || internalSequenceSource === "LOCAL_NORMALIZED_TITLE_ORDER") {
      targets.add(relativePath.replaceAll("\\", "/"));
    }
  }
  if (!targets.size) throw new Error(`WJBS专项基线没有目标记录：${baselinePath}`);
  return targets;
}

export function loadCurrentWjbsBlockedPaths(baselinePath) {
  const lines = fs.readFileSync(baselinePath, "utf8")
    .replace(/^\uFEFF/, "")
    .split(/\r?\n/)
    .filter(Boolean);
  if (!lines.length) throw new Error(`当前WJBS阻断基线为空：${baselinePath}`);
  const headers = parseCsvLine(lines[0]);
  const required = ["relative_path", "WJBS", "coding_status", "blocking_reason"];
  const missing = required.filter((header) => !headers.includes(header));
  if (missing.length) {
    throw new Error(`当前WJBS阻断基线缺少字段：${missing.join(", ")}`);
  }
  const indexes = Object.fromEntries(required.map((header) => [header, headers.indexOf(header)]));
  const targets = new Set();
  for (const line of lines.slice(1)) {
    const values = parseCsvLine(line);
    const relativePath = values[indexes.relative_path] ?? "";
    const wjbs = values[indexes.WJBS] ?? "";
    const codingStatus = values[indexes.coding_status] ?? "";
    const blockingReason = values[indexes.blocking_reason] ?? "";
    if (
      relativePath
      && !wjbs
      && codingStatus === "BLOCKED"
      && blockingReason.split("|").includes("MISSING_STANDARD_FIELD:WJBS")
    ) {
      targets.add(relativePath.replaceAll("\\", "/"));
    }
  }
  if (!targets.size) throw new Error(`当前WJBS阻断基线没有目标记录：${baselinePath}`);
  return targets;
}

export function resolveWjbsTargetFiles(workspaceRoot, targetPaths) {
  const resolvedWorkspace = path.resolve(workspaceRoot);
  const files = [];
  for (const relativePath of targetPaths) {
    const fullPath = path.resolve(resolvedWorkspace, ...relativePath.split("/"));
    const relative = path.relative(resolvedWorkspace, fullPath);
    if (
      !relative
      || relative.startsWith("..")
      || path.isAbsolute(relative)
      || path.extname(fullPath).toLowerCase() !== ".md"
    ) {
      throw new Error(`WJBS专项基线含非法路径：${relativePath}`);
    }
    if (!fs.statSync(fullPath, { throwIfNoEntry: false })?.isFile()) {
      throw new Error(`WJBS专项基线文件不存在：${relativePath}`);
    }
    files.push(fullPath);
  }
  return files.sort((left, right) => left.localeCompare(right, "zh-CN"));
}

export function describeExactWjbsScope(workspaceRoot, files) {
  const resolvedWorkspace = path.resolve(workspaceRoot);
  const sourceRoots = new Set();
  for (const file of files) {
    const relative = path.relative(resolvedWorkspace, path.resolve(file));
    if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
      throw new Error(`WJBS专项文件越出工作区：${file}`);
    }
    sourceRoots.add(relative.split(path.sep)[0]);
  }
  return {
    enumeration_mode: "EXACT_BASELINE_PATHS",
    full_corpus_enumerated: false,
    source_roots: [...sourceRoots].sort((left, right) => left.localeCompare(right, "zh-CN")),
    source_files: files.length,
  };
}
