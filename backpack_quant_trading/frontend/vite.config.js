import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  optimizeDeps: {
    include: ['element-plus', 'element-plus/dist/locale/zh-cn.js', 'vue', 'vue-router', 'pinia', 'axios', 'echarts'],
    force: false,
  },
  build: {
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        manualChunks: {
          'element-plus': ['element-plus'],
          'echarts': ['echarts'],
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