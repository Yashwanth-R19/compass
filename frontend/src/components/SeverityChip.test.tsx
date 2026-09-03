import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SeverityChip } from "./SeverityChip";
import { SEVERITY_CLASSES, SEVERITY_LABEL } from "../lib/format";
import type { Severity } from "../api/types";

const SEVERITIES: Severity[] = ["low", "med", "high"];

describe("SeverityChip", () => {
  it("renders the correct label for every severity value", () => {
    for (const severity of SEVERITIES) {
      const { unmount } = render(<SeverityChip severity={severity} />);
      expect(screen.getByText(SEVERITY_LABEL[severity])).toBeTruthy();
      unmount();
    }
  });

  it("reads its colour only from the heat ramp (scale-*), never a separate hue", () => {
    // Design tokens section 3.1: "severity maps onto that ramp and nowhere
    // else" -- a regression here (e.g. reintroducing a dedicated
    // sev-high/med/low hue) would silently violate that rule.
    for (const severity of SEVERITIES) {
      expect(SEVERITY_CLASSES[severity]).toMatch(/scale-[135]/);
    }
  });
});
