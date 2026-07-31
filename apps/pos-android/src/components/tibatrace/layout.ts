/**
 * Layout rules that have to hold on a 5" phone and a 12" ward tablet.
 *
 * The Android client is not a phone app that happens to run on tablets. The
 * same build is handed to a counter assistant on a handset and mounted on a
 * tablet at a dispensing bench, and neither should get a layout designed for
 * the other: a phone must not scroll sideways, and a tablet must not stretch a
 * single column of body text across 1200 points.
 *
 * Breakpoints themselves live in the shared design system, so Android and
 * Windows change columns at the same widths.
 */
import type { ViewStyle } from 'react-native';

/**
 * Caps a scrolling screen at a readable measure and centres what is left.
 *
 * Never binds on a phone -- no Android handset is 820 points wide -- so this
 * costs nothing there and stops a tablet from running text edge to edge.
 */
export const readableColumn: ViewStyle = {
  width: '100%',
  maxWidth: 820,
  alignSelf: 'center',
};

/**
 * One track in a wrapping row.
 *
 * React Native's flexbox has no `auto-fit`, but a `flexBasis` in points with
 * `flexGrow: 1` gives the same result: as many columns as the width can hold,
 * each stretched to share the remainder. A percentage basis cannot -- `45%`
 * is two columns on a phone and still two columns on a tablet, which is where
 * these grids previously left half the screen empty.
 */
export function columnTrack(minWidth: number): ViewStyle {
  return { flexGrow: 1, flexBasis: minWidth, minWidth: 0 };
}
