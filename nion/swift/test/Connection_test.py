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
from nion.swift.model import Profile
from nion.swift.model import Symbolic
from nion.ui import TestUI


def create_memory_profile_context():
    return Profile.MemoryProfileContext()


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
            display_item_1d = document_model.get_display_item_for_data_item(data_item_1d)
            display_item_3d = document_model.get_display_item_for_data_item(data_item_1d)
            interval = Graphics.IntervalGraphic()
            display_item_1d.add_graphic(interval)
            connection = Connection.PropertyConnection(display_item_3d.display_data_channels[0], "slice_center", interval, "start", parent=data_item_1d)
            document_model.append_connection(connection)
            # test to see if connection updates target when source changes
            display_item_3d.display_data_channels[0].slice_center = 12
            self.assertEqual(interval.start, 12)

    def test_connection_updates_source_when_target_changes(self):
        # setup document model
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item_3d = DataItem.DataItem(numpy.zeros((8, 8, 32), numpy.uint32))
            data_item_1d = DataItem.DataItem(numpy.zeros((32,), numpy.uint32))
            document_model.append_data_item(data_item_3d)
            document_model.append_data_item(data_item_1d)
            display_item_1d = document_model.get_display_item_for_data_item(data_item_1d)
            display_item_3d = document_model.get_display_item_for_data_item(data_item_1d)
            interval = Graphics.IntervalGraphic()
            display_item_1d.add_graphic(interval)
            display_data_channel_3d = display_item_3d.display_data_channels[0]
            connection = Connection.PropertyConnection(display_data_channel_3d, "slice_center", interval, "start", parent=data_item_1d)
            document_model.append_connection(connection)
            # test to see if connection updates target when source changes
            interval.start = 9
            self.assertEqual(display_data_channel_3d.slice_center, 9)

    def test_connection_saves_and_restores(self):
        # setup document
        with create_memory_profile_context() as profile_context:
            document_model = DocumentModel.DocumentModel(profile=profile_context.create_profile())
            with contextlib.closing(document_model):
                data_item_3d = DataItem.DataItem(numpy.zeros((8, 8, 32), numpy.uint32))
                data_item_1d = DataItem.DataItem(numpy.zeros((32,), numpy.uint32))
                document_model.append_data_item(data_item_3d)
                document_model.append_data_item(data_item_1d)
                display_item_1d = document_model.get_display_item_for_data_item(data_item_1d)
                display_item_3d = document_model.get_display_item_for_data_item(data_item_1d)
                interval = Graphics.IntervalGraphic()
                display_item_1d.add_graphic(interval)
                connection = Connection.PropertyConnection(display_item_3d.display_data_channels[0], "slice_center", interval, "start", parent=data_item_1d)
                document_model.append_connection(connection)
            # read it back
            document_model = DocumentModel.DocumentModel(profile=profile_context.create_profile())
            with contextlib.closing(document_model):
                # verify it read back
                data_item_3d = document_model.data_items[0]
                data_item_1d = document_model.data_items[1]
                display_item_1d = document_model.get_display_item_for_data_item(data_item_1d)
                display_item_3d = document_model.get_display_item_for_data_item(data_item_1d)
                interval = display_item_1d.graphics[0]
                self.assertEqual(1, len(document_model.connections))
                # verify connection is working in both directions
                display_data_channel_3d = display_item_3d.display_data_channels[0]
                display_data_channel_3d.slice_center = 11
                self.assertEqual(interval.start, 11)
                interval.start = 7
                self.assertEqual(display_data_channel_3d.slice_center, 7)

    def test_connection_closed_when_removed_from_data_item(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item_3d = DataItem.DataItem(numpy.zeros((32, 8, 8), numpy.uint32))
            data_item_1d = DataItem.DataItem(numpy.zeros((32,), numpy.uint32))
            document_model.append_data_item(data_item_3d)
            document_model.append_data_item(data_item_1d)
            display_item_1d = document_model.get_display_item_for_data_item(data_item_1d)
            display_item_3d = document_model.get_display_item_for_data_item(data_item_1d)
            interval = Graphics.IntervalGraphic()
            display_item_1d.add_graphic(interval)
            connection = Connection.PropertyConnection(display_item_3d.display_data_channels[0], "slice_center", interval, "start", parent=data_item_1d)
            document_model.append_connection(connection)
            self.assertFalse(connection._closed)
            document_model.remove_connection(connection)
            self.assertTrue(connection._closed)

    def test_connection_closed_when_data_item_removed_from_model(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item_3d = DataItem.DataItem(numpy.zeros((32, 8, 8), numpy.uint32))
            data_item_1d = DataItem.DataItem(numpy.zeros((32,), numpy.uint32))
            document_model.append_data_item(data_item_3d)
            document_model.append_data_item(data_item_1d)
            display_item_1d = document_model.get_display_item_for_data_item(data_item_1d)
            display_item_3d = document_model.get_display_item_for_data_item(data_item_1d)
            interval = Graphics.IntervalGraphic()
            display_item_1d.add_graphic(interval)
            connection = Connection.PropertyConnection(display_item_3d.display_data_channels[0], "slice_center", interval, "start", parent=data_item_1d)
            document_model.append_connection(connection)
            self.assertFalse(connection._closed)
            document_model.remove_data_item(data_item_1d)
            self.assertTrue(connection._closed)

    def test_connection_updates_interval_descriptors_on_line_profile_graphic_from_source(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            line_profile_display_item = document_controller.processing_line_profile()
            interval_region = Graphics.IntervalGraphic()
            interval = 0.2, 0.3
            interval_region.interval = interval
            line_profile_display_item.add_graphic(interval_region)
            line_profile_graphic = display_item.graphics[0]
            interval_descriptors = line_profile_graphic.interval_descriptors
            self.assertEqual(len(interval_descriptors), 1)
            self.assertEqual(interval_descriptors[0]["interval"], interval)

    def test_connection_updates_interval_descriptors_when_interval_mutates(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            line_profile_display_item = document_controller.processing_line_profile()
            interval_region = Graphics.IntervalGraphic()
            line_profile_display_item.add_graphic(interval_region)
            interval = 0.2, 0.3
            interval_region.interval = interval
            line_profile_graphic = display_item.graphics[0]
            interval_descriptors = line_profile_graphic.interval_descriptors
            self.assertEqual(len(interval_descriptors), 1)
            self.assertEqual(interval_descriptors[0]["interval"], interval)

    def test_connection_establishes_transaction_on_source(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item_src = DataItem.DataItem(numpy.zeros((1000, )))
            data_item_dst = DataItem.DataItem(numpy.zeros((1000, )))
            document_model.append_data_item(data_item_src)
            document_model.append_data_item(data_item_dst)
            display_item_src = document_model.get_display_item_for_data_item(data_item_src)
            display_item_dst = document_model.get_display_item_for_data_item(data_item_dst)
            interval_src = Graphics.IntervalGraphic()
            interval_dst = Graphics.IntervalGraphic()
            display_item_src.add_graphic(interval_src)
            display_item_dst.add_graphic(interval_dst)
            connection = Connection.PropertyConnection(interval_src, "interval", interval_dst, "interval", parent=data_item_dst)
            document_model.append_connection(connection)
            # check dependencies
            with document_model.item_transaction(data_item_dst):
                self.assertTrue(document_model.is_in_transaction_state(data_item_dst))
                self.assertTrue(document_model.is_in_transaction_state(display_item_dst))
                self.assertTrue(document_model.is_in_transaction_state(interval_dst))
                self.assertTrue(document_model.is_in_transaction_state(interval_src))
                self.assertTrue(document_model.is_in_transaction_state(display_item_src))
            self.assertEqual(0, document_model.transaction_count)

    def test_connection_establishes_transaction_on_parallel_source_connection(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item_src = DataItem.DataItem(numpy.zeros((1000, )))
            data_item_dst1 = DataItem.DataItem(numpy.zeros((1000, )))
            data_item_dst2 = DataItem.DataItem(numpy.zeros((1000, )))
            document_model.append_data_item(data_item_src)
            document_model.append_data_item(data_item_dst1)
            document_model.append_data_item(data_item_dst2)
            display_item_src = document_model.get_display_item_for_data_item(data_item_src)
            display_item_dst1 = document_model.get_display_item_for_data_item(data_item_dst1)
            display_item_dst2 = document_model.get_display_item_for_data_item(data_item_dst2)
            interval_src = Graphics.IntervalGraphic()
            interval_dst1 = Graphics.IntervalGraphic()
            interval_dst2 = Graphics.IntervalGraphic()
            display_item_src.add_graphic(interval_src)
            display_item_dst1.add_graphic(interval_dst1)
            display_item_dst2.add_graphic(interval_dst2)
            connection1 = Connection.PropertyConnection(interval_src, "interval", interval_dst1, "interval", parent=data_item_dst1)
            connection2 = Connection.PropertyConnection(interval_src, "interval", interval_dst2, "interval", parent=data_item_dst2)
            document_model.append_connection(connection1)
            document_model.append_connection(connection2)
            # check dependencies
            with document_model.item_transaction(data_item_dst1):
                self.assertTrue(document_model.is_in_transaction_state(data_item_dst1))
                self.assertTrue(document_model.is_in_transaction_state(interval_dst1))
                self.assertTrue(document_model.is_in_transaction_state(interval_src))
                self.assertTrue(document_model.is_in_transaction_state(display_item_dst2))  # from graphic
                self.assertTrue(document_model.is_in_transaction_state(interval_dst2))
                self.assertTrue(document_model.is_in_transaction_state(display_item_src))  # from graphic
            self.assertEqual(0, document_model.transaction_count)

    def test_connection_between_data_structures(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            data_struct1 = document_model.create_data_structure()
            data_struct2 = document_model.create_data_structure()
            data_struct1.set_property_value("title", "t1")
            data_struct2.set_property_value("title", "t2")
            document_model.append_data_structure(data_struct1)
            document_model.append_data_structure(data_struct2)
            connection = Connection.PropertyConnection(data_struct1, "title", data_struct2, "title", parent=data_item)
            document_model.append_connection(connection)
            data_struct1.set_property_value("title", "T1")
            self.assertEqual("T1", data_struct1.get_property_value("title"))
            self.assertEqual("T1", data_struct2.get_property_value("title"))
            data_struct2.set_property_value("title", "T2")
            self.assertEqual("T2", data_struct1.get_property_value("title"))
            self.assertEqual("T2", data_struct2.get_property_value("title"))

    def test_connection_establishes_transaction_on_target_data_structure(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item1 = DataItem.DataItem(numpy.zeros((2, 2)))
            data_item2 = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            interval1 = Graphics.IntervalGraphic()
            interval2 = Graphics.IntervalGraphic()
            display_item1.add_graphic(interval1)
            display_item2.add_graphic(interval2)
            data_struct1 = document_model.create_data_structure()
            data_struct2 = document_model.create_data_structure()
            data_struct1.set_property_value("x_interval", (0.5, 0.1))
            data_struct2.set_property_value("x_interval", (0.5, 0.2))
            document_model.append_data_structure(data_struct1)
            document_model.append_data_structure(data_struct2)
            connection1 = Connection.PropertyConnection(data_struct1, "x_interval", interval1, "interval", parent=data_item1)
            connection2 = Connection.PropertyConnection(interval2, "interval", data_struct2, "x_interval", parent=data_item2)
            document_model.append_connection(connection1)
            document_model.append_connection(connection2)
            with document_model.item_transaction(data_item1):
                self.assertTrue(document_model.is_in_transaction_state(data_item1))
                self.assertTrue(document_model.is_in_transaction_state(display_item1))
                self.assertTrue(document_model.is_in_transaction_state(data_struct1))
            with document_model.item_transaction(data_item2):
                self.assertTrue(document_model.is_in_transaction_state(data_item2))
                self.assertTrue(document_model.is_in_transaction_state(display_item2))
                self.assertTrue(document_model.is_in_transaction_state(data_struct2))
            self.assertEqual(0, document_model.transaction_count)

    def test_connection_establishes_transaction_on_target_data_structure_dependent(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((20, )))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            interval = Graphics.IntervalGraphic()
            display_item.add_graphic(interval)
            data_struct = document_model.create_data_structure()
            data_struct.set_property_value("x_interval", (0.5, 0.1))
            document_model.append_data_structure(data_struct)
            connection = Connection.PropertyConnection(data_struct, "x_interval", interval, "interval", parent=data_item)
            document_model.append_connection(connection)
            computed_data_item = DataItem.DataItem(numpy.zeros((100, )))
            document_model.append_data_item(computed_data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            computation.create_input_item("d", Symbolic.make_item(data_struct))
            document_model.set_data_item_computation(computed_data_item, computation)
            with document_model.item_transaction(data_item):
                self.assertTrue(document_model.is_in_transaction_state(data_item))
                self.assertTrue(document_model.is_in_transaction_state(display_item))
                self.assertTrue(document_model.is_in_transaction_state(data_struct))
                self.assertTrue(document_model.is_in_transaction_state(computed_data_item))
            self.assertEqual(0, document_model.transaction_count)

    def test_connection_to_graphic_puts_data_item_under_transaction(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((20, )))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            interval = Graphics.IntervalGraphic()
            display_item.add_graphic(interval)
            data_struct = document_model.create_data_structure()
            data_struct.set_property_value("x_interval", (0.5, 0.1))
            document_model.append_data_structure(data_struct)
            connection = Connection.PropertyConnection(data_struct, "x_interval", interval, "interval", parent=data_item)
            document_model.append_connection(connection)
            with document_model.item_transaction(data_struct):
                self.assertTrue(document_model.is_in_transaction_state(data_struct))
                self.assertTrue(document_model.is_in_transaction_state(interval))
                self.assertTrue(document_model.is_in_transaction_state(display_item))

    def test_removing_graphic_as_connection_source_results_in_consistent_state(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item1 = DataItem.DataItem(numpy.zeros((20, )))
            data_item2 = DataItem.DataItem(numpy.zeros((20, )))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            display_item1.add_graphic(Graphics.IntervalGraphic())
            display_item2.add_graphic(Graphics.IntervalGraphic())
            graphic1 = display_item1.graphics[0]
            graphic2 = display_item2.graphics[0]
            document_model.append_connection(Connection.PropertyConnection(graphic1, "interval", graphic2, "interval", parent=data_item1))
            display_item1.remove_graphic(graphic1)
            # the document must have a consistent state for item transaction to work
            with document_model.item_transaction(data_item1):
                pass
            with document_model.item_transaction(data_item2):
                pass

    def test_removing_graphic_as_connection_target_results_in_consistent_state(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item1 = DataItem.DataItem(numpy.zeros((20, )))
            data_item2 = DataItem.DataItem(numpy.zeros((20, )))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            display_item1.add_graphic(Graphics.IntervalGraphic())
            display_item2.add_graphic(Graphics.IntervalGraphic())
            graphic1 = display_item1.graphics[0]
            graphic2 = display_item2.graphics[0]
            document_model.append_connection(Connection.PropertyConnection(graphic1, "interval", graphic2, "interval", parent=data_item1))
            display_item1.remove_graphic(graphic2)
            # the document must have a consistent state for item transaction to work
            with document_model.item_transaction(data_item1):
                pass
            with document_model.item_transaction(data_item2):
                pass


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
