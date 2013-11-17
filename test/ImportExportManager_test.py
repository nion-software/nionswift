# standard libraries
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import ImportExportManager


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


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
