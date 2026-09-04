import { useOutletContext } from "react-router-dom";
import { TourPage } from "../onboard/TourPage";
import { PeoplePage } from "../onboard/PeoplePage";
import { GlossaryPanel } from "../onboard/GlossaryPanel";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { useMergedViewParam } from "./mergedView";
import type { RepoOutletContext } from "../RepoLayout";

/**
 * SCAFFOLDING -- `/repos/:id/guide` (rebuild spec section 4.2). Session 3
 * rebuilds this as a real, unified surface ("how do I get into this
 * codebase, and who do I ask"). For now this is a thin `?view=` switch over
 * the three pre-existing pages (Tour, Glossary, People) so the route exists
 * and the app keeps building/running.
 */
export function GuideSurfacePage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const [view, setView] = useMergedViewParam("view", "tour");

  return (
    <div className="flex flex-col gap-4">
      <SegmentedControl
        aria-label="Guide view"
        value={view}
        onValueChange={setView}
        options={[
          { value: "tour", label: "Tour" },
          { value: "glossary", label: "Glossary" },
          { value: "people", label: "People" },
        ]}
      />
      {view === "glossary" ? (
        <GlossaryPanel repoId={repo.id} share={share} onClose={() => setView("tour")} />
      ) : view === "people" ? (
        <PeoplePage />
      ) : (
        <TourPage />
      )}
    </div>
  );
}
