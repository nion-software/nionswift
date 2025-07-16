# standard libraries
import math
import time
import typing
import unittest

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift import Facade
from nion.swift import LineGraphCanvasItem
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import Graphics
from nion.swift.test import TestContext
from nion.utils import Geometry


Facade.initialize()


class TestInfoPanelClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self._test_setup = TestContext.TestSetup()

    def tearDown(self):
        self._test_setup = typing.cast(typing.Any, None)
        TestContext.end_leaks(self)

    def __wait_for_cursor_position_text(self, document_controller, info_panel, text: str) -> bool:
        # for async cursor position
        start = time.time()
        while time.time() - start < 1.0:
            if (info_panel.label_row_1.text or str()) == text:
                return True
            document_controller.periodic()
            time.sleep(0.01)
        return False

    def test_cursor_over_2d_image_pixel_boundaries(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((4,4)))
            document_model.append_data_item(data_item)
            info_panel = document_controller.find_dock_panel("info-panel")
            display_panel = document_controller.selected_display_panel
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((400 + header_height, 400))
            # test mouse positioning
            display_panel.display_canvas_item.mouse_entered()
            display_panel.display_canvas_item.mouse_position_changed(20, 20, Graphics.NullModifiers())
            self.assertTrue(self.__wait_for_cursor_position_text(document_controller, info_panel, "Position: 0.0, 0.0"))
            display_panel.display_canvas_item.mouse_position_changed(180, 180, Graphics.NullModifiers())
            self.assertTrue(self.__wait_for_cursor_position_text(document_controller, info_panel, "Position: 1.0, 1.0"))
            display_panel.display_canvas_item.mouse_position_changed(80, 80, Graphics.NullModifiers())
            self.assertTrue(self.__wait_for_cursor_position_text(document_controller, info_panel, "Position: 0.0, 0.0"))
            display_panel.display_canvas_item.mouse_position_changed(-20, -20, Graphics.NullModifiers())
            self.assertTrue(self.__wait_for_cursor_position_text(document_controller, info_panel, str()))
            display_panel.display_canvas_item.mouse_position_changed(80, 80, Graphics.NullModifiers())
            self.assertTrue(self.__wait_for_cursor_position_text(document_controller, info_panel, "Position: 0.0, 0.0"))
            display_panel.display_canvas_item.mouse_position_changed(-80, -80, Graphics.NullModifiers())
            self.assertTrue(self.__wait_for_cursor_position_text(document_controller, info_panel, str()))
            display_panel.display_canvas_item.mouse_exited()

    def test_cursor_over_1d_composite_image(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((32,)))
            data_item2 = DataItem.DataItem(numpy.zeros((32,)))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2, False)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            display_item.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item2))
            display_item.calibration_style_id = "pixels-top-left"
            p, v = display_item.get_value_and_position_text((25, ))
            self.assertEqual("25", p)
            self.assertEqual("", v)

    def test_cursor_over_1d_data_displays_without_exception(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((1000, )))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            display_panel.display_canvas_item.mouse_entered()
            display_panel.display_canvas_item.mouse_position_changed(500, 500, Graphics.NullModifiers())
            display_panel.display_canvas_item.mouse_exited()

    def test_cursor_over_1d_data_displays_without_exception_when_not_displaying_calibration(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((1000, )))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.calibration_style_id = "relative-top-left"
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            display_panel.display_canvas_item.mouse_entered()
            display_panel.display_canvas_item.mouse_position_changed(500, 500, Graphics.NullModifiers())
            display_panel.display_canvas_item.mouse_exited()

    def test_cursor_over_1d_data_displays_proper_fractional_position(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, )))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            info_panel = document_controller.find_dock_panel("info-panel")
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            line_graph_layer_canvas_item = next(i for i in display_panel.root_container.canvas_items_at_point(500, 500) if isinstance(i, LineGraphCanvasItem.LineGraphLayerCanvasItem))
            p1 = line_graph_layer_canvas_item.map_to_canvas_item(Geometry.IntPoint(500, 20), display_panel.display_canvas_item)
            p2 = line_graph_layer_canvas_item.map_to_canvas_item(Geometry.IntPoint(500, 70), display_panel.display_canvas_item)
            p3 = line_graph_layer_canvas_item.map_to_canvas_item(Geometry.IntPoint(500, 140), display_panel.display_canvas_item)
            # this section is a bit finicky - it seems to depend on the mouse text changing when cursor is moved, so
            # it gets tested in p1, p3, p2 order.
            display_panel.display_canvas_item.mouse_entered()
            display_panel.display_canvas_item.mouse_position_changed(p1.x, p1.y, Graphics.NullModifiers())
            self.assertTrue(self.__wait_for_cursor_position_text(document_controller, info_panel, "Position: 0.0"))
            display_panel.display_canvas_item.mouse_position_changed(p3.x, p3.y, Graphics.NullModifiers())
            self.assertTrue(self.__wait_for_cursor_position_text(document_controller, info_panel, "Position: 1.0"))
            display_panel.display_canvas_item.mouse_position_changed(p2.x, p2.y, Graphics.NullModifiers())
            self.assertTrue(self.__wait_for_cursor_position_text(document_controller, info_panel, "Position: 0.0"))
            display_panel.display_canvas_item.mouse_exited()

    def test_cursor_over_1d_multiple_data_displays_without_exception(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.zeros((4, 1000), numpy.float64), data_descriptor=DataAndMetadata.DataDescriptor(False, 1, 1))
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.calibration_style_id = "pixels-top-left"
            p, v = display_item.get_value_and_position_text((500,))
            self.assertEqual(p, "500.0, 0.0")
            self.assertEqual(v, "0")

    def test_cursor_over_1d_multiple_data_but_2_datum_dimensions_displays_without_exception(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.zeros((4, 1000), numpy.float64), data_descriptor=DataAndMetadata.DataDescriptor(False, 0, 2))
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.calibration_style_id = "pixels-top-left"
            p, v = display_item.get_value_and_position_text((500,))
            self.assertEqual(p, "500.0, 0.0")
            self.assertEqual(v, "0")

    def test_cursor_over_1d_sequence_data_displays_without_exception(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.zeros((4, 1000), numpy.float64), data_descriptor=DataAndMetadata.DataDescriptor(True, 0, 1))
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.calibration_style_id = "pixels-top-left"
            p, v = display_item.get_value_and_position_text((500,))
            self.assertEqual(p, "500.0, 0.0")
            self.assertEqual(v, "0")

    def test_cursor_over_1d_image_without_exception(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((50,)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.calibration_style_id = "pixels-top-left"
            p, v = display_item.get_value_and_position_text((25, ))
            self.assertEqual(p, "25.0")
            self.assertEqual(v, "0")

    def test_cursor_over_1d_image_without_exception_x(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.new_data_item(DataAndMetadata.new_data_and_metadata(numpy.zeros((4, 25)), data_descriptor=DataAndMetadata.DataDescriptor(False, 1, 1)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "image"
            p, v = display_item.get_value_and_position_text((2, 20))
            self.assertEqual(p, "20.0, 2.0")
            self.assertEqual(v, "0")

    def test_cursor_over_3d_data_displays_without_exception(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10, 4)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            display_panel.display_canvas_item.mouse_entered()
            display_panel.display_canvas_item.mouse_position_changed(500, 500, Graphics.NullModifiers())
            display_panel.display_canvas_item.mouse_exited()

    def test_cursor_over_3d_data_displays_correct_ordering_of_indices(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.ones((100, 100, 20)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.calibration_style_id = "pixels-top-left"
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            info_panel = document_controller.find_dock_panel("info-panel")
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            display_panel.display_canvas_item.mouse_entered()
            display_panel.display_canvas_item.mouse_position_changed(500, 500, Graphics.NullModifiers())
            self.assertTrue(self.__wait_for_cursor_position_text(document_controller, info_panel, "Position: 0.0, 50.0, 50.0"))
            self.assertEqual(info_panel.label_row_2.text, "Value: 1")
            self.assertIsNone(info_panel.label_row_3.text, None)
            display_panel.display_canvas_item.mouse_exited()

    def test_cursor_over_2d_data_sequence_displays_correct_ordering_of_indices(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((20, 100, 100), numpy.float64), data_descriptor=DataAndMetadata.DataDescriptor(True, 0, 2))
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_data_channels[0].sequence_index = 4
            display_item.calibration_style_id = "pixels-top-left"
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            info_panel = document_controller.find_dock_panel("info-panel")
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            display_panel.display_canvas_item.mouse_entered()
            document_controller.periodic()
            display_panel.display_canvas_item.mouse_position_changed(500, 500, Graphics.NullModifiers())
            self.assertTrue(self.__wait_for_cursor_position_text(document_controller, info_panel, "Position: 50.0, 50.0, 4.0"))
            self.assertEqual("Value: 1", info_panel.label_row_2.text)
            self.assertIsNone(info_panel.label_row_3.text, None)
            display_panel.display_canvas_item.mouse_exited()

    def test_cursor_over_4d_data_displays_correctly(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data = (numpy.random.randn(100, 100, 20, 20) * 100).astype(numpy.int32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.calibration_style_id = "pixels-top-left"
            display_item.display_data_channels[0].collection_index = 20, 30
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            info_panel = document_controller.find_dock_panel("info-panel")
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            display_panel.display_canvas_item.mouse_entered()
            display_panel.display_canvas_item.mouse_position_changed(400, 600, Graphics.NullModifiers())
            self.assertTrue(self.__wait_for_cursor_position_text(document_controller, info_panel, "Position: 8.0, 12.0, 30.0, 20.0"))
            self.assertEqual(info_panel.label_row_2.text, "Value: {}".format(data[20, 30, 12, 8]))
            self.assertIsNone(info_panel.label_row_3.text, None)
            display_panel.display_canvas_item.mouse_exited()

    def test_cursor_over_invalid_calibration_display_without_exception(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.zeros((4, 4)), dimensional_calibrations=[Calibration.Calibration(scale=math.nan), Calibration.Calibration(scale=math.nan)])
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            p, v = display_item.get_value_and_position_text((2, 2))
            self.assertEqual("2.0, 2.0", p)
            self.assertEqual(v, "0")

    def test_cursor_over_4d_data_sequence_displays_correct_ordering_of_indices(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data = numpy.ones((10, 50, 50, 50, 50), numpy.float64)
            data[4, 5, 30, 25, 25] = 2
            data_and_metadata = DataAndMetadata.new_data_and_metadata(data, data_descriptor=DataAndMetadata.DataDescriptor(True, 2, 2))
            data_item = DataItem.new_data_item(data_and_metadata)
            data_item.set_dimensional_calibration(0, Calibration.Calibration(scale=1.0, units="a"))
            data_item.set_dimensional_calibration(1, Calibration.Calibration(scale=1.0, units="b"))
            data_item.set_dimensional_calibration(2, Calibration.Calibration(scale=1.0, units="c"))
            data_item.set_dimensional_calibration(3, Calibration.Calibration(scale=1.0, units="d"))
            data_item.set_dimensional_calibration(4, Calibration.Calibration(scale=1.0, units="e"))
            data_item.set_intensity_calibration(Calibration.Calibration(scale=1.0, units="f"))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_data_channels[0].sequence_index = 4
            display_item.display_data_channels[0].collection_index = 5, 30
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            info_panel = document_controller.find_dock_panel("info-panel")
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            display_panel.display_canvas_item.mouse_entered()
            display_panel.display_canvas_item.mouse_position_changed(500, 500, Graphics.NullModifiers())
            document_controller.periodic()
            self.assertTrue(self.__wait_for_cursor_position_text(document_controller, info_panel, "Position: 25.0 e, 25.0 d, 30.0 c, 5.0 b, 4.0 a"))
            self.assertEqual("Value: 2 f", info_panel.label_row_2.text)
            self.assertIsNone(info_panel.label_row_3.text, None)
            display_panel.display_canvas_item.mouse_exited()

    def test_cursor_over_fft_displays_polar_correctly(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.random.randn(12, 12))
            data_item2 = DataItem.DataItem(numpy.random.randn(11, 11))
            data_item.set_dimensional_calibrations([Calibration.Calibration(scale=1.0, units="a"), Calibration.Calibration(scale=1.0, units="a")])
            data_item2.set_dimensional_calibrations([Calibration.Calibration(scale=1.0, units="a"), Calibration.Calibration(scale=1.0, units="a")])
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            fft_data_item = document_model.get_fft_new(display_item, display_item.data_item)
            fft_data_item2 = document_model.get_fft_new(display_item2, display_item2.data_item)
            document_model.recompute_all()
            fft_display_item = document_model.get_display_item_for_data_item(fft_data_item)
            fft_display_item2 = document_model.get_display_item_for_data_item(fft_data_item2)
            # the sign of the angle zero is not guaranteed, so don't check the sign
            self.assertEqual("0.000 1/a, 0.0000° (polar)", fft_display_item.get_value_and_position_text((6, 6))[0].replace("-", ""))
            self.assertEqual("0.000 1/a, 0.0000° (polar)", fft_display_item2.get_value_and_position_text((5, 5))[0].replace("-", ""))
            # the distance is in 'a' not '1/a', when the distance > 0
            self.assertEqual("12.00 a, 0.0000° (polar)", fft_display_item.get_value_and_position_text((6, 7))[0].replace("-", ""))
            self.assertEqual("12.00 a, -180.0000° (polar)", fft_display_item.get_value_and_position_text((6, 5))[0])
            self.assertEqual("12.00 a, -90.0000° (polar)", fft_display_item.get_value_and_position_text((7, 6))[0])
            self.assertEqual("12.00 a, 90.0000° (polar)", fft_display_item.get_value_and_position_text((5, 6))[0])
            self.assertEqual("11.00 a, 0.0000° (polar)", fft_display_item2.get_value_and_position_text((5, 6))[0].replace("-", ""))
            self.assertEqual("11.00 a, -180.0000° (polar)", fft_display_item2.get_value_and_position_text((5, 4))[0])
            self.assertEqual("11.00 a, -90.0000° (polar)", fft_display_item2.get_value_and_position_text((6, 5))[0])
            self.assertEqual("11.00 a, 90.0000° (polar)", fft_display_item2.get_value_and_position_text((4, 5))[0])
