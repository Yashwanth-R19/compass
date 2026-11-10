import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { DiagramAiGroupOut, DiagramResponse } from "../../api/types";
import { groupById, groupColor } from "../../lib/diagram/display";
import { fileNodeId, groupNodeId } from "../../lib/diagram/ids";
import { orderedChildren, type TreeFolder } from "../../lib/diagram/tree";
import { formatCompact } from "../../lib/format";

/** The same computed map as a nested outline: bands -> groups -> folders ->
 * files, with each group's import/hidden relationships spelled out. The
 * screen-reader path and the phone default. Tapping a row opens details. */
export function MapListView({
  data,
  trees,
  initialExpanded,
  aiOn,
  aiGroups,
  onSelect,
}: {
  data: DiagramResponse;
  trees: Map<string, TreeFolder>;
  initialExpanded: string[];
  aiOn: boolean;
  aiGroups: Map<string, DiagramAiGroupOut>;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState<Set<string>>(() => new Set(initialExpanded));
  const cap = data.caps.max_children_visible;

  function toggle(id: string) {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function renderFolder(folder: TreeFolder, depth: number) {
    const children = orderedChildren(folder, data);
    const shown = open.has(`all:${folder.id}`) ? children : children.slice(0, cap);
    const rest = children.length - shown.length;
    return (
      <ul className="flex flex-col gap-0.5" style={{ paddingLeft: depth > 0 ? 16 : 0 }}>
        {shown.map((child) => {
          if (child.kind === "folder") {
            const f = child.folder;
            const isOpen = open.has(f.id);
            const Icon = isOpen ? ChevronDown : ChevronRight;
            return (
              <li key={f.id}>
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    aria-expanded={isOpen}
                    aria-label={`${isOpen ? "Collapse" : "Expand"} ${f.name}`}
                    onClick={() => toggle(f.id)}
                    className="inline-flex h-5 w-5 items-center justify-center text-text-muted hover:text-accent"
                  >
                    <Icon size={13} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    onClick={() => onSelect(f.id)}
                    className="truncate text-left font-mono text-xs text-text hover:underline"
                  >
                    {f.name}/
                  </button>
                  <span className="cp-stat text-2xs text-text-muted">
                    {f.allFiles.length} files
                  </span>
                </div>
                {isOpen ? renderFolder(f, depth + 1) : null}
              </li>
            );
          }
          const file = data.files[child.index];
          return (
            <li key={file.i} className="flex items-center gap-1.5 pl-6">
              <button
                type="button"
                onClick={() => onSelect(fileNodeId(file.path))}
                className="truncate text-left font-mono text-xs text-accent hover:underline"
              >
                {file.path.split("/").pop()}
              </button>
              <span className="cp-stat text-2xs text-text-muted">
                {file.loc.toLocaleString()} LOC
              </span>
            </li>
          );
        })}
        {rest > 0 ? (
          <li className="pl-6">
            <button
              type="button"
              onClick={() => toggle(`all:${folder.id}`)}
              className="text-xs text-text-muted underline hover:text-text"
            >
              +{rest} more
            </button>
          </li>
        ) : null}
      </ul>
    );
  }

  const labelOf = (gid: string) => groupById(data, gid)?.label ?? gid;

  return (
    <div className="flex flex-col gap-6">
      {data.layers.map((layer) => {
        const groups = layer.group_ids
          .map((gid) => groupById(data, gid))
          .filter((g): g is NonNullable<typeof g> => g !== null);
        if (layer.kind === "actor" || layer.kind === "infra") {
          const items =
            layer.kind === "actor"
              ? data.actor
                ? [{ id: "actor", label: data.actor.label }]
                : []
              : data.infra.map((i) => ({ id: i.id, label: i.label }));
          return (
            <section key={layer.index} aria-label={layer.label}>
              <h3 className="cp-label mb-2 text-text-muted">{layer.label}</h3>
              <ul className="flex flex-wrap gap-2">
                {items.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={() => onSelect(item.id)}
                      className="rounded-sm border border-border px-2 py-1 text-xs text-text hover:border-accent"
                    >
                      {item.label}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          );
        }
        return (
          <section key={layer.index} aria-label={layer.label}>
            <h3 className="cp-label mb-2 text-text-muted">{layer.label}</h3>
            <ul className="flex flex-col gap-2">
              {groups.map((g) => {
                const id = groupNodeId(g.id);
                const isOpen = open.has(id);
                const Icon = isOpen ? ChevronDown : ChevronRight;
                const tree = trees.get(g.id);
                const friendly = aiOn ? aiGroups.get(g.id)?.friendly_name : null;
                const outgoing = data.group_edges.filter((e) => e.source === g.id);
                const incoming = data.group_edges.filter((e) => e.target === g.id);
                const hidden = data.hidden_group_edges.filter((h) => h.a === g.id || h.b === g.id);
                return (
                  <li
                    key={g.id}
                    className="rounded-md border border-border bg-bg-elevated p-3"
                    style={{ boxShadow: `inset 3px 0 0 ${groupColor(data, g.id)}` }}
                  >
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        aria-expanded={isOpen}
                        aria-label={`${isOpen ? "Collapse" : "Expand"} ${g.label}`}
                        onClick={() => toggle(id)}
                        className="inline-flex h-6 w-6 items-center justify-center rounded-xs border border-border text-text-muted hover:text-accent"
                      >
                        <Icon size={14} aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        onClick={() => onSelect(id)}
                        className="min-w-0 flex-1 text-left"
                      >
                        <span className="block truncate text-sm font-semibold text-text-heading">
                          {friendly ?? g.label}
                          {friendly ? <span className="ml-1 text-2xs text-info">(AI)</span> : null}
                        </span>
                        <span className="cp-stat block text-2xs text-text-muted">
                          {g.file_count} files · {formatCompact(g.total_loc)} LOC
                          {g.entry_points.length > 0 ? " · ▲ entry" : ""}
                          {g.in_group_cycle ? " · ↻ cycle" : ""}
                        </span>
                      </button>
                    </div>
                    <div className="mt-2 flex flex-col gap-0.5 text-xs text-text-muted">
                      {outgoing.length > 0 ? (
                        <p>
                          Imports:{" "}
                          {outgoing
                            .map((e) => `${labelOf(e.target)} (${e.import_count})`)
                            .join(", ")}
                        </p>
                      ) : null}
                      {incoming.length > 0 ? (
                        <p>
                          Imported by:{" "}
                          {incoming
                            .map((e) => `${labelOf(e.source)} (${e.import_count})`)
                            .join(", ")}
                        </p>
                      ) : null}
                      {hidden.length > 0 ? (
                        <p className="text-warning">
                          Changes with (no import):{" "}
                          {hidden.map((h) => labelOf(h.a === g.id ? h.b : h.a)).join(", ")}
                        </p>
                      ) : null}
                    </div>
                    {isOpen && tree ? <div className="mt-2">{renderFolder(tree, 0)}</div> : null}
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
