import {
  action,
  autoColumns,
  controlSize,
  deriveRetailPrimaryAction,
  fontSize,
  spacing,
  statusPalette,
  surface,
  text,
  viewportAtMost,
  type ViewportClass,
} from '@dawatrace/shared/design-system/index.js';
import { formatDecimal, formatMoney } from '@dawatrace/shared/money.js';
import {
  PosRetailClient,
  retailCashChangeDue,
  type RetailCatalogueItemDTO,
  type RetailTransactionDTO,
  type RetailTransactionLineDTO,
} from '@dawatrace/shared/retail/index.js';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { resolveShortcut } from '../../state/keyboard.js';
import { useViewport } from '../../state/useViewport.js';
import { RetailReturns } from './RetailReturns.js';

interface RetailWorkspaceProps {
  readonly apiFetch: typeof fetch;
  readonly deviceId: string;
}

/**
 * Native retail workspace.
 *
 * The screen stays intentionally dense: find/scan on the left, an authoritative
 * basket in the centre, and a sticky transaction summary on the right. After a
 * line mutation we rehydrate the complete transaction from the server instead
 * of recalculating totals in the renderer.
 */
export function RetailWorkspace({ apiFetch, deviceId }: RetailWorkspaceProps) {
  const client = useMemo(
    () => new PosRetailClient('/api/pos/retail', { fetcher: apiFetch }),
    [apiFetch],
  );
  const barcodeInput = useRef<HTMLInputElement>(null);
  const searchInput = useRef<HTMLInputElement>(null);
  const [storeId, setStoreId] = useState('');
  const [stores, setStores] = useState<
    readonly { id: string; name: string; location_type: string; status: string }[]
  >([]);
  const [storesLoading, setStoresLoading] = useState(true);
  const [transaction, setTransaction] = useState<RetailTransactionDTO | null>(null);
  const [results, setResults] = useState<readonly RetailCatalogueItemDTO[]>([]);
  const [barcode, setBarcode] = useState('');
  const [search, setSearch] = useState('');
  const [cashReceived, setCashReceived] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void client
      .stores(deviceId)
      .then((loaded) => {
        const sellableStores = loaded.filter(
          (store) =>
            store.status === 'ACTIVE' &&
            ['STORE', 'PHARMACY', 'DISPENSARY'].includes(store.location_type),
        );
        setStores(sellableStores);
        setStoreId((current) => current || sellableStores[0]?.id || '');
      })
      .catch((cause: unknown) => setNotice(message(cause)))
      .finally(() => setStoresLoading(false));
  }, [client, deviceId]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const command = resolveShortcut(event);
      if (command === 'SEARCH_MEDICINE') {
        event.preventDefault();
        searchInput.current?.focus();
      }
      if (command === 'SCAN_FOCUS') {
        event.preventDefault();
        barcodeInput.current?.focus();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const run = useCallback(async (operation: () => Promise<void>) => {
    setBusy(true);
    setNotice('');
    try {
      await operation();
    } catch (cause) {
      setNotice(message(cause));
    } finally {
      setBusy(false);
    }
  }, []);

  const refreshTransaction = useCallback(
    async (transactionId: string) => {
      setTransaction(await client.getTransaction(transactionId));
    },
    [client],
  );

  const startSale = () =>
    void run(async () => {
      if (!storeId) throw new Error('Select an active retail store before starting a sale.');
      setTransaction(await client.createDraft({ device_id: deviceId, store_id: storeId }));
      setResults([]);
      setBarcode('');
      setSearch('');
      setCashReceived('');
      requestAnimationFrame(() => barcodeInput.current?.focus());
    });

  const scan = () =>
    void run(async () => {
      if (!transaction) throw new Error('Start a retail sale before scanning an item.');
      if (!barcode.trim()) throw new Error('Enter or scan a barcode.');
      await client.scan(transaction.id, {
        device_id: deviceId,
        barcode: barcode.trim(),
        quantity: '1.00',
      });
      await refreshTransaction(transaction.id);
      setBarcode('');
      barcodeInput.current?.focus();
    });

  const find = () =>
    void run(async () => {
      if (!storeId) throw new Error('Select an active retail store before searching.');
      if (!search.trim()) {
        setResults([]);
        return;
      }
      setResults(
        await client.search({ device_id: deviceId, store_id: storeId, query: search.trim() }),
      );
    });

  const add = (item: RetailCatalogueItemDTO) =>
    void run(async () => {
      if (!transaction) throw new Error('Start a retail sale before adding an item.');
      await client.addLine(transaction.id, {
        device_id: deviceId,
        sku_id: item.sku_id,
        quantity: '1.00',
      });
      await refreshTransaction(transaction.id);
      barcodeInput.current?.focus();
    });

  const changeQuantity = (line: RetailTransactionLineDTO, increment: number) =>
    void run(async () => {
      if (!transaction) return;
      const next = Math.max(0, Number(line.quantity) + increment);
      if (next === 0) {
        await client.removeLine(transaction.id, { device_id: deviceId, line_id: line.id });
      } else {
        await client.setQuantity(transaction.id, {
          device_id: deviceId,
          line_id: line.id,
          quantity: formatDecimal(next, 2) || '1.00',
        });
      }
      await refreshTransaction(transaction.id);
    });

  const hold = () =>
    void run(async () => {
      if (!transaction) return;
      setTransaction(
        await client.hold(transaction.id, { device_id: deviceId, reason: 'Operator hold' }),
      );
    });

  const resume = () =>
    void run(async () => {
      if (!transaction) return;
      setTransaction(await client.resume(transaction.id, { device_id: deviceId }));
      requestAnimationFrame(() => barcodeInput.current?.focus());
    });

  const cancel = () =>
    void run(async () => {
      if (!transaction) return;
      if (!window.confirm(`Cancel ${transaction.transaction_number}? This cannot be undone.`)) return;
      setTransaction(
        await client.cancel(transaction.id, { device_id: deviceId, reason: 'Cancelled at POS' }),
      );
    });

  const preparePayment = () =>
    void run(async () => {
      if (!transaction) return;
      setTransaction(await client.readyForPayment(transaction.id, { device_id: deviceId }));
    });

  const changeDue = transaction
    ? retailCashChangeDue(transaction.total, cashReceived)
    : null;
  const receipt = transaction?.state === 'COMPLETED' ? transaction.receipt : null;
  const settleCash = () =>
    void run(async () => {
      if (!transaction) throw new Error('Start a sale before taking payment.');
      if (changeDue === null) throw new Error('Enter cash received equal to or greater than the sale total.');
      const settled = await client.settleCash(transaction.id, {
        device_id: deviceId,
        cash_received: cashReceived,
        idempotency_key: `retail-cash-${transaction.id}`,
      });
      setTransaction(settled);
      if (settled.state === 'DRAFT') {
        setCashReceived('');
        setNotice('The price or eligible stock changed. Review the updated basket; no cash or stock was recorded.');
      }
    });

  const primary = deriveRetailPrimaryAction({
    state: transaction?.state ?? null,
    lineCount: transaction?.lines.length ?? 0,
    hasStore: Boolean(storeId),
  });
  const performPrimaryAction = () => {
    if (primary.kind === 'START_SALE') startSale();
    if (primary.kind === 'RESUME_SALE') resume();
    if (primary.kind === 'PREPARE_PAYMENT') preparePayment();
    if (primary.kind === 'SETTLE_CASH') settleCash();
  };
  const viewport = useViewport();

  return (
    <main style={layoutFor(viewport)} aria-label="Retail sale workspace">
      <section style={panel} aria-label="Product search and barcode input">
        <SectionTitle title="Find and add" detail="Scan first, then search the sellable catalogue." />
        <label style={labelStyle}>
          Retail store
          <select
            value={storeId}
            onChange={(event) => setStoreId(event.target.value)}
            disabled={busy || Boolean(transaction)}
            style={inputStyle}
          >
            <option value="">Select store</option>
            {stores.map((store) => (
              <option key={store.id} value={store.id}>
                {store.name} · {store.location_type}
              </option>
            ))}
          </select>
        </label>
        {!storesLoading && stores.length === 0 ? (
          <p role="status" style={{ ...helperText, color: text.secondary, padding: `${spacing.sm}px ${spacing.md}px`, border: `1px solid ${surface.border}`, borderRadius: 8 }}>
            No retail store is available to this register. Ask an HQ manager to verify that its branch has an active STORE, PHARMACY, or DISPENSARY location and that your cashier account is assigned to that branch in People & Access.
          </p>
        ) : null}
        <p style={helperText}>{primary.detail}</p>

        <label style={labelStyle}>
          Barcode
          <input
            ref={barcodeInput}
            value={barcode}
            onChange={(event) => setBarcode(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') scan();
            }}
            disabled={busy || !transaction || transaction.state !== 'DRAFT'}
            placeholder="Scan barcode"
            aria-keyshortcuts="F12"
            style={inputStyle}
          />
        </label>
        <button
          type="button"
          disabled={busy || !transaction || transaction.state !== 'DRAFT' || !barcode.trim()}
          onClick={scan}
          style={secondaryButton}
          title="Add the scanned item"
        >
          Add scanned item
        </button>

        <label style={{ ...labelStyle, marginTop: spacing.lg }}>
          Find item
          <input
            ref={searchInput}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') find();
            }}
            disabled={busy || !storeId}
            placeholder="Name, SKU or barcode"
            aria-keyshortcuts="F2"
            style={inputStyle}
          />
        </label>
        <button type="button" disabled={busy || !storeId} onClick={find} style={secondaryButton}>
          Search catalogue
        </button>
        <div style={resultsStyle} aria-live="polite">
          {results.map((item) => (
            <button
              key={item.sku_id}
              type="button"
              disabled={busy || !transaction || transaction.state !== 'DRAFT' || item.stock_state === 'OUT_OF_STOCK'}
              onClick={() => add(item)}
              style={resultButton}
              title={
                item.stock_state === 'OUT_OF_STOCK'
                  ? 'This item cannot be added because stock is unavailable.'
                  : 'Add this priced catalogue item'
              }
            >
              <span style={resultText}>
                <strong>{item.display_name}</strong>
                <small>
                  {item.sku_code} · {item.available_quantity} {item.unit} ·{' '}
                  {item.stock_state.replace(/_/g, ' ').toLowerCase()}
                </small>
              </span>
              <span style={moneyStyle}>{money(item.unit_price, item.currency)}</span>
            </button>
          ))}
        </div>
      </section>

      <section style={panel} aria-label="Current retail basket">
        <SectionTitle
          title={transaction ? transaction.transaction_number : 'Current basket'}
          detail={
            transaction
              ? `${transaction.register_code} · ${transaction.state.replace(/_/g, ' ').toLowerCase()}`
              : 'Start a sale to open a register-bound basket.'
          }
        />
        <SafetyNote />
        {notice ? <p role="alert" style={noticeStyle}>{notice}</p> : null}
        {!transaction ? (
          <EmptyBasket />
        ) : transaction.lines.length === 0 ? (
          <EmptyBasket />
        ) : (
          <div style={linesStyle}>
            {transaction.lines.map((line) => (
              <RetailLine
                key={line.id}
                line={line}
                editable={!busy && transaction.state === 'DRAFT'}
                onDecrease={() => changeQuantity(line, -1)}
                onIncrease={() => changeQuantity(line, 1)}
              />
            ))}
          </div>
        )}
      </section>

      <aside style={summaryPanel} aria-label="Retail sale summary">
        <SectionTitle title="Sale context" detail="Server-authoritative operational and pricing context." />
        <dl style={contextList}>
          <Context label="Store" value={selectedStoreName(stores, storeId)} />
          <Context label="Register" value={transaction?.register_code ?? 'Opened when sale starts'} />
          <Context label="Sale state" value={transaction?.state.replace(/_/g, ' ') ?? 'No active sale'} />
          <Context
            label="Price source"
            value={transaction?.lines[0]?.price_snapshot.source ?? 'Resolved when an item is added'}
          />
        </dl>
        {transaction ? (
          <div style={totals}>
            <Total label="Subtotal" amount={transaction.subtotal} currency={transaction.currency} />
            <Total label="Discount" amount={transaction.discount_total} currency={transaction.currency} />
            <Total label="Tax" amount={transaction.tax_total} currency={transaction.currency} />
            <Total label="Total" amount={transaction.total} currency={transaction.currency} emphatic />
          </div>
        ) : null}
        {transaction?.state === 'READY_FOR_PAYMENT' ? (
          <section aria-label="Cash payment" style={paymentPanel}>
            <strong>Cash payment</strong>
            <p style={helperText}>Cash only. Card and M-PESA are not enabled for retail checkout.</p>
            <label style={labelStyle}>
              Cash received
              <input
                value={cashReceived}
                onChange={(event) => setCashReceived(event.target.value)}
                inputMode="decimal"
                disabled={busy}
                placeholder="0.00"
                style={inputStyle}
              />
            </label>
            <div style={changeStyle} aria-live="polite">
              {changeDue === null
                ? `Amount due: ${money(transaction.total, transaction.currency)}`
                : `Change due: ${money(changeDue, transaction.currency)}`}
            </div>
          </section>
        ) : null}
        {receipt ? (
          <section aria-label="Internal cash receipt" style={receiptPanel}>
            <strong>Internal receipt · {receipt.receipt_number}</strong>
            {receipt.lines_snapshot.map((line, index) => (
              <div key={`${line.sku_code}-${index}`} style={receiptLine}>
                <span>{line.description}</span>
                <small style={lineMeta}>
                  {line.quantity} {line.unit} × {money(line.unit_price, receipt.currency)}
                </small>
                <strong style={moneyStyle}>{money(line.line_total, receipt.currency)}</strong>
              </div>
            ))}
            <Total label="Cash received" amount={receipt.cash_received} currency={receipt.currency} />
            <Total label="Change returned" amount={receipt.change_due} currency={receipt.currency} />
            <p style={helperText}>
              {receipt.print_job?.transport === 'SIMULATOR'
                ? 'Print job queued for the simulator; no physical print is confirmed.'
                : receipt.print_job
                  ? `Print job: ${receipt.print_job.status.toLowerCase().replace(/_/g, ' ')}.`
                  : 'The internal receipt is saved; its print job could not be queued.'}
            </p>
            <p style={helperText}>{receipt.disclaimer}</p>
          </section>
        ) : null}
        <RetailReturns client={client} deviceId={deviceId} />
        <div style={actions}>
          {transaction?.state === 'DRAFT' ? (
            <button type="button" disabled={busy} onClick={hold} style={secondaryButton}>
              Hold sale
            </button>
          ) : null}
          <button
            type="button"
            disabled={busy || !primary.enabled || (primary.kind === 'SETTLE_CASH' && changeDue === null)}
            onClick={performPrimaryAction}
            style={{ ...primaryButton, ...(busy || !primary.enabled ? disabledButton : {}) }}
            title={primary.detail}
          >
            {primary.label}
          </button>
          {transaction && ['DRAFT', 'HELD', 'READY_FOR_PAYMENT'].includes(transaction.state) ? (
            <button type="button" disabled={busy} onClick={cancel} style={dangerButton}>
              Cancel sale
            </button>
          ) : null}
        </div>
      </aside>
    </main>
  );
}

function RetailLine({
  line,
  editable,
  onDecrease,
  onIncrease,
}: {
  readonly line: RetailTransactionLineDTO;
  readonly editable: boolean;
  readonly onDecrease: () => void;
  readonly onIncrease: () => void;
}) {
  return (
    <article style={lineCard}>
      <div style={lineIdentity}>
        <strong>{line.description_snapshot}</strong>
        <span style={lineMeta}>
          {line.sku_code} · {money(line.unit_price, line.currency)} / {line.unit}
        </span>
        <span style={lineMeta}>
          Stock {line.inventory_context.stock_state.replace(/_/g, ' ').toLowerCase()} · Price{' '}
          {line.price_snapshot.source ?? 'authoritative source'}
        </span>
      </div>
      <div style={lineControls} aria-label={`Quantity for ${line.description_snapshot}`}>
        <button
          type="button"
          aria-label={`Decrease quantity for ${line.description_snapshot}`}
          disabled={!editable}
          onClick={onDecrease}
          style={iconButton}
        >
          −
        </button>
        <span style={quantityStyle}>{line.quantity}</span>
        <button
          type="button"
          aria-label={`Increase quantity for ${line.description_snapshot}`}
          disabled={!editable}
          onClick={onIncrease}
          style={iconButton}
        >
          +
        </button>
      </div>
      <strong style={moneyStyle}>{money(line.line_total, line.currency)}</strong>
    </article>
  );
}

function SafetyNote() {
  const palette = statusPalette.ACTION_REQUIRED;
  return (
    <p
      style={{
        margin: `${spacing.md}px 0 0`,
        padding: spacing.sm,
        borderLeft: `3px solid ${palette.accent}`,
        background: palette.surface,
        color: palette.foreground,
        fontSize: fontSize.caption,
        lineHeight: 1.4,
      }}
    >
      Prescription medicines must be processed through the prescription workspace. Retail
      medicine screening is not available in this pilot.
    </p>
  );
}

function SectionTitle({ title, detail }: { readonly title: string; readonly detail: string }) {
  return (
    <div>
      <h2 style={{ margin: 0, fontSize: fontSize.sectionTitle }}>{title}</h2>
      <p style={{ margin: '4px 0 0', color: text.secondary, fontSize: fontSize.caption }}>
        {detail}
      </p>
    </div>
  );
}

function EmptyBasket() {
  return (
    <div style={emptyState}>
      <strong>No items are in this sale.</strong>
      <span>Scan a barcode or search for a priced, sellable item.</span>
    </div>
  );
}

function Total({
  label,
  amount,
  currency,
  emphatic = false,
}: {
  readonly label: string;
  readonly amount: string;
  readonly currency: string;
  readonly emphatic?: boolean;
}) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: spacing.md }}>
      <span style={{ fontWeight: emphatic ? 700 : 400 }}>{label}</span>
      <span style={{ ...moneyStyle, fontSize: emphatic ? fontSize.sectionTitle : fontSize.body }}>
        {money(amount, currency)}
      </span>
    </div>
  );
}

function Context({ label, value }: { readonly label: string; readonly value: string }) {
  return (
    <div>
      <dt style={contextLabel}>{label}</dt>
      <dd style={contextValue} title={value}>
        {value}
      </dd>
    </div>
  );
}

function selectedStoreName(
  stores: readonly { id: string; name: string }[],
  storeId: string,
): string {
  return stores.find((store) => store.id === storeId)?.name ?? 'Select an active store';
}

function money(amount: string, currency: string) {
  return formatMoney(amount, currency);
}

function message(cause: unknown) {
  return cause instanceof Error ? cause.message : String(cause);
}

/**
 * Search, basket and totals.
 *
 * The three panes only sit side by side once all three can hold their content;
 * below that they reflow, and the panes fall in the order the operator works
 * in -- find the item, check the basket, then settle.
 */
function layoutFor(viewport: ViewportClass) {
  return {
    display: 'grid',
    gridTemplateColumns: viewportAtMost(viewport, 'expanded')
      ? autoColumns(300)
      : 'minmax(270px, 0.8fr) minmax(440px, 1.45fr) minmax(300px, 0.9fr)',
    gap: spacing.lg,
    padding: viewportAtMost(viewport, 'compact') ? spacing.md : spacing.xl,
    overflow: 'auto',
  } as const;
}
const panel = {
  background: surface.raised,
  border: `1px solid ${surface.border}`,
  borderRadius: 14,
  padding: spacing.lg,
  alignSelf: 'start',
} as const;
const summaryPanel = {
  ...panel,
  position: 'sticky',
  top: spacing.lg,
} as const;
const labelStyle = {
  display: 'grid',
  gap: spacing.xs,
  marginTop: spacing.md,
  color: text.secondary,
  fontSize: fontSize.caption,
  fontWeight: 600,
} as const;
const inputStyle = {
  minHeight: controlSize.desktopHeightLarge,
  border: `1px solid ${surface.borderStrong}`,
  borderRadius: 8,
  padding: '0 10px',
  fontSize: fontSize.body,
  background: surface.raised,
  color: text.primary,
} as const;
const primaryButton = {
  minHeight: controlSize.desktopHeightLarge,
  border: 'none',
  borderRadius: 8,
  padding: '0 12px',
  background: action.primary,
  color: action.primaryForeground,
  fontWeight: 700,
  cursor: 'pointer',
} as const;
const secondaryButton = {
  minHeight: controlSize.desktopHeight,
  border: `1px solid ${action.secondaryBorder}`,
  borderRadius: 8,
  padding: '0 12px',
  background: action.secondary,
  color: text.primary,
  fontWeight: 600,
  cursor: 'pointer',
  marginTop: spacing.sm,
} as const;
const disabledButton = {
  background: action.disabled,
  color: action.disabledForeground,
  cursor: 'not-allowed',
} as const;
const dangerButton = {
  minHeight: controlSize.desktopHeight,
  border: `1px solid ${action.dangerBorder}`,
  borderRadius: 8,
  padding: '0 12px',
  background: action.dangerSurface,
  color: action.danger,
  fontWeight: 700,
  cursor: 'pointer',
} as const;
const iconButton = {
  width: controlSize.desktopHeight,
  height: controlSize.desktopHeight,
  border: `1px solid ${action.secondaryBorder}`,
  borderRadius: 8,
  background: action.secondary,
  color: text.primary,
  cursor: 'pointer',
  fontWeight: 700,
  fontSize: fontSize.bodyLarge,
} as const;
const resultsStyle = { display: 'grid', gap: spacing.xs, marginTop: spacing.md } as const;
const resultButton = {
  display: 'flex',
  justifyContent: 'space-between',
  gap: spacing.sm,
  textAlign: 'left',
  padding: spacing.sm,
  border: `1px solid ${surface.border}`,
  borderRadius: 8,
  background: surface.raised,
  color: text.primary,
  cursor: 'pointer',
} as const;
const resultText = { display: 'grid', gap: 2 } as const;
const linesStyle = { display: 'grid', gap: spacing.sm, marginTop: spacing.md } as const;
const lineCard = {
  display: 'grid',
  gridTemplateColumns: 'minmax(0, 1fr) auto auto',
  alignItems: 'center',
  gap: spacing.md,
  padding: spacing.md,
  border: `1px solid ${surface.border}`,
  borderRadius: 10,
} as const;
const lineIdentity = { display: 'grid', gap: 3, minWidth: 0 } as const;
const lineMeta = { color: text.secondary, fontSize: fontSize.caption } as const;
const lineControls = { display: 'flex', gap: spacing.xs, alignItems: 'center' } as const;
const quantityStyle = {
  minWidth: 44,
  textAlign: 'center',
  fontVariantNumeric: 'tabular-nums',
  fontWeight: 700,
} as const;
const moneyStyle = { fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' } as const;
const contextList = { display: 'grid', gap: spacing.md, margin: `${spacing.lg}px 0 0` } as const;
const contextLabel = {
  color: text.tertiary,
  fontSize: fontSize.meta,
  textTransform: 'uppercase',
  letterSpacing: 0.5,
} as const;
const contextValue = {
  margin: '2px 0 0',
  color: text.primary,
  fontWeight: 600,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
} as const;
const totals = {
  display: 'grid',
  gap: spacing.sm,
  marginTop: spacing.xl,
  paddingTop: spacing.md,
  borderTop: `1px solid ${surface.border}`,
} as const;
const paymentPanel = {
  display: 'grid',
  gap: spacing.xs,
  marginTop: spacing.lg,
  padding: spacing.md,
  border: `1px solid ${statusPalette.PROCESSING.border}`,
  borderRadius: 10,
  background: statusPalette.PROCESSING.surface,
} as const;
const receiptPanel = {
  display: 'grid',
  gap: spacing.sm,
  marginTop: spacing.lg,
  padding: spacing.md,
  border: `1px solid ${surface.border}`,
  borderRadius: 10,
  background: surface.page,
} as const;
const receiptLine = {
  display: 'grid',
  gridTemplateColumns: 'minmax(0, 1fr) auto',
  gap: spacing.xs,
  paddingTop: spacing.xs,
  borderTop: `1px solid ${surface.border}`,
} as const;
const changeStyle = { fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: text.primary } as const;
const actions = { display: 'grid', gap: spacing.sm, marginTop: spacing.xl } as const;
const helperText = { margin: `${spacing.sm}px 0 0`, color: text.secondary, fontSize: fontSize.caption } as const;
const noticeStyle = {
  margin: `${spacing.md}px 0 0`,
  padding: spacing.sm,
  borderLeft: `3px solid ${statusPalette.BLOCKING.accent}`,
  background: statusPalette.BLOCKING.surface,
  color: statusPalette.BLOCKING.foreground,
  fontWeight: 600,
} as const;
const emptyState = {
  display: 'grid',
  gap: spacing.xs,
  marginTop: spacing.xl,
  padding: spacing.lg,
  border: `1px dashed ${surface.borderStrong}`,
  borderRadius: 10,
  color: text.secondary,
} as const;
