import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { DICTS } from "./src/lib/i18n.js";

// The macOS menu-bar titles (menu.* keys) for core/hotkeys.py, which can't read i18n.js: static/app/menu.json.
const menuStrings = {
  name: "dictum-menu-json",
  generateBundle() {
    const pick = d => Object.fromEntries(Object.entries(d).filter(([k]) => k.startsWith("menu.")));
    const data = Object.fromEntries(Object.entries(DICTS).map(([lang, d]) => [lang, pick(d)]));
    this.emitFile({ type: "asset", fileName: "menu.json", source: JSON.stringify(data, null, 1) + "\n" });
  },
};

// Built into static/app and served by Flask at "/". The build output is committed,
// so running the app from source or packaging it doesn't need Node.
export default defineConfig({
  plugins: [svelte(), menuStrings],
  base: "/static/app/",
  build: { outDir: "../static/app", emptyOutDir: true, assetsDir: "assets", sourcemap: false },
  server: {
    // `npm run dev` proxies API calls to a running app (WORKBENCH_PORT, default 47823).
    proxy: Object.fromEntries(["/api", "/transcribe", "/job", "/summarize", "/settings", "/health",
      "/models", "/device-info", "/audio-devices", "/desktop-record", "/ollama", "/__workbench"]
      .map(p => [p, `http://127.0.0.1:${process.env.WORKBENCH_PORT || 47823}`])),
  },
});
