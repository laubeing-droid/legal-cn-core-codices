import assert from "node:assert/strict";
import test from "node:test";

import { extractPrimaryLegalDocumentBody } from "../legal_document_body.mjs";

test("an appended second legal instrument after the completed primary body is excluded", () => {
  const source = [
    "**北京市实施节约能源法办法**",
    "## 第一章 总则",
    "第一条 主法规正文。",
    "## 第二章 附则",
    "第二条 本办法自公布之日起施行。",
    "---",
    "北京市体育设施管理条例",
    "第一章 总则",
    "第一条 第二部法规正文。",
  ].join("\n");

  const result = extractPrimaryLegalDocumentBody(source);

  assert.equal(result.truncated, true);
  assert.equal(result.trailingTitle, "北京市体育设施管理条例");
  assert.match(result.body, /本办法自公布之日起施行/);
  assert.doesNotMatch(result.body, /北京市体育设施管理条例/);
});

test("an attachment after the primary legal instrument remains part of the body", () => {
  const source = [
    "第一条 正文。",
    "第二条 本办法自公布之日起施行。",
    "---",
    "附件：管制物项目录",
    "一、第一项。",
  ].join("\n");

  const result = extractPrimaryLegalDocumentBody(source);

  assert.equal(result.truncated, false);
  assert.match(result.body, /附件：管制物项目录/);
});
