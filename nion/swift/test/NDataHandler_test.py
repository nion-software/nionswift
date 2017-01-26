# standard libraries
import binascii
import contextlib
import datetime
import io
import json
import logging
import os
import shutil
import unittest
import uuid

# third party libraries
import numpy

# local libraries
from nion.swift.model import NDataHandler
from nion.swift.model import Cache


class TestNDataHandlerClass(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_ndata_handler_basic_functionality(self):
        now = datetime.datetime.now()
        current_working_directory = os.getcwd()
        data_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(data_dir)
        try:
            h = NDataHandler.NDataHandler(os.path.join(data_dir, "abc.ndata"))
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
        finally:
            #logging.debug("rmtree %s", data_dir)
            shutil.rmtree(data_dir)

    def test_ndata_handler_rewrites_reversed_zip_file(self):
        now = datetime.datetime.now()
        current_working_directory = os.getcwd()
        data_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(data_dir)
        try:
            p = {u"abc": 1, u"def": u"bcd", u"uuid": str(uuid.uuid4())}
            d = numpy.zeros((12,12), dtype=numpy.float32)
            # write zip file where metadata is first
            with open(os.path.join(data_dir, "file.ndata"), "w+b") as fp:
                dir_data_list = list()
                dt = now
                properties = p
                data = d
                if properties is not None:
                    json_io = io.StringIO()
                    json.dump(properties, json_io)
                    json_str = json_io.getvalue()
                    def write_json(fp):
                        json_bytes = bytes(json_str, 'ISO-8859-1')
                        fp.write(json_bytes)
                        return binascii.crc32(json_bytes) & 0xFFFFFFFF
                    offset_json = fp.tell()
                    json_len, json_crc32 = NDataHandler.write_local_file(fp, b"metadata.json", write_json, dt)
                    dir_data_list.append((offset_json, b"metadata.json", json_len, json_crc32))
                if data is not None:
                    offset_data = fp.tell()
                    def write_data(fp):
                        numpy_start_pos = fp.tell()
                        numpy.save(fp, data)
                        numpy_end_pos = fp.tell()
                        fp.seek(numpy_start_pos)
                        header_data = fp.read((numpy_end_pos - numpy_start_pos) - data.nbytes)  # read the header
                        data_crc32 = binascii.crc32(data.data, binascii.crc32(header_data)) & 0xFFFFFFFF
                        fp.seek(numpy_end_pos)
                        return data_crc32
                    data_len, crc32 = NDataHandler.write_local_file(fp, b"data.npy", write_data, dt)
                    dir_data_list.append((offset_data, b"data.npy", data_len, crc32))
                dir_offset = fp.tell()
                for offset, name_bytes, data_len, crc32 in dir_data_list:
                    NDataHandler.write_directory_data(fp, offset, name_bytes, data_len, crc32, dt)
                dir_size = fp.tell() - dir_offset
                NDataHandler.write_end_of_directory(fp, dir_size, dir_offset, len(dir_data_list))
                fp.truncate()
            # make sure read works
            h = NDataHandler.NDataHandler(os.path.join(data_dir, "file.ndata"))
            with contextlib.closing(h):
                self.assertEqual(h.read_properties(), p)
                dd = h.read_data()
                self.assertEqual(dd.shape, d.shape)
                self.assertEqual(dd.dtype, d.dtype)
                # now rewrite
                h.write_properties(p, now)
        finally:
            #logging.debug("rmtree %s", data_dir)
            shutil.rmtree(data_dir)

    def test_ndata_handles_discontiguous_data(self):
        logging.getLogger().setLevel(logging.DEBUG)
        now = datetime.datetime.now()
        current_working_directory = os.getcwd()
        data_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(data_dir)
        try:
            h = NDataHandler.NDataHandler(os.path.join(data_dir, "abc.ndata"))
            with contextlib.closing(h):
                data = numpy.random.randint(0, 10, size=(10, 10))[:,3]  # discontiguous data
                self.assertFalse(data.flags['C_CONTIGUOUS'])
                p = {u"uuid": str(uuid.uuid4())}
                # write properties
                h.write_properties(p, now)
                # write data
                h.write_data(data, now)
                d = h.read_data()
                self.assertEqual(d.shape, data.shape)
                self.assertEqual(d.dtype, data.dtype)
        finally:
            #logging.debug("rmtree %s", data_dir)
            shutil.rmtree(data_dir)

    def test_ndata_handles_corrupt_data(self):
        logging.getLogger().setLevel(logging.DEBUG)
        now = datetime.datetime.now()
        current_working_directory = os.getcwd()
        data_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(data_dir)
        try:
            zero_path = os.path.join(data_dir, "zeros.ndata")
            with open(zero_path, 'wb') as f:
                f.write(bytearray(1024))
            with self.assertRaises(IOError):
                with open(zero_path, "rb") as fp:
                    NDataHandler.parse_zip(fp)
        finally:
            #logging.debug("rmtree %s", data_dir)
            shutil.rmtree(data_dir)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
