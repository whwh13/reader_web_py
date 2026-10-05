import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// 后端地址：READER_BACKEND_URL 可覆盖，默认本机 reader-py (8081)
const backend = process.env.READER_BACKEND_URL || "http://127.0.0.1:8081";

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      "/reader3": { target: backend, changeOrigin: true },
      "/book-assets": { target: backend, changeOrigin: true },
    },
  },
  preview: {
    port: 4173,
    proxy: {
      "/reader3": { target: backend, changeOrigin: true },
      "/book-assets": { target: backend, changeOrigin: true },
    },
  },
});
