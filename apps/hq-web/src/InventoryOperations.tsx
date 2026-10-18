import { useCallback, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { createPortal } from 'react-dom';
import { IntakeModal } from './IntakeModal.js';
import { inventoryCommand, loadInventoryChanges, loadInventoryValuation } from './api.js';
import type { HQInventoryBatchItem, HQInventoryLocationItem, HQStockTransfer, InventoryChange, InventoryValuation } from './api.js';

type Operation = 'ADJUSTMENT' | 'WRITE_OFF' | 'DESTRUCTION' | 'COST' | 'TRANSFER_LOSS';
type Dialog = { kind: 'request'; operation: Operation; batchId?: string; transferId?: string } | { kind: 'decision'; item: InventoryChange; approve: boolean } | { kind: 'transfer'; id: string; action: 'reject' | 'cancel' };
const names: Record<Operation, string> = { ADJUSTMENT: 'Stock adjustment', WRITE_OFF: 'Write off stock', DESTRUCTION: 'Record destruction', COST: 'Declare acquisition cost', TRANSFER_LOSS: 'Close transfer shortage' };
export function InventoryOperations({ tenantId, csrfToken, batches, locations, transfers, onChanged }: {
  readonly tenantId: string; readonly csrfToken: string; readonly batches: readonly HQInventoryBatchItem[];
  readonly locations: readonly HQInventoryLocationItem[]; readonly transfers: readonly HQStockTransfer[]; readonly onChanged: () => Promise<void>;
}) {
  const [changes, setChanges] = useState<readonly InventoryChange[]>([]);
  const [valuation, setValuation] = useState<InventoryValuation | null>(null);
  const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [batchId, setBatchId] = useState(''); const [locationId, setLocationId] = useState('');
  const [quantity, setQuantity] = useState(''); const [reason, setReason] = useState(''); const [evidence, setEvidence] = useState('');
  const [key, setKey] = useState(() => crypto.randomUUID()); const [busy, setBusy] = useState(false);
  const reload = useCallback(async (signal?: AbortSignal) => {
    try { const [requests, values] = await Promise.all([loadInventoryChanges(tenantId, signal), loadInventoryValuation(tenantId, signal)]); if (!signal?.aborted) { setChanges(requests); setValuation(values); } }
    catch (cause) { if (!signal?.aborted) setError(cause instanceof Error ? cause.message : 'Could not load inventory operations.'); }
  }, [tenantId]);
  useEffect(() => { const controller = new AbortController(); void reload(controller.signal); return () => controller.abort(); }, [reload]);
  const open = (next: Dialog) => { setDialog(next); setBatchId(next.kind === 'request' ? next.batchId ?? '' : ''); setLocationId(''); setQuantity(''); setReason(''); setEvidence(''); setKey(crypto.randomUUID()); setError(''); };
  const save = async (event: FormEvent) => {
    event.preventDefault(); if (!dialog || busy) return; setBusy(true); setError('');
    try {
      if (dialog.kind === 'decision') await inventoryCommand(`/api/inventory/changes/${dialog.item.id}/decide/`, { approve: dialog.approve, reason }, csrfToken, tenantId);
      else if (dialog.kind === 'transfer') await inventoryCommand(`/api/inventory/transfers/${dialog.id}/${dialog.action}/`, { reason }, csrfToken, tenantId);
      else await inventoryCommand('/api/inventory/changes/', { kind: dialog.operation, reason, idempotency_key: key, payload: dialog.operation === 'TRANSFER_LOSS' ? { transfer_id: dialog.transferId } : { batch_id: batchId, ...(dialog.operation === 'COST' ? { unit_cost: quantity, evidence } : { location_id: locationId, quantity }) } }, csrfToken, tenantId);
      setDialog(null); setNotice(dialog.kind === 'request' ? 'Request recorded. A separate authorized operator must approve it.' : 'Decision recorded with its audit evidence.');
      await Promise.all([reload(), onChanged()]);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'The inventory operation could not be completed.'); }
    finally { setBusy(false); }
  };
  return <section className="inventory-operations">
    <div className="stocktake-heading"><div><h2>Inventory exceptions & acquisition value</h2><p className="panel-note">Investigate, request, then have a separate authorized operator approve. Quantities change only when approval succeeds.</p></div>
      <div className="tenant-row-actions">{(['ADJUSTMENT', 'WRITE_OFF', 'DESTRUCTION', 'COST'] as const).map((operation) => <button className="secondary-button" key={operation} type="button" onClick={() => open({ kind: 'request', operation })}>{names[operation]}</button>)}</div></div>
    {notice && <p role="status">{notice}</p>}{error && !dialog && <p role="alert" className="business-dialog-error">{error}</p>}
    <h3>Approval queue</h3>{!changes.length ? <p className="panel-note">No inventory exception requests.</p> : <div className="table-scroll"><table><thead><tr><th>Operation</th><th>Evidence</th><th>Requested by</th><th>Status</th><th>Decision</th></tr></thead><tbody>{changes.map((item) => <tr key={item.id}><td>{names[item.kind as Operation] || item.kind}<small className="row-detail">{item.payload.quantity ?? item.payload.unit_cost ?? ''} · {batches.find((batch) => batch.id === item.payload.batch_id)?.manufacturer_batch_number ?? transfers.find((transfer) => transfer.id === item.payload.transfer_id)?.transfer_number ?? ''}</small></td><td>{item.reason}</td><td>{item.requested_by_name}</td><td>{item.status}</td><td>{item.status === 'PENDING' ? <><button className="secondary-button" type="button" onClick={() => open({ kind: 'decision', item, approve: true })}>Review & approve</button><button className="secondary-button" type="button" onClick={() => open({ kind: 'decision', item, approve: false })}>Reject</button></> : <span>{item.decided_by_name} · {item.decision_reason}</span>}</td></tr>)}</tbody></table></div>}
    <h3>Transfer exceptions</h3><p className="panel-note">Cancel before dispatch, reject submitted requests, or investigate outstanding dispatched quantities. Shortage closure records loss against the dispatch and never removes source stock twice.</p>
    <div className="table-scroll"><table><thead><tr><th>Transfer</th><th>Status</th><th>Available actions</th></tr></thead><tbody>{transfers.filter((item) => ['DRAFT', 'SUBMITTED', 'APPROVED', 'DISPATCHED', 'IN_TRANSIT', 'PARTIALLY_RECEIVED'].includes(item.status)).map((item) => <tr key={item.id}><td>{item.transfer_number}</td><td>{item.status}</td><td>{['DRAFT', 'SUBMITTED', 'APPROVED'].includes(item.status) && <button className="secondary-button" type="button" onClick={() => open({ kind: 'transfer', id: item.id, action: 'cancel' })}>Cancel transfer</button>}{item.status === 'SUBMITTED' && <button className="secondary-button" type="button" onClick={() => open({ kind: 'transfer', id: item.id, action: 'reject' })}>Reject transfer</button>}{['DISPATCHED', 'IN_TRANSIT', 'PARTIALLY_RECEIVED'].includes(item.status) && <button className="secondary-button" type="button" onClick={() => open({ kind: 'request', operation: 'TRANSFER_LOSS', transferId: item.id })}>Investigate remaining shortage</button>}</td></tr>)}</tbody></table></div>
    <h3>Current stock valuation</h3>{valuation && <><p><strong>KES {valuation.known_value}</strong> recorded acquisition value · {valuation.unvalued_lines} unvalued custody lines · {valuation.complete ? 'All custody costs supplied' : 'Incomplete acquisition-cost coverage'}</p><p className="panel-note">Specific identification by physical batch and selling unit. {valuation.note}</p><div className="table-scroll"><table><thead><tr><th>Item / lot</th><th>Custody</th><th>Quantity</th><th>Unit cost (KES)</th><th>Value (KES)</th><th>Action</th></tr></thead><tbody>{valuation.rows.map((row) => <tr key={row.balance_id}><td>{row.sku_code} · {row.sku_name}<small className="row-detail">{row.batch_number}</small></td><td>{row.location} · {row.quality_status}</td><td>{row.quantity}</td><td>{row.unit_cost ?? 'Not supplied'}</td><td>{row.value ?? 'Unvalued'}</td><td>{row.unit_cost === null && row.batch_id && <button className="secondary-button" type="button" onClick={() => open({ kind: 'request', operation: 'COST', batchId: row.batch_id })}>Declare cost</button>}</td></tr>)}</tbody></table></div></>}
    {dialog && createPortal(<IntakeModal title={dialog.kind === 'request' ? names[dialog.operation] : dialog.kind === 'decision' ? `${dialog.approve ? 'Approve' : 'Reject'} ${names[dialog.item.kind as Operation]}` : `${dialog.action} transfer`} busy={busy} onClose={() => setDialog(null)}><form onSubmit={(event) => void save(event)}><fieldset disabled={busy} style={{ border: 0, padding: 0 }}>
      {dialog.kind === 'decision' && <p>{dialog.item.reason}<br />Requested by {dialog.item.requested_by_name}. Approval is independent and posts the proposed effect atomically.</p>}
      {dialog.kind === 'request' && dialog.operation === 'TRANSFER_LOSS' && <p>Investigate all remaining quantities on {transfers.find((item) => item.id === dialog.transferId)?.transfer_number}. Approval closes the outstanding shortage as lost; accepted and damaged receipts stay unchanged.</p>}
      {dialog.kind === 'request' && dialog.operation !== 'TRANSFER_LOSS' && <><label className="business-field">Exact stock batch / custody lot<select required value={batchId} onChange={(event) => setBatchId(event.target.value)}><option value="">Choose batch</option>{batches.map((batch) => <option key={batch.id} value={batch.id}>{batch.sku_code} · {batch.manufacturer_batch_number} · {batch.quality_status}</option>)}</select></label>
        {dialog.operation !== 'COST' && <label className="business-field">Physical custody location<select required value={locationId} onChange={(event) => setLocationId(event.target.value)}><option value="">Choose location</option>{locations.filter((location) => location.status === 'ACTIVE').map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}</select></label>}
        <label className="business-field">{dialog.operation === 'COST' ? 'Acquisition cost per selling unit (KES)' : dialog.operation === 'ADJUSTMENT' ? 'Signed quantity change (+ gain / − loss)' : 'Quantity removed'}<input required type="number" step="0.0001" min={dialog.operation === 'ADJUSTMENT' ? undefined : dialog.operation === 'COST' ? '0' : '0.0001'} value={quantity} onChange={(event) => setQuantity(event.target.value)} /></label>
        {dialog.operation === 'COST' && <label className="business-field">Invoice / acquisition evidence<textarea required maxLength={2000} value={evidence} onChange={(event) => setEvidence(event.target.value)} /></label>}
        {dialog.operation === 'ADJUSTMENT' && <p className="panel-note">Positive gains must enter a quarantined batch and custody location for quality review.</p>}</>}
      <label className="business-field">{dialog.kind === 'decision' ? 'Decision reason' : 'Investigation / physical evidence'}<textarea required maxLength={2000} value={reason} onChange={(event) => setReason(event.target.value)} /></label>{error && <p role="alert" className="business-dialog-error">{error}</p>}<footer><button className="secondary-button" type="button" onClick={() => setDialog(null)}>Close</button><button className="primary-button" type="submit">{busy ? 'Working…' : dialog.kind === 'request' ? 'Submit for independent approval' : 'Record decision'}</button></footer>
    </fieldset></form></IntakeModal>, document.body)}
  </section>;
}
