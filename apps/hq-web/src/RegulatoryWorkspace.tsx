import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';

import type { HQOverview, RegulatoryAction, RegulatoryAlert, RegulatoryImpact } from './api.js';
import {
  activateRegulatoryAlert,
  closeRegulatoryImpact,
  HQApiError,
  ingestRegulatoryAlert,
  loadRegulatoryAlerts,
  loadRegulatoryImpacts,
  quarantineRegulatoryBatches,
  quarantineTenantRegulatoryImpact,
  recordRegulatoryAction,
} from './api.js';
import { Icon } from './icons.js';

interface RegulatoryWorkspaceProps {
  csrfToken: string;
  overview: HQOverview;
}

type RegulatoryTab = 'alerts' | 'tenant';
type RecallActionType = 'PATIENT_CONTACT' | 'PRODUCT_RETURN' | 'DESTRUCTION' | 'REGULATORY_REPORT' | 'STOCK_RELEASE';

type DialogMode =
  | { readonly kind: 'ingest' }
  | { readonly kind: 'activate'; readonly alert: RegulatoryAlert }
  | { readonly kind: 'platform-quarantine'; readonly alert: RegulatoryAlert }
  | { readonly kind: 'tenant-quarantine'; readonly impact: RegulatoryImpact }
  | { readonly kind: 'action'; readonly impact: RegulatoryImpact; readonly actionType: RecallActionType }
  | { readonly kind: 'close'; readonly impact: RegulatoryImpact }
  | null;

const ACTION_LABELS: Readonly<Record<RecallActionType, string>> = {
  PATIENT_CONTACT: 'Prior dispense trace & patient contact',
  PRODUCT_RETURN: 'Product returned to supplier',
  DESTRUCTION: 'Product destroyed',
  REGULATORY_REPORT: 'Regulatory report submitted',
  STOCK_RELEASE: 'Release recalled stock',
};

export function RegulatoryWorkspace({ csrfToken, overview }: RegulatoryWorkspaceProps) {
  const isOwner = overview.is_platform_owner === true;
  const selectableTenants = useMemo(
    () => overview.network_items.filter((tenant) => tenant.status === 'ACTIVE'),
    [overview.network_items],
  );
  const [tenantId, setTenantId] = useState(
    overview.tenant_id || selectableTenants[0]?.id || '',
  );
  const [activeTab, setActiveTab] = useState<RegulatoryTab>(isOwner ? 'alerts' : 'tenant');
  const [alerts, setAlerts] = useState<readonly RegulatoryAlert[] | null>(null);
  const [impacts, setImpacts] = useState<readonly RegulatoryImpact[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [dialog, setDialog] = useState<DialogMode>(null);
  const permittedDialog = dialog && (isOwner || ['tenant-quarantine', 'action', 'close'].includes(dialog.kind)) ? dialog : null;

  useEffect(() => {
    if (!isOwner) {
      setActiveTab('tenant');
      setAlerts(null);
      setDialog(current => current && ['ingest', 'activate', 'platform-quarantine'].includes(current.kind) ? null : current);
    }
  }, [isOwner]);

  const reload = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setFailed(false);
    try {
      const [nextAlerts, nextImpacts] = await Promise.all([
        isOwner ? loadRegulatoryAlerts(signal) : Promise.resolve(null),
        tenantId ? loadRegulatoryImpacts(tenantId, signal) : Promise.resolve([]),
      ]);
      if (!signal?.aborted) {
        setAlerts(nextAlerts);
        setImpacts(nextImpacts);
      }
    } catch {
      if (!signal?.aborted) setFailed(true);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [isOwner, tenantId]);

  useEffect(() => {
    const controller = new AbortController();
    setImpacts(null);
    void reload(controller.signal);
    return () => controller.abort();
  }, [reload]);

  useEffect(() => {
    if (overview.tenant_id && overview.tenant_id !== tenantId) setTenantId(overview.tenant_id);
  }, [overview.tenant_id, tenantId]);

  const run = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!dialog) return;
    const values = new FormData(event.currentTarget);
    const field = (name: string) => String(values.get(name) ?? '').trim();
    setBusy(true);
    setError('');
    setNotice('');
    try {
      if (dialog.kind === 'ingest') {
        await ingestRegulatoryAlert({
          alert_reference: field('alert_reference'),
          title: field('title'),
          severity: field('severity'),
          issuing_regulator: field('issuing_regulator'),
          regulator_issue_date: field('regulator_issue_date') || null,
          ppb_registration_number: field('ppb_registration_number'),
          gtin: field('gtin'),
          product_name: field('product_name'),
          manufacturer_name: field('manufacturer_name'),
          affected_batches: field('affected_batches').split(/[\n,]+/).map((value) => value.trim()).filter(Boolean),
          description: field('description'),
          recommended_action: field('recommended_action'),
        }, csrfToken);
        setNotice('Draft alert ingested. Review the source and activate it to create tenant assessments.');
      } else if (dialog.kind === 'activate') {
        await activateRegulatoryAlert(dialog.alert.id, csrfToken);
        setNotice(`${dialog.alert.alert_reference} activated. An assessment case is now available for each active tenant.`);
      } else if (dialog.kind === 'platform-quarantine') {
        const batches = field('affected_batches').split(/[\n,]+/).map((value) => value.trim()).filter(Boolean);
        await quarantineRegulatoryBatches(dialog.alert.id, {
          tenant_id: field('tenant_id'),
          affected_batches: batches,
          prior_dispense_trace_required: values.get('prior_dispense_trace_required') === 'on',
        }, csrfToken);
        setNotice(`${batches.length} batch number${batches.length === 1 ? '' : 's'} sent for an inventory recall hold.`);
      } else if (dialog.kind === 'tenant-quarantine') {
        const batches = field('affected_batches').split(/[\n,]+/).map((value) => value.trim()).filter(Boolean);
        await quarantineTenantRegulatoryImpact(dialog.impact.id, {
          affected_batches: batches,
          prior_dispense_trace_required: values.get('prior_dispense_trace_required') === 'on',
        }, csrfToken, tenantId);
        setNotice(`${batches.length} batch number${batches.length === 1 ? '' : 's'} sent for an inventory recall hold.`);
      } else if (dialog.kind === 'action') {
        const evidenceReference = field('evidence_reference');
        const action: RegulatoryAction = await recordRegulatoryAction(
          dialog.impact.id,
          {
            action_type: dialog.actionType,
            notes: field('notes'),
            evidence_payload: dialog.actionType === 'PATIENT_CONTACT'
              ? { reference: evidenceReference, patient_count: Number(field('patient_count')) }
              : evidenceReference ? { reference: evidenceReference } : {},
          },
          csrfToken,
          tenantId,
        );
        setImpacts((current) => current?.map((impact) => impact.id === dialog.impact.id
          ? { ...impact, actions: [action, ...impact.actions], state: dialog.actionType === 'STOCK_RELEASE' ? 'RELEASED' : impact.state }
          : impact) ?? current);
        setNotice(`${ACTION_LABELS[dialog.actionType]} recorded with audit evidence.`);
      } else if (dialog.kind === 'close') {
        await closeRegulatoryImpact(dialog.impact.id, {
          regulator_withdrawal_reference: field('regulator_withdrawal_reference'),
          compliance_review_notes: field('compliance_review_notes'),
        }, csrfToken, tenantId);
        setNotice(`${dialog.impact.alert_reference} closed. Releasing held stock remains a separate action.`);
      }

      setDialog(null);
      await reload();
    } catch (cause) {
      setError(cause instanceof HQApiError || cause instanceof Error
        ? cause.message
        : 'The regulatory workflow action could not be completed.');
    } finally {
      setBusy(false);
    }
  };

  const openDialog = (next: Exclude<DialogMode, null>) => {
    setError('');
    setDialog(next);
  };

  const pendingCount = impacts?.filter((impact) => ['PENDING', 'QUARANTINED', 'UNDER_REVIEW'].includes(impact.state)).length ?? 0;
  const activeAlerts = alerts?.filter((alert) => alert.status === 'ACTIVE').length ?? 0;
  const canChooseTenant = isOwner && selectableTenants.length > 1;

  return (
    <div className="regulatory-workspace">
      <section className="panel regulatory-header">
        <div>
          <p className="eyebrow">Regulatory safety workflow</p>
          <h2>Alerts, recalls &amp; response evidence</h2>
          <p>Capture regulator notices, assess tenant exposure, hold matching batches, document response, then close only with withdrawal evidence.</p>
        </div>
        <div className="regulatory-header-actions">
          <span className="truth-label">Manual intake · LOCAL_RECALL_WORKFLOW_NO_REGULATOR_FEED</span>
          {isOwner ? <button className="primary-button" onClick={() => openDialog({ kind: 'ingest' })} type="button"><Icon name="plus" /> Ingest alert</button> : null}
        </div>
      </section>

      <section className="regulatory-steps" aria-label="Regulatory alert workflow">
        <div><b>1</b><span><strong>Ingest</strong><small>Capture the regulator notice as a draft.</small></span></div>
        <div><b>2</b><span><strong>Activate</strong><small>Create an assessment case per active tenant.</small></span></div>
        <div><b>3</b><span><strong>Hold &amp; respond</strong><small>Match real batch records and preserve evidence.</small></span></div>
        <div><b>4</b><span><strong>Close &amp; release</strong><small>Closure needs withdrawal proof; release is separate.</small></span></div>
      </section>

      {notice ? <p className="inline-alert regulatory-notice" role="status"><Icon name="check" /> {notice}</p> : null}
      {failed ? <p className="inline-alert regulatory-error" role="alert"><Icon name="alert" /> Could not load regulatory alerts or tenant response cases. Check the active workspace and permissions, then retry.</p> : null}

      <section className="panel regulatory-board">
        <header className="regulatory-board-heading">
          <div className="regulatory-tabs" role="tablist" aria-label="Regulatory work queues">
            {isOwner ? <button aria-selected={activeTab === 'alerts'} className={activeTab === 'alerts' ? 'regulatory-tab is-active' : 'regulatory-tab'} onClick={() => setActiveTab('alerts')} role="tab" type="button">Regulator alerts <b>{alerts?.length ?? '—'}</b></button> : null}
            <button aria-selected={activeTab === 'tenant'} className={activeTab === 'tenant' ? 'regulatory-tab is-active' : 'regulatory-tab'} onClick={() => setActiveTab('tenant')} role="tab" type="button">Tenant response <b>{pendingCount}</b></button>
          </div>
          {canChooseTenant ? (
            <label className="regulatory-tenant-select"><span>Tenant case view</span><select onChange={(event) => setTenantId(event.target.value)} value={tenantId}>{selectableTenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}</select></label>
          ) : null}
        </header>

        {loading ? <p className="panel-note">Loading regulatory workflow records…</p> : null}
        {!loading && activeTab === 'alerts' ? (
          isOwner ? (
            <>
              <div className="regulatory-summary"><span><strong>{alerts?.length ?? 0}</strong> captured notices</span><span><strong>{activeAlerts}</strong> active alerts</span><span><strong>{pendingCount}</strong> open cases in selected tenant</span></div>
              {alerts?.length ? (
                <div className="table-scroll"><table><thead><tr><th>Notice</th><th>Product match</th><th>Severity</th><th>Status</th><th>Source truth</th><th>Action</th></tr></thead><tbody>
                  {alerts.map((alert) => (
                    <tr key={alert.id}>
                      <td><strong>{alert.title}</strong><small className="row-detail"><code>{alert.alert_reference}</code> · {alert.issuing_regulator ?? 'Regulator'}{alert.regulator_issue_date ? ` · ${alert.regulator_issue_date}` : ''}</small></td>
                      <td><span>{alert.product_name || 'Product not specified'}</span><small className="row-detail">{alert.gtin ? `GTIN ${alert.gtin}` : ''}{alert.ppb_registration_number ? ` · PPB ${alert.ppb_registration_number}` : ''}</small></td>
                      <td><StatusPill value={alert.severity} /></td>
                      <td><StatusPill value={alert.status} /></td>
                      <td><small>{alert.truth_label.replaceAll('_', ' ')}</small></td>
                      <td><div className="regulatory-row-actions">
                        {['DRAFT', 'UNDER_REVIEW'].includes(alert.status) ? <button className="business-action" onClick={() => openDialog({ kind: 'activate', alert })} type="button">Activate</button> : null}
                        {alert.status === 'ACTIVE' ? <button className="secondary-button" onClick={() => openDialog({ kind: 'platform-quarantine', alert })} type="button">Quarantine batches</button> : null}
                      </div></td>
                    </tr>
                  ))}
                </tbody></table></div>
              ) : <EmptyState title="No regulator notices captured" detail="Use Ingest alert to enter a notice from PPB or another regulator. The screen labels manual intake until a verified live feed is connected." />}
            </>
          ) : <EmptyState title="Global alert register is restricted" detail="This tenant workspace can review alerts that have been activated and assigned to its response queue." />
        ) : null}

        {!loading && activeTab === 'tenant' ? (
          impacts?.length ? (
            <div className="regulatory-impact-list">{impacts.map((impact) => <ImpactCard impact={impact} key={impact.id} onAction={(actionType) => openDialog({ kind: 'action', impact, actionType })} onClose={() => openDialog({ kind: 'close', impact })} onQuarantine={() => openDialog({ kind: 'tenant-quarantine', impact })} />)}</div>
          ) : <EmptyState title="No tenant response cases" detail="When an alert is activated, the compliance team will see assessment cases here. Confirmed affected batches move into an inventory recall hold." />
        ) : null}
      </section>

      {permittedDialog ? <RegulatoryDialog busy={busy} dialog={permittedDialog} error={error} onClose={() => { if (!busy) setDialog(null); }} onSubmit={run} selectedTenantId={tenantId} tenants={selectableTenants} /> : null}
    </div>
  );
}

function ImpactCard({ impact, onAction, onClose, onQuarantine }: {
  readonly impact: RegulatoryImpact;
  readonly onAction: (action: RecallActionType) => void;
  readonly onClose: () => void;
  readonly onQuarantine: () => void;
}) {
  const isOpen = ['QUARANTINED', 'UNDER_REVIEW'].includes(impact.state);
  const traceRecorded = impact.actions.some((action) => (
    action.action_type === 'PATIENT_CONTACT'
    && typeof action.evidence_payload.patient_count === 'number'
    && typeof action.evidence_payload.reference === 'string'
    && action.evidence_payload.reference.trim().length > 0
    && (!impact.quarantined_at || new Date(action.performed_at).getTime() >= new Date(impact.quarantined_at).getTime())
  ));
  const canClose = isOpen && (!impact.prior_dispense_trace_required || traceRecorded);
  const actionChoices: RecallActionType[] = isOpen
    ? ['PATIENT_CONTACT', 'PRODUCT_RETURN', 'DESTRUCTION', 'REGULATORY_REPORT']
    : impact.state === 'RESOLVED' ? ['STOCK_RELEASE'] : [];

  return (
    <article className="regulatory-impact-card">
      <header><div><code>{impact.alert_reference}</code><h3>{impact.alert_title}</h3></div><StatusPill value={impact.state} /></header>
      <div className="regulatory-impact-meta"><span>Tenant <strong>{impact.tenant_name}</strong></span><span>Severity <strong>{impact.alert_severity}</strong></span><span>Batch records <strong>{impact.quarantined_stock_count}</strong></span></div>
      {impact.affected_batches.length ? <p className="regulatory-batches"><strong>Held batches</strong> {impact.affected_batches.join(', ')}</p> : <p className="regulatory-batches">No batch hold recorded yet. Confirmed affected batches are required to quarantine stock.</p>}
      {impact.prior_dispense_trace_required ? <p className="regulatory-trace-note">Prior dispensing trace is required. Record the affected patient count and evidence reference manually; automatic historical dispensing search is not connected.</p> : null}
      {impact.actions.length ? <div className="regulatory-action-history"><strong>Response log</strong>{impact.actions.map((action) => <ActionRow action={action} key={action.id} />)}</div> : null}
      <footer className="regulatory-card-actions">
        {actionChoices.map((action) => <button className={action === 'STOCK_RELEASE' ? 'secondary-button' : 'business-action'} key={action} onClick={() => onAction(action)} type="button">{ACTION_LABELS[action]}</button>)}
        {impact.prior_dispense_trace_required && !traceRecorded ? <span>Prior dispense trace evidence is required before closure.</span> : null}
        {canClose ? <button className="secondary-button" onClick={onClose} type="button">Close with withdrawal evidence</button> : null}
        {impact.state === 'PENDING' ? <button className="business-action" onClick={onQuarantine} type="button">Confirm affected batches</button> : null}
        {impact.state === 'RELEASED' ? <span>Recall hold released after closure</span> : null}
      </footer>
    </article>
  );
}

function ActionRow({ action }: { readonly action: RegulatoryAction }) {
  const reference = action.evidence_payload.reference;
  const patientCount = action.evidence_payload.patient_count;
  return <div className="regulatory-action-row"><span><strong>{ACTION_LABELS[action.action_type as RecallActionType] ?? action.action_type.replaceAll('_', ' ')}</strong><small>{action.performed_by_name} · {new Date(action.performed_at).toLocaleString()}{typeof patientCount === 'number' ? ` · ${patientCount} patients traced` : ''}</small></span>{typeof reference === 'string' ? <code>{reference}</code> : null}</div>;
}

function RegulatoryDialog({
  busy,
  dialog,
  error,
  onClose,
  onSubmit,
  selectedTenantId,
  tenants,
}: {
  readonly busy: boolean;
  readonly dialog: Exclude<DialogMode, null>;
  readonly error: string;
  readonly onClose: () => void;
  readonly onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  readonly selectedTenantId: string;
  readonly tenants: readonly HQOverview['network_items'][number][];
}) {
  const title = dialog.kind === 'ingest' ? 'Ingest regulator notice'
    : dialog.kind === 'activate' ? `Activate ${dialog.alert.alert_reference}`
      : dialog.kind === 'platform-quarantine' || dialog.kind === 'tenant-quarantine' ? 'Quarantine affected batches'
        : dialog.kind === 'action' ? ACTION_LABELS[dialog.actionType]
          : `Close ${dialog.impact.alert_reference}`;
  const isConfirmation = dialog.kind === 'activate';

  return (
    <div className="business-dialog-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target && !busy) onClose(); }} role="presentation">
      <section aria-labelledby="regulatory-dialog-title" aria-modal="true" className="business-dialog regulatory-dialog" role="dialog">
        <header><div><p className="eyebrow">Governed regulatory workflow</p><h2 id="regulatory-dialog-title">{title}</h2></div><button aria-label="Close dialog" disabled={busy} onClick={onClose} type="button"><Icon name="close" /></button></header>
        {isConfirmation ? <p className="business-dialog-confirm"><Icon name="shield" /> Activation publishes this manual notice and creates a response assessment for each active tenant. It does not assume a batch match.</p> : null}
        {dialog.kind === 'action' && dialog.actionType === 'STOCK_RELEASE' ? <p className="business-dialog-confirm"><Icon name="shield" /> The impact must already be closed with a regulator withdrawal reference. This action updates matching inventory batches and records a release event.</p> : null}
        {dialog.kind === 'close' ? <p className="business-dialog-confirm"><Icon name="shield" /> Closing does not release recalled stock. Record the separate stock release after closure if the regulator confirms withdrawal.</p> : null}
        <form onSubmit={onSubmit}>
          {dialog.kind === 'ingest' ? <IngestFields /> : null}
          {dialog.kind === 'platform-quarantine' || dialog.kind === 'tenant-quarantine' ? <>
            {dialog.kind === 'platform-quarantine' ? <label className="business-field"><span>Tenant receiving the recall hold<b>Required</b></span><select name="tenant_id" required defaultValue={selectedTenantId || tenants[0]?.id || ''}>{tenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}</select></label> : null}
            <label className="business-field"><span>Manufacturer batch numbers<b>Required</b></span><textarea autoFocus name="affected_batches" placeholder="One batch number per line or comma-separated" required rows={3} defaultValue={dialog.kind === 'platform-quarantine' ? dialog.alert.affected_batches?.join('\n') ?? '' : dialog.impact.affected_batches.join('\n')} /></label>
            <label className="business-checkbox"><input name="prior_dispense_trace_required" type="checkbox" /><span>Mark prior dispensing trace as required</span></label>
            <p className="form-hint">Each batch must exist in the selected tenant’s inventory. This creates an append-only recall hold and blocks eligible stock allocation.</p>
          </> : null}
          {dialog.kind === 'action' ? <>
            <label className="business-field"><span>Response notes<b>Required</b></span><textarea autoFocus name="notes" placeholder="Describe what was done, when, and by whom." required rows={3} /></label>
            {dialog.actionType === 'PATIENT_CONTACT' ? <label className="business-field"><span>Patients identified in trace<b>Required</b></span><input min="0" name="patient_count" placeholder="0" required step="1" type="number" /></label> : null}
            <label className="business-field"><span>{dialog.actionType === 'PATIENT_CONTACT' ? 'Trace / contact evidence reference' : 'Evidence reference'}{dialog.actionType === 'PATIENT_CONTACT' ? <b>Required</b> : null}</span><input name="evidence_reference" placeholder="Document ID, supplier return, report reference" required={dialog.actionType === 'PATIENT_CONTACT'} /></label>
          </> : null}
          {dialog.kind === 'close' ? <>
            <label className="business-field"><span>Regulator withdrawal reference<b>Required</b></span><input autoFocus name="regulator_withdrawal_reference" placeholder="PPB withdrawal or clearance reference" required /></label>
            <label className="business-field"><span>Compliance review notes<b>Required</b></span><textarea name="compliance_review_notes" placeholder="Record review outcome and supporting evidence." required rows={3} /></label>
          </> : null}
          {error ? <p className="business-dialog-error" role="alert"><Icon name="alert" /> {error}</p> : null}
          <footer><button className="secondary-button" disabled={busy} onClick={onClose} type="button">Cancel</button><button className="primary-button" disabled={busy} type="submit">{busy ? 'Saving…' : dialog.kind === 'activate' ? 'Activate alert' : dialog.kind === 'platform-quarantine' || dialog.kind === 'tenant-quarantine' ? 'Create inventory hold' : dialog.kind === 'close' ? 'Close response case' : dialog.kind === 'action' ? 'Record response' : 'Save draft alert'}</button></footer>
        </form>
      </section>
    </div>
  );
}

function IngestFields() {
  return <>
    <div className="regulatory-form-grid">
      <label className="business-field"><span>Regulator reference<b>Required</b></span><input autoFocus name="alert_reference" maxLength={100} placeholder="PPB/REC/2026/001" required /></label>
      <label className="business-field"><span>Severity<b>Required</b></span><select name="severity" required defaultValue="HIGH"><option value="CRITICAL">Critical</option><option value="HIGH">High</option><option value="MEDIUM">Medium</option><option value="LOW">Low</option></select></label>
      <label className="business-field"><span>Issuing regulator</span><input name="issuing_regulator" defaultValue="PPB" maxLength={80} /></label>
      <label className="business-field"><span>Issue date</span><input name="regulator_issue_date" type="date" /></label>
      <label className="business-field"><span>Product name</span><input name="product_name" maxLength={300} /></label>
      <label className="business-field"><span>GTIN-14</span><input inputMode="numeric" maxLength={14} name="gtin" pattern="[0-9]{14}" placeholder="14 numeric digits" /></label>
      <label className="business-field"><span>PPB registration</span><input name="ppb_registration_number" maxLength={80} /></label>
      <label className="business-field"><span>Manufacturer</span><input name="manufacturer_name" maxLength={200} /></label>
    </div>
    <label className="business-field"><span>Notice title<b>Required</b></span><input name="title" maxLength={300} placeholder="Product safety alert or recall title" required /></label>
    <label className="business-field"><span>Affected batch numbers</span><textarea name="affected_batches" placeholder="One batch number per line" rows={2} /></label>
    <label className="business-field"><span>Notice details</span><textarea name="description" placeholder="Copy the relevant notice details and source context." rows={3} /></label>
    <label className="business-field"><span>Recommended action</span><textarea name="recommended_action" placeholder="Regulator instructions for pharmacies" rows={2} /></label>
    <p className="form-hint">This creates an auditable draft. Confirm the regulator source before activation; no automated regulator feed is connected.</p>
  </>;
}

function StatusPill({ value }: { readonly value: string }) {
  const tone = value === 'CRITICAL' || value === 'RECALLED' ? 'rose'
    : ['HIGH', 'QUARANTINED', 'UNDER_REVIEW'].includes(value) ? 'amber'
      : ['ACTIVE', 'RELEASED', 'RESOLVED'].includes(value) ? 'teal' : 'neutral';
  return <span className={`regulatory-status status-${tone}`}>{value.replaceAll('_', ' ')}</span>;
}

function EmptyState({ title, detail }: { readonly title: string; readonly detail: string }) {
  return <div className="regulatory-empty"><Icon name="shield" /><div><strong>{title}</strong><p>{detail}</p></div></div>;
}
