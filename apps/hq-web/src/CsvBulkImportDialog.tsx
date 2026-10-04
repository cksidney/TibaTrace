import { useState } from 'react';
import type { ChangeEvent, ReactNode } from 'react';

import { Icon } from './icons.js';
import {
  downloadCsvTemplate,
  parseCsvForImport,
} from './bulkCsv.js';
import type { CsvImportRow } from './bulkCsv.js';

export interface CsvImportIssue {
  readonly row: number;
  readonly field: string;
  readonly value: string;
  readonly message: string;
}

export interface CsvImportPreview {
  readonly dry_run: boolean;
  readonly received: number;
  readonly valid: boolean;
  readonly errors: readonly CsvImportIssue[];
}

interface CsvBulkImportDialogProps<Result extends CsvImportPreview> {
  readonly columns: readonly string[];
  readonly description: string;
  readonly example: readonly string[];
  readonly filename: string;
  readonly onClose: () => void;
  readonly onImported: () => Promise<void>;
  readonly preview: (rows: readonly CsvImportRow[]) => Promise<Result>;
  readonly save: (rows: readonly CsvImportRow[]) => Promise<Result>;
  readonly summarise: (result: Result) => ReactNode;
  readonly title: string;
}

/**
 * Preview-first CSV import dialog shared by tenant catalogue and prices.
 *
 * Files are read only in the browser.  The first request is a dry run; the
 * irreversible-looking button remains disabled until the exact same parsed
 * rows return with no validation errors.
 */
export function CsvBulkImportDialog<Result extends CsvImportPreview>({
  columns,
  description,
  example,
  filename,
  onClose,
  onImported,
  preview,
  save,
  summarise,
  title,
}: CsvBulkImportDialogProps<Result>) {
  const [rows, setRows] = useState<readonly CsvImportRow[]>([]);
  const [fileName, setFileName] = useState('');
  const [parseError, setParseError] = useState('');
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState<'preview' | 'save' | null>(null);
  const [requestError, setRequestError] = useState('');
  const [saved, setSaved] = useState(false);

  const selectFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    setRows([]);
    setResult(null);
    setRequestError('');
    setSaved(false);
    if (!file) {
      setFileName('');
      setParseError('');
      return;
    }
    setFileName(file.name);
    try {
      const parsed = parseCsvForImport(await file.text(), columns);
      setParseError(parsed.error ?? '');
      setRows(parsed.rows);
    } catch {
      setParseError('The selected file could not be read as text. Save it as a UTF-8 CSV and try again.');
    }
  };

  const runPreview = async () => {
    if (!rows.length) return;
    setBusy('preview');
    setRequestError('');
    setSaved(false);
    try {
      setResult(await preview(rows));
    } catch (error) {
      setResult(null);
      setRequestError(error instanceof Error ? error.message : 'The import preview could not be completed.');
    } finally {
      setBusy(null);
    }
  };

  const apply = async () => {
    if (!rows.length || !result?.valid || result.errors.length) return;
    setBusy('save');
    setRequestError('');
    try {
      const applied = await save(rows);
      setResult(applied);
      if (applied.errors.length) return;
      await onImported();
      setSaved(true);
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : 'The import could not be saved.');
    } finally {
      setBusy(null);
    }
  };

  const errors = result?.errors ?? [];
  return (
    <div className="business-dialog-backdrop" role="presentation">
      <section aria-labelledby="csv-bulk-import-title" aria-modal="true" className="business-dialog bulk-import-dialog" role="dialog">
        <header>
          <div>
            <p className="eyebrow">Controlled CSV import</p>
            <h2 id="csv-bulk-import-title">{title}</h2>
          </div>
          <button aria-label="Close" disabled={busy !== null} onClick={onClose} type="button"><Icon name="close" /></button>
        </header>
        <p className="business-dialog-confirm"><Icon name="shield" />{description}</p>
        <div className="bulk-import-template">
          <div>
            <strong>Required CSV columns</strong>
            <code>{columns.join(', ')}</code>
          </div>
          <button
            className="secondary-button"
            onClick={() => downloadCsvTemplate(filename, columns, example)}
            type="button"
          >
            Download template
          </button>
        </div>
        <label className="business-field">
          <span>CSV file</span>
          <input accept=".csv,text/csv" onChange={(event) => void selectFile(event)} type="file" />
          <small>{fileName ? `${fileName} · ${rows.length} data row${rows.length === 1 ? '' : 's'} parsed` : 'CSV is read in this browser. It is not stored as an uploaded document.'}</small>
        </label>
        {parseError ? <p className="business-dialog-error" role="alert"><Icon name="alert" />{parseError}</p> : null}
        {requestError ? <p className="business-dialog-error" role="alert"><Icon name="alert" />{requestError}</p> : null}
        {result ? (
          <div className={errors.length ? 'bulk-import-result has-errors' : 'bulk-import-result'}>
            <strong>{result.dry_run ? 'Preview result' : saved ? 'Import complete' : 'Import result'}</strong>
            <p>{summarise(result)}</p>
            {errors.length ? (
              <div className="bulk-import-errors" role="alert">
                <strong>{errors.length} row{errors.length === 1 ? '' : 's'} need correction</strong>
                <ul>
                  {errors.slice(0, 12).map((issue, index) => (
                    <li key={`${issue.row}-${issue.field}-${index}`}>
                      <b>Row {issue.row}</b> · {issue.field}: {issue.message}
                      {issue.value ? <code>{issue.value}</code> : null}
                    </li>
                  ))}
                </ul>
                {errors.length > 12 ? <small>Showing the first 12 errors. Correct the file and preview it again.</small> : null}
              </div>
            ) : null}
          </div>
        ) : null}
        <footer>
          <button className="secondary-button" disabled={busy !== null} onClick={onClose} type="button">{saved ? 'Close' : 'Cancel'}</button>
          {!saved ? (
            <>
              <button className="secondary-button" disabled={!rows.length || busy !== null} onClick={() => void runPreview()} type="button">
                {busy === 'preview' ? 'Validating…' : 'Preview import'}
              </button>
              <button className="primary-button" disabled={!result?.valid || errors.length > 0 || busy !== null} onClick={() => void apply()} type="button">
                {busy === 'save' ? 'Saving…' : 'Import validated rows'}
              </button>
            </>
          ) : null}
        </footer>
      </section>
    </div>
  );
}
