"""Build synthetic layout fixtures. No journal, publisher, or AI source material.

Run with the project's .venv Python. Ground truth is authoring input, not extractor
output; the extraction tests compare the two independently.
"""
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import reportlab

ROOT = Path(__file__).resolve().parent
LABEL = "SELF-BUILT SYNTHETIC PDF - NOT A JOURNAL ARTICLE"


def new_canvas(name, size=(612, 792)):
    c = canvas.Canvas(str(ROOT / name), pagesize=size, invariant=1, pageCompression=0)
    c.setTitle(LABEL)
    c.setAuthor("DocStyle AI synthetic fixture builder")
    return c


def line(c, text, x, top, font="Times-Roman", size=11, height=792):
    c.setFont(font, size)
    c.drawString(x, height - top, text)


def plain_minimal_pdf(path, font_dictionary):
    # Correct xref offsets, deliberately missing BaseFont for the missing-font test.
    stream = b"BT /F1 11 Tf 60 650 Td (Missing font metadata fixture 12345) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        font_dictionary,
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(str(index).encode() + b" 0 obj\n" + obj + b"\nendobj\n")
    xref = len(output)
    output.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    path.write_bytes(output)


def build():
    ROOT.mkdir(parents=True, exist_ok=True)
    truth = {"provenance": LABEL, "coordinateSystem": "top-left PDF points, displayed rotation", "fixtures": {}}
    c = new_canvas("digital.pdf")
    for page in range(1, 4):
        line(c, LABEL, 60, 30, "Helvetica", 8)
        line(c, str(page), 300, 766, "Helvetica", 8)
        if page == 1:
            line(c, "Synthetic Digital Layout", 60, 90, "Times-Bold", 20)
            line(c, "Author: Example Researcher", 60, 118, "Times-Roman", 10)
            line(c, "Abstract: Layout measurement test only.", 60, 155)
            line(c, "Keywords: synthetic; measurement", 60, 177)
            line(c, "1 Introduction", 60, 210, "Times-Bold", 14)
        if page == 3:
            line(c, "References", 60, 110, "Times-Bold", 14)
            for i in range(6):
                line(c, f"[{i + 1}] Synthetic reference entry, year 2026.", 60, 145 + i * 18, size=9)
        else:
            for i in range(10):
                line(c, f"Body line {i + 1}: measured body font size is eleven points.", 60, 260 + i * 18)
        c.showPage()
    c.save()
    truth["fixtures"]["digital.pdf"] = {"pages": 3, "width": 612, "height": 792, "title": {"text": "Synthetic Digital Layout", "font": "Times-Bold", "size": 20, "x": 60, "baselineTop": 90}, "body": {"font": "Times-Roman", "size": 11, "baselineDistance": 18}, "referenceSize": 9, "headerRepeated": True}

    c = new_canvas("two_column.pdf")
    line(c, LABEL, 40, 30, "Helvetica", 8)
    line(c, "Synthetic Two Column Layout", 60, 90, "Times-Bold", 20)
    for i in range(18):
        line(c, f"Left column sample line {i + 1}.", 50, 155 + i * 20, size=10)
        line(c, f"Right column sample line {i + 1}.", 330, 155 + i * 20, size=10)
    c.save()
    truth["fixtures"]["two_column.pdf"] = {"pages": 1, "columns": 2, "bodySize": 10, "columnOrigins": [50, 330], "titleSpansColumns": True}

    c = new_canvas("rotated.pdf")
    c.setPageRotation(90)
    line(c, "Rotated synthetic evidence", 60, 90, "Helvetica", 16, height=612)
    for i in range(6):
        line(c, f"Rotated body evidence {i + 1}.", 60, 155 + i * 20, "Helvetica", 11, height=612)
    c.save()
    # reportlab changes the page media box to 792 x 612, then /Rotate=90
    # yields a displayed 612 x 792 page. Content becomes vertical on that page.
    truth["fixtures"]["rotated.pdf"] = {"pages": 1, "width": 612, "height": 792, "rotation": 90, "fontSize": 16, "text": "Rotated synthetic evidence"}

    image = Image.new("RGB", (1224, 1584), "white")
    draw = ImageDraw.Draw(image)
    raster_font = ImageFont.load_default(size=22)
    draw.text((100, 150), LABEL, fill="black", font=raster_font)
    draw.text((100, 250), "Scanned fixture: raster only, no PDF text layer.", fill="black", font=raster_font)
    for i in range(12):
        draw.text((100, 340 + 45 * i), f"Raster paragraph line {i + 1} - needs OCR", fill="black", font=raster_font)
    c = new_canvas("scanned.pdf")
    c.drawImage(ImageReader(image), 0, 0, width=612, height=792)
    c.save()
    truth["fixtures"]["scanned.pdf"] = {"pages": 1, "characters": 0, "images": 1, "status": "needs_ocr"}

    c = new_canvas("table_formula.pdf")
    line(c, LABEL, 60, 30, "Helvetica", 8)
    line(c, "Synthetic Table and Formula", 60, 90, "Times-Bold", 20)
    line(c, "Table 1. Synthetic observations", 60, 140, size=10)
    c.setLineWidth(1)
    for y in (180, 210, 240, 270):
        c.line(60, 792 - y, 500, 792 - y)
    for x in (60, 210, 350, 500):
        c.line(x, 792 - 180, x, 792 - 270)
    for row, texts in enumerate([["Item", "Value", "Unit"], ["Sample A", "12", "pt"], ["Sample B", "10", "pt"]]):
        for x, text in zip((70, 220, 360), texts):
            line(c, text, x, 200 + row * 30, size=11)
    line(c, "Note: Entire table is self-built.", 60, 292, size=9)
    line(c, "y = a + b x", 240, 360, "Times-Italic", 12)
    line(c, "(1)", 480, 360, size=12)
    c.save()
    truth["fixtures"]["table_formula.pdf"] = {"pages": 1, "tableBbox": [60, 180, 500, 270], "equationText": "y = a + b x", "equationSize": 12, "tableCells": 9, "borderSize": 1, "cellSize": 11}

    c = new_canvas("size_conflict.pdf")
    line(c, "Synthetic conflicting body sizes", 60, 90, "Times-Bold", 20)
    for i in range(6):
        line(c, f"Body size eleven observation {i + 1}.", 60, 160 + i * 20, size=11)
    for i in range(6):
        line(c, f"Body size thirteen observation {i + 1}.", 60, 360 + i * 22, size=13)
    c.save()
    truth["fixtures"]["size_conflict.pdf"] = {"pages": 1, "bodySizes": [11, 13], "mustNotAverage": 12}

    vera = Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"
    pdfmetrics.registerFont(TTFont("FixtureVera", str(vera)))
    c = new_canvas("subset_font.pdf")
    line(c, "Subset font synthetic fixture", 60, 90, "FixtureVera", 18)
    for i in range(6):
        line(c, f"Subset font body observation {i + 1}.", 60, 150 + i * 20, "FixtureVera", 11)
    c.save()
    truth["fixtures"]["subset_font.pdf"] = {"pages": 1, "subsetPrefix": "AAAAAA+", "fontBase": "BitstreamVeraSans-Roman", "bodySize": 11}

    plain_minimal_pdf(ROOT / "missing_font.pdf", b"<< /Type /Font /Subtype /Type1 >>")
    truth["fixtures"]["missing_font.pdf"] = {"pages": 1, "fontInformationMissing": True}
    (ROOT / "groundtruth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
    (ROOT / "README.md").write_text("# Self-built PDF fixtures\n\nAll eight PDFs were authored locally by `build_fixtures.py`. They are synthetic fixtures, not journal articles, learned publisher templates, or AI output. `groundtruth.json` records authoring inputs independently from extraction. Rebuild with `.venv/bin/python validation/v5/pdf_fixtures/build_fixtures.py`.\n\nThe missing-font fixture intentionally omits `/BaseFont`. The rotated fixture contains vertical displayed text. The scanned fixture has only a raster image.\n", encoding="utf-8")


if __name__ == "__main__":
    build()
