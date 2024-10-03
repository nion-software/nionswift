# standard libraries
import logging
import math
import typing
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
from nion.ui import CanvasItem
from nion.ui import DrawingContext
from nion.ui import TestUI
from nion.utils import Geometry




class TestImageCanvasItemClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        TestContext.end_leaks(self)

    # Wrapper function allowing comparison of Tuples with the AlmostEqual unit test function
    def assertTupleAlmostEqual(self, tuple1: typing.Tuple[typing.Any, ...], tuple2: typing.Tuple[typing.Any, ...],
                               delta: typing.Any=None, places: typing.Any=None):
        self.assertEqual(len(tuple1), len(tuple2), "Tuples are of different lengths.")
        for a, b in zip(tuple1, tuple2):
            if delta is not None:
                self.assertAlmostEqual(a, b, delta=delta)
            elif places is not None:
                self.assertAlmostEqual(a, b, places=places)
            else:
                self.assertAlmostEqual(a, b)

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

    def test_zoom_tool_in_and_out_around_clicked_point_fit_mode(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((50, 50)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((100 + header_height, 100))
            display_panel.perform_action("set_fit_mode")
            # run test. each data pixel will be spanned by two display pixels. clicking at an odd value
            # will be a click in the center of a data pixel. zoom should expand and contract around that
            # pixel. there is also a check to make sure zooming is not just ending up with the same exact
            # zoom, which would also succeed.
            self.assertEqual((25, 25),
                             display_panel.display_canvas_item.map_widget_to_image(Geometry.IntPoint(51, 51)))
            self.assertEqual((30, 30),
                             display_panel.display_canvas_item.map_widget_to_image(Geometry.IntPoint(61, 61)))
            document_controller.tool_mode = "zoom"
            display_panel.display_canvas_item.simulate_click((20, 20))  # 10,10 in image space
            # the zoom tool runs asynchronously, so give it a slice of async time.
            document_controller.periodic()
            # check results
            # After zooming in on 20,20 canvas (10,10 image) the canvas will have zoomed in 1.25X so the display
            # now only shows 40x40 of the image on the canvas. Since it was centered around the 10,10 position of
            # the image the Canvas is now displaying 2->42 of the image with 2 image pixels off the side to the left,
            # and 8 to the right.  A click at 51,51 (image centre) now is 51/2.5 (20) image pixels in from the left,
            # plus the 2 extra based on which bit of the image we are viewing, so 20+2 = 22.

            self.assertTupleAlmostEqual((22, 22),
                                        display_panel.display_canvas_item.map_widget_to_image(Geometry.IntPoint(51, 51)),
                                        delta=1)
            # A click at 61,61 should NOT be that 22 plus the 5 from before. This second test verifies that we are
            # zoomed in and not just translated
            self.assertNotEqual((30, 30),
                                display_panel.display_canvas_item.map_widget_to_image(Geometry.IntPoint(61, 61)))

            # zoom out is done by passing the alt key to the canvas item.
            display_panel.display_canvas_item.simulate_click((20, 20), CanvasItem.KeyboardModifiers(alt=True))
            document_controller.periodic()
            # zoom in at the center of a data pixel followed by zoom out in the same spot should end up in the same original mapping.
            self.assertEqual((25, 25),
                             display_panel.display_canvas_item.map_widget_to_image(Geometry.IntPoint(51, 51)))

            self.assertEqual((30, 30),
                             display_panel.display_canvas_item.map_widget_to_image(Geometry.IntPoint(61, 61)))

    def test_zoom_tool_in_and_out_around_clicked_point_1_to_1_mode(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((40, 40)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((100 + header_height, 100))
            display_panel.perform_action("set_one_to_one_mode")
            # run test. Each canvas pixel starts as 1 image pixel, with image centered
            self.assertEqual((20, 20),
                             display_panel.display_canvas_item.map_widget_to_image(Geometry.IntPoint(50, 50)))
            self.assertEqual((30, 30),
                             display_panel.display_canvas_item.map_widget_to_image(Geometry.IntPoint(60, 60)))
            document_controller.tool_mode = "zoom"
            display_panel.display_canvas_item.simulate_click((40, 40))  # 10,10 in image space
            # the zoom tool runs asynchronously, so give it a slice of async time.
            document_controller.periodic()
            # check results
            # After zooming in on 40,40 canvas (10,10 image) the canvas will have zoomed in 1.25X so the display
            # displays the full new 50x50, but a quarter of the new pixels (2.5) are on the left and 3/4 on the right.
            # So the canvas starts displaying at 27.5 to 77.5 the image which is now 50 canvas pixels wide
            # Clicking centrally again, pixel 50 is 45% of the image across. 45% of 40 pixels is 18

            self.assertTupleAlmostEqual((18, 18),
                                        display_panel.display_canvas_item.map_widget_to_image(
                                            Geometry.IntPoint(50, 50)),
                                        delta=1)
            # A click at 61,61 should NOT be that 22 plus the 5 from before. This second test verifies that we are
            # zoomed in and not just translated
            self.assertNotEqual((35, 35),
                                display_panel.display_canvas_item.map_widget_to_image(Geometry.IntPoint(60, 60)))

            # zoom out is done by passing the alt key to the canvas item.
            display_panel.display_canvas_item.simulate_click((40, 40), CanvasItem.KeyboardModifiers(alt=True))
            document_controller.periodic()
            # zoom in at the center of a data pixel followed by zoom out in the same spot should end up in the
            # same original mapping.
            self.assertTupleAlmostEqual((20, 20),
                                        display_panel.display_canvas_item.map_widget_to_image(Geometry.IntPoint(50, 50)),
                                        delta=1)

            self.assertTupleAlmostEqual((30, 30),
                                        display_panel.display_canvas_item.map_widget_to_image(Geometry.IntPoint(60, 60)),
                                        delta=1)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
