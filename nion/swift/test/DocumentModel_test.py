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
        document_model = DocumentModel.DocumentModel(persistent_storage_systems=[memory_persistent_storage_system])
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
        document_model = DocumentModel.DocumentModel(persistent_storage_systems=[memory_persistent_storage_system], log_migrations=False)
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
            interval1 = 5 / d.shape[-1], 8 / d.shape[-1]
            pick_data_item.displays[0].graphics[0].interval = interval1
            self.assertEqual(pick_data_item.displays[0].graphics[0].interval, data_item.displays[0].slice_interval)
            self.assertEqual(pick_data_item.displays[0].graphics[0].interval, interval1)
            interval2 = 10 / d.shape[-1], 15 / d.shape[-1]
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

    def test_recompute_twice_before_periodic_uses_final_data(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.zeros((2, 2), numpy.int)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata + x"))
            computation.create_object("a", document_model.get_object_specifier(data_item))
            x = computation.create_variable("x", value_type="integral", value=5)
            computed_data_item = DataItem.DataItem(d)
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            document_model.recompute_all(merge=False)
            x.value = 10
            document_model.recompute_all(merge=False)
            document_model.perform_data_item_merges()
            self.assertTrue(numpy.array_equal(computed_data_item.data, d + 10))

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

    find_max_eval_count = 0

    def __find_max(self, api, src):
        d = src.data
        max_pos = list(numpy.unravel_index(numpy.argmax(d), d.shape))
        max_pos = max_pos[0] / d.shape[0], max_pos[1] / d.shape[1]

        def commit(api, computation):
            graphic = computation.get_result("graphic", None)
            if not graphic:
                graphic = src.add_point_region(*max_pos)
                computation.set_result("graphic", graphic)
            graphic.position = max_pos
            self.find_max_eval_count += 1

        return commit

    def test_new_computation_into_existing_result_graphic(self):
        Symbolic.register_computation_type("find_max", {"inputs": [{"src": "data_item"}]}, self.__find_max)
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
        Symbolic.register_computation_type("find_max", {"inputs": [{"src": "data_item"}]}, self.__find_max)
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
        Symbolic.register_computation_type("find_max", {"inputs": [{"src": "data_item"}]}, self.__find_max)
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
        self.find_max_eval_count = 0
        Symbolic.register_computation_type("find_max", {"inputs": [{"src": "data_item"}]}, self.__find_max)
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
            self.assertEqual(self.find_max_eval_count, 1)
            document_model.recompute_all()
            self.assertEqual(self.find_max_eval_count, 1)

    def __set_const(self, api, src, value):
        new_data = numpy.full(src.data.shape, value)

        def commit(api, computation):
            dst_data_item = computation.get_result("dst")
            dst_data_item.data = new_data

        return commit

    def test_new_computation_with_variable(self):
        Symbolic.register_computation_type("set_const", {"inputs": [{"src": "data_item"}]}, self.__set_const)
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

    def __optional_graphic(self, api, src, value):
        def commit(api, computation):
            graphic = computation.get_result("graphic", None)
            if not value and graphic:
                src.remove_region(graphic)
                computation.set_result("graphic", None)
            elif value and not graphic:
                graphic = src.add_point_region(0.5, 0.5)
                computation.set_result("graphic", graphic)
        return commit

    def test_new_computation_with_optional_result(self):
        Symbolic.register_computation_type("optional_graphic", {}, self.__optional_graphic)
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

    def __n_graphics(self, api, src, value):
        def commit(api, computation):
            graphics = computation.get_result("graphics")
            while len(graphics) < value:
                graphic = src.add_point_region(0.5, 0.5)
                graphics.append(graphic)
            while len(graphics) > value:
                src.remove_region(graphics.pop())
            computation.set_result("graphics", graphics)
        return commit

    def test_new_computation_with_list_result(self):
        Symbolic.register_computation_type("n_graphics", {"inputs": [{"src": "data_item"}]}, self.__n_graphics)
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

    # computation cascade deletes when result marked for cascade delete is removed
    # computation cascade deletes when input marked for cascade delete is removed
    # loading computation with missing inputs does not recompute
    # computation with missing input does not recompute
    # successfully loading missing input triggers a recompute
    # removing result object from library automatically zeroes computation result
    # splitting complex and reconstructing complex does so efficiently
    # variable number of inputs, single output
    # test dependencies when result created inside computation
    # api computation can be configured from nionlib and interactive (set input/output objects and values)
    # menu example to toggle an operation on a data item
    # exporting a 'complete' set of data items includes all computations and references.
    # updating set or list of results does not trigger recompute
    # data item computations are migrated to independent computations
    # way to configure display for new data items?
    # there exists a way for user to discover library computations, and see which ones are dead and why
    # ability to add custom objects to library and depend on them and update them
    # file vaults (HDF5 w/ multiple data items) includes the library computations.
    # possible to keep an ordered list of results in computation


if __name__ == '__main__':
    unittest.main()
