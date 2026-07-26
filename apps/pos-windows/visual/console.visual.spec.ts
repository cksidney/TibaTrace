import { expect, test } from '@playwright/test';

import { SCENARIOS } from './scenarios.js';

/**
 * Visual regression for the clinical operations console.
 *
 * These assertions catch what a DOM snapshot cannot: a component rendering
 * white-on-white, a status badge losing its colour, a blocking banner
 * collapsing to zero height, text clipped out of a container. Those are the
 * failures that matter here, because each one removes a signal an operator
 * relies on to decide whether it is safe to supply a medicine.
 *
 * Alongside the image diff, each scenario is checked for two properties that
 * an image diff alone would happily accept as the new normal:
 *
 *  1. The rendered region has non-zero area. A collapsed banner produces a
 *     tiny, stable, entirely wrong screenshot that would be approved once and
 *     never questioned again.
 *  2. Nothing overflows its container horizontally. Clipped text reads as
 *     missing information, and missing information about why supply is blocked
 *     is the specific failure this console exists to prevent.
 */

async function openScenario(page: import('@playwright/test').Page, id: string) {
  await page.goto(`/?scenario=${id}`);
  // Wait on the harness's readiness attribute rather than a timeout, so the
  // capture cannot race a partially laid-out frame.
  await page.waitForSelector('html[data-visual-ready="true"]');
  const frame = page.locator(`[data-scenario="${id}"]`);
  await expect(frame).toBeVisible();
  return frame;
}

for (const scenario of SCENARIOS) {
  test.describe(scenario.title, () => {
    test(`renders as approved — ${scenario.id}`, async ({ page }) => {
      // Recorded on the test, so the rationale is in front of whoever reviews
      // a baseline change rather than buried in the catalogue.
      test.info().annotations.push({ type: 'rationale', description: scenario.rationale });

      const frame = await openScenario(page, scenario.id);
      await expect(frame).toHaveScreenshot(`${scenario.id}.png`);
    });

    test(`occupies real space — ${scenario.id}`, async ({ page }) => {
      const frame = await openScenario(page, scenario.id);
      const box = await frame.boundingBox();

      expect(box, 'the scenario rendered no box at all').not.toBeNull();
      // 8px is below any legitimate rendering of these components; anything
      // this small means the component collapsed rather than rendered.
      expect(box!.height, 'component collapsed to no usable height').toBeGreaterThan(8);
      expect(box!.width, 'component collapsed to no usable width').toBeGreaterThan(8);
    });

    test(`does not clip its content — ${scenario.id}`, async ({ page }) => {
      await openScenario(page, scenario.id);

      const overflowing = await page.evaluate(() => {
        const offenders: string[] = [];
        for (const element of Array.from(document.querySelectorAll('*'))) {
          const node = element as HTMLElement;
          const style = getComputedStyle(node);
          if (style.overflowX !== 'visible') continue;
          // A few pixels of subpixel rounding is normal; a real clip is wider.
          if (node.scrollWidth - node.clientWidth > 4) {
            offenders.push(
              `${node.tagName.toLowerCase()}: content ${node.scrollWidth}px in ${node.clientWidth}px`,
            );
          }
        }
        return offenders;
      });

      expect(overflowing, 'content is clipped, so an operator cannot read it').toEqual([]);
    });
  });
}

test('the catalogue covers every scenario it declares', async ({ page }) => {
  // Guards against a scenario being silently dropped from the index: a removed
  // scenario stops being screenshotted, and its stale baseline keeps passing.
  await page.goto('/');
  await page.waitForSelector('html[data-visual-ready="true"]');

  const links = await page.locator('a[href^="?scenario="]').count();
  expect(links).toBe(SCENARIOS.length);
});

test('an unknown scenario fails loudly rather than rendering blank', async ({ page }) => {
  // A blank frame would be captured and approved as an empty baseline.
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await page.goto('/?scenario=does-not-exist');
  await page.waitForTimeout(500);

  expect(errors.join('\n')).toContain('Unknown visual scenario');
});
