import { action, fontFamily, fontSize, spacing, statusPalette, surface, text } from '@dawatrace/shared/design-system/index.js';
import type { DispensingLineDTO } from '@dawatrace/shared/dispensing/index.js';

import { BlockingReason, StatusBadge } from './StatusBadge.js';

/**
 * Final check.
 *
 * A side-by-side comparison, not another button. The whole value of this step
 * is that a second person reads what was prescribed against what was actually
 * picked, so the two columns are always rendered together and mismatches are
 * called out rather than left to be spotted.
 */

export interface CheckRow {
  readonly field: string;
  readonly prescribed: string;
  readonly prepared: string;
  readonly matches: boolean;
}

/**
 * Compare a dispensing line against what was authorised.
 *
 * Quantities are compared numerically: "30" and "30.0000" are the same amount
 * of medicine, and flagging that as a mismatch would train checkers to dismiss
 * the warning.
 */
export function compareLine(line: DispensingLineDTO): readonly CheckRow[] {
  const authorised = Number(line.quantity_authorized);
  const prepared = Number(line.quantity_prepared);

  return [
    {
      field: 'Product',
      prescribed: line.prescribed_sku,
      prepared: line.supplied_sku,
      matches: line.prescribed_sku === line.supplied_sku,
    },
    {
      field: 'Quantity',
      prescribed: line.quantity_authorized,
      prepared: line.quantity_prepared,
      matches: Number.isFinite(authorised) && Number.isFinite(prepared) && authorised === prepared,
    },
    {
      field: 'Batch',
      prescribed: '—',
      prepared: line.batch_number_snapshot || '—',
      // A batch is picked at preparation, so there is nothing to compare it
      // against; it is shown for the checker to read off the physical pack.
      matches: true,
    },
    {
      field: 'Expiry',
      prescribed: '—',
      prepared: line.expiry_date_snapshot ?? '—',
      matches: true,
    },
  ];
}

export function hasMismatch(lines: readonly DispensingLineDTO[]): boolean {
  return lines.some((line) => compareLine(line).some((row) => !row.matches));
}

export function FinalCheckComparison({
  lines,
  canComplete,
  blockedReason,
  busy,
  onComplete,
}: {
  readonly lines: readonly DispensingLineDTO[];
  readonly canComplete: boolean;
  readonly blockedReason: string;
  readonly busy: boolean;
  readonly onComplete?: () => void;
}) {
  const mismatch = hasMismatch(lines);

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: spacing.lg }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: spacing.md }}>
        <h2 style={{ margin: 0, fontSize: fontSize.sectionTitle }}>Final check</h2>
        <StatusBadge
          status={mismatch ? 'BLOCKING' : canComplete ? 'ACTION_REQUIRED' : 'DISABLED'}
          label={mismatch ? 'Mismatch found' : canComplete ? 'Ready to check' : 'Not available'}
        />
      </header>

      {mismatch ? (
        <BlockingReason
          status="BLOCKING"
          reason="What was prepared does not match what was prescribed. Resolve the difference before completing the final check."
        />
      ) : null}

      {blockedReason ? <BlockingReason status="BLOCKING" reason={blockedReason} /> : null}

      {lines.map((line) => (
        <LineComparison key={line.id} line={line} />
      ))}

      {onComplete ? (
        <div>
          <button
            type="button"
            disabled={!canComplete || mismatch || busy}
            onClick={onComplete}
            style={{
              padding: '12px 20px',
              borderRadius: 8,
              minHeight: 48,
              border: 'none',
              background: canComplete && !mismatch && !busy ? action.primary : surface.sunken,
              color: canComplete && !mismatch && !busy ? action.primaryForeground : text.tertiary,
              fontSize: fontSize.bodyLarge,
              fontWeight: 600,
              cursor: canComplete && !mismatch && !busy ? 'pointer' : 'not-allowed',
            }}
          >
            {busy ? 'Recording…' : 'Complete final check'}
          </button>
        </div>
      ) : null}
    </section>
  );
}

function LineComparison({ line }: { readonly line: DispensingLineDTO }) {
  const rows = compareLine(line);
  const lineMismatch = rows.some((row) => !row.matches);

  return (
    <article
      style={{
        borderRadius: 12,
        border: `1px solid ${lineMismatch ? statusPalette.BLOCKING.border : surface.border}`,
        background: surface.raised,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          padding: `${spacing.md}px ${spacing.lg}px`,
          borderBottom: `1px solid ${surface.divider}`,
          fontSize: fontSize.bodyLarge,
          fontWeight: 600,
        }}
      >
        {line.supplied_sku}
      </div>

      {/* A prescribed-versus-prepared comparison loses its meaning if the
          columns reflow, so on a narrow screen the table scrolls sideways
          inside its own card rather than stacking. */}
      <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', minWidth: 340, borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={headerCell}>Field</th>
            <th style={headerCell}>Prescribed</th>
            <th style={headerCell}>Prepared</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const palette = row.matches ? null : statusPalette.BLOCKING;
            return (
              <tr key={row.field} style={{ background: palette ? palette.surface : 'transparent' }}>
                <td style={{ ...bodyCell, color: text.secondary }}>{row.field}</td>
                <td style={{ ...bodyCell, fontFamily: fontFamily.numeric }}>{row.prescribed}</td>
                <td
                  style={{
                    ...bodyCell,
                    fontFamily: fontFamily.numeric,
                    fontWeight: row.matches ? 500 : 700,
                    color: palette ? palette.foreground : text.primary,
                  }}
                >
                  {row.prepared}
                  {!row.matches ? (
                    <span style={{ marginLeft: 8, fontSize: fontSize.meta }}>differs</span>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      </div>
    </article>
  );
}

const headerCell: React.CSSProperties = {
  textAlign: 'left',
  padding: `${spacing.sm}px ${spacing.lg}px`,
  fontSize: fontSize.meta,
  textTransform: 'uppercase',
  letterSpacing: 0.5,
  color: text.tertiary,
  fontWeight: 600,
};

const bodyCell: React.CSSProperties = {
  padding: `${spacing.sm}px ${spacing.lg}px`,
  fontSize: fontSize.body,
  fontVariantNumeric: 'tabular-nums',
  borderTop: '1px solid #E6E8EC',
};
