# standard libraries
import logging
import unittest
import uuid

# third party libraries
# None

# local libraries
from nion.swift.model import Cache


class TestSuspendableCacheClass(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_get_cached_value_works_while_suspended(self):
        suspendable_cache = Cache.SuspendableCache(Cache.DictStorageCache())
        suspendable_cache.uuid = uuid.uuid4()
        suspendable_cache.set_cached_value(suspendable_cache, "key", 999, False)
        suspendable_cache.suspend_cache()
        self.assertEqual(suspendable_cache.get_cached_value(suspendable_cache, "key", None), 999)
        suspendable_cache.spill_cache()

    def test_is_cached_value_dirty_works_while_suspended(self):
        suspendable_cache = Cache.SuspendableCache(Cache.DictStorageCache())
        suspendable_cache.uuid = uuid.uuid4()
        suspendable_cache.set_cached_value(suspendable_cache, "key", 999, False)
        suspendable_cache.set_cached_value_dirty(suspendable_cache, "key", False)
        suspendable_cache.suspend_cache()
        self.assertFalse(suspendable_cache.is_cached_value_dirty(suspendable_cache, "key"))
        suspendable_cache.spill_cache()

    def test_remove_cached_value_works_while_suspended(self):
        suspendable_cache = Cache.SuspendableCache(Cache.DictStorageCache())
        suspendable_cache.uuid = uuid.uuid4()
        suspendable_cache.set_cached_value(suspendable_cache, "key", 999, False)
        suspendable_cache.suspend_cache()
        self.assertEqual(suspendable_cache.get_cached_value(suspendable_cache, "key", None), 999)
        suspendable_cache.remove_cached_value(suspendable_cache, "key")
        self.assertIsNone(suspendable_cache.get_cached_value(suspendable_cache, "key", None))
        suspendable_cache.spill_cache()
        self.assertIsNone(suspendable_cache.get_cached_value(suspendable_cache, "key", None))

    def test_spill_does_not_remove_value_that_has_been_set(self):
        suspendable_cache = Cache.SuspendableCache(Cache.DictStorageCache())
        suspendable_cache.uuid = uuid.uuid4()
        suspendable_cache.remove_cached_value(suspendable_cache, "key")
        suspendable_cache.set_cached_value(suspendable_cache, "key", True, False)
        suspendable_cache.suspend_cache()
        suspendable_cache.spill_cache()
        self.assertTrue(suspendable_cache.get_cached_value(suspendable_cache, "key", False))

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
