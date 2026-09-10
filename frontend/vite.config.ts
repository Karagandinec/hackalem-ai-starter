import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// .env лежит в корне монорепо — один файл на backend и frontend.
// Без envDir Vite искал бы его в frontend/ и тихо игнорировал VITE_API_URL.
const rootDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, rootDir, "VITE_"); // только VITE_*, ключи наружу не утекают

  return {
    plugins: [react()],
    envDir: rootDir,
    server: {
      port: 5173,
      // Фронт зовёт /api/..., Vite перекидывает на FastAPI: один и тот же путь
      // в деве и в проде, CORS не мешает.
      proxy: {
        "/api": {
          target: env.VITE_API_URL || "http://localhost:8000",
          changeOrigin: true,
        },
      },
    },
  };
});
