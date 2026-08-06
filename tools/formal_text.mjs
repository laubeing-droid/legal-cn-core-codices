export const fixedPollutionPattern = /本文由律锥[·・]?\s*Legalskill|智法AI|云法律网|^\s*-\s*IMA(?:知识库|条目ID)\s*[：:]/im;
export const embeddedAbsolutePathPattern = /[A-Za-z]:[\\/][^\s<>"'`)]+/g;

export function sanitizeFormalText(sourceBody) {
  let removedPollutionLines = 0;
  let removedAbsolutePaths = 0;
  const unsafeControlCharacters = sourceBody.match(
    /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/gu,
  ) ?? [];
  const withoutControls = sourceBody.replace(
    /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/gu,
    "",
  );
  const withoutPollution = withoutControls
    .split(/\r?\n/)
    .filter((line) => {
      if (!fixedPollutionPattern.test(line)) return true;
      removedPollutionLines += 1;
      return false;
    })
    .join("\n");
  const text = withoutPollution.replace(embeddedAbsolutePathPattern, () => {
    removedAbsolutePaths += 1;
    return "[本机路径已移除]";
  }).trim();
  return {
    text,
    removedPollutionLines,
    removedAbsolutePaths,
    removedUnsafeControlCharacters: unsafeControlCharacters.length,
  };
}
