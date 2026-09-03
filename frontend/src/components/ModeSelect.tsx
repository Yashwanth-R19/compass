import { InfoTooltip } from "./ui/InfoTooltip";

/** A small generic labelled `<select>` -- shared by every colour/edge/height
 * mode control across the codebase map and the 3D city (session 09), so
 * "pick one of these named options" always looks and behaves the same way
 * rather than each view rolling its own dropdown markup. A native
 * `<select>` deliberately, not the Radix `Select` primitive (components/ui) --
 * a plain native control is fully keyboard/screen-reader operable on its
 * own and there's no custom popover styling need here that would justify
 * the extra machinery. `tooltip`, when given, renders an `InfoTooltip` next
 * to the label -- every mode name carries one (UI rebuild session 3, Part
 * B: "an InfoTooltip on every mode name"). */
export function ModeSelect<T extends string>({
  label,
  tooltip,
  value,
  onChange,
  options,
  disabledOptions = [],
}: {
  label: string;
  tooltip?: string;
  value: T;
  onChange: (v: T) => void;
  options: Record<T, string>;
  disabledOptions?: T[];
}) {
  return (
    <label className="flex items-center gap-1.5 text-xs text-text-muted">
      {label}
      {tooltip ? <InfoTooltip label={`What does "${label}" mean?`} text={tooltip} /> : null}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
        className="rounded-sm border border-border-interactive bg-bg-inset px-2 py-1 text-xs text-text"
      >
        {(Object.keys(options) as T[]).map((key) => (
          <option key={key} value={key} disabled={disabledOptions.includes(key)}>
            {options[key]}
          </option>
        ))}
      </select>
    </label>
  );
}
