import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import feishu
import storage as db

class FeishuTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.patch=patch.object(db,'DATA',Path(self.temp.name));self.patch.start();db.init();feishu.STOP.clear()
    def tearDown(self):
        self.patch.stop();self.temp.cleanup();feishu.STOP.clear()
    def job(self,mode='user'):
        return {'id':'scan','mode':mode,'identity':mode,'range':'today','start':'2026-10-15T00:00:00+08:00','end':'2026-10-15T16:12:36+08:00','status':'listing' if mode=='user' else 'waiting_browser','chats':[],'list_token':'','message_token':'','seen_list_tokens':[],'seen_message_tokens':[],'listed':False,'chat_index':0,'completed_chats':[],'chats_done':0,'chats_total':0,'messages':0,'errors':[]}
    def message(self,mid='m',when='2026-10-15 10:00',**kw):
        return {'message_id':mid,'create_time':when,'sender':{'name':'同事'},'content':'版本跟进',**kw}
    def response(self,items,key='messages',more=False,token=''):
        return {'data':{key:items,'has_more':more,'page_token':token}}
    def run_crawl(self,job,call):
        feishu.LOCK.acquire()
        with patch.object(feishu,'call',side_effect=call):feishu.crawl(job)
    def test_chat_message_and_thread_pages_exhausted(self):
        calls=[]
        def call(args,*_):
            calls.append(args);token=args[args.index('--page-token')+1] if '--page-token' in args else ''
            if args[1]=='+chat-list':
                return self.response([{'chat_id':'c2' if token else 'c1','name':'工作群'}],'chats',not token,'list-next' if not token else '')
            if args[1]=='+threads-messages-list':
                return self.response([self.message('reply2' if token else 'reply1')],more=not token,token='thread-next' if not token else '')
            cid=args[args.index('--chat-id')+1]
            if cid=='c1':return self.response([self.message('old-root','2026-10-14 19:00',thread_id='omt_old')] if not token else [self.message('today')],more=not token,token='messages-next' if not token else '')
            return self.response([])
        job=self.job();self.run_crawl(job,call)
        self.assertEqual(job['status'],'complete');self.assertEqual(job['chats_done'],2)
        self.assertEqual(job['messages'],3)
        self.assertNotIn('feishu:old-root',[r['id'] for r in db.records('2026-10-14')])
        self.assertEqual(len([c for c in calls if c[1]=='+threads-messages-list']),2)
        self.assertTrue(all('--start' not in c for c in calls if c[1]=='+chat-messages-list'))
    def test_repeated_cursor_never_reports_complete(self):
        def call(args,*_):
            if args[1]=='+chat-list':return self.response([{'chat_id':'c1'}],'chats')
            return self.response([self.message()],more=True,token='same')
        job=self.job();self.run_crawl(job,call)
        self.assertEqual(job['status'],'partial');self.assertEqual(job['chats_done'],0)
        self.assertEqual(job['messages'],1)
    def test_retry_uses_saved_cursor_and_skips_finished_chat(self):
        job=self.job();job.update(listed=True,chats=[{'chat_id':'c1','name':'第一群'},{'chat_id':'c2','name':'第二群'}],chat_index=0,completed_chats=['c1'],failed_cursors={'c2':'saved-page'})
        calls=[]
        def call(args,*_):calls.append(args);return self.response([self.message('remaining')])
        self.run_crawl(job,call)
        self.assertEqual(job['status'],'complete');self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][calls[0].index('--page-token')+1],'saved-page')
        self.assertEqual(calls[0][calls[0].index('--chat-id')+1],'c2')
    def test_browser_batch_idempotence_bounds_and_pause(self):
        job=self.job('browser');db.put('feishu_crawl',job)
        payload={'job_id':'scan','chat':{'chat_id':'browser:群','name':'群'},'messages':[self.message('today'),self.message('yesterday','2026-10-14 23:59'),self.message('after','2026-10-15 16:13'),{'message_id':'unknown','text':'缺少时间'}],'chat_complete':True,'chats_total':1}
        self.assertEqual(feishu.browser_batch(payload)['imported'],1)
        self.assertEqual(feishu.browser_batch(payload)['imported'],0)
        self.assertEqual(len(db.records('2026-10-15')),1)
        self.assertEqual(db.get('feishu_crawl')['messages'],1)
        feishu.pause()
        with self.assertRaises(ValueError):feishu.browser_batch(payload)
    def test_browser_partial_is_not_full_completion(self):
        db.put('feishu_crawl',self.job('browser'))
        out=feishu.browser_batch({'job_id':'scan','chat':{'chat_id':'c','name':'群'},'messages':[],'chat_complete':True,'chats_total':2,'finished':True,'enumeration_complete':True})
        self.assertEqual(out['job']['status'],'partial')
    def test_api_browser_position_deduplication_and_own_reminders(self):
        chat={'chat_id':'c','name':'群'}
        original=feishu.save_message(self.message('om_api',message_position='19'),chat,'bot')
        browser=feishu.save_message({'message_id':'numeric-dom','position':'19','timestamp':'2026-10-15T10:00:00+08:00','text':'版本跟进','sender_name':'同事'},chat,'browser')
        self.assertEqual(original,browser)
        self.assertEqual(len(db.records('2026-10-15')),1)
        self.assertFalse(feishu.save_message({'message_id':'notice','timestamp':db.now(),'text':'Workworld · 连接测试'},chat,'browser'))
    def test_thread_render_without_id_merges_with_main_message(self):
        chat={'chat_id':'c','name':'群'}
        a=feishu.save_message(self.message('dom-main'),chat,'browser')
        b=feishu.save_message({'timestamp':'2026-10-15T10:00:00+08:00','text':'版本跟进','sender_name':'同事','thread_id':'root'},chat,'browser')
        self.assertEqual(a,b);self.assertEqual(len(db.records('2026-10-15')),1)
    def test_missing_next_page_token_is_an_error(self):
        with self.assertRaises(RuntimeError):feishu.page({'data':{'has_more':True,'messages':[]}},'messages')
    def test_no_pagination_tokens_in_public_status(self):
        job=self.job();job.update(failed_cursors={'c':'private-cursor'},thread_cursors={'t':'other'},message_keys=['m'],errors=[{'cursor':'secret','error':'读取失败'}]);db.put('feishu_crawl',job)
        value=feishu.public_job()
        self.assertNotIn('failed_cursors',value);self.assertNotIn('thread_cursors',value);self.assertNotIn('cursor',value['errors'][0])

if __name__=='__main__':unittest.main()
