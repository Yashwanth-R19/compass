import { createContext, useContext } from "react";
import type { DiagramAiGroupOut, DiagramResponse } from "../../api/types";
import type { ActivityBucket } from "../../lib/diagram/activity";
import type { MapLens } from "../../lib/diagram/urlState";

/** Everything a React Flow node/edge component needs beyond its own layout
 * data. React Flow renders nodes outside our component tree's prop flow, so
 * dynamic state (dimming, selection, AI labels, lens) travels through this
 * context instead of being baked into node data -- which also means a
 * focus or lens change never forces an ELK relayout. */
export interface MapContextValue {
  data: DiagramResponse;
  lens: MapLens;
  aiOn: boolean;
  aiGroups: Map<string, DiagramAiGroupOut>;
  aiBands: Map<number, string>;
  /** Keyed `${fromGroupId}>${toGroupId}`. */
  aiVerbs: Map<string, string>;
  activity: Map<string, ActivityBucket>;
  /** Node and edge ids to keep at full opacity; null = nothing dimmed. */
  emphasis: Set<string> | null;
  selectedId: string | null;
  /** Tour stop positions (1-based, as the Guide numbers them) per visible node id. */
  tourSteps: Map<string, number[]>;
  /** How many child boxes each visible container currently shows. */
  childCount: Map<string, number>;
  onToggleExpand: (id: string) => void;
  onSelect: (id: string) => void;
}

export const MapContext = createContext<MapContextValue | null>(null);

export function useMapContext(): MapContextValue {
  const ctx = useContext(MapContext);
  if (!ctx) throw new Error("useMapContext must be used inside MapContext.Provider");
  return ctx;
}
