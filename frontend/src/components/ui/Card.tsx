import type { ReactNode } from "react";

/**
 * The primary layout unit of the whole app (Part F) — replaces the old
 * top-level `components/Card.tsx` for all NEW code from this session
 * onward. Supports the eyebrow + serif heading convention (section 3.2):
 * a small uppercase tracked-out `eyebrow` sits above the `title`, which
 * renders in the display serif, not a generic bold sans label.
 *
 * TRANSITIONAL NOTE: the old top-level `components/Card.tsx`
 * (`title`/`subtitle`/`action`/`children`, sans-serif heading) is
 * deliberately left in place, unmodified, for the ~18 not-yet-rebuilt
 * repo-surface pages that still import it (sessions 3/4's job to migrate
 * off it as each page is rebuilt) — this session must not touch any repo
 * surface's internals. Once every page has moved to this component, the
 * old one should be deleted. See DESIGN_NOTES.md.
 */
export function Card({
  eyebrow,
  title,
  action,
  children,
  className = "",
}: {
  eyebrow?: string;
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`rounded-lg border border-border bg-bg-elevated p-5 ${className}`}>
      {eyebrow || title || action ? (
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            {eyebrow ? <p className="cp-label mb-1 text-text-muted">{eyebrow}</p> : null}
            {title ? (
              <h2 className="font-display text-xl leading-snug text-text-heading">{title}</h2>
            ) : null}
          </div>
          {action}
        </div>
      ) : null}
      {children}
    </div>
  );
}
