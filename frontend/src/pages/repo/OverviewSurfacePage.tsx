import { OverviewPage } from "../onboard/OverviewPage";

/** UI rebuild session 3: OverviewPage.tsx is now the real, complete
 * "overview" surface -- passport + health + waterfall + difficulty as one
 * unified page (replacing the former separately-stacked PassportPage and
 * HealthPage). The `#health` anchor the legacy `/repos/:id/audit/health`
 * redirect targets lives on OverviewPage's own health section now. */
export function OverviewSurfacePage() {
  return <OverviewPage />;
}
