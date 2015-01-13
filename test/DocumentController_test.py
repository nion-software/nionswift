# standard libraries
import gc
import logging
import unittest
import weakref

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift import ImagePanel
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Operation
from nion.swift.model import Region
from nion.ui import Test


def construct_test_document(app, workspace_id=None):
    document_model = DocumentModel.DocumentModel()
    document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id=workspace_id)
    data_group1 = DataGroup.DataGroup()
    document_model.append_data_group(data_group1)
    data_item1a = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
    document_model.append_data_item(data_item1a)
    data_group1.append_data_item(data_item1a)
    data_item1b = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
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
    data_item2b1a = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
    document_model.append_data_item(data_item2b1a)
    data_group2b1.append_data_item(data_item2b1a)
    return document_controller

class TestDocumentControllerClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_delete_document_controller(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model)
        document_model = None
        weak_document_model = weakref.ref(document_controller.document_model)
        weak_document_window = weakref.ref(document_controller.document_window)
        weak_document_controller = weakref.ref(document_controller)
        self.assertIsNotNone(weak_document_controller())
        self.assertIsNotNone(weak_document_window())
        self.assertIsNotNone(weak_document_model())
        document_controller.close()
        document_controller = None
        self.assertIsNone(weak_document_controller())
        self.assertIsNone(weak_document_window())
        self.assertIsNone(weak_document_model())

    def test_image_panel_releases_data_item(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model)
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        weak_data_item = weakref.ref(data_item)
        image_panel = ImagePanel.ImagePanel(document_controller)
        image_panel.set_displayed_data_item(data_item)
        self.assertIsNotNone(weak_data_item())
        image_panel.canvas_item.close()
        image_panel.close()
        document_controller.close()
        document_controller = None
        data_item = None
        document_model = None
        gc.collect()
        self.assertIsNone(weak_data_item())

    def test_flat_data_groups(self):
        document_controller = construct_test_document(self.app)
        self.assertEqual(len(list(document_controller.document_model.get_flat_data_group_generator())), 7)
        self.assertEqual(len(list(document_controller.document_model.get_flat_data_item_generator())), 3)
        self.assertEqual(document_controller.document_model.get_data_item_by_key(0), document_controller.document_model.data_groups[0].data_items[0])
        self.assertEqual(document_controller.document_model.get_data_item_by_key(1), document_controller.document_model.data_groups[0].data_items[1])
        self.assertEqual(document_controller.document_model.get_data_item_by_key(2), document_controller.document_model.data_groups[1].data_groups[1].data_groups[0].data_items[0])

    def test_receive_files_should_put_files_into_document_model_at_end(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item1 = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item1.title = "data_item1"
        document_model.append_data_item(data_item1)
        data_item2 = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item2.title = "data_item2"
        document_model.append_data_item(data_item2)
        data_item3 = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item3.title = "data_item3"
        document_model.append_data_item(data_item3)
        new_data_items = document_controller.receive_files([":/app/scroll_gem.png"], threaded=False)
        self.assertEqual(document_model.data_items.index(new_data_items[0]), 3)

    def test_receive_files_should_put_files_into_document_model_at_index(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item1 = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item1.title = "data_item1"
        document_model.append_data_item(data_item1)
        data_item2 = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item2.title = "data_item2"
        document_model.append_data_item(data_item2)
        data_item3 = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item3.title = "data_item3"
        document_model.append_data_item(data_item3)
        new_data_items = document_controller.receive_files([":/app/scroll_gem.png"], index=2, threaded=False)
        self.assertEqual(document_model.data_items.index(new_data_items[0]), 2)

    def test_receive_files_should_put_files_into_data_group_at_index(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_group = DataGroup.DataGroup()
        document_model.append_data_group(data_group)
        data_item1 = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item1.title = "data_item1"
        document_model.append_data_item(data_item1)
        data_group.append_data_item(data_item1)
        data_item2 = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item2.title = "data_item2"
        document_model.append_data_item(data_item2)
        data_group.append_data_item(data_item2)
        data_item3 = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item3.title = "data_item3"
        document_model.append_data_item(data_item3)
        data_group.append_data_item(data_item3)
        new_data_items = document_controller.receive_files([":/app/scroll_gem.png"], data_group=data_group, index=2, threaded=False)
        self.assertEqual(document_model.data_items.index(new_data_items[0]), 3)
        self.assertEqual(data_group.data_items.index(new_data_items[0]), 2)

    def test_remove_graphic_removes_it_from_data_item(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        image_panel = document_controller.selected_image_panel
        image_panel.set_displayed_data_item(data_item)
        line_graphic = document_controller.add_line_region()
        # make sure assumptions are correct
        self.assertEqual(len(image_panel.display.graphic_selection.indexes), 1)
        self.assertTrue(0 in image_panel.display.graphic_selection.indexes)
        self.assertEqual(len(data_item.displays[0].drawn_graphics), 1)
        self.assertEqual(data_item.displays[0].drawn_graphics[0], line_graphic)
        # remove the graphic and make sure things are as expected
        document_controller.remove_graphic()
        self.assertEqual(len(image_panel.display.graphic_selection.indexes), 0)
        self.assertEqual(len(data_item.displays[0].drawn_graphics), 0)
        # clean up
        image_panel.close()

    def test_remove_line_profile_does_not_remove_data_item_itself(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        image_panel = document_controller.selected_image_panel
        image_panel.set_displayed_data_item(data_item)
        line_profile_data_item = document_controller.processing_line_profile()
        image_panel.set_displayed_data_item(data_item)
        image_panel.display.graphic_selection.clear()
        image_panel.display.graphic_selection.add(0)
        # make sure assumptions are correct
        self.assertEqual(line_profile_data_item.operation.data_sources[0].source_data_item, data_item)
        self.assertTrue(line_profile_data_item in document_model.data_items)
        self.assertTrue(data_item in document_model.data_items)
        # remove the graphic and make sure things are as expected
        document_controller.remove_graphic()
        self.assertTrue(data_item in document_model.data_items)
        # clean up
        image_panel.close()

    def test_remove_line_profile_removes_associated_child_data_item(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        image_panel = document_controller.selected_image_panel
        image_panel.set_displayed_data_item(data_item)
        line_profile_data_item = document_controller.processing_line_profile()
        image_panel.display.graphic_selection.clear()
        image_panel.display.graphic_selection.add(0)
        # make sure assumptions are correct
        self.assertEqual(line_profile_data_item.operation.data_sources[0].source_data_item, data_item)
        self.assertTrue(line_profile_data_item in document_model.data_items)
        # remove the graphic and make sure things are as expected
        document_controller.remove_graphic()
        self.assertEqual(len(data_item.displays[0].drawn_graphics), 0)
        self.assertEqual(len(data_item.displays[0].graphic_selection.indexes), 0)  # disabled until test_remove_line_profile_updates_graphic_selection
        self.assertFalse(line_profile_data_item in document_model.data_items)
        # clean up
        image_panel.close()

    def test_document_model_closed_only_after_all_document_controllers_closed(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
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
        data_item = DataItem.DataItem(numpy.ones((256, 256), numpy.float32))
        crop_region = Region.RectRegion()
        crop_region.bounds = ((0.25, 0.25), (0.5, 0.5))
        data_item.add_region(crop_region)
        document_model.append_data_item(data_item)
        image_panel = document_controller.selected_image_panel
        image_panel.set_displayed_data_item(data_item)
        inverted_data_item = document_controller.add_processing_operation_by_id("invert-operation", crop_region=crop_region)
        inverted_data_item.recompute_data()
        self.assertEqual(inverted_data_item.maybe_data_source.data_shape, (128, 128))
        self.assertEqual(inverted_data_item.maybe_data_source.data_dtype, data_item.maybe_data_source.data_dtype)
        self.assertAlmostEqual(inverted_data_item.maybe_data_source.data[50, 50], -1.0)

    def test_processing_on_crop_region_connects_region_to_operation(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.ones((256, 256), numpy.float32))
        crop_region = Region.RectRegion()
        crop_region.bounds = ((0.25, 0.25), (0.5, 0.5))
        data_item.add_region(crop_region)
        document_model.append_data_item(data_item)
        image_panel = document_controller.selected_image_panel
        image_panel.set_displayed_data_item(data_item)
        operation = Operation.OperationItem("invert-operation")
        document_controller.add_processing_operation(operation, crop_region=crop_region)
        self.assertEqual(crop_region.bounds, operation.data_sources[0].get_property("bounds"))
        crop_region.bounds = ((0.3, 0.4), (0.25, 0.35))
        self.assertEqual(crop_region.bounds, operation.data_sources[0].get_property("bounds"))

    def test_processing_on_crop_region_recomputes_when_bounds_changes(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.ones((256, 256), numpy.float32))
        crop_region = Region.RectRegion()
        crop_region.bounds = ((0.25, 0.25), (0.5, 0.5))
        data_item.add_region(crop_region)
        document_model.append_data_item(data_item)
        image_panel = document_controller.selected_image_panel
        image_panel.set_displayed_data_item(data_item)
        operation = Operation.OperationItem("invert-operation")
        cropped_data_item = document_controller.add_processing_operation(operation, crop_region=crop_region)
        document_model.recompute_all()
        self.assertFalse(cropped_data_item.maybe_data_source.is_data_stale)
        crop_region.bounds = ((0.3, 0.4), (0.25, 0.35))
        self.assertTrue(cropped_data_item.maybe_data_source.is_data_stale)

    class SumOperation(Operation.Operation):

        def __init__(self):
            super(TestDocumentControllerClass.SumOperation, self).__init__("Sum", "sum-operation")

        def get_processed_data(self, data_sources, values):
            result = None
            for data_source in data_sources:
                if result is None:
                    result = data_source.data
                else:
                    result += data_source.data
            return result

    def test_processing_on_dual_crop_region_constructs_composite_operation(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data1 = numpy.zeros((256, 256), numpy.float32)
        data1[0:128, 0:128] = 1
        data_item1 = DataItem.DataItem(data1)
        crop_region1 = Region.RectRegion()
        crop_region1.bounds = ((0.0, 0.0), (0.5, 0.5))
        data_item1.add_region(crop_region1)
        document_model.append_data_item(data_item1)
        data2 = numpy.zeros((256, 256), numpy.float32)
        data2[0:128, 0:128] = 2
        data_item2 = DataItem.DataItem(data2)
        crop_region2 = Region.RectRegion()
        crop_region2.bounds = ((0.25, 0.25), (0.5, 0.5))
        data_item2.add_region(crop_region2)
        document_model.append_data_item(data_item2)
        sum_operation = TestDocumentControllerClass.SumOperation()
        Operation.OperationManager().register_operation("sum-operation", lambda: sum_operation)
        sum_operation_item = Operation.OperationItem("sum-operation")
        left_display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item1)
        right_display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item2)
        result_data_item = document_controller.add_binary_processing_operation(sum_operation_item, left_display_specifier, right_display_specifier, crop_region1=crop_region1, crop_region2=crop_region2)
        result_data_item.recompute_data()
        buffered_data_source = result_data_item.maybe_data_source
        self.assertEqual(buffered_data_source.data_shape, (128, 128))
        self.assertEqual(buffered_data_source.data_dtype, numpy.float32)
        self.assertAlmostEqual(buffered_data_source.data[32, 32], 3.0)
        self.assertAlmostEqual(buffered_data_source.data[96, 32], 1.0)
        self.assertAlmostEqual(buffered_data_source.data[96, 96], 1.0)
        self.assertAlmostEqual(buffered_data_source.data[32, 96], 1.0)

    def test_deleting_processed_data_item_and_then_recomputing_works(self):
        # processed data item should be removed from recomputing queue
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.ones((256, 256), numpy.float32))
        crop_region = Region.RectRegion()
        crop_region.bounds = ((0.25, 0.25), (0.5, 0.5))
        data_item.add_region(crop_region)
        document_model.append_data_item(data_item)
        image_panel = document_controller.selected_image_panel
        image_panel.set_displayed_data_item(data_item)
        data_item_result = document_controller.add_processing_operation_by_id("invert-operation", crop_region=crop_region)
        document_model.remove_data_item(data_item_result)
        document_model.recompute_all()

    def test_processing_duplicate_does_copy(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.ones((256, 256), numpy.float32))
        image_panel = document_controller.selected_image_panel
        image_panel.set_displayed_data_item(data_item)
        document_controller.processing_duplicate()

    def test_processing_duplicate_with_operation_copies_it_but_has_same_data_source(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        source_data_item = DataItem.DataItem(numpy.ones((256, 256), numpy.float32))
        document_model.append_data_item(source_data_item)
        data_item = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(source_data_item._create_test_data_source())
        data_item.set_operation(invert_operation)
        image_panel = document_controller.selected_image_panel
        image_panel.set_displayed_data_item(data_item)
        data_item_dup = document_controller.processing_duplicate()
        self.assertIsNotNone(data_item_dup.operation)
        self.assertNotEqual(data_item_dup.operation, data_item.operation)
        self.assertNotEqual(data_item_dup.operation.data_sources[0], data_item.operation.data_sources[0])
        self.assertEqual(data_item_dup.operation.data_sources[0].data_item_uuid, data_item.operation.data_sources[0].data_item_uuid)
        self.assertEqual(data_item_dup.operation.data_sources[0].source_data_item, data_item.operation.data_sources[0].source_data_item)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
