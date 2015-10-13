# standard libraries
import copy
import functools
import logging
import os
import pickle
import queue
import sqlite3
import sys
import threading
import time

# third party libraries
# None

# local libraries
from nion.ui import Observable


class TracingCache(object):

    def __init__(self, storage_cache):
        self.__storage_cache = storage_cache

    def suspend_cache(self):
        logging.debug("%s.suspend_cache()", id(self))
        self.__storage_cache.suspend_cache()

    def spill_cache(self):
        logging.debug("%s.spill_cache()", id(self))
        self.__storage_cache.spill_cache()

    def set_cached_value(self, object, key, value, dirty=False):
        logging.debug("%s.set_cached_value(%s, %s, %s, %s)", id(self), id(object), key, value, dirty)
        self.__storage_cache.set_cached_value(object, key, value, dirty)

    def get_cached_value(self, object, key, default_value=None):
        logging.debug("%s.get_cached_value(%s, %s, %s)", id(self), id(object), key, default_value)
        result = self.__storage_cache.get_cached_value(object, key, default_value)
        logging.debug("# %s", result)
        return result

    def remove_cached_value(self, object, key):
        logging.debug("%s.remove_cached_value(%s, %s)", id(self), object, key)
        self.__storage_cache.remove_cached_value(object, key)

    def is_cached_value_dirty(self, object, key):
        logging.debug("%s.is_cached_value_dirty(%s, %s)", id(self), id(object), key)
        result = self.__storage_cache.is_cached_value_dirty(object, key)
        logging.debug("# %s", result)
        return result

    def set_cached_value_dirty(self, object, key, dirty=True):
        logging.debug("%s.set_cached_value_dirty(%s, %s, %s)", id(self), object, key, dirty)
        self.__storage_cache.set_cached_value_dirty(object, key, dirty)


class SuspendableCache(object):

    def __init__(self, storage_cache, trace=False):
        self.__storage_cache = storage_cache
        self.__cache = dict()
        self.__cache_remove = dict()
        self.__cache_dirty = dict()
        self.__cache_mutex = threading.RLock()
        self.__cache_delayed = False

    # the cache system stores values that are expensive to calculate for quick retrieval.
    # an item can be marked dirty in the cache so that callers can determine whether that
    # value needs to be recalculated. marking a value as dirty doesn't affect the current
    # value in the cache. callers can still retrieve the latest value for an item in the
    # cache even when it is marked dirty. this way the cache is used to retrieve the best
    # available data without doing additional calculations.

    def suspend_cache(self):
        with self.__cache_mutex:
            self.__cache_delayed = True

    # move local cache items into permanent cache when transaction is finished.
    def spill_cache(self):
        with self.__cache_mutex:
            cache_copy = copy.copy(self.__cache)
            cache_dirty_copy = copy.copy(self.__cache_dirty)
            cache_remove_copy = copy.copy(self.__cache_remove)
            self.__cache.clear()
            self.__cache_remove.clear()
            self.__cache_dirty.clear()
            self.__cache_delayed = False
        if self.__storage_cache:
            for object_id, (object, object_dict) in iter(cache_copy.items()):
                _, object_dirty_dict = cache_dirty_copy.get(id(object), (object, dict()))
                for key, value in iter(object_dict.items()):
                    dirty = object_dirty_dict.get(key, False)
                    self.__storage_cache.set_cached_value(object, key, value, dirty)
            for object_id, (object, key_list) in iter(cache_remove_copy.items()):
                for key in key_list:
                    self.__storage_cache.remove_cached_value(object, key)

    # update the value in the cache. usually updating a value in the cache
    # means it will no longer be dirty.
    def set_cached_value(self, object, key, value, dirty=False):
        # if transaction count is 0, cache directly
        if self.__storage_cache and not self.__cache_delayed:
            self.__storage_cache.set_cached_value(object, key, value, dirty)
        # otherwise, store it temporarily until transaction is finished
        else:
            with self.__cache_mutex:
                _, object_dict = self.__cache.setdefault(id(object), (object, dict()))
                _, object_list = self.__cache_remove.get(id(object), (object, list()))
                _, object_dirty_dict = self.__cache_dirty.setdefault(id(object), (object, dict()))
                object_dict[key] = value
                object_dirty_dict[key] = dirty
                if key in object_list:
                    object_list.remove(key)

    # grab the last cached value, if any, from the cache.
    def get_cached_value(self, object, key, default_value=None):
        # first check temporary cache.
        with self.__cache_mutex:
            _, object_dict = self.__cache.get(id(object), (object, dict()))
            if key in object_dict:
                return object_dict.get(key)
        # not there, go to cache db
        if self.__storage_cache:
            return self.__storage_cache.get_cached_value(object, key, default_value)
        return default_value

    # removing values from the cache happens immediately under a transaction.
    # this is an area of improvement if it becomes a bottleneck.
    def remove_cached_value(self, object, key):
        # remove it from the cache db.
        if self.__storage_cache and not self.__cache_delayed:
            self.__storage_cache.remove_cached_value(object, key)
        else:
            # if its in the temporary cache, remove it
            with self.__cache_mutex:
                _, object_dict = self.__cache.get(id(object), (object, dict()))
                _, object_list = self.__cache_remove.setdefault(id(object), (object, list()))
                _, object_dirty_dict = self.__cache_dirty.get(id(object), (object, dict()))
                if key in object_dict:
                    del object_dict[key]
                if key in object_dirty_dict:
                    del object_dirty_dict[key]
                if key not in object_list:
                    object_list.append(key)

    # determines whether the item in the cache is dirty.
    def is_cached_value_dirty(self, object, key):
        # check the temporary cache first
        with self.__cache_mutex:
            _, object_dirty_dict = self.__cache_dirty.get(id(object), (object, dict()))
            if key in object_dirty_dict:
                return object_dirty_dict[key]
        # not there, go to the db cache
        if self.__storage_cache:
            return self.__storage_cache.is_cached_value_dirty(object, key)
        return True

    # set whether the cache value is dirty.
    def set_cached_value_dirty(self, object, key, dirty=True):
        # go directory to the db cache if not under a transaction
        if self.__storage_cache and not self.__cache_delayed:
            self.__storage_cache.set_cached_value_dirty(object, key, dirty)
        # otherwise mark it in the temporary cache
        else:
            with self.__cache_mutex:
                _, object_dirty_dict = self.__cache_dirty.setdefault(id(object), (object, dict()))
                object_dirty_dict[key] = dirty


class Cacheable(object):

    def __init__(self):
        super(Cacheable, self).__init__()
        self.__storage_cache = None
        self.__cache = dict()
        self.__cache_remove = list()
        self.__cache_dirty = dict()
        self.__cache_mutex = threading.RLock()
        self.__cache_delayed = False

    def get_storage_cache(self):
        return self.__storage_cache
    def set_storage_cache(self, storage_cache):
        self.__storage_cache = storage_cache
        self.storage_cache_changed(storage_cache)
        self.spill_cache()
    storage_cache = property(get_storage_cache, set_storage_cache)

    def storage_cache_changed(self, storage_cache):
        pass

    # the cache system stores values that are expensive to calculate for quick retrieval.
    # an item can be marked dirty in the cache so that callers can determine whether that
    # value needs to be recalculated. marking a value as dirty doesn't affect the current
    # value in the cache. callers can still retrieve the latest value for an item in the
    # cache even when it is marked dirty. this way the cache is used to retrieve the best
    # available data without doing additional calculations.

    # move local cache items into permanent cache when transaction is finished.
    def spill_cache(self):
        with self.__cache_mutex:
            cache_copy = copy.copy(self.__cache)
            cache_dirty_copy = copy.copy(self.__cache_dirty)
            cache_remove = copy.copy(self.__cache_remove)
            self.__cache.clear()
            self.__cache_remove = list()
            self.__cache_dirty.clear()
        if self.storage_cache:
            for key, value in iter(cache_copy.items()):
                self.storage_cache.set_cached_value(self, key, value, cache_dirty_copy.get(key, False))
            for key in cache_remove:
                self.storage_cache.remove_cached_value(self, key)

    # update the value in the cache. usually updating a value in the cache
    # means it will no longer be dirty.
    def set_cached_value(self, key, value, dirty=False):
        # if transaction count is 0, cache directly
        if self.storage_cache and not self.__cache_delayed:
            self.storage_cache.set_cached_value(self, key, value, dirty)
        # otherwise, store it temporarily until transaction is finished
        else:
            with self.__cache_mutex:
                self.__cache[key] = value
                self.__cache_dirty[key] = dirty
                if key in self.__cache_remove:
                    self.__cache_remove.remove(key)

    # grab the last cached value, if any, from the cache.
    def get_cached_value(self, key, default_value=None):
        # first check temporary cache.
        with self.__cache_mutex:
            if key in self.__cache:
                return self.__cache.get(key)
        # not there, go to cache db
        if self.storage_cache:
            return self.storage_cache.get_cached_value(self, key, default_value)
        return default_value

    # removing values from the cache happens immediately under a transaction.
    # this is an area of improvement if it becomes a bottleneck.
    def remove_cached_value(self, key):
        # remove it from the cache db.
        if self.storage_cache and not self.__cache_delayed:
            self.storage_cache.remove_cached_value(self, key)
        # if its in the temporary cache, remove it
        with self.__cache_mutex:
            if key in self.__cache:
                del self.__cache[key]
            if key in self.__cache_dirty:
                del self.__cache_dirty[key]
            if key not in self.__cache_remove:
                self.__cache_remove.append(key)

    # determines whether the item in the cache is dirty.
    def is_cached_value_dirty(self, key):
        # check the temporary cache first
        with self.__cache_mutex:
            if key in self.__cache_dirty:
                return self.__cache_dirty[key]
        # not there, go to the db cache
        if self.storage_cache:
            return self.storage_cache.is_cached_value_dirty(self, key)
        return True

    # set whether the cache value is dirty.
    def set_cached_value_dirty(self, key, dirty=True):
        # go directory to the db cache if not under a transaction
        if self.storage_cache and not self.__cache_delayed:
            self.storage_cache.set_cached_value_dirty(self, key, dirty)
        # otherwise mark it in the temporary cache
        else:
            with self.__cache_mutex:
                self.__cache_dirty[key] = dirty


def db_make_directory_if_needed(directory_path):
    if os.path.exists(directory_path):
        if not os.path.isdir(directory_path):
            raise OSError("Path is not a directory:", directory_path)
    else:
        os.makedirs(directory_path)


class DictStorageCache(object):
    def __init__(self):
        self.__cache = dict()
        self.__cache_dirty = dict()

    def close(self):
        pass

    @property
    def cache(self):
        return self.__cache

    def suspend_cache(self):
        pass

    def spill_cache(self):
        pass

    def set_cached_value(self, object, key, value, dirty=False):
        cache = self.__cache.setdefault(object.uuid, dict())
        cache_dirty = self.__cache_dirty.setdefault(object.uuid, dict())
        cache[key] = value
        cache_dirty[key] = False

    def get_cached_value(self, object, key, default_value=None):
        cache = self.__cache.setdefault(object.uuid, dict())
        return cache.get(key, default_value)

    def remove_cached_value(self, object, key):
        cache = self.__cache.setdefault(object.uuid, dict())
        cache_dirty = self.__cache_dirty.setdefault(object.uuid, dict())
        if key in cache:
            del cache[key]
        if key in cache_dirty:
            del cache_dirty[key]

    def is_cached_value_dirty(self, object, key):
        cache_dirty = self.__cache_dirty.setdefault(object.uuid, dict())
        return cache_dirty[key] if key in cache_dirty else True

    def set_cached_value_dirty(self, object, key, dirty=True):
        cache_dirty = self.__cache_dirty.setdefault(object.uuid, dict())
        cache_dirty[key] = dirty


class DbStorageCache(object):
    def __init__(self, cache_filename):
        self.__queue = queue.Queue()
        self.__queue_lock = threading.RLock()
        self.__started_event = threading.Event()
        self.__thread = threading.Thread(target=self.__run, args=[cache_filename])
        self.__thread.daemon = True
        self.__thread.start()
        self.__started_event.wait()

    def close(self):
        with self.__queue_lock:
            assert self.__queue is not None
            self.__queue.put((None, None, None, None))
            self.__queue.join()
            self.__queue = None

    def suspend_cache(self):
        pass

    def spill_cache(self):
        pass

    def __run(self, cache_filename):
        self.conn = sqlite3.connect(cache_filename)
        self.conn.execute("PRAGMA synchronous = OFF")
        self.__create()
        self.__started_event.set()
        while True:
            action = self.__queue.get()
            item, result, event, action_name = action
            #logging.debug("item %s  result %s  event %s  action %s", item, result, event, action_name)
            if item:
                try:
                    #logging.debug("EXECUTE %s", action_name)
                    start = time.time()
                    if result is not None:
                        result.append(item())
                    else:
                        item()
                    elapsed = time.time() - start
                    #logging.debug("ELAPSED %s", elapsed)
                except Exception as e:
                    import traceback
                    logging.debug("DB Error: %s", e)
                    traceback.print_exc()
                    traceback.print_stack()
                finally:
                    #logging.debug("FINISH")
                    if event:
                        event.set()
            self.__queue.task_done()
            if not item:
                break
        self.conn.close()
        self.conn = None

    def __create(self):
        with self.conn:
            self.execute("CREATE TABLE IF NOT EXISTS cache(uuid STRING, key STRING, value BLOB, dirty INTEGER, PRIMARY KEY(uuid, key))")

    def execute(self, stmt, args=None, log=False):
        if args:
            result = self.conn.execute(stmt, args)
            if log:
                logging.debug("%s [%s]", stmt, args)
            return result
        else:
            self.conn.execute(stmt)
            if log:
                logging.debug("%s", stmt)
            return None

    def __set_cached_value(self, object, key, value, dirty=False):
        with self.conn:
            self.execute("INSERT OR REPLACE INTO cache (uuid, key, value, dirty) VALUES (?, ?, ?, ?)", (str(object.uuid), key, sqlite3.Binary(pickle.dumps(value, 0)), 1 if dirty else 0))

    def __get_cached_value(self, object, key, default_value=None):
        last_result = self.execute("SELECT value FROM cache WHERE uuid=? AND key=?", (str(object.uuid), key))
        value_row = last_result.fetchone()
        if value_row is not None:
            if sys.version < '3':
                result = pickle.loads(bytes(bytearray(value_row[0])))
            else:
                result = pickle.loads(value_row[0], encoding='latin1')
            return result
        else:
            return default_value

    def __remove_cached_value(self, object, key):
        with self.conn:
            self.execute("DELETE FROM cache WHERE uuid=? AND key=?", (str(object.uuid), key))

    def __is_cached_value_dirty(self, object, key):
        last_result = self.execute("SELECT dirty FROM cache WHERE uuid=? AND key=?", (str(object.uuid), key))
        value_row = last_result.fetchone()
        if value_row is not None:
            return value_row[0] != 0
        else:
            return True

    def __set_cached_value_dirty(self, object, key, dirty=True):
        with self.conn:
            self.execute("UPDATE cache SET dirty=? WHERE uuid=? AND key=?", (1 if dirty else 0, str(object.uuid), key))

    def set_cached_value(self, object, key, value, dirty=False):
        event = threading.Event()
        with self.__queue_lock:
            queue = self.__queue
        if queue:
            queue.put((functools.partial(self.__set_cached_value, object, key, value, dirty), None, event, "set_cached_value"))
        #event.wait()

    def get_cached_value(self, object, key, default_value=None):
        event = threading.Event()
        result = list()
        with self.__queue_lock:
            queue = self.__queue
        if queue:
            queue.put((functools.partial(self.__get_cached_value, object, key, default_value), result, event, "get_cached_value"))
            event.wait()
        return result[0] if len(result) > 0 else None

    def remove_cached_value(self, object, key):
        event = threading.Event()
        with self.__queue_lock:
            queue = self.__queue
        if queue:
            queue.put((functools.partial(self.__remove_cached_value, object, key), None, event, "remove_cached_value"))
        #event.wait()

    def is_cached_value_dirty(self, object, key):
        event = threading.Event()
        result = list()
        with self.__queue_lock:
            queue = self.__queue
        if queue:
            queue.put((functools.partial(self.__is_cached_value_dirty, object, key), result, event, "is_cached_value_dirty"))
            event.wait()
        return result[0]

    def set_cached_value_dirty(self, object, key, dirty=True):
        event = threading.Event()
        with self.__queue_lock:
            queue = self.__queue
        if queue:
            queue.put((functools.partial(self.__set_cached_value_dirty, object, key, dirty), None, event, "set_cached_value_dirty"))
        #event.wait()
