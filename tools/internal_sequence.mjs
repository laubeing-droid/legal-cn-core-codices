export function assignInternalSequenceGroup(entries) {
  if (!Array.isArray(entries) || entries.length === 0) return [];
  if (entries.length > 999) throw new Error("INTERNAL_SEQUENCE_GROUP_OVERFLOW");
  if (entries.length === 1) {
    const decisionOrder = entries[0].officialDecisionOrder;
    if (Number.isInteger(decisionOrder) && decisionOrder >= 0 && decisionOrder <= 999) {
      return [{
        entry: entries[0],
        internalSequence: String(decisionOrder).padStart(3, "0"),
        source: "SOURCE_DECISION_BODY_ORDER",
      }];
    }
    return [{
      entry: entries[0],
      internalSequence: "000",
      source: "UNIQUE_COMPONENTS",
    }];
  }

  const validOrderCounts = new Map();
  for (const entry of entries) {
    const order = entry.officialDecisionOrder;
    if (!Number.isInteger(order) || order < 0 || order > 999) continue;
    validOrderCounts.set(order, (validOrderCounts.get(order) ?? 0) + 1);
  }
  return entries.map((entry, index) => ({ entry, index }))
    .sort((left, right) => {
      const leftOrder = left.entry.officialDecisionOrder;
      const rightOrder = right.entry.officialDecisionOrder;
      const leftKnown = Number.isInteger(leftOrder) && validOrderCounts.get(leftOrder) === 1;
      const rightKnown = Number.isInteger(rightOrder) && validOrderCounts.get(rightOrder) === 1;
      if (leftKnown !== rightKnown) return leftKnown ? -1 : 1;
      if (leftKnown && rightKnown) return leftOrder - rightOrder;
      return left.index - right.index;
    })
    .map(({ entry }) => {
    const order = entry.officialDecisionOrder;
    const uniquelyEvidenced = Number.isInteger(order)
      && order >= 0
      && order <= 999
      && validOrderCounts.get(order) === 1;
    const duplicateEvidencedOrder = Number.isInteger(order)
      && order >= 0
      && order <= 999
      && (validOrderCounts.get(order) ?? 0) > 1;
    return {
      entry,
      internalSequence: uniquelyEvidenced ? String(order).padStart(3, "0") : "",
      source: uniquelyEvidenced
        ? "SOURCE_DECISION_BODY_ORDER"
        : duplicateEvidencedOrder
          ? "BLOCKED_AUTHORITY_ASSIGNED_INTERNAL_SEQUENCE"
          : "BLOCKED_MISSING_OFFICIAL_DECISION_ORDER",
    };
    });
}
