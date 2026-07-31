import { defineConfig, devices } from '@playwright/test';

/**
 * Visual-regression configuration for the TibaTrace Windows console.
 *
 * Baselines are platform-specific. Font rasterisation and subpixel rendering
 * differ enough between macOS, Windows and Linux that a baseline captured on
 * one will fail on another for reasons that have nothing to do with the code.
 * CI (ubuntu-latest) is therefore the only authority for baselines, and the
 * snapshot path template includes the platform so a locally captured file can
 * never be mistaken for the CI one.
 *
 * To update baselines, run the CI workflow's `visual` job with
 * `update_baselines: true` and review every changed image before merging.
 * A baseline approved without being looked at is worse than no baseline: it
 * converts an unnoticed regression into a permanently recorded expectation.
 */
export default defineConfig({
  testDir: './visual',
  testMatch: /.*\.visual\.spec\.ts/,
  // A visual diff is never flaky in a useful way -- a retry that passes is
  // hiding a real nondeterminism.
  retries: 0,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : [['list']],

  snapshotPathTemplate:
    '{testDir}/__screenshots__/{platform}/{projectName}/{arg}{ext}',

  expect: {
    toHaveScreenshot: {
      // Zero tolerance on the ratio, with a small absolute allowance for
      // antialiasing on glyph edges. A threshold large enough to absorb a
      // colour change is a threshold that hides one.
      maxDiffPixelRatio: 0,
      maxDiffPixels: 24,
      threshold: 0.1,
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
    },
  },

  use: {
    baseURL: 'http://127.0.0.1:4173',
    // A fixed device pixel ratio, colour scheme, locale and timezone. Any of
    // these drifting would produce diffs unrelated to the change under review.
    ...devices['Desktop Chrome'],
    deviceScaleFactor: 1,
    colorScheme: 'light',
    locale: 'en-GB',
    timezoneId: 'UTC',
    trace: 'retain-on-failure',
  },

  /**
   * Two kinds of project.
   *
   * The first two hold approved pixel baselines. The last two do not: they
   * exist so the layout assertions -- occupies real space, does not clip --
   * run at tablet and phone widths, which is where a fixed column count or an
   * unclamped `minmax` floor shows up first. Adding baselines for them would
   * quadruple the images to review for no extra signal, since the same
   * components are already pixel-checked at two widths.
   */
  projects: [
    {
      name: 'console-1280',
      use: { viewport: { width: 1280, height: 900 } },
      metadata: { baselines: true },
    },
    {
      // The smallest till screen the console must remain usable on. Layout
      // failures show up here first.
      name: 'console-1024',
      use: { viewport: { width: 1024, height: 768 } },
      metadata: { baselines: true },
    },
    {
      // Tablet portrait, carried to the shelf.
      name: 'console-768',
      use: { viewport: { width: 768, height: 1024 } },
      metadata: { baselines: false },
    },
    {
      // A phone. Narrower than anything the console was designed for, which is
      // the point: nothing here may scroll sideways or clip.
      name: 'console-390',
      use: { viewport: { width: 390, height: 844 } },
      metadata: { baselines: false },
    },
  ],

  webServer: {
    command: 'npm run visual:serve',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
