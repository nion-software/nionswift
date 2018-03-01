# standard libraries
import contextlib
import copy
import functools
import json
import math
import unittest

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift import Facade
from nion.swift.model import DataItem
from nion.swift.model import Display
from nion.swift.model import DocumentModel
from nion.swift.model import Utility
from nion.ui import TestUI


Facade.initialize()


class TestDisplayClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_setting_inverted_display_limits_reverses_them(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        display.display_limits = (0.75, 0.25)
        self.assertEqual(display.display_limits, (0.25, 0.75))
        display.display_limits = None
        self.assertIsNone(display.display_limits)

    def test_setting_partial_display_limits_works(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        display.display_limits = None
        self.assertIsNone(display.display_limits)
        display.display_limits = (0.25,)
        self.assertEqual(display.display_limits, (0.25, None))
        display.display_limits = (0.25, None)
        self.assertEqual(display.display_limits, (0.25, None))
        display.display_limits = (None, 0.75)
        self.assertEqual(display.display_limits, (None, 0.75))
        display.display_limits = (None,)
        self.assertIsNone(display.display_limits)
        display.display_limits = (None, None)
        self.assertIsNone(display.display_limits)

    def test_setting_partial_display_limits_write_and_read_when_read_back_as_list(self):
        display = Display.Display()
        display.display_limits = (None, 10)
        j = json.dumps(display.write_to_dict())
        display.read_from_dict(Utility.clean_dict(json.loads(j)))
        self.assertEqual((None, 10), display.display_limits)

    def test_display_range_with_partial_display_limits_is_complete(self):
        data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.float64))
        display = data_item.displays[0]
        data_item.set_data(numpy.array(range(1,5)))
        display.display_limits = None
        self.assertEqual(display.get_calculated_display_values(True).display_range, (1.0, 4.0))
        display.display_limits = (2.0, None)
        self.assertEqual(display.get_calculated_display_values(True).display_range, (2.0, 4.0))
        display.display_limits = (None, 3.0)
        self.assertEqual(display.get_calculated_display_values(True).display_range, (1.0, 3.0))
        display.display_limits = (2.0, 3.0)
        self.assertEqual(display.get_calculated_display_values(True).display_range, (2.0, 3.0))

    def test_display_produces_valid_preview_when_viewing_3d_data_set(self):
        data_item = DataItem.DataItem(numpy.zeros((16, 16, 16), numpy.float64))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        self.assertIsNotNone(display.get_calculated_display_values(True).display_data_and_metadata)

    def test_preview_2d_shape_of_3d_data_set_has_correct_dimensions(self):
        data_item = DataItem.DataItem(numpy.zeros((16, 16, 64), numpy.float64))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        self.assertEqual(display_specifier.display.preview_2d_shape, (16, 16))

    def test_display_data_of_3d_data_set_has_correct_shape_and_calibrations(self):
        intensity_calibration = Calibration.Calibration(units="I")
        dim0_calibration = Calibration.Calibration(units="A")
        dim1_calibration = Calibration.Calibration(units="B")
        dim2_calibration = Calibration.Calibration(units="C")
        data_item = DataItem.DataItem(numpy.zeros((16, 16, 64), numpy.float64))
        data_item.set_intensity_calibration(intensity_calibration)
        data_item.set_dimensional_calibrations([dim0_calibration, dim1_calibration, dim2_calibration])
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display_data_and_metadata = display_specifier.display.get_calculated_display_values(True).display_data_and_metadata
        self.assertEqual(display_data_and_metadata.dimensional_shape, (16, 16))
        self.assertEqual(display_data_and_metadata.intensity_calibration, intensity_calibration)
        self.assertEqual(display_data_and_metadata.dimensional_calibrations[0], dim0_calibration)
        self.assertEqual(display_data_and_metadata.dimensional_calibrations[1], dim1_calibration)

    def test_changing_data_updates_display_range(self):
        irow, icol = numpy.ogrid[0:16, 0:16]
        data_item = DataItem.DataItem(icol, numpy.uint32)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        self.assertEqual(display.get_calculated_display_values(True).display_range, (0, 15))
        self.assertEqual(display.get_calculated_display_values(True).data_range, (0, 15))
        display_specifier.data_item.set_data(irow // 2 + 4)
        self.assertEqual(display.get_calculated_display_values(True).display_range, (4, 11))
        self.assertEqual(display.get_calculated_display_values(True).data_range, (4, 11))

    def test_changing_sequence_index_updates_display_range(self):
        data = numpy.zeros((3, 8, 8))
        data[1, ...] = 1
        data[2, ...] = 2
        xdata = DataAndMetadata.new_data_and_metadata(data, data_descriptor=DataAndMetadata.DataDescriptor(True, 0, 2))
        data_item = DataItem.new_data_item(xdata)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        self.assertEqual(display.get_calculated_display_values(True).display_range, (0, 0))
        self.assertEqual(display.get_calculated_display_values(True).data_range, (0, 0))
        display.sequence_index = 1
        self.assertEqual(display.get_calculated_display_values(True).display_range, (1, 1))
        self.assertEqual(display.get_calculated_display_values(True).data_range, (1, 1))

    def test_changing_data_notifies_data_and_display_range_change(self):
        # this is used to update the inspector
        irow, icol = numpy.ogrid[0:16, 0:16]
        data_item = DataItem.DataItem(icol, numpy.uint32)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        class Observer(object):
            def __init__(self):
                self.data_range = None
                self.display_range = None
            def next_calculated_display_values(self):
                calculated_display_values = display.get_calculated_display_values(True)
                self.display_range = calculated_display_values.display_range
                self.data_range = calculated_display_values.data_range
        o = Observer()
        listener = display.add_calculated_display_values_listener(o.next_calculated_display_values)
        # wait for initial display values to update.
        with contextlib.closing(listener):
            display_specifier.data_item.set_data(irow // 2 + 4)
            self.assertEqual(o.data_range, (4, 11))
            self.assertEqual(o.display_range, (4, 11))

    def test_data_item_copy_initialized_display_data_range(self):
        source_data_item = DataItem.DataItem(numpy.zeros((16, 16, 16), numpy.float64))
        data_item = copy.deepcopy(source_data_item)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        self.assertIsNotNone(display_specifier.display.get_calculated_display_values(True).data_range)

    def test_data_item_setting_slice_width_validates_when_invalid(self):
        data_item = DataItem.DataItem(numpy.ones((4, 4, 16), numpy.float64))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display_specifier.display.slice_center = 8
        display_specifier.display.slice_width = 0
        self.assertEqual(display_specifier.display.slice_width, 1)
        display_specifier.display.slice_width = -1
        self.assertEqual(display_specifier.display.slice_width, 1)
        display_specifier.display.slice_width = 20
        self.assertEqual(display_specifier.display.slice_width, 16)

    def test_data_item_setting_slice_center_validates_when_invalid(self):
        data_item = DataItem.DataItem(numpy.ones((4, 4, 16), numpy.float64))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display_specifier.display.slice_center = 8
        display_specifier.display.slice_width = 8
        display_specifier.display.slice_center = 0
        self.assertEqual(display_specifier.display.slice_center, 4)
        display_specifier.display.slice_center = 3
        self.assertEqual(display_specifier.display.slice_center, 4)
        display_specifier.display.slice_center = -1
        self.assertEqual(display_specifier.display.slice_center, 4)
        display_specifier.display.slice_center = 5.5
        self.assertEqual(display_specifier.display.slice_center, 5)
        display_specifier.display.slice_center = 12
        self.assertEqual(display_specifier.display.slice_center, 12)
        display_specifier.display.slice_center = 13
        self.assertEqual(display_specifier.display.slice_center, 12)
        display_specifier.display.slice_center = 20
        self.assertEqual(display_specifier.display.slice_center, 12)

    def test_data_item_setting_slice_validates_when_data_changes(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.random.randn(4, 4, 12)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            map = {"a": document_model.get_object_specifier(data_item)}
            data_item2 = document_controller.processing_computation("target.xdata = a.xdata[:,:,0:8]", map)
            document_model.recompute_all()
            assert numpy.array_equal(data_item2.data, d[:, :, 0:8])
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item2)
            display_specifier.display.slice_center = 6
            display_specifier.display.slice_width = 4
            self.assertEqual(display_specifier.display.slice_center, 6)
            self.assertEqual(display_specifier.display.slice_width, 4)
            document_model.get_data_item_computation(display_specifier.data_item).expression = "target.xdata = a.xdata[:, :, 0:4]"
            document_model.recompute_all()
            self.assertEqual(display_specifier.display.slice_center, 3)
            self.assertEqual(display_specifier.display.slice_width, 2)

    def test_setting_slice_interval_scales_to_correct_dimension(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.random.randn(4, 4, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.display.slice_interval = 0.4, 0.6
            # there is some rounding sloppiness... let it go for now
            self.assertTrue(39 <= int(d.shape[2] * display_specifier.display.slice_interval[0]) <= 41)
            self.assertTrue(display_specifier.display.slice_center == 50)
            self.assertTrue(19 <= display_specifier.display.slice_width <= 21)

    def test_changing_slice_width_updates_data_range(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.zeros((8, 8, 4), numpy.uint32)
            for i in range(4):
                d[..., i] = i
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.assertEqual(display_specifier.display.get_calculated_display_values(True).data_range, (0, 0))
            display_specifier.display.slice_center = 2
            display_specifier.display.slice_width = 4
            self.assertEqual(display_specifier.display.get_calculated_display_values(True).data_range, (6, 6))

    def test_display_data_is_scalar_for_1d_complex(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.ones((16,), numpy.complex128)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.assertEqual(display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data_dtype, numpy.float64)

    def test_display_data_is_scalar_for_2d_complex(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.ones((16, 16), numpy.complex128)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.assertEqual(display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data_dtype, numpy.float64)

    def test_display_data_is_rgba_for_2d_rgba(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.ones((16, 16, 4), numpy.uint8)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.assertEqual(display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data_dtype, numpy.uint8)
            self.assertEqual(display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data_shape[-1], 4)

    def test_display_data_is_2d_for_3d(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.ones((16, 16, 8), numpy.float64)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.assertEqual(display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data_shape, (16, 16))
            self.assertEqual(display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data_dtype, numpy.float64)

    def test_display_data_is_2d_scalar_for_3d_complex(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.ones((16, 16, 8), numpy.complex128)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.assertEqual(display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data_shape, (16, 16))
            self.assertEqual(display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data_dtype, numpy.float64)

    def test_image_with_no_data_displays_gracefully(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.ones((8,), numpy.float))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.data_item.set_xdata(DataAndMetadata.DataAndMetadata(lambda: None, ((8, 0), numpy.float)))
            display_specifier.display.display_type = "image"
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(data_item)
            display_panel.display_canvas_item.layout_immediate((640, 480))

    def test_setting_color_map_id_to_none_works(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.float64))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.display.color_map_id = None
            self.assertEqual(display_specifier.display.color_map_id, None)
            self.assertIsNotNone(display_specifier.display.color_map_data)

    def test_setting_color_map_id_to_valid_value_works(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.float64))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.display.color_map_id = 'ice'
            self.assertEqual(display_specifier.display.color_map_id, 'ice')
            self.assertIsNotNone(display_specifier.display.color_map_data)

    def test_setting_color_map_id_to_invalid_value_works(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.float64))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.display.color_map_id = 'elephant'
            self.assertEqual(display_specifier.display.color_map_id, 'elephant')
            self.assertIsNotNone(display_specifier.display.color_map_data)

    def test_reset_display_limits_resets_display_limits_to_none(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.float))
            data_item.displays[0].display_limits = 0.5, 1.5
            self.assertIsNotNone(data_item.displays[0].display_limits)  # check assumptions
            data_item.displays[0].reset_display_limits()
            self.assertIsNone(data_item.displays[0].display_limits)
            preview = data_item.displays[0].get_calculated_display_values(True).display_rgba
            self.assertIsNotNone(preview)

    def test_display_rgba_for_various_data_types_is_valid(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            dtypes = (numpy.uint16, numpy.int16, numpy.uint32, numpy.int32, numpy.uint64, numpy.int64, numpy.float32, numpy.float64, numpy.complex64, numpy.complex128)
            for dtype in dtypes:
                data_item = DataItem.DataItem(numpy.ones((16, 16), dtype))
                for display_limits in ((0, 1), (0.5, 1.5)):
                    data_item.displays[0].display_limits = display_limits
                    display_rgba = data_item.displays[0].get_calculated_display_values(True).display_rgba
                    self.assertTrue(display_rgba.dtype == numpy.uint32)

    def test_reset_display_limits_on_various_value_types_write_to_clean_json(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            dtypes = (numpy.float32, numpy.float64, numpy.complex64, numpy.complex128, numpy.int16, numpy.uint16, numpy.int32, numpy.uint32)
            for dtype in dtypes:
                data_item = DataItem.DataItem(numpy.ones((16, 16), dtype))
                document_model.append_data_item(data_item)
                display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
                display_specifier.display.reset_display_limits()
                Utility.clean_dict(data_item.properties)

    def test_reset_display_limits_on_complex_data_gives_reasonable_results(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data = numpy.ones((16, 16), numpy.complex64)
            re, im = numpy.meshgrid(numpy.linspace(-0.8, 2.1, 16), numpy.linspace(-1.4, 1.4, 16))
            data[:, :] = re + 1j * im
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.display.reset_display_limits()
            # the display limit should never be less than the display data minimum
            display_range = display_specifier.display.get_calculated_display_values(True).display_range
            self.assertLess(numpy.amin(display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data), display_range[0])
            self.assertAlmostEqual(numpy.amax(display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data), display_range[1])

    def test_data_range_still_valid_after_reset_display_limits(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data = numpy.ones((16, 16))
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            data_range = display_specifier.display.get_calculated_display_values(True).data_range
            self.assertIsNotNone(data_range)
            display_specifier.display.reset_display_limits()
            self.assertEqual(data_range, display_specifier.display.get_calculated_display_values(True).data_range)

    def test_auto_display_limits_works(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data = numpy.empty((100, 100))
            data[0:50, :] = 1
            data[50:100, :] = 2
            data[0, 0] = 0
            data[99, 99] = 3
            data_item = DataItem.DataItem(data)
            data_item.displays[0].auto_display_limits()
            low, high = data_item.displays[0].display_limits
            self.assertAlmostEqual(low, 0.0)
            self.assertAlmostEqual(high, 3.0)

    def test_display_range_is_recalculated_with_new_data(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.float))
            self.assertEqual(data_item.displays[0].get_calculated_display_values(True).display_range, (1, 1))
            with data_item.data_ref() as dr:
                dr.master_data[0,0] = 16
                dr.data_updated()
            self.assertEqual(data_item.displays[0].get_calculated_display_values(True).display_range, (1, 16))

    def test_display_range_is_correct_on_complex_data_display_as_absolute(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            complex_data = numpy.zeros((2, 2), numpy.complex64)
            complex_data[0, 0] = complex(4, 3)
            data_item = DataItem.DataItem(complex_data)
            data_item.displays[0].complex_display_type = "absolute"
            self.assertEqual(data_item.displays[0].get_calculated_display_values(True).display_range, (0, 5))

    def test_display_range_is_correct_on_complex_data_display_as_log_absolute(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            complex_data = numpy.array(range(10)).astype(numpy.complex)
            data_item = DataItem.DataItem(complex_data)
            min_ = numpy.log(numpy.abs(0).astype(numpy.float64) + numpy.nextafter(0,1))
            self.assertAlmostEqual(data_item.displays[0].get_calculated_display_values(True).display_range[0], min_)
            self.assertAlmostEqual(data_item.displays[0].get_calculated_display_values(True).display_range[1], math.log(9))

    def test_display_data_is_2d_for_2d_sequence(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((4, 16, 16), numpy.float64), data_descriptor=DataAndMetadata.DataDescriptor(True, 0, 2))
            data_item = DataItem.DataItem(numpy.ones((8,), numpy.float))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.data_item.set_xdata(data_and_metadata)
            self.assertEqual(display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data_shape, (16, 16))
            self.assertEqual(display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data_dtype, numpy.float64)
            self.assertEqual(display_specifier.display.preview_2d_shape, (16, 16))

    def test_display_data_is_2d_for_2d_collection_with_2d_datum(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((2, 2, 8, 8), numpy.float64), data_descriptor=DataAndMetadata.DataDescriptor(False, 2, 2))
            data_item = DataItem.DataItem(numpy.ones((8,), numpy.float))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.data_item.set_xdata(data_and_metadata)
            self.assertEqual(display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data_shape, (8, 8))
            self.assertEqual(display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data_dtype, numpy.float64)
            self.assertEqual(display_specifier.display.preview_2d_shape, (8, 8))

    def test_display_data_is_2d_for_sequence_of_2d_collection_with_2d_datum(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((3, 2, 2, 8, 8), numpy.float64), data_descriptor=DataAndMetadata.DataDescriptor(True, 2, 2))
            data_item = DataItem.DataItem(numpy.ones((8,), numpy.float))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.data_item.set_xdata(data_and_metadata)
            self.assertEqual(display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data_shape, (8, 8))
            self.assertEqual(display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data_dtype, numpy.float64)
            self.assertEqual(display_specifier.display.preview_2d_shape, (8, 8))

    def test_display_data_is_2d_for_collection_of_1d_datum(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((2, 8), numpy.float64), data_descriptor=DataAndMetadata.DataDescriptor(False, 1, 1))
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.assertEqual(display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data_shape, (2, 8))
            self.assertEqual(display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data_dtype, numpy.float64)
            self.assertEqual(display_specifier.display.preview_2d_shape, (2, 8))

    def test_sequence_index_validates_when_data_changes(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.random.randn(4, 3, 3)
            data_and_metadata = DataAndMetadata.new_data_and_metadata(d, data_descriptor=DataAndMetadata.DataDescriptor(True, 0, 2))
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.display.sequence_index = 3
            display_data = display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data
            self.assertTrue(numpy.array_equal(display_data, d[3, ...]))
            d2 = numpy.random.randn(2, 3, 3)
            data_and_metadata2 = DataAndMetadata.new_data_and_metadata(d2, data_descriptor=DataAndMetadata.DataDescriptor(True, 0, 2))
            display_specifier.data_item.set_xdata(data_and_metadata2)
            display_data2 = display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data
            self.assertTrue(numpy.array_equal(display_data2, d2[1, ...]))

    def test_collection_index_validates_when_data_changes(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.random.randn(4, 4, 3, 3)
            data_and_metadata = DataAndMetadata.new_data_and_metadata(d, data_descriptor=DataAndMetadata.DataDescriptor(False, 2, 2))
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.display.collection_index = 3, 3
            display_data = display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data
            self.assertTrue(numpy.array_equal(display_data, d[3, 3, ...]))
            d2 = numpy.random.randn(2, 2, 3, 3)
            data_and_metadata2 = DataAndMetadata.new_data_and_metadata(d2, data_descriptor=DataAndMetadata.DataDescriptor(False, 2, 2))
            display_specifier.data_item.set_xdata(data_and_metadata2)
            display_data2 = display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data
            self.assertTrue(numpy.array_equal(display_data2, d2[1, 1, ...]))

    def test_exception_during_calculate_display_values_recovers_gracefully(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.random.randn(4, 4, 3, 3)
            data_and_metadata = DataAndMetadata.new_data_and_metadata(d, data_descriptor=DataAndMetadata.DataDescriptor(False, 2, 2))
            data_item = DataItem.new_data_item(data_and_metadata)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            document_model.append_data_item(data_item)
            def next_calculated_display_values():
                pass
            listener = display_specifier.display.add_calculated_display_values_listener(next_calculated_display_values)
            with contextlib.closing(listener):
                display_data = display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data
                # now run the test
                display_specifier.display._calculated_display_values_test_exception = True
                display_specifier.display.collection_index = 2, 2  # should trigger the thread
                display_data = display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data
                display_specifier.display.collection_index = 2, 2
                display_data = display_specifier.display.get_calculated_display_values(True).display_data_and_metadata.data
                self.assertTrue(numpy.array_equal(display_data, d[2, 2, ...]))


if __name__ == '__main__':
    unittest.main()
