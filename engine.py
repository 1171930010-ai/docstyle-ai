"""DocStyle 5: native styles, explicit rule states and package preservation."""
from __future__ import annotations
import base64
import copy
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from lxml import etree as E
import latex2mathml.converter
import mathml2omml
from equation_formats import unwrap_latex, inventory as equation_inventory, validate_format as validate_equation_format, apply_format as apply_equation_format, verify_format as verify_equation_format, normalized_math

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
      'm': 'http://schemas.openxmlformats.org/officeDocument/2006/math',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
W, M = NS['w'], NS['m']
P_ORDER = 'pStyle keepNext keepLines pageBreakBefore framePr widowControl numPr suppressLineNumbers pBdr shd tabs suppressAutoHyphens kinsoku wordWrap overflowPunct topLinePunct autoSpaceDE autoSpaceDN bidi adjustRightInd snapToGrid spacing ind contextualSpacing mirrorIndents suppressOverlap jc textDirection textAlignment textboxTightWrap outlineLvl divId cnfStyle rPr sectPr pPrChange'.split()
R_ORDER = 'rStyle rFonts b bCs i iCs caps smallCaps strike dstrike outline shadow emboss imprint noProof snapToGrid vanish webHidden color spacing w kern position sz szCs highlight u effect bdr shd fitText vertAlign rtl cs em lang eastAsianLayout specVanish oMath rPrChange'.split()
ORDERS = {'pPr': P_ORDER, 'rPr': R_ORDER,
          'tblPr': 'tblStyle tblpPr tblOverlap bidiVisual tblStyleRowBandSize tblStyleColBandSize tblW jc tblCellSpacing tblInd tblBorders shd tblLayout tblCellMar tblLook tblCaption tblDescription tblPrChange'.split(),
          'tcPr': 'cnfStyle tcW gridSpan hMerge vMerge tcBorders shd noWrap tcMar textDirection tcFitText vAlign hideMark cellIns cellDel cellMerge tcPrChange'.split(),
          'trPr': 'cnfStyle divId gridBefore gridAfter wBefore wAfter cantSplit trHeight tblHeader tblCellSpacing jc hidden ins del trPrChange'.split(),
          'sectPr': 'headerReference footerReference footnotePr endnotePr type pgSz pgMar paperSrc pgBorders lnNumType pgNumType cols formProt vAlign noEndnote titlePg textDirection bidi rtlGutter docGrid printerSettings sectPrChange'.split(),
          'tblBorders': 'top left bottom right insideH insideV'.split(),
          'tcBorders': 'top left bottom right insideH insideV tl2br tr2bl'.split(),
          'tcMar': 'top left bottom right'.split(),
          'tblCellMar': 'top left bottom right'.split()}
STYLE_NAMES = {'title': '论文标题', 'author': '作者信息', 'keywords': '关键词', 'body': '正文', 'abstract': '摘要', 'caption': '图表题注', 'note': '表注 / 资料来源', 'reference': '参考文献'}
STYLE_NAMES.update({f'heading{i}': f'{i} 级标题' for i in range(1, 10)})
STYLE_IDS = {role: 'DocStyle' + role[0].upper() + role[1:] for role in STYLE_NAMES}
RUN_FIELDS = {'font', 'latin', 'size', 'bold', 'italic', 'underline', 'color'}
PARAGRAPH_FIELDS = {'align', 'before', 'after', 'line', 'lineMode', 'left', 'right', 'indent', 'indentMode', 'indentUnit', 'keepNext', 'keepLines', 'pageBreak', 'widow'}

def q(name):
    p, n = name.split(':') if ':' in name else ('w', name)
    return '{' + NS[p] + '}' + n

def local(el):
    return E.QName(el).localname

def val(el, key='val', default=None):
    return el.get(q(key), default) if el is not None else default

def child(el, name):
    return el.find(q(name)) if el is not None else None

def put(parent, name, attrs=None):
    node = child(parent, name)
    if node is None:
        node = E.Element(q(name))
        order = ORDERS.get(local(parent), [])
        rank = order.index(name) if name in order else 999
        for i, sibling in enumerate(parent):
            sname = local(sibling)
            if sname in order and order.index(sname) > rank:
                parent.insert(i, node)
                break
        else:
            parent.append(node)
    for k, v in (attrs or {}).items():
        node.set(q(k), str(v))
    return node

def firstprop(parent, name):
    node = child(parent, name)
    if node is None:
        node = E.Element(q(name)); parent.insert(0, node)
    return node

def delete_attr(el, *names):
    for n in names:
        el.attrib.pop(q(n), None)

def parse(data):
    if b'<!DOCTYPE' in data.upper():
        raise ValueError('DOCX 不支持包含 DTD 的 XML')
    return E.fromstring(data, E.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False))

def serialize(root):
    return E.tostring(root, encoding='UTF-8', xml_declaration=True, standalone=True)

def package(data):
    if len(data) > 30 * 1024 * 1024:
        raise ValueError('单份文档请小于 30 MB')
    z = zipfile.ZipFile(io.BytesIO(data))
    infos = z.infolist()
    if len(infos) > 4000 or sum(x.file_size for x in infos) > 180 * 1024 * 1024:
        raise ValueError('DOCX 解压体积过大')
    if len(set(x.filename for x in infos)) != len(infos):
        raise ValueError('DOCX 包内存在重复路径')
    if any(x.flag_bits & 1 for x in infos):
        raise ValueError('请先在 Word 中另存为未加密的 DOCX')
    parts = {x.filename: z.read(x) for x in infos}
    if 'word/document.xml' not in parts:
        raise ValueError('文件缺少 Word 主文档')
    return parts, infos

def default_profile():
    base = dict(enabled=True, font='宋体', latin='Times New Roman', size=10.5,
                bold=None, italic=None, underline=None, color=None, align='both',
                before=0, after=0, lineMode='multiple', line=1.5,
                left=0, right=0, indentMode='firstLine', indent=0.74, indentUnit='cm',
                keepNext=False, keepLines=False, pageBreak=False, widow=True)
    styles = {'body': dict(base)}
    styles['title'] = dict(base, font='黑体', size=18, bold=True, align='center', indent=0, after=12, keepNext=True)
    for i in range(1, 10):
        styles[f'heading{i}'] = dict(base, font='黑体' if i < 3 else '宋体', size={1:14,2:12}.get(i,10.5),
                                    bold=True, align='left', indent=0, before=12 if i==1 else 6, after=6, line=1.25, keepNext=True, keepLines=True)
    for key in ['author', 'abstract', 'keywords', 'caption', 'note', 'reference']:
        styles[key] = dict(base)
    styles['author'].update(align='center', indent=0, after=6)
    styles['keywords'].update(indent=0)
    styles['caption'].update(font='楷体', align='center', bold=True, indent=0, before=6, after=6, line=1, keepNext=True)
    styles['note'].update(size=9, indent=0, line=1, after=3)
    styles['reference'].update(size=9, indentMode='hanging', indent=.74, line=1.25)
    return {'version':5, 'styles':styles,
            'page':dict(enabled=False, paper='A4', orientation='portrait', top=2.54, bottom=2.54, left=2.54, right=2.54, header=1.27, footer=1.27),
            'table':dict(enabled=False, borderMode='three', borderColor='17283D', borderSize=.75,
                         borders={k:'single' for k in ['top','bottom','left','right','insideH','insideV']},
                         headerRows=1, headerFill='EDF2FC', headerBold=True, font='宋体', latin='Times New Roman', size=9,
                         align='center', cellAlign='center', valign='center', width=100, layout='autofit',
                         paddingTop=3, paddingBottom=3, paddingLeft=5, paddingRight=5, rowHeight=0, rowRule='atLeast',
                         repeatHeader=True, preventSplit=True, columns='', before=0, after=0, line=1, cells={}),
            'equation':dict(enabled=False, align='center', before=6, after=6, scope='all', font='Cambria Math', size=12, bold=None, italic=None, color=None,
                            _fieldStates={k:'unspecified' for k in ['font','size','bold','italic','color','scope']})}

def number(v, lo, hi, label):
    try: n = float(v)
    except (ValueError, TypeError): raise ValueError(f'{label}请输入数字')
    if not lo <= n <= hi: raise ValueError(f'{label}应在 {lo}–{hi} 之间')
    return n

def validate_style(s):
    states=s.get('_fieldStates',{})
    if not isinstance(states,dict) or any(k not in RUN_FIELDS | PARAGRAPH_FIELDS | {'enabled'} or v not in ['set','default','preserve','clear','unspecified'] for k,v in states.items()):
        raise ValueError('字段状态无效')
    s={k:v for k,v in s.items() if states.get(k) not in ['preserve','clear','unspecified']}
    for k, lo, hi in [('size',1,200),('before',0,500),('after',0,500),('left',0,30),('right',0,30),('indent',0,30)]:
        if k in s: number(s[k],lo,hi,k)
    if 'line' in s: number(s['line'],.1,200,'行距')
    for k in ['font','latin']:
        if k in s and (not isinstance(s[k],str) or len(s[k]) > 100): raise ValueError('字体名称无效')
    if s.get('color') is not None and not re.fullmatch('[0-9A-Fa-f]{6}',s['color']): raise ValueError('颜色值无效')
    for k,choices in [('align',['left','right','center','both']),('lineMode',['multiple','exact','atLeast']),('indentMode',['firstLine','hanging','none']),('indentUnit',['cm','chars'])]:
        if k in s and s[k] not in choices: raise ValueError(f'不支持的设置：{k}')

def read_format(ppr=None,rpr=None):
    out = {}
    if rpr is not None:
        fonts=child(rpr,'rFonts')
        for attr,key in [('eastAsia','font'),('ascii','latin')]:
            if val(fonts,attr): out[key]=val(fonts,attr)
        sz=val(child(rpr,'sz'))
        if sz: out['size']=float(sz)/2
        for key,tag in [('bold','b'),('italic','i')]:
            el=child(rpr,tag)
            if el is not None: out[key]=val(el,default='1') not in ['0','false','off']
        u=child(rpr,'u')
        if u is not None: out['underline']=val(u,default='single')!='none'
        c=val(child(rpr,'color'))
        if c and c!='auto': out['color']=c
    if ppr is not None:
        align=val(child(ppr,'jc'))
        if align: out['align']=align
        sp=child(ppr,'spacing')
        if sp is not None:
            for k in ['before','after']:
                if val(sp,k): out[k]=float(val(sp,k))/20
            line=val(sp,'line')
            if line:
                rule=val(sp,'lineRule','auto'); out.update(lineMode='multiple' if rule=='auto' else rule,line=float(line)/(240 if rule=='auto' else 20))
        ind=child(ppr,'ind')
        if ind is not None:
            for key in ['left','right']:
                if val(ind,key): out[key]=float(val(ind,key))*2.54/1440
            for key in ['firstLine','hanging']:
                if val(ind,key+'Chars') is not None: out.update(indentMode=key,indent=float(val(ind,key+'Chars'))/100,indentUnit='chars')
                elif val(ind,key) is not None: out.update(indentMode=key,indent=float(val(ind,key))*2.54/1440,indentUnit='cm')
        for k,tag in [('keepNext','keepNext'),('keepLines','keepLines'),('pageBreak','pageBreakBefore'),('widow','widowControl')]:
            if child(ppr,tag) is not None: out[k]=val(child(ppr,tag),default='1') not in ['0','false','off']
    return out

def style_context(parts, styles_root=None):
    """Resolve paragraph and character inheritance without rewriting source styles."""
    sr=styles_root if styles_root is not None else (parse(parts['word/styles.xml']) if 'word/styles.xml' in parts else E.Element(q('styles'),nsmap={'w':W}))
    styles={val(s,'styleId'):s for s in sr.findall(q('style'))}
    dd=child(sr,'docDefaults')
    theme=parse(parts['word/theme/theme1.xml']) if 'word/theme/theme1.xml' in parts else None
    def resolved_format(pp=None,rp=None):
        fmt=read_format(pp,rp); fonts=child(rp,'rFonts')
        if val(child(rp,'color'))=='auto': fmt['color']='auto'
        if theme is not None and fonts is not None:
            for attr,key in [('eastAsia','font'),('ascii','latin')]:
                token=val(fonts,attr+'Theme')
                if token:
                    family='majorFont' if token.startswith('major') else 'minorFont'
                    scheme=theme.find('.//{'+NS['a']+'}'+family)
                    script='ea' if attr=='eastAsia' else 'latin'
                    face=scheme.find('{'+NS['a']+'}'+script) if scheme is not None else None
                    name=face.get('typeface') if face is not None else None
                    if not name and script=='ea' and scheme is not None:
                        lang=val(child(rp,'lang'),'eastAsia',default='zh-CN')
                        script_name='Jpan' if lang.startswith('ja') else 'Hang' if lang.startswith('ko') else 'Hant' if lang in ['zh-TW','zh-HK'] else 'Hans'
                        name=next((n.get('typeface') for n in scheme.findall('{'+NS['a']+'}font') if n.get('script')==script_name),None)
                    if name: fmt[key]=name
        return fmt
    defaults=resolved_format(dd.find('.//'+q('pPr')) if dd is not None else None,dd.find('.//'+q('rPr')) if dd is not None else None)
    # OOXML defaults for fields absent from both docDefaults and the style chain.
    defaults={**dict(size=11,bold=False,italic=False,underline=False,color='auto',align='left',before=0,after=0,line=1,lineMode='multiple',left=0,right=0,indent=0,indentMode='firstLine',indentUnit='cm',keepNext=False,keepLines=False,pageBreak=False,widow=True),**defaults}
    normal=next((k for k,s in styles.items() if val(s,'type')=='paragraph' and val(s,'default') in ['1','true']), 'Normal' if 'Normal' in styles else None)
    def inherited(key,seen=None):
        seen=set() if seen is None else seen
        if key in seen or key not in styles: return {}
        seen.add(key); s=styles[key]
        return {**inherited(val(child(s,'basedOn')),seen),**resolved_format(child(s,'pPr'),child(s,'rPr'))}
    def effective(p,r=None):
        pp=child(p,'pPr'); out={**defaults,**inherited(val(child(pp,'pStyle'),default=normal)),**resolved_format(pp,child(pp,'rPr'))}
        if r is not None:
            rp=child(r,'rPr')
            out.update(inherited(val(child(rp,'rStyle')))); out.update(resolved_format(None,rp))
        return out
    return sr,styles,normal,inherited,effective

def merged_style(base, override):
    out={**base,**override}
    out['_fieldStates']={**base.get('_fieldStates',{}),**override.get('_fieldStates',{})}
    for key in override:
        if key in RUN_FIELDS|PARAGRAPH_FIELDS and key not in override.get('_fieldStates',{}) and key in out['_fieldStates']:
            out['_fieldStates'][key]='set'
    return out

def active_fields(s):
    states=s.get('_fieldStates',{})
    return {k:v for k,v in s.items() if k not in ['_fieldStates','enabled'] and states.get(k) not in ['preserve','clear','unspecified']}

def remove_field(pp,rp,key):
    """Clear only the requested OOXML property, preserving neighboring attributes."""
    tags={'font':('rFonts',['eastAsia','eastAsiaTheme']), 'latin':('rFonts',['ascii','hAnsi','cs','asciiTheme','hAnsiTheme','csTheme','cstheme']),
          'before':('spacing',['before','beforeLines','beforeAutospacing']), 'after':('spacing',['after','afterLines','afterAutospacing']),
          'line':('spacing',['line','lineRule']), 'lineMode':('spacing',['line','lineRule']),
          'left':('ind',['left','leftChars','start','startChars']), 'right':('ind',['right','rightChars','end','endChars']),
          'indent':('ind',['firstLine','hanging','firstLineChars','hangingChars']), 'indentMode':('ind',['firstLine','hanging','firstLineChars','hangingChars']), 'indentUnit':('ind',['firstLine','hanging','firstLineChars','hangingChars'])}
    simple={'size':['sz','szCs'],'bold':['b','bCs'],'italic':['i','iCs'],'underline':['u'],'color':['color'],
            'align':['jc'],'keepNext':['keepNext'],'keepLines':['keepLines'],'pageBreak':['pageBreakBefore'],'widow':['widowControl']}
    parent=rp if key in RUN_FIELDS else pp
    if parent is None: return
    if key in tags:
        tag,attrs=tags[key]; el=child(parent,tag)
        if el is not None:
            delete_attr(el,*attrs)
            if not el.attrib and not len(el): parent.remove(el)
    else:
        for tag in simple.get(key,[]):
            for el in list(parent.findall(q(tag))): parent.remove(el)

def grouped_states(s):
    """Coupled values (mode/unit and magnitude) have one effective state."""
    out={k:('preserve' if v=='unspecified' else v) for k,v in s.get('_fieldStates',{}).items()}
    for group in [('line','lineMode'),('indent','indentMode','indentUnit')]:
        explicit=[out[k] for k in group if k in out and out[k] in ['preserve','clear']]
        if explicit:
            if len(set(explicit))>1: raise ValueError('关联字段状态冲突')
            for k in group: out[k]=explicit[0]
    return out

def native_style(sr, role, s, normal, sid=None, isolated=False):
    sid=sid or STYLE_IDS[role]
    node=next((n for n in sr.findall(q('style')) if val(n,'styleId')==sid),None)
    if node is None: node=E.SubElement(sr,q('style'))
    else:
        for n in list(node): node.remove(n)
        node.attrib.clear()
    node.set(q('type'),'paragraph'); node.set(q('customStyle'),'1'); node.set(q('styleId'),sid)
    put(node,'name',{'val':'DocStyle '+STYLE_NAMES[role]+('（局部）' if isolated else '')})
    based=STYLE_IDS[role] if isolated=='preserve' else normal if role=='body' or isolated else STYLE_IDS['body']
    if based: put(node,'basedOn',{'val':based})
    put(node,'next',{'val':STYLE_IDS['body']}); put(node,'qFormat')
    pseudo=E.Element(q('p')); rules={**s,'_fieldStates':grouped_states(s)}
    apply_paragraph(pseudo,active_fields(rules),role)
    pp=child(pseudo,'pPr')
    if pp is not None: node.append(pp)
    r=E.Element(q('r')); apply_run(r,active_fields(rules)); rp=child(r,'rPr')
    if rp is not None and len(rp): node.append(rp)
    return sid

def cleared_character_style(sr, source_styles, old_id, fields, sid):
    """Flatten a character style while retaining every unrelated run property."""
    chain=[]; seen=set(); key=old_id
    while key in source_styles and key not in seen:
        seen.add(key); node=source_styles[key]; chain.append(node); key=val(child(node,'basedOn'))
    rp=E.Element(q('rPr'))
    for style in reversed(chain):
        old=child(style,'rPr')
        for prop in old if old is not None else []:
            previous=child(rp,local(prop))
            if previous is not None and local(prop) in ['rFonts','lang']:
                previous.attrib.update(prop.attrib)
            else:
                if previous is not None: rp.remove(previous)
                rp.append(copy.deepcopy(prop))
    for field in fields: remove_field(None,rp,field)
    existing=next((s for s in sr.findall(q('style')) if val(s,'styleId')==sid),None)
    if existing is not None: sr.remove(existing)
    style=E.SubElement(sr,q('style'),{q('type'):'character',q('customStyle'):'1',q('styleId'):sid})
    put(style,'name',{'val':'DocStyle 局部字符格式 '+sid})
    if len(rp): style.append(rp)
    return sid

def text(el):
    return ''.join(el.xpath('.//w:t/text()',namespaces=NS))

def classify(p, idx, names):
    t=text(p).strip(); pp=child(p,'pPr'); sty=val(child(pp,'pStyle'),default=''); name=names.get(sty,sty)
    if p.xpath('ancestor::w:tc',namespaces=NS): return 'cell'
    if p.find('.//'+q('m:oMathPara')) is not None or (not t and p.find('.//'+q('m:oMath')) is not None): return 'equation'
    if not t: return 'empty'
    for role,sid in STYLE_IDS.items():
        if sty==sid or sty.startswith(sid+'__'): return role
    if re.match(r'^(表|图|Table|Figure|Fig\.)\s*\d+',t,re.I): return 'caption'
    if re.match(r'^(注|资料来源|数据来源|说明)\s*[：:]',t): return 'note'
    if re.match(r'^(关键词|关键字|Keywords|Key words)\s*[：:]',t,re.I): return 'keywords'
    if re.match(r'^(摘要|Abstract)\s*[：:]',t,re.I): return 'abstract'
    if re.match(r'^(作者|作者信息|Author[s]?)\s*[：:]',t,re.I): return 'author'
    if re.match(r'^(参考文献|References)\s*[:：]?$',t,re.I): return 'heading1'
    h=re.search(r'(?:heading|标题)\s*([1-9])',name,re.I)
    if h: return 'heading'+h[1]
    level=val(child(pp,'outlineLvl'))
    if level and level.isdigit() and int(level)<9: return 'heading'+str(int(level)+1)
    if name.lower() in ['title','标题']: return 'title'
    if len(t)<95:
        if re.match(r'^[一二三四五六七八九十]+[、．.]',t): return 'heading1'
        if re.match(r'^[（(][一二三四五六七八九十]+[）)]',t): return 'heading2'
        h=re.match(r'^(\d+(?:\.\d+){0,8})[.．、\s]\s*[^\d]',t)
        if h: return 'heading'+str(min(9,h[1].count('.')+1))
    if idx==0 and len(t)<75 and not re.search('[。？！!?]$',t): return 'title'
    return 'body'

def omml_latex(node):
    """Conservative reverse conversion. Unknown constructs stay read-only."""
    unsupported=[]
    def conv(n):
        name=local(n)
        if E.QName(n).namespace==W or name.endswith('Pr'): return ''
        def arg(k):
            e=n.find('{'+M+'}'+k); return conv(e) if e is not None else ''
        if name=='t':
            trans={'α':r'\alpha ','β':r'\beta ','γ':r'\gamma ','δ':r'\delta ','ε':r'\varepsilon ','ϵ':r'\epsilon ','μ':r'\mu ','λ':r'\lambda ','σ':r'\sigma ','π':r'\pi ','θ':r'\theta ','∞':r'\infty ','≤':r'\le ','≥':r'\ge ','≠':r'\ne ','×':r'\times ','∈':r'\in ','∂':r'\partial ','∑':r'\sum ','∫':r'\int '}
            return ''.join(trans.get(c, '\\'+c if c in '{}%#$&_\\' else c) for c in (n.text or ''))
        if name in ['oMath','oMathPara','e','num','den','sup','sub','deg','lim','fName','mr']: return ''.join(conv(x) for x in n)
        if name=='box' and n.find('{'+M+'}boxPr') is None: return arg('e')
        if name=='r':
            rp=n.find('{'+M+'}rPr'); t=''.join(conv(x) for x in n if local(x)=='t')
            if rp is not None and rp.find('{'+M+'}nor') is not None: return r'\text{'+t+'}'
            return t
        if name=='f': return r'\frac{'+arg('num')+'}{'+arg('den')+'}'
        if name=='sSup': return '{'+arg('e')+'}^{'+arg('sup')+'}'
        if name=='sSub': return '{'+arg('e')+'}_{'+arg('sub')+'}'
        if name=='sSubSup': return '{'+arg('e')+'}_{'+arg('sub')+'}^{'+arg('sup')+'}'
        if name=='rad': return r'\sqrt'+('['+arg('deg')+']' if arg('deg') else '')+'{'+arg('e')+'}'
        if name=='d':
            prop=n.find('{'+M+'}dPr')
            def dv(k,d):
                e=prop.find('{'+M+'}'+k) if prop is not None else None
                return e.get('{'+M+'}val',d) if e is not None else d
            left,right=dv('begChr','('),dv('endChr',')')
            delim=lambda s: '\\'+s if s in ['{','}'] else (s or '.')
            return r'\left'+delim(left)+' '.join(conv(e) for e in n if local(e)=='e')+r'\right'+delim(right)
        if name=='nary':
            p=n.find('{'+M+'}naryPr'); c=p.find('{'+M+'}chr') if p is not None else None
            op=(c.get('{'+M+'}val','∫') if c is not None else '∫')
            command={'∑':r'\sum','∫':r'\int','∏':r'\prod','⋃':r'\bigcup','⋂':r'\bigcap'}.get(op)
            if command is None: unsupported.append(name); command=op
            return command+('_{'+arg('sub')+'}' if arg('sub') else '')+('^{'+arg('sup')+'}' if arg('sup') else '')+' '+arg('e')
        if name=='m': return r'\begin{matrix}'+r'\\'.join(' & '.join(conv(e) for e in row if local(e)=='e') for row in n if local(row)=='mr')+r'\end{matrix}'
        if name=='eqArr': return r'\begin{aligned}'+r'\\'.join(conv(e) for e in n if local(e)=='e')+r'\end{aligned}'
        if name=='func': return arg('fName')+' '+arg('e')
        if name=='bar':
            pos=n.find('./{'+M+'}barPr/{'+M+'}pos')
            return (r'\underline{' if pos is not None and pos.get('{'+M+'}val')=='bot' else r'\overline{')+arg('e')+'}'
        if name=='acc':
            p=n.find('{'+M+'}accPr'); c=p.find('{'+M+'}chr') if p is not None else None
            mark=c.get('{'+M+'}val','̂') if c is not None else '̂'
            cmd={'̂':r'\hat','¯':r'\bar','̄':r'\bar','̃':r'\tilde','⃗':r'\vec','̇':r'\dot','̈':r'\ddot'}.get(mark)
            if cmd is None: unsupported.append('acc:'+mark); cmd=r'\hat'
            return cmd+'{'+arg('e')+'}'
        unsupported.append(name)
        return ''.join(conv(x) for x in n)
    latex=conv(node)
    return latex,list(dict.fromkeys(unsupported))

def formula(latex):
    if not isinstance(latex,str) or not latex.strip() or len(latex)>12000: raise ValueError('请输入有效公式，最长 12000 字符')
    latex,_=unwrap_latex(latex)
    if re.search(r'\\(?:href|url|html\w*|include\w*|input|write\w*|require)\b',latex): raise ValueError('公式含不支持的命令')
    try:
        mathml=latex2mathml.converter.convert(latex)
        if re.search(r'\\[A-Za-z]+', ''.join(parse(mathml.encode()).itertext())):
            raise ValueError('包含当前转换器不支持的命令')
        raw=mathml2omml.convert(mathml)
        root=parse(('<root xmlns:m="'+M+'" xmlns:w="'+W+'">'+raw+'</root>').encode())[0]
        if root.tag!=q('m:oMath'): raise ValueError('未生成原生数学对象')
        # CT_Rad requires the degree slot even for a square root. The converter
        # omits it for sqrt; strict readers otherwise show placeholder boxes.
        for rad in root.findall('.//'+q('m:rad')):
            degree=rad.find(q('m:deg'))
            if degree is None:
                degree=E.Element(q('m:deg')); rad.insert(0,degree)
            props=rad.find(q('m:radPr'))
            if props is None: props=E.Element(q('m:radPr')); rad.insert(0,props)
            hide=props.find(q('m:degHide'))
            if hide is None: hide=E.SubElement(props,q('m:degHide'))
            hide.set('{'+M+'}val','1' if not ''.join(degree.itertext()).strip() else '0')
        for r in root.findall('.//'+q('m:r')):
            wp=child(r,'rPr')
            if wp is None:
                wp=E.Element(q('rPr')); r.insert(1 if r.find(q('m:rPr')) is not None else 0,wp)
            put(wp,'rFonts',{'ascii':'Cambria Math','hAnsi':'Cambria Math','eastAsia':'Cambria Math'})
        return root,mathml
    except Exception as ex: raise ValueError('公式转换失败，请检查括号及 LaTeX 命令：'+str(ex)[:180])

def inspect_doc(data):
    parts,_=package(data); root=parse(parts['word/document.xml']); body=root.find(q('body'))
    if body is None: raise ValueError('缺少正文节点')
    styles={}; names={}; defaults={}
    if 'word/styles.xml' in parts:
        sr=parse(parts['word/styles.xml']); dd=child(sr,'docDefaults')
        defaults=read_format(dd.find('.//'+q('pPr')) if dd is not None else None,dd.find('.//'+q('rPr')) if dd is not None else None)
        for s in sr.findall(q('style')):
            key=val(s,'styleId'); styles[key]=s; names[key]=val(child(s,'name'),default=key)
    def inherited(key,seen=None):
        seen=set() if seen is None else seen
        if key in seen or key not in styles: return dict(defaults)
        seen.add(key); s=styles[key]; out=inherited(val(child(s,'basedOn')),seen)
        out.update(read_format(child(s,'pPr'),child(s,'rPr'))); return out
    eqnodes=root.findall('.//'+q('m:oMath')); equations=[]; eqids={n:f'e{i}' for i,n in enumerate(eqnodes)}
    pars=root.findall('.//'+q('p')); pids={p:f'p{i}' for i,p in enumerate(pars)}; paragraphs=[]; in_refs=False
    rels={}
    if 'word/_rels/document.xml.rels' in parts:
        for rel in parse(parts['word/_rels/document.xml.rels']):
            if rel.get('TargetMode')!='External': rels[rel.get('Id')]=rel.get('Target','')
    context=style_context(parts)
    for i,p in enumerate(pars):
        role=classify(p,i,names); t=text(p); pp=child(p,'pPr'); fmt=inherited(val(child(pp,'pStyle')))
        runs=p.xpath('.//w:r[not(ancestor::m:oMath)]',namespaces=NS)
        fmt=context[4](p,runs[0] if runs else None)
        sid=val(child(pp,'pStyle'),default='')
        managed=any(sid==k or sid.startswith(k+'__') for k in STYLE_IDS.values())
        if role=='body' and in_refs and not managed: role='reference'
        if re.match(r'^(参考文献|References)\s*[:：]?$',t.strip(),re.I): in_refs=True
        elif role.startswith('heading'): in_refs=False
        images=[]
        for blip in p.findall('.//{'+NS['a']+'}blip'):
            target=rels.get(blip.get(q('r:embed')),'')
            path='word/'+target
            if path in parts and len(parts[path])<3*1024*1024 and path.lower().endswith(('.png','.jpg','.jpeg','.gif')):
                mime='image/png' if path.lower().endswith('.png') else 'image/gif' if path.lower().endswith('.gif') else 'image/jpeg'
                images.append('data:'+mime+';base64,'+base64.b64encode(parts[path]).decode())
        peqs=[]
        for n in p.findall('.//'+q('m:oMath')):
            if n in eqids: peqs.append(eqids[n])
        segments=[]
        def walk_content(n):
            if n.tag==q('m:oMath'):
                segments.append({'kind':'equation','id':eqids[n]}); return
            if n.tag==q('p') and n is not p: return
            if n.tag==q('t'):
                run=n.getparent(); sf=inherited(val(child(child(run,'rPr'),'rStyle')))
                sf.update(read_format(None,child(run,'rPr')))
                # Only preserve explicitly resolved inline emphasis; paragraph fields come from fmt/profile.
                segments.append({'kind':'text','text':n.text or '', 'format':{k:v for k,v in sf.items() if k in ['bold','italic','underline','color']}}); return
            if n.tag==q('tab'): segments.append({'kind':'text','text':'\t','format':{}}); return
            if n.tag in [q('br'),q('cr')]: segments.append({'kind':'text','text':'\n','format':{}}); return
            if local(n).endswith('Pr'): return
            for c in n: walk_content(c)
        walk_content(p)
        paragraphs.append(dict(id=pids[p],text=t,role=role,format=fmt,segments=segments,equations=peqs,images=images,
                               style=names.get(val(child(pp,'pStyle')),''),styleId=val(child(pp,'pStyle')), editable=p.getparent() is body,
                               guessed=not bool(val(child(pp,'pStyle')) or val(child(pp,'outlineLvl')))))
    for i,n in enumerate(eqnodes):
        latex,unsupported=omml_latex(n); p=next((a for a in n.iterancestors() if a.tag==q('p')),None)
        in_textbox=bool(n.xpath('ancestor::w:txbxContent',namespaces=NS))
        equations.append(dict(id=f'e{i}',paragraph=pids.get(p),latex=latex,unsupported=unsupported,
                              display=n.getparent().tag==q('m:oMathPara'),kind='native',
                              runFormats=[read_format(None,child(r,'rPr')) for r in n.findall('.//'+q('m:r'))],
                              capabilities={'expression':not bool(unsupported) and not in_textbox,'innerFormat':not in_textbox,'paragraphLayout':not in_textbox and n.getparent().tag==q('m:oMathPara')}))
    other_equations,_=equation_inventory(root,pids)
    equations.extend(other_equations)
    tables=[]; ts=root.findall('.//'+q('tbl')); tids={t:f't{i}' for i,t in enumerate(ts)}
    for t in ts:
        rows=[]
        for ri,row in enumerate(t.findall(q('tr'))):
            cells=[]
            for ci,c in enumerate(row.findall(q('tc'))):
                pr=child(c,'tcPr'); merge=child(pr,'vMerge'); span=int(val(child(pr,'gridSpan'),default='1'))
                cells.append(dict(key=f'{ri}:{ci}',text=text(c),paragraphs=[pids[p] for p in c.findall(q('p'))],span=span,
                                  merge=val(merge,default='continue') if merge is not None else None,
                                  nested=[tids[n] for n in c.findall(q('tbl'))]))
            rows.append(cells)
        widths=[int(val(g,'w','0')) for g in t.findall('./'+q('tblGrid')+'/'+q('gridCol'))]
        tables.append(dict(id=tids[t],rows=rows,columns=len(widths),widths=[round(w*2.54/1440,2) for w in widths],nested=t.getparent() is not body))
    blocks=[]
    for el in body:
        if el in pids: blocks.append({'kind':'paragraph','id':pids[el]})
        elif el in tids: blocks.append({'kind':'table','id':tids[el]})
        elif local(el) not in ['sectPr']: blocks.append({'kind':'other','text':'内容控件或特殊对象：导出时保留'})
    counts={'paragraphs':len(pars),'tables':len(ts),'equations':len(eqnodes),'images':len([k for k in parts if k.startswith('word/media/')]),
            'sections':len(root.findall('.//'+q('sectPr'))),'fields':len(root.findall('.//'+q('fldChar'))),
            'revisions':len(root.findall('.//'+q('ins')))+len(root.findall('.//'+q('del')))}
    warnings=[]
    if counts['revisions']: warnings.append('含修订记录：本版保留修订结构，格式修改不会生成 Word 修订标记。')
    if root.find('.//'+q('sdt')) is not None: warnings.append('含内容控件；结构预览不展开所有控件，请在 Word 中复核。')
    if root.find('.//'+q('txbxContent')) is not None: warnings.append('文本框内文字、表格和公式保留原样，暂不支持自动格式修改；请在 Word 中复核。')
    if any(e['kind']=='mathtype_ole' for e in other_equations): warnings.append('检测到 MathType 或旧公式嵌入对象：保留原对象；独立公式可调整段落布局，内部格式需原编辑器。')
    elif any('embeddings/' in x for x in parts): warnings.append('含 OLE 嵌入对象：原样保留，无法仅凭嵌入文件判断是否为 MathType。')
    if 'word/footnotes.xml' in parts or 'word/endnotes.xml' in parts: warnings.append('脚注和尾注原样保留；“表注”样式只处理正文中的表注与资料来源。')
    if any(e['unsupported'] for e in equations if e['kind']=='native'): warnings.append('部分原生公式含未支持的结构：可保留与对齐，暂不提供公式内容编辑。')
    return dict(paragraphs=paragraphs,tables=tables,equations=equations,blocks=blocks,counts=counts,warnings=warnings)

def apply_run(r, s):
    rp=firstprop(r,'rPr')
    if 'font' in s or 'latin' in s:
        rf=put(rp,'rFonts')
        if 'font' in s: rf.set(q('eastAsia'),s['font']); delete_attr(rf,'eastAsiaTheme')
        if 'latin' in s:
            for a in ['ascii','hAnsi','cs']: rf.set(q(a),s['latin'])
            delete_attr(rf,'asciiTheme','hAnsiTheme','cstheme','csTheme')
    if 'size' in s:
        for tag in ['sz','szCs']: put(rp,tag,{'val':round(s['size']*2)})
    for key,tags in [('bold',['b','bCs']),('italic',['i','iCs'])]:
        if s.get(key) is not None:
            for tag in tags: put(rp,tag,{'val':1 if s[key] else 0})
    if s.get('underline') is not None: put(rp,'u',{'val':'single' if s['underline'] else 'none'})
    if s.get('color'):
        c=put(rp,'color',{'val':s['color']}); delete_attr(c,'themeColor','themeTint','themeShade')

def apply_paragraph(p,s,role=None,audit=None):
    if not s.get('enabled',True): return False
    requested_rules=dict(s)
    validate_style(s); states=grouped_states(s)
    if role in [None,'cell','equation'] and not (set(active_fields({**s,'_fieldStates':states})) & (RUN_FIELDS|PARAGRAPH_FIELDS)) and not any(v=='clear' for v in states.values()): return False
    pp=firstprop(p,'pPr')
    for key,state in states.items():
        if state=='clear':
            remove_field(pp,child(pp,'rPr'),key)
            for r in p.xpath('.//w:r[not(ancestor::m:oMath) and not(ancestor::w:txbxContent)]',namespaces=NS):
                remove_field(None,child(r,'rPr'),key)
    s=active_fields({**s,'_fieldStates':states})
    if role and role.startswith('heading'): put(pp,'outlineLvl',{'val':int(role[7:])-1})
    elif role and role not in ['cell','equation']: put(pp,'outlineLvl',{'val':9})
    if 'align' in s: put(pp,'jc',{'val':s['align']})
    sp=put(pp,'spacing') if any(k in s for k in ['before','after','line']) else child(pp,'spacing')
    for k in ['before','after']:
        if k in s:
            sp.set(q(k),str(round(s[k]*20))); delete_attr(sp,k+'Lines',k+'Autospacing')
    if 'line' in s:
        mode=s.get('lineMode','multiple'); sp.set(q('line'),str(round(s['line']*(240 if mode=='multiple' else 20)))); sp.set(q('lineRule'),'auto' if mode=='multiple' else mode)
        put(pp,'snapToGrid',{'val':0})
    if any(k in s for k in ['left','right','indent']):
        ind=put(pp,'ind')
        for k in ['left','right']:
            if k in s:
                ind.set(q(k),str(round(s[k]*1440/2.54))); delete_attr(ind,k+'Chars','start' if k=='left' else 'end','startChars' if k=='left' else 'endChars')
        if 'indent' in s:
            delete_attr(ind,'firstLine','hanging','firstLineChars','hangingChars')
            mode=s.get('indentMode','firstLine'); tag='hanging' if mode=='hanging' else 'firstLine'
            unit=s.get('indentUnit','cm'); ind.set(q(tag+('Chars' if unit=='chars' else '')),str(round((0 if mode=='none' else s['indent'])*(100 if unit=='chars' else 1440/2.54))))
    for k,tag in [('keepNext','keepNext'),('keepLines','keepLines'),('pageBreak','pageBreakBefore'),('widow','widowControl')]:
        if k in s: put(pp,tag,{'val':1 if s[k] else 0})
    for r in p.xpath('.//w:r[not(ancestor::m:oMath) and not(ancestor::w:txbxContent)]',namespaces=NS):
        if r.find(q('t')) is not None or r.find(q('delText')) is not None: apply_run(r,s)
    if audit is not None: audit[p]=merged_style(audit.get(p,{}),requested_rules)
    return True

def apply_cell(c,s,audit=None):
    cp=firstprop(c,'tcPr')
    if s.get('_fieldStates',{}).get('valign')=='clear':
        for n in list(cp.findall(q('vAlign'))): cp.remove(n)
    if s.get('_fieldStates',{}).get('fill')=='clear':
        for n in list(cp.findall(q('shd'))): cp.remove(n)
    if s.get('fill'):
        if not re.fullmatch('[0-9A-Fa-f]{6}',s['fill']): raise ValueError('单元格颜色无效')
        sh=put(cp,'shd',{'val':'clear','color':'auto','fill':s['fill']}); delete_attr(sh,'themeFill','themeFillTint','themeFillShade')
    if s.get('valign') in ['top','center','bottom']: put(cp,'vAlign',{'val':s['valign']})
    for p in c.findall(q('p')):
        rules={**s,'_fieldStates':{k:v for k,v in s.get('_fieldStates',{}).items() if k in RUN_FIELDS|PARAGRAPH_FIELDS|{'enabled'}}}
        apply_paragraph(p,rules,'cell',audit)
    if 'borders' in s:
        bs=put(cp,'tcBorders')
        for edge,kind in s['borders'].items():
            if edge in ['top','bottom','left','right'] and kind in ['nil','single','double','dashed','dotted']:
                put(bs,edge,{'val':kind,'sz':round(number(s.get('borderSize',.75),.25,6,'边框粗细')*8),'color':s.get('borderColor','000000')})

def format_table(t,s,audit=None,styles_root=None):
    if not s.get('enabled'): return 0
    states=s.get('_fieldStates',{})
    if not isinstance(states,dict) or any(v not in ['set','default','preserve','clear','unspecified'] for v in states.values()): raise ValueError('表格字段状态无效')
    # Every unspecified/preserved field is ignored, including values retained in
    # the UI profile. Enabling a group does not confirm its other fields.
    candidate_profile=any(v=='unspecified' for v in states.values())
    active={k:v for k,v in s.items() if k not in ['enabled','_fieldStates','cells'] and states.get(k) not in ['preserve','clear','unspecified'] and (not candidate_profile or states.get(k) in ['set','default'])}
    clears={k for k,v in states.items() if v=='clear'}
    supported_clear=RUN_FIELDS|{'before','after','line','lineMode','headerBold','headerFill','cellAlign','valign','align','rowHeight','repeatHeader','preventSplit','borderSize','borderColor'}
    unsupported=clears-supported_clear-{'enabled'}
    if unsupported: raise ValueError('表格布局字段的清除尚不支持，已停止导出：'+', '.join(sorted(unsupported)))
    rules={**active,'_fieldStates':{k:v for k,v in states.items() if k in RUN_FIELDS|PARAGRAPH_FIELDS|{'enabled'}}}
    validate_style(rules)
    if not active and not clears: return 0
    tp=firstprop(t,'tblPr'); rows=t.findall(q('tr'))
    if 'align' in active:
        if active['align'] not in ['left','center','right']: raise ValueError('表格对齐无效')
        put(tp,'jc',{'val':active['align']})
    elif 'align' in clears:
        for n in list(tp.findall(q('jc'))): tp.remove(n)
    if 'width' in active: put(tp,'tblW',{'type':'pct','w':round(number(active['width'],1,100,'表宽')*50)})
    if 'layout' in active:
        if active['layout'] not in ['fixed','autofit']: raise ValueError('表格布局无效')
        put(tp,'tblLayout',{'type':active['layout']})
    padding={edge.lower():round(number(active['padding'+edge],0,100,'单元格边距')*20) for edge in ['Top','Bottom','Left','Right'] if 'padding'+edge in active}
    if padding:
        cm=put(tp,'tblCellMar')
        for edge,width in padding.items(): put(cm,edge,{'w':width,'type':'dxa'})
    existing_headers=sum(child(child(row,'trPr'),'tblHeader') is not None and val(child(child(row,'trPr'),'tblHeader'),default='1') not in ['0','false','off'] for row in rows)
    headers=int(number(active['headerRows'],0,len(rows),'表头行数')) if 'headerRows' in active else existing_headers
    border=active.get('borderMode'); mode_set=border not in [None,'preserve']
    if border not in [None,'preserve','three','grid','none','custom']: raise ValueError('表格边框模式无效')
    # Legacy preserve-border selection also suppresses the old populated defaults.
    if border=='preserve':
        for key in ['borderColor','borderSize']:
            if states.get(key) not in ['set','default']: active.pop(key,None)
    if 'borderSize' in active: number(active['borderSize'],.25,6,'边框粗细')
    if 'borderColor' in active and not re.fullmatch('[0-9A-Fa-f]{6}',active['borderColor']): raise ValueError('边框颜色无效')
    inherited_borders=None
    if styles_root is not None:
        source_styles={val(n,'styleId'):n for n in styles_root.findall(q('style'))}; key=val(child(tp,'tblStyle')); chain=[]; seen=set()
        while key in source_styles and key not in seen:
            seen.add(key); node=source_styles[key]; chain.append(node); key=val(child(node,'basedOn'))
        inherited_borders=E.Element(q('tblBorders'))
        for node in reversed(chain):
            source=child(child(node,'tblPr'),'tblBorders')
            for edge in source if source is not None else []:
                old=child(inherited_borders,local(edge))
                if old is not None: inherited_borders.remove(old)
                inherited_borders.append(copy.deepcopy(edge))
    def border_edge(container,edge,kind=None,fallback=None):
        current=child(container,edge)
        if current is None:
            source=child(fallback,edge) if fallback is not None else None
            if source is None and inherited_borders is not None: source=child(inherited_borders,edge)
            if source is None and kind is None: return
            current=copy.deepcopy(source) if source is not None else E.Element(q(edge)); container.append(current)
        if kind is not None:
            if kind not in ['single','nil','double','dashed','dotted']: raise ValueError('边框线型无效')
            current.set(q('val'),kind)
        if 'borderSize' in active: current.set(q('sz'),str(round(active['borderSize']*8)))
        elif 'borderSize' in clears: delete_attr(current,'sz')
        if 'borderColor' in active:
            current.set(q('color'),active['borderColor']); delete_attr(current,'themeColor','themeTint','themeShade')
        elif 'borderColor' in clears: delete_attr(current,'color','themeColor','themeTint','themeShade')
    border_change=mode_set or any(k in active or k in clears for k in ['borderColor','borderSize'])
    bs=child(tp,'tblBorders')
    if border_change:
        bs=put(tp,'tblBorders')
        for edge in ['top','bottom','left','right','insideH','insideV']:
            kind=None
            if mode_set:
                kind='single' if border=='grid' or border=='three' and edge in ['top','bottom'] else 'nil'
                if border=='custom': kind=active.get('borders',{}).get(edge,'nil')
            border_edge(bs,edge,kind)
    widths=[]
    if 'columns' in active and str(active['columns']).strip():
        widths=[round(number(x.strip(),.1,50,'列宽')*1440/2.54) for x in str(active['columns']).split(',')]
        grid=child(t,'tblGrid'); cols=list(grid) if grid is not None else []
        if len(widths)!=len(cols): raise ValueError(f'列宽应填写 {len(cols)} 个数值（厘米）')
        for c,w in zip(cols,widths): c.set(q('w'),str(w))
        put(tp,'tblW',{'type':'dxa','w':sum(widths)}); put(tp,'tblLayout',{'type':'fixed'})
    count=0
    for ri,row in enumerate(rows):
        row_fields={'repeatHeader':'tblHeader','preventSplit':'cantSplit'}
        for field,tag in row_fields.items():
            if field in active: put(firstprop(row,'trPr'),tag,{'val':int(bool(active[field]) and (ri<headers if field=='repeatHeader' else True))})
            elif field in clears:
                rp=child(row,'trPr')
                if rp is not None:
                    for n in list(rp.findall(q(tag))): rp.remove(n)
        if 'rowHeight' in active or 'rowHeight' in clears:
            rp=firstprop(row,'trPr'); height=number(active.get('rowHeight',0),0,500,'行高')
            if height:
                attrs={'val':round(height*20)}
                if 'rowRule' in active:
                    if active['rowRule'] not in ['exact','atLeast']: raise ValueError('行高规则无效')
                    attrs['hRule']=active['rowRule']
                put(rp,'trHeight',attrs)
            else:
                for n in list(rp.findall(q('trHeight'))): rp.remove(n)
        elif 'rowRule' in active:
            height=child(child(row,'trPr'),'trHeight')
            if height is not None: height.set(q('hRule'),active['rowRule'])
        column=int(val(child(child(row,'trPr'),'gridBefore'),default='0'))
        cells=row.findall(q('tc'))
        for ci,c in enumerate(cells):
            cp=firstprop(c,'tcPr'); span=int(val(child(cp,'gridSpan'),default='1'))
            if border_change and (mode_set or child(cp,'tcBorders') is not None):
                cb=put(cp,'tcBorders')
                for edge in ['top','bottom','left','right']:
                    kind=None
                    if mode_set:
                        kind='single' if border=='grid' else 'nil'
                        if border=='three' and ((edge=='top' and ri==0) or (edge=='bottom' and (ri==headers-1 or ri==len(rows)-1))): kind='single'
                        if border=='custom':
                            outer=(edge=='top' and ri==0) or (edge=='bottom' and ri==len(rows)-1) or (edge=='left' and ci==0) or (edge=='right' and ci==len(cells)-1)
                            kind=active.get('borders',{}).get(edge if outer else ('insideH' if edge in ['top','bottom'] else 'insideV'),'nil')
                    border_edge(cb,edge,kind,bs)
            if padding:
                mar=put(cp,'tcMar')
                for edge,width in padding.items(): put(mar,edge,{'w':width,'type':'dxa'})
            cellstyle={k:active[k] for k in ['font','latin','size','before','after','line','lineMode','bold','italic','underline','color'] if k in active}
            cellstates={k:'clear' for k in clears if k in RUN_FIELDS|{'before','after','line','lineMode'}}
            if 'line' in active and 'lineMode' not in active and not candidate_profile: cellstyle['lineMode']='multiple'
            for src,dst in [('cellAlign','align'),('valign','valign')]:
                if src in active: cellstyle[dst]=active[src]
                elif src in clears: cellstates[dst]='clear'
            if ri<headers:
                if 'headerBold' in active: cellstyle['bold']=active['headerBold']
                elif 'headerBold' in clears: cellstates['bold']='clear'
                if 'headerFill' in active: cellstyle['fill']=active['headerFill']
                elif 'headerFill' in clears: cellstates['fill']='clear'
            if cellstyle or cellstates:
                cellstyle['_fieldStates']=cellstates; apply_cell(c,cellstyle,audit)
            if widths: put(cp,'tcW',{'type':'dxa','w':sum(widths[column:column+span])})
            column+=span; count+=1
    return count

def page_format(root,s):
    if not s.get('enabled'): return 0
    states=s.get('_fieldStates',{})
    valid={'enabled','paper','orientation','top','bottom','left','right','header','footer'}
    if not isinstance(states,dict) or any(k not in valid or v not in ['set','default','preserve','clear','unspecified'] for k,v in states.items()): raise ValueError('页面字段状态无效')
    for key in ['paper','orientation']:
        if states.get(key)=='clear': raise ValueError('页面纸张/方向的清除尚不支持，已停止导出：'+key)
    active=active_fields(s)
    if not active and not any(v=='clear' for v in states.values()): return 0
    margins={k:round(number(active[k],0,12,'页边距')*1440/2.54) for k in ['top','bottom','left','right','header','footer'] if k in active}
    sections=root.findall('.//'+q('sectPr'))
    if not sections:
        sections=[E.SubElement(root.find(q('body')),q('sectPr'))]
    for sec in sections:
        old=child(sec,'pgSz'); olddim=(int(val(old,'w','11906')),int(val(old,'h','16838')))
        orientation=active.get('orientation',val(old,'orient','portrait'))
        if orientation not in ['portrait','landscape']: raise ValueError('纸张方向无效')
        if 'paper' in active:
            dim={'A4':(11906,16838),'Letter':(12240,15840),'A3':(16838,23811)}.get(active['paper'])
            if dim is None: raise ValueError('纸张类型无效')
            if orientation=='landscape': dim=dim[::-1]
        else: dim=tuple(sorted(olddim,reverse=orientation=='landscape'))
        if 'paper' in active or 'orientation' in active: put(sec,'pgSz',{'w':dim[0],'h':dim[1],'orient':orientation})
        mar=child(sec,'pgMar')
        combined={k:margins.get(k,int(val(mar,k,'1440'))) for k in ['left','right','top','bottom']}
        if combined['left']+combined['right']>=dim[0]-720 or combined['top']+combined['bottom']>=dim[1]-720: raise ValueError('页边距过大，可用版心不足')
        if margins: mar=put(sec,'pgMar',margins)
        if mar is not None:
            for key,state in states.items():
                if state=='clear' and key in ['top','bottom','left','right','header','footer']: delete_attr(mar,key)
    return len(sections)

def normalized_text(root):
    return root.xpath('//w:t/text()',namespaces=NS)

def transform(data,payload):
    parts,infos=package(data); root=parse(parts['word/document.xml']); original=parse(parts['word/document.xml']); content_reference=copy.deepcopy(original)
    profile=payload.get('profile') or default_profile(); roles=payload.get('roles',{}); overrides=payload.get('overrides',{})
    model=inspect_doc(data); pars=root.findall('.//'+q('p')); original_pars=original.findall('.//'+q('p')); pmap={f'p{i}':p for i,p in enumerate(pars)}
    if set(roles)|set(overrides)-set(pmap):
        if any(k not in pmap for k in list(roles)+list(overrides)): raise ValueError('段落选择已过期，请重新导入')
    counts={'paragraphs':0,'tables':0,'cells':0,'sections':0,'equationsEdited':0,'equationsInserted':0,'equationParagraphs':0,'equationsFormatted':0,'mathRunsFormatted':0,'latexConverted':0}
    expected=[]; affected=set(); style_mappings=[]; requested_audit={}
    sr,source_styles,normal,_,source_effective=style_context(parts)
    source_formats={p:(source_effective(p),[(r,source_effective(p,r)) for r in p.xpath('.//w:r[w:t or w:delText][not(ancestor::m:oMath) and not(ancestor::w:txbxContent)]',namespaces=NS)]) for p in pars}
    conversion_pids={e['paragraph'] for e in model['equations'] if e['kind']=='latex_text' and payload.get('equations',{}).get(e['id'],{}).get('convertLatex') is True}
    native_enabled=any(merged_style(profile.get('styles',{}).get(roles.get(e['id'],e['role']),{}),overrides.get(e['id'],{})).get('enabled',True) for e in model['paragraphs'] if roles.get(e['id'],e['role']) in STYLE_NAMES)
    if native_enabled:
        for role in STYLE_NAMES:
            native_style(sr,role,profile.get('styles',{}).get(role,{}),normal)
    for entry in model['paragraphs']:
        pid=entry['id']; p=pmap[pid]; role=roles.get(pid,entry['role'])
        if p.xpath('ancestor::w:txbxContent',namespaces=NS) or pid in conversion_pids: continue
        if role in ['cell','empty','equation']: continue
        if role not in STYLE_NAMES: raise ValueError('段落类型无效')
        s=merged_style(profile.get('styles',{}).get(role,{}),overrides.get(pid,{}))
        if not s.get('enabled',True): continue
        validate_style(s); states=grouped_states(s); s['_fieldStates']=states
        # Local clears inherit from the original default paragraph style, so the
        # role template cannot silently reintroduce the cleared property.
        sid=STYLE_IDS[role]
        if any(v in ['clear','preserve'] for v in states.values()):
            isolation='clear' if 'clear' in states.values() else 'preserve'
            local_rules=s if isolation=='clear' else {'_fieldStates':states}
            sid=native_style(sr,role,local_rules,normal,sid+'__'+pid,isolated=isolation)
        pp=firstprop(p,'pPr'); put(pp,'pStyle',{'val':sid})
        original_pp,original_runs=source_formats[p]
        preserve={k for k,v in states.items() if v=='preserve'}
        preserve.update(k for k in RUN_FIELDS if k in s and s[k] is None and states.get(k)!='clear')
        frozen={k:v for k,v in original_pp.items() if k in preserve & PARAGRAPH_FIELDS}
        if frozen: apply_paragraph(p,frozen)
        for ri,(r,fmt) in enumerate(original_runs):
            rp=child(r,'rPr')
            # A character style must not reintroduce cleared character fields.
            if any(k in RUN_FIELDS and v=='clear' for k,v in states.items()) and child(rp,'rStyle') is not None:
                cs=cleared_character_style(sr,source_styles,val(child(rp,'rStyle')),{k for k,v in states.items() if k in RUN_FIELDS and v=='clear'},'DocStyleChar__'+pid+'_'+str(ri))
                put(rp,'rStyle',{'val':cs})
                apply_run(r,{k:v for k,v in fmt.items() if k in RUN_FIELDS and states.get(k)!='clear'})
            apply_run(r,{k:v for k,v in fmt.items() if k in preserve & RUN_FIELDS})
        if apply_paragraph(p,s,role,requested_audit):
            # Global confirmed rules belong to the native role style. Remove
            # old direct overrides, including overrides supplied by character
            # styles, so later Word/WPS style edits can propagate normally.
            base=profile.get('styles',{}).get(role,{})
            global_rules=active_fields({**base,'_fieldStates':grouped_states(base)})
            local_keys=set(overrides.get(pid,{}))|set(overrides.get(pid,{}).get('_fieldStates',{}))
            for group in [{'indent','indentMode','indentUnit'},{'line','lineMode'}]:
                if local_keys & group: local_keys.update(group)
            # A bounded server retry may retain confirmed direct formatting.
            # It still uses native role mappings and every content/readback
            # guard below; the flag changes only this inheritance cleanup.
            inherited_keys=set() if payload.get('_forceDirectFormatting') is True else {k for k,v in global_rules.items() if k in RUN_FIELDS|PARAGRAPH_FIELDS and v is not None and k not in local_keys and states.get(k) not in ['preserve','clear']}
            for key in inherited_keys:
                remove_field(pp,child(pp,'rPr'),key)
            if 'line' in inherited_keys:
                for n in list(pp.findall(q('snapToGrid'))): pp.remove(n)
            for ri,(r,_) in enumerate(original_runs):
                rp=child(r,'rPr'); character=child(rp,'rStyle')
                if character is not None and inherited_keys & RUN_FIELDS:
                    current_styles={val(n,'styleId'):n for n in sr.findall(q('style'))}
                    cs=cleared_character_style(sr,current_styles,val(character),inherited_keys & RUN_FIELDS,'DocStyleChar__'+pid+'_'+str(ri))
                    put(rp,'rStyle',{'val':cs})
                for key in inherited_keys & RUN_FIELDS: remove_field(None,rp,key)
            counts['paragraphs']+=1; expected.append((pid,role,s)); affected.add(p)
            style_mappings.append(dict(paragraph=pid,role=role,fromStyle=val(child(child(original_pars[int(pid[1:])],'pPr'),'pStyle')),toStyle=sid))
    tables=root.findall('.//'+q('tbl'))
    for i,t in enumerate(tables):
        if t.xpath('ancestor::w:txbxContent',namespaces=NS):
            if payload.get('tables',{}).get(f't{i}'): raise ValueError('文本框内表格暂不支持格式修改，已停止导出')
            continue
        ts={**profile['table'],**payload.get('tables',{}).get(f't{i}',{})}
        c=format_table(t,ts,requested_audit,sr)
        if c:
            counts['tables']+=1; counts['cells']+=c; affected.update(t.findall('.//'+q('p')))
        for key,cs in ts.get('cells',{}).items():
            ri,ci=map(int,key.split(':')); rows=t.findall(q('tr'))
            if ri<0 or ri>=len(rows) or ci<0 or ci>=len(rows[ri].findall(q('tc'))): raise ValueError('单元格选择已过期')
            cell=rows[ri].findall(q('tc'))[ci]; apply_cell(cell,cs,requested_audit); affected.update(cell.findall(q('p')))
    counts['sections']=page_format(root,profile['page'])
    eqnodes=root.findall('.//'+q('m:oMath')); emap={f'e{i}':n for i,n in enumerate(eqnodes)}
    edits=payload.get('equations',{})
    if not isinstance(edits,dict): raise ValueError('公式设置无效')
    other_model,other_nodes=equation_inventory(root,{p:f'p{i}' for i,p in enumerate(pars)})
    all_eq={e['id']:e for e in model['equations']};expression_edits=set();conversions=[];converted_nodes={};formatted={};expected_math={};expected_math_values={}
    for eid,edit in edits.items():
        if eid not in all_eq or not isinstance(edit,dict): raise ValueError('公式选择已过期')
        entry=all_eq[eid]
        if entry['kind']=='mathtype_ole':
            if 'latex' in edit or edit.get('convertLatex') or edit.get('format'): raise ValueError('嵌入式公式内容和内部格式需用原公式编辑器修改')
        elif entry['kind']=='latex_text':
            if edit.get('convertLatex') is True:
                p=other_nodes[eid]; replacement,_=formula(entry['latex'])
                for n in list(p):
                    if n.tag!=q('pPr'):p.remove(n)
                if entry['display']:
                    op=E.SubElement(p,q('m:oMathPara'));op.append(replacement)
                else:p.append(replacement)
                converted_nodes[eid]=replacement
                reference_p=content_reference.findall('.//'+q('p'))[int(entry['paragraph'][1:])]
                for n in list(reference_p):
                    if n.tag!=q('pPr'):reference_p.remove(n)
                conversions.append({'id':eid,'sourceText':entry['sourceText'],'latex':entry['latex']});counts['latexConverted']+=1
            elif 'latex' in edit: raise ValueError('LaTeX 文本需先明确确认转换')
        else:
            if emap[eid].xpath('ancestor::w:txbxContent',namespaces=NS): raise ValueError('文本框内公式暂不支持表达式编辑，已停止导出')
            if 'latex' in edit:
                if entry['unsupported']:raise ValueError('该原生公式包含不支持的结构，不能替换表达式')
                replacement,_=formula(edit['latex']); n=emap[eid]; n.getparent().replace(n,replacement);emap[eid]=replacement;expression_edits.add(eid);counts['equationsEdited']+=1
    eqstyle=profile.get('equation',{})
    if eqstyle.get('enabled'):
        eqstates=eqstyle.get('_fieldStates',{})
        if not isinstance(eqstates,dict) or any(k not in ['enabled','align','before','after','font','size','bold','italic','color','scope'] or v not in ['set','default','preserve','clear','unspecified'] for k,v in eqstates.items()): raise ValueError('公式布局字段状态无效')
        eqrules={k:v for k,v in eqstyle.items() if k in ['align','before','after']}
        eqrules['_fieldStates']={k:v for k,v in eqstates.items() if k in ['align','before','after']}
        eqactive=active_fields(eqstyle)
        for entry in model['paragraphs']:
            if entry['role']=='equation' or any(x['paragraph']==entry['id'] and ((x['kind']=='mathtype_ole' and x['display']) or (x['id'] in converted_nodes and x['display'])) for x in other_model):
                p=pmap[entry['id']]
                if p.xpath('ancestor::w:txbxContent',namespaces=NS): continue
                did_apply=apply_paragraph(p,eqrules,'equation',requested_audit)
                if did_apply: affected.add(p)
                for op in p.findall(q('m:oMathPara')):
                    mp=op.find(q('m:oMathParaPr'))
                    if eqstates.get('align')=='clear' and mp is not None:
                        for n in list(mp.findall(q('m:jc'))): mp.remove(n)
                    if 'align' in eqactive:
                        if mp is None: mp=E.Element(q('m:oMathParaPr')); op.insert(0,mp)
                        jc=mp.find(q('m:jc'))
                        if jc is None: jc=E.SubElement(mp,q('m:jc'))
                        jc.set('{'+M+'}val',{'both':'center'}.get(eqactive['align'],eqactive['align']))
                if did_apply: counts['equationParagraphs']+=1
    # Local standalone paragraph settings override global settings and never change object internals.
    layout_seen=set()
    for eid,edit in edits.items():
        if 'layout' not in edit:continue
        entry=all_eq[eid]
        if not entry['display'] or entry['kind']=='latex_text' and eid not in converted_nodes:raise ValueError('仅独立公式可设置段落布局')
        local_layout=edit['layout']
        if not isinstance(local_layout,dict) or set(local_layout)-{'align','before','after','_fieldStates'}:raise ValueError('公式局部段落设置无效')
        p=pmap[entry['paragraph']]
        if p in layout_seen:raise ValueError('同一段落包含多个公式，段落局部设置冲突')
        if p.xpath('ancestor::w:txbxContent',namespaces=NS):raise ValueError('文本框内公式段落暂不支持修改')
        layout_seen.add(p)
        if apply_paragraph(p,local_layout,'equation',requested_audit):affected.add(p);counts['equationParagraphs']+=1
        active=active_fields(local_layout)
        for op in p.findall(q('m:oMathPara')):
            mp=op.find(q('m:oMathParaPr'))
            if local_layout.get('_fieldStates',{}).get('align')=='clear' and mp is not None:
                for n in list(mp.findall(q('m:jc'))):mp.remove(n)
            if 'align' in active:
                if mp is None:mp=E.Element(q('m:oMathParaPr'));op.insert(0,mp)
                jc=mp.find(q('m:jc'))
                if jc is None:jc=E.SubElement(mp,q('m:jc'))
                jc.set('{'+M+'}val',{'both':'center'}.get(active['align'],active['align']))
    scope=eqstyle.get('scope','all')
    if scope not in ['all','display','inline']:raise ValueError('公式格式适用范围无效')
    math_fields=['font','size','bold','italic','color']
    global_format={k:eqstyle[k] for k in math_fields if k in eqstyle}
    global_format['_fieldStates']={k:v for k,v in eqstyle.get('_fieldStates',{}).items() if k in math_fields}
    for eid,node in {**emap,**converted_nodes}.items():
        entry=all_eq[eid]
        if node.xpath('ancestor::w:txbxContent',namespaces=NS):
            if edits.get(eid,{}).get('format'):raise ValueError('文本框内公式暂不支持格式修改')
            continue
        use_global=eqstyle.get('enabled') and (scope=='all' or (scope=='display')==bool(entry['display']))
        base=global_format if use_global else {'_fieldStates':{k:'unspecified' for k in math_fields}}
        local_format=edits.get(eid,{}).get('format',{})
        combined=merged_style(base,local_format)
        fields=validate_equation_format(combined)
        if fields:
            before=copy.deepcopy(node);n=apply_equation_format(node,combined,put)
            if not n:raise ValueError('该公式没有可设置格式的数学文字，请在 Word 中检查')
            if normalized_math(before,fields)!=normalized_math(node,fields):raise ValueError('公式格式调整影响了表达式或非目标属性')
            formatted[eid]=list(fields);expected_math[eid]=E.tostring(node,method='c14n')
            expected_math_values[eid]=fields
            counts['equationsFormatted']+=1;counts['mathRunsFormatted']+=n
    additions=payload.get('insertions',[]); anchors={}; inserted=[]
    for insertion in additions:
        inserted_identifier=None
        math,_=formula(insertion['latex']); p=E.Element(q('p')); op=E.SubElement(p,q('m:oMathPara')); op.append(math)
        if eqstyle.get('enabled') and scope in ['all','display']:
            fields=validate_equation_format(global_format)
            if fields:
                original_math=copy.deepcopy(math);n=apply_equation_format(math,global_format,put)
                if normalized_math(original_math,fields)!=normalized_math(math,fields):raise ValueError('新增公式格式调整影响了表达式')
                identifier=str(insertion.get('id') or ('new'+str(len(inserted))))
                inserted_identifier=identifier
                formatted[identifier]=list(fields);expected_math[identifier]=E.tostring(math,method='c14n');converted_nodes[identifier]=math
                expected_math_values[identifier]=fields
                counts['equationsFormatted']+=1;counts['mathRunsFormatted']+=n
        apply_paragraph(p,dict(align=eqstyle.get('align','center'),before=eqstyle.get('before',6),after=eqstyle.get('after',6)),'equation',requested_audit)
        mp=E.Element(q('m:oMathParaPr')); op.insert(0,mp); jc=E.SubElement(mp,q('m:jc')); jc.set('{'+M+'}val',eqstyle.get('align','center'))
        anchorid=insertion.get('after'); anchor=anchors.get(anchorid,pmap.get(anchorid))
        body=root.find(q('body'))
        if anchor is not None:
            if anchor.getparent() is not body: raise ValueError('新增公式请选择正文中的段落，不能直接插入表格内')
            anchor.addnext(p); anchors[anchorid]=p
        else:
            sec=body.find(q('sectPr')); body.insert(body.index(sec) if sec is not None else len(body),p)
        if inserted_identifier is not None:expected_math[inserted_identifier]=E.tostring(math,method='c14n')
        inserted.append(p); affected.add(p); counts['equationsInserted']+=1
    # Existing ordinary text must match exactly; equations use m:t and have separate edit accounting.
    if normalized_text(root)!=normalized_text(content_reference): raise ValueError('原文文字发生意外变化，已停止导出')
    for old,new in zip(original.findall('.//'+q('tbl')),root.findall('.//'+q('tbl'))):
        sig=lambda t:[(local(n),sorted(n.attrib.items())) for n in t.iter() if local(n) in ['gridSpan','vMerge','hMerge']]
        if sig(old)!=sig(new): raise ValueError('合并单元格结构发生意外变化')
    for eid,n in emap.items():
        if eid not in expression_edits and eid not in formatted:
            # n remains the original in-memory node; compare content and properties to the original package.
            if E.tostring(n,method='c14n')!=E.tostring(original.findall('.//'+q('m:oMath'))[int(eid[1:])],method='c14n'): raise ValueError('未编辑公式发生意外变化')
    def protected_signature(doc):
        out=[]
        for node in doc.iter():
            if node.tag in [q(n) for n in ['fldChar','instrText','bookmarkStart','bookmarkEnd','drawing','pict','object','delText']]:
                out.append(E.tostring(node,method='c14n'))
            elif node.tag in [q(n) for n in ['ins','del','hyperlink','fldSimple']]:
                out.append((node.tag,sorted(node.attrib.items())))
        return out
    if protected_signature(root)!=protected_signature(original): raise ValueError('图片、引用域、书签或修订结构发生意外变化')
    changed=serialize(root); output=io.BytesIO(); replacements={'word/document.xml':changed}
    if native_enabled: replacements['word/styles.xml']=serialize(sr)
    # Unusual DOCX packages may lack a styles part; register the new part explicitly.
    if native_enabled and 'word/styles.xml' not in parts:
        relns='http://schemas.openxmlformats.org/package/2006/relationships'
        path='word/_rels/document.xml.rels'; rr=parse(parts[path]) if path in parts else E.Element('{'+relns+'}Relationships',nsmap={None:relns})
        ids={n.get('Id') for n in rr}; n=1
        while 'rIdDocStyle'+str(n) in ids: n+=1
        E.SubElement(rr,'{'+relns+'}Relationship',Id='rIdDocStyle'+str(n),Type=NS['r']+'/styles',Target='styles.xml')
        replacements[path]=serialize(rr)
        ctns='http://schemas.openxmlformats.org/package/2006/content-types'; ct=parse(parts['[Content_Types].xml'])
        if not any(n.get('PartName')=='/word/styles.xml' for n in ct): E.SubElement(ct,'{'+ctns+'}Override',PartName='/word/styles.xml',ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml')
        replacements['[Content_Types].xml']=serialize(ct)
    allowed_parts=[k for k,v in replacements.items() if v!=parts.get(k)]
    # Snapshot every affected run before serialization, then resolve the exported
    # package independently. This also covers cell overrides and equation paragraphs.
    before_effective=style_context(parts,sr)[4]
    audit_expected={p:(before_effective(p),[before_effective(p,r) for r in p.xpath('.//w:r[w:t or w:delText][not(ancestor::m:oMath) and not(ancestor::w:txbxContent)]',namespaces=NS)]) for p in affected}
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for info in infos: z.writestr(info,replacements.get(info.filename,parts[info.filename]))
        for path,value in replacements.items():
            if path not in parts: z.writestr(path,value)
    result=output.getvalue(); after,_=package(result); afterroot=parse(after['word/document.xml'])
    if normalized_text(afterroot)!=normalized_text(content_reference): raise ValueError('导出读回后原文文字不一致，已停止导出')
    if protected_signature(afterroot)!=protected_signature(original): raise ValueError('导出读回后图片、引用域、书签或修订结构不一致，已停止导出')
    after_tables=afterroot.findall('.//'+q('tbl'))
    if len(after_tables)!=len(tables): raise ValueError('导出读回后表格数量不一致')
    for old,new in zip(original.findall('.//'+q('tbl')),after_tables):
        if sig(old)!=sig(new): raise ValueError('导出读回后合并单元格结构不一致')
    for expected_table,new in zip(tables,after_tables):
        if E.tostring(expected_table,method='c14n')!=E.tostring(new,method='c14n'): raise ValueError('导出读回后表格内容或格式不一致')
    for tag in ['sectPr','m:oMathParaPr']:
        if [E.tostring(n,method='c14n') for n in root.findall('.//'+q(tag))]!=[E.tostring(n,method='c14n') for n in afterroot.findall('.//'+q(tag))]:
            raise ValueError('导出读回后页面或公式布局不一致')
    math_positions={n:i for i,n in enumerate(root.findall('.//'+q('m:oMath')))}; after_math=afterroot.findall('.//'+q('m:oMath'))
    for eid,n in {**emap,**converted_nodes}.items():
        if eid in formatted and E.tostring(after_math[math_positions[n]],method='c14n')!=expected_math[eid]:
            raise ValueError('导出读回后公式格式不一致')
        if eid in formatted and not verify_equation_format(after_math[math_positions[n]],expected_math_values[eid]):
            raise ValueError('导出读回后数学文字格式未达到所选值')
        if eid in emap and eid not in expression_edits and eid not in formatted and E.tostring(after_math[math_positions[n]],method='c14n')!=E.tostring(original.findall('.//'+q('m:oMath'))[int(eid[1:])],method='c14n'):
            raise ValueError('导出读回后未编辑公式不一致')
    unchanged=all(v==after.get(k) for k,v in parts.items() if k not in allowed_parts) and set(after)==set(parts)|set(replacements)
    if not unchanged: raise ValueError('DOCX 附件部件核验失败')
    # Read back serialized values, independent of UI status.
    style_errors=[]
    afterpars=afterroot.findall('.//'+q('p'))
    original_positions={p:i for i,p in enumerate(root.findall('.//'+q('p')))}; after_effective=style_context(after)[4]; runs_checked=0
    def same(a,b):
        return abs(a-b)<.06 if isinstance(a,(int,float)) and isinstance(b,(int,float)) else a==b
    mappings_by_id={m['paragraph']:m for m in style_mappings}
    for pid,role,s in expected:
        p=afterpars[original_positions[pmap[pid]]]; pp=child(p,'pPr'); runs=p.xpath('.//w:r[w:t or w:delText][not(ancestor::m:oMath) and not(ancestor::w:txbxContent)]',namespaces=NS)
        fmt=read_format(pp,child(runs[0],'rPr') if runs else None)
        for key in RUN_FIELDS | PARAGRAPH_FIELDS:
            if key in s and s[key] is not None and s.get('_fieldStates',{}).get(key) not in ['clear','preserve','unspecified']:
                formats=[after_effective(p,r) for r in runs] if key in RUN_FIELDS else [after_effective(p)]
                target=s[key]
                if key=='indentMode' and target=='none': target='firstLine'
                if key=='indent' and s.get('indentMode')=='none': target=0
                for ri,f in enumerate(formats):
                    if not same(f.get(key),target): style_errors.append(f'{pid} run{ri} {key}')
        if val(child(pp,'outlineLvl'))!=str(int(role[7:])-1 if role.startswith('heading') else 9): style_errors.append(f'{pid} outlineLvl')
        mapping=mappings_by_id[pid]
        if val(child(pp,'pStyle'))!=mapping['toStyle']: style_errors.append(f'{pid} pStyle')
        old=pmap[pid]; oldpf,oldruns=source_formats[old]
        preserved={k for k,v in s.get('_fieldStates',{}).items() if v in ['preserve','unspecified']}
        preserved.update(k for k in RUN_FIELDS if k in s and s[k] is None and s.get('_fieldStates',{}).get(k)!='clear')
        for key in preserved & PARAGRAPH_FIELDS:
            if not same(after_effective(p).get(key),oldpf.get(key)): style_errors.append(f'{pid} preserve {key}')
        for ri,(r,(_,oldfmt)) in enumerate(zip(runs,oldruns)):
            for key in preserved & RUN_FIELDS:
                if not same(after_effective(p,r).get(key),oldfmt.get(key)): style_errors.append(f'{pid} preserve run{ri} {key}')
    # Requested properties for table cells, local cell overrides and equations
    # are checked against their requested values on every text run as well.
    for old,s in requested_audit.items():
        p=afterpars[original_positions[old]]; runs=p.xpath('.//w:r[w:t or w:delText][not(ancestor::m:oMath) and not(ancestor::w:txbxContent)]',namespaces=NS)
        states=grouped_states(s)
        for key in RUN_FIELDS|PARAGRAPH_FIELDS:
            if key not in s or s[key] is None or states.get(key) in ['preserve','clear']: continue
            formats=[after_effective(p,r) for r in runs] if key in RUN_FIELDS else [after_effective(p)]
            target=s[key]
            if key=='indentMode' and target=='none': target='firstLine'
            if key=='indent' and s.get('indentMode')=='none': target=0
            if any(not same(f.get(key),target) for f in formats): style_errors.append(f'p{original_positions[old]} requested {key}')
    for old,(pf,rf) in audit_expected.items():
        p=afterpars[original_positions[old]]; runs=p.xpath('.//w:r[w:t or w:delText][not(ancestor::m:oMath) and not(ancestor::w:txbxContent)]',namespaces=NS)
        if not all(same(after_effective(p).get(k),v) for k,v in pf.items()): style_errors.append(f'p{original_positions[old]} serialized paragraph')
        if len(runs)!=len(rf): style_errors.append('文字 run 数量')
        for ri,(r,target) in enumerate(zip(runs,rf)):
            runs_checked+=1; f=after_effective(p,r)
            if not all(same(f.get(k),v) for k,v in target.items()): style_errors.append(f'p{original_positions[old]} serialized run{ri}')
    checks=[dict(name='原有正文文字',status='pass' if normalized_text(afterroot)==normalized_text(content_reference) else 'fail',detail=f'逐个文字节点对比；明确确认转换 {len(conversions)} 段 LaTeX 原文'),
            dict(name='段落格式写回',status='pass' if not style_errors else 'fail',detail=f"已读回核对 {len(affected)} 个受影响段落及全部 {runs_checked} 个文字 run；含角色、样式映射和大纲级别" if not style_errors else '不一致：'+', '.join(style_errors[:10])),
            dict(name='附件与引用部件',status='pass' if unchanged else 'fail',detail=f'{len([k for k in parts if k not in allowed_parts])} 个非允许修改部件逐字节一致；允许修改：'+', '.join(allowed_parts)),
            dict(name='表格合并结构',status='pass',detail=f'{len(tables)} 个表格的跨列、跨行合并标记保持一致'),
            dict(name='原生公式',status='pass',detail=f"保留表达式 {len(eqnodes)-len(expression_edits)} 个；明确编辑 {len(expression_edits)} 个；格式化 {len(formatted)} 个；确认转换 {len(conversions)} 段 LaTeX"),
            dict(name='Word / WPS 最终分页',status='pending',detail='结构预览不能替代最终分页；导出后在 Word / WPS 中复核')]
    if style_errors: raise ValueError('段落格式写回核验失败：'+', '.join(style_errors[:6]))
    warnings=model['warnings']+['页眉页脚、脚注尾注、已有编号域和引用域保持原样。','图片、内容控件及复杂浮动对象的最终位置请在 Word / WPS 中检查。']
    if any('clear' in s.get('_fieldStates',{}).values() for _,_,s in expected):
        warnings.append('清除字段通过局部原生样式重新继承原默认段落样式；继承结果可能与其他已设定的角色样式不同。')
    report=dict(product='DocStyle AI 5.0',createdAt=datetime.now(timezone.utc).isoformat(),sourceSHA256=hashlib.sha256(data).hexdigest(),
                resultSHA256=hashlib.sha256(result).hexdigest(),counts=counts,checks=checks,warnings=warnings,settings=payload,
                equationEdits=[dict(id=k,latex=edits[k]['latex']) for k in expression_edits],equationFormatting=formatted,latexConversions=conversions,allowedChangedParts=allowed_parts,
                styleMappings=style_mappings,paragraphMap={pid:'p'+str(original_positions[p]) for pid,p in pmap.items()},
                tableMap={f't{i}':f't{i}' for i in range(len(tables))},equationMap={eid:'e'+str(math_positions[n]) for eid,n in {**emap,**converted_nodes}.items()},validation=dict(affectedParagraphs=len(affected),textRunsChecked=runs_checked))
    return result,report
