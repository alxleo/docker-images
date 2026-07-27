import { defineCollection } from "astro:content";
import { glob } from "astro/loaders";
import { docsSchema } from "@astrojs/starlight/schema";

const base = process.env.DOCS_HUB_CONTENT_ROOT ?? "./fixtures/content";

export const collections = {
  docs: defineCollection({
    loader: glob({
      base,
      pattern: "**/[^_]*.{md,mdx}"
    }),
    schema: docsSchema()
  })
};
