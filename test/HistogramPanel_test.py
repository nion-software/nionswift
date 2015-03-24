# standard libraries
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift import HistogramPanel
from nion.swift.model import DataItem
from nion.swift.model import Display
from nion.swift.model import DocumentModel
from nion.swift.model import Storage
from nion.ui import Test


class TestHistogramPanelClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)
        cache_name = ":memory:"
        storage_cache = Storage.DbStorageCache(cache_name)
        self.document_model = DocumentModel.DocumentModel(storage_cache=storage_cache)
        self.document_controller = DocumentController.DocumentController(self.app.ui, self.document_model, workspace_id="library")
        self.image_panel = self.document_controller.selected_display_panel
        data = numpy.zeros((1000, 1000), dtype=numpy.uint32)
        data[:] = 200
        data[500,500] = 650
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
        self.histogram_panel = HistogramPanel.HistogramPanel(self.document_controller, "histogram-panel", None)
        self.histogram_canvas_item = self.histogram_panel._histogram_canvas_item
        self.display = self.display_specifier.display
        self.document_controller.display_data_item(self.display_specifier)
        self.histogram_canvas_item.container = CanvasItemContainer()
        self.histogram_canvas_item.update_layout((0, 0), (80, 300))

    def tearDown(self):
        self.histogram_canvas_item.close()
        self.document_controller.close()

    def test_drag_to_set_limits(self):
        self.assertEqual(self.display_specifier.display.display_range, (200, 650))
        self.assertIsNone(self.display_specifier.display.display_limits)
        self.assertEqual(self.histogram_canvas_item._get_display(), self.display_specifier.display)
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
        self.assertIsNone(self.histogram_canvas_item.histogram_data)
        self.display.get_processor("histogram").recompute_data(None)
        histogram_data1 = self.histogram_canvas_item.histogram_data
        self.assertIsNotNone(histogram_data1)
        # now change the data and verify that histogram gets recomputed via document model
        with self.display_specifier.buffered_data_source.data_ref() as data_ref:
            data_ref.master_data = numpy.ones((1000, 1000), dtype=numpy.uint32)
        self.document_model.recompute_all()
        histogram_data2 = self.histogram_canvas_item.histogram_data
        self.assertFalse(numpy.array_equal(histogram_data1, histogram_data2))

    def test_changing_source_data_marks_statistics_as_dirty_then_recomputes_via_model(self):
        # verify assumptions
        self.assertEqual(self.histogram_panel.stats1_property.value, str())
        self.assertEqual(self.histogram_panel.stats2_property.value, str())
        self.display_specifier.buffered_data_source.get_processor("statistics").recompute_data(None)
        stats1_text = self.histogram_panel.stats1_property.value
        stats2_text = self.histogram_panel.stats2_property.value
        self.assertIsNotNone(stats1_text)
        self.assertIsNotNone(stats2_text)
        # now change the data and verify that statistics gets recomputed via document model
        with self.display_specifier.buffered_data_source.data_ref() as data_ref:
            data_ref.master_data = numpy.ones((1000, 1000), dtype=numpy.uint32)
        self.document_model.recompute_all()
        self.assertNotEqual(stats1_text, self.histogram_panel.stats1_property.value)
        self.assertNotEqual(stats2_text, self.histogram_panel.stats2_property.value)

if __name__ == '__main__':
    unittest.main()
