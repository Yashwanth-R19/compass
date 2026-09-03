import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";
import { ScoreExplainer } from "./ScoreExplainer";
import { TooltipProvider } from "./ui/Tooltip";
import { FORMULA_COPY } from "../content/explainability";
import type { ScoreExplainerContribution } from "./ScoreExplainer";

const useFormulasMock = vi.fn();

vi.mock("../api/hooks", () => ({
  useFormulas: () => useFormulasMock(),
}));

const RISK_GROUP = {
  key: "risk",
  label: "Risk score",
  status: "locked" as const,
  formula:
    "risk_score = 0.60 x norm(churn_weighted x complexity) + 0.25 x norm(max coupling_degree) + 0.15 x norm(commit_count)",
  citation: null,
  constants: [
    { name: "churn_complexity_weight", value: 0.6, description: "" },
    { name: "coupling_weight", value: 0.25, description: "" },
    { name: "commit_count_weight", value: 0.15, description: "" },
  ],
};

const CONTRIBUTIONS: ScoreExplainerContribution[] = [
  {
    constantName: "churn_complexity_weight",
    label: "Churn x complexity",
    normalizedValue: 0.8,
    detail: "This file changed 900 lines across 40 commits, weighted for recency.",
  },
  {
    constantName: "coupling_weight",
    label: "Coupling",
    normalizedValue: 0.5,
    detail: null,
  },
  {
    constantName: "commit_count_weight",
    label: "Commit count",
    normalizedValue: 0.2,
    detail: "40 commits touched this file.",
  },
];

function renderExplainer(props: Partial<ComponentProps<typeof ScoreExplainer>> = {}) {
  return render(
    <TooltipProvider>
      <ScoreExplainer formulaKey="risk" contributions={CONTRIBUTIONS} {...props} />
    </TooltipProvider>,
  );
}

beforeEach(() => {
  useFormulasMock.mockReset();
});

describe("ScoreExplainer", () => {
  it("computes each term's arithmetic and marks the largest contribution", () => {
    useFormulasMock.mockReturnValue({ data: { groups: [RISK_GROUP] } });
    renderExplainer();

    // 0.60 x 0.800 = 0.480 (largest), 0.25 x 0.500 = 0.125, 0.15 x 0.200 = 0.030
    expect(screen.getByText("0.60 x 0.800 = 0.480")).toBeTruthy();
    expect(screen.getByText("0.25 x 0.500 = 0.125")).toBeTruthy();
    expect(screen.getByText("0.15 x 0.200 = 0.030")).toBeTruthy();

    const largest = screen.getByText("0.60 x 0.800 = 0.480");
    expect(largest.className).toContain("font-semibold");
    const other = screen.getByText("0.25 x 0.500 = 0.125");
    expect(other.className).not.toContain("font-semibold");
  });

  it("renders a detail line only for a term whose detail is provided", () => {
    useFormulasMock.mockReturnValue({ data: { groups: [RISK_GROUP] } });
    renderExplainer();

    expect(
      screen.getByText("This file changed 900 lines across 40 commits, weighted for recency."),
    ).toBeTruthy();
    expect(screen.getByText("40 commits touched this file.")).toBeTruthy();
    // The "Coupling" term's detail is null -- never "undefined", never a
    // placeholder, never a fabricated sentence.
    expect(screen.queryByText(/undefined/i)).toBeNull();
  });

  it("shows the capped-at note only when the raw sum genuinely exceeds the cap", () => {
    useFormulasMock.mockReturnValue({ data: { groups: [RISK_GROUP] } });

    const { rerender } = renderExplainer({ cap: { cappedAt: 100, rawSum: 112 } });
    expect(screen.getByText(/Capped at 100/)).toBeTruthy();
    expect(screen.getByText(/raw sum was 112/)).toBeTruthy();

    rerender(
      <TooltipProvider>
        <ScoreExplainer
          formulaKey="risk"
          contributions={CONTRIBUTIONS}
          cap={{ cappedAt: 100, rawSum: 100 }}
        />
      </TooltipProvider>,
    );
    expect(screen.queryByText(/Capped at/)).toBeNull();
  });

  it("never shows a capped-at note when no cap is supplied at all", () => {
    useFormulasMock.mockReturnValue({ data: { groups: [RISK_GROUP] } });
    renderExplainer();
    expect(screen.queryByText(/Capped at/)).toBeNull();
  });

  it("renders the qualitative summary and omits the numeric breakdown when /meta/formulas is unavailable", () => {
    useFormulasMock.mockReturnValue({ data: undefined, isPending: false, isError: true });
    renderExplainer();

    expect(screen.getByText(FORMULA_COPY.risk.summary)).toBeTruthy();
    // No weight was ever written in this file to fall back to -- the
    // numeric arithmetic (which would include "0.60") must not appear.
    expect(screen.queryByText(/0\.60/)).toBeNull();
    expect(screen.queryByText("0.60 x 0.800 = 0.480")).toBeNull();
  });

  it("renders the also-measured block with the caller-supplied values", () => {
    useFormulasMock.mockReturnValue({ data: { groups: [RISK_GROUP] } });
    renderExplainer({
      alsoMeasured: [{ label: "Total churn (unweighted)", value: "1,204", tooltip: "churnTotal" }],
    });

    expect(screen.getByText("Also measured (not scored)")).toBeTruthy();
    expect(screen.getByText("Total churn (unweighted)")).toBeTruthy();
    expect(screen.getByText("1,204")).toBeTruthy();
  });
});
