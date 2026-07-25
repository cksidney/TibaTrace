import { fontFamily, fontSize, spacing, surface, text } from '@dawatrace/shared/design-system/index.js';
import type { ClinicalStatus } from '@dawatrace/shared/design-system/index.js';
import type { BatchVerificationResponse } from '@dawatrace/shared/dispensing/index.js';
import { useRef, useState } from 'react';

import { BlockingReason, StatusBadge } from './StatusBadge.js';

/**
 * Batch verification at preparation.
 *
 * The scan result is whatever the server said. The client does not decide
 * whether a batch is dispensable -- it renders the server's verdict and the
 * exact reason, so an operator holding a pack knows why it was refused rather
 * than seeing a generic failure.
 */

/**
 * Classify a verification result for display.
 *
 * A refusal is never softened: an expired, recalled or quarantined batch is
 * BLOCKING, not a warning to be clicked past.
 */
export function verificationStatus(result: BatchVerificationResponse | null): {
  status: ClinicalStatus;
  label: string;
} {
  if (!result) return { status: 'DISABLED', label: 'Not scanned' };
  if (result.valid) return { status: 'SAFE', label: 'Verified' };
  if (result.is_recalled) return { status: 'BLOCKING', label: 'Recalled batch' };
  if (result.is_expired) return { status: 'BLOCKING', label: 'Expired batch' };
  if (!result.batch_found) return { status: 'BLOCKING', label: 'Batch not found' };
  if (!result.sku_match) return { status: 'BLOCKING', label: 'Wrong product' };
  if (result.release_status !== 'RELEASED') {
    return { status: 'BLOCKING', label: `Not released (${result.release_status})` };
  }
  return { status: 'BLOCKING', label: 'Cannot be supplied' };
}

export function BatchVerification({
  expectedSkuId,
  busy,
  onVerify,
}: {
  readonly expectedSkuId: string;
  readonly busy: boolean;
  readonly onVerify: (skuId: string, batchNumber: string) => Promise<BatchVerificationResponse | null>;
}) {
  const [batchNumber, setBatchNumber] = useState('');
  const [result, setResult] = useState<BatchVerificationResponse | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const state = verificationStatus(result);

  async function submit() {
    if (!batchNumber.trim()) return;
    const verdict = await onVerify(expectedSkuId, batchNumber.trim());
    setResult(verdict);
    // Return focus to the field so the next pack can be scanned without the
    // operator reaching for the mouse.
    inputRef.current?.select();
  }

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: spacing.md }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: spacing.md }}>
        <h2 style={{ margin: 0, fontSize: fontSize.sectionTitle }}>Batch verification</h2>
        <StatusBadge status={state.status} label={state.label} />
      </header>

      <label
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 4,
          fontSize: fontSize.caption,
          color: text.secondary,
        }}
      >
        Scan or type batch number
        <input
          ref={inputRef}
          value={batchNumber}
          autoFocus
          onChange={(event) => setBatchNumber(event.target.value)}
          // Barcode scanners emit a terminating Enter; the field must accept a
          // scan without the operator touching anything else.
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              void submit();
            }
          }}
          style={{
            padding: '12px 14px',
            borderRadius: 8,
            border: `1px solid ${surface.borderStrong}`,
            fontSize: fontSize.bodyLarge,
            fontFamily: fontFamily.numeric,
            minHeight: 48,
            maxWidth: 420,
          }}
        />
      </label>

      <div>
        <button
          type="button"
          disabled={busy || !batchNumber.trim()}
          onClick={() => void submit()}
          style={{
            padding: '10px 16px',
            borderRadius: 8,
            minHeight: 44,
            border: `1px solid ${surface.borderStrong}`,
            background: surface.raised,
            fontSize: fontSize.body,
            fontWeight: 600,
            cursor: busy || !batchNumber.trim() ? 'not-allowed' : 'pointer',
          }}
        >
          {busy ? 'Verifying…' : 'Verify batch'}
        </button>
      </div>

      {result ? (
        <>
          {/* The server's reason, verbatim. "There is an issue" helps nobody
              holding a pack at the counter. */}
          <BlockingReason status={state.status} reason={result.reason} />

          <dl
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
              gap: spacing.md,
              margin: 0,
            }}
          >
            <Detail label="Product match" value={result.sku_match ? 'Yes' : 'No'} />
            <Detail label="Batch found" value={result.batch_found ? 'Yes' : 'No'} />
            <Detail label="Release status" value={result.release_status} />
            <Detail label="Available" value={String(result.quantity_available)} numeric />
          </dl>
        </>
      ) : null}
    </section>
  );
}

function Detail({
  label,
  value,
  numeric,
}: {
  readonly label: string;
  readonly value: string;
  readonly numeric?: boolean;
}) {
  return (
    <div>
      <dt
        style={{
          fontSize: fontSize.meta,
          color: text.tertiary,
          textTransform: 'uppercase',
          letterSpacing: 0.5,
        }}
      >
        {label}
      </dt>
      <dd
        style={{
          margin: '2px 0 0',
          fontSize: fontSize.body,
          fontWeight: 500,
          color: text.primary,
          fontFamily: numeric ? fontFamily.numeric : fontFamily.sans,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {value}
      </dd>
    </div>
  );
}
