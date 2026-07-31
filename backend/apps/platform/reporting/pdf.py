"""Minimal PDF builder and QR helpers for report downloads."""
from __future__ import annotations

import zlib


def qr_matrix(payload: str) -> list[list[bool]]:
    import qrcode

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=1,
        border=2,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    return qr.get_matrix()


def _escape_pdf_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def _wrap(text: str, width: int) -> list[str]:
    words = (text or "").split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


class SimplePDF:
    """Compact PDF writer for professional multi-page report packs."""

    def __init__(self, *, title: str, author: str):
        self.title = title
        self.author = author
        self.page_width = 595
        self.page_height = 842
        self.margin = 48
        self.y = self.page_height - self.margin
        self.lines: list[str] = []
        self.pages: list[list[str]] = []

    def _ensure_space(self, need: float = 16) -> None:
        if self.y - need < self.margin:
            self.pages.append(self.lines)
            self.lines = []
            self.y = self.page_height - self.margin

    def heading(self, text: str, size: int = 16) -> None:
        self._ensure_space(size + 10)
        self.lines.append(
            f"BT /F1 {size} Tf {self.margin} {self.y} Td ({_escape_pdf_text(text)}) Tj ET"
        )
        self.y -= size + 8

    def subheading(self, text: str) -> None:
        self.heading(text, size=12)

    def text(self, text: str, size: int = 10) -> None:
        for chunk in _wrap(text, 92):
            self._ensure_space(size + 4)
            self.lines.append(
                f"BT /F1 {size} Tf {self.margin} {self.y} Td ({_escape_pdf_text(chunk)}) Tj ET"
            )
            self.y -= size + 3

    def key_value(self, label: str, value: str) -> None:
        self.text(f"{label}: {value}", size=10)

    def spacer(self, amount: float = 10) -> None:
        self.y -= amount

    def rule(self) -> None:
        self._ensure_space(8)
        y = self.y
        self.lines.append(f"{self.margin} {y} m {self.page_width - self.margin} {y} l S")
        self.y -= 12

    def qr_block(self, matrix: list[list[bool]], *, label: str) -> None:
        module = 2.2
        size = len(matrix) * module
        self._ensure_space(size + 36)
        self.text(label, size=9)
        origin_x = self.margin
        origin_y = self.y - size
        for row_index, row in enumerate(matrix):
            for col_index, filled in enumerate(row):
                if not filled:
                    continue
                x = origin_x + col_index * module
                y = origin_y + (len(matrix) - 1 - row_index) * module
                self.lines.append(f"{x:.2f} {y:.2f} {module:.2f} {module:.2f} re f")
        self.y = origin_y - 14

    def build(self) -> bytes:
        if self.lines:
            self.pages.append(self.lines)
        return _assemble_pdf(
            self.title,
            self.author,
            self.page_width,
            self.page_height,
            self.pages,
        )


def _assemble_pdf(
    title: str,
    author: str,
    width: int,
    height: int,
    pages: list[list[str]],
) -> bytes:
    font_obj = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>"]

    page_ids = []
    next_id = 3
    for _ in pages:
        page_ids.append(next_id)
        next_id += 2
    font_id = next_id
    info_id = next_id + 1

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode())

    for index, ops in enumerate(pages):
        page_id = page_ids[index]
        content_id = page_id + 1
        stream = ("\n".join(["0.18 w", *ops])).encode("latin-1", errors="replace")
        compressed = zlib.compress(stream)
        content = (
            f"<< /Length {len(compressed)} /Filter /FlateDecode >>\nstream\n".encode()
            + compressed
            + b"\nendstream"
        )
        page_dict = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode()
        objects.append(page_dict)
        objects.append(content)

    objects.append(font_obj)
    objects.append(
        (
            f"<< /Title ({_escape_pdf_text(title)}) "
            f"/Author ({_escape_pdf_text(author)}) "
            f"/Producer (TibaTrace Reporting) >>"
        ).encode()
    )

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{index} 0 obj\n".encode())
        out.extend(obj)
        out.extend(b"\nendobj\n")
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode())
    out.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {info_id} 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n"
        ).encode()
    )
    return bytes(out)


def build_pdf_bytes(*, title: str, author: str, builder) -> bytes:
    pdf = SimplePDF(title=title, author=author)
    builder(pdf)
    return pdf.build()
