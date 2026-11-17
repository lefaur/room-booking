import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

// npm run dev: фронт на :5173, API проксируется на поднятый docker compose (gateway :8080)
export default defineConfig({
  plugins: [vue()],
  server: { proxy: { "/api": "http://localhost:8080" } },
});
