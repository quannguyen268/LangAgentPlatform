import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  server: {
    port: 5173,
    proxy: {
      "/v1": "http://localhost:8900",
      "/ws": { target: "ws://localhost:8900", ws: true },
    },
  },
  build: {
    outDir: path.resolve(__dirname, "../src/api/static"),
    emptyOutDir: true,
    assetsDir: "assets",
  },
  base: "/web/",
});
