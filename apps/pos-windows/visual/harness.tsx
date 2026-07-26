/**
 * Visual-regression harness entry point.
 *
 * Renders exactly one scenario, chosen by `?scenario=<id>`, on a fixed
 * background at a fixed width. Nothing else is on the page, so a diff is
 * attributable to the component under test.
 *
 * Determinism rules enforced here rather than left to each scenario:
 *  - animations and transitions are disabled, so a screenshot cannot catch a
 *    component mid-transition;
 *  - the caret is hidden, so focus does not blink into the diff;
 *  - a `data-visual-ready` attribute is set after paint, which is what the
 *    Playwright spec waits on instead of a sleep.
 *
 * This harness is for screenshots only. It is never bundled into the shipped
 * application: it lives outside `src/` and has its own Vite config.
 */
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { SCENARIOS, SCENARIOS_BY_ID } from './scenarios.js';

const params = new URLSearchParams(window.location.search);
const requested = params.get('scenario');

const container = document.getElementById('root');
if (!container) throw new Error('Harness root element is missing.');

function Index() {
  return (
    <div style={{ padding: 24, fontFamily: 'system-ui, sans-serif' }}>
      <h1 style={{ fontSize: 18 }}>Visual scenarios ({SCENARIOS.length})</h1>
      <ul>
        {SCENARIOS.map((scenario) => (
          <li key={scenario.id}>
            <a href={`?scenario=${scenario.id}`}>{scenario.id}</a> — {scenario.title}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Frame({ id }: { id: string }) {
  const scenario = SCENARIOS_BY_ID.get(id);
  if (!scenario) {
    // Fail loudly. A silently blank frame would be screenshotted and approved
    // as an empty baseline, and the scenario would stop being covered.
    throw new Error(`Unknown visual scenario: ${id}`);
  }
  return (
    <div
      data-scenario={scenario.id}
      style={{ width: scenario.width, padding: 16, boxSizing: 'border-box' }}
    >
      {scenario.render()}
    </div>
  );
}

createRoot(container).render(
  <StrictMode>{requested ? <Frame id={requested} /> : <Index />}</StrictMode>,
);

// Signal readiness only after the browser has actually painted, so the spec
// never captures a partially laid-out frame.
requestAnimationFrame(() => {
  requestAnimationFrame(() => {
    document.documentElement.setAttribute('data-visual-ready', 'true');
  });
});
