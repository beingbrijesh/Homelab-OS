import { defineConfig } from 'vite';
import preact from '@preact/preset-vite';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [preact(), tailwindcss()],
  base: '/',
  build: {
    outDir: '../static/dist',
    emptyOutDir: true,
    target: 'es2020',
    minify: 'esbuild',
    cssMinify: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: undefined,
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:5001',
      '/static/manifest.json': 'http://127.0.0.1:5001',
      '/static/sw.js': 'http://127.0.0.1:5001',
    },
  },
});
