import { useRef, useState } from 'react';
import { clinicalCommand, FINAL_CHECK_ITEMS, reservationQuantityValid } from '@dawatrace/shared/dispensing/index.js';
import type { DispensingEpisodeDTO } from '@dawatrace/shared/dispensing/index.js';

export function ClinicalPreparation({ episode, apiFetch, onChanged }: {
  episode: DispensingEpisodeDTO; apiFetch: typeof fetch; onChanged: () => void;
}) {
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  const [notes, setNotes] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const keys = useRef<Record<string, string>>({});
  const items = episode.authorized_items ?? [];
  const run = async (command: string, body: unknown) => {
    setBusy(true); setError('');
    try { await clinicalCommand(apiFetch, episode.id, command, body); onChanged(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  };
  const reserve = (id: string, quantity: string) => {
    const keyId = `${episode.id}:${id}`;
    keys.current[keyId] ??= crypto.randomUUID();
    void run('reserve', { prescription_item_id: id, quantity, idempotency_key: keys.current[keyId] });
  };
  const preparing = ['DRAFT', 'PREPARING'].includes(episode.status);
  const checking = episode.status === 'CHECKING' && episode.lines.every(line => line.status === 'PREPARED');
  if (!preparing && !checking) return null;
  return <section aria-label="Governed preparation and final check" style={{ border: '1px solid #cbd5e1', padding: 20, borderRadius: 12 }}>
    {error ? <p role="alert">{error}</p> : null}
    <p>Use current pharmacist verification and released FEFO stock. A second authorised operator must perform the final check.</p>
    {preparing ? <>
      <h2>Reserve and prepare</h2>
      {items.map(item => <div key={item.id} style={{ marginBottom: 12 }}>
        <label>{item.medicine_name} · {item.unit} · {item.quantity_remaining} authorised remaining
          <input aria-label={`Reserve ${item.medicine_name}`} type="number" min="0.0001" step="0.0001"
            value={quantities[item.id] ?? item.quantity_remaining} disabled={busy || Number(item.reserved_quantity) > 0}
            onChange={event => setQuantities(previous => ({ ...previous, [item.id]: event.target.value }))} />
        </label>
        {Number(item.reserved_quantity) > 0 ? <span> Reserved: {item.reserved_quantity}</span> :
          <button disabled={busy || !reservationQuantityValid(item, quantities[item.id] ?? item.quantity_remaining)}
            onClick={() => reserve(item.id, quantities[item.id] ?? item.quantity_remaining)}>Reserve quantity</button>}
      </div>)}
      {items.length === 0 ? <p>No authorised items available. Complete prescription intake and pharmacist verification first.</p> : null}
      <button disabled={busy || !items.some(item => Number(item.reserved_quantity) > 0)} onClick={() => void run('allocate', {})}>Allocate FEFO batches</button>{' '}
      <button disabled={busy || !items.some(item => Number(item.reserved_quantity) > 0)} onClick={() => void run('prepare', {})}>Record preparation</button>
    </> : <>
      <h2>Independent final check — all prepared lines</h2>
      {!episode.clinical_details_visible ? <p>Sign in as the independent checker to view instructions and complete this check.</p> : null}
      {FINAL_CHECK_ITEMS.map(([key, label]) => <label key={key} style={{ display: 'block', padding: 6 }}>
        <input type="checkbox" checked={checks[key] === true} disabled={busy || !episode.clinical_details_visible}
          onChange={event => setChecks(previous => ({ ...previous, [key]: event.target.checked }))} /> {label}
      </label>)}
      <label>Checker notes <textarea value={notes} disabled={busy} onChange={event => setNotes(event.target.value)} /></label>
      <button disabled={busy || !episode.clinical_details_visible || !FINAL_CHECK_ITEMS.every(([key]) => checks[key])}
        onClick={() => void run('check', { checklist: checks, notes })}>Record independent final check</button>
    </>}
    <button disabled={busy} onClick={onChanged}>Refresh authoritative episode</button>
  </section>;
}
