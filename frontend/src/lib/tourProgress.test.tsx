import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { isTourStopDone, setTourStopDone } from "./tourProgress";

const REPO_ID = "repo-1";
const RUN_ID = "run-1";
const PATH = "src/app.py";

/** Mirrors exactly how TourStopItem (pages/onboard/TourPage.tsx) uses the
 * two helpers -- reads the stored flag once for its initial checkbox state,
 * writes it back on toggle. Kept minimal and local to this test file rather
 * than importing the full TourStopItem, which drags in the tour API/copy
 * dependencies this test isn't about. */
function TourStopCheckbox() {
  const [done, setDone] = useState(() => isTourStopDone(REPO_ID, RUN_ID, PATH));
  return (
    <label>
      progress
      <input
        type="checkbox"
        checked={done}
        onChange={(e) => {
          const next = e.target.checked;
          setDone(next);
          setTourStopDone(REPO_ID, RUN_ID, PATH, next);
        }}
      />
    </label>
  );
}

describe("tourProgress", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("round-trips through real localStorage", () => {
    expect(isTourStopDone(REPO_ID, RUN_ID, PATH)).toBe(false);
    setTourStopDone(REPO_ID, RUN_ID, PATH, true);
    expect(isTourStopDone(REPO_ID, RUN_ID, PATH)).toBe(true);
    setTourStopDone(REPO_ID, RUN_ID, PATH, false);
    expect(isTourStopDone(REPO_ID, RUN_ID, PATH)).toBe(false);
  });

  it("isTourStopDone returns false (never throws) when localStorage.getItem throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    expect(() => isTourStopDone(REPO_ID, RUN_ID, PATH)).not.toThrow();
    expect(isTourStopDone(REPO_ID, RUN_ID, PATH)).toBe(false);
  });

  it("setTourStopDone never throws when localStorage.setItem throws", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    expect(() => setTourStopDone(REPO_ID, RUN_ID, PATH, true)).not.toThrow();
  });

  it("a component using these helpers still renders and stays interactive when localStorage throws on every call", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });

    render(<TourStopCheckbox />);
    const checkbox = screen.getByRole("checkbox") as HTMLInputElement;
    expect(checkbox.checked).toBe(false);

    // The checkbox still toggles in memory even though persistence silently
    // fails -- the page must render correctly with no stored value (Known
    // Hazard #3), not crash or freeze.
    fireEvent.click(checkbox);
    expect(checkbox.checked).toBe(true);
  });
});
