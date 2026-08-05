import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

function normalizedTitle(value) {
  return String(value ?? "")
    .normalize("NFKC")
    .replace(/[\s《》〈〉]/g, "")
    .replace(/[（(](?:试行|暂行)[）)]$/u, "")
    .toLowerCase();
}

export function loadDecisionOrderEvidenceRegistry(registryPath) {
  const raw = JSON.parse(fs.readFileSync(registryPath, "utf8").replace(/^\uFEFF/, ""));
  const entries = Array.isArray(raw.entries) ? raw.entries : [];
  const baseDir = path.dirname(registryPath);
  return entries.map((entry, index) => {
    const label = `决定顺序补证注册表第${index + 1}项`;
    if (!/^\d{10}$/.test(entry.agency_code ?? "")) throw new Error(`${label}机关代码无效。`);
    if (!/^\d{8}$/.test(entry.promulgation_date ?? "")) throw new Error(`${label}日期无效。`);
    if (!/^\d{4}$/.test(entry.sequence_code ?? "")) throw new Error(`${label}文号顺序码无效。`);
    if (!Array.isArray(entry.ordered_titles) || !entry.ordered_titles.length) {
      throw new Error(`${label}没有决定内题名顺序。`);
    }
    const decisionTitle = String(entry.decision_title ?? "").trim();
    const evidencePath = path.resolve(baseDir, entry.evidence_path ?? "");
    if (!fs.existsSync(evidencePath)) throw new Error(`${label}证据文件不存在。`);
    const digest = crypto.createHash("sha256").update(fs.readFileSync(evidencePath)).digest("hex");
    if (digest !== String(entry.source_sha256 ?? "").toLowerCase()) {
      throw new Error(`${label}证据SHA-256不一致。`);
    }
    if (!/^https?:\/\//.test(entry.official_url ?? "")) throw new Error(`${label}官方URL无效。`);
    const seen = new Set();
    const seenOrders = new Set();
    const orderedTitles = entry.ordered_titles.map((item, titleIndex) => {
      const title = typeof item === "string" ? item : item?.title;
      const order = typeof item === "string" ? titleIndex + 1 : Number(item?.order);
      const key = normalizedTitle(title);
      if (!key || seen.has(key)) throw new Error(`${label}题名为空或重复。`);
      if (!Number.isInteger(order) || order < 1 || order > 999 || seenOrders.has(order)) {
        throw new Error(`${label}决定内顺序无效或重复。`);
      }
      seen.add(key);
      seenOrders.add(order);
      return { title, normalizedTitle: key, order, aliases: [] };
    });
    const orderedTitleByKey = new Map(orderedTitles.map((item) => [item.normalizedTitle, item]));
    for (const [aliasIndex, alias] of (entry.title_aliases ?? []).entries()) {
      const aliasLabel = `${label}题名别名第${aliasIndex + 1}项`;
      const officialTitleKey = normalizedTitle(alias.official_title);
      const aliasTitleKey = normalizedTitle(alias.alias_title);
      const target = orderedTitleByKey.get(officialTitleKey);
      if (!target) throw new Error(`${aliasLabel}没有对应的决定原文题名。`);
      if (!aliasTitleKey || seen.has(aliasTitleKey)) throw new Error(`${aliasLabel}为空或重复。`);
      const aliasEvidencePath = path.resolve(baseDir, alias.evidence_path ?? "");
      if (!fs.existsSync(aliasEvidencePath)) throw new Error(`${aliasLabel}证据文件不存在。`);
      const aliasDigest = crypto.createHash("sha256")
        .update(fs.readFileSync(aliasEvidencePath))
        .digest("hex");
      if (aliasDigest !== String(alias.source_sha256 ?? "").toLowerCase()) {
        throw new Error(`${aliasLabel}证据SHA-256不一致。`);
      }
      if (!/^https?:\/\//.test(alias.official_url ?? "")) {
        throw new Error(`${aliasLabel}官方URL无效。`);
      }
      seen.add(aliasTitleKey);
      target.aliases.push({
        title: alias.alias_title,
        normalizedTitle: aliasTitleKey,
        relativePath: path.relative(baseDir, aliasEvidencePath).replaceAll("\\", "/"),
        officialUrl: alias.official_url,
        sourceSha256: aliasDigest,
      });
    }
    return {
      agencyCode: entry.agency_code,
      promulgationDate: entry.promulgation_date,
      sequenceCode: entry.sequence_code,
      decisionTitle,
      orderedTitles,
      relativePath: path.relative(baseDir, evidencePath).replaceAll("\\", "/"),
      officialUrl: entry.official_url,
      sourceSha256: digest,
    };
  });
}

export function extractDecisionTitleOrder(body) {
  const text = String(body ?? "").normalize("NFKC");
  const heading = /^[\t ]*(?:#{1,6}\s*)?(?:\*\*)?([一二三四五六七八九十百]+|\d+)[、.．]\s*([^\n]*)/gmu;
  const matches = [...text.matchAll(heading)];
  const candidates = [];
  const addTitle = (value, position) => {
    const title = String(value ?? "").replaceAll("**", "").trim();
    const key = normalizedTitle(title);
    if (!key) return;
    candidates.push({ title, normalizedTitle: key, position: Number(position) || 0 });
  };
  const hasExplicitTitleHeadings = (
    /(?:决定[,，]?\s*)?对[^\n。]{0,400}(?:法规|规章)[^\n。]{0,30}作(?:出|如下)?修改/u.test(text)
    || /废止下列[^\n。]{0,80}(?:法规|规章)/u.test(text)
  );
  const explicitOperativeList = /对((?:《[^》\n]{2,120}》(?:[、,，和及]\s*)?){2,})作(?:出|如下)?修改/gu;
  for (const match of text.matchAll(explicitOperativeList)) {
    for (const titleMatch of match[1].matchAll(/《([^》\n]{2,120})》/gu)) {
      addTitle(titleMatch[1], (match.index ?? 0) + (titleMatch.index ?? 0));
    }
  }
  const singleOperativeClause = /(?:决定[,，]?\s*)?(?:对|将)《([^》\n]{2,120})》(?![^\n。]{0,30}等)(?:作出|作|进行|予以)?(?:如下)?修改/gu;
  for (const match of text.matchAll(singleOperativeClause)) {
    addTitle(match[1], match.index);
  }
  for (const match of matches) {
    const headingText = match[2] ?? "";
    const titleMatch = headingText.match(/《([^》\n]{2,120})》/u);
    if (/(?:将|对|在|修改|废止|删去|停止施行)/u.test(headingText) && titleMatch) {
      addTitle(titleMatch[1], match.index);
      continue;
    }
    if (
      hasExplicitTitleHeadings
      && titleMatch
      && /^\s*《[^》\n]{2,120}》(?:\s*[（(][^）)\n]*[）)])*\s*$/u.test(headingText)
    ) {
      addTitle(titleMatch[1], match.index);
      continue;
    }
    if (
      hasExplicitTitleHeadings
      && !titleMatch
      && !/(?:废止|修改)下列/u.test(headingText)
      && /(?:条例|办法|规定|规则|决定|法规)$/u.test(headingText.replaceAll("**", "").trim())
    ) {
      addTitle(headingText, match.index);
    }
  }
  const parenthesizedTarget = /^[\t ]*[（(][一二三四五六七八九十百\d]+[）)]\s*(?:(?:将|对|废止|修改)\s*)?《([^》\n]{2,120})》/gmu;
  for (const match of text.matchAll(parenthesizedTarget)) {
    addTitle(match[1], match.index);
  }
  if (hasExplicitTitleHeadings) {
    const aboutTarget = /^[\t ]*关于《([^》\n]{2,120})》[\t ]*$/gmu;
    for (const match of text.matchAll(aboutTarget)) {
      addTitle(match[1], match.index);
    }
  }
  const inlineRepeal = /(?:决定[,，]\s*)?(?:予以)?废止((?:《[^》\n]{2,120}》[、,，\s]*){2,})/gu;
  for (const match of text.matchAll(inlineRepeal)) {
    for (const titleMatch of match[1].matchAll(/《([^》\n]{2,120})》/gu)) {
      addTitle(titleMatch[1], (match.index ?? 0) + (titleMatch.index ?? 0));
    }
  }
  const ordered = [];
  const seen = new Set();
  for (const candidate of candidates.sort((left, right) => left.position - right.position)) {
    if (seen.has(candidate.normalizedTitle)) continue;
    seen.add(candidate.normalizedTitle);
    ordered.push(candidate);
  }
  return ordered.map(({ title, normalizedTitle }, index) => ({
    title,
    normalizedTitle,
    order: index + 1,
  }));
}

function chineseInteger(value) {
  const text = String(value ?? "").trim();
  if (/^\d+$/.test(text)) return Number(text);
  const digits = new Map([
    ["零", 0], ["〇", 0], ["一", 1], ["二", 2], ["两", 2], ["三", 3],
    ["四", 4], ["五", 5], ["六", 6], ["七", 7], ["八", 8], ["九", 9],
  ]);
  const units = new Map([["十", 10], ["百", 100], ["千", 1000]]);
  let total = 0;
  let current = 0;
  for (const character of text) {
    if (digits.has(character)) {
      current = digits.get(character);
      continue;
    }
    const unit = units.get(character);
    if (!unit) return undefined;
    total += (current || 1) * unit;
    current = 0;
  }
  const result = total + current;
  return Number.isInteger(result) && result > 0 ? result : undefined;
}

function declaredDecisionTitleCount(decisionTitle) {
  const match = String(decisionTitle ?? "").normalize("NFKC").match(
    /(?:等|共|涉及)?([零〇一二两三四五六七八九十百千\d]+)(?:部|件|项)(?:现行)?(?:地方性法规|行政法规|规章|法规|法律)/u,
  );
  return match ? chineseInteger(match[1]) : undefined;
}

function declaredDecisionBodyCount(body) {
  const text = String(body ?? "").normalize("NFKC");
  const grouped = new Map();
  for (const match of text.matchAll(/(废止|修改)下列([零〇一二两三四五六七八九十百千\d]+)(?:部|件|项)(?:现行)?(?:地方性法规|行政法规|规章|法规|法律)/gu)) {
    const count = chineseInteger(match[2]);
    if (Number.isInteger(count)) grouped.set(`${match[1]}|${count}`, count);
  }
  if (grouped.size) return [...grouped.values()].reduce((sum, count) => sum + count, 0);
  const direct = text.match(/对(?:下列|以下)([零〇一二两三四五六七八九十百千\d]+)(?:部|件|项)(?:现行)?(?:地方性法规|行政法规|规章|法规|法律)/u);
  return direct ? chineseInteger(direct[1]) : undefined;
}

export function validatedDecisionTitleOrder(decisionTitle, body) {
  let orderedTitles = extractDecisionTitleOrder(body);
  if (!orderedTitles.length && /(?:修改|废止)[^\n]{0,160}决定/u.test(decisionTitle ?? "")) {
    const quotedTitles = [...String(decisionTitle).matchAll(/《([^》\n]{2,120})》/gu)];
    if (quotedTitles.length === 1) {
      const title = quotedTitles[0][1];
      orderedTitles = [{ title, normalizedTitle: normalizedTitle(title), order: 1 }];
    }
  }
  const expectedCount = declaredDecisionBodyCount(body)
    ?? declaredDecisionTitleCount(decisionTitle);
  const extractedCount = orderedTitles.length;
  if (Number.isInteger(expectedCount) && expectedCount !== extractedCount) {
    return {
      status: "DECLARED_TITLE_COUNT_MISMATCH",
      expectedCount,
      extractedCount,
      orderedTitles: [],
    };
  }
  return {
    status: extractedCount ? "VALID" : "NO_ORDERED_TITLES",
    expectedCount,
    extractedCount,
    orderedTitles,
  };
}

export function decisionOrderForTitle(title, orderedTitles) {
  const key = normalizedTitle(title);
  if (!key) return undefined;
  const matches = (orderedTitles ?? []).filter((item) => (
    item.normalizedTitle === key
    || (item.aliases ?? []).some((alias) => alias.normalizedTitle === key)
  ));
  return matches.length === 1 ? matches[0].order : undefined;
}

function equivalentDecisionMatch(matches) {
  if (!matches.length) return null;
  const evidenceKeys = new Set(matches.map(({ decision, order }) => (
    `${decision.sequenceCode ?? ""}|${order}`
  )));
  if (evidenceKeys.size !== 1) return null;
  return [...matches].sort((left, right) => {
    const leftScore = Number(Boolean(left.decision.sourceSha256))
      + Number(Boolean(left.decision.officialUrl));
    const rightScore = Number(Boolean(right.decision.sourceSha256))
      + Number(Boolean(right.decision.officialUrl));
    return rightScore - leftScore
      || String(left.decision.relativePath ?? "")
        .localeCompare(String(right.decision.relativePath ?? ""), "zh-CN");
  })[0];
}

export function decisionForDocument(document, eventDecisions) {
  const documentTitleKey = normalizedTitle(document?.title);
  const titleMatches = (eventDecisions ?? [])
    .map((decision) => ({
      decision,
      order: documentTitleKey && documentTitleKey === normalizedTitle(decision.decisionTitle)
        ? 0
        : decisionOrderForTitle(document?.title, decision.orderedTitles),
    }))
    .filter(({ order }) => Number.isInteger(order));
  const exactSequenceMatches = titleMatches.filter(
    ({ decision }) => decision.sequenceCode === document?.sequenceCode,
  );
  if (exactSequenceMatches.length) return equivalentDecisionMatch(exactSequenceMatches);
  return equivalentDecisionMatch(titleMatches);
}

export function decisionCodingForDocument(document, eventDecisions) {
  const resolved = decisionForDocument(document, eventDecisions);
  if (!resolved) return null;
  const { decision, order } = resolved;
  const orderedTitle = order === 0
    ? decision.decisionTitle
    : decision.orderedTitles.find((item) => item.order === order)?.title;
  return {
    sequenceCode: decision.sequenceCode,
    officialDecisionOrder: order,
    canonicalTitle: orderedTitle ?? document?.title ?? "",
    decisionOrderEvidence: JSON.stringify({
      source_relative_path: decision.relativePath ?? "",
      source_official_url: decision.officialUrl ?? "",
      source_sha256: decision.sourceSha256 ?? "",
      order,
      decision_sequence_code: decision.sequenceCode,
    }),
  };
}

export function decisionCodingForLegacyCarrier(document, registeredDecisions) {
  const agencyCode = String(document?.agencyCode ?? "");
  const legacyPromulgationDate = String(document?.legacyPromulgationDate ?? "");
  if (!/^\d{10}$/.test(agencyCode) || !/^\d{8}$/.test(legacyPromulgationDate)) {
    return null;
  }
  const eventDecisions = (registeredDecisions ?? []).filter((decision) => (
    decision.agencyCode === agencyCode
    && decision.promulgationDate === legacyPromulgationDate
  ));
  const coding = decisionCodingForDocument(document, eventDecisions);
  return coding ? { ...coding, promulgationDate: legacyPromulgationDate } : null;
}
