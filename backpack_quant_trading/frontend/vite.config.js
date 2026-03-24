import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    include: ['axios', 'echarts'],
    force: false,
  },
  build: {
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        manualChunks: {
          echarts: ['echarts'],
        },
      },
    },
  },
  server: {
    port: 8050,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8100',  // 与 run_api 端口一致
        changeOrigin: true,
      },
    },
  },
})