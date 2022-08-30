from __future__ import annotations

# standard libraries
import copy
import datetime
import functools
import logging
import os
import pathlib
import pickle
import queue
import sqlite3
import sys
import threading

# third party libraries
# None

# local libraries
# None
import typing
import uuid


class CacheLike(typing.Protocol):
    def close(self) -> None: ...
    def suspend_cache(self) -> None: ...
    def spill_cache(self) -> None: ...
    def set_cached_value(self, target: typing.Any, key: str, value: typing.Any, dirty: bool = False) -> None: ...
    def get_cached_value(self, target: typing.Any, key: str, default_value: typing.Any = None) -> typing.Any: ...
    def remove_cached_value(self, target: typing.Any, key: str) -> None: ...
    def is_cached_value_dirty(self, target: typing.Any, key: str) -> bool: ...
    def set_cached_value_dirty(self, target: typing.Any, key: str, dirty: bool = True) -> None: ...


class CacheFactory(typing.Protocol):
    def create_cache(self) -> CacheLike: ...
    def release_cache(self, cache: CacheLike) -> None: ...


class TracingCache(CacheLike):

    def __init__(self, storage_cache: CacheLike) -> None:
        self.__storage_cache = storage_cache

    def close(self) -> None:
        pass

    def suspend_cache(self) -> None:
        logging.debug("%s.suspend_cache()", id(self))
        self.__storage_cache.suspend_cache()

    def spill_cache(self) -> None:
        logging.debug("%s.spill_cache()", id(self))
        self.__storage_cache.spill_cache()

    def set_cached_value(self, target: typing.Any, key: str, value: typing.Any, dirty: bool = False) -> None:
        logging.debug("%s.set_cached_value(%s, %s, %s, %s)", id(self), id(target), key, value, dirty)
        self.__storage_cache.set_cached_value(target, key, value, dirty)

    def get_cached_value(self, target: typing.Any, key: str, default_value: typing.Any = None) -> typing.Any:
        logging.debug("%s.get_cached_value(%s, %s, %s)", id(self), id(target), key, default_value)
        result = self.__storage_cache.get_cached_value(target, key, default_value)
        logging.debug("# %s", result)
        return result

    def remove_cached_value(self, target: typing.Any, key: str) -> None:
        logging.debug("%s.remove_cached_value(%s, %s)", id(self), target, key)
        self.__storage_cache.remove_cached_value(target, key)

    def is_cached_value_dirty(self, target: typing.Any, key: str) -> bool:
        logging.debug("%s.is_cached_value_dirty(%s, %s)", id(self), id(target), key)
        result = self.__storage_cache.is_cached_value_dirty(target, key)
        logging.debug("# %s", result)
        return result

    def set_cached_value_dirty(self, target: typing.Any, key: str, dirty: bool = True) -> None:
        logging.debug("%s.set_cached_value_dirty(%s, %s, %s)", id(self), target, key, dirty)
        self.__storage_cache.set_cached_value_dirty(target, key, dirty)


class SuspendableCache(CacheLike):

    def __init__(self, storage_cache: CacheLike) -> None:
        self.__storage_cache = storage_cache
        self.__cache: typing.Dict[int, typing.Tuple[typing.Any, typing.Dict[str, typing.Any]]] = dict()
        self.__cache_remove: typing.Dict[int, typing.Tuple[typing.Any, typing.List[typing.Any]]] = dict()
        self.__cache_dirty: typing.Dict[int, typing.Tuple[typing.Any, typing.Dict[str, bool]]] = dict()
        self.__cache_mutex = threading.RLock()
        self.__cache_delayed = False

    def close(self) -> None:
        pass

    # the cache system stores values that are expensive to calculate for quick retrieval.
    # an item can be marked dirty in the cache so that callers can determine whether that
    # value needs to be recalculated. marking a value as dirty doesn't affect the current
    # value in the cache. callers can still retrieve the latest value for an item in the
    # cache even when it is marked dirty. this way the cache is used to retrieve the best
    # available data without doing additional calculations.

    def suspend_cache(self) -> None:
        with self.__cache_mutex:
            self.__cache_delayed = True

    # move local cache items into permanent cache when transaction is finished.
    def spill_cache(self) -> None:
        with self.__cache_mutex:
            cache_copy = copy.copy(self.__cache)
            cache_dirty_copy = copy.copy(self.__cache_dirty)
            cache_remove_copy = copy.copy(self.__cache_remove)
            self.__cache.clear()
            self.__cache_remove.clear()
            self.__cache_dirty.clear()
            self.__cache_delayed = False
        if self.__storage_cache:
            for object_id, (target, object_dict) in iter(cache_copy.items()):
                _, object_dirty_dict = cache_dirty_copy.get(id(target), (target, dict()))
                for key, value in iter(object_dict.items()):
                    dirty = object_dirty_dict.get(key, False)
                    self.__storage_cache.set_cached_value(target, key, value, dirty)
            for object_id, (target, key_list) in iter(cache_remove_copy.items()):
                for key in key_list:
                    self.__storage_cache.remove_cached_value(target, key)

    # update the value in the cache. usually updating a value in the cache
    # means it will no longer be dirty.
    def set_cached_value(self, target: typing.Any, key: str, value: typing.Any, dirty: bool = False) -> None:
        # if transaction count is 0, cache directly
        if self.__storage_cache and not self.__cache_delayed:
            self.__storage_cache.set_cached_value(target, key, value, dirty)
        # otherwise, store it temporarily until transaction is finished
        else:
            with self.__cache_mutex:
                _, object_dict = self.__cache.setdefault(id(target), (target, dict()))
                _, object_list = self.__cache_remove.get(id(target), (target, list()))
                _, object_dirty_dict = self.__cache_dirty.setdefault(id(target), (target, dict()))
                object_dict[key] = value
                object_dirty_dict[key] = dirty
                if key in object_list:
                    object_list.remove(key)

    # grab the last cached value, if any, from the cache.
    def get_cached_value(self, target: typing.Any, key: str, default_value: typing.Any = None) -> typing.Any:
        # first check temporary cache.
        with self.__cache_mutex:
            _, object_dict = self.__cache.get(id(target), (target, dict()))
            if key in object_dict:
                return object_dict.get(key)
            _, object_list = self.__cache_remove.setdefault(id(target), (target, list()))
            if key in object_list:
                return None
        # not there, go to cache db
        if self.__storage_cache:
            return self.__storage_cache.get_cached_value(target, key, default_value)
        return default_value

    # removing values from the cache happens immediately under a transaction.
    # this is an area of improvement if it becomes a bottleneck.
    def remove_cached_value(self, target: typing.Any, key: str) -> None:
        # remove it from the cache db.
        if self.__storage_cache and not self.__cache_delayed:
            self.__storage_cache.remove_cached_value(target, key)
        else:
            # if its in the temporary cache, remove it
            with self.__cache_mutex:
                _, object_dict = self.__cache.get(id(target), (target, dict()))
                _, object_list = self.__cache_remove.setdefault(id(target), (target, list()))
                _, object_dirty_dict = self.__cache_dirty.get(id(target), (target, dict()))
                if key in object_dict:
                    del object_dict[key]
                if key in object_dirty_dict:
                    del object_dirty_dict[key]
                if key not in object_list:
                    object_list.append(key)

    # determines whether the item in the cache is dirty.
    def is_cached_value_dirty(self, target: typing.Any, key: str) -> bool:
        # check the temporary cache first
        with self.__cache_mutex:
            _, object_dirty_dict = self.__cache_dirty.get(id(target), (target, dict()))
            if key in object_dirty_dict:
                return object_dirty_dict[key]
        # not there, go to the db cache
        if self.__storage_cache:
            return self.__storage_cache.is_cached_value_dirty(target, key)
        return True

    # set whether the cache value is dirty.
    def set_cached_value_dirty(self, target: typing.Any, key: str, dirty: bool = True) -> None:
        # go directory to the db cache if not under a transaction
        if self.__storage_cache and not self.__cache_delayed:
            self.__storage_cache.set_cached_value_dirty(target, key, dirty)
        # otherwise mark it in the temporary cache
        else:
            with self.__cache_mutex:
                _, object_dirty_dict = self.__cache_dirty.setdefault(id(target), (target, dict()))
                object_dirty_dict[key] = dirty


class ShadowCache(CacheLike):
    """Shadow another cache, allowing cache usage before the other cache is created.

    Set the other cache using set_storage_cache. Anything cached on this object before
    set_storage_cache is called will be spilled into the other cache."""

    def __init__(self) -> None:
        self.__storage_cache: typing.Optional[CacheLike] = None
        self.__cache: typing.Dict[str, typing.Any] = dict()
        self.__cache_remove: typing.List[str] = list()
        self.__cache_dirty: typing.Dict[str, bool] = dict()
        self.__cache_mutex = threading.RLock()
        self.__cache_delayed = False

    def close(self) -> None:
        pass

    @property
    def storage_cache(self) -> typing.Optional[CacheLike]:
        return self.__storage_cache

    def set_storage_cache(self, storage_cache: typing.Optional[CacheLike], target: typing.Any) -> None:
        self.__storage_cache = storage_cache
        self.__spill_cache(target)

    # the cache system stores values that are expensive to calculate for quick retrieval.
    # an item can be marked dirty in the cache so that callers can determine whether that
    # value needs to be recalculated. marking a value as dirty doesn't affect the current
    # value in the cache. callers can still retrieve the latest value for an item in the
    # cache even when it is marked dirty. this way the cache is used to retrieve the best
    # available data without doing additional calculations.

    # move local cache items into permanent cache when transaction is finished.
    def __spill_cache(self, target: typing.Any) -> None:
        with self.__cache_mutex:
            cache_copy = copy.copy(self.__cache)
            cache_dirty_copy = copy.copy(self.__cache_dirty)
            cache_remove = copy.copy(self.__cache_remove)
            self.__cache.clear()
            self.__cache_remove = list()
            self.__cache_dirty.clear()
        if self.storage_cache:
            for key, value in iter(cache_copy.items()):
                self.storage_cache.set_cached_value(target, key, value, cache_dirty_copy.get(key, False))
            for key in cache_remove:
                self.storage_cache.remove_cached_value(target, key)

    # update the value in the cache. usually updating a value in the cache
    # means it will no longer be dirty.
    def set_cached_value(self, target: typing.Any, key: str, value: typing.Any, dirty: bool = False) -> None:
        # if transaction count is 0, cache directly
        if self.storage_cache and not self.__cache_delayed:
            self.storage_cache.set_cached_value(target, key, value, dirty)
        # otherwise, store it temporarily until transaction is finished
        else:
            with self.__cache_mutex:
                self.__cache[key] = value
                self.__cache_dirty[key] = dirty
                if key in self.__cache_remove:
                    self.__cache_remove.remove(key)

    # grab the last cached value, if any, from the cache.
    def get_cached_value(self, target: typing.Any, key: str, default_value: typing.Any = None) -> typing.Any:
        # first check temporary cache.
        with self.__cache_mutex:
            if key in self.__cache:
                return self.__cache.get(key)
        # not there, go to cache db
        if self.storage_cache:
            return self.storage_cache.get_cached_value(target, key, default_value)
        return default_value

    # removing values from the cache happens immediately under a transaction.
    # this is an area of improvement if it becomes a bottleneck.
    def remove_cached_value(self, target: typing.Any, key: str) -> None:
        # remove it from the cache db.
        if self.storage_cache and not self.__cache_delayed:
            self.storage_cache.remove_cached_value(target, key)
        # if its in the temporary cache, remove it
        with self.__cache_mutex:
            if key in self.__cache:
                del self.__cache[key]
            if key in self.__cache_dirty:
                del self.__cache_dirty[key]
            if key not in self.__cache_remove:
                self.__cache_remove.append(key)

    # determines whether the item in the cache is dirty.
    def is_cached_value_dirty(self, target: typing.Any, key: str) -> bool:
        # check the temporary cache first
        with self.__cache_mutex:
            if key in self.__cache_dirty:
                return self.__cache_dirty[key]
        # not there, go to the db cache
        if self.storage_cache:
            return self.storage_cache.is_cached_value_dirty(target, key)
        return True

    # set whether the cache value is dirty.
    def set_cached_value_dirty(self, target: typing.Any, key: str, dirty: bool = True) -> None:
        # go directory to the db cache if not under a transaction
        if self.storage_cache and not self.__cache_delayed:
            self.storage_cache.set_cached_value_dirty(target, key, dirty)
        # otherwise mark it in the temporary cache
        else:
            with self.__cache_mutex:
                self.__cache_dirty[key] = dirty


def db_make_directory_if_needed(directory_path: str) -> None:
    if os.path.exists(directory_path):
        if not os.path.isdir(directory_path):
            raise OSError("Path is not a directory:", directory_path)
    else:
        os.makedirs(directory_path)


class DictStorageCache(CacheLike):
    def __init__(self, cache: typing.Optional[typing.Dict[str, typing.Any]] = None,
                 cache_dirty: typing.Optional[typing.Dict[uuid.UUID, typing.Dict[str, typing.Any]]] = None) -> None:
        self.__cache: typing.Dict[str, typing.Any] = copy.deepcopy(cache) if cache else dict()
        self.__cache_dirty: typing.Dict[uuid.UUID, typing.Dict[str, bool]] = copy.deepcopy(cache_dirty) if cache_dirty else dict()

    def close(self) -> None:
        pass

    @property
    def cache(self) -> typing.Dict[str, typing.Any]:
        return self.__cache

    @property
    def _cache_dict(self) -> typing.Dict[str, typing.Any]:
        return self.__cache

    @property
    def _cache_dirty_dict(self) -> typing.Dict[uuid.UUID, typing.Dict[str, typing.Any]]:
        return self.__cache_dirty

    def clone(self) -> DictStorageCache:
        return DictStorageCache(cache=self.__cache, cache_dirty=self.__cache_dirty)

    def suspend_cache(self) -> None:
        pass

    def spill_cache(self) -> None:
        pass

    def set_cached_value(self, target: typing.Any, key: str, value: typing.Any, dirty: bool = False) -> None:
        cache = self.__cache.setdefault(target.uuid, dict())
        cache_dirty = self.__cache_dirty.setdefault(target.uuid, dict())
        cache[key] = value
        cache_dirty[key] = dirty

    def get_cached_value(self, target: typing.Any, key: str, default_value: typing.Any = None) -> typing.Any:
        cache = self.__cache.setdefault(target.uuid, dict())
        return cache.get(key, default_value)

    def remove_cached_value(self, target: typing.Any, key: str) -> None:
        cache = self.__cache.setdefault(target.uuid, dict())
        cache_dirty = self.__cache_dirty.setdefault(target.uuid, dict())
        if key in cache:
            del cache[key]
        if key in cache_dirty:
            del cache_dirty[key]

    def is_cached_value_dirty(self, target: typing.Any, key: str) -> bool:
        cache_dirty = self.__cache_dirty.setdefault(target.uuid, dict())
        return cache_dirty[key] if key in cache_dirty else True

    def set_cached_value_dirty(self, target: typing.Any, key: str, dirty: bool = True) -> None:
        cache_dirty = self.__cache_dirty.setdefault(target.uuid, dict())
        cache_dirty[key] = dirty


class DbStorageCache(CacheLike):
    count = 0  # useful for detecting leaks in tests

    def __init__(self, cache_filename: pathlib.Path) -> None:
        DbStorageCache.count += 1
        # Python 3.9+: fix typing
        self.__queue: typing.Any = queue.Queue()
        self.__queue_lock = threading.RLock()
        self.__started_event = threading.Event()
        self.__thread = threading.Thread(target=self.__run, args=[cache_filename])
        self.__thread.start()
        self.__started_event.wait()

    def close(self) -> None:
        with self.__queue_lock:
            assert self.__queue is not None
            self.__queue.put((None, None, None, None))
            self.__queue.join()
            self.__queue = None
        self.__thread.join()
        self.__thread = typing.cast(typing.Any, None)
        DbStorageCache.count -= 1

    def suspend_cache(self) -> None:
        pass

    def spill_cache(self) -> None:
        pass

    def __run(self, cache_filename: pathlib.Path) -> None:
        self.conn = sqlite3.connect(str(cache_filename))
        self.conn.execute("PRAGMA synchronous = OFF")
        self.__create()
        self.__started_event.set()
        while True:
            action = self.__queue.get()
            item, result, event, action_name = action
            # logging.debug("item %s  result %s  event %s  action %s", item, result, event, action_name)
            if item:
                try:
                    # logging.debug("EXECUTE %s", action_name)
                    # start = time.time()
                    if result is not None:
                        result.append(item())
                    else:
                        item()
                    # elapsed = time.time() - start
                    # logging.debug("ELAPSED %s", elapsed)
                except Exception as e:
                    import traceback
                    logging.debug("DB Error: %s", e)
                    traceback.print_exc()
                    traceback.print_stack()
                finally:
                    # logging.debug("FINISH")
                    if event:
                        event.set()
            self.__queue.task_done()
            if not item:
                break
        self.conn.close()
        self.conn = typing.cast(typing.Any, None)

    def __create(self) -> None:
        with self.conn:
            self.execute("CREATE TABLE IF NOT EXISTS cache(uuid STRING, key STRING, value BLOB, dirty INTEGER, PRIMARY KEY(uuid, key))")

    def execute(self, stmt: str, args: typing.Any = None, log: bool = False) -> typing.Any:
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

    def __set_cached_value(self, target: typing.Any, key: str, value: typing.Any, dirty: bool = False) -> None:
        with self.conn:
            self.execute("INSERT OR REPLACE INTO cache (uuid, key, value, dirty) VALUES (?, ?, ?, ?)",
                         (str(target.uuid), key, sqlite3.Binary(pickle.dumps(value, 0)), 1 if dirty else 0))

    def __get_cached_value(self, target: typing.Any, key: str, default_value: typing.Any = None) -> typing.Any:
        last_result = self.execute("SELECT value FROM cache WHERE uuid=? AND key=?", (str(target.uuid), key))
        value_row = last_result.fetchone()
        if value_row is not None:
            if sys.version < '3':
                result = pickle.loads(bytes(bytearray(value_row[0])))
            else:
                result = pickle.loads(value_row[0], encoding='latin1')
            return result
        else:
            return default_value

    def __remove_cached_value(self, target: typing.Any, key: str) -> None:
        with self.conn:
            self.execute("DELETE FROM cache WHERE uuid=? AND key=?", (str(target.uuid), key))

    def __is_cached_value_dirty(self, target: typing.Any, key: str) -> bool:
        last_result = self.execute("SELECT dirty FROM cache WHERE uuid=? AND key=?", (str(target.uuid), key))
        value_row = last_result.fetchone()
        if value_row is not None:
            return int(value_row[0]) != 0
        else:
            return True

    def __set_cached_value_dirty(self, target: typing.Any, key: str, dirty: bool = True) -> None:
        with self.conn:
            self.execute("UPDATE cache SET dirty=? WHERE uuid=? AND key=?", (1 if dirty else 0, str(target.uuid), key))

    def set_cached_value(self, target: typing.Any, key: str, value: typing.Any, dirty: bool = False) -> None:
        assert target is not None
        event = threading.Event()
        with self.__queue_lock:
            _queue = self.__queue
        if _queue:
            _queue.put((functools.partial(self.__set_cached_value, target, key, value, dirty), None, event, "set_cached_value"))
        # event.wait()

    def get_cached_value(self, target: typing.Any, key: str, default_value: typing.Any = None) -> typing.Any:
        assert target is not None
        event = threading.Event()
        result: typing.List[typing.Any] = list()
        with self.__queue_lock:
            _queue = self.__queue
        if _queue:
            _queue.put((functools.partial(self.__get_cached_value, target, key, default_value), result, event, "get_cached_value"))
            event.wait()
        return result[0] if len(result) > 0 else None

    def remove_cached_value(self, target: typing.Any, key: str) -> None:
        assert target is not None
        event = threading.Event()
        with self.__queue_lock:
            _queue = self.__queue
        if _queue:
            _queue.put((functools.partial(self.__remove_cached_value, target, key), None, event, "remove_cached_value"))
        # event.wait()

    def is_cached_value_dirty(self, target: typing.Any, key: str) -> bool:
        assert target is not None
        event = threading.Event()
        result: typing.List[typing.Any] = list()
        with self.__queue_lock:
            _queue = self.__queue
        if _queue:
            _queue.put((functools.partial(self.__is_cached_value_dirty, target, key), result, event, "is_cached_value_dirty"))
            event.wait()
        return typing.cast(bool, result[0])

    def set_cached_value_dirty(self, target: typing.Any, key: str, dirty: bool = True) -> None:
        assert target is not None
        event = threading.Event()
        with self.__queue_lock:
            _queue = self.__queue
        if _queue:
            _queue.put((functools.partial(self.__set_cached_value_dirty, target, key, dirty), None, event, "set_cached_value_dirty"))
        # event.wait()


class DbCacheFactory(CacheFactory):
    def __init__(self, cache_dir_path: pathlib.Path, identifier: str) -> None:
        self.__cache_dir_path = cache_dir_path
        self.__identifier = identifier

    def __purge(self, cache_path: pathlib.Path) -> None:
        try:
            if self.__cache_dir_path.exists():
                absolute_file_paths = set()
                for file_path in self.__cache_dir_path.rglob("*.nscache"):
                    absolute_file_paths.add(file_path)
                for file_path in absolute_file_paths - {cache_path}:
                    time_delta = datetime.datetime.now() - datetime.datetime.fromtimestamp(file_path.stat().st_mtime)
                    if time_delta.days > 30:
                        logging.getLogger("loader").info(f"Purging cache file {file_path}")
                        file_path.unlink(True)
        except Exception as e:
            pass

    def create_cache(self) -> CacheLike:
        cache_path = (self.__cache_dir_path / (self.__identifier)).with_suffix(".nscache")
        self.__purge(cache_path)
        logging.getLogger("loader").info(f"Using cache {cache_path}")
        return DbStorageCache(cache_path)

    def release_cache(self, cache: CacheLike) -> None:
        cache.close()


class DictCacheFactory(CacheFactory):
    def create_cache(self) -> CacheLike:
        return DictStorageCache()

    def release_cache(self, cache: CacheLike) -> None:
        cache.close()
