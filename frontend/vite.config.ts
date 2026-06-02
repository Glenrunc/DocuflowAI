import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

const sharedDir = fileURLToPath(new URL("../shared", import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@shared": sharedDir,
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    fs: { allow: [".", sharedDir] },
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
