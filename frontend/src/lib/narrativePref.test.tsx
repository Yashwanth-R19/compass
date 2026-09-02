import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Every test dynamically re-imports the module after `vi.resetModules()` --
// narrativePref.ts caches its value in a module-level variable read once at
// import time (so `useNarrativeEnabled` can be a plain useSyncExternalStore
// snapshot), so exercising "what happens on a fresh page load with
// localStorage blocked" genuinely needs a fresh module instance, not just a
// fresh localStorage.
describe("narrativePref", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
    vi.resetModules();
  });

  it("defaults to disabled (Known Hazard #5)", async () => {
    const mod = await import("./narrativePref");
    expect(mod.isNarrativeEnabled()).toBe(false);
  });

  it("round-trips through real localStorage", async () => {
    const mod = await import("./narrativePref");
    mod.setNarrativeEnabled(true);
    expect(mod.isNarrativeEnabled()).toBe(true);
    mod.setNarrativeEnabled(false);
    expect(mod.isNarrativeEnabled()).toBe(false);
  });

  it("setNarrativeEnabled never throws when localStorage.setItem throws, and still toggles in memory", async () => {
    const mod = await import("./narrativePref");
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    expect(() => mod.setNarrativeEnabled(true)).not.toThrow();
    expect(mod.isNarrativeEnabled()).toBe(true);
  });

  it("defaults to disabled, never throws, when localStorage.getItem throws at load time (a private window)", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    const mod = await import("./narrativePref");
    expect(mod.isNarrativeEnabled()).toBe(false);
  });

  it("useNarrativeEnabled reacts live to setNarrativeEnabled -- the header toggle updates every mounted NarrativeBlock", async () => {
    const mod = await import("./narrativePref");

    function Toggle() {
      const enabled = mod.useNarrativeEnabled();
      return (
        <button onClick={() => mod.setNarrativeEnabled(!enabled)}>{enabled ? "on" : "off"}</button>
      );
    }

    render(<Toggle />);
    const button = screen.getByRole("button");
    expect(button.textContent).toBe("off");

    fireEvent.click(button);
    expect(button.textContent).toBe("on");

    fireEvent.click(button);
    expect(button.textContent).toBe("off");
  });
});
