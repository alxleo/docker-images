const VISUAL_DIRECTIVE =
  /^:::visual\{format="([a-z0-9-]+)"\s+src="([^"]+)"\s+caption="([^"]*)"(?:\s+fallback="([^"]+)")?(?:\s+transcript="([^"]+)")?\}$/gm;

function escapeAttribute(value) {
  return value.replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

export function stripExecutableMarkdown(markdown) {
  return markdown
    .replace(/^---\n[\s\S]*?\n---\n?/u, "")
    .replace(/^(?:import|export)\s+[\s\S]*?;?\s*$/gmu, "")
    .replace(/<\s*(script|style|iframe|object|embed|link|meta)\b[\s\S]*?<\s*\/\s*\1\s*>/giu, "")
    .replace(/<\s*(script|style|iframe|object|embed|link|meta)\b[^>]*\/?\s*>/giu, "")
    .replace(/\son[a-z]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/giu, "")
    .replace(/(?:javascript|vbscript|data)\s*:/giu, "blocked:")
    .replace(/<([A-Z][A-Za-z0-9.]*)\b[^>]*\/?>/gu, "&lt;$1 component removed&gt;")
    // Raw repository HTML is never part of the executable rendering surface.
    // Owned visual placeholders are inserted only after this pass.
    .replace(/<[^>]+>/gu, "");
}

export function convertVisualDirectives(markdown, context) {
  return markdown.replace(VISUAL_DIRECTIVE, (_match, format, source, caption, fallback, transcript) => {
    if (!context.formats?.[format]) {
      throw new Error(`${format}: visual format is not allowlisted`);
    }
    const accessibleCaption = caption.trim();
    if (!accessibleCaption) {
      throw new Error(`${format}: visual directive caption must not be empty`);
    }
    const sourceUrl = context.assetUrl(source, format);
    const fallbackUrl = fallback ? context.assetUrl(fallback, "svg") : "";
    const transcriptUrl = transcript ? context.assetUrl(transcript, "transcript") : "";
    return [
      `<div class="docs-visual" data-format="${escapeAttribute(format)}"`,
      ` data-src="${escapeAttribute(sourceUrl)}"`,
      ` data-caption="${escapeAttribute(accessibleCaption)}"`,
      ` data-source="${escapeAttribute(context.editUrl(source))}"`,
      fallbackUrl ? ` data-fallback="${escapeAttribute(fallbackUrl)}"` : "",
      transcriptUrl ? ` data-transcript="${escapeAttribute(transcriptUrl)}"` : "",
      ' role="figure" aria-label="',
      escapeAttribute(accessibleCaption),
      '"></div>'
    ].join("");
  });
}

export function safeMarkdown(markdown, context) {
  return convertVisualDirectives(stripExecutableMarkdown(markdown), context);
}

export function markdownText(markdown) {
  return stripExecutableMarkdown(markdown)
    .replace(VISUAL_DIRECTIVE, (_match, format, source, caption) => `${caption} (${format}: ${source})`)
    .replace(/```[\s\S]*?```/gu, " ")
    .replace(/!\[([^\]]*)\]\([^)]*\)/gu, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/gu, "$1")
    .replace(/[#>*_`~|-]/gu, " ")
    .replace(/\s+/gu, " ")
    .trim();
}
