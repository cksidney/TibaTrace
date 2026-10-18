import { useEffect, useState, type ReactNode } from 'react';
import { Pressable, ScrollView, Text, TextInput } from 'react-native';

import type { AndroidPosRuntime } from '../native/runtime';

export function ActivationScreen({ runtime, onLogout, children }: {
  readonly runtime: AndroidPosRuntime; readonly onLogout: () => Promise<void>; readonly children: ReactNode;
}) {
  const [valid, setValid] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [deviceId, setDeviceId] = useState('');
  const [fingerprint, setFingerprint] = useState('');
  const [branch, setBranch] = useState('');
  const [register, setRegister] = useState('');
  const [name, setName] = useState('');
  const [justification, setJustification] = useState('');
  const [challenge, setChallenge] = useState('');
  const [requests, setRequests] = useState<{ id: string; deviceId: string; state: string; challengeAvailable?: boolean }[]>([]);
  const [options, setOptions] = useState<{ branches: { id: string; name: string; code: string }[]; registers: { id: string; code: string; name: string; branchId: string; available: boolean }[] }>({ branches: [], registers: [] });

  const refresh = async () => {
    setBusy(true);
    setError('');
    try {
      const id = await runtime.deviceId();
      const fp = await runtime.fingerprint();
      setDeviceId(id);
      setFingerprint(fp);
      const identity = await runtime.session.fetch('/api/identity/me/');
      if (!identity.ok) throw new Error('Sign in again to verify this operator session.');
      if ((await identity.json() as { must_change_password?: boolean }).must_change_password) {
        throw new Error('Change your temporary password in HQ at https://tibatrace.esenai.co.ke, then sign out and sign in again on this till.');
      }
      const stored = await runtime.activation().catch(() => { setError('Saved activation could not be read. Ask the platform owner for a recovery code for this installation.'); return null; });
      if (stored) {
        const response = await runtime.session.fetch('/api/v1/tenant/pos-activations/requests/validate/', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ signed_token: stored.signedToken, device_id: id, device_fingerprint: fp }),
        });
        if (response.ok && (await response.json() as { valid?: boolean }).valid === true) {
          setValid(true);
          return;
        }
      }
      setValid(false);
      const response = await runtime.session.fetch(`/api/v1/tenant/pos-activations/requests/?device_id=${encodeURIComponent(id)}`);
      if (!response.ok) throw new Error('Ask an authorized tenant Manager to sign in on this device and request activation.');
      setRequests(await response.json() as { id: string; deviceId: string; state: string; challengeAvailable?: boolean }[]);
      const setup = await runtime.session.fetch('/api/v1/tenant/pos-activations/requests/options/');
      if (setup.ok) setOptions(await setup.json() as typeof options);
    } catch (cause) {
      setValid(false);
      setError(cause instanceof Error ? cause.message : 'Activation could not be verified.');
    } finally { setBusy(false); }
  };
  useEffect(() => {
    void refresh();
    const timer = setInterval(() => { void refresh(); }, 60000);
    return () => clearInterval(timer);
  }, [runtime]);

  const mutate = async (path: string, body: Record<string, string>) => {
    setBusy(true);
    setError('');
    try {
      const response = await runtime.session.fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!response.ok) {
        const body = await response.json() as { detail?: string };
        throw new Error(body.detail ?? `Activation action was not accepted (HTTP ${response.status}).`);
      }
      setChallenge('');
      await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Activation action failed.'); }
    finally { setBusy(false); }
  };
  if (valid) return <>{children}</>;
  const approved = requests.find((request) => request.deviceId === deviceId && (request.state === 'APPROVED' || (request.state === 'ACTIVATED' && request.challengeAvailable)));
  const existing = requests.find(request => request.deviceId === deviceId && ['SUBMITTED', 'APPROVED', 'ACTIVATED', 'SUSPENDED'].includes(request.state));
  return <ScrollView contentContainerStyle={{ padding: 24, gap: 16 }}>
    <Text style={{ fontSize: 24, fontWeight: '700' }}>Activate this POS installation</Text>
    <Text>Trading stays blocked until a separate platform administrator approves this device and enrolment is verified online.</Text>
    <Text selectable>Device ID: {deviceId}</Text>
    <Text selectable>Installation fingerprint (not hardware attestation): {fingerprint}</Text>
    {error ? <Text accessibilityRole="alert" style={{ color: '#a31313' }}>{error}</Text> : null}
    {approved ? <>
      <Text>Approved request: {approved.id}. Enter the one-time challenge issued to your Manager.</Text>
      <TextInput value={challenge} onChangeText={setChallenge} placeholder="One-time enrolment challenge" autoCapitalize="none" autoCorrect={false} />
      <Pressable disabled={busy || !challenge.trim()} onPress={() => { void mutate(`/api/v1/tenant/pos-activations/requests/${approved.id}/enrol/`, {
        challenge_code: challenge.trim(), device_id: deviceId, device_fingerprint: fingerprint,
      }); }}><Text>Complete enrolment</Text></Pressable>
    </> : existing ? <Text>Activation: {existing.state}. {existing.state === 'SUBMITTED' ? 'Awaiting independent platform review.' : 'Ask the platform owner to resume the installation or issue a renewal / recovery code. No new activation request is required.'}</Text> : <>
      <Text>Choose branch</Text>
      {options.branches.map(row => <Pressable key={row.id} accessibilityRole="radio" accessibilityState={{ checked: branch === row.id }} disabled={busy} onPress={() => { setBranch(row.id); setRegister(''); }}><Text>{branch === row.id ? '● ' : '○ '}{row.name} · {row.code}</Text></Pressable>)}
      <Text>Choose available physical till</Text>
      {options.registers.filter(row => row.branchId === branch && row.available).map(row => <Pressable key={row.id} accessibilityRole="radio" accessibilityState={{ checked: register === row.code }} disabled={busy} onPress={() => setRegister(row.code)}><Text>{register === row.code ? '● ' : '○ '}{row.code} · {row.name}</Text></Pressable>)}
      {branch && !options.registers.some(row => row.branchId === branch && row.available) ? <Text>Create an unassigned till in HQ Finance &amp; Cash Control, or complete governed replacement of the old device.</Text> : null}
      <TextInput value={name} onChangeText={setName} placeholder="Device name" />
      <TextInput value={justification} onChangeText={setJustification} placeholder="Business justification (at least 10 characters)" multiline />
      <Pressable disabled={busy || !branch || !register || !name || justification.trim().length < 10} onPress={() => { void mutate('/api/v1/tenant/pos-activations/requests/', {
        tenant_id: runtime.session.current?.tenantId ?? '', branch_id: branch.trim(), requested_register: register.trim(),
        device_id: deviceId, device_fingerprint: fingerprint, device_name: name.trim(), device_type: 'MOBILE_ANDROID',
        app_version: runtime.version, business_justification: justification.trim(),
      }); }}><Text>Request independent approval</Text></Pressable>
      {requests.filter((request) => request.deviceId === deviceId).map((request) => <Text key={request.id}>Request {request.id}: {request.state}</Text>)}
    </>}
    <Pressable disabled={busy} onPress={() => { void refresh(); }}><Text>{busy ? 'Checking activation…' : 'Refresh approval status'}</Text></Pressable>
    <Pressable onPress={() => { void onLogout(); }}><Text>Sign out</Text></Pressable>
  </ScrollView>;
}
