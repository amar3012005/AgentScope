import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:6080",
      "/upload": "http://localhost:6080",
      "/agents": "http://localhost:6080",
      "/orchestrate": "http://localhost:6080",
    },
  },
  base: "/app/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
