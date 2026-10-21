import copy
import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import engine
import feishu
import server
import sources
import storage as db

class IntentionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.p=patch.object(db,'DATA',Path(self.temp.name));self.p.start();db.init()
        self.recent=patch.object(sources,'recent_codex',return_value=[]);self.recent_mock=self.recent.start()
        self.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);self.port=server.PORT;server.PORT=self.http.server_port
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join();server.PORT=self.port
        self.recent.stop();self.p.stop();self.temp.cleanup()
    def post(self,path,body):
        c=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=3)
        c.request('POST','/api/'+path,json.dumps(body),{'Content-Type':'application/json','X-Workstation-Key':server.TOKEN})
        r=c.getresponse();result=r.status,json.loads(r.read());c.close();return result
    def item(self,title='可能需要整理的材料',evidence='thread:one'):
        return {'title':title,'summary':'明确的工作线索','priority':'high','status':'todo','project':'SDK','evidence_ids':[evidence],
                'next_action':'整理已提供文字','night_eligible':True,'night_prompt':'仅离线分析已有文字，不调用工具','estimated_minutes':10}
    def analyze(self,items=None,risks=None):
        response={'headline':'工作线索','summary':'只保留有依据的意向','intentions':items or [],'risks':risks or []}
        with patch.object(engine,'invoke',return_value=json.dumps(response,ensure_ascii=False)):
            return engine.analyze()
    def evidence(self,rid='thread:one',kind='codex',text='用户请求整理材料',**extra):
        r={'id':rid,'kind':kind,'day':db.today(),'updated':db.now(),'title':'原始会话','text':text,**extra};db.save_record(r)
    def test_manual_todo_crud_and_analysis_never_overwrites_it(self):
        self.assertEqual(self.post('task/create',{'title':'   '})[0],400)
        status,t=self.post('task/create',{'title':'我亲自填写的待办','notes':'保留这份说明'});self.assertEqual(status,200)
        self.evidence();self.analyze([self.item(t['title']),self.item('有依据的意向')])
        self.assertEqual(len(db.todos()),1);self.assertEqual(db.todos()[0]['summary'],'保留这份说明')
        self.assertEqual([i['title'] for i in db.intentions()],['有依据的意向'])
        self.assertEqual(self.post('task',{'id':t['id'],'title':'我修改的待办','notes':'新说明','status':'done'})[0],200)
        self.analyze();self.assertEqual(db.task(t['id'])['title'],'我修改的待办');self.assertEqual(db.task(t['id'])['status'],'done')
        self.assertEqual(self.post('task',{'id':t['id'],'deleted':True})[0],200);self.assertEqual(db.todos(),[])
        self.assertEqual(self.post('task',{'id':t['id'],'deleted':False})[0],200);self.assertEqual(len(db.todos()),1)
    def test_recent_requests_are_used_and_have_source_details(self):
        self.evidence(text='只有助手结果')
        recent={'id':'thread:one','kind':'codex','day':db.today(),'updated':db.now(),'title':'原始会话','text':'用户明确请求：继续准备分享'}
        self.recent_mock.return_value=[recent]
        ctx=engine.context();self.assertIn('用户明确请求',[r['text'] for r in ctx['records'] if r['id']=='thread:one'][0])

    def test_empty_analysis_has_no_quota_and_does_not_create_todos(self):
        self.evidence();self.analyze([self.item()]);self.assertEqual(len(db.intentions()),1)
        self.analyze();self.assertEqual(db.intentions(),[]);self.assertEqual(db.todos(),[])
        self.assertEqual(db.get('plan:'+db.today())['risks'],[])
        self.assertEqual(db.tasks()[0]['stale'],True)
    def test_unrelated_group_requests_are_not_user_intentions(self):
        db.put('feishu_self',{'name':'示例用户','open_id':'me'})
        self.evidence('feishu:other','feishu','@回响 请替另一位同事处理',chat_id='group',sender_id='other',chat_type='group')
        self.evidence('feishu:mine','feishu','@示例用户 请核对这份资料',chat_id='group',sender_id='other',chat_type='group')
        self.analyze([self.item('别人的事','feishu:other'),self.item('明确 @ 我的事','feishu:mine')])
        self.assertEqual([t['title'] for t in db.intentions()],['明确 @ 我的事'])
    def test_hidden_intention_is_not_recreated_and_cannot_modify_todos(self):
        self.evidence();self.analyze([self.item()]);i=db.intentions()[0]
        self.assertEqual(self.post('task',{'id':i['id'],'title':'冒充待办'})[0],400)
        self.assertEqual(self.post('task',{'id':i['id'],'dismissed':True})[0],200)
        self.analyze([self.item()]);self.assertEqual(db.intentions(),[]);self.assertEqual(db.todos(),[])
    def test_old_queue_never_runs_after_switch_to_copy_only(self):
        cfg=db.get('settings');cfg.update(auto_night=True,night_limit=1);db.put('settings',cfg)
        for n in range(6):
            t=self.item('夜间材料 '+str(n));t.update(id=str(n),origin='codex',day=db.today(),queued=True);db.save_task(t)
        with patch.object(sources,'sync_all') as sync,patch.object(engine,'analyze') as analyze,patch.object(engine,'run_task') as run:
            result=engine.daily('night',allow_notify=False)
        self.assertTrue(result['manual_only']);run.assert_not_called();analyze.assert_not_called();sync.assert_not_called()
        self.assertEqual(self.post('settings',{'auto_night':True,'night_limit':1})[0],200)
        self.assertNotIn('night_limit',db.get('settings'));self.assertFalse(db.get('settings')['auto_night'])
    def test_intentions_and_risks_are_small_and_evidence_bound(self):
        self.evidence()
        risk=lambda n,confidence:{'title':'明日风险 '+str(n),'reason':'有明确明日影响','confidence':confidence,'evidence_ids':['thread:one'],'preparation':'核对材料'}
        self.analyze([self.item(str(n)) for n in range(5)],[risk(0,'low'),risk(1,'high'),risk(2,'medium'),risk(3,'high')])
        self.assertEqual(len(db.intentions()),3);self.assertEqual(len(db.get('plan:'+db.today())['risks']),2)
        self.assertEqual(db.todos(),[])

class RecentCodexTests(unittest.TestCase):
    def test_recent_window_reads_all_active_chats_and_excludes_internal_jobs(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td);start,_=sources.day_range(db.today())
            with sqlite3.connect(folder/'state_5.sqlite',factory=db.ClosingConnection) as c:
                c.execute('CREATE TABLE threads (id,title,cwd,updated_at,rollout_path)')
                for n,days,cwd in [('recent',2,'/home/example/sdk'),('today',0,'/home/example/other'),('too-old',9,'/home/example/old'),('internal',0,'/home/example/workstation/data/runs/a')]:
                    c.execute('INSERT INTO threads VALUES (?,?,?,?,?)',(n,n,cwd,int((start-timedelta(days=days)).timestamp())+5,'unused'))
            with patch.object(db,'DATA',folder/'data'),patch.object(sources,'CODEX',folder),patch.object(sources,'read_messages',return_value=([],False)) as read:
                db.init();records=sources.recent_codex()
                self.assertEqual({r['thread_id'] for r in records},{'recent','today'});self.assertEqual(read.call_count,2)
                self.assertTrue(all(c.kwargs['since']==start-timedelta(days=6) for c in read.call_args_list))

if __name__=='__main__':unittest.main()
