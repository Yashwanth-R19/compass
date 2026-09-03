import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { HomePage } from "./pages/HomePage";
import { HowItWorksPage } from "./pages/HowItWorksPage";
import { MethodsPage } from "./pages/MethodsPage";
import { DashboardPage } from "./pages/DashboardPage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { SharedRedirectPage } from "./pages/SharedRedirectPage";
import { LegacyRedirect, RepoIndexRedirect, RepoLayout } from "./pages/RepoLayout";
import { OverviewSurfacePage } from "./pages/repo/OverviewSurfacePage";
import { MapSurfacePage } from "./pages/repo/MapSurfacePage";
import { TourSurfacePage } from "./pages/repo/TourSurfacePage";
import { PeopleSurfacePage } from "./pages/repo/PeopleSurfacePage";
import { FindingsSurfacePage } from "./pages/repo/FindingsSurfacePage";
import { RiskSurfacePage } from "./pages/repo/RiskSurfacePage";
import { StructureSurfacePage } from "./pages/repo/StructureSurfacePage";
import { EvolutionSurfacePage } from "./pages/repo/EvolutionSurfacePage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<HomePage />} />
            <Route path="how-it-works" element={<HowItWorksPage />} />
            <Route path="methods" element={<MethodsPage />} />
            <Route path="dashboard" element={<DashboardPage />} />
            <Route path="portfolio" element={<PortfolioPage />} />
            <Route path="shared/:slug" element={<SharedRedirectPage />} />

            <Route path="repos/:repoId" element={<RepoLayout />}>
              {/* Redirect #1 of 23 (section 4.2) -- the bare index route. */}
              <Route index element={<RepoIndexRedirect />} />

              {/* The eight real repository surfaces (section 4.1). */}
              <Route path="overview" element={<OverviewSurfacePage />} />
              <Route path="map" element={<MapSurfacePage />} />
              <Route path="tour" element={<TourSurfacePage />} />
              <Route path="people" element={<PeopleSurfacePage />} />
              <Route path="findings" element={<FindingsSurfacePage />} />
              {/*
                Redirect #23 ("/repos/:id/risk -> /repos/:id/risk?tab=hotspots",
                the session-02 legacy share-link path) is NOT a separate
                route here -- it is the exact same "pleasant coincidence"
                the rebuild spec calls out for "overview" (section 4.2's own
                note), extended to this one case the spec's own note didn't
                name: the new real surface is ALSO bare-named "risk", and
                RiskSurfacePage already defaults its ?tab= to "hotspots"
                when absent (pages/repo/RiskSurfacePage.tsx), so visiting
                the legacy bare path produces byte-identical rendered
                output to the redirect's own target. Registering a second
                <Route path="risk"> here would either silently shadow this
                real surface or never be reached, depending on order --
                genuinely unreachable/harmful, not just redundant. See
                DESIGN_NOTES.md for this session's note on the discrepancy
                between the spec's literal 23-entry list and this one
                necessary exception, and RepoLayout.redirects.test.tsx for
                how this specific case is verified instead.
              */}
              <Route path="risk" element={<RiskSurfacePage />} />
              <Route path="structure" element={<StructureSurfacePage />} />
              <Route path="evolution" element={<EvolutionSurfacePage />} />

              {/* Pre-consolidation dual-mode paths (session 08) --
                  redirects #2-10 (onboard/*) and #11-19 (audit/*, minus
                  audit/risk which is folded into risk's own redirect
                  below) plus #20 (compare). */}
              <Route path="onboard" element={<LegacyRedirect to="overview" />} />
              <Route path="onboard/passport" element={<LegacyRedirect to="overview" />} />
              <Route path="onboard/tour" element={<LegacyRedirect to="tour" />} />
              <Route path="onboard/people" element={<LegacyRedirect to="people" />} />
              <Route
                path="onboard/glossary"
                element={<LegacyRedirect to="tour?panel=glossary" />}
              />
              <Route path="onboard/map" element={<LegacyRedirect to="map?view=graph" />} />
              <Route path="onboard/city" element={<LegacyRedirect to="map?view=city" />} />
              <Route
                path="onboard/impact"
                element={<LegacyRedirect to="structure?view=impact" />}
              />
              <Route
                path="onboard/evolution"
                element={<LegacyRedirect to="evolution?tab=timeline" />}
              />

              <Route path="audit" element={<LegacyRedirect to="findings" />} />
              <Route path="audit/findings" element={<LegacyRedirect to="findings" />} />
              <Route
                path="audit/security"
                element={<LegacyRedirect to="findings?category=secret" />}
              />
              <Route
                path="audit/hygiene"
                element={<LegacyRedirect to="findings?category=hygiene" />}
              />
              <Route
                path="audit/coupling"
                element={<LegacyRedirect to="structure?view=coupling" />}
              />
              <Route
                path="audit/architecture"
                element={<LegacyRedirect to="structure?view=architecture" />}
              />
              <Route path="audit/risk" element={<LegacyRedirect to="risk?tab=hotspots" />} />
              <Route path="audit/benchmark" element={<LegacyRedirect to="risk?tab=benchmark" />} />
              <Route path="audit/health" element={<LegacyRedirect to="overview#health" />} />

              <Route path="compare" element={<LegacyRedirect to="evolution?tab=compare" />} />

              {/* Session-02 legacy share-link paths (still-live links, not
                  a one-time migration aid -- must continue to work
                  indefinitely). "risk" itself is handled above as a real
                  route, not here -- see the comment on that route. */}
              <Route path="coupling" element={<LegacyRedirect to="structure?view=coupling" />} />
              <Route
                path="architecture"
                element={<LegacyRedirect to="structure?view=architecture" />}
              />
            </Route>

            <Route
              path="*"
              element={
                <div className="py-16 text-center text-sm text-text-muted">Page not found.</div>
              }
            />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
