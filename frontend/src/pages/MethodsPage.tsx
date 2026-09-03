/** Placeholder — session 2 builds the real Methods page here (locked
 * formulas, calibration provenance, corpus limitations, explicit excluded
 * cases). This session only needs the route to exist and render something
 * coherent. */
export function MethodsPage() {
  return (
    <div className="cp-prose mx-auto py-12">
      <p className="cp-label mb-2">Reference</p>
      <h1 className="font-display text-3xl text-text-heading">Methods</h1>
      <p className="mt-4 text-text-muted">
        This page will document every formula Compass computes — which are locked, which are
        literature-cited, which are openly heuristic — plus how the corpus baseline was built and
        what it deliberately does not cover. It's built in the next session of this rebuild.
      </p>
    </div>
  );
}
