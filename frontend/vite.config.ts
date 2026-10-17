import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base "./" keeps every path relative, so the same build works at the root of a host (Netlify)
// and in a sub-folder (GitHub Pages: https://name.github.io/repo/), and inside the desktop app.
export default defineConfig(({ mode }) => ({
  base: "./",
  plugins: [react()],
  // the browser build ("vite build --mode web") switches the website mode on; a .env file is not used because .env.* is git-ignored
  define: mode === "web" ? { "import.meta.env.VITE_WEB": JSON.stringify("1") } : {},
  server: { proxy: mode === "web" ? {} : { "/api": "http://127.0.0.1:8765" } },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 1200 },
}));
