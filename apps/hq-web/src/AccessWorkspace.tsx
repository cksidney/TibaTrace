import { FormEvent, useEffect, useMemo, useState } from 'react';

import { AccessUsersDirectory } from './AccessUsersDirectory.js';
import {
  createTenantRole,
  updateRolePermissions,
  type CapabilityCatalogue,
  type CapabilityMatrixData,
  type RegisterSessionSummary,
  type RoleDetail,
  type ServiceAccountItem,
  type ShiftReportSummary,
  type UserRoleGrant,
} from './api.js';
import { Icon } from './icons.js';

type AccessTab = 'users' | 'roles' | 'matrix' | 'grants' | 'machines' | 'custody' | 'activations';

const PAGE_SIZE = 10;

const TABS: readonly { readonly key: AccessTab; readonly label: string }[] = [
  { key: 'users', label: 'Users' },
  { key: 'roles', label: 'Roles & permissions' },
  { key: 'matrix', label: 'Coverage matrix' },
  { key: 'grants', label: 'Grants' },
  { key: 'machines', label: 'Service accounts' },
  { key: 'custody', label: 'Cash custody' },
  { key: 'activations', label: 'POS Activations' },
];

function formatMoney(value: number | string | null | undefined, currency: string) {
  if (value == null || value === '') return '—';
  const amount = typeof value === 'number' ? value : Number(value);
  if (Number.isNaN(amount)) return String(value);
  return new Intl.NumberFormat('en-KE', {
    style: 'currency',
    currency,
    maximumFractionDigits: 2,
  }).format(amount);
}

function formatTime(value: string | null | undefined) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('en-KE', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function titleCase(value: string) {
  return value
    .toLowerCase()
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function usePagedSearch<T>(
  items: readonly T[] | null,
  query: string,
  matches: (item: T, needle: string) => boolean,
  pageSize = PAGE_SIZE,
) {
  const [page, setPage] = useState(1);
  const filtered = useMemo(() => {
    if (!items) return [] as T[];
    const needle = query.trim().toLowerCase();
    if (!needle) return [...items];
    return items.filter((item) => matches(item, needle));
  }, [items, matches, query]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const pageItems = filtered.slice((safePage - 1) * pageSize, safePage * pageSize);

  useEffect(() => {
    setPage(1);
  }, [query, items]);

  useEffect(() => {
    if (page !== safePage) setPage(safePage);
  }, [page, safePage]);

  return {
    page: safePage,
    pageCount,
    pageItems,
    total: filtered.length,
    setPage,
  };
}

function AccessPager({
  page,
  pageCount,
  total,
  label,
  onPageChange,
}: {
  readonly page: number;
  readonly pageCount: number;
  readonly total: number;
  readonly label: string;
  readonly onPageChange: (page: number) => void;
}) {
  return (
    <footer className="access-pager">
      <span className="muted-cell">
        {total} {label}
        {total === 1 ? '' : 's'} · page {page} of {pageCount}
      </span>
      <div className="access-action-row">
        <button
          className="secondary-button"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
          type="button"
        >
          Previous
        </button>
        <button
          className="secondary-button"
          disabled={page >= pageCount}
          onClick={() => onPageChange(page + 1)}
          type="button"
        >
          Next
        </button>
      </div>
    </footer>
  );
}

function AccessSearchField({
  label,
  value,
  onChange,
  placeholder,
}: {
  readonly label: string;
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly placeholder: string;
}) {
  return (
    <label className="access-search-field">
      <span>{label}</span>
      <span className="access-search-control">
        <Icon name="search" />
        <input
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          type="search"
          value={value}
        />
      </span>
    </label>
  );
}

function RolePermissionsPanel({
  csrfToken,
  matrix,
  roles,
  tenantId,
  onRolesChanged,
}: {
  readonly csrfToken: string;
  readonly matrix: CapabilityMatrixData | null;
  readonly roles: readonly RoleDetail[] | null;
  readonly tenantId: string;
  readonly onRolesChanged: () => void;
}) {
  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const [nameDraft, setNameDraft] = useState('');
  const [capabilityDraft, setCapabilityDraft] = useState<string[]>([]);
  const [customCapability, setCustomCapability] = useState('');
  const [capabilityFilter, setCapabilityFilter] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [showCreateRole, setShowCreateRole] = useState(false);
  const [createRoleForm, setCreateRoleForm] = useState({
    code: '',
    name: '',
    capabilities: [] as string[],
  });

  const roleMatcher = useMemo(
    () => (role: RoleDetail, needle: string) => (
      role.code.toLowerCase().includes(needle)
      || role.name.toLowerCase().includes(needle)
      || role.capabilities.some((capability) => capability.toLowerCase().includes(needle))
    ),
    [],
  );
  const rolesPage = usePagedSearch(roles, search, roleMatcher, 8);
  const selected = (roles ?? []).find((role) => role.id === selectedId) ?? rolesPage.pageItems[0] ?? null;

  useEffect(() => {
    if (!selected) return;
    setSelectedId(selected.id);
    setNameDraft(selected.name);
    setCapabilityDraft([...selected.capabilities]);
    setNotice('');
    setError('');
    // Intentionally re-sync when the selected role identity or its saved permissions change.
  }, [selected?.id, selected?.name, selected?.capabilities?.join('|')]);

  const catalogue: CapabilityCatalogue = matrix?.catalogue ?? {
    capabilities: [],
    groups: [{ label: 'Assigned', capabilities: capabilityDraft }],
  };

  const groups = useMemo(() => {
    const needle = capabilityFilter.trim().toLowerCase();
    return catalogue.groups
      .map((group) => ({
        ...group,
        capabilities: group.capabilities.filter((capability) => (
          !needle || capability.toLowerCase().includes(needle)
        )),
      }))
      .filter((group) => group.capabilities.length > 0);
  }, [catalogue.groups, capabilityFilter]);

  const dirty = Boolean(
    selected
    && (
      nameDraft.trim() !== selected.name
      || [...capabilityDraft].sort().join('\n') !== [...selected.capabilities].sort().join('\n')
    ),
  );

  const toggleCapability = (capability: string) => {
    setCapabilityDraft((current) => (
      current.includes(capability)
        ? current.filter((item) => item !== capability)
        : [...current, capability].sort((a, b) => a.localeCompare(b))
    ));
  };

  const addCustomCapability = (event: FormEvent) => {
    event.preventDefault();
    const code = customCapability.trim();
    if (!code) return;
    setCapabilityDraft((current) => (
      current.includes(code) ? current : [...current, code].sort((a, b) => a.localeCompare(b))
    ));
    setCustomCapability('');
  };

  const save = async () => {
    if (!selected) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await updateRolePermissions(tenantId, selected.id, csrfToken, {
        name: nameDraft.trim(),
        capabilities: capabilityDraft,
        is_active: selected.is_active,
      });
      setNotice(`Updated permissions for ${selected.code}.`);
      onRolesChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update role permissions.');
    } finally {
      setBusy(false);
    }
  };

  const createRole = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const created = await createTenantRole(tenantId, csrfToken, {
        code: createRoleForm.code.trim(),
        name: createRoleForm.name.trim(),
        capabilities: createRoleForm.capabilities,
      });
      setNotice(`Created role ${created.code}. Assign it to users from the Users tab.`);
      setShowCreateRole(false);
      setCreateRoleForm({ code: '', name: '', capabilities: [] });
      setSelectedId(created.id);
      onRolesChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create role.');
    } finally {
      setBusy(false);
    }
  };

  const toggleRoleActive = async () => {
    if (!selected) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await updateRolePermissions(tenantId, selected.id, csrfToken, {
        is_active: !selected.is_active,
      });
      setNotice(`${selected.code} is now ${selected.is_active ? 'inactive' : 'active'}.`);
      onRolesChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update role status.');
    } finally {
      setBusy(false);
    }
  };

  if (!roles) {
    return <p className="muted-cell">Loading roles…</p>;
  }

  return (
    <div className="access-roles-layout">
      <aside className="access-roles-list panel-inset">
        <div className="access-role-list-head">
          <AccessSearchField
            label="Find role"
            onChange={setSearch}
            placeholder="Code, name, or capability"
            value={search}
          />
          <button
            className="secondary-button"
            onClick={() => setShowCreateRole((value) => !value)}
            type="button"
          >
            {showCreateRole ? 'Cancel' : 'Add role'}
          </button>
        </div>

        {showCreateRole ? (
          <form className="access-create-role" onSubmit={(event) => void createRole(event)}>
            <label>
              <span>Role code</span>
              <input
                onChange={(event) => setCreateRoleForm((current) => ({ ...current, code: event.target.value }))}
                placeholder="e.g. BRANCH_MANAGER"
                required
                value={createRoleForm.code}
              />
            </label>
            <label>
              <span>Display name</span>
              <input
                onChange={(event) => setCreateRoleForm((current) => ({ ...current, name: event.target.value }))}
                placeholder="e.g. Branch manager"
                required
                value={createRoleForm.name}
              />
            </label>
            <p className="muted-cell">Capabilities can be refined after the role is created.</p>
            <button className="primary-button" disabled={busy} type="submit">
              {busy ? 'Creating…' : 'Create role'}
            </button>
          </form>
        ) : null}

        {!roles.length ? (
          <p className="muted-cell">No roles yet. Create a role to start granting rights.</p>
        ) : (
          <ul className="access-role-nav">
            {rolesPage.pageItems.map((role) => {
              const assigned = matrix?.roles.find((item) => item.id === role.id)?.assigned_users_count ?? role.user_count;
              const active = selected?.id === role.id;
              return (
                <li key={role.id}>
                  <button
                    className={active ? 'access-role-nav-item is-active' : 'access-role-nav-item'}
                    onClick={() => setSelectedId(role.id)}
                    type="button"
                  >
                    <span>
                      <strong>{role.code}</strong>
                      <small>{role.name}{role.is_active ? '' : ' · inactive'}</small>
                    </span>
                    <em>{assigned}</em>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        <AccessPager
          label="role"
          onPageChange={rolesPage.setPage}
          page={rolesPage.page}
          pageCount={rolesPage.pageCount}
          total={rolesPage.total}
        />
      </aside>

      {selected ? (
        <section className="access-role-editor panel-inset">
          <header className="access-role-editor-head">
            <div>
              <p className="eyebrow">{selected.is_system ? 'System role' : 'Custom role'}</p>
              <h3>{selected.code}</h3>
              <p className="muted-cell">
                {capabilityDraft.length} permission{capabilityDraft.length === 1 ? '' : 's'} selected
                {dirty ? ' · unsaved changes' : ''}
                {selected.is_active ? '' : ' · inactive'}
              </p>
            </div>
            <div className="access-action-row">
              {selected.code !== 'TENANT_ADMIN' ? (
                <button className="ghost-button" disabled={busy} onClick={() => void toggleRoleActive()} type="button">
                  {selected.is_active ? 'Deactivate' : 'Activate'}
                </button>
              ) : null}
              <button
                className="ghost-button"
                disabled={!dirty || busy}
                onClick={() => {
                  setNameDraft(selected.name);
                  setCapabilityDraft([...selected.capabilities]);
                }}
                type="button"
              >
                Reset
              </button>
              <button className="primary-button" disabled={!dirty || busy} onClick={() => void save()} type="button">
                {busy ? 'Saving…' : 'Save permissions'}
              </button>
            </div>
          </header>

          <label className="access-search-field">
            <span>Display name</span>
            <input onChange={(event) => setNameDraft(event.target.value)} value={nameDraft} />
          </label>

          <div className="access-capability-toolbar">
            <AccessSearchField
              label="Filter permissions"
              onChange={setCapabilityFilter}
              placeholder="e.g. inventory.read"
              value={capabilityFilter}
            />
            <form className="access-custom-capability" onSubmit={addCustomCapability}>
              <label>
                <span>Add custom</span>
                <input
                  onChange={(event) => setCustomCapability(event.target.value)}
                  placeholder="domain.action"
                  value={customCapability}
                />
              </label>
              <button className="secondary-button" type="submit">Add</button>
            </form>
          </div>

          <div className="access-capability-groups">
            {groups.map((group) => (
              <section className="access-capability-group" key={group.label}>
                <header>
                  <h4>{group.label}</h4>
                  <small>
                    {group.capabilities.filter((capability) => capabilityDraft.includes(capability)).length}
                    /
                    {group.capabilities.length}
                  </small>
                </header>
                <div className="access-capability-grid">
                  {group.capabilities.map((capability) => {
                    const checked = capabilityDraft.includes(capability);
                    return (
                      <label
                        className={checked ? 'access-capability-option is-selected' : 'access-capability-option'}
                        key={capability}
                        title={capability}
                      >
                        <input
                          checked={checked}
                          onChange={() => toggleCapability(capability)}
                          type="checkbox"
                        />
                        <code>{capability}</code>
                      </label>
                    );
                  })}
                </div>
              </section>
            ))}
          </div>

          {notice ? <p className="inline-success" role="status">{notice}</p> : null}
          {error ? <p className="inline-alert" role="alert">{error}</p> : null}
        </section>
      ) : null}
    </div>
  );
}

export function AccessWorkspace({
  cashFailed,
  csrfToken,
  forcedClosures,
  identityFailed,
  matrix,
  onRolesChanged,
  roles,
  serviceAccounts,
  sessions,
  tenantId,
  userRoles,
  variances,
}: {
  readonly cashFailed: boolean;
  readonly csrfToken: string;
  readonly forcedClosures: readonly ShiftReportSummary[] | null;
  readonly identityFailed: boolean;
  readonly matrix: CapabilityMatrixData | null;
  readonly onRolesChanged: () => void;
  readonly roles: readonly RoleDetail[] | null;
  readonly serviceAccounts: readonly ServiceAccountItem[] | null;
  readonly sessions: readonly RegisterSessionSummary[] | null;
  readonly tenantId: string;
  readonly userRoles: readonly UserRoleGrant[] | null;
  readonly variances: readonly ShiftReportSummary[] | null;
}) {
  const [tab, setTab] = useState<AccessTab>('users');
  const [grantSearch, setGrantSearch] = useState('');
  const [machineSearch, setMachineSearch] = useState('');
  const [matrixSearch, setMatrixSearch] = useState('');
  const [custodySearch, setCustodySearch] = useState('');

  const grantMatcher = useMemo(
    () => (grant: UserRoleGrant, needle: string) => (
      grant.user_username.toLowerCase().includes(needle)
      || grant.role_code.toLowerCase().includes(needle)
      || grant.role_name.toLowerCase().includes(needle)
    ),
    [],
  );
  const grantsPage = usePagedSearch(userRoles, grantSearch, grantMatcher);

  const machineMatcher = useMemo(
    () => (account: ServiceAccountItem, needle: string) => (
      account.code.toLowerCase().includes(needle)
      || account.display_name.toLowerCase().includes(needle)
      || account.capabilities.some((capability) => capability.toLowerCase().includes(needle))
    ),
    [],
  );
  const machinesPage = usePagedSearch(serviceAccounts, machineSearch, machineMatcher);

  const matrixCapabilities = useMemo(() => {
    if (!matrix) return [] as string[];
    const caps = new Set<string>();
    for (const role of matrix.roles) {
      for (const capability of role.capabilities) caps.add(capability);
    }
    const needle = matrixSearch.trim().toLowerCase();
    return [...caps]
      .filter((capability) => !needle || capability.toLowerCase().includes(needle))
      .sort((a, b) => a.localeCompare(b));
  }, [matrix, matrixSearch]);

  const matrixCapPage = useMemo(() => {
    const pageCount = Math.max(1, Math.ceil(matrixCapabilities.length / PAGE_SIZE));
    return { pageCount, items: matrixCapabilities };
  }, [matrixCapabilities]);
  const [matrixPage, setMatrixPage] = useState(1);
  useEffect(() => setMatrixPage(1), [matrixSearch, matrix]);
  const matrixPageItems = matrixCapPage.items.slice(
    (Math.min(matrixPage, matrixCapPage.pageCount) - 1) * PAGE_SIZE,
    Math.min(matrixPage, matrixCapPage.pageCount) * PAGE_SIZE,
  );

  const custodyRows = useMemo(() => {
    const needle = custodySearch.trim().toLowerCase();
    const rows = [
      ...(sessions ?? []).map((session) => ({
        id: `session-${session.id}`,
        kind: 'Open session',
        register: session.register_code,
        actor: session.opened_by_username,
        date: session.business_date,
        detail: formatTime(session.opened_at),
        status: session.forced_closure ? 'FORCED' : session.state,
      })),
      ...(variances ?? []).map((report) => ({
        id: `variance-${report.id}`,
        kind: 'Variance',
        register: report.register_code,
        actor: report.report_number,
        date: report.business_date,
        detail: formatMoney(report.snapshot?.variance?.difference, 'KES'),
        status: 'VARIANCE',
      })),
      ...(forcedClosures ?? []).map((report) => ({
        id: `forced-${report.id}`,
        kind: 'Forced closure',
        register: report.register_code,
        actor: report.generated_by_username,
        date: report.business_date,
        detail: report.closure_reason || titleCase(report.closure_type),
        status: 'FORCED',
      })),
    ];
    if (!needle) return rows;
    return rows.filter((row) => (
      [row.kind, row.register, row.actor, row.date, row.detail, row.status]
        .join(' ')
        .toLowerCase()
        .includes(needle)
    ));
  }, [custodySearch, forcedClosures, sessions, variances]);

  const custodyMatcher = useMemo(
    () => () => true,
    [],
  );
  const custodyPage = usePagedSearch(custodyRows, '', custodyMatcher);

  return (
    <section className="access-workspace">
      <nav aria-label="Access sections" className="access-tabs segmented">
        {TABS.map((option) => (
          <button
            aria-pressed={tab === option.key}
            className={tab === option.key ? 'segmented-option is-active' : 'segmented-option'}
            key={option.key}
            onClick={() => setTab(option.key)}
            type="button"
          >
            {option.label}
          </button>
        ))}
      </nav>

      {identityFailed && tab !== 'custody' && tab !== 'users' && tab !== 'roles' ? (
        <div className="inline-alert" role="status">
          <Icon name="alert" />
          Identity data could not be loaded for this tenant.
        </div>
      ) : null}

      {tab === 'users' ? (
        <AccessUsersDirectory csrfToken={csrfToken} roles={roles} tenantId={tenantId} />
      ) : null}

      {tab === 'roles' ? (
        <article className="panel access-panel">
          <header className="panel-header access-panel-header">
            <div>
              <p className="eyebrow">Role governance</p>
              <h2>Roles & permission grants</h2>
              <p className="muted-cell">Create tenant roles, set capabilities, then assign them to users.</p>
            </div>
            <span className="panel-meta">{(roles ?? []).length} roles</span>
          </header>
          <RolePermissionsPanel
            csrfToken={csrfToken}
            matrix={matrix}
            onRolesChanged={onRolesChanged}
            roles={roles}
            tenantId={tenantId}
          />
        </article>
      ) : null}

      {tab === 'matrix' ? (
        <article className="panel access-panel">
          <header className="panel-header access-panel-header">
            <div>
              <p className="eyebrow">Coverage</p>
              <h2>Role × capability matrix</h2>
            </div>
            <span className="panel-meta">
              {matrix ? `${matrix.roles.length} roles · ${matrixCapabilities.length} capabilities` : '—'}
            </span>
          </header>
          <AccessSearchField
            label="Filter capabilities"
            onChange={setMatrixSearch}
            placeholder="Search capability codes"
            value={matrixSearch}
          />
          {!matrix ? (
            <p className="muted-cell">Loading capability matrix…</p>
          ) : matrix.roles.length === 0 || !matrixCapabilities.length ? (
            <p className="muted-cell">No capability coverage to display.</p>
          ) : (
            <>
              <div className="table-scroll capability-matrix-scroll">
                <table className="capability-matrix">
                  <thead>
                    <tr>
                      <th className="capability-matrix-sticky" scope="col">Capability</th>
                      {matrix.roles.map((role) => (
                        <th key={role.id} scope="col" title={role.name}>
                          <span className="capability-matrix-role">{role.code}</span>
                          <small>{role.assigned_users_count}</small>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {matrixPageItems.map((capability) => (
                      <tr key={capability}>
                        <th className="capability-matrix-sticky" scope="row"><code>{capability}</code></th>
                        {matrix.roles.map((role) => {
                          const granted = role.capabilities.includes(capability);
                          return (
                            <td className={granted ? 'matrix-cell-on' : 'matrix-cell-off'} key={`${role.id}-${capability}`}>
                              {granted ? <span aria-label={`${role.code} grants ${capability}`} className="matrix-check">✓</span> : <span aria-hidden="true" className="matrix-empty">·</span>}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <AccessPager
                label="capability"
                onPageChange={setMatrixPage}
                page={Math.min(matrixPage, matrixCapPage.pageCount)}
                pageCount={matrixCapPage.pageCount}
                total={matrixCapabilities.length}
              />
            </>
          )}
        </article>
      ) : null}

      {tab === 'grants' ? (
        <article className="panel access-panel">
          <header className="panel-header access-panel-header">
            <div>
              <p className="eyebrow">Assignments</p>
              <h2>User-to-role grants</h2>
            </div>
          </header>
          <AccessSearchField
            label="Search grants"
            onChange={setGrantSearch}
            placeholder="User or role"
            value={grantSearch}
          />
          {!userRoles ? (
            <p className="muted-cell">Loading grants…</p>
          ) : grantsPage.total === 0 ? (
            <p className="muted-cell">No role grants match this search.</p>
          ) : (
            <>
              <div className="table-scroll">
                <table className="access-compact-table">
                  <thead>
                    <tr>
                      <th>User</th>
                      <th>Role</th>
                      <th>Code</th>
                      <th>Granted</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {grantsPage.pageItems.map((grant) => (
                      <tr key={grant.id}>
                        <td><strong>{grant.user_username}</strong></td>
                        <td>{grant.role_name}</td>
                        <td><code>{grant.role_code}</code></td>
                        <td><small className="muted-cell">{formatTime(grant.created_at)}</small></td>
                        <td>
                          {grant.is_active
                            ? <span className="status-badge status-active"><i /> Active</span>
                            : <span className="muted-cell">Revoked</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <AccessPager
                label="grant"
                onPageChange={grantsPage.setPage}
                page={grantsPage.page}
                pageCount={grantsPage.pageCount}
                total={grantsPage.total}
              />
            </>
          )}
        </article>
      ) : null}

      {tab === 'machines' ? (
        <article className="panel access-panel">
          <header className="panel-header access-panel-header">
            <div>
              <p className="eyebrow">Integrations</p>
              <h2>Service accounts</h2>
            </div>
          </header>
          <AccessSearchField
            label="Search accounts"
            onChange={setMachineSearch}
            placeholder="Code, name, or capability"
            value={machineSearch}
          />
          {!serviceAccounts ? (
            <p className="muted-cell">Loading service accounts…</p>
          ) : machinesPage.total === 0 ? (
            <p className="muted-cell">No service accounts match this search.</p>
          ) : (
            <>
              <div className="table-scroll">
                <table className="access-compact-table">
                  <thead>
                    <tr>
                      <th>Code</th>
                      <th>Name</th>
                      <th>Capabilities</th>
                      <th>Fingerprint</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {machinesPage.pageItems.map((account) => (
                      <tr key={account.id}>
                        <td><code>{account.code}</code></td>
                        <td><strong>{account.display_name}</strong></td>
                        <td>
                          <span className="muted-cell">
                            {account.capabilities.length
                              ? account.capabilities.slice(0, 3).join(', ')
                                + (account.capabilities.length > 3 ? ` +${account.capabilities.length - 3}` : '')
                              : 'None'}
                          </span>
                        </td>
                        <td>
                          <code>
                            {account.credential_fingerprint
                              ? `${account.credential_fingerprint.slice(0, 12)}…`
                              : 'None'}
                          </code>
                        </td>
                        <td>
                          {account.is_active
                            ? <span className="status-badge status-active"><i /> Active</span>
                            : <span className="muted-cell">Inactive</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <AccessPager
                label="account"
                onPageChange={machinesPage.setPage}
                page={machinesPage.page}
                pageCount={machinesPage.pageCount}
                total={machinesPage.total}
              />
            </>
          )}
        </article>
      ) : null}

      {tab === 'custody' ? (
        <article className="panel access-panel">
          <header className="panel-header access-panel-header">
            <div>
              <p className="eyebrow">Financial custody</p>
              <h2>Registers & exceptions</h2>
            </div>
            <a className="panel-meta-link" href="#cash">Open cash desk</a>
          </header>
          {cashFailed ? (
            <div className="inline-alert" role="status">
              <Icon name="alert" />
              Cash and shift data could not be loaded.
            </div>
          ) : (
            <>
              <AccessSearchField
                label="Search custody events"
                onChange={setCustodySearch}
                placeholder="Register, operator, or status"
                value={custodySearch}
              />
              {sessions === null || variances === null || forcedClosures === null ? (
                <p className="muted-cell">Loading custody records…</p>
              ) : custodyPage.total === 0 ? (
                <p className="muted-cell">No open sessions, variances, or forced closures.</p>
              ) : (
                <>
                  <div className="table-scroll">
                    <table className="access-compact-table">
                      <thead>
                        <tr>
                          <th>Kind</th>
                          <th>Register</th>
                          <th>Actor / ref</th>
                          <th>Date</th>
                          <th>Detail</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {custodyPage.pageItems.map((row) => (
                          <tr key={row.id}>
                            <td><small>{row.kind}</small></td>
                            <td><code>{row.register}</code></td>
                            <td><small>{row.actor}</small></td>
                            <td><span className="muted-cell">{row.date}</span></td>
                            <td><small className="muted-cell">{row.detail}</small></td>
                            <td><span className={`status-badge status-${row.status.toLowerCase()}`}><i /> {titleCase(row.status)}</span></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <AccessPager
                    label="record"
                    onPageChange={custodyPage.setPage}
                    page={custodyPage.page}
                    pageCount={custodyPage.pageCount}
                    total={custodyPage.total}
                  />
                </>
              )}
            </>
          )}
        </article>
      ) : null}

      {tab === 'activations' ? (
        <article className="panel access-panel">
          <header className="panel-header access-panel-header">
            <div>
              <p className="eyebrow">Platform Governance</p>
              <h2>POS Device Activations & Quotas</h2>
              <p className="muted-cell">
                Only the TibaTrace Platform Owner may approve, activate, renew, suspend, or revoke POS device activations. Tenant Admins submit and track requests.
              </p>
            </div>
            <span className="panel-meta">Platform-governed</span>
          </header>
          <PosActivationsPanel tenantId={tenantId} csrfToken={csrfToken} />
        </article>
      ) : null}
    </section>
  );
}

interface PosActivationSummary {
  readonly id: string;
  readonly tenantId: string;
  readonly branchId: string;
  readonly register: string;
  readonly deviceName: string;
  readonly deviceType: string;
  readonly deviceFingerprint: string;
  readonly requester: string;
  readonly justification: string;
  readonly state: string;
}

function PosActivationsPanel({
  tenantId,
  csrfToken,
}: {
  readonly tenantId: string;
  readonly csrfToken: string;
}) {
  const [filter, setFilter] = useState<'ALL' | 'SUBMITTED' | 'APPROVED' | 'ACTIVATED' | 'SUSPENDED' | 'REVOKED'>('ALL');
  const [search, setSearch] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);
  const [activations, setActivations] = useState<readonly PosActivationSummary[]>([]);
  const [selectedRequestId, setSelectedRequestId] = useState<string | null>(null);
  const [approvalRationale, setApprovalRationale] = useState('');
  const [generatedChallenge, setGeneratedChallenge] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    setError('');
    fetch(`/api/v1/platform/pos-activations/requests/?tenant_id=${encodeURIComponent(tenantId)}`, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Activation service returned HTTP ${response.status}.`);
        const data = await response.json() as PosActivationSummary[] | { results?: PosActivationSummary[] };
        return Array.isArray(data) ? data : (data.results ?? []);
      })
      .then((items) => {
        if (!cancelled) setActivations(items);
      })
      .catch(() => {
        if (!cancelled) {
          setActivations([]);
          setError('POS activation service is unavailable. No approval action has been performed.');
        }
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  const filtered = useMemo(() => {
    return activations.filter((a) => {
      const matchFilter = filter === 'ALL' || a.state === filter;
      const matchSearch =
        !search.trim() ||
        [a.id, a.deviceName, a.branchId, a.register, a.requester, a.justification]
          .join(' ')
          .toLowerCase()
          .includes(search.trim().toLowerCase());
      return matchFilter && matchSearch;
    });
  }, [activations, filter, search]);

  const activeItem = useMemo(
    () => activations.find((a) => a.id === selectedRequestId) ?? filtered[0] ?? null,
    [activations, filtered, selectedRequestId],
  );

  const handlePlatformApprove = async () => {
    if (!activeItem || !approvalRationale.trim()) return;
    setBusy(true);
    setError('');
    setNotice('');
    setGeneratedChallenge(null);
    try {
      const response = await fetch(`/api/v1/platform/pos-activations/requests/${encodeURIComponent(activeItem.id)}/approve/`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({ approval_rationale: approvalRationale.trim() }),
      });
      if (!response.ok) throw new Error(`Activation service returned HTTP ${response.status}.`);
      const payload = await response.json() as { challengeCode?: string; challenge_code?: string };
      const challenge = payload.challengeCode ?? payload.challenge_code;
      if (!challenge) throw new Error('Activation service did not return a one-time challenge.');
      setGeneratedChallenge(challenge);
      setNotice(`Request ${activeItem.id} approved by the Platform Owner.`);
      setApprovalRationale('');
    } catch {
      setError('Approval failed closed. The activation service did not confirm the action.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="access-activations-container">
      <div className="access-users-toolbar">
        <form className="access-users-search" onSubmit={(e) => e.preventDefault()}>
          <label>
            <span>Search activations</span>
            <input
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Device name, ID, branch, or register"
              value={search}
            />
          </label>
        </form>
        <label>
          <span>Status Filter</span>
          <select value={filter} onChange={(e) => setFilter(e.target.value as any)}>
            <option value="ALL">All Activation Statuses</option>
            <option value="SUBMITTED">Pending Review (Submitted)</option>
            <option value="APPROVED">Approved (Enrolment Issued)</option>
            <option value="ACTIVATED">Active Terminals</option>
            <option value="SUSPENDED">Suspended</option>
            <option value="REVOKED">Revoked</option>
          </select>
        </label>
      </div>

      {notice ? <p className="inline-success" role="status">{notice}</p> : null}
      {error ? <p className="inline-alert" role="alert">{error}</p> : null}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 380px', gap: 16, marginTop: 16 }}>
        <div className="table-scroll">
          <table className="access-users-table">
            <thead>
              <tr>
                <th scope="col">Request ID</th>
                <th scope="col">Device / Register</th>
                <th scope="col">Branch</th>
                <th scope="col">Status</th>
                <th scope="col">Action</th>
              </tr>
            </thead>
            <tbody>
              {!busy && filtered.length === 0 ? (
                <tr><td colSpan={5}>No activation requests are available.</td></tr>
              ) : null}
              {filtered.map((item) => (
                <tr key={item.id} className={activeItem?.id === item.id ? 'is-selected' : ''}>
                  <td><code>{item.id}</code></td>
                  <td>
                    <strong>{item.deviceName}</strong>
                    <small className="muted-cell">{item.register} · {item.deviceType}</small>
                  </td>
                  <td><span className="muted-cell">{item.branchId}</span></td>
                  <td>
                    <span className={`status-badge status-${item.state === 'ACTIVATED' ? 'active' : item.state === 'SUBMITTED' ? 'warning' : 'suspended'}`}>
                      <i /> {item.state}
                    </span>
                  </td>
                  <td>
                    <button
                      className="ghost-button"
                      onClick={() => setSelectedRequestId(item.id)}
                      type="button"
                    >
                      Review
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {activeItem ? (
          <div style={{ border: '1px solid var(--surface-border, #CBD5E1)', borderRadius: 10, padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
            <h3 style={{ margin: 0, fontSize: 16 }}>{activeItem.deviceName}</h3>
            <small className="muted-cell">{activeItem.id} · {activeItem.tenantId}</small>

            <dl style={{ margin: 0, display: 'grid', gap: 6, fontSize: 13 }}>
              <div><dt style={{ opacity: 0.6 }}>Branch:</dt><dd style={{ margin: 0, fontWeight: 600 }}>{activeItem.branchId}</dd></div>
              <div><dt style={{ opacity: 0.6 }}>Fingerprint:</dt><dd style={{ margin: 0 }}><code>{activeItem.deviceFingerprint}</code></dd></div>
              <div><dt style={{ opacity: 0.6 }}>Requester:</dt><dd style={{ margin: 0 }}>{activeItem.requester}</dd></div>
              <div><dt style={{ opacity: 0.6 }}>Justification:</dt><dd style={{ margin: 0 }}>{activeItem.justification}</dd></div>
            </dl>

            {generatedChallenge ? (
              <div style={{ background: '#F0FDF4', border: '1px solid #86EFAC', padding: 12, borderRadius: 8, marginTop: 8 }}>
                <strong style={{ color: '#166534', fontSize: 12, textTransform: 'uppercase' }}>Enrolment Challenge Issued</strong>
                <code style={{ display: 'block', fontSize: 18, fontWeight: 'bold', margin: '4px 0', letterSpacing: 1 }}>{generatedChallenge}</code>
                <small className="muted-cell">Single-use challenge code. Valid for 15 minutes.</small>
              </div>
            ) : null}

            <div style={{ borderTop: '1px solid #CBD5E1', paddingTop: 12, marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <strong style={{ fontSize: 12, textTransform: 'uppercase', opacity: 0.7 }}>Platform Owner Action</strong>
              <label>
                <span style={{ fontSize: 12 }}>Approval / Action Rationale:</span>
                <input
                  onChange={(e) => setApprovalRationale(e.target.value)}
                  placeholder="Provide audit rationale..."
                  style={{ width: '100%', padding: '6px 10px', borderRadius: 6, border: '1px solid #94A3B8', marginTop: 4 }}
                  value={approvalRationale}
                />
              </label>
              <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                <button
                  className="primary-button"
                  disabled={busy || !approvalRationale.trim()}
                  onClick={handlePlatformApprove}
                  type="button"
                >
                  Approve & Issue Code
                </button>
                <button className="secondary-button" type="button">Reject</button>
              </div>
              <small className="muted-cell">Only users with Platform Owner capability can execute approval actions.</small>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
