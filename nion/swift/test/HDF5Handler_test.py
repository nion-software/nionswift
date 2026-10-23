import contextlib
import datetime
import os
import pathlib
import shutil
import unittest
import uuid

import h5py
# third party libraries
import numpy

# local libraries
from nion.data import DataAndMetadata
from nion.swift.model import HDF5Handler
from nion.swift.model import Cache


class TestHDF5Handler(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_get_write_chunk_shape_for_data(self):

        data_shapes_and_dtypes = [((512, 512, 130, 130), 'float32', DataAndMetadata.DataDescriptor(False, 2, 2)),
                                  ((971, 971, 130, 130), 'float32', DataAndMetadata.DataDescriptor(False, 2, 2)),
                                  ((1024, 1024, 130, 260), 'uint8', DataAndMetadata.DataDescriptor(True, 2, 1)),
                                  ((1024, 1024, 1030), 'int16', DataAndMetadata.DataDescriptor(False, 2, 1)),
                                  ((1024, 1024, 1032), 'float32', DataAndMetadata.DataDescriptor(False, 2, 1)),
                                  ((512, 512), 'float32', DataAndMetadata.DataDescriptor(False, 0, 2)),
                                  ((int(1e12),), 'int64', DataAndMetadata.DataDescriptor(False, 0, 1)),
                                  ((10, 1024, 1024, 1030), 'float32', DataAndMetadata.DataDescriptor(True, 2, 1)),
                                  ((3, 123, 17, 31, 29), 'float32', DataAndMetadata.DataDescriptor(False, 2, 2))]
        expected_chunk_shapes = [(1, 58, 32, 32),
                                 (1, 58, 32, 32),
                                 (1, 1, 130, 260),
                                 (1, 466, 257),
                                 (1, 232, 258),
                                 None,
                                 (30000,),
                                 (1, 1, 233, 257),
                                 (1, 1, 17, 31, 29)]

        for shape_dtype_descriptor, expected_chunk_shape in zip(data_shapes_and_dtypes, expected_chunk_shapes):
            with self.subTest(shape=shape_dtype_descriptor[0], dtype=shape_dtype_descriptor[1], data_descriptor=shape_dtype_descriptor[2]):
                chunk_shape = HDF5Handler.get_write_chunk_shape_for_data(*shape_dtype_descriptor)

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
                h.write_data(numpy.zeros((4,4), dtype=numpy.float64), DataAndMetadata.DataDescriptor(False, 0, 2), now)
                self.assertEqual(h.read_properties(), p)
                d = h.read_data()
                self.assertEqual(d.shape, (4, 4))
                self.assertEqual(d.dtype, numpy.float64)
                # rewrite data
                h.write_data(numpy.zeros((12,12), dtype=numpy.float32), DataAndMetadata.DataDescriptor(False, 0, 2), now)
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
                h.reserve_data((3, 15), numpy.float32, DataAndMetadata.DataDescriptor(False, 0, 2), now)
                self.assertEqual(h.read_properties(), p)
                d = h.read_data()
                self.assertEqual(d.shape, (3, 15))
                self.assertEqual(d.dtype, numpy.float32)
                self.assertTrue(numpy.allclose(d, 0))
        finally:
            #logging.debug("rmtree %s", data_dir)
            shutil.rmtree(data_dir)

    def test_hdf5_handler_write_chunks(self):
        current_working_directory = pathlib.Path.cwd()
        data_dir = current_working_directory / "__Test"
        if data_dir.exists():
            shutil.rmtree(data_dir)
        file_path = os.path.join(data_dir, "abc.h5")

        # Simple test with data shape divisible by chunk shape
        Cache.db_make_directory_if_needed(data_dir)
        try:
            h = HDF5Handler.HDF5Handler(file_path)
            with contextlib.closing(h):
                source_data = numpy.random.rand(10, 10).astype(numpy.float32)
                h._dataset = h._file.fp.create_dataset("data", shape=source_data.shape, dtype="float32", chunks=(5, 5))
                h.write_hdf5_chunks(source_data, (slice(0, 10), slice(0, 10)), (slice(0, 10), slice(0, 10)))
                d = h.read_data()
                self.assertTrue(numpy.allclose(d, source_data))
        finally:
            shutil.rmtree(data_dir)

        # More complex test case with incommensurate chunk sizes and data shapes
        Cache.db_make_directory_if_needed(data_dir)
        try:
            h = HDF5Handler.HDF5Handler(file_path)
            with contextlib.closing(h):
                source_data = numpy.random.rand(11, 17, 23).astype(numpy.float32)
                h._dataset = h._file.fp.create_dataset("data", shape=source_data.shape, dtype="float32", chunks=(2, 5, 12))
                h.write_hdf5_chunks(source_data, (slice(0, 11), slice(0, 17), slice(0, 23)), (slice(0, 11), slice(0, 17), slice(0, 23)))
                d = h.read_data()
                self.assertTrue(numpy.allclose(d, source_data))
        finally:
            shutil.rmtree(data_dir)

        # Test partial writes
        Cache.db_make_directory_if_needed(data_dir)
        try:
            h = HDF5Handler.HDF5Handler(file_path)
            with contextlib.closing(h):
                source_data = numpy.random.rand(11, 17, 23).astype(numpy.float32)
                h._dataset = h._file.fp.create_dataset("data", shape=source_data.shape, dtype="float32", chunks=(2, 7, 5))
                # Now write the data in multiple parts
                h.write_hdf5_chunks(source_data, (slice(0, 5), slice(0, 17), slice(0, 23)), (slice(0, 5), slice(0, 17), slice(0, 23)))
                h.write_hdf5_chunks(source_data, (slice(5, 6), slice(0, 11), slice(0, 23)), (slice(5, 6), slice(0, 11), slice(0, 23)))
                h.write_hdf5_chunks(source_data, (slice(5, 6), slice(11, 17), slice(0, 23)), (slice(5, 6), slice(11, 17), slice(0, 23)))
                h.write_hdf5_chunks(source_data, (slice(6, 7), slice(0, 17), slice(0, 12)), (slice(6, 7), slice(0, 17), slice(0, 12)))
                h.write_hdf5_chunks(source_data, (slice(6, 7), slice(0, 17), slice(12, 23)), (slice(6, 7), slice(0, 17), slice(12, 23)))
                h.write_hdf5_chunks(source_data, (slice(7, 11), slice(0, 17), slice(0, 23)), (slice(7, 11), slice(0, 17), slice(0, 23)))
                d = h.read_data()
                self.assertTrue(numpy.allclose(d, source_data))
        finally:
            shutil.rmtree(data_dir)

        # Test partial writes with complete slices indicated by slice(None, None, None)
        Cache.db_make_directory_if_needed(data_dir)
        try:
            h = HDF5Handler.HDF5Handler(file_path)
            with contextlib.closing(h):
                source_data = numpy.random.rand(11, 17, 23).astype(numpy.float32)
                h._dataset = h._file.fp.create_dataset("data", shape=source_data.shape, dtype="float32", chunks=(2, 7, 5))
                # Now write the data in multiple parts using slice(None) for complete slices
                h.write_hdf5_chunks(source_data, (slice(0, 5), slice(None), slice(None)), (slice(0, 5), slice(None), slice(None)))
                h.write_hdf5_chunks(source_data, (slice(5, 6), slice(0, 11), slice(None)), (slice(5, 6), slice(0, 11), slice(None)))
                h.write_hdf5_chunks(source_data, (slice(5, 6), slice(11, 17), slice(None)), (slice(5, 6), slice(11, 17), slice(None)))
                h.write_hdf5_chunks(source_data, (slice(6, 7), slice(None), slice(0, 12)), (slice(6, 7), slice(None), slice(0, 12)))
                h.write_hdf5_chunks(source_data, (slice(6, 7), slice(None), slice(12, 23)), (slice(6, 7), slice(None), slice(12, 23)))
                h.write_hdf5_chunks(source_data, (slice(7, 11), slice(None), slice(None)), (slice(7, 11), slice(None), slice(None)))
                d = h.read_data()
                self.assertTrue(numpy.allclose(d, source_data))
        finally:
            shutil.rmtree(data_dir)

    def test_hdf5_handler_bitshuffle_chunks_readable_by_standard_hdf5(self):
        import hdf5plugin  # registers the bitshuffle filter with h5py
        data_dir = pathlib.Path.cwd() / "__Test"
        if data_dir.exists():
            shutil.rmtree(data_dir)
        file_path = os.path.join(data_dir, "abc.h5")
        Cache.db_make_directory_if_needed(data_dir)
        try:
            cases = [((11, 17, 23), numpy.float32, (2, 5, 12)),
                     ((10, 10), numpy.float64, (5, 5)),
                     ((9, 31), numpy.int16, (4, 8))]
            for shape, dtype, chunks in cases:
                with self.subTest(shape=shape, dtype=dtype):
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    source_data = (numpy.random.rand(*shape) * 1000).astype(dtype)
                    h = HDF5Handler.HDF5Handler(file_path)
                    with contextlib.closing(h):
                        h._dataset = h._file.fp.create_dataset("data", shape=shape, dtype=dtype, chunks=chunks, compression=hdf5plugin.Bitshuffle(cname="lz4"))
                        full = tuple(slice(0, s) for s in shape)
                        h.write_hdf5_chunks(source_data, full, full)
                        h._wait_for_pending_writes()
                    # handler closed (executor shut down, file closed); read back with plain h5py
                    with h5py.File(file_path, "r") as f:
                        read_data = f["data"][:]
                    self.assertEqual(read_data.dtype, source_data.dtype)
                    self.assertTrue(numpy.array_equal(read_data, source_data))
        finally:
            shutil.rmtree(data_dir)
