/** The single content barrel (UI rebuild session 2, Part B) — every
 * user-facing explanatory string in the app is reachable from `src/content`,
 * either defined here directly (`./explainability`, `./methods`) or
 * re-exported (`./copy`, folding in the pre-existing `src/lib/copy.ts`
 * enum-derived-sentence maps — see that module's own header comment for why
 * it stays physically defined in `lib/`). Import from this barrel, or from
 * one of the three files directly — both are equivalent. */
export * from "./explainability";
export * from "./methods";
export * from "./copy";
