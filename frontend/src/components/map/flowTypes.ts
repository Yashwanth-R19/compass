import { memo } from "react";
import type { VisibleNode } from "../../lib/diagram/visible";
import { DiagramEdge } from "./DiagramEdge";
import {
  ActorNode,
  BandNode,
  FileNode,
  FolderNode,
  GroupNode,
  InfraNode,
  MoreNode,
} from "./MapNodes";

/** React Flow registries for the Map. Keys are prefixed ("map*") so none
 * collides with React Flow's own built-in node types (it ships a "group"). */
export const mapNodeTypes = {
  mapGroup: memo(GroupNode),
  mapFolder: memo(FolderNode),
  mapFile: memo(FileNode),
  mapMore: memo(MoreNode),
  mapActor: memo(ActorNode),
  mapInfra: memo(InfraNode),
  mapBand: memo(BandNode),
};

export const mapEdgeTypes = { diagram: memo(DiagramEdge) };

export const NODE_TYPE_FOR_KIND: Record<VisibleNode["kind"], keyof typeof mapNodeTypes> = {
  group: "mapGroup",
  folder: "mapFolder",
  file: "mapFile",
  more: "mapMore",
  actor: "mapActor",
  infra: "mapInfra",
};
