import type { CSSProperties } from 'react';

export type PosIconName = 'clinical' | 'retail' | 'register' | 'print' | 'sync' | 'shield' | 'search' | 'arrow' | 'lock' | 'help' | 'check' | 'bag';
const paths: Record<PosIconName, string> = {
  clinical: 'M9 3h6v6h6v6h-6v6H9v-6H3V9h6V3Z',
  retail: 'M3 3h2l3 12h10l3-9H6M9 21a1 1 0 1 0 0-2 1 1 0 0 0 0 2M18 21a1 1 0 1 0 0-2 1 1 0 0 0 0 2',
  register: 'M4 9h16v12H4V9ZM7 3h10v6H7V3ZM4 15h16M8 12h1M12 12h1M16 12h1M10 18h4',
  print: 'M7 8V3h10v5M7 17H3V8h18v9h-4M7 13h10v8H7v-8ZM17 10h1',
  sync: 'M20 7a9 9 0 0 0-15-2L2 8m0-5v5h5M4 17a9 9 0 0 0 15 2l3-3m0 5v-5h-5',
  shield: 'm12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6l9-4Zm-4 10 3 3 5-6',
  search: 'M21 21l-5-5M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14',
  arrow: 'M4 12h16m-6-6 6 6-6 6',
  lock: 'M5 10h14v11H5V10Zm3 0V6a4 4 0 0 1 8 0v4m-4 4v3',
  help: 'M9 8a3 3 0 1 1 5 2c-2 1-2 2-2 3m0 4h.01M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20',
  check: 'm5 12 4 4L19 6',
  bag: 'M4 7h16l-1 14H5L4 7Zm4 0V6a4 4 0 0 1 8 0v1',
};
export function PosIcon({ name, size = 20, style }: { readonly name: PosIconName; readonly size?: number; readonly style?: CSSProperties }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ flexShrink: 0, ...style }}><path d={paths[name]} /></svg>;
}
