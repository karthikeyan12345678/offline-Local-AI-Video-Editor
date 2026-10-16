import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend serves the built UI itself, so asset paths must be relative.
export default defineConfig({
  base: "./",
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
  build: { outDir: "dist", sourcemap: false },
});
