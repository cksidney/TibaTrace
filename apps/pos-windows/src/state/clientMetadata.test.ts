import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';
import { installedClientMetadata } from '../../electron/clientMetadata.js';

describe('installed Windows release identity', () => {
  it('executes the CommonJS sandbox preload with no npm environment and exposes the secure bridge', () => {
    const source = readFileSync('electron/preload.cts', 'utf8');
    const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
    let exposed: Record<string, unknown> | undefined;
    runInNewContext(compiled, { exports: {}, require: (name: string) => {
      expect(name).toBe('electron');
      return { contextBridge: { exposeInMainWorld: (key: string, value: Record<string, unknown>) => { expect(key).toBe('tibatrace'); exposed = value; } },
        ipcRenderer: { sendSync: (channel: string) => { expect(channel).toBe('app:metadata'); return { version: '1.0.5', buildNumber: 5 }; }, invoke: () => Promise.resolve() } };
    } });
    expect(exposed?.version).toBe('1.0.5');
    expect(exposed?.buildNumber).toBe(5);
    expect(typeof (exposed?.auth as { login: unknown }).login).toBe('function');
    expect(typeof (exposed?.api as { request: unknown }).request).toBe('function');
  });
  it('uses the installed manifest and Electron version without npm environment variables', () => {
    expect(installedClientMetadata('1.0.5', { version: '1.0.5', tibatraceBuildNumber: 5 })).toEqual({ version: '1.0.5', buildNumber: 5 });
  });
  it.each([null, {}, { version: '1.0.4', tibatraceBuildNumber: 5 },
    { version: '1.0.5', tibatraceBuildNumber: 0 }, { version: '1.0.5', tibatraceBuildNumber: '5' },
    { version: '1.0.5', tibatraceBuildNumber: 1.5 }])('refuses inconsistent release metadata: %j', (manifest) => {
    expect(() => installedClientMetadata('1.0.5', manifest)).toThrow('release metadata');
  });
});
