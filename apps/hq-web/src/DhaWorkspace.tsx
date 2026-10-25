import { useCallback, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { getHQTenantContext } from './api.js';
import { IntakeModal } from './IntakeModal.js';

interface Connection {
  id: string; branch: string; branch_name: string; environment: string; state: string;
  configuration: Record<string, unknown>; revision: number; validated_revision: number;
  readiness: { ready: boolean; connected: boolean; blockers: string[] };
}
interface Visit { id: string; patient: string; patient_name?: string; state: string; consent_expires_at: string | null }
interface Exchange { id: string; operation: string; state: string; attempts: number; error_code: string; created_at: string }
interface Option { id: string; name?: string; full_name?: string; patient_number?: string }
const BASE = '/api/nif/dha/connections/';
const initial = { base_url: 'https://ilm-dev.dha.go.ke/uat-middleware/api/v1', allowed_hosts: ['ilm-dev.dha.go.ke'],
  client_id_ref: '', client_secret_ref: '', callback_secret_ref: '', facility_id: '', practitioner_map: {},
  prescriber_map: {}, product_map: {}, claims_enabled: false };
const collection = <T,>(data: unknown): T[] => Array.isArray(data) ? data as T[] : (data as { results?: T[] })?.results ?? [];

export function DhaWorkspace({ csrfToken }: { csrfToken: string }) {
  const tenant = getHQTenantContext();
  const [connections, setConnections] = useState<Connection[]>([]);
  const [branches, setBranches] = useState<Option[]>([]);
  const [patients, setPatients] = useState<Option[]>([]);
  const [selected, setSelected] = useState('');
  const [visits, setVisits] = useState<Visit[]>([]);
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [patient, setPatient] = useState('');
  const [visit, setVisit] = useState('');
  const [otp, setOtp] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [setup, setSetup] = useState<Connection | 'new' | null>(null);
  const [approval, setApproval] = useState<Connection | null>(null);
  const [result, setResult] = useState<unknown>(null);
  const [refusal, setRefusal] = useState(false);
  const connection = connections.find(c => c.id === selected);
  const currentVisit = visits.find(v => v.id === visit);

  const request = useCallback(async (path: string, body?: unknown, method = 'POST', signal?: AbortSignal) => {
    const response = await fetch(path, { method: body === undefined ? 'GET' : method, credentials: 'include', ...(signal ? { signal } : {}),
      headers: { Accept: 'application/json', 'X-Tenant-ID': tenant, ...(body === undefined ? {} : {
        'Content-Type': 'application/json', 'X-CSRFToken': csrfToken }) }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    const data: unknown = await response.json();
    if (!response.ok) {
      const obj = data as Record<string, unknown>;
      throw Error(String(obj.detail ?? (Array.isArray(data) ? data.join(' · ') : Object.entries(obj).map(([k,v]) => `${k}: ${String(v)}`).join(' · '))));
    }
    return data;
  }, [tenant, csrfToken]);

  const load = useCallback(async (signal?: AbortSignal) => {
    if (!tenant) { setLoading(false); return; }
    setLoading(true);
    try {
      const list = collection<Connection>(await request(BASE, undefined, 'GET', signal));
      if (!signal?.aborted) { setConnections(list); setSelected(old => list.some(c => c.id === old) ? old : list[0]?.id ?? ''); }
    } catch (e) { if (!signal?.aborted) setError(e instanceof Error ? e.message : 'DHA setup is unavailable.'); }
    finally { if (!signal?.aborted) setLoading(false); }
  }, [request, tenant]);
  const loadDetails = useCallback(async (signal?: AbortSignal) => {
    if (!selected) return;
    try {
      const [v, e] = await Promise.all([request(`${BASE}${selected}/visits/`, undefined, 'GET', signal), request(`${BASE}${selected}/exchanges/`, undefined, 'GET', signal)]);
      if (!signal?.aborted) { setVisits(collection<Visit>(v)); setExchanges(collection<Exchange>(e)); }
    } catch (e) { if (!signal?.aborted) setError(e instanceof Error ? e.message : 'DHA records are unavailable.'); }
  }, [selected, request]);
  useEffect(() => { const c = new AbortController(); void load(c.signal); return () => c.abort(); }, [load]);
  useEffect(() => { setVisits([]); setExchanges([]); setVisit(''); setResult(null); const c = new AbortController(); void loadDetails(c.signal); return () => c.abort(); }, [loadDetails]);
  const perform = async (action: () => Promise<void>) => {
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    try { await action(); await load(); await loadDetails(); }
    catch (e) { setError(e instanceof Error ? e.message : 'The request could not be confirmed. Refresh before retrying.'); }
    finally { setBusy(false); }
  };
  const configure = () => void perform(async () => {
    setBranches(collection<Option>(await request('/api/organizations/locations/'))); setSetup('new');
  });
  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    void perform(async () => {
      const config = { ...(setup === 'new' ? {} : setup?.configuration ?? {}), base_url: String(form.get('base_url')), allowed_hosts: String(form.get('allowed_hosts')).split(',').map(v => v.trim()),
        facility_id: String(form.get('facility_id')), client_id_ref: String(form.get('client_id_ref')), client_secret_ref: String(form.get('client_secret_ref')),
        callback_secret_ref: String(form.get('callback_secret_ref')), hie_tenant_id: String(form.get('hie_tenant_id') ?? ''),
        callback_hie_secret_ref: String(form.get('callback_hie_secret_ref') ?? ''), claims_enabled: form.get('claims_enabled') === 'on',
        practitioner_map: JSON.parse(String(form.get('practitioner_map'))), prescriber_map: JSON.parse(String(form.get('prescriber_map'))), product_map: JSON.parse(String(form.get('product_map'))), unit_map: JSON.parse(String(form.get('unit_map'))), remittance_paths: JSON.parse(String(form.get('remittance_paths'))) };
      await request(setup === 'new' ? BASE : `${BASE}${setup?.id}/`, setup === 'new' ? { branch: form.get('branch'), environment: form.get('environment'), configuration: config } : { configuration: config }, setup === 'new' ? 'POST' : 'PATCH');
      setSetup(null); setNotice('Configuration saved. Review readiness before activation.');
    });
  };
  const command = (operation: string, payload: unknown = {}) => void perform(async () => {
    const response = await request(`${BASE}${selected}/commands/`, { operation, payload, visit, idempotency_key: crypto.randomUUID() }) as { state: string; error_code?: string; response?: unknown };
    setOtp('');
    setNotice(response.state === 'UNCERTAIN' ? 'Outcome uncertain. Reconcile the existing request before sending another.' : `${operation.replaceAll('_', ' ')}: ${response.state.toLowerCase().replaceAll('_', ' ')}${response.error_code ? ` · ${response.error_code}` : ''}.`);
    if (operation === 'patient_records') setResult(response.response ?? null);
  });

  if (!tenant) return <article className="panel"><h3>DHA connections</h3><p>Select a pharmacy to configure its branch integrations.</p></article>;
  return <section className="panel" aria-label="Tenant DHA integrations">
    <div className="section-heading"><div><p className="eyebrow">National health exchange</p><h2>DHA connections</h2><p>Configure each branch, validate its sandbox and record approval evidence before activation.</p></div>
      <div className="button-row"><button className="primary-button" disabled={busy} onClick={configure}>Add branch connection</button><button className="secondary-button" disabled={busy || loading} onClick={() => void perform(async () => {})}>Refresh</button></div></div>
    {error && !setup && !approval && !refusal && <p role="alert" className="business-dialog-error">{error}</p>}{notice && <p role="status">{notice}</p>}
    {loading && <p role="status">Loading DHA connections…</p>}
    {!loading && connections.length === 0 && <p>No DHA connections configured for this pharmacy. Add a sandbox branch connection to begin.</p>}
    {connections.length > 0 && <label className="business-field"><span>Branch connection</span><select value={selected} onChange={e => setSelected(e.target.value)}>{connections.map(c => <option key={c.id} value={c.id}>{c.branch_name} · {c.environment} · {c.state}</option>)}</select></label>}
    {connection && <>
      <div className="integration-section-head"><h3>{connection.branch_name} · {connection.state.toLowerCase()}</h3><span>Revision {connection.revision} · {connection.readiness.connected ? 'Enabled' : 'Activation pending'}</span></div>
      {connection.readiness.blockers.length > 0 && <ul>{connection.readiness.blockers.map(b => <li key={b}>{b}</li>)}</ul>}
      <div className="button-row"><button className="secondary-button" disabled={busy} onClick={() => setSetup(connection)}>Edit setup</button><button className="secondary-button" disabled={busy} onClick={() => void perform(async () => { await request(`${BASE}${selected}/probe/`, {}); setNotice('Token and facility connectivity validated for this revision.'); })}>Validate connectivity</button><button className="primary-button" disabled={busy || !connection.readiness.ready} onClick={() => setApproval(connection)}>Review activation evidence</button><button className="secondary-button" disabled={busy || !['ACTIVE', 'SANDBOX'].includes(connection.state)} onClick={() => void perform(async () => { await request(`${BASE}${selected}/suspend/`, {}); setNotice('Connection suspended.'); })}>Suspend</button></div>
      <h3>Patient consent and records</h3><p>Resolve and verify the patient’s CR identifier and map the requesting practitioner before opening a visit.</p>
      <button className="secondary-button" disabled={busy || !connection.readiness.connected} onClick={() => void perform(async () => { setPatients(collection<Option>(await request('/api/patients/'))); })}>Find patients</button>
      {patients.length > 0 && <div className="button-row"><label className="business-field"><span>Patient</span><select value={patient} onChange={e => setPatient(e.target.value)}><option value="">Select patient</option>{patients.map(p => <option key={p.id} value={p.id}>{p.full_name ?? p.name ?? p.patient_number ?? p.id}</option>)}</select></label><button className="primary-button" disabled={busy || !patient} onClick={() => void perform(async () => { const v = await request(`${BASE}${selected}/visits/`, { patient }) as Visit; setVisit(v.id); setNotice('Visit created. Request patient consent to continue.'); })}>Open visit</button></div>}
      <label className="business-field"><span>DHA visit</span><select value={visit} onChange={e => { setVisit(e.target.value); setResult(null); }}><option value="">Select your visit</option>{visits.map(v => <option key={v.id} value={v.id}>{v.patient_name ?? v.patient} · {v.state}</option>)}</select></label>
      {currentVisit && <div className="button-row">
        {currentVisit.state === 'PENDING' && <><button className="secondary-button" disabled={busy} onClick={() => command('consent_request', { visit_type: 'OP' })}>Request consent</button><button className="secondary-button" disabled={busy} onClick={() => command('consent_resend')}>Resend OTP</button><button className="secondary-button" disabled={busy} onClick={() => command('consent_status')}>Check consent</button></>}
        {['PENDING', 'CLOSING'].includes(currentVisit.state) && <><label className="business-field"><span>Patient OTP</span><input value={otp} onChange={e => setOtp(e.target.value)} autoComplete="one-time-code" inputMode="numeric" maxLength={12} /></label><button className="primary-button" disabled={busy || !otp} onClick={() => command('consent_verify', { otp })}>Verify OTP</button><button className="secondary-button" disabled={busy} onClick={() => setRefusal(true)}>Record refusal</button></>}
        {currentVisit.state === 'OPEN' && <><button className="secondary-button" disabled={busy} onClick={() => command('visit_refresh')}>Refresh consent</button><button className="primary-button" disabled={busy} onClick={() => command('patient_records', { resources: 'MedicationRequest,MedicationDispense,AllergyIntolerance' })}>Read pharmacy records</button><button className="secondary-button" disabled={busy} onClick={() => command('visit_close')}>Close visit</button></>}
      </div>}
      {result !== null && <PharmacyRecords value={result} />}
      <h3>Exchange journal</h3><p>Accepted means DHA received the request. Shared records require read-back confirmation. Uncertain outcomes require reconciliation.</p>
      <div className="table-scroll"><table><thead><tr><th>Operation</th><th>Status</th><th>Attempts</th><th>Action</th></tr></thead><tbody>{exchanges.map(e => <tr key={e.id}><td>{e.operation.replaceAll('_', ' ')}</td><td>{e.state.replaceAll('_', ' ')}{e.error_code && <small> · {e.error_code}</small>}</td><td>{e.attempts}</td><td>{e.operation === 'bundle_submit' && ['ACCEPTED', 'UNCERTAIN'].includes(e.state) ? <button className="secondary-button" disabled={busy} onClick={() => void perform(async () => { const r = await request(`${BASE}${selected}/confirm-bundle/`, { exchange: e.id, ...(visit ? { visit } : {}) }) as { state: string }; setNotice(r.state.replaceAll('_', ' ').toLowerCase()); })}>Confirm stored records</button> : '—'}</td></tr>)}</tbody></table></div>
    </>}
    {refusal && <IntakeModal title="Record consent refusal" busy={busy} onClose={() => setRefusal(false)}><form onSubmit={e => { e.preventDefault(); const reason = String(new FormData(e.currentTarget).get('reason')); setRefusal(false); command('consent_verify', { consent_decision: 'Reject', rejection_reason: reason }); }}><label className="business-field"><span>Reason the patient declined</span><textarea name="reason" required maxLength={1000} rows={3} /></label><footer><button type="button" className="secondary-button" onClick={() => setRefusal(false)}>Cancel</button><button className="primary-button" disabled={busy}>Record refusal</button></footer></form></IntakeModal>}
    {setup && <IntakeModal busy={busy} title={setup === 'new' ? 'Add DHA branch connection' : 'Edit DHA configuration'} onClose={() => { if (!busy) setSetup(null); }}>
      <p>Enter configuration locations and reference names only. Supply credential values through the server secrets manager. Editing disables the connection until revalidated.</p>
      {error && <p role="alert" className="business-dialog-error">{error}</p>}
      <form onSubmit={save}>{setup === 'new' && <><label className="business-field"><span>Branch</span><select name="branch" required>{branches.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select></label><label className="business-field"><span>Environment</span><select name="environment"><option>SANDBOX</option><option>PRODUCTION</option></select></label></>}
        {(['base_url', 'allowed_hosts', 'facility_id', 'client_id_ref', 'client_secret_ref', 'callback_secret_ref', 'hie_tenant_id', 'callback_hie_secret_ref'] as const).map(k => <label className="business-field" key={k}><span>{k.replaceAll('_', ' ')}</span><input required={!['hie_tenant_id', 'callback_hie_secret_ref'].includes(k)} name={k} defaultValue={String((setup === 'new' ? initial : setup.configuration)[k as keyof typeof initial] ?? '')} /></label>)}
        {['practitioner_map', 'prescriber_map', 'product_map', 'unit_map', 'remittance_paths'].map(k => <label className="business-field" key={k}><span>{k.replaceAll('_', ' ')} (JSON mappings)</span><textarea name={k} rows={3} defaultValue={JSON.stringify(setup === 'new' ? {} : setup.configuration[k] ?? {}, null, 2)} /></label>)}
        <p>Practitioner mappings: local user ID → verified PUID. Prescriber mappings: national practitioner ID → local practitioner ID. Product mappings: coding system|code → local SKU ID.</p>
        <label><input name="claims_enabled" type="checkbox" defaultChecked={setup !== 'new' && setup.configuration.claims_enabled === true} /> Enable SHA workflow capability for this connection</label>
        <footer><button className="secondary-button" type="button" disabled={busy} onClick={() => setSetup(null)}>Cancel</button><button className="primary-button" disabled={busy}>Save setup</button></footer>
      </form></IntakeModal>}
    {approval && <IntakeModal busy={busy} title="DHA activation evidence" onClose={() => { if (!busy) setApproval(null); }}><p>Reference verified approval documents. Recording a reference does not issue DHA certification.</p><form onSubmit={e => { e.preventDefault(); const data = Object.fromEntries(new FormData(e.currentTarget)); void perform(async () => { await request(`${BASE}${approval.id}/activate/`, { evidence: data }); setApproval(null); setNotice('Connection activated for its approved environment.'); }); }}>
      {error && <p role="alert" className="business-dialog-error">{error}</p>}
      {['sandbox_uat', 'security_review', 'system_dpia', 'facility_approval', ...(approval.environment === 'PRODUCTION' ? ['dha_approval', 'production_access'] : [])].map(k => <label className="business-field" key={k}><span>{k.replaceAll('_', ' ')}</span><input name={k} required minLength={5} maxLength={250} /></label>)}
      <footer><button className="secondary-button" type="button" disabled={busy} onClick={() => setApproval(null)}>Cancel</button><button className="primary-button" disabled={busy}>Record approval and activate</button></footer></form></IntakeModal>}
  </section>;
}

function PharmacyRecords({ value }: { value: unknown }) {
  interface Resource { resourceType?: string; id?: string; status?: string; medicationCodeableConcept?: Concept;
    medicationReference?: { display?: string; reference?: string }; code?: Concept; clinicalStatus?: Concept;
    quantity?: { value?: number; unit?: string }; dosageInstruction?: { text?: string }[] }
  interface Concept { text?: string; coding?: { display?: string; code?: string }[] }
  const describe = (concept?: Concept) => concept?.text ?? concept?.coding?.map(c => c.display ?? c.code).filter(Boolean).join(', ');
  const entries = (value as { entry?: { resource?: Resource }[] })?.entry ?? [];
  return <section aria-label="Consented pharmacy records"><h3>Consented pharmacy records</h3>
    {entries.length === 0 ? <p>No matching pharmacy records returned for this patient.</p> : <div className="table-scroll"><table>
      <thead><tr><th>Record</th><th>Medicine / allergy</th><th>Directions</th><th>Status / quantity</th></tr></thead><tbody>
        {entries.map((entry, index) => { const r = entry.resource ?? {}; return <tr key={`${r.resourceType}-${r.id ?? index}`}>
          <td>{r.resourceType === 'MedicationRequest' ? 'Prescription' : r.resourceType === 'MedicationDispense' ? 'Dispensing' : 'Allergy'}<small> · {r.id}</small></td>
          <td>{describe(r.medicationCodeableConcept ?? r.code) || r.medicationReference?.display || r.medicationReference?.reference || 'Review source record'}</td>
          <td>{r.dosageInstruction?.map(d => d.text).filter(Boolean).join('; ') || '—'}</td>
          <td>{r.status ?? describe(r.clinicalStatus) ?? 'Not specified'}{r.quantity && <small> · {r.quantity.value} {r.quantity.unit}</small>}</td>
        </tr>; })}
      </tbody></table></div>}
  </section>;
}
