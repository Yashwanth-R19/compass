import { TourPage } from "../onboard/TourPage";

/** UI rebuild session 3: TourPage.tsx is now the real, complete "tour"
 * surface -- the guided reading order plus the domain glossary as a real
 * side panel (`?panel=glossary`), not a full-page swap. */
export function TourSurfacePage() {
  return <TourPage />;
}
