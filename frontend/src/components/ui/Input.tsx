import { forwardRef } from "react";
import type { InputHTMLAttributes } from "react";

/** The one text-input primitive -- hairline border, sharp corners, no
 * coloured focus glow beyond the global `:focus-visible` ring (index.css).
 * Every existing ad-hoc `<input>` (FilePicker, HomePage's URL field,
 * PortfolioPage's textarea-adjacent controls) refits onto this. */
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className = "", ...props }, ref) {
    return (
      <input
        ref={ref}
        className={`w-full border border-border-interactive bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint disabled:cursor-not-allowed disabled:opacity-50 ${className}`}
        {...props}
      />
    );
  },
);
