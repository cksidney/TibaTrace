import { useState } from 'react';

interface RegulatoryWorkspaceProps {
  csrfToken: string;
}

export function RegulatoryWorkspace({ csrfToken: _csrfToken }: RegulatoryWorkspaceProps) {
  const [activeTab, setActiveTab] = useState<'premises' | 'practitioners' | 'controlled' | 'products' | 'recalls' | 'evidence'>('premises');

  const tabs = [
    { key: 'premises' as const, label: 'Premises Verification', icon: '🏛️' },
    { key: 'practitioners' as const, label: 'Practitioners Governance', icon: '👨‍⚕️' },
    { key: 'controlled' as const, label: 'Controlled Medicines Authority', icon: '💊' },
    { key: 'products' as const, label: 'Product Status Projection', icon: '📋' },
    { key: 'recalls' as const, label: 'Regulatory Alerts & Recalls', icon: '🔴' },
    { key: 'evidence' as const, label: 'Audit Evidence & Snapshots', icon: '📦' },
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
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', marginBottom: '8px' }}>
          <div style={{ fontSize: '32px' }}>⚖️</div>
          <div>
            <div style={{ fontWeight: 800, fontSize: '22px', color: 'var(--ink)' }}>
              Kenya Regulatory & Licence Governance Workspace
            </div>
            <div style={{ fontSize: '13px', color: 'var(--muted)', marginTop: '4px' }}>
              Pharmacy and Poisons Board (PPB) · Digital Health Agency (DHA) Compliance Engine
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
              background: 'var(--teal-100)',
              border: '1px solid var(--teal-700)',
              borderRadius: '8px',
              fontSize: '12px',
              color: 'var(--teal-700)',
              fontWeight: 700,
            }}
          >
            🛡️ Internal Compliance Review Active — Truth Label: MANUAL_INTERNAL_VERIFICATION
          </span>
        </div>
      </div>

      {/* Navigation Tabs */}
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
              background: activeTab === tab.key ? 'var(--teal-700)' : 'transparent',
              color: activeTab === tab.key ? '#ffffff' : 'var(--muted)',
              transition: 'all 0.15s ease',
            }}
            type="button"
          >
            <span>{tab.icon}</span> {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Panels */}
      {activeTab === 'premises' && (
        <div
          style={{
            background: 'var(--panel)',
            border: '1px solid var(--line)',
            borderRadius: '16px',
            padding: '24px',
            boxShadow: 'var(--shadow)',
          }}
        >
          <div style={{ fontWeight: 700, color: 'var(--ink)', fontSize: '16px', marginBottom: '16px' }}>
            Premises Licences & Superintendent Governance
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px', marginBottom: '20px' }}>
            <div style={{ background: 'var(--canvas)', border: '1px solid var(--line)', padding: '18px', borderRadius: '12px' }}>
              <div style={{ fontSize: '12px', color: 'var(--muted)' }}>Active Verified Premises</div>
              <div style={{ fontSize: '22px', fontWeight: 800, color: 'var(--teal-700)', marginTop: '4px' }}>1 Verified</div>
              <div style={{ fontSize: '11px', color: 'var(--muted-2)', marginTop: '4px' }}>Truth: MANUAL_INTERNAL_VERIFICATION</div>
            </div>
            <div style={{ background: 'var(--canvas)', border: '1px solid var(--line)', padding: '18px', borderRadius: '12px' }}>
              <div style={{ fontSize: '12px', color: 'var(--muted)' }}>Superintendent Pharmacist</div>
              <div style={{ fontSize: '15px', fontWeight: 700, color: 'var(--ink)', marginTop: '4px' }}>Dr. Sidney Kibet (Reg #2026-P)</div>
              <div style={{ fontSize: '11px', color: 'var(--teal-700)', marginTop: '4px', fontWeight: 600 }}>Licence Current</div>
            </div>
            <div style={{ background: 'var(--canvas)', border: '1px solid var(--line)', padding: '18px', borderRadius: '12px' }}>
              <div style={{ fontSize: '12px', color: 'var(--muted)' }}>Self-Verification Block</div>
              <div style={{ fontSize: '15px', fontWeight: 700, color: 'var(--navy-700)', marginTop: '4px' }}>Enforced</div>
              <div style={{ fontSize: '11px', color: 'var(--muted-2)', marginTop: '4px' }}>Reviewer must differ from Submitter</div>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'practitioners' && (
        <div
          style={{
            background: 'var(--panel)',
            border: '1px solid var(--line)',
            borderRadius: '16px',
            padding: '24px',
            boxShadow: 'var(--shadow)',
          }}
        >
          <div style={{ fontWeight: 700, color: 'var(--ink)', fontSize: '16px', marginBottom: '12px' }}>
            DHA Health Worker Registry (HWR) Practitioner Verification
          </div>
          <div style={{ fontSize: '13px', color: 'var(--muted)', marginBottom: '16px', lineHeight: 1.5 }}>
            All prescribers and pharmacists are checked against the 11-stage HWR verification lifecycle.
          </div>
          <div style={{ background: 'var(--canvas)', border: '1px solid var(--line)', padding: '16px', borderRadius: '10px', fontSize: '13px', color: 'var(--ink)' }}>
            <strong>Degraded Mode Policy:</strong> PROVIDER_UNAVAILABLE allows routine prescribing under degraded mode audit, but strictly fails closed for controlled medicines.
          </div>
        </div>
      )}

      {activeTab === 'controlled' && (
        <div
          style={{
            background: 'var(--panel)',
            border: '1px solid var(--red-500)',
            borderRadius: '16px',
            padding: '24px',
            boxShadow: 'var(--shadow)',
          }}
        >
          <div style={{ fontWeight: 700, color: 'var(--danger-ink)', fontSize: '16px', marginBottom: '12px' }}>
            Controlled Medicine Dispensing Authority & Gating
          </div>
          <div style={{ fontSize: '13px', color: 'var(--muted)', lineHeight: 1.6 }}>
            Controlled medicine dispensing requires active premises verification, verified practitioner licence, and valid controlled drug authority. Any STALE or EXPIRED status automatically blocks dispensing.
          </div>
        </div>
      )}

      {activeTab === 'products' && (
        <div
          style={{
            background: 'var(--panel)',
            border: '1px solid var(--line)',
            borderRadius: '16px',
            padding: '24px',
            boxShadow: 'var(--shadow)',
          }}
        >
          <div style={{ fontWeight: 700, color: 'var(--ink)', fontSize: '16px', marginBottom: '12px' }}>
            PPB Product Register & Status Projection
          </div>
          <div style={{ fontSize: '13px', color: 'var(--muted)', lineHeight: 1.5 }}>
            Products are evaluated for regulatory status (CURRENTLY_VERIFIED, STALE, SUSPENDED, WITHDRAWN, EXPIRED, UNKNOWN).
          </div>
        </div>
      )}

      {activeTab === 'recalls' && (
        <div
          style={{
            background: 'var(--panel)',
            border: '1px solid var(--line)',
            borderRadius: '16px',
            padding: '24px',
            boxShadow: 'var(--shadow)',
          }}
        >
          <div style={{ fontWeight: 700, color: 'var(--ink)', fontSize: '16px', marginBottom: '12px' }}>
            Regulatory Alerts & Recall Ingestion Engine
          </div>
          <div style={{ fontSize: '13px', color: 'var(--muted)', lineHeight: 1.5 }}>
            Workflow: Alert → Affected GTINs → Batches → Branch Quarantine (Append-Only Inventory Ledger) → Actions → Evidence → Release → Closure.
          </div>
        </div>
      )}

      {activeTab === 'evidence' && (
        <div
          style={{
            background: 'var(--panel)',
            border: '1px solid var(--line)',
            borderRadius: '16px',
            padding: '24px',
            boxShadow: 'var(--shadow)',
          }}
        >
          <div style={{ fontWeight: 700, color: 'var(--ink)', fontSize: '16px', marginBottom: '12px' }}>
            Immutable Verification Snapshots & Audit Trail
          </div>
          <div style={{ fontSize: '13px', color: 'var(--muted)', lineHeight: 1.5 }}>
            Snapshots are captured at every state transition and survive tenant suspension for compliance audit purposes.
          </div>
        </div>
      )}
    </div>
  );
}
