import type { KeyboardEvent, ReactNode } from "react";
import { Handle, Position, useStore, type Node, type NodeProps } from "@xyflow/react";
import {
  Box,
  ChevronDown,
  ChevronRight,
  Cloud,
  Database,
  FileCode,
  Folder,
  Users,
  Workflow,
} from "lucide-react";
import type { DiagramInfraCategory, DiagramLayerKind } from "../../api/types";
import { MAP_COPY } from "../../content/map";
import { TOOLTIPS } from "../../content/explainability";
import { activityColor } from "../../lib/diagram/activity";
import { displayName, groupById, groupColor } from "../../lib/diagram/display";
import { EXPANDED_HEADER } from "../../lib/diagram/layout";
import { sumChurn, sumLoc } from "../../lib/diagram/tree";
import type { VisibleNode } from "../../lib/diagram/visible";
import { formatCompact } from "../../lib/format";
import { InfoTooltip } from "../ui/InfoTooltip";
import { useMapContext } from "./mapContext";

export type DiagramNodeData = { vnode: VisibleNode };
export type BandNodeData = { index: number; label: string; kind: DiagramLayerKind };

type DiagramRFNode = Node<DiagramNodeData>;
type BandRFNode = Node<BandNodeData>;

/** Semantic zoom threshold: below this zoom a box shows only a large label. */
const COMPACT_ZOOM = 0.6;

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

/** Shared frame: dimming, selection ring, keyboard activation. */
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
  const frameClass = `${dimmed ? "opacity-20" : "opacity-100"} ${
    selected ? "ring-2 ring-accent ring-offset-2 ring-offset-bg" : ""
  } transition-opacity`;
  return { ctx, frameClass, onKeyDown };
}

function ExpandButton({ vnode, label }: { vnode: VisibleNode; label: string }) {
  const { onToggleExpand } = useMapContext();
  if (!vnode.expandable) return null;
  const Icon = vnode.expanded ? ChevronDown : ChevronRight;
  return (
    <button
      type="button"
      className="nodrag nopan inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-xs border border-border text-text-muted hover:border-accent hover:text-accent"
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
      <span key="entry" className="text-accent">
        ▲ entry
      </span>,
    );
  }
  if (group?.in_group_cycle) {
    items.push(
      <span key="cycle" className="text-danger">
        ↻ cycle
      </span>,
    );
  }
  if (steps && steps.length > 0) {
    items.push(
      <span
        key="tour"
        className="rounded-full bg-accent px-1.5 text-accent-contrast"
        title="Reading-order stops"
      >
        {steps.slice(0, 4).join(" · ")}
        {steps.length > 4 ? " …" : ""}
      </span>,
    );
  }
  if (items.length === 0) return null;
  return <div className="flex flex-wrap items-center gap-2 text-2xs font-medium">{items}</div>;
}

export function GroupNode({ data: { vnode } }: NodeProps<DiagramRFNode>) {
  const { ctx, frameClass, onKeyDown } = useFrame(vnode);
  const compact = useCompact();
  const group = groupById(ctx.data, vnode.groupId);
  const color = groupColor(ctx.data, vnode.groupId);
  const { name, fromAi } = displayName(vnode, ctx.aiOn, ctx.aiGroups);
  const caption = ctx.aiOn && vnode.groupId ? ctx.aiGroups.get(vnode.groupId)?.caption : null;
  const bucket = ctx.activity.get(vnode.id) ?? 0;
  const background = ctx.lens === "activity" && !vnode.expanded ? activityColor(bucket) : undefined;

  if (vnode.expanded) {
    return (
      <div
        className={`h-full w-full rounded-md border border-dashed border-border-strong ${frameClass}`}
        onKeyDown={onKeyDown}
        style={{ boxShadow: `inset 4px 0 0 ${color}` }}
      >
        <Handles />
        <div
          className="flex items-center gap-2 px-3"
          style={{ height: EXPANDED_HEADER - 8, paddingTop: 8 }}
        >
          <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: color }} />
          <span className="truncate text-sm font-semibold text-text-heading">{name}</span>
          {fromAi ? <AiChip /> : null}
          <span className="cp-stat shrink-0 text-2xs text-text-muted">
            {vnode.fileIndices.length} files
          </span>
          <span className="ml-auto" />
          <Badges vnode={vnode} />
          <ExpandButton vnode={vnode} label={name} />
        </div>
      </div>
    );
  }

  return (
    <div
      className={`relative flex h-full w-full flex-col justify-center overflow-hidden rounded-md border border-border bg-bg shadow-sm ${frameClass}`}
      style={{ background, boxShadow: `inset 4px 0 0 ${color}` }}
      onKeyDown={onKeyDown}
    >
      <Handles />
      {compact ? (
        <>
          <div className="px-4 text-center font-display text-xl leading-tight text-text-heading">
            <span className="line-clamp-2">{name}</span>
          </div>
          {/* Still expandable when zoomed out -- the chevron just moves to
              the corner instead of sitting in the (hidden) detail row. */}
          <div className="absolute top-2 right-2">
            <ExpandButton vnode={vnode} label={name} />
          </div>
          <div className="absolute bottom-2 left-4">
            <Badges vnode={vnode} />
          </div>
        </>
      ) : (
        <div className="flex h-full flex-col gap-1 py-2.5 pr-2.5 pl-4">
          <div className="flex items-start gap-1.5">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                <span className="truncate text-sm font-semibold text-text-heading" title={name}>
                  {name}
                </span>
                {fromAi ? <AiChip /> : null}
              </div>
              {fromAi ? (
                <p className="truncate text-2xs text-text-muted">
                  {MAP_COPY.computedPrefix} {vnode.label}
                </p>
              ) : null}
            </div>
            <ExpandButton vnode={vnode} label={name} />
          </div>
          {caption ? (
            <p className="line-clamp-2 text-xs italic leading-snug text-text-muted" title={caption}>
              {caption}
            </p>
          ) : null}
          <p className="cp-stat mt-auto truncate font-mono text-2xs text-text-muted">
            {group?.file_count ?? vnode.fileIndices.length} files ·{" "}
            {formatCompact(group?.total_loc ?? 0)} LOC
            {group?.cohesion != null ? ` · cohesion ${group.cohesion.toFixed(2)}` : ""}
            {ctx.lens === "activity"
              ? ` · ${(group?.churn_365d ?? 0).toLocaleString()} chg/yr`
              : ""}
          </p>
          <Badges vnode={vnode} />
        </div>
      )}
    </div>
  );
}

export function FolderNode({ data: { vnode } }: NodeProps<DiagramRFNode>) {
  const { ctx, frameClass, onKeyDown } = useFrame(vnode);
  const compact = useCompact();
  const color = groupColor(ctx.data, vnode.groupId);
  const bucket = ctx.activity.get(vnode.id) ?? 0;

  if (vnode.expanded) {
    return (
      <div
        className={`h-full w-full rounded-sm border border-dashed border-border ${frameClass}`}
        onKeyDown={onKeyDown}
      >
        <Handles />
        <div
          className="flex items-center gap-2 px-2.5"
          style={{ height: EXPANDED_HEADER - 12, paddingTop: 10 }}
        >
          <Folder size={13} className="shrink-0 text-text-muted" aria-hidden="true" />
          <span className="truncate font-mono text-xs text-text">{vnode.label}/</span>
          <span className="cp-stat shrink-0 text-2xs text-text-muted">
            {vnode.fileIndices.length} files
          </span>
          <span className="ml-auto" />
          <ExpandButton vnode={vnode} label={vnode.label} />
        </div>
      </div>
    );
  }

  return (
    <div
      className={`flex h-full w-full items-center gap-2 rounded-sm border border-border bg-bg-subtle px-2.5 ${frameClass}`}
      style={{
        background: ctx.lens === "activity" ? activityColor(bucket) : undefined,
        boxShadow: `inset 3px 0 0 ${color}`,
      }}
      onKeyDown={onKeyDown}
    >
      <Handles />
      <Folder size={14} className="shrink-0 text-text-muted" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className={`truncate font-mono text-text ${compact ? "text-base" : "text-xs"}`}>
          {vnode.label}/
        </p>
        {compact ? null : (
          <p className="cp-stat truncate text-2xs text-text-muted">
            {vnode.fileIndices.length} files · {formatCompact(sumLoc(ctx.data, vnode.fileIndices))}{" "}
            LOC
            {ctx.lens === "activity"
              ? ` · ${sumChurn(ctx.data, vnode.fileIndices).toLocaleString()} chg/yr`
              : ""}
          </p>
        )}
      </div>
      <ExpandButton vnode={vnode} label={vnode.label} />
    </div>
  );
}

export function FileNode({ data: { vnode } }: NodeProps<DiagramRFNode>) {
  const { ctx, frameClass, onKeyDown } = useFrame(vnode);
  const compact = useCompact();
  const file = vnode.fileIndex != null ? ctx.data.files[vnode.fileIndex] : null;
  const bucket = ctx.activity.get(vnode.id) ?? 0;
  const isEntry =
    file != null &&
    ctx.data.groups.some((g) => g.entry_points.some((ep) => ep.file_index === file.i));

  return (
    <div
      className={`flex h-full w-full items-center gap-2 rounded-sm border border-border bg-bg px-2.5 ${frameClass}`}
      style={{ background: ctx.lens === "activity" ? activityColor(bucket) : undefined }}
      title={file?.path}
      onKeyDown={onKeyDown}
    >
      <Handles />
      <FileCode size={13} className="shrink-0 text-text-muted" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className={`truncate font-mono text-text ${compact ? "text-base" : "text-xs"}`}>
          {vnode.label}
        </p>
        {compact || !file ? null : (
          <p className="cp-stat flex items-center gap-1.5 truncate text-2xs text-text-muted">
            {file.loc.toLocaleString()} LOC
            {isEntry ? <span className="text-accent">▲ entry</span> : null}
            {file.is_test ? <span>test</span> : null}
          </p>
        )}
      </div>
    </div>
  );
}

export function MoreNode({ data: { vnode } }: NodeProps<DiagramRFNode>) {
  const { frameClass, onKeyDown } = useFrame(vnode);
  return (
    <div
      className={`flex h-full w-full items-center justify-center rounded-full border border-dashed border-border-strong bg-bg-elevated text-xs text-text-muted ${frameClass}`}
      onKeyDown={onKeyDown}
    >
      <Handles />
      {vnode.label}
    </div>
  );
}

export function ActorNode({ data: { vnode } }: NodeProps<DiagramRFNode>) {
  const { frameClass, onKeyDown } = useFrame(vnode);
  return (
    <div
      className={`flex h-full w-full items-center justify-center gap-2 rounded-full border border-accent bg-accent-bg text-sm font-medium text-accent ${frameClass}`}
      onKeyDown={onKeyDown}
    >
      <Handles />
      <Users size={15} aria-hidden="true" />
      {vnode.label}
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
  return (
    <div
      className={`flex h-full w-full items-center gap-2.5 rounded-md border border-border bg-bg-subtle px-3 ${frameClass}`}
      onKeyDown={onKeyDown}
    >
      <Handles />
      <Icon size={compact ? 22 : 18} className="shrink-0 text-text-muted" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className={`truncate font-medium text-text-heading ${compact ? "text-lg" : "text-sm"}`}>
          {vnode.label}
        </p>
        {compact || !item ? null : (
          <p className="truncate text-2xs text-text-muted">{item.evidence[0]}</p>
        )}
      </div>
    </div>
  );
}

export function BandNode({ data }: NodeProps<BandRFNode>) {
  const { aiOn, aiBands } = useMapContext();
  const aiName = aiOn ? aiBands.get(data.index) : undefined;
  return (
    <div className="pointer-events-none h-full w-full rounded-lg border border-border/60 bg-bg-inset/40">
      <div className="pointer-events-auto absolute top-2 left-3 flex items-center gap-1.5 px-1">
        <span className="cp-label text-text-muted">{aiName ?? data.label}</span>
        {aiName ? <AiChip /> : null}
        {data.kind !== "actor" && data.kind !== "infra" ? (
          <InfoTooltip label="How are bands computed?" text={TOOLTIPS.mapLayers} />
        ) : null}
      </div>
    </div>
  );
}
