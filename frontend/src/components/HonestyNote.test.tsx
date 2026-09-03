import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HonestyNote } from "./HonestyNote";

describe("HonestyNote", () => {
  it("renders the exact text passed, verbatim", () => {
    render(
      <HonestyNote variant="scope-limitation" text="This is churn-ranked, not risk over time." />,
    );
    expect(screen.getByText("This is churn-ranked, not risk over time.")).toBeTruthy();
  });

  it.each(["scope-limitation", "confidence-caveat", "calibration"] as const)(
    "renders the %s variant without crashing",
    (variant) => {
      render(<HonestyNote variant={variant} text="A note." />);
      expect(screen.getByText("A note.")).toBeTruthy();
    },
  );
});
