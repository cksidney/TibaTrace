import { useEffect, useMemo, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';

import {
  formatMoney,
  HQApiError,
  loadProcurementData,
  procurementCommand,
} from './api.js';
import type {
  HQOverview,
  ProcurementBatch,
  ProcurementData,
  ProcurementReceipt,
  ProcurementSupplier,
} from './api.js';
import { Icon } from './icons.js';

interface ProcurementWorkspaceProps {
  readonly csrfToken: string;
  readonly overview: HQOverview;
}

type ProcurementTab =
  | 'suppliers'
  | 'requisitions'
  | 'orders'
  | 'receiving'
  | 'quality'
  | 'reconciliation';

type DialogMode =
  | {
    readonly kind: 'confirm';
    readonly confirmation: string;
    readonly message: string;
    readonly path: string;
    readonly payload: unknown;
    readonly record: string;
    readonly submitLabel: string;
    readonly title: string;
  }
  | { readonly kind: 'supplier' }
  | { readonly kind: 'qualification'; readonly supplier: ProcurementSupplier }
  | { readonly kind: 'suspend-supplier'; readonly supplier: ProcurementSupplier }
  | { readonly kind: 'requisition' }
  | { readonly kind: 'order' }
  | { readonly kind: 'receipt' }
  | { readonly kind: 'receive-batch'; readonly receipt: ProcurementReceipt }
  | { readonly kind: 'inspection'; readonly receipt: ProcurementReceipt }
  | { readonly kind: 'release'; readonly batch: ProcurementBatch }
  | { readonly kind: 'return' }
  | { readonly kind: 'match' }
  | null;

interface DraftLine {
  readonly id: string;
  readonly quantity: string;
  readonly referenceId: string;
  readonly requiresColdChain: boolean;
  readonly unitCost: string;
}

const procurementTabs: readonly { readonly key: ProcurementTab; readonly label: string }[] = [
  { key: 'suppliers', label: 'Suppliers' },
  { key: 'requisitions', label: 'Requisitions' },
  { key: 'orders', label: 'Purchase orders' },
  { key: 'receiving', label: 'Receiving' },
  { key: 'quality', label: 'Quality release' },
  { key: 'reconciliation', label: 'Returns & matching' },
];

export function ProcurementWorkspace({
  csrfToken,
  overview,
}: ProcurementWorkspaceProps) {
  const selectableTenants = overview.network_items.filter((item) => item.status === 'ACTIVE');
  const [tenantId, setTenantId] = useState(
    overview.tenant_id || selectableTenants[0]?.id || '',
  );
  const [data, setData] = useState<ProcurementData | null>(null);
  const [failed, setFailed] = useState(false);
  const [tab, setTab] = useState<ProcurementTab>('suppliers');
  const [dialog, setDialog] = useState<DialogMode>(null);
  const [notice, setNotice] = useState('');

  const reload = async (signal?: AbortSignal) => {
    if (!tenantId) return;
    setFailed(false);
    try {
      setData(await loadProcurementData(tenantId, signal));
    } catch {
      if (!signal?.aborted) setFailed(true);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    void reload(controller.signal);
    return () => controller.abort();
  }, [tenantId]);

  const metrics = useMemo(() => ({
    approvedSuppliers: data?.suppliers.filter((item) => ['APPROVED', 'ACTIVE'].includes(item.status)).length ?? 0,
    purchaseReadySuppliers: data?.suppliers.filter((item) => item.purchase_eligible).length ?? 0,
    heldBatches: data?.batches.filter((item) => item.quality_status !== 'RELEASED').length ?? 0,
    openOrders: data?.orders.filter((item) => !['CLOSED', 'CANCELLED', 'FULLY_RECEIVED'].includes(item.status)).length ?? 0,
    pendingRequisitions: data?.requisitions.filter((item) => ['DRAFT', 'SUBMITTED', 'UNDER_REVIEW', 'APPROVED', 'PARTIALLY_ORDERED'].includes(item.status)).length ?? 0,
    matchedInvoices: data?.matches.filter((item) => item.matching_status === 'MATCHED').length ?? 0,
    releasedBatches: data?.batches.filter((item) => item.quality_status === 'RELEASED').length ?? 0,
  }), [data]);

  const journey = useMemo(() => ([
    {
      step: '01',
      title: 'Qualify',
      detail: 'Verify supplier licences before an order can be raised.',
      tab: 'suppliers' as ProcurementTab,
      done: metrics.purchaseReadySuppliers > 0,
    },
    {
      step: '02',
      title: 'Approve demand',
      detail: 'Separate requesting from approval before funds are committed.',
      tab: 'requisitions' as ProcurementTab,
      done: (data?.requisitions.some((item) => ['APPROVED', 'PARTIALLY_ORDERED', 'FULLY_ORDERED', 'CLOSED'].includes(item.status)) ?? false),
    },
    {
      step: '03',
      title: 'Order',
      detail: 'Price every line and release only an approved purchase order.',
      tab: 'orders' as ProcurementTab,
      done: (data?.orders.some((item) => ['SENT', 'PARTIALLY_RECEIVED', 'FULLY_RECEIVED', 'CLOSED'].includes(item.status)) ?? false),
    },
    {
      step: '04',
      title: 'Receive & inspect',
      detail: 'Capture delivery note, batch, expiry, quality decision, and custody.',
      tab: 'receiving' as ProcurementTab,
      done: metrics.releasedBatches > 0 || (data?.receipts.some((item) => ['ACCEPTED', 'CLOSED', 'UNDER_INSPECTION'].includes(item.status)) ?? false),
    },
    {
      step: '05',
      title: 'Reconcile',
      detail: 'Match purchase order, accepted receipt, and supplier invoice.',
      tab: 'reconciliation' as ProcurementTab,
      done: metrics.matchedInvoices > 0,
    },
  ]), [data, metrics.matchedInvoices, metrics.purchaseReadySuppliers, metrics.releasedBatches]);

  if (!tenantId) {
    return (
      <article className="panel procurement-empty">
        <Icon name="building" />
        <h2>No active tenant workspace</h2>
        <p>Create or activate a tenant before starting procurement.</p>
      </article>
    );
  }

  return (
    <>
      <section className="procurement-scope panel">
        <div>
          <p className="eyebrow">Procure-to-stock control</p>
          <h2>Procurement cockpit</h2>
          <span>Supplier qualification, internal demand, purchasing, receiving, quality release, returns, and invoice matching in one governed flow.</span>
        </div>
        {overview.is_platform_overview ? (
          <label>
            <span>Operating tenant</span>
            <select onChange={(event) => setTenantId(event.target.value)} value={tenantId}>
              {selectableTenants.map((tenant) => (
                <option key={tenant.id} value={tenant.id}>{tenant.name}</option>
              ))}
            </select>
          </label>
        ) : null}
      </section>

      <section className="metric-grid network-metrics" aria-label="Procurement totals">
        <ProcurementMetric
          detail={`${metrics.approvedSuppliers} commercially approved`}
          icon="building"
          label="Purchase-ready suppliers"
          onActivate={() => setTab('suppliers')}
          value={metrics.purchaseReadySuppliers}
        />
        <ProcurementMetric
          detail="Demand awaiting completion"
          icon="docs"
          label="Open requisitions"
          onActivate={() => setTab('requisitions')}
          value={metrics.pendingRequisitions}
        />
        <ProcurementMetric
          detail="Commitments not fully received"
          icon="store"
          label="Open orders"
          onActivate={() => setTab('orders')}
          value={metrics.openOrders}
        />
        <ProcurementMetric
          detail="Batches outside released state"
          icon="alert"
          label="Quality holds"
          onActivate={() => setTab('quality')}
          value={metrics.heldBatches}
        />
      </section>

      <article className="panel procurement-workspace">
        <div className="procurement-tabs" role="tablist">
          {procurementTabs.map((item) => (
            <button
              aria-selected={tab === item.key}
              className={tab === item.key ? 'active' : ''}
              key={item.key}
              onClick={() => setTab(item.key)}
              role="tab"
              type="button"
            >
              {item.label}
              <b>{tabCount(item.key, data)}</b>
            </button>
          ))}
        </div>

        {notice ? <div className="procurement-notice" role="status"><Icon name="activity" /> {notice}</div> : null}
        {failed ? (
          <div className="inline-alert" role="alert"><Icon name="alert" /> Procurement data could not be loaded for this tenant.</div>
        ) : !data ? (
          <div className="procurement-loading"><Icon className="spin" name="refresh" /> Loading procurement workspace…</div>
        ) : (
          <>
            {tab === 'suppliers' ? (
              <SuppliersTab
                data={data}
                onDialog={setDialog}
              />
            ) : null}
            {tab === 'requisitions' ? (
              <RequisitionsTab
                data={data}
                onDialog={setDialog}
              />
            ) : null}
            {tab === 'orders' ? (
              <OrdersTab
                data={data}
                onDialog={setDialog}
              />
            ) : null}
            {tab === 'receiving' ? (
              <ReceivingTab
                data={data}
                onDialog={setDialog}
              />
            ) : null}
            {tab === 'quality' ? <QualityTab data={data} onDialog={setDialog} /> : null}
            {tab === 'reconciliation' ? (
              <ReconciliationTab
                data={data}
                onDialog={setDialog}
              />
            ) : null}
          </>
        )}
      </article>

      <section className="procurement-flow" aria-label="Procurement control flow">
        {journey.map((item) => (
          <button
            aria-label={`Open ${item.title} workspace`}
            className={item.done ? 'procurement-flow-step is-complete' : 'procurement-flow-step'}
            key={item.step}
            onClick={() => setTab(item.tab)}
            type="button"
          >
            <b>{item.step}</b>
            <strong>{item.title}</strong>
            <span>{item.detail}</span>
            <em>{item.done ? 'Complete in this tenant' : 'Awaiting activity'}</em>
          </button>
        ))}
      </section>

      {metrics.releasedBatches > 0 ? (
        <p className="procurement-inventory-link">
          Released batches post to the stock ledger.
          {' '}
          <a href="#inventory">Open Inventory Control</a>
          {' '}
          to verify balances after quality release.
        </p>
      ) : null}

      {dialog && data ? (
        <ProcurementDialog
          csrfToken={csrfToken}
          data={data}
          dialog={dialog}
          onClose={() => setDialog(null)}
          onSaved={async (message) => {
            setDialog(null);
            setNotice(message);
            await reload();
          }}
          tenantId={tenantId}
        />
      ) : null}
    </>
  );
}

function SuppliersTab({
  data,
  onDialog,
}: ProcurementTabProps) {
  return (
    <section className="procurement-section">
      <ProcurementHeader
        action="Register supplier"
        eyebrow="Counterparty governance"
        onAction={() => onDialog({ kind: 'supplier' })}
        title="Supplier register"
      />
      {data.suppliers.length ? (
        <>
          <div className="table-scroll">
            <table>
              <thead><tr><th>Supplier</th><th>Status</th><th>Risk</th><th>Qualifications</th><th>Terms</th><th>Actions</th></tr></thead>
              <tbody>
                {data.suppliers.map((supplier) => {
                  const qualifications = data.qualifications.filter((item) => item.supplier === supplier.id);
                  const verified = qualifications.filter((item) => item.verification_status === 'VERIFIED').length;
                  return (
                    <tr key={supplier.id}>
                      <td><strong>{supplier.legal_name}</strong><small className="tenant-slug">{supplier.supplier_code}</small></td>
                      <td><ProcurementStatus value={supplier.status} /></td>
                      <td>{titleCase(supplier.risk_category)}</td>
                      <td>
                        <strong>{verified}/{qualifications.length}</strong>
                        <small className="tenant-slug">verified/current</small>
                        <span
                          className={`supplier-readiness ${supplier.purchase_eligible ? 'ready' : 'blocked'}`}
                          title={supplier.eligibility_reasons.join(' ')}
                        >
                          {supplier.purchase_eligible ? 'Purchase ready' : 'Purchase blocked'}
                        </span>
                      </td>
                      <td><small>{supplier.payment_terms} · {supplier.default_currency}</small></td>
                      <td>
                        <div className="tenant-row-actions">
                          <button onClick={() => onDialog({ kind: 'qualification', supplier })} type="button">Add licence</button>
                          {supplier.status === 'PROSPECTIVE' || supplier.status === 'UNDER_REVIEW' ? (
                            <button onClick={() => onDialog(confirmationDialog({
                              confirmation: 'Approving this supplier permits new purchase orders once its required qualifications are current and verified.',
                              message: `${supplier.legal_name} approved.`,
                              path: `/api/procurement/suppliers/${supplier.id}/approve/`,
                              payload: { reason: 'Approved in HQ procurement workspace' },
                              record: supplier.legal_name,
                              submitLabel: 'Approve supplier',
                              title: 'Approve supplier',
                            }))} type="button">Approve</button>
                          ) : null}
                          {['APPROVED', 'ACTIVE'].includes(supplier.status) ? (
                            <button className="danger-link" onClick={() => onDialog({ kind: 'suspend-supplier', supplier })} type="button">Suspend</button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {data.qualifications.some((item) => item.verification_status === 'PENDING') ? (
            <div className="qualification-queue">
              <div><p>Compliance review</p><h3>Qualifications awaiting verification</h3></div>
              {data.qualifications.filter((item) => item.verification_status === 'PENDING').map((qualification) => (
                <div className="qualification-row" key={qualification.id}>
                  <div>
                    <strong>{qualification.supplier_code} · {titleCase(qualification.qualification_type)}</strong>
                    <small>{qualification.licence_number} · expires {formatDate(qualification.expiry_date)}</small>
                  </div>
                  <button
                    className="business-action"
                    onClick={() => onDialog(confirmationDialog({
                      confirmation: 'Verification marks this supplier evidence as current and makes it eligible for procurement controls.',
                      message: `${qualification.licence_number} verified.`,
                      path: `/api/procurement/supplier-qualifications/${qualification.id}/verify/`,
                      payload: {},
                      record: `${qualification.supplier_code} · ${qualification.licence_number}`,
                      submitLabel: 'Verify qualification',
                      title: 'Verify supplier qualification',
                    }))}
                    type="button"
                  >
                    Verify
                  </button>
                </div>
              ))}
            </div>
          ) : null}
        </>
      ) : <ProcurementEmpty icon="building" title="No suppliers registered" detail="Register a supplier, capture its licences, verify them, then approve the counterparty." />}
    </section>
  );
}

function RequisitionsTab({
  data,
  onDialog,
}: ProcurementTabProps) {
  return (
    <section className="procurement-section">
      <ProcurementHeader action="New requisition" eyebrow="Internal demand" onAction={() => onDialog({ kind: 'requisition' })} title="Purchase requisitions" />
      {data.requisitions.length ? (
        <div className="procurement-record-grid">
          {data.requisitions.map((requisition) => (
            <ProcurementRecord
              actions={
                <>
                  {requisition.status === 'DRAFT' ? <button onClick={() => onDialog(confirmationDialog({
                    confirmation: 'Submitting locks the demand request for review and starts the approval workflow.',
                    message: `${requisition.requisition_number} submitted.`,
                    path: `/api/procurement/requisitions/${requisition.id}/submit/`,
                    payload: {},
                    record: requisition.requisition_number,
                    submitLabel: 'Submit requisition',
                    title: 'Submit purchase requisition',
                  }))} type="button">Submit</button> : null}
                  {['SUBMITTED', 'UNDER_REVIEW'].includes(requisition.status) ? <button onClick={() => onDialog(confirmationDialog({
                    confirmation: 'Approval makes this demand available for purchasing. Confirm the quantities, priority and required-by date are correct.',
                    message: `${requisition.requisition_number} approved.`,
                    path: `/api/procurement/requisitions/${requisition.id}/approve/`,
                    payload: {},
                    record: requisition.requisition_number,
                    submitLabel: 'Approve requisition',
                    title: 'Approve purchase requisition',
                  }))} type="button">Approve</button> : null}
                </>
              }
              detail={`${requisition.requesting_branch_name} · Needed ${formatDate(requisition.requested_delivery_date)}`}
              key={requisition.id}
              metrics={[
                ['Priority', titleCase(requisition.priority)],
                ['Lines', String(requisition.lines.length)],
                ['Outstanding', String(requisition.lines.reduce((total, line) => total + line.outstanding_quantity, 0))],
              ]}
              reference={requisition.requisition_number}
              status={requisition.status}
              title={requisition.justification || `Internal demand for ${requisition.requesting_branch_name}`}
            />
          ))}
        </div>
      ) : <ProcurementEmpty icon="docs" title="No purchase requisitions" detail="Create internal demand with required-by dates and item quantities." />}
    </section>
  );
}

function OrdersTab({
  data,
  onDialog,
}: ProcurementTabProps) {
  return (
    <section className="procurement-section">
      <ProcurementHeader action="Raise purchase order" eyebrow="Commercial commitments" onAction={() => onDialog({ kind: 'order' })} title="Purchase orders" />
      {data.orders.length ? (
        <div className="procurement-record-grid">
          {data.orders.map((order) => (
            <ProcurementRecord
              actions={
                <>
                  {order.status === 'DRAFT' ? <button onClick={() => onDialog(confirmationDialog({
                    confirmation: 'Approval commits this purchase order for supplier transmission. Check commercial terms and expected delivery first.',
                    message: `${order.po_number} approved.`,
                    path: `/api/procurement/purchase-orders/${order.id}/approve/`,
                    payload: {},
                    record: order.po_number,
                    submitLabel: 'Approve purchase order',
                    title: 'Approve purchase order',
                  }))} type="button">Approve</button> : null}
                  {order.status === 'APPROVED' ? <button onClick={() => onDialog(confirmationDialog({
                    confirmation: 'Sending records the supplier release. The order will enter the delivery and receiving workflow.',
                    message: `${order.po_number} released to supplier.`,
                    path: `/api/procurement/purchase-orders/${order.id}/send/`,
                    payload: {},
                    record: order.po_number,
                    submitLabel: 'Send to supplier',
                    title: 'Release purchase order',
                  }))} type="button">Send to supplier</button> : null}
                </>
              }
              detail={`${order.supplier_name} · Expected ${formatDate(order.expected_delivery_date)}`}
              key={order.id}
              metrics={[
                ['Gross', formatMoney(order.total_gross, order.currency)],
                ['Lines', String(order.lines.length)],
                ['Received', `${order.lines.reduce((total, line) => total + line.received_quantity, 0)}/${order.lines.reduce((total, line) => total + line.ordered_quantity, 0)}`],
              ]}
              reference={order.po_number}
              status={order.status}
              title={order.supplier_name}
            />
          ))}
        </div>
      ) : <ProcurementEmpty icon="store" title="No purchase orders" detail="Raise an order from approved demand or create a priced direct order." />}
    </section>
  );
}

function ReceivingTab({
  data,
  onDialog,
}: ProcurementTabProps) {
  return (
    <section className="procurement-section">
      <ProcurementHeader action="Open goods receipt" eyebrow="Inbound custody" onAction={() => onDialog({ kind: 'receipt' })} title="Goods receipts" />
      {data.receipts.length ? (
        <div className="table-scroll">
          <table>
            <thead><tr><th>Receipt</th><th>Purchase order</th><th>Delivery note</th><th>Status</th><th>Lines</th><th>Actions</th></tr></thead>
            <tbody>
              {data.receipts.map((receipt) => (
                <tr key={receipt.id}>
                  <td><strong>{receipt.grn_number}</strong><small className="tenant-slug">{formatDateTime(receipt.arrival_time)}</small></td>
                  <td><code>{orderReference(data, receipt.purchase_order)}</code></td>
                  <td>{receipt.delivery_note_number}</td>
                  <td><ProcurementStatus value={receipt.status} /></td>
                  <td>{receipt.lines.length}</td>
                  <td>
                    <div className="tenant-row-actions">
                      {!['ACCEPTED', 'CLOSED', 'CANCELLED'].includes(receipt.status) ? <button onClick={() => onDialog({ kind: 'receive-batch', receipt })} type="button">Receive batch</button> : null}
                      {!['ACCEPTED', 'CLOSED', 'CANCELLED'].includes(receipt.status) ? <button onClick={() => onDialog({ kind: 'inspection', receipt })} type="button">Inspect</button> : null}
                      {!['ACCEPTED', 'CLOSED', 'CANCELLED'].includes(receipt.status) ? <button onClick={() => onDialog(confirmationDialog({
                        confirmation: 'Closing freezes delivery capture and receipt totals. Inspect all received batches before confirming.',
                        message: `${receipt.grn_number} closed.`,
                        path: `/api/procurement/goods-receipts/${receipt.id}/close/`,
                        payload: {},
                        record: receipt.grn_number,
                        submitLabel: 'Close goods receipt',
                        title: 'Close goods receipt',
                      }))} type="button">Close</button> : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <ProcurementEmpty icon="inventory" title="No goods receipts" detail="Open a receipt against a sent purchase order when a delivery reaches the receiving bay." />}
    </section>
  );
}

function QualityTab({
  data,
  onDialog,
}: Pick<ProcurementTabProps, 'data' | 'onDialog'>) {
  return (
    <section className="procurement-section">
      <ProcurementHeader eyebrow="Batch disposition" title="Quality-release queue" />
      {data.batches.length ? (
        <div className="table-scroll">
          <table>
            <thead><tr><th>Batch</th><th>SKU</th><th>Expiry</th><th>Received</th><th>Accepted</th><th>Held</th><th>Status</th><th>Action</th></tr></thead>
            <tbody>
              {data.batches.map((batch) => (
                <tr key={batch.id}>
                  <td><strong>{batch.manufacturer_batch_number}</strong></td>
                  <td><code>{batch.sku_code}</code></td>
                  <td>{formatDate(batch.expiry_date)}</td>
                  <td>{batch.received_quantity}</td>
                  <td>{batch.accepted_quantity}</td>
                  <td>{batch.quarantined_quantity}</td>
                  <td><ProcurementStatus value={batch.quality_status} /></td>
                  <td>{batch.quality_status !== 'RELEASED' ? <button className="business-action" onClick={() => onDialog({ kind: 'release', batch })} type="button">Release to stock</button> : <span className="muted-cell">Posted</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <ProcurementEmpty icon="shield" title="No received batches" detail="Batch and expiry records appear here after items are counted against a goods receipt." />}
    </section>
  );
}

function ReconciliationTab({
  data,
  onDialog,
}: ProcurementTabProps) {
  return (
    <section className="procurement-section">
      <div className="reconciliation-head">
        <ProcurementHeader eyebrow="Financial & supplier control" title="Returns and three-way matching" />
        <div>
          <button className="secondary-button" onClick={() => onDialog({ kind: 'return' })} type="button"><Icon name="refresh" /> New return</button>
          <button className="primary-button" onClick={() => onDialog({ kind: 'match' })} type="button"><Icon name="check" /> Match invoice</button>
        </div>
      </div>
      <div className="procurement-split">
        <div>
          <h3>Supplier returns</h3>
          {data.returns.length ? data.returns.map((item) => (
            <div className="reconciliation-row" key={item.id}>
              <div><code>{item.return_number}</code><strong>{item.reason}</strong><small>{item.lines.length} line(s)</small></div>
              <ProcurementStatus value={item.status} />
              <div className="tenant-row-actions">
                {item.status === 'REQUESTED' ? <button onClick={() => onDialog(confirmationDialog({
                  confirmation: 'Approval authorises the return against the supplier and preserves the linked receipt evidence.',
                  message: `${item.return_number} approved.`,
                  path: `/api/procurement/supplier-returns/${item.id}/approve/`,
                  payload: {},
                  record: item.return_number,
                  submitLabel: 'Approve return',
                  title: 'Approve supplier return',
                }))} type="button">Approve</button> : null}
                {item.status === 'APPROVED' ? <button onClick={() => onDialog(confirmationDialog({
                  confirmation: 'Dispatch records that the controlled return has left the receiving location.',
                  message: `${item.return_number} dispatched.`,
                  path: `/api/procurement/supplier-returns/${item.id}/dispatch/`,
                  payload: {},
                  record: item.return_number,
                  submitLabel: 'Dispatch return',
                  title: 'Dispatch supplier return',
                }))} type="button">Dispatch</button> : null}
              </div>
            </div>
          )) : <span className="muted-cell">No supplier returns.</span>}
        </div>
        <div>
          <h3>Invoice matches</h3>
          {data.matches.length ? data.matches.map((item) => (
            <div className="reconciliation-row" key={item.id}>
              <div><code>{item.invoice_reference}</code><strong>{orderReference(data, item.purchase_order)}</strong><small>Price variance {formatMoney(item.price_variance)}</small></div>
              <ProcurementStatus value={item.matching_status} />
            </div>
          )) : <span className="muted-cell">No supplier invoices matched.</span>}
        </div>
      </div>
    </section>
  );
}

interface ProcurementTabProps {
  readonly data: ProcurementData;
  readonly onDialog: (dialog: Exclude<DialogMode, null>) => void;
}

function ProcurementDialog({
  csrfToken,
  data,
  dialog,
  onClose,
  onSaved,
  tenantId,
}: {
  readonly csrfToken: string;
  readonly data: ProcurementData;
  readonly dialog: Exclude<DialogMode, null>;
  readonly onClose: () => void;
  readonly onSaved: (message: string) => Promise<void>;
  readonly tenantId: string;
}) {
  const [values, setValues] = useState<Record<string, string>>(() => dialogDefaults(dialog, data));
  const [lines, setLines] = useState<readonly DraftLine[]>([emptyLine()]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const setValue = (name: string, value: string) => {
    setValues((current) => ({ ...current, [name]: value }));
    if (dialog.kind === 'order' && name === 'originating_requisition') {
      const requisition = data.requisitions.find((item) => item.id === value);
      setLines(requisition?.lines.map((line) => ({
        id: crypto.randomUUID(),
        quantity: String(line.outstanding_quantity || line.requested_quantity),
        referenceId: line.id,
        requiresColdChain: false,
        unitCost: '',
      })) ?? [emptyLine()]);
    }
  };

  const updateLine = (id: string, patch: Partial<DraftLine>) => {
    setLines((current) => current.map((line) => line.id === id ? { ...line, ...patch } : line));
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const { path, payload, message } = dialog.kind === 'confirm'
        ? dialog
        : dialogRequest(dialog, values, lines, data);
      await procurementCommand(path, payload, tenantId, csrfToken);
      await onSaved(message);
    } catch (caught) {
      setError(caught instanceof HQApiError ? caught.message : 'The procurement record could not be saved.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="business-dialog-backdrop" role="presentation">
      <section aria-modal="true" className="business-dialog procurement-dialog" role="dialog">
        <header>
          <div><p className="eyebrow">Procurement workflow</p><h2>{dialogTitle(dialog)}</h2></div>
          <button aria-label="Close dialog" onClick={onClose} type="button"><Icon name="close" /></button>
        </header>
        <form onSubmit={(event) => void submit(event)}>
          {dialog.kind === 'confirm' ? (
            <>
              <div className="business-dialog-record"><div><code>Governed transition</code><strong>{dialog.record}</strong></div></div>
              <p className="business-dialog-confirm"><Icon name="shield" /> {dialog.confirmation}</p>
            </>
          ) : <DialogFields data={data} dialog={dialog} lines={lines} setValue={setValue} updateLine={updateLine} values={values} />}
          {supportsLines(dialog) ? (
            <div className="procurement-line-editor">
              <div><strong>Document lines</strong>{dialog.kind === 'order' && values.originating_requisition ? <small>Approved requisition quantities</small> : null}</div>
              {lines.map((line, index) => (
                <div className="procurement-line" key={line.id}>
                  <span>{index + 1}</span>
                  <select
                    disabled={dialog.kind === 'order' && Boolean(values.originating_requisition)}
                    onChange={(event) => updateLine(line.id, { referenceId: event.target.value })}
                    required
                    value={line.referenceId}
                  >
                    <option value="">Select item</option>
                    {(dialog.kind === 'order' && values.originating_requisition
                      ? data.requisitions.find((item) => item.id === values.originating_requisition)?.lines ?? []
                      : data.skus
                    ).map((item) => (
                      <option key={item.id} value={item.id}>
                        {`${item.sku_code} · ${'display_name' in item ? item.display_name : ''}`}
                      </option>
                    ))}
                  </select>
                  <input aria-label="Quantity" min="1" onChange={(event) => updateLine(line.id, { quantity: event.target.value })} placeholder="Qty" required type="number" value={line.quantity} />
                  {dialog.kind === 'order' ? <input aria-label="Unit cost" min="0.01" onChange={(event) => updateLine(line.id, { unitCost: event.target.value })} placeholder="Unit cost" required step="0.01" type="number" value={line.unitCost} /> : null}
                  {lines.length > 1 && !(dialog.kind === 'order' && values.originating_requisition) ? <button aria-label="Remove line" onClick={() => setLines((current) => current.filter((item) => item.id !== line.id))} type="button"><Icon name="close" /></button> : null}
                </div>
              ))}
              {!(dialog.kind === 'order' && values.originating_requisition) ? <button className="secondary-button" onClick={() => setLines((current) => [...current, emptyLine()])} type="button"><Icon name="plus" /> Add line</button> : null}
            </div>
          ) : null}
          {error ? <p className="business-dialog-error"><Icon name="alert" /> {error}</p> : null}
          <footer>
            <button className="secondary-button" disabled={busy} onClick={onClose} type="button">Cancel</button>
            <button className="primary-button" disabled={busy} type="submit">{busy ? 'Saving…' : dialogSubmitLabel(dialog)}</button>
          </footer>
        </form>
      </section>
    </div>
  );
}

function DialogFields({
  data,
  dialog,
  setValue,
  values,
}: {
  readonly data: ProcurementData;
  readonly dialog: Exclude<DialogMode, null>;
  readonly lines: readonly DraftLine[];
  readonly setValue: (name: string, value: string) => void;
  readonly updateLine: (id: string, patch: Partial<DraftLine>) => void;
  readonly values: Record<string, string>;
}) {
  const field = (
    name: string,
    label: string,
    options?: readonly { readonly id: string; readonly label: string }[],
    type = 'text',
    required = true,
  ) => (
    <label className="business-field">
      <span>{label} {required ? <b>Required</b> : null}</span>
      {options ? (
        <select onChange={(event) => setValue(name, event.target.value)} required={required} value={values[name] ?? ''}>
          <option value="">Select {label.toLowerCase()}</option>
          {options.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
        </select>
      ) : (
        <input onChange={(event) => setValue(name, event.target.value)} required={required} step={type === 'number' ? 'any' : undefined} type={type} value={values[name] ?? ''} />
      )}
    </label>
  );

  if (dialog.kind === 'confirm') return null;

  if (dialog.kind === 'supplier') return <>
    {field('supplier_code', 'Supplier code')}
    {field('legal_name', 'Legal name')}
    <div className="tenant-form-grid">{field('contact_email', 'Contact email', undefined, 'email', false)}{field('contact_phone', 'Contact phone', undefined, 'text', false)}</div>
    <div className="tenant-form-grid">
      {field('risk_category', 'Risk category', ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].map((id) => ({ id, label: titleCase(id) })))}
      {field('payment_terms', 'Payment terms')}
    </div>
  </>;

  if (dialog.kind === 'qualification') return <>
    <div className="business-dialog-record"><div><code>{dialog.supplier.supplier_code}</code><strong>{dialog.supplier.legal_name}</strong></div></div>
    {field('qualification_type', 'Qualification', qualificationOptions)}
    {field('licence_number', 'Licence number')}
    {field('issuing_authority', 'Issuing authority')}
    <div className="tenant-form-grid">{field('effective_date', 'Effective date', undefined, 'date')}{field('expiry_date', 'Expiry date', undefined, 'date')}</div>
    {field('document_reference', 'Document reference', undefined, 'text', false)}
  </>;

  if (dialog.kind === 'suspend-supplier') return <>
    <p className="business-dialog-confirm"><Icon name="alert" /> This stops new purchase orders without removing commercial history.</p>
    <label className="business-field"><span>Suspension reason <b>Required</b></span><textarea onChange={(event) => setValue('reason', event.target.value)} required value={values.reason ?? ''} /></label>
  </>;

  if (dialog.kind === 'requisition') return <>
    {field('requesting_branch', 'Requesting branch', locationOptions(data))}
    <div className="tenant-form-grid">{field('requested_delivery_date', 'Required by', undefined, 'date')}{field('priority', 'Priority', ['LOW', 'NORMAL', 'HIGH', 'URGENT'].map((id) => ({ id, label: titleCase(id) })))}</div>
    <label className="business-field"><span>Business justification <b>Required</b></span><textarea onChange={(event) => setValue('justification', event.target.value)} required value={values.justification ?? ''} /></label>
  </>;

  if (dialog.kind === 'order') return <>
    {field('supplier', 'Approved supplier', data.suppliers.filter((item) => ['APPROVED', 'ACTIVE'].includes(item.status)).map((item) => ({ id: item.id, label: `${item.supplier_code} · ${item.legal_name}` })))}
    {field('originating_requisition', 'Approved requisition (optional)', data.requisitions.filter((item) => item.status === 'APPROVED' || item.status === 'PARTIALLY_ORDERED').map((item) => ({ id: item.id, label: item.requisition_number })), 'text', false)}
    <div className="tenant-form-grid">{field('ordering_branch', 'Ordering branch', locationOptions(data))}{field('expected_delivery_date', 'Expected delivery', undefined, 'date')}</div>
  </>;

  if (dialog.kind === 'receipt') return <>
    {field('purchase_order', 'Sent purchase order', data.orders.filter((item) => ['SENT', 'PARTIALLY_RECEIVED'].includes(item.status)).map((item) => ({ id: item.id, label: `${item.po_number} · ${item.supplier_name}` })))}
    {field('receiving_branch', 'Receiving branch', locationOptions(data))}
    {field('delivery_note_number', 'Supplier delivery note')}
  </>;

  if (dialog.kind === 'receive-batch') {
    const order = data.orders.find((item) => item.id === dialog.receipt.purchase_order);
    return <>
      {field('po_line', 'Purchase-order line', order?.lines.map((line) => ({ id: line.id, label: `${line.sku_code} · ${line.received_quantity}/${line.ordered_quantity} received` })) ?? [])}
      {field('manufacturer_batch_number', 'Manufacturer batch number')}
      <div className="tenant-form-grid">{field('manufacture_date', 'Manufacture date', undefined, 'date', false)}{field('expiry_date', 'Expiry date', undefined, 'date')}</div>
      {field('received_quantity', 'Quantity received', undefined, 'number')}
    </>;
  }

  if (dialog.kind === 'inspection') return <>
    {field('decision', 'Inspection decision', ['QUARANTINE', 'REJECT', 'HOLD_FOR_INVESTIGATION', 'DESTROY'].map((id) => ({ id, label: titleCase(id) })))}
    <label className="business-field"><span>Inspection reason <b>Required</b></span><textarea onChange={(event) => setValue('reason', event.target.value)} required value={values.reason ?? ''} /></label>
    <label className="business-checkbox"><input checked={values.temperature_excursion === 'true'} onChange={(event) => setValue('temperature_excursion', String(event.target.checked))} type="checkbox" /> Temperature excursion observed</label>
  </>;

  if (dialog.kind === 'release') return <>
    <div className="business-dialog-record"><div><code>{dialog.batch.sku_code}</code><strong>{dialog.batch.manufacturer_batch_number}</strong></div><ProcurementStatus value={dialog.batch.quality_status} /></div>
    {field('inventory_location', 'Destination inventory location', data.inventoryLocations.filter((item) => item.status === 'ACTIVE').map((item) => ({ id: item.id, label: `${item.name} · ${titleCase(item.location_type)}` })))}
    {field('quantity', 'Release quantity', undefined, 'number')}
    <label className="business-field"><span>Release rationale <b>Required</b></span><textarea onChange={(event) => setValue('reason', event.target.value)} required value={values.reason ?? ''} /></label>
  </>;

  if (dialog.kind === 'return') return <>
    {field('goods_receipt', 'Goods receipt', data.receipts.map((item) => ({ id: item.id, label: `${item.grn_number} · ${item.delivery_note_number}` })))}
    {field('return_number', 'Return reference')}
    {field('sku', 'SKU', skuOptions(data))}
    {field('quantity', 'Return quantity', undefined, 'number')}
    <label className="business-field"><span>Return reason <b>Required</b></span><textarea onChange={(event) => setValue('reason', event.target.value)} required value={values.reason ?? ''} /></label>
  </>;

  return <>
    {field('purchase_order', 'Purchase order', data.orders.map((item) => ({ id: item.id, label: item.po_number })))}
    {field('goods_receipt', 'Goods receipt', data.receipts.map((item) => ({ id: item.id, label: item.grn_number })))}
    {field('invoice_reference', 'Supplier invoice')}
    {field('invoice_amount', 'Invoice amount', undefined, 'number')}
  </>;
}

function dialogRequest(
  dialog: Exclude<DialogMode, null>,
  values: Record<string, string>,
  lines: readonly DraftLine[],
  data: ProcurementData,
): { readonly message: string; readonly path: string; readonly payload: unknown } {
  if (dialog.kind === 'supplier') return {
    message: `${values.legal_name} registered as a prospective supplier.`,
    path: '/api/procurement/suppliers/',
    payload: { ...values, default_currency: 'KES' },
  };
  if (dialog.kind === 'qualification') return {
    message: `Qualification captured for ${dialog.supplier.legal_name}.`,
    path: '/api/procurement/supplier-qualifications/',
    payload: { ...values, supplier: dialog.supplier.id },
  };
  if (dialog.kind === 'suspend-supplier') return {
    message: `${dialog.supplier.legal_name} suspended.`,
    path: `/api/procurement/suppliers/${dialog.supplier.id}/suspend/`,
    payload: { reason: values.reason },
  };
  if (dialog.kind === 'requisition') return {
    message: 'Purchase requisition created in draft.',
    path: '/api/procurement/requisitions/',
    payload: {
      ...values,
      lines: lines.map((line) => ({
        purchase_unit: 'pack',
        requested_quantity: Number(line.quantity),
        sku: line.referenceId,
      })),
    },
  };
  if (dialog.kind === 'order') return {
    message: 'Purchase order created in draft.',
    path: '/api/procurement/purchase-orders/',
    payload: {
      currency: 'KES',
      expected_delivery_date: values.expected_delivery_date,
      lines: lines.map((line) => values.originating_requisition ? {
        quantity: Number(line.quantity),
        requisition_line: line.referenceId,
        requires_cold_chain: line.requiresColdChain,
        unit_cost: line.unitCost,
      } : {
        quantity: Number(line.quantity),
        requires_cold_chain: line.requiresColdChain,
        sku: line.referenceId,
        unit_cost: line.unitCost,
      }),
      ordering_branch: values.ordering_branch,
      originating_requisition: values.originating_requisition || null,
      supplier: values.supplier,
    },
  };
  if (dialog.kind === 'receipt') return {
    message: 'Goods receipt opened at the receiving bay.',
    path: '/api/procurement/goods-receipts/',
    payload: values,
  };
  if (dialog.kind === 'receive-batch') return {
    message: `Batch ${values.manufacturer_batch_number} captured in quarantine.`,
    path: `/api/procurement/goods-receipts/${dialog.receipt.id}/receive-batch/`,
    payload: { ...values, idempotency_key: crypto.randomUUID(), received_quantity: Number(values.received_quantity) },
  };
  if (dialog.kind === 'inspection') return {
    message: `Inspection recorded for ${dialog.receipt.grn_number}.`,
    path: `/api/procurement/goods-receipts/${dialog.receipt.id}/inspect/`,
    payload: { ...values, temperature_excursion: values.temperature_excursion === 'true' },
  };
  if (dialog.kind === 'release') return {
    message: `Batch ${dialog.batch.manufacturer_batch_number} released and posted to inventory.`,
    path: `/api/procurement/received-batches/${dialog.batch.id}/release/`,
    payload: { ...values, quantity: Number(values.quantity) },
  };
  if (dialog.kind === 'return') return {
    message: `Supplier return ${values.return_number} requested.`,
    path: '/api/procurement/supplier-returns/',
    payload: {
      goods_receipt: values.goods_receipt,
      lines: [{ quantity: Number(values.quantity), sku: values.sku }],
      reason: values.reason,
      return_number: values.return_number,
    },
  };
  const receipt = data.receipts.find((item) => item.id === values.goods_receipt);
  if (receipt && receipt.purchase_order !== values.purchase_order) {
    throw new HQApiError(400, 'The selected goods receipt does not belong to the selected purchase order.');
  }
  return {
    message: `Invoice ${values.invoice_reference} matched against the purchase order and receipt.`,
    path: '/api/procurement/matching/',
    payload: { ...values, invoice_amount: values.invoice_amount },
  };
}

function dialogDefaults(dialog: Exclude<DialogMode, null>, data: ProcurementData): Record<string, string> {
  const today = new Date().toISOString().slice(0, 10);
  const future = new Date(Date.now() + 7 * 86_400_000).toISOString().slice(0, 10);
  if (dialog.kind === 'confirm') return {};
  if (dialog.kind === 'supplier') return { contact_email: '', contact_phone: '', legal_name: '', payment_terms: 'NET30', risk_category: 'MEDIUM', supplier_code: '' };
  if (dialog.kind === 'qualification') return { document_reference: '', effective_date: today, expiry_date: '', issuing_authority: '', licence_number: '', qualification_type: 'BUSINESS_REGISTRATION' };
  if (dialog.kind === 'suspend-supplier') return { reason: '' };
  if (dialog.kind === 'requisition') return { justification: '', priority: 'NORMAL', requested_delivery_date: future, requesting_branch: data.locations[0]?.id ?? '' };
  if (dialog.kind === 'order') return { expected_delivery_date: future, ordering_branch: data.locations[0]?.id ?? '', originating_requisition: '', supplier: data.suppliers.find((item) => ['APPROVED', 'ACTIVE'].includes(item.status))?.id ?? '' };
  if (dialog.kind === 'receipt') return { delivery_note_number: '', purchase_order: data.orders.find((item) => ['SENT', 'PARTIALLY_RECEIVED'].includes(item.status))?.id ?? '', receiving_branch: data.locations[0]?.id ?? '' };
  if (dialog.kind === 'receive-batch') return { expiry_date: '', manufacture_date: '', manufacturer_batch_number: '', po_line: data.orders.find((item) => item.id === dialog.receipt.purchase_order)?.lines[0]?.id ?? '', received_quantity: '' };
  if (dialog.kind === 'inspection') return { decision: 'QUARANTINE', reason: '', temperature_excursion: 'false' };
  if (dialog.kind === 'release') return { inventory_location: data.inventoryLocations.find((item) => item.status === 'ACTIVE')?.id ?? '', quantity: String(dialog.batch.quarantined_quantity || dialog.batch.received_quantity), reason: '' };
  if (dialog.kind === 'return') return { goods_receipt: data.receipts[0]?.id ?? '', quantity: '', reason: '', return_number: `RET-${Date.now().toString().slice(-8)}`, sku: data.skus[0]?.id ?? '' };
  return { goods_receipt: data.receipts[0]?.id ?? '', invoice_amount: '', invoice_reference: '', purchase_order: data.receipts[0]?.purchase_order ?? data.orders[0]?.id ?? '' };
}

function dialogTitle(dialog: Exclude<DialogMode, null>): string {
  if (dialog.kind === 'confirm') return dialog.title;
  return {
    inspection: 'Record receiving inspection',
    match: 'Run three-way match',
    order: 'Raise purchase order',
    qualification: 'Capture supplier qualification',
    receipt: 'Open goods receipt',
    reconciliation: 'Reconcile procurement',
    release: 'Release batch to inventory',
    requisition: 'Create purchase requisition',
    return: 'Request supplier return',
    'receive-batch': 'Receive batch and expiry',
    supplier: 'Register supplier',
    'suspend-supplier': 'Suspend supplier',
  }[dialog.kind] ?? 'Procurement action';
}

function dialogSubmitLabel(dialog: Exclude<DialogMode, null>): string {
  if (dialog.kind === 'confirm') return dialog.submitLabel;
  if (dialog.kind === 'release') return 'Release to inventory';
  if (dialog.kind === 'match') return 'Run match';
  if (dialog.kind === 'inspection') return 'Record inspection';
  if (dialog.kind === 'suspend-supplier') return 'Suspend supplier';
  return 'Save record';
}

function supportsLines(dialog: Exclude<DialogMode, null>): boolean {
  return dialog.kind === 'requisition' || dialog.kind === 'order';
}

function confirmationDialog({
  confirmation,
  message,
  path,
  payload,
  record,
  submitLabel,
  title,
}: Omit<Extract<DialogMode, { readonly kind: 'confirm' }>, 'kind'>): Extract<DialogMode, { readonly kind: 'confirm' }> {
  return {
    confirmation,
    kind: 'confirm',
    message,
    path,
    payload,
    record,
    submitLabel,
    title,
  };
}

function emptyLine(): DraftLine {
  return {
    id: crypto.randomUUID(),
    quantity: '',
    referenceId: '',
    requiresColdChain: false,
    unitCost: '',
  };
}

function ProcurementHeader({
  action,
  eyebrow,
  onAction,
  title,
}: {
  readonly action?: string;
  readonly eyebrow: string;
  readonly onAction?: () => void;
  readonly title: string;
}) {
  return (
    <div className="procurement-section-head">
      <div><p>{eyebrow}</p><h2>{title}</h2></div>
      {action && onAction ? <button className="primary-button" onClick={onAction} type="button"><Icon name="plus" /> {action}</button> : null}
    </div>
  );
}

function ProcurementMetric({
  detail,
  icon,
  label,
  onActivate,
  value,
}: {
  readonly detail: string;
  readonly icon: 'alert' | 'building' | 'docs' | 'store';
  readonly label: string;
  readonly onActivate?: () => void;
  readonly value: number;
}) {
  const content = (
    <>
      <span className="summary-icon"><Icon name={icon} /></span>
      <div><p>{label}</p><strong>{value.toLocaleString()}</strong><small>{detail}</small></div>
    </>
  );
  if (onActivate) {
    return (
      <button
        aria-label={`Open ${label}: ${value.toLocaleString()}`}
        className="summary-card summary-card-link"
        onClick={onActivate}
        type="button"
      >
        {content}
      </button>
    );
  }
  return <article className="summary-card">{content}</article>;
}

function ProcurementRecord({
  actions,
  detail,
  metrics,
  reference,
  status,
  title,
}: {
  readonly actions: ReactNode;
  readonly detail: string;
  readonly metrics: readonly (readonly [string, string])[];
  readonly reference: string;
  readonly status: string;
  readonly title: string;
}) {
  return (
    <article className="procurement-record">
      <header><code>{reference}</code><ProcurementStatus value={status} /></header>
      <div><h3>{title}</h3><p>{detail}</p><dl>{metrics.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></div>
      <footer>{actions}</footer>
    </article>
  );
}

function ProcurementStatus({ value }: { readonly value: string }) {
  const positive = ['ACTIVE', 'APPROVED', 'ACCEPTED', 'RELEASED', 'MATCHED', 'VERIFIED', 'FULLY_RECEIVED', 'CLOSED'];
  const danger = ['SUSPENDED', 'REJECTED', 'DISQUALIFIED', 'DESTROYED', 'VARIANCE_FLAGGED', 'CANCELLED'];
  const tone = positive.includes(value) ? 'active' : danger.includes(value) ? 'suspended' : 'warning';
  return <span className={`status-badge status-${tone}`}><i /> {titleCase(value)}</span>;
}

function ProcurementEmpty({
  detail,
  icon,
  title,
}: {
  readonly detail: string;
  readonly icon: 'building' | 'docs' | 'inventory' | 'shield' | 'store';
  readonly title: string;
}) {
  return <div className="procurement-empty"><Icon name={icon} /><h3>{title}</h3><p>{detail}</p></div>;
}

function tabCount(tab: ProcurementTab, data: ProcurementData | null): number {
  if (!data) return 0;
  if (tab === 'suppliers') return data.suppliers.length;
  if (tab === 'requisitions') return data.requisitions.length;
  if (tab === 'orders') return data.orders.length;
  if (tab === 'receiving') return data.receipts.length;
  if (tab === 'quality') return data.batches.filter((item) => item.quality_status !== 'RELEASED').length;
  return data.returns.length + data.matches.length;
}

function locationOptions(data: ProcurementData) {
  return data.locations.filter((item) => item.status === 'ACTIVE').map((item) => ({
    id: item.id,
    label: `${item.code ?? ''} · ${item.name}`,
  }));
}

function skuOptions(data: ProcurementData) {
  return data.skus.filter((item) => item.status === 'ACTIVE').map((item) => ({
    id: item.id,
    label: `${item.sku_code} · ${item.display_name}`,
  }));
}

const qualificationOptions = [
  'BUSINESS_REGISTRATION',
  'TAX_COMPLIANCE',
  'WHOLESALE_DEALER_LICENCE',
  'GDP_CERTIFICATE',
  'QUALITY_AGREEMENT',
  'COLD_CHAIN_AUTHORIZATION',
  'CONTROLLED_DRUG_LICENCE',
].map((id) => ({ id, label: titleCase(id) }));

function orderReference(data: ProcurementData, orderId: string): string {
  return data.orders.find((item) => item.id === orderId)?.po_number ?? orderId;
}

function titleCase(value: string): string {
  return value.toLowerCase().replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('en-KE', { dateStyle: 'medium' }).format(new Date(`${value}T00:00:00`));
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat('en-KE', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}
