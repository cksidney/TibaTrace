import { describe, expect, it, vi } from 'vitest';

import { PosDispensingClient } from './client.js';
import { PosApiError } from './errors.js';
import type { DispensingEpisodeDTO, PaymentState } from './types.js';
import { DispensingWorkflow } from './workflow.js';

function episode(overrides: Partial<DispensingEpisodeDTO> = {}): DispensingEpisodeDTO {
  return {
    id: 'ep-1',
    dispensing_number: 'DISP-1',
    prescription: 'rx-1',
    patient: 'pat-1',
    branch: 'br-1',
    pharmacy_location: 'wh-1',
    pharmacist: 'u-1',
    status: 'READY_FOR_SUPPLY',
    initiated_at: '2026-01-01T00:00:00Z',
    completed_at: null,
    payment_state: 'PAID',
    payment_reference: '',
    tender_type: 'CASH',
    paid_amount: '0',
    collector_name: '',
    collector_id_number: '',
    collector_phone: '',
    collector_relationship: '',
    collection_proof_type: '',
    collected_at: null,
    controlled_witness: null,
    controlled_authority_checked: false,
    counselling_status: 'NOT_STARTED',
    notes: '',
    idempotency_key: 'k',
    lines: [],
    ...overrides,
  } as DispensingEpisodeDTO;
}

function workflowWith(ep: DispensingEpisodeDTO) {
  const client = new PosDispensingClient();
  vi.spyOn(client, 'getEpisode').mockResolvedValue(ep);
  const workflow = new DispensingWorkflow(client);
  return { client, workflow };
}

describe('supply gate', () => {
  it('permits collection when payment is settled and status allows supply', async () => {
    const { workflow } = workflowWith(episode());
    await workflow.load('ep-1');
    const gate = workflow.gate();
    expect(gate.canConfirmCollection).toBe(true);
    expect(gate.blockedReason).toBe('');
  });

  it('blocks collection when only partially paid', async () => {
    // The central rule: part-payment must never release stock.
    const { workflow } = workflowWith(episode({ payment_state: 'PARTIALLY_PAID' }));
    await workflow.load('ep-1');
    const gate = workflow.gate();
    expect(gate.canConfirmCollection).toBe(false);
    expect(gate.blockedReason).toContain('balance must be settled');
  });

  it.each<PaymentState>(['PENDING', 'FAILED', 'CANCELLED', 'REVERSAL_PENDING', 'REVERSED'])(
    'blocks collection when payment state is %s',
    async (state) => {
      const { workflow } = workflowWith(episode({ payment_state: state }));
      await workflow.load('ep-1');
      expect(workflow.gate().canConfirmCollection).toBe(false);
    },
  );

  it('only offers payment in READY_FOR_PAYMENT', async () => {
    const { workflow } = workflowWith(episode({ status: 'PREPARING', payment_state: 'PENDING' }));
    await workflow.load('ep-1');
    expect(workflow.gate().canTakePayment).toBe(false);

    const ready = workflowWith(episode({ status: 'READY_FOR_PAYMENT', payment_state: 'PENDING' }));
    await ready.workflow.load('ep-1');
    expect(ready.workflow.gate().canTakePayment).toBe(true);
  });

  it('reports no gate before an episode is loaded', () => {
    const client = new PosDispensingClient();
    expect(new DispensingWorkflow(client).gate().canConfirmCollection).toBe(false);
  });
});

describe('server refusals', () => {
  it('surfaces a clinical refusal without changing local state', async () => {
    const ep = episode({ status: 'READY_FOR_SUPPLY' });
    const { client, workflow } = workflowWith(ep);
    await workflow.load('ep-1');
    vi.spyOn(client, 'confirmCollection').mockRejectedValue(
      new PosApiError('STALE_CLINICAL_CONTEXT', 'Basket changed.', 409),
    );

    const outcome = await workflow.confirmCollection({
      collector_name: 'John Doe',
      idempotency_key: 'collect-1',
    });

    expect(outcome.kind).toBe('blocked');
    if (outcome.kind === 'blocked') {
      expect(outcome.code).toBe('STALE_CLINICAL_CONTEXT');
    }
    // The episode must not have advanced locally.
    expect(workflow.current?.status).toBe('READY_FOR_SUPPLY');
  });

  it('classifies a 403 as forbidden rather than a generic failure', () => {
    const error = new PosApiError('FORBIDDEN', 'Not permitted.', 403);
    expect(error.retryable).toBe(false);
    expect(error.clinicallyBlocking).toBe(false);
  });

  it('does not mark clinical refusals retryable', () => {
    for (const code of ['BLOCKING_FINDINGS', 'STALE_CLINICAL_CONTEXT', 'CONFLICT'] as const) {
      expect(new PosApiError(code, '', 409).retryable).toBe(false);
    }
  });
});

describe('unknown outcomes', () => {
  it('latches the gate shut when the network drops mid-write', async () => {
    // The write may well have landed. Assuming failure and retrying could
    // double-charge; assuming success could report a supply that never happened.
    const { client, workflow } = workflowWith(episode({ status: 'READY_FOR_PAYMENT' }));
    await workflow.load('ep-1');
    vi.spyOn(client, 'processPayment').mockRejectedValue(
      new PosApiError('NETWORK_UNAVAILABLE', 'unreachable', 0),
    );

    const outcome = await workflow.takePayment({
      tender_type: 'CASH',
      paid_amount: '100.00',
      device_id: 'device-1',
      idempotency_key: 'pay-1',
    });

    expect(outcome.kind).toBe('unknown');
    const gate = workflow.gate();
    expect(gate.outcomeUnknown).toBe(true);
    expect(gate.canTakePayment).toBe(false);
    expect(gate.canConfirmCollection).toBe(false);
    expect(gate.blockedReason).toContain('Refresh');
  });

  it('clears the latch only after a successful refresh', async () => {
    const { client, workflow } = workflowWith(episode({ status: 'READY_FOR_PAYMENT' }));
    await workflow.load('ep-1');
    vi.spyOn(client, 'processPayment').mockRejectedValue(
      new PosApiError('NETWORK_UNAVAILABLE', 'unreachable', 0),
    );
    await workflow.takePayment({
      tender_type: 'CASH',
      paid_amount: '100.00',
      device_id: 'device-1',
      idempotency_key: 'pay-1',
    });
    expect(workflow.gate().outcomeUnknown).toBe(true);

    await workflow.refresh();
    expect(workflow.gate().outcomeUnknown).toBe(false);
  });
});

describe('server state is authoritative', () => {
  it('re-reads the episode after a write instead of trusting the response', async () => {
    const before = episode({ status: 'READY_FOR_PAYMENT', payment_state: 'PENDING' });
    const after = episode({ status: 'PAID', payment_state: 'PAID' });
    const client = new PosDispensingClient();
    const getEpisode = vi
      .spyOn(client, 'getEpisode')
      .mockResolvedValueOnce(before)
      .mockResolvedValue(after);
    vi.spyOn(client, 'processPayment').mockResolvedValue({
      success: true,
      episode_id: 'ep-1',
      payment_state: 'PAID',
      payment_reference: 'r',
      tender_type: 'CASH',
      paid_amount: '100.00',
      replayed: false,
    });

    const workflow = new DispensingWorkflow(client);
    await workflow.load('ep-1');
    const outcome = await workflow.takePayment({
      tender_type: 'CASH',
      paid_amount: '100.00',
      device_id: 'device-1',
      idempotency_key: 'pay-1',
    });

    expect(outcome.kind).toBe('ok');
    expect(workflow.current?.payment_state).toBe('PAID');
    // load + refresh-after-write
    expect(getEpisode).toHaveBeenCalledTimes(2);
  });
});
