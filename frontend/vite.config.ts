import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: "0.0.0.0",
    proxy: {
      "/missions": "http://backend:8000",
      "/algorithms": "http://backend:8000",
      "/benchmark": "http://backend:8000",
      "/health": "http://backend:8000",
      "/ws": {
        target: "ws://backend:8000",
        ws: true
      }
    }
  }
});
