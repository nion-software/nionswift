# futures
from __future__ import absolute_import

# standard libraries
import contextlib
import copy
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Storage
from nion.ui import Test


class TestDocumentModelClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_remove_data_items_on_document_model(self):
        cache_name = ":memory:"
        storage_cache = Storage.DbStorageCache(cache_name)
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
        storage_cache = Storage.DbStorageCache(cache_name)
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
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.uint32))
            document_model.append_data_item(data_item)
        # modify data reference to have duplicate
        old_data_key = list(data_reference_handler.data.keys())[0]
        new_data_key = "2000" + old_data_key[4:]
        old_properties_key = list(data_reference_handler.properties.keys())[0]
        new_properties_key = "2000" + old_properties_key[4:]
        data_reference_handler.data[new_data_key] = copy.deepcopy(data_reference_handler.data[old_data_key])
        data_reference_handler.properties[new_properties_key] = copy.deepcopy(data_reference_handler.properties[old_properties_key])
        # reload and verify
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, log_migrations=False)
        with contextlib.closing(document_model):
            self.assertEqual(len(document_model.data_items), len(set([d.uuid for d in document_model.data_items])))
            self.assertEqual(len(document_model.data_items), 1)

if __name__ == '__main__':
    unittest.main()
