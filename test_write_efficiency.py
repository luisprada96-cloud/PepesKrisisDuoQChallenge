"""Avoid no-op writes without delaying real mutations or rotating recovery data."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
import storage
import test_neon_bandwidth as fixtures


class LocalWriteEfficiencyTests(unittest.TestCase):
    def test_repeated_identical_writes_do_not_touch_files_or_rotate_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'db.json'
            self.assertTrue(storage.write_json(target, {'value': 1}))
            self.assertTrue(storage.write_json(target, {'value': 2}))
            before = target.read_bytes()
            backup = Path(str(target)+'.previous.bak')
            recovery = backup.read_bytes()
            with patch.object(storage, '_replace_bytes', side_effect=AssertionError('No disk writes')):
                for _ in range(100):
                    self.assertFalse(storage.write_json(target, {'value': 2}))
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(backup.read_bytes(), recovery)
            self.assertEqual(storage.read_json(backup), {'value': 1})

    def test_first_save_creates_file_but_identical_save_does_not_create_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'secrets.json'
            self.assertTrue(storage.write_json(target, {'key': 'test-only'}))
            self.assertFalse(storage.write_json(target, {'key': 'test-only'}))
            self.assertFalse(Path(str(target)+'.previous.bak').exists())

    def test_distinct_json_types_are_still_written(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'db.json'
            storage.write_json(target, {'value': True})
            self.assertTrue(storage.write_json(target, {'value': 1}))
            self.assertIs(type(storage.read_json(target)['value']), int)
            self.assertTrue(storage.read_json(str(target)+'.previous.bak')['value'])


class RemoteWriteEfficiencyTests(unittest.TestCase):
    setUp = fixtures.NeonBandwidthEndpointTests.setUp
    tearDown = fixtures.NeonBandwidthEndpointTests.tearDown

    def test_noop_save_skips_sql_local_mirror_and_summary_invalidation(self):
        data = server.load_db()
        version = self.backend.version
        marker = object()
        with patch.object(server, 'summary_cache', {'key': marker}), patch.object(server, 'write_json') as disk:
            for _ in range(100):
                self.assertFalse(server.save_db(copy.deepcopy(data)))
            disk.assert_not_called()
            self.assertIs(server.summary_cache['key'], marker)
        self.assertEqual(self.backend.version, version)
        self.assertEqual(self.backend.update_attempts, 0)

    def test_real_mutation_is_written_immediately_and_repeated_save_is_noop(self):
        data = server.load_db()
        before = data['duos'][0]['blueShells']
        data['duos'][0]['blueShells'] = before + 1
        with patch.object(server, 'write_json', wraps=server.write_json) as disk:
            self.assertTrue(server.save_db(data))
            self.assertFalse(server.save_db(data))
            disk.assert_called_once()
        self.assertEqual(self.backend.update_attempts, 1)
        self.assertEqual(self.backend.remote['duos'][0]['blueShells'], before + 1)
        self.assertEqual(storage.read_json(server.DB_FILE)['duos'][0]['blueShells'], before + 1)


if __name__ == '__main__':
    unittest.main()
