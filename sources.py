import json
import os
import config
import sqlite3
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import storage as db

HOME = Path.home()
CODEX = config.path(config.SETTINGS['codex_home'])
LARK = config.executable('lark_bin')
TITLES = {}

def internal_chat(row):
    if row['id'] in config.SETTINGS['excluded_thread_ids']:return True
    cwd=Path(row['cwd']).resolve()
    return cwd.is_relative_to(db.DATA.resolve()) or any(p in str(cwd).replace('\\','/') for p in ('/workworld/data/','/workstation/data/'))

def thread_rows(start,end):
    errors=[]
    for path in sorted(CODEX.glob('state_*.sqlite'),key=lambda p:p.stat().st_mtime,reverse=True):
        try:
            with ro(path) as c:return c.execute('SELECT id,title,cwd,updated_at,rollout_path FROM threads WHERE updated_at>=? AND updated_at<? ORDER BY updated_at DESC',(int(start.timestamp()),int(end.timestamp()))).fetchall()
        except sqlite3.Error as ex:errors.append(str(ex))
    if errors:raise RuntimeError('Unsupported Codex thread database schema: '+errors[0])
    # CLI-only installs may have rollouts before a thread database exists.
    rows=[]
    for path in (CODEX/'sessions').rglob('*.jsonl'):
        updated=path.stat().st_mtime
        if not start.timestamp()<=updated<end.timestamp():continue
        try:
            with path.open() as f:meta=json.loads(f.readline()).get('payload',{})
            if not meta.get('id') or not meta.get('cwd'):continue
            rows.append({'id':meta['id'],'title':meta.get('title','Codex 会话'),'cwd':meta['cwd'],'updated_at':int(updated),'rollout_path':str(path)})
        except (OSError,ValueError):continue
    return rows

def ro(path):
    c = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True, timeout=4, factory=db.ClosingConnection)
    c.row_factory = sqlite3.Row
    return c

def day_range(day):
    start = datetime.fromisoformat(day).replace(tzinfo=db.TZ)
    return start, start + timedelta(days=1)

def same_day(ts, day):
    try:
        return datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone(db.TZ).date().isoformat() == day
    except (ValueError, AttributeError):
        return False

def read_messages(path, day, since=None):
    messages = []
    completed = []
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                try: x = json.loads(line)
                except ValueError: continue
                if day and not same_day(x.get('timestamp', ''), day): continue
                if since:
                    try:
                        if datetime.fromisoformat(x.get('timestamp','').replace('Z','+00:00'))<since:continue
                    except ValueError:continue
                p = x.get('payload', {})
                if x.get('type') == 'event_msg' and p.get('type') in ('task_complete', 'task_completed'):
                    if p.get('last_agent_message'): completed.append(db.clean(p['last_agent_message']))
                if x.get('type') != 'response_item' or p.get('type') != 'message': continue
                role = p.get('role')
                if role not in ('user', 'assistant'): continue
                if role == 'assistant' and p.get('phase') not in ('final_answer', 'final', 'commentary'): continue
                text = '\n'.join(v.get('text', '') for v in p.get('content', []) if v.get('type') in ('input_text', 'output_text', 'text'))
                if text.strip().startswith(('<environment_context>', '<external_codex_apps_open_page>', '<heartbeat>\n  <automation_id>')) and role == 'user': continue
                if '# My request:' in text: text = text.split('# My request:', 1)[1]
                if '## My request:' in text: text = text.split('## My request:', 1)[1]
                messages.append({'role': role, 'phase': p.get('phase', ''), 'text': db.clean(text)[:14000], 'time': x['timestamp']})
    except OSError:
        return [], False
    for t in completed[-2:]:
        if not any(t[:100] in m['text'] for m in messages):
            messages.append({'role': 'assistant', 'phase': 'final_answer', 'text': t[:14000], 'time': ''})
    finals = [m for m in messages if m['phase'] in ('final_answer', 'final')]
    user = [m for m in messages if m['role'] == 'user']
    commentary = [m for m in messages if m['phase'] == 'commentary']
    return (user[-3:] + finals[-3:] + commentary[-1:]), bool(completed or finals)

def recent_codex(days=7):
    """Read every recently active chat, keeping its latest requests and results."""
    start,end=day_range(db.today());start-=timedelta(days=days-1)
    rows=thread_rows(start,end)
    records=[];purged=db.purged_ids()
    for row in rows:
        if 'thread:'+row['id'] in purged:continue
        if internal_chat(row):continue
        messages,done=read_messages(row['rollout_path'],None,since=start)
        updated=datetime.fromtimestamp(row['updated_at'],db.TZ).isoformat()
        record={'id':'thread:'+row['id'],'kind':'codex','day':updated[:10],'updated':updated,
                'title':TITLES.get(row['id']) or db.clean(row['title']).split('\n')[0][:80],
                'thread_id':row['id'],'cwd':row['cwd'],'path':row['rollout_path'],'messages':messages,
                'text':'\n\n'.join(m['text'] for m in messages)[-10000:],'has_result':done,
                'coverage':'最近 7 天全部活跃 Codex 会话的近期请求与结果；不读取内部思考和工具输出'}
        records.append(record)
        # Keep source details available when an intention cites an older chat.
        if record['day']!=db.today() or not db.evidence_records([record['id']]):db.save_record(record)
    return records

def sync_codex(day):
    start, end = day_range(day)
    counts = {'threads': 0, 'memories': 0, 'read_errors': 0}
    purged=db.purged_ids()
    rows=thread_rows(start,end)
    for r in rows:
        if 'thread:'+r['id'] in purged:continue
        # Skip this workbench's CLI jobs; otherwise each summary recursively summarizes itself.
        if internal_chat(r): continue
        messages, done = read_messages(r['rollout_path'], day)
        title = TITLES.get(r['id']) or next((m['text'].strip().split('\n')[0][:65] for m in messages if m['role'] == 'user'), db.clean(r['title']).split('\n')[0][:65])
        db.save_record({'id': 'thread:' + r['id'], 'kind': 'codex', 'day': day, 'updated': datetime.fromtimestamp(r['updated_at'], db.TZ).isoformat(),
            'title': title, 'thread_id': r['id'], 'cwd': r['cwd'], 'path': r['rollout_path'], 'messages': messages,
            'text': '\n\n'.join(m['text'] for m in messages if m['role'] == 'assistant')[-19000:], 'has_result': done,
            'coverage': '当日用户消息与助手结果；不读取工具输出和思考内容'})
        counts['threads'] += 1
        if not messages: counts['read_errors'] += 1
    rows=[]
    if config.SETTINGS['read_codex_memories']:
        for path in sorted(CODEX.glob('memories_*.sqlite'),key=lambda p:p.stat().st_mtime,reverse=True):
            try:
                with ro(path) as c:rows=c.execute('SELECT * FROM stage1_outputs WHERE (generated_at>=? AND generated_at<?) OR (source_updated_at>=? AND source_updated_at<?)',(int(start.timestamp()),int(end.timestamp()),int(start.timestamp()),int(end.timestamp()))).fetchall()
                break
            except sqlite3.Error:counts['memory_schema_unavailable']=True
    for r in rows:
        if 'memory:'+r['thread_id']+':'+day in purged:continue
        db.save_record({'id': 'memory:' + r['thread_id'] + ':' + day, 'kind': 'memory', 'day': day, 'updated': datetime.fromtimestamp(r['generated_at'], db.TZ).isoformat(),
            'title': TITLES.get(r['thread_id'], r['rollout_slug'] or 'Codex 记忆'), 'thread_id': r['thread_id'],
            'text': db.clean(r['raw_memory']), 'summary': db.clean(r['rollout_summary']),
            'source_updated': datetime.fromtimestamp(r['source_updated_at'], db.TZ).isoformat(),
            'coverage': '今天生成或来源今天更新的记忆；原任务日期可能更早'})
        counts['memories'] += 1
    return counts

def lark_env():
    return config.feishu_env(db.DATA)

def lark(args, timeout=45):
    p = subprocess.run([LARK, *args], env=lark_env(), capture_output=True, text=True, timeout=timeout)
    try: value=json.loads(p.stdout or p.stderr)
    except ValueError:raise RuntimeError('飞书 CLI 未返回有效 JSON')
    if p.returncode or value.get('ok') is False:raise RuntimeError(db.clean(value.get('error',{}).get('message','飞书读取失败')))
    return value

def sync_feishu(day):
    import feishu
    connection=feishu.connection()
    if connection.get('ready'):
        old=db.get('feishu_crawl') or {}
        if old.get('status')!='paused':feishu.start('today',resume=old.get('status') in ('partial','error','interrupted'),mode=connection['mode'])
        job=feishu.public_job()
        status={'synced_at':db.now(),'identity':connection['mode'],'coverage':connection['message'],
                'chats':job.get('chats_total',0),'messages':len([r for r in db.records(day) if r['kind']=='feishu']),
                'complete':job.get('status')=='complete','status':job.get('status','pending'),'errors':job.get('errors',[])}
    else:status={'synced_at':db.now(),'identity':'user','coverage':connection['message'],'chats':0,'messages':0,'complete':False,'status':'needs_setup','errors':[]}
    db.put('feishu_status',status);return status

def sync_all():
    day = db.today(); status={'at': db.now(), 'day': day}
    try: status['codex'] = sync_codex(day) if config.SETTINGS['codex_enabled'] else {'disabled':True}
    except Exception as e: status['codex'] = {'error': db.clean(str(e))[:300]}
    status['feishu'] = sync_feishu(day) if config.SETTINGS['feishu_enabled'] else {'disabled':True,'messages':0}
    if config.SETTINGS.get('applications_enabled'):
        import applications
        try:status['applications']=applications.sync_local()
        except Exception as e:status['applications']={'error':db.clean(str(e))[:300]}
    import archives
    status['archives']={'days':len(archives.write_days())}
    db.put('last_sync', status)
    db.event('sync', '已同步工作记录', f"Codex {status.get('codex', {}).get('threads', 0)} 个会话 · {status.get('codex', {}).get('memories', 0)} 条记忆"+(f" · 飞书 {status['feishu']['messages']} 条消息" if config.SETTINGS['feishu_enabled'] else ' · 飞书已关闭'))
    return status
