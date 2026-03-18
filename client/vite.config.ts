import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";

const apiProxyTarget =
  process.env.VITE_DEV_API_PROXY_TARGET ?? "http://127.0.0.1:8000";

// https://vite.dev/config/
export default defineConfig({
  base: "/",
  root: path.resolve(__dirname),
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: apiProxyTarget,
        changeOrigin: true,
      },
    },
  },
  optimizeDeps: {
    noDiscovery: false,
    include: ["react/jsx-runtime", "react/jsx-dev-runtime"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
