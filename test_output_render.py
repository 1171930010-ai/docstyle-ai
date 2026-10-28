import unittest
from unittest.mock import patch
from pathlib import Path
from output_render import render_output,status
from sample import create_sample
class RenderTests(unittest.TestCase):
 def test_unavailable_is_not_a_pagination_pass(self):
  with patch('output_render.renderer_path',return_value=None):
   out,data=render_output(create_sample());self.assertEqual(out['status'],'unavailable');self.assertIsNone(data);self.assertFalse(out['WordWpsVerified'])
 def test_invalid_docx_rejected_before_renderer(self):
  with self.assertRaises(ValueError):render_output(b'not a docx')
 def test_status_does_not_claim_word_wps_compatibility(self):
  self.assertFalse(status()['WordWpsVerified']);self.assertEqual(status()['previewMode'],'libreoffice_reference_pagination')
if __name__=='__main__':unittest.main()
