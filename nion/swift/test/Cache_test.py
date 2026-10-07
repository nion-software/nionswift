# standard libraries
import contextlib
import logging
import os
import pathlib
import sqlite3
import tempfile
import time
import unittest
import uuid

# third party libraries
import numpy
import numpy.typing

# local libraries
from nion.swift.model import Cache


class TestThumbnailCacheClass(unittest.TestCase):

    def test_thumbnail_is_read_back_with_its_signature_after_reopening(self):
        with tempfile.TemporaryDirectory() as directory_str:
            path = pathlib.Path(directory_str) / "cache.nsthumbs"
            uuid_ = uuid.uuid4()
            image = numpy.arange(12, dtype=numpy.uint32).reshape(3, 4)
            with contextlib.closing(Cache.ThumbnailCache(path)) as thumbnail_cache:
                thumbnail_cache.set_thumbnail(uuid_, "signature", image)
            with contextlib.closing(Cache.ThumbnailCache(path)) as thumbnail_cache:
                thumbnail = thumbnail_cache.get_thumbnail(uuid_)
                self.assertIsNotNone(thumbnail)
                signature, read_image = thumbnail
                self.assertEqual("signature", signature)
                self.assertTrue(numpy.array_equal(image, read_image))
                self.assertIsNone(thumbnail_cache.get_thumbnail(uuid.uuid4()))

    def test_damaged_thumbnail_is_treated_as_missing(self):
        # a damaged cache file must not keep the thumbnail from being drawn.
        with tempfile.TemporaryDirectory() as directory_str:
            path = pathlib.Path(directory_str) / "cache.nsthumbs"
            uuid_ = uuid.uuid4()
            with contextlib.closing(Cache.ThumbnailCache(path)) as thumbnail_cache:
                thumbnail_cache.set_thumbnail(uuid_, "signature", numpy.zeros((4, 4), dtype=numpy.uint32))
            with contextlib.closing(sqlite3.connect(str(path))) as connection, connection:
                connection.execute("UPDATE thumbnails SET data = ? WHERE uuid = ?", (b"damaged", str(uuid_)))
            with contextlib.closing(Cache.ThumbnailCache(path)) as thumbnail_cache:
                self.assertIsNone(thumbnail_cache.get_thumbnail(uuid_))

    def test_thumbnail_updated_continuously_is_not_written_until_it_stops_changing(self):
        # a live display item must not write its thumbnail while it updates, since writing slows acquisition.

        def read_thumbnail_from_file(path: pathlib.Path, uuid_: uuid.UUID) -> tuple[str, numpy.typing.NDArray[numpy.uint32]] | None:
            with contextlib.closing(Cache.ThumbnailCache(path)) as reading_thumbnail_cache:
                return reading_thumbnail_cache.get_thumbnail(uuid_)

        with tempfile.TemporaryDirectory() as directory_str:
            path = pathlib.Path(directory_str) / "cache.nsthumbs"
            uuid_ = uuid.uuid4()
            with contextlib.closing(Cache.ThumbnailCache(path)) as thumbnail_cache:
                thumbnail_cache._write_delay = 0.2
                end_time = time.monotonic() + 0.6
                index = 0
                while time.monotonic() < end_time:
                    thumbnail_cache.set_thumbnail(uuid_, str(index), numpy.full((4, 4), index, dtype=numpy.uint32))
                    index += 1
                    time.sleep(0.02)
                self.assertIsNone(read_thumbnail_from_file(path, uuid_))
                end_time = time.monotonic() + 5.0
                while not read_thumbnail_from_file(path, uuid_) and time.monotonic() < end_time:
                    time.sleep(0.05)
                thumbnail = read_thumbnail_from_file(path, uuid_)
                self.assertIsNotNone(thumbnail)
                self.assertEqual(str(index - 1), thumbnail[0])

    def test_removed_thumbnail_is_removed_from_file_without_waiting(self):
        # a thumbnail which is no longer valid must not be read after a crash.
        with tempfile.TemporaryDirectory() as directory_str:
            path = pathlib.Path(directory_str) / "cache.nsthumbs"
            uuid_ = uuid.uuid4()
            with contextlib.closing(Cache.ThumbnailCache(path)) as thumbnail_cache:
                thumbnail_cache.set_thumbnail(uuid_, "signature", numpy.zeros((4, 4), dtype=numpy.uint32))
            with contextlib.closing(Cache.ThumbnailCache(path)) as thumbnail_cache, contextlib.closing(Cache.ThumbnailCache(path)) as reading_thumbnail_cache:
                thumbnail_cache._write_delay = 60.0
                thumbnail_cache.remove_thumbnail(uuid_)
                self.assertIsNone(thumbnail_cache.get_thumbnail(uuid_))
                end_time = time.monotonic() + 5.0
                while reading_thumbnail_cache.get_thumbnail(uuid_) and time.monotonic() < end_time:
                    time.sleep(0.02)
                self.assertIsNone(reading_thumbnail_cache.get_thumbnail(uuid_))

    def test_retain_thumbnails_removes_thumbnails_of_other_uuids(self):
        with contextlib.closing(Cache.ThumbnailCache(None)) as thumbnail_cache:
            retained_uuid = uuid.uuid4()
            removed_uuid = uuid.uuid4()
            thumbnail_cache.set_thumbnail(retained_uuid, "a", numpy.zeros((4, 4), dtype=numpy.uint32))
            thumbnail_cache.set_thumbnail(removed_uuid, "b", numpy.zeros((4, 4), dtype=numpy.uint32))
            thumbnail_cache.retain_thumbnails({retained_uuid})
            self.assertIsNotNone(thumbnail_cache.get_thumbnail(retained_uuid))
            self.assertIsNone(thumbnail_cache.get_thumbnail(removed_uuid))

    def test_cache_factory_removes_earlier_cache_file_of_project(self):
        # the earlier cache format is no longer read, so its file only takes space.
        with tempfile.TemporaryDirectory() as directory_str:
            cache_dir_path = pathlib.Path(directory_str)
            earlier_cache_path = cache_dir_path / "proj_X.nscache"
            other_earlier_cache_path = cache_dir_path / "proj_Y.nscache"
            earlier_cache_path.write_bytes(b"earlier")
            other_earlier_cache_path.write_bytes(b"earlier")
            cache_factory = Cache.DbCacheFactory(cache_dir_path, "proj_X")
            thumbnail_cache = cache_factory.create_cache()
            cache_factory.release_cache(thumbnail_cache)
            self.assertFalse(earlier_cache_path.exists())
            self.assertTrue(other_earlier_cache_path.exists())
            self.assertTrue((cache_dir_path / "proj_X.nsthumbs").exists())

    def test_cache_factory_keeps_thumbnails_of_project_opened_recently_without_changes(self):
        # a project which is opened often but not changed must not lose its thumbnails to the purge of unused projects.
        with tempfile.TemporaryDirectory() as directory_str:
            cache_dir_path = pathlib.Path(directory_str)
            cache_path = cache_dir_path / "proj_X.nsthumbs"
            uuid_ = uuid.uuid4()
            with contextlib.closing(Cache.ThumbnailCache(cache_path)) as thumbnail_cache:
                thumbnail_cache.set_thumbnail(uuid_, "signature", numpy.zeros((4, 4), dtype=numpy.uint32))
            last_written_time = time.time() - 40 * 24 * 60 * 60
            os.utime(cache_path, (last_written_time, last_written_time))
            cache_factory = Cache.DbCacheFactory(cache_dir_path, "proj_X")
            cache_factory.release_cache(cache_factory.create_cache())
            other_cache_factory = Cache.DbCacheFactory(cache_dir_path, "proj_Y")
            other_cache_factory.release_cache(other_cache_factory.create_cache())
            with contextlib.closing(Cache.ThumbnailCache(cache_path)) as thumbnail_cache:
                self.assertIsNotNone(thumbnail_cache.get_thumbnail(uuid_))


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
