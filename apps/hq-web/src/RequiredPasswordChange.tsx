import { useState } from 'react';

import { changeOwnPassword } from './api.js';
import { Icon } from './icons.js';
import './RequiredPasswordChange.css';

export function RequiredPasswordChange({ csrfToken, onChanged, onSignOut }: {
  csrfToken: string;
  onChanged: () => Promise<void>;
  onSignOut: () => Promise<void>;
}) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  return (
    <main className="auth-page required-password-page">
      <section className="required-password-card" aria-labelledby="required-password-heading">
        <div className="required-password-brand"><Icon name="security" /><span>TibaTrace · Account security</span></div>
        <h1 id="required-password-heading">Secure your account</h1>
        <p className="required-password-lead">Replace your temporary password before opening your workspace.</p>
        <form className="required-password-form" aria-busy={busy} onSubmit={(event) => {
          event.preventDefault();
          if (busy) return;
          setError('');
          if (next !== confirmation) { setError('New passwords do not match.'); return; }
          setBusy(true);
          void changeOwnPassword(current, next, csrfToken).then(async () => {
            setCurrent(''); setNext(''); setConfirmation(''); await onChanged();
          }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : 'Password change failed.'))
            .finally(() => setBusy(false));
        }}>
          <div className="required-password-field">
            <label htmlFor="temporary-password">Current temporary password</label>
            <input id="temporary-password" type="password" autoComplete="current-password" required disabled={busy}
              value={current} onChange={(event) => setCurrent(event.target.value)} />
          </div>
          <div className="required-password-field">
            <label htmlFor="replacement-password">New password</label>
            <input id="replacement-password" type="password" autoComplete="new-password" required minLength={12} disabled={busy}
              aria-describedby="replacement-password-help" value={next} onChange={(event) => setNext(event.target.value)} />
            <p id="replacement-password-help" className="required-password-hint">Use at least 12 characters.</p>
          </div>
          <div className="required-password-field">
            <label htmlFor="replacement-confirm">Confirm new password</label>
            <input id="replacement-confirm" type="password" autoComplete="new-password" required disabled={busy}
              value={confirmation} onChange={(event) => setConfirmation(event.target.value)} />
          </div>
          {error && <p className="required-password-error" role="alert"><Icon name="alert" /><span>{error}</span></p>}
          <div className="required-password-actions">
            <button type="submit" className="primary-button" disabled={busy}>{busy ? 'Updating…' : 'Change password'}</button>
            <button type="button" className="secondary-button" disabled={busy} onClick={() => void onSignOut()}>Sign out</button>
          </div>
        </form>
        <p className="required-password-footnote"><Icon name="shield" />Your workspace stays locked until your password is updated.</p>
      </section>
    </main>
  );
}
