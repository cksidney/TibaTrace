import { useRef, useState } from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';
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
  const sequence = useRef(0);
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
    keys.current[keyId] ??= `reserve:${episode.id}:${id}:${Date.now()}:${++sequence.current}`;
    void run('reserve', { prescription_item_id: id, quantity, idempotency_key: keys.current[keyId] });
  };
  const preparing = ['DRAFT', 'PREPARING'].includes(episode.status);
  const checking = episode.status === 'CHECKING' && episode.lines.length > 0 && episode.lines.every(line => line.status === 'PREPARED');
  const button = (label: string, disabled: boolean, onPress: () => void) => <Pressable accessibilityRole="button"
    accessibilityState={{ disabled }} disabled={disabled} onPress={onPress}
    style={{ padding: 14, marginVertical: 4, borderRadius: 8, backgroundColor: disabled ? '#dbe2e8' : '#086b52' }}>
    <Text style={{ color: disabled ? '#334155' : '#fff', fontWeight: '600' }}>{label}</Text>
  </Pressable>;
  if (!preparing && !checking) return null;
  return <View style={{ padding: 16, borderWidth: 1, borderColor: '#cbd5e1', borderRadius: 12 }}>
    {error ? <Text accessibilityRole="alert">{error}</Text> : null}
    <Text>Current pharmacist verification and released FEFO stock are required. The preparer cannot perform the final check.</Text>
    {preparing ? <>
      <Text style={{ fontWeight: '700', fontSize: 18 }}>Reserve and prepare</Text>
      {items.map(item => <View key={item.id} style={{ marginVertical: 8 }}>
        <Text>{item.medicine_name} · {item.unit} · {item.quantity_remaining} authorised remaining</Text>
        <TextInput accessibilityLabel={`Reserve ${item.medicine_name}`} keyboardType="decimal-pad"
          value={quantities[item.id] ?? item.quantity_remaining} editable={!busy && Number(item.reserved_quantity) === 0}
          onChangeText={value => setQuantities(previous => ({ ...previous, [item.id]: value }))}
          style={{ padding: 12, borderWidth: 1, borderColor: '#94a3b8', borderRadius: 6 }} />
        {Number(item.reserved_quantity) > 0 ? <Text>Reserved: {item.reserved_quantity}</Text> :
          button('Reserve quantity', busy || !reservationQuantityValid(item, quantities[item.id] ?? item.quantity_remaining),
            () => reserve(item.id, quantities[item.id] ?? item.quantity_remaining))}
      </View>)}
      {items.length === 0 ? <Text>Complete prescription intake and pharmacist verification first.</Text> : null}
      {button('Allocate FEFO batches', busy || !items.some(item => Number(item.reserved_quantity) > 0), () => void run('allocate', {}))}
      {button('Record preparation', busy || !items.some(item => Number(item.reserved_quantity) > 0), () => void run('prepare', {}))}
    </> : <>
      <Text style={{ fontWeight: '700', fontSize: 18 }}>Independent final check — all lines</Text>
      {!episode.clinical_details_visible ? <Text>Sign in as the independent checker to view instructions and complete this check.</Text> : null}
      {FINAL_CHECK_ITEMS.map(([key, label]) => <Pressable key={key} accessibilityRole="checkbox"
        accessibilityState={{ checked: checks[key] === true, disabled: busy || !episode.clinical_details_visible }}
        disabled={busy || !episode.clinical_details_visible}
        onPress={() => setChecks(previous => ({ ...previous, [key]: !previous[key] }))} style={{ padding: 12 }}>
        <Text>{checks[key] ? '☑' : '☐'} {label}</Text>
      </Pressable>)}
      <TextInput accessibilityLabel="Checker notes" multiline value={notes} onChangeText={setNotes} editable={!busy}
        style={{ padding: 12, borderWidth: 1, borderColor: '#94a3b8' }} />
      {button('Record independent final check', busy || !episode.clinical_details_visible || !FINAL_CHECK_ITEMS.every(([key]) => checks[key]),
        () => void run('check', { checklist: checks, notes }))}
    </>}
    {button('Refresh authoritative episode', busy, onChanged)}
  </View>;
}
