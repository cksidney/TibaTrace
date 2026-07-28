import { afterEach, describe, expect, it, vi } from 'vitest';

import { resolveFetcher } from './fetcher.js';
import { PosApiSession } from './session.js';

/**
 * The bug this guards against.
 *
 * `fetch` is a method of the global object and needs its receiver. Every client
 * in this package stored a bare reference -- `options.fetcher ?? fetch` -- and
 * called it later as a property of the instance, which invokes it with the
 * wrong `this`. A browser answers `TypeError: Failed to execute 'fetch' on
 * 'Window': Illegal invocation`, which is what the Windows POS renderer threw
 * when its sign-in button was pressed.
 *
 * It survived because both packaged apps inject their own fetcher, so the
 * default branch never ran in Electron or React Native. Only the browser
 * fallback reached it.
 */
describe('resolveFetcher', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns the caller’s fetcher unchanged', () => {
    // Identity has to survive, or tests asserting on an injected fetcher stop
    // seeing the function they passed.
    const injected = vi.fn();
    expect(resolveFetcher(injected as unknown as typeof fetch)).toBe(injected);
  });

  it('binds the global fetch to the global object', async () => {
    // The reproduction: a realistic global fetch that refuses a wrong receiver,
    // exactly as a browser does.
    const calls: string[] = [];
    const globalFetch = function (this: unknown, url: string) {
      if (this !== globalThis) {
        throw new TypeError(
          "Failed to execute 'fetch' on 'Window': Illegal invocation",
        );
      }
      calls.push(url);
      return Promise.resolve(new Response('{}'));
    };
    vi.stubGlobal('fetch', globalFetch);

    const holder = { fetcher: resolveFetcher() };
    await expect(holder.fetcher('/api/thing' as never)).resolves.toBeDefined();
    expect(calls).toEqual(['/api/thing']);
  });

  it('says so when no fetch exists rather than failing later', () => {
    vi.stubGlobal('fetch', undefined);
    expect(() => resolveFetcher()).toThrow(/No fetch implementation/);
  });
});

describe('PosApiSession without an injected fetcher', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('signs in through the global fetch instead of throwing Illegal invocation', async () => {
    const globalFetch = function (this: unknown) {
      if (this !== globalThis) {
        throw new TypeError(
          "Failed to execute 'fetch' on 'Window': Illegal invocation",
        );
      }
      return Promise.resolve(
        new Response(
          JSON.stringify({ access: 'a', refresh: 'r', tenant_id: 't', user_id: 'u' }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      );
    };
    vi.stubGlobal('fetch', globalFetch);

    let saved: unknown = null;
    const session = new PosApiSession({
      baseUrl: '',
      storage: {
        load: async () => null,
        save: async (tokens) => void (saved = tokens),
        clear: async () => void (saved = null),
      },
    });

    // Before the fix this rejected with Illegal invocation, which the POS
    // rendered as a bare error under the sign-in button.
    await expect(session.login('operator', 'password')).resolves.not.toThrow();
    expect(saved).not.toBeNull();
  });
});
