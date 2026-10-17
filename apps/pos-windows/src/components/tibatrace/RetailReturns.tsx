import { useEffect, useRef, useState } from 'react';
import type { PosRetailClient, RetailTransactionDTO, RetailStoreDTO } from '@dawatrace/shared/retail/index.js';

/** Original receipt, distinct approver and append-only refund; no cart edits. */
export function RetailReturns({ client, deviceId }: { client: PosRetailClient; deviceId: string }) {
  const [number, setNumber] = useState('');
  const [sale, setSale] = useState<RetailTransactionDTO | null>(null);
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [batches, setBatches] = useState<Record<string, string>>({});
  const [physical, setPhysical] = useState<Record<string, boolean>>({});
  const [location, setLocation] = useState('');
  const [stores, setStores] = useState<readonly RetailStoreDTO[]>([]);
  const [reason, setReason] = useState('');
  const [paymentReferences, setPaymentReferences] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const key = useRef('');
  useEffect(() => { void client.stores(deviceId).then(setStores).catch(() => setStores([])); }, [client, deviceId]);
  const run = async (work: () => Promise<void>) => {
    setBusy(true); setNotice('');
    try { await work(); } catch (cause) { setNotice(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  };
  const reload = async () => { if (sale) setSale(await client.getTransaction(sale.id)); };
  const load = () => void run(async () => {
    const loaded = await client.lookupReceipt(number.trim());
    setSale(loaded); setQuantities({}); setBatches({}); setPhysical({}); setReason(''); key.current = '';
  });
  const request = () => void run(async () => {
    if (!sale) return;
    const lines = sale.lines.filter(line => Number(quantities[line.id]) > 0).map(line => ({
      line_id: line.id, quantity: quantities[line.id]!, return_to_stock: physical[line.id] === true,
      ...(physical[line.id] ? { inventory_batch_id: batches[line.id] || '' } : {}),
    }));
    if (!lines.length || !reason.trim()) throw new Error('Select positive line quantities and record the refund reason.');
    if (lines.some(line => line.return_to_stock && (!location || !line.inventory_batch_id))) throw new Error('Confirm the original batch and quarantine location for every physical return.');
    key.current ||= crypto.randomUUID();
    await client.requestRefund(sale.id, { device_id: deviceId, reason: reason.trim(), idempotency_key: key.current,
      lines, ...(lines.some(line => line.return_to_stock) ? { return_location_id: location } : {}) });
    await reload(); setNotice('Request recorded. A different authorised supervisor must approve it.');
  });
  return <section aria-label="Governed retail returns" style={{ padding: 20, border: '1px solid #cbd5e1', borderRadius: 12, marginTop: 20 }}>
    <h2>Returns and refunds</h2>
    <p>Original internal receipt required. Physical returns stay in quarantine; this does not make returned medicine saleable.</p>
    <label>Original receipt number <input value={number} disabled={busy} onChange={event => setNumber(event.target.value)} /></label>{' '}
    <button disabled={busy || !number.trim()} onClick={load}>Find receipt</button>
    {notice ? <p role="status">{notice}</p> : null}
    {sale ? <>
      <h3>{sale.receipt?.receipt_number} · {sale.currency} {sale.total} · refunded {sale.refunded_total ?? '0.00'}</h3>
      {sale.lines.map(line => <div key={line.id} style={{ padding: 10, borderBottom: '1px solid #dbe2e8' }}>
        <label>{line.description_snapshot} · refundable {line.refundable_quantity ?? '0'} {line.unit}
          <input aria-label={`Refund quantity ${line.description_snapshot}`} type="number" min="0" max={line.refundable_quantity ?? '0'} step="0.0001"
            value={quantities[line.id] ?? '0'} disabled={busy} onChange={event => setQuantities(previous => ({ ...previous, [line.id]: event.target.value }))} />
        </label>
        <label><input type="checkbox" checked={physical[line.id] === true} disabled={busy} onChange={event => setPhysical(previous => ({ ...previous, [line.id]: event.target.checked }))} /> Receive physical stock into quarantine</label>
        {physical[line.id] ? <label>Confirmed batch from original issue
          <select value={batches[line.id] ?? ''} disabled={busy} onChange={event => setBatches(previous => ({ ...previous, [line.id]: event.target.value }))}>
            <option value="">Choose actual returned batch</option>
            {line.issued_batches?.map(batch => <option key={batch.batch_id} value={batch.batch_id}>{batch.batch_number} · expiry {batch.expiry_date} · issued {batch.quantity}</option>)}
          </select></label> : null}
      </div>)}
      {Object.values(physical).some(Boolean) ? <label>Quarantine custody location
        <select value={location} disabled={busy} onChange={event => setLocation(event.target.value)}><option value="">Select active quarantine location</option>
          {stores.filter(store => store.quarantine_capability).map(store => <option key={store.id} value={store.id}>{store.name}</option>)}
        </select></label> : null}
      <label>Refund / review reason <textarea value={reason} disabled={busy} onChange={event => setReason(event.target.value)} /></label>
      <button disabled={busy} onClick={request}>Request refund</button>{' '}
      <button disabled={busy} onClick={() => void run(reload)}>Refresh original facts</button>
      {sale.refund_requests?.map(refund => <article key={refund.id} style={{ marginTop: 16 }}>
        <strong>{refund.status} · {refund.currency} {refund.amount}</strong><p>{refund.reason}</p>
        {refund.payment_plan?.map(part => <p key={part.tender_id}>{part.tender_type} refund · {refund.currency} {part.amount}</p>)}
        {refund.status === 'REQUESTED' ? <>
          <button disabled={busy} onClick={() => void run(async () => { await client.reviewRefund(sale.id, refund.id, true); await reload(); })}>Supervisor approve</button>{' '}
          <button disabled={busy || !reason.trim()} onClick={() => void run(async () => { await client.reviewRefund(sale.id, refund.id, false, reason.trim()); await reload(); })}>Reject with reason</button>
          <p>A distinct authorised supervisor must sign in; the server enforces separation of duties.</p>
        </> : null}
        {refund.status === 'APPROVED' ? <>
          {refund.payment_plan?.filter(part => part.tender_type === 'CARD').map(part => <label key={part.tender_id}>Terminal refund approval reference · {refund.currency} {part.amount}
            <input value={paymentReferences[part.tender_id] ?? ''} disabled={busy} onChange={event => setPaymentReferences(previous => ({ ...previous, [part.tender_id]: event.target.value }))} />
          </label>)}
          {refund.payment_plan?.some(part => part.tender_type === 'MPESA') ? <p>M-PESA refunds await verified Daraja reversal setup. Cash cannot replace a mobile payment reversal.</p> : <button disabled={busy || refund.payment_plan?.some(part => part.tender_type === 'CARD' && !paymentReferences[part.tender_id]?.trim())} onClick={() => void run(async () => {
            await client.cashRefund(sale.id, refund.id, deviceId, `cash-refund:${refund.id}`, paymentReferences); await reload();
            setNotice('Original-method refund recorded. Print or review its refund receipt.');
          })}>Confirm original-method refund</button>}
        </> : null}
        {refund.receipt ? <p>Refund receipt {refund.receipt.refund_number} · {refund.receipt.currency} {refund.receipt.amount}. Print job {refund.receipt.print_job?.status ?? 'not queued'}. VSCU credit note: {refund.receipt.fiscal?.status ?? 'not issued'}.</p> : null}
      </article>)}
    </> : null}
  </section>;
}
