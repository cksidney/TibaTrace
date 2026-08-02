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
  ADAPTER_SCAFFOLDED_NOT_CONNECTED: { bg: '#1e2a3a', text: '#7aa2cc', dot: '#4a7fa5' },
  NOT_CONFIGURED:                   { bg: '#2a1e2a', text: '#cc7ab0', dot: '#a54a8a' },
  MANUAL_INTERNAL_VERIFICATION:     { bg: '#1e2a1e', text: '#7acc8a', dot: '#4aa560' },
  SNAPSHOT_IMPORTED_STALENESS_GOVERNED: { bg: '#2a2a1e', text: '#ccc07a', dot: '#a59440' },
  LOCAL_RECALL_WORKFLOW_NO_REGULATOR_FEED: { bg: '#2a1e1e', text: '#cc8a7a', dot: '#a55040' },
  MANUAL_VERIFICATION:              { bg: '#1e2a1e', text: '#7acc8a', dot: '#4aa560' },
  DISABLED_IN_PRODUCTION:           { bg: '#1e1e1e', text: '#888888', dot: '#555555' },
  SANDBOX_EVIDENCE_ONLY:            { bg: '#1e2228', text: '#7ab8cc', dot: '#4a8ea5' },
  PPB_API_ACTIVE:                   { bg: '#1e2a1e', text: '#66dd88', dot: '#44bb66' },
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

// Mock provider data — truth labels reflect actual state (not operational)
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
        gap: '5px',
        padding: '3px 9px',
        borderRadius: '12px',
        fontSize: '10px',
        fontWeight: 600,
        letterSpacing: '0.04em',
        textTransform: 'uppercase',
        background: colors.bg,
        color: colors.text,
        border: `1px solid ${colors.dot}33`,
        whiteSpace: 'nowrap',
      }}
    >
      <span
        style={{
          display: 'inline-block',
          width: '6px',
          height: '6px',
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
    <div style={{ marginTop: '10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '5px' }}>
        <span style={{ fontSize: '11px', color: '#8894a6', fontWeight: 500 }}>
          Activation stage
        </span>
        <span style={{ fontSize: '11px', color: '#c8d6e8', fontWeight: 600 }}>
          {ACTIVATION_STATE_LABELS[state]}
        </span>
      </div>
      <div style={{ height: '4px', background: '#1a2332', borderRadius: '2px', overflow: 'hidden' }}>
        <div
          style={{
            height: '100%',
            width: `${isTerminal ? 100 : progress}%`,
            background: isTerminal
              ? 'linear-gradient(90deg, #c0392b, #e74c3c)'
              : 'linear-gradient(90deg, #2980b9, #27ae60)',
            borderRadius: '2px',
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
        background: 'linear-gradient(135deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.01) 100%)',
        border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: '14px',
        padding: '20px',
        backdropFilter: 'blur(8px)',
        transition: 'all 0.2s ease',
        cursor: 'pointer',
      }}
      onClick={() => setExpanded(e => !e)}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '14px' }}>
        <div
          style={{
            width: '42px',
            height: '42px',
            borderRadius: '10px',
            background: 'rgba(255,255,255,0.06)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '20px',
            flexShrink: 0,
          }}
        >
          {icon}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, color: '#dde6f0', fontSize: '14px', marginBottom: '4px' }}>
            {provider.displayName}
          </div>
          <TruthLabelBadge label={provider.truthLabel} />
          <ActivationProgressBar state={provider.activationState} />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '6px' }}>
          {provider.pendingDeadLetters > 0 && (
            <span
              style={{
                background: 'rgba(231,76,60,0.2)',
                color: '#e74c3c',
                border: '1px solid rgba(231,76,60,0.3)',
                borderRadius: '10px',
                padding: '2px 8px',
                fontSize: '11px',
                fontWeight: 700,
              }}
            >
              {provider.pendingDeadLetters} DLQ
            </span>
          )}
          <span style={{ color: '#4a5568', fontSize: '12px' }}>
            {expanded ? '▲' : '▼'}
          </span>
        </div>
      </div>

      {expanded && (
        <div
          style={{
            marginTop: '16px',
            paddingTop: '16px',
            borderTop: '1px solid rgba(255,255,255,0.06)',
          }}
        >
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', fontSize: '12px' }}>
            <div>
              <div style={{ color: '#6b7a8d', marginBottom: '3px' }}>Provider type</div>
              <div style={{ color: '#c8d6e8', fontFamily: 'monospace' }}>{provider.providerType}</div>
            </div>
            <div>
              <div style={{ color: '#6b7a8d', marginBottom: '3px' }}>Last health check</div>
              <div style={{ color: '#c8d6e8' }}>
                {provider.lastHealthChecked
                  ? new Date(provider.lastHealthChecked).toLocaleString()
                  : 'Never checked'}
              </div>
            </div>
            <div>
              <div style={{ color: '#6b7a8d', marginBottom: '3px' }}>Reachability</div>
              <div style={{ color: provider.isReachable == null ? '#4a5568' : provider.isReachable ? '#27ae60' : '#e74c3c' }}>
                {provider.isReachable == null ? '— not yet probed' : provider.isReachable ? 'Reachable' : 'Unreachable'}
              </div>
            </div>
            <div>
              <div style={{ color: '#6b7a8d', marginBottom: '3px' }}>Dead-letter queue</div>
              <div style={{ color: provider.pendingDeadLetters > 0 ? '#e74c3c' : '#27ae60' }}>
                {provider.pendingDeadLetters > 0 ? `${provider.pendingDeadLetters} pending` : 'Clear'}
              </div>
            </div>
          </div>

          <div
            style={{
              marginTop: '14px',
              padding: '12px',
              background: 'rgba(0,0,0,0.2)',
              borderRadius: '8px',
              fontSize: '11px',
              color: '#6b7a8d',
              lineHeight: 1.6,
            }}
          >
            <strong style={{ color: '#7aa2cc' }}>Platform Owner action required</strong> to advance
            this integration beyond {ACTIVATION_STATE_LABELS[provider.activationState]}.
            No live traffic will be sent until this provider reaches{' '}
            <strong style={{ color: '#7aa2cc' }}>ACTIVE</strong> state with approved credentials.
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
        gap: '14px',
        marginBottom: '28px',
      }}
    >
      {[
        { label: 'Active integrations', value: active, color: '#27ae60', bg: 'rgba(39,174,96,0.1)' },
        { label: 'Pending activation', value: pending, color: '#f39c12', bg: 'rgba(243,156,18,0.1)' },
        { label: 'Blocked / terminal', value: blocked, color: '#e74c3c', bg: 'rgba(231,76,60,0.1)' },
      ].map(({ label, value, color, bg }) => (
        <div
          key={label}
          style={{
            background: bg,
            border: `1px solid ${color}33`,
            borderRadius: '12px',
            padding: '16px',
            textAlign: 'center',
          }}
        >
          <div style={{ fontSize: '28px', fontWeight: 700, color, lineHeight: 1 }}>{value}</div>
          <div style={{ fontSize: '11px', color: '#6b7a8d', marginTop: '6px' }}>{label}</div>
        </div>
      ))}
    </div>
  );
}

function ProgrammeGovRules() {
  return (
    <div
      style={{
        background: 'linear-gradient(135deg, rgba(74,127,165,0.08) 0%, rgba(39,130,120,0.05) 100%)',
        border: '1px solid rgba(74,127,165,0.2)',
        borderRadius: '14px',
        padding: '20px',
        marginBottom: '28px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '14px' }}>
        <span style={{ fontSize: '18px' }}>🔒</span>
        <span style={{ fontWeight: 700, color: '#7aa2cc', fontSize: '13px', letterSpacing: '0.04em', textTransform: 'uppercase' }}>
          Programme Governance Rules (Phase 16 — N1 to N8)
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', fontSize: '12px', lineHeight: 1.6 }}>
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
          <div key={phase} style={{ display: 'flex', gap: '8px' }}>
            <span
              style={{
                display: 'inline-block',
                minWidth: '26px',
                height: '18px',
                lineHeight: '18px',
                background: 'rgba(74,127,165,0.25)',
                color: '#7aa2cc',
                borderRadius: '4px',
                fontSize: '10px',
                fontWeight: 700,
                textAlign: 'center',
                flexShrink: 0,
              }}
            >
              {phase}
            </span>
            <span style={{ color: '#8894a6' }}>{text}</span>
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
        headers: { 'Accept': 'application/json' },
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
      {/* Header */}
      <div
        style={{
          background: 'linear-gradient(135deg, rgba(42,63,84,0.6) 0%, rgba(26,35,50,0.8) 100%)',
          border: '1px solid rgba(255,255,255,0.07)',
          borderRadius: '16px',
          padding: '24px 28px',
          marginBottom: '24px',
          backdropFilter: 'blur(12px)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', marginBottom: '10px' }}>
          <div
            style={{
              width: '44px',
              height: '44px',
              borderRadius: '12px',
              background: 'linear-gradient(135deg, #1a4a7a, #0d6b6b)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '22px',
            }}
          >
            🏗️
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: '18px', color: '#dde6f0', lineHeight: 1.2 }}>
              National Integration Command Centre
            </div>
            <div style={{ fontSize: '12px', color: '#6b7a8d', marginTop: '2px' }}>
              Kenya Digital Health Agency · Pharmacy and Poisons Board integrations
            </div>
          </div>
        </div>
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            padding: '5px 12px',
            background: 'rgba(231,76,60,0.12)',
            border: '1px solid rgba(231,76,60,0.25)',
            borderRadius: '8px',
            fontSize: '11px',
            color: '#e74c3c',
            fontWeight: 600,
          }}
        >
          ⚠️ No live national integrations active — Platform Owner approval required for all providers
        </div>
      </div>

      {loading && (
        <div style={{ padding: '12px', background: 'rgba(74,127,165,0.1)', color: '#7aa2cc', borderRadius: '8px', marginBottom: '16px', fontSize: '12px' }}>
          ⏳ Fetching platform integration configurations...
        </div>
      )}

      {error && (
        <div style={{ padding: '12px', background: 'rgba(231,76,60,0.1)', color: '#e74c3c', borderRadius: '8px', marginBottom: '16px', fontSize: '12px' }}>
          ⛔ {error}
        </div>
      )}

      {/* Summary cards */}
      <ActivationGateSummary providers={providers} />

      {/* Tabs */}
      <div
        style={{
          display: 'flex',
          gap: '4px',
          background: 'rgba(0,0,0,0.2)',
          borderRadius: '10px',
          padding: '4px',
          marginBottom: '20px',
          width: 'fit-content',
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
              gap: '6px',
              padding: '8px 16px',
              borderRadius: '7px',
              border: 'none',
              cursor: 'pointer',
              fontSize: '12px',
              fontWeight: 600,
              transition: 'all 0.15s ease',
              background: activeTab === tab.key ? 'rgba(74,127,165,0.2)' : 'transparent',
              color: activeTab === tab.key ? '#7aa2cc' : '#6b7a8d',
            }}
          >
            {tab.icon}
            {tab.label}
            {tab.badge != null && tab.badge > 0 && (
              <span
                style={{
                  background: '#e74c3c',
                  color: '#fff',
                  borderRadius: '8px',
                  padding: '1px 6px',
                  fontSize: '10px',
                  fontWeight: 700,
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
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
          {providers.map(provider => (
            <ProviderCard key={provider.providerType} provider={provider} />
          ))}
        </div>
      )}

      {activeTab === 'compliance' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '14px' }}>
          {[
            { title: 'Pharmacy Premises', value: 'Verified', sub: 'Truth: MANUAL_INTERNAL_VERIFICATION', color: '#27ae60' },
            { title: 'Practitioner Licences', value: '100% Governed', sub: 'HWR Gated for Controlled Meds', color: '#2980b9' },
            { title: 'Controlled Med Authority', value: 'Fail-Closed Active', sub: 'STALE / UNAVAILABLE Blocked', color: '#8e44ad' },
            { title: 'Active Recalls', value: 'Local Workflow', sub: 'NO_REGULATOR_FEED', color: '#e67e22' },
            { title: 'Quarantined Stock', value: 'Ledger Reserved', sub: 'Append-Only Ledger Integrated', color: '#c0392b' },
            { title: 'Outstanding Reviews', value: '0 Pending', sub: 'Platform Owner Gate Active', color: '#16a085' },
          ].map(card => (
            <div key={card.title} style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '12px', padding: '16px' }}>
              <div style={{ fontSize: '11px', color: '#6b7a8d', marginBottom: '6px' }}>{card.title}</div>
              <div style={{ fontSize: '20px', fontWeight: 700, color: card.color }}>{card.value}</div>
              <div style={{ fontSize: '11px', color: '#8894a6', marginTop: '4px' }}>{card.sub}</div>
            </div>
          ))}
        </div>
      )}

      {activeTab === 'reports' && (
        <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '14px', padding: '24px' }}>
          <div style={{ fontWeight: 700, color: '#dde6f0', fontSize: '15px', marginBottom: '12px' }}>
            Enterprise Compliance Reporting Engine (Phase 15)
          </div>
          <div style={{ fontSize: '12px', color: '#6b7a8d', marginBottom: '20px' }}>
            Download audit-ready compliance report packs in JSON, CSV, Excel, or PDF formats.
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            {[
              { type: 'PREMISES', label: 'Premises Verification & Licence Report' },
              { type: 'PRACTITIONERS', label: 'Practitioner Verification & Controlled Authority Report' },
              { type: 'PROVIDERS', label: 'Provider Platform Uptime & Reliability Report' },
              { type: 'RECALLS', label: 'Regulatory Recalls & Stock Quarantine Report' },
              { type: 'COMPLIANCE_READINESS', label: 'DHA & Regulatory Readiness Scorecard' },
              { type: 'SECURITY_AUDIT', label: 'Security, Activation & Kill Switch Audit' },
            ].map(r => (
              <div key={r.type} style={{ background: 'rgba(0,0,0,0.2)', padding: '14px', borderRadius: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '12px', color: '#c8d6e8', fontWeight: 500 }}>{r.label}</span>
                <a
                  href={`/api/nif/platform/reports/?report_type=${r.type}&format=json`}
                  target="_blank"
                  rel="noreferrer"
                  style={{ background: 'rgba(74,127,165,0.25)', color: '#7aa2cc', border: '1px solid rgba(74,127,165,0.4)', borderRadius: '6px', padding: '4px 10px', fontSize: '11px', textDecoration: 'none', fontWeight: 600 }}
                >
                  Download
                </a>
              </div>
            ))}
          </div>
        </div>
      )}

      {activeTab === 'evidence' && (
        <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '14px', padding: '24px' }}>
          <div style={{ fontWeight: 700, color: '#dde6f0', fontSize: '15px', marginBottom: '8px' }}>
            Certification Evidence Engine (Phase 16)
          </div>
          <div style={{ fontSize: '12px', color: '#6b7a8d', marginBottom: '16px' }}>
            Generate and export complete certification evidence bundles containing OpenAPI specs, checksums, test logs, coverage, SBOM, SLSA provenance, and readiness matrices.
          </div>
          <div style={{ display: 'flex', gap: '12px' }}>
            <a
              href="/api/nif/platform/evidence/?format=json"
              target="_blank"
              rel="noreferrer"
              style={{ background: 'rgba(39,174,96,0.2)', color: '#27ae60', border: '1px solid rgba(39,174,96,0.4)', borderRadius: '8px', padding: '10px 18px', fontSize: '12px', textDecoration: 'none', fontWeight: 600 }}
            >
              📄 View Evidence Package (JSON)
            </a>
            <a
              href="/api/nif/platform/evidence/?format=zip"
              target="_blank"
              rel="noreferrer"
              style={{ background: 'rgba(41,128,185,0.2)', color: '#2980b9', border: '1px solid rgba(41,128,185,0.4)', borderRadius: '8px', padding: '10px 18px', fontSize: '12px', textDecoration: 'none', fontWeight: 600 }}
            >
              📦 Export Evidence Bundle (ZIP)
            </a>
          </div>
        </div>
      )}

      {activeTab === 'dlq' && (
        <div
          style={{
            background: 'linear-gradient(135deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.01) 100%)',
            border: '1px solid rgba(255,255,255,0.07)',
            borderRadius: '14px',
            padding: '32px',
            textAlign: 'center',
          }}
        >
          <div style={{ fontSize: '36px', marginBottom: '12px' }}>📭</div>
          <div style={{ color: '#dde6f0', fontWeight: 600, fontSize: '15px', marginBottom: '8px' }}>
            Dead-letter queue is clear
          </div>
          <div style={{ color: '#6b7a8d', fontSize: '12px', maxWidth: '340px', margin: '0 auto', lineHeight: 1.6 }}>
            Integration messages that exhaust all retry attempts will appear here for manual review and replay by the Platform Owner.
          </div>
        </div>
      )}

      {activeTab === 'rules' && <ProgrammeGovRules />}
    </div>
  );
}
