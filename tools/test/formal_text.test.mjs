import assert from "node:assert/strict";
import test from "node:test";

import { sanitizeFormalText } from "../formal_text.mjs";

test("formal text removes fixed platform carriers and machine-local paths", () => {
  const result = sanitizeFormalText([
    "第一条 正文。",
    "- IMA知识库：法律全集100000+",
    "- IMA条目ID：word_123",
    "- intake原件：`D:\\private\\source.md`",
    "第二条 建立业务知识库。",
  ].join("\n"));
  assert.equal(result.text, [
    "第一条 正文。",
    "- intake原件：`[本机路径已移除]`",
    "第二条 建立业务知识库。",
  ].join("\n"));
  assert.equal(result.removedPollutionLines, 2);
  assert.equal(result.removedAbsolutePaths, 1);
});
