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
from nion.swift.model import Graphics
from nion.ui import TestUI


class TestConnectionClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_connection_updates_target_when_source_changes(self):
        # setup document model
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item_3d = DataItem.DataItem(numpy.zeros((8, 8, 32), numpy.uint32))
            data_item_1d = DataItem.DataItem(numpy.zeros((32,), numpy.uint32))
            document_model.append_data_item(data_item_3d)
            document_model.append_data_item(data_item_1d)
            display_specifier_1d = DataItem.DisplaySpecifier.from_data_item(data_item_1d)
            display_specifier_3d = DataItem.DisplaySpecifier.from_data_item(data_item_3d)
            interval = Graphics.IntervalGraphic()
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item_1d)
            display_specifier.display.add_graphic(interval)
            connection = Connection.PropertyConnection(display_specifier_3d.display, "slice_center", interval, "start")
            data_item_1d.add_connection(connection)
            # test to see if connection updates target when source changes
            display_specifier_3d.display.slice_center = 12
            self.assertEqual(interval.start, 12)

    def test_connection_updates_source_when_target_changes(self):
        # setup document model
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item_3d = DataItem.DataItem(numpy.zeros((8, 8, 32), numpy.uint32))
            data_item_1d = DataItem.DataItem(numpy.zeros((32,), numpy.uint32))
            document_model.append_data_item(data_item_3d)
            document_model.append_data_item(data_item_1d)
            display_specifier_1d = DataItem.DisplaySpecifier.from_data_item(data_item_1d)
            display_specifier_3d = DataItem.DisplaySpecifier.from_data_item(data_item_3d)
            interval = Graphics.IntervalGraphic()
            display_specifier_1d.display.add_graphic(interval)
            connection = Connection.PropertyConnection(display_specifier_3d.display, "slice_center", interval, "start")
            data_item_1d.add_connection(connection)
            # test to see if connection updates target when source changes
            interval.start = 9
            self.assertEqual(display_specifier_3d.display.slice_center, 9)

    def test_connection_saves_and_restores(self):
        # setup document
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_systems=[memory_persistent_storage_system])
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item_3d = DataItem.DataItem(numpy.zeros((8, 8, 32), numpy.uint32))
            data_item_1d = DataItem.DataItem(numpy.zeros((32,), numpy.uint32))
            document_model.append_data_item(data_item_3d)
            document_model.append_data_item(data_item_1d)
            display_specifier_1d = DataItem.DisplaySpecifier.from_data_item(data_item_1d)
            display_specifier_3d = DataItem.DisplaySpecifier.from_data_item(data_item_3d)
            interval = Graphics.IntervalGraphic()
            display_specifier_1d.display.add_graphic(interval)
            connection = Connection.PropertyConnection(display_specifier_3d.display, "slice_center", interval, "start")
            data_item_1d.add_connection(connection)
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_systems=[memory_persistent_storage_system])
        with contextlib.closing(document_model):
            # verify it read back
            data_item_3d = document_model.data_items[0]
            data_item_1d = document_model.data_items[1]
            display_specifier_1d = DataItem.DisplaySpecifier.from_data_item(data_item_1d)
            display_specifier_3d = DataItem.DisplaySpecifier.from_data_item(data_item_3d)
            interval = display_specifier_1d.display.graphics[0]
            self.assertEqual(len(data_item_1d.connections), 1)
            # verify connection is working in both directions
            display_specifier_3d.display.slice_center = 11
            self.assertEqual(interval.start, 11)
            interval.start = 7
            self.assertEqual(display_specifier_3d.display.slice_center, 7)

    def test_connection_closed_when_removed_from_data_item(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item_3d = DataItem.DataItem(numpy.zeros((32, 8, 8), numpy.uint32))
            data_item_1d = DataItem.DataItem(numpy.zeros((32,), numpy.uint32))
            document_model.append_data_item(data_item_3d)
            document_model.append_data_item(data_item_1d)
            display_specifier_1d = DataItem.DisplaySpecifier.from_data_item(data_item_1d)
            display_specifier_3d = DataItem.DisplaySpecifier.from_data_item(data_item_3d)
            interval = Graphics.IntervalGraphic()
            display_specifier_1d.display.add_graphic(interval)
            connection = Connection.PropertyConnection(display_specifier_3d.display, "slice_center", interval, "start")
            data_item_1d.add_connection(connection)
            self.assertFalse(connection._closed)
            data_item_1d.remove_connection(connection)
            self.assertTrue(connection._closed)

    def test_connection_closed_when_data_item_removed_from_model(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item_3d = DataItem.DataItem(numpy.zeros((32, 8, 8), numpy.uint32))
            data_item_1d = DataItem.DataItem(numpy.zeros((32,), numpy.uint32))
            document_model.append_data_item(data_item_3d)
            document_model.append_data_item(data_item_1d)
            display_specifier_1d = DataItem.DisplaySpecifier.from_data_item(data_item_1d)
            display_specifier_3d = DataItem.DisplaySpecifier.from_data_item(data_item_3d)
            interval = Graphics.IntervalGraphic()
            display_specifier_1d.display.add_graphic(interval)
            connection = Connection.PropertyConnection(display_specifier_3d.display, "slice_center", interval, "start")
            data_item_1d.add_connection(connection)
            self.assertFalse(connection._closed)
            document_model.remove_data_item(data_item_1d)
            self.assertTrue(connection._closed)

    def test_connection_updates_interval_descriptors_on_line_profile_graphic_from_source(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(data_item)
            line_profile_display_specifier = document_controller.processing_line_profile()
            interval_region = Graphics.IntervalGraphic()
            interval = 0.2, 0.3
            interval_region.interval = interval
            line_profile_display_specifier.display.add_graphic(interval_region)
            line_profile_graphic = display_specifier.display.graphics[0]
            interval_descriptors = line_profile_graphic.interval_descriptors
            self.assertEqual(len(interval_descriptors), 1)
            self.assertEqual(interval_descriptors[0]["interval"], interval)

    def test_connection_updates_interval_descriptors_when_interval_mutates(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(data_item)
            line_profile_display_specifier = document_controller.processing_line_profile()
            interval_region = Graphics.IntervalGraphic()
            line_profile_display_specifier.display.add_graphic(interval_region)
            interval = 0.2, 0.3
            interval_region.interval = interval
            line_profile_graphic = display_specifier.display.graphics[0]
            interval_descriptors = line_profile_graphic.interval_descriptors
            self.assertEqual(len(interval_descriptors), 1)
            self.assertEqual(interval_descriptors[0]["interval"], interval)

    def test_connection_establishes_transaction_on_source(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item_src = DataItem.DataItem(numpy.zeros((1000, )))
            data_item_dst = DataItem.DataItem(numpy.zeros((1000, )))
            interval_src = Graphics.IntervalGraphic()
            interval_dst = Graphics.IntervalGraphic()
            data_item_src.displays[0].add_graphic(interval_src)
            data_item_dst.displays[0].add_graphic(interval_dst)
            document_model.append_data_item(data_item_src)
            document_model.append_data_item(data_item_dst)
            connection = Connection.PropertyConnection(interval_src, "interval", interval_dst, "interval")
            data_item_dst.add_connection(connection)
            # check dependencies
            with document_model.item_transaction(data_item_dst):
                self.assertIn(data_item_dst.uuid, document_model._transactions.keys())
                self.assertIn(interval_dst.uuid, document_model._transactions.keys())
                self.assertIn(interval_src.uuid, document_model._transactions.keys())
                self.assertNotIn(data_item_src.uuid, document_model._transactions.keys())
            self.assertFalse(document_model._transactions)

    def test_connection_establishes_transaction_on_parallel_source_connection(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item_src = DataItem.DataItem(numpy.zeros((1000, )))
            data_item_dst1 = DataItem.DataItem(numpy.zeros((1000, )))
            data_item_dst2 = DataItem.DataItem(numpy.zeros((1000, )))
            interval_src = Graphics.IntervalGraphic()
            interval_dst1 = Graphics.IntervalGraphic()
            interval_dst2 = Graphics.IntervalGraphic()
            data_item_src.displays[0].add_graphic(interval_src)
            data_item_dst1.displays[0].add_graphic(interval_dst1)
            data_item_dst2.displays[0].add_graphic(interval_dst2)
            document_model.append_data_item(data_item_src)
            document_model.append_data_item(data_item_dst1)
            document_model.append_data_item(data_item_dst2)
            connection1 = Connection.PropertyConnection(interval_src, "interval", interval_dst1, "interval")
            data_item_dst1.add_connection(connection1)
            connection2 = Connection.PropertyConnection(interval_src, "interval", interval_dst2, "interval")
            data_item_dst2.add_connection(connection2)
            # check dependencies
            with document_model.item_transaction(data_item_dst1):
                self.assertIn(data_item_dst1.uuid, document_model._transactions.keys())
                self.assertIn(interval_dst1.uuid, document_model._transactions.keys())
                self.assertIn(interval_src.uuid, document_model._transactions.keys())
                self.assertNotIn(data_item_dst2.uuid, document_model._transactions.keys())
                self.assertIn(interval_dst2.uuid, document_model._transactions.keys())
                self.assertNotIn(data_item_src.uuid, document_model._transactions.keys())
            self.assertFalse(document_model._transactions)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
