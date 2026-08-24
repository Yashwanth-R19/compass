import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HeuristicNote } from "./HeuristicNote";

describe("HeuristicNote", () => {
  it("renders the default calibration message", () => {
    render(<HeuristicNote />);
    expect(screen.getByText(/not yet corpus-calibrated/i)).toBeTruthy();
  });

  it("renders a custom message when one is passed", () => {
    render(<HeuristicNote message="Custom heuristic note text." />);
    expect(screen.getByText("Custom heuristic note text.")).toBeTruthy();
    expect(screen.queryByText(/not yet corpus-calibrated/i)).toBeNull();
  });
});
