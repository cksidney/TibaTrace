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
      {/* Header */}
      <div
        style={{
          background: 'linear-gradient(135deg, rgba(39,174,96,0.15) 0%, rgba(26,35,50,0.8) 100%)',
          border: '1px solid rgba(39,174,96,0.3)',
          borderRadius: '16px',
          padding: '24px 28px',
          marginBottom: '24px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', marginBottom: '8px' }}>
          <div style={{ fontSize: '28px' }}>⚖️</div>
          <div>
            <div style={{ fontWeight: 700, fontSize: '20px', color: '#dde6f0' }}>
              Kenya Regulatory & Licence Governance Workspace
            </div>
            <div style={{ fontSize: '12px', color: '#6b7a8d', marginTop: '2px' }}>
              Pharmacy and Poisons Board (PPB) · Digital Health Agency (DHA) Compliance Engine
            </div>
          </div>
        </div>
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            padding: '4px 12px',
            background: 'rgba(39,174,96,0.2)',
            border: '1px solid rgba(39,174,96,0.4)',
            borderRadius: '6px',
            fontSize: '11px',
            color: '#66dd88',
            fontWeight: 600,
          }}
        >
          🛡️ Internal Compliance Review Active — Truth Label: MANUAL_INTERNAL_VERIFICATION
        </div>
      </div>

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
              background: activeTab === tab.key ? 'rgba(39,174,96,0.2)' : 'transparent',
              color: activeTab === tab.key ? '#66dd88' : '#6b7a8d',
            }}
          >
            {tab.icon} {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Panels */}
      {activeTab === 'premises' && (
        <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '14px', padding: '20px' }}>
          <div style={{ fontWeight: 700, color: '#dde6f0', fontSize: '15px', marginBottom: '12px' }}>
            Premises Licences & Superintendent Governance
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px', marginBottom: '20px' }}>
            <div style={{ background: 'rgba(0,0,0,0.2)', padding: '14px', borderRadius: '8px' }}>
              <div style={{ fontSize: '11px', color: '#6b7a8d' }}>Active Verified Premises</div>
              <div style={{ fontSize: '20px', fontWeight: 700, color: '#27ae60', marginTop: '4px' }}>1 Verified</div>
              <div style={{ fontSize: '10px', color: '#8894a6', marginTop: '2px' }}>Truth: MANUAL_INTERNAL_VERIFICATION</div>
            </div>
            <div style={{ background: 'rgba(0,0,0,0.2)', padding: '14px', borderRadius: '8px' }}>
              <div style={{ fontSize: '11px', color: '#6b7a8d' }}>Superintendent Pharmacist</div>
              <div style={{ fontSize: '14px', fontWeight: 600, color: '#c8d6e8', marginTop: '4px' }}>Dr. Sidney Kibet (Reg #2026-P)</div>
              <div style={{ fontSize: '10px', color: '#27ae60', marginTop: '2px' }}>Licence Current</div>
            </div>
            <div style={{ background: 'rgba(0,0,0,0.2)', padding: '14px', borderRadius: '8px' }}>
              <div style={{ fontSize: '11px', color: '#6b7a8d' }}>Self-Verification Block</div>
              <div style={{ fontSize: '14px', fontWeight: 600, color: '#2980b9', marginTop: '4px' }}>Enforced</div>
              <div style={{ fontSize: '10px', color: '#8894a6', marginTop: '2px' }}>Reviewer must differ from Submitter</div>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'practitioners' && (
        <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '14px', padding: '20px' }}>
          <div style={{ fontWeight: 700, color: '#dde6f0', fontSize: '15px', marginBottom: '12px' }}>
            DHA Health Worker Registry (HWR) Practitioner Verification
          </div>
          <div style={{ fontSize: '12px', color: '#6b7a8d', marginBottom: '16px' }}>
            All prescribers and pharmacists are checked against the 11-stage HWR verification lifecycle.
          </div>
          <div style={{ background: 'rgba(0,0,0,0.2)', padding: '14px', borderRadius: '8px', fontSize: '12px', color: '#c8d6e8' }}>
            <strong>Degraded Mode Policy:</strong> PROVIDER_UNAVAILABLE allows routine prescribing under degraded mode audit, but strictly fails closed for controlled medicines.
          </div>
        </div>
      )}

      {activeTab === 'controlled' && (
        <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '14px', padding: '20px' }}>
          <div style={{ fontWeight: 700, color: '#e74c3c', fontSize: '15px', marginBottom: '12px' }}>
            Controlled Medicine Dispensing Authority & Gating
          </div>
          <div style={{ fontSize: '12px', color: '#6b7a8d', lineHeight: 1.6 }}>
            Controlled medicine dispensing requires active premises verification, verified practitioner licence, and valid controlled drug authority. Any STALE or EXPIRED status automatically blocks dispensing.
          </div>
        </div>
      )}

      {activeTab === 'products' && (
        <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '14px', padding: '20px' }}>
          <div style={{ fontWeight: 700, color: '#dde6f0', fontSize: '15px', marginBottom: '12px' }}>
            PPB Product Register & Status Projection
          </div>
          <div style={{ fontSize: '12px', color: '#6b7a8d' }}>
            Products are evaluated for regulatory status (CURRENTLY_VERIFIED, STALE, SUSPENDED, WITHDRAWN, EXPIRED, UNKNOWN).
          </div>
        </div>
      )}

      {activeTab === 'recalls' && (
        <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '14px', padding: '20px' }}>
          <div style={{ fontWeight: 700, color: '#dde6f0', fontSize: '15px', marginBottom: '12px' }}>
            Regulatory Alerts & Recall Ingestion Engine
          </div>
          <div style={{ fontSize: '12px', color: '#6b7a8d' }}>
            Workflow: Alert → Affected GTINs → Batches → Branch Quarantine (Append-Only Inventory Ledger) → Actions → Evidence → Release → Closure.
          </div>
        </div>
      )}

      {activeTab === 'evidence' && (
        <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '14px', padding: '20px' }}>
          <div style={{ fontWeight: 700, color: '#dde6f0', fontSize: '15px', marginBottom: '12px' }}>
            Immutable Verification Snapshots & Audit Trail
          </div>
          <div style={{ fontSize: '12px', color: '#6b7a8d' }}>
            Snapshots are captured at every state transition and survive tenant suspension for compliance audit purposes.
          </div>
        </div>
      )}
    </div>
  );
}
