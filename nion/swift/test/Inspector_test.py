# standard imports
import contextlib
import locale
import logging
import math
import unittest
import uuid

# third-party imports
import numpy

# local imports
from nion.data import Calibration
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift import Facade
from nion.swift import Inspector
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.ui import TestUI
from nion.utils import Binding
from nion.utils import Observable


Facade.initialize()


class TestInspectorClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_info_inspector_section_follows_title_change(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
            data_item.title = "Title1"
            document_model.append_data_item(data_item)
            inspector_section = Inspector.InfoInspectorSection(document_controller, data_item)
            with contextlib.closing(inspector_section):
                self.assertEqual(inspector_section.info_title_label.text, "Title1")
                data_item.title = "Title2"
                self.assertEqual(inspector_section.info_title_label.text, "Title2")

    def test_display_limits_inspector_should_bind_to_display_without_errors(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            # configure the inspectors
            document_controller.notify_focused_display_changed(data_item.primary_display_specifier.display)
            document_controller.periodic()  # force UI to update
            document_controller.notify_focused_display_changed(None)

    def test_calibration_value_and_size_float_to_string_converter_works_with_display(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            converter = Inspector.CalibratedValueFloatToStringConverter(display_specifier.data_item, display_specifier.display, 0)
            converter.convert(0.5)
            converter = Inspector.CalibratedSizeFloatToStringConverter(display_specifier.data_item, display_specifier.display, 0)
            converter.convert(0.5)

    def test_adjusting_rectangle_width_should_keep_center_constant(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            rect_graphic = Graphics.RectangleGraphic()
            rect_graphic.bounds = ((0.25, 0.25), (0.5, 0.5))
            center = rect_graphic.center
            class BoolModel(Observable.Observable):
                def __init__(self):
                    super(BoolModel, self).__init__()
                    self.dimensional_calibration_style = "relative-top-left"
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            size_width_binding = Inspector.CalibratedSizeBinding(display_specifier.data_item, 0, display_specifier.display, Binding.TuplePropertyBinding(rect_graphic, "size", 0))
            size_width_binding.update_source("0.6")
            self.assertEqual(center, rect_graphic.center)

    def test_calibration_inspector_section_binds(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.data_item.set_dimensional_calibration(0, Calibration.Calibration(offset=5.1, scale=1.2, units="mm"))
            inspector_section = Inspector.CalibrationsInspectorSection(document_controller, display_specifier.data_item, display_specifier.display)
            with contextlib.closing(inspector_section):
                calibration_list_widget = inspector_section._section_content_for_test.find_widget_by_id("calibration_list_widget")
                calibration_row = calibration_list_widget.find_widget_by_id("content_section").children[0]
                offset_field = calibration_row.find_widget_by_id("offset")
                scale_field = calibration_row.find_widget_by_id("scale")
                units_field = calibration_row.find_widget_by_id("units")
                self.assertEqual(offset_field.text, "5.1000")
                self.assertEqual(scale_field.text, "1.2000")
                self.assertEqual(units_field.text, u"mm")
                display_specifier.data_item.set_dimensional_calibration(0, Calibration.Calibration(offset=1.5, scale=2.1, units="mmm"))
                self.assertEqual(offset_field.text, "1.5000")
                self.assertEqual(scale_field.text, "2.1000")
                self.assertEqual(units_field.text, u"mmm")

    def test_calibration_inspector_section_follows_spatial_calibration_change(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.data_item.set_dimensional_calibration(0, Calibration.Calibration(units="mm"))
            display_specifier.data_item.set_dimensional_calibration(1, Calibration.Calibration(units="mm"))
            inspector_section = Inspector.CalibrationsInspectorSection(document_controller, display_specifier.data_item, display_specifier.display)
            with contextlib.closing(inspector_section):
                calibration_list_widget = inspector_section._section_content_for_test.find_widget_by_id("calibration_list_widget")
                calibration_row = calibration_list_widget.find_widget_by_id("content_section").children[0]
                units_field = calibration_row.find_widget_by_id("units")
                self.assertEqual(units_field.text, "mm")
                display_specifier.data_item.set_dimensional_calibration(0, Calibration.Calibration(units="mmm"))
                self.assertEqual(units_field.text, "mmm")

    def test_graphic_inspector_section_follows_spatial_calibration_change(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.display.add_graphic(Graphics.PointGraphic())
            graphic_widget = self.app.ui.create_column_widget()
            display_specifier.display.dimensional_calibration_style = "calibrated"
            display_specifier.data_item.set_dimensional_calibration(1, Calibration.Calibration(units="mm"))
            Inspector.make_point_type_inspector(document_controller, graphic_widget, display_specifier, display_specifier.display.graphics[0])
            x_widget = graphic_widget.find_widget_by_id("x")
            self.assertEqual(x_widget.text, "128.0 mm")
            display_specifier.data_item.set_dimensional_calibration(1, Calibration.Calibration(units="mmm"))
            self.assertEqual(x_widget.text, "128.0 mmm")

    def test_changing_calibration_style_to_calibrated_displays_correct_values(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((100, 100), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            point_graphic = Graphics.PointGraphic()
            display_specifier.display.add_graphic(point_graphic)
            graphic_widget = self.app.ui.create_column_widget()
            display_specifier.display.dimensional_calibration_style = "calibrated"
            display_specifier.data_item.set_dimensional_calibration(0, Calibration.Calibration(offset=-100, scale=2, units="mm"))
            display_specifier.data_item.set_dimensional_calibration(1, Calibration.Calibration(offset=-100, scale=2, units="mm"))
            Inspector.make_point_type_inspector(document_controller, graphic_widget, display_specifier, display_specifier.display.graphics[0])
            x_widget = graphic_widget.find_widget_by_id("x")
            y_widget = graphic_widget.find_widget_by_id("y")
            self.assertEqual(x_widget.text, "0.0 mm")
            self.assertEqual(y_widget.text, "0.0 mm")
            x_widget.text = "-10"
            x_widget.on_editing_finished(x_widget.text)
            y_widget.text = "20"
            y_widget.on_editing_finished(y_widget.text)
            self.assertEqual(point_graphic.position, (0.6, 0.45))

    def test_graphic_inspector_section_displays_sensible_units(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.display.add_graphic(Graphics.PointGraphic())
            graphic_widget = self.app.ui.create_column_widget()
            display_specifier.display.dimensional_calibration_style = "calibrated"
            Inspector.make_point_type_inspector(document_controller, graphic_widget, display_specifier, display_specifier.display.graphics[0])
            display_specifier.data_item.set_dimensional_calibration(1, Calibration.Calibration(scale=math.sqrt(2.0), units="mm"))
            x_widget = graphic_widget.find_widget_by_id("x")
            self.assertEqual(x_widget.text, "181.0 mm")
            display_specifier.data_item.set_dimensional_calibration(1, Calibration.Calibration(scale=math.sqrt(2.0), offset=5.55555, units="mm"))
            self.assertEqual(x_widget.text, "186.6 mm")
            display_specifier.data_item.set_dimensional_calibration(1, Calibration.Calibration(scale=math.sqrt(2.0)/10, units="mm"))
            self.assertEqual(x_widget.text, "18.10 mm")
            display_specifier.data_item.set_dimensional_calibration(1, Calibration.Calibration(scale=math.sqrt(2.0)/10, offset=0.55555, units="mm"))
            self.assertEqual(x_widget.text, "18.66 mm")
            display_specifier.data_item.set_dimensional_calibration(1, Calibration.Calibration(scale=-math.sqrt(2.0)/10, units="mm"))
            self.assertEqual(x_widget.text, "-18.10 mm")

    def test_graphic_inspector_display_calibrated_length_units(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((200, 100), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            line_region = Graphics.LineGraphic()
            line_region.start = (0, 0)
            line_region.end = (1, 1)
            display_specifier.display.add_graphic(line_region)
            graphic_widget = self.app.ui.create_column_widget()
            display_specifier.display.dimensional_calibration_style = "calibrated"
            Inspector.make_line_type_inspector(document_controller, graphic_widget, display_specifier, display_specifier.display.graphics[0])
            display_specifier.data_item.set_dimensional_calibration(0, Calibration.Calibration(units="mm"))
            display_specifier.data_item.set_dimensional_calibration(1, Calibration.Calibration(units="mm"))
            self.assertEqual(graphic_widget.find_widget_by_id("length").text, "223.607 mm")  # sqrt(100*100 + 200*200)

    def test_graphic_inspector_sets_calibrated_length_units(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((200, 100), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            line_region = Graphics.LineGraphic()
            line_region.start = (0, 0)
            line_region.end = (0.5, 0.5)
            display_specifier.display.add_graphic(line_region)
            graphic_widget = self.app.ui.create_column_widget()
            display_specifier.display.dimensional_calibration_style = "calibrated"
            Inspector.make_line_type_inspector(document_controller, graphic_widget, display_specifier, display_specifier.display.graphics[0])
            display_specifier.data_item.set_dimensional_calibration(0, Calibration.Calibration(units="mm"))
            display_specifier.data_item.set_dimensional_calibration(1, Calibration.Calibration(units="mm"))
            length_str = "{0:g}".format(math.sqrt(100 * 100 + 200 * 200))
            length_widget = graphic_widget.find_widget_by_id("length")
            length_widget.text = length_str
            length_widget.on_editing_finished(length_str)
            self.assertAlmostEqual(line_region.end[0], 1.0, 3)
            self.assertAlmostEqual(line_region.end[1], 1.0, 3)

    def test_line_profile_inspector_display_calibrated_width_units(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((200, 100), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            line_profile = Graphics.LineProfileGraphic()
            line_profile.start = (0, 0)
            line_profile.end = (1, 1)
            line_profile.width = 10
            display_specifier.display.add_graphic(line_profile)
            graphic_widget = self.app.ui.create_column_widget()
            display_specifier.display.dimensional_calibration_style = "calibrated"
            Inspector.make_line_profile_inspector(document_controller, graphic_widget, display_specifier, display_specifier.display.graphics[0])
            display_specifier.data_item.set_dimensional_calibration(0, Calibration.Calibration(units="mm"))
            display_specifier.data_item.set_dimensional_calibration(1, Calibration.Calibration(units="mm"))
            self.assertEqual(graphic_widget.find_widget_by_id("width").text, "10.0 mm")

    def test_float_to_string_converter_strips_units(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display = display_specifier.display
            display.dimensional_calibration_style = "pixels-top-left"
            converter = Inspector.CalibratedValueFloatToStringConverter(data_item, display, 0)
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
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((32, 32, 16)))
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            document_controller.selected_display_panel = None
            document_controller.selected_display_panel = display_panel
            document_controller.processing_slice()
            document_model.recompute_all()
            display_panel.set_display_panel_data_item(document_model.data_items[1])
            inspector_panel = document_controller.find_dock_widget("inspector-panel").panel
            document_controller.periodic()
            self.assertTrue(len(inspector_panel._get_inspector_sections()) > 0)

    def test_slice_inspector_section_uses_correct_dimension(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((4, 4, 32), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.display.slice_center = 16
            display_specifier.display.slice_width = 4
            slice_inspector_section = Inspector.SliceInspectorSection(document_controller, data_item, display_specifier.display)
            with contextlib.closing(slice_inspector_section):
                self.assertEqual(slice_inspector_section._slice_center_slider_widget.value, 16)
                self.assertEqual(slice_inspector_section._slice_center_slider_widget.maximum, 31)
                self.assertEqual(slice_inspector_section._slice_width_slider_widget.value, 4)
                self.assertEqual(slice_inspector_section._slice_width_slider_widget.maximum, 31)
                self.assertEqual(slice_inspector_section._slice_center_line_edit_widget.text, "16")
                self.assertEqual(slice_inspector_section._slice_width_line_edit_widget.text, "4")

    def test_image_display_inspector_shows_empty_fields_for_none_display_limits(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((4, 4), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display = display_specifier.display
            inspector_section = Inspector.ImageDisplayInspectorSection(document_controller, display)
            with contextlib.closing(inspector_section):
                display.display_limits = None
                self.assertEqual(inspector_section.display_limits_limit_low.text, None)
                self.assertEqual(inspector_section.display_limits_limit_high.text, None)
                display.display_limits = (None, None)
                self.assertEqual(inspector_section.display_limits_limit_low.text, None)
                self.assertEqual(inspector_section.display_limits_limit_high.text, None)
                display.display_limits = (1, None)
                self.assertEqual(inspector_section.display_limits_limit_low.text, "1.0000")
                self.assertEqual(inspector_section.display_limits_limit_high.text, None)
                display.display_limits = (None, 2)
                self.assertEqual(inspector_section.display_limits_limit_low.text, None)
                self.assertEqual(inspector_section.display_limits_limit_high.text, "2.0000")
                display.display_limits = (1, 2)
                self.assertEqual(inspector_section.display_limits_limit_low.text, "1.0000")
                self.assertEqual(inspector_section.display_limits_limit_high.text, "2.0000")

    def test_image_display_inspector_sets_display_limits_when_text_is_changed(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((4, 4), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display = display_specifier.display
            inspector_section = Inspector.ImageDisplayInspectorSection(document_controller, display)
            with contextlib.closing(inspector_section):
                self.assertEqual(display.display_limits, None)
                inspector_section.display_limits_limit_low.text = "1"
                inspector_section.display_limits_limit_low.editing_finished("1")
                self.assertEqual(display.display_limits, (1.0, None))
                inspector_section.display_limits_limit_high.text = "2"
                inspector_section.display_limits_limit_high.editing_finished("2")
                self.assertEqual(display.display_limits, (1.0, 2.0))
                inspector_section.display_limits_limit_low.text = ""
                inspector_section.display_limits_limit_low.editing_finished("")
                self.assertEqual(display.display_limits, (None, 2.0))
                inspector_section.display_limits_limit_high.text = ""
                inspector_section.display_limits_limit_high.editing_finished("")
                self.assertEqual(display.display_limits, None)

    def test_inspector_handles_deleted_data(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
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
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.ones((8, 8)))
            document_model.append_data_item(data_item)
            document_controller.display_data_item(DataItem.DisplaySpecifier.from_data_item(data_item))
            # document_controller.periodic()  # this makes it succeed in all cases
            document_model.remove_data_item(data_item)
            document_controller.periodic()

    def test_inspector_handles_empty_data_item(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem()
            document_model.append_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(data_item)
            document_controller.selected_display_panel = None
            document_controller.selected_display_panel = display_panel
            inspector_panel = document_controller.find_dock_widget("inspector-panel").panel
            document_controller.periodic()
            self.assertTrue(len(inspector_panel._get_inspector_sections()) > 0)

    def test_inspector_handles_all_graphics_on_1d_data(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.ones((1024, )))
            document_model.append_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(data_item)
            document_controller.selected_display_panel = None
            document_controller.selected_display_panel = display_panel
            document_controller.add_point_graphic()
            document_controller.add_line_graphic()
            document_controller.add_rectangle_graphic()
            document_controller.add_ellipse_graphic()
            document_controller.add_interval_graphic()
            data_item.displays[0].graphic_selection.clear()  # make sure all graphics show up in inspector
            self.assertTrue(len(data_item.displays[0].graphics) == 5)
            inspector_panel = document_controller.find_dock_widget("inspector-panel").panel
            document_controller.periodic()
            self.assertTrue(len(inspector_panel._get_inspector_sections()) > 0)

    def test_inspector_handles_all_graphics_on_2d_data(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.ones((256, 256)))
            document_model.append_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(data_item)
            document_controller.selected_display_panel = None
            document_controller.selected_display_panel = display_panel
            document_controller.add_point_graphic()
            document_controller.add_line_graphic()
            document_controller.add_rectangle_graphic()
            document_controller.add_ellipse_graphic()
            document_controller.add_interval_graphic()
            data_item.displays[0].graphic_selection.clear()  # make sure all graphics show up in inspector
            self.assertTrue(len(data_item.displays[0].graphics) == 5)
            inspector_panel = document_controller.find_dock_widget("inspector-panel").panel
            document_controller.periodic()
            self.assertTrue(len(inspector_panel._get_inspector_sections()) > 0)

    def test_inspector_handles_all_graphics_on_3d_data(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.ones((5, 5, 5)))
            document_model.append_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(data_item)
            document_controller.selected_display_panel = None
            document_controller.selected_display_panel = display_panel
            document_controller.add_point_graphic()
            document_controller.add_line_graphic()
            document_controller.add_rectangle_graphic()
            document_controller.add_ellipse_graphic()
            document_controller.add_interval_graphic()
            data_item.displays[0].graphic_selection.clear()  # make sure all graphics show up in inspector
            self.assertTrue(len(data_item.displays[0].graphics) == 5)
            inspector_panel = document_controller.find_dock_widget("inspector-panel").panel
            document_controller.periodic()
            self.assertTrue(len(inspector_panel._get_inspector_sections()) > 0)

    def test_updating_display_limits_on_fft_does_not_enter_update_cycle(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.random.randn(16, 16)
            d = (d - numpy.min(d)) / (numpy.amax(d) - numpy.amin(d)).astype(numpy.complex128)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(data_item)
            document_controller.selected_display_panel = None
            document_controller.selected_display_panel = display_panel
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            count = [0]
            def property_changed(property_name):
                if property_name == "display_limits":
                    count[0] += 1
            property_changed_listener = display_specifier.display.property_changed_event.listen(property_changed)
            document_model.recompute_all()
            document_model.recompute_all()
            self.assertEqual(count[0], 0)
            property_changed_listener.close()

    def test_rectangle_dimensions_show_calibrated_units(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.full((256, 256, 37), 0, dtype=numpy.uint32))  # z, y, x
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.display.add_graphic(Graphics.RectangleGraphic())
            graphic_widget = self.app.ui.create_column_widget()
            display_specifier.display.dimensional_calibration_style = "calibrated"
            display_specifier.data_item.set_dimensional_calibration(0, Calibration.Calibration(units="mm", scale=0.5))  # y
            display_specifier.data_item.set_dimensional_calibration(1, Calibration.Calibration(units="mm", scale=2.0))  # x
            Inspector.make_rectangle_type_inspector(document_controller, graphic_widget, display_specifier, display_specifier.display.graphics[0], str())
            self.assertEqual(graphic_widget.find_widget_by_id("x").text, "256.0 mm")  # x
            self.assertEqual(graphic_widget.find_widget_by_id("y").text, "64.00 mm")  # y
            self.assertEqual(graphic_widget.find_widget_by_id("width").text, "512.0 mm")  # width
            self.assertEqual(graphic_widget.find_widget_by_id("height").text, "128.00 mm")  # height

    def test_line_dimensions_show_calibrated_units(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.full((100, 100, 37), 0, dtype=numpy.uint32))  # z, y, x
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            line_graphic = Graphics.LineGraphic()
            line_graphic.start = 0.2, 0.2
            line_graphic.end = 0.8, 0.8
            display_specifier.display.add_graphic(line_graphic)
            graphic_widget = self.app.ui.create_column_widget()
            display_specifier.display.dimensional_calibration_style = "calibrated"
            display_specifier.data_item.set_dimensional_calibration(0, Calibration.Calibration(units="mm", scale=0.5))  # y
            display_specifier.data_item.set_dimensional_calibration(1, Calibration.Calibration(units="mm", scale=2.0))  # x
            Inspector.make_line_type_inspector(document_controller, graphic_widget, display_specifier, display_specifier.display.graphics[0])
            self.assertEqual(graphic_widget.find_widget_by_id("x0").text, "40.0 mm")  # x0
            self.assertEqual(graphic_widget.find_widget_by_id("y0").text, "10.00 mm")  # y0
            self.assertEqual(graphic_widget.find_widget_by_id("x1").text, "160.0 mm")  # x1
            self.assertEqual(graphic_widget.find_widget_by_id("y1").text, "40.00 mm")  # y1

    def test_point_dimensions_show_calibrated_units(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.full((256, 256, 37), 0, dtype=numpy.uint32))  # z, y, x
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.display.add_graphic(Graphics.PointGraphic())
            graphic_widget = self.app.ui.create_column_widget()
            display_specifier.display.dimensional_calibration_style = "calibrated"
            display_specifier.data_item.set_dimensional_calibration(0, Calibration.Calibration(units="mm", scale=0.5))  # y
            display_specifier.data_item.set_dimensional_calibration(1, Calibration.Calibration(units="mm", scale=2.0))  # x
            Inspector.make_point_type_inspector(document_controller, graphic_widget, display_specifier, display_specifier.display.graphics[0])
            self.assertEqual(graphic_widget.find_widget_by_id("x").text, "256.0 mm")  # x
            self.assertEqual(graphic_widget.find_widget_by_id("y").text, "64.00 mm")  # y

    def test_pixel_center_rounding_correct_on_odd_dimensioned_image(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.full((139, 89), 0, dtype=numpy.uint32))  # y, x
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            point_graphic = Graphics.PointGraphic()
            point_graphic.position = 0.5, 0.5
            display_specifier.display.add_graphic(point_graphic)
            graphic_widget = self.app.ui.create_column_widget()
            Inspector.make_point_type_inspector(document_controller, graphic_widget, display_specifier, display_specifier.display.graphics[0])
            display_specifier.display.dimensional_calibration_style = "pixels-center"
            self.assertEqual(graphic_widget.find_widget_by_id("x").text, "0.0")  # x
            self.assertEqual(graphic_widget.find_widget_by_id("y").text, "0.0")  # y

    def test_editing_pixel_width_on_rectangle_adjusts_rectangle_properly(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.full((100, 50), 0, dtype=numpy.uint32))  # y, x
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            point_graphic = Graphics.RectangleGraphic()
            display_specifier.display.add_graphic(point_graphic)
            graphic_widget = self.app.ui.create_column_widget()
            Inspector.make_rectangle_type_inspector(document_controller, graphic_widget, display_specifier, display_specifier.display.graphics[0], str())
            display_specifier.display.dimensional_calibration_style = "pixels-center"
            self.assertEqual(graphic_widget.find_widget_by_id("x").text, "0.0")  # x
            self.assertEqual(graphic_widget.find_widget_by_id("y").text, "0.0")  # y
            self.assertEqual(graphic_widget.find_widget_by_id("width").text, "50.0")  # width
            self.assertEqual(graphic_widget.find_widget_by_id("height").text, "100.0")  # height
            graphic_widget.find_widget_by_id("width").text = "40"
            graphic_widget.find_widget_by_id("width").editing_finished("40")
            self.assertEqual(graphic_widget.find_widget_by_id("x").text, "0.0")  # x
            self.assertEqual(graphic_widget.find_widget_by_id("y").text, "0.0")  # y
            self.assertEqual(graphic_widget.find_widget_by_id("width").text, "40.0")  # width
            self.assertEqual(graphic_widget.find_widget_by_id("height").text, "100.0")  # height

    def test_interval_dimensions_show_calibrated_units_on_single_spectrum(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.full((100, ), 0, dtype=numpy.uint32))  # time, energy
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            interval_graphic = Graphics.IntervalGraphic()
            interval_graphic.start = 0.2
            interval_graphic.end = 0.4
            display_specifier.display.add_graphic(interval_graphic)
            graphic_widget = self.app.ui.create_column_widget()
            display_specifier.display.dimensional_calibration_style = "calibrated"
            display_specifier.data_item.set_dimensional_calibration(0, Calibration.Calibration(units="eV", scale=2.0))  # energy
            Inspector.make_interval_type_inspector(document_controller, graphic_widget, display_specifier, display_specifier.display.graphics[0])
            self.assertEqual("40.0 eV", graphic_widget.find_widget_by_id("start").text)  # energy
            self.assertEqual("80.0 eV", graphic_widget.find_widget_by_id("end").text)  # energy

    def test_interval_dimensions_show_calibrated_units_on_sequence_of_spectra(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.full((3, 100), 0, dtype=numpy.uint32))  # time, energy
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            interval_graphic = Graphics.IntervalGraphic()
            interval_graphic.start = 0.2
            interval_graphic.end = 0.4
            display_specifier.display.add_graphic(interval_graphic)
            graphic_widget = self.app.ui.create_column_widget()
            display_specifier.display.dimensional_calibration_style = "calibrated"
            display_specifier.data_item.set_dimensional_calibration(0, Calibration.Calibration(units="s", scale=1.0))  # time
            display_specifier.data_item.set_dimensional_calibration(1, Calibration.Calibration(units="eV", scale=2.0))  # energy
            Inspector.make_interval_type_inspector(document_controller, graphic_widget, display_specifier, display_specifier.display.graphics[0])
            self.assertEqual("40.0 eV", graphic_widget.find_widget_by_id("start").text)  # energy
            self.assertEqual("80.0 eV", graphic_widget.find_widget_by_id("end").text)  # energy

    def test_calibration_inspector_updates_for_when_data_shape_changes(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((10, 10, 10)))
            document_model.append_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(data_item)
            inspector_panel = document_controller.find_dock_widget("inspector-panel").panel
            document_controller.periodic()
            self.assertIn(Inspector.SliceInspectorSection, (type(i) for i in inspector_panel._get_inspector_sections()))
            data_item.set_data(numpy.zeros((10, 10)))
            document_controller.periodic()
            self.assertNotIn(Inspector.SliceInspectorSection, (type(i) for i in inspector_panel._get_inspector_sections()))

    def test_calibration_inspector_updates_for_when_empty_data_item_displayed_as_line_plot_gets_data(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem()
            document_model.append_data_item(data_item)
            data_item.ensure_data_source()
            data_item.displays[0].add_graphic(Graphics.IntervalGraphic())
            data_item.displays[0].display_type = "line_plot"
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(data_item)
            document_controller.periodic()
            data_item.set_data(numpy.zeros((10, )))

    def test_inspector_updates_for_new_data_item(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
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
            display_panel.set_display_panel_data_item(data_item)
            inspector_panel = document_controller.find_dock_widget("inspector-panel").panel
            document_controller.periodic()
            expected_inspector_section_count = len(inspector_panel._get_inspector_sections())
            # process to add new data item
            new_data_item = document_controller.processing_invert().data_item
            # print("new_data_item {}".format(new_data_item))
            document_model.recompute_all()
            document_controller.periodic()
            new_display_panel = document_controller.selected_display_panel
            self.assertNotEqual(new_display_panel, display_panel)
            self.assertEqual(new_display_panel.data_item, new_data_item)
            actual_inspector_section_count = len(inspector_panel._get_inspector_sections())
            self.assertEqual(expected_inspector_section_count, actual_inspector_section_count)

    def test_data_item_with_no_data_displays_as_line_plot(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem()
            document_model.append_data_item(data_item)
            data_item.ensure_data_source()
            data_item.displays[0].display_type = "line_plot"
            display_panel.set_display_panel_data_item(data_item)
            inspector_panel = document_controller.find_dock_widget("inspector-panel").panel
            document_controller.periodic()

    def test_inspector_updates_when_graphic_associated_with_pick_is_deleted(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((16, 16, 64)))
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            inspector_panel = document_controller.find_dock_widget("inspector-panel").panel
            document_controller.periodic()
            expected_inspector_section_count = len(inspector_panel._get_inspector_sections())
            # add the point graphic, ensure that inspector is updated with just a section for point graphic
            self.assertEqual(len(document_controller.selected_display_specifier.display.graphic_selection.indexes), 0)  # make sure graphic is not selected
            document_model.get_pick_new(data_item)
            self.assertEqual(document_controller.selected_display_specifier.data_item, data_item)
            document_controller.selected_display_specifier.display.graphic_selection.add(0)
            document_controller.periodic()
            graphic_inspector_section_count = len(inspector_panel._get_inspector_sections())
            self.assertNotEqual(expected_inspector_section_count, graphic_inspector_section_count)
            # now remove the point graphic and ensure that inspector inspecting data item again
            self.assertEqual(len(document_controller.selected_display_specifier.display.graphic_selection.indexes), 1)  # make sure graphic is selected
            document_controller.remove_selected_graphics()
            document_controller.periodic()
            self.assertEqual(len(document_controller.selected_display_specifier.display.graphic_selection.indexes), 0)  # make sure graphic is not selected
            actual_inspector_section_count = len(inspector_panel._get_inspector_sections())
            self.assertEqual(expected_inspector_section_count, actual_inspector_section_count)

    def test_graphic_inspector_updates_for_when_data_shape_changes(self):
        # change from 2d item with a rectangle to a 1d item. what happens?
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((16, 16)))
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            inspector_panel = document_controller.find_dock_widget("inspector-panel").panel
            document_controller.periodic()
            self.assertNotIn(Inspector.LinePlotDisplayInspectorSection, (type(i) for i in inspector_panel._get_inspector_sections()))
            data_item.set_data(numpy.zeros((10, )))
            document_controller.periodic()
            self.assertIn(Inspector.LinePlotDisplayInspectorSection, (type(i) for i in inspector_panel._get_inspector_sections()))
            data_item.set_data(numpy.zeros((10, 10)))
            document_controller.periodic()
            self.assertNotIn(Inspector.LinePlotDisplayInspectorSection, (type(i) for i in inspector_panel._get_inspector_sections()))

    def test_calibration_inspector_shows_correct_labels_for_1d(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((8, )))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            inspector_section = Inspector.CalibrationsInspectorSection(document_controller, display_specifier.data_item, display_specifier.display)
            with contextlib.closing(inspector_section):
                calibration_list_widget = inspector_section._section_content_for_test.find_widget_by_id("calibration_list_widget")
                content_section = calibration_list_widget.find_widget_by_id("content_section")
                self.assertEqual(len(content_section.children), 1)
                calibration_row = content_section.children[0]
                label = calibration_row.find_widget_by_id("label")
                self.assertEqual(label.text, "Channel")

    def test_calibration_inspector_shows_correct_labels_for_2d(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            inspector_section = Inspector.CalibrationsInspectorSection(document_controller, display_specifier.data_item, display_specifier.display)
            with contextlib.closing(inspector_section):
                calibration_list_widget = inspector_section._section_content_for_test.find_widget_by_id("calibration_list_widget")
                content_section = calibration_list_widget.find_widget_by_id("content_section")
                self.assertEqual(len(content_section.children), 2)
                self.assertEqual(content_section.children[0].find_widget_by_id("label").text, "Y")
                self.assertEqual(content_section.children[1].find_widget_by_id("label").text, "X")

    def test_calibration_inspector_shows_correct_labels_for_3d(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((8, 8, 16)))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            inspector_section = Inspector.CalibrationsInspectorSection(document_controller, display_specifier.data_item, display_specifier.display)
            with contextlib.closing(inspector_section):
                calibration_list_widget = inspector_section._section_content_for_test.find_widget_by_id("calibration_list_widget")
                content_section = calibration_list_widget.find_widget_by_id("content_section")
                self.assertEqual(len(content_section.children), 3)
                self.assertEqual(content_section.children[0].find_widget_by_id("label").text, "0")
                self.assertEqual(content_section.children[1].find_widget_by_id("label").text, "1")
                self.assertEqual(content_section.children[2].find_widget_by_id("label").text, "2")

    def test_computation_inspector_updates_when_computation_variable_type_changes(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            x = computation.create_variable("x", "integral", 0)
            document_model.set_data_item_computation(data_item, computation)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(data_item)
            inspector_panel = document_controller.find_dock_widget("inspector-panel").panel
            document_controller.periodic()
            inspector_section = next(x for x in inspector_panel._get_inspector_sections() if isinstance(x, Inspector.ComputationInspectorSection))
            line_edit_widget1 = inspector_section._variables_column_widget.children[0].content_widget.find_widget_by_id("value")
            line_edit_widget1.editing_finished("1")
            self.assertEqual(x.value, 1)
            x.value_type = "real"
            document_controller.periodic()
            line_edit_widget2 = inspector_section._variables_column_widget.children[0].content_widget.find_widget_by_id("value")
            line_edit_widget2.editing_finished("1.1")
            self.assertEqual(x.value, 1.1)

    def test_computation_inspector_handles_computation_variable_checkbox_and_undo_redo_cycle(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            new_data_item = document_model.get_transpose_flip_new(data_item)
            document_model.recompute_all()
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(new_data_item)
            inspector_panel = document_controller.find_dock_widget("inspector-panel").panel
            document_controller.periodic()
            computation = document_model.get_data_item_computation(new_data_item)
            self.assertFalse(computation._get_variable("do_transpose").value)
            inspector_section = next(x for x in inspector_panel._get_inspector_sections() if isinstance(x, Inspector.ComputationInspectorSection))
            cb_widget = inspector_section.find_widget_by_id("value")
            cb_widget.on_checked_changed(True)
            self.assertTrue(computation._get_variable("do_transpose").value)
            document_controller.handle_undo()
            self.assertFalse(computation._get_variable("do_transpose").value)
            document_controller.handle_redo()
            self.assertTrue(computation._get_variable("do_transpose").value)

    def test_computation_inspector_handles_computation_variable_slider_and_undo_redo_cycle(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            new_data_item = document_model.get_gaussian_blur_new(data_item)
            document_model.recompute_all()
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(new_data_item)
            inspector_panel = document_controller.find_dock_widget("inspector-panel").panel
            document_controller.periodic()
            computation = document_model.get_data_item_computation(new_data_item)
            old_sigma = computation._get_variable("sigma").value
            inspector_section = next(x for x in inspector_panel._get_inspector_sections() if isinstance(x, Inspector.ComputationInspectorSection))
            slider_widget = inspector_section.find_widget_by_id("value")
            slider_widget.on_value_changed(0)
            self.assertEqual(0, computation._get_variable("sigma").value)
            document_controller.handle_undo()
            self.assertEqual(old_sigma, computation._get_variable("sigma").value)
            document_controller.handle_redo()
            self.assertEqual(0, computation._get_variable("sigma").value)

    def test_computation_inspector_handles_computation_variable_int_and_undo_redo_cycle(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            new_data_item = document_model.get_histogram_new(data_item)
            document_model.recompute_all()
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(new_data_item)
            inspector_panel = document_controller.find_dock_widget("inspector-panel").panel
            document_controller.periodic()
            computation = document_model.get_data_item_computation(new_data_item)
            old_bins = computation._get_variable("bins").value
            inspector_section = next(x for x in inspector_panel._get_inspector_sections() if isinstance(x, Inspector.ComputationInspectorSection))
            field_widget = inspector_section.find_widget_by_id("value")
            field_widget.on_editing_finished("100")
            self.assertEqual(100, computation._get_variable("bins").value)
            document_controller.handle_undo()
            self.assertEqual(old_bins, computation._get_variable("bins").value)
            document_controller.handle_redo()
            self.assertEqual(100, computation._get_variable("bins").value)

    def test_computation_inspector_handles_computation_variable_specifier_and_undo_redo_cycle(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            new_data_item = document_model.get_invert_new(data_item)
            document_model.recompute_all()
            computation = document_model.get_data_item_computation(new_data_item)
            self.assertEqual(data_item, list(computation._get_variable("src").bound_item.base_objects)[0])
            specifier = {"type": "data_item", "version": 1, "uuid": str(uuid.uuid4())}
            command = Inspector.ChangeComputationVariableCommand(document_model, computation, computation._get_variable("src"), specifier=specifier)
            command.perform()
            document_controller.push_undo_command(command)
            self.assertIsNone(computation._get_variable("src").bound_item)
            self.assertTrue(document_controller._undo_stack.can_undo)
            document_controller.handle_undo()
            self.assertEqual(data_item, list(computation._get_variable("src").bound_item.base_objects)[0])
            document_controller.handle_redo()
            self.assertIsNone(computation._get_variable("src").bound_item)

    def test_change_property_command_multiple_undo(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
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
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
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
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
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
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
            document_model.append_data_item(data_item)
            command = Inspector.ChangeDimensionalCalibrationsCommand(document_model, data_item, [Calibration.Calibration(scale=2), Calibration.Calibration(scale=3)])
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual([Calibration.Calibration(scale=2), Calibration.Calibration(scale=3)], data_item.dimensional_calibrations)
            document_controller.handle_undo()
            self.assertEqual([Calibration.Calibration(), Calibration.Calibration()], data_item.dimensional_calibrations)
            document_controller.handle_redo()
            self.assertEqual([Calibration.Calibration(scale=2), Calibration.Calibration(scale=3)], data_item.dimensional_calibrations)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
