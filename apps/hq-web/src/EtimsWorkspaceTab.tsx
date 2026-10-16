import { useCallback, useEffect, useState } from 'react';
import { getHQTenantContext } from './api.js';
import { IntakeModal } from './IntakeModal.js';

interface Branch { id: string; code: string; name: string; enabled: boolean; message: string; mapped_item_count: number }
interface FiscalRow {
  id: string; branch_id: string; branch_name: string; source_kind: string; source_id: string;
  invoice_number: number | null; original_invoice_number: number | null; status: string;
  attempts: number; error: string; total: string | null; updated_at: string;
  receipt: Record<string, string | number> | null; can_prepare: boolean;
}

export function EtimsWorkspaceTab({ csrfToken }: { readonly csrfToken: string }) {
  const tenantId = getHQTenantContext();
  const [branches, setBranches] = useState<Branch[]>([]);
  const [rows, setRows] = useState<FiscalRow[]>([]);
  const [branchId, setBranchId] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [detail, setDetail] = useState<FiscalRow | null>(null);
  const [setup, setSetup] = useState(false);
  const headers = { Accept: 'application/json', 'X-Tenant-ID': tenantId };
  const load = useCallback(async (signal?: AbortSignal) => {
    if (!tenantId) { setLoading(false); return; }
    setLoading(true); setError('');
    try {
      const h = { Accept: 'application/json', 'X-Tenant-ID': tenantId };
      const [profile, receipts] = await Promise.all([
        fetch('/api/taxation/profile/', { credentials: 'include', headers: h, ...(signal ? { signal } : {}) }),
        fetch(`/api/taxation/receipts/${branchId ? `?branch_id=${encodeURIComponent(branchId)}` : ''}`, { credentials: 'include', headers: h, ...(signal ? { signal } : {}) }),
      ]);
      if (!profile.ok || !receipts.ok) throw Error('Fiscal records could not be loaded. Check your access and refresh.');
      const p = await profile.json() as { branches: Branch[] };
      const r = await receipts.json() as { results: FiscalRow[] };
      if (signal?.aborted) return;
      setBranches(p.branches); setRows(r.results);
    } catch (cause) { if (!signal?.aborted) setError(cause instanceof Error ? cause.message : 'Fiscal records are unavailable.'); }
    finally { if (!signal?.aborted) setLoading(false); }
  }, [tenantId, branchId]);
  useEffect(() => { const c = new AbortController(); void load(c.signal); return () => c.abort(); }, [load]);
  const prepare = async (row: FiscalRow) => {
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const response = await fetch(`/api/taxation/receipts/${row.id}/retry/`, {
        method: 'POST', credentials: 'include', headers: { ...headers, 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken }, body: '{}',
      });
      if (!response.ok) throw Error('Invoice preparation was refused. Review the registered VSCU configuration and mappings, then refresh.');
      setNotice('Invoice prepared for the existing fiscal queue. Provider acceptance is checked separately.');
      await load();
    } catch { setError('Preparation could not be confirmed. Refresh the queue before trying again; an existing invoice will not be retransmitted here.'); }
    finally { setBusy(false); }
  };
  if (!tenantId) return <article className="panel"><h2>eTIMS / VSCU</h2><p>Select a pharmacy to review its registered fiscal configuration and invoice queue.</p></article>;
  return <div className="etims-workspace">
    <article className="panel">
      <div className="section-heading"><div><p className="eyebrow">Fiscal operations</p><h2>eTIMS / VSCU</h2><p>Track invoices and credit notes from the POS fiscal queue.</p></div>
        <div className="button-row"><button className="secondary-button" onClick={() => setSetup(true)}>Review setup requirements</button><button className="secondary-button" disabled={loading || busy} onClick={() => void load()}>Refresh fiscal queue</button></div></div>
      {error && <p role="alert" className="business-dialog-error">{error}</p>}{notice && <p role="status">{notice}</p>}
      {loading ? <p role="status">Loading fiscal records…</p> : <>
        <div className="etims-branches">{branches.map(b => <article className="panel" key={b.id}><h3>{b.name} · {b.code}</h3><strong>{b.enabled ? 'Configured and enabled' : 'Setup pending'}</strong><p>{b.message}</p><small>{b.mapped_item_count} mapped items</small></article>)}</div>
        <label className="business-field"><span>Branch</span><select aria-label="Fiscal branch" value={branchId} onChange={e => setBranchId(e.target.value)}><option value="">All branches</option>{branches.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select></label>
        <p className="panel-note">Payment, fiscal acceptance and printing have separate states. An uncertain invoice must be reconciled with the registered device before any resubmission.</p>
        {!error && rows.length === 0 ? <p>No fiscal submissions in this scope. Completed paid sales enter this queue automatically.</p> : <div className="table-scroll"><table><thead><tr><th>Branch / source</th><th>Invoice</th><th>Status</th><th>Attempts</th><th>Actions</th></tr></thead><tbody>{rows.map(row => <tr key={row.id}>
          <td>{row.branch_name}<small className="muted-cell"> {row.source_kind.replace(/_/g, ' ')}</small></td><td>{row.invoice_number ?? 'Not allocated'}</td><td>{row.status.replace(/_/g, ' ')}</td><td>{row.attempts}</td><td><div className="button-row"><button className="secondary-button" onClick={() => setDetail(row)}>View fiscal details</button>{row.can_prepare && <button className="secondary-button" disabled={busy || !branches.find(b => b.id === row.branch_id)?.enabled} onClick={() => void prepare(row)}>Prepare invoice</button>}</div></td>
        </tr>)}</tbody></table></div>}
      </>}
    </article>
    {setup && <IntakeModal title="VSCU setup requirements" onClose={() => setSetup(false)}><p>Provide the installed VSCU service configuration location to your platform administrator. Registered device details, the branch invoice-number baseline, item codes, units and tax mappings must be verified before activation.</p><p>Configuration and credential references are managed on the server. This screen reports their readiness; it does not collect communication keys or activate a provider.</p><button className="secondary-button" onClick={() => setSetup(false)}>Done</button></IntakeModal>}
    {detail && <IntakeModal title="Fiscal submission details" onClose={() => setDetail(null)}><dl><dt>Branch</dt><dd>{detail.branch_name}</dd><dt>Invoice</dt><dd>{detail.invoice_number ?? 'Not allocated'}</dd><dt>Status</dt><dd>{detail.status.replace(/_/g, ' ')}</dd><dt>Original invoice</dt><dd>{detail.original_invoice_number || 'Sale invoice'}</dd><dt>Source</dt><dd>{detail.source_kind} · {detail.source_id}</dd></dl>{detail.error && <p role="status">{detail.error}</p>}{detail.status === 'ACCEPTED' && detail.receipt ? <><h3>Accepted provider evidence</h3><dl>{Object.entries(detail.receipt).map(([k,v]) => <div key={k}><dt>{k}</dt><dd>{String(v)}</dd></div>)}</dl></> : <p>Accepted fiscal receipt evidence is not yet available.</p>}<button className="secondary-button" onClick={() => setDetail(null)}>Close details</button></IntakeModal>}
  </div>;
}
