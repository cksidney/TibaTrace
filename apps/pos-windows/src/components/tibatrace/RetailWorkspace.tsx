import { PosRetailClient, type RetailCatalogueItemDTO, type RetailTransactionDTO, type RetailTransactionLineDTO } from '@dawatrace/shared/retail/index.js';
import { fontSize, spacing, surface, text } from '@dawatrace/shared/design-system/index.js';
import { useCallback, useEffect, useMemo, useState } from 'react';

interface RetailWorkspaceProps {
  readonly apiFetch: typeof fetch;
  readonly deviceId: string;
}

export function RetailWorkspace({ apiFetch, deviceId }: RetailWorkspaceProps) {
  const client = useMemo(() => new PosRetailClient('/api/pos/retail', { fetcher: apiFetch }), [apiFetch]);
  const [storeId, setStoreId] = useState('');
  const [stores, setStores] = useState<readonly { id: string; name: string; location_type: string; status: string }[]>([]);
  const [transaction, setTransaction] = useState<RetailTransactionDTO | null>(null);
  const [results, setResults] = useState<readonly RetailCatalogueItemDTO[]>([]);
  const [barcode, setBarcode] = useState('');
  const [search, setSearch] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void client.stores().then((loaded) => {
      const sellableStores = loaded.filter(
        (store) => store.status === 'ACTIVE' && ['STORE', 'PHARMACY', 'DISPENSARY'].includes(store.location_type),
      );
      setStores(sellableStores);
      setStoreId((current) => current || sellableStores[0]?.id || '');
    }).catch((cause: unknown) => setNotice(message(cause)));
  }, [client]);

  const run = useCallback(async (operation: () => Promise<void>) => {
    setBusy(true);
    try {
      await operation();
      setNotice('');
    } catch (cause) {
      setNotice(message(cause));
    } finally {
      setBusy(false);
    }
  }, []);

  const startSale = () => void run(async () => {
    if (!storeId) throw new Error('Select an active retail store before starting a sale.');
    setTransaction(await client.createDraft({ device_id: deviceId, store_id: storeId }));
    setResults([]);
    setBarcode('');
    setSearch('');
  });

  const updateLine = (line: RetailTransactionLineDTO) => {
    setTransaction((current) => current ? withLine(current, line) : current);
  };

  const scan = () => void run(async () => {
    if (!transaction) throw new Error('Start a retail sale before scanning an item.');
    if (!barcode.trim()) throw new Error('Enter or scan a barcode.');
    updateLine(await client.scan(transaction.id, { device_id: deviceId, barcode: barcode.trim(), quantity: '1.0000' }));
    setBarcode('');
  });

  const find = () => void run(async () => {
    if (!storeId) throw new Error('Select an active retail store before searching.');
    if (!search.trim()) {
      setResults([]);
      return;
    }
    setResults(await client.search({ device_id: deviceId, store_id: storeId, query: search.trim() }));
  });

  const add = (item: RetailCatalogueItemDTO) => void run(async () => {
    if (!transaction) throw new Error('Start a retail sale before adding an item.');
    updateLine(await client.addLine(transaction.id, { device_id: deviceId, sku_id: item.sku_id, quantity: '1.0000' }));
  });

  const changeQuantity = (line: RetailTransactionLineDTO, increment: number) => void run(async () => {
    if (!transaction) return;
    const next = Math.max(0, Number(line.quantity) + increment);
    if (next === 0) {
      await client.removeLine(transaction.id, { device_id: deviceId, line_id: line.id });
      setTransaction((current) => current ? withoutLine(current, line.id) : current);
      return;
    }
    updateLine(await client.setQuantity(transaction.id, {
      device_id: deviceId,
      line_id: line.id,
      quantity: next.toFixed(4),
    }));
  });

  const hold = () => void run(async () => {
    if (!transaction) return;
    setTransaction(await client.hold(transaction.id, { device_id: deviceId, reason: 'Operator hold' }));
  });

  const resume = () => void run(async () => {
    if (!transaction) return;
    setTransaction(await client.resume(transaction.id, { device_id: deviceId }));
  });

  const cancel = () => void run(async () => {
    if (!transaction) return;
    setTransaction(await client.cancel(transaction.id, { device_id: deviceId, reason: 'Cancelled at POS' }));
  });

  const beginPayment = () => void run(async () => {
    if (!transaction) return;
    setTransaction(await client.readyForPayment(transaction.id, { device_id: deviceId }));
  });

  return (
    <main style={{ display: 'grid', gridTemplateColumns: 'minmax(260px, 0.8fr) minmax(420px, 1.4fr) minmax(280px, 0.8fr)', gap: spacing.lg, padding: spacing.xl, overflow: 'auto' }}>
      <section style={panel}>
        <SectionTitle title="Sell" detail="Scan or find a sellable, priced item." />
        <label style={labelStyle}>Retail store
          <select value={storeId} onChange={(event) => setStoreId(event.target.value)} disabled={busy || Boolean(transaction)} style={inputStyle}>
            <option value="">Select store</option>
            {stores.map((store) => <option key={store.id} value={store.id}>{store.name} · {store.location_type}</option>)}
          </select>
        </label>
        <button type="button" disabled={busy || !storeId || Boolean(transaction)} onClick={startSale} style={primaryButton}>
          Start new sale
        </button>
        <label style={{ ...labelStyle, marginTop: spacing.lg }}>Barcode
          <input value={barcode} onChange={(event) => setBarcode(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') scan(); }} disabled={busy || !transaction} placeholder="Scan barcode" style={inputStyle} />
        </label>
        <button type="button" disabled={busy || !transaction || !barcode.trim()} onClick={scan} style={secondaryButton}>Add scanned item</button>
        <label style={{ ...labelStyle, marginTop: spacing.lg }}>Find item
          <input value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') find(); }} disabled={busy || !storeId} placeholder="Name, SKU or barcode" style={inputStyle} />
        </label>
        <button type="button" disabled={busy || !storeId} onClick={find} style={secondaryButton}>Search catalogue</button>
        <div style={{ display: 'grid', gap: spacing.xs, marginTop: spacing.md }}>
          {results.map((item) => (
            <button key={item.sku_id} type="button" disabled={busy || !transaction || item.stock_state === 'OUT_OF_STOCK'} onClick={() => add(item)} style={resultButton}>
              <span><strong>{item.display_name}</strong><small>{item.sku_code} · {item.available_quantity} {item.unit} · {item.stock_state.replace(/_/g, ' ')}</small></span>
              <span>{money(item.unit_price, item.currency)}</span>
            </button>
          ))}
        </div>
      </section>

      <section style={panel}>
        <SectionTitle title={transaction ? transaction.transaction_number : 'Current basket'} detail={transaction ? `${transaction.register_code} · ${transaction.state.replace(/_/g, ' ')}` : 'Start a sale to build a backend-backed basket.'} />
        {notice ? <p role="alert" style={{ margin: 0, color: '#A83416', fontWeight: 600 }}>{notice}</p> : null}
        {!transaction ? <EmptyBasket /> : (
          <>
            <div style={{ display: 'grid', gap: spacing.sm, marginTop: spacing.md }}>
              {transaction.lines.map((line) => (
                <article key={line.id} style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: spacing.md, padding: spacing.md, border: `1px solid ${surface.border}`, borderRadius: 10 }}>
                  <div><strong>{line.description_snapshot}</strong><div style={{ color: text.secondary, fontSize: fontSize.caption }}>{line.sku_code} · {money(line.unit_price, line.currency)} / {line.unit} · {line.inventory_context.stock_state.replace(/_/g, ' ')}</div></div>
                  <div style={{ textAlign: 'right' }}><strong>{money(line.line_total, line.currency)}</strong><div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', marginTop: 6 }}><button type="button" disabled={busy || transaction.state !== 'DRAFT'} onClick={() => changeQuantity(line, -1)} style={iconButton}>−</button><span style={{ minWidth: 34, alignSelf: 'center' }}>{line.quantity}</span><button type="button" disabled={busy || transaction.state !== 'DRAFT'} onClick={() => changeQuantity(line, 1)} style={iconButton}>+</button></div></div>
                </article>
              ))}
            </div>
            <div style={{ borderTop: `1px solid ${surface.border}`, marginTop: spacing.lg, paddingTop: spacing.md, display: 'grid', gap: 6 }}>
              <Total label="Subtotal" amount={transaction.subtotal} currency={transaction.currency} />
              <Total label="Discount" amount={transaction.discount_total} currency={transaction.currency} />
              <Total label="Tax" amount={transaction.tax_total} currency={transaction.currency} />
              <Total label="Total" amount={transaction.total} currency={transaction.currency} emphatic />
            </div>
          </>
        )}
      </section>

      <aside style={panel}>
        <SectionTitle title="Sale context" detail="Authoritative pricing and operational context." />
        <dl style={{ display: 'grid', gap: spacing.sm, margin: 0 }}>
          <Context label="Customer" value="Walk-in customer" />
          <Context label="Pricing" value={transaction?.lines[0]?.price_snapshot.source ?? 'Resolved when items are added'} />
          <Context label="Register" value={transaction?.register_code ?? 'Not opened for a sale'} />
          <Context label="Basket state" value={transaction?.state.replace(/_/g, ' ') ?? 'No active basket'} />
        </dl>
        {transaction ? <div style={{ display: 'grid', gap: spacing.sm, marginTop: spacing.xl }}>
          {transaction.state === 'HELD' ? <button type="button" disabled={busy} onClick={resume} style={primaryButton}>Resume basket</button> : <button type="button" disabled={busy || transaction.state !== 'DRAFT'} onClick={hold} style={secondaryButton}>Hold basket</button>}
          <button type="button" disabled={busy || !transaction.lines.length || transaction.state !== 'DRAFT'} onClick={beginPayment} style={primaryButton}>Begin payment · {money(transaction.total, transaction.currency)}</button>
          <button type="button" disabled={busy || transaction.state !== 'DRAFT'} onClick={cancel} style={dangerButton}>Cancel basket</button>
        </div> : null}
      </aside>
    </main>
  );
}

function withLine(transaction: RetailTransactionDTO, line: RetailTransactionLineDTO): RetailTransactionDTO {
  const lines = transaction.lines.some((existing) => existing.id === line.id)
    ? transaction.lines.map((existing) => existing.id === line.id ? line : existing)
    : [...transaction.lines, line];
  return withTotals({ ...transaction, lines });
}

function withoutLine(transaction: RetailTransactionDTO, lineId: string): RetailTransactionDTO {
  return withTotals({ ...transaction, lines: transaction.lines.filter((line) => line.id !== lineId) });
}

function withTotals(transaction: RetailTransactionDTO): RetailTransactionDTO {
  const subtotal = transaction.lines.reduce((total, line) => total + Number(line.line_total), 0).toFixed(2);
  return { ...transaction, subtotal, total: subtotal, discount_total: '0.00', tax_total: '0.00' };
}

function SectionTitle({ title, detail }: { readonly title: string; readonly detail: string }) {
  return <div><h2 style={{ margin: 0, fontSize: fontSize.sectionTitle }}>{title}</h2><p style={{ margin: '4px 0 0', color: text.secondary, fontSize: fontSize.caption }}>{detail}</p></div>;
}

function EmptyBasket() { return <p style={{ marginTop: spacing.xl, color: text.secondary }}>No retail basket is open. Select a store and start a sale.</p>; }
function Total({ label, amount, currency, emphatic = false }: { readonly label: string; readonly amount: string; readonly currency: string; readonly emphatic?: boolean }) { return <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: emphatic ? fontSize.bodyLarge : fontSize.body, fontWeight: emphatic ? 700 : 400 }}><span>{label}</span><span>{money(amount, currency)}</span></div>; }
function Context({ label, value }: { readonly label: string; readonly value: string }) { return <div><dt style={{ color: text.secondary, fontSize: fontSize.caption }}>{label}</dt><dd style={{ margin: 0, fontWeight: 600 }}>{value}</dd></div>; }
function money(amount: string, currency: string) { return `${currency} ${Number(amount).toLocaleString('en-KE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`; }
function message(cause: unknown) { return cause instanceof Error ? cause.message : String(cause); }

const panel = { background: surface.raised, border: `1px solid ${surface.border}`, borderRadius: 14, padding: spacing.lg, alignSelf: 'start' } as const;
const labelStyle = { display: 'grid', gap: 6, marginTop: spacing.md, color: text.secondary, fontSize: fontSize.caption } as const;
const inputStyle = { minHeight: 42, border: `1px solid ${surface.borderStrong}`, borderRadius: 8, padding: '0 10px', fontSize: fontSize.body, background: '#fff' } as const;
const primaryButton = { minHeight: 42, border: 'none', borderRadius: 8, padding: '0 12px', background: '#12854A', color: '#fff', fontWeight: 700, cursor: 'pointer', marginTop: spacing.sm } as const;
const secondaryButton = { minHeight: 40, border: `1px solid ${surface.borderStrong}`, borderRadius: 8, padding: '0 12px', background: '#fff', color: text.primary, fontWeight: 600, cursor: 'pointer', marginTop: spacing.sm } as const;
const dangerButton = { minHeight: 40, border: '1px solid #E6B3A8', borderRadius: 8, padding: '0 12px', background: '#FFF6F4', color: '#A83416', fontWeight: 700, cursor: 'pointer' } as const;
const iconButton = { width: 28, height: 28, border: `1px solid ${surface.borderStrong}`, borderRadius: 6, background: '#fff', cursor: 'pointer', fontWeight: 700 } as const;
const resultButton = { display: 'flex', justifyContent: 'space-between', gap: spacing.sm, textAlign: 'left', padding: spacing.sm, border: `1px solid ${surface.border}`, borderRadius: 8, background: '#fff', cursor: 'pointer' } as const;
