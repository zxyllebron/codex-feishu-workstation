import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import feishu as f
import feishu_api as api
import storage as db

class BulkApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.p=patch.object(db,'DATA',Path(self.temp.name));self.p.start();db.init();db.put('feishu_self',{'name':'示例用户','open_id':'me'});f.STOP.clear()
    def tearDown(self):self.p.stop();self.temp.cleanup();f.STOP.clear()
    def job(self):
        return {'id':'bulk','mode':'user','range':'today','start':'2026-10-15T00:00:00+08:00','end':'2026-10-15T17:00:00+08:00','messages':0,'errors':[],'chats_done':0,'chats_total':0}
    def message(self,mid,position='0'):
        return {'message_id':mid,'chat_id':'c','create_time':'2026-10-15T12:00:00+08:00','msg_type':'text','message_position':position,'body':{'content':'{"text":"版本已合入"}'},'sender':{'id':'colleague','sender_name':'同事'}}
    def run_worker(self,job,raw):
        f.LOCK.acquire()
        with patch.object(api,'raw',side_effect=raw):api.crawl(job)
    def test_bulk_pages_bodies_and_export_are_complete(self):
        calls=[]
        def raw(method,path,params=None,data=None):
            calls.append((method,path,params,data))
            if path.endswith('/search'):
                self.assertEqual(data['filter']['time_range']['start_time'],'2026-10-15T00:00:00+08:00')
                more=not params.get('page_token');mid='a' if more else 'b'
                return {'data':{'items':[{'meta_data':{'message_id':mid,'chat_id':'c','is_p2p_chat':False}}],'has_more':more,'page_token':'next' if more else ''}}
            if path.endswith('/mget'):
                self.assertTrue(params['with_sender_name']);return {'data':{'items':[self.message(params['message_ids'][0])]}}
            return {'data':{'items':[{'chat_id':'c','name':'SDK','chat_mode':'group'}]}}
        job=self.job();self.run_worker(job,raw)
        self.assertEqual(job['status'],'complete');self.assertEqual(job['messages'],2);self.assertEqual(job['indexed_messages'],2);self.assertEqual(job['pages'],2)
        lines=Path(job['export']['jsonl']).read_text().splitlines();self.assertEqual(len(lines),2)
        self.assertTrue(all(json.loads(l)['sender_name']=='同事' for l in lines))
    def test_missing_message_body_does_not_advance_cursor(self):
        def raw(method,path,params=None,data=None):
            if path.endswith('/search'):return {'data':{'items':[{'meta_data':{'message_id':'a'}}],'has_more':True,'page_token':'next'}}
            return {'data':{'items':[]}}
        job=self.job();self.run_worker(job,raw)
        self.assertEqual(job['status'],'error');self.assertFalse(job.get('search_token'));self.assertNotIn('export',job)
    def test_group_mutations_are_not_permitted_by_personal_adapter(self):
        with self.assertRaises(ValueError):api.raw('POST','/open-apis/im/v1/messages',data={'text':'不应发送'})
        with self.assertRaises(ValueError):api.raw('DELETE','/open-apis/im/v1/chats/c')
    def test_nested_json_card_text_is_preserved_without_actions(self):
        card={'json_card':json.dumps({'body':{'tag':'div','property':{'elements':[{'tag':'markdown','property':{'content':'已核对日志，问题仍待现场复现。'}},{'tag':'button','property':{'text':'重启机器人'}}]}}})}
        result=api.content_text({'msg_type':'interactive','body':{'content':json.dumps(card)}})
        self.assertEqual(result,'已核对日志，问题仍待现场复现。')
    def test_colliding_api_positions_do_not_merge_distinct_ids(self):
        a=self.message('api_a','-1');a['content']='a';a.pop('body');b=copy.deepcopy(a);b['message_id']='api_b';b['content']='b'
        chat={'chat_id':'c','name':'SDK'}
        self.assertNotEqual(f.save_message(a,chat,'user'),f.save_message(b,chat,'user'))
        self.assertEqual(len(db.records('2026-10-15')),2)
    def test_browser_canonical_id_remains_stable_on_api_resync(self):
        chat={'chat_id':'c','name':'SDK'}
        rid=f.save_message({'message_id':'dom','position':'19','timestamp':'2026-10-15T12:00:00+08:00','text':'版本已合入'},chat,'browser')
        m=self.message('om_a','19');self.assertEqual(f.save_message(m,chat,'user'),rid);self.assertEqual(f.save_message(m,chat,'user'),rid)
        self.assertEqual(len(db.records('2026-10-15')),1)
    def test_pause_before_read_makes_no_cloud_request(self):
        f.STOP.set();job=self.job()
        def forbidden(*a,**k):self.fail('暂停后不应再读取云端')
        self.run_worker(job,forbidden);self.assertEqual(job['status'],'paused')
    def test_private_chat_name_can_be_filled_after_first_outgoing_page(self):
        db.put('feishu_chat_cache',{'p':{'chat_id':'p','name':'私聊','chat_type':'p2p'}})
        response={'data':{'items':[{'chat_id':'p','name':'','chat_mode':'p2p','p2p_target_id':'peer'}]}}
        with patch.object(api,'raw',return_value=response):
            result=api.chat_context(['p'],[{'chat_id':'p','is_p2p_chat':True}],[{'chat_id':'p','sender':{'id':'peer','sender_name':'示例同事'}}])
        self.assertEqual(result['p']['name'],'示例同事')

class NotificationBoundaryTests(unittest.TestCase):
    def test_group_target_never_sends(self):
        import engine
        with tempfile.TemporaryDirectory() as td,patch.object(db,'DATA',Path(td)):
            db.init();cfg=db.get('settings');cfg.update(notify_feishu=True,notification_chat='oc_group');db.put('settings',cfg)
            with patch.object(engine.sources,'lark') as send:
                result=engine.notify('测试','不应发送到群')
            send.assert_not_called();self.assertEqual(result['feishu_status'],'failed')

if __name__=='__main__':unittest.main()
