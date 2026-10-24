import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev server on port 5173 (the backend allows this origin via CORS).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, host: true },
  build: { chunkSizeWarningLimit: 900 }, // one small dashboard bundle is fine
});
