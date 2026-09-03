import { useState } from "react";
import { Dialog as RadixDialog } from "radix-ui";
import { Search, X } from "lucide-react";
import { Input } from "./ui/Input";
import { EMPTY_MESSAGES, GLOSSARY } from "../content/explainability";

/**
 * The header-triggered dialog listing Compass's OWN vocabulary
 * (`content/explainability.ts`'s `GLOSSARY`) — session 1 left a stub
 * button in `AppShell`; this is the real dialog it now opens.
 *
 * A deliberate duplication worth stating plainly, because it looks like a
 * bug if it isn't: this is a DIFFERENT thing from the repo-scoped Tour
 * glossary (`GET /repos/{id}/glossary`, vocabulary mined from the analysed
 * repository's own identifiers). The two share the word "glossary" and
 * nothing else — one explains Compass, the other explains the codebase
 * being analysed. The dialog says so explicitly (below the search field)
 * so a reader doesn't reach for this one expecting repository-specific
 * terms.
 *
 * Built on Radix `Dialog` directly (not the existing `Drawer`, which is a
 * right-edge slide-in panel — a searchable term list reads better as a
 * centered modal) for the same reasons `Drawer` already established: focus
 * is trapped inside while open, `Escape` closes it, and focus returns to
 * the trigger button on close, all handled by Radix rather than hand-rolled.
 */
export function GlossaryDialog() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const normalized = query.trim().toLowerCase();
  const filtered = normalized
    ? GLOSSARY.filter(
        (entry) =>
          entry.term.toLowerCase().includes(normalized) ||
          entry.body.toLowerCase().includes(normalized),
      )
    : GLOSSARY;

  return (
    <RadixDialog.Root
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setQuery("");
      }}
    >
      <RadixDialog.Trigger asChild>
        <button type="button" className="cp-label hover:text-text">
          Glossary
        </button>
      </RadixDialog.Trigger>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 bg-overlay" />
        <RadixDialog.Content className="fixed left-1/2 top-1/2 z-50 flex max-h-[80vh] w-full max-w-md -translate-x-1/2 -translate-y-1/2 flex-col rounded-lg border border-border bg-bg-elevated shadow-lg">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <RadixDialog.Title className="font-display text-lg text-text-heading">
              Glossary
            </RadixDialog.Title>
            <RadixDialog.Close aria-label="Close" className="text-text-muted hover:text-text">
              <X size={16} aria-hidden="true" />
            </RadixDialog.Close>
          </div>

          <div className="border-b border-border px-4 py-3">
            <div className="relative">
              <Search
                size={14}
                aria-hidden="true"
                className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted"
              />
              <Input
                type="text"
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search terms…"
                aria-label="Search the glossary"
                className="pl-8"
              />
            </div>
            <RadixDialog.Description className="mt-2 text-xs text-text-muted">
              Compass's own vocabulary. Looking for terms specific to the repository you're
              analysing instead? That's the glossary panel on its Tour tab.
            </RadixDialog.Description>
          </div>

          <dl className="flex-1 overflow-y-auto px-4 py-3">
            {filtered.length === 0 ? (
              <p className="text-xs text-text-muted">{EMPTY_MESSAGES.glossarySearchNoResults}</p>
            ) : (
              <div className="flex flex-col gap-3">
                {filtered.map((entry) => (
                  <div key={entry.term}>
                    <dt className="text-sm font-medium text-text-heading">{entry.term}</dt>
                    <dd className="mt-0.5 text-xs leading-relaxed text-text-muted">{entry.body}</dd>
                  </div>
                ))}
              </div>
            )}
          </dl>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
