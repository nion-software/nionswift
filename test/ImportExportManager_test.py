# standard libraries
import datetime
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import ImportExportManager
from nion.swift import DataItem


class TestImportExportManagerClass(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_data_element(self):
        data_element = dict()
        data_element["data"] = numpy.zeros((16, 16), dtype=numpy.double)
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        self.assertIsNotNone(data_item.datetime_original)
        self.assertIsNotNone(data_item.datetime_modified)
        self.assertEqual(len(data_item.datetime_original["local_datetime"]), 26)
        self.assertEqual(len(data_item.datetime_original["tz"]), 5)
        self.assertEqual(len(data_item.datetime_original["dst"]), 3)
        data_item.add_ref()
        data_item.remove_ref()

    def test_date_formats(self):
        data_item = DataItem.DataItem()
        data_item.datetime_original = {"local_datetime": datetime.datetime(2013, 11, 18, 14, 5, 4, 0).isoformat(), "tz": "+0000", "dst": "+00"}
        data_item.datetime_original_as_string

    def test_sub_area_size_change(self):
        data_element = dict()
        data_element["data"] = numpy.zeros((16, 16), dtype=numpy.double)
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        with data_item.ref():
            self.assertEqual(data_item.spatial_shape, (16, 16))
            self.assertEqual(data_item.data_dtype, numpy.double)
            data_element["data"] = numpy.zeros((8, 8), dtype=numpy.double)
            data_element["sub_area"] = ((0,0), (4, 8))
            ImportExportManager.update_data_item_from_data_element(data_item, data_element)
            self.assertEqual(data_item.spatial_shape, (8, 8))
            self.assertEqual(data_item.data_dtype, numpy.double)
            data_element["data"] = numpy.zeros((8, 8), dtype=numpy.float)
            data_element["sub_area"] = ((0,0), (4, 8))
            ImportExportManager.update_data_item_from_data_element(data_item, data_element)
            self.assertEqual(data_item.spatial_shape, (8, 8))
            self.assertEqual(data_item.data_dtype, numpy.float)

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
