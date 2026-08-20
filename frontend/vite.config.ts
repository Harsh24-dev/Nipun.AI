import path from 'node:path'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  resolve: {
    // The `@/` → `src/` alias used throughout the app. (Previously provided by the
    // now-removed @base44/vite-plugin; kept here so imports keep resolving.)
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    proxy: {
      '/api-backend': {
        target: process.env.VITE_API_BASE_URL || 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api-backend/, ''),
        ws: true,
      },
    },
  },
  plugins: [
    react(),
  ],
});
