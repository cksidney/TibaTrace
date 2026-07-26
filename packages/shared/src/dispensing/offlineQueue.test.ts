import { describe, expect, it } from 'vitest';

import type { OfflineAction, OfflineActionType } from './offlineQueue.js';
import {
  blockingActions,
  canProceed,
  isConsequential,
  markConfirmed,
  markRejected,
  markSent,
  nextSendable,
  prune,
  recoverAfterRestart,
  resolveReconciliation,
  summariseQueue,
} from './offlineQueue.js';

function action(overrides: Partial<OfflineAction> = {}): OfflineAction {
  return {
    id: 'a-1',
    type: 'PAYMENT',
    episodeId: 'ep-1',
    idempotencyKey: 'payment:ep-1:attempt-1',
    payload: {},
    state: 'PENDING',
    queuedAt: '2026-01-01T09:00:00Z',
    attempts: 0,
    ...overrides,
  };
}

describe('restart recovery', () => {
  it.each<OfflineActionType>(['PAYMENT', 'SUPPLY', 'COLLECTION'])(
    'flags an interrupted %s for reconciliation rather than retrying it',
    (type) => {
      // The server may have applied it. Retrying blind could double it;
      // discarding it could lose a supply that physically happened.
      const recovered = recoverAfterRestart([action({ type, state: 'IN_FLIGHT' })]);
      expect(recovered[0]?.state).toBe('NEEDS_RECONCILIATION');
      expect(recovered[0]?.failureReason).toContain('outcome is unknown');
    },
  );

  it.each<OfflineActionType>(['COUNSELLING', 'LABEL_PRINT'])(
    'simply requeues an interrupted %s',
    (type) => {
      const recovered = recoverAfterRestart([action({ type, state: 'IN_FLIGHT' })]);
      expect(recovered[0]?.state).toBe('PENDING');
    },
  );

  it('leaves already-terminal actions untouched', () => {
    const input = [
      action({ id: 'done', state: 'CONFIRMED' }),
      action({ id: 'refused', state: 'REJECTED' }),
      action({ id: 'queued', state: 'PENDING' }),
    ];
    expect(recoverAfterRestart(input).map((a) => a.state)).toEqual([
      'CONFIRMED',
      'REJECTED',
      'PENDING',
    ]);
  });

  it('never marks an interrupted action confirmed', () => {
    // Inferring success from an interrupted request is how a POS reports a
    // supply that never happened.
    const recovered = recoverAfterRestart([action({ state: 'IN_FLIGHT' })]);
    expect(recovered[0]?.state).not.toBe('CONFIRMED');
  });

  it('never marks an interrupted action rejected', () => {
    const recovered = recoverAfterRestart([action({ state: 'IN_FLIGHT' })]);
    expect(recovered[0]?.state).not.toBe('REJECTED');
  });
});

describe('the eight interruption points', () => {
  const at = (type: OfflineActionType, state: OfflineAction['state']) =>
    recoverAfterRestart([action({ type, state })])[0];

  it('restart before payment leaves it sendable', () => {
    expect(at('PAYMENT', 'PENDING')?.state).toBe('PENDING');
  });

  it('restart during payment requires reconciliation', () => {
    expect(at('PAYMENT', 'IN_FLIGHT')?.state).toBe('NEEDS_RECONCILIATION');
  });

  it('restart after payment but before supply keeps payment confirmed', () => {
    const recovered = recoverAfterRestart([
      action({ id: 'pay', type: 'PAYMENT', state: 'CONFIRMED' }),
      action({ id: 'supply', type: 'SUPPLY', state: 'PENDING' }),
    ]);
    expect(recovered.find((a) => a.id === 'pay')?.state).toBe('CONFIRMED');
    expect(recovered.find((a) => a.id === 'supply')?.state).toBe('PENDING');
  });

  it('restart during supply requires reconciliation', () => {
    expect(at('SUPPLY', 'IN_FLIGHT')?.state).toBe('NEEDS_RECONCILIATION');
  });

  it('restart after supply but before acknowledgement requires reconciliation', () => {
    // Identical from the client's side: it sent, it never heard back.
    expect(at('SUPPLY', 'IN_FLIGHT')?.state).toBe('NEEDS_RECONCILIATION');
  });

  it('restart before printing simply reprints under the same key', () => {
    expect(at('LABEL_PRINT', 'IN_FLIGHT')?.state).toBe('PENDING');
  });

  it('restart during collection requires reconciliation', () => {
    expect(at('COLLECTION', 'IN_FLIGHT')?.state).toBe('NEEDS_RECONCILIATION');
  });

  it('restart during sync preserves queue order', () => {
    const recovered = recoverAfterRestart([
      action({ id: 'second', queuedAt: '2026-01-01T09:05:00Z' }),
      action({ id: 'first', queuedAt: '2026-01-01T09:00:00Z' }),
    ]);
    expect(nextSendable(recovered)?.id).toBe('first');
  });
});

describe('progression gating', () => {
  it('bars progress while a consequential action is unresolved', () => {
    // Carrying on while the system does not know whether money moved is how a
    // patient gets charged twice.
    const actions = [action({ state: 'NEEDS_RECONCILIATION' })];
    expect(canProceed(actions, 'ep-1')).toBe(false);
    expect(blockingActions(actions, 'ep-1')).toHaveLength(1);
  });

  it('bars progress while an action is still in flight', () => {
    expect(canProceed([action({ state: 'IN_FLIGHT' })], 'ep-1')).toBe(false);
  });

  it('permits progress once everything is resolved', () => {
    expect(canProceed([action({ state: 'CONFIRMED' })], 'ep-1')).toBe(true);
  });

  it('does not let one episode block another', () => {
    const actions = [action({ episodeId: 'ep-other', state: 'NEEDS_RECONCILIATION' })];
    expect(canProceed(actions, 'ep-1')).toBe(true);
  });
});

describe('idempotency', () => {
  it('reuses the same key across retries', () => {
    let actions = [action()];
    actions = markSent(actions, 'a-1') as OfflineAction[];
    const firstKey = actions[0]?.idempotencyKey;
    actions = recoverAfterRestart(actions) as OfflineAction[];
    actions = resolveReconciliation(actions, 'a-1', false) as OfflineAction[];
    actions = markSent(actions, 'a-1') as OfflineAction[];

    expect(actions[0]?.idempotencyKey).toBe(firstKey);
    expect(actions[0]?.attempts).toBe(2);
  });

  it('confirms a reconciliation the server says was applied', () => {
    const actions = resolveReconciliation(
      [action({ state: 'NEEDS_RECONCILIATION' })],
      'a-1',
      true,
    );
    expect(actions[0]?.state).toBe('CONFIRMED');
  });

  it('requeues a reconciliation the server says was not applied', () => {
    const actions = resolveReconciliation(
      [action({ state: 'NEEDS_RECONCILIATION' })],
      'a-1',
      false,
    );
    expect(actions[0]?.state).toBe('PENDING');
  });

  it('only resolves actions actually awaiting reconciliation', () => {
    const actions = resolveReconciliation([action({ state: 'PENDING' })], 'a-1', true);
    expect(actions[0]?.state).toBe('PENDING');
  });
});

describe('retention', () => {
  it('keeps an unresolved action regardless of age', () => {
    // Discarding an unreconciled supply destroys the only local record that it
    // happened.
    const ancient = action({
      state: 'NEEDS_RECONCILIATION',
      queuedAt: '2020-01-01T00:00:00Z',
      resolvedAt: '2020-01-01T00:00:00Z',
    });
    expect(prune([ancient], 30, new Date('2026-01-01T00:00:00Z'))).toHaveLength(1);
  });

  it('prunes terminal actions past the window', () => {
    const old = action({ state: 'CONFIRMED', resolvedAt: '2020-01-01T00:00:00Z' });
    expect(prune([old], 30, new Date('2026-01-01T00:00:00Z'))).toHaveLength(0);
  });

  it('keeps recent terminal actions', () => {
    const recent = action({ state: 'CONFIRMED', resolvedAt: '2025-12-25T00:00:00Z' });
    expect(prune([recent], 30, new Date('2026-01-01T00:00:00Z'))).toHaveLength(1);
  });
});

describe('summary', () => {
  it('counts each state for the sync indicator', () => {
    const actions = [
      action({ id: '1', state: 'PENDING' }),
      action({ id: '2', state: 'IN_FLIGHT' }),
      action({ id: '3', state: 'NEEDS_RECONCILIATION' }),
      action({ id: '4', state: 'REJECTED' }),
      action({ id: '5', state: 'CONFIRMED' }),
    ];
    expect(summariseQueue(actions)).toEqual({
      pending: 1,
      inFlight: 1,
      needsReconciliation: 1,
      rejected: 1,
    });
  });
});

describe('classification', () => {
  it('treats money and stock movements as consequential', () => {
    expect(isConsequential('PAYMENT')).toBe(true);
    expect(isConsequential('SUPPLY')).toBe(true);
    expect(isConsequential('COLLECTION')).toBe(true);
  });

  it('does not treat printing or counselling as consequential', () => {
    expect(isConsequential('LABEL_PRINT')).toBe(false);
    expect(isConsequential('COUNSELLING')).toBe(false);
  });
});

describe('state transitions', () => {
  it('records rejection with its reason', () => {
    const actions = markRejected([action({ state: 'IN_FLIGHT' })], 'a-1', 'Stale clinical context');
    expect(actions[0]?.state).toBe('REJECTED');
    expect(actions[0]?.failureReason).toBe('Stale clinical context');
  });

  it('marks confirmation terminal', () => {
    const actions = markConfirmed([action({ state: 'IN_FLIGHT' })], 'a-1');
    expect(actions[0]?.state).toBe('CONFIRMED');
    expect(actions[0]?.resolvedAt).toBeTruthy();
  });
});
