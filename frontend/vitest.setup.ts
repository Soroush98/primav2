import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// RTL's automatic cleanup needs global test hooks; vitest globals are off, so
// unmount rendered trees explicitly to keep tests isolated.
afterEach(() => {
  cleanup();
});
