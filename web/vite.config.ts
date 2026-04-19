import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backendPort = Number(process.env.BACKEND_PORT || 18000);

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: true,
      },
    },
  },
});
