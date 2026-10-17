import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PosDispensingClient, type DispensingEpisodeDTO, type PaymentProcessResponse } from '@dawatrace/shared/dispensing/index.js';

import { usePosWorkflow } from './usePosWorkflow.js';

const pendingEpisode = {
  id: 'episode-1', status: 'READY_FOR_PAYMENT', payment_state: 'PENDING',
  collected_at: null, lines: [],
} as unknown as DispensingEpisodeDTO;

describe('returning from a dispensing episode', () => {
  let root: Root;
  let container: HTMLDivElement;
  let current: ReturnType<typeof usePosWorkflow>;

  beforeEach(() => {
    (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement('div');
    document.body.append(container);
    root = createRoot(container);
    function Harness() {
      current = usePosWorkflow();
      return null;
    }
    act(() => root.render(<Harness />));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
  });

  it('keeps the same episode during payment and rejects duplicate submissions', async () => {
    const settled = { ...pendingEpisode, status: 'PAID', payment_state: 'PAID' } as DispensingEpisodeDTO;
    vi.spyOn(PosDispensingClient.prototype, 'getEpisode')
      .mockResolvedValueOnce(pendingEpisode).mockResolvedValue(settled);
    let completePayment!: (value: PaymentProcessResponse) => void;
    const processPayment = vi.spyOn(PosDispensingClient.prototype, 'processPayment')
      .mockReturnValue(new Promise((resolve) => { completePayment = resolve; }));
    await act(async () => { await current.select('episode-1'); });
    let payment!: Promise<unknown>;
    act(() => { payment = current.takePayment('CASH', '100.00', ''); });
    expect(current.state.busy).toBe(true);
    await act(async () => {
      await current.select(null);
      await current.takePayment('CASH', '100.00', '');
    });
    expect(current.state.selected?.id).toBe('episode-1');
    expect(processPayment).toHaveBeenCalledTimes(1);
    await act(async () => {
      completePayment({ success: true, episode_id: 'episode-1', replayed: false } as PaymentProcessResponse);
      await payment;
    });
    expect(current.state.selected?.payment_state).toBe('PAID');
    expect(current.state.busy).toBe(false);
    await act(async () => { await current.select(null); });
    expect(current.state.selected).toBeNull();
    expect(current.state.gate.canTakePayment).toBe(false);
    expect(current.state.gate.canConfirmCollection).toBe(false);
  });

  it('does not switch episodes while an authoritative read is pending', async () => {
    let completeLoad!: (value: DispensingEpisodeDTO) => void;
    const load = vi.spyOn(PosDispensingClient.prototype, 'getEpisode')
      .mockReturnValue(new Promise((resolve) => { completeLoad = resolve; }));
    let selection!: Promise<void>;
    act(() => { selection = current.select('episode-1'); });
    await act(async () => { await current.select('episode-2'); });
    expect(load).toHaveBeenCalledTimes(1);
    await act(async () => { completeLoad(pendingEpisode); await selection; });
    expect(current.state.selected?.id).toBe('episode-1');
  });
});
