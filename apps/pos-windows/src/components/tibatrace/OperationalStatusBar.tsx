import {
  PosOperationsClient,
} from '@dawatrace/shared/operational/index.js';
import type { PosOperationalRuntimeDTO } from '@dawatrace/shared/operational/index.js';
import { PosIcon } from './PosIcon.js';
import { useCallback, useEffect, useMemo, useState } from 'react';

interface OperationalStatusBarProps {
  readonly apiFetch: typeof fetch;
  readonly deviceId: string;
  readonly onOpenWorkspace?: (workspace: 'register' | 'print' | 'sync') => void;
}

export function OperationalStatusBar({
  apiFetch,
  deviceId,
  onOpenWorkspace,
}: OperationalStatusBarProps) {
  const client = useMemo(
    () => new PosOperationsClient('/api/pos/shift', { fetcher: apiFetch }),
    [apiFetch],
  );
  const [context, setContext] = useState<PosOperationalRuntimeDTO | null>(null);
  const [expanded, setExpanded] = useState(false);
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

  return <section className={`pos-status-strip ${context?.readiness === 'READY' ? 'is-ready' : 'needs-attention'}`} aria-label="Operational status">
    <div className="pos-status-overview"><span className="pos-status-dot" /><strong>{readiness}</strong><span className="pos-status-location">{context?.register?.branch_code ?? 'Branch unassigned'} <span>/</span> {context?.register?.code ?? 'Register unassigned'}</span>
      <div className="pos-status-actions">{context && context.readiness !== 'READY' && onOpenWorkspace && <button type="button" onClick={() => onOpenWorkspace('register')}>Open Register <PosIcon name="arrow" size={14} /></button>}<button type="button" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>{expanded ? 'Hide status' : 'View status'}</button><button type="button" aria-label="Refresh operational status" disabled={refreshing} onClick={() => void refresh()}><PosIcon name="sync" size={15} />{refreshing ? 'Refreshing…' : 'Refresh'}</button></div>
    </div>
    {expanded && <div className="pos-status-details"><p>{details}</p><dl><StatusItem label="Business day" value={context?.business_day?.business_date ?? 'Not opened'} /><StatusItem label="Operator shift" value={shift} /><StatusItem label="Printer" value={printer} /><StatusItem label="Last sync" value={sync} /><StatusItem label="Customers served" value={context?.operator_shift ? String(context.operator_shift.served_customer_count ?? 'Unavailable') : 'No active shift'} /></dl></div>}
  </section>;
}

function StatusItem({ label, value }: { readonly label: string; readonly value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Invalid timestamp' : date.toLocaleString();
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Unknown time' : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
