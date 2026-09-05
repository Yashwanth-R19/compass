import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { HomePage } from "./pages/HomePage";
import { WelcomePage } from "./pages/WelcomePage";
import { HowItWorksPage } from "./pages/HowItWorksPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ProfilePage } from "./pages/ProfilePage";
import { PortfolioRedirect } from "./pages/PortfolioRedirect";
import { SharedRedirectPage } from "./pages/SharedRedirectPage";
import { LegacyRedirect, RepoIndexRedirect, RepoLayout } from "./pages/RepoLayout";
import { OverviewSurfacePage } from "./pages/repo/OverviewSurfacePage";
import { GuideSurfacePage } from "./pages/repo/GuideSurfacePage";
import { ExploreSurfacePage } from "./pages/repo/ExploreSurfacePage";
import { FindingsSurfacePage } from "./pages/repo/FindingsSurfacePage";
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
            <Route path="welcome" element={<WelcomePage />} />
            <Route path="how-it-works" element={<HowItWorksPage />} />
            {/* D12: /how-it-works absorbs /methods -- session 4 builds the
                #methods section itself; this redirect exists now so no link
                to the old page ever 404s. */}
            <Route
              path="methods"
              element={<LegacyRedirect to="/how-it-works#methods" absolute />}
            />
            <Route path="dashboard" element={<DashboardPage />} />
            <Route path="profile" element={<ProfilePage />} />
            {/* D7: the Portfolio feature was cut entirely. A one-time toast
                explains the removal instead of a silent 404. */}
            <Route path="portfolio" element={<PortfolioRedirect />} />
            <Route path="shared/:slug" element={<SharedRedirectPage />} />

            <Route path="repos/:repoId" element={<RepoLayout />}>
              {/* The bare index route -- always lands on Overview. */}
              <Route index element={<RepoIndexRedirect />} />

              {/* The five real repository surfaces (rebuild spec section 4). */}
              <Route path="overview" element={<OverviewSurfacePage />} />
              <Route path="guide" element={<GuideSurfacePage />} />
              <Route path="explore" element={<ExploreSurfacePage />} />
              <Route path="findings" element={<FindingsSurfacePage />} />
              <Route path="evolution" element={<EvolutionSurfacePage />} />

              {/* Every currently-live path must keep working (section
                  4.6) -- both the pre-consolidation eight-surface paths
                  this app shipped with until a moment ago, and the
                  session-02-era legacy share-link paths that predate even
                  those. */}
              <Route path="map" element={<LegacyRedirect to="explore?view=files" />} />
              <Route path="onboard" element={<LegacyRedirect to="overview" />} />
              <Route path="onboard/passport" element={<LegacyRedirect to="overview" />} />
              <Route path="onboard/tour" element={<LegacyRedirect to="guide?view=tour" />} />
              <Route
                path="onboard/glossary"
                element={<LegacyRedirect to="guide?view=glossary" />}
              />
              <Route path="onboard/people" element={<LegacyRedirect to="guide?view=people" />} />
              <Route path="people" element={<LegacyRedirect to="guide?view=people" />} />
              <Route path="onboard/map" element={<LegacyRedirect to="explore?view=files" />} />
              <Route path="onboard/city" element={<LegacyRedirect to="explore?view=files" />} />
              <Route path="onboard/impact" element={<LegacyRedirect to="explore?view=impact" />} />
              <Route
                path="onboard/evolution"
                element={<LegacyRedirect to="evolution?view=timeline" />}
              />

              <Route path="structure" element={<LegacyRedirect to="explore?view=structure" />} />
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
                element={<LegacyRedirect to="explore?view=structure" />}
              />
              <Route path="coupling" element={<LegacyRedirect to="explore?view=structure" />} />
              <Route
                path="audit/architecture"
                element={<LegacyRedirect to="explore?view=structure" />}
              />
              <Route path="architecture" element={<LegacyRedirect to="explore?view=structure" />} />
              <Route path="audit/risk" element={<LegacyRedirect to="findings?view=risk" />} />
              <Route path="risk" element={<LegacyRedirect to="findings?view=risk" />} />
              <Route
                path="audit/benchmark"
                element={<LegacyRedirect to="findings?view=benchmark" />}
              />
              <Route path="audit/health" element={<LegacyRedirect to="overview#health" />} />

              <Route path="compare" element={<LegacyRedirect to="evolution?view=compare" />} />
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
