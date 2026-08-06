import path from "node:path";
import fs from "node:fs";

export function listMarkdownFiles(root) {
  const files = [];
  function walk(dir) {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(fullPath);
      } else if (entry.isFile() && /\.[mM][dD]$/.test(entry.name)) {
        files.push(path.resolve(fullPath));
      }
    }
  }
  walk(root);
  return files.sort((a, b) => a.localeCompare(b, "zh-CN"));
}
