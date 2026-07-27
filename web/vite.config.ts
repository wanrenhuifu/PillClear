/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    environmentOptions: { jsdom: { pretendToBeVisual: true } }, // 提供 requestAnimationFrame(DoseMeter 动画依赖)
    globals: true,
    setupFiles: ["./src/setupTests.ts"],
  },
});
