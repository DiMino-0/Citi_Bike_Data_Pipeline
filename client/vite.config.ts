import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";

// https://vite.dev/config/
export default defineConfig({
  base: "/",
  root: path.resolve(__dirname),
  plugins: [react()],
  // Workaround: disable dependency optimization to avoid the Vite optimizer crash
  // (caused by path/metadata handling) — this will disable pre-bundling but allow
  // the dev server to run. Remove once the underlying issue is resolved.
  optimizeDeps: {
    disabled: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
