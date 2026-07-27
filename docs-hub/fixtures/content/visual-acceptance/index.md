---
title: Visual acceptance fixtures
description: Owned fixtures for every enabled visual registry format.
---

These fixtures are intentionally owned by Docs Hub. Imported Markdown can only
produce the same allowlisted `docs-visual` placeholders through the directive
converter.

## Excalidraw

<div class="docs-visual" data-format="excalidraw" data-src="/visuals/scene.excalidraw" data-fallback="/visuals/scene.svg" data-caption="An editable Excalidraw source rendered in read-only mode." data-source="/visuals/scene.excalidraw"></div>

## Mermaid

<div class="docs-visual" data-format="mermaid" data-src="/visuals/flow.mmd" data-caption="A Mermaid source with pan and zoom controls." data-source="/visuals/flow.mmd"></div>

## Build-time diagram SVGs

<div class="docs-visual" data-format="d2" data-src="/visuals/d2.svg" data-caption="Deterministic D2 SVG output." data-source="/visuals/flow.d2"></div>
<div class="docs-visual" data-format="graphviz" data-src="/visuals/dot.svg" data-caption="Deterministic Graphviz SVG output." data-source="/visuals/flow.dot"></div>
<div class="docs-visual" data-format="plantuml" data-src="/visuals/plantuml.svg" data-caption="Deterministic PlantUML SVG output." data-source="/visuals/flow.puml"></div>

## Draw.io

<div class="docs-visual" data-format="drawio" data-src="/visuals/drawio.svg" data-fallback="/visuals/drawio.svg" data-caption="Draw.io editable source with a self-hosted SVG fallback." data-source="/visuals/flow.drawio"></div>

## Declarative charts

<div class="docs-visual" data-format="vega-lite" data-src="/visuals/chart.vl.json" data-caption="Vega-Lite declarative bar chart." data-source="/visuals/chart.vl.json"></div>
<div class="docs-visual" data-format="plotly" data-src="/visuals/chart.plotly.json" data-caption="Plotly declarative line chart." data-source="/visuals/chart.plotly.json"></div>

## PDF and OpenAPI

<div class="docs-visual" data-format="pdf" data-src="/visuals/sample.pdf" data-caption="PDF.js page navigation and zoom fixture." data-source="/visuals/sample.pdf"></div>
<div class="docs-visual" data-format="openapi" data-src="/visuals/openapi.json" data-caption="Interactive OpenAPI reference fixture." data-source="/visuals/openapi.json"></div>

## Images and models

<div class="docs-visual" data-format="svg" data-src="/visuals/image.svg" data-caption="Responsive SVG with lightbox-style fullscreen controls." data-source="/visuals/image.svg"></div>
<div class="docs-visual" data-format="raster" data-src="/visuals/raster.png" data-caption="Responsive raster image fixture." data-source="/visuals/raster.png"></div>
<div class="docs-visual" data-format="gltf" data-src="/visuals/triangle.gltf" data-caption="Read-only glTF model with camera controls." data-source="/visuals/triangle.gltf"></div>
<div class="docs-visual" data-format="stl" data-src="/visuals/triangle.stl" data-caption="Read-only STL printing source." data-source="/visuals/triangle.stl"></div>

## GeoJSON and notebook

<div class="docs-visual" data-format="geojson" data-src="/visuals/place.geojson" data-caption="Read-only GeoJSON map." data-source="/visuals/place.geojson"></div>
<div class="docs-visual" data-format="notebook" data-src="/visuals/sample.ipynb" data-caption="Saved notebook Markdown and output; cells are never executed." data-source="/visuals/sample.ipynb"></div>

## Media

<div class="docs-visual" data-format="audio" data-src="/visuals/silent.wav" data-caption="Native audio controls with a transcript fixture." data-source="/visuals/silent.wav" data-transcript="/visuals/captions.vtt"></div>
<div class="docs-visual" data-format="video" data-src="/visuals/silent.mp4" data-caption="Native video controls with a caption fixture." data-source="/visuals/silent.mp4" data-transcript="/visuals/captions.vtt"></div>

## Sandboxed HTML

<div class="docs-visual" data-format="html" data-src="__DOCS_ASSET_ORIGIN__/visuals/untrusted.html" data-caption="Separate-origin sandbox fixture whose repository script is disabled." data-source="/visuals/untrusted.html"></div>
