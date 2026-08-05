const ORDINAL = "[0-9〇零一二两三四五六七八九十百千万]+";
const articleLinePattern = new RegExp(`^第${ORDINAL}条(?:\\s|　|$)`);
const legalTitleTailPattern = /(?:法|条例|办法|规定|规则|决定|通知|方案|细则|意见|通则|章程|修正案)$/u;
const sentencePunctuationPattern = /[。！？；]/u;

function cleanMarkdownLine(value) {
  return String(value ?? "")
    .replace(/^\s{0,3}#{1,6}\s*/, "")
    .replace(/^\s*(?:[-*+]\s+|\d+[.)、]\s+)/, "")
    .replace(/^\s*>\s?/, "")
    .replace(/\*\*|__|`/g, "")
    .trim();
}

function firstTrailingLegalTitle(lines, startIndex) {
  const meaningful = [];
  for (let index = startIndex; index < lines.length && meaningful.length < 2; index += 1) {
    const line = cleanMarkdownLine(lines[index]);
    if (line) meaningful.push(line);
  }
  if (!meaningful.length) return "";
  for (const candidate of [meaningful[0], meaningful.join("")]) {
    if (/^(?:附件|附录|附表|目录)(?:[：:]|$)/u.test(candidate)) continue;
    if (candidate.length < 4 || candidate.length > 100) continue;
    if (sentencePunctuationPattern.test(candidate)) continue;
    if (legalTitleTailPattern.test(candidate)) return candidate;
  }
  return "";
}

export function extractPrimaryLegalDocumentBody(markdown) {
  const source = String(markdown ?? "");
  const lines = source.split(/\r?\n/);
  let hasArticleBeforeSeparator = false;
  for (let index = 0; index < lines.length; index += 1) {
    const line = cleanMarkdownLine(lines[index]);
    if (articleLinePattern.test(line)) hasArticleBeforeSeparator = true;
    if (!/^\s*---\s*$/.test(lines[index]) || !hasArticleBeforeSeparator) continue;
    const trailingTitle = firstTrailingLegalTitle(lines, index + 1);
    if (!trailingTitle) continue;
    return {
      body: lines.slice(0, index).join("\n").trim(),
      truncated: true,
      trailingTitle,
      removedLineCount: lines.length - index,
    };
  }
  return {
    body: source,
    truncated: false,
    trailingTitle: "",
    removedLineCount: 0,
  };
}
