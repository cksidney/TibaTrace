import { useEffect, useMemo, useState } from 'react';

import {
  downloadEnterpriseReport,
  validateReportReceipt,
  type HQOverview,
  type ReportDownloadReceipt,
  type ReportExportFormat,
  type ReportFilterOptions,
  type ReportGranularity,
} from './api.js';
import { Icon } from './icons.js';
import {
  REPORT_CATALOGUE,
  REPORT_CATEGORIES,
  type ReportCategoryId,
  type ReportDefinition,
} from './reportsCatalogue.js';

type WorkspaceView =
  | 'overview'
  | 'network'
  | 'people'
  | 'catalogue'
  | 'inventory'
  | 'operations'
  | 'commerce'
  | 'pricing'
  | 'cash'
  | 'insurance'
  | 'clinical'
  | 'reports'
  | 'governance'
  | 'access';

const PAGE_SIZE = 10;
const FORMATS: readonly { readonly id: ReportExportFormat; readonly label: string }[] = [
  { id: 'pdf', label: 'PDF' },
  { id: 'csv', label: 'CSV' },
  { id: 'xlsx', label: 'Excel' },
  { id: 'json', label: 'JSON' },
];

type CategoryFilter = 'ALL' | ReportCategoryId;
type DatePresetId = 'TODAY' | 'YESTERDAY' | 'THIS_WEEK' | 'THIS_MONTH' | 'LAST_MONTH' | 'THIS_YEAR' | 'CUSTOM';

const DATE_PRESETS: readonly { readonly id: DatePresetId; readonly label: string }[] = [
  { id: 'TODAY', label: 'Today' },
  { id: 'YESTERDAY', label: 'Yesterday' },
  { id: 'THIS_WEEK', label: 'This Week' },
  { id: 'THIS_MONTH', label: 'This Month' },
  { id: 'LAST_MONTH', label: 'Last Month' },
  { id: 'THIS_YEAR', label: 'This Year' },
  { id: 'CUSTOM', label: 'Custom Range' },
];

function formatLocalIso(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  const yyyy = date.getFullYear();
  const mm = pad(date.getMonth() + 1);
  const dd = pad(date.getDate());
  const hh = pad(date.getHours());
  const min = pad(date.getMinutes());
  return `${yyyy}-${mm}-${dd}T${hh}:${min}`;
}

function calculatePresetRange(preset: DatePresetId): { start: string; end: string } {
  const now = new Date();
  if (preset === 'TODAY') {
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
    return { start: formatLocalIso(start), end: formatLocalIso(now) };
  }
  if (preset === 'YESTERDAY') {
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1, 0, 0, 0);
    const end = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1, 23, 59, 59);
    return { start: formatLocalIso(start), end: formatLocalIso(end) };
  }
  if (preset === 'THIS_WEEK') {
    const day = now.getDay();
    const diff = now.getDate() - day + (day === 0 ? -6 : 1);
    const start = new Date(now.getFullYear(), now.getMonth(), diff, 0, 0, 0);
    return { start: formatLocalIso(start), end: formatLocalIso(now) };
  }
  if (preset === 'THIS_MONTH') {
    const start = new Date(now.getFullYear(), now.getMonth(), 1, 0, 0, 0);
    return { start: formatLocalIso(start), end: formatLocalIso(now) };
  }
  if (preset === 'LAST_MONTH') {
    const start = new Date(now.getFullYear(), now.getMonth() - 1, 1, 0, 0, 0);
    const end = new Date(now.getFullYear(), now.getMonth(), 0, 23, 59, 59);
    return { start: formatLocalIso(start), end: formatLocalIso(end) };
  }
  if (preset === 'THIS_YEAR') {
    const start = new Date(now.getFullYear(), 0, 1, 0, 0, 0);
    return { start: formatLocalIso(start), end: formatLocalIso(now) };
  }
  const start = new Date(now.getFullYear(), now.getMonth(), 1, 0, 0, 0);
  return { start: formatLocalIso(start), end: formatLocalIso(now) };
}

function reportRangeError(startValue: string, endValue: string): string {
  if (!startValue || !endValue) return 'Choose both a reporting-window start and end.';
  const start = new Date(startValue);
  const end = new Date(endValue);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return 'Choose valid reporting-window dates and times.';
  }
  if (start > end) return 'Reporting-window start must be before or equal to the end.';
  return '';
}

function useSummaryMap(overview: HQOverview) {
  return useMemo(
    () => new Map(overview.data_summary.map((item) => [item.label, item.value])),
    [overview.data_summary],
  );
}

export function ReportsWorkspace({
  csrfToken,
  overview,
  onNavigate,
}: {
  readonly csrfToken: string;
  readonly overview: HQOverview;
  readonly onNavigate: (view: WorkspaceView) => void;
}) {
  const summary = useSummaryMap(overview);
  const [category, setCategory] = useState<CategoryFilter>('ALL');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(REPORT_CATALOGUE[0]?.id ?? null);
  const [format, setFormat] = useState<ReportExportFormat>('pdf');
  const [busyId, setBusyId] = useState('');
  const [error, setError] = useState('');
  const [receipt, setReceipt] = useState<ReportDownloadReceipt | null>(null);
  const [validation, setValidation] = useState<Record<string, unknown> | null>(null);

  const [datePreset, setDatePreset] = useState<DatePresetId>('THIS_MONTH');
  const initialRange = useMemo(() => calculatePresetRange('THIS_MONTH'), []);
  const [startDateTimeIso, setStartDateTimeIso] = useState(initialRange.start);
  const [endDateTimeIso, setEndDateTimeIso] = useState(initialRange.end);
  const [granularity, setGranularity] = useState<ReportGranularity>('DAILY');
  const rangeError = useMemo(
    () => reportRangeError(startDateTimeIso, endDateTimeIso),
    [endDateTimeIso, startDateTimeIso],
  );

  const applyPreset = (preset: DatePresetId) => {
    setDatePreset(preset);
    if (preset !== 'CUSTOM') {
      const range = calculatePresetRange(preset);
      setStartDateTimeIso(range.start);
      setEndDateTimeIso(range.end);
    }
  };

  const counts = useMemo(() => {
    const byCategory = new Map<ReportCategoryId, number>();
    for (const report of REPORT_CATALOGUE) {
      byCategory.set(report.category, (byCategory.get(report.category) ?? 0) + 1);
    }
    return { byCategory, total: REPORT_CATALOGUE.length };
  }, []);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return REPORT_CATALOGUE.filter((report) => {
      if (category !== 'ALL' && report.category !== category) return false;
      if (!needle) return true;
      const categoryLabel = REPORT_CATEGORIES.find((item) => item.id === report.category)?.label ?? '';
      return [report.name, report.description, report.audience, report.cadence, categoryLabel, report.id]
        .join(' ')
        .toLowerCase()
        .includes(needle);
    });
  }, [category, search]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount);
  const pageItems = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);
  const selected = REPORT_CATALOGUE.find((report) => report.id === selectedId) ?? pageItems[0] ?? null;

  useEffect(() => {
    setPage(1);
  }, [category, search]);

  useEffect(() => {
    if (page !== safePage) setPage(safePage);
  }, [page, safePage]);

  const download = async (report: ReportDefinition, exportFormat: ReportExportFormat) => {
    if (rangeError) {
      setError(rangeError);
      return;
    }
    setBusyId(`${report.id}:${exportFormat}`);
    setError('');
    setValidation(null);
    try {
      const filterOpts: ReportFilterOptions = {
        fromIso: new Date(startDateTimeIso).toISOString(),
        toIso: new Date(endDateTimeIso).toISOString(),
        granularity,
      };
      const next = await downloadEnterpriseReport(
        report.id,
        exportFormat,
        csrfToken,
        overview.tenant_id,
        filterOpts,
      );
      setReceipt(next);
      if (next.receiptId) {
        const checked = await validateReportReceipt(next.receiptId, overview.tenant_id);
        setValidation(checked);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Report download failed.');
    } finally {
      setBusyId('');
    }
  };

  return (
    <div className="reports-workspace">
      <section className="reports-strip" aria-label="Reporting catalogue summary">
        <div>
          <p className="eyebrow">Enterprise reporting</p>
          <h2>Downloadable report packs</h2>
          <p>
            Professionally formatted exports for every catalogue pack. Each download embeds a unique
            validation QR with who downloaded it, when, tenant scope, terminal identity and integrity code.
          </p>
        </div>
        <dl className="reports-kpis">
          <div><dt>Catalogue</dt><dd>{counts.total}</dd></div>
          <div><dt>Formats</dt><dd>4</dd></div>
          <div><dt>QR validation</dt><dd>On</dd></div>
          <div><dt>Tenant isolation</dt><dd>On</dd></div>
        </dl>
      </section>

      <section className="panel reports-datetime-panel" aria-label="Reporting window">
        <header className="reports-datetime-header">
          <div>
            <p className="eyebrow"><Icon name="shield" /> Report scope</p>
            <h3>Reporting window & aggregation</h3>
            <p className="muted-cell">
              Record the precise period and aggregation used for this tenant-scoped export and its validation receipt.
            </p>
          </div>
          <div className="reports-datetime-badge">
            <Icon name="search" />
            <span>
              {startDateTimeIso ? new Date(startDateTimeIso).toLocaleString('en-KE', { dateStyle: 'medium', timeStyle: 'short' }) : 'Start'}
              {' → '}
              {endDateTimeIso ? new Date(endDateTimeIso).toLocaleString('en-KE', { dateStyle: 'medium', timeStyle: 'short' }) : 'End'}
            </span>
          </div>
        </header>

        <div className="reports-datetime-body">
          <div className="reports-preset-chips">
            <span className="reports-field-label">Quick presets</span>
            {DATE_PRESETS.map((preset) => (
              <button
                key={preset.id}
                type="button"
                className={datePreset === preset.id ? 'preset-chip is-active' : 'preset-chip'}
                onClick={() => applyPreset(preset.id)}
              >
                {preset.label}
              </button>
            ))}
          </div>

          <div className="reports-datetime-inputs">
            <label className="business-field">
              <span>Start date & time</span>
              <input
                max={endDateTimeIso || undefined}
                type="datetime-local"
                value={startDateTimeIso}
                onChange={(e) => {
                  setStartDateTimeIso(e.target.value);
                  setDatePreset('CUSTOM');
                }}
              />
            </label>

            <label className="business-field">
              <span>End date & time</span>
              <input
                min={startDateTimeIso || undefined}
                type="datetime-local"
                value={endDateTimeIso}
                onChange={(e) => {
                  setEndDateTimeIso(e.target.value);
                  setDatePreset('CUSTOM');
                }}
              />
            </label>

            <label className="business-field">
              <span>Aggregation granularity</span>
              <select value={granularity} onChange={(e) => setGranularity(e.target.value as ReportGranularity)}>
                <option value="HOURLY">Hourly</option>
                <option value="DAILY">Daily</option>
                <option value="WEEKLY">Weekly</option>
                <option value="MONTHLY">Monthly</option>
                <option value="YEARLY">Yearly</option>
              </select>
            </label>
          </div>
          {rangeError ? <p className="business-dialog-error" role="alert">{rangeError}</p> : null}
        </div>
      </section>

      <div className="reports-toolbar">
        <label className="reports-search">
          <span>Search reports</span>
          <span className="access-search-control">
            <Icon name="search" />
            <input
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Name, audience, or domain"
              type="search"
              value={search}
            />
          </span>
        </label>
        <label>
          <span>Default format</span>
          <select onChange={(event) => setFormat(event.target.value as ReportExportFormat)} value={format}>
            {FORMATS.map((item) => (
              <option key={item.id} value={item.id}>{item.label}</option>
            ))}
          </select>
        </label>
      </div>

      <nav aria-label="Report categories" className="reports-categories">
        <button
          className={category === 'ALL' ? 'reports-category is-active' : 'reports-category'}
          onClick={() => setCategory('ALL')}
          type="button"
        >
          <strong>All</strong>
          <small>{counts.total}</small>
        </button>
        {REPORT_CATEGORIES.map((item) => (
          <button
            className={category === item.id ? 'reports-category is-active' : 'reports-category'}
            key={item.id}
            onClick={() => setCategory(item.id)}
            type="button"
          >
            <span><Icon name={item.icon} /></span>
            <strong>{item.label}</strong>
            <small>{counts.byCategory.get(item.id) ?? 0}</small>
          </button>
        ))}
      </nav>

      {error ? <p className="inline-alert" role="alert"><Icon name="alert" /> {error}</p> : null}

      <div className="reports-layout">
        <article className="panel reports-list-panel">
          <header className="panel-header access-panel-header">
            <div>
              <p className="eyebrow">Catalogue</p>
              <h2>
                {category === 'ALL'
                  ? 'All report packs'
                  : REPORT_CATEGORIES.find((item) => item.id === category)?.label}
              </h2>
            </div>
            <span className="panel-meta">
              {filtered.length} pack{filtered.length === 1 ? '' : 's'}
            </span>
          </header>

          {pageItems.length === 0 ? (
            <p className="muted-cell">No reports match this search and filter.</p>
          ) : (
            <div className="table-scroll">
              <table className="access-compact-table reports-table">
                <thead>
                  <tr>
                    <th>Report</th>
                    <th>Audience</th>
                    <th>Cadence</th>
                    <th>Signal</th>
                    <th className="reports-download-header">Download export</th>
                  </tr>
                </thead>
                <tbody>
                  {pageItems.map((report) => {
                    const metric = report.metricLabel ? summary.get(report.metricLabel) : undefined;
                    const active = selected?.id === report.id;
                    return (
                      <tr
                        className={active ? 'is-clickable is-selected' : 'is-clickable'}
                        key={report.id}
                        onClick={() => setSelectedId(report.id)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault();
                            setSelectedId(report.id);
                          }
                        }}
                        role="button"
                        tabIndex={0}
                      >
                        <td>
                          <strong>{report.name}</strong>
                          <small className="muted-cell">{report.description}</small>
                        </td>
                        <td><small>{report.audience}</small></td>
                        <td><small className="muted-cell">{report.cadence}</small></td>
                        <td>
                          {metric != null
                            ? <strong>{new Intl.NumberFormat('en-KE').format(metric)}</strong>
                            : <span className="muted-cell">—</span>}
                        </td>
                        <td className="reports-download-cell">
                          <div className="reports-download-menu" onClick={(event) => event.stopPropagation()}>
                            <select
                              aria-label={`Export format for ${report.name}`}
                              className="reports-download-select"
                              disabled={Boolean(busyId) || Boolean(rangeError)}
                              onChange={(event) => {
                                const val = event.target.value as ReportExportFormat;
                                if (val) {
                                  void download(report, val);
                                  event.target.value = '';
                                }
                              }}
                              value=""
                            >
                              <option value="" disabled>
                                {busyId.startsWith(`${report.id}:`) ? 'Downloading…' : '📥 Export as…'}
                              </option>
                              <option value="pdf">📄 PDF Document (.pdf)</option>
                              <option value="csv">📊 CSV Data (.csv)</option>
                              <option value="xlsx">📈 Excel Workbook (.xlsx)</option>
                              <option value="json">⚙️ JSON Format (.json)</option>
                            </select>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          <footer className="access-pager">
            <span className="muted-cell">Page {safePage} of {pageCount}</span>
            <div className="access-action-row">
              <button className="secondary-button" disabled={safePage <= 1} onClick={() => setPage((c) => Math.max(1, c - 1))} type="button">Previous</button>
              <button className="secondary-button" disabled={safePage >= pageCount} onClick={() => setPage((c) => c + 1)} type="button">Next</button>
            </div>
          </footer>
        </article>

        <aside className="panel reports-detail-panel">
          <header className="panel-header access-panel-header">
            <div>
              <p className="eyebrow">Pack particulars</p>
              <h2>{selected ? selected.name : 'Select a report'}</h2>
            </div>
          </header>

          {selected ? (
            <>
              <dl className="clinical-particulars">
                <div>
                  <dt>Category</dt>
                  <dd>{REPORT_CATEGORIES.find((item) => item.id === selected.category)?.label}</dd>
                </div>
                <div>
                  <dt>Description</dt>
                  <dd>{selected.description}</dd>
                </div>
                <div>
                  <dt>Audience</dt>
                  <dd>{selected.audience}</dd>
                </div>
                <div>
                  <dt>Cadence</dt>
                  <dd>{selected.cadence}</dd>
                </div>
                <div>
                  <dt>Reporting window</dt>
                  <dd>
                    <strong>
                      {startDateTimeIso ? new Date(startDateTimeIso).toLocaleString('en-KE', { dateStyle: 'medium', timeStyle: 'short' }) : 'Start'}
                      {' to '}
                      {endDateTimeIso ? new Date(endDateTimeIso).toLocaleString('en-KE', { dateStyle: 'medium', timeStyle: 'short' }) : 'End'}
                    </strong>
                    <br />
                    <small className="muted-cell">Granularity: {granularity}</small>
                  </dd>
                </div>
                <div>
                  <dt>Export formats</dt>
                  <dd>PDF · CSV · Excel · JSON — each with unique validation QR / receipt</dd>
                </div>
              </dl>

              <div className="reports-download-panel">
                <p className="eyebrow">Issue download</p>
                <div className="reports-download-row">
                  {FORMATS.map((item) => (
                    <button
                      className={item.id === format ? 'primary-button' : 'secondary-button'}
                      disabled={Boolean(busyId) || Boolean(rangeError)}
                      key={item.id}
                      onClick={() => {
                        setFormat(item.id);
                        void download(selected, item.id);
                      }}
                      type="button"
                    >
                      {busyId === `${selected.id}:${item.id}` ? 'Preparing…' : `Download ${item.label}`}
                    </button>
                  ))}
                </div>
                {selected.href ? (
                  <button
                    className="ghost-button"
                    onClick={() => {
                      const view = selected.href!.slice(1).split('/')[0] ?? '';
                      window.location.hash = selected.href!.slice(1);
                      if (view) onNavigate(view as WorkspaceView);
                    }}
                    type="button"
                  >
                    Open linked workspace
                  </button>
                ) : null}
              </div>
            </>
          ) : (
            <p className="muted-cell">Choose a report pack to inspect particulars and issue a signed download.</p>
          )}

          {receipt ? (
            <section className="reports-receipt">
              <p className="eyebrow">Latest download receipt</p>
              <dl className="clinical-particulars">
                <div><dt>File</dt><dd><code>{receipt.filename}</code></dd></div>
                <div><dt>Receipt ID</dt><dd><code>{receipt.receiptId}</code></dd></div>
                <div><dt>Validation code</dt><dd><code>{receipt.validationCode}</code></dd></div>
                <div><dt>Integrity</dt><dd><code>{receipt.checksumSha256}</code></dd></div>
                <div>
                  <dt>Validate</dt>
                  <dd>
                    {receipt.validationUrl
                      ? <a href={receipt.validationUrl} rel="noreferrer" target="_blank">{receipt.validationUrl}</a>
                      : '—'}
                  </dd>
                </div>
                {validation ? (
                  <div>
                    <dt>Server check</dt>
                    <dd>
                      {String(validation.valid) === 'true' ? 'Valid' : 'Invalid'}
                      {' · '}
                      {String(validation.downloaded_by || '')}
                      {' · '}
                      {String(validation.terminal_label || validation.terminal_id || '')}
                      {' · '}
                      {String(validation.downloaded_at || '')}
                    </dd>
                  </div>
                ) : null}
              </dl>
              <p className="muted-cell">
                The PDF embeds a scannable QR encoding the same validation payload for offline verification.
              </p>
            </section>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
