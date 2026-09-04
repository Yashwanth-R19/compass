import { useEffect, useMemo, useState } from "react";
import { Dialog as RadixDialog } from "radix-ui";
import { useNavigate, useParams } from "react-router-dom";
import { Search } from "lucide-react";
import { useMe, useMyRepos, useShowcaseRepos } from "../api/hooks";
import { useTheme } from "../theme/ThemeProvider";
import { requestNarrativeDrawerOpen } from "../lib/narrativeDrawerSignal";
import { Input } from "./ui/Input";

interface Command {
  id: string;
  group: string;
  label: string;
  hint?: string;
  run: () => void;
}

/**
 * ⌘K / Ctrl+K command palette (rebuild spec section 7.4) -- jump to any
 * surface of the current repo, any of your own repos, any showcase repo,
 * the explanation page, or the theme toggle. Also the discovery surface
 * for "what can this app even do" -- opening it with an empty query shows
 * every group at once, not just the current repo's surfaces.
 *
 * Mounted once in AppShell; the global keydown listener lives here so the
 * shortcut works from any route.
 */
export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const navigate = useNavigate();
  const { repoId } = useParams<{ repoId: string }>();
  const me = useMe();
  const myRepos = useMyRepos(1, 50);
  const showcase = useShowcaseRepos();
  const { toggleTheme } = useTheme();

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  function go(to: string) {
    navigate(to);
    setOpen(false);
    setQuery("");
  }

  const commands = useMemo<Command[]>(() => {
    const list: Command[] = [];

    if (repoId) {
      const surfaces: [string, string][] = [
        ["overview", "Overview"],
        ["guide", "Guide"],
        ["explore", "Explore"],
        ["findings", "Findings"],
        ["evolution", "Evolution"],
      ];
      for (const [path, label] of surfaces) {
        list.push({
          id: `surface-${path}`,
          group: "This repository",
          label,
          run: () => go(`/repos/${repoId}/${path}`),
        });
      }
      list.push({
        id: "explain-repo",
        group: "This repository",
        label: "Explain this repo",
        run: () => {
          requestNarrativeDrawerOpen();
          setOpen(false);
        },
      });
    }

    list.push({
      id: "explain",
      group: "Compass",
      label: "How it works",
      run: () => go("/how-it-works"),
    });
    list.push({
      id: "dashboard",
      group: "Compass",
      label: "Dashboard",
      run: () => go("/dashboard"),
    });
    list.push({
      id: "theme",
      group: "Compass",
      label: "Toggle theme",
      run: () => {
        toggleTheme();
        setOpen(false);
      },
    });

    if (me.data) {
      for (const repo of myRepos.data?.repos ?? []) {
        list.push({
          id: `my-${repo.id}`,
          group: "Your repositories",
          label: `${repo.owner}/${repo.name}`,
          run: () => go(`/repos/${repo.id}/overview`),
        });
      }
    }

    for (const repo of showcase.data?.repos ?? []) {
      list.push({
        id: `showcase-${repo.id}`,
        group: "Showcase",
        label: `${repo.owner}/${repo.name}`,
        hint: repo.hook,
        run: () => go(`/repos/${repo.id}/overview`),
      });
    }

    return list;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repoId, me.data, myRepos.data, showcase.data]);

  const normalized = query.trim().toLowerCase();
  const filtered = normalized
    ? commands.filter((c) => c.label.toLowerCase().includes(normalized))
    : commands;

  const groups = new Map<string, Command[]>();
  for (const c of filtered) {
    const arr = groups.get(c.group) ?? [];
    arr.push(c);
    groups.set(c.group, arr);
  }

  return (
    <RadixDialog.Root
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setQuery("");
      }}
    >
      <RadixDialog.Trigger asChild>
        <button
          type="button"
          className="cp-label inline-flex items-center gap-1.5 rounded-sm border border-border px-2 py-1 hover:border-border-strong hover:text-text"
          aria-label="Open command palette"
        >
          <Search size={12} aria-hidden="true" />
          <span className="hidden sm:inline">⌘K</span>
        </button>
      </RadixDialog.Trigger>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 bg-overlay" />
        <RadixDialog.Content className="fixed left-1/2 top-24 z-50 flex max-h-[60vh] w-full max-w-lg -translate-x-1/2 flex-col rounded-lg border border-border bg-bg-elevated shadow-lg">
          <RadixDialog.Title className="sr-only">Command palette</RadixDialog.Title>
          <RadixDialog.Description className="sr-only">
            Jump to a repository surface, your repositories, a showcase repository, or a Compass
            page.
          </RadixDialog.Description>
          <div className="border-b border-border p-3">
            <div className="relative">
              <Search
                size={14}
                aria-hidden="true"
                className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted"
              />
              <Input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Jump to…"
                aria-label="Search commands"
                className="pl-8"
              />
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-2">
            {filtered.length === 0 ? (
              <p className="px-2 py-4 text-center text-xs text-text-muted">No matches.</p>
            ) : (
              [...groups.entries()].map(([group, items]) => (
                <div key={group} className="mb-2 last:mb-0">
                  <p className="cp-label px-2 py-1 text-text-muted">{group}</p>
                  {items.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      onClick={c.run}
                      className="flex w-full items-center justify-between gap-2 rounded-sm px-2 py-1.5 text-left text-sm text-text hover:bg-bg-inset"
                    >
                      <span className="truncate font-mono">{c.label}</span>
                      {c.hint ? (
                        <span className="shrink-0 truncate text-xs text-text-muted">{c.hint}</span>
                      ) : null}
                    </button>
                  ))}
                </div>
              ))
            )}
          </div>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
