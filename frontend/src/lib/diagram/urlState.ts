import type { DiagramGrouping } from "../../api/types";

export type MapLens = "none" | "activity";
export type MapView = "diagram" | "list";

export interface MapUrlState {
  grouping: DiagramGrouping;
  lens: MapLens;
  expanded: string[];
  focus: string | null;
  path: [string, string] | null;
  ai: boolean;
  entry: boolean;
  tour: boolean;
  weak: boolean;
  /** null = not chosen; the page picks a default by viewport width. */
  view: MapView | null;
  find: string | null;
}

/** Every param this module owns -- anything else on the URL (`share` above
 * all) is preserved untouched by `writeMapUrlState`. */
const OWNED = [
  "grouping",
  "lens",
  "expanded",
  "focus",
  "path",
  "ai",
  "entry",
  "tour",
  "weak",
  "view",
  "find",
];

export function readMapUrlState(params: URLSearchParams): MapUrlState {
  const pathParam = params.get("path");
  const sep = pathParam ? pathParam.indexOf("~") : -1;
  const view = params.get("view");
  return {
    grouping: params.get("grouping") === "folder" ? "folder" : "subsystem",
    lens: params.get("lens") === "activity" ? "activity" : "none",
    expanded: [...new Set(params.getAll("expanded"))].sort(),
    focus: params.get("focus"),
    path: pathParam && sep > 0 ? [pathParam.slice(0, sep), pathParam.slice(sep + 1)] : null,
    ai: params.get("ai") === "1",
    entry: params.get("entry") === "1",
    tour: params.get("tour") === "1",
    weak: params.get("weak") === "1",
    view: view === "list" || view === "diagram" ? view : null,
    find: params.get("find"),
  };
}

/** A NEW URLSearchParams: the previous params minus everything this module
 * owns, plus `state` serialised with defaults omitted. */
export function writeMapUrlState(prev: URLSearchParams, state: MapUrlState): URLSearchParams {
  const next = new URLSearchParams(prev);
  for (const key of OWNED) next.delete(key);
  if (state.grouping !== "subsystem") next.set("grouping", state.grouping);
  if (state.lens !== "none") next.set("lens", state.lens);
  for (const id of state.expanded) next.append("expanded", id);
  if (state.focus) next.set("focus", state.focus);
  if (state.path) next.set("path", `${state.path[0]}~${state.path[1]}`);
  if (state.ai) next.set("ai", "1");
  if (state.entry) next.set("entry", "1");
  if (state.tour) next.set("tour", "1");
  if (state.weak) next.set("weak", "1");
  if (state.view) next.set("view", state.view);
  if (state.find) next.set("find", state.find);
  return next;
}
