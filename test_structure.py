# coding: utf-8
import unittest
from structure import analyze_local,validate_results
class StructureTests(unittest.TestCase):
 def model(self):
  return {'paragraphs':[{'id':'p0','text':'测试文章','role':'title'}, {'id':'p1','text':'这段完整的论述说明研究设计与变量选择，并且包含多个说明内容，原文被错误设置为三级标题，但实际上是正文。','role':'heading3'}, {'id':'p2','text':'1.1.1.1 指标','role':'heading4'}],'tables':[],'equations':[],'blocks':[],'counts':{'tables':0,'equations':0}}
 def test_false_heading_corrected_and_jump_flagged(self):
  out=analyze_local(self.model());self.assertEqual(out['items'][1]['role'],'body');self.assertTrue(any(x['type']=='heading_jump' for x in out['issues']))
 def test_locks_survive_analysis(self):
  out=analyze_local(self.model(),{'p1':True},{'p1':'reference'});self.assertEqual(out['items'][1]['role'],'reference');self.assertTrue(out['items'][1]['locked'])
 def test_bad_ai_ids_are_not_complete(self):
  pars=self.model()['paragraphs'];raw=[{'id':'p0','role':'title','confidence':.9},{'id':'p0','role':'body','confidence':.8},{'id':'x','role':'body','confidence':.8},{'id':'p1','role':'evil','confidence':.8}]
  items,omitted,issues=validate_results(raw,pars);self.assertEqual(len(items),1);self.assertEqual(set(omitted),{'p1','p2'});self.assertEqual({x['type'] for x in issues},{'duplicate_id','unknown_id','invalid_role','omitted'})
if __name__=='__main__':unittest.main()
