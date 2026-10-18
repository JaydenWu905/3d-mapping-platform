import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Vite dev server proxies /api → backend FastAPI (single origin, no CORS pain).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // Vite's default proxy error handler leaves an SSE response open when
        // the upstream socket dies after headers were sent. Closing it lets
        // EventSource fire onerror so the UI can show "连接中断，正在重连".
        configure: (proxy) => {
          proxy.on('error', (_err, _req, res) => {
            if (res && typeof res.end === 'function' && !res.writableEnded) {
              res.end();
            }
          });
        },
      },
    },
  },
});