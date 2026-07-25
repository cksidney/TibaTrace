import { describe, expect, it } from 'vitest';

import type { ClinicalTask } from './taskQueue.js';
import {
  TASK_CATEGORIES,
  applyFilter,
  formatWaiting,
  queueCounts,
  rankTasks,
} from './taskQueue.js';

const NOW = new Date('2026-01-01T12:00:00Z');

function task(overrides: Partial<ClinicalTask> = {}): ClinicalTask {
  return {
    id: 't-1',
    category: 'FINAL_CHECK',
    episodeId: 'ep-1',
    dispensingNumber: 'DISP-1',
    patientInitials: 'G.K.',
    summary: 'Final check required',
    requestedBy: 'A. Technician',
    requestedAt: '2026-01-01T11:55:00Z',
    branchId: 'br-1',
    ...overrides,
  };
}

function minutesAgo(minutes: number): string {
  return new Date(NOW.getTime() - minutes * 60000).toISOString();
}

describe('ranking', () => {
  it('puts a controlled medicine above a final check of equal age', () => {
    const ranked = rankTasks(
      [
        task({ id: 'check', category: 'FINAL_CHECK', requestedAt: minutesAgo(5) }),
        task({ id: 'controlled', category: 'CONTROLLED_MEDICINE', requestedAt: minutesAgo(5) }),
      ],
      NOW,
    );
    expect(ranked[0]?.task.id).toBe('controlled');
  });

  it('lets a long-ignored task overtake a fresh urgent one', () => {
    // Without this, a steady stream of urgent arrivals starves everything else
    // -- and the starved item is always someone standing at a counter.
    const ranked = rankTasks(
      [
        task({ id: 'fresh-urgent', category: 'CONTROLLED_MEDICINE', requestedAt: minutesAgo(1) }),
        task({ id: 'old-routine', category: 'PAYMENT_EXCEPTION', requestedAt: minutesAgo(120) }),
      ],
      NOW,
    );
    expect(ranked[0]?.task.id).toBe('old-routine');
  });

  it('marks a task overdue past its category target', () => {
    const ranked = rankTasks(
      [task({ category: 'AWAITING_PHARMACIST', requestedAt: minutesAgo(20) })],
      NOW,
    );
    expect(ranked[0]?.overdue).toBe(true);
    expect(TASK_CATEGORIES.AWAITING_PHARMACIST.targetMinutes).toBe(15);
  });

  it('does not mark a task overdue within its target', () => {
    const ranked = rankTasks(
      [task({ category: 'AWAITING_PHARMACIST', requestedAt: minutesAgo(5) })],
      NOW,
    );
    expect(ranked[0]?.overdue).toBe(false);
  });

  it('treats an unparseable timestamp as new rather than ancient', () => {
    // A malformed record must not jump the queue.
    const ranked = rankTasks(
      [
        task({ id: 'broken', requestedAt: 'not-a-date' }),
        task({ id: 'real', requestedAt: minutesAgo(30) }),
      ],
      NOW,
    );
    expect(ranked[0]?.task.id).toBe('real');
    expect(ranked.find((r) => r.task.id === 'broken')?.waitingMinutes).toBe(0);
  });

  it('never reports a negative wait for a future timestamp', () => {
    const ranked = rankTasks([task({ requestedAt: minutesAgo(-30) })], NOW);
    expect(ranked[0]?.waitingMinutes).toBe(0);
  });
});

describe('filters', () => {
  const tasks = [
    task({ id: 'a', category: 'AWAITING_PHARMACIST', requestedAt: minutesAgo(30) }),
    task({ id: 'b', category: 'OVERRIDE_REQUEST', requestedAt: minutesAgo(2) }),
    task({ id: 'c', category: 'FINAL_CHECK', requestedAt: minutesAgo(1), assignedTo: 'me' }),
  ];

  it('filters by category', () => {
    const ranked = rankTasks(tasks, NOW);
    expect(applyFilter(ranked, 'OVERRIDE_REQUESTS').map((r) => r.task.id)).toEqual(['b']);
  });

  it('filters to overdue for high priority', () => {
    const ranked = rankTasks(tasks, NOW);
    const high = applyFilter(ranked, 'HIGH_PRIORITY');
    expect(high.every((r) => r.overdue)).toBe(true);
    expect(high.map((r) => r.task.id)).toEqual(['a']);
  });

  it('returns nothing for assigned-to-me without a signed-in user', () => {
    // Showing the whole queue as "mine" would misrepresent ownership.
    const ranked = rankTasks(tasks, NOW);
    expect(applyFilter(ranked, 'ASSIGNED_TO_ME')).toEqual([]);
    expect(applyFilter(ranked, 'ASSIGNED_TO_ME', 'me').map((r) => r.task.id)).toEqual(['c']);
  });
});

describe('counts', () => {
  it('reports total, overdue and unassigned', () => {
    const ranked = rankTasks(
      [
        task({ id: 'a', category: 'AWAITING_PHARMACIST', requestedAt: minutesAgo(30) }),
        task({ id: 'b', category: 'FINAL_CHECK', requestedAt: minutesAgo(1), assignedTo: 'me' }),
      ],
      NOW,
    );
    expect(queueCounts(ranked)).toEqual({ total: 2, overdue: 1, unassigned: 1 });
  });
});

describe('waiting time', () => {
  it('reads naturally at every scale', () => {
    expect(formatWaiting(0)).toBe('just now');
    expect(formatWaiting(5)).toBe('5 min');
    expect(formatWaiting(60)).toBe('1 h');
    expect(formatWaiting(95)).toBe('1 h 35 min');
  });
});

describe('shared-screen privacy', () => {
  it('carries initials rather than a full patient name', () => {
    // A queue is often on a screen other people can see.
    const sample = task();
    expect(sample.patientInitials).toBe('G.K.');
    expect(Object.keys(sample)).not.toContain('patientName');
    expect(Object.keys(sample)).not.toContain('dateOfBirth');
  });
});
