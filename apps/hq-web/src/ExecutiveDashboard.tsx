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

  const handleSelect = (widget: (typeof widgets)[number]) => {
    setSelectedWidget(widget.id);
    if (onNavigate) onNavigate(widget.nav);
  };

  return (
    <div className="executive-dashboard">
      <div className="executive-banner">
        <div className="executive-banner-content">
          <div className="executive-banner-icon">🏛️</div>
          <div>
            <div className="executive-banner-title">
              Executive Operations Command Centre
            </div>
            <div className="executive-banner-subtitle">
              Sample operational indicators · These example values are not live operational data.
            </div>
          </div>
        </div>
      </div>

      <div className="executive-grid">
        {widgets.map((w) => {
          const isSelected = selectedWidget === w.id;
          return (
            <div
              key={w.id}
              role="button"
              tabIndex={0}
              aria-label={`${w.title}: ${w.value}. Click to view ${w.nav}`}
              onClick={() => handleSelect(w)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  handleSelect(w);
                }
              }}
              className={`executive-widget${isSelected ? ' executive-widget-selected' : ''}`}
              style={{ '--widget-accent': w.color } as React.CSSProperties}
            >
              <div className="executive-widget-header">
                <span className="executive-widget-title">{w.title}</span>
                <span className="executive-widget-icon">{w.icon}</span>
              </div>
              <div className="executive-widget-value" style={{ color: w.color }}>
                {w.value}
              </div>
              <div className="executive-widget-sub">{w.sub}</div>
              <div className="executive-widget-action">
                <span>View {w.nav}</span>
                <span aria-hidden="true">→</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
