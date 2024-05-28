# standard libraries
import logging
import math
import unittest

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift import Application
from nion.swift.model import DataItem
from nion.swift.model import Graphics
from nion.swift.test import TestContext
from nion.ui import DrawingContext
from nion.ui import TestUI


class TestImageCanvasItemClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        TestContext.end_leaks(self)

    def test_mapping_widget_to_image_on_2d_data_stack_uses_signal_dimensions(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            document_controller.selected_display_panel.change_display_panel_content({"type": "image"})
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((50, 10, 10)), data_descriptor=DataAndMetadata.DataDescriptor(True, 0, 2))
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((100 + header_height, 100))
            # run test
            document_controller.tool_mode = "line-profile"
            display_panel.display_canvas_item.simulate_drag((20,25), (65,85))
            document_controller.periodic()
            self.assertEqual(display_item.graphics[0].vector, ((0.2, 0.25), (0.65, 0.85)))

    def test_mapping_widget_to_image_on_3d_spectrum_image_uses_collection_dimensions(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            document_controller.selected_display_panel.change_display_panel_content({"type": "image"})
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((10, 10, 50)), data_descriptor=DataAndMetadata.DataDescriptor(False, 2, 1))
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((100 + header_height, 100))
            # run test
            document_controller.tool_mode = "line-profile"
            display_panel.display_canvas_item.simulate_drag((20,25), (65,85))
            document_controller.periodic()
            self.assertEqual(display_item.graphics[0].vector, ((0.2, 0.25), (0.65, 0.85)))

    def test_dimension_used_for_scale_marker_on_2d_data_stack_is_correct(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            calibrations = [Calibration.Calibration(units="s"), Calibration.Calibration(units="y"), Calibration.Calibration(units="x")]
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((50, 10, 10)), dimensional_calibrations=calibrations, data_descriptor=DataAndMetadata.DataDescriptor(True, 0, 2))
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            # run test
            self.assertEqual(display_panel.display_canvas_item._scale_marker_canvas_item_for_test._dimension_calibration_for_test.units, "x")

    def test_dimension_used_for_scale_marker_on_3d_spectrum_image_is_correct(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            calibrations = [Calibration.Calibration(units="y"), Calibration.Calibration(units="x"), Calibration.Calibration(units="e")]
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((10, 10, 50)), dimensional_calibrations=calibrations, data_descriptor=DataAndMetadata.DataDescriptor(False, 2, 1))
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            # run test
            self.assertEqual(display_panel.display_canvas_item._scale_marker_canvas_item_for_test._dimension_calibration_for_test.units, "x")

    def test_dimension_used_for_scale_marker_on_4d_diffraction_image_is_correct(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            calibrations = [Calibration.Calibration(units="y"), Calibration.Calibration(units="x"), Calibration.Calibration(units="a"), Calibration.Calibration(units="b")]
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((10, 10, 50, 50)), dimensional_calibrations=calibrations, data_descriptor=DataAndMetadata.DataDescriptor(False, 2, 2))
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            # run test
            self.assertEqual(display_panel.display_canvas_item._scale_marker_canvas_item_for_test._dimension_calibration_for_test.units, "b")

    def test_scale_marker_with_invalid_calibration(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            calibrations = [Calibration.Calibration(scale=math.nan), Calibration.Calibration(scale=math.nan)]
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((10, 10)), dimensional_calibrations=calibrations)
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))

    def test_tool_returns_to_pointer_after_but_not_during_creating_rectangle(self):
        # setup
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            # run test
            self.assertEqual(document_controller.tool_mode, "pointer")
            for tool_mode in ["rectangle", "point", "ellipse", "line"]:
                document_controller.tool_mode = tool_mode
                display_panel.display_canvas_item.simulate_press((100,125))
                display_panel.display_canvas_item.simulate_move((100,125))
                self.assertEqual(document_controller.tool_mode, tool_mode)
                display_panel.display_canvas_item.simulate_move((250,200))
                display_panel.display_canvas_item.simulate_release((250,200))
                self.assertEqual(document_controller.tool_mode, "pointer")

    def test_selected_item_takes_priority_over_all_part(self):
        # setup
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            # run test
            rect_region = Graphics.RectangleGraphic()
            rect_region.bounds = (0.25, 0.25), (0.5, 0.5)
            line_region = Graphics.LineGraphic()
            line_region.start = (0.0, 1.0)
            line_region.end = (0.75, 0.25)
            # draws line, then rect
            display_item.add_graphic(line_region)
            display_item.add_graphic(rect_region)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.display_canvas_item.simulate_click((50, 950))
            document_controller.periodic()
            self.assertEqual(display_item.graphic_selection.indexes, set((0, )))
            display_panel.display_canvas_item.simulate_click((500, 500))
            document_controller.periodic()
            self.assertEqual(display_item.graphic_selection.indexes, set((0, )))

    def test_specific_parts_take_priority_over_all_part(self):
        # setup
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            # run test
            rect_region = Graphics.RectangleGraphic()
            rect_region.bounds = (0.25, 0.25), (0.5, 0.5)
            line_region = Graphics.LineGraphic()
            line_region.start = (0.5, 0.5)
            line_region.end = (0.5, 1.0)
            # draws line, then rect
            display_item.add_graphic(line_region)
            display_item.add_graphic(rect_region)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # clicking on line should select it
            display_panel.display_canvas_item.simulate_click((500, 600))
            document_controller.periodic()
            self.assertEqual(display_item.graphic_selection.indexes, set((0, )))

    def test_specific_parts_take_priority_when_another_selected(self):
        # setup
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            # run test
            rect_region1 = Graphics.RectangleGraphic()
            rect_region1.bounds = (0.2, 0.2), (0.4, 0.4)
            rect_region2 = Graphics.RectangleGraphic()
            rect_region2.bounds = (0.4, 0.4), (0.4, 0.4)
            display_item.add_graphic(rect_region1)
            display_item.add_graphic(rect_region2)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # clicking on line should select it
            display_panel.display_canvas_item.simulate_click((700, 700))
            document_controller.periodic()
            self.assertEqual(display_item.graphic_selection.indexes, set((1, )))
            display_panel.display_canvas_item.simulate_click((600, 200))
            document_controller.periodic()
            self.assertEqual(display_item.graphic_selection.indexes, set((0, )))

    def test_hit_testing_occurs_same_as_draw_order(self):
        # draw order occurs from 0 -> n
        # setup
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            # run test
            rect_region1 = Graphics.RectangleGraphic()
            rect_region1.bounds = (0.2, 0.2), (0.4, 0.4)
            rect_region2 = Graphics.RectangleGraphic()
            rect_region2.bounds = (0.4, 0.4), (0.4, 0.4)
            display_item.add_graphic(rect_region1)
            display_item.add_graphic(rect_region2)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.display_canvas_item.simulate_click((500, 500))
            document_controller.periodic()
            self.assertEqual(display_item.graphic_selection.indexes, set((1, )))

    def test_1d_data_displayed_as_2d(self):
        # setup
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, )))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            display_item.display_type = "image"
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            drawing_context = DrawingContext.DrawingContext()
            display_panel.root_container.repaint_immediate(drawing_context, display_panel.root_container.canvas_size)

    def test_hand_tool_on_one_image_of_multiple_displays(self):
        # setup
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            copy_display_item = document_model.get_display_item_copy_new(display_item)
            display_panel.set_display_panel_display_item(copy_display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            # run test
            document_controller.tool_mode = "hand"
            display_panel.display_canvas_item.simulate_press((100,125))

    def test_zoom_tool_on_one_image_of_multiple_displays(self):
        # setup
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            copy_display_item = document_model.get_display_item_copy_new(display_item)
            display_panel.set_display_panel_display_item(copy_display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            # run test
            document_controller.tool_mode = "zoom-in"
            display_panel.display_canvas_item.simulate_press((100, 125))

            document_controller.tool_mode = "zoom-out"
            display_panel.display_canvas_item.simulate_press((125, 100))

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
