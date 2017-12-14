# standard libraries
import contextlib
import unittest

# third party libraries
import numpy

# local libraries
from nion.data import DataAndMetadata
from nion.swift import Application
from nion.swift import DocumentController
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
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((1000, )))
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            display_panel.display_canvas_item.mouse_entered()
            display_panel.display_canvas_item.mouse_position_changed(500, 500, Graphics.NullModifiers())
            display_panel.display_canvas_item.mouse_exited()

    def test_cursor_over_1d_data_displays_without_exception_when_not_displaying_calibration(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((1000, )))
            document_model.append_data_item(data_item)
            data_item.displays[0].dimensional_calibration_style = "relative-top-left"
            display_panel.set_display_panel_data_item(data_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            display_panel.display_canvas_item.mouse_entered()
            display_panel.display_canvas_item.mouse_position_changed(500, 500, Graphics.NullModifiers())
            display_panel.display_canvas_item.mouse_exited()

    def test_cursor_over_1d_multiple_data_displays_without_exception(self):
        data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.zeros((4, 1000), numpy.float64), data_descriptor=DataAndMetadata.DataDescriptor(False, 1, 1))
        data_item = DataItem.new_data_item(data_and_metadata)
        display = DataItem.DisplaySpecifier.from_data_item(data_item).display
        display.dimensional_calibration_style = "pixels-top-left"
        p, v = display.get_value_and_position_text((500,))
        self.assertEqual(p, "500.0, 0.0")
        self.assertEqual(v, "0")

    def test_cursor_over_1d_multiple_data_but_2_datum_dimensions_displays_without_exception(self):
        data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.zeros((4, 1000), numpy.float64), data_descriptor=DataAndMetadata.DataDescriptor(False, 0, 2))
        data_item = DataItem.new_data_item(data_and_metadata)
        display = DataItem.DisplaySpecifier.from_data_item(data_item).display
        display.dimensional_calibration_style = "pixels-top-left"
        p, v = display.get_value_and_position_text((500,))
        self.assertEqual(p, "500.0, 0.0")
        self.assertEqual(v, "0")

    def test_cursor_over_1d_sequence_data_displays_without_exception(self):
        data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.zeros((4, 1000), numpy.float64), data_descriptor=DataAndMetadata.DataDescriptor(True, 0, 1))
        data_item = DataItem.new_data_item(data_and_metadata)
        display = DataItem.DisplaySpecifier.from_data_item(data_item).display
        display.dimensional_calibration_style = "pixels-top-left"
        p, v = display.get_value_and_position_text((500,))
        self.assertEqual(p, "500.0, 0.0")
        self.assertEqual(v, "0")

    def test_cursor_over_1d_image_without_exception(self):
        data_item = DataItem.DataItem(numpy.zeros((50,)))
        display = DataItem.DisplaySpecifier.from_data_item(data_item).display
        display.dimensional_calibration_style = "pixels-top-left"
        p, v = display.get_value_and_position_text((25, ))
        self.assertEqual(p, "25.0")
        self.assertEqual(v, "0")

    def test_cursor_over_3d_data_displays_without_exception(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10, 4)))
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            display_panel.display_canvas_item.mouse_entered()
            display_panel.display_canvas_item.mouse_position_changed(500, 500, Graphics.NullModifiers())
            display_panel.display_canvas_item.mouse_exited()

    def test_cursor_over_3d_data_displays_correct_ordering_of_indices(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.ones((100, 100, 20)))
            data_item.displays[0].dimensional_calibration_style = "pixels-top-left"
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            header_height = display_panel.header_canvas_item.header_height
            info_panel = document_controller.find_dock_widget("info-panel").panel
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            display_panel.display_canvas_item.mouse_entered()
            display_panel.display_canvas_item.mouse_position_changed(500, 500, Graphics.NullModifiers())
            document_controller.periodic()
            self.assertEqual(info_panel.label_row_1.text, "Position: 0.0, 50.0, 50.0")
            self.assertEqual(info_panel.label_row_2.text, "Value: 1")
            self.assertIsNone(info_panel.label_row_3.text, None)
            display_panel.display_canvas_item.mouse_exited()

    def test_cursor_over_2d_data_sequence_displays_correct_ordering_of_indices(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((20, 100, 100), numpy.float64), data_descriptor=DataAndMetadata.DataDescriptor(True, 0, 2))
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            display = DataItem.DisplaySpecifier.from_data_item(data_item).display
            display.sequence_index = 4
            display.dimensional_calibration_style = "pixels-top-left"
            display_panel.set_display_panel_data_item(data_item)
            header_height = display_panel.header_canvas_item.header_height
            info_panel = document_controller.find_dock_widget("info-panel").panel
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            display_panel.display_canvas_item.mouse_entered()
            document_controller.periodic()
            display_panel.display_canvas_item.mouse_position_changed(500, 500, Graphics.NullModifiers())
            document_controller.periodic()
            self.assertEqual(info_panel.label_row_1.text, "Position: 50.0, 50.0, 4.0")
            self.assertEqual(info_panel.label_row_2.text, "Value: 1")
            self.assertIsNone(info_panel.label_row_3.text, None)
            display_panel.display_canvas_item.mouse_exited()

    def test_cursor_over_4d_data_displays_correctly(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data = (numpy.random.randn(100, 100, 20, 20) * 100).astype(numpy.int32)
            data_item = DataItem.DataItem(data)
            display = data_item.displays[0]
            display.dimensional_calibration_style = "pixels-top-left"
            display.collection_index = 20, 30
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            header_height = display_panel.header_canvas_item.header_height
            info_panel = document_controller.find_dock_widget("info-panel").panel
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            display_panel.display_canvas_item.mouse_entered()
            display_panel.display_canvas_item.mouse_position_changed(400, 600, Graphics.NullModifiers())
            document_controller.periodic()
            self.assertEqual(info_panel.label_row_1.text, "Position: 8.0, 12.0, 30.0, 20.0")
            self.assertEqual(info_panel.label_row_2.text, "Value: {}".format(data[20, 30, 12, 8]))
            self.assertIsNone(info_panel.label_row_3.text, None)
            display_panel.display_canvas_item.mouse_exited()
