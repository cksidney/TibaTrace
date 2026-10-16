import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';

import { Icon } from './icons.js';
import { EtimsWorkspaceTab } from './EtimsWorkspaceTab.js';

interface IntegrationWorkspaceProps {
  csrfToken: string;
}

type ProviderState =
  | 'REQUESTED' | 'UNDER_REVIEW' | 'SECURITY_REVIEW' | 'SANDBOX_CONFIGURED'
  | 'SANDBOX_TESTING' | 'SANDBOX_PASSED' | 'CERTIFICATION_REVIEW'
  | 'SECURITY_APPROVED' | 'PRODUCTION_APPROVED' | 'ACTIVE' | 'SUSPENDED'
  | 'REVOKED' | 'DECOMMISSIONED' | 'REJECTED';

interface ProviderConfiguration {
  readonly id: string;
  readonly provider_type: string;
  readonly environment: 'SANDBOX' | 'PRODUCTION';
  readonly display_name: string;
  readonly activation_state: ProviderState;
  readonly truth_label: string;
  readonly is_operational: boolean;
  readonly activated_at: string | null;
  readonly notes: string;
  readonly configuration: Record<string, unknown>;
  readonly latest_health: HealthSnapshot | null;
  readonly endpoints: readonly ProviderEndpoint[];
  readonly credential_references: readonly CredentialReference[];
}

interface ActivationRequest {
  readonly id: string;
  readonly provider: string;
  readonly requested_by: string;
  readonly requested_by_name: string;
  readonly requested_at: string;
  readonly state: ProviderState;
  readonly justification: string;
  readonly sandbox_evidence: Record<string, unknown>;
  readonly security_review_notes: string;
  readonly notes: string;
  readonly decisions: readonly {
    readonly id: string;
    readonly decided_by_name: string;
    readonly decided_at: string;
    readonly from_state: ProviderState;
    readonly to_state: ProviderState;
    readonly decision_notes: string;
    readonly truth_label: string;
  }[];
}

interface DeadLetter {
  readonly id: string;
  readonly message: string;
  readonly dead_lettered_at: string;
  readonly dead_letter_reason: string;
  readonly replayed_at: string | null;
  readonly replay_notes: string;
}

interface HealthSnapshot {
  readonly id: string;
  readonly checked_at: string;
  readonly is_reachable: boolean;
  readonly response_time_ms: number | null;
  readonly status_code: number | null;
  readonly error_detail: string;
  readonly truth_label: string;
}

interface ProviderEndpoint {
  readonly id: string;
  readonly name: string;
  readonly base_url: string;
  readonly allowed_hosts: readonly string[];
  readonly is_active: boolean;
}

interface CredentialReference {
  readonly id: string;
  readonly credential_type: string;
  readonly reference: string;
  readonly is_configured: boolean;
  readonly configured_at: string | null;
}

interface ProviderResources {
  readonly endpoints: readonly ProviderEndpoint[];
  readonly credentials: readonly CredentialReference[];
}

interface ConnectivityResult {
  readonly provider: string;
  readonly endpoints: readonly {
    readonly endpoint_name: string;
    readonly base_url: string;
    readonly allowed_hosts: readonly string[];
    readonly is_allowed_hosts_configured: boolean;
    readonly status: string;
  }[];
}

type IntegrationTab = 'providers' | 'etims' | 'activations' | 'compliance' | 'reports' | 'evidence' | 'dlq' | 'rules';
type DialogState =
  | { readonly kind: 'provider' }
  | { readonly kind: 'activation'; readonly provider: ProviderConfiguration }
  | { readonly kind: 'advance'; readonly activation: ActivationRequest }
  | { readonly kind: 'endpoint'; readonly provider: ProviderConfiguration }
  | { readonly kind: 'credential'; readonly provider: ProviderConfiguration }
  | { readonly kind: 'replay'; readonly deadLetter: DeadLetter }
  | { readonly kind: 'kill-switch'; readonly provider: ProviderConfiguration }
  | null;

const PROVIDER_TYPES = [
  ['DHA_HIE', 'DHA Health Information Exchange'],
  ['DHA_HWR', 'DHA Health Worker Registry'],
  ['PPB_PREMISES', 'PPB Premises Registry'],
  ['PPB_PRODUCT_REGISTER', 'PPB Product Register'],
  ['PPB_REGULATORY_ALERTS', 'PPB Regulatory Alerts'],
  ['PPB_RECALLS', 'PPB Product Recalls'],
  ['SHA_INSURER', 'SHA / approved insurer'],
  ['MPESA', 'Safaricom M-PESA'],
] as const;

const STATE_LABELS: Record<ProviderState, string> = {
  REQUESTED: 'Requested', UNDER_REVIEW: 'Under review', SECURITY_REVIEW: 'Security review',
  SANDBOX_CONFIGURED: 'Sandbox configured', SANDBOX_TESTING: 'Sandbox testing',
  SANDBOX_PASSED: 'Sandbox passed', CERTIFICATION_REVIEW: 'Certification review',
  SECURITY_APPROVED: 'Security approved', PRODUCTION_APPROVED: 'Production approved',
  ACTIVE: 'Active', SUSPENDED: 'Suspended', REVOKED: 'Revoked',
  DECOMMISSIONED: 'Decommissioned', REJECTED: 'Rejected',
};

// Keep this list aligned with VALID_TRANSITIONS on the API. The server remains authoritative.
const NEXT_STATES: Partial<Record<ProviderState, readonly ProviderState[]>> = {
  REQUESTED: ['UNDER_REVIEW', 'REJECTED'],
  UNDER_REVIEW: ['SECURITY_REVIEW', 'SANDBOX_CONFIGURED', 'REJECTED'],
  SECURITY_REVIEW: ['SANDBOX_CONFIGURED', 'REJECTED'],
  SANDBOX_CONFIGURED: ['SANDBOX_TESTING', 'REJECTED'],
  SANDBOX_TESTING: ['SANDBOX_PASSED', 'SANDBOX_CONFIGURED', 'REJECTED'],
  SANDBOX_PASSED: ['CERTIFICATION_REVIEW', 'SECURITY_APPROVED', 'REJECTED'],
  CERTIFICATION_REVIEW: ['SECURITY_APPROVED', 'PRODUCTION_APPROVED', 'REJECTED'],
  SECURITY_APPROVED: ['PRODUCTION_APPROVED', 'REJECTED'],
  PRODUCTION_APPROVED: ['ACTIVE', 'REJECTED'],
  ACTIVE: ['SUSPENDED', 'REVOKED', 'DECOMMISSIONED'],
  SUSPENDED: ['ACTIVE', 'REVOKED', 'DECOMMISSIONED'],
};

const TERMINAL_STATES = new Set<ProviderState>(['REJECTED', 'REVOKED', 'DECOMMISSIONED']);
const TABS: readonly { readonly id: IntegrationTab; readonly label: string }[] = [
  { id: 'providers', label: 'Providers' },
  { id: 'etims', label: 'KRA eTIMS VSCU' },
  { id: 'activations', label: 'Activation workflow' },
  { id: 'compliance', label: 'Compliance status' },
  { id: 'reports', label: 'Reports' },
  { id: 'evidence', label: 'Certification evidence' },
  { id: 'dlq', label: 'Dead-letter queue' },
  { id: 'rules', label: 'Governance rules' },
];

function rows<T>(value: unknown): T[] {
  if (Array.isArray(value)) return value as T[];
  if (value && typeof value === 'object' && Array.isArray((value as { results?: unknown }).results)) {
    return (value as { results: T[] }).results;
  }
  return [];
}

async function readJson<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body && typeof body === 'object' && 'detail' in body
      ? String((body as { detail: unknown }).detail)
      : body && typeof body === 'object'
        ? Object.entries(body as Record<string, unknown>).map(([field, messages]) => `${field}: ${Array.isArray(messages) ? messages.join(', ') : String(messages)}`).join(' · ')
        : `Request failed (${response.status}).`;
    throw new Error(detail);
  }
  return body as T;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'The integration service could not complete the request.';
}

function formatDate(value: string | null | undefined): string {
  if (!value) return 'Not recorded';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function endpointHostIsAllowlisted(endpoint: ProviderEndpoint): boolean {
  try {
    const hostname = new URL(endpoint.base_url).hostname.toLowerCase().replace(/\.$/, '');
    return endpoint.allowed_hosts.some((host) => host.toLowerCase().replace(/\.$/, '') === hostname);
  } catch {
    return false;
  }
}

function labelForState(state: ProviderState): string {
  return STATE_LABELS[state] ?? state.replaceAll('_', ' ').toLowerCase();
}

export function IntegrationWorkspace({ csrfToken }: IntegrationWorkspaceProps) {
  const [providers, setProviders] = useState<ProviderConfiguration[]>([]);
  const [activations, setActivations] = useState<ActivationRequest[]>([]);
  const [deadLetters, setDeadLetters] = useState<DeadLetter[]>([]);
  const [health, setHealth] = useState<ReadonlyMap<string, HealthSnapshot>>(new Map());
  const [providerResources, setProviderResources] = useState<ReadonlyMap<string, ProviderResources>>(new Map());
  const [activeTab, setActiveTab] = useState<IntegrationTab>('providers');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [dialog, setDialog] = useState<DialogState>(null);
  const [connectivity, setConnectivity] = useState<ConnectivityResult | null>(null);
  const [decision, setDecision] = useState({ toState: '' as ProviderState | '', notes: '', evidenceJson: '' });
  const [dialogError, setDialogError] = useState('');

  const loadWorkspace = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [providerResponse, activationResponse, dlqResponse] = await Promise.all([
        fetch('/api/nif/platform/providers/', { headers: { Accept: 'application/json' }, credentials: 'same-origin' }),
        fetch('/api/nif/platform/activations/', { headers: { Accept: 'application/json' }, credentials: 'same-origin' }),
        fetch('/api/nif/platform/dead-letters/', { headers: { Accept: 'application/json' }, credentials: 'same-origin' }),
      ]);
      const [nextProviders, nextActivations, nextDeadLetters] = await Promise.all([
        readJson<unknown>(providerResponse), readJson<unknown>(activationResponse), readJson<unknown>(dlqResponse),
      ]);
      const providerItems = rows<ProviderConfiguration>(nextProviders);
      setProviders(providerItems);
      setActivations(rows<ActivationRequest>(nextActivations));
      setDeadLetters(rows<DeadLetter>(nextDeadLetters));
      setHealth(new Map(providerItems.filter((provider) => provider.latest_health).map((provider) => [provider.id, provider.latest_health!] as const)));
      setProviderResources(new Map(providerItems.map((provider) => [provider.id, {
        endpoints: provider.endpoints,
        credentials: provider.credential_references,
      }] as const)));
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void loadWorkspace(); }, [loadWorkspace]);

  const activeRequests = useMemo(() => activations.filter((item) => !TERMINAL_STATES.has(item.state) && item.state !== 'ACTIVE' && item.state !== 'SUSPENDED'), [activations]);
  const pendingDeadLetters = useMemo(() => deadLetters.filter((item) => !item.replayed_at), [deadLetters]);
  const providerById = useMemo(() => new Map(providers.map((provider) => [provider.id, provider])), [providers]);
  const activeProviders = providers.filter((provider) => provider.is_operational).length;

  const mutate = async (path: string, body: Record<string, unknown>, method = 'POST') => {
    const response = await fetch(path, {
      method,
      credentials: 'same-origin',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
      body: JSON.stringify(body),
    });
    return readJson<unknown>(response);
  };

  const submitDialog = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!dialog) return;
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setDialogError('');
    setNotice('');
    try {
      if (dialog.kind === 'provider') {
        const providerType = String(form.get('provider_type') ?? '');
        const environment = String(form.get('environment') ?? 'SANDBOX');
        const displayName = String(form.get('display_name') ?? '').trim();
        const notes = String(form.get('notes') ?? '').trim();
        await mutate('/api/nif/platform/providers/', {
          provider_type: providerType, environment, display_name: displayName, notes, configuration: {},
        });
        setNotice(`${displayName} provider configuration created. Credential values must remain in the approved secrets manager.`);
      } else if (dialog.kind === 'activation') {
        const justification = String(form.get('justification') ?? '').trim();
        await mutate('/api/nif/platform/activations/', { provider: dialog.provider.id, justification });
        setNotice(`Activation request opened for ${dialog.provider.display_name}.`);
      } else if (dialog.kind === 'advance') {
        const toState = String(form.get('to_state') ?? '') as ProviderState;
        const notes = String(form.get('notes') ?? '').trim();
        const evidenceRaw = String(form.get('sandbox_evidence') ?? '').trim();
        let sandboxEvidence: Record<string, unknown> = {};
        if (evidenceRaw) {
          const parsed: unknown = JSON.parse(evidenceRaw);
          if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('Evidence must be a JSON object.');
          sandboxEvidence = parsed as Record<string, unknown>;
        }
        await mutate(`/api/nif/platform/activations/${dialog.activation.id}/advance/`, {
          to_state: toState, notes, sandbox_evidence: sandboxEvidence,
        });
        setNotice(`Activation moved to ${labelForState(toState)}. The decision is recorded in the audit trail.`);
      } else if (dialog.kind === 'endpoint') {
        const allowedHosts = String(form.get('allowed_hosts') ?? '').split(/[\n,]/).map((host) => host.trim()).filter(Boolean);
        await mutate(`/api/nif/platform/providers/${dialog.provider.id}/endpoints/`, {
          name: String(form.get('name') ?? '').trim(),
          base_url: String(form.get('base_url') ?? '').trim(),
          allowed_hosts: allowedHosts,
          is_active: form.get('is_active') === 'on',
        });
        setNotice(`Endpoint policy saved for ${dialog.provider.display_name}.`);
      } else if (dialog.kind === 'credential') {
        await mutate(`/api/nif/platform/providers/${dialog.provider.id}/credential-references/`, {
          credential_type: String(form.get('credential_type') ?? '').trim(),
          reference: String(form.get('reference') ?? '').trim(),
          is_configured: form.get('is_configured') === 'on',
        });
        setNotice(`Credential reference saved for ${dialog.provider.display_name}. No secret value was submitted.`);
      } else if (dialog.kind === 'replay') {
        const replayNotes = String(form.get('replay_notes') ?? '').trim();
        await mutate(`/api/nif/platform/dead-letters/${dialog.deadLetter.id}/replay/`, { replay_notes: replayNotes });
        setNotice('Message replay queued. It will be picked up by the integration retry worker.');
      } else if (dialog.kind === 'kill-switch') {
        const reason = String(form.get('reason') ?? '').trim();
        await mutate(`/api/nif/platform/providers/${dialog.provider.id}/enable-kill-switch/`, { reason });
        setNotice(`Emergency suspension recorded for ${dialog.provider.display_name}.`);
      }
      setDialog(null);
      await loadWorkspace();
    } catch (cause) {
      setDialogError(errorText(cause));
    } finally {
      setBusy(false);
    }
  };

  const testConnectivity = async (provider: ProviderConfiguration) => {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await mutate(`/api/nif/platform/providers/${provider.id}/test-connectivity/`, {});
      setConnectivity(result as ConnectivityResult);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  };

  const openDialog = (next: Exclude<DialogState, null>) => {
    setDialogError('');
    setDialog(next);
  };

  return (
    <div className="integration-workspace">
      <section className="panel integration-header">
        <div>
          <p className="eyebrow">Platform integration governance</p>
          <h2>National Integration Command Centre</h2>
          <p>Manage provider records, activation evidence, operational checks, and failed-message recovery. Provider traffic remains gated by the audited activation state.</p>
        </div>
        <span className="truth-label">Platform Owner authority</span>
      </section>

      {error ? <div className="inline-alert" role="alert"><Icon name="alert" />{error}<button className="secondary-button" disabled={loading} onClick={() => void loadWorkspace()} type="button">Retry</button></div> : null}
      {notice ? <div className="inline-success" role="status"><Icon name="check" />{notice}</div> : null}

      <section className="metric-grid integration-metrics" aria-label="Integration governance summary">
        <IntegrationMetric label="Provider configurations" value={providers.length} detail="Sandbox and production records" />
        <IntegrationMetric label="Operational providers" value={activeProviders} detail="Activation state is Active" />
        <IntegrationMetric label="Open activation requests" value={activeRequests.length} detail="Awaiting a terminal decision" />
        <IntegrationMetric label="Messages needing review" value={pendingDeadLetters.length} detail="Unreplayed dead letters" />
      </section>

      <div className="integration-tabs" role="tablist" aria-label="Integration work areas">
        {TABS.map((tab) => <button aria-controls={`integration-panel-${tab.id}`} aria-selected={activeTab === tab.id} className={activeTab === tab.id ? 'integration-tab is-active' : 'integration-tab'} id={`integration-tab-${tab.id}`} key={tab.id} onClick={() => setActiveTab(tab.id)} role="tab" type="button">{tab.label}{tab.id === 'dlq' && pendingDeadLetters.length ? <b>{pendingDeadLetters.length}</b> : null}</button>)}
      </div>

      {loading ? <p className="muted-cell">Loading live integration records…</p> : null}

      {activeTab === 'providers' ? <section aria-labelledby="integration-tab-providers" className="integration-provider-list" id="integration-panel-providers" role="tabpanel" tabIndex={0}>
        <div className="integration-section-head"><div><p className="eyebrow">Provider registry</p><h3>Configurations and health</h3></div><button className="primary-button" onClick={() => openDialog({ kind: 'provider' })} type="button"><Icon name="plus" /> Add provider</button></div>
        {!loading && providers.length === 0 ? <div className="panel integration-empty"><Icon name="network" /><strong>No provider configurations found</strong><p>Create a provider record to begin the governed activation workflow.</p></div> : null}
        <div className="integration-provider-grid">
          {providers.map((provider) => {
            const latestHealth = health.get(provider.id);
            const resources = providerResources.get(provider.id) ?? { endpoints: [], credentials: [] };
            const activeEndpointCount = resources.endpoints.filter((item) => item.is_active && endpointHostIsAllowlisted(item)).length;
            const configuredCredentialCount = resources.credentials.filter((item) => item.is_configured).length;
            const openActivation = activations.find((item) => item.provider === provider.id && !TERMINAL_STATES.has(item.state));
            return <article className="panel integration-provider-card" key={provider.id}>
              <header><div><p className="eyebrow">{provider.provider_type} · {provider.environment}</p><h3>{provider.display_name}</h3></div><span className={`integration-state state-${provider.activation_state.toLowerCase()}`}>{labelForState(provider.activation_state)}</span></header>
              <p className="integration-truth"><span>Operational truth</span><strong>{provider.truth_label.replaceAll('_', ' ')}</strong></p>
              <dl className="integration-health-grid">
                <div><dt>Latest health record</dt><dd>{latestHealth ? formatDate(latestHealth.checked_at) : 'No health check recorded'}</dd></div>
                <div><dt>Reachability</dt><dd>{latestHealth ? (latestHealth.is_reachable ? 'Reachable' : 'Unreachable') : 'Not measured'}</dd></div>
                <div><dt>Response time</dt><dd>{latestHealth?.response_time_ms == null ? '—' : `${latestHealth.response_time_ms} ms`}</dd></div>
                <div><dt>Activation request</dt><dd>{openActivation ? labelForState(openActivation.state) : 'None open'}</dd></div>
                <div><dt>Allowed endpoints</dt><dd>{activeEndpointCount} active · {resources.endpoints.length} total</dd></div>
                <div><dt>Credential references</dt><dd>{configuredCredentialCount} configured · {resources.credentials.length} total</dd></div>
              </dl>
              {(resources.endpoints.length || resources.credentials.length) ? <details className="integration-evidence-details"><summary>Configuration records</summary>
                {resources.endpoints.length ? <><strong>Endpoints</strong><ul>{resources.endpoints.map((endpoint) => <li key={endpoint.id}><strong>{endpoint.name} · {endpoint.is_active ? 'Active' : 'Inactive'}</strong><span>{endpoint.base_url}</span><p>Allow-list: {endpoint.allowed_hosts.join(', ') || 'None'}</p></li>)}</ul></> : null}
                {resources.credentials.length ? <><strong>Credential references (names only)</strong><ul>{resources.credentials.map((credential) => <li key={credential.id}><strong>{credential.credential_type} · {credential.is_configured ? 'Configured' : 'Not configured'}</strong><span>{credential.reference}</span></li>)}</ul></> : null}
              </details> : null}
              {provider.notes ? <p className="integration-provider-notes">{provider.notes}</p> : null}
              <footer>
                {!provider.is_operational && !openActivation ? <button className="primary-button" onClick={() => openDialog({ kind: 'activation', provider })} type="button">Request activation</button> : null}
                <button className="secondary-button" onClick={() => openDialog({ kind: 'endpoint', provider })} type="button">Configure endpoint</button>
                <button className="secondary-button" onClick={() => openDialog({ kind: 'credential', provider })} type="button">Credential references</button>
                <button className="secondary-button" disabled={busy} onClick={() => void testConnectivity(provider)} type="button">Check endpoint policy</button>
                {provider.activation_state === 'ACTIVE' ? <button className="danger-button" onClick={() => openDialog({ kind: 'kill-switch', provider })} type="button">Suspend provider</button> : null}
              </footer>
            </article>;
          })}
        </div>
      </section> : null}

      {activeTab === 'etims' ? <EtimsWorkspaceTab csrfToken={csrfToken} /> : null}

      {activeTab === 'activations' ? <section aria-labelledby="integration-tab-activations" className="integration-activation-list" id="integration-panel-activations" role="tabpanel" tabIndex={0}>
        <div className="integration-section-head"><div><p className="eyebrow">Audited state transitions</p><h3>Activation requests</h3></div><span className="muted-cell">Only valid next states are offered</span></div>
        {!loading && activations.length === 0 ? <div className="panel integration-empty"><Icon name="shield" /><strong>No activation requests</strong><p>Start a request from a configured provider when the business owner is ready to begin review.</p></div> : null}
        <div className="integration-request-list">
          {activations.map((activation) => {
            const provider = providerById.get(activation.provider);
            const nextStates = NEXT_STATES[activation.state] ?? [];
            return <article className="panel integration-request-card" key={activation.id}>
              <header><div><p className="eyebrow">{provider?.provider_type ?? 'Provider'} · {provider?.environment ?? 'Configuration unavailable'}</p><h3>{provider?.display_name ?? `Provider ${activation.provider}`}</h3></div><span className={`integration-state state-${activation.state.toLowerCase()}`}>{labelForState(activation.state)}</span></header>
              <dl className="integration-request-meta"><div><dt>Requested</dt><dd>{formatDate(activation.requested_at)}</dd></div><div><dt>Requested by</dt><dd>{activation.requested_by_name || activation.requested_by || 'Unknown user'}</dd></div></dl>
              <div className="integration-justification"><strong>Business justification</strong><p>{activation.justification}</p></div>
              {activation.notes ? <div className="integration-justification"><strong>Latest decision notes</strong><p>{activation.notes}</p></div> : null}
              {activation.sandbox_evidence && Object.keys(activation.sandbox_evidence).length ? <details className="integration-evidence-details"><summary>View recorded evidence</summary><pre>{JSON.stringify(activation.sandbox_evidence, null, 2)}</pre></details> : null}
              {activation.decisions?.length ? <details className="integration-evidence-details"><summary>Decision history ({activation.decisions.length})</summary><ol>{activation.decisions.map((item) => <li key={item.id}><strong>{labelForState(item.from_state)} → {labelForState(item.to_state)}</strong><span>{item.decided_by_name} · {formatDate(item.decided_at)}</span><p>{item.decision_notes || 'No decision notes recorded.'}</p></li>)}</ol></details> : null}
              <footer>{nextStates.length ? <button className="primary-button" onClick={() => { setDecision({ toState: nextStates[0] ?? '', notes: '', evidenceJson: '' }); openDialog({ kind: 'advance', activation }); }} type="button">Record next decision</button> : <span className="muted-cell">No further transitions</span>}</footer>
            </article>;
          })}
        </div>
      </section> : null}

      {activeTab === 'compliance' ? <section aria-labelledby="integration-tab-compliance" className="integration-compliance" id="integration-panel-compliance" role="tabpanel" tabIndex={0}>
        <div className="integration-section-head"><div><p className="eyebrow">Current records</p><h3>Evidence-based compliance status</h3></div><button className="secondary-button" disabled={loading} onClick={() => void loadWorkspace()} type="button">Refresh status</button></div>
        <div className="integration-compliance-grid">
          <ComplianceCard title="Provider activation" value={`${activeProviders} active`} detail={`${providers.length - activeProviders} configured providers are not operational.`} />
          <ComplianceCard title="Activation review" value={`${activeRequests.length} open`} detail="Requests in progress, based on the persisted activation queue." />
          <ComplianceCard title="Message recovery" value={`${pendingDeadLetters.length} pending`} detail="Unreplayed dead letters require documented review before replay." />
          <ComplianceCard title="Health evidence" value={`${health.size} providers checked`} detail="Health snapshots are shown only when the server has recorded them." />
        </div>
        <p className="integration-disclaimer">This summary covers integration records available to the current Platform Owner account. It does not claim regulator acceptance, live connectivity, or premises and practitioner compliance unless those records are separately verified.</p>
      </section> : null}

      {activeTab === 'reports' ? <section aria-labelledby="integration-tab-reports" className="panel integration-resource-panel" id="integration-panel-reports" role="tabpanel" tabIndex={0}>
        <p className="eyebrow">Download from current platform records</p><h3>Compliance reports</h3><p>Generate a current report from the platform reporting service. The report’s truth labels distinguish internal evidence from external regulator confirmation.</p>
        <div className="integration-resource-list">{[
          ['PREMISES', 'Premises verification and licence report'], ['PRACTITIONERS', 'Practitioner verification and authority report'],
          ['PROVIDERS', 'Provider activation and reliability report'], ['RECALLS', 'Regulatory recalls and stock holds'],
          ['COMPLIANCE_READINESS', 'Regulatory readiness scorecard'], ['SECURITY_AUDIT', 'Security and activation audit'],
        ].map(([type, label]) => <a className="integration-resource-link" href={`/api/nif/platform/reports/?report_type=${type}&format=json`} key={type} rel="noreferrer" target="_blank"><span>{label}</span><strong>Download JSON <Icon name="arrow" /></strong></a>)}</div>
      </section> : null}

      {activeTab === 'evidence' ? <section aria-labelledby="integration-tab-evidence" className="panel integration-resource-panel" id="integration-panel-evidence" role="tabpanel" tabIndex={0}>
        <p className="eyebrow">Certification and release evidence</p><h3>Evidence package</h3><p>Export the current evidence bundle. Runtime records describe system state; they do not replace commit-matched CI attestations or regulator acceptance.</p>
        <div className="integration-resource-actions"><a className="primary-button" href="/api/nif/platform/evidence/?format=json" rel="noreferrer" target="_blank">View JSON package</a><a className="secondary-button" href="/api/nif/platform/evidence/?format=zip" rel="noreferrer" target="_blank">Export ZIP bundle</a></div>
      </section> : null}

      {activeTab === 'dlq' ? <section aria-labelledby="integration-tab-dlq" className="integration-dlq" id="integration-panel-dlq" role="tabpanel" tabIndex={0}>
        <div className="integration-section-head"><div><p className="eyebrow">Manual recovery queue</p><h3>Unreplayed dead letters</h3></div><button className="secondary-button" disabled={loading} onClick={() => void loadWorkspace()} type="button">Refresh queue</button></div>
        {pendingDeadLetters.length === 0 ? <div className="panel integration-empty"><Icon name="check" /><strong>No unreplayed dead letters</strong><p>The platform service currently reports no messages waiting for manual replay.</p></div> : <div className="table-scroll"><table><thead><tr><th>Message</th><th>Failed at</th><th>Reason</th><th>Action</th></tr></thead><tbody>{pendingDeadLetters.map((item) => <tr key={item.id}><td><code>{item.message}</code></td><td>{formatDate(item.dead_lettered_at)}</td><td>{item.dead_letter_reason}</td><td><button className="secondary-button" onClick={() => openDialog({ kind: 'replay', deadLetter: item })} type="button">Review &amp; replay</button></td></tr>)}</tbody></table></div>}
      </section> : null}

      {activeTab === 'rules' ? <section aria-labelledby="integration-tab-rules" className="panel integration-rules" id="integration-panel-rules" role="tabpanel" tabIndex={0}>
        <p className="eyebrow">Governance controls</p><h3>Provider activation and handling rules</h3>
        <ol><li>Record a business justification before opening an activation request.</li><li>Advance one state at a time through the API’s allowed transition list; each decision is audited.</li><li>Keep credential values in the approved secrets manager. This workspace stores references and non-secret configuration only.</li><li>Verify sandbox, security, and production evidence before the corresponding approval transitions.</li><li>Use the emergency suspension action for an immediate stop and record the reason.</li><li>Replay a dead letter only after reviewing its failure reason and recording the recovery plan.</li></ol>
      </section> : null}

      {connectivity ? <div className="business-dialog-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target) setConnectivity(null); }} role="presentation"><section aria-labelledby="integration-connectivity-title" aria-modal="true" className="business-dialog integration-dialog" role="dialog"><header><div><p className="eyebrow">Endpoint policy check</p><h2 id="integration-connectivity-title">{connectivity.provider}</h2></div><button aria-label="Close dialog" onClick={() => setConnectivity(null)} type="button"><Icon name="close" /></button></header>{connectivity.endpoints.length ? <div className="integration-endpoint-list">{connectivity.endpoints.map((item) => <article key={`${item.endpoint_name}-${item.base_url}`}><strong>{item.endpoint_name}</strong><code>{item.base_url}</code><span className={item.is_allowed_hosts_configured ? 'integration-check-good' : 'integration-check-blocked'}>{item.status.replaceAll('_', ' ')}</span><small>Allowed hosts: {item.allowed_hosts.length ? item.allowed_hosts.join(', ') : 'None configured'}</small></article>)}</div> : <p className="integration-dialog-note">No active endpoint records are configured. Connectivity was not attempted.</p>}<footer><button className="primary-button" onClick={() => setConnectivity(null)} type="button">Close</button></footer></section></div> : null}

      {dialog ? <IntegrationDialog busy={busy} dialog={dialog} error={dialogError} decision={decision} setDecision={setDecision} onClose={() => { if (!busy) setDialog(null); }} onSubmit={submitDialog} /> : null}
    </div>
  );
}

function IntegrationMetric({ label, value, detail }: { readonly label: string; readonly value: number; readonly detail: string }) {
  return <article className="metric-card"><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>;
}

function ComplianceCard({ title, value, detail }: { readonly title: string; readonly value: string; readonly detail: string }) {
  return <article className="panel integration-compliance-card"><span>{title}</span><strong>{value}</strong><p>{detail}</p></article>;
}

function IntegrationDialog({
  busy, decision, dialog, error, onClose, onSubmit, setDecision,
}: {
  readonly busy: boolean;
  readonly decision: { readonly toState: ProviderState | ''; readonly notes: string; readonly evidenceJson: string };
  readonly dialog: Exclude<DialogState, null>;
  readonly error: string;
  readonly onClose: () => void;
  readonly onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  readonly setDecision: (value: { toState: ProviderState | ''; notes: string; evidenceJson: string }) => void;
}) {
  const [providerType, setProviderType] = useState(PROVIDER_TYPES[0][0]);
  const [environment, setEnvironment] = useState<'SANDBOX' | 'PRODUCTION'>('SANDBOX');
  const activation = dialog.kind === 'advance' ? dialog.activation : null;
  const availableStates = activation ? NEXT_STATES[activation.state] ?? [] : [];
  const title = dialog.kind === 'provider' ? 'Add provider configuration'
    : dialog.kind === 'activation' ? `Request activation · ${dialog.provider.display_name}`
      : dialog.kind === 'advance' ? `Record decision · ${labelForState(dialog.activation.state)}`
        : dialog.kind === 'endpoint' ? `Configure endpoint · ${dialog.provider.display_name}`
          : dialog.kind === 'credential' ? `Credential references · ${dialog.provider.display_name}`
        : dialog.kind === 'replay' ? 'Review dead letter'
          : `Suspend ${dialog.provider.display_name}`;
  const requiresEvidence = decision.toState === 'SANDBOX_PASSED' || decision.toState === 'SECURITY_APPROVED' || decision.toState === 'PRODUCTION_APPROVED' || decision.toState === 'ACTIVE';

  return <div className="business-dialog-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target && !busy) onClose(); }} role="presentation">
    <section aria-labelledby="integration-dialog-title" aria-modal="true" className="business-dialog integration-dialog" role="dialog">
      <header><div><p className="eyebrow">Governed integration workflow</p><h2 id="integration-dialog-title">{title}</h2></div><button aria-label="Close dialog" disabled={busy} onClick={onClose} type="button"><Icon name="close" /></button></header>
      {dialog.kind === 'kill-switch' ? <p className="business-dialog-confirm"><Icon name="alert" /> This immediately suspends provider operations. Record the incident or regulatory reason for the audit trail.</p> : null}
      {dialog.kind === 'advance' ? <p className="business-dialog-confirm"><Icon name="shield" /> The server accepts only valid state transitions. This decision and its evidence become part of the platform audit record.</p> : null}
      {dialog.kind === 'provider' ? <p className="business-dialog-confirm"><Icon name="shield" /> Store only non-secret metadata here. Use the approved secrets manager for credential values.</p> : null}
      {dialog.kind === 'replay' ? <div className="integration-dialog-note"><strong>Message ID</strong><code>{dialog.deadLetter.message}</code><strong>Failure reason</strong><p>{dialog.deadLetter.dead_letter_reason}</p></div> : null}
      <form onSubmit={onSubmit}>
        {dialog.kind === 'provider' ? <>
          <label className="business-field"><span>Provider type<b>Required</b></span><select name="provider_type" onChange={(event) => setProviderType(event.target.value as typeof providerType)} value={providerType}>{PROVIDER_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="business-field"><span>Environment<b>Required</b></span><select name="environment" onChange={(event) => setEnvironment(event.target.value as 'SANDBOX' | 'PRODUCTION')} value={environment}><option value="SANDBOX">Sandbox</option><option value="PRODUCTION">Production</option></select></label>
          <label className="business-field"><span>Display name<b>Required</b></span><input autoFocus defaultValue={PROVIDER_TYPES.find(([value]) => value === providerType)?.[1] ?? ''} key={providerType} maxLength={200} name="display_name" required /></label>
          <label className="business-field"><span>Configuration note</span><textarea maxLength={3000} name="notes" rows={2} /></label>
        </> : null}
        {dialog.kind === 'activation' ? <>
          <div className="business-dialog-record"><div><code>{dialog.provider.provider_type} · {dialog.provider.environment}</code><strong>{dialog.provider.display_name}</strong></div></div>
          <label className="business-field"><span>Business justification<b>Required</b></span><textarea autoFocus minLength={15} maxLength={3000} name="justification" placeholder="State the business purpose, service owner, and expected operating scope." required rows={3} /></label>
        </> : null}
        {dialog.kind === 'advance' ? <>
          <label className="business-field"><span>Next state<b>Required</b></span><select autoFocus name="to_state" onChange={(event) => setDecision({ ...decision, toState: event.target.value as ProviderState })} required value={decision.toState}>{availableStates.map((state) => <option key={state} value={state}>{labelForState(state)}</option>)}</select></label>
          <label className="business-field"><span>Decision notes<b>Required</b></span><textarea minLength={10} name="notes" onChange={(event) => setDecision({ ...decision, notes: event.target.value })} placeholder="Record what was reviewed and why this transition is appropriate." required rows={3} value={decision.notes} /></label>
          <label className="business-field"><span>Evidence object{requiresEvidence ? <b>Required</b> : null}</span><textarea aria-describedby="integration-evidence-hint" name="sandbox_evidence" onChange={(event) => setDecision({ ...decision, evidenceJson: event.target.value })} placeholder={'{"evidence_reference":"CASE-123","summary":"Sandbox checks passed"}'} required={requiresEvidence} rows={3} value={decision.evidenceJson} /></label>
          <small id="integration-evidence-hint" className="integration-field-hint">Enter a JSON object. Never include secrets, tokens, or private keys.</small>
        </> : null}
        {dialog.kind === 'endpoint' ? <>
          <p className="business-dialog-confirm"><Icon name="shield" /> Use HTTPS only. The hostname must match an explicit TLS allow-list entry. Saving this record does not probe or contact the endpoint.</p>
          <label className="business-field"><span>Endpoint name<b>Required</b></span><input autoFocus maxLength={100} name="name" placeholder="Sandbox API" required /></label>
          <label className="business-field"><span>HTTPS base URL<b>Required</b></span><input name="base_url" pattern="https://.+" placeholder="https://sandbox.example.health/api" required type="url" /></label>
          <label className="business-field"><span>Allowed TLS hosts<b>Required</b></span><textarea name="allowed_hosts" placeholder="sandbox.example.health" required rows={2} /></label>
          <label className="integration-check-field"><input name="is_active" type="checkbox" /><span>Activate this endpoint after reviewing the URL and host allow-list</span></label>
        </> : null}
        {dialog.kind === 'credential' ? <>
          <p className="business-dialog-confirm"><Icon name="shield" /> Store a reference name or secret-manager path only. Never paste a client secret, token, private key, or certificate contents here.</p>
          <label className="business-field"><span>Credential type<b>Required</b></span><select name="credential_type"><option value="CLIENT_ID">Client ID reference</option><option value="CLIENT_SECRET">Client secret reference</option><option value="CALLBACK_VERIFICATION_KEY">Callback verification key</option><option value="CLIENT_CERTIFICATE">Client certificate reference</option><option value="OAUTH_ENDPOINT">OAuth endpoint reference</option><option value="ISSUER_URL">Issuer URL reference</option></select></label>
          <label className="business-field"><span>Reference name<b>Required</b></span><input autoFocus maxLength={500} name="reference" placeholder="TIBATRACE_DHA_HIE_SANDBOX_CLIENT_SECRET or vault://integrations/dha/client-secret" required /></label>
          <label className="integration-check-field"><input name="is_configured" type="checkbox" /><span>The referenced value exists and was verified in the secret manager</span></label>
        </> : null}
        {dialog.kind === 'replay' ? <label className="business-field"><span>Recovery plan<b>Required</b></span><textarea autoFocus minLength={10} maxLength={2000} name="replay_notes" placeholder="Explain the root cause review and why replay is safe." required rows={3} /></label> : null}
        {dialog.kind === 'kill-switch' ? <label className="business-field"><span>Suspension reason<b>Required</b></span><textarea autoFocus minLength={10} maxLength={2000} name="reason" placeholder="Incident, revocation notice, or security reason" required rows={3} /></label> : null}
        {error ? <p className="business-dialog-error" role="alert"><Icon name="alert" />{error}</p> : null}
        <footer><button className="secondary-button" disabled={busy} onClick={onClose} type="button">Cancel</button><button className={dialog.kind === 'kill-switch' ? 'danger-button' : 'primary-button'} disabled={busy} type="submit">{busy ? 'Saving…' : dialog.kind === 'provider' ? 'Create provider' : dialog.kind === 'activation' ? 'Open activation request' : dialog.kind === 'advance' ? 'Record decision' : dialog.kind === 'endpoint' ? 'Save endpoint policy' : dialog.kind === 'credential' ? 'Save credential reference' : dialog.kind === 'replay' ? 'Queue replay' : 'Suspend provider'}</button></footer>
      </form>
    </section>
  </div>;
}
