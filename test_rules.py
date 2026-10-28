# coding: utf-8
import unittest, math
from rules import parse_local, validate_items, apply_rules
from engine import default_profile
class RuleTests(unittest.TestCase):
 def test_chinese_sizes_spacing_and_char_units(self):
  x=parse_local('一级标题黑体小二、加粗、居中；正文宋体小四，英文 Times New Roman，1.5倍行距，段前12磅，段后0磅，首行缩进2字符')
  values={(i['role'],i['field']):i['value'] for i in x['items']}
  self.assertEqual(values[('heading1','size')],18)
  self.assertEqual(values[('body','size')],12)
  self.assertEqual(values[('body','before')],12)
  self.assertEqual(values[('body','after')],0)
  self.assertEqual(values[('body','indentUnit')],'chars')
  self.assertEqual(values[('body','latin')],'Times New Roman')
  self.assertNotIn(('body','color'),values)
 def test_invalid_units_nan_bool_and_keys_rejected(self):
  base={'target':'style','role':'body','field':'size','state':'set','value':12,'unit':'pt'}
  for key,value in [('value',float('nan')),('value',True),('unit','cm'),('field','__proto__')]:
   with self.assertRaises(ValueError):validate_items([{**base,key:value}])
 def test_conflict_confirmation_and_preserve_clear(self):
  item={'target':'style','role':'body','field':'before','state':'set','value':0,'unit':'pt','status':'confirmed'}
  first=apply_rules(default_profile(),[item]);self.assertEqual(first['profile']['styles']['body']['before'],0)
  conflict=apply_rules(first['profile'],[{**item,'value':12}]);self.assertTrue(conflict['conflicts'])
  resolved=apply_rules(first['profile'],[{**item,'value':12}],True);self.assertEqual(resolved['profile']['styles']['body']['before'],12)
  for state in ['preserve','clear']:
   result=apply_rules(default_profile(),[{**item,'state':state,'value':None}],True)
   self.assertEqual(result['profile']['styles']['body']['_fieldStates']['before'],state)
 def test_explicit_color_and_bold_are_independent(self):
  out=parse_local('正文宋体小四，不加粗，文字颜色黑色')
  values={x['field']:x['value'] for x in out['items']};self.assertEqual(values['bold'],False);self.assertEqual(values['color'],'000000')
 def test_local_conflicting_candidates_are_visible(self):
  out=parse_local('正文12磅；正文14磅');self.assertTrue(out['conflicts'])
 def test_missing_spacing_units_and_ambiguous_text_stay_unapplied(self):
  out=parse_local('正文宋体，段前12行，段后6，紧凑一点')
  self.assertFalse(any(x['field'] in ['before','after'] for x in out['items']));self.assertGreaterEqual(len(out['warnings']),3)
 def test_magnitude_requires_confirmed_mode(self):
  from server import confirmed_defaults
  x={'target':'style','role':'body','field':'line','state':'set','value':22,'unit':'pt','status':'confirmed'}
  with self.assertRaises(ValueError):apply_rules(confirmed_defaults(),[x])
  mode={**x,'field':'lineMode','value':'exact','unit':'enum'}
  result=apply_rules(confirmed_defaults(),[x,mode])['profile'];self.assertEqual(result['styles']['body']['lineMode'],'exact')
  multiple=apply_rules(confirmed_defaults(),[{**x,'value':1.5,'unit':'multiple'}])['profile'];self.assertEqual(multiple['styles']['body']['_fieldStates']['lineMode'],'set')
 def test_line_mode_unit_conflict_is_not_silently_reinterpreted(self):
  from server import confirmed_defaults
  base={'target':'style','role':'body','state':'set','status':'confirmed'}
  line={**base,'field':'line','value':22,'unit':'pt'};mode={**base,'field':'lineMode','value':'multiple','unit':'enum'}
  with self.assertRaises(ValueError):apply_rules(confirmed_defaults(),[line,mode])
 def test_same_value_different_unit_is_a_source_conflict(self):
  from rules import conflicts
  item={'target':'style','role':'body','field':'indent','state':'set','value':2,'unit':'cm','status':'confirmed'}
  self.assertTrue(conflicts(validate_items([item,{**item,'unit':'chars'}])))
 def test_unknown_requirement_does_not_invent_rules(self):
  out=parse_local('参考原图，看不清的字号先不设置');self.assertEqual(out['items'],[]);self.assertTrue(out['warnings'])
if __name__=='__main__':unittest.main()
