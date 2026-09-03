import { useMemo, useState } from "react";
import { Input } from "./ui/Input";

const MAX_SUGGESTIONS = 20;

/** A client-side autocomplete over a repository's file paths. Takes the
 * already-fetched path list as a prop -- the caller's query hook already
 * caches the list; this component's own job is just the O(n) substring
 * filter, which is fine up to ~5,000 paths. Kept dependency-free (no query
 * hook of its own) so it's usable and testable in isolation. */
export function FilePicker({
  paths,
  onSelect,
  placeholder = "Search files…",
}: {
  paths: string[];
  onSelect: (path: string) => void;
  placeholder?: string;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    const pool = q ? paths.filter((p) => p.toLowerCase().includes(q)) : paths;
    return pool.slice(0, MAX_SUGGESTIONS);
  }, [paths, query]);

  function handleSelect(path: string) {
    onSelect(path);
    setQuery(path);
    setOpen(false);
  }

  return (
    <div className="relative">
      <Input
        type="text"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        // A plain onBlur would fire before a list item's onClick and close
        // the dropdown first -- delay just long enough for the click to
        // land, then close.
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        placeholder={placeholder}
        disabled={paths.length === 0}
        className="font-mono"
      />

      {paths.length === 0 ? (
        <p className="mt-1 text-xs text-text-muted">No files available yet.</p>
      ) : null}

      {open && matches.length > 0 ? (
        <ul className="absolute z-10 mt-1 max-h-64 w-full overflow-y-auto rounded-sm border border-border bg-bg-elevated text-sm shadow-md">
          {matches.map((p) => (
            <li key={p}>
              <button
                type="button"
                onClick={() => handleSelect(p)}
                className="block w-full truncate px-3 py-1.5 text-left font-mono text-xs text-text-muted hover:bg-bg-inset hover:text-text"
                title={p}
              >
                {p}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
