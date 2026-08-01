import { describe, expect, it } from 'vitest';
import {
  determineItemUom,
  formatLocationHierarchy,
  generateDocumentQrPayload,
  matchInventoryItemByBarcode,
  parseBarcodeOrDataMatrix,
  resolveItemParentChild,
  verifyGoodsReceiptScan,
} from './barcodeScanner.js';

describe('barcodeScanner module', () => {
  it('parses formatted GS1 DataMatrix 2D barcode', () => {
    const input = '(01)06001234567890(17)261231(10)BATCH9988(21)SER1001';
    const parsed = parseBarcodeOrDataMatrix(input);

    expect(parsed.format).toBe('GS1_DATAMATRIX');
    expect(parsed.gtin).toBe('06001234567890');
    expect(parsed.expiryDateIso).toBe('2026-12-31');
    expect(parsed.batchNumber).toBe('BATCH9988');
    expect(parsed.serialNumber).toBe('SER1001');
    expect(parsed.lookupValues).toEqual(['06001234567890', '6001234567890']);
  });

  it('parses standard 1D barcode or SKU code', () => {
    const input = '6009876543210';
    const parsed = parseBarcodeOrDataMatrix(input);

    expect(parsed.format).toBe('STANDARD_BARCODE');
    expect(parsed.parsedSkuCode).toBe('6009876543210');
  });

  it('matches only an exact authoritative SKU or barcode', () => {
    const candidates = [
      { id: 'sku-1', skuCode: 'AMOX-500', barcode: '6001234567890' },
      { id: 'sku-2', skuCode: 'AMOX-250', barcode: '6001234567891' },
    ];

    expect(matchInventoryItemByBarcode('6001234567890', candidates)).toMatchObject({
      itemId: 'sku-1',
      status: 'MATCHED',
    });
    expect(matchInventoryItemByBarcode('AMOX', candidates).status).toBe('NOT_FOUND');
  });

  it('fails closed when a barcode mapping is ambiguous', () => {
    const result = matchInventoryItemByBarcode('6001234567890', [
      { id: 'sku-1', skuCode: 'AMOX-500', barcode: '6001234567890' },
      { id: 'sku-2', skuCode: 'AMOX-500-B', barcode: '6001234567890' },
    ]);

    expect(result.status).toBe('AMBIGUOUS');
    expect(result.itemId).toBeUndefined();
  });

  it('resolves Parent-Child Item Relationships with conversion factors', () => {
    const childItem = resolveItemParentChild({
      id: 'SKU-AMOX-UNIT',
      sku_code: 'SKU-AMOX-UNIT-10',
      name: 'Amoxicillin 500mg Blister Pack (10 Caps)',
      parent_sku_id: 'SKU-AMOX-BOX-100',
      parent_sku_code: 'SKU-AMOX-BOX-100',
      pack_relationship: 'INNER_BLISTER',
      conversion_factor: 10,
    });

    expect(childItem.parentSkuId).toBe('SKU-AMOX-BOX-100');
    expect(childItem.packLevel).toBe('INNER_BLISTER');
    expect(childItem.conversionFactor).toBe(10);
  });

  it('formats Parent-Child Location Hierarchy breadcrumb', () => {
    const location = formatLocationHierarchy({
      id: 'LOC-DISP-01',
      name: 'Dispensing Counter #1',
      parent_location_name: 'Nairobi Central Warehouse',
      hierarchy_level: 'ROOM',
    });

    expect(location.pathBreadcrumb).toBe('Nairobi Central Warehouse ➔ Dispensing Counter #1');
    expect(location.hierarchyLevel).toBe('ROOM');
  });

  it('packages a server-issued checksum and validation URL for a document QR', () => {
    const doc = generateDocumentQrPayload({
      checksumSha256: 'a'.repeat(64),
      documentType: 'STOCK_TRANSFER',
      documentId: 'TRF-1002',
      documentNumber: 'TRF-NAI-00192',
      tenantId: 'TENANT-001',
      issuerUserId: 'pharmacist-01',
      issueTimestampIso: '2026-08-01T15:00:00Z',
      validationUrl: 'https://tibatrace.esenai.co.ke/api/documents/TRF-1002/validate/',
    });

    expect(doc.documentNumber).toBe('TRF-NAI-00192');
    expect(doc.qrValidationUrl).toBe('https://tibatrace.esenai.co.ke/api/documents/TRF-1002/validate/');
    expect(doc.qrPayloadString).toContain('TRF-NAI-00192');
    expect(doc.verificationSignature).toBe('a'.repeat(64));
  });

  it('determines UOM categories and unit price conversions', () => {
    const uom = determineItemUom({
      skuCode: 'SKU-AMOX-500',
      name: 'Amoxicillin 500mg Capsules',
      dosageForm: 'Capsule',
      purchaseUnit: 'BOX_100',
      packSize: 100,
      packPriceKes: 1500,
    });

    expect(uom.dispensingUom).toBe('CAPSULE');
    expect(uom.uomCategory).toBe('SOLID_ORAL');
    expect(uom.conversionFactor).toBe(100);
    expect(uom.unitPriceKes).toBe(15);
    expect(uom.formattedSummary).toContain('1 BOX_100 = 100 CAPSULE');
  });

  it('verifies goods receipt scan and updates accepted quantities', () => {
    const result = verifyGoodsReceiptScan({
      scannedInput: '(01)06001234567890(17)261231(10)BATCH777',
      expectedLines: [
        {
          acceptedQuantity: 12,
          barcode: '6001234567890',
          batchNumber: 'BATCH777',
          expectedQuantity: 50,
          lineKey: 'line-1:batch-777',
          skuCode: 'SKU-AMOX-500',
        },
      ],
    });

    expect(result.matchFound).toBe(true);
    expect(result.matchedLineKey).toBe('line-1:batch-777');
    expect(result.matchedSkuCode).toBe('SKU-AMOX-500');
    expect(result.updatedAcceptedQuantity).toBe(13);
    expect(result.discrepancyDetected).toBe(false);
  });

  it('never falls back to an unrelated expected line', () => {
    const result = verifyGoodsReceiptScan({
      scannedInput: 'UNKNOWN-SKU',
      expectedLines: [
        {
          acceptedQuantity: 0,
          barcode: '6001234567890',
          batchNumber: 'BATCH777',
          expectedQuantity: 2,
          lineKey: 'line-1',
          skuCode: 'SKU-AMOX-500',
        },
      ],
    });

    expect(result.matchFound).toBe(false);
    expect(result.discrepancyDetected).toBe(true);
  });

  it('rejects a GS1 batch that is not expected on the transfer', () => {
    const result = verifyGoodsReceiptScan({
      scannedInput: '(01)06001234567890(10)WRONG-BATCH',
      expectedLines: [
        {
          acceptedQuantity: 0,
          barcode: '6001234567890',
          batchNumber: 'BATCH777',
          expectedQuantity: 2,
          lineKey: 'line-1',
          skuCode: 'SKU-AMOX-500',
        },
      ],
    });

    expect(result.matchFound).toBe(false);
    expect(result.statusNote).toContain('WRONG-BATCH');
  });
});
