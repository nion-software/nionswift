# futures
from __future__ import absolute_import

# standard libraries
import contextlib
import logging
import random
import unittest
import uuid

# third party libraries
import numpy
import scipy

# local libraries
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift.model import Calibration
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Region
from nion.swift.model import Symbolic
from nion.ui import Test


class TestSymbolicClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_unary_inversion_returns_inverted_data(self):
        document_model = DocumentModel.DocumentModel()
        d = numpy.zeros((8, 8), dtype=numpy.uint32)
        d[:] = random.randint(0, 100)
        data_item = DataItem.DataItem(d)
        document_model.append_data_item(data_item)
        map = {"a": document_model.get_object_specifier(data_item)}
        computation = Symbolic.Computation()
        computation.parse_expression(document_model, "-a", map)
        data = computation.evaluate().data
        assert numpy.array_equal(data, -d)

    def test_binary_addition_returns_added_data(self):
        document_model = DocumentModel.DocumentModel()
        d1 = numpy.zeros((8, 8), dtype=numpy.uint32)
        d1[:] = random.randint(0, 100)
        data_item1 = DataItem.DataItem(d1)
        d2 = numpy.zeros((8, 8), dtype=numpy.uint32)
        d2[:] = random.randint(0, 100)
        data_item2 = DataItem.DataItem(d2)
        document_model.append_data_item(data_item1)
        document_model.append_data_item(data_item2)
        map = {"a": document_model.get_object_specifier(data_item1), "b": document_model.get_object_specifier(data_item2)}
        computation = Symbolic.Computation()
        computation.parse_expression(document_model, "a+b", map)
        data = computation.evaluate().data
        assert numpy.array_equal(data, d1 + d2)

    def test_binary_multiplication_with_scalar_returns_multiplied_data(self):
        document_model = DocumentModel.DocumentModel()
        d = numpy.zeros((8, 8), dtype=numpy.uint32)
        d[:] = random.randint(0, 100)
        data_item = DataItem.DataItem(d)
        document_model.append_data_item(data_item)
        map = {"a": document_model.get_object_specifier(data_item)}
        computation1 = Symbolic.Computation()
        computation1.parse_expression(document_model, "a * 5", map)
        data1 = computation1.evaluate().data
        computation2 = Symbolic.Computation()
        computation2.parse_expression(document_model, "5 * a", map)
        data2 = computation1.evaluate().data
        assert numpy.array_equal(data1, d * 5)
        assert numpy.array_equal(data2, d * 5)

    def test_subtract_min_returns_subtracted_min(self):
        document_model = DocumentModel.DocumentModel()
        d = numpy.zeros((8, 8), dtype=numpy.uint32)
        d[:] = random.randint(0, 100)
        data_item = DataItem.DataItem(d)
        document_model.append_data_item(data_item)
        map = {"a": document_model.get_object_specifier(data_item)}
        computation = Symbolic.Computation()
        computation.parse_expression(document_model, "a - amin(a)", map)
        data = computation.evaluate().data
        assert numpy.array_equal(data, d - numpy.amin(d))

    def test_ability_to_take_slice(self):
        document_model = DocumentModel.DocumentModel()
        d = numpy.zeros((4, 8, 8), dtype=numpy.uint32)
        d[:] = random.randint(0, 100)
        data_item = DataItem.DataItem(d)
        document_model.append_data_item(data_item)
        map = {"a": document_model.get_object_specifier(data_item)}
        computation = Symbolic.Computation()
        computation.parse_expression(document_model, "a[:,4,4]", map)
        data = computation.evaluate().data
        assert numpy.array_equal(data, d[:,4,4])

    def test_ability_to_write_read_basic_nodes(self):
        document_model = DocumentModel.DocumentModel()
        src_data = numpy.zeros((8, 8), dtype=numpy.uint32)
        src_data[:] = random.randint(0, 100)
        data_item = DataItem.DataItem(src_data)
        document_model.append_data_item(data_item)
        map = {"a": document_model.get_object_specifier(data_item)}
        computation = Symbolic.Computation()
        computation.parse_expression(document_model, "-a / average(a) * 5", map)
        data_node_dict = computation.write_to_dict()
        computation2 = Symbolic.Computation()
        computation2.read_from_dict(data_node_dict)
        computation2.bind(document_model)
        data = computation.evaluate().data
        data2 = computation2.evaluate().data
        assert numpy.array_equal(data, -src_data / numpy.average(src_data) * 5)
        assert numpy.array_equal(data, data2)

    def test_make_operation_works_without_exception_and_produces_correct_data(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.zeros((8, 8), dtype=numpy.uint32)
            d[:] = random.randint(0, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            map = {"a": document_model.get_object_specifier(data_item)}
            data_item = document_controller.processing_calculation("-a / average(a) * 5", map)
            document_model.recompute_all()
            assert numpy.array_equal(data_item.maybe_data_source.data, -d / numpy.average(d) * 5)

    def test_fft_returns_complex_data(self):
        document_model = DocumentModel.DocumentModel()
        d = numpy.random.randn(64, 64)
        data_item = DataItem.DataItem(d)
        document_model.append_data_item(data_item)
        map = {"a": document_model.get_object_specifier(data_item)}
        computation = Symbolic.Computation()
        computation.parse_expression(document_model, "fft(a)", map)
        data = computation.evaluate().data
        assert numpy.array_equal(data, scipy.fftpack.fftshift(scipy.fftpack.fft2(d) * 1.0 / numpy.sqrt(d.shape[1] * d.shape[0])))

    def test_gaussian_blur_handles_scalar_argument(self):
        document_model = DocumentModel.DocumentModel()
        d = numpy.random.randn(64, 64)
        data_item = DataItem.DataItem(d)
        document_model.append_data_item(data_item)
        map = {"a": document_model.get_object_specifier(data_item)}
        computation = Symbolic.Computation()
        computation.parse_expression(document_model, "gaussian_blur(a, 4.0)", map)
        data = computation.evaluate().data
        assert numpy.array_equal(data, scipy.ndimage.gaussian_filter(d, sigma=4.0))

    def test_transpose_flip_handles_args(self):
        document_model = DocumentModel.DocumentModel()
        d = numpy.random.randn(30, 60)
        data_item = DataItem.DataItem(d)
        document_model.append_data_item(data_item)
        map = {"a": document_model.get_object_specifier(data_item)}
        computation = Symbolic.Computation()
        computation.parse_expression(document_model, "transpose_flip(a, flip_v=True)", map)
        data = computation.evaluate().data
        assert numpy.array_equal(data, numpy.flipud(d))

    def test_crop_handles_args(self):
        document_model = DocumentModel.DocumentModel()
        d = numpy.random.randn(64, 64)
        data_item = DataItem.DataItem(d)
        region = Region.RectRegion()
        region.center = 0.41, 0.51
        region.size = 0.52, 0.42
        data_item.maybe_data_source.add_region(region)
        document_model.append_data_item(data_item)
        map = {"a": document_model.get_object_specifier(data_item), "regionA": document_model.get_object_specifier(region)}
        computation = Symbolic.Computation()
        computation.parse_expression(document_model, "crop(a, regionA.bounds)", map)
        data = computation.evaluate().data
        assert numpy.array_equal(data, d[9:42, 19:45])

    def test_evaluate_computation_within_document_model_gives_correct_value(self):
        document_model = DocumentModel.DocumentModel()
        data = numpy.ones((2, 2), numpy.double)
        data_item = DataItem.DataItem(data)
        document_model.append_data_item(data_item)
        map = {"a": document_model.get_object_specifier(data_item)}
        computation = Symbolic.Computation()
        computation.parse_expression(document_model, "-a", map)
        data_and_metadata = computation.evaluate()
        self.assertTrue(numpy.array_equal(data_and_metadata.data, -data))

    def test_computation_within_document_model_fires_needs_update_event_when_data_changes(self):
        document_model = DocumentModel.DocumentModel()
        data = numpy.ones((2, 2), numpy.double)
        data_item = DataItem.DataItem(data)
        document_model.append_data_item(data_item)
        map = {"a": document_model.get_object_specifier(data_item)}
        computation = Symbolic.Computation()
        computation.parse_expression(document_model, "-a", map)
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
        data = numpy.ones((2, 2), numpy.double)
        data_item = DataItem.DataItem(data)
        document_model.append_data_item(data_item)
        map = {"a": document_model.get_object_specifier(data_item)}
        computation = Symbolic.Computation()
        computation.parse_expression(document_model, "-a", map)
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
        data = numpy.random.randn(64, 64)
        data_item = DataItem.DataItem(data)
        region = Region.RectRegion()
        region.center = 0.41, 0.51
        region.size = 0.52, 0.42
        data_item.maybe_data_source.add_region(region)
        document_model.append_data_item(data_item)
        map = {"a": document_model.get_object_specifier(data_item), "regionA": document_model.get_object_specifier(region)}
        computation = Symbolic.Computation()
        computation.parse_expression(document_model, "crop(a, regionA.bounds)", map)
        needs_update_ref = [False]
        def needs_update():
            needs_update_ref[0] = True
        needs_update_event_listener = computation.needs_update_event.listen(needs_update)
        with contextlib.closing(needs_update_event_listener):
            data_item.maybe_data_source.regions[0].size = 0.53, 0.43
        self.assertTrue(needs_update_ref[0])

    def test_calculation_handles_data_lookups(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            expression = "-data_by_uuid(uuid.UUID('{}'))".format(str(data_item.uuid))
            data_item = document_controller.processing_calculation(expression, dict())
            document_model.recompute_all()
            assert numpy.array_equal(data_item.maybe_data_source.data, -d)

    def test_calculation_handles_region_lookups(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.random.randn(100, 100)
            data_item = DataItem.DataItem(d)
            region = Region.RectRegion()
            region.center = 0.5, 0.5
            region.size = 0.6, 0.4
            data_item.maybe_data_source.add_region(region)
            document_model.append_data_item(data_item)
            map = {"a": document_model.get_object_specifier(data_item)}
            expression = "crop(a, region_by_uuid(uuid.UUID('{}')).bounds)".format(str(region.uuid))
            data_item = document_controller.processing_calculation(expression, map)
            document_model.recompute_all()
            assert numpy.array_equal(data_item.maybe_data_source.data, d[20:80, 30:70])

    def test_computation_copies_metadata_during_computation(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.zeros((8, 8), dtype=numpy.uint32)
            d[:] = random.randint(0, 100)
            data_item = DataItem.DataItem(d)
            data_item.maybe_data_source.set_metadata({"abc": 1})
            data_item.maybe_data_source.set_intensity_calibration(Calibration.Calibration(1.0, 2.0, "nm"))
            data_item.maybe_data_source.set_dimensional_calibrations([Calibration.Calibration(1.1, 2.1, "m"), Calibration.Calibration(1.2, 2.2, "m")])
            document_model.append_data_item(data_item)
            map = {"a": document_model.get_object_specifier(data_item)}
            new_data_item = document_controller.processing_calculation("-a / average(a) * 5", map)
            document_model.recompute_all()
            self.assertEqual(new_data_item.maybe_data_source.metadata, data_item.maybe_data_source.metadata)
            self.assertEqual(new_data_item.maybe_data_source.intensity_calibration, data_item.maybe_data_source.intensity_calibration)
            self.assertEqual(new_data_item.maybe_data_source.dimensional_calibrations, data_item.maybe_data_source.dimensional_calibrations)

    def test_remove_data_item_with_computation_succeeds(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.ones((8, 8), dtype=numpy.uint32)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            map = {"a": document_model.get_object_specifier(data_item)}
            new_data_item = document_controller.processing_calculation("-a", map)
            document_model.recompute_all()
            document_model.remove_data_item(new_data_item)

    def test_evaluate_corrupt_computation_within_document_model_gives_sensible_response(self):
        document_model = DocumentModel.DocumentModel()
        data = numpy.ones((2, 2), numpy.double)
        data_item = DataItem.DataItem(data)
        document_model.append_data_item(data_item)
        map = {"a": document_model.get_object_specifier(data_item)}
        computation = Symbolic.Computation()
        computation.parse_expression(document_model, "(a++)", map)
        data_and_metadata = computation.evaluate()
        self.assertIsNone(data_and_metadata)

    def test_evaluate_computation_with_invalid_source_gives_sensible_response(self):
        document_model = DocumentModel.DocumentModel()
        data = numpy.ones((2, 2), numpy.double)
        data_item = DataItem.DataItem(data)
        document_model.append_data_item(data_item)
        map = {"a": document_model.get_object_specifier(data_item)}
        computation = Symbolic.Computation()
        computation.parse_expression(document_model, "a+e", map)
        data_and_metadata = computation.evaluate()
        self.assertIsNone(data_and_metadata)

    def test_evaluate_computation_with_invalid_function_in_document_fails_cleanly(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data = numpy.ones((2, 2), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            map = {"a": document_model.get_object_specifier(data_item)}
            document_controller.processing_calculation("void(a,2)", map)
            document_model.recompute_all()

    def test_reconstruct_with_variable_works(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.random.randn(2, 2)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = Symbolic.Computation()
            computation.parse_expression(document_model, "-data_by_uuid(uuid.UUID('{}'))".format(str(data_item.uuid)), dict())
            expression = computation.reconstruct(dict())
            data_item = document_controller.processing_calculation(expression, dict())
            document_model.recompute_all()
            assert numpy.array_equal(data_item.maybe_data_source.data, -d)

    def test_reconstruct_reuses_existing_variables(self):
        document_model = DocumentModel.DocumentModel()
        d = numpy.random.randn(2, 2)
        data_item = DataItem.DataItem(d)
        document_model.append_data_item(data_item)
        map = {"a": document_model.get_object_specifier(data_item)}
        computation = Symbolic.Computation()
        computation.parse_expression(document_model, "a + a", map)
        expression = computation.reconstruct(dict())
        expression_lines = expression.split("\n")
        self.assertNotEqual(expression_lines[0], expression_lines[1])
        self.assertEqual(len(expression_lines), 2)

    def test_reconstruct_generates_unique_variables(self):
        document_model = DocumentModel.DocumentModel()
        d = numpy.random.randn(2, 2)
        data_item = DataItem.DataItem(d)
        document_model.append_data_item(data_item)
        data_item2 = DataItem.DataItem(numpy.ones((2, 2)))
        document_model.append_data_item(data_item2)
        map = {"a": document_model.get_object_specifier(data_item), "b": document_model.get_object_specifier(data_item2)}
        computation = Symbolic.Computation()
        computation.parse_expression(document_model, "a + b", map)
        expression = computation.reconstruct(dict())
        new_computation = Symbolic.Computation()
        new_computation.parse_expression(document_model, expression, dict())
        data_and_metadata = new_computation.evaluate()
        self.assertTrue(numpy.array_equal(data_and_metadata.data, d + 1))

    def test_reconstruct_all_node_types(self):
        document_model = DocumentModel.DocumentModel()
        d = numpy.random.randn(2, 2)
        data_item = DataItem.DataItem(d)
        document_model.append_data_item(data_item)
        map = {"a": document_model.get_object_specifier(data_item)}
        computation = Symbolic.Computation()
        expression_in = "-a / average(a) * 5"
        computation.parse_expression(document_model, expression_in, map)
        expression_out = computation.reconstruct(map)
        self.assertEqual(expression_in, expression_out)

    def test_computation_changed_updates_evaluated_data(self):
        document_model = DocumentModel.DocumentModel()
        data = numpy.ones((2, 2), numpy.double)
        data_item = DataItem.DataItem(data)
        document_model.append_data_item(data_item)
        map = {"a": document_model.get_object_specifier(data_item)}
        computation = Symbolic.Computation()
        computation.parse_expression(document_model, "-a", map)
        data_and_metadata = computation.evaluate()
        self.assertTrue(numpy.array_equal(data_and_metadata.data, -data))
        computation.parse_expression(document_model, "-2 * a", map)
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
            document_controller.processing_calculation("-a", map)
            document_model.recompute_all()
            computed_data_item = document_model.data_items[1]
            self.assertTrue(numpy.array_equal(computed_data_item.maybe_data_source.data, -data))
            computed_data_item.maybe_data_source.computation.parse_expression(document_model, "-a * 2", map)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(computed_data_item.maybe_data_source.data, -data * 2))

    def test_unary_functions_return_correct_dimensions(self):
        document_model = DocumentModel.DocumentModel()
        data = numpy.random.randn(2, 2)
        data_item = DataItem.DataItem(data)
        document_model.append_data_item(data_item)
        map = {"a": document_model.get_object_specifier(data_item)}
        computation = Symbolic.Computation()
        computation.parse_expression(document_model, "sin(a)", map)
        data_and_metadata = computation.evaluate()
        self.assertEqual(len(data_and_metadata.dimensional_calibrations), 2)

    def disabled_test_computations_update_data_item_dependencies_list(self):
        assert False

    def disabled_test_icol_and_irow_variables_available(self):
        assert False


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
