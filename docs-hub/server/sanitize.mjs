const VISUAL_DIRECTIVE =
  /^:::visual\{format="([a-z0-9-]+)"\s+src="([^"]+)"\s+caption="([^"]*)"(?:\s+fallback="([^"]+)")?(?:\s+transcript="([^"]+)")?\}$/gm;
const MARKDOWN_IMAGE = /(!\[[^\]]*\]\()([^)\s]+)((?:\s+(?:"[^"]*"|'[^']*'|\([^)]*\)))?\))/gu;

function escapeAttribute(value) {
  return value.replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function rewriteOutsideInlineCode(markdown, rewrite) {
  let output = "";
  let plainStart = 0;
  let cursor = 0;
  while (cursor < markdown.length) {
    const open = markdown.indexOf("`", cursor);
    if (open === -1) break;
    let markerLength = 1;
    while (markdown[open + markerLength] === "`") markerLength += 1;
    let search = open + markerLength;
    let close = -1;
    while (search < markdown.length) {
      const candidate = markdown.indexOf("`", search);
      if (candidate === -1) break;
      let candidateLength = 1;
      while (markdown[candidate + candidateLength] === "`") candidateLength += 1;
      if (candidateLength === markerLength) {
        close = candidate;
        break;
      }
      search = candidate + candidateLength;
    }
    if (close === -1) {
      cursor = open + markerLength;
      continue;
    }
    output += rewrite(markdown.slice(plainStart, open));
    const codeEnd = close + markerLength;
    output += markdown.slice(open, codeEnd);
    plainStart = codeEnd;
    cursor = codeEnd;
  }
  return output + rewrite(markdown.slice(plainStart));
}

function rewriteOutsideCode(markdown, rewrite) {
  const lines = markdown.split(/(?<=\n)/u);
  let output = "";
  let plain = "";
  let fence = null;
  for (const line of lines) {
    if (fence) {
      output += line;
      const close = line.match(/^ {0,3}(`+|~+)[\t ]*(?:\r?\n)?$/u);
      if (close && close[1][0] === fence.character && close[1].length >= fence.length) fence = null;
      continue;
    }
    const open = line.match(/^ {0,3}(`{3,}|~{3,})/u);
    if (open) {
      output += rewriteOutsideInlineCode(plain, rewrite);
      plain = "";
      output += line;
      fence = { character: open[1][0], length: open[1].length };
      continue;
    }
    plain += line;
  }
  return output + rewriteOutsideInlineCode(plain, rewrite);
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

export function rewriteRelativeMarkdownImages(markdown, context) {
  return rewriteOutsideCode(markdown, (prose) =>
    prose.replace(MARKDOWN_IMAGE, (match, prefix, source, suffix) => {
      if (/^(?:[a-z][a-z0-9+.-]*:|\/|#)/iu.test(source)) return match;
      return `${prefix}${context.assetUrl(source)}${suffix}`;
    })
  );
}

export function safeMarkdown(markdown, context) {
  return convertVisualDirectives(rewriteRelativeMarkdownImages(stripExecutableMarkdown(markdown), context), context);
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
