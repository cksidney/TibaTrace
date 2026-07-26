/**
 * Durable offline action queue and restart recovery.
 *
 * A till that loses power mid-sale must not, on restart, either repeat what it
 * already did or silently forget it. Both failures are worse than an error
 * message: one takes money twice, the other loses a supply that physically
 * happened.
 *
 * The design rests on two things. Every action carries a client-generated
 * idempotency key created *before* the request leaves, so a replay after
 * restart collapses onto the original server-side. And an action whose outcome
 * is unknown is recorded as unknown -- never as failed, and never as done --
 * because a request that timed out may well have been applied.
 */

export type OfflineActionType =
  | 'PAYMENT'
  | 'SUPPLY'
  | 'COLLECTION'
  | 'COUNSELLING'
  | 'LABEL_PRINT';

export type OfflineActionState =
  /** Queued locally, never sent. Safe to send or discard. */
  | 'PENDING'
  /** Sent; no response seen. Outcome genuinely unknown. */
  | 'IN_FLIGHT'
  /** Server confirmed. Terminal. */
  | 'CONFIRMED'
  /** Server refused for a stated reason. Terminal until a human intervenes. */
  | 'REJECTED'
  /** Sent, outcome unknown after restart. Must be reconciled, not retried blind. */
  | 'NEEDS_RECONCILIATION';

export interface OfflineAction {
  readonly id: string;
  readonly type: OfflineActionType;
  readonly episodeId: string;
  /** Generated before the first send, reused on every retry. */
  readonly idempotencyKey: string;
  readonly payload: Record<string, unknown>;
  readonly state: OfflineActionState;
  readonly queuedAt: string;
  readonly sentAt?: string;
  readonly resolvedAt?: string;
  readonly failureReason?: string;
  readonly attempts: number;
}

/** Storage a platform must provide. Deliberately tiny. */
export interface OfflineStore {
  read(): Promise<readonly OfflineAction[]>;
  write(actions: readonly OfflineAction[]): Promise<void>;
  clear(): Promise<void>;
}

/**
 * Actions whose outcome cannot be assumed after an unexpected restart.
 *
 * A payment, supply or collection that was in flight may have been applied by
 * the server. Retrying blind could double it; discarding it could lose it.
 */
const CONSEQUENTIAL: readonly OfflineActionType[] = ['PAYMENT', 'SUPPLY', 'COLLECTION'];

export function isConsequential(type: OfflineActionType): boolean {
  return CONSEQUENTIAL.includes(type);
}

/**
 * Reconcile the queue after a restart.
 *
 * Anything left IN_FLIGHT was interrupted mid-request. For a consequential
 * action that becomes NEEDS_RECONCILIATION: the client must ask the server what
 * actually happened before doing anything else. For a harmless one -- printing
 * a label, recording counselling -- it returns to PENDING and is simply retried
 * under the same key.
 */
export function recoverAfterRestart(
  actions: readonly OfflineAction[],
  now: string = new Date().toISOString(),
): readonly OfflineAction[] {
  return actions.map((action) => {
    if (action.state !== 'IN_FLIGHT') return action;
    if (isConsequential(action.type)) {
      return {
        ...action,
        state: 'NEEDS_RECONCILIATION' as const,
        failureReason:
          'The application restarted while this was in flight. Its outcome is unknown until the server is queried.',
        resolvedAt: now,
      };
    }
    return { ...action, state: 'PENDING' as const };
  });
}

/** Actions that must be resolved before the till may continue with this episode. */
export function blockingActions(
  actions: readonly OfflineAction[],
  episodeId: string,
): readonly OfflineAction[] {
  return actions.filter(
    (action) =>
      action.episodeId === episodeId &&
      (action.state === 'NEEDS_RECONCILIATION' || action.state === 'IN_FLIGHT'),
  );
}

/**
 * Whether the episode may progress locally.
 *
 * An unresolved consequential action bars progress. Letting an operator carry
 * on while the system does not know whether money moved is how a patient gets
 * charged twice.
 */
export function canProceed(actions: readonly OfflineAction[], episodeId: string): boolean {
  return blockingActions(actions, episodeId).length === 0;
}

/** The next action to send. Oldest first, so ordering survives a restart. */
export function nextSendable(actions: readonly OfflineAction[]): OfflineAction | null {
  const pending = actions
    .filter((action) => action.state === 'PENDING')
    .sort((a, b) => Date.parse(a.queuedAt) - Date.parse(b.queuedAt));
  return pending[0] ?? null;
}

export function markSent(
  actions: readonly OfflineAction[],
  id: string,
  now: string = new Date().toISOString(),
): readonly OfflineAction[] {
  return actions.map((action) =>
    action.id === id
      ? { ...action, state: 'IN_FLIGHT' as const, sentAt: now, attempts: action.attempts + 1 }
      : action,
  );
}

export function markConfirmed(
  actions: readonly OfflineAction[],
  id: string,
  now: string = new Date().toISOString(),
): readonly OfflineAction[] {
  return actions.map((action) =>
    action.id === id ? { ...action, state: 'CONFIRMED' as const, resolvedAt: now } : action,
  );
}

export function markRejected(
  actions: readonly OfflineAction[],
  id: string,
  reason: string,
  now: string = new Date().toISOString(),
): readonly OfflineAction[] {
  return actions.map((action) =>
    action.id === id
      ? { ...action, state: 'REJECTED' as const, failureReason: reason, resolvedAt: now }
      : action,
  );
}

/**
 * Resolve a reconciliation once the server has been asked.
 *
 * `applied` must come from querying the server by idempotency key, never from
 * guessing. This is the only path out of NEEDS_RECONCILIATION.
 */
export function resolveReconciliation(
  actions: readonly OfflineAction[],
  id: string,
  applied: boolean,
  now: string = new Date().toISOString(),
): readonly OfflineAction[] {
  return actions.map((action) => {
    if (action.id !== id || action.state !== 'NEEDS_RECONCILIATION') return action;
    if (applied) {
      return { ...action, state: 'CONFIRMED' as const, resolvedAt: now };
    }
    // Not applied: safe to send again under the same key. The stale failure
    // reason is dropped rather than set to undefined, so the field is genuinely
    // absent instead of present-and-empty.
    const { failureReason: _discarded, ...rest } = action;
    return { ...rest, state: 'PENDING' as const };
  });
}

/**
 * Prune terminal actions older than the retention window.
 *
 * Anything unresolved is kept regardless of age: a queue that quietly discards
 * an unreconciled supply destroys the only local record that it happened.
 */
export function prune(
  actions: readonly OfflineAction[],
  retentionDays = 30,
  now: Date = new Date(),
): readonly OfflineAction[] {
  const cutoff = now.getTime() - retentionDays * 24 * 60 * 60 * 1000;
  return actions.filter((action) => {
    if (action.state !== 'CONFIRMED' && action.state !== 'REJECTED') return true;
    const resolved = Date.parse(action.resolvedAt ?? action.queuedAt);
    return !Number.isFinite(resolved) || resolved >= cutoff;
  });
}

export interface QueueSummary {
  readonly pending: number;
  readonly inFlight: number;
  readonly needsReconciliation: number;
  readonly rejected: number;
}

export function summariseQueue(actions: readonly OfflineAction[]): QueueSummary {
  return {
    pending: actions.filter((a) => a.state === 'PENDING').length,
    inFlight: actions.filter((a) => a.state === 'IN_FLIGHT').length,
    needsReconciliation: actions.filter((a) => a.state === 'NEEDS_RECONCILIATION').length,
    rejected: actions.filter((a) => a.state === 'REJECTED').length,
  };
}
