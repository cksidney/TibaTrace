import { useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { IntakeModal } from './IntakeModal.js';
import { downloadOpeningStocktakeTemplate, importTenantItemList } from './api.js';
import type { TenantItemImportResult } from './api.js';
import { downloadCsvTemplate, parseCsvForImport } from './bulkCsv.js';
import type { CsvImportRow } from './bulkCsv.js';

export const ITEM_UPLOAD_COLUMNS = [
  'item_code', 'item_name', 'sales_unit', 'item_kind', 'pack_description',
  'cost_price', 'selling_price', 'tax_category', 'barcode', 'master_catalogue_code', 'source_quantity',
] as const;
const REQUIRED_COLUMNS = ['item_code', 'item_name', 'sales_unit'];
const MAX_FILE_BYTES = 5 * 1024 * 1024;
const MAX_ROWS = 5000;

function today(): string {
  const date = new Date();
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

export function TenantItemUploadDialog({ csrfToken, tenantId, onClose, onImported }: {
  readonly csrfToken: string;
  readonly tenantId: string;
  readonly onClose: () => void;
  readonly onImported: (result: TenantItemImportResult) => void;
}) {
  const [sourceDate, setSourceDate] = useState(today);
  const [filename, setFilename] = useState('');
  const [rows, setRows] = useState<readonly CsvImportRow[]>([]);
  const [error, setError] = useState('');
  const [result, setResult] = useState<TenantItemImportResult | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState<'read' | 'preview' | 'save' | 'download' | null>(null);
  const inFlight = useRef(false);
  const readVersion = useRef(0);

  const selectFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    const version = ++readVersion.current;
    setRows([]); setResult(null); setSaved(false); setError('');
    setFilename(file?.name ?? '');
    if (!file) { setBusy(null); return; }
    if (!file.name.toLowerCase().endsWith('.csv')) {
      setError('Save the item list as CSV UTF-8 (.csv) in Excel or your current system, then choose that file.');
      setBusy(null);
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setError('The file is larger than 5 MB. Split it into files of up to 5,000 items each.');
      setBusy(null);
      return;
    }
    setBusy('read');
    try {
      const parsed = parseCsvForImport(await file.text(), REQUIRED_COLUMNS);
      if (version !== readVersion.current) return;
      if (parsed.error) { setError(parsed.error); return; }
      if (parsed.rows.length > MAX_ROWS) { setError('Upload at most 5,000 item rows per file.'); return; }
      const unknown = [...new Set(parsed.rows.flatMap((row) => Object.keys(row.values)))].filter(
        (column) => !ITEM_UPLOAD_COLUMNS.includes(column as typeof ITEM_UPLOAD_COLUMNS[number]),
      );
      if (unknown.length) {
        setError(`Unrecognised columns: ${unknown.join(', ')}. Rename them to match the template, or remove them before uploading.`);
        return;
      }
      setRows(parsed.rows);
    } catch {
      if (version === readVersion.current) setError('The file could not be read. Save it as CSV UTF-8 and try again.');
    } finally {
      if (version === readVersion.current) setBusy(null);
    }
  };

  const runImport = async (dryRun: boolean) => {
    if (!rows.length || !sourceDate || inFlight.current || (!dryRun && !result?.valid)) return;
    inFlight.current = true;
    setBusy(dryRun ? 'preview' : 'save'); setError('');
    try {
      const imported = await importTenantItemList(
        rows.map((row) => ({ ...row.values, _source_row: row.line })),
        sourceDate, filename, dryRun, csrfToken, tenantId,
      );
      setResult(imported);
      if (!dryRun && imported.valid && !imported.errors.length && imported.import_id) {
        setSaved(true);
        onImported(imported);
      }
    } catch (cause) {
      // A lost response can follow a committed import. The server recognises
      // the same file on retry and preserves all existing review evidence.
      setError(cause instanceof Error ? cause.message : 'The import outcome could not be confirmed. Preview the same file again before retrying.');
      setResult(null);
    } finally { inFlight.current = false; setBusy(null); }
  };

  const downloadSheet = async () => {
    if (!result?.import_id || inFlight.current) return;
    inFlight.current = true; setBusy('download'); setError('');
    try { await downloadOpeningStocktakeTemplate(tenantId, result.import_id); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'The stock-take sheet could not be downloaded.'); }
    finally { inFlight.current = false; setBusy(null); }
  };

  const issues = result?.errors ?? [];
  return <IntakeModal title="Upload tenant item list" busy={busy !== null} onClose={onClose}>
    <p className="panel-note">Import your existing product list, then download a stock-take sheet for these items. Uploads enter the setup queue; catalogue mapping, price publication and opening-stock release follow review.</p>
    {!saved ? <>
      <div className="bulk-import-template">
        <div><strong>1. Prepare your item list</strong><p>Required: <code>item_code</code>, <code>item_name</code>, <code>sales_unit</code>. Other template cells may be blank.</p></div>
        <button className="secondary-button" type="button" disabled={busy !== null} onClick={() => downloadCsvTemplate(
          'tibatrace-tenant-items-template.csv', ITEM_UPLOAD_COLUMNS,
          ['ITEM-001', 'Example supply', 'piece', 'SUPPLY', 'Sold per piece', '100.00', '150.00', '', '', '', ''],
        )}>Download item template</button>
      </div>
      <details className="item-upload-help"><summary>Column guidance</summary>
        <p>Keep item codes and barcodes as text to preserve leading zeros. Use one row per item and a unique item code. Prices are per sales unit; use decimal numbers without currency symbols or thousands separators.</p>
        <p><code>item_kind</code>: MEDICINE, SUPPLY or SERVICE. <code>tax_category</code>: STANDARD, ZERO_RATED or EXEMPT. Leave an unverified tax treatment or national catalogue code blank.</p>
        <p><code>source_quantity</code> preserves a balance from your old system. The stock-take sheet leaves counts blank so staff record current physical quantities.</p>
      </details>
      <fieldset className="item-upload-fields" disabled={busy !== null}>
        <label className="business-field"><span>Date of source data</span><input type="date" required max={today()} value={sourceDate} onChange={(event) => { setSourceDate(event.target.value); setResult(null); }} /></label>
        <label className="business-field"><span>2. Choose item CSV</span><input type="file" accept=".csv,text/csv" onChange={(event) => void selectFile(event)} />
          <small>{filename ? `${filename} · ${rows.length} item rows read` : 'CSV UTF-8 · up to 5 MB and 5,000 items per file'}</small></label>
      </fieldset>
      {rows.length ? <div className="table-scroll item-upload-preview"><table><caption>First {Math.min(3, rows.length)} of {rows.length} items</caption><thead><tr><th>Item code</th><th>Name</th><th>Sales unit</th></tr></thead><tbody>{rows.slice(0, 3).map((row) => <tr key={row.line}><td><code>{row.values.item_code}</code></td><td>{row.values.item_name}</td><td>{row.values.sales_unit}</td></tr>)}</tbody></table></div> : null}
    </> : null}
    {error ? <p className="business-dialog-error" role="alert">{error}</p> : null}
    {result ? <div className={`bulk-import-result${issues.length ? ' has-errors' : ''}`} role="status">
      <strong>{saved ? 'Item list imported' : issues.length ? 'Correct the listed rows' : 'Validation complete'}</strong>
      <p>{issues.length ? `${result.received} rows checked; ${issues.length} issues need correction. Nothing was imported.`
        : saved ? `${result.created} items added to setup. ${result.existing} already imported items retained their existing review details.`
          : result.existing ? `${result.existing} items are already imported. Confirm to use the existing item list and download its stock-take sheet.`
            : `${result.ready_to_stage} items are ready for the setup queue.`}</p>
      {issues.length ? <ul className="item-upload-errors">{issues.slice(0, 20).map((issue, index) => <li key={`${issue.row}-${issue.field}-${index}`}><b>{issue.row ? `Row ${issue.row}` : 'File'} · {issue.field}</b>: {issue.message}{issue.value ? <code>{issue.value}</code> : null}</li>)}</ul> : null}
      {issues.length > 20 ? <small>Showing the first 20 issues. Correct the file and preview again.</small> : null}
      {saved ? <p>Next, count each item in its sales unit. For medicines, record each actual batch and expiry on a separate row. Enter zero for items with no physical stock. Keep the item IDs with the sheet, then enter the verified counts through <strong>Complete details</strong>.</p> : null}
    </div> : null}
    <footer className="item-upload-actions"><button className="secondary-button" type="button" disabled={busy !== null} onClick={onClose}>{saved ? 'Done' : 'Cancel'}</button>
      {saved ? <button className="primary-button" type="button" disabled={busy !== null} onClick={() => void downloadSheet()}>{busy === 'download' ? 'Preparing sheet…' : 'Download stock-take sheet'}</button> : <>
        <button className="secondary-button" type="button" disabled={!rows.length || !sourceDate || busy !== null} onClick={() => void runImport(true)}>{busy === 'preview' ? 'Validating…' : 'Preview import'}</button>
        <button className="primary-button" type="button" disabled={!result?.valid || issues.length > 0 || busy !== null} onClick={() => void runImport(false)}>{busy === 'save' ? 'Importing…' : 'Import validated items'}</button>
      </>}
    </footer>
  </IntakeModal>;
}
