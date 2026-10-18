import { useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { IntakeModal } from './IntakeModal.js';
import { inventoryCommand } from './api.js';
import { parseCsvForImport } from './bulkCsv.js';

export function CountSheetUpload({ path, opening = false, csrfToken, tenantId, onClose, onSaved }: {
  readonly path: string; readonly opening?: boolean; readonly csrfToken: string; readonly tenantId: string;
  readonly onClose: () => void; readonly onSaved: () => void;
}) {
  const [rows, setRows] = useState<readonly Readonly<Record<string, string>>[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState(false);
  const [result, setResult] = useState('');
  const version = useRef(0);
  const run = async (dryRun: boolean) => {
    if (busy || !rows.length || !dryRun && !preview) return;
    setBusy(true); setError('');
    try {
      const response = await inventoryCommand<{ items?: number; new_counts?: number; existing_counts?: number }>(path, { rows, dry_run: dryRun }, csrfToken, tenantId);
      setPreview(dryRun); setResult(`${rows.length} rows validated${response.items ? ` for ${response.items} items` : ''}. ${response.existing_counts ? `${response.existing_counts} unchanged counts recognised.` : ''}`);
      if (!dryRun) onSaved();
    } catch (cause) { setPreview(false); setError(cause instanceof Error ? cause.message : 'The count sheet could not be processed.'); }
    finally { setBusy(false); }
  };
  return createPortal(<IntakeModal title={opening ? 'Upload opening stock count' : 'Upload stocktake count sheet'} busy={busy} onClose={onClose}>
    <p className="panel-note">Use the downloaded CSV and keep its IDs unchanged. Enter observed quantities, including explicit zeroes. {opening ? 'Duplicate the item row for each actual medicine batch and expiry. Prices, product mapping and independent release follow manager review.' : 'One row per location, SKU and batch. Existing observations can only be changed through an audited recount. A separate operator posts variances.'}</p>
    <label className="business-field">Completed CSV<input type="file" accept=".csv,text/csv" disabled={busy} onChange={(event) => {
      const file = event.target.files?.[0]; const readVersion = ++version.current;
      setRows([]); setPreview(false); setResult(''); setError('');
      if (!file) return;
      if (!file.name.toLowerCase().endsWith('.csv') || file.size > 5 * 1024 * 1024) { setError('Choose a CSV file no larger than 5 MB.'); return; }
      setBusy(true);
      void file.text().then((content) => {
        if (readVersion !== version.current) return;
        const parsed = parseCsvForImport(content, opening ? ['item_id', 'expected_updated_at', 'counted_quantity', 'counted_on'] : ['session_id', 'location_id', 'sku_id', 'batch_id', 'counted_quantity']);
        if (parsed.error || !parsed.rows.length || parsed.rows.length > 5000) { setError(parsed.error || 'Upload between 1 and 5,000 rows.'); return; }
        setRows(parsed.rows.map((row) => row.values));
      }).catch(() => setError('The CSV could not be read.')).finally(() => setBusy(false));
    }} /></label>
    {rows.length > 0 && <p>{rows.length} rows ready for validation.</p>}
    {result && <p role="status">{result}</p>}{error && <p className="business-dialog-error" role="alert">{error}</p>}
    <footer><button className="secondary-button" type="button" disabled={busy} onClick={onClose}>Close</button><button className="secondary-button" type="button" disabled={busy || !rows.length} onClick={() => void run(true)}>Validate counts</button><button className="primary-button" type="button" disabled={busy || !preview} onClick={() => void run(false)}>{busy ? 'Working…' : 'Save validated counts'}</button></footer>
  </IntakeModal>, document.body);
}
