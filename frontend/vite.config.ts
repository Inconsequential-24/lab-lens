import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built files go to frontend/dist; FastAPI serves them. In dev, /v1 is proxied to the API.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true },
  server: { proxy: { "/v1": "http://localhost:8000", "/healthz": "http://localhost:8000" } },
});
