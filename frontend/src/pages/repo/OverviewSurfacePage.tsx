import { PassportPage } from "../onboard/PassportPage";
import { HealthPage } from "../audit/HealthPage";

/**
 * SCAFFOLDING (Part J): the interim "overview" surface -- mounts the
 * existing PassportPage verbatim, then the existing HealthPage under an
 * `#health` anchor so the legacy `/repos/:id/audit/health` redirect has
 * somewhere concrete to land. Session 3 rebuilds this as one real,
 * unified surface (passport + health + waterfall + difficulty) rather
 * than two stacked pre-existing pages.
 */
export function OverviewSurfacePage() {
  return (
    <div className="flex flex-col gap-10">
      <PassportPage />
      <div id="health" className="scroll-mt-6 border-t border-border pt-8">
        <p className="cp-label mb-3">Health</p>
        <HealthPage />
      </div>
    </div>
  );
}
