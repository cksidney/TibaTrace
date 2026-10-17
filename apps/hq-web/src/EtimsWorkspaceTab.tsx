import { useCallback, useEffect, useState } from 'react';
import type { FormEvent } from 'react';

import { Icon } from './icons.js';

interface EtimsWorkspaceTabProps {
  readonly csrfToken: string;
}

interface EtimsProfile {
  readonly id?: string;
  readonly is_enabled: boolean;
  readonly environment: 'SANDBOX' | 'PRODUCTION';
  readonly tin: string;
  readonly bhf_id: string;
  readonly dvc_srl_no: string;
  readonly has_cm_key: boolean;
  readonly base_url: string;
  readonly taxpayer_name: string;
  readonly branch_name: string;
  readonly sdc_id: string;
  readonly mrc_no: string;
  readonly last_invoice_number: number;
  readonly last_credit_note_number: number;
  readonly auto_fiscalize_pos_sales: boolean;
  readonly is_initialized: boolean;
  readonly is_configured: boolean;
  readonly last_sync_at: string | null;
  readonly notes: string;
}

interface FiscalReceiptRow {
  readonly id: string;
  readonly receipt_type: 'SALE' | 'CREDIT_NOTE';
  readonly invoice_number: number;
  readonly original_invoice_number: number;
  readonly customer_pin: string;
  readonly customer_name: string;
  readonly total_taxable_amount: string;
  readonly total_tax_amount: string;
  readonly total_amount: string;
  readonly currency: string;
  readonly receipt_signature: string;
  readonly internal_data: string;
  readonly qr_code_url: string;
  readonly submission_status: 'PENDING' | 'SUBMITTED' | 'FAILED' | 'OFFLINE_GENERATED';
  readonly attempt_count: number;
  readonly last_error: string;
  readonly submitted_at: string | null;
  readonly created_at: string;
}

export function EtimsWorkspaceTab({ csrfToken }: EtimsWorkspaceTabProps) {
  const [profile, setProfile] = useState<EtimsProfile | null>(null);
  const [receipts, setReceipts] = useState<readonly FiscalReceiptRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  // Form edit states
  const [isEnabled, setIsEnabled] = useState(false);
  const [environment, setEnvironment] = useState<'SANDBOX' | 'PRODUCTION'>('SANDBOX');
  const [tin, setTin] = useState('');
  const [bhfId, setBhfId] = useState('00');
  const [dvcSrlNo, setDvcSrlNo] = useState('');
  const [cmKey, setCmKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('https://etims-sbx.kra.go.ke');
  const [autoFiscalize, setAutoFiscalize] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [profileRes, receiptsRes] = await Promise.all([
        fetch('/api/taxation/profile/', {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
        }),
        fetch('/api/taxation/receipts/', {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
        }),
      ]);

      if (profileRes.ok) {
        const p = (await profileRes.json()) as EtimsProfile;
        setProfile(p);
        setIsEnabled(p.is_enabled);
        setEnvironment(p.environment || 'SANDBOX');
        setTin(p.tin || '');
        setBhfId(p.bhf_id || '00');
        setDvcSrlNo(p.dvc_srl_no || '');
        setBaseUrl(p.base_url || 'https://etims-sbx.kra.go.ke');
        setAutoFiscalize(p.auto_fiscalize_pos_sales);
      }

      if (receiptsRes.ok) {
        const rData = (await receiptsRes.json()) as { results?: FiscalReceiptRow[] };
        setReceipts(rData.results || []);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load eTIMS profile.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const saveProfile = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const payload: Record<string, unknown> = {
        is_enabled: isEnabled,
        environment,
        tin: tin.trim().toUpperCase(),
        bhf_id: bhfId.trim(),
        dvc_srl_no: dvcSrlNo.trim(),
        base_url: baseUrl.trim(),
        auto_fiscalize_pos_sales: autoFiscalize,
      };
      if (cmKey.trim()) {
        payload.cm_key = cmKey.trim();
      }

      const res = await fetch('/api/taxation/profile/', {
        method: 'PATCH',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(body.detail || `Save failed with status ${res.status}`);
      }

      const updated = (await res.json()) as EtimsProfile;
      setProfile(updated);
      setCmKey('');
      setNotice('eTIMS VSCU profile saved successfully.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Failed to save eTIMS profile.');
    } finally {
      setBusy(false);
    }
  };

  const testConnection = async () => {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const res = await fetch('/api/taxation/test-connection/', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          'X-CSRFToken': csrfToken,
        },
      });
      const data = (await res.json()) as { success: boolean; result_message?: string; error?: string; response_time_ms?: number };
      if (data.success) {
        setNotice(`KRA eTIMS server time check SUCCESS (${data.response_time_ms}ms). Connection verified.`);
      } else {
        setError(`Connection test failed: ${data.error || data.result_message || 'Endpoint unreachable'}`);
      }
      void loadData();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Connection test request failed.');
    } finally {
      setBusy(false);
    }
  };

  const initializeDevice = async () => {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const res = await fetch('/api/taxation/initialize/', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          'X-CSRFToken': csrfToken,
        },
      });
      const data = (await res.json()) as { success: boolean; result_message?: string; error?: string };
      if (data.success) {
        setNotice('KRA VSCU device handshake (selectInitInfo) completed successfully!');
      } else {
        setError(`VSCU handshake failed: ${data.error || data.result_message || 'Handshake rejected'}`);
      }
      void loadData();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Initialization request failed.');
    } finally {
      setBusy(false);
    }
  };

  const retryReceipt = async (receiptId: string) => {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const res = await fetch(`/api/taxation/receipts/${receiptId}/retry/`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          'X-CSRFToken': csrfToken,
        },
      });
      const data = (await res.json()) as { success: boolean; last_error?: string };
      if (data.success) {
        setNotice('Receipt retransmitted and fiscalized with KRA!');
      } else {
        setError(`Retransmission failed: ${data.last_error || 'KRA returned error'}`);
      }
      void loadData();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Retry request failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="etims-workspace-tab" className="etims-workspace-tab" role="tabpanel">
      <div className="integration-section-head">
        <div>
          <p className="eyebrow">Kenya Revenue Authority readiness</p>
          <h3>eTIMS Virtual Sales Control Unit (VSCU)</h3>
          <p>
            POS checkout fiscal documents use the server-side, branch-scoped VSCU outbox and item mappings.
            This profile is legacy diagnostic metadata and does not activate checkout fiscalization.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button className="secondary-button" disabled={busy || loading} onClick={() => void testConnection()} type="button">
            <Icon name="check" /> Test Connection
          </button>
          <button className="secondary-button" disabled={busy || loading} onClick={() => void initializeDevice()} type="button">
            <Icon name="network" /> Handshake (Init)
          </button>
        </div>
      </div>

      {notice ? (
        <div className="inline-success" role="status" style={{ margin: '12px 0' }}>
          <Icon name="check" /> {notice}
        </div>
      ) : null}
      {error ? (
        <div className="inline-alert" role="alert" style={{ margin: '12px 0' }}>
          <Icon name="alert" /> {error}
        </div>
      ) : null}

      <div className="inline-alert" role="note" style={{ margin: '12px 0' }}>
        <Icon name="alert" />
        <span>
          <strong>POS eTIMS is not configured by this profile.</strong> Keep it disabled for live checkout.
          Activation needs the installed VSCU endpoint, taxpayer and branch device details, verified item/tax
          mappings, and KRA sandbox and certification evidence in the server-side tenant/branch configuration.
          A green profile status here is not proof that a POS invoice was accepted by KRA.
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.8fr', gap: '16px', margin: '16px 0' }}>
        {/* Form panel */}
        <form className="panel" onSubmit={(e) => void saveProfile(e)} style={{ padding: '16px' }}>
          <h4>Legacy profile metadata</h4>
          <p className="muted-cell" style={{ marginBottom: '16px' }}>
            Credentials remain securely isolated per tenant. Cashiers are never blocked if the KRA server is offline.
          </p>

          <div style={{ display: 'flex', gap: '16px', marginBottom: '12px' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
              <input
                checked={isEnabled}
                onChange={(e) => setIsEnabled(e.target.checked)}
                type="checkbox"
              />
              <strong>Enable eTIMS Fiscalization</strong>
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
              <input
                checked={autoFiscalize}
                onChange={(e) => setAutoFiscalize(e.target.checked)}
                type="checkbox"
              />
              <span>Auto-fiscalize on sale completion</span>
            </label>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '12px' }}>
            <div>
              <label htmlFor="etims-env">Environment</label>
              <select
                id="etims-env"
                onChange={(e) => {
                  const val = e.target.value as 'SANDBOX' | 'PRODUCTION';
                  setEnvironment(val);
                  setBaseUrl(val === 'PRODUCTION' ? 'https://timsvscu.kra.go.ke' : 'https://etims-sbx.kra.go.ke');
                }}
                style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ccc' }}
                value={environment}
              >
                <option value="SANDBOX">Sandbox / Testing</option>
                <option value="PRODUCTION">Production Live</option>
              </select>
            </div>
            <div>
              <label htmlFor="etims-tin">Taxpayer PIN (KRA PIN)</label>
              <input
                id="etims-tin"
                onChange={(e) => setTin(e.target.value)}
                placeholder="e.g. P051234567Z"
                required
                style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ccc' }}
                type="text"
                value={tin}
              >
              </input>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '12px' }}>
            <div>
              <label htmlFor="etims-bhf">Branch ID (bhfId)</label>
              <input
                id="etims-bhf"
                onChange={(e) => setBhfId(e.target.value)}
                placeholder="00"
                required
                style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ccc' }}
                type="text"
                value={bhfId}
              >
              </input>
            </div>
            <div>
              <label htmlFor="etims-dvc">Device Serial Number (dvcSrlNo)</label>
              <input
                id="etims-dvc"
                onChange={(e) => setDvcSrlNo(e.target.value)}
                placeholder="e.g. VSCU-KENYA-001"
                required
                style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ccc' }}
                type="text"
                value={dvcSrlNo}
              >
              </input>
            </div>
          </div>

          <div style={{ marginBottom: '12px' }}>
            <label htmlFor="etims-cmkey">
              Communication Key (cmKey AES Secret) {profile?.has_cm_key ? <span className="truth-label">Configured</span> : null}
            </label>
            <input
              autoComplete="new-password"
              id="etims-cmkey"
              onChange={(e) => setCmKey(e.target.value)}
              placeholder={profile?.has_cm_key ? '•••••••••••••••• (Leave blank to keep current key)' : 'Enter KRA Communication Key'}
              style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ccc' }}
              type="password"
              value={cmKey}
            >
            </input>
          </div>

          <div style={{ marginBottom: '16px' }}>
            <label htmlFor="etims-url">KRA VSCU Base URL</label>
            <input
              id="etims-url"
              onChange={(e) => setBaseUrl(e.target.value)}
              style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ccc' }}
              type="url"
              value={baseUrl}
            >
            </input>
          </div>

          <button className="primary-button" disabled={busy || loading} type="submit">
            <Icon name="check" /> Save Configuration
          </button>
        </form>

        {/* Status and Control Unit Details */}
        <div className="panel" style={{ padding: '16px' }}>
          <h4>VSCU Status & Device Registration</h4>
          <div style={{ margin: '12px 0' }}>
            <p><strong>Status:</strong> {profile?.is_enabled ? <span className="truth-label" style={{ backgroundColor: '#e6fffa', color: '#047481' }}>Active & Enabled</span> : <span className="truth-label">Disabled</span>}</p>
            <p><strong>Handshake Initialized:</strong> {profile?.is_initialized ? 'Yes (selectInitInfo passed)' : 'No'}</p>
            <p><strong>Control Unit (SDC ID):</strong> {profile?.sdc_id || 'Not assigned yet'}</p>
            <p><strong>Machine Reg Code (MRC):</strong> {profile?.mrc_no || 'N/A'}</p>
            <p><strong>Taxpayer Registered:</strong> {profile?.taxpayer_name || 'N/A'}</p>
            <p><strong>Branch Registered:</strong> {profile?.branch_name || 'N/A'}</p>
            <p><strong>Last Fiscal Invoice:</strong> #{profile?.last_invoice_number ?? 0}</p>
            <p><strong>Last Credit Note:</strong> #{profile?.last_credit_note_number ?? 0}</p>
            <p><strong>Last Sync Timestamp:</strong> {profile?.last_sync_at ? new Date(profile.last_sync_at).toLocaleString() : 'Never'}</p>
          </div>

          <div style={{ borderTop: '1px solid #eee', paddingTop: '12px' }}>
            <p className="eyebrow">Tax Category Rules</p>
            <p style={{ fontSize: '11px', color: '#666' }}>
              • <strong>Code A (16% Standard):</strong> Cosmetics, sundries, general goods.<br />
              • <strong>Code E (Exempt 0%):</strong> Human pharmaceutical medicines per First Schedule VAT Act.<br />
              • <strong>Code B (Zero-Rated 0%):</strong> Exports and approved humanitarian supplies.
            </p>
          </div>
        </div>
      </div>

      {/* Receipts Table */}
      <div className="panel" style={{ padding: '16px', marginTop: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <h4>Recent Fiscal Receipts & Submission Queue</h4>
          <button className="secondary-button" disabled={loading} onClick={() => void loadData()} type="button">
            Refresh List
          </button>
        </div>

        {receipts.length === 0 ? (
          <p className="muted-cell">No fiscal receipts recorded yet. Settle a sale on the POS to generate one.</p>
        ) : (
          <div className="table-scroll">
            <table style={{ width: '100%', fontSize: '12px', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ textAlign: 'left', borderBottom: '1px solid #ccc' }}>
                  <th style={{ padding: '6px' }}>Invoice No</th>
                  <th style={{ padding: '6px' }}>Type</th>
                  <th style={{ padding: '6px' }}>Total (KES)</th>
                  <th style={{ padding: '6px' }}>Taxable</th>
                  <th style={{ padding: '6px' }}>VAT</th>
                  <th style={{ padding: '6px' }}>Status</th>
                  <th style={{ padding: '6px' }}>Signature</th>
                  <th style={{ padding: '6px' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {receipts.map((r) => (
                  <tr key={r.id} style={{ borderBottom: '1px solid #eee' }}>
                    <td style={{ padding: '6px', fontWeight: 'bold' }}>
                      #{r.invoice_number}
                      {r.original_invoice_number ? <small style={{ color: '#888', display: 'block' }}>Ref: #{r.original_invoice_number}</small> : null}
                    </td>
                    <td style={{ padding: '6px' }}>{r.receipt_type}</td>
                    <td style={{ padding: '6px' }}>{r.total_amount}</td>
                    <td style={{ padding: '6px' }}>{r.total_taxable_amount}</td>
                    <td style={{ padding: '6px' }}>{r.total_tax_amount}</td>
                    <td style={{ padding: '6px' }}>
                      <span
                        className="truth-label"
                        style={{
                          backgroundColor:
                            r.submission_status === 'SUBMITTED' ? '#d1fae5' : r.submission_status === 'FAILED' ? '#fee2e2' : '#fef3c7',
                          color:
                            r.submission_status === 'SUBMITTED' ? '#065f46' : r.submission_status === 'FAILED' ? '#991b1b' : '#92400e',
                        }}
                      >
                        {r.submission_status}
                      </span>
                      {r.last_error ? <small style={{ color: '#b91c1c', display: 'block', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.last_error}</small> : null}
                    </td>
                    <td style={{ padding: '6px', fontFamily: 'monospace', fontSize: '10px' }}>
                      {r.receipt_signature ? r.receipt_signature.slice(0, 16) + '…' : 'Pending'}
                      {r.qr_code_url ? (
                        <a href={r.qr_code_url} rel="noreferrer" style={{ display: 'block', color: '#0284c7' }} target="_blank">
                          Verify KRA QR
                        </a>
                      ) : null}
                    </td>
                    <td style={{ padding: '6px' }}>
                      {r.submission_status !== 'SUBMITTED' ? (
                        <button
                          className="secondary-button"
                          disabled={busy}
                          onClick={() => void retryReceipt(r.id)}
                          style={{ padding: '2px 8px', fontSize: '11px' }}
                          type="button"
                        >
                          Retry
                        </button>
                      ) : (
                        <span style={{ color: '#10b981' }}>✓ Fiscalized</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
