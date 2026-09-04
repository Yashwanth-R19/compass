import { Check, X } from "lucide-react";
import { useMe, useMyRepos } from "../api/hooks";
import {
  useChecklistDismissed,
  useChecklistFlags,
  dismissChecklistForever,
} from "../lib/checklist";
import { Card } from "./ui/Card";

interface ChecklistItem {
  id: string;
  label: string;
  done: boolean;
}

/**
 * The persistent, resumable checklist (rebuild spec section 7.3) --
 * non-linear, never modal, never a spotlight overlay. Shown in the
 * dashboard sidebar and beneath the landing hero for logged-in users;
 * dismissible forever, and never shown again once dismissed. Every item is
 * derived from real state (`lib/checklist.ts`'s own docstring explains
 * which items read the server directly and which use a locally-remembered
 * "did this at least once" flag, and why) -- never a click counter.
 */
export function GetStartedChecklist() {
  const me = useMe();
  const myRepos = useMyRepos(1, 50);
  const flags = useChecklistFlags();
  const dismissed = useChecklistDismissed();

  if (!me.data || dismissed) return null;

  const analysedRepo = (myRepos.data?.repos ?? []).some((r) => r.latest_run_status === "ready");

  const items: ChecklistItem[] = [
    { id: "analyse", label: "Analyse a repository", done: analysedRepo },
    { id: "finding", label: "Open a finding", done: flags.has("opened_finding") },
    { id: "who", label: "See who to ask about a file", done: flags.has("asked_who_to_ask") },
    { id: "narrative", label: "Ask for an AI explanation", done: flags.has("asked_narrative") },
    { id: "share", label: "Share a run", done: flags.has("shared_run") },
  ];

  const doneCount = items.filter((i) => i.done).length;

  return (
    <Card
      eyebrow="Get started"
      title={`${doneCount} of ${items.length}`}
      action={
        <button
          type="button"
          onClick={dismissChecklistForever}
          aria-label="Dismiss checklist"
          className="text-text-muted hover:text-text"
        >
          <X size={14} aria-hidden="true" />
        </button>
      }
    >
      <ul className="flex flex-col gap-2">
        {items.map((item) => (
          <li key={item.id} className="flex items-center gap-2 text-sm">
            <span
              className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
                item.done ? "border-accent bg-accent text-accent-contrast" : "border-border-strong"
              }`}
              aria-hidden="true"
            >
              {item.done ? <Check size={10} /> : null}
            </span>
            <span className={item.done ? "text-text-muted line-through" : "text-text"}>
              {item.label}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
