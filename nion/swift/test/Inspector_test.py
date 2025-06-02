# standard imports
import contextlib
import locale
import logging
import math
import typing
import unittest

# third-party imports
import numpy

# local imports
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift import DisplayPanel
from nion.swift import Facade
from nion.swift import Inspector
from nion.swift import LinePlotCanvasItem
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import Graphics
from nion.swift.model import Symbolic
from nion.swift.test import TestContext
from nion.utils import Binding
from nion.utils import Converter
from nion.utils import Geometry
from nion.utils import Observable


Facade.initialize()


class TestInspectorClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self._test_setup = TestContext.TestSetup()

    def tearDown(self):
        self._test_setup = typing.cast(typing.Any, None)
        TestContext.end_leaks(self)

    def test_info_inspector_section_follows_title_change(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
            data_item.title = "Title1"
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # find the inspector panel
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()  # needed to build the inspector
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            inspector_section = inspector_panel.widget.find_widget_by_id("info_inspector_section")
            self.assertEqual(inspector_section.info_title_label.text, "Title1")
            data_item.title = "Title2"
            document_controller.periodic()  # needed to update the inspector
            self.assertEqual(inspector_section.info_title_label.text, "Title2")

    def test_display_item_title_follows_title_change_in_inspector(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
            data_item.title = "Title1"
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            inspector_section = Inspector.InfoInspectorSection(document_controller, display_item)
            with contextlib.closing(inspector_section):
                inspector_section.info_title_label.editing_finished("Title2")
                self.assertEqual("Title2", display_item.title)

    def test_display_limits_inspector_should_bind_to_display_without_errors(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # configure the inspectors
            document_controller.notify_focused_display_changed(display_item)
            document_controller.periodic()  # force UI to update
            document_controller.notify_focused_display_changed(None)

    def test_calibration_value_and_size_float_to_string_converter_works_with_display(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            converter = Inspector.CalibratedValueFloatToStringConverter(display_item, 0)
            converter.convert(0.5)
            converter = Inspector.CalibratedSizeFloatToStringConverter(display_item, 0)
            converter.convert(0.5)

    def test_adjusting_rectangle_width_should_keep_center_constant(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            rect_graphic = Graphics.RectangleGraphic()
            rect_graphic.bounds = ((0.25, 0.25), (0.5, 0.5))
            center = rect_graphic.center
            class BoolModel(Observable.Observable):
                def __init__(self) -> None:
                    super(BoolModel, self).__init__()
                    self.calibration_style_id = "relative-top-left"
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            size_width_binding = Inspector.CalibratedSizeBinding(0, display_item, Binding.TuplePropertyBinding(rect_graphic, "size", 0))
            size_width_binding.update_source("0.6")
            self.assertEqual(center, rect_graphic.center)
            rect_graphic.close()

    def test_calibration_inspector_section_binds(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            data_item.set_dimensional_calibration(0, Calibration.Calibration(offset=5.1, scale=1.2, units="mm"))
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()  # needed to build the inspector
            calibration_section = Inspector.CalibrationsInspectorSection(document_controller, display_item.display_data_channel, display_item)
            with contextlib.closing(calibration_section):
                self.assertEqual(2, len(calibration_section._dimensional_calibrations_model.items))
                dimensional_calibration_model = calibration_section._dimensional_calibrations_model.items[0]
                self.assertEqual(dimensional_calibration_model.offset_str, "5.1")
                self.assertEqual(dimensional_calibration_model.scale_str, "1.2")
                self.assertEqual(dimensional_calibration_model.units, u"mm")
                data_item.set_dimensional_calibration(0, Calibration.Calibration(offset=1.5, scale=2.1, units="mmm"))
                self.assertEqual(dimensional_calibration_model.offset_str, "1.5")
                self.assertEqual(dimensional_calibration_model.scale_str, "2.1")
                self.assertEqual(dimensional_calibration_model.units, u"mmm")
                self.assertEqual("Y", dimensional_calibration_model.axis_name)

    def test_calibration_inspector_section_follows_spatial_calibration_change(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            data_item.set_dimensional_calibration(0, Calibration.Calibration(units="mm"))
            data_item.set_dimensional_calibration(1, Calibration.Calibration(units="mm"))
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()  # needed to build the inspector
            calibration_section = Inspector.CalibrationsInspectorSection(document_controller, display_item.display_data_channel, display_item)
            with contextlib.closing(calibration_section):
                self.assertEqual(2, len(calibration_section._dimensional_calibrations_model.items))
                dimensional_calibration_model = calibration_section._dimensional_calibrations_model.items[1]
                self.assertEqual(dimensional_calibration_model.units, u"mm")
                data_item.set_dimensional_calibration(1, Calibration.Calibration(units="mmm"))
                self.assertEqual(dimensional_calibration_model.units, u"mmm")
                self.assertEqual("X", dimensional_calibration_model.axis_name)

    def test_calibration_inspector_handles_deleted_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_graphic(Graphics.RectangleGraphic())
            data_item.set_dimensional_calibration(0, Calibration.Calibration(offset=5.1, scale=1.2, units="mm"))
            inspector = Inspector.InspectorPanel(document_controller, "x", {})
            with contextlib.closing(inspector):
                display_panel = document_controller.selected_display_panel
                display_panel.set_display_panel_display_item(display_item)
                document_controller.periodic()
                document_controller.delete_display_items([display_item])

    def test_graphic_inspector_section_follows_spatial_calibration_change(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_graphic(Graphics.PointGraphic())
            display_item.calibration_style_id = "calibrated"
            display_item.data_item.set_dimensional_calibration(1, Calibration.Calibration(units="mm"))
            # find the inspector panel
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()  # needed to build the inspector
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            point_handler = inspector_panel.column.find_widget_by_id("graphics_inspector_section")._handler._graphic_handlers[0]
            x_model = point_handler._point_position_x_model
            self.assertEqual(x_model.value, "128.0 mm")
            display_item.data_item.set_dimensional_calibration(1, Calibration.Calibration(units="mmm"))
            document_controller.periodic()  # needed to update the inspector
            self.assertEqual(x_model.value, "128.0 mmm")

    def test_changing_calibration_style_to_calibrated_displays_correct_values(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((100, 100), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            point_graphic = Graphics.PointGraphic()
            display_item.add_graphic(point_graphic)
            display_item.calibration_style_id = "calibrated"
            display_item.data_item.set_dimensional_calibration(0, Calibration.Calibration(offset=-100, scale=2, units="mm"))
            display_item.data_item.set_dimensional_calibration(1, Calibration.Calibration(offset=-100, scale=2, units="mm"))
            # find the inspector panel
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()  # needed to build the inspector
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            # check the values
            point_handler = inspector_panel.column.find_widget_by_id("graphics_inspector_section")._handler._graphic_handlers[0]
            x_model = point_handler._point_position_x_model
            y_model = point_handler._point_position_y_model
            self.assertEqual(x_model.value, "0.0 mm")
            self.assertEqual(y_model.value, "0.0 mm")
            x_model.value = "-10"
            y_model.value = "20"
            document_controller.periodic()  # needed to update the inspector
            self.assertEqual(point_graphic.position, (0.6, 0.45))

    def test_graphic_inspector_section_displays_sensible_units(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_graphic(Graphics.PointGraphic())
            display_item.calibration_style_id = "calibrated"
            # find the inspector panel
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()  # needed to build the inspector
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            point_handler = inspector_panel.column.find_widget_by_id("graphics_inspector_section")._handler._graphic_handlers[0]
            x_model = point_handler._point_position_x_model
            # check the values
            display_item.data_item.set_dimensional_calibration(1, Calibration.Calibration(scale=math.sqrt(2.0), units="mm"))
            document_controller.periodic()  # needed to update the inspector
            self.assertEqual(x_model.value, "181.0 mm")
            display_item.data_item.set_dimensional_calibration(1, Calibration.Calibration(scale=math.sqrt(2.0), offset=5.55555, units="mm"))
            document_controller.periodic()  # needed to update the inspector
            self.assertEqual(x_model.value, "186.6 mm")
            display_item.data_item.set_dimensional_calibration(1, Calibration.Calibration(scale=math.sqrt(2.0)/10, units="mm"))
            document_controller.periodic()  # needed to update the inspector
            self.assertEqual(x_model.value, "18.10 mm")
            display_item.data_item.set_dimensional_calibration(1, Calibration.Calibration(scale=math.sqrt(2.0)/10, offset=0.55555, units="mm"))
            document_controller.periodic()  # needed to update the inspector
            self.assertEqual(x_model.value, "18.66 mm")
            display_item.data_item.set_dimensional_calibration(1, Calibration.Calibration(scale=-math.sqrt(2.0)/10, units="mm"))
            document_controller.periodic()  # needed to update the inspector
            self.assertEqual(x_model.value, "-18.10 mm")

    def test_graphic_inspector_display_calibrated_length_units(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((200, 100), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            line_region = Graphics.LineGraphic()
            line_region.start = (0, 0)
            line_region.end = (1, 1)
            display_item.add_graphic(line_region)
            display_item.calibration_style_id = "calibrated"
            # find the inspector panel
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()  # needed to build the inspector
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            data_item.set_dimensional_calibration(0, Calibration.Calibration(units="mm"))
            data_item.set_dimensional_calibration(1, Calibration.Calibration(units="mm"))
            document_controller.periodic()  # needed to update the inspector
            line_handler = inspector_panel.column.find_widget_by_id("graphics_inspector_section")._handler._graphic_handlers[0]
            self.assertEqual(line_handler._length_model.value, "223.607 mm")  # sqrt(100*100 + 200*200)

    def test_graphic_inspector_sets_calibrated_length_units(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((200, 100), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            line_region = Graphics.LineGraphic()
            line_region.start = (0, 0)
            line_region.end = (0.5, 0.5)
            display_item.add_graphic(line_region)
            display_item.calibration_style_id = "calibrated"
            # find the inspector panel
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()  # needed to build the inspector
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            # check the values
            data_item.set_dimensional_calibration(0, Calibration.Calibration(units="mm"))
            data_item.set_dimensional_calibration(1, Calibration.Calibration(units="mm"))
            document_controller.periodic()  # needed to update the inspector
            length_str = "{0:g}".format(math.sqrt(100 * 100 + 200 * 200))
            line_handler = inspector_panel.column.find_widget_by_id("graphics_inspector_section")._handler._graphic_handlers[0]
            length_model = line_handler._length_model
            length_model.value = length_str
            self.assertAlmostEqual(line_region.end[0], 1.0, 3)
            self.assertAlmostEqual(line_region.end[1], 1.0, 3)

    def test_graphic_inspector_sets_calibrated_angle_units(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((200, 100), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            line_region = Graphics.LineGraphic()
            line_region.start = (0, 0)
            line_region.end = (0.25, 0.5)
            display_item.add_graphic(line_region)
            display_item.calibration_style_id = "calibrated"
            # find the inspector panel
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()  # needed to build the inspector
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            # check the values
            document_controller.periodic()  # needed to update the inspector
            line_handler = inspector_panel.column.find_widget_by_id("graphics_inspector_section")._handler._graphic_handlers[0]
            angle_model = line_handler._angle_model
            self.assertEqual(-45.0, Converter.FloatToStringConverter().convert_back(angle_model.value))
            angle_model.value = "45"
            self.assertAlmostEqual(line_region.end[0], -0.25, 3)
            self.assertAlmostEqual(line_region.end[1], 0.5, 3)

    def test_graphics_inspector_uses_non_calibrated_units_for_non_uniformly_calibrated_data(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((100, 100), numpy.uint32))
            data_item.set_dimensional_calibration(0, Calibration.Calibration(offset=5.1, scale=1.2, units="mm"))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            line_region = Graphics.LineGraphic()
            display_item.add_graphic(line_region)
            display_item.calibration_style_id = "calibrated"
            # find the inspector panel
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()  # needed to build the inspector
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            # check the length inspector
            line_region.start = (0, 0)
            line_region.end = (0.4, 0.3)
            document_controller.periodic()  # needed to update the inspector
            line_handler = inspector_panel.column.find_widget_by_id("graphics_inspector_section")._handler._graphic_handlers[0]
            length_model = line_handler._length_model
            self.assertEqual("50", length_model.value)
            length_model.value = "100"
            self.assertAlmostEqual(Geometry.FloatPoint(), line_region.start)
            self.assertAlmostEqual(Geometry.FloatPoint(0.8, 0.6), line_region.end)
            # check the angle inspector
            line_region.start = (0, 0)
            line_region.end = (0.5, math.cos(math.radians(30)))
            document_controller.periodic()  # needed to update the inspector
            angle_model = line_handler._angle_model
            self.assertEqual(-30.0, Converter.FloatToStringConverter().convert_back(angle_model.value))
            angle_model.value = "-60"
            self.assertAlmostEqual(Geometry.FloatPoint(), line_region.start)
            self.assertAlmostEqual(Geometry.FloatPoint(math.cos(math.radians(30)), 0.5), line_region.end)

    def test_line_profile_inspector_display_calibrated_width_units(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((200, 100), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            line_profile = Graphics.LineProfileGraphic()
            line_profile.start = (0, 0)
            line_profile.end = (1, 1)
            line_profile.width = 10
            display_item.add_graphic(line_profile)
            display_item.calibration_style_id = "calibrated"
            # find the inspector panel
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()  # needed to build the inspector
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            data_item.set_dimensional_calibration(0, Calibration.Calibration(units="mm"))
            data_item.set_dimensional_calibration(1, Calibration.Calibration(units="mm"))
            document_controller.periodic()  # needed to update the inspector
            line_handler = inspector_panel.column.find_widget_by_id("graphics_inspector_section")._handler._graphic_handlers[0]
            self.assertEqual(line_handler._line_profile_width_model.value, "10.0 mm")

    def test_float_to_string_converter_strips_units(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.calibration_style_id = "pixels-top-left"
            converter = Inspector.CalibratedValueFloatToStringConverter(display_item, 0)
            locale.setlocale(locale.LC_ALL, '')
            self.assertAlmostEqual(converter.convert_back("0.5"), 0.5 / 256)
            self.assertAlmostEqual(converter.convert_back(".5"), 0.5 / 256)
            self.assertAlmostEqual(converter.convert_back("00.5"), 0.5 / 256)
            self.assertAlmostEqual(converter.convert_back("0.500"), 0.5 / 256)
            self.assertAlmostEqual(converter.convert_back("0.500e0"), 0.5 / 256)
            self.assertAlmostEqual(converter.convert_back("+.5"), 0.5 / 256)
            self.assertAlmostEqual(converter.convert_back("-.5"), -0.5 / 256)
            self.assertAlmostEqual(converter.convert_back("+0.5"), 0.5 / 256)
            self.assertAlmostEqual(converter.convert_back("0.5x"), 0.5 / 256)
            self.assertAlmostEqual(converter.convert_back("x0.5"), 0.0)
            self.assertAlmostEqual(converter.convert_back(" 0.5 "), 0.5 / 256)
            self.assertAlmostEqual(converter.convert_back(""), 0.0)
            self.assertAlmostEqual(converter.convert_back("  "), 0.0)
            self.assertAlmostEqual(converter.convert_back(" x"), 0.0)
            try:
                locale.setlocale(locale.LC_ALL, 'de_DE')
                self.assertAlmostEqual(converter.convert_back("0,500"), 0.5 / 256)
                self.assertAlmostEqual(converter.convert_back("0.500"), 0.5 / 256)
            except locale.Error as e:
                pass

    def test_inspector_handles_sliced_3d_data(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((32, 32, 16)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            document_controller.selected_display_panel = None
            document_controller.selected_display_panel = display_panel
            document_controller.perform_action("processing.slice_sum")
            document_model.recompute_all()
            data_item1 = document_model.data_items[1]
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            display_panel.set_display_panel_display_item(display_item1)
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            document_controller.periodic()
            self.assertTrue(len(inspector_panel._get_inspector_sections()) > 0)

    def test_line_plot_with_one_data_item_displays_inspector(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((32, )))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            self.assertEqual(1, len(display_item.display_layers))
            display_panel.set_display_panel_display_item(display_item)
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            document_controller.periodic()
            self.assertIn(Inspector.LinePlotDisplayInspectorSection, (type(i) for i in inspector_panel._get_inspector_sections()))

    def test_line_plot_with_two_data_items_displays_inspector(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((32, )))
            data_item2 = DataItem.DataItem(numpy.zeros((32, )))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2, False)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            display_item.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item2))
            display_panel.set_display_panel_display_item(display_item)
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            document_controller.periodic()
            inspector_sections = list(type(i) for i in inspector_panel._get_inspector_sections())
            self.assertIn(Inspector.LinePlotDisplayInspectorSection, inspector_sections)

    def test_line_plot_with_data_item_with_two_rows_adds_display_layer_for_each_row(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((2, 32)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            self.assertEqual(2, len(display_item.display_layers))
            # check for unique data rows and fill colors
            self.assertEqual(display_item.get_display_layer_display_data_channel(0), display_item.get_display_layer_display_data_channel(1))
            self.assertNotEqual(display_item.get_display_layer_property(0, "data_row"), display_item.get_display_layer_property(1, "data_row"))
            self.assertNotEqual(display_item.get_display_layer_property(0, "fill_color"), display_item.get_display_layer_property(1, "fill_color"))
            display_item.display_type = "image"
            self.assertEqual(1, len(display_item.display_layers))

    def test_line_plot_with_data_item_with_three_rows_adds_display_layer_for_each_row(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((3, 32)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            self.assertEqual(3, len(display_item.display_layers))
            # check for unique data rows and fill colors
            self.assertEqual(1, len({display_item.get_display_layer_display_data_channel(i) for i in range(len(display_item.display_layers))}))
            self.assertEqual(3, len({display_item.get_display_layer_property(i, "data_row") for i in range(len(display_item.display_layers))}))
            self.assertEqual(3, len({display_item.get_display_layer_property(i, "fill_color") for i in range(len(display_item.display_layers))}))

    def test_line_plot_with_one_data_items_and_two_rows_and_two_layers_displays_inspector(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((2, 32)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_display_layer_for_display_data_channel(display_item.display_data_channels[0], data_row=1)
            display_item.display_type = "line_plot"
            display_panel.set_display_panel_display_item(display_item)
            inspector_panel = typing.cast(Inspector.InspectorPanel, document_controller.find_dock_panel("inspector-panel"))
            document_controller.periodic()
            self.assertIn(Inspector.LinePlotDisplayInspectorSection, (type(i) for i in inspector_panel._get_inspector_sections()))

    def test_line_plot_with_two_data_items_interval_inspector(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((32, )))
            data_item2 = DataItem.DataItem(numpy.zeros((32, )))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2, False)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            display_item.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item2))
            display_panel.set_display_panel_display_item(display_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(240, 1000))
            display_panel.display_canvas_item.refresh_layout_immediate()
            document_controller.periodic()
            line_plot_canvas_item = display_panel.display_canvas_item
            line_plot_canvas_item._mouse_dragged(0.3, 0.5)

    def test_line_plot_inspector_display_limits_undo(self):
        # note: testing this manually you need to unfocus the field to undo, otherwise it is a text undo.
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.array([1,2]))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # find the inspector panel
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()  # needed to build the inspector
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            inspector_section = inspector_panel.widget.find_widget_by_id("line_plot_display_inspector_section")
            self.assertEqual(None, inspector_section._line_plot_display_section_handler._y_min_model.value)
            self.assertEqual(None, inspector_section._line_plot_display_section_handler._y_max_model.value)
            # test undo after editing (only testing y_min field)
            inspector_section._line_plot_display_section_handler.y_min_field.editing_finished("0.0")
            self.assertEqual(0.0, inspector_section._line_plot_display_section_handler._y_min_model.value)
            document_controller.handle_undo()
            self.assertEqual(None, inspector_section._line_plot_display_section_handler._y_min_model.value)

    def test_line_plot_inspector_display_limits_update_when_using_auto_display(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.array([1,2]))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # find the inspector panel
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()  # needed to build the inspector
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            inspector_section = inspector_panel.widget.find_widget_by_id("line_plot_display_inspector_section")
            self.assertEqual(None, inspector_section._line_plot_display_section_handler._y_min_model.value)
            self.assertEqual(None, inspector_section._line_plot_display_section_handler._y_max_model.value)
            line_plot_canvas_item = typing.cast(LinePlotCanvasItem.LinePlotCanvasItem, display_panel.display_canvas_item)
            line_plot_canvas_item.handle_auto_display()
            # these values are manually determined by the auto display algorithm.
            self.assertEqual(0.0, inspector_section._line_plot_display_section_handler._y_min_model.value)
            self.assertEqual(2.4, inspector_section._line_plot_display_section_handler._y_max_model.value)
            document_controller.handle_undo()
            self.assertEqual(None, inspector_section._line_plot_display_section_handler._y_min_model.value)
            self.assertEqual(None, inspector_section._line_plot_display_section_handler._y_max_model.value)
            document_controller.handle_redo()
            self.assertEqual(0.0, inspector_section._line_plot_display_section_handler._y_min_model.value)
            self.assertEqual(2.4, inspector_section._line_plot_display_section_handler._y_max_model.value)

    def test_slice_inspector_section_uses_correct_dimension(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((4, 4, 32), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_data_channel = display_item.display_data_channels[0]
            display_data_channel.slice_center = 16
            display_data_channel.slice_width = 4
            slice_inspector_section = Inspector.SliceInspectorSection(document_controller, display_item.display_data_channels[0])
            with contextlib.closing(slice_inspector_section):
                self.assertEqual(slice_inspector_section._slice_section_handler.slice_center_model.value, 16)
                self.assertEqual(slice_inspector_section._slice_section_handler.slice_center_maximum, 31)
                self.assertEqual(slice_inspector_section._slice_section_handler.slice_width_model.value, 4)
                self.assertEqual(slice_inspector_section._slice_section_handler.slice_width_maximum, 32)

    def test_image_display_inspector_shows_empty_fields_for_none_display_limits(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((4, 4), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_data_channel = display_item.display_data_channels[0]
            # find the inspector panel
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()  # needed to build the inspector
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            inspector_section = inspector_panel.widget.find_widget_by_id("image_data_inspector_section")
            display_data_channel.display_limits = None
            document_controller.periodic()  # needed to update the inspector
            self.assertEqual(inspector_section.image_data_inspector_handler.display_limits_limit_low.text, None)
            self.assertEqual(inspector_section.image_data_inspector_handler.display_limits_limit_high.text, None)
            display_data_channel.display_limits = (None, None)
            document_controller.periodic()  # needed to update the inspector
            self.assertEqual(inspector_section.image_data_inspector_handler.display_limits_limit_low.text, None)
            self.assertEqual(inspector_section.image_data_inspector_handler.display_limits_limit_high.text, None)
            display_data_channel.display_limits = (1, None)
            document_controller.periodic()  # needed to update the inspector
            self.assertEqual(inspector_section.image_data_inspector_handler.display_limits_limit_low.text, "1.0")
            self.assertEqual(inspector_section.image_data_inspector_handler.display_limits_limit_high.text, None)
            display_data_channel.display_limits = (None, 2)
            document_controller.periodic()  # needed to update the inspector
            self.assertEqual(inspector_section.image_data_inspector_handler.display_limits_limit_low.text, None)
            self.assertEqual(inspector_section.image_data_inspector_handler.display_limits_limit_high.text, "2.0")
            display_data_channel.display_limits = (1, 2)
            document_controller.periodic()  # needed to update the inspector
            self.assertEqual(inspector_section.image_data_inspector_handler.display_limits_limit_low.text, "1.0")
            self.assertEqual(inspector_section.image_data_inspector_handler.display_limits_limit_high.text, "2.0")

    def test_image_display_inspector_sets_display_limits_when_text_is_changed(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((4, 4), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_data_channel = display_item.display_data_channels[0]
            # find the inspector panel
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()  # needed to build the inspector
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            inspector_section = inspector_panel.widget.find_widget_by_id("image_data_inspector_section")
            self.assertEqual(display_data_channel.display_limits, None)
            inspector_section.image_data_inspector_handler.display_limits_limit_low.editing_finished("1")
            self.assertEqual(display_data_channel.display_limits, (1.0, None))
            inspector_section.image_data_inspector_handler.display_limits_limit_high.editing_finished("2")
            self.assertEqual(display_data_channel.display_limits, (1.0, 2.0))
            inspector_section.image_data_inspector_handler.display_limits_limit_low.editing_finished("")
            self.assertEqual(display_data_channel.display_limits, (None, 2.0))
            inspector_section.image_data_inspector_handler.display_limits_limit_high.editing_finished("")
            self.assertEqual(display_data_channel.display_limits, None)

    def test_image_display_inspector_updates_data_range_when_data_changes(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.array([[1,2], [3,4]]))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_data_channel = display_item.display_data_channels[0]
            # find the inspector panel
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()  # needed to build the inspector
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            inspector_section = inspector_panel.widget.find_widget_by_id("image_data_inspector_section")
            self.assertEqual(1, inspector_section.image_data_inspector_handler._model.data_range_low_model.value)
            self.assertEqual(4, inspector_section.image_data_inspector_handler._model.data_range_high_model.value)
            data_item.set_data(numpy.array([[5,6], [7,8]]))
            document_controller.periodic()
            self.assertEqual(5, inspector_section.image_data_inspector_handler._model.data_range_low_model.value)
            self.assertEqual(8, inspector_section.image_data_inspector_handler._model.data_range_high_model.value)

    def test_image_data_inspector_handles_missing_color_table(self) -> None:
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((4, 4), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_data_channel = display_item.display_data_channels[0]
            display_data_channel.color_map_id = "__missing__"
            Inspector.ImageDataInspectorModel(document_controller, display_data_channel, display_item)

    def test_inspector_handles_deleted_data(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((32, 32)))
            document_model.append_data_item(data_item)
            document_controller.periodic()
            document_controller.select_data_item_in_data_panel(data_item=data_item)  # queues the update
            document_model.remove_data_item(data_item)  # removes item while still in queue
            document_controller.periodic()  # execute queue

    def test_inspector_handles_deleted_data_being_displayed(self):
        # if the inspector doesn't watch for the item being deleted, and the inspector's update display
        # doesn't get called during periodic before the item is deleted (which will naturally happen sometimes),
        # then there will be a pending call using a data item that doesn't exist.
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.ones((8, 8)))
            document_model.append_data_item(data_item)
            document_controller.show_display_item(document_model.get_display_item_for_data_item(data_item))
            # document_controller.periodic()  # this makes it succeed in all cases
            document_model.remove_data_item(data_item)
            document_controller.periodic()

    def test_inspector_handles_empty_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem()
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.selected_display_panel = None
            document_controller.selected_display_panel = display_panel
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            document_controller.periodic()
            self.assertTrue(len(inspector_panel._get_inspector_sections()) > 0)

    def test_inspector_handles_all_graphics_on_1d_data(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.ones((1024, )))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.selected_display_panel = None
            document_controller.selected_display_panel = display_panel
            document_controller.add_point_graphic()
            document_controller.add_line_graphic()
            document_controller.add_rectangle_graphic()
            document_controller.add_ellipse_graphic()
            document_controller.add_interval_graphic()
            display_item.graphic_selection.clear()  # make sure all graphics show up in inspector
            self.assertTrue(len(display_item.graphics) == 5)
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            document_controller.periodic()
            self.assertTrue(len(inspector_panel._get_inspector_sections()) > 0)

    def test_inspector_handles_all_graphics_on_2d_data(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.ones((256, 256)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.selected_display_panel = None
            document_controller.selected_display_panel = display_panel
            document_controller.add_point_graphic()
            document_controller.add_line_graphic()
            document_controller.add_rectangle_graphic()
            document_controller.add_ellipse_graphic()
            document_controller.add_interval_graphic()
            display_item.graphic_selection.clear()  # make sure all graphics show up in inspector
            self.assertTrue(len(display_item.graphics) == 5)
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            document_controller.periodic()
            self.assertTrue(len(inspector_panel._get_inspector_sections()) > 0)

    def test_inspector_handles_all_graphics_on_3d_data(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.ones((5, 5, 5)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.selected_display_panel = None
            document_controller.selected_display_panel = display_panel
            document_controller.add_point_graphic()
            document_controller.add_line_graphic()
            document_controller.add_rectangle_graphic()
            document_controller.add_ellipse_graphic()
            document_controller.add_interval_graphic()
            display_item.graphic_selection.clear()  # make sure all graphics show up in inspector
            self.assertTrue(len(display_item.graphics) == 5)
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            document_controller.periodic()
            self.assertTrue(len(inspector_panel._get_inspector_sections()) > 0)

    def test_updating_display_limits_on_fft_does_not_enter_update_cycle(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            d = numpy.random.randn(16, 16)
            d = (d - numpy.min(d)) / (numpy.amax(d) - numpy.amin(d)).astype(numpy.complex128)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.selected_display_panel = None
            document_controller.selected_display_panel = display_panel
            count = [0]
            def property_changed(property_name):
                if property_name == "display_limits":
                    count[0] += 1
            with display_item.display_data_channels[0].property_changed_event.listen(property_changed):
                document_model.recompute_all()
                document_model.recompute_all()
                self.assertEqual(count[0], 0)

    def test_rectangle_dimensions_show_calibrated_units(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.full((256, 256, 37), 0, dtype=numpy.uint32))  # z, y, x
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_graphic(Graphics.RectangleGraphic())
            display_item.calibration_style_id = "calibrated"
            data_item.set_dimensional_calibration(0, Calibration.Calibration(units="mm", scale=0.5))  # y
            data_item.set_dimensional_calibration(1, Calibration.Calibration(units="mm", scale=2.0))  # x
            rectangle_handler= Inspector.GraphicsInspectorHandler(document_controller, display_item, display_item.graphics[0])
            self.assertEqual(rectangle_handler._center_x_model.value, "256.0 mm")  # x
            self.assertEqual(rectangle_handler._center_y_model.value, "64.00 mm")  # y
            self.assertEqual(rectangle_handler._width_model.value, "512.0 mm")  # width
            self.assertEqual(rectangle_handler._height_model.value, "128.00 mm")  # height

    def test_line_dimensions_show_calibrated_units(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.full((100, 100, 37), 0, dtype=numpy.uint32))  # z, y, x
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            line_graphic = Graphics.LineGraphic()
            line_graphic.start = 0.2, 0.2
            line_graphic.end = 0.8, 0.8
            display_item.add_graphic(line_graphic)
            display_item.calibration_style_id = "calibrated"
            data_item.set_dimensional_calibration(0, Calibration.Calibration(units="mm", scale=0.5))  # y
            data_item.set_dimensional_calibration(1, Calibration.Calibration(units="mm", scale=2.0))  # x
            line_handler = Inspector.GraphicsInspectorHandler(document_controller, display_item, line_graphic)
            self.assertEqual(line_handler._x0_model.value, "40.0 mm")  # x0
            self.assertEqual(line_handler._y0_model.value, "10.00 mm")  # y0
            self.assertEqual(line_handler._x1_model.value, "160.0 mm")  # x1
            self.assertEqual(line_handler._y1_model.value, "40.00 mm")  # y1

    def test_point_dimensions_show_calibrated_units(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.full((256, 256, 37), 0, dtype=numpy.uint32))  # z, y, x
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_graphic(Graphics.PointGraphic())
            display_item.calibration_style_id = "calibrated"
            display_item.data_item.set_dimensional_calibration(0, Calibration.Calibration(units="mm", scale=0.5))  # y
            display_item.data_item.set_dimensional_calibration(1, Calibration.Calibration(units="mm", scale=2.0))  # x
            point_handler = Inspector.GraphicsInspectorHandler(document_controller, display_item, display_item.graphics[0])
            self.assertEqual(point_handler._point_position_x_model.value, "256.0 mm")  # x
            self.assertEqual(point_handler._point_position_y_model.value, "64.00 mm")  # y

    def test_point_dimensions_show_calibrated_units_on_4d(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.full((16, 16, 24, 24), 0, dtype=numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_graphic(Graphics.PointGraphic())
            display_item.calibration_style_id = "calibrated"
            display_item.data_item.set_dimensional_calibration(0, Calibration.Calibration(units="mm", scale=0.5))  # a
            display_item.data_item.set_dimensional_calibration(1, Calibration.Calibration(units="mm", scale=2.0))  # b
            display_item.data_item.set_dimensional_calibration(2, Calibration.Calibration(units="nm", scale=0.5))  # y
            display_item.data_item.set_dimensional_calibration(3, Calibration.Calibration(units="nm", scale=2.0))  # x
            point_handler = Inspector.GraphicsInspectorHandler(document_controller, display_item, display_item.graphics[0])
            self.assertEqual("6.00 nm", point_handler._point_position_y_model.value)  # y
            self.assertEqual("24.0 nm", point_handler._point_position_x_model.value)  # x

    def test_pixel_center_rounding_correct_on_odd_dimensioned_image(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.full((139, 89), 0, dtype=numpy.uint32))  # y, x
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            point_graphic = Graphics.PointGraphic()
            point_graphic.position = 0.5, 0.5
            display_item.add_graphic(point_graphic)
            # find the inspector panel
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()  # needed to build the inspector
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            # check the values
            display_item.calibration_style_id = "pixels-center"
            document_controller.periodic()  # needed to build the inspector
            point_handler = inspector_panel.column.find_widget_by_id("graphics_inspector_section")._handler._graphic_handlers[0]
            self.assertEqual(point_handler._point_position_x_model.value, "0.0")  # x
            self.assertEqual(point_handler._point_position_y_model.value, "0.0")  # y

    def test_editing_pixel_width_on_rectangle_adjusts_rectangle_properly(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.full((100, 50), 0, dtype=numpy.uint32))  # y, x
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            point_graphic = Graphics.RectangleGraphic()
            display_item.add_graphic(point_graphic)
            # find the inspector panel
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()  # needed to build the inspector
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            display_item.calibration_style_id = "pixels-center"
            document_controller.periodic()  # needed to update the inspector
            rectangle_handler = inspector_panel.column.find_widget_by_id("graphics_inspector_section")._handler._graphic_handlers[0]
            x_model = rectangle_handler._center_x_model
            y_model = rectangle_handler._center_y_model
            width_model = rectangle_handler._width_model
            height_model = rectangle_handler._height_model
            self.assertEqual(x_model.value, "0.0")  # x
            self.assertEqual(y_model.value, "0.0")  # y
            self.assertEqual(width_model.value, "50.0")  # width
            self.assertEqual(height_model.value, "100.0")  # height
            width_model.value = "40"
            document_controller.periodic()  # needed to update the inspector
            self.assertEqual(x_model.value, "0.0")  # x
            self.assertEqual(y_model.value, "0.0")  # y
            self.assertEqual(width_model.value, "40.0")  # width
            self.assertEqual(height_model.value, "100.0")  # height

    def test_interval_dimensions_show_calibrated_units_on_single_spectrum(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.full((100, ), 0, dtype=numpy.uint32))  # time, energy
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            interval_graphic = Graphics.IntervalGraphic()
            interval_graphic.start = 0.2
            interval_graphic.end = 0.4
            display_item.add_graphic(interval_graphic)
            display_item.calibration_style_id = "calibrated"
            data_item.set_dimensional_calibration(0, Calibration.Calibration(units="eV", scale=2.0))  # energy
            interval_handler = Inspector.GraphicsInspectorHandler(document_controller, display_item, interval_graphic)
            self.assertEqual("40.0 eV", interval_handler._start_model.value)  # energy
            self.assertEqual("80.0 eV", interval_handler._end_model.value)  # energy

    def test_interval_dimensions_show_calibrated_units_on_sequence_of_spectra(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.full((3, 100), 0, dtype=numpy.uint32))  # time, energy
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            interval_graphic = Graphics.IntervalGraphic()
            interval_graphic.start = 0.2
            interval_graphic.end = 0.4
            display_item.add_graphic(interval_graphic)
            display_item.calibration_style_id = "calibrated"
            data_item.set_dimensional_calibration(0, Calibration.Calibration(units="s", scale=1.0))  # time
            data_item.set_dimensional_calibration(1, Calibration.Calibration(units="eV", scale=2.0))  # energy
            interval_handler = Inspector.GraphicsInspectorHandler(document_controller, display_item, interval_graphic)
            self.assertEqual("40.0 eV", interval_handler._start_model.value)  # energy
            self.assertEqual("80.0 eV", interval_handler._end_model.value)  # energy

    def test_interval_dimensions_show_calibrated_units_on_composite_line_plot(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.full((100, ), 0, dtype=numpy.uint32))  # time, energy
            data_item2 = DataItem.DataItem(numpy.full((100, ), 1, dtype=numpy.uint32))  # time, energy
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2, False)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            display_item.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item2))
            interval_graphic = Graphics.IntervalGraphic()
            interval_graphic.start = 0.2
            interval_graphic.end = 0.4
            display_item.add_graphic(interval_graphic)
            display_item.calibration_style_id = "calibrated"
            data_item.set_dimensional_calibration(0, Calibration.Calibration(units="eV", scale=2.0))  # energy
            interval_handler = Inspector.GraphicsInspectorHandler(document_controller, display_item, interval_graphic)
            self.assertEqual("40.0 eV", interval_handler._start_model.value)  # energy
            self.assertEqual("80.0 eV", interval_handler._end_model.value)  # energy

    def test_3d_data_dimensions_show_calibrated(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.new_data_item(DataAndMetadata.new_data_and_metadata(numpy.ones((2, 4, 8)), data_descriptor=DataAndMetadata.DataDescriptor(False, 2, 1)))
            data_item.set_dimensional_calibration(0, Calibration.Calibration(units="nm", scale=1.0))
            data_item.set_dimensional_calibration(1, Calibration.Calibration(units="nm", scale=1.0))
            data_item.set_dimensional_calibration(2, Calibration.Calibration(units="eV", scale=1.0))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            point_graphic = Graphics.PointGraphic()
            point_graphic.position = Geometry.FloatPoint(0.5, 0.5)
            display_item.add_graphic(point_graphic)
            display_item.calibration_style_id = "relative-top-left"
            point_handler = Inspector.GraphicsInspectorHandler(document_controller, display_item, point_graphic)
            point_handler._point_position_x_model.value = "0.75"
            point_handler._point_position_y_model.value = "0.25"
            self.assertEqual(Geometry.FloatPoint(0.25, 0.75), point_graphic.position)
            display_item.calibration_style_id = "calibrated"
            self.assertEqual("3.0 nm", point_handler._point_position_x_model.value)
            self.assertEqual("0.5 nm", point_handler._point_position_y_model.value)

    def test_4d_data_dimensions_show_calibrated(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.new_data_item(DataAndMetadata.new_data_and_metadata(numpy.ones((2, 3, 4, 8)), data_descriptor=DataAndMetadata.DataDescriptor(False, 2, 2)))
            data_item.set_dimensional_calibration(0, Calibration.Calibration(units="nm", scale=1.0))
            data_item.set_dimensional_calibration(1, Calibration.Calibration(units="nm", scale=1.0))
            data_item.set_dimensional_calibration(2, Calibration.Calibration(units="cm", scale=1.0))
            data_item.set_dimensional_calibration(3, Calibration.Calibration(units="cm", scale=1.0))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            point_graphic = Graphics.PointGraphic()
            point_graphic.position = Geometry.FloatPoint(0.5, 0.5)
            display_item.add_graphic(point_graphic)
            display_item.calibration_style_id = "relative-top-left"
            point_handler = Inspector.GraphicsInspectorHandler(document_controller, display_item, point_graphic)
            point_handler._point_position_x_model.value = "0.75"
            point_handler._point_position_y_model.value = "0.25"
            self.assertEqual(Geometry.FloatPoint(0.25, 0.75), point_graphic.position)
            display_item.calibration_style_id = "calibrated"
            self.assertEqual("6.0 cm", point_handler._point_position_x_model.value)
            self.assertEqual("1.0 cm", point_handler._point_position_y_model.value)

    def test_calibration_inspector_updates_for_when_data_shape_changes(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((10, 10, 10)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            document_controller.periodic()
            self.assertIn(Inspector.SliceInspectorSection, (type(i) for i in inspector_panel._get_inspector_sections()))
            data_item.set_data(numpy.zeros((10, 10)))
            document_controller.periodic()
            self.assertNotIn(Inspector.SliceInspectorSection, (type(i) for i in inspector_panel._get_inspector_sections()))

    def test_calibration_inspector_updates_for_when_empty_data_item_displayed_as_line_plot_gets_data(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem()
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_graphic(Graphics.IntervalGraphic())
            display_item.display_type = "line_plot"
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()
            data_item.set_data(numpy.zeros((10, )))

    def test_inspector_updates_for_new_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            # configure workspace
            d = {"type": "splitter", "orientation": "vertical", "splits": [0.5, 0.5], "children": [
                {"type": "image", "uuid": "0569ca31-afd7-48bd-ad54-5e2bb9f21102", "identifier": "a", "selected": True},
                {"type": "image", "uuid": "acd77f9f-2f6f-4fbf-af5e-94330b73b997", "identifier": "b"}]}
            workspace_2x1 = document_controller.workspace_controller.new_workspace("2x1", d)
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            # put data item in first area
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            # print("data_item {}".format(data_item))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()  # needed to build the inspector
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            expected_inspector_section_count = len(inspector_panel._get_inspector_sections())
            # process to add new data item
            new_data_item = document_controller.processing_invert().data_item
            # print("new_data_item {}".format(new_data_item))
            document_model.recompute_all()
            document_controller.periodic()  # update the inspector
            new_display_panel = document_controller.selected_display_panel
            self.assertNotEqual(new_display_panel, display_panel)
            self.assertEqual(new_display_panel.data_item, new_data_item)
            actual_inspector_section_count = len(inspector_panel._get_inspector_sections())
            self.assertEqual(expected_inspector_section_count, actual_inspector_section_count)

    def test_data_item_with_no_data_displays_as_line_plot(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem()
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            display_panel.set_display_panel_display_item(display_item)
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            document_controller.periodic()

    def test_inspector_updates_when_graphic_associated_with_pick_is_deleted(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((16, 16, 64)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            document_model.recompute_all()
            document_controller.periodic()
            expected_inspector_section_count = len(inspector_panel._get_inspector_sections())
            # add the point graphic, ensure that inspector is updated with just a section for point graphic
            self.assertEqual(len(document_controller.selected_display_item.graphic_selection.indexes), 0)  # make sure graphic is not selected
            document_model.get_pick_new(display_item, display_item.data_item)
            self.assertEqual(document_controller.selected_data_item, data_item)
            document_controller.selected_display_item.graphic_selection.add(0)
            document_model.recompute_all()
            document_controller.periodic()
            graphic_inspector_section_count = len(inspector_panel._get_inspector_sections())
            self.assertNotEqual(expected_inspector_section_count, graphic_inspector_section_count)
            # now remove the point graphic and ensure that inspector inspecting data item again
            self.assertEqual(len(document_controller.selected_display_item.graphic_selection.indexes), 1)  # make sure graphic is selected
            document_controller.remove_selected_graphics()
            document_model.recompute_all()
            document_controller.periodic()
            self.assertEqual(len(document_controller.selected_display_item.graphic_selection.indexes), 0)  # make sure graphic is not selected
            actual_inspector_section_count = len(inspector_panel._get_inspector_sections())
            self.assertEqual(expected_inspector_section_count, actual_inspector_section_count)

    def test_spot_graphic_inspector_updates_without_exception(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((16, 16)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            document_controller.periodic()
            self.assertIsNone(inspector_panel.column.find_widget_by_id("graphics_inspector_section"))
            document_controller.add_spot_graphic()
            document_controller.periodic()
            graphics_section = inspector_panel.column.find_widget_by_id("graphics_inspector_section")
            self.assertIsNotNone(graphics_section)
            self.assertIn("Spot", (i._graphic_type_model.value for i in graphics_section._handler._graphic_handlers))

    def test_band_pass_graphic_inspector_updates_without_exception(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((16, 16)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            document_controller.periodic()
            self.assertIsNone(inspector_panel.column.find_widget_by_id("graphics_inspector_section"))
            document_controller.add_band_pass_graphic()
            document_controller.periodic()
            graphics_section = inspector_panel.column.find_widget_by_id("graphics_inspector_section")
            self.assertIsNotNone(graphics_section)
            self.assertIn("Annular Ring", (i._graphic_type_model.value for i in graphics_section._handler._graphic_handlers))

    def test_wedge_graphic_inspector_updates_without_exception(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((16, 16)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            document_controller.periodic()
            self.assertIsNone(inspector_panel.column.find_widget_by_id("graphics_inspector_section"))
            document_controller.add_angle_graphic()
            document_controller.periodic()
            graphics_section = inspector_panel.column.find_widget_by_id("graphics_inspector_section")
            self.assertIsNotNone(graphics_section)
            self.assertIn("Wedge", (i._graphic_type_model.value for i in graphics_section._handler._graphic_handlers))

    def test_graphic_inspector_updates_for_when_data_shape_changes(self):
        # change from 2d item with a rectangle to a 1d item. what happens?
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((16, 16)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            document_controller.periodic()
            self.assertNotIn(Inspector.LinePlotDisplayInspectorSection, (type(i) for i in inspector_panel._get_inspector_sections()))
            data_item.set_data(numpy.zeros((10, )))
            document_controller.periodic()
            self.assertIn(Inspector.LinePlotDisplayInspectorSection, (type(i) for i in inspector_panel._get_inspector_sections()))
            data_item.set_data(numpy.zeros((10, 10)))
            document_controller.periodic()
            self.assertNotIn(Inspector.LinePlotDisplayInspectorSection, (type(i) for i in inspector_panel._get_inspector_sections()))

    def test_calibration_inspector_shows_correct_labels_for_1d(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, )))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            calibration_section = Inspector.CalibrationsInspectorSection(document_controller, display_item.display_data_channels[0], display_item)
            with contextlib.closing(calibration_section):
                self.assertEqual(1, len(calibration_section._dimensional_calibrations_model.items))
                dimensional_calibration_model = calibration_section._dimensional_calibrations_model.items[0]
                self.assertEqual("Channel", dimensional_calibration_model.axis_name)

    def test_calibration_inspector_shows_correct_labels_for_2d(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            calibration_section = Inspector.CalibrationsInspectorSection(document_controller, display_item.display_data_channel, display_item)
            with contextlib.closing(calibration_section):
                self.assertEqual(2, len(calibration_section._dimensional_calibrations_model.items))
                self.assertEqual("Y", calibration_section._dimensional_calibrations_model.items[0].axis_name)
                self.assertEqual("X", calibration_section._dimensional_calibrations_model.items[1].axis_name)

    def test_calibration_inspector_shows_correct_labels_for_3d(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8, 16)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            calibration_section = Inspector.CalibrationsInspectorSection(document_controller, display_item.display_data_channel, display_item)
            with contextlib.closing(calibration_section):
                self.assertEqual(3, len(calibration_section._dimensional_calibrations_model.items))
                self.assertEqual("0", calibration_section._dimensional_calibrations_model.items[0].axis_name)
                self.assertEqual("1", calibration_section._dimensional_calibrations_model.items[1].axis_name)
                self.assertEqual("2", calibration_section._dimensional_calibrations_model.items[2].axis_name)

    def test_computation_inspector_updates_when_computation_variable_type_changes(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            x = computation.create_variable("x", "integral", 0)
            document_model.set_data_item_computation(data_item, computation)
            display_panel = document_controller.selected_display_panel
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            document_controller.periodic()
            inspector_section = next(x for x in inspector_panel._get_inspector_sections() if isinstance(x, Inspector.ComputationInspectorSection))
            line_edit_widget1 = inspector_section._variables_column_widget.children[0].content_widget.find_widget_by_id("value")
            line_edit_widget1.editing_finished("1")
            self.assertEqual(x.value, 1)
            x.value_type = Symbolic.ComputationVariableType.REAL
            document_controller.periodic()
            line_edit_widget2 = inspector_section._variables_column_widget.children[0].content_widget.find_widget_by_id("value")
            line_edit_widget2.editing_finished("1.1")
            self.assertEqual(x.value, 1.1)

    def test_computation_inspector_handles_computation_variable_checkbox_and_undo_redo_cycle(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            new_data_item = document_model.get_transpose_flip_new(display_item, display_item.data_item)
            new_display_item = document_model.get_display_item_for_data_item(new_data_item)
            document_model.recompute_all()
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(new_display_item)
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            document_controller.periodic()
            computation = document_model.get_data_item_computation(new_data_item)
            self.assertFalse(computation.get_input_value("do_transpose"))
            inspector_section = next(x for x in inspector_panel._get_inspector_sections() if isinstance(x, Inspector.ComputationInspectorSection))
            cb_widget = inspector_section.find_widget_by_id("value")
            cb_widget.checked = True
            self.assertTrue(computation.get_input_value("do_transpose"))
            document_controller.handle_undo()
            self.assertFalse(computation.get_input_value("do_transpose"))
            document_controller.handle_redo()
            self.assertTrue(computation.get_input_value("do_transpose"))

    def test_computation_inspector_handles_computation_variable_slider_and_undo_redo_cycle(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            new_data_item = document_model.get_gaussian_blur_new(display_item, display_item.data_item)
            new_display_item = document_model.get_display_item_for_data_item(new_data_item)
            document_model.recompute_all()
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(new_display_item)
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            document_controller.periodic()
            computation = document_model.get_data_item_computation(new_data_item)
            old_sigma = computation.get_input_value("sigma")
            inspector_section = next(x for x in inspector_panel._get_inspector_sections() if isinstance(x, Inspector.ComputationInspectorSection))
            slider_widget = inspector_section.find_widget_by_id("slider_value")
            slider_widget.value = 0
            self.assertEqual(0, computation.get_input_value("sigma"))
            document_controller.handle_undo()
            self.assertEqual(old_sigma, computation.get_input_value("sigma"))
            document_controller.handle_redo()
            self.assertEqual(0, computation.get_input_value("sigma"))

    def test_computation_inspector_handles_computation_variable_int_and_undo_redo_cycle(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            new_data_item = document_model.get_histogram_new(display_item, display_item.data_item)
            new_display_item = document_model.get_display_item_for_data_item(new_data_item)
            document_model.recompute_all()
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(new_display_item)
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            document_controller.periodic()
            computation = document_model.get_data_item_computation(new_data_item)
            old_bins = computation.get_input_value("bins")
            inspector_section = Inspector.ComputationInspectorSection(Inspector.ComputationInspectorContext(document_controller), new_data_item)
            with contextlib.closing(inspector_section):
                field_widget = inspector_section.find_widget_by_id("value")
                field_widget.editing_finished("100")
                self.assertEqual(100, computation.get_input_value("bins"))
                document_controller.handle_undo()
                self.assertEqual(old_bins, computation.get_input_value("bins"))
                document_controller.handle_redo()
                self.assertEqual(100, computation.get_input_value("bins"))

    def test_computation_inspector_handles_computation_variable_specifier_and_undo_redo_cycle(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            new_data_item = document_model.get_invert_new(display_item, display_item.data_item)
            document_model.recompute_all()
            computation = document_model.get_data_item_computation(new_data_item)
            self.assertEqual({data_item}, computation.get_variable_input_items("src"))
            command = Inspector.ChangeComputationVariableCommand(document_model, computation, computation._get_variable("src"), specified_object=None)
            command.perform()
            document_controller.push_undo_command(command)
            self.assertIsNone(computation.get_input("src"))
            self.assertTrue(document_controller._undo_stack.can_undo)
            document_controller.handle_undo()
            self.assertEqual({data_item}, computation.get_variable_input_items("src"))
            document_controller.handle_redo()
            self.assertIsNone(computation.get_input("src"))

    def test_change_property_command_multiple_undo(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
            document_model.append_data_item(data_item)
            session_metadata = data_item.session_metadata
            session_metadata["site"] = "S"
            session_metadata["instrument"] = "I"
            session_metadata["task"] = "T"
            data_item.session_metadata = session_metadata
            session_metadata = data_item.session_metadata
            session_metadata["site"] = "SS"
            command = Inspector.ChangePropertyCommand(document_model, data_item, "session_metadata", session_metadata)
            command.perform()
            document_controller.push_undo_command(command)
            session_metadata = data_item.session_metadata
            session_metadata["instrument"] = "II"
            command = Inspector.ChangePropertyCommand(document_model, data_item, "session_metadata", session_metadata)
            command.perform()
            document_controller.push_undo_command(command)
            session_metadata = data_item.session_metadata
            session_metadata["task"] = "TT"
            command = Inspector.ChangePropertyCommand(document_model, data_item, "session_metadata", session_metadata)
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(1, document_controller._undo_stack._undo_count)
            self.assertEqual({"site": "SS", "instrument": "II", "task": "TT"}, data_item.session_metadata)
            document_controller.handle_undo()
            self.assertEqual(0, document_controller._undo_stack._undo_count)
            self.assertEqual({"site": "S", "instrument": "I", "task": "T"}, data_item.session_metadata)
            document_controller.handle_redo()
            self.assertEqual(1, document_controller._undo_stack._undo_count)
            self.assertEqual({"site": "SS", "instrument": "II", "task": "TT"}, data_item.session_metadata)

    def test_change_property_command_with_different_properties_multiple_undo(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
            document_model.append_data_item(data_item)
            command = Inspector.ChangePropertyCommand(document_model, data_item, "title", "T")
            command.perform()
            document_controller.push_undo_command(command)
            command = Inspector.ChangePropertyCommand(document_model, data_item, "caption", "C")
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(2, document_controller._undo_stack._undo_count)
            document_controller.handle_undo()
            self.assertEqual("T", data_item.title)
            document_controller.handle_undo()
            self.assertEqual(0, document_controller._undo_stack._undo_count)

    def test_change_intensity_calibration_command(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
            document_model.append_data_item(data_item)
            command = Inspector.ChangeIntensityCalibrationCommand(document_model, data_item, Calibration.Calibration(scale=3))
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(Calibration.Calibration(scale=3), data_item.intensity_calibration)
            document_controller.handle_undo()
            self.assertEqual(Calibration.Calibration(), data_item.intensity_calibration)
            document_controller.handle_redo()
            self.assertEqual(Calibration.Calibration(scale=3), data_item.intensity_calibration)

    def test_change_dimensional_calibrations_command(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
            document_model.append_data_item(data_item)
            command = Inspector.ChangeDimensionalCalibrationsCommand(document_model, data_item, [Calibration.Calibration(scale=2), Calibration.Calibration(scale=3)])
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual([Calibration.Calibration(scale=2), Calibration.Calibration(scale=3)], list(data_item.dimensional_calibrations))
            document_controller.handle_undo()
            self.assertEqual([Calibration.Calibration(), Calibration.Calibration()], list(data_item.dimensional_calibrations))
            document_controller.handle_redo()
            self.assertEqual([Calibration.Calibration(scale=2), Calibration.Calibration(scale=3)], list(data_item.dimensional_calibrations))

    def test_change_display_type_command(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((2, 256)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            command = Inspector.ChangeDisplayTypeCommand(document_model, display_item, "image")
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual("image", display_item.display_type)
            document_controller.handle_undo()
            self.assertEqual("line_plot", display_item.display_type)
            document_controller.handle_redo()
            self.assertEqual("image", display_item.display_type)

    def test_remove_display_layer_command(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, )))
            data_item2 = DataItem.DataItem(numpy.zeros((8, )))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.append_display_data_channel_for_data_item(data_item2)
            self.assertEqual(2, len(display_item.display_data_channels))
            self.assertEqual(2, len(display_item.display_layers))
            self.assertEqual(display_item.display_data_channels[0], display_item.display_layers[0].display_data_channel)
            self.assertEqual(display_item.display_data_channels[1], display_item.display_layers[1].display_data_channel)
            command = Inspector.RemoveDisplayDataChannelCommand(document_controller, display_item, display_item.display_data_channels[1])
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(1, len(display_item.display_data_channels))
            self.assertEqual(1, len(display_item.display_layers))
            self.assertEqual(display_item.display_data_channels[0], display_item.display_layers[0].display_data_channel)
            command.undo()
            self.assertEqual(2, len(display_item.display_data_channels))
            self.assertEqual(2, len(display_item.display_layers))
            self.assertEqual(display_item.display_data_channels[0], display_item.display_layers[0].display_data_channel)
            self.assertEqual(display_item.display_data_channels[1], display_item.display_layers[1].display_data_channel)
            command.redo()
            self.assertEqual(1, len(display_item.display_data_channels))
            self.assertEqual(1, len(display_item.display_layers))
            self.assertEqual(display_item.display_data_channels[0], display_item.display_layers[0].display_data_channel)

    def test_change_display_layer_property_command(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, )))
            data_item2 = DataItem.DataItem(numpy.zeros((8, )))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.append_display_data_channel_for_data_item(data_item2)
            self.assertIsNone(display_item.get_display_layer_property(1, "label"))
            command = Inspector.ChangeDisplayLayerPropertyCommand(document_model, display_item, 1, "label", "A")
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual("A", display_item.get_display_layer_property(1, "label"))
            command.undo()
            self.assertIsNone(display_item.get_display_layer_property(1, "label"))
            command.redo()
            self.assertEqual("A", display_item.get_display_layer_property(1, "label"))

    def test_change_display_layer_data_command(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, )))
            data_item2 = DataItem.DataItem(numpy.zeros((8, )))
            data_item3 = DataItem.DataItem(numpy.zeros((8, )))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.append_display_data_channel_for_data_item(data_item2)
            display_item.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item3))
            self.assertEqual(3, len(display_item.display_data_channels))
            self.assertEqual(2, len(display_item.display_layers))
            self.assertEqual(display_item.display_data_channels[1], display_item.get_display_layer_display_data_channel(1))
            command = Inspector.ChangeDisplayLayerDisplayDataChannelCommand(document_model, display_item, display_item.display_layers[1], display_item.display_data_channels[2])
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(display_item.display_data_channels[2], display_item.get_display_layer_display_data_channel(1))
            command.undo()
            self.assertEqual(display_item.display_data_channels[1], display_item.get_display_layer_display_data_channel(1))
            command.redo()
            self.assertEqual(display_item.display_data_channels[2], display_item.get_display_layer_display_data_channel(1))

    def test_setting_display_layer_to_no_display_data_channel_and_back(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            display_panel = document_controller.selected_display_panel
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8,)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_layer = typing.cast(DisplayItem.DisplayLayer, display_item.display_layers[0])
            display_layer.display_data_channel = None
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            line_plot_display_layers_section = typing.cast(Inspector.LinePlotDisplayLayersInspectorSection, inspector_panel.widget.find_widget_by_id("line_plot_display_layers_inspector_section"))
            line_plot_display_layer_model = line_plot_display_layers_section._handler._line_plot_display_layer_handlers[0]._line_plot_display_layer_model
            line_plot_display_layer_model.data_index_model.value = None
            line_plot_display_layer_model.data_index_model.value = 0
            line_plot_display_layer_model.data_index_model.value = None
            line_plot_display_layer_model.data_index_model.value = 0

    def test_graphic_property_binding_handles_removed_graphic(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((10, )))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)

            interval = Graphics.IntervalGraphic()
            display_item.add_graphic(interval)
            interval2 = Graphics.IntervalGraphic()
            display_item.add_graphic(interval2)

            data_item2 = DataItem.DataItem(numpy.zeros((10, )))
            document_model.append_data_item(data_item2)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            data_item3 = DataItem.DataItem(numpy.zeros((10, )))
            document_model.append_data_item(data_item3)
            display_item3 = document_model.get_display_item_for_data_item(data_item3)

            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.create_input_item("interval", Symbolic.make_item(interval))
            computation.create_input_item("interval2", Symbolic.make_item(interval2))
            computation.create_output_item("dst", Symbolic.make_item(data_item2))
            computation.create_output_item("dst2", Symbolic.make_item(data_item3))
            document_model.append_computation(computation)
            document_model.recompute_all()
            interval2.source = interval
            display_item.append_display_data_channel_for_data_item(data_item2)
            display_item.append_display_data_channel_for_data_item(data_item3)

            binding = Inspector.CalibratedValueBinding(-1, display_item, Inspector.ChangeGraphicPropertyBinding(document_controller, display_item, interval2, "start"))
            with contextlib.closing(binding):
                display_item.remove_graphic(interval).close()

    def test_contrast_converters(self):
        self.assertEqual("1 / 4.00", Inspector.ContrastStringConverter().convert(0.25))
        self.assertEqual("2.50", Inspector.ContrastStringConverter().convert(2.5))
        self.assertEqual(0.25, Inspector.ContrastStringConverter().convert_back("1 / 4.00"))
        self.assertEqual(2.5, Inspector.ContrastStringConverter().convert_back("2.50"))
        self.assertEqual(0, Inspector.ContrastIntegerConverter(100).convert(0.1))
        self.assertEqual(100, Inspector.ContrastIntegerConverter(100).convert(10.0))
        self.assertEqual(0.1, Inspector.ContrastIntegerConverter(100).convert_back(0))
        self.assertEqual(10.0, Inspector.ContrastIntegerConverter(100).convert_back(100))
        # test invalid value case
        self.assertEqual("0.00", Inspector.ContrastStringConverter().convert(0.0))
        self.assertEqual(0.0, Inspector.ContrastStringConverter().convert_back("0.00"))
        self.assertEqual(100, Inspector.ContrastIntegerConverter(100).convert(0.0))
        self.assertEqual(10.0, Inspector.ContrastIntegerConverter(100).convert_back(100))

    def test_gamma_converters(self):
        self.assertEqual("1 / 4.000", Inspector.GammaStringConverter().convert(0.25))
        self.assertEqual("2.50", Inspector.GammaStringConverter().convert(2.5))
        self.assertEqual(0.25, Inspector.GammaStringConverter().convert_back("1 / 4.00"))
        self.assertEqual(2.5, Inspector.GammaStringConverter().convert_back("2.50"))
        self.assertEqual(100, Inspector.GammaIntegerConverter().convert(0.1))
        self.assertEqual(0, Inspector.GammaIntegerConverter().convert(10.0))
        self.assertEqual(0.1, Inspector.GammaIntegerConverter().convert_back(100))
        self.assertEqual(10.0, Inspector.GammaIntegerConverter().convert_back(0))
        # test invalid value case
        self.assertEqual("0.00", Inspector.GammaStringConverter().convert(0.0))
        self.assertEqual(0.0, Inspector.GammaStringConverter().convert_back("0.00"))
        self.assertEqual(0, Inspector.GammaIntegerConverter().convert(0.0))
        self.assertEqual(0.1, Inspector.GammaIntegerConverter().convert_back(100))

    def test_line_plot_inspector_handles_legend_position(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((32,)))
            data_item2 = DataItem.DataItem(numpy.zeros((32,)))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2, False)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            display_item.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item2))
            display_panel.set_display_panel_display_item(display_item)
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            document_controller.periodic()
            inspector_panel.show()
            self.assertNotEqual("outer-left", display_item.get_display_property("legend_position"))
            display_item.set_display_property("legend_position", "outer-left")
            self.assertEqual("outer-left", display_item.get_display_property("legend_position"))
            display_item.set_display_property("legend_position", "outer-right")
            self.assertEqual("outer-right", display_item.get_display_property("legend_position"))
            display_item.set_display_property("legend_position", "outer-space")  # dummy value

    def test_activating_inspector_should_not_trigger_data_item_change(self) -> None:
        # this error occurred because the inspector was setting the calibration on the wrong data item
        # when it changed.
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item1 = DataItem.new_data_item(DataAndMetadata.new_data_and_metadata(
                data=numpy.zeros((32, 32)),
                dimensional_calibrations=[Calibration.Calibration(units="x"), Calibration.Calibration()],
                intensity_calibration=Calibration.Calibration(units="u"))
            )
            data_item2 = DataItem.DataItem(numpy.zeros((32, 32)))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            last_modified1 = data_item1.modified
            last_modified2 = data_item2.modified
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            inspector_panel.show()
            display_panel.set_display_panel_display_item(display_item2)
            document_controller.periodic()
            display_panel.set_display_panel_display_item(display_item1)
            document_controller.periodic()
            self.assertEqual(last_modified1, data_item1.modified)
            self.assertEqual(last_modified2, data_item2.modified)
            display_panel.set_display_panel_display_item(display_item2)
            document_controller.periodic()
            self.assertEqual(last_modified1, data_item1.modified)
            self.assertEqual(last_modified2, data_item2.modified)

    def test_editing_calibrations_in_inspector_update_data_item(self) -> None:
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.new_data_item(DataAndMetadata.new_data_and_metadata(
                data=numpy.zeros((32, 32)),
                dimensional_calibrations=[Calibration.Calibration(units="x"), Calibration.Calibration()],
                intensity_calibration=Calibration.Calibration(units="u"))
            )
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            inspector_panel = document_controller.find_dock_panel("inspector-panel")
            inspector_panel.show()
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()
            calibration_section = Inspector.CalibrationsInspectorSection(document_controller, display_item.display_data_channel, display_item)
            with contextlib.closing(calibration_section):
                intensity_calibration_model = calibration_section._intensity_calibration_model
                intensity_calibration_model.units = "v"
                self.assertEqual("v", data_item.intensity_calibration.units)
                dimensional_calibration_model = calibration_section._dimensional_calibrations_model.items[1]
                dimensional_calibration_model.units = "y"
                self.assertEqual("y", data_item.dimensional_calibrations[1].units)

    def test_session_inspector_model_closes_properly(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((32,)))
            document_model.append_data_item(data_item)
            session_inspector_model = Inspector.SessionInspectorModel(document_controller, data_item)
            self.assertFalse(hasattr(session_inspector_model, "close"))
            # session_inspector_model.close()  # failed it old style code.
            session_inspector_model = None
            # nothing should be printed when this is run, since the model has been closed and no python
            # reference to it remains. in the failing code, the close does nothing other than mark the event
            # as not accepting events anymore. the change to data below would trigger a log message if this
            # isn't working properly.
            data_item.set_intensity_calibration(Calibration.Calibration(units="miles"))

    def test_undo_graphic_label(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            interval_graphic = Graphics.IntervalGraphic()
            display_item.add_graphic(interval_graphic)
            display_item.graphic_selection.set(0)
            self.assertEqual(1, len(display_item.graphics))
            command = DisplayPanel.ChangeGraphicsCommand(document_model, display_item, [interval_graphic])
            display_item.graphics[0].label = "abc"
            document_controller.push_undo_command(command)
            # check the undo status. use full object specifiers since objects may be replaced.
            self.assertEqual(1, len(display_item.graphics))
            self.assertEqual("abc", display_item.graphics[0].label)
            command.undo()
            self.assertFalse(display_item.graphics[0].label)
            command.redo()
            self.assertEqual("abc", display_item.graphics[0].label)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
