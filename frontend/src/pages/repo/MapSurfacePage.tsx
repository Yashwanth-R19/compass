import { MapPage } from "../onboard/MapPage";

/** UI rebuild session 3: MapPage.tsx is now the real, complete "map"
 * surface -- graph/treemap/3D-city behind its own `?view=` switch. This
 * wrapper exists only so App.tsx's eight-surface route table reads
 * uniformly (every surface route points at a `*SurfacePage` in this
 * directory); MapPage stays under `pages/onboard/` because
 * `lib/chartTheme.test.ts` reads that exact file path off disk to verify
 * it imports `colorForSubsystem` from `lib/subsystemColors` rather than a
 * local palette -- do not move it. */
export function MapSurfacePage() {
  return <MapPage />;
}
