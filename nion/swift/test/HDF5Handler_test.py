import contextlib
import datetime
import os
import pathlib
import shutil
import unittest
import uuid

# third party libraries
import numpy

# local libraries
from nion.swift.model import HDF5Handler
from nion.swift.model import Cache


class TestHDF5Handler(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_get_write_chunk_shape_for_data(self):

        data_shapes_and_dtypes = [((512, 512, 130, 130), 'float32'),
                                  ((971, 971, 130, 130), 'float32'),
                                  ((1024, 1024, 130, 260), 'uint8'),
                                  ((1024, 1024, 1030), 'int16'),
                                  ((1024, 1024, 1032), 'float32'),
                                  ((512, 512), 'float32'),
                                  ((int(1e12),), 'int64')]
        expected_chunk_shapes = [(1, 58, 32, 32),
                                 (1, 58, 32, 32),
                                 (1, 1, 130, 260),
                                 (1, 256, 257),
                                 (1, 232, 258),
                                 None,
                                 (30000,)]

        for shape_dtype, expected_chunk_shape in zip(data_shapes_and_dtypes, expected_chunk_shapes):
            with self.subTest(shape=shape_dtype[0], dtype=shape_dtype[1]):
                chunk_shape = HDF5Handler.get_write_chunk_shape_for_data(*shape_dtype)

                if expected_chunk_shape is None:
                    self.assertIsNone(chunk_shape)
                else:
                    self.assertSequenceEqual(chunk_shape, expected_chunk_shape)

    def test_hdf5_handler_basic_functionality(self):
        now = datetime.datetime.now()
        current_working_directory = pathlib.Path.cwd()
        data_dir = current_working_directory / "__Test"
        if data_dir.exists():
            shutil.rmtree(data_dir)
        Cache.db_make_directory_if_needed(data_dir)
        try:
            h = HDF5Handler.HDF5Handler(os.path.join(data_dir, "abc.h5"))
            with contextlib.closing(h):
                p = {u"abc": 1, u"def": u"bcd", u"uuid": str(uuid.uuid4())}
                # write properties
                h.write_properties(p, now)
                self.assertEqual(h.read_properties(), p)
                self.assertIsNone(h.read_data())
                # write data
                h.write_data(numpy.zeros((4,4), dtype=numpy.float64), now)
                self.assertEqual(h.read_properties(), p)
                d = h.read_data()
                self.assertEqual(d.shape, (4, 4))
                self.assertEqual(d.dtype, numpy.float64)
                # rewrite data
                h.write_data(numpy.zeros((12,12), dtype=numpy.float32), now)
                self.assertEqual(h.read_properties(), p)
                d = h.read_data()
                self.assertEqual(d.shape, (12, 12))
                self.assertEqual(d.dtype, numpy.float32)
                # rewrite properties
                h.write_properties(p, now)
                self.assertEqual(h.read_properties(), p)
                d = h.read_data()
                self.assertEqual(d.shape, (12, 12))
                self.assertEqual(d.dtype, numpy.float32)
                # reserve data
                h.reserve_data((3, 15), numpy.float32, now)
                self.assertEqual(h.read_properties(), p)
                d = h.read_data()
                self.assertEqual(d.shape, (3, 15))
                self.assertEqual(d.dtype, numpy.float32)
                self.assertTrue(numpy.allclose(d, 0))
        finally:
            #logging.debug("rmtree %s", data_dir)
            shutil.rmtree(data_dir)
