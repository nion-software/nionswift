# futures
from __future__ import absolute_import

# standard libraries
import contextlib
import copy
import logging
import random
import unittest

# third party libraries
import numpy
import scipy

# local libraries
from nion.data import Calibration
from nion.data import Core
from nion.data import Image
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import Symbolic
from nion.ui import TestUI
from nion.utils import Geometry


class TestSymbolicClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_unary_inversion_returns_inverted_data(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.zeros((8, 8), dtype=numpy.uint32)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("-a")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data = computation.evaluate().data
            assert numpy.array_equal(data, -d)

    def test_binary_addition_returns_added_data(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d1 = numpy.zeros((8, 8), dtype=numpy.uint32)
            d1[:] = random.randint(1, 100)
            data_item1 = DataItem.DataItem(d1)
            d2 = numpy.zeros((8, 8), dtype=numpy.uint32)
            d2[:] = random.randint(1, 100)
            data_item2 = DataItem.DataItem(d2)
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation("a+b")
            computation.create_object("a", document_model.get_object_specifier(data_item1, "data"))
            computation.create_object("b", document_model.get_object_specifier(data_item2, "data"))
            data = computation.evaluate().data
            assert numpy.array_equal(data, d1 + d2)

    def test_binary_multiplication_with_scalar_returns_multiplied_data(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.zeros((8, 8), dtype=numpy.uint32)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation1 = document_model.create_computation("a * 5")
            computation1.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data1 = computation1.evaluate().data
            computation2 = document_model.create_computation("5 * a")
            computation2.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data2 = computation1.evaluate().data
            assert numpy.array_equal(data1, d * 5)
            assert numpy.array_equal(data2, d * 5)

    def test_subtract_min_returns_subtracted_min(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.zeros((8, 8), dtype=numpy.uint32)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a - amin(a)")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data = computation.evaluate().data
            assert numpy.array_equal(data, d - numpy.amin(d))

    def test_ability_to_take_slice(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.zeros((4, 8, 8), dtype=numpy.uint32)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a[:,4,4]")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data = computation.evaluate().data
            assert numpy.array_equal(data, d[:,4,4])

    def test_ability_to_take_slice_on_1d_data(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.random.randn(8)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a[2:6]")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data = computation.evaluate().data
            assert numpy.array_equal(data, d[2:6])

    def test_slice_with_empty_dimension_produces_error(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.zeros((4, 8, 8), dtype=numpy.uint32)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a[2:2, :, :]")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            self.assertIsNone(computation.evaluate())

    def test_ability_to_take_slice_with_ellipses_produces_correct_data(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.zeros((4, 8, 8), dtype=numpy.uint32)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a[2, ...]")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data = computation.evaluate().data
            assert numpy.array_equal(data, d[2, ...])

    def test_ability_to_take_slice_with_ellipses_produces_correct_calibration(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.zeros((4, 8, 8), dtype=numpy.uint32)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            data_item.maybe_data_source.set_dimensional_calibrations([Calibration.Calibration(10, 20, "m"), Calibration.Calibration(11, 21, "mm"), Calibration.Calibration(12, 22, "nm")])
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a[2, ...]")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data_and_metadata = computation.evaluate()
            self.assertEqual(len(data_and_metadata.data_shape), len(data_and_metadata.dimensional_calibrations))
            self.assertEqual("mm", data_and_metadata.dimensional_calibrations[0].units)
            self.assertEqual("nm", data_and_metadata.dimensional_calibrations[1].units)

    def test_ability_to_take_slice_with_newaxis(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.zeros((8, 8), dtype=numpy.uint32)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a[newaxis, ...]")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data = computation.evaluate().data
            assert numpy.array_equal(data, d[numpy.newaxis, ...])

    def test_ability_to_take_1d_slice_with_newaxis(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.zeros((8,), dtype=numpy.uint32)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a[..., newaxis]")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data = computation.evaluate().data
            assert numpy.array_equal(data, d[..., numpy.newaxis])

    def test_slice_sum_sums_correct_slices(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.random.randn(4, 4, 16)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("slice_sum(a, 4, 6)")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data = computation.evaluate().data
            assert numpy.array_equal(data, numpy.sum(d[..., 1:7], -1))

    def test_reshape_1d_to_2d_produces_correct_data(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.random.randn(4)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("reshape(a, shape(2, 2))")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data = computation.evaluate().data
            assert numpy.array_equal(data, numpy.reshape(d, (2, 2)))
            computation = document_model.create_computation("reshape(a, shape(4, -1))")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data = computation.evaluate().data
            assert numpy.array_equal(data, numpy.reshape(d, (4, -1)))
            computation = document_model.create_computation("reshape(a, shape(-1, 4))")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data = computation.evaluate().data
            assert numpy.array_equal(data, numpy.reshape(d, (-1, 4)))

    def test_reshape_1d_to_2d_preserves_calibration(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.random.randn(4)
            data_item = DataItem.DataItem(d)
            data_item.maybe_data_source.set_dimensional_calibrations([Calibration.Calibration(1.1, 2.1, "m")])
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("reshape(a, shape(4, -1))")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data_and_metadata = computation.evaluate()
            self.assertEqual("m", data_and_metadata.dimensional_calibrations[0].units)
            self.assertEqual("", data_and_metadata.dimensional_calibrations[1].units)
            computation = document_model.create_computation("reshape(a, shape(-1, 4))")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data_and_metadata = computation.evaluate()
            self.assertEqual("", data_and_metadata.dimensional_calibrations[0].units)
            self.assertEqual("m", data_and_metadata.dimensional_calibrations[1].units)

    def test_reshape_2d_n_x_1_to_1d_preserves_calibration(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.random.randn(4, 1)
            data_item = DataItem.DataItem(d)
            data_item.maybe_data_source.set_dimensional_calibrations([Calibration.Calibration(1.1, 2.1, "m"), Calibration.Calibration()])
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("reshape(a, shape(4))")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data_and_metadata = computation.evaluate()
            self.assertEqual(1, len(data_and_metadata.dimensional_calibrations))
            self.assertEqual("m", data_and_metadata.dimensional_calibrations[0].units)

    def test_reshape_to_match_another_item(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.random.randn(4)
            d2 = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            data_item2 = DataItem.DataItem(d2)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation("reshape(a, data_shape(b))")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            computation.create_object("b", document_model.get_object_specifier(data_item2, "data"))
            data = computation.evaluate().data
            assert numpy.array_equal(data, numpy.reshape(d, (2, 2)))

    def test_concatenate_two_images(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.random.randn(4, 4)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("concatenate((a[0:2, 0:2], a[2:4, 2:4]))")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data = computation.evaluate().data
            assert numpy.array_equal(data, numpy.concatenate((d[0:2, 0:2], d[2:4, 2:4])))

    def test_concatenate_keeps_calibrations_in_non_axis_dimensions(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.random.randn(4, 4)
            data_item = DataItem.DataItem(d)
            data_item.maybe_data_source.set_intensity_calibration(Calibration.Calibration(1.0, 2.0, "nm"))
            data_item.maybe_data_source.set_dimensional_calibrations([Calibration.Calibration(1.1, 2.1, "m"), Calibration.Calibration(1.2, 2.2, "s")])
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("concatenate((a[0:2, 0:2], a[2:4, 2:4]))")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data_and_metadata = computation.evaluate()
            self.assertEqual("nm", data_and_metadata.intensity_calibration.units)
            self.assertEqual("m", data_and_metadata.dimensional_calibrations[0].units)
            self.assertEqual("", data_and_metadata.dimensional_calibrations[1].units)

    def test_concatenate_along_alternate_axis_images(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.random.randn(4)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("concatenate((reshape(a, shape(1, -1)), reshape(a, shape(1, -1))), 0)")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data = computation.evaluate().data
            assert numpy.array_equal(data, numpy.concatenate((numpy.reshape(d, (1, -1)), numpy.reshape(d, (1, -1))), 0))

    def test_concatenate_three_images_along_second_axis(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.random.randn(4, 4)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("concatenate((a[0:2, 0:2], a[1:3, 1:3], a[2:4, 2:4]), 1)")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data = computation.evaluate().data
            assert numpy.array_equal(data, numpy.concatenate((d[0:2, 0:2], d[1:3, 1:3], d[2:4, 2:4]), 1))

    def test_ability_to_write_read_basic_nodes(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data = numpy.zeros((8, 8), dtype=numpy.uint32)
            src_data[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("-a / average(a) * 5")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data_node_dict = computation.write_to_dict()
            computation2 = document_model.create_computation()
            computation2.read_from_dict(data_node_dict)
            computation2.needs_update = True
            data = computation.evaluate().data
            data2 = computation2.evaluate().data
            assert numpy.array_equal(data, -src_data / numpy.average(src_data) * 5)
            assert numpy.array_equal(data, data2)

    def test_make_operation_works_without_exception_and_produces_correct_data(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.zeros((8, 8), dtype=numpy.uint32)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("-a / average(a) * 5")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data = computation.evaluate().data
            assert numpy.array_equal(data, -d / numpy.average(d) * 5)

    def test_fft_returns_complex_data(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.random.randn(64, 64)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("fft(a)")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data = computation.evaluate().data
            assert numpy.array_equal(data, scipy.fftpack.fftshift(scipy.fftpack.fft2(d) * 1.0 / numpy.sqrt(d.shape[1] * d.shape[0])))

    def test_gaussian_blur_handles_scalar_argument(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.random.randn(64, 64)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("gaussian_blur(a, 4.0)")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data = computation.evaluate().data
            assert numpy.array_equal(data, scipy.ndimage.gaussian_filter(d, sigma=4.0))

    def test_transpose_flip_handles_args(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.random.randn(30, 60)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("transpose_flip(a, flip_v=True)")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data = computation.evaluate().data
            assert numpy.array_equal(data, numpy.flipud(d))

    def test_crop_handles_args(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.random.randn(64, 64)
            data_item = DataItem.DataItem(d)
            region = Graphics.RectangleGraphic()
            region.center = 0.41, 0.51
            region.size = 0.52, 0.42
            data_item.maybe_data_source.displays[0].add_graphic(region)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("crop(a, regionA.bounds)")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            computation.create_object("regionA", document_model.get_object_specifier(region))
            data = computation.evaluate().data
            assert numpy.array_equal(data, d[9:42, 19:45])

    def test_evaluate_computation_within_document_model_gives_correct_value(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data = numpy.ones((2, 2), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("-a")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data_and_metadata = computation.evaluate()
            self.assertTrue(numpy.array_equal(data_and_metadata.data, -data))

    def test_computation_within_document_model_fires_needs_update_event_when_data_changes(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data = numpy.ones((2, 2), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("-a")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            needs_update_ref = [False]
            def needs_update():
                needs_update_ref[0] = True
            needs_update_event_listener = computation.needs_update_event.listen(needs_update)
            with contextlib.closing(needs_update_event_listener):
                with data_item.maybe_data_source.data_ref() as dr:
                    dr.data += 1.5
            self.assertTrue(needs_update_ref[0])

    def test_computation_within_document_model_fires_needs_update_event_when_metadata_changes(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data = numpy.ones((2, 2), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("-a")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            needs_update_ref = [False]
            def needs_update():
                needs_update_ref[0] = True
            needs_update_event_listener = computation.needs_update_event.listen(needs_update)
            with contextlib.closing(needs_update_event_listener):
                metadata = data_item.maybe_data_source.metadata
                metadata["abc"] = 1
                data_item.maybe_data_source.set_metadata(metadata)
            self.assertTrue(needs_update_ref[0])

    def test_computation_within_document_model_fires_needs_update_event_when_object_property(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data = numpy.random.randn(64, 64)
            data_item = DataItem.DataItem(data)
            region = Graphics.RectangleGraphic()
            region.center = 0.41, 0.51
            region.size = 0.52, 0.42
            data_item.maybe_data_source.displays[0].add_graphic(region)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("crop(a, regionA.bounds)")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            computation.create_object("regionA", document_model.get_object_specifier(region))
            needs_update_ref = [False]
            def needs_update():
                needs_update_ref[0] = True
            needs_update_event_listener = computation.needs_update_event.listen(needs_update)
            with contextlib.closing(needs_update_event_listener):
                data_item.maybe_data_source.displays[0].graphics[0].size = 0.53, 0.43
            self.assertTrue(needs_update_ref[0])

    def test_computation_within_document_model_fires_needs_update_event_when_variable_or_object_added(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data = numpy.random.randn(64, 64)
            data_item = DataItem.DataItem(data)
            region = Graphics.RectangleGraphic()
            region.center = 0.41, 0.51
            region.size = 0.52, 0.42
            data_item.maybe_data_source.displays[0].add_graphic(region)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a+n")
            needs_update_ref = [False]
            def needs_update():
                needs_update_ref[0] = True
            needs_update_event_listener = computation.needs_update_event.listen(needs_update)
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            self.assertTrue(needs_update_ref[0])
            needs_update_ref[0] = False
            computation.create_variable("x", value_type="integral", value=5)
            self.assertTrue(needs_update_ref[0])

    def test_computation_handles_data_lookups(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("-data_by_uuid(uuid.UUID('{}'))".format(str(data_item.uuid)))
            data_and_metadata = computation.evaluate()
            assert numpy.array_equal(data_and_metadata.data, -d)

    def test_computation_handles_region_lookups(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.random.randn(100, 100)
            data_item = DataItem.DataItem(d)
            region = Graphics.RectangleGraphic()
            region.center = 0.5, 0.5
            region.size = 0.6, 0.4
            data_item.maybe_data_source.displays[0].add_graphic(region)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("crop(a, region_by_uuid(uuid.UUID('{}')).bounds)".format(str(region.uuid)))
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data_and_metadata = computation.evaluate()
            assert numpy.array_equal(data_and_metadata.data, d[20:80, 30:70])

    def test_computation_copies_metadata_during_computation(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.zeros((8, 8), dtype=numpy.uint32)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            data_item.maybe_data_source.set_metadata({"abc": 1})
            data_item.maybe_data_source.set_intensity_calibration(Calibration.Calibration(1.0, 2.0, "nm"))
            data_item.maybe_data_source.set_dimensional_calibrations([Calibration.Calibration(1.1, 2.1, "m"), Calibration.Calibration(1.2, 2.2, "m")])
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("-a / average(a) * 5")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data_and_metadata = computation.evaluate()
            self.assertEqual(data_and_metadata.metadata, data_item.maybe_data_source.metadata)
            self.assertEqual(data_and_metadata.intensity_calibration, data_item.maybe_data_source.intensity_calibration)
            self.assertEqual(data_and_metadata.dimensional_calibrations, data_item.maybe_data_source.dimensional_calibrations)

    def test_remove_data_item_with_computation_succeeds(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.ones((8, 8), dtype=numpy.uint32)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            map = {"a": document_model.get_object_specifier(data_item, "data")}
            new_data_item = document_controller.processing_computation("-a", map)
            document_model.recompute_all()
            document_model.remove_data_item(new_data_item)

    def test_evaluate_corrupt_computation_within_document_model_gives_sensible_response(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data = numpy.ones((2, 2), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("(a++)")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data_and_metadata = computation.evaluate()
            self.assertIsNone(data_and_metadata)

    def test_evaluate_computation_with_invalid_source_gives_sensible_response(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data = numpy.ones((2, 2), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a+e")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data_and_metadata = computation.evaluate()
            self.assertIsNone(data_and_metadata)

    def test_evaluate_computation_with_invalid_function_in_document_fails_cleanly(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data = numpy.ones((2, 2), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            map = {"a": document_model.get_object_specifier(data_item, "data")}
            document_controller.processing_computation("void(a,2)", map)
            document_model.recompute_all()

    def test_computation_changed_updates_evaluated_data(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data = numpy.ones((2, 2), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("-a")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data_and_metadata = computation.evaluate()
            self.assertTrue(numpy.array_equal(data_and_metadata.data, -data))
            computation.expression = "-2 * a"
            data_and_metadata = computation.evaluate()
            self.assertTrue(numpy.array_equal(data_and_metadata.data, -data*2))

    def test_changing_computation_updates_data_item(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            map = {"a": document_model.get_object_specifier(data_item)}
            computed_data_item = document_controller.processing_computation("-a.data", map)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.maybe_data_source.data, -data))
            computed_data_item.maybe_data_source.computation.expression = "-a.data * 2"
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.maybe_data_source.data, -data * 2))

    def test_unary_functions_return_correct_dimensions(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("sin(a)")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data_and_metadata = computation.evaluate()
            self.assertEqual(len(data_and_metadata.dimensional_calibrations), 2)

    def test_computation_stores_original_text(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("sin(a)")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            self.assertEqual(computation.expression, "sin(a)")

    def test_computation_stores_error_and_original_text(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("xyz(a)")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data_and_metadata = computation.evaluate()
            self.assertIsNone(data_and_metadata)
            self.assertTrue(computation.error_text is not None and len(computation.error_text) > 0)
            self.assertEqual(computation.expression, "xyz(a)")

    def test_computation_reloads_missing_scalar_function(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data = numpy.zeros((8, 8), dtype=numpy.uint32)
            src_data[:] = random.randint(0, 100)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("average(a)")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data_node_dict = computation.write_to_dict()
            data_node_dict['original_expression'] = "missing(a)"
            computation2 = document_model.create_computation()
            computation2.read_from_dict(data_node_dict)
            self.assertIsNone(computation2.evaluate())

    def test_computation_can_extract_item_from_scalar_tuple(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data = ((numpy.random.randn(4, 2) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a + data_shape(a)[1] + data_shape(a)[0]")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data_and_metadata = computation.evaluate()
            self.assertTrue(numpy.array_equal(data_and_metadata.data, data + 6))

    def test_columns_and_rows_and_radius_functions_return_correct_values(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("row(a, -1, 1) + column(a, -1, 1) + radius(a)")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data_and_metadata = computation.evaluate()
            icol, irow = numpy.meshgrid(numpy.linspace(-1, 1, 8), numpy.linspace(-1, 1, 10))
            self.assertTrue(numpy.array_equal(data_and_metadata.data, icol + irow + numpy.sqrt(pow(icol, 2) + pow(irow, 2))))

    def test_copying_data_item_with_computation_copies_computation(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("-a")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            computed_data_item = DataItem.DataItem(data.copy())
            computed_data_item.maybe_data_source.set_computation(computation)
            document_model.append_data_item(computed_data_item)
            document_model.recompute_all()
            copied_data_item = copy.deepcopy(computed_data_item)
            document_model.append_data_item(copied_data_item)
            self.assertIsNotNone(copied_data_item.maybe_data_source.computation)
            self.assertEqual(computed_data_item.maybe_data_source.computation.error_text, copied_data_item.maybe_data_source.computation.error_text)
            self.assertEqual(computed_data_item.maybe_data_source.computation.expression, copied_data_item.maybe_data_source.computation.expression)

    def test_changing_computation_source_data_updates_computation(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("-a")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            computed_data_item = DataItem.DataItem(data.copy())
            computed_data_item.maybe_data_source.set_computation(computation)
            document_model.append_data_item(computed_data_item)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item.maybe_data_source.data, data))
            self.assertTrue(numpy.array_equal(computed_data_item.maybe_data_source.data, -data_item.maybe_data_source.data))
            with data_item.maybe_data_source.data_ref() as dr:
                dr.data = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.uint32)
            document_model.recompute_all()
            self.assertFalse(numpy.array_equal(data_item.maybe_data_source.data, data))
            self.assertTrue(numpy.array_equal(computed_data_item.maybe_data_source.data, -data_item.maybe_data_source.data))

    def test_computation_is_live_after_copying_data_item_with_computation(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.int32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("-a")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            computed_data_item = DataItem.DataItem(data.copy())
            computed_data_item.maybe_data_source.set_computation(computation)
            document_model.append_data_item(computed_data_item)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.maybe_data_source.data, -data_item.maybe_data_source.data))
            copied_data_item = copy.deepcopy(computed_data_item)
            document_model.append_data_item(copied_data_item)
            with data_item.maybe_data_source.data_ref() as dr:
                dr.data = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.int32)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.maybe_data_source.data, -data_item.maybe_data_source.data))
            self.assertTrue(numpy.array_equal(copied_data_item.maybe_data_source.data, -data_item.maybe_data_source.data))

    def test_computation_extracts_data_property_of_data_item(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a.data")
            computation.create_object("a", document_model.get_object_specifier(data_item))
            computed_data_item = DataItem.DataItem(data.copy())
            computed_data_item.maybe_data_source.set_computation(computation)
            document_model.append_data_item(computed_data_item)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.maybe_data_source.data, data_item.maybe_data_source.data))

    def test_resample_produces_correct_data(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data = ((numpy.abs(numpy.random.randn(10, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("resample_image(a, shape(5, 4))")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            computed_data_item = DataItem.DataItem(data.copy())
            computed_data_item.maybe_data_source.set_computation(computation)
            document_model.append_data_item(computed_data_item)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.maybe_data_source.data, Image.scaled(data_item.maybe_data_source.data, (5, 4))))

    def test_resample_with_data_shape_produces_correct_data(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data = ((numpy.abs(numpy.random.randn(10, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            data2 = numpy.zeros((5, 4), numpy.uint32)
            data_item2 = DataItem.DataItem(data2)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation("resample_image(a, data_shape(b))")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            computation.create_object("b", document_model.get_object_specifier(data_item2, "data"))
            computed_data_item = DataItem.DataItem(data.copy())
            computed_data_item.maybe_data_source.set_computation(computation)
            document_model.append_data_item(computed_data_item)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.maybe_data_source.data, Image.scaled(data_item.maybe_data_source.data, (5, 4))))

    def test_computation_extracts_display_data_property_of_data_item(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a.display_data")
            computation.create_object("a", document_model.get_object_specifier(data_item))
            data_node_dict = computation.write_to_dict()
            computation2 = document_model.create_computation()
            computation2.read_from_dict(data_node_dict)
            computation2.needs_update = True
            data = computation.evaluate().data
            data2 = computation2.evaluate().data
            assert numpy.array_equal(data, src_data)
            assert numpy.array_equal(data, data2)

    def test_evaluation_with_variable_produces_correct_data(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a + x")
            computation.create_variable("x", value_type="integral", value=5)
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            data = computation.evaluate().data
            assert numpy.array_equal(data, d + 5)

    def test_evaluation_with_two_variables_produces_correct_data(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            src_data = ((numpy.abs(numpy.random.randn(10, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("gaussian_blur(a, x - y)")
            computation.create_variable("x", value_type="integral", value=5)
            computation.create_variable("y", value_type="integral", value=5)
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            assert numpy.array_equal(computation.evaluate().data, src_data)

    def test_changing_variable_value_updates_computation(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            src_data = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a + x")
            x = computation.create_variable("x", value_type="integral", value=5)
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            computed_data_item = DataItem.DataItem(src_data.copy())
            computed_data_item.maybe_data_source.set_computation(computation)
            document_model.append_data_item(computed_data_item)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.maybe_data_source.data, src_data + 5))
            x.value = 8
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.maybe_data_source.data, src_data + 8))

    def test_changing_region_property_updates_computation(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            src_data = numpy.random.randn(20, 20)
            data_item = DataItem.DataItem(src_data)
            line_region = Graphics.LineProfileGraphic()
            line_region.start = 0.25, 0.25
            line_region.end = 0.75, 0.75
            data_item.maybe_data_source.displays[0].add_graphic(line_region)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("line_profile(src.display_data, line_region.vector, line_region.width)")
            computation.create_object("src", document_model.get_object_specifier(data_item))
            computation.create_object("line_region", document_model.get_object_specifier(line_region))
            computed_data_item = DataItem.DataItem(src_data.copy())
            computed_data_item.maybe_data_source.set_computation(computation)
            document_model.append_data_item(computed_data_item)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.maybe_data_source.data, Core.function_line_profile(data_item.maybe_data_source.data_and_metadata, line_region.vector, 1.0).data))
            line_region.start = 0.25, 0.20
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.maybe_data_source.data, Core.function_line_profile(data_item.maybe_data_source.data_and_metadata, line_region.vector, 1.0).data))

    def test_changing_variable_name_has_no_effect_on_computation(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            src_data = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a + x")
            x = computation.create_variable("x", value_type="integral", value=5)
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            computed_data_item = DataItem.DataItem(src_data.copy())
            computed_data_item.maybe_data_source.set_computation(computation)
            document_model.append_data_item(computed_data_item)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.maybe_data_source.data, src_data + 5))
            x.name = "xx"
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.maybe_data_source.data, src_data + 5))

    def test_computation_with_variable_reloads(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data = ((numpy.abs(numpy.random.randn(10, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a + x")
            computation.create_variable("x", value_type="integral", value=5)
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            d = computation.write_to_dict()
            computation2 = document_model.create_computation()
            computation2.read_from_dict(d)
            computation2.needs_update = True
            self.assertTrue(numpy.array_equal(computation.evaluate().data, src_data + 5))
            self.assertTrue(numpy.array_equal(computation2.evaluate().data, src_data + 5))

    def test_computation_variable_writes_and_reads(self):
        variable = Symbolic.ComputationVariable("x", value_type="integral", value=5)
        self.assertEqual(variable.name, "x")
        self.assertEqual(variable.value, 5)
        data_node_dict = variable.write_to_dict()
        variable2 = Symbolic.ComputationVariable()
        variable2.read_from_dict(data_node_dict)
        self.assertEqual(variable.name, variable2.name)
        self.assertEqual(variable.value, variable2.value)

    def test_computation_variable_change_type(self):
        variable = Symbolic.ComputationVariable("x", value_type="integral", value=5)
        variable.variable_type = "data_item"
        variable = Symbolic.ComputationVariable("x", value_type="integral", value=5)
        variable.variable_type = "region"

    def test_computation_reparsing_keeps_variables(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a + x")
            x = computation.create_variable("x", value_type="integral", value=5)
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            self.assertTrue(numpy.array_equal(computation.evaluate().data, src_data + 5))
            computation.expression = "x + a"
            self.assertTrue(numpy.array_equal(computation.evaluate().data, src_data + 5))

    def test_computation_using_object_parses_and_evaluates(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a + x")
            computation.create_variable("x", value_type="integral", value=5)
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            self.assertTrue(numpy.array_equal(computation.evaluate().data, src_data + 5))

    def test_computation_using_object_updates_when_data_changes(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a + x")
            computation.create_variable("x", value_type="integral", value=5)
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            self.assertTrue(numpy.array_equal(computation.evaluate().data, src_data + 5))
            d = computation.write_to_dict()
            read_computation = document_model.create_computation()
            read_computation.read_from_dict(d)
            read_computation.needs_update = True
            src_data2 = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.uint32)
            with data_item.maybe_data_source.data_ref() as dr:
                dr.data = src_data2
            self.assertTrue(numpy.array_equal(read_computation.evaluate().data, src_data2 + 5))

    def test_computation_using_object_updates_efficiently_when_region_changes(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data = ((numpy.abs(numpy.random.randn(12, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            region = Graphics.RectangleGraphic()
            region.bounds = Geometry.FloatRect.from_center_and_size(Geometry.FloatPoint(0.5, 0.5), Geometry.FloatSize(0.5, 0.5))
            data_item.maybe_data_source.displays[0].add_graphic(region)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("crop(a, r.bounds)")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            computation.create_object("r", document_model.get_object_specifier(region))
            computed_data_item = DataItem.DataItem(src_data.copy())
            computed_data_item.maybe_data_source.set_computation(computation)
            document_model.append_data_item(computed_data_item)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.maybe_data_source.data, src_data[3:9, 2:6]))
            region.bounds = Geometry.FloatRect.from_center_and_size(Geometry.FloatPoint(0.25, 0.25), Geometry.FloatSize(0.5, 0.5))
            region.bounds = Geometry.FloatRect.from_center_and_size(Geometry.FloatPoint(0.0, 0.0), Geometry.FloatSize(0.5, 0.5))
            region.bounds = Geometry.FloatRect.from_center_and_size(Geometry.FloatPoint(0.25, 0.25), Geometry.FloatSize(0.5, 0.5))
            evaluation_count = computation._evaluation_count_for_test
            document_model.recompute_all()
            self.assertEqual(computation._evaluation_count_for_test - evaluation_count, 1)
            self.assertTrue(numpy.array_equal(computed_data_item.maybe_data_source.data, src_data[0:6, 0:4]))

    def test_computation_updates_efficiently_when_variable_changes(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data = ((numpy.abs(numpy.random.randn(12, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            region = Graphics.RectangleGraphic()
            region.bounds = Geometry.FloatRect.from_center_and_size(Geometry.FloatPoint(0.5, 0.5), Geometry.FloatSize(0.5, 0.5))
            data_item.maybe_data_source.displays[0].add_graphic(region)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("gaussian_blur(a, s)")
            s = computation.create_variable("s", value_type="integral", value=5)
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            computed_data_item = DataItem.DataItem(src_data.copy())
            computed_data_item.maybe_data_source.set_computation(computation)
            document_model.append_data_item(computed_data_item)
            document_model.recompute_all()
            evaluation_count = computation._evaluation_count_for_test
            s.value = 4
            self.assertEqual(computation._evaluation_count_for_test - evaluation_count, 0)
            document_model.recompute_all()
            self.assertEqual(computation._evaluation_count_for_test - evaluation_count, 1)

    def test_computation_updates_efficiently_when_variable_added_or_removed(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data = ((numpy.abs(numpy.random.randn(12, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            region = Graphics.RectangleGraphic()
            region.bounds = Geometry.FloatRect.from_center_and_size(Geometry.FloatPoint(0.5, 0.5), Geometry.FloatSize(0.5, 0.5))
            data_item.maybe_data_source.displays[0].add_graphic(region)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("gaussian_blur(a, s)")
            s = computation.create_variable("s", value_type="integral", value=5)
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            computed_data_item = DataItem.DataItem(src_data.copy())
            computed_data_item.maybe_data_source.set_computation(computation)
            document_model.append_data_item(computed_data_item)
            document_model.recompute_all()
            evaluation_count = computation._evaluation_count_for_test
            t = computation.create_variable("t", value_type="integral", value=5)
            self.assertEqual(computation._evaluation_count_for_test - evaluation_count, 0)
            document_model.recompute_all()
            self.assertEqual(computation._evaluation_count_for_test - evaluation_count, 1)
            computation.remove_variable(t)
            self.assertEqual(computation._evaluation_count_for_test - evaluation_count, 1)
            document_model.recompute_all()
            self.assertEqual(computation._evaluation_count_for_test - evaluation_count, 2)

    def test_computation_updates_efficiently_when_expression_changes(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data = ((numpy.abs(numpy.random.randn(12, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            region = Graphics.RectangleGraphic()
            region.bounds = Geometry.FloatRect.from_center_and_size(Geometry.FloatPoint(0.5, 0.5), Geometry.FloatSize(0.5, 0.5))
            data_item.maybe_data_source.displays[0].add_graphic(region)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("gaussian_blur(a, s)")
            s = computation.create_variable("s", value_type="integral", value=5)
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            computed_data_item = DataItem.DataItem(src_data.copy())
            computed_data_item.maybe_data_source.set_computation(computation)
            document_model.append_data_item(computed_data_item)
            document_model.recompute_all()
            evaluation_count = computation._evaluation_count_for_test
            computation.expression = "gaussian_blur(a, 2)"
            # computation should not be re-evaluated until requested
            self.assertEqual(computation._evaluation_count_for_test - evaluation_count, 0)
            document_model.recompute_all()
            self.assertEqual(computation._evaluation_count_for_test - evaluation_count, 1)

    def test_computation_with_object_writes_and_reads(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a + 4")
            a_specifier = document_model.get_object_specifier(data_item, "data")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            d = computation.write_to_dict()
            read_computation = document_model.create_computation()
            read_computation.read_from_dict(d)
            self.assertEqual(read_computation.variables[0].name, "a")
            self.assertEqual(read_computation.variables[0].specifier, a_specifier)

    def test_computation_with_object_reloads(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a + x")
            computation.create_variable("x", value_type="integral", value=5)
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            d = computation.write_to_dict()
            computation2 = document_model.create_computation()
            computation2.read_from_dict(d)
            computation2.needs_update = True
            self.assertTrue(numpy.array_equal(computation.evaluate().data, src_data + 5))
            self.assertTrue(numpy.array_equal(computation2.evaluate().data, src_data + 5))

    def test_computation_with_object_evaluates_correctly_after_changing_the_variable_name(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a + x")
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            x = computation.create_variable("x", value_type="integral", value=5)
            self.assertTrue(numpy.array_equal(computation.evaluate().data, src_data + 5))
            x.name = "xx"
            computation.expression = "a + xx"
            self.assertTrue(numpy.array_equal(computation.evaluate().data, src_data + 5))

    def test_computation_with_object_evaluates_correctly_after_changing_the_specifier(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data1 = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.uint32)
            src_data2 = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.uint32)
            data_item1 = DataItem.DataItem(src_data1)
            data_item2 = DataItem.DataItem(src_data2)
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            expression = "a + 1"
            computation = document_model.create_computation(expression)
            a = computation.create_object("a", document_model.get_object_specifier(data_item1, "data"))
            self.assertTrue(numpy.array_equal(computation.evaluate().data, src_data1 + 1))
            a.specifier = document_model.get_object_specifier(data_item2, "data")
            computation.expression = expression
            self.assertTrue(numpy.array_equal(computation.evaluate().data, src_data2 + 1))

    def test_computation_fires_needs_update_event_when_specifier_changes(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data1 = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.uint32)
            src_data2 = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.uint32)
            data_item1 = DataItem.DataItem(src_data1)
            data_item2 = DataItem.DataItem(src_data2)
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            expression = "a + 1"
            computation = document_model.create_computation(expression)
            a = computation.create_object("a", document_model.get_object_specifier(data_item1, "data"))
            needs_update_ref = [False]
            def needs_update():
                needs_update_ref[0] = True
            needs_update_event_listener = computation.needs_update_event.listen(needs_update)
            with contextlib.closing(needs_update_event_listener):
                a.specifier = document_model.get_object_specifier(data_item2)
            self.assertTrue(needs_update_ref[0])

    def test_computation_in_document_recomputes_when_specifier_changes(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data1 = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.uint32)
            src_data2 = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.uint32)
            data_item1 = DataItem.DataItem(src_data1)
            data_item2 = DataItem.DataItem(src_data2)
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            expression = "a + 1"
            computation = document_model.create_computation(expression)
            a = computation.create_object("a", document_model.get_object_specifier(data_item1, "data"))
            computed_data_item = DataItem.DataItem(src_data1.copy())
            computed_data_item.maybe_data_source.set_computation(computation)
            document_model.append_data_item(computed_data_item)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.maybe_data_source.data, src_data1 + 1))
            a.specifier = document_model.get_object_specifier(data_item2, "data")
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.maybe_data_source.data, src_data2 + 1))

    def test_computation_with_raw_reference_copies(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            region = Graphics.RectangleGraphic()
            data_item.maybe_data_source.displays[0].add_graphic(region)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("a + x")
            computation.create_variable("x", value_type="integral", value=5)
            a = computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            computation.remove_variable(a)
            copy.deepcopy(computation)

    def test_evaluation_error_recovers_gracefully(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data = ((numpy.abs(numpy.random.randn(12, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation("line_profile(a, vector(normalized_point(0.25, 0.25), normalized_point(0.5, 0.5)), x)")
            x = computation.create_variable("x", value_type="integral", value=0)
            computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
            computed_data_item = DataItem.DataItem(src_data.copy())
            computed_data_item.maybe_data_source.set_computation(computation)
            document_model.append_data_item(computed_data_item)
            document_model.recompute_all()
            self.assertIsNotNone(computation.error_text)
            self.assertEqual(len(computed_data_item.maybe_data_source.data.shape), 2)  # original data
            x.value = 1
            document_model.recompute_all()
            self.assertIsNone(computation.error_text)
            self.assertIsNotNone(computed_data_item.maybe_data_source.data)
            self.assertEqual(len(computed_data_item.maybe_data_source.data.shape), 1)  # computed data

    def test_various_expressions_produces_data(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data = ((numpy.abs(numpy.random.randn(10, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            script_and_data = [
                ("histogram(a, 10)", None),
                ("line_profile(a, vector(normalized_point(0.1, 0.1), normalized_point(0.8, 0.7)), 10)", None),
                ("transpose_flip(a, False, True, False)", None),
                ("crop(a, rectangle_from_origin_size(normalized_point(0, 0), normalized_size(0.5, 0.625)))", src_data[0:5, 0:5]),
                ("sum(a, 0)", numpy.sum(src_data, 0)),
                ("resample_image(a, shape(32, 32))", Image.scaled(src_data, (32, 32))),
                ("resample_image(a, data_shape(a))", src_data),
                ("resample_image(a, data_shape(crop(a, rectangle_from_origin_size(normalized_point(0, 0), normalized_size(0.5, 0.625)))))", Image.scaled(src_data, (5, 5))),
                ("a + x", src_data + 5),
                ("gaussian_blur(a, x + x)", None),
                ("gaussian_blur(a, x - 2)", None),
                ("gaussian_blur(a, 2 * x)", None),
                ("gaussian_blur(a, +x)", None),
            ]
            for script, data in script_and_data:
                computation = document_model.create_computation(script)
                computation.create_object("a", document_model.get_object_specifier(data_item, "data"))
                computation.create_variable("x", value_type="integral", value=5)
                computed_data_item = DataItem.DataItem(src_data.copy())
                computed_data_item.maybe_data_source.set_computation(computation)
                document_model.append_data_item(computed_data_item)
                document_model.recompute_all()
                self.assertIsNotNone(computed_data_item.maybe_data_source.data)
                if data is not None:
                    self.assertTrue(numpy.array_equal(computed_data_item.maybe_data_source.data, data))

    def test_conversion_to_int(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data = ((numpy.abs(numpy.random.randn(10, 8)) + 1) * 10).astype(numpy.float64)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data"))
            computation.expression = "astype(src, int)"
            data = computation.evaluate().data
            self.assertEqual(data.dtype, numpy.int_)
            self.assertTrue(numpy.array_equal(data, src_data.astype(int)))
            computation.expression = "astype(src, int16)"
            data = computation.evaluate().data
            self.assertEqual(data.dtype, numpy.int16)
            self.assertTrue(numpy.array_equal(data, src_data.astype(numpy.int16)))
            computation.expression = "astype(src, int32)"
            data = computation.evaluate().data
            self.assertEqual(data.dtype, numpy.int32)
            self.assertTrue(numpy.array_equal(data, src_data.astype(numpy.int32)))
            computation.expression = "astype(src, int64)"
            data = computation.evaluate().data
            self.assertEqual(data.dtype, numpy.int64)
            self.assertTrue(numpy.array_equal(data, src_data.astype(numpy.int64)))

    def test_conversion_to_uint(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data = ((numpy.abs(numpy.random.randn(10, 8)) + 1) * 10).astype(numpy.float64)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data"))
            computation.expression = "astype(src, uint8)"
            data = computation.evaluate().data
            self.assertEqual(data.dtype, numpy.uint8)
            self.assertTrue(numpy.array_equal(data, src_data.astype(numpy.uint8)))
            computation.expression = "astype(src, uint16)"
            data = computation.evaluate().data
            self.assertEqual(data.dtype, numpy.uint16)
            self.assertTrue(numpy.array_equal(data, src_data.astype(numpy.uint16)))
            computation.expression = "astype(src, uint32)"
            data = computation.evaluate().data
            self.assertEqual(data.dtype, numpy.uint32)
            self.assertTrue(numpy.array_equal(data, src_data.astype(numpy.uint32)))
            computation.expression = "astype(src, uint64)"
            data = computation.evaluate().data
            self.assertEqual(data.dtype, numpy.uint64)
            self.assertTrue(numpy.array_equal(data, src_data.astype(numpy.uint64)))

    def test_conversion_to_float(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data = ((numpy.abs(numpy.random.randn(10, 8)) + 1) * 10).astype(numpy.int32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data"))
            computation.expression = "astype(src, float32)"
            data = computation.evaluate().data
            self.assertEqual(data.dtype, numpy.float32)
            self.assertTrue(numpy.array_equal(data, src_data.astype(numpy.float32)))
            computation.expression = "astype(src, float64)"
            data = computation.evaluate().data
            self.assertEqual(data.dtype, numpy.float64)
            self.assertTrue(numpy.array_equal(data, src_data.astype(numpy.float64)))

    def test_conversion_to_complex(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data = ((numpy.abs(numpy.random.randn(10, 8)) + 1) * 10).astype(numpy.int32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data"))
            computation.expression = "astype(src, complex64)"
            data = computation.evaluate().data
            self.assertEqual(data.dtype, numpy.complex64)
            self.assertTrue(numpy.array_equal(data, src_data.astype(numpy.complex64)))
            computation.expression = "astype(src, complex128)"
            data = computation.evaluate().data
            self.assertEqual(data.dtype, numpy.complex128)
            self.assertTrue(numpy.array_equal(data, src_data.astype(numpy.complex128)))

    def test_data_descriptor_is_maintained_during_evaluate(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data1 = ((numpy.abs(numpy.random.randn(10,)) + 1) * 10).astype(numpy.int32)
            data_item1 = DataItem.DataItem(src_data1)
            document_model.append_data_item(data_item1)
            src_data2 = ((numpy.abs(numpy.random.randn(10,)) + 1) * 10).astype(numpy.int32)
            data_item2 = DataItem.DataItem(src_data2)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation()
            computation.create_object("src1", document_model.get_object_specifier(data_item1, "data"))
            computation.create_object("src2", document_model.get_object_specifier(data_item2, "data"))
            computation.expression = "vstack((src1, src2))"
            data_and_metadata = computation.evaluate_data()
            self.assertEqual(data_and_metadata.collection_dimension_count, 1)
            self.assertEqual(data_and_metadata.datum_dimension_count, 1)

    def disabled_test_reshape_rgb(self):
        assert False

    def disabled_test_computation_with_data_error_gets_reported(self):
        assert False  # when the data node returns None

    def disabled_test_computation_variable_gets_closed(self):
        assert False

    def disabled_test_computation_with_cycles_fails_gracefully(self):
        assert False

    def disabled_test_computations_handle_constant_values_as_errors(self):
        # computation.parse_expression(document_model, "7", dict())
        assert False

    def disabled_test_computations_update_data_item_dependencies_list(self):
        assert False

    def disabled_test_function_to_modify_intensity_calibration(self):
        assert False

    def disabled_test_function_to_modify_dimensional_calibrations(self):
        assert False

    def disabled_test_function_to_modify_metadata(self):
        assert False

    def test_data_slice_calibration_with_step(self):
        # d[::2, :, :]
        pass

    def disabled_test_invalid_computation_produces_error_message(self):
        # example d[3:3, ...]
        # should return None be allowed? what about raise exception in all cases?
        pass

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
