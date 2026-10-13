/** Render only an authoritative snapshot, escaping every server/user value. */
export function renderPrintDocument(value: unknown): string {
  if (!value || typeof value !== 'object') throw new Error('Invalid document snapshot.');
  const document = value as Record<string, unknown>;
  const snapshot = document['snapshot'];
  if (!snapshot || typeof snapshot !== 'object') throw new Error('Document snapshot missing.');
  const body = snapshot as Record<string, unknown>;
  const escape = (text: unknown) => String(text ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!);
  const rows = (Array.isArray(body['lines']) ? body['lines'] : []).map((item: unknown) => {
    const line = item && typeof item === 'object' ? item as Record<string, unknown> : {};
    return `<tr><td>${escape(line['medicine'] ?? line['description'] ?? line['sku_code'])}<br>${escape(line['batch_number'])}</td><td>${escape(line['quantity'])} ${escape(line['unit'])}</td><td>${escape(line['line_total'] ?? line['amount'])}</td></tr>`;
  }).join('');
  const payment = body['payment'] && typeof body['payment'] === 'object' ? body['payment'] as Record<string, unknown> : {};
  const totals = body['totals'] && typeof body['totals'] === 'object' ? body['totals'] as Record<string, unknown> : {};
  const patient = body['patient'] && typeof body['patient'] === 'object' ? body['patient'] as Record<string, unknown> : {};
  const number = escape(document['document_number'] ?? body['document_number']);
  if (body['document_type'] === 'MEDICINE_LABEL') {
    const label = body['label'] && typeof body['label'] === 'object' ? body['label'] as Record<string, unknown> : {};
    return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline';"><title>${number}</title><style>body{font-family:Arial,sans-serif;font-size:12px;color:#000;margin:3mm}h1{font-size:16px;margin:2mm 0}p{margin:2mm 0;overflow-wrap:anywhere}</style></head><body><strong>${escape(label['pharmacy'])}</strong><p>${escape(label['patient_name'])}</p><h1>${escape(label['medicine_name'])}</h1><strong>${escape(label['directions'])}</strong><p>${escape(label['quantity'])} ${escape(label['unit'])}</p><p>${escape(label['storage_instructions'])}</p><p>${escape(Array.isArray(label['warnings']) ? label['warnings'].join(' · ') : '')}</p><p>Batch ${escape(label['batch'])} · Expiry ${escape(label['expiry'])}</p><p>${escape(document['copy_classification'])} · copy ${escape(document['copy_number'])} · ${number}</p></body></html>`;
  }
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline';"><title>${number}</title><style>body{font-family:Arial,sans-serif;font-size:12px;color:#000;margin:6mm}h1{font-size:18px}table{width:100%;border-collapse:collapse}td{padding:5px 2px;border-bottom:1px solid #777;vertical-align:top}td:last-child{text-align:right}.copy{font-weight:bold}p{overflow-wrap:anywhere}@media print{body{margin:4mm}}</style></head><body><h1>TibaTrace</h1><p class="copy">${escape(document['copy_classification'])} · copy ${escape(document['copy_number'])}</p><p>${number}<br>${escape(body['issued_at'])}</p>${patient['name'] ? `<p>${escape(patient['name'])} · ${escape(patient['number'])}</p>` : ''}<table>${rows}</table><p><strong>${escape(payment['currency'])} ${escape(totals['total'] ?? payment['amount'] ?? payment['settled_amount'] ?? body['amount'])}</strong></p><p>Cash received ${escape(payment['cash_received'])}<br>Change ${escape(payment['change_due'])}</p><p>${escape(body['disclaimer'] ?? 'Internal document — not a fiscal/eTIMS receipt.')}</p><p>Document reference ${escape(document['document_hash'])}</p></body></html>`;
}
