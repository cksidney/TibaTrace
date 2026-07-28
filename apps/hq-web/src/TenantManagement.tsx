import { useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';

import {
  activatePharmacy,
  beginPharmacyOnboarding,
  HQApiError,
  loadPharmacies,
  loadPharmacyLifecycle,
  registerPharmacy,
  reinstatePharmacy,
  suspendPharmacy,
  terminatePharmacy,
  updatePharmacyProfile,
} from './api.js';
import type {
  HQOverview,
  Pharmacy,
  PharmacyLifecycleEvent,
  PharmacyStatus,
} from './api.js';
import { Icon } from './icons.js';

interface TenantManagementProps {
  readonly csrfToken: string;
  readonly onChanged: () => Promise<void>;
  readonly overview: HQOverview;
}

/**
 * Every dialog this screen can open.
 *
 * The lifecycle ones mirror the server's transitions exactly. Which of them are
 * offered for a given pharmacy is decided by `available_transitions` on the row
 * rather than by rules restated here -- a button that offers a move the service
 * will refuse is worse than no button.
 */
type Dialog =
  | { readonly mode: 'register' }
  | { readonly mode: 'onboard'; readonly pharmacy: Pharmacy }
  | { readonly mode: 'activate'; readonly pharmacy: Pharmacy }
  | { readonly mode: 'suspend'; readonly pharmacy: Pharmacy }
  | { readonly mode: 'reinstate'; readonly pharmacy: Pharmacy }
  | { readonly mode: 'terminate'; readonly pharmacy: Pharmacy }
  | { readonly mode: 'licence'; readonly pharmacy: Pharmacy }
  | { readonly mode: 'history'; readonly pharmacy: Pharmacy }
  | null;

const STATUS_FILTERS: readonly { readonly value: string; readonly label: string }[] = [
  { value: 'ALL', label: 'All states' },
  { value: 'PROSPECT', label: 'Prospect' },
  { value: 'ONBOARDING', label: 'Onboarding' },
  { value: 'ACTIVE', label: 'Active' },
  { value: 'SUSPENDED', label: 'Suspended' },
  { value: 'TERMINATED', label: 'Terminated' },
];

/** How near an expiry has to be before the screen says so. */
const LICENCE_WARNING_DAYS = 60;

export function TenantManagement({ csrfToken, onChanged, overview }: TenantManagementProps) {
  const [pharmacies, setPharmacies] = useState<readonly Pharmacy[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('ALL');
  const [dialog, setDialog] = useState<Dialog>(null);
  const canManage = overview.is_platform_overview;

  const reload = async (signal?: AbortSignal) => {
    setFailed(false);
    try {
      setPharmacies(await loadPharmacies(signal));
    } catch {
      if (!signal?.aborted) setFailed(true);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    void reload(controller.signal);
    return () => controller.abort();
  }, []);

  const visible = useMemo(() => {
    const rows = pharmacies ?? [];
    const needle = query.trim().toLowerCase();
    return rows.filter((row) => {
      if (status !== 'ALL' && row.status !== status) return false;
      if (!needle) return true;
      return (
        row.name.toLowerCase().includes(needle) ||
        row.slug.toLowerCase().includes(needle) ||
        (row.profile?.legal_name ?? '').toLowerCase().includes(needle)
      );
    });
  }, [pharmacies, query, status]);

  /** Pharmacies trading on a licence that lapses soon, or has already lapsed. */
  const licenceAttention = useMemo(
    () =>
      (pharmacies ?? []).filter((row) => {
        if (row.status !== 'ACTIVE') return false;
        const days = row.profile?.days_until_licence_expiry;
        return days === null || days === undefined || days <= LICENCE_WARNING_DAYS;
      }),
    [pharmacies],
  );

  return (
    <>
      {licenceAttention.length ? (
        <div className="inline-alert" role="status">
          <Icon name="alert" />
          {licenceAttention.length === 1
            ? '1 trading pharmacy has a premises licence that has expired or expires within 60 days.'
            : `${licenceAttention.length} trading pharmacies have a premises licence that has expired or expires within 60 days.`}
        </div>
      ) : null}

      <article className="panel table-panel">
        <div className="table-toolbar">
          <div>
            <p className="eyebrow">Pharmacy network</p>
            <h2>Registered pharmacies</h2>
          </div>
          {canManage ? (
            <button className="primary-button" onClick={() => setDialog({ mode: 'register' })} type="button">
              <Icon name="plus" /> Register pharmacy
            </button>
          ) : null}
        </div>

        <div className="table-filters">
          <label className="search-field">
            <span className="sr-only">Search pharmacies</span>
            <Icon name="search" />
            <input
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search by name, slug or legal entity"
              value={query}
            />
          </label>
          <label>
            <span className="sr-only">Filter by lifecycle state</span>
            <select onChange={(event) => setStatus(event.target.value)} value={status}>
              {STATUS_FILTERS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
        </div>

        {failed ? (
          <div className="inline-alert" role="alert"><Icon name="alert" /> Pharmacy data could not be loaded.</div>
        ) : pharmacies === null ? (
          <p className="muted-cell">Loading pharmacies…</p>
        ) : visible.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Pharmacy</th>
                  <th>State</th>
                  <th>Premises licence</th>
                  <th>Superintendent</th>
                  <th>Branches</th>
                  <th>Locale</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((pharmacy) => (
                  <tr key={pharmacy.id}>
                    <td>
                      <strong>{pharmacy.name}</strong>
                      <small className="tenant-slug">{pharmacy.profile?.legal_name || pharmacy.slug}</small>
                    </td>
                    <td><PharmacyState value={pharmacy.status} /></td>
                    <td><LicenceCell pharmacy={pharmacy} /></td>
                    <td>
                      {pharmacy.profile?.superintendent_name
                        ? <small>{pharmacy.profile.superintendent_name}</small>
                        : <span className="muted-cell">Not named</span>}
                    </td>
                    <td>{pharmacy.branch_count}</td>
                    <td><small>{pharmacy.country_code} · {pharmacy.time_zone}</small></td>
                    <td>
                      <RowActions
                        canManage={canManage}
                        onOpen={setDialog}
                        pharmacy={pharmacy}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="tenant-empty">
            <Icon name="network" />
            <strong>No pharmacies match</strong>
            <span>Adjust the search or state filter.</span>
          </div>
        )}
      </article>

      <section className="tenant-control-grid">
        <article className="panel tenant-control-card">
          <span className="tenant-control-icon"><Icon name="shield" /></span>
          <div>
            <p>Lifecycle control</p>
            <h2>A suspended pharmacy cannot trade</h2>
            <span>Suspension refuses that pharmacy&rsquo;s requests outright rather than only marking a record. Nothing is deleted: branches, users, transactions and compliance evidence are retained.</span>
          </div>
        </article>
        <article className="panel tenant-control-card">
          <span className="tenant-control-icon"><Icon name="database" /></span>
          <div>
            <p>Regulatory gate</p>
            <h2>Trading requires a current premises licence</h2>
            <span>A pharmacy cannot be activated or reinstated without an unexpired PPB premises licence and a named superintendent pharmacist.</span>
          </div>
        </article>
      </section>

      {dialog ? (
        <PharmacyDialog
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

/** Only the transitions the server says are available for this row. */
function RowActions({
  canManage,
  onOpen,
  pharmacy,
}: {
  readonly canManage: boolean;
  readonly onOpen: (dialog: Dialog) => void;
  readonly pharmacy: Pharmacy;
}) {
  const can = (state: PharmacyStatus) => pharmacy.available_transitions.includes(state);
  if (!canManage) {
    return (
      <div className="tenant-row-actions">
        <button onClick={() => onOpen({ mode: 'history', pharmacy })} type="button">History</button>
      </div>
    );
  }
  return (
    <div className="tenant-row-actions">
      <button onClick={() => onOpen({ mode: 'history', pharmacy })} type="button">History</button>
      <button onClick={() => onOpen({ mode: 'licence', pharmacy })} type="button">Licence</button>
      {can('ONBOARDING') ? (
        <button onClick={() => onOpen({ mode: 'onboard', pharmacy })} type="button">Provision</button>
      ) : null}
      {can('ACTIVE') && pharmacy.status === 'ONBOARDING' ? (
        <button onClick={() => onOpen({ mode: 'activate', pharmacy })} type="button">Activate</button>
      ) : null}
      {can('ACTIVE') && pharmacy.status === 'SUSPENDED' ? (
        <button onClick={() => onOpen({ mode: 'reinstate', pharmacy })} type="button">Reinstate</button>
      ) : null}
      {can('SUSPENDED') ? (
        <button className="danger-link" onClick={() => onOpen({ mode: 'suspend', pharmacy })} type="button">Suspend</button>
      ) : null}
      {can('TERMINATED') ? (
        <button className="danger-link" onClick={() => onOpen({ mode: 'terminate', pharmacy })} type="button">Terminate</button>
      ) : null}
    </div>
  );
}

function LicenceCell({ pharmacy }: { readonly pharmacy: Pharmacy }) {
  const profile = pharmacy.profile;
  if (!profile?.ppb_premises_licence_number) {
    return <span className="licence-flag licence-missing">Not recorded</span>;
  }
  const days = profile.days_until_licence_expiry;
  const tone = !profile.licence_is_current
    ? 'licence-expired'
    : days !== null && days <= LICENCE_WARNING_DAYS
      ? 'licence-expiring'
      : 'licence-current';
  const label = !profile.licence_is_current
    ? 'Expired'
    : days !== null && days <= LICENCE_WARNING_DAYS
      ? `${days} days left`
      : 'Current';
  return (
    <>
      <code>{profile.ppb_premises_licence_number}</code>
      <br />
      <span className={`licence-flag ${tone}`}>{label}</span>
      {/* Recorded and confirmed are different claims. Until the PPB
          integration exists every licence is hand-entered, and the screen says
          so rather than implying the registrar stands behind it. */}
      {!profile.licence_is_registrar_confirmed ? (
        <>
          <br />
          <span className="licence-provenance">Entered by hand</span>
        </>
      ) : null}
    </>
  );
}

function PharmacyState({ value }: { readonly value: PharmacyStatus }) {
  const tone: Record<PharmacyStatus, string> = {
    PROSPECT: 'state-prospect',
    ONBOARDING: 'state-onboarding',
    ACTIVE: 'state-active',
    SUSPENDED: 'state-suspended',
    TERMINATED: 'state-terminated',
  };
  const label = value.charAt(0) + value.slice(1).toLowerCase();
  return <span className={`pharmacy-state ${tone[value]}`}>{label}</span>;
}

const REASON_REQUIRED: ReadonlySet<string> = new Set(['suspend', 'terminate']);

function PharmacyDialog({
  csrfToken,
  dialog,
  onClose,
  onSaved,
}: {
  readonly csrfToken: string;
  readonly dialog: Exclude<Dialog, null>;
  readonly onClose: () => void;
  readonly onSaved: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [fields, setFields] = useState<Record<string, string>>(() => initialFields(dialog));
  const [history, setHistory] = useState<readonly PharmacyLifecycleEvent[] | null>(null);

  useEffect(() => {
    if (dialog.mode !== 'history') return;
    const controller = new AbortController();
    loadPharmacyLifecycle(dialog.pharmacy.id, controller.signal)
      .then(setHistory)
      .catch(() => { if (!controller.signal.aborted) setHistory([]); });
    return () => controller.abort();
  }, [dialog]);

  const set = (key: string) => (event: { target: { value: string } }) =>
    setFields((prev) => ({ ...prev, [key]: event.target.value }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (REASON_REQUIRED.has(dialog.mode) && !fields.reason?.trim()) {
      setError('A reason is required. It is recorded against the pharmacy permanently.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await runDialog(dialog, fields, csrfToken);
      await onSaved();
    } catch (cause) {
      // The service's own words: an operator needs to know it was the licence
      // that was missing, not merely that something failed.
      setError(
        cause instanceof HQApiError
          ? describe(cause)
          : cause instanceof Error ? cause.message : 'The action could not be completed.',
      );
      setBusy(false);
    }
  };

  if (dialog.mode === 'history') {
    return (
      <Modal onClose={onClose} title={`Lifecycle — ${dialog.pharmacy.name}`}>
        {history === null ? (
          <p className="muted-cell">Loading history…</p>
        ) : history.length ? (
          <div className="table-scroll">
            <table>
              <thead><tr><th>When</th><th>Change</th><th>By</th><th>Reason</th></tr></thead>
              <tbody>
                {history.map((event) => (
                  <tr key={event.id}>
                    <td><small>{new Date(event.occurred_at).toLocaleString('en-GB')}</small></td>
                    <td>
                      <small>{event.from_state || 'new'} → </small>
                      <strong>{event.to_state}</strong>
                    </td>
                    {/* Null actor means the platform acted, not that nobody is
                        accountable. */}
                    <td><small>{event.actor_name ?? 'Platform'}</small></td>
                    <td><small>{event.reason || '—'}</small></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="muted-cell">No transitions recorded.</p>}
        <form onSubmit={(event) => { event.preventDefault(); onClose(); }}>
          <footer>
            <button onClick={onClose} type="button">Close</button>
          </footer>
        </form>
      </Modal>
    );
  }

  return (
    <Modal onClose={onClose} title={titleFor(dialog)}>
      <form onSubmit={submit}>
        {error ? <p className="auth-error" role="alert"><Icon name="alert" /> {error}</p> : null}
        {describeIntent(dialog) ? <p className="panel-note">{describeIntent(dialog)}</p> : null}
        {fieldsFor(dialog).map((field) => (
          <label className="business-field" key={field.name}>
            <span>
              {field.label}
              {REASON_REQUIRED.has(dialog.mode) && field.name === 'reason' ? <b>Required</b> : null}
            </span>
            {field.multiline ? (
              <textarea onChange={set(field.name)} rows={3} value={fields[field.name] ?? ''} />
            ) : (
              <input
                onChange={set(field.name)}
                placeholder={field.placeholder}
                type={field.type ?? 'text'}
                value={fields[field.name] ?? ''}
              />
            )}
          </label>
        ))}
        <footer>
          <button disabled={busy} onClick={onClose} type="button">Cancel</button>
          <button className="primary-button" disabled={busy} type="submit">
            {busy ? 'Working…' : submitLabel(dialog)}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function Modal({
  children,
  onClose,
  title,
}: {
  readonly children: React.ReactNode;
  readonly onClose: () => void;
  readonly title: string;
}) {
  return (
    <div className="business-dialog-backdrop" role="presentation">
      <div aria-modal="true" className="business-dialog" role="dialog">
        <header>
          <h2>{title}</h2>
          <button aria-label="Close" onClick={onClose} type="button"><Icon name="close" /></button>
        </header>
        {children}
      </div>
    </div>
  );
}

interface Field {
  readonly label: string;
  readonly name: string;
  readonly multiline?: boolean;
  readonly placeholder?: string;
  readonly type?: string;
}

function initialFields(dialog: Exclude<Dialog, null>): Record<string, string> {
  if (dialog.mode === 'licence') {
    const profile = dialog.pharmacy.profile;
    return {
      ppb_premises_licence_number: profile?.ppb_premises_licence_number ?? '',
      ppb_licence_expiry: profile?.ppb_licence_expiry ?? '',
      superintendent_name: profile?.superintendent_name ?? '',
      superintendent_ppb_number: profile?.superintendent_ppb_number ?? '',
    };
  }
  if (dialog.mode === 'register') return { country_code: 'KE', time_zone: 'Africa/Nairobi' };
  return {};
}

function fieldsFor(dialog: Exclude<Dialog, null>): readonly Field[] {
  switch (dialog.mode) {
    case 'register':
      return [
        { label: 'Trading name', name: 'name', placeholder: 'Westlands Pharmacy' },
        { label: 'Slug', name: 'slug', placeholder: 'westlands-pharmacy' },
        { label: 'Registered legal entity', name: 'legal_name', placeholder: 'Westlands Pharmaceuticals Ltd' },
        { label: 'Business registration number', name: 'business_registration_number' },
        { label: 'PPB premises licence number', name: 'ppb_premises_licence_number' },
        { label: 'Licence expiry', name: 'ppb_licence_expiry', type: 'date' },
        { label: 'Superintendent pharmacist', name: 'superintendent_name' },
        { label: 'Superintendent PPB number', name: 'superintendent_ppb_number' },
        { label: 'Primary contact email', name: 'primary_contact_email', type: 'email' },
      ];
    case 'onboard':
      return [
        { label: 'Organisation name', name: 'organization_name' },
        { label: 'Organisation code', name: 'organization_code', placeholder: 'WLG' },
        { label: 'First branch name', name: 'branch_name' },
        { label: 'First branch code', name: 'branch_code', placeholder: 'WL-MAIN' },
      ];
    case 'licence':
      return [
        { label: 'PPB premises licence number', name: 'ppb_premises_licence_number' },
        { label: 'Licence expiry', name: 'ppb_licence_expiry', type: 'date' },
        { label: 'Superintendent pharmacist', name: 'superintendent_name' },
        { label: 'Superintendent PPB number', name: 'superintendent_ppb_number' },
      ];
    default:
      return [{ label: 'Reason', name: 'reason', multiline: true }];
  }
}

function titleFor(dialog: Exclude<Dialog, null>): string {
  const name = dialog.mode === 'register' ? '' : ` — ${dialog.pharmacy.name}`;
  const titles: Record<string, string> = {
    register: 'Register a pharmacy',
    onboard: 'Provision pharmacy',
    activate: 'Activate for trading',
    suspend: 'Suspend pharmacy',
    reinstate: 'Reinstate pharmacy',
    terminate: 'Terminate pharmacy',
    licence: 'Premises licence',
  };
  return `${titles[dialog.mode] ?? 'Pharmacy'}${name}`;
}

function describeIntent(dialog: Exclude<Dialog, null>): string {
  switch (dialog.mode) {
    case 'register':
      return 'Registers the pharmacy as a prospect. It cannot trade until it is provisioned and its premises licence is recorded.';
    case 'onboard':
      return 'Creates the organisation and first branch. A pharmacy cannot dispense without at least one branch.';
    case 'activate':
      return 'Checks the premises licence and superintendent before the pharmacy may trade. Refused if either is missing or expired.';
    case 'suspend':
      return 'The pharmacy stops immediately: its requests are refused until reinstated. The reason is recorded permanently.';
    case 'reinstate':
      return 'The premises licence is re-checked. A pharmacy whose licence has lapsed cannot be reinstated until it is renewed.';
    case 'terminate':
      return 'Final. A terminated pharmacy cannot be reinstated — bringing it back means registering it again, so this record keeps its history.';
    default:
      return '';
  }
}

function submitLabel(dialog: Exclude<Dialog, null>): string {
  const labels: Record<string, string> = {
    register: 'Register',
    onboard: 'Provision',
    activate: 'Activate',
    suspend: 'Suspend',
    reinstate: 'Reinstate',
    terminate: 'Terminate',
    licence: 'Save licence',
  };
  return labels[dialog.mode] ?? 'Save';
}

async function runDialog(
  dialog: Exclude<Dialog, null>,
  fields: Record<string, string>,
  csrfToken: string,
): Promise<unknown> {
  const reason = fields.reason ?? '';
  switch (dialog.mode) {
    case 'register':
      return registerPharmacy(
        {
          name: fields.name ?? '',
          slug: fields.slug ?? '',
          legal_name: fields.legal_name ?? '',
          country_code: fields.country_code || 'KE',
          time_zone: fields.time_zone || 'Africa/Nairobi',
          business_registration_number: fields.business_registration_number ?? '',
          ppb_premises_licence_number: fields.ppb_premises_licence_number ?? '',
          // An empty date field is no licence, not an invalid one.
          ppb_licence_expiry: fields.ppb_licence_expiry || null,
          superintendent_name: fields.superintendent_name ?? '',
          superintendent_ppb_number: fields.superintendent_ppb_number ?? '',
          primary_contact_email: fields.primary_contact_email ?? '',
        },
        csrfToken,
      );
    case 'onboard':
      return beginPharmacyOnboarding(
        dialog.pharmacy.id,
        {
          organization_name: fields.organization_name ?? '',
          organization_code: fields.organization_code ?? '',
          branch_name: fields.branch_name ?? '',
          branch_code: fields.branch_code ?? '',
        },
        csrfToken,
      );
    case 'activate':
      return activatePharmacy(dialog.pharmacy.id, reason, csrfToken);
    case 'suspend':
      return suspendPharmacy(dialog.pharmacy.id, reason, csrfToken);
    case 'reinstate':
      return reinstatePharmacy(dialog.pharmacy.id, reason, csrfToken);
    case 'terminate':
      return terminatePharmacy(dialog.pharmacy.id, reason, csrfToken);
    case 'licence':
      return updatePharmacyProfile(
        dialog.pharmacy.id,
        {
          ppb_premises_licence_number: fields.ppb_premises_licence_number ?? '',
          ppb_licence_expiry: fields.ppb_licence_expiry || null,
          superintendent_name: fields.superintendent_name ?? '',
          superintendent_ppb_number: fields.superintendent_ppb_number ?? '',
        },
        csrfToken,
      );
    default:
      throw new Error('Unknown action.');
  }
}

/** Turn a field-keyed error body into something an operator can act on. */
function describe(error: HQApiError): string {
  const detail = (error as { payload?: unknown }).payload;
  if (detail && typeof detail === 'object') {
    const parts = Object.entries(detail as Record<string, unknown>).map(([key, value]) => {
      const text = Array.isArray(value) ? value.join(' ') : String(value);
      return key === 'detail' ? text : `${key}: ${text}`;
    });
    if (parts.length) return parts.join(' ');
  }
  return error.message;
}
