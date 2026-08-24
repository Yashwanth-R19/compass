import { layoutTreemap, type TreemapNode } from "./treemapLayout";

export type CityHeightMetric = "complexity" | "churn" | "commits";

export interface CityLayoutFile {
  path: string;
  subsystemId: number | null;
  loc: number;
  complexity: number;
  churnWeighted: number;
  commitCount: number;
}

export interface CityLayoutSubsystem {
  id: number;
  label: string;
  totalLoc: number;
}

export interface CityLayoutInput {
  subsystems: CityLayoutSubsystem[];
  files: CityLayoutFile[];
}

export interface District {
  id: number;
  label: string;
  x: number;
  z: number;
  width: number;
  depth: number;
  totalLoc: number;
}

export interface Building {
  path: string;
  districtId: number;
  x: number;
  z: number;
  width: number;
  depth: number;
  height: number;
  loc: number;
  complexity: number;
}

/** The flat plate a district renders in place of every file beyond
 * MAX_CITY_BUILDINGS (Part F: "render the remainder as a flat 'outskirts'
 * plate per district"). Occupies the tail portion of the district's own
 * footprint, sized proportionally to how much LOC it represents. */
export interface OutskirtsPlate {
  districtId: number;
  label: string;
  fileCount: number;
  totalLoc: number;
  x: number;
  z: number;
  width: number;
  depth: number;
}

export interface CityLayoutResult {
  districts: District[];
  buildings: Building[];
  outskirts: OutskirtsPlate[];
  /** True whenever MAX_CITY_BUILDINGS actually engaged -- the caller must
   * surface this via PartialResultNotice (Known Hazard: "never silently
   * drop"). */
  capped: boolean;
  totalFiles: number;
  buildingsShown: number;
}

export interface CityLayoutOptions {
  width?: number;
  depth?: number;
  /** Gap between districts, in world units -- what makes the ground plane
   * read as separate neighbourhoods rather than one undifferentiated slab
   * (Part F: "Street gaps between districts"). */
  streetGap?: number;
  /** Gap between individual buildings within a district. */
  buildingGap?: number;
  minFootprint?: number;
  heightMetric?: CityHeightMetric;
  minHeight?: number;
  maxHeight?: number;
}

const DEFAULT_WIDTH = 400;
const DEFAULT_DEPTH = 400;
const DEFAULT_STREET_GAP = 6;
const DEFAULT_BUILDING_GAP = 0.4;
const DEFAULT_MIN_FOOTPRINT = 1.2;
const DEFAULT_MIN_HEIGHT = 0.5;
const DEFAULT_MAX_HEIGHT = 40;

/** The hard cap on individually-rendered buildings (Part F). Chosen to keep
 * one InstancedMesh per district comfortably within what a mid-range GPU
 * renders at interactive framerates; a repo under RULES.md sec 14's own
 * 8,000-file submission ceiling can still exceed it, hence the outskirts
 * fallback rather than a silent truncation. */
export const MAX_CITY_BUILDINGS = 5000;

function heightMetricValue(file: CityLayoutFile, metric: CityHeightMetric): number {
  if (metric === "churn") return Math.max(file.churnWeighted, 0);
  if (metric === "commits") return Math.max(file.commitCount, 0);
  return Math.max(file.complexity, 0);
}

const UNASSIGNED_DISTRICT_ID = -1;
const UNASSIGNED_DISTRICT_LABEL = "Unassigned";

/**
 * Deterministic city layout (session 09, Part F) -- districts (subsystems)
 * over a ground plane, buildings (files) nested inside their district via a
 * second `layoutTreemap` call. "Reusing layoutTreemap" (Part F's own
 * instruction) means literally this: one call for the district partition,
 * then one further call per district for its own buildings, exactly the
 * "call it once per level" pattern `treemapLayout.ts`'s own docstring
 * describes.
 *
 * Pure: no React, no DOM, no `Math.random()` -- every list this function
 * touches is sorted before being handed to `layoutTreemap` (which sorts
 * again internally, but the SELECTION of which files are "kept" vs.
 * "outskirts" below must itself be deterministic, hence the sort here
 * too), so the same input produces a deep-equal result on every call.
 */
export function layoutCity(data: CityLayoutInput, opts: CityLayoutOptions = {}): CityLayoutResult {
  const width = opts.width ?? DEFAULT_WIDTH;
  const depth = opts.depth ?? DEFAULT_DEPTH;
  const streetGap = opts.streetGap ?? DEFAULT_STREET_GAP;
  const buildingGap = opts.buildingGap ?? DEFAULT_BUILDING_GAP;
  const minFootprint = opts.minFootprint ?? DEFAULT_MIN_FOOTPRINT;
  const heightMetric = opts.heightMetric ?? "complexity";
  const minHeight = opts.minHeight ?? DEFAULT_MIN_HEIGHT;
  const maxHeight = opts.maxHeight ?? DEFAULT_MAX_HEIGHT;

  const filesByDistrict = new Map<number, CityLayoutFile[]>();
  for (const file of data.files) {
    const districtId = file.subsystemId ?? UNASSIGNED_DISTRICT_ID;
    const bucket = filesByDistrict.get(districtId);
    if (bucket) bucket.push(file);
    else filesByDistrict.set(districtId, [file]);
  }

  const districtMeta = new Map<number, { label: string; totalLoc: number }>();
  for (const s of data.subsystems) {
    districtMeta.set(s.id, { label: s.label, totalLoc: s.totalLoc });
  }
  if (filesByDistrict.has(UNASSIGNED_DISTRICT_ID) && !districtMeta.has(UNASSIGNED_DISTRICT_ID)) {
    const unassignedFiles = filesByDistrict.get(UNASSIGNED_DISTRICT_ID) ?? [];
    districtMeta.set(UNASSIGNED_DISTRICT_ID, {
      label: UNASSIGNED_DISTRICT_LABEL,
      totalLoc: unassignedFiles.reduce((sum, f) => sum + Math.max(f.loc, 0), 0),
    });
  }

  // Global top-N-by-LOC selection (Part F: "keep the largest by LOC"),
  // sorted deterministically (value desc, path asc tiebreak -- same
  // convention treemapLayout.ts itself uses).
  const sortedFiles = [...data.files].sort((a, b) => b.loc - a.loc || a.path.localeCompare(b.path));
  const capped = sortedFiles.length > MAX_CITY_BUILDINGS;
  const keptPaths = new Set(sortedFiles.slice(0, MAX_CITY_BUILDINGS).map((f) => f.path));

  const districtIds = [...districtMeta.keys()].sort((a, b) => a - b);
  const districtTreemapNodes: TreemapNode[] = districtIds.map((id) => ({
    id: String(id),
    value: Math.max(districtMeta.get(id)!.totalLoc, 1),
  }));

  const districtRects = layoutTreemap(districtTreemapNodes, width, depth, {
    padding: streetGap,
    minSize: minFootprint * 4,
  });
  const districtRectById = new Map(districtRects.map((r) => [Number(r.id), r]));

  const districts: District[] = districtIds.map((id) => {
    const rect = districtRectById.get(id)!;
    return {
      id,
      label: districtMeta.get(id)!.label,
      x: rect.x,
      z: rect.y,
      width: rect.width,
      depth: rect.height,
      totalLoc: districtMeta.get(id)!.totalLoc,
    };
  });

  // Height normalization is computed over every KEPT file city-wide (not
  // per-district) so a building's height means the same thing regardless
  // of which district it's in -- a complexity-10 file looks equally tall
  // whether its neighbours are simple or complex.
  const allKeptFiles = sortedFiles.filter((f) => keptPaths.has(f.path));
  const maxMetric = Math.max(1e-9, ...allKeptFiles.map((f) => heightMetricValue(f, heightMetric)));

  const buildings: Building[] = [];
  const outskirts: OutskirtsPlate[] = [];

  for (const district of districts) {
    const districtFiles = (filesByDistrict.get(district.id) ?? [])
      .slice()
      .sort((a, b) => b.loc - a.loc || a.path.localeCompare(b.path));
    const kept = districtFiles.filter((f) => keptPaths.has(f.path));
    const overflow = districtFiles.filter((f) => !keptPaths.has(f.path));

    // Reserve a slice of the district's own footprint for the outskirts
    // plate, proportional to how much LOC the overflow represents --
    // computed via the SAME layoutTreemap call as the buildings (one
    // extra synthetic node), so the plate and the buildings never overlap
    // (Part G: "no two buildings overlap" -- the plate counts as an
    // occupant of the district's footprint too).
    const buildingNodes: TreemapNode[] = kept.map((f) => ({
      id: f.path,
      value: Math.max(f.loc, 1),
    }));
    const overflowLoc = overflow.reduce((sum, f) => sum + Math.max(f.loc, 0), 0);
    const OUTSKIRTS_NODE_ID = "__outskirts__";
    if (overflow.length > 0) {
      buildingNodes.push({ id: OUTSKIRTS_NODE_ID, value: Math.max(overflowLoc, 1) });
    }

    const rects = layoutTreemap(buildingNodes, district.width, district.depth, {
      padding: buildingGap,
      minSize: minFootprint,
    });
    const rectById = new Map(rects.map((r) => [r.id, r]));

    for (const f of kept) {
      const rect = rectById.get(f.path);
      if (!rect) continue;
      const t = heightMetricValue(f, heightMetric) / maxMetric;
      buildings.push({
        path: f.path,
        districtId: district.id,
        x: district.x + rect.x,
        z: district.z + rect.y,
        width: rect.width,
        depth: rect.height,
        height: minHeight + t * (maxHeight - minHeight),
        loc: f.loc,
        complexity: f.complexity,
      });
    }

    if (overflow.length > 0) {
      const rect = rectById.get(OUTSKIRTS_NODE_ID);
      if (rect) {
        outskirts.push({
          districtId: district.id,
          label: district.label,
          fileCount: overflow.length,
          totalLoc: overflowLoc,
          x: district.x + rect.x,
          z: district.z + rect.y,
          width: rect.width,
          depth: rect.height,
        });
      }
    }
  }

  return {
    districts,
    buildings,
    outskirts,
    capped,
    totalFiles: data.files.length,
    buildingsShown: buildings.length,
  };
}
