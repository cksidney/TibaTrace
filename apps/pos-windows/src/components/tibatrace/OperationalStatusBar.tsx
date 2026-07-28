import {
  PosOperationsClient,
} from '@dawatrace/shared/operational/index.js';
import type { PosOperationalRuntimeDTO } from '@dawatrace/shared/operational/index.js';
import { spacing, statusPalette, surface, text } from '@dawatrace/shared/design-system/index.js';
import { useCallback, useEffect, useMemo, useState } from 'react';

interface OperationalStatusBarProps {
  readonly apiFetch: typeof fetch;
  readonly deviceId: string;
}

export function OperationalStatusBar({
  apiFetch,
  deviceId,
}: OperationalStatusBarProps) {
  const client = useMemo(
    () => new PosOperationsClient('/api/pos/shift', { fetcher: apiFetch }),
    [apiFetch],
  );
  const [context, setContext] = useState<PosOperationalRuntimeDTO | null>(null);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      setContext(await client.getRuntime(deviceId));
      setError('');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setContext(null);
    } finally {
      setRefreshing(false);
    }
  }, [client, deviceId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const palette =
    context?.readiness === 'READY'
      ? statusPalette.SAFE
      : context?.readiness === 'UNASSIGNED' || error
        ? statusPalette.BLOCKING
        : statusPalette.ACTION_REQUIRED;
  const readiness = error
    ? 'Status unavailable'
    : context?.readiness === 'READY'
      ? 'Operational context verified'
      : context?.readiness === 'UNASSIGNED'
        ? 'Register assignment required'
        : context
          ? 'Operational attention required'
          : 'Loading operational context';
  const printer = context?.device_health
    ? `${context.device_health.status} · paper ${context.device_health.printer_paper_level}`
    : 'No device report';
  const sync = context?.register?.last_synchronised_at
    ? `Recorded ${formatDateTime(context.register.last_synchronised_at)}`
    : 'No sync record';
  const shift = context?.operator_shift
    ? `${context.operator_shift.state.replace(/_/g, ' ')} since ${formatTime(context.operator_shift.started_at)}`
    : 'No active shift';
  const details = error || context?.notices.join(' ') || 'Register, business day, operator shift and device health match this session.';

  return (
    <section
      aria-label="Operational status"
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(240px, 1.4fr) repeat(5, minmax(110px, 1fr)) auto',
        gap: spacing.md,
        alignItems: 'center',
        padding: `${spacing.sm}px ${spacing.xl}px`,
        borderBottom: `1px solid ${palette.border}`,
        background: palette.surface,
        color: palette.foreground,
      }}
    >
      <div aria-live="polite">
        <strong>{readiness}</strong>
        <div style={{ marginTop: 2, fontSize: 12, color: text.secondary }}>{details}</div>
      </div>
      <StatusItem label="Branch" value={context?.register?.branch_code ?? 'Unassigned'} />
      <StatusItem label="Register" value={context?.register?.code ?? 'Unassigned'} />
      <StatusItem label="Business date" value={context?.business_day?.business_date ?? 'Unavailable'} />
      <StatusItem label="Shift" value={shift} />
      <StatusItem label="Printer" value={printer} />
      <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm }}>
        <StatusItem label="Sync" value={sync} />
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={refreshing}
          style={{
            minHeight: 36,
            padding: '6px 10px',
            border: `1px solid ${palette.border}`,
            borderRadius: 8,
            background: surface.raised,
            color: palette.foreground,
            cursor: refreshing ? 'wait' : 'pointer',
          }}
        >
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
    </section>
  );
}

function StatusItem({ label, value }: { readonly label: string; readonly value: string }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: 11, color: text.secondary, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        {label}
      </div>
      <div style={{ marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 13 }} title={value}>
        {value}
      </div>
    </div>
  );
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Invalid timestamp' : date.toLocaleString();
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Unknown time' : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
