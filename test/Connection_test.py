# futures
from __future__ import absolute_import

# standard libraries
import contextlib
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift.model import Connection
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Region
from nion.ui import Test


class TestConnectionClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_connection_updates_target_when_source_changes(self):
        # setup document model
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item_3d = DataItem.DataItem(numpy.zeros((32, 8, 8), numpy.uint32))
            data_item_1d = DataItem.DataItem(numpy.zeros((32,), numpy.uint32))
            document_model.append_data_item(data_item_3d)
            document_model.append_data_item(data_item_1d)
            display_specifier_1d = DataItem.DisplaySpecifier.from_data_item(data_item_1d)
            display_specifier_3d = DataItem.DisplaySpecifier.from_data_item(data_item_3d)
            interval = Region.IntervalRegion()
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item_1d)
            display_specifier.buffered_data_source.add_region(interval)
            connection = Connection.PropertyConnection(display_specifier_3d.display, "slice_center", interval, "start")
            data_item_1d.add_connection(connection)
            # test to see if connection updates target when source changes
            display_specifier_3d.display.slice_center = 12
            self.assertEqual(interval.start, 12)

    def test_connection_updates_source_when_target_changes(self):
        # setup document model
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item_3d = DataItem.DataItem(numpy.zeros((32, 8, 8), numpy.uint32))
            data_item_1d = DataItem.DataItem(numpy.zeros((32,), numpy.uint32))
            document_model.append_data_item(data_item_3d)
            document_model.append_data_item(data_item_1d)
            display_specifier_1d = DataItem.DisplaySpecifier.from_data_item(data_item_1d)
            display_specifier_3d = DataItem.DisplaySpecifier.from_data_item(data_item_3d)
            interval = Region.IntervalRegion()
            display_specifier_1d.buffered_data_source.add_region(interval)
            connection = Connection.PropertyConnection(display_specifier_3d.display, "slice_center", interval, "start")
            data_item_1d.add_connection(connection)
            # test to see if connection updates target when source changes
            interval.start = 9
            self.assertEqual(display_specifier_3d.display.slice_center, 9)

    def test_connection_saves_and_restores(self):
        # setup document
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item_3d = DataItem.DataItem(numpy.zeros((32, 8, 8), numpy.uint32))
            data_item_1d = DataItem.DataItem(numpy.zeros((32,), numpy.uint32))
            document_model.append_data_item(data_item_3d)
            document_model.append_data_item(data_item_1d)
            display_specifier_1d = DataItem.DisplaySpecifier.from_data_item(data_item_1d)
            display_specifier_3d = DataItem.DisplaySpecifier.from_data_item(data_item_3d)
            interval = Region.IntervalRegion()
            display_specifier_1d.buffered_data_source.add_region(interval)
            connection = Connection.PropertyConnection(display_specifier_3d.display, "slice_center", interval, "start")
            data_item_1d.add_connection(connection)
        # read it back
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        with contextlib.closing(document_model):
            # verify it read back
            data_item_3d = document_model.data_items[0]
            data_item_1d = document_model.data_items[1]
            display_specifier_1d = DataItem.DisplaySpecifier.from_data_item(data_item_1d)
            display_specifier_3d = DataItem.DisplaySpecifier.from_data_item(data_item_3d)
            interval = display_specifier_1d.buffered_data_source.regions[0]
            self.assertEqual(len(data_item_1d.connections), 1)
            # verify connection is working in both directions
            display_specifier_3d.display.slice_center = 11
            self.assertEqual(interval.start, 11)
            interval.start = 7
            self.assertEqual(display_specifier_3d.display.slice_center, 7)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
