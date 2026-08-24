import { lazy, Suspense } from "react";
import { useOutletContext } from "react-router-dom";
import { useCity } from "../../api/hooks";
import { LoadingState } from "../../components/LoadingState";
import { StageGate } from "../../components/StageGate";
import type { RepoOutletContext } from "../RepoLayout";

// Lazy-loaded so a user who never opens the city page never downloads
// three.js/@react-three/fiber/@react-three/drei (session 09, Part F --
// "users who never open the city do not download three"). This dynamic
// import is what makes Vite emit a SEPARATE chunk for CodeCity.tsx and
// everything it imports; verify with `npm run build` and check the output
// for a distinct chunk file, don't assume this line alone is sufficient.
const CodeCity = lazy(() =>
  import("../../components/CodeCity").then((m) => ({ default: m.CodeCity })),
);

export function CityPage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const city = useCity(repo.id, share);

  return (
    <StageGate
      query={city}
      loadingLabel="Loading the city payload…"
      emptyTitle="No files yet"
      isEmpty={(data) => data.files.rows.length === 0}
    >
      {(cityData) => (
        <Suspense fallback={<LoadingState label="Loading the 3D city renderer…" />}>
          <CodeCity repoId={repo.id} city={cityData} />
        </Suspense>
      )}
    </StageGate>
  );
}
