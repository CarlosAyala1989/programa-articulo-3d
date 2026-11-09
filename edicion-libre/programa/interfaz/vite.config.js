import { defineConfig } from 'vite';

export default defineConfig({
  // Evita el consumo excesivo de memoria de Rollup al analizar Three.js.
  build: { outDir: 'dist', rollupOptions: { treeshake: false } },
});
