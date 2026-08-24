import { useMemo, useState } from "react";

const MAX_SUGGESTIONS = 20;

/** A client-side autocomplete over a repository's file paths. Takes the
 * already-fetched path list as a prop -- the "fetch once and memoise" half
 * of Part B.2's spec is TanStack Query's job (the caller's query hook
 * already caches the list), this component's own job is just the O(n)
 * substring filter, which is fine up to ~5,000 paths (Part B.2). Kept
 * dependency-free (no query hook of its own) so it's usable and testable in
 * isolation, e.g. against a repository's /risk or /knowledge-map file
 * list. */
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
      <input
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
        className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500"
      />

      {paths.length === 0 ? (
        <p className="mt-1 text-xs text-slate-400 dark:text-slate-500">No files available yet.</p>
      ) : null}

      {open && matches.length > 0 ? (
        <ul className="absolute z-10 mt-1 max-h-64 w-full overflow-y-auto rounded-md border border-slate-200 bg-white text-sm shadow-lg dark:border-slate-700 dark:bg-slate-900">
          {matches.map((p) => (
            <li key={p}>
              <button
                type="button"
                onClick={() => handleSelect(p)}
                className="block w-full truncate px-3 py-1.5 text-left font-mono text-xs text-slate-700 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800"
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
