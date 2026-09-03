import { PeoplePage } from "../onboard/PeoplePage";

/** SCAFFOLDING (Part J): "people" has no merge to switch between -- it's a
 * direct 1:1 mount of the existing PeoplePage. Kept as its own file for
 * consistency with the other seven surfaces and so App.tsx's route table
 * reads uniformly. */
export function PeopleSurfacePage() {
  return <PeoplePage />;
}
