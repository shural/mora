import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies /api (including Range requests for audio) to the
// FastAPI backend. In mock mode no request ever leaves the browser.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8787",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    target: "es2020",
  },
});
