import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";

// https://vite.dev/config/
export default defineConfig({
  base: "/",
  root: path.resolve(__dirname),
  plugins: [react()],
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
