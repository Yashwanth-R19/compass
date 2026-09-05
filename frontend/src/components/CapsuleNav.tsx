import { motion } from "motion/react";
import { NavLink } from "react-router-dom";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";

/** A pill-style nav: a shared `layoutId="nav-pill"` background animates
 * between links as the active route changes (the classic "magic mover" tab
 * indicator), rather than each link owning its own static highlight. Falls
 * back to a plain, unanimated active class under reduced motion -- a
 * sliding background is exactly the kind of non-essential motion rule M5
 * exists to gate.
 *
 * Two shapes, one component: `bordered` (default) draws the whole row as
 * one hairline-bordered island, for a short, never-overflowing list (the
 * app shell's own two-item nav). `bordered={false}` renders bare,
 * individually-pilled links with no outer boundary -- for a row that must
 * support `overflow-x-auto` scrolling (the repo tab bar can hold five tabs
 * on a 360px viewport), since a rounded OUTER container fighting with an
 * inner horizontal scroll would clip its own corners mid-scroll. Every
 * instance still needs its OWN `layoutId` (via the `groupId` prop) so two
 * concurrently-mounted CapsuleNavs (the app shell's + a repo's tab bar)
 * never animate their pills into each other. */
export function CapsuleNav({
  items,
  groupId,
  bordered = true,
  className = "",
  itemClassName = "",
}: {
  items: { to: string; label: string }[];
  groupId: string;
  bordered?: boolean;
  className?: string;
  itemClassName?: string;
}) {
  const reducedMotion = usePrefersReducedMotion();
  const containerBase = bordered
    ? "gap-0.5 rounded-full border border-border bg-bg-elevated p-1"
    : "gap-1";

  return (
    <nav aria-label="Sections" className={`${containerBase} ${className}`}>
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) =>
            `relative rounded-full px-3.5 py-1.5 text-xs font-medium tracking-tight whitespace-nowrap transition-colors ${
              isActive ? "text-accent" : "text-text-muted hover:text-text"
            } ${itemClassName}`
          }
        >
          {({ isActive }) => (
            <>
              {isActive ? (
                reducedMotion ? (
                  <span className="absolute inset-0 -z-10 rounded-full bg-accent-bg" />
                ) : (
                  <motion.span
                    layoutId={`nav-pill-${groupId}`}
                    className="absolute inset-0 -z-10 rounded-full bg-accent-bg"
                    transition={{ type: "spring", stiffness: 420, damping: 34 }}
                  />
                )
              ) : null}
              <span className="relative">{item.label}</span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}
