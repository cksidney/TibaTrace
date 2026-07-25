import {
  fontFamily,
  fontSize,
  spacing,
  statusPalette,
  surface,
  text,
} from '@dawatrace/shared/design-system/index.js';
import type { TimelineEntry } from '@dawatrace/shared/dispensing/index.js';
import { TIMELINE_EVENTS, orderTimeline } from '@dawatrace/shared/dispensing/index.js';
import { useState } from 'react';

/**
 * Episode timeline.
 *
 * A readable operational history rather than raw audit JSON. Someone
 * reconstructing what happened to a prescription -- a pharmacist the next
 * morning, an auditor months later -- reads this in order without knowing the
 * event schema.
 *
 * Notable entries (refusals, reversals, staleness) carry extra weight, because
 * anyone opening a timeline is usually looking for the moment it went wrong.
 */
export function EpisodeTimeline({ entries }: { readonly entries: readonly TimelineEntry[] }) {
  const [notableOnly, setNotableOnly] = useState(false);
  const ordered = orderTimeline(entries);
  const shown = notableOnly
    ? ordered.filter((entry) => TIMELINE_EVENTS[entry.type]?.notable)
    : ordered;

  if (entries.length === 0) {
    return (
      <section>
        <h2 style={{ margin: 0, fontSize: fontSize.sectionTitle }}>History</h2>
        <p style={{ color: text.secondary, fontSize: fontSize.body }}>
          Nothing has been recorded for this episode yet.
        </p>
      </section>
    );
  }

  return (
    <section>
      <header style={{ display: 'flex', alignItems: 'center', gap: spacing.md }}>
        <h2 style={{ margin: 0, fontSize: fontSize.sectionTitle }}>History</h2>
        <label
          style={{
            marginLeft: 'auto',
            display: 'flex',
            alignItems: 'center',
            gap: spacing.sm,
            fontSize: fontSize.caption,
            color: text.secondary,
            minHeight: 36,
            cursor: 'pointer',
          }}
        >
          <input
            type="checkbox"
            checked={notableOnly}
            onChange={(event) => setNotableOnly(event.target.checked)}
            style={{ width: 16, height: 16 }}
          />
          Show only exceptions
        </label>
      </header>

      <ol style={{ listStyle: 'none', margin: `${spacing.lg}px 0 0`, padding: 0 }}>
        {shown.map((entry) => {
          const presentation = TIMELINE_EVENTS[entry.type];
          const palette = statusPalette[presentation?.status ?? 'INFORMATION'];
          const notable = presentation?.notable ?? false;

          return (
            <li
              key={entry.id}
              style={{
                display: 'grid',
                gridTemplateColumns: '150px 12px 1fr',
                gap: spacing.md,
                alignItems: 'start',
                padding: `${spacing.md}px 0`,
                borderTop: `1px solid ${surface.divider}`,
              }}
            >
              <time
                dateTime={entry.occurredAt}
                style={{
                  fontSize: fontSize.meta,
                  color: text.tertiary,
                  fontFamily: fontFamily.numeric,
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {formatTimestamp(entry.occurredAt)}
              </time>

              <span
                aria-hidden="true"
                style={{
                  width: 10,
                  height: 10,
                  marginTop: 5,
                  borderRadius: 999,
                  background: notable ? palette.accent : 'transparent',
                  border: `2px solid ${palette.accent}`,
                }}
              />

              <div>
                <div
                  style={{
                    fontSize: fontSize.body,
                    fontWeight: notable ? 700 : 500,
                    color: notable ? palette.foreground : text.primary,
                  }}
                >
                  {presentation?.label ?? entry.type.replace(/_/g, ' ').toLowerCase()}
                </div>
                <div style={{ fontSize: fontSize.caption, color: text.secondary, marginTop: 2 }}>
                  {entry.summary}
                  {entry.actor ? ` · ${entry.actor}` : ''}
                </div>
                {/* Only rendered when the server recorded one; never invented. */}
                {entry.reason ? (
                  <div
                    style={{
                      marginTop: spacing.xs,
                      fontSize: fontSize.caption,
                      color: palette.foreground,
                    }}
                  >
                    {entry.reason}
                  </div>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>

      {notableOnly && shown.length === 0 ? (
        <p style={{ color: text.secondary, fontSize: fontSize.body }}>
          No exceptions were recorded for this episode.
        </p>
      ) : null}
    </section>
  );
}

/** Renders an unparseable timestamp as-is rather than hiding the entry. */
function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toISOString().replace('T', ' ').slice(0, 19);
}
