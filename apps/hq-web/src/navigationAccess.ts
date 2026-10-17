import type { HQOverview } from './api.js';

const ownerOnlyViews = new Set(['executive', 'network', 'integration', 'platform_owner', 'activations']);

/** The server supplies current grants; scope labels and tenant roles never imply ownership. */
export function accessibleHqViews(overview: HQOverview): ReadonlySet<string> {
  const owner = overview.is_platform_owner === true;
  return new Set(['overview', ...(overview.allowed_views ?? []).filter(
    view => owner || !ownerOnlyViews.has(view),
  )]);
}

export function canOpenHqDestination(overview: HQOverview, href: string): boolean {
  if (href.startsWith('#')) return accessibleHqViews(overview).has(href.slice(1).split('/')[0] ?? '');
  if (href === '/pos/') return overview.show_pos_handoff === true;
  if (href.startsWith('/api/')) return overview.is_platform_owner === true;
  return false;
}
