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

  projects: [
    {
      name: 'console-1280',
      use: { viewport: { width: 1280, height: 900 } },
    },
    {
      // The smallest till screen the console must remain usable on. Layout
      // failures show up here first.
      name: 'console-1024',
      use: { viewport: { width: 1024, height: 768 } },
    },
  ],

  webServer: {
    command: 'npm run visual:serve',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
