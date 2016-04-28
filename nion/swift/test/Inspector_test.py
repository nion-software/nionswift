# futures
from __future__ import absolute_import

# standard libraries
import contextlib
import locale
import logging
import math
import unittest

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift import Inspector
from nion.swift.model import Cache
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.ui import Test
from nion.utils import Binding
from nion.utils import Observable


class TestInspectorClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_info_inspector_section_follows_title_change(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item.title = "Title1"
        inspector_section = Inspector.InfoInspectorSection(self.app.ui, data_item)
        self.assertEqual(inspector_section.info_title_label.text, "Title1")
        data_item.title = "Title2"
        self.assertEqual(inspector_section.info_title_label.text, "Title2")

    def test_display_limits_inspector_should_bind_to_display_without_errors(self):
        cache_name = ":memory:"
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        document_model.append_data_item(data_item)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        # configure the inspectors
        document_controller.notify_selected_data_item_changed(data_item)
        document_controller.periodic()  # force UI to update
        document_controller.notify_selected_data_item_changed(None)
        # clean up
        document_controller.close()

    def test_calibration_value_and_size_float_to_string_converter_works_with_display(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        converter = Inspector.CalibratedValueFloatToStringConverter(display_specifier.buffered_data_source, 0, 256)
        converter.convert(0.5)
        converter = Inspector.CalibratedSizeFloatToStringConverter(display_specifier.buffered_data_source, 0, 256)
        converter.convert(0.5)

    # necessary to make inspector display updated values properly
    def test_adjusting_rectangle_width_should_keep_center_constant(self):
        rect_graphic = Graphics.RectangleGraphic()
        rect_graphic.bounds = ((0.25, 0.25), (0.5, 0.5))
        center = rect_graphic.center
        class BoolModel(Observable.Observable):
            def __init__(self):
                super(BoolModel, self).__init__()
                self.display_calibrated_values = False
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        y_converter = Inspector.CalibratedValueFloatToStringConverter(display_specifier.buffered_data_source, 0, 256)
        height_converter = Inspector.CalibratedSizeFloatToStringConverter(display_specifier.buffered_data_source, 0, 256)
        bool_model = BoolModel()
        display_calibrated_values_binding = Binding.PropertyBinding(bool_model, "display_calibrated_values")
        display_calibrated_values_binding2 = Binding.PropertyBinding(bool_model, "display_calibrated_values")
        center_y_binding = Inspector.CalibratedValueBinding(display_specifier.buffered_data_source, Binding.TuplePropertyBinding(rect_graphic, "center", 0), display_calibrated_values_binding, y_converter)
        size_width_binding = Inspector.CalibratedValueBinding(display_specifier.buffered_data_source, Binding.TuplePropertyBinding(rect_graphic, "size", 0), display_calibrated_values_binding2, height_converter)
        size_width_binding.update_source("0.6")
        self.assertEqual(center, rect_graphic.center)

    def test_calibration_inspector_section_binds(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display_specifier.buffered_data_source.set_dimensional_calibration(0, Calibration.Calibration(offset=5.1, scale=1.2, units="mm"))
        inspector_section = Inspector.CalibrationsInspectorSection(self.app.ui, display_specifier.data_item, display_specifier.buffered_data_source, display_specifier.display)
        content_section = inspector_section._section_content_for_test.children[0].content_section
        calibration_row = content_section.children[0].children[0]
        offset_field = calibration_row.children[1]
        scale_field = calibration_row.children[2]
        units_field = calibration_row.children[3]
        self.assertEqual(offset_field.text, "5.1000")
        self.assertEqual(scale_field.text, "1.2000")
        self.assertEqual(units_field.text, u"mm")
        display_specifier.buffered_data_source.set_dimensional_calibration(0, Calibration.Calibration(offset=1.5, scale=2.1, units="mmm"))
        self.assertEqual(offset_field.text, "1.5000")
        self.assertEqual(scale_field.text, "2.1000")
        self.assertEqual(units_field.text, u"mmm")

    def test_calibration_inspector_section_follows_spatial_calibration_change(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display_specifier.buffered_data_source.set_dimensional_calibration(0, Calibration.Calibration(units="mm"))
        display_specifier.buffered_data_source.set_dimensional_calibration(1, Calibration.Calibration(units="mm"))
        inspector_section = Inspector.CalibrationsInspectorSection(self.app.ui, display_specifier.data_item, display_specifier.buffered_data_source, display_specifier.display)
        self.assertEqual(inspector_section._section_content_for_test.children[0].content_section.children[0].children[0].children[3].text, "mm")
        display_specifier.buffered_data_source.set_dimensional_calibration(0, Calibration.Calibration(units="mmm"))
        self.assertEqual(inspector_section._section_content_for_test.children[0].content_section.children[0].children[0].children[3].text, "mmm")

    def test_graphic_inspector_section_follows_spatial_calibration_change(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display_specifier.display.add_graphic(Graphics.PointGraphic())
        graphic_widget = self.app.ui.create_column_widget()
        display_specifier.display.display_calibrated_values = True
        display_specifier.buffered_data_source.set_dimensional_calibration(1, Calibration.Calibration(units="mm"))
        Inspector.make_point_type_inspector(self.app.ui, graphic_widget, display_specifier, display_specifier.buffered_data_source.dimensional_shape, display_specifier.display.graphics[0])
        self.assertEqual(graphic_widget.children[0].children[0].children[1].text, "128.0 mm")
        display_specifier.buffered_data_source.set_dimensional_calibration(1, Calibration.Calibration(units="mmm"))
        self.assertEqual(graphic_widget.children[0].children[0].children[1].text, "128.0 mmm")

    def test_graphic_inspector_section_displays_sensible_units(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display_specifier.display.add_graphic(Graphics.PointGraphic())
        graphic_widget = self.app.ui.create_column_widget()
        display_specifier.display.display_calibrated_values = True
        Inspector.make_point_type_inspector(self.app.ui, graphic_widget, display_specifier, display_specifier.buffered_data_source.dimensional_shape, display_specifier.display.graphics[0])
        display_specifier.buffered_data_source.set_dimensional_calibration(1, Calibration.Calibration(scale=math.sqrt(2.0), units="mm"))
        self.assertEqual(graphic_widget.children[0].children[0].children[1].text, "181.0 mm")
        display_specifier.buffered_data_source.set_dimensional_calibration(1, Calibration.Calibration(scale=math.sqrt(2.0), offset=5.55555, units="mm"))
        self.assertEqual(graphic_widget.children[0].children[0].children[1].text, "186.6 mm")
        display_specifier.buffered_data_source.set_dimensional_calibration(1, Calibration.Calibration(scale=math.sqrt(2.0)/10, units="mm"))
        self.assertEqual(graphic_widget.children[0].children[0].children[1].text, "18.10 mm")
        display_specifier.buffered_data_source.set_dimensional_calibration(1, Calibration.Calibration(scale=math.sqrt(2.0)/10, offset=0.55555, units="mm"))
        self.assertEqual(graphic_widget.children[0].children[0].children[1].text, "18.66 mm")
        display_specifier.buffered_data_source.set_dimensional_calibration(1, Calibration.Calibration(scale=-math.sqrt(2.0)/10, units="mm"))
        self.assertEqual(graphic_widget.children[0].children[0].children[1].text, "-18.10 mm")

    def test_graphic_inspector_display_calibrated_length_units(self):
        data_item = DataItem.DataItem(numpy.zeros((200, 100), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        line_region = Graphics.LineGraphic()
        line_region.start = (0, 0)
        line_region.end = (1, 1)
        display_specifier.display.add_graphic(line_region)
        graphic_widget = self.app.ui.create_column_widget()
        display_specifier.display.display_calibrated_values = True
        Inspector.make_line_type_inspector(self.app.ui, graphic_widget, display_specifier, display_specifier.buffered_data_source.dimensional_shape, display_specifier.display.graphics[0])
        display_specifier.buffered_data_source.set_dimensional_calibration(0, Calibration.Calibration(units="mm"))
        display_specifier.buffered_data_source.set_dimensional_calibration(1, Calibration.Calibration(units="mm"))
        self.assertEqual(graphic_widget.children[2].children[0].children[1].text, "223.607 mm")  # sqrt(100*100 + 200*200)

    def test_graphic_inspector_sets_calibrated_length_units(self):
        data_item = DataItem.DataItem(numpy.zeros((200, 100), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        line_region = Graphics.LineGraphic()
        line_region.start = (0, 0)
        line_region.end = (0.5, 0.5)
        display_specifier.display.add_graphic(line_region)
        graphic_widget = self.app.ui.create_column_widget()
        display_specifier.display.display_calibrated_values = True
        Inspector.make_line_type_inspector(self.app.ui, graphic_widget, display_specifier, display_specifier.buffered_data_source.dimensional_shape, display_specifier.display.graphics[0])
        display_specifier.buffered_data_source.set_dimensional_calibration(0, Calibration.Calibration(units="mm"))
        display_specifier.buffered_data_source.set_dimensional_calibration(1, Calibration.Calibration(units="mm"))
        length_str = "{0:g}".format(math.sqrt(100 * 100 + 200 * 200))
        graphic_widget.children[2].children[0].children[1].text = length_str
        graphic_widget.children[2].children[0].children[1].on_editing_finished(length_str)
        self.assertAlmostEqual(line_region.end[0], 1.0, 3)
        self.assertAlmostEqual(line_region.end[1], 1.0, 3)

    def test_float_to_string_converter_strips_units(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        buffered_data_source = display_specifier.buffered_data_source
        converter = Inspector.CalibratedValueFloatToStringConverter(buffered_data_source, 0, 256)
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
        display_panel = document_controller.selected_display_panel
        data_item = DataItem.DataItem(numpy.zeros((16, 32, 32)))
        document_model.append_data_item(data_item)
        display_panel.set_displayed_data_item(data_item)
        document_controller.selected_display_panel = None
        document_controller.selected_display_panel = display_panel
        document_controller.processing_slice()
        document_model.recompute_all()
        display_panel.set_displayed_data_item(document_model.data_items[1])
        inspector_panel = document_controller.find_dock_widget("inspector-panel").panel
        document_controller.periodic()
        self.assertTrue(len(inspector_panel._get_inspector_sections()) > 0)
        document_controller.close()

    def test_inspector_handles_deleted_data(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((32, 32)))
        document_model.append_data_item(data_item)
        document_controller.data_browser_controller.focused = True
        document_controller.periodic()
        document_controller.data_browser_controller.set_data_browser_selection(data_item=data_item)  # queues the update
        document_model.remove_data_item(data_item)  # removes item while still in queue
        document_controller.periodic()  # execute queue
        document_controller.close()

    def test_inspector_handles_deleted_data_being_displayed(self):
        # if the inspector doesn't watch for the item being deleted, and the inspector's update display
        # doesn't get called during periodic before the item is deleted (which will naturally happen sometimes),
        # then there will be a pending call using a data item that doesn't exist.
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.ones((8, 8)))
        document_model.append_data_item(data_item)
        document_controller.display_data_item(DataItem.DisplaySpecifier.from_data_item(data_item))
        # document_controller.periodic()  # this makes it succeed in all cases
        document_model.remove_data_item(data_item)
        document_controller.periodic()
        document_controller.close()

    def test_inspector_handles_empty_data_item(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem()
        document_model.append_data_item(data_item)
        display_panel = document_controller.selected_display_panel
        display_panel.set_displayed_data_item(data_item)
        document_controller.selected_display_panel = None
        document_controller.selected_display_panel = display_panel
        inspector_panel = document_controller.find_dock_widget("inspector-panel").panel
        document_controller.periodic()
        self.assertTrue(len(inspector_panel._get_inspector_sections()) > 0)
        document_controller.close()

    def test_inspector_handles_all_graphics_on_1d_data(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.ones((1024, )))
            document_model.append_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_displayed_data_item(data_item)
            document_controller.selected_display_panel = None
            document_controller.selected_display_panel = display_panel
            document_controller.add_point_graphic()
            document_controller.add_line_graphic()
            document_controller.add_rectangle_graphic()
            document_controller.add_ellipse_graphic()
            document_controller.add_interval_graphic()
            data_item.maybe_data_source.displays[0].graphic_selection.clear()  # make sure all graphics show up in inspector
            self.assertTrue(len(data_item.maybe_data_source.displays[0].graphics) == 5)
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
            display_panel.set_displayed_data_item(data_item)
            document_controller.selected_display_panel = None
            document_controller.selected_display_panel = display_panel
            document_controller.add_point_graphic()
            document_controller.add_line_graphic()
            document_controller.add_rectangle_graphic()
            document_controller.add_ellipse_graphic()
            document_controller.add_interval_graphic()
            data_item.maybe_data_source.displays[0].graphic_selection.clear()  # make sure all graphics show up in inspector
            self.assertTrue(len(data_item.maybe_data_source.displays[0].graphics) == 5)
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
            display_panel.set_displayed_data_item(data_item)
            document_controller.selected_display_panel = None
            document_controller.selected_display_panel = display_panel
            document_controller.add_point_graphic()
            document_controller.add_line_graphic()
            document_controller.add_rectangle_graphic()
            document_controller.add_ellipse_graphic()
            document_controller.add_interval_graphic()
            data_item.maybe_data_source.displays[0].graphic_selection.clear()  # make sure all graphics show up in inspector
            self.assertTrue(len(data_item.maybe_data_source.displays[0].graphics) == 5)
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
            display_panel.set_displayed_data_item(data_item)
            document_controller.selected_display_panel = None
            document_controller.selected_display_panel = display_panel
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            count = [0]
            def property_changed(property_name, value):
                if property_name == "display_limits":
                    count[0] += 1
            property_changed_listener = display_specifier.display.property_changed_event.listen(property_changed)
            document_model.recompute_all()
            document_model.recompute_all()
            self.assertEqual(count[0], 0)
            property_changed_listener.close()

    def disabled_test_corrupt_data_item_should_not_completely_disable_the_inspector(self):
        # a corrupt display panel (wrong dimensional calibrations, for instance) should not affect the other display
        # panels; nor should it affect the focus functionality
        raise Exception()


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
