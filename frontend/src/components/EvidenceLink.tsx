/** Builds the GitHub commit URL for a repo URL + sha -- handles a trailing
 * slash and a `.git` suffix on the stored repo URL, neither of which GitHub
 * accepts in a `/commit/<sha>` path. Exported standalone so it's testable
 * without rendering. */
export function buildCommitUrl(repoUrl: string, sha: string): string {
  const trimmed = repoUrl
    .trim()
    .replace(/\/+$/, "")
    .replace(/\.git$/i, "");
  return `${trimmed}/commit/${sha}`;
}

/** Renders a commit sha as a link to that commit on GitHub. The one place
 * this URL is built -- FindingItem and every onboard/audit page that shows
 * evidence commits should use this instead of hand-rolling the same
 * `.replace(/\/$/, "")` trick per call site. */
export function EvidenceLink({ repoUrl, sha }: { repoUrl: string; sha: string }) {
  return (
    <a
      href={buildCommitUrl(repoUrl, sha)}
      target="_blank"
      rel="noreferrer"
      className="w-fit rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-indigo-600 hover:underline dark:bg-slate-800 dark:text-indigo-400"
    >
      {sha.slice(0, 7)}
    </a>
  );
}
