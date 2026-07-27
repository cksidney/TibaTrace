import { describe, expect, it } from 'vitest';

import { formatDay, formatInstant, formatTimeOfDay } from './instant.js';

/**
 * Field order is pinned (en-GB, day-first, 24-hour) so a clinical timestamp
 * reads the same on every till and matches HQ. The timezone is not pinned: it
 * follows the device, because that is the pharmacy's own clock.
 *
 * These assert on structure rather than an exact string, so they hold wherever
 * the suite runs.
 */
describe('formatInstant', () => {
  it('renders a readable date and time rather than an ISO string', () => {
    const rendered = formatInstant('2026-01-01T09:00:00.000Z');
    expect(rendered).not.toContain('T');
    expect(rendered).not.toContain('Z');
    expect(rendered).toMatch(/\d{2} \w{3} \d{4}/);
    expect(rendered).toMatch(/\d{2}:\d{2}/);
  });

  it('renders in the local timezone, not UTC', () => {
    // The pharmacy runs on its own clock. Rendering the UTC hour to a Nairobi
    // counter shows 06:00 for a 09:00 screening, and rolls the date backwards
    // for anything dispensed in the evening.
    const instant = '2026-01-01T09:00:00.000Z';
    const expectedHour = new Date(instant).getHours().toString().padStart(2, '0');
    expect(formatInstant(instant)).toContain(`${expectedHour}:`);
  });

  it('says a missing timestamp is missing rather than inventing one', () => {
    expect(formatInstant(null)).toBe('Not recorded');
    expect(formatInstant(undefined)).toBe('Not recorded');
    expect(formatInstant('')).toBe('Not recorded');
  });

  it('distinguishes unreadable from absent', () => {
    // A value that arrived but could not be parsed is a different problem from
    // no value, and hiding one behind the other loses that.
    expect(formatInstant('not-a-date')).toBe('Unreadable timestamp');
  });
});

describe('formatDay', () => {
  it('renders a date with no time component', () => {
    const rendered = formatDay('2026-07-27T00:00:00.000Z');
    expect(rendered).toMatch(/\d{2} \w{3} \d{4}/);
    expect(rendered).not.toMatch(/\d{2}:\d{2}/);
  });

  it('handles a bare date string', () => {
    expect(formatDay('2026-07-27')).toMatch(/\d{2} \w{3} \d{4}/);
  });

  it('reports absence and unreadability separately', () => {
    expect(formatDay(null)).toBe('Not recorded');
    expect(formatDay('nonsense')).toBe('Unreadable timestamp');
  });
});

describe('formatTimeOfDay', () => {
  it('renders a 24-hour clock', () => {
    const rendered = formatTimeOfDay('2026-01-01T14:30:00.000Z');
    expect(rendered).toMatch(/^\d{2}:\d{2}$/);
    // No am/pm: a till reads faster without it, and 24-hour is unambiguous.
    expect(rendered.toLowerCase()).not.toContain('m');
  });

  it('reports absence and unreadability separately', () => {
    expect(formatTimeOfDay(undefined)).toBe('Not recorded');
    expect(formatTimeOfDay('nope')).toBe('Unreadable timestamp');
  });
});
