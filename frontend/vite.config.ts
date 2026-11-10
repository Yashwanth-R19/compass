/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Session 08: Vitest lives inside this same config (the `test` block below)
// rather than a separate vitest.config.ts -- one build tool, per CLAUDE.md's
// frontend conventions. Playwright is configured separately in
// playwright.config.ts since it drives a real browser against a running
// dev server, not the Vite/Vitest pipeline.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Mirrors frontend/vercel.json's production rewrite (/api/* -> the API),
  // so running the dev server with VITE_API_URL=/api exercises the exact
  // same-origin path production uses. The default dev setup (no
  // VITE_API_URL) still talks to http://localhost:8000 directly.
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    exclude: ['**/node_modules/**', '**/dist/**', 'e2e/**'],
  },
})
