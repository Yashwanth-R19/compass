import { useEffect, useMemo } from "react";
import { useOutletContext, useSearchParams } from "react-router-dom";
import { useRepoStatus, useSecrets, useVulnerabilities } from "../../api/hooks";
import type { SecretHitOut, Severity, VulnerabilityOut } from "../../api/types";
import { Card } from "../../components/Card";
import { EvidenceLink } from "../../components/EvidenceLink";
import { LoadingState } from "../../components/LoadingState";
import { NarrativeBlock } from "../../components/NarrativeBlock";
import { PartialResultNotice } from "../../components/PartialResultNotice";
import { SEVERITY_LABEL } from "../../lib/format";
import type { RepoOutletContext } from "../RepoLayout";

const ROTATE_NOTE =
  "This credential should be rotated — deleting the file does not remove it from history.";

const VULN_SEVERITY_ORDER: (Severity | "unknown")[] = ["high", "med", "low", "unknown"];

function secretRowId(hit: SecretHitOut): string {
  return `secret-${hit.commit_sha}-${hit.rule_id}`;
}

function vulnRowId(v: VulnerabilityOut): string {
  return `vuln-${v.osv_id}-${v.package_name}`;
}

/** Two independent sections (Part B): secrets-in-history, then dependency
 * vulnerabilities. "security" (the INSIGHT stage vulnerabilities depend on)
 * is `optional=True` (session 10) -- an OSV.dev outage fails only that
 * stage while the run still reaches "ready", so this page must be able to
 * show a working secrets section next to an errored vulnerabilities one
 * (Known Hazard #5). That distinction isn't visible in `/vulnerabilities`'s
 * own response (a failed optional stage just returns an honestly-empty
 * 200) -- it has to come from the stage's own status on `/status`, which is
 * why this page reads `useRepoStatus` directly rather than only the two
 * result hooks. */
export function SecurityPage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const status = useRepoStatus(repo.id, share);
  const securityStage = status.data?.stages.find((s) => s.name === "security");
  const securityFailed = securityStage?.status === "failed";

  return (
    <div className="flex flex-col gap-6">
      <SecretsSection repoId={repo.id} repoUrl={repo.url} share={share} />
      <VulnerabilitiesSection
        repoId={repo.id}
        share={share}
        failed={securityFailed}
        error={securityStage?.error ?? null}
      />
      <NarrativeBlock surface="security" />
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

  if (secrets.isPending) return <LoadingState label="Scanning history for secrets…" />;
  if (secrets.isError) {
    return (
      <Card title="Secrets">
        <p className="text-sm text-red-600 dark:text-red-400">
          {secrets.error instanceof Error
            ? secrets.error.message
            : "Couldn't load secret findings."}
        </p>
      </Card>
    );
  }
  if (secrets.data.kind === "pending")
    return <LoadingState label="Scanning history for secrets…" />;

  const { hits, truncated, truncation_reason } = secrets.data.data;
  const inHistoryOnly = hits.filter((h) => !h.still_in_head);
  const stillInHead = hits.filter((h) => h.still_in_head);

  if (hits.length === 0) {
    return (
      <Card title="Secrets" subtitle="Full commit history, not just the current tree">
        <p className="py-6 text-center text-sm text-ink-faint">
          No credential-shaped secrets were found in this repository's history.
        </p>
      </Card>
    );
  }

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
        <p className="-mt-2 text-xs text-ink-faint">{truncation_reason}</p>
      ) : null}

      {/* THE product's sharpest differentiator (Part B): first, and visually
          dominant -- a naive current-tree scanner would never find these,
          because the file has already been deleted or edited. Deliberately
          styled more strongly than "still in head" below (a solid red
          border, not the amber "surprising" treatment used elsewhere) --
          this is the one section on the whole page that should catch a
          viewer's eye first. */}
      <Card
        title="Removed from code but still in git history"
        subtitle={`${inHistoryOnly.length} credential${inHistoryOnly.length === 1 ? "" : "s"} — recoverable by anyone who can clone this repository`}
        className="border-2 border-red-300 ring-2 ring-red-100 dark:border-red-500/60 dark:ring-red-500/10"
      >
        {inHistoryOnly.length === 0 ? (
          <p className="text-sm text-ink-faint">
            None — every detected secret is still present in the current tree (see below).
          </p>
        ) : (
          <ul className="flex flex-col divide-y divide-red-100 dark:divide-red-500/10">
            {inHistoryOnly.map((h) => (
              <SecretRow key={secretRowId(h)} hit={h} repoUrl={repoUrl} />
            ))}
          </ul>
        )}
      </Card>

      <Card
        title="Still present in the current codebase"
        subtitle={`${stillInHead.length} credential${stillInHead.length === 1 ? "" : "s"}`}
      >
        {stillInHead.length === 0 ? (
          <p className="text-sm text-ink-faint">None currently in the checked-out tree.</p>
        ) : (
          <ul className="flex flex-col divide-y divide-slate-100 dark:divide-slate-800">
            {stillInHead.map((h) => (
              <SecretRow key={secretRowId(h)} hit={h} repoUrl={repoUrl} />
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function SecretRow({ hit, repoUrl }: { hit: SecretHitOut; repoUrl: string }) {
  return (
    <li data-sha={hit.commit_sha} className="flex flex-col gap-1.5 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-ink">{hit.description}</span>
        {hit.redacted_preview ? (
          <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-ink-muted dark:bg-slate-800">
            {hit.redacted_preview}
          </span>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
        <EvidenceLink repoUrl={repoUrl} sha={hit.commit_sha} />
        <span>{new Date(hit.committed_at).toLocaleDateString()}</span>
        {hit.file_path ? (
          <span className="truncate font-mono" title={hit.file_path}>
            {hit.file_path}
          </span>
        ) : null}
      </div>
      <p className="text-xs text-red-600 dark:text-red-400">{ROTATE_NOTE}</p>
    </li>
  );
}

// --- 2. Vulnerabilities -------------------------------------------------------

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

  // Hooks must run unconditionally on every render (Rules of Hooks) -- this
  // has to sit above every early return below, so it's computed over
  // whatever's available yet rather than only once data has actually
  // arrived.
  const vulnerabilities = vulns.data?.kind === "data" ? vulns.data.data.vulnerabilities : [];
  const bySeverity = useMemoGroupBySeverity(vulnerabilities);

  if (failed) {
    return (
      <Card title="Dependency vulnerabilities">
        <div className="flex flex-col gap-1 rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-500/30 dark:bg-red-500/10">
          <p className="text-sm font-medium text-red-700 dark:text-red-400">
            This section couldn't be computed
          </p>
          <p className="text-xs text-red-600/80 dark:text-red-400/70">
            {error ??
              "The vulnerability lookup (OSV.dev) failed for this run. The rest of this analysis is unaffected -- secrets above were computed independently."}
          </p>
        </div>
      </Card>
    );
  }

  if (vulns.isPending) return <LoadingState label="Loading dependency vulnerabilities…" />;
  if (vulns.isError) {
    return (
      <Card title="Dependency vulnerabilities">
        <p className="text-sm text-red-600 dark:text-red-400">
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
        <div className="rounded-lg border border-dashed border-slate-300 p-4 text-sm dark:border-slate-700">
          <p className="font-medium text-ink-muted">No supported dependency manifest found</p>
          <p className="mt-1 text-ink-muted">
            This is different from "no vulnerabilities found" — Compass couldn't identify a manifest
            to check at all. Formats it parses:
          </p>
          <ul className="mt-2 list-inside list-disc text-ink-muted">
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
      <Card title="Dependency vulnerabilities" subtitle="Checked against OSV.dev">
        <p className="py-6 text-center text-sm text-ink-faint">
          No known vulnerabilities were found in this repository's declared dependencies.
        </p>
      </Card>
    );
  }

  return (
    <Card
      title="Dependency vulnerabilities"
      subtitle={`${vulnerabilities.length} match${vulnerabilities.length === 1 ? "" : "es"} against OSV.dev`}
    >
      <div className="flex flex-col gap-4">
        {VULN_SEVERITY_ORDER.filter((s) => bySeverity[s]?.length).map((sev) => (
          <div key={sev} className="flex flex-col gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-faint">
              {sev === "unknown" ? "Unknown severity" : SEVERITY_LABEL[sev]} (
              {bySeverity[sev]!.length})
            </h3>
            <ul className="flex flex-col divide-y divide-slate-100 dark:divide-slate-800">
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

function useMemoGroupBySeverity(
  vulnerabilities: VulnerabilityOut[],
): Partial<Record<Severity | "unknown", VulnerabilityOut[]>> {
  return useMemo(() => {
    const groups: Partial<Record<Severity | "unknown", VulnerabilityOut[]>> = {};
    for (const v of vulnerabilities) {
      const key = (v.severity as Severity | "unknown") ?? "unknown";
      (groups[key] ??= []).push(v);
    }
    return groups;
  }, [vulnerabilities]);
}

function VulnRow({ vuln }: { vuln: VulnerabilityOut }) {
  return (
    <li data-osv={vuln.osv_id} className="flex flex-col gap-1 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm font-medium text-ink">
          {vuln.package_name}@{vuln.version}
        </span>
        {/* Direct vs transitive is a different remediation problem (Part B):
            a direct dep can be bumped in your own manifest; a transitive
            one needs its parent updated (or an override), so this must
            read distinctly, not just as a small badge easy to miss. */}
        <span
          className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
            vuln.is_direct
              ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-400"
              : "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-ink-faint"
          }`}
        >
          {vuln.is_direct ? "direct dependency" : "transitive dependency"}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <a
          href={`https://osv.dev/vulnerability/${encodeURIComponent(vuln.osv_id)}`}
          target="_blank"
          rel="noreferrer"
          className="font-mono text-indigo-600 hover:underline dark:text-indigo-400"
        >
          {vuln.osv_id}
        </a>
        {vuln.aliases.map((a) => (
          <a
            key={a}
            href={`https://osv.dev/vulnerability/${encodeURIComponent(a)}`}
            target="_blank"
            rel="noreferrer"
            className="font-mono text-ink-faint hover:underline"
          >
            {a}
          </a>
        ))}
        {vuln.cvss_score != null ? (
          <span className="text-ink-faint">CVSS {vuln.cvss_score.toFixed(1)}</span>
        ) : null}
      </div>
      <p className="text-sm text-ink-muted">{vuln.summary}</p>
      <p className="text-xs text-ink-muted">
        {vuln.fixed_version
          ? `Fix available: upgrade to ${vuln.fixed_version}.`
          : "No fixed version has been published yet."}
      </p>
    </li>
  );
}
