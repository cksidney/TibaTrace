import { fontFamily, fontSize, spacing, statusPalette, surface, text } from '@dawatrace/shared/design-system/index.js';
import type { PaymentMode, PaymentState, PaymentTenderType } from '@dawatrace/shared/dispensing/index.js';
import { TENDER_OPTIONS, paymentPermitsSupply } from '@dawatrace/shared/dispensing/index.js';
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

/**
 * Parse a server-supplied money string.
 *
 * The server sends unformatted decimal strings ("1250.00"). Anything else --
 * a grouped or localised value, an empty string, a null that slipped through
 * -- is treated as unknown rather than coerced.
 *
 * `parseFloat` is deliberately not used. It reads "1,250,000.00" as 1250,
 * which would under-report a balance by three orders of magnitude while
 * looking entirely plausible on screen. A refusal to parse is recoverable; a
 * confidently wrong figure at a till is not.
 */
function parseMoney(raw: string | null): number | null {
  if (raw === null) return null;
  const trimmed = raw.trim();
  if (!/^-?\d+(\.\d+)?$/.test(trimmed)) return null;
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

/**
 * The balance still owed, or null when it cannot be established.
 *
 * Never falls back to zero for an unparseable amount. Zero is a specific
 * claim -- "nothing is owed" -- and asserting it from a parse failure is how a
 * basket gets released without payment.
 */
export function remainingAmount(due: string | null, settled: string | null): number | null {
  const dueValue = parseMoney(due);
  const settledValue = parseMoney(settled);
  if (dueValue === null || settledValue === null) return null;
  return dueValue - settledValue;
}

export interface PaymentActionState {
  readonly enabled: boolean;
  /** Empty when enabled. Why the operator cannot collect, in their words. */
  readonly reason: string;
}

/**
 * Whether the collect action may be offered, and why not.
 *
 * One derived value drives `disabled`, the fill and the cursor. They were
 * three separate expressions, and they disagreed: the fill ignored `priced`
 * and the selected tender, so the button could render green and inviting while
 * being inert. An operator who clicks a live-looking button that does nothing
 * concludes the terminal is broken, and looks for another way to release the
 * medicine.
 *
 * This decides only whether to *offer* the action. The server remains the sole
 * authority on whether a payment succeeds.
 */
export function paymentActionState(input: {
  readonly priced: boolean;
  readonly remaining: number | null;
  readonly keyedAmount: string;
  readonly canTakePayment: boolean;
  readonly tenderAvailable: boolean;
  readonly busy: boolean;
  readonly submitted: boolean;
}): PaymentActionState {
  if (!input.priced)
    return {
      enabled: false,
      reason: 'No payment intent is open for this episode, so there is no amount to collect.',
    };
  if (input.remaining === null)
    return {
      enabled: false,
      // The panel must not invite a hand-keyed amount to paper over an amount
      // it could not read.
      reason: 'The amount on this payment intent could not be read, so payment cannot be collected.',
    };
  if (parseMoney(input.keyedAmount) === null)
    return { enabled: false, reason: 'Enter an amount as a plain number, for example 1250.00.' };
  if (!input.tenderAvailable)
    return { enabled: false, reason: 'The selected tender has no settlement path.' };
  if (!input.canTakePayment)
    return { enabled: false, reason: 'Payment is not permitted in the current state.' };
  if (input.busy || input.submitted)
    return { enabled: false, reason: 'A payment is already in flight.' };
  return { enabled: true, reason: '' };
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
  /** Null when no payment intent is open; the panel says so rather than guessing. */
  readonly amountDue: string | null;
  readonly amountSettled: string | null;
  readonly canTakePayment: boolean;
  readonly blockedReason: string;
  readonly busy: boolean;
  readonly onTakePayment: (tender: PaymentTenderType, amount: string, reference: string) => void;
}) {
  const [tender, setTender] = useState<PaymentMode>('CASH');
  const [amount, setAmount] = useState(amountDue ?? '');
  const [reference, setReference] = useState('');
  const [submitted, setSubmitted] = useState(false);

  const meta = paymentStatusMeta(paymentState);
  const selected = TENDER_OPTIONS.find((option) => option.type === tender);
  const priced = amountDue !== null && amountSettled !== null;
  const remaining = remainingAmount(amountDue, amountSettled);
  const action = paymentActionState({
    priced,
    remaining,
    keyedAmount: amount,
    canTakePayment,
    tenderAvailable: selected?.available ?? false,
    busy,
    submitted,
  });

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: spacing.lg }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: spacing.md }}>
        <h2 style={{ margin: 0, fontSize: fontSize.sectionTitle }}>Payment</h2>
        <StatusBadge status={meta.status} label={meta.label} />
      </header>

      <dl style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: spacing.lg, margin: 0 }}>
        <Amount label="Amount due" value={amountDue ?? 'Not priced'} />
        <Amount label="Settled" value={amountSettled ?? '—'} />
        <Amount
          label="Remaining"
          value={remaining === null ? '—' : remaining.toFixed(2)}
          emphasis={remaining !== null && remaining > 0}
        />
      </dl>

      {blockedReason ? <BlockingReason status="BLOCKING" reason={blockedReason} /> : null}

      {!priced ? (
        <BlockingReason
          status="DISABLED"
          reason="No payment intent is open for this episode, so there is no authoritative amount to collect."
        />
      ) : null}

      {/* An intent exists but its amounts did not parse. Distinct from "not
          priced", and stated as such: telling the operator there is no intent
          when there is one sends them to create a second one. */}
      {priced && remaining === null ? (
        <BlockingReason
          status="ACTION_REQUIRED"
          reason="The amount on this payment intent could not be read. Refresh the episode before collecting; do not key an amount by hand."
        />
      ) : null}

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
        // A single derived gate gives `disabled`, the fill and the cursor the
        // same answer, so the control can never look available while inert.
        disabled={!action.enabled}
        title={action.reason}
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
          background: action.enabled ? '#12854A' : surface.sunken,
          color: action.enabled ? '#fff' : text.tertiary,
          fontSize: fontSize.bodyLarge,
          fontWeight: 600,
          cursor: action.enabled ? 'pointer' : 'not-allowed',
        }}
      >
        {busy ? 'Confirming payment…' : 'Take payment'}
      </button>

      {/* A disabled control with no stated reason reads as a broken screen, and
          operators route around broken screens. */}
      {!action.enabled && action.reason ? (
        <p style={{ margin: 0, fontSize: fontSize.caption, color: text.tertiary }}>{action.reason}</p>
      ) : null}

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
