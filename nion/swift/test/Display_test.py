# standard libraries
import contextlib
import copy
import unittest

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Utility
from nion.ui import TestUI


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

    def test_display_produces_valid_preview_when_viewing_3d_data_set(self):
        data_item = DataItem.DataItem(numpy.zeros((16, 16, 16), numpy.float64))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        self.assertIsNotNone(display.display_data)

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
        data_item.maybe_data_source.set_intensity_calibration(intensity_calibration)
        data_item.maybe_data_source.set_dimensional_calibrations([dim0_calibration, dim1_calibration, dim2_calibration])
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display_data_and_metadata = display_specifier.display.display_data_and_metadata
        self.assertEqual(display_data_and_metadata.dimensional_shape, (16, 16))
        self.assertEqual(display_data_and_metadata.intensity_calibration, intensity_calibration)
        self.assertEqual(display_data_and_metadata.dimensional_calibrations[0], dim0_calibration)
        self.assertEqual(display_data_and_metadata.dimensional_calibrations[1], dim1_calibration)

    def test_changing_data_updates_display_range(self):
        irow, icol = numpy.ogrid[0:16, 0:16]
        data_item = DataItem.DataItem(icol, numpy.uint32)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        self.assertEqual(display.display_range, (0, 15))
        self.assertEqual(display.data_range, (0, 15))
        with display_specifier.buffered_data_source.data_ref() as dr:
            dr.data = irow // 2 + 4
        self.assertEqual(display.display_range, (4, 11))
        self.assertEqual(display.data_range, (4, 11))

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
            def property_changed(self, property, value):
                if property == "display_range":
                    self.display_range = value
                if property == "data_range":
                    self.data_range = value
        o = Observer()
        property_changed_listener = display.property_changed_event.listen(o.property_changed)
        with contextlib.closing(property_changed_listener):
            with display_specifier.buffered_data_source.data_ref() as dr:
                dr.data = irow // 2 + 4
            self.assertEqual(o.data_range, (4, 11))
            self.assertEqual(o.display_range, (4, 11))

    def test_data_item_copy_initialized_display_data_range(self):
        source_data_item = DataItem.DataItem(numpy.zeros((16, 16, 16), numpy.float64))
        data_item = copy.deepcopy(source_data_item)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        self.assertIsNotNone(display_specifier.display.data_range)

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
            map = {"a": document_model.get_object_specifier(data_item, "data")}
            data_item2 = document_controller.processing_computation("a[:,:,0:8]", map)
            document_model.recompute_all()
            assert numpy.array_equal(data_item2.maybe_data_source.data, d[:, :, 0:8])
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item2)
            display_specifier.display.slice_center = 6
            display_specifier.display.slice_width = 4
            self.assertEqual(display_specifier.display.slice_center, 6)
            self.assertEqual(display_specifier.display.slice_width, 4)
            display_specifier.buffered_data_source.computation.expression = "a[:, :, 0:4]"
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
            self.assertEqual(display_specifier.display.data_range, (0, 0))
            display_specifier.display.slice_center = 2
            display_specifier.display.slice_width = 4
            self.assertEqual(display_specifier.display.data_range, (6, 6))

    def test_display_data_is_scalar_for_1d_complex(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.ones((16,), numpy.complex128)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.assertEqual(display_specifier.display.display_data.dtype, numpy.float64)

    def test_display_data_is_scalar_for_2d_complex(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.ones((16, 16), numpy.complex128)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.assertEqual(display_specifier.display.display_data.dtype, numpy.float64)

    def test_display_data_is_rgba_for_2d_rgba(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.ones((16, 16, 4), numpy.uint8)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.assertEqual(display_specifier.display.display_data.dtype, numpy.uint8)
            self.assertEqual(display_specifier.display.display_data.shape[-1], 4)

    def test_display_data_is_2d_for_3d(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.ones((16, 16, 8), numpy.float64)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.assertEqual(display_specifier.display.display_data.shape, (16, 16))
            self.assertEqual(display_specifier.display.display_data.dtype, numpy.float64)

    def test_display_data_is_2d_scalar_for_3d_complex(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.ones((16, 16, 8), numpy.complex128)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.assertEqual(display_specifier.display.display_data.shape, (16, 16))
            self.assertEqual(display_specifier.display.display_data.dtype, numpy.float64)

    def test_image_with_no_data_displays_gracefully(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.ones((8,), numpy.float))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.buffered_data_source.set_data_and_metadata(DataAndMetadata.DataAndMetadata(lambda: None, ((8, 0), numpy.float)))
            display_specifier.display.display_type = "image"
            display_panel = document_controller.selected_display_panel
            display_panel.set_displayed_data_item(data_item)
            display_panel.display_canvas_item.update_layout((0, 0), (640, 480))
            display_panel.display_canvas_item.prepare_display()  # force layout

    def test_line_plot_with_no_data_displays_gracefully(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.ones((8,), numpy.float))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.buffered_data_source.set_data_and_metadata(DataAndMetadata.DataAndMetadata(lambda: None, ((8, 0), numpy.float)))
            display_specifier.display.display_type = "line_plot"
            display_panel = document_controller.selected_display_panel
            display_panel.set_displayed_data_item(data_item)
            display_panel.display_canvas_item.update_layout((0, 0), (640, 480))
            display_panel.display_canvas_item.prepare_display()  # force layout

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

    def test_auto_display_limits_on_various_value_types_write_to_clean_json(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            dtypes = (numpy.float32, numpy.float64, numpy.complex64, numpy.complex128, numpy.int16, numpy.uint16, numpy.int32, numpy.uint32)
            for dtype in dtypes:
                data_item = DataItem.DataItem(numpy.ones((16, 16), dtype))
                document_model.append_data_item(data_item)
                display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
                display_specifier.display.auto_display_limits()
                Utility.clean_dict(data_item.properties)

    def test_display_data_is_2d_for_2d_sequence(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((4, 16, 16), numpy.float64), data_descriptor=DataAndMetadata.DataDescriptor(True, 0, 2))
            data_item = DataItem.DataItem(numpy.ones((8,), numpy.float))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.buffered_data_source.set_data_and_metadata(data_and_metadata)
            self.assertEqual(display_specifier.display.display_data.shape, (16, 16))
            self.assertEqual(display_specifier.display.display_data.dtype, numpy.float64)
            self.assertEqual(display_specifier.display.display_data.shape, (16, 16))

    def test_display_data_is_2d_for_2d_collection_with_2d_datum(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((2, 2, 8, 8), numpy.float64), data_descriptor=DataAndMetadata.DataDescriptor(False, 2, 2))
            data_item = DataItem.DataItem(numpy.ones((8,), numpy.float))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.buffered_data_source.set_data_and_metadata(data_and_metadata)
            self.assertEqual(display_specifier.display.display_data.shape, (8, 8))
            self.assertEqual(display_specifier.display.display_data.dtype, numpy.float64)
            self.assertEqual(display_specifier.display.display_data.shape, (8, 8))

    def test_display_data_is_2d_for_sequence_of_2d_collection_with_2d_datum(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((3, 2, 2, 8, 8), numpy.float64), data_descriptor=DataAndMetadata.DataDescriptor(True, 2, 2))
            data_item = DataItem.DataItem(numpy.ones((8,), numpy.float))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.buffered_data_source.set_data_and_metadata(data_and_metadata)
            self.assertEqual(display_specifier.display.display_data.shape, (8, 8))
            self.assertEqual(display_specifier.display.display_data.dtype, numpy.float64)
            self.assertEqual(display_specifier.display.display_data.shape, (8, 8))


if __name__ == '__main__':
    unittest.main()
