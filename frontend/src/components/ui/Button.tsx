import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const BASE =
  "inline-flex items-center justify-center gap-1.5 border font-sans font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 whitespace-nowrap rounded-sm";

const SIZE: Record<Size, string> = {
  sm: "px-2.5 py-1 text-xs",
  md: "px-3.5 py-1.5 text-sm",
};

const VARIANT: Record<Variant, string> = {
  primary:
    "border-accent bg-accent text-accent-contrast hover:bg-accent-strong hover:border-accent-strong",
  secondary: "border-border-interactive bg-bg-elevated text-text hover:bg-bg-inset",
  ghost: "border-transparent bg-transparent text-text-muted hover:bg-bg-inset hover:text-text",
  danger: "border-danger bg-transparent text-danger hover:bg-danger-bg",
};

/** The one button primitive (Part F). `primary` is reserved for the single
 * dominant action on a page (rule V4) -- most buttons in this app are
 * `secondary` or `ghost`. Radius/border come from the token scale, never a
 * hardcoded value here. */
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
