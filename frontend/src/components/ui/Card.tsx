import type { ReactNode } from "react";

/**
 * The one card primitive in the app. Supports the eyebrow + display-serif
 * heading convention: a small uppercase tracked-out `eyebrow` sits above
 * the `title`, which renders in the display serif, not a generic bold sans
 * label.
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
