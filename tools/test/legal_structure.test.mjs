import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  duplicateContentStructureCodes,
  extractLegalContentRows,
  parseChineseOrdinal,
} from "../legal_structure.mjs";
import { loadFlkFulltextRegistry } from "../official_registry.mjs";

test("Chinese legal ordinals convert deterministically", () => {
  assert.equal(parseChineseOrdinal("十"), 10);
  assert.equal(parseChineseOrdinal("四百七十"), 470);
  assert.equal(parseChineseOrdinal("一千二百零三"), 1203);
  assert.equal(parseChineseOrdinal("36"), 36);
  assert.equal(parseChineseOrdinal("甲"), null);
});

test("legal structure extraction follows GB/T 47277 hierarchy and paragraph rules", () => {
  const body = [
    "第三编 合同",
    "第一分编 通则",
    "第二章 合同的订立",
    "第一节 一般规定",
    "第四百七十条 第一款正文。",
    "",
    "第二款正文：",
    "",
    "- （一）第一项；",
    "- 1. 第一目。",
    "",
    "- （二）第二项。",
    "第四百七十一条 单一自然段。",
  ].join("\n");
  const rows = extractLegalContentRows(body);
  assert.deepEqual(
    rows.map((row) => [row.DE_02003, row.DE_02001]),
    [
      ["01", "030000000000000000"],
      ["02", "030100000000000000"],
      ["03", "030102000000000000"],
      ["04", "030102010000000000"],
      ["06", "030102010470010000"],
      ["06", "030102010470020000"],
      ["07", "030102010470020100"],
      ["08", "030102010470020101"],
      ["07", "030102010470020200"],
      ["05", "030102010471000000"],
    ],
  );
  assert.equal(rows.at(-1).DE_02002, "第四百七十一条 单一自然段。");
});

test("Markdown article headings are parsed without creating an empty paragraph", () => {
  const rows = extractLegalContentRows([
    "## 第一章 总则",
    "### **第一条**",
    "为了规范地方立法程序，制定本规定。",
    "### **第二条**",
    "本规定适用于本行政区域。",
  ].join("\n"));

  assert.deepEqual(
    rows.map((row) => [row.DE_02003, row.DE_02001, row.DE_02002]),
    [
      ["03", "000001000000000000", "第一章 总则"],
      ["05", "000001000001000000", "第一条 为了规范地方立法程序，制定本规定。"],
      ["05", "000001000002000000", "第二条 本规定适用于本行政区域。"],
    ],
  );
});

test("Markdown table-of-contents hierarchy entries are not emitted as body structure", () => {
  const rows = extractLegalContentRows([
    "## 目 录",
    "- 第一章 总则",
    "- 第二章 附则",
    "---",
    "## 第一章 总则",
    "### **第一条**",
    "正文。",
    "## 第二章 附则",
    "### **第二条**",
    "本法自公布之日起施行。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(
    rows.filter((row) => row.DE_02003 === "03").map((row) => row.DE_02002),
    ["第一章 总则", "第二章 附则"],
  );
});

test("a Markdown table of contents without a separator ends when its first hierarchy repeats", () => {
  const rows = extractLegalContentRows([
    "目　　录",
    "## 第一章　总　则",
    "### 第一节　一般规定",
    "## 第二章　附　则",
    "### 第一节　一般规定",
    "## 第一章　总　则",
    "### **第一条**",
    "正文。",
    "## 第二章　附　则",
    "### **第二条**",
    "施行条款。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(
    rows.filter((row) => row.DE_02003 === "03").map((row) => row.DE_02002),
    ["第一章　总　则", "第二章　附　则"],
  );
  assert.deepEqual(rows.filter((row) => row.DE_02003 === "04"), []);
});

test("an unlabeled leading chapter list is discarded when body chapter numbering restarts", () => {
  const rows = extractLegalContentRows([
    "- 第一章　总则",
    "- 第二章　管理",
    "- 第三章　附则",
    "---",
    "## 第一章　总则",
    "### **第一条**",
    "正文。",
    "## 第二章　管理",
    "### **第二条**",
    "管理条款。",
    "## 第三章　附则",
    "### **第三条**",
    "施行条款。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(
    rows.filter((row) => row.DE_02003 === "03").map((row) => row.DE_02002),
    ["第一章　总则", "第二章　管理", "第三章　附则"],
  );
});

test("an unlabeled chapter contents list restores later title-only body headings", () => {
  const rows = extractLegalContentRows([
    "## 第一章　总则",
    "## 第二章　居住登记",
    "## 第三章　法律责任",
    "## 总则",
    "第一条 总则正文。",
    "## 居住登记",
    "第二条 登记正文。",
    "## 第三章　法律责任",
    "第三条 责任正文。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(
    rows.filter((row) => row.DE_02003 === "03").map((row) => row.DE_02002),
    ["第一章　总则", "第二章　居住登记", "第三章　法律责任"],
  );
  assert.deepEqual(
    rows.filter((row) => row.DE_02003 === "05").map((row) => row.DE_02001),
    ["000001000001000000", "000002000002000000", "000003000003000000"],
  );
});

test("byte-equivalent repeated structure rows collapse without masking divergent content", () => {
  const identicalRows = extractLegalContentRows([
    "第一章 总则",
    "第一条 相同正文。",
    "第一章 总则",
    "第一条 相同正文。",
  ].join("\n"));
  assert.deepEqual(duplicateContentStructureCodes(identicalRows), []);
  assert.equal(identicalRows.length, 2);

  const divergentRows = extractLegalContentRows([
    "第一条 第一份正文。",
    "第一条 第二份正文。",
  ].join("\n"));
  assert.deepEqual(
    duplicateContentStructureCodes(divergentRows),
    ["000000000001000000"],
  );
});

test("sentence fragments beginning with a chapter reference are not hierarchy headings", () => {
  const rows = extractLegalContentRows([
    "第一章 总则",
    "第一条 依照本办法第二章规定的程序实施监督检查。",
    "第二章规定的程序不适用于紧急检查。",
    "第一章规定的危害国家安全罪以及其他犯罪",
    "第一章的第二条至第四条另有规定",
    "第一章第二节有关程序另有规定",
    "第二条 其他事项。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.equal(rows.filter((row) => row.DE_02003 === "03").length, 1);
  assert.match(
    rows.find((row) => row.DE_02003 !== "03" && row.DE_02004 === "1").DE_02002,
    /第二章规定的程序/,
  );
});

test("split chapter and section references remain inside the current article", () => {
  const rows = extractLegalContentRows([
    "第一章 总则",
    "第一百条 企业采购药品，应当符合本规范",
    "## 第二章",
    "### 第八节的相关规定。",
    "第一百零一条 其他要求。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.equal(rows.filter((row) => row.DE_02003 === "03").length, 1);
  assert.match(
    rows.find((row) => /企业采购药品/.test(row.DE_02002)).DE_02002,
    /本规范第二章第八节的相关规定/u,
  );
});

test("an article-number reference ending in de-guiding text remains in the current article", () => {
  const rows = extractLegalContentRows([
    "第八十九条 保证人应当履行保证义务，包括遵守第九十条",
    "第九十条的规定；发现违反规定的，应当及时报告。",
    "第九十条 公安机关可以责令被取保候审人遵守特定规定。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.match(rows.find((row) => /第九十条的规定/.test(row.DE_02002)).DE_02002, /第九十条的规定/);
  assert.equal(rows.at(-1).DE_02001, "000000000090000000");
});

test("a parenthesized item range reference is not parsed as a repeated item", () => {
  const rows = extractLegalContentRows([
    "第三十五条 下列人员可以参加选举：",
    "（一）第一类人员；",
    "（二）第二类人员；",
    "（三）第三类人员；",
    "（四）第四类人员。",
    "（一）至（三）项所列人员，在工作单位参加选举。",
    "（四）项所列人员，在所在地参加选举。",
    "第三十六条 其他规定。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.equal(rows.filter((row) => row.DE_02003 === "07").length, 4);
  assert.match(
    rows.find((row) => /至（三）项所列人员/.test(row.DE_02002)).DE_02002,
    /工作单位参加选举/,
  );
});

test("Markdown headings split from inline article references are rejoined", () => {
  const rows = extractLegalContentRows([
    "### **第八条**",
    "检测程序依照本办法执行。",
    "### **第九条**",
    "异地车辆按照本办法",
    "### **第八条**",
    "规定的程序执行。",
    "### **第十条**",
    "后续独立条文。",
  ].join("\n"));

  assert.deepEqual(
    rows.map((row) => [row.DE_02001, row.DE_02002]),
    [
      ["000000000008000000", "第八条 检测程序依照本办法执行。"],
      ["000000000009000000", "第九条 异地车辆按照本办法第八条规定的程序执行。"],
      ["000000000010000000", "第十条 后续独立条文。"],
    ],
  );
  assert.deepEqual(duplicateContentStructureCodes(rows), []);
});

test("parenthesized Arabic sublists stay inside the preceding mu element", () => {
  const rows = extractLegalContentRows([
    "第六条 申请条件如下：",
    "（一）车辆条件：",
    "1.车辆技术要求；",
    "2.车辆其他要求：",
    "（1）大型物件运输车辆；",
    "（2）冷藏保鲜车辆；",
    "（3）集装箱车辆。",
    "（二）驾驶人员条件：",
    "1.取得驾驶证。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(
    rows.map((row) => [row.DE_02003, row.DE_02001]),
    [
      ["06", "000000000006010000"],
      ["07", "000000000006010100"],
      ["08", "000000000006010101"],
      ["08", "000000000006010102"],
      ["07", "000000000006010200"],
      ["08", "000000000006010201"],
    ],
  );
  assert.match(rows[3].DE_02002, /（1）大型物件运输车辆；.*（3）集装箱车辆。/);
});

test("split references with paragraph qualifiers and article lists are rejoined", () => {
  const rows = extractLegalContentRows([
    "### **第七条**",
    "禁止行为。",
    "### **第八条**",
    "限制行为。",
    "### **第九条**",
    "责任条款。",
    "### **第十条**",
    "违反本办法",
    "### **第七条**",
    "、",
    "### **第八条**",
    "、",
    "### **第九条**",
    "规定的，依法处理。",
    "### **第十一条**",
    "违反本办法",
    "### **第十条**",
    "第一款规定的，责令改正。",
    "### **第十二条**",
    "违反本办法",
    "### **第十条**",
    "第二款、",
    "### **第九条**",
    "规定的，依法处理。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.match(rows.find((row) => row.DE_02004 === "10").DE_02002, /本办法第七条、第八条、第九条规定/);
  assert.match(rows.find((row) => row.DE_02004 === "11").DE_02002, /本办法第十条第一款规定/);
  assert.match(rows.find((row) => row.DE_02004 === "12").DE_02002, /本办法第十条第二款、第九条规定/);
});

test("adjacent article references split after a cited regulation title are rejoined", () => {
  const rows = extractLegalContentRows([
    "### **第十九条**",
    "转让项目，应当符合《条例》",
    "### **第二十条**",
    "、",
    "### **第二十一条**",
    "规定。转让项目的受让人应当具备资质。",
    "### **第二十条**",
    "商品房预售应当符合《条例》",
    "### **第二十三条**",
    "规定的条件。",
    "### **第二十一条**",
    "销售商品房应当公示法定事项。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(rows.map((entry) => entry.DE_02004), ["19", "20", "21"]);
  assert.match(rows[0].DE_02002, /《条例》第二十条、第二十一条规定/);
  assert.match(rows[1].DE_02002, /《条例》第二十三条规定/);
});

test("an embedded next item marker resets following subitem numbering", () => {
  const rows = extractLegalContentRows([
    "第二十四条 受管制项目如下：",
    "（十三）模拟和数字计算装置：",
    "1．第一项技术条件；",
    "2．第二项技术条件的（十四）模数转换器：",
    "1．第一项转换条件；",
    "2．第二项转换条件。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.ok(rows.some((row) => row.DE_02001 === "000000000024011401"));
  assert.ok(rows.some((row) => row.DE_02001 === "000000000024011402"));
});

test("an embedded next article marker after an item starts the next article", () => {
  const rows = extractLegalContentRows([
    "第四十二条 有下列行为之一的，予以处罚：",
    "（一）第一项行为；",
    "（二）第二项行为；  第四十三条 违反本条例规定，有下列行为之一的，予以处罚：",
    "（一）第三项行为；",
    "（二）第四项行为。",
    "第四十四条 其他规定。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(
    rows.filter((row) => row.DE_02003 === "07").map((row) => row.DE_02001),
    [
      "000000000042010100",
      "000000000042010200",
      "000000000043010100",
      "000000000043010200",
    ],
  );
});

test("an embedded next article marker inside an article line starts the next article", () => {
  const rows = extractLegalContentRows([
    "第六十四条 既有规定从其规定。第六十五条 有下列情形之一的，予以处理：",
    "（一）第一项情形；",
    "（二）第二项情形。第六十六条 主管部门有下列情形之一的，予以处理：",
    "（一）第三项情形；",
    "（二）第四项情形。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(
    [...new Set(rows.map((row) => row.DE_02001.slice(8, 12)))],
    ["0064", "0065", "0066"],
  );
});

test("content structure overflow is blocking instead of wrapping or truncating", () => {
  const body = [
    "第一条 第一段。",
    ...Array.from({ length: 99 }, (_, index) => `后续自然段${index + 2}。`),
  ].join("\n");
  assert.throws(
    () => extractLegalContentRows(body),
    /CONTENT_PARAGRAPH_OVERFLOW/,
  );
});

test("a long Markdown table is preserved as one paragraph instead of overflowing paragraph codes", () => {
  const tableRows = [
    "| 序号 | 项目 |",
    "| --- | --- |",
    ...Array.from({ length: 101 }, (_, index) => `| ${index + 1} | 项目${index + 1} |`),
  ];
  const rows = extractLegalContentRows([
    "### 第一条",
    "适用项目见下表：",
    ...tableRows,
    "### 第二条",
    "本规定自公布之日起施行。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.equal(rows.filter((row) => row.DE_02001.slice(8, 12) === "0001").length, 2);
  assert.match(rows.map((row) => row.DE_02002).join("\n"), /\| 101 \| 项目101 \|/u);
});

test("an unnumbered schedule after the final effective clause is not counted as article paragraphs", () => {
  const rows = extractLegalContentRows([
    "### 第五十一条",
    "本办法自2024年3月1日起施行，旧办法同时废止。",
    "中央企业安全生产监管分类名单",
    ...Array.from({ length: 101 }, (_, index) => `企业${index + 1}`),
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].DE_02004, "51");
  assert.doesNotMatch(rows[0].DE_02002, /企业101/u);
});

test("inserted articles with the same numeric article code remain blocking", () => {
  const rows = extractLegalContentRows(
    [
      "第一百二十条 原条文。",
      "第一百二十条 之一 新增条文。",
    ].join("\n"),
  );
  assert.deepEqual(
    duplicateContentStructureCodes(rows),
    ["000000000120000000"],
  );
});

test("a backward bare article heading inside an unfinished sentence is discarded as carrier noise", () => {
  const rows = extractLegalContentRows([
    "### **第七条**",
    "在下列地区扩建房屋，除特殊情况，经审核符合本规定",
    "### **第三条**",
    "条件、批准建设二层楼房的外，一般不得建设二层以上楼房。",
    "### **第八条**",
    "应当按照许可证施工。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(rows.map((entry) => entry.DE_02004), ["7", "8"]);
  assert.match(rows[0].DE_02002, /符合本规定第三条条件、批准建设二层楼房/);
});

test("a forward-jump bare article heading inside an unfinished sentence is discarded when the expected next article follows", () => {
  const rows = extractLegalContentRows([
    "### **第二条**",
    "本规定所称文件材料，是指本规定",
    "### **第十条**",
    "规定应当归档而尚未归档的文字、声像材料及物品。",
    "### **第三条**",
    "本规定适用于本行政区域。",
    "### **第十条**",
    "国有企业在公务活动中形成的材料应当归档。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(rows.map((entry) => entry.DE_02004), ["2", "3", "10"]);
  assert.match(rows[0].DE_02002, /本规定所称文件材料.*本规定第十条规定应当归档/);
});

test("a forward-jump reference after an unquoted legal title is rejoined", () => {
  const rows = extractLegalContentRows([
    "### **第十二条**",
    "符合政府采购法",
    "### **第二十二条**",
    "第一款规定条件的供应商可以加入供应商库。",
    "### **第十三条**",
    "供应商应当提交响应文件。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(rows.map((entry) => entry.DE_02004), ["12", "13"]);
  assert.match(rows[0].DE_02002, /政府采购法第二十二条第一款规定/);
});

test("a backward reference followed by a forward article list does not corrupt sequence tracking", () => {
  const rows = extractLegalContentRows([
    "### **第二十七条**",
    "采购项目按照本办法",
    "### **第四条**",
    "批准后实施；符合本款情形的，本办法",
    "### **第三十三条**",
    "、",
    "### **第三十五条**",
    "中规定的最低数量可以为两家。",
    "### **第二十八条**",
    "后续独立条文。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(rows.map((entry) => entry.DE_02004), ["27", "28"]);
  assert.match(rows[0].DE_02002, /本办法第四条批准后实施/);
  assert.match(rows[0].DE_02002, /本办法第三十三条、第三十五条中规定/);
});

test("an out-of-sequence linked article is rejoined when the expected next article follows", () => {
  const rows = extractLegalContentRows([
    "### **第十条**",
    "申请人应当遵守",
    "### **第五条**",
    "规定的程序。",
    "### **第十一条**",
    "后续独立条文。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(rows.map((entry) => entry.DE_02004), ["10", "11"]);
  assert.match(rows[0].DE_02002, /遵守第五条规定的程序/);
});

test("a backward inline article qualifier remains content of the current article", () => {
  const rows = extractLegalContentRows([
    "### **第四十五条**",
    "第四十四条所称可以改正的情形包括下列事项。",
    "### **第四十六条**",
    "第四十四条规定的其他情形另行处理。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(rows.map((entry) => entry.DE_02004), ["45", "46"]);
  assert.match(rows[0].DE_02002, /第四十四条所称/);
  assert.match(rows[1].DE_02002, /第四十四条规定/);
});

test("an expected-number reference immediately before the actual article is rejoined", () => {
  const rows = extractLegalContentRows([
    "### **第十一条**",
    "采购人自行组织招标必须符合本办法",
    "### **第十二条**",
    "规定的条件。",
    "### **第十二条**",
    "采购人符合下列条件的，可以自行组织招标。",
    "### **第十三条**",
    "后续条文。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(rows.map((entry) => entry.DE_02004), ["11", "12", "13"]);
  assert.match(rows[0].DE_02002, /本办法第十二条规定的条件/);
});

test("an expected next article reference followed by further cited articles is rejoined", () => {
  const rows = extractLegalContentRows([
    "### **第三条**",
    "不得有下列行为：（一）属于商标法",
    "### **第四条**",
    "规定的不以使用为目的恶意申请注册；（二）属于商标法",
    "### **第十三条**",
    "规定的其他情形。",
    "### **第四条**",
    "商标代理机构应当遵循诚实信用原则。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.equal(rows.at(-1).DE_02001, "000000000004000000");
  assert.match(rows[0].DE_02002, /商标法第四条规定的.*商标法第十三条规定的/u);
});

test("split article references with conjunction continuations are rejoined", () => {
  const rows = extractLegalContentRows([
    "### **第二十二条**",
    "申请人除依照本办法",
    "### **第二十三条**",
    "或者",
    "### **第二十四条**",
    "的规定提供担保外，还应提交申请书。",
    "### **第二十三条**",
    "申请人应当提供足额担保。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(rows.map((row) => row.DE_02004), ["22", "23"]);
  assert.match(rows[0].DE_02002, /第二十三条或者第二十四条的规定/u);
});

test("a chain of forward article references before the expected next article is rejoined", () => {
  const rows = extractLegalContentRows([
    "### **第十七条**",
    "项目单位应当取得",
    "### **第二十二条**",
    "规定依法应当附具的文件后，按照本办法",
    "### **第二十三条**",
    "规定报送。",
    "### **第十八条**",
    "项目单位对材料真实性负责。",
    "### **第二十二条**",
    "项目单位报送申请报告时应当附具批准文件。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(rows.map((row) => row.DE_02004), ["17", "18", "22"]);
  assert.match(rows[0].DE_02002, /取得第二十二条规定.*本办法第二十三条规定报送/u);
});

test("article references after an aliased regulation title are rejoined", () => {
  const rows = extractLegalContentRows([
    "### **第一条**",
    "依照《中华人民共和国专利法实施细则》（以下简称专利法实施细则）",
    "### **第二条**",
    "和",
    "### **第十五条**",
    "第二款，制定本规定。",
    "### **第二条**",
    "申请人应当签订用户协议。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(rows.map((row) => row.DE_02004), ["1", "2"]);
  assert.match(rows[0].DE_02002, /实施细则）第二条和第十五条第二款/u);
});

test("an expected article reference after ben-guicheng is rejoined", () => {
  const rows = extractLegalContentRows([
    "### **第四条**",
    "除本规程",
    "### **第五条**",
    "另有规定外，可以申请行政复议。",
    "### **第五条**",
    "下列情形不能申请行政复议。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(rows.map((row) => row.DE_02004), ["4", "5"]);
  assert.match(rows[0].DE_02002, /除本规程第五条另有规定外/u);
});

test("an expected article reference in an unfinished sentence is rejoined before its real heading", () => {
  const rows = extractLegalContentRows([
    "### **第四十条**",
    "备案时附",
    "### **第四十一条**",
    "要求的相关文件。",
    "### **第四十一条**",
    "增加国际二字时应当报送批准文件。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(rows.map((row) => row.DE_02004), ["40", "41"]);
  assert.match(rows[0].DE_02002, /附第四十一条要求的相关文件/u);
});

test("an expected article list is rejoined before the first real heading", () => {
  const rows = extractLegalContentRows([
    "### **第二条**",
    "连续工作时间和",
    "### **第三条**",
    "、",
    "### **第四条**",
    "中所称累计工作时间均按工作年限计算。",
    "### **第三条**",
    "探亲假不计入年休假。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(rows.map((row) => row.DE_02004), ["2", "3"]);
  assert.match(rows[0].DE_02002, /第三条、第四条中所称/u);
});

test("a previously seen article followed by item qualifiers remains a reference", () => {
  const rows = extractLegalContentRows([
    "### **第三十条**",
    "城市排水设施由维护单位管理。",
    "### **第三十一条**",
    "维护单位应当履行职责；",
    "### **第三十条**",
    "第二、三项规定的单位还应接受业务指导。",
    "### **第三十二条**",
    "主管部门定期监督检查。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(rows.map((row) => row.DE_02004), ["30", "31", "32"]);
  assert.match(rows[1].DE_02002, /第三十条第二、三项规定/u);
});

test("an expected article qualifier remains a reference even after terminal punctuation", () => {
  const rows = extractLegalContentRows([
    "### **第四条**",
    "违反本规定的，按下列情形处罚：",
    "### **第五条**",
    "第（一）、（二）项规定的，给予警告。",
    "### **第五条**",
    "本规定由主管部门解释。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(rows.map((row) => row.DE_02004), ["4", "5"]);
  assert.match(rows[0].DE_02002, /第五条第（一）、（二）项规定/u);
});

test("a leading quoted official synopsis is not emitted when structured body headings follow", () => {
  const rows = extractLegalContentRows([
    "# 某管理规定",
    "> 第一条摘要用半角标点,制定本规定。第二条摘要内容。",
    "### 第一条",
    "正文使用规范标点，制定本规定。",
    "### 第二条",
    "正文内容。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(rows.map((row) => row.DE_02004), ["1", "2"]);
  assert.doesNotMatch(rows[0].DE_02002, /摘要/u);
});

test("an article number embedded in a cited agreement title remains inline", () => {
  const rows = extractLegalContentRows([
    "### **第六条**",
    "本办法所称区域贸易协定，是指《亚太贸易协定第二修正案",
    "### **第7条** 的协定》。",
    "### **第七条**",
    "原产货物应当符合相关标准。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.equal(rows.at(-1).DE_02004, "7");
  assert.match(rows.map((row) => row.DE_02002).join(""), /第7条\s*的协定/u);
});

test("article references immediately after an empty article heading remain its content", () => {
  const rows = extractLegalContentRows([
    "### **第九条**",
    "",
    "### **第七条**",
    "和",
    "### **第八条**",
    "所述登记者应当办理登记。",
    "### **第十条**",
    "后续独立条文。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(rows.map((entry) => entry.DE_02004), ["9", "10"]);
  assert.match(rows[0].DE_02002, /第九条\s*第七条和第八条所述登记者/);
});

test("article-free rules expose consecutive top-level Chinese items", () => {
  const rows = extractLegalContentRows([
    "# 关于划定隔离带的规定",
    "为了加强管理，作如下规定： 一、隔离带范围。（一）风景河道。 二、隔离带应当绿化。 三、不得建设生产用房。 四、现有建筑逐步调整。 五、违法建设依法处理。 六、郊区另作补充规定。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(
    rows.map((entry) => [entry.DE_02003, entry.DE_02001, entry.DE_02004]),
    [
      ["07", "000000000000010100", "1"],
      ["07", "000000000000010200", "2"],
      ["07", "000000000000010300", "3"],
      ["07", "000000000000010400", "4"],
      ["07", "000000000000010500", "5"],
      ["07", "000000000000010600", "6"],
    ],
  );
});

test("a multi-instrument modification decision is structured by its own top-level items", () => {
  const rows = extractLegalContentRows([
    "一、将《甲条例》",
    "### **第八条**",
    "修改为新的甲条例条文。",
    "二、将《乙条例》",
    "### **第八条**",
    "修改为新的乙条例条文。",
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.deepEqual(
    rows.map((entry) => [entry.DE_02003, entry.DE_02001, entry.DE_02004]),
    [
      ["07", "000000000000010100", "1"],
      ["07", "000000000000010200", "2"],
    ],
  );
});

test("an explicit Markdown attachment heading ends article structure parsing", () => {
  const attachmentLines = Array.from(
    { length: 110 },
    (_, index) => `附件说明第${index + 1}行。`,
  );
  const rows = extractLegalContentRows([
    "### 第一百六十条",
    "本法规定的权利义务继续有效。",
    "---",
    "### 附件一",
    "行政长官的产生办法",
    ...attachmentLines,
  ].join("\n"));

  assert.deepEqual(duplicateContentStructureCodes(rows), []);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].DE_02004, "160");
  assert.doesNotMatch(rows[0].DE_02002, /附件说明/u);
});

test("FLK fulltext registry loads only traceable rows and exposes verified carriers", async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "flk-fulltext-"));
  const csvPath = path.join(directory, "verification.csv");
  fs.writeFileSync(
    csvPath,
    [
      "relative_path,bbbs,official_url,official_file_relative_path,official_carrier_sha256,official_text_sha256,local_text_sha256,official_text_length,local_text_length,official_block_coverage,verification_status,verified_at,error",
      "01/a.md,abc,https://flk/a,documents/abc.docx,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb,cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc,100,100,1,FULLTEXT_VERIFIED,2026-07-30T00:00:00+0800,",
      "01/b.md,def,https://flk/b,,,,,,,0,FULLTEXT_MISMATCH,2026-07-30T00:00:00+0800,mismatch",
    ].join("\n"),
    "utf8",
  );
  const registry = await loadFlkFulltextRegistry(csvPath);
  assert.equal(registry.rowCount, 2);
  assert.equal(registry.byVersionId.get("abc").verification_status, "FULLTEXT_VERIFIED");
  assert.equal(registry.byRelativePath.get("01/b.md").verification_status, "FULLTEXT_MISMATCH");
});
