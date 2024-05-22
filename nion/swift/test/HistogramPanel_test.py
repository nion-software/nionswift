# standard libraries
import contextlib
import unittest

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.swift import Application
from nion.swift import HistogramPanel
from nion.swift.model import DataItem
from nion.swift.model import Graphics
from nion.swift.test import TestContext
from nion.ui import TestUI


class TestHistogramPanelClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        TestContext.end_leaks(self)

    def get_data(self):
        data = numpy.full((10, 10), 200, dtype=numpy.uint32)
        data[5, 5] = 650
        return data

    def test_drag_to_set_limits(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(self.get_data())
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # set up histogram
            histogram_panel = document_controller.find_dock_panel("histogram-panel")
            histogram_canvas_item = histogram_panel._histogram_widget._histogram_canvas_item
            document_controller.show_display_item(display_item)
            histogram_canvas_item.update_layout((0, 0), (80, 300))
            # test
            display_data_channel = display_item.display_data_channels[0]
            self.assertEqual(display_data_channel.get_latest_computed_display_values().display_range, (200, 650))
            self.assertIsNone(display_data_channel.display_limits)
            histogram_panel._histogram_processor._evaluate_immediate()
            # drag
            histogram_canvas_item.mouse_pressed(60, 58, 0)
            histogram_canvas_item.mouse_position_changed(80, 58, 0)
            histogram_canvas_item.mouse_released(90, 58, 0)
            self.assertIsNotNone(display_data_channel.display_limits)
            self.assertEqual(display_data_channel.get_latest_computed_display_values().display_range, (290, 320))
            # double click and return to None
            histogram_canvas_item.mouse_pressed(121, 51, 0)
            histogram_canvas_item.mouse_released(121, 51, 0)
            histogram_canvas_item.mouse_pressed(121, 51, 0)
            histogram_canvas_item.mouse_double_clicked(121, 51, 0)
            histogram_canvas_item.mouse_released(121, 51, 0)
            self.assertIsNone(display_data_channel.display_limits)
            self.assertEqual(display_data_channel.get_latest_computed_display_values().display_range, (200, 650))

    def test_changing_source_data_marks_histogram_as_dirty_then_recomputes_via_model(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.random.randn(10, 10))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # set up histogram
            histogram_panel = document_controller.find_dock_panel("histogram-panel")
            histogram_canvas_item = histogram_panel._histogram_widget._histogram_canvas_item
            document_controller.show_display_item(display_item)
            histogram_canvas_item.update_layout((0, 0), (80, 300))
            # verify assumptions
            # wait for histogram task to be complete
            histogram_panel._histogram_processor._evaluate_immediate()
            histogram_data1 = histogram_canvas_item.histogram_data
            self.assertIsNotNone(histogram_data1)
            # now change the data and verify that histogram gets recomputed via document model
            display_item.data_item.set_data(numpy.random.randn(10, 10))
            # wait for histogram task to be complete
            histogram_panel._histogram_processor._evaluate_immediate()
            histogram_data2 = histogram_canvas_item.histogram_data
            self.assertFalse(numpy.array_equal(histogram_data1, histogram_data2))

    def test_changing_source_data_marks_statistics_as_dirty_then_recomputes_via_model(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(self.get_data())
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # set up histogram
            histogram_panel = document_controller.find_dock_panel("histogram-panel")
            histogram_canvas_item = histogram_panel._histogram_widget._histogram_canvas_item
            document_controller.show_display_item(display_item)
            histogram_canvas_item.update_layout((0, 0), (80, 300))
            # verify assumptions
            histogram_panel._histogram_processor._evaluate_immediate()
            stats1_text = histogram_panel._statistics_widget._stats1_property.value
            stats2_text = histogram_panel._statistics_widget._stats2_property.value
            self.assertIsNotNone(stats1_text)
            self.assertIsNotNone(stats2_text)
            # now change the data and verify that statistics gets recomputed via document model
            display_item.data_item.set_data(numpy.ones((10, 10), dtype=numpy.uint32))
            # wait for statistics task to be complete
            histogram_panel._histogram_processor._evaluate_immediate()
            self.assertNotEqual(stats1_text, histogram_panel._statistics_widget._stats1_property.value)
            self.assertNotEqual(stats2_text, histogram_panel._statistics_widget._stats2_property.value)

    def test_changing_intensity_calibration_marks_statistics_as_dirty_then_recomputes_via_model(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(self.get_data())
            data_item.intensity_calibration = Calibration.Calibration(0, 1, "nm")
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # set up histogram
            histogram_panel = document_controller.find_dock_panel("histogram-panel")
            histogram_canvas_item = histogram_panel._histogram_widget._histogram_canvas_item
            document_controller.show_display_item(display_item)
            histogram_canvas_item.update_layout((0, 0), (80, 300))
            # grab initial values
            histogram_panel._histogram_processor._evaluate_immediate()
            stats1_text = histogram_panel._statistics_widget._stats1_property.value
            stats2_text = histogram_panel._statistics_widget._stats2_property.value
            # now change the data and verify that statistics gets recomputed via document model
            display_item.intensity_calibration_style_id = display_item.intensity_calibration_styles[-1].calibration_style_id
            # wait for statistics task to be complete
            histogram_panel._histogram_processor._evaluate_immediate()
            self.assertNotEqual(stats1_text, histogram_panel._statistics_widget._stats1_property.value)
            self.assertNotEqual(stats2_text, histogram_panel._statistics_widget._stats2_property.value)

    def test_histogram_updates_when_crop_region_changes(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data = numpy.zeros((100, 100))
            data[20:40, 20:40] = 1
            data[40:60, 40:60] = 2
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # set up histogram
            histogram_panel = document_controller.find_dock_panel("histogram-panel")
            histogram_canvas_item = histogram_panel._histogram_widget._histogram_canvas_item
            document_controller.show_display_item(display_item)
            histogram_canvas_item.update_layout((0, 0), (80, 300))
            # test
            histogram_panel._histogram_processor._evaluate_immediate()
            stats1_text = histogram_panel._statistics_widget._stats1_property.value
            stats2_text = histogram_panel._statistics_widget._stats2_property.value
            rect_region = Graphics.RectangleGraphic()
            rect_region.bounds = (0.2, 0.2), (0.2, 0.2)
            display_item.add_graphic(rect_region)
            display_item.graphic_selection.set(0)
            histogram_panel._histogram_processor._evaluate_immediate()
            stats1_new_text = histogram_panel._statistics_widget._stats1_property.value
            stats2_new_text = histogram_panel._statistics_widget._stats2_property.value
            self.assertNotEqual(stats1_text, stats1_new_text)
            self.assertNotEqual(stats2_text, stats2_new_text)
            rect_region.bounds = (0.4, 0.4), (0.2, 0.2)
            histogram_panel._histogram_processor._evaluate_immediate()
            self.assertNotEqual(stats1_new_text, histogram_panel._statistics_widget._stats1_property.value)
            self.assertNotEqual(stats2_new_text, histogram_panel._statistics_widget._stats2_property.value)

    def test_target_region_stream_stops_updates_when_region_deselected(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(self.get_data())
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # test
            target_display_item_stream = HistogramPanel.TargetDisplayItemStream(document_controller)
            target_region_stream = HistogramPanel.TargetRegionStream(target_display_item_stream)
            with target_region_stream.ref():
                count = 0

                def new_region(graphic: Graphics.Graphic) -> None:
                    nonlocal count
                    count += 1

                with contextlib.closing(target_region_stream.value_stream.listen(new_region)):
                    rect_region = Graphics.RectangleGraphic()
                    rect_region.bounds = (0.2, 0.2), (0.2, 0.2)
                    display_item.add_graphic(rect_region)
                    display_item.graphic_selection.set(0)  # count 1
                    rect_region.bounds = (0.2, 0.2), (0.2, 0.2)  # count 2
                    display_item.graphic_selection.clear()  # count 2
                    count0 = count
                    rect_region.bounds = (0.2, 0.2), (0.2, 0.2)  # count 2
                    rect_region.bounds = (0.2, 0.2), (0.2, 0.2)  # count 2
                    rect_region.bounds = (0.2, 0.2), (0.2, 0.2)  # count 2
                    self.assertEqual(count0, count)

    def test_cursor_histogram_of_empty_data_displays_without_exception(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(self.get_data())
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # set up histogram
            histogram_panel = document_controller.find_dock_panel("histogram-panel")
            histogram_canvas_item = histogram_panel._histogram_widget._histogram_canvas_item
            document_controller.show_display_item(display_item)
            histogram_canvas_item.update_layout((0, 0), (80, 300))
            # run test
            data_item._force_unload()
            histogram_canvas_item.mouse_position_changed(80, 58, 0)

    def test_histogram_statistics_with_zero_array(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data = numpy.ones((10, 10), dtype=numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            rect_region = Graphics.RectangleGraphic()
            rect_region.bounds = (10000, 10000), (1, 1)
            display_item.add_graphic(rect_region)
            display_item.graphic_selection.set(0)
            # set up histogram
            histogram_panel = document_controller.find_dock_panel("histogram-panel")
            histogram_canvas_item = histogram_panel._histogram_widget._histogram_canvas_item
            document_controller.show_display_item(display_item)
            histogram_canvas_item.update_layout((0, 0), (80, 300))

    def test_histogram_statistics_on_slice(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data = numpy.multiply(numpy.abs(numpy.random.randn(2, 2, 20)), 100).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_data_channel = display_item.display_data_channels[0]
            display_data_channel.slice_center = 15
            display_data_channel.slice_width = 2
            # set up histogram
            histogram_panel = document_controller.find_dock_panel("histogram-panel")
            histogram_canvas_item = histogram_panel._histogram_widget._histogram_canvas_item
            document_controller.show_display_item(display_item)
            histogram_canvas_item.update_layout((0, 0), (80, 300))
            # force evaluation of the histogram statistics
            histogram_panel._histogram_processor._evaluate_immediate()
            statistics_dict = histogram_panel._histogram_processor.statistics
            self.assertAlmostEqual(float(statistics_dict["mean"]), numpy.average(numpy.sum(data[..., 14:16], -1)))
            self.assertAlmostEqual(float(statistics_dict["min"]), numpy.amin(numpy.sum(data[..., 14:16], -1)))
            self.assertAlmostEqual(float(statistics_dict["max"]), numpy.amax(numpy.sum(data[..., 14:16], -1)))

    def test_histogram_processor(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data = numpy.random.randn(16, 16)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            histogram_processor = HistogramPanel.HistogramProcessor(document_controller.event_loop)
            with contextlib.closing(histogram_processor):
                display_data_channel = display_item.display_data_channel
                display_values = display_data_channel.get_latest_computed_display_values()
                histogram_processor.display_data_and_metadata = display_values.display_data_and_metadata
                histogram_processor.display_range = display_values.display_range
                histogram_processor.display_data_range = display_values.data_range
                histogram_processor.displayed_intensity_calibration = display_item.displayed_intensity_calibration
                had_histogram = False
                had_statistics = False
                def property_changed(key: str) -> None:
                    nonlocal had_histogram, had_statistics
                    if key == "histogram_widget_data":
                        had_histogram = True
                    if key == "statistics":
                        had_statistics = True
                with contextlib.closing(histogram_processor.property_changed_event.listen(property_changed)):
                    while not had_histogram or not had_statistics:
                        document_controller.periodic()
                display_values = None


if __name__ == '__main__':
    unittest.main()
