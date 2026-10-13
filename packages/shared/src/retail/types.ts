export interface RetailStoreDTO {
  readonly id: string;
  readonly branch: string;
  readonly name: string;
  readonly location_type: string;
  readonly status: string;
  readonly quarantine_capability?: boolean;
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
  readonly refundable_quantity?: string;
  readonly issued_batches?: readonly { batch_id: string; batch_number: string; expiry_date: string; quantity: string }[];
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
  readonly receipt: RetailCashReceiptDTO | null;
  readonly refunded_total?: string;
  readonly refund_requests?: readonly RetailRefundRequestDTO[];
}

export interface RetailRefundRequestDTO {
  id: string;
  status: 'REQUESTED' | 'APPROVED' | 'REJECTED' | 'COMPLETED';
  reason: string;
  amount: string;
  currency: string;
  receipt?: RetailCashRefundDTO | null;
  lines: readonly { original_line: string; description: string; quantity: string; amount: string; return_to_stock: boolean; inventory_batch: string | null }[];
}

export interface RetailCashRefundDTO {
  id: string;
  refund_number: string;
  original_receipt_number: string;
  amount: string;
  currency: string;
  completed_at: string;
  print_job: { id: string; status: string; transport: string } | null;
}

export interface RetailRefundInput {
  device_id: string;
  reason: string;
  idempotency_key: string;
  return_location_id?: string;
  lines: readonly { line_id: string; quantity: string; return_to_stock: boolean; inventory_batch_id?: string }[];
}

export interface RetailCashReceiptDTO {
  readonly receipt_number: string;
  readonly tender_type: 'CASH';
  readonly amount: string;
  readonly cash_received: string;
  readonly change_due: string;
  readonly currency: string;
  readonly lines_snapshot: readonly {
    readonly sku_code: string;
    readonly description: string;
    readonly quantity: string;
    readonly unit: string;
    readonly unit_price: string;
    readonly discount_amount: string;
    readonly tax_amount: string;
    readonly line_total: string;
  }[];
  readonly totals_snapshot: {
    readonly subtotal: string;
    readonly discount_total: string;
    readonly tax_total: string;
    readonly total: string;
  };
  readonly settled_at: string;
  readonly disclaimer: string;
  readonly print_job: { readonly id: string; readonly status: string; readonly transport: string } | null;
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
