import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev server proxies API + media file serving to the FastAPI backend on 8100,
// so the frontend uses relative URLs (no CORS in dev).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5200,
    proxy: {
      '/api': 'http://localhost:8100',
      '/files': 'http://localhost:8100',
    },
  },
});
