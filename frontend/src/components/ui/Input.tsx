import { forwardRef } from "react";
import type { InputHTMLAttributes } from "react";

/** The one text-input primitive -- hairline border, the new softened
 * radius scale, no coloured focus glow beyond the global `:focus-visible`
 * ring (index.css). */
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className = "", ...props }, ref) {
    return (
      <input
        ref={ref}
        className={`w-full rounded-sm border border-border-interactive bg-bg-elevated px-3 py-2 text-sm text-text placeholder:text-text-muted disabled:cursor-not-allowed disabled:opacity-50 ${className}`}
        {...props}
      />
    );
  },
);
