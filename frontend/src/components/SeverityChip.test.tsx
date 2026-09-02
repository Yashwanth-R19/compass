import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SeverityChip } from "./SeverityChip";
import { SEVERITY_LABEL } from "../lib/format";
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
});
