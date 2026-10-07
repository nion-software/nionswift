from __future__ import annotations

# standard libraries
import datetime
import logging
import os
import pathlib
import sqlite3
import threading
import time
import traceback
import typing
import uuid
import zlib

# third party libraries
import numpy
import numpy.typing


class ThumbnailCache:
    """Store thumbnails persistently in an SQLite database, keyed by display item uuid.

    Each thumbnail is a uint32 RGBA image stored compressed, together with the signature of the display item it was drawn
    from. The image and signature are in one row, so they are always written together.

    Changes are kept in memory and written on a writer thread. A thumbnail is written once it has been unchanged for the
    write delay, so the thumbnail of a live display item is not written while it updates. A removal is written without
    delay, since it keeps a thumbnail which is no longer valid from being read after a crash.

    The project removes the thumbnails of deleted display items when it is loaded, and the cache factory removes the cache
    file of a project not opened for 30 days.

    The path is the database file, or None to keep the database in memory.

    Thread safe. The connection lock protects the connection. The condition protects the pending changes, the stored
    uuids, and the uuids being written, and is never held while using the database, so that a change does not wait for a write.
    """

    _write_delay = 2.0
    count = 0  # used to detect caches which are not closed in tests

    def __init__(self, path: pathlib.Path | None) -> None:
        """Open the database, creating it if needed.

        Raises sqlite3.Error if the file cannot be opened or is not a thumbnail database.
        """
        connection = sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False, isolation_level=None)
        try:
            if path:
                # write-ahead logging lets an interrupted write roll back without syncing on every write.
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute("CREATE TABLE IF NOT EXISTS thumbnails (uuid TEXT PRIMARY KEY, signature TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL, data BLOB NOT NULL)")
            stored_uuid_strs = {row[0] for row in connection.execute("SELECT uuid FROM thumbnails")}
        except sqlite3.Error:
            connection.close()
            raise
        ThumbnailCache.count += 1
        self.__connection_lock = threading.Lock()
        self.__condition = threading.Condition()
        self.__connection: sqlite3.Connection | None = connection
        self.__stored_uuid_strs = stored_uuid_strs
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
        ThumbnailCache.count -= 1

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

    def discard_pending_thumbnail(self, uuid_: uuid.UUID) -> bool:
        """Discard the thumbnail waiting to be written for the uuid, so that it is not written.

        Return whether a thumbnail was discarded. A removal is kept, and a write already started still finishes.
        """
        uuid_str = str(uuid_)
        with self.__condition:
            pending_change = self.__pending_changes.get(uuid_str)
            if pending_change and pending_change[1] is not None:
                del self.__pending_changes[uuid_str]
                return True
            return False

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


def db_make_directory_if_needed(directory_path: str) -> None:
    if os.path.exists(directory_path):
        if not os.path.isdir(directory_path):
            raise OSError("Path is not a directory:", directory_path)
    else:
        os.makedirs(directory_path)


def remove_cache_file(cache_path: pathlib.Path) -> None:
    """Remove a cache file and its write-ahead log files, which SQLite on macOS keeps after closing."""
    cache_path.unlink(True)
    cache_path.with_name(cache_path.name + "-wal").unlink(True)
    cache_path.with_name(cache_path.name + "-shm").unlink(True)


def open_cache_file(cache_path: pathlib.Path) -> ThumbnailCache:
    """Open the cache file, creating it and its directory if needed, and mark it as opened now.

    The purge goes by modification time, and opening a project whose thumbnails are all valid writes nothing, so the
    file is marked as opened explicitly.

    Raises OSError or sqlite3.Error if the file cannot be used.
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.touch()
    return ThumbnailCache(cache_path)


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
                        remove_cache_file(file_path)
        except OSError:
            # a cache file which cannot be removed now is removed on a later attempt.
            pass

    def create_cache(self) -> ThumbnailCache:
        cache_path = (self.__cache_dir_path / (self.__identifier)).with_suffix(".nsthumbs")
        self.__purge(cache_path)
        logging.getLogger("loader").info(f"Using cache {cache_path}")
        try:
            return open_cache_file(cache_path)
        except (OSError, sqlite3.Error):
            # the thumbnails can always be drawn again, so a damaged cache file is replaced rather than keeping the
            # project from opening.
            traceback.print_exc()
        try:
            remove_cache_file(cache_path)
            return open_cache_file(cache_path)
        except (OSError, sqlite3.Error):
            # the thumbnails are kept in memory when no cache file can be used.
            traceback.print_exc()
        return ThumbnailCache(None)

    def release_cache(self, cache: ThumbnailCache) -> None:
        cache.close()


class DictCacheFactory(CacheFactory):
    def create_cache(self) -> ThumbnailCache:
        return ThumbnailCache(None)

    def release_cache(self, cache: ThumbnailCache) -> None:
        cache.close()
