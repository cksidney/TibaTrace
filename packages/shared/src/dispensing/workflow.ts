/**
 * Platform-agnostic dispensing workflow controller.
 *
 * Windows and Android both drive this, so neither can end up with weaker rules
 * than the other. It holds no clinical policy of its own: it calls the server,
 * stores what the server returned, and derives what the operator may do next
 * from that. When the answer is unknown it reports unknown rather than
 * guessing, because in a dispensing context an optimistic guess means telling a
 * pharmacist that money moved or stock left the shelf when it did not.
 */
import type { PosDispensingClient } from './client.js';
import { PosApiError } from './errors.js';
import type {
  CollectionConfirmRequest,
  CounsellingRecordRequest,
  DispensingEpisodeDTO,
  PaymentProcessRequest,
} from './types.js';
import { paymentPermitsSupply } from './types.js';

/** What the operator is allowed to attempt, and why not when they cannot. */
export interface GateState {
  readonly canTakePayment: boolean;
  readonly canConfirmCollection: boolean;
  readonly blockedReason: string;
  /**
   * True when a write completed with an unknown outcome. The UI must refuse to
   * progress and force a refresh -- never retry blindly, never assume failure.
   */
  readonly outcomeUnknown: boolean;
}

export type ActionOutcome =
  | { readonly kind: 'ok'; readonly episode: DispensingEpisodeDTO }
  | { readonly kind: 'blocked'; readonly code: string; readonly message: string }
  | { readonly kind: 'unknown'; readonly message: string };

export class DispensingWorkflow {
  private readonly client: PosDispensingClient;
  private episode: DispensingEpisodeDTO | null = null;
  private unknownOutcome = false;

  constructor(client: PosDispensingClient) {
    this.client = client;
  }

  get current(): DispensingEpisodeDTO | null {
    return this.episode;
  }

  async load(episodeId: string): Promise<DispensingEpisodeDTO> {
    const episode = await this.client.getEpisode(episodeId);
    this.episode = episode;
    this.unknownOutcome = false;
    return episode;
  }

  /**
   * Re-read authoritative state. Required after any unknown outcome, and after
   * a restart, before the UI re-enables anything.
   */
  async refresh(): Promise<DispensingEpisodeDTO | null> {
    if (!this.episode) return null;
    const episode = await this.client.getEpisode(this.episode.id);
    this.episode = episode;
    this.unknownOutcome = false;
    return episode;
  }

  /**
   * Derived purely from server state. This decides what to grey out; it never
   * authorises anything, and the server rejects independently.
   */
  gate(): GateState {
    const episode = this.episode;
    if (!episode) {
      return {
        canTakePayment: false,
        canConfirmCollection: false,
        blockedReason: 'No dispensing episode loaded.',
        outcomeUnknown: false,
      };
    }
    if (this.unknownOutcome) {
      return {
        canTakePayment: false,
        canConfirmCollection: false,
        blockedReason:
          'The last action did not complete cleanly. Refresh to read the current state before continuing.',
        outcomeUnknown: true,
      };
    }

    const canTakePayment = episode.status === 'READY_FOR_PAYMENT';
    const paymentSettled = paymentPermitsSupply(episode.payment_state);
    const supplyStatus =
      episode.status === 'READY_FOR_SUPPLY' ||
      episode.status === 'READY_FOR_COLLECTION' ||
      episode.status === 'PARTIALLY_SUPPLIED';

    let blockedReason = '';
    if (!canTakePayment && !supplyStatus) {
      blockedReason = `Episode is ${episode.status}; no payment or supply action is available.`;
    } else if (supplyStatus && !paymentSettled) {
      // The single most important message in the UI: part-payment must not
      // release stock, and the operator needs to know exactly why.
      blockedReason =
        episode.payment_state === 'PARTIALLY_PAID'
          ? 'Partially paid. The balance must be settled before medicine can be supplied.'
          : `Payment state is ${episode.payment_state}; supply is not permitted.`;
    }

    return {
      canTakePayment,
      canConfirmCollection: supplyStatus && paymentSettled,
      blockedReason,
      outcomeUnknown: false,
    };
  }

  async takePayment(request: PaymentProcessRequest): Promise<ActionOutcome> {
    return this.run(async () => {
      await this.client.processPayment(this.requireEpisode().id, request);
      // Deliberately re-read rather than trusting the action response: the
      // episode's canonical state is a server projection.
      return this.refreshOrThrow();
    });
  }

  async recordCounselling(request: CounsellingRecordRequest): Promise<ActionOutcome> {
    return this.run(async () => {
      await this.client.recordCounselling(this.requireEpisode().id, request);
      return this.refreshOrThrow();
    });
  }

  async confirmCollection(request: CollectionConfirmRequest): Promise<ActionOutcome> {
    return this.run(async () => {
      await this.client.confirmCollection(this.requireEpisode().id, request);
      return this.refreshOrThrow();
    });
  }

  async transition(newStatus: string, notes = ''): Promise<ActionOutcome> {
    return this.run(async () => {
      await this.client.transitionState(this.requireEpisode().id, {
        new_status: newStatus,
        notes,
      });
      return this.refreshOrThrow();
    });
  }

  private requireEpisode(): DispensingEpisodeDTO {
    if (!this.episode) throw new Error('No dispensing episode loaded.');
    return this.episode;
  }

  private async refreshOrThrow(): Promise<DispensingEpisodeDTO> {
    const episode = await this.refresh();
    if (!episode) throw new Error('Episode disappeared during refresh.');
    return episode;
  }

  private async run(action: () => Promise<DispensingEpisodeDTO>): Promise<ActionOutcome> {
    try {
      const episode = await action();
      return { kind: 'ok', episode };
    } catch (error) {
      if (error instanceof PosApiError) {
        if (error.code === 'NETWORK_UNAVAILABLE') {
          // Latch it: the write may have landed. The gate stays shut until a
          // successful refresh proves otherwise.
          this.unknownOutcome = true;
          return { kind: 'unknown', message: error.message };
        }
        return { kind: 'blocked', code: error.code, message: error.message };
      }
      throw error;
    }
  }
}

/**
 * Idempotency keys for POS actions.
 *
 * Stable for a given attempt so a retry cannot double-charge, and distinct per
 * episode and action so unrelated operations never collide.
 */
export function actionIdempotencyKey(
  episodeId: string,
  action: string,
  attemptId: string,
): string {
  return `${action}:${episodeId}:${attemptId}`;
}
