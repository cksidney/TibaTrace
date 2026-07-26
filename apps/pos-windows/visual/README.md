# Visual regression — TibaTrace clinical operations console

Catches what types and unit tests cannot: a component rendering white-on-white,
a status badge losing its colour, a blocking banner collapsing to zero height,
a reason clipped out of its container. Each of those removes a signal an
operator uses to decide whether it is safe to supply a medicine.

## What runs

Every scenario in `scenarios.tsx` is checked three ways:

| Check | Catches |
| --- | --- |
| `renders as approved` | Image diff against the committed baseline |
| `occupies real space` | A component that collapsed instead of rendering |
| `does not clip its content` | Text an operator cannot read |

The last two are platform-independent and enforce properties an image diff
would happily accept as the new normal — a collapsed banner produces a small,
stable, entirely wrong screenshot that gets approved once and never questioned
again.

## Running it

```bash
npm run visual --workspace @dawatrace/pos-windows
```

The layout checks alone, which need no baselines:

```bash
npx playwright test --grep "occupies real space|does not clip" --workspace @dawatrace/pos-windows
```

## Baselines

**CI is the only authority.** Font rasterisation and subpixel rendering differ
enough between macOS, Windows and Linux that a baseline captured on one fails
on another for reasons that have nothing to do with the code. Only
`visual/__screenshots__/linux/` is committed; `darwin/` and `win32/` are
gitignored local scratch.

Capturing baselines locally to look at them is useful and encouraged. Committing
them is not.

To update baselines, run the CI `visual` job with snapshot updating enabled, then
**open every changed image before merging**. A baseline approved without being
looked at is worse than no baseline: it converts an unnoticed regression into a
permanently recorded expectation.

Each scenario carries a `rationale` explaining why that state is in the
catalogue. It is attached to the test result, so it is in front of whoever
reviews a baseline change.

## Adding a scenario

Add it to `SCENARIOS` with a `rationale` that says what going wrong would cost
an operator. Prefer the states that are dangerous to get wrong over the ones
that are common: `payment-ready` is a screenshot, `payment-blocked` is a
control.

The harness fails loudly on an unknown scenario id rather than rendering blank,
because a blank frame would be captured and approved as an empty baseline.

## Determinism

The harness disables animations and transitions, hides the caret, fixes the
locale to `en-GB` and the timezone to UTC, and pins `deviceScaleFactor` to 1.
Scenarios contain no clock reads, no randomness and no network. `retries` is 0:
a visual diff that passes on retry is hiding a real nondeterminism.

Readiness is signalled by `data-visual-ready` after two animation frames, so a
capture cannot race a partially laid-out frame. Never replace that with a sleep.

## What this found

Written as a harness, used as an inspection. The first pass through it surfaced
six defects, five of which no type or unit test would have caught:

- `PHARMACIST_REVIEW` rendered `✓`, the same glyph as `SAFE` — a blocking state
  reading as approval wherever colour was unavailable.
- `ACTION_REQUIRED` announced `polite` despite blocking progression.
- The remaining balance rendered `NaN` for any amount not sent as a plain
  decimal string.
- `Take payment` stayed enabled and green beside a warning not to key an amount
  by hand, and its fill was computed from a different condition than its
  `disabled` state.
- The ribbon distinguished blocked, stale and action-required by hue alone.
- The amount field pre-filled the full price on a partially paid basket, so a
  cashier who did not cross-check collected the settled portion twice.
