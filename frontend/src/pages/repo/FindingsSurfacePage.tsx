import { useEffect, useMemo, useState } from "react";
import { useOutletContext, useSearchParams } from "react-router-dom";
import {
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import {
  useFindings,
  useHygiene,
  useRepoStatus,
  useRisk,
  useSecrets,
  useTestGaps,
  useVulnerabilities,
} from "../../api/hooks";
import type {
  FindingCategory,
  FindingOut,
  HygieneEventKind,
  HygieneEventOut,
  HygieneFileOut,
  SecretHitOut,
  Severity,
  TestGapFileOut,
  VulnerabilityOut,
} from "../../api/types";
import { Alert } from "../../components/ui/Alert";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { EvidenceLink } from "../../components/EvidenceLink";
import { FindingItem } from "../../components/FindingItem";
import { HonestyNote } from "../../components/HonestyNote";
import { InfoTooltip } from "../../components/ui/InfoTooltip";
import { LoadingState } from "../../components/LoadingState";
import { NarrativeBlock } from "../../components/NarrativeBlock";
import { PartialResultNotice } from "../../components/PartialResultNotice";
import { ScoreExplainer } from "../../components/ScoreExplainer";
import { StageGate } from "../../components/StageGate";
import { HONESTY, TOOLTIPS } from "../../content/explainability";
import {
  FINDING_CATEGORY_COPY,
  HYGIENE_KIND_COPY,
  HYGIENE_KIND_LABEL,
  TEST_CLASSIFICATION_COPY,
} from "../../lib/copy";
import { SEVERITY_LABEL, formatPercent, formatScore } from "../../lib/format";
import { CHROME, SEVERITY_COLOR, rechartsTheme } from "../../lib/chartTheme";
import type { RepoOutletContext } from "../RepoLayout";

// THE governing constraint of this surface (section 5.2/RULES.md sec 12,
// Known Hazard #2): the default view shows the few things that matter,
// never a wall of everything. Ten, with an explicit "show all" affordance
// -- never quietly raised. A dedicated test asserts this exact number.
const DEFAULT_VISIBLE = 10;
const LOW_CONFIDENCE_THRESHOLD = 0.4;

const CATEGORIES: FindingCategory[] = [
  "risk",
  "architecture",
  "hidden_dependency",
  "knowledge",
  "hygiene",
  "test_gap",
  "secret",
  "vulnerability",
];
const SEVERITIES: Severity[] = ["high", "med", "low"];

const ROTATE_NOTE =
  "This credential should be rotated -- deleting the file does not remove it from history.";

const HYGIENE_KIND_ORDER: HygieneEventKind[] = ["risky_commit", "fixup_churn", "oversized"];
const HYGIENE_KIND_COLOR: Record<HygieneEventKind, string> = {
  oversized: CHROME.inkMuted,
  fixup_churn: SEVERITY_COLOR.med,
  risky_commit: SEVERITY_COLOR.high,
};

function secretRowId(hit: SecretHitOut): string {
  return `secret-${hit.commit_sha}-${hit.rule_id}`;
}
function vulnRowId(v: VulnerabilityOut): string {
  return `vuln-${v.osv_id}-${v.package_name}`;
}
function hygieneFileRowId(path: string): string {
  return `hygiene-file-${encodeURIComponent(path)}`;
}
function testGapFileRowId(path: string): string {
  return `testgap-file-${encodeURIComponent(path)}`;
}

/**
 * `/repos/:id/findings` (UI rebuild session 4, Part A) -- merges the former
 * Findings, Security, and Hygiene pages into one ranked stream plus four
 * evidence sections (secrets, vulnerabilities, commit hygiene, test
 * maintenance), filtered by `?category=`.
 *
 * Two rules govern the ranked stream and are easy to break: it is
 * SUBTRACTIVE (`DEFAULT_VISIBLE` findings by default, an explicit "show
 * all" control, never quietly raised -- see `FindingsSurfacePage.test.tsx`),
 * and it never re-sorts client-side -- `FindingsRankEngine` already
 * computed one global, cross-category rank server-side; filtering removes
 * rows, it never reorders what remains.
 *
 * Every section below gates on its OWN backend stage independently (section
 * 4.4) and must never block on the latest one -- the vulnerabilities
 * section in particular must render as a self-contained error card while
 * secrets (a different, earlier stage) renders normally when the optional
 * "security" stage failed (this is read directly off `useRepoStatus`, since
 * a failed optional stage's own `/vulnerabilities` response is an
 * honestly-empty 200, indistinguishable from "no vulnerabilities" without
 * that check).
 */
export function FindingsSurfacePage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const [searchParams] = useSearchParams();
  const [category, setCategory] = useState<FindingCategory | "">(
    (searchParams.get("category") as FindingCategory | "") ?? "",
  );
  const [severity, setSeverity] = useState<Severity | "">("");
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    const fromUrl = searchParams.get("category") as FindingCategory | "" | null;
    if (fromUrl) setCategory(fromUrl);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams.get("category")]);

  const findings = useFindings(repo.id, category || undefined, share);
  const status = useRepoStatus(repo.id, share);
  const securityStage = status.data?.stages.find((s) => s.name === "security");
  const securityFailed = securityStage?.status === "failed";

  function changeCategory(next: FindingCategory | "") {
    setCategory(next);
    setShowAll(false);
  }

  return (
    <div className="flex flex-col gap-6">
      <Card
        eyebrow="Anti-alert-fatigue spine"
        title="Findings"
        action={
          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label="Filter findings by category"
              value={category}
              onChange={(e) => changeCategory(e.target.value as FindingCategory | "")}
              className="rounded-sm border border-border-interactive bg-bg-elevated px-2 py-1 text-xs text-text"
            >
              <option value="">All categories</option>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {FINDING_CATEGORY_COPY[c]()}
                </option>
              ))}
            </select>
            <select
              aria-label="Filter findings by severity"
              value={severity}
              onChange={(e) => {
                setSeverity(e.target.value as Severity | "");
                setShowAll(false);
              }}
              className="rounded-sm border border-border-interactive bg-bg-elevated px-2 py-1 text-xs text-text"
            >
              <option value="">All severities</option>
              {SEVERITIES.map((s) => (
                <option key={s} value={s}>
                  {SEVERITY_LABEL[s]}
                </option>
              ))}
            </select>
          </div>
        }
      >
        <StageGate
          query={findings}
          loadingLabel="Loading findings…"
          emptyTitle="No findings"
          emptyMessage="Nothing rose above the noise floor for this repo yet."
          isEmpty={(data) => data.findings.length === 0}
        >
          {(data) => (
            <RankedFindingsList
              findings={data.findings}
              severity={severity}
              showAll={showAll}
              onToggleShowAll={() => setShowAll((v) => !v)}
              repoId={repo.id}
              repoUrl={repo.url}
            />
          )}
        </StageGate>
      </Card>

      <SecretsSection repoId={repo.id} repoUrl={repo.url} share={share} />
      <VulnerabilitiesSection
        repoId={repo.id}
        share={share}
        failed={securityFailed}
        error={securityStage?.error ?? null}
      />
      <HygieneSection repoId={repo.id} share={share} />
      <TestMaintenanceSection repoId={repo.id} share={share} />
      <NarrativeBlock surface="security" />
    </div>
  );
}

// --- 0. Ranked findings stream ----------------------------------------------

function RankedFindingsList({
  findings,
  severity,
  showAll,
  onToggleShowAll,
  repoId,
  repoUrl,
}: {
  findings: FindingOut[];
  severity: Severity | "";
  showAll: boolean;
  onToggleShowAll: () => void;
  repoId: string;
  repoUrl: string;
}) {
  // A pure filter (removes rows), never a sort -- `findings` arrives already
  // in the backend's one global cross-category rank; `.filter` preserves
  // that order exactly.
  const filtered = severity ? findings.filter((f) => f.severity === severity) : findings;
  const visible = showAll ? filtered : filtered.slice(0, DEFAULT_VISIBLE);
  const lowConfidenceCount = filtered.filter((f) => f.confidence < LOW_CONFIDENCE_THRESHOLD).length;

  if (filtered.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-text-muted">No findings match this filter.</p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {lowConfidenceCount > 0 ? (
        <HonestyNote
          variant="confidence-caveat"
          text={`${lowConfidenceCount} of ${filtered.length} ${
            filtered.length === 1 ? "finding is" : "findings are"
          } low-confidence -- this repository may not have enough analyzed history yet for a firm signal. Treat these as directional, not certain.`}
        />
      ) : null}

      <ul>
        {visible.map((f) => (
          <FindingItem key={f.id} finding={f} repoId={repoId} repoUrl={repoUrl} />
        ))}
      </ul>

      {filtered.length > DEFAULT_VISIBLE ? (
        <Button
          variant="secondary"
          size="sm"
          onClick={onToggleShowAll}
          className="w-fit self-center"
        >
          {showAll ? `Show top ${DEFAULT_VISIBLE} only` : `Show all ${filtered.length} findings`}
        </Button>
      ) : null}
    </div>
  );
}

// --- 1. Secrets --------------------------------------------------------------

function SecretsSection({
  repoId,
  repoUrl,
  share,
}: {
  repoId: string;
  repoUrl: string;
  share?: string;
}) {
  const secrets = useSecrets(repoId, share);
  const [searchParams] = useSearchParams();
  const targetSha = searchParams.get("sha");

  useEffect(() => {
    if (!targetSha) return;
    const el = document.querySelector(`[data-sha="${CSS.escape(targetSha)}"]`);
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [targetSha, secrets.data]);

  return (
    <StageGate
      query={secrets}
      loadingLabel="Scanning history for secrets…"
      emptyTitle="Secrets"
      emptyMessage="No credential-shaped secrets were found in this repository's history."
      isEmpty={(data) => data.hits.length === 0}
    >
      {(data) => {
        const { hits, truncated, truncation_reason } = data;
        const inHistoryOnly = hits.filter((h) => !h.still_in_head);
        const stillInHead = hits.filter((h) => h.still_in_head);

        return (
          <div className="flex flex-col gap-4">
            {truncated ? (
              <PartialResultNotice
                shown={hits.length}
                total={hits.length}
                itemLabel="secret hits"
                capped
              />
            ) : null}
            {truncated && truncation_reason ? (
              <p className="-mt-2 text-xs text-text-muted">{truncation_reason}</p>
            ) : null}

            {/* THE product's sharpest differentiator: first, and visually
                dominant -- a naive current-tree scanner would never find
                these, because the file has already been deleted or edited. */}
            <Card
              title="Removed from code but still in git history"
              action={
                <span className="cp-label text-text-muted">
                  {inHistoryOnly.length} credential{inHistoryOnly.length === 1 ? "" : "s"}
                </span>
              }
              className="border-2 border-danger ring-2 ring-danger-bg"
            >
              <HonestyNote
                variant="scope-limitation"
                text={HONESTY.secretHistoryStillRecoverable}
              />
              {inHistoryOnly.length === 0 ? (
                <p className="mt-2 text-sm text-text-muted">
                  None -- every detected secret is still present in the current tree (see below).
                </p>
              ) : (
                <ul className="mt-2 flex flex-col divide-y divide-border">
                  {inHistoryOnly.map((h) => (
                    <SecretRow key={secretRowId(h)} hit={h} repoUrl={repoUrl} />
                  ))}
                </ul>
              )}
            </Card>

            <Card
              title="Still present in the current codebase"
              action={
                <span className="cp-label text-text-muted">
                  {stillInHead.length} credential{stillInHead.length === 1 ? "" : "s"}
                </span>
              }
            >
              {stillInHead.length === 0 ? (
                <p className="text-sm text-text-muted">None currently in the checked-out tree.</p>
              ) : (
                <ul className="flex flex-col divide-y divide-border">
                  {stillInHead.map((h) => (
                    <SecretRow key={secretRowId(h)} hit={h} repoUrl={repoUrl} />
                  ))}
                </ul>
              )}
            </Card>
          </div>
        );
      }}
    </StageGate>
  );
}

function SecretRow({ hit, repoUrl }: { hit: SecretHitOut; repoUrl: string }) {
  return (
    <li data-sha={hit.commit_sha} className="flex flex-col gap-1.5 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-text">{hit.description}</span>
        {hit.redacted_preview ? (
          <span className="cp-stat rounded-xs bg-bg-inset px-1.5 py-0.5 text-xs text-text-muted">
            {hit.redacted_preview}
          </span>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-text-muted">
        <EvidenceLink repoUrl={repoUrl} sha={hit.commit_sha} />
        <span>{new Date(hit.committed_at).toLocaleDateString()}</span>
        {hit.file_path ? (
          <span className="truncate font-mono" title={hit.file_path}>
            {hit.file_path}
          </span>
        ) : null}
      </div>
      <p className="text-xs text-danger">{ROTATE_NOTE}</p>
    </li>
  );
}

// --- 2. Vulnerabilities -------------------------------------------------------

const VULN_SEVERITY_ORDER: (Severity | "unknown")[] = ["high", "med", "low", "unknown"];

function VulnerabilitiesSection({
  repoId,
  share,
  failed,
  error,
}: {
  repoId: string;
  share?: string;
  failed: boolean;
  error: string | null;
}) {
  const vulns = useVulnerabilities(repoId, share);
  const [searchParams] = useSearchParams();
  const targetOsv = searchParams.get("osv");

  useEffect(() => {
    if (!targetOsv) return;
    const el = document.querySelector(`[data-osv="${CSS.escape(targetOsv)}"]`);
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [targetOsv, vulns.data]);

  // Hooks run unconditionally, above every early return -- computed over
  // whatever's available yet, not only once real data has arrived.
  const vulnerabilities = vulns.data?.kind === "data" ? vulns.data.data.vulnerabilities : [];
  const bySeverity = useMemo(() => {
    const groups: Partial<Record<Severity | "unknown", VulnerabilityOut[]>> = {};
    for (const v of vulnerabilities) {
      const key = (v.severity as Severity | "unknown") ?? "unknown";
      (groups[key] ??= []).push(v);
    }
    return groups;
  }, [vulnerabilities]);

  // The visible payoff of per-stage failure isolation (session 10): this
  // section renders a self-contained error card while Secrets, a different
  // and earlier stage, renders normally above it.
  if (failed) {
    return (
      <Card title="Dependency vulnerabilities">
        <Alert variant="danger">
          <p className="font-medium">This section couldn't be computed</p>
          <p className="mt-1 text-xs opacity-80">
            {error ??
              "The vulnerability lookup (OSV.dev) failed for this run. The rest of this analysis is unaffected -- secrets above were computed independently."}
          </p>
        </Alert>
      </Card>
    );
  }

  if (vulns.isPending) return <LoadingState label="Loading dependency vulnerabilities…" />;
  if (vulns.isError) {
    return (
      <Card title="Dependency vulnerabilities">
        <p className="text-sm text-danger">
          {vulns.error instanceof Error ? vulns.error.message : "Couldn't load vulnerabilities."}
        </p>
      </Card>
    );
  }
  if (vulns.data.kind === "pending")
    return <LoadingState label="Loading dependency vulnerabilities…" />;

  const { no_supported_manifest } = vulns.data.data;

  if (no_supported_manifest) {
    return (
      <Card title="Dependency vulnerabilities">
        <div className="rounded-md border border-dashed border-border-strong p-4 text-sm">
          <p className="font-medium text-text">No supported dependency manifest found</p>
          <HonestyNote
            variant="scope-limitation"
            text={HONESTY.noSupportedManifestDistinctFromZero}
            className="mt-2"
          />
          <ul className="mt-2 list-inside list-disc text-text-muted">
            <li>requirements*.txt (Python)</li>
            <li>pyproject.toml (Python)</li>
            <li>package-lock.json (npm)</li>
            <li>pom.xml (Maven)</li>
          </ul>
        </div>
      </Card>
    );
  }

  if (vulnerabilities.length === 0) {
    return (
      <Card title="Dependency vulnerabilities" eyebrow="Checked against OSV.dev">
        <p className="py-6 text-center text-sm text-text-muted">
          No known vulnerabilities were found in this repository's declared dependencies.
        </p>
      </Card>
    );
  }

  return (
    <Card
      title="Dependency vulnerabilities"
      eyebrow={`${vulnerabilities.length} match${vulnerabilities.length === 1 ? "" : "es"} against OSV.dev`}
    >
      <div className="flex flex-col gap-4">
        {VULN_SEVERITY_ORDER.filter((s) => bySeverity[s]?.length).map((sev) => (
          <div key={sev} className="flex flex-col gap-2">
            <h3 className="cp-label text-text-muted">
              {sev === "unknown" ? "Unknown severity" : SEVERITY_LABEL[sev]} (
              {bySeverity[sev]!.length})
            </h3>
            <ul className="flex flex-col divide-y divide-border">
              {bySeverity[sev]!.map((v) => (
                <VulnRow key={vulnRowId(v)} vuln={v} />
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Card>
  );
}

function VulnRow({ vuln }: { vuln: VulnerabilityOut }) {
  return (
    <li data-osv={vuln.osv_id} className="flex flex-col gap-1 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm font-medium text-text">
          {vuln.package_name}@{vuln.version}
        </span>
        {/* Direct vs transitive is a different remediation problem: a direct
            dep can be bumped in your own manifest; a transitive one needs
            its parent updated (or an override). */}
        <span title={TOOLTIPS.dependencyDirectness}>
          <Badge tone={vuln.is_direct ? "accent" : "neutral"}>
            {vuln.is_direct ? "direct dependency" : "transitive dependency"}
          </Badge>
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <a
          href={`https://osv.dev/vulnerability/${encodeURIComponent(vuln.osv_id)}`}
          target="_blank"
          rel="noreferrer"
          className="font-mono text-accent hover:underline"
        >
          {vuln.osv_id}
        </a>
        {vuln.aliases.map((a) => (
          <a
            key={a}
            href={`https://osv.dev/vulnerability/${encodeURIComponent(a)}`}
            target="_blank"
            rel="noreferrer"
            className="font-mono text-text-muted hover:underline"
          >
            {a}
          </a>
        ))}
        {vuln.cvss_score != null ? (
          <span className="text-text-muted">CVSS {vuln.cvss_score.toFixed(1)}</span>
        ) : null}
      </div>
      <p className="text-sm text-text-muted">{vuln.summary}</p>
      <p className="text-xs text-text-muted">
        {vuln.fixed_version
          ? `Fix available: upgrade to ${vuln.fixed_version}.`
          : "No fixed version has been published yet."}
      </p>
    </li>
  );
}

// --- 3. Commit hygiene ---------------------------------------------------------

function HygieneSection({ repoId, share }: { repoId: string; share?: string }) {
  const hygiene = useHygiene(repoId, share);
  const [searchParams] = useSearchParams();
  const highlightPath =
    searchParams.get("category") === "hygiene" ? searchParams.get("file") : null;

  useEffect(() => {
    if (!highlightPath) return;
    document
      .getElementById(hygieneFileRowId(highlightPath))
      ?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [highlightPath]);

  return (
    <StageGate
      query={hygiene}
      loadingLabel="Loading commit hygiene…"
      emptyTitle="No hygiene signal yet"
      isEmpty={(data) => Object.values(data.events_by_kind).every((v) => !v || v.length === 0)}
    >
      {(data) => (
        <div className="flex flex-col gap-4">
          <EventTimeline eventsByKind={data.events_by_kind} />

          {data.insufficient_history_for_oversized ? (
            <p className="rounded-md bg-bg-inset px-3 py-2 text-xs text-text-muted">
              Too few commits to compute a reliable "oversized commit" percentile for this repo yet.
            </p>
          ) : null}

          <InstabilityRanking files={data.files} highlightPath={highlightPath} />
        </div>
      )}
    </StageGate>
  );
}

function EventTimeline({
  eventsByKind,
}: {
  eventsByKind: Partial<Record<HygieneEventKind, HygieneEventOut[]>>;
}) {
  const points = useMemo(() => {
    const all: { x: number; y: number; kind: HygieneEventKind; event: HygieneEventOut }[] = [];
    HYGIENE_KIND_ORDER.forEach((kind, laneIndex) => {
      for (const event of eventsByKind[kind] ?? []) {
        const t = Date.parse(event.occurred_at);
        if (!Number.isNaN(t)) all.push({ x: t, y: laneIndex, kind, event });
      }
    });
    return all;
  }, [eventsByKind]);

  if (points.length === 0) {
    return (
      <Card title="Commit hygiene timeline">
        <p className="py-6 text-center text-sm text-text-muted">
          No oversized commits, fixup clusters, or risky commits were detected.
        </p>
      </Card>
    );
  }

  return (
    <Card
      title="Commit hygiene timeline"
      eyebrow="Real detected events -- not a fabricated commit-volume curve"
    >
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
            <CartesianGrid {...rechartsTheme.grid} />
            <XAxis
              type="number"
              dataKey="x"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(v: number) => new Date(v).toLocaleDateString()}
              tick={rechartsTheme.axis.tick}
              stroke={rechartsTheme.axis.stroke}
            />
            <YAxis
              type="number"
              dataKey="y"
              domain={[-0.5, HYGIENE_KIND_ORDER.length - 0.5]}
              ticks={HYGIENE_KIND_ORDER.map((_, i) => i)}
              tickFormatter={(v: number) => HYGIENE_KIND_LABEL[HYGIENE_KIND_ORDER[v]]?.() ?? ""}
              width={110}
              tick={rechartsTheme.axis.tick}
              stroke={rechartsTheme.axis.stroke}
            />
            <ZAxis range={[50, 50]} />
            <Tooltip
              cursor={{ strokeDasharray: "3 3" }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0].payload as (typeof points)[number];
                return (
                  <div className="max-w-xs border border-border bg-bg-elevated px-2 py-1.5 text-xs">
                    <p className="font-medium text-text">{HYGIENE_KIND_LABEL[p.kind]()}</p>
                    <p className="mt-0.5 text-text-muted">
                      {HYGIENE_KIND_COPY[p.kind](p.event.detail)}
                    </p>
                  </div>
                );
              }}
            />
            {HYGIENE_KIND_ORDER.map((kind) => (
              <Scatter
                key={kind}
                data={points.filter((p) => p.kind === kind)}
                fill={HYGIENE_KIND_COLOR[kind]}
              />
            ))}
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <HonestyNote
        variant="scope-limitation"
        text={HONESTY.timeOfDayExcludedFromHygiene}
        className="mt-2"
      />
    </Card>
  );
}

function InstabilityRanking({
  files,
  highlightPath,
}: {
  files: HygieneFileOut[];
  highlightPath: string | null;
}) {
  const ranked = useMemo(
    () =>
      [...files]
        .filter((f) => f.instability_score != null)
        .sort((a, b) => (b.instability_score ?? 0) - (a.instability_score ?? 0)),
    [files],
  );
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? ranked : ranked.slice(0, 15);

  if (ranked.length === 0) return null;

  const topScore = ranked[0];

  return (
    <Card title="Per-file instability" eyebrow={`${ranked.length} files with a computed score`}>
      <ScoreExplainer
        formulaKey="hygiene"
        contributions={[]}
        alsoMeasured={[
          {
            label: "This file's own oversized / fixup / revert counts",
            value: `${topScore.oversized_commit_count ?? 0} / ${topScore.fixup_commit_count ?? 0} / ${topScore.revert_cycle_count ?? 0}`,
            tooltip: "instability",
          },
        ]}
      />
      <ul className="mt-3 flex flex-col divide-y divide-border">
        {visible.map((f) => (
          <li
            key={f.file_path}
            id={hygieneFileRowId(f.file_path)}
            className={`flex flex-wrap items-center justify-between gap-2 py-2 text-sm ${
              highlightPath === f.file_path ? "bg-accent-bg" : ""
            }`}
          >
            <span
              className="max-w-[320px] truncate font-mono text-xs text-text-muted"
              title={f.file_path}
            >
              {f.file_path}
            </span>
            <span className="flex shrink-0 items-center gap-3 text-xs text-text-muted">
              <span className="flex items-center gap-1.5">
                <div className="h-1.5 w-16 overflow-hidden rounded-full bg-bg-inset">
                  <div
                    className="h-full rounded-full bg-warning"
                    style={{ width: `${Math.round((f.instability_score ?? 0) * 100)}%` }}
                  />
                </div>
                {formatScore(f.instability_score ?? 0, 2)}
              </span>
              <span>{f.oversized_commit_count ?? 0} oversized</span>
              <span>{f.fixup_commit_count ?? 0} fixup</span>
              <span>{f.revert_cycle_count ?? 0} reverts</span>
            </span>
          </li>
        ))}
      </ul>
      {ranked.length > 15 ? (
        <Button
          variant="secondary"
          size="sm"
          onClick={() => setShowAll((v) => !v)}
          className="mt-2"
        >
          {showAll ? "Show top 15 only" : `Show all ${ranked.length} files`}
        </Button>
      ) : null}
    </Card>
  );
}

// --- 4. Test maintenance --------------------------------------------------------

function TestMaintenanceSection({ repoId, share }: { repoId: string; share?: string }) {
  const testGaps = useTestGaps(repoId, share);
  const risk = useRisk(repoId, share);
  const [searchParams] = useSearchParams();
  const highlightPath =
    searchParams.get("category") === "test_gap" ? searchParams.get("file") : null;

  useEffect(() => {
    if (!highlightPath) return;
    document
      .getElementById(testGapFileRowId(highlightPath))
      ?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [highlightPath]);

  const riskByPath = useMemo(() => {
    const map = new Map<string, number>();
    if (risk.data?.kind === "data") {
      for (const f of risk.data.data.files) map.set(f.file_path, f.risk_score);
    }
    return map;
  }, [risk.data]);

  return (
    <StageGate
      query={testGaps}
      loadingLabel="Loading test maintenance data…"
      emptyTitle="No test-mapped files"
      isEmpty={(data) => data.files.length === 0}
    >
      {(data) => {
        const counts: Record<TestGapFileOut["classification"], number> = {
          no_test: 0,
          stale_test: 0,
          tracked: 0,
        };
        for (const f of data.files) counts[f.classification]++;
        const total = data.files.length || 1;

        const topGapsWithRisk = data.files
          .filter((f) => f.classification !== "tracked" && riskByPath.has(f.file_path))
          .map((f) => ({ ...f, risk_score: riskByPath.get(f.file_path)! }))
          .sort((a, b) => b.risk_score - a.risk_score)
          .slice(0, 10);

        return (
          <Card
            title="Test maintenance"
            eyebrow="Whether tests change alongside the code they cover"
          >
            {/* The API's own limitation string, verbatim, above the fold --
                "untested code" is shorter and reads better, and it is
                wrong: this measures maintenance, never coverage. */}
            <HonestyNote variant="scope-limitation" text={data.limitation} className="mb-3" />

            <ScoreExplainer formulaKey="test_gaps" contributions={[]} />

            <div className="mb-4 mt-3 flex h-3 w-full overflow-hidden rounded-full bg-bg-inset">
              <div
                className="h-full bg-danger"
                style={{ width: `${(counts.no_test / total) * 100}%` }}
                title={`${TEST_CLASSIFICATION_COPY.no_test()} (${counts.no_test})`}
              />
              <div
                className="h-full bg-warning"
                style={{ width: `${(counts.stale_test / total) * 100}%` }}
                title={`${TEST_CLASSIFICATION_COPY.stale_test()} (${counts.stale_test})`}
              />
              <div
                className="h-full bg-success"
                style={{ width: `${(counts.tracked / total) * 100}%` }}
                title={`${TEST_CLASSIFICATION_COPY.tracked()} (${counts.tracked})`}
              />
            </div>
            <div className="mb-4 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-muted">
              <span>No mapped test: {counts.no_test}</span>
              <span>Rarely changes with code: {counts.stale_test}</span>
              <span>Changes with code: {counts.tracked}</span>
              <span className="flex items-center gap-1 text-text-muted">
                · mean co-change ratio {formatPercent(data.mean_test_cochange_ratio)}
                <InfoTooltip
                  label="What is test co-change ratio?"
                  text={TOOLTIPS.testCochangeRatio}
                />
              </span>
            </div>

            <h3 className="cp-label mb-1.5 text-text-muted">
              Top-risk files with a maintenance gap
            </h3>
            {topGapsWithRisk.length === 0 ? (
              <p className="text-sm text-text-muted">
                No top-risk file currently has a test-maintenance gap.
              </p>
            ) : (
              <ul className="flex flex-col divide-y divide-border">
                {topGapsWithRisk.map((f) => (
                  <li
                    key={f.file_path}
                    id={testGapFileRowId(f.file_path)}
                    className={`flex flex-wrap items-center justify-between gap-2 py-2 text-sm ${
                      highlightPath === f.file_path ? "bg-accent-bg" : ""
                    }`}
                  >
                    <span
                      className="max-w-[280px] truncate font-mono text-xs text-text-muted"
                      title={f.file_path}
                    >
                      {f.file_path}
                    </span>
                    <span className="shrink-0 text-xs text-text-muted">
                      {TEST_CLASSIFICATION_COPY[f.classification]()} · risk{" "}
                      {formatScore(f.risk_score, 2)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        );
      }}
    </StageGate>
  );
}
