export function contentStructurePublicationErrors({
  codeScope,
  structureRows,
  structureFailure,
}) {
  if (codeScope !== "GBT47277" || !structureFailure) return [];
  return [{
    code: structureFailure.startsWith("CONTENT_")
      ? structureFailure
      : "CONTENT_STRUCTURE_PARSE_ERROR",
    field: "DE_02001",
  }];
}

const GBT47277_CORE_FIELDS = Object.freeze([
  "DE_01001", "DE_01002", "DE_01004", "DE_01006", "DE_01007",
  "DE_01014", "DE_01015", "DE_01018", "DE_01019", "DE_01020", "DE_01021",
]);

export function required47277CoreFields({ fulltextAvailable = true } = {}) {
  return fulltextAvailable
    ? [...GBT47277_CORE_FIELDS]
    : GBT47277_CORE_FIELDS.filter((field) => field !== "DE_01019");
}

export function formalLawPublicationDecision({
  lawErrors,
  publicationErrors,
  fulltextAvailable = true,
}) {
  if (lawErrors.length === 0) {
    const contentErrors = [...publicationErrors];
    return {
      publishFormal: true,
      emitMarkdown: fulltextAvailable,
      emitStructuredContents: fulltextAvailable && contentErrors.length === 0,
      ingestStatus: !fulltextAvailable
        ? "READY_FORMAL_LAW_METADATA_ONLY"
        : contentErrors.length
          ? "READY_FORMAL_LAW_UNSTRUCTURED_FULLTEXT"
          : "READY_FORMAL_LAW",
      targetRelativePath: null,
      formalErrors: [],
      contentErrors,
    };
  }
  return {
    publishFormal: false,
    emitMarkdown: false,
    emitStructuredContents: false,
    ingestStatus: "BLOCKED_STANDARD_FIELDS",
    targetRelativePath: "",
    formalErrors: [...lawErrors],
    contentErrors: [...publicationErrors],
  };
}
