import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConfidenceMeter } from "./ConfidenceMeter";

// Spans confidenceLabel's three bands (lib/format.ts: <0.4 low, <0.75
// medium, else high), so every possible rendered state (Part H) is
// exercised, not just one representative value per tier. Values are chosen
// to multiply out to whole percentages, avoiding floating-point rounding
// ambiguity between the test's own expectation and formatPercent's
// `.toFixed(0)`.
const VALUES = [0, 0.1, 0.25, 0.4, 0.5, 0.75, 0.9, 1];

describe("ConfidenceMeter", () => {
  it("renders a percentage for every possible confidence value", () => {
    for (const value of VALUES) {
      const { unmount } = render(<ConfidenceMeter confidence={value} />);
      expect(screen.getByText(new RegExp(`${Math.round(value * 100)}%`))).toBeTruthy();
      unmount();
    }
  });

  it("labels low confidence explicitly, and never labels medium/high as low", () => {
    const low = render(<ConfidenceMeter confidence={0.1} />);
    expect(low.getByText(/\(low\)/)).toBeTruthy();
    low.unmount();

    const high = render(<ConfidenceMeter confidence={0.9} />);
    expect(high.queryByText(/\(low\)/)).toBeNull();
    high.unmount();
  });

  it("never folds the score's own color into confidence -- this is a separate, non-opacity dimension", () => {
    // Regression guard for Known Hazard #3: the meter must never render
    // via an `opacity` style, which is the "fading = less risky" mistake
    // the hazard warns about.
    const { container } = render(<ConfidenceMeter confidence={0.3} />);
    expect(container.innerHTML).not.toContain("opacity");
  });
});
