import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 本專案專屬固定埠;strictPort 確保埠被佔用時直接報錯,不會偷偷跳到別的埠/別的網站。
// 依專案調整 5180 / 8010,避免與其他專案的 5173 / 8000 衝突。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8010", changeOrigin: true },
      "/ws": { target: "ws://127.0.0.1:8010", ws: true },
    },
  },
});
