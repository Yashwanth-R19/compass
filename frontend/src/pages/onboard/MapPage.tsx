import { useMemo, useState } from "react";
import { Link, useOutletContext, useSearchParams } from "react-router-dom";
import ForceGraph2D from "react-force-graph-2d";
import {
  useArchitecture,
  useCity,
  useCoupling,
  useHiddenDeps,
  useModuleCoupling,
  useSubsystems,
} from "../../api/hooks";
import type { CityResponse, ModuleCouplingPairOut, SubsystemsResponse } from "../../api/types";
import { Card } from "../../components/Card";
import { DirectoryTreemap } from "../../components/DirectoryTreemap";
import { FileDetailPanel } from "../../components/FileDetailPanel";
import { GraphCanvas } from "../../components/GraphCanvas";
import { GraphCapNotice } from "../../components/GraphCapNotice";
import { ModeSelect } from "../../components/ModeSelect";
import { StageGate } from "../../components/StageGate";
import { useCappedGraph, type CappableEdge, type CappableNode } from "../../hooks/useGraphCap";
import { toCityFile, type CityFile } from "../../lib/cityFile";
import { fileName } from "../../lib/format";
import { average, majority, ownerColor, recencyColor, riskColor } from "../../lib/metricColor";
import { colorForSubsystem, UNASSIGNED_COLOR } from "../../lib/subsystemColors";
import type { RepoOutletContext } from "../RepoLayout";

type ColorMode = "subsystem" | "risk" | "owner" | "recency";
type EdgeMode = "structural" | "coupling" | "both";
type MapView = "graph" | "treemap";

const COLOR_MODE_LABEL: Record<ColorMode, string> = {
  subsystem: "Subsystem",
  risk: "Risk",
  owner: "Principal author",
  recency: "Recency",
};

const EDGE_MODE_LABEL: Record<EdgeMode, string> = {
  structural: "Structural imports only",
  coupling: "Coupling only",
  both: "Both",
};

// --- Shared city-derived lookups --------------------------------------------
// The map page's flagship interaction (expand a subsystem into its files,
// colour by risk/owner/recency) needs per-file metrics that only /city
// carries (raw LOC, risk_score, principal_expert_id, last_modified_at --
// CLAUDE.md's "Codebase map" section). /subsystems remains the PRIMARY,
// earlier-available gate for the graph's basic subsystem-level view
// (it only needs the "subsystems" stage, several stages before "onboarding"
// which /city gates on) -- city data is used opportunistically to enrich
// colouring once it's ready, never to block the graph's first paint.

interface CityLookups {
  byPath: Map<string, CityFile>;
  labelById: Map<number, string>;
  boundsLastModified: { min: number; max: number };
}

function useCityLookups(city: CityResponse | undefined): CityLookups | null {
  return useMemo(() => {
    if (!city) return null;
    return {
      byPath: new Map(city.files.rows.map((r) => [r[0], toCityFile(r)])),
      labelById: new Map(city.subsystems.map((s) => [s.id, s.label])),
      boundsLastModified: city.bounds.last_modified_at,
    };
  }, [city]);
}

/** Never opens at file level (CLAUDE.md's semantic-zoom rule): the default
 * view is the subsystem graph, collapsed. Switching to the treemap or
 * expanding a subsystem are both explicit user actions. */
export function MapPage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const [searchParams] = useSearchParams();
  const [view, setView] = useState<MapView>((searchParams.get("view") as MapView) ?? "graph");

  const subsystems = useSubsystems(repo.id, true, share);
  const moduleCoupling = useModuleCoupling(repo.id, "subsystem", share);
  const architecture = useArchitecture(repo.id, share);
  const coupling = useCoupling(repo.id, share);
  const hiddenDeps = useHiddenDeps(repo.id, share);
  const city = useCity(repo.id, share);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex items-center gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-800/60">
          <button
            type="button"
            onClick={() => setView("graph")}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              view === "graph"
                ? "bg-indigo-600 text-white"
                : "text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
            }`}
          >
            Subsystem graph
          </button>
          <button
            type="button"
            onClick={() => setView("treemap")}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              view === "treemap"
                ? "bg-indigo-600 text-white"
                : "text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
            }`}
          >
            Treemap
          </button>
        </div>
        <Link
          to={`/repos/${repo.id}/onboard/city`}
          className="text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
        >
          View as 3D city →
        </Link>
      </div>

      {view === "graph" ? (
        <StageGate
          query={subsystems}
          loadingLabel="Detecting subsystems…"
          emptyTitle="No subsystems detected"
          emptyMessage="This repo doesn't have enough structure (imports, coupling) to partition into subsystems yet."
          isEmpty={(data) => data.subsystems.length === 0}
        >
          {(subsystemsData) => (
            <SubsystemGraphView
              subsystemsData={subsystemsData}
              moduleCouplingPairs={
                moduleCoupling.data?.kind === "data" ? moduleCoupling.data.data.pairs : []
              }
              archEdges={architecture.data?.kind === "data" ? architecture.data.data.edges : []}
              couplingPairs={coupling.data?.kind === "data" ? coupling.data.data.pairs : []}
              hiddenPairs={hiddenDeps.data?.kind === "data" ? hiddenDeps.data.data.pairs : []}
              city={city.data?.kind === "data" ? city.data.data : undefined}
              repoId={repo.id}
            />
          )}
        </StageGate>
      ) : (
        <StageGate
          query={city}
          loadingLabel="Loading file metrics for the treemap…"
          emptyTitle="No files yet"
          isEmpty={(data) => data.files.rows.length === 0}
        >
          {(cityData) => <DirectoryTreemap city={cityData} />}
        </StageGate>
      )}
    </div>
  );
}

// --- Subsystem graph, semantic zoom -----------------------------------------

interface MapNode extends CappableNode {
  kind: "subsystem" | "file";
  label: string;
  size: number;
  subsystemLabel: string | null;
  city?: CityFile;
}

interface MapEdge extends CappableEdge {
  hidden: boolean;
  hasStructural: boolean;
  hasCoupling: boolean;
}

function pairKey(a: string, b: string): string {
  return a < b ? `${a}|${b}` : `${b}|${a}`;
}

/** Client-side aggregation of file-level structural edges up to subsystem
 * granularity -- legitimate here (unlike coupling_degree, which the LOCKED
 * formula forbids aggregating from file pairs, see CLAUDE.md's
 * "Module-level coupling") because "does an import cross this subsystem
 * pair" is a plain count, not a formula whose inputs are per-pair
 * revision ratios. */
function structuralSubsystemCounts(
  edges: { from_path: string; to_path: string }[],
  fileLabel: Map<string, string>,
): Map<string, number> {
  const counts = new Map<string, number>();
  for (const e of edges) {
    const a = fileLabel.get(e.from_path);
    const b = fileLabel.get(e.to_path);
    if (!a || !b || a === b) continue;
    const key = pairKey(a, b);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return counts;
}

function couplingSubsystemWeights(pairs: ModuleCouplingPairOut[]): Map<string, number> {
  const weights = new Map<string, number>();
  for (const p of pairs) {
    const key = pairKey(p.module_a, p.module_b);
    weights.set(key, Math.max(weights.get(key) ?? 0, p.coupling_degree));
  }
  return weights;
}

function subsystemLevelEdges(
  structuralCounts: Map<string, number>,
  couplingWeights: Map<string, number>,
  edgeMode: EdgeMode,
  exclude?: string,
): MapEdge[] {
  const keys = new Set<string>();
  if (edgeMode !== "coupling") for (const k of structuralCounts.keys()) keys.add(k);
  if (edgeMode !== "structural") for (const k of couplingWeights.keys()) keys.add(k);

  const edges: MapEdge[] = [];
  for (const key of keys) {
    const [a, b] = key.split("|");
    if (exclude && (a === exclude || b === exclude)) continue;
    const hasStructural = structuralCounts.has(key);
    const hasCoupling = couplingWeights.has(key);
    const weight = hasCoupling
      ? couplingWeights.get(key)!
      : Math.min(1, (structuralCounts.get(key) ?? 0) / 5);
    edges.push({
      source: a,
      target: b,
      weight,
      hidden: hasCoupling && !hasStructural,
      hasStructural,
      hasCoupling,
    });
  }
  return edges;
}

function SubsystemGraphView({
  subsystemsData,
  moduleCouplingPairs,
  archEdges,
  couplingPairs,
  hiddenPairs,
  city,
  repoId,
}: {
  subsystemsData: SubsystemsResponse;
  moduleCouplingPairs: ModuleCouplingPairOut[];
  archEdges: { from_path: string; to_path: string }[];
  couplingPairs: { file_a_path: string; file_b_path: string; coupling_degree: number }[];
  hiddenPairs: { file_a_path: string; file_b_path: string }[];
  city?: CityResponse;
  repoId: string;
}) {
  const [colorMode, setColorMode] = useState<ColorMode>("subsystem");
  const [edgeMode, setEdgeMode] = useState<EdgeMode>("both");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);

  const cityLookups = useCityLookups(city);

  const fileSubsystemLabel = useMemo(() => {
    const map = new Map<string, string>();
    for (const s of subsystemsData.subsystems) {
      for (const m of s.members ?? []) map.set(m.file_path, s.label);
    }
    return map;
  }, [subsystemsData]);

  const structuralCounts = useMemo(
    () => structuralSubsystemCounts(archEdges, fileSubsystemLabel),
    [archEdges, fileSubsystemLabel],
  );
  const couplingWeights = useMemo(
    () => couplingSubsystemWeights(moduleCouplingPairs),
    [moduleCouplingPairs],
  );
  const hiddenFilePairKeys = useMemo(
    () => new Set(hiddenPairs.map((p) => pairKey(p.file_a_path, p.file_b_path))),
    [hiddenPairs],
  );

  // Aggregate colour-mode values per subsystem label, computed once city
  // data is available -- a subsystem collapsed to one node still needs a
  // representative risk/owner/recency value to colour itself by.
  const subsystemAggregates = useMemo(() => {
    if (!cityLookups) return null;
    const byLabel = new Map<
      string,
      { risk: number[]; owners: (number | null)[]; recency: number[] }
    >();
    for (const file of cityLookups.byPath.values()) {
      const label = file.subsystemId != null ? cityLookups.labelById.get(file.subsystemId) : null;
      if (!label) continue;
      let bucket = byLabel.get(label);
      if (!bucket) {
        bucket = { risk: [], owners: [], recency: [] };
        byLabel.set(label, bucket);
      }
      if (file.riskScore != null) bucket.risk.push(file.riskScore);
      bucket.owners.push(file.principalExpertId);
      bucket.recency.push(file.lastModifiedAt);
    }
    const result = new Map<
      string,
      { avgRisk: number | null; ownerId: number | null; avgRecency: number | null }
    >();
    for (const [label, bucket] of byLabel) {
      result.set(label, {
        avgRisk: average(bucket.risk),
        ownerId: majority(bucket.owners),
        avgRecency: average(bucket.recency),
      });
    }
    return result;
  }, [cityLookups]);

  const { nodes, edges } = useMemo(() => {
    if (!expanded) {
      const nodes: MapNode[] = subsystemsData.subsystems.map((s) => ({
        id: s.label,
        kind: "subsystem",
        label: s.label,
        subsystemLabel: s.label,
        size: s.file_count,
      }));
      return { nodes, edges: subsystemLevelEdges(structuralCounts, couplingWeights, edgeMode) };
    }

    const expandedSubsystem = subsystemsData.subsystems.find((s) => s.label === expanded);
    const memberPaths = new Set((expandedSubsystem?.members ?? []).map((m) => m.file_path));

    const nodes: MapNode[] = [];
    for (const s of subsystemsData.subsystems) {
      if (s.label === expanded) continue;
      nodes.push({
        id: s.label,
        kind: "subsystem",
        label: s.label,
        subsystemLabel: s.label,
        size: s.file_count,
      });
    }
    for (const path of memberPaths) {
      nodes.push({
        id: path,
        kind: "file",
        label: fileName(path),
        subsystemLabel: expanded,
        size: 1,
        city: cityLookups?.byPath.get(path),
      });
    }

    const internal = new Map<string, MapEdge>();
    if (edgeMode !== "coupling") {
      for (const e of archEdges) {
        if (e.from_path === e.to_path) continue;
        if (!memberPaths.has(e.from_path) || !memberPaths.has(e.to_path)) continue;
        const key = pairKey(e.from_path, e.to_path);
        const existing = internal.get(key);
        if (existing) existing.hasStructural = true;
        else
          internal.set(key, {
            source: e.from_path,
            target: e.to_path,
            weight: 0.3,
            hidden: false,
            hasStructural: true,
            hasCoupling: false,
          });
      }
    }
    if (edgeMode !== "structural") {
      for (const p of couplingPairs) {
        if (!memberPaths.has(p.file_a_path) || !memberPaths.has(p.file_b_path)) continue;
        const key = pairKey(p.file_a_path, p.file_b_path);
        const hidden = hiddenFilePairKeys.has(key);
        const existing = internal.get(key);
        if (existing) {
          existing.hasCoupling = true;
          existing.weight = Math.max(existing.weight, p.coupling_degree);
          existing.hidden = existing.hidden || hidden;
        } else {
          internal.set(key, {
            source: p.file_a_path,
            target: p.file_b_path,
            weight: p.coupling_degree,
            hidden,
            hasStructural: false,
            hasCoupling: true,
          });
        }
      }
    }

    // External: one endpoint is a member file, the other belongs to a
    // still-collapsed subsystem -- redirected to that subsystem's node id
    // and deduped, so the expanded view doesn't draw one edge per remote
    // file (only per remote SUBSYSTEM).
    const external = new Map<string, MapEdge>();
    function addExternal(
      filePath: string,
      otherLabel: string,
      weight: number,
      hidden: boolean,
      hasStructural: boolean,
      hasCoupling: boolean,
    ) {
      const key = `${filePath}=>${otherLabel}`;
      const existing = external.get(key);
      if (existing) {
        existing.weight = Math.max(existing.weight, weight);
        existing.hidden = existing.hidden || hidden;
        existing.hasStructural = existing.hasStructural || hasStructural;
        existing.hasCoupling = existing.hasCoupling || hasCoupling;
      } else {
        external.set(key, {
          source: filePath,
          target: otherLabel,
          weight,
          hidden,
          hasStructural,
          hasCoupling,
        });
      }
    }
    if (edgeMode !== "coupling") {
      for (const e of archEdges) {
        const aIn = memberPaths.has(e.from_path);
        const bIn = memberPaths.has(e.to_path);
        if (aIn === bIn) continue;
        const filePath = aIn ? e.from_path : e.to_path;
        const otherPath = aIn ? e.to_path : e.from_path;
        const otherLabel = fileSubsystemLabel.get(otherPath);
        if (!otherLabel || otherLabel === expanded) continue;
        addExternal(filePath, otherLabel, 0.3, false, true, false);
      }
    }
    if (edgeMode !== "structural") {
      for (const p of couplingPairs) {
        const aIn = memberPaths.has(p.file_a_path);
        const bIn = memberPaths.has(p.file_b_path);
        if (aIn === bIn) continue;
        const filePath = aIn ? p.file_a_path : p.file_b_path;
        const otherPath = aIn ? p.file_b_path : p.file_a_path;
        const otherLabel = fileSubsystemLabel.get(otherPath);
        if (!otherLabel || otherLabel === expanded) continue;
        const hidden = hiddenFilePairKeys.has(pairKey(p.file_a_path, p.file_b_path));
        addExternal(filePath, otherLabel, p.coupling_degree, hidden, false, true);
      }
    }

    const otherSubsystemEdges = subsystemLevelEdges(
      structuralCounts,
      couplingWeights,
      edgeMode,
      expanded,
    );

    return { nodes, edges: [...internal.values(), ...external.values(), ...otherSubsystemEdges] };
  }, [
    expanded,
    subsystemsData,
    structuralCounts,
    couplingWeights,
    edgeMode,
    archEdges,
    couplingPairs,
    hiddenFilePairKeys,
    fileSubsystemLabel,
    cityLookups,
  ]);

  const capped = useCappedGraph(nodes, edges);

  function colorForNode(n: MapNode): string {
    if (colorMode === "subsystem") return colorForSubsystem(n.subsystemLabel);
    if (colorMode === "risk") {
      const risk =
        n.kind === "file"
          ? (n.city?.riskScore ?? null)
          : (subsystemAggregates?.get(n.label)?.avgRisk ?? null);
      return riskColor(risk);
    }
    if (colorMode === "owner") {
      const ownerId =
        n.kind === "file"
          ? (n.city?.principalExpertId ?? null)
          : (subsystemAggregates?.get(n.label)?.ownerId ?? null);
      return ownerColor(ownerId);
    }
    const bounds = cityLookups?.boundsLastModified;
    const value =
      n.kind === "file"
        ? (n.city?.lastModifiedAt ?? null)
        : (subsystemAggregates?.get(n.label)?.avgRecency ?? null);
    return bounds ? recencyColor(value, bounds.min, bounds.max) : UNASSIGNED_COLOR;
  }

  const selectedCityFile = selectedFile ? cityLookups?.byPath.get(selectedFile) : undefined;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-4">
        <ModeSelect
          label="Colour by"
          value={colorMode}
          onChange={setColorMode}
          options={COLOR_MODE_LABEL}
          disabledOptions={cityLookups ? [] : (["risk", "owner", "recency"] as ColorMode[])}
        />
        <ModeSelect
          label="Edges"
          value={edgeMode}
          onChange={setEdgeMode}
          options={EDGE_MODE_LABEL}
        />
        {expanded ? (
          <span className="text-xs text-slate-500 dark:text-slate-400">
            Expanded:{" "}
            <span className="font-medium text-slate-700 dark:text-slate-200">{expanded}</span>{" "}
            <button
              type="button"
              onClick={() => setExpanded(null)}
              className="ml-1 text-indigo-600 hover:underline dark:text-indigo-400"
            >
              collapse
            </button>
          </span>
        ) : (
          <span className="text-xs text-slate-400 dark:text-slate-500">
            Click a subsystem to expand it into its files.
          </span>
        )}
      </div>

      {/* The flagship visual distinction (Part C): a hidden dependency (coupled,
          no import) is amber, thicker, AND dashed -- not one subtle cue alone. */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_300px]">
        <Card>
          <GraphCapNotice
            nodesCapped={capped.nodesCapped}
            edgesCapped={capped.edgesCapped}
            shownNodes={capped.nodes.length}
            totalNodes={capped.totalNodes}
          />
          <GraphCanvas height={560}>
            {({ width, height }) => (
              <ForceGraph2D
                graphData={{ nodes: capped.nodes, links: capped.edges }}
                width={width}
                height={height}
                backgroundColor="rgba(0,0,0,0)"
                nodeRelSize={5}
                nodeVal={(n) => (n as MapNode).size}
                nodeLabel={(n) => (n as MapNode).id}
                nodeColor={(n) => colorForNode(n as MapNode)}
                linkColor={(l) => ((l as unknown as MapEdge).hidden ? "#f97316" : "#94a3b8")}
                linkWidth={(l) => {
                  const edge = l as unknown as MapEdge;
                  return edge.hidden ? 2.5 + edge.weight * 3 : 0.6 + edge.weight * 2;
                }}
                linkLineDash={(l) => ((l as unknown as MapEdge).hidden ? [6, 3] : null)}
                onNodeClick={(n) => {
                  const node = n as MapNode;
                  if (node.kind === "subsystem") {
                    setExpanded((current) => (current === node.label ? null : node.label));
                    setSelectedFile(null);
                  } else {
                    setSelectedFile((current) => (current === node.id ? null : node.id));
                  }
                }}
                onBackgroundClick={() => {
                  setExpanded(null);
                  setSelectedFile(null);
                }}
              />
            )}
          </GraphCanvas>
        </Card>

        <div className="flex flex-col gap-4">
          <Card title="Subsystems" subtitle={`${subsystemsData.subsystems.length} detected`}>
            <ul className="flex flex-col divide-y divide-slate-100 text-sm dark:divide-slate-800">
              {subsystemsData.subsystems.map((s) => (
                <li key={s.label} className="flex items-center justify-between gap-2 py-1.5">
                  <button
                    type="button"
                    onClick={() => {
                      setExpanded((current) => (current === s.label ? null : s.label));
                      setSelectedFile(null);
                    }}
                    className="flex items-center gap-2 truncate text-left hover:underline"
                  >
                    <span
                      className="h-2.5 w-2.5 shrink-0 rounded-full"
                      style={{ backgroundColor: colorForSubsystem(s.label) }}
                    />
                    <span className={expanded === s.label ? "font-semibold" : ""}>{s.label}</span>
                  </button>
                  <span className="shrink-0 text-xs text-slate-400 dark:text-slate-500">
                    {s.file_count} files
                  </span>
                </li>
              ))}
            </ul>
          </Card>

          {selectedFile ? (
            <FileDetailPanel
              repoId={repoId}
              path={selectedFile}
              loc={selectedCityFile?.loc}
              complexity={selectedCityFile?.complexity}
              riskScore={selectedCityFile?.riskScore}
              subsystemLabel={fileSubsystemLabel.get(selectedFile) ?? null}
              onClose={() => setSelectedFile(null)}
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}
