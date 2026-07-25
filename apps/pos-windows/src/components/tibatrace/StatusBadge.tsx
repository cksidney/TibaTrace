import { CLINICAL_STATUS, statusPalette } from '@dawatrace/shared/design-system/index.js';
import type { ClinicalStatus } from '@dawatrace/shared/design-system/index.js';
import type { CSSProperties, ReactNode } from 'react';

/**
 * A status is never communicated by colour alone.
 *
 * Every badge renders a glyph and a text label as well as its palette, so the
 * meaning survives colour-blindness, a sun-washed till screen and a monochrome
 * remote session. `title` carries the longer description for hover and
 * assistive technology.
 */

const GLYPH: Record<string, string> = {
  'octagon-x': '✕',
  'user-check': '✓',
  history: '↺',
  'cloud-off': '⌁',
  'alert-triangle': '!',
  loader: '◌',
  info: 'i',
  'check-circle': '✓',
  'shield-check': '✓',
  lock: '🔒',
};

export interface StatusBadgeProps {
  readonly status: ClinicalStatus;
  /** Overrides the default status label where a more specific one reads better. */
  readonly label?: string;
  readonly size?: 'sm' | 'md';
  readonly children?: ReactNode;
}

export function StatusBadge({ status, label, size = 'md', children }: StatusBadgeProps) {
  const meta = CLINICAL_STATUS[status];
  const palette = statusPalette[status];

  const style: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    padding: size === 'sm' ? '2px 8px' : '4px 10px',
    borderRadius: 999,
    background: palette.surface,
    color: palette.foreground,
    border: `1px solid ${palette.border}`,
    fontSize: size === 'sm' ? 12 : 13,
    fontWeight: 600,
    lineHeight: 1.2,
    whiteSpace: 'nowrap',
  };

  return (
    <span style={style} title={meta.description} data-status={status}>
      <span aria-hidden="true" style={{ fontWeight: 700 }}>
        {GLYPH[meta.icon] ?? '•'}
      </span>
      <span>{label ?? meta.label}</span>
      {children}
    </span>
  );
}

/**
 * The reason an operator cannot proceed.
 *
 * Rendered as an assertive live region for blocking states so a screen reader
 * announces a new blocker rather than leaving it to be discovered.
 */
export function BlockingReason({ status, reason }: { status: ClinicalStatus; reason: string }) {
  if (!reason) return null;
  const palette = statusPalette[status];
  const meta = CLINICAL_STATUS[status];

  return (
    <div
      role="status"
      aria-live={meta.announce === 'off' ? 'off' : meta.announce}
      style={{
        display: 'flex',
        gap: 10,
        padding: '10px 12px',
        borderRadius: 8,
        background: palette.surface,
        border: `1px solid ${palette.border}`,
        borderLeft: `4px solid ${palette.accent}`,
        color: palette.foreground,
        fontSize: 14,
        lineHeight: 1.45,
      }}
    >
      <span aria-hidden="true" style={{ fontWeight: 700 }}>
        {GLYPH[meta.icon] ?? '•'}
      </span>
      <span>{reason}</span>
    </div>
  );
}
