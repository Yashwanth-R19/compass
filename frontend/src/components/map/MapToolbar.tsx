import type { ReactNode } from "react";
import {
  Download,
  Flame,
  ListOrdered,
  LogIn,
  Maximize2,
  Minimize2,
  Pause,
  Play,
  Sparkles,
  Spline,
} from "lucide-react";
import type { DiagramGrouping } from "../../api/types";
import { MAP_COPY } from "../../content/map";
import type { MapView } from "../../lib/diagram/urlState";
import { GlareHover } from "../../reactbits/GlareHover";
import { Button } from "../ui/Button";
import { DropdownMenu } from "../ui/DropdownMenu";
import { SegmentedControl } from "../ui/SegmentedControl";

function Toggle({
  pressed,
  onClick,
  icon,
  children,
  disabled,
  title,
}: {
  pressed: boolean;
  onClick: () => void;
  icon: ReactNode;
  children: ReactNode;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <Button
      type="button"
      size="sm"
      variant="secondary"
      aria-pressed={pressed}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={pressed ? "!border-accent !text-accent" : ""}
    >
      {icon}
      {children}
    </Button>
  );
}

export function MapToolbar(props: {
  grouping: DiagramGrouping;
  onGrouping: (g: DiagramGrouping) => void;
  view: MapView;
  onView: (v: MapView) => void;
  activity: boolean;
  onActivity: () => void;
  entry: boolean;
  onEntry: () => void;
  entryAvailable: boolean;
  tour: boolean;
  onTour: () => void;
  weak: boolean;
  onWeak: () => void;
  weakAvailable: boolean;
  motionOn: boolean;
  onMotion: () => void;
  reducedMotion: boolean;
  aiOn: boolean;
  aiHasData: boolean;
  onAi: () => void;
  onExport: (kind: "png" | "svg" | "mermaid") => void;
  fullscreenSupported: boolean;
  isFullscreen: boolean;
  onFullscreen: () => void;
  search: ReactNode;
  pathFinder: ReactNode;
}) {
  const diagramOnly = props.view === "diagram";
  return (
    <div className="flex flex-col gap-2" data-map-export-exclude>
      <div className="flex flex-wrap items-center gap-2">
        <SegmentedControl
          aria-label={MAP_COPY.groupBy}
          value={props.grouping}
          onValueChange={(v) => props.onGrouping(v as DiagramGrouping)}
          options={[
            { value: "subsystem", label: MAP_COPY.groupingSubsystem },
            { value: "folder", label: MAP_COPY.groupingFolder },
          ]}
        />
        <SegmentedControl
          aria-label={MAP_COPY.view}
          value={props.view}
          onValueChange={(v) => props.onView(v as MapView)}
          options={[
            { value: "diagram", label: MAP_COPY.viewDiagram },
            { value: "list", label: MAP_COPY.viewList },
          ]}
        />
        {props.search}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {diagramOnly ? (
          <>
            <Toggle
              pressed={props.activity}
              onClick={props.onActivity}
              icon={<Flame size={13} aria-hidden="true" />}
            >
              {MAP_COPY.activity}
            </Toggle>
            {props.entryAvailable ? (
              <Toggle
                pressed={props.entry}
                onClick={props.onEntry}
                icon={<LogIn size={13} aria-hidden="true" />}
              >
                {MAP_COPY.entryPoints}
              </Toggle>
            ) : null}
            <Toggle
              pressed={props.tour}
              onClick={props.onTour}
              icon={<ListOrdered size={13} aria-hidden="true" />}
            >
              {MAP_COPY.readingOrder}
            </Toggle>
            {props.weakAvailable ? (
              <Toggle
                pressed={props.weak}
                onClick={props.onWeak}
                icon={<Spline size={13} aria-hidden="true" />}
              >
                {MAP_COPY.weakLinks}
              </Toggle>
            ) : null}
            <Toggle
              pressed={props.motionOn && !props.reducedMotion}
              onClick={props.onMotion}
              disabled={props.reducedMotion}
              title={props.reducedMotion ? MAP_COPY.motionReduced : undefined}
              icon={
                props.motionOn && !props.reducedMotion ? (
                  <Pause size={13} aria-hidden="true" />
                ) : (
                  <Play size={13} aria-hidden="true" />
                )
              }
            >
              {props.motionOn && !props.reducedMotion ? MAP_COPY.motionOn : MAP_COPY.motionOff}
            </Toggle>
            {props.pathFinder}
          </>
        ) : null}
        <span className="flex-1" />
        {props.aiHasData ? (
          <Toggle
            pressed={props.aiOn}
            onClick={props.onAi}
            icon={<Sparkles size={13} aria-hidden="true" />}
          >
            {MAP_COPY.aiLabels}
          </Toggle>
        ) : (
          <GlareHover className="inline-flex rounded-sm">
            <Button type="button" size="sm" variant="secondary" onClick={props.onAi}>
              <Sparkles size={13} aria-hidden="true" />
              {MAP_COPY.describeWithAi}
            </Button>
          </GlareHover>
        )}
        {diagramOnly ? (
          <DropdownMenu
            trigger={
              <Button type="button" size="sm" variant="secondary">
                <Download size={13} aria-hidden="true" />
                {MAP_COPY.exportLabel}
              </Button>
            }
            items={[
              { label: MAP_COPY.downloadPng, onSelect: () => props.onExport("png") },
              { label: MAP_COPY.downloadSvg, onSelect: () => props.onExport("svg") },
              { label: MAP_COPY.copyMermaid, onSelect: () => props.onExport("mermaid") },
            ]}
          />
        ) : null}
        {diagramOnly && props.fullscreenSupported ? (
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={props.onFullscreen}
            aria-label={props.isFullscreen ? MAP_COPY.exitFullscreen : MAP_COPY.fullscreen}
          >
            {props.isFullscreen ? (
              <Minimize2 size={13} aria-hidden="true" />
            ) : (
              <Maximize2 size={13} aria-hidden="true" />
            )}
          </Button>
        ) : null}
      </div>
    </div>
  );
}
