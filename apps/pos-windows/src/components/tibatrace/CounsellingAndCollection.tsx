import { action, fontFamily, fontSize, spacing, surface, text } from '@dawatrace/shared/design-system/index.js';
import type { CounsellingRecordRequest } from '@dawatrace/shared/dispensing/index.js';
import { formatInstant } from '@dawatrace/shared/clinical/index.js';
import { useState } from 'react';

import { BlockingReason, StatusBadge } from './StatusBadge.js';

/**
 * Counselling.
 *
 * Every topic starts unchecked. The server defaults each flag to true when a
 * field is omitted, so sending a partly-filled body would silently record that
 * everything was explained. The panel therefore always sends an explicit value
 * for every topic -- a counselling record has to reflect what actually happened.
 */

const TOPICS = [
  { key: 'medicine_explained', label: 'Medicine and purpose explained' },
  { key: 'dosage_explained', label: 'Dosage and frequency explained' },
  { key: 'storage_explained', label: 'Storage explained' },
  { key: 'side_effects_discussed', label: 'Side effects discussed' },
  { key: 'interaction_advice_given', label: 'Interaction advice given' },
  { key: 'patient_acknowledged', label: 'Patient acknowledged understanding' },
] as const;

type TopicKey = (typeof TOPICS)[number]['key'];

export function CounsellingPanel({
  counsellingStatus,
  busy,
  onRecord,
}: {
  readonly counsellingStatus: string;
  readonly busy: boolean;
  readonly onRecord: (request: CounsellingRecordRequest) => void;
}) {
  const [checked, setChecked] = useState<Record<TopicKey, boolean>>({
    medicine_explained: false,
    dosage_explained: false,
    storage_explained: false,
    side_effects_discussed: false,
    interaction_advice_given: false,
    patient_acknowledged: false,
  });
  const [notes, setNotes] = useState('');
  const complete = counsellingStatus === 'COMPLETED';

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: spacing.md }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: spacing.md }}>
        <h2 style={{ margin: 0, fontSize: fontSize.sectionTitle }}>Counselling</h2>
        <StatusBadge
          status={complete ? 'COMPLETED' : 'ACTION_REQUIRED'}
          label={complete ? 'Recorded' : 'Not recorded'}
        />
      </header>

      <fieldset style={{ border: 'none', margin: 0, padding: 0, display: 'grid', gap: spacing.sm }}>
        {TOPICS.map((topic) => (
          <label
            key={topic.key}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: spacing.sm,
              fontSize: fontSize.body,
              minHeight: 36,
              cursor: 'pointer',
            }}
          >
            <input
              type="checkbox"
              checked={checked[topic.key]}
              onChange={(event) =>
                setChecked((prev) => ({ ...prev, [topic.key]: event.target.checked }))
              }
              style={{ width: 18, height: 18 }}
            />
            {topic.label}
          </label>
        ))}
      </fieldset>

      <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: fontSize.caption, color: text.secondary }}>
        Notes
        <textarea
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          rows={3}
          style={{
            padding: '10px 12px',
            borderRadius: 8,
            border: `1px solid ${surface.borderStrong}`,
            fontSize: fontSize.body,
            fontFamily: fontFamily.sans,
            resize: 'vertical',
          }}
        />
      </label>

      <div>
        <button
          type="button"
          disabled={busy}
          // Always sends every flag explicitly, never a partial body.
          onClick={() => onRecord({ ...checked, notes })}
          style={{
            padding: '10px 16px',
            borderRadius: 8,
            minHeight: 44,
            border: `1px solid ${surface.borderStrong}`,
            background: surface.raised,
            fontSize: fontSize.body,
            fontWeight: 600,
            cursor: busy ? 'not-allowed' : 'pointer',
          }}
        >
          {busy ? 'Recording…' : 'Record counselling'}
        </button>
      </div>
    </section>
  );
}

/**
 * Collection.
 *
 * Supply and collection are separate facts and are never merged: paying for
 * medicine is not receiving it, and the record must be able to say which
 * happened. Confirming collection is what posts inventory on the server.
 */
export function CollectionPanel({
  canConfirm,
  blockedReason,
  collectedAt,
  collectorName,
  busy,
  onConfirm,
}: {
  readonly canConfirm: boolean;
  readonly blockedReason: string;
  readonly collectedAt: string | null;
  readonly collectorName: string;
  readonly busy: boolean;
  readonly onConfirm: (name: string, idNumber: string, relationship: string) => void;
}) {
  const [name, setName] = useState('');
  const [idNumber, setIdNumber] = useState('');
  const [relationship, setRelationship] = useState('SELF');
  const [submitted, setSubmitted] = useState(false);

  if (collectedAt) {
    return (
      <section style={{ display: 'flex', flexDirection: 'column', gap: spacing.sm }}>
        <header style={{ display: 'flex', alignItems: 'center', gap: spacing.md }}>
          <h2 style={{ margin: 0, fontSize: fontSize.sectionTitle }}>Collection</h2>
          <StatusBadge status="COMPLETED" label="Collected" />
        </header>
        <p style={{ margin: 0, fontSize: fontSize.body, color: text.secondary }}>
          Collected by {collectorName || 'unrecorded collector'} at{' '}
          <span style={{ fontVariantNumeric: 'tabular-nums' }}>{formatInstant(collectedAt)}</span>.
        </p>
      </section>
    );
  }

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: spacing.md }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: spacing.md }}>
        <h2 style={{ margin: 0, fontSize: fontSize.sectionTitle }}>Collection</h2>
        <StatusBadge
          status={canConfirm ? 'ACTION_REQUIRED' : 'DISABLED'}
          label={canConfirm ? 'Ready to hand over' : 'Not permitted'}
        />
      </header>

      {blockedReason ? <BlockingReason status="BLOCKING" reason={blockedReason} /> : null}

      <div style={{ display: 'flex', gap: spacing.md, flexWrap: 'wrap' }}>
        <Field label="Collector name" value={name} onChange={setName} />
        <Field label="Identity number" value={idNumber} onChange={setIdNumber} numeric />
        <label
          style={{
            display: 'flex',
            flex: '1 1 200px',
            minWidth: 0,
            flexDirection: 'column',
            gap: 4,
            fontSize: fontSize.caption,
            color: text.secondary,
          }}
        >
          Relationship
          <select
            value={relationship}
            onChange={(event) => setRelationship(event.target.value)}
            style={{
              boxSizing: 'border-box',
              width: '100%',
              padding: '10px 12px',
              borderRadius: 8,
              border: `1px solid ${surface.borderStrong}`,
              fontSize: fontSize.body,
              minHeight: 44,
              minWidth: 0,
            }}
          >
            <option value="SELF">Patient</option>
            <option value="REPRESENTATIVE">Authorised representative</option>
            <option value="COURIER">Courier</option>
            <option value="WARD_STAFF">Ward staff</option>
          </select>
        </label>
      </div>

      <div>
        <button
          type="button"
          disabled={!canConfirm || busy || submitted || !name.trim()}
          onClick={() => {
            setSubmitted(true);
            onConfirm(name.trim(), idNumber.trim(), relationship);
          }}
          style={{
            padding: '12px 20px',
            borderRadius: 8,
            minHeight: 48,
            border: 'none',
            background: canConfirm && !busy && !submitted && name.trim() ? action.primary : surface.sunken,
            color: canConfirm && !busy && !submitted && name.trim() ? action.primaryForeground : text.tertiary,
            fontSize: fontSize.bodyLarge,
            fontWeight: 600,
            cursor: canConfirm && !busy && !submitted && name.trim() ? 'pointer' : 'not-allowed',
          }}
        >
          {busy ? 'Confirming…' : 'Confirm collection'}
        </button>
      </div>

      <p style={{ margin: 0, fontSize: fontSize.caption, color: text.secondary }}>
        Confirming collection posts the inventory movement. It cannot be undone from this screen.
      </p>
    </section>
  );
}

function Field({
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
    <label
      style={{
        display: 'flex',
        flex: '1 1 200px',
        minWidth: 0,
        flexDirection: 'column',
        gap: 4,
        fontSize: fontSize.caption,
        color: text.secondary,
      }}
    >
      {label}
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        style={{
          boxSizing: 'border-box',
          width: '100%',
          padding: '10px 12px',
          borderRadius: 8,
          border: `1px solid ${surface.borderStrong}`,
          fontSize: fontSize.body,
          minHeight: 44,
          minWidth: 0,
          fontFamily: numeric ? fontFamily.numeric : fontFamily.sans,
        }}
      />
    </label>
  );
}
