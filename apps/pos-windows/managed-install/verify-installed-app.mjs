import assert from 'node:assert/strict';
import { _electron as electron } from '@playwright/test';

const executablePath = process.env.TIBATRACE_INSTALLED_EXE;
const version = process.env.TIBATRACE_EXPECTED_VERSION;
const buildNumber = Number(process.env.TIBATRACE_EXPECTED_BUILD);
assert(executablePath && version && Number.isSafeInteger(buildNumber) && buildNumber > 0);
const application = await electron.launch({ executablePath, timeout: 30000 });
try {
  const page = await application.firstWindow({ timeout: 30000 });
  await page.waitForFunction(() => Boolean(window.tibatrace?.auth && window.tibatrace?.api), undefined, { timeout: 15000 });
  const identity = await page.evaluate(() => ({ version: window.tibatrace.version, buildNumber: window.tibatrace.buildNumber,
    login: typeof window.tibatrace.auth.login, api: typeof window.tibatrace.api.request,
    printing: typeof window.tibatrace.print.document }));
  assert.equal(identity.version, version);
  assert.equal(identity.buildNumber, buildNumber);
  assert.equal(identity.login, 'function');
  assert.equal(identity.api, 'function');
  assert.equal(identity.printing, 'function');
  const session = await page.evaluate(() => window.tibatrace.auth.restore());
  assert.equal(session.authenticated, false);
  console.log('Installed application launch and sandboxed bridge passed:', JSON.stringify(identity));
} finally {
  await application.close();
}
