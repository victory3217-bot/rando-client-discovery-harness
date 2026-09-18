# -*- coding: utf-8 -*-
"""Documents built in memory for the intake tests.

Nothing here is committed as a file. ``.gitignore`` blocks ``*.pdf``, ``*.docx``, ``*.pptx`` and
``*.xlsx`` so that an uploaded document can never reach a commit, and that rule applies to test
fixtures too. Generating them instead turns out to be the better arrangement: a public
repository ends up with no opaque binaries in it, and every byte a test parses is visible in
this file.

Every builder takes the text to embed, so the canary tests can put a unique string inside each
format and then go looking for it.
"""
from __future__ import annotations

import csv
import io
import zipfile

CANARY = "ZQX-CANARY-7f3d9a2b-DO-NOT-LEAK"

SAMPLE_PARAGRAPHS = [
    "메콩델타 상수도 사업자는 건기 염분 상승 구간에서 측정 주기를 늘려야 한다.",
    "현장 인력은 수동 채수에 의존하고 있어 주기를 늘리기 어렵다.",
    "The regional utilities operate two treatment plants and several reservoirs.",
]


# ---------------------------------------------------------------------------
# text formats
# ---------------------------------------------------------------------------

def make_txt(text: str = CANARY, *, encoding: str = "utf-8") -> bytes:
    body = f"{SAMPLE_PARAGRAPHS[0]}\n\n{text}\n\n{SAMPLE_PARAGRAPHS[1]}\n"
    return body.encode(encoding)


def make_md(text: str = CANARY) -> bytes:
    body = (
        "# 시장 개요\n\n"
        f"{SAMPLE_PARAGRAPHS[0]}\n\n"
        "## 운영 현황\n\n"
        f"{text}\n\n"
        "## 결론\n\n"
        f"{SAMPLE_PARAGRAPHS[2]}\n"
    )
    return body.encode("utf-8")


def make_csv(text: str = CANARY, *, rows: int = 4) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["utility", "region", "note"])
    writer.writerow(["Fictional Aqua", "Delta", text])
    for index in range(rows - 1):
        writer.writerow([f"Fictional Utility {index}", "Delta", SAMPLE_PARAGRAPHS[2]])
    return buffer.getvalue().encode("utf-8")


def make_html(text: str = CANARY) -> bytes:
    body = f"""<!doctype html>
<html><head>
  <title>Fictional market note</title>
  <style>.hidden {{ display: none; }} /* {text}-IN-STYLE */</style>
  <script>var tracking = "{text}-IN-SCRIPT";</script>
</head>
<body>
  <!-- internal note: {text}-IN-COMMENT -->
  <main>
    <h2>운영 현황</h2>
    <p>{SAMPLE_PARAGRAPHS[0]}</p>
    <p>{text}</p>
    <noscript>{text}-IN-NOSCRIPT</noscript>
    <table><tr><td>Fictional Aqua</td><td>Delta</td></tr></table>
  </main>
</body></html>
"""
    return body.encode("utf-8")


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def make_pdf(text: str = CANARY, *, with_text_layer: bool = True) -> bytes:
    """A minimal, valid PDF assembled by hand.

    Written out rather than generated with a library because none of the four intake
    dependencies can *create* a PDF, and adding a fifth dependency to produce test input would
    be a poor trade. The content stream is uncompressed, so what the parser reads is visible
    here.

    ``with_text_layer=False`` produces a page with no text operators at all — a stand-in for a
    scan, which must come back as ``EXTRACT_NO_TEXT_LAYER``.
    """
    escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    # WinAnsi cannot represent Hangul, so the embedded text stays ASCII. What matters for these
    # tests is that a known string survives extraction.
    ascii_text = escaped.encode("ascii", "replace").decode("ascii")

    stream = (
        f"BT /F1 12 Tf 72 720 Td ({ascii_text}) Tj ET" if with_text_layer else "q Q"
    ).encode("ascii")

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode("ascii")

    return bytes(out)


# ---------------------------------------------------------------------------
# OOXML
# ---------------------------------------------------------------------------

def make_docx(text: str = CANARY) -> bytes:
    from docx import Document

    document = Document()
    document.add_heading("시장 개요", level=1)
    document.add_paragraph(SAMPLE_PARAGRAPHS[0])
    document.add_paragraph(text)
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "utility"
    table.cell(0, 1).text = "region"
    table.cell(1, 0).text = "Fictional Aqua"
    table.cell(1, 1).text = "Delta"

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def make_pptx(text: str = CANARY) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "운영 현황"
    box = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(6), Inches(2))
    box.text_frame.text = SAMPLE_PARAGRAPHS[0]
    slide.notes_slide.notes_text_frame.text = text

    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def make_xlsx(text: str = CANARY) -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "utilities-ops"
    sheet.append(["utility", "region", "note"])
    sheet.append(["Fictional Aqua", "Delta", text])
    sheet.append(["Fictional Utility 2", "Delta", SAMPLE_PARAGRAPHS[2]])

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# adversarial input
# ---------------------------------------------------------------------------

def make_zip_bomb(*, declared_size: int = 500 * 1024 * 1024) -> bytes:
    """A ZIP whose central directory declares far more than it delivers.

    Built by writing a highly compressible entry, which is exactly the shape the uncompressed
    -size limit exists to catch.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", b"\x00" * declared_size)
    return buffer.getvalue()


def make_non_ooxml_zip() -> bytes:
    """A ZIP that is not an Office package at all."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "not an office document")
    return buffer.getvalue()


def make_encrypted_pdf_marker() -> bytes:
    """A PDF whose trailer declares encryption, without a usable empty password."""
    base = make_pdf("locked")
    return base.replace(b"/Root 1 0 R", b"/Root 1 0 R /Encrypt 6 0 R")


#: Every well-formed builder, keyed by the ``FileType`` name it produces.
BUILDERS = {
    "TXT": make_txt,
    "MD": make_md,
    "CSV": make_csv,
    "HTML": make_html,
    "PDF": make_pdf,
    "DOCX": make_docx,
    "PPTX": make_pptx,
    "XLSX": make_xlsx,
}
