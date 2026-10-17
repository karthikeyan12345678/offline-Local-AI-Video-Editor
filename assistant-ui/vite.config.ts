import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The desktop app serves the built UI itself, so asset paths must be relative.
// "vite build --mode web" makes the website copy: it runs in the browser with no server (see src/web).
export default defineConfig(({ mode }) => ({
  base: "./",
  plugins: [react()],
  define: mode === "web" ? { "import.meta.env.VITE_WEB": JSON.stringify("1") } : {},
  server: { proxy: mode === "web" ? {} : { "/api": "http://127.0.0.1:8766" } },
  build: { outDir: "dist", sourcemap: false, emptyOutDir: mode !== "web", chunkSizeWarningLimit: 1200 },
}));
