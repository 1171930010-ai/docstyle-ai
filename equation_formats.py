"""Conservative math inventory and formatting for OOXML document bodies."""
import copy
import re
from lxml import etree as E
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
M='http://schemas.openxmlformats.org/officeDocument/2006/math'
NS={'w':W,'m':M}
def tag(ns,name): return '{'+ns+'}'+name

def unwrap_latex(value):
    s=value.strip()
    for left,right in [('$$','$$'),('\\[','\\]'),('\\(','\\)'),('$','$')]:
        if s.startswith(left) and s.endswith(right) and len(s)>len(left)+len(right):
            return s[len(left):-len(right)].strip(), left in ('$$','\\[')
    return s,None

def standalone_latex(p):
    if p.xpath('ancestor::w:txbxContent',namespaces=NS): return None
    children=[n for n in p if n.tag!=tag(W,'pPr')]
    if not children or any(n.tag!=tag(W,'r') for n in children): return None
    if any(n.tag not in (tag(W,'rPr'),tag(W,'t')) for run in children for n in run): return None
    original=''.join((n.text or '') for run in children for n in run if n.tag==tag(W,'t'))
    expression,display=unwrap_latex(original)
    if display is None or not expression: return None
    return {'sourceText':original,'latex':expression,'display':display}

def inventory(root,pids):
    results=[];nodes={}
    for obj in root.findall('.//'+tag(W,'object')):
        ole=next((n for n in obj.iter() if E.QName(n).localname=='OLEObject'),None)
        if ole is None: continue
        prog=ole.get('ProgID','')
        if not re.search(r'Equation|MathType|DSMT',prog,re.I): continue
        p=next((a for a in obj.iterancestors() if a.tag==tag(W,'p')),None)
        if p is None: continue
        text=''.join(p.xpath('.//w:t/text()',namespaces=NS)).strip()
        standalone=not text or bool(re.fullmatch(r'[(（]\s*[\w.\-]+\s*[)）]',text))
        identifier='o'+str(sum(x['kind']=='mathtype_ole' for x in results))
        results.append({'id':identifier,'kind':'mathtype_ole','paragraph':pids.get(p),'latex':'','sourceLabel':prog,
                        'display':standalone,'unsupported':['embedded_object'],
                        'capabilities':{'expression':False,'innerFormat':False,'paragraphLayout':standalone}})
        nodes[identifier]=obj
    for p in pids:
        found=standalone_latex(p)
        if found is None: continue
        identifier='l'+str(sum(x['kind']=='latex_text' for x in results))
        results.append({'id':identifier,'kind':'latex_text','paragraph':pids[p],**found,'unsupported':[],
                        'capabilities':{'expression':True,'innerFormat':False,'paragraphLayout':found['display']}})
        nodes[identifier]=p
    return results,nodes

def validate_format(s):
    if not isinstance(s,dict): raise ValueError('公式格式设置无效')
    allowed={'font','size','bold','italic','color'}; states=s.get('_fieldStates',{})
    if not isinstance(states,dict) or any(k not in allowed or v not in ('set','preserve','unspecified','clear','default') for k,v in states.items()): raise ValueError('公式文字格式字段状态无效')
    if any(states.get(k)=='clear' for k in allowed): raise ValueError('公式内部格式暂不支持清除，请选择保留或指定具体值')
    out={k:v for k,v in s.items() if k in allowed and states.get(k) not in ('preserve','unspecified','clear') and v is not None}
    if 'font' in out and (not isinstance(out['font'],str) or not out['font'].strip() or len(out['font'])>100 or re.search(r'[\x00-\x1f]',out['font'])): raise ValueError('公式字体名称无效')
    if 'size' in out and (isinstance(out['size'],bool) or not isinstance(out['size'],(int,float)) or not 1<=out['size']<=200): raise ValueError('公式字号应在 1–200 磅之间')
    if 'size' in out and abs(out['size']*2-round(out['size']*2))>1e-9:raise ValueError('Word 公式字号需以 0.5 磅为步长')
    for k in ('bold','italic'):
        if k in out and not isinstance(out[k],bool): raise ValueError('公式粗斜体设置无效')
    if 'color' in out and (not isinstance(out['color'],str) or not re.fullmatch('[0-9a-fA-F]{6}',out['color'])): raise ValueError('公式颜色须为六位 HEX')
    return out

def apply_format(node,settings,put):
    values=validate_format(settings)
    if not values: return 0
    runs=node.findall('.//'+tag(M,'r'))
    for run in runs:
        wp=run.find(tag(W,'rPr'))
        if wp is None:
            wp=E.Element(tag(W,'rPr')); mr=run.find(tag(M,'rPr'));run.insert(1 if mr is not None else 0,wp)
        if 'font' in values:
            rf=put(wp,'rFonts')
            for a in ('ascii','hAnsi','eastAsia','cs'):rf.set(tag(W,a),values['font'])
            for a in ('asciiTheme','hAnsiTheme','eastAsiaTheme','csTheme','cstheme'):rf.attrib.pop(tag(W,a),None)
        if 'size' in values:
            for prop in ('sz','szCs'):put(wp,prop,{'val':round(values['size']*2)})
        if 'color' in values:
            c=put(wp,'color',{'val':values['color'].upper()})
            for a in ('themeColor','themeTint','themeShade'):c.attrib.pop(tag(W,a),None)
        if 'bold' in values or 'italic' in values:
            mp=run.find(tag(M,'rPr'))
            if mp is None: mp=E.Element(tag(M,'rPr'));run.insert(0,mp)
            sty=mp.find(tag(M,'sty')); style=sty.get(tag(M,'val'),'i') if sty is not None else 'i'
            bold=values.get('bold',style in ('b','bi'));italic=values.get('italic',style in ('i','bi'))
            if sty is None:sty=E.SubElement(mp,tag(M,'sty'))
            sty.set(tag(M,'val'),'bi' if bold and italic else 'b' if bold else 'i' if italic else 'p')
            for key,prop in [('bold','b'),('italic','i')]:
                if key in values:
                    for name in (prop,prop+'Cs'):put(wp,name,{'val':1 if values[key] else 0})
    return len(runs)

def verify_format(node,values):
    for run in node.findall('.//'+tag(M,'r')):
        wp=run.find(tag(W,'rPr'))
        if wp is None:return False
        if 'font' in values:
            rf=wp.find(tag(W,'rFonts'))
            if rf is None or any(rf.get(tag(W,a))!=values['font'] for a in ('ascii','hAnsi','eastAsia','cs')):return False
        if 'size' in values:
            if any(wp.find(tag(W,k)) is None or wp.find(tag(W,k)).get(tag(W,'val'))!=str(round(values['size']*2)) for k in ('sz','szCs')):return False
        if 'color' in values:
            c=wp.find(tag(W,'color'))
            if c is None or c.get(tag(W,'val'))!=values['color'].upper():return False
        for key,prop in [('bold','b'),('italic','i')]:
            if key in values:
                for name in (prop,prop+'Cs'):
                    v=wp.find(tag(W,name))
                    if v is None or v.get(tag(W,'val'))!=str(int(values[key])):return False
                mp=run.find(tag(M,'rPr'));sty=mp.find(tag(M,'sty')) if mp is not None else None
                style=sty.get(tag(M,'val')) if sty is not None else None
                actual=style in (('b','bi') if key=='bold' else ('i','bi'))
                if actual!=values[key]:return False
    return True

def normalized_math(node,fields):
    n=copy.deepcopy(node)
    props={'font':('rFonts',),'size':('sz','szCs'),'color':('color',),'bold':('b','bCs'),'italic':('i','iCs')}
    for run in n.findall('.//'+tag(M,'r')):
        wp=run.find(tag(W,'rPr'))
        if wp is not None:
            for field in fields:
                for name in props.get(field,()):
                    for x in wp.findall(tag(W,name)): wp.remove(x)
            if len(wp)==0 and not wp.attrib:run.remove(wp)
        mp=run.find(tag(M,'rPr'))
        if mp is not None and ('bold' in fields or 'italic' in fields):
            for x in mp.findall(tag(M,'sty')):mp.remove(x)
            if len(mp)==0 and not mp.attrib:run.remove(mp)
    return E.tostring(n,method='c14n')
