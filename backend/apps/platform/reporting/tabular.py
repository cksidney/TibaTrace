"""Real tabular formats. All workbook cells are literal strings, never formulas."""
import csv
import io
import re
import zipfile
from xml.sax.saxutils import escape


def csv_bytes(rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for row in rows:
        values = []
        for value in row:
            text = str(value if value is not None else "")
            # Spreadsheet applications may evaluate imported CSV values.
            values.append("'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text)
        writer.writerow(values)
    return buffer.getvalue().encode("utf-8-sig")


def xlsx_bytes(rows):
    sheet_rows = []
    for index, row in enumerate(rows, 1):
        cells = []
        for column, value in enumerate(row, 1):
            name, number = "", column
            while number:
                number, remainder = divmod(number - 1, 26)
                name = chr(65 + remainder) + name
            text = escape(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value if value is not None else "")))
            cells.append(f'<c r="{name}{index}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>')
        sheet_rows.append(f'<row r="{index}">{"".join(cells)}</row>')
    xml_header = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    files = {
        "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Report" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>',
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for filename, content in files.items():
            archive.writestr(filename, xml_header + content)
    return buffer.getvalue()
