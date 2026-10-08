import { defineConfig } from "vite";

export default defineConfig({
  build: {
    // Gameplay assets are backend-owned at /assets. Keep generated frontend
    // bundles in a separate namespace so production routing is unambiguous.
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
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
});
