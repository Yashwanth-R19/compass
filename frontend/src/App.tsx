import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { HomePage } from "./pages/HomePage";
import { DashboardPage } from "./pages/DashboardPage";
import { SharedRedirectPage } from "./pages/SharedRedirectPage";
import { RepoLayout } from "./pages/RepoLayout";
import { OverviewPage } from "./pages/OverviewPage";
import { CouplingPage } from "./pages/CouplingPage";
import { ArchitecturePage } from "./pages/ArchitecturePage";
import { RiskPage } from "./pages/RiskPage";

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
              <Route index element={<Navigate to="overview" replace />} />
              <Route path="overview" element={<OverviewPage />} />
              <Route path="coupling" element={<CouplingPage />} />
              <Route path="architecture" element={<ArchitecturePage />} />
              <Route path="risk" element={<RiskPage />} />
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
