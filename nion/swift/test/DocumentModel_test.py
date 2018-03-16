# standard libraries
import contextlib
import copy
import gc
import random
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import Facade
from nion.swift.model import Cache
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import Symbolic
from nion.ui import TestUI
from nion.utils import Recorder


Facade.initialize()


class TestDocumentModelClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_remove_data_items_on_document_model(self):
        cache_name = ":memory:"
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(storage_cache=storage_cache)
        with contextlib.closing(document_model):
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
        cache_name = ":memory:"
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(storage_cache=storage_cache)
        with contextlib.closing(document_model):
            data_item1 = DataItem.DataItem()
            data_item1.title = 'title'
            data_item2 = DataItem.DataItem()
            data_item2.title = 'title'
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            data_group = DataGroup.DataGroup()
            document_model.append_data_group(data_group)
            data_group.append_data_item(data_item1)
            data_group.append_data_item(data_item2)
            self.assertEqual(data_group.counted_data_items[data_item1], 1)
            self.assertEqual(data_group.counted_data_items[data_item2], 1)
            document_model.remove_data_item(data_item1)
            self.assertEqual(data_group.counted_data_items[data_item1], 0)
            self.assertEqual(data_group.counted_data_items[data_item2], 1)

    def test_loading_document_with_duplicated_data_items_ignores_earlier_ones(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.uint32))
            document_model.append_data_item(data_item)
        # modify data reference to have duplicate
        old_data_key = list(memory_persistent_storage_system.data.keys())[0]
        new_data_key = "2000" + old_data_key[4:]
        old_properties_key = list(memory_persistent_storage_system.properties.keys())[0]
        new_properties_key = "2000" + old_properties_key[4:]
        memory_persistent_storage_system.data[new_data_key] = copy.deepcopy(memory_persistent_storage_system.data[old_data_key])
        memory_persistent_storage_system.properties[new_properties_key] = copy.deepcopy(memory_persistent_storage_system.properties[old_properties_key])
        # reload and verify
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            self.assertEqual(len(document_model.data_items), len(set([d.uuid for d in document_model.data_items])))
            self.assertEqual(len(document_model.data_items), 1)

    def test_document_model_releases_data_item(self):
        # test memory usage
        document_model = DocumentModel.DocumentModel()
        import weakref
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(data=numpy.zeros((2, 2)))
            data_item_weak_ref = weakref.ref(data_item)
            document_model.append_data_item(data_item)
            data_item = None
        document_model = None
        gc.collect()
        self.assertIsNone(data_item_weak_ref())

    def test_data_items_without_display_close_nicely(self):
        # see test_flattened_model_with_empty_master_item_closes_properly
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item1 = DataItem.DataItem(numpy.zeros((2, 2)))
            data_item2 = DataItem.DataItem()
            data_item2.remove_display(data_item2.displays[0])
            data_item3 = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)

    def test_processing_line_profile_configures_intervals_connection(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.zeros((8, 8), dtype=numpy.float)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            line_profile_data_item = document_model.get_line_profile_new(data_item)
            self.assertEqual(len(data_item.displays[0].graphics[0].interval_descriptors), 0)
            interval = Graphics.IntervalGraphic()
            interval.interval = 0.3, 0.6
            line_profile_data_item.displays[0].add_graphic(interval)
            self.assertEqual(len(data_item.displays[0].graphics[0].interval_descriptors), 1)
            self.assertEqual(data_item.displays[0].graphics[0].interval_descriptors[0]["interval"], interval.interval)

    def test_processing_pick_configures_in_and_out_regions_and_connection(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = (100 * numpy.random.randn(8, 8, 64)).astype(numpy.int)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            pick_data_item = document_model.get_pick_new(data_item)
            self.assertEqual(len(data_item.displays[0].graphics), 1)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(pick_data_item.data, d[4, 4, :]))
            data_item.displays[0].graphics[0].position = 0, 0
            document_model.recompute_all()
            self.assertFalse(numpy.array_equal(pick_data_item.data, d[4, 4, :]))
            self.assertTrue(numpy.array_equal(pick_data_item.data, d[0, 0, :]))
            self.assertEqual(pick_data_item.displays[0].graphics[0].interval, data_item.displays[0].slice_interval)
            # set up interval to be on pixel boundaries; and only even width intervals will map exactly
            interval1 = 5 / d.shape[-1], 9 / d.shape[-1]
            pick_data_item.displays[0].graphics[0].interval = interval1
            self.assertEqual(pick_data_item.displays[0].graphics[0].interval, data_item.displays[0].slice_interval)
            self.assertEqual(pick_data_item.displays[0].graphics[0].interval, interval1)
            # set up interval to be on pixel boundaries; and only even width intervals will map exactly
            interval2 = 10 / d.shape[-1], 16 / d.shape[-1]
            data_item.displays[0].slice_interval = interval2
            self.assertEqual(pick_data_item.displays[0].graphics[0].interval, data_item.displays[0].slice_interval)
            self.assertEqual(pick_data_item.displays[0].graphics[0].interval, interval2)

    def test_recompute_after_data_item_deleted_does_not_update_data_on_deleted_data_item(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = (100 * numpy.random.randn(4, 4)).astype(numpy.int)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(data_item)
            document_model.remove_data_item(inverted_data_item)
            document_model.recompute_all()

    def test_recompute_after_computation_cleared_does_not_update_data(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = (100 * numpy.random.randn(4, 4)).astype(numpy.int)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(data_item)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(inverted_data_item.data, -d))
            data_item.set_data((100 * numpy.random.randn(4, 4)).astype(numpy.int))
            document_model.set_data_item_computation(inverted_data_item, None)
            self.assertTrue(numpy.array_equal(inverted_data_item.data, -d))
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(inverted_data_item.data, -d))

    def test_data_item_recording(self):
        data_item = DataItem.DataItem(numpy.zeros((16, 16)))
        data_item_recorder = Recorder.Recorder(data_item)
        data_item.displays[0].display_type = "line_plot"
        point_graphic = Graphics.PointGraphic()
        point_graphic.position = 0.2, 0.3
        data_item.displays[0].add_graphic(point_graphic)
        point_graphic.position = 0.21, 0.31
        new_data_item = DataItem.DataItem(numpy.zeros((16, 16)))
        self.assertNotEqual(data_item.displays[0].display_type, new_data_item.displays[0].display_type)
        data_item_recorder.apply(new_data_item)
        self.assertEqual(data_item.displays[0].display_type, new_data_item.displays[0].display_type)
        self.assertEqual(new_data_item.displays[0].graphics[0].position, point_graphic.position)

    def test_creating_r_var_on_library_items(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            composite_item = DataItem.CompositeLibraryItem()
            document_model.append_data_item(composite_item)
            composite_item.append_data_item(data_item)
            data_item_r = document_model.assign_variable_to_library_item(data_item)
            composite_item_r = document_model.assign_variable_to_library_item(composite_item)
            self.assertEqual(data_item_r, "r01")
            self.assertEqual(composite_item_r, "r02")

    def test_transaction_on_composite_display_propagates_to_dependents(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((100, )))
            document_model.append_data_item(data_item)
            composite_item = DataItem.CompositeLibraryItem()
            document_model.append_data_item(composite_item)
            composite_item.append_data_item(data_item)
            composite_item.displays[0].display_type = "line_plot"
            interval = Graphics.IntervalGraphic()
            composite_item.displays[0].add_graphic(interval)
            computed_data_item = DataItem.DataItem(numpy.zeros((100, )))
            document_model.append_data_item(computed_data_item)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
            computation.create_object("interval", document_model.get_object_specifier(interval))
            document_model.set_data_item_computation(computed_data_item, computation)
            self.assertSetEqual(set(document_model.get_dependent_items(data_item)), {computed_data_item})
            self.assertSetEqual(set(document_model.get_dependent_items(interval)), {computed_data_item})
            with document_model.begin_display_transaction(composite_item.displays[0]):
                self.assertTrue(composite_item.in_transaction_state)
                self.assertTrue(computed_data_item.in_transaction_state)
                self.assertFalse(data_item.in_transaction_state)
            self.assertFalse(composite_item.in_transaction_state)
            self.assertFalse(computed_data_item.in_transaction_state)
            self.assertFalse(data_item.in_transaction_state)

    def test_transaction_handles_added_graphic(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((100, )))
            document_model.append_data_item(data_item)
            with document_model.item_transaction(data_item):
                interval = Graphics.IntervalGraphic()
                data_item.displays[0].add_graphic(interval)
            self.assertEqual(0, document_model.transaction_count)

    def test_transaction_handles_removed_graphic(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((100, )))
            interval = Graphics.IntervalGraphic()
            data_item.displays[0].add_graphic(interval)
            document_model.append_data_item(data_item)
            with document_model.item_transaction(data_item):
                data_item.displays[0].remove_graphic(interval)
            self.assertEqual(0, document_model.transaction_count)

    def test_transaction_handles_added_dependent_data_item(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            data_item.displays[0].add_graphic(crop_region)
            document_model.append_data_item(data_item)
            with document_model.item_transaction(data_item):
                data_item_crop = document_model.get_crop_new(data_item, crop_region)
                self.assertTrue(document_model.is_in_transaction_state(data_item_crop))
            self.assertEqual(0, document_model.transaction_count)

    def test_transaction_handles_removed_dependent_data_item(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            data_item.displays[0].add_graphic(crop_region)
            document_model.append_data_item(data_item)
            data_item_crop = document_model.get_crop_new(data_item, crop_region)
            with document_model.item_transaction(data_item):
                document_model.remove_data_item(data_item_crop)
            self.assertEqual(0, document_model.transaction_count)

    def test_transaction_propogates_to_data_structure_referenced_objects(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            data_struct = document_model.create_data_structure()
            data_struct.set_referenced_object("master", data_item)
            document_model.append_data_structure(data_struct)
            with document_model.item_transaction(data_struct):
                self.assertTrue(data_item.in_transaction_state)
            self.assertEqual(0, document_model.transaction_count)

    def test_transaction_propogates_to_data_structure_referenced_objects_added_during_transaction(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            data_struct = document_model.create_data_structure()
            document_model.append_data_structure(data_struct)
            with document_model.item_transaction(data_struct):
                data_struct.set_referenced_object("master", data_item)
                self.assertTrue(data_item.in_transaction_state)
            self.assertEqual(0, document_model.transaction_count)

    def test_transaction_handles_nested_transaction_with_dependent_data_item(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((100, )))
            document_model.append_data_item(data_item)
            with document_model.item_transaction(data_item):
                with document_model.item_transaction(data_item):
                    line_profile_data_item = document_model.get_line_profile_new(data_item)
                    self.assertTrue(document_model.is_in_transaction_state(data_item))
                    self.assertTrue(document_model.is_in_transaction_state(line_profile_data_item))
                self.assertTrue(document_model.is_in_transaction_state(data_item))
                self.assertTrue(document_model.is_in_transaction_state(line_profile_data_item))
            self.assertEqual(0, document_model.transaction_count)

    def test_composite_item_deletes_children_when_deleted(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((100, )))
            document_model.append_data_item(data_item)
            composite_item = DataItem.CompositeLibraryItem()
            document_model.append_data_item(composite_item)
            composite_item.append_data_item(data_item)
            data_item.source = composite_item
            self.assertEqual(len(document_model.data_items), 2)
            document_model.remove_data_item(composite_item)
            self.assertEqual(len(document_model.data_items), 0)

    def test_data_item_with_associated_data_structure_deletes_when_data_item_deleted(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
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
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            data_item.displays[0].add_graphic(crop_region)
            document_model.append_data_item(data_item)
            data_item_crop = document_model.get_crop_new(data_item, crop_region)
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
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.zeros((2, 2), numpy.int)
            d[1, 0] = 1
            data_item = DataItem.DataItem(d)
            graphic = Graphics.PointGraphic()
            data_item.displays[0].add_graphic(graphic)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
            computation.create_result("graphic", document_model.get_object_specifier(graphic))
            computation.processing_id = "find_max"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(graphic.position, (0.5, 0))

    def test_new_computation_into_new_result_graphic(self):
        Symbolic.register_computation_type("find_max", self.FindMax)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.zeros((2, 2), numpy.int)
            d[1, 0] = 1
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
            computation.processing_id = "find_max"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(data_item.displays[0].graphics), 1)
            self.assertEqual(data_item.displays[0].graphics[0].position, (0.5, 0))

    def test_new_computation_into_new_and_then_existing_result_graphic(self):
        Symbolic.register_computation_type("find_max", self.FindMax)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.zeros((2, 2), numpy.int)
            d[1, 0] = 1
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
            computation.processing_id = "find_max"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(data_item.displays[0].graphics), 1)
            self.assertEqual(data_item.displays[0].graphics[0].position, (0.5, 0))
            # change it again
            d[0, 1] = 2
            data_item.set_data(d)
            document_model.recompute_all()
            self.assertEqual(len(data_item.displays[0].graphics), 1)
            self.assertEqual(data_item.displays[0].graphics[0].position, (0, 0.5))

    def test_new_computation_into_new_and_result_graphic_only_evaluates_once(self):
        TestDocumentModelClass.find_max_eval_count = 0
        Symbolic.register_computation_type("find_max", self.FindMax)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.zeros((2, 2), numpy.int)
            d[1, 0] = 1
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
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
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            data_item2 = DataItem.DataItem(numpy.zeros((3, 3), numpy.int))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
            value = computation.create_variable("value", "integral", 3)
            computation.create_result("dst", document_model.get_object_specifier(data_item2, "data_item"))
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
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            data_item2 = DataItem.DataItem(numpy.zeros((3, 3), numpy.int))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            data_structure = document_model.create_data_structure()
            data_structure.set_property_value("value", 3)
            document_model.append_data_structure(data_structure)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
            computation.create_object("data_structure", document_model.get_object_specifier(data_structure))
            computation.create_result("dst", document_model.get_object_specifier(data_item2, "data_item"))
            computation.processing_id = "set_const_struct"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item2.data, numpy.full((8, 8), 3)))
            data_structure.set_property_value("value", 5)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item2.data, numpy.full((8, 8), 5)))

    def test_new_computation_with_data_structure_property(self):
        Symbolic.register_computation_type("set_const", self.SetConst)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            data_item2 = DataItem.DataItem(numpy.zeros((3, 3), numpy.int))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            data_structure = document_model.create_data_structure()
            data_structure.set_property_value("amount", 3)
            document_model.append_data_structure(data_structure)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
            computation.create_input("value", document_model.get_object_specifier(data_structure), property_name="amount")
            computation.create_result("dst", document_model.get_object_specifier(data_item2, "data_item"))
            computation.processing_id = "set_const"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item2.data, numpy.full((8, 8), 3)))
            data_structure.set_property_value("amount", 5)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item2.data, numpy.full((8, 8), 5)))

    def test_computation_creates_dependency_between_data_structure_and_target(self):
        Symbolic.register_computation_type("set_const", self.SetConst)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            data_item2 = DataItem.DataItem(numpy.zeros((3, 3), numpy.int))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            data_structure = document_model.create_data_structure()
            data_structure.set_property_value("amount", 3)
            document_model.append_data_structure(data_structure)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
            computation.create_input("value", document_model.get_object_specifier(data_structure), property_name="amount")
            computation.create_result("dst", document_model.get_object_specifier(data_item2, "data_item"))
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
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
            value = computation.create_variable("value", "boolean", True)
            computation.create_result("graphic")
            computation.processing_id = "optional_graphic"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(data_item.displays[0].graphics), 1)
            value.value = False
            document_model.recompute_all()
            self.assertEqual(len(data_item.displays[0].graphics), 0)
            value.value = True
            document_model.recompute_all()
            self.assertEqual(len(data_item.displays[0].graphics), 1)
        # note: the computation function will remove the graphic which will remove the dependency.
        # it will also set a result on the computation which will also try to remove the dependency.

    def test_new_computation_with_optional_result_updates_dependencies(self):
        Symbolic.register_computation_type("optional_graphic", self.OptionalGraphic)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
            value = computation.create_variable("value", "boolean", True)
            computation.create_result("graphic")
            computation.processing_id = "optional_graphic"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 1)
            self.assertEqual(document_model.get_dependent_items(data_item)[0], data_item.displays[0].graphics[0])
            value.value = False
            document_model.recompute_all()
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 0)
            value.value = True
            document_model.recompute_all()
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 1)
            self.assertEqual(document_model.get_dependent_items(data_item)[0], data_item.displays[0].graphics[0])

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
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
            value = computation.create_variable("value", "integral", 3)
            computation.create_result("graphics", specifiers=[])
            computation.processing_id = "n_graphics"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(data_item.displays[0].graphics), 3)
            value.value = 5
            document_model.recompute_all()
            self.assertEqual(len(data_item.displays[0].graphics), 5)

    def test_new_computation_with_list_result_updates_dependencies(self):
        Symbolic.register_computation_type("n_graphics", self.NGraphics)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
            value = computation.create_variable("value", "integral", 3)
            computation.create_result("graphics", specifiers=[])
            computation.processing_id = "n_graphics"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 3)
            self.assertEqual(set(document_model.get_dependent_items(data_item)), set(data_item.displays[0].graphics))
            value.value = 5
            document_model.recompute_all()
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 5)
            self.assertEqual(set(document_model.get_dependent_items(data_item)), set(data_item.displays[0].graphics))
            value.value = 3
            document_model.recompute_all()
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 3)
            self.assertEqual(set(document_model.get_dependent_items(data_item)), set(data_item.displays[0].graphics))

    def test_new_computation_creates_dependency_when_result_created_during_computation(self):
        Symbolic.register_computation_type("set_const", self.SetConst)
        document_model = DocumentModel.DocumentModel()
        self.app._set_document_model(document_model)  # required to allow API to find document model
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
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
        document_model = DocumentModel.DocumentModel()
        self.app._set_document_model(document_model)  # required to allow API to find document model
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            data_item2 = DataItem.DataItem(numpy.zeros((3, 3), numpy.int))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
            computation.create_result("dst", document_model.get_object_specifier(data_item2, "data_item"))
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
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            data_item2 = DataItem.DataItem(numpy.zeros((3, 3), numpy.int))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
            value = computation.create_variable("value", "integral", 3)
            computation.create_result("dst", document_model.get_object_specifier(data_item2, "data_item"))
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

    def test_new_computation_keeps_computation_until_last_input_deleted(self):
        Symbolic.register_computation_type("add2", self.Add2)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item2 = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            computation = document_model.create_computation()
            computation.create_object("src1", document_model.get_object_specifier(data_item))
            computation.create_object("src2", document_model.get_object_specifier(data_item2))
            computation.create_result("dst", document_model.get_object_specifier(data_item3, "data_item"))
            computation.processing_id = "add2"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(document_model.computations), 1)
            self.assertEqual(len(document_model.data_items), 3)
            document_model.remove_data_item(data_item)
            self.assertEqual(len(computation._inputs), 1)
            self.assertEqual(len(computation._outputs), 0)
            self.assertEqual(len(document_model.computations), 1)
            self.assertEqual(len(document_model.data_items), 1)
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 0)
            self.assertEqual(len(document_model.get_dependent_items(data_item2)), 0)
            self.assertEqual(len(document_model.get_dependent_items(data_item3)), 0)
            document_model.remove_data_item(data_item2)
            self.assertEqual(len(document_model.computations), 0)
            self.assertEqual(len(document_model.data_items), 0)

    def test_new_computation_deletes_computation_when_result_data_item_deleted(self):
        Symbolic.register_computation_type("add2", self.Add2)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item2 = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            computation = document_model.create_computation()
            computation.create_object("src1", document_model.get_object_specifier(data_item))
            computation.create_object("src2", document_model.get_object_specifier(data_item2))
            computation.create_result("dst", document_model.get_object_specifier(data_item3, "data_item"))
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

    def test_new_computation_deleting_computation_deletes_all_results(self):
        Symbolic.register_computation_type("add2", self.Add2)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item2 = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            computation = document_model.create_computation()
            computation.create_object("src1", document_model.get_object_specifier(data_item))
            computation.create_object("src2", document_model.get_object_specifier(data_item2))
            computation.create_result("dst", document_model.get_object_specifier(data_item3, "data_item"))
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
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
            value = computation.create_variable("value", "integral", 3)
            computation.create_result("graphics", specifiers=[])
            computation.processing_id = "n_graphics"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(document_model.computations), 1)
            self.assertEqual(len(document_model.data_items), 1)
            self.assertEqual(len(data_item.displays[0].graphics), 3)
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 3)
            document_model.remove_computation(computation)
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 0)
            self.assertEqual(len(document_model.data_items), 1)
            self.assertEqual(len(document_model.computations), 0)

    def test_new_computation_deleting_result_on_computation_with_multiple_results_deletes_all_results_and_computation(self):
        Symbolic.register_computation_type("n_graphics", self.NGraphics)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
            value = computation.create_variable("value", "integral", 3)
            computation.create_result("graphics", specifiers=[])
            computation.processing_id = "n_graphics"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(document_model.computations), 1)
            self.assertEqual(len(document_model.data_items), 1)
            self.assertEqual(len(data_item.displays[0].graphics), 3)
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 3)
            data_item.displays[0].remove_graphic(data_item.displays[0].graphics[0])
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 0)
            self.assertEqual(len(document_model.data_items), 1)
            self.assertEqual(len(document_model.computations), 0)

    def test_new_computation_deletes_auto_created_result_data_item_when_input_data_item_deleted(self):
        Symbolic.register_computation_type("set_const", self.SetConst)
        document_model = DocumentModel.DocumentModel()
        self.app._set_document_model(document_model)  # required to allow API to find document model
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
            computation.create_variable("value", "integral", 3)
            computation.processing_id = "set_const"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(len(document_model.computations), 1)
            self.assertEqual(len(document_model.data_items), 2)
            document_model.remove_data_item(data_item)
            self.assertEqual(len(document_model.data_items), 0)
            self.assertEqual(len(document_model.computations), 0)

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
        document_model = DocumentModel.DocumentModel()
        self.app._set_document_model(document_model)  # required to allow API to find document model
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            data_item2 = DataItem.DataItem()
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
            computation.create_result("dst", document_model.get_object_specifier(data_item2, "data_item"))
            computation.processing_id = "copy_data"
            document_model.append_computation(computation)
            with self.assertRaises(Exception):
                computation2 = document_model.create_computation()
                computation2.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
                computation2.create_result("dst", document_model.get_object_specifier(data_item2, "data_item"))
                computation2.processing_id = "copy_data"
                document_model.append_computation(computation2)

    def test_new_computation_cannot_result_in_immediate_circular_dependency(self):
        Symbolic.register_computation_type("copy_data", self.CopyData)
        document_model = DocumentModel.DocumentModel()
        self.app._set_document_model(document_model)  # required to allow API to find document model
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            document_model.append_data_item(data_item)
            with self.assertRaises(Exception):
                computation = document_model.create_computation()
                computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
                computation.create_result("dst", document_model.get_object_specifier(data_item, "data_item"))
                computation.processing_id = "copy_data"
                document_model.append_computation(computation)

    def test_new_computation_cannot_result_in_secondary_circular_dependency(self):
        Symbolic.register_computation_type("copy_data", self.CopyData)
        document_model = DocumentModel.DocumentModel()
        self.app._set_document_model(document_model)  # required to allow API to find document model
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            data_item2 = DataItem.DataItem(numpy.zeros((2, 2), numpy.int))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
            computation.create_result("dst", document_model.get_object_specifier(data_item2, "data_item"))
            computation.processing_id = "copy_data"
            document_model.append_computation(computation)
            with self.assertRaises(Exception):
                computation = document_model.create_computation()
                computation.create_object("src", document_model.get_object_specifier(data_item2, "data_item"))
                computation.create_result("dst", document_model.get_object_specifier(data_item, "data_item"))
                computation.processing_id = "copy_data"
                document_model.append_computation(computation)

    def test_new_computation_with_missing_input_does_not_recompute(self):
        TestDocumentModelClass.add2_eval_count = 0
        Symbolic.register_computation_type("add2", self.Add2)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item2 = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            computation = document_model.create_computation()
            computation.create_object("src1", document_model.get_object_specifier(data_item))
            computation.create_object("src2", document_model.get_object_specifier(data_item2))
            computation.create_result("dst", document_model.get_object_specifier(data_item3, "data_item"))
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
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item2 = DataItem.DataItem(numpy.ones((2, 2), numpy.int))  # NOT INITIALLY ADDED TO DOCUMENT
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item3)
            computation = document_model.create_computation()
            computation.create_object("src1", document_model.get_object_specifier(data_item))
            computation.create_object("src2", document_model.get_object_specifier(data_item2))
            computation.create_result("dst", document_model.get_object_specifier(data_item3, "data_item"))
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
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item3)
            computation = document_model.create_computation()
            computation.create_object("src1", document_model.get_object_specifier(data_item))
            # computation.create_object("src2")
            computation.create_result("dst", document_model.get_object_specifier(data_item3, "data_item"))
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
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item)
            # document_model.append_data_item(data_item3)  # purposely not added
            computation = document_model.create_computation()
            computation.create_object("src_xdata", document_model.get_object_specifier(data_item, "xdata"))
            computation.create_result("dst", document_model.get_object_specifier(data_item3, "data_item"))
            computation.processing_id = "pass_thru"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(1, len(document_model.data_items))

    def test_new_computation_with_missing_input_which_subsequently_appears_does_evaluate(self):
        Symbolic.register_computation_type("pass_thru", self.PassThru)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item3 = DataItem.DataItem()
            # document_model.append_data_item(data_item)  # purposely not added
            document_model.append_data_item(data_item3)
            computation = document_model.create_computation()
            computation.create_object("src_xdata", document_model.get_object_specifier(data_item, "xdata"))
            computation.create_result("dst", document_model.get_object_specifier(data_item3, "data_item"))
            computation.processing_id = "pass_thru"
            document_model.append_computation(computation)
            self.assertFalse(computation.is_resolved)
            document_model.append_data_item(data_item)  # computation should become valid
            self.assertTrue(computation.is_resolved)

    def test_new_computation_with_missing_output_which_subsequently_appears_does_evaluate(self):
        Symbolic.register_computation_type("pass_thru", self.PassThru)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item)
            # document_model.append_data_item(data_item3)  # purposely not added
            computation = document_model.create_computation()
            computation.create_object("src_xdata", document_model.get_object_specifier(data_item, "xdata"))
            computation.create_result("dst", document_model.get_object_specifier(data_item3, "data_item"))
            computation.processing_id = "pass_thru"
            document_model.append_computation(computation)
            self.assertFalse(computation.is_resolved)
            document_model.append_data_item(data_item3)  # computation should become valid
            self.assertTrue(computation.is_resolved)

    def test_new_computation_with_missing_data_struct_input_which_subsequently_appears_does_evaluate(self):
        Symbolic.register_computation_type("set_const_struct", self.SetConstDataStruct)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            data_item2 = DataItem.DataItem(numpy.zeros((3, 3), numpy.int))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            data_structure = document_model.create_data_structure()
            data_structure.set_property_value("value", 3)
            # document_model.append_data_structure(data_structure)  # purposely not added
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
            computation.create_object("data_structure", document_model.get_object_specifier(data_structure))
            computation.create_result("dst", document_model.get_object_specifier(data_item2, "data_item"))
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
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            data_item2 = DataItem.DataItem(numpy.zeros((3, 3), numpy.int))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            graphic = Graphics.PointGraphic()
            # data_item.displays[0].add_graphic(graphic)  # purposely not added
            computation = document_model.create_computation()
            computation.create_object("src", document_model.get_object_specifier(data_item, "data_item"))
            computation.create_object("graphic", document_model.get_object_specifier(graphic))
            computation.create_result("dst", document_model.get_object_specifier(data_item2, "data_item"))
            computation.processing_id = "set_const_graphic"
            document_model.append_computation(computation)
            self.assertFalse(computation.is_resolved)
            data_item.displays[0].add_graphic(graphic)  # computation should become valid
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
        document_model = DocumentModel.DocumentModel()
        self.app._set_document_model(document_model)  # required to allow API to find document model
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            graphic = Graphics.RectangleGraphic()
            data_item.displays[0].add_graphic(graphic)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation()
            computation.create_object("rect", document_model.get_object_specifier(graphic))
            computation.processing_id = "genzero"
            document_model.append_computation(computation)
            document_model.recompute_all()
            target_data_item = document_model.data_items[1]
            self.assertEqual(document_model.get_dependent_items(graphic)[0], target_data_item)
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 0)
            self.assertEqual(len(document_model.get_dependent_items(target_data_item)), 0)
            self.assertEqual(document_model.get_source_items(target_data_item)[0], graphic)
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
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.random.randn(12, 12))
            data_item2 = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation()
            computation.create_object("src_xdata", document_model.get_object_specifier(data_item, "xdata"))
            computation.create_result("dst", document_model.get_object_specifier(data_item2, "data_item"))
            computation.processing_id = "crop_half"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item2.data, data_item.data[3:9, 3:9]))
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 1)
            self.assertEqual(document_model.get_dependent_items(data_item)[0], data_item2)
            self.assertEqual(len(document_model.get_source_items(data_item2)), 1)
            self.assertEqual(document_model.get_source_items(data_item2)[0], data_item)

    def test_computation_can_depend_on_display_xdata(self):
        Symbolic.register_computation_type("crop_half", self.CropHalf)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.random.randn(12, 12, 4))
            data_item.displays[0].slice_center = 2
            data_item.displays[0].slice_width = 1
            data_item2 = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation()
            computation.create_object("src_xdata", document_model.get_object_specifier(data_item, "display_xdata"))
            computation.create_result("dst", document_model.get_object_specifier(data_item2, "data_item"))
            computation.processing_id = "crop_half"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item2.data, data_item.data[3:9, 3:9, 2]))
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 1)
            self.assertEqual(document_model.get_dependent_items(data_item)[0], data_item2)
            self.assertEqual(len(document_model.get_source_items(data_item2)), 1)
            self.assertEqual(document_model.get_source_items(data_item2)[0], data_item)

    def test_computation_can_depend_on_cropped_xdata(self):
        Symbolic.register_computation_type("crop_half", self.CropHalf)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.random.randn(24, 24))
            data_item2 = DataItem.DataItem(numpy.zeros((2, 2)))
            graphic = Graphics.RectangleGraphic()
            graphic.bounds = (0, 0), (0.5, 0.5)
            data_item.displays[0].add_graphic(graphic)
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation()
            computation.create_object("src_xdata", document_model.get_object_specifier(data_item, "cropped_xdata"), secondary_specifier=document_model.get_object_specifier(graphic))
            computation.create_result("dst", document_model.get_object_specifier(data_item2, "data_item"))
            computation.processing_id = "crop_half"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item2.data, data_item.data[3:9, 3:9]))
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 1)
            self.assertEqual(document_model.get_dependent_items(data_item)[0], data_item2)
            self.assertEqual(len(document_model.get_dependent_items(graphic)), 1)
            self.assertEqual(document_model.get_dependent_items(graphic)[0], data_item2)
            self.assertEqual(len(document_model.get_source_items(data_item2)), 2)
            self.assertIn(graphic, document_model.get_source_items(data_item2))
            self.assertIn(data_item, document_model.get_source_items(data_item2))

    def test_computation_can_depend_on_cropped_display_xdata(self):
        Symbolic.register_computation_type("crop_half", self.CropHalf)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.random.randn(24, 24, 4))
            data_item.displays[0].slice_center = 2
            data_item.displays[0].slice_width = 1
            data_item2 = DataItem.DataItem(numpy.zeros((2, 2)))
            graphic = Graphics.RectangleGraphic()
            graphic.bounds = (0, 0), (0.5, 0.5)
            data_item.displays[0].add_graphic(graphic)
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation()
            computation.create_object("src_xdata", document_model.get_object_specifier(data_item, "cropped_display_xdata"), secondary_specifier=document_model.get_object_specifier(graphic))
            computation.create_result("dst", document_model.get_object_specifier(data_item2, "data_item"))
            computation.processing_id = "crop_half"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item2.data, data_item.data[3:9, 3:9, 2]))
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 1)
            self.assertEqual(document_model.get_dependent_items(data_item)[0], data_item2)
            self.assertEqual(len(document_model.get_dependent_items(graphic)), 1)
            self.assertEqual(document_model.get_dependent_items(graphic)[0], data_item2)
            self.assertEqual(len(document_model.get_source_items(data_item2)), 2)
            self.assertIn(graphic, document_model.get_source_items(data_item2))
            self.assertIn(data_item, document_model.get_source_items(data_item2))

    def test_computation_can_depend_on_filter_xdata(self):
        Symbolic.register_computation_type("pass_thru", self.PassThru)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.full((20, 20), 5))
            data_item2 = DataItem.DataItem(numpy.zeros((2, 2)))
            graphic = Graphics.RingGraphic()
            graphic.radius_1 = 0.2
            graphic.radius_2 = 1.0
            data_item.displays[0].add_graphic(graphic)
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation()
            computation.create_object("src_xdata", document_model.get_object_specifier(data_item, "filter_xdata"))
            computation.create_result("dst", document_model.get_object_specifier(data_item2, "data_item"))
            computation.processing_id = "pass_thru"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(data_item2.xdata.dimensional_shape, (20, 20))
            self.assertEqual(numpy.amin(data_item2.data), 0)
            self.assertEqual(numpy.amax(data_item2.data), 1)
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 1)
            self.assertEqual(document_model.get_dependent_items(data_item)[0], data_item2)
            self.assertEqual(len(document_model.get_dependent_items(graphic)), 1)
            self.assertEqual(document_model.get_dependent_items(graphic)[0], data_item2)
            self.assertEqual(len(document_model.get_source_items(data_item2)), 2)
            self.assertIn(graphic, document_model.get_source_items(data_item2))
            self.assertIn(data_item, document_model.get_source_items(data_item2))

    def test_computation_can_depend_on_filtered_xdata(self):
        Symbolic.register_computation_type("pass_thru", self.PassThru)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.full((20, 20), 5, dtype=numpy.complex128))
            data_item2 = DataItem.DataItem(numpy.zeros((2, 2)))
            graphic = Graphics.RingGraphic()
            graphic.radius_1 = 0.2
            graphic.radius_2 = 1.0
            data_item.displays[0].add_graphic(graphic)
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation()
            computation.create_object("src_xdata", document_model.get_object_specifier(data_item, "filtered_xdata"))
            computation.create_result("dst", document_model.get_object_specifier(data_item2, "data_item"))
            computation.processing_id = "pass_thru"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(data_item2.xdata.dimensional_shape, (20, 20))
            self.assertEqual(numpy.amin(data_item2.data), 0)
            self.assertEqual(numpy.amax(data_item2.data), 5)
            self.assertEqual(len(document_model.get_dependent_items(data_item)), 1)
            self.assertEqual(document_model.get_dependent_items(data_item)[0], data_item2)
            self.assertEqual(len(document_model.get_dependent_items(graphic)), 1)
            self.assertEqual(document_model.get_dependent_items(graphic)[0], data_item2)
            self.assertEqual(len(document_model.get_source_items(data_item2)), 2)
            self.assertIn(graphic, document_model.get_source_items(data_item2))
            self.assertIn(data_item, document_model.get_source_items(data_item2))

    def test_computation_sequence_evaluates(self):
        Symbolic.register_computation_type("pass_thru", self.PassThru)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item1 = DataItem.DataItem(numpy.zeros((2, 2)))
            data_item2 = DataItem.DataItem()
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            computation1 = document_model.create_computation()
            computation1.create_object("src_xdata", document_model.get_object_specifier(data_item1, "xdata"))
            computation1.create_result("dst", document_model.get_object_specifier(data_item2, "data_item"))
            computation1.processing_id = "pass_thru"
            document_model.append_computation(computation1)
            computation2 = document_model.create_computation()
            computation2.create_object("src_xdata", document_model.get_object_specifier(data_item2, "xdata"))
            computation2.create_result("dst", document_model.get_object_specifier(data_item3, "data_item"))
            computation2.processing_id = "pass_thru"
            document_model.append_computation(computation2)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item1.data, data_item2.data))
            self.assertTrue(numpy.array_equal(data_item1.data, data_item3.data))

    def test_computation_deletes_when_source_deletes(self):
        Symbolic.register_computation_type("pass_thru", self.PassThru)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item1 = DataItem.DataItem(numpy.zeros((2, 2)))
            data_item2 = DataItem.DataItem()
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            computation = document_model.create_computation()
            computation.source = data_item3
            computation.create_object("src_xdata", document_model.get_object_specifier(data_item1, "xdata"))
            computation.create_result("dst", document_model.get_object_specifier(data_item2, "data_item"))
            computation.processing_id = "pass_thru"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertEqual(1, len(document_model.computations))
            document_model.remove_data_item(data_item3)
            self.assertEqual(0, len(document_model.computations))

    def test_computation_deletes_when_triggered_by_both_inputs_and_source_deletion(self):
        Symbolic.register_computation_type("pass_thru", self.PassThru)
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item1 = DataItem.DataItem(numpy.zeros((2, 2)))
            data_item2 = DataItem.DataItem()
            data_item3 = DataItem.DataItem()
            data_item3.source = data_item2
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            computation = document_model.create_computation()
            computation.source = data_item3
            computation.create_object("src_xdata", document_model.get_object_specifier(data_item1, "xdata"))
            computation.create_result("dst", document_model.get_object_specifier(data_item2, "data_item"))
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

    def test_new_computation_with_missing_processor_fails_gracefully(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.int))
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item3)
            computation = document_model.create_computation()
            computation.create_object("src1", document_model.get_object_specifier(data_item))
            computation.create_result("dst", document_model.get_object_specifier(data_item3, "data_item"))
            computation.processing_id = "nothing"
            document_model.append_computation(computation)
            document_model.recompute_all()
            self.assertTrue(computation.error_text.startswith("Missing computation"))

    def test_undelete_data_structure(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_structure = document_model.create_data_structure()
            data_structure.set_property_value("amount", 1)
            document_model.append_data_structure(data_structure)
            data_structure = document_model.create_data_structure()
            data_structure.set_property_value("amount", 2)
            document_model.append_data_structure(data_structure)
            data_structure = document_model.create_data_structure()
            data_structure.set_property_value("amount", 3)
            document_model.append_data_structure(data_structure)
            undelete_log = document_model.remove_data_structure(document_model.data_structures[1])
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
        document_model = DocumentModel.DocumentModel()
        self.app._set_document_model(document_model)  # required to allow API to find document model
        with contextlib.closing(document_model):
            # create the data items
            data_item = DataItem.DataItem(numpy.ones((4, 4)))
            document_model.append_data_item(data_item)
            data_item2 = DataItem.DataItem()
            document_model.append_data_item(data_item2)
            # create the computation
            computation = document_model.create_computation()
            computation.source = data_item
            computation.create_object("src_xdata", document_model.get_object_specifier(data_item, "xdata"))
            computation.create_result("dst", document_model.get_object_specifier(data_item2, "data_item"))
            computation.processing_id = "negate"
            document_model.append_computation(computation)
            document_model.recompute_all()
            # check results
            self.assertTrue(numpy.array_equal(numpy.full((4, 4), -1), data_item2.data))
            # remove computation and verify it was removed along with dst data item
            undelete_log = document_model.remove_computation(computation, safe=True)
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
            self.assertEqual(document_model.data_items[0], document_model.get_source_items(document_model.data_items[1])[0])
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
        document_model = DocumentModel.DocumentModel()
        self.app._set_document_model(document_model)  # required to allow API to find document model
        with contextlib.closing(document_model):
            # create the data items
            data_item = DataItem.DataItem(numpy.ones((4, 4)))
            document_model.append_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            data_item.displays[0].add_graphic(crop_region)
            data_item2 = document_model.get_crop_new(data_item, crop_region)
            data_item3 = DataItem.DataItem()
            document_model.append_data_item(data_item3)
            # create the computation
            computation = document_model.create_computation()
            computation.source = data_item
            computation.create_object("src_xdata", document_model.get_object_specifier(data_item2, "xdata"))
            computation.create_result("dst", document_model.get_object_specifier(data_item3, "data_item"))
            computation.processing_id = "negate"
            document_model.append_computation(computation)
            document_model.recompute_all()
            # check results
            self.assertTrue(numpy.array_equal(numpy.full((2, 2), 1), data_item2.data))
            self.assertTrue(numpy.array_equal(numpy.full((2, 2), -1), data_item3.data))
            # remove computation and verify it was removed along with dst data item
            undelete_log = document_model.remove_data_item(data_item, safe=True)
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
        document_model = DocumentModel.DocumentModel()
        self.app._set_document_model(document_model)  # required to allow API to find document model
        with contextlib.closing(document_model):
            # create the data items
            data_item = DataItem.DataItem(numpy.ones((4, 4, 100)))
            document_model.append_data_item(data_item)
            pick_data_item = document_model.get_pick_new(data_item)
            self.assertEqual(1, len(document_model.connections))
            self.assertEqual(1, len(document_model.computations))
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(pick_data_item.displays[0].graphics[0].interval, data_item.displays[0].slice_interval)
            # only even width intervals aligned to pixels are represented exactly by slices
            pick_data_item.displays[0].graphics[0].interval = (12/100, 16/100)
            self.assertEqual(pick_data_item.displays[0].graphics[0].interval, data_item.displays[0].slice_interval)
            # delete the pick and verify
            undelete_log = document_model.remove_data_item(pick_data_item, safe=True)
            self.assertEqual(0, len(document_model.connections))
            self.assertEqual(0, len(document_model.computations))
            self.assertEqual(1, len(document_model.data_items))
            # undelete and verify
            document_model.undelete_all(undelete_log)
            pick_data_item = document_model.data_items[1]
            self.assertEqual(1, len(document_model.connections))
            self.assertEqual(1, len(document_model.computations))
            self.assertEqual(2, len(document_model.data_items))
            # ensure connection works
            pick_data_item.displays[0].graphics[0].interval = (56/100, 64/100)
            self.assertEqual(pick_data_item.displays[0].graphics[0].interval, data_item.displays[0].slice_interval)

    def test_undeleted_connection_is_properly_restored_into_persistent_object_context(self):
        document_model = DocumentModel.DocumentModel()
        self.app._set_document_model(document_model)  # required to allow API to find document model
        with contextlib.closing(document_model):
            # create the data items
            data_item = DataItem.DataItem(numpy.ones((4, 4, 100)))
            document_model.append_data_item(data_item)
            pick_data_item = document_model.get_pick_new(data_item)
            # only even width intervals aligned to pixels are represented exactly by slices
            pick_data_item.displays[0].graphics[0].interval = (12/100, 16/100)
            # delete the pick and verify
            undelete_log = document_model.remove_data_item(pick_data_item, safe=True)
            # undelete and verify
            document_model.undelete_all(undelete_log)
            pick_data_item = document_model.data_items[1]
            # delete again
            pick_data_item.displays[0].graphics[0].interval = (56/100, 64/100)
            document_model.remove_data_item(pick_data_item, safe=True)

    def test_undelete_graphic(self):
        document_model = DocumentModel.DocumentModel()
        self.app._set_document_model(document_model)  # required to allow API to find document model
        with contextlib.closing(document_model):
            # create the data items
            data_item = DataItem.DataItem(numpy.ones((8, 8)))
            document_model.append_data_item(data_item)
            line_profile_data_item = document_model.get_line_profile_new(data_item)
            self.assertEqual(1, len(document_model.connections))
            self.assertEqual(1, len(document_model.computations))
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(1, len(document_model.data_items[0].displays[0].graphics))
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(numpy.ones((5, )), line_profile_data_item.data))
            # delete the line profile and verify
            undelete_log = data_item.displays[0].remove_graphic(data_item.displays[0].graphics[0], safe=True)
            self.assertEqual(0, len(document_model.connections))
            self.assertEqual(0, len(document_model.computations))
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(0, len(document_model.data_items[0].displays[0].graphics))
            # undelete and verify
            document_model.undelete_all(undelete_log)
            line_profile_data_item = document_model.data_items[1]
            self.assertEqual(1, len(document_model.connections))
            self.assertEqual(1, len(document_model.computations))
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(1, len(document_model.data_items[0].displays[0].graphics))
            # ensure computation works
            self.assertTrue(numpy.array_equal(numpy.ones((5, )), line_profile_data_item.data))
            data_item.set_data(numpy.zeros((8, 8)))
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(numpy.zeros((5, )), line_profile_data_item.data))

    def test_undeleted_graphic_is_properly_restored_into_persistent_object_context(self):
        document_model = DocumentModel.DocumentModel()
        self.app._set_document_model(document_model)  # required to allow API to find document model
        with contextlib.closing(document_model):
            # create the data items
            data_item = DataItem.DataItem(numpy.ones((8, 8)))
            document_model.append_data_item(data_item)
            line_profile_data_item = document_model.get_line_profile_new(data_item)
            # delete the graphic and verify
            undelete_log = data_item.displays[0].remove_graphic(data_item.displays[0].graphics[0], safe=True)
            # undelete and verify
            document_model.undelete_all(undelete_log)
            # delete again
            data_item.displays[0].remove_graphic(data_item.displays[0].graphics[0], safe=True)

    def test_undelete_data_item(self):
        document_model = DocumentModel.DocumentModel()
        self.app._set_document_model(document_model)  # required to allow API to find document model
        with contextlib.closing(document_model):
            # create the data items
            data_item = DataItem.DataItem(numpy.ones((8, 8)))
            document_model.append_data_item(data_item)
            self.assertEqual(1, len(document_model.data_items))
            # delete the data item and verify
            undelete_log = document_model.remove_data_item(data_item, safe=True)
            self.assertEqual(0, len(document_model.data_items))
            # undelete and verify
            document_model.undelete_all(undelete_log)
            self.assertEqual(1, len(document_model.data_items))
            self.assertTrue(numpy.array_equal(numpy.ones((8, 8)), document_model.data_items[0].data))

    def test_undelete_data_item_with_connection_and_graphic(self):
        document_model = DocumentModel.DocumentModel()
        self.app._set_document_model(document_model)  # required to allow API to find document model
        with contextlib.closing(document_model):
            # create the data items
            data_item = DataItem.DataItem(numpy.ones((8, 8)))
            document_model.append_data_item(data_item)
            line_profile_data_item = document_model.get_line_profile_new(data_item)
            self.assertEqual(1, len(document_model.connections))
            self.assertEqual(1, len(document_model.computations))
            self.assertEqual(2, len(document_model.data_items))
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(numpy.ones((5, )), line_profile_data_item.data))
            # delete the line profile and verify
            undelete_log = document_model.remove_data_item(line_profile_data_item, safe=True)
            self.assertEqual(0, len(document_model.connections))
            self.assertEqual(0, len(document_model.computations))
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(0, len(document_model.data_items[0].displays[0].graphics))
            # undelete and verify
            document_model.undelete_all(undelete_log)
            line_profile_data_item = document_model.data_items[1]
            self.assertEqual(1, len(document_model.connections))
            self.assertEqual(1, len(document_model.computations))
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(1, len(document_model.data_items[0].displays[0].graphics))
            # ensure computation works
            self.assertTrue(numpy.array_equal(numpy.ones((5, )), line_profile_data_item.data))
            data_item.set_data(numpy.zeros((8, 8)))
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(numpy.zeros((5, )), line_profile_data_item.data))
            # delete the line profile again and verify
            undelete_log = document_model.remove_data_item(line_profile_data_item, safe=True)
            self.assertEqual(0, len(document_model.connections))
            self.assertEqual(0, len(document_model.computations))
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(0, len(document_model.data_items[0].displays[0].graphics))

    def test_undelete_composite_item(self):
        document_model = DocumentModel.DocumentModel()
        self.app._set_document_model(document_model)  # required to allow API to find document model
        with contextlib.closing(document_model):
            # create the data items
            data_item1 = DataItem.DataItem(numpy.ones((8, 8)))
            data_item2 = DataItem.DataItem(numpy.ones((8, 8)))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            composite_item = DataItem.CompositeLibraryItem()
            document_model.append_data_item(composite_item)
            composite_item.append_data_item(data_item1)
            composite_item.append_data_item(data_item2)
            self.assertEqual(3, len(document_model.data_items))
            self.assertEqual(2, len(document_model.data_items[2].data_items))
            # delete the data item and verify
            undelete_log = document_model.remove_data_item(composite_item, safe=True)
            self.assertEqual(2, len(document_model.data_items))
            # undelete and verify
            document_model.undelete_all(undelete_log)
            self.assertEqual(3, len(document_model.data_items))
            self.assertEqual(2, len(document_model.data_items[2].data_items))

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
