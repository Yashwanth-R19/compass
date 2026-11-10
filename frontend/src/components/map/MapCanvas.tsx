import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Background,
  BackgroundVariant,
  ConnectionMode,
  Controls,
  MiniMap,
  ReactFlow,
  getNodesBounds,
  useReactFlow,
  useStoreApi,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useTheme } from "../../theme/ThemeProvider";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";
import { MAP_COPY } from "../../content/map";
import type { DiagramResponse } from "../../api/types";
import { resolvedGroupColor } from "../../lib/diagram/display";
import { layoutDiagram } from "../../lib/diagram/layout";
import type { VisibleEdge, VisibleGraph } from "../../lib/diagram/visible";
import { Skeleton } from "../ui/Skeleton";
import type { DiagramEdgeData } from "./DiagramEdge";
import type { DiagramNodeData } from "./MapNodes";
import { mapEdgeTypes, mapNodeTypes, NODE_TYPE_FOR_KIND } from "./flowTypes";
import { useMapContext } from "./mapContext";

/** Below this zoom the boxes switch to their compact titles. The first view
 * never opens smaller than this unless the map is too WIDE to fit at it. */
const READABLE_ZOOM = 0.6;

export interface FitRequest {
  /** Candidate node ids in priority order; the first one on screen wins. */
  ids: string[];
  /** Changes on every request so the same ids can be re-fitted. */
  nonce: number;
  /** The request also changed what's visible (expand/search), so it must
   * wait for the NEXT layout -- fitting the old one would frame stale boxes. */
  afterRelayout: boolean;
}

type Box = { x: number; y: number; w: number; h: number };

/** Which side of each box an edge leaves / enters, chosen so lines run
 * through gutters rather than across other boxes (GitDiagram-style):
 * - two boxes stacked in the same container: straight down/up when they're
 *   neighbours, otherwise a bracket along the right-hand gutter;
 * - a box INSIDE a container talking to anything outside it: through its
 *   side facing the other end, so the line never cuts through its stack;
 * - two top-level boxes: facing sides within a row, bottom-to-top across rows. */
function pickHandles(
  graph: VisibleGraph,
  absolute: Map<string, Box>,
  sourceId: string,
  targetId: string,
): [string, string] {
  const a = absolute.get(sourceId) as Box;
  const b = absolute.get(targetId) as Box;
  const s = graph.byId.get(sourceId);
  const t = graph.byId.get(targetId);
  const ax = a.x + a.w / 2;
  const bx = b.x + b.w / 2;
  if (s?.parentId && s.parentId === t?.parentId) {
    const top = Math.min(a.y + a.h, b.y + b.h);
    const bottom = Math.max(a.y, b.y);
    const between = graph.nodes.some((n) => {
      if (n.parentId !== s.parentId || n.id === s.id || n.id === t.id) return false;
      const box = absolute.get(n.id);
      return Boolean(box) && box!.y >= top - 1 && box!.y + box!.h <= bottom + 1;
    });
    if (!between && Math.abs(ax - bx) < 4) return a.y < b.y ? ["b", "t"] : ["t", "b"];
    return ["r", "r"];
  }
  const facing = (fromX: number, toX: number) => (toX >= fromX ? "r" : "l");
  const sourceSide = s?.parentId ? facing(ax, bx) : null;
  const targetSide = t?.parentId ? facing(bx, ax) : null;
  if (sourceSide || targetSide) {
    const vertical = a.y < b.y ? ["b", "t"] : ["t", "b"];
    return [sourceSide ?? vertical[0], targetSide ?? vertical[1]];
  }
  const sameRow = a.y < b.y + b.h && b.y < a.y + a.h;
  if (sameRow) return ax <= bx ? ["r", "l"] : ["l", "r"];
  return a.y < b.y ? ["b", "t"] : ["t", "b"];
}

function buildFlow(
  data: DiagramResponse,
  graph: VisibleGraph,
  edges: VisibleEdge[],
  layout: Awaited<ReturnType<typeof layoutDiagram>>,
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const labelOf = new Map(data.layers.map((l) => [l.index, l]));
  for (const band of layout.bands) {
    const layer = labelOf.get(band.index);
    nodes.push({
      id: `band:${band.index}`,
      type: "mapBand",
      position: { x: band.x, y: band.y },
      data: { index: band.index, label: layer?.label ?? "", kind: layer?.kind ?? "connected" },
      width: band.width,
      height: band.height,
      style: { width: band.width, height: band.height },
      zIndex: -1,
      selectable: false,
      draggable: false,
      focusable: false,
      connectable: false,
    });
  }
  // computeVisible emits parents before children -- React Flow requires it.
  for (const vnode of graph.nodes) {
    const box = layout.nodes.get(vnode.id);
    if (!box) continue;
    const node: Node<DiagramNodeData> = {
      id: vnode.id,
      type: NODE_TYPE_FOR_KIND[vnode.kind],
      position: { x: box.x, y: box.y },
      data: { vnode },
      width: box.width,
      height: box.height,
      style: { width: box.width, height: box.height },
      draggable: false,
      connectable: false,
      zIndex: vnode.depth,
      ariaLabel: `${vnode.kind} ${vnode.label}`,
    };
    if (vnode.parentId) {
      node.parentId = vnode.parentId;
      node.extent = "parent";
    }
    nodes.push(node);
  }
  // Absolute boxes (children are stored relative to their parent).
  const absolute = new Map<string, Box>();
  for (const vnode of graph.nodes) {
    const box = layout.nodes.get(vnode.id);
    if (!box) continue;
    const parent = vnode.parentId ? absolute.get(vnode.parentId) : undefined;
    absolute.set(vnode.id, {
      x: box.x + (parent?.x ?? 0),
      y: box.y + (parent?.y ?? 0),
      w: box.width,
      h: box.height,
    });
  }

  const flowEdges: Edge<DiagramEdgeData>[] = edges
    .filter((e) => absolute.has(e.source) && absolute.has(e.target))
    .map((e) => {
      const [sourceHandle, targetHandle] = pickHandles(graph, absolute, e.source, e.target);
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle,
        targetHandle,
        type: "diagram",
        data: { vedge: e },
        zIndex: 1000,
      };
    });
  return { nodes, edges: flowEdges };
}

export function MapCanvas({
  data,
  graph,
  edges,
  fitRequest,
  onNodesReady,
  overlay,
}: {
  data: DiagramResponse;
  graph: VisibleGraph;
  edges: VisibleEdge[];
  fitRequest: FitRequest | null;
  onNodesReady: (nodes: Node[]) => void;
  overlay?: ReactNode;
}) {
  const { theme } = useTheme();
  const reducedMotion = usePrefersReducedMotion();
  const ctx = useMapContext();
  const { fitView, setViewport } = useReactFlow();
  const store = useStoreApi();
  const [flow, setFlow] = useState<{ nodes: Node[]; edges: Edge[] } | null>(null);
  const firstFitDone = useRef(false);
  const flowVersion = useRef(0);
  const pendingFit = useRef<{ request: FitRequest; version: number } | null>(null);

  useEffect(() => {
    let cancelled = false;
    void layoutDiagram(graph, edges).then((layout) => {
      if (cancelled) return;
      const next = buildFlow(data, graph, edges, layout);
      flowVersion.current += 1;
      setFlow(next);
      onNodesReady(next.nodes);
    });
    return () => {
      cancelled = true;
    };
  }, [data, graph, edges, onNodesReady]);

  useEffect(() => {
    if (fitRequest) pendingFit.current = { request: fitRequest, version: flowVersion.current };
  }, [fitRequest]);

  // Fit once the laid-out nodes are actually in the store: the whole map on
  // first layout, or the requested nodes after an expand/search/focus.
  useEffect(() => {
    if (!flow) return;
    const duration = reducedMotion ? 0 : 300;
    const frame = requestAnimationFrame(() => {
      if (!firstFitDone.current) {
        firstFitDone.current = true;
        // Fit the whole map when it's still legible that way; otherwise open
        // at a readable zoom aligned to the TOP band (GitDiagram-style: start
        // readable and scroll down, rather than start as a thumbnail).
        const { width, height } = store.getState();
        const bounds = getNodesBounds(flow.nodes);
        const fitZoom = Math.min(width / (bounds.width * 1.1), height / (bounds.height * 1.1));
        if (fitZoom >= READABLE_ZOOM || !width || !bounds.width) {
          void fitView({ padding: 0.08, duration: 0, maxZoom: 1 });
        } else {
          const zoom = Math.max(fitZoom, Math.min(READABLE_ZOOM, width / (bounds.width + 80)));
          void setViewport({
            x: (width - bounds.width * zoom) / 2 - bounds.x * zoom,
            y: 24 - bounds.y * zoom,
            zoom,
          });
        }
        return;
      }
      const pending = pendingFit.current;
      if (!pending) return;
      if (pending.request.afterRelayout && flowVersion.current <= pending.version) return;
      // ids are in priority order -- fit the first one actually on screen
      // (a searched file may sit behind its folder's "+N more" chip).
      const target = pending.request.ids.find((id) => flow.nodes.some((n) => n.id === id));
      if (!target) return;
      pendingFit.current = null;
      void fitView({ nodes: [{ id: target }], padding: 0.3, duration, maxZoom: 1.2 });
    });
    return () => cancelAnimationFrame(frame);
  }, [flow, fitRequest, fitView, setViewport, store, reducedMotion]);

  if (!flow) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-8">
        <Skeleton className="h-24 w-64" />
        <Skeleton className="h-24 w-96" />
        <p className="text-xs text-text-muted">{MAP_COPY.layingOut}</p>
      </div>
    );
  }

  return (
    <ReactFlow
      nodes={flow.nodes}
      edges={flow.edges}
      nodeTypes={mapNodeTypes}
      edgeTypes={mapEdgeTypes}
      colorMode={theme}
      connectionMode={ConnectionMode.Loose}
      minZoom={0.1}
      maxZoom={2}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable
      nodesFocusable
      edgesFocusable
      onlyRenderVisibleElements
      proOptions={{ hideAttribution: true }}
      onNodeClick={(_, node) => {
        if (!node.id.startsWith("band:")) ctx.onSelect(node.id);
      }}
      onEdgeClick={(_, edge) => ctx.onSelect(edge.id)}
      onPaneClick={() => ctx.onSelect("")}
    >
      <Background
        variant={BackgroundVariant.Dots}
        gap={28}
        size={1}
        color="color-mix(in oklab, var(--color-border) 70%, transparent)"
      />
      <Controls showInteractive={false} position="bottom-left" />
      <MiniMap
        pannable
        zoomable
        position="bottom-right"
        className="!hidden sm:!block"
        nodeColor={(node) => {
          const vnode = (node.data as Partial<DiagramNodeData>).vnode;
          if (!vnode) return "transparent";
          return resolvedGroupColor(data, vnode.groupId);
        }}
        maskColor="var(--color-overlay)"
      />
      {overlay}
    </ReactFlow>
  );
}
