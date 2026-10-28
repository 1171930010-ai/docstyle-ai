#!/usr/bin/env python3
"""Loopback service: local documents, evidence, versioned projects, audited optional AI."""
import argparse,base64,copy,hashlib,json,mimetypes,secrets,threading,time,webbrowser,subprocess,sys,re,os
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from engine import default_profile,inspect_doc,transform,formula,package,parse,q,child,read_format,style_context,NS
from sample import create_sample
from rules import schema,SCHEMA,parse_local,apply_rules,validate_items
from structure import analyze_local,audit_outline
from ai_pipeline import parse_requirements,analyze_document
from pdf_reference import analyze_pdf,render_page
from project_store import LocalStore,sanitize_state,decode_source,clean
from tasks import TaskManager
from output_render import render_output,status as render_status
from math_fonts import inspect_font_file,font_assessment
from course_hosting import config as hosting_config
BASE=Path(__file__).resolve().parent
STORE={};PDFSTORE={};RENDERSTORE={};LOCK=threading.RLock();MAX_BYTES=220*1024*1024
DEEPSEEK={'key':None,'model':'deepseek-flash','checked':None}
DEEPSEEK_MODELS={'deepseek-flash','deepseek-v4-pro'}
FONT_CACHE=None;FONT_LOCK=threading.Lock();COURSE_POST_LOCK=threading.Lock()
FONT_FALLBACK=['宋体','黑体','微软雅黑','仿宋','楷体','SimSun','SimHei','Microsoft YaHei','FangSong','KaiTi','等线','DengXian','Times New Roman','Arial','Calibri','Aptos','Cambria','Cambria Math','STIX Two Math','Helvetica','PingFang SC','苹方-简']
course_config=hosting_config(os.environ)
if course_config.enabled:MAX_BYTES=20*1024*1024
DISK=LocalStore(course_config.data_dir if course_config.enabled else os.environ.get('DOCSTYLE_DATA_DIR',str(BASE/'.docstyle_data')))

def available_fonts():
 global FONT_CACHE
 if FONT_CACHE is not None:return FONT_CACHE
 with FONT_LOCK:
  if FONT_CACHE is not None:return FONT_CACHE
  fonts=set();math_status={};status='unavailable'
  if sys.platform=='darwin':
   try:
    result=subprocess.run(['/usr/sbin/system_profiler','-json','SPFontsDataType'],capture_output=True,text=True,timeout=25,check=True)
    records=json.loads(result.stdout).get('SPFontsDataType',[])
    for record in records:
     if record.get('enabled')!='yes':continue
     for face in record.get('typefaces',[]):
      if face.get('enabled')=='yes' and face.get('valid')=='yes' and face.get('family','').strip():
       family=face['family'].strip();fonts.add(family)
       observed=inspect_font_file(record.get('path',''))
       previous=math_status.get(family)
       if previous is None:math_status[family]=observed
       elif previous!=observed:math_status[family]='unknown'
    status='detected'
   except Exception:status='failed'
  FONT_CACHE={'installedFonts':sorted(fonts,key=str.casefold),'mathFontStatus':math_status,'commonFonts':FONT_FALLBACK,'fonts':sorted(fonts,key=str.casefold),'source':'检测到的本机字体','detection':{'status':status,'renderVerified':False}}
 return FONT_CACHE

def confirmed_defaults():
 profile=default_profile()
 for target,fields in SCHEMA.items():
  destinations=profile['styles'].values() if target=='style' else [profile[target]]
  for dest in destinations:dest['_fieldStates']={key:'unspecified' for key in fields if key!='enabled'}
 profile['schemaVersion']=1;profile['ruleLedger']={};return profile

def import_document(name,data):
 if not isinstance(data,bytes) or not data or len(data)>(5 if course_config.enabled else 30)*1024*1024:raise ValueError('DOCX超过当前运行环境限制')
 model=inspect_doc(data)
 with LOCK:
  if len(STORE)>=100 or sum(len(x['data']) for x in STORE.values())+len(data)>MAX_BYTES:raise ValueError('会话文档超过100份或220MB，请移除文档')
  identifier=secrets.token_hex(16);STORE[identifier]={'data':data,'name':Path(str(name)).name,'time':time.time()}
 return {'id':identifier,'name':Path(str(name)).name,'model':model,'sourceData':base64.b64encode(data).decode(),'sourceHash':hashlib.sha256(data).hexdigest()}

def get_source(identifier):
 with LOCK:source=STORE.get(identifier)
 if source is None:raise ValueError('文档会话已失效，请恢复项目或重新导入')
 return source

def source_name(identifier):
 with LOCK:return STORE.get(identifier,{}).get('name','失效文档.docx')

def validate_profile_values(profile,overrides=None):
 candidates=[]
 def group(target,role,dest):
  states=dest.get('_fieldStates',{})
  for field,(unit,kind,_) in SCHEMA[target].items():
   if field not in dest or dest[field] is None or states.get(field) in ['preserve','clear','unspecified']:continue
   if field=='columns' and dest[field]=='':continue
   if unit=='dynamic':unit=dest.get('indentUnit','cm') if field=='indent' else 'multiple' if dest.get('lineMode','multiple')=='multiple' else 'pt'
   candidates.append({'target':target,'role':role,'field':field,'state':'set','value':dest[field],'unit':unit})
 for role,dest in profile.get('styles',{}).items():group('style',role,dest)
 for target in ['page','table','equation']:group(target,None,profile.get(target,{}))
 for dest in (overrides or {}).values():group('style','body',dest)
 # Profile may contain nine roles and many local overlays; validate in bounded chunks.
 for i in range(0,len(candidates),1000):validate_items(candidates[i:i+1000])

def execute(settings,source=None):
 source=source or get_source(settings.get('id'));settings=clean(settings);validate_profile_values(settings.get('profile') or confirmed_defaults(),settings.get('overrides'))
 retry_history=[]
 try:result,report=transform(source['data'],settings)
 except ValueError as error:
  if not str(error).startswith('段落格式写回核验失败') or settings.get('_forceDirectFormatting') is True:raise
  retry_history.append({'attempt':1,'reason':str(error)[:500],'action':'仅把已确认字段重新写为直接格式，保留原生样式；不放宽内容或保真检查','maxAttempts':2})
  settings={**settings,'_forceDirectFormatting':True}
  try:result,report=transform(source['data'],settings)
  except ValueError as second:raise ValueError('已进行1次有界格式重试仍失败，停止导出：'+str(second)) from None
 before=inspect_doc(source['data']);roles=[{'id':p['id'],'role':settings.get('roles',{}).get(p['id'],p['role'])} for p in before['paragraphs'] if p['role'] not in ['cell','empty','equation']]
 outline,issues=audit_outline(roles,before)
 report['checks'].append({'name':'图片、引用域与书签结构','status':'pass','detail':'引擎读回比较图片绘图标记、引用域、书签和修订结构，任何不一致都会停止导出'})
 report['structure']={'outline':outline,'issues':issues,'confidence':'人工确认或待复核的分类，不是AI准确率'}
 report['checks'].append({'name':'标题级别与编号','status':'pending' if issues else 'pass','detail':'发现需人工复核的结构问题' if issues else '按最终分类检查标题跳级与重复编号'})
 installed=set(available_fonts()['installedFonts']);requested=set();actual=set();unresolved=0
 for x in settings.get('profile',{}).get('styles',{}).values():
  if not x.get('enabled',True):continue
  for field in ['font','latin']:
   if x.get('_fieldStates',{}).get(field) not in ['unspecified','preserve','clear'] and x.get(field):requested.add(x[field])
 exported,_=package(result);tree=parse(exported['word/document.xml']);effective=style_context(exported)[4]
 for p in tree.findall('.//'+q('p')):
  for r in p.xpath('.//w:r[w:t or w:delText][not(ancestor::m:oMath)]',namespaces=NS):
   fmt=effective(p,r)
   for field in ['font','latin']:
    if fmt.get(field):actual.add(fmt[field])
    else:unresolved+=1
 math_runs=tree.findall('.//'+q('m:r'))
 for run in math_runs:
  fonts_node=child(child(run,'rPr'),'rFonts')
  if fonts_node is not None:
   for field in ['ascii','hAnsi','eastAsia','cs']:
    name=fonts_node.get(q(field))
    if name:actual.add(name)
 math_requested=set()
 for e in settings.get('equations',{}).values():
  f=e.get('format',{}) if isinstance(e,dict) else {}
  if f.get('font') and f.get('_fieldStates',{}).get('font') not in ['unspecified','preserve','clear']:
   requested.add(f['font']);math_requested.add(f['font'])
 eq=settings.get('profile',{}).get('equation',{})
 if eq.get('enabled') and eq.get('font') and eq.get('_fieldStates',{}).get('font') not in ['unspecified','preserve','clear']:
  requested.add(eq['font']);math_requested.add(eq['font'])
 fonts=actual|requested;missing=fonts-installed
 report['fontAvailability']={'requestedFonts':sorted(requested),'outputResolvedFonts':sorted(actual),'detectedInstalled':sorted(fonts&installed),'notDetected':sorted(missing),'unresolvedThemeFields':unresolved,'substitution':'由Word/WPS及系统选择；未实测目标软件的替代结果','catalogDetection':available_fonts()['detection']}
 report['fontAvailability']['mathRunsInspected']=len(math_runs)
 report['fontAvailability']['mathFontAssessments']=[font_assessment(name,available_fonts()) for name in sorted(math_requested)]
 if math_requested:
  report['checks'].append({'name':'公式字体在 Word/WPS 中的显示','status':'pending','detail':'已将所选字体名称写入公式，并非实际渲染验证；普通字体或缺少数学排版表的字体可能被 Word 替换为 Cambria Math。请在目标 Word/WPS 逐项复核。'})
  for item in report['fontAvailability']['mathFontAssessments']:
   if item['status'] in ('ordinary','not_detected','unknown'):
    report['warnings'].append('公式字体 '+item['font']+'：'+{'ordinary':'检测到字体但未发现数学排版 MATH 表','not_detected':'本机未检测到该字体','unknown':'无法确认其数学排版支持'}[item['status']]+'；Word 可能替换为 Cambria Math，建议使用已安装的数学字体并在目标软件复核。')
 if missing:report['warnings'].append('未检测到这些字体：'+', '.join(sorted(missing))+'；字体名称写入DOCX，预览或目标设备可能替代。')
 if unresolved:report['warnings'].append('部分原稿主题字体尚未映射为确定字体名称，请在目标Word/WPS环境检查。')
 report['checks'].append({'name':'字体可用性','status':'pending' if missing or unresolved else 'pass','detail':'对输出全部文字run检查可解析字体名称；安装检测不代表Word/WPS渲染验证，主题字体未知及缺失见fontAvailability'})
 report['ruleLedger']=settings.get('profile',{}).get('ruleLedger',{});report['previewMode']='structure';report['retryHistory']=retry_history;report['humanReview']=[{'name':c['name'],'reason':c['detail']} for c in report['checks'] if c['status']=='pending'];report['classificationLocks']=settings.get('locks',{});report['classificationReview']=settings.get('classificationReview',{})
 return result,report

TASKS=TaskManager(execute,source_name)

def preview_changes(settings):
 source=get_source(settings.get('id'));result,report=execute(settings)
 a=inspect_doc(source['data']);b=inspect_doc(result);changes=[];profile=settings.get('profile',{});ledger=profile.get('ruleLedger',{})
 def add(kind,obj,field,before,after,role=None):
  if before==after:return
  src=ledger.get(('styles.'+role if role else kind)+'.'+field,{}).get('source') or {'kind':'manual_or_preserved','text':'当前设置 / 原稿保留'}
  changes.append({'kind':kind,'object':obj,'field':field,'before':before,'after':after,'source':src})
 by_new={p['id']:p for p in b['paragraphs']};mapping=report.get('paragraphMap',{})
 for old in a['paragraphs']:
  new=by_new[mapping.get(old['id'],old['id'])]
  role=settings.get('roles',{}).get(old['id'],old['role']);add('style',old['id'],'role',old['role'],role,role);add('style',old['id'],'style',old.get('styleId'),new.get('styleId'),role)
  for key in sorted(set(old['format'])|set(new['format'])):add('style',old['id'],key,old['format'].get(key),new['format'].get(key),role)
 # Run-level changes are included, so mixed formatting is reviewable before writing.
 pa,_=package(source['data']);pb,_=package(result);ra=parse(pa['word/document.xml']);rb=parse(pb['word/document.xml']);ea=style_context(pa)[4];eb=style_context(pb)[4]
 newpars=rb.findall('.//'+q('p'))
 for pi,op in enumerate(ra.findall('.//'+q('p'))):
  np=newpars[int(mapping.get(f'p{pi}',f'p{pi}')[1:])]
  ors=op.xpath('.//w:r[w:t or w:delText][not(ancestor::m:oMath)]',namespaces=NS);nrs=np.xpath('.//w:r[w:t or w:delText][not(ancestor::m:oMath)]',namespaces=NS)
  for ri,(orr,nr) in enumerate(zip(ors,nrs)):
   f1=ea(op,orr);f2=eb(np,nr)
   for key in ['font','latin','size','bold','italic','underline','color']:add('style',f'p{pi}/run{ri}',key,f1.get(key),f2.get(key),settings.get('roles',{}).get(f'p{pi}',a['paragraphs'][pi]['role']))
 for i,(op,np) in enumerate(zip(ra.findall('.//'+q('tbl')),rb.findall('.//'+q('tbl')))):
  for field,tag in [('tableProperties','tblPr'),('columns','tblGrid')]:
   first=child(op,tag);second=child(np,tag);add('table',f't{i}',field,None if first is None else __import__('lxml.etree',fromlist=['tostring']).tostring(first).decode(),None if second is None else __import__('lxml.etree',fromlist=['tostring']).tostring(second).decode())
  for ci,(oc,nc) in enumerate(zip(op.findall('.//'+q('tc')),np.findall('.//'+q('tc')))):
   def props(c):return [__import__('lxml.etree',fromlist=['tostring']).tostring(x).decode() for x in c.findall(q('tcPr'))]
   add('table',f't{i}/cell{ci}','cellProperties',props(oc),props(nc))
 for i,(old,new) in enumerate(zip(ra.findall('.//'+q('sectPr')),rb.findall('.//'+q('sectPr')))):
  for tag in ['pgSz','pgMar']:
   def attrs(n):e=child(n,tag);return {} if e is None else {k.rsplit('}',1)[-1]:v for k,v in e.attrib.items()}
   add('page',f'section{i}',tag,attrs(old),attrs(new))
 originals={e['id']:e for e in a['equations']};outputs={e['id']:e for e in b['equations']}
 for eid,x in settings.get('equations',{}).items():
  if 'latex' in x:add('equation',eid,'expression',originals.get(eid,{}).get('latex'),x['latex'])
  if x.get('convertLatex'):
   add('equation',eid,'conversion','LaTeX 文本','明确转换为 Word 原生公式')
   changes[-1]['source']={'kind':'user_requirement','text':'用户确认转换该段 LaTeX'}
  if 'layout' in x:add('equation',eid,'layout','原段落设置',x['layout'])
 for eid,fields in report.get('equationFormatting',{}).items():
  before=originals.get(eid,{}).get('runFormats',[]);after=outputs.get(report.get('equationMap',{}).get(eid),{}).get('runFormats',[])
  for field in fields:
   key='latin' if field=='font' else field
   old=list(dict.fromkeys(str(x.get(key,'继承 / 未指定')) for x in before));new=list(dict.fromkeys(str(x.get(key,'继承 / 未指定')) for x in after))
   change_count=len(changes)
   add('equation',eid+'（'+str(len(after))+' 个文字片段）',field,old,new)
   if len(changes)>change_count and field in settings.get('equations',{}).get(eid,{}).get('format',{}):
    changes[-1]['source']={'kind':'user_requirement','text':'手工设置当前公式，覆盖全文规则'}
 for x in settings.get('insertions',[]):add('equation',x.get('id'),'insert',None,x.get('latex'))
 return {'changes':changes,'warnings':report['warnings'],'summary':{'changes':len(changes),'affectedParagraphs':report['validation']['affectedParagraphs'],'runsChecked':report['validation']['textRunsChecked'],'note':'原稿未改变；使用同一执行器生成新字节进行预览校验'}}

def restore_project(raw):
 state=sanitize_state(raw);imports=[];idmap={};pdfrecords=[];pdfmap={};newdocs={};newpdfs={}
 oldids={d['id'] for d in state['documents']};oldpdfids={p.get('id') for p in state['workflow'].get('pdfs',[])}
 for d in state['documents']:
  original=d['id'];data,sha=decode_source(d,30*1024*1024);model=inspect_doc(data);identifier=secrets.token_hex(16)
  source={'data':data,'name':Path(str(d.get('name','恢复文档.docx'))).name,'time':time.time()};newdocs[identifier]=source
  new={'id':identifier,'name':source['name'],'model':model,'sourceData':base64.b64encode(data).decode(),'sourceHash':sha}
  idmap[original]=identifier;d['id']=identifier;imports.append(new)
  if d.get('result'):
   try:
    settings={k:d.get(k,{}) for k in ['roles','overrides','tables','equations']};settings.update(id=identifier,profile=state['profile'],locks=d.get('aiLocks',{}),insertions=d.get('insertions',[]),classificationReview={'sourceMode':d.get('aiSummary',{}).get('sourceMode','manual'),'liveVerified':bool(d.get('aiSummary',{}).get('liveVerified')),'items':d.get('aiCandidates',[])})
    output,report=execute(settings,source);saved=base64.b64decode(d['result'],validate=True)
    if package(saved)[0]!=package(output)[0]:raise ValueError('旧输出与恢复后的设置不一致')
    pagination=(d.get('report') or {}).get('pagination')
    if isinstance(pagination,dict) and pagination.get('sourceSHA256')==report['resultSHA256']:
     report['pagination']={k:v for k,v in clean(pagination).items() if k!='id'}
     report['pagination'].update(visualReview='pending',WordWpsVerified=False,restoredMetadataUnverified=True,runtimeAvailable=False)
    d['report']=report;d['report']['restoredAndRechecked']=True
   except Exception:
    d['result']=None;d['report']=None;d['restoreWarning']='旧输出未通过恢复核验，请重新排版；原稿和人工设置已保留'
 for p in state['workflow'].get('pdfs',[]):
  if not p.get('sourceData'):continue
  data,sha=decode_source(p);identifier=secrets.token_hex(16);pdfmap[p.get('id')]=identifier
  newpdfs[identifier]={'data':data,'name':p.get('name','参考PDF.pdf')};p['id']=identifier;pdfrecords.append(p)
 # Commit only when all sources and capacity checks succeeded; repeated restores
 # replace the previous IDs from this same project instead of leaking sessions.
 with LOCK:
  retained={k:v for k,v in STORE.items() if k not in oldids};retainedpdf={k:v for k,v in PDFSTORE.items() if k not in oldpdfids}
  if len(retained)+len(newdocs)>100 or sum(len(x['data']) for x in [*retained.values(),*newdocs.values()])>MAX_BYTES:raise ValueError('恢复项目超过会话文档容量，请移除其他文档或重启服务')
  if len(retainedpdf)+len(newpdfs)>100 or sum(len(x['data']) for x in [*retainedpdf.values(),*newpdfs.values()])>200*1024*1024:raise ValueError('恢复项目超过参考PDF容量')
  STORE.clear();STORE.update(retained);STORE.update(newdocs);PDFSTORE.clear();PDFSTORE.update(retainedpdf);PDFSTORE.update(newpdfs)
 state['view']['current']=idmap.get(state['view'].get('current'),state['view'].get('current'))
 wf=state['workflow'];wf['selectedPdf']=pdfmap.get(wf.get('selectedPdf'),wf.get('selectedPdf'));wf['templatePdfIds']=[pdfmap.get(x,x) for x in wf.get('templatePdfIds',[])];wf['batchId']=None
 if isinstance(wf.get('batch'),dict):
  for row in wf['batch'].get('items',[]):
   if isinstance(row,dict):row['id']=idmap.get(row.get('id'),row.get('id'))
  restored_batch=TASKS.restore(wf['batch'],state['documents'],state['profile']);wf['batch']=restored_batch;wf['batchId']=restored_batch['id'] if restored_batch else None
 return {'state':state,'documents':imports,'idMap':idmap,'pdfRecords':pdfrecords,'pdfIdMap':pdfmap}

def deepseek_request(key,model,messages,structured=False,max_tokens=2048):
    body={'model':model,'messages':messages,'max_tokens':max_tokens,'stream':False,'thinking':{'type':'disabled'}}
    if structured: body['response_format']={'type':'json_object'}
    request=Request('https://api.deepseek.com/chat/completions',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    try:
        with urlopen(request,timeout=90) as response: result=json.loads(response.read(5*1024*1024))
    except HTTPError as e:
        messages={401:'API Key 无效或已失效',402:'账户余额不足或 API 服务未开通',403:'API 请求未获授权',404:'模型暂不可用，请更换模型后重试',429:'请求频率受限，请稍后再试'}
        raise ValueError(messages.get(e.code,'DeepSeek 服务暂不可用，请检查网络后重试')) from None
    except (URLError,TimeoutError):
        raise ValueError('连接 DeepSeek 失败，请检查网络后重试') from None
    except json.JSONDecodeError:
        raise ValueError('DeepSeek 返回内容无法读取，请重试') from None
    choices=result.get('choices') or []
    content=choices[0].get('message',{}).get('content') if choices else None
    if not isinstance(content,str) or not content.strip(): raise ValueError('DeepSeek 没有返回可读取的结果，请重试')
    return content

class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def send(self,status,data,kind='application/json; charset=utf-8'):
  raw=json.dumps(data,ensure_ascii=False,allow_nan=False).encode() if not isinstance(data,bytes) else data
  self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)));self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store' if kind.startswith('application/json') else 'no-cache');self.send_header('Referrer-Policy','no-referrer');self.end_headers();self.wfile.write(raw)
 def allowed(self):
  origin=self.headers.get('Origin');return course_config.allowed(self.headers.get('Host'),origin) if course_config.enabled else hosting_config({}).__class__(False,port=self.server.server_port).allowed(self.headers.get('Host'),origin)
 def do_GET(self):
  if not self.allowed():return self.send(403,{'error':'仅允许本机页面访问'})
  path=urlparse(self.path).path
  try:
   if path=='/api/health':return self.send(200,{'status':'ok','version':'5.0','engine':'local-ooxml','formula':True,'liveAiVerified':bool(DEEPSEEK['checked']),'courseMode':course_config.enabled})
   if path=='/api/fonts':
    cloud=json.loads((BASE/'office_cloud_fonts.json').read_text(encoding='utf-8'));return self.send(200,{**available_fonts(),'officeFonts':cloud.get('fonts',[]),'officeSource':cloud.get('source_url',''),'officeUpdated':cloud.get('source_last_updated')})
   if path=='/api/deepseek/status':return self.send(200,deepseek_status())
   if path=='/api/defaults':return self.send(200,confirmed_defaults())
   if path=='/api/sample':return self.send(200,import_document('自建演示文档.docx',create_sample()))
   if path=='/api/render/status':return self.send(200,render_status())
   if path=='/api/rules/schema':return self.send(200,schema())
   if path=='/api/projects':return self.send(200,{'projects':DISK.list_projects()})
   if path=='/api/templates':return self.send(200,{'templates':DISK.list_templates()})
   match=re.fullmatch(r'/api/render/([a-f0-9]{32})/(page/(\d+)|download)',path)
   if match:
    with LOCK:rendered=RENDERSTORE.get(match[1])
    if not rendered:raise ValueError('分页参考会话已失效，请重新生成')
    return self.send(200,render_page(rendered['data'],int(match[3])),'image/png') if match[3] else self.send(200,rendered['data'],'application/pdf')
   match=re.fullmatch(r'/api/pdf/([a-f0-9]{32})/page/(\d+)',path)
   if match:
    with LOCK:pdf=PDFSTORE.get(match[1])
    if not pdf:raise ValueError('参考PDF会话已失效，请恢复项目')
    return self.send(200,render_page(pdf['data'],int(match[2])),'image/png')
   match=re.fullmatch('/api/tasks/([a-f0-9]{32})(/download)?',path)
   if match:return self.send(200,TASKS.download(match[1]),'application/zip') if match[2] else self.send(200,TASKS.snapshot(match[1]))
   mapping={'/':'index.html','/index.html':'index.html','/app.js':'app.js','/style.css':'style.css','/workflow.js':'workflow.js','/workflow.css':'workflow.css','/journals.json':'journals.json'}
   file=BASE/mapping[path] if path in mapping else BASE/path.lstrip('/') if path.startswith('/vendor/') else None
   if file is None or not file.resolve().is_relative_to(BASE) or not file.is_file():return self.send(404,{'error':'未找到资源'})
   return self.send(200,file.read_bytes(),mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
  except Exception as e:return self.send(400,{'error':safe_error(e)})
 def do_POST(self):
  if course_config.enabled and not COURSE_POST_LOCK.acquire(blocking=False):return self.send(429,{'error':'服务器正在处理请求，请稍后重试'})
  try:return self._post()
  finally:
   if course_config.enabled:COURSE_POST_LOCK.release()
 def _post(self):
  if not self.allowed():return self.send(403,{'error':'请求来源不匹配'})
  if course_config.enabled and self.headers.get('Origin')!=course_config.origin:return self.send(403,{'error':'课程服务器仅接受同源网页请求'})
  try:
   length=int(self.headers.get('Content-Length','0'))
   if length<=0 or length>(16 if course_config.enabled else 280)*1024*1024:raise ValueError('请求大小超过当前运行环境限制')
   if not self.headers.get('Content-Type','').startswith('application/json'):raise ValueError('仅接受JSON请求')
   payload=json.loads(self.rfile.read(length),parse_constant=lambda x:(_ for _ in ()).throw(ValueError('不支持NaN/Infinity')))
   if not isinstance(payload,dict):raise ValueError('请求应为JSON对象')
   path=urlparse(self.path).path
   if path=='/api/deepseek/disconnect':
    if course_config.enabled:raise ValueError('服务器密钥由课程上传页面管理')
    with LOCK:DEEPSEEK.update(key=None,checked=None)
    return self.send(200,{'connected':False,'model':DEEPSEEK['model']})
   if path=='/api/deepseek/connect':
    key=str(payload.get('key','')).strip();model=payload.get('model','deepseek-flash')
    if model not in DEEPSEEK_MODELS or len(key)>512:raise ValueError('模型或密钥长度无效')
    if course_config.enabled:return self.send(200,course_connect(key,model))
    with LOCK:candidate=key or DEEPSEEK['key']
    if not candidate:raise ValueError('请填写API Key')
    deepseek_request(candidate,model,[{'role':'user','content':'Reply with OK.'}],max_tokens=16)
    with LOCK:DEEPSEEK.update(key=candidate,model=model,checked=time.time())
    return self.send(200,{'connected':True,'model':model,'checked':DEEPSEEK['checked']})
   if path=='/api/rules/parse':
    if payload.get('mode','local')=='local':return self.send(200,parse_local(payload.get('text')))
    if payload.get('mode')!='deepseek':raise ValueError('解析方式无效')
    key,model=ai_credentials();return self.send(200,parse_requirements(deepseek_request,key,model,payload.get('text')))
   if path=='/api/rules/apply':return self.send(200,apply_rules(payload.get('profile') or confirmed_defaults(),payload.get('items'),bool(payload.get('resolveConflicts'))))
   if path in ['/api/structure','/api/deepseek/analyze']:
    source=get_source(payload.get('id'));document=inspect_doc(source['data'])
    if path=='/api/structure':return self.send(200,analyze_local(document,payload.get('locks'),payload.get('roles')))
    key,model=ai_credentials();return self.send(200,analyze_document(deepseek_request,key,model,document,payload.get('profile') or confirmed_defaults(),payload.get('notes',''),payload.get('locks'),payload.get('roles')))
   if path=='/api/pdf/import':
    data=base64.b64decode(payload.get('data',''),validate=True)
    if len(data)>(5 if course_config.enabled else 25)*1024*1024:raise ValueError('参考PDF超过当前运行环境限制')
    metadata=clean(payload.get('metadata') or {});out=analyze_pdf(data,str(payload.get('name','参考PDF.pdf')),metadata);identifier=secrets.token_hex(16)
    with LOCK:
     if len(PDFSTORE)>=100 or sum(len(x['data']) for x in PDFSTORE.values())+len(data)>(20 if course_config.enabled else 200)*1024*1024:raise ValueError('参考PDF总量超过100份或200MB')
     PDFSTORE[identifier]={'data':data,'name':out.get('name',payload.get('name'))}
    return self.send(200,{**out,'id':identifier,'sourceData':base64.b64encode(data).decode(),'sourceHash':hashlib.sha256(data).hexdigest()})
   if path=='/api/templates/save':return self.send(200,DISK.save_template(payload.get('name'),payload.get('purpose'),payload.get('metadata'),payload.get('items'),payload.get('pdfIds',[])))
   if path=='/api/projects/save':return self.send(200,{'project':DISK.save_project(payload.get('name'),payload.get('state'),payload.get('id'))})
   if path=='/api/projects/restore':
    state=payload.get('state') if 'state' in payload else DISK.read('projects',payload.get('id'))['state'];return self.send(200,restore_project(state))
   if path=='/api/projects/delete':return self.send(200,DISK.delete_project(payload.get('id')))
   if path=='/api/tasks/start':
    if course_config.enabled and len(payload.get('documents') or [])>3:raise ValueError('课程演示版每批最多处理3份文档')
    return self.send(200,TASKS.start(payload.get('documents')))
   if path=='/api/tasks/cancel':return self.send(200,TASKS.cancel(payload.get('id')))
   if path=='/api/tasks/retry':return self.send(200,TASKS.retry(payload.get('id'),payload.get('documents')))
   if path=='/api/import':return self.send(200,import_document(payload.get('name'),base64.b64decode(payload.get('data',''),validate=True)))
   if path=='/api/release':
    with LOCK:STORE.pop(payload.get('id'),None)
    return self.send(200,{'ok':True})
   if path=='/api/formula':
    _,mathml=formula(payload['latex']);return self.send(200,{'mathml':mathml})
   if path=='/api/render':
    data=base64.b64decode(payload.get('data',''),validate=True);info,pdf=render_output(data)
    if pdf:
     identifier=secrets.token_hex(16)
     with LOCK:
      while len(RENDERSTORE)>=10:RENDERSTORE.pop(next(iter(RENDERSTORE)))
      RENDERSTORE[identifier]={'data':pdf,'time':time.time()}
     info.update(id=identifier,sourceSHA256=hashlib.sha256(data).hexdigest())
    return self.send(200,info)
   if path=='/api/preview':return self.send(200,preview_changes(payload))
   if path=='/api/format':
    result,report=execute(payload);return self.send(200,{'data':base64.b64encode(result).decode(),'report':report})
   return self.send(404,{'error':'接口不存在'})
  except Exception as e:return self.send(400,{'error':safe_error(e)})

def safe_error(error):
 text=str(error)[:500]
 with LOCK:key=os.environ.get('DEEPSEEK_API_KEY') if course_config.enabled else DEEPSEEK.get('key')
 if key:text=text.replace(key,'[已隐藏]')
 return text

def deepseek_status():
 with LOCK:
  return {k:DEEPSEEK[k] for k in ['model','checked']}|{'connected':bool(DEEPSEEK['checked']) if course_config.enabled else bool(DEEPSEEK['key']),'configured':bool(os.environ.get('DEEPSEEK_API_KEY')) if course_config.enabled else bool(DEEPSEEK['key']),'serverManaged':course_config.enabled}

def course_connect(key,model):
 if key:raise ValueError('课程服务器不接受网页输入密钥；请在上传管理页配置')
 candidate=os.environ.get('DEEPSEEK_API_KEY','')
 if not candidate:raise ValueError('请由组员在课程上传页配置 DEEPSEEK_API_KEY')
 deepseek_request(candidate,model,[{'role':'user','content':'Reply with OK.'}],max_tokens=16)
 with LOCK:DEEPSEEK.update(model=model,checked=time.time())
 return deepseek_status()

def ai_credentials():
 with LOCK:key=os.environ.get('DEEPSEEK_API_KEY') if course_config.enabled else DEEPSEEK['key'];model=DEEPSEEK['model']
 if not key:raise ValueError('请先在DeepSeek API设置中连接并测试；真实AI调用尚未验证')
 return key,model

def open_workbench(url):
 """Use Launch Services on macOS; report failures instead of silently exiting."""
 try:
  if sys.platform=='darwin':
   result=subprocess.run(['/usr/bin/open',url],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,timeout=10)
   opened=result.returncode==0
  else:opened=bool(webbrowser.open(url,new=2,autoraise=True))
 except Exception:
  opened=False
 if opened:print('已请求浏览器打开工作台：'+url,flush=True)
 else:print('未能自动打开浏览器。请将以下地址复制到浏览器地址栏：'+url,flush=True)
 return opened

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=course_config.port);parser.add_argument('--open',action='store_true');args=parser.parse_args()
 try:server=ThreadingHTTPServer((course_config.host,args.port),Handler)
 except OSError:
  if args.open:
   try:
    with urlopen(f'http://127.0.0.1:{args.port}/api/health',timeout=2) as r:health=json.load(r)
    if health.get('version')=='5.0' and health.get('engine')=='local-ooxml':
     url=f'http://127.0.0.1:{args.port}'
     print('DocStyle AI 已在运行，正在打开已有工作台。',flush=True)
     open_workbench(url);return
   except Exception:pass
  print(f'端口{args.port}已占用，请用--port指定其他端口。',flush=True);raise SystemExit(1)
 url=f'http://127.0.0.1:{args.port}';print(f'DocStyle AI 5.0 已启动：{url}\n'+('课程服务器模式：项目/模板为共享数据；密钥从服务器环境读取。' if course_config.enabled else '文档在本机处理；确认的项目/模板保存到本机，API Key仅在内存。'),flush=True)
 if args.open:open_workbench(url)
 try:server.serve_forever()
 except KeyboardInterrupt:server.server_close()
if __name__=='__main__':main()
