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
from nion.swift.model import Cache
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.ui import TestUI


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
        memory_persistent_storage_system = DocumentModel.MemoryPersistentStorageSystem()
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
            self.assertEqual(len(data_item.maybe_data_source.displays[0].graphics[0].interval_descriptors), 0)
            interval = Graphics.IntervalGraphic()
            interval.interval = 0.3, 0.6
            line_profile_data_item.maybe_data_source.displays[0].add_graphic(interval)
            self.assertEqual(len(data_item.maybe_data_source.displays[0].graphics[0].interval_descriptors), 1)
            self.assertEqual(data_item.maybe_data_source.displays[0].graphics[0].interval_descriptors[0]["interval"], interval.interval)

    def test_processing_pick_configures_in_and_out_regions_and_connection(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.random.rand(64, 8, 8)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            pick_data_item = document_model.get_pick_new(data_item)
            self.assertEqual(len(data_item.maybe_data_source.displays[0].graphics), 1)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(pick_data_item.maybe_data_source.data, d[:, 4, 4]))
            data_item.maybe_data_source.displays[0].graphics[0].position = 0, 0
            document_model.recompute_all()
            self.assertFalse(numpy.array_equal(pick_data_item.maybe_data_source.data, d[:, 4, 4]))
            self.assertTrue(numpy.array_equal(pick_data_item.maybe_data_source.data, d[:, 0, 0]))
            self.assertEqual(pick_data_item.maybe_data_source.displays[0].graphics[0].interval, data_item.maybe_data_source.displays[0].slice_interval)
            interval1 = 5 / d.shape[0], 8 / d.shape[0]
            pick_data_item.maybe_data_source.displays[0].graphics[0].interval = interval1
            self.assertEqual(pick_data_item.maybe_data_source.displays[0].graphics[0].interval, data_item.maybe_data_source.displays[0].slice_interval)
            self.assertEqual(pick_data_item.maybe_data_source.displays[0].graphics[0].interval, interval1)
            interval2 = 10 / d.shape[0], 15 / d.shape[0]
            data_item.maybe_data_source.displays[0].slice_interval = interval2
            self.assertEqual(pick_data_item.maybe_data_source.displays[0].graphics[0].interval, data_item.maybe_data_source.displays[0].slice_interval)
            self.assertEqual(pick_data_item.maybe_data_source.displays[0].graphics[0].interval, interval2)

if __name__ == '__main__':
    unittest.main()
