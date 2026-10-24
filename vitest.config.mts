import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

// Unit tests cover the logic that lives in lib/. React page components are exercised by the Playwright E2E stage.
export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } },
  test: {
    environment: "jsdom",
    include: ["unit/**/*.test.ts"],
    coverage: {
      provider: "v8",
      include: ["lib/**/*.ts"],
      reporter: ["text", "json-summary"],
      thresholds: { lines: 100, branches: 100, functions: 100, statements: 100 },
    },
  },
});
