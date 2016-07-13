# standard libraries
import unittest

# third party libraries
import numpy

# local libraries
from nion.data import DataAndMetadata
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift import HistogramPanel
from nion.swift.model import Cache
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.ui import TestUI


class TestHistogramPanelClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)
        cache_name = ":memory:"
        storage_cache = Cache.DbStorageCache(cache_name)
        self.document_model = DocumentModel.DocumentModel(storage_cache=storage_cache)
        self.document_controller = DocumentController.DocumentController(self.app.ui, self.document_model, workspace_id="library")
        data = numpy.zeros((10, 10), dtype=numpy.uint32)
        data[:] = 200
        data[5, 5] = 650
        self.data_item = DataItem.DataItem(data)
        self.document_model.append_data_item(self.data_item)
        self.display_specifier = DataItem.DisplaySpecifier.from_data_item(self.data_item)
        # create the histogram canvas object
        class CanvasItemContainer(object):
            def __init__(self):
                self.root_container = self
                self.mouse_canvas_item = None
            def draw(self):
                pass
            def _child_updated(self, child):
                pass
        self.histogram_panel = HistogramPanel.HistogramPanel(self.document_controller, "histogram-panel", None, debounce=False, sample=False)
        self.histogram_canvas_item = self.histogram_panel._histogram_widget._histogram_canvas_item
        self.display = self.display_specifier.display
        self.document_controller.display_data_item(self.display_specifier)
        self.histogram_canvas_item.update_layout((0, 0), (80, 300))

    def tearDown(self):
        self.histogram_canvas_item.close()
        self.document_controller.close()

    def test_drag_to_set_limits(self):
        self.assertEqual(self.display_specifier.display.display_range, (200, 650))
        self.assertIsNone(self.display_specifier.display.display_limits)
        # drag
        self.histogram_canvas_item.mouse_pressed(60, 58, 0)
        self.histogram_canvas_item.mouse_position_changed(80, 58, 0)
        self.histogram_canvas_item.mouse_released(90, 58, 0)
        self.assertIsNotNone(self.display_specifier.display.display_limits)
        self.assertEqual(self.display_specifier.display.display_range, (290, 320))
        # double click and return to None
        self.histogram_canvas_item.mouse_pressed(121, 51, 0)
        self.histogram_canvas_item.mouse_released(121, 51, 0)
        self.histogram_canvas_item.mouse_pressed(121, 51, 0)
        self.histogram_canvas_item.mouse_double_clicked(121, 51, 0)
        self.histogram_canvas_item.mouse_released(121, 51, 0)
        self.assertIsNone(self.display_specifier.display.display_limits)

    def test_changing_source_data_marks_histogram_as_dirty_then_recomputes_via_model(self):
        # verify assumptions
        histogram_data1 = self.histogram_canvas_item.histogram_data
        self.assertIsNotNone(histogram_data1)
        # now change the data and verify that histogram gets recomputed via document model
        with self.display_specifier.buffered_data_source.data_ref() as data_ref:
            data_ref.master_data = numpy.ones((10, 10), dtype=numpy.uint32)
        self.histogram_panel._histogram_widget._recompute()
        histogram_data2 = self.histogram_canvas_item.histogram_data
        self.assertFalse(numpy.array_equal(histogram_data1, histogram_data2))

    def test_changing_source_data_marks_statistics_as_dirty_then_recomputes_via_model(self):
        # verify assumptions
        stats1_text = self.histogram_panel._statistics_widget._stats1_property.value
        stats2_text = self.histogram_panel._statistics_widget._stats2_property.value
        self.assertIsNotNone(stats1_text)
        self.assertIsNotNone(stats2_text)
        # now change the data and verify that statistics gets recomputed via document model
        with self.display_specifier.buffered_data_source.data_ref() as data_ref:
            data_ref.master_data = numpy.ones((10, 10), dtype=numpy.uint32)
        self.assertNotEqual(stats1_text, self.histogram_panel._statistics_widget._stats1_property.value)
        self.assertNotEqual(stats2_text, self.histogram_panel._statistics_widget._stats2_property.value)

    def test_cursor_histogram_of_empty_data_displays_without_exception(self):
        self.data_item.maybe_data_source.set_data_and_calibration(DataAndMetadata.DataAndMetadata(lambda: None, ((0, 0), numpy.float)))
        self.histogram_canvas_item.mouse_position_changed(80, 58, 0)

    def test_histogram_statistics_with_zero_array(self):
        with self.display_specifier.buffered_data_source.data_ref() as data_ref:
            data_ref.master_data = numpy.ones((10, 10), dtype=numpy.uint32)
        rect_region = Graphics.RectangleGraphic()
        rect_region.bounds = (10000, 10000), (10001, 10001)
        self.display_specifier.display.add_graphic(rect_region)
        self.display_specifier.display.graphic_selection.set(0)
        self.histogram_panel._histogram_widget._recompute()

if __name__ == '__main__':
    unittest.main()
