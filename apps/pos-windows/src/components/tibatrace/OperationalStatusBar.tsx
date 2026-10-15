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
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: spacing.sm,
        padding: `5px clamp(${spacing.md}px, 2vw, ${spacing.xl}px)`,
        borderBottom: `1px solid ${palette.border}`,
        background: palette.surface,
        color: palette.foreground,
      }}
    >
      <div aria-live="polite" style={{ display: 'flex', alignItems: 'center', gap: spacing.sm, minWidth: 0 }}>
        <span
          style={{
            display: 'inline-block',
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: context?.readiness === 'READY' ? '#10B981' : context?.readiness === 'UNASSIGNED' || error ? '#EF4444' : '#F59E0B',
            flexShrink: 0,
          }}
        />
        <strong style={{ fontSize: 12, whiteSpace: 'nowrap' }}>{readiness}</strong>
        {details ? (
          <span style={{ fontSize: 11, color: text.secondary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 300 }} title={details}>
            · {details}
          </span>
        ) : null}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: spacing.md, flexWrap: 'wrap' }}>
        <StatusItem label="Branch" value={context?.register?.branch_code ?? 'Unassigned'} />
        <StatusItem label="Register" value={context?.register?.code ?? 'Unassigned'} />
        <StatusItem label="Date" value={context?.business_day?.business_date ?? 'Unavailable'} />
        <StatusItem label="Shift" value={shift} />
        <StatusItem label="Printer" value={printer} />
        <StatusItem label="Sync" value={sync} />
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={refreshing}
          style={{
            minHeight: 26,
            padding: '2px 8px',
            border: `1px solid ${palette.border}`,
            borderRadius: 6,
            background: surface.raised,
            color: palette.foreground,
            fontSize: 11,
            fontWeight: 600,
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
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 4, minWidth: 0, fontSize: 12 }} title={`${label}: ${value}`}>
      <span style={{ fontSize: 11, color: text.secondary, textTransform: 'uppercase', letterSpacing: 0.5 }}>{label}:</span>
      <span style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 150 }}>{value}</span>
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
