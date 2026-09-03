import { FindingsPage } from "../audit/FindingsPage";
import { SecurityPage } from "../audit/SecurityPage";
import { HygienePage } from "../audit/HygienePage";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { useMergedViewParam } from "./mergedView";

/**
 * SCAFFOLDING (Part J): the interim "findings" surface. `?category=secret`
 * and `?category=hygiene` swap in the existing SecurityPage/HygienePage
 * (their own specialised sections -- grouped secrets/vulnerabilities, the
 * commit-hygiene timeline) rather than FindingsPage's plain ranked list,
 * matching the legacy `audit/security`/`audit/hygiene` redirects. Any
 * other category value (or none) renders FindingsPage, which already has
 * its own local category dropdown covering every category including
 * these two, just without the specialised layout. Session 4 rebuilds this
 * as one real merged surface.
 */
export function FindingsSurfacePage() {
  const [category, setCategory] = useMergedViewParam("category", "");
  const segment =
    category === "secret" ? "secret" : category === "hygiene" ? "hygiene" : "findings";

  return (
    <div className="flex flex-col gap-4">
      <SegmentedControl
        aria-label="Findings section"
        value={segment}
        onValueChange={(v) => setCategory(v === "findings" ? "" : v)}
        options={[
          { value: "findings", label: "Findings" },
          { value: "secret", label: "Security" },
          { value: "hygiene", label: "Hygiene" },
        ]}
      />
      {segment === "secret" ? (
        <SecurityPage />
      ) : segment === "hygiene" ? (
        <HygienePage />
      ) : (
        <FindingsPage />
      )}
    </div>
  );
}
