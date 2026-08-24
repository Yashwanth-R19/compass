import { describe, expect, it } from "vitest";
import { average, lerpColor, majority, ownerColor, recencyColor, riskColor } from "./metricColor";
import { SUBSYSTEM_PALETTE, UNASSIGNED_COLOR } from "./subsystemColors";

describe("metricColor", () => {
  it("lerpColor is deterministic and hits the endpoints exactly", () => {
    expect(lerpColor("#000000", "#ffffff", 0)).toBe("#000000");
    expect(lerpColor("#000000", "#ffffff", 1)).toBe("#ffffff");
    expect(lerpColor("#000000", "#ffffff", 0.5)).toBe(lerpColor("#000000", "#ffffff", 0.5));
  });

  it("average handles the empty list without dividing by zero", () => {
    expect(average([])).toBeNull();
    expect(average([2, 4, 6])).toBe(4);
  });

  it("majority picks the most frequent value, ignoring null/undefined", () => {
    expect(majority([1, 1, 2, null, undefined, 1])).toBe(1);
    expect(majority([null, undefined])).toBeNull();
  });

  it("riskColor and recencyColor fall back to the unassigned colour for missing data", () => {
    expect(riskColor(null)).toBe(UNASSIGNED_COLOR);
    expect(recencyColor(null, 0, 100)).toBe(UNASSIGNED_COLOR);
    expect(recencyColor(50, 100, 100)).toBe(UNASSIGNED_COLOR); // zero-width bounds
  });

  it("ownerColor is deterministic and drawn from the shared palette", () => {
    const a = ownerColor(7);
    expect(ownerColor(7)).toBe(a);
    expect(SUBSYSTEM_PALETTE).toContain(a);
    expect(ownerColor(null)).toBe(UNASSIGNED_COLOR);
  });
});
