import { defineConfig } from "astro/config";
import react from "@astrojs/react";
import starlight from "@astrojs/starlight";

const contentRoot = process.env.DOCS_HUB_CONTENT_ROOT ?? "./fixtures/content";
const publicRoot = process.env.DOCS_HUB_PUBLIC_ROOT ?? "./fixtures/public";
const siteUrl = process.env.DOCS_HUB_SITE_URL ?? "http://localhost:8080";
const assetOrigin = process.env.DOCS_HUB_ASSET_ORIGIN ?? "http://localhost:8081";
const title = process.env.DOCS_HUB_TITLE ?? "Docs Hub";
const description =
  process.env.DOCS_HUB_DESCRIPTION ?? "Source-provenanced documentation for humans and read-only clients.";

export default defineConfig({
  site: siteUrl,
  output: "static",
  publicDir: publicRoot,
  integrations: [
    react(),
    starlight({
      title,
      description,
      favicon: "/favicon.svg",
      lastUpdated: true,
      customCss: ["./src/styles/docs-hub.css"],
      components: {
        Head: "./src/components/Head.astro"
      },
      sidebar: [
        {
          label: "Repositories",
          items: [{ autogenerate: { directory: "repos" } }]
        },
        {
          label: "Visual acceptance",
          items: [{ autogenerate: { directory: "visual-acceptance" } }]
        }
      ]
    })
  ],
  vite: {
    cacheDir: "/tmp/docs-hub-vite-cache",
    define: {
      __DOCS_ASSET_ORIGIN__: JSON.stringify(assetOrigin)
    }
  },
  experimental: {
    contentIntellisense: true
  }
});

process.env.DOCS_HUB_CONTENT_ROOT = contentRoot;
