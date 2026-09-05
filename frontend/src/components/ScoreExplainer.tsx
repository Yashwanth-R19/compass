import { Expander } from "./motion/Expander";
import { InfoTooltip } from "./ui/InfoTooltip";
import { useFormulas } from "../api/hooks";
import { CALIBRATION_COPY, FORMULA_COPY, TOOLTIPS } from "../content/explainability";
import type { TooltipKey } from "../content/explainability";

const CAP_EPSILON = 1e-6;

export interface ScoreExplainerContribution {
  /** Must match a `FormulaConstant.name` in this `formulaKey`'s
   * GET /meta/formulas group -- ScoreExplainer looks the weight up from
   * there (never a hardcoded copy, section 5.4) and pairs it with the
   * caller-supplied, already-normalized input value. */
  constantName: string;
  label: string;
  tooltip?: TooltipKey;
  /** This term's own normalized [0, 1] input value (already run through
   * norm()) -- ScoreExplainer computes `weight x normalizedValue` for the
   * arithmetic line and the contribution bar. */
  normalizedValue: number;
  /** A plain-English sentence grounded in real counts, or `null`/`undefined`
   * when the underlying counts are unavailable for this subject. Renders
   * nothing in that case -- never "undefined", never an invented number
   * (section 5.2 item 4). */
  detail?: string | null;
}

export interface ScoreExplainerAlsoMeasuredValue {
  label: string;
  value: string;
  tooltip?: TooltipKey;
}

export interface ScoreExplainerProps {
  /** The FormulaGroup key this score belongs to (matches GET
   * /meta/formulas's `groups[].key` AND `content/explainability.ts`'s
   * `FORMULA_COPY` key) -- e.g. "risk", "health", "onboarding_difficulty". */
  formulaKey: string;
  /** The response's own `calibration` field ("heuristic" | "corpus"),
   * when this score is calibration-aware. Omit for a formula with no
   * baseline-provider seam (e.g. coupling, subsystems). */
  calibration?: string | null;
  contributions: ScoreExplainerContribution[];
  /** The formula's own stated cap and the raw, pre-cap sum -- only when a
   * cap genuinely exists. The note renders only when `rawSum` truly
   * exceeds `cappedAt` (a small epsilon guards float noise), never on
   * every render (section 5.2 item 5). */
  cap?: { cappedAt: number; rawSum: number };
  alsoMeasured?: ScoreExplainerAlsoMeasuredValue[];
  defaultOpen?: boolean;
}

/**
 * The ONE generic "How this is calculated" expander (section 5.2) --
 * every score on every surface uses this, never a page-local
 * reimplementation. Built on `Expander`'s pure-CSS disclosure.
 *
 * Every formula constant it renders comes from `GET /meta/formulas`
 * (`useFormulas`), never a value written in this file (section 5.4). When
 * that request hasn't resolved, or fails, or this `formulaKey` isn't in the
 * response, ScoreExplainer degrades to `FORMULA_COPY[formulaKey].summary`
 * -- a qualitative, NUMBER-FREE sentence -- and omits the entire numeric
 * breakdown (the range note, calibration line, contribution rows and
 * capped-at note), rather than falling back to a hardcoded copy of the
 * weights.
 */
export function ScoreExplainer({
  formulaKey,
  calibration,
  contributions,
  cap,
  alsoMeasured,
  defaultOpen = false,
}: ScoreExplainerProps) {
  const formulas = useFormulas();
  const group = formulas.data?.groups.find((g) => g.key === formulaKey);
  const copy = FORMULA_COPY[formulaKey];

  const constantValue = (name: string): number | null => {
    const c = group?.constants.find((c) => c.name === name);
    return typeof c?.value === "number" ? c.value : null;
  };

  // Every contribution this component can actually price out -- one with no
  // matching constant in the live response (formulas unavailable, or the
  // group/constant genuinely doesn't exist) is silently excluded from the
  // numeric breakdown rather than rendered with a missing weight.
  const priced = contributions
    .map((c) => ({ ...c, weight: constantValue(c.constantName) }))
    .filter((c): c is typeof c & { weight: number } => c.weight !== null);

  const products = priced.map((c) => c.weight * c.normalizedValue);
  const total = products.reduce((sum, p) => sum + p, 0);
  const maxProduct = products.length > 0 ? Math.max(...products) : null;

  const showNumericBreakdown = Boolean(group) && priced.length === contributions.length;
  const capExceeded = cap != null && cap.rawSum > cap.cappedAt + CAP_EPSILON;
  const calibrationText =
    calibration === "heuristic" || calibration === "corpus" ? CALIBRATION_COPY[calibration] : null;

  return (
    <Expander
      defaultOpen={defaultOpen}
      trigger="How this is calculated"
      className="mt-2 border-t border-border pt-3"
    >
      <div className="flex flex-col gap-3 pb-1 pt-2 text-sm">
        {/* 1. Formula sentence -- the real numeric formula from the API when
            available, otherwise the qualitative, number-free summary. */}
        {group ? (
          <p className="font-mono text-xs leading-relaxed text-text">{group.formula}</p>
        ) : (
          <p className="text-text-muted">{copy?.summary}</p>
        )}

        {/* A cited formula (e.g. degree of authorship) is marked and sourced
            explicitly here -- this is not Compass's own invention, and the
            distinction between "we decided this" and "the literature
            established this" is exactly the credibility this component
            exists to carry (section 5.1/5.2 -- three visually/verbally
            distinct statuses). */}
        {group?.status === "cited" && group.citation ? (
          <p className="flex items-start gap-1.5 text-xs text-text-muted">
            <span className="cp-label shrink-0 text-accent">Cited</span>
            <span>{group.citation}</span>
          </p>
        ) : null}

        {/* 2. Range note */}
        {copy ? <p className="text-xs text-text-muted">{copy.rangeNote}</p> : null}

        {/* 3. Calibration line */}
        {calibrationText ? <p className="text-xs text-text-muted">{calibrationText}</p> : null}

        {/* 4. Contribution rows -- only when every term could be priced from
            the live response; a partial breakdown would misrepresent the
            total. */}
        {showNumericBreakdown ? (
          <div className="flex flex-col gap-4">
            {priced.map((c, i) => {
              const product = products[i];
              const share = total > 0 ? product / total : 0;
              const isLargest = maxProduct !== null && product === maxProduct;
              return (
                <div key={c.constantName} className="flex flex-col gap-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1 text-xs text-text">
                      {c.label}
                      {c.tooltip ? (
                        <InfoTooltip label={`What is ${c.label}?`} text={TOOLTIPS[c.tooltip]} />
                      ) : null}
                    </span>
                    <span
                      className={`tabular-nums font-mono text-xs ${
                        isLargest ? "font-semibold text-text-heading" : "text-text-muted"
                      }`}
                    >
                      {c.weight.toFixed(2)} x {c.normalizedValue.toFixed(3)} = {product.toFixed(3)}
                    </span>
                  </div>
                  <div
                    className="h-1.5 w-full overflow-hidden rounded-full bg-bg-inset"
                    role="presentation"
                  >
                    <div
                      className={`h-full rounded-full ${isLargest ? "bg-accent" : "bg-border-strong"}`}
                      style={{ width: `${Math.min(100, Math.max(0, share * 100))}%` }}
                    />
                  </div>
                  {c.detail ? <p className="text-xs text-text-muted">{c.detail}</p> : null}
                </div>
              );
            })}
          </div>
        ) : null}

        {/* 5. Capped-at note */}
        {capExceeded && cap ? (
          <p className="text-xs text-warning">
            Capped at {cap.cappedAt} — the raw sum was {cap.rawSum.toFixed(2)}.
          </p>
        ) : null}

        {/* 6. Also measured (not scored) */}
        {alsoMeasured?.length || copy?.alsoMeasuredNote ? (
          <div className="mt-1 border-t border-border pt-3">
            <p className="cp-label mb-2 text-text-muted">Also measured (not scored)</p>
            {copy?.alsoMeasuredNote ? (
              <p className="mb-2 text-xs text-text-muted">{copy.alsoMeasuredNote}</p>
            ) : null}
            {alsoMeasured?.length ? (
              <dl className="flex flex-col gap-1.5">
                {alsoMeasured.map((item) => (
                  <div key={item.label} className="flex items-center justify-between gap-2">
                    <dt className="flex items-center gap-1 text-xs text-text-muted">
                      {item.label}
                      {item.tooltip ? (
                        <InfoTooltip
                          label={`What is ${item.label}?`}
                          text={TOOLTIPS[item.tooltip]}
                        />
                      ) : null}
                    </dt>
                    <dd className="tabular-nums font-mono text-xs text-text">{item.value}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
          </div>
        ) : null}
      </div>
    </Expander>
  );
}
