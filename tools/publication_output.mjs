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

export function formalLawPublicationDecision({ lawErrors, publicationErrors }) {
  const formalErrors = [...lawErrors, ...publicationErrors];
  if (formalErrors.length === 0) {
    return {
      publishFormal: true,
      emitMarkdown: true,
      ingestStatus: "READY_FORMAL_LAW",
      targetRelativePath: null,
      formalErrors,
    };
  }
  return {
    publishFormal: false,
    emitMarkdown: false,
    ingestStatus: publicationErrors.length
      ? "BLOCKED_CONTENT_STRUCTURE"
      : "BLOCKED_STANDARD_FIELDS",
    targetRelativePath: "",
    formalErrors,
  };
}
