import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import type { CityResponse } from "../api/types";
import {
  citySubsystemLabelById,
  cityContributorNameById,
  toCityFiles,
  type CityFile,
} from "../lib/cityFile";
import {
  layoutCity,
  type Building,
  type CityHeightMetric,
  type District,
  type OutskirtsPlate,
} from "../lib/cityLayout";
import { ownerColor, recencyColor, riskColor } from "../lib/metricColor";
import { colorForSubsystem, UNASSIGNED_COLOR } from "../lib/subsystemColors";
import { Card } from "./Card";
import { DirectoryTreemap } from "./DirectoryTreemap";
import { FileDetailPanel } from "./FileDetailPanel";
import { ModeSelect } from "./ModeSelect";
import { PartialResultNotice } from "./PartialResultNotice";

type CityColorMode = "subsystem" | "risk" | "owner" | "age" | "test";

const COLOR_MODE_LABEL: Record<CityColorMode, string> = {
  subsystem: "Subsystem",
  risk: "Risk",
  owner: "Principal author",
  age: "Age (recency)",
  test: "Test vs source",
};

const HEIGHT_MODE_LABEL: Record<CityHeightMetric, string> = {
  complexity: "Complexity",
  churn: "Churn",
  commits: "Commit count",
};

const TEST_COLOR = "#6366f1"; // indigo-500 -- this app's existing "structural" accent
const SOURCE_COLOR = UNASSIGNED_COLOR;

function detectWebGL(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(
      window.WebGLRenderingContext && (canvas.getContext("webgl2") || canvas.getContext("webgl")),
    );
  } catch {
    return false;
  }
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    const mql = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handler = () => setReduced(mql.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);
  return reduced;
}

function colorForBuilding(
  building: Building,
  file: CityFile | undefined,
  colorMode: CityColorMode,
  labelById: Map<number, string>,
): string {
  if (colorMode === "subsystem") {
    return colorForSubsystem(labelById.get(building.districtId) ?? null);
  }
  if (colorMode === "risk") return riskColor(file?.riskScore ?? null);
  if (colorMode === "owner") return ownerColor(file?.principalExpertId ?? null);
  if (colorMode === "test") return file?.isTest ? TEST_COLOR : SOURCE_COLOR;
  return UNASSIGNED_COLOR; // "age" is handled by the caller (needs bounds)
}

// --- The 3D scene, everything inside <Canvas> --------------------------------

interface HoverInfo {
  building: Building;
  file: CityFile | undefined;
  districtLabel: string;
}

function DistrictBuildings({
  district,
  buildings,
  filesByPath,
  colorMode,
  labelById,
  boundsLastModified,
  onHover,
  onSelect,
}: {
  district: District;
  buildings: Building[];
  filesByPath: Map<string, CityFile>;
  colorMode: CityColorMode;
  labelById: Map<number, string>;
  boundsLastModified: { min: number; max: number };
  onHover: (info: HoverInfo | null) => void;
  onSelect: (building: Building) => void;
}) {
  const meshRef = useRef<THREE.InstancedMesh>(null);

  useEffect(() => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const dummy = new THREE.Object3D();
    const color = new THREE.Color();
    for (let i = 0; i < buildings.length; i++) {
      const b = buildings[i];
      dummy.position.set(b.x + b.width / 2, b.height / 2, b.z + b.depth / 2);
      dummy.scale.set(Math.max(b.width, 0.05), Math.max(b.height, 0.05), Math.max(b.depth, 0.05));
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);

      const file = filesByPath.get(b.path);
      const hex =
        colorMode === "age"
          ? recencyColor(
              file?.lastModifiedAt ?? null,
              boundsLastModified.min,
              boundsLastModified.max,
            )
          : colorForBuilding(b, file, colorMode, labelById);
      color.set(hex);
      mesh.setColorAt(i, color);
    }
    mesh.instanceMatrix.needsUpdate = true;
    // setColorAt lazily allocates instanceColor on first call -- guard for
    // the (impossible-in-practice, buildings.length===0) case where the
    // loop above never ran, per the Known Hazard: forgetting this makes a
    // colour-mode switch appear to do nothing.
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    // THREE's WebGLRenderer decides whether to compile the
    // USE_INSTANCING_COLOR shader variant from `instanceColor !== null` at
    // PROGRAM-COMPILE time. The mesh's first frame renders (via R3F's own
    // mount-time render) before this effect has a chance to call
    // setColorAt, so the program gets cached WITHOUT that define -- adding
    // the color data afterward silently does nothing until something forces
    // a recompile. Confirmed directly: instanceColor was correctly
    // populated with the right values every time, but nothing appeared on
    // screen until this line was added. Cheap (one flag check inside
    // three.js, not a real recompile unless the material's actually dirty).
    const material = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material;
    if (material) material.needsUpdate = true;
  }, [buildings, colorMode, labelById, boundsLastModified, filesByPath]);

  if (buildings.length === 0) return null;

  return (
    <instancedMesh
      key={`${district.id}-${buildings.length}`}
      ref={meshRef}
      args={[undefined, undefined, buildings.length]}
      castShadow
      receiveShadow
      onPointerMove={(e: ThreeEvent<PointerEvent>) => {
        e.stopPropagation();
        if (e.instanceId == null) return;
        const b = buildings[e.instanceId];
        onHover({ building: b, file: filesByPath.get(b.path), districtLabel: district.label });
      }}
      onPointerOut={(e: ThreeEvent<PointerEvent>) => {
        e.stopPropagation();
        onHover(null);
      }}
      onClick={(e: ThreeEvent<MouseEvent>) => {
        e.stopPropagation();
        if (e.instanceId == null) return;
        onSelect(buildings[e.instanceId]);
      }}
    >
      <boxGeometry args={[1, 1, 1]} />
      <meshStandardMaterial />
    </instancedMesh>
  );
}

function OutskirtsPlates({ plates }: { plates: OutskirtsPlate[] }) {
  return (
    <>
      {plates.map((p) => (
        <mesh
          key={p.districtId}
          position={[p.x + p.width / 2, 0.1, p.z + p.depth / 2]}
          receiveShadow
        >
          <boxGeometry args={[Math.max(p.width, 0.05), 0.2, Math.max(p.depth, 0.05)]} />
          <meshStandardMaterial color="#64748b" opacity={0.6} transparent />
        </mesh>
      ))}
    </>
  );
}

const LABEL_HIDE_DISTANCE = 260;

/** Billboarded district labels, hidden once the camera is far enough out
 * that a dozen labels would overlap into noise (Part F). Tracks camera
 * distance itself via useFrame with an internal ref-guarded setState (only
 * fires a re-render on the boolean actually flipping), so this doesn't
 * force the whole scene to re-render every frame. */
function DistrictLabels({ districts, center }: { districts: District[]; center: THREE.Vector3 }) {
  const [visible, setVisible] = useState(true);
  const lastVisible = useRef(true);

  useFrame(({ camera }) => {
    const shouldShow = camera.position.distanceTo(center) < LABEL_HIDE_DISTANCE;
    if (shouldShow !== lastVisible.current) {
      lastVisible.current = shouldShow;
      setVisible(shouldShow);
    }
  });

  if (!visible) return null;

  return (
    <>
      {districts.map((d) => (
        <Html
          key={d.id}
          position={[d.x + d.width / 2, 1, d.z + d.depth / 2]}
          center
          distanceFactor={80}
          occlude={false}
        >
          <div className="pointer-events-none rounded bg-slate-900/80 px-1.5 py-0.5 text-[10px] font-medium whitespace-nowrap text-white">
            {d.label}
          </div>
        </Html>
      ))}
    </>
  );
}

function HoverTooltip({ info }: { info: HoverInfo }) {
  const { building, file, districtLabel } = info;
  return (
    <Html
      position={[
        building.x + building.width / 2,
        building.height + 1,
        building.z + building.depth / 2,
      ]}
      center
      style={{ pointerEvents: "none" }}
    >
      <div className="w-56 rounded-md border border-slate-700 bg-slate-900/95 p-2 text-[11px] text-slate-100 shadow-lg">
        <p className="truncate font-mono" title={building.path}>
          {building.path}
        </p>
        <p className="mt-1 text-slate-300">
          {building.loc.toLocaleString()} LOC · complexity {building.complexity.toFixed(1)}
        </p>
        {file?.riskScore != null ? (
          <p className="text-slate-300">Risk {(file.riskScore * 100).toFixed(0)}%</p>
        ) : null}
        <p className="text-slate-400">{districtLabel}</p>
      </div>
    </Html>
  );
}

/**
 * The scene's one directional light, with its shadow camera frustum sized
 * to actually cover the whole ground plane. THREE's `DirectionalLight`
 * defaults to a tiny +/-5 unit orthographic shadow frustum aimed at world
 * origin (0,0,0) -- fine for a small demo scene, but this city's ground
 * plane spans hundreds of units and isn't centred on the origin, so the
 * default frustum missed almost the entire scene (observed directly: the
 * whole city rendered uniformly dim/washed-out, not just "missing
 * shadows", until both the frustum bounds AND the light's target were
 * corrected here). The target must be explicitly added to the scene graph
 * for THREE to use its position -- an untracked `target` prop value is a
 * documented three.js/R3F gotcha, hence the ref + primitive rather than a
 * plain `target={...}` prop. */
function CityLight({ worldWidth, worldDepth }: { worldWidth: number; worldDepth: number }) {
  const targetRef = useRef<THREE.Object3D>(null);
  const lightRef = useRef<THREE.DirectionalLight>(null);

  useEffect(() => {
    if (lightRef.current && targetRef.current) {
      lightRef.current.target = targetRef.current;
    }
  }, []);

  return (
    <>
      <directionalLight
        ref={lightRef}
        position={[worldWidth * 0.5, Math.max(worldWidth, worldDepth), worldDepth * 1.1]}
        intensity={4}
        castShadow
        shadow-mapSize-width={1024}
        shadow-mapSize-height={1024}
        shadow-camera-left={-worldWidth}
        shadow-camera-right={worldWidth}
        shadow-camera-top={worldDepth}
        shadow-camera-bottom={-worldDepth}
        shadow-camera-near={1}
        shadow-camera-far={Math.max(worldWidth, worldDepth) * 1.5}
        shadow-bias={-0.0015}
      />
      <object3D ref={targetRef} position={[worldWidth / 2, 0, worldDepth / 2]} />
    </>
  );
}

function CameraRig({ target }: { target: [number, number, number] }) {
  const { camera } = useThree();
  useEffect(() => {
    camera.lookAt(...target);
  }, [camera, target]);
  return null;
}

// --- Top-level component -----------------------------------------------------

export function CodeCity({ repoId, city }: { repoId: string; city: CityResponse }) {
  const [searchParams] = useSearchParams();
  const [colorMode, setColorMode] = useState<CityColorMode>("subsystem");
  const [heightMetric, setHeightMetric] = useState<CityHeightMetric>("complexity");
  const [hover, setHover] = useState<HoverInfo | null>(null);
  const [selected, setSelected] = useState<Building | null>(null);
  const [inView, setInView] = useState(true);
  const [tabHidden, setTabHidden] = useState(
    () => typeof document !== "undefined" && document.visibilityState === "hidden",
  );
  const containerRef = useRef<HTMLDivElement>(null);
  const reducedMotion = usePrefersReducedMotion();
  const webglAvailable = useMemo(detectWebGL, []);

  useEffect(() => {
    function onVisibility() {
      setTabHidden(document.visibilityState === "hidden");
    }
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const mountedAt = performance.now();
    const observer = new IntersectionObserver(
      ([entry]) => {
        // A freshly-mounted container can report a spurious
        // not-intersecting ratio before layout has fully settled (observed
        // directly: without this guard, the canvas could freeze on its
        // very first, incomplete frame -- dim, no lighting/shadows
        // resolved yet -- the moment frameloop flips to "never", and never
        // recover since nothing re-triggers a frame after that). A grace
        // period is enough since a REAL user scroll-away happens well
        // after mount, and this only delays the performance optimization
        // by a fraction of a second, never breaks it.
        if (performance.now() - mountedAt < 300) return;
        setInView(entry.isIntersecting);
      },
      { threshold: 0.05 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const files = useMemo(() => toCityFiles(city), [city]);
  const filesByPath = useMemo(() => new Map(files.map((f) => [f.path, f])), [files]);
  const labelById = useMemo(() => citySubsystemLabelById(city), [city]);
  const contributorNameById = useMemo(() => cityContributorNameById(city), [city]);

  const layoutInput = useMemo(
    () => ({
      subsystems: city.subsystems.map((s) => ({ id: s.id, label: s.label, totalLoc: s.total_loc })),
      files: files.map((f) => ({
        path: f.path,
        subsystemId: f.subsystemId,
        loc: f.loc,
        complexity: f.complexity,
        churnWeighted: f.churnWeighted,
        commitCount: f.commitCount,
      })),
    }),
    [city, files],
  );

  const layout = useMemo(
    () => layoutCity(layoutInput, { heightMetric }),
    [layoutInput, heightMetric],
  );

  const buildingsByDistrict = useMemo(() => {
    const map = new Map<number, Building[]>();
    for (const b of layout.buildings) {
      const bucket = map.get(b.districtId);
      if (bucket) bucket.push(b);
      else map.set(b.districtId, [b]);
    }
    return map;
  }, [layout]);

  const outskirtsByDistrict = useMemo(() => {
    const map = new Map<number, OutskirtsPlate>();
    for (const p of layout.outskirts) map.set(p.districtId, p);
    return map;
  }, [layout]);

  const focusPath = searchParams.get("focus");
  const focusBuilding = focusPath ? layout.buildings.find((b) => b.path === focusPath) : undefined;

  const worldWidth = Math.max(...layout.districts.map((d) => d.x + d.width), 1);
  const worldDepth = Math.max(...layout.districts.map((d) => d.z + d.depth), 1);
  const center = useMemo(
    () => new THREE.Vector3(worldWidth / 2, 0, worldDepth / 2),
    [worldWidth, worldDepth],
  );

  const cameraTarget: [number, number, number] = focusBuilding
    ? [
        focusBuilding.x + focusBuilding.width / 2,
        focusBuilding.height / 2,
        focusBuilding.z + focusBuilding.depth / 2,
      ]
    : [worldWidth / 2, 0, worldDepth / 2];
  const cameraPosition: [number, number, number] = focusBuilding
    ? [cameraTarget[0] + 20, cameraTarget[1] + 20, cameraTarget[2] + 20]
    : [worldWidth * 0.75, Math.max(worldWidth, worldDepth) * 0.6, worldDepth * 0.75];

  const selectedFile = selected ? filesByPath.get(selected.path) : undefined;
  const selectedSubsystemLabel = selected ? (labelById.get(selected.districtId) ?? null) : null;
  const selectedExpertName =
    selectedFile?.principalExpertId != null
      ? (contributorNameById.get(selectedFile.principalExpertId) ?? null)
      : null;

  if (!webglAvailable) {
    return (
      <DirectoryTreemap
        city={city}
        fallbackNotice="WebGL isn't available in this browser, so the 3D code city can't render here — showing the directory treemap instead."
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-4">
        <ModeSelect
          label="Colour by"
          value={colorMode}
          onChange={setColorMode}
          options={COLOR_MODE_LABEL}
        />
        <ModeSelect
          label="Height by"
          value={heightMetric}
          onChange={setHeightMetric}
          options={HEIGHT_MODE_LABEL}
        />
      </div>

      <PartialResultNotice
        shown={layout.buildingsShown}
        total={layout.totalFiles}
        itemLabel="files rendered as buildings (the rest are shown as flat outskirts plates)"
        capped={layout.capped}
      />

      <div
        ref={containerRef}
        className="relative h-[640px] w-full overflow-hidden rounded-lg border border-slate-200 bg-slate-950 dark:border-slate-800"
      >
        <Canvas
          key={focusPath ?? "default"}
          shadows
          frameloop={tabHidden || !inView ? "never" : "always"}
          camera={{ position: cameraPosition, fov: 50, near: 0.1, far: 5000 }}
          gl={{ toneMappingExposure: 1.4 }}
        >
          <ambientLight intensity={1.8} />
          <CityLight worldWidth={worldWidth} worldDepth={worldDepth} />
          <mesh
            rotation={[-Math.PI / 2, 0, 0]}
            position={[worldWidth / 2, -0.05, worldDepth / 2]}
            receiveShadow
          >
            <planeGeometry args={[worldWidth + 40, worldDepth + 40]} />
            <meshStandardMaterial color="#1e293b" />
          </mesh>

          {layout.districts.map((d) => (
            <DistrictBuildings
              key={d.id}
              district={d}
              buildings={buildingsByDistrict.get(d.id) ?? []}
              filesByPath={filesByPath}
              colorMode={colorMode}
              labelById={labelById}
              boundsLastModified={city.bounds.last_modified_at}
              onHover={setHover}
              onSelect={setSelected}
            />
          ))}
          <OutskirtsPlates plates={[...outskirtsByDistrict.values()]} />
          <DistrictLabels districts={layout.districts} center={center} />
          {hover ? <HoverTooltip info={hover} /> : null}

          <CameraRig target={cameraTarget} />
          <OrbitControls
            target={cameraTarget}
            enableDamping={!reducedMotion}
            autoRotate={false}
            maxPolarAngle={Math.PI / 2 - 0.05}
            minDistance={5}
            maxDistance={Math.max(worldWidth, worldDepth) * 2.5}
          />
        </Canvas>
      </div>

      <Legend colorMode={colorMode} heightMetric={heightMetric} districts={layout.districts} />

      {selected ? (
        <FileDetailPanel
          repoId={repoId}
          path={selected.path}
          loc={selected.loc}
          complexity={selected.complexity}
          riskScore={selectedFile?.riskScore}
          subsystemLabel={selectedSubsystemLabel}
          expertName={selectedExpertName}
          onClose={() => setSelected(null)}
        />
      ) : null}
    </div>
  );
}

function Legend({
  colorMode,
  heightMetric,
  districts,
}: {
  colorMode: CityColorMode;
  heightMetric: CityHeightMetric;
  districts: District[];
}) {
  return (
    <Card title="Legend">
      <p className="text-xs text-slate-600 dark:text-slate-300">
        Footprint area = lines of code. Height = {HEIGHT_MODE_LABEL[heightMetric].toLowerCase()}.
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {colorMode === "subsystem" ? (
          districts.map((d) => (
            <span
              key={d.id}
              className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300"
            >
              <span
                className="h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: colorForSubsystem(d.label) }}
              />
              {d.label}
            </span>
          ))
        ) : colorMode === "risk" ? (
          <GradientLegend
            lowLabel="Low risk"
            highLabel="High risk"
            lowColor="#22c55e"
            highColor="#ef4444"
          />
        ) : colorMode === "age" ? (
          <GradientLegend
            lowLabel="Stale"
            highLabel="Recently changed"
            lowColor={UNASSIGNED_COLOR}
            highColor="#0ea5e9"
          />
        ) : colorMode === "test" ? (
          <>
            <Swatch color={SOURCE_COLOR} label="Source" />
            <Swatch color={TEST_COLOR} label="Test" />
          </>
        ) : (
          <p className="text-[11px] text-slate-500 dark:text-slate-400">
            Colour = principal author. Hover a building to see who.
          </p>
        )}
      </div>
    </Card>
  );
}

function GradientLegend({
  lowLabel,
  highLabel,
  lowColor,
  highColor,
}: {
  lowLabel: string;
  highLabel: string;
  lowColor: string;
  highColor: string;
}) {
  return (
    <div className="flex items-center gap-2 text-[11px] text-slate-500 dark:text-slate-400">
      <span>{lowLabel}</span>
      <span
        className="h-2.5 w-24 rounded-full"
        style={{ background: `linear-gradient(to right, ${lowColor}, ${highColor})` }}
      />
      <span>{highLabel}</span>
    </div>
  );
}

function Swatch({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-slate-500 dark:text-slate-400">
      <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />
      {label}
    </span>
  );
}
