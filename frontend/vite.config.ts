import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Launching the frontend should land you on the page, not on a URL to
    // copy by hand.
    open: true,
    // The app talks to the API with RELATIVE paths, so the same code works
    // here (proxied to the backend) and in production (where FastAPI serves
    // the built files itself, from a single origin, with no CORS involved).
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
