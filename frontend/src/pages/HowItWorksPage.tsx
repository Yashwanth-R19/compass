/** Placeholder — session 2 builds the real scrollytelling pipeline
 * walkthrough here (13 stages, one worked example threaded through all of
 * them, fetched live from the showcase API). This session only needs the
 * route to exist and render something coherent, per Part J's scaffolding
 * instruction and the explicit "out of scope" note for this page's real
 * content. */
export function HowItWorksPage() {
  return (
    <div className="cp-prose mx-auto py-12">
      <p className="cp-label mb-2">Pipeline</p>
      <h1 className="font-display text-3xl text-text-heading">How Compass works</h1>
      <p className="mt-4 text-text-muted">
        This page will walk through Compass's full mining-to-insight pipeline, stage by stage, with
        one real repository's numbers threaded through every step. It's built in the next session of
        this rebuild — for now, the showcase repositories on the landing page already show real,
        complete output from that same pipeline.
      </p>
    </div>
  );
}
