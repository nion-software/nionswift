# standard libraries
import contextlib
import gc
import logging
import unittest
import weakref

# third party libraries
import numpy

# local libraries
from nion.data import DataAndMetadata
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift import DisplayPanel
from nion.swift import Facade
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.ui import TestUI


Facade.initialize()


def construct_test_document(app, workspace_id=None):
    document_model = DocumentModel.DocumentModel()
    document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id=workspace_id)
    data_group1 = DataGroup.DataGroup()
    document_model.append_data_group(data_group1)
    data_item1a = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
    document_model.append_data_item(data_item1a)
    data_group1.append_data_item(data_item1a)
    data_item1b = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
    document_model.append_data_item(data_item1b)
    data_group1.append_data_item(data_item1b)
    data_group1a = DataGroup.DataGroup()
    data_group1.append_data_group(data_group1a)
    data_group1b = DataGroup.DataGroup()
    data_group1.append_data_group(data_group1b)
    data_group2 = DataGroup.DataGroup()
    document_controller.document_model.append_data_group(data_group2)
    data_group2a = DataGroup.DataGroup()
    data_group2.append_data_group(data_group2a)
    data_group2b = DataGroup.DataGroup()
    data_group2.append_data_group(data_group2b)
    data_group2b1 = DataGroup.DataGroup()
    data_group2b.append_data_group(data_group2b1)
    data_item2b1a = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
    document_model.append_data_item(data_item2b1a)
    data_group2b1.append_data_item(data_item2b1a)
    return document_controller

class TestDocumentControllerClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_delete_document_controller(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model)
        document_model = None
        weak_document_model = weakref.ref(document_controller.document_model)
        weak_document_window = weakref.ref(document_controller._document_window)
        weak_document_controller = weakref.ref(document_controller)
        self.assertIsNotNone(weak_document_controller())
        self.assertIsNotNone(weak_document_window())
        self.assertIsNotNone(weak_document_model())
        document_controller.request_close()
        document_controller = None
        self.assertIsNone(weak_document_controller())
        self.assertIsNone(weak_document_window())
        self.assertIsNone(weak_document_model())

    def test_document_controller_releases_document_model(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        document_model.append_data_item(data_item)
        weak_document_model = weakref.ref(document_model)
        document_controller.close()
        document_controller = None
        data_item = None
        document_model = None
        gc.collect()
        self.assertIsNone(weak_document_model())

    def test_document_controller_releases_workspace_controller(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        document_model.append_data_item(data_item)
        weak_workspace_controller = weakref.ref(document_controller.workspace_controller)
        document_controller.close()
        document_controller = None
        data_item = None
        document_model = None
        gc.collect()
        self.assertIsNone(weak_workspace_controller())

    def test_document_controller_releases_data_item(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        document_model.append_data_item(data_item)
        weak_data_item = weakref.ref(data_item)
        document_controller.close()
        document_controller = None
        data_item = None
        document_model = None
        gc.collect()
        self.assertIsNone(weak_data_item())

    def test_display_panel_releases_data_item(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        document_model.append_data_item(data_item)
        weak_data_item = weakref.ref(data_item)
        display_panel = DisplayPanel.DisplayPanel(document_controller, dict())
        display_panel.set_display_panel_data_item(data_item)
        self.assertIsNotNone(weak_data_item())
        display_panel.close()
        document_controller.close()
        document_controller = None
        data_item = None
        document_model = None
        display_panel = None
        gc.collect()
        self.assertIsNone(weak_data_item())

    def test_document_controller_releases_itself(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        weak_document_controller = weakref.ref(document_controller)
        document_model.append_data_item(DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32)))
        document_controller.periodic()
        document_controller.close()
        document_controller = None
        gc.collect()
        self.assertIsNone(weak_document_controller())

    def test_flat_data_groups(self):
        document_controller = construct_test_document(self.app)
        with contextlib.closing(document_controller):
            self.assertEqual(len(list(document_controller.document_model.get_flat_data_group_generator())), 7)
            self.assertEqual(len(list(document_controller.document_model.get_flat_data_item_generator())), 3)
            self.assertEqual(document_controller.document_model.get_data_item_by_key(0), document_controller.document_model.data_groups[0].data_items[0])
            self.assertEqual(document_controller.document_model.get_data_item_by_key(1), document_controller.document_model.data_groups[0].data_items[1])
            self.assertEqual(document_controller.document_model.get_data_item_by_key(2), document_controller.document_model.data_groups[1].data_groups[1].data_groups[0].data_items[0])

    def test_receive_files_should_put_files_into_document_model_at_end(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item1.title = "data_item1"
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2.title = "data_item2"
            document_model.append_data_item(data_item2)
            data_item3 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item3.title = "data_item3"
            document_model.append_data_item(data_item3)
            new_data_items = document_controller.receive_files([":/app/scroll_gem.png"], threaded=False)
            self.assertEqual(document_model.data_items.index(new_data_items[0]), 3)

    def test_receive_files_should_put_files_into_document_model_at_index(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item1.title = "data_item1"
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2.title = "data_item2"
            document_model.append_data_item(data_item2)
            data_item3 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item3.title = "data_item3"
            document_model.append_data_item(data_item3)
            new_data_items = document_controller.receive_files([":/app/scroll_gem.png"], index=2, threaded=False)
            self.assertEqual(document_model.data_items.index(new_data_items[0]), 2)

    def test_receive_files_should_put_files_into_data_group_at_index(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_group = DataGroup.DataGroup()
            document_model.append_data_group(data_group)
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item1.title = "data_item1"
            document_model.append_data_item(data_item1)
            data_group.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2.title = "data_item2"
            document_model.append_data_item(data_item2)
            data_group.append_data_item(data_item2)
            data_item3 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item3.title = "data_item3"
            document_model.append_data_item(data_item3)
            data_group.append_data_item(data_item3)
            new_data_items = document_controller.receive_files([":/app/scroll_gem.png"], data_group=data_group, index=2, threaded=False)
            self.assertEqual(document_model.data_items.index(new_data_items[0]), 3)
            self.assertEqual(data_group.data_items.index(new_data_items[0]), 2)

    def test_remove_graphic_removes_it_from_data_item(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        document_model.append_data_item(data_item)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        display_panel = document_controller.selected_display_panel
        display_panel.set_display_panel_data_item(data_item)
        line_graphic = document_controller.add_line_graphic()
        # make sure assumptions are correct
        self.assertEqual(len(display_specifier.display.graphic_selection.indexes), 1)
        self.assertTrue(0 in display_specifier.display.graphic_selection.indexes)
        self.assertEqual(len(display_specifier.display.graphics), 1)
        self.assertEqual(display_specifier.display.graphics[0], line_graphic)
        # remove the graphic and make sure things are as expected
        display_panel.set_display_panel_data_item(data_item)
        document_controller.remove_selected_graphics()
        self.assertEqual(len(display_specifier.display.graphic_selection.indexes), 0)
        self.assertEqual(len(display_specifier.display.graphics), 0)
        # clean up
        document_controller.close()

    def test_remove_line_profile_does_not_remove_data_item_itself(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        document_model.append_data_item(data_item)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        display_panel = document_controller.selected_display_panel
        display_panel.set_display_panel_data_item(data_item)
        line_profile_data_item = document_controller.processing_line_profile().data_item
        document_controller.periodic()  # TODO: remove need to let the inspector catch up
        display_panel.set_display_panel_data_item(data_item)
        display_specifier.display.graphic_selection.clear()
        display_specifier.display.graphic_selection.add(0)
        # make sure assumptions are correct
        self.assertEqual(document_model.get_source_data_items(line_profile_data_item)[0], data_item)
        self.assertTrue(line_profile_data_item in document_model.data_items)
        self.assertTrue(data_item in document_model.data_items)
        # remove the graphic and make sure things are as expected
        display_panel.set_display_panel_data_item(data_item)
        document_controller.remove_selected_graphics()
        self.assertTrue(data_item in document_model.data_items)
        # clean up
        document_controller.close()

    def test_remove_line_profile_removes_associated_child_data_item(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            # add a data item
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display = DataItem.DisplaySpecifier.from_data_item(data_item).display
            # ensure first data item is displayed
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(data_item)
            # make a line profile
            line_profile_data_item = document_controller.processing_line_profile().data_item
            # set up the selection
            display.graphic_selection.clear()
            display.graphic_selection.add(0)
            # make sure assumptions are correct
            self.assertEqual(document_model.get_source_data_items(line_profile_data_item)[0], data_item)
            self.assertTrue(line_profile_data_item in document_model.data_items)
            # ensure data item is selected, then remove the graphic
            display_panel.set_display_panel_data_item(data_item)
            document_controller.remove_selected_graphics()
            self.assertEqual(0, len(display.graphics))
            self.assertEqual(0, len(display.graphic_selection.indexes))  # disabled until test_remove_line_profile_updates_graphic_selection
            self.assertFalse(line_profile_data_item in document_model.data_items)

    def test_document_model_closed_only_after_all_document_controllers_closed(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        document_model.append_data_item(data_item)
        document_controller1 = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        document_controller2 = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with data_item.data_item_changes():
            pass  # triggers usage of 'processors' which gets set to null when closed
        document_controller1.close()
        with data_item.data_item_changes():
            pass  # triggers usage of 'processors' which gets set to null when closed
        document_controller2.close()  # this would fail even if processors part didn't fail

    def test_processing_on_crop_region_constructs_composite_operation(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        h, w = 8, 8
        data_item = DataItem.DataItem(numpy.ones((h, w), numpy.float32))
        crop_region = Graphics.RectangleGraphic()
        crop_region.bounds = ((0.25, 0.25), (0.5, 0.5))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display_specifier.display.add_graphic(crop_region)
        document_model.append_data_item(data_item)
        display_panel = document_controller.selected_display_panel
        display_panel.set_display_panel_data_item(data_item)
        new_data_item = document_model.get_invert_new(data_item, crop_region)
        document_model.recompute_all()
        self.assertEqual(new_data_item.data_shape, (h//2, w//2))
        self.assertEqual(new_data_item.data_dtype, data_item.data_dtype)
        self.assertAlmostEqual(new_data_item.data[h//4, w//4], -1.0)
        document_controller.close()

    def test_processing_on_crop_region_connects_region_to_operation(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
        crop_region = Graphics.RectangleGraphic()
        crop_region.bounds = ((0.25, 0.25), (0.5, 0.5))
        DataItem.DisplaySpecifier.from_data_item(data_item).display.add_graphic(crop_region)
        document_model.append_data_item(data_item)
        new_data_item = document_model.get_invert_new(data_item, crop_region)
        self.assertEqual(crop_region.bounds, document_model.resolve_object_specifier(document_model.get_data_item_computation(new_data_item).variables[0].secondary_specifier).value.bounds)
        crop_region.bounds = ((0.3, 0.4), (0.25, 0.35))
        self.assertEqual(crop_region.bounds, document_model.resolve_object_specifier(document_model.get_data_item_computation(new_data_item).variables[0].secondary_specifier).value.bounds)
        document_controller.close()

    def test_processing_on_crop_region_recomputes_when_bounds_changes(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
        crop_region = Graphics.RectangleGraphic()
        crop_region.bounds = ((0.25, 0.25), (0.5, 0.5))
        DataItem.DisplaySpecifier.from_data_item(data_item).display.add_graphic(crop_region)
        document_model.append_data_item(data_item)
        cropped_data_item = document_model.get_invert_new(data_item, crop_region)
        document_model.recompute_all()
        self.assertFalse(document_model.get_data_item_computation(cropped_data_item).needs_update)
        crop_region.bounds = ((0.3, 0.4), (0.25, 0.35))
        self.assertTrue(document_model.get_data_item_computation(cropped_data_item).needs_update)
        document_controller.close()

    def test_creating_with_variable_produces_valid_computation(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data = ((numpy.random.randn(2, 2) + 1) * 10).astype(numpy.int32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            data_item_r = document_model.assign_variable_to_library_item(data_item)
            computed_data_item = document_controller.processing_computation("target.xdata = {0}.xdata * 2".format(data_item_r))
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, data*2))

    def test_extra_variables_in_computation_get_purged(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data = ((numpy.random.randn(2, 2) + 1) * 10).astype(numpy.int32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            data_item2 = DataItem.DataItem(numpy.copy(data))
            document_model.append_data_item(data_item2)
            data_item3 = DataItem.DataItem(numpy.copy(data))
            document_model.append_data_item(data_item3)
            data_item_r = document_model.assign_variable_to_library_item(data_item)
            data_item_r2 = document_model.assign_variable_to_library_item(data_item2)
            document_model.assign_variable_to_library_item(data_item3)
            computed_data_item = document_controller.processing_computation("target.xdata = {0}.xdata * 2 + {1}.xdata".format(data_item_r, data_item_r2))
            self.assertEqual(len(document_model.get_data_item_computation(computed_data_item).variables), 2)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, data*2 + data))

    def test_deleting_processed_data_item_and_then_recomputing_works(self):
        # processed data item should be removed from recomputing queue
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
        crop_region = Graphics.RectangleGraphic()
        crop_region.bounds = ((0.25, 0.25), (0.5, 0.5))
        DataItem.DisplaySpecifier.from_data_item(data_item).display.add_graphic(crop_region)
        document_model.append_data_item(data_item)
        display_panel = document_controller.selected_display_panel
        display_panel.set_display_panel_data_item(data_item)
        data_item_result = document_model.get_invert_new(data_item, crop_region)
        document_model.remove_data_item(data_item_result)
        document_model.recompute_all()
        document_controller.close()

    def test_delete_source_region_of_computation_deletes_target_data_item(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            source_data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            target_data_item = document_model.get_line_profile_new(source_data_item, None)
            display = DataItem.DisplaySpecifier.from_data_item(source_data_item).display
            self.assertIn(target_data_item, document_model.data_items)
            display.remove_graphic(display.graphics[0])
            self.assertNotIn(target_data_item, document_model.data_items)

    def test_delete_source_data_item_of_computation_deletes_target_data_item(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            source_data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            target_data_item = document_model.get_line_profile_new(source_data_item, None)
            self.assertIn(target_data_item, document_model.data_items)
            document_model.remove_data_item(source_data_item)
            self.assertNotIn(target_data_item, document_model.data_items)

    def test_delete_target_data_item_of_computation_deletes_source_region(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            source_data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            target_data_item = document_model.get_line_profile_new(source_data_item, None)
            display = DataItem.DisplaySpecifier.from_data_item(source_data_item).display
            self.assertIn(target_data_item, document_model.data_items)
            self.assertEqual(len(display.graphics), 1)
            document_model.remove_data_item(target_data_item)
            self.assertEqual(len(display.graphics), 0)
            self.assertNotIn(target_data_item, document_model.data_items)

    def test_delete_data_item_with_source_region_also_cascade_deletes_target(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            source_data_item = DataItem.DataItem(numpy.ones((8, 8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            intermediate_data_item = document_model.get_pick_region_new(source_data_item)
            intermediate_display = intermediate_data_item.displays[0]
            interval_region = Graphics.IntervalGraphic()
            intermediate_display.add_graphic(interval_region)
            target_data_item = document_model.get_invert_new(source_data_item)
            target_computation = document_model.get_data_item_computation(target_data_item)
            target_computation.create_object("interval", document_model.get_object_specifier(interval_region), label="I")
            self.assertIn(source_data_item, document_model.data_items)
            self.assertIn(intermediate_data_item, document_model.data_items)
            self.assertIn(target_data_item, document_model.data_items)
            document_model.remove_data_item(intermediate_data_item)  # this will cascade delete target
            self.assertIn(source_data_item, document_model.data_items)
            self.assertNotIn(intermediate_data_item, document_model.data_items)
            self.assertNotIn(target_data_item, document_model.data_items)

    def test_delete_graphic_with_sibling_and_data_item_dependent_on_both_also_cascade_deletes_target(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            source_data_item = DataItem.DataItem(numpy.ones((8, 8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            intermediate_data_item = document_model.get_pick_region_new(source_data_item)
            intermediate_display = intermediate_data_item.displays[0]
            interval_region1 = Graphics.IntervalGraphic()
            intermediate_display.add_graphic(interval_region1)
            interval_region2 = Graphics.IntervalGraphic()
            intermediate_display.add_graphic(interval_region2)
            target_data_item = document_model.get_invert_new(source_data_item)
            target_computation = document_model.get_data_item_computation(target_data_item)
            target_computation.create_object("interval1", document_model.get_object_specifier(interval_region1), label="I")
            target_computation.create_object("interval2", document_model.get_object_specifier(interval_region2), label="I")
            self.assertIn(source_data_item, document_model.data_items)
            self.assertIn(intermediate_data_item, document_model.data_items)
            self.assertIn(target_data_item, document_model.data_items)
            intermediate_display.remove_graphic(interval_region2)  # this will cascade delete target and then interval_region1
            self.assertIn(source_data_item, document_model.data_items)
            self.assertIn(intermediate_data_item, document_model.data_items)
            self.assertNotIn(target_data_item, document_model.data_items)
            self.assertNotIn(interval_region1, intermediate_display.graphics)
            self.assertNotIn(interval_region2, intermediate_display.graphics)

    def test_delete_composite_cascade_delete_works(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            composite_item = DataItem.CompositeLibraryItem()
            document_model.append_data_item(composite_item)
            composite_item.append_data_item(data_item)
            document_model.remove_data_item(composite_item)

    def test_delete_graphic_with_two_dependencies_deletes_both_dependencies(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            source_data_item = DataItem.DataItem(numpy.ones((8, 8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            crop_region = Graphics.RectangleGraphic()
            source_data_item.displays[0].add_graphic(crop_region)
            target_data_item1 = document_model.get_invert_new(source_data_item, crop_region)
            target_data_item2 = document_model.get_invert_new(source_data_item, crop_region)
            self.assertIn(target_data_item1, document_model.data_items)
            self.assertIn(target_data_item2, document_model.data_items)
            source_data_item.displays[0].remove_graphic(crop_region)
            self.assertNotIn(target_data_item1, document_model.data_items)
            self.assertNotIn(target_data_item2, document_model.data_items)

    def test_delete_target_data_item_with_source_region_with_another_target_does_not_delete_source_region(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            source_data_item = DataItem.DataItem(numpy.ones((8, 8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            crop_region = Graphics.RectangleGraphic()
            source_data_item.displays[0].add_graphic(crop_region)
            target_data_item1 = document_model.get_invert_new(source_data_item, crop_region)
            target_data_item2 = document_model.get_invert_new(source_data_item, crop_region)
            self.assertIn(target_data_item1, document_model.data_items)
            self.assertIn(target_data_item2, document_model.data_items)
            # removing one of two targets should not delete the other target
            document_model.remove_data_item(target_data_item1)
            self.assertNotIn(target_data_item1, document_model.data_items)
            self.assertIn(target_data_item2, document_model.data_items)
            self.assertIn(crop_region, source_data_item.displays[0].graphics)
            # but removing the last target should delete both the target and the source graphic
            document_model.remove_data_item(target_data_item2)
            self.assertNotIn(target_data_item2, document_model.data_items)
            self.assertNotIn(crop_region, source_data_item.displays[0].graphics)

    def test_crop_new_works_with_no_rectangle_graphic(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            source_data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            data_item = document_model.get_crop_new(source_data_item, None)
            self.assertIsNotNone(data_item)

    def test_processing_duplicate_does_copy(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
        document_model.append_data_item(data_item)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        display_panel = document_controller.selected_display_panel
        display_panel.set_display_panel_data_item(data_item)
        document_controller.processing_duplicate()
        document_controller.close()

    def test_processing_duplicate_with_region_does_copy(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
        document_model.append_data_item(data_item)
        crop_region = Graphics.RectangleGraphic()
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display_specifier.display.add_graphic(crop_region)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        display_panel = document_controller.selected_display_panel
        display_panel.set_display_panel_data_item(data_item)
        document_controller.processing_duplicate()
        document_controller.close()

    def test_processing_duplicate_with_computation_copies_it_but_has_same_data_source(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            source_data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            data_item = document_model.get_invert_new(source_data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(data_item)
            document_controller.processing_duplicate()
            data_item_dup = document_model.data_items[-1]
            self.assertIsNotNone(document_model.get_data_item_computation(data_item_dup))
            self.assertNotEqual(document_model.get_data_item_computation(data_item_dup), document_model.get_data_item_computation(data_item))
            self.assertNotEqual(document_model.get_data_item_computation(data_item_dup).variables[0], document_model.get_data_item_computation(data_item).variables[0])
            self.assertEqual(document_model.get_data_item_computation(data_item_dup).variables[0].variable_specifier["uuid"], document_model.get_data_item_computation(data_item).variables[0].variable_specifier["uuid"])
            self.assertEqual(document_model.resolve_object_specifier(document_model.get_data_item_computation(data_item_dup).variables[0].variable_specifier).value.data_item,
                             document_model.resolve_object_specifier(document_model.get_data_item_computation(data_item).variables[0].variable_specifier).value.data_item)

    def test_fixing_display_limits_works_for_all_data_types(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_size = (8, 8)
        document_model.append_data_item(DataItem.DataItem(numpy.ones(data_size, numpy.int16)))
        document_model.append_data_item(DataItem.DataItem(numpy.ones(data_size, numpy.int32)))
        document_model.append_data_item(DataItem.DataItem(numpy.ones(data_size, numpy.int64)))
        document_model.append_data_item(DataItem.DataItem(numpy.ones(data_size, numpy.uint16)))
        document_model.append_data_item(DataItem.DataItem(numpy.ones(data_size, numpy.uint32)))
        document_model.append_data_item(DataItem.DataItem(numpy.ones(data_size, numpy.uint64)))
        document_model.append_data_item(DataItem.DataItem(numpy.ones(data_size, numpy.float32)))
        document_model.append_data_item(DataItem.DataItem(numpy.ones(data_size, numpy.float64)))
        document_model.append_data_item(DataItem.DataItem(numpy.ones(data_size, numpy.complex64)))
        document_model.append_data_item(DataItem.DataItem(numpy.ones(data_size, numpy.complex128)))
        document_model.append_data_item(DataItem.DataItem(numpy.ones(data_size + (3,), numpy.uint8)))
        document_model.append_data_item(DataItem.DataItem(numpy.ones(data_size + (4,), numpy.uint8)))
        document_model.append_data_item(DataItem.DataItem(numpy.ones((2, ) + data_size, numpy.float32)))
        for data_item in document_model.data_items:
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            document_controller.fix_display_limits(display_specifier)
            self.assertEqual(len(display_specifier.display.display_limits), 2)
        document_controller.close()

    def test_delete_by_context_menu_actually_deletes_item_from_library(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            source_data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            context_menu = document_controller.create_context_menu_for_display(source_data_item.primary_display_specifier.display)
            context_menu_items = context_menu.items
            delete_item = next(x for x in context_menu_items if x.title == "Delete Library Item")
            delete_item.callback()
            self.assertEqual(len(document_model.data_items), 0)

    def test_putting_data_item_in_selected_empty_display_updates_selected_data_item_binding(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            self.assertEqual(document_controller.focused_data_item, data_item)

    def test_creating_r_var_on_data_item(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(data_item)
            document_controller.prepare_data_item_script(do_log=False)
            self.assertEqual(data_item.r_var, "r01")

    def test_creating_r_var_on_composite_item(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            composite_item = DataItem.CompositeLibraryItem()
            document_model.append_data_item(composite_item)
            composite_item.append_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(composite_item)
            document_controller.prepare_data_item_script(do_log=False)
            self.assertEqual(composite_item.r_var, "r01")

    def test_display_data_item_when_it_is_immediately_filtered(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            document_controller.set_filter("none")
            document_controller.display_data_item(DataItem.DisplaySpecifier.from_data_item(data_item))

    def test_cut_paste_undo_redo(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            display = data_item.displays[0]
            display.add_graphic(Graphics.RectangleGraphic())
            display.add_graphic(Graphics.EllipseGraphic())
            self.assertEqual(2, len(display.graphics))
            self.assertIsInstance(display.graphics[0], Graphics.RectangleGraphic)
            self.assertIsInstance(display.graphics[1], Graphics.EllipseGraphic)
            document_controller.display_data_item(DataItem.DisplaySpecifier.from_data_item(data_item))
            display.graphic_selection.set(0)
            display.graphic_selection.add(1)
            # handle cut, undo, redo
            document_controller.handle_cut()
            self.assertEqual(0, len(display.graphics))
            document_controller.handle_undo()
            self.assertEqual(2, len(display.graphics))
            self.assertIsInstance(display.graphics[0], Graphics.RectangleGraphic)
            self.assertIsInstance(display.graphics[1], Graphics.EllipseGraphic)
            document_controller.handle_redo()
            self.assertEqual(0, len(display.graphics))
            # handle paste, undo, redo
            document_controller.handle_paste()
            self.assertEqual(2, len(display.graphics))
            self.assertIsInstance(display.graphics[0], Graphics.RectangleGraphic)
            self.assertIsInstance(display.graphics[1], Graphics.EllipseGraphic)
            document_controller.handle_undo()
            self.assertEqual(0, len(display.graphics))
            document_controller.handle_redo()
            self.assertEqual(2, len(display.graphics))
            self.assertIsInstance(display.graphics[0], Graphics.RectangleGraphic)
            self.assertIsInstance(display.graphics[1], Graphics.EllipseGraphic)

    def test_snapshot_undo_redo_cycle(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            # verify initial conditions
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(None, display_panel.library_item)
            # do the snapshot and verify
            document_controller._perform_snapshot(data_item)
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(document_model.data_items[1], display_panel.library_item)
            snapshot_uuid = document_model.data_items[1].uuid
            # undo and verify
            document_controller.handle_undo()
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(None, display_panel.library_item)
            # redo and verify
            document_controller.handle_redo()
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(snapshot_uuid, document_model.data_items[1].uuid)
            self.assertEqual(document_model.data_items[1], display_panel.library_item)
            # undo again and verify
            document_controller.handle_undo()
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(None, display_panel.library_item)
            # redo again and verify
            document_controller.handle_redo()
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(snapshot_uuid, document_model.data_items[1].uuid)
            self.assertEqual(document_model.data_items[1], display_panel.library_item)

    def test_insert_library_items_undo_redo_cycle(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item1 = DataItem.DataItem(numpy.zeros((2, 2)))
            data_item2 = DataItem.DataItem(numpy.zeros((2, 2)))
            data_item3 = DataItem.DataItem(numpy.zeros((2, 2)))
            data_item4 = DataItem.DataItem(numpy.zeros((2, 2)))
            data_item_uuids = [data_item1.uuid, data_item2.uuid, data_item3.uuid, data_item4.uuid]
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item4)
            # insert the new data items
            command = DocumentController.DocumentController.InsertLibraryItemsCommand(document_controller, [data_item2, data_item3], 1)
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(4, len(document_model.data_items))
            self.assertListEqual([data_item1, data_item2, data_item3, data_item4], list(document_model.data_items))
            # undo and check
            document_controller.handle_undo()
            self.assertEqual(2, len(document_model.data_items))
            self.assertListEqual([data_item1, data_item4], list(document_model.data_items))
            # redo and check
            document_controller.handle_redo()
            self.assertEqual(4, len(document_model.data_items))
            self.assertListEqual(data_item_uuids, [data_item.uuid for data_item in document_model.data_items])


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
