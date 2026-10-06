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
import time
import traceback
import typing
import uuid
import zlib

# third party libraries
import numpy
import numpy.typing

# local libraries
from nion.utils import Process


class CacheLike(typing.Protocol):
    def close(self) -> None: ...
    def suspend_cache(self) -> None: ...
    def spill_cache(self) -> None: ...
    def set_cached_value(self, target: typing.Any, key: str, value: typing.Any, dirty: bool = False) -> None: ...
    def get_cached_value(self, target: typing.Any, key: str, default_value: typing.Any = None) -> typing.Any: ...
    def remove_cached_value(self, target: typing.Any, key: str) -> None: ...
    def is_cached_value_dirty(self, target: typing.Any, key: str) -> bool: ...
    def set_cached_value_dirty(self, target: typing.Any, key: str, dirty: bool = True) -> None: ...


class ThumbnailCache:
    """Store thumbnails persistently in an SQLite database, keyed by display item uuid.

    Each thumbnail is a uint32 RGBA image stored compressed, together with the signature of the display item it was drawn
    from. The image and signature are in one row, so they are always written together.

    Changes are kept in memory and written on a writer thread. A thumbnail is written once it has been unchanged for the
    write delay, so the thumbnail of a live display item is not written while it updates. A removal is written without
    delay, since it keeps a thumbnail which is no longer valid from being read after a crash.

    The project removes the thumbnails of deleted display items when it is loaded, and the cache factory removes the cache
    file of a project not changed for 30 days.

    The path is the database file, or None to keep the database in memory.

    Thread safe. The connection lock protects the connection. The condition protects the pending changes, the stored
    uuids, and the uuids being written, and is never held while using the database, so that a change does not wait for a write.
    """

    _write_delay = 2.0

    def __init__(self, path: pathlib.Path | None) -> None:
        self.__connection_lock = threading.Lock()
        self.__condition = threading.Condition()
        self.__connection: sqlite3.Connection | None = sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False, isolation_level=None)
        if path:
            # write-ahead logging lets an interrupted write roll back without syncing on every write.
            self.__connection.execute("PRAGMA journal_mode = WAL")
            self.__connection.execute("PRAGMA synchronous = NORMAL")
        self.__connection.execute("CREATE TABLE IF NOT EXISTS thumbnails (uuid TEXT PRIMARY KEY, signature TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL, data BLOB NOT NULL)")
        self.__stored_uuid_strs = {row[0] for row in self.__connection.execute("SELECT uuid FROM thumbnails")}
        self.__writing_uuid_strs: set[str] = set()
        # maps a uuid to the time of the change and the thumbnail, or None for a removal.
        self.__pending_changes: dict[str, tuple[float, tuple[str, numpy.typing.NDArray[numpy.uint32]] | None]] = dict()
        self.__is_closing = False
        # the time before which nothing is written, after a failed write.
        self.__retry_time = 0.0
        self.__writer_thread = threading.Thread(target=self.__write_pending_changes, daemon=True)
        self.__writer_thread.start()

    def close(self) -> None:
        """Write the pending changes and close the database."""
        with self.__condition:
            self.__is_closing = True
            self.__condition.notify_all()
        self.__writer_thread.join()
        with self.__connection_lock:
            if self.__connection:
                self.__connection.close()
                self.__connection = None

    def get_thumbnail(self, uuid_: uuid.UUID) -> tuple[str, numpy.typing.NDArray[numpy.uint32]] | None:
        """Return the signature and image of the thumbnail stored for the uuid, or None if there is none."""
        uuid_str = str(uuid_)
        with self.__condition:
            if pending_change := self.__pending_changes.get(uuid_str):
                return pending_change[1]
            if uuid_str not in self.__stored_uuid_strs:
                return None
        with self.__connection_lock:
            if not self.__connection:
                return None
            row = self.__connection.execute("SELECT signature, width, height, data FROM thumbnails WHERE uuid = ?", (uuid_str,)).fetchone()
        if not row:
            return None
        signature, width, height, data = row
        try:
            return signature, numpy.frombuffer(zlib.decompress(data), dtype="<u4").astype(numpy.uint32).reshape(height, width)
        except (zlib.error, ValueError):
            # a damaged thumbnail is treated as missing; it is drawn again and the new thumbnail replaces it.
            return None

    def set_thumbnail(self, uuid_: uuid.UUID, signature: str, image: numpy.typing.NDArray[numpy.uint32]) -> None:
        """Store the image of the thumbnail and the signature of the display item it was drawn from.

        The image must not be modified afterwards, since it is written later. Ignored once the cache is closing.
        """
        with self.__condition:
            if self.__is_closing:
                return
            self.__pending_changes[str(uuid_)] = time.monotonic(), (signature, image)
            self.__condition.notify_all()

    def remove_thumbnail(self, uuid_: uuid.UUID) -> None:
        uuid_str = str(uuid_)
        with self.__condition:
            if self.__is_closing:
                return
            # a thumbnail being written is stored once the write finishes, so it is removed afterwards.
            if uuid_str in self.__stored_uuid_strs or uuid_str in self.__writing_uuid_strs:
                self.__pending_changes[uuid_str] = time.monotonic(), None
                self.__condition.notify_all()
            else:
                self.__pending_changes.pop(uuid_str, None)

    def retain_thumbnails(self, uuids: typing.AbstractSet[uuid.UUID]) -> None:
        """Remove the thumbnails of all uuids not in the set, such as those of deleted display items."""
        retained_uuid_strs = {str(uuid_) for uuid_ in uuids}
        with self.__condition:
            for uuid_str in (self.__stored_uuid_strs | self.__writing_uuid_strs | set(self.__pending_changes)) - retained_uuid_strs:
                if uuid_str in self.__stored_uuid_strs or uuid_str in self.__writing_uuid_strs:
                    self.__pending_changes[uuid_str] = time.monotonic(), None
                else:
                    self.__pending_changes.pop(uuid_str, None)
            self.__condition.notify_all()

    def __write_pending_changes(self) -> None:
        # runs on the writer thread until the cache closes.
        while True:
            with self.__condition:
                while True:
                    now = time.monotonic()
                    if not self.__is_closing and now < self.__retry_time:
                        self.__condition.wait(self.__retry_time - now)
                        continue
                    ready_changes = {uuid_str: pending_change for uuid_str, pending_change in self.__pending_changes.items() if self.__is_closing or pending_change[1] is None or now - pending_change[0] >= self._write_delay}
                    if ready_changes or self.__is_closing:
                        break
                    timeout = min((pending_change[0] + self._write_delay - now for pending_change in self.__pending_changes.values()), default=None)
                    self.__condition.wait(timeout)
                is_closing = self.__is_closing
                self.__writing_uuid_strs = set(ready_changes)
            # compress outside the lock so that readers and writers are not blocked.
            rows = list()
            for uuid_str, (_, thumbnail) in ready_changes.items():
                if thumbnail:
                    signature, image = thumbnail
                    height, width = image.shape
                    # fast compression; a thumbnail typically compresses to a third or less of its size.
                    rows.append((uuid_str, signature, width, height, zlib.compress(image.astype("<u4").tobytes(), 1)))
            removed_uuid_strs = [uuid_str for uuid_str, (_, thumbnail) in ready_changes.items() if not thumbnail]
            is_written = False
            with self.__connection_lock:
                if self.__connection:
                    try:
                        self.__connection.execute("BEGIN")
                        self.__connection.executemany("DELETE FROM thumbnails WHERE uuid = ?", [(uuid_str,) for uuid_str in removed_uuid_strs])
                        self.__connection.executemany("INSERT OR REPLACE INTO thumbnails (uuid, signature, width, height, data) VALUES (?, ?, ?, ?, ?)", rows)
                        self.__connection.execute("COMMIT")
                        is_written = True
                    except sqlite3.Error:
                        # the changes stay pending and are written again after the write delay.
                        traceback.print_exc()
                        if self.__connection.in_transaction:
                            self.__connection.execute("ROLLBACK")
            with self.__condition:
                self.__writing_uuid_strs = set()
                if is_written:
                    self.__stored_uuid_strs.difference_update(removed_uuid_strs)
                    self.__stored_uuid_strs.update(row[0] for row in rows)
                    # a change made while writing replaced the pending change, so it is kept to be written later.
                    for uuid_str, pending_change in ready_changes.items():
                        if self.__pending_changes.get(uuid_str) is pending_change:
                            del self.__pending_changes[uuid_str]
                else:
                    self.__retry_time = time.monotonic() + self._write_delay
            if is_closing:
                return


class CacheFactory(typing.Protocol):
    def create_cache(self) -> ThumbnailCache: ...
    def release_cache(self, cache: ThumbnailCache) -> None: ...


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
            _, object_dirty_dict = self.__cache_dirty.get(id(target), typing.cast(typing.Tuple[typing.Any, typing.Dict[str, bool]], (target, dict())))
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

    def suspend_cache(self) -> None:
        return  # required to avoid being recognized as abstract by mypy

    def spill_cache(self) -> None:
        return  # required to avoid being recognized as abstract by mypy

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
        return  # required to avoid being recognized as abstract by mypy

    def spill_cache(self) -> None:
        return  # required to avoid being recognized as abstract by mypy

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
        return  # required to avoid being recognized as abstract by mypy

    def spill_cache(self) -> None:
        return  # required to avoid being recognized as abstract by mypy

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
                    with Process.audit(f"cache.{action_name}"):
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
        # remove the cache files of projects not opened in the last 30 days, including the files of the earlier cache
        # format, and remove the earlier format file of this project, which is no longer used.
        try:
            if self.__cache_dir_path.exists():
                cache_file_paths = set(self.__cache_dir_path.rglob("*.nscache")) | set(self.__cache_dir_path.rglob("*.nsthumbs"))
                for file_path in cache_file_paths - {cache_path}:
                    time_delta = datetime.datetime.now() - datetime.datetime.fromtimestamp(file_path.stat().st_mtime)
                    if time_delta.days > 30 or file_path == cache_path.with_suffix(".nscache"):
                        logging.getLogger("loader").info(f"Purging cache file {file_path}")
                        file_path.unlink(True)
                        # the write-ahead log files, which SQLite on macOS keeps after closing.
                        file_path.with_name(file_path.name + "-wal").unlink(True)
                        file_path.with_name(file_path.name + "-shm").unlink(True)
        except OSError:
            # a cache file which cannot be removed now is removed on a later attempt.
            pass

    def create_cache(self) -> ThumbnailCache:
        cache_path = (self.__cache_dir_path / (self.__identifier)).with_suffix(".nsthumbs")
        self.__purge(cache_path)
        logging.getLogger("loader").info(f"Using cache {cache_path}")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        return ThumbnailCache(cache_path)

    def release_cache(self, cache: ThumbnailCache) -> None:
        cache.close()


class DictCacheFactory(CacheFactory):
    def create_cache(self) -> ThumbnailCache:
        return ThumbnailCache(None)

    def release_cache(self, cache: ThumbnailCache) -> None:
        cache.close()
