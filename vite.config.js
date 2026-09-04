import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    watch: {
      // .venv (Python backend deps, thousands of files) and the RAG
      // vectorstore have no reason to be watched by the frontend dev
      // server — without this, Vite's watcher blows past the OS inotify
      // limit (ENOSPC: System limit for number of file watchers reached).
      ignored: ['**/.venv/**', '**/backend/athena/rag/vectorstore/**', '**/__pycache__/**'],
    },
  },
})