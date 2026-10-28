import struct
import tempfile
import unittest
from pathlib import Path

class MathFontCatalogTest(unittest.TestCase):
    def test_sfnt_math_table_and_ordinary_font(self):
        from math_fonts import inspect_font_file
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'font.otf'
            p.write_bytes(b'OTTO' + struct.pack('>HHHH', 1, 0, 0, 0) + b'MATH' + b'\0' * 12)
            self.assertEqual(inspect_font_file(p), 'math')
            p.write_bytes(b'OTTO' + struct.pack('>HHHH', 1, 0, 0, 0) + b'name' + b'\0' * 12)
            self.assertEqual(inspect_font_file(p), 'ordinary')
            p.write_bytes(b'ttcf' + b'\0' * 20)
            self.assertEqual(inspect_font_file(p), 'unknown')

    def test_report_never_confuses_written_font_with_word_verification(self):
        from math_fonts import font_assessment
        catalog={'installedFonts':['STIX Two Math','Times New Roman'], 'mathFontStatus':{'STIX Two Math':'math','Times New Roman':'ordinary'}}
        self.assertEqual(font_assessment('STIX Two Math',catalog)['status'], 'math')
        self.assertFalse(font_assessment('STIX Two Math',catalog)['wordVerified'])
        self.assertEqual(font_assessment('Times New Roman',catalog)['status'], 'ordinary')
        self.assertEqual(font_assessment('宋体',catalog)['status'], 'not_detected')
        self.assertEqual(font_assessment('Other',{'installedFonts':[],'mathFontStatus':{},'detection':{'status':'unavailable'}})['status'], 'unknown')
