import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    host: true,
  },
  build: {
    // Leaflet is the only large third-party dependency; splitting it out keeps
    // the application chunk small enough to re-download cheaply on each deploy.
    // The county dataset is NOT in the bundle — it is fetched at runtime from
    // `public/data/`, so it caches separately from the code.
    rollupOptions: {
      output: {
        manualChunks: {
          leaflet: ['leaflet'],
        },
      },
    },
    chunkSizeWarningLimit: 2500,
  },
})
