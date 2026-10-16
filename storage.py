import json
import hashlib
import os
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import config

ROOT = Path(__file__).resolve().parent
DATA = config.path(config.SETTINGS['data_dir'])
TZ = ZoneInfo(config.SETTINGS['timezone'])

def now():
    return datetime.now(TZ).isoformat(timespec='seconds')

def today():
    return datetime.now(TZ).date().isoformat()

def clean(text):
    text = str(text or '')
    text = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----', '[私钥已隐藏]', text, flags=re.S)
    text = re.sub(r'(?:glpat-|sk-|gh[pousr]_)[A-Za-z0-9_.\-]{10,}', '[凭据已隐藏]', text)
    text = re.sub(r'(?i)((?:password|passwd|app_secret|access_token|refresh_token|api_key|密码)\s*[:=：]?\s*)[\w.\-/+]{4,}', r'\1[已隐藏]', text)
    text = re.sub(r'''(?i)((?:wifi-sec\.psk|app_secret|access_token|refresh_token|api_key)\s*[=:]?\s*)["'][^"']+["']''', r'\1[已隐藏]', text)
    text = re.sub(r'(?i)([?&](?:token|code|key|disposable_login_token)=)[^\s&)]+', r'\1[已隐藏]', text)
    return text

def connect():
    DATA.mkdir(mode=0o700, exist_ok=True)
    os.chmod(DATA, 0o700)
    c = sqlite3.connect(DATA / 'workstation.sqlite', timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    return c

def init():
    with connect() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, kind TEXT, day TEXT, updated TEXT, body TEXT);
        CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, day TEXT, body TEXT);
        CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created TEXT, status TEXT, body TEXT);
        CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, created TEXT, kind TEXT, title TEXT, detail TEXT);
        CREATE TABLE IF NOT EXISTS schedule_fires (key TEXT PRIMARY KEY, created TEXT, status TEXT);
        CREATE TABLE IF NOT EXISTS purged_items (kind TEXT, id TEXT, PRIMARY KEY(kind,id));
        CREATE TABLE IF NOT EXISTS planning_items (id TEXT PRIMARY KEY, kind TEXT, day TEXT, body TEXT);
        CREATE TABLE IF NOT EXISTS record_snapshots (day TEXT, id TEXT, kind TEXT, updated TEXT, body TEXT, PRIMARY KEY(day,id));
        INSERT OR IGNORE INTO record_snapshots SELECT day,id,kind,updated,body FROM records;
        CREATE TABLE IF NOT EXISTS archive_dirty (day TEXT PRIMARY KEY, revision INTEGER);
        INSERT OR IGNORE INTO archive_dirty SELECT DISTINCT day,1 FROM record_snapshots;
        CREATE INDEX IF NOT EXISTS records_day_updated ON records(day,updated);
        ''')
    defaults = {'name': config.SETTINGS['name'], 'morning': config.SETTINGS['morning'], 'evening': config.SETTINGS['evening'], 'night': '23:00', 'schedule_enabled': config.SETTINGS['schedule_enabled'],
                'auto_night': False, 'night_mode': 'manual_copy', 'notify_feishu': False, 'notification_chat': '',
                'sync_minutes': 10}
    if get('settings') is None:
        put('settings', defaults)
    settings=get('settings')
    if not get('planning_schedule_v1'):
        put('planning_schedule_v1',True)
    settings.pop('night_limit',None)
    settings.update(auto_night=False,night_mode='manual_copy');put('settings',settings)
    # Old queues are no longer executable; historical results remain available.
    for task in all_tasks():
        if task.get('queued'):task['queued']=False;save_task(task)
    if not get('planning_store_v1'):
        with connect() as c:plans=c.execute("SELECT value FROM kv WHERE key LIKE 'plan:%'").fetchall()
        for row in plans:
            plan=json.loads(row[0]);day=plan.get('day',today())
            for kind,key in [('night','night_recommendations'),('risk','risks')]:
                save_planning_batch(kind,plan.get(key,[]),day)
        put('planning_store_v1',True)
    # A process interrupted during execution never silently becomes successful.
    with connect() as c:
        for r in c.execute("SELECT id,body FROM runs WHERE status='running'").fetchall():
            b = json.loads(r['body']); b.update(status='interrupted', finished=now(), error='后台重启，执行结果未确认；可手动重新运行。')
            c.execute('UPDATE runs SET status=?,body=? WHERE id=?', ('interrupted', json.dumps(b, ensure_ascii=False), r['id']))

def get(key, default=None):
    with connect() as c:
        r = c.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
    return json.loads(r[0]) if r else default

def put(key, value):
    with connect() as c:
        c.execute('INSERT OR REPLACE INTO kv VALUES (?,?)', (key, json.dumps(value, ensure_ascii=False)))

def event(kind, title, detail=''):
    with connect() as c:
        c.execute('INSERT INTO events(created,kind,title,detail) VALUES (?,?,?,?)', (now(), kind, clean(title), clean(detail)))

def records(day=None):
    with connect() as c:
        rows = c.execute('SELECT body FROM records WHERE day=? ORDER BY updated DESC', (day or today(),)).fetchall()
    return [v for r in rows if not (v:=json.loads(r[0])).get('superseded_by_api_job')]

def save_record(record):
    with connect() as c:
        previous=c.execute('SELECT day FROM records WHERE id=?',(record['id'],)).fetchone()
        # Keep per-day snapshots before a Codex chat advances to another day.
        c.execute('''INSERT OR REPLACE INTO record_snapshots SELECT day,id,kind,updated,body FROM records WHERE id=?
            AND NOT EXISTS (SELECT 1 FROM purged_items WHERE kind='record' AND id=?)''',(record['id'],record['id']))
        c.execute('''INSERT OR REPLACE INTO records SELECT ?,?,?,?,?
            WHERE NOT EXISTS (SELECT 1 FROM purged_items WHERE kind='record' AND id=?)''',
            (record['id'], record['kind'], record['day'], record['updated'], json.dumps(record, ensure_ascii=False),record['id']))
        c.execute('''INSERT OR REPLACE INTO record_snapshots SELECT ?,?,?,?,?
            WHERE NOT EXISTS (SELECT 1 FROM purged_items WHERE kind='record' AND id=?)''',
            (record['day'],record['id'],record['kind'],record['updated'],json.dumps(record,ensure_ascii=False),record['id']))
        for day in {record['day'],previous[0] if previous else record['day']}:
            c.execute('''INSERT INTO archive_dirty SELECT ?,1 WHERE NOT EXISTS (SELECT 1 FROM purged_items WHERE kind='record' AND id=?)
                ON CONFLICT(day) DO UPDATE SET revision=revision+1''',(day,record['id']))

def tasks(day=None):
    with connect() as c:
        rows = c.execute('SELECT body FROM tasks WHERE day=?', (day or today(),)).fetchall()
    return [json.loads(r[0]) for r in rows]

def task(task_id):
    with connect() as c:
        row=c.execute('SELECT body FROM tasks WHERE id=?',(task_id,)).fetchone()
    return json.loads(row[0]) if row else None

def all_tasks():
    with connect() as c:
        rows=c.execute('SELECT body FROM tasks ORDER BY day DESC').fetchall()
    return [json.loads(r[0]) for r in rows]

def todos(day=None):
    day=day or today()
    return [t for t in all_tasks() if t.get('origin')=='user' and not t.get('deleted')
            and (t['status']!='done' or (t.get('completed_at') or t['day'])[:10]==day)]

def intentions(day=None):
    items=[t for t in tasks(day) if t.get('origin')!='user' and t['status']!='done'
           and not (t.get('dismissed') or t.get('stale') or t.get('deleted'))]
    return sorted(items,key=lambda t:(t.get('rank',99),{'high':0,'medium':1,'low':2}.get(t.get('priority'),2)))[:3]

def night_work():
    items=active_planning('night')
    closed={normalized_title(t['title']) for t in all_tasks() if t.get('origin')!='user'
            and (t.get('status')=='done' or t.get('dismissed') or t.get('deleted'))}
    return [t for t in items if normalized_title(t.get('intention_title') or t['title']) not in closed][:3]

def normalized_title(title):
    return re.sub(r'[^\w\u4e00-\u9fff]','',str(title).lower())

def unfinished():
    with connect() as c:
        rows=c.execute('SELECT body FROM tasks ORDER BY day DESC').fetchall()
    return [t for r in rows if (t:=json.loads(r[0]))['status']!='done'
            and not (t.get('deleted') or t.get('dismissed') or t.get('stale'))]

def evidence_records(ids):
    if not ids:return []
    with connect() as c:
        rows=c.execute('SELECT body FROM records WHERE id IN ('+','.join('?' for _ in ids)+')',list(ids)).fetchall()
    return [json.loads(r[0]) for r in rows]

def save_task(task,preserve_manual=False):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if preserve_manual:
            row=c.execute('SELECT body FROM tasks WHERE id=?',(task['id'],)).fetchone()
            if row:
                old=json.loads(row[0])
                if old.get('deleted') or old.get('dismissed') or (old.get('manual_status') and old.get('status')=='done'):return False
                if old.get('manual_status'):
                    for key in ('status','manual_status','completed_at'):task[key]=old.get(key)
        result=c.execute('''INSERT OR REPLACE INTO tasks SELECT ?,?,?
            WHERE NOT EXISTS (SELECT 1 FROM purged_items WHERE kind='task' AND id=?)''',
            (task['id'], task['day'], json.dumps(task, ensure_ascii=False),task['id']))
        return bool(result.rowcount)

def planning_id(kind,title):
    if kind not in ('night','risk'):raise ValueError('无效类别')
    return kind+':'+hashlib.sha256(normalized_title(title).encode()).hexdigest()[:16]

def planning_body(kind,item,day):
    return {**item,'id':planning_id(kind,item['title']),'kind':kind,'day':day,
            'role':'night_recommendation' if kind=='night' else 'forecast','status':'todo','created':item.get('created') or now()}

def active_planning(kind,day=None):
    day=day or today();key='night_recommendations' if kind=='night' else 'risks'
    plan=get('plan:'+day) or {};purged=purged_ids(kind)
    with connect() as c:stored={r['id']:json.loads(r['body']) for r in c.execute('SELECT id,body FROM planning_items WHERE kind=?',(kind,))}
    candidates={r['id']:r for r in (planning_body(kind,item,day) for item in plan.get(key,[]))}
    candidates.update({id:item for id,item in stored.items() if item.get('day')==day})
    out=[]
    for id,item in candidates.items():
        current=stored.get(id,item)
        if id in purged or current.get('deleted') or current.get('stale') or current.get('status')=='done':continue
        out.append(current)
    return out[:3 if kind=='night' else 2]

def planning_item(item_id):
    with connect() as c:row=c.execute('SELECT body FROM planning_items WHERE id=?',(item_id,)).fetchone()
    if row:return json.loads(row[0])
    return next((t for kind in ('night','risk') for t in active_planning(kind) if t['id']==item_id),None)

def save_planning_batch(kind,items,day=None):
    day=day or today();keep=set()
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        for item in items:
            body=planning_body(kind,item,day);id=body['id']
            if c.execute('SELECT 1 FROM purged_items WHERE kind=? AND id=?',(kind,id)).fetchone():continue
            row=c.execute('SELECT body FROM planning_items WHERE id=?',(id,)).fetchone()
            if row:
                old=json.loads(row[0])
                if old.get('deleted') or old.get('status')=='done':continue
                body['created']=old.get('created',body['created'])
            body['stale']=False;keep.add(id)
            c.execute('INSERT OR REPLACE INTO planning_items VALUES (?,?,?,?)',(id,kind,day,json.dumps(body,ensure_ascii=False)))
        for row in c.execute('SELECT id,body FROM planning_items WHERE kind=? AND day=?',(kind,day)).fetchall():
            if row['id'] not in keep:
                old=json.loads(row['body']);old['stale']=True
                c.execute('UPDATE planning_items SET body=? WHERE id=?',(json.dumps(old,ensure_ascii=False),row['id']))
    return [t for t in active_planning(kind,day) if t['id'] in keep]

def set_planning_status(item_id,status):
    if status not in ('todo','done'):raise ValueError('无效状态')
    item=planning_item(item_id)
    if not item or item.get('kind')!='night' or item.get('deleted'):raise ValueError('夜间推荐不存在')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT body FROM planning_items WHERE id=?',(item_id,)).fetchone()
        if row:item=json.loads(row[0])
        if item.get('deleted') or c.execute("SELECT 1 FROM purged_items WHERE kind='night' AND id=?",(item_id,)).fetchone():raise ValueError('推荐已删除')
        item.update(status=status,manual_status=True,completed_at=now() if status=='done' else None,updated=now(),stale=False)
        if status=='todo':item['day']=today()
        c.execute('INSERT OR REPLACE INTO planning_items VALUES (?,?,?,?)',(item_id,'night',item['day'],json.dumps(item,ensure_ascii=False)))
    return item

def delete_work_item(kind,item_id):
    if kind not in ('task','night','risk') or not isinstance(item_id,str):raise ValueError('无效条目')
    item=task(item_id) if kind=='task' else planning_item(item_id)
    if not item or (kind!='task' and item.get('kind')!=kind):raise ValueError('条目不存在')
    table='tasks' if kind=='task' else 'planning_items'
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM purged_items WHERE kind=? AND id=?',(kind,item_id)).fetchone():raise ValueError('条目已完全删除')
        row=c.execute(f'SELECT body FROM {table} WHERE id=?',(item_id,)).fetchone()
        if row:item=json.loads(row[0])
        item.update(deleted=True,deleted_at=now(),updated=now(),queued=False)
        if kind=='task':
            if item.get('origin')!='user':item['dismissed']=True
            c.execute('INSERT OR REPLACE INTO tasks VALUES (?,?,?)',(item_id,item['day'],json.dumps(item,ensure_ascii=False)))
        else:c.execute('INSERT OR REPLACE INTO planning_items VALUES (?,?,?,?)',(item_id,kind,item['day'],json.dumps(item,ensure_ascii=False)))
    return {'id':item_id,'kind':kind,'deleted':True}

def runs():
    with connect() as c:
        rows = c.execute('SELECT body FROM runs ORDER BY created DESC LIMIT 80').fetchall()
    return [json.loads(r[0]) for r in rows]

def save_run(run):
    with connect() as c:
        c.execute('''INSERT OR REPLACE INTO runs SELECT ?,?,?,?
            WHERE NOT EXISTS (SELECT 1 FROM purged_items WHERE kind='run' AND id=?)''',
            (run['id'], run['created'], run['status'], json.dumps(run, ensure_ascii=False),run['id']))

def purged_ids(kind='record'):
    with connect() as c:
        return {r[0] for r in c.execute('SELECT id FROM purged_items WHERE kind=?',(kind,))}

def run(run_id):
    with connect() as c:
        row=c.execute('SELECT body FROM runs WHERE id=?',(run_id,)).fetchone()
    return json.loads(row[0]) if row else None

# Completed categories are disjoint. Opening the archive only reads counts/dates;
# entry bodies are requested after the user chooses a category (and date).
COMPLETED = {
    'work': ('tasks', 'task', "json_extract(body,'$.status')='done' AND (json_extract(body,'$.origin')='user' OR json_extract(body,'$.manual_status')=1) AND NOT coalesce(json_extract(body,'$.deleted'),0)", "coalesce(json_extract(body,'$.completed_at'),day)"),
    'night': ('runs', 'run', "json_extract(body,'$.kind')='night' AND status='success'", 'created'),
    'date': ('records', 'record', "(kind='memory' OR (kind='codex' AND json_extract(body,'$.has_result')=1)) AND coalesce(json_extract(body,'$.superseded_by_api_job'),'') IN ('',0)", 'updated'),
}

def completed_source(category):
    if category!='night':return COMPLETED[category]
    return ("""(SELECT id,created,body FROM runs WHERE json_extract(body,'$.kind')='night' AND status='success'
        UNION ALL SELECT id,json_extract(body,'$.completed_at') AS created,body FROM planning_items
        WHERE kind='night' AND json_extract(body,'$.status')='done' AND NOT coalesce(json_extract(body,'$.deleted'),0))""",
        'run','1=1','created')

def completed(category='',day='',query='',offset=0,limit=50):
    if category and category not in COMPLETED:raise ValueError('无效的已完成分类')
    if day:
        if datetime.strptime(day,'%Y-%m-%d').date().isoformat()!=day:raise ValueError('无效日期')
    query=str(query)[:200];offset=max(0,int(offset));limit=max(1,min(100,int(limit)))
    search=" AND instr(lower(coalesce(json_extract(body,'$.title'),'') || ' ' || coalesce(json_extract(body,'$.text'),'') || ' ' || coalesce(json_extract(body,'$.summary'),'') || ' ' || coalesce(json_extract(body,'$.result'),'')),lower(?))>0"
    with connect() as c:
        if not category:
            counts={};dates=[]
            for key in COMPLETED:
                table,_,where,_=completed_source(key)
                if key=='date':where+=f" AND day>='{window_start()}' AND day<='{today()}'"
                counts[key]=c.execute(f'SELECT count(*) FROM {table} WHERE {where}'+search,(query,)).fetchone()[0]
                if key=='date':
                    dates=[dict(r) for r in c.execute(f'SELECT day,count(*) AS count FROM records WHERE {where}'+search+' GROUP BY day ORDER BY day DESC',(query,))]
            return {'counts':counts,'dates':dates}
        if category=='date' and not day:return {'items':[],'total':0}
        table,kind,where,order=completed_source(category);params=[]
        if category=='date':where+=' AND day=? AND day>=? AND day<=?';params.extend([day,window_start(),today()])
        where+=search;params.append(query)
        total=c.execute(f'SELECT count(*) FROM {table} WHERE {where}',params).fetchone()[0]
        rows=c.execute(f'SELECT body FROM {table} WHERE {where} ORDER BY {order} DESC,id LIMIT ? OFFSET ?',params+[limit,offset]).fetchall()
    return {'items':[{**(item:=json.loads(r[0])),'_completed_kind':'night' if item.get('role')=='night_recommendation' else kind} for r in rows],'total':total}

def delete_completed(kind,item_id):
    category={'task':'work','run':'night','night':'night','record':'date'}.get(kind)
    if not category or not isinstance(item_id,str):raise ValueError('无效的已完成条目')
    table,_,where,_=COMPLETED[category]
    if kind=='night':table='planning_items';where="kind='night' AND json_extract(body,'$.status')='done' AND NOT coalesce(json_extract(body,'$.deleted'),0)"
    days=[]
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute(f'SELECT body FROM {table} WHERE id=? AND {where}',(item_id,)).fetchone()
        if not row:raise ValueError('条目不存在或尚未完成，请刷新后重试')
        if kind=='run':
            # Delete only the directory owned by this run, never artifact_dir from JSON.
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',item_id):raise ValueError('产物路径无效')
            root=DATA/'runs';folder=root/item_id
            if root.is_symlink() or folder.is_symlink() or folder.resolve().parent!=root.resolve():raise ValueError('产物路径无效')
            if folder.exists():shutil.rmtree(folder)
        c.execute('INSERT OR IGNORE INTO purged_items VALUES (?,?)',(kind,item_id))
        c.execute(f'DELETE FROM {table} WHERE id=?',(item_id,))
        if kind=='record':
            days=[r[0] for r in c.execute('SELECT day FROM record_snapshots WHERE id=?',(item_id,))]
            c.execute('DELETE FROM record_snapshots WHERE id=?',(item_id,))
            for day in days:c.execute('INSERT INTO archive_dirty VALUES (?,1) ON CONFLICT(day) DO UPDATE SET revision=revision+1',(day,))
    if days:
        import archives
        archives.write_days(days)
    return {'deleted':True,'kind':kind,'id':item_id}

def window_start():
    from datetime import date,timedelta
    return (date.fromisoformat(today())-timedelta(days=4)).isoformat()

def related_flags(records):
    me=get('feishu_self') or {'name':get('settings',{}).get('name','')};cache=get('feishu_chat_cache') or {}
    def own(r):
        return bool((me.get('open_id') and r.get('sender_id')==me['open_id']) or
                    (me.get('name') and r.get('sender_name')==me['name']))
    with connect() as c:
        rows=c.execute("SELECT body FROM records WHERE kind='feishu' AND (json_extract(body,'$.sender_id')=? OR json_extract(body,'$.sender_name')=?)",(me.get('open_id',''),me.get('name',''))).fetchall()
    mine=[json.loads(r[0]) for r in rows]
    threads={(r.get('chat_id'),r['thread_id']) for r in mine if r.get('thread_id')}
    message_ids={r['message_id'] for r in mine if r.get('message_id')}
    out=[]
    for r in records:
        text=r.get('text','');chat_type=r.get('chat_type') or cache.get(r.get('chat_id'),{}).get('chat_type')
        mentioned=bool(me.get('name') and '@'+me['name'] in text) or bool(me.get('open_id') and me['open_id'] in json.dumps(r.get('mentions',[])))
        related=(r['kind'] in ('codex','memory') or chat_type=='p2p' or own(r) or mentioned or
                 (bool(r.get('thread_id')) and (r.get('chat_id'),r['thread_id']) in threads) or
                 any(r.get(k) in message_ids for k in ('parent_id','root_id')))
        out.append({**r,'related_to_user':bool(related)})
    return out

def visible_records(kind='all',related=False,query='',offset=0,limit=50,range_name='five'):
    if kind not in ('all','codex','memory','feishu'):raise ValueError('无效来源')
    offset=max(0,int(offset));limit=max(1,min(100,int(limit)))
    start=today() if range_name=='today' else window_start()
    with connect() as c:
        rows=c.execute('SELECT body FROM records WHERE day>=? AND day<=? ORDER BY updated DESC,id',(start,today())).fetchall()
    items=related_flags([v for r in rows if not (v:=json.loads(r[0])).get('superseded_by_api_job') and (kind=='all' or v['kind']==kind)])
    query=str(query).casefold()[:200]
    items=[r for r in items if (not related or r['related_to_user']) and (not query or query in (r['title']+' '+r.get('text','')+' '+r.get('summary','')).casefold())]
    return {'items':items[offset:offset+limit],'total':len(items),'start_day':start,'end_day':today(),'days':5}
