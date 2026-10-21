import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import engine
import server
import sources
import storage as db

class WorkworldTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.data_patch=patch.object(db,'DATA',Path(self.temp.name));self.data_patch.start()
        db.init()
        self.recent_patch=patch.object(sources,'recent_codex',return_value=[]);self.recent_patch.start()

    def tearDown(self):
        self.recent_patch.stop();self.data_patch.stop();self.temp.cleanup()

    def task(self,day=None):
        return {'id':'carry-task','day':day or db.today(),'title':'准备证据差异表','status':'todo','summary':'仅做离线准备',
                'project':'SDK','priority':'high','evidence_ids':['thread:one'],'next_action':'整理材料','night_eligible':True,
                'night_prompt':'只分析给定文字','estimated_minutes':10,'queued':True}

    def test_beijing_day_boundary(self):
        self.assertTrue(sources.same_day('2026-10-14T16:00:00Z','2026-10-15'))
        self.assertFalse(sources.same_day('2026-10-15T16:00:00Z','2026-10-15'))
        self.assertFalse(sources.same_day('not a date','2026-10-15'))

    def test_secrets_removed_from_display(self):
        raw='glpat-abcdefghijklmnop -----BEGIN OPENSSH PRIVATE KEY-----\nsecret\n-----END OPENSSH PRIVATE KEY----- password=abcdef'
        cleaned=db.clean(raw)
        for val in ['abcdefghijklmnop','secret','abcdef']:self.assertNotIn(val,cleaned)

    def test_workbench_analysis_sessions_are_excluded_after_rename(self):
        import sqlite3
        root=Path(self.temp.name)/'codex';root.mkdir()
        with sqlite3.connect(root/'state_5.sqlite',factory=db.ClosingConnection) as c:
            c.execute('CREATE TABLE threads (id,title,cwd,updated_at,rollout_path)')
            for idx,cwd in enumerate(('/home/example/workworld/data/runs/old','/home/example/workstation/data/runs/new','/home/example/sdk-915')):
                c.execute('INSERT INTO threads VALUES (?,?,?,?,?)',(str(idx),'会话',cwd,int(sources.day_range(db.today())[0].timestamp())+100,'unused'))
        with sqlite3.connect(root/'memories_1.sqlite',factory=db.ClosingConnection) as c:
            c.execute('CREATE TABLE stage1_outputs (generated_at,source_updated_at)')
        with patch.object(sources,'CODEX',root),patch.object(sources,'read_messages',return_value=([],False)):
            sources.sync_codex(db.today())
        self.assertEqual([r['cwd'] for r in db.records()],['/home/example/sdk-915'])

    def test_unfinished_work_carries_into_next_morning(self):
        original=self.task('2026-10-14');db.save_task(original)
        db.save_record({'id':'thread:one','kind':'codex','day':'2026-10-14','updated':'2026-10-14T20:00:00+08:00','title':'昨天未完工作','text':'验证仍未完成'})
        ctx=engine.context()
        self.assertIn('thread:one',[r['id'] for r in ctx['records']])
        out={k:v for k,v in original.items() if k in engine.ITEM['properties']}
        response={'headline':'继续准备','summary':'保留昨天未完成事项','tasks':[out],'risks':[]}
        with patch.object(engine,'invoke',return_value=json.dumps(response,ensure_ascii=False)):
            result=engine.analyze()
        self.assertNotIn('error',result)
        task=db.tasks()[0]
        self.assertEqual(task['id'],original['id'])
        self.assertFalse(task['queued'])
        self.assertTrue(task['night_prompt'])
        self.assertEqual(task['day'],db.today())

    def test_daily_slot_cannot_send_twice(self):
        db.save_task(self.task())
        with patch.object(sources,'sync_all') as sync,patch.object(engine,'analyze',return_value={'run_id':'sample-run'}):
            first=engine.daily('evening')
            second=engine.daily('evening')
        self.assertIn('title',first)
        self.assertTrue(second['already_ran'])
        self.assertEqual(sync.call_count,1)
        self.assertEqual(len(db.get('notifications')),1)

    def test_failed_schedule_is_not_reported_as_success(self):
        with patch.object(sources,'sync_all'),patch.object(engine,'analyze',return_value={'error':'模拟离线'}):
            result=engine.daily('evening',allow_notify=False)
        self.assertIn('error',result)
        with db.connect() as c:status=c.execute('SELECT status FROM schedule_fires').fetchone()[0]
        self.assertEqual(status,'failed')
        self.assertIsNone(db.get('report:evening:'+db.today()))

    def test_restart_marks_unconfirmed_run_interrupted(self):
        db.save_run({'id':'r','created':db.now(),'status':'running','kind':'night','title':'未完成执行','result':''})
        db.init()
        self.assertEqual(db.runs()[0]['status'],'interrupted')

    def test_http_origin_token_and_import_idempotence(self):
        http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        original_port=server.PORT;server.PORT=http.server_port
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        def post(path,body,headers=None):
            conn=http_client();conn.request('POST',path,body=json.dumps(body),headers={'Content-Type':'application/json',**(headers or {})})
            r=conn.getresponse();out=(r.status,json.loads(r.read()));conn.close();return out
        import http.client as client
        def http_client():return client.HTTPConnection('127.0.0.1',http.server_port,timeout=3)
        try:
            self.assertEqual(post('/api/import',{})[0],403)
            self.assertEqual(post('/api/import',{}, {'X-Workworld-Key':server.TOKEN,'Origin':'https://other.example'})[0],403)
            headers={'X-Workworld-Key':server.TOKEN,'Origin':f'http://127.0.0.1:{http.server_port}'}
            records={'messages':[{'message_id':'same-message','timestamp':db.now(),'text':'真实整理文本'},{'message_id':'old-message','timestamp':'2000-01-01T12:00:00+08:00','text':'昨天的消息'}]}
            self.assertEqual(post('/api/import',records,headers),(200,{'imported':1}))
            self.assertEqual(post('/api/import',records,headers),(200,{'imported':1}))
            self.assertEqual(len(db.records()),1)
            self.assertEqual(post('/api/settings',{'morning':'27:99'},headers)[0],400)
        finally:http.shutdown();http.server_close();thread.join();server.PORT=original_port

if __name__=='__main__':unittest.main()
