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

class CourseDocumentLimitsTests(unittest.TestCase):
    def test_rejects_compressed_docx_with_oversized_expansion(self):
        import io, zipfile
        from course_hosting import check_docx_size
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w',compression=zipfile.ZIP_DEFLATED) as z:z.writestr('word/document.xml',b'X'*(33*1024*1024))
        with self.assertRaisesRegex(ValueError,'解压'):check_docx_size(b.getvalue())

class CourseRestoreIsolationTests(unittest.TestCase):
    def test_restore_does_not_remove_another_session_document(self):
        import server
        from course_hosting import config
        raw={'documents':[{'id':'other','sourceData':'unused'}], 'workflow':{},'profile':{},'view':{}}
        with patch.object(server,'course_config',config({'DOCSTYLE_COURSE_MODE':'1'})), patch.object(server,'sanitize_state',return_value=raw), patch.object(server,'decode_source',return_value=(b'example','hash')), patch.object(server,'check_docx_size'), patch.object(server,'inspect_doc',return_value={}), patch.dict(server.STORE,{'other':{'data':b'private','name':'other.docx'}},clear=True):
            server.restore_project(raw)
            self.assertEqual(server.STORE['other']['data'],b'private')

class CourseSessionStorageTests(unittest.TestCase):
    def test_browser_sessions_get_distinct_storage_and_bad_ids_are_rejected(self):
        import tempfile
        from course_hosting import session_store
        with tempfile.TemporaryDirectory() as d:
            first=session_store(d,'a'*64)
            second=session_store(d,'b'*64)
            first.write('projects','c'*32,{'id':'c'*32,'name':'first','updatedAt':'now','state':{'documents':[]}})
            self.assertEqual(len(first.list_projects()),1)
            self.assertEqual(second.list_projects(),[])
            with self.assertRaises(ValueError):second.read('projects','c'*32)
            with self.assertRaises(ValueError):session_store(d,'../other')
