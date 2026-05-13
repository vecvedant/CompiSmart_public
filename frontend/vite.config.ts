import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Build output goes straight into the FastAPI static dir so the same Python
// server can serve the SPA at /. In dev, run `npm run build -- --watch` in
// one terminal and `uvicorn app.main:app --reload` in another -- both write
// to / read from this directory. Browser hits http://localhost:8000.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: path.resolve(__dirname, "../backend/static"),
    emptyOutDir: true,
    sourcemap: false,
    target: "es2020",
  },
  server: {
    port: 5173,
    // Vite dev server proxies API calls to FastAPI -- only used if you choose
    // to run `npm run dev` instead of build-watch. The "one port" workflow
    // (build-watch + uvicorn) doesn't need this.
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
