import { useState } from "react";
import { Link } from "react-router-dom";
import { useGlossary } from "../../api/hooks";
import type { GlossaryTermOut } from "../../api/types";
import { Card } from "../../components/ui/Card";
import { Alert } from "../../components/ui/Alert";
import { ScoreExplainer } from "../../components/ScoreExplainer";
import { StageGate } from "../../components/StageGate";

/** The repo-scoped domain glossary, as a side panel on the Tour surface
 * (UI rebuild session 3, Part C) -- reachable at `?panel=glossary`, never a
 * full-page swap. This is DELIBERATELY a different thing from the header
 * glossary (`GlossaryDialog`, session 2): that one explains Compass's own
 * vocabulary; this one extracts THIS repository's own vocabulary from its
 * identifiers and file names. The two share a name and nothing else -- see
 * `GlossaryResponse.limitation`, rendered verbatim below, for the exact
 * scope this panel claims (vocabulary, never definitions). */
export function GlossaryPanel({
  repoId,
  share,
  onClose,
}: {
  repoId: string;
  share?: string;
  onClose: () => void;
}) {
  const glossary = useGlossary(repoId, share);

  return (
    <StageGate
      query={glossary}
      loadingLabel="Extracting domain vocabulary…"
      emptyTitle="No terms extracted"
      emptyMessage="Not enough named symbols or file stems were found to build a glossary."
      isEmpty={(data) => data.terms.length === 0}
    >
      {(data) => (
        <div className="flex flex-col gap-3">
          <Alert variant="info">{data.limitation}</Alert>
          <p className="text-xs text-text-muted">
            This is this repository's own vocabulary, distinct from the header glossary above, which
            explains Compass's own terms.
          </p>
          <Card
            title="Domain vocabulary"
            action={
              <button
                type="button"
                onClick={onClose}
                className="text-xs text-text-muted hover:text-text"
              >
                Close
              </button>
            }
          >
            <p className="mb-2 text-xs text-text-muted">
              {data.terms.length} term{data.terms.length === 1 ? "" : "s"}, ranked by how much this
              codebase revolves around them
            </p>
            <ul className="flex flex-col divide-y divide-border">
              {data.terms.map((term) => (
                <GlossaryTermRow key={term.term} term={term} repoId={repoId} />
              ))}
            </ul>
          </Card>
        </div>
      )}
    </StageGate>
  );
}

function GlossaryTermRow({ term, repoId }: { term: GlossaryTermOut; repoId: string }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <li className="py-2.5">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 text-left"
      >
        <span className="font-mono text-sm font-medium text-text">{term.term}</span>
        <span className="text-xs text-text-muted">
          {term.occurrences} occurrence{term.occurrences === 1 ? "" : "s"}
        </span>
        <span className="text-xs text-text-muted">
          spans {term.subsystem_spread} subsystem{term.subsystem_spread === 1 ? "" : "s"}
        </span>
        <span className="text-xs font-medium text-accent">{expanded ? "Hide" : "Show"} detail</span>
      </button>

      {expanded ? (
        <div className="mt-1.5 ml-1 flex flex-col gap-2">
          {term.defining_paths.length > 0 ? (
            <ul className="flex flex-col gap-1">
              {term.defining_paths.map((path) => (
                <li key={path}>
                  <Link
                    to={`/repos/${repoId}/people?path=${encodeURIComponent(path)}`}
                    className="font-mono text-xs text-text-muted hover:text-accent hover:underline"
                  >
                    {path}
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-text-muted">No defining file found for this term.</p>
          )}
          <ScoreExplainer formulaKey="glossary_term_score" contributions={[]} />
        </div>
      ) : null}
    </li>
  );
}
