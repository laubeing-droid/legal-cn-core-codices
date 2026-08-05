import assert from "node:assert/strict";
import crypto from "node:crypto";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  build47277FileCode,
  buildContentStructureCode,
  buildElectronicDocumentBody,
  buildWjbs,
  composeLegalProvisionCode,
  isOfficialCaseId,
  validate47277FileCode,
  validateContentStructureCode,
  validateWjbs,
} from "../standard_codes.mjs";
import {
  extractInlineDataImages,
  localAttachmentReferences,
} from "../markdown_attachments.mjs";
import {
  deriveAgencyCode,
  deriveAgencyName,
  deriveCategoryCode,
  deriveCompleteDate,
  deriveEffectCode,
  deriveExplicitEffectiveDate,
  deriveFileTypeCode,
  deriveLegacyFilenameMetadata,
  deriveNationalRuleAgencyName,
  normalizeRequiredDate,
  deriveSequenceCode,
  normalizeSourceDate,
} from "../standard_metadata.mjs";
import { assignInternalSequenceGroup } from "../internal_sequence.mjs";
import { listMarkdownFilesWithRipgrep } from "../file_inventory.mjs";
import {
  applyMetadataOverride,
  loadMetadataOverrides,
} from "../metadata_overrides.mjs";
import {
  applyOfficialPageMetadata,
  loadOfficialPageMetadata,
  officialPageEvidenceForDocument,
} from "../official_page_metadata.mjs";
import {
  classifySourceContent,
  fragmentDescriptor,
} from "../content_scope.mjs";
import {
  decisionCodingForLegacyCarrier,
  decisionCodingForDocument,
  decisionForDocument,
  decisionOrderForTitle,
  extractDecisionTitleOrder,
  loadDecisionOrderEvidenceRegistry,
  validatedDecisionTitleOrder,
} from "../decision_order.mjs";
import {
  cleanNationalRulesPublishers,
  formalFulltextBlockingCode,
  loadFlkRegistry,
  mapFlkEffectCode,
  officialVersionIdCandidates,
  resolveNationalRuleRecord,
  resolveFlkRecord,
} from "../official_registry.mjs";
import { targetDirectoryForSource } from "../delivery_paths.mjs";
import {
  canonicalizeLegalVersions,
  normalizeCoreProvisionsForCarrierIdentity,
  normalizeLegalTextForIdentity,
} from "../legal_version_identity.mjs";
import {
  describeExactWjbsScope,
  loadExactPathBaseline,
  loadCurrentWjbsBlockedPaths,
  loadWjbsTargetPaths,
  resolveWjbsTargetFiles,
} from "../wjbs_target_scope.mjs";
import {
  loadPublicationSkips,
  partitionPublicationSkips,
} from "../publication_skips.mjs";
import {
  contentStructurePublicationErrors,
  formalLawPublicationDecision,
} from "../publication_output.mjs";

const testDir = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(testDir, "..", "..");
const sourceRoot = path.join(
  repositoryRoot,
  "workspace",
  "source",
  "legal-references",
);
const officialRegistryRoot = path.join(repositoryRoot, "schema", "official_registry");
const registeredPageAuditDir = path.join(
  repositoryRoot,
  "workspace",
  "engineering-history",
  "90_项目任务记录",
  "目录分类与编码修复_20260803_164212",
  "wjbs_gate_audit_20260804",
);
const schemaPath = path.join(repositoryRoot, "schema", "tables.json");
const builderPath = path.resolve(testDir, "..", "build_local_csv.mjs");
const schema = JSON.parse(fs.readFileSync(schemaPath, "utf8").replace(/^\uFEFF/, ""));

test("current-applicable source status maps to the standard effective code", () => {
  assert.equal(deriveEffectCode("现行适用"), "01");
  assert.equal(deriveEffectCode("现行有效"), "01");
});

test("required standard dates reject malformed compact values instead of preserving them", () => {
  assert.equal(normalizeRequiredDate("20021119"), "20021119");
  assert.equal(normalizeRequiredDate("2023-03-01"), "20230301");
  assert.equal(normalizeRequiredDate("77892909"), "");
  assert.equal(normalizeRequiredDate("94577205"), "");
  assert.equal(normalizeRequiredDate("2023-02-29"), "");
});

test("an explicit self-effective clause repairs a corrupted carrier date", () => {
  assert.equal(
    deriveExplicitEffectiveDate("第二十六条 本办法自2002年11月19日起施行。"),
    "20021119",
  );
  assert.equal(
    deriveExplicitEffectiveDate("第六条 本清单自2023年3月1日起施行。"),
    "20230301",
  );
  assert.equal(
    deriveExplicitEffectiveDate("本办法所称事项包括2023年3月1日发生的行为。"),
    "",
  );
});

test("blocked formal laws never emit final Markdown or a final target path", () => {
  const decision = formalLawPublicationDecision({
    lawErrors: [{ code: "MISSING_STANDARD_FIELD", field: "WJBS" }],
    publicationErrors: [],
  });
  assert.equal(decision.publishFormal, false);
  assert.equal(decision.emitMarkdown, false);
  assert.equal(decision.targetRelativePath, "");
  assert.equal(decision.ingestStatus, "BLOCKED_STANDARD_FIELDS");
});

test("ready formal laws emit one final Markdown derivative", () => {
  const decision = formalLawPublicationDecision({ lawErrors: [], publicationErrors: [] });
  assert.equal(decision.publishFormal, true);
  assert.equal(decision.emitMarkdown, true);
  assert.equal(decision.ingestStatus, "READY_FORMAL_LAW");
});

test("article-free legal documents do not invent a zero article content code", () => {
  assert.deepEqual(contentStructurePublicationErrors({
    codeScope: "GBT47277",
    structureRows: [],
    structureFailure: "",
  }), []);
});

test("actual content-structure parsing failures remain publication blockers", () => {
  assert.deepEqual(contentStructurePublicationErrors({
    codeScope: "GBT47277",
    structureRows: [],
    structureFailure: "CONTENT_STRUCTURE_DUPLICATE",
  }), [{ code: "CONTENT_STRUCTURE_DUPLICATE", field: "DE_02001" }]);
});

test("legal identity hash ignores only trailing source-link carriers", () => {
  const body = "# 规则\n\n第一条 正文含 https://example.cn/normative 。";
  const first = `${body}\n\n---\n\n> 来源: 国家规章库 (www.gov.cn)\n> 原文链接: [查看原文](http://www.gov.cn/a)`;
  const second = `${body}\n\n---\n\n> 来源：国家规章库 (www.gov.cn)\n> 原文链接：[查看原文](http://www.gov.cn/b)`;
  assert.equal(normalizeLegalTextForIdentity(first), normalizeLegalTextForIdentity(second));
  assert.notEqual(
    normalizeLegalTextForIdentity(body),
    normalizeLegalTextForIdentity(body.replace("normative", "changed")),
  );
  assert.equal(
    normalizeLegalTextForIdentity("# 发布载体题名\n\n第一条 相同正文"),
    normalizeLegalTextForIdentity("# 规范题名\n\n第一条 相同正文"),
  );
  assert.equal(
    normalizeLegalTextForIdentity("第一条\u001f正文"),
    normalizeLegalTextForIdentity("第一条正文"),
  );
});

test("same core provisions collapse an incomplete carrier into the complete official carrier", () => {
  const shortBody = "# 电子招标投标办法\n\n### 第一条\n共同正文。\n\n### 第二条\n共同结尾。";
  const completeBody = `${shortBody}\n\n附件：《技术规范》\n附件完整正文。`;
  const coreHash = (body) => crypto.createHash("sha256")
    .update(normalizeCoreProvisionsForCarrierIdentity(body))
    .digest("hex");
  assert.equal(coreHash(shortBody), coreHash(completeBody));
  assert.equal(
    coreHash(`${shortBody}\n\n### 第六十六条\n本办法自2013年5月1日起施行。`),
    coreHash(`${shortBody}\n\n### 第六十六条\n本办法自2013年5月1日起施行。附件：《技术规范》\n附件完整正文。`),
  );
  assert.equal(
    coreHash(shortBody),
    coreHash(`${shortBody}\n\n---\n\n> 来源: 国家规章库\n> 原文链接: https://example.cn/rule`),
  );
  const common = {
    title: "电子招标投标办法",
    categoryCode: "1300",
    agencyCode: "0000003032",
    promulgationDate: "20130204",
    sequenceCode: "0020",
    fileTypeCode: "00",
    effectiveDate: "20130501",
    effectCode: "01",
    officialRuleIndexMatch: true,
  };
  const result = canonicalizeLegalVersions([
    {
      ...common,
      relativePath: "incomplete.md",
      normalizedTextSha256: crypto.createHash("sha256").update(shortBody).digest("hex"),
      coreProvisionSha256: coreHash(shortBody),
      normalizedTextLength: shortBody.length,
    },
    {
      ...common,
      relativePath: "complete.md",
      normalizedTextSha256: crypto.createHash("sha256").update(completeBody).digest("hex"),
      coreProvisionSha256: coreHash(completeBody),
      normalizedTextLength: completeBody.length,
    },
  ]);
  assert.deepEqual(result.canonical.map((entry) => entry.relativePath), ["complete.md"]);
  assert.equal(result.duplicates[0].canonicalRelativePath, "complete.md");
});

test("different core provisions never collapse merely because metadata matches", () => {
  const firstBody = "### 第一条\n甲正文。";
  const secondBody = "### 第一条\n乙正文。";
  const coreHash = (body) => crypto.createHash("sha256")
    .update(normalizeCoreProvisionsForCarrierIdentity(body))
    .digest("hex");
  const common = {
    title: "同名办法",
    categoryCode: "1400",
    agencyCode: "1100003000",
    promulgationDate: "20200101",
    sequenceCode: "0001",
    fileTypeCode: "00",
    effectiveDate: "20200201",
    effectCode: "01",
  };
  const result = canonicalizeLegalVersions([
    {
      ...common,
      relativePath: "first.md",
      normalizedTextSha256: crypto.createHash("sha256").update(firstBody).digest("hex"),
      coreProvisionSha256: coreHash(firstBody),
    },
    {
      ...common,
      relativePath: "second.md",
      normalizedTextSha256: crypto.createHash("sha256").update(secondBody).digest("hex"),
      coreProvisionSha256: coreHash(secondBody),
    },
  ]);
  assert.equal(result.canonical.length, 2);
  assert.equal(result.duplicates.length, 0);
});

test("candidate build fails closed when official page metadata registry is omitted", () => {
  const result = spawnSync(
    process.execPath,
    [
      builderPath,
      "--full-corpus",
      "--full-corpus-purpose",
      "FINAL_ACCEPTANCE_ONLY",
      "--output-root",
      "X",
      "--engineering-root",
      "Y",
    ],
    { encoding: "utf8" },
  );
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /必须显式提供 --official-page-metadata/);
});

test("candidate build never falls back to full-corpus enumeration without explicit consent", () => {
  const result = spawnSync(process.execPath, [builderPath], { encoding: "utf8" });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /必须显式选择 --full-corpus 或提供精确路径基线/);
});

test("full-corpus enumeration requires final-acceptance double confirmation", () => {
  const result = spawnSync(process.execPath, [builderPath, "--full-corpus"], { encoding: "utf8" });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /--full-corpus-purpose FINAL_ACCEPTANCE_ONLY/);
});

test("WJBS target scope reads only the 44 and legacy-sequence cohorts from baseline", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "wjbs-target-scope-"));
  try {
    const first = path.join(directory, "01", "a,one.md");
    const second = path.join(directory, "01", "b.md");
    fs.mkdirSync(path.dirname(first), { recursive: true });
    fs.writeFileSync(first, "# A\n", "utf8");
    fs.writeFileSync(second, "# B\n", "utf8");
    const baseline = path.join(directory, "baseline.csv");
    fs.writeFileSync(baseline, [
      "relative_path,WJBS,internal_sequence_source",
      '"01/a,one.md",,STANDARD_DERIVED_LOCAL',
      "01/b.md,existing,LOCAL_NORMALIZED_TITLE_ORDER",
      "01/not-target.md,existing,STANDARD_DERIVED_LOCAL",
      "",
    ].join("\r\n"), "utf8");
    const targets = loadWjbsTargetPaths(baseline);
    assert.deepEqual([...targets], ["01/a,one.md", "01/b.md"]);
    assert.deepEqual(resolveWjbsTargetFiles(directory, targets), [first, second]);
    assert.throws(
      () => resolveWjbsTargetFiles(directory, new Set(["../escape.md"])),
      /非法路径/,
    );
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("current WJBS blocked scope excludes resolved and out-of-scope rows", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "wjbs-current-blocked-"));
  try {
    const baseline = path.join(directory, "current.csv");
    fs.writeFileSync(baseline, [
      "relative_path,WJBS,internal_sequence_source,coding_status,blocking_reason",
      "01/sequence.md,,BLOCKED_MISSING_OFFICIAL_DECISION_ORDER,BLOCKED,MISSING_STANDARD_FIELD:WJBS",
      "01/agency.md,,,BLOCKED,MISSING_STANDARD_FIELD:WJBS|MISSING_STANDARD_FIELD:ZDJGDM",
      "01/effect.md,existing,STANDARD_DERIVED_LOCAL,BLOCKED,MISSING_STANDARD_FIELD:SXX",
      "01/out.md,,,OUT_OF_STANDARD_SCOPE,NON_NORMATIVE",
      "01/ready.md,existing,STANDARD_DERIVED_LOCAL,READY,",
      "",
    ].join("\r\n"), "utf8");
    assert.deepEqual(
      [...loadCurrentWjbsBlockedPaths(baseline)],
      ["01/sequence.md", "01/agency.md"],
    );
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("publication skip registry is exact, explicit, and limited to the approved paths", () => {
  const registryPath = path.resolve(
    testDir,
    "..",
    "..",
    "schema",
    "publication_skip_registry.csv",
  );
  const skips = loadPublicationSkips(registryPath);
  assert.equal(skips.size, 9);
  assert.ok([...skips.values()].every((entry) => entry.status === "ACTIVE"));
  assert.equal(
    skips.get("01_立法与公开行政文件/04_规章/01_部门规章/交通运输部规章/大型飞机公共航空运输承运人运行合格审定规则_2026-01-01_有效_ima-5cce8912.md")?.skipCode,
    "CONTENT_STRUCTURE_UNREPRESENTABLE",
  );
  assert.equal(
    skips.get("01_立法与公开行政文件/04_规章/01_部门规章/交通运输部规章/涡轮发动机飞机燃油排泄和排气排出物规定_2028-01-01_有效_ima-2d2cdb5a.md")?.skipCode,
    "CONTENT_STRUCTURE_UNREPRESENTABLE",
  );
  for (const relativePath of skips.keys()) {
    assert.ok(fs.existsSync(path.resolve(sourceRoot, relativePath)));
  }
});

test("publication skips remove only registered laws from formal processing", () => {
  const entries = [
    { relativePath: "01/skip.md" },
    { relativePath: "01/keep.md" },
  ];
  const skips = new Map([[
    "01/skip.md",
    {
      relativePath: "01/skip.md",
      skipCode: "MISSING_OFFICIAL_DECISION_ORDER",
      status: "ACTIVE",
      rationale: "官方历史顺序不可得，按用户决定跳过正式编码。",
    },
  ]]);
  const partition = partitionPublicationSkips(entries, skips);
  assert.deepEqual(partition.included.map((entry) => entry.relativePath), ["01/keep.md"]);
  assert.deepEqual(partition.skipped.map((entry) => entry.relativePath), ["01/skip.md"]);
  assert.equal(partition.skipped[0].publicationSkip.skipCode, "MISSING_OFFICIAL_DECISION_ORDER");
});

test("exact path baseline selects every listed path without cohort inference", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "exact-path-baseline-"));
  try {
    const baseline = path.join(directory, "exact.csv");
    fs.writeFileSync(baseline, [
      "relative_path,reason",
      '"01/a,one.md",MISSING_EFFECT',
      "02/b.md,DUPLICATE_REVIEW",
      '"01/a,one.md",DUPLICATE_INPUT',
      "",
    ].join("\r\n"), "utf8");
    assert.deepEqual([...loadExactPathBaseline(baseline)], ["01/a,one.md", "02/b.md"]);

    const empty = path.join(directory, "empty.csv");
    fs.writeFileSync(empty, "relative_path\r\n", "utf8");
    assert.throws(() => loadExactPathBaseline(empty), /没有目标记录/);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("exact WJBS scope summary cannot claim full-corpus enumeration", () => {
  const workspaceRoot = path.resolve("D:/legal-references");
  const files = [
    path.join(workspaceRoot, "01_立法与公开行政文件", "a.md"),
    path.join(workspaceRoot, "02_法院系统", "b.md"),
  ];
  assert.deepEqual(describeExactWjbsScope(workspaceRoot, files), {
    enumeration_mode: "EXACT_BASELINE_PATHS",
    full_corpus_enumerated: false,
    source_roots: ["01_立法与公开行政文件", "02_法院系统"],
    source_files: 2,
  });
});

test("identical legal-version carriers collapse to one formal object and remain traceable", () => {
  const common = {
    title: "不动产登记暂行条例",
    categoryCode: "0400",
    agencyCode: "0000001002",
    promulgationDate: "20240310",
    sequenceCode: "0123",
    fileTypeCode: "00",
    effectiveDate: "20240501",
    effectCode: "01",
    normalizedTextSha256: "a".repeat(64),
  };
  const result = canonicalizeLegalVersions([
    { ...common, relativePath: "02/second.md", officialIndexMatch: false },
    { ...common, relativePath: "02/official.md", officialIndexMatch: true },
  ]);
  assert.deepEqual(result.canonical.map((entry) => entry.relativePath), ["02/official.md"]);
  assert.deepEqual(result.duplicates, [{
    relativePath: "02/second.md",
    canonicalRelativePath: "02/official.md",
    reason: "DUPLICATE_NORMALIZED_LEGAL_VERSION",
  }]);
});

test("same event with different normalized text remains two legal versions", () => {
  const common = {
    title: "某条例",
    categoryCode: "0500",
    agencyCode: "1300000001",
    promulgationDate: "20240101",
    sequenceCode: "0001",
    fileTypeCode: "00",
    effectiveDate: "20240201",
    effectCode: "01",
  };
  const result = canonicalizeLegalVersions([
    { ...common, relativePath: "a.md", normalizedTextSha256: "a".repeat(64) },
    { ...common, relativePath: "b.md", normalizedTextSha256: "b".repeat(64) },
  ]);
  assert.equal(result.canonical.length, 2);
  assert.equal(result.duplicates.length, 0);
});

test("conflicting effect metadata prevents silent legal-version deduplication", () => {
  const common = {
    title: "某办法",
    categoryCode: "0600",
    agencyCode: "0000004970",
    promulgationDate: "20200101",
    sequenceCode: "0002",
    fileTypeCode: "00",
    effectiveDate: "20200201",
    normalizedTextSha256: "c".repeat(64),
  };
  const result = canonicalizeLegalVersions([
    { ...common, relativePath: "valid.md", effectCode: "01" },
    { ...common, relativePath: "repealed.md", effectCode: "03" },
  ]);
  assert.equal(result.canonical.length, 2);
  assert.equal(result.duplicates.length, 0);
});

test("one official index effect resolves an otherwise identical carrier conflict", () => {
  const common = {
    title: "中华人民共和国药品管理法实施条例",
    categoryCode: "0400",
    agencyCode: "0000003000",
    promulgationDate: "20241206",
    sequenceCode: "0360",
    fileTypeCode: "00",
    effectiveDate: "20250120",
    normalizedTextSha256: "d".repeat(64),
  };
  const result = canonicalizeLegalVersions([
    {
      ...common,
      relativePath: "official-amended.md",
      effectCode: "03",
      officialIndexMatch: true,
    },
    {
      ...common,
      relativePath: "unverified-effective.md",
      effectCode: "01",
      officialIndexMatch: false,
    },
  ]);
  assert.deepEqual(result.canonical.map((entry) => entry.relativePath), ["official-amended.md"]);
  assert.deepEqual(result.duplicates, [{
    relativePath: "unverified-effective.md",
    canonicalRelativePath: "official-amended.md",
    reason: "DUPLICATE_NORMALIZED_LEGAL_VERSION_OFFICIAL_METADATA_RESOLVED",
  }]);
});

test("one complete carrier resolves an identical carrier with missing version metadata", () => {
  const common = {
    title: "关于修改甲条例的决定",
    categoryCode: "0700",
    agencyCode: "1300001001",
    promulgationDate: "20210929",
    sequenceCode: "0094",
    fileTypeCode: "00",
    normalizedTextSha256: "d".repeat(64),
  };
  const result = canonicalizeLegalVersions([
    {
      ...common,
      relativePath: "complete.md",
      effectiveDate: "20210929",
      effectCode: "01",
    },
    {
      ...common,
      relativePath: "missing-effect.md",
      effectiveDate: "20210929",
      effectCode: "",
    },
  ]);
  assert.equal(result.canonical.length, 1);
  assert.equal(result.canonical[0].relativePath, "complete.md");
  assert.equal(result.duplicates[0].canonicalRelativePath, "complete.md");
});

test("one official index version resolves a conflicting local default effective date", () => {
  const common = {
    title: "广东省实施中华人民共和国妇女权益保障法办法",
    categoryCode: "0700",
    agencyCode: "4400001001",
    promulgationDate: "20070531",
    sequenceCode: "0009",
    fileTypeCode: "00",
    normalizedTextSha256: "e".repeat(64),
  };
  const result = canonicalizeLegalVersions([
    {
      ...common,
      relativePath: "official-amended.md",
      effectiveDate: "20071001",
      effectCode: "03",
      officialIndexMatch: true,
    },
    {
      ...common,
      relativePath: "unverified-local-default.md",
      effectiveDate: "20070531",
      effectCode: "01",
      officialIndexMatch: false,
    },
  ]);
  assert.deepEqual(result.canonical.map((entry) => entry.relativePath), ["official-amended.md"]);
  assert.deepEqual(result.duplicates, [{
    relativePath: "unverified-local-default.md",
    canonicalRelativePath: "official-amended.md",
    reason: "DUPLICATE_NORMALIZED_LEGAL_VERSION_OFFICIAL_METADATA_RESOLVED",
  }]);
});

test("different effective dates remain independent without unique official evidence", () => {
  const common = {
    title: "某地方性法规",
    categoryCode: "0700",
    agencyCode: "4400001001",
    promulgationDate: "20070531",
    sequenceCode: "0009",
    fileTypeCode: "00",
    effectCode: "01",
    normalizedTextSha256: "f".repeat(64),
  };
  const result = canonicalizeLegalVersions([
    { ...common, relativePath: "first.md", effectiveDate: "20070531" },
    { ...common, relativePath: "second.md", effectiveDate: "20071001" },
  ]);
  assert.equal(result.canonical.length, 2);
  assert.equal(result.duplicates.length, 0);
});

test("same joint rule carriers deduplicate by evidenced agency name while agency code stays blocked", () => {
  const common = {
    title: "人防建设与城市建设相结合实施办法",
    categoryCode: "1400",
    agencyName: "济南军区",
    agencyCode: "",
    promulgationDate: "19890814",
    sequenceCode: "0086",
    fileTypeCode: "00",
    effectiveDate: "19890814",
    effectCode: "01",
    normalizedTextSha256: "1".repeat(64),
  };
  const result = canonicalizeLegalVersions([
    { ...common, relativePath: "henan.md" },
    { ...common, relativePath: "shandong.md" },
  ]);
  assert.equal(result.canonical.length, 1);
  assert.deepEqual(result.duplicates, [{
    relativePath: "shandong.md",
    canonicalRelativePath: "henan.md",
    reason: "DUPLICATE_NORMALIZED_LEGAL_VERSION",
  }]);
});

test("missing both agency code and agency name remains fail-closed for carrier identity", () => {
  const common = {
    title: "同名办法",
    categoryCode: "1400",
    agencyName: "",
    agencyCode: "",
    promulgationDate: "19890814",
    sequenceCode: "0000",
    fileTypeCode: "00",
    effectiveDate: "19890814",
    effectCode: "01",
    normalizedTextSha256: "2".repeat(64),
  };
  const result = canonicalizeLegalVersions([
    { ...common, relativePath: "first.md" },
    { ...common, relativePath: "second.md" },
  ]);
  assert.equal(result.canonical.length, 2);
  assert.equal(result.duplicates.length, 0);
});

test("CSV builder requires an explicit exchange-candidate output root", () => {
  const help = spawnSync(process.execPath, [builderPath, "--help"], { encoding: "utf8" });
  assert.equal(help.status, 0);
  assert.match(help.stdout, /--output-root/);

  const missing = spawnSync(
    process.execPath,
    [builderPath, "--full-corpus", "--full-corpus-purpose", "FINAL_ACCEPTANCE_ONLY"],
    { encoding: "utf8" },
  );
  assert.notEqual(missing.status, 0);
  assert.match(missing.stderr, /--output-root/);
});

test("local migration builder does not require an online fulltext registry", () => {
  const source = fs.readFileSync(builderPath, "utf8");
  assert.doesNotMatch(source, /flk_fulltext/i);
  assert.doesNotMatch(source, /formalFulltextBlockingCode/);
  assert.doesNotMatch(source, /formalErrors\.length === 0 && officialCarrier/);
  assert.doesNotMatch(source, /\.docx/i);
  assert.doesNotMatch(source, /path\.resolve\(formalMarkdownDir,\s*relativePath\)/);
  assert.match(source, /Markdown/);
  assert.match(source, /source_relative_path/);
  assert.match(source, /source_sha256/);
  assert.ok(source.includes("IMA(?:知识库|条目ID)"));
});

test("successfully stripped platform pollution is an engineering warning, not a formal blocker", () => {
  const source = fs.readFileSync(builderPath, "utf8");
  const pollutionBranch = source.match(
    /if \(thirdPartyPollution\) \{([\s\S]+?)\n\s*\}/u,
  )?.[1] ?? "";
  assert.match(pollutionBranch, /error_code: "FIXED_PLATFORM_POLLUTION"/u);
  assert.match(pollutionBranch, /severity: "WARNING"/u);
  assert.match(pollutionBranch, /正式 Markdown 已移除/u);
});

test("builder uses the traceable union of complete national rules snapshots", () => {
  const source = fs.readFileSync(builderPath, "utf8");
  assert.match(source, /national_rules_database_union_20260730_20260803/);
  assert.doesNotMatch(source, /national_rules_database_20260730_full/);
  assert.doesNotMatch(source, /national_rules_database_20260803_full/);
});

test("date normalization never turns a year-month into a fabricated day", () => {
  assert.equal(normalizeSourceDate("2026-04"), "2026-04");
  assert.equal(deriveCompleteDate("2026-04"), "");
  assert.equal(deriveCompleteDate("2026-02-30"), "");
  assert.equal(deriveCompleteDate("发布时间：2026-01-20"), "2026-01-20");
});

test("GB/T 47229.2 WJBS accepts authority value or deterministic local standard derivation", () => {
  const body = buildElectronicDocumentBody({
    category: "0100",
    agency: "0000001001",
    promulgationDate: "20230313",
    sequence: "0003",
    internalSequence: "000",
    fileCategory: "00",
  });
  assert.equal(body.length, 31);
  const wjbs = `1.2.156.3005.6-${body}`;
  assert.equal(buildWjbs({
    category: "0100",
    agency: "0000001001",
    promulgationDate: "20230313",
    sequence: "0003",
    internalSequence: "000",
    fileCategory: "00",
  }), wjbs);
  assert.deepEqual(validateWjbs(wjbs, { sourceType: "AUTHORITY_ISSUED" }), []);
  assert.deepEqual(validateWjbs(wjbs, { sourceType: "STANDARD_DERIVED_LOCAL" }), []);
  assert.ok(validateWjbs(wjbs).includes("WJBS_PROVENANCE_MISSING"));
  assert.ok(validateWjbs(`${wjbs}9`, {
    sourceType: "STANDARD_DERIVED_LOCAL",
  }).includes("INVALID_WJBS_FORMAT"));
});

test("GB/T 47277 file code rejects categories 1600-2100", () => {
  const valid = build47277FileCode({
    category: "1100",
    agency: "0000001610",
    promulgationDate: "20240821",
    sequence: "0009",
    internalSequence: "000",
    fileType: "00",
  });
  assert.equal(valid.length, 31);
  assert.deepEqual(validate47277FileCode(valid), []);
  assert.throws(
    () => build47277FileCode({
      category: "2000",
      agency: "0000001610",
      promulgationDate: "20240821",
      sequence: "0009",
      internalSequence: "000",
      fileType: "00",
    }),
    /CATEGORY_OUTSIDE_GBT47277/,
  );
});

test("18-digit content structure and 49-digit provision code are exact", () => {
  const content = buildContentStructureCode({
    book: 0,
    subBook: 0,
    chapter: 1,
    section: 1,
    article: 10,
    paragraph: 2,
    item: 3,
    subItem: 0,
  });
  assert.equal(content, "000001010010020300");
  assert.deepEqual(validateContentStructureCode(content), []);
  const fileCode = "1100000000161020240821000900000";
  assert.equal(composeLegalProvisionCode(fileCode, content).length, 49);
});

test("formal schema keeps standard fields separate from engineering hashes and states", () => {
  const documents = schema.tables["legal_documents.csv"].columns;
  const contents = schema.tables["legal_contents.csv"].columns;
  const sources = schema.tables["legal_sources.csv"].columns;
  const cases = schema.tables["cases.csv"].columns;
  assert.ok(documents.includes("DE_01001"));
  assert.ok(documents.includes("DE_01021"));
  assert.ok(!contents.includes("DE_02006_sha256"));
  assert.ok(!sources.includes("DE_04003_sha256"));
  assert.ok(!cases.includes("source_status"));
});

test("case ids reject dates, IMA ids, hashes and local sequence numbers", () => {
  assert.equal(isOfficialCaseId("2024-01-01"), false);
  assert.equal(isOfficialCaseId("ima-pdf_12dd-12345678"), false);
  assert.equal(isOfficialCaseId("0123456789abcdef0123456789abcdef"), false);
  assert.equal(isOfficialCaseId("CASE-000001"), false);
  assert.equal(isOfficialCaseId("检例第186号"), true);
  assert.equal(isOfficialCaseId("2024-07-2-111-001"), true);
});

test("attachment parser accepts document links and rejects obfuscated script fragments", () => {
  const markdown = [
    "![图一](../附件/示意图.png)",
    "[附件](./files/裁定书.pdf \"下载\")",
    "q,F[D3('0x380','k%50'",
    "![远程图](https://example.test/a.png)",
    "[普通网页](./index.html)",
  ].join("\n");
  assert.deepEqual(
    localAttachmentReferences(markdown).map((item) => item.decoded),
    [path.normalize("../附件/示意图.png"), path.normalize("./files/裁定书.pdf")],
  );
});

test("inline Base64 images are removed from legal text and retained as hashed attachment evidence", () => {
  const payload = Buffer.from("binary image evidence", "utf8").toString("base64");
  const source = `正文。\n![保护范围图](data:image/jpeg;base64,${payload})\n第二条。`;
  const result = extractInlineDataImages(source);
  assert.equal(result.attachments.length, 1);
  assert.equal(result.attachments[0].label, "保护范围图");
  assert.equal(result.attachments[0].mimeType, "image/jpeg");
  assert.equal(result.attachments[0].byteLength, 21);
  assert.match(result.attachments[0].sha256, /^[0-9a-f]{64}$/);
  assert.doesNotMatch(result.markdown, /data:image|base64/);
  assert.match(result.markdown, new RegExp(result.attachments[0].sha256));
});

test("standard metadata derives exact categories from declared type before path fallback", () => {
  assert.equal(deriveCategoryCode({ group: "法律" }, "01_x/01_y/a.md"), "0100");
  assert.equal(
    deriveCategoryCode({ 法律类型: "地方政府规章" }, "01_x/04_y/02_z/a.md"),
    "1400",
  );
  assert.equal(
    deriveCategoryCode({}, "02_法院系统/02_法院司法规范性文件/a.md"),
    "2000",
  );
  assert.equal(deriveCategoryCode({ group: "修改、废止的决定" }, "01_x/04_y/01_z/a.md"), "1300");
  assert.equal(
    deriveCategoryCode(
      { group: "修改、废止的决定" },
      "01_立法与公开行政文件/01_宪法、法律与全国人大规范性文件/a.md",
    ),
    "0100",
  );
  assert.equal(
    deriveCategoryCode(
      { group: "修改、废止的决定" },
      "01_立法与公开行政文件/03_地方立法/02_自治条例和单行条例/a.md",
    ),
    "0800",
  );
  assert.equal(
    deriveCategoryCode(
      { group: "修改、废止的决定" },
      "02_法院系统/01_司法解释及审判规则/a.md",
    ),
    "1100",
  );
});

test("exact metadata evidence overrides only allowlisted standard fields", () => {
  const registryPath = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    "..",
    "..",
    "schema",
    "标准元数据补证注册表.json",
  );
  const registry = loadMetadataOverrides(registryPath);
  const relativePath = "01_立法与公开行政文件/03_地方立法/01_地方性法规/四川/四川省绿化条例_0000-00-00_有效_ff808181927f127601930063dfb64209.md";
  const row = applyMetadataOverride({ GBRQ: "", SXRQ: "" }, registry.get(relativePath));
  assert.equal(row.GBRQ, "20020330");
  assert.equal(row.SXRQ, "20020330");
  assert.equal(row._promulgation_source, "OFFICIAL_LEGISLATIVE_HISTORY");
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "document-number-override-"));
  const documentNumberRegistry = path.join(directory, "override.json");
  fs.writeFileSync(documentNumberRegistry, JSON.stringify({
    entries: [{
      relative_path: "a.md",
      values: { FWZH: "法发〔2000〕24号" },
      evidence: { type: "SOURCE_BODY_DOCUMENT_NUMBER" },
    }],
  }), "utf8");
  const documentNumber = loadMetadataOverrides(documentNumberRegistry);
  assert.equal(
    applyMetadataOverride({ FWZH: "" }, documentNumber.get("a.md")).FWZH,
    "法发〔2000〕24号",
  );
});

test("metadata override can correct carrier-derived effect and invalidity metadata", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "metadata-effect-override-"));
  const registryPath = path.join(directory, "registry.json");
  try {
    fs.writeFileSync(registryPath, JSON.stringify({
      entries: [{
        relative_path: "a.md",
        values: {
          ZDJGMC: "国家互联网信息办公室",
          ZDJGDM: "0000006350",
          GBRQ: "20200413",
          SXRQ: "20200601",
          SXX: "04",
          SHXRQ: "20220215",
          _effect_source: "OFFICIAL_REPEAL_CLAUSE",
        },
        evidence: { type: "OFFICIAL_REPEAL_CLAUSE" },
      }],
    }), "utf8");
    const registry = loadMetadataOverrides(registryPath);
    const row = applyMetadataOverride({ SXX: "01", SHXRQ: "" }, registry.get("a.md"));
    assert.equal(row.ZDJGMC, "国家互联网信息办公室");
    assert.equal(row.ZDJGDM, "0000006350");
    assert.equal(row.GBRQ, "20200413");
    assert.equal(row.SXRQ, "20200601");
    assert.equal(row.SXX, "04");
    assert.equal(row.SHXRQ, "20220215");
    assert.equal(row._effect_source, "OFFICIAL_REPEAL_CLAUSE");
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("Jinan Military Region joint air-defense carriers share the evidenced issuing agency name", () => {
  const registryPath = path.resolve(testDir, "..", "..", "schema", "标准元数据补证注册表.json");
  const metadata = loadMetadataOverrides(registryPath);
  const paths = [
    "01_立法与公开行政文件/04_规章/02_地方政府规章/河南/人防建设与城市建设相结合实施办法_1989-08-14_有效_ima-952e2a0a.md",
    "01_立法与公开行政文件/04_规章/02_地方政府规章/山东/人防建设与城市建设相结合实施办法_1989-08-14_有效_ima-e4f8e892.md",
  ];
  for (const relativePath of paths) {
    const override = metadata.get(relativePath);
    assert.ok(override, relativePath);
    const row = applyMetadataOverride({ ZDJGMC: "", ZDJGDM: "", FWZH: "" }, override);
    assert.equal(row.ZDJGMC, "济南军区", relativePath);
    assert.equal(row.ZDJGDM, "", relativePath);
    assert.equal(row.FWZH, "〔1989〕济字第86号", relativePath);
    assert.equal(
      row._agency_name_source,
      "OFFICIAL_PAGE_DOCUMENT_NUMBER_AND_BODY",
      relativePath,
    );
  }
});

test("same-title local rules preserve distinct official revision events", () => {
  const registryPath = path.resolve(testDir, "..", "..", "schema", "标准元数据补证注册表.json");
  const metadata = loadMetadataOverrides(registryPath);
  const expected = new Map([
    [
      "01_立法与公开行政文件/04_规章/02_地方政府规章/湖北/湖北省公共安全视频图像信息系统管理办法_2013-07-08_有效_gov-rule-a31bb0b0d1734c6e4a30223879a063fb.md",
      ["20260606", "湖北省人民政府令第440号", "20260801"],
    ],
    [
      "01_立法与公开行政文件/04_规章/02_地方政府规章/湖南/张家界市人民政府起草地方性法规草案和制定政府规章程序规定_2025-01-10_有效_ima-fe86a918.md",
      ["20250110", "张家界市人民政府令第46号", "20250210"],
    ],
    [
      "01_立法与公开行政文件/04_规章/02_地方政府规章/上海/上海市市标制作使用管理暂行规定_1991-02-09_有效_gov-rule-9841cdf0c17036b624ec17b36a5cb5bd.md",
      ["19971219", "上海市人民政府令第54号", "19980101"],
    ],
    [
      "01_立法与公开行政文件/04_规章/02_地方政府规章/上海/上海市市标制作使用管理暂行规定_1991-02-09_有效_gov-rule-8f538a8291b6b478fa3f39f98fc7fe30.md",
      ["20240402", "上海市人民政府令第13号", "20240515"],
    ],
  ]);
  for (const [relativePath, [date, documentNumber, effectiveDate]] of expected) {
    const override = metadata.get(relativePath);
    assert.ok(override, relativePath);
    const row = applyMetadataOverride({ GBRQ: "19910209", FWZH: "", SXRQ: "" }, override);
    assert.equal(row.GBRQ, date, relativePath);
    assert.equal(row.FWZH, documentNumber, relativePath);
    assert.equal(row.SXRQ, effectiveDate, relativePath);
    assert.equal(row._promulgation_source, "OFFICIAL_VERSION_EVENT", relativePath);
    assert.equal(row._effective_date_source, "OFFICIAL_VERSION_EVENT", relativePath);
  }
});

test("registered national-rule version events replace republication metadata", () => {
  const metadataRegistryPath = path.resolve(testDir, "..", "..", "schema", "标准元数据补证注册表.json");
  const decisionRegistryPath = path.resolve(
    officialRegistryRoot,
    "decision_order_evidence",
    "registry.json",
  );
  const metadata = loadMetadataOverrides(metadataRegistryPath);
  const cyber = metadata.get("01_立法与公开行政文件/04_规章/01_部门规章/国家市场监督管理总局规章/网络安全审查办法_2020-06-01_有效_ima-501d755d.md");
  assert.equal(cyber.values.ZDJGMC, "国家互联网信息办公室");
  assert.equal(cyber.values.GBRQ, "20200413");
  assert.equal(cyber.values.SXX, "04");
  assert.equal(cyber.values.SHXRQ, "20220215");

  const venture = metadata.get("01_立法与公开行政文件/04_规章/01_部门规章/国家市场监督管理总局规章/外商投资创业投资企业管理规定_2003-03-01_有效_ima-f26a4551.md");
  assert.equal(venture.values.ZDJGMC, "商务部");
  assert.equal(venture.values.GBRQ, "20151028");
  assert.equal(venture.values.FWZH, "中华人民共和国商务部令2015年第2号");

  const decisions = loadDecisionOrderEvidenceRegistry(decisionRegistryPath);
  const merger2001 = decisions.find((item) => item.promulgationDate === "20011122");
  const acquisition2009 = decisions.find((item) => item.promulgationDate === "20090622");
  const commerce2015 = decisions.find((item) => item.promulgationDate === "20151028");
  assert.equal(decisionOrderForTitle("外商投资企业合并与分立规定", merger2001.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("商务部关于外国投资者并购境内企业的规定", acquisition2009.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("外商投资创业投资企业管理规定", commerce2015.orderedTitles), 6);
});

test("central department decision orders and 2005 finance orders are registered exactly", () => {
  const metadataRegistryPath = path.resolve(testDir, "..", "..", "schema", "标准元数据补证注册表.json");
  const decisionRegistryPath = path.resolve(
    officialRegistryRoot,
    "decision_order_evidence",
    "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(decisionRegistryPath);
  const miit = decisions.find((item) => (
    item.agencyCode === "0000003392" && item.promulgationDate === "20140923"
  ));
  const mct = decisions.find((item) => (
    item.agencyCode === "0000003720" && item.promulgationDate === "20171215"
  ));
  const csrc = decisions.find((item) => (
    item.agencyCode === "0000004970" && item.promulgationDate === "20210115"
  ));
  const miit2015 = decisions.find((item) => (
    item.agencyCode === "0000003392" && item.promulgationDate === "20150429"
  ));
  const ndrc2013 = decisions.find((item) => (
    item.agencyCode === "0000003032" && item.promulgationDate === "20130311"
  ));
  assert.equal(decisionOrderForTitle("电信服务质量监督管理暂行办法", miit.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("公用电信网间互联管理规定", miit.orderedTitles), 2);
  assert.equal(decisionOrderForTitle("电信网码号资源管理办法", miit.orderedTitles), 4);
  assert.equal(decisionOrderForTitle("社会艺术水平考级管理办法", mct.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("营业性演出管理条例实施细则", mct.orderedTitles), 2);
  assert.equal(decisionOrderForTitle("娱乐场所管理办法", mct.orderedTitles), 5);
  assert.equal(decisionOrderForTitle("证券公司和证券投资基金管理公司境外设立、收购、参股经营机构管理办法", csrc.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("期货公司董事、监事和高级管理人员任职管理办法", csrc.orderedTitles), 2);
  assert.equal(decisionOrderForTitle("证券基金经营机构信息技术管理办法", csrc.orderedTitles), 4);
  assert.equal(decisionOrderForTitle("民用爆炸物品销售许可实施办法", miit2015.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("电子认证服务管理办法", miit2015.orderedTitles), 2);
  assert.equal(decisionOrderForTitle("工程建设项目勘察设计招标投标办法", ndrc2013.orderedTitles), 7);
  assert.equal(decisionOrderForTitle("工程建设项目货物招标投标办法", ndrc2013.orderedTitles), 10);

  const metadata = loadMetadataOverrides(metadataRegistryPath);
  const financeRoot = "01_立法与公开行政文件/04_规章/01_部门规章/财政部规章/";
  assert.equal(metadata.get(`${financeRoot}代理记账管理办法_2005-03-01_有效_ima-2cf31e8f.md`).values.FWZH, "中华人民共和国财政部令第27号");
  assert.equal(metadata.get(`${financeRoot}会计从业资格管理办法_2005-03-01_有效_ima-91325348.md`).values.FWZH, "中华人民共和国财政部令第26号");
  assert.equal(metadata.get(`${financeRoot}注册会计师注册办法_2005-03-01_有效_ima-c31537ab.md`).values.FWZH, "中华人民共和国财政部令第25号");

  const miitRoot = "01_立法与公开行政文件/04_规章/01_部门规章/工业和信息化部规章/";
  const harmfulSubstances = metadata.get(`${miitRoot}电器电子产品有害物质限制使用管理办法_2016-07-01_有效_ima-cab29aeb.md`);
  const electronicTender = metadata.get(`${miitRoot}电子招标投标办法_2013-05-01_有效_ima-9632e8ba.md`);
  const chemicals = metadata.get(`${miitRoot}中华人民共和国监控化学品管理条例实施细则_2019-01-01_有效_ima-d35e42cd.md`);
  assert.equal(harmfulSubstances.values.GBRQ, "20160106");
  assert.equal(harmfulSubstances.values.FWZH.endsWith("令第32号"), true);
  assert.equal(electronicTender.values.ZDJGDM, "0000003032");
  assert.equal(electronicTender.values.GBRQ, "20130204");
  assert.equal(electronicTender.values.FWZH.endsWith("令第20号"), true);
  assert.equal(chemicals.values.GBRQ, "20180702");
  assert.equal(chemicals.values.FWZH, "中华人民共和国工业和信息化部令第48号");
});

test("2026-08-04 central rule decision batches preserve official internal order", () => {
  const decisionRegistryPath = path.resolve(
    officialRegistryRoot,
    "decision_order_evidence",
    "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(decisionRegistryPath);
  const byKey = (agencyCode, promulgationDate, sequenceCode) => decisions.find((item) => (
    item.agencyCode === agencyCode
    && item.promulgationDate === promulgationDate
    && item.sequenceCode === sequenceCode
  ));

  const hrss2019 = byKey("0000003561", "20191231", "0043");
  const hrss2015 = byKey("0000003561", "20150430", "0024");
  const agriculture2017 = byKey("0000003260", "20171130", "0008");
  const naturalResources2019 = byKey("0000003670", "20190724", "0005");
  const csrc2021 = byKey("0000004970", "20210611", "0184");
  const ndrc2023 = byKey("0000003032", "20230323", "0001");
  const miit2002 = byKey("0000003391", "20020626", "0022");
  const mps2020 = byKey("0000003120", "20200806", "0160");
  const aqsiqMii2002 = byKey("0000004240", "20020723", "0024");
  const csrc2025 = byKey("0000004970", "20251231", "0232");

  assert.ok(hrss2019);
  assert.ok(hrss2015);
  assert.ok(agriculture2017);
  assert.ok(naturalResources2019);
  assert.ok(csrc2021);
  assert.ok(ndrc2023);
  assert.ok(miit2002);
  assert.ok(mps2020);
  assert.ok(aqsiqMii2002);
  assert.ok(csrc2025);
  assert.equal(decisionOrderForTitle("人才市场管理规定", hrss2019.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("外商投资人才中介机构管理暂行规定", hrss2019.orderedTitles), 2);
  assert.equal(decisionOrderForTitle("企业年金基金管理机构资格认定暂行办法", hrss2015.orderedTitles), 6);
  assert.equal(decisionOrderForTitle("企业年金基金管理办法", hrss2015.orderedTitles), 7);
  assert.equal(decisionOrderForTitle("农业转基因生物进口安全管理办法", agriculture2017.orderedTitles), 3);
  assert.equal(decisionOrderForTitle("农业转基因生物标识管理办法", agriculture2017.orderedTitles), 4);
  assert.equal(naturalResources2019.orderedTitles.length, 23);
  assert.equal(decisionOrderForTitle("矿山地质环境保护规定", naturalResources2019.orderedTitles), 17);
  assert.equal(decisionOrderForTitle("古生物化石保护条例实施办法", naturalResources2019.orderedTitles), 19);
  assert.equal(decisionOrderForTitle("优先股试点管理办法", csrc2021.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("客户交易结算资金管理办法", csrc2021.orderedTitles), 3);
  assert.equal(decisionOrderForTitle("工程咨询行业管理办法", ndrc2023.orderedTitles), 5);
  assert.equal(decisionOrderForTitle("企业投资项目核准和备案管理办法", ndrc2023.orderedTitles), 6);
  assert.equal(decisionOrderForTitle("国际通信设施建设管理规定", miit2002.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("国际通信出入口局管理办法", miit2002.orderedTitles), 2);
  assert.equal(mps2020.orderedTitles.length, 4);
  assert.equal(decisionOrderForTitle("公安机关内部执法监督工作规定", mps2020.orderedTitles), 2);
  assert.equal(decisionOrderForTitle("公安机关适用继续盘问规定", mps2020.orderedTitles), 3);
  assert.equal(aqsiqMii2002.orderedTitles.length, 2);
  assert.equal(decisionOrderForTitle("微型计算机商品修理更换退货责任规定", aqsiqMii2002.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("家用视听商品修理更换退货责任规定", aqsiqMii2002.orderedTitles), 2);
  assert.equal(decisionOrderForTitle("证券期货行政执法当事人承诺制度实施规定", csrc2025.orderedTitles), 1);
});

test("2026-08-04 official orders override polluted central-rule dates and numbers", () => {
  const metadataRegistryPath = path.resolve(testDir, "..", "..", "schema", "标准元数据补证注册表.json");
  const metadata = loadMetadataOverrides(metadataRegistryPath);
  const root = "01_立法与公开行政文件/04_规章/01_部门规章";
  const expected = [
    ["人力资源和社会保障部规章/人才市场管理规定_2019-12-31_有效_ima-3cbe6786.md", "20191231", "中华人民共和国人力资源和社会保障部令第43号", undefined],
    ["人力资源和社会保障部规章/外商投资人才中介机构管理暂行规定_2019-12-31_有效_ima-f8d232d2.md", "20191231", "中华人民共和国人力资源和社会保障部令第43号", undefined],
    ["人力资源和社会保障部规章/企业年金基金管理办法_2015-04-30_有效_ima-41f8651e.md", "20150430", "中华人民共和国人力资源和社会保障部令第24号", undefined],
    ["人力资源和社会保障部规章/企业年金基金管理机构资格认定暂行办法_2015-04-30_有效_ima-9e2b1a80.md", "20150430", "中华人民共和国人力资源和社会保障部令第24号", undefined],
    ["农业农村部规章/农业转基因生物进口安全管理办法_2017-11-30_有效_ima-0709a2d8.md", "20171130", "中华人民共和国农业部令2017年第8号", undefined, "农业部", "0000003260"],
    ["农业农村部规章/农业转基因生物标识管理办法_2017-11-30_有效_ima-290a76b4.md", "20171130", "中华人民共和国农业部令2017年第8号", undefined, "农业部", "0000003260"],
    ["农业农村部规章/农村土地承包经营纠纷仲裁规则_2010-01-01_有效_ima-b8f6dbe4.md", "20091229", "中华人民共和国农业部、国家林业局令2010年第1号", "20100101", "农业部", "0000003260"],
    ["国家林业和草原局规章/农村土地承包经营纠纷仲裁规则_2010-01-01_有效_ima-f0d466d0.md", "20091229", "中华人民共和国农业部、国家林业局令2010年第1号", "20100101", "农业部", "0000003260"],
    ["国家林业和草原局规章/农村土地承包仲裁委员会示范章程_2009-12-29_有效_ima-6b420699.md", "20091229", "中华人民共和国农业部、国家林业局令2010年第2号", undefined, "农业部", "0000003260"],
    ["自然资源部规章/矿山地质环境保护规定_2019-07-16_有效_ima-5b01383b.md", "20190724", "中华人民共和国自然资源部令第5号", undefined],
    ["自然资源部规章/古生物化石保护条例实施办法_2019-07-16_有效_ima-077c8e63.md", "20190724", "中华人民共和国自然资源部令第5号", undefined],
    ["中国证券监督管理委员会规章/首次公开发行股票注册管理办法 [source-rule-dd93be3a4784fc11]_2023-02-17_有效.md", "20230217", "中国证券监督管理委员会令第205号", "20230217"],
    ["中国证券监督管理委员会规章/北京证券交易所向不特定合格投资者公开发行股票注册管理办法 [source-rule-c9b51b7abdf93134]_2023-02-17_有效.md", "20230217", "中国证券监督管理委员会令第210号", "20230217"],
    ["中国证券监督管理委员会规章/证券期货市场监督管理措施实施办法 [source-rule-7b06b79f743fe3bb]_2025-12-31_有效.md", "20251231", "中国证券监督管理委员会令第231号", "20260630"],
    ["中国证券监督管理委员会规章/证券期货行政执法当事人承诺制度实施规定 [source-rule-817c68fe657fa674]_2025-12-31_有效.md", "20251231", "中国证券监督管理委员会令第232号", "20260201"],
    ["国家知识产权局规章/集体商标、证明商标注册和管理规定 [source-rule-062b27b7fb993d57]_2023-12-29_有效.md", "20231229", "国家知识产权局令第79号", "20240201"],
    ["国家知识产权局规章/地理标志产品保护办法 [source-rule-76abe45c1b310a86]_2023-12-29_有效.md", "20231229", "国家知识产权局令第80号", "20240201"],
    ["国家发展和改革委员会规章/工程咨询行业管理办法_2023-03-23_有效_ima-daed0888.md", "20230323", "中华人民共和国国家发展和改革委员会令第1号", "20230501"],
    ["国家发展和改革委员会规章/企业投资项目核准和备案管理办法_2023-03-23_有效_ima-2cb8631f.md", "20230323", "中华人民共和国国家发展和改革委员会令第1号", "20230501"],
    ["工业和信息化部规章/国际通信设施建设管理规定_2002-08-01_有效_ima-51e4fa12.md", "20020626", "中华人民共和国信息产业部令第22号", undefined, "信息产业部", "0000003391"],
    ["工业和信息化部规章/国际通信出入口局管理办法_2002-10-01_有效_ima-ec752fda.md", "20020626", "中华人民共和国信息产业部令第22号", undefined, "信息产业部", "0000003391"],
    ["文化和旅游部规章/文物认定管理暂行办法_2009-10-01_有效_ima-b854ba78.md", "20090810", "中华人民共和国文化部令第46号", undefined, "文化部", "0000003570"],
    ["文化和旅游部规章/乡镇综合文化站管理办法_2009-10-01_有效_ima-d7a8182b.md", "20090915", "中华人民共和国文化部令第48号", undefined, "文化部", "0000003570"],
    ["国家市场监督管理总局规章/纤维制品质量监督管理办法_2016-03-31_有效_ima-c79ae2f8.md", "20160223", "国家质量监督检验检疫总局令第178号", undefined, "国家质量监督检验检疫总局", "0000004240"],
    ["国家市场监督管理总局规章/家用视听商品修理更换退货责任规定_2002-09-01_有效_ima-92eab393.md", "20020723", "国家质量监督检验检疫总局、信息产业部令第24号", "20020901", "国家质量监督检验检疫总局", "0000004240"],
    ["国家市场监督管理总局规章/微型计算机商品修理更换退货责任规定_2002-09-01_有效_ima-e07e0164.md", "20020723", "国家质量监督检验检疫总局、信息产业部令第24号", "20020901", "国家质量监督检验检疫总局", "0000004240"],
    ["财政部规章/国家蓄滞洪区运用财政补偿资金管理规定_２００２-01-01_有效_ima-ad513303.md", "20011231", "中华人民共和国财政部令第13号", undefined],
    ["财政部规章/国有资产评估违法行为处罚办法_2002-01-01_有效_ima-0aaf9ffb.md", "20011231", "中华人民共和国财政部令第15号", undefined],
    ["国家广播电视总局规章/广播电台电视台审批管理办法_2004-09-20_有效_ima-10786942.md", "20040818", "国家广播电影电视总局令第37号", undefined, "国家广播电影电视总局", "0000004250"],
    ["国家广播电视总局规章/境外机构设立驻华广播电视办事机构管理规定_2004-08-01_有效_ima-c5129892.md", "20040618", "国家广播电影电视总局令第28号", undefined, "国家广播电影电视总局", "0000004250"],
    ["国家国防科技工业局规章/国防科学技术工业委员会行政处罚实施办法（试行）_2007-03-01_有效_ima-7bd648b6.md", "20061225", "中华人民共和国国防科学技术工业委员会令第20号", undefined, "国防科学技术工业委员会", "0000003070"],
    ["国家国防科技工业局规章/国防科学技术工业委员会听证规则_2007-03-01_有效_ima-55e5b384.md", "20061225", "中华人民共和国国防科学技术工业委员会令第21号", "20070301", "国防科学技术工业委员会", "0000003070"],
  ];

  for (const [relativePath, promulgationDate, documentNumber, effectiveDate, agencyName, agencyCode] of expected) {
    const entry = metadata.get(`${root}/${relativePath}`);
    assert.ok(entry, relativePath);
    assert.equal(entry.values.GBRQ, promulgationDate, relativePath);
    assert.equal(entry.values.FWZH, documentNumber, relativePath);
    if (effectiveDate) assert.equal(entry.values.SXRQ, effectiveDate, relativePath);
    if (agencyName) assert.equal(entry.values.ZDJGMC, agencyName, relativePath);
    if (agencyCode) assert.equal(entry.values.ZDJGDM, agencyCode, relativePath);
  }
});

test("Beijing order 259 metadata overrides expose the decision number for local rule carriers", () => {
  const metadataRegistryPath = path.resolve(testDir, "..", "..", "schema", "标准元数据补证注册表.json");
  const metadata = loadMetadataOverrides(metadataRegistryPath);
  const expected = [
    "01_立法与公开行政文件/04_规章/02_地方政府规章/北京/北京市劳动就业服务企业管理实施办法_2014-07-09_有效_ima-c397ec14.md",
    "01_立法与公开行政文件/04_规章/02_地方政府规章/北京/北京市森林资源保护管理条例实施办法_2014-07-09_有效_ima-e721d889.md",
    "01_立法与公开行政文件/04_规章/02_地方政府规章/北京/北京市住宅区及住宅安全防范设施建设和使用管理办法_2014-07-09_有效_ima-5701582d.md",
  ];
  for (const relativePath of expected) {
    const entry = metadata.get(relativePath);
    assert.ok(entry, relativePath);
    assert.equal(entry.values.GBRQ, "20140709", relativePath);
    assert.equal(entry.values.FWZH, "北京市人民政府令第259号", relativePath);
  }
});

test("Liaoning order 171 preserves the official amendment-decision order", () => {
  const decisionRegistryPath = path.resolve(
    officialRegistryRoot,
    "decision_order_evidence",
    "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(decisionRegistryPath);
  const order171 = decisions.find((item) => (
    item.agencyCode === "2100003000"
    && item.promulgationDate === "20040627"
    && item.sequenceCode === "0171"
  ));
  assert.ok(order171);
  assert.equal(decisionOrderForTitle("辽宁省城市节约用水管理实施办法", order171.orderedTitles), 1);
  assert.equal(
    decisionOrderForTitle("辽宁省占用农业灌溉水源灌排工程设施灌溉耕地管理办法", order171.orderedTitles),
    7,
  );
  assert.equal(decisionOrderForTitle("辽宁省村庄和集镇规划建设管理办法", order171.orderedTitles), 16);

  const byOrder = (date, sequence) => decisions.find((item) => (
    item.agencyCode === "2100003000"
    && item.promulgationDate === date
    && item.sequenceCode === sequence
  ));
  assert.equal(decisionOrderForTitle("辽宁省有线电视管理办法", byOrder("20111215", "0269").orderedTitles), 8);
  assert.equal(decisionOrderForTitle("辽宁省殡葬管理实施办法", byOrder("20111215", "0269").orderedTitles), 11);
  assert.equal(decisionOrderForTitle("辽宁省人民防空设施管理规定", byOrder("20131225", "0286").orderedTitles), 24);
  assert.equal(decisionOrderForTitle("辽宁省科学技术奖励办法", byOrder("20131225", "0286").orderedTitles), 28);
  assert.equal(decisionOrderForTitle("辽宁省土地调查管理办法", byOrder("20161129", "0305").orderedTitles), 3);
  assert.equal(decisionOrderForTitle("辽宁省城市房地产开发经营管理规定", byOrder("20161129", "0305").orderedTitles), 5);
  assert.equal(decisionOrderForTitle("辽宁省地质灾害防治管理办法", byOrder("20171129", "0311").orderedTitles), 4);
  assert.equal(decisionOrderForTitle("辽宁省固体废物污染环境防治办法", byOrder("20171129", "0311").orderedTitles), 13);
  assert.equal(decisionOrderForTitle("辽宁省雷电灾害防御管理规定", byOrder("20181126", "0324").orderedTitles), 1);
  assert.equal(decisionOrderForTitle("辽宁省城市市容和环境卫生管理规定", byOrder("20181126", "0324").orderedTitles), 3);
});

test("decision registry accepts exact official positions without inventing omitted titles", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "decision-position-registry-"));
  const evidencePath = path.join(directory, "evidence.md");
  fs.writeFileSync(evidencePath, "official excerpt", "utf8");
  const digest = crypto.createHash("sha256").update(fs.readFileSync(evidencePath)).digest("hex");
  const registryPath = path.join(directory, "registry.json");
  fs.writeFileSync(registryPath, JSON.stringify({
    entries: [{
      agency_code: "2100003000",
      promulgation_date: "20111215",
      sequence_code: "0269",
      ordered_titles: [
        { title: "辽宁省有线电视管理办法", order: 8 },
        { title: "辽宁省殡葬管理实施办法", order: 11 },
      ],
      official_url: "https://www.ln.gov.cn/example",
      evidence_path: "evidence.md",
      source_sha256: digest,
    }],
  }), "utf8");
  const [decision] = loadDecisionOrderEvidenceRegistry(registryPath);
  assert.equal(decisionOrderForTitle("辽宁省有线电视管理办法", decision.orderedTitles), 8);
  assert.equal(decisionOrderForTitle("辽宁省殡葬管理实施办法", decision.orderedTitles), 11);
});

test("Jinan same-day rules retain their distinct official order numbers", () => {
  const metadataRegistryPath = path.resolve(testDir, "..", "..", "schema", "标准元数据补证注册表.json");
  const metadata = loadMetadataOverrides(metadataRegistryPath);
  const expected = [
    ["01_立法与公开行政文件/04_规章/02_地方政府规章/山东/济南市消防安全宣传教育规定_2023-11-01_有效_ima-d5e98c9a.md", "济南市人民政府令第282号"],
    ["01_立法与公开行政文件/04_规章/02_地方政府规章/山东/济南市绿化条例实施细则_2023-11-01_有效_ima-4fee4853.md", "济南市人民政府令第283号"],
    ["01_立法与公开行政文件/04_规章/02_地方政府规章/山东/济南市城市绿线管理办法_2023-11-01_有效_ima-2c594ae6.md", "济南市人民政府令第284号"],
  ];
  for (const [relativePath, documentNumber] of expected) {
    const entry = metadata.get(relativePath);
    assert.ok(entry, relativePath);
    assert.equal(entry.values.GBRQ, "20230913", relativePath);
    assert.equal(entry.values.FWZH, documentNumber, relativePath);
    assert.equal(entry.values.SXRQ, "20231101", relativePath);
  }
});

test("Hebei rules using the same effective date retain distinct official order numbers", () => {
  const metadataRegistryPath = path.resolve(testDir, "..", "..", "schema", "标准元数据补证注册表.json");
  const metadata = loadMetadataOverrides(metadataRegistryPath);
  const expected = [
    [
      "01_立法与公开行政文件/04_规章/02_地方政府规章/河北/河北省政府规章制定办法_2020-02-01_有效_ima-5bf2901b.md",
      "20191215",
      "河北省人民政府令〔2019〕第10号",
    ],
    [
      "01_立法与公开行政文件/04_规章/02_地方政府规章/河北/河北省重大行政决策程序暂行办法_2020-02-01_有效_ima-63991626.md",
      "20191231",
      "河北省人民政府令〔2019〕第12号",
    ],
  ];
  for (const [relativePath, promulgationDate, documentNumber] of expected) {
    const entry = metadata.get(relativePath);
    assert.ok(entry, relativePath);
    assert.equal(entry.values.GBRQ, promulgationDate, relativePath);
    assert.equal(entry.values.SXRQ, "20200201", relativePath);
    assert.equal(entry.values.FWZH, documentNumber, relativePath);
  }
});

test("Cangzhou rules using the same effective date retain distinct official order numbers", () => {
  const metadataRegistryPath = path.resolve(testDir, "..", "..", "schema", "标准元数据补证注册表.json");
  const metadata = loadMetadataOverrides(metadataRegistryPath);
  const expected = [
    [
      "01_立法与公开行政文件/04_规章/02_地方政府规章/河北/沧州市重大行政决策程序规定_2026-02-10_有效_ima-7f5056c6.md",
      "沧州市人民政府令〔2025〕第4号",
    ],
    [
      "01_立法与公开行政文件/04_规章/02_地方政府规章/河北/沧州市人民政府拟定地方性法规草案和制定政府规章程序规定_2026-02-10_有效_ima-e8f7ff6a.md",
      "沧州市人民政府令〔2025〕第5号",
    ],
  ];
  for (const [relativePath, documentNumber] of expected) {
    const entry = metadata.get(relativePath);
    assert.ok(entry, relativePath);
    assert.equal(entry.values.GBRQ, "20251231", relativePath);
    assert.equal(entry.values.SXRQ, "20260210", relativePath);
    assert.equal(entry.values.FWZH, documentNumber, relativePath);
  }
});

test("Hebei 2018 and 2024 same-day rules retain their distinct official order numbers", () => {
  const metadataRegistryPath = path.resolve(testDir, "..", "..", "schema", "标准元数据补证注册表.json");
  const metadata = loadMetadataOverrides(metadataRegistryPath);
  const expected = [
    [
      "01_立法与公开行政文件/04_规章/02_地方政府规章/河北/河北省社会保险基金监督办法_2018-07-01_有效_ima-2b91e1c7.md",
      "20180521", "20180701", "河北省人民政府令〔2018〕第1号",
    ],
    [
      "01_立法与公开行政文件/04_规章/02_地方政府规章/河北/河北省安全生产风险管控与隐患治理规定_2018-07-01_有效_ima-27d775f5.md",
      "20180521", "20180701", "河北省人民政府令〔2018〕第2号",
    ],
    [
      "01_立法与公开行政文件/04_规章/02_地方政府规章/河北/河北省军事设施保护管理规定_2025-01-01_有效_ima-b17ee4a7.md",
      "20241116", "20250101", "河北省人民政府令〔2024〕第5号",
    ],
    [
      "01_立法与公开行政文件/04_规章/02_地方政府规章/河北/河北省排污许可管理办法_2025-01-01_有效_ima-d1c63a0f.md",
      "20241116", "20250101", "河北省人民政府令〔2024〕第6号",
    ],
  ];
  for (const [relativePath, promulgationDate, effectiveDate, documentNumber] of expected) {
    const entry = metadata.get(relativePath);
    assert.ok(entry, relativePath);
    assert.equal(entry.values.GBRQ, promulgationDate, relativePath);
    assert.equal(entry.values.SXRQ, effectiveDate, relativePath);
    assert.equal(entry.values.FWZH, documentNumber, relativePath);
  }
});

test("registered official page body overrides polluted republication date", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "official-page-metadata-"));
  const csvPath = path.join(directory, "page.csv");
  fs.writeFileSync(
    csvPath,
    [
      "relative_path,official_url,final_url,http_status,promulgation_date,document_number,effective_date,parse_status,evidence_excerpt,content_sha256,raw_relative_path,fetched_at,error",
      "a.md,https://www.gov.cn/a,https://www.gov.cn/a,200,2009-09-13,辽宁省人民政府令第237号,2009-10-15,PARSED,正文括注," + "a".repeat(64) + ",a.html,2026-08-03T00:00:00Z,",
      "b.md,https://www.gov.cn/b,https://www.gov.cn/b,200,,,,BLOCKED_NO_PROMULGATION_EVIDENCE,," + "b".repeat(64) + ",b.html,2026-08-03T00:00:00Z,",
    ].join("\n"),
    "utf8",
  );
  const registry = loadOfficialPageMetadata(csvPath);
  assert.equal(registry.size, 1);
  assert.equal(registry.byRelativePath.get("a.md").official_url, "https://www.gov.cn/a");
  assert.equal(
    officialPageEvidenceForDocument(registry, "a.md", "https://www.gov.cn/old-carrier").official_url,
    "https://www.gov.cn/a",
  );
  const row = applyOfficialPageMetadata(
    { GBRQ: "20211224", FWZH: "", SXRQ: "" },
    registry.get("https://www.gov.cn/a"),
  );
  assert.equal(row.GBRQ, "20090913");
  assert.equal(row.FWZH, "辽宁省人民政府令第237号");
  assert.equal(row.SXRQ, "20091015");
  assert.equal(row._promulgation_source, "REGISTERED_OFFICIAL_PAGE_BODY");
  assert.equal(deriveSequenceCode({ document_number: row.FWZH }, ""), "0237");
});

test("河北省人大常委会第二十五次会议公告号证据逐件锁定发布顺序码", () => {
  const auditDir = registeredPageAuditDir;
  const registry = loadOfficialPageMetadata(
    path.join(auditDir, "registered_page_metadata_v25.csv"),
  );
  const expected = new Map([
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/河北/河北省公安机关警务辅助人员管理条例_2022-01-01_有效_ff8081817cbae2b2017ccb32a2845c63.md",
      ["河北省第十三届人民代表大会常务委员会公告第96号", "2021-09-29", "2022-01-01"],
    ],
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/河北/河北省人民代表大会常务委员会关于废止河北省民办教育条例等三部法规的决定_2021-09-29_未知_ff8081817d124368017d27c24a7c1928.md",
      ["河北省第十三届人民代表大会常务委员会公告第93号", "2021-09-29", "2021-09-29"],
    ],
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/河北/河北省人民代表大会常务委员会关于修改河北省技术市场条例等十四部法规的决定_2021-09-29_未知_ff80818184cc7b200184f15ed6a5080a.md",
      ["河北省第十三届人民代表大会常务委员会公告第94号", "2021-09-29", "2021-09-29"],
    ],
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/河北/河北省实施中华人民共和国道路交通安全法办法_2021-09-29_有效_ff8081817cbadfae017ccb171a485044.md",
      ["河北省第十三届人民代表大会常务委员会公告第94号", "2021-09-29", "2021-09-29"],
    ],
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/河北/塞罕坝森林草原防火条例_2021-11-01_有效_ff8081817cbadfae017ccb346a045380.md",
      ["河北省第十三届人民代表大会常务委员会公告第97号", "2021-09-29", "2021-11-01"],
    ],
  ]);
  for (const [relativePath, [documentNumber, promulgationDate, effectiveDate]] of expected) {
    const evidence = registry.byRelativePath.get(relativePath);
    assert.ok(evidence, relativePath);
    assert.equal(evidence.document_number, documentNumber);
    assert.equal(evidence.promulgation_date, promulgationDate);
    assert.equal(evidence.effective_date, effectiveDate);
    assert.equal(
      deriveSequenceCode({ document_number: evidence.document_number }, ""),
      documentNumber.match(/第(\d+)号/u)[1].padStart(4, "0"),
    );
    const rawPath = path.resolve(auditDir, evidence.raw_relative_path);
    assert.ok(fs.existsSync(rawPath), rawPath);
    assert.equal(
      crypto.createHash("sha256").update(fs.readFileSync(rawPath)).digest("hex"),
      evidence.content_sha256,
    );
  }
});

test("上海市人大常委会2020年12月30日四件公告号逐件锁定发布顺序码", () => {
  const auditDir = registeredPageAuditDir;
  const registry = loadOfficialPageMetadata(
    path.join(auditDir, "registered_page_metadata_v26.csv"),
  );
  const expected = new Map([
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/上海/上海市知识产权保护条例_2021-03-01_有效_ff8081817a2e2abe017a31a290d60543.md",
      ["上海市人民代表大会常务委员会公告第58号", "2020-12-30", "2021-03-01"],
    ],
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/上海/上海市铁路安全管理条例_2021-03-01_有效_ff8081817a333243017a37b34e3f0583.md",
      ["上海市人民代表大会常务委员会公告第59号", "2020-12-30", "2021-03-01"],
    ],
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/上海/上海市人民代表大会常务委员会关于修改本市部分地方性法规的决定_2021-01-01_未知_ff8081817b4e92cc017b572bfc4f01b1.md",
      ["上海市人民代表大会常务委员会公告第60号", "2020-12-30", "2021-01-01"],
    ],
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/上海/上海市人民代表大会常务委员会关于废止上海市机动车道路交通事故赔偿责任若干规定的决定_2021-01-01_未知_ff8081817a9d9766017a9df7136200ad.md",
      ["上海市人民代表大会常务委员会公告第61号", "2020-12-30", "2021-01-01"],
    ],
  ]);
  for (const [relativePath, [documentNumber, promulgationDate, effectiveDate]] of expected) {
    const evidence = registry.byRelativePath.get(relativePath);
    assert.ok(evidence, relativePath);
    assert.equal(evidence.document_number, documentNumber);
    assert.equal(evidence.promulgation_date, promulgationDate);
    assert.equal(evidence.effective_date, effectiveDate);
    assert.equal(
      deriveSequenceCode({ document_number: evidence.document_number }, ""),
      documentNumber.match(/第(\d+)号/u)[1].padStart(4, "0"),
    );
    const rawPath = path.resolve(auditDir, evidence.raw_relative_path);
    assert.ok(fs.existsSync(rawPath), rawPath);
    assert.equal(
      crypto.createHash("sha256").update(fs.readFileSync(rawPath)).digest("hex"),
      evidence.content_sha256,
    );
  }
});

test("湖北省人大常委会第二十六次会议三件公告号逐件锁定发布顺序码", () => {
  const auditDir = registeredPageAuditDir;
  const registry = loadOfficialPageMetadata(
    path.join(auditDir, "registered_page_metadata_v27.csv"),
  );
  const expected = new Map([
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/湖北/湖北省节约用水条例_2022-01-01_有效_ff8081817cbadfae017cc5d21955372a.md",
      ["湖北省人民代表大会常务委员会公告第299号", "2021-09-29", "2022-01-01"],
    ],
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/湖北/湖北省人民代表大会常务委员会关于集中修改涉及长江保护法省本级地方性法规的决定_2021-09-29_未知_ff80818181a8104b0181dc45cafb1a14.md",
      ["湖北省人民代表大会常务委员会公告第300号", "2021-09-29", "2021-09-29"],
    ],
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/湖北/湖北省人民代表大会常务委员会关于废止湖北省实施〈中华人民共和国预算法〉办法的决定_2021-09-29_未知_ff8081817ceadf53017cff16caa8151c.md",
      ["湖北省人民代表大会常务委员会公告第301号", "2021-09-29", "2021-09-29"],
    ],
  ]);
  for (const [relativePath, [documentNumber, promulgationDate, effectiveDate]] of expected) {
    const evidence = registry.byRelativePath.get(relativePath);
    assert.ok(evidence, relativePath);
    assert.equal(evidence.document_number, documentNumber);
    assert.equal(evidence.promulgation_date, promulgationDate);
    assert.equal(evidence.effective_date, effectiveDate);
    assert.equal(
      deriveSequenceCode({ document_number: evidence.document_number }, ""),
      documentNumber.match(/第(\d+)号/u)[1].padStart(4, "0"),
    );
    const rawPath = path.resolve(auditDir, evidence.raw_relative_path);
    assert.ok(fs.existsSync(rawPath), rawPath);
    assert.equal(
      crypto.createHash("sha256").update(fs.readFileSync(rawPath)).digest("hex"),
      evidence.content_sha256,
    );
  }
});

test("湖北省人大常委会第十六次会议公告268和272逐件锁定发布顺序码", () => {
  const auditDir = registeredPageAuditDir;
  const registry = loadOfficialPageMetadata(
    path.join(auditDir, "registered_page_metadata_v28.csv"),
  );
  const expected = new Map([
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/湖北/湖北省就业促进条例_2020-06-03_有效_ff80808172b5fee801730f13063127e4.md",
      ["湖北省人民代表大会常务委员会公告第268号", "2020-06-03", "2020-06-03"],
    ],
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/湖北/湖北省人民代表大会常务委员会关于集中修改、废止涉及取消证明事项的部分省本级地方性法规的决定_2020-06-03_未知_ff808181818ea4040181dc321c48210c.md",
      ["湖北省人民代表大会常务委员会公告第268号", "2020-06-03", "2020-06-03"],
    ],
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/湖北/湖北省学校安全条例_2020-08-01_有效_ff80808172b5f6e301730efbbc0629f6.md",
      ["湖北省人民代表大会常务委员会公告第272号", "2020-06-03", "2020-08-01"],
    ],
  ]);
  for (const [relativePath, [documentNumber, promulgationDate, effectiveDate]] of expected) {
    const evidence = registry.byRelativePath.get(relativePath);
    assert.ok(evidence, relativePath);
    assert.equal(evidence.document_number, documentNumber);
    assert.equal(evidence.promulgation_date, promulgationDate);
    assert.equal(evidence.effective_date, effectiveDate);
    const rawPath = path.resolve(auditDir, evidence.raw_relative_path);
    assert.ok(fs.existsSync(rawPath), rawPath);
    assert.equal(
      crypto.createHash("sha256").update(fs.readFileSync(rawPath)).digest("hex"),
      evidence.content_sha256,
    );
  }
});

test("安徽省人大常委会第二十六次会议公告41和43逐件锁定发布顺序码", () => {
  const auditDir = registeredPageAuditDir;
  const registry = loadOfficialPageMetadata(
    path.join(auditDir, "registered_page_metadata_v29.csv"),
  );
  const expected = new Map([
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/安徽/安徽省大数据发展条例_2021-05-01_有效_ff80818179b2ae250179ca51dfbe0f35.md",
      ["安徽省人民代表大会常务委员会公告第四十一号", "2021-03-29", "2021-05-01", "0041"],
    ],
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/安徽/安徽省人民代表大会常务委员会关于修改和废止部分地方性法规的决定_2021-03-29_未知_ff8081817a9ec324017aa8646edd085c.md",
      ["安徽省人民代表大会常务委员会公告第四十三号", "2021-03-29", "2021-03-29", "0043"],
    ],
  ]);
  for (const [relativePath, [documentNumber, promulgationDate, effectiveDate, sequenceCode]] of expected) {
    const evidence = registry.byRelativePath.get(relativePath);
    assert.ok(evidence, relativePath);
    assert.equal(evidence.document_number, documentNumber);
    assert.equal(evidence.promulgation_date, promulgationDate);
    assert.equal(evidence.effective_date, effectiveDate);
    assert.equal(deriveSequenceCode({ document_number: documentNumber }, ""), sequenceCode);
    const rawPath = path.resolve(auditDir, evidence.raw_relative_path);
    assert.ok(fs.existsSync(rawPath), rawPath);
    assert.equal(
      crypto.createHash("sha256").update(fs.readFileSync(rawPath)).digest("hex"),
      evidence.content_sha256,
    );
  }
});

test("辽宁省人大常委会第二十三次会议四份公告逐件锁定发布顺序码", () => {
  const auditDir = registeredPageAuditDir;
  const registry = loadOfficialPageMetadata(
    path.join(auditDir, "registered_page_metadata_v31.csv"),
  );
  const expected = new Map([
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/辽宁/辽宁省电梯安全管理条例_2021-02-01_有效_ff80808176d5cbce0176d68dc13d027d.md",
      ["辽宁省人民代表大会常务委员会公告〔十三届〕第六十五号", "2020-11-25", "2021-02-01", "0065"],
    ],
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/辽宁/辽宁省人民代表大会常务委员会关于废止辽宁省商品质量监督条例等3件地方性法规的决定_2021-01-01_有效_f1ca850db63f4908a4e22b3d8372c5a6.md",
      ["辽宁省人民代表大会常务委员会公告〔十三届〕第六十三号", "2020-11-25", "2021-01-01", "0063"],
    ],
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/辽宁/辽宁省人民代表大会常务委员会关于修改辽宁省城镇房地产交易管理条例等12件地方性法规的决定_2021-01-01_未知_ff808181826bc2d001826d77360e0165.md",
      ["辽宁省人民代表大会常务委员会公告〔十三届〕第六十二号", "2020-11-25", "2021-01-01", "0062"],
    ],
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/辽宁/辽宁省铁路安全管理条例_2021-02-01_有效_ff80808176d5cbce0176d6c6ac2b0362.md",
      ["辽宁省人民代表大会常务委员会公告〔十三届〕第六十七号", "2020-11-25", "2021-02-01", "0067"],
    ],
  ]);
  for (const [relativePath, [documentNumber, promulgationDate, effectiveDate, sequenceCode]] of expected) {
    const evidence = registry.byRelativePath.get(relativePath);
    assert.ok(evidence, relativePath);
    assert.equal(evidence.document_number, documentNumber);
    assert.equal(evidence.promulgation_date, promulgationDate);
    assert.equal(evidence.effective_date, effectiveDate);
    assert.equal(deriveSequenceCode({ document_number: documentNumber }, ""), sequenceCode);
    const rawPath = path.resolve(auditDir, evidence.raw_relative_path);
    assert.ok(fs.existsSync(rawPath), rawPath);
    assert.equal(
      crypto.createHash("sha256").update(fs.readFileSync(rawPath)).digest("hex"),
      evidence.content_sha256,
    );
  }
});

test("山东省人大常委会第九次会议三份公告逐件锁定发布顺序码", () => {
  const auditDir = registeredPageAuditDir;
  const registry = loadOfficialPageMetadata(
    path.join(auditDir, "registered_page_metadata_v32.csv"),
  );
  const expected = new Map([
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/山东/山东省人民代表大会常务委员会关于修改山东省黄河河道管理条例山东省黄河防汛条例山东省电力设施和电能保护条例的决定_2024-05-30_未知_a9b7dd7fe49649ff8802eaf217fa6798.md",
      ["山东省人民代表大会常务委员会公告第45号", "2024-05-30", "2024-05-30", "0045"],
    ],
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/山东/山东省人民代表大会常务委员会关于修改山东省涉案物品价格鉴证条例的决定_2024-05-30_未知_ac25553936d54318923211b43c6e5b42.md",
      ["山东省人民代表大会常务委员会公告第46号", "2024-05-30", "2024-05-30", "0046"],
    ],
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/山东/山东省社区矫正工作条例_2024-07-01_有效_ff80818190734f1d0190c3ad10d47971.md",
      ["山东省人民代表大会常务委员会公告第43号", "2024-05-30", "2024-07-01", "0043"],
    ],
  ]);
  for (const [relativePath, [documentNumber, promulgationDate, effectiveDate, sequenceCode]] of expected) {
    const evidence = registry.byRelativePath.get(relativePath);
    assert.ok(evidence, relativePath);
    assert.equal(evidence.document_number, documentNumber);
    assert.equal(evidence.promulgation_date, promulgationDate);
    assert.equal(evidence.effective_date, effectiveDate);
    assert.equal(deriveSequenceCode({ document_number: documentNumber }, ""), sequenceCode);
    const rawPath = path.resolve(auditDir, evidence.raw_relative_path);
    assert.ok(fs.existsSync(rawPath), rawPath);
    assert.equal(
      crypto.createHash("sha256").update(fs.readFileSync(rawPath)).digest("hex"),
      evidence.content_sha256,
    );
  }
});

test("徐州市人大常委会第五十次会议两份公告逐件锁定发布顺序码", () => {
  const auditDir = registeredPageAuditDir;
  const registry = loadOfficialPageMetadata(
    path.join(auditDir, "registered_page_metadata_v33.csv"),
  );
  const expected = new Map([
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/江苏/徐州市城乡网格化服务管理条例_2022-05-01_有效_ff8081817e9b2546017efc2e3f3234d1.md",
      ["徐州市第十六届人民代表大会常务委员会公告第53号", "2022-01-20", "2022-05-01", "0053"],
    ],
    [
      "01_立法与公开行政文件/03_地方立法/01_地方性法规/江苏/徐州市人民代表大会常务委员会关于修改徐州市村集体经济组织财务管理条例等六件地方性法规的决定_2022-03-01_未知_ff8081817f48d8de017f636440e50c3b.md",
      ["徐州市第十六届人民代表大会常务委员会公告第54号", "2022-01-20", "2022-03-01", "0054"],
    ],
  ]);
  for (const [relativePath, [documentNumber, promulgationDate, effectiveDate, sequenceCode]] of expected) {
    const evidence = registry.byRelativePath.get(relativePath);
    assert.ok(evidence, relativePath);
    assert.equal(evidence.document_number, documentNumber);
    assert.equal(evidence.promulgation_date, promulgationDate);
    assert.equal(evidence.effective_date, effectiveDate);
    assert.equal(deriveSequenceCode({ document_number: documentNumber }, ""), sequenceCode);
    const rawPath = path.resolve(auditDir, evidence.raw_relative_path);
    assert.ok(fs.existsSync(rawPath), rawPath);
    assert.equal(
      crypto.createHash("sha256").update(fs.readFileSync(rawPath)).digest("hex"),
      evidence.content_sha256,
    );
  }
});

test("宽甸满族自治县两份公告逐件锁定发布顺序码", () => {
  const auditDir = registeredPageAuditDir;
  const registry = loadOfficialPageMetadata(
    path.join(auditDir, "registered_page_metadata_v34.csv"),
  );
  const expected = new Map([
    [
      "01_立法与公开行政文件/03_地方立法/02_自治条例和单行条例/辽宁/宽甸满族自治县第七届人民代表大会第四次会议关于宽甸满族自治县旅游条例_2021-09-15_未知_ff8081818214c2ea018267b23d62363f.md",
      ["宽甸满族自治县人民代表大会常务委员会公告〔七届〕第24号", "2021-08-31", "2021-09-15", "0024"],
    ],
    [
      "01_立法与公开行政文件/03_地方立法/02_自治条例和单行条例/辽宁/宽甸满族自治县风景区管理条例等三部单行条例修正案_2021-08-31_未知_ff8081817cc76d83017ccafbc53a03c9.md",
      ["宽甸满族自治县人民代表大会常务委员会公告〔七届〕第25号", "2021-08-31", "2021-08-31", "0025"],
    ],
  ]);
  for (const [relativePath, [documentNumber, promulgationDate, effectiveDate, sequenceCode]] of expected) {
    const evidence = registry.byRelativePath.get(relativePath);
    assert.ok(evidence, relativePath);
    assert.equal(evidence.document_number, documentNumber);
    assert.equal(evidence.promulgation_date, promulgationDate);
    assert.equal(evidence.effective_date, effectiveDate);
    assert.equal(deriveSequenceCode({ document_number: documentNumber }, ""), sequenceCode);
    const rawPath = path.resolve(auditDir, evidence.raw_relative_path);
    assert.ok(fs.existsSync(rawPath), rawPath);
    assert.equal(
      crypto.createHash("sha256").update(fs.readFileSync(rawPath)).digest("hex"),
      evidence.content_sha256,
    );
  }
});

test("split legal Markdown and obvious court publications are not independent laws", () => {
  const fragment = "01_立法与公开行政文件/04_规章/01_部门规章/公安部规章/公安机关办理行政案件程序规定-01-第一章-共18册_2020-08-06_有效_x.md";
  assert.deepEqual(fragmentDescriptor(fragment), {
    baseTitle: "公安机关办理行政案件程序规定",
    part: 1,
    total: 18,
  });
  assert.equal(classifySourceContent(fragment, "", ""), "legal_fragment");
  assert.equal(
    classifySourceContent(
      "01_立法与公开行政文件/04_规章/01_部门规章/a.md",
      "跨境服务贸易特别管理措施",
      [
        "# 跨境服务贸易特别管理措施",
        "",
        "> （2024年3月22日商务部令第1号公布）",
        "",
        "《跨境服务贸易特别管理措施（负面清单）》（2024年版）.pdf 《自由贸易试验区跨境服务贸易特别管理措施（负面清单）》（2024年版）.pdf",
      ].join("\n"),
    ),
    "official_attachment_index",
  );
  assert.equal(
    classifySourceContent(
      "01_立法与公开行政文件/04_规章/02_地方政府规章/湖南/_地方政府规章_20240801 [ima-markdown-64a96765].md",
      "## 第一章总则",
      "第2号《怀化市人民政府制定地方性法规草案和规章办法》已经通过。",
    ),
    "unidentified_fulltext_carrier",
  );
  assert.equal(
    classifySourceContent(
      "02_法院系统/02_法院司法规范性文件/a.md",
      "最高人民法院发布五件典型案例",
      "",
    ),
    "case",
  );
  assert.equal(
    classifySourceContent(
      "02_法院系统/02_法院司法规范性文件/a.md",
      "最高人民法院公布四起毒品犯罪典型案件",
      "以下为四起案件案情",
    ),
    "case",
  );
  for (const title of [
    "最高人民法院批准撤销、设立、变更人民法院的公告",
    "最高人民法院批准撤销、设立的人民法院",
    "最高人民法院发出通知要求依法及时处理偷税、抗税犯罪分子",
  ]) {
    assert.equal(
      classifySourceContent(
        "02_法院系统/02_法院司法规范性文件/a.md",
        title,
        "新闻式公布或摘要载体",
      ),
      "practice_reference",
      title,
    );
  }
  assert.equal(
    classifySourceContent(
      "02_法院系统/02_法院司法规范性文件/a.md",
      "最高人民法院知识产权案件年度报告（2009）（续）",
      "",
    ),
    "practice_reference",
  );
  assert.equal(
    classifySourceContent(
      "02_法院系统/02_法院司法规范性文件/a.md",
      "最高人民法院关于进一步加强和规范执行工作的若干意见",
      "正文提及一次新闻发布会",
    ),
    "legal_document",
  );
  assert.equal(
    classifySourceContent(
      "02_法院系统/02_法院司法规范性文件/a.md",
      "关于人民法院处理涉台民事案件的几个法律问题",
      "新闻发布会谈话",
    ),
    "practice_reference",
  );
  assert.equal(
    classifySourceContent(
      "01_立法与公开行政文件/03_地方立法/a.md",
      "某修改决定",
      "<noscript>Please enable JavaScript and refresh the page.</noscript> WZWS_CONFIRM_PREFIX_LABEL",
    ),
    "blocked_access_content",
  );
  assert.equal(
    targetDirectoryForSource({
      relativePath: "02_法院系统/02_法院司法规范性文件/a.md",
      objectType: "case",
      title: "最高人民法院发布五件典型案例",
    }),
    "81_最高人民法院公开案例【非规范性法源】/02_最高人民法院典型案例",
  );
  assert.equal(
    targetDirectoryForSource({
      relativePath: "02_法院系统/02_法院司法规范性文件/a.md",
      objectType: "practice_reference",
      title: "最高人民法院知识产权案件年度报告",
    }),
    "10_司法业务指导、会议纪要与公开答疑【非规范性法源】/02_审判业务指导文件",
  );
});

test("file inventory uses fast exact Markdown enumeration", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "legal-md-inventory-"));
  fs.mkdirSync(path.join(directory, "子目录"));
  fs.writeFileSync(path.join(directory, "a.md"), "a", "utf8");
  fs.writeFileSync(path.join(directory, "子目录", "b.MD"), "b", "utf8");
  fs.writeFileSync(path.join(directory, "c.txt"), "c", "utf8");
  const files = listMarkdownFilesWithRipgrep(directory);
  assert.deepEqual(
    files.map((filePath) => path.basename(filePath)).sort(),
    ["a.md", "b.MD"],
  );
});

test("standard metadata maps central agency codes and official area registry entries", () => {
  const registry = new Map([
    ["国务院", "3000"],
    ["最高人民法院", "1610"],
    ["中华人民共和国交通运输部", "3481"],
    ["中国人民银行", "3200"],
    ["国家林业和草原局(国家公园管理局)", "4060"],
    ["卫生部", "3610"],
    ["中华人民共和国国务院办公厅", "4340"],
  ]);
  const areas = [
    { code: "350000", name: "福建省", path: "福建省" },
    { code: "350100", name: "福州市", path: "福建省/福州市" },
    { code: "350102", name: "鼓楼区", path: "福建省/福州市/鼓楼区" },
    { code: "320106", name: "鼓楼区", path: "江苏省/南京市/鼓楼区" },
    { code: "230200", name: "齐齐哈尔市", path: "黑龙江省/齐齐哈尔市" },
    { code: "654000", name: "伊犁哈萨克自治州", path: "新疆维吾尔自治区/伊犁哈萨克自治州" },
  ];
  assert.equal(deriveAgencyName({ author: "最高人民法院、最高人民检察院" }), "最高人民法院");
  assert.equal(deriveAgencyCode("国务院", registry), "0000003000");
  assert.equal(deriveAgencyCode("交通运输部", registry), "0000003481");
  assert.equal(deriveAgencyCode("人民银行", registry), "0000003200");
  assert.equal(deriveAgencyCode("国家林业和草原局", registry), "0000004060");
  assert.equal(deriveAgencyCode("卫生部(已撤销)", registry), "0000003610");
  assert.equal(
    deriveAgencyCode("福州市人民政府办公室", registry, areas),
    "3501004340",
  );
  assert.equal(
    deriveAgencyCode("齐齐哈尔人民政府", registry, areas),
    "2302003000",
  );
  assert.equal(
    deriveAgencyCode(
      "新疆伊犁哈萨克自治州人民政府",
      registry,
      areas,
      "01_立法与公开行政文件/04_规章/02_地方政府规章/新疆/a.md",
    ),
    "6540003000",
  );
  assert.equal(
    deriveAgencyCode("福建省人民代表大会常务委员会", registry, areas),
    "3500001001",
  );
  assert.equal(
    deriveAgencyCode(
      "鼓楼区人民政府",
      registry,
      areas,
      "01_立法与公开行政文件/03_地方立法/福建/鼓楼区文件.md",
    ),
    "3501023000",
  );
  assert.equal(deriveAgencyCode("鼓楼区人民政府", registry, areas), "");
});

test("State Council antimonopoly coordinating bodies use the Appendix B.3 State Council code", () => {
  const registryPath = path.resolve(testDir, "..", "..", "schema", "制定机关代码注册表.csv");
  const registry = new Map(
    fs.readFileSync(registryPath, "utf8").replace(/^\uFEFF/, "").split(/\r?\n/).slice(1)
      .map((line) => line.match(/^(\d{4}),([^,]+),/))
      .filter(Boolean)
      .map((match) => [match[2].trim(), match[1]]),
  );
  assert.equal(deriveAgencyCode("国务院反垄断委员会", registry), "0000003000");
  assert.equal(deriveAgencyCode("国务院反垄断反不正当竞争委员会", registry), "0000003000");
});

test("agency name migration uses exact rule directory or unique title jurisdiction", () => {
  const areas = [
    { code: "350000", name: "福建省", path: "福建省" },
    { code: "350100", name: "福州市", path: "福建省/福州市" },
  ];
  assert.equal(
    deriveAgencyName(
      {},
      "01_立法与公开行政文件/04_规章/01_部门规章/交通运输部规章/示例办法.md",
      "",
      "1300",
      areas,
    ),
    "交通运输部",
  );
  assert.equal(
    deriveAgencyName(
      {},
      "01_立法与公开行政文件/04_规章/02_地方政府规章/福建/福州市城市管理办法.md",
      "福州市城市管理办法",
      "1400",
      areas,
    ),
    "福州市人民政府",
  );
  assert.equal(
    deriveAgencyName(
      {},
      "01_立法与公开行政文件/04_规章/02_地方政府规章/福建/城市管理办法.md",
      "城市管理办法",
      "1400",
      areas,
    ),
    "",
  );
  assert.equal(
    deriveAgencyName(
      {},
      "02_法院系统/02_法院司法规范性文件/示例.md",
      "最高人民法院关于示例事项的通知",
      "2000",
      areas,
    ),
    "最高人民法院",
  );
  assert.equal(
    deriveAgencyName(
      {},
      "03_检察院系统/02_检察规范性文件/示例.md",
      "最高人民检察院关于示例事项的通知",
      "2100",
      areas,
    ),
    "最高人民检察院",
  );
  assert.equal(
    deriveAgencyName({ 制定或修改机关名称: "黄冈市人民政府发布" }),
    "黄冈市人民政府",
  );
  assert.equal(
    deriveNationalRuleAgencyName(
      { category: "地方政府规章", publishers: ["北京市"] },
      [{ code: "110000", name: "北京市", path: "北京市" }],
      "01_立法与公开行政文件/04_规章/02_地方政府规章/北京/a.md",
    ),
    "北京市人民政府",
  );
});

test("local government rule agency needs title, declared issuer, or exact evidence", () => {
  const areas = [
    { code: "110000", name: "北京市", path: "北京市" },
    { code: "510700", name: "绵阳市", path: "四川省/绵阳市" },
  ];
  assert.equal(
    deriveAgencyName(
      {},
      "01_立法与公开行政文件/04_规章/02_地方政府规章/北京/关于划定市区河道两侧隔离带的规定.md",
      "关于划定市区河道两侧隔离带的规定",
      "1400",
      areas,
    ),
    "",
  );
  assert.equal(
    deriveAgencyName(
      { 制定机关: "绵阳市" },
      "01_立法与公开行政文件/04_规章/02_地方政府规章/四川/规定.md",
      "绵阳市人民政府拟定地方性法规草案和制定规章程序规定",
      "1400",
      areas,
    ),
    "绵阳市人民政府",
  );
});

test("local legislature agency normalizes autonomous county shorthand", () => {
  const areas = [
    {
      code: "530925",
      name: "双江拉祜族佤族布朗族傣族自治县",
      path: "云南省/临沧市/双江拉祜族佤族布朗族傣族自治县",
    },
  ];
  assert.equal(
    deriveAgencyName(
      { 制定机关: "双江拉祜族佤族布朗族傣族常委会" },
      "01_立法与公开行政文件/03_地方立法/02_自治条例和单行条例/云南/条例.md",
      "云南省双江拉祜族佤族布朗族傣族自治县古茶树保护管理条例",
      "0700",
      areas,
    ),
    "双江拉祜族佤族布朗族傣族自治县人民代表大会常务委员会",
  );
});

test("standard metadata derives sequence and file type only by Appendix A rules", () => {
  assert.equal(deriveSequenceCode({ document_number: "法释〔2021〕12号" }, ""), "0012");
  assert.equal(deriveSequenceCode({ document_number: "吉林省人民政府令286号" }, ""), "0286");
  assert.equal(deriveSequenceCode({}, "第九十一次会议通过"), "0091");
  assert.equal(deriveSequenceCode({}, "正文无令号、公告号、发文字号或会议号"), "0000");
  assert.equal(deriveFileTypeCode({ group: "修正案" }), "10");
  assert.equal(deriveFileTypeCode({ 法律类型: "修改、废止的决定" }), "30");
  assert.equal(deriveFileTypeCode({ group: "国务院关于修改部分行政法规的决定" }), "30");
  assert.equal(deriveFileTypeCode({ group: "关于废止三件地方性法规的决定" }), "30");
  assert.equal(deriveFileTypeCode({ group: "行政法规" }), "00");
});

test("decision title overrides a generic source group when deriving file type", () => {
  assert.equal(
    deriveFileTypeCode(
      { group: "地方性法规" },
      "湖南省人民代表大会常务委员会关于修改《湖南省水能资源开发利用管理条例》等九件地方性法规的决定",
    ),
    "30",
  );
  assert.equal(
    deriveFileTypeCode({ group: "地方性法规" }, "湖南省水能资源开发利用管理条例"),
    "00",
  );
});

test("decision body order reads only top-level modification items", () => {
  const body = `
国务院决定修改的行政法规

一、将《外商投资电信企业管理规定》第二条修改为……
“（一）投资者情况说明书；引用《中华人民共和国公司法》。”

二、将《医疗机构管理条例》第九条修改为……

三、删去《中华人民共和国进出口商品检验法实施条例》第三十七条。
`;
  const ordered = extractDecisionTitleOrder(body);
  assert.deepEqual(
    ordered.map(({ title, order }) => [title, order]),
    [
      ["外商投资电信企业管理规定", 1],
      ["医疗机构管理条例", 2],
      ["中华人民共和国进出口商品检验法实施条例", 3],
    ],
  );
  assert.equal(decisionOrderForTitle("医疗机构管理条例", ordered), 2);
  assert.equal(decisionOrderForTitle("中华人民共和国公司法", ordered), undefined);
});

test("decision body order accepts explicit top-level regulation title headings", () => {
  const body = `
某市人大常委会决定，对下列四部法规作出修改：

一、某市燃气管理条例
（一）将第三条修改为……

二、某市物业管理条例
（一）删去第五条。
`;
  assert.deepEqual(
    extractDecisionTitleOrder(body).map(({ title, order }) => [title, order]),
    [
      ["某市燃气管理条例", 1],
      ["某市物业管理条例", 2],
    ],
  );
});

test("decision body order accepts an explicit inline repeal list", () => {
  const body = `
某市人大常委会决定，废止《甲条例》、《乙条例》、《丙条例》。
本决定自公布之日起生效。
`;
  assert.deepEqual(
    extractDecisionTitleOrder(body).map(({ title, order }) => [title, order]),
    [
      ["甲条例", 1],
      ["乙条例", 2],
      ["丙条例", 3],
    ],
  );
});

test("decision body order reads a single modified regulation from the operative clause", () => {
  const body = `
某市人民代表大会常务委员会决定对《某市森林公园管理条例》作如下修改：

一、将第十一条第一款修改为……

本决定自公布之日起施行。
`;
  assert.deepEqual(
    extractDecisionTitleOrder(body).map(({ title, order }) => [title, order]),
    [["某市森林公园管理条例", 1]],
  );
});

test("local decision order fails closed when declared and extracted title counts differ", () => {
  const result = validatedDecisionTitleOrder(
    "某省人大常委会关于修改《甲条例》等三件地方性法规的决定",
    [
      "一、对《甲条例》作出修改",
      "二、对《乙条例》作出修改",
    ].join("\n"),
  );
  assert.equal(result.status, "DECLARED_TITLE_COUNT_MISMATCH");
  assert.equal(result.expectedCount, 3);
  assert.equal(result.extractedCount, 2);
  assert.deepEqual(result.orderedTitles, []);
});

test("local decision order accepts a complete declared title list", () => {
  const result = validatedDecisionTitleOrder(
    "某省人大常委会关于修改《甲条例》等二件地方性法规的决定",
    [
      "一、对《甲条例》作出修改",
      "二、对《乙条例》作出修改",
    ].join("\n"),
  );
  assert.equal(result.status, "VALID");
  assert.equal(result.expectedCount, 2);
  assert.equal(result.extractedCount, 2);
  assert.deepEqual(result.orderedTitles.map(({ title }) => title), ["甲条例", "乙条例"]);
});

test("single-law modification or repeal decision title is sufficient for order one", () => {
  for (const decisionTitle of [
    "某市人大常委会关于修改《甲条例》的决定",
    "某市人大常委会关于废止《甲条例》的决定",
  ]) {
    const result = validatedDecisionTitleOrder(decisionTitle, "本决定自公布之日起施行。");
    assert.equal(result.status, "VALID");
    assert.equal(result.extractedCount, 1);
    assert.deepEqual(result.orderedTitles.map(({ title, order }) => [title, order]), [["甲条例", 1]]);
  }
});

test("decision body order accepts parenthesized target-law headings", () => {
  const result = validatedDecisionTitleOrder(
    "某省人大常委会关于废止和修改部分地方性法规的决定",
    [
      "决定，废止下列2件地方性法规，修改下列2件地方性法规：",
      "一、废止下列2件地方性法规",
      "（一）《甲条例》（2001年通过）",
      "（二）《乙条例》（2002年通过）",
      "二、修改下列2件地方性法规",
      "（一）将《丙条例》第一条修改为……",
      "（二）对《丁条例》作出修改。",
    ].join("\n"),
  );
  assert.equal(result.status, "VALID");
  assert.equal(result.expectedCount, 4);
  assert.deepEqual(result.orderedTitles.map(({ title }) => title), ["甲条例", "乙条例", "丙条例", "丁条例"]);
});

test("decision body order accepts bare and 关于 target-law headings after an explicit preamble", () => {
  const result = validatedDecisionTitleOrder(
    "某市人大常委会关于修改部分地方性法规的决定",
    [
      "决定，对下列三项地方性法规作如下修改：",
      "一、《甲条例》",
      "（一）将第一条修改为……",
      "关于《乙条例》",
      "二、将第二条修改为……",
      "关于《丙条例》",
      "三、删去第三条。",
    ].join("\n"),
  );
  assert.equal(result.status, "VALID");
  assert.equal(result.expectedCount, 3);
  assert.deepEqual(result.orderedTitles.map(({ title }) => title), ["甲条例", "乙条例", "丙条例"]);
});

test("decision body order accepts titled Markdown headings after a counted decision preamble", () => {
  const result = validatedDecisionTitleOrder(
    "某省人大常委会关于修改《甲条例》等四件地方性法规的决定",
    [
      "某省人大常委会决定对《甲条例》等四件地方性法规作如下修改：",
      "## 一、甲条例",
      "（一）将第一条修改为……",
      "## 二、乙条例",
      "（一）将第二条修改为……",
      "## 三、丙条例",
      "（一）将第三条修改为……",
      "## 四、丁条例",
      "（一）将第四条修改为……",
    ].join("\n"),
  );
  assert.equal(result.status, "VALID");
  assert.deepEqual(result.orderedTitles.map(({ title }) => title), ["甲条例", "乙条例", "丙条例", "丁条例"]);
});

test("decision body order accepts a complete quoted target list in the operative preamble", () => {
  const result = validatedDecisionTitleOrder(
    "某省人大常委会关于修改《甲条例》等四件地方性法规的决定",
    "某省人大常委会决定，对《甲条例》、《乙条例》、《丙条例》、《丁条例》作如下修改：",
  );
  assert.equal(result.status, "VALID");
  assert.deepEqual(result.orderedTitles.map(({ title }) => title), ["甲条例", "乙条例", "丙条例", "丁条例"]);
});

test("decision body order accepts numbered repeal headings", () => {
  const result = validatedDecisionTitleOrder(
    "某省人大常委会关于废止《甲条例》等四部地方性法规的决定",
    [
      "决定，废止下列地方性法规：",
      "一、《甲条例》（2001年通过）",
      "二、《乙条例》（2002年通过）",
      "三、《丙条例》（2003年通过）",
      "四、《丁条例》（2004年通过）",
    ].join("\n"),
  );
  assert.equal(result.status, "VALID");
  assert.deepEqual(result.orderedTitles.map(({ title }) => title), ["甲条例", "乙条例", "丙条例", "丁条例"]);
});

test("mixed modification and repeal counts use the complete body total", () => {
  const result = validatedDecisionTitleOrder(
    "某市人大常委会关于修改《甲条例》等四件法规和废止《戊条例》的决定",
    [
      "决定，修改下列4件法规，废止下列1件法规：",
      "一、对《甲条例》作出修改",
      "二、对《乙条例》作出修改",
      "三、对《丙条例》作出修改",
      "四、对《丁条例》作出修改",
      "五、废止《戊条例》。",
    ].join("\n"),
  );
  assert.equal(result.status, "VALID");
  assert.equal(result.expectedCount, 5);
  assert.equal(result.extractedCount, 5);
});

test("decision body order accepts indented headings from official PDF text", () => {
  const body = "  一、将《甲办法》第一条修改为……\n  二、将《乙规定》第二条修改为……";
  assert.deepEqual(
    extractDecisionTitleOrder(body).map(({ title, order }) => ({ title, order })),
    [
      { title: "甲办法", order: 1 },
      { title: "乙规定", order: 2 },
    ],
  );
});

test("decision body order accepts top-level additions written as 在《规章》后增加", () => {
  const ordered = extractDecisionTitleOrder([
    "一、将《甲办法》第一条修改为：……",
    "二、在《乙办法》第二十六条后增加一条，作为第二十七条：……",
  ].join("\n"));
  assert.deepEqual(ordered.map(({ title, order }) => ({ title, order })), [
    { title: "甲办法", order: 1 },
    { title: "乙办法", order: 2 },
  ]);
});

test("official decision-order registry requires a hash-verified evidence file", () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "decision-order-"));
  const evidencePath = path.join(tempDir, "decision.pdf");
  fs.writeFileSync(evidencePath, "official decision bytes");
  const sourceSha256 = crypto.createHash("sha256").update("official decision bytes").digest("hex");
  const registryPath = path.join(tempDir, "registry.json");
  fs.writeFileSync(registryPath, JSON.stringify({ entries: [{
    agency_code: "0000004970",
    promulgation_date: "20200320",
    sequence_code: "0166",
    ordered_titles: ["甲办法", "乙规定"],
    official_url: "https://example.gov.cn/decision.pdf",
    evidence_path: "decision.pdf",
    source_sha256: sourceSha256,
  }] }));
  const [decision] = loadDecisionOrderEvidenceRegistry(registryPath);
  assert.equal(decision.orderedTitles[1].order, 2);
  assert.equal(decision.sourceSha256, sourceSha256);
});

test("Liaoning order 341 preserves the official 41-item modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot,
    "decision_order_evidence",
    "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "2100003000"
    && entry.promulgationDate === "20210518"
    && entry.sequenceCode === "0341"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 41);
  assert.equal(decisionOrderForTitle("辽宁省人工影响天气管理办法", decision.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("辽宁省草原管理实施办法", decision.orderedTitles), 20);
  assert.equal(decisionOrderForTitle("辽宁省测绘市场管理办法", decision.orderedTitles), 41);
});

test("Liaoning order 247 preserves the official 89-item modification and repeal order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "2100003000"
    && entry.promulgationDate === "20110113"
    && entry.sequenceCode === "0247"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 89);
  assert.equal(decisionOrderForTitle("辽宁省罚款决定与罚款收缴分离实施细则", decision.orderedTitles), 7);
  assert.equal(decisionOrderForTitle("辽宁省文物勘探管理办法", decision.orderedTitles), 37);
  assert.equal(decisionOrderForTitle("辽宁省按比例分散安置残疾人就业规定", decision.orderedTitles), 45);
  assert.equal(decisionOrderForTitle("辽宁省公共场所治安管理办法", decision.orderedTitles), 60);
  assert.equal(decisionOrderForTitle("辽宁省劳动保护规定", decision.orderedTitles), 89);
});

test("legacy carrier page dates yield to a hash-verified decision matching its filename event", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const coding = decisionCodingForLegacyCarrier({
    title: "辽宁省按比例分散安置残疾人就业规定",
    agencyCode: "2100003000",
    carrierPromulgationDate: "20211224",
    legacyPromulgationDate: "20110113",
    sequenceCode: "0000",
    categoryCode: "1400",
  }, decisions);
  assert.ok(coding);
  assert.equal(coding.promulgationDate, "20110113");
  assert.equal(coding.sequenceCode, "0247");
  assert.equal(coding.officialDecisionOrder, 45);
});

test("legacy carrier dates do not change without an exact registered decision event", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  assert.equal(decisionCodingForLegacyCarrier({
    title: "辽宁省保障性安居工程建设和管理办法",
    agencyCode: "2100003000",
    carrierPromulgationDate: "20211224",
    legacyPromulgationDate: "20130301",
    sequenceCode: "0000",
    categoryCode: "1400",
  }, decisions), null);
});

test("Hunan order 251 preserves the official 55-item repeal and modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "4300003000"
    && entry.promulgationDate === "20110130"
    && entry.sequenceCode === "0251"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 55);
  assert.equal(decisionOrderForTitle("湖南省洞庭湖蓄洪区安全与建设管理办法", decision.orderedTitles), 33);
  assert.equal(decisionOrderForTitle("湖南省实施电力设施保护条例办法", decision.orderedTitles), 37);
  assert.equal(decisionOrderForTitle("湖南省公众聚集场所消防安全管理办法", decision.orderedTitles), 42);
  assert.equal(decisionOrderForTitle("湖南省国有林场管理办法", decision.orderedTitles), 46);
  assert.equal(decisionOrderForTitle(
    "湖南省禁止非医学需要鉴定胎儿性别和选择性别终止妊娠规定",
    decision.orderedTitles,
  ), 50);
  assert.equal(decisionOrderForTitle("湖南省开发区管理办法", decision.orderedTitles), 51);
  assert.equal(decisionOrderForTitle("湖南省实施〈殡葬管理条例〉办法", decision.orderedTitles), 55);
  const localGroupTitles = [
    "湖南省测量标志保护办法",
    "湖南省洞庭湖蓄洪区安全与建设管理办法",
    "湖南省公众聚集场所消防安全管理办法",
    "湖南省国有林场管理办法",
    "湖南省禁止非医学需要鉴定胎儿性别和选择性别终止妊娠规定",
    "湖南省开发区管理办法",
    "湖南省实施电力设施保护条例办法",
    "湖南省水利水电工程管理办法",
    "湖南省土地市场管理办法",
    "湖南省制止牟取暴利办法",
  ];
  const assignments = assignInternalSequenceGroup(localGroupTitles.map((title) => ({
    title,
    officialDecisionOrder: decisionOrderForTitle(title, decision.orderedTitles),
  })));
  assert.equal(assignments.length, 10);
  assert.ok(assignments.every((assignment) => assignment.source === "SOURCE_DECISION_BODY_ORDER"));
  assert.deepEqual(
    assignments.map((assignment) => assignment.internalSequence),
    ["033", "034", "036", "037", "039", "042", "046", "050", "051", "052"],
  );
});

test("Anhui order 230 preserves the official 39-regulation modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "3400003000"
    && entry.promulgationDate === "20101223"
    && entry.sequenceCode === "0230"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 39);
  assert.equal(decisionOrderForTitle("安徽省推广使用车用乙醇汽油管理暂行办法", decision.orderedTitles), 7);
  assert.equal(decisionOrderForTitle("安徽省民用爆炸物品安全管理办法", decision.orderedTitles), 8);
  assert.equal(decisionOrderForTitle("安徽省林业基金管理办法", decision.orderedTitles), 14);
  assert.equal(decisionOrderForTitle("安徽省食盐加碘消除碘缺乏危害管理实施办法", decision.orderedTitles), 22);
  assert.equal(decisionOrderForTitle("安徽省地名管理办法", decision.orderedTitles), 23);
  assert.equal(decisionOrderForTitle("安徽省驷马山灌区管理暂行办法", decision.orderedTitles), 24);
  assert.equal(decisionOrderForTitle("安徽省城市房屋租赁管理办法", decision.orderedTitles), 39);
});

test("targeted Anhui legacy carriers use the exact official decision event and position", () => {
  const testDir = path.dirname(fileURLToPath(import.meta.url));
  const decisionRegistryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(decisionRegistryPath);
  const expectedDecisions = new Map([
    [
      "20040810|0175",
      new Map([
        ["安徽省饮用天然矿泉水资源管理办法", 20],
        ["安徽省地质灾害防治管理办法", 30],
        ["安徽省公共安全技术防范管理规定", 36],
      ]),
    ],
    [
      "20141216|0258",
      new Map([
        ["安徽省体育设施管理办法", 3],
        ["安徽省查处非法生产卷烟规定", 5],
        ["安徽省城市污水处理费管理暂行办法", 8],
        ["安徽省实施《军人抚恤优待条例》办法", 11],
      ]),
    ],
  ]);
  for (const [event, titles] of expectedDecisions) {
    const [promulgationDate, sequenceCode] = event.split("|");
    const decision = decisions.find((entry) => (
      entry.agencyCode === "3400003000"
      && entry.promulgationDate === promulgationDate
      && entry.sequenceCode === sequenceCode
    ));
    assert.ok(decision, `missing Anhui decision ${event}`);
    for (const [title, order] of titles) {
      assert.equal(decisionOrderForTitle(title, decision.orderedTitles), order);
    }
  }

  const metadataRegistryPath = path.resolve(
    testDir, "..", "..", "schema", "标准元数据补证注册表.json",
  );
  const metadata = loadMetadataOverrides(metadataRegistryPath);
  const expectedMetadata = new Map([
    ["安徽省公共安全技术防范管理规定_2004-08-10_有效_ima-4fb34b0d.md", ["20040810", "安徽省人民政府令第175号"]],
    ["安徽省饮用天然矿泉水资源管理办法_2004-08-10_有效_ima-3bf4df19.md", ["20040810", "安徽省人民政府令第175号"]],
    ["安徽省鼓励台湾同胞投资的规定_2010-12-23_有效_ima-5d23ebac.md", ["20101223", "安徽省人民政府令第230号"]],
    ["安徽省森林和野生动物类型自然保护区管理办法_2010-12-23_有效_ima-6423aa03.md", ["20101223", "安徽省人民政府令第230号"]],
    ["安徽省体育设施管理办法_2014-12-16_有效_ima-b3888d44.md", ["20141216", "安徽省人民政府令第258号"]],
    ["安徽省查处非法生产卷烟规定_2014-12-16_有效_ima-01d02bc3.md", ["20141216", "安徽省人民政府令第258号"]],
    ["安徽省城市污水处理费管理暂行办法_2014-12-16_有效_ima-633f64ef.md", ["20141216", "安徽省人民政府令第258号"]],
    ["安徽省实施军人抚恤优待条例办法_2014-12-16_有效_ima-c5eee6b1.md", ["20141216", "安徽省人民政府令第258号"]],
  ]);
  for (const [fileName, [promulgationDate, documentNumber]] of expectedMetadata) {
    const [relativePath, values] = [...metadata.entries()].find(([candidate]) => candidate.endsWith(fileName)) ?? [];
    assert.ok(relativePath, `missing metadata override ${fileName}`);
    assert.equal(values.values.GBRQ, promulgationDate);
    assert.equal(values.values.FWZH, documentNumber);
  }
});

test("Hefei order 206 preserves exact decision positions and effective date", () => {
  const testDir = path.dirname(fileURLToPath(import.meta.url));
  const decisionRegistryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(decisionRegistryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "3401003000"
    && entry.promulgationDate === "20191231"
    && entry.sequenceCode === "0206"
  ));
  assert.ok(decision);
  assert.equal(decisionOrderForTitle("合肥市户外广告和招牌设置管理办法", decision.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("合肥市机动车排气污染防治办法", decision.orderedTitles), 3);

  const metadata = loadMetadataOverrides(path.resolve(
    testDir, "..", "..", "schema", "标准元数据补证注册表.json",
  ));
  for (const fileName of [
    "合肥市户外广告和招牌设置管理办法_2019-12-31_有效_ima-47c24b6c.md",
    "合肥市机动车排气污染防治办法_2019-12-31_有效_ima-968c8fad.md",
  ]) {
    const [, entry] = [...metadata.entries()].find(([candidate]) => candidate.endsWith(fileName)) ?? [];
    assert.ok(entry, `missing metadata override ${fileName}`);
    assert.equal(entry.values.GBRQ, "20191231");
    assert.equal(entry.values.FWZH, "合肥市人民政府令第206号");
    assert.equal(entry.values.SXRQ, "20200301");
  }
});

test("Anhui order 307 and standalone orders 309/310 preserve their distinct promulgation events", () => {
  const testDir = path.dirname(fileURLToPath(import.meta.url));
  const decisionRegistryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(decisionRegistryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "3400003000"
    && entry.promulgationDate === "20220113"
    && entry.sequenceCode === "0307"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 4);
  assert.equal(decisionOrderForTitle("安徽省城市房地产开发经营管理办法", decision.orderedTitles), 1);
  assert.equal(decisionOrderForTitle(
    "安徽省实施〈中华人民共和国河道管理条例〉办法",
    decision.orderedTitles,
  ), 2);
  assert.equal(decisionOrderForTitle("安徽省最低工资规定", decision.orderedTitles), 3);
  assert.equal(decisionOrderForTitle("安徽省税收保障办法", decision.orderedTitles), 4);

  const metadataRegistryPath = path.resolve(
    testDir, "..", "..", "schema", "标准元数据补证注册表.json",
  );
  const metadata = loadMetadataOverrides(metadataRegistryPath);
  const expected = new Map([
    [
      "01_立法与公开行政文件/04_规章/02_地方政府规章/安徽/安徽省城市房地产开发经营管理办法_2021-12-29_有效_ima-ed8cc3f9.md",
      ["20220113", "安徽省人民政府令第307号"],
    ],
    [
      "01_立法与公开行政文件/04_规章/02_地方政府规章/安徽/安徽省实施中华人民共和国河道管理条例办法_2021-12-29_有效_ima-dbb294af.md",
      ["20220113", "安徽省人民政府令第307号"],
    ],
    [
      "01_立法与公开行政文件/04_规章/02_地方政府规章/安徽/安徽省最低工资规定_2021-12-29_有效_ima-88d2fb59.md",
      ["20220113", "安徽省人民政府令第307号"],
    ],
    [
      "01_立法与公开行政文件/04_规章/02_地方政府规章/安徽/安徽省药品和医疗器械使用监督管理办法_2022-03-01_有效_ima-7258738e.md",
      ["20220116", "安徽省人民政府令第309号"],
    ],
    [
      "01_立法与公开行政文件/04_规章/02_地方政府规章/安徽/安徽省建设工程勘察设计管理办法_2022-03-01_有效_ima-d9588193.md",
      ["20220122", "安徽省人民政府令第310号"],
    ],
  ]);
  for (const [relativePath, [date, documentNumber]] of expected) {
    const row = applyMetadataOverride({ GBRQ: "20211229", FWZH: "" }, metadata.get(relativePath));
    assert.equal(row.GBRQ, date);
    assert.equal(row.FWZH, documentNumber);
    assert.equal(row._promulgation_source, "OFFICIAL_PROMULGATION_ORDER");
  }
});

test("Tianjin order 29 preserves the official 16-item modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "1200003000"
    && entry.promulgationDate === "20180109"
    && entry.sequenceCode === "0029"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 16);
  assert.equal(decisionOrderForTitle("天津市设定与实施行政许可规定", decision.orderedTitles), 3);
  assert.equal(decisionOrderForTitle("天津市殡葬管理条例实施办法", decision.orderedTitles), 6);
  assert.equal(decisionOrderForTitle("天津市行业协会管理办法", decision.orderedTitles), 7);
  assert.equal(decisionOrderForTitle("天津市发展散装水泥管理办法", decision.orderedTitles), 8);
  assert.equal(decisionOrderForTitle("天津市危险化学品安全管理办法", decision.orderedTitles), 12);
  const localGroupTitles = [
    "天津市殡葬管理条例实施办法",
    "天津市发展散装水泥管理办法",
    "天津市设定与实施行政许可规定",
    "天津市危险化学品安全管理办法",
    "天津市行业协会管理办法",
  ];
  const assignments = assignInternalSequenceGroup(localGroupTitles.map((title) => ({
    title,
    officialDecisionOrder: decisionOrderForTitle(title, decision.orderedTitles),
  })));
  assert.deepEqual(
    assignments.map((assignment) => assignment.internalSequence),
    ["003", "006", "007", "008", "012"],
  );
  assert.ok(assignments.every((assignment) => assignment.source === "SOURCE_DECISION_BODY_ORDER"));
});

test("Ningxia order 133 preserves the official six-item modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "6400003000"
    && entry.promulgationDate === "20241114"
    && entry.sequenceCode === "0133"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 6);
  assert.equal(decisionOrderForTitle(
    "宁夏回族自治区取水许可和水资源费征收管理实施办法",
    decision.orderedTitles,
  ), 1);
  assert.equal(decisionOrderForTitle("宁夏回族自治区节水型社会建设管理办法", decision.orderedTitles), 2);
  assert.equal(decisionOrderForTitle("宁夏回族自治区职工生育保险办法", decision.orderedTitles), 4);
  assert.equal(decisionOrderForTitle("宁夏回族自治区殡葬管理办法", decision.orderedTitles), 5);
  assert.equal(decisionOrderForTitle(
    "宁夏回族自治区气象灾害预警信号发布与传播办法",
    decision.orderedTitles,
  ), 6);
  const localGroupTitles = [
    "宁夏回族自治区殡葬管理办法",
    "宁夏回族自治区节水型社会建设管理办法",
    "宁夏回族自治区气象灾害预警信号发布与传播办法",
    "宁夏回族自治区取水许可和水资源费征收管理实施办法",
    "宁夏回族自治区职工生育保险办法",
  ];
  const assignments = assignInternalSequenceGroup(localGroupTitles.map((title) => ({
    title,
    officialDecisionOrder: decisionOrderForTitle(title, decision.orderedTitles),
  })));
  assert.deepEqual(
    assignments.map((assignment) => assignment.internalSequence),
    ["001", "002", "004", "005", "006"],
  );
  assert.ok(assignments.every((assignment) => assignment.source === "SOURCE_DECISION_BODY_ORDER"));
});

test("2019 antimonopoly guide notification preserves the official four-item order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "0000003000"
    && entry.promulgationDate === "20190104"
    && entry.sequenceCode === "0002"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 4);
  assert.equal(decisionOrderForTitle(
    "国务院反垄断委员会关于汽车业的反垄断指南",
    decision.orderedTitles,
  ), 1);
  assert.equal(decisionOrderForTitle(
    "国务院反垄断委员会关于知识产权领域的反垄断指南",
    decision.orderedTitles,
  ), 2);
  assert.equal(decisionOrderForTitle(
    "国务院反垄断委员会横向垄断协议案件宽大制度适用指南",
    decision.orderedTitles,
  ), 3);
  assert.equal(decisionOrderForTitle(
    "国务院反垄断委员会垄断案件经营者承诺指南",
    decision.orderedTitles,
  ), 4);
});

test("Ningxia order 28 metadata uses the promulgation order while unresolved item order stays blocked", () => {
  const metadata = loadMetadataOverrides(path.resolve(
    testDir, "..", "..", "schema", "标准元数据补证注册表.json",
  ));
  const paths = [
    "01_立法与公开行政文件/04_规章/02_地方政府规章/宁夏/宁夏回族自治区地方预算执行情况审计监督办法_2010-11-04_有效_ima-74a1eaed.md",
    "01_立法与公开行政文件/04_规章/02_地方政府规章/宁夏/宁夏回族自治区地震灾情上报规定_2010-11-04_有效_ima-835b5fa9.md",
    "01_立法与公开行政文件/04_规章/02_地方政府规章/宁夏/宁夏回族自治区国有企业档案工作规定_2010-11-04_有效_ima-0cabe67a.md",
    "01_立法与公开行政文件/04_规章/02_地方政府规章/宁夏/宁夏回族自治区科学技术保密细则_2010-11-04_有效_ima-a9f6eac0.md",
    "01_立法与公开行政文件/04_规章/02_地方政府规章/宁夏/宁夏回族自治区民兵预备役部队训练基地（中心）管理规定_2010-11-04_有效_ima-9d81e240.md",
  ];
  for (const relativePath of paths) {
    const override = metadata.get(relativePath);
    assert.ok(override, `missing Ningxia order 28 override: ${relativePath}`);
    const row = applyMetadataOverride({ GBRQ: "", FWZH: "" }, override);
    assert.equal(row.GBRQ, "20101104");
    assert.equal(row.FWZH, "宁夏回族自治区人民政府令第28号");
  }
  const repealed = applyMetadataOverride(
    { SXX: "01", SHXRQ: "" },
    metadata.get(paths[0]),
  );
  assert.equal(repealed.SXX, "04");
  assert.equal(repealed.SHXRQ, "20251111");
});

test("Ningxia order 92 preserves the official 24-item modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "6400003000"
    && entry.promulgationDate === "20171009"
    && entry.sequenceCode === "0092"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 24);
  assert.equal(decisionOrderForTitle("宁夏回族自治区旅游船舶安全管理办法", decision.orderedTitles), 5);
  assert.equal(decisionOrderForTitle("宁夏回族自治区失业保险办法", decision.orderedTitles), 7);
  assert.equal(decisionOrderForTitle("宁夏回族自治区自然保护区管理办法", decision.orderedTitles), 8);
  assert.equal(decisionOrderForTitle("宁夏回族自治区人工影响天气管理办法", decision.orderedTitles), 11);
  assert.equal(decisionOrderForTitle("宁夏回族自治区水上交通安全管理办法", decision.orderedTitles), 12);
  assert.equal(decisionOrderForTitle("宁夏回族自治区政府投资项目审计办法", decision.orderedTitles), 15);
  assert.equal(decisionOrderForTitle("宁夏回族自治区行政事业性收费收缴分离规定", decision.orderedTitles), 18);
  const localGroupTitles = [
    "宁夏回族自治区旅游船舶安全管理办法",
    "宁夏回族自治区人工影响天气管理办法",
    "宁夏回族自治区失业保险办法",
    "宁夏回族自治区水上交通安全管理办法",
    "宁夏回族自治区行政事业性收费收缴分离规定",
    "宁夏回族自治区政府投资项目审计办法",
    "宁夏回族自治区自然保护区管理办法",
  ];
  const assignments = assignInternalSequenceGroup(localGroupTitles.map((title) => ({
    title,
    officialDecisionOrder: decisionOrderForTitle(title, decision.orderedTitles),
  })));
  assert.deepEqual(
    assignments.map((assignment) => assignment.internalSequence),
    ["005", "007", "008", "011", "012", "015", "018"],
  );
  assert.ok(assignments.every((assignment) => assignment.source === "SOURCE_DECISION_BODY_ORDER"));
});

test("Ningxia order 108 preserves the official 14-item modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "6400003000"
    && entry.promulgationDate === "20191204"
    && entry.sequenceCode === "0108"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 14);
  assert.equal(decisionOrderForTitle("宁夏回族自治区自然灾害救助办法", decision.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("宁夏回族自治区林业有害生物防治办法", decision.orderedTitles), 7);
  assert.equal(decisionOrderForTitle("宁夏回族自治区招标投标管理办法", decision.orderedTitles), 8);
  assert.equal(decisionOrderForTitle("宁夏回族自治区献血管理办法", decision.orderedTitles), 9);
  const localGroupTitles = [
    "宁夏回族自治区林业有害生物防治办法",
    "宁夏回族自治区献血管理办法",
    "宁夏回族自治区招标投标管理办法",
    "宁夏回族自治区自然灾害救助办法",
  ];
  const assignments = assignInternalSequenceGroup(localGroupTitles.map((title) => ({
    title,
    officialDecisionOrder: decisionOrderForTitle(title, decision.orderedTitles),
  })));
  assert.deepEqual(
    assignments.map((assignment) => assignment.internalSequence),
    ["001", "007", "008", "009"],
  );
  assert.ok(assignments.every((assignment) => assignment.source === "SOURCE_DECISION_BODY_ORDER"));
});

test("Guangxi order 128 preserves the official 15-item modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "4500003000"
    && entry.promulgationDate === "20180809"
    && entry.sequenceCode === "0128"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 15);
  assert.equal(decisionOrderForTitle("广西壮族自治区防御雷电灾害管理办法", decision.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("广西壮族自治区气候资源开发利用和保护管理办法", decision.orderedTitles), 2);
  assert.equal(decisionOrderForTitle("广西壮族自治区水产苗种管理办法", decision.orderedTitles), 8);
  assert.equal(decisionOrderForTitle("广西壮族自治区公共机构节能管理办法", decision.orderedTitles), 9);
  assert.equal(decisionOrderForTitle("广西壮族自治区果树种苗管理办法", decision.orderedTitles), 14);
  const localGroupTitles = [
    "广西壮族自治区防御雷电灾害管理办法",
    "广西壮族自治区公共机构节能管理办法",
    "广西壮族自治区果树种苗管理办法",
    "广西壮族自治区气候资源开发利用和保护管理办法",
    "广西壮族自治区水产苗种管理办法",
  ];
  const assignments = assignInternalSequenceGroup(localGroupTitles.map((title) => ({
    title,
    officialDecisionOrder: decisionOrderForTitle(title, decision.orderedTitles),
  })));
  assert.deepEqual(
    assignments.map((assignment) => assignment.internalSequence),
    ["001", "002", "008", "009", "014"],
  );
  assert.ok(assignments.every((assignment) => assignment.source === "SOURCE_DECISION_BODY_ORDER"));
});

test("Liaoning order 333 preserves the official six-item modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "2100003000"
    && entry.promulgationDate === "20201017"
    && entry.sequenceCode === "0333"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 6);
  assert.equal(decisionOrderForTitle("辽宁省实有人口服务管理办法", decision.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("辽宁省建设工程造价管理办法", decision.orderedTitles), 2);
  assert.equal(decisionOrderForTitle("辽宁省病媒生物预防控制管理办法", decision.orderedTitles), 4);
  assert.equal(decisionOrderForTitle("辽宁省公共消防设施管理办法", decision.orderedTitles), 6);
  const localGroupTitles = [
    "辽宁省病媒生物预防控制管理办法",
    "辽宁省公共消防设施管理办法",
    "辽宁省建设工程造价管理办法",
    "辽宁省实有人口服务管理办法",
  ];
  const assignments = assignInternalSequenceGroup(localGroupTitles.map((title) => ({
    title,
    officialDecisionOrder: decisionOrderForTitle(title, decision.orderedTitles),
  })));
  assert.deepEqual(
    assignments.map((assignment) => assignment.internalSequence),
    ["001", "002", "004", "006"],
  );
  assert.ok(assignments.every((assignment) => assignment.source === "SOURCE_DECISION_BODY_ORDER"));
});

test("Liaoning order 308 preserves the official eight-item modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "2100003000"
    && entry.promulgationDate === "20170816"
    && entry.sequenceCode === "0308"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 8);
  assert.equal(decisionOrderForTitle("辽宁省实验动物管理办法", decision.orderedTitles), 2);
  assert.equal(decisionOrderForTitle("辽宁省取水许可和水资源费征收管理实施办法", decision.orderedTitles), 4);
  assert.equal(decisionOrderForTitle("辽宁省城镇企业职工生育保险规定", decision.orderedTitles), 6);
  assert.equal(decisionOrderForTitle("辽宁省农村居民最低生活保障办法", decision.orderedTitles), 8);
  const localGroupTitles = [
    "辽宁省城镇企业职工生育保险规定",
    "辽宁省农村居民最低生活保障办法",
    "辽宁省取水许可和水资源费征收管理实施办法",
    "辽宁省实验动物管理办法",
  ];
  const assignments = assignInternalSequenceGroup(localGroupTitles.map((title) => ({
    title,
    officialDecisionOrder: decisionOrderForTitle(title, decision.orderedTitles),
  })));
  assert.deepEqual(
    assignments.map((assignment) => assignment.internalSequence),
    ["002", "004", "006", "008"],
  );
  assert.ok(assignments.every((assignment) => assignment.source === "SOURCE_DECISION_BODY_ORDER"));
});

test("Liaoning order 331 preserves one repeal followed by five modifications", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "2100003000"
    && entry.promulgationDate === "20191127"
    && entry.sequenceCode === "0331"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 6);
  assert.equal(decisionOrderForTitle("辽宁省气象灾害防御实施办法", decision.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("辽宁省海洋环境保护办法", decision.orderedTitles), 3);
  assert.equal(decisionOrderForTitle("辽宁省新型墙体材料开发应用管理规定", decision.orderedTitles), 5);
  assert.equal(decisionOrderForTitle("辽宁省住房公积金管理规定", decision.orderedTitles), 6);
});

test("Shanghai order 30 preserves the official 19-item modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "3100003000"
    && entry.promulgationDate === "20150522"
    && entry.sequenceCode === "0030"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 19);
  assert.equal(decisionOrderForTitle("上海港口客运站管理办法", decision.orderedTitles), 8);
  assert.equal(decisionOrderForTitle("上海市农村公路管理办法", decision.orderedTitles), 9);
  assert.equal(decisionOrderForTitle("上海市防空警报管理办法", decision.orderedTitles), 12);
  assert.equal(decisionOrderForTitle("上海市森林管理规定", decision.orderedTitles), 14);
  const localGroupTitles = [
    "上海港口客运站管理办法",
    "上海市防空警报管理办法",
    "上海市农村公路管理办法",
    "上海市森林管理规定",
  ];
  const assignments = assignInternalSequenceGroup(localGroupTitles.map((title) => ({
    title,
    officialDecisionOrder: decisionOrderForTitle(title, decision.orderedTitles),
  })));
  assert.deepEqual(
    assignments.map((assignment) => assignment.internalSequence),
    ["008", "009", "012", "014"],
  );
  assert.ok(assignments.every((assignment) => assignment.source === "SOURCE_DECISION_BODY_ORDER"));
});

test("Shanghai order 13 preserves the official five-item modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "3100003000"
    && entry.promulgationDate === "20240402"
    && entry.sequenceCode === "0013"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 5);
  assert.equal(decisionOrderForTitle("上海市医患纠纷预防与调解办法", decision.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("上海市安全生产事故隐患排查治理办法", decision.orderedTitles), 3);
  assert.equal(decisionOrderForTitle("上海市停车场（库）管理办法", decision.orderedTitles), 4);
  assert.equal(decisionOrderForTitle("上海市流动户外广告设置管理规定", decision.orderedTitles), 5);
  const localGroupTitles = [
    "上海市安全生产事故隐患排查治理办法",
    "上海市流动户外广告设置管理规定",
    "上海市停车场（库）管理办法",
    "上海市医患纠纷预防与调解办法",
  ];
  const assignments = assignInternalSequenceGroup(localGroupTitles.map((title) => ({
    title,
    officialDecisionOrder: decisionOrderForTitle(title, decision.orderedTitles),
  })));
  assert.deepEqual(
    assignments.map((assignment) => assignment.internalSequence),
    ["001", "003", "004", "005"],
  );
  assert.ok(assignments.every((assignment) => assignment.source === "SOURCE_DECISION_BODY_ORDER"));
});

test("Shanghai order 54 keeps the cross-validated city-logo position without inventing the other 62 titles", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "3100003000"
    && entry.promulgationDate === "19971219"
    && entry.sequenceCode === "0054"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 1);
  assert.equal(
    decisionOrderForTitle("上海市市标制作使用管理暂行规定", decision.orderedTitles),
    24,
  );
});

test("Shanghai order 24 preserves the official four modifications then twelve repeals", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "3100003000"
    && entry.promulgationDate === "20251229"
    && entry.sequenceCode === "0024"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 16);
  assert.equal(decisionOrderForTitle("上海市公共法律服务办法", decision.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("上海市燃气管道设施保护办法", decision.orderedTitles), 2);
  assert.equal(decisionOrderForTitle("上海市液化石油气管理办法", decision.orderedTitles), 3);
  assert.equal(decisionOrderForTitle("上海市邮政设施管理办法", decision.orderedTitles), 4);
  assert.equal(decisionOrderForTitle("上海市基本医疗保险监督管理办法", decision.orderedTitles), 5);
  assert.equal(decisionOrderForTitle("上海市监督检查从事行政许可事项活动的规定", decision.orderedTitles), 16);
});

test("Beijing order 259 preserves the official thirteen-item modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "1100003000"
    && entry.promulgationDate === "20140709"
    && entry.sequenceCode === "0259"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 13);
  assert.equal(decisionOrderForTitle("北京市劳动就业服务企业管理实施办法", decision.orderedTitles), 2);
  assert.equal(decisionOrderForTitle("北京市住宅区及住宅安全防范设施建设和使用管理办法", decision.orderedTitles), 9);
  assert.equal(decisionOrderForTitle("北京市森林资源保护管理条例实施办法", decision.orderedTitles), 13);
});

test("CSRC order 227 preserves the official 21-item modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "0000004970"
    && entry.promulgationDate === "20250327"
    && entry.sequenceCode === "0227"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 21);
  assert.equal(decisionOrderForTitle("上市公司证券发行注册管理办法", decision.orderedTitles), 1);
  assert.equal(decisionOrderForTitle(
    "北京证券交易所上市公司证券发行注册管理办法",
    decision.orderedTitles,
  ), 5);
  assert.equal(decisionOrderForTitle(
    "公开募集证券投资基金管理人监督管理办法",
    decision.orderedTitles,
  ), 11);
  assert.equal(decisionOrderForTitle("上市公司独立董事管理办法", decision.orderedTitles), 17);
  assert.equal(decisionOrderForTitle("上市公司股东减持股份管理暂行办法", decision.orderedTitles), 18);
  const localGroupTitles = [
    "北京证券交易所上市公司证券发行注册管理办法",
    "公开募集证券投资基金管理人监督管理办法",
    "上市公司独立董事管理办法",
    "上市公司股东减持股份管理暂行办法",
    "上市公司证券发行注册管理办法",
  ];
  const assignments = assignInternalSequenceGroup(localGroupTitles.map((title) => ({
    title,
    officialDecisionOrder: decisionOrderForTitle(title, decision.orderedTitles),
  })));
  assert.deepEqual(
    assignments.map((assignment) => assignment.internalSequence),
    ["001", "005", "011", "017", "018"],
  );
  assert.ok(assignments.every((assignment) => assignment.source === "SOURCE_DECISION_BODY_ORDER"));
});

test("SAMR order 31 preserves the official 30-item modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot,
    "decision_order_evidence",
    "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "0000004010"
    && entry.promulgationDate === "20201023"
    && entry.sequenceCode === "0031"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 30);
  assert.equal(decisionOrderForTitle("计量基准管理办法", decision.orderedTitles), 15);
  assert.equal(decisionOrderForTitle("中华人民共和国进口计量器具监督管理办法实施细则", decision.orderedTitles), 21);
  assert.equal(decisionOrderForTitle("眼镜制配计量监督管理办法", decision.orderedTitles), 27);
});

test("MARA order 2022 No. 1 preserves the official 29-item modification and repeal order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot,
    "decision_order_evidence",
    "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "0000003710"
    && entry.promulgationDate === "20220107"
    && entry.sequenceCode === "0001"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 29);
  assert.equal(decisionOrderForTitle("农业野生植物保护办法", decision.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("兽药产品批准文号管理办法", decision.orderedTitles), 13);
  assert.equal(decisionOrderForTitle("农作物种质资源管理办法", decision.orderedTitles), 23);
  assert.equal(decisionOrderForTitle("黄渤海区对虾亲虾资源管理暂行规定", decision.orderedTitles), 29);
});

test("Beijing order 277 preserves the official 26-item modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot,
    "decision_order_evidence",
    "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "1100003000"
    && entry.promulgationDate === "20180212"
    && entry.sequenceCode === "0277"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 26);
  assert.equal(decisionOrderForTitle("北京市利用文物保护单位拍摄电影、电视管理暂行办法", decision.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("北京市建设工程规划监督若干规定", decision.orderedTitles), 18);
  assert.equal(decisionOrderForTitle("北京市快递安全管理办法", decision.orderedTitles), 26);
});

test("Beijing order 302 preserves the official combined 16-item decision order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot,
    "decision_order_evidence",
    "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "1100003000"
    && entry.promulgationDate === "20211230"
    && entry.sequenceCode === "0302"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 16);
  assert.equal(decisionOrderForTitle("北京市社会抚养费征收管理办法", decision.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("北京市行政处罚听证程序实施办法", decision.orderedTitles), 10);
  assert.equal(decisionOrderForTitle("北京市储备粮管理办法", decision.orderedTitles), 16);
});

test("State Council order 797 preserves the official 25-item modification and repeal order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot,
    "decision_order_evidence",
    "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "0000003000"
    && entry.promulgationDate === "20241206"
    && entry.sequenceCode === "0797"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 25);
  assert.equal(decisionOrderForTitle("医疗器械监督管理条例", decision.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("婚姻登记条例", decision.orderedTitles), 20);
  assert.equal(decisionOrderForTitle("行政机关公务员处分条例", decision.orderedTitles), 25);
});

test("Zhejiang order 341 preserves the official 23-item modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot,
    "decision_order_evidence",
    "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "3300003000"
    && entry.promulgationDate === "20151228"
    && entry.sequenceCode === "0341"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 23);
  assert.equal(decisionOrderForTitle("浙江省归正人员安置帮教工作办法", decision.orderedTitles), 6);
  assert.equal(decisionOrderForTitle("浙江省人民防空警报设施管理办法", decision.orderedTitles), 7);
  assert.equal(decisionOrderForTitle("浙江省国家档案馆管理办法", decision.orderedTitles), 13);
  assert.equal(decisionOrderForTitle("浙江省高层建筑消防安全管理规定", decision.orderedTitles), 23);
});

test("Zhejiang order 284 preserves the official 18-item modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot,
    "decision_order_evidence",
    "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "3300003000"
    && entry.promulgationDate === "20101221"
    && entry.sequenceCode === "0284"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 18);
  assert.equal(decisionOrderForTitle("浙江省专业技术人员继续教育规定", decision.orderedTitles), 3);
  assert.equal(decisionOrderForTitle("浙江省社会团体管理办法", decision.orderedTitles), 7);
  assert.equal(decisionOrderForTitle("浙江省地方储备粮管理办法", decision.orderedTitles), 11);
});

test("Zhejiang order 402 preserves the official four-item modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot,
    "decision_order_evidence",
    "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "3300003000"
    && entry.promulgationDate === "20231229"
    && entry.sequenceCode === "0402"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 4);
  assert.equal(decisionOrderForTitle("浙江省种畜禽管理办法", decision.orderedTitles), 2);
  assert.equal(decisionOrderForTitle("浙江省女职工劳动保护办法", decision.orderedTitles), 3);
  assert.equal(decisionOrderForTitle("浙江省实施《中华人民共和国种子法》办法", decision.orderedTitles), 4);
});

test("Anhui order 288 preserves the official five-item modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot,
    "decision_order_evidence",
    "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "3400003000"
    && entry.promulgationDate === "20190102"
    && entry.sequenceCode === "0288"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 5);
  assert.equal(decisionOrderForTitle("安徽省陆生野生动物造成人身伤害和财产损失补偿办法", decision.orderedTitles), 2);
  assert.equal(decisionOrderForTitle("安徽省气象设施和气象探测环境保护办法", decision.orderedTitles), 4);
  assert.equal(decisionOrderForTitle("安徽省融资担保公司管理办法（试行）", decision.orderedTitles), 5);
});

test("Hebei announcement 94 preserves its decision carrier and 14-item modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot,
    "decision_order_evidence",
    "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "1300001001"
    && entry.promulgationDate === "20210929"
    && entry.sequenceCode === "0094"
  ));
  assert.ok(decision);
  assert.equal(decision.decisionTitle, "河北省人民代表大会常务委员会关于修改河北省技术市场条例等十四部法规的决定");
  assert.equal(decision.orderedTitles.length, 14);
  assert.equal(decisionOrderForTitle("河北省实施《中华人民共和国道路交通安全法》办法", decision.orderedTitles), 12);
});

test("Hebei order 2024 No. 7 preserves its official 28-item modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot,
    "decision_order_evidence",
    "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "1300003000"
    && entry.promulgationDate === "20241116"
    && entry.sequenceCode === "0007"
  ));
  assert.ok(decision);
  assert.equal(decision.decisionTitle, "河北省人民政府关于废止和修改部分省政府规章的决定");
  assert.equal(decision.orderedTitles.length, 28);
  assert.equal(decisionOrderForTitle("河北省测绘航空摄影管理规定", decision.orderedTitles), 18);
  assert.equal(decisionOrderForTitle("河北省暴雪大风寒潮大雾高温灾害防御办法", decision.orderedTitles), 21);
  assert.equal(decisionOrderForTitle("河北省税收征管保障办法", decision.orderedTitles), 28);
});

test("Hubei announcement 268 preserves its decision carrier and ten-item order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot,
    "decision_order_evidence",
    "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "4200001001"
    && entry.promulgationDate === "20200603"
    && entry.sequenceCode === "0268"
  ));
  assert.ok(decision);
  assert.equal(
    decision.decisionTitle,
    "湖北省人民代表大会常务委员会关于集中修改、废止涉及取消证明事项的部分省本级地方性法规的决定",
  );
  assert.equal(decision.orderedTitles.length, 10);
  assert.equal(decisionOrderForTitle("湖北省就业促进条例", decision.orderedTitles), 3);
});

test("modification decision resolves by agency date and exact title across categories", () => {
  const decisions = [
    {
      categoryCode: "0200",
      sequenceCode: "0045",
      orderedTitles: [
        { title: "甲法", normalizedTitle: "甲法", order: 1 },
        { title: "乙法", normalizedTitle: "乙法", order: 2 },
      ],
    },
  ];
  const resolved = decisionForDocument({
    title: "乙法",
    sequenceCode: "0099",
    categoryCode: "0100",
  }, decisions);
  assert.equal(resolved.decision.sequenceCode, "0045");
  assert.equal(resolved.order, 2);
});

test("equivalent duplicate decision evidence does not create a false ambiguity", () => {
  const decisions = [
    {
      relativePath: "official_registry/order.html",
      officialUrl: "https://example.gov.cn/order",
      sourceSha256: "a".repeat(64),
      sequenceCode: "0006",
      orderedTitles: [
        { title: "Target Regulation", normalizedTitle: "targetregulation", order: 3 },
      ],
    },
    {
      relativePath: "local/decision.md",
      sequenceCode: "0006",
      orderedTitles: [
        { title: "Target Regulation", normalizedTitle: "targetregulation", order: 3 },
      ],
    },
  ];
  const resolved = decisionForDocument({
    title: "Target Regulation",
    sequenceCode: "0006",
  }, decisions);
  assert.equal(resolved.order, 3);
  assert.equal(resolved.decision.relativePath, "official_registry/order.html");
});

test("conflicting duplicate decision evidence remains unresolved", () => {
  const decisions = [
    {
      sequenceCode: "0006",
      orderedTitles: [
        { title: "Target Regulation", normalizedTitle: "targetregulation", order: 3 },
      ],
    },
    {
      sequenceCode: "0006",
      orderedTitles: [
        { title: "Target Regulation", normalizedTitle: "targetregulation", order: 4 },
      ],
    },
  ];
  assert.equal(decisionForDocument({
    title: "Target Regulation",
    sequenceCode: "0006",
  }, decisions), null);
});

test("internal sequence accepts only evidenced order inside the promulgation decision", () => {
  const entries = [
    { id: "乙", title: "乙法", relativePath: "乙.md", officialDecisionOrder: 2 },
    { id: "甲", title: "甲法", relativePath: "甲.md", officialDecisionOrder: 1 },
  ];
  const assignments = assignInternalSequenceGroup(entries);
  assert.deepEqual(
    assignments.map(({ entry, internalSequence, source }) => [entry.id, internalSequence, source]),
    [
      ["甲", "001", "SOURCE_DECISION_BODY_ORDER"],
      ["乙", "002", "SOURCE_DECISION_BODY_ORDER"],
    ],
  );
});

test("single modified regulation keeps its evidenced order inside the decision", () => {
  const [assignment] = assignInternalSequenceGroup([
    {
      id: "外商投资电信企业管理规定",
      title: "外商投资电信企业管理规定",
      relativePath: "外商投资电信企业管理规定.md",
      officialDecisionOrder: 1,
    },
  ]);
  assert.equal(assignment.internalSequence, "001");
  assert.equal(assignment.source, "SOURCE_DECISION_BODY_ORDER");
});

test("promulgating decision keeps internal 000 while its modified regulation uses evidenced order", () => {
  const decisions = [{
    decisionTitle: "关于修改甲条例等法规的决定",
    sequenceCode: "0094",
    orderedTitles: [{ title: "甲条例", normalizedTitle: "甲条例", order: 12 }],
  }];
  const carrier = decisionForDocument({
    title: "关于修改甲条例等法规的决定",
    sequenceCode: "0094",
  }, decisions);
  const modified = decisionForDocument({ title: "甲条例", sequenceCode: "0094" }, decisions);
  assert.equal(carrier.order, 0);
  assert.equal(modified.order, 12);
  const assignments = assignInternalSequenceGroup([
    { id: "decision", officialDecisionOrder: carrier.order },
    { id: "modified", officialDecisionOrder: modified.order },
  ]);
  assert.deepEqual(
    assignments.map(({ entry, internalSequence, source }) => [entry.id, internalSequence, source]),
    [
      ["decision", "000", "SOURCE_DECISION_BODY_ORDER"],
      ["modified", "012", "SOURCE_DECISION_BODY_ORDER"],
    ],
  );
});

test("decision coding keeps carrier order zero and replaces a meeting-number sequence", () => {
  const coding = decisionCodingForDocument({
    title: "关于修改甲条例等法规的决定",
    sequenceCode: "0025",
  }, [{
    decisionTitle: "关于修改甲条例等法规的决定",
    sequenceCode: "0094",
    relativePath: "official_registry/decision.html",
    officialUrl: "https://example.gov.cn/decision.html",
    sourceSha256: "a".repeat(64),
    orderedTitles: [{ title: "甲条例", normalizedTitle: "甲条例", order: 12 }],
  }]);
  assert.equal(coding.sequenceCode, "0094");
  assert.equal(coding.officialDecisionOrder, 0);
  assert.equal(coding.canonicalTitle, "关于修改甲条例等法规的决定");
  assert.equal(JSON.parse(coding.decisionOrderEvidence).order, 0);
});

test("known official orders remain assignable when another collision peer lacks evidence", () => {
  const assignments = assignInternalSequenceGroup([
    { id: "已知二十", officialDecisionOrder: 20 },
    { id: "缺证" },
    { id: "已知三十六", officialDecisionOrder: 36 },
  ]);
  assert.deepEqual(
    assignments.map(({ entry, internalSequence, source }) => [entry.id, internalSequence, source]),
    [
      ["已知二十", "020", "SOURCE_DECISION_BODY_ORDER"],
      ["已知三十六", "036", "SOURCE_DECISION_BODY_ORDER"],
      ["缺证", "", "BLOCKED_MISSING_OFFICIAL_DECISION_ORDER"],
    ],
  );
});

test("duplicate evidenced orders require an authority-assigned internal sequence", () => {
  const assignments = assignInternalSequenceGroup([
    { id: "同日决定甲", officialDecisionOrder: 0 },
    { id: "同日决定乙", officialDecisionOrder: 0 },
  ]);
  assert.deepEqual(
    assignments.map(({ entry, internalSequence, source }) => [entry.id, internalSequence, source]),
    [
      ["同日决定甲", "", "BLOCKED_AUTHORITY_ASSIGNED_INTERNAL_SEQUENCE"],
      ["同日决定乙", "", "BLOCKED_AUTHORITY_ASSIGNED_INTERNAL_SEQUENCE"],
    ],
  );
});

test("official index rank and normalized title order cannot replace decision order", () => {
  const entries = [
    { id: "乙", title: "乙法", relativePath: "乙.md", officialLawRank: 20 },
    { id: "甲", title: "甲法", relativePath: "甲.md", officialLawRank: 10 },
  ];
  const assignments = assignInternalSequenceGroup(entries);
  assert.deepEqual(
    assignments.map(({ entry, internalSequence, source }) => [entry.id, internalSequence, source]),
    [
      ["乙", "", "BLOCKED_MISSING_OFFICIAL_DECISION_ORDER"],
      ["甲", "", "BLOCKED_MISSING_OFFICIAL_DECISION_ORDER"],
    ],
  );
});

test("delivery paths follow GB/T 47277 local-legislation categories", () => {
  assert.equal(
    targetDirectoryForSource({
      relativePath: "01_立法与公开行政文件/03_地方立法/示例.md",
      objectType: "legal_document",
      title: "深圳经济特区示例条例",
      categoryCode: "0901",
      agencyName: "深圳市人民代表大会常务委员会",
    }),
    "05_地方立法/04_经济特区法规",
  );
  assert.equal(
    targetDirectoryForSource({
      relativePath: "01_立法与公开行政文件/03_地方立法/示例.md",
      objectType: "legal_document",
      title: "上海市浦东新区示例法规",
      categoryCode: "0902",
      agencyName: "上海市人民代表大会常务委员会",
    }),
    "05_地方立法/05_浦东新区法规",
  );
  assert.equal(
    targetDirectoryForSource({
      relativePath: "01_立法与公开行政文件/03_地方立法/示例.md",
      objectType: "legal_document",
      title: "海南自由贸易港示例法规",
      categoryCode: "0903",
      agencyName: "海南省人民代表大会常务委员会",
    }),
    "05_地方立法/06_海南自由贸易港法规",
  );
  assert.equal(
    targetDirectoryForSource({
      relativePath: "01_立法与公开行政文件/03_地方立法/02_自治条例和单行条例/示例.md",
      objectType: "legal_document",
      title: "某自治县自治条例",
      categoryCode: "0800",
      agencyName: "某自治县人民代表大会",
    }),
    "05_地方立法/02_自治条例",
  );
  assert.equal(
    targetDirectoryForSource({
      relativePath: "01_立法与公开行政文件/03_地方立法/02_自治条例和单行条例/示例.md",
      objectType: "legal_document",
      title: "某自治县水资源管理条例",
      categoryCode: "0800",
      agencyName: "某自治县人民代表大会",
    }),
    "05_地方立法/03_单行条例",
  );
});

test("court Q&A delivery keeps source subtypes separate", () => {
  const base = "02_法院系统/05_法答网精选与法院业务答疑";
  assert.equal(
    targetDirectoryForSource({
      relativePath: `${base}/01_法答网精选/示例.md`,
      objectType: "practice_reference",
    }),
    "10_司法业务指导、会议纪要与公开答疑【非规范性法源】/03_法答网精选",
  );
  assert.equal(
    targetDirectoryForSource({
      relativePath: `${base}/02_最高法法律问答批次汇编/示例.md`,
      objectType: "practice_reference",
    }),
    "10_司法业务指导、会议纪要与公开答疑【非规范性法源】/04_法院业务答疑/01_最高法法律问答批次汇编",
  );
  assert.equal(
    targetDirectoryForSource({
      relativePath: `${base}/03_其他法院公开答疑/示例.md`,
      objectType: "practice_reference",
    }),
    "10_司法业务指导、会议纪要与公开答疑【非规范性法源】/04_法院业务答疑/02_其他法院公开答疑",
  );
});

test("one-time migration reads only exact legacy filename date and effect suffixes", () => {
  assert.deepEqual(
    deriveLegacyFilenameMetadata(
      "01_立法与公开行政文件/03_地方立法/示例条例_2004-05-30_有效_ima-a1.md",
    ),
    { promulgationDate: "2004-05-30", effectCode: "01" },
  );
  assert.deepEqual(
    deriveLegacyFilenameMetadata("01_x/示例条例_2004-05-30_未知_ima-a1.md"),
    { promulgationDate: "2004-05-30", effectCode: "" },
  );
  assert.deepEqual(
    deriveLegacyFilenameMetadata("01_x/示例条例_2004-02-30_有效_ima-a1.md"),
    { promulgationDate: "", effectCode: "01" },
  );
  assert.deepEqual(
    deriveLegacyFilenameMetadata("01_x/示例条例_２００２-06-01_有效_ima-a1.md"),
    { promulgationDate: "2002-06-01", effectCode: "01" },
  );
  assert.deepEqual(
    deriveLegacyFilenameMetadata("03_检察院系统/人民检察院审查案件听证工作规定_2020-01-01_有效.md"),
    { promulgationDate: "2020-01-01", effectCode: "01" },
  );
});

test("explicit decision clauses and the 2023 minor-sexual-assault opinion supply effect metadata", () => {
  const registryPath = path.resolve(testDir, "..", "..", "schema", "标准元数据补证注册表.json");
  const metadata = loadMetadataOverrides(registryPath);
  const decisionEntries = [...metadata.values()].filter(
    (entry) => entry.evidence.type === "OFFICIAL_EFFECTIVE_DECISION_CLAUSE",
  );
  assert.equal(decisionEntries.length, 15);
  assert.equal(decisionEntries.every((entry) => entry.values.SXX === "01"), true);
  assert.equal(
    decisionEntries.every((entry) => entry.values._effect_source === "OFFICIAL_EFFECTIVE_CLAUSE"),
    true,
  );

  const opinionPath = "02_法院系统/02_法院司法规范性文件/【法发〔2013〕12号】最高人民法院最高人民检察院公安部司法部关于印发《关于办理性侵害未成年人刑事案件的意见》的通知高检发〔_20230601_司法文件 [ima-pdf_32e7-2143438f] (1).md";
  const opinion = metadata.get(opinionPath);
  assert.deepEqual(
    {
      GBRQ: opinion?.values.GBRQ,
      SXRQ: opinion?.values.SXRQ,
      SXX: opinion?.values.SXX,
      FWZH: opinion?.values.FWZH,
      ZDJGDM: opinion?.values.ZDJGDM,
    },
    {
      GBRQ: "20230524",
      SXRQ: "20230601",
      SXX: "01",
      FWZH: "高检发〔2023〕4号",
      ZDJGDM: "0000001510",
    },
  );
});

test("official FLK status maps only observed live values to standard effect codes", () => {
  assert.equal(mapFlkEffectCode("3"), "01");
  assert.equal(mapFlkEffectCode("4"), "02");
  assert.equal(mapFlkEffectCode("2"), "03");
  assert.equal(mapFlkEffectCode("1"), "04");
  assert.equal(mapFlkEffectCode("-1"), "");
  assert.equal(mapFlkEffectCode(""), "");
});

test("official FLK identity reads 文件标识 and URL id without treating them as WJBS", () => {
  assert.deepEqual(
    officialVersionIdCandidates(
      { 文件标识: "ABC123", WJBS: "1.2.156.3005.6-0100000000100120200101000100000" },
      "https://flk.npc.gov.cn/detail?id=DEF456&fileId=",
    ),
    ["abc123", "def456"],
  );
});

test("official FLK metadata resolves only a unique version id with the same title", () => {
  const registry = {
    byId: new Map([
      ["abc123", [{
        bbbs: "abc123",
        title: "中华人民共和国示例法",
        gbrq: "2024-01-01",
        sxrq: "2024-02-01",
        sxx: "3",
      }]],
    ]),
  };
  assert.equal(
    resolveFlkRecord(
      { 文件标识: "ABC123" },
      "",
      "中华人民共和国示例法",
      registry,
    )?.bbbs,
    "abc123",
  );
  assert.equal(
    resolveFlkRecord({ 文件标识: "ABC123" }, "", "另一标题", registry),
    null,
  );
});

test("formal fulltext blockers distinguish mismatch, access block and absence", () => {
  assert.equal(
    formalFulltextBlockingCode({ verification_status: "FULLTEXT_MISMATCH" }),
    "FULLTEXT_MISMATCH",
  );
  assert.equal(
    formalFulltextBlockingCode({ verification_status: "BLOCKED_ACCESS" }),
    "FULLTEXT_BLOCKED_ACCESS",
  );
  assert.equal(
    formalFulltextBlockingCode(null),
    "FULLTEXT_VERIFICATION_MISSING",
  );
  assert.equal(
    formalFulltextBlockingCode({ verification_status: "FULLTEXT_VERIFIED" }),
    "",
  );
});

test("official FLK CSV loader preserves records containing quoted line breaks", async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "flk-registry-test-"));
  const csvPath = path.join(directory, "index.csv");
  try {
    fs.writeFileSync(
      csvPath,
      [
        "bbbs,title,gbrq,sxrq,sxx,zdjgName,flxz,zdjgCodeId,flfgCodeId,raw_json",
        'a1,"跨行',
        '标题",2024-01-01,2024-02-01,3,国务院,行政法规,120,210,"{""x"":1}"',
        'a2,普通标题,2024-03-01,2024-04-01,4,国务院,行政法规,120,210,"{""x"":2}"',
      ].join("\r\n"),
      "utf8",
    );
    const registry = await loadFlkRegistry(csvPath);
    assert.equal(registry.rowCount, 2);
    assert.equal(registry.uniqueIdCount, 2);
    assert.equal(registry.byId.get("a1")[0].title, "跨行\n标题");
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("national rules registry uses only unique title-category matches and one publisher", () => {
  assert.deepEqual(cleanNationalRulesPublishers("['北京市人民政府']"), ["北京市人民政府"]);
  assert.deepEqual(
    cleanNationalRulesPublishers("['交通运输部', '公安部']"),
    ["交通运输部", "公安部"],
  );
  const registry = {
    byCategoryTitle: new Map([
      ["地方政府规章|示例办法", [{
        record_id: "official-1",
        title: "示例办法",
        category: "地方政府规章",
        publishers: ["北京市人民政府"],
      }]],
    ]),
  };
  assert.equal(
    resolveNationalRuleRecord("示例办法", "1400", registry)?.record_id,
    "official-1",
  );
  assert.equal(resolveNationalRuleRecord("示例办法", "1300", registry), null);
});

test("national rules registry disambiguates duplicate carriers only by exact issuing agency", () => {
  const registry = {
    byCategoryTitle: new Map([[
      "部门规章|联合办法",
      [
        {
          record_id: "commerce-copy",
          title: "联合办法",
          category: "部门规章",
          publishers: ["商务部"],
        },
        {
          record_id: "market-copy",
          title: "联合办法",
          category: "部门规章",
          publishers: ["国家市场监督管理总局"],
        },
      ],
    ]]),
  };
  assert.equal(resolveNationalRuleRecord("联合办法", "1300", registry), null);
  assert.equal(
    resolveNationalRuleRecord("联合办法", "1300", registry, "国家市场监督管理总局")?.record_id,
    "market-copy",
  );
  assert.equal(resolveNationalRuleRecord("联合办法", "1300", registry, "司法部"), null);
});

test("WJBS transition audit rejects formal document CSVs in place of coding manifests", () => {
  const temporaryDirectory = fs.mkdtempSync(path.join(os.tmpdir(), "wjbs-audit-header-"));
  const wrongBaselinePath = path.join(temporaryDirectory, "legal_documents.csv");
  const currentPath = path.join(temporaryDirectory, "current.csv");
  fs.writeFileSync(
    wrongBaselinePath,
    "legal_document_id,title,body_markdown\n1,示例法规,正文\n",
    "utf8",
  );
  fs.writeFileSync(
    currentPath,
    [
      "relative_path,WJBS,internal_sequence_source,coding_status,blocking_reason,category_code,agency_code,promulgation_date,sequence_code,file_type_code",
      "example.md,,BLOCKED_SEQUENCE,BLOCKED,INTERNAL_SEQUENCE_UNRESOLVED,1100,0000000001,20260101,,00",
      "",
    ].join("\n"),
    "utf8",
  );

  const auditPath = path.resolve(testDir, "..", "audit_wjbs_gate_transition.mjs");
  const result = spawnSync(process.execPath, [
    auditPath,
    "--baseline", wrongBaselinePath,
    "--current", currentPath,
  ], { encoding: "utf8" });

  assert.notEqual(result.status, 0);
  assert.match(`${result.stdout}\n${result.stderr}`, /标准编码生成清单|缺少必需字段/);
});

test("WJBS transition audit does not report effect-blocked rows as released WJBS", () => {
  const temporaryDirectory = fs.mkdtempSync(path.join(os.tmpdir(), "wjbs-audit-effect-"));
  const baselinePath = path.join(temporaryDirectory, "baseline.csv");
  const currentPath = path.join(temporaryDirectory, "current.csv");
  const headers = "relative_path,WJBS,internal_sequence_source,coding_status,blocking_reason,category_code,agency_code,promulgation_date,sequence_code,file_type_code";
  fs.writeFileSync(
    baselinePath,
    [
      headers,
      "missing.md,,,BLOCKED,MISSING_STANDARD_FIELD:WJBS,0400,0000000003,20240113,0002,30",
      "legacy.md,old,LOCAL_NORMALIZED_TITLE_ORDER,READY,,0700,1300001001,20210929,0025,00",
      "",
    ].join("\n"),
    "utf8",
  );
  fs.writeFileSync(
    currentPath,
    [
      headers,
      "missing.md,new,OFFICIAL_SOURCE_ORDER,BLOCKED,MISSING_STANDARD_FIELD:SXX,0400,0000000003,20240113,0002,30",
      "legacy.md,newer,OFFICIAL_DECISION_ORDER,BLOCKED,MISSING_STANDARD_FIELD:SXX|MISSING_47277_CORE_ELEMENT:DE_01018,0700,1300001001,20210929,0025,00",
      "",
    ].join("\n"),
    "utf8",
  );

  const auditPath = path.resolve(testDir, "..", "audit_wjbs_gate_transition.mjs");
  const result = spawnSync(process.execPath, [
    auditPath,
    "--baseline", baselinePath,
    "--current", currentPath,
  ], { encoding: "utf8" });

  assert.equal(result.status, 0, result.stderr);
  const report = JSON.parse(result.stdout);
  assert.equal(report.original44.BLOCKED_EFFECT_METADATA, 1);
  assert.equal(report.original1247.BLOCKED_EFFECT_METADATA, 1);
  assert.equal(report.original44.WJBS_UNIQUE, undefined);
  assert.equal(report.original1247.WJBS_DECISION, undefined);
});

test("polluted 2026 court carrier dates are replaced by exact source-body and official dates", () => {
  const metadataRegistryPath = path.resolve(
    testDir, "..", "..", "schema", "标准元数据补证注册表.json",
  );
  const metadata = loadMetadataOverrides(metadataRegistryPath);
  const root = "02_法院系统/02_法院司法规范性文件/";
  const expected = new Map([
    [
      `${root}最高人民法院关于加强和规范人民法院国家司法救助工作的意见_2026-01-06_有效_imp-32e7-22ac912e.md`,
      ["20160701", "法发〔2016〕16号"],
    ],
    [
      `${root}最高人民法院关于深化执行改革健全解决执行难长效机制的意见——人民法院执行工作纲要（2019—2023_2026-01-06_有效_imp-32e7-b872f377.md`,
      ["20190603", "法发〔2019〕16号"],
    ],
    [
      `${root}法发〔2019〕25号最高人民法院关于依法妥善审理高空抛物、坠物案件的意见_2026-01-06_有效_imp-32e7-2d77017c.md`,
      ["20191021", "法发〔2019〕25号"],
    ],
    [
      `${root}最高人民法院关于为长江经济带发展提供司法服务和保障的意见_2026-01-06_有效_imp-32e7-7b66e24f.md`,
      ["20160224", "法发〔2016〕8号"],
    ],
    [
      `${root}最高人民法院印发关于依法妥善处理历史形成的产权案件工作实施意见的通知_2026-01-06_有效_imp-32e7-6de20471.md`,
      ["20161128", "法发〔2016〕28号"],
    ],
  ]);
  for (const [relativePath, [date, documentNumber]] of expected) {
    const override = metadata.get(relativePath);
    assert.ok(override, relativePath);
    const row = applyMetadataOverride({ GBRQ: "20260106", FWZH: "" }, override);
    assert.equal(row.GBRQ, date, relativePath);
    assert.equal(row.FWZH, documentNumber, relativePath);
    assert.equal(row._promulgation_source, "SOURCE_BODY_ISSUE_DATE", relativePath);
  }
});

test("targeted legacy court carriers use exact issue metadata and official repeal status", () => {
  const metadataRegistryPath = path.resolve(
    testDir, "..", "..", "schema", "标准元数据补证注册表.json",
  );
  const metadata = loadMetadataOverrides(metadataRegistryPath);
  const root = "02_法院系统/02_法院司法规范性文件/";
  const expected = new Map([
    [
      `${root}最高人民法院公安部印发关于开展司法拘留社会矛盾化解工作的意见的通知_2026-01-06_有效_imp-32e7-294c8b6c.md`,
      ["20161116", "法发〔2016〕25号", "01", ""],
    ],
    [
      `${root}最高人民法院关于加强经济审判工作的通知_2026-01-06_有效_imp-32e7-e27fd6d2.md`,
      ["19851209", "法（研）发〔1985〕28号", "04", "20130118"],
    ],
    [
      `${root}最高人民法院最高人民检察院公安部司法部关于抓紧从严打击制造、贩卖假药、毒品和有毒食品等严重危害人民生_1985-01-01_有效_imp-32e7-7c273179.md`,
      ["19850712", "法（研）发〔1985〕15号", "04", "20130118"],
    ],
    [
      `${root}最高人民法院最高人民检察院关于当前办理盗窃案件中适用法律问题的补充通知_2026-01-06_有效_imp-32e7-06580c68.md`,
      ["19860917", "法（研）发〔1986〕26号", "04", "20130118"],
    ],
  ]);
  for (const [relativePath, [date, documentNumber, effectCode, invalidityDate]] of expected) {
    const override = metadata.get(relativePath);
    assert.ok(override, relativePath);
    const row = applyMetadataOverride({ GBRQ: "20260106", FWZH: "", SXX: "01", SHXRQ: "" }, override);
    assert.equal(row.GBRQ, date, relativePath);
    assert.equal(row.FWZH, documentNumber, relativePath);
    assert.equal(row.SXX, effectCode, relativePath);
    assert.equal(row.SHXRQ, invalidityDate, relativePath);
  }
});

test("targeted court batch two separates exact dates from explicit repeal dates", () => {
  const metadataRegistryPath = path.resolve(
    testDir, "..", "..", "schema", "标准元数据补证注册表.json",
  );
  const metadata = loadMetadataOverrides(metadataRegistryPath);
  const root = "02_法院系统/02_法院司法规范性文件/";
  const expected = new Map([
    [
      `${root}最高人民法院、最高人民检察院、公安部、司法部印发关于办理“套路贷”刑事案件若干问题的意见的通知_2019-01-01_有效_imp-32e7-b79ac925.md`,
      ["20190228", "法发〔2019〕11号", "20190409", "01", ""],
    ],
    [
      `${root}最高人民法院关于各级人民法院处理民事和经济纠纷案件申诉的暂行规定_1989-01-01_有效_imp-32e7-cbc50c26.md`,
      ["19890721", "法（申）发〔1989〕17号", "", "04", "20130118"],
    ],
    [
      `${root}最高人民法院全国工商联印发关于发挥商会调解优势推进民营经济领域纠纷多元化解机制建设的意见的通知_2019-01-01_有效_imp-32e7-b0ac9d2b.md`,
      ["20190114", "法〔2019〕11号", "", "01", ""],
    ],
    [
      `${root}最高人民法院最高人民检察院公安部国家安全部司法部全国人大常委会法制工作委员会关于刑事诉讼法实施中若干_1998-01-01_有效_imp-32e7-29206f42.md`,
      ["19980119", "", "", "04", "20130101"],
    ],
    [
      `${root}最高人民法院最高人民检察院公安部国家工商行政管理局关于印发关于依法查处盗窃、抢劫机动车案件的规定_1998-01-01_有效_imp-32e7-1f969821.md`,
      ["19980508", "公通字〔1998〕31号", "", "01", ""],
    ],
    [
      `${root}最高人民法院最高人民检察院公安部司法部卫生部关于精神疾病司法鉴定暂行规定_1989-01-01_有效_imp-32e7-22680f29.md`,
      ["19890711", "卫医字〔1989〕第17号", "19890801", "01", ""],
    ],
    [
      `${root}最高人民法院最高人民检察院印发关于办理盗窃、盗掘、非法经营和走私文物的案件具体应用法律的若干问题的_1987-01-01_有效_imp-32e7-58ef5b88.md`,
      ["19871127", "法（研）发〔1987〕32号", "", "04", "20160101"],
    ],
    [
      `${root}最高人民法院关于涉外海事诉讼管辖的具体规定_2026-01-06_有效_imp-32e7-71709096.md`,
      ["19860131", "", "", "04", "20130118"],
    ],
  ]);
  for (const [relativePath, [date, documentNumber, effectiveDate, effectCode, invalidityDate]] of expected) {
    const override = metadata.get(relativePath);
    assert.ok(override, relativePath);
    const row = applyMetadataOverride(
      { GBRQ: "20260106", FWZH: "", SXRQ: "", SXX: "01", SHXRQ: "" },
      override,
    );
    assert.equal(row.GBRQ, date, relativePath);
    assert.equal(row.FWZH, documentNumber, relativePath);
    assert.equal(row.SXRQ, effectiveDate, relativePath);
    assert.equal(row.SXX, effectCode, relativePath);
    assert.equal(row.SHXRQ, invalidityDate, relativePath);
  }
});

test("targeted legacy court batch three replaces carrier dates with evidenced issue metadata", () => {
  const registryPath = path.resolve(testDir, "..", "..", "schema", "标准元数据补证注册表.json");
  const metadata = loadMetadataOverrides(registryPath);
  const root = "02_法院系统/02_法院司法规范性文件/";
  const expected = new Map([
    [`${root}最高人民法院关于贯彻执行〈经济合同法若干问题的意见_1985-01-01_有效_imp-32e7-915bb6a0.md`, ["19840917", "(1984)法办字第128号", "最高人民法院", "0000001610"]],
    [`${root}最高人民法院关于贯彻执行民事诉讼法（试行）若干问题的意见_1985-01-01_有效_imp-32e7-aab4e959.md`, ["19840908", "〔84〕法办字第112号", "最高人民法院", "0000001610"]],
    [`${root}最高人民法院关于在经济审判工作中贯彻执行民事诉讼法（试行）若干问题的意见_1985-01-01_有效_imp-32e7-8faafca6.md`, ["19841010", "〔84〕法办字第128号", "最高人民法院", "0000001610"]],
    [`${root}最高人民法院关于开展专利审判工作的几个问题的通知_2026-01-06_有效_imp-32e7-5359a5c9.md`, ["19850216", "法（经）〔1985〕3号", "最高人民法院", "0000001610"]],
    [`${root}最高人民法院关于审理农村承包合同纠纷案件若干问题的意见_1986-01-01_有效_imp-32e7-398f824f.md`, ["19860414", "法（经）发〔1986〕13号", "最高人民法院", "0000001610"]],
    [`${root}最高人民法院关于诉讼前扣押船舶的具体规定_2026-01-06_有效_imp-32e7-68cbef2f.md`, ["19860131", "", "最高人民法院", "0000001610"]],
    [`${root}最高人民法院最高人民检察院司法部公安部关于印发人体重伤鉴定标准（试行）的通知_1986-01-01_有效_imp-32e7-cb3a9a91.md`, ["19860815", "（86）司发研字第249号", "中华人民共和国司法部", "0000003150"]],
  ]);
  for (const [relativePath, [date, documentNumber, agencyName, agencyCode]] of expected) {
    const override = metadata.get(relativePath);
    assert.ok(override, relativePath);
    const row = applyMetadataOverride({ GBRQ: "20260106", FWZH: "", ZDJGMC: "最高人民法院", ZDJGDM: "0000001610" }, override);
    assert.equal(row.GBRQ, date, relativePath);
    assert.equal(row.FWZH, documentNumber, relativePath);
    assert.equal(row.ZDJGMC, agencyName, relativePath);
    assert.equal(row.ZDJGDM, agencyCode, relativePath);
    assert.equal(row._promulgation_source, "CROSS_VALIDATED_ORIGINAL_CARRIER", relativePath);
  }
});

test("Shanghai order 49 follows the official three-rule modification order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "3100003000"
    && entry.promulgationDate === "20210508"
    && entry.sequenceCode === "0049"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 3);
  assert.equal(decisionOrderForTitle("上海市居住房屋租赁管理办法", decision.orderedTitles), 1);
  assert.equal(decisionOrderForTitle("上海市海域使用管理办法", decision.orderedTitles), 2);
  assert.equal(decisionOrderForTitle("上海市停车场（库）管理办法", decision.orderedTitles), 3);
});

test("Anshan order 190 preserves the official six-rule amendment order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "2103003000"
    && entry.promulgationDate === "20171025"
    && entry.sequenceCode === "0190"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 6);
  assert.equal(decisionOrderForTitle("鞍山市传染病病人收治管理办法", decision.orderedTitles), 2);
  assert.equal(decisionOrderForTitle("鞍山市河道管理实施细则", decision.orderedTitles), 5);
  assert.equal(decisionOrderForTitle("鞍山市城市房屋设施拆改管理办法", decision.orderedTitles), 6);
});

test("Jiangxi order 241 preserves the cross-validated 43-rule amendment order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "3600003000"
    && entry.promulgationDate === "20190929"
    && entry.sequenceCode === "0241"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 43);
  assert.equal(decisionOrderForTitle("江西省非机动车管理办法", decision.orderedTitles), 3);
  assert.equal(decisionOrderForTitle("江西省合同格式条款监督办法", decision.orderedTitles), 38);
});

test("Ningxia order 117 preserves the official eleven-rule amendment order", () => {
  const registryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(registryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "6400003000"
    && entry.promulgationDate === "20210820"
    && entry.sequenceCode === "0117"
  ));
  assert.ok(decision);
  assert.equal(decision.orderedTitles.length, 11);
  assert.equal(decisionOrderForTitle("宁夏回族自治区中小学教师继续教育规定", decision.orderedTitles), 2);
  assert.equal(decisionOrderForTitle("宁夏回族自治区城镇国有土地使用权出让和转让办法", decision.orderedTitles), 6);
});

test("Ningxia order 117 targets use the official order number and date", () => {
  const registryPath = path.resolve(testDir, "..", "..", "schema", "标准元数据补证注册表.json");
  const metadata = loadMetadataOverrides(registryPath);
  const expected = [
    "01_立法与公开行政文件/04_规章/02_地方政府规章/宁夏/宁夏回族自治区中小学教师继续教育规定_2021-08-20_有效_ima-4c9206da.md",
    "01_立法与公开行政文件/04_规章/02_地方政府规章/宁夏/宁夏回族自治区城镇国有土地使用权出让和转让办法_2021-08-20_有效_ima-048bc1e0.md",
  ];
  for (const relativePath of expected) {
    const override = metadata.get(relativePath);
    assert.ok(override, relativePath);
    const row = applyMetadataOverride({ GBRQ: "", FWZH: "", ZDJGMC: "", ZDJGDM: "" }, override);
    assert.equal(row.GBRQ, "20210820", relativePath);
    assert.equal(row.FWZH, "宁夏回族自治区人民政府令第117号", relativePath);
    assert.equal(row.ZDJGMC, "宁夏回族自治区人民政府", relativePath);
    assert.equal(row.ZDJGDM, "6400003000", relativePath);
  }
});

test("Qinhuangdao Kongming lantern rule uses archived official order 2 metadata", () => {
  const registryPath = path.resolve(testDir, "..", "..", "schema", "标准元数据补证注册表.json");
  const metadata = loadMetadataOverrides(registryPath);
  const relativePath = "01_立法与公开行政文件/04_规章/02_地方政府规章/河北/秦皇岛市“孔明灯”管理规定_2016-07-01_有效_ima-ca9e2ab9.md";
  const override = metadata.get(relativePath);
  assert.ok(override, relativePath);
  const row = applyMetadataOverride({ GBRQ: "", FWZH: "", SXRQ: "", ZDJGMC: "", ZDJGDM: "" }, override);
  assert.equal(row.GBRQ, "20160618");
  assert.equal(row.FWZH, "秦皇岛市人民政府令第2号");
  assert.equal(row.SXRQ, "20160701");
  assert.equal(row.ZDJGMC, "秦皇岛市人民政府");
  assert.equal(row.ZDJGDM, "1303003000");
  assert.equal(override.evidence.type, "ARCHIVED_OFFICIAL_LOCAL_GOVERNMENT_PDF");
  assert.equal(override.evidence.source_sha256, "249B475DC3D8EB0A44C9ACBAA7679174632562EE7BA2743DF9E6EDC8E4F2C43D");
});

test("Beijing 1994 document-number expression order resolves three omitted-attachment targets", () => {
  const decisionRegistryPath = path.resolve(
    officialRegistryRoot, "decision_order_evidence", "registry.json",
  );
  const decisions = loadDecisionOrderEvidenceRegistry(decisionRegistryPath);
  const decision = decisions.find((entry) => (
    entry.agencyCode === "1100003000"
    && entry.promulgationDate === "19940117"
    && entry.sequenceCode === "0005"
  ));
  assert.ok(decision);
  const expectedOrders = new Map([
    ["北京市铁路干线两侧隔离带规划建设管理暂行规定", 3],
    ["北京市城镇私有房屋翻建扩建规划管理若干规定", 4],
    ["关于划定市区河道两侧隔离带的规定", 6],
  ]);
  for (const [title, order] of expectedOrders) {
    assert.equal(decisionOrderForTitle(title, decision.orderedTitles), order, title);
  }

  const metadataRegistryPath = path.resolve(testDir, "..", "..", "schema", "标准元数据补证注册表.json");
  const metadata = loadMetadataOverrides(metadataRegistryPath);
  const expectedPaths = [
    "01_立法与公开行政文件/04_规章/02_地方政府规章/北京/北京市铁路干线两侧隔离带规划建设管理暂行规定_1994-01-17_有效_ima-a53778af.md",
    "01_立法与公开行政文件/04_规章/02_地方政府规章/北京/北京市城镇私有房屋翻建扩建规划管理若干规定_1994-01-17_有效_ima-4380d40d.md",
    "01_立法与公开行政文件/04_规章/02_地方政府规章/北京/关于划定市区河道两侧隔离带的规定_1994-01-17_有效_ima-c9ae30e3.md",
  ];
  for (const relativePath of expectedPaths) {
    const override = metadata.get(relativePath);
    assert.ok(override, relativePath);
    const row = applyMetadataOverride({ GBRQ: "", FWZH: "", ZDJGMC: "", ZDJGDM: "" }, override);
    assert.equal(row.GBRQ, "19940117", relativePath);
    assert.equal(row.FWZH, "京政发〔1994〕5号", relativePath);
    assert.equal(row.ZDJGMC, "北京市人民政府", relativePath);
    assert.equal(row.ZDJGDM, "1100003000", relativePath);
  }
});
