/** A small generic labelled `<select>` -- shared by every colour/edge/height
 * mode control across the codebase map and the 3D city (session 09), so
 * "pick one of these named options" always looks and behaves the same way
 * rather than each view rolling its own dropdown markup. A native
 * `<select>` deliberately, not the Radix `Select` primitive (components/ui) --
 * a plain native control is fully keyboard/screen-reader operable on its
 * own and there's no custom popover styling need here that would justify
 * the extra machinery. */
export function ModeSelect<T extends string>({
  label,
  value,
  onChange,
  options,
  disabledOptions = [],
}: {
  label: string;
  value: T;
  onChange: (v: T) => void;
  options: Record<T, string>;
  disabledOptions?: T[];
}) {
  return (
    <label className="flex items-center gap-2 text-xs text-ink-muted">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
        className="border border-border-interactive bg-surface px-2 py-1 text-xs text-ink"
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
