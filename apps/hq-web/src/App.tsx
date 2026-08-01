import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, FormEvent } from 'react';

import {
  matchInventoryItemByBarcode,
  verifyGoodsReceiptScan,
} from '@dawatrace/shared/dispensing/index.js';

import { AccessWorkspace } from './AccessWorkspace.js';
import { ReportsWorkspace } from './ReportsWorkspace.js';
import {
  activateCustomer,
  approveCustomer,
  approveCashMovement,
  approveStockTransfer,
  beginCustomerReview,
  CLAIM_STATES,
  confirmPasswordReset,
  createCustomer,
  createInsurer,
  createStockTransfer,
  decidePriceOverride,
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
  loadRemittances,
  loadRejections,
  loadCoverages,
  loadCustomers,
  loadPosDeviceHealth,
  loadPosRegisters,
  loadCashMovements,
  loadCashDeclarations,
  loadBusinessDays,
  loadOpenRegisterSessions,
  loadUnclosedRegisterSessions,
  loadClaims,
  loadClinicalProducts,
  loadManufacturedProducts,
  loadManufacturers,
  loadPriceBooks,
  loadPriceBookVersions,
  loadPriceBookEntries,
  loadPriceAssignments,
  loadAppliedPrices,
  loadPriceOverrides,
  loadPriceLocks,
  resolvePrice,
  resolveCashExceptionReview,
  saveTenantPriceDraft,
  setHQTenantContext,
  startCashExceptionReview,
  loadRolesDetail,
  loadUserRoles,
  loadServiceAccounts,
  loadCapabilityMatrix,
  requestPosDownload,
  requestPasswordReset,
  loadPosReleases,
  loadSystemHealth,
  probeEndpointHeartbeat,
  loadTenantSkus,
  readSession,
  reactivateCustomer,
  SignInError,
  signIn,
  signOut,
  suspendCustomer,
  transitionPriceBookVersion,
  updateGovernmentCatalogueSelection,
  loadInventoryLocations,
  loadInventoryBalances,
  loadInventoryLedger,
  loadInventoryBatches,
  loadInventoryReservations,
  loadStockTransfers,
  loadQuotations,
  loadPickingWaves,
  loadPickingTasks,
  loadPackingSessions,
  loadPackages,
  loadDeliveryRecords,
  loadSalesReturns,
  loadSalesOrderHolds,
  dispatchStockTransfer,
  receiveStockTransfer,
} from './api.js';
import type {
  ActiveSubstanceSummary,
  SystemHealth,
  PosRelease,
  PosReleaseCatalogue,
  ClaimFilters,
  ClinicalProductSummary,
  DashboardMetric,
  GovernmentCataloguePage,
  HQBusinessAction,
  HQOverview,
  HQSku,
  HQWorkItem,
  HQWorkspaceData,
  HQKnowledgeRelease,
  HQCodeSystem,
  HQValueSet,
  HQEncounter,
  HQCondition,
  HQObservation,
  HQFhirIdempotencyRecord,
  InsuranceClaim,
  Insurer,
  InsuranceRemittance,
  ClaimRejection,
  InsuranceCoverage,
  CustomerItem,
  EndpointHeartbeat,
  PosDeviceHealthItem,
  PosRegisterItem,
  CashMovementItem,
  CashDeclarationItem,
  BusinessDayItem,
  HQInventoryLocationItem,
  HQInventoryBalanceItem,
  HQInventoryLedgerItem,
  HQInventoryBatchItem,
  HQInventoryReservationItem,
  HQStockTransfer,
  HQStockTransferDraft,
  HQStockTransferReceipt,
  HQQuotationItem,
  HQPickingWaveItem,
  HQPickingTaskItem,
  HQPackingSessionItem,
  HQPackageItem,
  HQDeliveryRecordItem,
  HQSalesReturnItem,
  HQSalesOrderHoldItem,
  ManufacturedProductSummary,
  ManufacturerSummary,
  PriceBookSummary,
  PriceBookVersion,
  PriceBookEntry,
  PriceAssignment,
  AppliedPriceSnapshot,
  ManualPriceOverride,
  PriceLock,
  PriceResolutionResult,
  RoleDetail,
  UserRoleGrant,
  ServiceAccountItem,
  CapabilityMatrixData,
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
  | 'inventory'
  | 'operations'
  | 'commerce'
  | 'pricing'
  | 'cash'
  | 'insurance'
  | 'clinical'
  | 'reports'
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
  { key: 'inventory', label: 'Inventory Control', caption: 'Balances, ledger & FEFO', icon: 'inventory' },
  { key: 'operations', label: 'Procurement & Supply', caption: 'Purchase orders & GRN', icon: 'store' },
  { key: 'commerce', label: 'Sales & fulfilment', caption: 'Orders through delivery', icon: 'store' },
  { key: 'pricing', label: 'Pricing', caption: 'Branch price books', icon: 'database' },
  { key: 'cash', label: 'Cash control', caption: 'Shifts, tills and variances', icon: 'building' },
  { key: 'insurance', label: 'Insurance & Claims', caption: 'Adjudication & SHA', icon: 'insurance' },
  { key: 'clinical', label: 'Clinical governance', caption: 'Safety and standards', icon: 'clinical' },
  { key: 'reports', label: 'Reports', caption: 'Enterprise & security packs', icon: 'docs' },
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
  inventory: {
    eyebrow: 'Stock & Ledger Governance',
    title: 'Inventory Control & Stock Ledger',
    description: 'Track real-time stock balances, double-entry append-only ledger audit trails, lot batch expiries, location capabilities, and FEFO reservations.',
  },
  operations: {
    eyebrow: 'Supply operations',
    title: 'Procurement & Supply Chain',
    description: 'Track purchase requisitions, POs, goods receipt notes, supplier qualifications, and 3-way invoice matching.',
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
  reports: {
    eyebrow: 'Enterprise reporting',
    title: 'Reports & assurance packs',
    description: 'Browse the TibaTrace reporting catalogue — operational, regulatory, audit and security reports with live workspace links.',
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
  const [tenantOptions, setTenantOptions] = useState<HQOverview['network_items']>([]);
  const [selectedTenantId, setSelectedTenantId] = useState('');
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
    void (async () => {
      const user = session.user;
      if (user?.is_platform_admin) {
        setHQTenantContext('');
        const platformOverview = await loadHQOverview(controller.signal);
        setTenantOptions(platformOverview.network_items);
        const storedTenant = sessionStorage.getItem('hq-tenant-context') ?? '';
        const validStoredTenant = platformOverview.network_items.some(
          (tenant) => tenant.id === storedTenant,
        ) ? storedTenant : '';
        setSelectedTenantId(validStoredTenant);
        setHQTenantContext(validStoredTenant);
        setOverview(
          validStoredTenant
            ? await loadHQOverview(controller.signal)
            : platformOverview,
        );
        return;
      }
      const tenantId = user?.tenant_id ?? '';
      setSelectedTenantId(tenantId);
      setHQTenantContext(tenantId);
      setOverview(await loadHQOverview(controller.signal));
    })()
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason);
      });
    return () => controller.abort();
  }, [session?.authenticated, session?.user]);

  const endSession = useCallback(async () => {
    await signOut(session?.csrf_token ?? '');
    // Cleared rather than reloaded: the workspace data belongs to the person
    // who just left, and leaving it on screen while a new sign-in happens shows
    // one user another's claims.
    setOverview(null);
    setTenantOptions([]);
    setSelectedTenantId('');
    setHQTenantContext('');
    setError(null);
    setSession(await readSession());
  }, [session?.csrf_token]);

  const selectTenant = useCallback(async (tenantId: string) => {
    const previousTenant = selectedTenantId;
    setRefreshing(true);
    setRefreshFailed(false);
    setHQTenantContext(tenantId);
    setSelectedTenantId(tenantId);
    sessionStorage.setItem('hq-tenant-context', tenantId);
    try {
      setOverview(await loadHQOverview());
    } catch {
      setHQTenantContext(previousTenant);
      setSelectedTenantId(previousTenant);
      sessionStorage.setItem('hq-tenant-context', previousTenant);
      setRefreshFailed(true);
    } finally {
      setRefreshing(false);
    }
  }, [selectedTenantId]);

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
  if (error) {
    const detail = error instanceof HQApiError
      ? `Backend responded with ${error.status}. ${error.message}`
      : error instanceof Error
        ? error.message
        : undefined;
    return <Unavailable {...(detail === undefined ? {} : { detail })} />;
  }
  if (!session) return <LoadingScreen />;
  if (!session.authenticated) {
    return <AuthenticationRequired csrfToken={session.csrf_token} onSignedIn={setSession} />;
  }
  if (!overview) return <LoadingScreen />;

  return (
    <Dashboard
      csrfToken={session.csrf_token}
      isPlatformAdmin={Boolean(session.user?.is_platform_admin)}
      overview={overview}
      onSelectTenant={selectTenant}
      onSignOut={endSession}
      onRefresh={refresh}
      refreshFailed={refreshFailed}
      refreshing={refreshing}
      selectedTenantId={selectedTenantId}
      tenantOptions={tenantOptions}
    />
  );
}

function Dashboard({
  csrfToken,
  isPlatformAdmin,
  overview,
  onRefresh,
  onSelectTenant,
  onSignOut,
  refreshFailed,
  refreshing,
  selectedTenantId,
  tenantOptions,
}: {
  readonly csrfToken: string;
  readonly isPlatformAdmin: boolean;
  readonly overview: HQOverview;
  readonly onRefresh: () => Promise<void>;
  readonly onSelectTenant: (tenantId: string) => Promise<void>;
  readonly onSignOut: () => Promise<void>;
  readonly refreshFailed: boolean;
  readonly refreshing: boolean;
  readonly selectedTenantId: string;
  readonly tenantOptions: HQOverview['network_items'];
}) {
  const [activeView, setActiveView] = useState<WorkspaceView>(() => viewFromHash());
  const [workspaceData, setWorkspaceData] = useState<HQWorkspaceData | null>(null);
  const [workspaceFailed, setWorkspaceFailed] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const userMenuAnchorRef = useRef<HTMLDivElement>(null);
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
    const focus = focusFromHash();
    if (!focus) {
      window.scrollTo({ top: 0, behavior: 'smooth' });
      return undefined;
    }
    const targetId = resolveFocusTargetId(activeView, focus);
    if (!targetId) return undefined;
    const tryScroll = () => {
      const node = document.getElementById(targetId);
      if (!node) return false;
      node.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return true;
    };
    if (tryScroll()) return undefined;
    const first = window.setTimeout(tryScroll, 200);
    const second = window.setTimeout(tryScroll, 700);
    return () => {
      window.clearTimeout(first);
      window.clearTimeout(second);
    };
  }, [activeView, workspaceData, overview.generated_at]);

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

  useEffect(() => {
    if (!userMenuOpen) return;

    const closeWhenOutside = (event: PointerEvent) => {
      if (!userMenuAnchorRef.current?.contains(event.target as Node)) {
        setUserMenuOpen(false);
      }
    };
    document.addEventListener('pointerdown', closeWhenOutside);
    return () => document.removeEventListener('pointerdown', closeWhenOutside);
  }, [userMenuOpen]);

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
        <header className={`topbar${isPlatformAdmin ? ' topbar-platform' : ''}`}>
          <button className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => setMobileNavOpen(true)} type="button">
            <Icon name="menu" />
          </button>
          <div className="workspace-identity">
            <span>{overview.scope_label}</span>
            <strong>{overview.tenant_name}</strong>
          </div>
          {isPlatformAdmin ? (
            <label className="workspace-switcher">
              <span>Operating workspace</span>
              <select
                aria-label="Operating tenant workspace"
                disabled={refreshing}
                onChange={(event) => void onSelectTenant(event.target.value)}
                value={selectedTenantId}
              >
                <option value="">All tenants — platform view</option>
                {tenantOptions.map((tenant) => (
                  <option key={tenant.id} value={tenant.id}>
                    {tenant.name} · {titleCase(tenant.status)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <button className="search-trigger" onClick={() => setCommandOpen(true)} type="button">
            <Icon name="search" />
            <span>Search HQ or jump to a workspace</span>
            <kbd>⌘ K</kbd>
          </button>
          <div className="topbar-actions">
            <SystemHealthIndicator />
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
            <div className="popover-anchor account-menu-anchor" ref={userMenuAnchorRef}>
              <button
                className={`user-trigger${userMenuOpen ? ' user-trigger-open' : ''}`}
                aria-label={`${displayName(overview.user_name)} account menu, ${isPlatformAdmin ? 'platform administrator' : 'tenant operator'}`}
                aria-controls="hq-account-menu"
                aria-haspopup="true"
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
                  <small>{isPlatformAdmin ? 'Platform administrator' : 'Tenant operator'}</small>
                </div>
                <Icon name="chevron" />
              </button>
              {userMenuOpen ? (
                <UserMenu
                  overview={overview}
                  onClose={() => setUserMenuOpen(false)}
                  onSignOut={onSignOut}
                />
              ) : null}
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
          {activeView === 'inventory' ? <InventoryView csrfToken={csrfToken} overview={overview} /> : null}
          {activeView === 'operations' ? <OperationsView csrfToken={csrfToken} data={workspaceData} failed={workspaceFailed} onWorkspaceChanged={reloadWorkspace} overview={overview} /> : null}
          {activeView === 'commerce' ? <CommerceView csrfToken={csrfToken} data={workspaceData} failed={workspaceFailed} onWorkspaceChanged={reloadWorkspace} /> : null}
          {activeView === 'pricing' ? <PricingView csrfToken={csrfToken} overview={overview} /> : null}
          {activeView === 'cash' ? <CashControlView csrfToken={csrfToken} overview={overview} /> : null}
          {activeView === 'insurance' ? <InsuranceView csrfToken={csrfToken} overview={overview} /> : null}
          {activeView === 'clinical' ? <ClinicalView csrfToken={csrfToken} data={workspaceData} failed={workspaceFailed} onWorkspaceChanged={reloadWorkspace} overview={overview} /> : null}
          {activeView === 'reports' ? <ReportsWorkspace csrfToken={csrfToken} overview={overview} onNavigate={setActiveView} /> : null}
          {activeView === 'governance' ? <GovernanceView data={workspaceData} failed={workspaceFailed} /> : null}
          {activeView === 'access' ? <AccessView csrfToken={csrfToken} data={workspaceData} failed={workspaceFailed} onWorkspaceChanged={reloadWorkspace} overview={overview} /> : null}
        </main>
      </div>

      {commandOpen ? <CommandPalette onClose={() => setCommandOpen(false)} onNavigate={setActiveView} /> : null}
    </div>
  );
}

/**
 * The topbar health indicator.
 *
 * Was the fixed text "System live" beside a green dot, linked to the raw health
 * JSON. Nothing was checked, so it claimed the system was live whatever the
 * system was doing, and clicking it dropped an operator onto a JSON document.
 *
 * It now reports what the backend says, and re-checks periodically so a
 * long-open workspace does not keep showing a stale answer.
 */
const HEALTH_POLL_MS = 60_000;

const HEALTH_PRESENTATION: Readonly<Record<SystemHealth, { label: string; tone: string }>> = {
  checking: { label: 'Checking…', tone: 'checking' },
  live: { label: 'System live', tone: 'live' },
  degraded: { label: 'System degraded', tone: 'degraded' },
  unreachable: { label: 'System unreachable', tone: 'unreachable' },
};

function SystemHealthIndicator() {
  const [health, setHealth] = useState<SystemHealth>('checking');

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const check = () => {
      loadSystemHealth(controller.signal).then((result) => {
        if (!cancelled && !controller.signal.aborted) setHealth(result);
      });
    };
    check();
    const timer = window.setInterval(check, HEALTH_POLL_MS);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timer);
    };
  }, []);

  const { label, tone } = HEALTH_PRESENTATION[health];
  return (
    <span className={`health-status health-${tone}`} role="status" aria-live="polite">
      <span className="status-dot" />
      {label}
    </span>
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
        <a href="/api/docs/" target="_blank" rel="noreferrer">Open API workspace <Icon name="external" /></a>
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
          {overview.metrics.map((metric, index) => <MetricCard key={metric.label} metric={metric} index={index} onNavigate={onNavigate} />)}
      </section>

      <section className="content-grid content-grid-primary">
        <article className="panel attention-panel">
          <PanelHeader eyebrow="Operational focus" title="What needs attention" actionLabel="Open operations" onAction={() => navigateTo('operations', onNavigate)} />
          <div className="attention-list">
            {overview.attention_items.map((item) => {
              const destination = item.href?.trim() ?? '';
              const content = (
                <>
                  <span className={`attention-icon attention-${item.tone}`}>
                    <Icon name={item.tone === 'rose' ? 'alert' : item.tone === 'teal' ? 'check' : 'activity'} />
                  </span>
                  <div><strong>{item.label}</strong><p>{item.detail}</p></div>
                  <b>{formatNumber(item.value)}</b>
                  {destination && !isCurrentHqDestination(destination) ? <Icon className="attention-arrow" name="chevron" /> : null}
                </>
              );
              if (!destination || isCurrentHqDestination(destination)) {
                return <div className="attention-row" key={item.label}>{content}</div>;
              }
              return (
                <a
                  aria-label={`Open ${item.label}`}
                  className="attention-row attention-row-link"
                  href={destination}
                  key={item.label}
                  onClick={(event) => {
                    if (openHqDestination(destination, onNavigate)) event.preventDefault();
                  }}
                >
                  {content}
                </a>
              );
            })}
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
            <Stat href="#network" label="Active locations" value={summary.get('Active locations') ?? 0} onNavigate={onNavigate} />
            <Stat href="#people/practitioners" label="Practitioners" value={summary.get('Practitioners') ?? 0} onNavigate={onNavigate} />
            <Stat href="#access" label="Active users" value={summary.get('Active users') ?? 0} onNavigate={onNavigate} />
          </div>
        </article>
      </section>

      <section className="content-grid">
        <article className="panel data-panel">
          <PanelHeader eyebrow="Data estate" title="Current record coverage" />
          <div className="data-bars">
            {overview.data_summary.map((item) => (
              <DataBar
                {...(item.href === undefined ? {} : { href: item.href })}
                icon={overviewDataIcon(item.label)}
                key={item.label}
                label={item.label}
                max={largestOverviewValue(overview)}
                onNavigate={onNavigate}
                value={item.value}
              />
            ))}
          </div>
        </article>

        <article className="panel command-panel">
          <PanelHeader eyebrow="Command centre" title="Move into a workspace" />
          <div className="command-links">
            <CommandLink href="#people/customers" title="People & customers" detail="Patients, practitioners and counterparties" icon="users" onNavigate={onNavigate} />
            <CommandLink href="#catalogue/skus" title="Medicine catalogue" detail="Commercial SKUs and product master" icon="inventory" onNavigate={onNavigate} />
            <CommandLink href="#commerce/orders" title="Sales & fulfilment" detail="Quotations, orders, pick, pack and delivery" icon="store" onNavigate={onNavigate} />
            <CommandLink href="#pricing/books" title="Branch price books" detail="Price books, assignments and overrides" icon="docs" onNavigate={onNavigate} />
            <CommandLink href="#cash/tills" title="Shifts & cash control" detail="Tills, variances and forced closures" icon="activity" onNavigate={onNavigate} />
            <CommandLink href="/pos/" title="Point of sale" detail="Dispensing and sales operations" icon="store" />
            <CommandLink href="#reports" title="Reports catalogue" detail="Enterprise, audit and security packs" icon="docs" onNavigate={onNavigate} />
            <CommandLink href="#access" title="System controls" detail="Identity, security and governance" icon="settings" onNavigate={onNavigate} />
            <CommandLink href="/api/docs/" title="API workspace" detail="Integration contracts and testing" icon="docs" />
          </div>
        </article>
      </section>

      <HeartbeatsTelemetryPanel />
    </>
  );
}

interface HeartbeatNode {
  readonly id: string;
  readonly name: string;
  readonly type: 'SERVICE' | 'DEVICE';
  readonly category: string;
  readonly endpointOrHardware: string;
  readonly status: 'ONLINE' | 'DEGRADED' | 'STANDBY' | 'OFFLINE';
  readonly latencyMs: number | null;
  readonly observation: string;
  readonly lastPingSec: number;
}

const HEARTBEAT_ENDPOINTS = [
  {
    id: 'srv-001',
    name: 'API Gateway & Core Router',
    category: 'Core Infrastructure',
    endpoint: '/api/health/',
  },
  {
    id: 'srv-002',
    name: 'Kenya eTCD Master Catalogue',
    category: 'Medicines Master',
    endpoint: '/api/medicines/government-catalogue/?page_size=1',
  },
  {
    id: 'srv-003',
    name: 'Pricing & Resolution Engine',
    category: 'Commercial Pricing',
    endpoint: '/api/pricing/books/?page_size=1',
  },
  {
    id: 'srv-004',
    name: 'POS Shift & Cash Control',
    category: 'Till Custody',
    endpoint: '/api/pos/shift/registers/?page_size=1',
  },
  {
    id: 'srv-005',
    name: 'Insurance Claims Relay',
    category: 'Third-party Adjudication',
    endpoint: '/api/insurance/claims/?page_size=1',
  },
] as const;

const HEARTBEAT_POLL_MS = 60_000;
const DEVICE_OFFLINE_AFTER_MS = 5 * 60_000;

function HeartbeatsTelemetryPanel() {
  const [nodesFilter, setNodesFilter] = useState<'ALL' | 'SERVICES' | 'DEVICES'>('ALL');
  const [serviceHeartbeats, setServiceHeartbeats] = useState<readonly EndpointHeartbeat[]>([]);
  const [deviceHealth, setDeviceHealth] = useState<readonly PosDeviceHealthItem[]>([]);
  const [posRegisters, setPosRegisters] = useState<readonly PosRegisterItem[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<number | null>(null);
  const [clock, setClock] = useState(() => Date.now());
  const [telemetryError, setTelemetryError] = useState('');

  const fetchHeartbeats = useCallback(async (signal?: AbortSignal) => {
    setRefreshing(true);
    const [services, devices, registers] = await Promise.allSettled([
      Promise.all(HEARTBEAT_ENDPOINTS.map(({ endpoint }) => probeEndpointHeartbeat(endpoint, signal))),
      loadPosDeviceHealth(signal),
      // loadPosRegisters takes (tenantId, signal); passing the signal first
      // sent an AbortSignal as the tenant filter and dropped cancellation.
      loadPosRegisters('', signal),
    ]);

    if (signal?.aborted) return;
    if (services.status === 'fulfilled') setServiceHeartbeats(services.value);
    if (devices.status === 'fulfilled') setDeviceHealth(devices.value);
    if (registers.status === 'fulfilled') setPosRegisters(registers.value);

    const failedSources = [
      services.status === 'rejected' ? 'service endpoints' : '',
      devices.status === 'rejected' ? 'POS device telemetry' : '',
      registers.status === 'rejected' ? 'register directory' : '',
    ].filter(Boolean);
    setTelemetryError(failedSources.length > 0 ? `Could not refresh ${failedSources.join(', ')}.` : '');
    setLastRefreshedAt(Date.now());
    setClock(Date.now());
    setRefreshing(false);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void fetchHeartbeats(controller.signal);
    const clockInterval = window.setInterval(() => setClock(Date.now()), 1000);
    const pollInterval = window.setInterval(() => void fetchHeartbeats(controller.signal), HEARTBEAT_POLL_MS);
    return () => {
      controller.abort();
      window.clearInterval(clockInterval);
      window.clearInterval(pollInterval);
    };
  }, [fetchHeartbeats]);

  const serviceNodes: readonly HeartbeatNode[] = serviceHeartbeats.map((heartbeat, index) => {
    const endpoint = HEARTBEAT_ENDPOINTS[index];
    return {
      id: endpoint?.id ?? heartbeat.endpoint,
      name: endpoint?.name ?? heartbeat.endpoint,
      type: 'SERVICE',
      category: endpoint?.category ?? 'Application Service',
      endpointOrHardware: heartbeat.endpoint,
      status: heartbeat.status,
      latencyMs: heartbeat.latencyMs,
      observation: heartbeat.statusCode === null ? 'No HTTP response' : `HTTP ${heartbeat.statusCode}`,
      lastPingSec: secondsSince(heartbeat.checkedAt, clock),
    };
  });

  const registersByDevice = new Map(
    posRegisters.filter((register) => register.device_id).map((register) => [register.device_id, register]),
  );
  const deviceNodes: readonly HeartbeatNode[] = deviceHealth.map((device) => {
    const register = registersByDevice.get(device.device_id);
    const heartbeatAt = Date.parse(device.last_heartbeat);
    const isStale = !Number.isFinite(heartbeatAt) || clock - heartbeatAt > DEVICE_OFFLINE_AFTER_MS;
    const status = isStale || device.status === 'OFFLINE'
      ? 'OFFLINE'
      : device.status === 'OK'
        ? register?.state === 'LOCKED' ? 'STANDBY' : 'ONLINE'
        : 'DEGRADED';
    const peripheralState = [
      `Printer ${displayName(device.printer_paper_level)}`,
      device.scanner_connected ? 'Scanner connected' : 'Scanner disconnected',
    ].join(' · ');
    return {
      id: device.id,
      name: register ? `${register.code} (${register.name})` : device.device_id,
      type: 'DEVICE',
      category: displayName(device.device_type),
      endpointOrHardware: device.device_id,
      status,
      latencyMs: device.network_latency_ms,
      observation: peripheralState,
      lastPingSec: secondsSince(device.last_heartbeat, clock),
    };
  });

  const allNodes = [...serviceNodes, ...deviceNodes];
  const filteredNodes = nodesFilter === 'SERVICES'
    ? serviceNodes
    : nodesFilter === 'DEVICES'
    ? deviceNodes
    : allNodes;

  const onlineCount = allNodes.filter((n) => n.status === 'ONLINE').length;
  const standbyCount = allNodes.filter((n) => n.status === 'STANDBY').length;
  const degradedCount = allNodes.filter((n) => n.status === 'DEGRADED' || n.status === 'OFFLINE').length;
  const lastRefreshedSec = lastRefreshedAt === null ? null : Math.max(Math.floor((clock - lastRefreshedAt) / 1000), 0);

  return (
    <article className="panel heartbeats-panel" style={{ marginTop: '24px' }}>
      <PanelHeader
        eyebrow="Live Telemetry"
        title="Devices & Services Heartbeats"
        actionLabel={refreshing ? 'Ping Telemetry…' : 'Ping Telemetry'}
        onAction={() => void fetchHeartbeats()}
      />

      {telemetryError ? <p className="inline-alert" role="alert"><Icon name="alert" /> {telemetryError}</p> : null}

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px', marginBottom: '18px' }}>
        <div className="segmented" role="tablist">
          <button
            className={nodesFilter === 'ALL' ? 'segmented-option is-active' : 'segmented-option'}
            onClick={() => setNodesFilter('ALL')}
            type="button"
          >
            All Nodes ({allNodes.length})
          </button>
          <button
            className={nodesFilter === 'SERVICES' ? 'segmented-option is-active' : 'segmented-option'}
            onClick={() => setNodesFilter('SERVICES')}
            type="button"
          >
            Services ({serviceNodes.length})
          </button>
          <button
            className={nodesFilter === 'DEVICES' ? 'segmented-option is-active' : 'segmented-option'}
            onClick={() => setNodesFilter('DEVICES')}
            type="button"
          >
            POS Hardware ({deviceNodes.length})
          </button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', fontSize: '0.8125rem' }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', color: 'var(--teal-500)', fontWeight: 600 }}>
            <span className="status-dot" style={{ background: '#10b981', boxShadow: '0 0 10px #10b981' }} />
            {onlineCount} Online
          </span>
          {standbyCount > 0 ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', color: '#f59e0b', fontWeight: 600 }}>
              <span className="status-dot" style={{ background: '#f59e0b', boxShadow: '0 0 10px #f59e0b' }} />
              {standbyCount} Standby
            </span>
          ) : null}
          {degradedCount > 0 ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', color: 'var(--red-500)', fontWeight: 600 }}>
              <span className="status-dot" style={{ background: 'var(--red-500)' }} />
              {degradedCount} Needs attention
            </span>
          ) : null}
          <span style={{ color: 'var(--muted)', fontSize: '0.78rem' }}>
            {lastRefreshedSec === null ? 'Waiting for first sample' : `Sampled ${lastRefreshedSec}s ago`}
          </span>
        </div>
      </div>

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Node / Service Name</th>
              <th>Type</th>
              <th>Category / Subsystem</th>
              <th>Endpoint / Hardware ID</th>
              <th>Heartbeat Status</th>
              <th>Latency</th>
              <th>Observation</th>
              <th>Last Ping</th>
            </tr>
          </thead>
          <tbody>
            {filteredNodes.map((node) => (
              <tr key={node.id}>
                <td>
                  <strong style={{ fontSize: '0.9rem' }}>{node.name}</strong>
                </td>
                <td>
                  <span className={`reference-badge ${node.type === 'SERVICE' ? 'is-selected' : ''}`} style={{ fontSize: '0.72rem' }}>
                    {node.type}
                  </span>
                </td>
                <td><small>{node.category}</small></td>
                <td><code>{node.endpointOrHardware}</code></td>
                <td>
                  <span
                    className={`status-badge ${
                      node.status === 'ONLINE'
                        ? 'status-active'
                        : node.status === 'STANDBY'
                        ? 'status-warning'
                        : 'status-suspended'
                    }`}
                    style={{ fontSize: '0.75rem' }}
                  >
                    <i />
                    {node.status}
                  </span>
                </td>
                <td><small style={{ fontWeight: 600, color: 'var(--ink)' }}>{node.latencyMs === null ? '—' : `${node.latencyMs} ms`}</small></td>
                <td><small>{node.observation}</small></td>
                <td><small>{node.lastPingSec}s ago</small></td>
              </tr>
            ))}
            {!refreshing && filteredNodes.length === 0 ? (
              <tr>
                <td colSpan={8}>
                  <EmptyState
                    detail={nodesFilter === 'DEVICES' ? 'No POS device has submitted telemetry for this tenant.' : 'No heartbeat samples are available.'}
                    icon="activity"
                    title="No telemetry recorded"
                  />
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </article>
  );
}

type InventoryTab = 'balances' | 'ledger' | 'batches' | 'locations' | 'reservations' | 'transfers';

type StockTransferDialogMode =
  | { readonly kind: 'create' }
  | { readonly kind: 'approve'; readonly transfer: HQStockTransfer }
  | { readonly kind: 'dispatch'; readonly transfer: HQStockTransfer }
  | { readonly kind: 'receive'; readonly transfer: HQStockTransfer }
  | null;

function InventoryView({
  csrfToken,
  overview,
}: {
  readonly csrfToken: string;
  readonly overview: HQOverview;
}) {
  const selectableTenants = useMemo(
    () => overview.network_items.filter((item) => item.status === 'ACTIVE'),
    [overview.network_items],
  );
  const [tenantId, setTenantId] = useState(
    overview.tenant_id || selectableTenants[0]?.id || '',
  );
  const [tab, setTab] = useState<InventoryTab>('balances');
  const [balances, setBalances] = useState<readonly HQInventoryBalanceItem[] | null>(null);
  const [ledger, setLedger] = useState<readonly HQInventoryLedgerItem[] | null>(null);
  const [batches, setBatches] = useState<readonly HQInventoryBatchItem[] | null>(null);
  const [locations, setLocations] = useState<readonly HQInventoryLocationItem[] | null>(null);
  const [reservations, setReservations] = useState<readonly HQInventoryReservationItem[] | null>(null);
  const [transfers, setTransfers] = useState<readonly HQStockTransfer[] | null>(null);
  const [dialog, setDialog] = useState<StockTransferDialogMode>(null);
  const [notice, setNotice] = useState('');
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const nextTenantId = overview.tenant_id
      || (selectableTenants.some((tenant) => tenant.id === tenantId)
        ? tenantId
        : selectableTenants[0]?.id || '');
    if (nextTenantId !== tenantId) setTenantId(nextTenantId);
  }, [overview.tenant_id, selectableTenants, tenantId]);

  const reload = useCallback(async (signal?: AbortSignal) => {
    if (!tenantId) return;
    setLoading(true);
    setFailed(false);
    try {
      const [b, l, bt, loc, r, t] = await Promise.all([
        loadInventoryBalances(tenantId, signal),
        loadInventoryLedger(tenantId, signal),
        loadInventoryBatches(tenantId, signal),
        loadInventoryLocations(tenantId, signal),
        loadInventoryReservations(tenantId, signal),
        loadStockTransfers(tenantId, signal),
      ]);
      setBalances(b);
      setLedger(l);
      setBatches(bt);
      setLocations(loc);
      setReservations(r);
      setTransfers(t);
    } catch {
      if (!signal?.aborted) setFailed(true);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    const controller = new AbortController();
    void reload(controller.signal);
    return () => controller.abort();
  }, [reload]);

  if (!tenantId) {
    return <TenantWorkspaceRequired domain="inventory control" />;
  }

  if (loading) {
    return (
      <article className="panel">
        <PanelHeader eyebrow="Inventory Control" title="Stock & Ledger Governance" />
        <p className="panel-note">Loading authoritative inventory balances and ledger entries…</p>
      </article>
    );
  }

  if (failed) {
    return (
      <article className="panel">
        <PanelHeader eyebrow="Inventory Control" title="Stock & Ledger Governance" />
        <div className="inline-alert" role="status">
          <Icon name="alert" /> Could not load inventory control records. Verify tenant workspace session.
        </div>
      </article>
    );
  }

  return (
    <>
      {overview.is_platform_overview ? (
        <section className="procurement-scope panel">
          <div>
            <p className="eyebrow">Tenant stock authority</p>
            <h2>Inventory operating workspace</h2>
            <span>Balances, custody locations, reservations, and inter-branch transfers remain isolated to one pharmacy tenant.</span>
          </div>
          <label>
            <span>Operating tenant</span>
            <select onChange={(event) => setTenantId(event.target.value)} value={tenantId}>
              {selectableTenants.map((tenant) => (
                <option key={tenant.id} value={tenant.id}>{tenant.name}</option>
              ))}
            </select>
          </label>
        </section>
      ) : null}
      {notice ? <div className="procurement-notice" role="status"><Icon name="check" /> {notice}</div> : null}
      <section className="metric-grid inventory-authority-strip" aria-label="Tenant stock authority summary">
        <button className="metric-card metric-teal metric-card-button" onClick={() => setTab('balances')} type="button">
          <div className="metric-top"><span><Icon name="inventory" /></span><small>Open balances</small></div>
          <strong>{formatNumber(balances?.length ?? 0)}</strong>
          <p>Stock balances</p>
          <small>Projected quantity by location, SKU and lot</small>
        </button>
        <button className="metric-card metric-violet metric-card-button" onClick={() => setTab('batches')} type="button">
          <div className="metric-top"><span><Icon name="database" /></span><small>Open batches</small></div>
          <strong>{formatNumber(batches?.filter((batch) => batch.quality_status === 'RELEASED').length ?? 0)}</strong>
          <p>FEFO-ready batches</p>
          <small>{formatNumber(batches?.filter((batch) => batch.quality_status !== 'RELEASED').length ?? 0)} on quality hold</small>
        </button>
        <button className="metric-card metric-amber metric-card-button" onClick={() => setTab('reservations')} type="button">
          <div className="metric-top"><span><Icon name="shield" /></span><small>Open reservations</small></div>
          <strong>{formatNumber(reservations?.length ?? 0)}</strong>
          <p>Allocated stock</p>
          <small>Held against dispensing and sales demand</small>
        </button>
        <button className="metric-card metric-navy metric-card-button" onClick={() => setTab('transfers')} type="button">
          <div className="metric-top"><span><Icon name="arrow" /></span><small>Open transfers</small></div>
          <strong>{formatNumber(transfers?.length ?? 0)}</strong>
          <p>Stock transfers</p>
          <small>{formatNumber(locations?.length ?? 0)} custody locations</small>
        </button>
      </section>
      <article className="panel inventory-workspace">
        <PanelHeader eyebrow="Stock & Ledger Governance" title="Inventory Control & Stock Ledger" />
        <p className="panel-note">
          Tenant stock authority is absolute: balances, ledger entries, batches, reservations and transfers
          never mix across pharmacies. Every quantity change is append-only in the ledger.
        </p>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px', marginBottom: '20px' }}>
          <div className="segmented" role="tablist">
          <button
            className={tab === 'balances' ? 'segmented-option is-active' : 'segmented-option'}
            onClick={() => setTab('balances')}
            type="button"
          >
            Stock balances ({balances?.length ?? 0})
          </button>
          <button
            className={tab === 'ledger' ? 'segmented-option is-active' : 'segmented-option'}
            onClick={() => setTab('ledger')}
            type="button"
          >
            Inventory ledger ({ledger?.length ?? 0})
          </button>
          <button
            className={tab === 'batches' ? 'segmented-option is-active' : 'segmented-option'}
            onClick={() => setTab('batches')}
            type="button"
          >
            Batches &amp; expiries ({batches?.length ?? 0})
          </button>
          <button
            className={tab === 'locations' ? 'segmented-option is-active' : 'segmented-option'}
            onClick={() => setTab('locations')}
            type="button"
          >
            Locations ({locations?.length ?? 0})
          </button>
          <button
            className={tab === 'reservations' ? 'segmented-option is-active' : 'segmented-option'}
            onClick={() => setTab('reservations')}
            type="button"
          >
            Reservations ({reservations?.length ?? 0})
          </button>
          <button
            className={tab === 'transfers' ? 'segmented-option is-active' : 'segmented-option'}
            onClick={() => setTab('transfers')}
            type="button"
          >
            Transfers ({transfers?.length ?? 0})
          </button>
          </div>
        </div>

      {tab === 'balances' && (
        <>
          <p className="panel-note">
            Real-time projected inventory quantities per location, SKU, and lot batch. Available stock enforces strict allocation rules.
          </p>
          {balances && balances.length > 0 ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>SKU / Product</th>
                    <th>Location</th>
                    <th>Batch Lot</th>
                    <th>On Hand</th>
                    <th>Reserved</th>
                    <th>Quarantined</th>
                    <th>Damaged</th>
                    <th>Expired</th>
                    <th>Available Quantity</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {balances.map((b) => (
                    <tr key={b.id}>
                      <td>
                        <strong>{b.sku_name || b.sku_code || 'SKU Item'}</strong>
                        {b.sku_code ? <small className="row-detail"><code>{b.sku_code}</code></small> : null}
                      </td>
                      <td><small>{b.location_name || 'Main Location'}</small></td>
                      <td><code>{b.batch_number || '—'}</code></td>
                      <td><strong>{b.on_hand}</strong></td>
                      <td><small style={{ color: 'var(--amber-700)' }}>{b.reserved}</small></td>
                      <td><small style={{ color: b.quarantined !== '0' ? '#f59e0b' : 'var(--muted)' }}>{b.quarantined}</small></td>
                      <td><small style={{ color: b.damaged !== '0' ? '#ef4444' : 'var(--muted)' }}>{b.damaged}</small></td>
                      <td><small style={{ color: b.expired !== '0' ? '#ef4444' : 'var(--muted)' }}>{b.expired}</small></td>
                      <td>
                        <strong style={{ color: 'var(--teal-500)', fontSize: '0.95rem' }}>{b.available}</strong>
                      </td>
                      <td>
                        <span className={`status-badge ${b.quality_status === 'RELEASED' || !b.quality_status ? 'status-active' : 'status-warning'}`}>
                          <i />
                          {b.quality_status || 'RELEASED'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              icon="inventory"
              title="No stock balances found"
              detail="Stock balances appear here automatically as goods receipts and inventory entries are posted."
            />
          )}
        </>
      )}

      {tab === 'ledger' && (
        <>
          <p className="panel-note">
            Immutable, append-only inventory transaction ledger. Every stock movement, receipt, issue, or transfer produces an auditable entry.
          </p>
          {ledger && ledger.length > 0 ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Timestamp</th>
                    <th>Entry Type</th>
                    <th>SKU Code</th>
                    <th>Location</th>
                    <th>Batch Lot</th>
                    <th>Quantity Delta</th>
                    <th>Base Delta</th>
                    <th>Source Document</th>
                    <th>Reason / Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {ledger.map((l) => (
                    <tr key={l.id}>
                      <td><small>{formatDate(l.transaction_timestamp)}</small></td>
                      <td>
                        <span className="reference-badge is-selected" style={{ fontSize: '0.72rem' }}>
                          {l.entry_type}
                        </span>
                      </td>
                      <td><code>{l.sku_code || '—'}</code></td>
                      <td><small>{l.location_name || 'Main Location'}</small></td>
                      <td><code>{l.batch_number || '—'}</code></td>
                      <td>
                        <strong style={{ color: parseFloat(l.quantity_delta) >= 0 ? 'var(--teal-500)' : '#ef4444' }}>
                          {parseFloat(l.quantity_delta) >= 0 ? `+${l.quantity_delta}` : l.quantity_delta} {l.unit}
                        </strong>
                      </td>
                      <td><small>{l.base_quantity_delta}</small></td>
                      <td>
                        <small><code>{l.source_document_type}</code> #{l.source_document_id.slice(0, 8)}</small>
                      </td>
                      <td><small>{l.reason_code || l.notes || '—'}</small></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              icon="database"
              title="No ledger entries found"
              detail="Immutable inventory ledger audit logs will appear here when inventory transactions occur."
            />
          )}
        </>
      )}

      {tab === 'batches' && (
        <>
          <p className="panel-note">
            Manufacturer batch lot tracking, quality disposition status, and FEFO expiry management.
          </p>
          {batches && batches.length > 0 ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Manufacturer Batch #</th>
                    <th>SKU Code</th>
                    <th>Manufacture Date</th>
                    <th>Expiry Date</th>
                    <th>Quality Status</th>
                    <th>Recall Status</th>
                  </tr>
                </thead>
                <tbody>
                  {batches.map((bt) => (
                    <tr key={bt.id}>
                      <td><strong><code>{bt.manufacturer_batch_number}</code></strong></td>
                      <td><code>{bt.sku_code || '—'}</code></td>
                      <td><small>{bt.manufacture_date ? formatDate(bt.manufacture_date) : '—'}</small></td>
                      <td>
                        <strong style={{ color: 'var(--teal-500)' }}>{formatDate(bt.expiry_date)}</strong>
                      </td>
                      <td>
                        <span className={`status-badge ${bt.quality_status === 'RELEASED' ? 'status-active' : 'status-warning'}`}>
                          <i />
                          {bt.quality_status}
                        </span>
                      </td>
                      <td>
                        <span className={`reference-badge ${bt.recall_status === 'NONE' ? '' : 'is-selected'}`}>
                          {bt.recall_status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              icon="store"
              title="No lot batches found"
              detail="Lot batches and expiry dates are registered automatically during goods receipt inspection."
            />
          )}
        </>
      )}

      {tab === 'locations' && (
        <>
          <p className="panel-note">
            Physical and logical inventory locations, zone classifications, and storage capabilities.
          </p>
          {locations && locations.length > 0 ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Location Code</th>
                    <th>Name</th>
                    <th>Type</th>
                    <th>Branch</th>
                    <th>Capabilities</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {locations.map((loc) => (
                    <tr key={loc.id}>
                      <td><strong><code>{loc.location_code}</code></strong></td>
                      <td><strong>{loc.name}</strong></td>
                      <td>
                        <span className="reference-badge" style={{ fontSize: '0.72rem' }}>
                          {loc.location_type}
                        </span>
                      </td>
                      <td><small>{loc.branch_name || 'Main Branch'}</small></td>
                      <td>
                        <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                          {loc.cold_chain_capability ? <span className="positive-chip" style={{ fontSize: '0.65rem' }}>Cold Chain</span> : null}
                          {loc.controlled_drug_capability ? <span className="positive-chip" style={{ fontSize: '0.65rem', background: 'rgba(168, 85, 247, 0.16)', color: '#a855f7' }}>Vault</span> : null}
                          {loc.quarantine_capability ? <span className="positive-chip" style={{ fontSize: '0.65rem', background: 'rgba(245, 158, 11, 0.16)', color: '#f59e0b' }}>Quarantine</span> : null}
                          {!loc.cold_chain_capability && !loc.controlled_drug_capability && !loc.quarantine_capability ? <small>Standard</small> : null}
                        </div>
                      </td>
                      <td>
                        <span className={`status-badge ${loc.status === 'ACTIVE' ? 'status-active' : 'status-warning'}`}>
                          <i />
                          {loc.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              icon="building"
              title="No locations configured"
              detail="Storage locations and pharmacy dispensaries appear here."
            />
          )}
        </>
      )}

      {tab === 'reservations' && (
        <>
          <p className="panel-note">
            Active stock reservations locking quantities for sales orders, preauthorisations, or clinical dispensing.
          </p>
          {reservations && reservations.length > 0 ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Reservation # / ID</th>
                    <th>SKU Code</th>
                    <th>Location</th>
                    <th>Requested Qty</th>
                    <th>Allocated Qty</th>
                    <th>Status</th>
                    <th>Created At</th>
                  </tr>
                </thead>
                <tbody>
                  {reservations.map((r) => (
                    <tr key={r.id}>
                      <td><strong><code>{r.id.slice(0, 8)}</code></strong></td>
                      <td><code>{r.sku_code || '—'}</code></td>
                      <td><small>{r.location_name || 'Main Location'}</small></td>
                      <td><small>{r.requested_quantity}</small></td>
                      <td><strong style={{ color: 'var(--teal-500)' }}>{r.allocated_quantity}</strong></td>
                      <td>
                        <span className={`status-badge ${r.status === 'ALLOCATED' || r.status === 'FULFILLED' ? 'status-active' : 'status-warning'}`}>
                          <i />
                          {r.status}
                        </span>
                      </td>
                      <td><small>{formatDate(r.created_at)}</small></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              icon="check"
              title="No active reservations"
              detail="Stock reservations appear here when orders or dispensing requests lock available inventory."
            />
          )}
        </>
      )}

        {tab === 'transfers' ? (
          <StockTransfersTab
            balances={balances ?? []}
            locations={locations ?? []}
            onDialog={setDialog}
            transfers={transfers ?? []}
          />
        ) : null}
      </article>
      {dialog ? (
        <StockTransferDialog
          balances={balances ?? []}
          csrfToken={csrfToken}
          dialog={dialog}
          locations={locations ?? []}
          onClose={() => setDialog(null)}
          onSaved={async (message) => {
            setDialog(null);
            setNotice(message);
            await reload();
          }}
          tenantId={tenantId}
        />
      ) : null}
    </>
  );
}

function StockTransfersTab({
  balances,
  locations,
  onDialog,
  transfers,
}: {
  readonly balances: readonly HQInventoryBalanceItem[];
  readonly locations: readonly HQInventoryLocationItem[];
  readonly onDialog: (dialog: StockTransferDialogMode) => void;
  readonly transfers: readonly HQStockTransfer[];
}) {
  const activeTransfers = transfers.filter((transfer) => !['RECEIVED', 'CLOSED', 'CANCELLED', 'REJECTED'].includes(transfer.status));
  const inTransit = transfers.filter((transfer) => ['DISPATCHED', 'IN_TRANSIT', 'PARTIALLY_RECEIVED'].includes(transfer.status));
  const canCreate = locations.filter((location) => location.status === 'ACTIVE').length >= 2
    && balances.some((balance) => Number(balance.available) > 0);

  return (
    <>
      <div className="stock-transfer-heading">
        <div>
          <p className="eyebrow">Inter-branch custody</p>
          <h2>Stock transfer register</h2>
          <p className="panel-note">
            Request stock, approve independently, dispatch by FEFO batch, and acknowledge receipt into the destination ledger.
          </p>
        </div>
        <button
          className="primary-button"
          disabled={!canCreate}
          onClick={() => onDialog({ kind: 'create' })}
          type="button"
        >
          <Icon name="inventory" />
          New transfer request
        </button>
      </div>

      <section className="metric-grid network-metrics" aria-label="Stock transfer totals">
        <SummaryCard icon="docs" label="Total transfers" value={transfers.length} detail="Complete custody history" />
        <SummaryCard icon="alert" label="Open workflow" value={activeTransfers.length} detail="Awaiting approval, movement, or receipt" tone="amber" />
        <SummaryCard icon="activity" label="In transit" value={inTransit.length} detail="Stock outside branch custody" tone="rose" />
        <SummaryCard icon="check" label="Received" value={transfers.filter((transfer) => transfer.status === 'RECEIVED').length} detail="Destination acknowledged" tone="teal" />
      </section>

      {!canCreate ? (
        <div className="inline-alert" role="status">
          <Icon name="alert" />
          Configure at least two active inventory locations and release stock before creating a transfer.
        </div>
      ) : null}

      {transfers.length === 0 ? (
        <EmptyState
          detail="Create the first governed stock movement between active inventory locations."
          icon="inventory"
          title="No stock transfers"
        />
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Transfer</th>
                <th>Route</th>
                <th>Lines</th>
                <th>Requested by</th>
                <th>Status</th>
                <th>Movement</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {transfers.map((transfer) => (
                <tr key={transfer.id}>
                  <td>
                    <strong><code>{transfer.transfer_number}</code></strong>
                    <small className="row-detail">{transfer.document_reference || formatDate(transfer.created_at)}</small>
                  </td>
                  <td>
                    <strong>{transfer.source_location_name}</strong>
                    <small className="row-detail">to {transfer.destination_location_name}</small>
                  </td>
                  <td>
                    <strong>{transfer.lines.length}</strong>
                    <small className="row-detail">
                      {transfer.lines.map((line) => `${line.sku_code} · ${line.requested_quantity} ${line.unit}`).join(', ')}
                    </small>
                  </td>
                  <td><small>{transfer.requested_by_username || 'System'}</small></td>
                  <td><StatusBadge value={transfer.status} /></td>
                  <td>
                    <small>
                      {transfer.dispatch_timestamp ? `Dispatched ${formatDate(transfer.dispatch_timestamp)}` : 'Not dispatched'}
                    </small>
                    {transfer.receipt_timestamp ? <small className="row-detail">Received {formatDate(transfer.receipt_timestamp)}</small> : null}
                  </td>
                  <td>
                    {transfer.status === 'SUBMITTED' ? (
                      <button className="secondary-button" onClick={() => onDialog({ kind: 'approve', transfer })} type="button">
                        Approve
                      </button>
                    ) : null}
                    {transfer.status === 'APPROVED' ? (
                      <button className="primary-button" onClick={() => onDialog({ kind: 'dispatch', transfer })} type="button">
                        Dispatch
                      </button>
                    ) : null}
                    {['DISPATCHED', 'IN_TRANSIT', 'PARTIALLY_RECEIVED'].includes(transfer.status) ? (
                      <button className="primary-button" onClick={() => onDialog({ kind: 'receive', transfer })} type="button">
                        Receive
                      </button>
                    ) : null}
                    {['RECEIVED', 'CLOSED', 'CANCELLED', 'REJECTED'].includes(transfer.status) ? (
                      <span className="muted-cell">No action due</span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

interface StockTransferDraftLine {
  readonly key: string;
  readonly sku: string;
  readonly quantity: string;
}

interface StockTransferReceiptDraftLine {
  readonly key: string;
  readonly lineId: string;
  readonly skuCode: string;
  readonly batchId: string;
  readonly batchNumber: string;
  readonly skuBarcode: string;
  readonly remaining: string;
  readonly quantity: string;
  readonly damaged: string;
  readonly discrepancyReason: string;
  readonly unit: string;
}

function newTransferReference(prefix: string): string {
  const token = globalThis.crypto?.randomUUID?.().replace(/-/g, '').slice(0, 10).toUpperCase()
    ?? Date.now().toString(36).toUpperCase();
  return `${prefix}-${token}`;
}

function StockTransferDialog({
  balances,
  csrfToken,
  dialog,
  locations,
  onClose,
  onSaved,
  tenantId,
}: {
  readonly balances: readonly HQInventoryBalanceItem[];
  readonly csrfToken: string;
  readonly dialog: Exclude<StockTransferDialogMode, null>;
  readonly locations: readonly HQInventoryLocationItem[];
  readonly onClose: () => void;
  readonly onSaved: (message: string) => Promise<void>;
  readonly tenantId: string;
}) {
  const activeLocations = locations.filter((location) => location.status === 'ACTIVE');

  const initialSource = activeLocations.find((location) => balances.some(
    (balance) => balance.location === location.id && Number(balance.available) > 0,
  ))?.id ?? activeLocations[0]?.id ?? '';
  const [transferNumber, setTransferNumber] = useState(() => newTransferReference('TRF'));
  const [sourceLocation, setSourceLocation] = useState(initialSource);
  const [destinationLocation, setDestinationLocation] = useState(
    activeLocations.find((location) => location.id !== initialSource)?.id ?? '',
  );
  const [reason, setReason] = useState('');
  const [documentReference, setDocumentReference] = useState('');
  const [draftLines, setDraftLines] = useState<readonly StockTransferDraftLine[]>([
    { key: newTransferReference('LINE'), quantity: '', sku: '' },
  ]);
  const [receiptLines, setReceiptLines] = useState<readonly StockTransferReceiptDraftLine[]>(() => (
    dialog.kind === 'receive'
      ? dialog.transfer.lines.flatMap((line) => line.dispatch_allocations
        .filter((allocation) => Number(allocation.remaining_quantity) > 0)
        .map((allocation) => ({
          batchId: allocation.batch_id,
          batchNumber: allocation.batch_number,
          damaged: '0',
          discrepancyReason: '',
          key: `${line.id}:${allocation.batch_id}`,
          lineId: line.id,
          quantity: '0',
          remaining: allocation.remaining_quantity,
          skuBarcode: line.sku_barcode || '',
          skuCode: line.sku_code,
          unit: line.unit,
        })))
      : []
  ));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [scanInput, setScanInput] = useState('');
  const [scanNotice, setScanNotice] = useState('');
  const [scanFailed, setScanFailed] = useState(false);
  const [receiveScanInput, setReceiveScanInput] = useState('');
  const [receiveScanNotice, setReceiveScanNotice] = useState('');
  const [receiveScanFailed, setReceiveScanFailed] = useState(false);

  const availableSkus = useMemo(() => {
    const bySku = new Map<string, {
      available: number;
      barcode: string;
      code: string;
      name: string;
    }>();
    balances
      .filter((balance) => balance.location === sourceLocation && Number(balance.available) > 0)
      .forEach((balance) => {
        const current = bySku.get(balance.sku);
        bySku.set(balance.sku, {
          available: (current?.available ?? 0) + Number(balance.available),
          barcode: balance.sku_barcode || current?.barcode || '',
          code: balance.sku_code || balance.sku,
          name: balance.sku_name || balance.sku_code || 'Stock item',
        });
      });
    return [...bySku.entries()].map(([id, value]) => ({ id, ...value }));
  }, [balances, sourceLocation]);

  const handleScan = (inputVal: string) => {
    if (!inputVal.trim()) return;
    const match = matchInventoryItemByBarcode(
      inputVal,
      availableSkus.map((sku) => ({ barcode: sku.barcode, id: sku.id, skuCode: sku.code })),
    );
    if (match.status !== 'MATCHED' || !match.itemId) {
      setScanFailed(true);
      setScanNotice(match.status === 'AMBIGUOUS'
        ? 'This code maps to more than one released SKU. Correct the catalogue mapping before transfer.'
        : 'No released stock at the selected source matches this barcode or SKU code.');
      return;
    }

    const parsed = match.parsedBarcode;
    const matched = availableSkus.find((sku) => sku.id === match.itemId)!;
    const existing = draftLines.find((line) => line.sku === matched.id);
    const nextQuantity = Number(existing?.quantity || 0) + 1;
    if (nextQuantity > matched.available) {
      setScanFailed(true);
      setScanNotice(`${matched.code} has only ${matched.available} available at this source.`);
      return;
    }

    setDraftLines((current) => {
      if (existing) {
        return current.map((line) => (
          line.key === existing.key ? { ...line, quantity: String(nextQuantity) } : line
        ));
      }
      const emptyIndex = current.findIndex((line) => !line.sku);
      if (emptyIndex >= 0) {
        return current.map((line, index) => (
          index === emptyIndex ? { ...line, sku: matched.id, quantity: '1' } : line
        ));
      }
      return [
        ...current,
        { key: newTransferReference('LINE'), sku: matched.id, quantity: '1' },
      ];
    });
    const trace = [
      parsed.batchNumber ? `batch ${parsed.batchNumber}` : '',
      parsed.expiryDateIso ? `expiry ${parsed.expiryDateIso}` : '',
    ].filter(Boolean).join(' · ');
    setScanFailed(false);
    setScanNotice(
      `${matched.code} added from ${parsed.format === 'GS1_DATAMATRIX' ? 'GS1 DataMatrix' : 'barcode / SKU'}${trace ? ` · ${trace}` : ''}. Dispatch still allocates the authoritative FEFO batch.`,
    );
    setScanInput('');
  };

  const handleReceiveScan = (inputVal: string) => {
    if (!inputVal.trim()) return;
    const verification = verifyGoodsReceiptScan({
      scannedInput: inputVal,
      expectedLines: receiptLines.map((l) => ({
        barcode: l.skuBarcode,
        lineKey: l.key,
        skuCode: l.skuCode,
        expectedQuantity: Number(l.remaining),
        acceptedQuantity: Number(l.quantity || 0),
        batchNumber: l.batchNumber,
      })),
    });

    if (
      verification.matchFound
      && !verification.discrepancyDetected
      && verification.matchedLineKey
    ) {
      setReceiptLines((current) =>
        current.map((line) =>
          line.key === verification.matchedLineKey
            ? { ...line, quantity: String(verification.updatedAcceptedQuantity) }
            : line
        )
      );
      setReceiveScanFailed(false);
      setReceiveScanNotice(verification.statusNote);
      setReceiveScanInput('');
    } else {
      setReceiveScanFailed(true);
      setReceiveScanNotice(verification.statusNote);
    }
  };

  const updateDraftLine = (key: string, values: Partial<StockTransferDraftLine>) => {
    setDraftLines((current) => current.map((line) => (
      line.key === key ? { ...line, ...values } : line
    )));
  };

  const updateReceiptLine = (key: string, values: Partial<StockTransferReceiptDraftLine>) => {
    setReceiptLines((current) => current.map((line) => (
      line.key === key ? { ...line, ...values } : line
    )));
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      if (dialog.kind === 'create') {
        const payload: HQStockTransferDraft = {
          destination_location: destinationLocation,
          document_reference: documentReference.trim(),
          lines: draftLines.map((line) => ({ quantity: line.quantity, sku: line.sku })),
          reason: reason.trim(),
          source_location: sourceLocation,
          transfer_number: transferNumber.trim(),
        };
        await createStockTransfer(payload, tenantId, csrfToken);
        await onSaved(`Transfer ${transferNumber} submitted for independent approval.`);
        return;
      }
      if (dialog.kind === 'approve') {
        await approveStockTransfer(dialog.transfer.id, tenantId, csrfToken);
        await onSaved(`Transfer ${dialog.transfer.transfer_number} approved.`);
        return;
      }
      if (dialog.kind === 'dispatch') {
        await dispatchStockTransfer(dialog.transfer.id, tenantId, csrfToken);
        await onSaved(`Transfer ${dialog.transfer.transfer_number} dispatched by FEFO allocation.`);
        return;
      }
      const payload: HQStockTransferReceipt = {
        idempotency_key: newTransferReference('RCV'),
        lines: receiptLines
          .filter((line) => Number(line.quantity) + Number(line.damaged) > 0)
          .map((line) => ({
            batch_id: line.batchId,
            damaged: line.damaged || '0',
            discrepancy_reason: line.discrepancyReason.trim(),
            line_id: line.lineId,
            quantity: line.quantity || '0',
          })),
      };
      await receiveStockTransfer(dialog.transfer.id, payload, tenantId, csrfToken);
      await onSaved(`Receipt recorded for transfer ${dialog.transfer.transfer_number}.`);
    } catch (reasonCaught) {
      setError(reasonCaught instanceof Error ? reasonCaught.message : 'The stock transfer action failed.');
    } finally {
      setBusy(false);
    }
  };

  const title = dialog.kind === 'create'
    ? 'Create stock transfer'
    : dialog.kind === 'approve'
      ? 'Approve stock transfer'
      : dialog.kind === 'dispatch'
        ? 'Dispatch stock transfer'
        : 'Receive stock transfer';
  const transfer = dialog.kind === 'create' ? null : dialog.transfer;
  const submitLabel = dialog.kind === 'create'
    ? 'Submit transfer'
    : dialog.kind === 'approve'
      ? 'Approve transfer'
      : dialog.kind === 'dispatch'
        ? 'Allocate & dispatch'
        : 'Post receipt';
  const receiptInvalid = dialog.kind === 'receive' && (
    receiptLines.length === 0
    || receiptLines.every((line) => Number(line.quantity) + Number(line.damaged) <= 0)
    || receiptLines.some((line) => {
      const recorded = Number(line.quantity) + Number(line.damaged);
      const remaining = Number(line.remaining);
      return recorded > remaining
        || ((recorded < remaining || Number(line.damaged) > 0) && !line.discrepancyReason.trim());
    })
  );

  return (
    <div className="business-dialog-backdrop" role="presentation">
      <section aria-labelledby="stock-transfer-dialog-title" aria-modal="true" className="business-dialog stock-transfer-dialog" role="dialog">
        <header>
          <div>
            <p className="eyebrow">Inter-branch custody workflow</p>
            <h2 id="stock-transfer-dialog-title">{title}</h2>
          </div>
          <button aria-label="Close dialog" disabled={busy} onClick={onClose} type="button">
            <Icon name="close" />
          </button>
        </header>
        {transfer ? (
          <div className="business-dialog-record">
            <div>
              <code>{transfer.transfer_number}</code>
              <strong>{transfer.source_location_name} → {transfer.destination_location_name}</strong>
              <small>{transfer.lines.length} stock line{transfer.lines.length === 1 ? '' : 's'} · {titleCase(transfer.status)}</small>
            </div>
          </div>
        ) : null}
        <p className="business-dialog-confirm">
          <Icon name={dialog.kind === 'dispatch' ? 'alert' : 'shield'} />
          {dialog.kind === 'create'
            ? 'Submission records the requester and routes the movement for independent approval.'
            : dialog.kind === 'approve'
              ? 'The requester cannot approve their own transfer. Your identity is retained in the custody trail.'
              : dialog.kind === 'dispatch'
                ? 'Dispatch allocates released stock by earliest expiry and posts immutable TRANSFER_OUT ledger entries.'
                : 'Receipt posts accepted stock to destination custody and damaged stock to its controlled holding location.'}
        </p>
        <form onSubmit={(event) => void submit(event)}>
          {dialog.kind === 'create' ? (
            <>
              <div className="stock-transfer-form-grid">
                <label className="business-field">
                  <span>Transfer number</span>
                  <input maxLength={100} onChange={(event) => setTransferNumber(event.target.value)} required value={transferNumber} />
                </label>
                <label className="business-field">
                  <span>Request reference</span>
                  <input maxLength={255} onChange={(event) => setDocumentReference(event.target.value)} placeholder="Optional requisition or memo" value={documentReference} />
                </label>
                <label className="business-field">
                  <span>Source location</span>
                  <select
                    onChange={(event) => {
                      const nextSource = event.target.value;
                      setSourceLocation(nextSource);
                      if (destinationLocation === nextSource) {
                        setDestinationLocation(activeLocations.find((location) => location.id !== nextSource)?.id ?? '');
                      }
                      setDraftLines([{ key: newTransferReference('LINE'), quantity: '', sku: '' }]);
                    }}
                    required
                    value={sourceLocation}
                  >
                    {activeLocations.map((location) => (
                      <option key={location.id} value={location.id}>{location.branch_name} · {location.name}</option>
                    ))}
                  </select>
                </label>
                <label className="business-field">
                  <span>Destination location</span>
                  <select onChange={(event) => setDestinationLocation(event.target.value)} required value={destinationLocation}>
                    {activeLocations.filter((location) => location.id !== sourceLocation).map((location) => (
                      <option key={location.id} value={location.id}>{location.branch_name} · {location.name}</option>
                    ))}
                  </select>
                </label>
              </div>
              <label className="business-field">
                <span>Transfer reason</span>
                <textarea onChange={(event) => setReason(event.target.value)} placeholder="Why stock is moving and who requested the rebalance" required rows={3} value={reason} />
              </label>
              <div className="stock-transfer-scan-panel">
                <div>
                  <span className="stock-transfer-scan-title"><Icon name="search" /> Scan released stock</span>
                  <small>GS1 DataMatrix, registered barcode, or exact SKU code</small>
                </div>
                <div className="stock-transfer-scan-control">
                  <input
                    aria-label="Scan released stock barcode or SKU"
                    onChange={(e) => setScanInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        handleScan(scanInput);
                      }
                    }}
                    placeholder="Scan GS1, barcode, or SKU"
                    type="text"
                    value={scanInput}
                  />
                  <button
                    className="secondary-button"
                    disabled={!scanInput.trim()}
                    onClick={() => handleScan(scanInput)}
                    type="button"
                  >
                    Scan & Add
                  </button>
                </div>
                {scanNotice ? (
                  <p className={scanFailed ? 'stock-transfer-scan-note is-error' : 'stock-transfer-scan-note'} role={scanFailed ? 'alert' : 'status'}>
                    {scanNotice}
                  </p>
                ) : null}
              </div>
              <div className="stock-transfer-lines">
                <div className="stock-transfer-lines-heading">
                  <strong>Stock lines</strong>
                  <button
                    className="secondary-button"
                    disabled={draftLines.length >= availableSkus.length}
                    onClick={() => setDraftLines((current) => [
                      ...current,
                      { key: newTransferReference('LINE'), quantity: '', sku: '' },
                    ])}
                    type="button"
                  >
                    Add line
                  </button>
                </div>
                {draftLines.map((line, index) => {
                  const selectedSku = availableSkus.find((sku) => sku.id === line.sku);
                  return (
                    <div className="stock-transfer-line" key={line.key}>
                      <label className="business-field">
                        <span>SKU {index + 1}</span>
                        <select onChange={(event) => updateDraftLine(line.key, { sku: event.target.value })} required value={line.sku}>
                          <option value="">Select released stock</option>
                          {availableSkus.map((sku) => (
                            <option
                              disabled={draftLines.some((candidate) => candidate.key !== line.key && candidate.sku === sku.id)}
                              key={sku.id}
                              value={sku.id}
                            >
                              {sku.code} · {sku.name} · {sku.available} available
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="business-field">
                        <span>Quantity {selectedSku ? <b>Max {selectedSku.available}</b> : null}</span>
                        <input
                          max={selectedSku?.available}
                          min="0.0001"
                          onChange={(event) => updateDraftLine(line.key, { quantity: event.target.value })}
                          required
                          step="0.0001"
                          type="number"
                          value={line.quantity}
                        />
                      </label>
                      <button
                        aria-label={`Remove stock line ${index + 1}`}
                        className="danger-link"
                        disabled={draftLines.length === 1}
                        onClick={() => setDraftLines((current) => current.filter((candidate) => candidate.key !== line.key))}
                        type="button"
                      >
                        Remove
                      </button>
                    </div>
                  );
                })}
              </div>
            </>
          ) : null}
          {dialog.kind === 'receive' ? (
            <div className="stock-transfer-lines">
              <div className="stock-transfer-scan-panel">
                <div>
                  <span className="stock-transfer-scan-title"><Icon name="check" /> Verify received stock</span>
                  <small>Each accepted unit must match the transfer SKU and, when encoded, its batch.</small>
                </div>
                <div className="stock-transfer-scan-control">
                  <input
                    aria-label="Verify received stock barcode"
                    onChange={(e) => setReceiveScanInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        handleReceiveScan(receiveScanInput);
                      }
                    }}
                    placeholder="Scan the received unit"
                    type="text"
                    value={receiveScanInput}
                  />
                  <button
                    className="secondary-button"
                    disabled={!receiveScanInput.trim()}
                    onClick={() => handleReceiveScan(receiveScanInput)}
                    type="button"
                  >
                    Verify Scan
                  </button>
                </div>
                {receiveScanNotice ? (
                  <p className={receiveScanFailed ? 'stock-transfer-scan-note is-error' : 'stock-transfer-scan-note'} role={receiveScanFailed ? 'alert' : 'status'}>
                    {receiveScanNotice}
                  </p>
                ) : null}
              </div>
              {receiptLines.length === 0 ? (
                <div className="inline-alert" role="status"><Icon name="check" /> No dispatched quantity remains to receive.</div>
              ) : receiptLines.map((line) => (
                  <div className="stock-transfer-receipt-line" key={line.key}>
                    <div>
                      <strong>{line.skuCode}</strong>
                      <small>Batch {line.batchNumber} · {line.remaining} remaining</small>
                      <small>Authoritative unit: {line.unit || 'UNIT'}</small>
                    </div>
                    <label className="business-field">
                      <span>Accepted</span>
                      <input
                        max={line.remaining}
                        min="0"
                        onChange={(event) => updateReceiptLine(line.key, { quantity: event.target.value })}
                        step="0.0001"
                        type="number"
                        value={line.quantity}
                      />
                    </label>
                    <label className="business-field">
                      <span>Damaged</span>
                      <input
                        max={line.remaining}
                        min="0"
                        onChange={(event) => updateReceiptLine(line.key, { damaged: event.target.value })}
                        step="0.0001"
                        type="number"
                        value={line.damaged}
                      />
                    </label>
                    <label className="business-field">
                      <span>Discrepancy note</span>
                      <input onChange={(event) => updateReceiptLine(line.key, { discrepancyReason: event.target.value })} placeholder="Required when quantities differ" value={line.discrepancyReason} />
                    </label>
                  </div>
              ))}
            </div>
          ) : null}
          {error ? <p className="business-dialog-error" role="alert"><Icon name="alert" /> {error}</p> : null}
          <footer>
            <button className="secondary-button" disabled={busy} onClick={onClose} type="button">Cancel</button>
            <button
              className="primary-button"
              disabled={busy || receiptInvalid}
              type="submit"
            >
              {busy ? 'Recording…' : submitLabel}
            </button>
          </footer>
        </form>
      </section>
    </div>
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

function PricingView({
  csrfToken,
  overview,
}: {
  readonly csrfToken: string;
  readonly overview: HQOverview;
}) {
  const selectableTenants = useMemo(
    () => overview.network_items.filter((item) => item.status === 'ACTIVE'),
    [overview.network_items],
  );
  const [tenantId, setTenantId] = useState(
    overview.tenant_id || selectableTenants[0]?.id || '',
  );

  useEffect(() => {
    const nextTenantId = overview.tenant_id
      || (selectableTenants.some((tenant) => tenant.id === tenantId)
        ? tenantId
        : selectableTenants[0]?.id || '');
    if (nextTenantId !== tenantId) setTenantId(nextTenantId);
  }, [overview.tenant_id, selectableTenants, tenantId]);

  if (!tenantId) {
    return <TenantWorkspaceRequired domain="pricing control" />;
  }
  return (
    <>
      {overview.is_platform_overview ? (
        <section className="procurement-scope panel">
          <div>
            <p className="eyebrow">Tenant pricing authority</p>
            <h2>Commercial pricing workspace</h2>
            <span>Prepare, review, publish, assign, and test one tenant's prices without combining pharmacy records.</span>
          </div>
          <label>
            <span>Operating tenant</span>
            <select onChange={(event) => setTenantId(event.target.value)} value={tenantId}>
              {selectableTenants.map((tenant) => (
                <option key={tenant.id} value={tenant.id}>{tenant.name}</option>
              ))}
            </select>
          </label>
        </section>
      ) : null}
      <TenantPricingView csrfToken={csrfToken} tenantId={tenantId} />
    </>
  );
}

function TenantPricingView({
  csrfToken,
  tenantId,
}: {
  readonly csrfToken: string;
  readonly tenantId: string;
}) {
  const [books, setBooks] = useState<readonly PriceBookSummary[] | null>(null);
  const [overrides, setOverrides] = useState<readonly ManualPriceOverride[] | null>(null);
  const [locks, setLocks] = useState<readonly PriceLock[] | null>(null);
  const [appliedPrices, setAppliedPrices] = useState<readonly AppliedPriceSnapshot[] | null>(null);
  const [assignments, setAssignments] = useState<readonly PriceAssignment[] | null>(null);
  const [tenantSkus, setTenantSkus] = useState<readonly HQSku[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [pricingReload, setPricingReload] = useState(0);
  const [priceDraftOpen, setPriceDraftOpen] = useState(false);
  const [priceDraftSku, setPriceDraftSku] = useState('');
  const [priceDraftAmount, setPriceDraftAmount] = useState('');
  const [priceDraftFloor, setPriceDraftFloor] = useState('');
  const [priceDraftTaxInclusive, setPriceDraftTaxInclusive] = useState(true);
  const [priceDraftBusy, setPriceDraftBusy] = useState(false);
  const [priceDraftError, setPriceDraftError] = useState('');
  const [priceNotice, setPriceNotice] = useState('');
  const [busyOverrideId, setBusyOverrideId] = useState<string | null>(null);
  const [overrideError, setOverrideError] = useState('');
  const [overrideDecision, setOverrideDecision] = useState<{
    readonly decision: 'approve' | 'reject';
    readonly override: ManualPriceOverride;
  } | null>(null);
  const [overrideReason, setOverrideReason] = useState('');

  // Selected state for versions and entries
  const [selectedBook, setSelectedBook] = useState<PriceBookSummary | null>(null);
  const [versions, setVersions] = useState<readonly PriceBookVersion[] | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<PriceBookVersion | null>(null);
  const [entries, setEntries] = useState<readonly PriceBookEntry[] | null>(null);
  const [versionReload, setVersionReload] = useState(0);
  const [versionAction, setVersionAction] = useState<{
    readonly action: 'approve' | 'publish' | 'submit';
    readonly version: PriceBookVersion;
  } | null>(null);
  const [versionActionBusy, setVersionActionBusy] = useState(false);
  const [versionActionError, setVersionActionError] = useState('');

  // Simulator State
  const [simBranch, setSimBranch] = useState('');
  const [simSku, setSimSku] = useState('');
  const [simQty, setSimQty] = useState('1');
  const [simDate, setSimDate] = useState(() => new Date().toISOString().split('T')[0] ?? '');
  const [simCurrency, setSimCurrency] = useState('KES');
  const [resolutionResult, setResolutionResult] = useState<PriceResolutionResult | null>(null);
  const [resolving, setResolving] = useState(false);
  const [resolutionError, setResolutionError] = useState<string | null>(null);

  const fetchOverrides = useCallback((signal?: AbortSignal) => {
    loadPriceOverrides(false, tenantId, signal)
      .then(setOverrides)
      .catch(() => {});
  }, [tenantId]);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      loadPriceBooks(tenantId, controller.signal),
      loadPriceOverrides(false, tenantId, controller.signal),
      loadPriceLocks(tenantId, controller.signal),
      loadAppliedPrices(tenantId, controller.signal),
      loadPriceAssignments(tenantId, controller.signal),
      loadTenantSkus(tenantId, controller.signal),
    ])
      .then(([b, o, l, a, ass, skus]) => {
        setBooks(b);
        setOverrides(o);
        setLocks(l);
        setAppliedPrices(a);
        setAssignments(ass);
        setTenantSkus(skus);
        setSelectedBook((current) => (
          b.find((book) => book.id === current?.id) ?? b[0] ?? null
        ));
        setFailed(false);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [pricingReload, tenantId]);

  // Fetch versions when selectedBook changes
  useEffect(() => {
    if (!selectedBook) return;
    const controller = new AbortController();
    setVersions(null);
    setSelectedVersion(null);
    setEntries(null);
    loadPriceBookVersions(selectedBook.id, tenantId, controller.signal)
      .then((vList) => {
        setVersions(vList);
        if (vList.length > 0) {
          setSelectedVersion(vList[0] ?? null);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setVersions([]);
      });
    return () => controller.abort();
  }, [selectedBook, tenantId, versionReload]);

  // Fetch entries when selectedVersion changes
  useEffect(() => {
    if (!selectedVersion) return;
    const controller = new AbortController();
    setEntries(null);
    loadPriceBookEntries(selectedVersion.id, tenantId, controller.signal)
      .then(setEntries)
      .catch(() => {
        if (!controller.signal.aborted) setEntries([]);
      });
    return () => controller.abort();
  }, [selectedVersion, tenantId]);

  const handleResolvePrice = async (e: FormEvent) => {
    e.preventDefault();
    setResolving(true);
    setResolutionError(null);
    setResolutionResult(null);
    try {
      const res = await resolvePrice({
        branch: simBranch,
        sku: simSku,
        quantity: simQty,
        service_date: simDate,
        currency: simCurrency,
      });
      setResolutionResult(res);
    } catch (err: unknown) {
      if (err instanceof HQApiError) {
        setResolutionError(err.message);
      } else {
        setResolutionError('Price resolution failed.');
      }
    } finally {
      setResolving(false);
    }
  };

  if (failed) return <Unavailable />;
  if (!books || !overrides || !locks || !appliedPrices || !assignments || !tenantSkus) {
    return <p className="muted-cell">Loading pricing & commercial governance data…</p>;
  }

  const inert = books.filter((book) => book.live_version === null);
  const branchScoped = books.filter((book) => book.scope_type === 'BRANCH');
  const pendingOverrides = overrides.filter((o) => o.status === 'REQUESTED');
  const liveLocks = locks.filter((l) => l.is_live);

  return (
    <>
      <article className="panel price-control-guide">
        <div className="price-control-guide-head">
          <div>
            <p className="eyebrow">Controlled selling-price workflow</p>
            <h2>From tenant catalogue to a price every till can charge</h2>
            <p>
              Prices are prepared in a draft, independently approved, then published.
              Tills only resolve active or scheduled versions assigned to their scope.
            </p>
          </div>
          <button
            className="primary-button"
            onClick={() => {
              setPriceDraftError('');
              setPriceDraftOpen(true);
            }}
            type="button"
          >
            <Icon name="database" />
            Create or update price draft
          </button>
        </div>
        <div className="price-control-steps" aria-label="Price control workflow">
          <div><span>1</span><strong>Prepare</strong><small>Select a tenant SKU and set its selling price and floor.</small></div>
          <div><span>2</span><strong>Submit</strong><small>Lock the draft and send the complete version for review.</small></div>
          <div><span>3</span><strong>Approve</strong><small>A different authorised person checks the version.</small></div>
          <div><span>4</span><strong>Publish</strong><small>Make approved prices available from their effective date.</small></div>
          <div><span>5</span><strong>Resolve</strong><small>Verify the exact branch and SKU price before tills use it.</small></div>
        </div>
        {tenantSkus.length === 0 ? (
          <div className="inline-alert" role="status" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
              <Icon name="alert" />
              No governed tenant SKU is selected yet. Click "Create or update price draft" to set prices directly, or select items from the Government Catalogue.
            </span>
            <a href="#catalogue" className="secondary-button" style={{ padding: '4px 12px', fontSize: '0.8rem', textDecoration: 'none' }}>
              <Icon name="inventory" /> Go to Medicine Catalogue
            </a>
          </div>
        ) : null}
        {priceNotice ? <p className="inline-alert" role="status"><Icon name="check" /> {priceNotice}</p> : null}
      </article>

      <section className="metric-grid network-metrics" aria-label="Price book totals">
        <SummaryCard icon="database" label="Price books" value={books.length} detail={`${inert.length} without live version`} onActivate={() => document.getElementById('pricing-books')?.scrollIntoView({ behavior: 'smooth', block: 'start' })} />
        <SummaryCard
          icon="building"
          label="Branch assignments"
          value={assignments.length}
          detail={`${branchScoped.length} branch price overrides`}
          tone="teal"
          onActivate={() => document.getElementById('pricing-assignments')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
        />
        <SummaryCard
          icon="alert"
          label="Pending overrides"
          value={pendingOverrides.length}
          detail="Supervisor review required"
          tone={pendingOverrides.length ? 'rose' : 'navy'}
          onActivate={() => document.getElementById('pricing-overrides')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
        />
        <SummaryCard
          icon="check"
          label="Active price locks"
          value={liveLocks.length}
          detail="Active till basket locks"
          tone="amber"
          onActivate={() => document.getElementById('pricing-locks')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
        />
      </section>

      {/* Section 1: Interactive Price Resolution Simulator */}
      <section className="content-grid content-grid-primary">
        <article className="panel">
          <PanelHeader eyebrow="Simulation Sandbox" title="Live Price Resolution Engine" />
          <form className="resolution-form" onSubmit={(e) => void handleResolvePrice(e)} style={{ display: 'grid', gap: '12px', padding: '16px 0' }}>
            <p className="muted-cell" style={{ margin: 0 }}>
              Test pricing rules without recording a sale. Computes active price book precedence, customer/branch scope, and tax inclusion.
            </p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px' }}>
              <label>
                <small className="muted-cell">Branch ID (UUID / Code)</small>
                <input
                  className="search-field"
                  onChange={(e) => setSimBranch(e.target.value)}
                  placeholder="e.g. branch-nairobi"
                  style={{ width: '100%', padding: '8px 12px', marginTop: '4px' }}
                  type="text"
                  value={simBranch}
                />
              </label>
              <label>
                <small className="muted-cell">SKU Code / ID</small>
                <input
                  className="search-field"
                  onChange={(e) => setSimSku(e.target.value)}
                  placeholder="e.g. SKU-PARA-500"
                  style={{ width: '100%', padding: '8px 12px', marginTop: '4px' }}
                  type="text"
                  value={simSku}
                />
              </label>
              <label>
                <small className="muted-cell">Quantity</small>
                <input
                  className="search-field"
                  onChange={(e) => setSimQty(e.target.value)}
                  placeholder="1"
                  style={{ width: '100%', padding: '8px 12px', marginTop: '4px' }}
                  type="number"
                  value={simQty}
                />
              </label>
              <label>
                <small className="muted-cell">Currency</small>
                <select
                  className="search-field"
                  onChange={(e) => setSimCurrency(e.target.value)}
                  style={{ width: '100%', padding: '8px 12px', marginTop: '4px' }}
                  value={simCurrency}
                >
                  <option value="KES">KES</option>
                  <option value="USD">USD</option>
                  <option value="EUR">EUR</option>
                  <option value="UGX">UGX</option>
                  <option value="TZS">TZS</option>
                </select>
              </label>
              <label>
                <small className="muted-cell">Service Date</small>
                <input
                  className="search-field"
                  onChange={(e) => setSimDate(e.target.value)}
                  style={{ width: '100%', padding: '8px 12px', marginTop: '4px' }}
                  type="date"
                  value={simDate}
                />
              </label>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '12px', marginTop: '4px' }}>
              <button className="primary-button" disabled={resolving} type="submit">
                <Icon className={resolving ? 'spin' : ''} name="activity" />
                {resolving ? 'Calculating…' : 'Calculate & Resolve Price'}
              </button>
            </div>
          </form>

          {resolutionError ? (
            <div className="inline-alert" role="status" style={{ marginTop: '12px' }}>
              <Icon name="alert" />
              {resolutionError}
            </div>
          ) : null}

          {resolutionResult ? (
            <div className="resolution-result-card" style={{ marginTop: '16px', padding: '16px', borderRadius: '10px', background: 'var(--panel)', border: '1px solid var(--teal-500)', boxShadow: 'var(--shadow)' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                <span className="status-badge status-active"><i /> Price Resolved</span>
                <strong style={{ fontSize: '1.2rem', color: 'var(--teal-600)' }}>
                  {formatMoney(resolutionResult.unit_price, resolutionResult.currency)} / unit
                </strong>
              </div>
              <p style={{ margin: '4px 0', fontSize: '0.85rem' }}>
                <strong>Explanation:</strong> {resolutionResult.explanation}
              </p>
              <div style={{ display: 'flex', gap: '16px', fontSize: '0.75rem', color: 'var(--muted)', marginTop: '8px' }}>
                <span>Source: <strong>{resolutionResult.source}</strong> ({resolutionResult.source_reference})</span>
                <span>Tax: <strong>{resolutionResult.tax_inclusive ? 'Tax Inclusive' : 'Tax Exclusive'}</strong></span>
                <span>Hash: <code>{resolutionResult.context_hash.slice(0, 12)}…</code></span>
              </div>

              {resolutionResult.considered && resolutionResult.considered.length > 0 ? (
                <div style={{ marginTop: '12px', paddingTop: '8px', borderTop: '1px dashed var(--line)' }}>
                  <small className="muted-cell">Books Considered in Precedence Order:</small>
                  <ul style={{ margin: '4px 0 0 16px', padding: 0, fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                    {resolutionResult.considered.map((item, idx) => (
                      <li key={idx}>{item}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : null}
        </article>
      </section>

      {/* Section 2: Master Price Books & Version Explorer */}
      <section className="content-grid content-grid-primary" style={{ marginTop: '24px' }}>
        <article className="panel" id="pricing-books">
          <PanelHeader eyebrow="Commercial Control" title="Price Books Directory" />
          {books.length === 0 ? (
            <EmptyState detail="No price books are configured for this tenant." icon="database" title="No price books" />
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Code</th>
                    <th>Name</th>
                    <th>Scope</th>
                    <th>Type</th>
                    <th>Priority</th>
                    <th>Currency</th>
                    <th>Live Version</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {books.map((book) => {
                    const isSelected = selectedBook?.id === book.id;
                    return (
                      <tr key={book.id} style={isSelected ? { background: 'var(--teal-50)' } : undefined}>
                        <td><code>{book.code}</code></td>
                        <td><strong>{book.name}</strong></td>
                        <td><small>{book.scope_type}</small></td>
                        <td><span className="muted-cell">{book.price_type}</span></td>
                        <td>{book.priority}</td>
                        <td>{book.currency}</td>
                        <td>
                          {book.live_version === null ? (
                            <span className="muted-cell">No live version</span>
                          ) : (
                            <span className="status-badge status-active"><i /> v{book.live_version}</span>
                          )}
                        </td>
                        <td>
                          <button
                            className="secondary-button"
                            onClick={() => setSelectedBook(book)}
                            style={{ padding: '4px 8px', fontSize: '0.75rem' }}
                            type="button"
                          >
                            {isSelected ? 'Viewing' : 'Inspect'}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </article>

        {/* Versions & Entries Explorer */}
        <article className="panel">
          <PanelHeader
            eyebrow={selectedBook ? `Book: ${selectedBook.code}` : 'Versions'}
            title={selectedBook ? `${selectedBook.name} Versions & Entries` : 'Select a Price Book'}
          />
          {!selectedBook ? (
            <EmptyState detail="Click Inspect on any price book to explore its versions and price entries." icon="docs" title="Select a Price Book" />
          ) : !versions ? (
            <p className="muted-cell">Loading book versions…</p>
          ) : versions.length === 0 ? (
            <EmptyState detail="This price book has no published or draft versions." icon="alert" title="No versions found" />
          ) : (
            <div style={{ display: 'grid', gap: '16px' }}>
              <div>
                <small className="muted-cell" style={{ display: 'block', marginBottom: '6px' }}>Version Timeline:</small>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  {versions.map((ver) => {
                    const isVerSelected = selectedVersion?.id === ver.id;
                    return (
                      <button
                        key={ver.id}
                        onClick={() => setSelectedVersion(ver)}
                        style={{
                          padding: '6px 12px',
                          borderRadius: '6px',
                          border: isVerSelected ? '1px solid var(--teal-500)' : '1px solid var(--line)',
                          background: isVerSelected ? 'var(--teal-100)' : 'var(--panel)',
                          color: isVerSelected ? 'var(--teal-600)' : 'var(--ink)',
                          cursor: 'pointer',
                          fontSize: '0.78rem',
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '6px',
                        }}
                        type="button"
                      >
                        <strong>v{ver.version_number}</strong>
                        <span className={`status-badge status-${ver.status.toLowerCase()}`} style={{ padding: '2px 6px', fontSize: '0.65rem' }}>
                          {ver.status}
                        </span>
                        <small className="muted-cell">({ver.entry_count} SKUs)</small>
                      </button>
                    );
                  })}
                </div>
              </div>

              {selectedVersion ? (
                <div style={{ borderTop: '1px solid var(--line)', paddingTop: '12px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', flexWrap: 'wrap', gap: '8px' }}>
                    <small className="muted-cell">
                      Version v{selectedVersion.version_number} Entries ({selectedVersion.status}) — Effective: {selectedVersion.effective_from} to {selectedVersion.effective_to || 'Indefinite'}
                    </small>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <button
                        className="secondary-button"
                        onClick={() => {
                          setPriceDraftError('');
                          setPriceDraftOpen(true);
                        }}
                        style={{ padding: '4px 10px', fontSize: '0.78rem' }}
                        type="button"
                      >
                        <Icon name="database" /> + Add SKU Price Entry
                      </button>
                      {['DRAFT', 'UNDER_REVIEW', 'APPROVED'].includes(selectedVersion.status) ? (
                        <button
                          className="primary-button"
                          onClick={() => {
                            const action = selectedVersion.status === 'DRAFT'
                              ? 'submit'
                              : selectedVersion.status === 'UNDER_REVIEW'
                                ? 'approve'
                                : 'publish';
                            setVersionAction({ action, version: selectedVersion });
                            setVersionActionError('');
                          }}
                          style={{ padding: '4px 10px', fontSize: '0.78rem' }}
                          type="button"
                        >
                          {selectedVersion.status === 'DRAFT'
                            ? 'Submit for review'
                            : selectedVersion.status === 'UNDER_REVIEW'
                              ? 'Approve version'
                              : 'Publish version'}
                        </button>
                      ) : null}
                    </div>
                  </div>
                  {!entries ? (
                    <p className="muted-cell">Loading SKU price entries…</p>
                  ) : entries.length === 0 ? (
                    <p className="muted-cell">No price entries recorded in version v{selectedVersion.version_number}.</p>
                  ) : (
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>SKU Code</th>
                            <th>Unit Price</th>
                            <th>Min Qty</th>
                            <th>Max Qty</th>
                            <th>Floor Price</th>
                            <th>Tax</th>
                            <th>Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {entries.map((entry) => (
                            <tr key={entry.id}>
                              <td><code>{entry.sku_code}</code></td>
                              <td><strong>{formatMoney(entry.unit_price, selectedBook.currency)}</strong></td>
                              <td>{entry.minimum_quantity}</td>
                              <td>{entry.maximum_quantity || '—'}</td>
                              <td>
                                {entry.minimum_allowed_price
                                  ? <span className="text-rose">{formatMoney(entry.minimum_allowed_price, selectedBook.currency)}</span>
                                  : <span className="muted-cell">None</span>}
                              </td>
                              <td>{entry.tax_inclusive ? 'Inclusive' : 'Exclusive'}</td>
                              <td>
                                <button
                                  className="secondary-button"
                                  onClick={() => {
                                    setPriceDraftSku(entry.sku_code);
                                    setPriceDraftAmount(entry.unit_price);
                                    setPriceDraftFloor(entry.minimum_allowed_price || '');
                                    setPriceDraftTaxInclusive(entry.tax_inclusive);
                                    setPriceDraftError('');
                                    setPriceDraftOpen(true);
                                  }}
                                  style={{ padding: '2px 8px', fontSize: '0.75rem' }}
                                  type="button"
                                >
                                  Edit price
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              ) : null}
            </div>
          )}
        </article>
      </section>

      <article className="panel" id="pricing-assignments" style={{ marginTop: '24px' }}>
        <PanelHeader eyebrow="Resolution Scope" title="Price Book Assignments" />
        <p className="panel-note">
          Assignments decide which book is considered for a tenant, branch, group or customer
          scope. Higher-priority books win only within the same scope; a true tie is refused.
        </p>
        {assignments.length === 0 ? (
          <EmptyState
            detail="Saving the first tenant retail draft creates its default tenant assignment automatically."
            icon="building"
            title="No price assignments"
          />
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Price Book</th>
                  <th>Scope</th>
                  <th>Target</th>
                  <th>Priority</th>
                  <th>Validity</th>
                  <th>State</th>
                </tr>
              </thead>
              <tbody>
                {assignments.map((assignment) => {
                  const target = assignment.branch_code
                    ? `${assignment.branch_code} — ${assignment.branch_name ?? 'Branch'}`
                    : assignment.branch_group || assignment.region || assignment.customer_segment || 'Whole tenant';
                  return (
                    <tr key={assignment.id}>
                      <td><code>{assignment.price_book_code}</code></td>
                      <td><strong>{titleCase(assignment.scope_type)}</strong></td>
                      <td>{target}</td>
                      <td>{assignment.priority}</td>
                      <td>
                        <small>
                          {assignment.valid_from ?? 'Immediately'} → {assignment.valid_to ?? 'No end date'}
                        </small>
                      </td>
                      <td><StatusBadge value={assignment.is_active ? 'ACTIVE' : 'INACTIVE'} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </article>

      {/* Section 3: Manual Supervisor Overrides & Applied Price Audit */}
      <section className="content-grid content-grid-primary" style={{ marginTop: '24px' }}>
        <article className="panel" id="pricing-overrides">
          <PanelHeader eyebrow="Supervisor Governance" title="Manual Price Overrides Audit" />
          {overrideError ? (
            <div className="inline-alert" role="alert"><Icon name="alert" />{overrideError}</div>
          ) : null}
          {overrides.length === 0 ? (
            <EmptyState detail="No manual price override requests recorded." icon="check" title="No price overrides" />
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>SKU Code</th>
                    <th>Transaction Ref</th>
                    <th>Resolved Price</th>
                    <th>Override Price</th>
                    <th>Variance</th>
                    <th>Reason</th>
                    <th>Requested By</th>
                    <th>Approver</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {overrides.map((ov) => (
                    <tr key={ov.id}>
                      <td><code>{ov.sku_code}</code></td>
                      <td><small>{ov.transaction_reference}</small></td>
                      <td>{formatMoney(ov.resolved_price)}</td>
                      <td><strong>{formatMoney(ov.override_price)}</strong></td>
                      <td>
                        <span className={Number(ov.difference) < 0 ? 'text-rose' : 'muted-cell'}>
                          {formatMoney(ov.difference)}
                        </span>
                      </td>
                      <td><small>{ov.reason_code}</small></td>
                      <td><small>{ov.requested_by_username}</small></td>
                      <td><small>{ov.approved_by_username || '—'}</small></td>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                          <span className={`status-badge status-${ov.status.toLowerCase()}`}>
                            <i /> {ov.status}
                          </span>
                          {ov.status === 'REQUESTED' ? (
                            <>
                              <button
                                className="segmented-option is-active"
                                disabled={busyOverrideId === ov.id}
                                onClick={() => {
                                  setOverrideReason('');
                                  setOverrideDecision({ decision: 'approve', override: ov });
                                }}
                                style={{ padding: '2px 8px', fontSize: '0.72rem' }}
                                type="button"
                              >
                                Approve
                              </button>
                              <button
                                className="segmented-option"
                                disabled={busyOverrideId === ov.id}
                                onClick={() => {
                                  setOverrideReason('');
                                  setOverrideDecision({ decision: 'reject', override: ov });
                                }}
                                style={{ padding: '2px 8px', fontSize: '0.72rem', color: '#f43f5e' }}
                                type="button"
                              >
                                Reject
                              </button>
                            </>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>

        <article className="panel">
          <PanelHeader eyebrow="Audit Trail" title="Applied Price Snapshots" />
          {appliedPrices.length === 0 ? (
            <EmptyState detail="No applied price snapshots recorded yet." icon="docs" title="No snapshots" />
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Line Ref</th>
                    <th>Type</th>
                    <th>SKU Code</th>
                    <th>Qty</th>
                    <th>Unit Price</th>
                    <th>Line Total</th>
                    <th>Source</th>
                    <th>Resolved At</th>
                  </tr>
                </thead>
                <tbody>
                  {appliedPrices.slice(0, 10).map((ap) => (
                    <tr key={ap.id}>
                      <td><code>{ap.line_reference}</code></td>
                      <td><small>{ap.line_type}</small></td>
                      <td><small>{ap.sku_code}</small></td>
                      <td>{ap.quantity}</td>
                      <td>{formatMoney(ap.unit_price, ap.currency)}</td>
                      <td><strong>{formatMoney(ap.line_total, ap.currency)}</strong></td>
                      <td><span className="muted-cell">{ap.source}</span></td>
                      <td><small className="muted-cell">{formatTime(ap.resolved_at)}</small></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>
      </section>

      {/* Section 4: Active Price Locks Watchlist */}
      <article className="panel" id="pricing-locks" style={{ marginTop: '24px' }}>
        <PanelHeader eyebrow="Basket Custody" title="Active Price Locks Watchlist" />
        {locks.length === 0 ? (
          <EmptyState detail="No basket price locks currently active." icon="check" title="No active locks" />
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Basket Reference</th>
                  <th>Line Reference</th>
                  <th>SKU Code</th>
                  <th>Quantity</th>
                  <th>Locked Price</th>
                  <th>Status</th>
                  <th>Live Status</th>
                  <th>Expires At</th>
                </tr>
              </thead>
              <tbody>
                {locks.map((lock) => (
                  <tr key={lock.id}>
                    <td><code>{lock.basket_reference}</code></td>
                    <td><small>{lock.line_reference}</small></td>
                    <td><small>{lock.sku_code}</small></td>
                    <td>{lock.quantity}</td>
                    <td><strong>{formatMoney(lock.locked_unit_price, lock.currency)}</strong></td>
                    <td><small>{lock.status}</small></td>
                    <td>
                      {lock.is_live ? (
                        <span className="status-badge status-active"><i /> Live</span>
                      ) : (
                        <span className="muted-cell">Expired / Consumed</span>
                      )}
                    </td>
                    <td><small className="muted-cell">{formatTime(lock.expires_at)}</small></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </article>
      {priceDraftOpen ? (
        <div className="business-dialog-backdrop" role="presentation">
          <section aria-labelledby="price-draft-title" aria-modal="true" className="business-dialog" role="dialog">
            <header>
              <div>
                <p className="eyebrow">Prepare controlled prices</p>
                <h2 id="price-draft-title">Create or update tenant retail draft</h2>
              </div>
              <button
                aria-label="Close dialog"
                disabled={priceDraftBusy}
                onClick={() => setPriceDraftOpen(false)}
                type="button"
              >
                <Icon name="close" />
              </button>
            </header>
            <form
              onSubmit={async (event) => {
                event.preventDefault();
                setPriceDraftBusy(true);
                setPriceDraftError('');
                try {
                  const saved = await saveTenantPriceDraft(
                    {
                      sku_code: priceDraftSku,
                      unit_price: priceDraftAmount,
                      minimum_allowed_price: priceDraftFloor || null,
                      tax_inclusive: priceDraftTaxInclusive,
                    },
                    tenantId,
                    csrfToken,
                  );
                  setPriceNotice(
                    `${saved.sku_code} saved in ${saved.price_book} draft v${saved.version_number}. `
                    + 'Complete the draft, then submit it for independent review.',
                  );
                  setPriceDraftOpen(false);
                  setPriceDraftSku('');
                  setPriceDraftAmount('');
                  setPriceDraftFloor('');
                  setPricingReload((value) => value + 1);
                } catch (reason) {
                  setPriceDraftError(
                    reason instanceof Error ? reason.message : 'The price draft could not be saved.',
                  );
                } finally {
                  setPriceDraftBusy(false);
                }
              }}
            >
              <p className="business-dialog-confirm">
                <Icon name="shield" />
                This only changes the editable draft. Active till prices remain unchanged until
                a different authorised person approves and publishes the full version.
              </p>
              {priceDraftError ? <p className="business-dialog-error" role="alert"><Icon name="alert" /> {priceDraftError}</p> : null}
              <label className="business-field">
                <span>Tenant commercial SKU</span>
                {tenantSkus.length > 0 ? (
                  <select
                    onChange={(event) => setPriceDraftSku(event.target.value)}
                    required
                    value={priceDraftSku}
                  >
                    <option value="">Select an eligible SKU</option>
                    {tenantSkus.map((sku) => (
                      <option key={sku.id} value={sku.sku_code}>
                        {sku.sku_code} — {sku.display_name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    onChange={(event) => setPriceDraftSku(event.target.value)}
                    placeholder="Enter SKU Code (e.g. SKU-PARA-500, Amoxicillin 500mg)"
                    required
                    type="text"
                    value={priceDraftSku}
                  />
                )}
              </label>
              <div className="tenant-form-grid">
                <label className="business-field">
                  <span>Unit selling price (KES)</span>
                  <input
                    min="0"
                    onChange={(event) => setPriceDraftAmount(event.target.value)}
                    required
                    step="0.01"
                    type="number"
                    value={priceDraftAmount}
                  />
                </label>
                <label className="business-field">
                  <span>Minimum allowed price (KES)</span>
                  <input
                    min="0"
                    onChange={(event) => setPriceDraftFloor(event.target.value)}
                    step="0.01"
                    type="number"
                    value={priceDraftFloor}
                  />
                  <small>Optional floor for supervised transaction overrides.</small>
                </label>
              </div>
              <label className="business-checkbox">
                <input
                  checked={priceDraftTaxInclusive}
                  onChange={(event) => setPriceDraftTaxInclusive(event.target.checked)}
                  type="checkbox"
                />
                <span>Displayed selling price includes applicable tax</span>
              </label>
              <footer>
                <button
                  className="secondary-button"
                  disabled={priceDraftBusy}
                  onClick={() => setPriceDraftOpen(false)}
                  type="button"
                >
                  Cancel
                </button>
                <button
                  className="primary-button"
                  disabled={priceDraftBusy || !priceDraftSku || !priceDraftAmount}
                  type="submit"
                >
                  {priceDraftBusy ? 'Saving…' : 'Save to draft'}
                </button>
              </footer>
            </form>
          </section>
        </div>
      ) : null}
      {overrideDecision ? (
        <div className="business-dialog-backdrop" role="presentation">
          <section aria-labelledby="override-decision-title" aria-modal="true" className="business-dialog" role="dialog">
            <header>
              <div>
                <p className="eyebrow">Independent supervisor decision</p>
                <h2 id="override-decision-title">
                  {overrideDecision.decision === 'approve' ? 'Approve price override' : 'Reject price override'}
                </h2>
              </div>
              <button
                aria-label="Close dialog"
                disabled={Boolean(busyOverrideId)}
                onClick={() => setOverrideDecision(null)}
                type="button"
              >
                <Icon name="close" />
              </button>
            </header>
            <div className="business-dialog-record">
              <div>
                <code>{overrideDecision.override.transaction_reference}</code>
                <strong>{overrideDecision.override.sku_code}</strong>
                <small>
                  {formatMoney(overrideDecision.override.resolved_price)} →{' '}
                  {formatMoney(overrideDecision.override.override_price)}
                </small>
              </div>
            </div>
            <p className="business-dialog-confirm">
              <Icon name={overrideDecision.decision === 'approve' ? 'shield' : 'alert'} />
              The requester cannot decide their own override. Your authenticated identity and
              decision are retained in the price audit trail.
            </p>
            {overrideDecision.decision === 'reject' ? (
              <label className="business-field">
                <span>Rejection reason</span>
                <textarea
                  onChange={(event) => setOverrideReason(event.target.value)}
                  required
                  rows={3}
                  value={overrideReason}
                />
              </label>
            ) : null}
            {overrideError ? <p className="business-dialog-error" role="alert"><Icon name="alert" /> {overrideError}</p> : null}
            <footer>
              <button
                className="secondary-button"
                disabled={Boolean(busyOverrideId)}
                onClick={() => setOverrideDecision(null)}
                type="button"
              >
                Cancel
              </button>
              <button
                className={overrideDecision.decision === 'approve' ? 'primary-button' : 'danger-link'}
                disabled={Boolean(busyOverrideId) || (overrideDecision.decision === 'reject' && !overrideReason.trim())}
                onClick={async () => {
                  setBusyOverrideId(overrideDecision.override.id);
                  setOverrideError('');
                  try {
                    await decidePriceOverride(
                      overrideDecision.override.id,
                      overrideDecision.decision,
                      csrfToken,
                      overrideReason,
                    );
                    setOverrideDecision(null);
                    fetchOverrides();
                  } catch (reason) {
                    setOverrideError(
                      reason instanceof Error ? reason.message : 'The override decision failed.',
                    );
                  } finally {
                    setBusyOverrideId(null);
                  }
                }}
                type="button"
              >
                {busyOverrideId
                  ? 'Recording…'
                  : overrideDecision.decision === 'approve'
                    ? 'Approve override'
                    : 'Reject override'}
              </button>
            </footer>
          </section>
        </div>
      ) : null}
      {versionAction ? (
        <div className="business-dialog-backdrop" role="presentation">
          <section aria-labelledby="price-version-action-title" aria-modal="true" className="business-dialog" role="dialog">
            <header>
              <div>
                <p className="eyebrow">Price book governance</p>
                <h2 id="price-version-action-title">
                  {versionAction.action === 'submit'
                    ? 'Submit price version for review'
                    : versionAction.action === 'approve'
                      ? 'Approve price version'
                      : 'Publish price version'}
                </h2>
              </div>
              <button
                aria-label="Close dialog"
                disabled={versionActionBusy}
                onClick={() => setVersionAction(null)}
                type="button"
              >
                <Icon name="close" />
              </button>
            </header>
            <div className="business-dialog-record">
              <div>
                <code>{versionAction.version.price_book_code}</code>
                <strong>Version {versionAction.version.version_number}</strong>
              </div>
            </div>
            <p className="business-dialog-confirm">
              <Icon name={versionAction.action === 'publish' ? 'alert' : 'shield'} />
              {versionAction.action === 'submit'
                ? 'Submission locks this draft for independent commercial review.'
                : versionAction.action === 'approve'
                  ? 'The preparer cannot approve their own price version. Your identity is recorded.'
                  : 'Publishing makes these approved prices available to tills from the effective date.'}
            </p>
            {versionActionError ? (
              <p className="auth-error" role="alert"><Icon name="alert" /> {versionActionError}</p>
            ) : null}
            <footer>
              <button
                className="secondary-button"
                disabled={versionActionBusy}
                onClick={() => setVersionAction(null)}
                type="button"
              >
                Cancel
              </button>
              <button
                className="primary-button"
                disabled={versionActionBusy}
                onClick={async () => {
                  setVersionActionBusy(true);
                  setVersionActionError('');
                  try {
                    await transitionPriceBookVersion(
                      versionAction.version.id,
                      versionAction.action,
                      csrfToken,
                    );
                    setVersionAction(null);
                    setVersionReload((current) => current + 1);
                    setPricingReload((current) => current + 1);
                  } catch (reason) {
                    setVersionActionError(
                      reason instanceof Error ? reason.message : 'Price version action failed.',
                    );
                  } finally {
                    setVersionActionBusy(false);
                  }
                }}
                type="button"
              >
                {versionActionBusy
                  ? 'Working…'
                  : versionAction.action === 'submit'
                    ? 'Submit for review'
                    : versionAction.action === 'approve'
                      ? 'Approve version'
                      : 'Publish prices'}
              </button>
            </footer>
          </section>
        </div>
      ) : null}
    </>
  );
}

/**
 * POS installers.
 *
 * Lives with cash control because the person standing up a new till is the one
 * who needs the installer, and tills are what this section is about.
 *
 * The checksum is shown beside every download, not hidden behind a detail view:
 * verifying a release binary before installing it on a device that takes money is
 * the whole reason to publish one.
 */
function PosDownloads({ csrfToken }: { readonly csrfToken: string }) {
  const [catalogue, setCatalogue] = useState<PosReleaseCatalogue | null>(null);
  const [failed, setFailed] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedRelease, setSelectedRelease] = useState<PosRelease | null>(null);
  const [releaseFilter, setReleaseFilter] = useState<'LATEST' | 'WINDOWS' | 'ANDROID' | 'ALL'>('LATEST');
  const [copiedChecksum, setCopiedChecksum] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    loadPosReleases(controller.signal)
      .then(setCatalogue)
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!selectedRelease) return undefined;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && pending !== selectedRelease.id) setSelectedRelease(null);
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [pending, selectedRelease]);

  const latestReleaseIds = useMemo(() => {
    const latest = new Map<PosRelease['platform'], PosRelease>();
    for (const release of catalogue?.releases ?? []) {
      const current = latest.get(release.platform);
      if (!current || release.build_number > current.build_number) latest.set(release.platform, release);
    }
    return new Set([...latest.values()].map((release) => release.id));
  }, [catalogue]);

  const visibleReleases = useMemo(() => {
    const releases = catalogue?.releases ?? [];
    if (releaseFilter === 'LATEST') return releases.filter((release) => latestReleaseIds.has(release.id));
    if (releaseFilter === 'ALL') return releases;
    return releases.filter((release) => release.platform === releaseFilter);
  }, [catalogue, latestReleaseIds, releaseFilter]);

  const download = useCallback(
    async (release: PosRelease) => {
      setPending(release.id);
      setError(null);
      try {
        const grant = await requestPosDownload(release.id, csrfToken);
        // The signed URL is short lived, so it is followed immediately rather
        // than rendered as a link somebody might open an hour later.
        window.location.assign(grant.url);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : 'The download could not be started.');
      } finally {
        setPending(null);
      }
    },
    [csrfToken],
  );

  const copyChecksum = async (release: PosRelease) => {
    try {
      await navigator.clipboard.writeText(release.sha256);
      setCopiedChecksum(release.id);
      setError(null);
    } catch {
      setCopiedChecksum(null);
      setError('Clipboard access was blocked. Select and copy the checksum manually.');
    }
  };

  if (failed) return <Unavailable />;
  if (!catalogue) return <p className="muted-cell">Loading installers…</p>;

  return (
    <article className="panel pos-downloads-panel" id="cash-installers">
      <header className="pos-downloads-header">
        <div>
          <p className="eyebrow">Point of sale</p>
          <h2>Point of Sale Till Installers</h2>
          <p>Verified desktop and mobile packages for managed pharmacy terminals.</p>
        </div>
        <div className="pos-downloads-delivery">
          <span className={`status-badge ${catalogue.downloads_available ? 'status-active' : 'status-warning'}`}><i /> {catalogue.downloads_available ? 'Downloads ready' : 'Downloads unavailable'}</span>
          <small>{catalogue.storage_backend === 'local' ? 'Protected HQ delivery' : 'Short-lived signed links'} · {Math.max(1, Math.round(catalogue.url_ttl_seconds / 60))} min access window</small>
        </div>
      </header>

      {error ? (
        <p className="auth-error" role="alert" aria-live="assertive">
          <Icon name="alert" /> {error}
        </p>
      ) : null}

      {!catalogue.downloads_available ? (
        <p className="panel-note">
          Installer storage is not configured for this deployment, so downloads are
          unavailable. The catalogue below is what would be served.
        </p>
      ) : null}

      {catalogue.releases.length ? (
        <>
          <nav aria-label="Installer release filters" className="pos-release-filters segmented">
            {([
              ['LATEST', 'Latest'],
              ['WINDOWS', 'Windows'],
              ['ANDROID', 'Android'],
              ['ALL', 'All releases'],
            ] as const).map(([value, label]) => (
              <button
                aria-pressed={releaseFilter === value}
                className={releaseFilter === value ? 'segmented-option is-active' : 'segmented-option'}
                key={value}
                onClick={() => setReleaseFilter(value)}
                type="button"
              >
                {label}
              </button>
            ))}
          </nav>
          <div className="pos-release-grid">
            {visibleReleases.map((release) => {
              const isLatest = latestReleaseIds.has(release.id);
              return (
                <section className={`pos-release-card ${isLatest ? 'is-latest' : ''}`} key={release.id}>
                  <header>
                    <span className={`pos-platform-mark pos-platform-${release.platform.toLowerCase()}`} aria-hidden="true">
                      {release.platform === 'WINDOWS' ? 'W' : 'A'}
                    </span>
                    <div>
                      <span className="pos-release-kicker">{release.platform === 'WINDOWS' ? 'Windows till' : 'Android till'}</span>
                      <h3>Version {release.version}</h3>
                    </div>
                    {isLatest ? <span className="status-badge status-active"><i /> Latest</span> : <span className="panel-meta">Previous</span>}
                  </header>

                  <p className="pos-release-notes">{release.release_notes || 'Validated TibaTrace POS release.'}</p>
                  {release.operations_impact ? <p className="pos-release-impact"><strong>Operations impact</strong>{release.operations_impact}</p> : null}

                  <dl className="pos-release-facts">
                    <div><dt>Package</dt><dd>{release.download_filename}</dd></div>
                    <div><dt>Size</dt><dd>{formatBytes(release.size_bytes)}</dd></div>
                    <div><dt>Published</dt><dd>{formatDate(release.published_at)}</dd></div>
                    <div><dt>Minimum OS</dt><dd>{release.minimum_os || 'Not specified'}</dd></div>
                  </dl>

                  <div className="pos-release-checksum">
                    <span>SHA-256 integrity checksum</span>
                    <code>{release.sha256}</code>
                    <button className="ghost-button" onClick={() => void copyChecksum(release)} type="button">
                      {copiedChecksum === release.id ? 'Copied' : 'Copy'}
                    </button>
                  </div>

                  <footer>
                    <span>{release.minimum_supported_build > 0 ? `Required below build ${release.minimum_supported_build}` : 'Advisory release'}</span>
                    <button
                      className="primary-button"
                      disabled={!catalogue.downloads_available || pending === release.id}
                      onClick={() => setSelectedRelease(release)}
                      type="button"
                    >
                      {pending === release.id ? 'Preparing…' : 'Review & download'}
                    </button>
                  </footer>
                </section>
              );
            })}
          </div>
        </>
      ) : (
        <EmptyState
          icon="store"
          title="No installers published"
          detail="Published POS builds appear here for download."
        />
      )}

      {selectedRelease ? (
        <div className="business-dialog-backdrop" role="presentation">
          <section aria-labelledby="pos-download-title" aria-modal="true" className="business-dialog" role="dialog">
            <header>
              <div><p className="eyebrow">Verified point of sale release</p><h2 id="pos-download-title">Review installer</h2></div>
              <button aria-label="Close dialog" disabled={pending === selectedRelease.id} onClick={() => setSelectedRelease(null)} type="button"><Icon name="close" /></button>
            </header>
            <div className="business-dialog-record"><div><code>{selectedRelease.platform} · {formatBytes(selectedRelease.size_bytes)}</code><strong>Version {selectedRelease.version}</strong><small>{selectedRelease.download_filename}</small></div></div>
            <p className="business-dialog-confirm"><Icon name="shield" /> Verify this SHA-256 checksum after download before installing on a device that processes transactions.</p>
            <div className="pos-download-review-facts">
              <div><span>Minimum OS</span><strong>{selectedRelease.minimum_os || 'Not specified'}</strong></div>
              <div><span>Published</span><strong>{formatDate(selectedRelease.published_at)}</strong></div>
            </div>
            <label className="business-field"><span>SHA-256</span><code className="pos-download-dialog-digest">{selectedRelease.sha256}</code></label>
            {selectedRelease.release_notes ? <p className="pos-download-dialog-notes">{selectedRelease.release_notes}</p> : null}
            <footer>
              <button className="secondary-button" disabled={pending === selectedRelease.id} onClick={() => setSelectedRelease(null)} type="button">Cancel</button>
              <button className="primary-button" disabled={pending === selectedRelease.id} onClick={() => void download(selectedRelease)} type="button">{pending === selectedRelease.id ? 'Preparing…' : 'Start secure download'}</button>
            </footer>
          </section>
        </div>
      ) : null}
    </article>
  );
}

function CashControlView({
  csrfToken,
  overview,
}: {
  readonly csrfToken: string;
  readonly overview: HQOverview;
}) {
  const selectableTenants = useMemo(
    () => overview.network_items.filter((item) => item.status === 'ACTIVE'),
    [overview.network_items],
  );
  const [tenantId, setTenantId] = useState(
    overview.tenant_id || selectableTenants[0]?.id || '',
  );

  useEffect(() => {
    const nextTenantId = overview.tenant_id
      || (selectableTenants.some((tenant) => tenant.id === tenantId)
        ? tenantId
        : selectableTenants[0]?.id || '');
    if (nextTenantId !== tenantId) setTenantId(nextTenantId);
  }, [overview.tenant_id, selectableTenants, tenantId]);

  if (!tenantId) {
    return <TenantWorkspaceRequired domain="cash control" />;
  }

  return (
    <>
      {overview.is_platform_overview ? (
        <section className="procurement-scope panel">
          <div>
            <p className="eyebrow">Tenant cash authority</p>
            <h2>Register &amp; shift workspace</h2>
            <span>Till sessions, cash movements, declarations and variances stay isolated to one pharmacy tenant.</span>
          </div>
          <label>
            <span>Operating tenant</span>
            <select onChange={(event) => setTenantId(event.target.value)} value={tenantId}>
              {selectableTenants.map((tenant) => (
                <option key={tenant.id} value={tenant.id}>{tenant.name}</option>
              ))}
            </select>
          </label>
        </section>
      ) : null}
      <TenantCashControlView csrfToken={csrfToken} tenantId={tenantId} />
    </>
  );
}

function TenantCashControlView({
  csrfToken,
  tenantId,
}: {
  readonly csrfToken: string;
  readonly tenantId: string;
}) {
  const [open, setOpen] = useState<readonly RegisterSessionSummary[] | null>(null);
  const [unclosed, setUnclosed] = useState<readonly RegisterSessionSummary[] | null>(null);
  const [variances, setVariances] = useState<readonly ShiftReportSummary[] | null>(null);
  const [forced, setForced] = useState<readonly ShiftReportSummary[] | null>(null);
  const [tills, setTills] = useState<readonly PosRegisterItem[] | null>(null);
  const [movements, setMovements] = useState<readonly CashMovementItem[] | null>(null);
  const [declarations, setDeclarations] = useState<readonly CashDeclarationItem[] | null>(null);
  const [businessDays, setBusinessDays] = useState<readonly BusinessDayItem[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [cashReload, setCashReload] = useState(0);
  const [movementReview, setMovementReview] = useState<CashMovementItem | null>(null);
  const [movementBusy, setMovementBusy] = useState(false);
  const [movementError, setMovementError] = useState('');
  const [cashNotice, setCashNotice] = useState('');
  const [cashReviewAction, setCashReviewAction] = useState<{
    readonly action: 'resolve' | 'start';
    readonly report: ShiftReportSummary;
  } | null>(null);
  const [cashReviewNote, setCashReviewNote] = useState('');
  const [cashReviewBusy, setCashReviewBusy] = useState(false);
  const [cashReviewError, setCashReviewError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      loadOpenRegisterSessions(tenantId, controller.signal),
      loadUnclosedRegisterSessions(tenantId, controller.signal),
      loadCashVariances(tenantId, controller.signal),
      loadForcedClosures(tenantId, controller.signal),
      loadPosRegisters(tenantId, controller.signal),
      loadCashMovements(tenantId, controller.signal),
      loadCashDeclarations(tenantId, controller.signal),
      loadBusinessDays(tenantId, controller.signal),
    ])
      .then(([a, u, b, c, t, m, d, bd]) => {
        setOpen(a);
        setUnclosed(u);
        setVariances(b);
        setForced(c);
        setTills(t);
        setMovements(m);
        setDeclarations(d);
        setBusinessDays(bd);
        setFailed(false);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [cashReload, tenantId]);

  if (failed) return <Unavailable />;
  if (!open || !unclosed || !variances || !forced || !tills || !movements || !declarations || !businessDays) {
    return <p className="muted-cell">Loading cash control data…</p>;
  }

  const pendingMovements = movements.filter((movement) => movement.approved_at === null);

  return (
    <>
      <article className="panel cash-control-guide">
        <PanelHeader eyebrow="Accountable cash workflow" title="Count, trade, approve, close and reconcile" />
        <div className="cash-control-steps" aria-label="Cash control workflow">
          <div><span>1</span><strong>Blind opening count</strong><small>The operator counts denominations before the till opens.</small></div>
          <div><span>2</span><strong>Controlled movements</strong><small>Safe drops, banking and cash adjustments require a reason.</small></div>
          <div><span>3</span><strong>Independent approval</strong><small>A second authorised operator approves non-sale movements.</small></div>
          <div><span>4</span><strong>Blind closing count</strong><small>The till creates one immutable Z report and reveals variance after count.</small></div>
          <div><span>5</span><strong>HQ exception review</strong><small>HQ monitors variances, forced closures and sessions without a Z report.</small></div>
        </div>
        {cashNotice ? <p className="inline-alert" role="status"><Icon name="check" /> {cashNotice}</p> : null}
      </article>

      <section className="metric-grid network-metrics" aria-label="Cash control totals">
        <SummaryCard
          detail="Physical registers configured"
          icon="building"
          label="Physical Tills"
          value={tills ? tills.length : open.length}
          onActivate={() => document.getElementById('cash-tills')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
        />
        <SummaryCard
          detail="Open register sessions"
          icon="activity"
          label="Tills still trading"
          tone={open.length ? 'amber' : 'navy'}
          value={open.length}
          onActivate={() => document.getElementById('cash-open-sessions')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
        />
        <SummaryCard
          detail="Z reports carrying a variance"
          icon="alert"
          label="Drawers that did not balance"
          tone={variances.length ? 'rose' : 'navy'}
          value={variances.length}
          onActivate={() => document.getElementById('cash-variances')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
        />
        <SummaryCard
          detail="Closed by somebody other than the operator"
          icon="shield"
          label="Forced closures"
          tone={forced.length ? 'amber' : 'navy'}
          value={forced.length}
          onActivate={() => document.getElementById('cash-forced')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
        />
        <SummaryCard
          detail="Require a second authorised operator"
          icon="shield"
          label="Movements awaiting approval"
          tone={pendingMovements.length ? 'rose' : 'teal'}
          value={pendingMovements.length}
          onActivate={() => document.getElementById('cash-movements')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
        />
      </section>

      <PosDownloads csrfToken={csrfToken} />

      {unclosed.length > 0 ? (
        <article className="panel cash-exception-panel">
          <PanelHeader eyebrow="Blocking Exception" title="Sessions without an authoritative Z report" />
          <p className="inline-alert" role="alert">
            <Icon name="alert" />
            These sessions reached closing state without a final Z report. Investigate before
            banking or reopening the register.
          </p>
          <div className="table-scroll">
            <table>
              <thead><tr><th>Register</th><th>Business date</th><th>Opened by</th><th>Opened</th><th>State</th></tr></thead>
              <tbody>
                {unclosed.map((session) => (
                  <tr key={session.id}>
                    <td><code>{session.register_code}</code></td>
                    <td>{session.business_date}</td>
                    <td>{session.opened_by_username}</td>
                    <td><span className="muted-cell">{formatDateTime(session.opened_at)}</span></td>
                    <td><StatusBadge value={session.state} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      ) : null}

      <article className="panel" id="cash-open-sessions" style={{ marginBottom: '24px' }}>
        <PanelHeader eyebrow="Live Accountability" title="Open Register Sessions" />
        {open.length === 0 ? (
          <EmptyState detail="No register session is currently trading." icon="check" title="All tills closed" />
        ) : (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Register</th><th>Business date</th><th>Opened by</th><th>Opened</th><th>Final Z</th><th>State</th></tr></thead>
              <tbody>
                {open.map((session) => (
                  <tr key={session.id}>
                    <td><code>{session.register_code}</code></td>
                    <td>{session.business_date}</td>
                    <td>{session.opened_by_username}</td>
                    <td><span className="muted-cell">{formatDateTime(session.opened_at)}</span></td>
                    <td>{session.has_final_report ? <StatusBadge value="RECORDED" /> : <span className="muted-cell">Pending closure</span>}</td>
                    <td><StatusBadge value={session.state} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </article>

      {/* Till Registers Directory */}
      <article className="panel" id="cash-tills" style={{ marginBottom: '24px' }}>
        <PanelHeader eyebrow="Till Infrastructure" title="Physical POS Register Directory" />
        {!tills ? (
          <p className="muted-cell">Loading physical tills…</p>
        ) : tills.length === 0 ? (
          <EmptyState detail="No physical tills configured." icon="building" title="No registers" />
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Code & Name</th>
                  <th>Device ID</th>
                  <th>Expected Float</th>
                  <th>Last Synchronised</th>
                  <th>State</th>
                </tr>
              </thead>
              <tbody>
                {tills.map((till) => (
                  <tr key={till.id}>
                    <td>
                      <code>{till.code}</code>
                      <br />
                      <strong>{till.name}</strong>
                    </td>
                    <td><code>{till.device_id || 'Unbound'}</code></td>
                    <td>{formatMoney(till.expected_float, till.currency)}</td>
                    <td>
                      <span className="muted-cell">
                        {till.last_synchronised_at ? formatDate(till.last_synchronised_at) : 'Never'}
                      </span>
                    </td>
                    <td>
                      <span className={`status-badge status-${till.state === 'OPEN' || till.state === 'AVAILABLE' ? 'active' : 'suspended'}`}>
                        <i /> {titleCase(till.state)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </article>

      <section className="content-grid content-grid-primary">
        <article className="panel" id="cash-variances">
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
                    <th>Reconciliation</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {variances.map((report) => {
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
                        <td>
                          {report.cash_exception_review ? (
                            <>
                              <StatusBadge value={report.cash_exception_review.status} />
                              <small className="row-detail">
                                Opened by {report.cash_exception_review.opened_by_username}
                              </small>
                            </>
                          ) : <StatusBadge value="UNREVIEWED" />}
                        </td>
                        <td>
                          {report.cash_exception_review?.status === 'RESOLVED' ? (
                            <span className="muted-cell">Resolved</span>
                          ) : (
                            <button
                              className="secondary-button"
                              onClick={() => {
                                setCashReviewError('');
                                setCashReviewNote('');
                                setCashReviewAction({
                                  action: report.cash_exception_review ? 'resolve' : 'start',
                                  report,
                                });
                              }}
                              type="button"
                            >
                              {report.cash_exception_review ? 'Resolve investigation' : 'Start investigation'}
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </article>

        <article className="panel" id="cash-forced">
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
                    <th>Reconciliation</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {forced.map((report) => (
                    <tr key={report.id}>
                      <td><code>{report.report_number}</code></td>
                      <td>{report.register_code}</td>
                      <td>{report.generated_by_username}</td>
                      <td><span className="muted-cell">{report.closure_reason || '—'}</span></td>
                      <td>
                        <StatusBadge value={report.cash_exception_review?.status ?? 'UNREVIEWED'} />
                      </td>
                      <td>
                        {report.cash_exception_review?.status === 'RESOLVED' ? (
                          <span className="muted-cell">Resolved</span>
                        ) : (
                          <button
                            className="secondary-button"
                            onClick={() => {
                              setCashReviewError('');
                              setCashReviewNote('');
                              setCashReviewAction({
                                action: report.cash_exception_review ? 'resolve' : 'start',
                                report,
                              });
                            }}
                            type="button"
                          >
                            {report.cash_exception_review ? 'Resolve investigation' : 'Start investigation'}
                          </button>
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

      {/* Cash Movements & Outflow Custody */}
      <section className="content-grid content-grid-primary" style={{ marginTop: '24px' }}>
        <article className="panel" id="cash-movements">
          <PanelHeader eyebrow="Custody Movements" title="Drawer Cash Inflows & Outflows" />
          {!movements ? (
            <p className="muted-cell">Loading cash movements…</p>
          ) : movements.length === 0 ? (
            <EmptyState detail="No non-sale cash movements recorded." icon="check" title="No movements" />
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Register</th>
                    <th>Movement Kind</th>
                    <th>Amount</th>
                    <th>Reason / Code</th>
                    <th>Reference</th>
                    <th>Custody</th>
                    <th>Created</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {movements.map((m) => (
                    <tr key={m.id}>
                      <td><code>{m.register_code}</code></td>
                      <td><strong>{titleCase(m.kind)}</strong></td>
                      <td>
                        <strong className={m.kind.includes('OUT') || m.kind.includes('DROP') || m.kind.includes('BANKING') ? 'text-rose' : ''}>
                          {formatMoney(m.amount, m.currency)}
                        </strong>
                      </td>
                      <td><small>{m.reason_code || m.description || '—'}</small></td>
                      <td><code>{m.reference || '—'}</code></td>
                      <td>
                        <small>Recorded by {m.created_by_username}</small>
                        <br />
                        {m.approved_at ? (
                          <span className="status-badge status-active"><i /> Approved by {m.approved_by_username}</span>
                        ) : (
                          <span className="status-badge status-warning"><i /> Awaiting approval</span>
                        )}
                      </td>
                      <td><span className="muted-cell">{formatDate(m.created_at)}</span></td>
                      <td>
                        {m.approved_at ? (
                          <span className="muted-cell">Complete</span>
                        ) : (
                          <button
                            className="secondary-button"
                            onClick={() => {
                              setMovementError('');
                              setMovementReview(m);
                            }}
                            type="button"
                          >
                            Review approval
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>

        <article className="panel">
          <PanelHeader eyebrow="Blind Count Audit" title="Opening & Closing Declarations" />
          {!declarations ? (
            <p className="muted-cell">Loading cash declarations…</p>
          ) : declarations.length === 0 ? (
            <EmptyState detail="No cash declarations recorded." icon="shield" title="No declarations" />
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Register</th>
                    <th>Kind</th>
                    <th>Declared Amount</th>
                    <th>Attempt</th>
                    <th>Declared By</th>
                    <th>Confirmed At</th>
                  </tr>
                </thead>
                <tbody>
                  {declarations.map((d) => (
                    <tr key={d.id}>
                      <td><code>{d.register_code}</code></td>
                      <td><span className="status-badge status-active"><i /> {d.kind}</span></td>
                      <td><strong>{formatMoney(d.declared_amount, d.currency)}</strong></td>
                      <td>Attempt #{d.attempt}</td>
                      <td>{d.declared_by_username}</td>
                      <td><span className="muted-cell">{d.confirmed_at ? formatDate(d.confirmed_at) : 'Unconfirmed'}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>
      </section>

      {/* Business Day Accounting Calendar */}
      {businessDays && businessDays.length > 0 ? (
        <article className="panel" style={{ marginTop: '24px' }}>
          <PanelHeader eyebrow="Accounting Periods" title="Business Days Calendar" />
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Business Date</th>
                  <th>Opened At</th>
                  <th>Closed At</th>
                  <th>State</th>
                  <th>Reopen Reason</th>
                </tr>
              </thead>
              <tbody>
                {businessDays.map((bd) => (
                  <tr key={bd.id}>
                    <td><strong>{bd.business_date}</strong></td>
                    <td><small>{formatDate(bd.opened_at)}</small></td>
                    <td><small className="muted-cell">{bd.closed_at ? formatDate(bd.closed_at) : '—'}</small></td>
                    <td><span className={`status-badge status-${bd.state === 'OPEN' ? 'active' : 'suspended'}`}><i /> {titleCase(bd.state)}</span></td>
                    <td><small className="muted-cell">{bd.reopen_reason || '—'}</small></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      ) : null}
      {cashReviewAction ? (
        <div className="business-dialog-backdrop" role="presentation">
          <section aria-labelledby="cash-exception-review-title" aria-modal="true" className="business-dialog" role="dialog">
            <header>
              <div>
                <p className="eyebrow">Cash exception reconciliation</p>
                <h2 id="cash-exception-review-title">
                  {cashReviewAction.action === 'start' ? 'Start cash investigation' : 'Resolve cash investigation'}
                </h2>
              </div>
              <button
                aria-label="Close dialog"
                disabled={cashReviewBusy}
                onClick={() => setCashReviewAction(null)}
                type="button"
              >
                <Icon name="close" />
              </button>
            </header>
            <div className="business-dialog-record">
              <div>
                <code>{cashReviewAction.report.report_number}</code>
                <strong>{cashReviewAction.report.register_code} · {cashReviewAction.report.business_date}</strong>
                <small>
                  {cashReviewAction.report.closure_type === 'FORCED'
                    ? `Forced closure: ${cashReviewAction.report.closure_reason}`
                    : `Variance: ${formatMoney(cashReviewAction.report.snapshot.variance?.difference)}`}
                </small>
              </div>
            </div>
            {cashReviewAction.report.cash_exception_review ? (
              <dl className="cash-review-details">
                <div><dt>Opened by</dt><dd>{cashReviewAction.report.cash_exception_review.opened_by_username}</dd></div>
                <div><dt>Opening note</dt><dd>{cashReviewAction.report.cash_exception_review.opening_note}</dd></div>
                <div><dt>Opened at</dt><dd>{formatDateTime(cashReviewAction.report.cash_exception_review.opened_at)}</dd></div>
              </dl>
            ) : null}
            <label className="business-field">
              <span>
                {cashReviewAction.action === 'start' ? 'Investigation opening note' : 'Resolution and evidence note'}
              </span>
              <textarea
                onChange={(event) => setCashReviewNote(event.target.value)}
                placeholder={
                  cashReviewAction.action === 'start'
                    ? 'Describe what must be checked, who holds the drawer evidence, and the next control step.'
                    : 'Record the verified cause, supporting reference, corrective action, and final disposition.'
                }
                required
                rows={5}
                value={cashReviewNote}
              />
            </label>
            <p className="business-dialog-confirm">
              <Icon name="shield" />
              {cashReviewAction.action === 'start'
                ? 'The Z-report generator cannot review their own exception.'
                : 'The investigator who opened this review cannot also resolve it. A second authorised person must sign off.'}
            </p>
            {cashReviewError ? <p className="business-dialog-error" role="alert"><Icon name="alert" /> {cashReviewError}</p> : null}
            <footer>
              <button
                className="secondary-button"
                disabled={cashReviewBusy}
                onClick={() => setCashReviewAction(null)}
                type="button"
              >
                Cancel
              </button>
              <button
                className="primary-button"
                disabled={cashReviewBusy || !cashReviewNote.trim()}
                onClick={async () => {
                  setCashReviewBusy(true);
                  setCashReviewError('');
                  try {
                    const review = cashReviewAction.action === 'start'
                      ? await startCashExceptionReview(
                        cashReviewAction.report.id,
                        cashReviewNote,
                        csrfToken,
                      )
                      : await resolveCashExceptionReview(
                        cashReviewAction.report.id,
                        cashReviewNote,
                        csrfToken,
                      );
                    setCashNotice(
                      `${review.report_number} cash investigation is now ${titleCase(review.status)}.`,
                    );
                    setCashReviewAction(null);
                    setCashReload((value) => value + 1);
                  } catch (reason) {
                    setCashReviewError(
                      reason instanceof Error ? reason.message : 'The cash review action failed.',
                    );
                  } finally {
                    setCashReviewBusy(false);
                  }
                }}
                type="button"
              >
                {cashReviewBusy
                  ? 'Recording…'
                  : cashReviewAction.action === 'start'
                    ? 'Start investigation'
                    : 'Resolve investigation'}
              </button>
            </footer>
          </section>
        </div>
      ) : null}
      {movementReview ? (
        <div className="business-dialog-backdrop" role="presentation">
          <section aria-labelledby="cash-movement-approval-title" aria-modal="true" className="business-dialog" role="dialog">
            <header>
              <div>
                <p className="eyebrow">Second-person cash custody</p>
                <h2 id="cash-movement-approval-title">Approve cash movement</h2>
              </div>
              <button
                aria-label="Close dialog"
                disabled={movementBusy}
                onClick={() => setMovementReview(null)}
                type="button"
              >
                <Icon name="close" />
              </button>
            </header>
            <div className="business-dialog-record">
              <div>
                <code>{movementReview.register_code} · {titleCase(movementReview.kind)}</code>
                <strong>{formatMoney(movementReview.amount, movementReview.currency)}</strong>
                <small>Recorded by {movementReview.created_by_username}</small>
              </div>
            </div>
            <dl className="cash-review-details">
              <div><dt>Reason code</dt><dd>{movementReview.reason_code}</dd></div>
              <div><dt>Reference</dt><dd>{movementReview.reference || 'Not supplied'}</dd></div>
              <div><dt>Description</dt><dd>{movementReview.description || 'Not supplied'}</dd></div>
              <div><dt>Expected cash effect</dt><dd>{formatMoney(movementReview.signed_amount, movementReview.currency)}</dd></div>
            </dl>
            <p className="business-dialog-confirm">
              <Icon name="shield" />
              Approval confirms that a different authorised operator checked the physical
              custody event. The creator cannot approve their own movement.
            </p>
            {movementError ? <p className="business-dialog-error" role="alert"><Icon name="alert" /> {movementError}</p> : null}
            <footer>
              <button
                className="secondary-button"
                disabled={movementBusy}
                onClick={() => setMovementReview(null)}
                type="button"
              >
                Cancel
              </button>
              <button
                className="primary-button"
                disabled={movementBusy}
                onClick={async () => {
                  setMovementBusy(true);
                  setMovementError('');
                  try {
                    const approved = await approveCashMovement(movementReview.id, csrfToken);
                    setCashNotice(
                      `${titleCase(approved.kind)} on ${approved.register_code} approved by ${approved.approved_by_username}.`,
                    );
                    setMovementReview(null);
                    setCashReload((value) => value + 1);
                  } catch (reason) {
                    setMovementError(
                      reason instanceof Error ? reason.message : 'The cash movement could not be approved.',
                    );
                  } finally {
                    setMovementBusy(false);
                  }
                }}
                type="button"
              >
                {movementBusy ? 'Approving…' : 'Approve movement'}
              </button>
            </footer>
          </section>
        </div>
      ) : null}
    </>
  );
}

function ClaimsRegister({ tenantId }: { readonly tenantId: string }) {
  const [filters, setFilters] = useState<ClaimFilters>({});
  const [claims, setClaims] = useState<readonly InsuranceClaim[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setFailed(false);
    setClaims(null);
    // Filters go to the server. Filtering a fetched page in the browser reports
    // "3 rejected" when the register holds four hundred, and the number looks
    // authoritative because it was counted rather than guessed.
    loadClaims(tenantId, filters, controller.signal)
      .then(setClaims)
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [filters, tenantId]);

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

function InsuranceView({
  csrfToken,
  overview,
}: {
  readonly csrfToken: string;
  readonly overview: HQOverview;
}) {
  const selectableTenants = useMemo(
    () => overview.network_items.filter((item) => item.status === 'ACTIVE'),
    [overview.network_items],
  );
  const [tenantId, setTenantId] = useState(
    overview.tenant_id || selectableTenants[0]?.id || '',
  );

  useEffect(() => {
    const nextTenantId = overview.tenant_id
      || (selectableTenants.some((tenant) => tenant.id === tenantId)
        ? tenantId
        : selectableTenants[0]?.id || '');
    if (nextTenantId !== tenantId) setTenantId(nextTenantId);
  }, [overview.tenant_id, selectableTenants, tenantId]);

  if (!tenantId) {
    return <TenantWorkspaceRequired domain="insurance claims" />;
  }

  return (
    <>
      {overview.is_platform_overview ? (
        <section className="procurement-scope panel">
          <div>
            <p className="eyebrow">Tenant claims authority</p>
            <h2>Prescription insurance workspace</h2>
            <span>Insurer integrations, claims, remittances and coverages stay isolated to one pharmacy tenant.</span>
          </div>
          <label>
            <span>Operating tenant</span>
            <select onChange={(event) => setTenantId(event.target.value)} value={tenantId}>
              {selectableTenants.map((tenant) => (
                <option key={tenant.id} value={tenant.id}>{tenant.name}</option>
              ))}
            </select>
          </label>
        </section>
      ) : null}
      <TenantInsuranceView csrfToken={csrfToken} tenantId={tenantId} />
    </>
  );
}

function TenantInsuranceView({
  csrfToken,
  tenantId,
}: {
  readonly csrfToken: string;
  readonly tenantId: string;
}) {
  const [insurers, setInsurers] = useState<readonly Insurer[] | null>(null);
  const [unpaid, setUnpaid] = useState<readonly InsuranceClaim[] | null>(null);
  const [awaiting, setAwaiting] = useState<readonly InsuranceClaim[] | null>(null);
  const [attention, setAttention] = useState<readonly InsuranceClaim[] | null>(null);
  const [remittances, setRemittances] = useState<readonly InsuranceRemittance[] | null>(null);
  const [rejections, setRejections] = useState<readonly ClaimRejection[] | null>(null);
  const [coverages, setCoverages] = useState<readonly InsuranceCoverage[] | null>(null);
  const [failed, setFailed] = useState(false);

  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [insurerType, setInsurerType] = useState('PUBLIC');
  const [adapter, setAdapter] = useState('SHA');
  const [env, setEnv] = useState('SANDBOX');
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState('');

  const fetchInsurers = useCallback((signal?: AbortSignal) => {
    loadInsurers(tenantId, signal)
      .then(setInsurers)
      .catch(() => {
        if (!signal?.aborted) setFailed(true);
      });
  }, [tenantId]);

  useEffect(() => {
    const controller = new AbortController();
    setFailed(false);
    setInsurers(null);
    setUnpaid(null);
    setAwaiting(null);
    setAttention(null);
    setRemittances(null);
    setRejections(null);
    setCoverages(null);
    Promise.all([
      loadInsurers(tenantId, controller.signal),
      loadApprovedUnpaidClaims(tenantId, controller.signal),
      loadClaimsAwaitingDecision(tenantId, controller.signal),
      loadClaimsNeedingAttention(tenantId, controller.signal),
      loadRemittances(tenantId, controller.signal),
      loadRejections(tenantId, true, controller.signal),
      loadCoverages(tenantId, controller.signal),
    ])
      .then(([a, b, c, d, r, rej, cov]) => {
        setInsurers(a);
        setUnpaid(b);
        setAwaiting(c);
        setAttention(d);
        setRemittances(r);
        setRejections(rej);
        setCoverages(cov);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [tenantId]);

  const handleCreateInsurer = async (e: FormEvent) => {
    e.preventDefault();
    setCreateBusy(true);
    setCreateError('');
    try {
      await createInsurer(
        {
          code: code.trim(),
          name: name.trim(),
          insurer_type: insurerType,
          integration_adapter: adapter,
          environment: env,
          status: 'ACTIVE',
        },
        csrfToken,
        tenantId,
      );
      setCreateModalOpen(false);
      setCode('');
      setName('');
      setInsurerType('PUBLIC');
      setAdapter('SHA');
      setEnv('SANDBOX');
      fetchInsurers();
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : 'Could not configure insurer integration.');
    } finally {
      setCreateBusy(false);
    }
  };

  if (failed) return <Unavailable />;
  if (!insurers || !unpaid || !awaiting || !attention) {
    return <p className="muted-cell">Loading insurance data…</p>;
  }

  const receivable = unpaid.reduce(
    (total, claim) => total + Number.parseFloat(claim.outstanding_amount || '0'),
    0,
  );

  return (
    <>
      <section className="metric-grid network-metrics" aria-label="Insurance claim positions">
        <SummaryCard targetId="insurance-register" icon="insurance" label="Awaiting insurer decision" value={awaiting.length} detail="Sent and acknowledged, not yet adjudicated" />
        <SummaryCard targetId="insurance-unpaid" icon="check" label="Approved, unpaid" value={unpaid.length} detail="Insurer agreed to pay and has not paid" tone="teal" />
        <SummaryCard targetId="insurance-attention" icon="alert" label="Needs attention here" value={attention.length} detail="Rejected, or blocked on this end" tone="rose" />
        <SummaryCard targetId="insurance-remittances" icon="building" label="Receivable" value={Math.round(receivable)} detail="Approved less received, this tenant" tone="amber" />
      </section>

      <section className="content-grid content-grid-primary">
        <article className="panel">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '12px' }}>
            <PanelHeader eyebrow="Insurer integrations" title="Configured insurers" actionHref="#insurance" actionLabel="Open insurance workspace" />
            <button
              className="primary-button"
              onClick={() => {
                setCreateError('');
                setCreateModalOpen(true);
              }}
              type="button"
            >
              <Icon name="insurance" /> + Configure Insurer Integration
            </button>
          </div>

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

        <article className="panel" id="insurance-unpaid">
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

        <article className="panel" id="insurance-attention">
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

      {/* Remittances & Financial Settlement */}
      <section className="content-grid content-grid-primary" style={{ marginTop: '24px' }} id="insurance-remittances">
        <article className="panel">
          <PanelHeader eyebrow="Remittance Advice" title="Payment Settlements & Bank Remittances" />
          {!remittances ? (
            <p className="muted-cell">Loading remittance advice…</p>
          ) : remittances.length === 0 ? (
            <EmptyState icon="check" title="No remittances" detail="Remittance advice notices will appear as payments settle." />
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Remittance #</th>
                    <th>Insurer</th>
                    <th>Remitted Total</th>
                    <th>Payment Ref</th>
                    <th>Remittance Date</th>
                    <th>Unmatched Lines</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {remittances.map((rem) => (
                    <tr key={rem.id}>
                      <td><code>{rem.remittance_number}</code></td>
                      <td><small>{rem.insurer_code}</small></td>
                      <td><strong>{formatMoney(rem.total_remitted_amount, 'KES')}</strong></td>
                      <td><code>{rem.payment_reference || '—'}</code></td>
                      <td><span className="muted-cell">{formatDate(rem.remittance_date)}</span></td>
                      <td>
                        {rem.unmatched_lines > 0 ? (
                          <span className="status-badge status-suspended"><i /> {rem.unmatched_lines} unmatched</span>
                        ) : (
                          <span className="muted-cell">0</span>
                        )}
                      </td>
                      <td><span className="status-badge status-active"><i /> {titleCase(rem.status)}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>

        <article className="panel">
          <PanelHeader eyebrow="Claim Recovery" title="Unresolved Rejections & Exceptions" />
          {!rejections ? (
            <p className="muted-cell">Loading rejections watchlist…</p>
          ) : rejections.length === 0 ? (
            <EmptyState icon="check" title="No unresolved rejections" detail="All claim rejections have been resolved or resubmitted." />
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Claim #</th>
                    <th>Code</th>
                    <th>Reason</th>
                    <th>Resubmission</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {rejections.map((rej) => (
                    <tr key={rej.id}>
                      <td><code>{rej.claim_number}</code></td>
                      <td><code className="text-rose">{rej.rejection_code}</code></td>
                      <td><small>{rej.reason_description}</small></td>
                      <td>
                        {rej.resubmission_eligible ? (
                          <span className="status-badge status-active"><i /> Eligible</span>
                        ) : (
                          <span className="status-badge status-suspended"><i /> Final</span>
                        )}
                      </td>
                      <td><small className="muted-cell">{rej.operator_action || 'Review claim data'}</small></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>
      </section>

      {/* Member Coverages Watchlist */}
      {coverages && coverages.length > 0 ? (
        <article className="panel" style={{ marginTop: '24px' }}>
          <PanelHeader eyebrow="Member Eligibility" title="Active Insurance Policies & Benefit Limits" />
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Membership #</th>
                  <th>Relationship</th>
                  <th>Valid Range</th>
                  <th>Remaining Limit</th>
                  <th>Copay / Coinsurance</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {coverages.map((cov) => (
                  <tr key={cov.id}>
                    <td><code>{cov.membership_number}</code></td>
                    <td><small>{titleCase(cov.relationship)}</small></td>
                    <td><span className="muted-cell">{formatDate(cov.valid_from)} — {cov.valid_to ? formatDate(cov.valid_to) : 'Ongoing'}</span></td>
                    <td><strong>{formatMoney(cov.remaining_limit, 'KES')}</strong></td>
                    <td>
                      <small>
                        {formatMoney(cov.copay_amount, 'KES')} copay ({cov.coinsurance_percentage}% co-ins)
                      </small>
                    </td>
                    <td><span className="status-badge status-active"><i /> {titleCase(cov.status)}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      ) : null}

      <div id="insurance-register">
        <ClaimsRegister tenantId={tenantId} />
      </div>

      {createModalOpen ? (
        <div className="business-dialog-backdrop" role="presentation">
          <section aria-labelledby="create-insurer-title" aria-modal="true" className="business-dialog" role="dialog">
            <header>
              <div>
                <p className="eyebrow">Insurance & Claims Integration</p>
                <h2 id="create-insurer-title">Configure Insurer Integration</h2>
              </div>
              <button
                aria-label="Close dialog"
                disabled={createBusy}
                onClick={() => setCreateModalOpen(false)}
                type="button"
              >
                <Icon name="close" />
              </button>
            </header>
            <form onSubmit={(e) => void handleCreateInsurer(e)}>
              {createError ? <p className="business-dialog-error" role="alert"><Icon name="alert" /> {createError}</p> : null}

              <div className="tenant-form-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <label className="business-field">
                  <span>Insurer Code</span>
                  <input
                    onChange={(e) => setCode(e.target.value)}
                    placeholder="e.g. SHA-KE"
                    required
                    type="text"
                    value={code}
                  />
                </label>
                <label className="business-field">
                  <span>Insurer Name</span>
                  <input
                    onChange={(e) => setName(e.target.value)}
                    placeholder="e.g. Social Health Authority (SHA) Kenya"
                    required
                    type="text"
                    value={name}
                  />
                </label>
              </div>

              <div className="tenant-form-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px', marginTop: '12px' }}>
                <label className="business-field">
                  <span>Insurer Type</span>
                  <select
                    onChange={(e) => setInsurerType(e.target.value)}
                    value={insurerType}
                  >
                    <option value="PUBLIC">Public Health Financing Scheme</option>
                    <option value="PRIVATE">Private Medical Insurer</option>
                    <option value="EMPLOYER">Employer-Funded Scheme</option>
                    <option value="TPA">Third-Party Administrator</option>
                    <option value="COMMUNITY">Community Mutual Fund</option>
                  </select>
                </label>
                <label className="business-field">
                  <span>Integration Adapter</span>
                  <select
                    onChange={(e) => setAdapter(e.target.value)}
                    value={adapter}
                  >
                    <option value="SHA">Social Health Authority (SHA) Kenya API</option>
                    <option value="PRIVATE_REST">Generic Private Insurer REST API</option>
                    <option value="BATCH_FILE">SFTP / Batch File Export</option>
                    <option value="MANUAL_PORTAL">Manual Web Portal Submission</option>
                  </select>
                </label>
                <label className="business-field">
                  <span>Target Environment</span>
                  <select
                    onChange={(e) => setEnv(e.target.value)}
                    value={env}
                  >
                    <option value="SANDBOX">Sandbox / Test Environment</option>
                    <option value="PRODUCTION">Production Environment</option>
                  </select>
                </label>
              </div>

              <p className="business-dialog-confirm" style={{ marginTop: '16px' }}>
                <Icon name="shield" />
                This stores the insurer configuration. The readiness column confirms whether a transaction adapter is installed; endpoints and credentials are provisioned separately.
              </p>

              <footer style={{ marginTop: '20px', display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
                <button
                  className="secondary-button"
                  disabled={createBusy}
                  onClick={() => setCreateModalOpen(false)}
                  type="button"
                >
                  Cancel
                </button>
                <button
                  className="primary-button"
                  disabled={createBusy || !name.trim() || !code.trim()}
                  type="submit"
                >
                  {createBusy ? 'Saving Integration…' : 'Configure Integration'}
                </button>
              </footer>
            </form>
          </section>
        </div>
      ) : null}
    </>
  );
}

function PeopleView({
  csrfToken,
  data,
  failed,
  onWorkspaceChanged,
}: BusinessViewProps) {
  const [counterparties, setCounterparties] = useState<readonly CustomerItem[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [custNumber, setCustNumber] = useState('');
  const [legalName, setLegalName] = useState('');
  const [tradingName, setTradingName] = useState('');
  const [custType, setCustType] = useState('PHARMACY');
  const [regNumber, setRegNumber] = useState('');
  const [taxNumber, setTaxNumber] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [riskClass, setRiskClass] = useState('MEDIUM');
  const [controlledEligible, setControlledEligible] = useState(false);
  const [coldChainCapable, setColdChainCapable] = useState(false);
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState('');
  const [pendingAction, setPendingAction] = useState<{
    readonly action: 'activate' | 'approve' | 'begin-review' | 'reactivate' | 'suspend';
    readonly customer: CustomerItem;
  } | null>(null);
  const [actionReason, setActionReason] = useState('');
  const [actionError, setActionError] = useState('');

  const fetchCounterparties = useCallback((signal?: AbortSignal) => {
    loadCustomers(signal)
      .then(setCounterparties)
      .catch(() => {
        if (!signal?.aborted) setLoadError(true);
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetchCounterparties(controller.signal);
    return () => controller.abort();
  }, [fetchCounterparties]);

  const handleCustomerAction = async (e: FormEvent) => {
    e.preventDefault();
    if (!pendingAction) return;
    setBusyId(pendingAction.customer.id);
    setActionError('');
    try {
      const mutate = {
        activate: activateCustomer,
        approve: approveCustomer,
        'begin-review': beginCustomerReview,
        reactivate: reactivateCustomer,
        suspend: suspendCustomer,
      }[pendingAction.action];
      await mutate(pendingAction.customer.id, actionReason.trim(), csrfToken);
      setPendingAction(null);
      setActionReason('');
      fetchCounterparties();
      await onWorkspaceChanged();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Could not complete the customer action.');
    } finally {
      setBusyId(null);
    }
  };

  const handleCreateCustomer = async (e: FormEvent) => {
    e.preventDefault();
    setCreateBusy(true);
    setCreateError('');
    try {
      await createCustomer(
        {
          customer_number: custNumber.trim(),
          legal_name: legalName.trim(),
          trading_name: tradingName.trim() || undefined,
          customer_type: custType,
          registration_number: regNumber.trim() || undefined,
          tax_number: taxNumber.trim() || undefined,
          contact_email: email.trim() || undefined,
          contact_phone: phone.trim() || undefined,
          risk_classification: riskClass,
          controlled_medicine_eligible: controlledEligible,
          cold_chain_capable: coldChainCapable,
        },
        csrfToken,
      );
      setCreateModalOpen(false);
      setCustNumber('');
      setLegalName('');
      setTradingName('');
      setRegNumber('');
      setTaxNumber('');
      setEmail('');
      setPhone('');
      setCustType('PHARMACY');
      setRiskClass('MEDIUM');
      setControlledEligible(false);
      setColdChainCapable(false);
      fetchCounterparties();
      await onWorkspaceChanged();
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : 'Could not create customer counterparty.');
    } finally {
      setCreateBusy(false);
    }
  };

  if (failed) return <WorkspaceSectionError domain="people and customer" />;
  if (!data) return <WorkspaceSectionLoading domain="people and customer" />;

  const { counts, patients, practitioners } = data.people;
  const activeCustomersCount = counterparties ? counterparties.filter((c) => c.status === 'ACTIVE' || c.status === 'APPROVED').length : counts.customers;
  const scrollPeople = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <>
      <section className="metric-grid network-metrics" aria-label="People and customer totals">
        <SummaryCard icon="patients" label="Patient records" value={counts.patients} detail={`${formatNumber(counts.active_patients)} active`} onActivate={() => scrollPeople('people-patients')} />
        <SummaryCard icon="clinical" label="Practitioners" value={counts.practitioners} detail={`${formatNumber(counts.verified_practitioners)} verified`} tone="teal" onActivate={() => scrollPeople('people-practitioners')} />
        <SummaryCard icon="building" label="Counterparty Customers" value={counterparties ? counterparties.length : counts.customers} detail={`${formatNumber(activeCustomersCount)} active/approved`} onActivate={() => scrollPeople('people-customers')} />
        <SummaryCard icon="shield" label="Verification gap" value={Math.max(counts.practitioners - counts.verified_practitioners, 0)} detail="Practitioners needing review" tone={counts.practitioners === counts.verified_practitioners ? 'teal' : 'amber'} onActivate={() => scrollPeople('people-practitioners')} />
      </section>

      <div id="people-customers">
        <BusinessWorkbench csrfToken={csrfToken} data={data} domain="people" onChanged={onWorkspaceChanged} />
      </div>

      <section className="content-grid content-grid-primary">
        <article className="panel" id="people-patients">
          <PanelHeader eyebrow="Care records" title="Recently updated patients" />
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

        <article className="panel" id="people-practitioners">
          <PanelHeader eyebrow="Clinical workforce" title="Practitioner verification" />
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

      <article className="panel" style={{ marginTop: '24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '12px' }}>
          <PanelHeader eyebrow="Commercial Counterparties" title="Customer Governance Directory" />
          <button
            className="primary-button"
            onClick={() => {
              setCreateError('');
              setCreateModalOpen(true);
            }}
            type="button"
          >
            <Icon name="building" /> + Register Commercial Customer
          </button>
        </div>

        {loadError ? (
          <div className="inline-alert" role="alert"><Icon name="alert" /> Commercial customer counterparty records could not be loaded.</div>
        ) : counterparties === null ? (
          <p className="muted-cell">Loading customer counterparties…</p>
        ) : counterparties.length === 0 ? (
          <EmptyState icon="building" title="No commercial customers" detail="Approved pharmacy, hospital and institutional customers will appear here." />
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Legal & Trading Name</th>
                  <th>Customer #</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Risk & Credit</th>
                  <th>Capabilities</th>
                  <th>Governance Actions</th>
                </tr>
              </thead>
              <tbody>
                {counterparties.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <strong>{c.legal_name}</strong>
                      {c.trading_name && c.trading_name !== c.legal_name ? <small className="muted-cell"><br />{c.trading_name}</small> : null}
                    </td>
                    <td><code>{c.customer_number}</code></td>
                    <td><small>{titleCase(c.customer_type)}</small></td>
                    <td><StatusBadge value={c.status} /></td>
                    <td>
                      <small>
                        Risk: <StatusBadge value={c.risk_classification} /><br />
                        Credit: <StatusBadge value={c.credit_status} />
                      </small>
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                        {c.controlled_medicine_eligible ? <span className="status-badge status-active" style={{ fontSize: '0.65rem' }}>Controlled Meds</span> : null}
                        {c.cold_chain_capable ? <span className="status-badge status-teal" style={{ fontSize: '0.65rem' }}>Cold Chain</span> : null}
                        {!c.controlled_medicine_eligible && !c.cold_chain_capable ? <span className="muted-cell">Standard</span> : null}
                      </div>
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: '6px' }}>
                        {c.status === 'PROSPECTIVE' ? (
                          <button
                            className="segmented-option is-active"
                            disabled={busyId === c.id}
                            onClick={() => {
                              setActionError('');
                              setActionReason('');
                              setPendingAction({ action: 'begin-review', customer: c });
                            }}
                            style={{ padding: '2px 8px', fontSize: '0.75rem' }}
                            type="button"
                          >
                            Start Review
                          </button>
                        ) : null}
                        {c.status === 'UNDER_REVIEW' ? (
                          <button
                            className="segmented-option is-active"
                            disabled={busyId === c.id}
                            onClick={() => {
                              setActionError('');
                              setActionReason('');
                              setPendingAction({ action: 'approve', customer: c });
                            }}
                            style={{ padding: '2px 8px', fontSize: '0.75rem' }}
                            type="button"
                          >
                            Approve
                          </button>
                        ) : null}
                        {c.status === 'APPROVED' ? (
                          <button
                            className="segmented-option is-active"
                            disabled={busyId === c.id}
                            onClick={() => {
                              setActionError('');
                              setActionReason('');
                              setPendingAction({ action: 'activate', customer: c });
                            }}
                            style={{ padding: '2px 8px', fontSize: '0.75rem' }}
                            type="button"
                          >
                            Activate
                          </button>
                        ) : null}
                        {c.status === 'ACTIVE' ? (
                          <button
                            className="segmented-option"
                            disabled={busyId === c.id}
                            onClick={() => {
                              setActionError('');
                              setActionReason('');
                              setPendingAction({ action: 'suspend', customer: c });
                            }}
                            style={{ padding: '2px 8px', fontSize: '0.75rem', color: '#f43f5e' }}
                            type="button"
                          >
                            Suspend
                          </button>
                        ) : null}
                        {c.status === 'SUSPENDED' ? (
                          <button
                            className="segmented-option is-active"
                            disabled={busyId === c.id}
                            onClick={() => {
                              setActionError('');
                              setActionReason('');
                              setPendingAction({ action: 'reactivate', customer: c });
                            }}
                            style={{ padding: '2px 8px', fontSize: '0.75rem' }}
                            type="button"
                          >
                            Reactivate
                          </button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </article>

      {createModalOpen ? (
        <div className="business-dialog-backdrop" role="presentation">
          <section aria-labelledby="create-customer-title" aria-modal="true" className="business-dialog" role="dialog">
            <header>
              <div>
                <p className="eyebrow">Counterparty Governance</p>
                <h2 id="create-customer-title">Register Commercial Customer</h2>
              </div>
              <button
                aria-label="Close dialog"
                disabled={createBusy}
                onClick={() => setCreateModalOpen(false)}
                type="button"
              >
                <Icon name="close" />
              </button>
            </header>
            <form onSubmit={(e) => void handleCreateCustomer(e)}>
              {createError ? <p className="business-dialog-error" role="alert"><Icon name="alert" /> {createError}</p> : null}

              <div className="tenant-form-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <label className="business-field">
                  <span>Customer Number</span>
                  <input
                    onChange={(e) => setCustNumber(e.target.value)}
                    required
                    type="text"
                    value={custNumber}
                  />
                </label>
                <label className="business-field">
                  <span>Customer Type</span>
                  <select
                    onChange={(e) => setCustType(e.target.value)}
                    value={custType}
                  >
                    <option value="PHARMACY">Retail Pharmacy</option>
                    <option value="HOSPITAL">Hospital</option>
                    <option value="CLINIC">Clinic / Medical Centre</option>
                    <option value="WHOLESALER">Wholesaler</option>
                    <option value="DISTRIBUTOR">Distributor</option>
                    <option value="CORPORATE">Corporate Account</option>
                    <option value="INSURER">Insurer Account</option>
                    <option value="INDIVIDUAL">Individual Account</option>
                  </select>
                </label>
              </div>

              <div className="tenant-form-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginTop: '12px' }}>
                <label className="business-field">
                  <span>Legal Name</span>
                  <input
                    onChange={(e) => setLegalName(e.target.value)}
                    placeholder="e.g. Nairobi Health Chemists Ltd"
                    required
                    type="text"
                    value={legalName}
                  />
                </label>
                <label className="business-field">
                  <span>Trading Name</span>
                  <input
                    onChange={(e) => setTradingName(e.target.value)}
                    placeholder="e.g. HealthCare Pharmacy"
                    type="text"
                    value={tradingName}
                  />
                </label>
              </div>

              <div className="tenant-form-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px', marginTop: '12px' }}>
                <label className="business-field">
                  <span>Reg Number</span>
                  <input
                    onChange={(e) => setRegNumber(e.target.value)}
                    placeholder="e.g. CPR/2026/102"
                    type="text"
                    value={regNumber}
                  />
                </label>
                <label className="business-field">
                  <span>KRA Tax PIN</span>
                  <input
                    onChange={(e) => setTaxNumber(e.target.value)}
                    placeholder="e.g. P051234567Z"
                    type="text"
                    value={taxNumber}
                  />
                </label>
                <label className="business-field">
                  <span>Risk Rating</span>
                  <select
                    onChange={(e) => setRiskClass(e.target.value)}
                    value={riskClass}
                  >
                    <option value="LOW">Low Risk</option>
                    <option value="MEDIUM">Medium Risk</option>
                    <option value="HIGH">High Risk</option>
                    <option value="CRITICAL">Critical Risk</option>
                  </select>
                </label>
              </div>

              <div className="tenant-form-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginTop: '12px' }}>
                <label className="business-field">
                  <span>Contact Email</span>
                  <input
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="contact@pharmacy.co.ke"
                    type="email"
                    value={email}
                  />
                </label>
                <label className="business-field">
                  <span>Contact Phone</span>
                  <input
                    onChange={(e) => setPhone(e.target.value)}
                    placeholder="+254 700 000 000"
                    type="text"
                    value={phone}
                  />
                </label>
              </div>

              <div style={{ display: 'flex', gap: '16px', marginTop: '16px' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '0.85rem' }}>
                  <input
                    checked={controlledEligible}
                    onChange={(e) => setControlledEligible(e.target.checked)}
                    type="checkbox"
                  />
                  <span>Controlled Substance Eligible</span>
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '0.85rem' }}>
                  <input
                    checked={coldChainCapable}
                    onChange={(e) => setColdChainCapable(e.target.checked)}
                    type="checkbox"
                  />
                  <span>Cold Chain Capable</span>
                </label>
              </div>

              <footer style={{ marginTop: '20px', display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
                <button
                  className="secondary-button"
                  disabled={createBusy}
                  onClick={() => setCreateModalOpen(false)}
                  type="button"
                >
                  Cancel
                </button>
                <button
                  className="primary-button"
                  disabled={createBusy || !legalName.trim() || !custNumber.trim()}
                  type="submit"
                >
                  {createBusy ? 'Registering…' : 'Register Customer'}
                </button>
              </footer>
            </form>
          </section>
        </div>
      ) : null}

      {pendingAction ? (
        <div className="business-dialog-backdrop" role="presentation">
          <section aria-labelledby="customer-action-title" aria-modal="true" className="business-dialog" role="dialog">
            <header>
              <div>
                <p className="eyebrow">Customer Governance</p>
                <h2 id="customer-action-title">
                  {{
                    activate: 'Activate Customer',
                    approve: 'Approve Customer',
                    'begin-review': 'Begin Customer Review',
                    reactivate: 'Reactivate Customer',
                    suspend: 'Suspend Customer',
                  }[pendingAction.action]}
                </h2>
              </div>
              <button
                aria-label="Close dialog"
                disabled={busyId === pendingAction.customer.id}
                onClick={() => setPendingAction(null)}
                type="button"
              >
                <Icon name="close" />
              </button>
            </header>
            <form onSubmit={(e) => void handleCustomerAction(e)}>
              <div className="business-dialog-record">
                <div>
                  <code>{pendingAction.customer.customer_number}</code>
                  <strong>{pendingAction.customer.legal_name}</strong>
                </div>
              </div>
              <p className="business-dialog-confirm">
                <Icon name={pendingAction.action === 'suspend' ? 'alert' : 'shield'} />
                {{
                  activate: 'Activation enables this approved customer to pass active commercial policy checks.',
                  approve: 'Approval confirms that the customer has passed the tenant governance review.',
                  'begin-review': 'This moves the prospective customer into formal tenant governance review.',
                  reactivate: 'Reactivation restores this customer to active commercial policy checks.',
                  suspend: 'Suspension immediately prevents this customer from passing active customer policy checks.',
                }[pendingAction.action]}
              </p>
              <label className="business-field">
                <span>Reason</span>
                <textarea
                  onChange={(e) => setActionReason(e.target.value)}
                  placeholder="Record the business reason for this decision"
                  required
                  rows={3}
                  value={actionReason}
                />
              </label>
              {actionError ? <p className="business-dialog-error" role="alert"><Icon name="alert" /> {actionError}</p> : null}
              <footer>
                <button
                  className="secondary-button"
                  disabled={busyId === pendingAction.customer.id}
                  onClick={() => setPendingAction(null)}
                  type="button"
                >
                  Cancel
                </button>
                <button
                  className="primary-button"
                  disabled={busyId === pendingAction.customer.id || !actionReason.trim()}
                  type="submit"
                >
                  {busyId === pendingAction.customer.id
                    ? 'Applying…'
                    : {
                        activate: 'Confirm Activation',
                        approve: 'Confirm Approval',
                        'begin-review': 'Begin Review',
                        reactivate: 'Confirm Reactivation',
                        suspend: 'Confirm Suspension',
                      }[pendingAction.action]}
                </button>
              </footer>
            </form>
          </section>
        </div>
      ) : null}
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
  const scrollCatalogue = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  return (
    <>
      <section className="metric-grid network-metrics" aria-label="Medicine catalogue totals">
        <SummaryCard icon="inventory" label="Commercial SKUs" value={counts.skus} detail={`${formatNumber(counts.active_skus)} active`} onActivate={() => scrollCatalogue('catalogue-skus')} />
        <SummaryCard icon="clinical" label="Active substances" value={counts.substances} detail="Governed ingredient records" tone="teal" onActivate={() => scrollCatalogue('catalogue-layers')} />
        <SummaryCard icon="building" label="Manufacturers" value={counts.manufacturers} detail="Registered product sources" onActivate={() => scrollCatalogue('catalogue-layers')} />
        <SummaryCard icon="alert" label="Inactive SKUs" value={Math.max(counts.skus - counts.active_skus, 0)} detail="Draft, inactive or recalled" tone={counts.skus === counts.active_skus ? 'teal' : 'amber'} onActivate={() => scrollCatalogue('catalogue-skus')} />
      </section>

      <GovernmentCatalogue csrfToken={csrfToken} overview={overview} />

      <BusinessWorkbench csrfToken={csrfToken} data={data} domain="catalogue" onChanged={onWorkspaceChanged} />

      <article className="panel table-panel" id="catalogue-skus">
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

      <div id="catalogue-layers">
        <CatalogueLayers />
      </div>
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
  const [pendingSelection, setPendingSelection] = useState<{
    readonly medicineId: string;
    readonly productName: string;
    readonly selected: boolean;
  } | null>(null);
  const [reloadVersion, setReloadVersion] = useState(0);
  const [priceModal, setPriceModal] = useState<{
    readonly code: string;
    readonly name: string;
  } | null>(null);
  const [modalUnitPrice, setModalUnitPrice] = useState('250.00');
  const [modalMinPrice, setModalMinPrice] = useState('200.00');
  const [modalTaxInc, setModalTaxInc] = useState(true);
  const [tenantSkus, setTenantSkus] = useState<readonly HQSku[]>([]);
  const [priceSkuCode, setPriceSkuCode] = useState('');
  const [priceSubmitting, setPriceSubmitting] = useState(false);
  const [priceSuccess, setPriceSuccess] = useState('');
  const [priceError, setPriceError] = useState('');

  useEffect(() => {
    const nextTenantId = overview.tenant_id || overview.network_items[0]?.id || '';
    setTenantId((current) => current || nextTenantId);
  }, [overview.network_items, overview.tenant_id]);

  useEffect(() => {
    if (!tenantId) {
      setTenantSkus([]);
      return;
    }
    const controller = new AbortController();
    loadTenantSkus(tenantId, controller.signal)
      .then((skus) => {
        setTenantSkus(skus);
        setPriceSkuCode((current) => (
          skus.some((sku) => sku.sku_code === current) ? current : ''
        ));
      })
      .catch(() => {
        if (!controller.signal.aborted) setTenantSkus([]);
      });
    return () => controller.abort();
  }, [tenantId]);

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
  const changeSelection = async (medicineId: string, selected: boolean): Promise<boolean> => {
    if (!tenantId) return false;
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
      return true;
    } catch (reason) {
      setMutationError(
        reason instanceof Error ? reason.message : 'The tenant catalogue could not be updated.',
      );
    } finally {
      setMutationId('');
    }
    return false;
  };
  const confirmSelection = async () => {
    if (!pendingSelection) return;
    const changed = await changeSelection(pendingSelection.medicineId, pendingSelection.selected);
    if (changed) setPendingSelection(null);
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
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                        {medicine.selected ? (
                          <>
                            <span className="reference-badge is-selected">Selected</span>
                            <button
                              className="segmented-option is-active"
                              onClick={() => {
                                setPriceModal({
                                  code: medicine.code,
                                  name: medicine.generic_name || medicine.brand_name || medicine.code,
                                });
                                setPriceSkuCode(
                                  tenantSkus.find((sku) => sku.sku_code === medicine.code)?.sku_code ?? '',
                                );
                                setPriceSuccess('');
                                setPriceError('');
                              }}
                              style={{ padding: '2px 8px', fontSize: '0.72rem' }}
                              type="button"
                            >
                              Create price draft
                            </button>
                            {catalogueMode === 'tenant' && catalogue.can_manage ? (
                              <button
                                className="catalogue-remove-button"
                                disabled={mutationId === medicine.id}
                                onClick={() => setPendingSelection({
                                  medicineId: medicine.id,
                                  productName: medicine.generic_name || medicine.brand_name || medicine.code,
                                  selected: false,
                                })}
                                type="button"
                              >
                                {mutationId === medicine.id ? 'Removing…' : 'Remove'}
                              </button>
                            ) : null}
                          </>
                        ) : catalogue.can_manage ? (
                          <button
                            className="catalogue-add-button"
                            disabled={mutationId === medicine.id}
                            onClick={() => setPendingSelection({
                              medicineId: medicine.id,
                              productName: medicine.generic_name || medicine.brand_name || medicine.code,
                              selected: true,
                            })}
                            type="button"
                          >
                            {mutationId === medicine.id ? 'Adding…' : 'Add to tenant'}
                          </button>
                        ) : <span className="reference-badge">Master only</span>}
                      </div>
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

      {pendingSelection ? (
        <div className="business-dialog-backdrop" role="presentation">
          <section aria-labelledby="catalogue-selection-title" aria-modal="true" className="business-dialog" role="dialog">
            <header>
              <div><p className="eyebrow">Tenant catalogue</p><h2 id="catalogue-selection-title">{pendingSelection.selected ? 'Add product to tenant' : 'Remove product from tenant'}</h2></div>
              <button aria-label="Close dialog" disabled={Boolean(mutationId)} onClick={() => setPendingSelection(null)} type="button"><Icon name="close" /></button>
            </header>
            <div className="business-dialog-record"><div><code>Universal master</code><strong>{pendingSelection.productName}</strong></div></div>
            <p className="business-dialog-confirm"><Icon name={pendingSelection.selected ? 'shield' : 'alert'} /> {pendingSelection.selected
              ? 'Adding makes this government master product available for this tenant’s package, price and assortment governance.'
              : 'Removing takes the product out of this tenant catalogue. Existing governed history is retained.'}</p>
            <footer>
              <button className="secondary-button" disabled={Boolean(mutationId)} onClick={() => setPendingSelection(null)} type="button">Cancel</button>
              <button className={pendingSelection.selected ? 'primary-button' : 'danger-link'} disabled={Boolean(mutationId)} onClick={() => void confirmSelection()} type="button">
                {mutationId ? 'Saving…' : pendingSelection.selected ? 'Add to tenant catalogue' : 'Remove from tenant catalogue'}
              </button>
            </footer>
          </section>
        </div>
      ) : null}
      {priceModal ? (
        <div
          className="business-dialog-backdrop"
          onClick={(e) => {
            if (e.target === e.currentTarget && !priceSubmitting) setPriceModal(null);
          }}
          role="presentation"
        >
          <div aria-modal="true" className="business-dialog" role="dialog" style={{ maxWidth: '460px' }}>
            <header>
              <h2>Create Tenant Price Draft</h2>
              <button aria-label="Close" onClick={() => setPriceModal(null)} type="button"><Icon name="close" /></button>
            </header>
            <form onSubmit={async (e) => {
              e.preventDefault();
              setPriceError('');
              setPriceSuccess('');
              const unitPriceNum = Number(modalUnitPrice);
              const minPriceNum = modalMinPrice ? Number(modalMinPrice) : 0;
              if (Number.isNaN(unitPriceNum) || unitPriceNum <= 0) {
                setPriceError('Unit selling price must be a positive number greater than zero.');
                return;
              }
              if (modalMinPrice && (Number.isNaN(minPriceNum) || minPriceNum < 0)) {
                setPriceError('Minimum floor price must be a non-negative number.');
                return;
              }
              if (modalMinPrice && minPriceNum > unitPriceNum) {
                setPriceError(`Minimum floor price (KES ${minPriceNum.toFixed(2)}) cannot exceed unit selling price (KES ${unitPriceNum.toFixed(2)}).`);
                return;
              }

              setPriceSubmitting(true);
              try {
                const draft = await saveTenantPriceDraft(
                  {
                    sku_code: priceSkuCode,
                    unit_price: modalUnitPrice,
                    minimum_allowed_price: modalMinPrice || null,
                    tax_inclusive: modalTaxInc,
                  },
                  tenantId,
                  csrfToken,
                );
                setPriceSuccess(
                  `Draft v${draft.version_number} saved for ${draft.sku_code}. Submit it from Pricing for independent review.`,
                );
              } catch (reason) {
                setPriceError(
                  reason instanceof Error ? reason.message : 'Could not save price draft.',
                );
              } finally {
                setPriceSubmitting(false);
              }
            }}>
              <p className="panel-note">
                Prepare the retail price for <strong>{priceModal.name}</strong>. Prices remain
                drafts until an independent approver reviews and publishes the version.
              </p>
              {priceError ? <p className="auth-error" role="alert"><Icon name="alert" /> {priceError}</p> : null}
              {priceSuccess ? <p className="inline-alert" role="status"><Icon name="check" /> {priceSuccess}</p> : null}

              <label className="business-field">
                <span>Commercial SKU</span>
                <select
                  onChange={(event) => setPriceSkuCode(event.target.value)}
                  required
                  value={priceSkuCode}
                >
                  <option value="">Select a governed tenant SKU</option>
                  {tenantSkus.map((sku) => (
                    <option key={sku.id} value={sku.sku_code}>
                      {sku.sku_code} — {sku.display_name}
                    </option>
                  ))}
                </select>
                {tenantSkus.length === 0 ? (
                  <small>Complete product and package governance before pricing this catalogue item.</small>
                ) : null}
              </label>

              <label className="business-field">
                <span>Unit Selling Price (KES)</span>
                <input
                  onChange={(e) => setModalUnitPrice(e.target.value)}
                  placeholder="e.g. 250.00"
                  required
                  type="number"
                  step="0.01"
                  value={modalUnitPrice}
                />
              </label>

              <label className="business-field">
                <span>Minimum Floor Price (KES)</span>
                <input
                  onChange={(e) => setModalMinPrice(e.target.value)}
                  placeholder="e.g. 200.00"
                  type="number"
                  step="0.01"
                  value={modalMinPrice}
                />
              </label>

              {modalUnitPrice && modalMinPrice && Number(modalUnitPrice) >= Number(modalMinPrice) ? (
                <p className="business-dialog-confirm" style={{ margin: '8px 0', fontSize: '0.8rem' }}>
                  <Icon name="shield" /> Governed margin window: <strong>KES {(Number(modalUnitPrice) - Number(modalMinPrice)).toFixed(2)}</strong> floor buffer.
                </p>
              ) : null}

              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', margin: '12px 0', fontSize: '0.85rem' }}>
                <input
                  checked={modalTaxInc}
                  onChange={(e) => setModalTaxInc(e.target.checked)}
                  type="checkbox"
                />
                <span>Tax Inclusive Pricing</span>
              </label>

              <footer>
                <button disabled={priceSubmitting} onClick={() => setPriceModal(null)} type="button">Cancel</button>
                <button className="primary-button" disabled={priceSubmitting || !priceSkuCode} type="submit">
                  {priceSubmitting ? 'Saving…' : 'Save Draft'}
                </button>
              </footer>
            </form>
          </div>
        </div>
      ) : null}
    </article>
  );
}

function CommerceView({
  csrfToken,
  data,
  failed,
  onWorkspaceChanged,
}: BusinessViewProps) {
  const [tab, setTab] = useState<'orders' | 'quotations' | 'picking' | 'packing' | 'dispatches' | 'deliveries' | 'returns' | 'holds'>('orders');
  const [quotations, setQuotations] = useState<readonly HQQuotationItem[] | null>(null);
  const [pickingWaves, setPickingWaves] = useState<readonly HQPickingWaveItem[] | null>(null);
  const [pickingTasks, setPickingTasks] = useState<readonly HQPickingTaskItem[] | null>(null);
  const [packingSessions, setPackingSessions] = useState<readonly HQPackingSessionItem[] | null>(null);
  const [packages, setPackages] = useState<readonly HQPackageItem[] | null>(null);
  const [deliveries, setDeliveries] = useState<readonly HQDeliveryRecordItem[] | null>(null);
  const [returns, setReturns] = useState<readonly HQSalesReturnItem[] | null>(null);
  const [holds, setHolds] = useState<readonly HQSalesOrderHoldItem[] | null>(null);

  useEffect(() => {
    const applyFocus = () => {
      const focus = focusFromHash();
      const allowed = new Set(['orders', 'quotations', 'picking', 'packing', 'dispatches', 'deliveries', 'returns', 'holds']);
      if (allowed.has(focus)) {
        setTab(focus as typeof tab);
      }
    };
    applyFocus();
    window.addEventListener('hashchange', applyFocus);
    return () => window.removeEventListener('hashchange', applyFocus);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      loadQuotations(controller.signal).catch(() => null),
      loadPickingWaves(controller.signal).catch(() => null),
      loadPickingTasks(controller.signal).catch(() => null),
      loadPackingSessions(controller.signal).catch(() => null),
      loadPackages(controller.signal).catch(() => null),
      loadDeliveryRecords(controller.signal).catch(() => null),
      loadSalesReturns(controller.signal).catch(() => null),
      loadSalesOrderHolds(controller.signal).catch(() => null),
    ]).then(([q, pw, pt, ps, pkg, del, ret, h]) => {
      setQuotations(q);
      setPickingWaves(pw);
      setPickingTasks(pt);
      setPackingSessions(ps);
      setPackages(pkg);
      setDeliveries(del);
      setReturns(ret);
      setHolds(h);
    });
    return () => controller.abort();
  }, []);

  if (failed) return <WorkspaceSectionError domain="sales and fulfilment" />;
  if (!data) return <WorkspaceSectionLoading domain="sales and fulfilment" />;

  const { counts, dispatches, orders } = data.commerce;
  return (
    <>
      <section className="metric-grid network-metrics" aria-label="Sales and fulfilment totals">
        <SummaryCard icon="docs" label="Quotations" value={counts.quotations} detail="Commercial offers" onActivate={() => setTab('quotations')} />
        <SummaryCard icon="store" label="Open orders" value={counts.open_orders} detail={`${formatNumber(counts.orders)} total orders`} tone={counts.open_orders ? 'amber' : 'teal'} onActivate={() => setTab('orders')} />
        <SummaryCard icon="inventory" label="Dispatches" value={counts.dispatches} detail={`${formatNumber(counts.deliveries)} delivery records`} onActivate={() => setTab('dispatches')} />
        <SummaryCard icon="refresh" label="Returns" value={counts.returns} detail="Authorised return records" tone={counts.returns ? 'amber' : 'teal'} onActivate={() => setTab('returns')} />
      </section>

      <BusinessWorkbench csrfToken={csrfToken} data={data} domain="commerce" onChanged={onWorkspaceChanged} />

      <article className="panel" style={{ marginTop: '24px' }}>
        <PanelHeader eyebrow="Fulfilment Execution Desk" title="Order-to-Delivery Operations Workbench" />

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px', marginBottom: '20px' }}>
          <div className="segmented" role="tablist">
            <button className={tab === 'orders' ? 'segmented-option is-active' : 'segmented-option'} onClick={() => setTab('orders')} type="button">
              🛒 Orders ({orders.length})
            </button>
            <button className={tab === 'quotations' ? 'segmented-option is-active' : 'segmented-option'} onClick={() => setTab('quotations')} type="button">
              📄 Quotations ({quotations?.length ?? counts.quotations})
            </button>
            <button className={tab === 'picking' ? 'segmented-option is-active' : 'segmented-option'} onClick={() => setTab('picking')} type="button">
              📦 Picking ({pickingTasks?.length ?? 0})
            </button>
            <button className={tab === 'packing' ? 'segmented-option is-active' : 'segmented-option'} onClick={() => setTab('packing')} type="button">
              🎁 Packing & Seals ({packages?.length ?? 0})
            </button>
            <button className={tab === 'dispatches' ? 'segmented-option is-active' : 'segmented-option'} onClick={() => setTab('dispatches')} type="button">
              🚚 Dispatches ({dispatches.length})
            </button>
            <button className={tab === 'deliveries' ? 'segmented-option is-active' : 'segmented-option'} onClick={() => setTab('deliveries')} type="button">
              📋 Deliveries ({deliveries?.length ?? counts.deliveries})
            </button>
            <button className={tab === 'returns' ? 'segmented-option is-active' : 'segmented-option'} onClick={() => setTab('returns')} type="button">
              🔄 Returns ({returns?.length ?? counts.returns})
            </button>
            <button className={tab === 'holds' ? 'segmented-option is-active' : 'segmented-option'} onClick={() => setTab('holds')} type="button">
              ⛔ Holds ({holds?.length ?? 0})
            </button>
          </div>
        </div>

        {tab === 'orders' && (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Order #</th><th>Customer</th><th>Date</th><th>Priority</th><th>Total</th><th>Status</th></tr></thead>
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
        )}

        {tab === 'quotations' && (
          <>
            <p className="panel-note">Customer commercial quotations, price agreements, and validity dates.</p>
            {quotations && quotations.length > 0 ? (
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Quotation #</th><th>Customer</th><th>Issue Date</th><th>Valid Until</th><th>Total Amount</th><th>Status</th></tr></thead>
                  <tbody>
                    {quotations.map((q) => (
                      <tr key={q.id}>
                        <td><code>{q.quotation_number}</code></td>
                        <td><strong>{q.customer_name || 'Commercial Customer'}</strong></td>
                        <td><small>{formatDate(q.issue_date)}</small></td>
                        <td><small>{q.valid_until ? formatDate(q.valid_until) : 'Ongoing'}</small></td>
                        <td><strong>{formatMoney(q.total, q.currency)}</strong></td>
                        <td><StatusBadge value={q.status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <EmptyState icon="docs" title="No quotations" detail="Commercial quotations appear here as price offers are drafted." />}
          </>
        )}

        {tab === 'picking' && (
          <>
            <p className="panel-note">
              Warehouse picking tasks, FEFO batch allocations, and short-pick exceptions. {pickingWaves ? `(${pickingWaves.length} active waves)` : ''}
            </p>
            {pickingTasks && pickingTasks.length > 0 ? (
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Task ID</th><th>Sales Order</th><th>SKU Code</th><th>Requested Qty</th><th>Picked Qty</th><th>Status</th></tr></thead>
                  <tbody>
                    {pickingTasks.map((pt) => (
                      <tr key={pt.id}>
                        <td><code>{pt.id.slice(0, 8)}</code></td>
                        <td><code>{pt.sales_order_number || 'Order'}</code></td>
                        <td><code>{pt.sku_code || '—'}</code></td>
                        <td><small>{pt.requested_quantity}</small></td>
                        <td><strong style={{ color: 'var(--teal-500)' }}>{pt.picked_quantity}</strong></td>
                        <td><StatusBadge value={pt.status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <EmptyState icon="inventory" title="No picking tasks" detail="Warehouse picking tasks appear when sales orders enter picking waves." />}
          </>
        )}

        {tab === 'packing' && (
          <>
            <p className="panel-note">
              Verified packages, barcode verification, temperature zones, and tamper seals. {packingSessions ? `(${packingSessions.length} packing sessions)` : ''}
            </p>
            {packages && packages.length > 0 ? (
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Package #</th><th>Sales Order</th><th>Temp Zone</th><th>Status</th></tr></thead>
                  <tbody>
                    {packages.map((pkg) => (
                      <tr key={pkg.id}>
                        <td><code>{pkg.package_number}</code></td>
                        <td><code>{pkg.sales_order_number || 'Order'}</code></td>
                        <td><span className="positive-chip" style={{ fontSize: '0.68rem' }}>{pkg.temperature_zone}</span></td>
                        <td><StatusBadge value={pkg.status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <EmptyState icon="store" title="No packages verified" detail="Packages appear here when picking tasks are verified into shipping containers." />}
          </>
        )}

        {tab === 'dispatches' && (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Dispatch #</th><th>Customer</th><th>Carrier</th><th>Dispatch Date</th><th>Expected Delivery</th><th>Status</th></tr></thead>
              <tbody>
                {dispatches.map((d) => (
                  <tr key={d.id}>
                    <td><code>{d.dispatch_number}</code></td>
                    <td><strong>{d.customer_name}</strong></td>
                    <td><small>{d.carrier || 'Internal fleet'}</small></td>
                    <td><span className="muted-cell">{formatDate(d.dispatch_date)}</span></td>
                    <td><span className="muted-cell">{formatDate(d.expected_delivery_date)}</span></td>
                    <td><StatusBadge value={d.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {tab === 'deliveries' && (
          <>
            <p className="panel-note">Proof of delivery (POD) records, recipient signatures, GPS coordinates, and temperature evidence.</p>
            {deliveries && deliveries.length > 0 ? (
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Record ID</th><th>Dispatch #</th><th>Recipient</th><th>Delivered Timestamp</th><th>Status</th></tr></thead>
                  <tbody>
                    {deliveries.map((del) => (
                      <tr key={del.id}>
                        <td><code>{del.id.slice(0, 8)}</code></td>
                        <td><code>{del.dispatch_number || 'Dispatch'}</code></td>
                        <td><strong>{del.recipient_name || 'Customer Recipient'}</strong></td>
                        <td><small>{del.delivered_at ? formatDate(del.delivered_at) : 'En route'}</small></td>
                        <td><StatusBadge value={del.status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <EmptyState icon="check" title="No delivery records" detail="Proof of delivery records appear when dispatches reach customer destinations." />}
          </>
        )}

        {tab === 'returns' && (
          <>
            <p className="panel-note">Customer return authorizations (RMA), cold chain evidence checks, and quality dispositions.</p>
            {returns && returns.length > 0 ? (
              <div className="table-scroll">
                <table>
                  <thead><tr><th>RMA Return #</th><th>Sales Order</th><th>Customer</th><th>Reason</th><th>Status</th></tr></thead>
                  <tbody>
                    {returns.map((ret) => (
                      <tr key={ret.id}>
                        <td><code>{ret.return_number}</code></td>
                        <td><code>{ret.sales_order_number || 'Order'}</code></td>
                        <td><strong>{ret.customer_name || 'Customer'}</strong></td>
                        <td><small>{ret.reason || 'Customer return'}</small></td>
                        <td><StatusBadge value={ret.status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <EmptyState icon="refresh" title="No return authorizations" detail="Customer RMA return requests appear here when logged." />}
          </>
        )}

        {tab === 'holds' && (
          <>
            <p className="panel-note">Active order holds (Credit hold, Compliance review, Recall hold, Quality hold).</p>
            {holds && holds.length > 0 ? (
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Hold ID</th><th>Sales Order</th><th>Hold Type</th><th>Reason</th><th>Placed Date</th><th>Status</th></tr></thead>
                  <tbody>
                    {holds.map((h) => (
                      <tr key={h.id}>
                        <td><code>{h.id.slice(0, 8)}</code></td>
                        <td><code>{h.sales_order_number || 'Order'}</code></td>
                        <td><span className="status-badge status-warning"><i /> {h.hold_type}</span></td>
                        <td><small>{h.reason}</small></td>
                        <td><small>{formatDate(h.placed_at)}</small></td>
                        <td>{h.is_active ? <span className="status-badge status-suspended"><i /> ACTIVE HOLD</span> : <small>RELEASED</small>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <EmptyState icon="check" title="No order holds active" detail="Order holds will appear here if compliance or credit checks block an order." />}
          </>
        )}
      </article>

      <article className="panel workflow-panel" style={{ marginTop: '24px' }}>
        <PanelHeader eyebrow="Order-to-delivery" title="Fulfilment Workspaces & Steps" />
        <div className="workflow-grid">
          <button className="workflow-link" onClick={() => setTab('quotations')} type="button">
            <div className="workflow-top"><span><Icon name="docs" /></span><small>01</small></div>
            <strong>Quotations</strong>
            <p>Price and approve customer demand.</p>
            <b>Open quotations</b>
          </button>
          <button className="workflow-link" onClick={() => setTab('orders')} type="button">
            <div className="workflow-top"><span><Icon name="store" /></span><small>02</small></div>
            <strong>Sales orders</strong>
            <p>Control holds, allocation and approval.</p>
            <b>Open orders</b>
          </button>
          <button className="workflow-link" onClick={() => setTab('picking')} type="button">
            <div className="workflow-top"><span><Icon name="inventory" /></span><small>03</small></div>
            <strong>Pick & pack</strong>
            <p>Coordinate warehouse fulfilment.</p>
            <b>Open picking</b>
          </button>
          <button className="workflow-link" onClick={() => setTab('deliveries')} type="button">
            <div className="workflow-top"><span><Icon name="check" /></span><small>04</small></div>
            <strong>Delivery & returns</strong>
            <p>Capture proof, exceptions and returns.</p>
            <b>Open deliveries</b>
          </button>
        </div>
      </article>
    </>
  );
}

function GovernanceView({ data, failed }: { readonly data: HQWorkspaceData | null; readonly failed: boolean }) {
  if (failed) return <WorkspaceSectionError domain="system governance" />;
  if (!data) return <WorkspaceSectionLoading domain="system governance" />;

  const { audit_events: auditEvents, counts, crosswalks, documents, domain_events: domainEvents, notifications } = data.governance;
  const scrollTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  return (
    <>
      <section className="metric-grid network-metrics" aria-label="System governance totals">
        <SummaryCard icon="shield" label="Audit events" value={counts.audit_events} detail="Immutable activity records" onActivate={() => scrollTo('governance-audit')} />
        <SummaryCard icon="docs" label="Clinical documents" value={counts.documents} detail="Stored governed files" onActivate={() => scrollTo('governance-documents')} />
        <SummaryCard icon="activity" label="Failed events" value={counts.failed_domain_events} detail={`${formatNumber(counts.domain_events)} domain events`} tone={counts.failed_domain_events ? 'rose' : 'teal'} onActivate={() => scrollTo('governance-events')} />
        <SummaryCard icon="external" label="Pending notifications" value={counts.pending_notifications} detail={`${formatNumber(counts.crosswalks)} legacy crosswalks`} tone={counts.pending_notifications ? 'amber' : 'teal'} onActivate={() => scrollTo('governance-notifications')} />
      </section>

      <article className="panel" id="governance-audit">
        <PanelHeader eyebrow="Immutable record" title="Recent audit activity" />
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

      <section className="content-grid content-grid-primary governance-grid" id="governance-events">
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

        <article className="panel" id="governance-notifications">
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

      <section className="content-grid" id="governance-documents">
        <article className="panel">
          <PanelHeader eyebrow="Clinical storage" title="Recent documents" />
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
 * Decision support, terminology, encounters, conditions, observations and FHIR
 * write-protection records. Summary cards switch the entity table; each row
 * opens particulars so operators can inspect a single clinical / interop record.
 */
type ClinicalTable =
  | 'encounters'
  | 'conditions'
  | 'observations'
  | 'releases'
  | 'terminology'
  | 'fhir';

const CLINICAL_TABLES: readonly { readonly key: ClinicalTable; readonly label: string }[] = [
  { key: 'encounters', label: 'Encounters' },
  { key: 'conditions', label: 'Conditions' },
  { key: 'observations', label: 'Observations' },
  { key: 'releases', label: 'Knowledge releases' },
  { key: 'terminology', label: 'Terminology' },
  { key: 'fhir', label: 'FHIR writes' },
];

type ClinicalSelection =
  | { readonly kind: 'release'; readonly row: HQKnowledgeRelease }
  | { readonly kind: 'code_system'; readonly row: HQCodeSystem }
  | { readonly kind: 'value_set'; readonly row: HQValueSet }
  | { readonly kind: 'encounter'; readonly row: HQEncounter }
  | { readonly kind: 'condition'; readonly row: HQCondition }
  | { readonly kind: 'observation'; readonly row: HQObservation }
  | { readonly kind: 'fhir'; readonly row: HQFhirIdempotencyRecord };

function clinicalParticulars(selection: ClinicalSelection): readonly { readonly label: string; readonly value: string }[] {
  switch (selection.kind) {
    case 'release':
      return [
        { label: 'Code', value: selection.row.code },
        { label: 'Version', value: selection.row.version },
        { label: 'Source', value: selection.row.source || '—' },
        { label: 'Source version', value: selection.row.source_version || '—' },
        { label: 'Licence', value: selection.row.licence || '—' },
        { label: 'Classification', value: selection.row.classification || '—' },
        { label: 'Effective', value: formatDate(selection.row.effective_date) },
        { label: 'Expires', value: formatDate(selection.row.expires_at) },
        { label: 'State', value: selection.row.is_active ? 'ACTIVE' : 'INACTIVE' },
        { label: 'Checksum (full)', value: selection.row.checksum_full || selection.row.checksum || '—' },
        { label: 'Record id', value: selection.row.id },
      ];
    case 'code_system':
      return [
        { label: 'Name', value: selection.row.name },
        { label: 'Title', value: selection.row.title || '—' },
        { label: 'URL', value: selection.row.url || '—' },
        { label: 'Version', value: selection.row.version || '—' },
        { label: 'Content mode', value: selection.row.content_mode || '—' },
        { label: 'Scope', value: selection.row.is_global ? 'Global' : 'Tenant' },
        { label: 'Concepts', value: formatNumber(selection.row.concept_count) },
        {
          label: 'Sample concepts',
          value: selection.row.sample_concepts?.length
            ? selection.row.sample_concepts.map((c) => `${c.code}${c.display && c.display !== c.code ? ` — ${c.display}` : ''}`).join('; ')
            : '—',
        },
        { label: 'Record id', value: selection.row.id },
      ];
    case 'value_set':
      return [
        { label: 'Name', value: selection.row.name },
        { label: 'Title', value: selection.row.title || '—' },
        { label: 'URL', value: selection.row.url || '—' },
        { label: 'Version', value: selection.row.version || '—' },
        { label: 'Scope', value: selection.row.is_global ? 'Global' : 'Tenant' },
        {
          label: 'Compose',
          value: selection.row.compose && Object.keys(selection.row.compose).length
            ? JSON.stringify(selection.row.compose)
            : '—',
        },
        { label: 'Record id', value: selection.row.id },
      ];
    case 'encounter':
      return [
        { label: 'Patient', value: selection.row.patient_name || 'Not recorded' },
        { label: 'Patient number', value: selection.row.patient_number || '—' },
        { label: 'Class', value: selection.row.encounter_class || '—' },
        { label: 'Status', value: selection.row.status },
        { label: 'Practitioner', value: selection.row.practitioner_name || 'Not recorded' },
        { label: 'Organization', value: selection.row.organization_name || '—' },
        { label: 'Location', value: selection.row.location_name || '—' },
        { label: 'Started', value: formatDateTime(selection.row.start_time) },
        { label: 'Ended', value: formatDateTime(selection.row.end_time) },
        { label: 'Reason', value: selection.row.reason_code || '—' },
        { label: 'Record id', value: selection.row.id },
      ];
    case 'condition':
      return [
        { label: 'Patient', value: selection.row.patient_name || 'Not recorded' },
        { label: 'Display', value: selection.row.display || selection.row.code },
        { label: 'Code', value: selection.row.code },
        { label: 'System', value: selection.row.system || '—' },
        { label: 'Category', value: selection.row.category || '—' },
        { label: 'Clinical status', value: selection.row.clinical_status },
        { label: 'Verification', value: selection.row.verification_status },
        { label: 'Onset', value: formatDateTime(selection.row.onset_date) },
        { label: 'Recorded', value: formatDateTime(selection.row.recorded_date) },
        { label: 'Encounter', value: selection.row.encounter_id || '—' },
        { label: 'Record id', value: selection.row.id },
      ];
    case 'observation':
      return [
        { label: 'Patient', value: selection.row.patient_name || 'Not recorded' },
        { label: 'Display', value: selection.row.display || selection.row.code },
        { label: 'Code', value: selection.row.code },
        { label: 'System', value: selection.row.system || '—' },
        { label: 'Category', value: selection.row.category || '—' },
        { label: 'Status', value: selection.row.status },
        {
          label: 'Value',
          value: selection.row.value_string
            || (selection.row.value_quantity
              ? `${selection.row.value_quantity}${selection.row.value_unit ? ` ${selection.row.value_unit}` : ''}`
              : '—'),
        },
        { label: 'Interpretation', value: selection.row.interpretation || '—' },
        { label: 'Effective', value: formatDateTime(selection.row.effective_time) },
        { label: 'Encounter', value: selection.row.encounter_id || '—' },
        { label: 'Record id', value: selection.row.id },
      ];
    case 'fhir':
      return [
        { label: 'Resource', value: selection.row.resource_type },
        { label: 'Operation', value: selection.row.operation },
        { label: 'State', value: selection.row.state },
        { label: 'HTTP status', value: selection.row.response_status != null ? String(selection.row.response_status) : '—' },
        { label: 'Resource id', value: selection.row.resource_id || '—' },
        { label: 'Idempotency key', value: selection.row.key },
        { label: 'Request hash', value: selection.row.request_hash_full || selection.row.request_hash || '—' },
        { label: 'Actor', value: selection.row.actor },
        { label: 'Created', value: formatDateTime(selection.row.created_at) },
        { label: 'Record id', value: selection.row.id },
      ];
  }
}

function ClinicalEntityDetailDialog({
  selection,
  onClose,
}: {
  readonly selection: ClinicalSelection;
  readonly onClose: () => void;
}) {
  const title = ({
    release: 'Knowledge release',
    code_system: 'Code system',
    value_set: 'Value set',
    encounter: 'Clinical encounter',
    condition: 'Condition',
    observation: 'Observation',
    fhir: 'FHIR idempotency record',
  } as const)[selection.kind];
  const fields = clinicalParticulars(selection);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  return (
    <div className="business-dialog-backdrop" onClick={onClose} role="presentation">
      <section
        aria-labelledby="clinical-entity-title"
        aria-modal="true"
        className="business-dialog clinical-entity-dialog"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
      >
        <header className="panel-header">
          <div>
            <p className="eyebrow">Particulars</p>
            <h2 id="clinical-entity-title">{title}</h2>
          </div>
          <button aria-label="Close particulars" onClick={onClose} type="button"><Icon name="close" /></button>
        </header>
        <dl className="clinical-particulars">
          {fields.map((field) => (
            <div key={field.label}>
              <dt>{field.label}</dt>
              <dd><code>{field.value}</code></dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}

function ClinicalGovernanceTables({
  data,
  table,
  onTableChange,
  onSelect,
}: {
  readonly data: HQWorkspaceData | null;
  readonly table: ClinicalTable;
  readonly onTableChange: (table: ClinicalTable) => void;
  readonly onSelect: (selection: ClinicalSelection) => void;
}) {
  if (!data) return null;
  const clinical = data.clinical;

  return (
    <article className="panel table-panel" id="clinical-tables">
      <div className="table-toolbar">
        <PanelHeader eyebrow="Clinical governance" title="Safety & interoperability records" />
        <nav className="segmented" aria-label="Clinical governance table">
          {CLINICAL_TABLES.map((option) => (
            <button
              key={option.key}
              type="button"
              className={option.key === table ? 'segmented-option is-active' : 'segmented-option'}
              aria-pressed={option.key === table}
              onClick={() => onTableChange(option.key)}
            >
              {option.label}
            </button>
          ))}
        </nav>
      </div>

      <div className="table-scroll">
        {table === 'encounters' && (clinical.encounters.length ? (
          <table>
            <thead><tr><th>Patient</th><th>Class</th><th>Practitioner</th><th>Started</th><th>Reason</th><th>Status</th></tr></thead>
            <tbody>
              {clinical.encounters.map((encounter) => (
                <tr
                  key={encounter.id}
                  className="is-clickable"
                  onClick={() => onSelect({ kind: 'encounter', row: encounter })}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      onSelect({ kind: 'encounter', row: encounter });
                    }
                  }}
                  role="button"
                  tabIndex={0}
                >
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

        {table === 'conditions' && (clinical.conditions.length ? (
          <table>
            <thead><tr><th>Patient</th><th>Condition</th><th>Code</th><th>Clinical</th><th>Verification</th><th>Recorded</th></tr></thead>
            <tbody>
              {clinical.conditions.map((condition) => (
                <tr
                  key={condition.id}
                  className="is-clickable"
                  onClick={() => onSelect({ kind: 'condition', row: condition })}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      onSelect({ kind: 'condition', row: condition });
                    }
                  }}
                  role="button"
                  tabIndex={0}
                >
                  <td><strong>{condition.patient_name ?? 'Not recorded'}</strong></td>
                  <td><small>{condition.display || condition.code}</small></td>
                  <td><code>{condition.code}</code></td>
                  <td><StatusBadge value={condition.clinical_status} /></td>
                  <td><StatusBadge value={condition.verification_status} /></td>
                  <td><small>{formatDateTime(condition.recorded_date)}</small></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <EmptyState icon="patients" title="No conditions recorded" detail="Diagnoses and problem lists appear here when captured." />)}

        {table === 'observations' && (clinical.observations.length ? (
          <table>
            <thead><tr><th>Patient</th><th>Observation</th><th>Value</th><th>Status</th><th>Effective</th></tr></thead>
            <tbody>
              {clinical.observations.map((observation) => (
                <tr
                  key={observation.id}
                  className="is-clickable"
                  onClick={() => onSelect({ kind: 'observation', row: observation })}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      onSelect({ kind: 'observation', row: observation });
                    }
                  }}
                  role="button"
                  tabIndex={0}
                >
                  <td><strong>{observation.patient_name ?? 'Not recorded'}</strong></td>
                  <td><small>{observation.display || observation.code}</small></td>
                  <td>
                    <code>
                      {observation.value_string
                        || (observation.value_quantity
                          ? `${observation.value_quantity}${observation.value_unit ? ` ${observation.value_unit}` : ''}`
                          : '—')}
                    </code>
                  </td>
                  <td><StatusBadge value={observation.status} /></td>
                  <td><small>{formatDateTime(observation.effective_time)}</small></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <EmptyState icon="activity" title="No observations recorded" detail="Vitals and lab-style observations appear here when captured." />)}

        {table === 'releases' && (clinical.knowledge_releases.length ? (
          <table>
            <thead><tr><th>Release</th><th>Version</th><th>Source</th><th>Effective</th><th>Licence</th><th>Checksum</th><th>State</th></tr></thead>
            <tbody>
              {clinical.knowledge_releases.map((release) => (
                <tr
                  key={release.id}
                  className="is-clickable"
                  onClick={() => onSelect({ kind: 'release', row: release })}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      onSelect({ kind: 'release', row: release });
                    }
                  }}
                  role="button"
                  tabIndex={0}
                >
                  <td><code>{release.code}</code></td>
                  <td><strong>{release.version}</strong></td>
                  <td><small>{release.source}{release.source_version ? ` · ${release.source_version}` : ''}</small></td>
                  <td><small>{formatDate(release.effective_date)}</small></td>
                  <td><small>{release.licence || '—'}</small></td>
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
                <tr
                  key={system.id}
                  className="is-clickable"
                  onClick={() => onSelect({ kind: 'code_system', row: system })}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      onSelect({ kind: 'code_system', row: system });
                    }
                  }}
                  role="button"
                  tabIndex={0}
                >
                  <td><small>Code system</small></td>
                  <td><strong>{system.name}</strong></td>
                  <td><small>{system.title || system.url}</small></td>
                  <td><small>{system.version || '—'}</small></td>
                  <td><small>{formatNumber(system.concept_count)}</small></td>
                  <td><small>{system.is_global ? 'Global' : 'Tenant'}</small></td>
                </tr>
              ))}
              {clinical.value_sets.map((valueSet) => (
                <tr
                  key={valueSet.id}
                  className="is-clickable"
                  onClick={() => onSelect({ kind: 'value_set', row: valueSet })}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      onSelect({ kind: 'value_set', row: valueSet });
                    }
                  }}
                  role="button"
                  tabIndex={0}
                >
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

        {table === 'fhir' && (clinical.fhir_idempotency_records.length ? (
          <table>
            <thead><tr><th>Resource</th><th>Operation</th><th>State</th><th>Actor</th><th>Key</th><th>Created</th></tr></thead>
            <tbody>
              {clinical.fhir_idempotency_records.map((record) => (
                <tr
                  key={record.id}
                  className="is-clickable"
                  onClick={() => onSelect({ kind: 'fhir', row: record })}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      onSelect({ kind: 'fhir', row: record });
                    }
                  }}
                  role="button"
                  tabIndex={0}
                >
                  <td><strong>{record.resource_type}</strong></td>
                  <td><small>{record.operation}</small></td>
                  <td><StatusBadge value={record.state} /></td>
                  <td><span className="muted-cell">{record.actor}</span></td>
                  <td><code>{record.key}</code></td>
                  <td><small>{formatDateTime(record.created_at)}</small></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <EmptyState icon="security" title="No FHIR write records" detail="Idempotency records appear when FHIR writes are processed." />)}
      </div>
      <p className="muted-cell clinical-table-hint">Select a row to open full particulars for that record.</p>
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
  const [clinicalTable, setClinicalTable] = useState<ClinicalTable>('encounters');
  const [selection, setSelection] = useState<ClinicalSelection | null>(null);
  const openPrescriptions = metricValue(overview, 'Open prescriptions');
  const substitutions = data?.clinical.counts.substitutions ?? 0;
  const labels = data?.clinical.counts.dispensing_labels ?? 0;

  const clinicalMetrics = [
    {
      label: 'Encounters',
      value: summary.get('Clinical encounters') ?? data?.clinical.counts.encounters ?? 0,
      icon: 'clinical' as IconName,
      table: 'encounters' as ClinicalTable,
      detail: 'Visit and care episodes',
    },
    {
      label: 'Conditions',
      value: summary.get('Conditions') ?? data?.clinical.counts.conditions ?? 0,
      icon: 'patients' as IconName,
      table: 'conditions' as ClinicalTable,
      detail: 'Diagnoses and problems',
    },
    {
      label: 'Observations',
      value: summary.get('Observations') ?? data?.clinical.counts.observations ?? 0,
      icon: 'activity' as IconName,
      table: 'observations' as ClinicalTable,
      detail: 'Vitals and measured values',
    },
    {
      label: 'Knowledge releases',
      value: summary.get('Active clinical releases') ?? data?.clinical.counts.active_knowledge_releases ?? 0,
      icon: 'shield' as IconName,
      table: 'releases' as ClinicalTable,
      detail: 'Active CDS rule packs',
    },
    {
      label: 'Terminology',
      value: (summary.get('Code systems') ?? data?.clinical.counts.code_systems ?? 0)
        + (summary.get('Value sets') ?? data?.clinical.counts.value_sets ?? 0),
      icon: 'database' as IconName,
      table: 'terminology' as ClinicalTable,
      detail: 'Code systems and value sets',
    },
    {
      label: 'FHIR writes',
      value: summary.get('FHIR idempotency records') ?? data?.clinical.counts.fhir_idempotency_records ?? 0,
      icon: 'security' as IconName,
      table: 'fhir' as ClinicalTable,
      detail: 'Protected exchange writes',
    },
  ];

  const openClinicalSection = (table: ClinicalTable) => {
    setClinicalTable(table);
    window.requestAnimationFrame(() => {
      document.getElementById('clinical-tables')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  };

  return (
    <>
      <section className="metric-grid network-metrics" aria-label="Clinical governance totals">
        {clinicalMetrics.map((metric) => (
          <SummaryCard
            detail={metric.detail}
            icon={metric.icon}
            key={metric.label}
            label={metric.label}
            onActivate={() => openClinicalSection(metric.table)}
            targetId="clinical-tables"
            value={metric.value}
          />
        ))}
      </section>

      <ClinicalGovernanceTables
        data={data}
        onSelect={setSelection}
        onTableChange={setClinicalTable}
        table={clinicalTable}
      />

      <div id="clinical-workflow">
        {failed
          ? <WorkspaceSectionError domain="clinical workflow" />
          : data
            ? <BusinessWorkbench csrfToken={csrfToken} data={data} domain="clinical" onChanged={onWorkspaceChanged} />
            : <WorkspaceSectionLoading domain="clinical workflow" />}
      </div>

      <section className="content-grid" id="clinical-dispensing">
        <article className="panel">
          <PanelHeader
            actionHref="/api/fhir/r4/metadata"
            actionLabel="Open CapStmt"
            eyebrow="Interoperability"
            title="FHIR R4 exchange"
          />
          <div className="priority-list">
            <PriorityItem
              action="Code systems & value sets"
              detail="Governed terminology registrations"
              icon="docs"
              onActivate={() => openClinicalSection('terminology')}
              value={(data?.clinical.counts.code_systems ?? 0) + (data?.clinical.counts.value_sets ?? 0)}
            />
            <PriorityItem
              action="Idempotent FHIR writes"
              detail="Duplicate-protected exchange operations"
              icon="security"
              onActivate={() => openClinicalSection('fhir')}
              value={data?.clinical.counts.fhir_idempotency_records ?? 0}
              {...((data?.clinical.counts.fhir_idempotency_records ?? 0) ? {} : { valueLabel: 'None' })}
            />
            <PriorityItem
              action="Open CapStmt"
              detail="Capability statement for this gateway"
              icon="external"
              onActivate={() => { window.location.href = '/api/fhir/r4/metadata'; }}
              value={1}
              valueLabel="R4 4.0.1"
            />
          </div>
        </article>
        <article className="panel">
          <PanelHeader eyebrow="Prescription governance" title="Active dispensing" />
          <div className="priority-list">
            <PriorityItem
              action="Open prescriptions"
              detail="Active prescribing and dispensing workflow"
              icon="clinical"
              onActivate={() => {
                document.getElementById('clinical-workflow')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
              }}
              tone={openPrescriptions ? 'amber' : 'teal'}
              value={openPrescriptions}
            />
            <PriorityItem
              action="Clinical substitutions"
              detail="Pharmacist-initiated therapeutic substitutions"
              icon="activity"
              onActivate={() => {
                document.getElementById('clinical-workflow')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
              }}
              value={substitutions}
              {...(substitutions ? {} : { valueLabel: 'None' })}
            />
            <PriorityItem
              action="Dispensing labels"
              detail="Audit label generation and reprints"
              icon="docs"
              onActivate={() => {
                document.getElementById('clinical-dispensing')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
              }}
              value={labels}
              {...(labels ? {} : { valueLabel: 'None' })}
            />
          </div>
        </article>
      </section>

      {selection ? <ClinicalEntityDetailDialog onClose={() => setSelection(null)} selection={selection} /> : null}
    </>
  );
}

function AccessView({
  csrfToken,
  data,
  failed,
  overview,
}: BusinessViewProps & { readonly overview: HQOverview }) {
  const summary = useSummary(overview);
  const selectableTenants = useMemo(
    () => overview.network_items.filter((item) => item.status === 'ACTIVE'),
    [overview.network_items],
  );
  const [tenantId, setTenantId] = useState(
    overview.tenant_id || selectableTenants[0]?.id || '',
  );
  const [sessions, setSessions] = useState<readonly RegisterSessionSummary[] | null>(null);
  const [variances, setVariances] = useState<readonly ShiftReportSummary[] | null>(null);
  const [forcedClosures, setForcedClosures] = useState<readonly ShiftReportSummary[] | null>(null);
  const [cashFailed, setCashFailed] = useState(false);
  const [identityFailed, setIdentityFailed] = useState(false);
  const [identityTick, setIdentityTick] = useState(0);

  const [roles, setRoles] = useState<readonly RoleDetail[] | null>(null);
  const [userRoles, setUserRoles] = useState<readonly UserRoleGrant[] | null>(null);
  const [matrix, setMatrix] = useState<CapabilityMatrixData | null>(null);
  const [serviceAccounts, setServiceAccounts] = useState<readonly ServiceAccountItem[] | null>(null);

  useEffect(() => {
    const nextTenantId = overview.tenant_id
      || (selectableTenants.some((tenant) => tenant.id === tenantId)
        ? tenantId
        : selectableTenants[0]?.id || '');
    if (nextTenantId !== tenantId) setTenantId(nextTenantId);
  }, [overview.tenant_id, selectableTenants, tenantId]);

  useEffect(() => {
    if (!tenantId) return;
    const controller = new AbortController();
    setCashFailed(false);
    setSessions(null);
    setVariances(null);
    setForcedClosures(null);
    Promise.all([
      loadOpenRegisterSessions(tenantId, controller.signal),
      loadCashVariances(tenantId, controller.signal),
      loadForcedClosures(tenantId, controller.signal),
    ])
      .then(([s, v, f]) => {
        setSessions(s);
        setVariances(v);
        setForcedClosures(f);
      })
      .catch(() => {
        if (!controller.signal.aborted) setCashFailed(true);
      });
    return () => controller.abort();
  }, [tenantId]);

  useEffect(() => {
    if (!tenantId) return;
    const controller = new AbortController();
    setIdentityFailed(false);
    setRoles(null);
    setUserRoles(null);
    setMatrix(null);
    setServiceAccounts(null);
    Promise.all([
      loadRolesDetail(tenantId, controller.signal),
      loadUserRoles(tenantId, controller.signal),
      loadCapabilityMatrix(tenantId, controller.signal),
      loadServiceAccounts(tenantId, controller.signal),
    ])
      .then(([r, ur, m, sa]) => {
        setRoles(r);
        setUserRoles(ur);
        setMatrix(m);
        setServiceAccounts(sa);
      })
      .catch(() => {
        if (!controller.signal.aborted) setIdentityFailed(true);
      });
    return () => controller.abort();
  }, [tenantId, identityTick]);

  return (
    <div className="access-view">
      <header className="access-strip">
        <div className="access-strip-identity">
          <span className="profile-avatar profile-avatar-compact">{initials(overview.user_name)}</span>
          <div>
            <p className="eyebrow">Tenant access administration</p>
            <h2>{displayName(overview.user_name)}</h2>
            <p>
              {overview.is_platform_overview
                ? 'Select a tenant below, then create users and grant role rights for that organisation.'
                : `${overview.tenant_name} · create users, define roles, and assign capabilities (${formatNumber(summary.get('Active users') ?? 0)} active)`}
            </p>
          </div>
        </div>
        {overview.is_platform_overview && tenantId ? (
          <label className="access-tenant-select">
            <span>Operating tenant</span>
            <select onChange={(event) => setTenantId(event.target.value)} value={tenantId}>
              {selectableTenants.map((tenant) => (
                <option key={tenant.id} value={tenant.id}>{tenant.name}</option>
              ))}
            </select>
          </label>
        ) : (
          <span className="status-badge status-active"><i /> Tenant scoped</span>
        )}
      </header>

      {identityFailed ? (
        <div className="inline-alert" role="status">
          <Icon name="alert" />
          Identity administration requires the <code>identity.manage</code> capability on a role assigned to your account
          (for example <code>TENANT_ADMIN</code>).
        </div>
      ) : null}

      {!tenantId ? <TenantWorkspaceRequired domain="user access" /> : null}

      {failed ? <WorkspaceSectionError domain="user access register" /> : null}
      {!failed && !data ? <WorkspaceSectionLoading domain="user access register" /> : null}

      {tenantId ? (
        <AccessWorkspace
          cashFailed={cashFailed}
          csrfToken={csrfToken}
          forcedClosures={forcedClosures}
          identityFailed={identityFailed}
          matrix={matrix}
          onRolesChanged={() => setIdentityTick((value) => value + 1)}
          roles={roles}
          serviceAccounts={serviceAccounts}
          sessions={sessions}
          tenantId={tenantId}
          tenantName={selectableTenants.find((tenant) => tenant.id === tenantId)?.name || overview.tenant_name}
          userRoles={userRoles}
          variances={variances}
        />
      ) : null}
    </div>
  );
}

function MetricCard({ metric, index, onNavigate }: { readonly metric: DashboardMetric; readonly index: number; readonly onNavigate?: (view: WorkspaceView) => void }) {
  const icons: readonly IconName[] = ['building', 'patients', 'clinical', 'inventory'];
  const destination = metric.href?.trim() ?? '';
  const content = (
    <>
      <div className="metric-top">
        <span><Icon name={icons[index] ?? 'overview'} /></span>
        <small>{destination ? 'Open workspace' : 'Current scope'}</small>
      </div>
      <strong>{formatNumber(metric.value)}</strong>
      <p>{metric.label}</p>
      <small>{metric.detail}</small>
    </>
  );
  if (!destination || isCurrentHqDestination(destination)) {
    return <article className={`metric-card metric-${metric.accent}`}>{content}</article>;
  }
  return (
    <a
      aria-label={`Open ${metric.label}: ${formatNumber(metric.value)} ${metric.detail}`}
      className={`metric-card metric-${metric.accent} metric-card-link`}
      href={destination}
      onClick={(event) => {
        if (openHqDestination(destination, onNavigate)) event.preventDefault();
      }}
    >
      {content}
    </a>
  );
}

function SummaryCard({
  detail,
  href,
  icon,
  label,
  onActivate,
  targetId,
  tone = 'navy',
  value,
}: {
  readonly detail: string;
  readonly href?: string;
  readonly icon: IconName;
  readonly label: string;
  readonly onActivate?: () => void;
  readonly targetId?: string;
  readonly tone?: string;
  readonly value: number;
}) {
  const destination = href?.trim() ?? '';
  const content = (
    <>
      <span><Icon name={icon} /></span>
      <div><small>{label}</small><strong>{formatNumber(value)}</strong><p>{detail}</p></div>
    </>
  );
  const activate = onActivate ?? (targetId
    ? () => {
        document.getElementById(targetId)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    : undefined);
  if (activate) {
    return (
      <button
        aria-label={`Open ${label}: ${formatNumber(value)}`}
        className={`summary-card summary-card-link summary-${tone}`}
        onClick={activate}
        type="button"
      >
        {content}
      </button>
    );
  }
  if (!destination || isCurrentHqDestination(destination)) {
    return <article className={`summary-card summary-${tone}`}>{content}</article>;
  }
  return (
    <a aria-label={`Open ${label}: ${formatNumber(value)}`} className={`summary-card summary-card-link summary-${tone}`} href={destination}>
      {content}
    </a>
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
  const showLink = Boolean(destination && actionLabel && !isCurrentHqDestination(destination));
  const showButton = Boolean(onAction && actionLabel);
  return (
    <header className="panel-header">
      <div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2></div>
      {showLink ? (
        <a href={destination} {...externalLinkProps(destination)}>
          {actionLabel} <Icon name={isExternalDestination(destination) ? 'external' : 'arrow'} />
        </a>
      ) : null}
      {showButton ? <button onClick={onAction} type="button">{actionLabel} <Icon name="arrow" /></button> : null}
      {!showLink && !showButton && actionLabel ? (
        <span className="panel-meta">{actionLabel}</span>
      ) : null}
    </header>
  );
}

function DataBar({
  href,
  icon,
  label,
  max,
  onActivate,
  onNavigate,
  value,
}: {
  readonly href?: string;
  readonly icon: IconName;
  readonly label: string;
  readonly max: number;
  readonly onActivate?: () => void;
  readonly onNavigate?: (view: WorkspaceView) => void;
  readonly value: number;
}) {
  const width = value && max ? Math.max(Math.round((value / max) * 100), 5) : 0;
  const destination = href?.trim() ?? '';
  const content = (
    <>
      <span><Icon name={icon} /></span>
      <div>
        <div><strong>{label}</strong><b>{formatNumber(value)}</b></div>
        <div className="bar-track"><i style={{ width: `${width}%` }} /></div>
      </div>
      {(onActivate || (destination && !isCurrentHqDestination(destination))) ? <Icon className="data-bar-arrow" name="chevron" /> : null}
    </>
  );
  if (onActivate) {
    return (
      <button aria-label={`Open ${label}`} className="data-bar data-bar-link" onClick={onActivate} type="button">
        {content}
      </button>
    );
  }
  if (!destination || isCurrentHqDestination(destination)) {
    return <div className="data-bar">{content}</div>;
  }
  return (
    <a
      aria-label={`Open ${label}`}
      className="data-bar data-bar-link"
      href={destination}
      onClick={(event) => {
        if (openHqDestination(destination, onNavigate)) event.preventDefault();
      }}
    >
      {content}
    </a>
  );
}

function CommandLink({
  detail,
  href,
  icon,
  onNavigate,
  title,
}: {
  readonly detail: string;
  readonly href: string;
  readonly icon: IconName;
  readonly onNavigate?: (view: WorkspaceView) => void;
  readonly title: string;
}) {
  const destination = href;
  const content = <><span><Icon name={icon} /></span><div><strong>{title}</strong><small>{detail}</small></div>{!isCurrentHqDestination(destination) ? <Icon className="command-arrow" name={isExternalDestination(destination) ? 'external' : 'arrow'} /> : null}</>;
  return isCurrentHqDestination(destination)
    ? <div className="command-link-static">{content}</div>
    : (
      <a
        href={destination}
        {...externalLinkProps(destination)}
        onClick={(event) => {
          if (openHqDestination(destination, onNavigate)) event.preventDefault();
        }}
      >
        {content}
      </a>
    );
}

function PriorityItem({
  action,
  detail,
  href,
  icon,
  onActivate,
  tone = 'amber',
  value,
  valueLabel,
}: {
  readonly action: string;
  readonly detail: string;
  readonly href?: string;
  readonly icon: IconName;
  readonly onActivate?: () => void;
  readonly tone?: string;
  readonly value: number;
  readonly valueLabel?: string;
}) {
  const destination = href?.trim() ?? '';
  const content = (
    <>
      <span className={`priority-icon priority-${tone}`}><Icon name={icon} /></span>
      <div><strong>{action}</strong><small>{detail}</small></div>
      <b>{valueLabel ?? formatNumber(value)}</b>
      {(onActivate || (destination && !isCurrentHqDestination(destination))) ? <Icon className="priority-arrow" name="chevron" /> : null}
    </>
  );
  if (onActivate) {
    return (
      <button aria-label={`Open ${action}`} className="priority-item priority-item-button" onClick={onActivate} type="button">
        {content}
      </button>
    );
  }
  if (!destination || isCurrentHqDestination(destination)) {
    return <div className="priority-item priority-item-static">{content}</div>;
  }
  return (
    <a className="priority-item" href={destination}>{content}</a>
  );
}

function Stat({
  href,
  label,
  onNavigate,
  value,
}: {
  readonly href?: string;
  readonly label: string;
  readonly onNavigate?: (view: WorkspaceView) => void;
  readonly value: number;
}) {
  const destination = href?.trim() ?? '';
  const content = (
    <>
      <small>{label}</small>
      <strong>{formatNumber(value)}</strong>
    </>
  );
  if (!destination || isCurrentHqDestination(destination)) {
    return <div>{content}</div>;
  }
  return (
    <a
      aria-label={`Open ${label}`}
      className="compact-stat-link"
      href={destination}
      onClick={(event) => {
        if (openHqDestination(destination, onNavigate)) event.preventDefault();
      }}
    >
      {content}
    </a>
  );
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

function TenantWorkspaceRequired({ domain }: { readonly domain: string }) {
  return (
    <article className="panel tenant-workspace-required">
      <EmptyState
        detail={`Choose an operating tenant from the workspace selector before opening ${domain}. Tenant financial and operational records are never combined across pharmacies.`}
        icon="building"
        title="Select a tenant workspace"
      />
    </article>
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
          <a href={item.href?.trim() || '#operations'} key={item.label}>
            <span className={`notification-icon attention-${item.tone}`}><Icon name={item.tone === 'teal' ? 'check' : 'alert'} /></span>
            <div><strong>{item.label}</strong><small>{item.detail}</small></div>
            <b>{formatNumber(item.value)}</b>
          </a>
        ))}
      </div>
    </div>
  );
}

function UserMenu({ overview, onClose, onSignOut }: {
  readonly overview: HQOverview;
  readonly onClose: () => void;
  readonly onSignOut: () => Promise<void>;
}) {
  const [signingOut, setSigningOut] = useState(false);

  const signOut = async () => {
    setSigningOut(true);
    try {
      await onSignOut();
    } finally {
      setSigningOut(false);
    }
  };

  return (
    <div aria-label="Account options" className="popover user-menu" id="hq-account-menu" role="group">
      <div className="user-menu-head">
        <span>{initials(overview.user_name)}</span>
        <div>
          <strong>{displayName(overview.user_name)}</strong>
          <small>{overview.tenant_name}</small>
        </div>
      </div>
      <div className="user-menu-items">
        <a href="#access" onClick={onClose}>
          <span className="user-menu-icon"><Icon name="security" /></span>
          <span><strong>Access overview</strong><small>Roles and permissions</small></span>
        </a>
        <a href="#access" onClick={onClose}>
          <span className="user-menu-icon"><Icon name="settings" /></span>
          <span><strong>System controls</strong><small>Identity and governance</small></span>
        </a>
        <a href="/api/docs/" target="_blank" rel="noreferrer" onClick={onClose}>
          <span className="user-menu-icon"><Icon name="docs" /></span>
          <span><strong>API workspace</strong><small>Opens in a new tab</small></span>
          <Icon className="user-menu-external" name="external" />
        </a>
      </div>
      <button className="signout-link" disabled={signingOut} type="button" onClick={() => void signOut()}>
        <span className="user-menu-icon"><Icon name="logout" /></span>
        <span><strong>{signingOut ? 'Signing out…' : 'Sign out'}</strong><small>End this secure session</small></span>
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
  type AuthMode = 'signin' | 'forgot' | 'reset';

  const [mode, setMode] = useState<AuthMode>('signin');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [resetUid, setResetUid] = useState('');
  const [resetToken, setResetToken] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [forgotDetail, setForgotDetail] = useState('');
  const [busy, setBusy] = useState(false);

  const goSignIn = useCallback((successNotice = '') => {
    setMode('signin');
    setPassword('');
    setConfirmPassword('');
    setResetUid('');
    setResetToken('');
    setError('');
    setForgotDetail('');
    setNotice(successNotice);
  }, []);

  const submitSignIn = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      if (busy) return;

      setBusy(true);
      setError('');
      setNotice('');
      try {
        const session = await signIn(username, password, csrfToken);
        setPassword('');
        onSignedIn(session);
      } catch (caught: unknown) {
        setError(caught instanceof SignInError ? caught.message : 'Sign-in failed.');
        setPassword('');
      } finally {
        setBusy(false);
      }
    },
    [busy, csrfToken, onSignedIn, password, username],
  );

  const submitForgot = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      if (busy) return;

      setBusy(true);
      setError('');
      setForgotDetail('');
      try {
        const identity = username.includes('@')
          ? { email: username.trim() }
          : { username: username.trim() };
        const result = await requestPasswordReset(identity, csrfToken);
        setForgotDetail(result.detail);
        if (result.dev_reset_uid && result.dev_reset_token) {
          setResetUid(result.dev_reset_uid);
          setResetToken(result.dev_reset_token);
        } else {
          setResetUid('');
          setResetToken('');
        }
      } catch (caught: unknown) {
        setError(caught instanceof SignInError ? caught.message : 'Password reset request failed.');
      } finally {
        setBusy(false);
      }
    },
    [busy, csrfToken, username],
  );

  const submitReset = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      if (busy) return;

      if (password !== confirmPassword) {
        setError('Passwords do not match.');
        return;
      }

      setBusy(true);
      setError('');
      try {
        const detail = await confirmPasswordReset(
          { uid: resetUid, token: resetToken, password },
          csrfToken,
        );
        setPassword('');
        setConfirmPassword('');
        goSignIn(detail);
      } catch (caught: unknown) {
        setError(caught instanceof SignInError ? caught.message : 'Password reset failed.');
        setPassword('');
        setConfirmPassword('');
      } finally {
        setBusy(false);
      }
    },
    [busy, confirmPassword, csrfToken, goSignIn, password, resetToken, resetUid],
  );

  const cardTitle =
    mode === 'forgot' ? 'Reset your password' : mode === 'reset' ? 'Choose a new password' : 'Sign in to TibaTrace HQ';
  const cardEyebrow =
    mode === 'forgot' ? 'Account recovery' : mode === 'reset' ? 'Set new password' : 'Protected workspace';

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
          <p className="eyebrow">{cardEyebrow}</p>
          <h2>{cardTitle}</h2>

          {mode === 'signin' ? (
            <>
              {notice ? (
                <p className="auth-success" role="status">
                  <Icon name="check" /> {notice}
                </p>
              ) : null}

              <form className="auth-form" onSubmit={submitSignIn}>
                <label htmlFor="signin-username">Email or username</label>
                <input
                  id="signin-username"
                  name="username"
                  autoComplete="username"
                  placeholder="name@organisation.co.ke"
                  spellCheck={false}
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

                <div className="auth-form-tools">
                  <button
                    className="auth-text-link"
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      setMode('forgot');
                      setError('');
                      setNotice('');
                      setForgotDetail('');
                      setPassword('');
                    }}
                  >
                    Forgot password?
                  </button>
                </div>

                {error ? (
                  <p className="auth-error" role="alert" aria-live="assertive">
                    <Icon name="alert" /> {error}
                  </p>
                ) : null}

                <button className="primary-button" type="submit" disabled={busy}>
                  {busy ? 'Signing in…' : 'Sign in'} <Icon name="arrow" />
                </button>
              </form>
            </>
          ) : null}

          {mode === 'forgot' ? (
            <>
              <p className="auth-card-lead">
                Enter the email or username for your HQ account. If it matches an active account, reset instructions will be prepared.
              </p>

              {forgotDetail ? (
                <p className="auth-success" role="status">
                  <Icon name="check" /> {forgotDetail}
                </p>
              ) : null}

              {!forgotDetail ? (
                <form className="auth-form" onSubmit={submitForgot}>
                  <label htmlFor="forgot-identity">Email or username</label>
                  <input
                    id="forgot-identity"
                    name="identity"
                    autoComplete="username"
                    placeholder="name@organisation.co.ke"
                    spellCheck={false}
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    disabled={busy}
                    required
                  />

                  {error ? (
                    <p className="auth-error" role="alert" aria-live="assertive">
                      <Icon name="alert" /> {error}
                    </p>
                  ) : null}

                  <button className="primary-button" type="submit" disabled={busy}>
                    {busy ? 'Submitting…' : 'Send reset link'} <Icon name="arrow" />
                  </button>
                </form>
              ) : null}

              {forgotDetail && resetUid && resetToken ? (
                <button
                  className="primary-button"
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setMode('reset');
                    setError('');
                    setPassword('');
                    setConfirmPassword('');
                  }}
                >
                  Continue to reset <Icon name="arrow" />
                </button>
              ) : null}

              <div className="auth-form-tools auth-form-tools-footer">
                <button
                  className="auth-text-link"
                  type="button"
                  disabled={busy}
                  onClick={() => goSignIn()}
                >
                  Back to sign in
                </button>
              </div>
            </>
          ) : null}

          {mode === 'reset' ? (
            <>
              <p className="auth-card-lead">
                Choose a new password for your HQ account. Use at least 12 characters.
              </p>

              <form className="auth-form" onSubmit={submitReset}>
                <label htmlFor="reset-password">New password</label>
                <input
                  id="reset-password"
                  name="password"
                  type="password"
                  autoComplete="new-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  disabled={busy}
                  required
                  minLength={12}
                />

                <label htmlFor="reset-password-confirm">Confirm password</label>
                <input
                  id="reset-password-confirm"
                  name="password_confirm"
                  type="password"
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  disabled={busy}
                  required
                  minLength={12}
                />

                {error ? (
                  <p className="auth-error" role="alert" aria-live="assertive">
                    <Icon name="alert" /> {error}
                  </p>
                ) : null}

                <button className="primary-button" type="submit" disabled={busy}>
                  {busy ? 'Updating…' : 'Update password'} <Icon name="arrow" />
                </button>
              </form>

              <div className="auth-form-tools auth-form-tools-footer">
                <button
                  className="auth-text-link"
                  type="button"
                  disabled={busy}
                  onClick={() => goSignIn()}
                >
                  Back to sign in
                </button>
              </div>
            </>
          ) : null}

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

function Unavailable({ detail }: { readonly detail?: string } = {}) {
  return (
    <div className="auth-page">
      <header><Brand /></header>
      <main className="auth-layout auth-layout-single">
        <section className="auth-card">
          <span className="auth-icon auth-icon-error"><Icon name="alert" /></span>
          <p className="eyebrow">Connection interrupted</p>
          <h2>HQ data is temporarily unavailable</h2>
          <p>
            {detail?.trim()
              || 'The web application could not reach the TibaTrace backend. Confirm the API is running on port 8000, then try again.'}
          </p>
          <button className="primary-button" type="button" onClick={() => window.location.reload()}>Try again <Icon name="refresh" /></button>
        </section>
      </main>
    </div>
  );
}

function useSummary(overview: HQOverview) {
  return useMemo(() => new Map(overview.data_summary.map((item) => [item.label, item.value])), [overview.data_summary]);
}

function parseHqHash(): { readonly view: WorkspaceView; readonly focus: string } {
  const raw = window.location.hash.replace(/^#/, '');
  const [viewPart = '', focus = ''] = raw.split('/');
  const view = navigation.some((item) => item.key === viewPart)
    ? (viewPart as WorkspaceView)
    : 'overview';
  return { view, focus };
}

function viewFromHash(): WorkspaceView {
  return parseHqHash().view;
}

function focusFromHash(): string {
  return parseHqHash().focus;
}

function navigateTo(view: WorkspaceView, onNavigate: (view: WorkspaceView) => void) {
  window.location.hash = view;
  onNavigate(view);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

/** In-app hash destinations like `#catalogue/skus`. Returns true when handled. */
function openHqDestination(destination: string, onNavigate?: (view: WorkspaceView) => void) {
  if (!destination.startsWith('#') || isExternalDestination(destination)) return false;
  const path = destination.slice(1);
  const viewKey = path.split('/')[0] ?? '';
  if (!navigation.some((item) => item.key === viewKey)) return false;
  const nextHash = `#${path}`;
  if (window.location.hash === nextHash) {
    window.dispatchEvent(new Event('hashchange'));
  } else {
    window.location.hash = path;
  }
  onNavigate?.(viewKey as WorkspaceView);
  return true;
}

function resolveFocusTargetId(view: WorkspaceView, focus: string): string {
  const map: Partial<Record<WorkspaceView, Record<string, string>>> = {
    people: {
      patients: 'people-patients',
      practitioners: 'people-practitioners',
      customers: 'people-customers',
    },
    catalogue: {
      skus: 'catalogue-skus',
      layers: 'catalogue-layers',
    },
    pricing: {
      books: 'pricing-books',
      assignments: 'pricing-assignments',
      overrides: 'pricing-overrides',
      locks: 'pricing-locks',
    },
    cash: {
      tills: 'cash-tills',
      sessions: 'cash-open-sessions',
      variances: 'cash-variances',
      forced: 'cash-forced',
      movements: 'cash-movements',
      installers: 'cash-installers',
    },
  };
  return map[view]?.[focus] ?? '';
}

/**
 * Whether a destination leaves the workspace.
 *
 * Only the API surfaces do: the OpenAPI page and the FHIR capability
 * statement, both of which are developer tools rather than operator screens.
 * They open in a new tab so somebody who clicks one does not lose the workspace
 * they were in, and they carry a marker so it is clear before clicking that the
 * link goes somewhere else.
 */
function isExternalDestination(destination: string) {
  return destination.startsWith('/api/');
}

/** Props that send a link out of the app, or nothing for an in-app hash. */
function externalLinkProps(destination: string) {
  return isExternalDestination(destination)
    ? { target: '_blank', rel: 'noreferrer' as const }
    : {};
}

function isCurrentHqDestination(destination: string) {
  const current = window.location.hash || '#overview';
  return destination === current || destination === `#${viewFromHash()}`;
}

function metricValue(overview: HQOverview, label: string) {
  return overview.metrics.find((metric) => metric.label === label)?.value ?? 0;
}

function overviewDataIcon(label: string): IconName {
  const icons: Record<string, IconName> = {
    'Active locations': 'building',
    'Active users': 'users',
    Patients: 'patients',
    Practitioners: 'users',
    Customers: 'building',
    'Commercial SKUs': 'inventory',
    'Clinical encounters': 'clinical',
    Conditions: 'patients',
    Observations: 'activity',
    'Inventory batches': 'inventory',
    'Open purchase orders': 'store',
    'Open sales orders': 'store',
    'Price books': 'docs',
    'Open tills': 'activity',
    'Active clinical releases': 'shield',
    'Code systems': 'docs',
    'Value sets': 'clinical',
    'FHIR idempotency records': 'security',
  };
  return icons[label] ?? 'overview';
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

function secondsSince(value: string, now: number) {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return 0;
  return Math.max(Math.floor((now - timestamp) / 1000), 0);
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
