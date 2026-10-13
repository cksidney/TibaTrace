import { describe, expect, it, vi } from 'vitest';
import { clinicalCommand, reservationQuantityValid } from './clinicalCommands.js';
import { FINAL_CHECK_ITEMS } from './types.js';

describe('governed clinical commands', () => {
  it('records a canonical independent check, never a status transition', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{}'));
    await clinicalCommand(fetcher, 'ep-1', 'check', { checklist: { patient: true } });
    expect(fetcher.mock.calls[0]?.[0]).toBe('/api/pos/dispensing/episodes/ep-1/check/');
    expect(FINAL_CHECK_ITEMS).toHaveLength(10);
  });
  it('surfaces business refusal and unknown outcome distinctly', async () => {
    const refused = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'The preparer cannot check.' }), { status: 400 }));
    await expect(clinicalCommand(refused, 'ep', 'check', {})).rejects.toThrow('preparer cannot check');
    await expect(clinicalCommand(vi.fn().mockRejectedValue(new Error('timeout')), 'ep', 'reserve', {})).rejects.toThrow('Outcome unknown');
  });
  it('requires an explicit positive quantity within authority and no existing reservation', () => {
    const item = { id: 'i', medicine_name: 'Test', sku_id: 's', quantity_remaining: '10', reserved_quantity: '0', unit: 'TABLET' };
    expect(reservationQuantityValid(item, '10')).toBe(true);
    expect(reservationQuantityValid(item, '11')).toBe(false);
    expect(reservationQuantityValid(item, '0')).toBe(false);
    expect(reservationQuantityValid({ ...item, reserved_quantity: '1' }, '1')).toBe(false);
  });
});
