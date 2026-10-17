import { IntakeModal } from './IntakeModal.js';
import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { loadInventoryLocations, loadTenantSkus, releaseLegacySetup, stageLegacySetup } from './api.js';
import type { HQInventoryLocationItem, HQSku, LegacySetupItem } from './api.js';

export function LegacySetupCompletion({ item, tenantId, csrfToken, onClose, onSaved }: { readonly item: LegacySetupItem; readonly tenantId: string; readonly csrfToken: string; readonly onClose: () => void; readonly onSaved: () => void }) {
  const [skus, setSkus] = useState<readonly HQSku[]>([]);
  const [locations, setLocations] = useState<readonly HQInventoryLocationItem[]>([]);
  const [skuId, setSkuId] = useState('');
  const [branchId, setBranchId] = useState(item.completion?.branch_id ?? '');
  const [locationId, setLocationId] = useState('');
  const [productConfirmed, setProductConfirmed] = useState(false);
  const [unitConfirmed, setUnitConfirmed] = useState(false);
  const [storage, setStorage] = useState('');
  const [taxInclusive, setTaxInclusive] = useState(true);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const releasing = item.completion?.phase === 'QUARANTINED';
  useEffect(() => {
    const controller = new AbortController();
    setBusy(true);
    Promise.all([loadTenantSkus(tenantId, controller.signal), loadInventoryLocations(tenantId, controller.signal)])
      .then(([products, places]) => { if (!controller.signal.aborted) { setSkus(products.filter((sku) => sku.status === 'ACTIVE')); setLocations(places.filter((place) => place.status === 'ACTIVE')); } })
      .catch((cause: unknown) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Setup options could not be loaded.'); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [tenantId]);
  const branches = [...new Map(locations.map((location) => [location.branch, location.branch_name ?? location.branch])).entries()];
  const selectedSku = skus.find((sku) => sku.id === skuId);
  const storageChoices = locations.filter((place) => place.branch === branchId && Boolean(place.quarantine_capability) !== releasing && !place.returns_capability && !['DAMAGED', 'EXPIRED', 'TRANSIT'].includes(place.location_type));
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('');
    try {
      if (releasing) await releaseLegacySetup(item, locationId, reason.trim(), csrfToken);
      else await stageLegacySetup(item, { sku_id: skuId, branch_id: branchId, quarantine_location_id: locationId, product_match_confirmed: productConfirmed, unit_match_confirmed: unitConfirmed, storage_requirement: storage, tax_inclusive: taxInclusive, reason: reason.trim() }, csrfToken);
      onSaved();
    } catch (cause: unknown) { setError(cause instanceof Error ? cause.message : 'Opening setup could not be completed.'); }
    finally { setBusy(false); }
  };
  return <IntakeModal title={releasing ? 'Independent opening-stock release' : 'Stage opening setup'} busy={busy} onClose={onClose}><section className="legacy-detail" aria-labelledby="opening-setup-title">
    <h3 id="opening-setup-title">{releasing ? 'Independent opening-stock release' : 'Link reviewed product and stage opening setup'}</h3>
    <p><strong>{item.source_name}</strong> · confirmed {item.review.counted_quantity} {item.review.sales_unit}, KES {item.review.confirmed_price} per sales unit.</p>
    <p>{releasing ? 'The linked price version must be independently approved, published and effective. A different quality-authorized user then confirms the actual batches and moves quarantine stock into saleable storage.' : 'Create and activate the exact reviewed medicine/pack in the catalogue first. This step creates only a price draft and quarantined opening stock; it does not approve a price or release stock. Imported quantities are never used automatically.'}</p>
    <form onSubmit={(event) => void submit(event)}><fieldset disabled={busy}><div className="legacy-fields">
      {!releasing && <><label>Governed tenant SKU<select required value={skuId} onChange={(event) => setSkuId(event.target.value)}><option value="">Select the exact product/pack</option>{skus.map((sku) => <option key={sku.id} value={sku.id}>{sku.sku_code} · {sku.display_name} · {sku.sales_unit}</option>)}</select>{selectedSku && <small>{selectedSku.canonical_medicine_name} · {selectedSku.package_description} · {selectedSku.tax_category}</small>}</label>
        <label>Confirmed pack storage requirement<select required value={storage} onChange={(event) => setStorage(event.target.value)}><option value="">Confirm from actual pack</option><option value="AMBIENT">Ambient</option><option value="COLD_CHAIN">Cold chain</option></select></label></>}
      <label>Branch<select required disabled={releasing} value={branchId} onChange={(event) => { setBranchId(event.target.value); setLocationId(''); }}><option value="">Select branch</option>{branches.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
      <label>{releasing ? 'Saleable destination' : 'Quarantine custody'}<select required value={locationId} onChange={(event) => setLocationId(event.target.value)}><option value="">Select storage location</option>{storageChoices.map((place) => <option key={place.id} value={place.id}>{place.name} · {place.location_code}</option>)}</select><small>{storageChoices.length ? 'Cold/controlled storage capability is enforced on the server.' : 'Provision the appropriate inventory location first.'}</small></label>
    </div>
      {!releasing && <><label className="legacy-exclude"><input required type="checkbox" checked={productConfirmed} onChange={(event) => setProductConfirmed(event.target.checked)} />I compared the actual pack and reviewed national reference with this exact SKU, strength, form and manufacturer.</label>
        <label className="legacy-exclude"><input required type="checkbox" checked={unitConfirmed} onChange={(event) => setUnitConfirmed(event.target.checked)} />Confirmed quantities/prices are one-to-one with this SKU's sales unit; no guessed conversion.</label>
        <label className="legacy-exclude"><input type="checkbox" checked={taxInclusive} onChange={(event) => setTaxInclusive(event.target.checked)} />Confirmed selling price includes applicable tax.</label></>}
      <label className="legacy-notes">{releasing ? 'Quality inspection evidence / release reason' : 'Mapping evidence / setup reason'}<textarea required maxLength={2000} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
      {error && <p className="legacy-error" role="alert">{error}</p>}
      <footer className="legacy-actions"><button className="secondary-button" type="button" onClick={onClose}>Close</button><button className="primary-button" type="submit">{busy ? 'Working…' : releasing ? 'Release verified opening stock' : 'Stage draft price and quarantine stock'}</button></footer>
    </fieldset></form>
  </section></IntakeModal>;
}
