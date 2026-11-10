import { useNavigate, Link } from "react-router-dom";
import { useDiagram } from "../../api/hooks";
import type { DiagramResponse } from "../../api/types";
import { groupColor, withShare } from "../../lib/diagram/display";
import { Card } from "../ui/Card";

const VIEW_WIDTH = 600;
const ROW_HEIGHT = 56;
const BOX_HEIGHT = 26;
const MAX_EDGES = 12;

function truncate(label: string): string {
  return label.length > 14 ? `${label.slice(0, 13)}…` : label;
}

/** Overview's "Architecture at a glance" -- a tiny hand-drawn SVG of the
 * Map's top-level groups by band. Deliberately does NOT import React Flow
 * or ELK, so the Overview bundle stays light; it renders nothing at all
 * while the diagram is pending, errored or archived (never blocks Overview). */
export function MiniMapPreview({ repoId, share }: { repoId: string; share?: string }) {
  const diagram = useDiagram(repoId, "subsystem", share);
  const navigate = useNavigate();
  if (diagram.data?.kind !== "data") return null;
  const data = diagram.data.data;
  if (data.facts_archived || data.groups.length === 0) return null;

  const mapHref = withShare(`/repos/${repoId}/map`, share);
  return (
    <Card
      title="Architecture at a glance"
      eyebrow={`${data.groups.length} groups · ${data.stats.import_edge_count.toLocaleString()} import links · ${data.hidden_group_edges.length} hidden links`}
      action={
        <Link to={mapHref} className="text-xs text-accent hover:underline">
          Open the map →
        </Link>
      }
    >
      <button
        type="button"
        onClick={() => navigate(mapHref)}
        className="block w-full cursor-pointer text-left"
        aria-label="Open the map"
      >
        <MiniMapSvg data={data} />
      </button>
      <p className="sr-only">
        {data.groups.length} groups in {data.layers.length} bands:{" "}
        {data.groups.map((g) => g.label).join(", ")}.
      </p>
    </Card>
  );
}

function MiniMapSvg({ data }: { data: DiagramResponse }) {
  const bands = data.layers.filter((l) => l.kind !== "actor" && l.kind !== "infra");
  const positions = new Map<string, { x: number; y: number; w: number }>();
  bands.forEach((band, row) => {
    const n = band.group_ids.length;
    const slot = VIEW_WIDTH / Math.max(1, n);
    const w = Math.min(120, slot - 12);
    band.group_ids.forEach((gid, k) => {
      positions.set(gid, { x: slot * k + (slot - w) / 2, y: row * ROW_HEIGHT + 14, w });
    });
  });
  const height = Math.max(ROW_HEIGHT, bands.length * ROW_HEIGHT);
  const edges = [...data.group_edges]
    .sort((a, b) => b.import_count - a.import_count)
    .slice(0, MAX_EDGES);
  const labelOf = new Map(data.groups.map((g) => [g.id, g.label]));

  return (
    <svg viewBox={`0 0 ${VIEW_WIDTH} ${height}`} className="w-full" aria-hidden="true">
      {edges.map((e) => {
        const a = positions.get(e.source);
        const b = positions.get(e.target);
        if (!a || !b) return null;
        const ax = a.x + a.w / 2;
        const bx = b.x + b.w / 2;
        // Same band: a shallow arc under the row, so it never crosses labels;
        // otherwise bottom-centre of one box to the top-centre of the other
        // (upward for an import that points back up the bands).
        const d =
          a.y === b.y
            ? `M ${ax} ${a.y + BOX_HEIGHT} Q ${(ax + bx) / 2} ${a.y + BOX_HEIGHT + 16} ${bx} ${b.y + BOX_HEIGHT}`
            : a.y < b.y
              ? `M ${ax} ${a.y + BOX_HEIGHT} L ${bx} ${b.y}`
              : `M ${ax} ${a.y} L ${bx} ${b.y + BOX_HEIGHT}`;
        return (
          <path
            key={`${e.source}-${e.target}`}
            d={d}
            fill="none"
            stroke={
              e.in_group_cycle || e.in_file_cycle
                ? "var(--color-danger)"
                : "var(--color-border-strong)"
            }
            strokeWidth={1}
          />
        );
      })}
      {[...positions.entries()].map(([gid, p]) => {
        const color = groupColor(data, gid);
        return (
          <g key={gid}>
            <rect
              x={p.x}
              y={p.y}
              width={p.w}
              height={BOX_HEIGHT}
              rx={4}
              fill={`color-mix(in oklab, ${color} 22%, transparent)`}
              stroke={color}
            />
            <text
              x={p.x + p.w / 2}
              y={p.y + BOX_HEIGHT / 2 + 3}
              textAnchor="middle"
              fontFamily="var(--font-mono)"
              fontSize="9"
              fill="var(--color-text)"
            >
              {truncate(labelOf.get(gid) ?? gid)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
