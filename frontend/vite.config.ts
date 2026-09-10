import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Прокси: фронт зовёт /api/..., Vite перекидывает на FastAPI.
    // Благодаря этому в проде и в деве один и тот же путь, а CORS не мешает.
    proxy: {
      "/api": {
        target: process.env.VITE_API_URL || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
