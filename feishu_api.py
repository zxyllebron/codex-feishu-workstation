"""Read-only bulk collection using the endpoints used by the official Feishu CLI."""
import json
import re
import time
from collections import Counter
from datetime import datetime

import storage as db
import feishu as f

ALLOWED = {
    ('POST','/open-apis/im/v1/messages/search'),
    ('GET','/open-apis/im/v1/messages/mget'),
    ('POST','/open-apis/im/v1/chats/batch_query'),
    ('GET','/open-apis/authen/v1/user_info'),
}

def raw(method,path,params=None,data=None):
    if (method,path) not in ALLOWED:raise ValueError('个人飞书连接仅允许消息与会话读取接口')
    args=['api',method,path,'--as','user']
    if params is not None:args+=['--params',json.dumps(params,ensure_ascii=False)]
    if data is not None:args+=['--data',json.dumps(data,ensure_ascii=False)]
    return f.call(args,'user',timeout=90)

def content_text(message):
    body=(message.get('body') or {}).get('content') or message.get('content') or ''
    try:obj=json.loads(body) if isinstance(body,str) else body
    except ValueError:obj=body
    pieces=[]
    def walk(v):
        if isinstance(v,str):pieces.append(v)
        elif isinstance(v,list):
            for item in v:walk(item)
        elif isinstance(v,dict):
            if isinstance(v.get('json_card'),str):
                try:walk(json.loads(v['json_card']))
                except ValueError:walk(v['json_card'])
                return
            tag=v.get('tag')
            if tag=='at':pieces.append('@'+str(v.get('user_name') or v.get('user_id') or '成员'));return
            if tag in ('img','image'):pieces.append('[图片]');return
            if tag in ('button','action'):return
            # Content-bearing fields only; do not include card actions or metadata.
            for key in ('title','text','content','elements','body','header','zh_cn','en_us','description','columns','fields','rows','cells','i18n_elements','property','children'):
                if key in v:walk(v[key])
            if not any(k in v for k in ('title','text','content','elements','body','header','zh_cn','en_us','description')):
                if 'file_name' in v:pieces.append('[文件] '+str(v['file_name']))
                elif 'image_key' in v:pieces.append('[图片]')
                elif 'file_key' in v:pieces.append('[音视频或附件]')
    walk(obj)
    text='\n'.join(pieces).strip()
    for mention in message.get('mentions') or []:
        if mention.get('key') and mention.get('name'):text=text.replace(mention['key'],'@'+mention['name'])
    if not text and message.get('msg_type') in ('interactive','post'):
        text='[保留原始卡片结构] '+json.dumps(obj,ensure_ascii=False)
    if not text:text={'image':'[图片]','media':'[视频]','audio':'[音频]','merge_forward':'[合并转发，子消息未展开]','file':'[文件]'}.get(message.get('msg_type'),'[非文本消息]')
    return text

def own_user(refresh=False):
    cached=db.get('feishu_self') or {}
    if cached and not refresh:return cached
    try:
        value=raw('GET','/open-apis/authen/v1/user_info').get('data') or {}
        cached={k:value.get(k) for k in ('name','open_id')};db.put('feishu_self',cached)
    except Exception:cached={'name':db.get('settings',{}).get('name','')}
    return cached

def chat_context(ids, metas, messages):
    cache=db.get('feishu_chat_cache') or {}
    me=own_user()
    missing=[cid for cid in ids if cid not in cache or cache[cid].get('name') in ('自己','飞书会话','私聊') or (cache[cid].get('chat_type')=='p2p' and not cache[cid].get('partner_id'))]
    if missing:
        result=raw('POST','/open-apis/im/v1/chats/batch_query',params={'user_id_type':'open_id'},data={'chat_ids':missing}).get('data') or {}
        for item in result.get('items',[]):
            cid=item['chat_id'];is_p2p=any(m.get('chat_id')==cid and m.get('is_p2p_chat') for m in metas)
            cache[cid]={'chat_id':cid,'name':item.get('name') or '', 'chat_type':'p2p' if is_p2p or item.get('chat_mode')=='p2p' else 'group', 'partner_id':item.get('p2p_target_id')}
    for cid in ids:
        chat=cache.setdefault(cid,{'chat_id':cid,'name':'','chat_type':'unknown'})
        if not chat.get('name') or chat.get('name') in ('自己','飞书会话','私聊'):
            peers=[m.get('sender',{}).get('sender_name') for m in messages if m.get('chat_id')==cid and m.get('sender',{}).get('id')!=me.get('open_id')]
            chat['name']=(me.get('name') if chat.get('partner_id')==me.get('open_id') else None) or next((n for n in peers if n and n!=me.get('name')),None) or ('私聊' if chat.get('chat_type')=='p2p' else '飞书会话')
        # Reconcile browser aliases before matching message positions.
        with db.connect() as c:
            aliases=c.execute("SELECT id,body FROM records WHERE kind='feishu' AND json_extract(body,'$.chat_id') IN (?,?)",('browser:'+chat['name'],cid)).fetchall()
            for row in aliases:
                b=json.loads(row['body']);b['chat_id']=cid;b['title']=chat['name']
                c.execute('UPDATE records SET body=? WHERE id=?',(json.dumps(b,ensure_ascii=False),row['id']))
    db.put('feishu_chat_cache',cache)
    return {cid:cache[cid] for cid in ids}

def archive_browser_snapshot(job):
    # Keep earlier browser evidence recoverable while the verified API snapshot is displayed.
    with db.connect() as c:
        rows=c.execute("SELECT id,body FROM records WHERE kind='feishu' AND json_extract(body,'$.source')='browser' AND updated<=?"+(' AND updated>=?' if job.get('start') else ''),[job['end']]+([job['start']] if job.get('start') else [])).fetchall()
        for row in rows:
            b=json.loads(row['body']);b['superseded_by_api_job']=job['id']
            c.execute('UPDATE records SET body=? WHERE id=?',(json.dumps(b,ensure_ascii=False),row['id']))

def update_status(job):
    status=db.get('feishu_status') or {}
    status.update(synced_at=db.now(),identity='user',coverage='个人用户 API，跨会话检索与批量正文读取，包含话题内消息',
                  chats=job.get('chats_total',0),messages=len([r for r in db.records() if r['kind']=='feishu']),
                  complete=job.get('status')=='complete',status=job.get('status'),errors=job.get('errors',[]))
    db.put('feishu_status',status)

def crawl(job):
    began=time.monotonic()
    try:
        job['status']='searching';job['strategy']='search';job['coverage']='个人用户 API 跨会话检索，包括话题内消息；仅只读接口'
        f.persist(job)
        while True:
            if f.STOP.is_set():job['status']='paused';return
            params={'page_size':50}
            if job.get('search_token'):params['page_token']=job['search_token']
            time_range={'end_time':job['end']}
            if job.get('start'):time_range['start_time']=job['start']
            result=raw('POST','/open-apis/im/v1/messages/search',params=params,data={'query':'','filter':{'time_range':time_range}})
            rows,token,more=f.page(result,'items')
            metas=[r.get('meta_data') or {} for r in rows]
            ids=list(dict.fromkeys(m.get('message_id') for m in metas if m.get('message_id')))
            if len(ids)!=len(rows):raise RuntimeError('检索结果中存在缺失或重复的消息标识，未标记完整')
            # A page cursor is committed only after every message body is confirmed.
            got=[]
            if ids:
                got=raw('GET','/open-apis/im/v1/messages/mget',params={'message_ids':ids,'with_sender_name':True,'card_msg_content_type':'raw_card_content'}).get('data',{}).get('items',[])
                if set(ids)!={m.get('message_id') for m in got}:raise RuntimeError('本页部分消息正文没有返回，已保留原游标等待重试')
                chats=chat_context(list(dict.fromkeys(m['chat_id'] for m in got)),metas,got)
                for original in got:
                    message=dict(original);message['content']=content_text(original);message.pop('body',None)
                    sender=message.get('sender') or {};sender['name']=sender.get('sender_name') or sender.get('name') or sender.get('id','未知发送者')
                    pos=original.get('thread_message_position')
                    if original.get('thread_id') and pos is not None and str(pos) not in ('','0'):
                        message['message_position']='thread:'+original['thread_id']+':'+str(pos)
                    message['time_precision']='second'
                    if not f.within(job,message):raise RuntimeError('接口返回了所选时间范围外的消息，未标记完整')
                    fresh=message['message_id'] not in job.setdefault('_indexed_ids',[])
                    if fresh:job['_indexed_ids'].append(message['message_id'])
                    saved=f.count_message(job,message,chats[message['chat_id']],'user')
                    if fresh and not saved:job['excluded_messages']=job.get('excluded_messages',0)+1
                    job['indexed_messages']=len(job['_indexed_ids'])
                    cid=message['chat_id']
                    if cid not in job.setdefault('collected_chats',[]):job['collected_chats'].append(cid)
                    if message.get('thread_id') and message['thread_id'] not in job.setdefault('thread_ids',[]):job['thread_ids'].append(message['thread_id'])
            if more and token in job.setdefault('seen_search_tokens',[]):raise RuntimeError('检索分页游标重复，未标记完成')
            if more:job['seen_search_tokens'].append(token)
            job['search_token']=token;job['pages']=job.get('pages',0)+1
            job['chats_total']=len(job.get('collected_chats',[]));job['current_chat']='跨会话批量读取'
            job['elapsed_seconds']=round(time.monotonic()-began,2);f.persist(job);update_status(job)
            if not more:break
        if job.get('indexed_messages',0)!=job.get('messages',0)+job.get('excluded_messages',0):raise RuntimeError('消息索引与保存数量不一致，未标记完整')
        job.update(status='complete',finished_at=db.now(),chats_done=job['chats_total'],completed_chats=job.get('collected_chats',[]),pending_work=[])
        archive_browser_snapshot(job)
        job['export']=write_export(job)
        import archives
        archives.write_days()
        db.put('feishu_last_success',{k:job.get(k) for k in ('id','end','messages','chats_total','pages','elapsed_seconds','export')})
        db.event('sync','个人飞书 API 已完成遍历',f"{job['messages']} 条消息 · {job['chats_total']} 个会话 · {len(job.get('thread_ids',[]))} 个话题 · {job['pages']} 页")
    except Exception as ex:
        job['status']='partial' if job.get('messages') else 'error';job.setdefault('errors',[]).append({'error':db.clean(str(ex))[:350]})
        db.event('error','个人飞书同步未完成',db.clean(str(ex)))
    finally:
        job['elapsed_seconds']=round(time.monotonic()-began,2);f.persist(job);update_status(job);f.LOCK.release()

def render_export(records,range_name,fmt):
    if fmt=='jsonl':return ''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records)
    counts=Counter(r['title'] for r in records)
    lines=['# 飞书消息采集',f'生成时间：{db.now()}',f'范围：{range_name} · {len(records)} 条消息 · {len({r.get("chat_id") for r in records})} 个会话','', '仅只读采集，未在群聊发消息或修改群内容。','', '## 会话索引','']
    lines += [f'- {name}：{count} 条' for name,count in counts.most_common()]
    lines += ['','## 消息记录','']
    for r in reversed(records):
        lines += [f"### {r['updated']} · {r['title']} · {r.get('sender_name','')}",f"消息 ID：{r.get('message_id','')}",'',r['text'],'']
    return '\n'.join(lines)

def export_text(range_name='today',fmt='jsonl'):
    return render_export(f.messages(range_name,limit=1_000_000)['items'],range_name,fmt)

def write_export(job):
    folder=db.DATA/'exports'/'feishu'/job['end'][:10];folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    records=sorted(db.evidence_records(job.get('message_keys',[])),key=lambda r:r['updated'],reverse=True)
    for fmt in ('jsonl','md'):
        path=folder/('messages.'+fmt);temp=path.with_suffix('.tmp');temp.write_text(render_export(records,(job.get('start') or '最早可见历史')+' — '+job['end'],fmt),encoding='utf-8');temp.chmod(0o600);temp.replace(path)
    (folder/'collection.json').write_text(json.dumps({k:job.get(k) for k in ('id','start','end','status','messages','chats_total','pages','thread_ids')},ensure_ascii=False,indent=2),encoding='utf-8')
    return {'jsonl':str(folder/'messages.jsonl'),'markdown':str(folder/'messages.md')}


def brief_text(plan):
    if not plan:return '# 今日工作摘要\n\n尚未完成今日整理。\n'
    lines=[f"# {plan.get('day',db.today())} 工作摘要",f"整理时间：{plan.get('generated_at','未记录')}",'',plan.get('headline',''),'',plan.get('summary',''),'', '## 待办','']
    todos=db.todos(plan.get('day'))
    if not todos:lines+=['暂无手填待办。','']
    for task in todos:
        status='已完成' if task['status']=='done' else '待完成'
        lines += [f"### {task['title']} · {status}",task.get('summary',''),'']
    lines += ['## 意向','']
    intentions=db.intentions(plan.get('day'))
    if not intentions:lines+=['暂无合适意向。','']
    for task in intentions:
        status={'todo':'待推进','blocked':'等待前提','done':'已完成','observed':'待复核'}.get(task.get('status'),task.get('status',''))
        lines += [f"### {task['title']} · {status}",task.get('next_action') or task.get('summary',''),'']
        evidence=db.evidence_records(task.get('evidence_ids',[]))
        lines += ['依据：'+'；'.join(f"{r['title']} / {r.get('message_id') or r['id']}" for r in evidence),'']
    lines += ['## 夜间工作推荐','', '仅推荐；由本人复制提示词到 Codex 后决定是否运行。','']
    for item in db.night_work():
        lines += [f"### {item['title']}",item.get('content',''),'','提示词：',item.get('prompt',''),'']
    lines += ['## 明日预判','']
    for risk in db.active_planning('risk',plan.get('day')):lines += [f"### {risk['title']}",risk.get('reason',''),'提前准备：'+risk.get('preparation',''),'']
    latest=db.get('feishu_last_success') or {}
    lines += ['## 采集范围','',f"飞书用户 API：{latest.get('messages',0)} 条消息，{latest.get('chats_total',0)} 个会话。截止：{latest.get('end','未同步')}。",'群聊仅只读采集，未发送消息或更改群内容。','完整来源见同目录 messages.jsonl / messages.md。']
    return '\n'.join(lines)


def write_brief(plan):
    folder=db.DATA/'exports'/'feishu'/plan.get('day',db.today());folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=folder/'brief.md';temp=path.with_suffix('.tmp');temp.write_text(brief_text(plan),encoding='utf-8');temp.chmod(0o600);temp.replace(path)
    return str(path)
