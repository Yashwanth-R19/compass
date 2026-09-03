import { ArchitecturePage } from "../audit/ArchitecturePage";
import { CouplingPage } from "../audit/CouplingPage";
import { ImpactPage } from "../onboard/ImpactPage";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { useMergedViewParam } from "./mergedView";

/**
 * SCAFFOLDING (Part J): the interim "structure" surface --
 * `?view=architecture` (default) / `coupling` / `impact`. `ImpactPage`
 * writes its OWN `path`/`depth` params via a plain (non-merging)
 * `setSearchParams` call, which drops this wrapper's `view` param as a
 * side effect -- `useMergedViewParam` is specifically written to tolerate
 * that (see its own docstring) rather than snapping back to Architecture
 * the moment a file is selected on the Impact view. Session 4 rebuilds
 * this as one real surface.
 */
export function StructureSurfacePage() {
  const [view, setView] = useMergedViewParam("view", "architecture");
  const active = view === "coupling" || view === "impact" ? view : "architecture";

  return (
    <div className="flex flex-col gap-4">
      <SegmentedControl
        aria-label="Structure view"
        value={active}
        onValueChange={setView}
        options={[
          { value: "architecture", label: "Architecture" },
          { value: "coupling", label: "Coupling" },
          { value: "impact", label: "Impact" },
        ]}
      />
      {active === "coupling" ? (
        <CouplingPage />
      ) : active === "impact" ? (
        <ImpactPage />
      ) : (
        <ArchitecturePage />
      )}
    </div>
  );
}
