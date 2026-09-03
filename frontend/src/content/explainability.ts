/**
 * The single source of every explanatory string in the app (UI rebuild
 * session 2, Part B — plan/UI_REBUILD_SESSIONS.md section 5, "the
 * explainability doctrine"). From this session onward, no component
 * hardcodes user-facing explanatory copy inline — it imports from here.
 *
 * This keeps the product's voice consistent and its claims auditable: a
 * reviewer can read this one file and see every claim Compass makes about
 * its own numbers, in one place, instead of hunting through component
 * markup. Nothing here is copied from any reference product's copy — every
 * sentence is written fresh, about Compass's own domain.
 *
 * What does NOT live here: per-backend-enum sentences (finding categories,
 * tour reason codes, hygiene kinds, ...) — those stay in `lib/copy.ts`,
 * re-exported from `./copy` for a single import surface, per that module's
 * own exhaustiveness-test discipline (see `./copy.ts`'s header comment for
 * why that file is not moved wholesale into this one).
 */

// ---------------------------------------------------------------------------
// Landing page onboarding panel (moved verbatim from
// components/OnboardingPanel.tsx, session 1 — see that file's own comment,
// which anticipated exactly this move being mechanical).
// ---------------------------------------------------------------------------

export const ONBOARDING_INTRO =
  "Compass turns a repository's own commit history into evidence — every number below is computed from real git data, the same way every time, never inferred by a model skimming the current tree.";

export interface OnboardingStep {
  title: string;
  body: string;
}

export const ONBOARDING_STEPS: OnboardingStep[] = [
  {
    title: "Mine the history",
    body: "Compass clones the repository and streams its full commit log — every changeset, every author, every file touched — without guessing at anything a language model would have to hallucinate from a snapshot.",
  },
  {
    title: "Compute the facts",
    body: "Commits, files, and structural imports are parsed into a plain, deterministic dataset: who touched what, when, and what depends on what.",
  },
  {
    title: "Derive the insight",
    body: "Locked formulas run over those facts — change-coupling, calibrated risk, subsystem structure, knowledge distribution — and the exact formula behind every score is one click away.",
  },
];

export const ONBOARDING_FOOTNOTE =
  "Everything on the page you're about to see — the showcase cards, and any repository you submit — is the output of exactly this pipeline, not a summary written after the fact.";

// ---------------------------------------------------------------------------
// Tooltips — one entry for every metric name that appears anywhere in the
// app. `InfoTooltip` (src/components/ui/InfoTooltip.tsx) is the single
// mechanism these reach the screen through. Each is two to four plain
// sentences: what it measures, how to read it, and — where it applies —
// what it does not mean.
// ---------------------------------------------------------------------------

export type TooltipKey =
  | "riskScore"
  | "riskConfidence"
  // UI rebuild session 3 additions -- Overview's difficulty breakdown rows
  // and team/cadence cards, and People's "who do I ask" flagship search.
  | "subsystemCount"
  | "medianComplexity"
  | "maxDependencyDepth"
  | "botCommitRatio"
  | "commitCadence"
  | "principalAuthor"
  | "recency"
  | "churnTotal"
  | "churnWeighted"
  | "complexity"
  | "couplingDegree"
  | "sharedRevisions"
  | "avgRevisions"
  | "hiddenDependency"
  | "moduleCoupling"
  | "subsystem"
  | "cohesion"
  | "modularity"
  | "centrality"
  | "entryPoint"
  | "healthScore"
  | "highRiskRatio"
  | "cycle"
  | "onboardingDifficulty"
  | "docCoverage"
  | "truckFactor"
  | "degreeOfAuthorship"
  | "expert"
  | "staleContributor"
  | "orphanedKnowledge"
  | "instability"
  | "revertCycleCount"
  | "oversizedCommit"
  | "fixupChurn"
  | "riskyCommit"
  | "testCochangeRatio"
  | "testClassification"
  | "blastRadius"
  | "surprisingAffected"
  | "glossaryTermScore"
  | "secretFingerprint"
  | "stillInHead"
  | "vulnerabilitySeverity"
  | "dependencyDirectness"
  | "benchmarkPercentile"
  | "widenedComparison"
  | "calibration"
  | "snapshot"
  | "churnRankedHotspot"
  | "engineVersion";

export const TOOLTIPS: Record<TooltipKey, string> = {
  riskScore:
    "A composite 0–1 score combining recency-weighted churn times complexity (60%), the file's strongest coupling partner (25%), and commit count (15%) — each term normalized before weighting. It is a locked formula: the weights never change file to file or repo to repo. Higher means more of the classic hotspot signal — frequently changed, complex code — not a prediction that this specific file will break.",
  riskConfidence:
    "How much commit history backs this file's risk score, independent of the score itself — min(1, commit_count / 10). A file can be high-risk and low-confidence at once: exactly as risky by the numbers available, just backed by less history. Never folded into risk_score.",
  churnTotal:
    "The raw sum of added and deleted lines across every commit that touched this file, with no time decay. Shown alongside churn_weighted for comparison — it is not what feeds the risk formula.",
  churnWeighted:
    "Churn with exponential decay applied — a 365-day half-life relative to the repository's own last commit, never wall-clock time. A file heavily edited five years ago and untouched since weighs far less than one edited constantly this year. This is the churn value the locked risk formula actually uses.",
  complexity:
    "Cyclomatic complexity, measured on the current checked-out tree only — never at a past revision. A file's score is the maximum complexity across its functions, not the average, so one complicated function is never diluted by many simple ones.",
  couplingDegree:
    "shared_revs / min(revs(A), revs(B)) — the fraction of the less-active file's own commits that also touched the other file. Dividing by the file that changed LESS, not the average, is deliberate: it asks 'when this file changes, how often does the other change too', which is the direction that actually predicts a missed edit.",
  sharedRevisions:
    "How many commits touched both files in a pair. A pair needs at least 5 shared revisions to be reported (lowered to 2 on a small repository with too little history, which also marks the run low-confidence).",
  avgRevisions:
    "The average number of commits each file in a coupling pair was touched in, shown for context. Not what the locked coupling_degree formula divides by — that always uses the LESS-active file, never the average.",
  hiddenDependency:
    "A pair of files that change together constantly (coupling_degree at or above 0.30) but share no import or structural reference in either direction. This is the flagship insight change-coupling analysis exists to surface: a real relationship the source code itself does not declare.",
  moduleCoupling:
    "The identical locked coupling_degree formula, computed directly from directory- or subsystem-grain commit changesets — never derived by averaging or summing file-pair coupling values, which would be mathematically invalid (each file-pair ratio divides by that pair's own revision counts, not the module's).",
  subsystem:
    "A group of files detected by running deterministic community detection (Louvain, with a fixed seed) over the combined import-and-coupling graph, then named from a shared path prefix or common identifier. A computed grouping, not a declared package or module boundary the repository itself states.",
  cohesion:
    "internal_edges / (internal_edges + external_edges) for a subsystem — how much of its edge weight stays inside the group versus reaching outside it. 0 for a subsystem with no edges at all.",
  modularity:
    "A standard graph-partition quality measure (networkx's modularity), computed on the raw community detection result before small subsystems are merged or the subsystem count is capped for readability. Higher generally means a cleaner separation between subsystems.",
  centrality:
    "PageRank computed once over the whole combined dependency-and-coupling graph. A file many other files (transitively) depend on scores higher — it is a measure of structural importance, not of risk or quality.",
  entryPoint:
    "A file detected as somewhere execution starts — a CLI command, a web server, a UI root, a test suite root, or a build entry point. Detected from manifests (package.json, pyproject.toml, ...), naming conventions, or graph shape (nothing imports it, and it imports several other files) — never guessed from file contents.",
  healthScore:
    "100 minus a risk penalty (capped at 40 points), 6 points per detected circular dependency (capped at 30), and 3 points per hidden-dependency pair (capped at 30). An openly heuristic composite, not a locked formula — its penalty weights are a documented starting point, not a statistically fitted model.",
  highRiskRatio:
    "The proportion of a repository's files with a risk_score at or above 0.60 — one of the three inputs to the health score. This 0.60 threshold is distinct from RiskEngine's own 0.70 finding-severity threshold; the two numbers look like they should be the same one, but they answer different questions.",
  cycle:
    "A circular chain of imports (A imports B imports C imports A) found by walking the dependency graph. Each cycle costs the health score 6 points, capped at 30 points total regardless of how many cycles exist.",
  onboardingDifficulty:
    "A 0–100 heuristic composite of subsystem count, median file complexity, documentation coverage, truck factor, and maximum dependency-graph depth from any entry point. Higher means harder to get oriented in. Explicitly heuristic — the inputs are specified, the weights are a documented, adjustable starting point.",
  docCoverage:
    "Whether a README exists, how long it is, and whether a CONTRIBUTING or docs directory exists — a coarse, mechanical signal, not a judgment of documentation quality.",
  truckFactor:
    "How many contributors would need to leave before more than half of the repository's files lose every identified expert — computed by repeatedly removing whichever remaining contributor is expert for the most still-covered files. This measures the PROJECT's knowledge-distribution risk, never any one person's importance.",
  degreeOfAuthorship:
    "DOA(d, f) = 3.293 + 1.098×FA + 0.164×DL − 0.321×ln(1+AC), a formula published by Fernández-Ramil, Izquierdo-Cortázar & Mens and used for truck-factor estimation by Avelino, Passos, Hora & Valente (ICPC 2016) — implemented exactly as published, not tuned by Compass. FA is 1 if this developer authored the file's first commit, DL is their own change count on the file, AC is every other developer's change count.",
  expert:
    "A contributor whose DOA for a file reaches at least 75% of that file's own highest DOA AND clears an absolute floor of 3.293 — both conditions, independently. The absolute floor stops a file with only thin history from manufacturing a false expert purely by winning a lopsided comparison against equally weak candidates.",
  staleContributor:
    "A contributor whose last commit is more than 180 days before the repository's own most recent commit — never compared against today's date. An archived repository whose whole team was active right up until its last commit has nobody stale, even though every timestamp looks old by the wall-clock.",
  orphanedKnowledge:
    "A file whose only remaining expert has gone stale. When that file is also in the top quartile of this run's risk scores, it becomes a knowledge finding — real risk with no one currently active to explain it.",
  instability:
    "norm(oversized_commit_count + fixup_commit_count + 2 × revert_cycle_count) for a file — a revert counts double, since undoing a change entirely is a stronger signal than one unusually large commit. An openly heuristic signal about how a file is committed to, not about what it does.",
  revertCycleCount:
    "How many times a change to this file was later reverted, detected from the commit history's own is_revert/is_fix flags. Feeds instability_score with double weight.",
  oversizedCommit:
    "A commit whose files-changed count AND total line churn both exceed this repository's own 95th percentile — measured against the repository's own distribution, never a fixed absolute number, so what counts as oversized differs between a small project and a monorepo that regularly does hundred-file dependency bumps.",
  fixupChurn:
    "Three or more consecutive commits by the same author, close together in time, touching overlapping files, where at least one message reads like wip/fixup/oops/typo. Reported as a hygiene signal, never treated as a defect.",
  riskyCommit:
    "A commit scored 0–4 on four independent conditions: touching at least 3 subsystems, being in the top churn quintile, changing no test file, and having a message shorter than 15 characters. Reported once it meets at least 3 of the 4 — deliberately excludes anything about time of day, which is folklore and timezone-dependent.",
  testCochangeRatio:
    "The fraction of a file's commits that also touch at least one of its mapped tests. This measures test MAINTENANCE — whether tests keep changing alongside the code — never test coverage or quality. A file with excellent, rarely-changed tests can score exactly like an untested one.",
  testClassification:
    "no_test (no mapped test found), stale_test (a mapped test exists but its co-change ratio is 0.20 or below, with enough commit history to judge), or tracked (everything else). Mapping is best-effort, by naming convention and by structural import from a test file.",
  blastRadius:
    "Everything that could be affected by changing one file, from two independent angles: structural (files that transitively import it) and historical (files with a real change-coupling relationship to it, from the persisted coupling data). The two are shown separately and never blended into one score.",
  surprisingAffected:
    "Files in a blast radius's historical set but NOT its structural one — real, persistent co-change with no import path this computation found. This is the money result: evidence of a relationship the source code doesn't declare.",
  glossaryTermScore:
    "log(1 + occurrences) × (1 + subsystem_spread / total_subsystems) — an openly heuristic ranking of a repository's own vocabulary, mined from identifier and file names, never file contents. A high score means a term is both frequent and used across many subsystems: shared vocabulary, not one subsystem's internal jargon.",
  secretFingerprint:
    "A salted SHA-256 hash of a detected secret's value — the only trace of the value itself Compass ever stores. The raw value is never persisted, logged, or returned by any endpoint; the fingerprint exists only to deduplicate and to match a hit still present in the current checkout.",
  stillInHead:
    "Whether the exact line containing a detected secret is still present in the current checkout, determined by a second scan of the working tree — never inferred from whether the file itself still exists, since a file can survive with that one line removed.",
  vulnerabilitySeverity:
    "Read from the OSV.dev advisory: a real CVSS v3 base score computed from its vector string when one exists, otherwise the source's own severity label, otherwise 'unknown' — a severity is never invented when the advisory carries none.",
  dependencyDirectness:
    "Whether a vulnerable package is declared directly by this repository's own manifest or pulled in transitively by another dependency — a different remediation problem in each case (edit your own manifest versus wait on or override an upstream one).",
  benchmarkPercentile:
    "Where one of this repository's metrics falls against a curated corpus of real repositories in the same language and size bucket. Interpolated from stored percentile breakpoints (p10/p25/p50/p75/p90), never recomputed live against the corpus repositories themselves.",
  widenedComparison:
    "The exact (language, size bucket) cell had fewer than 5 contributing corpus repositories, so the comparison broadened — first to any size bucket in the same language, then to any language at all — before falling back to a purely per-repository heuristic. A percentile is never presented as more authoritative than the repository count actually behind it.",
  calibration:
    'Whether a heuristic score\'s normalization is per-repository min-max scaling ("heuristic") or drawn from the curated corpus\'s own percentile curve ("corpus"). Read from the response at request time — a score is never labelled more precisely calibrated than the currently configured provider actually supports.',
  snapshot:
    "One point in the evolution timeline, recomputed from commit history up to that point only — never from a checked-out tree at that revision. Up to 24 points, spaced evenly by commit index (not by date), so an unevenly active repository's snapshots still represent roughly equal amounts of real development activity.",
  churnRankedHotspot:
    "The top files by cumulative churn AS OF one historical snapshot — deliberately never called 'risk' at that point in time, since complexity was never measured historically and the locked risk formula needs it.",
  engineVersion:
    "Which version of the analysis formulas produced a given run. Bumped only when a measurement genuinely changes (for example, session 07's switch from raw churn to recency-weighted churn) — comparing two runs across a version boundary is legitimate, but some of the movement may reflect the measurement change rather than the code.",
  subsystemCount:
    "How many subsystems the repository was partitioned into — one of the five terms in the onboarding difficulty score. More subsystems generally means more structure a newcomer has to hold in their head at once.",
  medianComplexity:
    "The median cyclomatic complexity across the repository's files — one of the five terms in the onboarding difficulty score. The median, not the mean, so a handful of extreme outliers don't dominate a repository-wide reading the way they deliberately do for a single file's own risk score.",
  maxDependencyDepth:
    "The longest shortest-path from any detected entry point through the dependency graph — one of the five terms in the onboarding difficulty score. A deep chain means tracing execution from where a program starts to a specific piece of behavior takes many hops.",
  botCommitRatio:
    "The proportion of commits authored by an identity flagged as a bot (a name ending in the literal `[bot]` suffix, e.g. dependabot) — bots are counted here but excluded entirely from expertise/truck-factor modelling.",
  commitCadence:
    "Commit counts over the three most recent windows relative to this run's own start time (last 30, 90, and 365 days) — the closest thing to an activity trend Compass computes; no endpoint returns a full commit-by-day time series, so this is three real numbers, not an interpolated curve.",
  principalAuthor:
    "The contributor with the highest Degree of Authorship for a file — its most likely single point of contact, not necessarily its most recent editor or most frequent committer.",
  recency:
    "How recently a file was last modified, on a scale between the oldest and most recently touched file in this view. Not a measure of quality or risk on its own — a stale file may simply be finished and stable.",
};

// ---------------------------------------------------------------------------
// Header glossary — Compass's own vocabulary, for the GlossaryDialog. This
// is DELIBERATELY a different thing from the repo-scoped Tour glossary
// (GET /repos/{id}/glossary, terms mined from the analysed repository's own
// identifiers) — the two share the word "glossary" and nothing else. One
// explains Compass; the other explains the codebase being analysed. Do not
// merge them.
// ---------------------------------------------------------------------------

export interface GlossaryEntry {
  term: string;
  body: string;
}

export const GLOSSARY: GlossaryEntry[] = [
  {
    term: "Facts",
    body: "The layer of data mined directly from git — commits, files, imports — deterministic for a given repository and commit sha, and replaced wholesale whenever that commit sha changes.",
  },
  {
    term: "Insight",
    body: "Everything an analysis engine computes from the Facts for one specific run — coupling, risk, subsystems, findings — kept per run rather than overwritten, so old runs stay comparable.",
  },
  {
    term: "Analysis run",
    body: "One complete pass of the pipeline over a repository at a specific commit. A repository accumulates many runs over time; only its current run is shown by default.",
  },
  {
    term: "Engine",
    body: "One pure, deterministic computation over already-mined data — coupling, risk, subsystems, and so on are each their own engine, run in a fixed order because later ones depend on earlier ones' output.",
  },
  {
    term: "Subsystem",
    body: "A group of files Compass detects by clustering the dependency-and-coupling graph — a computed grouping, not necessarily the same as the repository's own declared package structure.",
  },
  {
    term: "Coupling",
    body: "How often two files change together across the commit history, independent of whether either one imports the other.",
  },
  {
    term: "Hidden dependency",
    body: "A pair of files with strong change-coupling but no structural import relationship — a real connection the source code itself never states.",
  },
  {
    term: "Risk score",
    body: "A locked, weighted combination of churn, complexity, coupling, and commit count for one file — the same formula on every repository.",
  },
  {
    term: "Confidence",
    body: "How much evidence backs a specific number — shown as an independent value, never blended into the score it accompanies.",
  },
  {
    term: "Finding",
    body: "One flagged observation — a hotspot, a hidden dependency, a secret, a vulnerability — ranked globally by severity, then by confidence.",
  },
  {
    term: "Severity",
    body: "How serious a finding is: low, medium, or high. Always the primary sort key for the findings stream.",
  },
  {
    term: "Health score",
    body: "A single 0–100 composite of a repository's high-risk file ratio, circular dependencies, and hidden dependencies.",
  },
  {
    term: "Truck factor",
    body: "How many people would need to leave before most of the codebase loses everyone who understands it.",
  },
  {
    term: "Degree of authorship (DOA)",
    body: "A published formula estimating how much a specific person actually knows a specific file, from their share of its edit history.",
  },
  {
    term: "Entry point",
    body: "A file where execution starts — a CLI command, a web server, a UI root — detected from manifests, naming convention, or graph shape.",
  },
  {
    term: "Onboarding difficulty",
    body: "A heuristic 0–100 estimate of how hard a repository is to get oriented in, from its structure, complexity, documentation, and knowledge concentration.",
  },
  {
    term: "Commit hygiene",
    body: "Signals about HOW a repository is committed to — oversized commits, fixup churn, risky commits — distinct from risk (what's risky) and knowledge (who knows it).",
  },
  {
    term: "Test gap",
    body: "A file with no mapped test, or one whose mapped test rarely changes alongside it. Measures test maintenance, never coverage or quality.",
  },
  {
    term: "Blast radius",
    body: "Everything that could be affected by changing one file — structurally, by import, and historically, by real change-coupling.",
  },
  {
    term: "Corpus baseline",
    body: "Percentile breakpoints computed from a small, curated set of real repositories, used to say whether a metric is high or low RELATIVE to similar projects.",
  },
  {
    term: "Calibration",
    body: "Whether a score's normalization compares a repository only against itself (heuristic) or against the curated corpus (corpus).",
  },
  {
    term: "Showcase repository",
    body: "A pinned, pre-computed example repository shown on the landing page — click straight into a full result with no analysis wait.",
  },
  {
    term: "Share link",
    body: "A link granting access to one specific analysis run of a private repository — never to the repository itself, and never to a later run.",
  },
  {
    term: "Narrative",
    body: "An optional, off-by-default sentence phrasing already-computed numbers into prose. Never a source of numbers itself — every figure it mentions is already on screen.",
  },
];

// ---------------------------------------------------------------------------
// Empty states — every empty-state string this session's own components
// use, keyed by situation. An empty state must always say why it is empty
// and what would change it.
// ---------------------------------------------------------------------------

export const EMPTY_MESSAGES = {
  workedExampleUnavailable:
    "No showcase repository has a completed analysis run yet, so there's no worked example to show here — every stage below still describes what it computes.",
  formulasUnavailable:
    "The live formula values couldn't be loaded right now. The description above is still accurate; only the numeric breakdown is unavailable.",
  pipelineUnavailable:
    "The pipeline stage list couldn't be loaded right now — try reloading this page.",
  glossarySearchNoResults: "No glossary terms match that search.",
} as const;

// ---------------------------------------------------------------------------
// Formula copy — per explainable quantity, keyed by the SAME `key` GET
// /meta/formulas uses for each FormulaGroup. Drives ScoreExplainer's range
// note and "Also measured (not scored)" block (section 5.2). The formula
// text and constants themselves come from the API (section 5.4) — this is
// presentation-only curation: which fields belong in the "also measured"
// block and how to phrase the range.
// ---------------------------------------------------------------------------

export interface AlsoMeasuredItem {
  label: string;
  tooltip?: TooltipKey;
}

export interface FormulaCopyEntry {
  /** A qualitative, NUMBER-FREE description naming the terms a formula
   * combines — deliberately containing no weight or threshold of its own,
   * so it stays true (and renderable) even when GET /meta/formulas is
   * unavailable and ScoreExplainer has no live constants to show (section
   * 5.4: "never falls back to a hardcoded copy of the weights"). The
   * numeric formula string with real weights substituted comes from the
   * API's own `formula` field instead, only when that request succeeds. */
  summary: string;
  rangeNote: string;
  alsoMeasuredNote?: string;
  alsoMeasured?: AlsoMeasuredItem[];
}

export const FORMULA_COPY: Record<string, FormulaCopyEntry> = {
  risk: {
    summary:
      "A weighted combination of recency-weighted churn times complexity, the file's strongest coupling partner, and how many times it's been committed.",
    rangeNote: "Score range: 0 to 1. Higher means more of the classic hotspot signal.",
    alsoMeasuredNote:
      "None of these feed the locked formula above — they're returned so they can be shown alongside it without being folded in.",
    alsoMeasured: [
      { label: "Total churn (unweighted)", tooltip: "churnTotal" },
      { label: "Instability score", tooltip: "instability" },
      { label: "Revert cycle count", tooltip: "revertCycleCount" },
      { label: "Test classification", tooltip: "testClassification" },
      { label: "Test co-change ratio", tooltip: "testCochangeRatio" },
      { label: "Expert count", tooltip: "expert" },
      { label: "Orphaned knowledge", tooltip: "orphanedKnowledge" },
    ],
  },
  coupling: {
    summary:
      "The fraction of the less-active file's own commits that also touched the other file in a pair.",
    rangeNote: "Score range: 0 to 1. Higher means the two files change together more consistently.",
    alsoMeasuredNote:
      'The locked formula divides by the LESS-active file, never the average — "shared over average" is the intuitive wrong guess.',
    alsoMeasured: [
      { label: "Shared revisions", tooltip: "sharedRevisions" },
      { label: "Average revisions", tooltip: "avgRevisions" },
      { label: "Confidence hint", tooltip: undefined },
    ],
  },
  module_coupling: {
    summary:
      "The same change-coupling relationship as file-level coupling, computed directly at directory or subsystem grain.",
    rangeNote:
      "Same 0 to 1 range as file-level coupling, computed independently at directory or subsystem grain — never derived from file-pair values.",
  },
  health: {
    summary:
      "100 minus a penalty for the proportion of high-risk files, a penalty per circular dependency, and a penalty per hidden-dependency pair.",
    rangeNote: "Score range: 0 to 100. Higher means healthier.",
    alsoMeasuredNote:
      "high_risk_ratio's own 0.60 threshold is distinct from the risk engine's own 0.70 finding-severity threshold — two different numbers that look like they should be the same one.",
  },
  onboarding_difficulty: {
    summary:
      "A weighted combination of subsystem count, median file complexity, documentation coverage, truck factor, and how deep the dependency graph runs from any entry point.",
    rangeNote: "Score range: 0 to 100. Higher means harder to onboard into.",
    alsoMeasuredNote:
      "doc_coverage and truck_factor are not passed through the normalizer the way the other three terms are — their own arithmetic already bounds them to [0, 1].",
  },
  expertise: {
    summary:
      "A published formula combining whether this developer authored the file's first commit, their own change count on it, and every other developer's change count on it.",
    rangeNote:
      "DOA has no fixed upper bound; a developer is an expert once their score clears both a relative and an absolute threshold.",
    alsoMeasuredNote:
      "Shown as supporting evidence for an expert assignment, alongside the DOA score itself.",
    alsoMeasured: [
      { label: "Changes to this file", tooltip: "degreeOfAuthorship" },
      { label: "Last touched" },
      { label: "Contributor is stale", tooltip: "staleContributor" },
    ],
  },
  truck_factor: {
    summary:
      "Repeatedly remove whichever remaining contributor is expert for the most still-covered files, until more than half of considered files have lost every expert.",
    rangeNote: "A count of people, not a percentage or a score in [0, 1].",
  },
  hygiene: {
    summary:
      "A weighted count of oversized commits, fixup-churn clusters, and revert cycles, with a revert counted double.",
    rangeNote: "Score range: 0 to 1, relative to this repository's own commit-size distribution.",
  },
  test_gaps: {
    summary:
      "The fraction of a file's commits that also touch at least one of its mapped tests, classified against this repository's own thresholds.",
    rangeNote:
      "test_cochange_ratio ranges 0 to 1 — the fraction of a file's commits that also touch one of its mapped tests.",
  },
  findings_rank: {
    summary: "Severity decides a finding's global rank first; confidence only breaks a tie.",
    rangeNote:
      "A single global ordering across every finding category — severity always decides first, confidence only breaks a tie within the same severity.",
  },
  subsystems: {
    summary:
      "Deterministic community detection over the combined dependency-and-coupling graph, merged and capped for readability.",
    rangeNote: "A partition into a small number of named subsystems, capped for readability.",
  },
  baseline: {
    summary:
      "A percentile lookup against a curated corpus of real repositories, widening past a thin cell before falling back to a per-repository comparison.",
    rangeNote:
      "A (metric, language, size bucket) cell needs enough contributing corpus repositories before a percentile at that exact grain is trusted.",
  },
  glossary_term_score: {
    summary:
      "How often a term occurs across the codebase, boosted by how many different subsystems it appears in.",
    rangeNote:
      "No fixed upper bound — a term used constantly across every subsystem scores highest; a term confined to one subsystem's internal jargon scores lower even at the same occurrence count.",
  },
};

// ---------------------------------------------------------------------------
// Calibration line copy — ScoreExplainer contract item 3: "states whether
// normalization is heuristic... or corpus-calibrated, read from the
// response's own `calibration` field. Never a hardcoded string [in the
// component]." The string itself still has to live somewhere — here.
// ---------------------------------------------------------------------------

export const CALIBRATION_COPY: Record<"heuristic" | "corpus", string> = {
  heuristic:
    "Normalized against this repository's own values only (per-repository min–max scaling) — not yet compared against other repositories.",
  corpus:
    "Normalized against a curated corpus of real repositories in the same language and size bucket — see the Methods page for how that corpus was built.",
};

// ---------------------------------------------------------------------------
// The honesty registry (section 5.3) — fixed strings for statements that
// are NOT already returned verbatim by the API. Where the API DOES return
// the string (TimelineResponse.not_covered, TestGapsResponse.limitation,
// GlossaryResponse.limitation, unreferenced_files_caveat, secrets_caveat,
// pooled_distribution_label, corpus_note, the truck-factor interpretation),
// render THAT string verbatim instead — never a local copy that could
// drift out of sync with it.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// /how-it-works content: the "why this is not an AI wrapper" argument and
// the closing "what Compass deliberately does not do" list (Part D).
// ---------------------------------------------------------------------------

export const NOT_AI_WRAPPER_POINTS: string[] = [
  "The analysis pipeline contains no language-model call anywhere — a claim a reader can check directly by searching this repository's own backend/app/jobs/ directory for any reference to the narrative package and finding none.",
  "The same repository at the same commit produces identical output on every run — deterministic community detection with a fixed seed, an explicit sort of every community list, and a total, path-based tie-break on every other ordering are what make that guarantee mechanical rather than aspirational.",
  "The narrative layer is optional, off by default, and may only rephrase numbers that are already computed and already on screen — it never introduces a score, a rank, a file list, or a recommendation of its own.",
];

export const WHAT_COMPASS_DOES_NOT_DO: string[] = [
  "Renames are not tracked as continuity — a rename is recorded as the old path being deleted and a new one added, since git's own history doesn't reliably mark an arbitrary diff as a single rename event.",
  "Java same-package references are not inferred — only explicit import statements are modeled, because guessing at same-package usage would require real type resolution Compass doesn't attempt.",
  "Complexity is measured on the current checked-out tree only, never at a historical revision — sampling it historically would require checking the repository out at every point, which this product deliberately doesn't do.",
  "Test-gap analysis measures maintenance, not coverage — Compass has no way to know whether a test actually exercises the code it sits near, only whether the two tend to change together.",
  "The domain glossary extracts vocabulary, not definitions — Compass has no access to what a term actually means, only how often it appears and how widely it's used across the codebase.",
  "Unreferenced-file detection is not dead-code detection — a file with no detected structural edge can still be reached through a dynamic import, reflection, or a build-config reference Compass doesn't parse.",
];

export const HONESTY = {
  secretHistoryStillRecoverable:
    "A secret removed from the current code but still present in git history is still HIGH severity — it is fully recoverable from this repository's public commit history and still needs rotation. This is never shown as resolved.",
  noSupportedManifestDistinctFromZero:
    "No supported dependency manifest was found in this repository (Compass parses requirements*.txt, pyproject.toml's [project.dependencies], package-lock.json, and pom.xml). This is a different, honest state from having scanned dependencies and found zero vulnerabilities.",
  couplingLowConfidence:
    "This repository had too few analyzed commits for the normal coupling floor, so a lowered threshold was used for this run — read these pairs as a smaller, less certain sample.",
  benchmarkWidened:
    "This comparison broadened past the exact language-and-size-bucket cell because too few corpus repositories matched it exactly — treat it as a coarser comparison.",
  compareEngineVersionDiffers:
    "These two runs used different engine versions. A prior change altered how an input is measured (for example, churn) — some movement shown here may reflect that measurement change rather than a real change in the code.",
  // UI rebuild session 3 additions -- the Map and People surfaces.
  pageRankUniformOnEdgelessGraph:
    "PageRank returns a uniform distribution on a graph with no detected import or coupling edges — every file gets the same centrality score. This correctly reflects the absence of structural data, not a computation error; centrality is not discriminating on a repository like this.",
  staleMeasuredAgainstRepoActivity:
    "Staleness is measured against this repository's own most recent commit, never against today's date. An archived repository whose whole team was active right up until its last commit has nobody stale, even though every timestamp looks old by the wall clock.",
  botsExcludedFromAuthorship:
    "Bot commits are excluded from authorship modelling entirely, not merely down-weighted. A file only ever touched by a bot — a lockfile only a dependency-update bot edits, for example — has no expert at all, rather than a weak one.",
  identityMergingIsRuleBasedNotFuzzy:
    "Contributor identities are merged by deterministic, rule-based matching only — an exact email, a GitHub noreply address, an exact name, or a shared email local part — never fuzzy string similarity. A missed merge only slightly undercounts one person's activity; a false merge would put someone else's history under the wrong name, which is the worse mistake to risk.",
} as const;
