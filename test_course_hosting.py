"""Course hosting must be opt-in, bounded, and avoid exposing server secrets."""
import importlib
import os
import unittest
from unittest.mock import patch

class CourseConfigTests(unittest.TestCase):
    def test_local_defaults_and_course_configuration(self):
        import course_hosting
        self.assertFalse(course_hosting.config({}).enabled)
        c=course_hosting.config({'DOCSTYLE_COURSE_MODE':'1','PORT':'8123','DATA_DIR':'/tmp/course-data','DOCSTYLE_PUBLIC_ORIGIN':'https://mf01.show.lingnan.top'})
        self.assertEqual((c.host,c.port,c.data_dir),('0.0.0.0',8123,'/tmp/course-data'))
        self.assertTrue(c.allowed('mf01.show.lingnan.top','https://mf01.show.lingnan.top'))
        self.assertFalse(c.allowed('mf01.show.lingnan.top','https://evil.example'))
        self.assertFalse(c.allowed('evil.example','https://mf01.show.lingnan.top'))
        self.assertTrue(c.allowed('127.0.0.1:8123',None))
    def test_bad_configuration_is_rejected(self):
        import course_hosting
        with self.assertRaises(ValueError):course_hosting.config({'DOCSTYLE_COURSE_MODE':'1','PORT':'0','DOCSTYLE_PUBLIC_ORIGIN':'https://mf01.show.lingnan.top'})
        with self.assertRaises(ValueError):course_hosting.config({'DOCSTYLE_COURSE_MODE':'1','DOCSTYLE_PUBLIC_ORIGIN':'http://example.org/path'})
    def test_server_secret_cannot_be_changed_by_web_request(self):
        import server
        c=server.course_config
        with patch.object(server,'course_config',new=__import__('course_hosting').config({'DOCSTYLE_COURSE_MODE':'1','DOCSTYLE_PUBLIC_ORIGIN':'https://mf01.show.lingnan.top'})):
            with patch.dict(os.environ, {'DEEPSEEK_API_KEY':'test-only-key'}):
                self.assertEqual(server.ai_credentials()[0],'test-only-key')
                self.assertNotIn('test-only-key',str(server.deepseek_status()))
                with self.assertRaises(ValueError):server.course_connect('injected','deepseek-flash')
