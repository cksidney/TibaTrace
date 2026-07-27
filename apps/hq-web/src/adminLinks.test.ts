/**
 * No workspace control may point at Django admin.
 *
 * The HQ app is meant to be the operator's whole surface. For a long time the
 * source carried `/admin/...` URLs in every `href`, translated at render time by
 * a `hqDestinationFor` mapper into in-app hashes. That worked -- no anchor ever
 * reached Django -- but it read as though the app were full of admin links, and
 * the mapper's `?? 'access'` fallback sent an unrecognised prefix to the wrong
 * view rather than failing.
 *
 * The hrefs are now the in-app destinations themselves. This test keeps them
 * that way, and checks the source rather than a render because the failure it
 * guards against is somebody pasting an admin URL into a new component -- which
 * a render test only catches if that component happens to be on screen.
 */
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const SRC = new URL('.', import.meta.url).pathname;

function sourceFiles(): readonly string[] {
  return readdirSync(SRC)
    .filter((name) => /\.tsx?$/.test(name) && !name.endsWith('.test.ts') && !name.endsWith('.test.tsx'))
    .map((name) => join(SRC, name));
}

/** Every `href="..."` / `actionHref="..."` literal in a source file. */
function hrefLiterals(file: string): readonly string[] {
  const source = readFileSync(file, 'utf8');
  return [...source.matchAll(/(?:href|actionHref)="([^"]*)"/g)].map((m) => m[1] ?? '');
}

describe('workspace navigation', () => {
  it('scans a non-empty set of source files', () => {
    // A guard that reads nothing passes exactly as loudly as one that works.
    const files = sourceFiles();
    expect(files.length).toBeGreaterThan(2);
    expect(files.some((f) => f.endsWith('App.tsx'))).toBe(true);
  });

  it('finds the hrefs it is meant to be checking', () => {
    const all = sourceFiles().flatMap(hrefLiterals);
    expect(all.length).toBeGreaterThan(10);
  });

  it('has no href pointing at Django admin', () => {
    const offenders = sourceFiles().flatMap((file) =>
      hrefLiterals(file)
        .filter((href) => href.startsWith('/admin') || href.includes('/admin/'))
        .map((href) => `${file.split('/').pop()}: ${href}`),
    );
    expect(offenders, 'Link to the in-app view instead, e.g. href="#catalogue".').toEqual([]);
  });

  it('points every internal href at a real workspace view', () => {
    const views = [
      'overview', 'network', 'people', 'catalogue', 'operations', 'commerce',
      'pricing', 'cash', 'insurance', 'clinical', 'governance', 'access',
    ];
    // #main-content is the skip link's target, not a view.
    const allowed = new Set([...views.map((v) => `#${v}`), '#main-content']);
    const unknown = sourceFiles()
      .flatMap(hrefLiterals)
      .filter((href) => href.startsWith('#'))
      .filter((href) => !allowed.has(href));
    expect([...new Set(unknown)]).toEqual([]);
  });
});
