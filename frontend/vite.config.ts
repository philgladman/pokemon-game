import { defineConfig } from "vite";

export default defineConfig({
  build: {
    // Keep generated bundles separate from backend-owned source assets.
    assetsDir: "frontend",
    rollupOptions: {
      output: {
        manualChunks: {
          three: ["three"],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/assets": "http://localhost:8000",
      "/source-assets": "http://localhost:8000",
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
});
