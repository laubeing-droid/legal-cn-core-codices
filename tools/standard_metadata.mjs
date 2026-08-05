function validCalendarDate(year, month, day) {
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year
    && date.getUTCMonth() === month - 1
    && date.getUTCDate() === day;
}

export function normalizeSourceDate(value) {
  const text = String(value ?? "").trim().normalize("NFKC");
  const separated = text.match(
    /(?<!\d)(\d{4})\s*[-./年]\s*(\d{1,2})\s*[-./月]\s*(\d{1,2})\s*日?(?!\d)/,
  );
  const compact = separated
    ? null
    : text.match(/(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)/);
  const match = separated ?? compact;
  if (!match) return text;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (!validCalendarDate(year, month, day)) return text;
  return [
    String(year).padStart(4, "0"),
    String(month).padStart(2, "0"),
    String(day).padStart(2, "0"),
  ].join("-");
}

export function deriveCompleteDate(value) {
  const normalized = normalizeSourceDate(value);
  const match = normalized.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return "";
  return validCalendarDate(Number(match[1]), Number(match[2]), Number(match[3]))
    ? normalized
    : "";
}

export function normalizeRequiredDate(value) {
  const complete = deriveCompleteDate(value);
  return complete ? complete.replaceAll("-", "") : "";
}

export function deriveExplicitEffectiveDate(value) {
  const dates = new Set();
  const pattern = /(?:本法|本条例|本办法|本规定|本细则|本清单|本决定|本规则|本标准|本通知)\s*自\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*起\s*(?:施行|实施)/gu;
  for (const match of String(value ?? "").normalize("NFKC").matchAll(pattern)) {
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    if (!validCalendarDate(year, month, day)) continue;
    dates.add(
      `${String(year).padStart(4, "0")}${String(month).padStart(2, "0")}${String(day).padStart(2, "0")}`,
    );
  }
  return dates.size === 1 ? [...dates][0] : "";
}

const CATEGORY_BY_NAME = new Map([
  ["宪法", "0000"],
  ["法律", "0100"],
  ["有关法律问题和重大问题的决定", "0200"],
  ["有关法律问题和重大问题的决定（部分）", "0200"],
  ["法律解释", "0300"],
  ["行政法规", "0400"],
  ["军事法规", "0500"],
  ["监察法规", "0600"],
  ["地方性法规", "0700"],
  ["地方法规", "0700"],
  ["自治条例和单行条例", "0800"],
  ["经济特区法规", "0901"],
  ["浦东新区法规", "0902"],
  ["海南自由贸易港法规", "0903"],
  ["法规性决定", "1000"],
  ["司法解释", "1100"],
  ["军事规章", "1200"],
  ["部门规章", "1300"],
  ["地方政府规章", "1400"],
  ["特别行政区本地法律", "1500"],
  ["人大规范性文件", "1600"],
  ["行政规范性文件", "1700"],
  ["国家级行政规范性文件", "1700"],
  ["地方行政规范性文件", "1700"],
  ["军事规范性文件", "1800"],
  ["监察规范性文件", "1900"],
  ["法院规范性文件", "2000"],
  ["法院司法规范性文件", "2000"],
  ["法院司法规范性文件候选", "2000"],
  ["检察院规范性文件", "2100"],
  ["检察规范性文件", "2100"],
]);
const LEGACY_EFFECT_BY_NAME = new Map([
  ["有效", "01"],
  ["现行有效", "01"],
  ["现行适用", "01"],
  ["尚未生效", "02"],
  ["尚未施行", "02"],
  ["已修改", "03"],
  ["已废止", "04"],
  ["废止", "04"],
  ["已失效", "05"],
  ["失效", "05"],
]);

export function deriveEffectCode(value) {
  return LEGACY_EFFECT_BY_NAME.get(String(value ?? "").trim()) ?? "";
}

function text(value) {
  if (Array.isArray(value)) return value.find(Boolean)?.trim() ?? "";
  return String(value ?? "").trim();
}

function first(meta, keys) {
  for (const key of keys) {
    const value = text(meta[key]);
    if (value) return value;
  }
  return "";
}

function pathCategory(relativePath) {
  const parts = relativePath.replaceAll("\\", "/").split("/");
  const root = parts[0] ?? "";
  const branch = parts[1] ?? "";
  const subBranch = parts[2] ?? "";
  if (root.startsWith("01_") && branch.startsWith("01_")) return "0100";
  if (root.startsWith("01_") && branch.startsWith("02_")) return "0400";
  if (root.startsWith("01_") && branch.startsWith("03_") && subBranch.startsWith("01_")) {
    return "0700";
  }
  if (root.startsWith("01_") && branch.startsWith("03_") && subBranch.startsWith("02_")) {
    return "0800";
  }
  if (root.startsWith("01_") && branch.startsWith("03_") && subBranch.startsWith("03_")) {
    return "0901";
  }
  if (root.startsWith("01_") && branch.startsWith("04_") && subBranch.startsWith("01_")) {
    return "1300";
  }
  if (root.startsWith("01_") && branch.startsWith("04_") && subBranch.startsWith("02_")) {
    return "1400";
  }
  if (root.startsWith("01_") && branch.startsWith("05_")) return "1700";
  if (root.startsWith("02_") && branch.startsWith("01_")) return "1100";
  if (root.startsWith("02_") && branch.startsWith("02_")) return "2000";
  if (root.startsWith("03_") && branch.startsWith("01_")) return "1100";
  if (root.startsWith("03_") && branch.startsWith("02_")) return "2100";
  return "";
}

export function deriveCategoryCode(meta, relativePath) {
  const declared = first(meta, [
    "FLFGDZWJFLDM",
    "法律法规电子文件分类代码",
    "group",
    "法律类型",
    "document_type",
    "文件类型",
  ]);
  if (/^\d{4}$/.test(declared)) return declared;
  if (CATEGORY_BY_NAME.has(declared)) return CATEGORY_BY_NAME.get(declared);
  return pathCategory(relativePath);
}

export function deriveAgencyName(
  meta,
  relativePath = "",
  title = "",
  categoryCode = "",
  areaRegistry = [],
) {
  const declared = first(meta, [
    "ZDJGMC",
    "author",
    "制定机关",
    "发布机关",
    "制定或修改机关名称",
  ]);
  const normalizedTitle = title.normalize("NFKC").trim().replace(/^《/, "");
  if (declared) {
    const normalizedDeclared = declared
      .split(/[,，、;；]/, 1)[0]
      .trim()
      .replace("人大常务委员会", "人民代表大会常务委员会")
      .replace("人大常委会", "人民代表大会常务委员会")
      .replace(/人大常委$/, "人民代表大会常务委员会")
      .replace(/常务委员会常务委员会$/, "常务委员会")
      .replace(/人民政府发布$/, "人民政府");
    if (categoryCode === "1400") {
      const label = normalizedDeclared
        .replace(/人民政府$/, "")
        .replace(/(?:市|州)$/, "");
      const candidates = areaRegistry.filter((area) =>
        area.name === normalizedDeclared
        || shortAreaName(area.name) === label
        || area.name.startsWith(label));
      const area = chooseArea(candidates, relativePath);
      if (area) return `${area.name}人民政府`;
    }
    if (["0700", "0800", "0901", "0902", "0903"].includes(categoryCode)) {
      const suffix = normalizedDeclared.includes("常委")
        || normalizedDeclared.includes("常务委员会")
        ? "人民代表大会常务委员会"
        : (normalizedDeclared.includes("人民代表大会") ? "人民代表大会" : "");
      if (suffix) {
        const candidates = areaRegistry.filter((area) => normalizedTitle.includes(area.name));
        if (candidates.length) {
          const longest = Math.max(...candidates.map((area) => area.name.length));
          const area = chooseArea(
            candidates.filter((candidate) => candidate.name.length === longest),
            relativePath,
          );
          if (area) return `${area.name}${suffix}`;
        }
      }
    }
    return normalizedDeclared;
  }
  const parts = relativePath.replaceAll("\\", "/").split("/");
  if (categoryCode === "1300") {
    const directory = parts[3] ?? "";
    if (directory.endsWith("规章") && directory.length > 2) {
      return directory.slice(0, -"规章".length);
    }
  }
  if (categoryCode === "1400" && title && areaRegistry.length) {
    const matching = areaRegistry.filter((area) => normalizedTitle.startsWith(area.name));
    if (matching.length) {
      const longest = Math.max(...matching.map((area) => area.name.length));
      const area = chooseArea(
        matching.filter((candidate) => candidate.name.length === longest),
        relativePath,
      );
      if (area) return `${area.name}人民政府`;
    }
  }
  if (
    ["1100", "2000"].includes(categoryCode)
    && normalizedTitle.startsWith("最高人民法院")
  ) {
    return "最高人民法院";
  }
  if (
    ["1100", "2100"].includes(categoryCode)
    && normalizedTitle.startsWith("最高人民检察院")
  ) {
    return "最高人民检察院";
  }
  return "";
}

function shortAreaName(value) {
  return value
    .replace(/(?:壮族|回族|维吾尔|蒙古族|藏族|朝鲜族|苗族|土家族)?自治区$/, "")
    .replace(/(?:特别行政区|自治州|地区|盟|省|市|县|区)$/, "");
}

function chooseArea(candidates, relativePath) {
  if (candidates.length === 1) return candidates[0];
  if (!relativePath) return null;
  const scored = candidates.map((candidate) => {
    const ancestors = candidate.path.split("/").slice(0, -1);
    const score = ancestors.filter((part) => {
      const short = shortAreaName(part);
      return short.length >= 2 && relativePath.includes(short);
    }).length;
    return { candidate, score };
  });
  const bestScore = Math.max(...scored.map((item) => item.score));
  const best = scored.filter((item) => item.score === bestScore && bestScore > 0);
  return best.length === 1 ? best[0].candidate : null;
}

function localAgencyCode(agencyName, areaRegistry, relativePath) {
  const suffixes = [
    ["人民代表大会常务委员会", "1001"],
    ["人民代表大会", "1000"],
    ["人民政府", "3000"],
  ];
  const matched = suffixes.find(([suffix]) => agencyName.endsWith(suffix));
  if (!matched) return "";
  const [suffix, agencySuffix] = matched;
  const areaName = agencyName.slice(0, -suffix.length);
  const candidates = areaRegistry.filter((area) =>
    area.name === areaName
    || shortAreaName(area.name) === areaName
    || areaName.endsWith(area.name));
  const area = chooseArea(candidates, relativePath);
  return area ? `${area.code}${agencySuffix}` : "";
}

export function deriveAgencyCode(
  agencyName,
  centralAgencyRegistry,
  areaRegistry = [],
  relativePath = "",
) {
  const normalizedAgencyName = agencyName.replace(/[（(](?:已撤销|撤销)[）)]$/, "");
  let suffix = centralAgencyRegistry.get(normalizedAgencyName);
  if (!suffix && normalizedAgencyName) {
    const aliases = [...centralAgencyRegistry.entries()].filter(([registeredName]) => {
      if (registeredName === normalizedAgencyName) return true;
      if (registeredName.startsWith(`${normalizedAgencyName}(`)) return true;
      if (!registeredName.endsWith(normalizedAgencyName)) return false;
      const prefix = registeredName.slice(0, -normalizedAgencyName.length);
      return prefix === "中华人民共和国" || prefix === "中国";
    });
    if (aliases.length === 1) suffix = aliases[0][1];
  }
  if (suffix && /^\d{4}$/.test(suffix)) return `000000${suffix}`;
  if (agencyName === "中华人民共和国国务院") {
    const stateCouncil = centralAgencyRegistry.get("国务院");
    return stateCouncil ? `000000${stateCouncil}` : "";
  }
  const officeMatch = agencyName.match(/^(.*?)人民政府(?:办公厅|办公室)$/);
  if (officeMatch) {
    const governmentCode = localAgencyCode(
      `${officeMatch[1]}人民政府`,
      areaRegistry,
      relativePath,
    );
    const officeSuffix = centralAgencyRegistry.get("中华人民共和国国务院办公厅")
      ?? centralAgencyRegistry.get("国务院办公厅");
    if (governmentCode && /^\d{4}$/.test(officeSuffix ?? "")) {
      return `${governmentCode.slice(0, 6)}${officeSuffix}`;
    }
  }
  return localAgencyCode(agencyName, areaRegistry, relativePath);
}

export function deriveNationalRuleAgencyName(
  officialRuleRecord,
  areaRegistry = [],
  relativePath = "",
) {
  if (officialRuleRecord?.publishers?.length !== 1) return "";
  const publisher = text(officialRuleRecord.publishers[0]);
  if (!publisher) return "";
  if (officialRuleRecord.category !== "地方政府规章") return publisher;
  if (/人民政府(?:办公厅|办公室)?$/.test(publisher)) return publisher;
  const candidates = areaRegistry.filter((area) =>
    area.name === publisher || shortAreaName(area.name) === publisher);
  const area = chooseArea(candidates, relativePath);
  return area ? `${area.name}人民政府` : publisher;
}

function parseOrdinal(raw) {
  if (/^\d{1,4}$/.test(raw)) return Number(raw);
  const digits = new Map([
    ["零", 0], ["〇", 0], ["一", 1], ["二", 2], ["两", 2], ["三", 3],
    ["四", 4], ["五", 5], ["六", 6], ["七", 7], ["八", 8], ["九", 9],
  ]);
  const units = new Map([["十", 10], ["百", 100], ["千", 1000]]);
  let total = 0;
  let current = 0;
  for (const character of raw) {
    if (digits.has(character)) {
      current = digits.get(character);
    } else if (units.has(character)) {
      total += (current || 1) * units.get(character);
      current = 0;
    } else {
      return Number.NaN;
    }
  }
  return total + current;
}

function sequenceFromText(value) {
  const patterns = [
    /〔\s*\d{4}\s*〕\s*([0-9一二两三四五六七八九十百千〇零]{1,8})\s*号/,
    /第\s*([0-9一二两三四五六七八九十百千〇零]{1,8})\s*号/,
    /(?:令|公告)\s*([0-9一二两三四五六七八九十百千〇零]{1,8})\s*号/,
    /第\s*([0-9一二两三四五六七八九十百千〇零]{1,8})\s*次会议/,
  ];
  for (const pattern of patterns) {
    const match = value.match(pattern);
    if (!match) continue;
    const number = parseOrdinal(match[1]);
    if (Number.isInteger(number) && number >= 0 && number <= 9999) {
      return String(number).padStart(4, "0");
    }
    return "";
  }
  return "";
}

export function deriveSequenceCode(meta, body) {
  const documentNumber = first(meta, [
    "FWZH",
    "document_number",
    "发文字号",
    "公布令号",
    "公告号",
    "文件号",
  ]);
  if (documentNumber) return sequenceFromText(documentNumber);
  const fromBody = sequenceFromText(String(body ?? "").slice(0, 3000));
  return fromBody || "0000";
}

export function deriveFileTypeCode(meta, title = "") {
  const explicit = first(meta, ["DE_01020", "文件类型代码"]);
  if (/^(?:[0-4][0-5])$/.test(explicit)) return explicit;
  const declared = first(meta, ["group", "法律类型", "document_type", "文件类型"]);
  const identity = `${declared}\n${String(title ?? "")}`;
  if (identity.includes("修正案")) return "10";
  if (identity.includes("批准决定")) return "20";
  if (identity.includes("决定") && /修改|废止/u.test(identity)) {
    return "30";
  }
  return "00";
}

function validIsoDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year
    && date.getUTCMonth() === month - 1
    && date.getUTCDate() === day;
}

export function deriveLegacyFilenameMetadata(relativePath) {
  const filename = (
    relativePath.replaceAll("\\", "/").split("/").at(-1) ?? ""
  ).normalize("NFKC");
  const match = filename.match(
    /_(\d{4}-\d{2}-\d{2})_(有效|尚未生效|尚未施行|已修改|已废止|失效|未知)(?:_[^/]+)?\.md$/i,
  );
  if (!match) return { promulgationDate: "", effectCode: "" };
  return {
    promulgationDate: validIsoDate(match[1]) ? match[1] : "",
    effectCode: LEGACY_EFFECT_BY_NAME.get(match[2]) ?? "",
  };
}
