import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import server
import sources
import storage as db


class CompletedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.folder=Path(self.temp.name)
        self.data_patch=patch.object(db,'DATA',self.folder/'data');self.data_patch.start();db.init()
        self.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.old_port=server.PORT;server.PORT=self.http.server_port
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join();server.PORT=self.old_port
        self.data_patch.stop();self.temp.cleanup()

    def request(self,path,body=None,key=True,origin=None):
        headers={'Content-Type':'application/json'}
        if key:headers['X-Workstation-Key']=server.TOKEN
        if origin:headers['Origin']=origin
        conn=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=3)
        conn.request('POST' if body is not None else 'GET','/api/'+path,json.dumps(body) if body is not None else None,headers)
        response=conn.getresponse();raw=response.read();conn.close()
        return response.status,json.loads(raw) if response.getheader('Content-Type').startswith('application/json') else raw

    def task(self,id='todo:done',**extra):
        t={'id':id,'day':db.today(),'origin':'user','title':'手填已完成','status':'done','completed_at':db.now(),**extra}
        db.save_task(t);return t

    def make_run(self,id='night-done',**extra):
        r={'id':id,'kind':'night','created':db.now(),'status':'success','title':'夜间产物','result':'内容',**extra}
        db.save_run(r);return r

    def record(self,id='thread:done',**extra):
        r={'id':id,'kind':'codex','day':db.today(),'updated':db.now(),'title':'已输出结果','text':'正文','has_result':True,**extra}
        db.save_record(r);return r

    def test_index_is_metadata_only_and_categories_never_mix(self):
        self.task();self.make_run();self.record();self.record('memory:old',kind='memory',day='2026-01-02')
        self.task('todo:open',status='todo');self.task('intention:done',origin='codex')
        self.task('todo:hidden',deleted=True);self.make_run('analysis',kind='analysis');self.make_run('failed',status='failed')
        self.record('thread:open',has_result=False);self.record('feishu:one',kind='feishu');self.record('thread:hidden',superseded_by_api_job='api')
        status,index=self.request('completed');self.assertEqual(status,200)
        self.assertEqual(index['counts'],{'work':1,'night':1,'date':1})
        self.assertEqual(index['dates'],[{'day':db.today(),'count':1}])
        self.assertNotIn('items',index);self.assertNotIn('正文',json.dumps(index,ensure_ascii=False))
        for category,kind,id in [('work','task','todo:done'),('night','run','night-done'),('date','record','thread:done')]:
            status,result=self.request('completed?category='+category+'&day='+db.today());self.assertEqual(status,200)
            self.assertEqual([(x['_completed_kind'],x['id']) for x in result['items']],[(kind,id)])
        self.assertEqual(self.request('completed?category=date')[1],{'items':[],'total':0})

    def test_archive_uses_all_dates_and_paginates_search_results(self):
        for n in range(4):self.task('old:'+str(n),title='项目 '+str(n),day='2026-01-01',completed_at='2026-01-01T12:00:00+08:00')
        page=db.completed('work',query='项目',offset=1,limit=2)
        self.assertEqual(page['total'],4);self.assertEqual([x['id'] for x in page['items']],['old:1','old:2'])
        self.assertEqual(db.completed('work',query='不存在')['items'],[])
        for args in ['category=unknown','category=date&day=2026-02-30','offset=no-number','day=2026-1-1']:
            self.assertEqual(self.request('completed?'+args)[0],400)

    def test_task_purge_removes_body_and_prevents_reinsertion(self):
        t=self.task();self.task('todo:keep',status='todo')
        status,result=self.request('completed/delete',{'kind':'task','id':t['id']})
        self.assertEqual(status,200);self.assertTrue(result['deleted']);self.assertIsNone(db.task(t['id']))
        db.save_task(t);self.assertIsNone(db.task(t['id']));self.assertIsNotNone(db.task('todo:keep'))
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT kind,id FROM purged_items').fetchall()[0][:],('task',t['id']))
        self.assertEqual(db.completed()['counts']['work'],0)

    def test_only_completed_supported_items_can_be_purged(self):
        self.task(status='todo');self.make_run(status='running');self.record(has_result=False)
        for kind,id in [('task','todo:done'),('run','night-done'),('record','thread:done'),('record','missing'),('unknown','none')]:
            self.assertEqual(self.request('completed/delete',{'kind':kind,'id':id})[0],400)
        self.assertEqual(db.purged_ids('task'),set());self.assertIsNotNone(db.task('todo:done'))

    def test_purge_requires_same_origin_and_csrf(self):
        self.task();body={'kind':'task','id':'todo:done'}
        self.assertEqual(self.request('completed/delete',body,key=False)[0],403)
        self.assertEqual(self.request('completed/delete',body,origin='https://other.example')[0],403)
        self.assertIsNotNone(db.task('todo:done'))

    def test_run_purge_removes_only_its_owned_artifacts_and_keeps_execution_marker(self):
        r=self.make_run();owned=db.DATA/'runs'/r['id'];owned.mkdir(parents=True);(owned/'result.md').write_text('产物')
        unrelated=db.DATA/'runs'/'other';unrelated.mkdir();(unrelated/'keep').write_text('保留')
        self.task('intention',origin='codex',status='todo',last_run=r['id'],night_eligible=True)
        self.assertEqual(self.request('completed/delete',{'kind':'run','id':r['id']})[0],200)
        self.assertFalse(owned.exists());self.assertTrue((unrelated/'keep').exists());self.assertIsNone(db.run(r['id']))
        self.assertEqual(db.task('intention')['last_run'],r['id'])
        db.save_run(r);self.assertIsNone(db.run(r['id']))
        self.assertEqual(self.request('artifact/'+r['id'])[0],404)

    def test_artifact_path_cannot_escape_run_folder(self):
        outside=self.folder/'keep';outside.mkdir();(outside/'keep').write_text('保留')
        r=self.make_run(artifact_dir=str(outside));self.assertTrue(db.delete_completed('run',r['id'])['deleted'])
        self.assertTrue((outside/'keep').exists())
        for id in ['../keep','linked']:
            self.make_run(id)
            if id=='linked':
                root=db.DATA/'runs';root.mkdir(exist_ok=True);(root/id).symlink_to(outside,target_is_directory=True)
            with self.assertRaises(ValueError):db.delete_completed('run',id)
            self.assertIsNotNone(db.run(id));self.assertTrue((outside/'keep').exists())

    def test_record_purge_removes_evidence_and_does_not_reappear_in_recent_context(self):
        r=self.record('thread:one');source=self.folder/'source.jsonl';source.write_text('original')
        with sqlite3.connect(self.folder/'state_5.sqlite') as c:
            c.execute('CREATE TABLE threads(id,title,cwd,updated_at,rollout_path)')
            c.execute('INSERT INTO threads VALUES(?,?,?,?,?)',('one','one','/home/example/project',int(sources.day_range(db.today())[0].timestamp())+1,str(source)))
        with sqlite3.connect(self.folder/'memories_1.sqlite') as c:
            c.execute('CREATE TABLE stage1_outputs(thread_id,generated_at,source_updated_at,rollout_slug,raw_memory,rollout_summary)')
        self.assertTrue(db.delete_completed('record',r['id'])['deleted']);db.save_record(r)
        self.assertEqual(db.evidence_records([r['id']]),[])
        with patch.object(sources,'CODEX',self.folder),patch.object(sources,'read_messages') as read:
            self.assertEqual(sources.recent_codex(),[]);self.assertEqual(sources.sync_codex(db.today())['threads'],0);read.assert_not_called()
        self.assertEqual(source.read_text(),'original')

    def test_memory_purge_blocks_sync_reinsertion(self):
        r=self.record('memory:one:'+db.today(),kind='memory');db.delete_completed('record',r['id']);db.save_record(r)
        self.assertEqual(db.records(),[]);self.assertEqual(db.completed()['dates'],[])

    def test_archive_artifact_download_is_not_limited_to_latest_eighty_runs(self):
        self.make_run('old',created='2020-01-01T00:00:00+08:00',result='旧结果')
        for n in range(81):self.make_run('new'+str(n))
        self.assertNotIn('old',[r['id'] for r in db.runs()])
        self.assertEqual(self.request('artifact/old'),(200,'旧结果'.encode()))

if __name__=='__main__':unittest.main()
