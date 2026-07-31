import {
  ALLERGY_STATUS,
  SAFETY_BADGE,
  fontSize,
  spacing,
  surface,
  text,
} from '@dawatrace/shared/design-system/index.js';
import type { AllergyStatus, SafetyBadge } from '@dawatrace/shared/design-system/index.js';

import { StatusBadge } from './StatusBadge.js';

export interface PatientSummary {
  readonly fullName: string;
  readonly reference: string;
  readonly dateOfBirth?: string;
  readonly age?: string;
  readonly sex?: string;
  readonly allergyStatus: AllergyStatus;
  readonly badges: readonly SafetyBadge[];
  readonly prescriptionRef?: string;
}

/**
 * Persistent patient context.
 *
 * Stays visible through prescription, clinical, payment and dispensing stages:
 * an operator must never have to navigate away to confirm who they are
 * dispensing for.
 *
 * Allergy status is the reason this component exists. "Unknown" is rendered as
 * an amber action-required badge, never as a neutral or green one, because
 * absence of recorded allergies is not evidence of absence and showing the two
 * alike invites treating an unassessed patient as cleared.
 */
export function PatientSafetyBanner({ patient }: { patient: PatientSummary | null }) {
  if (!patient) {
    return (
      <div
        style={{
          padding: `${spacing.md}px ${spacing.xl}px`,
          background: surface.sunken,
          borderBottom: `1px solid ${surface.border}`,
          color: text.secondary,
          fontSize: fontSize.body,
        }}
      >
        No patient selected — search for or register a patient to begin dispensing.
      </div>
    );
  }

  const allergy = ALLERGY_STATUS[patient.allergyStatus];
  // The allergy badge is always shown, and always first: it is the single most
  // consequential fact on the banner.
  const badges = patient.badges.filter(
    (badge) =>
      badge !== 'KNOWN_ALLERGY' &&
      badge !== 'NO_KNOWN_ALLERGIES' &&
      badge !== 'ALLERGY_STATUS_UNKNOWN',
  );

  return (
    <section
      aria-label="Patient safety information"
      style={{
        display: 'flex',
        alignItems: 'center',
        // Identity, safety badges and the prescription reference each move to
        // their own line rather than being squeezed. Without this the three
        // compete for one row, and on a narrow screen the prescription
        // reference was compressed to a few pixels of clipped text.
        flexWrap: 'wrap',
        rowGap: spacing.sm,
        columnGap: spacing.xl,
        padding: `${spacing.md}px clamp(${spacing.md}px, 3vw, ${spacing.xl}px)`,
        background: surface.raised,
        borderBottom: `1px solid ${surface.border}`,
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            fontSize: fontSize.patientName,
            fontWeight: 600,
            color: text.primary,
            lineHeight: 1.2,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {patient.fullName}
        </div>
        <div style={{ fontSize: fontSize.caption, color: text.secondary, marginTop: 2 }}>
          <span style={{ fontVariantNumeric: 'tabular-nums' }}>{patient.reference}</span>
          {patient.dateOfBirth ? ` · ${patient.dateOfBirth}` : ''}
          {patient.age ? ` · ${patient.age}` : ''}
          {patient.sex ? ` · ${patient.sex}` : ''}
        </div>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: spacing.sm, alignItems: 'center' }}>
        <StatusBadge status={allergy.status} label={allergy.label} />
        {badges.map((badge) => {
          const meta = SAFETY_BADGE[badge];
          return <StatusBadge key={badge} status={meta.status} label={meta.label} size="sm" />;
        })}
      </div>

      {patient.prescriptionRef ? (
        <div
          style={{
            marginLeft: 'auto',
            flexShrink: 0,
            fontSize: fontSize.caption,
            color: text.secondary,
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          Prescription {patient.prescriptionRef}
        </div>
      ) : null}
    </section>
  );
}
