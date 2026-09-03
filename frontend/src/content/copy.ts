/**
 * Re-exports `src/lib/copy.ts` under `src/content/` so this directory is
 * genuinely the single place every user-facing string in the app is
 * imported from, per plan/UI_REBUILD_SESSIONS.md section 5's "one content
 * module owns every user-facing string" rule.
 *
 * The maps themselves stay physically defined in `../lib/copy.ts` rather
 * than being moved here: decision #11 (section 1 of that same spec)
 * requires every `src/lib/*.test.ts` file — including `lib/copy.test.ts`,
 * which hardcodes a literal list of every backend enum value and is
 * deliberately NOT derived from the maps it tests — to keep passing
 * UNTOUCHED. Moving the maps would mean either moving that test alongside
 * them (touching a protected file for no functional gain) or leaving the
 * test importing from a now-stale path. A re-export satisfies both rules
 * at once: `lib/copy.ts` and its test are untouched, and every NEW import
 * from this session onward can still write `from "../content/copy"` (or
 * the `../content` barrel) like any other content module.
 */
export * from "../lib/copy";
