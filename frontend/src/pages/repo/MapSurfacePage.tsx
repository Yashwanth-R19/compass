import { MapPage } from "../onboard/MapPage";
import { CityPage } from "../onboard/CityPage";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { useMergedViewParam } from "./mergedView";

/**
 * SCAFFOLDING (Part J): the interim "map" surface. `MapPage` already
 * handles its own graph/treemap switch internally via the SAME `?view=`
 * param (session 09) -- this wrapper only adds the one distinction MapPage
 * does NOT already cover: the separate, lazy-loaded 3D city renderer
 * (`CityPage`). Redirects land here as `?view=graph`, `?view=treemap`
 * (both handled by MapPage itself), or `?view=city` (handled here).
 * Session 3 rebuilds this as one real surface.
 */
export function MapSurfacePage() {
  const [view, setView] = useMergedViewParam("view", "graph");
  const top = view === "city" ? "city" : "map";

  return (
    <div className="flex flex-col gap-4">
      <SegmentedControl
        aria-label="Map view"
        value={top}
        onValueChange={(v) => setView(v === "city" ? "city" : "graph")}
        options={[
          { value: "map", label: "Map" },
          { value: "city", label: "3D City" },
        ]}
      />
      {top === "city" ? <CityPage /> : <MapPage />}
    </div>
  );
}
