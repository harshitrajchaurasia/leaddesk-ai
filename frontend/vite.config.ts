import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Build output goes to ../web, which FastAPI serves. `npm run dev` proxies the API to uvicorn on :8000.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "../web", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
