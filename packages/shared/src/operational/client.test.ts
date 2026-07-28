import { describe, expect, it } from 'vitest';

import { PosOperationsClient } from './client.js';

describe('PosOperationsClient', () => {
  it('submits a blind closing count to the selected register and device', async () => {
    const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
      expect(String(input)).toBe('/api/pos/shift/registers/register-1/close/');
      expect(init?.method).toBe('POST');
      expect(JSON.parse(String(init?.body))).toEqual({
        device_id: 'device-1',
        declared_amount: '6500.00',
        denominations: { 1000: 6, 500: 1 },
        reason: 'End of shift',
      });
      return new Response(JSON.stringify({ report_number: 'HQ/TILL-01/2026-07-28/Z/0001' }), { status: 200 });
    };
    const client = new PosOperationsClient('/api/pos/shift', { fetcher: fetcher as typeof fetch });

    const report = await client.closeRegister('register-1', {
      deviceId: 'device-1',
      declaredAmount: '6500.00',
      denominations: { 1000: 6, 500: 1 },
      reason: 'End of shift',
    });

    expect(report.report_number).toBe('HQ/TILL-01/2026-07-28/Z/0001');
  });

  it('accepts only the named pending shift on the active device', async () => {
    const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
      expect(String(input)).toBe('/api/pos/shift/shifts/shift-outgoing/accept-handover/');
      expect(init?.method).toBe('POST');
      expect(JSON.parse(String(init?.body))).toEqual({ device_id: 'device-1' });
      return new Response(JSON.stringify({
        outgoing_shift: { id: 'shift-outgoing', state: 'CLOSED' },
        operator_shift: { id: 'shift-incoming', state: 'OPEN' },
      }), { status: 201 });
    };
    const client = new PosOperationsClient('/api/pos/shift', { fetcher: fetcher as typeof fetch });

    const result = await client.acceptHandover('shift-outgoing', 'device-1');

    expect(result.outgoing_shift.state).toBe('CLOSED');
    expect(result.operator_shift.state).toBe('OPEN');
  });

  it('preserves the server refusal instead of replacing it with a generic status', async () => {
    const client = new PosOperationsClient('/api/pos/shift', {
      fetcher: (async () => new Response(
        JSON.stringify({ detail: ['A different operator must approve this movement.'] }),
        { status: 400, headers: { 'Content-Type': 'application/json' } },
      )) as typeof fetch,
    });

    await expect(client.approveCashMovement('movement-1')).rejects.toThrow(
      'A different operator must approve this movement.',
    );
  });
});
