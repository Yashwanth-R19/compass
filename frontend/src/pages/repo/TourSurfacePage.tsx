import { TourPage } from "../onboard/TourPage";
import { GlossaryPage } from "../onboard/GlossaryPage";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { useMergedViewParam } from "./mergedView";

/**
 * SCAFFOLDING (Part J): the interim "tour" surface -- `?panel=glossary`
 * shows the existing GlossaryPage in place of the guided reading order.
 * Session 3 rebuilds this as one surface with the glossary as a real
 * panel alongside the tour, not a full-page swap.
 */
export function TourSurfacePage() {
  const [panel, setPanel] = useMergedViewParam("panel", "tour");

  return (
    <div className="flex flex-col gap-4">
      <SegmentedControl
        aria-label="Tour panel"
        value={panel === "glossary" ? "glossary" : "tour"}
        onValueChange={setPanel}
        options={[
          { value: "tour", label: "Tour" },
          { value: "glossary", label: "Glossary" },
        ]}
      />
      {panel === "glossary" ? <GlossaryPage /> : <TourPage />}
    </div>
  );
}
