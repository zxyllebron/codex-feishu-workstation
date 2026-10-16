import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from urllib.parse import quote
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch

import archives
import engine
import server
import sources
import storage as db

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.data_patch=patch.object(db,'DATA',self.folder);self.data_patch.start();db.init()
        self.recent_patch=patch.object(sources,'recent_codex',return_value=[]);self.recent_patch.start()
        self.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);self.old_port=server.PORT;server.PORT=self.http.server_port
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join();server.PORT=self.old_port
        self.recent_patch.stop();self.data_patch.stop();self.temp.cleanup()
    def request(self,path,data=None):
        c=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=3)
        c.request('GET' if data is None else 'POST','/api/'+quote(path,safe='?=&/'),None if data is None else json.dumps(data),{'Content-Type':'application/json','X-Workstation-Key':server.TOKEN})
        r=c.getresponse();raw=r.read();out=json.loads(raw) if r.getheader('Content-Type').startswith('application/json') else raw;c.close();return r.status,out
    def record(self,id='thread:one',day=None,**extra):
        r={'id':id,'kind':'codex','day':day or db.today(),'updated':(day or db.today())+'T12:00:00+08:00','title':'核对控制器资料','text':'用户希望整理已有资料，现场验证尚未完成。','has_result':True,**extra};db.save_record(r);return r
    def intention(self,id='intent:one',**extra):
        t={'id':id,'day':db.today(),'created':db.now(),'title':'整理资料','origin':'codex','role':'intention','status':'todo','priority':'high','summary':'文字整理','next_action':'整理已有材料','night_prompt':'整理给定文字','night_eligible':True,'evidence_ids':['thread:one'],**extra};db.save_task(t);return t
    def analyze(self,**extra):
        plan={'headline':'摘要','summary':'工作线索','intentions':[],'risks':[],'night_recommendations':[],**extra}
        with patch.object(engine,'invoke',return_value=json.dumps(plan,ensure_ascii=False)):
            return engine.analyze()
    def recommendation(self,**extra):
        return {'title':'整理今晚的未收尾资料','content':'复核已有资料并形成缺口清单','prompt':'基于已有材料完成缺口清单，保留未确认项。','intention_title':'整理资料','forecast_title':'','evidence_ids':['thread:one'],**extra}

    def test_intention_checkbox_completion_is_archived_and_survives_analysis(self):
        self.record();t=self.intention()
        self.assertEqual(self.request('task',{'id':t['id'],'status':'done'})[0],200)
        self.assertEqual(db.intentions(),[]);self.assertEqual(db.completed('work')['items'][0]['id'],t['id'])
        output={k:t.get(k,'') for k in engine.ITEM['properties']};output['estimated_minutes']=10
        plan=self.analyze(intentions=[output],night_recommendations=[self.recommendation()])
        self.assertEqual(plan['intentions'],[]);self.assertEqual(db.task(t['id'])['status'],'done');self.assertEqual(db.night_work(),[])
        with patch.object(db,'today',return_value='2026-10-20'):
            self.assertEqual(self.request('task',{'id':t['id'],'status':'todo'})[0],200)
            self.assertEqual(db.intentions()[0]['id'],t['id'])
        self.assertEqual(self.request('task',{'id':t['id'],'title':'自动改待办'})[0],400)

    def test_completed_intention_purge_cannot_be_reinserted(self):
        t=self.intention(status='done',manual_status=True,completed_at=db.now())
        self.assertTrue(db.delete_completed('task',t['id'])['deleted']);db.save_task(t);self.assertIsNone(db.task(t['id']))

    def test_no_execution_path_even_with_legacy_settings_and_queue(self):
        self.intention(queued=True)
        settings=db.get('settings');settings['auto_night']=True;db.put('settings',settings)
        with patch.object(engine,'invoke') as invoke,patch.object(engine,'analyze') as analyze,patch.object(sources,'sync_all') as sync:
            self.assertEqual(self.request('run',{'id':'intent:one'})[0],410)
            self.assertEqual(self.request('report',{'kind':'night','preview':False})[0],410)
            self.assertTrue(engine.run_task('intent:one')['manual_only']);self.assertTrue(engine.daily('night')['disabled'])
            invoke.assert_not_called();analyze.assert_not_called();sync.assert_not_called()
        self.assertEqual(db.runs(),[])
        self.assertEqual(self.request('task',{'id':'intent:one','queued':True})[0],400)
        self.assertFalse(self.request('settings',{'auto_night':True})[1]['auto_night'])
        db.init();self.assertFalse(db.task('intent:one')['queued']);self.assertFalse(db.get('settings')['auto_night'])

    def test_recommendation_is_self_contained_and_not_a_completed_task(self):
        self.record();self.intention()
        result=self.analyze(night_recommendations=[self.recommendation()])
        item=db.night_work()[0];prompt=engine.copy_prompt(item)
        self.assertIn(item['title'],prompt);self.assertIn(item['content'],prompt);self.assertIn('thread:one',prompt);self.assertIn('尚未完成',prompt)
        self.assertEqual(db.completed()['counts']['night'],0);self.assertEqual(db.task('intent:one')['status'],'todo')
        self.assertEqual(len(result['night_recommendations']),1)

    def test_forecasts_describe_problems_and_duplicate_work_titles_are_removed(self):
        self.record()
        risk=lambda title:{'title':title,'reason':'影响明日现场准备','confidence':'high','evidence_ids':['thread:one'],'preparation':'核对材料'}
        result=self.analyze(night_recommendations=[self.recommendation()],risks=[risk('整理今晚的未收尾资料'),risk('明日现场缺少故障证据')])
        self.assertEqual([r['title'] for r in result['risks']],['明日现场缺少故障证据'])
        result=self.analyze();self.assertEqual(result['risks'],[]);self.assertEqual(db.night_work(),[])

    def test_evening_notice_contains_topic_content_and_prompt_without_run(self):
        self.record();db.put('plan:'+db.today(),{'night_recommendations':[self.recommendation()]})
        with patch.object(sources,'sync_all'),patch.object(engine,'analyze',return_value={'run_id':'analysis'}),patch.object(engine,'run_task') as run:
            result=engine.daily('evening',allow_notify=False)
        self.assertIn('工作主题：',result['text']);self.assertIn('工作内容：',result['text']);self.assertIn('任务提示词：',result['text']);run.assert_not_called()

    def test_exact_five_day_window_old_and_future_hidden_in_every_source(self):
        today=date.fromisoformat(db.today());old=(today-timedelta(days=5)).isoformat();edge=(today-timedelta(days=4)).isoformat();future=(today+timedelta(days=1)).isoformat()
        for kind in ('codex','memory','feishu'):
            for day in (old,edge,db.today(),future):self.record(kind+':'+day,day,kind=kind)
        for kind in ('all','codex','memory','feishu'):
            status,result=self.request('records?kind='+kind);self.assertEqual(status,200)
            self.assertEqual({r['day'] for r in result['items']},{edge,db.today()})
        for category in ('codex','memory'):
            self.assertEqual(db.completed('date',old)['items'],[])
        self.assertEqual(self.request('feishu/messages?range=all')[1]['total'],2)
        self.assertIsNotNone(db.evidence_records(['codex:'+old])[0])

    def test_related_filter_mentions_private_own_and_participated_threads(self):
        db.put('feishu_self',{'name':'示例用户','open_id':'me'})
        self.record('codex:mine')
        base={'kind':'feishu','chat_id':'group','chat_type':'group','sender_id':'other','text':'普通群消息'}
        self.record('f:other',**base)
        self.record('f:mention',**{**base,'mentions':[{'id':{'open_id':'me'}}]})
        self.record('f:private',**{**base,'chat_type':'p2p'})
        self.record('f:self',**{**base,'sender_id':'me','message_id':'my-message','thread_id':'topic'})
        self.record('f:reply',**{**base,'thread_id':'topic'})
        self.record('f:direct',**{**base,'parent_id':'my-message'})
        result=self.request('records?related=1')[1]
        self.assertEqual({r['id'] for r in result['items']},{'codex:mine','f:mention','f:private','f:self','f:reply','f:direct'})
        result=self.request('records?kind=feishu&related=1&query=普通&offset=1&limit=2')[1]
        self.assertEqual(result['total'],5);self.assertEqual(len(result['items']),2)
        self.assertEqual(self.request('records?kind=bad')[0],400)

    def test_markdown_retains_old_records_and_each_day_of_a_codex_chat(self):
        old=(date.fromisoformat(db.today())-timedelta(days=7)).isoformat()
        self.record('thread:one',old,text='第一天的内容');self.record('thread:one',text='今天的内容')
        archives.write_days()
        self.assertIn('第一天的内容',archives.read(old).decode());self.assertIn('今天的内容',archives.read(db.today()).decode())
        self.assertEqual(db.visible_records()['total'],1)
        status,content=self.request('archive?day='+old);self.assertEqual(status,200);self.assertIn('第一天的内容',content.decode())
        self.assertEqual(self.request('archive?day=../secret')[0],400)
        self.assertEqual(self.request('archive?day=2000-01-01')[0],404)
        self.assertEqual((db.DATA/'archives'/(old+'.md')).stat().st_mode & 0o777,0o600)
        db.delete_completed('record','thread:one')
        self.assertNotIn('第一天的内容',archives.read(old).decode());self.assertEqual(db.evidence_records(['thread:one']),[])

    def test_local_backup_recovery_preserves_daily_history_and_purge_markers(self):
        self.record('thread:one',text='旧快照')
        backup=db.DATA/'backups'/'one';backup.mkdir(parents=True)
        with db.connect() as source,sqlite3.connect(backup/'before.sqlite') as target:source.backup(target)
        db.delete_completed('record','thread:one');self.assertEqual(archives.recover_local_backups(),0)
        self.assertEqual(db.visible_records()['items'],[])

    def test_planning_schedule_only_runs_at_seventeen_once(self):
        from datetime import datetime
        with db.connect() as c:c.execute('INSERT INTO schedule_fires VALUES (?,?,?)',(db.today()+':morning',db.now(),'success'))
        def complete(kind):
            with db.connect() as c:c.execute('INSERT INTO schedule_fires VALUES (?,?,?)',(db.today()+':'+kind,db.now(),'success'))
        with patch.object(engine,'daily',side_effect=complete) as run:
            for clock in ('14:00:00','16:59:59','17:00:20','17:00:40','18:00:00'):
                server.check_schedules(datetime.fromisoformat(db.today()+'T'+clock+'+08:00'))
        self.assertEqual([c.args for c in run.call_args_list],[('evening',)])
        self.assertEqual(db.get('settings')['evening'],'17:00')

    def test_missed_planning_slot_does_not_auto_generate_later(self):
        from datetime import datetime
        with db.connect() as c:c.execute('INSERT INTO schedule_fires VALUES (?,?,?)',(db.today()+':morning',db.now(),'success'))
        with patch.object(engine,'daily') as run:
            server.check_schedules(datetime.fromisoformat(db.today()+'T17:01:00+08:00'))
        run.assert_not_called()
        with db.connect() as c:self.assertEqual(c.execute('SELECT status FROM schedule_fires WHERE key=?',(db.today()+':evening',)).fetchone()[0],'missed')

    def test_morning_scope_preserves_night_and_forecasts(self):
        self.record();self.intention()
        risk={'title':'明日缺少证据','reason':'已有线索','confidence':'high','preparation':'核对','evidence_ids':['thread:one']}
        self.analyze(night_recommendations=[self.recommendation()],risks=[risk])
        before=db.night_work();before_risks=db.active_planning('risk');stamp=db.get('plan:'+db.today())['planning_generated_at']
        bad={'headline':'今日','summary':'摘要','intentions':[],'night_recommendations':[self.recommendation(title='不应生成')],'risks':[]}
        with patch.object(engine,'invoke',return_value=json.dumps(bad,ensure_ascii=False)) as invoke:
            result=engine.analyze('intentions')
        self.assertNotIn('error',result)
        self.assertEqual(db.night_work(),before);self.assertEqual(db.active_planning('risk'),before_risks)
        self.assertEqual(db.get('plan:'+db.today())['planning_generated_at'],stamp)
        schema=invoke.call_args.args[2]
        self.assertEqual(schema['properties']['night_recommendations']['maxItems'],0)
        self.assertEqual(schema['properties']['risks']['maxItems'],0)

    def test_planning_scope_does_not_modify_intentions(self):
        self.record();original=self.intention()
        body={'headline':'推荐','summary':'摘要','intentions':[],'night_recommendations':[self.recommendation()],'risks':[]}
        with patch.object(engine,'invoke',return_value=json.dumps(body,ensure_ascii=False)) as invoke:result=engine.analyze('planning')
        self.assertNotIn('error',result);self.assertEqual(db.task(original['id']),original)
        self.assertEqual(invoke.call_args.args[2]['properties']['intentions']['maxItems'],0)
        self.assertEqual(len(db.night_work()),1)

    def test_daily_schedule_uses_separate_generation_scopes(self):
        with patch.object(sources,'sync_all'),patch.object(engine,'analyze',return_value={'run_id':'summary'}) as analyze:
            engine.daily('morning',allow_notify=False);evening=engine.daily('evening',allow_notify=False)
        self.assertEqual([c.args for c in analyze.call_args_list],[('intentions',),('planning',)])
        self.assertIn('17:00',evening['title']);self.assertIn('明日预判',evening['text'])

    def test_night_completion_archives_and_survives_regeneration(self):
        self.record();self.analyze(night_recommendations=[self.recommendation()])
        item=db.night_work()[0]
        status,_=self.request('planning',{'id':item['id'],'status':'done'});self.assertEqual(status,200)
        self.assertEqual(db.night_work(),[])
        page=self.request('completed?category=night')[1]
        self.assertEqual(page['items'][0]['_completed_kind'],'night');self.assertTrue(page['items'][0]['copy_prompt'])
        self.analyze(night_recommendations=[self.recommendation()])
        self.assertEqual(db.night_work(),[]);self.assertEqual(db.completed()['counts']['night'],1)
        self.assertEqual(self.request('planning',{'id':item['id'],'status':'todo'})[0],200)
        self.assertEqual(len(db.night_work()),1)

    def test_all_work_types_delete_without_entering_completed_or_reappearing(self):
        self.record();intent=self.intention();manual=self.intention('todo:manual',origin='user',title='手填待办')
        risk={'title':'明日可能缺少证据','reason':'有影响','confidence':'high','preparation':'核对材料','evidence_ids':['thread:one']}
        self.analyze(night_recommendations=[self.recommendation()],risks=[risk])
        # Reinsert the known intention after this fixture's empty intention output.
        db.save_task(intent)
        targets=[('task',manual['id']),('task',intent['id']),('night',db.night_work()[0]['id']),('risk',db.active_planning('risk')[0]['id'])]
        for kind,id in targets:self.assertEqual(self.request('item/delete',{'kind':kind,'id':id})[0],200)
        self.assertEqual(db.todos(),[]);self.assertEqual(db.intentions(),[]);self.assertEqual(db.night_work(),[]);self.assertEqual(db.active_planning('risk'),[])
        self.assertEqual(db.completed()['counts']['work'],0);self.assertEqual(db.completed()['counts']['night'],0)
        proposal={k:intent.get(k,'') for k in engine.ITEM['properties']};proposal['estimated_minutes']=10
        self.analyze(intentions=[proposal],night_recommendations=[self.recommendation()],risks=[risk])
        self.assertEqual(db.intentions(),[]);self.assertEqual(db.night_work(),[]);self.assertEqual(db.active_planning('risk'),[])
        self.assertEqual(db.task(manual['id'])['status'],'todo')

    def test_deletion_of_completed_work_removes_it_from_completed(self):
        t=self.intention(status='done',manual_status=True)
        self.assertEqual(db.completed()['counts']['work'],1)
        self.request('item/delete',{'kind':'task','id':t['id']})
        self.assertEqual(db.completed()['counts']['work'],0)

    def test_planning_delete_and_status_validate_kind_and_auth(self):
        self.record();risk={'title':'明日缺少证据','reason':'有影响','confidence':'high','preparation':'核对','evidence_ids':['thread:one']}
        self.analyze(risks=[risk]);r=db.active_planning('risk')[0]
        self.assertEqual(self.request('planning',{'id':r['id'],'status':'done'})[0],400)
        self.assertEqual(self.request('item/delete',{'kind':'night','id':r['id']})[0],400)
        self.assertEqual(self.request('item/delete',{'kind':'record','id':'thread:one'})[0],400)
        self.assertEqual(self.request('item/delete',{'kind':'task','id':'missing'})[0],400)
        self.assertEqual(len(db.active_planning('risk')),1)
        c=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=3)
        c.request('POST','/api/item/delete',json.dumps({'kind':'risk','id':r['id']}),{'Content-Type':'application/json'})
        response=c.getresponse();response.read();self.assertEqual(response.status,403);c.close()

    def test_completed_night_can_be_purged_without_recreation(self):
        self.record();self.analyze(night_recommendations=[self.recommendation()]);item=db.night_work()[0]
        db.set_planning_status(item['id'],'done')
        self.assertEqual(self.request('completed/delete',{'kind':'night','id':item['id']})[0],200)
        self.analyze(night_recommendations=[self.recommendation()])
        self.assertEqual(db.night_work(),[]);self.assertEqual(db.completed()['counts']['night'],0)
        self.assertIsNone(db.planning_item(item['id']))

    def test_manual_delete_during_generation_is_preserved(self):
        self.record();t=self.intention()
        proposal={k:t.get(k,'') for k in engine.ITEM['properties']};proposal['estimated_minutes']=10
        def response(*args):
            db.delete_work_item('task',t['id'])
            return json.dumps({'headline':'摘要','summary':'','intentions':[proposal],'night_recommendations':[],'risks':[]})
        with patch.object(engine,'invoke',side_effect=response):engine.analyze()
        self.assertEqual(db.intentions(),[]);self.assertTrue(db.task(t['id'])['deleted'])

if __name__=='__main__':unittest.main()
