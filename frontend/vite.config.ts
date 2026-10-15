import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  return {
    plugins: [react(), tailwindcss()],
    optimizeDeps: {
      exclude: ['@arcgis/core', '@esri/calcite-components'],
    },
    server: {
      host: true,
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': {
          target: env.VITE_API_PROXY_TARGET || 'https://osea-data-pipeline.onrender.com',
          changeOrigin: true,
          secure: true,
        },
      },
    },
  };
});
