import { createHash } from "node:crypto";
import path from "node:path";

const attachmentExtension = /\.(?:png|jpe?g|gif|svg|webp|pdf|docx?|xlsx?|ofd|uof|zip)$/i;
const markdownLink = /!?\[[^\]\r\n]*\]\(([^)\r\n]+)\)/g;

function isBase64Payload(value) {
  if (!value) return false;
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    const allowed = (code >= 65 && code <= 90)
      || (code >= 97 && code <= 122)
      || (code >= 48 && code <= 57)
      || code === 43
      || code === 47
      || code === 61
      || code === 9
      || code === 10
      || code === 13
      || code === 32;
    if (!allowed) return false;
  }
  return true;
}

export function extractInlineDataImages(markdown) {
  const source = String(markdown ?? "");
  const markerText = "](data:image/";
  const parts = [];
  const attachments = [];
  let cursor = 0;
  let searchFrom = 0;

  while (searchFrom < source.length) {
    const marker = source.indexOf(markerText, searchFrom);
    if (marker < 0) break;
    const altStart = source.lastIndexOf("![", marker);
    const headerEnd = source.indexOf(";base64,", marker + markerText.length);
    const close = headerEnd >= 0 ? source.indexOf(")", headerEnd + 8) : -1;
    const altSegment = altStart >= 0 ? source.slice(altStart + 2, marker) : "";
    const mimeType = headerEnd >= 0 ? source.slice(marker + 7, headerEnd).toLowerCase() : "";
    if (
      altStart < cursor
      || altSegment.includes("\n")
      || headerEnd < 0
      || close < 0
      || !/^image\/[a-z0-9.+-]+$/i.test(mimeType)
    ) {
      searchFrom = marker + markerText.length;
      continue;
    }
    const payload = source.slice(headerEnd + 8, close);
    if (!isBase64Payload(payload)) {
      searchFrom = close + 1;
      continue;
    }
    const decoded = Buffer.from(payload, "base64");
    if (!decoded.length) {
      searchFrom = close + 1;
      continue;
    }
    const sha256 = createHash("sha256").update(decoded).digest("hex");
    const label = altSegment.trim() || `内嵌图像${attachments.length + 1}`;
    parts.push(
      source.slice(cursor, altStart),
      `[内嵌图像已分离：${label}；MIME=${mimeType}；SHA-256=${sha256}]`,
    );
    attachments.push({
      label,
      mimeType,
      sha256,
      byteLength: decoded.length,
    });
    cursor = close + 1;
    searchFrom = cursor;
  }

  if (!attachments.length) return { markdown: source, attachments };
  parts.push(source.slice(cursor));
  return { markdown: parts.join(""), attachments };
}

export function localAttachmentReferences(markdown) {
  const references = [];
  for (const match of markdown.matchAll(markdownLink)) {
    let raw = match[1].trim().replace(/^<|>$/g, "");
    if (!raw || /^(?:https?:|data:|mailto:)/i.test(raw)) continue;
    raw = raw.replace(/\s+["'][^"']*["']$/, "").trim();
    const withoutQuery = raw.split(/[?#]/, 1)[0];
    let decoded = withoutQuery;
    try {
      decoded = decodeURIComponent(withoutQuery);
    } catch {
      continue;
    }
    if (!attachmentExtension.test(decoded)) continue;
    if (decoded.includes("\0") || /[\[\]'"`]/.test(decoded)) continue;
    references.push({
      raw,
      decoded: path.normalize(decoded),
    });
  }
  return references;
}
