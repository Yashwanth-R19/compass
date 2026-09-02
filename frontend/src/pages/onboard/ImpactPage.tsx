import { useMemo, useState } from "react";
import { useOutletContext, useSearchParams } from "react-router-dom";
import { useBlastRadius, useKnowledgeMap } from "../../api/hooks";
import type { BlastRadiusAffectedFileOut, BlastRadiusResponse } from "../../api/types";
import { Card } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { EvidenceLink } from "../../components/EvidenceLink";
import { FilePicker } from "../../components/FilePicker";
import { LoadingState } from "../../components/LoadingState";
import { PartialResultNotice } from "../../components/PartialResultNotice";
import { formatPercent } from "../../lib/format";
import type { RepoOutletContext } from "../RepoLayout";

const MIN_DEPTH = 1;
const MAX_DEPTH = 6;
const DEFAULT_DEPTH = 3;

function clampDepth(value: number): number {
  return Math.min(MAX_DEPTH, Math.max(MIN_DEPTH, value));
}

/** The impact / blast-radius explorer (Part D). Deep-linkable via
 * `?path=<path>&depth=<n>` -- a tour stop, a finding, or the codebase map's
 * selected-file panel can all link straight into a specific blast radius,
 * per this session's own cross-page linking convention. */
export function ImpactPage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const [searchParams, setSearchParams] = useSearchParams();
  const knowledgeMap = useKnowledgeMap(repo.id, share);

  const [selectedPath, setSelectedPath] = useState<string | null>(searchParams.get("path"));
  const [depth, setDepth] = useState(
    clampDepth(Number(searchParams.get("depth")) || DEFAULT_DEPTH),
  );

  const blastRadius = useBlastRadius(repo.id, selectedPath ?? undefined, depth, share);

  const paths = useMemo(() => {
    if (knowledgeMap.data?.kind !== "data") return [];
    return knowledgeMap.data.data.files.map((f) => f.file_path);
  }, [knowledgeMap.data]);

  function selectPath(path: string) {
    setSelectedPath(path);
    setSearchParams({ path, depth: String(depth) }, { replace: true });
  }

  function changeDepth(next: number) {
    const clamped = clampDepth(next);
    setDepth(clamped);
    if (selectedPath)
      setSearchParams({ path: selectedPath, depth: String(clamped) }, { replace: true });
  }

  return (
    <div className="flex flex-col gap-4">
      <Card title="Impact explorer" subtitle="Pick a file to see what it affects">
        <FilePicker paths={paths} onSelect={selectPath} placeholder="Search files by path…" />
      </Card>

      {!selectedPath ? (
        <EmptyState
          title="Pick a file"
          message="Select a file above to see its structural and historical blast radius."
        />
      ) : blastRadius.isPending ? (
        <LoadingState label="Computing blast radius…" />
      ) : blastRadius.isError ? (
        <ErrorState error={blastRadius.error} onRetry={() => void blastRadius.refetch()} />
      ) : blastRadius.data.kind === "pending" ? (
        <LoadingState label="Computing blast radius…" />
      ) : (
        <BlastRadiusResult
          data={blastRadius.data.data}
          repoUrl={repo.url}
          depth={depth}
          onDepthChange={changeDepth}
        />
      )}
    </div>
  );
}

function BlastRadiusResult({
  data,
  repoUrl,
  depth,
  onDepthChange,
}: {
  data: BlastRadiusResponse;
  repoUrl: string;
  depth: number;
  onDepthChange: (depth: number) => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      <DepthSlider depth={depth} onChange={onDepthChange} />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Headline label="Files affected" value={data.total_affected_count.toLocaleString()} />
        <Headline label="% of repository" value={formatPercent(data.percentage_of_repo_files)} />
        <Headline
          label="Subsystems touched"
          value={data.subsystems_touched.length.toLocaleString()}
        />
        <Headline label="Reviewers needed" value={data.experts_to_review.length.toLocaleString()} />
      </div>

      {/* The money output (Part D): coupled-but-not-imported, FIRST and
          visually distinct -- this is the non-obvious result and the whole
          reason blast radius exists as a feature, not a footnote below the
          two "obvious" lists. */}
      <Card
        title="Coupled but NOT imported"
        subtitle="Changes with this file historically, with no import connecting them at all"
        className="border-amber-300 ring-1 ring-amber-200 dark:border-amber-500/40 dark:ring-amber-500/20"
      >
        {data.surprising_affected.length === 0 ? (
          <p className="text-sm text-ink-faint">
            Nothing surprising -- every historically co-changed file is also structurally connected.
          </p>
        ) : (
          <ul className="flex flex-col divide-y divide-amber-100 dark:divide-amber-500/10">
            {data.surprising_affected.map((f) => (
              <AffectedFileRow key={f.file_path} file={f} showCoupling />
            ))}
          </ul>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card
          title="Imports you, directly or transitively"
          subtitle={`${data.structural_affected.length} files`}
        >
          <PartialResultNotice
            shown={data.structural_affected.length}
            total={data.structural_affected.length}
            itemLabel="structurally affected files"
            capped={data.depth_capped || data.node_cap_engaged}
          />
          {data.structural_affected.length === 0 ? (
            <p className="text-sm text-ink-faint">No structural dependents.</p>
          ) : (
            <ul className="flex max-h-96 flex-col divide-y divide-slate-100 overflow-y-auto dark:divide-slate-800">
              {data.structural_affected.map((f) => (
                <AffectedFileRow key={f.file_path} file={f} showHops />
              ))}
            </ul>
          )}
        </Card>

        <Card
          title="Changes with you historically"
          subtitle={`${data.historical_affected.length} files`}
        >
          {data.historical_affected.length === 0 ? (
            <p className="text-sm text-ink-faint">No strong historical coupling.</p>
          ) : (
            <ul className="flex max-h-96 flex-col divide-y divide-slate-100 overflow-y-auto dark:divide-slate-800">
              {data.historical_affected.map((f) => (
                <AffectedFileRow key={f.file_path} file={f} showCoupling />
              ))}
            </ul>
          )}
        </Card>
      </div>

      {data.historical_evidence.length > 0 ? (
        <Card
          title="Historical evidence"
          subtitle={`Of ${data.commits_touching_path} commits touching this file`}
        >
          <ul className="flex flex-col divide-y divide-slate-100 text-sm dark:divide-slate-800">
            {data.historical_evidence.map((e) => (
              <li key={e.affected_path} className="flex flex-col gap-1 py-2.5">
                <p className="text-ink-muted">
                  Of the {data.commits_touching_path} commits touching this file,{" "}
                  <span className="font-medium">{e.shared_commit_count}</span> (
                  {formatPercent(e.shared_commit_percentage)}) also touched{" "}
                  <span className="font-mono text-xs">{e.affected_path}</span>
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {e.example_shas.map((sha) => (
                    <EvidenceLink key={sha} repoUrl={repoUrl} sha={sha} />
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}

function AffectedFileRow({
  file,
  showHops = false,
  showCoupling = false,
}: {
  file: BlastRadiusAffectedFileOut;
  showHops?: boolean;
  showCoupling?: boolean;
}) {
  return (
    <li className="flex items-center justify-between gap-2 py-2 text-sm">
      <span className="truncate font-mono text-xs text-ink-muted" title={file.file_path}>
        {file.file_path}
      </span>
      <span className="shrink-0 text-xs text-ink-faint">
        {showHops && file.hop_distance != null
          ? `${file.hop_distance} hop${file.hop_distance === 1 ? "" : "s"}`
          : null}
        {showCoupling && file.coupling_degree != null ? formatPercent(file.coupling_degree) : null}
      </span>
    </li>
  );
}

function Headline({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
      <p className="text-xs text-ink-muted">{label}</p>
      <p className="text-xl font-semibold tabular-nums text-ink">{value}</p>
    </div>
  );
}

function DepthSlider({ depth, onChange }: { depth: number; onChange: (depth: number) => void }) {
  return (
    <label className="flex items-center gap-3 text-xs text-ink-muted">
      Depth
      <input
        type="range"
        min={MIN_DEPTH}
        max={MAX_DEPTH}
        step={1}
        value={depth}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-40 accent-indigo-600"
      />
      <span className="tabular-nums font-medium text-ink">{depth}</span>
    </label>
  );
}
