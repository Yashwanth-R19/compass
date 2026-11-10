import type { CSSProperties, KeyboardEvent, ReactNode } from "react";
import { Handle, Position, useStore, type Node, type NodeProps } from "@xyflow/react";
import {
  Box,
  ChevronDown,
  ChevronRight,
  Cloud,
  Database,
  Folder,
  Users,
  Workflow,
} from "lucide-react";
import type { DiagramInfraCategory, DiagramLayerKind } from "../../api/types";
import { MAP_COPY } from "../../content/map";
import { TOOLTIPS } from "../../content/explainability";
import { activityColor } from "../../lib/diagram/activity";
import {
  EXTERNAL_HUE,
  displayName,
  fileTitle,
  groupById,
  groupHue,
} from "../../lib/diagram/display";
import { CONTAINER_FOOTER, EXPANDED_HEADER } from "../../lib/diagram/layout";
import type { VisibleNode } from "../../lib/diagram/visible";
import { formatCompact } from "../../lib/format";
import { InfoTooltip } from "../ui/InfoTooltip";
import { useMapContext } from "./mapContext";

export type DiagramNodeData = { vnode: VisibleNode };
export type BandNodeData = { index: number; label: string; kind: DiagramLayerKind };

type DiagramRFNode = Node<DiagramNodeData>;
type BandRFNode = Node<BandNodeData>;

/** Semantic zoom threshold: below this, boxes drop their secondary lines and
 * enlarge their titles so the overview stays legible. Box sizes never change. */
const COMPACT_ZOOM = 0.55;

function useCompact(): boolean {
  return useStore((s) => s.transform[2] < COMPACT_ZOOM);
}

/** One invisible handle per side. The canvas runs in loose connection mode
 * and picks a side pair per edge from the laid-out positions (down the page
 * between bands, sideways within a band), so edges never loop over boxes. */
function Handles() {
  return (
    <>
      <Handle
        id="t"
        type="source"
        position={Position.Top}
        className="!opacity-0"
        isConnectable={false}
      />
      <Handle
        id="b"
        type="source"
        position={Position.Bottom}
        className="!opacity-0"
        isConnectable={false}
      />
      <Handle
        id="l"
        type="source"
        position={Position.Left}
        className="!opacity-0"
        isConnectable={false}
      />
      <Handle
        id="r"
        type="source"
        position={Position.Right}
        className="!opacity-0"
        isConnectable={false}
      />
    </>
  );
}

function AiChip() {
  return (
    <span
      className="inline-flex shrink-0 items-center rounded-xs border border-info px-1 text-[10px] font-medium leading-4 text-info"
      title={TOOLTIPS.mapAiLabel}
      aria-label="AI-written"
    >
      {MAP_COPY.aiChip}
    </span>
  );
}

/** Shared behaviour: dimming, selection ring, keyboard activation. */
function useFrame(vnode: VisibleNode) {
  const ctx = useMapContext();
  const dimmed = ctx.emphasis !== null && !ctx.emphasis.has(vnode.id);
  const selected = ctx.selectedId === vnode.id;
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter") ctx.onSelect(vnode.id);
    if (e.key === " " && vnode.expandable) {
      e.preventDefault();
      ctx.onToggleExpand(vnode.id);
    }
  };
  const frameClass = `${dimmed ? "opacity-[0.18]" : "opacity-100"} ${
    selected ? "ring-2 ring-accent ring-offset-2 ring-offset-bg" : ""
  } transition-opacity duration-200`;
  return { ctx, frameClass, onKeyDown };
}

function ExpandButton({ vnode, label }: { vnode: VisibleNode; label: string }) {
  const { onToggleExpand } = useMapContext();
  if (!vnode.expandable) return null;
  const Icon = vnode.expanded ? ChevronDown : ChevronRight;
  return (
    <button
      type="button"
      className="nodrag nopan inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-xs text-text-muted transition-colors hover:bg-bg-inset hover:text-accent"
      aria-label={`${vnode.expanded ? "Collapse" : "Expand"} ${label}`}
      aria-expanded={vnode.expanded}
      onClick={(e) => {
        e.stopPropagation();
        onToggleExpand(vnode.id);
      }}
    >
      <Icon size={14} aria-hidden="true" />
    </button>
  );
}

function Badges({ vnode }: { vnode: VisibleNode }) {
  const { data, tourSteps } = useMapContext();
  const group = vnode.kind === "group" ? groupById(data, vnode.groupId) : null;
  const steps = tourSteps.get(vnode.id);
  const items: ReactNode[] = [];
  if (group && group.entry_points.length > 0) {
    items.push(
      <span key="entry" className="text-accent" title="Has entry points">
        ▲ entry
      </span>,
    );
  }
  if (group?.in_group_cycle) {
    items.push(
      <span key="cycle" className="text-danger" title="Imports and is imported by another group">
        ↻ cycle
      </span>,
    );
  }
  if (steps && steps.length > 0) {
    items.push(
      <span
        key="tour"
        className="rounded-full bg-accent px-1.5 font-mono text-accent-contrast"
        title="Reading-order stops"
      >
        {steps.slice(0, 4).join(" · ")}
        {steps.length > 4 ? " …" : ""}
      </span>,
    );
  }
  if (items.length === 0) return null;
  return <div className="flex items-center gap-2 text-[10px] font-medium leading-4">{items}</div>;
}

// ---------------------------------------------------------------------------
// Containers (a group, collapsed or expanded)
// ---------------------------------------------------------------------------

export function GroupNode({ data: { vnode } }: NodeProps<DiagramRFNode>) {
  const { ctx, frameClass, onKeyDown } = useFrame(vnode);
  const compact = useCompact();
  const group = groupById(ctx.data, vnode.groupId);
  const hue = groupHue(ctx.data, vnode.groupId);
  const { name, fromAi } = displayName(vnode, ctx.aiOn, ctx.aiGroups);
  const caption = ctx.aiOn && vnode.groupId ? ctx.aiGroups.get(vnode.groupId)?.caption : null;
  const fileCount = group?.file_count ?? vnode.fileIndices.length;
  const shownChildren = ctx.childCount.get(vnode.id) ?? 0;
  const hiddenFiles = vnode.expanded ? 0 : fileCount - shownChildren;

  const style: CSSProperties = {
    background: vnode.expanded ? "transparent" : "var(--map-cluster-bg)",
    borderColor: "var(--map-cluster-border)",
  };

  return (
    <div
      className={`relative h-full w-full rounded-[6px] border ${vnode.expanded ? "border-dashed" : ""} ${frameClass}`}
      style={style}
      onKeyDown={onKeyDown}
    >
      <Handles />
      {/* Hue marker: a thin top rule in the group's colour. */}
      <span
        aria-hidden="true"
        className="absolute inset-x-0 top-0 h-[3px] rounded-t-[6px]"
        style={{ background: hue.stroke }}
      />
      <div
        className="flex flex-col items-center justify-center px-9 text-center"
        style={{ height: shownChildren > 0 || vnode.expanded ? EXPANDED_HEADER : "100%" }}
      >
        <div className="flex max-w-full items-center gap-1.5">
          <span
            className={`truncate font-semibold ${compact ? "text-lg" : "text-[13px]"}`}
            style={{ color: "var(--map-cluster-title)" }}
            title={fromAi ? `${name} (computed: ${vnode.label})` : name}
          >
            {name}
          </span>
          {fromAi && !compact ? <AiChip /> : null}
        </div>
        {compact ? null : (
          <p className="max-w-full truncate font-mono text-[10.5px] text-text-muted">
            {group?.base_path ? `[${group.base_path}] · ` : ""}
            {fileCount} file{fileCount === 1 ? "" : "s"}
            {group ? ` · ${formatCompact(group.total_loc)} LOC` : ""}
            {fromAi ? ` · computed: ${vnode.label}` : ""}
          </p>
        )}
      </div>
      <div className="absolute top-1.5 left-2">
        <Badges vnode={vnode} />
      </div>
      <div className="absolute top-1.5 right-1.5">
        <ExpandButton vnode={vnode} label={name} />
      </div>
      {caption && !compact && !vnode.expanded && shownChildren === 0 ? (
        <p className="px-4 text-center text-[11px] italic leading-snug text-text-muted">
          {caption}
        </p>
      ) : null}
      {hiddenFiles > 0 && !compact ? (
        <button
          type="button"
          className="nodrag nopan absolute inset-x-0 bottom-0 flex items-center justify-center text-[11px] text-text-muted hover:text-accent"
          style={{ height: CONTAINER_FOOTER }}
          onClick={(e) => {
            e.stopPropagation();
            ctx.onToggleExpand(vnode.id);
          }}
          aria-label={`Expand ${name} to show all ${fileCount} files`}
        >
          +{hiddenFiles} more file{hiddenFiles === 1 ? "" : "s"}
        </button>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Boxes inside containers
// ---------------------------------------------------------------------------

function Box2Line({
  vnode,
  title,
  subtitle,
  icon,
  trailing,
}: {
  vnode: VisibleNode;
  title: string;
  subtitle: string;
  icon?: ReactNode;
  trailing?: ReactNode;
}) {
  const { ctx, frameClass, onKeyDown } = useFrame(vnode);
  const compact = useCompact();
  const hue = groupHue(ctx.data, vnode.groupId);
  const bucket = ctx.activity.get(vnode.id) ?? 0;
  const activityOn = ctx.lens === "activity";
  const style: CSSProperties = {
    background: activityOn ? activityColor(bucket) : hue.fill,
    borderColor: activityOn ? "var(--color-accent)" : hue.stroke,
    color: activityOn ? "var(--color-text)" : hue.text,
  };
  return (
    <div
      className={`relative flex h-full w-full items-center justify-center gap-1.5 rounded-[4px] border-[1.5px] px-3 ${frameClass}`}
      style={style}
      onKeyDown={onKeyDown}
    >
      <Handles />
      {icon}
      <div className="min-w-0 text-center leading-tight">
        <p
          className={`truncate font-medium ${compact ? "text-[15px]" : "text-[12.5px]"}`}
          title={title}
        >
          {title}
        </p>
        {compact ? null : (
          <p className="truncate font-mono text-[10.5px] opacity-75" title={subtitle}>
            {subtitle}
          </p>
        )}
      </div>
      {trailing}
    </div>
  );
}

function isEntryFile(vnode: VisibleNode, data: ReturnType<typeof useMapContext>["data"]): boolean {
  return (
    vnode.fileIndex != null &&
    data.groups.some((g) => g.entry_points.some((ep) => ep.file_index === vnode.fileIndex))
  );
}

/** A key file of a collapsed group, or a file inside an expanded one. */
export function ComponentNode({ data: { vnode } }: NodeProps<DiagramRFNode>) {
  const { data } = useMapContext();
  const file = vnode.fileIndex != null ? data.files[vnode.fileIndex] : null;
  const entry = isEntryFile(vnode, data);
  return (
    <Box2Line
      vnode={vnode}
      title={file ? fileTitle(file.path) : vnode.label}
      subtitle={`[${vnode.label}]`}
      trailing={
        entry ? (
          <span
            className="absolute -top-2 -right-2 rounded-full border border-accent bg-bg px-1 text-[9px] font-semibold leading-4 text-accent"
            title="Entry point"
          >
            ▲
          </span>
        ) : null
      }
    />
  );
}

export function FolderNode({ data: { vnode } }: NodeProps<DiagramRFNode>) {
  const { frameClass, onKeyDown } = useFrame(vnode);
  if (vnode.expanded) {
    return (
      <div
        className={`h-full w-full rounded-[6px] border border-dashed ${frameClass}`}
        style={{ borderColor: "var(--map-cluster-border)" }}
        onKeyDown={onKeyDown}
      >
        <Handles />
        <div
          className="flex items-center justify-center gap-2 px-8"
          style={{ height: EXPANDED_HEADER }}
        >
          <Folder size={13} className="shrink-0 text-text-muted" aria-hidden="true" />
          <span
            className="truncate font-mono text-xs"
            style={{ color: "var(--map-cluster-title)" }}
          >
            {vnode.label}/
          </span>
          <span className="shrink-0 text-[10.5px] text-text-muted">
            {vnode.fileIndices.length} files
          </span>
        </div>
        <div className="absolute top-1.5 right-1.5">
          <ExpandButton vnode={vnode} label={vnode.label} />
        </div>
      </div>
    );
  }
  return (
    <Box2Line
      vnode={vnode}
      title={`${vnode.label}/`}
      subtitle={`[${vnode.fileIndices.length} file${vnode.fileIndices.length === 1 ? "" : "s"}]`}
      icon={<Folder size={13} className="shrink-0 opacity-70" aria-hidden="true" />}
      trailing={
        <div className="absolute top-1/2 right-1 -translate-y-1/2">
          <ExpandButton vnode={vnode} label={vnode.label} />
        </div>
      }
    />
  );
}

export function MoreNode({ data: { vnode } }: NodeProps<DiagramRFNode>) {
  const { frameClass, onKeyDown } = useFrame(vnode);
  return (
    <div
      className={`flex h-full w-full items-center justify-center rounded-full border border-dashed text-[11px] text-text-muted ${frameClass}`}
      style={{ borderColor: "var(--map-cluster-border)", background: "var(--map-cluster-bg)" }}
      onKeyDown={onKeyDown}
    >
      <Handles />
      {vnode.label}
    </div>
  );
}

// ---------------------------------------------------------------------------
// External things
// ---------------------------------------------------------------------------

export function ActorNode({ data: { vnode } }: NodeProps<DiagramRFNode>) {
  const { frameClass, onKeyDown } = useFrame(vnode);
  return (
    <div
      className={`flex h-full w-full flex-col items-center justify-center gap-1 rounded-full border-[1.5px] text-center ${frameClass}`}
      style={{
        background: EXTERNAL_HUE.fill,
        borderColor: EXTERNAL_HUE.stroke,
        color: EXTERNAL_HUE.text,
      }}
      onKeyDown={onKeyDown}
    >
      <Handles />
      <Users size={18} aria-hidden="true" />
      <span className="px-3 text-[12px] font-medium leading-tight">{vnode.label}</span>
    </div>
  );
}

const INFRA_ICON: Record<DiagramInfraCategory, typeof Box> = {
  container: Box,
  deploy: Cloud,
  ci: Workflow,
  datastore: Database,
};

export function InfraNode({ data: { vnode } }: NodeProps<DiagramRFNode>) {
  const { ctx, frameClass, onKeyDown } = useFrame(vnode);
  const compact = useCompact();
  const item = ctx.data.infra.find((i) => i.id === vnode.id);
  const Icon = item ? INFRA_ICON[item.category] : Box;
  const file = item?.paths[0];
  return (
    <div
      className={`flex h-full w-full items-center justify-center gap-2 rounded-[4px] border-[1.5px] px-3 ${frameClass}`}
      style={{
        background: EXTERNAL_HUE.fill,
        borderColor: EXTERNAL_HUE.stroke,
        color: EXTERNAL_HUE.text,
      }}
      onKeyDown={onKeyDown}
    >
      <Handles />
      <Icon size={compact ? 18 : 14} className="shrink-0 opacity-80" aria-hidden="true" />
      <div className="min-w-0 text-center leading-tight">
        <p className={`truncate font-medium ${compact ? "text-[15px]" : "text-[12.5px]"}`}>
          {vnode.label}
        </p>
        {compact || !file ? null : (
          <p className="truncate font-mono text-[10.5px] opacity-75">[{file.split("/").pop()}]</p>
        )}
      </div>
    </div>
  );
}

/** A band: no slab, just a faint dashed rule and a small label -- the layers
 * are a reading aid, not the main event. */
export function BandNode({ data }: NodeProps<BandRFNode>) {
  const { aiOn, aiBands } = useMapContext();
  const aiName = aiOn ? aiBands.get(data.index) : undefined;
  return (
    <div className="pointer-events-none h-full w-full border-t border-dashed border-border/70">
      <div className="pointer-events-auto absolute top-2 left-0 flex items-center gap-1.5">
        <span className="cp-label text-[10px] text-text-muted/80">{aiName ?? data.label}</span>
        {aiName ? <AiChip /> : null}
        {data.kind !== "actor" && data.kind !== "infra" ? (
          <InfoTooltip label="How are bands computed?" text={TOOLTIPS.mapLayers} />
        ) : null}
      </div>
    </div>
  );
}
