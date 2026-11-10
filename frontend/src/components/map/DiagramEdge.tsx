import {
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  useStore,
  type Edge,
  type EdgeProps,
} from "@xyflow/react";
import { MAP_COPY } from "../../content/map";
import { edgeVerb } from "../../lib/diagram/display";
import type { VisibleEdge } from "../../lib/diagram/visible";
import { useMapContext } from "./mapContext";

export type DiagramEdgeData = { vedge: VisibleEdge };
type DiagramRFEdge = Edge<DiagramEdgeData>;

/** Labels show from this zoom up (and always on a selected/emphasised edge). */
const LABEL_ZOOM = 0.5;

function baseVerb(e: VisibleEdge): string {
  switch (e.kind) {
    case "import":
      return "imports";
    case "hidden":
      return "co-changes";
    case "actor":
      return "enters";
    case "runs":
      return "runs";
  }
}

function detail(e: VisibleEdge): string | null {
  if (e.kind === "import") return String(e.count);
  if (e.kind === "hidden") return `${Math.round((e.maxDegree ?? 0) * 100)}%`;
  return null;
}

/** GitDiagram-style connection: a hairline orthogonal line, a small
 * arrowhead, and a short verb sitting on the line. Imports are solid (with
 * a slow marching dash while Motion is on), co-change links dotted amber,
 * cycle links rose. */
export function DiagramEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
}: EdgeProps<DiagramRFEdge>) {
  const ctx = useMapContext();
  const showLabelsByZoom = useStore((s) => s.transform[2] >= LABEL_ZOOM);
  if (!data) return null;
  const e = data.vedge;

  const [path, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    borderRadius: 8,
    offset: 18,
  });

  const emphasised = ctx.emphasis !== null && ctx.emphasis.has(id);
  const dimmed = ctx.emphasis !== null && !emphasised;
  const selected = ctx.selectedId === id;
  const strong = emphasised || selected;

  let stroke = "var(--map-edge)";
  if (e.kind === "hidden") stroke = "var(--color-warning)";
  if (e.inCycle) stroke = "var(--color-danger)";
  if (strong && !e.inCycle) stroke = "var(--color-accent)";

  const width =
    (e.kind === "import" ? 1 + Math.min(1.25, Math.log10(Math.max(1, e.count))) : 1) +
    (strong ? 1 : 0);
  const directed = e.kind !== "hidden";
  const markerId = `cp-map-arrow-${id.replace(/[^a-zA-Z0-9_-]/g, "_")}`;
  const verb = edgeVerb(e, ctx.aiOn, ctx.aiVerbs);
  const showLabel = showLabelsByZoom || strong;
  const flowClass =
    e.kind === "hidden"
      ? "cp-map-edge-dotted"
      : e.kind === "import"
        ? "cp-map-edge-flow"
        : "cp-map-edge-flow-slow";

  return (
    <g style={{ opacity: dimmed ? 0.1 : 1, transition: "opacity 200ms" }}>
      {directed ? (
        <defs>
          <marker
            id={markerId}
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            markerUnits="userSpaceOnUse"
            orient="auto-start-reverse"
          >
            <path d="M0,0 L10,5 L0,10 z" fill={stroke} />
          </marker>
        </defs>
      ) : null}
      <BaseEdge
        id={id}
        path={path}
        markerEnd={directed ? `url(#${markerId})` : undefined}
        className={flowClass}
        style={{ stroke, strokeWidth: width, strokeLinecap: "round" }}
        interactionWidth={16}
      />
      {showLabel ? (
        <EdgeLabelRenderer>
          <button
            type="button"
            className="nodrag nopan absolute rounded-[3px] px-1.5 py-px text-[11px] leading-4 whitespace-nowrap transition-colors hover:text-accent"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              pointerEvents: "all",
              background: "var(--map-label-bg)",
              color: e.inCycle ? "var(--color-danger)" : "var(--map-label-text)",
              opacity: dimmed ? 0.15 : 1,
            }}
            onClick={() => ctx.onSelect(id)}
            aria-label={`Show evidence: ${verb ?? baseVerb(e)}${detail(e) ? ` ${detail(e)}` : ""}`}
          >
            {verb ? (
              <>
                <span>{verb}</span>
                <span className="ml-1 text-[9px] font-semibold text-info" aria-label="AI-written">
                  {MAP_COPY.aiChip}
                </span>
              </>
            ) : (
              <span>{baseVerb(e)}</span>
            )}
            {detail(e) ? (
              <span className="ml-1 font-mono text-[10px] opacity-60">{detail(e)}</span>
            ) : null}
          </button>
        </EdgeLabelRenderer>
      ) : null}
    </g>
  );
}
