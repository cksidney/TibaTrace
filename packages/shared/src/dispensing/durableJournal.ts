import {
  canProceed,
  markConfirmed,
  markRejected,
  markSent,
  prune,
  recoverAfterRestart,
  resolveReconciliation,
  summariseQueue,
} from './offlineQueue.js';
import type {
  OfflineAction,
  OfflineActionType,
  OfflineStore,
  QueueSummary,
} from './offlineQueue.js';

interface JournalOutcome {
  readonly kind: 'ok' | 'blocked' | 'unknown';
  readonly message?: string;
}

export interface JournalAction {
  readonly id: string;
  readonly type: OfflineActionType;
  readonly episodeId: string;
  readonly idempotencyKey: string;
  readonly payload: Record<string, unknown>;
}

export class DurableActionJournal {
  private readonly store: OfflineStore;
  private actions: readonly OfflineAction[] = [];
  private ready = false;

  constructor(store: OfflineStore) {
    this.store = store;
  }

  get summary(): QueueSummary {
    return summariseQueue(this.actions);
  }

  /** Immutable view for the native Sync Centre; callers cannot mutate storage. */
  get entries(): readonly OfflineAction[] {
    return this.actions;
  }

  async initialise(): Promise<QueueSummary> {
    const recovered = recoverAfterRestart(await this.store.read());
    this.actions = prune(recovered);
    await this.store.write(this.actions);
    this.ready = true;
    return this.summary;
  }

  canProceed(episodeId: string): boolean {
    return this.ready && canProceed(this.actions, episodeId);
  }

  async run<T extends JournalOutcome>(
    input: JournalAction,
    action: () => Promise<T>,
  ): Promise<T> {
    if (!this.ready) throw new Error('The durable action journal is not ready.');
    if (!canProceed(this.actions, input.episodeId)) {
      throw new Error(
        'A previous payment or collection has an unknown outcome. Reconcile it before continuing.',
      );
    }

    const queued: OfflineAction = {
      ...input,
      state: 'PENDING',
      queuedAt: new Date().toISOString(),
      attempts: 0,
    };
    this.actions = [...this.actions, queued];
    await this.persist(markSent(this.actions, queued.id));

    try {
      const outcome = await action();
      if (outcome.kind === 'ok') {
        await this.persist(markConfirmed(this.actions, queued.id));
      } else if (outcome.kind === 'blocked') {
        await this.persist(
          markRejected(
            this.actions,
            queued.id,
            outcome.message ?? 'The server rejected this action.',
          ),
        );
      } else {
        await this.persist(recoverAfterRestart(this.actions));
      }
      return outcome;
    } catch (cause) {
      await this.persist(recoverAfterRestart(this.actions));
      throw cause;
    }
  }

  /**
   * Resolve one unknown consequential action after the server looked up its
   * original idempotency key. This method deliberately cannot dispatch or
   * discard the action: an absent authoritative record becomes PENDING and
   * may be retried only through its original workflow.
   */
  async reconcile(id: string, applied: boolean): Promise<QueueSummary> {
    if (!this.ready) throw new Error('The durable action journal is not ready.');
    const entry = this.actions.find((candidate) => candidate.id === id);
    if (!entry) throw new Error('The durable action was not found in this device journal.');
    if (entry.state !== 'NEEDS_RECONCILIATION') {
      throw new Error('Only an unknown consequential action can be reconciled.');
    }
    await this.persist(resolveReconciliation(this.actions, id, applied));
    return this.summary;
  }

  private async persist(actions: readonly OfflineAction[]): Promise<void> {
    this.actions = actions;
    await this.store.write(actions);
  }
}
