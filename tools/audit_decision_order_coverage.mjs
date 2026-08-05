import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

import { extractDecisionTitleOrder } from "./decision_order.mjs";
import { classifySourceContent } from "./content_scope.mjs";

const root = path.resolve(process.argv[2] ?? "");
if (!root || !fs.existsSync(root)) throw new Error("USAGE: node audit_decision_order_coverage.mjs <source-root>");
const sourceDirectories = [
  "00_法律Wiki导航与引用规则",
  "01_立法与公开行政文件",
  "02_法院系统",
  "03_检察院系统",
  "04_仲裁系统",
  "06_参考材料",
]
  .map((name) => path.join(root, name))
  .filter((sourcePath) => fs.existsSync(sourcePath));

const inventory = spawnSync(
  "rg",
  [
    "-l",
    "^(group|法律类型):.*(修改|废止).*决定",
    ...sourceDirectories,
    "--glob",
    "*.md",
  ],
  { encoding: "utf8", windowsHide: true },
);
if (![0, 1].includes(inventory.status)) throw new Error(inventory.stderr || "RG_FAILED");
const files = inventory.stdout.split(/\r?\n/).filter(Boolean);
const results = files.map((filePath) => {
  const relativePath = path.relative(root, filePath).replaceAll("\\", "/");
  const body = fs.readFileSync(filePath, "utf8");
  return {
    relative_path: relativePath,
    content_type: classifySourceContent(relativePath, "", body),
    ordered_titles: extractDecisionTitleOrder(body).length,
  };
});
const parsed = results.filter((row) => row.ordered_titles > 0);
const unparsedMultiTitle = results.filter(
  (row) => row.ordered_titles === 0 && /等[二三四五六七八九十百\d]+(?:部|件|项)/u.test(row.relative_path),
);
process.stdout.write(`${JSON.stringify({
  decision_files: files.length,
  blocked_access_decision_files: results.filter(
    (row) => row.content_type === "blocked_access_content",
  ).length,
  parsed_decision_files: parsed.length,
  ordered_titles: parsed.reduce((sum, row) => sum + row.ordered_titles, 0),
  unparsed_multi_title_files: unparsedMultiTitle.length,
  unparsed_multi_title_examples: unparsedMultiTitle.slice(0, 30),
  largest: parsed.sort((left, right) => right.ordered_titles - left.ordered_titles).slice(0, 20),
}, null, 2)}\n`);
