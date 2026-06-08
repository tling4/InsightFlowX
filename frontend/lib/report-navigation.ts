export function reportAnchorId(kind: "section" | "subsection", label: string) {
  let hash = 0;
  for (const char of label) {
    hash = (hash * 31 + char.codePointAt(0)!) >>> 0;
  }
  return `report-${kind}-${hash.toString(36)}`;
}

export function extractReportSubheadings(content: string) {
  return Array.from(content.matchAll(/^\s*\*\*([^*\n]+)\*\*\s*$/gm), (match) => match[1].trim());
}

export function normalizeReportMarkdown(markdown: string) {
  return markdown
    .replace(
      /^[ \t]*\*\*([^*\n]+)\*\*[ \t]*$/gm,
      (_, label: string) => `\n\n**${label.trim()}**\n\n`,
    )
    .replace(/\n{3,}/g, "\n\n");
}
