import { useEffect, useRef, useState } from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';
import type { PosRetailClient, RetailTransactionDTO, RetailStoreDTO } from '@dawatrace/shared/retail/index.js';

export function RetailReturns({ client, deviceId }: { client: PosRetailClient; deviceId: string }) {
  const [number, setNumber] = useState('');
  const [sale, setSale] = useState<RetailTransactionDTO | null>(null);
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [batches, setBatches] = useState<Record<string, string>>({});
  const [physical, setPhysical] = useState<Record<string, boolean>>({});
  const [location, setLocation] = useState('');
  const [stores, setStores] = useState<readonly RetailStoreDTO[]>([]);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const key = useRef('');
  useEffect(() => { void client.stores(deviceId).then(setStores).catch(() => setStores([])); }, [client, deviceId]);
  const run = async (work: () => Promise<void>) => {
    setBusy(true); setNotice('');
    try { await work(); } catch (cause) { setNotice(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  };
  const reload = async () => { if (sale) setSale(await client.getTransaction(sale.id)); };
  const button = (label: string, onPress: () => void, disabled = busy) => <Pressable accessibilityRole="button" disabled={disabled}
    accessibilityState={{ disabled }} onPress={onPress} style={{ padding: 14, borderRadius: 8, marginVertical: 4, backgroundColor: disabled ? '#dbe2e8' : '#086b52' }}>
    <Text style={{ color: disabled ? '#334155' : 'white', fontWeight: '600' }}>{label}</Text></Pressable>;
  const request = () => void run(async () => {
    if (!sale) return;
    const lines = sale.lines.filter(line => Number(quantities[line.id]) > 0).map(line => ({
      line_id: line.id, quantity: quantities[line.id]!, return_to_stock: physical[line.id] === true,
      ...(physical[line.id] ? { inventory_batch_id: batches[line.id] || '' } : {}),
    }));
    if (!lines.length || !reason.trim()) throw new Error('Select positive quantities and record a reason.');
    if (lines.some(line => line.return_to_stock && (!location || !line.inventory_batch_id))) throw new Error('Confirm original batch and quarantine location for physical returns.');
    key.current ||= `refund:${sale.id}:${Date.now()}`;
    await client.requestRefund(sale.id, { device_id: deviceId, reason: reason.trim(), idempotency_key: key.current,
      lines, ...(lines.some(line => line.return_to_stock) ? { return_location_id: location } : {}) });
    await reload(); setNotice('Request saved. A distinct authorised supervisor must approve it.');
  });
  const inputStyle = { borderWidth: 1, borderColor: '#94a3b8', padding: 12, borderRadius: 6 };
  return <View style={{ padding: 16, borderWidth: 1, borderColor: '#cbd5e1', borderRadius: 12, marginTop: 16 }}>
    <Text style={{ fontWeight: '700', fontSize: 18 }}>Returns and cash refunds</Text>
    <Text>Original internal receipt required. Physical returns remain quarantined, not saleable.</Text>
    <TextInput accessibilityLabel="Original receipt number" value={number} onChangeText={setNumber} editable={!busy} style={inputStyle} />
    {button('Find receipt', () => void run(async () => {
      setSale(await client.lookupReceipt(number.trim())); setQuantities({}); setPhysical({}); setBatches({}); key.current = '';
    }), busy || !number.trim())}
    {notice ? <Text accessibilityRole="alert">{notice}</Text> : null}
    {sale ? <>
      <Text>{sale.receipt?.receipt_number} · {sale.currency} {sale.total} · refunded {sale.refunded_total ?? '0.00'}</Text>
      {sale.lines.map(line => <View key={line.id} style={{ paddingVertical: 10 }}>
        <Text>{line.description_snapshot} · refundable {line.refundable_quantity ?? '0'} {line.unit}</Text>
        <TextInput accessibilityLabel={`Refund quantity ${line.description_snapshot}`} keyboardType="decimal-pad"
          value={quantities[line.id] ?? '0'} onChangeText={value => setQuantities(previous => ({ ...previous, [line.id]: value }))} editable={!busy} style={inputStyle} />
        <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: physical[line.id] === true }} disabled={busy}
          onPress={() => setPhysical(previous => ({ ...previous, [line.id]: !previous[line.id] }))} style={{ padding: 12 }}>
          <Text>{physical[line.id] ? '☑' : '☐'} Receive physical stock into quarantine</Text>
        </Pressable>
        {physical[line.id] ? <View><Text>Choose the actual returned original batch:</Text>
          {line.issued_batches?.map(batch => button(`${batches[line.id] === batch.batch_id ? '●' : '○'} ${batch.batch_number} · ${batch.expiry_date} · issued ${batch.quantity}`,
            () => setBatches(previous => ({ ...previous, [line.id]: batch.batch_id }))))}
        </View> : null}
      </View>)}
      {Object.values(physical).some(Boolean) ? <View><Text>Quarantine custody location:</Text>
        {stores.filter(store => store.quarantine_capability).map(store => <View key={store.id}>{button(`${location === store.id ? '●' : '○'} ${store.name}`, () => setLocation(store.id))}</View>)}
      </View> : null}
      <TextInput accessibilityLabel="Refund or review reason" multiline value={reason} onChangeText={setReason} editable={!busy} style={inputStyle} />
      {button('Request refund', request)}
      {button('Refresh original facts', () => void run(reload))}
      {sale.refund_requests?.map(refund => <View key={refund.id} style={{ paddingVertical: 12 }}>
        <Text style={{ fontWeight: '700' }}>{refund.status} · {refund.currency} {refund.amount}</Text><Text>{refund.reason}</Text>
        {refund.status === 'REQUESTED' ? <>
          {button('Supervisor approve', () => void run(async () => { await client.reviewRefund(sale.id, refund.id, true); await reload(); }))}
          {button('Reject with reason', () => void run(async () => { await client.reviewRefund(sale.id, refund.id, false, reason.trim()); await reload(); }), busy || !reason.trim())}
          <Text>A different authorised supervisor must sign in; the server enforces this rule.</Text>
        </> : null}
        {refund.status === 'APPROVED' ? button('Confirm cash handed back', () => void run(async () => {
          await client.cashRefund(sale.id, refund.id, deviceId, `cash-refund:${refund.id}`); await reload();
          setNotice('Cash refund recorded. The original sale is unchanged.');
        })) : null}
        {refund.receipt ? <Text>Refund receipt {refund.receipt.refund_number} · {refund.receipt.currency} {refund.receipt.amount}. Print job {refund.receipt.print_job?.status ?? 'not queued'}.</Text> : null}
      </View>)}
    </> : null}
  </View>;
}
