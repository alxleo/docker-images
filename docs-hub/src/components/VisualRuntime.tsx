import { useEffect } from "react";
import { createRoot } from "react-dom/client";
import "@excalidraw/excalidraw/index.css";
import "leaflet/dist/leaflet.css";

type VisualElement = HTMLElement & {
  dataset: DOMStringMap & {
    format?: string;
    src?: string;
    fallback?: string;
    caption?: string;
    source?: string;
    transcript?: string;
  };
};

function button(label: string, action: () => void): HTMLButtonElement {
  const element = document.createElement("button");
  element.type = "button";
  element.textContent = label;
  element.addEventListener("click", action);
  return element;
}

function link(label: string, href: string): HTMLAnchorElement {
  const element = document.createElement("a");
  element.textContent = label;
  element.href = href;
  element.target = "_blank";
  element.rel = "noopener noreferrer";
  return element;
}

function visualChrome(host: VisualElement): {
  toolbar: HTMLDivElement;
  surface: HTMLDivElement;
} {
  host.replaceChildren();
  const toolbar = document.createElement("div");
  toolbar.className = "docs-visual__toolbar";
  const surface = document.createElement("div");
  surface.className = "docs-visual__surface";
  host.append(toolbar, surface);
  if (host.dataset.source) {
    toolbar.append(link("Source / edit", host.dataset.source));
  }
  if (host.dataset.fallback) {
    toolbar.append(link("SVG fallback", host.dataset.fallback));
  }
  if (host.dataset.caption) {
    const caption = document.createElement("div");
    caption.className = "docs-visual__caption";
    caption.textContent = host.dataset.caption;
    host.append(caption);
  }
  return { toolbar, surface };
}

function installPanZoom(toolbar: HTMLElement, surface: HTMLElement): void {
  let scale = 1;
  const apply = () => {
    const child = surface.firstElementChild as HTMLElement | null;
    if (child) {
      child.style.transformOrigin = "top left";
      child.style.transform = `scale(${scale})`;
    }
  };
  toolbar.append(
    button("−", () => {
      scale = Math.max(0.25, scale - 0.25);
      apply();
    }),
    button("+", () => {
      scale = Math.min(4, scale + 0.25);
      apply();
    }),
    button("Reset", () => {
      scale = 1;
      apply();
    }),
    button("Fullscreen", () => void surface.requestFullscreen())
  );
}

async function renderExcalidraw(host: VisualElement, src: string): Promise<void> {
  const { toolbar, surface } = visualChrome(host);
  const [{ Excalidraw }, scene] = await Promise.all([
    import("@excalidraw/excalidraw"),
    fetch(src, { credentials: "same-origin" }).then((response) => response.json())
  ]);
  toolbar.append(button("Fullscreen", () => void surface.requestFullscreen()));
  surface.style.height = "min(70vh, 48rem)";
  createRoot(surface).render(
    // Imported scenes remain editable source files, but the published viewer is
    // intentionally read-only. Links, pan, zoom, fullscreen, and theme remain.
    <Excalidraw
      initialData={scene}
      viewModeEnabled
      zenModeEnabled
      gridModeEnabled={false}
      theme={document.documentElement.dataset.theme === "dark" ? "dark" : "light"}
    />
  );
}

async function renderMermaid(host: VisualElement, src: string): Promise<void> {
  const { toolbar, surface } = visualChrome(host);
  const [{ default: mermaid }, source] = await Promise.all([
    import("mermaid"),
    fetch(src, { credentials: "same-origin" }).then((response) => response.text())
  ]);
  mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "neutral" });
  const result = await mermaid.render(`diagram-${crypto.randomUUID()}`, source);
  surface.innerHTML = result.svg;
  installPanZoom(toolbar, surface);
  toolbar.append(link("Diagram source", src));
}

async function renderPdf(host: VisualElement, src: string): Promise<void> {
  const { toolbar, surface } = visualChrome(host);
  const pdfjs = await import("pdfjs-dist");
  const worker = await import("pdfjs-dist/build/pdf.worker.mjs?url");
  pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
  const documentProxy = await pdfjs.getDocument(src).promise;
  let pageNumber = 1;
  let scale = 1.15;
  const canvas = document.createElement("canvas");
  surface.append(canvas);
  const render = async () => {
    const page = await documentProxy.getPage(pageNumber);
    const viewport = page.getViewport({ scale });
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Canvas unavailable");
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    await page.render({ canvas, canvasContext: context, viewport }).promise;
  };
  const status = document.createElement("span");
  const searchInput = document.createElement("input");
  searchInput.type = "search";
  searchInput.placeholder = "Search PDF text";
  searchInput.setAttribute("aria-label", "Search PDF text");
  const searchStatus = document.createElement("span");
  searchStatus.setAttribute("role", "status");
  const update = async () => {
    status.textContent = `${pageNumber} / ${documentProxy.numPages}`;
    await render();
  };
  const search = async () => {
    const query = searchInput.value.trim().toLocaleLowerCase();
    if (!query) {
      searchStatus.textContent = "Enter text to search";
      return;
    }
    searchStatus.textContent = "Searching…";
    for (let candidate = 1; candidate <= documentProxy.numPages; candidate += 1) {
      const page = await documentProxy.getPage(candidate);
      const text = await page.getTextContent();
      const contents = text.items
        .map((item) => ("str" in item ? item.str : ""))
        .join(" ")
        .toLocaleLowerCase();
      if (contents.includes(query)) {
        pageNumber = candidate;
        await update();
        searchStatus.textContent = `Found on page ${candidate}`;
        return;
      }
    }
    searchStatus.textContent = "No match";
  };
  searchInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") void search();
  });
  toolbar.append(
    button("Previous", () => {
      pageNumber = Math.max(1, pageNumber - 1);
      void update();
    }),
    status,
    button("Next", () => {
      pageNumber = Math.min(documentProxy.numPages, pageNumber + 1);
      void update();
    }),
    button("−", () => {
      scale = Math.max(0.5, scale - 0.2);
      void render();
    }),
    button("+", () => {
      scale = Math.min(3, scale + 0.2);
      void render();
    }),
    searchInput,
    button("Search", () => void search()),
    searchStatus,
    link("Download", src)
  );
  await update();
}

async function renderChart(host: VisualElement, src: string, format: string): Promise<void> {
  const { toolbar, surface } = visualChrome(host);
  const spec = await fetch(src, { credentials: "same-origin" }).then((response) => response.json());
  if (format === "vega-lite") {
    const { default: embed } = await import("vega-embed");
    await embed(surface, spec, { actions: true, renderer: "svg" });
  } else {
    const plotlyModule = await import("plotly.js-dist-min");
    const Plotly = "default" in plotlyModule ? plotlyModule.default : plotlyModule;
    await Plotly.newPlot(surface, spec.data ?? [], spec.layout ?? {}, {
      responsive: true,
      displaylogo: false
    });
  }
  toolbar.append(link("Declarative source", src));
}

async function renderGeoJson(host: VisualElement, src: string): Promise<void> {
  const { toolbar, surface } = visualChrome(host);
  const [{ default: L }, data] = await Promise.all([
    import("leaflet"),
    fetch(src, { credentials: "same-origin" }).then((response) => response.json())
  ]);
  surface.style.height = "28rem";
  const map = L.map(surface, { zoomControl: true, attributionControl: false }).setView([51.5, -0.1], 8);
  const layer = L.geoJSON(data).addTo(map);
  const bounds = layer.getBounds();
  if (bounds.isValid()) map.fitBounds(bounds.pad(0.1));
  toolbar.append(link("GeoJSON source", src));
}

async function renderOpenApi(host: VisualElement, src: string): Promise<void> {
  const { toolbar, surface } = visualChrome(host);
  const { createApiReference } = await import("@scalar/api-reference");
  createApiReference(surface, {
    url: src,
    hideClientButton: true,
    hideModels: false,
    darkMode: document.documentElement.dataset.theme === "dark"
  });
  toolbar.append(link("OpenAPI source", src));
}

async function renderModel(host: VisualElement, src: string, format: string): Promise<void> {
  const { toolbar, surface } = visualChrome(host);
  if (format === "stl") {
    const [THREE, { STLLoader }, { OrbitControls }] = await Promise.all([
      import("three"),
      import("three/examples/jsm/loaders/STLLoader.js"),
      import("three/examples/jsm/controls/OrbitControls.js")
    ]);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 10_000);
    const geometry = await new STLLoader().loadAsync(src);
    geometry.computeVertexNormals();
    geometry.center();
    const material = new THREE.MeshStandardMaterial({
      color: 0x6c8cff,
      metalness: 0.05,
      roughness: 0.65
    });
    const mesh = new THREE.Mesh(geometry, material);
    scene.add(mesh);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x303040, 2.5));
    const directional = new THREE.DirectionalLight(0xffffff, 2);
    directional.position.set(2, 3, 4);
    scene.add(directional);
    const bounds = new THREE.Box3().setFromObject(mesh);
    const size = bounds.getSize(new THREE.Vector3()).length() || 1;
    camera.position.set(size, size * 0.8, size * 1.5);
    camera.near = Math.max(size / 10_000, 0.001);
    camera.far = size * 100;
    camera.updateProjectionMatrix();
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.target.set(0, 0, 0);
    surface.style.height = "min(60vh, 36rem)";
    surface.append(renderer.domElement);
    const resize = () => {
      const width = Math.max(surface.clientWidth, 320);
      const height = Math.max(surface.clientHeight, 240);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(surface);
    resize();
    const animate = () => {
      if (!renderer.domElement.isConnected) {
        observer.disconnect();
        controls.dispose();
        geometry.dispose();
        material.dispose();
        renderer.dispose();
        return;
      }
      controls.update();
      renderer.render(scene, camera);
      requestAnimationFrame(animate);
    };
    requestAnimationFrame(animate);
    toolbar.append(button("Reset camera", () => controls.reset()));
  } else {
    await import("@google/model-viewer");
    const model = document.createElement("model-viewer");
    model.setAttribute("src", src);
    model.setAttribute("camera-controls", "");
    model.setAttribute("auto-rotate", "");
    model.setAttribute("interaction-prompt", "auto");
    surface.append(model);
  }
  toolbar.append(link("Model source", src));
}

async function renderNotebook(host: VisualElement, src: string): Promise<void> {
  const { toolbar, surface } = visualChrome(host);
  const notebook = await fetch(src, { credentials: "same-origin" }).then((response) => response.json());
  surface.classList.add("docs-notebook");
  for (const [index, cell] of (notebook.cells ?? []).entries()) {
    const section = document.createElement("section");
    section.className = "docs-notebook__cell";
    const heading = document.createElement("h3");
    heading.textContent = `${cell.cell_type === "markdown" ? "Markdown" : "Code"} cell ${index + 1}`;
    const source = document.createElement("pre");
    source.textContent = Array.isArray(cell.source) ? cell.source.join("") : String(cell.source ?? "");
    section.append(heading, source);
    for (const output of cell.outputs ?? []) {
      const data = output.data ?? {};
      const text =
        (Array.isArray(output.text) ? output.text.join("") : output.text) ??
        (Array.isArray(data["text/markdown"]) ? data["text/markdown"].join("") : data["text/markdown"]) ??
        (Array.isArray(data["text/plain"]) ? data["text/plain"].join("") : data["text/plain"]);
      if (text) {
        const saved = document.createElement("pre");
        saved.className = "docs-notebook__output";
        saved.textContent = String(text);
        section.append(saved);
      }
      const png = Array.isArray(data["image/png"]) ? data["image/png"].join("") : data["image/png"];
      if (png) {
        const image = document.createElement("img");
        image.src = `data:image/png;base64,${png}`;
        image.alt = `Saved output from notebook cell ${index + 1}`;
        section.append(image);
      }
      // Saved text/html and JavaScript outputs are deliberately ignored.
    }
    surface.append(section);
  }
  toolbar.append(link("Notebook source", src));
}

function renderMedia(host: VisualElement, src: string, format: string): void {
  const { toolbar, surface } = visualChrome(host);
  const media = document.createElement(format === "audio" ? "audio" : "video");
  media.controls = true;
  media.preload = "metadata";
  media.src = src;
  if (host.dataset.transcript) {
    const track = document.createElement("track");
    track.kind = format === "video" ? "captions" : "descriptions";
    track.src = host.dataset.transcript;
    track.srclang = "en";
    track.label = "English";
    track.default = true;
    media.append(track);
  }
  surface.append(media);
  toolbar.append(link("Download", src));
  if (host.dataset.transcript) toolbar.append(link("Transcript / captions", host.dataset.transcript));
}

function renderImage(host: VisualElement, src: string): void {
  const { toolbar, surface } = visualChrome(host);
  const image = document.createElement("img");
  image.src = src;
  image.alt = host.dataset.caption ?? "";
  image.loading = "lazy";
  surface.append(image);
  installPanZoom(toolbar, surface);
}

function renderSandbox(host: VisualElement, src: string): void {
  const url = new URL(src, window.location.href);
  if (url.origin !== __DOCS_ASSET_ORIGIN__) {
    throw new Error(`sandbox asset must use ${__DOCS_ASSET_ORIGIN__}`);
  }
  const { toolbar, surface } = visualChrome(host);
  const frame = document.createElement("iframe");
  frame.src = url.href;
  // Intentionally leave the iframe sandbox token set empty. Imported HTML may
  // render inert markup on the separate asset origin, but cannot run scripts,
  // submit forms, open popups, or escape to the top-level documentation origin.
  frame.setAttribute("sandbox", "");
  frame.referrerPolicy = "no-referrer";
  frame.loading = "lazy";
  surface.append(frame);
  toolbar.append(link("Open sandboxed asset", url.href));
}

async function installRefreshControl(): Promise<void> {
  if (document.querySelector("[data-docs-refresh]")) return;
  const container = document.createElement("div");
  container.dataset.docsRefresh = "true";
  container.style.cssText =
    "position:fixed;right:1rem;bottom:1rem;z-index:30;display:flex;gap:.4rem;align-items:center;padding:.5rem;background:var(--sl-color-bg-nav);border:1px solid var(--sl-color-gray-5);border-radius:.65rem";
  const source = document.createElement("select");
  source.setAttribute("aria-label", "Documentation source to refresh");
  source.append(new Option("All sources", ""));
  try {
    const sources = await fetch("/api/v1/sources", { credentials: "same-origin" }).then((response) =>
      response.ok ? response.json() : []
    );
    for (const item of sources) source.append(new Option(item.label, item.id));
  } catch {
    // The current published site stays usable if the controller is unavailable.
  }
  const status = document.createElement("span");
  status.setAttribute("role", "status");
  const refresh = button("Refresh mirrors", async () => {
    refresh.disabled = true;
    status.textContent = "Refreshing…";
    try {
      const response = await fetch("/api/v1/admin/refresh", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: source.value })
      });
      if (!response.ok) throw new Error(`refresh returned ${response.status}`);
      status.textContent = "Published";
    } catch (error) {
      status.textContent = error instanceof Error ? error.message : "Refresh failed";
    } finally {
      refresh.disabled = false;
    }
  });
  container.append(source, refresh, status);
  document.body.append(container);
}

async function renderVisual(host: VisualElement): Promise<void> {
  const format = host.dataset.format ?? "";
  const src = host.dataset.src ?? "";
  if (!src) throw new Error("visual source is missing");
  if (format === "excalidraw") return renderExcalidraw(host, src);
  if (format === "mermaid") return renderMermaid(host, src);
  if (format === "pdf") return renderPdf(host, src);
  if (format === "vega-lite" || format === "plotly") return renderChart(host, src, format);
  if (format === "geojson") return renderGeoJson(host, src);
  if (format === "openapi") return renderOpenApi(host, src);
  if (["gltf", "glb", "stl"].includes(format)) return renderModel(host, src, format);
  if (format === "notebook") return renderNotebook(host, src);
  if (["audio", "video"].includes(format)) return renderMedia(host, src, format);
  if (format === "html" || format === "iframe") return renderSandbox(host, src);
  // Build-time diagram SVG, Draw.io fallback, SVG, and raster images share
  // the same read-only pan/zoom/lightbox surface.
  return renderImage(host, src);
}

export default function VisualRuntime(): null {
  useEffect(() => {
    void installRefreshControl();
    for (const host of document.querySelectorAll<VisualElement>(".docs-visual")) {
      if (host.dataset.hydrated === "true") continue;
      host.dataset.hydrated = "true";
      void renderVisual(host)
        .then(() => {
          host.dataset.ready = "true";
        })
        .catch((error: unknown) => {
          host.replaceChildren();
          const message = document.createElement("p");
          message.className = "docs-visual__error";
          message.textContent = error instanceof Error ? error.message : "Visual failed to render";
          host.append(message);
          if (host.dataset.fallback) host.append(link("Open fallback", host.dataset.fallback));
        });
    }
  }, []);
  return null;
}
