#!/usr/bin/env python3
import argparse
import hashlib
import json
import mimetypes
import os
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import storage as db
import sources
import engine
import feishu
import config

TOKEN=secrets.token_urlsafe(32)
PORT=config.SETTINGS['port']
DEMO=False
SYNC_LOCK=threading.Lock()

def background(fn,*args):
    threading.Thread(target=fn,args=args,daemon=True).start()

def sync():
    if not SYNC_LOCK.acquire(False):return {'busy':True}
    try:return sources.sync_all()
    finally:SYNC_LOCK.release()

def check_schedules(current):
    settings=db.get('settings')
    if not settings.get('schedule_enabled'):return
    for kind in ('morning','evening'):
        target=current.replace(hour=int(settings[kind][:2]),minute=int(settings[kind][3:]),second=0,microsecond=0)
        if current<target:continue
        key=current.date().isoformat()+':'+kind
        with db.connect() as c:exists=c.execute('SELECT status FROM schedule_fires WHERE key=?',(key,)).fetchone()
        if exists:continue
        # Planning only runs in its scheduled minute; no off-time automatic catch-up.
        window=60 if kind=='evening' else 3600
        if (current-target).total_seconds()<window:engine.daily(kind)
        else:
            with db.connect() as c:c.execute('INSERT OR IGNORE INTO schedule_fires VALUES (?,?,?)',(key,db.now(),'missed'))
            db.event('schedule','已记录错过的定时任务',f'{settings[kind]} 的任务未运行；可由你主动点击生成。')

def scheduler():
    last_sync=0
    while True:
        try:
            settings=db.get('settings')
            if time.time()-last_sync>=settings.get('sync_minutes',10)*60:
                sync();last_sync=time.time()
            check_schedules(datetime.now(db.TZ))
            db.put('scheduler_heartbeat',db.now())
        except Exception as e:db.event('error','后台调度异常',str(e))
        time.sleep(20)

def state():
    with db.connect() as c:
        events=[dict(r) for r in c.execute('SELECT * FROM events ORDER BY id DESC LIMIT 35')]
        fires=[dict(r) for r in c.execute('SELECT * FROM schedule_fires ORDER BY created DESC LIMIT 20')]
    records=db.records();ts=db.todos();intentions=db.intentions();night_tasks=[{**t,'copy_prompt':engine.copy_prompt(t)} for t in db.night_work()];rs=db.runs()
    current_records=list(records)
    plan=db.get('plan:'+db.today())
    if plan:plan={**plan,'risks':db.active_planning('risk'),'night_recommendations':db.night_work()}
    ids={i for t in ts+intentions+night_tasks+(plan.get('risks',[]) if plan else []) for i in t.get('evidence_ids',[])}-{r['id'] for r in records}
    records+=db.evidence_records(ids)
    return {'date':db.today(),'now':db.now(),'timezone':config.SETTINGS['timezone'],'demo':DEMO,'csrf':TOKEN,'settings':db.get('settings'),
        'records':records,'tasks':ts,'intentions':intentions,'night_tasks':night_tasks,'runs':rs,'plan':plan,'last_sync':db.get('last_sync'),
        'feishu':db.get('feishu_status'),'events':events,'notifications':db.get('notifications',[]),'scheduler_heartbeat':db.get('scheduler_heartbeat'),
        'feishu_connection':feishu.connection(),'feishu_job':feishu.public_job(),
        'schedule_fires':fires,'reports':{k:db.get('report:'+k+':'+db.today()) for k in ['morning','evening','night']},
        'busy':engine.LOCK.locked(), 'counts':{'threads':sum(r['kind']=='codex' for r in current_records),'memories':sum(r['kind']=='memory' for r in current_records),
        'messages':sum(r['kind']=='feishu' for r in current_records),'todo':sum(t['status'] not in ['done'] for t in ts),'intentions':len(intentions),'queued':sum(t.get('queued',False) for t in night_tasks)}}

class Handler(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args):pass
    def allowed_host(self):
        return self.headers.get('Host','') in (f'127.0.0.1:{PORT}',f'localhost:{PORT}')
    def send(self,value,status=200,ctype='application/json; charset=utf-8'):
        body=json.dumps(value,ensure_ascii=False).encode() if not isinstance(value,bytes) else value
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'")
        self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if not self.allowed_host():return self.send({'error':'仅支持本机访问'},403)
        path=urlparse(self.path).path
        if path=='/api/state':return self.send(state())
        if path=='/api/health':return self.send({'ok':True,'at':db.now()})
        if path=='/api/records':
            try:
                q=parse_qs(urlparse(self.path).query)
                return self.send(db.visible_records(q.get('kind',['all'])[0],q.get('related',['0'])[0]=='1',q.get('query',[''])[0],
                    q.get('offset',['0'])[0],q.get('limit',['50'])[0],q.get('range',['five'])[0]))
            except ValueError as ex:return self.send({'error':str(ex)},400)
        if path=='/api/archives':
            import archives
            return self.send({'items':archives.list_files()})
        if path=='/api/archive':
            import archives
            try:
                day=parse_qs(urlparse(self.path).query).get('day',[''])[0]
                return self.send(archives.read(day),ctype='text/markdown; charset=utf-8')
            except ValueError as ex:return self.send({'error':str(ex)},400)
            except FileNotFoundError:return self.send({'error':'归档不存在'},404)
        if path=='/api/completed':
            try:
                q=parse_qs(urlparse(self.path).query)
                result=db.completed(q.get('category',[''])[0],q.get('day',[''])[0],q.get('query',[''])[0],
                    q.get('offset',['0'])[0],q.get('limit',['50'])[0])
                for item in result.get('items',[]):
                    if item.get('_completed_kind')=='night':item['copy_prompt']=engine.copy_prompt(item)
                return self.send(result)
            except ValueError as ex:return self.send({'error':str(ex)},400)
        if path=='/api/feishu/export':
            try:
                import feishu_api
                q=parse_qs(urlparse(self.path).query);fmt=q.get('format',['jsonl'])[0]
                if fmt not in ('jsonl','md','brief'):raise ValueError('导出格式仅支持 jsonl、md 或 brief')
                value=feishu_api.brief_text(db.get('plan:'+db.today())) if fmt=='brief' else feishu_api.export_text(q.get('range',['today'])[0],fmt)
                return self.send(value.encode(),ctype='application/x-ndjson; charset=utf-8' if fmt=='jsonl' else 'text/markdown; charset=utf-8')
            except ValueError as ex:return self.send({'error':str(ex)},400)
        if path=='/api/feishu/messages':
            try:
                q=parse_qs(urlparse(self.path).query)
                return self.send(db.visible_records('feishu',q.get('related',['0'])[0]=='1',q.get('query',[''])[0],
                    q.get('offset',['0'])[0],q.get('limit',['50'])[0],q.get('range',['five'])[0]))
            except ValueError as ex:return self.send({'error':str(ex)},400)
        if path.startswith('/api/artifact/'):
            rid=path.rsplit('/',1)[1]
            run=db.run(rid)
            if not run:return self.send({'error':'产物不存在'},404)
            content=run.get('output') or run.get('result') or run.get('error','')
            return self.send(content.encode(),ctype='text/plain; charset=utf-8')
        files={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/icon.svg':'icon.svg'}
        if path not in files:return self.send({'error':'页面不存在'},404)
        p=db.ROOT/'static'/files[path]
        return self.send(p.read_bytes(),ctype=mimetypes.guess_type(p)[0]+'; charset=utf-8')
    def do_POST(self):
        if not self.allowed_host():return self.send({'error':'仅支持本机访问'},403)
        origin=self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'):return self.send({'error':'不允许跨站操作'},403)
        if not secrets.compare_digest((self.headers.get('X-Workstation-Key') or self.headers.get('X-Workworld-Key','')),TOKEN):return self.send({'error':'请刷新工作台后重试'},403)
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size>2_000_000:return self.send({'error':'请求过大'},413)
            data=json.loads(self.rfile.read(size) or '{}')
            path=urlparse(self.path).path
            if DEMO and path in ('/api/analyze','/api/sync','/api/notify-test','/api/feishu/connect','/api/feishu/crawl','/api/report'):
                return self.send({'error':'演示模式使用虚构数据，不连接账号或调用模型。'},400)
            if path=='/api/completed/delete':return self.send(db.delete_completed(data.get('kind'),data.get('id')))
            if path=='/api/item/delete':return self.send(db.delete_work_item(data.get('kind'),data.get('id')))
            if path=='/api/planning':return self.send(db.set_planning_status(data.get('id'),data.get('status')))
            if path=='/api/feishu/connect':return self.send(feishu.connect_personal())
            if path=='/api/feishu/crawl':return self.send(feishu.start(data.get('range','today'),bool(data.get('resume')),data.get('mode')))
            if path=='/api/feishu/stop':return self.send(feishu.pause())
            if path=='/api/feishu/browser-batch':return self.send(feishu.browser_batch(data))
            if path=='/api/sync':background(sync);return self.send({'started':True})
            if path=='/api/analyze':
                scope=data.get('scope','all')
                if scope not in ('all','intentions','planning'):raise ValueError('无效整理范围')
                if engine.LOCK.locked():return self.send({'error':'Codex 正在执行，请等待当前任务完成'},409)
                background(engine.analyze,scope);return self.send({'started':True,'scope':scope})
            if path=='/api/task/create':
                title=data.get('title','');notes=data.get('notes','')
                if not isinstance(title,str) or not title.strip() or len(title.strip())>200:raise ValueError('请填写 1—200 字的待办')
                if not isinstance(notes,str) or len(notes)>4000:raise ValueError('待办说明最多 4000 字')
                t={'id':'todo:'+str(uuid.uuid4()),'day':db.today(),'created':db.now(),'updated':db.now(),'title':db.clean(title.strip()),
                   'summary':db.clean(notes.strip()),'next_action':db.clean(notes.strip()),'origin':'user','role':'todo','status':'todo',
                   'priority':'medium','project':'','evidence_ids':[],'night_eligible':False,'night_prompt':'','queued':False}
                db.save_task(t);return self.send(t)
            if path=='/api/task':
                t=db.task(data.get('id'))
                if not t:return self.send({'error':'任务不存在'},404)
                if any(k in data for k in ('title','notes','deleted')) and t.get('origin')!='user':raise ValueError('自动意向不能改写为待办，请自行填写待办')
                if 'title' in data:
                    if not isinstance(data['title'],str) or not data['title'].strip() or len(data['title'].strip())>200:raise ValueError('请填写 1—200 字的待办')
                    t['title']=db.clean(data['title'].strip())
                if 'notes' in data:
                    if not isinstance(data['notes'],str) or len(data['notes'])>4000:raise ValueError('待办说明最多 4000 字')
                    t['summary']=t['next_action']=db.clean(data['notes'].strip())
                if 'deleted' in data:t['deleted']=bool(data['deleted'])
                if 'dismissed' in data:
                    if t.get('origin')=='user':raise ValueError('手填待办不属于自动意向')
                    t['dismissed']=bool(data['dismissed'])
                if 'status' in data:
                    if data['status'] not in ('todo','done','blocked','observed'):raise ValueError('无效任务状态')
                    if t.get('origin')!='user' and data['status'] not in ('todo','done'):raise ValueError('意向仅支持完成或重新打开')
                    t.update(status=data['status'],manual_status=True)
                    t['completed_at']=db.now() if data['status']=='done' else None
                    if t.get('origin')!='user' and data['status']=='todo':t.update(day=db.today(),stale=False,dismissed=False,rank=-1)
                if 'queued' in data:
                    raise ValueError('夜间工作由你复制提示词后手动运行，不再使用执行队列')
                t['updated']=db.now();db.save_task(t);return self.send(t)
            if path=='/api/run':
                return self.send({'error':'夜间工作仅提供推荐，请复制提示词到 Codex 后自行运行','manual_only':True},410)
            if path=='/api/cancel':return self.send({'cancelled':engine.cancel(data.get('id'))})
            if path=='/api/report':
                kind=data.get('kind')
                if kind not in ('morning','evening','night'):raise ValueError('无效的时间安排')
                if kind=='night':return self.send({'error':'夜间自动执行已停用，请查看夜间推荐并自行运行'},410)
                # Preview does not consume the real scheduled slot and does not send a message.
                if data.get('preview',True):
                    ts=db.todos() if kind=='morning' else db.night_work()
                    text='\n'.join('• '+t['title'] for t in ts) if kind=='morning' else '\n\n'.join(engine.copy_prompt(t) for t in ts)
                    if kind=='morning':
                        text='夜间工作由你手动运行，复制提示词不代表已完成。\n\n今日待办：\n'+text
                    r={'day':db.today(),'created':db.now(),'kind':kind,'title':'晨报预览' if kind=='morning' else '夜间推荐预览','text':text or '暂无合适内容。','preview':True}
                    db.put('report:'+kind+':'+db.today(),r);return self.send(r)
                background(engine.daily,kind);return self.send({'started':True})
            if path=='/api/settings':
                s=db.get('settings')
                for k in ('morning','evening'):
                    if k in data:
                        datetime.strptime(data[k],'%H:%M');s[k]=data[k]
                for k in ('schedule_enabled','notify_feishu'):
                    if k in data:s[k]=bool(data[k])
                if 'name' in data:s['name']=str(data['name'])[:40]
                if 'notification_chat' in data:raise ValueError('提醒目标固定为当前已授权用户，不接受会话 ID')
                s.pop('night_limit',None)
                s.update(auto_night=False,night_mode='manual_copy')
                db.put('settings',s);db.event('settings','已保存个人偏好');return self.send(s)
            if path=='/api/notify-test':return self.send(engine.notify('Workstation · 连接测试','本机工作台已启动。此消息用于验证提醒通道。'))
            if path=='/api/import':
                records=data.get('messages',[])
                if not isinstance(records,list) or len(records)>1000:raise ValueError('每次最多导入 1000 条记录')
                count=0
                for m in records:
                    if not isinstance(m,dict) or not m.get('text'):continue
                    timestamp=m.get('timestamp',db.now())
                    if not sources.same_day(timestamp,db.today()):continue
                    mid=str(m.get('message_id') or hashlib.sha256((str(m.get('chat_id'))+timestamp+m['text']).encode()).hexdigest())
                    db.save_record({'id':'feishu-import:'+mid,'kind':'feishu','day':db.today(),'updated':timestamp,'title':db.clean(m.get('chat_name','消息文件整理')),'text':db.clean(m['text']), 'chat_id':m.get('chat_id'),'message_id':mid,'coverage':'消息文件整理导入；范围以整理者声明为准'})
                    count+=1
                db.event('sync','已导入消息文件整理结果',f'{count} 条今日记录');return self.send({'imported':count})
            return self.send({'error':'接口不存在'},404)
        except (ValueError,KeyError,TypeError) as e:return self.send({'error':db.clean(str(e))},400)
        except Exception as e:db.event('error','操作未完成',str(e));return self.send({'error':'操作未完成，详情已写入本机事件记录'},500)

def main():
    global PORT,DEMO
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=config.SETTINGS['port']);parser.add_argument('--demo',action='store_true');args=parser.parse_args();PORT=args.port;DEMO=args.demo
    config.SETTINGS['port']=PORT
    demo_data=None
    if DEMO:
        import tempfile
        demo_data=tempfile.TemporaryDirectory(prefix='workstation-demo-');db.DATA=Path(demo_data.name)
    os.umask(0o077)
    db.init()
    import archives
    archives.write_days()
    job=db.get('feishu_crawl') or {}
    if job.get('status') in ('listing','reading','searching'):
        job['status']='interrupted';feishu.persist(job)
    if DEMO:
        import demo
        demo.seed()
    else:background(scheduler)
    server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    print(f'Workstation: http://127.0.0.1:{PORT}',flush=True)
    server.serve_forever()

if __name__=='__main__':main()
