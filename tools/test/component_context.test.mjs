import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  acceptedCodingComponentContext,
  componentKey,
  loadComponentContext,
  mergeComponentContexts,
} from "../component_context.mjs";

test("component context loads only complete coding groups", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "component-context-"));
  const csvPath = path.join(directory, "context.csv");
  fs.writeFileSync(csvPath, [
    "relative_path,category_code,agency_code,promulgation_date,sequence_code,file_type_code",
    "a.md,0700,1100001001,20200101,0001,00",
    "b.md,0700,,20200101,0001,00",
  ].join("\n"), "utf8");
  const context = loadComponentContext(csvPath);
  assert.deepEqual([...context.keys()], ["0700|1100001001|20200101|0001|00"]);
  assert.deepEqual([...context.values()].map((value) => [...value]), [["a.md"]]);
});

test("accepted WJBS and engineering context merge into one owner index", () => {
  const accepted = acceptedCodingComponentContext(new Map([["accepted.md", {
    WJBS: "1.2.156.3005.6-0700110000100120200101000100000",
  }]]));
  const key = componentKey({
    categoryCode: "0700",
    agencyCode: "1100001001",
    promulgationDate: "20200101",
    sequenceCode: "0001",
    fileTypeCode: "00",
  });
  const merged = mergeComponentContexts(accepted, new Map([[key, new Set(["blocked.md"])]]));
  assert.deepEqual([...merged.get(key)].sort(), ["accepted.md", "blocked.md"]);
});
