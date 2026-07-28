import { PosRetailClient, type RetailCatalogueItemDTO, type RetailTransactionDTO, type RetailTransactionLineDTO } from '@dawatrace/shared/retail/index.js';
import { fontSize, spacing, surface, text } from '@dawatrace/shared/design-system/index.js';
import { useEffect, useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

interface RetailScreenProps {
  readonly apiBaseUrl: string;
  readonly apiFetch: typeof fetch;
  readonly deviceId: string;
}

export function RetailScreen({ apiBaseUrl, apiFetch, deviceId }: RetailScreenProps) {
  const client = useMemo(() => new PosRetailClient(`${apiBaseUrl}/api/pos/retail`, { fetcher: apiFetch }), [apiBaseUrl, apiFetch]);
  const [storeId, setStoreId] = useState('');
  const [stores, setStores] = useState<readonly { id: string; name: string; location_type: string; status: string }[]>([]);
  const [transaction, setTransaction] = useState<RetailTransactionDTO | null>(null);
  const [results, setResults] = useState<readonly RetailCatalogueItemDTO[]>([]);
  const [barcode, setBarcode] = useState('');
  const [query, setQuery] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void client.stores().then((loaded) => {
      const active = loaded.filter((store) => store.status === 'ACTIVE' && ['STORE', 'PHARMACY', 'DISPENSARY'].includes(store.location_type));
      setStores(active);
      setStoreId((current) => current || active[0]?.id || '');
    }).catch((cause: unknown) => setNotice(message(cause)));
  }, [client]);

  const run = async (operation: () => Promise<void>) => {
    setBusy(true);
    try { await operation(); setNotice(''); } catch (cause) { setNotice(message(cause)); } finally { setBusy(false); }
  };
  const start = () => void run(async () => {
    if (!storeId) throw new Error('An active retail store is required.');
    setTransaction(await client.createDraft({ device_id: deviceId, store_id: storeId }));
    setResults([]);
  });
  const scan = () => void run(async () => {
    if (!transaction) throw new Error('Start a sale before scanning.');
    if (!barcode.trim()) throw new Error('Enter or scan a barcode.');
    updateLine(await client.scan(transaction.id, { device_id: deviceId, barcode: barcode.trim(), quantity: '1.0000' }));
    setBarcode('');
  });
  const search = () => void run(async () => {
    if (!storeId || !query.trim()) { setResults([]); return; }
    setResults(await client.search({ device_id: deviceId, store_id: storeId, query: query.trim() }));
  });
  const add = (item: RetailCatalogueItemDTO) => void run(async () => {
    if (!transaction) throw new Error('Start a sale before adding an item.');
    updateLine(await client.addLine(transaction.id, { device_id: deviceId, sku_id: item.sku_id, quantity: '1.0000' }));
  });
  const quantity = (line: RetailTransactionLineDTO, change: number) => void run(async () => {
    if (!transaction) return;
    const next = Math.max(0, Number(line.quantity) + change);
    if (next === 0) {
      await client.removeLine(transaction.id, { device_id: deviceId, line_id: line.id });
      setTransaction((current) => current ? withoutLine(current, line.id) : current);
      return;
    }
    updateLine(await client.setQuantity(transaction.id, { device_id: deviceId, line_id: line.id, quantity: next.toFixed(4) }));
  });
  const updateLine = (line: RetailTransactionLineDTO) => setTransaction((current) => current ? withLine(current, line) : current);
  const hold = () => void run(async () => { if (transaction) setTransaction(await client.hold(transaction.id, { device_id: deviceId, reason: 'Operator hold' })); });
  const resume = () => void run(async () => { if (transaction) setTransaction(await client.resume(transaction.id, { device_id: deviceId })); });
  const payment = () => void run(async () => { if (transaction) setTransaction(await client.readyForPayment(transaction.id, { device_id: deviceId })); });

  return <View style={styles.root}>
    <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
      <Text style={styles.title}>Retail sale</Text>
      <Text style={styles.muted}>Native tablet basket with authoritative pricing and store availability.</Text>
      {notice ? <Text accessibilityLiveRegion="assertive" style={styles.notice}>{notice}</Text> : null}
      <View style={styles.storeRow}>{stores.map((store) => <Pressable key={store.id} disabled={Boolean(transaction)} onPress={() => setStoreId(store.id)} style={[styles.store, storeId === store.id && styles.storeSelected]}><Text style={storeId === store.id ? styles.storeTextSelected : styles.storeText}>{store.name}</Text><Text style={styles.small}>{store.location_type}</Text></Pressable>)}</View>
      {!transaction ? <Pressable disabled={busy || !storeId} onPress={start} style={[styles.primary, (busy || !storeId) && styles.disabled]}><Text style={styles.primaryText}>Start new sale</Text></Pressable> : null}
      <View style={styles.card}>
        <Text style={styles.section}>Scan item</Text>
        <View style={styles.fieldRow}><TextInput value={barcode} onChangeText={setBarcode} onSubmitEditing={scan} editable={Boolean(transaction) && !busy} placeholder="Barcode" style={styles.input} /><Pressable onPress={scan} disabled={busy || !transaction} style={styles.secondary}><Text style={styles.secondaryText}>Add</Text></Pressable></View>
        <Text style={styles.section}>Find item</Text>
        <View style={styles.fieldRow}><TextInput value={query} onChangeText={setQuery} onSubmitEditing={search} editable={!busy} placeholder="Name or SKU" style={styles.input} /><Pressable onPress={search} disabled={busy || !storeId} style={styles.secondary}><Text style={styles.secondaryText}>Search</Text></Pressable></View>
        {results.map((item) => <Pressable key={item.sku_id} onPress={() => add(item)} disabled={busy || !transaction || item.stock_state === 'OUT_OF_STOCK'} style={styles.result}><View><Text style={styles.resultName}>{item.display_name}</Text><Text style={styles.small}>{item.sku_code} · {item.available_quantity} {item.unit} · {item.stock_state.replace(/_/g, ' ')}</Text></View><Text style={styles.resultPrice}>{money(item.unit_price, item.currency)}</Text></Pressable>)}
      </View>
      <View style={styles.card}><Text style={styles.section}>{transaction ? transaction.transaction_number : 'Basket'}</Text>{transaction?.lines.length ? transaction.lines.map((line) => <View key={line.id} style={styles.line}><View style={styles.lineInfo}><Text style={styles.resultName}>{line.description_snapshot}</Text><Text style={styles.small}>{money(line.unit_price, line.currency)} · {line.inventory_context.stock_state.replace(/_/g, ' ')}</Text></View><View style={styles.lineControls}><Pressable disabled={busy || transaction.state !== 'DRAFT'} onPress={() => quantity(line, -1)} style={styles.count}><Text>−</Text></Pressable><Text>{line.quantity}</Text><Pressable disabled={busy || transaction.state !== 'DRAFT'} onPress={() => quantity(line, 1)} style={styles.count}><Text>+</Text></Pressable></View><Text style={styles.resultPrice}>{money(line.line_total, line.currency)}</Text></View>) : <Text style={styles.muted}>No items in the current basket.</Text>}</View>
    </ScrollView>
    {transaction ? <View style={styles.footer}><View><Text style={styles.small}>Basket total · {transaction.state.replace(/_/g, ' ')}</Text><Text style={styles.total}>{money(transaction.total, transaction.currency)}</Text></View><View style={styles.footerActions}>{transaction.state === 'HELD' ? <Pressable onPress={resume} disabled={busy} style={styles.secondary}><Text style={styles.secondaryText}>Resume</Text></Pressable> : <Pressable onPress={hold} disabled={busy || transaction.state !== 'DRAFT'} style={styles.secondary}><Text style={styles.secondaryText}>Hold</Text></Pressable>}<Pressable onPress={payment} disabled={busy || !transaction.lines.length || transaction.state !== 'DRAFT'} style={[styles.primary, styles.pay, (busy || !transaction.lines.length || transaction.state !== 'DRAFT') && styles.disabled]}><Text style={styles.primaryText}>Payment</Text></Pressable></View></View> : null}
  </View>;
}

function withLine(transaction: RetailTransactionDTO, line: RetailTransactionLineDTO): RetailTransactionDTO { const lines = transaction.lines.some((entry) => entry.id === line.id) ? transaction.lines.map((entry) => entry.id === line.id ? line : entry) : [...transaction.lines, line]; return withTotals({ ...transaction, lines }); }
function withoutLine(transaction: RetailTransactionDTO, id: string): RetailTransactionDTO { return withTotals({ ...transaction, lines: transaction.lines.filter((line) => line.id !== id) }); }
function withTotals(transaction: RetailTransactionDTO): RetailTransactionDTO { const total = transaction.lines.reduce((sum, line) => sum + Number(line.line_total), 0).toFixed(2); return { ...transaction, lines: transaction.lines, subtotal: total, total, discount_total: '0.00', tax_total: '0.00' }; }
function money(amount: string, currency: string) { return `${currency} ${Number(amount).toFixed(2)}`; }
function message(cause: unknown) { return cause instanceof Error ? cause.message : String(cause); }

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: surface.page }, content: { padding: spacing.lg, gap: spacing.md, paddingBottom: 104 }, title: { fontSize: fontSize.screenTitle, color: text.primary, fontWeight: '700' }, muted: { color: text.secondary }, notice: { color: '#A83416', fontWeight: '700' }, storeRow: { flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' }, store: { borderWidth: 1, borderColor: surface.border, borderRadius: 8, padding: spacing.sm, backgroundColor: surface.raised }, storeSelected: { backgroundColor: '#E7F5EC', borderColor: '#12854A' }, storeText: { color: text.primary, fontWeight: '600' }, storeTextSelected: { color: '#075D31', fontWeight: '700' }, card: { borderWidth: 1, borderColor: surface.border, borderRadius: 12, padding: spacing.md, gap: spacing.sm, backgroundColor: surface.raised }, section: { fontWeight: '700', fontSize: fontSize.bodyLarge, color: text.primary }, fieldRow: { flexDirection: 'row', gap: spacing.sm }, input: { flex: 1, minHeight: 44, borderWidth: 1, borderColor: surface.borderStrong, borderRadius: 8, paddingHorizontal: 10, backgroundColor: '#fff', color: text.primary }, primary: { minHeight: 44, borderRadius: 8, backgroundColor: '#12854A', alignItems: 'center', justifyContent: 'center', paddingHorizontal: spacing.md }, primaryText: { color: '#fff', fontWeight: '700' }, secondary: { minHeight: 42, borderWidth: 1, borderColor: surface.borderStrong, borderRadius: 8, paddingHorizontal: spacing.md, alignItems: 'center', justifyContent: 'center', backgroundColor: '#fff' }, secondaryText: { color: text.primary, fontWeight: '700' }, disabled: { opacity: 0.45 }, result: { flexDirection: 'row', justifyContent: 'space-between', gap: spacing.sm, paddingVertical: spacing.sm, borderTopWidth: 1, borderTopColor: surface.border }, resultName: { color: text.primary, fontWeight: '700' }, resultPrice: { color: text.primary, fontWeight: '700', alignSelf: 'center' }, small: { color: text.secondary, fontSize: fontSize.caption }, line: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, borderTopWidth: 1, borderTopColor: surface.border, paddingVertical: spacing.sm }, lineInfo: { flex: 1 }, lineControls: { flexDirection: 'row', alignItems: 'center', gap: 8 }, count: { width: 28, height: 28, borderWidth: 1, borderColor: surface.borderStrong, borderRadius: 6, alignItems: 'center', justifyContent: 'center' }, footer: { position: 'absolute', left: 0, right: 0, bottom: 0, backgroundColor: surface.raised, borderTopWidth: 1, borderTopColor: surface.border, padding: spacing.md, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm }, total: { fontSize: fontSize.bodyLarge, fontWeight: '700', color: text.primary }, footerActions: { flexDirection: 'row', gap: spacing.sm, alignItems: 'center' }, pay: { minWidth: 96 },
});
