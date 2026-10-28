# coding: utf-8
"""Cancellable batch tasks retain successful results and retry failures only."""
import base64,copy,io,json,re,threading,uuid,zipfile
from datetime import datetime,timezone
class TaskManager:
 def __init__(self,execute,name):self.execute=execute;self.name=name;self.jobs={};self.lock=threading.RLock()
 def start(self,documents,completed=None,previous_id=None,attempts=None):
  if not isinstance(documents,list) or not 1<=len(documents)<=100:raise ValueError('请选择1–100份文档')
  with self.lock:
   active=sum(x['status'] in ['queued','running','cancelling'] for x in self.jobs.values())
   if active>=2:raise ValueError('最多同时运行2个批量任务')
   job={'id':uuid.uuid4().hex,'status':'queued','cancel':False,'createdAt':datetime.now(timezone.utc).isoformat(),'previousId':previous_id,'items':copy.deepcopy(completed or [])+[{'id':x.get('id'),'name':self.name(x.get('id')),'status':'queued','settings':copy.deepcopy(x),'attempts':(attempts or {}).get(x.get('id'),0)} for x in documents]};self.jobs[job['id']]=job
  threading.Thread(target=self._run,args=(job['id'],),daemon=True).start();return {'id':job['id']}
 def _run(self,identifier):
  job=self.jobs[identifier]
  with self.lock:job['status']='running'
  for item in job['items']:
   if item['status']=='completed':continue
   with self.lock:
    if job['cancel']:item['status']='cancelled';continue
    item['status']='running';item['attempts']+=1
   try:
    result,report=self.execute(item['settings'])
    with self.lock:item.update(status='completed',result=base64.b64encode(result).decode(),report=report)
   except Exception as e:
    with self.lock:item.update(status='failed',error=str(e)[:250])
  with self.lock:job['status']='cancelled' if job['cancel'] else 'completed_with_errors' if any(x['status']=='failed' for x in job['items']) else 'completed'
 def snapshot(self,identifier):
  with self.lock:
   job=self.jobs.get(identifier)
   if not job:raise ValueError('批量任务不存在或服务已重启')
   items=[{k:copy.deepcopy(v) for k,v in x.items() if k!='settings'} for x in job['items']]
   done=sum(x['status'] in ['completed','failed','cancelled'] for x in items)
   return {'id':job['id'],'status':job['status'],'previousId':job.get('previousId'),'items':items,'progress':{'done':done,'total':len(items),'success':sum(x['status']=='completed' for x in items),'failed':sum(x['status']=='failed' for x in items)}}
 def cancel(self,identifier):
  with self.lock:
   job=self.jobs.get(identifier)
   if not job:raise ValueError('批量任务不存在')
   if job['status'] in ['queued','running','cancelling']:job['cancel']=True;job['status']='cancelling'
  return self.snapshot(identifier)
 def retry(self,identifier,replacements=None):
  with self.lock:
   job=self.jobs.get(identifier)
   if not job:raise ValueError('批量任务不存在')
   if job['status'] in ['queued','running','cancelling']:raise ValueError('请等待任务结束后重试')
   docs=[x['settings'] for x in job['items'] if x['status'] in ['failed','cancelled']]
   completed=[x for x in job['items'] if x['status']=='completed'];attempts={x['id']:x['attempts'] for x in job['items']}
  if not docs:raise ValueError('没有可重试的失败或取消项')
  if replacements is not None:
   if not isinstance(replacements,list):raise ValueError('重试设置应为列表')
   failed_ids={x['id'] for x in docs};updated={x.get('id'):x for x in replacements if isinstance(x,dict) and x.get('id') in failed_ids}
   docs=[copy.deepcopy(updated.get(x['id'],x)) for x in docs]
  return self.start(docs,completed,identifier,attempts)
 def restore(self,snapshot,documents,profile):
  if not isinstance(snapshot,dict) or not isinstance(snapshot.get('items'),list) or len(snapshot['items'])>100:raise ValueError('保存的批量摘要无效')
  by_id={x['id']:x for x in documents};items=[]
  for row in snapshot['items']:
   if not isinstance(row,dict) or row.get('id') not in by_id:continue
   d=by_id[row['id']];settings={k:copy.deepcopy(d.get(k,{})) for k in ['roles','overrides','tables','equations']};settings.update(id=d['id'],profile=copy.deepcopy(profile),locks=copy.deepcopy(d.get('aiLocks',{})),insertions=copy.deepcopy(d.get('insertions',[])))
   item={'id':d['id'],'name':d.get('name',row.get('name','恢复文档.docx')),'status':row.get('status','cancelled'),'attempts':row.get('attempts',0),'settings':settings}
   if item['status']=='completed' and d.get('result') and d.get('report',{}).get('restoredAndRechecked'):item.update(result=d['result'],report=copy.deepcopy(d['report']))
   elif item['status']=='completed':item.update(status='failed',error='旧成功输出未通过恢复核验，请重新排版')
   elif item['status'] in ['queued','running','cancelling']:item.update(status='cancelled',error='服务重启中断了未完成任务，可以重试')
   elif item['status'] in ['failed','cancelled']:item['error']=str(row.get('error',''))[:250]
   else:item.update(status='cancelled',error='保存的任务状态未知，需要重新处理')
   items.append(item)
  if not items:return None
  identifier=uuid.uuid4().hex;statuses={x['status'] for x in items};job={'id':identifier,'previousId':snapshot.get('id'),'status':'cancelled' if 'cancelled' in statuses else 'completed_with_errors' if 'failed' in statuses else 'completed','cancel':False,'createdAt':datetime.now(timezone.utc).isoformat(),'items':items}
  with self.lock:self.jobs[identifier]=job
  return self.snapshot(identifier)
 def download(self,identifier):
  snap=self.snapshot(identifier)
  if snap['status'] in ['queued','running','cancelling']:raise ValueError('请等待任务结束后下载')
  out=io.BytesIO()
  with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
   for i,x in enumerate(snap['items']):
    if x['status']!='completed':continue
    name=re.sub(r'[\x00-\x1f/\\:*?"<>|]','_',str(x['name'])).removesuffix('.docx')[:100]
    prefix=f'{i+1:03}_{name}'
    z.writestr(prefix+'_DocStyle_v5.docx',base64.b64decode(x['result']))
    z.writestr(prefix+'_检查报告.json',json.dumps(x['report'],ensure_ascii=False,indent=2))
   z.writestr('任务汇总.json',json.dumps({'id':snap['id'],'status':snap['status'],'progress':snap['progress'],'items':[{k:v for k,v in x.items() if k not in ['result','report']} for x in snap['items']]},ensure_ascii=False,indent=2))
  return out.getvalue()
