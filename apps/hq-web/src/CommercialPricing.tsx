import { useEffect, useState, type FormEvent } from 'react';
import { commandCommercialList, loadCommercialEntries, loadCommercialLists, loadCommercialPriceOptions, saveCommercialEntry, saveCommercialList } from './api.js';
import type { CommercialPriceEntry, CommercialPriceList, CommercialPriceOptions } from './api.js';
import './CommercialPricing.css';

export function CommercialPricing({ tenantId, csrfToken }: { readonly tenantId: string; readonly csrfToken: string }) {
  const [lists, setLists] = useState<readonly CommercialPriceList[]>([]);
  const [entries, setEntries] = useState<readonly CommercialPriceEntry[]>([]);
  const [options, setOptions] = useState<CommercialPriceOptions | null>(null);
  const [selectedId, setSelectedId] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [reason, setReason] = useState('');
  const [key, setKey] = useState(() => window.crypto.randomUUID());
  const [code, setCode] = useState(''); const [name, setName] = useState(''); const [from, setFrom] = useState(''); const [isDefault, setDefault] = useState(false);
  const [editId, setEditId] = useState(''); const [sku, setSku] = useState(''); const [price, setPrice] = useState(''); const [minimum, setMinimum] = useState('1');
  const [entryFrom, setEntryFrom] = useState(''); const [entryTo, setEntryTo] = useState(''); const [active, setActive] = useState(true);
  const resetEntry = () => { setEditId(''); setSku(''); setPrice(''); setMinimum('1'); setEntryFrom(''); setEntryTo(''); setActive(true); };
  useEffect(() => { setSelectedId(''); setLists([]); setEntries([]); setOptions(null); setNotice(''); setReason(''); setCode(''); setName(''); setFrom(''); setDefault(false); setSearch(''); resetEntry(); setKey(window.crypto.randomUUID()); }, [tenantId]);
  useEffect(() => { resetEntry(); setReason(''); setCode(''); setName(''); setFrom(''); setDefault(false); setKey(window.crypto.randomUUID()); }, [selectedId]);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError('');
    Promise.all([loadCommercialLists(tenantId, controller.signal), loadCommercialEntries(tenantId, controller.signal)])
      .then(([loadedLists, loadedEntries]) => { if (!controller.signal.aborted) { setLists(loadedLists); setEntries(loadedEntries); } })
      .catch((cause: unknown) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Commercial prices could not be loaded.'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [tenantId, refresh]);
  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      loadCommercialPriceOptions(tenantId, search, controller.signal)
        .then((loadedOptions) => { if (!controller.signal.aborted) setOptions(loadedOptions); })
        .catch((cause: unknown) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'SKU search could not be loaded.'); });
    }, search ? 250 : 0);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [tenantId, refresh, search]);
  const selected = lists.find((list) => list.id === selectedId);
  const editingEntry = entries.find((entry) => entry.id === editId);
  const execute = async (operation: () => Promise<unknown>) => {
    setBusy(true); setError(''); setNotice('');
    try { await operation(); setKey(window.crypto.randomUUID()); setRefresh((value) => value + 1); setNotice('Commercial pricing step recorded. Publication still requires current independent approval.'); }
    catch (cause: unknown) { setError(`${cause instanceof Error ? cause.message : 'Command failed.'} Refresh the record before retrying an uncertain result; the command key is retained.`); }
    finally { setBusy(false); }
  };
  const create = (event: FormEvent) => { event.preventDefault(); void execute(async () => {
    const payload = { code, name, effective_from: from, is_default: isDefault, reason, idempotency_key: key, change_reason: reason };
    const result = selected && selected.status !== 'DRAFT'
      ? await commandCommercialList(selected.id, 'new-draft', payload, tenantId, csrfToken)
      : await saveCommercialList({ ...payload, currency: 'KES' }, tenantId, csrfToken);
    setSelectedId(result.id);
  }); };
  const edit = (entry: CommercialPriceEntry) => { setEditId(entry.id); setSku(entry.sku); setPrice(entry.unit_price); setMinimum(entry.minimum_quantity); setEntryFrom(entry.effective_from); setEntryTo(entry.effective_to ?? ''); setActive(entry.is_active); };
  const review = (operation: string) => { if (selected) void execute(() => commandCommercialList(selected.id, 'govern', {
    operation, reason, idempotency_key: key, expected_content_hash: selected.governance.content_hash,
  }, tenantId, csrfToken)); };
  return <article className="panel commercial-pricing" aria-labelledby="b2b-pricing-title"><h2 id="b2b-pricing-title">Commercial B2B price lists</h2>
    <p className="panel-note">Separate from retail price books. Maintain drafts, record independent exact-content approval, then publish. Active prices cannot be edited or deleted; clone a new draft. Clones retain actual entry dates and require review. No missing price becomes a free item.</p>
    {error && <p role="alert" className="inline-alert">{error}</p>}{notice && <p role="status" className="inline-success">{notice}</p>}
    {loading && <p role="status">Loading commercial price records…</p>}
    {!options ? <p role="status">{error ? 'Commercial workspace unavailable.' : 'Loading commercial pricing…'}</p> : <fieldset disabled={busy || loading}>
      <label className="business-field">Commercial list<select value={selectedId} onChange={(event) => { setSelectedId(event.target.value); setEditId(''); }}><option value="">Choose list or create</option>{lists.map((list) => <option key={list.id} value={list.id}>{list.code} · {list.name} · {list.governance.state}</option>)}</select></label>
      <label className="business-field">Specific change/review reason<input required value={reason} onChange={(event) => setReason(event.target.value)} maxLength={1000} /></label>
      {selected && <><p>{selected.currency} · {selected.effective_from} to {selected.effective_to ?? 'open-ended'} · {selected.is_default ? 'Default' : 'Customer-assigned'} · {selected.governance.state}</p>
        <div className="table-wrap"><table><thead><tr><th>SKU</th><th>Unit price</th><th>Quantity break</th><th>Effective</th><th>Active</th><th>Action</th></tr></thead><tbody>{entries.filter((entry) => entry.price_list === selected.id).map((entry) => <tr key={entry.id}><td>{entry.sku_code} · {entry.sku_name}</td><td>{selected.currency} {entry.unit_price}</td><td>{entry.minimum_quantity}</td><td>{entry.effective_from} — {entry.effective_to ?? 'open-ended'}</td><td>{entry.is_active ? 'Yes' : 'No'}</td><td>{selected.status === 'DRAFT' && options.can_edit ? <button type="button" onClick={() => edit(entry)}>Edit draft entry</button> : 'Immutable'}</td></tr>)}</tbody></table></div>
        {selected.status === 'DRAFT' && <div className="button-row">
          {options.can_edit && <button type="button" disabled={!reason.trim()} onClick={() => review('submit')}>Submit exact draft</button>}
          {options.can_approve && selected.governance.state === 'SUBMITTED' && <><button type="button" disabled={!reason.trim()} onClick={() => review('approve')}>Independent approval</button><button type="button" disabled={!reason.trim()} onClick={() => review('reject')}>Reject draft</button></>}
          {options.can_publish && selected.governance.state === 'APPROVED' && <button type="button" disabled={!reason.trim()} onClick={() => review('publish')}>Publish approved prices</button>}
        </div>}
        {selected.status === 'ACTIVE' && options.can_publish && <button type="button" disabled={!reason.trim()} onClick={() => void execute(() => commandCommercialList(selected.id, 'archive', { reason }, tenantId, csrfToken))}>Archive list with reason</button>}
        {selected.status === 'DRAFT' && options.can_edit && <form onSubmit={(event) => { event.preventDefault(); void execute(() => saveCommercialEntry(editId, { price_list: selected.id, sku, unit_price: price, minimum_quantity: minimum, effective_from: entryFrom, effective_to: entryTo || null, is_active: active, change_reason: reason, idempotency_key: key }, tenantId, csrfToken)); }}>
          <h3>{editId ? 'Edit draft entry' : 'Add draft price'}</h3><div className="stocktake-form-grid">
            <label className="business-field">Find SKU<input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Code or item name" /></label>
            <label className="business-field">SKU<select required value={sku} onChange={(event) => setSku(event.target.value)}><option value="">Choose tenant SKU</option>{editingEntry && !options.skus.some((item) => item.id === editingEntry.sku) && <option value={editingEntry.sku}>{editingEntry.sku_code} · {editingEntry.sku_name} · existing draft entry</option>}{options.skus.map((item) => <option key={item.id} value={item.id}>{item.sku_code} · {item.display_name} · {item.sales_unit}</option>)}</select></label>
            <label className="business-field">Price in {selected.currency}<input required type="number" min="0.01" step="0.01" value={price} onChange={(event) => setPrice(event.target.value)} /></label>
            <label className="business-field">Minimum quantity<input required type="number" min="0.0001" step="0.0001" value={minimum} onChange={(event) => setMinimum(event.target.value)} /></label>
            <label className="business-field">Entry effective from<input required type="date" value={entryFrom} onChange={(event) => setEntryFrom(event.target.value)} /></label><label className="business-field">Entry effective to<input type="date" value={entryTo} onChange={(event) => setEntryTo(event.target.value)} /></label>
          </div><label><input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} /> Active draft entry</label>
          {options.more_skus && <p>First 1,000 matching SKUs shown. Narrow the search for other items.</p>}
          <button type="submit" disabled={!reason.trim()}>Save draft price</button><button type="button" onClick={resetEntry}>New entry</button>
        </form>}
      </>}
      {options.can_edit && <form onSubmit={create}><h3>{selected && selected.status !== 'DRAFT' ? 'Clone into a new draft' : 'Create commercial draft (KES)'}</h3><div className="stocktake-form-grid">
        <label className="business-field">Unique list code<input required value={code} onChange={(event) => setCode(event.target.value)} maxLength={64} /></label><label className="business-field">List name<input required value={name} onChange={(event) => setName(event.target.value)} maxLength={255} /></label><label className="business-field">Confirmed list start date<input required type="date" value={from} onChange={(event) => setFrom(event.target.value)} /></label>
      </div><label><input type="checkbox" checked={isDefault} onChange={(event) => setDefault(event.target.checked)} /> Use as tenant default after approved publication</label><button type="submit" disabled={!reason.trim()}>{selected && selected.status !== 'DRAFT' ? 'Clone as unapproved draft' : 'Create unapproved draft'}</button></form>}
      {!options.can_edit && !options.can_approve && !options.can_publish && <p>Read-only commercial pricing access.</p>}
    </fieldset>}
    <button type="button" disabled={busy} onClick={() => setRefresh((value) => value + 1)}>Refresh commercial prices</button>
  </article>;
}
