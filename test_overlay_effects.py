import copy
import json
from pathlib import Path
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch, MagicMock

import overlay_effects as effects
import server
import test_shell_penalties as fixtures
from storage import StorageError

WEBM = b'\x1aE\xdf\xa3' + b'\x00webm' + b'\x00' * 64


class EffectLogicTests(unittest.TestCase):
    def test_bulo_timing_is_in_snapshot_without_mutating_storage(self):
        db = {'overlayEffects': [{**effects.BUILTIN, 'kind':'video', 'id':effects.BULO_VIDEO_ID}]}
        selected = effects.choose(db)
        self.assertEqual(selected['senderRevealMs'], 6500)
        self.assertNotIn('senderRevealMs', db['overlayEffects'][0])

    def test_removal_is_reversible_without_changing_old_attack_snapshot(self):
        db = {}
        video = effects.validate_upload('Incorrecta',1200,WEBM)
        effects.add(db,video)
        attack = effects.snapshot(video)
        effects.remove(db,video['id'])
        self.assertEqual(len(effects.library(db)),1)
        self.assertFalse(effects.removed(db)[0]['active'])
        self.assertEqual(attack['id'],video['id'])
        effects.restore(db,video['id'])
        self.assertEqual(len(effects.library(db)),2)
        self.assertEqual(effects.removed(db),[])
        effects.set_active(db,video['id'],True)
        effects.set_active(db,effects.BUILTIN['id'],False)
        with self.assertRaises(ValueError): effects.remove(db,video['id'])

    def test_default_is_non_mutating_and_selection_is_snapshotted(self):
        db = {}
        self.assertEqual(effects.choose(db)['id'], effects.BUILTIN['id'])
        self.assertEqual(db, {})
        video = effects.validate_upload('Prueba', 1500, WEBM)
        effects.add(db, video)
        with patch.object(effects.secrets, 'choice', side_effect=lambda items: items[-1]) as draw:
            selected = effects.choose(db)
        self.assertEqual(len(draw.call_args.args[0]), 2)
        effects.set_active(db, video['id'], False)
        self.assertEqual(selected['id'], video['id'])
        self.assertNotIn('active', selected)
        self.assertEqual(effects.choose(db)['kind'], 'builtin')

    def test_rejects_invalid_media_limits_and_last_disabled(self):
        for name, duration, blob in [('',1000,WEBM),('x',float('nan'),WEBM),('x',31000,WEBM),
                                     ('x',1000,b'<html>'),('x',1000,b'x'*(effects.MAX_BYTES+1))]:
            with self.subTest(name=name,duration=duration):
                with self.assertRaises(ValueError): effects.validate_upload(name,duration,blob)
        with self.assertRaises(ValueError): effects.set_active({}, effects.BUILTIN['id'],False)

    def test_neon_media_uses_separate_parameterized_table_and_failure_is_reported(self):
        backend = MagicMock()
        cursor = backend.connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        effect = effects.validate_upload('Video',1000,WEBM)
        effects.media_bytes(effect['id'], 'unused', backend, WEBM)
        self.assertEqual(cursor.execute.call_args.args[1], (effect['id'],WEBM))
        cursor.fetchone.return_value = (memoryview(WEBM),)
        self.assertEqual(effects.media_bytes(effect['id'],'unused',backend),WEBM)
        backend.connect.side_effect = OSError('unavailable')
        with self.assertRaises(StorageError): effects.media_bytes(effect['id'],'unused',backend)


class EffectEndpointTests(unittest.TestCase):
    setUp = fixtures.ShellEndpointTests.setUp
    tearDown = fixtures.ShellEndpointTests.tearDown
    post = fixtures.ShellEndpointTests.post

    def upload(self, pin='9999', blob=WEBM, name='Nueva', origin=None):
        headers = {'Content-Type':'video/webm','X-Admin-Pin':pin,'X-Overlay-Name':name,'X-Overlay-Duration':'1200'}
        if origin: headers['Origin'] = origin
        request = urllib.request.Request(self.base+'/api/admin/overlay/upload',data=blob,headers=headers)
        return urllib.request.urlopen(request,timeout=5)

    def get(self,path,headers=None):
        return urllib.request.urlopen(urllib.request.Request(self.base+path,headers=headers or {}),timeout=5)

    def test_admin_remove_restore_keeps_bytes_available(self):
        with self.upload() as response: video = json.load(response)['effects'][-1]
        result = self.post('/api/admin/overlay',{'authPin':'9999','action':'remove','id':video['id']})
        self.assertEqual(len(result['effects']),1)
        self.assertEqual(result['removedEffects'][0]['id'],video['id'])
        with self.get(video['url']) as response: self.assertEqual(response.read(),WEBM)
        result = self.post('/api/admin/overlay',{'authPin':'9999','action':'restore','id':video['id']})
        self.assertFalse(result['effects'][-1]['active'])

    def test_upload_auth_persistence_ranges_and_snapshot_for_both_receivers(self):
        with self.assertRaises(urllib.error.HTTPError) as error: self.upload(pin='wrong')
        self.assertEqual(error.exception.code,401)
        with self.assertRaises(urllib.error.HTTPError) as error: self.upload(origin='https://foreign.test')
        self.assertEqual(error.exception.code,403)
        with self.upload() as response:
            video = json.load(response)['effects'][-1]
        self.assertTrue(video['active'])
        self.assertNotIn('payload', json.dumps(server.load_db()))
        self.assertTrue((Path(server.DB_FILE).parent/'overlay-media'/(video['id']+'.webm')).is_file())
        with self.get(video['url'],{'Range':'bytes=2-8'}) as response:
            self.assertEqual(response.status,206)
            self.assertEqual(response.read(),WEBM[2:9])
            self.assertIn('immutable',response.headers['Cache-Control'])
        for path in ['/api/overlay/media/not-a-hash','/overlay-media/'+video['id']+'.webm']:
            with self.assertRaises(urllib.error.HTTPError) as error: self.get(path)
            self.assertEqual(error.exception.code,404)
        self.post('/api/admin/overlay',{'authPin':'9999','action':'toggle','id':effects.BUILTIN['id'],'active':False})
        sender = self.post('/api/player/login',{'teamId':'a','password':'a-pass'})['sessionToken']
        first = self.post('/api/player/login',{'teamId':'b','password':'b-pass'})['sessionToken']
        second = self.post('/api/player/login',{'teamId':'b','password':'b-pass'})['sessionToken']
        attack = self.post('/api/player/launch-shell',{'targetId':'b','sessionToken':sender})['attack']
        self.assertEqual(attack['overlayEffect']['id'],video['id'])
        self.post('/api/admin/overlay',{'authPin':'9999','action':'toggle','id':effects.BUILTIN['id'],'active':True})
        self.post('/api/admin/overlay',{'authPin':'9999','action':'toggle','id':video['id'],'active':False})
        for token in (first,second):
            self.assertEqual(server.receiver_notification_state(token)['attacks'][0]['overlayEffect'],attack['overlayEffect'])
        with self.get(video['url']) as response: self.assertEqual(response.read(),WEBM)
        with self.get('/api/overlay/effects') as response:
            self.assertEqual([v['kind'] for v in json.load(response)['effects']],['builtin'])
        with patch.object(effects.secrets,'choice', side_effect=AssertionError('Must not redraw on read')):
            self.assertEqual(server.load_db()['shellAttacks'][0]['overlayEffect'],attack['overlayEffect'])
            server.receiver_notification_state(first)

    def test_duplicate_invalid_upload_and_failed_save_do_not_publish(self):
        before = copy.deepcopy(server.load_db())
        with self.assertRaises(urllib.error.HTTPError) as error: self.upload(blob=b'<html>'+b'x'*50)
        self.assertEqual(error.exception.code,400)
        self.assertEqual(server.load_db(),before)
        with patch.object(server,'save_db',side_effect=StorageError('simulated')):
            with self.assertRaises(urllib.error.HTTPError) as error: self.upload()
        self.assertEqual(error.exception.code,503)
        self.assertEqual(server.load_db(),before)
        with self.upload() as response: self.assertEqual(response.status,200)
        with self.assertRaises(urllib.error.HTTPError) as error: self.upload()
        self.assertEqual(error.exception.code,400)
        self.assertEqual(len(effects.library(server.load_db())),2)


if __name__ == '__main__': unittest.main()
