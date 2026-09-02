import { Select as RadixSelect } from "radix-ui";

/** A styled Radix `Select` -- full keyboard support (arrow keys, type-ahead,
 * Home/End, Escape) and correct ARIA roles for free, which a hand-rolled
 * `<select>`-replacement almost never gets right. Falls back to this
 * instead of a native `<select>` only where a page wants the popover's
 * appearance to match the rest of the instrument chrome; a plain native
 * `<select>` (see ModeSelect.tsx) remains fine for a simple mode switch. */
export function Select<T extends string>({
  label,
  value,
  onChange,
  options,
  disabledOptions = [],
}: {
  label?: string;
  value: T;
  onChange: (v: T) => void;
  options: Record<T, string>;
  disabledOptions?: T[];
}) {
  const keys = Object.keys(options) as T[];

  return (
    <label className="flex items-center gap-2 text-xs text-ink-muted">
      {label}
      <RadixSelect.Root value={value} onValueChange={(v) => onChange(v as T)}>
        <RadixSelect.Trigger className="inline-flex items-center gap-1.5 border border-border-interactive bg-surface px-2 py-1 text-xs text-ink data-[placeholder]:text-ink-faint">
          <RadixSelect.Value />
          <RadixSelect.Icon aria-hidden="true">▾</RadixSelect.Icon>
        </RadixSelect.Trigger>
        <RadixSelect.Portal>
          <RadixSelect.Content
            position="popper"
            sideOffset={4}
            className="z-50 border border-border bg-surface text-xs text-ink"
          >
            <RadixSelect.Viewport className="p-1">
              {keys.map((key) => (
                <RadixSelect.Item
                  key={key}
                  value={key}
                  disabled={disabledOptions.includes(key)}
                  className="flex cursor-pointer items-center justify-between gap-3 px-2 py-1.5 outline-none data-[highlighted]:bg-surface-2 data-[disabled]:cursor-not-allowed data-[disabled]:opacity-40"
                >
                  <RadixSelect.ItemText>{options[key]}</RadixSelect.ItemText>
                  <RadixSelect.ItemIndicator aria-hidden="true">✓</RadixSelect.ItemIndicator>
                </RadixSelect.Item>
              ))}
            </RadixSelect.Viewport>
          </RadixSelect.Content>
        </RadixSelect.Portal>
      </RadixSelect.Root>
    </label>
  );
}
