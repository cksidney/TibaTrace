/**
 * A `fetch` that is safe to hold onto.
 *
 * `fetch` is a method of the global object and needs its receiver. Storing a
 * bare reference and calling it later invokes it with the wrong `this`:
 *
 *     this.fetcher = options.fetcher ?? fetch;   // detached
 *     await this.fetcher(url);                   // `this` is the class instance
 *
 * A browser answers that with `TypeError: Failed to execute 'fetch' on
 * 'Window': Illegal invocation`, which is what the Windows POS renderer threw
 * on its sign-in button. The same shape appears when the expression is called
 * immediately, `(config.fetcher ?? fetch)(url)`, where `this` is undefined.
 *
 * It went unnoticed because both packaged apps inject their own fetcher --
 * Electron routes through its main process, so the default branch never ran
 * there. Only the browser fallback and any caller that omits `fetcher` reached
 * it.
 */

export type Fetcher = typeof fetch;

/**
 * Returns the caller's fetcher, or a correctly bound global one.
 *
 * Binding rather than wrapping keeps the identity stable, so tests that assert
 * on a passed-in fetcher still see exactly the function they supplied.
 */
export function resolveFetcher(fetcher?: Fetcher): Fetcher {
  if (fetcher) return fetcher;
  if (typeof globalThis.fetch !== 'function') {
    throw new Error(
      'No fetch implementation is available. Pass `fetcher` explicitly on this runtime.',
    );
  }
  return globalThis.fetch.bind(globalThis);
}
