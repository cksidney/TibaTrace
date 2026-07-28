import { describe, expect, it } from 'vitest';

import { DurableActionJournal } from './durableJournal.js';
import type { OfflineAction, OfflineStore } from './offlineQueue.js';

class MemoryStore implements OfflineStore {
  actions: readonly OfflineAction[] = [];

  async read() {
    return this.actions;
  }

  async write(actions: readonly OfflineAction[]) {
    this.actions = actions;
  }

  async clear() {
    this.actions = [];
  }
}

const payment = {
  id: 'action-1',
  type: 'PAYMENT' as const,
  episodeId: 'episode-1',
  idempotencyKey: 'payment:episode-1:attempt-1',
  payload: { amount: '100.00' },
};

describe('DurableActionJournal', () => {
  it('writes in-flight before invoking a consequential action', async () => {
    const store = new MemoryStore();
    const journal = new DurableActionJournal(store);
    await journal.initialise();

    await journal.run(payment, async () => {
      expect(store.actions[0]?.state).toBe('IN_FLIGHT');
      return { kind: 'ok' as const };
    });

    expect(store.actions[0]?.state).toBe('CONFIRMED');
  });

  it('requires reconciliation after an unknown outcome', async () => {
    const store = new MemoryStore();
    const journal = new DurableActionJournal(store);
    await journal.initialise();

    await journal.run(payment, async () => ({ kind: 'unknown' as const }));

    expect(store.actions[0]?.state).toBe('NEEDS_RECONCILIATION');
    expect(journal.canProceed('episode-1')).toBe(false);
  });

  it('recovers interrupted actions during initialisation', async () => {
    const store = new MemoryStore();
    store.actions = [
      {
        ...payment,
        state: 'IN_FLIGHT',
        queuedAt: '2026-07-26T00:00:00Z',
        attempts: 1,
      },
    ];
    const journal = new DurableActionJournal(store);

    await journal.initialise();

    expect(store.actions[0]?.state).toBe('NEEDS_RECONCILIATION');
    expect(journal.summary.needsReconciliation).toBe(1);
  });

  it('resolves an unknown action only after an authoritative lookup result', async () => {
    const store = new MemoryStore();
    const journal = new DurableActionJournal(store);
    await journal.initialise();
    await journal.run(payment, async () => ({ kind: 'unknown' as const }));
    const entry = journal.entries[0];
    expect(entry?.state).toBe('NEEDS_RECONCILIATION');

    await journal.reconcile(entry!.id, true);
    expect(journal.entries[0]?.state).toBe('CONFIRMED');
  });

  it('returns an absent authoritative action to pending without resending it', async () => {
    const store = new MemoryStore();
    const journal = new DurableActionJournal(store);
    await journal.initialise();
    await journal.run(payment, async () => ({ kind: 'unknown' as const }));
    const entry = journal.entries[0];

    await journal.reconcile(entry!.id, false);
    expect(journal.entries[0]?.state).toBe('PENDING');
    expect(journal.entries[0]?.attempts).toBe(1);
    expect(journal.canProceed(payment.episodeId)).toBe(true);
  });
});
