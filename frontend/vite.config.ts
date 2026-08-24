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
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    exclude: ['**/node_modules/**', '**/dist/**', 'e2e/**'],
  },
})
