import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { loadGovernmentCatalogue, loadLegacySetup, saveLegacySetupReview } from './api.js';
import type { GovernmentCatalogueMedicine } from './api.js';
import type { LegacySetupItem, LegacySetupPage, LegacySetupReview } from './api.js';
import './legacyItemSetup.css';
import { LegacySetupCompletion } from './LegacySetupCompletion.js';

const labels: Record<string, string> = { AWAITING_MANAGER: 'Awaiting manager', IN_PROGRESS: 'In progress', DETAILS_COMPLETE: 'Details complete', EXCLUDED: 'Excluded' };

export function LegacyItemSetup({ csrfToken, tenantId = '' }: { readonly csrfToken: string; readonly tenantId?: string }) {
  const [data, setData] = useState<LegacySetupPage | null>(null);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [stock, setStock] = useState('positive');
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [selected, setSelected] = useState<LegacySetupItem | null>(null);
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(false);
  const [completionItem, setCompletionItem] = useState<LegacySetupItem | null>(null);

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
      loadLegacySetup(query, stock, page, controller.signal).then((value) => {
        if (!controller.signal.aborted) setData(value);
      }).catch((err: unknown) => {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Could not load initial setup.');
      }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 200);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [query, stock, page, refresh]);

  if (!data && !error) return <article className="panel legacy-setup"><p>Loading initial item setup…</p></article>;
  if (!error && data?.summary.total === 0) return null;
  return <article className="panel legacy-setup" id="catalogue-initial-setup">
    <header className="legacy-heading"><div><p className="eyebrow">Initial catalogue & stock setup</p><h2>Complete imported item details</h2></div>
      <span className="status-badge status-warning">Setup only · not saleable stock</span></header>
    <p className="legacy-explainer">Imported names, prices and balances are preserved as reported on {data?.source_date ?? 'the source date'}. Confirm today’s sales unit, price and physical count. Add actual batches and expiry dates for medicines. Saving details does not activate a SKU, publish a price or release stock.</p>
    {data && <div className="legacy-stats" aria-label="Initial setup progress">
      <div><strong>{data.summary.total}</strong><span>Imported items</span></div><div><strong>{data.summary.positive_stock}</strong><span>Positive source balances</span></div>
      <div><strong>{data.summary.negative_stock}</strong><span>Negative balances to recount</span></div><div><strong>{data.summary.details_complete}</strong><span>Details complete for catalogue review</span></div>
    </div>}
    <div className="legacy-tools"><label>Find an item<input type="search" value={query} placeholder="Name or legacy code" onChange={(e) => { setQuery(e.target.value); setPage(1); }} /></label>
      <label>Source balance<select value={stock} onChange={(e) => { setStock(e.target.value); setPage(1); }}><option value="positive">Positive stock first</option><option value="">All items</option><option value="negative">Negative balances</option></select></label>
      <button type="button" className="secondary-button" disabled={loading} onClick={() => setRefresh((r) => r + 1)}>Refresh</button></div>
    {error && <p role="alert" className="legacy-error">{error}</p>}{notice && <p role="status" className="legacy-notice">{notice}</p>}
    {!data?.can_edit && data && <p className="legacy-explainer">Read-only. A tenant administrator with inventory management access can complete these details.</p>}
    {data && <><div className="table-scroll" aria-busy={loading}><table><thead><tr><th>Item / source code</th><th>Source unit</th><th>Source quantity</th><th>Cost / selling price (KES)</th><th>Setup status</th><th>Action</th></tr></thead><tbody>
      {data.results.map((item) => <tr key={item.id}><td><strong>{item.source_name}</strong><small className="legacy-code">Legacy: {item.legacy_code || 'missing'} · Proposed: {item.proposed_sku_code}</small></td>
        <td>{item.source_uom || 'Not supplied'}</td><td>{item.source_quantity}</td><td>{item.source_cost} / {item.source_price}</td>
        <td><span className="status-badge status-warning">{item.completion?.phase || labels[item.status] || item.status}</span><small className="legacy-code">{item.completion?.sku_code || (item.source_issues.length ? `${item.source_issues.length} source issue(s)` : 'Awaiting confirmation')}</small></td>
        <td>{!item.completion?.phase && <button type="button" className="secondary-button" disabled={!data.can_edit || loading} onClick={() => { setSelected(item); setNotice(''); }}>Complete details</button>}
          {(item.status === 'DETAILS_COMPLETE' && !item.completion?.phase || item.completion?.phase === 'QUARANTINED') && <button type="button" className="secondary-button" disabled={!data.can_edit || loading} onClick={() => { setSelected(null); setCompletionItem(item); }}>{item.completion?.phase === 'QUARANTINED' ? 'Independent release' : 'Stage opening setup'}</button>}
          {item.completion?.price_version_id && <small className="legacy-code">Linked price version: {item.completion.price_version_id}. Review and publish in Pricing.</small>}
        </td></tr>)}
      {data.results.length === 0 && <tr><td colSpan={6}>No items match this search.</td></tr>}
    </tbody></table></div><div className="legacy-pagination"><span>{data.count} matching items · Page {data.page} of {data.pages}{loading ? ' · Loading…' : ''}</span>
      <div><button type="button" className="secondary-button" disabled={loading || data.page <= 1} onClick={() => setPage(data.page - 1)}>Previous</button> <button type="button" className="secondary-button" disabled={loading || data.page >= data.pages} onClick={() => setPage(data.page + 1)}>Next</button></div></div></>}
    {selected && <ItemDetails key={selected.id} item={selected} csrfToken={csrfToken} onCancel={() => setSelected(null)} onSaved={(item) => {
      setSelected(null); setNotice(`${item.source_name}: details saved. ${item.missing_details.length ? `Still needed: ${item.missing_details.join('; ')}.` : 'Ready for governed catalogue review, not yet saleable.'}`); setRefresh((r) => r + 1);
    }} />}
    {completionItem && <LegacySetupCompletion key={completionItem.id} item={completionItem} csrfToken={csrfToken} tenantId={tenantId} onClose={() => setCompletionItem(null)} onSaved={() => { setCompletionItem(null); setRefresh((current) => current + 1); setNotice('Governed setup step recorded. Price approval/publication and independent quality release remain separate decisions.'); }} />}
  </article>;
}

function ItemDetails({ item, csrfToken, onCancel, onSaved }: { readonly item: LegacySetupItem; readonly csrfToken: string; readonly onCancel: () => void; readonly onSaved: (item: LegacySetupItem) => void }) {
  const [review, setReview] = useState<LegacySetupReview>(item.review);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const edit = (key: keyof LegacySetupReview, value: string) => setReview((r) => ({ ...r, [key]: value }));
  const batches = review.batches ?? [];
  const save = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('');
    const payload = { ...review, confirmed_price: review.confirmed_price || null, confirmed_cost: review.confirmed_cost || null,
      counted_quantity: review.counted_quantity || null, counted_on: review.counted_on || null };
    try { onSaved(await saveLegacySetupReview(item, payload, csrfToken)); }
    catch (err: unknown) { setError(err instanceof Error ? err.message : 'Could not save details.'); }
    finally { setBusy(false); }
  };
  return <section className="legacy-detail" aria-labelledby="legacy-item-title"><header className="legacy-heading"><div><p className="eyebrow">Manager confirmation</p><h3 id="legacy-item-title" tabIndex={-1}>{item.source_name}</h3></div><button type="button" className="secondary-button" disabled={busy} onClick={onCancel}>Close</button></header>
    <p>Source: Products.pdf page {item.source_product.page}; stock PDF page {item.source_stock.page}. Original values remain unchanged. The proposed item code is an internal reference, not a barcode.</p>
    {item.source_issues.length > 0 && <ul className="legacy-issues">{item.source_issues.map((issue) => <li key={issue}>{issue}</li>)}</ul>}
    <form onSubmit={(e) => { void save(e); }}><fieldset disabled={busy}><p><button type="button" className="secondary-button" onClick={() => setReview((r) => ({ ...r, confirmed_price: item.source_price, confirmed_cost: item.source_cost }))}>Confirm source cost and price</button> Only use these values after confirming the sales unit.</p><div className="legacy-fields">
      <label>Item type<select value={review.item_kind ?? ''} onChange={(e) => edit('item_kind', e.target.value)}><option value="">Needs confirmation</option><option value="MEDICINE">Medicine</option><option value="SUPPLY">Supply / other merchandise</option><option value="SERVICE">Service</option></select></label>
      <label>Confirmed sales unit<input value={review.sales_unit ?? ''} placeholder="e.g. tablet, strip, box, bottle" maxLength={80} onChange={(e) => edit('sales_unit', e.target.value)} /></label>
      <label>Pack description / unit conversion<input value={review.pack_description ?? ''} placeholder="e.g. box of 100 tablets, sold per tablet" maxLength={255} onChange={(e) => edit('pack_description', e.target.value)} /></label>
      <label>Confirmed selling price (KES per sales unit)<input type="number" min="0" step="0.0001" value={review.confirmed_price ?? ''} placeholder={`Source: ${item.source_price}`} onChange={(e) => edit('confirmed_price', e.target.value)} /></label>
      <label>Confirmed cost (KES per sales unit)<input type="number" min="0" step="0.0001" value={review.confirmed_cost ?? ''} placeholder={`Source: ${item.source_cost}`} onChange={(e) => edit('confirmed_cost', e.target.value)} /></label>
      <label>Tax treatment<select value={review.tax_category ?? ''} onChange={(e) => edit('tax_category', e.target.value)}><option value="">Needs confirmation</option><option value="STANDARD">Standard rated</option><option value="ZERO_RATED">Zero rated</option><option value="EXEMPT">Exempt</option></select></label>
      <label>Current physical count (sales units)<input type="number" min="0" step="0.0001" value={review.counted_quantity ?? ''} placeholder={`Source: ${item.source_quantity}`} onChange={(e) => edit('counted_quantity', e.target.value)} /></label>
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
    </fieldset></form></section>;
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
