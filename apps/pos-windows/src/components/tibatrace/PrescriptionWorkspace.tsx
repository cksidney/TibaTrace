import { autoColumns, fontFamily, fontSize, spacing, statusPalette, surface, text } from '@dawatrace/shared/design-system/index.js';
import type { ClinicalStatus } from '@dawatrace/shared/design-system/index.js';
import type { BatchVerificationResponse, DispensingLineDTO } from '@dawatrace/shared/dispensing/index.js';
import { useState } from 'react';

import { StatusBadge } from './StatusBadge.js';
import { BatchVerification } from './BatchVerification.js';
import { FinalCheckComparison } from './FinalCheck.js';

/**
 * The prescription workspace.
 *
 * Hierarchy is deliberate and is the whole point of the layout: medicine name
 * and strength read first, dosage instructions second, batch and expiry third,
 * price last. Price must never dominate a clinical instruction -- this is a
 * dispensary, not a checkout.
 */

/** Derived from server line status; the client does not invent line states. */
export function lineStatus(status: string): { status: ClinicalStatus; label: string } {
  switch (status) {
    case 'SUPPLIED':
      return { status: 'COMPLETED', label: 'Supplied' };
    case 'PARTIALLY_SUPPLIED':
      return { status: 'ACTION_REQUIRED', label: 'Partially supplied' };
    case 'CHECKED':
      return { status: 'SAFE', label: 'Final checked' };
    case 'PREPARED':
      return { status: 'INFORMATION', label: 'Prepared' };
    case 'AUTHORIZED':
      return { status: 'DISABLED', label: 'Not prepared' };
    case 'REVERSED':
      return { status: 'BLOCKING', label: 'Reversed' };
    default:
      // An unrecognised server state is reported as unknown rather than
      // optimistically rendered as fine.
      return { status: 'ACTION_REQUIRED', label: status.replace(/_/g, ' ') };
  }
}

export function PrescriptionWorkspace({
  lines,
  apiFetch,
  episodeId,
  onSelectLine,
  selectedLineId,
  onTransition,
}: {
  readonly lines: readonly DispensingLineDTO[];
  readonly apiFetch?: typeof fetch;
  readonly episodeId?: string;
  readonly onSelectLine?: (lineId: string) => void;
  readonly selectedLineId?: string;
  /** Called after a successful state transition (e.g. CHECKED). */
  readonly onTransition?: () => void;
}) {
  if (lines.length === 0) {
    return (
      <div style={{ padding: spacing.xl, color: text.secondary, fontSize: fontSize.body }}>
        No medicine lines on this episode.
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.xxl ?? spacing.xl }}>
      {lines.map((line) => (
        <LineSection
          key={line.id}
          line={line}
          selected={selectedLineId === line.id}
          apiFetch={apiFetch}
          episodeId={episodeId}
          onSelect={onSelectLine}
          onTransition={onTransition}
        />
      ))}
    </div>
  );
}

function LineSection({
  line,
  selected,
  apiFetch,
  episodeId,
  onSelect,
  onTransition,
}: {
  readonly line: DispensingLineDTO;
  readonly selected: boolean;
  readonly apiFetch?: typeof fetch;
  readonly episodeId?: string;
  readonly onSelect?: (lineId: string) => void;
  readonly onTransition?: () => void;
}) {
  const [busy, setBusy] = useState(false);

  const doVerify = apiFetch
    ? async (skuId: string, batchNumber: string): Promise<BatchVerificationResponse | null> => {
        const response = await apiFetch('/api/pos/dispensing/episodes/verify-batch/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ sku_id: skuId, batch_number: batchNumber }),
        });
        if (!response.ok) return null;
        return response.json() as Promise<BatchVerificationResponse>;
      }
    : undefined;

  const doComplete = apiFetch && episodeId
    ? async () => {
        setBusy(true);
        try {
          const resp = await apiFetch(
            `/api/pos/dispensing/episodes/${episodeId}/transition-state/`,
            {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
              body: JSON.stringify({ new_status: 'CHECKING' }),
            },
          );
          if (resp.ok) onTransition?.();
        } finally {
          setBusy(false);
        }
      }
    : undefined;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.md }}>
      <MedicineLine
        line={line}
        selected={selected}
        onSelect={onSelect}
      />
      {line.status === 'AUTHORIZED' && doVerify ? (
        <BatchVerification
          expectedSkuId={line.supplied_sku || line.prescribed_sku}
          busy={busy}
          onVerify={doVerify}
        />
      ) : null}
      {(line.status === 'PREPARED' || line.status === 'CHECKING') ? (
        <FinalCheckComparison
          lines={[line]}
          canComplete={!!doComplete && line.status === 'PREPARED'}
          blockedReason=''
          busy={busy}
          onComplete={doComplete}
        />
      ) : null}
    </div>
  );
}

function MedicineLine({
  line,
  selected,
  onSelect,
}: {
  readonly line: DispensingLineDTO;
  readonly selected: boolean;
  readonly onSelect?: (lineId: string) => void;
}) {
  const state = lineStatus(line.status);
  const palette = statusPalette[state.status];
  const outstanding = Number(line.quantity_authorized) - Number(line.quantity_supplied);
  const expired = isExpired(line.expiry_date_snapshot);

  return (
    <article
      onClick={onSelect ? () => onSelect(line.id) : undefined}
      style={{
        borderRadius: 12,
        border: `1px solid ${selected ? palette.accent : surface.border}`,
        borderLeft: `4px solid ${palette.accent}`,
        background: surface.raised,
        padding: spacing.lg,
        cursor: onSelect ? 'pointer' : 'default',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: spacing.md }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          {/* Primary: what is being dispensed. */}
          <h3
            style={{
              margin: 0,
              fontSize: fontSize.medicineName,
              fontWeight: 600,
              color: text.primary,
              lineHeight: 1.2,
            }}
          >
            {line.supplied_sku}
          </h3>

          {/* Prominent: how the patient takes it. Never demoted below price. */}
          <p
            style={{
              margin: `${spacing.sm}px 0 0`,
              fontSize: fontSize.instruction,
              lineHeight: 1.45,
              color: text.primary,
            }}
          >
            {line.dosage_label_instructions || 'No dosage instructions recorded'}
          </p>
        </div>

        <StatusBadge status={state.status} label={state.label} />
      </div>

      <dl
        style={{
          display: 'grid',
          gridTemplateColumns: autoColumns(140),
          gap: spacing.md,
          margin: `${spacing.lg}px 0 0`,
        }}
      >
        <Field label="Authorised" value={line.quantity_authorized} numeric />
        <Field label="Prepared" value={line.quantity_prepared} numeric />
        <Field label="Supplied" value={line.quantity_supplied} numeric />
        {outstanding > 0 ? (
          <Field label="Outstanding" value={String(outstanding)} numeric emphasis />
        ) : null}
        <Field label="Batch" value={line.batch_number_snapshot || '—'} numeric />
        <Field
          label="Expiry"
          value={line.expiry_date_snapshot ?? '—'}
          numeric
          {...(expired ? { danger: true } : {})}
        />
      </dl>

      {expired ? (
        <div style={{ marginTop: spacing.md }}>
          <StatusBadge status="BLOCKING" label="Batch expired — cannot be supplied" size="sm" />
        </div>
      ) : null}
    </article>
  );
}

function Field({
  label,
  value,
  numeric,
  emphasis,
  danger,
}: {
  readonly label: string;
  readonly value: string;
  readonly numeric?: boolean;
  readonly emphasis?: boolean;
  readonly danger?: boolean;
}) {
  return (
    <div>
      <dt style={{ fontSize: fontSize.meta, color: text.tertiary, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        {label}
      </dt>
      <dd
        style={{
          margin: '2px 0 0',
          fontSize: fontSize.body,
          fontWeight: emphasis || danger ? 700 : 500,
          color: danger ? statusPalette.BLOCKING.foreground : text.primary,
          // Tabular figures so quantities and dates line up down the column.
          fontFamily: numeric ? fontFamily.numeric : fontFamily.sans,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {value}
      </dd>
    </div>
  );
}

function isExpired(expiry: string | null): boolean {
  if (!expiry) return false;
  const date = new Date(expiry);
  if (Number.isNaN(date.getTime())) return false;
  return date.getTime() < Date.now();
}
