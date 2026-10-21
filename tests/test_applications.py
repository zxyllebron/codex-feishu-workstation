import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import applications as app
import config
import engine
import sources
import storage as db

class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.data=patch.object(db,'DATA',self.root/'data');self.data.start();self.addCleanup(self.data.stop);db.init()
    def record(self,**changes):
        return {'id':'gmail:one','kind':'gmail','title':'Application Confirmation','updated':'2026-10-17T10:00:00+08:00',
            'text':'Application submitted. password=do-not-store\nDetails\nhttps://example.edu/status?token=private',
            'source_url':'https://mail.google.com/mail/u/0/#all/one','direction':'received',**changes}
    def test_import_redacts_credentials_and_rejects_script_links(self):
        app.import_connector({'records':[self.record(source_url='javascript:alert(1)')]})
        record=db.evidence_records(['gmail:one'])[0]
        self.assertNotIn('do-not-store',record['text']);self.assertNotIn('token=private',record['text']);self.assertEqual(record['source_url'],'')
    def test_idempotency_and_older_portal_snapshot_cannot_replace_newer(self):
        snapshot={'records':[self.record()]};self.assertEqual(app.import_connector(snapshot),1);self.assertEqual(app.import_connector(snapshot),0)
        self.assertEqual(app.import_connector({'records':[self.record(updated='2026-10-16T10:00:00+08:00',text='Old')]}),0)
        self.assertNotEqual(db.evidence_records(['gmail:one'])[0]['text'],'Old')
    def test_invalid_source_and_naive_timestamp_rejected(self):
        for record in [self.record(kind='feishu'),self.record(updated='2026-10-17T10:00:00')]:
            with self.assertRaises(ValueError):app.import_connector({'records':[record]})
    def test_contacts_are_separate_from_formal_applications(self):
        record=self.record(title='Prospective PhD Student',direction='sent',recipients=['Professor <p@example.edu>'],thread_id='a')
        incoming=self.record(id='gmail:reply',thread_id='a',title='Automatic reply: Prospective PhD',updated='2026-10-17T11:00:00+08:00')
        result=app.contacts([record,incoming]);self.assertEqual(len(result),1);self.assertEqual(result[0]['stage'],'auto_reply')
    def test_disabled_feishu_never_invokes_its_sync(self):
        with patch.dict(config.SETTINGS,{'feishu_enabled':False,'codex_enabled':False,'applications_enabled':False}),patch.object(sources,'sync_feishu') as remote:
            self.assertTrue(sources.sync_all()['feishu']['disabled'])
        remote.assert_not_called()
    def test_unverifiable_model_result_does_not_replace_previous_tracker(self):
        db.put('applications',{'items':[{'id':'keep'}]})
        invalid={'applications':[{**dict.fromkeys(app.FIELDS,''),'stage':'submitted','evidence_ids':['fabricated']}],'coverage':''}
        with patch.object(engine,'invoke',return_value=json.dumps(invalid)):
            self.assertIn('error',app.reconcile())
        self.assertEqual(db.get('applications')['items'][0]['id'],'keep')
    def test_model_output_cannot_claim_current_portal_verification(self):
        app.import_connector({'records':[self.record()]})
        item={**dict.fromkeys(app.FIELDS,''),'institution':'Example','program':'Robotics','stage':'submitted','evidence_ids':['gmail:one']}
        with patch.object(engine,'invoke',return_value=json.dumps({'applications':[item],'coverage':'Mail evidence only'})):
            result=app.reconcile()
        self.assertIsNone(result['items'][0]['portal_checked_at']);self.assertEqual(result['items'][0]['portal_state'],'needs_verification')
    def test_note_scan_avoids_accounts_and_backups(self):
        root=self.root/'notes';root.mkdir();(root/'申请状态.md').write_text('Saved, not submitted',encoding='utf-8')
        folder=root/'backups_old';folder.mkdir();(folder/'申请状态.md').write_text('Old',encoding='utf-8')
        (root/'账号密码.md').write_text('Secret',encoding='utf-8')
        with patch.dict(config.SETTINGS,{'application_roots':[str(root)]}):self.assertEqual(app.sync_notes(),1)

    def test_gmail_source_url_removes_credentials_but_preserves_message_fragment(self):
        valid='https://mail.google.com/mail/u/0/?token=private#all/example1'
        app.import_connector({'records':[self.record(source_url=valid)]})
        self.assertEqual(db.evidence_records(['gmail:one'])[0]['source_url'],'https://mail.google.com/mail/u/0/#all/example1')
        for value in ['https://user:secret@mail.google.com/mail/u/0/#all/one','https://mail.google.com.evil.example/mail/',
                      'https://mail.google.com:9999/mail/']:
            self.assertEqual(app.safe_gmail_url(value),'')

    def test_metadata_only_changes_require_reconciliation(self):
        record=self.record();digest=app.evidence_digest([record])
        self.assertNotEqual(digest,app.evidence_digest([{**record,'updated':'2026-10-18T10:00:00+08:00'}]))
        self.assertNotEqual(digest,app.evidence_digest([{**record,'direction':'sent'}]))

    def test_disabled_codex_does_not_read_application_chat_history(self):
        with patch.dict(config.SETTINGS,{'codex_enabled':False,'application_roots':[]}),patch.object(app,'sync_memories') as history:
            self.assertEqual(app.sync_local()['memories'],0)
        history.assert_not_called()

    def test_messages_without_thread_ids_cannot_be_paired_as_replies(self):
        outgoing=self.record(title='Prospective PhD Student',direction='sent',recipients=['Professor <p@example.edu>'])
        incoming=self.record(id='gmail:unrelated',updated='2026-10-18T10:00:00+08:00')
        self.assertEqual(app.contacts([outgoing,incoming])[0]['stage'],'contacted')

if __name__=='__main__':unittest.main()
