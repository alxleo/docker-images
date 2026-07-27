import path from "node:path";
import { fileURLToPath } from "node:url";
import { markdownText } from "./sanitize.mjs";

function collectStrings(value, keys = new Set(["text", "label", "title", "description", "summary"])) {
  const output = [];
  const visit = (node, key = "") => {
    if (typeof node === "string" && (keys.has(key) || key === "")) {
      output.push(node);
    } else if (Array.isArray(node)) {
      for (const item of node) visit(item, key);
    } else if (node && typeof node === "object") {
      for (const [childKey, child] of Object.entries(node)) visit(child, childKey);
    }
  };
  visit(value);
  return output.join(" ");
}

function notebookText(notebook) {
  const text = [];
  for (const cell of notebook.cells ?? []) {
    if (Array.isArray(cell.source)) text.push(cell.source.join(""));
    for (const output of cell.outputs ?? []) {
      if (Array.isArray(output.text)) text.push(output.text.join(""));
      if (output.data?.["text/plain"]) text.push(output.data["text/plain"].join(""));
      // Saved textual output is indexed; HTML/JavaScript output is never run.
      if (output.data?.["text/markdown"]) text.push(output.data["text/markdown"].join(""));
    }
  }
  return text.join("\n");
}

export function extractText(relativePath, buffer) {
  const lower = relativePath.toLowerCase();
  const text = buffer.toString("utf8");
  if (lower.endsWith(".md") || lower.endsWith(".mdx")) return markdownText(text);
  if (lower.endsWith(".svg")) {
    return text
      .replace(/<script[\s\S]*?<\/script>/giu, " ")
      .replace(/<[^>]+>/gu, " ")
      .replace(/&(?:amp|lt|gt|quot|apos);/gu, " ")
      .replace(/\s+/gu, " ")
      .trim();
  }
  if (lower.endsWith(".excalidraw")) {
    try {
      return collectStrings(JSON.parse(text), new Set(["text", "originalText", "label"]));
    } catch {
      return "";
    }
  }
  if (lower.endsWith(".ipynb")) {
    try {
      return notebookText(JSON.parse(text));
    } catch {
      return "";
    }
  }
  if (
    lower.endsWith(".json") ||
    lower.endsWith(".geojson") ||
    lower.endsWith(".yaml") ||
    lower.endsWith(".yml")
  ) {
    try {
      return collectStrings(JSON.parse(text));
    } catch {
      return text.replace(/\s+/gu, " ").slice(0, 200_000);
    }
  }
  if (
    [".d2", ".dot", ".gv", ".puml", ".plantuml", ".mmd", ".mermaid", ".vtt"].includes(
      path.extname(lower)
    )
  ) {
    return text.replace(/[{}[\]();#<>-]/gu, " ").replace(/\s+/gu, " ").trim();
  }
  // PDF text is extracted by the build image's PDF.js verifier when possible.
  // Binary-only visuals remain discoverable through required captions.
  return "";
}

async function pdfText(buffer) {
  try {
    const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs");
    const standardFontDataUrl = fileURLToPath(
      new URL("../../standard_fonts/", import.meta.resolve("pdfjs-dist/legacy/build/pdf.mjs"))
    );
    const loadingTask = pdfjs.getDocument({
      data: new Uint8Array(buffer),
      disableFontFace: true,
      useSystemFonts: false,
      standardFontDataUrl
    });
    const document = await loadingTask.promise;
    const text = [];
    for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
      const page = await document.getPage(pageNumber);
      const content = await page.getTextContent();
      text.push(content.items.map((item) => ("str" in item ? item.str : "")).join(" "));
    }
    await loadingTask.destroy();
    return text.join("\n");
  } catch {
    return "";
  }
}

export async function buildDocument({ source, relativePath, sha, mimeType, renderedUrl, buffer, builtAt }) {
  return {
    source,
    path: relativePath,
    commitSha: sha,
    mimeType,
    renderedUrl,
    buildTimestamp: builtAt,
    text: relativePath.toLowerCase().endsWith(".pdf") ? await pdfText(buffer) : extractText(relativePath, buffer)
  };
}

export function searchCorpus(corpus, { query = "", source = "", pathPrefix = "" }) {
  const terms = query
    .toLowerCase()
    .split(/\s+/u)
    .filter(Boolean);
  return corpus
    .filter((document) => !source || document.source === source)
    .filter((document) => !pathPrefix || document.path.startsWith(pathPrefix))
    .map((document) => {
      const haystack = `${document.path} ${document.text}`.toLowerCase();
      const score = terms.reduce((total, term) => total + (haystack.includes(term) ? 1 : 0), 0);
      return { ...document, score };
    })
    .filter((document) => terms.length === 0 || document.score === terms.length)
    .sort((left, right) => right.score - left.score || left.path.localeCompare(right.path))
    .slice(0, 100);
}
