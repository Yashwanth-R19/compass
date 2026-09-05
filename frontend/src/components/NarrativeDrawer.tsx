import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";
import { useNarrative } from "../api/hooks";
import { Button } from "./ui/Button";
import { Drawer } from "./ui/Drawer";
import { Tooltip } from "./ui/Tooltip";
import { Skeleton } from "./ui/Skeleton";
import { GlareHover } from "../reactbits/GlareHover";
import { markChecklistFlag } from "../lib/checklist";
import { onNarrativeDrawerOpenRequested } from "../lib/narrativeDrawerSignal";

/**
 * The AI explanation button + drawer (rebuild spec D17/section 8.1) --
 * REPLACES the old three-surface, globally-toggled `NarrativeBlock`. One
 * explicit "Explain this repo" action, per repo, costing nothing until
 * clicked (rule 3: every page is fully usable, at zero request cost, with
 * this drawer never opened -- `useNarrative`'s own `enabled` flag only
 * turns true once `open` has been true at least once).
 */
export function NarrativeDrawer({
  repoId,
  share,
  keysConfigured = true,
}: {
  repoId: string;
  share?: string;
  /** Whether this deployment has any narrative provider keys configured at
   * all. Unknown ahead of a real request (there's no cheap "are keys
   * configured" endpoint), so this defaults to `true` -- the drawer opens,
   * fires the request, and the `no_keys` reason renders the same quiet
   * unavailable line an actual empty pool would. The one place this can be
   * set `false` up front is a caller that already knows from another
   * response this run's narrative is unavailable for that reason. */
  keysConfigured?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [everOpened, setEverOpened] = useState(false);
  const narrative = useNarrative(repoId, everOpened, share);

  function handleOpen() {
    setEverOpened(true);
    setOpen(true);
    markChecklistFlag("asked_narrative");
  }

  // The ⌘K palette's "Explain this repo" entry (section 8.1) opens THIS
  // instance via the shared signal, since the palette has no direct
  // reference to whichever NarrativeDrawer is currently mounted.
  useEffect(() => {
    if (!keysConfigured) return;
    return onNarrativeDrawerOpenRequested(handleOpen);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keysConfigured]);

  const trigger = (
    <Button
      type="button"
      variant="secondary"
      size="sm"
      onClick={handleOpen}
      disabled={!keysConfigured}
      aria-label="Explain this repo"
    >
      <Sparkles size={13} aria-hidden="true" />
      Explain this repo
    </Button>
  );

  return (
    <>
      {keysConfigured ? (
        <GlareHover className="inline-flex rounded-sm">{trigger}</GlareHover>
      ) : (
        <Tooltip content="AI explanations aren't configured for this deployment">
          {/* A disabled native button still receives hover in most
              browsers, but wrapping it removes any doubt Radix's trigger
              actually gets the pointer events. */}
          <span className="inline-flex">{trigger}</span>
        </Tooltip>
      )}

      <Drawer open={open} onOpenChange={setOpen} title="Explain this repo">
        <NarrativeDrawerContent
          isPending={narrative.isPending || narrative.isFetching}
          isError={narrative.isError}
          available={narrative.data?.available}
          reason={narrative.data?.reason}
          content={narrative.data?.content}
          provider={narrative.data?.provider}
          model={narrative.data?.model}
        />
      </Drawer>
    </>
  );
}

// One short, honest sentence per `NarrativeUnavailableReason` -- `no_keys`
// specifically is worth distinguishing from the others in the UI: it means
// this DEPLOYMENT has no provider keys configured at all (COMPASS_GEMINI_KEYS/
// COMPASS_GROQ_KEYS unset), not that a request failed, so the generic
// "try again later" framing the other reasons use would be misleading here.
const REASON_COPY: Record<string, string> = {
  no_keys: "This deployment has no AI provider keys configured.",
  pool_exhausted: "Every configured provider key is temporarily rate-limited. Try again shortly.",
  rejected: "The generated text didn't pass Compass's own grounding check and was discarded.",
  disabled: "The underlying analysis for this repo isn't finished yet.",
};

function NarrativeDrawerContent({
  isPending,
  isError,
  available,
  reason,
  content,
  provider,
  model,
}: {
  isPending: boolean;
  isError: boolean;
  available: boolean | undefined;
  reason: string | null | undefined;
  content: string | null | undefined;
  provider: string | null | undefined;
  model: string | null | undefined;
}) {
  if (isPending) {
    return (
      <div className="flex flex-col gap-2">
        <Skeleton className="h-3 w-2/3" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-1/2" />
      </div>
    );
  }

  if (isError || !available) {
    return (
      <div className="flex flex-col gap-1">
        <p className="text-sm text-text-muted">
          Narrative unavailable — the computed data across this repo's pages is unaffected.
        </p>
        {reason && REASON_COPY[reason] ? (
          <p className="text-xs text-text-muted">{REASON_COPY[reason]}</p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-info bg-info-bg p-3">
      <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-info">
        Generated phrasing of the metrics Compass computed — the numbers themselves are computed,
        not generated{provider && model ? ` · ${provider}/${model}` : ""}
      </p>
      <p className="text-sm leading-relaxed text-text">{content}</p>
    </div>
  );
}
