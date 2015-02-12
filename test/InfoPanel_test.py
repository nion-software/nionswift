# standard libraries
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift import Panel
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.ui import Test


class TestInfoPanelClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_cursor_over_1d_data_displays_without_exception(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        image_panel = document_controller.selected_display_panel
        data_item = DataItem.DataItem(numpy.zeros((1000, )))
        document_model.append_data_item(data_item)
        image_panel.set_displayed_data_item(data_item)
        header_height = Panel.HeaderCanvasItem().header_height
        image_panel.canvas_item.root_container.canvas_widget.on_size_changed(1000, 1000 + header_height)
        image_panel.display_canvas_item.mouse_entered()
        image_panel.display_canvas_item.mouse_position_changed(500, 500, Graphics.NullModifiers())
        image_panel.display_canvas_item.mouse_exited()

    def test_cursor_over_3d_data_displays_without_exception(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        image_panel = document_controller.selected_display_panel
        data_item = DataItem.DataItem(numpy.zeros((8, 1000, 1000)))
        document_model.append_data_item(data_item)
        image_panel.set_displayed_data_item(data_item)
        header_height = Panel.HeaderCanvasItem().header_height
        image_panel.canvas_item.root_container.canvas_widget.on_size_changed(1000, 1000 + header_height)
        image_panel.display_canvas_item.mouse_entered()
        image_panel.display_canvas_item.mouse_position_changed(500, 500, Graphics.NullModifiers())
        image_panel.display_canvas_item.mouse_exited()
