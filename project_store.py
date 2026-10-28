# coding: utf-8
"""Versioned local artifacts; explicit whitelist; reversible deletion."""
import base64,copy,hashlib,json,os,re,threading,uuid
from datetime import datetime,timezone
from pathlib import Path
from rules import validate_items,conflicts,path
LOCK=threading.RLock()
DOC_FIELDS=['id','name','sourceData','sourceHash','roles','aiLocks','overrides','tables','equations','insertions','result','report','aiCandidates','aiSummary','aiRuleNotes','notes']
PDF_FIELDS=['id','name','sourceData','sourceHash','metadata','status','pages','pageCount','candidates','warnings','limits','analysis','coordinateConvention','coordinateSystem','ocr']
SECRET=re.compile(r'^(api[_-]?key|key|token|bearer|authorization|password|secret|credentials|deepseekConnected|deepseekKey)$',re.I)
def now():return datetime.now(timezone.utc).isoformat()
def clean(value,depth=0):
 if depth>30:raise ValueError('项目结构过深')
 if value is None or isinstance(value,(str,int,float,bool)):return value
 if isinstance(value,list):return [clean(x,depth+1) for x in value]
 if isinstance(value,dict):return {k:clean(v,depth+1) for k,v in value.items() if not SECRET.fullmatch(k) and k not in ['__proto__','prototype','constructor']}
 raise ValueError('项目字段类型无效')
def decode_source(record,limit=50*1024*1024):
 try:data=base64.b64decode(record['sourceData'],validate=True)
 except Exception:raise ValueError('项目原稿数据缺失或损坏') from None
 if not data or len(data)>limit:raise ValueError('项目原稿为空或超出限制')
 sha=hashlib.sha256(data).hexdigest()
 if record.get('sourceHash') and record['sourceHash']!=sha:raise ValueError('项目原稿哈希不一致')
 return data,sha

def sanitize_state(raw):
 if not isinstance(raw,dict) or (raw.get('format') and raw.get('format')!='DocStyleProject') or (raw.get('version') and raw.get('version') not in [4,5]) or not isinstance(raw.get('profile'),dict) or not isinstance(raw.get('documents'),list):raise ValueError('项目结构无效')
 if len(raw['documents'])>100:raise ValueError('项目最多100份文档')
 docs=[];ids=set();total=0
 for d in raw['documents']:
  if not isinstance(d,dict) or not isinstance(d.get('id'),str) or d['id'] in ids:raise ValueError('项目文档标识无效或重复')
  ids.add(d['id']);data,sha=decode_source(d,30*1024*1024);total+=len(data)
  x={k:clean(d[k]) for k in DOC_FIELDS if k in d};x['sourceHash']=sha;docs.append(x)
 workflow=clean(raw.get('workflow') or {});pdfs=[]
 for p in workflow.get('pdfs',[]):
  x={k:clean(p[k]) for k in PDF_FIELDS if k in p}
  if p.get('sourceData'):
   data,sha=decode_source(p);total+=len(data);x['sourceHash']=sha
  elif p.get('status')!='failed':raise ValueError('参考PDF缺少原文件')
  pdfs.append(x)
 if total>200*1024*1024:raise ValueError('项目原文件总计超过200MB')
 workflow['pdfs']=pdfs
 return {'format':'DocStyleProject','version':5,'name':str(raw.get('name') or '未命名项目')[:120],'savedAt':raw.get('savedAt') or now(),'profile':clean(raw['profile']),'documents':docs,'workflow':workflow,'view':clean(raw.get('view') or {})}

class LocalStore:
 def __init__(self,root):
  self.root=Path(root)
  for d in ['projects','templates','trash']:(self.root/d).mkdir(parents=True,exist_ok=True)
 def file(self,category,identifier):
  if category not in ['projects','templates','trash'] or not re.fullmatch('[a-f0-9]{32}',str(identifier)):raise ValueError('存储标识无效')
  return self.root/category/(identifier+'.json')
 def write(self,category,identifier,payload):
  file=self.file(category,identifier);temp=file.with_suffix('.tmp');data=json.dumps(payload,ensure_ascii=False,allow_nan=False)
  if len(data.encode())>280*1024*1024:raise ValueError('项目包超过存储限制')
  with LOCK:
   temp.write_text(data,encoding='utf-8');temp.chmod(0o600);os.replace(temp,file)
 def read(self,category,identifier):
  file=self.file(category,identifier)
  if not file.is_file():raise ValueError('保存的项目或模板不存在')
  return json.loads(file.read_text(encoding='utf-8'))
 def list_projects(self):
  out=[]
  for f in (self.root/'projects').glob('*.json'):
   try:
    p=json.loads(f.read_text());s=p['state'];out.append({'id':p['id'],'name':p['name'],'updatedAt':p['updatedAt'],'documentCount':len(s['documents'])})
   except Exception:continue
  return sorted(out,key=lambda x:x['updatedAt'],reverse=True)
 def save_project(self,name,state,identifier=None):
  state=sanitize_state(state);identifier=identifier or uuid.uuid4().hex
  payload={'id':identifier,'name':str(name or state['name'])[:120],'updatedAt':now(),'state':state};self.write('projects',identifier,payload)
  return {k:v for k,v in payload.items() if k!='state'}
 def delete_project(self,identifier):
  file=self.file('projects',identifier)
  with LOCK:
   if not file.exists():raise ValueError('项目不存在')
   os.replace(file,self.file('trash',identifier))
  return {'deleted':True,'recoverable':True,'id':identifier,'message':'已移至本机项目回收目录，可恢复'}
 def list_templates(self):
  out=[]
  for file in (self.root/'templates').glob('*.json'):
   try:out.append(json.loads(file.read_text()))
   except Exception:continue
  return sorted(out,key=lambda x:x['createdAt'],reverse=True)
 def save_template(self,name,purpose,metadata,items,pdf_ids):
  if not isinstance(name,str) or not name.strip():raise ValueError('模板名称不能为空')
  if purpose not in ['publication_reference','pdf_publication','user_requirements','official_submission','submission_guideline']:raise ValueError('模板用途无效')
  items=validate_items(items)
  items=[x for x in items if x['status']=='confirmed' and x['state']!='unspecified']
  if not items:raise ValueError('模板至少包含一项已确认规则')
  collisions=conflicts(items)
  if collisions:return {'template':None,'conflicts':collisions}
  metadata=clean(metadata or {})
  scope=(name.strip(),purpose,metadata.get('journal'),metadata.get('year'),metadata.get('articleType'))
  with LOCK:
   prev=[x for x in self.list_templates() if (x['name'],x['purpose'],x['metadata'].get('journal'),x['metadata'].get('year'),x['metadata'].get('articleType'))==scope]
   previous=max(prev,key=lambda x:x['version']) if prev else None
   before={path(x):x for x in previous['items']} if previous else {};after={path(x):x for x in items}
   changes=[{'path':p,'before':before.get(p,{}).get('value'),'after':after.get(p,{}).get('value'),'beforeUnit':before.get(p,{}).get('unit'),'afterUnit':after.get(p,{}).get('unit'),'beforeState':before.get(p,{}).get('state'),'afterState':after.get(p,{}).get('state')} for p in sorted(set(before)|set(after)) if (before.get(p,{}).get('state'),before.get(p,{}).get('value'),before.get(p,{}).get('unit'))!=(after.get(p,{}).get('state'),after.get(p,{}).get('value'),after.get(p,{}).get('unit'))]
   template={'id':uuid.uuid4().hex,'name':name.strip()[:120],'purpose':purpose,'metadata':metadata,'version':previous['version']+1 if previous else 1,'previousId':previous['id'] if previous else None,'createdAt':now(),'items':items,'pdfIds':pdf_ids,'changes':changes,'status':'confirmed'}
   self.write('templates',template['id'],template)
  return {'template':template,'conflicts':[]}
