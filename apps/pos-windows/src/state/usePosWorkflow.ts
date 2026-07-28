import {
  DispensingWorkflow,
  DurableActionJournal,
  PosApiError,
  PosDispensingClient,
  actionIdempotencyKey,
} from '@dawatrace/shared/dispensing/index.js';
import type {
  ActionOutcome,
  CounsellingRecordRequest,
  DispensingEpisodeDTO,
  GateState,
  OfflineStore,
} from '@dawatrace/shared/dispensing/index.js';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

export interface PosState {
  readonly queue: readonly DispensingEpisodeDTO[];
  readonly selected: DispensingEpisodeDTO | null;
  readonly gate: GateState;
  readonly busy: boolean;
  /** Last refusal from the server, shown verbatim rather than reinterpreted. */
  readonly notice: { kind: 'blocked' | 'unknown' | 'error'; message: string } | null;
}

const EMPTY_GATE: GateState = {
  canTakePayment: false,
  canConfirmCollection: false,
  blockedReason: 'No dispensing episode selected.',
  outcomeUnknown: false,
};

export function usePosWorkflow(
  baseUrl = '/api/pos/dispensing',
  fetcher: typeof fetch = fetch,
  offlineStore?: OfflineStore,
  deviceId = '',
) {
  const client = useMemo(
    () => new PosDispensingClient(baseUrl, '', 15000, { fetcher }),
    [baseUrl, fetcher],
  );
  const workflow = useMemo(() => new DispensingWorkflow(client), [client]);
  const journal = useMemo(
    () => (offlineStore ? new DurableActionJournal(offlineStore) : null),
    [offlineStore],
  );

  const [queue, setQueue] = useState<readonly DispensingEpisodeDTO[]>([]);
  const [selected, setSelected] = useState<DispensingEpisodeDTO | null>(null);
  const [gate, setGate] = useState<GateState>(EMPTY_GATE);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<PosState['notice']>(null);
  const [journalReady, setJournalReady] = useState(journal === null);
  const [journalBlocked, setJournalBlocked] = useState(false);

  /**
   * One attempt id per in-flight action. Retrying the *same* attempt reuses the
   * key so the server treats it as a replay; a new action gets a new one.
   */
  const attemptId = useRef<string>(crypto.randomUUID());

  useEffect(() => {
    if (!journal) return;
    void journal
      .initialise()
      .then(() => setJournalReady(true))
      .catch((error: unknown) => {
        setNotice(describe(error));
        setJournalReady(false);
      });
  }, [journal]);

  const sync = useCallback(() => {
    setSelected(workflow.current);
    setGate(workflow.gate());
    setJournalBlocked(
      workflow.current ? !(journal?.canProceed(workflow.current.id) ?? true) : false,
    );
  }, [workflow, journal]);

  const refreshQueue = useCallback(async () => {
    setBusy(true);
    try {
      setQueue(await client.getQueue());
      setNotice(null);
    } catch (error) {
      setNotice(describe(error));
    } finally {
      setBusy(false);
    }
  }, [client]);

  const select = useCallback(
    async (episodeId: string) => {
      setBusy(true);
      try {
        await workflow.load(episodeId);
        attemptId.current = crypto.randomUUID();
        setNotice(null);
      } catch (error) {
        setNotice(describe(error));
      } finally {
        sync();
        setBusy(false);
      }
    },
    [workflow, sync],
  );

  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      await workflow.refresh();
      setNotice(null);
    } catch (error) {
      setNotice(describe(error));
    } finally {
      sync();
      setBusy(false);
    }
  }, [workflow, sync]);

  const run = useCallback(
    async (action: () => Promise<ActionOutcome>) => {
      setBusy(true);
      try {
        const outcome = await action();
        if (outcome.kind === 'ok') {
          attemptId.current = crypto.randomUUID();
          setNotice(null);
        } else {
          setNotice({ kind: outcome.kind === 'unknown' ? 'unknown' : 'blocked', message: outcome.message });
        }
        return outcome;
      } catch (error) {
        setNotice(describe(error));
        return null;
      } finally {
        sync();
        setBusy(false);
      }
    },
    [sync],
  );

  const takePayment = useCallback(
    (tenderType: 'CASH' | 'CARD' | 'MPESA', amount: string, reference: string) => {
      const episode = workflow.current;
      if (!episode) return Promise.resolve(null);
      const idempotencyKey = actionIdempotencyKey(
        episode.id,
        'payment',
        attemptId.current,
      );
      const request = {
          tender_type: tenderType,
          paid_amount: amount,
          payment_reference: reference,
          device_id: deviceId,
          idempotency_key: idempotencyKey,
        };
      return run(() =>
        journal
          ? journal.run(
              {
                id: crypto.randomUUID(),
                type: 'PAYMENT',
                episodeId: episode.id,
                idempotencyKey,
                payload: request,
              },
              () => workflow.takePayment(request),
            )
          : workflow.takePayment(request),
      );
    },
    [workflow, run, journal, deviceId],
  );

  const confirmCollection = useCallback(
    (collectorName: string, idNumber: string, relationship: string) => {
      const episode = workflow.current;
      if (!episode) return Promise.resolve(null);
      const idempotencyKey = actionIdempotencyKey(
        episode.id,
        'collection',
        attemptId.current,
      );
      const request = {
          collector_name: collectorName,
          collector_id_number: idNumber,
          collector_relationship: relationship,
          idempotency_key: idempotencyKey,
        };
      return run(() =>
        journal
          ? journal.run(
              {
                id: crypto.randomUUID(),
                type: 'COLLECTION',
                episodeId: episode.id,
                idempotencyKey,
                payload: request,
              },
              () => workflow.confirmCollection(request),
            )
          : workflow.confirmCollection(request),
      );
    },
    [workflow, run, journal],
  );

  const recordCounselling = useCallback(
    // Takes the whole request: the server defaults every omitted counselling
    // flag to true, so a partial body would record topics that were never
    // covered.
    (request: CounsellingRecordRequest) => run(() => workflow.recordCounselling(request)),
    [workflow, run],
  );

  const transition = useCallback(
    (status: string) => run(() => workflow.transition(status)),
    [workflow, run],
  );

  const effectiveGate: GateState =
    !journalReady || journalBlocked
      ? {
          canTakePayment: false,
          canConfirmCollection: false,
          blockedReason: !journalReady
            ? 'Secure action recovery is still starting.'
            : 'A previous payment or collection has an unknown outcome. Reconcile it before continuing.',
          outcomeUnknown: journalBlocked,
        }
      : gate;

  return {
    client,
    state: { queue, selected, gate: effectiveGate, busy, notice } satisfies PosState,
    refreshQueue,
    select,
    refresh,
    takePayment,
    confirmCollection,
    recordCounselling,
    transition,
    journal,
  };
}

function describe(error: unknown): PosState['notice'] {
  if (error instanceof PosApiError) {
    return {
      kind: error.code === 'NETWORK_UNAVAILABLE' ? 'unknown' : 'blocked',
      message: error.message,
    };
  }
  return { kind: 'error', message: error instanceof Error ? error.message : String(error) };
}
