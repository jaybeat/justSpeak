import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 前端开发服务器把 /ws、/healthz 反向代理到 Python 后端（uvicorn :8000），
// 这样前后端同源：浏览器只连页面所在 origin，免去跨域/混合内容问题，
// 之后手机走 https 时也能无缝用 wss。
export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // 监听 0.0.0.0，允许局域网内手机访问
    proxy: {
      '/ws': { target: 'ws://localhost:8000', ws: true },
      '/healthz': 'http://localhost:8000',
    },
  },
  // npm run preview（跑生产构建）也要能连后端，代理同 server
  preview: {
    host: true,
    proxy: {
      '/ws': { target: 'ws://localhost:8000', ws: true },
      '/healthz': 'http://localhost:8000',
    },
  },
})
