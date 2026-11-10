import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ExternalLink, X } from "lucide-react";
import type { DiagramAiGroupOut, DiagramResponse } from "../../api/types";
import { ENTRY_KIND_LABEL, MAP_COPY } from "../../content/map";
import { HONESTY, TOOLTIPS } from "../../content/explainability";
import { displayName, edgeVerb, groupById, groupColor, withShare } from "../../lib/diagram/display";
import { fileNodeId, folderNodeId, groupNodeId, parseNodeId } from "../../lib/diagram/ids";
import { blobUrl, hostLabel, treeUrl } from "../../lib/diagram/sourceLinks";
import {
  findFolder,
  maxLastChanged,
  sumChurn,
  sumLoc,
  type TreeChild,
  type TreeFolder,
} from "../../lib/diagram/tree";
import type { VisibleEdge, VisibleGraph } from "../../lib/diagram/visible";
import { formatPercent } from "../../lib/format";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { InfoTooltip } from "../ui/InfoTooltip";
import { HonestyNote } from "../HonestyNote";

export interface SidePanelActions {
  onSelect: (id: string) => void;
  onToggleExpand: (id: string) => void;
  onFocus: (id: string) => void;
  onPathEnd: (which: "from" | "to", id: string) => void;
}

interface PanelProps extends SidePanelActions {
  selectedId: string;
  data: DiagramResponse;
  graph: VisibleGraph;
  edges: VisibleEdge[];
  trees: Map<string, TreeFolder>;
  indexByPath: Map<string, number>;
  aiOn: boolean;
  aiGroups: Map<string, DiagramAiGroupOut>;
  aiVerbs: Map<string, string>;
  share: string | undefined;
}

const TOP_FILES = 8;

function formatDate(epochSeconds: number): string {
  return epochSeconds > 0 ? new Date(epochSeconds * 1000).toLocaleDateString() : "—";
}

function Facts({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
      {rows.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-text-muted">{k}</dt>
          <dd className="cp-stat text-right font-mono text-text">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-1.5">
      <h4 className="cp-label text-text-muted">{title}</h4>
      {children}
    </section>
  );
}

function ExternalSourceLink({ href, data }: { href: string | null; data: DiagramResponse }) {
  if (!href) return null;
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
    >
      Open on {hostLabel(data.source)} <ExternalLink size={11} aria-hidden="true" />
    </a>
  );
}

function rankFiles(data: DiagramResponse, indices: number[]): number[] {
  return [...indices].sort((a, b) => {
    const fa = data.files[a];
    const fb = data.files[b];
    const primary =
      data.grouping === "subsystem" ? (fb.centrality ?? 0) - (fa.centrality ?? 0) : fb.loc - fa.loc;
    return primary || fa.path.localeCompare(fb.path);
  });
}

function FileList({
  data,
  indices,
  onSelect,
}: {
  data: DiagramResponse;
  indices: number[];
  onSelect: (id: string) => void;
}) {
  return (
    <ul className="flex flex-col gap-0.5">
      {indices.map((i) => (
        <li key={i} className="flex items-center justify-between gap-2">
          <button
            type="button"
            onClick={() => onSelect(fileNodeId(data.files[i].path))}
            className="min-w-0 truncate text-left font-mono text-xs text-accent hover:underline"
            title={data.files[i].path}
          >
            {data.files[i].path}
          </button>
          <span className="cp-stat shrink-0 text-2xs text-text-muted">
            {data.files[i].loc.toLocaleString()} LOC
          </span>
        </li>
      ))}
    </ul>
  );
}

function ActionRow({
  id,
  expandable,
  expanded,
  actions,
}: {
  id: string;
  expandable?: boolean;
  expanded?: boolean;
  actions: SidePanelActions;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {expandable ? (
        <Button type="button" size="sm" onClick={() => actions.onToggleExpand(id)}>
          {expanded ? "Collapse" : "Expand"}
        </Button>
      ) : null}
      <Button type="button" size="sm" onClick={() => actions.onFocus(id)}>
        Focus
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={() => actions.onPathEnd("from", id)}>
        Path from here
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={() => actions.onPathEnd("to", id)}>
        Path to here
      </Button>
    </div>
  );
}

function GroupPanel(props: PanelProps & { groupId: string }) {
  const { data, groupId, trees, aiOn, aiGroups, graph, share } = props;
  const group = groupById(data, groupId);
  const tree = trees.get(groupId);
  if (!group || !tree)
    return <p className="text-xs text-text-muted">This group is no longer on the map.</p>;
  const id = groupNodeId(groupId);
  const vnode = graph.byId.get(id);
  const { name, fromAi } = vnode
    ? displayName(vnode, aiOn, aiGroups)
    : { name: group.label, fromAi: false };
  const caption = aiOn ? aiGroups.get(groupId)?.caption : null;
  const labelOf = (gid: string) => groupById(data, gid)?.label ?? gid;
  const outgoing = data.group_edges
    .filter((e) => e.source === groupId)
    .sort((a, b) => b.import_count - a.import_count);
  const incoming = data.group_edges
    .filter((e) => e.target === groupId)
    .sort((a, b) => b.import_count - a.import_count);
  const hidden = data.hidden_group_edges
    .filter((h) => h.a === groupId || h.b === groupId)
    .sort((a, b) => b.max_degree - a.max_degree);
  const band = data.layers.find((l) => l.index === group.layer);

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <span
            className="h-3 w-3 shrink-0 rounded-full"
            style={{ background: groupColor(data, groupId) }}
          />
          <h3 className="font-display text-lg text-text-heading">{name}</h3>
          {fromAi ? <Badge tone="neutral">AI name</Badge> : null}
        </div>
        {fromAi ? (
          <p className="text-xs text-text-muted">
            {MAP_COPY.computedPrefix} {group.label}
          </p>
        ) : null}
        {caption ? (
          <p className="text-sm italic text-text-muted">
            {caption}{" "}
            <span className="not-italic text-info" title={TOOLTIPS.mapAiLabel}>
              (AI)
            </span>
          </p>
        ) : null}
        {band ? <p className="cp-label text-text-muted">Band: {band.label}</p> : null}
      </header>
      <ActionRow
        id={id}
        expandable={vnode?.expandable}
        expanded={vnode?.expanded}
        actions={props}
      />
      <Facts
        rows={[
          ["Files", group.file_count.toLocaleString()],
          ["Lines of code", group.total_loc.toLocaleString()],
          ...(group.cohesion != null
            ? [
                [
                  <span key="c" className="inline-flex items-center gap-1">
                    Cohesion <InfoTooltip label="What is cohesion?" text={TOOLTIPS.cohesion} />
                  </span>,
                  group.cohesion.toFixed(2),
                ] as [ReactNode, ReactNode],
              ]
            : []),
          ...(group.internal_edges != null
            ? [
                [
                  "Internal / external edges",
                  `${group.internal_edges} / ${group.external_edges ?? 0}`,
                ] as [ReactNode, ReactNode],
              ]
            : []),
          ["Label source", group.label_source.replace("_", " ")],
          ["Changes (365 days)", group.churn_365d.toLocaleString()],
          ["Last changed", formatDate(group.last_changed)],
          ["Commits", group.commit_count.toLocaleString()],
        ]}
      />
      {group.entry_points.length > 0 ? (
        <Section title="Entry points">
          <ul className="flex flex-col gap-1 text-xs">
            {group.entry_points.map((ep) => (
              <li key={`${ep.path}-${ep.kind}`}>
                <span className="font-mono text-text">{ep.path}</span>
                <span className="text-text-muted">
                  {" "}
                  · {ENTRY_KIND_LABEL[ep.kind] ?? ep.kind} · {ep.evidence}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
      {outgoing.length > 0 ? (
        <Section title="Imports">
          <ul className="flex flex-col gap-0.5 text-xs">
            {outgoing.map((e) => (
              <li key={e.target}>
                <button
                  type="button"
                  className="text-accent hover:underline"
                  onClick={() => props.onSelect(groupNodeId(e.target))}
                >
                  → {labelOf(e.target)}
                </button>
                <span className="cp-stat text-text-muted"> ({e.import_count})</span>
                {e.in_group_cycle || e.in_file_cycle ? (
                  <span className="text-danger"> ↻</span>
                ) : null}
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
      {incoming.length > 0 ? (
        <Section title="Imported by">
          <ul className="flex flex-col gap-0.5 text-xs">
            {incoming.map((e) => (
              <li key={e.source}>
                <button
                  type="button"
                  className="text-accent hover:underline"
                  onClick={() => props.onSelect(groupNodeId(e.source))}
                >
                  ← {labelOf(e.source)}
                </button>
                <span className="cp-stat text-text-muted"> ({e.import_count})</span>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
      {hidden.length > 0 ? (
        <Section title="Changes together with (no import)">
          <ul className="flex flex-col gap-0.5 text-xs">
            {hidden.map((h) => {
              const other = h.a === groupId ? h.b : h.a;
              return (
                <li key={other}>
                  <button
                    type="button"
                    className="text-warning hover:underline"
                    onClick={() => props.onSelect(groupNodeId(other))}
                  >
                    {labelOf(other)}
                  </button>
                  <span className="text-text-muted">
                    {" "}
                    · {h.pair_count} pair{h.pair_count === 1 ? "" : "s"} · up to{" "}
                    {formatPercent(h.max_degree)}
                  </span>
                </li>
              );
            })}
          </ul>
        </Section>
      ) : null}
      <Section title="Top files">
        <FileList
          data={data}
          indices={rankFiles(data, tree.allFiles).slice(0, TOP_FILES)}
          onSelect={props.onSelect}
        />
      </Section>
      <div className="flex flex-wrap items-center gap-3">
        <Link
          to={withShare(`/repos/${data.repo_id}/explore?view=files`, share)}
          className="text-xs text-accent hover:underline"
        >
          Explore files
        </Link>
        {group.base_path ? (
          <ExternalSourceLink href={treeUrl(data.source, group.base_path)} data={data} />
        ) : null}
      </div>
    </div>
  );
}

function FolderPanel(props: PanelProps & { groupId: string; relPath: string }) {
  const { data, trees, groupId, relPath, graph } = props;
  const root = trees.get(groupId);
  const folder = root ? findFolder(root, relPath) : null;
  const group = groupById(data, groupId);
  if (!folder || !group)
    return <p className="text-xs text-text-muted">This folder is no longer on the map.</p>;
  const id = folderNodeId(groupId, relPath);
  const vnode = graph.byId.get(id);
  const fullDir = group.base_path ? `${group.base_path}/${relPath}` : relPath;
  return (
    <div className="flex flex-col gap-4">
      <header>
        <h3 className="break-all font-mono text-sm text-text-heading">{fullDir}/</h3>
        <p className="text-xs text-text-muted">in {group.label}</p>
      </header>
      <ActionRow
        id={id}
        expandable={vnode?.expandable}
        expanded={vnode?.expanded}
        actions={props}
      />
      <Facts
        rows={[
          ["Files", folder.allFiles.length.toLocaleString()],
          ["Lines of code", sumLoc(data, folder.allFiles).toLocaleString()],
          ["Changes (365 days)", sumChurn(data, folder.allFiles).toLocaleString()],
          ["Last changed", formatDate(maxLastChanged(data, folder.allFiles))],
        ]}
      />
      <Section title="Top files">
        <FileList
          data={data}
          indices={rankFiles(data, folder.allFiles).slice(0, TOP_FILES)}
          onSelect={props.onSelect}
        />
      </Section>
      <ExternalSourceLink href={treeUrl(data.source, fullDir)} data={data} />
    </div>
  );
}

function FilePanel(props: PanelProps & { path: string }) {
  const { data, indexByPath, path, share } = props;
  const index = indexByPath.get(path);
  if (index == null)
    return <p className="text-xs text-text-muted">This file isn't in the analysed snapshot.</p>;
  const file = data.files[index];
  const group = groupById(data, file.group_id);
  const entries = data.groups
    .flatMap((g) => g.entry_points)
    .filter((ep) => ep.file_index === index);
  return (
    <div className="flex flex-col gap-4">
      <header>
        <h3 className="break-all font-mono text-sm text-text-heading">{file.path}</h3>
        {group ? <p className="text-xs text-text-muted">in {group.label}</p> : null}
      </header>
      <ActionRow id={fileNodeId(file.path)} actions={props} />
      <Facts
        rows={[
          ["Lines of code", file.loc.toLocaleString()],
          ["Commits", file.commit_count.toLocaleString()],
          ["Changes (365 days)", file.churn_365d.toLocaleString()],
          ["Last changed", formatDate(file.last_changed)],
          ["Language", file.language],
          ["Test file", file.is_test ? "yes" : "no"],
        ]}
      />
      {entries.length > 0 ? (
        <Section title="Entry point">
          {entries.map((ep) => (
            <p key={ep.kind} className="text-xs text-text-muted">
              {ENTRY_KIND_LABEL[ep.kind] ?? ep.kind} · {ep.evidence}
            </p>
          ))}
        </Section>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <Link
          to={withShare(
            `/repos/${data.repo_id}/explore?view=impact&path=${encodeURIComponent(file.path)}`,
            share,
          )}
          className="text-xs text-accent hover:underline"
        >
          Blast radius
        </Link>
        <ExternalSourceLink href={blobUrl(data.source, file.path)} data={data} />
      </div>
    </div>
  );
}

function MorePanel(props: PanelProps & { hidden: TreeChild[] }) {
  const { data, hidden } = props;
  return (
    <div className="flex flex-col gap-3">
      <h3 className="font-display text-lg text-text-heading">{hidden.length} more items</h3>
      <ul className="flex flex-col gap-1 text-xs">
        {hidden.map((child) =>
          child.kind === "folder" ? (
            <li key={child.folder.id} className="flex justify-between gap-2">
              <span className="truncate font-mono text-text">{child.folder.name}/</span>
              <span className="cp-stat shrink-0 text-text-muted">
                {child.folder.allFiles.length} files
              </span>
            </li>
          ) : (
            <li key={child.index} className="flex items-center justify-between gap-2">
              <button
                type="button"
                className="min-w-0 truncate text-left font-mono text-accent hover:underline"
                onClick={() => props.onSelect(fileNodeId(data.files[child.index].path))}
              >
                {data.files[child.index].path.split("/").pop()}
              </button>
              <span className="cp-stat shrink-0 text-text-muted">
                {data.files[child.index].loc.toLocaleString()} LOC
              </span>
            </li>
          ),
        )}
      </ul>
    </div>
  );
}

function EdgePanel(props: PanelProps & { edge: VisibleEdge }) {
  const { edge, graph, data, aiOn, aiVerbs } = props;
  const name = (id: string) => graph.byId.get(id)?.label ?? id;
  const verb = edgeVerb(edge, aiOn, aiVerbs);
  const pairList = (
    <ul className="flex flex-col gap-0.5">
      {edge.filePairs.map(([a, b]) => (
        <li
          key={`${a}-${b}`}
          className="truncate font-mono text-2xs text-text-muted"
          title={`${data.files[a].path} → ${data.files[b].path}`}
        >
          {data.files[a].path} {edge.kind === "hidden" ? "↔" : "→"} {data.files[b].path}
        </li>
      ))}
    </ul>
  );
  if (edge.kind === "hidden") {
    return (
      <div className="flex flex-col gap-3">
        <h3 className="font-display text-lg text-text-heading">Hidden co-change</h3>
        <p className="text-sm text-text">
          <span className="font-medium">{name(edge.source)}</span> and{" "}
          <span className="font-medium">{name(edge.target)}</span> change together with no import
          between them.
        </p>
        <Facts
          rows={[
            ["File pairs", edge.count.toLocaleString()],
            ["Strongest coupling", formatPercent(edge.maxDegree ?? 0)],
            ["Shared revisions", (edge.sharedRevs ?? 0).toLocaleString()],
          ]}
        />
        <p className="text-xs text-text-muted">{TOOLTIPS.mapHiddenEdge}</p>
        <Section title="Underlying pairs">{pairList}</Section>
      </div>
    );
  }
  if (edge.kind === "import") {
    return (
      <div className="flex flex-col gap-3">
        <h3 className="font-display text-lg text-text-heading">Imports</h3>
        <p className="text-sm text-text">
          <span className="font-medium">{name(edge.source)}</span> imports{" "}
          <span className="font-medium">{name(edge.target)}</span>
        </p>
        <Facts rows={[["Import links", edge.count.toLocaleString()]]} />
        {edge.inCycle ? <Badge tone="high">part of a dependency cycle</Badge> : null}
        {verb ? (
          <p className="text-xs text-text-muted">
            AI verb: <em className="text-text">"{verb}"</em> <span className="text-info">(AI)</span>{" "}
            — {MAP_COPY.aiVerbCaveat}
          </p>
        ) : null}
        <Section
          title={`Underlying imports${edge.count > edge.filePairs.length ? ` (first ${edge.filePairs.length})` : ""}`}
        >
          {pairList}
        </Section>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <h3 className="font-display text-lg text-text-heading">
        {edge.kind === "actor" ? "Entry" : "Runs"}
      </h3>
      <p className="text-sm text-text">
        {name(edge.source)} → {name(edge.target)}
      </p>
      <p className="text-xs text-text-muted">
        {edge.kind === "actor" ? TOOLTIPS.mapActor : HONESTY.mapInfraHeuristic}
      </p>
    </div>
  );
}

function ActorPanel({ data }: PanelProps) {
  if (!data.actor) return null;
  const kinds = new Set(data.actor.entry_kinds);
  return (
    <div className="flex flex-col gap-3">
      <h3 className="font-display text-lg text-text-heading">{data.actor.label}</h3>
      <p className="text-xs text-text-muted">{TOOLTIPS.mapActor}</p>
      {data.actor.group_ids.map((gid) => {
        const group = groupById(data, gid);
        if (!group) return null;
        return (
          <Section key={gid} title={group.label}>
            <ul className="flex flex-col gap-0.5 text-xs">
              {group.entry_points
                .filter((ep) => kinds.has(ep.kind))
                .map((ep) => (
                  <li key={`${ep.path}-${ep.kind}`}>
                    <span className="font-mono text-text">{ep.path}</span>
                    <span className="text-text-muted">
                      {" "}
                      · {ENTRY_KIND_LABEL[ep.kind] ?? ep.kind}
                    </span>
                  </li>
                ))}
            </ul>
          </Section>
        );
      })}
    </div>
  );
}

function InfraPanel(props: PanelProps & { infraId: string }) {
  const { data, infraId } = props;
  const item = data.infra.find((i) => i.id === infraId);
  if (!item) return null;
  return (
    <div className="flex flex-col gap-3">
      <h3 className="font-display text-lg text-text-heading">{item.label}</h3>
      <p className="cp-label text-text-muted">{item.category}</p>
      <Section title="Evidence">
        <ul className="flex flex-col gap-0.5 text-xs text-text">
          {item.evidence.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      </Section>
      <Section title="Files">
        <ul className="flex flex-col gap-0.5">
          {item.paths.map((p) => {
            const href = blobUrl(data.source, p);
            return (
              <li key={p} className="truncate font-mono text-xs">
                {href ? (
                  <a
                    href={href}
                    target="_blank"
                    rel="noreferrer"
                    className="text-accent hover:underline"
                  >
                    {p}
                  </a>
                ) : (
                  <span className="text-text">{p}</span>
                )}
              </li>
            );
          })}
        </ul>
      </Section>
      {item.runs_group_ids.length > 0 ? (
        <Section title="Runs">
          <ul className="flex flex-col gap-0.5 text-xs">
            {item.runs_group_ids.map((gid) => (
              <li key={gid}>
                <button
                  type="button"
                  className="text-accent hover:underline"
                  onClick={() => props.onSelect(groupNodeId(gid))}
                >
                  {groupById(data, gid)?.label ?? gid}
                </button>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
      <HonestyNote variant="scope-limitation" text={HONESTY.mapInfraHeuristic} />
    </div>
  );
}

export function SidePanelContent(props: PanelProps) {
  const { selectedId, edges, graph } = props;
  if (selectedId.startsWith("e:")) {
    const edge = edges.find((e) => e.id === selectedId);
    return edge ? <EdgePanel {...props} edge={edge} /> : null;
  }
  const parsed = parseNodeId(selectedId);
  if (!parsed) return null;
  switch (parsed.kind) {
    case "group":
      return <GroupPanel {...props} groupId={parsed.groupId} />;
    case "folder":
      return <FolderPanel {...props} groupId={parsed.groupId} relPath={parsed.relPath} />;
    case "file":
      return <FilePanel {...props} path={parsed.path} />;
    case "more": {
      const vnode = graph.byId.get(selectedId);
      return vnode?.hiddenChildren ? <MorePanel {...props} hidden={vnode.hiddenChildren} /> : null;
    }
    case "actor":
      return <ActorPanel {...props} />;
    case "infra":
      return <InfraPanel {...props} infraId={parsed.infraId} />;
  }
}

/** Desktop: a right-hand panel inside the map container. (On narrow screens
 * the page renders the same content inside the app's Drawer instead.) */
export function MapSidePanel(props: PanelProps & { onClose: () => void }) {
  return (
    <aside
      data-map-export-exclude
      className="absolute top-0 right-0 z-20 flex h-full w-[360px] max-w-[85%] flex-col border-l border-border bg-bg-elevated"
      aria-label="Details"
    >
      <div className="flex items-center justify-end border-b border-border px-3 py-2">
        <button
          type="button"
          onClick={props.onClose}
          aria-label={MAP_COPY.closePanel}
          className="text-text-muted hover:text-text"
        >
          <X size={16} aria-hidden="true" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        <SidePanelContent {...props} />
      </div>
    </aside>
  );
}

export type { PanelProps };
