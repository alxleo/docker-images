# Manyfold native curation

| Native behavior | Fix | Retirement condition |
| --- | --- | --- |
| OAuth model merge | Existing `write` scope reaches the native merge policy; read-only and delete-only tokens stay excluded. | Upstream maps merge to its write scope. |
| Collection assignment | Resolve editable collection references into records. | Upstream fixes `ModelDeserializer.isPartOf`. |
| Merge collisions | Remove duplicate source files, retain distinct files with unique native IDs, fail on an unsuccessful move. | Upstream passes the same scan-after-merge checks. |
| File writeback | Copy open request streams and retain canonical filenames/MIME types. | Upstream handles unlinked Puma tempfiles and record-owned attachment metadata. |

This image changes the pinned application's own sources at build time. It adds no
runtime patch loader, controller, service or credentials. Per-image acceptance
runs native Rails requests and file operations against the built image before
publication. The upstream base and image tag are pinned in the Dockerfile and
`.ci.json`; update them together and remove fixes when their native checks pass.
