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

  it("switches to the corpus message and tone when calibration is 'corpus'", () => {
    const { container } = render(<HeuristicNote calibration="corpus" />);
    expect(screen.getByText(/calibrated against a curated corpus/i)).toBeTruthy();
    expect(container.innerHTML).toContain("border-success");
    expect(container.innerHTML).not.toContain("border-warning");
  });
});
