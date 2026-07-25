import { fontFamily, fontSize, spacing, statusPalette, surface, text } from '@dawatrace/shared/design-system/index.js';
import type { PaymentMode, PaymentState, PaymentTenderType } from '@dawatrace/shared/dispensing/index.js';
import { paymentPermitsSupply } from '@dawatrace/shared/dispensing/index.js';
import { useState } from 'react';

import { BlockingReason, StatusBadge } from './StatusBadge.js';

/**
 * Payment.
 *
 * Tender availability is declared, not guessed. A tender whose settlement path
 * does not exist on the server is rendered disabled with the reason stated --
 * showing it as active would let an operator start a payment the system cannot
 * finish, which is worse than not offering it.
 */

interface TenderOption {
  readonly type: PaymentMode;
  readonly label: string;
  readonly available: boolean;
  /** Why this tender cannot be used. Shown to the operator verbatim. */
  readonly blocker?: string;
}

/**
 * Cash and card settle through the ledger today. M-PESA has no provider adapter
 * and split tender has no orchestration, so both are disabled rather than
 * presented as working.
 */
export const TENDER_OPTIONS: readonly TenderOption[] = [
  { type: 'CASH', label: 'Cash', available: true },
  { type: 'CARD', label: 'Card (manual approval)', available: true },
  {
    type: 'MPESA',
    label: 'M-PESA',
    available: false,
    blocker: 'M-PESA settlement is not yet available on this deployment.',
  },
  {
    type: 'SPLIT',
    label: 'Split tender',
    available: false,
    blocker: 'Split-tender allocation is not yet available on this deployment.',
  },
];

export function paymentStatusMeta(state: PaymentState) {
  switch (state) {
    case 'PAID':
      return { status: 'COMPLETED' as const, label: 'Paid' };
    case 'NOT_REQUIRED':
      return { status: 'INFORMATION' as const, label: 'No payment required' };
    case 'WAIVED':
      return { status: 'INFORMATION' as const, label: 'Waived' };
    case 'PARTIALLY_PAID':
      return { status: 'ACTION_REQUIRED' as const, label: 'Partially paid' };
    case 'AUTHORIZED':
      return { status: 'INFORMATION' as const, label: 'Authorised' };
    case 'FAILED':
      return { status: 'BLOCKING' as const, label: 'Failed' };
    case 'CANCELLED':
      return { status: 'BLOCKING' as const, label: 'Cancelled' };
    case 'REVERSAL_PENDING':
      return { status: 'STALE' as const, label: 'Reversal pending' };
    case 'REVERSED':
      return { status: 'BLOCKING' as const, label: 'Reversed' };
    case 'REFUNDED':
      return { status: 'INFORMATION' as const, label: 'Refunded' };
    default:
      return { status: 'ACTION_REQUIRED' as const, label: 'Pending' };
  }
}

export function PaymentPanel({
  paymentState,
  amountDue,
  amountSettled,
  canTakePayment,
  blockedReason,
  busy,
  onTakePayment,
}: {
  readonly paymentState: PaymentState;
  readonly amountDue: string;
  readonly amountSettled: string;
  readonly canTakePayment: boolean;
  readonly blockedReason: string;
  readonly busy: boolean;
  readonly onTakePayment: (tender: PaymentTenderType, amount: string, reference: string) => void;
}) {
  const [tender, setTender] = useState<PaymentMode>('CASH');
  const [amount, setAmount] = useState(amountDue);
  const [reference, setReference] = useState('');
  const [submitted, setSubmitted] = useState(false);

  const meta = paymentStatusMeta(paymentState);
  const selected = TENDER_OPTIONS.find((option) => option.type === tender);
  const remaining = Number(amountDue) - Number(amountSettled);

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: spacing.lg }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: spacing.md }}>
        <h2 style={{ margin: 0, fontSize: fontSize.sectionTitle }}>Payment</h2>
        <StatusBadge status={meta.status} label={meta.label} />
      </header>

      <dl style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: spacing.lg, margin: 0 }}>
        <Amount label="Amount due" value={amountDue} />
        <Amount label="Settled" value={amountSettled} />
        <Amount label="Remaining" value={remaining.toFixed(2)} emphasis={remaining > 0} />
      </dl>

      {blockedReason ? <BlockingReason status="BLOCKING" reason={blockedReason} /> : null}

      {/* Part-payment is called out explicitly: it is the state most likely to
          be mistaken for "paid enough to hand over the medicine". */}
      {paymentState === 'PARTIALLY_PAID' ? (
        <BlockingReason
          status="ACTION_REQUIRED"
          reason="Partially paid. The balance must be settled before medicine can be supplied."
        />
      ) : null}

      <fieldset style={{ border: 'none', margin: 0, padding: 0 }}>
        <legend style={{ fontSize: fontSize.caption, color: text.tertiary, textTransform: 'uppercase', letterSpacing: 0.6 }}>
          Tender
        </legend>
        <div style={{ display: 'flex', gap: spacing.sm, flexWrap: 'wrap', marginTop: spacing.sm }}>
          {TENDER_OPTIONS.map((option) => (
            <button
              key={option.type}
              type="button"
              disabled={!option.available}
              aria-pressed={tender === option.type}
              title={option.blocker}
              onClick={() => setTender(option.type)}
              style={{
                padding: '10px 14px',
                borderRadius: 8,
                minHeight: 44,
                cursor: option.available ? 'pointer' : 'not-allowed',
                border: `1px solid ${tender === option.type ? statusPalette.INFORMATION.accent : surface.borderStrong}`,
                background: !option.available
                  ? surface.sunken
                  : tender === option.type
                    ? statusPalette.INFORMATION.surface
                    : surface.raised,
                color: option.available ? text.primary : text.tertiary,
                fontSize: fontSize.body,
                fontWeight: 600,
              }}
            >
              {option.label}
            </button>
          ))}
        </div>
        {selected && !selected.available && selected.blocker ? (
          <p style={{ margin: `${spacing.sm}px 0 0`, fontSize: fontSize.caption, color: text.secondary }}>
            {selected.blocker}
          </p>
        ) : null}
      </fieldset>

      <div style={{ display: 'flex', gap: spacing.md, flexWrap: 'wrap' }}>
        <Input label="Amount" value={amount} onChange={setAmount} numeric />
        <Input
          label={tender === 'CARD' ? 'Approval reference' : 'Reference (optional)'}
          value={reference}
          onChange={setReference}
        />
      </div>

      <button
        type="button"
        disabled={!canTakePayment || busy || submitted || !(selected?.available ?? false)}
        onClick={() => {
          // Guards a double-submit: a second click must not become a second
          // charge while the first is still in flight.
          setSubmitted(true);
          // SPLIT is a UI mode, never a tender the server accepts, so it can
          // only reach here as a real tender type.
          onTakePayment(tender as PaymentTenderType, amount, reference);
        }}
        style={{
          alignSelf: 'flex-start',
          padding: '12px 20px',
          borderRadius: 8,
          border: 'none',
          minHeight: 48,
          background: canTakePayment && !busy && !submitted ? '#12854A' : surface.sunken,
          color: canTakePayment && !busy && !submitted ? '#fff' : text.tertiary,
          fontSize: fontSize.bodyLarge,
          fontWeight: 600,
          cursor: canTakePayment && !busy && !submitted ? 'pointer' : 'not-allowed',
        }}
      >
        {busy ? 'Confirming payment…' : 'Take payment'}
      </button>

      {paymentPermitsSupply(paymentState) ? (
        <p style={{ margin: 0, fontSize: fontSize.caption, color: text.secondary }}>
          Payment permits commercial completion. Medicine is supplied only when collection is
          confirmed.
        </p>
      ) : null}
    </section>
  );
}

function Amount({ label, value, emphasis }: { label: string; value: string; emphasis?: boolean }) {
  return (
    <div>
      <dt style={{ fontSize: fontSize.meta, color: text.tertiary, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        {label}
      </dt>
      <dd
        style={{
          margin: '2px 0 0',
          fontSize: fontSize.medicineName,
          fontWeight: emphasis ? 700 : 600,
          fontFamily: fontFamily.numeric,
          fontVariantNumeric: 'tabular-nums',
          color: emphasis ? statusPalette.ACTION_REQUIRED.foreground : text.primary,
        }}
      >
        {value}
      </dd>
    </div>
  );
}

function Input({
  label,
  value,
  onChange,
  numeric,
}: {
  readonly label: string;
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly numeric?: boolean;
}) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: fontSize.caption, color: text.secondary }}>
      {label}
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        inputMode={numeric ? 'decimal' : 'text'}
        style={{
          padding: '10px 12px',
          borderRadius: 8,
          border: `1px solid ${surface.borderStrong}`,
          fontSize: fontSize.body,
          minHeight: 44,
          minWidth: 200,
          fontFamily: numeric ? fontFamily.numeric : fontFamily.sans,
          fontVariantNumeric: 'tabular-nums',
        }}
      />
    </label>
  );
}
