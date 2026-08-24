import { describe, expect, it } from "vitest";
import { SUBSYSTEM_PALETTE, UNASSIGNED_COLOR, colorForSubsystem } from "./subsystemColors";

// The anti-drift test (Part G): every consumer of this module -- the
// subsystem graph, the treemap, and the 3D city -- must resolve the same
// subsystem key to the same colour. This test doesn't render any of the
// three; it asserts the one property that keeps them consistent through
// session 15's refit: colorForSubsystem itself is a pure, deterministic
// function of its input.
describe("colorForSubsystem", () => {
  it("is deterministic for the same label across repeated calls", () => {
    const label = "billing";
    const first = colorForSubsystem(label);
    for (let i = 0; i < 10; i++) {
      expect(colorForSubsystem(label)).toBe(first);
    }
  });

  it("resolves a numeric id and its string form to the same colour", () => {
    expect(colorForSubsystem(3)).toBe(colorForSubsystem("3"));
  });

  it("always returns a colour drawn from the published palette", () => {
    for (const label of ["billing", "auth", "graph engine", "Unclustered", "Other", ""]) {
      const color = label === "" ? UNASSIGNED_COLOR : colorForSubsystem(label);
      if (label === "") {
        expect(color).toBe(UNASSIGNED_COLOR);
      } else {
        expect(SUBSYSTEM_PALETTE).toContain(color);
      }
    }
  });

  it("null/undefined/empty all resolve to the dedicated unassigned colour, never a hashed slot", () => {
    expect(colorForSubsystem(null)).toBe(UNASSIGNED_COLOR);
    expect(colorForSubsystem(undefined)).toBe(UNASSIGNED_COLOR);
    expect(colorForSubsystem("")).toBe(UNASSIGNED_COLOR);
    expect(SUBSYSTEM_PALETTE).not.toContain(UNASSIGNED_COLOR);
  });

  it("simulates all three views resolving the same subsystem set consistently (the real anti-drift property)", () => {
    // Stand-ins for what MapPage (graph), the treemap, and CodeCity would
    // each independently compute a colour for -- all keyed by the one
    // identifier they all share, the subsystem label.
    const subsystems = ["billing", "auth", "core", "web"];
    const graphNodeColor = new Map(subsystems.map((s) => [s, colorForSubsystem(s)]));
    const treemapFillColor = new Map(subsystems.map((s) => [s, colorForSubsystem(s)]));
    const cityInstanceColor = new Map(subsystems.map((s) => [s, colorForSubsystem(s)]));

    for (const s of subsystems) {
      expect(graphNodeColor.get(s)).toBe(treemapFillColor.get(s));
      expect(treemapFillColor.get(s)).toBe(cityInstanceColor.get(s));
    }
  });

  it("has exactly 12 categorical colours, all distinct", () => {
    expect(SUBSYSTEM_PALETTE.length).toBe(12);
    expect(new Set(SUBSYSTEM_PALETTE).size).toBe(12);
  });
});
