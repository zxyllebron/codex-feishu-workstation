import http.client
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import server
import storage as db


class CompletionRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.clock=datetime.fromisoformat('2026-10-18T23:55:00+08:00')
        self.patches=[patch.object(db,'DATA',Path(self.temp.name)),
                      patch.object(db,'now',side_effect=lambda:self.clock.isoformat()),
                      patch.object(db,'today',side_effect=lambda:self.clock.date().isoformat())]
        for p in self.patches:p.start()
        db.init()
        self.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.old_port=server.PORT;server.PORT=self.http.server_port
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join();server.PORT=self.old_port
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def post(self,path,body):
        c=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=3)
        c.request('POST','/api/'+path,json.dumps(body),{'Content-Type':'application/json','X-Workstation-Key':server.TOKEN})
        response=c.getresponse();value=json.loads(response.read());c.close()
        self.assertEqual(response.status,200,value)
        return value

    def task(self,origin='user'):
        item={'id':'test:task','day':db.today(),'created':db.now(),'origin':origin,
              'title':'保留已完成任务','status':'todo','evidence_ids':[]}
        db.save_task(item);return item

    def test_manual_completion_survives_midnight_restart_and_expires_at_24_hours(self):
        item=self.task();done=self.post('task',{'id':item['id'],'status':'done'})
        self.clock+=timedelta(hours=23,minutes=59,seconds=59)
        db.init()  # Reopening the persistent store must not reset the timer.
        self.assertEqual(db.recent_completed_work()[0]['completed_at'],done['completed_at'])
        self.assertEqual(db.todos()[0]['id'],item['id'])
        self.assertEqual(db.completed('work')['items'],[])
        self.clock+=timedelta(seconds=1)
        self.assertEqual(db.recent_completed_work(),[]);self.assertEqual(db.todos(),[])
        self.assertEqual(db.completed('work')['items'][0]['id'],item['id'])
        self.assertEqual(db.completed()['counts']['work'],1)
        self.assertIsNotNone(db.task(item['id']))

    def test_duplicate_completion_does_not_extend_timer_and_reopening_starts_a_new_one(self):
        item=self.task();done=self.post('task',{'id':item['id'],'status':'done'})
        self.clock+=timedelta(hours=23)
        self.assertEqual(self.post('task',{'id':item['id'],'status':'done'})['completed_at'],done['completed_at'])
        self.post('task',{'id':item['id'],'status':'todo'})
        self.assertEqual(db.recent_completed_work(),[])
        self.clock+=timedelta(hours=2)
        redone=self.post('task',{'id':item['id'],'status':'done'})
        self.assertNotEqual(redone['completed_at'],done['completed_at'])
        self.assertEqual(len(db.recent_completed_work()),1);self.assertEqual(db.completed('work')['items'],[])

    def test_completed_intention_is_retained_even_if_analysis_marks_it_stale(self):
        item=self.task('codex');self.post('task',{'id':item['id'],'status':'done'})
        self.clock+=timedelta(hours=1)
        stored=db.task(item['id']);stored['stale']=True;db.save_task(stored)
        self.assertEqual(db.intentions(),[])
        self.assertEqual(db.recent_completed_work()[0]['id'],item['id'])
        self.assertEqual(server.state()['home_completed'][0]['id'],item['id'])
        self.clock+=timedelta(hours=23)
        self.assertEqual(db.recent_completed_work(),[])
        self.assertEqual(db.completed('work')['items'][0]['id'],item['id'])

    def test_editing_completed_todo_preserves_completion_until_explicit_reopen(self):
        item=self.task();done=self.post('task',{'id':item['id'],'status':'done'})
        self.clock+=timedelta(hours=2)
        edited=self.post('task',{'id':item['id'],'title':'修改后的待办','notes':'修改后的说明'})
        self.assertEqual(edited['status'],'done')
        self.assertEqual(edited['completed_at'],done['completed_at'])
        self.assertEqual(db.recent_completed_work()[0]['summary'],'修改后的说明')
        self.post('task',{'id':item['id'],'status':'todo'})
        self.assertIsNone(db.task(item['id'])['completed_at'])
        self.assertEqual(db.recent_completed_work(),[])
        self.assertEqual(db.todos()[0]['title'],'修改后的待办')
        self.assertEqual(db.completed('work')['items'],[])

    def test_night_checkbox_retention_and_archive_transition(self):
        item={'title':'夜间已完成任务','content':'核对资料','evidence_ids':[]}
        stored=db.save_planning_batch('night',[item])[0]
        done=self.post('planning',{'id':stored['id'],'status':'done'})
        self.clock+=timedelta(hours=23)
        again=self.post('planning',{'id':stored['id'],'status':'done'})
        self.assertEqual(again['completed_at'],done['completed_at'])
        self.assertEqual(db.recent_completed_work()[0]['_completed_kind'],'night')
        self.assertTrue(server.state()['home_completed'][0]['copy_prompt'])
        self.assertEqual(db.completed('night')['items'],[])
        self.clock+=timedelta(hours=1)
        self.assertEqual(db.recent_completed_work(),[])
        self.assertEqual(db.completed('night')['items'][0]['id'],stored['id'])
        self.assertEqual(db.completed()['counts']['night'],1)

    def test_deleted_and_legacy_completed_tasks_do_not_linger_on_home(self):
        item=self.task();self.post('task',{'id':item['id'],'status':'done'})
        self.post('item/delete',{'kind':'task','id':item['id']})
        self.assertEqual(db.recent_completed_work(),[])
        old={'id':'legacy','day':'2020-01-01','origin':'user','title':'旧任务','status':'done'}
        db.save_task(old)
        self.assertEqual(db.recent_completed_work(),[])
        self.assertEqual(db.completed('work')['items'][0]['id'],'legacy')


if __name__=='__main__':unittest.main()
