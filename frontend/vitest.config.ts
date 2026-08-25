import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  test: { environment: "jsdom", setupFiles: ["./vitest.setup.ts"], globals: true, exclude: ["tests/e2e/**", "node_modules/**"] },
  resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } },
});
