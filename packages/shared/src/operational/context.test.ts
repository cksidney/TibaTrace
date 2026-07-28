import { describe, expect, it } from 'vitest';

import { resolveOperationalContext } from './context.js';
import type { OperationalContextInput } from './context.js';

function operationalInput(overrides: Partial<OperationalContextInput> = {}): OperationalContextInput {
  return {
    deviceId: 'device-1',
    operatorId: 'operator-1',
    registers: [{ id: 'register-1', code: 'TILL-01', name: 'Main till', branch_code: 'HQ', device_id: 'device-1', currency: 'KES', state: 'OPEN', expected_float: '0.00', last_synchronised_at: '2026-07-28T09:00:00Z' }],
    businessDays: [{ id: 'day-1', branch_code: 'HQ', business_date: '2026-07-28', state: 'OPEN', opened_at: '2026-07-28T06:00:00Z', closed_at: null, accepts_transactions: true, reopen_reason: '' }],
    openSessions: [{ id: 'session-1', register_code: 'TILL-01', business_date: '2026-07-28', state: 'OPEN', opened_at: '2026-07-28T06:00:00Z', opened_by_username: 'supervisor', closed_at: null, closed_by_username: '', forced_closure: false, forced_closure_reason: '', has_final_report: false, operator_shifts: [{ id: 'shift-1', operator_id: 'operator-1', operator_username: 'cashier', state: 'OPEN', started_at: '2026-07-28T07:00:00Z', ended_at: null, handed_over_to_username: '', close_reason: '' }] }],
    devices: [{ id: 'health-1', device_id: 'device-1', device_type: 'TERMINAL', status: 'OK', printer_paper_level: 'OK', scanner_connected: true, cash_drawer_open: false, network_latency_ms: 20, battery_level_pct: null, storage_used_pct: 21 }],
    ...overrides,
  };
}

describe('resolveOperationalContext', () => {
  it('only marks a device ready when register, business day, shift and health all match', () => {
    const result = resolveOperationalContext(operationalInput());
    expect(result.readiness).toBe('READY');
    expect(result.register?.code).toBe('TILL-01');
    expect(result.operatorShift?.operator_id).toBe('operator-1');
    expect(result.notices).toEqual([]);
  });

  it('does not guess a register when a device has no explicit assignment', () => {
    const result = resolveOperationalContext(operationalInput({ deviceId: 'other-device' }));
    expect(result.readiness).toBe('UNASSIGNED');
    expect(result.notices).toEqual(['This device is not assigned to a register.']);
  });

  it('requires an accountable shift for the signed-in operator', () => {
    const result = resolveOperationalContext(operationalInput({ operatorId: 'other-operator' }));
    expect(result.readiness).toBe('ATTENTION');
    expect(result.notices).toContain('No active accountable operator shift was found for this session.');
  });

  it('surfaces printer and terminal warnings as an exception', () => {
    const baseline = operationalInput();
    const result = resolveOperationalContext({
      ...baseline,
      devices: [{ ...baseline.devices[0]!, status: 'WARNING', printer_paper_level: 'LOW' }],
    });
    expect(result.readiness).toBe('ATTENTION');
    expect(result.notices).toContain('The device or printer requires attention before continuing.');
  });
});
