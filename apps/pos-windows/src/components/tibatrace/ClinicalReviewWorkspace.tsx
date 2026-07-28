import { fontSize, spacing, statusPalette, surface, text } from '@dawatrace/shared/design-system/index.js';
import type { ScreeningDecision, ScreeningOverride, ScreeningResult } from '@dawatrace/shared/clinical/index.js';
import { useMemo, useState } from 'react';

type ReviewDecision =
  | 'APPROVE'
  | 'APPROVE_WITH_CONDITIONS'
  | 'RETURN_FOR_CORRECTION'
  | 'REJECT'
  | 'CONTACT_PRESCRIBER'
  | 'REQUIRE_ALTERNATIVE'
  | 'REQUEST_MORE_INFORMATION';

const DECISIONS: readonly { value: ReviewDecision; label: string; consequence: string }[] = [
  { value: 'APPROVE', label: 'Approve', consequence: 'Releases only the screened clinical context.' },
  { value: 'APPROVE_WITH_CONDITIONS', label: 'Approve with conditions', consequence: 'Keeps supply blocked until the conditions are fulfilled and the basket is screened again.' },
  { value: 'RETURN_FOR_CORRECTION', label: 'Return for correction', consequence: 'Keeps supply blocked until the changed basket is screened again.' },
  { value: 'REJECT', label: 'Reject', consequence: 'Keeps supply blocked for this finding.' },
  { value: 'CONTACT_PRESCRIBER', label: 'Contact prescriber', consequence: 'Keeps supply blocked pending prescriber clarification.' },
  { value: 'REQUIRE_ALTERNATIVE', label: 'Require alternative', consequence: 'Keeps supply blocked until an alternative is selected and screened.' },
  { value: 'REQUEST_MORE_INFORMATION', label: 'Request more information', consequence: 'Keeps supply blocked until missing clinical information is recorded.' },
];

type OverrideAction = 'request' | 'start-review' | 'approve' | 'reject' | 'revoke';

export interface ClinicalOverrideActionInput {
  readonly action: OverrideAction;
  readonly overrideId?: string;
  readonly findingId: string;
  readonly overrideReason?: string;
  readonly requestedReason?: string;
  readonly supportingNotes?: string;
  readonly clinicalJustification?: string;
  readonly conditions?: string;
  readonly expiresAt?: string;
  readonly reason?: string;
}

export function ClinicalReviewWorkspace({
  result,
  findingId,
  patientName,
  prescriptionReference,
  busy,
  error,
  onBack,
  onRequestReview,
  onSubmit,
  onOverrideAction,
}: {
  readonly result: ScreeningResult;
  readonly findingId: string;
  readonly patientName: string;
  readonly prescriptionReference: string;
  readonly busy: boolean;
  readonly error: string;
  readonly onBack: () => void;
  readonly onRequestReview: () => void;
  readonly onSubmit: (input: {
    decision: ReviewDecision;
    clinicalJustification: string;
    conditions: string;
    followUpActions: string;
  }) => void;
  readonly onOverrideAction: (input: ClinicalOverrideActionInput) => void;
}) {
  const finding = result.findings.find((candidate) => candidate.id === findingId) ?? result.findings[0];
  const [decision, setDecision] = useState<ReviewDecision>('APPROVE');
  const [justification, setJustification] = useState('');
  const [conditions, setConditions] = useState('');
  const [followUpActions, setFollowUpActions] = useState('');
  const history = useMemo(
    () => result.decisions.filter((item) => item.findingId === finding?.id),
    [finding?.id, result.decisions],
  );

  if (!finding) {
    return <section style={workspace}><h2 style={heading}>Clinical review unavailable</h2></section>;
  }

  const selected = DECISIONS.find((option) => option.value === decision)!;
  const requiresConditions = decision === 'APPROVE_WITH_CONDITIONS';
  const ready = !busy && justification.trim().length > 0 && (!requiresConditions || conditions.trim().length > 0);
  const palette = statusPalette[finding.blocking ? 'BLOCKING' : 'PHARMACIST_REVIEW'];

  return (
    <section aria-label="Clinical review workspace" style={workspace}>
      <header style={header}>
        <div>
          <p style={eyebrow}>Clinical decision workspace</p>
          <h2 style={heading}>Pharmacist review</h2>
          <p style={subheading}>The server verifies authority, separation of duties, and the current basket before it records a decision.</p>
        </div>
        <button type="button" onClick={onBack} style={secondaryButton}>Back to dispensing</button>
      </header>

      <section style={patientCard}>
        <Meta label="Patient" value={patientName} />
        <Meta label="Prescription" value={prescriptionReference || 'Not recorded'} />
        <Meta label="Screening context" value={`${result.contextHash.slice(0, 16)}…`} />
        <Meta label="Ruleset" value={result.ruleSetVersion || 'Not recorded'} />
      </section>

      <article style={{ ...findingCard, borderColor: palette.border, borderLeftColor: palette.accent }}>
        <p style={eyebrow}>{finding.category.replace(/_/g, ' ').toLowerCase()}</p>
        <h3 style={sectionHeading}>{finding.title}</h3>
        <p style={body}>{finding.explanation}</p>
        {finding.recommendation ? <p style={{ ...body, fontWeight: 600 }}>{finding.recommendation}</p> : null}
        <p style={statusText}>Status: {(finding.resolutionStatus || 'OPEN').replace(/_/g, ' ')}</p>
      </article>

      <section style={formCard}>
        <div style={formHeader}>
          <div><p style={eyebrow}>Decision</p><h3 style={sectionHeading}>Record pharmacist decision</h3></div>
          <button type="button" disabled={busy} onClick={onRequestReview} style={secondaryButton}>Request review</button>
        </div>
        <div style={decisionGrid}>
          {DECISIONS.map((option) => (
            <label key={option.value} style={{ ...decisionOption, borderColor: decision === option.value ? '#075E37' : surface.border }}>
              <input type="radio" name="clinical-decision" checked={decision === option.value} onChange={() => setDecision(option.value)} />
              <span><strong>{option.label}</strong><small style={consequence}>{option.consequence}</small></span>
            </label>
          ))}
        </div>
        <p style={consequence}>{selected.consequence}</p>
        <label style={fieldLabel}>Clinical rationale (required)
          <textarea value={justification} onChange={(event) => setJustification(event.target.value)} rows={4} style={textarea} />
        </label>
        {requiresConditions ? <label style={fieldLabel}>Conditions of approval (required)
          <textarea value={conditions} onChange={(event) => setConditions(event.target.value)} rows={3} style={textarea} />
        </label> : null}
        <label style={fieldLabel}>Follow-up actions
          <textarea value={followUpActions} onChange={(event) => setFollowUpActions(event.target.value)} rows={3} style={textarea} />
        </label>
        {error ? <p role="alert" style={errorText}>{error}</p> : null}
        <button
          type="button"
          disabled={!ready}
          onClick={() => onSubmit({ decision, clinicalJustification: justification.trim(), conditions: conditions.trim(), followUpActions: followUpActions.trim() })}
          style={primaryButton(ready)}
        >
          {busy ? 'Recording clinical decision…' : 'Record clinical decision'}
        </button>
      </section>

      <DecisionHistory decisions={history} />
      <OverrideLifecycle
        finding={finding}
        overrides={result.overrides.filter((item) => item.findingId === finding.id)}
        busy={busy}
        onSubmit={onOverrideAction}
      />
    </section>
  );
}

function DecisionHistory({ decisions }: { readonly decisions: readonly ScreeningDecision[] }) {
  return (
    <section style={historyCard}>
      <p style={eyebrow}>Audit history</p>
      <h3 style={sectionHeading}>Prior clinical decisions</h3>
      {decisions.length === 0 ? <p style={body}>No prior decision has been recorded for this finding.</p> : decisions.map((item) => (
        <article key={item.id} style={historyItem}>
          <strong>{item.decision.replace(/_/g, ' ')}</strong>
          <span style={historyMeta}>{item.pharmacistName || 'Pharmacist'} · {item.createdAt || 'Recorded now'}</span>
          <p style={body}>{item.clinicalJustification}</p>
          {item.conditions ? <p style={body}>Conditions: {item.conditions}</p> : null}
          {item.followUpActions ? <p style={body}>Follow-up: {item.followUpActions}</p> : null}
        </article>
      ))}
    </section>
  );
}

function OverrideLifecycle({
  finding,
  overrides,
  busy,
  onSubmit,
}: {
  readonly finding: { readonly id: string; readonly overrideAllowed: boolean };
  readonly overrides: readonly ScreeningOverride[];
  readonly busy: boolean;
  readonly onSubmit: (input: ClinicalOverrideActionInput) => void;
}) {
  const [action, setAction] = useState<OverrideAction | null>(null);
  const [overrideReason, setOverrideReason] = useState('CLINICALLY_JUSTIFIED');
  const [requestedReason, setRequestedReason] = useState('');
  const [supportingNotes, setSupportingNotes] = useState('');
  const [clinicalJustification, setClinicalJustification] = useState('');
  const [conditions, setConditions] = useState('');
  const [expiresAt, setExpiresAt] = useState('');
  const [reason, setReason] = useState('');
  const current = overrides[0];
  const mayRequest = finding.overrideAllowed && (!current || ['REJECTED', 'REVOKED', 'EXPIRED'].includes(current.status));
  const actionLabel = action === 'request'
    ? 'Request override'
    : action === 'start-review'
      ? 'Start pharmacist review'
      : action === 'approve'
        ? 'Approve override'
        : action === 'reject'
          ? 'Reject override'
          : 'Revoke override';
  const modalReady = !busy && (
    action === 'start-review'
    || (action === 'request' && requestedReason.trim().length > 0)
    || (action === 'approve' && clinicalJustification.trim().length > 0)
    || ((action === 'reject' || action === 'revoke') && reason.trim().length > 0)
  );

  const submit = () => {
    if (!action || !modalReady) return;
    onSubmit({
      action,
      ...(current ? { overrideId: current.id } : {}),
      findingId: finding.id,
      overrideReason,
      requestedReason: requestedReason.trim(),
      supportingNotes: supportingNotes.trim(),
      clinicalJustification: clinicalJustification.trim(),
      conditions: conditions.trim(),
      ...(expiresAt ? { expiresAt: new Date(expiresAt).toISOString() } : {}),
      reason: reason.trim(),
    });
    setAction(null);
  };

  return (
    <section style={historyCard} aria-label="Governed clinical override lifecycle">
      <p style={eyebrow}>Controlled exception</p>
      <h3 style={sectionHeading}>Clinical override lifecycle</h3>
      <p style={body}>Overrides are time-bound, scoped to this screening, and require a separate authorised approval. They cannot be used to bypass an unresolved clinical finding.</p>
      {current ? <article style={historyItem}>
        <strong>{current.status.replace(/_/g, ' ')}</strong>
        <span style={historyMeta}>{current.overrideReason.replace(/_/g, ' ')} · {current.createdAt || 'Recorded now'}</span>
        <p style={body}>Request: {current.requestedReason || 'Not recorded'}</p>
        {current.clinicalJustification ? <p style={body}>Approval rationale: {current.clinicalJustification}</p> : null}
        {current.conditions ? <p style={body}>Conditions: {current.conditions}</p> : null}
        {current.expiresAt ? <p style={body}>Expires: {new Date(current.expiresAt).toLocaleString()}</p> : null}
        {current.rejectionReason ? <p style={body}>Rejection: {current.rejectionReason}</p> : null}
        {current.revocationReason ? <p style={body}>Revocation: {current.revocationReason}</p> : null}
        {current.consumedEvent ? <p style={body}>Consumed by: {current.consumedEvent}</p> : null}
      </article> : <p style={body}>No override has been requested for this finding.</p>}
      <div style={overrideActions}>
        {mayRequest ? <button type="button" disabled={busy} onClick={() => setAction('request')} style={secondaryButton}>Request override</button> : null}
        {current?.status === 'REQUESTED' ? <button type="button" disabled={busy} onClick={() => setAction('start-review')} style={secondaryButton}>Start review</button> : null}
        {['REQUESTED', 'UNDER_REVIEW'].includes(current?.status ?? '') ? <button type="button" disabled={busy} onClick={() => setAction('approve')} style={primaryButton(!busy)}>Approve override</button> : null}
        {['REQUESTED', 'UNDER_REVIEW'].includes(current?.status ?? '') ? <button type="button" disabled={busy} onClick={() => setAction('reject')} style={secondaryButton}>Reject override</button> : null}
        {['APPROVED', 'APPROVED_WITH_CONDITIONS'].includes(current?.status ?? '') ? <button type="button" disabled={busy} onClick={() => setAction('revoke')} style={secondaryButton}>Revoke override</button> : null}
      </div>
      {action ? <div role="dialog" aria-modal="true" aria-label={actionLabel} style={modalBackdrop}>
        <section style={modalCard}>
          <p style={eyebrow}>Controlled clinical action</p>
          <h3 style={sectionHeading}>{actionLabel}</h3>
          {action === 'request' ? <>
            <label style={fieldLabel}>Override reason
              <select value={overrideReason} onChange={(event) => setOverrideReason(event.target.value)} style={select}>
                <option value="CLINICALLY_JUSTIFIED">Clinically justified</option>
                <option value="PRESCRIBER_CONFIRMED">Prescriber confirmed</option>
                <option value="KNOWN_AND_MONITORED">Known and monitored</option>
                <option value="OTHER">Other</option>
              </select>
            </label>
            <label style={fieldLabel}>Request rationale (required)
              <textarea value={requestedReason} onChange={(event) => setRequestedReason(event.target.value)} rows={4} style={textarea} />
            </label>
            <label style={fieldLabel}>Supporting notes
              <textarea value={supportingNotes} onChange={(event) => setSupportingNotes(event.target.value)} rows={3} style={textarea} />
            </label>
          </> : null}
          {action === 'approve' ? <>
            <label style={fieldLabel}>Clinical approval rationale (required)
              <textarea value={clinicalJustification} onChange={(event) => setClinicalJustification(event.target.value)} rows={4} style={textarea} />
            </label>
            <label style={fieldLabel}>Conditions (optional; keeps supply blocked until rescreened)
              <textarea value={conditions} onChange={(event) => setConditions(event.target.value)} rows={3} style={textarea} />
            </label>
            <label style={fieldLabel}>Expiry (optional; defaults to the policy window)
              <input type="datetime-local" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} style={select} />
            </label>
          </> : null}
          {action === 'reject' || action === 'revoke' ? <label style={fieldLabel}>{action === 'reject' ? 'Rejection' : 'Revocation'} reason (required)
            <textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={3} style={textarea} />
          </label> : null}
          {action === 'start-review' ? <p style={body}>This records that an authorised pharmacist has opened the override request for review. It does not approve supply.</p> : null}
          <div style={modalActions}>
            <button type="button" onClick={() => setAction(null)} style={secondaryButton}>Cancel</button>
            <button type="button" disabled={!modalReady} onClick={submit} style={primaryButton(modalReady)}>{actionLabel}</button>
          </div>
        </section>
      </div> : null}
    </section>
  );
}

function Meta({ label, value }: { readonly label: string; readonly value: string }) {
  return <div><dt style={metaLabel}>{label}</dt><dd style={metaValue}>{value}</dd></div>;
}

const workspace: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: spacing.xl, maxWidth: 980, margin: '0 auto', paddingBottom: spacing.xxxl };
const header: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: spacing.lg };
const heading: React.CSSProperties = { margin: 0, fontSize: fontSize.screenTitle, color: text.primary };
const subheading: React.CSSProperties = { maxWidth: 680, margin: `${spacing.sm}px 0 0`, color: text.secondary, lineHeight: 1.5 };
const eyebrow: React.CSSProperties = { margin: 0, color: text.tertiary, fontSize: fontSize.caption, textTransform: 'uppercase', letterSpacing: 0.7 };
const patientCard: React.CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: spacing.lg, margin: 0, padding: spacing.lg, border: `1px solid ${surface.border}`, borderRadius: 12, background: surface.raised };
const metaLabel: React.CSSProperties = { margin: 0, color: text.tertiary, fontSize: fontSize.meta, textTransform: 'uppercase' };
const metaValue: React.CSSProperties = { margin: '4px 0 0', color: text.primary, fontSize: fontSize.body, overflowWrap: 'anywhere' };
const findingCard: React.CSSProperties = { padding: spacing.lg, border: `1px solid ${surface.border}`, borderLeftWidth: 5, borderRadius: 12, background: surface.raised };
const body: React.CSSProperties = { margin: `${spacing.sm}px 0 0`, color: text.secondary, fontSize: fontSize.body, lineHeight: 1.5 };
const statusText: React.CSSProperties = { margin: `${spacing.md}px 0 0`, color: text.tertiary, fontSize: fontSize.caption, fontWeight: 600, textTransform: 'uppercase' };
const formCard: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: spacing.lg, padding: spacing.xl, border: `1px solid ${surface.border}`, borderRadius: 12, background: surface.raised };
const formHeader: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: spacing.md };
const sectionHeading: React.CSSProperties = { margin: '4px 0 0', color: text.primary, fontSize: fontSize.sectionTitle };
const decisionGrid: React.CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: spacing.sm };
const decisionOption: React.CSSProperties = { display: 'flex', gap: spacing.sm, alignItems: 'flex-start', padding: spacing.md, border: '1px solid', borderRadius: 10, cursor: 'pointer', color: text.primary };
const consequence: React.CSSProperties = { display: 'block', margin: 0, color: text.secondary, fontSize: fontSize.caption, lineHeight: 1.35 };
const fieldLabel: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: spacing.xs, color: text.secondary, fontSize: fontSize.caption, fontWeight: 600 };
const textarea: React.CSSProperties = { minHeight: 84, resize: 'vertical', padding: spacing.md, border: `1px solid ${surface.borderStrong}`, borderRadius: 8, color: text.primary, fontFamily: 'inherit', fontSize: fontSize.body };
const secondaryButton: React.CSSProperties = { minHeight: 42, padding: '8px 12px', borderRadius: 8, border: `1px solid ${surface.borderStrong}`, background: surface.raised, color: text.primary, fontWeight: 600, cursor: 'pointer', whiteSpace: 'nowrap' };
const primaryButton = (ready: boolean): React.CSSProperties => ({ minHeight: 48, alignSelf: 'flex-start', padding: '12px 18px', border: 'none', borderRadius: 8, background: ready ? '#075E37' : surface.sunken, color: ready ? text.inverse : text.tertiary, fontWeight: 700, cursor: ready ? 'pointer' : 'not-allowed' });
const errorText: React.CSSProperties = { margin: 0, padding: spacing.md, borderRadius: 8, color: statusPalette.BLOCKING.foreground, background: statusPalette.BLOCKING.surface };
const historyCard: React.CSSProperties = { padding: spacing.lg, border: `1px solid ${surface.border}`, borderRadius: 12, background: surface.raised };
const historyItem: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: spacing.xs, padding: `${spacing.md}px 0`, borderTop: `1px solid ${surface.border}` };
const historyMeta: React.CSSProperties = { color: text.tertiary, fontSize: fontSize.caption };
const overrideActions: React.CSSProperties = { display: 'flex', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.md };
const modalBackdrop: React.CSSProperties = { position: 'fixed', inset: 0, zIndex: 20, display: 'grid', placeItems: 'center', padding: spacing.lg, background: 'rgba(10, 24, 43, 0.52)' };
const modalCard: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: spacing.md, width: 'min(560px, 100%)', maxHeight: 'calc(100vh - 48px)', overflowY: 'auto', padding: spacing.xl, borderRadius: 12, background: surface.raised, boxShadow: '0 20px 55px rgba(10, 24, 43, 0.28)' };
const modalActions: React.CSSProperties = { display: 'flex', justifyContent: 'flex-end', gap: spacing.sm };
const select: React.CSSProperties = { minHeight: 42, padding: `0 ${spacing.sm}px`, border: `1px solid ${surface.borderStrong}`, borderRadius: 8, background: surface.raised, color: text.primary, fontFamily: 'inherit', fontSize: fontSize.body };
