import { IntakeModal } from './IntakeModal.js';
import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { createPortal } from 'react-dom';
import { downloadOpeningStocktakeTemplate, loadGovernmentCatalogue, loadLegacySetup, saveLegacySetupReview } from './api.js';
import type { GovernmentCatalogueMedicine } from './api.js';
import type { LegacySetupItem, LegacySetupPage, LegacySetupReview } from './api.js';
import './legacyItemSetup.css';
import { LegacySetupCompletion } from './LegacySetupCompletion.js';
import { CountSheetUpload } from './CountSheetUpload.js';
import { TenantItemUploadDialog } from './TenantItemUploadDialog.js';

const labels: Record<string, string> = { AWAITING_MANAGER: 'Awaiting manager', IN_PROGRESS: 'In progress', DETAILS_COMPLETE: 'Details complete', EXCLUDED: 'Excluded' };

export function LegacyItemSetup({ csrfToken, tenantId = '' }: { readonly csrfToken: string; readonly tenantId?: string }) {
  const [data, setData] = useState<LegacySetupPage | null>(null);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [stock, setStock] = useState('');
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [selected, setSelected] = useState<LegacySetupItem | null>(null);
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(false);
  const [completionItem, setCompletionItem] = useState<LegacySetupItem | null>(null);
  const [countUploadOpen, setCountUploadOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [importId, setImportId] = useState('');
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    if (selected) {
      const heading = document.getElementById('legacy-item-title');
      heading?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
      heading?.focus({ preventScroll: true });
    }
  }, [selected]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    const timer = window.setTimeout(() => {
      loadLegacySetup(query, stock, page, controller.signal, tenantId).then((value) => {
        if (!controller.signal.aborted) setData(value);
      }).catch((err: unknown) => {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Could not load initial setup.');
      }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 200);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [query, stock, page, refresh, tenantId]);

  const downloadStocktake = async () => {
    if (downloading) return;
    setDownloading(true); setError('');
    try { await downloadOpeningStocktakeTemplate(tenantId, importId); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not download the stock-take sheet.'); }
    finally { setDownloading(false); }
  };

  if (!data && !error) return <article className="panel legacy-setup"><p>Loading initial item setup…</p></article>;
  return <article className="panel legacy-setup" id="catalogue-initial-setup">
    <header className="legacy-heading"><div><p className="eyebrow">Initial catalogue & stock setup</p><h2>Upload items & prepare stock take</h2></div>
      <button className="primary-button" type="button" disabled={!data?.can_edit || loading} onClick={() => setUploadOpen(true)}>Upload item list</button></header>
    <ol className="item-onboarding-steps" aria-label="Item onboarding workflow"><li><strong>Upload item list</strong><span>Names, codes, units and optional source prices.</span></li><li><strong>Download & count</strong><span>A populated sheet with blank physical-count fields.</span></li><li><strong>Review opening setup</strong><span>Confirm units, batches and prices before trading.</span></li></ol>
    <p className="legacy-explainer">Upload your existing item CSV first. Then download an opening stock-take sheet, count what is on the shelves and upload the completed count sheet or enter verified counts through Complete details. Medicine stock needs actual batches and expiry dates. Catalogue mapping, price publication and stock release follow review.</p>
    <span className="status-badge status-warning">Setup only · not saleable stock</span>
    {data && data.summary.total > 0 ? <div className="item-onboarding-download">
      <div><strong>Opening stock-take sheet</strong><small>Includes all eligible items in the selected source, with counts left blank. Completed or excluded setup items are omitted.</small></div>
      <label><span>Item source</span><select value={importId} onChange={(event) => setImportId(event.target.value)} disabled={downloading}><option value="">All imported items</option>{data.imports?.map((batch) => <option key={batch.id} value={batch.id}>{batch.source_filename || batch.code} · {batch.source_date} · {batch.item_count} items</option>)}</select></label>
      <button className="secondary-button" type="button" disabled={!data.can_edit || downloading || loading} onClick={() => void downloadStocktake()}>{downloading ? 'Preparing sheet…' : 'Download stock-take sheet'}</button>
      <button className="secondary-button" type="button" disabled={!data.can_edit || loading} onClick={() => setCountUploadOpen(true)}>Upload completed count sheet</button>
    </div> : null}
    {data && data.summary.total > 0 ? <div className="legacy-stats" aria-label="Initial setup progress">
      <div><strong>{data.summary.total}</strong><span>Imported items</span></div><div><strong>{data.summary.positive_stock}</strong><span>Positive source balances</span></div>
      <div><strong>{data.summary.negative_stock}</strong><span>Negative balances to recount</span></div><div><strong>{data.summary.details_complete}</strong><span>Details complete for catalogue review</span></div>
    </div> : null}
    {data && data.summary.total > 0 ? <div className="legacy-tools"><label>Find an item<input type="search" value={query} placeholder="Name or legacy code" onChange={(e) => { setQuery(e.target.value); setPage(1); }} /></label>
      <label>Source balance<select value={stock} onChange={(e) => { setStock(e.target.value); setPage(1); }}><option value="">All items</option><option value="positive">Positive balances</option><option value="negative">Negative balances</option></select></label>
      <button type="button" className="secondary-button" disabled={loading} onClick={() => setRefresh((r) => r + 1)}>Refresh</button></div>
      : data ? <p className="item-onboarding-empty">No item list has been imported yet. Choose <strong>Upload item list</strong> to download the CSV template and get started.</p> : null}
    {error && <p role="alert" className="legacy-error">{error}</p>}{notice && <p role="status" className="legacy-notice">{notice}</p>}
    {!data?.can_edit && data && <p className="legacy-explainer">Read-only. A tenant administrator with inventory management access can complete these details.</p>}
    {data && data.summary.total > 0 && <><div className="table-scroll" aria-busy={loading}><table><thead><tr><th>Item / source code</th><th>Source unit</th><th>Source quantity</th><th>Cost / selling price (KES)</th><th>Setup status</th><th>Action</th></tr></thead><tbody>
      {data.results.map((item) => <tr key={item.id}><td><strong>{item.source_name}</strong><small className="legacy-code">Legacy: {item.legacy_code || 'missing'} · Proposed: {item.proposed_sku_code}</small></td>
        <td>{item.source_uom || 'Not supplied'}</td><td>{sourceValue(item, 'source_quantity', item.source_quantity)}</td><td>{sourceValue(item, 'cost_price', item.source_cost)} / {sourceValue(item, 'selling_price', item.source_price)}</td>
        <td><span className="status-badge status-warning">{item.completion?.phase || labels[item.status] || item.status}</span><small className="legacy-code">{item.completion?.sku_code || (item.source_issues.length ? `${item.source_issues.length} source issue(s)` : 'Awaiting confirmation')}</small></td>
        <td>{!item.completion?.phase && <button type="button" className="secondary-button" disabled={!data.can_edit || loading} onClick={() => { setSelected(item); setNotice(''); }}>Complete details</button>}
          {(item.status === 'DETAILS_COMPLETE' && !item.completion?.phase || item.completion?.phase === 'QUARANTINED') && <button type="button" className="secondary-button" disabled={!data.can_edit || loading} onClick={() => { setSelected(null); setCompletionItem(item); }}>{item.completion?.phase === 'QUARANTINED' ? 'Independent release' : 'Stage opening setup'}</button>}
          {item.completion?.price_version_id && <small className="legacy-code">Linked price version: {item.completion.price_version_id}. Review and publish in Pricing.</small>}
        </td></tr>)}
      {data.results.length === 0 && <tr><td colSpan={6}>No items match this search.</td></tr>}
    </tbody></table></div><div className="legacy-pagination"><span>{data.count} matching items · Page {data.page} of {data.pages}{loading ? ' · Loading…' : ''}</span>
      <div><button type="button" className="secondary-button" disabled={loading || data.page <= 1} onClick={() => setPage(data.page - 1)}>Previous</button> <button type="button" className="secondary-button" disabled={loading || data.page >= data.pages} onClick={() => setPage(data.page + 1)}>Next</button></div></div></>}
    {countUploadOpen && <CountSheetUpload opening path="/api/medicines/initial-setup/stocktake-upload/" csrfToken={csrfToken} tenantId={tenantId} onClose={() => setCountUploadOpen(false)} onSaved={() => { setCountUploadOpen(false); setRefresh((value) => value + 1); setNotice('Physical counts saved. Complete manager details, product mapping, prices and independent release next.'); }} />}
    {uploadOpen && createPortal(<TenantItemUploadDialog csrfToken={csrfToken} tenantId={tenantId} onClose={() => setUploadOpen(false)} onImported={(result) => {
      setImportId(result.import_id ?? ''); setQuery(''); setStock(''); setPage(1); setRefresh((current) => current + 1);
      setNotice(`${result.created} items imported; ${result.existing} existing items retained. Download the stock-take sheet for a current physical count.`);
    }} />, document.body)}
    {selected && createPortal(<ItemDetails key={selected.id} item={selected} csrfToken={csrfToken} tenantId={tenantId} onCancel={() => setSelected(null)} onSaved={(item) => {
      setSelected(null); setNotice(`${item.source_name}: details saved. ${item.missing_details.length ? `Still needed: ${item.missing_details.join('; ')}.` : 'Ready for governed catalogue review, not yet saleable.'}`); setRefresh((r) => r + 1);
    }} />, document.body)}
    {completionItem && createPortal(<LegacySetupCompletion key={completionItem.id} item={completionItem} csrfToken={csrfToken} tenantId={tenantId} onClose={() => setCompletionItem(null)} onSaved={() => { setCompletionItem(null); setRefresh((current) => current + 1); setNotice('Governed setup step recorded. Price approval/publication and independent quality release remain separate decisions.'); }} />, document.body)}
  </article>;
}

function sourceValue(item: LegacySetupItem, field: string, fallback: string): string {
  const uploaded = item.source_product.upload_canonical;
  return uploaded && uploaded[field] == null ? 'Not supplied' : fallback;
}

function ItemDetails({ item, csrfToken, tenantId, onCancel, onSaved }: { readonly item: LegacySetupItem; readonly csrfToken: string; readonly tenantId: string; readonly onCancel: () => void; readonly onSaved: (item: LegacySetupItem) => void }) {
  const [review, setReview] = useState<LegacySetupReview>(() => {
    const source = item.source_product.upload_canonical;
    return source ? { item_kind: source.item_kind ?? '', sales_unit: item.source_uom,
      pack_description: source.pack_description ?? '', tax_category: source.tax_category ?? '',
      barcode: source.barcode ?? '', master_catalogue_code: source.master_catalogue_code ?? '', ...item.review } : item.review;
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const edit = (key: keyof LegacySetupReview, value: string) => setReview((r) => ({ ...r, [key]: value }));
  const batches = review.batches ?? [];
  const save = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('');
    const payload = { ...review, confirmed_price: review.confirmed_price || null, confirmed_cost: review.confirmed_cost || null,
      counted_quantity: review.counted_quantity || null, counted_on: review.counted_on || null };
    try { onSaved(await saveLegacySetupReview(item, payload, csrfToken, tenantId)); }
    catch (err: unknown) { setError(err instanceof Error ? err.message : 'Could not save details.'); }
    finally { setBusy(false); }
  };
  return <IntakeModal title={`Complete item details — ${item.source_name}`} busy={busy} onClose={onCancel}><section className="legacy-detail" aria-labelledby="legacy-item-title"><header className="legacy-heading"><div><p className="eyebrow">Manager confirmation</p><h3 id="legacy-item-title" tabIndex={-1}>{item.source_name}</h3></div><button type="button" className="secondary-button" disabled={busy} onClick={onCancel}>Close</button></header>
    <p>Source: {item.source_product.filename || item.source_product.file || 'Product source'}{item.source_product.page ? ` · page ${item.source_product.page}` : ''}{item.source_product.source_row ? ` · row ${item.source_product.source_row}` : ''}{item.source_stock.page ? `; stock source page ${item.source_stock.page}` : ''}{item.source_date ? ` · ${item.source_date}` : ''}. Original values remain unchanged. The proposed item code is an internal reference, not a barcode.</p>
    {item.source_product.upload_canonical ? <p>Uploaded fields are shown as suggestions. Check them against the actual pack and sales unit before saving this review.</p> : null}
    {item.source_issues.length > 0 && <ul className="legacy-issues">{item.source_issues.map((issue) => <li key={issue}>{issue}</li>)}</ul>}
    <form onSubmit={(e) => { void save(e); }}><fieldset disabled={busy}><p><button type="button" className="secondary-button" disabled={sourceValue(item, 'selling_price', item.source_price) === 'Not supplied' && sourceValue(item, 'cost_price', item.source_cost) === 'Not supplied'} onClick={() => setReview((r) => ({ ...r,
      ...(sourceValue(item, 'selling_price', item.source_price) !== 'Not supplied' ? { confirmed_price: item.source_price } : {}),
      ...(sourceValue(item, 'cost_price', item.source_cost) !== 'Not supplied' ? { confirmed_cost: item.source_cost } : {}),
    }))}>Confirm source cost and price</button> Only use supplied values after confirming the sales unit.</p><div className="legacy-fields">
      <label>Item type<select value={review.item_kind ?? ''} onChange={(e) => edit('item_kind', e.target.value)}><option value="">Needs confirmation</option><option value="MEDICINE">Medicine</option><option value="SUPPLY">Supply / other merchandise</option><option value="SERVICE">Service</option></select></label>
      <label>Confirmed sales unit<input value={review.sales_unit ?? ''} placeholder="e.g. tablet, strip, box, bottle" maxLength={80} onChange={(e) => edit('sales_unit', e.target.value)} /></label>
      <label>Pack description / unit conversion<input value={review.pack_description ?? ''} placeholder="e.g. box of 100 tablets, sold per tablet" maxLength={255} onChange={(e) => edit('pack_description', e.target.value)} /></label>
      <label>Confirmed selling price (KES per sales unit)<input type="number" min="0" step="0.0001" value={review.confirmed_price ?? ''} placeholder={`Source: ${sourceValue(item, 'selling_price', item.source_price)}`} onChange={(e) => edit('confirmed_price', e.target.value)} /></label>
      <label>Confirmed cost (KES per sales unit)<input type="number" min="0" step="0.0001" value={review.confirmed_cost ?? ''} placeholder={`Source: ${sourceValue(item, 'cost_price', item.source_cost)}`} onChange={(e) => edit('confirmed_cost', e.target.value)} /></label>
      <label>Tax treatment<select value={review.tax_category ?? ''} onChange={(e) => edit('tax_category', e.target.value)}><option value="">Needs confirmation</option><option value="STANDARD">Standard rated</option><option value="ZERO_RATED">Zero rated</option><option value="EXEMPT">Exempt</option></select></label>
      <label>Current physical count (sales units)<input type="number" min="0" step="0.0001" value={review.counted_quantity ?? ''} placeholder="Enter today’s observed quantity" onChange={(e) => edit('counted_quantity', e.target.value)} /></label>
      <label>Physical count date<input type="date" value={review.counted_on ?? ''} onChange={(e) => edit('counted_on', e.target.value)} /></label>
      <label>Reviewed national medicine code<input value={review.master_catalogue_code ?? ''} placeholder="Confirm exact product in national catalogue" maxLength={120} onChange={(e) => edit('master_catalogue_code', e.target.value)} /><small>For medicines. A similar name alone is not a confirmed match.</small></label>
      <label>Actual manufacturer barcode (optional)<input value={review.barcode ?? ''} maxLength={100} onChange={(e) => edit('barcode', e.target.value)} /><small>Leave blank if none. Name and internal code lookup can be used after activation.</small></label>
    </div><ReferenceSearch sourceName={item.source_name} onChoose={(code) => edit('master_catalogue_code', code)} /><div className="legacy-batches"><h4>Actual opening-stock batches</h4><p>Split the physical count by batch. Quantities are in the confirmed sales unit. Do not copy a guessed batch number or expiry.</p>
      {batches.map((batch, index) => <div className="legacy-batch" key={index}>
        <label>Batch number<input required maxLength={120} value={batch.batch_number} onChange={(e) => setReview((r) => ({ ...r, batches: batches.map((b, i) => i === index ? { ...b, batch_number: e.target.value } : b) }))} /></label>
        <label>Expiry date<input required type="date" value={batch.expiry_date} onChange={(e) => setReview((r) => ({ ...r, batches: batches.map((b, i) => i === index ? { ...b, expiry_date: e.target.value } : b) }))} /></label>
        <label>Quantity<input required type="number" min="0.0001" step="0.0001" value={batch.quantity} onChange={(e) => setReview((r) => ({ ...r, batches: batches.map((b, i) => i === index ? { ...b, quantity: e.target.value } : b) }))} /></label>
        <button type="button" className="secondary-button" aria-label={`Remove batch ${index + 1}`} onClick={() => setReview((r) => ({ ...r, batches: batches.filter((_, i) => i !== index) }))}>Remove</button></div>)}
      <button type="button" className="secondary-button" onClick={() => setReview((r) => ({ ...r, batches: [...batches, { batch_number: '', expiry_date: '', quantity: '' }] }))}>Add batch</button>
    </div><label className="legacy-notes">Manager notes<textarea rows={3} maxLength={4000} value={review.notes ?? ''} onChange={(e) => edit('notes', e.target.value)} /></label>
      <label className="legacy-exclude"><input type="checkbox" checked={review.excluded ?? false} onChange={(e) => setReview((r) => ({ ...r, excluded: e.target.checked }))} />Exclude from initial setup (source record retained)</label>
      {error && <p role="alert" className="legacy-error">{error}</p>}<footer className="legacy-actions"><button className="secondary-button" type="button" onClick={onCancel}>Cancel</button><button className="primary-button" type="submit">{busy ? 'Saving…' : 'Save setup details'}</button></footer>
    </fieldset></form></section></IntakeModal>;
}

function ReferenceSearch({ sourceName, onChoose }: { readonly sourceName: string; readonly onChoose: (code: string) => void }) {
  const [query, setQuery] = useState(sourceName.split(/\s+/)[0] ?? '');
  const [rows, setRows] = useState<readonly GovernmentCatalogueMedicine[] | null>(null);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const find = async () => {
    if (!query.trim()) return;
    setBusy(true); setError('');
    try { const page = await loadGovernmentCatalogue({ query, pageSize: 25 }); setRows(page.results); setTotal(page.count); }
    catch (err: unknown) { setError(err instanceof Error ? err.message : 'Could not search the national catalogue.'); }
    finally { setBusy(false); }
  };
  return <div className="legacy-reference"><h4>Find a national reference</h4><p>Search by brand, generic name or exact eTCD code. Compare strength, form and manufacturer against the actual pack. These are reference candidates, not proof of licence status or automatic product matches.</p>
    <div className="legacy-tools"><label>Reference search<input type="search" value={query} onChange={(e) => setQuery(e.target.value)} /></label><button type="button" className="secondary-button" disabled={busy || !query.trim()} onClick={() => { void find(); }}>{busy ? 'Searching…' : 'Search references'}</button></div>
    {error && <p role="alert" className="legacy-error">{error}</p>}{rows && <><p>{total} reference candidate(s). {total > rows.length ? 'First 25 shown; narrow the search.' : ''}</p><div className="table-scroll"><table><thead><tr><th>Reference</th><th>Generic / brand</th><th>Strength / form</th><th>Manufacturer</th><th>Action</th></tr></thead><tbody>{rows.map((r) => <tr key={r.id}><td>{r.code}</td><td>{r.generic_name}<small className="legacy-code">{r.brand_name}</small></td><td>{r.strength} · {r.dosage_form}</td><td>{r.manufacturer_name || 'Not supplied'}</td><td><button type="button" className="secondary-button" onClick={() => onChoose(r.code)}>Set reference for review</button></td></tr>)}</tbody></table></div></>}
  </div>;
}
