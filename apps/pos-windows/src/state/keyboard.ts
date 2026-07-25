/**
 * Keyboard operation for the Windows till.
 *
 * A dispensary runs at speed and the operator's hands are often on a scanner,
 * not a mouse. Every stage the console can reach has a shortcut.
 *
 * Two rules shape the map:
 *
 * 1. No shortcut performs a clinical, financial or custody action. F8 opens the
 *    payment stage; it does not take payment. A stray keypress must never move
 *    money or release stock -- those stay behind explicit, focusable controls.
 * 2. Nothing is bound that the browser or Electron already owns in a way an
 *    operator relies on.
 */

export type PosCommand =
  | 'HELP'
  | 'SEARCH_MEDICINE'
  | 'PATIENT'
  | 'PRESCRIPTION'
  | 'CLINICAL_FINDINGS'
  | 'PHARMACIST_REVIEW'
  | 'PREPARATION'
  | 'PAYMENT'
  | 'HOLD'
  | 'SCAN_FOCUS'
  | 'CLOSE'
  | 'REFRESH';

export interface ShortcutBinding {
  readonly key: string;
  readonly ctrl?: boolean;
  readonly command: PosCommand;
  readonly label: string;
  /** True where the binding only navigates. All of them do, by design. */
  readonly navigationOnly: boolean;
}

export const SHORTCUTS: readonly ShortcutBinding[] = [
  { key: 'F1', command: 'HELP', label: 'Help and shortcuts', navigationOnly: true },
  { key: 'F2', command: 'SEARCH_MEDICINE', label: 'Medicine search', navigationOnly: true },
  { key: 'F3', command: 'PATIENT', label: 'Patient', navigationOnly: true },
  { key: 'F4', command: 'PRESCRIPTION', label: 'Prescription', navigationOnly: true },
  { key: 'F5', command: 'CLINICAL_FINDINGS', label: 'Clinical findings', navigationOnly: true },
  { key: 'F6', command: 'PHARMACIST_REVIEW', label: 'Pharmacist review', navigationOnly: true },
  { key: 'F7', command: 'PREPARATION', label: 'Preparation', navigationOnly: true },
  { key: 'F8', command: 'PAYMENT', label: 'Payment stage', navigationOnly: true },
  { key: 'F9', command: 'HOLD', label: 'Hold transaction', navigationOnly: true },
  { key: 'F12', command: 'SCAN_FOCUS', label: 'Focus scan field', navigationOnly: true },
  { key: 'Escape', command: 'CLOSE', label: 'Close drawer or return', navigationOnly: true },
  {
    key: 'r',
    ctrl: true,
    command: 'REFRESH',
    label: 'Re-read authoritative state',
    navigationOnly: true,
  },
];

/** Fields where a shortcut must not fire, so typing a batch number is safe. */
function isTextEntry(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return (
    tag === 'INPUT' ||
    tag === 'TEXTAREA' ||
    tag === 'SELECT' ||
    target.isContentEditable
  );
}

/**
 * Resolve a keyboard event to a command, or null.
 *
 * Escape is deliberately still honoured inside a text field: an operator must
 * always be able to back out of a drawer even mid-entry.
 */
export function resolveShortcut(event: {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  target?: EventTarget | null;
}): PosCommand | null {
  const inText = isTextEntry(event.target ?? null);
  if (inText && event.key !== 'Escape') {
    // Function keys are still safe inside a field; character keys are not.
    if (!/^F\d+$/.test(event.key)) return null;
  }

  for (const binding of SHORTCUTS) {
    if (binding.key !== event.key) continue;
    const wantsModifier = binding.ctrl === true;
    const hasModifier = Boolean(event.ctrlKey) || Boolean(event.metaKey);
    if (wantsModifier !== hasModifier) continue;
    return binding.command;
  }
  return null;
}

/** Every binding is navigation-only; asserted in tests, not just documented. */
export function performsPrivilegedAction(binding: ShortcutBinding): boolean {
  return !binding.navigationOnly;
}
