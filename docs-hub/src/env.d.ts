/// <reference types="astro/client" />

declare const __DOCS_ASSET_ORIGIN__: string;

declare module "*?url" {
  const value: string;
  export default value;
}
