import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Proxy /api calls to the FastAPI backend during local development.
    // In production (Fly.io), frontend and backend are served from the same
    // origin so no proxy is needed — /api resolves to the same host.
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
