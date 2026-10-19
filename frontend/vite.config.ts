import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    // In Docker the backend is a sibling service, so localhost would resolve to
    // this container. Compose sets VITE_API_PROXY; bare `npm run dev` keeps localhost.
    host: true,
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY || 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
    },
  },
})
