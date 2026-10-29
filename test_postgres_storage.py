import copy
import json
import unittest
from unittest.mock import patch
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
        self.update_attempts = 0

    def fetch(self):
        if self.offline: raise StorageError("offline")
        self.cached, self.revision = copy.deepcopy(self.remote), self.version
        import time
        self.checked_at = time.monotonic()
        return self.remote, self.version, self.write_id

    def update(self, data, revision, write_id):
        self.update_attempts += 1
        if self.offline: raise StorageError("offline")
        if revision != self.version: return None
        self.remote = copy.deepcopy(data)
        self.version += 1
        self.write_id = write_id
        if self.lose_response: raise StorageError("response lost")
        return self.version


class CountingPostgres(FakePostgres):
    """Exercise the real read query with an in-memory Postgres wire substitute."""
    fetch = PostgresStorage.fetch

    def __init__(self):
        super().__init__()
        self.queries = []
        self.payload_reads = 0
        self.wire_bytes = 0
        self.empty = False

    def connect(self):
        if self.offline:
            raise StorageError('offline')
        owner = self

        class Connection:
            def __enter__(self): return self
            def __exit__(self, *args): return False

            def execute(self, query, params):
                query = ' '.join(query.split())
                if 'SELECT CASE WHEN revision = %s THEN NULL ELSE payload END' not in query:
                    raise AssertionError('Reads must be conditional and parameterized')
                owner.queries.append((query, params))
                self.row = None
                if not owner.empty:
                    payload = None if params[0] == owner.version else copy.deepcopy(owner.remote)
                    owner.payload_reads += int(payload is not None)
                    self.row = (payload, owner.version, owner.write_id)
                    owner.wire_bytes += len(json.dumps(self.row).encode())
                return self

            def fetchone(self): return self.row

        return Connection()


class ConditionalReadTests(unittest.TestCase):
    def test_hundred_unchanged_checks_transfer_one_document_not_one_hundred(self):
        store = CountingPostgres()
        store.remote['duos'][0]['history'] = ['x' * 200000]
        document_size = len(json.dumps(store.remote).encode())
        with patch('postgres_storage.time.monotonic') as clock:
            for minute in range(100):
                clock.return_value = minute * 61
                self.assertEqual(store.load()['duos'][0]['blueShells'], 10)
        self.assertEqual(len(store.queries), 100)
        self.assertEqual(store.payload_reads, 1)
        self.assertEqual(store.queries[0][1], (None,))
        self.assertTrue(all(params == (1,) for _, params in store.queries[1:]))
        self.assertLess(store.wire_bytes, document_size * 1.02)
        self.assertLess(store.wire_bytes, document_size * 100 * .02)

    def test_sixty_second_check_interval_is_unchanged(self):
        store = CountingPostgres()
        with patch('postgres_storage.time.monotonic') as clock:
            clock.return_value = 100
            store.load()
            clock.return_value = 159.99
            store.load()
            self.assertEqual(len(store.queries), 1)
            clock.return_value = 160
            store.load()
            self.assertEqual(len(store.queries), 2)
        self.assertEqual(store.payload_reads, 1)

    def test_external_change_downloads_the_new_revision(self):
        store = CountingPostgres()
        store.load()
        store.remote['duos'][0]['blueShells'] = 8
        store.version += 1
        store.checked_at -= 61
        data = store.load()
        self.assertEqual(data['duos'][0]['blueShells'], 8)
        self.assertEqual(data['_storageRevision'], 2)
        self.assertEqual(store.payload_reads, 2)
        store.checked_at -= 61
        store.load()
        self.assertEqual(store.payload_reads, 2)

    def test_own_write_is_available_immediately_without_another_download(self):
        store = CountingPostgres()
        data = store.load()
        data['duos'][0]['blueShells'] = 9
        store.save(data)
        self.assertEqual(store.load()['duos'][0]['blueShells'], 9)
        store.checked_at -= 61
        self.assertEqual(store.load()['duos'][0]['blueShells'], 9)
        self.assertEqual(store.queries[-1][1], (2,))
        self.assertEqual(store.payload_reads, 1)

    def test_fetch_and_load_return_complete_detached_snapshots(self):
        store = CountingPostgres()
        store.load()['duos'][0]['blueShells'] = 123
        snapshot, revision, _ = store.fetch()
        self.assertEqual(revision, 1)
        self.assertEqual(snapshot['duos'][0]['blueShells'], 10)
        snapshot['duos'][0]['blueShells'] = 456
        self.assertEqual(store.load()['duos'][0]['blueShells'], 10)
        self.assertEqual(store.payload_reads, 1)

    def test_expired_cache_does_not_hide_a_database_outage(self):
        store = CountingPostgres()
        store.load()
        store.offline = True
        store.checked_at -= 61
        with self.assertRaises(StorageError): store.load()
        with self.assertRaises(StorageError): store.load()
        store.offline = False
        self.assertEqual(store.load()['duos'][0]['blueShells'], 10)
        self.assertEqual(store.payload_reads, 1)

    def test_empty_or_invalid_remote_state_never_becomes_an_empty_tournament(self):
        for empty in (True, False):
            with self.subTest(empty=empty):
                store = CountingPostgres()
                store.load()
                store.empty = empty
                store.version += 1
                store.remote = {'invalid': True}
                store.checked_at -= 61
                with self.assertRaises(StorageError): store.load()
                self.assertEqual(store.cached['duos'][0]['blueShells'], 10)

    def test_conflict_still_reloads_and_never_overwrites_external_changes(self):
        store = CountingPostgres()
        stale = store.load()
        store.version += 1
        store.remote['duos'][0]['blueShells'] = 8
        stale['duos'][0]['blueShells'] = 9
        with self.assertRaises(StorageError): store.save(stale)
        self.assertEqual(store.remote['duos'][0]['blueShells'], 8)
        self.assertEqual(store.load()['duos'][0]['blueShells'], 8)
        self.assertEqual(store.queries[-1][1], (None,))

    def test_lost_commit_response_is_confirmed_before_using_the_cache(self):
        store = CountingPostgres()
        data = store.load()
        data['duos'][0]['blueShells'] = 9
        store.lose_response = True
        store.save(data)
        self.assertEqual(data['_storageRevision'], 2)
        self.assertIsNone(store.pending)
        self.assertEqual(store.payload_reads, 2)
        store.checked_at -= 61
        self.assertEqual(store.load()['duos'][0]['blueShells'], 9)
        self.assertEqual(store.payload_reads, 2)

    def test_unconfirmed_write_stays_blocked_until_reconciliation(self):
        store = CountingPostgres()
        data = store.load()
        data['duos'][0]['blueShells'] = 9
        store.offline = True
        with self.assertRaises(StorageError): store.save(data)
        with self.assertRaises(StorageError): store.save(data)
        self.assertIsNotNone(store.pending)
        store.offline = False
        store.reconcile()
        self.assertIsNone(store.pending)
        self.assertEqual(store.load()['duos'][0]['blueShells'], 10)

    def test_cold_cache_with_a_known_revision_still_requests_the_document(self):
        store = CountingPostgres()
        store.load()
        store.cached = None
        self.assertEqual(store.load()['duos'][0]['blueShells'], 10)
        self.assertEqual(store.queries[-1][1], (None,))
        self.assertEqual(store.payload_reads, 2)


class PostgresTests(unittest.TestCase):
    def test_confirmed_commit_and_noop(self):
        store = FakePostgres()
        data = store.load()
        data["duos"][0]["blueShells"] = 9
        self.assertTrue(store.save(data))
        self.assertEqual(store.remote["duos"][0]["blueShells"], 9)
        self.assertNotIn("_storageRevision", store.remote)
        self.assertFalse(store.save(data))
        self.assertEqual(store.version, 2)
        self.assertEqual(store.update_attempts, 1)

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
