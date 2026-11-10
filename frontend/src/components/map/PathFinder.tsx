import { useEffect, useState } from "react";
import { Route } from "lucide-react";
import { MAP_COPY } from "../../content/map";
import { Button } from "../ui/Button";
import { Popover } from "../ui/Popover";

export interface PathOption {
  id: string;
  label: string;
}

/** Two pickers over the boxes currently on screen. The result itself is
 * computed by the page (it owns the projected edges) and shown here. */
export function PathFinder({
  options,
  value,
  resultText,
  onFind,
  onClear,
}: {
  options: PathOption[];
  value: [string, string] | null;
  resultText: string | null;
  onFind: (from: string, to: string) => void;
  onClear: () => void;
}) {
  const [from, setFrom] = useState(value?.[0] ?? "");
  const [to, setTo] = useState(value?.[1] ?? "");

  useEffect(() => {
    setFrom(value?.[0] ?? "");
    setTo(value?.[1] ?? "");
  }, [value]);

  const select = (label: string, current: string, onChange: (v: string) => void) => (
    <label className="flex flex-col gap-1 text-xs text-text-muted">
      {label}
      <select
        value={current}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-sm border border-border-interactive bg-bg-elevated px-2 py-1 text-xs text-text"
      >
        <option value="">{MAP_COPY.pathPick}</option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <Popover
      trigger={
        <Button type="button" variant="secondary" size="sm" aria-pressed={value !== null}>
          <Route size={13} aria-hidden="true" />
          {MAP_COPY.pathLabel}
        </Button>
      }
    >
      <div className="flex flex-col gap-3">
        {select(MAP_COPY.pathFrom, from, setFrom)}
        {select(MAP_COPY.pathTo, to, setTo)}
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="primary"
            size="sm"
            disabled={!from || !to || from === to}
            onClick={() => onFind(from, to)}
          >
            {MAP_COPY.pathFind}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={onClear}>
            {MAP_COPY.pathClear}
          </Button>
        </div>
        {resultText ? <p className="text-xs leading-relaxed text-text">{resultText}</p> : null}
      </div>
    </Popover>
  );
}
