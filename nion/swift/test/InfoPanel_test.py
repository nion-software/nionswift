# futures
from __future__ import absolute_import

# standard libraries
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift import InfoPanel
from nion.swift import Panel
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.ui import TestUI


class TestInfoPanelClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_cursor_over_1d_data_displays_without_exception(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        display_panel = document_controller.selected_display_panel
        data_item = DataItem.DataItem(numpy.zeros((1000, )))
        document_model.append_data_item(data_item)
        display_panel.set_displayed_data_item(data_item)
        header_height = Panel.HeaderCanvasItem().header_height
        display_panel.canvas_item.root_container.canvas_widget.on_size_changed(1000, 1000 + header_height)
        display_panel.display_canvas_item.mouse_entered()
        display_panel.display_canvas_item.mouse_position_changed(500, 500, Graphics.NullModifiers())
        display_panel.display_canvas_item.mouse_exited()
        document_controller.close()

    def test_cursor_over_1d_data_displays_without_exception_when_not_displaying_calibration(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        display_panel = document_controller.selected_display_panel
        data_item = DataItem.DataItem(numpy.zeros((1000, )))
        document_model.append_data_item(data_item)
        data_item.data_sources[0].displays[0].display_calibrated_values = False
        display_panel.set_displayed_data_item(data_item)
        header_height = Panel.HeaderCanvasItem().header_height
        display_panel.canvas_item.root_container.canvas_widget.on_size_changed(1000, 1000 + header_height)
        display_panel.display_canvas_item.mouse_entered()
        display_panel.display_canvas_item.mouse_position_changed(500, 500, Graphics.NullModifiers())
        display_panel.display_canvas_item.mouse_exited()
        document_controller.close()

    def test_cursor_over_1d_multiple_data_displays_without_exception(self):
        data_item = DataItem.DataItem(numpy.zeros((4, 1000)))
        p, v = InfoPanel.get_value_and_position_text(data_item.maybe_data_source.data_and_calibration, False, (500,))
        self.assertEqual(p, "500.0")
        self.assertEqual(v, "0")

    def test_cursor_over_1d_image_without_exception(self):
        data_item = DataItem.DataItem(numpy.zeros((50,)))
        p, v = InfoPanel.get_value_and_position_text(data_item.maybe_data_source.data_and_calibration, False, (0.5, 25))
        self.assertEqual(p, "25.0")
        self.assertEqual(v, "0")

    def test_cursor_over_3d_data_displays_without_exception(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        display_panel = document_controller.selected_display_panel
        data_item = DataItem.DataItem(numpy.zeros((4, 10, 10)))
        document_model.append_data_item(data_item)
        display_panel.set_displayed_data_item(data_item)
        header_height = Panel.HeaderCanvasItem().header_height
        display_panel.canvas_item.root_container.canvas_widget.on_size_changed(1000, 1000 + header_height)
        display_panel.display_canvas_item.mouse_entered()
        display_panel.display_canvas_item.mouse_position_changed(500, 500, Graphics.NullModifiers())
        display_panel.display_canvas_item.mouse_exited()
        document_controller.close()
