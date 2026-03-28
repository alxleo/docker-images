# Changelog

## [1.1.0](https://github.com/alxleo/docker-images/compare/pr-reviewer/v1.0.0...pr-reviewer/v1.1.0) (2026-03-28)


### Features

* add pr-reviewer image (AI CLI + GitHub watcher) ([f9f27b7](https://github.com/alxleo/docker-images/commit/f9f27b785156b7b6fcee5f9a838ca697127bfe3d))
* **pr-reviewer:** backlog batch — commit status, checksums, shuffle, tests ([#44](https://github.com/alxleo/docker-images/issues/44)) ([76da3d4](https://github.com/alxleo/docker-images/commit/76da3d45ceb920878e504f1376c8b302c2481aa2))
* **pr-reviewer:** Gitea webhook handler + shared review core ([#40](https://github.com/alxleo/docker-images/issues/40)) ([ea943cc](https://github.com/alxleo/docker-images/commit/ea943ccdfde41ebef128fa82586db3c2c65e20d8))
* **pr-reviewer:** GitHub App auth + on-demand triggers ([#24](https://github.com/alxleo/docker-images/issues/24)) ([851aab1](https://github.com/alxleo/docker-images/commit/851aab1a4c4e0a3eccfec2825ec234e4b7b4cf30))
* **pr-reviewer:** inline review comments + architecture lens ([#38](https://github.com/alxleo/docker-images/issues/38)) ([8cb3998](https://github.com/alxleo/docker-images/commit/8cb3998b9db663601b81d5f545031e820540b7c9))
* **pr-reviewer:** LLM-planned search queries for cross-file context ([#48](https://github.com/alxleo/docker-images/issues/48)) ([6669ee6](https://github.com/alxleo/docker-images/commit/6669ee6cc984cc43111dbbda878f7eec046cf63f))
* **pr-reviewer:** multi-org GitHub App auth ([#73](https://github.com/alxleo/docker-images/issues/73)) ([4602a96](https://github.com/alxleo/docker-images/commit/4602a96b162aad9e729922ab3f3cbda5ddac8f43))
* **pr-reviewer:** observability, inline comments, PageRank repomap ([#70](https://github.com/alxleo/docker-images/issues/70)) ([2f97e7a](https://github.com/alxleo/docker-images/commit/2f97e7a942b637a1a09517d343fd816274fa3d83))
* **pr-reviewer:** Tier 2 orchestrator — single Claude session with sub-agents ([#43](https://github.com/alxleo/docker-images/issues/43)) ([6e4a4a4](https://github.com/alxleo/docker-images/commit/6e4a4a4cdd37ded0f4e94b6de1c6d24d6370f3b2))
* **pr-reviewer:** upgrade gh_watcher to Tier 2 orchestrator ([#47](https://github.com/alxleo/docker-images/issues/47)) ([7bce4e9](https://github.com/alxleo/docker-images/commit/7bce4e9a034570a3311a4b672b9632b46e23bd89))
* **pr-reviewer:** user feedback + bug fixes ([#56](https://github.com/alxleo/docker-images/issues/56)) ([fa43639](https://github.com/alxleo/docker-images/commit/fa4363906f086b1d4e3b4c17ab01e59dc94e041c))
* **pr-reviewer:** v2 — enhanced prompts, structural context, intelligent routing ([#41](https://github.com/alxleo/docker-images/issues/41)) ([7a0d9f3](https://github.com/alxleo/docker-images/commit/7a0d9f3bcdcfcccb1aa7a938532a5de5ecb8b52c))


### Bug Fixes

* add OCI source labels to all Dockerfiles ([#81](https://github.com/alxleo/docker-images/issues/81)) ([3bf3571](https://github.com/alxleo/docker-images/commit/3bf35716729caf2c0fe11d41014d78aeb5b5fdd5))
* address Copilot review feedback on pr-reviewer ([#23](https://github.com/alxleo/docker-images/issues/23)) ([48fda38](https://github.com/alxleo/docker-images/commit/48fda385b7abcdcff036e126f1f105fe3b34d484))
* pass pr-reviewer prompts via stdin ([#22](https://github.com/alxleo/docker-images/issues/22)) ([913b1c1](https://github.com/alxleo/docker-images/commit/913b1c154f58d72f362b49a22320b1f91edfd209))
* **pr-reviewer:** file-based secrets + dead code cleanup ([#74](https://github.com/alxleo/docker-images/issues/74)) ([0da758b](https://github.com/alxleo/docker-images/commit/0da758bff91c751cf714a52ff5e4aa19506aaa35))
* **pr-reviewer:** post_status_comment crash on GitHub API pagination ([#62](https://github.com/alxleo/docker-images/issues/62)) ([6874cfd](https://github.com/alxleo/docker-images/commit/6874cfd9435a030f31397883ece1821fcb2e6f32))
* **pr-reviewer:** stop deleting old reviews ([#63](https://github.com/alxleo/docker-images/issues/63)) ([b11c678](https://github.com/alxleo/docker-images/commit/b11c678e96a0ab3f895674a35c2ad3d7f7ba0c39))
* **pr-reviewer:** stringify app_id in JWT iss claim ([#35](https://github.com/alxleo/docker-images/issues/35)) ([df48e09](https://github.com/alxleo/docker-images/commit/df48e09cccd38459c97e967ae671d26e15b3791d))
* use GCR mirror to avoid Docker Hub rate limits in CI ([#75](https://github.com/alxleo/docker-images/issues/75)) ([7d8453e](https://github.com/alxleo/docker-images/commit/7d8453e14f5d5fae3631aacd4a81fe17da59265e))
