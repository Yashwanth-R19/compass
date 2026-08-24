import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Unmounts every rendered component between tests -- without this, a
// component left mounted by one test (e.g. one that never unmounts on
// purpose, like the throwing-localStorage case) leaks into the next test's
// DOM and produces confusing duplicate-element failures.
afterEach(() => {
  cleanup();
});
