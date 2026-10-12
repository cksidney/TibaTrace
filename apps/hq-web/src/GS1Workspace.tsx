import { useEffect, useMemo, useState } from 'react';

import { matchInventoryItemByBarcode, parseBarcodeOrDataMatrix } from '@dawatrace/shared/dispensing/index.js';
import type { HQInventoryBatchItem, HQOverview, HQSku } from './api.js';
import { loadInventoryBatches, loadTenantSkus } from './api.js';
import { Icon } from './icons.js';

interface GS1WorkspaceProps {
  overview: HQOverview;
}

type ScanStatus = 'MATCHED' | 'NOT_FOUND' | 'AMBIGUOUS' | 'INVALID_GTIN' | 'NO_INPUT';

interface ScanResult {
  readonly status: ScanStatus;
  readonly raw: string;
  readonly parsed: ReturnType<typeof parseBarcodeOrDataMatrix>;
  readonly matchedSku?: HQSku;
  readonly matchedBatches: readonly HQInventoryBatchItem[];
  readonly gtinValid: boolean | null;
  readonly notice: string;
}

export function validateGtin(gtin: string): boolean {
  if (!/^(?:\d{8}|\d{12,14})$/.test(gtin)) return false;
  const digits = gtin.split('').map(Number);
  const checkDigit = digits.pop();
  if (checkDigit === undefined) return false;
  let sum = 0;
  let weight = 3;
  for (let index = digits.length - 1; index >= 0; index -= 1) {
    sum += digits[index]! * weight;
    weight = weight === 3 ? 1 : 3;
  }
  return (10 - (sum % 10)) % 10 === checkDigit;
}

export function GS1Workspace({ overview }: GS1WorkspaceProps) {
  const selectableTenants = useMemo(
    () => overview.network_items.filter((tenant) => tenant.status === 'ACTIVE'),
    [overview.network_items],
  );
  const [tenantId, setTenantId] = useState(
    overview.tenant_id || selectableTenants[0]?.id || '',
  );
  const [rawInput, setRawInput] = useState('');
  const [skus, setSkus] = useState<readonly HQSku[]>([]);
  const [batches, setBatches] = useState<readonly HQInventoryBatchItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);

  useEffect(() => {
    setScanResult(null);
    if (!tenantId) {
      setSkus([]);
      setBatches([]);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setLoadFailed(false);
    Promise.all([
      loadTenantSkus(tenantId, controller.signal),
      loadInventoryBatches(tenantId, controller.signal),
    ]).then(([nextSkus, nextBatches]) => {
      if (!controller.signal.aborted) {
        setSkus(nextSkus);
        setBatches(nextBatches);
      }
    }).catch(() => {
      if (!controller.signal.aborted) setLoadFailed(true);
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [tenantId]);

  useEffect(() => {
    if (overview.tenant_id && overview.tenant_id !== tenantId) setTenantId(overview.tenant_id);
  }, [overview.tenant_id, tenantId]);

  const candidates = useMemo(() => skus.map((sku) => ({
    id: sku.id,
    skuCode: sku.sku_code,
    barcode: sku.default_barcode,
  })), [skus]);

  const ingestScan = () => {
    const raw = rawInput.trim();
    if (!raw) {
      setScanResult({ status: 'NO_INPUT', raw, parsed: parseBarcodeOrDataMatrix(raw), matchedBatches: [], gtinValid: null, notice: 'Scan or paste a barcode first.' });
      return;
    }
    const parsed = parseBarcodeOrDataMatrix(raw);
    const gtin = parsed.gtin ?? (parsed.format === 'STANDARD_BARCODE' ? raw : undefined);
    const gtinValid = gtin ? validateGtin(gtin) : null;
    if (gtin && !gtinValid) {
      setScanResult({ status: 'INVALID_GTIN', raw, parsed, matchedBatches: [], gtinValid: false, notice: 'The barcode has a GTIN with an invalid check digit. Verify the scan before using it for traceability.' });
      return;
    }

    const match = matchInventoryItemByBarcode(raw, candidates);
    if (match.status !== 'MATCHED') {
      setScanResult({
        status: match.status,
        raw,
        parsed,
        matchedBatches: [],
        gtinValid,
        notice: match.status === 'AMBIGUOUS'
          ? 'More than one catalogue item uses this identifier. Resolve the duplicate before receiving stock.'
          : 'No exact tenant catalogue identifier matched. Add or correct the barcode on the governed SKU before receiving stock.',
      });
      return;
    }
    const matchedSku = skus.find((sku) => sku.id === match.itemId);
    const matchingBatches = parsed.batchNumber
      ? batches.filter((batch) => batch.sku === match.itemId && batch.manufacturer_batch_number.toUpperCase() === parsed.batchNumber?.toUpperCase())
      : [];
    const expiryMismatch = Boolean(parsed.expiryDateIso && matchingBatches.length && matchingBatches.every((batch) => batch.expiry_date !== parsed.expiryDateIso));
    setScanResult({
      status: 'MATCHED',
      raw,
      parsed,
      ...(matchedSku ? { matchedSku } : {}),
      matchedBatches: matchingBatches,
      gtinValid,
      notice: parsed.batchNumber && matchingBatches.length === 0
        ? `SKU matched. Batch ${parsed.batchNumber} is not registered in this tenant’s inventory yet; receive and inspect the delivery before it can be traced as stock.`
        : expiryMismatch
          ? 'The scanned expiry does not match the registered inventory batch. Hold the delivery and resolve the discrepancy during goods receipt.'
          : 'Exact tenant SKU match. Use procurement goods receipt to register a new batch and post its custody record.',
    });
  };

  return (
    <div className="gs1-workspace">
      <section className="panel gs1-header">
        <div><p className="eyebrow">GS1 traceability intake</p><h2>Scan, validate &amp; match medicine identifiers</h2><p>Decode a GS1 DataMatrix or barcode, verify the GTIN check digit, then match it to this tenant’s catalogue and registered batch records.</p></div>
        <span className="truth-label">Tenant scope · exact identifier match</span>
      </section>

      {!tenantId ? <div className="inline-alert" role="status"><Icon name="alert" /> Select an operating tenant to load its catalogue and batch records.</div> : null}
      {loadFailed ? <div className="inline-alert" role="alert"><Icon name="alert" /> Catalogue or inventory batches could not be loaded. Retry after checking your tenant access.</div> : null}

      <section className="panel gs1-scan-panel">
        <div className="gs1-panel-heading"><div><p className="eyebrow">Ingestion point</p><h3>Scan a medicine pack</h3><p>Use a scanner that types into this field, or paste GS1 human-readable text such as <code>(01)05012345678900(17)271231(10)BATCH-01(21)SERIAL-01</code>.</p></div>{overview.is_platform_overview ? <label className="regulatory-tenant-select"><span>Operating tenant</span><select onChange={(event) => setTenantId(event.target.value)} value={tenantId}>{selectableTenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}</select></label> : <span className="gs1-scan-icon"><Icon name="inventory" /></span>}</div>
        <form className="gs1-scan-form" onSubmit={(event) => { event.preventDefault(); ingestScan(); }}>
          <label className="business-field"><span>Barcode or DataMatrix text<b>Required</b></span><textarea autoComplete="off" autoFocus onChange={(event) => setRawInput(event.target.value)} placeholder="Scan or paste the complete code, including (01), (17), (10), and (21) identifiers when available." rows={3} value={rawInput} /></label>
          <div className="gs1-scan-actions"><small>{loading ? 'Loading tenant identifiers…' : `${skus.length} catalogue SKUs · ${batches.length} inventory batch records`}</small><button className="primary-button" disabled={loading || !tenantId} type="submit"><Icon name="search" /> Decode &amp; trace</button></div>
        </form>
      </section>

      {scanResult ? <ScanResultCard result={scanResult} /> : null}

      <section className="gs1-next-steps">
        <article className="panel"><span>01</span><div><strong>Catalogue match</strong><p>Only exact GTIN, barcode, SKU code, or SKU ID matches are accepted. Names are never used as a fallback.</p></div></article>
        <article className="panel"><span>02</span><div><strong>Goods receipt intake</strong><p>New batch numbers, expiry, inspection and accepted quantities are recorded in the controlled procurement workflow.</p><a href="#operations">Open procurement goods receipt <Icon name="arrow" /></a></div></article>
        <article className="panel"><span>03</span><div><strong>Inventory trace</strong><p>Registered batches carry recall and quality status into the append-only inventory ledger and FEFO allocation checks.</p><a href="#inventory">Open inventory control <Icon name="arrow" /></a></div></article>
      </section>
    </div>
  );
}

function ScanResultCard({ result }: { readonly result: ScanResult }) {
  const batch = result.matchedBatches[0];
  return (
    <section className={`panel gs1-result gs1-result-${result.status.toLowerCase()}`} aria-live="polite">
      <header><div><p className="eyebrow">Trace result</p><h3>{result.status === 'MATCHED' ? result.matchedSku?.display_name ?? 'Catalogue match' : result.status.replaceAll('_', ' ')}</h3></div><span className={`regulatory-status ${result.status === 'MATCHED' ? 'status-teal' : result.status === 'NOT_FOUND' || result.status === 'INVALID_GTIN' ? 'status-rose' : 'status-amber'}`}>{result.status.replaceAll('_', ' ')}</span></header>
      <p className="gs1-result-notice"><Icon name={result.status === 'MATCHED' && !result.notice.includes('Hold') ? 'check' : 'alert'} /> {result.notice}</p>
      <dl className="gs1-result-grid">
        <div><dt>Identifier format</dt><dd>{result.parsed.format.replaceAll('_', ' ')}</dd></div>
        <div><dt>GTIN check digit</dt><dd>{result.gtinValid === null ? 'Not present' : result.gtinValid ? 'Valid' : 'Invalid'}</dd></div>
        <div><dt>GTIN</dt><dd>{result.parsed.gtin ?? (result.parsed.format === 'STANDARD_BARCODE' ? result.raw : '—')}</dd></div>
        <div><dt>Manufacturer batch</dt><dd>{result.parsed.batchNumber ?? '—'}</dd></div>
        <div><dt>Expiry from scan</dt><dd>{result.parsed.expiryDateIso ?? '—'}</dd></div>
        <div><dt>Serial number</dt><dd>{result.parsed.serialNumber ?? '—'}</dd></div>
        {result.matchedSku ? <div><dt>Tenant SKU</dt><dd><code>{result.matchedSku.sku_code}</code></dd></div> : null}
        {batch ? <div><dt>Registered batch</dt><dd><code>{batch.manufacturer_batch_number}</code> · {batch.expiry_date} · {batch.quality_status} · {batch.recall_status}</dd></div> : null}
      </dl>
      {result.parsed.rawText ? <details><summary>Show original scanner input</summary><code>{result.parsed.rawText}</code></details> : null}
    </section>
  );
}
