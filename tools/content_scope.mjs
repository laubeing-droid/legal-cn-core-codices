export function fragmentDescriptor(relativePath) {
  const filename = String(relativePath ?? "").replaceAll("\\", "/").split("/").at(-1) ?? "";
  const match = filename.match(/^(.*?)-(\d{2})-.*共(\d+)册.*\.md$/i);
  if (!match) return null;
  return {
    baseTitle: match[1],
    part: Number(match[2]),
    total: Number(match[3]),
  };
}

function isAttachmentOnlyIndex(body) {
  const contentLines = String(body ?? "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !/^#{1,6}\s/.test(line) && !/^>/.test(line));
  if (contentLines.length === 0) return false;
  const content = contentLines.join(" ");
  const attachmentPattern = /\S+\.(?:pdf|ofd|docx?|xlsx?)(?=\s|$)/gi;
  const attachments = content.match(attachmentPattern) ?? [];
  if (attachments.length === 0) return false;
  return content.replace(attachmentPattern, "").replace(/[、，,；;]+/g, "").trim() === "";
}

export function classifySourceContent(relativePath, title = "", body = "") {
  if (fragmentDescriptor(relativePath)) return "legal_fragment";
  if (
    /WZWS_CONFIRM_PREFIX_LABEL/.test(body)
    || /Please enable JavaScript and refresh the page[\s\S]{0,500}<script/i.test(body)
  ) return "blocked_access_content";
  if (isAttachmentOnlyIndex(body)) return "official_attachment_index";
  const filename = String(relativePath ?? "")
    .replaceAll("\\", "/")
    .split("/")
    .at(-1) ?? "";
  if (
    /^_地方政府规章_/i.test(filename)
    && /^#{1,6}\s*/.test(String(title ?? ""))
  ) return "unidentified_fulltext_carrier";
  const parts = String(relativePath ?? "").replaceAll("\\", "/").split("/");
  const root = parts[0] ?? "";
  const branch = parts[1] ?? "";
  if (root.startsWith("02_") && branch.startsWith("02_")) {
    if (/典型(?:案例|案件)/.test(title)) return "case";
    if (
      /年度报告|批准撤销、设立(?:、(?:更名|变更))?(?:的)?人民法院|宁波海事法院设立|关于人民法院处理涉台民事案件的几个法律问题|^最高人民法院发出通知要求/.test(title)
    ) return "practice_reference";
    if (/（续）|\(续\)/.test(title)) return "legal_fragment";
  }
  if (
    root.startsWith("01_")
    || (root.startsWith("02_") && /^(01|02)_/.test(branch))
    || (root.startsWith("03_") && /^(01|02)_/.test(branch))
  ) return "legal_document";
  if (
    (root.startsWith("02_") && /^(06|07|09|10)_/.test(branch))
    || (root.startsWith("03_") && /^(04|05)_/.test(branch))
    || (root.startsWith("04_") && /^01_/.test(branch))
  ) return "case";
  if (root.startsWith("02_") && /^(03|04|05)_/.test(branch)) {
    return "practice_reference";
  }
  return "other_reference";
}
