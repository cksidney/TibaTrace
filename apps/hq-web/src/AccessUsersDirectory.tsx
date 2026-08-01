import { FormEvent, useEffect, useMemo, useState } from 'react';

import {
  createTenantUser,
  loadUserDirectory,
  resetUserPassword,
  setUserAccountStatus,
  setUserRoles,
  type RoleDetail,
  type UserDetail,
  type UserDirectoryPage,
} from './api.js';

type UserCategoryFilter = 'ALL' | 'ACTIVE' | 'SUSPENDED' | 'DISABLED' | 'ADMIN' | `ROLE:${string}`;

interface AccessUsersDirectoryProps {
  readonly csrfToken: string;
  readonly roles: readonly RoleDetail[] | null;
  readonly tenantId: string;
  readonly tenantName: string;
}

const EMPTY_CREATE_FORM = {
  username: '',
  email: '',
  first_name: '',
  last_name: '',
  professional_staff_id: '',
  role_ids: [] as string[],
};

function statusBadge(user: UserDetail) {
  const status = (user.account_status || (user.is_active ? 'ACTIVE' : 'DISABLED')).toUpperCase();
  if (status === 'ACTIVE') {
    return <span className="status-badge status-active"><i /> Active</span>;
  }
  if (status === 'SUSPENDED') {
    return <span className="status-badge status-warning"><i /> Suspended</span>;
  }
  return <span className="status-badge status-suspended"><i /> Disabled</span>;
}

function displayName(user: UserDetail) {
  const name = `${user.first_name} ${user.last_name}`.trim();
  return name || user.username;
}

export function AccessUsersDirectory({ csrfToken, roles, tenantId, tenantName }: AccessUsersDirectoryProps) {
  const [search, setSearch] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');
  const [category, setCategory] = useState<UserCategoryFilter>('ALL');
  const [page, setPage] = useState(1);
  const [directory, setDirectory] = useState<UserDirectoryPage | null>(null);
  const [failed, setFailed] = useState(false);
  const [busyId, setBusyId] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState(EMPTY_CREATE_FORM);
  const [createdUser, setCreatedUser] = useState<UserDetail | null>(null);
  const [credentialCopied, setCredentialCopied] = useState(false);
  const [roleEditorUserId, setRoleEditorUserId] = useState('');
  const [roleDraft, setRoleDraft] = useState<string[]>([]);

  useEffect(() => {
    setPage(1);
  }, [tenantId, category, appliedSearch]);

  useEffect(() => {
    if (!showCreate) return undefined;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && busyId !== 'create') {
        setShowCreate(false);
        setCreatedUser(null);
        setCredentialCopied(false);
        setError('');
        setCreateForm(EMPTY_CREATE_FORM);
      }
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [busyId, showCreate]);

  useEffect(() => {
    if (!tenantId) return;
    const controller = new AbortController();
    setFailed(false);
    setDirectory(null);
    loadUserDirectory(
      tenantId,
      {
        search: appliedSearch,
        category: category === 'ALL' ? '' : category,
        page,
        pageSize: 10,
      },
      controller.signal,
    )
      .then(setDirectory)
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [tenantId, appliedSearch, category, page]);

  const pageCount = useMemo(() => {
    if (!directory) return 1;
    return Math.max(1, Math.ceil(directory.count / 10));
  }, [directory]);

  const refresh = async () => {
    const next = await loadUserDirectory(tenantId, {
      search: appliedSearch,
      category: category === 'ALL' ? '' : category,
      page,
      pageSize: 10,
    });
    setDirectory(next);
  };

  const runAction = async (userId: string, work: () => Promise<UserDetail>, success: string) => {
    setBusyId(userId);
    setError('');
    setNotice('');
    try {
      const result = await work();
      if (result.temporary_password) {
        setNotice(`${success} Temporary password: ${result.temporary_password}`);
      } else {
        setNotice(success);
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'User action failed.');
    } finally {
      setBusyId('');
    }
  };

  const onCreate = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    setNotice('');

    const usernameTrimmed = createForm.username.trim();
    const emailTrimmed = createForm.email.trim();
    const firstNameTrimmed = createForm.first_name.trim();
    const lastNameTrimmed = createForm.last_name.trim();

    if (usernameTrimmed.length < 3) {
      setError('Username must be at least 3 characters long.');
      return;
    }
    if (emailTrimmed && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailTrimmed)) {
      setError('Please enter a valid email address.');
      return;
    }
    if (!firstNameTrimmed || !lastNameTrimmed) {
      setError('First and last name are required for an accountable staff profile.');
      return;
    }
    if (createForm.role_ids.length === 0) {
      setError('Please assign at least one role to the new user.');
      return;
    }

    setBusyId('create');
    try {
      const created = await createTenantUser(tenantId, csrfToken, {
        username: usernameTrimmed,
        email: emailTrimmed,
        first_name: firstNameTrimmed,
        last_name: lastNameTrimmed,
        professional_staff_id: createForm.professional_staff_id.trim(),
        role_ids: createForm.role_ids,
        must_change_password: true,
      });
      setCreatedUser(created);
      setCredentialCopied(false);
      setNotice(`Created ${created.username} with ${created.assigned_roles.length} assigned role${created.assigned_roles.length === 1 ? '' : 's'}.`);
      setCreateForm(EMPTY_CREATE_FORM);
      setPage(1);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create user.');
    } finally {
      setBusyId('');
    }
  };

  const closeCreate = () => {
    if (busyId === 'create') return;
    setShowCreate(false);
    setCreatedUser(null);
    setCredentialCopied(false);
    setCreateForm(EMPTY_CREATE_FORM);
    setError('');
  };

  const copyTemporaryPassword = async () => {
    if (!createdUser?.temporary_password) return;
    try {
      await navigator.clipboard.writeText(createdUser.temporary_password);
      setCredentialCopied(true);
      setError('');
    } catch {
      setCredentialCopied(false);
      setError('Clipboard access was blocked. Select and copy the temporary password manually.');
    }
  };

  const openRoleEditor = (user: UserDetail) => {
    setRoleEditorUserId(user.id);
    setRoleDraft(user.assigned_roles.map((role) => role.id));
  };

  const saveRoles = async (userId: string) => {
    await runAction(
      userId,
      () => setUserRoles(tenantId, userId, roleDraft, csrfToken),
      'Role assignments updated.',
    );
    setRoleEditorUserId('');
  };

  return (
    <article className="panel access-users-panel">
      <header className="panel-header access-users-header">
        <div>
          <p className="eyebrow">Tenant directory</p>
          <h2>Users & role assignment</h2>
          <p className="muted-cell">Create accounts for this pharmacy and grant them one or more roles.</p>
        </div>
        <button
          className="primary-button"
          disabled={!roles?.length}
          onClick={() => {
            setError('');
            setNotice('');
            setCreatedUser(null);
            setCredentialCopied(false);
            setShowCreate(true);
          }}
          type="button"
        >
          Add user
        </button>
      </header>

      <div className="access-users-toolbar">
        <form
          className="access-users-search"
          onSubmit={(event) => {
            event.preventDefault();
            setAppliedSearch(search.trim());
          }}
        >
          <label>
            <span>Search users</span>
            <input
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Username, name, or email"
              value={search}
            />
          </label>
          <button className="secondary-button" type="submit">Search</button>
        </form>
        <label>
          <span>Category</span>
          <select
            onChange={(event) => setCategory(event.target.value as UserCategoryFilter)}
            value={category}
          >
            <option value="ALL">All profiles</option>
            <option value="ACTIVE">Active</option>
            <option value="SUSPENDED">Suspended</option>
            <option value="DISABLED">Disabled</option>
            <option value="ADMIN">Admins</option>
            {(roles ?? []).map((role) => (
              <option key={role.id} value={`ROLE:${role.code}`}>
                Role · {role.code}
              </option>
            ))}
          </select>
        </label>
      </div>

      {showCreate ? (
        <div className="business-dialog-backdrop" role="presentation">
          <section aria-describedby={createdUser ? undefined : 'add-user-description'} aria-labelledby="add-user-title" aria-modal="true" className="business-dialog access-user-dialog" role="dialog">
            <header>
              <div>
                <p className="eyebrow">Account provisioning</p>
                <h2 id="add-user-title">Add user to {tenantName}</h2>
              </div>
              <button aria-label="Close Add User dialog" disabled={busyId === 'create'} onClick={closeCreate} type="button">
                <span aria-hidden="true">×</span>
              </button>
            </header>

            {createdUser ? (
              <div className="access-credential-handoff">
                <div className="access-credential-success" aria-hidden="true">✓</div>
                <div>
                  <p className="eyebrow">Account created</p>
                  <h3>{displayName(createdUser)}</h3>
                  <p>
                    <strong>{createdUser.username}</strong> is active and must change this password at first sign-in.
                  </p>
                </div>
                {createdUser.temporary_password ? (
                  <div className="access-temporary-password">
                    <span>One-time temporary password</span>
                    <code>{createdUser.temporary_password}</code>
                    <button className="secondary-button" onClick={() => void copyTemporaryPassword()} type="button">
                      {credentialCopied ? 'Copied' : 'Copy password'}
                    </button>
                    <small>Copy it now. For security, it will not be shown again after this dialog closes.</small>
                  </div>
                ) : null}
                <dl className="access-provisioning-summary">
                  <div><dt>Tenant</dt><dd>{tenantName}</dd></div>
                  <div><dt>Roles</dt><dd>{createdUser.assigned_roles.map((role) => role.code).join(', ')}</dd></div>
                  <div><dt>Status</dt><dd>Active · password change required</dd></div>
                </dl>
                {error ? <p className="business-dialog-error" role="alert">{error}</p> : null}
                <footer className="access-user-dialog-footer">
                  <button className="primary-button" onClick={closeCreate} type="button">Done</button>
                </footer>
              </div>
            ) : (
              <form className="access-user-form" onSubmit={onCreate}>
                <p className="access-user-dialog-intro" id="add-user-description">
                  Create an accountable staff identity, then assign the least-privilege roles needed for their work.
                </p>
                <div className="access-user-form-grid">
                  <label>
                    <span>Username <b>Required</b></span>
                    <input
                      autoFocus
                      autoComplete="off"
                      minLength={3}
                      required
                      onChange={(event) => setCreateForm((current) => ({ ...current, username: event.target.value }))}
                      placeholder="e.g. jane.wanjiku"
                      value={createForm.username}
                    />
                    <small>At least 3 characters; unique across TibaTrace.</small>
                  </label>
                  <label>
                    <span>Email</span>
                    <input
                      autoComplete="email"
                      onChange={(event) => setCreateForm((current) => ({ ...current, email: event.target.value }))}
                      placeholder="name@pharmacy.co.ke"
                      type="email"
                      value={createForm.email}
                    />
                    <small>Used for identity recovery and account notices.</small>
                  </label>
                  <label>
                    <span>First name <b>Required</b></span>
                    <input
                      autoComplete="given-name"
                      required
                      onChange={(event) => setCreateForm((current) => ({ ...current, first_name: event.target.value }))}
                      value={createForm.first_name}
                    />
                  </label>
                  <label>
                    <span>Last name <b>Required</b></span>
                    <input
                      autoComplete="family-name"
                      required
                      onChange={(event) => setCreateForm((current) => ({ ...current, last_name: event.target.value }))}
                      value={createForm.last_name}
                    />
                  </label>
                  <label className="access-professional-id-field">
                    <span>Professional staff ID</span>
                    <input
                      onChange={(event) => setCreateForm((current) => ({ ...current, professional_staff_id: event.target.value }))}
                      placeholder="Optional licence or employee identifier"
                      value={createForm.professional_staff_id}
                    />
                    <small>Recommended for pharmacists and regulated clinical staff.</small>
                  </label>
                </div>
                <fieldset className="access-role-picker">
                  <legend>Assign roles <b>Required</b></legend>
                  <p>Select at least one role. Permissions are inherited from the role and can be changed later.</p>
                  <div className="access-role-options">
                    {(roles ?? []).map((role) => {
                      const checked = createForm.role_ids.includes(role.id);
                      return (
                        <label className={`access-role-option ${checked ? 'is-selected' : ''}`} key={role.id}>
                          <input
                            checked={checked}
                            onChange={() => {
                              setCreateForm((current) => ({
                                ...current,
                                role_ids: checked
                                  ? current.role_ids.filter((id) => id !== role.id)
                                  : [...current.role_ids, role.id],
                              }));
                            }}
                            type="checkbox"
                          />
                          <span><strong>{role.name}</strong><code>{role.code}</code></span>
                          <small>{role.capabilities.length} permission{role.capabilities.length === 1 ? '' : 's'}</small>
                        </label>
                      );
                    })}
                  </div>
                </fieldset>
                <div className="access-account-policy">
                  <strong>Secure first sign-in</strong>
                  <span>A strong temporary password will be generated. The user must replace it immediately.</span>
                </div>
                {error ? <p className="business-dialog-error" role="alert">{error}</p> : null}
                <footer>
                  <span>{createForm.role_ids.length} role{createForm.role_ids.length === 1 ? '' : 's'} selected</span>
                  <div>
                    <button className="secondary-button" disabled={busyId === 'create'} onClick={closeCreate} type="button">Cancel</button>
                    <button className="primary-button" disabled={busyId === 'create' || createForm.role_ids.length === 0} type="submit">
                      {busyId === 'create' ? 'Creating account…' : 'Create user'}
                    </button>
                  </div>
                </footer>
              </form>
            )}
          </section>
        </div>
      ) : null}

      {notice ? <p className="inline-success" role="status">{notice}</p> : null}
      {error && !showCreate ? <p className="inline-alert" role="alert">{error}</p> : null}
      {failed ? (
        <p className="inline-alert" role="status">User directory could not be loaded for this tenant.</p>
      ) : null}

      {!directory && !failed ? (
        <p className="muted-cell">Loading user directory…</p>
      ) : directory && directory.results.length === 0 ? (
        <p className="muted-cell">No users match this search and category.</p>
      ) : directory ? (
        <>
          <div className="table-scroll">
            <table className="access-users-table">
              <thead>
                <tr>
                  <th scope="col">User</th>
                  <th scope="col">Status</th>
                  <th scope="col">Category</th>
                  <th scope="col">Roles</th>
                  <th scope="col">Last login</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {directory.results.map((user) => (
                  <tr key={user.id}>
                    <td>
                      <strong>{user.username}</strong>
                      <small className="muted-cell">{displayName(user)}</small>
                      {user.email ? <small className="access-email">{user.email}</small> : null}
                    </td>
                    <td>{statusBadge(user)}</td>
                    <td><span className="muted-cell">{user.category}</span></td>
                    <td>
                      {roleEditorUserId === user.id ? (
                        <div className="access-role-editor">
                          <div className="capability-chips">
                            {(roles ?? []).map((role) => {
                              const checked = roleDraft.includes(role.id);
                              return (
                                <label className={`capability-chip ${checked ? 'is-selected' : ''}`} key={role.id}>
                                  <input
                                    checked={checked}
                                    onChange={() => {
                                      setRoleDraft((current) => (
                                        checked
                                          ? current.filter((id) => id !== role.id)
                                          : [...current, role.id]
                                      ));
                                    }}
                                    type="checkbox"
                                  />
                                  {role.code}
                                </label>
                              );
                            })}
                          </div>
                          <div className="access-action-row">
                            <button
                              className="secondary-button"
                              disabled={busyId === user.id}
                              onClick={() => void saveRoles(user.id)}
                              type="button"
                            >
                              Save roles
                            </button>
                            <button className="ghost-button" onClick={() => setRoleEditorUserId('')} type="button">
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : user.assigned_roles.length > 0 ? (
                        <div className="capability-chips">
                          {user.assigned_roles.map((role) => (
                            <span className="capability-chip capability-chip-role" key={role.id} title={role.name}>
                              {role.code}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="muted-cell">No assigned roles</span>
                      )}
                    </td>
                    <td>
                      {user.last_login
                        ? <small className="muted-cell">{new Date(user.last_login).toLocaleString()}</small>
                        : <span className="muted-cell">Never</span>}
                    </td>
                    <td>
                      <div className="access-action-row">
                        {user.account_status !== 'ACTIVE' ? (
                          <button
                            className="ghost-button"
                            disabled={busyId === user.id}
                            onClick={() => void runAction(
                              user.id,
                              () => setUserAccountStatus(tenantId, user.id, 'activate', csrfToken),
                              `${user.username} reactivated.`,
                            )}
                            type="button"
                          >
                            Enable
                          </button>
                        ) : null}
                        {user.account_status === 'ACTIVE' ? (
                          <button
                            className="ghost-button"
                            disabled={busyId === user.id}
                            onClick={() => void runAction(
                              user.id,
                              () => setUserAccountStatus(tenantId, user.id, 'suspend', csrfToken),
                              `${user.username} suspended.`,
                            )}
                            type="button"
                          >
                            Suspend
                          </button>
                        ) : null}
                        {user.account_status !== 'DISABLED' ? (
                          <button
                            className="ghost-button"
                            disabled={busyId === user.id}
                            onClick={() => void runAction(
                              user.id,
                              () => setUserAccountStatus(tenantId, user.id, 'disable', csrfToken),
                              `${user.username} disabled.`,
                            )}
                            type="button"
                          >
                            Disable
                          </button>
                        ) : null}
                        <button
                          className="ghost-button"
                          disabled={busyId === user.id}
                          onClick={() => void runAction(
                            user.id,
                            () => resetUserPassword(tenantId, user.id, csrfToken),
                            `Password reset for ${user.username}.`,
                          )}
                          type="button"
                        >
                          Reset password
                        </button>
                        <button
                          className="ghost-button"
                          disabled={busyId === user.id}
                          onClick={() => openRoleEditor(user)}
                          type="button"
                        >
                          Roles
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <footer className="access-users-pager">
            <span className="muted-cell">
              {directory.count} user{directory.count === 1 ? '' : 's'} · page {page} of {pageCount}
            </span>
            <div className="access-action-row">
              <button
                className="secondary-button"
                disabled={page <= 1}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
                type="button"
              >
                Previous
              </button>
              <button
                className="secondary-button"
                disabled={page >= pageCount}
                onClick={() => setPage((current) => current + 1)}
                type="button"
              >
                Next
              </button>
            </div>
          </footer>
        </>
      ) : null}
    </article>
  );
}
