import { useCallback, useEffect, useMemo, useState } from 'react';
import type { CSSProperties, FormEvent } from 'react';

import {
  CLAIM_STATES,
  HQApiError,
  executeHQBusinessAction,
  formatMoney,
  loadActiveSubstances,
  loadApprovedUnpaidClaims,
  loadClaimsAwaitingDecision,
  loadClaimsNeedingAttention,
  loadCashVariances,
  loadForcedClosures,
  loadGovernmentCatalogue,
  loadHQOverview,
  loadHQWorkspace,
  loadInsurers,
  loadOpenRegisterSessions,
  loadClaims,
  loadClinicalProducts,
  loadManufacturedProducts,
  loadManufacturers,
  loadPriceBooks,
  readSession,
  SignInError,
  signIn,
  signOut,
  updateGovernmentCatalogueSelection,
  varianceNeedsExplanation,
} from './api.js';
import type {
  ActiveSubstanceSummary,
  ClaimFilters,
  ClinicalProductSummary,
  DashboardMetric,
  GovernmentCataloguePage,
  HQBusinessAction,
  HQOverview,
  HQWorkItem,
  HQWorkspaceData,
  InsuranceClaim,
  Insurer,
  ManufacturedProductSummary,
  ManufacturerSummary,
  PriceBookSummary,
  RegisterSessionSummary,
  SessionState,
  ShiftReportSummary,
} from './api.js';
import { Icon } from './icons.js';
import type { IconName } from './icons.js';
import { ProcurementWorkspace } from './ProcurementWorkspace.js';
import { TenantManagement } from './TenantManagement.js';

type WorkspaceView =
  | 'overview'
  | 'network'
  | 'people'
  | 'catalogue'
  | 'operations'
  | 'commerce'
  | 'pricing'
  | 'cash'
  | 'insurance'
  | 'clinical'
  | 'governance'
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
  { key: 'people', label: 'People & customers', caption: 'Care and commercial records', icon: 'patients' },
  { key: 'catalogue', label: 'Medicine catalogue', caption: 'SKUs and product governance', icon: 'clinical' },
  { key: 'operations', label: 'Inventory & procurement', caption: 'Stock and supply', icon: 'inventory' },
  { key: 'commerce', label: 'Sales & fulfilment', caption: 'Orders through delivery', icon: 'store' },
  { key: 'pricing', label: 'Pricing', caption: 'Branch price books', icon: 'database' },
  { key: 'cash', label: 'Cash control', caption: 'Shifts, tills and variances', icon: 'building' },
  { key: 'insurance', label: 'Insurance & Claims', caption: 'Adjudication & SHA', icon: 'insurance' },
  { key: 'clinical', label: 'Clinical governance', caption: 'Safety and standards', icon: 'clinical' },
  { key: 'governance', label: 'System governance', caption: 'Audit, events and documents', icon: 'shield' },
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
  people: {
    eyebrow: 'People operations',
    title: 'People & customers',
    description: 'Review patient records, verified practitioners and commercial customers without exposing sensitive clinical details.',
  },
  catalogue: {
    eyebrow: 'Product governance',
    title: 'Medicine catalogue',
    description: 'Inspect commercial SKUs, governed substances and manufacturer coverage used throughout stock, pricing and dispensing.',
  },
  operations: {
    eyebrow: 'Supply operations',
    title: 'Inventory & procurement',
    description: 'Track stock readiness, quality holds and active dispensing demand before it affects patient care.',
  },
  commerce: {
    eyebrow: 'Order operations',
    title: 'Sales & fulfilment',
    description: 'Follow customer demand from quotation and order through dispatch, delivery and return.',
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
  governance: {
    eyebrow: 'Platform assurance',
    title: 'System governance',
    description: 'Monitor immutable audit records, clinical documents, domain events, notifications and legacy identifier migration.',
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
      csrfToken={session.csrf_token}
      overview={overview}
      onSignOut={endSession}
      onRefresh={refresh}
      refreshFailed={refreshFailed}
      refreshing={refreshing}
    />
  );
}

function Dashboard({
  csrfToken,
  overview,
  onRefresh,
  onSignOut,
  refreshFailed,
  refreshing,
}: {
  readonly csrfToken: string;
  readonly overview: HQOverview;
  readonly onRefresh: () => Promise<void>;
  readonly onSignOut: () => Promise<void>;
  readonly refreshFailed: boolean;
  readonly refreshing: boolean;
}) {
  const [activeView, setActiveView] = useState<WorkspaceView>(() => viewFromHash());
  const [workspaceData, setWorkspaceData] = useState<HQWorkspaceData | null>(null);
  const [workspaceFailed, setWorkspaceFailed] = useState(false);
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

  const reloadWorkspace = useCallback(async (signal?: AbortSignal) => {
    setWorkspaceFailed(false);
    try {
      setWorkspaceData(await loadHQWorkspace(signal));
    } catch {
      if (!signal?.aborted) setWorkspaceFailed(true);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void reloadWorkspace(controller.signal);
    return () => controller.abort();
  }, [overview.generated_at, reloadWorkspace]);

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
          {activeView === 'network' ? <NetworkView csrfToken={csrfToken} onChanged={onRefresh} overview={overview} /> : null}
          {activeView === 'people' ? <PeopleView csrfToken={csrfToken} data={workspaceData} failed={workspaceFailed} onWorkspaceChanged={reloadWorkspace} /> : null}
          {activeView === 'catalogue' ? <CatalogueView csrfToken={csrfToken} data={workspaceData} failed={workspaceFailed} onWorkspaceChanged={reloadWorkspace} overview={overview} /> : null}
          {activeView === 'operations' ? <OperationsView csrfToken={csrfToken} data={workspaceData} failed={workspaceFailed} onWorkspaceChanged={reloadWorkspace} overview={overview} /> : null}
          {activeView === 'commerce' ? <CommerceView csrfToken={csrfToken} data={workspaceData} failed={workspaceFailed} onWorkspaceChanged={reloadWorkspace} /> : null}
          {activeView === 'pricing' ? <PricingView /> : null}
          {activeView === 'cash' ? <CashControlView /> : null}
          {activeView === 'insurance' ? <InsuranceView /> : null}
          {activeView === 'clinical' ? <ClinicalView csrfToken={csrfToken} data={workspaceData} failed={workspaceFailed} onWorkspaceChanged={reloadWorkspace} overview={overview} /> : null}
          {activeView === 'governance' ? <GovernanceView data={workspaceData} failed={workspaceFailed} /> : null}
          {activeView === 'access' ? <AccessView csrfToken={csrfToken} data={workspaceData} failed={workspaceFailed} onWorkspaceChanged={reloadWorkspace} overview={overview} /> : null}
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
            <CommandLink href="#access" title="System controls" detail="Identity, security and governance" icon="settings" />
            <CommandLink href="/api/docs/" title="API workspace" detail="Integration contracts and testing" icon="docs" />
          </div>
        </article>
      </section>
    </>
  );
}

function NetworkView({
  csrfToken,
  onChanged,
  overview,
}: {
  readonly csrfToken: string;
  readonly onChanged: () => Promise<void>;
  readonly overview: HQOverview;
}) {
  return <TenantManagement csrfToken={csrfToken} onChanged={onChanged} overview={overview} />;
}

interface BusinessViewProps {
  readonly csrfToken: string;
  readonly data: HQWorkspaceData | null;
  readonly failed: boolean;
  readonly onWorkspaceChanged: () => Promise<void>;
}

function OperationsView({
  csrfToken,
  overview,
}: BusinessViewProps & { readonly overview: HQOverview }) {
  return <ProcurementWorkspace csrfToken={csrfToken} overview={overview} />;
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
          <PanelHeader eyebrow="Insurer integrations" title="Configured insurers" actionHref="#insurance" actionLabel="Open insurance workspace" />
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

function PeopleView({
  csrfToken,
  data,
  failed,
  onWorkspaceChanged,
}: BusinessViewProps) {
  if (failed) return <WorkspaceSectionError domain="people and customer" />;
  if (!data) return <WorkspaceSectionLoading domain="people and customer" />;

  const { counts, customers, patients, practitioners } = data.people;
  return (
    <>
      <section className="metric-grid network-metrics" aria-label="People and customer totals">
        <SummaryCard icon="patients" label="Patient records" value={counts.patients} detail={`${formatNumber(counts.active_patients)} active`} />
        <SummaryCard icon="clinical" label="Practitioners" value={counts.practitioners} detail={`${formatNumber(counts.verified_practitioners)} verified`} tone="teal" />
        <SummaryCard icon="building" label="Customers" value={counts.customers} detail={`${formatNumber(counts.active_customers)} active`} />
        <SummaryCard icon="shield" label="Verification gap" value={Math.max(counts.practitioners - counts.verified_practitioners, 0)} detail="Practitioners needing review" tone={counts.practitioners === counts.verified_practitioners ? 'teal' : 'amber'} />
      </section>

      <BusinessWorkbench csrfToken={csrfToken} data={data} domain="people" onChanged={onWorkspaceChanged} />

      <section className="content-grid content-grid-primary">
        <article className="panel">
          <PanelHeader eyebrow="Care records" title="Recently updated patients" actionHref="#people" actionLabel="Manage patients" />
          {patients.length ? (
            <div className="table-scroll">
              <table>
                <thead><tr><th>Patient</th><th>Reference</th><th>Verification</th><th>Consent</th><th>Updated</th></tr></thead>
                <tbody>
                  {patients.map((patient) => (
                    <tr key={patient.id}>
                      <td><strong>{patient.full_name}</strong></td>
                      <td><code>{patient.patient_number}</code></td>
                      <td><StatusBadge value={patient.verification_status} /></td>
                      <td><small>{titleCase(patient.consent_status)}</small></td>
                      <td><span className="muted-cell">{formatDate(patient.updated_at)}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <EmptyState icon="patients" title="No patient records" detail="Registered patient records will appear here without exposing sensitive clinical fields." />}
        </article>

        <article className="panel">
          <PanelHeader eyebrow="Clinical workforce" title="Practitioner verification" actionHref="#people" actionLabel="Manage practitioners" />
          {practitioners.length ? (
            <div className="table-scroll">
              <table>
                <thead><tr><th>Practitioner</th><th>Profession</th><th>Registration</th><th>Licence</th><th>Verification</th></tr></thead>
                <tbody>
                  {practitioners.map((practitioner) => (
                    <tr key={practitioner.id}>
                      <td><strong>{practitioner.full_name}</strong></td>
                      <td><small>{titleCase(practitioner.profession)}</small></td>
                      <td><code>{practitioner.registration_number || '—'}</code></td>
                      <td><StatusBadge value={practitioner.licence_status} /></td>
                      <td><StatusBadge value={practitioner.verification_state} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <EmptyState icon="clinical" title="No practitioner records" detail="Practitioners will appear here when added to the current workspace." />}
        </article>
      </section>

      <article className="panel">
        <PanelHeader eyebrow="Commercial records" title="Customer directory" actionHref="#people" actionLabel="Manage customers" />
        {customers.length ? (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Customer</th><th>Number</th><th>Type</th><th>Status</th><th>Risk</th><th>Credit</th></tr></thead>
              <tbody>
                {customers.map((customer) => (
                  <tr key={customer.id}>
                    <td><strong>{customer.legal_name}</strong></td>
                    <td><code>{customer.customer_number}</code></td>
                    <td><small>{titleCase(customer.customer_type)}</small></td>
                    <td><StatusBadge value={customer.status} /></td>
                    <td><StatusBadge value={customer.risk_classification} /></td>
                    <td><StatusBadge value={customer.credit_status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <EmptyState icon="building" title="No commercial customers" detail="Approved pharmacy, hospital and institutional customers will appear here." />}
      </article>
    </>
  );
}

/**
 * The catalogue layers, in the app rather than in Django admin.
 *
 * These four panels replace four links into `/admin/medicines/…`. The admin is
 * a database editor: it shows every column, enforces none of the service rules,
 * and is reachable only by staff accounts. Reading the product master should not
 * require either.
 *
 * Read-only for now. The write path for these records goes through
 * MedicineCatalogueService, and putting an edit form here before that is wired
 * up would either bypass it or pretend to.
 */
type CatalogueLayer = 'substances' | 'clinical' | 'manufactured' | 'manufacturers';

const CATALOGUE_LAYERS: readonly { readonly key: CatalogueLayer; readonly label: string; readonly detail: string }[] = [
  { key: 'substances', label: 'Substances', detail: 'Canonical active ingredients' },
  { key: 'clinical', label: 'Clinical products', detail: 'Strength, dose form and route' },
  { key: 'manufactured', label: 'Manufactured products', detail: 'Brands and market authorisations' },
  { key: 'manufacturers', label: 'Manufacturers', detail: 'Registered product sources' },
];

function CatalogueLayers() {
  const [layer, setLayer] = useState<CatalogueLayer>('substances');
  const [substances, setSubstances] = useState<readonly ActiveSubstanceSummary[] | null>(null);
  const [clinical, setClinical] = useState<readonly ClinicalProductSummary[] | null>(null);
  const [manufactured, setManufactured] = useState<readonly ManufacturedProductSummary[] | null>(null);
  const [manufacturers, setManufacturers] = useState<readonly ManufacturerSummary[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const fail = () => {
      if (!controller.signal.aborted) setFailed(true);
    };
    // Each layer is fetched once and kept. Switching tabs should not re-request
    // data that has not changed.
    loadActiveSubstances(controller.signal).then(setSubstances).catch(fail);
    loadClinicalProducts(controller.signal).then(setClinical).catch(fail);
    loadManufacturedProducts(controller.signal).then(setManufactured).catch(fail);
    loadManufacturers(controller.signal).then(setManufacturers).catch(fail);
    return () => controller.abort();
  }, []);

  if (failed) return <Unavailable />;

  const rows = { substances, clinical, manufactured, manufacturers }[layer];

  return (
    <article className="panel table-panel">
      <div className="table-toolbar">
        <PanelHeader eyebrow="Catalogue layers" title="Product governance records" />
        <nav className="segmented" aria-label="Catalogue layer">
          {CATALOGUE_LAYERS.map((option) => (
            <button
              key={option.key}
              type="button"
              className={option.key === layer ? 'segmented-option is-active' : 'segmented-option'}
              aria-pressed={option.key === layer}
              title={option.detail}
              onClick={() => setLayer(option.key)}
            >
              {option.label}
            </button>
          ))}
        </nav>
      </div>

      {rows === null ? (
        <p className="muted-cell">Loading {layer === 'clinical' ? 'clinical products' : layer}…</p>
      ) : rows.length === 0 ? (
        <EmptyState
          icon="clinical"
          title={`No ${CATALOGUE_LAYERS.find((o) => o.key === layer)?.label.toLowerCase()}`}
          detail="Records added to the product master appear here."
        />
      ) : (
        <div className="table-scroll">
          {layer === 'substances' && (
            <table>
              <thead><tr><th>Code</th><th>Canonical name</th><th>Type</th><th>Controlled</th><th>Scope</th><th>Status</th></tr></thead>
              <tbody>
                {substances?.map((row) => (
                  <tr key={row.id}>
                    <td><code>{row.code}</code></td>
                    <td><strong>{row.canonical_name}</strong>{row.display_name && row.display_name !== row.canonical_name ? <small> · {row.display_name}</small> : null}</td>
                    <td><small>{row.substance_type || '—'}</small></td>
                    <td>{row.controlled_classification && row.controlled_classification !== 'NONE'
                      ? <StatusBadge value={row.controlled_classification} />
                      : <span className="muted-cell">—</span>}</td>
                    <td><small>{row.is_global ? 'Global' : 'Tenant'}</small></td>
                    <td><StatusBadge value={row.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {layer === 'clinical' && (
            <table>
              <thead><tr><th>Code</th><th>Product</th><th>Dose form</th><th>Ingredients</th><th>Classification</th><th>Status</th></tr></thead>
              <tbody>
                {clinical?.map((row) => (
                  <tr key={row.id}>
                    <td><code>{row.code}</code></td>
                    <td><strong>{row.canonical_name}</strong></td>
                    <td><small>{row.dose_form_name || '—'}</small></td>
                    <td><small>{row.ingredients.length
                      ? row.ingredients.map((i) => `${i.active_substance_name} ${i.numerator_value}${i.numerator_unit}`).join(' + ')
                      : '—'}</small></td>
                    <td><small>{[
                      row.prescription_classification,
                      row.controlled_classification !== 'NONE' ? row.controlled_classification : null,
                      row.antimicrobial_classification !== 'NONE' ? row.antimicrobial_classification : null,
                    ].filter(Boolean).join(' · ') || '—'}</small></td>
                    <td><StatusBadge value={row.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {layer === 'manufactured' && (
            <table>
              <thead><tr><th>Code</th><th>Brand</th><th>Clinical product</th><th>Manufacturer</th><th>Authorisation</th><th>Licence</th></tr></thead>
              <tbody>
                {manufactured?.map((row) => (
                  <tr key={row.id}>
                    <td><code>{row.code}</code></td>
                    <td><strong>{row.brand_name}</strong></td>
                    <td><small>{row.clinical_product_name || '—'}</small></td>
                    <td><span className="muted-cell">{row.manufacturer_name || '—'}</span></td>
                    <td><code>{row.market_authorisation_number || '—'}</code></td>
                    <td><StatusBadge value={row.licence_status || row.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {layer === 'manufacturers' && (
            <table>
              <thead><tr><th>Code</th><th>Legal name</th><th>Trading as</th><th>Country</th><th>Regulator ID</th><th>Status</th></tr></thead>
              <tbody>
                {manufacturers?.map((row) => (
                  <tr key={row.id}>
                    <td><code>{row.code}</code></td>
                    <td><strong>{row.legal_name}</strong></td>
                    <td><span className="muted-cell">{row.trading_name || '—'}</span></td>
                    <td><small>{row.country || '—'}</small></td>
                    <td><code>{row.regulator_identifier || '—'}</code></td>
                    <td><StatusBadge value={row.is_active ? 'ACTIVE' : 'INACTIVE'} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </article>
  );
}

function CatalogueView({
  csrfToken,
  data,
  failed,
  onWorkspaceChanged,
  overview,
}: BusinessViewProps & { readonly overview: HQOverview }) {
  if (failed) return <WorkspaceSectionError domain="medicine catalogue" />;
  if (!data) return <WorkspaceSectionLoading domain="medicine catalogue" />;

  const { counts, skus } = data.catalogue;
  return (
    <>
      <section className="metric-grid network-metrics" aria-label="Medicine catalogue totals">
        <SummaryCard icon="inventory" label="Commercial SKUs" value={counts.skus} detail={`${formatNumber(counts.active_skus)} active`} />
        <SummaryCard icon="clinical" label="Active substances" value={counts.substances} detail="Governed ingredient records" tone="teal" />
        <SummaryCard icon="building" label="Manufacturers" value={counts.manufacturers} detail="Registered product sources" />
        <SummaryCard icon="alert" label="Inactive SKUs" value={Math.max(counts.skus - counts.active_skus, 0)} detail="Draft, inactive or recalled" tone={counts.skus === counts.active_skus ? 'teal' : 'amber'} />
      </section>

      <GovernmentCatalogue csrfToken={csrfToken} overview={overview} />

      <BusinessWorkbench csrfToken={csrfToken} data={data} domain="catalogue" onChanged={onWorkspaceChanged} />

      <article className="panel table-panel">
        <div className="table-toolbar">
          <PanelHeader eyebrow="Product master" title="Commercial medicine catalogue" />
        </div>
        {skus.length ? (
          <div className="table-scroll">
            <table>
              <thead><tr><th>SKU</th><th>Display name</th><th>Medicine</th><th>Brand</th><th>Barcode</th><th>Uses</th><th>Status</th></tr></thead>
              <tbody>
                {skus.map((sku) => (
                  <tr key={sku.id}>
                    <td><code>{sku.sku_code}</code></td>
                    <td><strong>{sku.display_name}</strong></td>
                    <td><small>{sku.canonical_medicine_name}</small></td>
                    <td><span className="muted-cell">{sku.brand_name || 'Generic'}</span></td>
                    <td><code>{sku.default_barcode || '—'}</code></td>
                    <td><small>{[sku.is_saleable && 'Sale', sku.is_purchasable && 'Purchase', sku.is_dispensable && 'Dispense'].filter(Boolean).join(' · ') || 'Reference only'}</small></td>
                    <td><StatusBadge value={sku.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <EmptyState icon="inventory" title="No commercial SKUs" detail="Create governed products, packages and identifiers before stock can be transacted." />}
      </article>

      <CatalogueLayers />
    </>
  );
}

function GovernmentCatalogue({
  csrfToken,
  overview,
}: {
  readonly csrfToken: string;
  readonly overview: HQOverview;
}) {
  const [query, setQuery] = useState('');
  const [appliedQuery, setAppliedQuery] = useState('');
  const [kemlStatus, setKemlStatus] = useState('');
  const [levelOfUse, setLevelOfUse] = useState('');
  const [catalogueMode, setCatalogueMode] = useState<'master' | 'tenant'>('master');
  const [tenantId, setTenantId] = useState(
    overview.tenant_id || overview.network_items[0]?.id || '',
  );
  const [page, setPage] = useState(1);
  const [catalogue, setCatalogue] = useState<GovernmentCataloguePage | null>(null);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [mutationId, setMutationId] = useState('');
  const [mutationError, setMutationError] = useState('');
  const [reloadVersion, setReloadVersion] = useState(0);

  useEffect(() => {
    const nextTenantId = overview.tenant_id || overview.network_items[0]?.id || '';
    setTenantId((current) => current || nextTenantId);
  }, [overview.network_items, overview.tenant_id]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setFailed(false);
    loadGovernmentCatalogue(
      {
        kemlStatus,
        levelOfUse,
        page,
        pageSize: 50,
        query: appliedQuery,
        selectedOnly: catalogueMode === 'tenant',
        tenantId,
      },
      controller.signal,
    )
      .then((response) => {
        if (!controller.signal.aborted) {
          setCatalogue(response);
          setPage(response.page);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [appliedQuery, catalogueMode, kemlStatus, levelOfUse, page, reloadVersion, tenantId]);

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPage(1);
    setAppliedQuery(query.trim());
  };
  const resetFilters = () => {
    setQuery('');
    setAppliedQuery('');
    setKemlStatus('');
    setLevelOfUse('');
    setPage(1);
  };
  const changeSelection = async (medicineId: string, selected: boolean) => {
    if (!tenantId) return;
    setMutationId(medicineId);
    setMutationError('');
    try {
      await updateGovernmentCatalogueSelection(
        medicineId,
        selected,
        tenantId,
        csrfToken,
      );
      setReloadVersion((version) => version + 1);
    } catch (reason) {
      setMutationError(
        reason instanceof Error ? reason.message : 'The tenant catalogue could not be updated.',
      );
    } finally {
      setMutationId('');
    }
  };
  const filterActive = Boolean(appliedQuery || kemlStatus || levelOfUse);
  const sourceDate = catalogue?.source_version.match(/updated:([^;]+)/)?.[1] ?? '';
  const resultStart = catalogue && catalogue.count
    ? ((catalogue.page - 1) * catalogue.page_size) + 1
    : 0;
  const resultEnd = catalogue
    ? Math.min(catalogue.page * catalogue.page_size, catalogue.count)
    : 0;

  return (
    <article className="panel table-panel government-catalogue">
      <div className="government-catalogue-head">
        <div>
          <p className="eyebrow">Universal medicine master</p>
          <h2>Kenya eTCD product catalogue</h2>
          <p>
            The national catalogue is shared across TibaTrace. Each tenant selects only
            the medicines it carries, then completes package, price and branch governance.
          </p>
        </div>
        <div className="government-catalogue-summary">
          <span><strong>{formatNumber(catalogue?.catalogue_count ?? 0)}</strong> reference products</span>
          <small>
            {catalogue?.tenant_name
              ? `${formatNumber(catalogue.selected_count)} selected for ${catalogue.tenant_name}`
              : sourceDate
                ? `Source updated ${formatDate(sourceDate)}`
                : 'Government catalogue source'}
          </small>
        </div>
      </div>

      <div className="catalogue-scopebar">
        <nav className="segmented" aria-label="Catalogue scope">
          <button
            aria-pressed={catalogueMode === 'master'}
            className={catalogueMode === 'master' ? 'segmented-option is-active' : 'segmented-option'}
            onClick={() => {
              setCatalogueMode('master');
              setPage(1);
            }}
            type="button"
          >
            Universal master
          </button>
          <button
            aria-pressed={catalogueMode === 'tenant'}
            className={catalogueMode === 'tenant' ? 'segmented-option is-active' : 'segmented-option'}
            disabled={!tenantId}
            onClick={() => {
              setCatalogueMode('tenant');
              setPage(1);
            }}
            type="button"
          >
            Tenant catalogue
          </button>
        </nav>
        {overview.is_platform_overview ? (
          <label className="catalogue-tenant-select">
            <span>Tenant workspace</span>
            <select
              onChange={(event) => {
                setTenantId(event.target.value);
                setPage(1);
              }}
              value={tenantId}
            >
              {overview.network_items.map((tenant) => (
                <option key={tenant.id} value={tenant.id}>{tenant.name}</option>
              ))}
            </select>
          </label>
        ) : (
          <div className="catalogue-tenant-label">
            <span>Tenant catalogue</span>
            <strong>{overview.tenant_name}</strong>
          </div>
        )}
      </div>

      <form className="government-catalogue-filters" onSubmit={submitSearch}>
        <label className="search-field">
          <span className="sr-only">Search national catalogue</span>
          <Icon name="search" />
          <input
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search eTCD ID, generic, brand, PPB or manufacturer"
            type="search"
            value={query}
          />
        </label>
        <label>
          <span className="sr-only">KEML status</span>
          <select
            aria-label="KEML status"
            onChange={(event) => {
              setKemlStatus(event.target.value);
              setPage(1);
            }}
            value={kemlStatus}
          >
            <option value="">All KEML statuses</option>
            {(catalogue?.available_keml_statuses ?? ['No', 'Yes']).map((status) => (
              <option key={status} value={status}>{status === 'Yes' ? 'On KEML' : 'Not on KEML'}</option>
            ))}
          </select>
        </label>
        <label>
          <span className="sr-only">Level of use</span>
          <select
            aria-label="Level of use"
            onChange={(event) => {
              setLevelOfUse(event.target.value);
              setPage(1);
            }}
            value={levelOfUse}
          >
            <option value="">All levels of use</option>
            {(catalogue?.available_levels_of_use ?? ['1', '2', '3', '4', '5', '6', '9']).map((level) => (
              <option key={level} value={level}>Level {level}</option>
            ))}
          </select>
        </label>
        <button className="primary-button" type="submit">Search</button>
        {filterActive ? <button className="secondary-button" onClick={resetFilters} type="button">Clear</button> : null}
      </form>

      {mutationError ? <div className="catalogue-action-error" role="status"><Icon name="alert" />{mutationError}</div> : null}

      {failed ? (
        <EmptyState icon="alert" title="National catalogue unavailable" detail="The government catalogue could not be loaded. Try again after checking the API service." />
      ) : catalogue === null ? (
        <p className="catalogue-loading">Loading national catalogue…</p>
      ) : catalogue.results.length === 0 ? (
        <EmptyState
          icon="clinical"
          title={catalogueMode === 'tenant' ? 'No medicines selected for this tenant' : 'No matching master products'}
          detail={catalogueMode === 'tenant'
            ? 'Use the Universal master tab to add medicines to this tenant catalogue.'
            : 'Adjust the search or KEML filters to broaden the catalogue results.'}
        />
      ) : (
        <>
          <div className={loading ? 'table-scroll catalogue-table is-loading' : 'table-scroll catalogue-table'}>
            <table>
              <thead>
                <tr>
                  <th>eTCD ID</th>
                  <th>Generic / brand</th>
                  <th>Strength & form</th>
                  <th>Route</th>
                  <th>PPB registration</th>
                  <th>KEML / level</th>
                  <th>Manufacturer</th>
                  <th>Tenant catalogue</th>
                </tr>
              </thead>
              <tbody>
                {catalogue.results.map((medicine) => (
                  <tr key={medicine.id}>
                    <td><code>{medicine.code}</code></td>
                    <td>
                      <strong>{medicine.generic_name || 'Unnamed product'}</strong>
                      <small className="row-detail">{medicine.brand_name || 'Generic / unbranded'}</small>
                    </td>
                    <td>
                      <strong>{medicine.strength || '—'}</strong>
                      <small className="row-detail">{medicine.dosage_form || 'Form not stated'}</small>
                    </td>
                    <td><small>{medicine.route || '—'}</small></td>
                    <td><code>{medicine.licence_identifier || '—'}</code></td>
                    <td>
                      <span className={medicine.keml_status === 'Yes' ? 'keml-mark is-listed' : 'keml-mark'}>
                        {medicine.keml_status === 'Yes' ? 'KEML' : 'Not KEML'}
                      </span>
                      <small className="row-detail">{medicine.level_of_use ? `Level ${medicine.level_of_use}` : 'Level not stated'}</small>
                    </td>
                    <td><small>{medicine.manufacturer_name || '—'}</small></td>
                    <td>
                      {medicine.selected ? (
                        catalogueMode === 'tenant' && catalogue.can_manage ? (
                          <button
                            className="catalogue-remove-button"
                            disabled={mutationId === medicine.id}
                            onClick={() => void changeSelection(medicine.id, false)}
                            type="button"
                          >
                            {mutationId === medicine.id ? 'Removing…' : 'Remove'}
                          </button>
                        ) : <span className="reference-badge is-selected">Selected</span>
                      ) : catalogue.can_manage ? (
                        <button
                          className="catalogue-add-button"
                          disabled={mutationId === medicine.id}
                          onClick={() => void changeSelection(medicine.id, true)}
                          type="button"
                        >
                          {mutationId === medicine.id ? 'Adding…' : 'Add to tenant'}
                        </button>
                      ) : <span className="reference-badge">Master only</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <footer className="catalogue-pagination">
            <span>
              Showing {formatNumber(resultStart)}–{formatNumber(resultEnd)} of {formatNumber(catalogue.count)}
              {filterActive ? ` matches · ${formatNumber(catalogue.catalogue_count)} master total` : ''}
            </span>
            <div>
              <button
                className="secondary-button"
                disabled={loading || catalogue.page <= 1}
                onClick={() => setPage((current) => Math.max(current - 1, 1))}
                type="button"
              >
                Previous
              </button>
              <strong>Page {formatNumber(catalogue.page)} of {formatNumber(catalogue.pages)}</strong>
              <button
                className="secondary-button"
                disabled={loading || catalogue.page >= catalogue.pages}
                onClick={() => setPage((current) => current + 1)}
                type="button"
              >
                Next
              </button>
            </div>
          </footer>
        </>
      )}
    </article>
  );
}

function CommerceView({
  csrfToken,
  data,
  failed,
  onWorkspaceChanged,
}: BusinessViewProps) {
  if (failed) return <WorkspaceSectionError domain="sales and fulfilment" />;
  if (!data) return <WorkspaceSectionLoading domain="sales and fulfilment" />;

  const { counts, dispatches, orders } = data.commerce;
  return (
    <>
      <section className="metric-grid network-metrics" aria-label="Sales and fulfilment totals">
        <SummaryCard icon="docs" label="Quotations" value={counts.quotations} detail="Commercial offers" />
        <SummaryCard icon="store" label="Open orders" value={counts.open_orders} detail={`${formatNumber(counts.orders)} total orders`} tone={counts.open_orders ? 'amber' : 'teal'} />
        <SummaryCard icon="inventory" label="Dispatches" value={counts.dispatches} detail={`${formatNumber(counts.deliveries)} delivery records`} />
        <SummaryCard icon="refresh" label="Returns" value={counts.returns} detail="Authorised return records" tone={counts.returns ? 'amber' : 'teal'} />
      </section>

      <BusinessWorkbench csrfToken={csrfToken} data={data} domain="commerce" onChanged={onWorkspaceChanged} />

      <section className="content-grid content-grid-primary">
        <article className="panel">
          <PanelHeader eyebrow="Order book" title="Recent sales orders" actionHref="#commerce" actionLabel="Manage orders" />
          {orders.length ? (
            <div className="table-scroll">
              <table>
                <thead><tr><th>Order</th><th>Customer</th><th>Date</th><th>Priority</th><th>Total</th><th>Status</th></tr></thead>
                <tbody>
                  {orders.map((order) => (
                    <tr key={order.id}>
                      <td><code>{order.order_number}</code></td>
                      <td><strong>{order.customer_name}</strong></td>
                      <td><span className="muted-cell">{formatDate(order.order_date)}</span></td>
                      <td><small>{order.priority ? `Priority ${order.priority}` : 'Standard'}</small></td>
                      <td><strong>{formatMoney(order.total, order.currency)}</strong></td>
                      <td><StatusBadge value={order.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <EmptyState icon="store" title="No sales orders" detail="Approved customer demand will appear here as orders enter fulfilment." />}
        </article>

        <article className="panel">
          <PanelHeader eyebrow="Outbound logistics" title="Recent dispatches" actionHref="#commerce" actionLabel="Manage dispatches" />
          {dispatches.length ? (
            <div className="table-scroll">
              <table>
                <thead><tr><th>Dispatch</th><th>Customer</th><th>Carrier</th><th>Dispatch date</th><th>Expected</th><th>Status</th></tr></thead>
                <tbody>
                  {dispatches.map((dispatch) => (
                    <tr key={dispatch.id}>
                      <td><code>{dispatch.dispatch_number}</code></td>
                      <td><strong>{dispatch.customer_name}</strong></td>
                      <td><small>{dispatch.carrier || 'Internal fleet'}</small></td>
                      <td><span className="muted-cell">{formatDate(dispatch.dispatch_date)}</span></td>
                      <td><span className="muted-cell">{formatDate(dispatch.expected_delivery_date)}</span></td>
                      <td><StatusBadge value={dispatch.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <EmptyState icon="inventory" title="No dispatches" detail="Packed orders will appear here when released to outbound logistics." />}
        </article>
      </section>

      <article className="panel workflow-panel">
        <PanelHeader eyebrow="Order-to-delivery" title="Fulfilment workspaces" />
        <div className="workflow-grid">
          <WorkflowLink href="#commerce" icon="docs" step="01" title="Quotations" detail="Price and approve customer demand." />
          <WorkflowLink href="#commerce" icon="store" step="02" title="Sales orders" detail="Control holds, allocation and approval." />
          <WorkflowLink href="#commerce" icon="inventory" step="03" title="Pick & pack" detail="Coordinate warehouse fulfilment." />
          <WorkflowLink href="#commerce" icon="check" step="04" title="Delivery & returns" detail="Capture proof, exceptions and returns." />
        </div>
      </article>
    </>
  );
}

function GovernanceView({ data, failed }: { readonly data: HQWorkspaceData | null; readonly failed: boolean }) {
  if (failed) return <WorkspaceSectionError domain="system governance" />;
  if (!data) return <WorkspaceSectionLoading domain="system governance" />;

  const { audit_events: auditEvents, counts, crosswalks, documents, domain_events: domainEvents, notifications } = data.governance;
  return (
    <>
      <section className="metric-grid network-metrics" aria-label="System governance totals">
        <SummaryCard icon="shield" label="Audit events" value={counts.audit_events} detail="Immutable activity records" />
        <SummaryCard icon="docs" label="Clinical documents" value={counts.documents} detail="Stored governed files" />
        <SummaryCard icon="activity" label="Failed events" value={counts.failed_domain_events} detail={`${formatNumber(counts.domain_events)} domain events`} tone={counts.failed_domain_events ? 'rose' : 'teal'} />
        <SummaryCard icon="external" label="Pending notifications" value={counts.pending_notifications} detail={`${formatNumber(counts.crosswalks)} legacy crosswalks`} tone={counts.pending_notifications ? 'amber' : 'teal'} />
      </section>

      <article className="panel">
        <PanelHeader eyebrow="Immutable record" title="Recent audit activity" actionHref="/api/audit/events/" actionLabel="Open audit API" />
        {auditEvents.length ? (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Record</th><th>Object</th><th>Outcome</th><th>Correlation</th></tr></thead>
              <tbody>
                {auditEvents.map((event) => (
                  <tr key={event.id}>
                    <td><span className="muted-cell">{formatDateTime(event.created_at)}</span></td>
                    <td><strong>{event.actor}</strong></td>
                    <td><small>{titleCase(event.action)}</small></td>
                    <td><code>{event.model_name}</code></td>
                    <td><code>{event.object_id}</code></td>
                    <td><StatusBadge value={event.outcome} /></td>
                    <td><code>{event.correlation_id || '—'}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <EmptyState icon="shield" title="No audit events" detail="Immutable activity records will appear as governed actions occur." />}
      </article>

      <section className="content-grid content-grid-primary governance-grid">
        <article className="panel">
          <PanelHeader eyebrow="Workflow engine" title="Domain event queue" />
          {domainEvents.length ? (
            <div className="table-scroll">
              <table>
                <thead><tr><th>Event</th><th>Aggregate</th><th>Attempts</th><th>Status</th><th>Created</th></tr></thead>
                <tbody>
                  {domainEvents.map((event) => (
                    <tr key={event.id}>
                      <td><strong>{event.event_type}</strong>{event.last_error ? <small className="row-detail text-rose">{event.last_error}</small> : null}</td>
                      <td><code>{event.aggregate_type}</code></td>
                      <td>{formatNumber(event.attempts)}</td>
                      <td><StatusBadge value={event.status} /></td>
                      <td><span className="muted-cell">{formatDateTime(event.created_at)}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <EmptyState icon="activity" title="No domain events" detail="Workflow events will appear as asynchronous processing begins." />}
        </article>

        <article className="panel">
          <PanelHeader eyebrow="Communications" title="Notification outbox" />
          {notifications.length ? (
            <div className="table-scroll">
              <table>
                <thead><tr><th>Channel</th><th>Recipient</th><th>Template</th><th>Status</th><th>Created</th></tr></thead>
                <tbody>
                  {notifications.map((notification) => (
                    <tr key={notification.id}>
                      <td><strong>{titleCase(notification.channel)}</strong></td>
                      <td><code>{notification.recipient}</code></td>
                      <td><small>{notification.template_code}</small></td>
                      <td><StatusBadge value={notification.status} /></td>
                      <td><span className="muted-cell">{formatDateTime(notification.created_at)}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <EmptyState icon="external" title="Notification outbox is empty" detail="Queued patient and operational communications will appear here with masked recipients." />}
        </article>
      </section>

      <section className="content-grid">
        <article className="panel">
          <PanelHeader eyebrow="Clinical storage" title="Recent documents" actionHref="/api/documents/" actionLabel="Open documents API" />
          {documents.length ? (
            <div className="table-scroll">
              <table>
                <thead><tr><th>Document</th><th>Type</th><th>Size</th><th>Malware scan</th><th>Created</th></tr></thead>
                <tbody>
                  {documents.map((document) => (
                    <tr key={document.id}>
                      <td><strong>{document.original_name}</strong></td>
                      <td><small>{document.content_type}</small></td>
                      <td>{formatBytes(document.size_bytes)}</td>
                      <td><StatusBadge value={document.malware_scan_status} /></td>
                      <td><span className="muted-cell">{formatDateTime(document.created_at)}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <EmptyState icon="docs" title="No stored documents" detail="Clinical uploads will appear after storage and malware scanning." />}
        </article>

        <article className="panel">
          <PanelHeader eyebrow="Migration assurance" title="Legacy identifier crosswalks" />
          {crosswalks.length ? (
            <div className="table-scroll">
              <table>
                <thead><tr><th>Source</th><th>Source type</th><th>Target type</th><th>Batch</th><th>Migrated</th></tr></thead>
                <tbody>
                  {crosswalks.map((crosswalk) => (
                    <tr key={crosswalk.id}>
                      <td><code>{crosswalk.source_system}</code></td>
                      <td><small>{titleCase(crosswalk.source_entity_type)}</small></td>
                      <td><small>{titleCase(crosswalk.target_entity_type)}</small></td>
                      <td><code>{crosswalk.migration_batch || '—'}</code></td>
                      <td><span className="muted-cell">{formatDateTime(crosswalk.migrated_at)}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <EmptyState icon="database" title="No legacy crosswalks" detail="Immutable source-to-TibaTrace identifier mappings will appear during migration." />}
        </article>
      </section>
    </>
  );
}


/**
 * Decision support, terminology and encounters.
 *
 * These three replaced a row of cards that linked to `#clinical` -- the view
 * they were already on. They read as navigation to a management screen that did
 * not exist: `cds`, `terminology` and `clinical` had models, endpoints and rows,
 * and no surface anywhere in the app.
 *
 * Read-only. Knowledge releases are published artefacts with a checksum, and
 * terminology is governed reference data; editing either from here would need a
 * service and an approval step that do not exist yet.
 */
type ClinicalTable = 'releases' | 'terminology' | 'encounters';

const CLINICAL_TABLES: readonly { readonly key: ClinicalTable; readonly label: string }[] = [
  { key: 'releases', label: 'Knowledge releases' },
  { key: 'terminology', label: 'Terminology' },
  { key: 'encounters', label: 'Encounters' },
];

function ClinicalGovernanceTables({ data }: { readonly data: HQWorkspaceData | null }) {
  const [table, setTable] = useState<ClinicalTable>('releases');
  if (!data) return null;
  const clinical = data.clinical;

  return (
    <article className="panel table-panel">
      <div className="table-toolbar">
        <PanelHeader eyebrow="Clinical governance" title="Decision support and terminology" />
        <nav className="segmented" aria-label="Clinical governance table">
          {CLINICAL_TABLES.map((option) => (
            <button
              key={option.key}
              type="button"
              className={option.key === table ? 'segmented-option is-active' : 'segmented-option'}
              aria-pressed={option.key === table}
              onClick={() => setTable(option.key)}
            >
              {option.label}
            </button>
          ))}
        </nav>
      </div>

      <div className="table-scroll">
        {table === 'releases' && (clinical.knowledge_releases.length ? (
          <table>
            <thead><tr><th>Release</th><th>Version</th><th>Source</th><th>Effective</th><th>Licence</th><th>Checksum</th><th>State</th></tr></thead>
            <tbody>
              {clinical.knowledge_releases.map((release) => (
                <tr key={release.id}>
                  <td><code>{release.code}</code></td>
                  <td><strong>{release.version}</strong></td>
                  <td><small>{release.source}{release.source_version ? ` · ${release.source_version}` : ''}</small></td>
                  <td><small>{formatDate(release.effective_date)}</small></td>
                  <td><small>{release.licence || '—'}</small></td>
                  {/* The digest is what ties a screening decision to the rules
                      that produced it, so it is shown rather than hidden. */}
                  <td><code>{release.checksum || '—'}</code></td>
                  <td><StatusBadge value={release.is_active ? 'ACTIVE' : 'INACTIVE'} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <EmptyState icon="shield" title="No knowledge releases" detail="Decision support screens against published releases; none are loaded." />)}

        {table === 'terminology' && (clinical.code_systems.length || clinical.value_sets.length ? (
          <table>
            <thead><tr><th>Kind</th><th>Name</th><th>Title</th><th>Version</th><th>Concepts</th><th>Scope</th></tr></thead>
            <tbody>
              {clinical.code_systems.map((system) => (
                <tr key={system.id}>
                  <td><small>Code system</small></td>
                  <td><strong>{system.name}</strong></td>
                  <td><small>{system.title || system.url}</small></td>
                  <td><small>{system.version || '—'}</small></td>
                  <td><small>{formatNumber(system.concept_count)}</small></td>
                  <td><small>{system.is_global ? 'Global' : 'Tenant'}</small></td>
                </tr>
              ))}
              {clinical.value_sets.map((valueSet) => (
                <tr key={valueSet.id}>
                  <td><small>Value set</small></td>
                  <td><strong>{valueSet.name}</strong></td>
                  <td><small>{valueSet.title || valueSet.url}</small></td>
                  <td><small>{valueSet.version || '—'}</small></td>
                  <td><span className="muted-cell">—</span></td>
                  <td><small>{valueSet.is_global ? 'Global' : 'Tenant'}</small></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <EmptyState icon="database" title="No terminology registered" detail="Code systems and value sets appear here once registered." />)}

        {table === 'encounters' && (clinical.encounters.length ? (
          <table>
            <thead><tr><th>Patient</th><th>Class</th><th>Practitioner</th><th>Started</th><th>Reason</th><th>Status</th></tr></thead>
            <tbody>
              {clinical.encounters.map((encounter) => (
                <tr key={encounter.id}>
                  <td><strong>{encounter.patient_name ?? 'Not recorded'}</strong></td>
                  <td><small>{encounter.encounter_class || '—'}</small></td>
                  <td><span className="muted-cell">{encounter.practitioner_name ?? 'Not recorded'}</span></td>
                  <td><small>{formatDateTime(encounter.start_time)}</small></td>
                  <td><small>{encounter.reason_code || '—'}</small></td>
                  <td><StatusBadge value={encounter.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <EmptyState icon="clinical" title="No encounters recorded" detail="Clinical encounters appear here as they are captured." />)}
      </div>
    </article>
  );
}

function ClinicalView({
  csrfToken,
  data,
  failed,
  onWorkspaceChanged,
  overview,
}: BusinessViewProps & { readonly overview: HQOverview }) {
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

      {failed
        ? <WorkspaceSectionError domain="clinical workflow" />
        : data
          ? <BusinessWorkbench csrfToken={csrfToken} data={data} domain="clinical" onChanged={onWorkspaceChanged} />
          : <WorkspaceSectionLoading domain="clinical workflow" />}

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

      <ClinicalGovernanceTables data={data} />

      <section className="content-grid">
        <article className="panel">
          <PanelHeader eyebrow="Prescription governance" title="Active dispensing" />
          <div className="priority-list">
            <PriorityItem action="Open prescriptions" detail="Active prescribing and dispensing workflow" href="#clinical" icon="clinical" value={metricValue(overview, 'Open prescriptions')} tone={metricValue(overview, 'Open prescriptions') ? 'amber' : 'teal'} />
            <PriorityItem action="Clinical substitutions" detail="Pharmacist-initiated therapeutic substitutions" href="#clinical" icon="activity" value={0} valueLabel="View" />
            <PriorityItem action="Dispensing labels" detail="Audit label generation and reprints" href="#clinical" icon="docs" value={0} valueLabel="Audit" />
          </div>
        </article>
        <article className="panel">
          <PanelHeader eyebrow="Formulary" title="Medicines & pricing" />
          <div className="command-links">
            <CommandLink href="#catalogue" title="Commercial SKUs" detail="Packaged medicines and identifiers" icon="inventory" />
            <CommandLink href="#catalogue" title="Active substances" detail="Governed substance register" icon="clinical" />
            <CommandLink href="#pricing" title="Price books" detail="Formulary pricing and live versions" icon="building" />
          </div>
        </article>
      </section>
    </>
  );
}

function AccessView({
  csrfToken,
  data,
  failed,
  onWorkspaceChanged,
  overview,
}: BusinessViewProps & { readonly overview: HQOverview }) {
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
        <span className="status-badge status-active"><i /> Access controls active</span>
      </section>

      {failed
        ? <WorkspaceSectionError domain="user access register" />
        : data
          ? <BusinessWorkbench csrfToken={csrfToken} data={data} domain="access" onChanged={onWorkspaceChanged} />
          : <WorkspaceSectionLoading domain="user access register" />}

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
            <SecurityCheck title="Audited administration" detail="Sensitive changes remain behind governed service interfaces." />
          </div>
        </article>
      </section>

      <article className="panel workflow-panel">
        <PanelHeader eyebrow="Identity administration" title="Access management workspaces" />
        <div className="workflow-grid">
          <WorkflowLink href="#access" icon="users" step="01" title="Users" detail="Accounts, status and workspace assignment." />
          <WorkflowLink href="#access" icon="shield" step="02" title="Roles" detail="Capability bundles and system roles." />
          <WorkflowLink href="#access" icon="security" step="03" title="Assignments" detail="Audited user-to-role grants." />
          <WorkflowLink href="#access" icon="database" step="04" title="Service accounts" detail="Machine identities and capabilities." />
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
              <PanelHeader eyebrow="Cash control" title="Open register sessions" actionHref="#cash" actionLabel="View all" />
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
              <PanelHeader eyebrow="Financial audit" title="Cash variance watchlist" actionHref="#cash" actionLabel="View all" />
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
            <PanelHeader eyebrow="Custody audit" title="Forced register closures" actionHref="#cash" actionLabel="View all" />
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
  const destination = actionHref ?? '';
  return (
    <header className="panel-header">
      <div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2></div>
      {destination && actionLabel && !isCurrentHqDestination(destination) ? <a href={destination}>{actionLabel} <Icon name="arrow" /></a> : null}
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
  const destination = href;
  const content = <><span><Icon name={icon} /></span><div><strong>{title}</strong><small>{detail}</small></div>{!isCurrentHqDestination(destination) ? <Icon className="command-arrow" name="arrow" /> : null}</>;
  return isCurrentHqDestination(destination)
    ? <div className="command-link-static">{content}</div>
    : <a href={destination}>{content}</a>;
}

function WorkflowLink({ detail, href, icon, step, title }: { readonly detail: string; readonly href: string; readonly icon: IconName; readonly step: string; readonly title: string }) {
  const destination = href;
  const content = (
    <>
      <div className="workflow-top"><span><Icon name={icon} /></span><small>{step}</small></div>
      <strong>{title}</strong>
      <p>{detail}</p>
      <b>{isCurrentHqDestination(destination) ? 'Current workspace' : <>Open workspace <Icon name="arrow" /></>}</b>
    </>
  );
  if (isCurrentHqDestination(destination)) {
    return <div className="workflow-link workflow-link-static">{content}</div>;
  }
  return (
    <a className="workflow-link" href={destination}>{content}</a>
  );
}

function PriorityItem({ action, detail, href, icon, tone = 'amber', value, valueLabel }: { readonly action: string; readonly detail: string; readonly href: string; readonly icon: IconName; readonly tone?: string; readonly value: number; readonly valueLabel?: string }) {
  const destination = href;
  const content = (
    <>
      <span className={`priority-icon priority-${tone}`}><Icon name={icon} /></span>
      <div><strong>{action}</strong><small>{detail}</small></div>
      <b>{valueLabel ?? formatNumber(value)}</b>
      {!isCurrentHqDestination(destination) ? <Icon className="priority-arrow" name="chevron" /> : null}
    </>
  );
  if (isCurrentHqDestination(destination)) {
    return <div className="priority-item priority-item-static">{content}</div>;
  }
  return (
    <a className="priority-item" href={destination}>{content}</a>
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

function WorkspaceSectionLoading({ domain }: { readonly domain: string }) {
  return (
    <article className="panel">
      <EmptyState icon="refresh" title={`Loading ${domain} data`} detail="The latest governed records are being prepared for this workspace." />
    </article>
  );
}

function WorkspaceSectionError({ domain }: { readonly domain: string }) {
  return (
    <div className="inline-alert" role="status">
      <Icon name="alert" />
      The {domain} workspace could not be loaded. Refresh the HQ snapshot to try again.
    </div>
  );
}

interface BusinessWorkbenchProps {
  readonly csrfToken: string;
  readonly data: HQWorkspaceData;
  readonly domain: string;
  readonly onChanged: () => Promise<void>;
}

interface PendingBusinessAction {
  readonly action: HQBusinessAction;
  readonly item: HQWorkItem;
}

function BusinessWorkbench({
  csrfToken,
  data,
  domain,
  onChanged,
}: BusinessWorkbenchProps) {
  const modules = useMemo(
    () => data.business_modules.filter((module) => module.domain === domain),
    [data.business_modules, domain],
  );
  const [activeModuleKey, setActiveModuleKey] = useState('');
  const [query, setQuery] = useState('');
  const [pendingAction, setPendingAction] = useState<PendingBusinessAction | null>(null);

  useEffect(() => {
    if (!modules.some((module) => module.key === activeModuleKey)) {
      setActiveModuleKey(modules[0]?.key ?? '');
    }
  }, [activeModuleKey, modules]);

  const activeModule = modules.find((module) => module.key === activeModuleKey) ?? modules[0];
  const records = useMemo(() => {
    if (!activeModule) return [];
    const normalizedQuery = query.trim().toLowerCase();
    if (!normalizedQuery) return activeModule.records;
    return activeModule.records.filter((record) => (
      [
        record.reference,
        record.title,
        record.status,
        record.detail,
        record.tenant_name,
      ].some((value) => value.toLowerCase().includes(normalizedQuery))
    ));
  }, [activeModule, query]);
  const actionableCount = activeModule?.records.filter((record) => record.actions.length > 0).length ?? 0;

  return (
    <article className="panel business-workbench">
      <header className="business-workbench-head">
        <div>
          <p className="eyebrow">Native business desk</p>
          <h2>{activeModule?.title ?? 'Governed workflow'}</h2>
          <p>{activeModule?.description ?? 'No workflow modules are configured for this domain.'}</p>
        </div>
        {activeModule ? (
          <div className="business-workbench-summary">
            <span><strong>{formatNumber(activeModule.records.length)}</strong> records</span>
            <span><strong>{formatNumber(actionableCount)}</strong> actionable</span>
          </div>
        ) : null}
      </header>

      {modules.length ? (
        <>
          <div className="module-tabs" role="tablist" aria-label="Business workflow modules">
            {modules.map((module) => (
              <button
                aria-selected={module.key === activeModule?.key}
                className={module.key === activeModule?.key ? 'module-tab module-tab-active' : 'module-tab'}
                key={module.key}
                onClick={() => {
                  setActiveModuleKey(module.key);
                  setQuery('');
                }}
                role="tab"
                type="button"
              >
                <span>{module.title}</span>
                <b>{formatNumber(module.records.length)}</b>
              </button>
            ))}
          </div>

          <div className="business-toolbar">
            <label>
              <Icon name="search" />
              <span className="sr-only">Search {activeModule?.title}</span>
              <input
                onChange={(event) => setQuery(event.target.value)}
                placeholder={`Search ${activeModule?.title.toLowerCase() ?? 'records'}`}
                type="search"
                value={query}
              />
            </label>
            <small>Actions shown are valid for the record’s current state.</small>
          </div>

          {records.length ? (
            <div className="business-records">
              {records.map((item) => (
                <BusinessRecord
                  item={item}
                  key={`${activeModule?.key ?? domain}-${item.id}`}
                  onAction={(action) => setPendingAction({ action, item })}
                />
              ))}
            </div>
          ) : (
            <EmptyState
              detail={query ? 'Clear the search to restore the complete governed queue.' : 'Records will appear as this workflow receives business activity.'}
              icon={query ? 'search' : 'check'}
              title={query ? 'No matching records' : `No ${activeModule?.title.toLowerCase() ?? 'workflow'} records`}
            />
          )}
        </>
      ) : (
        <EmptyState icon="shield" title="Oversight only" detail="This domain has no state-changing HQ workflow. Its authoritative records remain visible in the panels below." />
      )}

      {pendingAction ? (
        <BusinessActionDialog
          csrfToken={csrfToken}
          onChanged={onChanged}
          onClose={() => setPendingAction(null)}
          pending={pendingAction}
        />
      ) : null}
    </article>
  );
}

function BusinessRecord({
  item,
  onAction,
}: {
  readonly item: HQWorkItem;
  readonly onAction: (action: HQBusinessAction) => void;
}) {
  return (
    <section className="business-record">
      <div className="record-identity">
        <div>
          <code>{item.reference || 'No reference'}</code>
          <span>{item.tenant_name}</span>
        </div>
        <StatusBadge value={item.status} />
      </div>
      <div className="record-body">
        <div>
          <h3>{item.title}</h3>
          <p>{item.detail || 'No additional detail recorded.'}</p>
        </div>
        {item.metrics.length ? (
          <dl className="record-metrics">
            {item.metrics.map((metric) => (
              <div key={`${item.id}-${metric.label}`}>
                <dt>{metric.label}</dt>
                <dd>{friendlyMetricValue(metric.value)}</dd>
              </div>
            ))}
          </dl>
        ) : null}
      </div>
      <footer className="record-actions">
        {item.actions.length ? (
          item.actions.map((action) => (
            <button
              className={`business-action business-action-${action.tone}`}
              key={action.key}
              onClick={() => onAction(action)}
              type="button"
            >
              {action.label}
              <Icon name="arrow" />
            </button>
          ))
        ) : (
          <span><Icon name="check" /> No action required in this state</span>
        )}
      </footer>
    </section>
  );
}

function BusinessActionDialog({
  csrfToken,
  onChanged,
  onClose,
  pending,
}: {
  readonly csrfToken: string;
  readonly onChanged: () => Promise<void>;
  readonly onClose: () => void;
  readonly pending: PendingBusinessAction;
}) {
  const { action, item } = pending;
  const [values, setValues] = useState<Record<string, boolean | number | string>>(
    () => Object.fromEntries(action.fields.map((field) => [field.name, field.default])),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [busy, onClose]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const missingField = action.fields.find((field) => {
      const value = values[field.name];
      return field.required && (
        value === undefined
        || value === false
        || (typeof value === 'string' && !value.trim())
      );
    });
    if (missingField) {
      setError(`${missingField.label} is required.`);
      return;
    }

    setBusy(true);
    setError('');
    try {
      await executeHQBusinessAction(action, item, csrfToken, values);
      await onChanged();
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The workflow action could not be completed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="business-dialog-backdrop"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target && !busy) onClose();
      }}
      role="presentation"
    >
      <section aria-labelledby="business-dialog-title" aria-modal="true" className="business-dialog" role="dialog">
        <header>
          <div>
            <p className="eyebrow">Governed action</p>
            <h2 id="business-dialog-title">{action.label}</h2>
          </div>
          <button aria-label="Close action" disabled={busy} onClick={onClose} type="button"><Icon name="close" /></button>
        </header>
        <div className="business-dialog-record">
          <div><code>{item.reference}</code><strong>{item.title}</strong></div>
          <StatusBadge value={item.status} />
        </div>
        <p className="business-dialog-confirm"><Icon name="shield" /> {action.confirm || 'Confirm this state transition.'}</p>
        <form onSubmit={(event) => void submit(event)}>
          {action.fields.map((field) => (
            <ActionField
              field={field}
              key={field.name}
              onChange={(value) => setValues((current) => ({ ...current, [field.name]: value }))}
              value={values[field.name]}
            />
          ))}
          {error ? <div className="business-dialog-error" role="alert"><Icon name="alert" /> {error}</div> : null}
          <footer>
            <button className="secondary-button" disabled={busy} onClick={onClose} type="button">Cancel</button>
            <button className={`primary-button business-action-${action.tone}`} disabled={busy} type="submit">
              {busy ? 'Completing action…' : action.label}
            </button>
          </footer>
        </form>
      </section>
    </div>
  );
}

function ActionField({
  field,
  onChange,
  value,
}: {
  readonly field: HQBusinessAction['fields'][number];
  readonly onChange: (value: boolean | number | string) => void;
  readonly value: boolean | number | string | undefined;
}) {
  const fieldId = `business-field-${field.name}`;
  if (field.type === 'hidden') return null;
  if (field.type === 'checkbox') {
    return (
      <label className="business-checkbox" htmlFor={fieldId}>
        <input
          checked={Boolean(value)}
          id={fieldId}
          onChange={(event) => onChange(event.target.checked)}
          type="checkbox"
        />
        <span>{field.label}</span>
      </label>
    );
  }
  return (
    <label className="business-field" htmlFor={fieldId}>
      <span>{field.label}{field.required ? <b>Required</b> : null}</span>
      {field.type === 'textarea' ? (
        <textarea
          autoFocus
          id={fieldId}
          onChange={(event) => onChange(event.target.value)}
          required={field.required}
          rows={4}
          value={String(value ?? '')}
        />
      ) : field.type === 'select' ? (
        <select
          autoFocus
          id={fieldId}
          onChange={(event) => onChange(event.target.value)}
          required={field.required}
          value={String(value ?? '')}
        >
          {field.options.map((option) => <option key={option} value={option}>{titleCase(option)}</option>)}
        </select>
      ) : (
        <input
          autoFocus
          id={fieldId}
          onChange={(event) => onChange(field.type === 'number' ? Number(event.target.value) : event.target.value)}
          required={field.required}
          type={field.type}
          value={String(value ?? '')}
        />
      )}
    </label>
  );
}

function friendlyMetricValue(value: string) {
  if (!value) return '—';
  if (/^\d{4}-\d{2}-\d{2}T/.test(value)) return formatDateTime(value);
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return formatDate(value);
  return titleCase(value);
}

function StatusBadge({ value }: { readonly value: string }) {
  return <span className={`status-badge status-${statusTone(value)}`}><i /> {titleCase(value)}</span>;
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
      <a href="#access"><Icon name="settings" /> System controls</a>
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
    { key: 'controls', label: 'System controls', caption: 'Identity, security and governance', icon: 'settings' as IconName, href: '#access', type: 'HQ view' },
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

function isCurrentHqDestination(destination: string) {
  return destination === `#${viewFromHash()}`;
}

function metricValue(overview: HQOverview, label: string) {
  return overview.metrics.find((metric) => metric.label === label)?.value ?? 0;
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

function formatDate(value: string | null) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('en-KE', { day: '2-digit', month: 'short', year: 'numeric' }).format(date);
}

function formatDateTime(value: string | null) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('en-KE', {
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(date);
}

function formatBytes(value: number) {
  if (value < 1024) return `${formatNumber(value)} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function statusTone(value: string) {
  const status = value.toUpperCase();
  if (['ACTIVE', 'APPROVED', 'CLEAN', 'COMPLETED', 'DELIVERED', 'PASSED', 'PROCESSED', 'SUCCESS', 'VALID', 'VERIFIED'].includes(status)) return 'active';
  if (['BLOCKED', 'CRITICAL', 'FAILED', 'HIGH', 'INVALID', 'RECALLED', 'REJECTED', 'SUSPENDED'].includes(status)) return 'suspended';
  return 'warning';
}

function titleCase(value: string | number) {
  return String(value).replace(/[_-]+/g, ' ').toLowerCase().replace(/(^|\s)\S/g, (letter) => letter.toUpperCase());
}
