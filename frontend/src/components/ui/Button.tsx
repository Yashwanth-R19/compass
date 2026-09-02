import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const BASE =
  "inline-flex items-center justify-center gap-1.5 border font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 whitespace-nowrap";

const SIZE: Record<Size, string> = {
  sm: "px-2.5 py-1 text-xs",
  md: "px-3 py-1.5 text-sm",
};

const VARIANT: Record<Variant, string> = {
  primary: "border-signal bg-signal text-signal-ink hover:opacity-90",
  secondary: "border-border-interactive bg-surface text-ink hover:bg-surface-2",
  ghost: "border-transparent bg-transparent text-ink-muted hover:bg-surface-2 hover:text-ink",
  danger: "border-sev-high bg-transparent text-sev-high hover:bg-sev-high/10",
};

/** The one button primitive. Sharp corners and hairline borders come from
 * the token scale (Part A), not from anything here -- this component only
 * decides variant/size colour mapping. Never a drop shadow, never a
 * gradient (DESIGN.md). `primary` is reserved for the single dominant
 * action on a page (see Part D's home page / repo submission) -- most
 * buttons in this app are `secondary` or `ghost`. */
export const Button = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: Variant;
    size?: Size;
  }
>(function Button({ variant = "secondary", size = "md", className = "", ...props }, ref) {
  return (
    <button
      ref={ref}
      className={`${BASE} ${SIZE[size]} ${VARIANT[variant]} ${className}`}
      {...props}
    />
  );
});
