import { describe, expect, it } from 'vitest';
import { renderPrintDocument } from '../../electron/printDocument.js';

describe('authoritative printer rendering', () => {
  it('escapes every value and carries immutable copy/document references', () => {
    const html = renderPrintDocument({ document_number: 'RCP-1', document_hash: 'hash', copy_number: 2, copy_classification: 'REPRINT',
      snapshot: { lines: [{ description: '<img src="https://bad" onerror="steal()">', quantity: '1', unit: 'EA', line_total: '25.00' }],
        payment: { amount: '25.00', currency: 'KES' }, disclaimer: 'Internal receipt' } });
    expect(html).toContain('REPRINT · copy 2');
    expect(html).toContain('RCP-1');
    expect(html).toContain('&lt;img');
    expect(html).not.toContain('<img');
    expect(html).toContain("default-src 'none'");
  });
  it('refuses absent snapshot rather than printing invented receipt', () => {
    expect(() => renderPrintDocument({})).toThrow('snapshot missing');
  });
  it('renders approved label instructions and warnings without raw markup', () => {
    const html = renderPrintDocument({ document_number: 'LBL-1', copy_number: 1, copy_classification: 'ORIGINAL',
      snapshot: { document_type: 'MEDICINE_LABEL', label: { medicine_name: 'Actual medicine', directions: 'Take one daily',
        warnings: ['Avoid <strong>alcohol</strong>'], batch: 'B-1', expiry: '2028-12-31' } } });
    expect(html).toContain('Take one daily');
    expect(html).toContain('Avoid &lt;strong&gt;alcohol&lt;/strong&gt;');
    expect(html).toContain('Batch B-1');
    expect(html).not.toContain('<strong>alcohol</strong>');
  });
});
