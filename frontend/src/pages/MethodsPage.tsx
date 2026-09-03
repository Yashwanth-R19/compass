import { ExternalLink } from "lucide-react";
import { useFormulas } from "../api/hooks";
import { InfoTooltip } from "../components/ui/InfoTooltip";
import { Alert } from "../components/ui/Alert";
import {
  CELL_SIZE_GATE_NOTE,
  CORPUS_DESCRIPTION,
  CORPUS_REPO_LIST_PATH,
  CORPUS_REPO_LIST_URL,
  LIMITATIONS,
  METHODS_INTRO,
  METHODS_SECTIONS,
  REPRODUCIBILITY_CHANGES,
  REPRODUCIBILITY_GUARANTEE,
} from "../content/methods";
import { FORMULA_COPY, TOOLTIPS } from "../content/explainability";
import type { FormulaGroupOut, FormulaStatus } from "../api/types";

const STATUS_LABEL: Record<FormulaStatus, string> = {
  locked: "Locked",
  heuristic: "Heuristic",
  cited: "Cited",
};

const STATUS_CLASS: Record<FormulaStatus, string> = {
  locked: "border-text-heading text-text-heading",
  heuristic: "border-warning text-warning",
  cited: "border-info text-info",
};

const STATUS_EXPLAINER: Record<FormulaStatus, string> = {
  locked:
    "A fixed product decision — the same formula and weights on every repository, never tuned.",
  heuristic:
    "A documented, adjustable starting point Compass chose — a considered guess, not a proven model.",
  cited:
    "Taken directly from published research and implemented as specified, not adjusted by Compass.",
};

function section(id: string) {
  return METHODS_SECTIONS.find((s) => s.id === id);
}

/**
 * Compass's answer to "does this actually work?" (UI rebuild session 2,
 * Part E). Structured, numbered sections — no scrollytelling, unlike
 * /how-it-works. Every NUMBER on this page comes from `GET /meta/formulas`
 * at request time; the prose around it lives in `content/methods.ts`.
 */
export function MethodsPage() {
  const formulas = useFormulas();
  const groups = formulas.data?.groups ?? [];
  const activeProvider = formulas.data?.active_baseline_provider;

  const alsoMeasuredGroups = groups
    .map((g) => ({ group: g, copy: FORMULA_COPY[g.key] }))
    .filter((x) => x.copy?.alsoMeasured?.length);

  return (
    <div className="cp-prose mx-auto py-10">
      <p className="cp-label mb-2">Reference</p>
      <h1 className="font-display text-4xl font-medium tracking-tight text-text-heading">
        Methods
      </h1>
      <p className="mt-4 max-w-2xl text-lg leading-normal text-text-muted">{METHODS_INTRO}</p>

      {/* Section 1 -------------------------------------------------- */}
      <section className="mt-12 border-t border-border pt-10">
        <p className="cp-label mb-1">{section("scores")?.eyebrow}</p>
        <h2 className="font-display text-2xl text-text-heading">{section("scores")?.title}</h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-muted">
          {section("scores")?.body}
        </p>

        {formulas.isPending ? (
          <p className="mt-6 text-sm text-text-muted">Loading the live formula values…</p>
        ) : groups.length === 0 ? (
          <Alert variant="neutral" className="mt-6">
            The live formula values couldn't be loaded right now.
          </Alert>
        ) : (
          <div className="mt-6 flex flex-col gap-6">
            {groups.map((group) => (
              <FormulaGroupCard key={group.key} group={group} />
            ))}
          </div>
        )}
      </section>

      {/* Section 2 -------------------------------------------------- */}
      <section className="mt-12 border-t border-border pt-10">
        <p className="cp-label mb-1">{section("calibration")?.eyebrow}</p>
        <h2 className="font-display text-2xl text-text-heading">{section("calibration")?.title}</h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-muted">
          {section("calibration")?.body}
        </p>
        {activeProvider ? (
          <p className="mt-3 text-sm text-text">
            This deployment is currently configured to use the{" "}
            <span className="font-mono font-medium text-accent">{activeProvider}</span> provider.
          </p>
        ) : null}
        <p className="mt-4 max-w-2xl text-sm leading-relaxed text-text-muted">
          {CORPUS_DESCRIPTION}
        </p>
        <a
          href={CORPUS_REPO_LIST_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-3 flex w-fit items-center gap-1.5 font-mono text-sm text-accent hover:underline"
        >
          <ExternalLink size={13} aria-hidden="true" />
          {CORPUS_REPO_LIST_PATH}
        </a>
        <p className="mt-4 max-w-2xl text-sm leading-relaxed text-text-muted">
          {CELL_SIZE_GATE_NOTE}
        </p>
      </section>

      {/* Section 3 -------------------------------------------------- */}
      <section className="mt-12 border-t border-border pt-10">
        <p className="cp-label mb-1">{section("also-measured")?.eyebrow}</p>
        <h2 className="font-display text-2xl text-text-heading">
          {section("also-measured")?.title}
        </h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-muted">
          {section("also-measured")?.body}
        </p>
        <div className="mt-6 flex flex-col gap-5">
          {alsoMeasuredGroups.map(({ group, copy }) => (
            <div key={group.key}>
              <h3 className="font-display text-base text-text-heading">{group.label}</h3>
              {copy?.alsoMeasuredNote ? (
                <p className="mt-1 text-xs text-text-muted">{copy.alsoMeasuredNote}</p>
              ) : null}
              <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5">
                {copy?.alsoMeasured?.map((item) => (
                  <li key={item.label} className="flex items-center gap-1 text-xs text-text">
                    {item.label}
                    {item.tooltip ? (
                      <InfoTooltip label={`What is ${item.label}?`} text={TOOLTIPS[item.tooltip]} />
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      {/* Section 4 -------------------------------------------------- */}
      <section className="mt-12 border-t border-border pt-10">
        <p className="cp-label mb-1">{section("limitations")?.eyebrow}</p>
        <h2 className="font-display text-2xl text-text-heading">{section("limitations")?.title}</h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-muted">
          {section("limitations")?.body}
        </p>
        <ul className="mt-4 flex flex-col gap-3">
          {LIMITATIONS.map((item) => (
            <li key={item} className="flex gap-2 text-sm leading-relaxed text-text-muted">
              <span
                className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-warning"
                aria-hidden="true"
              />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </section>

      {/* Section 5 -------------------------------------------------- */}
      <section className="mt-12 border-t border-border pt-10">
        <p className="cp-label mb-1">{section("reproducibility")?.eyebrow}</p>
        <h2 className="font-display text-2xl text-text-heading">
          {section("reproducibility")?.title}
        </h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-muted">
          {section("reproducibility")?.body}
        </p>
        <p className="mt-4 max-w-2xl text-sm leading-relaxed text-text">
          {REPRODUCIBILITY_GUARANTEE}
        </p>
        <dl className="mt-4 flex flex-col gap-3">
          {REPRODUCIBILITY_CHANGES.map((c) => (
            <div key={c.cause} className="grid grid-cols-1 gap-1 sm:grid-cols-[220px_1fr] sm:gap-4">
              <dt className="text-xs font-medium text-text-heading">{c.cause}</dt>
              <dd className="text-xs leading-relaxed text-text-muted">{c.effect}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}

function FormulaGroupCard({ group }: { group: FormulaGroupOut }) {
  return (
    <div className="rounded-lg border border-border bg-bg-elevated p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-display text-lg text-text-heading">{group.label}</h3>
        <span
          className={`cp-label rounded-full border px-2 py-0.5 ${STATUS_CLASS[group.status]}`}
          title={STATUS_EXPLAINER[group.status]}
        >
          {STATUS_LABEL[group.status]}
        </span>
      </div>
      <p className="mt-1 text-xs text-text-muted">{STATUS_EXPLAINER[group.status]}</p>
      <p className="mt-3 font-mono text-xs leading-relaxed text-text">{group.formula}</p>
      {group.citation ? (
        <p className="mt-2 text-xs italic text-text-muted">{group.citation}</p>
      ) : null}
      <dl className="mt-4 flex flex-col gap-1.5">
        {group.constants.map((c) => (
          <div key={c.name} className="flex items-baseline justify-between gap-3">
            <dt className="font-mono text-xs text-text-muted">{c.name}</dt>
            <dd className="tabular-nums font-mono text-xs text-text">{c.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
