import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import { MAP_COPY } from "../../content/map";

export interface SearchItem {
  /** Node id the item resolves to (group/folder/file id format). */
  id: string;
  kind: "group" | "folder" | "file";
  label: string;
  /** Text matched against (label + path / AI name). */
  haystack: string;
  detail: string;
}

const MAX_RESULTS = 30;
const KIND_RANK = { group: 0, folder: 1, file: 2 } as const;

/** ARIA combobox over every group, folder and file in the diagram --
 * including ones not currently on screen (selecting those expands their
 * ancestors first). `/` focuses it from anywhere on the page. */
export function MapSearch({
  items,
  onPick,
  initialQuery,
}: {
  items: SearchItem[];
  onPick: (item: SearchItem) => void;
  initialQuery?: string | null;
}) {
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState(initialQuery ?? "");
  const [open, setOpen] = useState(Boolean(initialQuery));
  const [active, setActive] = useState(0);
  const autoPicked = useRef(false);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return items
      .map((item) => ({ item, at: item.haystack.toLowerCase().indexOf(q) }))
      .filter((r) => r.at >= 0)
      .sort(
        (a, b) =>
          KIND_RANK[a.item.kind] - KIND_RANK[b.item.kind] ||
          a.at - b.at ||
          a.item.label.localeCompare(b.item.label),
      )
      .slice(0, MAX_RESULTS)
      .map((r) => r.item);
  }, [items, query]);

  // A `?find=` that matches exactly one thing is resolved immediately.
  useEffect(() => {
    if (initialQuery && !autoPicked.current && results.length === 1) {
      autoPicked.current = true;
      onPick(results[0]);
      setOpen(false);
    }
  }, [initialQuery, results, onPick]);

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      const typing =
        target &&
        (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
      if (e.key === "/" && !typing) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  function pick(item: SearchItem) {
    onPick(item);
    setOpen(false);
    setQuery(item.label);
  }

  return (
    <div className="relative w-full sm:w-64">
      <Search
        size={13}
        className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-text-muted"
        aria-hidden="true"
      />
      <input
        ref={inputRef}
        role="combobox"
        aria-label={MAP_COPY.searchLabel}
        aria-expanded={open && query.trim().length > 0}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && results[active] ? `${listId}-${active}` : undefined}
        value={query}
        placeholder={MAP_COPY.searchPlaceholder}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          setActive(0);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setActive((a) => Math.min(a + 1, Math.max(0, results.length - 1)));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((a) => Math.max(0, a - 1));
          } else if (e.key === "Enter" && results[active]) {
            e.preventDefault();
            pick(results[active]);
          } else if (e.key === "Escape") {
            setOpen(false);
            e.currentTarget.blur();
          }
        }}
        className="w-full rounded-sm border border-border-interactive bg-bg-elevated py-1 pr-2 pl-7 text-xs text-text placeholder:text-text-muted"
      />
      {open && query.trim() ? (
        <ul
          id={listId}
          role="listbox"
          className="absolute z-30 mt-1 max-h-72 w-full overflow-y-auto rounded-sm border border-border bg-bg-elevated p-1 text-xs shadow-md sm:w-96"
        >
          {results.length === 0 ? (
            <li className="px-2 py-1.5 text-text-muted">{MAP_COPY.noMatches}</li>
          ) : (
            results.map((item, i) => (
              <li
                key={item.id}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === active}
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(item);
                }}
                onMouseEnter={() => setActive(i)}
                className={`flex cursor-pointer items-center gap-2 rounded-xs px-2 py-1.5 ${
                  i === active ? "bg-bg-inset" : ""
                }`}
              >
                <span className="cp-label w-12 shrink-0 text-text-muted">{item.kind}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-text">{item.label}</span>
                  <span className="block truncate font-mono text-2xs text-text-muted">
                    {item.detail}
                  </span>
                </span>
              </li>
            ))
          )}
        </ul>
      ) : null}
    </div>
  );
}
