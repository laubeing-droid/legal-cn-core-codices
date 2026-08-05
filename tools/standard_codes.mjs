const ELECTRONIC_DOCUMENT_CATEGORIES = new Set([
  "0000", "0100", "0200", "0300", "0400", "0500", "0600", "0700",
  "0800", "0901", "0902", "0903", "1000", "1100", "1200", "1300",
  "1400", "1500", "1600", "1700", "1800", "1900", "2000", "2100",
]);
const GBT47277_CATEGORIES = new Set(
  [...ELECTRONIC_DOCUMENT_CATEGORIES].filter((code) => Number(code) <= 1500),
);
const ELECTRONIC_FILE_CATEGORIES = new Set(
  [0, 1, 2, 3, 4].flatMap((tens) =>
    [0, 1, 2, 3, 4, 5].map((ones) => `${tens}${ones}`)),
);
const GBT47277_FILE_TYPES = new Set(["00", "10", "20", "30", "40"]);

function validDate(value) {
  if (!/^\d{8}$/.test(value)) return false;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year
    && date.getUTCMonth() === month - 1
    && date.getUTCDate() === day;
}

function validateParts(parts, { categories, fileTypes }) {
  const errors = [];
  if (!categories.has(parts.category)) errors.push("INVALID_CATEGORY");
  if (!/^\d{10}$/.test(parts.agency)) errors.push("INVALID_AGENCY");
  if (!validDate(parts.promulgationDate)) errors.push("INVALID_PROMULGATION_DATE");
  if (!/^\d{4}$/.test(parts.sequence)) errors.push("INVALID_SEQUENCE");
  if (!/^\d{3}$/.test(parts.internalSequence)) errors.push("INVALID_INTERNAL_SEQUENCE");
  if (!fileTypes.has(parts.fileType ?? parts.fileCategory)) errors.push("INVALID_FILE_TYPE");
  return errors;
}

function concatenateParts(parts, finalField) {
  return [
    parts.category,
    parts.agency,
    parts.promulgationDate,
    parts.sequence,
    parts.internalSequence,
    parts[finalField],
  ].join("");
}

export function buildElectronicDocumentBody(parts) {
  const errors = validateParts(parts, {
    categories: ELECTRONIC_DOCUMENT_CATEGORIES,
    fileTypes: ELECTRONIC_FILE_CATEGORIES,
  });
  if (errors.length) throw new Error(errors.join("|"));
  return concatenateParts(parts, "fileCategory");
}

export function buildWjbs(parts) {
  return `1.2.156.3005.6-${buildElectronicDocumentBody(parts)}`;
}

export function build47277FileCode(parts) {
  if (ELECTRONIC_DOCUMENT_CATEGORIES.has(parts.category)
      && !GBT47277_CATEGORIES.has(parts.category)) {
    throw new Error("CATEGORY_OUTSIDE_GBT47277");
  }
  const errors = validateParts(parts, {
    categories: GBT47277_CATEGORIES,
    fileTypes: GBT47277_FILE_TYPES,
  });
  if (errors.length) throw new Error(errors.join("|"));
  return concatenateParts(parts, "fileType");
}

export function validate47277FileCode(value) {
  if (!/^\d{31}$/.test(value)) return ["INVALID_47277_FILE_CODE_FORMAT"];
  const parts = {
    category: value.slice(0, 4),
    agency: value.slice(4, 14),
    promulgationDate: value.slice(14, 22),
    sequence: value.slice(22, 26),
    internalSequence: value.slice(26, 29),
    fileType: value.slice(29, 31),
  };
  return validateParts(parts, {
    categories: GBT47277_CATEGORIES,
    fileTypes: GBT47277_FILE_TYPES,
  });
}

export function validateWjbs(value, { sourceType = "" } = {}) {
  const errors = [];
  const match = /^1\.2\.156\.3005\.6-(\d{31})$/.exec(value);
  if (!match) return ["INVALID_WJBS_FORMAT"];
  const body = match[1];
  const parts = {
    category: body.slice(0, 4),
    agency: body.slice(4, 14),
    promulgationDate: body.slice(14, 22),
    sequence: body.slice(22, 26),
    internalSequence: body.slice(26, 29),
    fileCategory: body.slice(29, 31),
  };
  errors.push(...validateParts(parts, {
    categories: ELECTRONIC_DOCUMENT_CATEGORIES,
    fileTypes: ELECTRONIC_FILE_CATEGORIES,
  }));
  if (!new Set(["AUTHORITY_ISSUED", "STANDARD_DERIVED_LOCAL"]).has(sourceType)) {
    errors.push("WJBS_PROVENANCE_MISSING");
  }
  return errors;
}

function fixedWidth(value, width, field) {
  const number = Number(value);
  if (!Number.isInteger(number) || number < 0 || number >= 10 ** width) {
    throw new Error(`INVALID_${field.toUpperCase()}`);
  }
  return String(number).padStart(width, "0");
}

export function buildContentStructureCode(parts) {
  return [
    fixedWidth(parts.book, 2, "book"),
    fixedWidth(parts.subBook, 2, "sub_book"),
    fixedWidth(parts.chapter, 2, "chapter"),
    fixedWidth(parts.section, 2, "section"),
    fixedWidth(parts.article, 4, "article"),
    fixedWidth(parts.paragraph, 2, "paragraph"),
    fixedWidth(parts.item, 2, "item"),
    fixedWidth(parts.subItem, 2, "sub_item"),
  ].join("");
}

export function validateContentStructureCode(value) {
  return /^\d{18}$/.test(value) ? [] : ["INVALID_CONTENT_STRUCTURE_CODE"];
}

export function composeLegalProvisionCode(fileCode, contentCode) {
  const errors = [
    ...validate47277FileCode(fileCode),
    ...validateContentStructureCode(contentCode),
  ];
  if (errors.length) throw new Error(errors.join("|"));
  return `${fileCode}${contentCode}`;
}

export function isOfficialCaseId(value) {
  const text = String(value ?? "").trim();
  if (!text || /^ima-/i.test(text) || /^[0-9a-f]{32,64}$/i.test(text)) return false;
  if (/^\d{4}[-./]\d{1,2}[-./]\d{1,2}$/.test(text)) return false;
  if (/^(?:检例第|指导案例)\d+号$/.test(text)) return true;
  if (/^D?\d{4}(?:-\d{1,3}){3}-\d{3}$/.test(text)) return true;
  return /^[A-Z]{5,8}\d{10}$/.test(text);
}

export const STANDARD_CODE_SETS = Object.freeze({
  electronicDocumentCategories: [...ELECTRONIC_DOCUMENT_CATEGORIES],
  gbt47277Categories: [...GBT47277_CATEGORIES],
  electronicFileCategories: [...ELECTRONIC_FILE_CATEGORIES],
  gbt47277FileTypes: [...GBT47277_FILE_TYPES],
  effectCodes: ["01", "02", "03", "04", "05"],
});
