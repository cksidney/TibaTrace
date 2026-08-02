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
          <div style={{ fontSize: '32px' }}>🛡️</div>
          <div>
            <div style={{ fontWeight: 800, fontSize: '22px', color: 'var(--ink)' }}>
              Insurance & SHA Claims Integration Workspace
            </div>
            <div style={{ fontSize: '13px', color: 'var(--muted)', marginTop: '4px' }}>
              Social Health Authority (SHA) · Private Health Insurers · Real-time Adjudication
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
              background: 'var(--amber-100)',
              border: '1px solid var(--amber-700)',
              borderRadius: '8px',
              fontSize: '12px',
              color: 'var(--amber-700)',
              fontWeight: 700,
            }}
          >
            🔐 SHA / Insurance Provider Adapter — Platform Owner Activation Required
          </span>
        </div>
      </div>

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
              background: activeTab === tab.key ? 'var(--navy-700)' : 'transparent',
              color: activeTab === tab.key ? '#ffffff' : 'var(--muted)',
              transition: 'all 0.15s ease',
            }}
            type="button"
          >
            <span>{tab.icon}</span> {tab.label}
          </button>
        ))}
      </div>

      {/* Panels */}
      {activeTab === 'eligibility' && (
        <div
          style={{
            background: 'var(--panel)',
            border: '1px solid var(--line)',
            borderRadius: '16px',
            padding: '24px',
            boxShadow: 'var(--shadow)',
          }}
        >
          <div style={{ fontWeight: 700, color: 'var(--ink)', fontSize: '16px', marginBottom: '8px' }}>
            Real-Time Member Eligibility Verification
          </div>
          <div style={{ fontSize: '13px', color: 'var(--muted)', lineHeight: 1.5 }}>
            Verify member policy status, co-pay requirements, and benefit cap limits prior to dispensing.
          </div>
        </div>
      )}

      {activeTab === 'preauth' && (
        <div
          style={{
            background: 'var(--panel)',
            border: '1px solid var(--line)',
            borderRadius: '16px',
            padding: '24px',
            boxShadow: 'var(--shadow)',
          }}
        >
          <div style={{ fontWeight: 700, color: 'var(--ink)', fontSize: '16px', marginBottom: '8px' }}>
            Pre-Authorisation Requests & Approval Tracking
          </div>
          <div style={{ fontSize: '13px', color: 'var(--muted)', lineHeight: 1.5 }}>
            Submit and track pre-authorisation requests for high-value specialty medicines and chronic refills.
          </div>
        </div>
      )}

      {activeTab === 'claims' && (
        <div
          style={{
            background: 'var(--panel)',
            border: '1px solid var(--line)',
            borderRadius: '16px',
            padding: '24px',
            boxShadow: 'var(--shadow)',
          }}
        >
          <div style={{ fontWeight: 700, color: 'var(--ink)', fontSize: '16px', marginBottom: '8px' }}>
            Insurance Claims Queue & Batch Submission
          </div>
          <div style={{ fontSize: '13px', color: 'var(--muted)', lineHeight: 1.5 }}>
            Batch claim generation, FHIR Claim resource mapping, and adjudication tracking.
          </div>
        </div>
      )}

      {activeTab === 'rejections' && (
        <div
          style={{
            background: 'var(--panel)',
            border: '1px solid var(--line)',
            borderRadius: '16px',
            padding: '24px',
            boxShadow: 'var(--shadow)',
          }}
        >
          <div style={{ fontWeight: 700, color: 'var(--ink)', fontSize: '16px', marginBottom: '8px' }}>
            Rejection Management & Appeal Workflows
          </div>
          <div style={{ fontSize: '13px', color: 'var(--muted)', lineHeight: 1.5 }}>
            Review rejected claim line items, attach clinical notes, and resubmit appeals.
          </div>
        </div>
      )}

      {activeTab === 'remittance' && (
        <div
          style={{
            background: 'var(--panel)',
            border: '1px solid var(--line)',
            borderRadius: '16px',
            padding: '24px',
            boxShadow: 'var(--shadow)',
          }}
        >
          <div style={{ fontWeight: 700, color: 'var(--ink)', fontSize: '16px', marginBottom: '8px' }}>
            Remittance Advice & Financial Reconciliation
          </div>
          <div style={{ fontSize: '13px', color: 'var(--muted)', lineHeight: 1.5 }}>
            Reconcile electronic remittance advice (ERA) against submitted claims and ledger accounts.
          </div>
        </div>
      )}
    </div>
  );
}
