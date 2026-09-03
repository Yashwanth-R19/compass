import { Select as RadixSelect } from "radix-ui";
import { Check, ChevronDown } from "lucide-react";

/** A styled Radix `Select` -- full keyboard support (arrow keys,
 * type-ahead, Home/End, Escape) and correct ARIA roles for free. Falls
 * back to this instead of a native `<select>` only where a page wants the
 * popover's appearance to match the rest of the instrument chrome; a plain
 * native `<select>` remains fine for a simple mode switch. */
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
    <label className="flex items-center gap-2 text-xs text-text-muted">
      {label}
      <RadixSelect.Root value={value} onValueChange={(v) => onChange(v as T)}>
        <RadixSelect.Trigger className="inline-flex items-center gap-1.5 rounded-sm border border-border-interactive bg-bg-elevated px-2 py-1 text-xs text-text data-[placeholder]:text-text-muted">
          <RadixSelect.Value />
          <RadixSelect.Icon aria-hidden="true">
            <ChevronDown size={12} />
          </RadixSelect.Icon>
        </RadixSelect.Trigger>
        <RadixSelect.Portal>
          <RadixSelect.Content
            position="popper"
            sideOffset={4}
            className="z-50 rounded-sm border border-border bg-bg-elevated text-xs text-text shadow-md"
          >
            <RadixSelect.Viewport className="p-1">
              {keys.map((key) => (
                <RadixSelect.Item
                  key={key}
                  value={key}
                  disabled={disabledOptions.includes(key)}
                  className="flex cursor-pointer items-center justify-between gap-3 rounded-xs px-2 py-1.5 outline-none data-[highlighted]:bg-bg-inset data-[disabled]:cursor-not-allowed data-[disabled]:opacity-40"
                >
                  <RadixSelect.ItemText>{options[key]}</RadixSelect.ItemText>
                  <RadixSelect.ItemIndicator aria-hidden="true">
                    <Check size={12} />
                  </RadixSelect.ItemIndicator>
                </RadixSelect.Item>
              ))}
            </RadixSelect.Viewport>
          </RadixSelect.Content>
        </RadixSelect.Portal>
      </RadixSelect.Root>
    </label>
  );
}
