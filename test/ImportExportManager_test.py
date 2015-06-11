# futures
from __future__ import absolute_import

# standard libraries
import datetime
import logging
import os
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift.model import DataItem
from nion.swift.model import ImportExportManager
from nion.swift.model import Utility


class TestImportExportManagerClass(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_data_element(self):
        data_element = dict()
        data_element["version"] = 1
        data_element["data"] = numpy.zeros((16, 16), dtype=numpy.double)
        data_element["datetime_modified"] = Utility.get_current_datetime_item()
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        self.assertIsNotNone(data_item.created)
        self.assertEqual(len(data_item.metadata["description"]["time_zone"]["tz"]), 5)
        self.assertEqual(len(data_item.metadata["description"]["time_zone"]["dst"]), 3)

    def test_date_formats(self):
        data_item = DataItem.DataItem()
        data_item.created = datetime.datetime(2013, 11, 18, 14, 5, 4, 0)
        data_item.created_local_as_string

    def test_sub_area_size_change(self):
        data_element = dict()
        data_element["version"] = 1
        data_element["data"] = numpy.zeros((16, 16), dtype=numpy.double)
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        self.assertEqual(display_specifier.buffered_data_source.dimensional_shape, (16, 16))
        self.assertEqual(display_specifier.buffered_data_source.data_dtype, numpy.double)
        data_element["data"] = numpy.zeros((8, 8), dtype=numpy.double)
        data_element["sub_area"] = ((0,0), (4, 8))
        ImportExportManager.update_data_item_from_data_element(data_item, data_element)
        self.assertEqual(display_specifier.buffered_data_source.dimensional_shape, (8, 8))
        self.assertEqual(display_specifier.buffered_data_source.data_dtype, numpy.double)
        data_element["data"] = numpy.zeros((8, 8), dtype=numpy.float)
        data_element["sub_area"] = ((0,0), (4, 8))
        ImportExportManager.update_data_item_from_data_element(data_item, data_element)
        self.assertEqual(display_specifier.buffered_data_source.dimensional_shape, (8, 8))
        self.assertEqual(display_specifier.buffered_data_source.data_dtype, numpy.float)

    def test_ndata_write_to_then_read_from_temp_file(self):
        current_working_directory = os.getcwd()
        file_path = os.path.join(current_working_directory, "__file.ndata")
        handler = ImportExportManager.NDataImportExportHandler("ndata1-io-handler", "ndata", ["ndata"])
        data_item = DataItem.DataItem(numpy.zeros((16, 16), dtype=numpy.double))
        handler.write(None, data_item, file_path, "ndata")
        self.assertTrue(os.path.exists(file_path))
        try:
            data_items = handler.read_data_items(None, "ndata", file_path)
            self.assertEqual(len(data_items), 1)
            data_item = data_items[0]
        finally:
            os.remove(file_path)

    def test_get_writers_for_empty_data_item_returns_valid_list(self):
        data_item = DataItem.DataItem()
        writers = ImportExportManager.ImportExportManager().get_writers_for_data_item(data_item)
        self.assertEqual(len(writers), 0)

    def test_get_writers_for_float_2d_data_item_returns_valid_list(self):
        data_item = DataItem.DataItem(numpy.zeros((64, 64), numpy.float))
        writers = ImportExportManager.ImportExportManager().get_writers_for_data_item(data_item)
        self.assertTrue(len(writers) > 0)

    def test_data_element_date(self):
        data_element = dict()
        data_element["version"] = 1
        data_element["data"] = numpy.zeros((16, 16), dtype=numpy.double)
        data_element["datetime_modified"] = {'tz': '-0700', 'dst': '+60', 'local_datetime': '2015-06-10T09:31:52.780511'}
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        self.assertIsNotNone(data_item.created)
        self.assertEqual(len(data_item.metadata["description"]["time_zone"]["tz"]), 5)
        self.assertEqual(len(data_item.metadata["description"]["time_zone"]["dst"]), 3)
        match = datetime.datetime(year=2015, month=6, day=10, hour=9, minute=31, second=52, microsecond=780511)
        self.assertEqual(data_item.created_local, match)

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
