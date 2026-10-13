import { describe, expect, it } from 'vitest';
import { installedClientMetadata } from '../../electron/clientMetadata.js';

describe('installed Windows release identity', () => {
  it('uses the installed manifest and Electron version without npm environment variables', () => {
    expect(installedClientMetadata('1.0.5', { version: '1.0.5', tibatraceBuildNumber: 5 })).toEqual({ version: '1.0.5', buildNumber: 5 });
  });
  it.each([null, {}, { version: '1.0.4', tibatraceBuildNumber: 5 },
    { version: '1.0.5', tibatraceBuildNumber: 0 }, { version: '1.0.5', tibatraceBuildNumber: '5' },
    { version: '1.0.5', tibatraceBuildNumber: 1.5 }])('refuses inconsistent release metadata: %j', (manifest) => {
    expect(() => installedClientMetadata('1.0.5', manifest)).toThrow('release metadata');
  });
});
