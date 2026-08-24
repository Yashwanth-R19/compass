import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { LegacyRedirect, RepoIndexRedirect } from "./RepoLayout";

// Mirrors RepoLayout.tsx's own MODE_STORAGE_KEY constant (not exported --
// duplicated here deliberately, same as every other hardcoded-literal test
// in this suite that pins a string the implementation must keep using).
const MODE_STORAGE_KEY = "compass:mode";

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

/** The slice of App.tsx's real route tree relevant to redirects -- every
 * legacy path plus every one of its real targets, so a redirect that lands
 * somewhere with no matching route (a silent 404) fails the assertion
 * instead of rendering nothing. */
function renderAt(initialPath: string) {
  render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="repos/:repoId">
          <Route index element={<RepoIndexRedirect />} />
          <Route path="onboard/passport" element={<LocationProbe />} />
          <Route path="audit/findings" element={<LocationProbe />} />
          <Route path="audit/coupling" element={<LocationProbe />} />
          <Route path="audit/architecture" element={<LocationProbe />} />
          <Route path="audit/risk" element={<LocationProbe />} />
          <Route path="overview" element={<LegacyRedirect to="onboard/passport" />} />
          <Route path="coupling" element={<LegacyRedirect to="audit/coupling" />} />
          <Route path="architecture" element={<LegacyRedirect to="audit/architecture" />} />
          <Route path="risk" element={<LegacyRedirect to="audit/risk" />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("session 02 legacy path redirects (Known Hazard #1)", () => {
  it("redirects /overview to /onboard/passport, preserving ?share=", () => {
    renderAt("/repos/abc-123/overview?share=xyz");
    expect(screen.getByTestId("location").textContent).toBe(
      "/repos/abc-123/onboard/passport?share=xyz",
    );
  });

  it("redirects /coupling to /audit/coupling", () => {
    renderAt("/repos/abc-123/coupling");
    expect(screen.getByTestId("location").textContent).toBe("/repos/abc-123/audit/coupling");
  });

  it("redirects /architecture to /audit/architecture", () => {
    renderAt("/repos/abc-123/architecture");
    expect(screen.getByTestId("location").textContent).toBe("/repos/abc-123/audit/architecture");
  });

  it("redirects /risk to /audit/risk, preserving ?share=", () => {
    renderAt("/repos/abc-123/risk?share=xyz");
    expect(screen.getByTestId("location").textContent).toBe("/repos/abc-123/audit/risk?share=xyz");
  });
});

describe("the bare /repos/:repoId index route", () => {
  afterEach(() => {
    window.localStorage.clear();
  });

  it("defaults to Onboard's passport tab when no mode was ever stored", () => {
    renderAt("/repos/abc-123");
    expect(screen.getByTestId("location").textContent).toBe("/repos/abc-123/onboard/passport");
  });

  it("remembers Audit as the last-used mode", () => {
    window.localStorage.setItem(MODE_STORAGE_KEY, "audit");
    renderAt("/repos/abc-123?share=xyz");
    expect(screen.getByTestId("location").textContent).toBe(
      "/repos/abc-123/audit/findings?share=xyz",
    );
  });
});
