import { useEffect, useMemo, useState } from "react";
import { useOutletContext, useSearchParams } from "react-router-dom";
import ForceGraph2D from "react-force-graph-2d";
import {
  useArchitecture,
  useCoupling,
  useHiddenDeps,
  useModuleCoupling,
  useSubsystems,
} from "../../api/hooks";
import type { ModuleCouplingGranularity } from "../../api/types";
import { Card } from "../../components/Card";
import { GraphCanvas } from "../../components/GraphCanvas";
import { GraphCapNotice } from "../../components/GraphCapNotice";
import { colorForSubsystem } from "../../lib/subsystemColors";
import { useCappedGraph, type CappableEdge, type CappableNode } from "../../hooks/useGraphCap";
import { fileName, formatPercent } from "../../lib/format";
import { CHROME, SEVERITY_COLOR } from "../../lib/chartTheme";
import type { RepoOutletContext } from "../RepoLayout";

type Granularity = ModuleCouplingGranularity | "file";

interface CouplingEdge extends CappableEdge {
  isHidden: boolean;
  sharedRevs: number;
  confidence: string;
}

interface CouplingPair {
  a: string;
  b: string;
  coupling_degree: number;
  shared_revs: number;
  confidence: string;
  hidden: boolean;
}

// A hidden dependency (coupled, no import) is this app's flagship insight
// (CLAUDE.md "OverlayEngine") -- it gets the med-severity amber-family
// colour, never a neutral one, so it reads as "worth attention" wherever it
// appears (this graph, the map, a finding chip).
const HIDDEN_COLOR = SEVERITY_COLOR.med;
const NORMAL_COLOR = CHROME.inkMuted;

function pairKey(a: string, b: string): string {
  return [a, b].sort().join("|");
}

/** Cross-references `/module-coupling?granularity=subsystem` (the LOCKED
 * formula, read straight) against `/architecture`'s file-level structural
 * edges aggregated up to subsystem pairs -- a plain existence check ("does
 * ANY import cross this subsystem pair"), which is legitimate to compute
 * client-side because it's a count, not the coupling_degree formula itself
 * (CLAUDE.md's MapPage section: aggregating coupling_degree from file pairs
 * is forbidden; aggregating "is there an edge at all" is not). Directory
 * granularity has no equivalent here -- the backend's directory truncation
 * depth isn't known to the frontend, so hidden-only filtering is offered
 * only at subsystem and file granularity. */
function useStructuralSubsystemPairs(repoId: string, share?: string): Set<string> {
  const subsystems = useSubsystems(repoId, true, share);
  const architecture = useArchitecture(repoId, share);

  return useMemo(() => {
    const pairs = new Set<string>();
    if (subsystems.data?.kind !== "data" || architecture.data?.kind !== "data") return pairs;

    const pathLabel = new Map<string, string>();
    for (const s of subsystems.data.data.subsystems) {
      for (const m of s.members ?? []) pathLabel.set(m.file_path, s.label);
    }
    for (const e of architecture.data.data.edges) {
      const from = pathLabel.get(e.from_path);
      const to = pathLabel.get(e.to_path);
      if (from && to && from !== to) pairs.add(pairKey(from, to));
    }
    return pairs;
  }, [subsystems.data, architecture.data]);
}

/** Coupling (Part D): opens at SUBSYSTEM granularity by default -- legible on
 * a large repo, meaningful on a small one, the same "semantic zoom" default
 * session 09's map already established. A switch drops to directory or file
 * grain; "hidden only" is one click at subsystem/file grain. */
export function CouplingPage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const [searchParams] = useSearchParams();
  const [granularity, setGranularity] = useState<Granularity>("subsystem");
  const [hiddenOnly, setHiddenOnly] = useState(false);
  const [highlightPair, setHighlightPair] = useState<[string, string] | null>(null);

  // A hidden_dependency finding's deep link (lib/findingLinks.ts) arrives as
  // `?pair=a|b&hiddenOnly=1` -- that pair is always a FILE pair (the
  // signature convention for a file-level hidden_dependency finding), so
  // landing here forces file granularity, not whatever was last selected.
  useEffect(() => {
    const pairParam = searchParams.get("pair");
    const hiddenParam = searchParams.get("hiddenOnly");
    if (pairParam) {
      const [a, b] = pairParam.split("|");
      if (a && b) {
        setGranularity("file");
        setHighlightPair([a, b]);
      }
    }
    if (hiddenParam === "1") setHiddenOnly(true);
    // Only react to the deep-link params changing, not every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams.get("pair"), searchParams.get("hiddenOnly")]);

  const moduleCoupling = useModuleCoupling(
    repo.id,
    granularity === "file" ? "directory" : granularity,
    share,
  );
  const fileCoupling = useCoupling(repo.id, share);
  const hiddenDeps = useHiddenDeps(repo.id, share);
  const structuralSubsystemPairs = useStructuralSubsystemPairs(repo.id, share);

  const isLoading =
    granularity === "file"
      ? fileCoupling.isPending || fileCoupling.data?.kind === "pending"
      : moduleCoupling.isPending || moduleCoupling.data?.kind === "pending";
  const isError = granularity === "file" ? fileCoupling.isError : moduleCoupling.isError;

  const { pairs, lowConfidence } = useMemo((): {
    pairs: CouplingPair[];
    lowConfidence: boolean;
  } => {
    if (granularity === "file") {
      if (fileCoupling.data?.kind !== "data") return { pairs: [], lowConfidence: false };
      const hiddenKeys = new Set(
        hiddenDeps.data?.kind === "data"
          ? hiddenDeps.data.data.pairs.map((p) => pairKey(p.file_a_path, p.file_b_path))
          : [],
      );
      return {
        pairs: fileCoupling.data.data.pairs.map((p) => ({
          a: p.file_a_path,
          b: p.file_b_path,
          coupling_degree: p.coupling_degree,
          shared_revs: p.shared_revs,
          confidence: p.confidence,
          hidden: hiddenKeys.has(pairKey(p.file_a_path, p.file_b_path)),
        })),
        lowConfidence: fileCoupling.data.data.low_confidence,
      };
    }
    if (moduleCoupling.data?.kind !== "data") return { pairs: [], lowConfidence: false };
    return {
      pairs: moduleCoupling.data.data.pairs.map((p) => ({
        a: p.module_a,
        b: p.module_b,
        coupling_degree: p.coupling_degree,
        shared_revs: p.shared_revs,
        confidence: p.confidence,
        hidden:
          granularity === "subsystem" &&
          !structuralSubsystemPairs.has(pairKey(p.module_a, p.module_b)),
      })),
      lowConfidence: moduleCoupling.data.data.low_confidence,
    };
  }, [
    granularity,
    fileCoupling.data,
    moduleCoupling.data,
    hiddenDeps.data,
    structuralSubsystemPairs,
  ]);

  const visiblePairs = hiddenOnly ? pairs.filter((p) => p.hidden) : pairs;

  const { nodes, edges } = useMemo(() => {
    const nodeIds = new Set<string>();
    const builtEdges: CouplingEdge[] = visiblePairs.map((p) => {
      nodeIds.add(p.a);
      nodeIds.add(p.b);
      return {
        source: p.a,
        target: p.b,
        weight: p.coupling_degree,
        sharedRevs: p.shared_revs,
        isHidden: p.hidden,
        confidence: p.confidence,
      };
    });
    return { nodes: [...nodeIds].map((id) => ({ id })), edges: builtEdges };
  }, [visiblePairs]);

  const capped = useCappedGraph(nodes, edges);

  if (isError) {
    return (
      <Card>
        <p className="text-sm text-red-600 dark:text-red-400">Couldn't load coupling data.</p>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <GranularitySwitch value={granularity} onChange={setGranularity} />

      {lowConfidence ? (
        <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-500/10 dark:text-amber-400">
          Low confidence: this repo doesn't have much analyzed history yet, so the small-repo
          fallback threshold was used. Treat these pairs as directional signal, not certainty.
        </p>
      ) : null}

      {isLoading ? (
        <Card>
          <p className="py-8 text-center text-sm text-ink-faint">Loading coupling data…</p>
        </Card>
      ) : pairs.length === 0 ? (
        <Card>
          <p className="py-8 text-center text-sm text-ink-faint">
            No coupling pairs found at this granularity yet.
          </p>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px]">
          <Card>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
              <GraphCapNotice
                nodesCapped={capped.nodesCapped}
                edgesCapped={capped.edgesCapped}
                shownNodes={capped.nodes.length}
                totalNodes={capped.totalNodes}
              />
              {granularity !== "directory" ? (
                <label className="flex shrink-0 items-center gap-2 text-xs text-ink-muted">
                  <input
                    type="checkbox"
                    checked={hiddenOnly}
                    onChange={(e) => setHiddenOnly(e.target.checked)}
                    className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 dark:border-slate-600"
                  />
                  Hidden dependencies only
                </label>
              ) : (
                <span className="text-xs text-ink-faint">
                  Hidden-only filtering isn't available at directory granularity.
                </span>
              )}
            </div>
            <GraphCanvas>
              {({ width, height }) => (
                <ForceGraph2D
                  graphData={{ nodes: capped.nodes, links: capped.edges }}
                  width={width}
                  height={height}
                  backgroundColor="rgba(0,0,0,0)"
                  nodeRelSize={4}
                  nodeLabel={(n) => (n as CappableNode).id}
                  nodeColor={(n) => {
                    const id = (n as CappableNode).id;
                    if (highlightPair && (id === highlightPair[0] || id === highlightPair[1]))
                      return CHROME.signal;
                    return granularity === "subsystem" ? colorForSubsystem(id) : CHROME.inkMuted;
                  }}
                  linkColor={(l) =>
                    (l as unknown as CouplingEdge).isHidden ? HIDDEN_COLOR : NORMAL_COLOR
                  }
                  linkWidth={(l) => {
                    const edge = l as unknown as CouplingEdge;
                    return edge.isHidden ? 2 + edge.weight * 4 : 0.5 + edge.weight * 4;
                  }}
                  linkLineDash={(l) => ((l as unknown as CouplingEdge).isHidden ? [6, 3] : null)}
                  linkLabel={(l) => {
                    const link = l as unknown as CouplingEdge;
                    return `${formatPercent(link.weight)} coupled, ${link.sharedRevs} shared commits${link.isHidden ? " — hidden dependency" : ""}`;
                  }}
                />
              )}
            </GraphCanvas>
          </Card>

          <Card
            title="Ranked pairs"
            subtitle={`${visiblePairs.length} of ${pairs.length}${hiddenOnly ? " (hidden only)" : ""}`}
          >
            <ul className="max-h-[480px] divide-y divide-slate-100 overflow-y-auto text-sm dark:divide-slate-800">
              {visiblePairs.map((p) => {
                const isTarget =
                  highlightPair &&
                  pairKey(p.a, p.b) === pairKey(highlightPair[0], highlightPair[1]);
                return (
                  <li
                    key={pairKey(p.a, p.b)}
                    className={`py-2 ${isTarget ? "rounded bg-sky-50 px-1.5 dark:bg-sky-500/10" : ""}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-medium text-ink-muted">
                        {granularity === "file" ? fileName(p.a) : p.a} ↔{" "}
                        {granularity === "file" ? fileName(p.b) : p.b}
                      </span>
                      {p.hidden ? (
                        <span className="shrink-0 rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:bg-amber-500/10 dark:text-amber-400">
                          hidden
                        </span>
                      ) : null}
                    </div>
                    <p className="text-xs text-ink-faint">
                      {formatPercent(p.coupling_degree)} coupled · {p.shared_revs} shared commits ·{" "}
                      {p.confidence} confidence
                    </p>
                  </li>
                );
              })}
            </ul>
          </Card>
        </div>
      )}
    </div>
  );
}

function GranularitySwitch({
  value,
  onChange,
}: {
  value: Granularity;
  onChange: (g: Granularity) => void;
}) {
  const options: { key: Granularity; label: string }[] = [
    { key: "subsystem", label: "Subsystem" },
    { key: "directory", label: "Directory" },
    { key: "file", label: "File" },
  ];
  return (
    <div className="inline-flex w-fit items-center gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-800/60">
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          onClick={() => onChange(o.key)}
          className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
            value === o.key
              ? "bg-indigo-600 text-white"
              : "text-ink-muted hover:bg-slate-200 dark:hover:bg-slate-700"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
