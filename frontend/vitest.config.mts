import { configDefaults, defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Honor the tsconfig "@/*" path alias natively (Vite 8+).
    tsconfigPaths: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    // e2e/ belongs to Playwright — vitest must not try to run those specs.
    exclude: [...configDefaults.exclude, "e2e/**"],
  },
});
