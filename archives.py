"""Daily local Markdown retention. The five-day rule only limits UI visibility."""
import json
import os
import re
import threading
import sqlite3
from datetime import date

import storage as db

LOCK=threading.RLock()
NAMES={'codex':'Codex 会话','memory':'Codex 记忆','feishu':'飞书消息'}

def valid_day(day):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(day)) or date.fromisoformat(day).isoformat()!=day:raise ValueError('无效归档日期')
    return day

def write_days(days=None):
    with LOCK:
        with db.connect() as c:
            if days is None:days=[r[0] for r in c.execute('SELECT day FROM archive_dirty ORDER BY day')]
        folder=db.DATA/'archives';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        for day in set(days):
            valid_day(day)
            with db.connect() as c:
                revision=c.execute('SELECT revision FROM archive_dirty WHERE day=?',(day,)).fetchone()
                rows=c.execute('SELECT body FROM record_snapshots WHERE day=? ORDER BY updated,id',(day,)).fetchall()
            records=[v for r in rows if not (v:=json.loads(r[0])).get('superseded_by_api_job')]
            lines=[f'# {day} 记忆与消息','',f'共 {len(records)} 条记录。按北京时间日期保存；网页仅显示近五天，历史继续保留。','']
            for r in records:
                lines.extend([f"## {r['title']}",'',f"来源：{NAMES.get(r['kind'],r['kind'])} | 时间：{r.get('updated','')} | ID：{r['id']}",''])
                if r.get('messages'):
                    for m in r['messages']:lines.extend([f"### {'用户' if m.get('role')=='user' else '助手'} · {m.get('time','')}",'',m.get('text',''),''])
                else:lines.extend([r.get('text',''),''])
                if r.get('summary') and r.get('summary')!=r.get('text'):lines.extend(['### 摘要','',r['summary'],''])
            text=db.clean('\n'.join(lines));path=folder/(day+'.md')
            if not path.exists() or path.read_text()!=text:
                temp=path.with_suffix('.tmp');temp.write_text(text);os.chmod(temp,0o600);temp.replace(path)
            if revision:
                with db.connect() as c:c.execute('DELETE FROM archive_dirty WHERE day=? AND revision=?',(day,revision[0]))
        return list_files()

def list_files():
    folder=db.DATA/'archives'
    return [{'day':p.stem,'name':p.name,'bytes':p.stat().st_size} for p in sorted(folder.glob('????-??-??.md'),reverse=True)]

def read(day):
    valid_day(day);path=db.DATA/'archives'/(day+'.md')
    if not path.is_file():raise FileNotFoundError('归档不存在')
    return path.read_bytes()

def recover_local_backups():
    """Recover already-collected daily versions without changing live records."""
    recovered=0;purged=db.purged_ids()
    for path in sorted((db.DATA/'backups').glob('*/before.sqlite')):
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as source:
            rows=source.execute('SELECT day,id,kind,updated,body FROM records').fetchall()
        with db.connect() as c:
            for row in rows:
                if row[1] in purged:continue
                valid_day(row[0])
                count=c.execute('INSERT OR IGNORE INTO record_snapshots VALUES (?,?,?,?,?)',row).rowcount;recovered+=count
                if count:c.execute('INSERT INTO archive_dirty VALUES (?,1) ON CONFLICT(day) DO UPDATE SET revision=revision+1',(row[0],))
    return recovered
