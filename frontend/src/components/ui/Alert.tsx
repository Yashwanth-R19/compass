import { CircleAlert, CircleCheck, Info, OctagonAlert, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

type Variant = "info" | "success" | "warning" | "danger" | "neutral";

const ICON: Record<Variant, typeof Info> = {
  info: Info,
  success: CircleCheck,
  warning: TriangleAlert,
  danger: OctagonAlert,
  neutral: CircleAlert,
};

const TONE: Record<Variant, string> = {
  info: "border-info text-info",
  success: "border-success text-success",
  warning: "border-warning text-warning",
  danger: "border-danger text-danger",
  neutral: "border-border-strong text-text-muted",
};

/** The one banner primitive (Part F) -- a bordered block with a single
 * lucide icon and a body slot. Used for every banner in the app: the
 * free-tier constraint note on the landing submit form, a repo's archived-
 * Facts notice, an errored-optional-stage card, a compare
 * engine-version-mismatch flag, and so on. Colour is the icon/border only —
 * the surface stays neutral (`bg-bg-elevated`), matching rule V4 ("colour
 * encodes data, chrome stays neutral"): a banner is chrome describing a
 * state, not a data value itself. */
export function Alert({
  variant = "neutral",
  children,
  className = "",
}: {
  variant?: Variant;
  children: ReactNode;
  className?: string;
}) {
  const Icon = ICON[variant];
  return (
    <div
      role={variant === "danger" || variant === "warning" ? "alert" : undefined}
      className={`flex items-start gap-2.5 rounded-md border bg-bg-elevated px-3.5 py-3 text-sm ${TONE[variant]} ${className}`}
    >
      <Icon size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
      <div className="text-text">{children}</div>
    </div>
  );
}
