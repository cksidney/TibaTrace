import { useState } from 'react';

interface InsuranceWorkspaceProps {
  csrfToken: string;
}

export function InsuranceWorkspace({ csrfToken: _csrfToken }: InsuranceWorkspaceProps) {
  const [activeTab, setActiveTab] = useState<'eligibility' | 'preauth' | 'claims' | 'rejections' | 'remittance'>('eligibility');

  const tabs = [
    { key: 'eligibility' as const, label: 'Patient Eligibility', icon: '👤' },
    { key: 'preauth' as const, label: 'Pre-Authorisation', icon: '📝' },
    { key: 'claims' as const, label: 'Claims Engine', icon: '📄' },
    { key: 'rejections' as const, label: 'Rejections & Appeals', icon: '⚠️' },
    { key: 'remittance' as const, label: 'Remittance & Reconciliation', icon: '💰' },
  ];

  return (
    <div style={{ padding: '0 0 40px' }}>
      {/* Header */}
      <div
        style={{
          background: 'linear-gradient(135deg, rgba(230,126,34,0.15) 0%, rgba(26,35,50,0.8) 100%)',
          border: '1px solid rgba(230,126,34,0.3)',
          borderRadius: '16px',
          padding: '24px 28px',
          marginBottom: '24px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', marginBottom: '8px' }}>
          <div style={{ fontSize: '28px' }}>🛡️</div>
          <div>
            <div style={{ fontWeight: 700, fontSize: '20px', color: '#dde6f0' }}>
              Insurance & SHA Claims Integration Workspace
            </div>
            <div style={{ fontSize: '12px', color: '#6b7a8d', marginTop: '2px' }}>
              Social Health Authority (SHA) · Private Health Insurers · Real-time Adjudication
            </div>
          </div>
        </div>
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            padding: '4px 12px',
            background: 'rgba(230,126,34,0.2)',
            borderRadius: '6px',
            fontSize: '11px',
            color: '#f39c12',
            fontWeight: 600,
          }}
        >
          🔐 SHA / Insurance Provider Adapter — Platform Owner Activation Required
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
              background: activeTab === tab.key ? 'rgba(230,126,34,0.25)' : 'transparent',
              color: activeTab === tab.key ? '#f39c12' : '#6b7a8d',
            }}
          >
            {tab.icon} {tab.label}
          </button>
        ))}
      </div>

      {/* Panels */}
      {activeTab === 'eligibility' && (
        <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '14px', padding: '20px' }}>
          <div style={{ fontWeight: 700, color: '#dde6f0', fontSize: '15px', marginBottom: '12px' }}>
            Real-Time Member Eligibility Verification
          </div>
          <div style={{ fontSize: '12px', color: '#6b7a8d' }}>
            Verify member policy status, co-pay requirements, and benefit cap limits prior to dispensing.
          </div>
        </div>
      )}

      {activeTab === 'preauth' && (
        <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '14px', padding: '20px' }}>
          <div style={{ fontWeight: 700, color: '#dde6f0', fontSize: '15px', marginBottom: '12px' }}>
            Pre-Authorisation Requests & Approval Tracking
          </div>
          <div style={{ fontSize: '12px', color: '#6b7a8d' }}>
            Submit and track pre-authorisation requests for high-value specialty medicines and chronic refills.
          </div>
        </div>
      )}

      {activeTab === 'claims' && (
        <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '14px', padding: '20px' }}>
          <div style={{ fontWeight: 700, color: '#dde6f0', fontSize: '15px', marginBottom: '12px' }}>
            Insurance Claims Queue & Batch Submission
          </div>
          <div style={{ fontSize: '12px', color: '#6b7a8d' }}>
            Batch claim generation, FHIR Claim resource mapping, and adjudication tracking.
          </div>
        </div>
      )}

      {activeTab === 'rejections' && (
        <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '14px', padding: '20px' }}>
          <div style={{ fontWeight: 700, color: '#dde6f0', fontSize: '15px', marginBottom: '12px' }}>
            Rejection Management & Appeal Workflows
          </div>
          <div style={{ fontSize: '12px', color: '#6b7a8d' }}>
            Review rejected claim line items, attach clinical notes, and resubmit appeals.
          </div>
        </div>
      )}

      {activeTab === 'remittance' && (
        <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '14px', padding: '20px' }}>
          <div style={{ fontWeight: 700, color: '#dde6f0', fontSize: '15px', marginBottom: '12px' }}>
            Remittance Advice & Financial Reconciliation
          </div>
          <div style={{ fontSize: '12px', color: '#6b7a8d' }}>
            Reconcile electronic remittance advice (ERA) against submitted claims and ledger accounts.
          </div>
        </div>
      )}
    </div>
  );
}
