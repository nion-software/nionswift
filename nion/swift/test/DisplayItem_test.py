# standard libraries
import contextlib
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import Facade
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import DocumentModel
from nion.ui import TestUI


Facade.initialize()


class TestDisplayItemClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_display_item_with_multiple_display_data_channels_has_sensible_properties(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2, False)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item2))
            self.assertIsNotNone(display_item.size_and_data_format_as_string)
            self.assertIsNotNone(display_item.date_for_sorting)
            self.assertIsNotNone(display_item.date_for_sorting_local_as_string)
            self.assertIsNotNone(display_item.status_str)


if __name__ == '__main__':
    unittest.main()
