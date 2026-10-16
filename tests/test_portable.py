import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import config
import demo
import engine
import feishu_api
import sources
import storage as db

class PortableTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.p=patch.object(db,'DATA',Path(self.temp.name)/'data');self.p.start();db.init()
    def tearDown(self):self.p.stop();self.temp.cleanup()
    def test_private_account_is_not_an_initial_default(self):
        s=db.get('settings');self.assertEqual(s['notification_chat'],'');self.assertFalse(s['notify_feishu']);self.assertFalse(s['auto_night'])
    def test_feishu_store_is_isolated_from_bridge_environment(self):
        with patch.dict(os.environ,{'LARK_CHANNEL_CONFIG':'private-bridge','LARKSUITE_CLI_CONFIG_DIR':'wrong-store','OPENCLAW_HOME':'wrong-agent'}):
            env=config.feishu_env(db.DATA)
        self.assertNotIn('LARK_CHANNEL_CONFIG',env);self.assertNotIn('OPENCLAW_HOME',env)
        self.assertEqual(env['LARKSUITE_CLI_CONFIG_DIR'],str(db.DATA/'feishu-cli'))
        self.assertEqual((db.DATA/'feishu-cli').stat().st_mode&0o777,0o700)
    def test_no_history_or_memory_is_valid_for_a_new_install(self):
        with patch.object(sources,'CODEX',Path(self.temp.name)/'empty-codex'):
            self.assertEqual(sources.sync_codex(db.today()),{'threads':0,'memories':0,'read_errors':0});self.assertEqual(sources.recent_codex(),[])
    def test_configured_data_path_excludes_own_runs(self):
        self.assertTrue(sources.internal_chat({'id':'a','cwd':str(db.DATA/'runs/a')}))
        self.assertFalse(sources.internal_chat({'id':'b','cwd':str(Path(self.temp.name)/'project')}))
    def test_cli_rollout_fallback(self):
        home=Path(self.temp.name)/'codex';folder=home/'sessions';folder.mkdir(parents=True)
        file=folder/'one.jsonl';file.write_text(json.dumps({'type':'session_meta','payload':{'id':'example','cwd':str(home/'project')}})+'\n')
        a,b=sources.day_range(db.today())
        with patch.object(sources,'CODEX',home):rows=sources.thread_rows(a,b)
        self.assertEqual(rows[0]['id'],'example')
    def test_demo_uses_no_real_sources(self):
        with patch.object(sources,'lark') as cloud,patch.object(sources,'recent_codex') as history:demo.seed()
        cloud.assert_not_called();history.assert_not_called();self.assertEqual(len(db.night_work()),1)
        self.assertFalse(db.get('settings')['schedule_enabled']);self.assertEqual(len(db.todos()),1)
    def test_notifications_resolve_only_current_authorized_user(self):
        cfg=db.get('settings');cfg['notify_feishu']=True;db.put('settings',cfg)
        with patch.object(feishu_api,'own_user',return_value={'open_id':'ou_synthetic_user'}) as who,patch.object(sources,'lark',return_value={'data':{'message_id':'synthetic'}}) as send:
            result=engine.notify('Example','Synthetic reminder')
        who.assert_called_once_with(refresh=True);args=send.call_args.args[0]
        self.assertIn('--user-id',args);self.assertNotIn('--chat-id',args);self.assertEqual(result['feishu_status'],'sent')
    def test_failed_identity_check_never_sends(self):
        cfg=db.get('settings');cfg['notify_feishu']=True;db.put('settings',cfg)
        with patch.object(feishu_api,'own_user',return_value={}),patch.object(sources,'lark') as send:result=engine.notify('Example','Synthetic')
        send.assert_not_called();self.assertEqual(result['feishu_status'],'failed')

if __name__=='__main__':unittest.main()
