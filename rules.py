# coding: utf-8
"""Typed, evidence-bearing candidates. Unknown values never become zero."""
import copy, math, re, uuid
from datetime import datetime, timezone
ROLE_LABELS={'title':'论文标题',**{f'heading{i}':f'{i}级标题' for i in range(1,10)},'author':'作者信息','abstract':'摘要','keywords':'关键词','body':'正文','caption':'图表题注','note':'表注 / 资料来源','reference':'参考文献'}
STYLE_FIELDS={
 'font':('name','str',None),'latin':('name','str',None),'size':('pt','number',(1,200)),
 'before':('pt','number',(0,500)),'after':('pt','number',(0,500)),
 'left':('cm','number',(0,30)),'right':('cm','number',(0,30)),'indent':('dynamic','number',(0,30)),
 'indentUnit':('enum','enum',['cm','chars']),'indentMode':('enum','enum',['firstLine','hanging','none']),
 'line':('dynamic','number',(.1,200)),'lineMode':('enum','enum',['multiple','exact','atLeast']),
 'align':('enum','enum',['left','right','center','both']),'bold':('bool','bool',None),'italic':('bool','bool',None),
 'underline':('bool','bool',None),'color':('hex','color',None),'enabled':('bool','bool',None),
 'keepNext':('bool','bool',None),'keepLines':('bool','bool',None),'pageBreak':('bool','bool',None),'widow':('bool','bool',None)}
PAGE_FIELDS={k:('cm','number',(0,12)) for k in ['top','bottom','left','right','header','footer']}
PAGE_FIELDS.update(enabled=('bool','bool',None),paper=('enum','enum',['A4','A3','Letter']),orientation=('enum','enum',['portrait','landscape']))
TABLE_FIELDS={k:STYLE_FIELDS[k] for k in ['font','latin','size','enabled','before','after','line','lineMode']}
TABLE_FIELDS.update(borderMode=('enum','enum',['three','grid','none','custom','preserve']),borderSize=('pt','number',(.25,6)),borderColor=('hex','color',None),headerRows=('count','number',(0,100)),headerFill=('hex','color',None),headerBold=('bool','bool',None),width=('percent','number',(1,100)),align=STYLE_FIELDS['align'],cellAlign=STYLE_FIELDS['align'],valign=('enum','enum',['top','center','bottom']),rowHeight=('pt','number',(0,500)),repeatHeader=('bool','bool',None),preventSplit=('bool','bool',None))
TABLE_FIELDS.update(layout=('enum','enum',['autofit','fixed']),rowRule=('enum','enum',['exact','atLeast']),columns=('cm_list','str',None))
TABLE_FIELDS.update({k:('pt','number',(0,100)) for k in ['paddingTop','paddingBottom','paddingLeft','paddingRight']})
EQUATION_FIELDS={k:STYLE_FIELDS[k] for k in ['enabled','align','before','after','font','size','bold','italic','color']}
EQUATION_FIELDS['scope']=('enum','enum',['all','display','inline'])
SCHEMA={'style':STYLE_FIELDS,'page':PAGE_FIELDS,'table':TABLE_FIELDS,'equation':EQUATION_FIELDS}
STATES={'set','preserve','clear','unspecified'}
SIZES={'初号':42,'小初':36,'一号':26,'小一':24,'二号':22,'小二':18,'三号':16,'小三':15,'四号':14,'小四':12,'五号':10.5,'小五':9,'六号':7.5,'小六':6.5,'七号':5.5,'八号':5}
FONTS=['Times New Roman','Microsoft YaHei','Arial','Calibri','Aptos','Cambria Math','Cambria','宋体','黑体','楷体','仿宋','微软雅黑','等线','华文中宋','华文仿宋','华文楷体','华文宋体','华文细黑','华文黑体','苹方-简','思源黑体','思源宋体']
def schema():
 return {'version':1,'roles':ROLE_LABELS,'states':sorted(STATES),'targets':{t:{k:{'unit':v[0],'type':v[1],'rangeOrChoices':v[2]} for k,v in fields.items()} for t,fields in SCHEMA.items()}}
def path(item):return ('styles.'+item['role'] if item['target']=='style' else item['target'])+'.'+item['field']
def validate_items(items,source_kind='user_requirements'):
 if not isinstance(items,list) or len(items)>1000:raise ValueError('规则候选应为不超过1000项的列表')
 out=[];seen=set()
 for raw in items:
  if not isinstance(raw,dict):raise ValueError('规则候选结构无效')
  target=raw.get('target','style'); role=raw.get('role') if target=='style' else None;field=raw.get('field');state=raw.get('state','set')
  if target not in SCHEMA or field not in SCHEMA[target] or state not in STATES:raise ValueError('规则目标、字段或状态无效')
  if target=='style' and role not in ROLE_LABELS:raise ValueError('规则角色无效')
  unit,kind,constraint=SCHEMA[target][field];value=raw.get('value');provided=raw.get('unit',unit)
  if unit=='dynamic':
   allowed=['pt','multiple'] if field=='line' else ['cm','chars']
   if provided not in allowed:raise ValueError('规则单位与字段不一致')
  elif provided!=unit:raise ValueError('规则单位与字段不一致')
  if state=='set':
   if kind=='number':
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not constraint[0]<=value<=constraint[1]:raise ValueError('规则数值无效或超出范围')
    if field in ['headerRows'] and int(value)!=value:raise ValueError('表头行数必须为整数')
    if target=='equation' and field=='size' and abs(value*2-round(value*2))>1e-9:raise ValueError('Word 公式字号需以 0.5 磅为步长')
   elif kind=='str':
    if not isinstance(value,str) or not value.strip() or len(value)>100 or re.search(r'[\x00-\x1f]',value):raise ValueError('字体名称无效')
    value=value.strip()
   elif kind=='bool' and not isinstance(value,bool):raise ValueError('开关规则必须为布尔值')
   elif kind=='enum' and value not in constraint:raise ValueError('规则枚举值无效')
   elif kind=='color' and (not isinstance(value,str) or not re.fullmatch(r'[A-Fa-f0-9]{6}',value)):raise ValueError('颜色规则必须为6位HEX')
  else:value=None
  if target=='table' and field=='align' and state=='set' and value=='both':raise ValueError('表格对齐应为左、右或居中')
  confidence=raw.get('confidence')
  if confidence is not None and (isinstance(confidence,bool) or not isinstance(confidence,(int,float)) or not math.isfinite(confidence) or not 0<=confidence<=1):raise ValueError('候选确定程度无效')
  identifier=str(raw.get('id') or uuid.uuid4().hex)
  if identifier in seen:raise ValueError('候选ID重复')
  seen.add(identifier)
  source=raw.get('source') or {'kind':source_kind}
  if not isinstance(source,dict):raise ValueError('规则来源无效')
  status=raw.get('status','pending')
  if status not in ['pending','confirmed','ignored']:raise ValueError('确认状态无效')
  out.append({'id':identifier,'target':target,'role':role,'field':field,'state':state,'value':value,'unit':provided,'status':status,'source':copy.deepcopy(source),'confidence':confidence,'schemaVersion':1})
 return out

def conflicts(items):
 by={};out=[]
 for item in items:
  if item['state']=='unspecified' or item['status']=='ignored':continue
  key=path(item);previous=by.get(key)
  if previous and (previous['state'],previous['value'],previous['unit'])!=(item['state'],item['value'],item['unit']):out.append({'path':key,'before':previous['value'],'after':item['value'],'beforeUnit':previous['unit'],'afterUnit':item['unit'],'beforeState':previous['state'],'afterState':item['state'],'ids':[previous['id'],item['id']],'reason':'同一字段出现不同候选'})
  by[key]=item
 return out

def apply_rules(profile,items,resolve_conflicts=False):
 items=validate_items(items);active=[x for x in items if x['status']=='confirmed' and x['state']!='unspecified']
 collision=conflicts(active)
 if collision: return {'profile':copy.deepcopy(profile),'ledger':[],'conflicts':collision}
 prior=profile.get('ruleLedger',{});collision=[]
 for item in active:
  old=prior.get(path(item))
  if old and (old.get('state'),old.get('value'),old.get('unit'))!=(item['state'],item['value'],item['unit']):collision.append({'path':path(item),'before':old.get('value'),'after':item['value'],'beforeUnit':old.get('unit'),'afterUnit':item['unit'],'beforeState':old.get('state'),'afterState':item['state'],'reason':'将覆盖已确认规则','sourceBefore':old.get('source'),'sourceAfter':item['source']})
 if collision and not resolve_conflicts:return {'profile':copy.deepcopy(profile),'ledger':[],'conflicts':collision}
 result=copy.deepcopy(profile);result.setdefault('ruleLedger',{})
 for item in active:
  dest=result.setdefault('styles',{}).setdefault(item['role'],{}) if item['target']=='style' else result.setdefault(item['target'],{})
  dest.setdefault('_fieldStates',{})[item['field']]=item['state']
  if item['state']=='set':
   dest[item['field']]=item['value']
   if item['field']=='indent':
    dest['indentUnit']=item['unit'];dest['_fieldStates']['indentUnit']='set'
   if item['field']=='line' and item['unit']=='multiple':dest['lineMode']='multiple';dest['_fieldStates']['lineMode']='set'
  elif item['state']=='clear':dest.pop(item['field'],None)
  record={**item,'confirmedAt':datetime.now(timezone.utc).isoformat()}
  result['ruleLedger'][path(item)]=record
 for item in active:
  if item['state']!='set' or item['field'] not in ['line','indent']:continue
  dest=result['styles'][item['role']] if item['target']=='style' else result[item['target']]
  mode='lineMode' if item['field']=='line' else 'indentMode'
  if item['field']=='line' and ((item['unit']=='pt' and dest.get(mode) not in ['exact','atLeast']) or (item['unit']=='multiple' and dest.get(mode)!='multiple')):raise ValueError('行距数值单位与行距模式冲突，请确认固定值/最小值或倍数模式')
  if item['field']=='indent' and dest.get(mode)=='none' and item['value']!=0:raise ValueError('无缩进与非零缩进量冲突')
  if dest.get('_fieldStates',{}).get(mode) in ['unspecified','preserve','clear']:
   raise ValueError('请同时确认'+('固定值或最小值行距模式' if mode=='lineMode' else '首行或悬挂缩进模式')+'，不能猜测未指定参数')
 result['schemaVersion']=1;result['version']=5
 return {'profile':result,'ledger':active,'conflicts':[]}

def parse_local(text):
 if not isinstance(text,str) or not text.strip() or len(text)>20000:raise ValueError('请输入不超过20000字符的格式要求')
 items=[];warnings=[];target='style';role=None
 def add(field,value,unit=None,state='set'):
  if target=='style' and role is None:return
  if field not in SCHEMA[target]:return
  items.append({'target':target,'role':role,'field':field,'value':value,'unit':unit or SCHEMA[target][field][0],'state':state,'status':'pending','source':{'kind':'user_requirements','text':chunk,'originalRequirements':text,'method':'local_explicit_parser'},'confidence':None})
 for chunk in re.split(r'[；;。\n，,、]',text):
  chunk=chunk.strip()
  if not chunk:continue
  h=re.search(r'([一二三四五六七八九1-9])\s*级标题',chunk)
  if h:target='style';role='heading'+str('一二三四五六七八九'.find(h[1])+1 if h[1] in '一二三四五六七八九' else int(h[1]))
  else:
   labels=[('论文标题|文章标题','title'),('参考文献','reference'),('资料来源|表注','note'),('图表标题|图表题注|图题|表题|题注','caption'),('关键词','keywords'),('摘要','abstract'),('作者信息|作者','author'),('正文','body')]
   found=next((value for pattern,value in labels if re.search(pattern,chunk)),None)
   if found:target='style';role=found
   elif re.search('页边距|页面|纸张|四周',chunk):target='page';role=None
   elif re.search('表格',chunk):target='table';role=None
   elif re.search('公式',chunk):target='equation';role=None
  used=False
  for field,label in [('size','字号'),('font','中文字体'),('latin','英文字体'),('before','段前'),('after','段后'),('line','行距'),('indent','缩进'),('color','颜色')]:
   if label in chunk and re.search('保留原文|不修改|沿用原文',chunk):add(field,None,state='preserve',unit='pt' if field=='line' else 'cm' if field=='indent' else None);used=True
   elif label in chunk and re.search('清除|取消设置|恢复默认',chunk):add(field,None,state='clear',unit='pt' if field=='line' else 'cm' if field=='indent' else None);used=True
  if used:continue
  if target in ['style','table','equation']:
   for font in sorted(FONTS,key=len,reverse=True):
    if font in chunk:
     field='font' if target=='equation' else ('latin' if re.search(r'[a-zA-Z]',font) or re.search('英文|数字|西文',chunk) else 'font')
     add(field,font);used=True;break
   custom=re.search(r'(数学字体|公式字体|中文字体|英文字体|数字字体)\s*[：:]?\s*[“"\']([^”"\']+)[”"\']',chunk)
   if custom:add('font' if target=='equation' or custom[1]=='中文字体' else 'latin',custom[2]);used=True
   chinese=next((value for name,value in sorted(SIZES.items(),key=lambda x:len(x[0]),reverse=True) if name in chunk),None)
   size=re.search(r'(?:字号\s*(?:为|是|[:：])?\s*)?(\d+(?:\.\d+)?)\s*(?:磅|pt)(?!.*(?:段前|段后))',chunk,re.I)
   if chinese is not None:add('size',chinese);used=True
   elif size and not re.search('段前|段后|行距|缩进|边距',chunk):add('size',float(size[1]));used=True
   if '不加粗' in chunk or '取消加粗' in chunk:add('bold',False);used=True
   elif '加粗' in chunk:add('bold',True);used=True
   if '斜体' in chunk:add('italic',not bool(re.search('不斜体|取消斜体',chunk)));used=True
   if '下划线' in chunk:add('underline',not bool(re.search('无下划线|取消下划线',chunk)));used=True
   color=re.search(r'(?:文字颜色|字体颜色|颜色)\s*(?:为|是|[:：])?\s*#?([0-9A-Fa-f]{6})(?![0-9A-Fa-f])',chunk)
   if color:add('color',color[1].upper());used=True
   elif '黑色' in chunk:add('color','000000');used=True
  for label,field in [('居中','align'),('两端对齐','align'),('左对齐','align'),('右对齐','align')]:
   if label in chunk:add(field,{'居中':'center','两端对齐':'both','左对齐':'left','右对齐':'right'}[label]);used=True
  for pattern,field in [(r'段前\s*(\d+(?:\.\d+)?)\s*(?:磅|pt)','before'),(r'段后\s*(\d+(?:\.\d+)?)\s*(?:磅|pt)','after')]:
   m=re.search(pattern,chunk,re.I)
   if m:add(field,float(m[1]));used=True
   elif re.search('段前' if field=='before' else '段后',chunk):warnings.append('段落间距单位缺失或暂不支持，请明确磅值：'+chunk);used=True
  m=re.search(r'(\d+(?:\.\d+)?)\s*倍\s*行距',chunk) or re.search(r'行距\s*(\d+(?:\.\d+)?)\s*倍',chunk)
  if m:add('lineMode','multiple');add('line',float(m[1]),'multiple');used=True
  m=re.search(r'(固定|最小|至少)\s*(?:值)?\s*行距\s*(\d+(?:\.\d+)?)\s*(?:磅|pt)',chunk,re.I)
  if m:add('lineMode','exact' if m[1]=='固定' else 'atLeast');add('line',float(m[2]),'pt');used=True
  if '单倍行距' in chunk:add('lineMode','multiple');add('line',1,'multiple');used=True
  m=re.search(r'(首行|悬挂)?\s*缩进\s*(\d+(?:\.\d+)?)\s*(字符|字|厘米|cm)',chunk,re.I)
  if m:add('indentMode','hanging' if m[1]=='悬挂' else 'firstLine');add('indentUnit','chars' if m[3] in ['字符','字'] else 'cm');add('indent',float(m[2]),'chars' if m[3] in ['字符','字'] else 'cm');used=True
  if target=='page':
   if 'A4' in chunk.upper():add('paper','A4');used=True
   if 'A3' in chunk.upper():add('paper','A3');used=True
   if '横向' in chunk:add('orientation','landscape');used=True
   elif '纵向' in chunk:add('orientation','portrait');used=True
   m=re.search(r'(四周|上|下|左|右).*?(\d+(?:\.\d+)?)\s*(厘米|cm)',chunk,re.I)
   if m:
    for field in ['top','bottom','left','right'] if m[1]=='四周' else [{'上':'top','下':'bottom','左':'left','右':'right'}[m[1]]]:add(field,float(m[2]))
    add('enabled',True);used=True
  if target=='table':
   if '三线表' in chunk:add('borderMode','three');add('enabled',True);used=True
   elif '网格' in chunk:add('borderMode','grid');add('enabled',True);used=True
   m=re.search(r'(\d+)\s*行表头|表头\s*(\d+)\s*行',chunk)
   if m:add('headerRows',int(m[1] or m[2]));used=True
  if re.search('适当|紧凑|合适|大约|自动判断|参考原图',chunk):warnings.append('存在模糊或不完整的要求，请人工明确：'+chunk[:160])
  if not used and not re.fullmatch(r'(英文|数字|中文|标题|正文|格式要求|不要改正文|内容不变)[：:]?',chunk):warnings.append('需人工确认：'+chunk[:160])
 if any(x['target']=='equation' and x['field']!='enabled' for x in items) and not any(x['target']=='equation' and x['field']=='enabled' for x in items):
  items.append({'target':'equation','field':'enabled','value':True,'unit':'bool','state':'set','status':'pending','source':{'kind':'user_requirements','text':'根据明确的公式格式要求启用规则','originalRequirements':text,'method':'local_explicit_parser'},'confidence':None})
 normalized=validate_items(items)
 if not normalized:warnings.append('未提取到明确可执行规则，请补充对象、参数和单位。')
 return {'items':normalized,'warnings':warnings,'conflicts':conflicts(normalized),'sourceMode':'local','liveVerified':False,'label':'本机明确规则解析（非AI调用）','originalText':text}
