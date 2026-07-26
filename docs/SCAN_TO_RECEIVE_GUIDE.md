# TibaTrace Scan-to-Receive & GRN Runbook

## 1. Receiving Workflow
1. **Session Opening**: Receiver opens a `ReceivingSession` referencing an approved Purchase Order and Delivery Note number.
2. **Barcode Scanning**: Items are scanned via standard GS1 / GTIN / internal barcodes. The system validates:
   - Item belongs to PO line.
   - Batch number and expiry date are captured.
   - Expiry date is in the future and meets minimum shelf life.
3. **GRN Posting**: Receiver posts the immutable `GoodsReceivedNote`. The system atomically:
   - Posts `PURCHASE_RECEIPT` entries to the append-only `InventoryLedgerEntry`.
   - Places new stock into `QUARANTINED` status.
   - Updates PO line received quantities.
