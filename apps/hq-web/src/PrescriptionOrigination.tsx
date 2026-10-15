import { useEffect, useRef, useState } from 'react';
import { IntakeModal } from './IntakeModal.js';
import { useIngestionWorkspace } from './IngestionWorkspace.js';
import { createClinicalWorkflowRecord, loadPrescriptionIntakeOptions, type PrescriptionIntakeOptions } from './api.js';

export function PrescriptionOrigination({ csrfToken, tenantId, onChanged }: { csrfToken: string; tenantId: string; onChanged: () => Promise<void> }) {
  const openInWorkspace = useIngestionWorkspace();
  const [mode, setMode] = useState<'prescription' | 'episode' | null>(null);
  const inFlight = useRef(false);
  const [options, setOptions] = useState<PrescriptionIntakeOptions | null>(null);
  const [query, setQuery] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [items, setItems] = useState<readonly { sku: string; quantity: string; directions: string }[]>([{ sku: '', quantity: '', directions: '' }]);
  const [physicalEvidence, setPhysicalEvidence] = useState(false);
  const [episodeKey, setEpisodeKey] = useState('');
  const reload = async (signal?: AbortSignal, search = query) => {
    if (!tenantId) return;
    try { const loaded = await loadPrescriptionIntakeOptions(search, signal, tenantId); if (!signal?.aborted) setOptions(loaded); }
    catch (cause) { if (!signal?.aborted) setNotice(cause instanceof Error ? cause.message : String(cause)); }
  };
  useEffect(() => { const controller = new AbortController(); setOptions(null); setValues({}); setQuery(''); setEpisodeKey(''); setItems([{ sku: '', quantity: '', directions: '' }]); setPhysicalEvidence(false); void reload(controller.signal, ''); return () => controller.abort(); }, [tenantId]);
  const field = (key: string, value: string) => setValues(previous => ({ ...previous, [key]: value }));
  const select = (label: string, key: string, rows: readonly { id: string; name: string }[]) => <label className="business-field">{label}
    <select required value={values[key] ?? ''} onChange={event => field(key, event.target.value)}><option value="">Select confirmed record</option>
      {rows.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}
    </select></label>;
  const command = async (work: () => Promise<void>) => {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setNotice('');
    try {
      await work(); setMode(null); setValues({}); setEpisodeKey('');
      setItems([{ sku: '', quantity: '', directions: '' }]); setPhysicalEvidence(false);
      try { await onChanged(); } catch { setNotice('The record was saved. Refresh the workspace to load its current state.'); }
      await reload();
    }
    catch (cause) { setNotice(cause instanceof Error ? cause.message : 'Outcome unknown. Refresh before retrying with the same original reference.'); }
    finally { inFlight.current = false; setBusy(false); }
  };
  return <section className="panel" aria-label="Prescription origination">
    <h3>Receive prescription and open a dispensing episode</h3>
    <p className="panel-note">Record the actual prescription. Legal validation, clinical review and pharmacist verification remain separate actions in the workbench. Opening an episode does not reserve stock or certify a medicine supply.</p>
    {notice ? <p role="status" className="inline-warning">{notice}</p> : null}
    <div className="button-row"><button className="primary-button" type="button" onClick={() => openInWorkspace(() => { setNotice(''); setMode('prescription'); })}>Receive prescription</button><button className="secondary-button" type="button" onClick={() => openInWorkspace(() => { setNotice(''); setMode('episode'); })}>Open dispensing episode</button></div>
    {mode && <IntakeModal title={mode === 'prescription' ? 'Receive prescription' : 'Open dispensing episode'} busy={busy} onClose={() => setMode(null)}>
    {notice && <p role="alert" className="business-dialog-error">{notice}</p>}
    <label className="business-field">Find patient, prescriber or medicine<input value={query} onChange={event => setQuery(event.target.value)} /></label>
    <button className="secondary-button" type="button" disabled={busy} onClick={() => void reload()}>Search intake records</button>
    {options?.search_limited ? <p>Only the first 100 matches are shown. Refine the search.</p> : null}
    {options ? <>
      {mode === 'prescription' && <form onSubmit={event => { event.preventDefault(); void command(async () => {
        if (!physicalEvidence) throw new Error('Confirm that the genuine prescription is available for review.');
        const branch = options.branches.find(row => row.id === values['branch']);
        if (!branch) throw new Error('Select the receiving pharmacy branch.');
        const result = await createClinicalWorkflowRecord('/api/prescriptions/', {
          patient: values['patient'], practitioner: values['practitioner'], organization: branch.organization, location: branch.id,
          prescription_number: values['reference'], external_prescription_reference: values['reference'], prescription_date: values['date'],
          prescription_type: values['type'], source_channel: 'PAPER', notes: values['notes'] ?? '',
          items: items.map(item => {
            const sku = options.skus.find(row => row.id === item.sku);
            if (!sku) throw new Error('Select the exact governed medicine/pack for each line.');
            return { prescribed_sku: sku.id, medication_name: sku.name, quantity: item.quantity, unit: sku.unit, dosage_instruction: item.directions };
          }),
        }, csrfToken, tenantId);
        setNotice(`Prescription ${result.prescription_number ?? values['reference']} received for governed review.`);
      }); }}>
        <fieldset disabled={busy} className="stocktake-form-grid intake-fields"><legend>Actual prescription intake</legend>
          {select('Patient', 'patient', options.patients.map(row => ({ id: row.id, name: `${row.name} · ${row.number}` })))}
          {select('Prescriber', 'practitioner', options.practitioners.map(row => ({ id: row.id, name: `${row.name} · ${row.number}` })))}
          {select('Receiving pharmacy branch', 'branch', options.branches)}
          <label className="business-field">Original prescription reference<input required value={values['reference'] ?? ''} onChange={event => field('reference', event.target.value)} maxLength={100} /></label>
          <label className="business-field">Actual prescription date<input required type="date" value={values['date'] ?? ''} onChange={event => field('date', event.target.value)} /></label>
          <label className="business-field">Actual prescription type<select required value={values['type'] ?? ''} onChange={event => field('type', event.target.value)}>
            <option value="">Select the source type</option>{['ACUTE', 'REPEAT', 'CHRONIC', 'CONTROLLED', 'DISCHARGE', 'EMERGENCY', 'VETERINARY', 'INTERNAL'].map(type => <option key={type} value={type}>{type.replace(/_/g, ' ')}</option>)}
          </select></label>
          <div className="intake-wide intake-lines">{items.map((item, index) => <div className="business-record" key={index}>
            <label className="business-field">Exact prescribed medicine / pack<select required value={item.sku} onChange={event => setItems(previous => previous.map((row, i) => i === index ? { ...row, sku: event.target.value } : row))}><option value="">Choose actual product</option>{options.skus.map(sku => <option key={sku.id} value={sku.id}>{sku.name} · {sku.unit}</option>)}</select></label>
            <label className="business-field">Authorised quantity<input required type="number" min="0.0001" step="0.0001" value={item.quantity} onChange={event => setItems(previous => previous.map((row, i) => i === index ? { ...row, quantity: event.target.value } : row))} /></label>
            <label className="business-field">Verbatim dosage directions<textarea required value={item.directions} onChange={event => setItems(previous => previous.map((row, i) => i === index ? { ...row, directions: event.target.value } : row))} /></label>
            {items.length > 1 ? <button className="secondary-button" type="button" onClick={() => setItems(previous => previous.filter((_, i) => i !== index))}>Remove unsaved line</button> : null}
          </div>)}
          <button className="secondary-button" type="button" onClick={() => setItems(previous => [...previous, { sku: '', quantity: '', directions: '' }])}>Add prescribed line</button></div>
          <label className="intake-wide intake-confirmation"><input type="checkbox" checked={physicalEvidence} onChange={event => setPhysicalEvidence(event.target.checked)} /> The genuine original is available for pharmacist/legal review; this is not a national verification claim</label>
          <button className="primary-button intake-wide" disabled={!physicalEvidence} type="submit">Receive for review</button>
        </fieldset>
      </form>}
      {mode === 'episode' && <form onSubmit={event => { event.preventDefault(); void command(async () => {
        const prescription = options.verified_prescriptions.find(row => row.id === values['verified']);
        const store = options.stores.find(row => row.id === values['store']);
        const order = options.priced_orders.find(row => row.id === values['order']);
        if (!prescription || !store || !order || order.branch !== store.branch) throw new Error('A verified prescription, same-branch store and approved priced order are required.');
        const key = episodeKey || crypto.randomUUID(); setEpisodeKey(key);
        const result = await createClinicalWorkflowRecord('/api/dispensing/episodes/', { prescription_id: prescription.id,
          branch_id: store.branch, pharmacy_location_id: store.id, sales_order_id: order.id, payment_state: 'PENDING', idempotency_key: key }, csrfToken, tenantId);
        setNotice(`Episode ${result.dispensing_number ?? result.id} opened. Continue in the activated till for FEFO reservation/preparation, independent check, cash settlement, counselling and collection.`);
      }); }}>
        <fieldset disabled={busy} className="stocktake-form-grid intake-fields"><legend>Paid clinical dispensing origination</legend>
          {select('Pharmacist-verified prescription', 'verified', options.verified_prescriptions.map(row => ({ id: row.id, name: row.prescription_number })))}
          {select('Dispensing inventory location', 'store', options.stores)}
          {select('Approved authoritative priced order', 'order', options.priced_orders.map(row => ({ id: row.id, name: `${row.order_number} · ${row.total}` })))}
          <p className="panel-note">Confirm the order covers the exact prescribed medicines, pack units and quantities. No payment waiver is created here. Tills refuse missing or unapproved pricing.</p>
          <button className="primary-button" type="submit">Open pending-payment episode</button>
        </fieldset>
      </form>}
    </> : <p>Loading permitted intake records. Create genuine missing patient/prescriber/catalogue records in their dedicated sections first.</p>}
    </IntakeModal>}
  </section>;
}
