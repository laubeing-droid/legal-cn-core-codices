import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const testDir = path.dirname(fileURLToPath(import.meta.url));
const engineeringRoot = path.resolve(testDir, "..");
const schema = JSON.parse(
  fs.readFileSync(path.join(engineeringRoot, "schema", "tables.json"), "utf8"),
);
const standardRegistry = JSON.parse(
  fs.readFileSync(
    path.join(engineeringRoot, "schema", "standard_registry.json"),
    "utf8",
  ),
);
const fieldMap = fs.readFileSync(
  path.join(engineeringRoot, "schema", "标准字段映射表.md"),
  "utf8",
);
const buildSource = fs.readFileSync(
  path.join(engineeringRoot, "tools", "build_local_csv.mjs"),
  "utf8",
);
const sourceRegistry = JSON.parse(
  fs.readFileSync(path.join(engineeringRoot, "schema", "来源注册表.json"), "utf8"),
);

test("D01-D02: WJBS permits evidenced STANDARD_DERIVED_LOCAL", () => {
  assert.equal(
    standardRegistry.wjbs_rule.authority_issued_required,
    false,
  );
  assert.deepEqual(
    standardRegistry.wjbs_rule.allowed_source_types,
    ["AUTHORITY_ISSUED", "STANDARD_DERIVED_LOCAL"],
  );
  assert.match(fieldMap, /STANDARD_DERIVED_LOCAL.*正式/);
  assert.doesNotMatch(fieldMap, /本库派生组合只可进入编码候选清单/);
});

test("D06-D07: pseudo binary relative-path fields are removed", () => {
  const allColumns = Object.values(schema.tables).flatMap((table) => table.columns);
  assert.equal(allColumns.includes("DE_02006_relative_path"), false);
  assert.equal(allColumns.includes("DE_04003_relative_path"), false);
  assert.deepEqual(
    schema.tables["legal_contents.csv"].columns,
    ["DE_01001", "DE_02001", "DE_02002", "DE_02003", "DE_02004", "DE_02005"],
  );
  assert.deepEqual(
    schema.tables["legal_sources.csv"].columns,
    ["DE_01001", "DE_04001", "DE_04002", "DE_04003"],
  );
});

test("D03-D05: Markdown paths are readable and follow the final tree", async () => {
  const {
    readableMarkdownFilename,
    targetDirectoryForSource,
    REQUIRED_FINAL_DIRECTORIES,
  } = await import("../tools/delivery_paths.mjs");
  assert.ok(REQUIRED_FINAL_DIRECTORIES.includes("00_法律检索导航与效力适用规则"));
  assert.ok(REQUIRED_FINAL_DIRECTORIES.includes("01_宪法/02_宪法修正案"));
  assert.ok(REQUIRED_FINAL_DIRECTORIES.includes("80_司法部仲裁案例【参考性、非规范性法源】/03_撤销与不予执行仲裁裁决案例"));
  assert.equal(
    readableMarkdownFilename({
      objectType: "legal_document",
      title: "中华人民共和国示例法",
      publicationDate: "2026-07-31",
      effectLabel: "有效",
      wjbs: "1.2.156.3005.6-0100000000161020260731000100000",
    }),
    "中华人民共和国示例法_2026-07-31_有效_1.2.156.3005.6-0100000000161020260731000100000.md",
  );
  const caseName = readableMarkdownFilename({
    objectType: "case",
    title: "测试案例",
    officialCaseId: "",
    publicationDate: "2026-07-31",
  });
  assert.equal(caseName, "测试案例__2026-07-31.md");
  assert.doesNotMatch(caseName, /^[0-9a-f]{64}\.md$/);
  assert.equal(
    targetDirectoryForSource({
      relativePath: "04_仲裁系统/01_司法部案例库仲裁案例/案例.md",
      objectType: "case",
      title: "国内仲裁案例",
    }),
    "80_司法部仲裁案例【参考性、非规范性法源】/01_国内仲裁案例",
  );
  assert.equal(
    targetDirectoryForSource({
      relativePath: "02_法院系统/06_最高人民法院指导性案例/案例.md",
      objectType: "case",
      title: "指导案例",
    }),
    "81_最高人民法院公开案例【非规范性法源】/01_最高人民法院指导性案例",
  );
  assert.equal(
    targetDirectoryForSource({
      relativePath: "03_检察院系统/05_检察机关典型案例/案例.md",
      objectType: "case",
      title: "典型案例",
    }),
    "82_最高人民检察院公开案例【非规范性法源】/02_最高人民检察院典型案例",
  );
});

test("D10-D12: builder separates candidate and engineering roots", () => {
  assert.match(buildSource, /--engineering-root/);
  assert.match(
    buildSource,
    /path\.resolve\(scriptDir, "\.\.", "workspace", "交换候选"\)/,
  );
  assert.match(
    buildSource,
    /path\.resolve\(scriptDir, "\.\.", "workspace", "工程记录"\)/,
  );
  assert.doesNotMatch(buildSource, /SOURCE_RELATIVE_PATH_SHA256/);
  assert.doesNotMatch(
    buildSource,
    /const formalDir = path\.join\(deliveryRoot, "正式数据"\)/,
  );
  assert.match(buildSource, /candidateFinalRoot/);
});

test("D11: source registry uses final target directory identities", () => {
  const targets = sourceRegistry.official_sources.flatMap(
    (source) => source.target_dirs ?? [],
  );
  assert.ok(targets.some((target) => target.startsWith("80_司法部仲裁案例")));
  assert.ok(targets.some((target) => target.startsWith("81_最高人民法院公开案例")));
  assert.ok(targets.some((target) => target.startsWith("82_最高人民检察院公开案例")));
  assert.ok(targets.some((target) => target.startsWith("89_人民法院案例库")));
  assert.equal(
    targets.some((target) => /^\d{2}_(?:立法与公开行政文件|法院系统|检察院系统|仲裁系统)/.test(target)),
    false,
  );
});

test("verification states retain honest unverified migration states", () => {
  const values = schema.constraints.allowed_values.verification_status;
  assert.ok(values.includes("UNOFFICIAL_CANDIDATE"));
  assert.ok(values.includes("UNMATCHED_OFFICIAL_INDEX"));
  assert.ok(values.includes("BLOCKED_ACCESS"));
  assert.ok(values.includes("UNVERIFIED_LOCAL"));
  assert.ok(values.includes("IDENTITY_METADATA_VERIFIED_FULLTEXT_MISSING"));
});

test("access challenges are metadata-only inputs, never formal fulltext", () => {
  assert.match(buildSource, /IDENTITY_METADATA_VERIFIED_FULLTEXT_MISSING/);
  assert.match(buildSource, /sourceContentClass === "blocked_access_content"/);
  assert.doesNotMatch(
    buildSource,
    /emitDerivedMarkdown\(\{[\s\S]{0,500}body:\s*sourceBody[\s\S]{0,500}blocked_access_content/,
  );
});

test("formal verification hashes the same sanitized text that is published", () => {
  assert.match(
    buildSource,
    /normalized_text_sha256:[\s\S]{0,180}normalizeLegalTextForIdentity\(sanitizeFormalText\(body\)\.text\)/,
  );
});
