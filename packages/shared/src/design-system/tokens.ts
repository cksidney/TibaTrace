/**
 * TibaTrace clinical POS design tokens.
 *
 * Platform-neutral values. Windows renders them as CSS custom properties;
 * Android maps them into its own theme. Components must reference tokens rather
 * than literals so that a status colour can never be tuned in one screen and
 * left stale in another.
 *
 * Colours are chosen for contrast on till hardware, which is often a glossy
 * panel in a brightly lit room. Every status pairs a strong foreground with a
 * low-saturation surface so text stays legible without relying on hue.
 */
import type { ClinicalStatus } from './clinicalStatus.js';

export const spacing = {
  none: 0,
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
  xxxl: 48,
} as const;

export const radii = {
  none: 0,
  sm: 4,
  md: 8,
  lg: 12,
  pill: 999,
} as const;

export const fontSize = {
  /** Metadata and audit timestamps. Never used for clinical instructions. */
  meta: 12,
  caption: 13,
  body: 15,
  bodyLarge: 16,
  /** Dosage instructions -- must stay readable at till distance. */
  instruction: 18,
  sectionTitle: 18,
  medicineName: 22,
  patientName: 24,
  screenTitle: 28,
} as const;

export const fontWeight = {
  regular: 400,
  medium: 500,
  semibold: 600,
  bold: 700,
} as const;

export const lineHeight = {
  tight: 1.2,
  normal: 1.45,
  relaxed: 1.6,
} as const;

/**
 * Minimum interactive sizes.
 *
 * Android follows the 48dp accessible touch-target guidance. Desktop controls
 * are smaller but still generous, because till operators work fast and a
 * mis-click on a clinical action is expensive.
 */
export const controlSize = {
  desktopHeight: 40,
  desktopHeightLarge: 48,
  touchTarget: 48,
  touchTargetLarge: 56,
  iconSm: 16,
  iconMd: 20,
  iconLg: 24,
} as const;

export const elevation = {
  none: 'none',
  raised: '0 1px 2px rgba(15, 23, 42, 0.08)',
  drawer: '0 8px 24px rgba(15, 23, 42, 0.16)',
  modal: '0 16px 48px rgba(15, 23, 42, 0.24)',
} as const;

export const duration = {
  /** Kept short: motion communicates a transition, it never gates the workflow. */
  instant: 0,
  fast: 120,
  normal: 200,
  slow: 320,
} as const;

export interface StatusPalette {
  readonly foreground: string;
  readonly surface: string;
  readonly border: string;
  /** Strong fill, for badges and the leading edge of a status card. */
  readonly accent: string;
}

/**
 * Semantic status palette.
 *
 * Red is reserved for genuine blocking and destructive states. A routine
 * warning that does not stop dispensing must not borrow it, or operators learn
 * to click through red.
 */
export const statusPalette: Readonly<Record<ClinicalStatus, StatusPalette>> = {
  SAFE: {
    foreground: '#0B6B3A',
    surface: '#ECFDF3',
    border: '#A6E9C5',
    accent: '#12854A',
  },
  INFORMATION: {
    foreground: '#0F4C81',
    surface: '#EFF6FF',
    border: '#B3D4F5',
    accent: '#1B6BB8',
  },
  ACTION_REQUIRED: {
    foreground: '#7A4A00',
    surface: '#FFF8EB',
    border: '#F5D699',
    accent: '#B26E00',
  },
  PHARMACIST_REVIEW: {
    foreground: '#8A3D00',
    surface: '#FFF3E8',
    border: '#F7C8A0',
    accent: '#C25708',
  },
  BLOCKING: {
    foreground: '#8B1116',
    surface: '#FEF1F1',
    border: '#F5B9BB',
    accent: '#C1272D',
  },
  STALE: {
    // Distinct from both amber and red: a stale approval is not a new clinical
    // risk, it is a loss of authority, and it must not read as either.
    foreground: '#5B2B8A',
    surface: '#F7F1FE',
    border: '#D9C2F2',
    accent: '#7A3FBF',
  },
  OFFLINE: {
    foreground: '#2E3A59',
    surface: '#F2F4F9',
    border: '#C6CEE0',
    accent: '#44557F',
  },
  PROCESSING: {
    foreground: '#0F4C81',
    surface: '#EFF6FF',
    border: '#B3D4F5',
    accent: '#1B6BB8',
  },
  COMPLETED: {
    foreground: '#37524A',
    surface: '#F1F6F4',
    border: '#C4D6CF',
    accent: '#4E7267',
  },
  DISABLED: {
    foreground: '#5B6472',
    surface: '#F4F5F7',
    border: '#D7DAE0',
    accent: '#8A929F',
  },
};

export const surface = {
  page: '#F6F7F9',
  raised: '#FFFFFF',
  sunken: '#EEF0F4',
  inverse: '#101828',
  border: '#D7DAE0',
  borderStrong: '#B4BAC5',
  divider: '#E6E8EC',
} as const;

export const text = {
  primary: '#101828',
  secondary: '#48505E',
  /** Floor for any clinical content. Never used for warnings or identifiers. */
  tertiary: '#667085',
  inverse: '#FFFFFF',
  link: '#1B6BB8',
} as const;

export const focus = {
  ring: '#1B6BB8',
  ringWidth: 2,
  ringOffset: 2,
} as const;

/**
 * System-first stacks. No webfont is fetched: a till may be offline, and a
 * clinical instruction must never wait on -- or fall back from -- a download.
 */
export const fontFamily = {
  sans: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  /** Tabular figures for quantities, money, batch numbers and timestamps. */
  numeric:
    'ui-monospace, "SF Mono", "Cascadia Mono", "Roboto Mono", Consolas, "Courier New", monospace',
} as const;

export const zIndex = {
  base: 0,
  sticky: 100,
  drawer: 200,
  modal: 300,
  toast: 400,
} as const;
