import {
  CLINICAL_STATUS,
  CONNECTIVITY,
  fontSize,
  spacing,
  statusPalette,
  surface,
  text,
} from '@dawatrace/shared/design-system/index.js';
import type {
  ClinicalStatus,
  ConnectivityState,
} from '@dawatrace/shared/design-system/index.js';

import { BlockingReason, StatusBadge } from './StatusBadge.js';

export interface ClinicalFinding {
  readonly id: string;
  readonly severity: ClinicalStatus;
  readonly category: string;
  readonly title: string;
  readonly explanation: string;
  readonly recommendation: string;
  readonly blocking: boolean;
  readonly overrideAllowed: boolean;
  readonly requiresPharmacist: boolean;
}

export interface ClinicalSummary {
  /** Server-supplied. The client never computes this. */
  readonly safeToProceed: boolean;
  readonly screened: boolean;
  readonly stale: boolean;
  readonly blockingCount: number;
  readonly findings: readonly ClinicalFinding[];
  readonly connectivity: ConnectivityState;
  readonly evaluatedAt?: string;
}

/**
 * The clinical operations rail.
 *
 * Stays visible through dispensing and payment rather than hiding behind a
 * modal, so the operator can always see what is blocking them and what the next
 * lawful action is.
 *
 * The headline state is derived strictly from the server's `safe_to_proceed`.
 * The client never infers safety from the absence of findings it happens to
 * have loaded -- a screening it could not fetch is not a screening that passed.
 */
export function ClinicalRail({
  summary,
  onAcknowledge,
  onRequestPharmacist,
  onRequestOverride,
  capabilities,
}: {
  readonly summary: ClinicalSummary | null;
  readonly onAcknowledge?: (findingId: string) => void;
  readonly onRequestPharmacist?: () => void;
  readonly onRequestOverride?: (findingId: string) => void;
  /** Used only to hide controls the user cannot use. The server still decides. */
  readonly capabilities?: ReadonlySet<string>;
}) {
  const headline = deriveHeadline(summary);
  const palette = statusPalette[headline.status];

  return (
    <aside
      aria-label="Clinical status"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: spacing.lg,
        padding: spacing.lg,
        background: surface.raised,
        borderLeft: `1px solid ${surface.border}`,
        overflowY: 'auto',
        minWidth: 320,
      }}
    >
      <section
        // Politeness follows the status rather than being fixed. This was
        // hardcoded 'polite', so a blocking finding, a stale screening or a
        // pharmacist referral was queued until the operator went idle -- which
        // at a working till is after they have already acted.
        aria-live={CLINICAL_STATUS[headline.status].announce}
        style={{
          padding: spacing.lg,
          borderRadius: 12,
          background: palette.surface,
          border: `1px solid ${palette.border}`,
          borderTop: `4px solid ${palette.accent}`,
        }}
      >
        <div style={{ fontSize: fontSize.sectionTitle, fontWeight: 700, color: palette.foreground }}>
          {headline.title}
        </div>
        <p
          style={{
            margin: `${spacing.sm}px 0 0`,
            fontSize: fontSize.body,
            lineHeight: 1.45,
            color: text.secondary,
          }}
        >
          {headline.detail}
        </p>
        {summary?.evaluatedAt ? (
          <div
            style={{
              marginTop: spacing.sm,
              fontSize: fontSize.meta,
              color: text.tertiary,
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            Screened {summary.evaluatedAt}
          </div>
        ) : null}
      </section>

      <ConnectivityRow state={summary?.connectivity ?? 'ONLINE'} />

      {summary && summary.findings.length > 0 ? (
        <section>
          <h3
            style={{
              margin: `0 0 ${spacing.sm}px`,
              fontSize: fontSize.caption,
              textTransform: 'uppercase',
              letterSpacing: 0.6,
              color: text.tertiary,
            }}
          >
            Findings ({summary.findings.length})
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.md }}>
            {/* Blocking findings first: the operator must not have to scroll
                past advisories to discover why they are stuck. */}
            {[...summary.findings]
              .sort(
                (a, b) =>
                  CLINICAL_STATUS[b.severity].weight - CLINICAL_STATUS[a.severity].weight,
              )
              .map((finding) => (
                <FindingCard
                  key={finding.id}
                  finding={finding}
                  {...(capabilities ? { capabilities } : {})}
                  {...(onAcknowledge ? { onAcknowledge } : {})}
                  {...(onRequestPharmacist ? { onRequestPharmacist } : {})}
                  {...(onRequestOverride ? { onRequestOverride } : {})}
                />
              ))}
          </div>
        </section>
      ) : null}
    </aside>
  );
}

function ConnectivityRow({ state }: { state: ConnectivityState }) {
  const meta = CONNECTIVITY[state];
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm }}>
      <span style={{ fontSize: fontSize.meta, color: text.tertiary }}>Connectivity</span>
      <StatusBadge status={meta.status} label={meta.label} size="sm" />
    </div>
  );
}

function FindingCard({
  finding,
  capabilities,
  onAcknowledge,
  onRequestPharmacist,
  onRequestOverride,
}: {
  readonly finding: ClinicalFinding;
  readonly capabilities?: ReadonlySet<string>;
  readonly onAcknowledge?: (findingId: string) => void;
  readonly onRequestPharmacist?: () => void;
  readonly onRequestOverride?: (findingId: string) => void;
}) {
  const palette = statusPalette[finding.severity];
  const may = (capability: string) => !capabilities || capabilities.has(capability);

  return (
    <article
      style={{
        borderRadius: 10,
        border: `1px solid ${palette.border}`,
        borderLeft: `4px solid ${palette.accent}`,
        background: surface.raised,
        padding: spacing.md,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm, flexWrap: 'wrap' }}>
        <StatusBadge status={finding.severity} size="sm" />
        <span style={{ fontSize: fontSize.meta, color: text.tertiary }}>
          {finding.category.replace(/_/g, ' ').toLowerCase()}
        </span>
      </div>

      <h4
        style={{
          margin: `${spacing.sm}px 0 ${spacing.xs}px`,
          fontSize: fontSize.bodyLarge,
          fontWeight: 600,
          color: text.primary,
        }}
      >
        {finding.title}
      </h4>
      <p style={{ margin: 0, fontSize: fontSize.body, lineHeight: 1.45, color: text.secondary }}>
        {finding.explanation}
      </p>

      {finding.recommendation ? (
        <p
          style={{
            margin: `${spacing.sm}px 0 0`,
            fontSize: fontSize.body,
            lineHeight: 1.45,
            color: text.primary,
            fontWeight: 500,
          }}
        >
          {finding.recommendation}
        </p>
      ) : null}

      <div style={{ display: 'flex', gap: spacing.sm, marginTop: spacing.md, flexWrap: 'wrap' }}>
        {/* An advisory can be acknowledged at the till. A blocking finding
            cannot -- acknowledgement must never stand in for a decision. */}
        {!finding.blocking && onAcknowledge && may('clinical.finding.acknowledge') ? (
          <SecondaryButton onClick={() => onAcknowledge(finding.id)}>Acknowledge</SecondaryButton>
        ) : null}

        {finding.requiresPharmacist && onRequestPharmacist ? (
          <SecondaryButton onClick={onRequestPharmacist}>Request pharmacist review</SecondaryButton>
        ) : null}

        {/* Never offered for a finding the server marks non-overridable, and
            never to a user without the capability. Hiding it is a courtesy;
            the backend refuses regardless. */}
        {finding.overrideAllowed && onRequestOverride && may('clinical.override.request') ? (
          <SecondaryButton onClick={() => onRequestOverride(finding.id)}>
            Request clinical override
          </SecondaryButton>
        ) : null}
      </div>
    </article>
  );
}

function SecondaryButton({
  onClick,
  children,
}: {
  readonly onClick: () => void;
  readonly children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        padding: '8px 12px',
        borderRadius: 8,
        border: `1px solid ${surface.borderStrong}`,
        background: surface.raised,
        color: text.primary,
        fontSize: fontSize.caption,
        fontWeight: 600,
        cursor: 'pointer',
        minHeight: 36,
      }}
    >
      {children}
    </button>
  );
}

/** The one authoritative summary line at the top of the rail. */
export function deriveHeadline(summary: ClinicalSummary | null): {
  status: ClinicalStatus;
  title: string;
  detail: string;
} {
  if (!summary) {
    return {
      status: 'DISABLED',
      title: 'No clinical result',
      detail: 'Screening is required before payment.',
    };
  }
  if (summary.connectivity === 'OFFLINE_DISPENSING_BLOCKED') {
    return {
      status: 'BLOCKING',
      title: 'Offline dispensing blocked',
      detail: 'The clinical package is expired or could not be verified. Reconnect to continue.',
    };
  }
  if (summary.stale) {
    return {
      status: 'STALE',
      title: 'Stale clinical result',
      detail: 'The prescription changed after approval. Re-screening is required.',
    };
  }
  if (!summary.screened) {
    return {
      status: 'ACTION_REQUIRED',
      title: 'Screening required',
      detail: 'Clinical screening must be completed before payment.',
    };
  }
  if (summary.blockingCount > 0) {
    return {
      status: 'PHARMACIST_REVIEW',
      title: 'Pharmacist review required',
      detail:
        summary.blockingCount === 1
          ? 'One blocking finding prevents progression.'
          : `${summary.blockingCount} blocking findings prevent progression.`,
    };
  }
  if (!summary.safeToProceed) {
    // The server withheld approval for a reason the client cannot see. Report
    // that honestly rather than presenting it as safe.
    return {
      status: 'ACTION_REQUIRED',
      title: 'Progression not permitted',
      detail: 'The server has not confirmed this screening as safe to proceed.',
    };
  }
  return {
    status: 'SAFE',
    title: 'Safe to proceed',
    detail: 'Clinical screening is current. No unresolved blocking findings.',
  };
}

export { BlockingReason };
