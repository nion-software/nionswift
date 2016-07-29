# futures
from __future__ import absolute_import

# standard libraries
import contextlib
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift import ImageCanvasItem
from nion.swift import Panel
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.ui import TestUI
from nion.utils import Geometry


class TestImageCanvasItemClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_mapping_widget_to_image_on_3d_data_uses_last_two_dimensions(self):
        canvas_size = Geometry.FloatSize(100, 100)
        canvas_origin = Geometry.FloatPoint(0, 0)
        dimensional_size = (256, 16, 16)
        widget_mapping = ImageCanvasItem.ImageCanvasItemMapping(dimensional_size, canvas_origin, canvas_size)
        # image_norm_to_widget
        image_norm_point = Geometry.FloatPoint(0.5, 0.5)
        widget_point = widget_mapping.map_point_image_norm_to_widget(image_norm_point)
        self.assertEqual(widget_point, Geometry.FloatPoint(50, 50))
        # widget_to_image
        self.assertEqual(widget_mapping.map_point_widget_to_image(Geometry.FloatPoint(50, 50)), Geometry.FloatPoint(8, 8))

    def test_tool_returns_to_pointer_after_but_not_during_creating_rectangle(self):
        # setup
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_panel.set_displayed_data_item(data_item)
            header_height = Panel.HeaderCanvasItem().header_height
            display_panel.canvas_item.root_container.canvas_widget.on_size_changed(1000, 1000 + header_height)
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
            display_panel.set_displayed_data_item(data_item)
            header_height = Panel.HeaderCanvasItem().header_height
            display_panel.canvas_item.root_container.canvas_widget.on_size_changed(1000, 1000 + header_height)
            # run test
            rect_region = Graphics.RectangleGraphic()
            rect_region.bounds = (0.25, 0.25), (0.5, 0.5)
            line_region = Graphics.LineGraphic()
            line_region.start = (0.0, 1.0)
            line_region.end = (0.75, 0.25)
            # draws line, then rect
            data_item.maybe_data_source.displays[0].add_graphic(line_region)
            data_item.maybe_data_source.displays[0].add_graphic(rect_region)
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
            display_panel.set_displayed_data_item(data_item)
            header_height = Panel.HeaderCanvasItem().header_height
            display_panel.canvas_item.root_container.canvas_widget.on_size_changed(1000, 1000 + header_height)
            # run test
            rect_region = Graphics.RectangleGraphic()
            rect_region.bounds = (0.25, 0.25), (0.5, 0.5)
            line_region = Graphics.LineGraphic()
            line_region.start = (0.5, 0.5)
            line_region.end = (0.5, 1.0)
            # draws line, then rect
            data_item.maybe_data_source.displays[0].add_graphic(line_region)
            data_item.maybe_data_source.displays[0].add_graphic(rect_region)
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
            display_panel.set_displayed_data_item(data_item)
            header_height = Panel.HeaderCanvasItem().header_height
            display_panel.canvas_item.root_container.canvas_widget.on_size_changed(1000, 1000 + header_height)
            # run test
            rect_region1 = Graphics.RectangleGraphic()
            rect_region1.bounds = (0.2, 0.2), (0.4, 0.4)
            rect_region2 = Graphics.RectangleGraphic()
            rect_region2.bounds = (0.4, 0.4), (0.4, 0.4)
            data_item.maybe_data_source.displays[0].add_graphic(rect_region1)
            data_item.maybe_data_source.displays[0].add_graphic(rect_region2)
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
            display_panel.set_displayed_data_item(data_item)
            header_height = Panel.HeaderCanvasItem().header_height
            display_panel.canvas_item.root_container.canvas_widget.on_size_changed(1000, 1000 + header_height)
            # run test
            rect_region1 = Graphics.RectangleGraphic()
            rect_region1.bounds = (0.2, 0.2), (0.4, 0.4)
            rect_region2 = Graphics.RectangleGraphic()
            rect_region2.bounds = (0.4, 0.4), (0.4, 0.4)
            data_item.maybe_data_source.displays[0].add_graphic(rect_region1)
            data_item.maybe_data_source.displays[0].add_graphic(rect_region2)
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
            display_panel.set_displayed_data_item(data_item)
            DataItem.DisplaySpecifier.from_data_item(data_item).display.display_type = "image"
            header_height = Panel.HeaderCanvasItem().header_height
            display_panel.canvas_item.root_container.canvas_widget.on_size_changed(1000, 1000 + header_height)

    def test_move_with_pointer_defaults_to_drag(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_panel.set_displayed_data_item(data_item)
            header_height = Panel.HeaderCanvasItem().header_height
            display_panel.canvas_item.root_container.canvas_widget.on_size_changed(1000, 1000 + header_height)
            display_panel.display_canvas_item.simulate_press((100, 125))
            display_panel.display_canvas_item.simulate_move((100, 125))
            display_panel.display_canvas_item.simulate_move((200, 125))
            display_panel.display_canvas_item.simulate_release((200, 125))
            self.assertEqual(display_panel.display_canvas_item.scroll_area_canvas_item.visible_rect[0][0], -100)

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
