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

const LABEL_ZOOM = 0.8;

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
    borderRadius: 12,
  });

  const dimmed = ctx.emphasis !== null && !ctx.emphasis.has(id);
  const highlighted = ctx.emphasis !== null && ctx.emphasis.has(id);
  const selected = ctx.selectedId === id;

  let stroke = "var(--color-border-strong)";
  if (e.kind === "hidden") stroke = "var(--color-warning)";
  if (e.kind === "actor" || e.kind === "runs") stroke = "var(--color-accent)";
  if (e.inCycle) stroke = "var(--color-danger)";
  if (highlighted || selected) stroke = e.inCycle ? "var(--color-danger)" : "var(--color-accent)";

  const baseWidth = e.kind === "import" ? 1 + Math.min(4, Math.log2(Math.max(1, e.count))) : 1.25;
  const width = baseWidth + (highlighted || selected ? 1.5 : 0);
  const directed = e.kind !== "hidden";
  const markerId = `cp-map-arrow-${id.replace(/[^a-zA-Z0-9_-]/g, "_")}`;
  const verb = edgeVerb(e, ctx.aiOn, ctx.aiVerbs);

  let label: string | null = null;
  if (e.kind === "import") label = verb ? `${verb} · ${e.count}` : String(e.count);
  else if (e.kind === "hidden") label = `co-change ${Math.round((e.maxDegree ?? 0) * 100)}%`;
  else if (e.kind === "actor") label = "enters";
  else if (e.kind === "runs") label = "runs";
  const showLabel = label !== null && (showLabelsByZoom || selected || highlighted);

  return (
    <g style={{ opacity: dimmed ? 0.12 : 1, transition: "opacity 200ms" }}>
      {directed ? (
        <defs>
          <marker
            id={markerId}
            viewBox="0 0 10 10"
            refX="8"
            refY="5"
            markerWidth="6"
            markerHeight="6"
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
        className={e.kind === "hidden" ? "cp-map-edge-flow-hidden" : undefined}
        style={{ stroke, strokeWidth: width }}
        interactionWidth={14}
      />
      {directed ? (
        <path
          d={path}
          fill="none"
          className="cp-map-edge-flow pointer-events-none"
          style={{
            stroke: e.inCycle ? stroke : "var(--color-accent)",
            strokeWidth: width,
            opacity: 0.55,
          }}
        />
      ) : null}
      {showLabel ? (
        <EdgeLabelRenderer>
          <button
            type="button"
            className="nodrag nopan absolute rounded-xs border border-border bg-bg-elevated px-1.5 py-0.5 font-mono text-2xs text-text-muted hover:border-accent"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              pointerEvents: "all",
              opacity: dimmed ? 0.2 : 1,
            }}
            onClick={() => ctx.onSelect(id)}
            aria-label={`Show evidence for ${label}`}
          >
            {verb ? (
              <>
                <em className="not-italic text-text">{verb}</em>
                <span className="ml-1 text-info" aria-label="AI-written">
                  {MAP_COPY.aiChip}
                </span>
                <span> · {e.count}</span>
              </>
            ) : (
              label
            )}
          </button>
        </EdgeLabelRenderer>
      ) : null}
    </g>
  );
}
