# coding: utf-8
"""Optional real LibreOffice pagination. Never claims Word/WPS compatibility."""
import os,shutil,subprocess,tempfile,threading
from pathlib import Path
from xml.sax.saxutils import escape
from engine import package
from pdf_reference import analyze_pdf
LOCK=threading.Semaphore(1)
LIMIT=30*1024*1024
SUBSTITUTIONS={'宋体':'Arial Unicode MS','SimSun':'Arial Unicode MS','黑体':'Heiti SC','SimHei':'Heiti SC','楷体':'Arial Unicode MS','KaiTi':'Arial Unicode MS','Cambria Math':'STIX Two Math'}
def renderer_path():
 path=shutil.which('soffice') or shutil.which('libreoffice')
 if path:return path
 for p in [Path('/Applications/LibreOffice.app/Contents/MacOS/soffice'),Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override/soffice']:
  if p.is_file():return str(p)
 return None

def status():
 return {'available':bool(renderer_path()),'renderer':'LibreOffice','previewMode':'libreoffice_reference_pagination','WordWpsVerified':False,'message':'此为本机LibreOffice真实分页参考，字体可能替代；Word/WPS最终分页仍需实测'}

def font_config(directory,renderer):
 if not Path('/System/Library/Fonts').exists():return None,{}
 # The bundled runtime uses Fontconfig instead of macOS CoreText. Explicit aliases
 # are disclosed in the result and do not change the exported DOCX font names.
 if 'codex-runtimes' not in renderer:return None,{}
 native=Path(renderer).resolve().parents[2]/'native/libreoffice-headless/libreoffice/LibreOfficeDev.app/Contents/Resources'
 dirs=[Path('/System/Library/Fonts'),Path('/System/Library/Fonts/Supplemental'),Path('/Library/Fonts'),Path.home()/'Library/Fonts',native/'fonts/truetype']
 contents='<?xml version="1.0"?><fontconfig>'+''.join('<dir>'+escape(str(p))+'</dir>' for p in dirs if p.exists())
 contents+='<include ignore_missing="yes">'+escape(str(native/'fontconfig/conf.d'))+'</include><cachedir>'+escape(str(directory/'font-cache'))+'</cachedir>'
 contents+=''.join('<alias><family>'+escape(k)+'</family><prefer><family>'+escape(v)+'</family></prefer></alias>' for k,v in SUBSTITUTIONS.items())+'</fontconfig>'
 f=directory/'fontconfig.xml';f.write_text(contents);return str(f),SUBSTITUTIONS.copy()

def render_output(data):
 if not data or len(data)>LIMIT:raise ValueError('预览DOCX超出30MB限制')
 try:package(data)
 except Exception:raise ValueError('预览文件不是有效DOCX') from None
 renderer=renderer_path()
 if not renderer:return {**status(),'status':'unavailable','warnings':['未检测到LibreOffice；可以导出DOCX后在Word/WPS查看分页。']},None
 if not LOCK.acquire(blocking=False):raise ValueError('本机分页渲染正在运行，请稍后重试')
 try:
  with tempfile.TemporaryDirectory(prefix='docstyle-render-') as temp:
   d=Path(temp);src=d/'document.docx';src.write_bytes(data);out=d/'pdf';out.mkdir();profile=d/'profile';env=os.environ.copy();config,aliases=font_config(d,renderer)
   if config:env['FONTCONFIG_FILE']=config
   command=[renderer,'-env:UserInstallation='+profile.as_uri(),'--headless','--convert-to','pdf','--outdir',str(out),str(src)]
   try:res=subprocess.run(command,capture_output=True,text=True,timeout=55,env=env)
   except subprocess.TimeoutExpired:raise ValueError('分页渲染超过55秒，已停止；请使用Word/WPS查看') from None
   target=out/'document.pdf'
   if res.returncode or not target.is_file():raise ValueError('LibreOffice未生成可读取PDF；请在Word/WPS复核，不能视为分页通过')
   pdf=target.read_bytes()
   if len(pdf)>25*1024*1024:raise ValueError('渲染PDF超过25MB限制')
   analysis=analyze_pdf(pdf,'本机分页参考.pdf',{'purpose':'output_preview'})
   if analysis['status']=='failed' or not analysis['pages']:raise ValueError('渲染PDF无法读取，不能显示为分页成功')
   warnings=['这是LibreOffice生成的真实分页参考；未验证Word/WPS兼容性。','字体替代或公式渲染可能影响版面，请检查缺字、重叠和分页。']
   if aliases:warnings.append('为本机渲染配置了明确字体替代：'+', '.join(k+'→'+v for k,v in aliases.items())+'；DOCX未修改这些字体名称。')
   return {**status(),'status':'rendered','pages':[{'number':p['number'],'width':p['width'],'height':p['height']} for p in analysis['pages']],'pageCount':len(analysis['pages']),'fontSubstitutions':aliases,'visualReview':'pending','warnings':warnings},pdf
 finally:LOCK.release()
