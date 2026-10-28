# coding: utf-8
import unittest,tempfile,base64,threading,zipfile,io,json,time
from project_store import LocalStore,sanitize_state
from tasks import TaskManager
from sample import create_sample
from engine import default_profile
class StorageTests(unittest.TestCase):
 def state(self):return {'profile':default_profile(),'documents':[{'id':'old','name':'样例.docx','sourceData':base64.b64encode(create_sample()).decode(),'roles':{'p0':'body'},'aiLocks':{'p0':True},'overrides':{'p1':{'size':13}},'equations':{'e0':{'latex':'x'}}}],'workflow':{'pdfs':[],'secret':'SHOULD_NOT_PERSIST'},'deepseekKey':'SECRET'}
 def test_restart_restore_and_credentials_removed(self):
  with tempfile.TemporaryDirectory() as d:
   first=LocalStore(d);saved=first.save_project('恢复测试',self.state());again=LocalStore(d).read('projects',saved['id']);self.assertEqual(again['state']['documents'][0]['aiLocks'],{'p0':True});self.assertNotIn('secret',again['state']['workflow']);self.assertNotIn('deepseekKey',json.dumps(again));first.delete_project(saved['id']);self.assertTrue(first.read('trash',saved['id'])['state'])
 def test_source_hash_and_path_tampering(self):
  s=self.state();s['documents'][0]['sourceHash']='broken'
  with self.assertRaises(ValueError):sanitize_state(s)
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(ValueError):LocalStore(d).read('projects','../bad')
 def test_template_versions_and_scope(self):
  item={'target':'style','role':'body','field':'size','state':'set','value':12,'unit':'pt','status':'confirmed'}
  with tempfile.TemporaryDirectory() as d:
   store=LocalStore(d);a=store.save_template('测试','publication_reference',{'journal':'自建'},[item],[])['template'];b=store.save_template('测试','publication_reference',{'journal':'自建'},[{**item,'value':14}],[])['template'];self.assertEqual((a['version'],b['version']),(1,2));self.assertTrue(b['changes']);c=store.save_template('测试','publication_reference',{'journal':'另一期刊'},[item],[])['template'];self.assertEqual(c['version'],1)
 def test_template_same_value_unit_change_is_versioned(self):
  item={'target':'style','role':'body','field':'indent','state':'set','value':2,'unit':'cm','status':'confirmed'}
  with tempfile.TemporaryDirectory() as d:
   store=LocalStore(d);store.save_template('单位','publication_reference',{},[item],[])
   out=store.save_template('单位','publication_reference',{},[{**item,'unit':'chars'}],[])['template'];self.assertEqual(out['version'],2);self.assertEqual(out['changes'][0]['beforeUnit'],'cm');self.assertEqual(out['changes'][0]['afterUnit'],'chars')
class BatchTests(unittest.TestCase):
 def wait(self,t,id):
  deadline=time.monotonic()+3
  while time.monotonic()<deadline:
   s=t.snapshot(id)
   if s['status'] not in ['running','queued','cancelling']:return s
   time.sleep(.01)
  self.fail('task did not finish')
 def test_partial_success_and_retry_only_failure(self):
  attempts={}
  def execute(x):
   id=x['id'];attempts[id]=attempts.get(id,0)+1
   if id=='bad' and attempts[id]==1:raise ValueError('模拟瞬时失败')
   return b'actual bytes',{'checks':[{'status':'pass'}]}
  t=TaskManager(execute,lambda id:id+'.docx');id=t.start([{'id':'ok'},{'id':'bad'}])['id'];s=self.wait(t,id);self.assertEqual(s['status'],'completed_with_errors');z=zipfile.ZipFile(io.BytesIO(t.download(id)));self.assertEqual(len(z.namelist()),3);retry=t.retry(id)['id'];self.assertEqual(self.wait(t,retry)['progress']['success'],2);self.assertEqual(len(zipfile.ZipFile(io.BytesIO(t.download(retry))).namelist()),5);self.assertEqual(attempts['ok'],1);self.assertEqual(t.snapshot(id)['items'][0]['result'],base64.b64encode(b'actual bytes').decode())
 def test_retry_can_use_corrected_failed_settings(self):
  def execute(x):
   if x.get('broken'):raise ValueError('设置无效')
   return b'bytes',{}
  t=TaskManager(execute,str);identifier=t.start([{'id':'a','broken':True}])['id'];self.wait(t,identifier)
  second=t.retry(identifier,[{'id':'a','broken':False}])['id'];self.assertEqual(self.wait(t,second)['progress']['success'],1)
 def test_saved_batch_recovery_retains_success_and_interrupts_pending(self):
  t=TaskManager(lambda x:(b'bytes',{}),str);docs=[{'id':'a','name':'a.docx','result':base64.b64encode(b'bytes').decode(),'report':{'restoredAndRechecked':True}},{'id':'b','name':'b.docx'}]
  out=t.restore({'id':'old','items':[{'id':'a','status':'completed','attempts':1},{'id':'b','status':'running','attempts':1}]},docs,{})
  self.assertEqual([x['status'] for x in out['items']],['completed','cancelled']);retry=t.retry(out['id'])['id'];self.assertEqual(self.wait(t,retry)['progress']['success'],2)
 def test_cancel_keeps_current_success(self):
  entered=threading.Event();release=threading.Event()
  def execute(x):entered.set();release.wait(2);return b'bytes',{}
  t=TaskManager(execute,str);id=t.start([{'id':'a'},{'id':'b'}])['id'];self.assertTrue(entered.wait(1));t.cancel(id);release.set();s=self.wait(t,id);self.assertEqual([x['status'] for x in s['items']],['completed','cancelled'])
if __name__=='__main__':unittest.main()
