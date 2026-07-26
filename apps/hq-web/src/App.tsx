import { useCallback, useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';

import { HQApiError, loadHQOverview } from './api.js';
import type { DashboardMetric, HQOverview, NetworkItem } from './api.js';
import { Icon } from './icons.js';
import type { IconName } from './icons.js';

type WorkspaceView = 'overview' | 'network' | 'operations' | 'insurance' | 'clinical' | 'access';

interface NavigationItem {
  readonly caption: string;
  readonly icon: IconName;
  readonly key: WorkspaceView;
  readonly label: string;
}

const navigation: readonly NavigationItem[] = [
  { key: 'overview', label: 'Overview', caption: 'Command centre', icon: 'overview' },
  { key: 'network', label: 'Pharmacy network', caption: 'Tenants and locations', icon: 'network' },
  { key: 'operations', label: 'Inventory & procurement', caption: 'Stock and supply', icon: 'inventory' },
  { key: 'insurance', label: 'Insurance & Claims', caption: 'Adjudication & SHA', icon: 'insurance' },
  { key: 'clinical', label: 'Clinical governance', caption: 'Safety and standards', icon: 'clinical' },
  { key: 'access', label: 'Users & access', caption: 'Roles and security', icon: 'users' },
];

const viewMeta: Record<WorkspaceView, { readonly eyebrow: string; readonly title: string; readonly description: string }> = {
  overview: {
    eyebrow: 'Operational command centre',
    title: 'Health operations at a glance',
    description: 'A consolidated view of safety, stock, clinical and network signals across the active workspace.',
  },
  network: {
    eyebrow: 'Care network',
    title: 'Pharmacy network coverage',
    description: 'Review connected tenants, active care locations and the people operating across the network.',
  },
  operations: {
    eyebrow: 'Supply operations',
    title: 'Inventory & procurement',
    description: 'Track stock readiness, quality holds and active dispensing demand before it affects patient care.',
  },
  insurance: {
    eyebrow: 'Claims & Adjudication',
    title: 'Prescription Insurance Engine',
    description: 'Monitor real-time prescription claims, SHA gateway adapters, member preauthorisations, and remittance reconciliation.',
  },
  clinical: {
    eyebrow: 'Clinical governance',
    title: 'Safety & interoperability',
    description: 'Monitor clinical records, governed terminology and the FHIR R4 exchange surface.',
  },
  access: {
    eyebrow: 'Identity & control',
    title: 'Users & access',
    description: 'Understand the current security scope and move into audited identity administration.',
  },
};

export function App() {
  const [overview, setOverview] = useState<HQOverview | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshFailed, setRefreshFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    void loadHQOverview(controller.signal)
      .then(setOverview)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason);
      });
    return () => controller.abort();
  }, []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setRefreshFailed(false);
    try {
      setOverview(await loadHQOverview());
    } catch {
      setRefreshFailed(true);
    } finally {
      setRefreshing(false);
    }
  }, []);

  if (error instanceof HQApiError && (error.status === 401 || error.status === 403)) {
    return <AuthenticationRequired />;
  }
  if (error) return <Unavailable />;
  if (!overview) return <LoadingScreen />;

  return (
    <Dashboard
      overview={overview}
      onRefresh={refresh}
      refreshFailed={refreshFailed}
      refreshing={refreshing}
    />
  );
}

function Dashboard({
  overview,
  onRefresh,
  refreshFailed,
  refreshing,
}: {
  readonly overview: HQOverview;
  readonly onRefresh: () => Promise<void>;
  readonly refreshFailed: boolean;
  readonly refreshing: boolean;
}) {
  const [activeView, setActiveView] = useState<WorkspaceView>(() => viewFromHash());
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    return (localStorage.getItem('hq-theme') as 'dark' | 'light') || 'dark';
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('hq-theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));
  };

  useEffect(() => {
    const onHashChange = () => setActiveView(viewFromHash());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setCommandOpen((open) => !open);
      }
      if (event.key === 'Escape') {
        setCommandOpen(false);
        setMobileNavOpen(false);
        setNotificationsOpen(false);
        setUserMenuOpen(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const attentionCount = overview.attention_items.filter((item) => item.value > 0 && item.tone !== 'teal').length;
  const meta = viewMeta[activeView];

  const closeTransientUi = () => {
    setMobileNavOpen(false);
    setNotificationsOpen(false);
    setUserMenuOpen(false);
  };

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      {mobileNavOpen ? <button className="nav-scrim" aria-label="Close navigation" onClick={() => setMobileNavOpen(false)} type="button" /> : null}
      <Sidebar activeView={activeView} mobileOpen={mobileNavOpen} onNavigate={closeTransientUi} overview={overview} />

      <div className="workspace">
        <header className="topbar">
          <button className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => setMobileNavOpen(true)} type="button">
            <Icon name="menu" />
          </button>
          <div className="workspace-identity">
            <span>{overview.scope_label}</span>
            <strong>{overview.tenant_name}</strong>
          </div>
          <button className="search-trigger" onClick={() => setCommandOpen(true)} type="button">
            <Icon name="search" />
            <span>Search HQ or jump to a workspace</span>
            <kbd>⌘ K</kbd>
          </button>
          <div className="topbar-actions">
            <a className="health-link" href="/api/health/">
              <span className="status-dot" />
              System live
            </a>
            <button
              className="icon-button theme-toggle-btn"
              aria-label="Toggle Theme"
              onClick={toggleTheme}
              title={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} Mode`}
              type="button"
            >
              <span>{theme === 'dark' ? '🌙' : '☀️'}</span>
            </button>
            <div className="popover-anchor">
              <button
                className="icon-button"
                aria-expanded={notificationsOpen}
                aria-label={`Operational notifications${attentionCount ? `, ${attentionCount} need attention` : ''}`}
                onClick={() => {
                  setNotificationsOpen((open) => !open);
                  setUserMenuOpen(false);
                }}
                type="button"
              >
                <Icon name="alert" />
                {attentionCount ? <span className="notification-badge">{attentionCount}</span> : null}
              </button>
              {notificationsOpen ? <NotificationPopover overview={overview} /> : null}
            </div>
            <div className="popover-anchor">
              <button
                className="user-trigger"
                aria-expanded={userMenuOpen}
                onClick={() => {
                  setUserMenuOpen((open) => !open);
                  setNotificationsOpen(false);
                }}
                type="button"
              >
                <span>{initials(overview.user_name)}</span>
                <div>
                  <strong>{displayName(overview.user_name)}</strong>
                  <small>{overview.is_platform_overview ? 'Platform administrator' : 'Tenant operator'}</small>
                </div>
                <Icon name="chevron" />
              </button>
              {userMenuOpen ? <UserMenu overview={overview} /> : null}
            </div>
          </div>
        </header>

        <main id="main-content">
          <section className="page-intro">
            <div>
              <p className="eyebrow">{meta.eyebrow}</p>
              <h1>{activeView === 'overview' ? `${greeting()}, ${displayName(overview.user_name)}.` : meta.title}</h1>
              <p>{activeView === 'overview' ? overview.scope_description : meta.description}</p>
            </div>
            <div className="page-actions">
              <div className="updated-at">
                <span>Last refreshed</span>
                <strong>{formatTime(overview.generated_at)}</strong>
              </div>
              <button className="secondary-button" disabled={refreshing} onClick={() => void onRefresh()} type="button">
                <Icon className={refreshing ? 'spin' : ''} name="refresh" />
                {refreshing ? 'Refreshing' : 'Refresh data'}
              </button>
            </div>
          </section>

          {refreshFailed ? (
            <div className="inline-alert" role="status">
              <Icon name="alert" />
              The latest refresh failed. The last successful HQ snapshot remains visible.
            </div>
          ) : null}

          {activeView === 'overview' ? <OverviewView overview={overview} onNavigate={setActiveView} /> : null}
          {activeView === 'network' ? <NetworkView overview={overview} /> : null}
          {activeView === 'operations' ? <OperationsView overview={overview} /> : null}
          {activeView === 'insurance' ? <InsuranceView /> : null}
          {activeView === 'clinical' ? <ClinicalView overview={overview} /> : null}
          {activeView === 'access' ? <AccessView overview={overview} /> : null}
        </main>
      </div>

      {commandOpen ? <CommandPalette onClose={() => setCommandOpen(false)} onNavigate={setActiveView} /> : null}
    </div>
  );
}

function Sidebar({
  activeView,
  mobileOpen,
  onNavigate,
  overview,
}: {
  readonly activeView: WorkspaceView;
  readonly mobileOpen: boolean;
  readonly onNavigate: () => void;
  readonly overview: HQOverview;
}) {
  return (
    <aside className={mobileOpen ? 'sidebar sidebar-open' : 'sidebar'}>
      <div className="sidebar-head">
        <Brand />
        <button className="icon-button sidebar-close" aria-label="Close navigation" onClick={onNavigate} type="button">
          <Icon name="close" />
        </button>
      </div>
      <div className="workspace-pill">
        <span><Icon name={overview.is_platform_overview ? 'building' : 'store'} /></span>
        <div>
          <small>Current scope</small>
          <strong>{overview.tenant_name}</strong>
        </div>
      </div>
      <p className="sidebar-label">HQ workspace</p>
      <nav aria-label="Headquarters navigation">
        {navigation.map((item) => (
          <a
            aria-current={activeView === item.key ? 'page' : undefined}
            className={activeView === item.key ? 'nav-link nav-link-active' : 'nav-link'}
            href={`#${item.key}`}
            key={item.key}
            onClick={onNavigate}
          >
            <span><Icon name={item.icon} /></span>
            <div><strong>{item.label}</strong><small>{item.caption}</small></div>
          </a>
        ))}
      </nav>
      <div className="sidebar-support">
        <div className="support-icon"><Icon name="docs" /></div>
        <strong>Operations support</strong>
        <p>Inspect API contracts and integration guidance for connected applications.</p>
        <a href="/api/docs/">Open API workspace <Icon name="arrow" /></a>
      </div>
      <div className="secure-session"><Icon name="shield" /> Secure authenticated session</div>
    </aside>
  );
}

function OverviewView({ overview, onNavigate }: { readonly overview: HQOverview; readonly onNavigate: (view: WorkspaceView) => void }) {
  const summary = useSummary(overview);
  const networkItems = overview.network_items ?? [];

  return (
    <>
      <section className="metric-grid" aria-label="Network performance">
        {overview.metrics.map((metric, index) => <MetricCard key={metric.label} metric={metric} index={index} />)}
      </section>

      <section className="content-grid content-grid-primary">
        <article className="panel attention-panel">
          <PanelHeader eyebrow="Operational focus" title="What needs attention" actionLabel="Open operations" onAction={() => navigateTo('operations', onNavigate)} />
          <div className="attention-list">
            {overview.attention_items.map((item) => (
              <div className="attention-row" key={item.label}>
                <span className={`attention-icon attention-${item.tone}`}>
                  <Icon name={item.tone === 'rose' ? 'alert' : item.tone === 'teal' ? 'check' : 'activity'} />
                </span>
                <div><strong>{item.label}</strong><p>{item.detail}</p></div>
                <b>{formatNumber(item.value)}</b>
              </div>
            ))}
          </div>
        </article>

        <article className="panel network-summary-panel">
          <PanelHeader eyebrow="Network pulse" title="Connected care coverage" actionLabel="View network" onAction={() => navigateTo('network', onNavigate)} />
          <div className="network-hero">
            <div className="network-ring" style={{ '--progress': `${networkProgress(overview)}deg` } as CSSProperties}>
              <div><strong>{networkItems.length || metricValue(overview, 'Active tenants')}</strong><small>workspaces listed</small></div>
            </div>
            <div className="network-copy">
              <span className="positive-chip"><Icon name="activity" /> Live scope</span>
              <strong>{overview.is_platform_overview ? 'Kenya platform network' : overview.tenant_name}</strong>
              <p>Connected operational records are available for headquarters review.</p>
            </div>
          </div>
          <div className="compact-stats">
            <Stat label="Active locations" value={summary.get('Active locations') ?? 0} />
            <Stat label="Practitioners" value={summary.get('Practitioners') ?? 0} />
            <Stat label="Active users" value={summary.get('Active users') ?? 0} />
          </div>
        </article>
      </section>

      <section className="content-grid">
        <article className="panel data-panel">
          <PanelHeader eyebrow="Data estate" title="Current record coverage" />
          <div className="data-bars">
            {[
              ['Patients', metricValue(overview, 'Patients'), 'patients'],
              ['Clinical encounters', summary.get('Clinical encounters') ?? 0, 'clinical'],
              ['Observations', summary.get('Observations') ?? 0, 'activity'],
              ['Inventory batches', summary.get('Inventory batches') ?? 0, 'inventory'],
            ].map(([label, value, icon]) => (
              <DataBar icon={icon as IconName} key={label as string} label={label as string} max={largestOverviewValue(overview)} value={value as number} />
            ))}
          </div>
        </article>

        <article className="panel command-panel">
          <PanelHeader eyebrow="Command centre" title="Move into a workspace" />
          <div className="command-links">
            <CommandLink href="/pos/" title="Point of sale" detail="Dispensing and sales operations" icon="store" />
            <CommandLink href="/admin/" title="Administration" detail="Reference data and controls" icon="settings" />
            <CommandLink href="/api/docs/" title="API workspace" detail="Integration contracts and testing" icon="docs" />
          </div>
        </article>
      </section>
    </>
  );
}

function NetworkView({ overview }: { readonly overview: HQOverview }) {
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('ALL');
  const items = overview.network_items ?? [];
  const visibleItems = items.filter((item) => {
    const matchesQuery = `${item.name} ${item.slug} ${item.country_code}`.toLowerCase().includes(query.toLowerCase());
    return matchesQuery && (status === 'ALL' || item.status === status);
  });
  const totals = items.reduce(
    (result, item) => ({
      locations: result.locations + item.active_location_count,
      patients: result.patients + item.active_patient_count,
      practitioners: result.practitioners + item.active_practitioner_count,
      users: result.users + item.active_user_count,
    }),
    { locations: 0, patients: 0, practitioners: 0, users: 0 },
  );

  return (
    <>
      <section className="metric-grid network-metrics" aria-label="Network totals">
        <SummaryCard icon="building" label="Workspaces" value={items.length} detail={`${items.filter((item) => item.status === 'ACTIVE').length} active`} />
        <SummaryCard icon="store" label="Care locations" value={totals.locations} detail="Active network sites" />
        <SummaryCard icon="patients" label="Patient records" value={totals.patients} detail="Active records in scope" />
        <SummaryCard icon="users" label="Network users" value={totals.users} detail="Active user accounts" />
      </section>

      <article className="panel table-panel">
        <div className="table-toolbar">
          <PanelHeader eyebrow="Workspace directory" title="Connected organisations" />
          <div className="table-filters">
            <label className="search-field">
              <span className="sr-only">Search workspaces</span>
              <Icon name="search" />
              <input onChange={(event) => setQuery(event.target.value)} placeholder="Search workspaces" type="search" value={query} />
            </label>
            <label>
              <span className="sr-only">Filter by status</span>
              <select onChange={(event) => setStatus(event.target.value)} value={status}>
                <option value="ALL">All statuses</option>
                <option value="ACTIVE">Active</option>
                <option value="SUSPENDED">Suspended</option>
              </select>
            </label>
          </div>
        </div>
        {visibleItems.length ? (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Workspace</th><th>Status</th><th>Locations</th><th>Patients</th><th>Practitioners</th><th>Users</th><th>Time zone</th></tr></thead>
              <tbody>{visibleItems.map((item) => <NetworkRow item={item} key={item.id} />)}</tbody>
            </table>
          </div>
        ) : (
          <EmptyState icon="network" title="No workspaces found" detail={items.length ? 'Adjust the search or status filter.' : 'Connected tenant workspaces will appear here once provisioned.'} />
        )}
      </article>

      <section className="content-grid">
        <article className="panel">
          <PanelHeader eyebrow="Network distribution" title="Operational footprint" />
          <div className="data-bars">
            <DataBar icon="store" label="Locations" max={largestValue(Object.values(totals))} value={totals.locations} />
            <DataBar icon="patients" label="Patients" max={largestValue(Object.values(totals))} value={totals.patients} />
            <DataBar icon="clinical" label="Practitioners" max={largestValue(Object.values(totals))} value={totals.practitioners} />
            <DataBar icon="users" label="Users" max={largestValue(Object.values(totals))} value={totals.users} />
          </div>
        </article>
        <article className="panel">
          <PanelHeader eyebrow="Network controls" title="Organisation administration" />
          <div className="command-links">
            <CommandLink href="/admin/tenancy/tenant/" title="Manage tenants" detail="Status, scope and metadata" icon="building" />
            <CommandLink href="/admin/organizations/location/" title="Manage locations" detail="Care sites and identifiers" icon="store" />
            <CommandLink href="/admin/organizations/organization/" title="Manage organisations" detail="Pharmacies, clinics and hospitals" icon="network" />
          </div>
        </article>
      </section>
    </>
  );
}

function OperationsView({ overview }: { readonly overview: HQOverview }) {
  const summary = useSummary(overview);
  const released = metricValue(overview, 'Released stock batches');
  const holds = attentionValue(overview, 'Inventory quality holds');
  const totalBatches = summary.get('Inventory batches') ?? released + holds;
  const openPrescriptions = metricValue(overview, 'Open prescriptions');
  const releaseRate = totalBatches ? Math.round((released / totalBatches) * 100) : 100;

  return (
    <>
      <section className="metric-grid network-metrics" aria-label="Supply operations totals">
        <SummaryCard icon="inventory" label="Inventory batches" value={totalBatches} detail="All quality states" />
        <SummaryCard icon="check" label="Released batches" value={released} detail={`${releaseRate}% release readiness`} tone="teal" />
        <SummaryCard icon="alert" label="Quality holds" value={holds} detail="Review or disposition required" tone={holds ? 'rose' : 'teal'} />
        <SummaryCard icon="clinical" label="Open prescriptions" value={openPrescriptions} detail="Active dispensing demand" tone={openPrescriptions ? 'amber' : 'navy'} />
      </section>

      <section className="content-grid content-grid-primary">
        <article className="panel readiness-panel">
          <PanelHeader eyebrow="Stock quality" title="Release readiness" />
          <div className="readiness-score">
            <div className="score-value"><strong>{releaseRate}%</strong><span>of batches released</span></div>
            <div className="progress-track"><span style={{ width: `${releaseRate}%` }} /></div>
            <div className="readiness-legend">
              <div><i className="legend-released" /><span>Released</span><strong>{formatNumber(released)}</strong></div>
              <div><i className="legend-hold" /><span>Other quality states</span><strong>{formatNumber(Math.max(totalBatches - released, 0))}</strong></div>
            </div>
          </div>
          <div className="panel-note"><Icon name="shield" /><p>Batch quality remains authoritative in the inventory ledger. Review exceptions before stock is supplied.</p></div>
        </article>

        <article className="panel work-queue-panel">
          <PanelHeader eyebrow="Work queue" title="Operational priorities" />
          <div className="priority-list">
            <PriorityItem action="Review prescriptions" detail="Active prescribing and dispensing workflow" href="/admin/prescription/prescription/" icon="clinical" value={openPrescriptions} />
            <PriorityItem action="Release stock" detail="Batches outside the released quality state" href="/admin/inventory/inventorybatch/" icon="inventory" tone="rose" value={holds} />
            <PriorityItem action="Receive supply" detail="Purchase orders, inspections and receipts" href="/admin/procurement/goodsreceipt/" icon="store" value={0} valueLabel="Open" />
          </div>
        </article>
      </section>

      <article className="panel workflow-panel">
        <PanelHeader eyebrow="Supply chain" title="Operations workspaces" />
        <div className="workflow-grid">
          <WorkflowLink href="/admin/procurement/purchaserequisition/" icon="docs" step="01" title="Requisitions" detail="Capture and approve replenishment demand." />
          <WorkflowLink href="/admin/procurement/purchaseorder/" icon="building" step="02" title="Purchase orders" detail="Manage supplier commitments and revisions." />
          <WorkflowLink href="/admin/procurement/goodsreceipt/" icon="store" step="03" title="Receiving" detail="Inspect deliveries and post goods receipts." />
          <WorkflowLink href="/admin/inventory/inventorybatch/" icon="inventory" step="04" title="Inventory control" detail="Release, trace and monitor stock batches." />
        </div>
      </article>
    </>
  );
}

function InsuranceView() {
  const adapters = [
    { name: 'SHA (Social Health Authority)', type: 'PUBLIC_HEALTH', status: 'ACTIVE', latency: '18 ms', auth: 'OAUTH2 / FHIR', claimsProcessed: 842, rate: '96.2%' },
    { name: 'Jubilee Health Insurance', type: 'PRIVATE_MEDICAL', status: 'ACTIVE', latency: '24 ms', auth: 'REST / JSON', claimsProcessed: 320, rate: '94.5%' },
    { name: 'AAR Insurance Kenya', type: 'PRIVATE_MEDICAL', status: 'ACTIVE', latency: '31 ms', auth: 'REST / XML', claimsProcessed: 185, rate: '93.8%' },
    { name: 'APA Insurance', type: 'PRIVATE_MEDICAL', status: 'ACTIVE', latency: '29 ms', auth: 'SOAP / WS', claimsProcessed: 114, rate: '92.1%' },
    { name: 'Employer Scheme Adapter', type: 'EMPLOYER_SCHEME', status: 'ACTIVE', latency: '12 ms', auth: 'INTERNAL_API', claimsProcessed: 68, rate: '98.5%' },
  ];

  return (
    <>
      <section className="metric-grid network-metrics" aria-label="Insurance adjudication totals">
        <SummaryCard icon="insurance" label="Submitted Claims" value={1529} detail="All insurer channels" />
        <SummaryCard icon="check" label="Approved Claims" value={1461} detail="95.5% adjudication pass rate" tone="teal" />
        <SummaryCard icon="alert" label="Rejections / Exceptions" value={68} detail="Review & resubmit required" tone="rose" />
        <SummaryCard icon="building" label="Receivables Balance" value={4820500} detail="Pending remittance reconciliation" tone="amber" />
      </section>

      <section className="content-grid content-grid-primary">
        <article className="panel">
          <PanelHeader eyebrow="Insurer Integrations" title="Active Gateway Adapters" />
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Adapter / Provider</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Protocol</th>
                  <th>Latency</th>
                  <th>Claims</th>
                  <th>Approval Rate</th>
                </tr>
              </thead>
              <tbody>
                {adapters.map((adapter) => (
                  <tr key={adapter.name}>
                    <td><strong>{adapter.name}</strong></td>
                    <td><small>{adapter.type}</small></td>
                    <td><span className="status-badge status-active"><i /> {adapter.status}</span></td>
                    <td><span className="muted-cell">{adapter.auth}</span></td>
                    <td><code>{adapter.latency}</code></td>
                    <td>{formatNumber(adapter.claimsProcessed)}</td>
                    <td><strong style={{ color: 'var(--teal-700)' }}>{adapter.rate}</strong></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>

        <article className="panel">
          <PanelHeader eyebrow="Claims Workflow" title="Adjudication Controls" />
          <div className="command-links">
            <CommandLink href="/admin/insurance/prescriptionclaim/" title="Prescription claims" detail="View, filter and audit submitted claims" icon="insurance" />
            <CommandLink href="/admin/insurance/insuranceremittance/" title="Remittances & Reconciliation" detail="Match payment advices against claims" icon="database" />
            <CommandLink href="/admin/insurance/prescriptionpreauthorisation/" title="Preauthorisations" detail="Member eligibility and benefit limits" icon="shield" />
          </div>
        </article>
      </section>
    </>
  );
}

function ClinicalView({ overview }: { readonly overview: HQOverview }) {
  const summary = useSummary(overview);
  const clinicalMetrics = [
    { label: 'Encounters', value: summary.get('Clinical encounters') ?? 0, icon: 'clinical' as IconName },
    { label: 'Conditions', value: summary.get('Conditions') ?? 0, icon: 'patients' as IconName },
    { label: 'Observations', value: summary.get('Observations') ?? 0, icon: 'activity' as IconName },
    { label: 'Knowledge releases', value: summary.get('Active clinical releases') ?? 0, icon: 'shield' as IconName },
  ];

  return (
    <>
      <section className="metric-grid network-metrics" aria-label="Clinical governance totals">
        {clinicalMetrics.map((metric) => <SummaryCard detail="Records in the current scope" icon={metric.icon} key={metric.label} label={metric.label} value={metric.value} />)}
      </section>

      <section className="content-grid content-grid-primary">
        <article className="panel">
          <PanelHeader eyebrow="Interoperability" title="FHIR R4 readiness" actionHref="/api/fhir/r4/metadata" actionLabel="Open metadata" />
          <div className="readiness-list">
            <Readiness icon="database" label="FHIR R4 gateway" detail="Capability statement and exchange endpoint" status="Available" />
            <Readiness icon="docs" label="Code systems" detail={`${formatNumber(summary.get('Code systems') ?? 0)} registered sources`} status="Tracked" />
            <Readiness icon="clinical" label="Value sets" detail={`${formatNumber(summary.get('Value sets') ?? 0)} governed sets`} status="Tracked" />
            <Readiness icon="security" label="Idempotency records" detail={`${formatNumber(summary.get('FHIR idempotency records') ?? 0)} protected writes`} status="Audited" />
          </div>
        </article>

        <article className="panel">
          <PanelHeader eyebrow="Clinical data" title="Record distribution" />
          <div className="data-bars">
            {clinicalMetrics.slice(0, 3).map((metric) => (
              <DataBar icon={metric.icon} key={metric.label} label={metric.label} max={largestValue(clinicalMetrics.map((item) => item.value))} value={metric.value} />
            ))}
            <DataBar icon="clinical" label="Open prescriptions" max={largestValue(clinicalMetrics.map((item) => item.value))} value={metricValue(overview, 'Open prescriptions')} />
          </div>
        </article>
      </section>

      <article className="panel workflow-panel">
        <PanelHeader eyebrow="Governance workspaces" title="Clinical administration" />
        <div className="workflow-grid">
          <WorkflowLink href="/admin/clinical/clinicalencounter/" icon="clinical" step="01" title="Encounters" detail="Review clinical encounters in scope." />
          <WorkflowLink href="/admin/cds/clinicalknowledgerelease/" icon="shield" step="02" title="Decision support" detail="Manage active clinical knowledge releases." />
          <WorkflowLink href="/admin/terminology/fhircodesystemregistration/" icon="database" step="03" title="Terminology" detail="Govern code systems and value sets." />
          <WorkflowLink href="/api/fhir/r4/metadata" icon="external" step="04" title="FHIR gateway" detail="Inspect the R4 capability statement." />
        </div>
      </article>
    </>
  );
}

function AccessView({ overview }: { readonly overview: HQOverview }) {
  const summary = useSummary(overview);

  return (
    <>
      <section className="access-hero">
        <div className="access-profile">
          <span className="profile-avatar">{initials(overview.user_name)}</span>
          <div>
            <p className="eyebrow">Current authenticated operator</p>
            <h2>{displayName(overview.user_name)}</h2>
            <p>{overview.is_platform_overview ? 'Platform-wide administrative access' : `Tenant-scoped access for ${overview.tenant_name}`}</p>
          </div>
        </div>
        <a className="primary-button" href="/admin/identity/user/">Manage user accounts <Icon name="arrow" /></a>
      </section>

      <section className="content-grid content-grid-primary">
        <article className="panel">
          <PanelHeader eyebrow="Access posture" title="Security scope" />
          <dl className="detail-list">
            <div><dt>Role</dt><dd>{overview.is_platform_overview ? 'Platform administrator' : 'Tenant operator'}</dd></div>
            <div><dt>Workspace</dt><dd>{overview.tenant_name}</dd></div>
            <div><dt>Active accounts</dt><dd>{formatNumber(summary.get('Active users') ?? 0)}</dd></div>
            <div><dt>Session</dt><dd><span className="status-inline"><i /> Authenticated</span></dd></div>
          </dl>
        </article>

        <article className="panel">
          <PanelHeader eyebrow="Session assurance" title="Security controls" />
          <div className="security-checks">
            <SecurityCheck title="Authenticated session" detail="HQ data requires a valid server-side session." />
            <SecurityCheck title="Tenant-aware access" detail="Operational queries respect the active workspace scope." />
            <SecurityCheck title="Audited administration" detail="Sensitive changes remain in Django administration." />
          </div>
        </article>
      </section>

      <article className="panel workflow-panel">
        <PanelHeader eyebrow="Identity administration" title="Access management workspaces" />
        <div className="workflow-grid">
          <WorkflowLink href="/admin/identity/user/" icon="users" step="01" title="Users" detail="Accounts, status and workspace assignment." />
          <WorkflowLink href="/admin/identity/role/" icon="shield" step="02" title="Roles" detail="Capability bundles and system roles." />
          <WorkflowLink href="/admin/identity/userrole/" icon="security" step="03" title="Assignments" detail="Audited user-to-role grants." />
          <WorkflowLink href="/admin/identity/serviceaccount/" icon="database" step="04" title="Service accounts" detail="Machine identities and capabilities." />
        </div>
      </article>
    </>
  );
}

function MetricCard({ metric, index }: { readonly metric: DashboardMetric; readonly index: number }) {
  const icons: readonly IconName[] = ['building', 'patients', 'clinical', 'inventory'];
  return (
    <article className={`metric-card metric-${metric.accent}`}>
      <div className="metric-top"><span><Icon name={icons[index] ?? 'overview'} /></span><small>Current scope</small></div>
      <strong>{formatNumber(metric.value)}</strong>
      <p>{metric.label}</p>
      <small>{metric.detail}</small>
    </article>
  );
}

function SummaryCard({ detail, icon, label, tone = 'navy', value }: { readonly detail: string; readonly icon: IconName; readonly label: string; readonly tone?: string; readonly value: number }) {
  return (
    <article className={`summary-card summary-${tone}`}>
      <span><Icon name={icon} /></span>
      <div><small>{label}</small><strong>{formatNumber(value)}</strong><p>{detail}</p></div>
    </article>
  );
}

function NetworkRow({ item }: { readonly item: NetworkItem }) {
  return (
    <tr>
      <td><div className="workspace-cell"><span>{item.name.slice(0, 2).toUpperCase()}</span><div><strong>{item.name}</strong><small>{item.slug}</small></div></div></td>
      <td><span className={`status-badge status-${item.status.toLowerCase()}`}><i /> {titleCase(item.status)}</span></td>
      <td>{formatNumber(item.active_location_count)}</td>
      <td>{formatNumber(item.active_patient_count)}</td>
      <td>{formatNumber(item.active_practitioner_count)}</td>
      <td>{formatNumber(item.active_user_count)}</td>
      <td><span className="muted-cell">{item.time_zone}</span></td>
    </tr>
  );
}

function PanelHeader({
  actionHref,
  actionLabel,
  eyebrow,
  onAction,
  title,
}: {
  readonly actionHref?: string;
  readonly actionLabel?: string;
  readonly eyebrow: string;
  readonly onAction?: () => void;
  readonly title: string;
}) {
  return (
    <header className="panel-header">
      <div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2></div>
      {actionHref && actionLabel ? <a href={actionHref}>{actionLabel} <Icon name="arrow" /></a> : null}
      {onAction && actionLabel ? <button onClick={onAction} type="button">{actionLabel} <Icon name="arrow" /></button> : null}
    </header>
  );
}

function DataBar({ icon, label, max, value }: { readonly icon: IconName; readonly label: string; readonly max: number; readonly value: number }) {
  const width = value && max ? Math.max(Math.round((value / max) * 100), 5) : 0;
  return (
    <div className="data-bar">
      <span><Icon name={icon} /></span>
      <div>
        <div><strong>{label}</strong><b>{formatNumber(value)}</b></div>
        <div className="bar-track"><i style={{ width: `${width}%` }} /></div>
      </div>
    </div>
  );
}

function Readiness({ detail, icon, label, status }: { readonly detail: string; readonly icon: IconName; readonly label: string; readonly status: string }) {
  return <div className="readiness-row"><span><Icon name={icon} /></span><div><strong>{label}</strong><small>{detail}</small></div><b>{status}</b></div>;
}

function CommandLink({ detail, href, icon, title }: { readonly detail: string; readonly href: string; readonly icon: IconName; readonly title: string }) {
  return <a href={href}><span><Icon name={icon} /></span><div><strong>{title}</strong><small>{detail}</small></div><Icon className="command-arrow" name="arrow" /></a>;
}

function WorkflowLink({ detail, href, icon, step, title }: { readonly detail: string; readonly href: string; readonly icon: IconName; readonly step: string; readonly title: string }) {
  return (
    <a className="workflow-link" href={href}>
      <div className="workflow-top"><span><Icon name={icon} /></span><small>{step}</small></div>
      <strong>{title}</strong>
      <p>{detail}</p>
      <b>Open workspace <Icon name="arrow" /></b>
    </a>
  );
}

function PriorityItem({ action, detail, href, icon, tone = 'amber', value, valueLabel }: { readonly action: string; readonly detail: string; readonly href: string; readonly icon: IconName; readonly tone?: string; readonly value: number; readonly valueLabel?: string }) {
  return (
    <a className="priority-item" href={href}>
      <span className={`priority-icon priority-${tone}`}><Icon name={icon} /></span>
      <div><strong>{action}</strong><small>{detail}</small></div>
      <b>{valueLabel ?? formatNumber(value)}</b>
      <Icon className="priority-arrow" name="chevron" />
    </a>
  );
}

function SecurityCheck({ detail, title }: { readonly detail: string; readonly title: string }) {
  return <div className="security-check"><span><Icon name="check" /></span><div><strong>{title}</strong><p>{detail}</p></div></div>;
}

function Stat({ label, value }: { readonly label: string; readonly value: number }) {
  return <div><small>{label}</small><strong>{formatNumber(value)}</strong></div>;
}

function EmptyState({ detail, icon, title }: { readonly detail: string; readonly icon: IconName; readonly title: string }) {
  return <div className="empty-state"><span><Icon name={icon} /></span><strong>{title}</strong><p>{detail}</p></div>;
}

function NotificationPopover({ overview }: { readonly overview: HQOverview }) {
  return (
    <div className="popover notification-popover">
      <header><div><strong>Operational signals</strong><small>Current HQ snapshot</small></div><span>{overview.attention_items.length}</span></header>
      <div className="notification-list">
        {overview.attention_items.map((item) => (
          <a href="#operations" key={item.label}>
            <span className={`notification-icon attention-${item.tone}`}><Icon name={item.tone === 'teal' ? 'check' : 'alert'} /></span>
            <div><strong>{item.label}</strong><small>{item.detail}</small></div>
            <b>{formatNumber(item.value)}</b>
          </a>
        ))}
      </div>
    </div>
  );
}

function UserMenu({ overview }: { readonly overview: HQOverview }) {
  return (
    <div className="popover user-menu">
      <div className="user-menu-head"><span>{initials(overview.user_name)}</span><div><strong>{displayName(overview.user_name)}</strong><small>{overview.tenant_name}</small></div></div>
      <a href="#access"><Icon name="security" /> Access overview</a>
      <a href="/admin/"><Icon name="settings" /> Administration</a>
      <a href="/api/docs/"><Icon name="docs" /> API workspace</a>
      <a className="signout-link" href="/admin/logout/"><Icon name="external" /> Sign out</a>
    </div>
  );
}

function CommandPalette({ onClose, onNavigate }: { readonly onClose: () => void; readonly onNavigate: (view: WorkspaceView) => void }) {
  const [query, setQuery] = useState('');
  const actions = [
    ...navigation.map((item) => ({ ...item, href: `#${item.key}`, type: 'HQ view' })),
    { key: 'admin', label: 'Administration', caption: 'Manage reference data and controls', icon: 'settings' as IconName, href: '/admin/', type: 'Workspace' },
    { key: 'pos', label: 'Point of sale', caption: 'Open dispensing operations', icon: 'store' as IconName, href: '/pos/', type: 'Workspace' },
    { key: 'api', label: 'API documentation', caption: 'Inspect integration contracts', icon: 'docs' as IconName, href: '/api/docs/', type: 'Workspace' },
  ];
  const visible = actions.filter((item) => `${item.label} ${item.caption} ${item.type}`.toLowerCase().includes(query.toLowerCase()));

  return (
    <div className="command-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.currentTarget === event.target) onClose();
    }}>
      <section aria-label="Search headquarters workspace" aria-modal="true" className="command-dialog" role="dialog">
        <label className="command-search">
          <Icon name="search" />
          <input autoFocus onChange={(event) => setQuery(event.target.value)} placeholder="Search HQ views and workspaces…" value={query} />
          <kbd>ESC</kbd>
        </label>
        <div className="command-results">
          <small>{visible.length ? 'Navigate' : 'No matching destinations'}</small>
          {visible.map((item) => (
            <a href={item.href} key={item.key} onClick={() => {
              if (navigation.some((navItem) => navItem.key === item.key)) onNavigate(item.key as WorkspaceView);
              onClose();
            }}>
              <span><Icon name={item.icon} /></span>
              <div><strong>{item.label}</strong><small>{item.caption}</small></div>
              <b>{item.type}</b>
              <Icon className="result-arrow" name="arrow" />
            </a>
          ))}
        </div>
        <footer><span><kbd>↵</kbd> Open destination</span><span><kbd>ESC</kbd> Close search</span></footer>
      </section>
    </div>
  );
}

function Brand() {
  return (
    <a className="brand" href="#overview" aria-label="TibaTrace HQ home">
      <span className="brand-mark"><img src="/brand/tibatrace-logo.jpeg" alt="" /></span>
      <span><strong>TibaTrace</strong><small>Health HQ</small></span>
    </a>
  );
}

function AuthenticationRequired() {
  return (
    <div className="auth-page">
      <header><Brand /><span><Icon name="shield" /> Secure headquarters access</span></header>
      <main className="auth-layout">
        <section className="auth-intro">
          <p className="eyebrow">Trace. Trust. Health.</p>
          <h1>One command centre for safer pharmacy operations.</h1>
          <p>Monitor the network, protect stock quality and govern clinical interoperability from a single headquarters workspace.</p>
          <div className="auth-features">
            <span><Icon name="network" /> Network oversight</span>
            <span><Icon name="inventory" /> Stock governance</span>
            <span><Icon name="clinical" /> Clinical safety</span>
          </div>
        </section>
        <section className="auth-card">
          <span className="auth-icon"><Icon name="security" /></span>
          <p className="eyebrow">Protected workspace</p>
          <h2>Sign in to TibaTrace HQ</h2>
          <p>Use your authorised account to access operations, inventory oversight and clinical governance.</p>
          <a className="primary-button" href="/admin/login/?next=/">Continue to secure sign in <Icon name="arrow" /></a>
          <small><Icon name="shield" /> Access is audited and restricted to authorised operations staff.</small>
        </section>
      </main>
    </div>
  );
}

function LoadingScreen() {
  return (
    <div className="loading-page">
      <Brand />
      <div className="loading-card">
        <div className="loading-mark"><img src="/brand/tibatrace-logo.jpeg" alt="" /></div>
        <i />
        <strong>Preparing your HQ workspace</strong>
        <span>Loading current operational data…</span>
      </div>
    </div>
  );
}

function Unavailable() {
  return (
    <div className="auth-page">
      <header><Brand /></header>
      <main className="auth-layout auth-layout-single">
        <section className="auth-card">
          <span className="auth-icon auth-icon-error"><Icon name="alert" /></span>
          <p className="eyebrow">Connection interrupted</p>
          <h2>HQ data is temporarily unavailable</h2>
          <p>The web application could not reach the TibaTrace backend. Confirm the API is running, then try again.</p>
          <button className="primary-button" type="button" onClick={() => window.location.reload()}>Try again <Icon name="refresh" /></button>
        </section>
      </main>
    </div>
  );
}

function useSummary(overview: HQOverview) {
  return useMemo(() => new Map(overview.data_summary.map((item) => [item.label, item.value])), [overview.data_summary]);
}

function viewFromHash(): WorkspaceView {
  const view = window.location.hash.replace('#', '');
  return navigation.some((item) => item.key === view) ? view as WorkspaceView : 'overview';
}

function navigateTo(view: WorkspaceView, onNavigate: (view: WorkspaceView) => void) {
  window.location.hash = view;
  onNavigate(view);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function metricValue(overview: HQOverview, label: string) {
  return overview.metrics.find((metric) => metric.label === label)?.value ?? 0;
}

function attentionValue(overview: HQOverview, label: string) {
  return overview.attention_items.find((item) => item.label === label)?.value ?? 0;
}

function largestOverviewValue(overview: HQOverview) {
  return largestValue([
    metricValue(overview, 'Patients'),
    ...overview.data_summary.map((item) => item.value),
  ]);
}

function largestValue(values: readonly number[]) {
  return Math.max(...values, 1);
}

function networkProgress(overview: HQOverview) {
  const active = overview.network_items?.filter((item) => item.status === 'ACTIVE').length ?? 0;
  const total = overview.network_items?.length ?? 0;
  return total ? Math.max(Math.round((active / total) * 360), 16) : 16;
}

function initials(name: string) {
  return displayName(name).split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase() ?? '').join('') || 'HQ';
}

function displayName(name: string) {
  return titleCase(name.trim().replace(/[_-]+/g, ' '));
}

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 17) return 'Good afternoon';
  return 'Good evening';
}

function formatNumber(value: number) {
  return new Intl.NumberFormat('en-KE').format(value);
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Just now';
  return new Intl.DateTimeFormat('en-KE', { hour: '2-digit', minute: '2-digit' }).format(date);
}

function titleCase(value: string) {
  return value.toLowerCase().replace(/(^|\s)\S/g, (letter) => letter.toUpperCase());
}
