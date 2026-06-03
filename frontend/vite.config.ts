import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const allowedHosts = process.env.VITE_ALLOWED_HOSTS
  ?.split(",")
  .map((host) => host.trim())
  .filter(Boolean);

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: "0.0.0.0",
    ...(allowedHosts?.length ? { allowedHosts } : {}),
    proxy: {
      "/missions": "http://backend:8000",
      "/algorithms": "http://backend:8000",
      "/benchmark": "http://backend:8000",
      "/health": "http://backend:8000",
      "/sitl": "http://backend:8000",
      "/ws": {
        target: "ws://backend:8000",
        ws: true
      }
    }
  }
});
