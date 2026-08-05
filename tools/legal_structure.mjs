import { buildContentStructureCode } from "./standard_codes.mjs";

const DIGITS = new Map([
  ["零", 0],
  ["〇", 0],
  ["一", 1],
  ["二", 2],
  ["两", 2],
  ["三", 3],
  ["四", 4],
  ["五", 5],
  ["六", 6],
  ["七", 7],
  ["八", 8],
  ["九", 9],
]);
const UNITS = new Map([
  ["十", 10],
  ["百", 100],
  ["千", 1000],
  ["万", 10000],
]);
const ORDINAL = "[0-9〇零一二两三四五六七八九十百千万]+";
const CHINESE_ORDINAL = "[〇零一二两三四五六七八九十百千万]+";

export function parseChineseOrdinal(value) {
  const source = String(value ?? "").trim();
  if (/^\d+$/.test(source)) {
    const number = Number.parseInt(source, 10);
    return Number.isSafeInteger(number) && number >= 0 ? number : null;
  }
  if (!source || [...source].some((character) =>
    !DIGITS.has(character) && !UNITS.has(character))) {
    return null;
  }
  let total = 0;
  let section = 0;
  let digit = 0;
  for (const character of source) {
    if (DIGITS.has(character)) {
      digit = DIGITS.get(character);
      continue;
    }
    const unit = UNITS.get(character);
    if (unit === 10000) {
      section = (section + digit) * unit;
      total += section;
      section = 0;
    } else {
      section += (digit || 1) * unit;
    }
    digit = 0;
  }
  return total + section + digit;
}

function cleanMarkdownLine(value) {
  return value
    .replace(/^\s{0,3}#{1,6}\s*/, "")
    .replace(/^\s*(?:[-*+]\s+|\d+[.)、]\s+)/, "")
    .replace(/^\s*>\s?/, "")
    .replace(/\*\*|__|`/g, "")
    .trim();
}

function rejoinSplitHierarchyReferences(markdown) {
  const input = String(markdown ?? "").split(/\r?\n/);
  const output = [];
  const carrierTail = /(?:本法|本条例|本办法|本规定|本规范|本细则|本规则|《[^》]{1,40}》)$/u;
  const continuation = new RegExp(
    `^(?:第${ORDINAL}(?:编|分编|章|节|条)(?:的|规定|有关|中)|的|中|关于|未作出|规定之外|至|[、，及和])`,
  );
  for (let index = 0; index < input.length; index += 1) {
    const rawLine = input[index];
    const line = cleanMarkdownLine(rawLine);
    const hierarchyLabel = line.match(new RegExp(`^第(${ORDINAL})(?:编|分编|章|节)$`));
    if (!hierarchyLabel) {
      output.push(rawLine);
      continue;
    }
    let previousIndex = output.length - 1;
    while (previousIndex >= 0 && !cleanMarkdownLine(output[previousIndex])) previousIndex -= 1;
    let nextIndex = index + 1;
    while (nextIndex < input.length && !cleanMarkdownLine(input[nextIndex])) nextIndex += 1;
    const previousLine = previousIndex >= 0 ? cleanMarkdownLine(output[previousIndex]) : "";
    const nextLine = nextIndex < input.length ? cleanMarkdownLine(input[nextIndex]) : "";
    if (carrierTail.test(previousLine) && continuation.test(nextLine)) {
      output.splice(previousIndex + 1);
      output[previousIndex] = `${previousLine}${line}${nextLine}`;
      index = nextIndex;
      continue;
    }
    output.push(rawLine);
  }
  return output;
}

function rejoinSplitArticleReferences(markdown) {
  const input = rejoinSplitHierarchyReferences(markdown);
  const output = [];
  const seenArticleLabels = new Set();
  let lastAcceptedArticleNumber = null;
  const carrierReferenceTail = new RegExp(
    `(?:本法|本条例|本办法|本规定|本规范|本细则|本规则|本规程|《[^》]{1,40}》|[\\p{Script=Han}]{2,40}(?:法|条例|办法|规定|规范|规则|规程))(?:[（(][^）)\\r\\n]{1,40}[）)])?(?:第${ORDINAL}条(?:第?${ORDINAL}(?:款|项))?(?:[、，及和至]|或者|以及)?)*$`,
    "u",
  );
  const referenceContinuation = new RegExp(
    `^(?:[、，。；及和至]|或者|以及|第[（(]${ORDINAL}[）)](?:[、，][（(]${ORDINAL}[）)])+(?:款|项|目)|第?${ORDINAL}(?:[、，]${ORDINAL})+(?:款|项|目)|第?[（(]?${ORDINAL}[）)]?(?:款|项|目)|规定|的规定|中规定|所称|所述|所列|所规定|所禁止|另有规定|范围|有关|办理|处理|处罚|要求|确定|给予)`,
  );
  const referenceCarrierPhrase = /(?:本法|本条例|本办法|本规定|本细则|本规则|依据|依照|按照|根据|符合|适用|违反|参照)/u;
  for (let index = 0; index < input.length; index += 1) {
    const rawLine = input[index];
    const line = cleanMarkdownLine(rawLine);
    const articleLabel = line.match(new RegExp(`^第(${ORDINAL})条$`));
    if (!articleLabel) {
      output.push(rawLine);
      continue;
    }

    const label = `第${articleLabel[1]}条`;
    const articleNumber = parseChineseOrdinal(articleLabel[1]);
    let previousIndex = output.length - 1;
    while (previousIndex >= 0 && !cleanMarkdownLine(output[previousIndex])) {
      previousIndex -= 1;
    }
    let nextIndex = index + 1;
    while (nextIndex < input.length && !cleanMarkdownLine(input[nextIndex])) {
      nextIndex += 1;
    }
    const previousLine = previousIndex >= 0
      ? cleanMarkdownLine(output[previousIndex])
      : "";
    const nextLine = nextIndex < input.length
      ? cleanMarkdownLine(input[nextIndex])
      : "";
    let followingArticleNumber = null;
    for (let followingIndex = nextIndex + 1; followingIndex < input.length; followingIndex += 1) {
      const followingLine = cleanMarkdownLine(input[followingIndex]);
      if (!followingLine) continue;
      const followingArticle = followingLine.match(new RegExp(`^第(${ORDINAL})条$`));
      if (followingArticle) {
        followingArticleNumber = parseChineseOrdinal(followingArticle[1]);
      }
      break;
    }
    let sameArticleAhead = followingArticleNumber === articleNumber;
    if (!sameArticleAhead && Number.isInteger(articleNumber)) {
      let inspectedHeadings = 0;
      for (let followingIndex = nextIndex + 1;
        followingIndex < input.length && inspectedHeadings < 3;
        followingIndex += 1) {
        const followingLine = cleanMarkdownLine(input[followingIndex]);
        if (!followingLine) continue;
        const followingArticle = followingLine.match(new RegExp(`^第(${ORDINAL})条$`));
        if (!followingArticle) continue;
        inspectedHeadings += 1;
        if (parseChineseOrdinal(followingArticle[1]) === articleNumber) {
          sameArticleAhead = true;
          break;
        }
      }
    }
    let expectedNextArticleAhead = false;
    if (Number.isInteger(lastAcceptedArticleNumber)
      && Number.isInteger(articleNumber)
      && articleNumber > lastAcceptedArticleNumber + 1
      && previousLine
      && !/[。；：！？]$/u.test(previousLine)) {
      let inspectedHeadings = 0;
      for (let followingIndex = nextIndex + 1;
        followingIndex < input.length && inspectedHeadings < 3;
        followingIndex += 1) {
        const followingLine = cleanMarkdownLine(input[followingIndex]);
        if (!followingLine) continue;
        const followingArticle = followingLine.match(new RegExp(`^第(${ORDINAL})条$`));
        if (!followingArticle) continue;
        inspectedHeadings += 1;
        const followingNumber = parseChineseOrdinal(followingArticle[1]);
        if (followingNumber === lastAcceptedArticleNumber + 1) {
          expectedNextArticleAhead = true;
          break;
        }
        if (!Number.isInteger(followingNumber)
          || followingNumber <= lastAcceptedArticleNumber + 1) break;
      }
    }
    const isRepeatedSplitReference = seenArticleLabels.has(label)
      && referenceContinuation.test(nextLine);
    const isForwardJumpSplitReference = Number.isInteger(lastAcceptedArticleNumber)
      && Number.isInteger(articleNumber)
      && articleNumber > lastAcceptedArticleNumber + 1
      && (followingArticleNumber === lastAcceptedArticleNumber + 1
        || expectedNextArticleAhead)
      && carrierReferenceTail.test(previousLine);
    const isForwardReferenceChain = expectedNextArticleAhead
      && !/[。；：！？]$/u.test(previousLine);
    const isAdjacentListSplitReference = Number.isInteger(lastAcceptedArticleNumber)
      && Number.isInteger(articleNumber)
      && articleNumber === lastAcceptedArticleNumber + 1
      && followingArticleNumber === articleNumber + 1
      && carrierReferenceTail.test(previousLine)
      && /^(?:[、，及和至]|或者|以及)$/u.test(nextLine);
    const isBackwardSplitReference = Number.isInteger(lastAcceptedArticleNumber)
      && Number.isInteger(articleNumber)
      && articleNumber <= lastAcceptedArticleNumber
      && carrierReferenceTail.test(previousLine)
      && referenceCarrierPhrase.test(previousLine);
    const isForwardListSplitReference = Number.isInteger(lastAcceptedArticleNumber)
      && Number.isInteger(articleNumber)
      && articleNumber > lastAcceptedArticleNumber + 1
      && carrierReferenceTail.test(previousLine)
      && /^[、，及和至]$/u.test(nextLine);
    const isForwardCarrierSplitReference = Number.isInteger(lastAcceptedArticleNumber)
      && Number.isInteger(articleNumber)
      && articleNumber > lastAcceptedArticleNumber + 1
      && carrierReferenceTail.test(previousLine)
      && referenceContinuation.test(nextLine);
    const isExpectedNextCarrierSplitReference = Number.isInteger(lastAcceptedArticleNumber)
      && Number.isInteger(articleNumber)
      && articleNumber === lastAcceptedArticleNumber + 1
      && followingArticleNumber !== articleNumber + 1
      && carrierReferenceTail.test(previousLine)
      && referenceContinuation.test(nextLine);
    const isExpectedNumberReferenceBeforeActual = Number.isInteger(articleNumber)
      && sameArticleAhead
      && (carrierReferenceTail.test(previousLine)
        || (previousLine && !/[。；：！？]$/u.test(previousLine))
        || referenceContinuation.test(nextLine));
    const emptyArticleReferenceChain = previousLine.match(new RegExp(
      `^第(${ORDINAL})条(?:第${ORDINAL}条(?:[、，及和至])?)*$`,
    ));
    const isReferenceInsideEmptyArticle = Number.isInteger(lastAcceptedArticleNumber)
      && Number.isInteger(articleNumber)
      && parseChineseOrdinal(emptyArticleReferenceChain?.[1]) === lastAcceptedArticleNumber
      && articleNumber <= lastAcceptedArticleNumber
      && referenceContinuation.test(nextLine);
    if (isRepeatedSplitReference
      || isForwardJumpSplitReference
      || isForwardReferenceChain
      || isAdjacentListSplitReference
      || isBackwardSplitReference
      || isForwardListSplitReference
      || isForwardCarrierSplitReference
      || isExpectedNextCarrierSplitReference
      || isExpectedNumberReferenceBeforeActual
      || isReferenceInsideEmptyArticle) {
      output.splice(previousIndex + 1);
      output[previousIndex] = `${previousLine}${label}${nextLine}`;
      index = nextIndex;
      continue;
    }

    seenArticleLabels.add(label);
    lastAcceptedArticleNumber = articleNumber;
    output.push(rawLine);
  }
  return output;
}

function removeLeadingQuotedSynopsisWhenStructuredBodyFollows(markdown) {
  const lines = String(markdown ?? "").split(/\r?\n/);
  const firstStructuredBodyHeading = lines.findIndex((line) =>
    /^\s{0,3}#{2,6}\s*(?:\*\*)?第[0-9〇零一二两三四五六七八九十百千万]+(?:编|分编|章|节|条)/u.test(line));
  if (firstStructuredBodyHeading < 0) return String(markdown ?? "");
  return lines
    .filter((line, index) => index >= firstStructuredBodyHeading || !/^\s*>/u.test(line))
    .join("\n");
}

function code(state) {
  return buildContentStructureCode({
    book: state.book,
    subBook: state.subBook,
    chapter: state.chapter,
    section: state.section,
    article: state.article,
    paragraph: state.paragraph,
    item: state.item,
    subItem: state.subItem,
  });
}

function row(state, category, order, content) {
  return {
    DE_02001: code(state),
    DE_02002: content,
    DE_02003: category,
    DE_02004: String(order),
    DE_02005: "",
    DE_02006_relative_path: "",
  };
}

function deduplicateIdenticalStructureRows(rows) {
  const seen = new Set();
  return rows.filter((entry) => {
    const identity = [
      entry.DE_02001,
      entry.DE_02003,
      String(entry.DE_02002 ?? "").replace(/\s+/gu, ""),
    ].join("\u0000");
    if (seen.has(identity)) return false;
    seen.add(identity);
    return true;
  });
}

function matchOrdinal(line, suffix) {
  return line.match(new RegExp(`^第(${ORDINAL})${suffix}(?:\\s+|　)*(.*)$`));
}

function isHierarchyReferenceRemainder(value) {
  return /^(?:的|中|关于|未作出|规定之外|至|[、，及和]|规定的|所称|所述|有关)/u.test(value)
    || new RegExp(`^第${ORDINAL}(?:编|分编|章|节|条)`).test(value);
}

function primaryHierarchyMarkerKey(line) {
  for (const suffix of ["编", "分编", "章"]) {
    const match = matchOrdinal(line, suffix);
    if (match) {
      return `${suffix}:${match[1]}:${match[2].replace(/\\s+/gu, "")}`;
    }
  }
  return "";
}

function hierarchyMarker(line) {
  const cleaned = cleanMarkdownLine(line);
  if (!cleaned.startsWith("第")) return null;
  for (const [suffix, category] of [["编", "01"], ["分编", "02"], ["章", "03"], ["节", "04"]]) {
    const match = matchOrdinal(cleaned, suffix);
    if (!match || /[。；，！？]/u.test(match[2])) continue;
    return {
      category,
      number: parseChineseOrdinal(match[1]),
      title: match[2].replace(/\s+/gu, ""),
      line: cleaned,
    };
  }
  return null;
}

function restoreBodyHierarchyFromLeadingContents(lines) {
  const markers = [];
  const markerIndexes = [];
  let collecting = false;
  let blockEnd = -1;
  for (let index = 0; index < lines.length; index += 1) {
    const cleaned = cleanMarkdownLine(lines[index]);
    if (!collecting && cleaned.replace(/\s+/gu, "") === "目录") return lines;
    const marker = hierarchyMarker(lines[index]);
    if (!collecting) {
      if (new RegExp(`^第${ORDINAL}条(?:\s|$)`).test(cleaned)) break;
      if (!marker) continue;
      collecting = true;
    }
    if (marker) {
      markers.push(marker);
      markerIndexes.push(index);
      blockEnd = index;
      continue;
    }
    if (!cleaned) continue;
    if (cleaned === "---") break;
    break;
  }
  if (markers.length < 2) return lines;

  const replacements = new Map();
  const matchedMarkers = new Set();
  for (let index = blockEnd + 1; index < lines.length; index += 1) {
    const cleaned = cleanMarkdownLine(lines[index]);
    const laterMarker = hierarchyMarker(lines[index]);
    const laterTitle = cleaned.replace(/\s+/gu, "");
    const isMarkdownHeading = /^\s{0,3}#{1,6}\s*/.test(lines[index]);
    for (let markerIndex = 0; markerIndex < markers.length; markerIndex += 1) {
      if (matchedMarkers.has(markerIndex)) continue;
      const marker = markers[markerIndex];
      const repeatsFullMarker = laterMarker
        && laterMarker.category === marker.category
        && laterMarker.number === marker.number
        && laterMarker.title === marker.title;
      const repeatsTitleOnly = isMarkdownHeading
        && marker.title
        && !laterMarker
        && laterTitle === marker.title;
      if (!repeatsFullMarker && !repeatsTitleOnly) continue;
      matchedMarkers.add(markerIndex);
      if (repeatsTitleOnly) replacements.set(index, marker.line);
      break;
    }
  }
  if (matchedMarkers.size < 2) return lines;

  const discarded = new Set(markerIndexes);
  return lines.flatMap((line, index) =>
    discarded.has(index) ? [] : [replacements.get(index) ?? line]);
}

function parseArticle(article, hierarchy) {
  const events = article.events;
  const ordinary = events.filter((event) => event.type === "paragraph");
  const hasNested = events.some((event) =>
    event.type === "item" || event.type === "subItem");
  if (ordinary.length === 1 && !hasNested) {
    return [row(
      { ...hierarchy, article: article.number, paragraph: 0, item: 0, subItem: 0 },
      "05",
      article.number,
      ordinary[0].content,
    )];
  }

  const output = [];
  let paragraph = 0;
  let item = 0;
  for (const event of events) {
    if (event.type === "paragraph") {
      if (paragraph >= 99) {
        throw new Error("CONTENT_PARAGRAPH_OVERFLOW");
      }
      paragraph += 1;
      item = 0;
      output.push(row(
        { ...hierarchy, article: article.number, paragraph, item: 0, subItem: 0 },
        "06",
        paragraph,
        event.content,
      ));
    } else if (event.type === "item") {
      if (paragraph === 0) paragraph = 1;
      item = event.number;
      output.push(row(
        { ...hierarchy, article: article.number, paragraph, item, subItem: 0 },
        "07",
        item,
        event.content,
      ));
    } else if (event.type === "subItem") {
      if (paragraph === 0) paragraph = 1;
      output.push(row(
        {
          ...hierarchy,
          article: article.number,
          paragraph,
          item,
          subItem: event.number,
        },
        "08",
        event.number,
        event.content,
      ));
    }
  }
  return output;
}

function extractTopLevelChineseItemRows(markdown) {
  const text = String(markdown ?? "")
    .split(/\r?\n/)
    .map(cleanMarkdownLine)
    .filter((line) => line && line !== "---")
    .join(" ");
  const markers = [...text.matchAll(/(^|[\s：。；！？])([一二三四五六七八九十百]+)、/gu)]
    .map((match) => ({
      start: match.index + match[1].length,
      number: parseChineseOrdinal(match[2]),
    }))
    .filter((marker) => Number.isInteger(marker.number) && marker.number > 0 && marker.number <= 99);

  let best = [];
  let current = [];
  for (const marker of markers) {
    if (marker.number === 1) {
      if (current.length > best.length) best = current;
      current = [marker];
      continue;
    }
    if (current.length && marker.number === current.at(-1).number + 1) {
      current.push(marker);
      continue;
    }
    if (current.length > best.length) best = current;
    current = [];
  }
  if (current.length > best.length) best = current;
  if (best.length < 2) return [];

  return best.map((marker, index) => row(
    {
      book: 0,
      subBook: 0,
      chapter: 0,
      section: 0,
      article: 0,
      paragraph: 1,
      item: marker.number,
      subItem: 0,
    },
    "07",
    marker.number,
    text.slice(marker.start, best[index + 1]?.start ?? text.length).trim(),
  ));
}

function extractModificationDecisionRows(markdown) {
  const cleanedLines = String(markdown ?? "")
    .split(/\r?\n/)
    .map(cleanMarkdownLine)
    .filter(Boolean);
  const beginsWithInstrumentDirective = cleanedLines.some((line) =>
    /^一、\s*(?:将|对)?《/u.test(line));
  if (!beginsWithInstrumentDirective) return [];
  const rows = extractTopLevelChineseItemRows(markdown);
  if (rows.length < 2) return [];
  const directiveRows = rows.filter((entry) =>
    /《[^》]+》/u.test(entry.DE_02002)
    && /(?:修改|废止|删除|增加)/u.test(entry.DE_02002));
  return directiveRows.length >= 2 ? rows : [];
}

export function extractLegalContentRows(markdown) {
  const structureMarkdown = removeLeadingQuotedSynopsisWhenStructuredBodyFollows(markdown);
  const modificationDecisionRows = extractModificationDecisionRows(structureMarkdown);
  if (modificationDecisionRows.length) {
    return deduplicateIdenticalStructureRows(modificationDecisionRows);
  }
  const rows = [];
  const hierarchy = {
    book: 0,
    subBook: 0,
    chapter: 0,
    section: 0,
  };
  let article = null;
  let acceptedArticleCount = 0;
  let currentItemNumber = 0;
  let pendingSpuriousArticleReference = "";
  let insideTableOfContents = false;
  let insideUnstructuredAttachment = false;
  let tableOfContentsFirstPrimaryKey = "";
  const flushArticle = () => {
    if (!article) return;
    rows.push(...parseArticle(article, hierarchy));
    article = null;
  };
  const discardUnlabeledLeadingHierarchyList = (candidateCode, category) => {
    if (acceptedArticleCount > 0) return;
    const repeatsLeadingHierarchy = rows.some((entry) =>
      entry.DE_02003 === category && entry.DE_02001 === candidateCode);
    if (!repeatsLeadingHierarchy) return;
    rows.length = 0;
    hierarchy.book = 0;
    hierarchy.subBook = 0;
    hierarchy.chapter = 0;
    hierarchy.section = 0;
  };

  const rejoinedLines = rejoinSplitArticleReferences(structureMarkdown);
  for (const rawLine of restoreBodyHierarchyFromLeadingContents(rejoinedLines)) {
    const line = cleanMarkdownLine(rawLine);
    if (!line || line === "---") continue;
    if (insideUnstructuredAttachment) continue;

    const previousArticleText = article?.events
      .filter((event) => event.type === "paragraph")
      .map((event) => event.content)
      .join(" ") ?? "";
    if (article && /^\s*#{1,6}\s*附件[0-9一二三四五六七八九十百]*\s*$/u.test(rawLine)) {
      flushArticle();
      insideUnstructuredAttachment = true;
      continue;
    }
    if (article
      && /(?:施行|废止)/u.test(previousArticleText)
      && /^(?:附件[0-9一二三四五六七八九十]*[：:]?\s*)?.{2,80}(?:名单|名录|目录|附表|一览表)$/u.test(line)) {
      flushArticle();
      insideUnstructuredAttachment = true;
      continue;
    }

    if (article && /^\s*\|.*\|\s*$/u.test(rawLine)) {
      const previousEvent = article.events.at(-1);
      if (previousEvent?.type === "paragraph" && previousEvent.markdownTable) {
        previousEvent.content = `${previousEvent.content}\n${rawLine.trim()}`;
      } else {
        article.events.push({
          type: "paragraph",
          content: article.events.length === 0
            ? `${article.label} ${rawLine.trim()}`
            : rawLine.trim(),
          markdownTable: true,
        });
      }
      continue;
    }

    if (line.replace(/\s+/gu, "") === "目录") {
      flushArticle();
      insideTableOfContents = true;
      tableOfContentsFirstPrimaryKey = "";
      continue;
    }
    if (insideTableOfContents) {
      const primaryKey = primaryHierarchyMarkerKey(line);
      if (primaryKey && !tableOfContentsFirstPrimaryKey) {
        tableOfContentsFirstPrimaryKey = primaryKey;
        continue;
      }
      const startsArticle = new RegExp(`^第${ORDINAL}条(?:\\s|$)`).test(line);
      const repeatsFirstPrimary = Boolean(primaryKey)
        && primaryKey === tableOfContentsFirstPrimaryKey;
      if (!repeatsFirstPrimary && !startsArticle) continue;
      insideTableOfContents = false;
    }

    let match = matchOrdinal(line, "编");
    if (match && (/[。；！？]/u.test(match[2]) || isHierarchyReferenceRemainder(match[2]))) match = null;
    if (match) {
      flushArticle();
      const book = parseChineseOrdinal(match[1]) ?? 0;
      discardUnlabeledLeadingHierarchyList(code({
        book,
        subBook: 0,
        chapter: 0,
        section: 0,
        article: 0,
        paragraph: 0,
        item: 0,
        subItem: 0,
      }), "01");
      hierarchy.book = book;
      hierarchy.subBook = 0;
      hierarchy.chapter = 0;
      hierarchy.section = 0;
      rows.push(row(
        { ...hierarchy, article: 0, paragraph: 0, item: 0, subItem: 0 },
        "01",
        hierarchy.book,
        line,
      ));
      continue;
    }
    match = matchOrdinal(line, "分编");
    if (match && (/[。；！？]/u.test(match[2]) || isHierarchyReferenceRemainder(match[2]))) match = null;
    if (match) {
      flushArticle();
      const subBook = parseChineseOrdinal(match[1]) ?? 0;
      discardUnlabeledLeadingHierarchyList(code({
        ...hierarchy,
        subBook,
        chapter: 0,
        section: 0,
        article: 0,
        paragraph: 0,
        item: 0,
        subItem: 0,
      }), "02");
      hierarchy.subBook = subBook;
      hierarchy.chapter = 0;
      hierarchy.section = 0;
      rows.push(row(
        { ...hierarchy, article: 0, paragraph: 0, item: 0, subItem: 0 },
        "02",
        hierarchy.subBook,
        line,
      ));
      continue;
    }
    match = matchOrdinal(line, "章");
    if (match && (/[。；！？]/u.test(match[2]) || isHierarchyReferenceRemainder(match[2]))) match = null;
    if (match) {
      flushArticle();
      const chapter = parseChineseOrdinal(match[1]) ?? 0;
      discardUnlabeledLeadingHierarchyList(code({
        ...hierarchy,
        chapter,
        section: 0,
        article: 0,
        paragraph: 0,
        item: 0,
        subItem: 0,
      }), "03");
      hierarchy.chapter = chapter;
      hierarchy.section = 0;
      rows.push(row(
        { ...hierarchy, article: 0, paragraph: 0, item: 0, subItem: 0 },
        "03",
        hierarchy.chapter,
        line,
      ));
      continue;
    }
    match = matchOrdinal(line, "节");
    if (match && (/[。；！？]/u.test(match[2]) || isHierarchyReferenceRemainder(match[2]))) match = null;
    if (match) {
      flushArticle();
      const section = parseChineseOrdinal(match[1]) ?? 0;
      discardUnlabeledLeadingHierarchyList(code({
        ...hierarchy,
        section,
        article: 0,
        paragraph: 0,
        item: 0,
        subItem: 0,
      }), "04");
      hierarchy.section = section;
      rows.push(row(
        { ...hierarchy, article: 0, paragraph: 0, item: 0, subItem: 0 },
        "04",
        hierarchy.section,
        line,
      ));
      continue;
    }
    match = matchOrdinal(line, "条");
    if (match) {
      const number = parseChineseOrdinal(match[1]);
      if (number === null || number > 9999) continue;
      const isBackwardInlineReference = article
        && number <= article.number
        && Boolean(match[2])
        && new RegExp(
          `^(?:所称|规定|有关|中的|中|第?${ORDINAL}(?:款|项)|后|前|的规定)`,
        ).test(match[2]);
      const isStrongInlineReference = article
        && /^(?:[、，。；及和至]|或者|以及|的规定|的协定》|规定的|所称|所述|所列|所禁止|有关|办理|处理|处罚|要求|确定|给予)/u.test(match[2]);
      if (isBackwardInlineReference || isStrongInlineReference) match = null;
    }
    if (match) {
      const number = parseChineseOrdinal(match[1]);
      const lastEvent = article?.events.at(-1);
      const isSpuriousBackwardBareHeading = article
        && number <= article.number
        && !match[2]
        && lastEvent?.type === "paragraph"
        && !/[。；：！？]$/u.test(lastEvent.content.trim());
      if (isSpuriousBackwardBareHeading) {
        pendingSpuriousArticleReference = `第${match[1]}条`;
        continue;
      }
      const embeddedNextArticle = match[2].match(
        new RegExp(`^(.+?[；。])\\s*第(${ORDINAL})条\\s*(.*)$`),
      );
      const embeddedArticleNumber = embeddedNextArticle
        ? parseChineseOrdinal(embeddedNextArticle[2])
        : null;
      if (Number.isInteger(embeddedArticleNumber)
        && embeddedArticleNumber === number + 1) {
        flushArticle();
        acceptedArticleCount += 1;
        article = {
          number,
          label: `第${match[1]}条`,
          events: [{
            type: "paragraph",
            content: `第${match[1]}条 ${embeddedNextArticle[1]}`.trim(),
          }],
        };
        flushArticle();
        acceptedArticleCount += 1;
        const embeddedLabel = `第${embeddedNextArticle[2]}条`;
        article = {
          number: embeddedArticleNumber,
          label: embeddedLabel,
          events: embeddedNextArticle[3]
            ? [{
                type: "paragraph",
                content: `${embeddedLabel} ${embeddedNextArticle[3]}`.trim(),
              }]
            : [],
        };
        currentItemNumber = 0;
        continue;
      }
      flushArticle();
      acceptedArticleCount += 1;
      article = {
        number,
        label: `第${match[1]}条`,
        events: [],
      };
      currentItemNumber = 0;
      if (match[2]) {
        article.events.push({
          type: "paragraph",
          content: `${article.label} ${match[2]}`.trim(),
        });
      }
      continue;
    }
    if (!article) continue;

    if (pendingSpuriousArticleReference) {
      const lastEvent = article.events.at(-1);
      if (lastEvent?.type === "paragraph") {
        lastEvent.content = `${lastEvent.content}${pendingSpuriousArticleReference}${line}`;
        pendingSpuriousArticleReference = "";
        continue;
      }
      pendingSpuriousArticleReference = "";
    }

    const itemMatch = line.match(new RegExp(`^[（(](${CHINESE_ORDINAL})[）)]\\s*(.*)$`));
    if (itemMatch) {
      const number = parseChineseOrdinal(itemMatch[1]);
      const embeddedNextArticle = itemMatch[2].match(
        new RegExp(`^(.+?[；。])\\s*第(${ORDINAL})条\\s*(.*)$`),
      );
      const embeddedArticleNumber = embeddedNextArticle
        ? parseChineseOrdinal(embeddedNextArticle[2])
        : null;
      if (Number.isInteger(number)
        && Number.isInteger(embeddedArticleNumber)
        && embeddedArticleNumber === article.number + 1) {
        const embeddedLabel = `第${embeddedNextArticle[2]}条`;
        article.events.push({
          type: "item",
          number,
          content: line.slice(0, line.lastIndexOf(embeddedLabel)).trim(),
        });
        flushArticle();
        acceptedArticleCount += 1;
        article = {
          number: embeddedArticleNumber,
          label: embeddedLabel,
          events: embeddedNextArticle[3]
            ? [{
                type: "paragraph",
                content: `${embeddedLabel} ${embeddedNextArticle[3]}`.trim(),
              }]
            : [],
        };
        currentItemNumber = 0;
        continue;
      }
      const isItemRangeReference = Number.isInteger(number)
        && number <= currentItemNumber
        && /^(?:项(?:所列|规定)|至[（(][^）)]+[）)]项|[、，及和][（(][^）)]+[）)]项)/u.test(itemMatch[2]);
      if (isItemRangeReference) {
        article.events.push({ type: "paragraph", content: line });
      } else if (number !== null && number <= 99) {
        article.events.push({ type: "item", number, content: line });
        currentItemNumber = number;
      }
      continue;
    }
    const parenthesizedArabicMatch = line.match(/^[（(](\d{1,2})[）)]\s*(.*)$/);
    if (parenthesizedArabicMatch) {
      const previousEvent = article.events.at(-1);
      if (previousEvent?.type === "subItem" && previousEvent.style === "dot") {
        previousEvent.content = `${previousEvent.content} ${line}`;
      } else {
        article.events.push({
          type: "subItem",
          number: Number.parseInt(parenthesizedArabicMatch[1], 10),
          content: line,
          style: "parenthesized",
        });
      }
      continue;
    }
    const subItemMatch = line.match(/^(\d{1,2})[.．、]\s*(.*)$/);
    if (subItemMatch) {
      const embeddedItem = subItemMatch[2].match(
        new RegExp(`^(.+?)\\s*([（(](${CHINESE_ORDINAL})[）)])\\s*(.+)$`),
      );
      const embeddedItemNumber = embeddedItem
        ? parseChineseOrdinal(embeddedItem[3])
        : null;
      if (Number.isInteger(embeddedItemNumber)
        && embeddedItemNumber > currentItemNumber
        && embeddedItemNumber <= 99) {
        article.events.push({
          type: "subItem",
          number: Number.parseInt(subItemMatch[1], 10),
          content: `${subItemMatch[1]}．${embeddedItem[1]}`,
          style: "dot",
        });
        article.events.push({
          type: "item",
          number: embeddedItemNumber,
          content: `${embeddedItem[2]}${embeddedItem[4]}`,
        });
        currentItemNumber = embeddedItemNumber;
        continue;
      }
      article.events.push({
        type: "subItem",
        number: Number.parseInt(subItemMatch[1], 10),
        content: line,
        style: "dot",
      });
      continue;
    }
    article.events.push({
      type: "paragraph",
      content: article.events.length === 0
        ? `${article.label} ${line}`.trim()
        : line,
    });
  }
  flushArticle();
  return deduplicateIdenticalStructureRows(
    rows.length ? rows : extractTopLevelChineseItemRows(markdown),
  );
}

export function duplicateContentStructureCodes(rows) {
  const seen = new Set();
  const duplicates = new Set();
  for (const row of rows) {
    const value = row.DE_02001;
    if (seen.has(value)) duplicates.add(value);
    seen.add(value);
  }
  return [...duplicates].sort();
}
