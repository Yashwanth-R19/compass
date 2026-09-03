import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { LegacyRedirect, RepoIndexRedirect } from "./RepoLayout";

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search + location.hash}</div>;
}

/** The slice of App.tsx's real route tree relevant to redirects -- every
 * legacy path plus every one of the eight real surfaces, so a redirect
 * that lands somewhere with no matching route (a silent 404) fails the
 * assertion instead of rendering nothing. Mirrors App.tsx's own route
 * list exactly; keep the two in sync by hand. */
function renderAt(initialPath: string) {
  render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="repos/:repoId">
          <Route index element={<RepoIndexRedirect />} />

          {/* The eight real surfaces (section 4.1) -- stand-ins, since
              this test only cares about WHERE navigation lands, not what
              each surface renders. */}
          <Route path="overview" element={<LocationProbe />} />
          <Route path="map" element={<LocationProbe />} />
          <Route path="tour" element={<LocationProbe />} />
          <Route path="people" element={<LocationProbe />} />
          <Route path="findings" element={<LocationProbe />} />
          <Route path="risk" element={<LocationProbe />} />
          <Route path="structure" element={<LocationProbe />} />
          <Route path="evolution" element={<LocationProbe />} />

          {/* Redirects -- section 4.2, verbatim from App.tsx. */}
          <Route path="onboard" element={<LegacyRedirect to="overview" />} />
          <Route path="onboard/passport" element={<LegacyRedirect to="overview" />} />
          <Route path="onboard/tour" element={<LegacyRedirect to="tour" />} />
          <Route path="onboard/people" element={<LegacyRedirect to="people" />} />
          <Route path="onboard/glossary" element={<LegacyRedirect to="tour?panel=glossary" />} />
          <Route path="onboard/map" element={<LegacyRedirect to="map?view=graph" />} />
          <Route path="onboard/city" element={<LegacyRedirect to="map?view=city" />} />
          <Route path="onboard/impact" element={<LegacyRedirect to="structure?view=impact" />} />
          <Route
            path="onboard/evolution"
            element={<LegacyRedirect to="evolution?tab=timeline" />}
          />

          <Route path="audit" element={<LegacyRedirect to="findings" />} />
          <Route path="audit/findings" element={<LegacyRedirect to="findings" />} />
          <Route path="audit/security" element={<LegacyRedirect to="findings?category=secret" />} />
          <Route path="audit/hygiene" element={<LegacyRedirect to="findings?category=hygiene" />} />
          <Route path="audit/coupling" element={<LegacyRedirect to="structure?view=coupling" />} />
          <Route
            path="audit/architecture"
            element={<LegacyRedirect to="structure?view=architecture" />}
          />
          <Route path="audit/risk" element={<LegacyRedirect to="risk?tab=hotspots" />} />
          <Route path="audit/benchmark" element={<LegacyRedirect to="risk?tab=benchmark" />} />
          <Route path="audit/health" element={<LegacyRedirect to="overview#health" />} />

          <Route path="compare" element={<LegacyRedirect to="evolution?tab=compare" />} />

          <Route path="coupling" element={<LegacyRedirect to="structure?view=coupling" />} />
          <Route
            path="architecture"
            element={<LegacyRedirect to="structure?view=architecture" />}
          />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

function expectLocation(text: string) {
  expect(screen.getByTestId("location").textContent).toBe(text);
}

// All 23 redirects, rebuild spec section 4.2, numbered exactly as the spec
// lists them (entry 1 is the bare index route).
describe("all 23 redirects (rebuild spec section 4.2)", () => {
  it("1. /repos/:id -> /repos/:id/overview, preserving ?share=", () => {
    renderAt("/repos/abc-123?share=xyz");
    expectLocation("/repos/abc-123/overview?share=xyz");
  });

  it("2. /repos/:id/onboard -> /repos/:id/overview", () => {
    renderAt("/repos/abc-123/onboard");
    expectLocation("/repos/abc-123/overview");
  });

  it("3. /repos/:id/onboard/passport -> /repos/:id/overview", () => {
    renderAt("/repos/abc-123/onboard/passport");
    expectLocation("/repos/abc-123/overview");
  });

  it("4. /repos/:id/onboard/tour -> /repos/:id/tour", () => {
    renderAt("/repos/abc-123/onboard/tour");
    expectLocation("/repos/abc-123/tour");
  });

  it("5. /repos/:id/onboard/people -> /repos/:id/people", () => {
    renderAt("/repos/abc-123/onboard/people");
    expectLocation("/repos/abc-123/people");
  });

  it("6. /repos/:id/onboard/glossary -> /repos/:id/tour?panel=glossary", () => {
    renderAt("/repos/abc-123/onboard/glossary");
    expectLocation("/repos/abc-123/tour?panel=glossary");
  });

  it("7. /repos/:id/onboard/map -> /repos/:id/map?view=graph", () => {
    renderAt("/repos/abc-123/onboard/map");
    expectLocation("/repos/abc-123/map?view=graph");
  });

  it("8. /repos/:id/onboard/city -> /repos/:id/map?view=city", () => {
    renderAt("/repos/abc-123/onboard/city");
    expectLocation("/repos/abc-123/map?view=city");
  });

  it("9. /repos/:id/onboard/impact -> /repos/:id/structure?view=impact", () => {
    renderAt("/repos/abc-123/onboard/impact");
    expectLocation("/repos/abc-123/structure?view=impact");
  });

  it("10. /repos/:id/onboard/evolution -> /repos/:id/evolution?tab=timeline", () => {
    renderAt("/repos/abc-123/onboard/evolution");
    expectLocation("/repos/abc-123/evolution?tab=timeline");
  });

  it("11. /repos/:id/audit -> /repos/:id/findings", () => {
    renderAt("/repos/abc-123/audit");
    expectLocation("/repos/abc-123/findings");
  });

  it("12. /repos/:id/audit/findings -> /repos/:id/findings", () => {
    renderAt("/repos/abc-123/audit/findings");
    expectLocation("/repos/abc-123/findings");
  });

  it("13. /repos/:id/audit/security -> /repos/:id/findings?category=secret", () => {
    renderAt("/repos/abc-123/audit/security");
    expectLocation("/repos/abc-123/findings?category=secret");
  });

  it("14. /repos/:id/audit/hygiene -> /repos/:id/findings?category=hygiene", () => {
    renderAt("/repos/abc-123/audit/hygiene");
    expectLocation("/repos/abc-123/findings?category=hygiene");
  });

  it("15. /repos/:id/audit/coupling -> /repos/:id/structure?view=coupling", () => {
    renderAt("/repos/abc-123/audit/coupling");
    expectLocation("/repos/abc-123/structure?view=coupling");
  });

  it("16. /repos/:id/audit/architecture -> /repos/:id/structure?view=architecture", () => {
    renderAt("/repos/abc-123/audit/architecture");
    expectLocation("/repos/abc-123/structure?view=architecture");
  });

  it("17. /repos/:id/audit/risk -> /repos/:id/risk?tab=hotspots", () => {
    renderAt("/repos/abc-123/audit/risk");
    expectLocation("/repos/abc-123/risk?tab=hotspots");
  });

  it("18. /repos/:id/audit/benchmark -> /repos/:id/risk?tab=benchmark", () => {
    renderAt("/repos/abc-123/audit/benchmark");
    expectLocation("/repos/abc-123/risk?tab=benchmark");
  });

  it("19. /repos/:id/audit/health -> /repos/:id/overview#health", () => {
    renderAt("/repos/abc-123/audit/health");
    expectLocation("/repos/abc-123/overview#health");
  });

  it("20. /repos/:id/compare -> /repos/:id/evolution?tab=compare", () => {
    renderAt("/repos/abc-123/compare");
    expectLocation("/repos/abc-123/evolution?tab=compare");
  });

  it("21. /repos/:id/coupling -> /repos/:id/structure?view=coupling (session-02 legacy share link)", () => {
    renderAt("/repos/abc-123/coupling");
    expectLocation("/repos/abc-123/structure?view=coupling");
  });

  it("22. /repos/:id/architecture -> /repos/:id/structure?view=architecture (session-02 legacy share link)", () => {
    renderAt("/repos/abc-123/architecture");
    expectLocation("/repos/abc-123/structure?view=architecture");
  });

  it("23. /repos/:id/risk (session-02 legacy share link) resolves directly to the real risk surface", () => {
    // Unlike the other 22, this is deliberately NOT a <Navigate>-based
    // redirect route: the new route table's own "risk" surface is
    // bare-named identically to this legacy path (the exact same
    // "pleasant coincidence" section 4.2's own note describes for
    // "overview", extended here to the one case that note didn't name).
    // App.tsx registers exactly one <Route path="risk">, the real
    // surface -- a second, competing <Route path="risk"> for the
    // redirect would be unreachable dead code at best. Verified here as
    // "the location is exactly the real surface's own path" rather than
    // "the location changed to a redirect target", since no navigation
    // actually occurs.
    renderAt("/repos/abc-123/risk");
    expectLocation("/repos/abc-123/risk");
  });
});

describe("redirects merge ?share= with a fixed target query param, never concatenate", () => {
  it("preserves ?share= through a redirect with no added query param", () => {
    renderAt("/repos/abc-123/onboard/tour?share=xyz");
    expectLocation("/repos/abc-123/tour?share=xyz");
  });

  it("merges ?share= with a redirect's own fixed added query param", () => {
    renderAt("/repos/abc-123/onboard/glossary?share=xyz");
    expectLocation("/repos/abc-123/tour?share=xyz&panel=glossary");
  });

  it("merges ?share= with a redirect target that also carries a #hash", () => {
    renderAt("/repos/abc-123/audit/health?share=xyz");
    expectLocation("/repos/abc-123/overview?share=xyz#health");
  });
});

describe("the bare /repos/:repoId index route", () => {
  it("always lands on the overview surface -- there is no 'last used mode' to remember any more", () => {
    renderAt("/repos/abc-123");
    expectLocation("/repos/abc-123/overview");
  });

  it("preserves ?share= across the index redirect", () => {
    renderAt("/repos/abc-123?share=xyz");
    expectLocation("/repos/abc-123/overview?share=xyz");
  });
});
