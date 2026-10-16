"""Personal Feishu collection: explicit API pagination or an authenticated browser worker."""
import hashlib
import json
import os
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import storage as db
import sources
import config

LOCK = threading.Lock()
STOP = threading.Event()
AUTH_LOCK = threading.Lock()
SCOPES = ['offline_access', 'search:message', 'im:chat:readonly', 'im:message:readonly',
          'im:message.group_msg:get_as_user', 'im:message.p2p_msg:get_as_user']
RANGES = {'today': 1, 'five':5, 'week': 7, 'month': 30, 'all': None}

def user_env():
    return config.feishu_env(db.DATA)

def call(args, identity='bot', timeout=60):
    if identity == 'bot': return sources.lark(args, timeout=timeout)
    p = subprocess.run([sources.LARK, *args], env=user_env(), capture_output=True, text=True, timeout=timeout)
    try: out = json.loads(p.stdout or p.stderr)
    except ValueError: raise RuntimeError('飞书命令没有返回有效 JSON')
    if out.get('ok') is False or p.returncode:
        error = out.get('error') or {}
        raise RuntimeError(f"{error.get('code','')} {db.clean(error.get('message','飞书读取失败'))}".strip())
    return out

def connection(refresh=False):
    if not config.SETTINGS['feishu_enabled']:return {'ready':False,'mode':'user','phase':'disabled','message':'飞书同步已在 config.json 中关闭。'}
    cached = db.get('feishu_connection') or {}
    if refresh or not cached:
        try:
            raw = call(['auth','status'], 'user', timeout=10)
            user = (raw.get('identities') or {}).get('user') or {}
            if user.get('available'):
                checked = call(['auth','check','--scope',' '.join(SCOPES[1:]),'--json'], 'user', timeout=10)
                cached = {'ready': True, 'mode': 'user', 'phase': 'ready', 'checked_at': db.now(),
                          'message': '已连接个人飞书，将检索授权范围内的消息与话题。'}
            else:
                cached = {'ready': False,'mode':'user','phase':'needs_setup','checked_at':db.now(),
                          'message':'请配置飞书应用并授权个人消息读取，详见 docs/FEISHU.zh-CN.md。'}
        except Exception as ex:
            cached = {'ready':False,'mode':'user','phase':'needs_setup','checked_at':db.now(),
                      'message':'尚未配置独立的飞书用户授权。'}
        db.put('feishu_connection',cached)
    browser = db.get('feishu_browser') or {}
    if cached.get('mode') != 'user' and browser.get('verified_at'):
        try: fresh = datetime.now(db.TZ)-datetime.fromisoformat(browser['verified_at']) < timedelta(hours=24)
        except ValueError: fresh = False
        if fresh:
            return {**cached, 'ready':True, 'mode':'browser', 'browser':browser,
                    'message':'已复用 Chrome 中登录的个人飞书。消息由本机 Codex 浏览器采集，API 接入可另行授权。'}
    return cached

def bounds(range_name):
    if range_name not in RANGES: raise ValueError('不支持的消息范围')
    end = datetime.now(db.TZ)
    if range_name == 'all': return None, end.isoformat(timespec='seconds')
    start = end.replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=RANGES[range_name]-1)
    return start.isoformat(), end.isoformat(timespec='seconds')

def timestamp(value):
    if not value: return db.now()
    value = str(value)
    if value.isdigit():
        n = int(value)
        return datetime.fromtimestamp(n/1000 if n>10**11 else n,db.TZ).isoformat(timespec='seconds')
    parsed = datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=db.TZ)
    return parsed.astimezone(db.TZ).isoformat(timespec='seconds')

def save_message(message, chat, origin):
    content = (message.get('body') or {}).get('content') or message.get('content') or message.get('text') or ''
    if not isinstance(content,str): content=json.dumps(content,ensure_ascii=False)
    try:
        obj=json.loads(content)
        content=obj.get('text') if isinstance(obj,dict) and obj.get('text') else content
    except ValueError: pass
    sender = message.get('sender') or {}
    if not isinstance(sender,dict): sender={'name':str(sender)}
    if content.startswith(('Workworld ·','Workstation ·','今日晨报\n','18:00 · 今晚值得提前做\n','夜间任务执行结果\n','工作台定时任务需要关注\n')): return False
    date = timestamp(message.get('create_time') or message.get('timestamp'))
    mid = message.get('message_id') or message.get('id')
    generated_id=not mid
    if not mid:
        mid='browser-'+hashlib.sha256((chat['chat_id']+date+sender.get('name','')+content).encode()).hexdigest()
    rid='feishu:'+str(mid)
    position=str(message.get('message_position') or message.get('position') or '')
    with db.connect() as c:
        previous=c.execute("SELECT id,body FROM records WHERE id=? OR (kind='feishu' AND json_extract(body,'$.message_id')=?) LIMIT 1",(rid,str(mid))).fetchone()
        if not previous and position:
            statement="SELECT id,body FROM records WHERE kind='feishu' AND json_extract(body,'$.chat_id')=? AND json_extract(body,'$.position')=?"
            params=[chat['chat_id'],position]
            if origin in ('user','bot'):
                statement+=" AND json_extract(body,'$.source')='browser'"
            previous=c.execute(statement+' LIMIT 1',params).fetchone()
        if not previous and generated_id:
            previous=c.execute("SELECT id,body FROM records WHERE kind='feishu' AND json_extract(body,'$.chat_id')=? AND substr(updated,1,16)=? AND json_extract(body,'$.sender_name')=? AND json_extract(body,'$.text')=? LIMIT 1",(chat['chat_id'],date[:16],db.clean(message.get('sender_name') or sender.get('name','')),db.clean(content))).fetchone()
        if previous:rid=previous['id']

    record={'id':rid,'kind':'feishu','day':date[:10],'updated':date,'title':db.clean(chat.get('name','飞书会话')),
            'text':db.clean(content),'chat_id':chat['chat_id'],'message_id':str(mid),
            'sender_name':db.clean(sender.get('name') or sender.get('sender_name') or message.get('sender_name') or ''), 'sender_id':sender.get('id'), 'parent_id':message.get('parent_id'), 'root_id':message.get('root_id'),
            'message_type':message.get('msg_type'),'source':origin,'chat_type':chat.get('chat_type','unknown'),'deleted':bool(message.get('deleted')),
            'coverage':'已登录飞书网页版可见消息' if origin=='browser' else '个人用户 API 可见消息' if origin=='user' else '机器人 API 可见消息'}
    record.update(position=position,thread_id=message.get('thread_id'),mentions=message.get('mentions') or [],
                  time_precision=message.get('time_precision','minute' if len(str(message.get('create_time','')))==16 else 'second'),
                  restricted=bool(message.get('restricted')),has_attachment=bool(message.get('has_attachment')),
                  display_time=message.get('display_time'),has_thread=bool(message.get('has_thread')),reply_count=int(message.get('reply_count') or 0))
    if previous:
        old=json.loads(previous['body'])
        if origin=='browser' and old.get('source') in ('user','bot'):
            record.update(message_id=old['message_id'],source=old['source'],sender_name=old.get('sender_name',record['sender_name']))
    db.save_record(record)
    return rid


def count_message(job, message, chat, identity):
    rid=save_message(message,chat,identity)
    if rid and rid not in job.setdefault('message_keys',[]):job['message_keys'].append(rid)
    job['messages']=len(job.get('message_keys',[]))
    return rid


def page(data, key):
    body=data.get('data') or {}
    items=body.get(key) or body.get('items') or []
    token=body.get('page_token') or ''
    has_more=bool(body.get('has_more'))
    if has_more and not token: raise RuntimeError('接口声明有下一页，但未返回分页游标')
    return items,token,has_more

def public_job():
    job=db.get('feishu_crawl') or {}
    visible={k:v for k,v in job.items() if k not in ('chats','list_token','message_token','seen_list_tokens','seen_message_tokens','failed_cursors','message_keys','thread_cursors','search_token','seen_search_tokens','_indexed_ids')}
    visible['errors']=[{k:v for k,v in e.items() if k!='cursor'} for e in job.get('errors',[])]
    return visible

def persist(job):
    job['updated_at']=db.now();db.put('feishu_crawl',job)

def start(range_name='today', resume=False, mode=None):
    if range_name not in RANGES:raise ValueError('不支持的消息范围')
    state=connection()
    mode=mode or state.get('mode','bot')
    if mode=='user' and not state.get('ready'):raise ValueError('请先完成个人飞书授权')
    old=db.get('feishu_crawl') or {}
    if old.get('status') in ('listing','reading','searching','waiting_browser'):
        if old.get('mode')=='browser' and mode=='user' and state.get('mode')=='user':
            db.put('feishu_browser_previous_job',old)
        else:return {'busy':True,'job':public_job()}
    if mode=='browser':
        if resume and old.get('mode')=='browser' and old.get('range')==range_name:
            job=old;job['status']='waiting_browser';job['errors']=[]
        else:
            a,b=bounds(range_name)
            job={'id':str(uuid.uuid4()),'mode':'browser','identity':'user_browser','range':range_name,
                 'start':a,'end':b,'status':'waiting_browser','created_at':db.now(),'chats_done':0,'chats_total':0,
                 'messages':0,'errors':[],'coverage':'等待已登录浏览器逐会话采集','completed_chats':[]}
        persist(job);return {'started':True,'job':public_job()}
    if not LOCK.acquire(False):return {'busy':True}
    STOP.clear()
    if resume and old.get('mode')==mode and old.get('range')==range_name and old.get('status') in ('paused','partial','error','interrupted'):
        job=old;job['errors']=[];job['status']='listing' if not job.get('listed') else 'reading'
        if old.get('listed') and old.get('chat_index',0)>=len(old.get('chats',[])):
            job['chat_index']=0;job['message_token']='';job['seen_message_tokens']=[]
    else:
        a,b=bounds(range_name)
        job={'id':str(uuid.uuid4()),'mode':mode,'identity':mode,'range':range_name,'start':a,'end':b,
             'status':'listing','created_at':db.now(),'chats_done':0,'chats_total':0,'messages':0,'errors':[],
             'chats':[],'list_token':'','message_token':'','seen_list_tokens':[],'seen_message_tokens':[],
             'listed':False,'chat_index':0,'completed_chats':[],'failed_cursors':{},'coverage':'仅机器人可见会话' if mode=='bot' else '用户 API 可见群聊和私聊'}
    persist(job)
    if mode=='user':
        import feishu_api
        target=feishu_api.crawl
    else:target=crawl
    threading.Thread(target=target,args=(job,),daemon=True).start()
    return {'started':True,'job':public_job()}

def within(job, message):
    value=message.get('create_time') or message.get('timestamp')
    if not value:return False
    stamp=timestamp(value)
    return (not job.get('start') or stamp>=job['start']) and stamp<=job['end']


def collect_thread(job, chat, thread, identity):
    if thread in job.setdefault('threads_done',[]):return
    token=job.setdefault('thread_cursors',{}).get(thread,'')
    seen=[]
    while True:
        if STOP.is_set():raise InterruptedError('采集已暂停')
        args=['im','+threads-messages-list','--as',identity,'--thread',thread,'--order','asc','--no-reactions','--page-size','50']
        if token:args+=['--page-token',token]
        rows,next_token,more=page(call(args,identity),'messages')
        for message in rows:
            if within(job,message):count_message(job,{**message,'thread_id':thread},chat,identity)
        if more and next_token in seen:raise RuntimeError('话题分页游标重复，未标记完成')
        if more:seen.append(next_token)
        token=next_token;job['thread_cursors'][thread]=token;persist(job)
        if not more:
            job['threads_done'].append(thread);job['thread_cursors'].pop(thread,None);persist(job);return


def crawl(job):
    identity=job['mode']
    try:
        while not job.get('listed'):
            if STOP.is_set():job['status']='paused';return
            args=['im','+chat-list','--as',identity,'--page-size','100']
            if identity=='user':args+=['--types','group,p2p']
            if job['list_token']:args+=['--page-token',job['list_token']]
            items,token,more=page(call(args,identity),'chats')
            known={c['chat_id'] for c in job['chats']}
            for item in items:
                cid=item.get('chat_id') or item.get('id')
                if cid and cid not in known:job['chats'].append({'chat_id':cid,'name':item.get('name') or item.get('chat_name') or cid,'chat_type':item.get('chat_type','group')});known.add(cid)
            if more and token in job['seen_list_tokens']:raise RuntimeError('会话分页游标重复，已停止，避免错误地宣告全量完成')
            if more:job['seen_list_tokens'].append(token)
            job['list_token']=token;job['chats_total']=len(job['chats']);job['listed']=not more;persist(job)
        job['chats_total']=len(job['chats']);job['status']='reading';persist(job)
        while job['chat_index']<len(job['chats']):
            if STOP.is_set():job['status']='paused';return
            chat=job['chats'][job['chat_index']];job['current_chat']=chat['name'];persist(job)
            if chat['chat_id'] in job.setdefault('completed_chats',[]):
                job['chat_index']+=1;job['message_token']='';job['seen_message_tokens']=[];continue
            if not job['message_token']:
                job['message_token']=job.get('failed_cursors',{}).get(chat['chat_id'],'')
            try:
                args=['im','+chat-messages-list','--as',identity,'--chat-id',chat['chat_id'],'--order','asc','--no-reactions','--page-size','50','--end',job['end']]
                # Older topic roots may have replies today, so discover roots across visible history.
                if job['message_token']:args+=['--page-token',job['message_token']]
                messages,token,more=page(call(args,identity),'messages')
                for m in messages:
                    if within(job,m):count_message(job,m,chat,identity)
                    if m.get('thread_id'):collect_thread(job,chat,m['thread_id'],identity)
                    for reply in m.get('thread_replies',[]) or []:
                        if within(job,reply):count_message(job,reply,chat,identity)
                if more and token in job['seen_message_tokens']:raise RuntimeError('消息分页游标重复，未标记完成')
                job['message_token']=token
                if more:job['seen_message_tokens'].append(token)
                if not more:
                    job['completed_chats'].append(chat['chat_id']);job['chats_done']=len(job['completed_chats'])
                    job.setdefault('failed_cursors',{}).pop(chat['chat_id'],None)
                    job['chat_index']+=1;job['message_token']='';job['seen_message_tokens']=[]
                persist(job)
            except InterruptedError:
                job['status']='paused';return
            except Exception as ex:
                job['errors'].append({'chat_id':chat['chat_id'],'chat':chat['name'],'cursor':job['message_token'],'error':db.clean(str(ex))[:250]})
                job.setdefault('failed_cursors',{})[chat['chat_id']]=job['message_token']
                job['chat_index']+=1;job['message_token']='';job['seen_message_tokens']=[];persist(job)
        job['status']='partial' if job['errors'] else 'complete';job['finished_at']=db.now()
        db.event('sync','飞书消息遍历结束',f"{job['chats_done']}/{job['chats_total']} 个会话，{job['messages']} 条消息，范围 {job['range']}，身份 {identity}")
    except Exception as ex:
        job['status']='error';job['errors'].append({'error':db.clean(str(ex))[:300]})
    finally:
        persist(job);LOCK.release()

def pause():
    job=db.get('feishu_crawl') or {}
    if job.get('mode')=='browser' and job.get('status')=='waiting_browser':job['status']='paused';persist(job)
    STOP.set()
    return {'paused':True}

def browser_batch(payload):
    job=db.get('feishu_crawl') or {}
    if job.get('mode')!='browser' or payload.get('job_id')!=job.get('id'):raise ValueError('浏览器采集任务已失效')
    if job.get('status')!='waiting_browser':raise ValueError('采集已暂停或结束，请先继续任务')
    chat=payload.get('chat') or {}
    if not chat.get('chat_id'):raise ValueError('缺少会话标识')
    messages=payload.get('messages') or []
    if len(messages)>500:raise ValueError('每批最多 500 条消息')
    count=0
    for m in messages:
        if not (m.get('timestamp') or m.get('create_time')):continue
        stamp=timestamp(m.get('timestamp') or m.get('create_time'))
        if job['start'] and stamp<job['start']:continue
        if stamp>job['end']:continue
        before=job.get('messages',0)
        count_message(job,m,chat,'browser')
        count+=job.get('messages',0)-before
    completed=job.setdefault('completed_chats',[])
    if payload.get('chat_complete') and chat['chat_id'] not in completed:completed.append(chat['chat_id'])
    job['chats_done']=len(completed);job['chats_total']=max(int(payload.get('chats_total',job.get('chats_total',0))),len(completed))
    job['current_chat']=chat.get('name','')
    if payload.get('boundary'):job.setdefault('boundaries',{})[chat['chat_id']]=db.clean(payload['boundary'])
    if payload.get('inventory'):job['inventory']=payload['inventory']
    if 'pending_work' in payload:job['pending_work']=payload['pending_work']
    if payload.get('error'):job.setdefault('errors',[]).append({'chat':chat.get('name'),'error':db.clean(payload['error'])})
    if payload.get('finished'):
        complete=payload.get('enumeration_complete') and job['chats_done']==job['chats_total'] and not job.get('errors')
        job['status']='complete' if complete else 'partial';job['finished_at']=db.now()
    persist(job)
    status=db.get('feishu_status') or {}
    status.update(synced_at=db.now(),identity='browser',coverage='已登录个人飞书网页；逐会话和话题核验',chats=job['chats_total'],messages=len([r for r in db.records() if r['kind']=='feishu']),complete=job.get('status')=='complete',status=job.get('status'),errors=job.get('errors',[]))
    db.put('feishu_status',status)
    db.put('feishu_browser',{'verified_at':db.now(),'url':'https://www.feishu.cn/messenger/',
                            'account':db.get('settings',{}).get('name',''),'coverage':job['range'],'last_job':job['id']})
    return {'imported':count,'job':public_job()}

def messages(range_name='today', query='', offset=0, limit=50):
    a,b=bounds(range_name)
    terms=["kind='feishu' AND COALESCE(json_extract(body,'$.superseded_by_api_job'),'')=''"];params=[]
    if a:terms+=['updated>=?'];params+=[a]
    terms+=['updated<=?'];params+=[b]
    if query:terms+=['(json_extract(body,\'$.text\') LIKE ? OR json_extract(body,\'$.title\') LIKE ?)'];params+=['%'+query+'%']*2
    where=' AND '.join(terms)
    with db.connect() as c:
        total=c.execute('SELECT COUNT(*) FROM records WHERE '+where,params).fetchone()[0]
        rows=c.execute('SELECT body FROM records WHERE '+where+' ORDER BY updated DESC,id LIMIT ? OFFSET ?',params+[limit,offset]).fetchall()
    return {'items':[json.loads(r[0]) for r in rows],'total':total,'offset':offset,'range':range_name}

def connect_personal():
    if not AUTH_LOCK.acquire(False):return {'busy':True}
    threading.Thread(target=auth_flow,daemon=True).start()
    return {'started':True}

def auth_flow():
    process=None
    try:
        db.put('feishu_connection',{'ready':False,'mode':'user','phase':'authorizing','message':'正在发起个人飞书只读授权；请先运行 python3 manage.py feishu-setup。'})
        auth=call(['auth','login','--scope',' '.join(SCOPES),'--no-wait','--json'],'user',timeout=30)
        data=auth.get('data') or auth
        code=data.get('device_code');url=data.get('verification_uri_complete') or data.get('verification_url') or data.get('verification_uri')
        if not code or not url:raise RuntimeError('飞书未提供有效授权链接，请检查应用的消息只读权限')
        db.put('feishu_connection',{'ready':False,'mode':'user','phase':'authorizing','verification_url':url,
                                  'message':'请确认读取会话与私聊、群聊消息的权限。授权由你在飞书完成。'})
        call(['auth','login','--device-code',code,'--json'],'user',timeout=900)
        connection(refresh=True)
    except Exception as ex:
        db.put('feishu_connection',{'ready':False,'mode':'user','phase':'error','message':db.clean(str(ex))[:300]})
    finally:AUTH_LOCK.release()
