function normalizedTitle(value) {
  return String(value ?? "")
    .normalize("NFKC")
    .replace(/[\s《》]/g, "")
    .toLowerCase();
}

const unsafeTextControls = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/gu;

export function stripUnsafeTextControls(value) {
  return String(value ?? "").replace(unsafeTextControls, "");
}

export function normalizeLegalTextForIdentity(value) {
  return stripUnsafeTextControls(value)
    .normalize("NFKC")
    .replace(/\r\n?/g, "\n")
    .replace(/^\s*#{1,6}\s*[^\n]+\n/u, "")
    .replace(
      /\n---\s*\n(?:\s*>\s*(?:来源|原文链接)\s*[：:].*(?:\n|$))+\s*$/u,
      "",
    )
    .replace(/\s+/g, "");
}

export function normalizeCoreProvisionsForCarrierIdentity(value) {
  const text = String(value ?? "")
    .normalize("NFKC")
    .replace(/\r\n?/g, "\n");
  const firstArticle = text.search(
    /^#{2,6}\s*(?:\*\*)?第一条(?:\*\*)?(?:\s|$)/mu,
  );
  if (firstArticle < 0) return "";
  let core = text.slice(firstArticle);
  core = core.replace(
    /\n---\s*\n(?:\s*>\s*(?:来源|原文链接)\s*[：:].*(?:\n|$))+\s*$/u,
    "",
  );
  const attachment = core.match(
    /(?:\n|(?:施行|生效)[。.;；]\s*)(?:#{1,6}\s*)?附件\s*[：:]/u,
  );
  if (attachment?.index !== undefined) {
    const attachmentLabelIndex = attachment[0].lastIndexOf("附件");
    core = core.slice(0, attachment.index + attachmentLabelIndex);
  }
  return core.replace(/[^\p{L}\p{N}]/gu, "");
}

function evidenceRank(entry) {
  return [
    entry.wjbsSourceType === "AUTHORITY_ISSUED" ? 1 : 0,
    entry.officialIndexMatch ? 1 : 0,
    entry.officialRuleIndexMatch ? 1 : 0,
    entry.officialPageEvidence ? 1 : 0,
    entry.effectiveDate && entry.effectCode ? 1 : 0,
    Number(entry.normalizedTextLength ?? 0),
  ];
}

function compareCanonicalPriority(left, right) {
  const leftRank = evidenceRank(left);
  const rightRank = evidenceRank(right);
  for (let index = 0; index < leftRank.length; index += 1) {
    if (leftRank[index] !== rightRank[index]) return rightRank[index] - leftRank[index];
  }
  return String(left.relativePath).localeCompare(String(right.relativePath), "zh-CN");
}

function metadataIdentityKey(entry) {
  const agencyIdentity = entry.agencyCode
    ? `CODE:${entry.agencyCode}`
    : (entry.agencyName ? `NAME:${normalizedTitle(entry.agencyName)}` : "");
  const requiredComponents = [
    normalizedTitle(entry.title),
    entry.categoryCode,
    agencyIdentity,
    entry.promulgationDate,
    entry.sequenceCode,
    entry.fileTypeCode,
  ].map((value) => String(value ?? ""));
  if (requiredComponents.some((value) => !value)) return "";
  if (!/^[0-9a-f]{64}$/i.test(entry.normalizedTextSha256)) {
    return "";
  }
  return requiredComponents.join("|");
}

function sameContentIdentity(left, right) {
  if (left.normalizedTextSha256 === right.normalizedTextSha256) return true;
  return /^[0-9a-f]{64}$/i.test(left.coreProvisionSha256 ?? "")
    && left.coreProvisionSha256 === right.coreProvisionSha256;
}

function contentIdentityComponents(entries) {
  const pending = new Set(entries.map((_, index) => index));
  const components = [];
  while (pending.size) {
    const first = pending.values().next().value;
    pending.delete(first);
    const componentIndexes = [first];
    for (let cursor = 0; cursor < componentIndexes.length; cursor += 1) {
      const current = componentIndexes[cursor];
      for (const candidate of [...pending]) {
        if (!sameContentIdentity(entries[current], entries[candidate])) continue;
        pending.delete(candidate);
        componentIndexes.push(candidate);
      }
    }
    components.push(componentIndexes.map((index) => entries[index]));
  }
  return components;
}

function versionMetadataKey(entry) {
  return [
    String(entry.effectiveDate ?? ""),
    String(entry.effectCode ?? ""),
  ].join("|");
}

function appendCanonicalGroup(group, canonical, duplicates, reason) {
  const [selected, ...remaining] = [...group].sort(compareCanonicalPriority);
  canonical.push(selected);
  for (const duplicate of remaining) {
    duplicates.push({
      relativePath: duplicate.relativePath,
      canonicalRelativePath: selected.relativePath,
      reason,
    });
  }
}

export function canonicalizeLegalVersions(entries) {
  const groups = new Map();
  const independent = [];
  for (const entry of entries) {
    const key = metadataIdentityKey(entry);
    if (!key) {
      independent.push(entry);
      continue;
    }
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(entry);
  }

  const canonical = [...independent];
  const duplicates = [];
  for (const metadataGroup of groups.values()) {
    for (const group of contentIdentityComponents(metadataGroup)) {
    const byVersionMetadata = new Map();
    for (const entry of group) {
      const metadataKey = versionMetadataKey(entry);
      if (!byVersionMetadata.has(metadataKey)) byVersionMetadata.set(metadataKey, []);
      byVersionMetadata.get(metadataKey).push(entry);
    }
    if (byVersionMetadata.size === 1) {
      appendCanonicalGroup(
        group,
        canonical,
        duplicates,
        "DUPLICATE_NORMALIZED_LEGAL_VERSION",
      );
      continue;
    }
    const officialVersionMetadata = new Set(
      group
        .filter((entry) => (
          entry.officialIndexMatch
          && entry.effectiveDate
          && entry.effectCode
        ))
        .map(versionMetadataKey),
    );
    if (officialVersionMetadata.size === 1) {
      appendCanonicalGroup(
        group,
        canonical,
        duplicates,
        "DUPLICATE_NORMALIZED_LEGAL_VERSION_OFFICIAL_METADATA_RESOLVED",
      );
      continue;
    }
    const completeVersionMetadata = new Set(
      group
        .filter((entry) => entry.effectiveDate && entry.effectCode)
        .map(versionMetadataKey),
    );
    const incompleteMetadataOnly = group.every((entry) => (
      !entry.effectiveDate
      || !entry.effectCode
      || completeVersionMetadata.has(versionMetadataKey(entry))
    ));
    if (completeVersionMetadata.size === 1 && incompleteMetadataOnly) {
      appendCanonicalGroup(
        group,
        canonical,
        duplicates,
        "DUPLICATE_NORMALIZED_LEGAL_VERSION_COMPLETE_METADATA_RESOLVED",
      );
      continue;
    }
    for (const sameMetadataGroup of byVersionMetadata.values()) {
      appendCanonicalGroup(
        sameMetadataGroup,
        canonical,
        duplicates,
        "DUPLICATE_NORMALIZED_LEGAL_VERSION",
      );
    }
    }
  }
  return { canonical, duplicates };
}
