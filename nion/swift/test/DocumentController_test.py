# standard libraries
import contextlib
import gc
import logging
import os
import tempfile
import unittest
import weakref

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift import DisplayPanel
from nion.swift import Facade
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import Symbolic
from nion.swift.test import TestContext
from nion.ui import TestUI
from nion.utils import Geometry


Facade.initialize()


def create_memory_profile_context() -> TestContext.MemoryProfileContext:
    return TestContext.MemoryProfileContext()


def construct_test_document(document_controller: DocumentController.DocumentController) -> None:
    document_model = document_controller.document_model
    data_group1 = DataGroup.DataGroup()
    document_model.append_data_group(data_group1)
    data_item1a = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
    document_model.append_data_item(data_item1a)
    data_group1.append_display_item(document_model.get_display_item_for_data_item(data_item1a))
    data_item1b = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
    document_model.append_data_item(data_item1b)
    data_group1.append_display_item(document_model.get_display_item_for_data_item(data_item1b))
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
    data_group2b1.append_display_item(document_model.get_display_item_for_data_item(data_item2b1a))

class TestDocumentControllerClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        TestContext.end_leaks(self)

    def test_delete_document_controller(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            weak_document_model = weakref.ref(document_controller.document_model)
            weak_document_window = weakref.ref(document_controller._document_window)
            weak_document_controller = weakref.ref(document_controller)
            self.assertIsNotNone(weak_document_controller())
            self.assertIsNotNone(weak_document_window())
            self.assertIsNotNone(weak_document_model())
        document_controller = None
        gc.collect()
        self.assertIsNone(weak_document_controller())
        self.assertIsNone(weak_document_window())
        self.assertIsNone(weak_document_model())

    def test_document_controller_releases_document_model(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            weak_document_model = weakref.ref(document_model)
        document_controller = None
        data_item = None
        document_model = None
        gc.collect()
        self.assertIsNone(weak_document_model())

    def test_document_controller_releases_workspace_controller(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            weak_workspace_controller = weakref.ref(document_controller.workspace_controller)
        document_controller = None
        data_item = None
        document_model = None
        gc.collect()
        self.assertIsNone(weak_workspace_controller())

    def test_document_controller_releases_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            weak_data_item = weakref.ref(data_item)
        document_controller = None
        data_item = None
        document_model = None
        gc.collect()
        self.assertIsNone(weak_data_item())

    def test_display_panel_releases_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            weak_data_item = weakref.ref(data_item)
            display_panel = DisplayPanel.DisplayPanel(document_controller, dict())
            display_panel.set_display_panel_display_item(display_item)
            self.assertIsNotNone(weak_data_item())
            display_panel.close()
        document_controller = None
        data_item = None
        display_item = None
        document_model = None
        display_panel = None
        gc.collect()
        self.assertIsNone(weak_data_item())

    def test_document_controller_releases_itself(self):
        i = 0
        try:
            for i in range(100):
                with TestContext.create_memory_context() as test_context:
                    document_controller = test_context.create_document_controller()
                    document_model = document_controller.document_model
                    weak_document_controller = weakref.ref(document_controller)
                    document_model.append_data_item(DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32)))
                    document_controller.periodic()
                document_controller = None
                gc.collect()
                self.assertIsNone(weak_document_controller())
        except Exception as e:
            print(i)
            raise

    def test_flat_data_groups(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            construct_test_document(document_controller)
            self.assertEqual(len(list(document_controller.document_model.get_flat_data_group_generator())), 7)
            self.assertEqual(len(document_controller.document_model.data_items), 3)
            self.assertEqual(document_controller.document_model.display_items[0], document_controller.document_model.data_groups[0].display_items[0])
            self.assertEqual(document_controller.document_model.display_items[1], document_controller.document_model.data_groups[0].display_items[1])
            self.assertEqual(document_controller.document_model.display_items[2], document_controller.document_model.data_groups[1].data_groups[1].data_groups[0].display_items[0])

    def test_receive_files_should_put_files_into_document_model_at_end(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
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
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
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
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_group = DataGroup.DataGroup()
            document_model.append_data_group(data_group)
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item1.title = "data_item1"
            document_model.append_data_item(data_item1)
            data_group.append_display_item(document_model.get_display_item_for_data_item(data_item1))
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2.title = "data_item2"
            document_model.append_data_item(data_item2)
            data_group.append_display_item(document_model.get_display_item_for_data_item(data_item2))
            data_item3 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item3.title = "data_item3"
            document_model.append_data_item(data_item3)
            data_group.append_display_item(document_model.get_display_item_for_data_item(data_item3))
            new_data_items = document_controller.receive_files([":/app/scroll_gem.png"], data_group=data_group, index=2, threaded=False, project=document_model._project)
            self.assertEqual(document_model.data_items.index(new_data_items[0]), 3)
            self.assertEqual(data_group.display_items.index(document_model.get_display_item_for_data_item(new_data_items[0])), 2)

    def test_remove_graphic_removes_it_from_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            line_graphic = document_controller.add_line_graphic()
            # make sure assumptions are correct
            self.assertEqual(len(display_item.graphic_selection.indexes), 1)
            self.assertTrue(0 in display_item.graphic_selection.indexes)
            self.assertEqual(len(display_item.graphics), 1)
            self.assertEqual(display_item.graphics[0], line_graphic)
            # remove the graphic and make sure things are as expected
            display_panel.set_display_panel_display_item(display_item)
            document_controller.remove_selected_graphics()
            self.assertEqual(len(display_item.graphic_selection.indexes), 0)
            self.assertEqual(len(display_item.graphics), 0)

    def test_remove_line_profile_does_not_remove_data_item_itself(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            line_profile_data_item = document_controller.processing_line_profile().data_item
            document_controller.periodic()  # TODO: remove need to let the inspector catch up
            display_panel.set_display_panel_display_item(display_item)
            display_item.graphic_selection.clear()
            display_item.graphic_selection.add(0)
            # make sure assumptions are correct
            self.assertEqual(document_model.get_source_data_items(line_profile_data_item)[0], data_item)
            self.assertTrue(line_profile_data_item in document_model.data_items)
            self.assertTrue(data_item in document_model.data_items)
            # remove the graphic and make sure things are as expected
            display_panel.set_display_panel_display_item(display_item)
            document_controller.remove_selected_graphics()
            self.assertTrue(data_item in document_model.data_items)

    def test_remove_line_profile_removes_associated_child_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            # add a data item
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # ensure first data item is displayed
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            # make a line profile
            line_profile_data_item = document_controller.processing_line_profile().data_item
            # set up the selection
            display_item.graphic_selection.clear()
            display_item.graphic_selection.add(0)
            # make sure assumptions are correct
            self.assertEqual(document_model.get_source_data_items(line_profile_data_item)[0], data_item)
            self.assertTrue(line_profile_data_item in document_model.data_items)
            # ensure data item is selected, then remove the graphic
            display_panel.set_display_panel_display_item(display_item)
            document_controller.remove_selected_graphics()
            self.assertEqual(0, len(display_item.graphics))
            self.assertEqual(0, len(display_item.graphic_selection.indexes))  # disabled until test_remove_line_profile_updates_graphic_selection
            self.assertFalse(line_profile_data_item in document_model.data_items)

    def test_document_model_closed_only_after_all_document_controllers_closed(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model(auto_close=False)
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            document_controller1 = test_context.create_secondary_document_controller(document_model, auto_close=False)
            document_controller2 = test_context.create_secondary_document_controller(document_model, auto_close=False)
            with data_item.data_item_changes():
                pass  # triggers usage of 'processors' which gets set to null when closed
            document_controller1.close()
            with data_item.data_item_changes():
                pass  # triggers usage of 'processors' which gets set to null when closed
            document_controller2.close()  # this would fail even if processors part didn't fail

    def test_processing_on_crop_region_constructs_composite_operation(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            h, w = 8, 8
            data_item = DataItem.DataItem(numpy.ones((h, w), numpy.float32))
            document_model.append_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = ((0.25, 0.25), (0.5, 0.5))
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_graphic(crop_region)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            new_data_item = document_model.get_invert_new(display_item, display_item.data_item, crop_region)
            document_model.recompute_all()
            self.assertEqual(new_data_item.data_shape, (h//2, w//2))
            self.assertEqual(new_data_item.data_dtype, data_item.data_dtype)
            self.assertAlmostEqual(new_data_item.data[h//4, w//4], -1.0)

    def test_processing_on_crop_region_connects_region_to_operation(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = ((0.25, 0.25), (0.5, 0.5))
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_graphic(crop_region)
            new_data_item = document_model.get_invert_new(display_item, display_item.data_item, crop_region)
            self.assertEqual(crop_region.bounds, document_model.get_data_item_computation(new_data_item).get_input("src").graphic.bounds)
            crop_region.bounds = ((0.3, 0.4), (0.25, 0.35))
            self.assertEqual(crop_region.bounds, document_model.get_data_item_computation(new_data_item).get_input("src").graphic.bounds)

    def test_processing_on_crop_region_recomputes_when_bounds_changes(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = ((0.25, 0.25), (0.5, 0.5))
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_graphic(crop_region)
            cropped_data_item = document_model.get_invert_new(display_item, display_item.data_item, crop_region)
            document_model.recompute_all()
            cropped_display_item = document_model.get_data_item_computation(cropped_data_item)
            self.assertFalse(cropped_display_item.needs_update)
            crop_region.bounds = ((0.3, 0.4), (0.25, 0.35))
            self.assertTrue(cropped_display_item.needs_update)

    def test_creating_with_variable_produces_valid_computation(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data = ((numpy.random.randn(2, 2) + 1) * 10).astype(numpy.int32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            r_var = document_model.assign_variable_to_display_item(display_item)
            computed_data_item = document_controller.processing_computation(f"target.xdata = {r_var}.xdata * 2")
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, data*2))

    def test_extra_variables_in_computation_get_purged(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data = ((numpy.random.randn(2, 2) + 1) * 10).astype(numpy.int32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            data_item2 = DataItem.DataItem(numpy.copy(data))
            document_model.append_data_item(data_item2)
            data_item3 = DataItem.DataItem(numpy.copy(data))
            document_model.append_data_item(data_item3)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            display_item3 = document_model.get_display_item_for_data_item(data_item3)
            r_var = document_model.assign_variable_to_display_item(display_item)
            r_var2 = document_model.assign_variable_to_display_item(display_item2)
            document_model.assign_variable_to_display_item(display_item3)
            computed_data_item = document_controller.processing_computation(f"target.xdata = {r_var}.xdata * 2 + {r_var2}.xdata")
            self.assertEqual(len(document_model.get_data_item_computation(computed_data_item).variables), 2)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, data*2 + data))

    def test_deleting_processed_data_item_and_then_recomputing_works(self):
        # processed data item should be removed from recomputing queue
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = ((0.25, 0.25), (0.5, 0.5))
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_graphic(crop_region)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            data_item_result = document_model.get_invert_new(display_item, display_item.data_item, crop_region)
            document_model.remove_data_item(data_item_result)
            document_model.recompute_all()

    def test_delete_source_region_of_computation_deletes_target_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            source_data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            source_display_item = document_model.get_display_item_for_data_item(source_data_item)
            target_data_item = document_model.get_line_profile_new(source_display_item, source_display_item.data_item, None)
            self.assertIn(target_data_item, document_model.data_items)
            source_display_item.remove_graphic(source_display_item.graphics[0]).close()
            self.assertNotIn(target_data_item, document_model.data_items)

    def test_delete_source_data_item_of_computation_deletes_target_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            source_data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            source_display_item = document_model.get_display_item_for_data_item(source_data_item)
            target_data_item = document_model.get_line_profile_new(source_display_item, source_display_item.data_item, None)
            self.assertIn(target_data_item, document_model.data_items)
            document_model.remove_data_item(source_data_item)
            self.assertNotIn(target_data_item, document_model.data_items)

    def test_delete_target_data_item_of_computation_deletes_source_region(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            source_data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            source_display_item = document_model.get_display_item_for_data_item(source_data_item)
            target_data_item = document_model.get_line_profile_new(source_display_item, source_display_item.data_item, None)
            self.assertIn(target_data_item, document_model.data_items)
            self.assertEqual(len(source_display_item.graphics), 1)
            document_model.remove_data_item(target_data_item)
            self.assertEqual(len(source_display_item.graphics), 0)
            self.assertNotIn(target_data_item, document_model.data_items)

    def test_delete_data_item_with_source_region_also_cascade_deletes_target(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            source_data_item = DataItem.DataItem(numpy.ones((8, 8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            source_display_item = document_model.get_display_item_for_data_item(source_data_item)
            intermediate_data_item = document_model.get_pick_region_new(source_display_item, source_display_item.data_item)
            intermediate_display_item = document_model.get_display_item_for_data_item(intermediate_data_item)
            interval_region = Graphics.IntervalGraphic()
            intermediate_display_item.add_graphic(interval_region)
            target_data_item = document_model.get_invert_new(source_display_item, source_display_item.data_item)
            target_computation = document_model.get_data_item_computation(target_data_item)
            target_computation.create_input_item("interval", Symbolic.make_item(interval_region), label="I")
            self.assertIn(source_data_item, document_model.data_items)
            self.assertIn(intermediate_data_item, document_model.data_items)
            self.assertIn(target_data_item, document_model.data_items)
            document_model.remove_data_item(intermediate_data_item)  # this will cascade delete target
            self.assertIn(source_data_item, document_model.data_items)
            self.assertNotIn(intermediate_data_item, document_model.data_items)
            self.assertNotIn(target_data_item, document_model.data_items)

    def test_delete_graphic_with_sibling_and_data_item_dependent_on_both_also_cascade_deletes_target(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            source_data_item = DataItem.DataItem(numpy.ones((8, 8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            source_display_item = document_model.get_display_item_for_data_item(source_data_item)
            intermediate_data_item = document_model.get_pick_region_new(source_display_item, source_display_item.data_item)
            intermediate_display_item = document_model.get_display_item_for_data_item(intermediate_data_item)
            interval_region1 = Graphics.IntervalGraphic()
            intermediate_display_item.add_graphic(interval_region1)
            interval_region2 = Graphics.IntervalGraphic()
            intermediate_display_item.add_graphic(interval_region2)
            target_data_item = document_model.get_invert_new(source_display_item, source_display_item.data_item)
            target_computation = document_model.get_data_item_computation(target_data_item)
            target_computation.create_input_item("interval1", Symbolic.make_item(interval_region1), label="I")
            target_computation.create_input_item("interval2", Symbolic.make_item(interval_region2), label="I")
            self.assertIn(source_data_item, document_model.data_items)
            self.assertIn(intermediate_data_item, document_model.data_items)
            self.assertIn(target_data_item, document_model.data_items)
            intermediate_display_item.remove_graphic(interval_region2).close()  # this will cascade delete target and then interval_region1
            self.assertIn(source_data_item, document_model.data_items)
            self.assertIn(intermediate_data_item, document_model.data_items)
            self.assertNotIn(target_data_item, document_model.data_items)
            self.assertNotIn(interval_region1, intermediate_display_item.graphics)
            self.assertNotIn(interval_region2, intermediate_display_item.graphics)

    def test_delete_graphic_with_two_dependencies_deletes_both_dependencies(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            source_data_item = DataItem.DataItem(numpy.ones((8, 8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            source_display_item = document_model.get_display_item_for_data_item(source_data_item)
            crop_region = Graphics.RectangleGraphic()
            source_display_item.add_graphic(crop_region)
            target_data_item1 = document_model.get_invert_new(source_display_item, source_display_item.data_item, crop_region)
            target_data_item2 = document_model.get_invert_new(source_display_item, source_display_item.data_item, crop_region)
            self.assertIn(target_data_item1, document_model.data_items)
            self.assertIn(target_data_item2, document_model.data_items)
            source_display_item.remove_graphic(crop_region).close()
            self.assertNotIn(target_data_item1, document_model.data_items)
            self.assertNotIn(target_data_item2, document_model.data_items)

    def test_delete_target_data_item_with_source_region_with_another_target_does_not_delete_source_region(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            source_data_item = DataItem.DataItem(numpy.ones((8, 8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            source_display_item = document_model.get_display_item_for_data_item(source_data_item)
            crop_region = Graphics.RectangleGraphic()
            source_display_item.add_graphic(crop_region)
            target_data_item1 = document_model.get_invert_new(source_display_item, source_display_item.data_item, crop_region)
            target_data_item2 = document_model.get_invert_new(source_display_item, source_display_item.data_item, crop_region)
            self.assertIn(target_data_item1, document_model.data_items)
            self.assertIn(target_data_item2, document_model.data_items)
            # removing one of two targets should not delete the other target
            document_model.remove_data_item(target_data_item1)
            self.assertNotIn(target_data_item1, document_model.data_items)
            self.assertIn(target_data_item2, document_model.data_items)
            self.assertIn(crop_region, source_display_item.graphics)
            # but removing the last target should delete both the target and the source graphic
            document_model.remove_data_item(target_data_item2)
            self.assertNotIn(target_data_item2, document_model.data_items)
            self.assertNotIn(crop_region, source_display_item.graphics)

    def test_crop_new_works_with_no_rectangle_graphic(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            source_data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            source_display_item = document_model.get_display_item_for_data_item(source_data_item)
            data_item = document_model.get_crop_new(source_display_item, source_display_item.data_item)
            self.assertIsNotNone(data_item)

    def test_processing_duplicate_does_copy(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.processing_duplicate()

    def test_processing_duplicate_with_region_does_copy(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_graphic(crop_region)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.processing_duplicate()

    def test_processing_duplicate_with_computation_copies_it_but_has_same_data_source(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            source_data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            source_display_item = document_model.get_display_item_for_data_item(source_data_item)
            data_item = document_model.get_invert_new(source_display_item, source_display_item.data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.processing_duplicate()
            data_item_dup = document_model.data_items[-1]
            self.assertIsNotNone(document_model.get_data_item_computation(data_item_dup))
            self.assertNotEqual(document_model.get_data_item_computation(data_item_dup), document_model.get_data_item_computation(data_item))
            self.assertNotEqual(document_model.get_data_item_computation(data_item_dup).variables[0], document_model.get_data_item_computation(data_item).variables[0])
            self.assertEqual(document_model.get_data_item_computation(data_item_dup).get_input("src").data_item,
                             document_model.get_data_item_computation(data_item).get_input("src").data_item)

    def test_fixing_display_limits_works_for_all_data_types(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
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
                display_item = document_model.get_display_item_for_data_item(data_item)
                display_data_channel = display_item.display_data_channels[0]
                display_data_channel.display_limits = display_data_channel.get_calculated_display_values(True).data_range
                self.assertEqual(len(display_data_channel.display_limits), 2)

    def test_context_menu_succeeds_with_no_display_item(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            document_controller.select_display_items_in_data_panel([display_item])
            with contextlib.closing(document_controller.create_context_menu_for_display(list())):
                pass
            with contextlib.closing(document_controller.create_context_menu_for_display(list())):
                pass

    def test_delete_by_context_menu_actually_deletes_item_from_library(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            source_data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            source_display_item = document_model.get_display_item_for_data_item(source_data_item)
            context_menu = document_controller.create_context_menu_for_display([source_display_item])
            context_menu_items = context_menu.items
            delete_item = next(x for x in context_menu_items if x.title.startswith("Delete Data Item"))
            delete_item.callback()
            document_controller.periodic()
            self.assertEqual(len(document_model.data_items), 0)

    def test_delete_by_display_panel_context_menu_only_deletes_data_item_in_display_panel(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            source_data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            source_display_item = document_model.get_display_item_for_data_item(source_data_item)
            extra_data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(extra_data_item)
            document_controller.selection.set(0)
            document_controller.selection.add(1)
            document_controller.selected_display_panel = None  # use the document controller selection
            self.assertEqual(2, len(document_controller.selected_display_items))
            context_menu = document_controller.create_context_menu_for_display([source_display_item])
            context_menu_items = context_menu.items
            delete_item = next(x for x in context_menu_items if x.title.startswith("Delete Data Item"))
            delete_item.callback()
            document_controller.periodic()
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(1, len(document_controller.selection.indexes))

    def test_delete_by_data_panel_context_menu_only_deletes_all_selected_data_items(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            source_data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            extra_data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(extra_data_item)
            document_controller.selection.set(0)
            document_controller.selection.add(1)
            document_controller.selected_display_panel = None  # this would occur when user clicks in data panel
            context_menu = document_controller.create_context_menu_for_display(document_controller.selected_display_items)
            context_menu_items = context_menu.items
            delete_item = next(x for x in context_menu_items if x.title.startswith("Delete Display Items"))
            delete_item.callback()
            document_controller.periodic()
            self.assertEqual(len(document_model.data_items), 0)
            self.assertEqual(len(document_controller.selection.indexes), 0)

    def test_selected_display_items_is_non_empty_for_single_focused_display_panel_with_display_item(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            self.assertEqual(display_item, document_controller.selected_display_item)
            self.assertEqual([display_item], document_controller.selected_display_items)

    def test_selected_display_items_is_empty_after_clearing_display_panel(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            # clear the display panel
            display_panel.set_display_panel_display_item(None)
            self.assertEqual(None, document_controller.selected_display_item)
            self.assertEqual([], document_controller.selected_display_items)

    def test_selected_display_item_is_empty_after_selecting_multiple_items_in_browser(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((16, 16))))
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((16, 16))))
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((16, 16))))
            self.assertEqual(len(document_model.data_items), 4)
            display_item = document_model.get_display_item_for_data_item(data_item)
            d = {"type": "image", "display-panel-type": "browser-display-panel"}
            display_panel.change_display_panel_content(d)
            display_panel.set_display_panel_display_item(display_item)
            self.assertEqual(display_item, document_controller.selected_display_item)
            self.assertEqual([display_item], document_controller.selected_display_items)
            # change the selection in the display panel
            display_panel._selection_for_test.add_range(range(0, 4))
            self.assertEqual(None, document_controller.selected_display_item)
            self.assertEqual(set(document_model.display_items), set(document_controller.selected_display_items))

    def test_selected_display_item_is_empty_after_deleting_item_in_display_panel(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            self.assertEqual(display_item, document_controller.selected_display_item)
            self.assertEqual([display_item], document_controller.selected_display_items)
            document_controller.delete_display_items([display_item])
            self.assertEqual(None, document_controller.selected_display_item)
            self.assertEqual([], document_controller.selected_display_items)

    def test_selected_display_item_is_empty_after_deleting_item_in_data_panel(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(data_item)
            document_controller.selection.set(0)
            document_controller.selected_display_panel = None  # this would occur when user clicks in data panel
            context_menu = document_controller.create_context_menu_for_display(document_controller.selected_display_items)
            context_menu_items = context_menu.items
            delete_item = next(x for x in context_menu_items if x.title.startswith("Delete Data Item"))
            delete_item.callback()
            document_controller.periodic()
            self.assertEqual(len(document_model.data_items), 0)
            self.assertEqual(len(document_controller.selection.indexes), 0)
            self.assertEqual(None, document_controller.selected_display_item)
            self.assertEqual([], document_controller.selected_display_items)

    def test_putting_data_item_in_selected_empty_display_updates_selected_data_item_binding(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            self.assertEqual(document_controller.selected_data_item, data_item)

    def test_creating_r_var_on_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_model.assign_variable_to_display_item(display_item)
            self.assertEqual(DocumentModel.MappedItemManager().get_item_r_var(display_item), "r01")

    def test_display_data_channel_when_it_is_immediately_filtered(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            document_controller.set_filter("none")
            document_controller.show_display_item(document_model.get_display_item_for_data_item(data_item))

    def test_snapshot_of_display_is_added_to_all(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # check assumptions
            document_controller.set_filter(None)
            self.assertEqual(1, len(document_controller.filtered_display_items_model.items))
            # do the snapshot and verify
            document_controller._perform_display_item_snapshot(display_item)
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            self.assertEqual(2, len(document_controller.filtered_display_items_model.items))

    def test_snapshot_of_live_display_is_added_to_all(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            data_item.category = "temporary"
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # check assumptions
            document_controller.set_filter("persistent")
            self.assertEqual(0, len(document_controller.filtered_display_items_model.items))
            # do the snapshot and verify
            document_controller._perform_display_item_snapshot(display_item)
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            self.assertEqual(1, len(document_controller.filtered_display_items_model.items))

    def test_cut_paste_undo_redo(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_graphic(Graphics.RectangleGraphic())
            display_item.add_graphic(Graphics.EllipseGraphic())
            self.assertEqual(2, len(display_item.graphics))
            self.assertIsInstance(display_item.graphics[0], Graphics.RectangleGraphic)
            self.assertIsInstance(display_item.graphics[1], Graphics.EllipseGraphic)
            document_controller.show_display_item(document_model.get_display_item_for_data_item(data_item))
            display_item.graphic_selection.set(0)
            display_item.graphic_selection.add(1)
            # handle cut, undo, redo
            document_controller.handle_cut()
            self.assertEqual(0, len(display_item.graphics))
            document_controller.handle_undo()
            self.assertEqual(2, len(display_item.graphics))
            self.assertIsInstance(display_item.graphics[0], Graphics.RectangleGraphic)
            self.assertIsInstance(display_item.graphics[1], Graphics.EllipseGraphic)
            document_controller.handle_redo()
            self.assertEqual(0, len(display_item.graphics))
            # handle paste, undo, redo
            document_controller.handle_paste()
            self.assertEqual(2, len(display_item.graphics))
            self.assertIsInstance(display_item.graphics[0], Graphics.RectangleGraphic)
            self.assertIsInstance(display_item.graphics[1], Graphics.EllipseGraphic)
            document_controller.handle_undo()
            self.assertEqual(0, len(display_item.graphics))
            document_controller.handle_redo()
            self.assertEqual(2, len(display_item.graphics))
            self.assertIsInstance(display_item.graphics[0], Graphics.RectangleGraphic)
            self.assertIsInstance(display_item.graphics[1], Graphics.EllipseGraphic)

    def test_snapshot_undo_redo_cycle(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            # verify initial conditions
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(None, display_panel.data_item)
            # do the snapshot and verify
            document_controller._perform_display_item_snapshot(display_item)
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            self.assertEqual(document_model.data_items[1], display_panel.data_item)
            snapshot_uuid = document_model.data_items[1].uuid
            # undo and verify
            document_controller.handle_undo()
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(1, len(document_model.display_items))
            self.assertEqual(None, display_panel.data_item)
            # redo and verify
            document_controller.handle_redo()
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            self.assertEqual(snapshot_uuid, document_model.data_items[1].uuid)
            self.assertEqual(document_model.data_items[1], display_panel.data_item)
            # undo again and verify
            document_controller.handle_undo()
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(1, len(document_model.display_items))
            self.assertEqual(None, display_panel.data_item)
            # redo again and verify
            document_controller.handle_redo()
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            self.assertEqual(snapshot_uuid, document_model.data_items[1].uuid)
            self.assertEqual(document_model.data_items[1], display_panel.data_item)

    def test_insert_data_items_undo_redo_cycle(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item1 = DataItem.DataItem(numpy.zeros((2, 2)))
            data_item2 = DataItem.DataItem(numpy.zeros((2, 2)))
            data_item3 = DataItem.DataItem(numpy.zeros((2, 2)))
            data_item4 = DataItem.DataItem(numpy.zeros((2, 2)))
            data_item_uuids = [data_item1.uuid, data_item2.uuid, data_item3.uuid, data_item4.uuid]
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item4)
            # insert the new data items
            command = DocumentController.DocumentController.InsertDataItemsCommand(document_controller, [data_item2, data_item3], 1)
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(4, len(document_model.data_items))
            self.assertEqual(4, len(document_model.display_items))
            self.assertListEqual([data_item1, data_item2, data_item3, data_item4], list(document_model.data_items))
            # undo and check
            document_controller.handle_undo()
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            self.assertListEqual([data_item1, data_item4], list(document_model.data_items))
            # redo and check
            document_controller.handle_redo()
            self.assertEqual(4, len(document_model.data_items))
            self.assertEqual(4, len(document_model.display_items))
            self.assertListEqual(data_item_uuids, [data_item.uuid for data_item in document_model.data_items])

    def test_remove_display_items_undo_redo_cycle(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            data_item2 = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item2)
            display_item = DisplayItem.DisplayItem()
            display_item.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item))
            display_item.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item2))
            document_model.append_display_item(display_item)
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(3, len(document_model.display_items))
            self.assertEqual(1, len(document_model.display_items[0].display_data_channels))
            self.assertEqual(1, len(document_model.display_items[1].display_data_channels))
            self.assertEqual(2, len(document_model.display_items[-1].display_data_channels))
            # remove display
            command = document_controller.create_remove_display_items_command([display_item])
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            self.assertEqual(1, len(document_model.display_items[0].display_data_channels))
            self.assertEqual(1, len(document_model.display_items[1].display_data_channels))
            # undo and check
            document_controller.handle_undo()
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(3, len(document_model.display_items))
            self.assertEqual(1, len(document_model.display_items[0].display_data_channels))
            self.assertEqual(1, len(document_model.display_items[1].display_data_channels))
            self.assertEqual(2, len(document_model.display_items[-1].display_data_channels))
            # redo and check
            document_controller.handle_redo()
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            self.assertEqual(1, len(document_model.display_items[0].display_data_channels))
            self.assertEqual(1, len(document_model.display_items[1].display_data_channels))

    def test_remove_one_of_two_display_items_undo_redo_cycle(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            copy_display_item = document_model.get_display_item_copy_new(display_item)
            self.assertEqual(2, len(document_model.get_display_items_for_data_item(data_item)))
            # remove display
            command = DocumentController.DocumentController.RemoveDisplayItemCommand(document_controller, copy_display_item)
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(1, len(document_model.get_display_items_for_data_item(data_item)))
            # undo and check
            document_controller.handle_undo()
            self.assertEqual(2, len(document_model.get_display_items_for_data_item(data_item)))
            # redo and check
            document_controller.handle_redo()
            self.assertEqual(1, len(document_model.get_display_items_for_data_item(data_item)))

    def test_add_line_profile_undo_redo_cycle(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # ensure first data item is displayed
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            # make a line profile
            document_controller.processing_line_profile()
            document_model.recompute_all()
            # check assumptions
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            # undo and check
            document_controller.handle_undo()
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(1, len(document_model.display_items))
            # redo and check
            document_controller.handle_redo()
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))

    def test_adding_display_data_channel_to_displayed_line_plot_handles_display_ref_counts(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item1 = DataItem.DataItem(numpy.zeros((2,)))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((2,)))
            document_model.append_data_item(data_item2)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            # ensure first line profile is displayed
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item1)
            # add display layer
            display_item1.append_display_data_channel_for_data_item(data_item2)

    def test_remove_computation_triggering_removing_display_data_channels_is_undoable(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item1 = DataItem.DataItem(numpy.zeros((2,)))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((2,2)))
            document_model.append_data_item(data_item2)
            data_item3 = document_model.get_line_profile_new(document_model.get_display_item_for_data_item(data_item2), data_item2)
            document_model.recompute_all()
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            display_item1.append_display_data_channel_for_data_item(data_item3)
            interval_graphic = Graphics.IntervalGraphic()
            display_item1.add_graphic(interval_graphic)
            document_model.computations[0].source = interval_graphic
            # check assumptions
            self.assertEqual(3, len(document_model.data_items))
            self.assertEqual(2, len(display_item1.data_items))
            self.assertEqual(2, len(display_item1.display_layers))
            # remove interval and check
            command = document_controller.RemoveGraphicsCommand(document_controller, display_item1, [interval_graphic])
            command.perform()
            document_controller.push_undo_command(command)
            document_model.recompute_all()
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(1, len(display_item1.data_items))
            self.assertEqual(1, len(display_item1.display_layers))
            # undo and check
            document_controller.handle_undo()
            document_model.recompute_all()
            self.assertEqual(3, len(document_model.data_items))
            self.assertEqual(2, len(display_item1.data_items))
            self.assertEqual(2, len(display_item1.display_layers))
            # redo and check
            document_controller.handle_redo()
            document_model.recompute_all()
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(1, len(display_item1.data_items))
            self.assertEqual(1, len(display_item1.display_layers))
            # undo and check one more time
            document_controller.handle_undo()
            document_model.recompute_all()
            self.assertEqual(3, len(document_model.data_items))
            self.assertEqual(2, len(display_item1.data_items))
            self.assertEqual(2, len(display_item1.display_layers))

    class AddGraphics:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, src, graphics_list):
            self.__data = numpy.full((4, 4), len(graphics_list))

        def commit(self):
            self.computation.set_referenced_data("dst", self.__data)

    def test_remove_computation_graphic_from_list_is_undoable(self):
        Symbolic.register_computation_type("add_g", self.AddGraphics)
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller_with_application()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.full((2, 2), 1))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_graphic(Graphics.RectangleGraphic())
            display_item.add_graphic(Graphics.RectangleGraphic())
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.create_input_item("graphics_list", Symbolic.make_item_list(display_item.graphics))
            computation.processing_id = "add_g"
            document_model.append_computation(computation)
            document_model.recompute_all()
            result_data_item = document_model.data_items[-1]
            self.assertTrue(numpy.array_equal(result_data_item.data, numpy.full((4, 4), 2)))
            command = document_controller.RemoveGraphicsCommand(document_controller, display_item, [display_item.graphics[0]])
            command.perform()
            document_controller.push_undo_command(command)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(result_data_item.data, numpy.full((4, 4), 1)))
            document_controller.handle_undo()
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(result_data_item.data, numpy.full((4, 4), 2)))
            document_controller.handle_redo()
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(result_data_item.data, numpy.full((4, 4), 1)))
            document_controller.handle_undo()
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(result_data_item.data, numpy.full((4, 4), 2)))

    def test_remove_line_profile_graphic_in_composite_line_plot_undoes_layers(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((2,2)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            data_item1 = document_model.get_line_profile_new(display_item, display_item.data_item)
            data_item2 = document_model.get_line_profile_new(display_item, display_item.data_item)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            display_item1.append_display_data_channel_for_data_item(data_item2)
            # check assumptions
            self.assertEqual(3, len(document_model.data_items))
            self.assertEqual(2, len(display_item1.data_items))
            self.assertEqual(2, len(display_item1.display_layers))
            # remove interval and check
            command = document_controller.RemoveGraphicsCommand(document_controller, display_item, [display_item.graphics[0]])
            command.perform()
            document_controller.push_undo_command(command)
            document_model.recompute_all()
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(1, len(display_item1.data_items))
            self.assertEqual(1, len(display_item1.display_layers))
            # undo and check
            document_controller.handle_undo()
            document_model.recompute_all()
            self.assertEqual(3, len(document_model.data_items))
            self.assertEqual(2, len(display_item1.data_items))
            self.assertEqual(2, len(display_item1.display_layers))
            # redo and check
            document_controller.handle_redo()
            document_model.recompute_all()
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(1, len(display_item1.data_items))
            self.assertEqual(1, len(display_item1.display_layers))
            # undo and check one more time
            document_controller.handle_undo()
            document_model.recompute_all()
            self.assertEqual(3, len(document_model.data_items))
            self.assertEqual(2, len(display_item1.data_items))
            self.assertEqual(2, len(display_item1.display_layers))

    def test_get_3_data_sources_with_two_selected_in_data_panel(self):
        # test that getting 3 sources works when only two are selected
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item1 = DataItem.DataItem(numpy.zeros((2, 2)))
            data_item2 = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            document_controller.select_display_items_in_data_panel([display_item1, display_item2])
            document_controller.data_panel_focused()
            self.assertEqual(2, len(document_controller._get_n_data_sources(2)))
            self.assertEqual(3, len(document_controller._get_n_data_sources(3)))

    def test_filenames_in_exports(self):
        # The bmp writer is a dumb writer, and used to avoid complex setup code
        FILE_NAMES = ["test.bmp", "/././////.test.bmp", "$$%/%%_test.bmp", "\\aaaaa//test.bmp"]

        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            construct_test_document(document_controller)
            document_controller.ui.set_persistent_string("export_directory", tempfile.gettempdir())
            save_dir = tempfile.gettempdir()
            display_item = document_controller.project.display_items[-1]

            for file_name in FILE_NAMES:
                file_path = save_dir + os.sep + file_name
                for x in document_controller.project.display_items:
                    x.title = file_name

                with self.subTest(file_name=file_name+"export_file"):
                    try:
                        os.remove(file_path)
                    except FileNotFoundError:
                        pass
                    document_controller.export_file(display_item, file_path)
                    self.assertTrue(os.path.isfile(file_path))

                # The code path for export_files ends up at a pass statement unless its given a single item
                # display_item list. At that point it just calls export_file
                #with self.subTest(file_name=file_name + "export_files"):
                #    try:
                #        os.remove(file_path)
                #    except FileNotFoundError:
                #        pass
                #    document_controller.export_files(document_controller.project.display_items)
                #    self.assertTrue(os.path.isfile(file_path))

                with self.subTest(file_name=file_name + "export_svg"):
                    try:
                        os.remove(file_path)
                    except FileNotFoundError:
                        pass
                    document_controller.export_svg(display_item, file_path)
                    self.assertTrue(os.path.isfile(file_path))


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
