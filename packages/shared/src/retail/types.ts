export interface RetailStoreDTO {
  readonly id: string;
  readonly branch: string;
  readonly name: string;
  readonly location_type: string;
  readonly status: string;
}

export interface RetailInventoryContextDTO {
  readonly store: string;
  readonly available_quantity: string;
  readonly stock_state: 'IN_STOCK' | 'OUT_OF_STOCK' | 'INSUFFICIENT' | 'NOT_TRACKED';
  readonly policy: { readonly stock_tracking_required?: boolean };
}

export interface RetailTransactionLineDTO {
  readonly id: string;
  readonly sku: string;
  readonly sku_code: string;
  readonly description_snapshot: string;
  readonly unit: string;
  readonly quantity: string;
  readonly unit_price: string;
  readonly discount_amount: string;
  readonly tax_amount: string;
  readonly line_total: string;
  readonly currency: string;
  readonly price_snapshot: { readonly source?: string; readonly source_reference?: string };
  readonly scan_source: string;
  readonly inventory_context: RetailInventoryContextDTO;
}

export interface RetailTransactionDTO {
  readonly id: string;
  readonly transaction_number: string;
  readonly state: string;
  readonly branch: string;
  readonly branch_code: string;
  readonly store: string;
  readonly register: string;
  readonly register_code: string;
  readonly register_session: string;
  readonly operator_shift: string;
  readonly business_day: string;
  readonly currency: string;
  readonly subtotal: string;
  readonly discount_total: string;
  readonly tax_total: string;
  readonly total: string;
  readonly hold_reason: string;
  readonly lines: readonly RetailTransactionLineDTO[];
}

export interface RetailCatalogueItemDTO {
  readonly sku_id: string;
  readonly sku_code: string;
  readonly display_name: string;
  readonly unit: string;
  readonly stock_tracking_required: boolean;
  readonly available_quantity: string;
  readonly stock_state: string;
  readonly unit_price: string;
  readonly currency: string;
  readonly price_source: string;
  readonly price_reference: string;
}
