import { describe, expect, it } from "vitest";
import { resolveNodeColor } from "./ArchitecturePage";
import { colorForSubsystem } from "../../lib/subsystemColors";

// Session 09's subsystemColors.test.ts covers colorForSubsystem's own
// determinism; this is the "extend it to cover this view" anti-drift test
// Known Hazard #4 calls for -- it asserts the Architecture graph's node
// coloring resolves to the EXACT SAME color colorForSubsystem would give
// the Onboard map / 3D city for the same subsystem label, and that
// selection/cycle highlighting takes priority over it without silently
// replacing it with a locally-invented palette.
describe("ArchitecturePage.resolveNodeColor", () => {
  it("colors an unselected, non-cycle node the same as colorForSubsystem for its label", () => {
    for (const label of ["billing", "auth", "search", null, undefined]) {
      const color = resolveNodeColor("src/a.py", {
        selectedNode: null,
        inCycle: false,
        subsystemLabel: label,
      });
      expect(color).toBe(colorForSubsystem(label));
    }
  });

  it("gives the same label the same color at two different call sites (map vs architecture)", () => {
    const archColor = resolveNodeColor("src/billing/invoice.py", {
      selectedNode: null,
      inCycle: false,
      subsystemLabel: "billing",
    });
    // The map/city resolve a subsystem's color by calling colorForSubsystem
    // directly with the label -- simulated here rather than importing
    // MapPage (which needs a live network graph to render at all).
    const mapColor = colorForSubsystem("billing");
    expect(archColor).toBe(mapColor);
  });

  it("selection overrides both cycle and subsystem coloring", () => {
    const color = resolveNodeColor("src/a.py", {
      selectedNode: "src/a.py",
      inCycle: true,
      subsystemLabel: "billing",
    });
    expect(color).not.toBe(colorForSubsystem("billing"));
  });

  it("cycle membership overrides subsystem coloring when nothing is selected", () => {
    const color = resolveNodeColor("src/a.py", {
      selectedNode: null,
      inCycle: true,
      subsystemLabel: "billing",
    });
    expect(color).not.toBe(colorForSubsystem("billing"));
  });
});
