/** The one Compass mark, used everywhere a logo appears -- the app shell's
 * header (every screen, since AppShell wraps every route) and
 * `public/favicon.svg` render the SAME geometry, not two different
 * interpretations of "compass": a four-point rose needle inside a thin
 * ring. Colour comes from `currentColor` (wrap in a `text-*` class, same
 * convention the lucide icon this replaced used), so it inherits the
 * accent everywhere it's placed instead of carrying its own hardcoded
 * fill. The favicon keeps its own self-contained dark badge circle behind
 * the same needle -- a favicon floats on arbitrary browser-chrome
 * backgrounds and needs that; inline in the app it already sits on a
 * matching surface, so no backing circle here. */
export function Logo({ size = 20, className = "" }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      <circle cx="16" cy="16" r="14.25" stroke="currentColor" strokeWidth="1.3" opacity="0.9" />
      <path d="M16 4.5 19.4 16 16 27.5 12.6 16Z" fill="currentColor" />
      <path d="M4.5 16 16 12.6 27.5 16 16 19.4Z" fill="currentColor" opacity="0.55" />
    </svg>
  );
}
