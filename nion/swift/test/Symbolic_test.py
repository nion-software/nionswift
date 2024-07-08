# standard libraries
import contextlib
import copy
import logging
import random
import threading
import time
import unittest
import uuid

# third party libraries
import numpy
import scipy
import scipy.fft

# local libraries
from nion.data import Calibration
from nion.data import Core
from nion.data import Image
from nion.swift import Application
from nion.swift import Facade
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import Symbolic
from nion.swift.model import Utility
from nion.swift.test import TestContext
from nion.ui import TestUI
from nion.utils import Geometry


Facade.initialize()


class TestSymbolicClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self.app = Application.Application(TestUI.UserInterface(), set_global=True)

    def tearDown(self):
        TestContext.end_leaks(self)

    def test_unary_inversion_returns_inverted_data(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.zeros((8, 8), dtype=numpy.uint32)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("-a.xdata"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            assert numpy.array_equal(data, -d)

    def test_binary_addition_returns_added_data(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d1 = numpy.zeros((8, 8), dtype=numpy.uint32)
            d1[:] = random.randint(1, 100)
            data_item1 = DataItem.DataItem(d1)
            d2 = numpy.zeros((8, 8), dtype=numpy.uint32)
            d2[:] = random.randint(1, 100)
            data_item2 = DataItem.DataItem(d2)
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata + b.xdata"))
            computation.create_input_item("a", Symbolic.make_item(data_item1))
            computation.create_input_item("b", Symbolic.make_item(data_item2))
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            assert numpy.array_equal(data, d1 + d2)

    def test_binary_multiplication_with_scalar_returns_multiplied_data(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.zeros((8, 8), dtype=numpy.uint32)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation1 = document_model.create_computation(Symbolic.xdata_expression("a.xdata * 5"))
            computation1.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation1)
            data1 = DocumentModel.evaluate_data(computation1).data
            computation2 = document_model.create_computation(Symbolic.xdata_expression("5 * a.xdata"))
            computation2.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation2)
            data2 = DocumentModel.evaluate_data(computation2).data
            assert numpy.array_equal(data1, d * 5)
            assert numpy.array_equal(data2, d * 5)

    def test_subtract_min_returns_subtracted_min(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.zeros((8, 8), dtype=numpy.uint32)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata - numpy.amin(a.data)"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            assert numpy.array_equal(data, d - numpy.amin(d))

    def test_ability_to_take_slice(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.zeros((4, 8, 8), dtype=numpy.uint32)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata[:,4,4]"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            assert numpy.array_equal(data, d[:,4,4])

    def test_ability_to_take_slice_on_1d_data(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.random.randn(8)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata[2:6]"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            assert numpy.array_equal(data, d[2:6])

    def test_slice_with_empty_dimension_produces_error(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.zeros((4, 8, 8), dtype=numpy.uint32)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata[2:2, :, :]"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            self.assertIsNone(DocumentModel.evaluate_data(computation))
            computation.close()

    def test_ability_to_take_slice_with_ellipses_produces_correct_data(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.zeros((4, 8, 8), dtype=numpy.uint32)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata[2, ...]"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            assert numpy.array_equal(data, d[2, ...])

    def test_ability_to_take_slice_with_ellipses_produces_correct_calibration(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.zeros((4, 8, 8), dtype=numpy.uint32)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            data_item.set_dimensional_calibrations([Calibration.Calibration(10, 20, "m"), Calibration.Calibration(11, 21, "mm"), Calibration.Calibration(12, 22, "nm")])
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata[2, ...]"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data_and_metadata = DocumentModel.evaluate_data(computation)
            self.assertEqual(len(data_and_metadata.data_shape), len(data_and_metadata.dimensional_calibrations))
            self.assertEqual("mm", data_and_metadata.dimensional_calibrations[0].units)
            self.assertEqual("nm", data_and_metadata.dimensional_calibrations[1].units)

    def test_ability_to_take_slice_with_newaxis(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.zeros((8, 8), dtype=numpy.uint32)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata[numpy.newaxis, ...]"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            assert numpy.array_equal(data, d[numpy.newaxis, ...])

    def test_ability_to_take_1d_slice_with_newaxis(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.zeros((8,), dtype=numpy.uint32)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata[..., numpy.newaxis]"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            assert numpy.array_equal(data, d[..., numpy.newaxis])

    def test_slice_sum_sums_correct_slices(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.random.randn(4, 4, 16)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.slice_sum(a.xdata, 4, 6)"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            assert numpy.array_equal(data, numpy.sum(d[..., 1:7], -1))

    def test_reshape_1d_to_2d_produces_correct_data(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.random.randn(4)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.reshape(a.xdata, (2, 2))"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            assert numpy.array_equal(data, numpy.reshape(d, (2, 2)))
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.reshape(a.xdata, (4, -1))"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            assert numpy.array_equal(data, numpy.reshape(d, (4, -1)))
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.reshape(a.xdata, (-1, 4))"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            assert numpy.array_equal(data, numpy.reshape(d, (-1, 4)))

    def test_reshape_1d_to_2d_preserves_calibration(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.random.randn(4)
            data_item = DataItem.DataItem(d)
            data_item.set_dimensional_calibrations([Calibration.Calibration(1.1, 2.1, "m")])
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.reshape(a.xdata, (4, -1))"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data_and_metadata = DocumentModel.evaluate_data(computation)
            self.assertEqual("m", data_and_metadata.dimensional_calibrations[0].units)
            self.assertEqual("", data_and_metadata.dimensional_calibrations[1].units)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.reshape(a.xdata, (-1, 4))"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data_and_metadata = DocumentModel.evaluate_data(computation)
            self.assertEqual("", data_and_metadata.dimensional_calibrations[0].units)
            self.assertEqual("m", data_and_metadata.dimensional_calibrations[1].units)

    def test_reshape_2d_n_x_1_to_1d_preserves_calibration(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.random.randn(4, 1)
            data_item = DataItem.DataItem(d)
            data_item.set_dimensional_calibrations([Calibration.Calibration(1.1, 2.1, "m"), Calibration.Calibration()])
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.reshape(a.xdata, (4, ))"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data_and_metadata = DocumentModel.evaluate_data(computation)
            self.assertEqual(1, len(data_and_metadata.dimensional_calibrations))
            self.assertEqual("m", data_and_metadata.dimensional_calibrations[0].units)

    def test_reshape_to_match_another_item(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.random.randn(4)
            d2 = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            data_item2 = DataItem.DataItem(d2)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.reshape(a.xdata, b.xdata.data_shape)"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            computation.create_input_item("b", Symbolic.make_item(data_item2))
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            assert numpy.array_equal(data, numpy.reshape(d, (2, 2)))

    def test_concatenate_two_images(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.random.randn(4, 4)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.concatenate((a.xdata[0:2, 0:2], a.xdata[2:4, 2:4]))"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            assert numpy.array_equal(data, numpy.concatenate((d[0:2, 0:2], d[2:4, 2:4])))

    def test_concatenate_keeps_calibrations_in_non_axis_dimensions(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.random.randn(4, 4)
            data_item = DataItem.DataItem(d)
            data_item.set_intensity_calibration(Calibration.Calibration(1.0, 2.0, "nm"))
            data_item.set_dimensional_calibrations([Calibration.Calibration(1.1, 2.1, "m"), Calibration.Calibration(1.2, 2.2, "s")])
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.concatenate((a.xdata[0:2, 0:2], a.xdata[0:2, 2:4]))"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data_and_metadata = DocumentModel.evaluate_data(computation)
            self.assertEqual("nm", data_and_metadata.intensity_calibration.units)
            self.assertEqual("m", data_and_metadata.dimensional_calibrations[0].units)
            self.assertEqual("", data_and_metadata.dimensional_calibrations[1].units)

    def test_concatenate_along_alternate_axis_images(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.random.randn(4)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.concatenate((xd.reshape(a.xdata, (1, -1)), xd.reshape(a.xdata, (1, -1))), 0)"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            assert numpy.array_equal(data, numpy.concatenate((numpy.reshape(d, (1, -1)), numpy.reshape(d, (1, -1))), 0))

    def test_concatenate_three_images_along_second_axis(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.random.randn(4, 4)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.concatenate((a.xdata[0:2, 0:2], a.xdata[1:3, 1:3], a.xdata[2:4, 2:4]), 1)"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            assert numpy.array_equal(data, numpy.concatenate((d[0:2, 0:2], d[1:3, 1:3], d[2:4, 2:4]), 1))

    def test_ability_to_write_read_basic_nodes(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data = numpy.zeros((8, 8), dtype=numpy.uint32)
            src_data[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("-a.xdata / numpy.average(a.data) * 5"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            data_node_dict = computation.write_to_dict()
            data_node_dict["uuid"] = str(uuid.uuid4())
            data_node_dict["variables"][0]["uuid"] = str(uuid.uuid4())
            computation2 = document_model.create_computation()
            computation2.read_from_dict(data_node_dict)
            computation2.needs_update = True
            document_model.append_computation(computation)
            document_model.append_computation(computation2)
            data = DocumentModel.evaluate_data(computation).data
            data2 = DocumentModel.evaluate_data(computation2).data
            assert numpy.array_equal(data, -src_data / numpy.average(src_data) * 5)
            assert numpy.array_equal(data, data2)

    def test_make_operation_works_without_exception_and_produces_correct_data(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            d = numpy.zeros((8, 8), dtype=numpy.uint32)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("-a.xdata / numpy.average(a.data) * 5"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            assert numpy.array_equal(data, -d / numpy.average(d) * 5)

    def test_fft_returns_complex_data(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.random.randn(64, 64)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.fft(a.xdata)"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            assert numpy.array_equal(data, scipy.fft.fftshift(scipy.fft.fft2(d) * 1.0 / numpy.sqrt(d.shape[1] * d.shape[0])))

    def test_gaussian_blur_handles_scalar_argument(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.random.randn(64, 64)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.gaussian_blur(a.xdata, 4.0)"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            assert numpy.array_equal(data, scipy.ndimage.gaussian_filter(d, sigma=4.0))

    def test_transpose_flip_handles_args(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.random.randn(30, 60)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.transpose_flip(a.xdata, flip_v=True)"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            assert numpy.array_equal(data, numpy.flipud(d))

    def test_crop_handles_args(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.random.randn(64, 64)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            region = Graphics.RectangleGraphic()
            region.center = 0.41, 0.51
            region.size = 0.52, 0.42
            display_item.add_graphic(region)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.crop(a.xdata, regionA.bounds)"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            computation.create_input_item("regionA", Symbolic.make_item(region))
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            assert numpy.array_equal(data, d[9:42, 19:45])

    def test_evaluate_computation_gives_correct_value(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.ones((2, 2), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("-a.xdata"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data_and_metadata = DocumentModel.evaluate_data(computation)
            self.assertTrue(numpy.array_equal(data_and_metadata.data, -data))

    def test_computation_fires_needs_update_event_when_data_changes(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.ones((2, 2), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("-a.xdata"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            needs_update_ref = [False]
            def needs_update():
                needs_update_ref[0] = True
            with contextlib.closing(computation.computation_mutated_event.listen(needs_update)):
                with data_item.data_ref() as dr:
                    dr.data += 1.5
            self.assertTrue(needs_update_ref[0])

    def test_computation_fires_needs_update_event_when_display_data_changes(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.random.uniform(0, 10, (2, 2, 2, 2)).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.display_xdata"))
            computation.create_input_item("a", Symbolic.make_item(display_item.display_data_channel))
            computed_data_item = DataItem.DataItem(data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            # verify assumptions
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data[0, 0, ...], computed_data_item.data))
            # change display, check
            display_item.display_data_channels[0].collection_index = 1, 1
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data[1, 1, ...], computed_data_item.data))

    def test_computation_fires_needs_update_event_when_metadata_changes(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.ones((2, 2), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("-a.xdata"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            needs_update_ref = [False]
            def needs_update():
                needs_update_ref[0] = True
            with contextlib.closing(computation.computation_mutated_event.listen(needs_update)):
                metadata = data_item.metadata
                metadata["abc"] = 1
                data_item.metadata = metadata
            self.assertTrue(needs_update_ref[0])

    def test_computation_does_not_update_when_graphic_changes_on_source(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.ones((2, 2), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_graphic(Graphics.PointGraphic())
            computation = document_model.create_computation(Symbolic.xdata_expression("-a.xdata"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            needs_update_ref = [False]
            def needs_update():
                needs_update_ref[0] = True
            with contextlib.closing(computation.computation_mutated_event.listen(needs_update)):
                display_item.graphics[0].position = (0.3, 0.4)
            self.assertFalse(needs_update_ref[0])

    def test_computation_fires_needs_update_event_when_object_property(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.random.randn(64, 64)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            region = Graphics.RectangleGraphic()
            region.center = 0.41, 0.51
            region.size = 0.52, 0.42
            display_item.add_graphic(region)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.crop(a.xdata, regionA.bounds)"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            computation.create_input_item("regionA", Symbolic.make_item(region))
            document_model.append_computation(computation)
            needs_update_ref = [False]
            def needs_update():
                needs_update_ref[0] = True
            with contextlib.closing(computation.computation_mutated_event.listen(needs_update)):
                display_item.graphics[0].size = 0.53, 0.43
            self.assertTrue(needs_update_ref[0])

    def test_computation_fires_needs_update_event_when_variable_or_object_added(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.random.randn(64, 64)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            region = Graphics.RectangleGraphic()
            region.center = 0.41, 0.51
            region.size = 0.52, 0.42
            display_item.add_graphic(region)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata + n"))
            document_model.append_computation(computation)
            needs_update_ref = [False]
            def needs_update():
                needs_update_ref[0] = True
            with contextlib.closing(computation.computation_mutated_event.listen(needs_update)):
                computation.create_input_item("a", Symbolic.make_item(data_item))
                self.assertTrue(needs_update_ref[0])
                needs_update_ref[0] = False
                computation.create_variable("x", value_type="integral", value=5)
                self.assertTrue(needs_update_ref[0])

    def test_computation_handles_data_lookups(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller_with_application()
            document_model = document_controller.document_model
            d = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("-api.library.get_data_item_by_uuid(uuid.UUID('{}')).xdata".format(str(data_item.uuid))))
            document_model.append_computation(computation)
            data_and_metadata = DocumentModel.evaluate_data(computation)
            assert numpy.array_equal(data_and_metadata.data, -d)

    def test_computation_handles_region_lookups(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller_with_application()
            document_model = document_controller.document_model
            d = numpy.random.randn(100, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            region = Graphics.RectangleGraphic()
            region.center = 0.5, 0.5
            region.size = 0.6, 0.4
            display_item.add_graphic(region)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.crop(a.xdata, api.library.get_graphic_by_uuid(uuid.UUID('{}')).bounds)".format(str(region.uuid))))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data_and_metadata = DocumentModel.evaluate_data(computation)
            assert numpy.array_equal(data_and_metadata.data, d[20:80, 30:70])

    def test_computation_does_not_copy_metadata_during_computation(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            d = numpy.zeros((8, 8), dtype=numpy.uint32)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            data_item.metadata = {"abc": 1}
            data_item.set_intensity_calibration(Calibration.Calibration(1.0, 2.0, "nm"))
            data_item.set_dimensional_calibrations([Calibration.Calibration(1.1, 2.1, "m"), Calibration.Calibration(1.2, 2.2, "m")])
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("-a.xdata / numpy.average(a.data) * 5"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data_and_metadata = DocumentModel.evaluate_data(computation)
            self.assertEqual(data_and_metadata.metadata, dict())
            self.assertEqual(data_and_metadata.intensity_calibration, data_item.intensity_calibration)
            self.assertEqual(data_and_metadata.dimensional_calibrations, data_item.dimensional_calibrations)

    def test_remove_data_item_with_computation_succeeds(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            d = numpy.ones((8, 8), dtype=numpy.uint32)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            map = {"a": Symbolic.make_item(data_item)}
            new_data_item = document_controller.processing_computation("-a.xdata", map)
            document_model.recompute_all()
            document_model.remove_data_item(new_data_item)

    def test_evaluate_corrupt_computation_gives_sensible_response(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.ones((2, 2), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("(a.xdata++)"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            data_and_metadata = DocumentModel.evaluate_data(computation)
            self.assertIsNone(data_and_metadata)
            computation.close()

    def test_evaluate_computation_with_invalid_source_gives_sensible_response(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.ones((2, 2), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata + e"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            data_and_metadata = DocumentModel.evaluate_data(computation)
            self.assertIsNone(data_and_metadata)
            computation.close()

    def test_evaluate_computation_with_invalid_function_in_document_fails_cleanly(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data = numpy.ones((2, 2), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            map = {"a": Symbolic.make_item(data_item)}
            document_controller.processing_computation("void(a,2)", map)
            document_model.recompute_all()

    def test_computation_changed_updates_evaluated_data(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.ones((2, 2), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("-a.xdata"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data_and_metadata = DocumentModel.evaluate_data(computation)
            self.assertTrue(numpy.array_equal(data_and_metadata.data, -data))
            computation.expression = Symbolic.xdata_expression("-2 * a.xdata")
            data_and_metadata = DocumentModel.evaluate_data(computation)
            self.assertTrue(numpy.array_equal(data_and_metadata.data, -data*2))

    def test_changing_computation_updates_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            map = {"a": Symbolic.make_item(data_item)}
            computed_data_item = document_controller.processing_computation(Symbolic.xdata_expression("-a.xdata"), map)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, -data))
            document_model.get_data_item_computation(computed_data_item).expression = Symbolic.xdata_expression("-a.xdata * 2")
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, -data * 2))

    def test_unary_functions_return_correct_dimensions(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.data_expression("numpy.sin(a.data)"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data_and_metadata = DocumentModel.evaluate_data(computation)
            self.assertEqual(len(data_and_metadata.dimensional_calibrations), 2)

    def test_computation_stores_original_text(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            data_expression = Symbolic.data_expression("numpy.sin(a.data)")
            computation = document_model.create_computation(data_expression)
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            self.assertEqual(computation.expression, data_expression)

    def test_computation_stores_error_and_original_text(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            xdata_expression = Symbolic.xdata_expression("xyz(a.xdata)")
            computation = document_model.create_computation(xdata_expression)
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data_and_metadata = DocumentModel.evaluate_data(computation)
            self.assertIsNone(data_and_metadata)
            self.assertTrue(computation.error_text is not None and len(computation.error_text) > 0)
            self.assertEqual(computation.expression, xdata_expression)

    def test_computation_reloads_missing_scalar_function(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data = numpy.zeros((8, 8), dtype=numpy.uint32)
            src_data[:] = random.randint(0, 100)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("numpy.average(a.data)"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data_node_dict = computation.write_to_dict()
            data_node_dict['original_expression'] = "missing(a.xdata)"
            computation2 = document_model.create_computation()
            computation2.read_from_dict(data_node_dict)
            self.assertIsNone(DocumentModel.evaluate_data(computation2))
            computation2.close()

    def test_computation_can_extract_item_from_scalar_tuple(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.random.uniform(0, 10, (4, 2)).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata + a.xdata.data_shape[1] + a.xdata.data_shape[0]"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data_and_metadata = DocumentModel.evaluate_data(computation)
            self.assertTrue(numpy.array_equal(data_and_metadata.data, data + 6))

    def test_columns_and_rows_and_radius_functions_return_correct_values(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.random.uniform(0, 10, (10, 8)).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.row(a.xdata.data_shape, -1, 1) + xd.column(a.xdata.data_shape, -1, 1) + xd.radius(a.xdata.data_shape)"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data_and_metadata = DocumentModel.evaluate_data(computation)
            icol, irow = numpy.meshgrid(numpy.linspace(-1, 1, 8), numpy.linspace(-1, 1, 10))
            self.assertTrue(numpy.array_equal(data_and_metadata.data, icol + irow + numpy.sqrt(pow(icol, 2) + pow(irow, 2))))

    def test_copying_data_item_with_computation_copies_computation(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.random.uniform(0, 10, (10, 8)).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("-a.xdata"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            computed_data_item = DataItem.DataItem(data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            document_model.recompute_all()
            copied_data_item = document_model.copy_data_item(computed_data_item)
            self.assertIsNotNone(document_model.get_data_item_computation(copied_data_item))
            self.assertEqual(document_model.get_data_item_computation(computed_data_item).error_text, document_model.get_data_item_computation(copied_data_item).error_text)
            self.assertEqual(document_model.get_data_item_computation(computed_data_item).expression, document_model.get_data_item_computation(copied_data_item).expression)

    def test_changing_computation_source_data_updates_computation(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.random.uniform(0, 10, (10, 8)).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("-a.xdata"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            computed_data_item = DataItem.DataItem(data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item.data, data))
            self.assertTrue(numpy.array_equal(computed_data_item.data, -data_item.data))
            data_item.set_data(numpy.random.uniform(0, 10, (10, 8)).astype(numpy.uint32))
            document_model.recompute_all()
            self.assertFalse(numpy.array_equal(data_item.data, data))
            self.assertTrue(numpy.array_equal(computed_data_item.data, -data_item.data))

    def test_computation_is_live_after_copying_data_item_with_computation(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = ((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.int32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("-a.xdata"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            computed_data_item = DataItem.DataItem(data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, -data_item.data))
            copied_data_item = document_model.copy_data_item(computed_data_item)
            data_item.set_data(((numpy.random.randn(10, 8) + 1) * 10).astype(numpy.int32))
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, -data_item.data))
            self.assertTrue(numpy.array_equal(copied_data_item.data, -data_item.data))

    def test_computation_extracts_data_property_of_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.random.uniform(0, 10, (10, 8)).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            computed_data_item = DataItem.DataItem(data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, data_item.data))

    def test_resample_produces_correct_data(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = ((numpy.abs(numpy.random.randn(10, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.resample_image(a.xdata, (5, 4))"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            computed_data_item = DataItem.DataItem(data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, Image.scaled(data_item.data, (5, 4))))

    def test_resample_with_data_shape_produces_correct_data(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = ((numpy.abs(numpy.random.randn(10, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            data2 = numpy.zeros((5, 4), numpy.uint32)
            data_item2 = DataItem.DataItem(data2)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.resample_image(a.xdata, b.xdata.data_shape)"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            computation.create_input_item("b", Symbolic.make_item(data_item2))
            computed_data_item = DataItem.DataItem(data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, Image.scaled(data_item.data, (5, 4))))

    def test_computation_extracts_display_data_property_of_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data = numpy.random.uniform(0, 10, (10, 8)).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_data_channel = display_item.display_data_channel
            computation = document_model.create_computation(Symbolic.xdata_expression("a.display_xdata"))
            computation.create_input_item("a", Symbolic.make_item(display_data_channel))
            data_node_dict = computation.write_to_dict()
            data_node_dict["uuid"] = str(uuid.uuid4())
            data_node_dict["variables"][0]["uuid"] = str(uuid.uuid4())
            computation2 = document_model.create_computation()
            computation2.read_from_dict(data_node_dict)
            computation2.needs_update = True
            document_model.append_computation(computation)
            document_model.append_computation(computation2)
            data = DocumentModel.evaluate_data(computation).data
            data2 = DocumentModel.evaluate_data(computation2).data
            assert numpy.array_equal(data, src_data)
            assert numpy.array_equal(data, data2)

    def test_evaluation_with_variable_produces_correct_data(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            d = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata + x"))
            computation.create_variable("x", value_type="integral", value=5)
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            assert numpy.array_equal(data, d + 5)

    def test_evaluation_with_two_variables_produces_correct_data(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            src_data = ((numpy.abs(numpy.random.randn(10, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.gaussian_blur(a.xdata, x - y)"))
            computation.create_variable("x", value_type="integral", value=5)
            computation.create_variable("y", value_type="integral", value=5)
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            assert numpy.array_equal(DocumentModel.evaluate_data(computation).data, src_data)

    def test_changing_variable_value_updates_computation(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            src_data = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata + x"))
            x = computation.create_variable("x", value_type="integral", value=5)
            computation.create_input_item("a", Symbolic.make_item(data_item))
            computed_data_item = DataItem.DataItem(src_data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, src_data + 5))
            x.value = 8
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, src_data + 8))

    def test_changing_region_property_updates_computation(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            src_data = numpy.random.randn(20, 20)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            line_region = Graphics.LineProfileGraphic()
            line_region.start = 0.25, 0.25
            line_region.end = 0.75, 0.75
            display_item.add_graphic(line_region)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.line_profile(src.display_xdata, line_region.vector, line_region.line_width)"))
            computation.create_input_item("src", Symbolic.make_item(display_item.display_data_channel))
            computation.create_input_item("line_region", Symbolic.make_item(line_region))
            computed_data_item = DataItem.DataItem(src_data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, Core.function_line_profile(data_item.xdata, line_region.vector, 1.0).data))
            line_region.start = 0.25, 0.20
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, Core.function_line_profile(data_item.xdata, line_region.vector, 1.0).data))

    def test_changing_variable_name_has_no_effect_on_computation(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            src_data = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata + x"))
            x = computation.create_variable("x", value_type="integral", value=5)
            computation.create_input_item("a", Symbolic.make_item(data_item))
            computed_data_item = DataItem.DataItem(src_data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, src_data + 5))
            x.name = "xx"
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, src_data + 5))

    def test_computation_with_variable_reloads(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data = ((numpy.abs(numpy.random.randn(10, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata + x"))
            computation.create_variable("x", value_type="integral", value=5)
            computation.create_input_item("a", Symbolic.make_item(data_item))
            d = computation.write_to_dict()
            d["uuid"] = str(uuid.uuid4())
            d["variables"][0]["uuid"] = str(uuid.uuid4())
            d["variables"][1]["uuid"] = str(uuid.uuid4())
            computation2 = document_model.create_computation()
            computation2.read_from_dict(d)
            computation2.needs_update = True
            document_model.append_computation(computation)
            document_model.append_computation(computation2)
            self.assertTrue(numpy.array_equal(DocumentModel.evaluate_data(computation).data, src_data + 5))
            self.assertTrue(numpy.array_equal(DocumentModel.evaluate_data(computation2).data, src_data + 5))

    def test_computation_variable_writes_and_reads(self):
        with contextlib.closing(Symbolic.ComputationVariable("x", value_type=Symbolic.ComputationVariableType.INTEGRAL, value=5)) as variable:
            self.assertEqual(variable.name, "x")
            self.assertEqual(variable.value, 5)
            data_node_dict = variable.write_to_dict()
            with contextlib.closing(Symbolic.ComputationVariable()) as variable2:
                variable2.read_from_dict(data_node_dict)
                self.assertEqual(variable.name, variable2.name)
                self.assertEqual(variable.value, variable2.value)

    def test_computation_variable_change_type(self):
        with contextlib.closing(Symbolic.ComputationVariable("x", value_type=Symbolic.ComputationVariableType.INTEGRAL, value=5)) as variable:
            variable.variable_type = "data_item"
        with contextlib.closing(Symbolic.ComputationVariable("x", value_type=Symbolic.ComputationVariableType.INTEGRAL, value=5)) as variable:
            variable.variable_type = "graphic"

    def test_computation_reparsing_keeps_variables(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data = numpy.random.uniform(0, 10, (10, 8)).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata + x"))
            x = computation.create_variable("x", value_type="integral", value=5)
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            self.assertTrue(numpy.array_equal(DocumentModel.evaluate_data(computation).data, src_data + 5))
            computation.expression = Symbolic.xdata_expression("x + a.xdata")
            self.assertTrue(numpy.array_equal(DocumentModel.evaluate_data(computation).data, src_data + 5))

    def test_computation_using_object_parses_and_evaluates(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data = numpy.random.uniform(0, 10, (10, 8)).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata + x"))
            computation.create_variable("x", value_type="integral", value=5)
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            self.assertTrue(numpy.array_equal(DocumentModel.evaluate_data(computation).data, src_data + 5))

    def test_computation_using_object_updates_when_data_changes(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data = numpy.random.uniform(0, 10, (10, 8)).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata + x"))
            computation.create_variable("x", value_type="integral", value=5)
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            self.assertTrue(numpy.array_equal(DocumentModel.evaluate_data(computation).data, src_data + 5))
            d = computation.write_to_dict()
            d["uuid"] = str(uuid.uuid4())
            d["variables"][0]["uuid"] = str(uuid.uuid4())
            d["variables"][1]["uuid"] = str(uuid.uuid4())
            read_computation = document_model.create_computation()
            read_computation.read_from_dict(d)
            read_computation.needs_update = True
            document_model.append_computation(read_computation)
            src_data2 = numpy.random.uniform(0, 10, (10, 8)).astype(numpy.uint32)
            data_item.set_data(src_data2)
            self.assertTrue(numpy.array_equal(DocumentModel.evaluate_data(read_computation).data, src_data2 + 5))

    def test_computation_using_object_updates_efficiently_when_region_changes(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data = ((numpy.abs(numpy.random.randn(12, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            region = Graphics.RectangleGraphic()
            region.bounds = Geometry.FloatRect.from_center_and_size(Geometry.FloatPoint(0.5, 0.5), Geometry.FloatSize(0.5, 0.5))
            display_item.add_graphic(region)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.crop(a.xdata, r.bounds)"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            computation.create_input_item("r", Symbolic.make_item(region))
            computed_data_item = DataItem.DataItem(src_data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, src_data[3:9, 2:6]))
            region.bounds = Geometry.FloatRect.from_center_and_size(Geometry.FloatPoint(0.25, 0.25), Geometry.FloatSize(0.5, 0.5))
            region.bounds = Geometry.FloatRect.from_center_and_size(Geometry.FloatPoint(0.0, 0.0), Geometry.FloatSize(0.5, 0.5))
            region.bounds = Geometry.FloatRect.from_center_and_size(Geometry.FloatPoint(0.25, 0.25), Geometry.FloatSize(0.5, 0.5))
            evaluation_count = computation._evaluation_count_for_test
            document_model.recompute_all()
            self.assertEqual(computation._evaluation_count_for_test - evaluation_count, 1)
            self.assertTrue(numpy.array_equal(computed_data_item.data, src_data[0:6, 0:4]))

    def test_computation_updates_efficiently_when_variable_changes(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data = ((numpy.abs(numpy.random.randn(12, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            region = Graphics.RectangleGraphic()
            region.bounds = Geometry.FloatRect.from_center_and_size(Geometry.FloatPoint(0.5, 0.5), Geometry.FloatSize(0.5, 0.5))
            display_item.add_graphic(region)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.gaussian_blur(a.xdata, s)"))
            s = computation.create_variable("s", value_type="integral", value=5)
            computation.create_input_item("a", Symbolic.make_item(data_item))
            computed_data_item = DataItem.DataItem(src_data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            document_model.recompute_all()
            evaluation_count = computation._evaluation_count_for_test
            s.value = 4
            self.assertEqual(computation._evaluation_count_for_test - evaluation_count, 0)
            document_model.recompute_all()
            self.assertEqual(computation._evaluation_count_for_test - evaluation_count, 1)

    def test_computation_updates_efficiently_when_variable_added_or_removed(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data = ((numpy.abs(numpy.random.randn(12, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            region = Graphics.RectangleGraphic()
            region.bounds = Geometry.FloatRect.from_center_and_size(Geometry.FloatPoint(0.5, 0.5), Geometry.FloatSize(0.5, 0.5))
            display_item.add_graphic(region)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.gaussian_blur(a.xdata, s)"))
            s = computation.create_variable("s", value_type="integral", value=5)
            computation.create_input_item("a", Symbolic.make_item(data_item))
            computed_data_item = DataItem.DataItem(src_data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
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
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data = ((numpy.abs(numpy.random.randn(12, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            region = Graphics.RectangleGraphic()
            region.bounds = Geometry.FloatRect.from_center_and_size(Geometry.FloatPoint(0.5, 0.5), Geometry.FloatSize(0.5, 0.5))
            display_item.add_graphic(region)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.gaussian_blur(a.xdata, s)"))
            s = computation.create_variable("s", value_type="integral", value=5)
            computation.create_input_item("a", Symbolic.make_item(data_item))
            computed_data_item = DataItem.DataItem(src_data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            document_model.recompute_all()
            evaluation_count = computation._evaluation_count_for_test
            computation.expression = Symbolic.xdata_expression("xd.gaussian_blur(a, 2)")
            # computation should not be re-evaluated until requested
            self.assertEqual(computation._evaluation_count_for_test - evaluation_count, 0)
            document_model.recompute_all()
            self.assertEqual(computation._evaluation_count_for_test - evaluation_count, 1)

    def test_computation_with_object_writes_and_reads(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data = numpy.random.uniform(0, 10, (10, 8)).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata + 4"))
            a_specifier = computation.create_input_item("a", Symbolic.make_item(data_item)).specifier
            d = computation.write_to_dict()
            document_model.append_computation(computation)
            read_computation = document_model.create_computation()
            read_computation.read_from_dict(d)
            self.assertEqual(read_computation.variables[0].name, "a")
            self.assertEqual(read_computation.variables[0].specifier, a_specifier)
            read_computation.close()

    def test_computation_with_object_reloads(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data = numpy.random.uniform(0, 10, (10, 8)).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata + x"))
            computation.create_variable("x", value_type="integral", value=5)
            computation.create_input_item("a", Symbolic.make_item(data_item))
            d = computation.write_to_dict()
            d["uuid"] = str(uuid.uuid4())
            d["variables"][0]["uuid"] = str(uuid.uuid4())
            d["variables"][1]["uuid"] = str(uuid.uuid4())
            computation2 = document_model.create_computation()
            computation2.read_from_dict(d)
            computation2.needs_update = True
            document_model.append_computation(computation)
            document_model.append_computation(computation2)
            self.assertTrue(numpy.array_equal(DocumentModel.evaluate_data(computation).data, src_data + 5))
            self.assertTrue(numpy.array_equal(DocumentModel.evaluate_data(computation2).data, src_data + 5))

    def test_computation_with_object_evaluates_correctly_after_changing_the_variable_name(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data = numpy.random.uniform(0, 10, (10, 8)).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata + x"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            x = computation.create_variable("x", value_type="integral", value=5)
            document_model.append_computation(computation)
            self.assertTrue(numpy.array_equal(DocumentModel.evaluate_data(computation).data, src_data + 5))
            x.name = "xx"
            computation.expression = Symbolic.xdata_expression("a.xdata + xx")
            self.assertTrue(numpy.array_equal(DocumentModel.evaluate_data(computation).data, src_data + 5))

    def test_computation_with_object_evaluates_correctly_after_changing_the_specifier(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data1 = numpy.random.uniform(0, 10, (10, 8)).astype(numpy.uint32)
            src_data2 = numpy.random.uniform(0, 10, (10, 8)).astype(numpy.uint32)
            data_item1 = DataItem.DataItem(src_data1)
            data_item2 = DataItem.DataItem(src_data2)
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            expression = "a.xdata + 1"
            computation = document_model.create_computation(Symbolic.xdata_expression(expression))
            a = computation.create_input_item("a", Symbolic.make_item(data_item1))
            document_model.append_computation(computation)
            self.assertTrue(numpy.array_equal(DocumentModel.evaluate_data(computation).data, src_data1 + 1))
            computation.set_input_item("a", Symbolic.make_item(data_item2))
            computation.expression = Symbolic.xdata_expression(expression)
            self.assertTrue(numpy.array_equal(DocumentModel.evaluate_data(computation).data, src_data2 + 1))

    def test_computation_fires_needs_update_event_when_specifier_changes(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data1 = numpy.random.uniform(0, 10, (10, 8)).astype(numpy.uint32)
            src_data2 = numpy.random.uniform(0, 10, (10, 8)).astype(numpy.uint32)
            data_item1 = DataItem.DataItem(src_data1)
            data_item2 = DataItem.DataItem(src_data2)
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            expression = "a.xdata + 1"
            computation = document_model.create_computation(Symbolic.xdata_expression(expression))
            a = computation.create_input_item("a", Symbolic.make_item(data_item1))
            document_model.append_computation(computation)
            needs_update_ref = [False]
            def needs_update():
                needs_update_ref[0] = True
            with contextlib.closing(computation.computation_mutated_event.listen(needs_update)):
                computation.set_input_item("a", Symbolic.make_item(data_item2))
            self.assertTrue(needs_update_ref[0])

    def test_computation_in_document_recomputes_when_specifier_changes(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data1 = numpy.random.uniform(0, 10, (10, 8)).astype(numpy.uint32)
            src_data2 = numpy.random.uniform(0, 10, (10, 8)).astype(numpy.uint32)
            data_item1 = DataItem.DataItem(src_data1)
            data_item2 = DataItem.DataItem(src_data2)
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            expression = "a.xdata + 1"
            computation = document_model.create_computation(Symbolic.xdata_expression(expression))
            a = computation.create_input_item("a", Symbolic.make_item(data_item1))
            computed_data_item = DataItem.DataItem(src_data1.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, src_data1 + 1))
            computation.set_input_item("a", Symbolic.make_item(data_item2))
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, src_data2 + 1))

    def test_computation_in_document_is_still_live_when_region_specifier_uuid_str_changes(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data = ((numpy.abs(numpy.random.randn(10, 10)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            region1 = Graphics.RectangleGraphic()
            region1.bounds = Geometry.FloatRect.from_tlhw(0.0, 0.0, 0.5, 0.5)
            display_item.add_graphic(region1)
            region2 = Graphics.RectangleGraphic()
            region2.bounds = Geometry.FloatRect.from_tlhw(0.5, 0.5, 0.5, 0.5)
            display_item.add_graphic(region2)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.crop(a.xdata, r.bounds)"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            r = computation.create_input_item("r", Symbolic.make_item(region1))
            computed_data_item = DataItem.DataItem(src_data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            # verify assumptions
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, src_data[0:5, 0:5]))
            # now switch the region uuid
            # TODO: should this happen automatically without the unbind/bind?
            r.unbind()
            r.specifier.reference = region2
            r.bind()
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, src_data[5:10, 5:10]))
            # and make sure recompute happens when new region uuid changes
            region2.bounds = Geometry.FloatRect.from_tlhw(0.0, 0.0, 0.5, 0.5)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.data, src_data[0:5, 0:5]))

    def test_computation_with_raw_reference_copies(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data = numpy.random.uniform(0, 10, (10, 8)).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            region = Graphics.RectangleGraphic()
            display_item.add_graphic(region)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata + x"))
            computation.create_variable("x", value_type="integral", value=5)
            a = computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            computation.remove_variable(a)
            copy.deepcopy(computation).close()

    def test_evaluation_error_recovers_gracefully(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data = ((numpy.abs(numpy.random.randn(12, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.line_profile(a.xdata, xd.vector(xd.norm_point(0.25, 0.25), xd.norm_point(0.5, 0.5)), x)"))
            x = computation.create_variable("x", value_type="integral", value=0)
            computation.create_input_item("a", Symbolic.make_item(data_item))
            computed_data_item = DataItem.DataItem(src_data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            document_model.recompute_all()
            self.assertIsNotNone(computation.error_text)
            self.assertEqual(len(computed_data_item.data.shape), 2)  # original data
            x.value = 1
            document_model.recompute_all()
            self.assertIsNone(computation.error_text)
            self.assertIsNotNone(computed_data_item.data)
            self.assertEqual(len(computed_data_item.data.shape), 1)  # computed data

    def test_various_expressions_produces_data(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data = ((numpy.abs(numpy.random.randn(10, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            script_and_data = [
                ("xd.histogram(a.xdata, 10)", None),
                ("xd.line_profile(a.xdata, xd.vector(xd.norm_point(0.1, 0.1), xd.norma_point(0.8, 0.7)), 10)", None),
                ("xd.transpose_flip(a.xdata, False, True, False)", None),
                ("xd.crop(a.xdata, xd.rectangle_from_origin_size(xd.norm_point(0, 0), xd.norm_size(0.5, 0.625)))", src_data[0:5, 0:5]),
                ("xd.sum(a.xdata, 0)", numpy.sum(src_data, 0)),
                ("xd.resample_image(a.xdata, (32, 32))", Image.scaled(src_data, (32, 32))),
                ("xd.resample_image(a.xdata, a.xdata.data_shape)", src_data),
                ("xd.resample_image(a.xdata, xd.crop(a.xdata, xd.rectangle_from_origin_size(xd.norm_point(0, 0), xd.norm_size(0.5, 0.625))).data_shape)", Image.scaled(src_data, (5, 5))),
                ("a.xdata + x", src_data + 5),
                ("xd.gaussian_blur(a.xdata, x + x)", None),
                ("xd.gaussian_blur(a.xdata, x - 2)", None),
                ("xd.gaussian_blur(a.xdata, 2 * x)", None),
                ("xd.gaussian_blur(a.xdata, +x)", None),
            ]
            for script, data in script_and_data:
                computation = document_model.create_computation(Symbolic.xdata_expression(script))
                computation.create_input_item("a", Symbolic.make_item(data_item))
                computation.create_variable("x", value_type="integral", value=5)
                computed_data_item = DataItem.DataItem(src_data.copy())
                document_model.append_data_item(computed_data_item)
                document_model.set_data_item_computation(computed_data_item, computation)
                document_model.recompute_all()
                self.assertIsNotNone(computed_data_item.data)
                if data is not None:
                    self.assertTrue(numpy.array_equal(computed_data_item.data, data))

    def test_conversion_to_int(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data = ((numpy.abs(numpy.random.randn(10, 8)) + 1) * 10).astype(numpy.float64)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.expression = Symbolic.xdata_expression("xd.astype(src.xdata, int)")
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            self.assertEqual(data.dtype, numpy.int_)
            self.assertTrue(numpy.array_equal(data, src_data.astype(int)))
            computation.expression = Symbolic.xdata_expression("xd.astype(src.xdata, numpy.int16)")
            data = DocumentModel.evaluate_data(computation).data
            self.assertEqual(data.dtype, numpy.int16)
            self.assertTrue(numpy.array_equal(data, src_data.astype(numpy.int16)))
            computation.expression = Symbolic.xdata_expression("xd.astype(src.xdata, numpy.int32)")
            data = DocumentModel.evaluate_data(computation).data
            self.assertEqual(data.dtype, numpy.int32)
            self.assertTrue(numpy.array_equal(data, src_data.astype(numpy.int32)))
            computation.expression = Symbolic.xdata_expression("xd.astype(src.xdata, numpy.int64)")
            data = DocumentModel.evaluate_data(computation).data
            self.assertEqual(data.dtype, numpy.int64)
            self.assertTrue(numpy.array_equal(data, src_data.astype(numpy.int64)))

    def test_conversion_to_uint(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data = ((numpy.abs(numpy.random.randn(10, 8)) + 1) * 10).astype(numpy.float64)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.expression = Symbolic.xdata_expression("xd.astype(src.xdata, numpy.uint8)")
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            self.assertEqual(data.dtype, numpy.uint8)
            self.assertTrue(numpy.array_equal(data, src_data.astype(numpy.uint8)))
            computation.expression = Symbolic.xdata_expression("xd.astype(src.xdata, numpy.uint16)")
            data = DocumentModel.evaluate_data(computation).data
            self.assertEqual(data.dtype, numpy.uint16)
            self.assertTrue(numpy.array_equal(data, src_data.astype(numpy.uint16)))
            computation.expression = Symbolic.xdata_expression("xd.astype(src.xdata, numpy.uint32)")
            data = DocumentModel.evaluate_data(computation).data
            self.assertEqual(data.dtype, numpy.uint32)
            self.assertTrue(numpy.array_equal(data, src_data.astype(numpy.uint32)))
            computation.expression = Symbolic.xdata_expression("xd.astype(src.xdata, numpy.uint64)")
            data = DocumentModel.evaluate_data(computation).data
            self.assertEqual(data.dtype, numpy.uint64)
            self.assertTrue(numpy.array_equal(data, src_data.astype(numpy.uint64)))

    def test_conversion_to_float(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data = ((numpy.abs(numpy.random.randn(10, 8)) + 1) * 10).astype(numpy.int32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.expression = Symbolic.xdata_expression("xd.astype(src.xdata, numpy.float32)")
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            self.assertEqual(data.dtype, numpy.float32)
            self.assertTrue(numpy.array_equal(data, src_data.astype(numpy.float32)))
            computation.expression = Symbolic.xdata_expression("xd.astype(src.xdata, numpy.float64)")
            data = DocumentModel.evaluate_data(computation).data
            self.assertEqual(data.dtype, numpy.float64)
            self.assertTrue(numpy.array_equal(data, src_data.astype(numpy.float64)))

    def test_conversion_to_complex(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data = ((numpy.abs(numpy.random.randn(10, 8)) + 1) * 10).astype(numpy.int32)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.expression = Symbolic.xdata_expression("xd.astype(src.xdata, numpy.complex64)")
            document_model.append_computation(computation)
            data = DocumentModel.evaluate_data(computation).data
            self.assertEqual(data.dtype, numpy.complex64)
            self.assertTrue(numpy.array_equal(data, src_data.astype(numpy.complex64)))
            computation.expression = Symbolic.xdata_expression("xd.astype(src.xdata, numpy.complex128)")
            data = DocumentModel.evaluate_data(computation).data
            self.assertEqual(data.dtype, numpy.complex128)
            self.assertTrue(numpy.array_equal(data, src_data.astype(numpy.complex128)))

    def test_data_descriptor_is_maintained_during_evaluate(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data1 = ((numpy.abs(numpy.random.randn(10,)) + 1) * 10).astype(numpy.int32)
            data_item1 = DataItem.DataItem(src_data1)
            document_model.append_data_item(data_item1)
            src_data2 = ((numpy.abs(numpy.random.randn(10,)) + 1) * 10).astype(numpy.int32)
            data_item2 = DataItem.DataItem(src_data2)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation()
            computation.create_input_item("src1", Symbolic.make_item(data_item1))
            computation.create_input_item("src2", Symbolic.make_item(data_item2))
            computation.expression = Symbolic.xdata_expression("xd.vstack((src1.xdata, src2.xdata))")
            document_model.append_computation(computation)
            data_and_metadata = DocumentModel.evaluate_data(computation)
            self.assertEqual(data_and_metadata.collection_dimension_count, 1)
            self.assertEqual(data_and_metadata.datum_dimension_count, 1)

    def test_computation_evaluates_on_thread(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            # in order to make this test go fast, attach the call_soon event here
            # and handle it, setting the continue event at the same time.
            # this must go before the document controller is created since call_soon
            # is a 'fire_any' style event, meaning that only the first handler takes
            # it. we return False to let the document controller eventually handle it.
            continue_event = threading.Event()
            def do_call_soon():
                continue_event.set()
                return False
            listener = document_model.call_soon_event.listen(do_call_soon)
            src_data = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("-a.xdata"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            computed_data_item = DataItem.DataItem(src_data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            document_model.start_dispatcher()
            continue_event.wait(10.0)
            listener.close()
            listener = None
            document_controller.periodic()
            self.assertTrue(numpy.array_equal(computed_data_item.data, -src_data))

    def test_computation_on_deleted_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            src_data = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("-a.xdata"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            computed_data_item = DataItem.DataItem(src_data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            document_model.remove_data_item(data_item)
            document_model.recompute_all()

    def test_computation_updates_timezone(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            try:
                src_data = numpy.random.randn(2, 2)
                data_item = DataItem.DataItem(src_data)
                document_model.append_data_item(data_item)
                computation = document_model.create_computation(Symbolic.xdata_expression("-a.xdata"))
                computation.create_input_item("a", Symbolic.make_item(data_item))
                Utility.local_timezone_override = [None]
                Utility.local_utcoffset_override = [0]
                computed_data_item = DataItem.DataItem(src_data.copy())
                document_model.append_data_item(computed_data_item)
                document_model.set_data_item_computation(computed_data_item, computation)
                self.assertFalse(computed_data_item.timezone)
                self.assertEqual(computed_data_item.timezone_offset, "+0000")
                Utility.local_timezone_override = ["Europe/Athens"]
                Utility.local_utcoffset_override = [180]
                document_model.recompute_all()
                self.assertEqual(computed_data_item.timezone, "Europe/Athens")
                self.assertEqual(computed_data_item.timezone_offset, "+0300")
            finally:
                Utility.local_timezone_override = None
                Utility.local_utcoffset_override = None

    def test_deleting_one_variable_on_bound_computation_rebinds_properly(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            src_data = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(src_data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("x"))
            x_var = computation.create_variable("x")
            computed_data_item = DataItem.DataItem(src_data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            computation.remove_variable(x_var)

    class ComputeExecError:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, src_xdata):
            raise RuntimeError()

        def commit(self):
            pass

    def test_computation_error_is_handled_in_main_thread(self):
        Symbolic.register_computation_type("compute_error", self.ComputeExecError)
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            # in order to make this test go fast, attach the call_soon event here
            # and handle it, setting the continue event at the same time.
            # this must go before the document controller is created since call_soon
            # is a 'fire_any' style event, meaning that only the first handler takes
            # it. we return False to let the document controller eventually handle it.
            continue_event = threading.Event()
            def do_call_soon():
                continue_event.set()
                return False
            listener = document_model.call_soon_event.listen(do_call_soon)
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            computation1 = document_model.create_computation()
            computation1.create_input_item("src_xdata", Symbolic.make_item(data_item, type="xdata"))
            computation1.processing_id = "compute_error"
            document_model.append_computation(computation1)
            document_model.start_dispatcher()
            continue_event.wait(10.0)
            listener.close()
            document_controller.periodic()

    def test_computation_error_clear_initial_computation_flag(self):
        Symbolic.register_computation_type("compute_error", self.ComputeExecError)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            computation1 = document_model.create_computation()
            computation1.create_input_item("src_xdata", Symbolic.make_item(data_item, type="xdata"))
            computation1.processing_id = "compute_error"
            document_model.append_computation(computation1)
            document_model.recompute_all()
            self.assertTrue(computation1.is_initial_computation_complete.wait(0.01))

    class ComputeExecDelayedError:
        def __init__(self, started_event: threading.Event, continue_event: threading.Event, computation, **kwargs):
            self.computation = computation
            self.started_event = started_event
            self.continue_event = continue_event

        def execute(self, src_xdata):
            self.started_event.set()
            self.continue_event.wait(5)
            raise RuntimeError()

        def commit(self):
            pass

    def test_computation_removed_during_execute_is_handled(self):
        started_event = threading.Event()
        continue_event = threading.Event()
        import functools
        Symbolic.register_computation_type("compute_delayed_error", functools.partial(self.ComputeExecDelayedError, started_event, continue_event))
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            computation1 = document_model.create_computation()
            computation1.create_input_item("src_xdata", Symbolic.make_item(data_item, type="xdata"))
            computation1.processing_id = "compute_delayed_error"
            document_model.append_computation(computation1)
            document_model.start_dispatcher()
            started_event.wait(5)
            # computation will be in execute now
            document_model.remove_computation(computation1)
            # now let the computation finish
            continue_event.set()
            # give it a chance to fully complete with a pending error.
            time.sleep(0.05)
            document_model.recompute_all()
            document_controller.periodic()

    def test_removing_computation_unbinds(self):
        Symbolic.register_computation_type("compute_error", self.ComputeExecError)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.random.randn(2, 2))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            document_model.get_invert_new(display_item, display_item.data_item)
            computation = document_model.computations[0]
            self.assertIsNotNone(computation.get_input("src"))
            document_model.remove_data_item(document_model.data_items[1])
            self.assertTrue(computation._closed)

    def test_removing_data_item_source_data_item_from_library_is_possible(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata"))
            computation.create_input_item("a", Symbolic.make_item(data_item))
            document_model.append_computation(computation)
            self.assertTrue(computation.is_resolved)
            document_model.remove_data_item(data_item)
            self.assertTrue(computation._closed)

    def test_adjusting_interval_on_line_profile_does_not_trigger_recompute(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            line_profile_display_item = document_controller.processing_line_profile()
            document_model.recompute_all()
            self.assertEqual(1, document_model.computations[-1]._evaluation_count_for_test)
            interval_region = Graphics.IntervalGraphic()
            line_profile_display_item.add_graphic(interval_region)
            document_model.recompute_all()
            self.assertEqual(1, document_model.computations[-1]._evaluation_count_for_test)
            interval_region.interval = 0.2, 0.3
            document_model.recompute_all()
            self.assertEqual(1, document_model.computations[-1]._evaluation_count_for_test)

    def test_changing_display_slice_does_not_trigger_pick_recompute(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.perform_action("processing.pick")
            # pick_display_item = document_model.display_items[-1]
            document_model.recompute_all()
            self.assertEqual(1, document_model.computations[-1]._evaluation_count_for_test)
            display_item.display_data_channels[0].slice_center += 1
            document_model.recompute_all()
            self.assertEqual(1, document_model.computations[-1]._evaluation_count_for_test)

    def test_inserting_and_changing_unrelated_graphic_does_not_trigger_pick_recompute(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.perform_action("processing.pick")
            # pick_display_item = document_model.display_items[-1]
            document_model.recompute_all()
            self.assertEqual(1, document_model.computations[-1]._evaluation_count_for_test)
            rectangle = Graphics.RectangleGraphic()
            display_item.add_graphic(rectangle)
            document_model.recompute_all()
            self.assertEqual(1, document_model.computations[-1]._evaluation_count_for_test)
            rectangle.center = 0.2, 0.2
            document_model.recompute_all()
            self.assertEqual(1, document_model.computations[-1]._evaluation_count_for_test)

    def test_removing_unrelated_graphic_does_not_trigger_pick_recompute(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            rectangle = Graphics.RectangleGraphic()
            display_item.add_graphic(rectangle)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.perform_action("processing.pick")
            # pick_display_item = document_model.display_items[-1]
            document_model.recompute_all()
            self.assertEqual(1, document_model.computations[-1]._evaluation_count_for_test)
            display_item.remove_graphic(rectangle).close()
            document_model.recompute_all()
            self.assertEqual(1, document_model.computations[-1]._evaluation_count_for_test)

    def test_data_source_watches_correct_graphics(self):
        # this failed at one point due to improper use of local variable
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem()
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            display_item.add_graphic(crop_region)
            graphic = Graphics.PointGraphic()
            display_item.add_graphic(graphic)
            document_model.get_fft_new(display_item, display_item.data_item, crop_region)
            display_item.remove_graphic(graphic).close()
            document_model.recompute_all()
            graphic = Graphics.PointGraphic()
            display_item.add_graphic(graphic)
            # at this stage the data source monitor was corrupt
            graphic.position = 0.2, 0.2  # this triggered an exception

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

    def disabled_test_data_slice_calibration_with_step(self):
        # d[::2, :, :]
        pass

    def disabled_test_invalid_computation_produces_error_message(self):
        # example d[3:3, ...]
        # should return None be allowed? what about raise exception in all cases?
        pass

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
