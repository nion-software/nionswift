# standard libraries
import contextlib
import copy
import gc
import random
import time
import typing
import unittest
import uuid
import weakref

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import Facade
from nion.swift.model import Connection
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DataStructure
from nion.swift.model import DisplayItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import Symbolic
from nion.swift.test import TestContext
from nion.ui import TestUI
from nion.utils import Recorder


Facade.initialize()


def create_memory_profile_context() -> TestContext.MemoryProfileContext:
    return TestContext.MemoryProfileContext()


class TestDocumentModelClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        TestContext.end_leaks(self)

    def test_remove_data_items_on_document_model(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item1 = DataItem.DataItem()
            data_item1.title = 'title'
            data_item2 = DataItem.DataItem()
            data_item2.title = 'title'
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            self.assertEqual(len(document_model.data_items), 2)
            self.assertTrue(data_item1 in document_model.data_items)
            self.assertTrue(data_item2 in document_model.data_items)
            document_model.remove_data_item(data_item1)
            self.assertFalse(data_item1 in document_model.data_items)
            self.assertTrue(data_item2 in document_model.data_items)

    def test_removing_data_item_should_remove_from_groups_too(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item1 = DataItem.DataItem()
            data_item1.title = 'title'
            data_item2 = DataItem.DataItem()
            data_item2.title = 'title'
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            data_group = DataGroup.DataGroup()
            document_model.append_data_group(data_group)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            data_group.append_display_item(display_item1)
            data_group.append_display_item(display_item2)
            self.assertEqual(data_group.counted_display_items[display_item1], 1)
            self.assertEqual(data_group.counted_display_items[display_item2], 1)
            document_model.remove_display_item(display_item1)
            self.assertEqual(data_group.counted_display_items[display_item1], 0)
            self.assertEqual(data_group.counted_display_items[display_item2], 1)

    def test_loading_document_with_duplicated_data_items_ignores_earlier_ones(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.uint32))
                document_model.append_data_item(data_item)
            # modify data reference to have duplicate
            old_data_key = list(profile_context.data_map.keys())[0]
            new_data_key = "2000" + old_data_key[4:]
            old_properties_key = list(profile_context.data_properties_map.keys())[0]
            new_properties_key = "2000" + old_properties_key[4:]
            profile_context.data_map[new_data_key] = copy.deepcopy(profile_context.data_map[old_data_key])
            profile_context.data_properties_map[new_properties_key] = copy.deepcopy(profile_context.data_properties_map[old_properties_key])
            # reload and verify
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(len(document_model.data_items), len(set([d.uuid for d in document_model.data_items])))
                self.assertEqual(len(document_model.data_items), 1)

    def test_document_model_releases_data_item(self):
        # test memory usage
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(data=numpy.zeros((2, 2)))
            data_item_weak_ref = weakref.ref(data_item)
            document_model.append_data_item(data_item)
            data_item = None
        document_model = None
        gc.collect()
        self.assertIsNone(data_item_weak_ref())

    def test_processing_line_profile_configures_intervals_connection(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.zeros((8, 8), dtype=numpy.float)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            line_profile_data_item = document_model.get_line_profile_new(display_item, display_item.data_item)
            self.assertEqual(len(display_item.graphics[0].interval_descriptors), 0)
            interval = Graphics.IntervalGraphic()
            interval.interval = 0.3, 0.6
            document_model.get_display_item_for_data_item(line_profile_data_item).add_graphic(interval)
            self.assertEqual(len(display_item.graphics[0].interval_descriptors), 1)
            self.assertEqual(display_item.graphics[0].interval_descriptors[0]["interval"], interval.interval)

    def test_processing_pick_configures_in_and_out_regions_and_connection(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = (100 * numpy.random.randn(8, 8, 64)).astype(numpy.int)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            pick_data_item = document_model.get_pick_new(display_item, display_item.data_item)
            pick_display_item = document_model.get_display_item_for_data_item(pick_data_item)
            display_data_channel = display_item.display_data_channels[0]
            self.assertEqual(len(display_item.graphics), 1)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(pick_data_item.data, d[4, 4, :]))
            display_item.graphics[0].position = 0, 0
            document_model.recompute_all()
            self.assertFalse(numpy.array_equal(pick_data_item.data, d[4, 4, :]))
            self.assertTrue(numpy.array_equal(pick_data_item.data, d[0, 0, :]))
            self.assertEqual(pick_display_item.graphics[0].interval, display_data_channel.slice_interval)
            # set up interval to be on pixel boundaries; and only even width intervals will map exactly
            interval1 = 5 / d.shape[-1], 9 / d.shape[-1]
            pick_display_item.graphics[0].interval = interval1
            self.assertEqual(pick_display_item.graphics[0].interval, display_data_channel.slice_interval)
            self.assertEqual(pick_display_item.graphics[0].interval, interval1)
            # set up interval to be on pixel boundaries; and only even width intervals will map exactly
            interval2 = 10 / d.shape[-1], 16 / d.shape[-1]
            display_data_channel.slice_interval = interval2
            self.assertEqual(pick_display_item.graphics[0].interval, display_data_channel.slice_interval)
            self.assertEqual(pick_display_item.graphics[0].interval, interval2)

    def test_recompute_after_data_item_deleted_does_not_update_data_on_deleted_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = (100 * numpy.random.randn(4, 4)).astype(numpy.int)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(display_item, display_item.data_item)
            document_model.remove_data_item(inverted_data_item)
            document_model.recompute_all()

    def test_recompute_after_computation_cleared_does_not_update_data(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = (100 * numpy.random.randn(4, 4)).astype(numpy.int)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(display_item, display_item.data_item)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(inverted_data_item.data, -d))
            data_item.set_data((100 * numpy.random.randn(4, 4)).astype(numpy.int))
            document_model.set_data_item_computation(inverted_data_item, None)
            self.assertTrue(numpy.array_equal(inverted_data_item.data, -d))
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(inverted_data_item.data, -d))

    def test_data_item_recording(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((16, 16)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item_recorder = Recorder.Recorder(display_item)
            with contextlib.closing(display_item_recorder):
                display_item.display_type = "line_plot"
                point_graphic = Graphics.PointGraphic()
                point_graphic.position = 0.2, 0.3
                display_item.add_graphic(point_graphic)
                point_graphic.position = 0.21, 0.31
                new_data_item = DataItem.DataItem(numpy.zeros((16, 16)))
                document_model.append_data_item(new_data_item)
                new_display_item = document_model.get_display_item_for_data_item(new_data_item)
                self.assertNotEqual(display_item.display_type, new_display_item.display_type)
                display_item_recorder.apply(new_display_item)
                self.assertEqual(display_item.display_type, new_display_item.display_type)
                self.assertEqual(new_display_item.graphics[0].position, point_graphic.position)

    def test_creating_r_var_on_data_items(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            r_var = document_model.assign_variable_to_display_item(display_item)
            self.assertIsNotNone(r_var)
            self.assertEqual(r_var, DocumentModel.MappedItemManager().get_item_r_var(display_item))

    def test_transaction_handles_added_graphic(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((100, )))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            with document_model.item_transaction(data_item):
                interval = Graphics.IntervalGraphic()
                display_item.add_graphic(interval)
            self.assertEqual(0, document_model.transaction_count)

    def test_transaction_handles_removed_graphic(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((100, )))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            interval = Graphics.IntervalGraphic()
            display_item.add_graphic(interval)
            with document_model.item_transaction(data_item):
                display_item.remove_graphic(interval).close()
            self.assertEqual(0, document_model.transaction_count)

    def test_transaction_handles_added_dependent_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            display_item.add_graphic(crop_region)
            with document_model.item_transaction(data_item):
                data_item_crop = document_model.get_crop_new(display_item, display_item.data_item, crop_region)
                self.assertTrue(document_model.is_in_transaction_state(data_item_crop))
            self.assertEqual(0, document_model.transaction_count)

    def test_transaction_handles_removed_dependent_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            display_item.add_graphic(crop_region)
            data_item_crop = document_model.get_crop_new(display_item, display_item.data_item, crop_region)
            with document_model.item_transaction(data_item):
                document_model.remove_data_item(data_item_crop)
            self.assertEqual(0, document_model.transaction_count)

    def test_transaction_propagates_to_data_structure_referenced_objects(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            data_struct = document_model.create_data_structure()
            data_struct.set_referenced_object("master", data_item)
            document_model.append_data_structure(data_struct)
            with document_model.item_transaction(data_struct):
                self.assertTrue(data_item.in_transaction_state)
            self.assertEqual(0, document_model.transaction_count)

    def test_transaction_propogates_to_data_structure_referenced_objects_added_during_transaction(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            data_struct = document_model.create_data_structure()
            document_model.append_data_structure(data_struct)
            with document_model.item_transaction(data_struct):
                data_struct.set_referenced_object("master", data_item)
                self.assertTrue(data_item.in_transaction_state)
            self.assertEqual(0, document_model.transaction_count)

    def test_transaction_handles_nested_transaction_with_dependent_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((100, )))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            with document_model.item_transaction(data_item):
                with document_model.item_transaction(data_item):
                    line_profile_data_item = document_model.get_line_profile_new(display_item, display_item.data_item)
                    self.assertTrue(document_model.is_in_transaction_state(data_item))
                    self.assertTrue(document_model.is_in_transaction_state(line_profile_data_item))
                self.assertTrue(document_model.is_in_transaction_state(data_item))
                self.assertTrue(document_model.is_in_transaction_state(line_profile_data_item))
            self.assertEqual(0, document_model.transaction_count)

    def test_display_item_associated_with_data_item_should_be_under_transaction(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            with document_model.item_transaction(data_item):
                self.assertTrue(data_item.in_transaction_state)
                self.assertTrue(display_item.in_transaction_state)
            self.assertFalse(data_item.in_transaction_state)
            self.assertFalse(display_item.in_transaction_state)
            self.assertEqual(0, document_model.transaction_count)

    def test_display_item_associated_with_dependent_data_items_should_be_under_transaction(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            line_profile_data_item = document_model.get_line_profile_new(display_item, display_item.data_item)
            line_profile_display_item = document_model.get_display_item_for_data_item(line_profile_data_item)
            with document_model.item_transaction(data_item):
                self.assertTrue(line_profile_data_item.in_transaction_state)
                self.assertTrue(line_profile_display_item.in_transaction_state)
            self.assertFalse(line_profile_data_item.in_transaction_state)
            self.assertFalse(line_profile_display_item.in_transaction_state)
            self.assertEqual(0, document_model.transaction_count)

    def test_data_item_with_associated_data_structure_deletes_when_data_item_deleted(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            document_model.append_data_item(data_item)
            data_structure = document_model.create_data_structure()
            data_structure.set_property_value("title", "Title")
            data_structure.set_property_value("width", 8.5)
            data_structure.set_property_value("interval", (0.5, 0.2))
            document_model.append_data_structure(data_structure)
            document_model.attach_data_structure(data_structure, data_item)
            self.assertEqual(len(document_model.data_structures), 1)
            self.assertSetEqual(set(document_model.get_dependent_items(data_item)), set())
            self.assertSetEqual(set(document_model.get_source_items(data_structure)), set())
            document_model.remove_data_item(data_item)
            self.assertEqual(len(document_model.data_structures), 0)

    def test_computation_creates_dependency_between_data_source_graphic_and_target(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            display_item.add_graphic(crop_region)
            data_item_crop = document_model.get_crop_new(display_item, display_item.data_item, crop_region)
            self.assertSetEqual(set(document_model.get_dependent_items(data_item)), {data_item_crop})
            self.assertSetEqual(set(document_model.get_dependent_items(crop_region)), {data_item_crop})
            self.assertSetEqual(set(document_model.get_source_items(data_item_crop)), {data_item, crop_region})

    find_max_eval_count = 0

    class FindMax:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, src):
            d = src.data
            max_pos = list(numpy.unravel_index(numpy.argmax(d), d.shape))
            max_pos = max_pos[0] / d.shape[0], max_pos[1] / d.shape[1]
            self.__src = src
            self.__max_pos = max_pos

        def commit(self):
            graphic = self.computation.get_result("graphic", None)
            if not graphic:
                graphic = self.__src.add_point_region(*self.__max_pos)
                self.computation.set_result("graphic", graphic)
            graphic.position = self.__max_pos
            TestDocumentModelClass.find_max_eval_count += 1

    def test_new_computation_into_existing_result_graphic(self):
        Symbolic.register_computation_type("find_max", self.FindMax)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.zeros((2, 2), numpy.int)
            d[1, 0] = 1
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            graphic = Graphics.PointGraphic()
            display_item.add_graphic(graphic)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.create_output_item("graphic", Symbolic.make_item(graphic))
            computation.processing_id = "find_max"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(graphic.position, (0.5, 0))

    def test_new_computation_into_new_result_graphic(self):
        Symbolic.register_computation_type("find_max", self.FindMax)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.zeros((2, 2), numpy.int)
            d[1, 0] = 1
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.processing_id = "find_max"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(display_item.graphics), 1)
            self.assertEqual(display_item.graphics[0].position, (0.5, 0))

    def test_new_computation_into_new_and_then_existing_result_graphic(self):
        Symbolic.register_computation_type("find_max", self.FindMax)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.zeros((2, 2), numpy.int)
            d[1, 0] = 1
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.processing_id = "find_max"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(display_item.graphics), 1)
            self.assertEqual(display_item.graphics[0].position, (0.5, 0))
            # change it again
            d[0, 1] = 2
            data_item.set_data(d)
            document_model.recompute_all()
            self.assertEqual(len(display_item.graphics), 1)
            self.assertEqual(display_item.graphics[0].position, (0, 0.5))

    def test_new_computation_into_new_and_result_graphic_only_evaluates_once(self):
        TestDocumentModelClass.find_max_eval_count = 0
        Symbolic.register_computation_type("find_max", self.FindMax)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.zeros((2, 2), numpy.int)
            d[1, 0] = 1
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.processing_id = "find_max"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(TestDocumentModelClass.find_max_eval_count, 1)
            document_model.recompute_all()
            self.assertEqual(TestDocumentModelClass.find_max_eval_count, 1)

    class SetConst:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, src, value):
            self.__new_data = numpy.full(src.data.shape, value)

        def commit(self):
            dst_data_item = self.computation.get_result("dst")
            if not dst_data_item:
                dst_data_item = self.computation.api.library.create_data_item()
                self.computation.set_result("dst", dst_data_item)
            dst_data_item.data = self.__new_data

    def test_new_computation_with_variable(self):
        Symbolic.register_computation_type("set_const", self.SetConst)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            data_item2 = DataItem.DataItem(numpy.zeros((3, 3), numpy.int))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            value = computation.create_variable("value", "integral", 3)
            computation.create_output_item("dst", Symbolic.make_item(data_item2))
            computation.processing_id = "set_const"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item2.data, numpy.full((2, 2), 3)))
            value.value = 5
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item2.data, numpy.full((2, 2), 5)))

    class SetConstDataStruct:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, src, data_structure):
            self.__new_data = numpy.full(src.data.shape, data_structure.get_property("value"))

        def commit(self):
            self.computation.set_referenced_data("dst", self.__new_data)

    def test_new_computation_with_data_structure(self):
        Symbolic.register_computation_type("set_const_struct", self.SetConstDataStruct)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            data_item2 = DataItem.DataItem(numpy.zeros((3, 3), numpy.int))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            data_structure = document_model.create_data_structure()
            data_structure.set_property_value("value", 3)
            document_model.append_data_structure(data_structure)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.create_input_item("data_structure", Symbolic.make_item(data_structure))
            computation.create_output_item("dst", Symbolic.make_item(data_item2))
            computation.processing_id = "set_const_struct"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item2.data, numpy.full((8, 8), 3)))
            data_structure.set_property_value("value", 5)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item2.data, numpy.full((8, 8), 5)))

    def test_new_computation_with_data_structure_property(self):
        Symbolic.register_computation_type("set_const", self.SetConst)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            data_item2 = DataItem.DataItem(numpy.zeros((3, 3), numpy.int))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            data_structure = document_model.create_data_structure()
            data_structure.set_property_value("amount", 3)
            document_model.append_data_structure(data_structure)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.create_input_item("value", Symbolic.make_item(data_structure), property_name="amount")
            computation.create_output_item("dst", Symbolic.make_item(data_item2))
            computation.processing_id = "set_const"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item2.data, numpy.full((8, 8), 3)))
            data_structure.set_property_value("amount", 5)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item2.data, numpy.full((8, 8), 5)))

    def test_computation_creates_dependency_between_data_structure_and_target(self):
        Symbolic.register_computation_type("set_const", self.SetConst)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            data_item2 = DataItem.DataItem(numpy.zeros((3, 3), numpy.int))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            data_structure = document_model.create_data_structure()
            data_structure.set_property_value("amount", 3)
            document_model.append_data_structure(data_structure)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.create_input_item("value", Symbolic.make_item(data_structure), property_name="amount")
            computation.create_output_item("dst", Symbolic.make_item(data_item2))
            computation.processing_id = "set_const"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertSetEqual(set(document_model.get_dependent_items(data_item)), {data_item2})
            self.assertSetEqual(set(document_model.get_dependent_items(data_structure)), {data_item2})
            self.assertSetEqual(set(document_model.get_source_items(data_item2)), {data_item, data_structure})
            self.assertEqual(len(document_model.data_items), 2)
            document_model.remove_data_structure(data_structure)
            self.assertEqual(len(document_model.data_items), 1)

    class OptionalGraphic:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, src, value):
            self.__src = src
            self.__value = value

        def commit(self):
            graphic = self.computation.get_result("graphic", None)
            if not self.__value and graphic:
                self.__src.remove_region(graphic)
                self.computation.set_result("graphic", None)
            elif self.__value and not graphic:
                graphic = self.__src.add_point_region(0.5, 0.5)
                self.computation.set_result("graphic", graphic)

    def test_new_computation_with_optional_result(self):
        Symbolic.register_computation_type("optional_graphic", self.OptionalGraphic)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            value = computation.create_variable("value", "boolean", True)
            computation.create_output_item("graphic")
            computation.processing_id = "optional_graphic"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(display_item.graphics), 1)
            value.value = False
            document_model.recompute_all()
            self.assertEqual(len(display_item.graphics), 0)
            value.value = True
            document_model.recompute_all()
            self.assertEqual(len(display_item.graphics), 1)
        # note: the computation function will remove the graphic which will remove the dependency.
        # it will also set a result on the computation which will also try to remove the dependency.

    def test_new_computation_with_optional_result_updates_dependencies(self):
        Symbolic.register_computation_type("optional_graphic", self.OptionalGraphic)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            value = computation.create_variable("value", "boolean", True)
            computation.create_output_item("graphic")
            computation.processing_id = "optional_graphic"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 1)
            self.assertEqual(document_model.get_dependent_items(data_item)[0], display_item.graphics[0])
            value.value = False
            document_model.recompute_all()
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 0)
            value.value = True
            document_model.recompute_all()
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 1)
            self.assertEqual(document_model.get_dependent_items(data_item)[0], display_item.graphics[0])

    class NGraphics:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, src, value):
            self.__src = src
            self.__value = value

        def commit(self):
            graphics = self.computation.get_result("graphics")
            while len(graphics) < self.__value:
                graphic = self.__src.add_point_region(0.5, 0.5)
                graphics.append(graphic)
            while len(graphics) > self.__value:
                self.__src.remove_region(graphics.pop())
            self.computation.set_result("graphics", graphics)

    def test_new_computation_with_list_result(self):
        Symbolic.register_computation_type("n_graphics", self.NGraphics)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            value = computation.create_variable("value", "integral", 3)
            computation.create_output_item("graphics", Symbolic.make_item_list([]))
            computation.processing_id = "n_graphics"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(display_item.graphics), 3)
            value.value = 5
            document_model.recompute_all()
            self.assertEqual(len(display_item.graphics), 5)

    def test_new_computation_with_list_result_updates_dependencies(self):
        Symbolic.register_computation_type("n_graphics", self.NGraphics)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            value = computation.create_variable("value", "integral", 3)
            computation.create_output_item("graphics", Symbolic.make_item_list([]))
            computation.processing_id = "n_graphics"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 3)
            self.assertEqual(set(document_model.get_dependent_items(data_item)), set(display_item.graphics))
            value.value = 5
            document_model.recompute_all()
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 5)
            self.assertEqual(set(document_model.get_dependent_items(data_item)), set(display_item.graphics))
            value.value = 3
            document_model.recompute_all()
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 3)
            self.assertEqual(set(document_model.get_dependent_items(data_item)), set(display_item.graphics))

    def test_removing_last_item_from_list_removes_computation(self):
        Symbolic.register_computation_type("n_graphics", self.NGraphics)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            graphic = Graphics.PointGraphic()
            display_item.add_graphic(graphic)
            graphic2 = Graphics.PointGraphic()
            display_item.add_graphic(graphic2)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.create_input_item("graphics", Symbolic.make_item_list([graphic, graphic2]))
            document_model.append_computation(computation)
            self.assertEqual(1, len(document_model.computations))
            display_item.remove_graphic(graphic2).close()
            self.assertEqual(1, len(document_model.computations))
            display_item.remove_graphic(graphic).close()
            self.assertEqual(0, len(document_model.computations))

    def test_new_computation_creates_dependency_when_result_created_during_computation(self):
        Symbolic.register_computation_type("set_const", self.SetConst)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.create_variable("value", "integral", 3)
            computation.processing_id = "set_const"
            document_model.append_computation(computation)
            self.assertEqual(len(document_model.data_items), 1)
            self.assertEqual(len(document_model.get_dependent_data_items(data_item)), 0)
            self.assertEqual(len(document_model.computations), 1)
            document_model.recompute_all()
            self.assertEqual(len(document_model.data_items), 2)
            self.assertEqual(len(document_model.get_dependent_data_items(data_item)), 1)
            self.assertEqual(document_model.get_dependent_data_items(data_item)[0], document_model.data_items[1])

    def test_new_computation_creates_dependency_when_result_created_before_computation(self):
        Symbolic.register_computation_type("set_const", self.SetConst)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            data_item2 = DataItem.DataItem(numpy.zeros((3, 3), numpy.int))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.create_output_item("dst", Symbolic.make_item(data_item2))
            computation.create_variable("value", "integral", 3)
            computation.processing_id = "set_const"
            document_model.append_computation(computation)
            self.assertEqual(len(document_model.data_items), 2)
            self.assertEqual(len(document_model.get_dependent_data_items(data_item)), 1)
            self.assertEqual(len(document_model.computations), 1)
            document_model.recompute_all()
            self.assertEqual(len(document_model.data_items), 2)
            self.assertEqual(len(document_model.get_dependent_data_items(data_item)), 1)
            self.assertEqual(document_model.get_dependent_data_items(data_item)[0], document_model.data_items[1])

    def test_new_computation_deletes_computation_and_result_data_item_when_input_data_item_deleted(self):
        Symbolic.register_computation_type("set_const", self.SetConst)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            data_item2 = DataItem.DataItem(numpy.zeros((3, 3), numpy.int))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            value = computation.create_variable("value", "integral", 3)
            computation.create_output_item("dst", Symbolic.make_item(data_item2))
            computation.processing_id = "set_const"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(document_model.computations), 1)
            self.assertEqual(len(document_model.data_items), 2)
            document_model.remove_data_item(data_item)
            self.assertEqual(len(document_model.data_items), 0)
            self.assertEqual(len(document_model.computations), 0)

    add2_eval_count = 0

    class Add2:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, src1, src2):
            self.__new_data = src1.data + src2.data

        def commit(self):
            dst_data_item = self.computation.get_result("dst")
            dst_data_item.data = self.__new_data
            TestDocumentModelClass.add2_eval_count += 1

    def test_new_computation_becomes_unresolved_when_data_item_input_is_removed_from_document(self):
        Symbolic.register_computation_type("add2", self.Add2)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item2 = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            computation = document_model.create_computation()
            computation.create_input_item("src1", Symbolic.make_item(data_item))
            computation.create_input_item("src2", Symbolic.make_item(data_item2))
            computation.create_output_item("dst", Symbolic.make_item(data_item3))
            computation.processing_id = "add2"
            document_model.append_computation(computation)
            self.assertTrue(computation.is_resolved)
            document_model.recompute_all()
            self.assertFalse(computation.needs_update)
            document_model.remove_data_item(data_item)
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(1, len(document_model.display_items))
            self.assertEqual(0, len(document_model.computations))

    def test_new_computation_becomes_unresolved_when_data_source_input_is_removed_from_document(self):
        Symbolic.register_computation_type("add2", self.Add2)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item2 = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            computation = document_model.create_computation()
            computation.create_input_item("src1", Symbolic.make_item(data_item))
            computation.create_input_item("src2", Symbolic.make_item(data_item2))
            computation.create_output_item("dst", Symbolic.make_item(data_item3))
            computation.processing_id = "add2"
            document_model.append_computation(computation)
            self.assertTrue(computation.is_resolved)
            document_model.recompute_all()
            self.assertFalse(computation.needs_update)
            document_model.remove_data_item(data_item)
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(1, len(document_model.display_items))
            self.assertEqual(0, len(document_model.computations))

    def test_new_computation_becomes_unresolved_when_xdata_input_is_removed_from_document(self):
        Symbolic.register_computation_type("add2", self.Add2)
        for t in ("xdata", "display_xdata", "cropped_xdata", "cropped_display_xdata", "filter_xdata", "filtered_xdata"):
            with TestContext.create_memory_context() as test_context:
                document_model = test_context.create_document_model()
                data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
                data_item2 = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
                data_item3 = DataItem.DataItem()
                document_model.append_data_item(data_item)
                document_model.append_data_item(data_item2)
                document_model.append_data_item(data_item3)
                computation = document_model.create_computation()
                computation.create_input_item("src1", Symbolic.make_item(document_model.get_display_item_for_data_item(data_item).display_data_channel, type=t))
                computation.create_input_item("src2", Symbolic.make_item(document_model.get_display_item_for_data_item(data_item2).display_data_channel, type=t))
                computation.create_output_item("dst", Symbolic.make_item(data_item3))
                computation.processing_id = "add2"
                document_model.append_computation(computation)
                self.assertTrue(computation.is_resolved)
                document_model.recompute_all()
                self.assertFalse(computation.needs_update)
                document_model.remove_data_item(data_item)
                self.assertEqual(1, len(document_model.data_items))
                self.assertEqual(1, len(document_model.display_items))
                self.assertEqual(0, len(document_model.computations))

    def test_new_computation_becomes_unresolved_when_data_structure_input_is_removed_from_document(self):
        Symbolic.register_computation_type("set_const_struct", self.SetConstDataStruct)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            data_item2 = DataItem.DataItem(numpy.zeros((3, 3), numpy.int))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            data_structure = document_model.create_data_structure()
            data_structure.set_property_value("value", 3)
            document_model.append_data_structure(data_structure)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.create_input_item("data_structure", Symbolic.make_item(data_structure))
            computation.create_output_item("dst", Symbolic.make_item(data_item2))
            computation.processing_id = "set_const_struct"
            document_model.append_computation(computation)
            self.assertTrue(computation.is_resolved)
            document_model.recompute_all()
            self.assertFalse(computation.needs_update)
            document_model.remove_data_structure(data_structure)
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(1, len(document_model.display_items))
            self.assertEqual(0, len(document_model.computations))

    def test_new_computation_becomes_unresolved_when_graphic_input_is_removed_from_document(self):
        Symbolic.register_computation_type("set_const_graphic", self.SetConstGraphic)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            data_item2 = DataItem.DataItem(numpy.zeros((3, 3), numpy.int))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            display_item = document_model.get_display_item_for_data_item(data_item)
            graphic = Graphics.PointGraphic()
            display_item.add_graphic(graphic)  # computation should become valid
            # display_item.add_graphic(graphic)  # purposely not added
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.create_input_item("graphic", Symbolic.make_item(graphic))
            computation.create_output_item("dst", Symbolic.make_item(data_item2))
            computation.processing_id = "set_const_graphic"
            document_model.append_computation(computation)
            self.assertTrue(computation.is_resolved)
            document_model.recompute_all()
            self.assertFalse(computation.needs_update)
            display_item.remove_graphic(graphic).close()
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(1, len(document_model.display_items))
            self.assertEqual(0, len(document_model.computations))

    def test_new_computation_deletes_computation_when_result_data_item_deleted(self):
        Symbolic.register_computation_type("add2", self.Add2)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item2 = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            computation = document_model.create_computation()
            computation.create_input_item("src1", Symbolic.make_item(data_item))
            computation.create_input_item("src2", Symbolic.make_item(data_item2))
            computation.create_output_item("dst", Symbolic.make_item(data_item3))
            computation.processing_id = "add2"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(document_model.computations), 1)
            self.assertEqual(len(document_model.data_items), 3)
            document_model.remove_data_item(data_item3)
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 0)
            self.assertEqual(len(document_model.get_dependent_items(data_item2)), 0)
            self.assertEqual(len(document_model.get_dependent_items(data_item3)), 0)
            self.assertEqual(len(document_model.data_items), 2)
            self.assertEqual(len(document_model.computations), 0)

    class Overlay2:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, src):
            pass

        def commit(self):
            self.computation.set_referenced_data("dst1", numpy.zeros((2, )))
            self.computation.set_referenced_data("dst2", numpy.zeros((2, )))

    def test_new_computation_deletes_computation_when_any_result_data_item_deleted(self):
        Symbolic.register_computation_type("overlay2", self.Overlay2)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, )))
            data_item3 = DataItem.DataItem()
            data_item4 = DataItem.DataItem()
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item3)
            document_model.append_data_item(data_item4)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.create_output_item("dst1", Symbolic.make_item(data_item3))
            computation.create_output_item("dst2", Symbolic.make_item(data_item4))
            computation.processing_id = "overlay2"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(document_model.computations), 1)
            self.assertEqual(len(document_model.data_items), 3)
            # NOTE: removing display item which will remove the data item output
            document_model.remove_display_item(document_model.display_items[-1])
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 0)
            self.assertEqual(len(document_model.data_items), 1)
            self.assertEqual(len(document_model.computations), 0)

    def test_new_computation_deleting_computation_deletes_all_results(self):
        Symbolic.register_computation_type("add2", self.Add2)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item2 = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            computation = document_model.create_computation()
            computation.create_input_item("src1", Symbolic.make_item(data_item))
            computation.create_input_item("src2", Symbolic.make_item(data_item2))
            computation.create_output_item("dst", Symbolic.make_item(data_item3))
            computation.processing_id = "add2"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(document_model.computations), 1)
            self.assertEqual(len(document_model.data_items), 3)
            document_model.remove_computation(computation)
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 0)
            self.assertEqual(len(document_model.get_dependent_items(data_item2)), 0)
            self.assertEqual(len(document_model.get_dependent_items(data_item3)), 0)
            self.assertEqual(len(document_model.data_items), 2)
            self.assertEqual(len(document_model.computations), 0)

    def test_new_computation_deleting_computation_deletes_all_result_lists(self):
        Symbolic.register_computation_type("n_graphics", self.NGraphics)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            value = computation.create_variable("value", "integral", 3)
            computation.create_output_item("graphics", Symbolic.make_item_list([]))
            computation.processing_id = "n_graphics"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(document_model.computations), 1)
            self.assertEqual(len(document_model.data_items), 1)
            self.assertEqual(len(display_item.graphics), 3)
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 3)
            document_model.remove_computation(computation)
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 0)
            self.assertEqual(len(document_model.data_items), 1)
            self.assertEqual(len(document_model.computations), 0)

    def test_new_computation_deleting_result_on_computation_with_multiple_results_deletes_all_results_and_computation(self):
        Symbolic.register_computation_type("n_graphics", self.NGraphics)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            value = computation.create_variable("value", "integral", 3)
            computation.create_output_item("graphics", Symbolic.make_item_list([]))
            computation.processing_id = "n_graphics"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(document_model.computations), 1)
            self.assertEqual(len(document_model.data_items), 1)
            self.assertEqual(len(display_item.graphics), 3)
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 3)
            display_item.remove_graphic(display_item.graphics[0]).close()
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 0)
            self.assertEqual(len(document_model.data_items), 1)
            self.assertEqual(len(document_model.computations), 0)

    def test_new_computation_deletes_auto_created_result_data_item_when_input_data_item_deleted(self):
        Symbolic.register_computation_type("set_const", self.SetConst)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.create_variable("value", "integral", 3)
            computation.processing_id = "set_const"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(document_model.computations), 1)
            self.assertEqual(len(document_model.data_items), 2)
            document_model.remove_data_item(data_item)
            self.assertEqual(len(document_model.data_items), 0)
            self.assertEqual(len(document_model.computations), 0)

    class AddN:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, src_list):
            if len(set(src.data_shape for src in src_list)) == 1:
                self.__new_data = numpy.sum([src.data for src in src_list], axis=0)
            else:
                self.__new_data = None

        def commit(self):
            if self.__new_data is not None:
                self.computation.set_referenced_data("dst", self.__new_data)
            else:
                self.computation.clear_referenced_data("dst")

    def test_new_computation_allows_list_of_data_item_inputs(self):
        Symbolic.register_computation_type("add_n", self.AddN)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            data_item1 = DataItem.DataItem(numpy.full((2, 2), 1))
            document_model.append_data_item(data_item1)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.full((2, 2), 2))
            document_model.append_data_item(data_item2)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            computation = document_model.create_computation()
            items = Symbolic.make_item_list([display_item1.display_data_channel, display_item2.display_data_channel], type="display_xdata")
            computation.create_input_item("src_list", items)
            computation.processing_id = "add_n"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(document_model.computations), 1)
            self.assertEqual(len(document_model.data_items), 3)
            data_item3 = document_model.data_items[2]
            self.assertTrue(numpy.array_equal(data_item3.data, numpy.full((2, 2), 3)))

    def test_new_computation_treats_list_of_data_item_inputs_as_inputs(self):
        Symbolic.register_computation_type("add_n", self.AddN)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            data_item1 = DataItem.DataItem(numpy.full((2, 2), 1))
            document_model.append_data_item(data_item1)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.full((2, 2), 2))
            document_model.append_data_item(data_item2)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            computation = document_model.create_computation()
            items = Symbolic.make_item_list([display_item1.display_data_channel, display_item2.display_data_channel], type="display_xdata")
            computation.create_input_item("src_list", items)
            computation.processing_id = "add_n"
            document_model.append_computation(computation)
            self.assertIn(data_item1, computation._inputs)
            self.assertIn(data_item2, computation._inputs)

    def test_new_computation_with_list_of_data_item_inputs_does_not_remove_outputs_when_item_in_list_is_removed(self):
        Symbolic.register_computation_type("add_n", self.AddN)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            data_item1 = DataItem.DataItem(numpy.full((2, 2), 1))
            document_model.append_data_item(data_item1)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.full((2, 2), 2))
            document_model.append_data_item(data_item2)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            computation = document_model.create_computation()
            items = Symbolic.make_item_list([display_item1.display_data_channel, display_item2.display_data_channel], type="display_xdata")
            computation.create_input_item("src_list", items)
            computation.processing_id = "add_n"
            document_model.append_computation(computation)
            document_model.recompute_all()  # establish outputs
            self.assertEqual(1, len(document_model.computations))
            self.assertEqual(3, len(document_model.data_items))
            document_model.remove_data_item(data_item2)
            self.assertEqual(1, len(document_model.computations))
            self.assertEqual(2, len(document_model.data_items))

    def test_new_computation_reevaluates_when_list_of_data_item_inputs_changes(self):
        Symbolic.register_computation_type("add_n", self.AddN)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            data_item1 = DataItem.DataItem(numpy.full((2, 2), 1))
            document_model.append_data_item(data_item1)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.full((2, 2), 2))
            document_model.append_data_item(data_item2)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            data_item3 = DataItem.DataItem(numpy.full((2, 2), 3))
            document_model.append_data_item(data_item3)
            display_item3 = document_model.get_display_item_for_data_item(data_item3)
            computation = document_model.create_computation()
            items = Symbolic.make_item_list([display_item1.display_data_channel, display_item2.display_data_channel], type="display_xdata")
            computation.create_input_item("src_list", items)
            computation.processing_id = "add_n"
            document_model.append_computation(computation)
            document_model.recompute_all()
            data_item4 = document_model.data_items[3]
            self.assertTrue(numpy.array_equal(data_item4.data, numpy.full((2, 2), 3)))
            computation.insert_item_into_objects("src_list", 0, Symbolic.make_item(display_item3.display_data_channel, type="display_xdata"))
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item4.data, numpy.full((2, 2), 6)))
            computation.remove_item_from_objects("src_list", 2)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item4.data, numpy.full((2, 2), 4)))

    def test_new_computation_reevaluates_when_referenced_item_in_list_of_inputs_is_removed(self):
        Symbolic.register_computation_type("add_n", self.AddN)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            data_item1 = DataItem.DataItem(numpy.full((2, 2), 1))
            document_model.append_data_item(data_item1)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.full((2, 2), 2))
            document_model.append_data_item(data_item2)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            data_item3 = DataItem.DataItem(numpy.full((2, 2), 3))
            document_model.append_data_item(data_item3)
            display_item3 = document_model.get_display_item_for_data_item(data_item3)
            computation = document_model.create_computation()
            items = Symbolic.make_item_list([display_item1.display_data_channel, display_item2.display_data_channel, display_item3.display_data_channel], type="display_xdata")
            computation.create_input_item("src_list", items)
            computation.processing_id = "add_n"
            document_model.append_computation(computation)
            document_model.recompute_all()
            data_item4 = document_model.data_items[3]
            self.assertTrue(numpy.array_equal(data_item4.data, numpy.full((2, 2), 6)))
            document_model.remove_data_item(data_item3)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item4.data, numpy.full((2, 2), 3)))

    def test_new_computation_unresolved_list_prevents_recomputation(self):
        Symbolic.register_computation_type("add_n", self.AddN)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            data_item1 = DataItem.DataItem(numpy.full((2, 2), 1))
            document_model.append_data_item(data_item1)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.full((2, 2), 2))
            document_model.append_data_item(data_item2)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            computation = document_model.create_computation()
            src_list = Symbolic.make_item_list([None, display_item2.display_data_channel], type="display_xdata")
            computation.create_input_item("src_list", src_list)
            computation.processing_id = "add_n"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(document_model.computations), 1)
            self.assertEqual(len(document_model.data_items), 2)
            computation.remove_item_from_objects("src_list", 0)
            computation.insert_item_into_objects("src_list", 0, Symbolic.make_item(display_item1.display_data_channel, type="display_xdata"))
            document_model.recompute_all()
            data_item3 = document_model.data_items[2]
            self.assertTrue(numpy.array_equal(data_item3.data, numpy.full((2, 2), 3)))

    def test_new_computation_recomputes_when_list_element_changes(self):
        Symbolic.register_computation_type("add_n", self.AddN)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            data_item1 = DataItem.DataItem(numpy.full((2, 2), 1))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.full((2, 2), 2))
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation()
            items = Symbolic.make_item_list([data_item1, data_item2], type="xdata")
            computation.create_input_item("src_list", items)
            computation.processing_id = "add_n"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(document_model.computations), 1)
            self.assertEqual(len(document_model.data_items), 3)
            data_item3 = document_model.data_items[2]
            self.assertTrue(numpy.array_equal(data_item3.data, numpy.full((2, 2), 3)))
            data_item1.set_data(numpy.full((2, 2), 2))
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item3.data, numpy.full((2, 2), 4)))

    class CopyData:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, src):
            self.__new_data = src.data

        def commit(self):
            dst_data_item = self.computation.get_result("dst")
            dst_data_item.data = self.__new_data

    def test_new_computation_cannot_result_in_parallel_dependency(self):
        Symbolic.register_computation_type("copy_data", self.CopyData)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            data_item2 = DataItem.DataItem()
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.create_output_item("dst", Symbolic.make_item(data_item2))
            computation.processing_id = "copy_data"
            document_model.append_computation(computation)
            with self.assertRaises(Exception):
                computation2 = document_model.create_computation()
                computation2.create_input_item("src", Symbolic.make_item(data_item))
                computation2.create_output_item("dst", Symbolic.make_item(data_item2))
                computation2.processing_id = "copy_data"
                document_model.append_computation(computation2)

    def test_new_computation_cannot_result_in_immediate_circular_dependency(self):
        Symbolic.register_computation_type("copy_data", self.CopyData)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            document_model.append_data_item(data_item)
            with self.assertRaises(Exception):
                computation = document_model.create_computation()
                computation.create_input_item("src", Symbolic.make_item(data_item))
                computation.create_output_item("dst", Symbolic.make_item(data_item))
                computation.processing_id = "copy_data"
                document_model.append_computation(computation)

    def test_new_computation_cannot_result_in_secondary_circular_dependency(self):
        Symbolic.register_computation_type("copy_data", self.CopyData)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            data_item2 = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.create_output_item("dst", Symbolic.make_item(data_item2))
            computation.processing_id = "copy_data"
            document_model.append_computation(computation)
            with self.assertRaises(Exception):
                computation = document_model.create_computation()
                computation.create_input_item("src", Symbolic.make_item(data_item2))
                computation.create_output_item("dst", Symbolic.make_item(data_item))
                computation.processing_id = "copy_data"
                document_model.append_computation(computation)

    def test_new_computation_with_missing_input_does_not_recompute(self):
        TestDocumentModelClass.add2_eval_count = 0
        Symbolic.register_computation_type("add2", self.Add2)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item2 = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            computation = document_model.create_computation()
            computation.create_input_item("src1", Symbolic.make_item(data_item))
            computation.create_input_item("src2", Symbolic.make_item(data_item2))
            computation.create_output_item("dst", Symbolic.make_item(data_item3))
            computation.processing_id = "add2"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(TestDocumentModelClass.add2_eval_count, 1)
            document_model.recompute_all()
            self.assertEqual(TestDocumentModelClass.add2_eval_count, 1)
            document_model.remove_data_item(data_item)
            document_model.recompute_all()
            self.assertEqual(TestDocumentModelClass.add2_eval_count, 1)

    def test_new_computation_with_missing_input_recomputes_when_missing_input_supplied(self):
        TestDocumentModelClass.add2_eval_count = 0
        Symbolic.register_computation_type("add2", self.Add2)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item2 = DataItem.DataItem(numpy.ones((2, 2), numpy.int))  # NOT INITIALLY ADDED TO DOCUMENT
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item3)
            computation = document_model.create_computation()
            computation.create_input_item("src1", Symbolic.make_item(data_item))
            computation.create_input_item("src2", Symbolic.make_item(data_item2), _item_specifier=DataStructure.get_object_specifier(data_item2))
            computation.create_output_item("dst", Symbolic.make_item(data_item3))
            computation.processing_id = "add2"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(TestDocumentModelClass.add2_eval_count, 0)
            document_model.append_data_item(data_item2)
            document_model.recompute_all()
            self.assertEqual(TestDocumentModelClass.add2_eval_count, 1)

    def test_new_computation_with_initially_missing_input_fails_gracefully(self):
        TestDocumentModelClass.add2_eval_count = 0
        Symbolic.register_computation_type("add2", self.Add2)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item3)
            computation = document_model.create_computation()
            computation.create_input_item("src1", Symbolic.make_item(data_item))
            computation.create_output_item("dst", Symbolic.make_item(data_item3))
            computation.processing_id = "add2"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(TestDocumentModelClass.add2_eval_count, 0)

    class PassThru:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, src_xdata):
            self.__new_data = numpy.copy(src_xdata.data)

        def commit(self):
            self.computation.set_referenced_data("dst", self.__new_data)

    def test_new_computation_with_missing_output_does_not_evaluate(self):
        Symbolic.register_computation_type("pass_thru", self.PassThru)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item3 = DataItem.DataItem()
            with contextlib.closing(data_item3):
                document_model.append_data_item(data_item)
                # document_model.append_data_item(data_item3)  # purposely not added
                computation = document_model.create_computation()
                computation.create_input_item("src_xdata", Symbolic.make_item(data_item, type="xdata"))
                computation.create_output_item("dst", Symbolic.make_item(data_item3), _item_specifier=DataStructure.get_object_specifier(data_item3))
                computation.processing_id = "pass_thru"
                document_model.append_computation(computation)
                document_model.recompute_all()
                self.assertEqual(1, len(document_model.data_items))

    def test_new_computation_with_missing_input_which_subsequently_appears_does_evaluate(self):
        Symbolic.register_computation_type("pass_thru", self.PassThru)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item3 = DataItem.DataItem()
            # document_model.append_data_item(data_item)  # purposely not added
            document_model.append_data_item(data_item3)
            computation = document_model.create_computation()
            computation.create_input_item("src_xdata", Symbolic.make_item(data_item, type="xdata"), _item_specifier=DataStructure.get_object_specifier(data_item))
            computation.create_output_item("dst", Symbolic.make_item(data_item3))
            computation.processing_id = "pass_thru"
            document_model.append_computation(computation)
            self.assertFalse(computation.is_resolved)
            document_model.append_data_item(data_item)  # computation should become valid
            self.assertTrue(computation.is_resolved)

    def test_new_computation_with_missing_output_which_subsequently_appears_does_evaluate(self):
        Symbolic.register_computation_type("pass_thru", self.PassThru)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item)
            # document_model.append_data_item(data_item3)  # purposely not added
            computation = document_model.create_computation()
            computation.create_input_item("src_xdata", Symbolic.make_item(data_item, type="xdata"))
            computation.create_output_item("dst", Symbolic.make_item(data_item3), _item_specifier=DataStructure.get_object_specifier(data_item3))
            computation.processing_id = "pass_thru"
            document_model.append_computation(computation)
            self.assertFalse(computation.is_resolved)
            document_model.append_data_item(data_item3)  # computation should become valid
            self.assertTrue(computation.is_resolved)

    def test_new_computation_with_missing_data_struct_input_which_subsequently_appears_does_evaluate(self):
        Symbolic.register_computation_type("set_const_struct", self.SetConstDataStruct)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            data_item2 = DataItem.DataItem(numpy.zeros((3, 3), numpy.int))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            data_structure = document_model.create_data_structure()
            data_structure.set_property_value("value", 3)
            # document_model.append_data_structure(data_structure)  # purposely not added
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.create_input_item("data_structure", Symbolic.make_item(data_structure), _item_specifier=DataStructure.get_object_specifier(data_structure))
            computation.create_output_item("dst", Symbolic.make_item(data_item2))
            computation.processing_id = "set_const_struct"
            document_model.append_computation(computation)
            self.assertFalse(computation.is_resolved)
            document_model.append_data_structure(data_structure)  # computation should become valid
            self.assertTrue(computation.is_resolved)

    class SetConstGraphic:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, src, graphic):
            self.__new_data = numpy.full(src.data.shape, graphic.position[0])

        def commit(self):
            self.computation.set_referenced_data("dst", self.__new_data)

    def test_new_computation_with_missing_graphic_input_which_subsequently_appears_does_evaluate(self):
        Symbolic.register_computation_type("set_const_graphic", self.SetConstGraphic)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            data_item2 = DataItem.DataItem(numpy.zeros((3, 3), numpy.int))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            display_item = document_model.get_display_item_for_data_item(data_item)
            graphic = Graphics.PointGraphic()
            # display_item.add_graphic(graphic)  # purposely not added
            computation = document_model.create_computation()
            computation.create_input_item("src", Symbolic.make_item(data_item))
            computation.create_input_item("graphic", Symbolic.make_item(graphic), _item_specifier=DataStructure.get_object_specifier(graphic))
            computation.create_output_item("dst", Symbolic.make_item(data_item2))
            computation.processing_id = "set_const_graphic"
            document_model.append_computation(computation)
            self.assertFalse(computation.is_resolved)
            display_item.add_graphic(graphic)  # computation should become valid
            self.assertTrue(computation.is_resolved)

    class GenerateZero:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, rect):
            size = int(rect.bounds[1][0] * 100), int(rect.bounds[1][1] * 100)
            self.__new_data = numpy.zeros(size)

        def commit(self):
            dst_data_item = self.computation.get_result("dst")
            if not dst_data_item:
                dst_data_item = self.computation.api.library.create_data_item()
                self.computation.set_result("dst", dst_data_item)
            dst_data_item.data = self.__new_data

    def test_dependency_from_graphic_to_data_item_establishes_cleanly(self):
        Symbolic.register_computation_type("genzero", self.GenerateZero)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            graphic = Graphics.RectangleGraphic()
            display_item.add_graphic(graphic)
            computation = document_model.create_computation()
            computation.create_input_item("rect", Symbolic.make_item(graphic))
            computation.processing_id = "genzero"
            document_model.append_computation(computation)
            document_model.recompute_all()
            target_data_item = document_model.data_items[1]
            self.assertEqual(document_model.get_dependent_items(graphic)[0], target_data_item)
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 0)
            self.assertEqual(len(document_model.get_dependent_items(target_data_item)), 0)
            self.assertIn(graphic, document_model.get_source_items(target_data_item))
            self.assertEqual(len(document_model.get_source_items(graphic)), 0)
            self.assertEqual(len(document_model.get_source_items(data_item)), 0)

    class CropHalf:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, src_xdata):
            top = src_xdata.dimensional_shape[0] // 4
            left = src_xdata.dimensional_shape[1] // 4
            bottom = top + src_xdata.dimensional_shape[0] // 2
            right = left + src_xdata.dimensional_shape[1] // 2
            self.__new_data = src_xdata.data[top:bottom, left:right]

        def commit(self):
            dst_data_item = self.computation.get_result("dst")
            if not dst_data_item:
                dst_data_item = self.computation.api.library.create_data_item()
                self.computation.set_result("dst", dst_data_item)
            dst_data_item.data = self.__new_data

    def test_computation_can_depend_on_xdata(self):
        Symbolic.register_computation_type("crop_half", self.CropHalf)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.random.randn(12, 12))
            data_item2 = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation()
            computation.create_input_item("src_xdata", Symbolic.make_item(data_item, type="xdata"))
            computation.create_output_item("dst", Symbolic.make_item(data_item2))
            computation.processing_id = "crop_half"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item2.data, data_item.data[3:9, 3:9]))
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 1)
            self.assertEqual(document_model.get_dependent_items(data_item)[0], data_item2)
            self.assertEqual(len(document_model.get_source_items(data_item2)), 1)
            self.assertIn(data_item, document_model.get_source_items(data_item2))

    def test_computation_can_depend_on_display_xdata(self):
        Symbolic.register_computation_type("crop_half", self.CropHalf)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.random.randn(12, 12, 4))
            data_item2 = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_data_channel = display_item.display_data_channels[0]
            display_data_channel.slice_center = 2
            display_data_channel.slice_width = 1
            computation = document_model.create_computation()
            computation.create_input_item("src_xdata", Symbolic.make_item(display_data_channel, type="display_xdata"))
            computation.create_output_item("dst", Symbolic.make_item(data_item2))
            computation.processing_id = "crop_half"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item2.data, data_item.data[3:9, 3:9, 2]))
            self.assertEqual(1, len(document_model.get_dependent_items(data_item)))
            self.assertEqual(document_model.get_dependent_items(data_item)[0], data_item2)
            self.assertEqual(2, len(document_model.get_source_items(data_item2)))  # data item, display item
            self.assertIn(data_item, document_model.get_source_items(data_item2))

    def test_computation_can_depend_on_cropped_xdata(self):
        Symbolic.register_computation_type("crop_half", self.CropHalf)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.random.randn(24, 24))
            data_item2 = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            display_item = document_model.get_display_item_for_data_item(data_item)
            graphic = Graphics.RectangleGraphic()
            graphic.bounds = (0, 0), (0.5, 0.5)
            display_item.add_graphic(graphic)
            computation = document_model.create_computation()
            computation.create_input_item("src_xdata", Symbolic.make_item(display_item.display_data_channel, type="cropped_xdata", secondary_item=graphic))
            computation.create_output_item("dst", Symbolic.make_item(data_item2))
            computation.processing_id = "crop_half"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item2.data, data_item.data[3:9, 3:9]))
            self.assertEqual(1, len(document_model.get_dependent_items(data_item)))
            self.assertEqual(document_model.get_dependent_items(data_item)[0], data_item2)
            self.assertEqual(1, len(document_model.get_dependent_items(graphic)))
            self.assertEqual(document_model.get_dependent_items(graphic)[0], data_item2)
            self.assertEqual(3, len(document_model.get_source_items(data_item2)))  # rect, data item, display item
            self.assertIn(graphic, document_model.get_source_items(data_item2))
            self.assertIn(data_item, document_model.get_source_items(data_item2))

    def test_computation_can_depend_on_cropped_display_xdata(self):
        Symbolic.register_computation_type("crop_half", self.CropHalf)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.random.randn(24, 24, 4))
            data_item2 = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_data_channel = display_item.display_data_channels[0]
            display_data_channel.slice_center = 2
            display_data_channel.slice_width = 1
            graphic = Graphics.RectangleGraphic()
            graphic.bounds = (0, 0), (0.5, 0.5)
            display_item.add_graphic(graphic)
            computation = document_model.create_computation()
            computation.create_input_item("src_xdata", Symbolic.make_item(display_data_channel, type="cropped_display_xdata", secondary_item=graphic))
            computation.create_output_item("dst", Symbolic.make_item(data_item2))
            computation.processing_id = "crop_half"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item2.data, data_item.data[3:9, 3:9, 2]))
            self.assertEqual(1, len(document_model.get_dependent_items(data_item)))
            self.assertEqual(document_model.get_dependent_items(data_item)[0], data_item2)
            self.assertEqual(1, len(document_model.get_dependent_items(graphic)))
            self.assertEqual(document_model.get_dependent_items(graphic)[0], data_item2)
            self.assertEqual(3, len(document_model.get_source_items(data_item2)))  # rect, data item, display item
            self.assertIn(graphic, document_model.get_source_items(data_item2))
            self.assertIn(data_item, document_model.get_source_items(data_item2))

    def test_computation_can_depend_on_filter_xdata(self):
        Symbolic.register_computation_type("pass_thru", self.PassThru)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.full((20, 20), 5))
            data_item2 = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            graphic = Graphics.RingGraphic()
            graphic.radius_1 = 0.2
            graphic.radius_2 = 1.0
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_graphic(graphic)
            computation = document_model.create_computation()
            computation.create_input_item("src_xdata", Symbolic.make_item(display_item.display_data_channel, type="filter_xdata"))
            computation.create_output_item("dst", Symbolic.make_item(data_item2))
            computation.processing_id = "pass_thru"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(data_item2.xdata.dimensional_shape, (20, 20))
            self.assertEqual(numpy.amin(data_item2.data), 0)
            self.assertEqual(numpy.amax(data_item2.data), 1)
            self.assertEqual(1, len(document_model.get_dependent_items(data_item)))
            self.assertEqual(document_model.get_dependent_items(data_item)[0], data_item2)
            self.assertEqual(1, len(document_model.get_dependent_items(graphic)))
            self.assertEqual(document_model.get_dependent_items(graphic)[0], data_item2)
            self.assertEqual(3, len(document_model.get_source_items(data_item2)))  # graphic, data item, display item
            self.assertIn(graphic, document_model.get_source_items(data_item2))
            self.assertIn(data_item, document_model.get_source_items(data_item2))

    def test_computation_can_depend_on_filtered_xdata(self):
        Symbolic.register_computation_type("pass_thru", self.PassThru)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.full((20, 20), 5, dtype=numpy.complex128))
            data_item2 = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            graphic = Graphics.RingGraphic()
            graphic.radius_1 = 0.2
            graphic.radius_2 = 1.0
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_graphic(graphic)
            computation = document_model.create_computation()
            computation.create_input_item("src_xdata", Symbolic.make_item(display_item.display_data_channel, type="filtered_xdata"))
            computation.create_output_item("dst", Symbolic.make_item(data_item2))
            computation.processing_id = "pass_thru"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(data_item2.xdata.dimensional_shape, (20, 20))
            self.assertEqual(numpy.amin(data_item2.data), 0)
            self.assertEqual(numpy.amax(data_item2.data), 5)
            self.assertEqual(1, len(document_model.get_dependent_items(data_item)))
            self.assertEqual(document_model.get_dependent_items(data_item)[0], data_item2)
            self.assertEqual(1, len(document_model.get_dependent_items(graphic)),)
            self.assertEqual(document_model.get_dependent_items(graphic)[0], data_item2)
            self.assertEqual(3, len(document_model.get_source_items(data_item2)))  # graphic, display item, data item
            self.assertIn(graphic, document_model.get_source_items(data_item2))
            self.assertIn(data_item, document_model.get_source_items(data_item2))

    def test_computation_sequence_evaluates(self):
        Symbolic.register_computation_type("pass_thru", self.PassThru)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item1 = DataItem.DataItem(numpy.zeros((2, 2)))
            data_item2 = DataItem.DataItem()
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            computation1 = document_model.create_computation()
            computation1.create_input_item("src_xdata", Symbolic.make_item(data_item1, type="xdata"))
            computation1.create_output_item("dst", Symbolic.make_item(data_item2))
            computation1.processing_id = "pass_thru"
            document_model.append_computation(computation1)
            computation2 = document_model.create_computation()
            computation2.create_input_item("src_xdata", Symbolic.make_item(data_item2, type="xdata"))
            computation2.create_output_item("dst", Symbolic.make_item(data_item3))
            computation2.processing_id = "pass_thru"
            document_model.append_computation(computation2)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item1.data, data_item2.data))
            self.assertTrue(numpy.array_equal(data_item1.data, data_item3.data))

    def test_computation_deletes_when_source_deletes(self):
        Symbolic.register_computation_type("pass_thru", self.PassThru)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item1 = DataItem.DataItem(numpy.zeros((2, 2)))
            data_item2 = DataItem.DataItem()
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            computation = document_model.create_computation()
            computation.source = data_item3
            computation.create_input_item("src_xdata", Symbolic.make_item(data_item1, type="xdata"))
            computation.create_output_item("dst", Symbolic.make_item(data_item2))
            computation.processing_id = "pass_thru"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(1, len(document_model.computations))
            document_model.remove_data_item(data_item3)
            self.assertEqual(0, len(document_model.computations))

    class SourceCycleTest:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, s, i1, i2l):
            pass

        def commit(self):
            self.computation.set_referenced_data("dst1", numpy.zeros((2, )))
            self.computation.set_referenced_data("dst2", numpy.zeros((2, )))

    def test_computation_deletes_when_source_cycle_deletes(self):
        Symbolic.register_computation_type("source_cycle_test", self.SourceCycleTest)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            data_item1 = DataItem.DataItem(numpy.zeros((2, )))
            document_model.append_data_item(data_item1)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            interval1 = Graphics.IntervalGraphic()
            interval2 = Graphics.IntervalGraphic()
            interval3 = Graphics.IntervalGraphic()
            display_item1.add_graphic(interval1)
            display_item1.add_graphic(interval2)
            display_item1.add_graphic(interval3)
            computation = document_model.create_computation()
            computation.processing_id = "source_cycle_test"
            computation.create_input_item("s", Symbolic.make_item(data_item1, type="xdata"))
            computation.create_input_item("i1", Symbolic.make_item(interval1))
            computation.create_input_item("i2l", Symbolic.make_item_list([interval2, interval3]))
            computation.source = interval1
            document_model.append_computation(computation)
            interval1.source = computation
            interval2.source = interval1
            interval3.source = interval1
            document_model.recompute_all()
            document_model.remove_data_item(document_model.data_items[-1])
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(0, len(document_model.computations))
            self.assertEqual(0, len(display_item1.graphics))
            self.assertEqual(0, len(document_model.get_dependent_items(data_item1)))

    def test_computation_deletes_when_triggered_by_both_inputs_and_source_deletion(self):
        Symbolic.register_computation_type("pass_thru", self.PassThru)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item1 = DataItem.DataItem(numpy.zeros((2, 2)))
            data_item2 = DataItem.DataItem()
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            data_item3.source = data_item2
            computation = document_model.create_computation()
            computation.source = data_item3
            computation.create_input_item("src_xdata", Symbolic.make_item(data_item1, type="xdata"))
            computation.create_output_item("dst", Symbolic.make_item(data_item2))
            computation.processing_id = "pass_thru"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(1, len(document_model.computations))
            # deleting data_item1 will delete the computation (as its only input)
            # deleting the computation will delete data_item2 (which is its output)
            # deleting data_item2 will delete data_item3 (which has it as its source)
            # deleting data_item3 will also delete computation (which has it as its source)
            document_model.remove_data_item(data_item1)
            self.assertEqual(0, len(document_model.data_items))
            self.assertEqual(0, len(document_model.computations))

    def test_computation_deletes_when_any_input_deleted(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item1)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item2)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            document_model.get_cross_correlate_new(display_item1, display_item1.data_item, display_item2, display_item2.data_item)
            document_model.remove_data_item(data_item2)
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(data_item1, document_model.data_items[0])
            self.assertEqual(0, len(document_model.computations))

    def test_new_computation_with_missing_processor_fails_gracefully(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item3)
            computation = document_model.create_computation()
            computation.create_input_item("src1", Symbolic.make_item(data_item))
            computation.create_output_item("dst", Symbolic.make_item(data_item3))
            computation.processing_id = "nothing"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertTrue(computation.error_text.startswith("Missing computation"))

    def test_undelete_data_structure(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_structure = document_model.create_data_structure()
            data_structure.set_property_value("amount", 1)
            document_model.append_data_structure(data_structure)
            data_structure = document_model.create_data_structure()
            data_structure.set_property_value("amount", 2)
            document_model.append_data_structure(data_structure)
            data_structure = document_model.create_data_structure()
            data_structure.set_property_value("amount", 3)
            document_model.append_data_structure(data_structure)
            with contextlib.closing(document_model.remove_data_structure_with_log(document_model.data_structures[1])) as undelete_log:
                self.assertEqual(2, len(document_model.data_structures))
                document_model.undelete_all(undelete_log)
            # required to handle is_reading?
            self.assertEqual(3, len(document_model.data_structures))
            self.assertEqual(2, document_model.data_structures[1].amount)

    class Negate:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, src_xdata):
            self.__new_data = -src_xdata.data

        def commit(self):
            self.computation.set_referenced_data("dst", self.__new_data)

    def test_undelete_computation(self):
        Symbolic.register_computation_type("negate", self.Negate)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            # create the data items
            data_item = DataItem.DataItem(numpy.ones((4, 4)))
            document_model.append_data_item(data_item)
            data_item2 = DataItem.DataItem()
            document_model.append_data_item(data_item2)
            # create the computation
            computation = document_model.create_computation()
            computation.source = data_item
            computation.create_input_item("src_xdata", Symbolic.make_item(data_item, type="xdata"))
            computation.create_output_item("dst", Symbolic.make_item(data_item2))
            computation.processing_id = "negate"
            document_model.append_computation(computation)
            document_model.recompute_all()
            # check results
            self.assertTrue(numpy.array_equal(numpy.full((4, 4), -1), data_item2.data))
            # remove computation and verify it was removed along with dst data item
            with contextlib.closing(document_model.remove_computation_with_log(computation, safe=True)) as undelete_log:
                self.assertEqual(1, len(document_model.data_items))
                self.assertEqual(0, len(document_model.computations))
                # start a recompute, but it won't do anything now
                data_item.set_data(numpy.full((4, 4), 2))
                document_model.recompute_all()
                # undelete
                document_model.undelete_all(undelete_log)
            # verify state of document
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(1, len(document_model.computations))
            self.assertEqual(1, len(document_model.get_dependent_items(document_model.data_items[0])))
            self.assertEqual(document_model.data_items[1], document_model.get_dependent_items(document_model.data_items[0])[0])
            self.assertEqual(1, len(document_model.get_source_items(document_model.data_items[1])))
            self.assertIn(document_model.data_items[0], document_model.get_source_items(document_model.data_items[1]))
            # recompute, should use the previously started one
            self.assertTrue(numpy.array_equal(numpy.full((4, 4), -1), document_model.data_items[1].data))
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(numpy.full((4, 4), -2), document_model.data_items[1].data))
            # update data, ensure everything connected again
            data_item.set_data(numpy.full((4, 4), 3))
            self.assertTrue(numpy.array_equal(numpy.full((4, 4), -2), document_model.data_items[1].data))
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(numpy.full((4, 4), -3), document_model.data_items[1].data))

    def test_undelete_data_item_with_double_computation(self):
        Symbolic.register_computation_type("negate", self.Negate)
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            # create the data items
            data_item = DataItem.DataItem(numpy.ones((4, 4)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            display_item.add_graphic(crop_region)
            data_item2 = document_model.get_crop_new(display_item, display_item.data_item, crop_region)
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item3)
            # create the computation
            computation = document_model.create_computation()
            computation.source = data_item
            computation.create_input_item("src_xdata", Symbolic.make_item(data_item2, type="xdata"))
            computation.create_output_item("dst", Symbolic.make_item(data_item3))
            computation.processing_id = "negate"
            document_model.append_computation(computation)
            document_model.recompute_all()
            # check results
            self.assertTrue(numpy.array_equal(numpy.full((2, 2), 1), data_item2.data))
            self.assertTrue(numpy.array_equal(numpy.full((2, 2), -1), data_item3.data))
            # remove computation and verify it was removed along with dst data item
            with contextlib.closing(document_model.remove_data_item_with_log(data_item, safe=True)) as undelete_log:
                self.assertEqual(0, len(document_model.data_items))
                self.assertEqual(0, len(document_model.computations))
                # undelete
                document_model.undelete_all(undelete_log)
            document_model.recompute_all()
            # verify state of document
            self.assertEqual(3, len(document_model.data_items))
            self.assertEqual(2, len(document_model.computations))
            self.assertEqual(1, len(document_model.get_dependent_items(document_model.data_items[0])))
            self.assertEqual(document_model.data_items[1], document_model.get_dependent_items(document_model.data_items[0])[0])
            self.assertEqual(1, len(document_model.get_dependent_items(document_model.data_items[1])))
            self.assertEqual(document_model.data_items[2], document_model.get_dependent_items(document_model.data_items[1])[0])
            # now update source data and observe the fun
            document_model.data_items[0].set_data(numpy.full((4, 4), 2))
            document_model.recompute_all()
            # update data, ensure everything connected again
            self.assertTrue(numpy.array_equal(numpy.full((2, 2), 2), document_model.data_items[1].data))
            self.assertTrue(numpy.array_equal(numpy.full((2, 2), -2), document_model.data_items[2].data))

    def test_undelete_connection(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            # create the data items
            data_item1 = DataItem.DataItem(numpy.ones((4, 4)))
            document_model.append_data_item(data_item1)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            display_item1.title = "a"
            data_item2 = DataItem.DataItem(numpy.ones((4, 4)))
            document_model.append_data_item(data_item2)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            display_item2.title = "b"
            connection = Connection.PropertyConnection(display_item1, "title", display_item2, "title", parent=data_item1)
            document_model.append_connection(connection)
            # check assumptions
            self.assertEqual(display_item1.title, display_item2.title)
            display_item1.title = "aa"
            self.assertEqual(display_item1.title, display_item2.title)
            display_item2.title = "bb"
            self.assertEqual(display_item1.title, display_item2.title)
            self.assertEqual(1, len(document_model.connections))
            with contextlib.closing(document_model.remove_data_item_with_log(data_item1, safe=True)) as undelete_log:
                self.assertEqual(0, len(document_model.connections))
                self.assertEqual(1, len(document_model.data_items))
                self.assertEqual(1, len(document_model.display_items))
                # undelete and verify
                document_model.undelete_all(undelete_log)
            # verify
            self.assertEqual(1, len(document_model.connections))
            display_item1 = document_model.display_items[0]
            display_item2 = document_model.display_items[1]
            self.assertEqual(display_item1.title, display_item2.title)
            display_item1.title = "aaa"
            self.assertEqual(display_item1.title, display_item2.title)
            display_item2.title = "bbb"
            self.assertEqual(display_item1.title, display_item2.title)

    def test_undeleted_connection_is_properly_restored_into_persistent_object_context(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            # create the data items
            data_item = DataItem.DataItem(numpy.ones((4, 4, 100)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            pick_data_item = document_model.get_pick_new(display_item, display_item.data_item)
            pick_display_item = document_model.get_display_item_for_data_item(pick_data_item)
            # only even width intervals aligned to pixels are represented exactly by slices
            pick_display_item.graphics[0].interval = (12 / 100, 16 / 100)
            # delete the pick and verify
            with contextlib.closing(document_model.remove_data_item_with_log(pick_data_item, safe=True)) as undelete_log:
                # undelete and verify
                document_model.undelete_all(undelete_log)
            pick_data_item = document_model.data_items[1]
            pick_display_item = document_model.get_display_item_for_data_item(pick_data_item)
            # delete again
            pick_display_item.graphics[0].interval = (56/100, 64/100)
            document_model.remove_data_item(pick_data_item, safe=True)

    def test_undelete_graphic(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            # create the data items
            data_item = DataItem.DataItem(numpy.ones((8, 8)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            line_profile_data_item = document_model.get_line_profile_new(display_item, display_item.data_item)
            self.assertEqual(1, len(document_model.computations))
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(1, len(document_model.display_items[0].graphics))
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(numpy.ones((5, )), line_profile_data_item.data))
            # delete the line profile and verify
            undelete_log = display_item.remove_graphic(display_item.graphics[0], safe=True)
            self.assertEqual(0, len(document_model.computations))
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(0, len(document_model.display_items[0].graphics))
            # undelete and verify
            document_model.undelete_all(undelete_log)
            undelete_log.close()
            line_profile_data_item = document_model.data_items[1]
            self.assertEqual(1, len(document_model.computations))
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(1, len(document_model.display_items[0].graphics))
            # ensure computation works
            self.assertTrue(numpy.array_equal(numpy.ones((5, )), line_profile_data_item.data))
            data_item.set_data(numpy.zeros((8, 8)))
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(numpy.zeros((5, )), line_profile_data_item.data))

    def test_undeleted_graphic_is_properly_restored_into_persistent_object_context(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            # create the data items
            data_item = DataItem.DataItem(numpy.ones((8, 8)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            document_model.get_line_profile_new(display_item, display_item.data_item)
            # delete the graphic and verify
            undelete_log = display_item.remove_graphic(display_item.graphics[0], safe=True)
            # undelete and verify
            document_model.undelete_all(undelete_log)
            undelete_log.close()
            # delete again
            display_item.remove_graphic(display_item.graphics[0], safe=True).close()

    def test_undelete_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            # create the data items
            data_item = DataItem.DataItem(numpy.ones((8, 8)))
            document_model.append_data_item(data_item)
            self.assertEqual(1, len(document_model.data_items))
            # delete the data item and verify
            with contextlib.closing(document_model.remove_data_item_with_log(data_item, safe=True)) as undelete_log:
                self.assertEqual(0, len(document_model.data_items))
                # undelete and verify
                document_model.undelete_all(undelete_log)
            self.assertEqual(1, len(document_model.data_items))
            self.assertTrue(numpy.array_equal(numpy.ones((8, 8)), document_model.data_items[0].data))

    def test_undelete_data_item_with_graphic(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            self.app._set_document_model(document_model)  # required to allow API to find document model
            # create the data items
            data_item = DataItem.DataItem(numpy.ones((8, 8)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            line_profile_data_item = document_model.get_line_profile_new(display_item, display_item.data_item)
            self.assertEqual(1, len(document_model.computations))
            self.assertEqual(2, len(document_model.data_items))
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(numpy.ones((5, )), line_profile_data_item.data))
            # delete the line profile and verify
            with contextlib.closing(document_model.remove_data_item_with_log(line_profile_data_item, safe=True)) as undelete_log:
                self.assertEqual(0, len(document_model.computations))
                self.assertEqual(1, len(document_model.data_items))
                self.assertEqual(0, len(document_model.display_items[0].graphics))
                # undelete and verify
                document_model.undelete_all(undelete_log)
            line_profile_data_item = document_model.data_items[1]
            self.assertEqual(1, len(document_model.computations))
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(1, len(document_model.display_items[0].graphics))
            # ensure computation works
            self.assertTrue(numpy.array_equal(numpy.ones((5, )), line_profile_data_item.data))
            data_item.set_data(numpy.zeros((8, 8)))
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(numpy.zeros((5, )), line_profile_data_item.data))
            # delete the line profile again and verify
            document_model.remove_data_item(line_profile_data_item, safe=True)
            self.assertEqual(0, len(document_model.computations))
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(0, len(document_model.display_items[0].graphics))

    def test_snapshot_has_unique_title(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            snapshot_display_item = document_model.get_display_item_snapshot_new(display_item)
            self.assertNotEqual(display_item.displayed_title, snapshot_display_item.displayed_title)

    def test_snapshot_snapshots_display(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_graphic(Graphics.PointGraphic())
            snapshot_display_item = document_model.get_display_item_snapshot_new(display_item)
            self.assertEqual(1, len(snapshot_display_item.graphics))

    def test_new_display_makes_another_display_item(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            copy_display_item = document_model.get_display_item_copy_new(display_item)
            self.assertIsNot(copy_display_item, display_item)
            self.assertEqual(2, len(document_model.get_display_items_for_data_item(data_item)))

    def test_able_to_make_new_data_item_by_processing_existing_data_item_with_multiple_displays(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            document_model.get_display_item_copy_new(display_item)
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            document_model.get_invert_new(display_item, display_item.data_item)
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(3, len(document_model.display_items))

    def test_delete_display_item_with_missing_data_item_reference(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item1 = DataItem.DataItem(numpy.ones((2, 2)))
                document_model.append_data_item(data_item1)
                data_item2 = DataItem.DataItem(numpy.ones((2, 2)))
                document_model.append_data_item(data_item2)
                display_item = DisplayItem.DisplayItem()
                document_model.append_display_item(display_item)
                display_item.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item1))
                display_item.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item2))
            profile_context.project_properties["display_items"][2]["display_data_channels"][0]["data_item_reference"] = str(uuid.uuid4())
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.remove_display_item(document_model.display_items[-1])

    def test_delete_one_data_item_from_multi_data_item_display(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item1 = DataItem.DataItem(numpy.ones((2,)))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.ones((2,)))
            document_model.append_data_item(data_item2)
            display_item = DisplayItem.DisplayItem()
            document_model.append_display_item(display_item)
            display_item.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item1))
            display_item.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item2))
            document_model.remove_data_item(data_item2)
            self.assertEqual(1, len(display_item.display_data_channels))

    def test_deleting_last_display_item_for_data_item_also_deletes_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            # make two data items and add display for 2nd to first
            # this results in two display items, the first with both data items;
            # the second with just the 2nd data item.
            data_item1 = DataItem.DataItem(numpy.ones((2,)))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.ones((2,)))
            document_model.append_data_item(data_item2)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            display_item1.append_display_data_channel_for_data_item(data_item2)
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            self.assertIn(data_item1, document_model.data_items)
            # remove the first data item from the first display; now the first data item
            # is not displayed anywhere and should be cascade deleted. the correct result
            # should be two display items, both displaying the 2nd data item. the first data
            # item should be removed from the document.
            display_item1.remove_display_data_channel(display_item1.display_data_channels[0]).close()
            self.assertNotIn(data_item1, document_model.data_items)
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(2, len(document_model.get_display_items_for_data_item(data_item2)))

    def test_modified_property_is_updated_when_child_item_changes(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2,)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            graphic = Graphics.PointGraphic()
            display_item.add_graphic(graphic)
            modified = display_item.modified
            time.sleep(0.001)  # windows has a time resolution of 1ms. sleep to avoid duplicate.
            graphic.label = "Fred"
            self.assertGreater(display_item.modified, modified)

    def test_data_item_reference_gets_reconnected_when_reloading(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((2, 2)))
                document_model.append_data_item(data_item)
                document_model._update_data_item_reference("abc", data_item)
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item_reference = document_model.get_data_item_reference("abc")
                self.assertEqual(document_model.data_items[0], data_item_reference.data_item)

    def test_data_item_reference_gets_connected_when_referenced_before_setting(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.get_data_item_reference("abc")
                data_item = DataItem.DataItem(numpy.ones((2, 2)))
                document_model.append_data_item(data_item)
                document_model._update_data_item_reference("abc", data_item)
                data_item_reference = document_model.get_data_item_reference("abc")
                self.assertEqual(document_model.data_items[0], data_item_reference.data_item)

    def test_display_items_with_multiple_data_channels_list_all_sources(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((4, )))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                data_item2 = document_model.get_invert_new(display_item, display_item.data_item)
                display_item2 = document_model.get_display_item_for_data_item(data_item2)
                data_item3 = document_model.get_invert_new(display_item2, display_item2.data_item)
                display_item3 = document_model.get_display_item_for_data_item(data_item3)
                display_item2.append_display_data_channel_for_data_item(data_item3)
                # check sources. display_item2 should not be included in source items for itself
                self.assertEqual([], document_model.get_source_display_items(display_item))
                self.assertEqual([display_item], document_model.get_source_display_items(display_item2))
                self.assertEqual([display_item2], document_model.get_source_display_items(display_item3))
                # check dependents. display_item2 should not be included in source items for itself
                self.assertEqual([display_item2], document_model.get_dependent_display_items(display_item))
                self.assertEqual([display_item3], document_model.get_dependent_display_items(display_item2))
                self.assertEqual([], document_model.get_dependent_display_items(display_item3))

    def test_display_items_with_multiple_data_channels_processing(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((4, )))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                data_item2 = DataItem.DataItem(numpy.ones((4, )))
                document_model.append_data_item(data_item2)
                display_item2 = document_model.get_display_item_for_data_item(data_item2)
                display_item2.append_display_data_channel_for_data_item(data_item)
                inverted_data_item = document_model.get_invert_new(display_item2, data_item)
                # check the data and display_data paths by doing some computations
                document_model.recompute_all()
                self.assertAlmostEqual(-4, float(numpy.sum(inverted_data_item.data)))
                data_item.set_data(numpy.full((4, ), 8))
                document_model.recompute_all()
                self.assertAlmostEqual(-32, float(numpy.sum(inverted_data_item.data)))

    def test_item_variable_is_removed_after_item_is_deleted(self):
        with create_memory_profile_context() as profile_context:
            self.assertEqual(0, len(DocumentModel.MappedItemManager().item_map.keys()))
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                item_uuid = uuid.uuid4()
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32), item_uuid=item_uuid)
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                r_var = document_model.assign_variable_to_display_item(display_item)
                self.assertEqual(1, len(DocumentModel.MappedItemManager().item_map.keys()))
                document_model.remove_data_item(data_item)
                self.assertEqual(0, len(DocumentModel.MappedItemManager().item_map.keys()))

    def test_related_items_changed_event_fires_when_new_display_data_channel_added(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item1 = DataItem.DataItem(numpy.zeros((2, 2)))
            data_item2 = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            line_profile_data_item1 = document_model.get_line_profile_new(display_item1, display_item1.data_item)
            line_profile_display_item1 = document_model.get_display_item_for_data_item(line_profile_data_item1)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            line_profile_data_item2 = document_model.get_line_profile_new(display_item2, display_item2.data_item)
            self.assertEqual([display_item1], document_model.get_source_display_items(line_profile_display_item1))
            related_items_did_change = False

            def related_items_changed(display_item: DisplayItem.DisplayItem,
                                      source_display_items: typing.List[DisplayItem.DisplayItem],
                                      dependent_display_items: typing.List[DisplayItem.DisplayItem]) -> None:
                nonlocal related_items_did_change
                related_items_did_change = True

            with contextlib.closing(document_model.related_items_changed.listen(related_items_changed)):
                line_profile_display_item1.append_display_data_channel_for_data_item(line_profile_data_item2)
                self.assertEqual([display_item1, display_item2], document_model.get_source_display_items(line_profile_display_item1))
                self.assertTrue(related_items_did_change)
                related_items_did_change = False
                line_profile_display_item1.remove_display_data_channel(line_profile_display_item1.display_data_channels[1]).close()
                self.assertEqual([display_item1], document_model.get_source_display_items(line_profile_display_item1))
                self.assertTrue(related_items_did_change)

    # solve problem of where to create new elements (same library), generally shouldn't create data items for now?
    # way to configure display for new data items?
    # splitting complex and reconstructing complex does so efficiently (i.e. one recompute for each change at each step)
    # variable number of inputs, single output
    # user has way to see error output from a failed computation
    # future ability to prepare is not precluded
    # future ability to undo is not precluded
    # naming method, similar to commit
    # provenance, similar to commit
    # check to delete method, similar to commit
    # ability to debounce and sample change messages for improved performance
    # ability to have long running operations
    # api computation can be configured from nionlib and interactive (set input/output objects and values)
    # menu example to toggle an operation on a data item
    # exporting a 'complete' set of data items includes all computations and references.
    # updating set or list of results does not trigger recompute
    # data item computations are migrated to independent computations
    # there exists a way for user to discover library computations, and see which ones are dead and why
    # file vaults (HDF5 w/ multiple data items) includes the library computations.
    # possible to keep an ordered list of results in computation
    # idea of intermediate mode computations - pass results directly to another computation? chain?


if __name__ == '__main__':
    unittest.main()
