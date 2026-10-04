/**
 * Small CSV reader for controlled imports.
 *
 * It intentionally supports the CSV features staff exports actually contain
 * (UTF-8 BOM, CRLF, quoted commas, and escaped quotes) without adding a
 * dependency to the HQ bundle.  Parsing is local: the API receives structured
 * values only after the operator has inspected a dry-run report.
 */

export interface CsvImportRow {
  readonly line: number;
  readonly values: Readonly<Record<string, string>>;
}

export interface CsvParseResult {
  readonly error: string | null;
  readonly rows: readonly CsvImportRow[];
}

function normaliseHeader(value: string): string {
  return value.replace(/^\uFEFF/, '').trim().toLowerCase();
}

function parseRecords(source: string): { readonly error: string | null; readonly records: readonly string[][] } {
  const records: string[][] = [];
  let record: string[] = [];
  let value = '';
  let quoted = false;

  for (let index = 0; index < source.length; index += 1) {
    const character = source[index] ?? '';
    if (quoted) {
      if (character === '"') {
        if (source[index + 1] === '"') {
          value += '"';
          index += 1;
        } else {
          quoted = false;
        }
      } else {
        value += character;
      }
      continue;
    }
    if (character === '"') {
      if (value) return { error: 'A quote may only begin at the start of a CSV field.', records: [] };
      quoted = true;
    } else if (character === ',') {
      record.push(value);
      value = '';
    } else if (character === '\n') {
      record.push(value.replace(/\r$/, ''));
      records.push(record);
      record = [];
      value = '';
    } else {
      value += character;
    }
  }
  if (quoted) return { error: 'The CSV ends inside a quoted field.', records: [] };
  if (value || record.length) {
    record.push(value.replace(/\r$/, ''));
    records.push(record);
  }
  return { error: null, records };
}

export function parseCsvForImport(
  source: string,
  requiredColumns: readonly string[],
): CsvParseResult {
  const parsed = parseRecords(source);
  if (parsed.error) return { error: parsed.error, rows: [] };
  const nonEmpty = parsed.records
    .map((record, index) => ({ line: index + 1, record }))
    .filter(({ record }) => record.some((value) => value.trim()));
  if (!nonEmpty.length) return { error: 'The CSV is empty.', rows: [] };

  const headers = nonEmpty[0]!.record.map(normaliseHeader);
  const duplicateHeader = headers.find((header, index) => header && headers.indexOf(header) !== index);
  if (duplicateHeader) return { error: `The header "${duplicateHeader}" appears more than once.`, rows: [] };
  const missing = requiredColumns.filter((column) => !headers.includes(column));
  if (missing.length) return {
    error: `Missing required column${missing.length === 1 ? '' : 's'}: ${missing.join(', ')}.`,
    rows: [],
  };

  const rows: CsvImportRow[] = [];
  for (let index = 1; index < nonEmpty.length; index += 1) {
    const { line, record } = nonEmpty[index]!;
    if (record.length > headers.length) {
      return { error: `Row ${line} has more columns than the header.`, rows: [] };
    }
    const values: Record<string, string> = {};
    headers.forEach((header, column) => {
      if (header) values[header] = (record[column] ?? '').trim();
    });
    rows.push({ line, values });
  }
  if (!rows.length) return { error: 'The CSV has a header but no data rows.', rows: [] };
  return { error: null, rows };
}

export function downloadCsvTemplate(
  filename: string,
  headers: readonly string[],
  example: readonly string[],
): void {
  const escape = (value: string) => /[",\r\n]/.test(value)
    ? `"${value.replace(/"/g, '""')}"`
    : value;
  const text = `${headers.map(escape).join(',')}\r\n${example.map(escape).join(',')}\r\n`;
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
