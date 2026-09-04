import { useMemo, useState } from "react";
import { useOutletContext, useSearchParams } from "react-router-dom";
import {
  useArchitecture,
  useBlastRadius,
  useCity,
  useHiddenDeps,
  useModuleCoupling,
  useSubsystems,
} from "../../api/hooks";
import type { ModuleCouplingGranularity } from "../../api/types";
import { Card } from "../../components/ui/Card";
import { Table } from "../../components/ui/Table";
import { Badge } from "../../components/ui/Badge";
import { FileDetailPanel } from "../../components/FileDetailPanel";
import { FilePicker } from "../../components/FilePicker";
import { HonestyNote } from "../../components/HonestyNote";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { StageGate } from "../../components/StageGate";
import { HONESTY } from "../../content/explainability";
import { formatPercent, formatScore } from "../../lib/format";
import { citySubsystemLabelById, toCityFiles } from "../../lib/cityFile";
import { useMergedViewParam } from "./mergedView";
import type { RepoOutletContext } from "../RepoLayout";

/**
 * SCAFFOLDING -- `/repos/:id/explore` (rebuild spec section 4.3). The
 * canvas-based map/graph/treemap this surface used to mount was deleted
 * (D6/D14/D15): this is a compact, list-only placeholder covering the same
 * three views (files / structure / impact) with real data so the route
 * exists and the app keeps building/running. Session 3 replaces this with
 * the real sortable file table, the ranked coupling/cycle lists with tiny
 * hand-authored inline SVGs, and the full impact explorer per section 4.3.
 */
export function ExploreSurfacePage() {
  const [view, setView] = useMergedViewParam("view", "files");

  return (
    <div className="flex flex-col gap-4">
      <SegmentedControl
        aria-label="Explore view"
        value={view}
        onValueChange={setView}
        options={[
          { value: "files", label: "Files" },
          { value: "structure", label: "Structure" },
          { value: "impact", label: "Impact" },
        ]}
      />
      {view === "structure" ? (
        <StructureView />
      ) : view === "impact" ? (
        <ImpactView />
      ) : (
        <FilesView />
      )}
    </div>
  );
}

// --- Files ------------------------------------------------------------------

function FilesView() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const subsystems = useSubsystems(repo.id, true, share);
  const city = useCity(repo.id, share);
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <StageGate
      query={subsystems}
      loadingLabel="Loading subsystems…"
      emptyTitle="No subsystems detected"
    >
      {(subsystemData) => (
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
          <Card title="Subsystems" className="lg:w-64 lg:shrink-0">
            <ul className="flex flex-col divide-y divide-border">
              {subsystemData.subsystems.map((s) => (
                <li key={s.label} className="flex flex-col gap-1 py-2 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-text">{s.label}</span>
                    <span className="cp-stat text-xs text-text-muted">{s.file_count} files</span>
                  </div>
                  <div className="h-1 w-full overflow-hidden rounded-full bg-bg-inset">
                    <div
                      className="h-full rounded-full bg-accent"
                      style={{ width: `${Math.round(s.cohesion * 100)}%` }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          </Card>

          <div className="min-w-0 flex-1">
            <StageGate
              query={city}
              loadingLabel="Loading file metrics…"
              emptyTitle="No files"
              isEmpty={(data) => data.files.rows.length === 0}
            >
              {(cityData) => {
                const files = toCityFiles(cityData);
                const labelById = citySubsystemLabelById(cityData);
                const selectedFile = files.find((f) => f.path === selected);
                return (
                  <div className="flex flex-col gap-4">
                    <Card
                      title="Files"
                      eyebrow={`${files.length} files`}
                      action={
                        <FilePicker
                          paths={files.map((f) => f.path)}
                          onSelect={setSelected}
                          placeholder="Jump to file…"
                        />
                      }
                    >
                      <Table
                        rowKey={(f) => f.path}
                        rows={files}
                        emptyMessage="No files."
                        columns={[
                          {
                            key: "path",
                            header: "Path",
                            render: (f) => (
                              <button
                                type="button"
                                onClick={() => setSelected(f.path)}
                                className="max-w-[360px] truncate text-left font-mono text-xs text-accent hover:underline"
                                title={f.path}
                              >
                                {f.path}
                              </button>
                            ),
                          },
                          {
                            key: "loc",
                            header: "LOC",
                            numeric: true,
                            align: "right",
                            render: (f) => f.loc.toLocaleString(),
                          },
                          {
                            key: "complexity",
                            header: "Complexity",
                            numeric: true,
                            align: "right",
                            render: (f) => formatScore(f.complexity, 1),
                          },
                          {
                            key: "risk",
                            header: "Risk",
                            numeric: true,
                            align: "right",
                            render: (f) => (f.riskScore != null ? formatPercent(f.riskScore) : "—"),
                          },
                          {
                            key: "commits",
                            header: "Commits",
                            numeric: true,
                            align: "right",
                            render: (f) => f.commitCount.toLocaleString(),
                          },
                        ]}
                      />
                    </Card>

                    {selectedFile ? (
                      <FileDetailPanel
                        repoId={repo.id}
                        path={selectedFile.path}
                        loc={selectedFile.loc}
                        complexity={selectedFile.complexity}
                        riskScore={selectedFile.riskScore}
                        subsystemLabel={
                          selectedFile.subsystemId != null
                            ? (labelById.get(selectedFile.subsystemId) ?? null)
                            : null
                        }
                        onClose={() => setSelected(null)}
                      />
                    ) : null}
                  </div>
                );
              }}
            </StageGate>
          </div>
        </div>
      )}
    </StageGate>
  );
}

// --- Structure ----------------------------------------------------------------

function StructureView() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const architecture = useArchitecture(repo.id, share);
  const hiddenDeps = useHiddenDeps(repo.id, share);
  const [granularity, setGranularity] = useState<ModuleCouplingGranularity>("subsystem");
  const moduleCoupling = useModuleCoupling(repo.id, granularity, share);

  return (
    <div className="flex flex-col gap-4">
      <StageGate
        query={architecture}
        loadingLabel="Loading architecture…"
        emptyTitle="No cycles or layering violations"
      >
        {(data) => (
          <Card
            title="Cycles & layering"
            eyebrow={`${data.cycles.length} cycle${data.cycles.length === 1 ? "" : "s"} · ${data.layering_violations.length} layering violation${data.layering_violations.length === 1 ? "" : "s"}`}
          >
            {data.cycles.length === 0 && data.layering_violations.length === 0 ? (
              <p className="py-4 text-center text-sm text-text-muted">
                No circular dependencies or layering violations detected.
              </p>
            ) : (
              <ul className="flex flex-col divide-y divide-border text-sm">
                {data.cycles.map((c, i) => (
                  <li key={`cycle-${i}`} className="py-2">
                    <Badge tone={c.severity}>cycle</Badge>{" "}
                    <span className="font-mono text-xs text-text-muted">{c.files.join(" → ")}</span>
                  </li>
                ))}
                {data.layering_violations.map((v, i) => (
                  <li key={`layer-${i}`} className="py-2">
                    <Badge tone={v.severity}>{v.kind}</Badge>{" "}
                    <span className="font-mono text-xs text-text-muted">
                      {v.from_path} → {v.to_path}
                    </span>
                  </li>
                ))}
              </ul>
            )}

            {data.unreferenced_files.length > 0 ? (
              <div className="mt-4 border-t border-border pt-3">
                <h3 className="cp-label mb-1.5 text-text-muted">
                  Unreferenced files ({data.unreferenced_files.length})
                </h3>
                <p className="mb-2 text-xs text-text-muted">{data.unreferenced_files_caveat}</p>
                <ul className="flex flex-col gap-1">
                  {data.unreferenced_files.slice(0, 15).map((f) => (
                    <li key={f.file_path} className="font-mono text-xs text-text-muted">
                      {f.file_path}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </Card>
        )}
      </StageGate>

      <StageGate
        query={hiddenDeps}
        loadingLabel="Loading coupling…"
        emptyTitle="No hidden dependencies"
        emptyMessage="Every strongly-coupled file pair also shares a structural import."
        isEmpty={(data) => data.pairs.length === 0}
      >
        {(data) => (
          <Card title="Hidden dependencies" eyebrow="Coupled but not structurally connected">
            <ul className="flex flex-col divide-y divide-border text-sm">
              {data.pairs.map((p, i) => (
                <li key={i} className="flex items-center justify-between gap-2 py-2">
                  <span className="truncate font-mono text-xs text-text-muted">
                    {p.file_a_path} ↔ {p.file_b_path}
                  </span>
                  <span className="cp-stat shrink-0 text-xs text-warning">
                    {formatPercent(p.coupling_degree)}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </StageGate>

      <Card
        title="Module coupling"
        action={
          <SegmentedControl
            aria-label="Coupling granularity"
            value={granularity}
            onValueChange={(v) => setGranularity(v as ModuleCouplingGranularity)}
            options={[
              { value: "directory", label: "Directory" },
              { value: "subsystem", label: "Subsystem" },
            ]}
          />
        }
      >
        {granularity === "directory" ? (
          <HonestyNote
            variant="scope-limitation"
            text={HONESTY.directoryGrainHasNoStructuralCrossReference}
            className="mb-2"
          />
        ) : null}
        <StageGate
          query={moduleCoupling}
          loadingLabel="Loading module coupling…"
          emptyTitle="No module pairs above the coupling threshold"
          isEmpty={(data) => data.pairs.length === 0}
        >
          {(data) => (
            <ul className="flex flex-col divide-y divide-border text-sm">
              {data.pairs.map((p, i) => (
                <li key={i} className="flex items-center justify-between gap-2 py-2">
                  <span className="truncate font-mono text-xs text-text-muted">
                    {p.module_a} ↔ {p.module_b}
                  </span>
                  <span className="cp-stat shrink-0 text-xs text-text-muted">
                    {formatPercent(p.coupling_degree)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </StageGate>
      </Card>
    </div>
  );
}

// --- Impact -------------------------------------------------------------------

function ImpactView() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const [searchParams, setSearchParams] = useSearchParams();
  const path = searchParams.get("path") ?? undefined;
  const depth = Number(searchParams.get("depth") ?? "3");
  const city = useCity(repo.id, share);
  const blastRadius = useBlastRadius(repo.id, path, depth, share);

  const allPaths = useMemo(
    () => (city.data?.kind === "data" ? toCityFiles(city.data.data).map((f) => f.path) : []),
    [city.data],
  );

  function selectPath(next: string) {
    setSearchParams(
      (prev) => {
        const merged = new URLSearchParams(prev);
        merged.set("view", "impact");
        merged.set("path", next);
        return merged;
      },
      { replace: true },
    );
  }

  return (
    <Card title="Blast radius" eyebrow="What could be affected by changing one file">
      <FilePicker paths={allPaths} onSelect={selectPath} placeholder="Pick a file…" />

      {!path ? (
        <p className="mt-4 py-6 text-center text-sm text-text-muted">
          Pick a file above to see its blast radius.
        </p>
      ) : (
        <div className="mt-4">
          <StageGate
            query={blastRadius}
            loadingLabel="Computing blast radius…"
            emptyTitle="No affected files"
          >
            {(data) => (
              <div className="flex flex-col gap-4">
                {data.surprising_affected.length > 0 ? (
                  <div className="rounded-md border border-2 border-warning bg-warning-bg p-3">
                    <h3 className="cp-label mb-2 text-warning">
                      Coupled but never imported ({data.surprising_affected.length})
                    </h3>
                    <ul className="flex flex-col gap-1">
                      {data.surprising_affected.map((f) => (
                        <li key={f.file_path} className="font-mono text-xs text-text">
                          {f.file_path}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <h3 className="cp-label mb-1.5 text-text-muted">
                      Imports this file ({data.structural_affected.length})
                    </h3>
                    <ul className="flex flex-col gap-1">
                      {data.structural_affected.map((f) => (
                        <li
                          key={f.file_path}
                          className="truncate font-mono text-xs text-text-muted"
                        >
                          {f.file_path}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <h3 className="cp-label mb-1.5 text-text-muted">
                      Changes with this file ({data.historical_affected.length})
                    </h3>
                    <ul className="flex flex-col gap-1">
                      {data.historical_affected.map((f) => (
                        <li
                          key={f.file_path}
                          className="truncate font-mono text-xs text-text-muted"
                        >
                          {f.file_path}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
            )}
          </StageGate>
        </div>
      )}
    </Card>
  );
}
