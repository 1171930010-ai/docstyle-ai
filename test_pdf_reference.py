"""Regression tests against explicitly self-built PDF authoring inputs."""
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image
import pdf_reference as pdf

FIXTURES = Path(__file__).parent / "validation" / "v5" / "pdf_fixtures"
TRUTH = json.loads((FIXTURES / "groundtruth.json").read_text())


def fixture(name):
    return (FIXTURES / name).read_bytes()


class PdfReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = {name: pdf.analyze_pdf(fixture(name), name, {"provenance": "self-built"}) for name in TRUTH["fixtures"]}

    def test_digital_measurements_and_provenance(self):
        result = self.results["digital.pdf"]
        self.assertEqual(result["status"], "pending_confirmation")
        self.assertEqual(result["sourceHash"], hashlib.sha256(fixture("digital.pdf")).hexdigest())
        self.assertEqual(len(result["pages"]), 3)
        page = result["pages"][0]
        self.assertAlmostEqual(page["width"], 612, delta=.1)
        self.assertAlmostEqual(page["height"], 792, delta=.1)
        title = next(c for c in result["candidates"] if c["role"] == "title" and c["field"] == "size")
        self.assertEqual(title["value"], 20)
        self.assertAlmostEqual(title["source"]["bbox"][0], 60, delta=.1)
        self.assertIn("Synthetic Digital Layout", title["source"]["evidence"])
        self.assertEqual(title["source"]["measurement"]["unit"], "pt")
        self.assertEqual(title["source"]["pdfHash"], result["sourceHash"])
        json.dumps(result, allow_nan=False)

    def test_unknown_word_parameters_are_not_precise_values(self):
        result = self.results["digital.pdf"]
        for field in ("before", "after", "line", "indent"):
            candidates = [c for c in result["candidates"] if c["role"] == "body" and c["field"] == field]
            self.assertTrue(candidates, field)
            self.assertTrue(all(c["state"] == "unspecified" and c["value"] is None for c in candidates))
        self.assertTrue(any(p["observations"]["baselineDistancesPt"] for p in result["pages"]))

    def test_scanned_pdf_is_not_empty_success(self):
        result = self.results["scanned.pdf"]
        self.assertEqual(result["status"], "needs_ocr")
        self.assertEqual(result["pages"][0]["characters"], [])
        self.assertEqual(len(result["pages"][0]["images"]), 1)
        self.assertEqual(result["candidates"], [])
        self.assertFalse(result["ocr"]["used"])

    def test_two_columns_kept_separate_with_spanning_title(self):
        page = self.results["two_column.pdf"]["pages"][0]
        self.assertEqual(page["columns"], 2)
        body = [line for line in page["lines"] if line["role"] == "body"]
        self.assertTrue(any(line["column"] == 1 for line in body))
        self.assertTrue(any(line["column"] == 2 for line in body))
        self.assertFalse(any("Left" in line["text"] and "Right" in line["text"] for line in body))
        self.assertEqual(next(line for line in page["lines"] if line["role"] == "title")["column"], 0)

    def test_repeated_headers_footers_and_reference_pages(self):
        result = self.results["digital.pdf"]
        self.assertTrue(all(any(line["region"] == "header" for line in p["lines"]) for p in result["pages"]))
        self.assertTrue(all(any(line["region"] == "footer" for line in p["lines"]) for p in result["pages"]))
        self.assertEqual(result["pages"][2]["pageRole"], "references")
        self.assertTrue(any(c["role"] == "reference" and c["value"] == 9 for c in result["candidates"]))

    def test_render_and_evidence_align_including_rotation(self):
        for name in ("digital.pdf", "rotated.pdf", "two_column.pdf"):
            result = self.results[name]
            page = result["pages"][0]
            image = Image.open(io.BytesIO(pdf.render_page(fixture(name), 1))).convert("RGB")
            sx, sy = image.width / page["width"], image.height / page["height"]
            self.assertAlmostEqual(sx, sy, delta=.01)
            if name == "rotated.pdf":
                self.assertEqual(page["rotation"], 90)
                self.assertTrue(any(abs(char["size"] - 16) < .1 for char in page["characters"]))
            measured = next(c for c in result["candidates"] if c["field"] == "size")
            x0, y0, x1, y1 = measured["source"]["bbox"]
            crop = image.crop((int(x0 * sx), int(y0 * sy), int(x1 * sx) + 1, int(y1 * sy) + 1))
            dark = sum(1 for pixel in crop.convert("L").tobytes() if pixel < 190)
            self.assertGreater(dark, 15, name)

    def test_table_formula_detected_without_rewriting_expression(self):
        page = self.results["table_formula.pdf"]["pages"][0]
        table = page["tableCandidates"][0]
        for actual, expected in zip(table["bbox"], TRUTH["fixtures"]["table_formula.pdf"]["tableBbox"]):
            self.assertAlmostEqual(actual, expected, delta=.2)
        self.assertGreaterEqual(len(table["cells"]), 9)
        self.assertTrue(any("y = a + b x" in line["text"] and line["region"] == "equation" for line in page["lines"]))
        self.assertTrue(any(c["target"] == "equation" for c in self.results["table_formula.pdf"]["candidates"]))
        table_rules = [c for c in self.results["table_formula.pdf"]["candidates"] if c["target"] == "table"]
        self.assertTrue(any(c["field"] == "size" and c["value"] == 11 for c in table_rules))
        self.assertTrue(any(c["field"] == "borderSize" and c["value"] == 1 for c in table_rules))
        self.assertTrue(any(line["role"] == "title" for line in page["lines"]))

    def test_conflicting_sizes_are_not_averaged(self):
        result = self.results["size_conflict.pdf"]
        sizes = {c["value"] for c in result["candidates"] if c["role"] == "body" and c["field"] == "size"}
        self.assertEqual(sizes, {11, 13})
        self.assertTrue(any("conflict" in warning.lower() for warning in result["warnings"]))

    def test_font_subset_and_alias_without_fuzzy_equivalence(self):
        result = self.results["subset_font.pdf"]
        fonts = result["pages"][0]["fontNames"]
        self.assertTrue(any(f["raw"].startswith("AAAAAA+") for f in fonts))
        self.assertTrue(any(f["normalized"] == "BitstreamVeraSans-Roman" for f in fonts))
        self.assertEqual(pdf.normalize_font("ABCDEF+TimesNewRomanPSMT")["normalized"], "Times New Roman")
        self.assertEqual(pdf.normalize_font("SomeLookalikeSerif")["normalized"], "SomeLookalikeSerif")
        self.assertEqual(pdf.normalize_font("Helvetica")["normalized"], "Helvetica")

    def test_missing_font_information_stays_unknown(self):
        result = self.results["missing_font.pdf"]
        self.assertNotEqual(result["status"], "failed")
        font_candidates = [c for c in result["candidates"] if c["field"] in ("font", "latin")]
        self.assertTrue(font_candidates)
        self.assertTrue(all(c["state"] == "unspecified" and c["value"] is None for c in font_candidates))
        self.assertTrue(any("font" in warning.lower() for warning in result["warnings"]))

    def test_invalid_and_resource_limited_inputs(self):
        self.assertEqual(pdf.analyze_pdf(b"not a pdf", "bad.pdf")["status"], "failed")
        self.assertEqual(pdf.analyze_pdf(b"%PDF-" + b"a" * pdf.MAX_PDF_BYTES, "large.pdf")["status"], "failed")
        with self.assertRaises(ValueError):
            pdf.render_page(fixture("digital.pdf"), 0)
        with self.assertRaises(ValueError):
            pdf.render_page(fixture("digital.pdf"), 100)
        safe = pdf.analyze_pdf(fixture("digital.pdf"), "../../bad.pdf", {"journal": "Synthetic"})
        self.assertEqual(safe["name"], "bad.pdf")
        self.assertEqual(safe["metadata"]["journal"], "Synthetic")

    def test_candidates_follow_shared_rule_schema(self):
        from rules import validate_items
        for name, result in self.results.items():
            normalized = validate_items(result["candidates"])
            self.assertEqual(len(normalized), len(result["candidates"]), name)
            self.assertTrue(all(item["status"] == "pending" for item in normalized))

    def test_page_count_and_deadline_fail_explicitly(self):
        from reportlab.pdfgen import canvas
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer)
        for _ in range(pdf.MAX_PAGES + 1):
            c.drawString(50, 100, "Synthetic resource-limit page")
            c.showPage()
        c.save()
        result = pdf.analyze_pdf(buffer.getvalue(), "too_many.pdf")
        self.assertEqual(result["status"], "failed")
        self.assertIn("40", result["error"])
        with patch.object(pdf, "OPERATION_TIMEOUT_SECONDS", .001):
            timed = pdf.analyze_pdf(fixture("digital.pdf"), "timed.pdf")
        self.assertEqual(timed["status"], "failed")
        self.assertIn("limit", timed["error"])

    def test_rules_cannot_change_content_or_apply_pending_measurements(self):
        from rules import apply_rules
        profile = {"styles": {"body": {"size": 12}}}
        pending = self.results["digital.pdf"]["candidates"]
        applied = apply_rules(profile, pending)
        self.assertEqual(applied["profile"]["styles"]["body"]["size"], 12)
        self.assertFalse(applied["ledger"])
        self.assertFalse(any(item["field"] in ("expression", "tableValues", "merges") for item in pending))

    def test_arbitrary_angle_font_size_is_unknown(self):
        from reportlab.pdfgen import canvas
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer)
        c.translate(100, 500)
        c.rotate(30)
        c.setFont("Helvetica", 20)
        c.drawString(0, 0, "Synthetic angle test observation")
        c.save()
        result = pdf.analyze_pdf(buffer.getvalue(), "angle.pdf")
        self.assertNotEqual(result["status"], "failed")
        sizes = [item for item in result["candidates"] if item["field"] == "size"]
        self.assertTrue(sizes)
        self.assertTrue(all(item["state"] == "unspecified" for item in sizes))

    def test_chinese_and_latin_font_fields_are_separate(self):
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer)
        c.setFont("STSong-Light", 11)
        for i in range(6):
            c.drawString(60, 650 - 20 * i, f"自建中英文字体核对样例 Sample {i + 1}")
        c.save()
        result = pdf.analyze_pdf(buffer.getvalue(), "bilingual.pdf")
        fields = {item["field"] for item in result["candidates"] if item["role"] == "body"}
        self.assertIn("font", fields)
        self.assertIn("latin", fields)

    def test_figure_text_and_footnote_do_not_contaminate_body(self):
        from reportlab.pdfgen import canvas
        from reportlab.lib.utils import ImageReader
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer)
        c.setFont("Times-Roman", 11)
        for i in range(8):
            c.drawString(60, 650 - 20 * i, f"Normal body text observation {i + 1}.")
        c.drawImage(ImageReader(Image.new("RGB", (100, 100), "lightgray")), 330, 500, width=220, height=120)
        c.setFont("Helvetica", 9)
        c.drawString(340, 550, "Figure internal label")
        c.setFont("Times-Roman", 8)
        c.drawString(60, 100, "1 Synthetic footnote evidence only.")
        c.save()
        result = pdf.analyze_pdf(buffer.getvalue(), "figure_footnote.pdf")
        self.assertNotEqual(result["status"], "failed")
        lines = result["pages"][0]["lines"]
        self.assertEqual(next(line for line in lines if "Figure internal" in line["text"])["region"], "figure_text")
        self.assertEqual(next(line for line in lines if "footnote" in line["text"])["region"], "footnote")
        self.assertEqual({item["value"] for item in result["candidates"] if item["role"] == "body" and item["target"] == "style" and item["field"] == "size"}, {11})

    def test_multiple_samples_keep_measured_conflicts(self):
        from rules import conflicts
        items = self.results["digital.pdf"]["candidates"] + self.results["size_conflict.pdf"]["candidates"]
        differences = conflicts(items)
        self.assertTrue(any(item["path"] == "styles.body.size" and item["before"] != item["after"] for item in differences))
        self.assertEqual(len({item["source"]["pdfHash"] for item in items}), 2)

    def test_all_quarter_turns_preserve_text_order_and_evidence(self):
        from reportlab.pdfgen import canvas
        text = "Synthetic rotation ordering evidence"
        for rotation in (0, 90, 180, 270):
            buffer = io.BytesIO()
            c = canvas.Canvas(buffer, pagesize=(612, 792))
            c.setPageRotation(rotation)
            c.setFont("Helvetica", 13)
            c.drawString(60, 400, text)
            c.save()
            data = buffer.getvalue()
            result = pdf.analyze_pdf(data, f"rotate{rotation}.pdf")
            self.assertNotEqual(result["status"], "failed")
            page = result["pages"][0]
            line = next(line for line in page["lines"] if line["text"] == text)
            self.assertAlmostEqual(line["size"], 13, delta=.1)
            image = Image.open(io.BytesIO(pdf.render_page(data, 1))).convert("L")
            sx, sy = image.width / page["width"], image.height / page["height"]
            x0, y0, x1, y1 = line["bbox"]
            crop = image.crop((int(x0 * sx), int(y0 * sy), int(x1 * sx) + 1, int(y1 * sy) + 1))
            self.assertGreater(sum(pixel < 190 for pixel in crop.tobytes()), 20)

    def test_cropped_page_evidence_has_display_origin(self):
        import pypdfium2
        document = pypdfium2.PdfDocument(fixture("digital.pdf"))
        page = document[0]
        pypdfium2.raw.FPDFPage_SetCropBox(page.raw, 30, 30, 582, 762)
        page.close()
        buffer = io.BytesIO()
        document.save(buffer)
        document.close()
        data = buffer.getvalue()
        result = pdf.analyze_pdf(data, "cropped.pdf")
        self.assertEqual(result["status"], "pending_confirmation")
        first = result["pages"][0]
        self.assertEqual(first["width"], 552)
        self.assertEqual(first["height"], 732)
        title = next(item for item in result["candidates"] if item["role"] == "title" and item["field"] == "size")
        self.assertAlmostEqual(title["source"]["bbox"][0], 30, delta=.1)
        image = Image.open(io.BytesIO(pdf.render_page(data, 1))).convert("L")
        x0, y0, x1, y1 = title["source"]["bbox"]
        sx, sy = image.width / first["width"], image.height / first["height"]
        crop = image.crop((int(x0 * sx), int(y0 * sy), int(x1 * sx) + 1, int(y1 * sy) + 1))
        self.assertGreater(sum(pixel < 190 for pixel in crop.tobytes()), 20)


if __name__ == "__main__":
    unittest.main()
