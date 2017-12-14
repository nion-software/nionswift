# standard libraries
import contextlib
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift import Panel
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.ui import TestUI


class TestImageCanvasItemClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_mapping_widget_to_image_on_2d_data_stack_uses_signal_dimensions(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            document_controller.selected_display_panel.change_display_panel_content({"type": "image"})
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((50, 10, 10)), data_descriptor=DataAndMetadata.DataDescriptor(True, 0, 2))
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((100 + header_height, 100))
            # run test
            document_controller.tool_mode = "line-profile"
            display_panel.display_canvas_item.simulate_drag((20,25), (65,85))
            self.assertEqual(data_item.displays[0].graphics[0].vector, ((0.2, 0.25), (0.65, 0.85)))

    def test_mapping_widget_to_image_on_3d_spectrum_image_uses_collection_dimensions(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            document_controller.selected_display_panel.change_display_panel_content({"type": "image"})
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((10, 10, 50)), data_descriptor=DataAndMetadata.DataDescriptor(False, 2, 1))
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((100 + header_height, 100))
            # run test
            document_controller.tool_mode = "line-profile"
            display_panel.display_canvas_item.simulate_drag((20,25), (65,85))
            self.assertEqual(data_item.displays[0].graphics[0].vector, ((0.2, 0.25), (0.65, 0.85)))

    def test_dimension_used_for_scale_marker_on_2d_data_stack_is_correct(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            calibrations = [Calibration.Calibration(units="s"), Calibration.Calibration(units="y"), Calibration.Calibration(units="x")]
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((50, 10, 10)), dimensional_calibrations=calibrations, data_descriptor=DataAndMetadata.DataDescriptor(True, 0, 2))
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            # run test
            self.assertEqual(display_panel.display_canvas_item._info_overlay_canvas_item_for_test._dimension_calibration_for_test.units, "x")

    def test_dimension_used_for_scale_marker_on_3d_spectrum_image_is_correct(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            calibrations = [Calibration.Calibration(units="y"), Calibration.Calibration(units="x"), Calibration.Calibration(units="e")]
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((10, 10, 50)), dimensional_calibrations=calibrations, data_descriptor=DataAndMetadata.DataDescriptor(False, 2, 1))
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            # run test
            self.assertEqual(display_panel.display_canvas_item._info_overlay_canvas_item_for_test._dimension_calibration_for_test.units, "x")

    def test_tool_returns_to_pointer_after_but_not_during_creating_rectangle(self):
        # setup
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            # run test
            self.assertEqual(document_controller.tool_mode, "pointer")
            for tool_mode in ["rectangle", "point", "ellipse", "line"]:
                document_controller.tool_mode = tool_mode
                display_panel.display_canvas_item.simulate_press((100,125))
                display_panel.display_canvas_item.simulate_move((100,125))
                self.assertEqual(document_controller.tool_mode, tool_mode)
                display_panel.display_canvas_item.simulate_move((250,200))
                display_panel.display_canvas_item.simulate_release((250,200))
                self.assertEqual(document_controller.tool_mode, "pointer")

    def test_selected_item_takes_priority_over_all_part(self):
        # setup
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            # run test
            rect_region = Graphics.RectangleGraphic()
            rect_region.bounds = (0.25, 0.25), (0.5, 0.5)
            line_region = Graphics.LineGraphic()
            line_region.start = (0.0, 1.0)
            line_region.end = (0.75, 0.25)
            # draws line, then rect
            data_item.displays[0].add_graphic(line_region)
            data_item.displays[0].add_graphic(rect_region)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_panel.display_canvas_item.simulate_click((50, 950))
            self.assertEqual(display_specifier.display.graphic_selection.indexes, set((0, )))
            display_panel.display_canvas_item.simulate_click((500, 500))
            self.assertEqual(display_specifier.display.graphic_selection.indexes, set((0, )))

    def test_specific_parts_take_priority_over_all_part(self):
        # setup
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            # run test
            rect_region = Graphics.RectangleGraphic()
            rect_region.bounds = (0.25, 0.25), (0.5, 0.5)
            line_region = Graphics.LineGraphic()
            line_region.start = (0.5, 0.5)
            line_region.end = (0.5, 1.0)
            # draws line, then rect
            data_item.displays[0].add_graphic(line_region)
            data_item.displays[0].add_graphic(rect_region)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            # clicking on line should select it
            display_panel.display_canvas_item.simulate_click((500, 600))
            self.assertEqual(display_specifier.display.graphic_selection.indexes, set((0, )))

    def test_specific_parts_take_priority_when_another_selected(self):
        # setup
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            # run test
            rect_region1 = Graphics.RectangleGraphic()
            rect_region1.bounds = (0.2, 0.2), (0.4, 0.4)
            rect_region2 = Graphics.RectangleGraphic()
            rect_region2.bounds = (0.4, 0.4), (0.4, 0.4)
            data_item.displays[0].add_graphic(rect_region1)
            data_item.displays[0].add_graphic(rect_region2)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            # clicking on line should select it
            display_panel.display_canvas_item.simulate_click((700, 700))
            self.assertEqual(display_specifier.display.graphic_selection.indexes, set((1, )))
            display_panel.display_canvas_item.simulate_click((600, 200))
            self.assertEqual(display_specifier.display.graphic_selection.indexes, set((0, )))

    def test_hit_testing_occurs_same_as_draw_order(self):
        # draw order occurs from 0 -> n
        # setup
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            # run test
            rect_region1 = Graphics.RectangleGraphic()
            rect_region1.bounds = (0.2, 0.2), (0.4, 0.4)
            rect_region2 = Graphics.RectangleGraphic()
            rect_region2.bounds = (0.4, 0.4), (0.4, 0.4)
            data_item.displays[0].add_graphic(rect_region1)
            data_item.displays[0].add_graphic(rect_region2)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_panel.display_canvas_item.simulate_click((500, 500))
            self.assertEqual(display_specifier.display.graphic_selection.indexes, set((1, )))

    def test_1d_data_displayed_as_2d(self):
        # setup
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, )))
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            DataItem.DisplaySpecifier.from_data_item(data_item).display.display_type = "image"
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
