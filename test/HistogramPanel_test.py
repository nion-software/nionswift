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
        document_model = DocumentModel.DocumentModel(storage_cache=storage_cache)
        self.document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.image_panel = self.document_controller.selected_image_panel
        data = numpy.zeros((1000, 1000), dtype=numpy.uint32)
        data[:] = 200
        data[500,500] = 650
        self.data_item = self.document_controller.document_model.set_data_by_key("test", data)
        with self.data_item.data_ref() as data_ref:
            data_ref.data  # trigger data loading
        # create the histogram canvas object
        class CanvasItemContainer(object):
            def __init__(self):
                self.root_container = self
                self.mouse_canvas_item = None
            def draw(self):
                pass
            def _child_updated(self, child):
                pass
        self.histogram_canvas_item = HistogramPanel.HistogramCanvasItem()
        self.display = self.data_item.displays[0]
        self.histogram_canvas_item.update_display(self.display)
        self.histogram_canvas_item.container = CanvasItemContainer()
        self.histogram_canvas_item.update_layout((0, 0), (80, 300))

    def tearDown(self):
        self.image_panel.close()
        self.histogram_canvas_item.close()
        self.document_controller.close()

    def test_drag_to_set_limits(self):
        self.assertEqual(self.data_item.displays[0].display_range, (200, 650))
        self.assertIsNone(self.data_item.displays[0].display_limits)
        self.assertEqual(self.histogram_canvas_item._get_display().data_item, self.data_item)
        # drag
        self.histogram_canvas_item.mouse_pressed(60, 58, 0)
        self.histogram_canvas_item.mouse_position_changed(80, 58, 0)
        self.histogram_canvas_item.mouse_released(90, 58, 0)
        self.assertIsNotNone(self.data_item.displays[0].display_limits)
        self.assertEqual(self.data_item.displays[0].display_range, (290, 320))
        # double click and return to None
        self.histogram_canvas_item.mouse_pressed(121, 51, 0)
        self.histogram_canvas_item.mouse_released(121, 51, 0)
        self.histogram_canvas_item.mouse_pressed(121, 51, 0)
        self.histogram_canvas_item.mouse_double_clicked(121, 51, 0)
        self.histogram_canvas_item.mouse_released(121, 51, 0)
        self.assertIsNone(self.data_item.displays[0].display_limits)

if __name__ == '__main__':
    unittest.main()
