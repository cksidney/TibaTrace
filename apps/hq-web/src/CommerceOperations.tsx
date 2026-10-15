import { useEffect, useState } from 'react';
import { createContext, useContext } from 'react';
import type { ReactNode } from 'react';
import { IntakeForm } from './IntakeModal.js';
import { loadCommerceDesk, runCommerceCommand } from './api.js';
import type { CommerceDesk, CommerceDispatch, CommerceTask } from './api.js';

const CommandError = createContext('');
const retryKey = () => window.crypto.randomUUID();
export function CommerceOperations({ csrfToken, revision, onChanged }: { readonly csrfToken: string; readonly revision: string; readonly onChanged: () => Promise<void> }) {
  const [desk, setDesk] = useState<CommerceDesk | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [kind, setKind] = useState<'orders' | 'quotations'>('orders');
  const [selectedId, setSelectedId] = useState('');
  const [branchId, setBranchId] = useState('');
  const [customerId, setCustomerId] = useState('');
  const [skuId, setSkuId] = useState('');
  const [quantity, setQuantity] = useState('');
  const [key, setKey] = useState(retryKey);
  useEffect(() => {
    const controller = new AbortController(); setDesk(null); setError('');
    loadCommerceDesk(controller.signal).then((value) => { if (!controller.signal.aborted) setDesk(value); })
      .catch((cause: unknown) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'The execution desk could not be loaded.'); });
    return () => controller.abort();
  }, [revision, refresh]);
  const execute = async (resource: Parameters<typeof runCommerceCommand>[0], id: string, action: string, payload: Record<string, unknown>) => {
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await runCommerceCommand(resource, id, action, { ...payload, idempotency_key: key }, csrfToken);
      if (!id && (resource === 'orders' || resource === 'quotations')) setSelectedId(result.id);
      setKey(retryKey()); setRefresh((value) => value + 1);
      setNotice('Authoritative workflow step recorded. Continue its governed approval/fulfilment actions below.');
      try { await onChanged(); } catch { setNotice('The step was saved. Refresh the workspace to load its current state.'); }
      return true;
    } catch (cause: unknown) { setError(cause instanceof Error ? cause.message : 'Command failed. Refresh and verify the record before retrying an uncertain outcome.'); return false; }
    finally { setBusy(false); }
  };
  const drafts = desk?.[kind] ?? [];
  const selected = drafts.find((draft) => draft.id === selectedId);
  const selectedSku = desk?.skus.find((sku) => sku.id === skuId);
  return <CommandError.Provider value={error}><article className="panel" aria-labelledby="commerce-execution-heading"><h2 id="commerce-execution-heading">Create and execute fulfilment</h2>
    <p className="panel-note">Draft offers/orders, add actual SKU lines, pick authoritative allocations, pack verified stock and capture genuine delivery evidence. Independent checks and backend permissions apply at each step.</p>
    {error && <p className="inline-alert" role="alert">{error}</p>}{notice && <p className="inline-success" role="status">{notice}</p>}
    {!desk ? <p role="status">{error ? 'Desk unavailable; no empty activity is implied.' : 'Loading execution desk…'}</p> : <fieldset disabled={busy} style={{ border: 0, padding: 0 }}>
      <div className="stocktake-form-grid"><label className="business-field">Document<select value={kind} onChange={(event) => { setKind(event.target.value as typeof kind); setSelectedId(''); }}><option value="orders">Sales order</option><option value="quotations">Quotation</option></select></label>
        <label className="business-field">Existing document<select value={selectedId} onChange={(event) => setSelectedId(event.target.value)}><option value="">Select or create below</option>{drafts.map((draft) => <option key={draft.id} value={draft.id}>{draft.order_number ?? draft.quotation_number} · {draft.customer_name} · {draft.status}</option>)}</select></label></div>
      {!selected && <DeskForm label={kind === 'orders' ? 'Create sales order draft' : 'Create quotation draft'} submit={() => execute(kind, '', '', { branch: branchId, customer: customerId, currency: 'KES' })}>
        <label className="business-field">Branch<select required value={branchId} onChange={(event) => setBranchId(event.target.value)}><option value="">Select branch</option>{desk.options.branches.map((branch) => <option key={branch.id} value={branch.id}>{branch.name}</option>)}</select></label>
        <label className="business-field">Active customer<select required value={customerId} onChange={(event) => setCustomerId(event.target.value)}><option value="">Select customer</option>{desk.options.customers.map((customer) => <option key={customer.id} value={customer.id}>{customer.customer_number} · {customer.legal_name}</option>)}</select></label>
      </DeskForm>}
      {selected && <><h3>{selected.order_number ?? selected.quotation_number} · {selected.status}</h3><ul>{selected.lines.map((line) => <li key={line.id}>{line.description_snapshot || desk.skus.find((sku) => sku.id === line.sku)?.display_name} · {line.requested_quantity} {line.unit}</li>)}</ul>
        {selected.status === 'DRAFT' && <DeskForm label="Add draft line" submit={() => execute(kind, selected.id, 'lines', { sku: skuId, requested_quantity: quantity, unit: selectedSku?.sales_unit ?? '' })}>
          <label className="business-field">Governed SKU<select required value={skuId} onChange={(event) => setSkuId(event.target.value)}><option value="">Select SKU</option>{desk.skus.filter((sku) => sku.status === 'ACTIVE').map((sku) => <option key={sku.id} value={sku.id}>{sku.sku_code} · {sku.display_name}</option>)}</select><small>{selectedSku?.package_description} · Sales unit: {selectedSku?.sales_unit ?? 'Select a governed pack'}</small></label>
          <label className="business-field">Quantity in SKU sales units<input type="number" required min="0.001" step="0.001" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></label>
        </DeskForm>}
        {kind === 'orders' && <>
          {['ALLOCATED', 'PARTIALLY_ALLOCATED'].includes(selected.status) && <button className="primary-button" type="button" onClick={() => void execute('orders', selected.id, 'picking-wave', {})}>Create released picking wave from allocations</button>}
          {desk.tasks.filter((task) => task.sales_order === selected.id).map((task) => <PickingTaskCard key={task.id} task={task} busy={busy} onExecute={(action, payload) => execute('picking-tasks', task.id, action, payload)} />)}
          {['PICKED', 'PARTIALLY_PICKED'].includes(selected.status) && <button className="primary-button" type="button" onClick={() => void execute('orders', selected.id, 'packing-session', {})}>Open packing session</button>}
          {desk.sessions.filter((session) => session.sales_order === selected.id && ['OPEN', 'PACKING'].includes(session.status)).map((session) => <SessionPackageForm key={session.id} sessionNumber={session.session_number} onExecute={(payload) => execute('packing-sessions', session.id, 'create-package', payload)} />)}
          {desk.packages.filter((packageItem) => packageItem.sales_order === selected.id).map((packageItem) => <PackageCard key={packageItem.id} packageItem={packageItem} desk={desk} onExecute={(action, payload) => execute('packages', packageItem.id, action, payload)} />)}
          {['PACKED', 'PARTIALLY_PACKED'].includes(selected.status) && <DispatchCreate orderId={selected.id} customerId={selected.customer} desk={desk} onExecute={(payload) => execute('orders', selected.id, 'create-dispatch', payload)} />}
          {desk.dispatches.filter((dispatch) => dispatch.sales_order === selected.id && ['DISPATCHED', 'IN_TRANSIT', 'PARTIALLY_DELIVERED'].includes(dispatch.status)).map((dispatch) => <DeliveryForm key={dispatch.id} dispatch={dispatch} desk={desk} onExecute={(payload) => execute('dispatches', dispatch.id, 'delivery', payload)} />)}
        </>}
      </>}
    </fieldset>}
    <button className="secondary-button" type="button" disabled={busy} onClick={() => setRefresh((value) => value + 1)}>Refresh execution records</button>
  </article></CommandError.Provider>;
}

function DeskForm({ label, submit, children }: { readonly label: string; readonly submit: () => Promise<boolean>; readonly children: ReactNode }) {
  const error = useContext(CommandError);
  return <IntakeForm title={label} submitLabel={label} submit={submit} error={error}>{children}</IntakeForm>;
}
function PickingTaskCard({ task, busy, onExecute }: { readonly task: CommerceTask; readonly busy: boolean; readonly onExecute: (action: string, payload: Record<string, unknown>) => Promise<boolean> }) {
  const [picked, setPicked] = useState(''); const [short, setShort] = useState('0');
  return <section className="business-record"><h4>{task.sku_code} · requested {task.requested_quantity} · {task.status}</h4>
    {task.status === 'PENDING' && <button disabled={busy} type="button" onClick={() => void onExecute('assign', {})}>Assign to me</button>}
    {task.status === 'ASSIGNED' && <button disabled={busy} type="button" onClick={() => void onExecute('start', {})}>Start physical pick</button>}
    {task.status === 'IN_PROGRESS' && <DeskForm label="Record actual pick" submit={() => onExecute('record', { picked_quantity: picked, short_quantity: short })}><label className="business-field">Picked quantity<input required min="0" step="0.001" type="number" value={picked} onChange={(event) => setPicked(event.target.value)} /></label><label className="business-field">Short quantity<input required min="0" step="0.001" type="number" value={short} onChange={(event) => setShort(event.target.value)} /></label></DeskForm>}
    {['PICKED', 'SHORT_PICK'].includes(task.status) && <button disabled={busy} type="button" onClick={() => void onExecute('verify', {})}>Independent pick verification</button>}
  </section>;
}
function PackageCard({ packageItem, desk, onExecute }: { readonly packageItem: CommerceDesk['packages'][number]; readonly desk: CommerceDesk; readonly onExecute: (action: string, payload: Record<string, unknown>) => Promise<boolean> }) {
  const [taskId, setTaskId] = useState(''); const [quantity, setQuantity] = useState(''); const [seal, setSeal] = useState('');
  return <section className="business-record"><h4>{packageItem.package_number} · {packageItem.status}</h4><p>{packageItem.lines.length} packed lines</p>
    {['OPEN', 'PACKING'].includes(packageItem.status) && <><DeskForm label="Pack verified stock" submit={() => onExecute('pack-line', { picking_task_id: taskId, quantity })}><label className="business-field">Verified pick<select required value={taskId} onChange={(event) => setTaskId(event.target.value)}><option value="">Select verified task</option>{desk.tasks.filter((task) => task.sales_order === packageItem.sales_order && task.status === 'VERIFIED').map((task) => <option key={task.id} value={task.id}>{task.sku_code} · picked {task.picked_quantity}</option>)}</select></label><label className="business-field">Actual packed quantity<input required type="number" min="0.001" step="0.001" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></label></DeskForm>
      <DeskForm label="Independent verify and seal" submit={() => onExecute('seal', { seal_number: seal })}><label className="business-field">Actual tamper seal<input required value={seal} onChange={(event) => setSeal(event.target.value)} maxLength={100} /></label></DeskForm></>}
  </section>;
}
function SessionPackageForm({ sessionNumber, onExecute }: { readonly sessionNumber: string; readonly onExecute: (payload: Record<string, unknown>) => Promise<boolean> }) {
  const [zone, setZone] = useState(''); const [type, setType] = useState('');
  return <section><h4>{sessionNumber}</h4><DeskForm label="Create confirmed package" submit={() => onExecute({ temperature_zone: zone, package_type: type })}>
    <label className="business-field">Actual package temperature zone<select required value={zone} onChange={(event) => setZone(event.target.value)}><option value="">Confirm package conditions</option><option value="AMBIENT">Ambient</option><option value="COLD_CHAIN">Cold chain</option><option value="FROZEN">Frozen</option></select></label><label className="business-field">Packaging type / evidence<input required value={type} onChange={(event) => setType(event.target.value)} maxLength={100} /></label>
  </DeskForm><p className="panel-note">Use validated cold/controlled packaging and maintain genuine temperature evidence where required.</p></section>;
}
function DispatchCreate({ orderId, customerId, desk, onExecute }: { readonly orderId: string; readonly customerId: string; readonly desk: CommerceDesk; readonly onExecute: (payload: Record<string, unknown>) => Promise<boolean> }) {
  const [address, setAddress] = useState(''); const [carrier, setCarrier] = useState(''); const [ids, setIds] = useState<readonly string[]>([]);
  return <DeskForm label="Create dispatch for selected sealed packages" submit={() => onExecute({ delivery_address_id: address, carrier, package_ids: ids })}>
    <label className="business-field">Customer delivery address<select required value={address} onChange={(event) => setAddress(event.target.value)}><option value="">Select registered address</option>{desk.options.addresses.filter((item) => item.customer_id === customerId).map((item) => <option key={item.id} value={item.id}>{item.address_code} · {item.address_line1} · {item.city}</option>)}</select></label>
    <label className="business-field">Carrier / route<input value={carrier} onChange={(event) => setCarrier(event.target.value)} maxLength={200} /></label>
    <fieldset><legend>Sealed packages</legend>{desk.packages.filter((item) => item.sales_order === orderId && item.status === 'SEALED').map((item) => <label key={item.id}><input type="checkbox" checked={ids.includes(item.id)} onChange={() => setIds((current) => current.includes(item.id) ? current.filter((id) => id !== item.id) : [...current, item.id])} />{item.package_number}</label>)}</fieldset>
  </DeskForm>;
}
function DeliveryForm({ dispatch, desk, onExecute }: { readonly dispatch: CommerceDispatch; readonly desk: CommerceDesk; readonly onExecute: (payload: Record<string, unknown>) => Promise<boolean> }) {
  const [recipient, setRecipient] = useState(''); const [proof, setProof] = useState(''); const [notes, setNotes] = useState('');
  const [lines, setLines] = useState(() => dispatch.lines.map((line) => ({ dispatch_line_id: line.id, accepted_quantity: '', rejected_quantity: '0', damaged_quantity: '0', missing_quantity: '0' })));
  return <section className="business-record"><h4>Proof of delivery · {dispatch.dispatch_number}</h4><DeskForm label="Record evidenced delivery" submit={() => onExecute({ recipient_name: recipient, proof_type: 'DOCUMENT_REFERENCE', signature_ref: proof, delivery_notes: notes, delivery_lines_data: lines })}>
    <label className="business-field">Actual recipient<input required value={recipient} onChange={(event) => setRecipient(event.target.value)} /></label><label className="business-field">Actual signed POD evidence reference<input required value={proof} onChange={(event) => setProof(event.target.value)} placeholder="Reference to stored signed evidence" /></label>
    <label className="business-field">Delivery notes<input value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
    {lines.map((line, index) => <fieldset key={line.dispatch_line_id}><legend>{desk.skus.find((sku) => sku.id === dispatch.lines[index]?.sku)?.display_name} · dispatched {dispatch.lines[index]?.quantity}</legend>{(['accepted_quantity', 'rejected_quantity', 'damaged_quantity', 'missing_quantity'] as const).map((field) => <label className="business-field" key={field}>{field.replace('_quantity', '').replace('_', ' ')}<input required type="number" min="0" step="0.001" value={line[field]} onChange={(event) => setLines((current) => current.map((entry, position) => position === index ? { ...entry, [field]: event.target.value } : entry))} /></label>)}</fieldset>)}
  </DeskForm></section>;
}
