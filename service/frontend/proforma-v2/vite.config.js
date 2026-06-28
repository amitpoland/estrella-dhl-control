import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/v2/proforma-react/',
  build: {
    outDir: '../../app/static/v2/proforma-react',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/auth': 'http://localhost:8000',
      '/login': 'http://localhost:8000',
    },
  },
})
