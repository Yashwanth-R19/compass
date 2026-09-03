import { EvolutionPage } from "../onboard/EvolutionPage";
import { ComparePage } from "../ComparePage";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { useMergedViewParam } from "./mergedView";

/** SCAFFOLDING (Part J): the interim "evolution" surface --
 * `?tab=timeline` (default) mounts the existing EvolutionPage,
 * `?tab=compare` mounts the existing ComparePage. Session 4 rebuilds this
 * as one real surface. */
export function EvolutionSurfacePage() {
  const [tab, setTab] = useMergedViewParam("tab", "timeline");
  const active = tab === "compare" ? "compare" : "timeline";

  return (
    <div className="flex flex-col gap-4">
      <SegmentedControl
        aria-label="Evolution view"
        value={active}
        onValueChange={setTab}
        options={[
          { value: "timeline", label: "Timeline" },
          { value: "compare", label: "Compare" },
        ]}
      />
      {active === "compare" ? <ComparePage /> : <EvolutionPage />}
    </div>
  );
}
