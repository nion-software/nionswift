# standard libraries
import contextlib
import copy
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
            self.assertIsNotNone(display_item.used_display_type)

    def test_display_item_snapshot_and_copy_preserve_display_type(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            snapshot_display_item = display_item.snapshot()
            self.assertEqual("line_plot", snapshot_display_item.display_type)
            copy_display_item = copy.deepcopy(display_item)
            self.assertEqual("line_plot", copy_display_item.display_type)

    def test_appending_display_data_channel_does_nothing_if_display_data_channel_already_exists(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
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
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item1 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            document_model.append_data_item(data_item2)
            display_item = document_model.get_display_item_for_data_item(data_item1)
            self.assertEqual(1, len(display_item.display_layers))
            display_item.append_display_data_channel_for_data_item(data_item2)
            self.assertEqual(2, len(display_item.display_data_channels))

    def test_removing_data_item_updates_display_layer_data_indexes(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item1 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            document_model.append_data_item(data_item2)
            display_item = document_model.get_display_item_for_data_item(data_item1)
            display_item.append_display_data_channel_for_data_item(data_item2)
            display_item._set_display_layer_property(0, "ref", "A")
            display_item._set_display_layer_property(1, "ref", "B")
            self.assertEqual(2, len(display_item.display_data_channels))
            self.assertEqual(0, display_item.get_display_layer_property(0, "data_index"))
            self.assertEqual(1, display_item.get_display_layer_property(1, "data_index"))
            document_model.remove_data_item(data_item1)
            self.assertEqual(1, len(display_item.display_layers))
            self.assertEqual(0, display_item.get_display_layer_property(0, "data_index"))
            self.assertEqual("B", display_item.get_display_layer_property(0, "ref"))

    def test_inserting_display_data_channel_updates_display_layer_data_indexes(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
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
            self.assertEqual(0, display_item.get_display_layer_property(0, "data_index"))
            self.assertEqual(1, display_item.get_display_layer_property(1, "data_index"))
            display_item.insert_display_data_channel(1, DisplayItem.DisplayDataChannel(data_item=data_item3))
            self.assertEqual(3, len(display_item.display_data_channels))
            self.assertEqual(0, display_item.get_display_layer_property(0, "data_index"))
            self.assertEqual(2, display_item.get_display_layer_property(1, "data_index"))
            self.assertEqual("A", display_item.get_display_layer_property(0, "ref"))
            self.assertEqual("B", display_item.get_display_layer_property(1, "ref"))

    def test_copy_display_item_should_copy_all_display_data_channels_and_layers(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
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
            self.assertEqual(display_item.display_layers, display_item_copy.display_layers)

    def test_snapshot_display_item_with_data_item_and_multiple_display_layers(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((3, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            display_item.display_layers = [
                {"data_index": 0, "data_row": 2, "label": "Signal"},
                {"data_index": 0, "data_row": 1, "label": "Background"},
                {"data_index": 0, "data_row": 0, "label": "Data"},
            ]
            self.assertEqual(1, len(document_model.display_items))
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(1, len(display_item.data_items))
            self.assertEqual(3, len(display_item.display_layers))
            display_item_copy = document_model.get_display_item_snapshot_new(display_item)
            self.assertEqual(2, len(document_model.display_items))
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(1, len(display_item_copy.data_items))
            self.assertEqual(3, len(display_item_copy.display_layers))
            self.assertEqual(display_item.display_layers, display_item_copy.display_layers)

    def test_add_layer_to_line_plot_with_auto_layer_color_sets_both_colors(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            data_item2 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.remove_display_layer(0)
            self.assertEqual(0, len(display_item.display_layers))
            display_item.append_display_data_channel_for_data_item(data_item2)
            self.assertEqual(2, len(display_item.display_layers))
            self.assertIn("data_index", display_item.display_layers[0])
            self.assertIn("data_index", display_item.display_layers[1])
            self.assertIn("fill_color", display_item.display_layers[0])
            self.assertIn("fill_color", display_item.display_layers[1])

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
