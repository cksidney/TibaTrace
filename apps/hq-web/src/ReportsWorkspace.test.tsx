/** @vitest-environment jsdom */
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it, vi } from 'vitest';

import { ReportsWorkspace } from './ReportsWorkspace.js';
import { downloadEnterpriseReport, loadReportAvailability } from './api.js';

vi.mock('./api.js', () => ({
  loadReportAvailability: vi.fn(async () => [
    { id: 'exec-dashboard', available: true, period_filter: false, availability_note: 'Current snapshot; no historical filtering.' },
    { id: 'fin-gl', available: false, period_filter: true, availability_note: 'No source-data query implemented.' },
  ]),
  downloadEnterpriseReport: vi.fn(async () => ({ receiptId: '', filename: 'report.pdf' })),
  validateReportReceipt: vi.fn(),
}));

describe('source-data report availability', () => {
  it('disables planned packs and does not send a historical window for snapshots', async () => {
    (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const container = document.createElement('div');
    const root = createRoot(container);
    try {
      await act(async () => root.render(<ReportsWorkspace csrfToken="csrf" onNavigate={vi.fn()} overview={{
        tenant_id: 'tenant', tenant_name: 'Tenant', user_name: 'Manager', is_platform_overview: false,
        attention_items: [], data_summary: [], metrics: [], network_items: [], generated_at: '', scope_label: 'Tenant', scope_description: '',
      }} />));
      expect(loadReportAvailability).toHaveBeenCalledWith('tenant', expect.any(AbortSignal));
      expect(container.textContent).toContain('Current snapshot; no historical filtering.');
      const snapshotExport = container.querySelector<HTMLSelectElement>('[aria-label="Export format for Executive KPI dashboard"]');
      // The selected first report has a verified implementation; all unknown packs remain disabled.
      expect(Array.from(container.querySelectorAll('select.reports-download-select')).filter((item) => !(item as HTMLSelectElement).disabled)).toHaveLength(1);
      const enabled = snapshotExport ?? container.querySelector<HTMLSelectElement>('select.reports-download-select:not(:disabled)');
      await act(async () => {
        if (enabled) enabled.value = 'pdf';
        enabled?.dispatchEvent(new Event('change', { bubbles: true }));
      });
      expect(downloadEnterpriseReport).toHaveBeenCalledWith('exec-dashboard', 'pdf', 'csrf', 'tenant', {});
    } finally { await act(async () => root.unmount()); }
  });
});
