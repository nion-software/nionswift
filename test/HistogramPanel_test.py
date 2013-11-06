# standard libraries
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DataItem
from nion.swift import DocumentController
from nion.swift import DocumentModel
from nion.swift import HistogramPanel
from nion.swift import ImagePanel
from nion.swift import Storage
from nion.swift import Test


class TestHistogramPanelClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)
        db_name = ":memory:"
        storage_writer = Storage.DbStorageWriter(db_name, db_name, create=True)
        document_model = DocumentModel.DocumentModel(storage_writer)
        self.document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.document_controller.document_model.create_default_data_groups()
        default_data_group = self.document_controller.document_model.data_groups[0]
        self.image_panel = self.document_controller.selected_image_panel
        self.image_panel.image_canvas.width = 1000
        self.image_panel.image_canvas.height = 1000
        data = numpy.zeros((1000, 1000), dtype=numpy.uint32)
        data[:] = 200
        data[500,500] = 650
        self.data_item = self.document_controller.document_model.set_data_by_key("test", data)
        self.data_item.add_ref()
        with self.data_item.create_data_accessor() as data_accessor:
            data_accessor.data  # trigger data loading
        # create the histogram panel
        self.histogram_panel = HistogramPanel.HistogramPanel(self.document_controller, "histogram", None)
        self.histogram_panel.canvas.width = 300
        self.histogram_panel.canvas.height = 80
        self.histogram_panel._set_data_item(self.data_item)

    def tearDown(self):
        self.data_item.remove_ref()
        self.image_panel.close()
        self.histogram_panel.close()
        self.document_controller.close()

    def test_drag_to_set_limits(self):
        self.assertEqual(self.data_item.display_range, (200, 650))
        self.assertIsNone(self.data_item.display_limits)
        self.assertEqual(self.histogram_panel._get_data_item(), self.data_item)
        # drag
        self.histogram_panel.mouse_pressed(60, 58, 0)
        self.histogram_panel.mouse_position_changed(80, 58, 0)
        self.histogram_panel.mouse_released(90, 58, 0)
        self.assertIsNotNone(self.data_item.display_limits)
        self.assertEqual(self.data_item.display_range, (290, 320))
        # double click and return to None
        self.histogram_panel.mouse_pressed(121, 51, 0)
        self.histogram_panel.mouse_released(121, 51, 0)
        self.histogram_panel.mouse_pressed(121, 51, 0)
        self.histogram_panel.mouse_double_clicked(121, 51, 0)
        self.histogram_panel.mouse_released(121, 51, 0)
        self.assertIsNone(self.data_item.display_limits)

if __name__ == '__main__':
    unittest.main()
