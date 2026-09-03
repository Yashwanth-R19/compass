import { RiskPage } from "../audit/RiskPage";
import { BenchmarkPage } from "../audit/BenchmarkPage";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { useMergedViewParam } from "./mergedView";

/** SCAFFOLDING (Part J): the interim "risk" surface -- `?tab=hotspots`
 * (default) mounts RiskPage, `?tab=benchmark` mounts BenchmarkPage.
 * Session 4 rebuilds this as one real surface. */
export function RiskSurfacePage() {
  const [tab, setTab] = useMergedViewParam("tab", "hotspots");
  const active = tab === "benchmark" ? "benchmark" : "hotspots";

  return (
    <div className="flex flex-col gap-4">
      <SegmentedControl
        aria-label="Risk view"
        value={active}
        onValueChange={setTab}
        options={[
          { value: "hotspots", label: "Hotspots" },
          { value: "benchmark", label: "Benchmark" },
        ]}
      />
      {active === "benchmark" ? <BenchmarkPage /> : <RiskPage />}
    </div>
  );
}
