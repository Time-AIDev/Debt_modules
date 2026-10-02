import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The prototype backend runs on 8000. The browser only ever talks to /api; the API itself serves /v1/... with no
    // prefix, so the prefix is stripped here. Without the rewrite every screen in
    // dev gets a 404 and renders its empty state — which the unit tests cannot
    // catch, because they stub fetch.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.js'],
    globals: true,
  },
})
