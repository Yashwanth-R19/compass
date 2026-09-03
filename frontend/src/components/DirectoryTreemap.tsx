import { useMemo, useState } from "react";
import type { CityBounds, CityResponse } from "../api/types";
import { toCityFiles, type CityFile } from "../lib/cityFile";
import { average, majority, ownerColor, recencyColor, riskColor } from "../lib/metricColor";
import { colorForSubsystem, UNASSIGNED_COLOR } from "../lib/subsystemColors";
import { layoutTreemap, type TreemapNode } from "../lib/treemapLayout";
import { Card } from "./ui/Card";
import { Alert } from "./ui/Alert";
import { ColorModeLegend } from "./ColorModeLegend";
import { EmptyState } from "./EmptyState";
import { GraphCanvas } from "./GraphCanvas";
import { ModeSelect } from "./ModeSelect";
import { TOOLTIPS } from "../content/explainability";

export type TreemapColorMode = "subsystem" | "risk" | "owner" | "recency";

export const TREEMAP_COLOR_MODE_LABEL: Record<TreemapColorMode, string> = {
  subsystem: "Subsystem",
  risk: "Risk",
  owner: "Principal author",
  recency: "Recency",
};

const TREEMAP_COLOR_MODE_TOOLTIP: Record<TreemapColorMode, string> = {
  subsystem: TOOLTIPS.subsystem,
  risk: TOOLTIPS.riskScore,
  owner: TOOLTIPS.principalAuthor,
  recency: TOOLTIPS.recency,
};

interface TreemapChild {
  id: string;
  name: string;
  isDirectory: boolean;
  loc: number;
  fileCount: number;
  subsystemIds: (number | null)[];
  riskScores: number[];
  ownerIds: (number | null)[];
  lastModified: number[];
}

function childrenAt(files: CityFile[], dirPrefix: string): TreemapChild[] {
  const prefix = dirPrefix === "" ? "" : `${dirPrefix}/`;
  const buckets = new Map<string, TreemapChild>();
  for (const f of files) {
    if (prefix !== "" && !f.path.startsWith(prefix)) continue;
    const rest = prefix === "" ? f.path : f.path.slice(prefix.length);
    const slashIdx = rest.indexOf("/");
    const isDirectory = slashIdx !== -1;
    const name = isDirectory ? rest.slice(0, slashIdx) : rest;
    const id = isDirectory ? prefix + name : f.path;
    let bucket = buckets.get(id);
    if (!bucket) {
      bucket = {
        id,
        name,
        isDirectory,
        loc: 0,
        fileCount: 0,
        subsystemIds: [],
        riskScores: [],
        ownerIds: [],
        lastModified: [],
      };
      buckets.set(id, bucket);
    }
    bucket.loc += f.loc;
    bucket.fileCount += 1;
    bucket.subsystemIds.push(f.subsystemId);
    if (f.riskScore != null) bucket.riskScores.push(f.riskScore);
    bucket.ownerIds.push(f.principalExpertId);
    bucket.lastModified.push(f.lastModifiedAt);
  }
  return [...buckets.values()];
}

function treemapChildColor(
  child: TreemapChild,
  colorMode: TreemapColorMode,
  labelById: Map<number, string>,
  bounds: CityBounds,
): string {
  if (colorMode === "subsystem") {
    const id = majority(child.subsystemIds);
    return id == null ? UNASSIGNED_COLOR : colorForSubsystem(labelById.get(id) ?? id);
  }
  if (colorMode === "risk") {
    return riskColor(average(child.riskScores));
  }
  if (colorMode === "owner") {
    return ownerColor(majority(child.ownerIds));
  }
  const avg = average(child.lastModified);
  return recencyColor(avg, bounds.last_modified_at.min, bounds.last_modified_at.max);
}

function Breadcrumb({
  currentDir,
  onNavigate,
}: {
  currentDir: string;
  onNavigate: (dir: string) => void;
}) {
  const segments = currentDir === "" ? [] : currentDir.split("/");
  return (
    <nav className="mb-2 flex flex-wrap items-center gap-1 font-mono text-xs text-text-muted">
      <button type="button" onClick={() => onNavigate("")} className="hover:underline">
        root
      </button>
      {segments.map((seg, i) => {
        const path = segments.slice(0, i + 1).join("/");
        return (
          <span key={path} className="flex items-center gap-1">
            <span className="text-text-muted/60">/</span>
            <button type="button" onClick={() => onNavigate(path)} className="hover:underline">
              {seg}
            </button>
          </span>
        );
      })}
    </nav>
  );
}

/** The directory-hierarchy treemap (session 09, Part C.2) -- rectangle area
 * is LOC, colour is selectable, clicking a directory drills in, a
 * breadcrumb walks back out. Reused verbatim as the WebGL-unavailable
 * fallback for the 3D city (Part F: "render the Part C treemap instead
 * with a clear explanation"), so this lives here rather than inside
 * MapPage.tsx. */
export function DirectoryTreemap({
  city,
  fallbackNotice,
}: {
  city: CityResponse;
  fallbackNotice?: string;
}) {
  const [currentDir, setCurrentDir] = useState("");
  const [colorMode, setColorMode] = useState<TreemapColorMode>("subsystem");

  const files = useMemo(() => toCityFiles(city), [city]);
  const labelById = useMemo(() => new Map(city.subsystems.map((s) => [s.id, s.label])), [city]);
  const children = useMemo(() => childrenAt(files, currentDir), [files, currentDir]);

  return (
    <Card>
      {fallbackNotice ? (
        <Alert variant="info" className="mb-3">
          {fallbackNotice}
        </Alert>
      ) : null}
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <Breadcrumb currentDir={currentDir} onNavigate={setCurrentDir} />
        <ModeSelect
          label="Colour by"
          tooltip={TREEMAP_COLOR_MODE_TOOLTIP[colorMode]}
          value={colorMode}
          onChange={setColorMode}
          options={TREEMAP_COLOR_MODE_LABEL}
        />
      </div>
      {children.length === 0 ? (
        <EmptyState title="Empty directory" message="No files under this path." />
      ) : (
        <GraphCanvas height={520}>
          {({ width, height }) => {
            const treemapNodes: TreemapNode[] = children.map((c) => ({
              id: c.id,
              value: Math.max(c.loc, 1),
            }));
            const rects = layoutTreemap(treemapNodes, width, height, { minSize: 6, padding: 2 });
            const byId = new Map(children.map((c) => [c.id, c]));
            return (
              <svg width={width} height={height} role="img" aria-label="Directory treemap">
                {rects.map((r) => {
                  const child = byId.get(r.id);
                  if (!child) return null;
                  const color = treemapChildColor(child, colorMode, labelById, city.bounds);
                  return (
                    <g
                      key={r.id}
                      onClick={() => (child.isDirectory ? setCurrentDir(child.id) : undefined)}
                      style={{ cursor: child.isDirectory ? "pointer" : "default" }}
                    >
                      <rect
                        x={r.x}
                        y={r.y}
                        width={r.width}
                        height={r.height}
                        fill={color}
                        stroke="rgba(255,255,255,0.5)"
                        strokeWidth={1}
                      />
                      {r.width > 40 && r.height > 16 ? (
                        <text
                          x={r.x + 4}
                          y={r.y + 14}
                          fontSize={11}
                          fill="#fff"
                          pointerEvents="none"
                        >
                          {child.name}
                          {child.isDirectory ? "/" : ""}
                        </text>
                      ) : null}
                      <title>
                        {`${child.id} — ${child.loc.toLocaleString()} LOC${child.isDirectory ? ` (${child.fileCount} files)` : ""}`}
                      </title>
                    </g>
                  );
                })}
              </svg>
            );
          }}
        </GraphCanvas>
      )}
      <div className="mt-3 border-t border-border pt-3">
        <ColorModeLegend mode={colorMode} subsystemLabels={city.subsystems.map((s) => s.label)} />
      </div>
    </Card>
  );
}
