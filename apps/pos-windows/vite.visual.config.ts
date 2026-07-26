import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

/**
 * Build config for the visual-regression harness only.
 *
 * Kept separate from vite.config.ts so the harness and its fixture data can
 * never be bundled into the shipped renderer. The scenarios contain fabricated
 * patient records; they must not reach a production build.
 */
export default defineConfig({
  root: 'visual',
  plugins: [react()],
  build: {
    outDir: '../dist/visual',
    emptyOutDir: true,
    // Screenshots should reflect source layout, not minifier output.
    minify: false,
  },
  preview: {
    port: 4173,
    host: '127.0.0.1',
    strictPort: true,
  },
  server: {
    port: 4173,
    host: '127.0.0.1',
    strictPort: true,
  },
});
