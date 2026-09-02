import { describe, expect, it } from "vitest";
import type { HeadlineDeltaOut } from "../api/types";
import { formatSignedDelta, headlineDirection } from "./compare";

function delta(overrides: Partial<HeadlineDeltaOut>): HeadlineDeltaOut {
  return {
    metric: "health_score",
    label: "Health score",
    before: 50,
    after: 40,
    delta: -10,
    higher_is_better: true,
    ...overrides,
  };
}

describe("headlineDirection", () => {
  it("a negative delta on a higher-is-better metric (health) is worsened", () => {
    expect(headlineDirection(delta({ delta: -12, higher_is_better: true }))).toBe("worsened");
  });

  it("a negative delta on a lower-is-better metric (onboarding difficulty) is improved", () => {
    expect(headlineDirection(delta({ delta: -12, higher_is_better: false }))).toBe("improved");
  });

  it("a positive delta on a higher-is-better metric (truck factor) is improved", () => {
    expect(headlineDirection(delta({ delta: 1, higher_is_better: true }))).toBe("improved");
  });

  it("a metric with no inherent direction is always neutral", () => {
    expect(headlineDirection(delta({ delta: 3, higher_is_better: null }))).toBe("neutral");
    expect(headlineDirection(delta({ delta: -3, higher_is_better: null }))).toBe("neutral");
  });

  it("a zero or null delta is neutral regardless of direction", () => {
    expect(headlineDirection(delta({ delta: 0, higher_is_better: true }))).toBe("neutral");
    expect(headlineDirection(delta({ delta: null, higher_is_better: true }))).toBe("neutral");
  });
});

describe("formatSignedDelta", () => {
  it("prefixes a plus sign on positive values only", () => {
    expect(formatSignedDelta(12)).toBe("+12");
    expect(formatSignedDelta(-12)).toBe("-12");
    expect(formatSignedDelta(0)).toBe("0");
  });

  it("never renders a bare negative zero for a tiny negative delta (found via manual QA)", () => {
    // Rounds to -0.00 internally; must display as "0", never the literal "-0".
    expect(formatSignedDelta(-0.002)).toBe("0");
  });
});
