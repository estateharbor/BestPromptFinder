import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // Front end calls /api/*; Vite forwards to the FastAPI backend.
      "/api": "http://localhost:8000",
    },
  },
});
