import { fontSize, spacing, statusPalette, surface, text } from '@dawatrace/shared/design-system/index.js';
import { useState } from 'react';

import { BlockingReason, StatusBadge } from './StatusBadge.js';

/**
 * Pharmacist review and clinical override.
 *
 * Both are exceptional acts and are presented as such. The language is
 * deliberate: "Request clinical override", never "Continue anyway". An operator
 * should feel that they are recording a clinical decision, because that is what
 * the audit trail will say they did.
 *
 * Neither panel decides anything. The server validates capability, separation
 * of duties and context freshness, and returns the updated screening state.
 * Hiding a control here is a courtesy to the operator, not a security measure.
 */

export type ReviewDecision =
  | 'APPROVE_AS_WRITTEN'
  | 'REJECT_SUPPLY'
  | 'REQUEST_CLARIFICATION'
  | 'APPROVE_WITH_COUNSELLING';

const DECISIONS: readonly { value: ReviewDecision; label: string; consequence: string }[] = [
  {
    value: 'APPROVE_AS_WRITTEN',
    label: 'Approve as written',
    consequence:
      'Authorises progression for the current clinical context only. Any prescription or basket change invalidates this decision.',
  },
  {
    value: 'APPROVE_WITH_COUNSELLING',
    label: 'Approve with counselling',
    consequence:
      'Authorises progression on condition that the recorded counselling is delivered before supply.',
  },
  {
    value: 'REQUEST_CLARIFICATION',
    label: 'Request clarification',
    consequence: 'Holds the episode pending prescriber clarification. Supply remains blocked.',
  },
  {
    value: 'REJECT_SUPPLY',
    label: 'Reject supply',
    consequence: 'Refuses supply for this finding. The episode cannot progress.',
  },
];

export function PharmacistReviewPanel({
  findingTitle,
  contextHash,
  screenedAt,
  busy,
  onSubmit,
}: {
  readonly findingTitle: string;
  readonly contextHash: string;
  readonly screenedAt: string;
  readonly busy: boolean;
  readonly onSubmit: (decision: ReviewDecision, justification: string) => void;
}) {
  const [decision, setDecision] = useState<ReviewDecision>('APPROVE_AS_WRITTEN');
  const [justification, setJustification] = useState('');
  const [submitted, setSubmitted] = useState(false);

  const selected = DECISIONS.find((option) => option.value === decision);
  // A rejection or a clarification request is a clinical position that has to be
  // explainable later, so it carries the same evidence bar as an approval.
  const justificationRequired = decision !== 'APPROVE_AS_WRITTEN';
  const ready = !busy && !submitted && (!justificationRequired || justification.trim().length > 0);

  return (
    <section style={panel}>
      <header style={{ display: 'flex', alignItems: 'center', gap: spacing.md }}>
        <h2 style={{ margin: 0, fontSize: fontSize.sectionTitle }}>Pharmacist review</h2>
        <StatusBadge status="PHARMACIST_REVIEW" />
      </header>

      <p style={{ margin: 0, fontSize: fontSize.bodyLarge, fontWeight: 600 }}>{findingTitle}</p>

      <dl style={metaGrid}>
        <Meta label="Screened" value={screenedAt || '—'} />
        <Meta label="Context" value={contextHash ? `${contextHash.slice(0, 12)}…` : '—'} />
      </dl>

      <fieldset style={{ border: 'none', margin: 0, padding: 0, display: 'grid', gap: spacing.sm }}>
        <legend style={legend}>Decision</legend>
        {DECISIONS.map((option) => (
          <label key={option.value} style={radioRow}>
            <input
              type="radio"
              name="pharmacist-decision"
              checked={decision === option.value}
              onChange={() => setDecision(option.value)}
              style={{ width: 18, height: 18 }}
            />
            <span style={{ fontWeight: 600 }}>{option.label}</span>
          </label>
        ))}
      </fieldset>

      {/* The consequence is stated before submission, not after. */}
      {selected ? (
        <BlockingReason status="INFORMATION" reason={selected.consequence} />
      ) : null}

      <label style={fieldLabel}>
        Clinical justification{justificationRequired ? ' (required)' : ' (optional)'}
        <textarea
          value={justification}
          onChange={(event) => setJustification(event.target.value)}
          rows={3}
          style={textarea}
        />
      </label>

      <div>
        <button
          type="button"
          disabled={!ready}
          onClick={() => {
            // Latches: a clinical decision must not be submitted twice.
            setSubmitted(true);
            onSubmit(decision, justification.trim());
          }}
          style={primaryButton(ready)}
        >
          {busy ? 'Submitting decision…' : 'Submit decision'}
        </button>
      </div>
    </section>
  );
}

export function OverrideRequestPanel({
  findingTitle,
  overrideAllowed,
  busy,
  onRequest,
}: {
  readonly findingTitle: string;
  readonly overrideAllowed: boolean;
  readonly busy: boolean;
  readonly onRequest: (justification: string) => void;
}) {
  const [justification, setJustification] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const ready = overrideAllowed && !busy && !submitted && justification.trim().length > 0;

  return (
    <section style={{ ...panel, borderColor: statusPalette.PHARMACIST_REVIEW.border }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: spacing.md }}>
        <h2 style={{ margin: 0, fontSize: fontSize.sectionTitle }}>Request clinical override</h2>
        <StatusBadge status="PHARMACIST_REVIEW" label="Exceptional action" />
      </header>

      <p style={{ margin: 0, fontSize: fontSize.bodyLarge, fontWeight: 600 }}>{findingTitle}</p>

      {!overrideAllowed ? (
        <BlockingReason
          status="BLOCKING"
          reason="This finding cannot be overridden. A pharmacist decision or a change to the prescription is required."
        />
      ) : (
        <BlockingReason
          status="ACTION_REQUIRED"
          reason="An override applies only to the current clinical context. Any prescription or basket change invalidates it, and the request is recorded against your name."
        />
      )}

      <label style={fieldLabel}>
        Clinical justification (required)
        <textarea
          value={justification}
          onChange={(event) => setJustification(event.target.value)}
          rows={3}
          style={textarea}
        />
      </label>

      <div>
        <button
          type="button"
          disabled={!ready}
          onClick={() => {
            setSubmitted(true);
            onRequest(justification.trim());
          }}
          style={primaryButton(ready)}
        >
          {busy ? 'Submitting request…' : 'Request clinical override'}
        </button>
      </div>
    </section>
  );
}

const panel: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: spacing.md,
  padding: spacing.lg,
  borderRadius: 12,
  border: `1px solid ${surface.border}`,
  background: surface.raised,
};

const metaGrid: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
  gap: spacing.md,
  margin: 0,
};

const legend: React.CSSProperties = {
  fontSize: fontSize.caption,
  color: text.tertiary,
  textTransform: 'uppercase',
  letterSpacing: 0.6,
};

const radioRow: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: spacing.sm,
  fontSize: fontSize.body,
  minHeight: 36,
  cursor: 'pointer',
};

const fieldLabel: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
  fontSize: fontSize.caption,
  color: text.secondary,
};

const textarea: React.CSSProperties = {
  padding: '10px 12px',
  borderRadius: 8,
  border: `1px solid ${surface.borderStrong}`,
  fontSize: fontSize.body,
  resize: 'vertical',
};

function primaryButton(ready: boolean): React.CSSProperties {
  return {
    padding: '12px 20px',
    borderRadius: 8,
    minHeight: 48,
    border: 'none',
    background: ready ? '#C25708' : surface.sunken,
    color: ready ? '#fff' : text.tertiary,
    fontSize: fontSize.bodyLarge,
    fontWeight: 600,
    cursor: ready ? 'pointer' : 'not-allowed',
  };
}

function Meta({ label, value }: { readonly label: string; readonly value: string }) {
  return (
    <div>
      <dt style={{ fontSize: fontSize.meta, color: text.tertiary, textTransform: 'uppercase' }}>
        {label}
      </dt>
      <dd style={{ margin: '2px 0 0', fontSize: fontSize.body, fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </dd>
    </div>
  );
}

export { DECISIONS };
