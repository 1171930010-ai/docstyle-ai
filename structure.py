# coding: utf-8
"""Full-document context and audited role proposals. Local heuristics are not AI."""
import re,math
from rules import ROLE_LABELS

def paragraph_candidates(model):return [p for p in model['paragraphs'] if p['text'].strip() and p['role'] not in ['cell','equation']]
def role_guess(p,index=0):
 t=p['text'].strip();hint=p.get('role','body')
 if re.match(r'^(关键词|Keywords)\s*[：:]',t,re.I):return 'keywords','关键词标记'
 if re.match(r'^(摘要|Abstract)\s*[：:]',t,re.I):return 'abstract','摘要标记'
 if re.match(r'^(作者|Authors?|单位|Affiliation)\s*[：:]',t,re.I):return 'author','作者或单位标记'
 if re.match(r'^(图|表|Table|Figure|Fig\.)\s*[\d一二三四五六七八九十]',t,re.I):return 'caption','图表编号题注'
 if re.match(r'^(注|资料来源|数据来源|说明)\s*[：:]',t):return 'note','表注或来源标记'
 if re.match(r'^(参考文献|References)\s*[:：]?$',t,re.I):return 'heading1','参考文献分部标题'
 if len(t)>70 or re.search(r'[。！？!?；;]$',t) or (len(t)>35 and re.search(r'[，,。]',t)):
  return 'reference' if hint=='reference' else 'body','完整论述句或较长段落；样式不能决定其为标题'
 if re.match(r'^[一二三四五六七八九十]+[、．.]',t):return 'heading1','中文一级编号'
 if re.match(r'^[（(][一二三四五六七八九十]+[）)]',t):return 'heading2','中文二级编号'
 m=re.match(r'^(\d+(?:\.\d+){0,8})[.．、\s]\s*[^\d]',t)
 if m:return 'heading'+str(min(9,m[1].count('.')+1)),'章节数字编号'
 if hint in ['author','abstract','keywords','reference','caption','note']:return hint,'既有角色线索，需结合正文复核'
 if index==0 and len(t)<60 and not re.search('[，,。.!?！？]',t):return 'title','首个简短标题候选'
 if hint.startswith('heading') and len(t)<35 and not re.search('[，,。.!?！？]',t):return hint,'简短标题线索；本机建议，尚未经AI确认'
 return 'body','未发现充分标题证据'

def audit_outline(items,model):
 texts={p['id']:p['text'] for p in model['paragraphs']};issues=[];outline=[];last=0;seen={}
 for x in items:
  role=x['role'];t=texts.get(x['id'],'')
  if role=='title' or role.startswith('heading'):
   level=0 if role=='title' else int(role[7:])
   outline.append({'id':x['id'],'role':role,'level':level,'text':t[:180]})
   if level and level>last+1:issues.append({'id':x['id'],'type':'heading_jump','message':f'标题从{last}级跳至{level}级，请复核'})
   if level:last=level
   number=re.match(r'^(\d+(?:\.\d+)*)[.．、\s]',t)
   if number:
    n=number[1]
    if n in seen:issues.append({'id':x['id'],'type':'duplicate_number','message':'章节编号重复：'+n})
    seen[n]=x['id']
    if level!=min(9,n.count('.')+1):issues.append({'id':x['id'],'type':'number_role_conflict','message':'编号深度与建议标题级别不一致'})
 return outline,issues

def full_context(model):
 pars=paragraph_candidates(model);proposals=[{'id':p['id'],'role':role_guess(p,i)[0]} for i,p in enumerate(pars)]
 outline,issues=audit_outline(proposals,model)
 positions={b['id']:i for i,b in enumerate(model.get('blocks',[])) if 'id' in b}
 return {'document_summary':{'paragraphs':len(pars),'tables':model['counts'].get('tables',0),'equations':model['counts'].get('equations',0)},
         'outline_hint':outline,'structural_warnings':issues,
         'table_positions':[{'id':t['id'],'block_position':positions.get(t['id']),'rows':len(t['rows']),'columns':t['columns']} for t in model['tables']],
         'equation_positions':[{'id':e['id'],'paragraph':e['paragraph'],'display':e['display']} for e in model['equations']]}

def validate_results(raw,pars,locks=None,roles=None):
 if not isinstance(raw,list):raise ValueError('结构识别结果必须为列表')
 locks=locks or {};roles=roles or {};valid={p['id']:p for p in pars};seen=set();out=[];issues=[]
 for item in raw:
  if not isinstance(item,dict):issues.append({'type':'invalid_item','message':'结果项结构无效'});continue
  pid=item.get('id');role=item.get('role');c=item.get('confidence')
  if pid not in valid:issues.append({'type':'unknown_id','message':'返回未知段落ID'});continue
  if pid in seen:issues.append({'id':pid,'type':'duplicate_id','message':'段落ID重复'});continue
  if role not in ROLE_LABELS:issues.append({'id':pid,'type':'invalid_role','message':'段落角色无效'});continue
  if c is not None and (isinstance(c,bool) or not isinstance(c,(int,float)) or not math.isfinite(c) or not 0<=c<=1):issues.append({'id':pid,'type':'invalid_confidence','message':'模型自评值无效'});continue
  seen.add(pid)
  if locks.get(pid):
   role=roles.get(pid,valid[pid]['role']);c=None
   if role not in ROLE_LABELS:raise ValueError('锁定段落角色无效')
  out.append({'id':pid,'role':role,'confidence':c,'reason':str(item.get('reason',''))[:300], 'locked':bool(locks.get(pid)),'current_role':roles.get(pid,valid[pid]['role']),'text':valid[pid]['text'][:1000],'style_hint':valid[pid].get('style','')})
 for pid,p in valid.items():
  if locks.get(pid) and pid not in seen:
   locked_role=roles.get(pid,p['role'])
   if locked_role not in ROLE_LABELS:raise ValueError('锁定段落角色无效')
   seen.add(pid);out.append({'id':pid,'role':locked_role,'confidence':None,'reason':'用户已锁定分类','locked':True,'current_role':locked_role,'text':p['text'][:1000],'style_hint':p.get('style','')})
 omitted=[pid for pid in valid if pid not in seen]
 for pid in omitted:issues.append({'id':pid,'type':'omitted','message':'段落未返回有效识别结果，保留原分类'})
 order={p['id']:i for i,p in enumerate(pars)};out.sort(key=lambda x:order[x['id']])
 return out,omitted,issues

def analyze_local(model,locks=None,roles=None):
 pars=paragraph_candidates(model);raw=[]
 for i,p in enumerate(pars):
  role,reason=role_guess(p,i);raw.append({'id':p['id'],'role':role,'confidence':None,'reason':reason})
 items,omitted,issues=validate_results(raw,pars,locks,roles);outline,structural=audit_outline(items,model)
 return {'items':items,'total':len(pars),'omitted':len(omitted),'omittedIds':omitted,'issues':issues+structural,'outline':outline,'context':full_context(model),'sourceMode':'local','liveVerified':False,'confidenceLabel':'本机规则建议，非AI准确率','tables':model['counts'].get('tables',0),'equations':model['counts'].get('equations',0)}
