import { useEffect, useMemo, useState } from "react";
import { Link, useOutletContext, useSearchParams } from "react-router-dom";
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
  useBenchmark,
  useFindings,
  useHygiene,
  useRepoStatus,
  useRisk,
  useSecrets,
  useVulnerabilities,
} from "../../api/hooks";
import type {
  BenchmarkResponse,
  FindingCategory,
  FindingOut,
  HygieneEventKind,
  HygieneEventOut,
  HygieneFileOut,
  RiskFileOut,
  RiskResponse,
  SecretHitOut,
  Severity,
  VulnerabilityOut,
} from "../../api/types";
import { Alert } from "../../components/ui/Alert";
import { Badge } from "../../components/ui/Badge";
import { Card } from "../../components/ui/Card";
import { ConfidenceMeter } from "../../components/ConfidenceMeter";
import { EvidenceLink } from "../../components/EvidenceLink";
import { Expander } from "../../components/motion/Expander";
import { FindingItem } from "../../components/FindingItem";
import { HonestyNote } from "../../components/HonestyNote";
import { InfoTooltip } from "../../components/ui/InfoTooltip";
import { LoadingState } from "../../components/LoadingState";
import { MetricRow } from "../../components/MetricRow";
import { PartialResultNotice } from "../../components/PartialResultNotice";
import { AnimatedList } from "../../reactbits/AnimatedList";
import { Reveal } from "../../components/motion/Reveal";
import { ScoreExplainer } from "../../components/ScoreExplainer";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { StageGate } from "../../components/StageGate";
import { HONESTY, TOOLTIPS } from "../../content/explainability";
import type { TooltipKey } from "../../content/explainability";
import { CORPUS_REPO_LIST_URL } from "../../content/methods";
import { FINDING_CATEGORY_COPY, HYGIENE_KIND_COPY, HYGIENE_KIND_LABEL } from "../../lib/copy";
import { confidenceLabel, SEVERITY_LABEL, formatPercent, formatScore } from "../../lib/format";
import { CHROME, CONFIDENCE_COLOR, SEVERITY_COLOR, rechartsTheme } from "../../lib/chartTheme";
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
const HYGIENE_KIND_TOOLTIP: Record<HygieneEventKind, TooltipKey> = {
  oversized: "oversizedCommit",
  fixup_churn: "fixupChurn",
  risky_commit: "riskyCommit",
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

type FindingsView = "findings" | "risk" | "benchmark";

function isFindingsView(v: string | null): v is FindingsView {
  return v === "findings" || v === "risk" || v === "benchmark";
}

/**
 * `/repos/:id/findings` (rebuild spec section 4.4) -- "what's wrong with
 * it." The ranked findings stream plus Risk and Benchmark as views inside
 * this one surface (`?view=findings|risk|benchmark`, findings is the
 * default), and four evidence sections beneath the stream (secrets,
 * vulnerabilities, commit hygiene), filtered by `?category=`.
 *
 * Two rules govern the ranked stream and are easy to break: it is
 * SUBTRACTIVE (`DEFAULT_VISIBLE` findings by default, an explicit "show
 * all" control, never quietly raised), and it never re-sorts client-side --
 * `FindingsRankEngine` already computed one global, cross-category rank
 * server-side; filtering removes rows, it never reorders what remains.
 *
 * Every section below gates on its OWN backend stage independently and
 * must never block on the latest one -- the vulnerabilities section in
 * particular must render as a self-contained error card while secrets (a
 * different, earlier stage) renders normally when the optional "security"
 * stage failed (this is read directly off `useRepoStatus`, since a failed
 * optional stage's own `/vulnerabilities` response is an honestly-empty
 * 200, indistinguishable from "no vulnerabilities" without that check).
 */
export function FindingsSurfacePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlView = searchParams.get("view");
  const [view, setView] = useState<FindingsView>(isFindingsView(urlView) ? urlView : "findings");

  function changeView(next: string) {
    setView(next as FindingsView);
    setSearchParams(
      (prev) => {
        const merged = new URLSearchParams(prev);
        merged.set("view", next);
        return merged;
      },
      { replace: true },
    );
  }

  const activeView = isFindingsView(urlView) ? urlView : view;

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-text-muted">
        Every flagged issue this analysis surfaced, ranked by severity, plus the hotspot ranking and
        a comparison against similar repositories.
      </p>
      <SegmentedControl
        aria-label="Findings view"
        value={activeView}
        onValueChange={changeView}
        options={[
          { value: "findings", label: "Findings" },
          { value: "risk", label: "Risk" },
          { value: "benchmark", label: "Benchmark" },
        ]}
      />
      {activeView === "risk" ? (
        <HotspotsTab />
      ) : activeView === "benchmark" ? (
        <BenchmarkTab />
      ) : (
        <FindingsStreamView />
      )}
    </div>
  );
}

function FindingsStreamView() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const [searchParams] = useSearchParams();
  const [category, setCategory] = useState<FindingCategory | "">(
    (searchParams.get("category") as FindingCategory | "") ?? "",
  );
  const [severity, setSeverity] = useState<Severity | "">("");

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
              onChange={(e) => setSeverity(e.target.value as Severity | "")}
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
    </div>
  );
}

// --- 0. Ranked findings stream ----------------------------------------------

function RankedFindingsList({
  findings,
  severity,
  repoId,
  repoUrl,
}: {
  findings: FindingOut[];
  severity: Severity | "";
  repoId: string;
  repoUrl: string;
}) {
  // A pure filter (removes rows), never a sort -- `findings` arrives already
  // in the backend's one global cross-category rank; `.filter` preserves
  // that order exactly.
  const filtered = severity ? findings.filter((f) => f.severity === severity) : findings;
  const visible = filtered.slice(0, DEFAULT_VISIBLE);
  const rest = filtered.slice(DEFAULT_VISIBLE);
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

      <AnimatedList
        items={visible}
        keyFor={(f) => f.id}
        renderItem={(f) => <FindingItem finding={f} repoId={repoId} repoUrl={repoUrl} />}
      />

      {rest.length > 0 ? (
        // Keyed by severity so switching the filter starts collapsed again,
        // rather than an Expander instance carrying its open state across
        // an unrelated filter change.
        <Expander
          key={severity}
          trigger={`${rest.length} more finding${rest.length === 1 ? "" : "s"}`}
        >
          <ul className="pt-1">
            {rest.map((f) => (
              <li key={f.id}>
                <FindingItem finding={f} repoId={repoId} repoUrl={repoUrl} />
              </li>
            ))}
          </ul>
        </Expander>
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
                <AnimatedList
                  items={inHistoryOnly}
                  keyFor={secretRowId}
                  className="mt-2 flex flex-col divide-y divide-border"
                  renderItem={(h) => <SecretRow hit={h} repoUrl={repoUrl} />}
                />
              )}
            </Card>

            <Card
              title="Still present in the current codebase"
              action={
                <span className="flex items-center gap-1.5">
                  <span className="cp-label text-text-muted">
                    {stillInHead.length} credential{stillInHead.length === 1 ? "" : "s"}
                  </span>
                  <InfoTooltip label="How is this determined?" text={TOOLTIPS.stillInHead} />
                </span>
              }
            >
              {stillInHead.length === 0 ? (
                <p className="text-sm text-text-muted">None currently in the checked-out tree.</p>
              ) : (
                <AnimatedList
                  items={stillInHead}
                  keyFor={secretRowId}
                  className="flex flex-col divide-y divide-border"
                  renderItem={(h) => <SecretRow hit={h} repoUrl={repoUrl} />}
                />
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
    <div data-sha={hit.commit_sha} className="flex flex-col gap-1.5 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-text">{hit.description}</span>
        {hit.redacted_preview ? (
          <span className="flex items-center gap-1">
            <span className="cp-stat rounded-xs bg-bg-inset px-1.5 py-0.5 text-xs text-text-muted">
              {hit.redacted_preview}
            </span>
            <InfoTooltip label="Why is only a preview shown?" text={TOOLTIPS.secretFingerprint} />
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
    </div>
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
      action={
        <InfoTooltip label="How is severity determined?" text={TOOLTIPS.vulnerabilitySeverity} />
      }
    >
      <div className="flex flex-col gap-4">
        {VULN_SEVERITY_ORDER.filter((s) => bySeverity[s]?.length).map((sev) => (
          <div key={sev} className="flex flex-col gap-2">
            <h3 className="cp-label text-text-muted">
              {sev === "unknown" ? "Unknown severity" : SEVERITY_LABEL[sev]} (
              {bySeverity[sev]!.length})
            </h3>
            <AnimatedList
              items={bySeverity[sev]!}
              keyFor={vulnRowId}
              className="flex flex-col divide-y divide-border"
              renderItem={(v) => <VulnRow vuln={v} />}
            />
          </div>
        ))}
      </div>
    </Card>
  );
}

function VulnRow({ vuln }: { vuln: VulnerabilityOut }) {
  return (
    <div data-osv={vuln.osv_id} className="flex flex-col gap-1 py-2.5">
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
    </div>
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
      emptyMessage="No oversized commits, fixup clusters, or risky commits were detected in this repository's history."
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
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5">
        {HYGIENE_KIND_ORDER.map((kind) => (
          <span key={kind} className="flex items-center gap-1 text-xs text-text-muted">
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: HYGIENE_KIND_COLOR[kind] }}
              aria-hidden="true"
            />
            {HYGIENE_KIND_LABEL[kind]()}
            <InfoTooltip
              label={`What is a ${HYGIENE_KIND_LABEL[kind]().toLowerCase()}?`}
              text={TOOLTIPS[HYGIENE_KIND_TOOLTIP[kind]]}
            />
          </span>
        ))}
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
  const visible = ranked.slice(0, 15);
  const rest = ranked.slice(15);

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
      <AnimatedList
        items={visible}
        keyFor={(f) => f.file_path}
        className="mt-3 flex flex-col divide-y divide-border"
        renderItem={(f) => <InstabilityRow file={f} highlighted={highlightPath === f.file_path} />}
      />
      {rest.length > 0 ? (
        <Expander
          className="mt-2"
          trigger={`${rest.length} more file${rest.length === 1 ? "" : "s"}`}
        >
          <ul className="flex flex-col divide-y divide-border pt-1">
            {rest.map((f) => (
              <li key={f.file_path}>
                <InstabilityRow file={f} highlighted={highlightPath === f.file_path} />
              </li>
            ))}
          </ul>
        </Expander>
      ) : null}
    </Card>
  );
}

function InstabilityRow({ file: f, highlighted }: { file: HygieneFileOut; highlighted: boolean }) {
  return (
    <div
      id={hygieneFileRowId(f.file_path)}
      className={`flex flex-wrap items-center justify-between gap-2 py-2 text-sm ${
        highlighted ? "bg-accent-bg" : ""
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
    </div>
  );
}

// =============================================================================
// Risk -- a view inside Findings now (rebuild spec section 4.4), not its own
// surface. Hotspot list ranked by hotspot_rank, plus a risk-vs-confidence
// scatter so the independence of the two axes is visually obvious before
// anyone reads a row.
// =============================================================================

function riskRowId(path: string): string {
  return `risk-row-${encodeURIComponent(path)}`;
}

function HotspotsTab() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const risk = useRisk(repo.id, share);
  const [searchParams] = useSearchParams();
  const [expandedPath, setExpandedPath] = useState<string | null>(searchParams.get("file"));

  useEffect(() => {
    const target = searchParams.get("file");
    if (!target) return;
    setExpandedPath(target);
    document
      .getElementById(riskRowId(target))
      ?.scrollIntoView({ block: "center", behavior: "smooth" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams.get("file")]);

  return (
    <StageGate
      query={risk}
      loadingLabel="Loading risk data…"
      emptyTitle="No scored files"
      emptyMessage="This repo has no analyzed files yet."
      isEmpty={(data: RiskResponse) => data.files.length === 0}
    >
      {(data) => (
        <div className="flex flex-col gap-4">
          <Reveal>
            <RiskScatter files={data.files} />
          </Reveal>

          <Reveal delay={0.05}>
            <Card
              eyebrow="Ranked by risk_score, highest first"
              title="Files by risk"
              action={
                <span className="cp-label text-text-muted">
                  {data.files.length} {data.files.length === 1 ? "file" : "files"}
                </span>
              }
            >
              <HonestyNote
                variant="confidence-caveat"
                text={HONESTY.riskConfidenceNotAFourthTerm}
              />
              <AnimatedList
                items={data.files}
                keyFor={(f) => f.file_path}
                className="mt-3 flex flex-col"
                renderItem={(file) => (
                  <RiskRow
                    file={file}
                    repoId={repo.id}
                    calibration={data.calibration}
                    expanded={expandedPath === file.file_path}
                    onToggle={(open) => setExpandedPath(open ? file.file_path : null)}
                  />
                )}
              />
            </Card>
          </Reveal>
        </div>
      )}
    </StageGate>
  );
}

/** The risk-vs-confidence scatter: plotting the two LOCKED-independent
 * axes against each other is what makes "a file can be high-risk and
 * low-confidence at once" immediately legible, rather than a claim the
 * reader has to take on faith from two separate numbers in a table row. */
function RiskScatter({ files }: { files: RiskFileOut[] }) {
  const points = files.map((f) => ({
    x: f.risk_confidence,
    y: f.risk_score,
    path: f.file_path,
    tier: confidenceLabel(f.risk_confidence),
  }));
  const byTier = {
    low: points.filter((p) => p.tier === "low"),
    medium: points.filter((p) => p.tier === "medium"),
    high: points.filter((p) => p.tier === "high"),
  };

  return (
    <Card
      title="Risk vs. confidence"
      eyebrow="Two independent axes — a point in the top-left is high-risk AND low-confidence, not a contradiction"
      action={<InfoTooltip label="What is risk confidence?" text={TOOLTIPS.riskConfidence} />}
    >
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid {...rechartsTheme.grid} />
            <XAxis
              type="number"
              dataKey="x"
              name="confidence"
              domain={[0, 1]}
              tickFormatter={(v: number) => formatPercent(v)}
              label={{
                value: "risk_confidence",
                position: "insideBottom",
                offset: -4,
                fontSize: 11,
                fill: rechartsTheme.axis.tick.fill,
              }}
              tick={rechartsTheme.axis.tick}
              stroke={rechartsTheme.axis.stroke}
            />
            <YAxis
              type="number"
              dataKey="y"
              name="risk score"
              domain={[0, 1]}
              tickFormatter={(v: number) => formatScore(v, 1)}
              label={{
                value: "risk_score",
                angle: -90,
                position: "insideLeft",
                fontSize: 11,
                fill: rechartsTheme.axis.tick.fill,
              }}
              tick={rechartsTheme.axis.tick}
              stroke={rechartsTheme.axis.stroke}
            />
            <ZAxis range={[40, 40]} />
            <Tooltip
              cursor={{ strokeDasharray: "3 3" }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0].payload as (typeof points)[number];
                return (
                  <div className="border border-border bg-bg-elevated px-2 py-1.5 text-xs">
                    <p className="max-w-[220px] truncate font-mono text-text">{p.path}</p>
                    <p className="text-text-muted">
                      risk {formatScore(p.y, 2)} · confidence {formatPercent(p.x)} ({p.tier})
                    </p>
                  </div>
                );
              }}
            />
            <Scatter data={byTier.low} fill={CONFIDENCE_COLOR.low} />
            <Scatter data={byTier.medium} fill={CONFIDENCE_COLOR.medium} />
            <Scatter data={byTier.high} fill={CONFIDENCE_COLOR.high} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function RiskRow({
  file,
  repoId,
  calibration,
  expanded,
  onToggle,
}: {
  file: RiskFileOut;
  repoId: string;
  calibration: string;
  expanded: boolean;
  onToggle: (open: boolean) => void;
}) {
  const isLowConfidence = confidenceLabel(file.risk_confidence) === "low";

  return (
    <div
      id={riskRowId(file.file_path)}
      // Low confidence gets a LEFT-BORDER treatment, not a background fill
      // -- a full-row bg-warning-bg wash falls short of body-text contrast;
      // a border keeps the row's background at the already-verified
      // bg-elevated pairing.
      className={`border-b border-border pl-2 last:border-0 ${
        isLowConfidence ? "border-l-2 border-l-warning" : ""
      }`}
    >
      <Expander
        open={expanded}
        onOpenChange={onToggle}
        trigger={
          <span className="flex w-full flex-wrap items-center gap-3">
            <span
              className="max-w-[280px] truncate font-mono text-xs text-text-muted"
              title={file.file_path}
            >
              {file.file_path}
            </span>
            <span className="ml-auto flex shrink-0 items-center gap-4">
              <span className="flex items-center gap-2">
                <span className="h-1.5 w-16 overflow-hidden rounded-full bg-bg-inset">
                  <span
                    className="block h-full rounded-full bg-accent"
                    style={{ width: `${Math.round(file.risk_score * 100)}%` }}
                  />
                </span>
                <span className="cp-stat text-xs text-text-muted">
                  {formatScore(file.risk_score)}
                </span>
              </span>
              {/* A SEPARATE visual dimension from the bar above -- never
                  opacity, never folded into the score's own color/width. */}
              <ConfidenceMeter confidence={file.risk_confidence} size="sm" />
            </span>
          </span>
        }
      >
        <div className="pb-3">
          <RiskEvidence file={file} repoId={repoId} calibration={calibration} />
        </div>
      </Expander>
    </div>
  );
}

function RiskEvidence({
  file,
  repoId,
  calibration,
}: {
  file: RiskFileOut;
  repoId: string;
  calibration: string;
}) {
  return (
    <div className="flex flex-col gap-3 border-l-2 border-border-strong bg-bg-inset p-3">
      <MetricRow
        items={[
          {
            label: "churn (recency-weighted)",
            value: formatScore(file.churn_weighted, 0),
            tooltip: "churnWeighted",
          },
          { label: "complexity", value: formatScore(file.complexity, 1), tooltip: "complexity" },
          { label: "commits", value: file.commit_count },
          {
            label: "max coupling",
            value: formatPercent(file.max_coupling_degree),
            tooltip: "couplingDegree",
          },
        ]}
      />

      {/* The formula's own real weights (from GET /meta/formulas) plus every
          signal Compass measures for this file but does NOT fold into
          risk_score -- real, per-file values, not a generic description. */}
      <ScoreExplainer
        formulaKey="risk"
        calibration={calibration}
        contributions={[]}
        alsoMeasured={[
          {
            label: "Churn (total, unweighted)",
            value: String(file.churn_total),
            tooltip: "churnTotal",
          },
          {
            label: "Instability score",
            value: file.instability_score != null ? formatScore(file.instability_score, 2) : "—",
            tooltip: "instability",
          },
          {
            label: "Revert cycle count",
            value: String(file.revert_cycle_count ?? "—"),
            tooltip: "revertCycleCount",
          },
          { label: "Expert count", value: String(file.expert_count), tooltip: "expert" },
          {
            label: "Orphaned knowledge",
            value: file.is_orphaned_knowledge ? "yes" : "no",
            tooltip: "orphanedKnowledge",
          },
        ]}
      />

      <Link
        to={`/repos/${repoId}/explore?view=impact&path=${encodeURIComponent(file.file_path)}`}
        className="w-fit text-xs font-medium text-accent hover:underline"
      >
        View blast radius →
      </Link>
    </div>
  );
}

// =============================================================================
// Benchmark -- a view inside Findings now (rebuild spec section 4.4): corpus
// percentile bars, each showing the n_repos/n_files behind it and a
// `widened` badge when the comparison broadened past the exact cell.
// =============================================================================

function MetricBar({ metric }: { metric: BenchmarkResponse["metrics"][number] }) {
  const pct = Math.round(metric.percentile * 100);
  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-2 text-xs">
        <span className="flex items-center gap-1 text-text-muted">
          {metric.metric}
          <InfoTooltip
            label="What is a benchmark percentile?"
            text={TOOLTIPS.benchmarkPercentile}
          />
        </span>
        <span className="flex items-center gap-2 tabular-nums text-text-muted">
          {formatScore(metric.value, 2)} · p{pct}
          {metric.widened ? (
            <span className="flex items-center gap-1">
              <Badge tone="med">widened</Badge>
              <InfoTooltip label="What does widened mean?" text={TOOLTIPS.widenedComparison} />
            </span>
          ) : null}
          <span>
            n={metric.n_repos} repos / {metric.n_files} files
          </span>
        </span>
      </div>
      <div className="h-2 w-full rounded-full bg-bg-inset">
        <div className="h-2 rounded-full bg-accent" style={{ width: `${Math.max(2, pct)}%` }} />
      </div>
    </div>
  );
}

function BenchmarkTab() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const benchmark = useBenchmark(repo.id, share);

  return (
    <StageGate
      query={benchmark}
      loadingLabel="Comparing against the corpus…"
      emptyTitle="No corpus data yet"
      emptyMessage="No comparable repositories exist for this language/size combination yet."
      isEmpty={(data: BenchmarkResponse) => data.metrics.every((m) => m.n_repos === 0)}
    >
      {(data) => (
        <Reveal>
          <Card
            title="Compared against the curated corpus"
            eyebrow={`${data.dominant_language} · ${data.size_bucket} repositories`}
          >
            <ScoreExplainer formulaKey="baseline" contributions={[]} />
            <HonestyNote
              variant="scope-limitation"
              text={HONESTY.benchmarkVsPortfolioDistinct}
              className="mb-3 mt-2"
            />
            <p className="mb-4 text-xs text-text-muted">{data.corpus_note}</p>
            <div className="flex flex-col gap-3">
              {data.metrics.map((m) => (
                <MetricBar key={m.metric} metric={m} />
              ))}
            </div>
            <a
              href={CORPUS_REPO_LIST_URL}
              target="_blank"
              rel="noreferrer"
              className="mt-4 inline-block text-xs text-accent hover:underline"
            >
              See the exact repository list this corpus comes from →
            </a>
            <Link
              to="/how-it-works#methods"
              className="ml-4 inline-block text-xs text-accent hover:underline"
            >
              How calibration works →
            </Link>
          </Card>
        </Reveal>
      )}
    </StageGate>
  );
}
