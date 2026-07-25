/**
 * Clinical task queue.
 *
 * What is waiting on a pharmacist or supervisor, ordered so the thing that has
 * been blocking a patient longest surfaces first.
 *
 * Two constraints shape this. A queue is a shared view, often on a screen other
 * people can see, so it carries the minimum patient data needed to identify the
 * right prescription and no more. And priority is derived from what the task is
 * and how long it has waited -- never set by whoever created it, or every task
 * becomes urgent.
 */
import type { ClinicalStatus } from '../design-system/clinicalStatus.js';

export type TaskCategory =
  | 'AWAITING_PHARMACIST'
  | 'OVERRIDE_REQUEST'
  | 'FINAL_CHECK'
  | 'CONTROLLED_MEDICINE'
  | 'STALE_REVIEW'
  | 'OFFLINE_SYNC_CONFLICT'
  | 'PAYMENT_EXCEPTION';

export type TaskFilter =
  | 'ALL'
  | 'AWAITING_PHARMACIST'
  | 'OVERRIDE_REQUESTS'
  | 'FINAL_CHECKS'
  | 'CONTROLLED_MEDICINES'
  | 'STALE_REVIEWS'
  | 'HIGH_PRIORITY'
  | 'ASSIGNED_TO_ME';

export interface ClinicalTask {
  readonly id: string;
  readonly category: TaskCategory;
  readonly episodeId: string;
  readonly dispensingNumber: string;
  /** Enough to identify the right patient at the counter, not a full record. */
  readonly patientInitials: string;
  readonly summary: string;
  readonly requestedBy: string;
  readonly requestedAt: string;
  readonly assignedTo?: string;
  readonly branchId: string;
}

interface CategoryMeta {
  readonly label: string;
  readonly status: ClinicalStatus;
  /** Base weight before waiting time is considered. */
  readonly baseWeight: number;
  /** Minutes after which this task is considered overdue. */
  readonly targetMinutes: number;
}

export const TASK_CATEGORIES: Readonly<Record<TaskCategory, CategoryMeta>> = {
  // A controlled supply and an override both stop a patient leaving with
  // medicine and carry the most regulatory weight, so they lead.
  CONTROLLED_MEDICINE: {
    label: 'Controlled medicine',
    status: 'PHARMACIST_REVIEW',
    baseWeight: 100,
    targetMinutes: 10,
  },
  OVERRIDE_REQUEST: {
    label: 'Override request',
    status: 'PHARMACIST_REVIEW',
    baseWeight: 95,
    targetMinutes: 10,
  },
  AWAITING_PHARMACIST: {
    label: 'Awaiting pharmacist',
    status: 'PHARMACIST_REVIEW',
    baseWeight: 90,
    targetMinutes: 15,
  },
  OFFLINE_SYNC_CONFLICT: {
    label: 'Offline sync conflict',
    status: 'BLOCKING',
    baseWeight: 85,
    targetMinutes: 30,
  },
  STALE_REVIEW: {
    label: 'Stale review',
    status: 'STALE',
    baseWeight: 80,
    targetMinutes: 20,
  },
  FINAL_CHECK: {
    label: 'Final check',
    status: 'ACTION_REQUIRED',
    baseWeight: 70,
    targetMinutes: 20,
  },
  PAYMENT_EXCEPTION: {
    label: 'Payment exception',
    status: 'ACTION_REQUIRED',
    baseWeight: 60,
    targetMinutes: 60,
  },
};

export interface RankedTask {
  readonly task: ClinicalTask;
  readonly waitingMinutes: number;
  readonly overdue: boolean;
  readonly priority: number;
  readonly status: ClinicalStatus;
  readonly label: string;
}

/**
 * Rank the queue.
 *
 * Waiting time compounds with category weight so an ordinary task that has been
 * ignored eventually outranks a fresh urgent one. Without that, a steady stream
 * of high-priority arrivals starves everything else -- and the starved item is
 * always someone standing at a counter.
 */
export function rankTasks(tasks: readonly ClinicalTask[], now: Date = new Date()): readonly RankedTask[] {
  return tasks
    .map((task) => {
      const meta = TASK_CATEGORIES[task.category];
      const waitingMinutes = minutesSince(task.requestedAt, now);
      const overdue = waitingMinutes > meta.targetMinutes;
      // One point per minute waited, so age overtakes category within an hour.
      const priority = meta.baseWeight + waitingMinutes;
      return {
        task,
        waitingMinutes,
        overdue,
        priority,
        status: meta.status,
        label: meta.label,
      };
    })
    .sort((a, b) => b.priority - a.priority);
}

export function applyFilter(
  ranked: readonly RankedTask[],
  filter: TaskFilter,
  currentUser?: string,
): readonly RankedTask[] {
  switch (filter) {
    case 'ALL':
      return ranked;
    case 'AWAITING_PHARMACIST':
      return ranked.filter((r) => r.task.category === 'AWAITING_PHARMACIST');
    case 'OVERRIDE_REQUESTS':
      return ranked.filter((r) => r.task.category === 'OVERRIDE_REQUEST');
    case 'FINAL_CHECKS':
      return ranked.filter((r) => r.task.category === 'FINAL_CHECK');
    case 'CONTROLLED_MEDICINES':
      return ranked.filter((r) => r.task.category === 'CONTROLLED_MEDICINE');
    case 'STALE_REVIEWS':
      return ranked.filter((r) => r.task.category === 'STALE_REVIEW');
    case 'HIGH_PRIORITY':
      return ranked.filter((r) => r.overdue);
    case 'ASSIGNED_TO_ME':
      // With no signed-in user this returns nothing rather than everything:
      // showing the whole queue as "mine" would misrepresent ownership.
      return currentUser ? ranked.filter((r) => r.task.assignedTo === currentUser) : [];
  }
}

export function queueCounts(ranked: readonly RankedTask[]): {
  total: number;
  overdue: number;
  unassigned: number;
} {
  return {
    total: ranked.length,
    overdue: ranked.filter((r) => r.overdue).length,
    unassigned: ranked.filter((r) => !r.task.assignedTo).length,
  };
}

export function formatWaiting(minutes: number): string {
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}

function minutesSince(iso: string, now: Date): number {
  const then = Date.parse(iso);
  // An unparseable timestamp is treated as brand new rather than infinitely
  // old, so a malformed record cannot jump the queue.
  if (!Number.isFinite(then)) return 0;
  return Math.max(0, Math.floor((now.getTime() - then) / 60000));
}
