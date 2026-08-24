import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { HomePage } from "./pages/HomePage";
import { DashboardPage } from "./pages/DashboardPage";
import { SharedRedirectPage } from "./pages/SharedRedirectPage";
import { LegacyRedirect, RepoIndexRedirect, RepoLayout } from "./pages/RepoLayout";
import { PassportPage } from "./pages/onboard/PassportPage";
import { TourPage } from "./pages/onboard/TourPage";
import { PeoplePage } from "./pages/onboard/PeoplePage";
import { GlossaryPage } from "./pages/onboard/GlossaryPage";
import { MapPage } from "./pages/onboard/MapPage";
import { ImpactPage } from "./pages/onboard/ImpactPage";
import { CityPage } from "./pages/onboard/CityPage";
import { FindingsPage } from "./pages/audit/FindingsPage";
import { CouplingPage } from "./pages/audit/CouplingPage";
import { ArchitecturePage } from "./pages/audit/ArchitecturePage";
import { RiskPage } from "./pages/audit/RiskPage";
import { HealthPage } from "./pages/audit/HealthPage";

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
            <Route path="dashboard" element={<DashboardPage />} />
            <Route path="shared/:slug" element={<SharedRedirectPage />} />
            <Route path="repos/:repoId" element={<RepoLayout />}>
              <Route index element={<RepoIndexRedirect />} />

              {/* Onboard mode: passport | tour | people | glossary | map |
                  impact | city (the last three added session 09). */}
              <Route path="onboard" element={<Navigate to="passport" replace />} />
              <Route path="onboard/passport" element={<PassportPage />} />
              <Route path="onboard/tour" element={<TourPage />} />
              <Route path="onboard/people" element={<PeoplePage />} />
              <Route path="onboard/glossary" element={<GlossaryPage />} />
              <Route path="onboard/map" element={<MapPage />} />
              <Route path="onboard/impact" element={<ImpactPage />} />
              <Route path="onboard/city" element={<CityPage />} />

              {/* Audit mode: findings | coupling | architecture | risk |
                  health -- fleshed out further in session 11. */}
              <Route path="audit" element={<Navigate to="findings" replace />} />
              <Route path="audit/findings" element={<FindingsPage />} />
              <Route path="audit/coupling" element={<CouplingPage />} />
              <Route path="audit/architecture" element={<ArchitecturePage />} />
              <Route path="audit/risk" element={<RiskPage />} />
              <Route path="audit/health" element={<HealthPage />} />

              {/* Pre-dual-mode paths (session 02 share links point at
                  these) -- redirect rather than 404 (Known Hazard #1). */}
              <Route path="overview" element={<LegacyRedirect to="onboard/passport" />} />
              <Route path="coupling" element={<LegacyRedirect to="audit/coupling" />} />
              <Route path="architecture" element={<LegacyRedirect to="audit/architecture" />} />
              <Route path="risk" element={<LegacyRedirect to="audit/risk" />} />
            </Route>
            <Route
              path="*"
              element={
                <div className="py-16 text-center text-sm text-slate-500 dark:text-slate-400">
                  Page not found.
                </div>
              }
            />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
