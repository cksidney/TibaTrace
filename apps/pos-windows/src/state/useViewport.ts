/**
 * Current viewport class for the renderer.
 *
 * The console is inline-styled throughout, so a media query cannot reach the
 * layouts that matter -- the shell grid, the clinical rail and the retail
 * three-pane. Those read this hook instead and pick a column count directly.
 * Grids whose only problem is track width should use `autoColumns` and stay
 * out of JavaScript entirely.
 */
import { breakpoint, viewportClassFor, type ViewportClass } from '@dawatrace/shared/design-system/index.js';
import { useEffect, useState } from 'react';

function measure(): ViewportClass {
  // Electron always has a window; the guard is for the unit runner, which
  // imports components without a DOM. Assume the till panel there.
  if (typeof window === 'undefined') return viewportClassFor(breakpoint.expanded);
  return viewportClassFor(window.innerWidth);
}

export function useViewport(): ViewportClass {
  const [viewport, setViewport] = useState(measure);

  useEffect(() => {
    const onResize = () => setViewport(measure());
    // Re-measure on mount: an Electron window restored to its last size fires
    // no resize event, so the first render's value can already be stale.
    onResize();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  return viewport;
}
