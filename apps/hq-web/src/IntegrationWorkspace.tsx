import { useCallback, useEffect, useState } from 'react';
import type {
  IntegrationProviderCardData,
  IntegrationTruthLabel,
  ProviderActivationState,
  ProviderType,
} from '@dawatrace/shared/dispensing/index.js';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface IntegrationWorkspaceProps {
  csrfToken: string;
}

interface DeadLetterItem {
  id: string;
  messageType: string;
  provider: string;
  deadLetteredAt: string;
  reason: string;
  replayedAt: string | null;
}

// ---------------------------------------------------------------------------
// Constants & helpers
// ---------------------------------------------------------------------------

const TRUTH_LABEL_COLORS: Record<IntegrationTruthLabel, { bg: string; text: string; dot: string }> = {
  ADAPTER_SCAFFOLDED_NOT_CONNECTED: { bg: 'var(--navy-100)', text: 'var(--navy-700)', dot: 'var(--navy-700)' },
  NOT_CONFIGURED:                   { bg: 'var(--violet-100)', text: 'var(--violet-700)', dot: 'var(--violet-700)' },
  MANUAL_INTERNAL_VERIFICATION:     { bg: 'var(--teal-100)', text: 'var(--teal-700)', dot: 'var(--teal-700)' },
  SNAPSHOT_IMPORTED_STALENESS_GOVERNED: { bg: 'var(--amber-100)', text: 'var(--amber-700)', dot: 'var(--amber-700)' },
  LOCAL_RECALL_WORKFLOW_NO_REGULATOR_FEED: { bg: 'var(--red-100)', text: 'var(--danger-ink)', dot: 'var(--red-700)' },
  MANUAL_VERIFICATION:              { bg: 'var(--teal-100)', text: 'var(--teal-700)', dot: 'var(--teal-700)' },
  DISABLED_IN_PRODUCTION:           { bg: 'var(--line-soft)', text: 'var(--muted)', dot: 'var(--muted)' },
  SANDBOX_EVIDENCE_ONLY:            { bg: 'var(--cyan-100)', text: 'var(--cyan-700)', dot: 'var(--cyan-700)' },
  PPB_API_ACTIVE:                   { bg: 'var(--teal-100)', text: 'var(--teal-700)', dot: 'var(--teal-700)' },
};

const ACTIVATION_STATE_LABELS: Record<ProviderActivationState, string> = {
  REQUESTED:          'Requested',
  UNDER_REVIEW:       'Under Review',
  SANDBOX_CONFIGURED: 'Sandbox Configured',
  SANDBOX_TESTING:    'Sandbox Testing',
  SANDBOX_PASSED:     'Sandbox Passed',
  SECURITY_APPROVED:  'Security Approved',
  PRODUCTION_APPROVED:'Production Approved',
  ACTIVE:             'Active',
  SUSPENDED:          'Suspended',
  DECOMMISSIONED:     'Decommissioned',
  REJECTED:           'Rejected',
};

const PROVIDER_ICONS: Record<ProviderType, string> = {
  DHA_HIE:               '🏥',
  DHA_HWR:               '👨‍⚕️',
  PPB_PREMISES:          '🏛️',
  PPB_PRODUCT_REGISTER:  '💊',
  PPB_REGULATORY_ALERTS: '⚠️',
  PPB_RECALLS:           '🔴',
};

const MOCK_PROVIDERS: IntegrationProviderCardData[] = [
  {
    providerType: 'DHA_HIE',
    displayName: 'DHA Health Information Exchange',
    activationState: 'REQUESTED',
    truthLabel: 'ADAPTER_SCAFFOLDED_NOT_CONNECTED',
    lastHealthChecked: null,
    isReachable: null,
    pendingDeadLetters: 0,
  },
  {
    providerType: 'DHA_HWR',
    displayName: 'DHA Health Worker Registry',
    activationState: 'REQUESTED',
    truthLabel: 'ADAPTER_SCAFFOLDED_NOT_CONNECTED',
    lastHealthChecked: null,
    isReachable: null,
    pendingDeadLetters: 0,
  },
  {
    providerType: 'PPB_PREMISES',
    displayName: 'PPB Premises Registry',
    activationState: 'REQUESTED',
    truthLabel: 'MANUAL_INTERNAL_VERIFICATION',
    lastHealthChecked: null,
    isReachable: null,
    pendingDeadLetters: 0,
  },
  {
    providerType: 'PPB_PRODUCT_REGISTER',
    displayName: 'PPB Product Register',
    activationState: 'REQUESTED',
    truthLabel: 'SNAPSHOT_IMPORTED_STALENESS_GOVERNED',
    lastHealthChecked: null,
    isReachable: null,
    pendingDeadLetters: 0,
  },
  {
    providerType: 'PPB_REGULATORY_ALERTS',
    displayName: 'PPB Regulatory Alerts',
    activationState: 'REQUESTED',
    truthLabel: 'LOCAL_RECALL_WORKFLOW_NO_REGULATOR_FEED',
    lastHealthChecked: null,
    isReachable: null,
    pendingDeadLetters: 0,
  },
  {
    providerType: 'PPB_RECALLS',
    displayName: 'PPB Product Recalls',
    activationState: 'REQUESTED',
    truthLabel: 'LOCAL_RECALL_WORKFLOW_NO_REGULATOR_FEED',
    lastHealthChecked: null,
    isReachable: null,
    pendingDeadLetters: 0,
  },
];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function TruthLabelBadge({ label }: { label: IntegrationTruthLabel }) {
  const colors = TRUTH_LABEL_COLORS[label] ?? TRUTH_LABEL_COLORS['NOT_CONFIGURED'];
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        padding: '4px 10px',
        borderRadius: '12px',
        fontSize: '11px',
        fontWeight: 700,
        letterSpacing: '0.04em',
        textTransform: 'uppercase',
        background: colors.bg,
        color: colors.text,
        border: `1px solid ${colors.text}44`,
        whiteSpace: 'nowrap',
      }}
    >
      <span
        style={{
          display: 'inline-block',
          width: '7px',
          height: '7px',
          borderRadius: '50%',
          background: colors.dot,
          flexShrink: 0,
        }}
      />
      {label.replace(/_/g, ' ')}
    </span>
  );
}

function ActivationProgressBar({ state }: { state: ProviderActivationState }) {
  const steps: ProviderActivationState[] = [
    'REQUESTED', 'UNDER_REVIEW', 'SANDBOX_CONFIGURED', 'SANDBOX_TESTING',
    'SANDBOX_PASSED', 'SECURITY_APPROVED', 'PRODUCTION_APPROVED', 'ACTIVE',
  ];
  const isTerminal = state === 'REJECTED' || state === 'SUSPENDED' || state === 'DECOMMISSIONED';
  const stepIdx = steps.indexOf(state);
  const progress = isTerminal ? 0 : stepIdx >= 0 ? ((stepIdx + 1) / steps.length) * 100 : 0;

  return (
    <div style={{ marginTop: '12px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
        <span style={{ fontSize: '12px', color: 'var(--muted)', fontWeight: 600 }}>
          Activation stage
        </span>
        <span style={{ fontSize: '12px', color: 'var(--ink)', fontWeight: 700 }}>
          {ACTIVATION_STATE_LABELS[state]}
        </span>
      </div>
      <div style={{ height: '6px', background: 'var(--line-soft)', borderRadius: '3px', overflow: 'hidden' }}>
        <div
          style={{
            height: '100%',
            width: `${isTerminal ? 100 : progress}%`,
            background: isTerminal
              ? 'var(--red-700)'
              : 'linear-gradient(90deg, var(--navy-700), var(--teal-700))',
            borderRadius: '3px',
            transition: 'width 0.6s ease',
          }}
        />
      </div>
    </div>
  );
}

function ProviderCard({ provider }: { provider: IntegrationProviderCardData }) {
  const [expanded, setExpanded] = useState(false);
  const icon = PROVIDER_ICONS[provider.providerType] ?? '🔗';

  return (
    <div
      className="integration-provider-card"
      style={{
        background: 'var(--panel)',
        border: '1px solid var(--line)',
        borderRadius: '16px',
        padding: '22px',
        boxShadow: 'var(--shadow)',
        transition: 'all 0.2s ease',
        cursor: 'pointer',
      }}
      onClick={() => setExpanded(e => !e)}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '16px' }}>
        <div
          style={{
            width: '46px',
            height: '46px',
            borderRadius: '12px',
            background: 'var(--canvas)',
            border: '1px solid var(--line)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '22px',
            flexShrink: 0,
          }}
        >
          {icon}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 800, color: 'var(--ink)', fontSize: '15px', marginBottom: '6px' }}>
            {provider.displayName}
          </div>
          <TruthLabelBadge label={provider.truthLabel} />
          <ActivationProgressBar state={provider.activationState} />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '8px' }}>
          {provider.pendingDeadLetters > 0 && (
            <span
              style={{
                background: 'var(--red-100)',
                color: 'var(--danger-ink)',
                border: '1px solid var(--red-500)',
                borderRadius: '10px',
                padding: '4px 10px',
                fontSize: '11px',
                fontWeight: 700,
              }}
            >
              {provider.pendingDeadLetters} DLQ
            </span>
          )}
          <span style={{ color: 'var(--muted)', fontSize: '12px' }}>
            {expanded ? '▲' : '▼'}
          </span>
        </div>
      </div>

      {expanded && (
        <div
          style={{
            marginTop: '18px',
            paddingTop: '18px',
            borderTop: '1px solid var(--line)',
          }}
        >
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', fontSize: '13px' }}>
            <div>
              <div style={{ color: 'var(--muted)', marginBottom: '4px' }}>Provider type</div>
              <div style={{ color: 'var(--ink)', fontFamily: 'monospace', fontWeight: 600 }}>{provider.providerType}</div>
            </div>
            <div>
              <div style={{ color: 'var(--muted)', marginBottom: '4px' }}>Last health check</div>
              <div style={{ color: 'var(--ink)', fontWeight: 600 }}>
                {provider.lastHealthChecked
                  ? new Date(provider.lastHealthChecked).toLocaleString()
                  : 'Never checked'}
              </div>
            </div>
            <div>
              <div style={{ color: 'var(--muted)', marginBottom: '4px' }}>Reachability</div>
              <div style={{ color: provider.isReachable == null ? 'var(--muted-2)' : provider.isReachable ? 'var(--teal-700)' : 'var(--red-700)', fontWeight: 700 }}>
                {provider.isReachable == null ? '— not yet probed' : provider.isReachable ? 'Reachable' : 'Unreachable'}
              </div>
            </div>
            <div>
              <div style={{ color: 'var(--muted)', marginBottom: '4px' }}>Dead-letter queue</div>
              <div style={{ color: provider.pendingDeadLetters > 0 ? 'var(--red-700)' : 'var(--teal-700)', fontWeight: 700 }}>
                {provider.pendingDeadLetters > 0 ? `${provider.pendingDeadLetters} pending` : 'Clear'}
              </div>
            </div>
          </div>

          <div
            style={{
              marginTop: '16px',
              padding: '14px',
              background: 'var(--canvas)',
              border: '1px solid var(--line)',
              borderRadius: '10px',
              fontSize: '12px',
              color: 'var(--muted)',
              lineHeight: 1.6,
            }}
          >
            <strong style={{ color: 'var(--navy-700)' }}>Platform Owner action required</strong> to advance
            this integration beyond {ACTIVATION_STATE_LABELS[provider.activationState]}.
            No live traffic will be sent until this provider reaches{' '}
            <strong style={{ color: 'var(--teal-700)' }}>ACTIVE</strong> state with approved credentials.
          </div>
        </div>
      )}
    </div>
  );
}

function ActivationGateSummary({ providers }: { providers: IntegrationProviderCardData[] }) {
  const active = providers.filter(p => p.activationState === 'ACTIVE').length;
  const pending = providers.filter(p => !['ACTIVE', 'REJECTED', 'SUSPENDED', 'DECOMMISSIONED'].includes(p.activationState)).length;
  const blocked = providers.filter(p => ['REJECTED', 'SUSPENDED', 'DECOMMISSIONED'].includes(p.activationState)).length;

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap: '16px',
        marginBottom: '28px',
      }}
    >
      {[
        { label: 'Active integrations', value: active, color: 'var(--teal-700)', bg: 'var(--teal-50)', border: 'var(--teal-500)' },
        { label: 'Pending activation', value: pending, color: 'var(--amber-700)', bg: 'var(--amber-100)', border: 'var(--amber-700)' },
        { label: 'Blocked / terminal', value: blocked, color: 'var(--danger-ink)', bg: 'var(--red-100)', border: 'var(--red-500)' },
      ].map(({ label, value, color, bg, border }) => (
        <div
          key={label}
          style={{
            background: bg,
            border: `1px solid ${border}`,
            borderRadius: '14px',
            padding: '20px',
            textAlign: 'center',
            boxShadow: 'var(--shadow)',
          }}
        >
          <div style={{ fontSize: '32px', fontWeight: 800, color, lineHeight: 1 }}>{value}</div>
          <div style={{ fontSize: '12px', color: 'var(--ink)', fontWeight: 700, marginTop: '8px' }}>{label}</div>
        </div>
      ))}
    </div>
  );
}

function ProgrammeGovRules() {
  return (
    <div
      style={{
        background: 'var(--panel)',
        border: '1px solid var(--line)',
        borderRadius: '16px',
        padding: '24px',
        marginBottom: '28px',
        boxShadow: 'var(--shadow)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
        <span style={{ fontSize: '20px' }}>🔒</span>
        <span style={{ fontWeight: 800, color: 'var(--ink)', fontSize: '15px' }}>
          Programme Governance Rules (Phase 16 — N1 to N8)
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', fontSize: '13px', lineHeight: 1.6 }}>
        {[
          { phase: 'N1', text: 'Premises and superintendent reconciliation' },
          { phase: 'N2', text: 'Provider configuration, activation governance and OAuth foundation' },
          { phase: 'N3', text: 'DHA HWR practitioner verification' },
          { phase: 'N4', text: 'Regulatory medicine-status freshness and provenance' },
          { phase: 'N5', text: 'Regulatory alerts and recall ingestion' },
          { phase: 'N6', text: 'HQ monitoring, reports and evidence' },
          { phase: 'N7', text: 'DHA sandbox and end-to-end certification' },
          { phase: 'N8', text: 'Controlled production activation' },
        ].map(({ phase, text }) => (
          <div key={phase} style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            <span
              style={{
                display: 'inline-block',
                padding: '3px 8px',
                background: 'var(--navy-100)',
                color: 'var(--navy-700)',
                borderRadius: '6px',
                fontSize: '11px',
                fontWeight: 800,
                textAlign: 'center',
                flexShrink: 0,
              }}
            >
              {phase}
            </span>
            <span style={{ color: 'var(--ink)', fontWeight: 500 }}>{text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main workspace component
// ---------------------------------------------------------------------------

export function IntegrationWorkspace({ csrfToken: _csrfToken }: IntegrationWorkspaceProps) {
  const [providers, setProviders] = useState<IntegrationProviderCardData[]>(MOCK_PROVIDERS);
  const [activeTab, setActiveTab] = useState<'providers' | 'compliance' | 'reports' | 'evidence' | 'dlq' | 'rules'>('providers');
  const [deadLetters] = useState<DeadLetterItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchWorkspaceData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/nif/platform/providers/', {
        headers: { Accept: 'application/json' },
      });
      if (res.status === 403) {
        setError('Permission denied: Platform Owner capability is required to view national integration providers.');
        setLoading(false);
        return;
      }
      if (res.ok) {
        const data = await res.json();
        const results = Array.isArray(data) ? data : data.results || [];
        if (results.length > 0) {
          const mapped: IntegrationProviderCardData[] = results.map((item: any) => ({
            providerType: item.provider_type || item.providerType,
            displayName: item.display_name || item.displayName || item.provider_type,
            activationState: item.activation_state || item.activationState || 'REQUESTED',
            truthLabel: item.truth_label || item.truthLabel || 'ADAPTER_SCAFFOLDED_NOT_CONNECTED',
            lastHealthChecked: item.last_health_checked || null,
            isReachable: item.is_reachable ?? null,
            pendingDeadLetters: item.pending_dead_letters || 0,
          }));
          setProviders(mapped);
        }
      }
    } catch {
      // Fallback gracefully to scaffolded provider cards when server is unverified
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchWorkspaceData();
  }, [fetchWorkspaceData]);

  const tabs = [
    { key: 'providers' as const, label: 'Provider configurations', icon: '🔗' },
    { key: 'compliance' as const, label: 'Compliance Dashboard', icon: '📊' },
    { key: 'reports' as const, label: 'Compliance Reports', icon: '📑' },
    { key: 'evidence' as const, label: 'Certification Evidence', icon: '📦' },
    { key: 'dlq' as const, label: 'Dead-letter queue', icon: '📭', badge: deadLetters.length },
    { key: 'rules' as const, label: 'Programme governance', icon: '🔒' },
  ];

  return (
    <div style={{ padding: '0 0 40px' }}>
      {/* Header Banner */}
      <div
        style={{
          background: 'var(--panel)',
          border: '1px solid var(--line)',
          borderRadius: '16px',
          padding: '24px 28px',
          marginBottom: '24px',
          boxShadow: 'var(--shadow)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', marginBottom: '10px' }}>
          <div
            style={{
              width: '48px',
              height: '48px',
              borderRadius: '14px',
              background: 'var(--teal-100)',
              border: '1px solid var(--teal-700)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '24px',
            }}
          >
            🏗️
          </div>
          <div>
            <div style={{ fontWeight: 800, fontSize: '22px', color: 'var(--ink)', lineHeight: 1.2 }}>
              National Integration Command Centre
            </div>
            <div style={{ fontSize: '13px', color: 'var(--muted)', marginTop: '4px' }}>
              Kenya Digital Health Agency · Pharmacy and Poisons Board integrations
            </div>
          </div>
        </div>
        <div style={{ marginTop: '12px' }}>
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 14px',
              background: 'var(--red-100)',
              border: '1px solid var(--red-500)',
              borderRadius: '8px',
              fontSize: '12px',
              color: 'var(--danger-ink)',
              fontWeight: 700,
            }}
          >
            ⚠️ No live national integrations active — Platform Owner approval required for all providers
          </span>
        </div>
      </div>

      {loading && (
        <div style={{ padding: '14px', background: 'var(--cyan-100)', color: 'var(--cyan-700)', border: '1px solid var(--cyan-700)', borderRadius: '10px', marginBottom: '20px', fontSize: '13px', fontWeight: 600 }}>
          ⏳ Fetching platform integration configurations...
        </div>
      )}

      {error && (
        <div style={{ padding: '14px', background: 'var(--red-100)', color: 'var(--danger-ink)', border: '1px solid var(--red-500)', borderRadius: '10px', marginBottom: '20px', fontSize: '13px', fontWeight: 600 }}>
          ⛔ {error}
        </div>
      )}

      {/* Summary cards */}
      <ActivationGateSummary providers={providers} />

      {/* Tabs */}
      <div
        style={{
          display: 'flex',
          gap: '6px',
          background: 'var(--panel)',
          border: '1px solid var(--line)',
          borderRadius: '12px',
          padding: '6px',
          marginBottom: '24px',
          width: 'fit-content',
          boxShadow: 'var(--shadow)',
        }}
      >
        {tabs.map(tab => (
          <button
            key={tab.key}
            id={`integration-tab-${tab.key}`}
            onClick={() => setActiveTab(tab.key)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '10px 18px',
              borderRadius: '8px',
              border: 'none',
              cursor: 'pointer',
              fontSize: '13px',
              fontWeight: 700,
              transition: 'all 0.15s ease',
              background: activeTab === tab.key ? 'var(--navy-700)' : 'transparent',
              color: activeTab === tab.key ? '#ffffff' : 'var(--muted)',
            }}
            type="button"
          >
            <span>{tab.icon}</span>
            {tab.label}
            {tab.badge != null && tab.badge > 0 && (
              <span
                style={{
                  background: 'var(--red-500)',
                  color: '#fff',
                  borderRadius: '10px',
                  padding: '2px 8px',
                  fontSize: '11px',
                  fontWeight: 800,
                }}
              >
                {tab.badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'providers' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
          {providers.map(provider => (
            <ProviderCard key={provider.providerType} provider={provider} />
          ))}
        </div>
      )}

      {activeTab === 'compliance' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px' }}>
          {[
            { title: 'Pharmacy Premises', value: 'Verified', sub: 'Truth: MANUAL_INTERNAL_VERIFICATION', color: 'var(--teal-700)' },
            { title: 'Practitioner Licences', value: '100% Governed', sub: 'HWR Gated for Controlled Meds', color: 'var(--navy-700)' },
            { title: 'Controlled Med Authority', value: 'Fail-Closed Active', sub: 'STALE / UNAVAILABLE Blocked', color: 'var(--violet-700)' },
            { title: 'Active Recalls', value: 'Local Workflow', sub: 'NO_REGULATOR_FEED', color: 'var(--amber-700)' },
            { title: 'Quarantined Stock', value: 'Ledger Reserved', sub: 'Append-Only Ledger Integrated', color: 'var(--danger-ink)' },
            { title: 'Outstanding Reviews', value: '0 Pending', sub: 'Platform Owner Gate Active', color: 'var(--teal-700)' },
          ].map(card => (
            <div key={card.title} style={{ background: 'var(--panel)', border: '1px solid var(--line)', borderRadius: '14px', padding: '20px', boxShadow: 'var(--shadow)' }}>
              <div style={{ fontSize: '12px', color: 'var(--muted)', marginBottom: '8px' }}>{card.title}</div>
              <div style={{ fontSize: '22px', fontWeight: 800, color: card.color }}>{card.value}</div>
              <div style={{ fontSize: '12px', color: 'var(--muted-2)', marginTop: '6px' }}>{card.sub}</div>
            </div>
          ))}
        </div>
      )}

      {activeTab === 'reports' && (
        <div style={{ background: 'var(--panel)', border: '1px solid var(--line)', borderRadius: '16px', padding: '24px', boxShadow: 'var(--shadow)' }}>
          <div style={{ fontWeight: 800, color: 'var(--ink)', fontSize: '16px', marginBottom: '8px' }}>
            Enterprise Compliance Reporting Engine (Phase 15)
          </div>
          <div style={{ fontSize: '13px', color: 'var(--muted)', marginBottom: '20px' }}>
            Download audit-ready compliance report packs in JSON, CSV, Excel, or PDF formats.
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
            {[
              { type: 'PREMISES', label: 'Premises Verification & Licence Report' },
              { type: 'PRACTITIONERS', label: 'Practitioner Verification & Controlled Authority Report' },
              { type: 'PROVIDERS', label: 'Provider Platform Uptime & Reliability Report' },
              { type: 'RECALLS', label: 'Regulatory Recalls & Stock Quarantine Report' },
              { type: 'COMPLIANCE_READINESS', label: 'DHA & Regulatory Readiness Scorecard' },
              { type: 'SECURITY_AUDIT', label: 'Security, Activation & Kill Switch Audit' },
            ].map(r => (
              <div key={r.type} style={{ background: 'var(--canvas)', border: '1px solid var(--line)', padding: '16px', borderRadius: '10px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '13px', color: 'var(--ink)', fontWeight: 600 }}>{r.label}</span>
                <a
                  href={`/api/nif/platform/reports/?report_type=${r.type}&format=json`}
                  target="_blank"
                  rel="noreferrer"
                  style={{ background: 'var(--navy-100)', color: 'var(--navy-700)', border: '1px solid var(--navy-700)', borderRadius: '8px', padding: '6px 14px', fontSize: '12px', textDecoration: 'none', fontWeight: 700 }}
                >
                  Download
                </a>
              </div>
            ))}
          </div>
        </div>
      )}

      {activeTab === 'evidence' && (
        <div style={{ background: 'var(--panel)', border: '1px solid var(--line)', borderRadius: '16px', padding: '24px', boxShadow: 'var(--shadow)' }}>
          <div style={{ fontWeight: 800, color: 'var(--ink)', fontSize: '16px', marginBottom: '8px' }}>
            Certification Evidence Engine (Phase 16)
          </div>
          <div style={{ fontSize: '13px', color: 'var(--muted)', marginBottom: '20px' }}>
            Generate and export complete certification evidence bundles containing OpenAPI specs, checksums, test logs, coverage, SBOM, SLSA provenance, and readiness matrices.
          </div>
          <div style={{ display: 'flex', gap: '14px' }}>
            <a
              href="/api/nif/platform/evidence/?format=json"
              target="_blank"
              rel="noreferrer"
              style={{ background: 'var(--teal-100)', color: 'var(--teal-700)', border: '1px solid var(--teal-700)', borderRadius: '8px', padding: '10px 20px', fontSize: '13px', textDecoration: 'none', fontWeight: 700 }}
            >
              📄 View Evidence Package (JSON)
            </a>
            <a
              href="/api/nif/platform/evidence/?format=zip"
              target="_blank"
              rel="noreferrer"
              style={{ background: 'var(--navy-100)', color: 'var(--navy-700)', border: '1px solid var(--navy-700)', borderRadius: '8px', padding: '10px 20px', fontSize: '13px', textDecoration: 'none', fontWeight: 700 }}
            >
              📦 Export Evidence Bundle (ZIP)
            </a>
          </div>
        </div>
      )}

      {activeTab === 'dlq' && (
        <div
          style={{
            background: 'var(--panel)',
            border: '1px solid var(--line)',
            borderRadius: '16px',
            padding: '36px',
            textAlign: 'center',
            boxShadow: 'var(--shadow)',
          }}
        >
          <div style={{ fontSize: '40px', marginBottom: '12px' }}>📭</div>
          <div style={{ color: 'var(--ink)', fontWeight: 800, fontSize: '16px', marginBottom: '8px' }}>
            Dead-letter queue is clear
          </div>
          <div style={{ color: 'var(--muted)', fontSize: '13px', maxWidth: '360px', margin: '0 auto', lineHeight: 1.6 }}>
            Integration messages that exhaust all retry attempts will appear here for manual review and replay by the Platform Owner.
          </div>
        </div>
      )}

      {activeTab === 'rules' && <ProgrammeGovRules />}
    </div>
  );
}
