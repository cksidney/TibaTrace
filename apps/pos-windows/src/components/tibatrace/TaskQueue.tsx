import {
  fontFamily,
  fontSize,
  spacing,
  statusPalette,
  surface,
  text,
} from '@dawatrace/shared/design-system/index.js';
import type { ClinicalTask, TaskFilter } from '@dawatrace/shared/dispensing/index.js';
import {
  applyFilter,
  formatWaiting,
  queueCounts,
  rankTasks,
} from '@dawatrace/shared/dispensing/index.js';
import { useMemo, useState } from 'react';

import { StatusBadge } from './StatusBadge.js';

const FILTERS: readonly { value: TaskFilter; label: string }[] = [
  { value: 'ALL', label: 'All' },
  { value: 'HIGH_PRIORITY', label: 'Overdue' },
  { value: 'AWAITING_PHARMACIST', label: 'Awaiting pharmacist' },
  { value: 'OVERRIDE_REQUESTS', label: 'Override requests' },
  { value: 'CONTROLLED_MEDICINES', label: 'Controlled' },
  { value: 'FINAL_CHECKS', label: 'Final checks' },
  { value: 'STALE_REVIEWS', label: 'Stale' },
  { value: 'ASSIGNED_TO_ME', label: 'Assigned to me' },
];

/**
 * Clinical task queue.
 *
 * Ordered so the item that has kept someone waiting longest surfaces first.
 * Deliberately shows patient initials and the dispensing number rather than a
 * name: this is a shared screen, often visible from the shop floor, and it only
 * needs to identify the right prescription.
 */
export function TaskQueue({
  tasks,
  currentUser,
  onOpen,
}: {
  readonly tasks: readonly ClinicalTask[];
  readonly currentUser?: string;
  readonly onOpen?: (episodeId: string) => void;
}) {
  const [filter, setFilter] = useState<TaskFilter>('ALL');
  const ranked = useMemo(() => rankTasks(tasks), [tasks]);
  const shown = useMemo(
    () => applyFilter(ranked, filter, currentUser),
    [ranked, filter, currentUser],
  );
  const counts = queueCounts(ranked);

  return (
    <section>
      <header style={{ display: 'flex', alignItems: 'baseline', gap: spacing.md }}>
        <h2 style={{ margin: 0, fontSize: fontSize.sectionTitle }}>Task queue</h2>
        <span style={{ fontSize: fontSize.caption, color: text.secondary }}>
          {counts.total} waiting
          {counts.overdue > 0 ? ` · ${counts.overdue} overdue` : ''}
          {counts.unassigned > 0 ? ` · ${counts.unassigned} unassigned` : ''}
        </span>
      </header>

      <div
        role="group"
        aria-label="Filter tasks"
        style={{ display: 'flex', gap: spacing.sm, flexWrap: 'wrap', margin: `${spacing.md}px 0` }}
      >
        {FILTERS.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={filter === option.value}
            onClick={() => setFilter(option.value)}
            style={{
              padding: '6px 12px',
              minHeight: 36,
              borderRadius: 999,
              border: `1px solid ${filter === option.value ? statusPalette.INFORMATION.accent : surface.border}`,
              background:
                filter === option.value ? statusPalette.INFORMATION.surface : surface.raised,
              fontSize: fontSize.caption,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            {option.label}
          </button>
        ))}
      </div>

      {shown.length === 0 ? (
        <p style={{ color: text.secondary, fontSize: fontSize.body }}>
          {filter === 'ALL'
            ? 'Nothing is waiting.'
            : 'No tasks match this filter.'}
        </p>
      ) : (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: spacing.sm }}>
          {shown.map((item) => {
            const palette = statusPalette[item.status];
            return (
              <li key={item.task.id}>
                <button
                  type="button"
                  onClick={onOpen ? () => onOpen(item.task.episodeId) : undefined}
                  style={{
                    width: '100%',
                    display: 'grid',
                    gridTemplateColumns: 'auto 1fr auto',
                    gap: spacing.md,
                    alignItems: 'center',
                    textAlign: 'left',
                    padding: spacing.md,
                    minHeight: 56,
                    borderRadius: 10,
                    border: `1px solid ${surface.border}`,
                    borderLeft: `4px solid ${palette.accent}`,
                    background: surface.raised,
                    cursor: onOpen ? 'pointer' : 'default',
                  }}
                >
                  <StatusBadge status={item.status} label={item.label} size="sm" />

                  <span style={{ minWidth: 0 }}>
                    <span
                      style={{
                        display: 'block',
                        fontSize: fontSize.body,
                        fontWeight: 600,
                        color: text.primary,
                      }}
                    >
                      {item.task.summary}
                    </span>
                    <span
                      style={{
                        display: 'block',
                        fontSize: fontSize.caption,
                        color: text.secondary,
                        fontFamily: fontFamily.numeric,
                      }}
                    >
                      {item.task.dispensingNumber} · {item.task.patientInitials} ·{' '}
                      {item.task.requestedBy}
                      {item.task.assignedTo ? ` · assigned to ${item.task.assignedTo}` : ''}
                    </span>
                  </span>

                  <span
                    style={{
                      fontSize: fontSize.caption,
                      fontWeight: item.overdue ? 700 : 500,
                      color: item.overdue ? statusPalette.BLOCKING.foreground : text.secondary,
                      fontVariantNumeric: 'tabular-nums',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {formatWaiting(item.waitingMinutes)}
                    {item.overdue ? ' overdue' : ''}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
