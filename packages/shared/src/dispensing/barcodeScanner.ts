/**
 * GS1 DataMatrix & Barcode Scanning Engine + Parent-Child Relationship Resolver
 * Kenya Digital Health Agency (DHA) 2025 & GS1 Serialization Baseline
 */

export interface ParsedBarcodeResult {
  readonly rawText: string;
  readonly format: 'GS1_DATAMATRIX' | 'STANDARD_BARCODE' | 'SKU_CODE';
  readonly lookupValues: readonly string[];
  readonly gtin?: string | undefined;
  readonly batchNumber?: string | undefined;
  readonly expiryDateIso?: string | undefined;
  readonly serialNumber?: string | undefined;
  readonly parsedSkuCode?: string | undefined;
}

function lookupValues(...values: Array<string | undefined>): readonly string[] {
  const result = new Set<string>();
  for (const value of values) {
    const normalized = value?.trim().toUpperCase();
    if (!normalized) continue;
    result.add(normalized);
    if (/^0\d{13}$/.test(normalized)) result.add(normalized.slice(1));
  }
  return [...result];
}

function gs1ExpiryDate(value: string): string | undefined {
  if (!/^\d{6}$/.test(value)) return undefined;
  const year = 2000 + Number(value.slice(0, 2));
  const month = Number(value.slice(2, 4));
  const day = Number(value.slice(4, 6));
  const candidate = new Date(Date.UTC(year, month - 1, day));
  if (
    candidate.getUTCFullYear() !== year
    || candidate.getUTCMonth() !== month - 1
    || candidate.getUTCDate() !== day
  ) return undefined;
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

export interface ParentChildInventoryItem {
  readonly id: string;
  readonly skuCode: string;
  readonly name: string;
  readonly parentSkuId?: string | null | undefined;
  readonly parentSkuCode?: string | null | undefined;
  readonly packLevel: 'MASTER_PACK' | 'OUTER_BOX' | 'INNER_BLISTER' | 'UNIT_OF_USE';
  readonly conversionFactor: number;
  readonly childSkus?: readonly ParentChildInventoryItem[] | undefined;
}

export interface ParentChildLocationItem {
  readonly id: string;
  readonly code: string;
  readonly name: string;
  readonly parentLocationId?: string | null | undefined;
  readonly parentLocationName?: string | null | undefined;
  readonly hierarchyLevel: 'FACILITY' | 'ROOM' | 'ZONE' | 'SHELF_BIN' | 'VIRTUAL';
  readonly pathBreadcrumb: string;
}

/**
 * Parses raw barcode input (GS1 2D DataMatrix or 1D Barcode/SKU)
 */
export function parseBarcodeOrDataMatrix(scannedInput: string): ParsedBarcodeResult {
  const input = scannedInput.trim();
  if (!input) {
    return { rawText: '', format: 'SKU_CODE', lookupValues: [] };
  }

  // Human-readable GS1 scanner output. Variable-length AIs remain bounded by
  // the next parenthesized AI; an un-delimited raw symbol must be resolved by
  // an authoritative scanner/GS1 decoder rather than guessed here.
  const formattedGs1Regex = /\((01|17|10|21)\)([^()]*)/g;
  let gtin: string | undefined;
  let expiryDateIso: string | undefined;
  let batchNumber: string | undefined;
  let serialNumber: string | undefined;
  let gs1Match: RegExpExecArray | null;
  let recognizedAis = 0;
  while ((gs1Match = formattedGs1Regex.exec(input.replace(/^\]d2/, ''))) !== null) {
    const ai = gs1Match[1];
    const value = gs1Match[2]?.trim() || '';
    if (ai === '01' && /^\d{14}$/.test(value)) gtin = value;
    else if (ai === '17') expiryDateIso = gs1ExpiryDate(value);
    else if (ai === '10' && value) batchNumber = value.slice(0, 20);
    else if (ai === '21' && value) serialNumber = value.slice(0, 20);
    else continue;
    recognizedAis += 1;
  }

  if (recognizedAis > 0) {
    return {
      rawText: input,
      format: 'GS1_DATAMATRIX',
      lookupValues: lookupValues(gtin),
      gtin,
      batchNumber,
      expiryDateIso,
      serialNumber,
      parsedSkuCode: gtin,
    };
  }

  const format = /^\d{8}$|^\d{12,14}$/.test(input) ? 'STANDARD_BARCODE' : 'SKU_CODE';
  return {
    rawText: input,
    format,
    lookupValues: lookupValues(input),
    parsedSkuCode: input.toUpperCase(),
  };
}

export interface InventoryBarcodeCandidate {
  readonly id: string;
  readonly skuCode: string;
  readonly barcode?: string | undefined;
}

export interface InventoryBarcodeMatch {
  readonly status: 'MATCHED' | 'NOT_FOUND' | 'AMBIGUOUS';
  readonly parsedBarcode: ParsedBarcodeResult;
  readonly itemId?: string | undefined;
}

/** Resolves an exact tenant-catalogue identifier without fuzzy or fallback matching. */
export function matchInventoryItemByBarcode(
  scannedInput: string,
  candidates: readonly InventoryBarcodeCandidate[],
): InventoryBarcodeMatch {
  const parsedBarcode = parseBarcodeOrDataMatrix(scannedInput);
  const identifiers = new Set(parsedBarcode.lookupValues.map((value) => value.toUpperCase()));
  const matches = candidates.filter((candidate) => (
    identifiers.has(candidate.id.trim().toUpperCase())
    || identifiers.has(candidate.skuCode.trim().toUpperCase())
    || Boolean(candidate.barcode && identifiers.has(candidate.barcode.trim().toUpperCase()))
  ));
  if (matches.length === 0) return { parsedBarcode, status: 'NOT_FOUND' };
  if (matches.length > 1) return { parsedBarcode, status: 'AMBIGUOUS' };
  return { itemId: matches[0]!.id, parsedBarcode, status: 'MATCHED' };
}

/**
 * Resolves Parent-Child Item Relationship and breakdown conversion
 */
export function resolveItemParentChild(
  item: {
    readonly id: string;
    readonly sku_code?: string;
    readonly name?: string;
    readonly parent_sku_id?: string | null;
    readonly parent_sku_code?: string | null;
    readonly pack_relationship?: string;
    readonly conversion_factor?: number;
  },
): ParentChildInventoryItem {
  const packLevels = new Set<ParentChildInventoryItem['packLevel']>([
    'MASTER_PACK',
    'OUTER_BOX',
    'INNER_BLISTER',
    'UNIT_OF_USE',
  ]);
  const candidate = item.pack_relationship as ParentChildInventoryItem['packLevel'] | undefined;
  const packLevel = candidate && packLevels.has(candidate)
    ? candidate
    : item.parent_sku_id ? 'UNIT_OF_USE' : 'OUTER_BOX';
  const conversionFactor = item.conversion_factor && item.conversion_factor > 0 ? item.conversion_factor : 1;

  return {
    id: item.id,
    skuCode: item.sku_code || item.id,
    name: item.name || item.sku_code || 'Inventory Item',
    parentSkuId: item.parent_sku_id || null,
    parentSkuCode: item.parent_sku_code || null,
    packLevel,
    conversionFactor,
  };
}

/**
 * Formats Parent-Child Location Hierarchy Breadcrumb
 */
export function formatLocationHierarchy(
  location: {
    readonly id: string;
    readonly location_code?: string;
    readonly name: string;
    readonly parent_location_id?: string | null;
    readonly parent_location_name?: string | null;
    readonly hierarchy_level?: string;
    readonly branch_name?: string;
  },
): ParentChildLocationItem {
  const hierarchyLevels = new Set<ParentChildLocationItem['hierarchyLevel']>([
    'FACILITY',
    'ROOM',
    'ZONE',
    'SHELF_BIN',
    'VIRTUAL',
  ]);
  const candidate = location.hierarchy_level as ParentChildLocationItem['hierarchyLevel'] | undefined;
  const hierarchyLevel = candidate && hierarchyLevels.has(candidate)
    ? candidate
    : location.parent_location_id ? 'ROOM' : 'FACILITY';
  const parentName = location.parent_location_name || location.branch_name || null;
  const pathBreadcrumb = parentName ? `${parentName} ➔ ${location.name}` : location.name;

  return {
    id: location.id,
    code: location.location_code || location.id,
    name: location.name,
    parentLocationId: location.parent_location_id || null,
    parentLocationName: parentName,
    hierarchyLevel,
    pathBreadcrumb,
  };
}

export interface SystemDocumentQrInput {
  readonly documentType: 'STOCK_TRANSFER' | 'GOODS_RECEIPT' | 'PRESCRIPTION' | 'DISPENSING_RECEIPT' | 'INVOICE' | 'PURCHASE_ORDER' | 'SHIFT_REPORT' | 'AUDIT_LOG';
  readonly documentId: string;
  readonly documentNumber: string;
  readonly tenantId: string;
  readonly issuerUserId: string;
  readonly issueTimestampIso: string;
  /** Server-issued SHA-256 digest. This helper never invents or signs one. */
  readonly checksumSha256: string;
  /** Authoritative HTTPS endpoint that validates the persisted document. */
  readonly validationUrl: string;
}

export interface SystemDocumentQrOutput {
  readonly documentNumber: string;
  readonly qrPayloadString: string;
  readonly qrValidationUrl: string;
  readonly verificationSignature: string;
}

/**
 * Packages an authoritative document checksum and validation URL for QR encoding.
 * Authenticity remains a server responsibility; this helper does not sign data.
 */
export function generateDocumentQrPayload(doc: SystemDocumentQrInput): SystemDocumentQrOutput {
  const checksum = doc.checksumSha256.trim().toLowerCase();
  if (!/^[a-f0-9]{64}$/.test(checksum)) {
    throw new Error('Document QR payload requires a server-issued SHA-256 checksum.');
  }
  const validationUrl = new URL(doc.validationUrl);
  if (validationUrl.protocol !== 'https:') {
    throw new Error('Document QR validation URL must use HTTPS.');
  }
  const qrPayloadObj = {
    type: doc.documentType,
    id: doc.documentId,
    num: doc.documentNumber,
    tenant: doc.tenantId,
    user: doc.issuerUserId,
    ts: doc.issueTimestampIso,
    sig: checksum,
    vUrl: validationUrl.toString(),
  };

  return {
    documentNumber: doc.documentNumber,
    qrPayloadString: JSON.stringify(qrPayloadObj),
    qrValidationUrl: validationUrl.toString(),
    verificationSignature: checksum,
  };
}

export interface UomDeterminationInput {
  readonly skuCode: string;
  readonly name: string;
  readonly dosageForm?: string | undefined;
  readonly purchaseUnit?: string | undefined;
  readonly dispensingUnit?: string | undefined;
  readonly packSize?: number | undefined;
  readonly packPriceKes?: number | undefined;
}

export interface DeterminedUomResult {
  readonly skuCode: string;
  readonly dispensingUom: 'CAPSULE' | 'TABLET' | 'ML' | 'VIAL' | 'AMPOULE' | 'SACHET' | 'PATCH' | 'DOSE' | 'UNIT';
  readonly purchaseUom: string;
  readonly uomCategory: 'SOLID_ORAL' | 'LIQUID_VOLUME' | 'INJECTABLE' | 'TOPICAL' | 'UNIT_PACK';
  readonly conversionFactor: number;
  readonly unitPriceKes: number | null;
  readonly formattedSummary: string;
}

/**
 * Determines Unit of Measure (UOM) for inventory items, pack sizes, and unit price calculations
 */
export function determineItemUom(input: UomDeterminationInput): DeterminedUomResult {
  const text = `${input.skuCode} ${input.name} ${input.dosageForm || ''}`.toUpperCase();

  let dispensingUom: DeterminedUomResult['dispensingUom'] = 'UNIT';
  let uomCategory: DeterminedUomResult['uomCategory'] = 'UNIT_PACK';

  if (text.includes('CAPSULE') || text.includes('CAP') || text.includes('CAPS')) {
    dispensingUom = 'CAPSULE';
    uomCategory = 'SOLID_ORAL';
  } else if (text.includes('INJ') || text.includes('VIAL')) {
    dispensingUom = 'VIAL';
    uomCategory = 'INJECTABLE';
  } else if (text.includes('AMP') || text.includes('AMPOULE')) {
    dispensingUom = 'AMPOULE';
    uomCategory = 'INJECTABLE';
  } else if (text.includes('SYRUP') || text.includes('SUSP') || text.includes('LIQUID') || text.includes('ML')) {
    dispensingUom = 'ML';
    uomCategory = 'LIQUID_VOLUME';
  } else if (text.includes('SACHET')) {
    dispensingUom = 'SACHET';
    uomCategory = 'UNIT_PACK';
  } else if (text.includes('PATCH')) {
    dispensingUom = 'PATCH';
    uomCategory = 'TOPICAL';
  } else if (text.includes('TABLET') || text.includes(' TAB')) {
    dispensingUom = 'TABLET';
    uomCategory = 'SOLID_ORAL';
  }

  const declaredUom = input.dispensingUnit?.trim().toUpperCase();
  const supportedUoms = new Set<DeterminedUomResult['dispensingUom']>([
    'CAPSULE', 'TABLET', 'ML', 'VIAL', 'AMPOULE', 'SACHET', 'PATCH', 'DOSE', 'UNIT',
  ]);
  if (declaredUom && supportedUoms.has(declaredUom as DeterminedUomResult['dispensingUom'])) {
    dispensingUom = declaredUom as DeterminedUomResult['dispensingUom'];
  }

  const conversionFactor = input.packSize && input.packSize > 0 ? input.packSize : 1;
  const purchaseUom = input.purchaseUnit?.trim() || 'UNIT';
  const unitPriceKes = input.packPriceKes != null && input.packPriceKes >= 0
    ? Math.round((input.packPriceKes / conversionFactor) * 100) / 100
    : null;
  const formattedSummary = unitPriceKes == null
    ? `1 ${purchaseUom} = ${conversionFactor} ${dispensingUom}`
    : `1 ${purchaseUom} = ${conversionFactor} ${dispensingUom} (KES ${unitPriceKes.toFixed(2)} / ${dispensingUom})`;

  return {
    skuCode: input.skuCode,
    dispensingUom,
    purchaseUom,
    uomCategory,
    conversionFactor,
    unitPriceKes,
    formattedSummary,
  };
}

export interface GoodsReceiptScanVerificationInput {
  readonly scannedInput: string;
  readonly expectedLines: readonly {
    readonly lineKey: string;
    readonly skuCode: string;
    readonly barcode?: string | undefined;
    readonly expectedQuantity: number;
    readonly acceptedQuantity: number;
    readonly batchNumber?: string | undefined;
  }[];
}

export interface GoodsReceiptScanVerificationResult {
  readonly matchFound: boolean;
  readonly matchedLineKey?: string | undefined;
  readonly matchedSkuCode?: string | undefined;
  readonly updatedAcceptedQuantity: number;
  readonly parsedBarcode: ParsedBarcodeResult;
  readonly discrepancyDetected: boolean;
  readonly statusNote: string;
}

/**
 * Scans goods receipt items (2D DataMatrix or 1D barcode) to verify received quantity and batch
 */
export function verifyGoodsReceiptScan(
  input: GoodsReceiptScanVerificationInput,
): GoodsReceiptScanVerificationResult {
  const parsed = parseBarcodeOrDataMatrix(input.scannedInput);
  const identifiers = new Set(parsed.lookupValues.map((value) => value.toUpperCase()));
  const identifierMatches = input.expectedLines.filter((line) => (
    identifiers.has(line.skuCode.trim().toUpperCase())
    || Boolean(line.barcode && identifiers.has(line.barcode.trim().toUpperCase()))
  ));
  if (identifierMatches.length === 0) {
    return {
      matchFound: false,
      updatedAcceptedQuantity: 0,
      parsedBarcode: parsed,
      discrepancyDetected: true,
      statusNote: 'The scanned code does not match any SKU expected on this transfer.',
    };
  }

  const batch = parsed.batchNumber?.trim().toUpperCase();
  const batchMatches = batch
    ? identifierMatches.filter((line) => line.batchNumber?.trim().toUpperCase() === batch)
    : identifierMatches;
  if (batch && batchMatches.length === 0) {
    return {
      matchFound: false,
      updatedAcceptedQuantity: 0,
      parsedBarcode: parsed,
      discrepancyDetected: true,
      statusNote: `SKU matched, but batch ${parsed.batchNumber} is not expected on this transfer.`,
    };
  }
  if (batchMatches.length !== 1) {
    return {
      matchFound: false,
      updatedAcceptedQuantity: 0,
      parsedBarcode: parsed,
      discrepancyDetected: true,
      statusNote: 'This SKU has multiple expected batches. Scan a GS1 code containing the batch number.',
    };
  }

  const matchedLine = batchMatches[0]!;
  const newQty = matchedLine.acceptedQuantity + 1;
  const discrepancy = newQty > matchedLine.expectedQuantity;

  return {
    matchFound: true,
    matchedLineKey: matchedLine.lineKey,
    matchedSkuCode: matchedLine.skuCode,
    updatedAcceptedQuantity: newQty,
    parsedBarcode: parsed,
    discrepancyDetected: discrepancy,
    statusNote: discrepancy
      ? `${matchedLine.skuCode} is already fully counted (${matchedLine.expectedQuantity}).`
      : `${matchedLine.skuCode} accepted count updated to ${newQty}/${matchedLine.expectedQuantity}.`,
  };
}
