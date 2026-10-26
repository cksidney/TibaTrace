import { useState, type FormEvent } from 'react';
import { mfaCommand, readSession, type SessionState, type MfaResult } from './api.js';
import './mfa.css';

export function MfaSecurity({ session, onComplete, onSignOut }: {
  readonly session: SessionState;
  readonly onComplete: (session: SessionState) => void;
  readonly onSignOut: () => Promise<void>;
}) {
  const [current, setCurrent] = useState(session);
  const [setup, setSetup] = useState<MfaResult | null>(null);
  const [codes, setCodes] = useState<readonly string[]>([]);
  const [stored, setStored] = useState(false);
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [action, setAction] = useState<'recovery' | 'reset'>('recovery');
  const managing = current.mfa?.enrolled && current.mfa.verified;
  const expired = current.mfa?.reauthenticate && !managing;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError('');
    try {
      if (!current.mfa?.enrolled && !setup) {
        setSetup(await mfaCommand('enroll', { current_password: password }, current.csrf_token));
      } else {
        const operation = setup ? 'confirm' : managing ? action : 'verify';
        const result = await mfaCommand(operation, { current_password: password, code }, current.csrf_token);
        if (result.recovery_codes?.length) { setCodes(result.recovery_codes); setStored(false); }
        const next = await readSession();
        setCurrent(next); setSetup(null);
        if (!result.recovery_codes?.length && operation === 'verify') onComplete(next);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'MFA request failed.');
    } finally {
      setPassword(''); setCode(''); setBusy(false);
    }
  }

  return <main className="mfa-screen"><section className="mfa-card" aria-labelledby="mfa-title">
    <img className="mfa-brand" src="/brand/tibatrace-logo.jpeg" alt="TibaTrace" />
    <p className="eyebrow">Account security</p>
    <h1 id="mfa-title">{codes.length ? 'Save your recovery codes' : expired ? 'Sign in again' : setup ? 'Connect your authenticator' : managing ? 'Manage two-step verification' : current.mfa?.enrolled ? 'Verify your sign-in' : 'Protect your account'}</h1>
    {error && <p className="inline-alert" role="alert">{error}</p>}
    {codes.length ? <>
      <p>Keep these codes in a secure place separate from your authenticator. Each code works once. They are shown only now.</p>
      <div className="mfa-codes" aria-label="Recovery codes">{codes.map(value => <code key={value}>{value}</code>)}</div>
      <label className="mfa-check"><input type="checkbox" checked={stored} onChange={e => setStored(e.target.checked)} />I have stored these recovery codes securely.</label>
      <button className="primary-button" disabled={!stored || busy} onClick={() => {
        setBusy(true); setError('');
        void readSession().then(next => { setCodes([]); onComplete(next); })
          .catch(reason => setError(reason instanceof Error ? reason.message : 'Session could not be confirmed. Your recovery codes are still shown.'))
          .finally(() => setBusy(false));
      }}>Continue to HQ</button>
    </> : expired ? <>
      <p>Your verification window has ended. Sign out and enter your password again to continue.</p>
    </> : <form className="auth-form" onSubmit={event => void submit(event)}>
      {setup ? <>
        <p>Scan this code with your authenticator app, then enter its six-digit code.</p>
        {setup.qr_svg && <img className="mfa-qr" src={`data:image/svg+xml,${encodeURIComponent(setup.qr_svg)}`} alt="Authenticator enrollment QR code" />}
        <details><summary>Enter the setup key manually</summary><code className="mfa-secret">{setup.secret}</code></details>
      </> : managing ? <>
        <p>Confirm your password and a fresh authenticator or unused recovery code. Other verified sessions will need to sign in again.</p>
        <label>Action<select value={action} onChange={e => setAction(e.target.value as 'recovery' | 'reset')}><option value="recovery">Generate new recovery codes</option><option value="reset">Replace authenticator</option></select></label>
      </> : <p>{current.mfa?.enrolled ? 'Enter a fresh authenticator code or one of your unused recovery codes.' : 'Use an authenticator app to add a second check to sign-in. Confirm your current password to begin.'}</p>}
      {!setup && (!current.mfa?.enrolled || managing) && <label>Current password<input autoComplete="current-password" type="password" required value={password} onChange={e => setPassword(e.target.value)} /></label>}
      {(setup || current.mfa?.enrolled) && <label>{setup ? 'Authenticator code' : 'Authenticator or recovery code'}<input autoComplete="one-time-code" autoFocus required maxLength={80} value={code} onChange={e => setCode(e.target.value)} /></label>}
      <button type="submit" className="primary-button" disabled={busy}>{busy ? 'Checking…' : setup ? 'Confirm authenticator' : managing ? 'Confirm change' : current.mfa?.enrolled ? 'Verify and continue' : 'Set up authenticator'}</button>
    </form>}
    <div className="mfa-footer">
      {!codes.length && (!current.mfa?.required || current.mfa.verified) && <button className="secondary-button" onClick={() => onComplete(current)}>Back to HQ</button>}
      <button className="secondary-button" disabled={busy} onClick={() => void onSignOut()}>Sign out</button>
    </div>
  </section></main>;
}
