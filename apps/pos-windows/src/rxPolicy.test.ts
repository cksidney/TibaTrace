import { expect, it } from 'vitest';
import { allowsRxCamera, rxRequestLimit } from '../electron/rxPolicy.js';

it('allows larger payloads only on the two RX upload commands', () => {
  expect(rxRequestLimit('/api/pos/dispensing/intake/', 'POST')).toBe(12 * 1024 * 1024);
  expect(rxRequestLimit('/api/pos/dispensing/intake/import/', 'POST')).toBe(12 * 1024 * 1024);
  for (const [path, method] of [['/api/pos/dispensing/intake/', 'GET'], ['/api/pos/dispensing/intake/rx/progress/', 'POST'], ['/api/pos/dispensing/intake/../payment/', 'POST'], ['/api/pos/payments/', 'POST']]) {
    expect(rxRequestLimit(path!, method!)).toBe(1024 * 1024);
  }
});

it('grants camera access only to the focused main renderer and denies microphone and frames', () => {
  const request = { page: 'file:///app/index.html', requestingUrl: 'file:///app/index.html', packagedPage: 'file:///app/index.html', devServer: undefined, focused: true, isMainFrame: true, permission: 'media', mediaTypes: ['video'] };
  expect(allowsRxCamera(request)).toBe(true);
  for (const change of [{ mediaTypes: ['audio'] }, { mediaTypes: ['video', 'audio'] }, { isMainFrame: false }, { focused: false }, { requestingUrl: 'blob:file:///app/index.html' }, { page: 'https://example.test' }, { permission: 'geolocation' }]) {
    expect(allowsRxCamera({ ...request, ...change })).toBe(false);
  }
  expect(allowsRxCamera({ ...request, page: 'http://localhost:5173/', requestingUrl: 'http://localhost:5173/', devServer: 'http://localhost:5173/' })).toBe(true);
  expect(allowsRxCamera({ ...request, page: 'http://localhost:5173.evil.test/', requestingUrl: 'http://localhost:5173.evil.test/', devServer: 'http://localhost:5173/' })).toBe(false);
});
