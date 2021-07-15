# standard libraries
import contextlib
import unittest

# third party libraries
import numpy

# local libraries
from nion.data import DataAndMetadata
from nion.swift import HistogramPanel
from nion.swift.model import DataItem
from nion.swift.model import Graphics
from nion.swift.test import TestContext


class TestHistogramPanelClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self.test_context = TestContext.create_memory_context()
        self.document_controller = self.test_context.create_document_controller_with_application()
        self.document_model = self.document_controller.document_model
        data = numpy.full((10, 10), 200, dtype=numpy.uint32)
        data[5, 5] = 650
        self.data_item = DataItem.DataItem(data)
        self.document_model.append_data_item(self.data_item)
        self.display_item = self.document_model.get_display_item_for_data_item(self.data_item)
        self.histogram_panel = HistogramPanel.HistogramPanel(self.document_controller, "histogram-panel", None, debounce=False, sample=False)
        self.histogram_canvas_item = self.histogram_panel._histogram_widget._histogram_canvas_item
        self.document_controller.show_display_item(self.display_item)
        self.histogram_canvas_item.update_layout((0, 0), (80, 300), immediate=True)

    def tearDown(self):
        self.histogram_panel.close()
        self.test_context.close()
        TestContext.end_leaks(self)

    def test_drag_to_set_limits(self):
        display_data_channel = self.display_item.display_data_channels[0]
        self.assertEqual(display_data_channel.get_calculated_display_values(True).display_range, (200, 650))
        self.assertIsNone(display_data_channel.display_limits)
        self.histogram_panel._histogram_widget._histogram_data_func_value_model._run_until_complete()
        # drag
        self.histogram_canvas_item.mouse_pressed(60, 58, 0)
        self.histogram_canvas_item.mouse_position_changed(80, 58, 0)
        self.histogram_canvas_item.mouse_released(90, 58, 0)
        self.assertIsNotNone(display_data_channel.display_limits)
        self.assertEqual(display_data_channel.get_calculated_display_values(True).display_range, (290, 320))
        # double click and return to None
        self.histogram_canvas_item.mouse_pressed(121, 51, 0)
        self.histogram_canvas_item.mouse_released(121, 51, 0)
        self.histogram_canvas_item.mouse_pressed(121, 51, 0)
        self.histogram_canvas_item.mouse_double_clicked(121, 51, 0)
        self.histogram_canvas_item.mouse_released(121, 51, 0)
        self.assertIsNone(display_data_channel.display_limits)
        self.assertEqual(display_data_channel.get_calculated_display_values(True).display_range, (200, 650))

    def test_changing_source_data_marks_histogram_as_dirty_then_recomputes_via_model(self):
        # verify assumptions
        # wait for histogram task to be complete
        self.histogram_panel._histogram_widget._histogram_data_func_value_model._run_until_complete()
        histogram_data1 = self.histogram_canvas_item.histogram_data
        self.assertIsNotNone(histogram_data1)
        # now change the data and verify that histogram gets recomputed via document model
        self.display_item.data_item.set_data(numpy.ones((10, 10), dtype=numpy.uint32))
        # wait for histogram task to be complete
        self.histogram_panel._histogram_widget._histogram_data_func_value_model._run_until_complete()
        histogram_data2 = self.histogram_canvas_item.histogram_data
        self.assertFalse(numpy.array_equal(histogram_data1, histogram_data2))

    def test_changing_source_data_marks_statistics_as_dirty_then_recomputes_via_model(self):
        # verify assumptions
        stats1_text = self.histogram_panel._statistics_widget._stats1_property.value
        stats2_text = self.histogram_panel._statistics_widget._stats2_property.value
        self.assertIsNotNone(stats1_text)
        self.assertIsNotNone(stats2_text)
        # now change the data and verify that statistics gets recomputed via document model
        self.display_item.data_item.set_data(numpy.ones((10, 10), dtype=numpy.uint32))
        # wait for statistics task to be complete
        self.histogram_panel._statistics_widget._statistics_func_value_model._run_until_complete()
        self.assertNotEqual(stats1_text, self.histogram_panel._statistics_widget._stats1_property.value)
        self.assertNotEqual(stats2_text, self.histogram_panel._statistics_widget._stats2_property.value)

    def test_histogram_updates_when_crop_region_changes(self):
        data = numpy.zeros((100, 100))
        data[20:40, 20:40] = 1
        data[40:60, 40:60] = 2
        self.display_item.data_item.set_data(data)
        self.histogram_panel._statistics_widget._statistics_func_value_model._run_until_complete()
        stats1_text = self.histogram_panel._statistics_widget._stats1_property.value
        stats2_text = self.histogram_panel._statistics_widget._stats2_property.value
        rect_region = Graphics.RectangleGraphic()
        rect_region.bounds = (0.2, 0.2), (0.2, 0.2)
        self.display_item.add_graphic(rect_region)
        self.display_item.graphic_selection.set(0)
        self.histogram_panel._statistics_widget._statistics_func_value_model._run_until_complete()
        stats1_new_text = self.histogram_panel._statistics_widget._stats1_property.value
        stats2_new_text = self.histogram_panel._statistics_widget._stats2_property.value
        self.assertNotEqual(stats1_text, stats1_new_text)
        self.assertNotEqual(stats2_text, stats2_new_text)
        rect_region.bounds = (0.4, 0.4), (0.2, 0.2)
        self.histogram_panel._statistics_widget._statistics_func_value_model._run_until_complete()
        self.assertNotEqual(stats1_new_text, self.histogram_panel._statistics_widget._stats1_property.value)
        self.assertNotEqual(stats2_new_text, self.histogram_panel._statistics_widget._stats2_property.value)

    def test_target_region_stream_stops_updates_when_region_deselected(self):
        target_display_item_stream = HistogramPanel.TargetDisplayItemStream(self.document_controller)
        target_region_stream = HistogramPanel.TargetRegionStream(target_display_item_stream).add_ref()
        try:
            count = 0
            def new_region(graphic: Graphics.Graphic) -> None:
                nonlocal count
                count += 1

            with contextlib.closing(target_region_stream.value_stream.listen(new_region)):
                rect_region = Graphics.RectangleGraphic()
                rect_region.bounds = (0.2, 0.2), (0.2, 0.2)
                self.display_item.add_graphic(rect_region)
                self.display_item.graphic_selection.set(0)  # count 1
                rect_region.bounds = (0.2, 0.2), (0.2, 0.2)  # count 2
                self.display_item.graphic_selection.clear()  # count 2
                count0 = count
                rect_region.bounds = (0.2, 0.2), (0.2, 0.2)  # count 2
                rect_region.bounds = (0.2, 0.2), (0.2, 0.2)  # count 2
                rect_region.bounds = (0.2, 0.2), (0.2, 0.2)  # count 2
                self.assertEqual(count0, count)

        finally:
            target_region_stream.remove_ref()

    def test_cursor_histogram_of_empty_data_displays_without_exception(self):
        self.data_item.set_xdata(DataAndMetadata.DataAndMetadata(lambda: None, ((0, 0), float)))
        self.histogram_canvas_item.mouse_position_changed(80, 58, 0)

    def test_histogram_statistics_with_zero_array(self):
        self.display_item.data_item.set_data(numpy.ones((10, 10), dtype=numpy.uint32))
        rect_region = Graphics.RectangleGraphic()
        rect_region.bounds = (10000, 10000), (1, 1)
        self.display_item.add_graphic(rect_region)
        self.display_item.graphic_selection.set(0)
        self.histogram_panel._histogram_widget._recompute()

    def test_histogram_statistics_on_slice(self):
        data = numpy.multiply(numpy.abs(numpy.random.randn(2, 2, 20)), 100).astype(numpy.uint32)
        self.display_item.data_item.set_data(data)
        display_data_channel = self.display_item.display_data_channels[0]
        display_data_channel.slice_center = 15
        display_data_channel.slice_width = 2
        # get the values twice: one to finish anything pending, and one to get the correct values
        statistics_dict = self.histogram_panel._statistics_widget._statistics_func_value_model._evaluate_immediate()
        self.assertAlmostEqual(float(statistics_dict["mean"]), numpy.average(numpy.sum(data[..., 14:16], -1)))
        self.assertAlmostEqual(float(statistics_dict["min"]), numpy.amin(numpy.sum(data[..., 14:16], -1)))
        self.assertAlmostEqual(float(statistics_dict["max"]), numpy.amax(numpy.sum(data[..., 14:16], -1)))

if __name__ == '__main__':
    unittest.main()
