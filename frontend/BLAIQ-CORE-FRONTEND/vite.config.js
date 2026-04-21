import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'path';

const proxyTarget = process.env.VITE_PROXY_TARGET || 'http://localhost:6080';
const devApiKey = process.env.API_KEY || 'your_secure_api_key_here';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 3001,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: proxyTarget,
        changeOrigin: true,
        headers: {
          'X-API-Key': devApiKey,
        },
      },
      '/agents': {
        target: proxyTarget,
        changeOrigin: true,
        headers: {
          'X-API-Key': devApiKey,
        },
      },
      '/upload': {
        target: proxyTarget,
        changeOrigin: true,
        headers: {
          'X-API-Key': devApiKey,
        },
      },
    },
  },
});
