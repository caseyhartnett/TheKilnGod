import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/picoreflow/v2/',
  build: {
    outDir: '../public/v2',
    emptyOutDir: true
  }
})
