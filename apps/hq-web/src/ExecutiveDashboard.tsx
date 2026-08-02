import { useState } from 'react';

interface ExecutiveDashboardProps {
  csrfToken: string;
  onNavigate?: (tab: string) => void;
}

export function ExecutiveDashboard({ csrfToken: _csrfToken, onNavigate }: ExecutiveDashboardProps) {
  const [selectedWidget, setSelectedWidget] = useState<string | null>(null);

  const widgets = [
    { id: 'dispensing', title: "Today's Dispensing", value: '142 Prescriptions', sub: 'KES 485,200 total value', color: 'var(--teal-700)', icon: '💊', nav: 'Dispensing' },
    { id: 'pending_rx', title: 'Pending Prescriptions', value: '8 Awaiting Review', sub: '3 High Priority', color: 'var(--amber-700)', icon: '📋', nav: 'Dispensing' },
    { id: 'insurance', title: 'Insurance Claims', value: '45 Submitted', sub: 'KES 310,000 pending adjudication', color: 'var(--navy-700)', icon: '🛡️', nav: 'Insurance' },
    { id: 'recalls', title: 'Recall Alerts', value: '1 Active Recall', sub: 'Batch BATCH-2026-001 quarantined', color: 'var(--red-700)', icon: '🔴', nav: 'National Integration' },
    { id: 'expiring_meds', title: 'Expiring Medicines', value: '12 SKUs < 60 days', sub: 'FEFO picking active', color: 'var(--amber-700)', icon: '⏳', nav: 'Inventory' },
    { id: 'expiring_licences', title: 'Expiring Licences', value: 'Premises Valid', sub: 'Superintendent licence current', color: 'var(--teal-700)', icon: '🏛️', nav: 'Regulatory' },
    { id: 'nif_health', title: 'National Integration Health', value: '81.5% Readiness', sub: 'DHA, PPB, HWR Externally Gated', color: 'var(--violet-700)', icon: '🌐', nav: 'National Integration' },
    { id: 'regulatory_actions', title: 'Outstanding Regulatory Actions', value: '0 Required', sub: 'All tenant impacts managed', color: 'var(--teal-700)', icon: '⚖️', nav: 'Regulatory' },
    { id: 'revenue', title: 'Today Revenue', value: 'KES 620,400', sub: 'Cash: 40% | Insurance: 60%', color: 'var(--teal-700)', icon: '💵', nav: 'Sales' },
    { id: 'stock_value', title: 'Total Stock Value', value: 'KES 18,450,000', sub: '4,280 total SKUs', color: 'var(--navy-700)', icon: '📊', nav: 'Inventory' },
    { id: 'stock_risk', title: 'Stock Risk Analysis', value: 'Low Risk', sub: 'Zero stock-outs on core meds', color: 'var(--teal-700)', icon: '🛡️', nav: 'Inventory' },
    { id: 'fefo_violations', title: 'FEFO Violations', value: '0 Violations', sub: 'Strict FEFO allocation active', color: 'var(--teal-700)', icon: '✅', nav: 'Inventory' },
    { id: 'quarantined_stock', title: 'Quarantined Stock', value: '350 Units Reserved', sub: 'Append-Only Ledger tracked', color: 'var(--red-700)', icon: '🔒', nav: 'Inventory' },
    { id: 'transfers', title: 'Outstanding Transfers', value: '2 In Transit', sub: 'Branch-to-Branch movements', color: 'var(--navy-700)', icon: '🚚', nav: 'Inventory' },
    { id: 'purchase_orders', title: 'Outstanding POs', value: '4 Active POs', sub: 'Awaiting supplier confirmation', color: 'var(--amber-700)', icon: '📝', nav: 'Procurement' },
    { id: 'goods_receipts', title: 'Pending Goods Receipts', value: '1 Arrived', sub: 'Quality inspection in progress', color: 'var(--violet-700)', icon: '📦', nav: 'Procurement' },
    { id: 'approvals', title: 'Outstanding Approvals', value: '0 Pending', sub: 'Dual sign-off current', color: 'var(--teal-700)', icon: '✍️', nav: 'Administration' },
    { id: 'platform_notifs', title: 'Platform Notifications', value: '3 Active Alerts', sub: '1 Critical, 2 Info', color: 'var(--amber-700)', icon: '🔔', nav: 'National Integration' },
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
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            <div style={{ fontSize: '32px' }}>🏛️</div>
            <div>
              <div style={{ fontWeight: 800, fontSize: '22px', color: 'var(--ink)' }}>
                Executive Operations Command Centre
              </div>
              <div style={{ fontSize: '13px', color: 'var(--muted)', marginTop: '4px' }}>
                TibaTrace National Health & Enterprise Pharmacy Operations Platform v0.2.0-rc10
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Widget Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px' }}>
        {widgets.map(w => (
          <div
            key={w.id}
            onClick={() => {
              setSelectedWidget(w.id);
              if (onNavigate) onNavigate(w.nav);
            }}
            style={{
              background: 'var(--panel)',
              border: `1px solid ${selectedWidget === w.id ? w.color : 'var(--line)'}`,
              borderRadius: '14px',
              padding: '20px',
              cursor: 'pointer',
              boxShadow: 'var(--shadow)',
              transition: 'all 0.15s ease',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
              <span style={{ fontSize: '13px', color: 'var(--muted)', fontWeight: 600 }}>{w.title}</span>
              <span style={{ fontSize: '22px' }}>{w.icon}</span>
            </div>
            <div style={{ fontSize: '20px', fontWeight: 800, color: w.color, lineHeight: 1.2 }}>{w.value}</div>
            <div style={{ fontSize: '12px', color: 'var(--muted-2)', marginTop: '8px' }}>{w.sub}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
