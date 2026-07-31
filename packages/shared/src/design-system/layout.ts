/**
 * Viewport classes shared by HQ, Windows POS and Android POS.
 *
 * A till is not the only place this software is read. The same console is
 * opened on a counter panel, on a tablet carried to a shelf, and on a phone
 * when someone is covering a shift away from the desk. Each client therefore
 * decides its column count from the same four classes rather than from its own
 * guess, so "two columns" happens at the same width everywhere and a layout
 * tested on one client is not silently different on another.
 *
 * Boundaries follow the Material window size classes, which are drawn around
 * real device widths rather than round numbers.
 */

/** Upper bound of each class, in CSS pixels. `wide` is everything above. */
export const breakpoint = {
  /** Phones in portrait. */
  compact: 600,
  /** Phones in landscape, foldables, small tablets. */
  medium: 840,
  /** Tablets, laptops and the standard till panel. */
  expanded: 1280,
} as const;

export type ViewportClass = 'compact' | 'medium' | 'expanded' | 'wide';

const ORDER: readonly ViewportClass[] = ['compact', 'medium', 'expanded', 'wide'];

export function viewportClassFor(width: number): ViewportClass {
  if (width < breakpoint.compact) return 'compact';
  if (width < breakpoint.medium) return 'medium';
  if (width < breakpoint.expanded) return 'expanded';
  return 'wide';
}

/** True when `viewport` is `limit` or narrower. */
export function viewportAtMost(viewport: ViewportClass, limit: ViewportClass): boolean {
  return ORDER.indexOf(viewport) <= ORDER.indexOf(limit);
}

/**
 * A grid template that reflows on its own, without a media query.
 *
 * `min(100%, ...)` is what stops the track from being wider than the container:
 * a bare `minmax(220px, 1fr)` keeps its 220px floor on a 360px phone once
 * padding is subtracted, and the row overflows sideways. Clamping the floor to
 * the container width makes the last column collapse instead of spilling.
 */
export function autoColumns(minColumnWidth: number): string {
  return `repeat(auto-fit, minmax(min(100%, ${minColumnWidth}px), 1fr))`;
}
