import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useOutletContext, useSearchParams } from "react-router-dom";
import { ReactFlowProvider, type Node } from "@xyflow/react";
import { useDiagram, useDiagramAi, useTour } from "../../api/hooks";
import type { DiagramResponse } from "../../api/types";
import { StageGate } from "../../components/StageGate";
import { EmptyState } from "../../components/EmptyState";
import { HonestyNote } from "../../components/HonestyNote";
import { Drawer } from "../../components/ui/Drawer";
import { useToast } from "../../components/ui/Toast";
import { AiSummaryBanner } from "../../components/map/AiSummaryBanner";
import { MapCanvas, type FitRequest } from "../../components/map/MapCanvas";
import { MapLegend } from "../../components/map/MapLegend";
import { MapListView } from "../../components/map/MapListView";
import { MapSearch, type SearchItem } from "../../components/map/MapSearch";
import { MapSidePanel, SidePanelContent } from "../../components/map/MapSidePanel";
import { MapToolbar } from "../../components/map/MapToolbar";
import { PathFinder } from "../../components/map/PathFinder";
import { MapContext, type MapContextValue } from "../../components/map/mapContext";
import { HONESTY } from "../../content/explainability";
import {
  MAP_COPY,
  foldedNote,
  pathResultLine,
  truncatedNote,
  weakHiddenNote,
} from "../../content/map";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";
import { activityBucket, type ActivityBucket } from "../../lib/diagram/activity";
import { displayName, edgeVerb, fileTitle, groupHueIndex } from "../../lib/diagram/display";
import { downloadDiagramImage, readCssVar } from "../../lib/diagram/exportImage";
import {
  fileNodeId,
  folderNodeId,
  groupNodeId,
  moreNodeId,
  parseNodeId,
} from "../../lib/diagram/ids";
import { toMermaid } from "../../lib/diagram/mermaid";
import { findPath } from "../../lib/diagram/pathfinder";
import { ancestorFolderPaths, buildGroupTrees, sumChurn } from "../../lib/diagram/tree";
import { readMapUrlState, writeMapUrlState, type MapUrlState } from "../../lib/diagram/urlState";
import { ancestorIds, computeVisible, projectEdges } from "../../lib/diagram/visible";
import type { RepoOutletContext } from "../RepoLayout";

const MOTION_STORAGE_KEY = "compass-map-motion";

function readMotionPref(): boolean {
  try {
    return window.localStorage.getItem(MOTION_STORAGE_KEY) !== "off";
  } catch {
    return true;
  }
}

function writeMotionPref(on: boolean): void {
  try {
    window.localStorage.setItem(MOTION_STORAGE_KEY, on ? "on" : "off");
  } catch {
    // Storage unavailable (private mode etc.) -- the toggle still works for this visit.
  }
}

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(
    () => typeof window !== "undefined" && window.matchMedia(query).matches,
  );
  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

/** `/repos/:id/map` -- the computed architecture diagram. Every box and
 * arrow comes from `GET /repos/{id}/diagram` (a deterministic aggregation of
 * imports, the subsystem partition, entry points and commit-history
 * coupling); the optional AI pass only ever adds text on top. */
export function MapSurfacePage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const [searchParams] = useSearchParams();
  const grouping = searchParams.get("grouping") === "folder" ? "folder" : "subsystem";
  const diagram = useDiagram(repo.id, grouping, share);

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-text-muted">{MAP_COPY.intro}</p>
      <StageGate
        query={diagram}
        loadingLabel={MAP_COPY.loading}
        emptyTitle={MAP_COPY.emptyTitle}
        emptyMessage={MAP_COPY.emptyMessage}
        isEmpty={(data) => !data.facts_archived && data.groups.length === 0}
      >
        {(data) =>
          data.facts_archived ? (
            <EmptyState title={MAP_COPY.archivedTitle} message={MAP_COPY.archivedMessage} />
          ) : (
            <ReactFlowProvider>
              <MapWorkspace data={data} repoOwner={repo.owner} repoName={repo.name} share={share} />
            </ReactFlowProvider>
          )
        }
      </StageGate>
    </div>
  );
}

function MapWorkspace({
  data,
  repoOwner,
  repoName,
  share,
}: {
  data: DiagramResponse;
  repoOwner: string;
  repoName: string;
  share: string | undefined;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const state = useMemo(() => readMapUrlState(searchParams), [searchParams]);
  const showToast = useToast();
  const reducedMotion = usePrefersReducedMotion();
  const narrow = useMediaQuery("(max-width: 639px)");
  const belowMd = useMediaQuery("(max-width: 767px)");
  const containerRef = useRef<HTMLDivElement>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [fitRequest, setFitRequest] = useState<FitRequest | null>(null);
  const [flowNodes, setFlowNodes] = useState<Node[]>([]);
  const [motionOn, setMotionOn] = useState(readMotionPref);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [summaryDismissed, setSummaryDismissed] = useState(false);
  const [findRequest, setFindRequest] = useState<{ query: string; nonce: number } | null>(() =>
    state.find ? { query: state.find, nonce: 0 } : null,
  );

  // React Router's functional setSearchParams reads the params from the last
  // RENDER, so two updates in the same tick (e.g. a click that sets the lens,
  // then another before re-render) would drop the first. Chain every update
  // off the most recent params we wrote instead; reset once the router has
  // caught up (searchParams changed).
  const pendingParams = useRef<URLSearchParams | null>(null);
  useEffect(() => {
    pendingParams.current = null;
  }, [searchParams]);
  const update = useCallback(
    (patch: Partial<MapUrlState>) => {
      const base = pendingParams.current ?? new URLSearchParams(window.location.search);
      const next = writeMapUrlState(base, { ...readMapUrlState(base), ...patch });
      pendingParams.current = next;
      setSearchParams(next, { replace: true });
    },
    [setSearchParams],
  );

  // `?find=` is a one-shot instruction (from the command palette): hand it to
  // the search box (remounting it, so a second "find" while already on the
  // Map works too), then drop it from the URL.
  useEffect(() => {
    if (!state.find) return;
    setFindRequest((prev) =>
      // The mount-time request (nonce 0) is already in the search box.
      prev && prev.nonce === 0 && prev.query === state.find
        ? prev
        : { query: state.find as string, nonce: Date.now() },
    );
    update({ find: null });
  }, [state.find, update]);

  const view = state.view ?? (narrow ? "list" : "diagram");

  const trees = useMemo(() => buildGroupTrees(data), [data]);
  const indexByPath = useMemo(() => new Map(data.files.map((f) => [f.path, f.i])), [data]);
  const expandedKey = state.expanded.join("\n");
  const expandedSet = useMemo(
    () => new Set(expandedKey ? expandedKey.split("\n") : []),
    [expandedKey],
  );
  const graph = useMemo(
    () => computeVisible(data, trees, expandedSet, { showActor: state.entry }),
    [data, trees, expandedSet, state.entry],
  );
  const projected = useMemo(
    () => projectEdges(data, graph, { showWeak: state.weak, showActor: state.entry }),
    [data, graph, state.weak, state.entry],
  );
  const edges = projected.edges;

  // ---- AI labelling (text only, on demand) ----
  const aiQuery = useDiagramAi(data.repo_id, data.grouping, state.ai, share);
  const aiPayload = state.ai && aiQuery.data?.available ? aiQuery.data.payload : null;
  const aiOn = aiPayload !== null;
  const aiGroups = useMemo(
    () => new Map((aiPayload?.groups ?? []).map((g) => [g.group_id, g])),
    [aiPayload],
  );
  const aiBands = useMemo(
    () => new Map((aiPayload?.bands ?? []).map((b) => [b.layer, b.name])),
    [aiPayload],
  );
  const aiVerbs = useMemo(
    () =>
      new Map((aiPayload?.edge_verbs ?? []).map((v) => [`${v.from_group}>${v.to_group}`, v.verb])),
    [aiPayload],
  );

  // ---- Activity lens ----
  const activity = useMemo(() => {
    const result = new Map<string, ActivityBucket>();
    if (state.lens !== "activity") return result;
    const values = new Map<string, number>();
    let max = 0;
    for (const n of graph.nodes) {
      if (n.kind !== "group" && n.kind !== "folder" && n.kind !== "file" && n.kind !== "component")
        continue;
      const v = sumChurn(data, n.fileIndices);
      values.set(n.id, v);
      max = Math.max(max, v);
    }
    for (const [id, v] of values) result.set(id, activityBucket(v, max));
    return result;
  }, [state.lens, graph, data]);

  // ---- Reading-order overlay ----
  const tour = useTour(state.tour ? data.repo_id : undefined, share);
  const tourSteps = useMemo(() => {
    const steps = new Map<string, number[]>();
    if (!state.tour || tour.data?.kind !== "data") return steps;
    for (const stop of tour.data.data.stops) {
      const index = indexByPath.get(stop.file_path);
      if (index == null) continue;
      const owner = graph.ownerOf[index];
      if (!owner) continue;
      const list = steps.get(owner) ?? [];
      list.push(stop.position); // already 1-based, same numbering as the Guide
      steps.set(owner, list);
    }
    for (const list of steps.values()) list.sort((a, b) => a - b);
    return steps;
  }, [state.tour, tour.data, indexByPath, graph]);

  // ---- Focus / path emphasis ----
  const visibleIdFor = useCallback(
    (id: string | null): string | null => {
      if (!id) return null;
      if (graph.byId.has(id)) return id;
      const parsed = parseNodeId(id);
      if (parsed?.kind === "file") {
        const index = indexByPath.get(parsed.path);
        return index != null ? graph.ownerOf[index] || null : null;
      }
      return null;
    },
    [graph, indexByPath],
  );

  const pathResult = useMemo(() => {
    if (!state.path) return null;
    const [from, to] = state.path;
    const a = visibleIdFor(from);
    const b = visibleIdFor(to);
    if (!a || !b) return { result: null, from: a, to: b };
    return { result: findPath(edges, a, b), from: a, to: b };
  }, [state.path, visibleIdFor, edges]);

  const emphasis = useMemo(() => {
    const keep = new Set<string>();
    const addWithAncestors = (id: string) => {
      for (const a of ancestorIds(graph, id)) keep.add(a);
    };
    if (pathResult?.result) {
      for (const id of pathResult.result.nodes) addWithAncestors(id);
      for (const id of pathResult.result.edges) keep.add(id);
      return keep;
    }
    const focus = visibleIdFor(state.focus);
    if (!focus) return null;
    addWithAncestors(focus);
    for (const e of edges) {
      if (e.source === focus || e.target === focus) {
        keep.add(e.id);
        addWithAncestors(e.source);
        addWithAncestors(e.target);
      }
    }
    return keep;
  }, [pathResult, state.focus, visibleIdFor, edges, graph]);

  // ---- Actions ----
  const toggleExpand = useCallback(
    (id: string) => {
      const parsed = parseNodeId(id);
      const isOpen = state.expanded.includes(id);
      let next: string[];
      if (isOpen) {
        const prefix =
          parsed?.kind === "group"
            ? `f:${parsed.groupId}::`
            : parsed?.kind === "folder"
              ? `f:${parsed.groupId}::${parsed.relPath}/`
              : null;
        next = state.expanded.filter((x) => x !== id && !(prefix && x.startsWith(prefix)));
      } else {
        next = [...state.expanded, id];
      }
      update({ expanded: next });
      setFitRequest({ ids: [id], nonce: Date.now(), afterRelayout: true });
    },
    [state.expanded, update],
  );

  const select = useCallback((id: string) => setSelectedId(id || null), []);

  const focusNode = useCallback(
    (id: string) => {
      update({ focus: id, path: null });
      setFitRequest({ ids: [id], nonce: Date.now(), afterRelayout: false });
    },
    [update],
  );

  const revealAndFocus = useCallback(
    (item: SearchItem) => {
      const parsed = parseNodeId(item.id);
      const toExpand = new Set(state.expanded);
      const fitIds: string[] = [item.id];
      if (parsed?.kind === "folder" || parsed?.kind === "file") {
        const groupId =
          parsed.kind === "folder"
            ? parsed.groupId
            : data.files[indexByPath.get(parsed.path) ?? 0]?.group_id;
        const group = data.groups.find((g) => g.id === groupId);
        if (group) {
          const gid = groupNodeId(group.id);
          toExpand.add(gid);
          const chain =
            parsed.kind === "folder"
              ? ancestorFolderPaths(`${parsed.relPath}/x`, "").slice(0, -1)
              : ancestorFolderPaths(parsed.path, group.base_path);
          let parentId = gid;
          for (const rel of chain) {
            const fid = folderNodeId(group.id, rel);
            toExpand.add(fid);
            parentId = fid;
          }
          fitIds.push(moreNodeId(parentId), parentId);
        }
      }
      const nextExpanded = [...toExpand].sort();
      const changed = nextExpanded.join("|") !== [...state.expanded].sort().join("|");
      update({ expanded: nextExpanded, focus: item.id, path: null });
      setSelectedId(item.id);
      setFitRequest({ ids: fitIds, nonce: Date.now(), afterRelayout: changed });
    },
    [state.expanded, data, indexByPath, update],
  );

  // A half-chosen path ("Path from here" clicked, no "to" yet) lives here,
  // not in the URL; it becomes `?path=` once both ends are set.
  const [pathDraft, setPathDraft] = useState<[string, string]>(["", ""]);
  const setPathEnd = useCallback(
    (which: "from" | "to", id: string) => {
      const base = state.path ?? pathDraft;
      const next: [string, string] = which === "from" ? [id, base[1]] : [base[0], id];
      if (next[0] && next[1] && next[0] !== next[1]) {
        setPathDraft(["", ""]);
        update({ path: next, focus: null });
      } else {
        setPathDraft(next);
        update({ path: null, focus: id });
      }
    },
    [state.path, pathDraft, update],
  );

  // Escape clears focus, path and selection.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      if (state.focus || state.path) update({ focus: null, path: null });
      setSelectedId(null);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state.focus, state.path, update]);

  // ---- Fullscreen ----
  const fullscreenSupported = typeof document !== "undefined" && document.fullscreenEnabled;
  useEffect(() => {
    const onChange = () => setIsFullscreen(document.fullscreenElement === containerRef.current);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);
  function toggleFullscreen() {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void containerRef.current?.requestFullscreen();
  }

  // ---- Labels used by search, path picker, Mermaid ----
  const labelFor = useCallback(
    (id: string) => {
      const node = graph.byId.get(id);
      if (!node) return id;
      return displayName(node, aiOn, aiGroups).name;
    },
    [graph, aiOn, aiGroups],
  );

  const searchItems = useMemo<SearchItem[]>(() => {
    const items: SearchItem[] = [];
    for (const g of data.groups) {
      const friendly = aiGroups.get(g.id)?.friendly_name ?? "";
      items.push({
        id: groupNodeId(g.id),
        kind: "group",
        label: g.label,
        haystack: `${g.label} ${friendly} ${g.base_path}`,
        detail: `${g.file_count} files${g.base_path ? ` · ${g.base_path}` : ""}`,
      });
    }
    for (const [groupId, root] of trees) {
      const base = data.groups.find((g) => g.id === groupId)?.base_path ?? "";
      const walk = (folder: typeof root) => {
        for (const f of folder.folders) {
          const full = base ? `${base}/${f.relPath}` : f.relPath;
          items.push({
            id: f.id,
            kind: "folder",
            label: `${f.name}/`,
            haystack: full,
            detail: full,
          });
          walk(f);
        }
      };
      walk(root);
    }
    for (const f of data.files) {
      items.push({
        id: fileNodeId(f.path),
        kind: "file",
        label: f.path.split("/").pop() ?? f.path,
        haystack: f.path,
        detail: f.path,
      });
    }
    return items;
  }, [data, trees, aiGroups]);

  const pathOptions = useMemo(
    () =>
      graph.nodes
        .filter((n) => n.kind !== "more")
        .map((n) => ({ id: n.id, label: `${n.kind}: ${labelFor(n.id)}` }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [graph, labelFor],
  );

  const pathText = useMemo(() => {
    if (!state.path || !pathResult) return null;
    const fromLabel = pathResult.from ? labelFor(pathResult.from) : state.path[0];
    const toLabel = pathResult.to ? labelFor(pathResult.to) : state.path[1];
    const r = pathResult.result;
    return pathResultLine(r?.direction ?? null, fromLabel, toLabel, r ? r.edges.length : 0);
  }, [state.path, pathResult, labelFor]);

  // ---- Export ----
  const fileBase = `compass-map-${repoOwner}-${repoName}-${data.grouping}`;
  async function handleExport(kind: "png" | "svg" | "mermaid") {
    if (kind === "mermaid") {
      const text = toMermaid({
        repoName: `${repoOwner}/${repoName}`,
        grouping: data.grouping,
        aiOn,
        nodes: graph.nodes,
        edges,
        labelOf: (n) => displayName(n, aiOn, aiGroups).name,
        isAiLabel: (n) => displayName(n, aiOn, aiGroups).fromAi,
        bands: data.layers.map((l) => ({
          index: l.index,
          label: (aiOn ? aiBands.get(l.index) : undefined) ?? l.label,
        })),
        infraCategory: (id) => data.infra.find((i) => i.id === id)?.category ?? null,
        verbOf: (e) => edgeVerb(e, aiOn, aiVerbs),
        cycleColor: readCssVar("--cp-danger"),
        hueOf: (n) => groupHueIndex(data, n.groupId),
        titleOf: (n) => fileTitle(n.fileIndex != null ? data.files[n.fileIndex].path : n.label),
      });
      try {
        await navigator.clipboard.writeText(text);
        showToast(MAP_COPY.mermaidCopied);
      } catch {
        showToast(MAP_COPY.clipboardFailed);
      }
      return;
    }
    try {
      await downloadDiagramImage(flowNodes, kind, fileBase);
    } catch {
      showToast(MAP_COPY.exportFailed);
    }
  }

  const childCount = useMemo(() => {
    const counts = new Map<string, number>();
    for (const n of graph.nodes) {
      if (n.parentId) counts.set(n.parentId, (counts.get(n.parentId) ?? 0) + 1);
    }
    return counts;
  }, [graph]);

  const contextValue: MapContextValue = useMemo(
    () => ({
      data,
      lens: state.lens,
      aiOn,
      aiGroups,
      aiBands,
      aiVerbs,
      activity,
      emphasis,
      selectedId,
      tourSteps,
      childCount,
      onToggleExpand: toggleExpand,
      onSelect: select,
    }),
    [
      data,
      state.lens,
      aiOn,
      aiGroups,
      aiBands,
      aiVerbs,
      activity,
      emphasis,
      selectedId,
      tourSteps,
      childCount,
      toggleExpand,
      select,
    ],
  );

  const panelProps = {
    data,
    graph,
    edges,
    trees,
    indexByPath,
    aiOn,
    aiGroups,
    aiVerbs,
    share,
    onSelect: select,
    onToggleExpand: toggleExpand,
    onFocus: focusNode,
    onPathEnd: setPathEnd,
  };

  const notes: string[] = [];
  if (data.stats.other_folded_count > 0) notes.push(foldedNote(data.stats.other_folded_count));
  if (data.stats.imports_truncated) {
    notes.push(truncatedNote(data.stats.import_edge_count, data.caps.max_import_edges));
  }
  if (view === "diagram" && projected.weakHiddenCount > 0 && !state.weak) {
    notes.push(weakHiddenNote(projected.weakHiddenCount));
  }
  if (data.infra.length > 0) notes.push(HONESTY.mapInfraHeuristic);

  return (
    <MapContext.Provider value={contextValue}>
      <div className="flex flex-col gap-3">
        <MapToolbar
          grouping={data.grouping}
          onGrouping={(g) => {
            update({ grouping: g, expanded: [], focus: null, path: null });
            setSelectedId(null);
          }}
          view={view}
          onView={(v) => update({ view: v })}
          activity={state.lens === "activity"}
          onActivity={() => update({ lens: state.lens === "activity" ? "none" : "activity" })}
          entry={state.entry}
          onEntry={() => update({ entry: !state.entry })}
          entryAvailable={data.actor !== null}
          tour={state.tour}
          onTour={() => update({ tour: !state.tour })}
          weak={state.weak}
          onWeak={() => update({ weak: !state.weak })}
          weakAvailable={projected.weakHiddenCount > 0 || state.weak}
          motionOn={motionOn}
          onMotion={() => {
            writeMotionPref(!motionOn);
            setMotionOn(!motionOn);
          }}
          reducedMotion={reducedMotion}
          aiOn={state.ai}
          aiHasData={Boolean(aiQuery.data?.available)}
          onAi={() => {
            setSummaryDismissed(false);
            update({ ai: !state.ai });
          }}
          onExport={(kind) => void handleExport(kind)}
          fullscreenSupported={fullscreenSupported}
          isFullscreen={isFullscreen}
          onFullscreen={toggleFullscreen}
          search={
            <MapSearch
              key={findRequest?.nonce ?? "search"}
              items={searchItems}
              onPick={revealAndFocus}
              initialQuery={findRequest?.query ?? null}
            />
          }
          pathFinder={
            <PathFinder
              options={pathOptions}
              value={state.path ?? (pathDraft[0] || pathDraft[1] ? pathDraft : null)}
              resultText={pathText}
              onFind={(from, to) => {
                setPathDraft(["", ""]);
                update({ path: [from, to], focus: null });
              }}
              onClear={() => {
                setPathDraft(["", ""]);
                update({ path: null });
              }}
            />
          }
        />

        {state.ai && !summaryDismissed ? (
          <AiSummaryBanner query={aiQuery} onDismiss={() => setSummaryDismissed(true)} />
        ) : null}

        {view === "diagram" ? (
          <div
            ref={containerRef}
            className={`cp-map relative overflow-hidden border border-border bg-bg-elevated ${
              isFullscreen ? "rounded-none" : "rounded-lg"
            }`}
            style={{ height: isFullscreen ? "100dvh" : "max(560px, calc(100dvh - 240px))" }}
            data-map-motion={motionOn && !reducedMotion ? "on" : "off"}
          >
            <MapCanvas
              data={data}
              graph={graph}
              edges={edges}
              fitRequest={fitRequest}
              onNodesReady={setFlowNodes}
              overlay={<MapLegend activityOn={state.lens === "activity"} />}
            />
            {selectedId && !belowMd ? (
              <MapSidePanel
                {...panelProps}
                selectedId={selectedId}
                onClose={() => setSelectedId(null)}
              />
            ) : null}
          </div>
        ) : (
          <MapListView
            data={data}
            trees={trees}
            initialExpanded={state.expanded}
            aiOn={aiOn}
            aiGroups={aiGroups}
            onSelect={select}
          />
        )}

        {selectedId && (belowMd || view === "list") ? (
          <Drawer
            open
            onOpenChange={(open) => {
              if (!open) setSelectedId(null);
            }}
            title="Details"
          >
            <SidePanelContent {...panelProps} selectedId={selectedId} />
          </Drawer>
        ) : null}

        {notes.map((text) => (
          <HonestyNote key={text} variant="scope-limitation" text={text} />
        ))}
      </div>
    </MapContext.Provider>
  );
}
