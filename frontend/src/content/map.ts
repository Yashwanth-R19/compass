/**
 * Every user-facing string the Map surface renders, kept out of the
 * components (same convention as `content/explainability.ts`). Tooltip
 * definitions live in `TOOLTIPS.map*`; the infra caveat in
 * `HONESTY.mapInfraHeuristic`.
 */

export const MAP_COPY = {
  intro:
    "How this repository is put together, drawn from its import graph and commit history. Every box and arrow is computed, nothing is generated.",
  loading: "Drawing the map…",
  layingOut: "Laying out…",
  emptyTitle: "Nothing to map",
  emptyMessage: "This repository has no files with detected structure to draw.",
  archivedTitle: "Map unavailable",
  archivedMessage:
    "This analysis was archived to save storage, so its file-level structure is gone. Re-analyse the repository to rebuild the map.",
  groupBy: "Group by",
  groupingSubsystem: "Subsystems",
  groupingFolder: "Folders",
  view: "View",
  viewDiagram: "Diagram",
  viewList: "List",
  activity: "Activity",
  entryPoints: "Entry points",
  readingOrder: "Reading order",
  weakLinks: "Weak links",
  motionOn: "Motion on",
  motionOff: "Motion off",
  motionReduced: "Motion is off because your system prefers reduced motion",
  describeWithAi: "Describe with AI",
  aiLabels: "AI labels",
  aiLoading: "Asking the AI to label the map…",
  exportLabel: "Export",
  downloadPng: "Download PNG",
  downloadSvg: "Download SVG",
  copyMermaid: "Copy Mermaid",
  mermaidCopied: "Mermaid copied to clipboard",
  clipboardFailed: "Couldn't access the clipboard",
  exportFailed: "Couldn't export the map",
  fullscreen: "Fullscreen",
  exitFullscreen: "Exit fullscreen",
  searchPlaceholder: "Find a group, folder or file…",
  searchLabel: "Search the map",
  noMatches: "No matches",
  pathLabel: "Path",
  pathFrom: "From",
  pathTo: "To",
  pathFind: "Find path",
  pathClear: "Clear",
  pathPick: "Choose a box…",
  closePanel: "Close panel",
  legend: "Legend",
  legendImport: "imports (thicker = more)",
  legendHidden: "changes together, no import",
  legendCycle: "in a dependency cycle",
  legendEntry: "has entry points",
  legendQuiet: "Quiet",
  legendBusy: "Busy",
  legendActivityCaption: "Changes in the last 365 days, relative to the busiest box on screen",
  aiEyebrow: "AI-written summary. Boxes and arrows are computed, not generated",
  aiVerbCaveat: "AI-suggested from names only, not proven by the code.",
  aiChip: "AI",
  computedPrefix: "computed:",
  dismiss: "Dismiss",
} as const;

/** Mirrors NarrativeDrawer's REASON_COPY wording (kept here rather than
 * imported from inside that component). */
export const MAP_AI_REASON_COPY: Record<string, string> = {
  no_keys: "This deployment has no AI provider keys configured.",
  pool_exhausted: "Every configured provider key is temporarily rate-limited. Try again shortly.",
  rejected: "The generated labels didn't pass Compass's own grounding check and were discarded.",
  disabled: "The underlying analysis for this repo isn't finished yet.",
};

export function aiUnavailableLine(reason: string | null | undefined): string {
  const detail = reason ? MAP_AI_REASON_COPY[reason] : undefined;
  return detail
    ? `AI labels unavailable. ${detail}`
    : "AI labels unavailable. The computed map is unaffected.";
}

export function aiRateLimitedLine(seconds: number): string {
  return `AI labelling is rate-limited. Try again in ${seconds}s.`;
}

export function foldedNote(n: number): string {
  return `${n} smaller folders are folded into "Other" to keep the map readable.`;
}

export function truncatedNote(total: number, cap: number): string {
  return `This repository has ${total.toLocaleString()} import links; the map draws the first ${cap.toLocaleString()} (cycle and cross-group links first).`;
}

export function weakHiddenNote(n: number): string {
  return `${n} single-import link${n === 1 ? " is" : "s are"} hidden. Turn on "Weak links" to show ${n === 1 ? "it" : "them"}.`;
}

export function pathResultLine(
  direction: "forward" | "reverse" | null,
  from: string,
  to: string,
  steps: number,
): string {
  if (direction === "forward") {
    return `${from} reaches ${to} in ${steps} step${steps === 1 ? "" : "s"} through imports.`;
  }
  if (direction === "reverse") {
    return `No import path from ${from} to ${to}, but ${to} reaches ${from} in ${steps} step${steps === 1 ? "" : "s"}.`;
  }
  return "No import path connects these at the current zoom level. Try expanding groups.";
}

export const ENTRY_KIND_LABEL: Record<string, string> = {
  web_server: "web server",
  ui_root: "UI root",
  cli: "CLI",
  test_root: "test root",
  build: "build",
  graph_inferred: "inferred from the import graph",
};
