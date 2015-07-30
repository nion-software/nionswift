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
from nion.swift import ImageCanvasItem
from nion.swift import Panel
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.ui import Geometry
from nion.ui import Test


class TestImageCanvasItemClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    # make sure we can remove a single operation
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

    # make sure we can remove a single operation
    def test_tool_returns_to_pointer_after_but_not_during_creating_rectangle(self):
        # setup
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
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

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
