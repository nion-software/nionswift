# standard libraries
import contextlib
import copy
import math
import typing
import unittest

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift import Application
from nion.swift import Facade
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import DynamicString
from nion.swift.model import ImportExportManager
from nion.swift.test import TestContext
from nion.ui import TestUI


Facade.initialize()


def create_memory_profile_context() -> TestContext.MemoryProfileContext:
    return TestContext.MemoryProfileContext()


class TestDisplayItemClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        TestContext.end_leaks(self)

    def test_display_item_with_multiple_display_data_channels_has_sensible_properties(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
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
            self.assertIsNotNone(display_item.project_str)
            self.assertIsNotNone(display_item.used_display_type)

    def test_display_data_channel_disconnects_if_display_item_closed(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item_snapshot = display_item.snapshot()
            self.assertEqual(2, len(data_item.display_data_channels))
            display_item_snapshot.close()
            self.assertEqual(1, len(data_item.display_data_channels))

    def test_display_item_snapshot_and_copy_preserve_display_type(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            with contextlib.closing(display_item.snapshot()) as snapshot_display_item:
                self.assertEqual("line_plot", snapshot_display_item.display_type)
                with contextlib.closing(copy.deepcopy(display_item)) as copy_display_item:
                    self.assertEqual("line_plot", copy_display_item.display_type)

    def test_appending_display_data_channel_does_nothing_if_display_data_channel_already_exists(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item1 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            document_model.append_data_item(data_item2)
            display_item = document_model.get_display_item_for_data_item(data_item1)
            self.assertEqual(1, len(display_item.display_data_channels))
            display_item.append_display_data_channel_for_data_item(data_item2)
            self.assertEqual(2, len(display_item.display_data_channels))
            display_item.append_display_data_channel_for_data_item(data_item2)
            self.assertEqual(2, len(display_item.display_data_channels))

    def test_appending_display_data_channel_adds_layer(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item1 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            document_model.append_data_item(data_item2)
            display_item = document_model.get_display_item_for_data_item(data_item1)
            self.assertEqual(1, len(display_item.display_layers))
            display_item.append_display_data_channel_for_data_item(data_item2)
            self.assertEqual(2, len(display_item.display_data_channels))

    def test_appending_then_removing_display_data_channel_returns_to_original(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item1 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            document_model.append_data_item(data_item2)
            display_item = document_model.get_display_item_for_data_item(data_item1)
            self.assertEqual(1, len(display_item.display_data_channels))
            self.assertEqual(1, len(display_item.display_layers))
            self.assertEqual(data_item1, display_item.display_data_channel.data_item)
            display_data_channel_uuid = display_item.display_data_channel.uuid
            self.assertFalse(display_item.display_properties)
            self.assertEqual(1, len(display_item.display_layers))
            display_item.append_display_data_channel_for_data_item(data_item2)
            self.assertEqual(2, len(display_item.display_data_channels))
            display_item.remove_display_data_channel(display_item.display_data_channels[-1]).close()
            self.assertEqual(1, len(display_item.display_data_channels))
            self.assertEqual(1, len(display_item.display_layers))
            self.assertEqual(data_item1, display_item.display_data_channel.data_item)
            self.assertEqual(display_data_channel_uuid, display_item.display_data_channel.uuid)
            self.assertFalse(display_item.display_properties)

    def test_removing_data_item_updates_display_layer_data_indexes(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item1 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            document_model.append_data_item(data_item2)
            display_item = document_model.get_display_item_for_data_item(data_item1)
            display_item.append_display_data_channel_for_data_item(data_item2)
            display_item._set_display_layer_property(0, "ref", "A")
            display_item._set_display_layer_property(1, "ref", "B")
            self.assertEqual(2, len(display_item.display_data_channels))
            self.assertEqual(display_item.display_data_channels[0], display_item.get_display_layer_display_data_channel(0))
            self.assertEqual(display_item.display_data_channels[1], display_item.get_display_layer_display_data_channel(1))
            document_model.remove_data_item(data_item1)
            self.assertEqual(1, len(display_item.display_layers))
            self.assertEqual(display_item.display_data_channels[0], display_item.get_display_layer_display_data_channel(0))
            self.assertEqual("B", display_item.get_display_layer_property(0, "ref"))

    def test_removing_display_data_channel_updates_display_layer_data_indexes(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item1 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            data_item2 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            data_item3 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            display_item = document_model.get_display_item_for_data_item(data_item1)
            display_item.append_display_data_channel_for_data_item(data_item2)
            display_item.append_display_data_channel_for_data_item(data_item3)
            display_item._set_display_layer_property(0, "ref", "A")
            display_item._set_display_layer_property(1, "ref", "B")
            display_item._set_display_layer_property(2, "ref", "C")
            self.assertEqual(3, len(display_item.display_data_channels))
            self.assertEqual(display_item.display_data_channels[0], display_item.get_display_layer_display_data_channel(0))
            self.assertEqual(display_item.display_data_channels[1], display_item.get_display_layer_display_data_channel(1))
            self.assertEqual(display_item.display_data_channels[2], display_item.get_display_layer_display_data_channel(2))
            display_item.remove_display_data_channel(display_item.display_data_channels[1]).close()
            self.assertEqual(2, len(display_item.display_data_channels))
            self.assertEqual(display_item.display_data_channels[0], display_item.get_display_layer_display_data_channel(0))
            self.assertEqual(display_item.display_data_channels[1], display_item.get_display_layer_display_data_channel(1))
            self.assertEqual("A", display_item.get_display_layer_property(0, "ref"))
            self.assertEqual("C", display_item.get_display_layer_property(1, "ref"))

    def test_removing_display_layer_removes_associated_display_data_channel(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item1 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            data_item2 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            display_item = document_model.get_display_item_for_data_item(data_item1)
            display_item.append_display_data_channel_for_data_item(data_item2)
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            self.assertEqual(2, len(display_item.display_data_channels))
            self.assertEqual(2, len(display_item.display_layers))
            self.assertEqual(display_item.display_data_channels[0], display_item.display_layers[0].display_data_channel)
            self.assertEqual(display_item.display_data_channels[1], display_item.display_layers[1].display_data_channel)
            display_item.remove_display_layer(display_item.display_layers[1]).close()
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            self.assertEqual(1, len(display_item.display_data_channels))
            self.assertEqual(1, len(display_item.display_layers))
            self.assertEqual(display_item.display_data_channels[0], display_item.display_layers[0].display_data_channel)

    def test_removing_display_layer_removes_associated_display_data_channel_only_if_no_other_references(self):
        with TestContext.create_memory_context() as test_context:
            with TestContext.create_memory_context() as test_context:
                document_model = test_context.create_document_model()
                data_item1 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
                data_item2 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
                document_model.append_data_item(data_item1)
                document_model.append_data_item(data_item2)
                display_item = document_model.get_display_item_for_data_item(data_item1)
                display_item.append_display_data_channel_for_data_item(data_item2)
                display_item._add_display_layer_for_data_item(data_item2)
                self.assertEqual(2, len(document_model.data_items))
                self.assertEqual(2, len(document_model.display_items))
                self.assertEqual(2, len(display_item.display_data_channels))
                self.assertEqual(3, len(display_item.display_layers))
                self.assertEqual(display_item.display_data_channels[0], display_item.display_layers[0].display_data_channel)
                self.assertEqual(display_item.display_data_channels[1], display_item.display_layers[1].display_data_channel)
                self.assertEqual(display_item.display_data_channels[1], display_item.display_layers[2].display_data_channel)
                display_item.remove_display_layer(display_item.display_layers[2]).close()
                self.assertEqual(2, len(document_model.data_items))
                self.assertEqual(2, len(document_model.display_items))
                self.assertEqual(2, len(display_item.display_data_channels))
                self.assertEqual(2, len(display_item.display_layers))
                self.assertEqual(display_item.display_data_channels[0], display_item.display_layers[0].display_data_channel)
                self.assertEqual(display_item.display_data_channels[1], display_item.display_layers[1].display_data_channel)

    def test_inserting_display_data_channel_updates_display_layer_data_indexes(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item1 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            document_model.append_data_item(data_item2)
            data_item3 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            document_model.append_data_item(data_item3)
            display_item = document_model.get_display_item_for_data_item(data_item1)
            display_item.append_display_data_channel_for_data_item(data_item2)
            display_item._set_display_layer_property(0, "ref", "A")
            display_item._set_display_layer_property(1, "ref", "B")
            self.assertEqual(2, len(display_item.display_data_channels))
            self.assertEqual(display_item.display_data_channels[0], display_item.get_display_layer_display_data_channel(0))
            self.assertEqual(display_item.display_data_channels[1], display_item.get_display_layer_display_data_channel(1))
            display_item.insert_display_data_channel(1, DisplayItem.DisplayDataChannel(data_item=data_item3))
            self.assertEqual(3, len(display_item.display_data_channels))
            self.assertEqual(display_item.display_data_channels[0], display_item.get_display_layer_display_data_channel(0))
            self.assertEqual(display_item.display_data_channels[2], display_item.get_display_layer_display_data_channel(1))
            self.assertEqual("A", display_item.get_display_layer_property(0, "ref"))
            self.assertEqual("B", display_item.get_display_layer_property(1, "ref"))

    def test_copy_display_item_should_copy_all_display_data_channels_and_layers(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            data_item2 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2, False)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.append_display_data_channel_for_data_item(data_item2)
            self.assertEqual(1, len(document_model.display_items))
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(display_item.data_items))
            self.assertEqual(2, len(display_item.display_layers))
            display_item_copy = document_model.get_display_item_copy_new(display_item)
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            self.assertEqual(2, len(display_item_copy.data_items))
            self.assertEqual(2, len(display_item_copy.display_layers))
            self.assertTrue(display_item.display_layers_match(display_item_copy))

    def test_snapshot_display_item_with_data_item_and_multiple_display_layers(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((3, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            display_item.move_display_layer_backward(1)  # 0 1 2 -> 0 2 1
            display_item.move_display_layer_backward(0)  # 0 2 1 -> 2 0 1
            display_item.move_display_layer_backward(1)  # 2 0 1 -> 2 1 0
            self.assertEqual(1, len(document_model.display_items))
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(1, len(display_item.data_items))
            self.assertEqual(3, len(display_item.display_layers))
            display_item_copy = document_model.get_display_item_snapshot_new(display_item)
            self.assertEqual(2, len(document_model.display_items))
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(1, len(display_item_copy.data_items))
            self.assertEqual(3, len(display_item_copy.display_layers))
            self.assertTrue(display_item.display_layers_match(display_item_copy))

    def test_add_layer_to_line_plot_with_auto_layer_color_sets_both_colors(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            data_item2 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            display_item = document_model.get_display_item_for_data_item(data_item)
            self.assertEqual(1, len(display_item.display_layers))
            display_item.append_display_data_channel_for_data_item(data_item2, {"stroke_color": "#000"})
            self.assertEqual(2, len(display_item.display_layers))
            self.assertIsNotNone(display_item.get_display_layer_display_data_channel(0))
            self.assertIsNotNone(display_item.get_display_layer_display_data_channel(1))
            self.assertIsNotNone(display_item.get_display_layer_property(0, "fill_color"))
            self.assertIsNotNone(display_item.get_display_layer_property(1, "stroke_color"))
            self.assertIsNone(display_item.get_display_layer_property(1, "fill_color"))

    def test_second_layer_to_line_plot_enables_caption(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            data_item2 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            data_item3 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            display_item = document_model.get_display_item_for_data_item(data_item)
            self.assertIsNone(display_item.get_display_property("legend_position"))
            # check that legend is automatically enabled for 2nd layer
            display_item.append_display_data_channel_for_data_item(data_item2)
            self.assertEqual("top-right", display_item.get_display_property("legend_position"))
            # check that legend is not automatically enabled for 3rd layer
            display_item.set_display_property("legend_position", None)
            display_item.append_display_data_channel_for_data_item(data_item3)
            self.assertIsNone(display_item.get_display_property("legend_position"))

    def test_closing_display_does_not_trigger_computation_binding(self):
        # this tests to make sure that items involving filters are closed properly.
        # notifications should not be sent during closing, otherwise the computation
        # will try to update its dependencies using the item being destructed.
        # this test only failed in that it printed a stack trace.
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            fft_data_item = document_model.get_fft_new(display_item, display_item.data_item)
            document_model.recompute_all()
            fft_display_item = document_model.get_display_item_for_data_item(fft_data_item)
            document_model.get_fourier_filter_new(fft_display_item, fft_data_item)
            document_model.recompute_all()

    def test_build_table_with_calibrated_1d_data(self):
        with TestContext.create_memory_context() as test_context:
            calibration = Calibration.Calibration(1.0, 2.0, "nm")
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.array([1.1, 1.2, 1.3, 1.4]))
            data_item.set_dimensional_calibration(0, calibration)
            data_item.set_intensity_calibration(Calibration.Calibration(0, 1, "e"))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item._set_display_layer_property(0, "label", "W")
            headers, data = ImportExportManager.build_table(display_item)
            self.assertEqual(2, len(headers))
            self.assertEqual(2, len(data))
            self.assertEqual("X (nm)", headers[0])
            self.assertEqual("W (e)", headers[1])
            self.assertTrue(numpy.array_equal(calibration.convert_to_calibrated_value(numpy.arange(0, data_item.data.shape[0])), data[0]))
            self.assertTrue(numpy.array_equal(data_item.data, data[1]))

    def test_build_table_with_two_display_layers_of_same_calibrated_1d_data(self):
        with TestContext.create_memory_context() as test_context:
            calibration = Calibration.Calibration(1.0, 2.0, "nm")
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.array([1.1, 1.2, 1.3, 1.4]))
            data_item.set_dimensional_calibration(0, calibration)
            data_item.set_intensity_calibration(Calibration.Calibration(0, 1, "e"))
            data_item2 = DataItem.DataItem(numpy.array([2.1, 2.2, 2.3, 2.4]))
            data_item2.set_dimensional_calibration(0, calibration)
            data_item2.set_intensity_calibration(Calibration.Calibration(0, 1, "e"))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.append_display_data_channel_for_data_item(data_item2)
            display_item._set_display_layer_property(0, "label", "W")
            display_item._set_display_layer_property(1, "label", "T")
            headers, data = ImportExportManager.build_table(display_item)
            self.assertEqual(3, len(headers))
            self.assertEqual(3, len(data))
            self.assertEqual("X (nm)", headers[0])
            self.assertEqual("W (e)", headers[1])
            self.assertEqual("T (e)", headers[2])
            self.assertTrue(numpy.array_equal(calibration.convert_to_calibrated_value(numpy.arange(0, data_item.data.shape[0])), data[0]))
            self.assertTrue(numpy.array_equal(data_item.data, data[1]))
            self.assertTrue(numpy.array_equal(data_item2.data, data[2]))

    def test_build_table_with_two_display_layers_of_different_calibrated_1d_data(self):
        with TestContext.create_memory_context() as test_context:
            calibration = Calibration.Calibration(1.0, 2.0, "nm")
            calibration2 = Calibration.Calibration(1.5, 2.5, "nm")
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.array([1.1, 1.2, 1.3, 1.4]))
            data_item.set_dimensional_calibration(0, calibration)
            data_item.set_intensity_calibration(Calibration.Calibration(0, 1, "e"))
            data_item2 = DataItem.DataItem(numpy.array([2.1, 2.2, 2.3, 2.4]))
            data_item2.set_dimensional_calibration(0, calibration2)
            data_item2.set_intensity_calibration(Calibration.Calibration(0, 1, "e"))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.append_display_data_channel_for_data_item(data_item2)
            display_item._set_display_layer_property(0, "label", "W")
            display_item._set_display_layer_property(1, "label", "T")
            headers, data = ImportExportManager.build_table(display_item)
            self.assertEqual(4, len(headers))
            self.assertEqual(4, len(data))
            self.assertEqual("X W (nm)", headers[0])
            self.assertEqual("Y W (e)", headers[1])
            self.assertEqual("X T (nm)", headers[2])
            self.assertEqual("Y T (e)", headers[3])
            self.assertTrue(numpy.array_equal(calibration.convert_to_calibrated_value(numpy.arange(0, data_item.data.shape[0])), data[0]))
            self.assertTrue(numpy.array_equal(data_item.data, data[1]))
            self.assertTrue(numpy.array_equal(calibration2.convert_to_calibrated_value(numpy.arange(0, data_item.data.shape[0])), data[2]))
            self.assertTrue(numpy.array_equal(data_item2.data, data[3]))

    def test_display_layer_property_changed(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, )))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_layer = typing.cast(DisplayItem.DisplayLayer, display_item.display_layers[0])
            property_did_change = False
            def property_changed(name: str) -> None:
                nonlocal property_did_change
                property_did_change = True
            with contextlib.closing(display_layer.property_changed_event.listen(property_changed)):
                display_layer.fill_color = "red"
            self.assertTrue(property_did_change)

    def test_display_layer_property_reloads_after_change(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                data_item = DataItem.DataItem(numpy.zeros((8,)))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                display_layer = typing.cast(DisplayItem.DisplayLayer, display_item.display_layers[0])
                display_layer.fill_color = "red"
                display_item.title = "red"
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                data_item = document_model.data_items[0]
                display_item = document_model.get_display_item_for_data_item(data_item)
                display_layer = typing.cast(DisplayItem.DisplayLayer, display_item.display_layers[0])
                self.assertEqual("red", display_layer.fill_color)
                display_layer.fill_color = "blue"  # should be able to set value after reload. failed once.

    def test_display_layer_property_reloads_with_no_display_data_channel(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                data_item = DataItem.DataItem(numpy.zeros((8,)))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                display_layer = typing.cast(DisplayItem.DisplayLayer, display_item.display_layers[0])
                display_layer.display_data_channel = None
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                data_item = document_model.data_items[0]
                display_item = document_model.get_display_item_for_data_item(data_item)
                display_layer = typing.cast(DisplayItem.DisplayLayer, display_item.display_layers[0])
                self.assertIsNone(display_layer.display_data_channel)

    def test_display_layers_reload_after_inserting_and_removing(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                data_item = DataItem.DataItem(numpy.zeros((8,)))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                # add a new layer
                display_item.add_display_layer_for_display_data_channel(display_item.display_data_channels[0])
                self.assertEqual(2, len(display_item.display_layers))
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                data_item = document_model.data_items[0]
                display_item = document_model.get_display_item_for_data_item(data_item)
                self.assertEqual(2, len(display_item.display_layers))
                # now remove a layer
                display_item.remove_display_layer(display_item.display_layers[1]).close()
                self.assertEqual(1, len(display_item.display_layers))
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                data_item = document_model.data_items[0]
                display_item = document_model.get_display_item_for_data_item(data_item)
                self.assertEqual(1, len(display_item.display_layers))

    def test_displayed_title_is_inherited_from_source(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                data_item = DataItem.DataItem(numpy.zeros((8,)))
                data_item.title = "red"
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                data_item2 = document_model.get_invert_new(display_item, display_item.data_item)
                display_item2 = document_model.get_display_item_for_data_item(data_item2)
                data_item3 = document_model.get_invert_new(display_item2, display_item2.data_item)
                display_item3 = document_model.get_display_item_for_data_item(data_item3)
                document_model.recompute_all()
                self.assertEqual("red", display_item.displayed_title)
                self.assertEqual("red (Negate)", display_item2.displayed_title)
                self.assertEqual("red (Negate) (Negate)", display_item3.displayed_title)
                data_item.title = "green"
                self.assertEqual("green", display_item.displayed_title)
                self.assertEqual("green (Negate)", display_item2.displayed_title)
                self.assertEqual("green (Negate) (Negate)", display_item3.displayed_title)

    def test_display_item_handles_invalid_calibration(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.new_data_item(DataAndMetadata.new_data_and_metadata(numpy.zeros((8,)), dimensional_calibrations=[Calibration.Calibration(0.0, -math.inf, "x")]))
            document_model.append_data_item(data_item)

    def test_displayed_title_shows_dynamic_title_or_title_if_set(self):
        # requirement: dynamic_titles
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                data_item = DataItem.DataItem(numpy.zeros((8,)))
                data_item.dynamic_title = DynamicString._TestDynamicString()
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                self.assertEqual("green", display_item.displayed_title)
                data_item.title = "red"
                self.assertEqual("red", display_item.displayed_title)
                data_item.title = str()
                self.assertEqual("green", display_item.displayed_title)
                data_item.dynamic_title = DynamicString._TestDynamicString()

    def test_dynamic_title_enabled_when_setting_dynamic_title_and_disabled_when_setting_title_directly(self):
        # requirement: dynamic_titles
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                data_item = DataItem.DataItem(numpy.zeros((8,)))
                data_item.dynamic_title = DynamicString._TestDynamicString()
                self.assertTrue(data_item.dynamic_title_enabled)
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                self.assertEqual("green", display_item.displayed_title)
                data_item.title = "red"
                self.assertFalse(data_item.dynamic_title_enabled)
                self.assertEqual("red", display_item.displayed_title)
                data_item.dynamic_title = DynamicString._TestDynamicString()
                self.assertTrue(data_item.dynamic_title_enabled)

    def test_dynamic_title_updates_title_only_if_dynamic_title_is_enabled_and_updates_when_re_enabled(self):
        # requirement: dynamic_titles
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                data_item = DataItem.DataItem(numpy.zeros((8,)))
                data_item.dynamic_title = DynamicString._TestDynamicString()
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                self.assertEqual("green", display_item.displayed_title)
                data_item.dynamic_title.string_stream.value = "blue"
                self.assertEqual("blue", display_item.displayed_title)
                data_item.dynamic_title_enabled = False
                data_item.dynamic_title.string_stream.value = "purple"
                self.assertEqual("blue", display_item.displayed_title)
                data_item.dynamic_title_enabled = True
                self.assertEqual("purple", display_item.displayed_title)

    def test_displayed_title_shows_source_title_with_suffix_if_not_specified(self):
        # requirement: dynamic_titles
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                data_item = DataItem.DataItem(numpy.zeros((8,)))
                data_item.dynamic_title = DynamicString._TestDynamicString()
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                data_item2 = document_model.get_invert_new(display_item, display_item.data_item)
                display_item2 = document_model.get_display_item_for_data_item(data_item2)
                self.assertEqual("green (Negate)", display_item2.displayed_title)
                data_item2.title = "blue"
                self.assertEqual("blue", display_item2.displayed_title)
                data_item2.title = None
                self.assertEqual("green (Negate)", display_item2.displayed_title)
                display_item2.title = "yellow"
                self.assertEqual("yellow", display_item2.displayed_title)
                display_item2.title = None
                self.assertEqual("green (Negate)", display_item2.displayed_title)

    def test_placeholder_title_ignores_specified_data_item_or_display_item_titles(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                data_item = DataItem.DataItem(numpy.zeros((8,)))
                data_item.title = "green"
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                data_item2 = document_model.get_invert_new(display_item, display_item.data_item)
                display_item2 = document_model.get_display_item_for_data_item(data_item2)
                self.assertEqual("green (Negate)", display_item2.placeholder_title)
                data_item2.title = "blue"
                self.assertEqual("green (Negate)", display_item2.placeholder_title)
                data_item2.title = None
                self.assertEqual("green (Negate)", display_item2.placeholder_title)
                display_item2.title = "yellow"
                self.assertEqual("green (Negate)", display_item2.placeholder_title)
                display_item2.title = None
                self.assertEqual("green (Negate)", display_item2.placeholder_title)

    # test_transaction_does_not_cascade_to_data_item_refs
    # test_increment_data_ref_counts_cascades_to_data_item_refs
    # test_adding_data_item_twice_to_composite_item_fails
    # test_composition_item_starts_drag_with_composition_item_mime_data
    # test_composite_library_item_produces_composite_display
    # test_changing_display_type_of_composite_updates_displays_in_canvas_item
    # test_changing_display_type_of_child_updates_composite_display
    # test_composite_item_deletes_cleanly_when_displayed
    # test_delete_composite_cascade_delete_works
    # test_creating_r_var_on_composite_item
    # test_creating_r_var_on_library_items
    # test_transaction_on_composite_display_propagates_to_dependents
    # test_composite_item_deletes_children_when_deleted
    # test_undelete_composite_item
    # test_composite_line_plot_initializes_properly
    # test_composite_line_plot_calculates_calibrated_data_of_two_data_items_with_same_units_but_different_scales_properly
    # test_composite_line_plot_handles_drawing_with_fixed_y_scale_and_without_data
    # test_composite_line_plot_handles_first_components_without_data
    # test_multi_line_plot_without_calibration_does_not_display_any_line_graphs
    # test_multi_line_plot_handles_calibrated_vs_uncalibrated_display
    # test_delete_and_undelete_from_memory_storage_system_restores_composite_item_after_reload
    # test_data_item_with_references_to_another_data_item_reloads
    # test_composite_library_item_reloads_metadata
    # test_composite_data_item_saves_to_file_storage
    # test_composition_display_thumbnail_source_produces_library_item_mime_data


if __name__ == '__main__':
    unittest.main()
