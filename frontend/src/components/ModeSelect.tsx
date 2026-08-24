/** A small generic labelled `<select>` -- shared by every colour/edge/height
 * mode control across the codebase map and the 3D city (session 09), so
 * "pick one of these named options" always looks and behaves the same way
 * rather than each view rolling its own dropdown markup. */
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
    <label className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
        className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
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
