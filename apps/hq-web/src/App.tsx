import { useCallback, useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';

import {
  CLAIM_STATES,
  HQApiError,
  formatMoney,
  loadApprovedUnpaidClaims,
  loadClaimsAwaitingDecision,
  loadClaimsNeedingAttention,
  loadCashVariances,
  loadForcedClosures,
  loadHQOverview,
  loadInsurers,
  loadOpenRegisterSessions,
  loadClaims,
  loadPriceBooks,
  readSession,
  SignInError,
  signIn,
  signOut,
  varianceNeedsExplanation,
} from './api.js';
import type {
  ClaimFilters,
  DashboardMetric,
  HQOverview,
  InsuranceClaim,
  Insurer,
  NetworkItem,
  PriceBookSummary,
  RegisterSessionSummary,
  SessionState,
  ShiftReportSummary,
} from './api.js';
import { Icon } from './icons.js';
import type { IconName } from './icons.js';

type WorkspaceView =
  | 'overview'
  | 'network'
  | 'operations'
  | 'pricing'
  | 'cash'
  | 'insurance'
  | 'clinical'
  | 'access';

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
  { key: 'pricing', label: 'Pricing', caption: 'Branch price books', icon: 'database' },
  { key: 'cash', label: 'Cash control', caption: 'Shifts, tills and variances', icon: 'building' },
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
  pricing: {
    eyebrow: 'Commercial control',
    title: 'Branch price books',
    description: 'Which price book each branch charges from, and whether it has a version a till can actually use.',
  },
  cash: {
    eyebrow: 'Till accountability',
    title: 'Shifts, tills and cash variances',
    description: 'Registers still trading, drawers that did not balance, and closures performed by somebody other than the accountable operator.',
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
  const [session, setSession] = useState<SessionState | null>(null);
  const [overview, setOverview] = useState<HQOverview | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshFailed, setRefreshFailed] = useState(false);

  // The session is read before anything else. It answers whether to render a
  // form or a workspace, and it carries the CSRF token the form needs to post
  // at all -- so fetching the overview first would just produce a 401 and a
  // sign-in page with no way to submit.
  useEffect(() => {
    const controller = new AbortController();
    void readSession(controller.signal)
      .then(setSession)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!session?.authenticated) return undefined;
    const controller = new AbortController();
    void loadHQOverview(controller.signal)
      .then(setOverview)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason);
      });
    return () => controller.abort();
  }, [session?.authenticated]);

  const endSession = useCallback(async () => {
    await signOut(session?.csrf_token ?? '');
    // Cleared rather than reloaded: the workspace data belongs to the person
    // who just left, and leaving it on screen while a new sign-in happens shows
    // one user another's claims.
    setOverview(null);
    setError(null);
    setSession(await readSession());
  }, [session?.csrf_token]);

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
    return (
      <AuthenticationRequired
        csrfToken={session?.csrf_token ?? ''}
        onSignedIn={setSession}
      />
    );
  }
  if (error) return <Unavailable />;
  if (!session) return <LoadingScreen />;
  if (!session.authenticated) {
    return <AuthenticationRequired csrfToken={session.csrf_token} onSignedIn={setSession} />;
  }
  if (!overview) return <LoadingScreen />;

  return (
    <Dashboard
      overview={overview}
      onSignOut={endSession}
      onRefresh={refresh}
      refreshFailed={refreshFailed}
      refreshing={refreshing}
    />
  );
}

function Dashboard({
  overview,
  onRefresh,
  onSignOut,
  refreshFailed,
  refreshing,
}: {
  readonly overview: HQOverview;
  readonly onRefresh: () => Promise<void>;
  readonly onSignOut: () => Promise<void>;
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
              {userMenuOpen ? <UserMenu overview={overview} onSignOut={onSignOut} /> : null}
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
          {activeView === 'pricing' ? <PricingView /> : null}
          {activeView === 'cash' ? <CashControlView /> : null}
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
  const openGRN = summary.get('Open goods receipts') ?? 0;

  const [sessions, setSessions] = useState<readonly RegisterSessionSummary[] | null>(null);
  const [priceBooks, setPriceBooks] = useState<readonly PriceBookSummary[] | null>(null);
  const [opsFailed, setOpsFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      loadOpenRegisterSessions(controller.signal),
      loadPriceBooks(controller.signal),
    ])
      .then(([s, p]) => { setSessions(s); setPriceBooks(p); })
      .catch(() => { if (!controller.signal.aborted) setOpsFailed(true); });
    return () => controller.abort();
  }, []);

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
            <PriorityItem action="Receive supply" detail="Purchase orders, inspections and receipts" href="/admin/procurement/goodsreceipt/" icon="store" value={openGRN} valueLabel={openGRN ? String(openGRN) : 'Open'} />
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

      {opsFailed ? null : (
        <section className="content-grid">
          <article className="panel">
            <PanelHeader eyebrow="Cash operations" title="Open register sessions" actionHref="/admin/pos_shift/shiftrecord/" actionLabel="View all sessions" />
            {sessions === null ? (
              <p className="muted-cell">Loading register sessions…</p>
            ) : sessions.length === 0 ? (
              <EmptyState icon="check" title="No open registers" detail="All registers are closed for the current business day." />
            ) : (
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Register</th><th>Cashier</th><th>Business date</th><th>Opened at</th><th>State</th></tr></thead>
                  <tbody>
                    {sessions.map((s) => (
                      <tr key={s.id}>
                        <td><code>{s.register_code}</code></td>
                        <td><small>{s.opened_by_username}</small></td>
                        <td><span className="muted-cell">{s.business_date}</span></td>
                        <td><small>{formatTime(s.opened_at)}</small></td>
                        <td>
                          <span className={`status-badge status-${s.state.toLowerCase()}`}><i /> {titleCase(s.state)}</span>
                          {s.forced_closure ? <span className="status-badge status-suspended" style={{ marginLeft: 6 }}><i /> Forced</span> : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </article>

          <article className="panel">
            <PanelHeader eyebrow="Pricing" title="Active price books" actionHref="/admin/pricing/pricebook/" actionLabel="Manage books" />
            {priceBooks === null ? (
              <p className="muted-cell">Loading price books…</p>
            ) : priceBooks.length === 0 ? (
              <EmptyState icon="inventory" title="No price books" detail="Configure price books before tenants can transact." />
            ) : (
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Code</th><th>Name</th><th>Currency</th><th>Type</th><th>Live version</th></tr></thead>
                  <tbody>
                    {priceBooks.map((book) => (
                      <tr key={book.id}>
                        <td><code>{book.code}</code></td>
                        <td><strong>{book.name}</strong></td>
                        <td><span className="muted-cell">{book.currency}</span></td>
                        <td><small>{titleCase(book.price_type)}</small></td>
                        <td>
                          {book.live_version !== null
                            ? <span className="status-badge status-active"><i /> v{book.live_version}</span>
                            : <span className="muted-cell">No live version</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </article>
        </section>
      )}
    </>
  );
}

function PricingView() {
  const [books, setBooks] = useState<readonly PriceBookSummary[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    loadPriceBooks(controller.signal)
      .then(setBooks)
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, []);

  if (failed) return <Unavailable />;
  if (!books) return <p className="muted-cell">Loading price books…</p>;

  // A book with no live version is configured but inert: nothing can charge
  // from it. Counted separately because it is the failure somebody discovers
  // at a till rather than on this screen.
  const inert = books.filter((book) => book.live_version === null);
  const branchScoped = books.filter((book) => book.scope_type === 'BRANCH');

  return (
    <>
      <section className="metric-grid network-metrics" aria-label="Price book totals">
        <SummaryCard icon="database" label="Price books" value={books.length} detail="All scopes" />
        <SummaryCard
          icon="building"
          label="Branch overrides"
          value={branchScoped.length}
          detail="Branches charging their own price"
          tone="teal"
        />
        <SummaryCard
          icon="alert"
          label="Without a live version"
          value={inert.length}
          detail="Configured, but nothing a till can charge"
          tone={inert.length ? 'rose' : 'navy'}
        />
      </section>

      <section className="content-grid content-grid-primary">
        <article className="panel">
          <PanelHeader eyebrow="Commercial control" title="Price books" />
          {books.length === 0 ? (
            <p className="muted-cell">No price books are configured for this tenant.</p>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Code</th>
                    <th>Scope</th>
                    <th>Type</th>
                    <th>Currency</th>
                    <th>Live version</th>
                  </tr>
                </thead>
                <tbody>
                  {books.map((book) => (
                    <tr key={book.id}>
                      <td><code>{book.code}</code></td>
                      <td><small>{book.scope_type}</small></td>
                      <td><span className="muted-cell">{book.price_type}</span></td>
                      <td>{book.currency}</td>
                      <td>
                        {book.live_version === null ? (
                          <span className="muted-cell">No live version</span>
                        ) : (
                          <strong>v{book.live_version}</strong>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>
      </section>
    </>
  );
}

function CashControlView() {
  const [open, setOpen] = useState<readonly RegisterSessionSummary[] | null>(null);
  const [variances, setVariances] = useState<readonly ShiftReportSummary[] | null>(null);
  const [forced, setForced] = useState<readonly ShiftReportSummary[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      loadOpenRegisterSessions(controller.signal),
      loadCashVariances(controller.signal),
      loadForcedClosures(controller.signal),
    ])
      .then(([a, b, c]) => {
        setOpen(a);
        setVariances(b);
        setForced(c);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, []);

  if (failed) return <Unavailable />;
  if (!open || !variances || !forced) {
    return <p className="muted-cell">Loading cash control data…</p>;
  }

  return (
    <>
      <section className="metric-grid network-metrics" aria-label="Cash control totals">
        <SummaryCard
          icon="building"
          label="Tills still trading"
          value={open.length}
          detail="Open register sessions"
          tone={open.length ? 'amber' : 'navy'}
        />
        <SummaryCard
          icon="alert"
          label="Drawers that did not balance"
          value={variances.length}
          detail="Z reports carrying a variance"
          tone={variances.length ? 'rose' : 'navy'}
        />
        <SummaryCard
          icon="shield"
          label="Forced closures"
          value={forced.length}
          detail="Closed by somebody other than the operator"
          tone={forced.length ? 'amber' : 'navy'}
        />
      </section>

      <section className="content-grid content-grid-primary">
        <article className="panel">
          <PanelHeader eyebrow="Till accountability" title="Cash variances" />
          {variances.length === 0 ? (
            <p className="muted-cell">Every closed drawer balanced.</p>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Report</th>
                    <th>Register</th>
                    <th>Business date</th>
                    <th>Expected</th>
                    <th>Counted</th>
                    <th>Difference</th>
                  </tr>
                </thead>
                <tbody>
                  {variances.map((report) => {
                    /* Read from the report's own frozen snapshot, never
                       recomputed. The snapshot is what was counted and signed,
                       and a screen that recalculates can disagree with the
                       paper the operator is holding. */
                    const variance = report.snapshot?.variance;
                    return (
                      <tr key={report.id}>
                        <td><code>{report.report_number}</code></td>
                        <td>{report.register_code}</td>
                        <td><span className="muted-cell">{report.business_date}</span></td>
                        <td>{formatMoney(variance?.expected)}</td>
                        <td>{formatMoney(variance?.declared)}</td>
                        <td>
                          <strong style={{ color: 'var(--rose-600, #b3261e)' }}>
                            {formatMoney(variance?.difference)}
                          </strong>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </article>

        <article className="panel">
          <PanelHeader eyebrow="Exception review" title="Forced closures" />
          {forced.length === 0 ? (
            <p className="muted-cell">No forced closures to review.</p>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Report</th>
                    <th>Register</th>
                    <th>Closed by</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {forced.map((report) => (
                    <tr key={report.id}>
                      <td><code>{report.report_number}</code></td>
                      <td>{report.register_code}</td>
                      <td>{report.generated_by_username}</td>
                      {/* Each of these is a drawer counted by somebody who was
                          not accountable for it, so the reason is shown rather
                          than hidden behind a detail view. */}
                      <td><span className="muted-cell">{report.closure_reason || '—'}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>
      </section>
    </>
  );
}

function ClaimsRegister() {
  const [filters, setFilters] = useState<ClaimFilters>({});
  const [claims, setClaims] = useState<readonly InsuranceClaim[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setFailed(false);
    // Filters go to the server. Filtering a fetched page in the browser reports
    // "3 rejected" when the register holds four hundred, and the number looks
    // authoritative because it was counted rather than guessed.
    loadClaims(filters, controller.signal)
      .then(setClaims)
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [filters]);

  const setFilter = useCallback((key: keyof ClaimFilters, value: string) => {
    setFilters((current) => {
      const next = { ...current };
      if (value) next[key] = value;
      else delete next[key];
      return next;
    });
  }, []);

  const active = Object.keys(filters).length;

  return (
    <article className="panel">
      {/* Spread conditionally: exactOptionalPropertyTypes distinguishes an
          absent optional prop from one explicitly set to undefined, and
          PanelHeader accepts the former. */}
      <PanelHeader
        eyebrow="Claims operations"
        title="Claims register"
        {...(active ? { actionLabel: 'Clear filters', onAction: () => setFilters({}) } : {})}
      />

      <div className="filter-row">
        <label>
          Submission
          <select
            value={filters.submission_state ?? ''}
            onChange={(event) => setFilter('submission_state', event.target.value)}
          >
            <option value="">Any</option>
            {CLAIM_STATES.submission.map((state) => (
              <option key={state} value={state}>{titleCase(state)}</option>
            ))}
          </select>
        </label>

        <label>
          Adjudication
          <select
            value={filters.adjudication_state ?? ''}
            onChange={(event) => setFilter('adjudication_state', event.target.value)}
          >
            <option value="">Any</option>
            {CLAIM_STATES.adjudication.map((state) => (
              <option key={state} value={state}>{titleCase(state)}</option>
            ))}
          </select>
        </label>

        <label>
          Payment
          <select
            value={filters.payment_state ?? ''}
            onChange={(event) => setFilter('payment_state', event.target.value)}
          >
            <option value="">Any</option>
            {CLAIM_STATES.payment.map((state) => (
              <option key={state} value={state}>{titleCase(state)}</option>
            ))}
          </select>
        </label>
      </div>

      {failed ? (
        /* Distinct from an empty register. "No claims match" and "the query
           failed" look identical if both render as an empty table, and the
           first is believed. */
        <p className="auth-error" role="alert">
          <Icon name="alert" /> The claims register could not be loaded.
        </p>
      ) : !claims ? (
        <p className="muted-cell">Loading claims…</p>
      ) : claims.length === 0 ? (
        <EmptyState
          icon="insurance"
          title={active ? 'No claims match these filters' : 'No claims yet'}
          detail={active ? 'Clear the filters to see the whole register.' : 'Claims appear here once prescriptions are dispensed against insurance.'}
        />
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Claim</th>
                <th>Insurer</th>
                <th>Member</th>
                <th>Claimed</th>
                <th>Approved</th>
                <th>Outstanding</th>
                <th>Submission</th>
                <th>Adjudication</th>
                <th>Payment</th>
              </tr>
            </thead>
            <tbody>
              {claims.map((claim) => (
                <tr key={claim.id}>
                  <td><code>{claim.claim_number}</code></td>
                  <td><small>{claim.insurer_code}</small></td>
                  <td><span className="muted-cell">{claim.membership_number}</span></td>
                  <td>{formatMoney(claim.claimed_gross_amount, claim.currency)}</td>
                  {/* Claimed and approved side by side. The gap between them is
                      the contractual adjustment somebody has to account for,
                      and showing only one hides it. */}
                  <td>{formatMoney(claim.approved_amount, claim.currency)}</td>
                  <td><strong>{formatMoney(claim.outstanding_amount, claim.currency)}</strong></td>
                  <td><small>{titleCase(claim.submission_state)}</small></td>
                  <td><small>{titleCase(claim.adjudication_state)}</small></td>
                  <td><small>{titleCase(claim.payment_state)}</small></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </article>
  );
}

function InsuranceView() {
  const [insurers, setInsurers] = useState<readonly Insurer[] | null>(null);
  const [unpaid, setUnpaid] = useState<readonly InsuranceClaim[] | null>(null);
  const [awaiting, setAwaiting] = useState<readonly InsuranceClaim[] | null>(null);
  const [attention, setAttention] = useState<readonly InsuranceClaim[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      loadInsurers(controller.signal),
      loadApprovedUnpaidClaims(controller.signal),
      loadClaimsAwaitingDecision(controller.signal),
      loadClaimsNeedingAttention(controller.signal),
    ])
      .then(([a, b, c, d]) => {
        setInsurers(a);
        setUnpaid(b);
        setAwaiting(c);
        setAttention(d);
      })
      .catch(() => {
        // Surfaced, not swallowed into zeroes. A dashboard showing "0 claims"
        // because the request failed is believed; one saying it could not load
        // is questioned.
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, []);

  if (failed) return <Unavailable />;
  if (!insurers || !unpaid || !awaiting || !attention) {
    return <p className="muted-cell">Loading insurance data…</p>;
  }

  // Summed from the rows themselves rather than from a separate total, so the
  // headline and the table below it cannot disagree.
  const receivable = unpaid.reduce(
    (total, claim) => total + Number.parseFloat(claim.outstanding_amount || '0'),
    0,
  );

  return (
    <>
      <section className="metric-grid network-metrics" aria-label="Insurance claim positions">
        <SummaryCard icon="insurance" label="Awaiting insurer decision" value={awaiting.length} detail="Sent and acknowledged, not yet adjudicated" />
        <SummaryCard icon="check" label="Approved, unpaid" value={unpaid.length} detail="Insurer agreed to pay and has not paid" tone="teal" />
        <SummaryCard icon="alert" label="Needs attention here" value={attention.length} detail="Rejected, or blocked on this end" tone="rose" />
        <SummaryCard icon="building" label="Receivable" value={Math.round(receivable)} detail="Approved less received, this tenant" tone="amber" />
      </section>

      <section className="content-grid content-grid-primary">
        <article className="panel">
          <PanelHeader eyebrow="Insurer integrations" title="Configured insurers" actionHref="/admin/insurance/insurer/" actionLabel="Manage in admin" />
          {insurers.length === 0 ? (
            <EmptyState icon="insurance" title="No insurers configured" detail="Add an insurer integration before submitting claims." />
          ) : (
            <div className="table-scroll">
              <table>
                <thead><tr><th>Insurer</th><th>Adapter</th><th>Environment</th><th>Status</th><th>Can transact</th></tr></thead>
                <tbody>
                  {insurers.map((insurer) => (
                    <tr key={insurer.id}>
                      <td><strong>{insurer.name}</strong></td>
                      <td><small>{insurer.integration_adapter}</small></td>
                      <td><span className="muted-cell">{insurer.environment}</span></td>
                      <td><small>{insurer.status}</small></td>
                      <td>
                        {insurer.adapter_registered
                          ? <span className="status-badge status-active"><i /> Adapter ready</span>
                          : <span className="muted-cell">No adapter implemented</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>

        <article className="panel">
          <PanelHeader eyebrow="Claims workflow" title="Approved and unpaid" />
          {unpaid.length === 0 ? (
            <EmptyState icon="check" title="No outstanding approved claims" detail="All approved claims have been paid or are not yet due." />
          ) : (
            <div className="table-scroll">
              <table>
                <thead><tr><th>Claim</th><th>Insurer</th><th>Member</th><th>Approved</th><th>Received</th><th>Outstanding</th></tr></thead>
                <tbody>
                  {unpaid.map((claim) => (
                    <tr key={claim.id}>
                      <td><code>{claim.claim_number}</code></td>
                      <td><small>{claim.insurer_code}</small></td>
                      <td><span className="muted-cell">{claim.membership_number}</span></td>
                      <td>{formatMoney(claim.approved_amount, claim.currency)}</td>
                      <td>{formatMoney(claim.paid_amount, claim.currency)}</td>
                      <td><strong>{formatMoney(claim.outstanding_amount, claim.currency)}</strong></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>
      </section>

      <section className="content-grid content-grid-primary">
        <article className="panel">
          <PanelHeader eyebrow="Pending adjudication" title="Claims awaiting insurer decision" />
          {awaiting.length === 0 ? (
            <EmptyState icon="insurance" title="No claims pending adjudication" detail="All submitted claims have been adjudicated." />
          ) : (
            <div className="table-scroll">
              <table>
                <thead><tr><th>Claim</th><th>Insurer</th><th>Member</th><th>Claimed</th><th>Submission</th><th>Adjudication</th></tr></thead>
                <tbody>
                  {awaiting.map((claim) => (
                    <tr key={claim.id}>
                      <td><code>{claim.claim_number}</code></td>
                      <td><small>{claim.insurer_code}</small></td>
                      <td><span className="muted-cell">{claim.membership_number}</span></td>
                      <td>{formatMoney(claim.claimed_gross_amount, claim.currency)}</td>
                      <td><span className="status-badge status-suspended"><i /> {titleCase(claim.submission_state)}</span></td>
                      <td><span className="muted-cell">{titleCase(claim.adjudication_state)}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>

        <article className="panel">
          <PanelHeader eyebrow="Action required" title="Claims needing attention" />
          {attention.length === 0 ? (
            <EmptyState icon="check" title="No claims need attention" detail="No claims are blocked or rejected on this end." />
          ) : (
            <div className="table-scroll">
              <table>
                <thead><tr><th>Claim</th><th>Insurer</th><th>Member</th><th>Outstanding</th><th>Submission</th><th>Adjudication</th></tr></thead>
                <tbody>
                  {attention.map((claim) => (
                    <tr key={claim.id}>
                      <td><code>{claim.claim_number}</code></td>
                      <td><small>{claim.insurer_code}</small></td>
                      <td><span className="muted-cell">{claim.membership_number}</span></td>
                      <td><strong className="text-rose">{formatMoney(claim.outstanding_amount, claim.currency)}</strong></td>
                      <td><span className="status-badge status-suspended"><i /> {titleCase(claim.submission_state)}</span></td>
                      <td><span className="status-badge status-suspended"><i /> {titleCase(claim.adjudication_state)}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>
      </section>

      <ClaimsRegister />
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

  const codeSystems = summary.get('Code systems') ?? 0;
  const valueSets = summary.get('Value sets') ?? 0;
  const fhirIdempotency = summary.get('FHIR idempotency records') ?? 0;

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
            <Readiness
              icon="docs"
              label="Code systems"
              detail={codeSystems > 0 ? `${formatNumber(codeSystems)} registered sources` : 'No code systems registered'}
              status={codeSystems > 0 ? 'Tracked' : 'None registered'}
            />
            <Readiness
              icon="clinical"
              label="Value sets"
              detail={valueSets > 0 ? `${formatNumber(valueSets)} governed sets` : 'No value sets configured'}
              status={valueSets > 0 ? 'Tracked' : 'None configured'}
            />
            <Readiness
              icon="security"
              label="Idempotency records"
              detail={fhirIdempotency > 0 ? `${formatNumber(fhirIdempotency)} protected writes` : 'No idempotency records yet'}
              status={fhirIdempotency > 0 ? 'Audited' : 'No records'}
            />
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

      <section className="content-grid">
        <article className="panel">
          <PanelHeader eyebrow="Prescription governance" title="Active dispensing" />
          <div className="priority-list">
            <PriorityItem action="Open prescriptions" detail="Active prescribing and dispensing workflow" href="/admin/prescription/prescription/" icon="clinical" value={metricValue(overview, 'Open prescriptions')} tone={metricValue(overview, 'Open prescriptions') ? 'amber' : 'teal'} />
            <PriorityItem action="Clinical substitutions" detail="Pharmacist-initiated therapeutic substitutions" href="/admin/prescription/clinicalsubstitution/" icon="activity" value={0} valueLabel="View" />
            <PriorityItem action="Dispensing labels" detail="Audit label generation and reprints" href="/admin/prescription/dispensinglabel/" icon="docs" value={0} valueLabel="Audit" />
          </div>
        </article>
        <article className="panel">
          <PanelHeader eyebrow="Formulary" title="Medicines & pricing" />
          <div className="command-links">
            <CommandLink href="/admin/medicines/commercialsku/" title="Commercial SKUs" detail="Packaged medicines and identifiers" icon="inventory" />
            <CommandLink href="/admin/medicines/activesubstance/" title="Active substances" detail="Governed substance register" icon="clinical" />
            <CommandLink href="/admin/pricing/pricebook/" title="Price books" detail="Formulary pricing and live versions" icon="building" />
          </div>
        </article>
      </section>
    </>
  );
}

function AccessView({ overview }: { readonly overview: HQOverview }) {
  const summary = useSummary(overview);
  const [sessions, setSessions] = useState<readonly RegisterSessionSummary[] | null>(null);
  const [variances, setVariances] = useState<readonly ShiftReportSummary[] | null>(null);
  const [forcedClosures, setForcedClosures] = useState<readonly ShiftReportSummary[] | null>(null);
  const [cashFailed, setCashFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      loadOpenRegisterSessions(controller.signal),
      loadCashVariances(controller.signal),
      loadForcedClosures(controller.signal),
    ])
      .then(([s, v, f]) => { setSessions(s); setVariances(v); setForcedClosures(f); })
      .catch(() => { if (!controller.signal.aborted) setCashFailed(true); });
    return () => controller.abort();
  }, []);

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

      {cashFailed ? (
        <div className="inline-alert" role="status">
          <Icon name="alert" />
          Cash and shift data could not be loaded. Financial custody data requires the POS shift API to be reachable.
        </div>
      ) : (
        <>
          <section className="content-grid content-grid-primary">
            <article className="panel">
              <PanelHeader eyebrow="Cash control" title="Open register sessions" actionHref="/admin/pos_shift/shiftrecord/" actionLabel="View all" />
              {sessions === null ? (
                <p className="muted-cell">Loading register sessions…</p>
              ) : sessions.length === 0 ? (
                <EmptyState icon="check" title="No open registers" detail="All registers are closed. No open custody positions." />
              ) : (
                <div className="table-scroll">
                  <table>
                    <thead><tr><th>Register</th><th>Cashier</th><th>Business date</th><th>Opened at</th><th>State</th></tr></thead>
                    <tbody>
                      {sessions.map((s) => (
                        <tr key={s.id}>
                          <td><code>{s.register_code}</code></td>
                          <td><small>{s.opened_by_username}</small></td>
                          <td><span className="muted-cell">{s.business_date}</span></td>
                          <td><small>{formatTime(s.opened_at)}</small></td>
                          <td>
                            <span className={`status-badge status-${s.state.toLowerCase()}`}><i /> {titleCase(s.state)}</span>
                            {s.forced_closure ? <span className="status-badge status-suspended" style={{ marginLeft: 6 }}><i /> Forced</span> : null}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </article>

            <article className="panel">
              <PanelHeader eyebrow="Financial audit" title="Cash variance watchlist" actionHref="/admin/pos_shift/shiftreport/?has_variance=1" actionLabel="View all" />
              {variances === null ? (
                <p className="muted-cell">Loading variance reports…</p>
              ) : variances.length === 0 ? (
                <EmptyState icon="check" title="No cash variances" detail="All Z-reports balanced. No unexplained differences." />
              ) : (
                <div className="table-scroll">
                  <table>
                    <thead><tr><th>Report</th><th>Register</th><th>Date</th><th>Expected</th><th>Declared</th><th>Difference</th><th>Flag</th></tr></thead>
                    <tbody>
                      {variances.map((r) => (
                        <tr key={r.id}>
                          <td><code>{r.report_number}</code></td>
                          <td><small>{r.register_code}</small></td>
                          <td><span className="muted-cell">{r.business_date}</span></td>
                          <td>{formatMoney(r.snapshot?.cash?.expected_closing, 'KES')}</td>
                          <td>{formatMoney(r.snapshot?.variance?.declared, 'KES')}</td>
                          <td><strong className="text-rose">{formatMoney(r.snapshot?.variance?.difference, 'KES')}</strong></td>
                          <td>{varianceNeedsExplanation(r) ? <span className="status-badge status-suspended"><i /> Explanation required</span> : <span className="muted-cell">—</span>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </article>
          </section>

          <article className="panel">
            <PanelHeader eyebrow="Custody audit" title="Forced register closures" actionHref="/admin/pos_shift/shiftreport/?forced_closure=1" actionLabel="View all" />
            {forcedClosures === null ? (
              <p className="muted-cell">Loading forced closures…</p>
            ) : forcedClosures.length === 0 ? (
              <EmptyState icon="check" title="No forced closures" detail="No registers have been closed by an unaccountable operator." />
            ) : (
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Report</th><th>Register</th><th>Date</th><th>Closed by</th><th>Closure type</th><th>Reason</th></tr></thead>
                  <tbody>
                    {forcedClosures.map((r) => (
                      <tr key={r.id}>
                        <td><code>{r.report_number}</code></td>
                        <td><small>{r.register_code}</small></td>
                        <td><span className="muted-cell">{r.business_date}</span></td>
                        <td><small>{r.generated_by_username}</small></td>
                        <td><span className="status-badge status-suspended"><i /> {titleCase(r.closure_type)}</span></td>
                        <td><small className="muted-cell">{r.closure_reason || '—'}</small></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </article>
        </>
      )}
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

function UserMenu({ overview, onSignOut }: {
  readonly overview: HQOverview;
  readonly onSignOut: () => Promise<void>;
}) {
  return (
    <div className="popover user-menu">
      <div className="user-menu-head"><span>{initials(overview.user_name)}</span><div><strong>{displayName(overview.user_name)}</strong><small>{overview.tenant_name}</small></div></div>
      <a href="#access"><Icon name="security" /> Access overview</a>
      <a href="/admin/"><Icon name="settings" /> Administration</a>
      <a href="/api/docs/"><Icon name="docs" /> API workspace</a>
      <button className="signout-link" type="button" onClick={onSignOut}>
        <Icon name="external" /> Sign out
      </button>
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

function AuthenticationRequired({ csrfToken, onSignedIn }: {
  readonly csrfToken: string;
  readonly onSignedIn: (session: SessionState) => void;
}) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      // Guarded rather than merely disabled: a second submit while the first is
      // in flight spends another attempt against a throttle of ten a minute.
      if (busy) return;

      setBusy(true);
      setError('');
      try {
        const session = await signIn(username, password, csrfToken);
        // Cleared on the way out. There is no reason for it to outlive the
        // request, and React state ends up in devtools and error reports.
        setPassword('');
        onSignedIn(session);
      } catch (caught: unknown) {
        // The server's wording. It deliberately does not say which field was
        // wrong, and guessing here would undo that.
        setError(caught instanceof SignInError ? caught.message : 'Sign-in failed.');
        setPassword('');
      } finally {
        setBusy(false);
      }
    },
    [busy, csrfToken, onSignedIn, password, username],
  );

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

          <form className="auth-form" onSubmit={submit}>
            <label htmlFor="signin-username">Username</label>
            <input
              id="signin-username"
              name="username"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              disabled={busy}
              required
            />

            <label htmlFor="signin-password">Password</label>
            <input
              id="signin-password"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={busy}
              required
            />

            {error ? (
              // Assertive: the operator has just acted and is waiting on the
              // result, so a polite region would leave a screen-reader user
              // unaware the attempt failed.
              <p className="auth-error" role="alert" aria-live="assertive">
                <Icon name="alert" /> {error}
              </p>
            ) : null}

            <button className="primary-button" type="submit" disabled={busy}>
              {busy ? 'Signing in…' : 'Sign in'} <Icon name="arrow" />
            </button>
          </form>

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
