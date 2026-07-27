/**
 * Rendering an instant to a person standing at a counter.
 *
 * The POS was printing raw ISO strings -- `Screened 2026-01-01T09:00:00.000Z`
 * -- straight into the clinical rail, the collection receipt and the episode
 * timeline. There was no date formatting anywhere in either POS app or in this
 * package.
 *
 * Two problems, and the second is the serious one.
 *
 * It is unreadable: a pharmacist mid-dispense should not be parsing an ISO
 * string to work out whether a screening is minutes or hours old.
 *
 * And it is in the wrong timezone. That `Z` is UTC. A pharmacy in Nairobi runs
 * three hours ahead, so a screening at 09:00 local prints as 06:00, and an
 * evening dispense prints as the previous day's date. The backend already has
 * this hazard on its own side -- business dates there must use `localdate()`
 * rather than the UTC date, or they read wrong between midnight and 03:00 --
 * and this is the same bug wearing client-side clothes.
 *
 * These render in the device's own timezone, which for a till is the pharmacy's.
 *
 * The locale is pinned to en-GB while the timezone is left to the device. Field
 * order is a consistency question -- HQ writes "27 Jul 2026", and a clinical
 * timestamp should not read day-first on one till and month-first on the next
 * because their operating systems were installed with different locales. The
 * clock is a correctness question, and that must follow the pharmacy.
 */

/**
 * Day-first ordering and a 24-hour clock, matching HQ. Not the device locale:
 * see above.
 */
const LOCALE = 'en-GB';

/** What to show when a timestamp is missing. Never a fabricated date. */
const ABSENT = 'Not recorded';

/** What to show when a timestamp is present but unparseable. */
const UNREADABLE = 'Unreadable timestamp';

function parse(value: string | null | undefined): Date | null {
  if (value === null || value === undefined || value === '') return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/**
 * A date and time, e.g. "27 Jul 2026, 09:04".
 *
 * For anything an operator may need to reason about the age of: when a
 * screening ran, when a package was collected, when a state changed.
 */
export function formatInstant(value: string | null | undefined): string {
  const parsed = parse(value);
  if (value === null || value === undefined || value === '') return ABSENT;
  if (!parsed) return UNREADABLE;
  return new Intl.DateTimeFormat(LOCALE, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(parsed);
}

/** A date alone, e.g. "27 Jul 2026". For expiry dates and similar. */
export function formatDay(value: string | null | undefined): string {
  const parsed = parse(value);
  if (value === null || value === undefined || value === '') return ABSENT;
  if (!parsed) return UNREADABLE;
  return new Intl.DateTimeFormat(LOCALE, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(parsed);
}

/**
 * Time alone, e.g. "09:04". Only for a timestamp already known to be today --
 * on anything older it hides the date and makes a stale value look current.
 */
export function formatTimeOfDay(value: string | null | undefined): string {
  const parsed = parse(value);
  if (value === null || value === undefined || value === '') return ABSENT;
  if (!parsed) return UNREADABLE;
  return new Intl.DateTimeFormat(LOCALE, {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(parsed);
}
