import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Приложение живёт под /karta/ (noindex); корень сайта — статический слой фактов (T2.5).
// Локально: RF_API=http://localhost:8000 npm run dev (uvicorn --factory rf_api.app:create_app).
export default defineConfig({
  base: "/karta/",
  plugins: [react()],
  server: {
    fs: { allow: [".."] }, // config/ecosystem.json лежит вне web/
    proxy: { "/api": process.env.RF_API ?? "http://localhost:8000" },
  },
  build: {
    chunkSizeWarningLimit: 1100,
    rollupOptions: {
      // Библиотеки карты меняются редко — отдельные чанки живут в кеше браузера между выкладками.
      output: { manualChunks: { maplibre: ["maplibre-gl"], deck: ["@deck.gl/core", "@deck.gl/layers", "@deck.gl/mapbox"] } },
    },
  },
});
