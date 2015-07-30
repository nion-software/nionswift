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
from nion.swift import Panel
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import LineGraphCanvasItem
from nion.swift.model import Region
from nion.ui import Test


class TestLineGraphCanvasItem(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_data_values_give_pretty_limits_when_auto(self):

        test_ranges = (
            ((7.46, 85.36), (0.0, 100.0)),
            ((7.67, 12.95), (0.0, 15.0)),
            ((6.67, 11.95), (0.0, 15.0)),
            ((0.00, 0.00), (0.0, 0.0))
        )

        for data_in, data_out in test_ranges:
            data_min, data_max = data_in
            expected_uncalibrated_data_min, expected_uncalibrated_data_max = data_out
            data = numpy.zeros((16, 16), dtype=numpy.float64)
            irow, icol = numpy.ogrid[0:16, 0:16]
            data[:] = data_min + (data_max - data_min) * (irow / 15.0)
            # auto on min/max
            data_info = LineGraphCanvasItem.LineGraphDataInfo(lambda: data, None, None)
            self.assertEqual(data_info.y_properties.uncalibrated_data_min, expected_uncalibrated_data_min)
            self.assertEqual(data_info.y_properties.uncalibrated_data_max, expected_uncalibrated_data_max)

    def test_tool_returns_to_pointer_after_but_not_during_creating_interval(self):
        # setup
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        display_panel = document_controller.selected_display_panel
        data_item = DataItem.DataItem(numpy.zeros((100,)))
        document_model.append_data_item(data_item)
        display_panel.set_displayed_data_item(data_item)
        header_height = Panel.HeaderCanvasItem().header_height
        display_panel.canvas_item.root_container.canvas_widget.on_size_changed(1000, 1000 + header_height)
        # run test
        self.assertEqual(document_controller.tool_mode, "pointer")
        for tool_mode in ["interval"]:
            document_controller.tool_mode = tool_mode
            display_panel.display_canvas_item.simulate_press((100,125))
            display_panel.display_canvas_item.simulate_move((100,125))
            self.assertEqual(document_controller.tool_mode, tool_mode)
            display_panel.display_canvas_item.simulate_move((250,200))
            display_panel.display_canvas_item.simulate_release((250,200))
            self.assertEqual(document_controller.tool_mode, "pointer")

    def test_pointer_tool_makes_intervals(self):
        # setup
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        display_panel = document_controller.selected_display_panel
        data_item = DataItem.DataItem(numpy.zeros((100,)))
        document_model.append_data_item(data_item)
        display_panel.set_displayed_data_item(data_item)
        display_panel.display_canvas_item.update_layout((0, 0), (640, 480))
        display_panel.display_canvas_item.prepare_display()  # force layout
        # test
        document_controller.tool_mode = "pointer"
        display_panel.display_canvas_item.simulate_drag((240, 160), (240, 480))
        interval_region = data_item.maybe_data_source.regions[0]
        self.assertEqual(interval_region.type, "interval-region")
        self.assertTrue(interval_region.end > interval_region.start)

    def test_pointer_tool_makes_intervals_when_other_intervals_exist(self):
        # setup
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        display_panel = document_controller.selected_display_panel
        data_item = DataItem.DataItem(numpy.zeros((100,)))
        region = Region.IntervalRegion()
        region.start = 0.9
        region.end = 0.95
        data_item.maybe_data_source.add_region(region)
        document_model.append_data_item(data_item)
        display_panel.set_displayed_data_item(data_item)
        display_panel.display_canvas_item.update_layout((0, 0), (640, 480))
        display_panel.display_canvas_item.prepare_display()  # force layout
        # test
        document_controller.tool_mode = "pointer"
        display_panel.display_canvas_item.simulate_drag((240, 160), (240, 480))
        interval_region = data_item.maybe_data_source.regions[1]
        self.assertEqual(interval_region.type, "interval-region")
        self.assertTrue(interval_region.end > interval_region.start)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
