import copy
import unittest
from postgres_storage import PostgresStorage
from storage import StorageError


class FakePostgres(PostgresStorage):
    def __init__(self):
        super().__init__("postgresql://test@localhost/test")
        self.remote = {"config": {}, "duos": [{"id": "a", "blueShells": 10}]}
        self.version = 1
        self.write_id = None
        self.offline = False
        self.lose_response = False

    def fetch(self):
        if self.offline: raise StorageError("offline")
        self.cached, self.revision = copy.deepcopy(self.remote), self.version
        import time
        self.checked_at = time.monotonic()
        return self.remote, self.version, self.write_id

    def update(self, data, revision, write_id):
        if self.offline: raise StorageError("offline")
        if revision != self.version: return None
        self.remote = copy.deepcopy(data)
        self.version += 1
        self.write_id = write_id
        if self.lose_response: raise StorageError("response lost")
        return self.version


class PostgresTests(unittest.TestCase):
    def test_confirmed_commit_and_noop(self):
        store = FakePostgres()
        data = store.load()
        data["duos"][0]["blueShells"] = 9
        store.save(data)
        self.assertEqual(store.remote["duos"][0]["blueShells"], 9)
        self.assertNotIn("_storageRevision", store.remote)
        store.save(data)
        self.assertEqual(store.version, 2)

    def test_conflicting_update_is_not_overwritten(self):
        store = FakePostgres()
        data = store.load()
        store.version += 1
        store.remote["duos"][0]["blueShells"] = 8
        data["duos"][0]["blueShells"] = 9
        with self.assertRaises(StorageError): store.save(data)
        self.assertEqual(store.remote["duos"][0]["blueShells"], 8)
        self.assertEqual(store.load()["duos"][0]["blueShells"], 8)

    def test_lost_commit_response_is_reconciled(self):
        store = FakePostgres()
        data = store.load()
        data["duos"][0]["blueShells"] = 9
        store.lose_response = True
        store.save(data)
        self.assertEqual(data["_storageRevision"], 2)
        self.assertEqual(store.remote["duos"][0]["blueShells"], 9)

    def test_failure_blocks_writes_until_reconciled(self):
        store = FakePostgres()
        data = store.load()
        data["duos"][0]["blueShells"] = 9
        store.offline = True
        with self.assertRaises(StorageError): store.save(data)
        with self.assertRaises(StorageError): store.save(data)
        self.assertEqual(store.remote["duos"][0]["blueShells"], 10)
        store.offline = False
        store.reconcile()
        self.assertEqual(store.load()["duos"][0]["blueShells"], 10)

    def test_fresh_process_reads_remote_state(self):
        old = FakePostgres()
        data = old.load()
        data["duos"][0]["blueShells"] = 7
        old.save(data)
        new = FakePostgres()
        new.remote, new.version = old.remote, old.version
        self.assertEqual(new.load()["duos"][0]["blueShells"], 7)
