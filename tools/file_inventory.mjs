import path from "node:path";
import { spawnSync } from "node:child_process";

export function listMarkdownFilesWithRipgrep(root) {
  const result = spawnSync(
    "rg",
    ["--files", root, "-g", "*.[mM][dD]"],
    {
      encoding: "utf8",
      windowsHide: true,
      maxBuffer: 128 * 1024 * 1024,
    },
  );
  if (result.error) throw result.error;
  if (![0, 1].includes(result.status)) {
    throw new Error(`RG_FILE_INVENTORY_FAILED:${result.status}:${result.stderr.trim()}`);
  }
  return result.stdout
    .replace(/^\uFEFF/, "")
    .split(/\r?\n/)
    .filter(Boolean)
    .map((filePath) => path.resolve(filePath));
}
