import { describe, expect, it } from 'vitest';

import { parseCsvForImport } from './bulkCsv.js';

describe('parseCsvForImport', () => {
  it('accepts BOM-prefixed headers, CRLF, and quoted fields', () => {
    const result = parseCsvForImport(
      '\uFEFFsku_code,unit_price,notes\r\nSKU-001,250.00,"pack, retail"\r\n',
      ['sku_code', 'unit_price'],
    );

    expect(result.error).toBeNull();
    expect(result.rows).toEqual([
      { line: 2, values: { sku_code: 'SKU-001', unit_price: '250.00', notes: 'pack, retail' } },
    ]);
  });

  it('reports missing required headers before any row can be sent', () => {
    const result = parseCsvForImport('sku_code,unit_price\nSKU-001,250.00\n', [
      'sku_code',
      'unit_price',
      'tax_inclusive',
    ]);

    expect(result.rows).toEqual([]);
    expect(result.error).toContain('tax_inclusive');
  });

  it('rejects malformed quotes rather than guessing the column boundary', () => {
    const result = parseCsvForImport('sku_code,unit_price\nSKU-001,"250.00\n', [
      'sku_code',
      'unit_price',
    ]);

    expect(result.rows).toEqual([]);
    expect(result.error).toContain('quoted field');
  });
});
