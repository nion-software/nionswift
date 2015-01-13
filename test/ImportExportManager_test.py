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


class TestImportExportManagerClass(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_data_element(self):
        data_element = dict()
        data_element["version"] = 1
        data_element["data"] = numpy.zeros((16, 16), dtype=numpy.double)
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        self.assertIsNotNone(data_item.datetime_original)
        self.assertIsNotNone(data_item.datetime_modified)
        self.assertEqual(len(data_item.datetime_original["local_datetime"]), 26)
        self.assertEqual(len(data_item.datetime_original["tz"]), 5)
        self.assertEqual(len(data_item.datetime_original["dst"]), 3)

    def test_date_formats(self):
        data_item = DataItem.DataItem()
        data_item.datetime_original = {"local_datetime": datetime.datetime(2013, 11, 18, 14, 5, 4, 0).isoformat(), "tz": "+0000", "dst": "+00"}
        data_item.datetime_original_as_string

    def test_sub_area_size_change(self):
        data_element = dict()
        data_element["version"] = 1
        data_element["data"] = numpy.zeros((16, 16), dtype=numpy.double)
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        self.assertEqual(data_item.maybe_data_source.dimensional_shape, (16, 16))
        self.assertEqual(data_item.maybe_data_source.data_dtype, numpy.double)
        data_element["data"] = numpy.zeros((8, 8), dtype=numpy.double)
        data_element["sub_area"] = ((0,0), (4, 8))
        ImportExportManager.update_data_item_from_data_element(data_item, data_element)
        self.assertEqual(data_item.maybe_data_source.dimensional_shape, (8, 8))
        self.assertEqual(data_item.maybe_data_source.data_dtype, numpy.double)
        data_element["data"] = numpy.zeros((8, 8), dtype=numpy.float)
        data_element["sub_area"] = ((0,0), (4, 8))
        ImportExportManager.update_data_item_from_data_element(data_item, data_element)
        self.assertEqual(data_item.maybe_data_source.dimensional_shape, (8, 8))
        self.assertEqual(data_item.maybe_data_source.data_dtype, numpy.float)

    def test_ndata_write_to_then_read_from_temp_file(self):
        current_working_directory = os.getcwd()
        file_path = os.path.join(current_working_directory, "__file.ndata")
        handler = ImportExportManager.NDataImportExportHandler("ndata", ["ndata"])
        data_item = DataItem.DataItem(numpy.zeros((16, 16), dtype=numpy.double))
        handler.write(None, data_item, file_path, "ndata")
        self.assertTrue(os.path.exists(file_path))
        try:
            data_items = handler.read_data_items(None, "ndata", file_path)
            self.assertEqual(len(data_items), 1)
            data_item = data_items[0]
        finally:
            os.remove(file_path)

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
