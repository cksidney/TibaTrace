import { useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';

import {
  activateTenant,
  createTenant,
  HQApiError,
  loadTenants,
  suspendTenant,
  updateTenant,
} from './api.js';
import type { HQOverview, TenantWorkspace } from './api.js';
import { Icon } from './icons.js';

interface TenantManagementProps {
  readonly csrfToken: string;
  readonly onChanged: () => Promise<void>;
  readonly overview: HQOverview;
}

type TenantDialog =
  | { readonly mode: 'create' }
  | { readonly mode: 'edit'; readonly tenant: TenantWorkspace }
  | { readonly mode: 'activate'; readonly tenant: TenantWorkspace }
  | { readonly mode: 'suspend'; readonly tenant: TenantWorkspace }
  | null;

interface TenantFormState {
  readonly countryCode: string;
  readonly name: string;
  readonly slug: string;
  readonly supportEmail: string;
  readonly timeZone: string;
}

const emptyTenant: TenantFormState = {
  countryCode: 'KE',
  name: '',
  slug: '',
  supportEmail: '',
  timeZone: 'Africa/Nairobi',
};

export function TenantManagement({
  csrfToken,
  onChanged,
  overview,
}: TenantManagementProps) {
  const [tenants, setTenants] = useState<readonly TenantWorkspace[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('ALL');
  const [dialog, setDialog] = useState<TenantDialog>(null);
  const canManage = overview.is_platform_overview;

  const reload = async (signal?: AbortSignal) => {
    setFailed(false);
    try {
      setTenants(await loadTenants(signal));
    } catch {
      if (!signal?.aborted) setFailed(true);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    void reload(controller.signal);
    return () => controller.abort();
  }, [overview.generated_at]);

  const visible = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return (tenants ?? []).filter((tenant) => {
      const matchesQuery = `${tenant.name} ${tenant.slug} ${tenant.country_code}`
        .toLowerCase()
        .includes(normalized);
      return matchesQuery && (status === 'ALL' || tenant.status === status);
    });
  }, [query, status, tenants]);

  const totals = useMemo(
    () => (tenants ?? []).reduce(
      (result, tenant) => ({
        active: result.active + (tenant.status === 'ACTIVE' ? 1 : 0),
        locations: result.locations + tenant.active_location_count,
        users: result.users + tenant.active_user_count,
      }),
      { active: 0, locations: 0, users: 0 },
    ),
    [tenants],
  );

  return (
    <>
      <section className="metric-grid network-metrics" aria-label="Tenant network totals">
        <TenantMetric icon="building" label="Tenant workspaces" value={tenants?.length ?? 0} detail={`${totals.active} active`} />
        <TenantMetric icon="store" label="Care locations" value={totals.locations} detail="Active tenant sites" />
        <TenantMetric icon="users" label="Tenant users" value={totals.users} detail="Enabled user accounts" />
        <TenantMetric icon="shield" label="Suspended" value={(tenants?.length ?? 0) - totals.active} detail="Access held at platform level" />
      </section>

      <article className="panel table-panel tenant-management">
        <div className="table-toolbar">
          <div className="panel-header">
            <div><p>Tenant management</p><h2>Workspace directory</h2></div>
            {canManage ? (
              <button onClick={() => setDialog({ mode: 'create' })} type="button">
                <Icon name="plus" /> Create tenant
              </button>
            ) : null}
          </div>
          <div className="table-filters">
            <label className="search-field">
              <span className="sr-only">Search tenants</span>
              <Icon name="search" />
              <input onChange={(event) => setQuery(event.target.value)} placeholder="Search tenant, slug or country" type="search" value={query} />
            </label>
            <label>
              <span className="sr-only">Filter tenants by status</span>
              <select onChange={(event) => setStatus(event.target.value)} value={status}>
                <option value="ALL">All statuses</option>
                <option value="ACTIVE">Active</option>
                <option value="SUSPENDED">Suspended</option>
              </select>
            </label>
          </div>
        </div>

        {failed ? (
          <div className="inline-alert" role="alert"><Icon name="alert" /> Tenant data could not be loaded.</div>
        ) : tenants === null ? (
          <p className="muted-cell">Loading tenant workspaces…</p>
        ) : visible.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Tenant</th>
                  <th>Status</th>
                  <th>Organisations</th>
                  <th>Locations</th>
                  <th>Patients</th>
                  <th>Users</th>
                  <th>Locale</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((tenant) => (
                  <tr key={tenant.id}>
                    <td>
                      <strong>{tenant.name}</strong>
                      <small className="tenant-slug">{tenant.slug}</small>
                    </td>
                    <td><TenantStatus value={tenant.status} /></td>
                    <td>{tenant.active_organization_count}</td>
                    <td>{tenant.active_location_count}</td>
                    <td>{tenant.active_patient_count}</td>
                    <td>{tenant.active_user_count}</td>
                    <td><small>{tenant.country_code} · {tenant.time_zone}</small></td>
                    <td>
                      {canManage ? (
                        <div className="tenant-row-actions">
                          <button onClick={() => setDialog({ mode: 'edit', tenant })} type="button">Edit</button>
                          {tenant.status === 'ACTIVE' ? (
                            <button className="danger-link" onClick={() => setDialog({ mode: 'suspend', tenant })} type="button">Suspend</button>
                          ) : (
                            <button onClick={() => setDialog({ mode: 'activate', tenant })} type="button">Activate</button>
                          )}
                        </div>
                      ) : <span className="muted-cell">View only</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="tenant-empty">
            <Icon name="network" />
            <strong>No tenant workspaces match</strong>
            <span>Adjust the search or status filter.</span>
          </div>
        )}
      </article>

      <section className="tenant-control-grid">
        <article className="panel tenant-control-card">
          <span className="tenant-control-icon"><Icon name="shield" /></span>
          <div>
            <p>Lifecycle control</p>
            <h2>Suspension preserves the audit trail</h2>
            <span>Workspaces are held rather than deleted, retaining locations, users, transactions, catalogue selections, and compliance evidence.</span>
          </div>
        </article>
        <article className="panel tenant-control-card">
          <span className="tenant-control-icon"><Icon name="database" /></span>
          <div>
            <p>Isolation model</p>
            <h2>Every operational record remains tenant-scoped</h2>
            <span>Platform administrators can operate across workspaces; tenant operators only see the organisation assigned to their identity.</span>
          </div>
        </article>
      </section>

      {dialog ? (
        <TenantDialogForm
          csrfToken={csrfToken}
          dialog={dialog}
          onClose={() => setDialog(null)}
          onSaved={async () => {
            setDialog(null);
            await Promise.all([reload(), onChanged()]);
          }}
        />
      ) : null}
    </>
  );
}

function TenantDialogForm({
  csrfToken,
  dialog,
  onClose,
  onSaved,
}: {
  readonly csrfToken: string;
  readonly dialog: Exclude<TenantDialog, null>;
  readonly onClose: () => void;
  readonly onSaved: () => Promise<void>;
}) {
  const tenant = dialog.mode === 'create' ? null : dialog.tenant;
  const [form, setForm] = useState<TenantFormState>(() => tenant ? {
    countryCode: tenant.country_code,
    name: tenant.name,
    slug: tenant.slug,
    supportEmail: String(tenant.metadata.support_email ?? ''),
    timeZone: tenant.time_zone,
  } : emptyTenant);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const setField = (field: keyof TenantFormState, value: string) => {
    setForm((current) => ({ ...current, [field]: value }));
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      if (dialog.mode === 'activate') {
        await activateTenant(dialog.tenant.id, csrfToken);
      } else if (dialog.mode === 'suspend') {
        await suspendTenant(dialog.tenant.id, reason, csrfToken);
      } else {
        const values = {
          country_code: form.countryCode,
          metadata: {
            ...(tenant?.metadata ?? {}),
            support_email: form.supportEmail,
          },
          name: form.name,
          slug: form.slug,
          time_zone: form.timeZone,
        };
        if (dialog.mode === 'create') {
          await createTenant(values, csrfToken);
        } else {
          await updateTenant(dialog.tenant.id, values, csrfToken);
        }
      }
      await onSaved();
    } catch (caught) {
      setError(caught instanceof HQApiError ? caught.message : 'The tenant change could not be saved.');
    } finally {
      setBusy(false);
    }
  };

  const title = dialog.mode === 'create'
    ? 'Create tenant workspace'
    : dialog.mode === 'edit'
      ? 'Edit tenant workspace'
      : dialog.mode === 'activate'
        ? 'Activate tenant workspace'
        : 'Suspend tenant workspace';

  return (
    <div className="business-dialog-backdrop" role="presentation">
      <section aria-labelledby="tenant-dialog-title" aria-modal="true" className="business-dialog tenant-dialog" role="dialog">
        <header>
          <div><p className="eyebrow">Platform administration</p><h2 id="tenant-dialog-title">{title}</h2></div>
          <button aria-label="Close dialog" onClick={onClose} type="button"><Icon name="close" /></button>
        </header>
        {tenant ? (
          <div className="business-dialog-record">
            <div><code>{tenant.slug}</code><strong>{tenant.name}</strong></div>
            <TenantStatus value={tenant.status} />
          </div>
        ) : null}
        <form onSubmit={(event) => void submit(event)}>
          {dialog.mode === 'activate' ? (
            <p className="business-dialog-confirm"><Icon name="shield" /> Activation restores normal access to this workspace and its governed business workflows.</p>
          ) : dialog.mode === 'suspend' ? (
            <>
              <p className="business-dialog-confirm"><Icon name="alert" /> Suspension blocks normal workspace operation without deleting business history.</p>
              <label className="business-field">
                <span>Suspension reason <b>Required</b></span>
                <textarea autoFocus onChange={(event) => setReason(event.target.value)} required value={reason} />
              </label>
            </>
          ) : (
            <>
              <label className="business-field">
                <span>Workspace name <b>Required</b></span>
                <input autoFocus onChange={(event) => setField('name', event.target.value)} required value={form.name} />
              </label>
              <label className="business-field">
                <span>Workspace slug <b>Required</b></span>
                <input onChange={(event) => setField('slug', slugify(event.target.value))} pattern="[a-z0-9-]+" required value={form.slug} />
              </label>
              <div className="tenant-form-grid">
                <label className="business-field">
                  <span>Country</span>
                  <input maxLength={2} onChange={(event) => setField('countryCode', event.target.value.toUpperCase())} value={form.countryCode} />
                </label>
                <label className="business-field">
                  <span>Time zone</span>
                  <input onChange={(event) => setField('timeZone', event.target.value)} value={form.timeZone} />
                </label>
              </div>
              <label className="business-field">
                <span>Support email</span>
                <input onChange={(event) => setField('supportEmail', event.target.value)} type="email" value={form.supportEmail} />
              </label>
            </>
          )}
          {error ? <p className="business-dialog-error"><Icon name="alert" /> {error}</p> : null}
          <footer>
            <button className="secondary-button" disabled={busy} onClick={onClose} type="button">Cancel</button>
            <button className="primary-button" disabled={busy} type="submit">
              {busy ? 'Saving…' : dialog.mode === 'suspend' ? 'Suspend workspace' : dialog.mode === 'activate' ? 'Activate workspace' : 'Save workspace'}
            </button>
          </footer>
        </form>
      </section>
    </div>
  );
}

function TenantMetric({
  detail,
  icon,
  label,
  value,
}: {
  readonly detail: string;
  readonly icon: 'building' | 'shield' | 'store' | 'users';
  readonly label: string;
  readonly value: number;
}) {
  return (
    <article className="summary-card">
      <span className="summary-icon"><Icon name={icon} /></span>
      <div><p>{label}</p><strong>{value.toLocaleString()}</strong><small>{detail}</small></div>
    </article>
  );
}

function TenantStatus({ value }: { readonly value: string }) {
  return (
    <span className={`status-badge status-${value === 'ACTIVE' ? 'active' : 'suspended'}`}>
      <i /> {value === 'ACTIVE' ? 'Active' : 'Suspended'}
    </span>
  );
}

function slugify(value: string): string {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}
