/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Base URL of the agent backend, e.g. `http://localhost:8000`.
   * When unset the app defaults to a local dev server at that address.
   */
  readonly VITE_GEO_API_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
