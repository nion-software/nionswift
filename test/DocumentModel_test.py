# standard libraries
import logging
import unittest

# third party libraries
# None

# local libraries
from nion.swift import Application
from nion.swift import DataGroup
from nion.swift import DataItem
from nion.swift import DocumentModel
from nion.swift import Storage
from nion.ui import Test


class TestDocumentModelClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_counted_data_items_updated_when_adding_and_removing_on_document_model(self):
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        with document_model.ref():
            data_item1 = DataItem.DataItem()
            data_item1.title = 'title'
            data_item2 = DataItem.DataItem()
            data_item2.title = 'title'
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            self.assertEqual(document_model.counted_data_items[data_item1], 1)
            self.assertEqual(document_model.counted_data_items[data_item2], 1)
            document_model.remove_data_item(data_item1)
            self.assertEqual(document_model.counted_data_items[data_item1], 0)
            self.assertEqual(document_model.counted_data_items[data_item2], 1)

    def test_removing_data_item_should_remove_from_groups_too(self):
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        with document_model.ref():
            data_item1 = DataItem.DataItem()
            data_item1.title = 'title'
            data_item2 = DataItem.DataItem()
            data_item2.title = 'title'
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            data_group = DataGroup.DataGroup()
            document_model.data_groups.append(data_group)
            data_group.append_data_item(data_item1)
            data_group.append_data_item(data_item2)
            self.assertEqual(data_group.counted_data_items[data_item1], 1)
            self.assertEqual(data_group.counted_data_items[data_item2], 1)
            document_model.remove_data_item(data_item1)
            self.assertEqual(data_group.counted_data_items[data_item1], 0)
            self.assertEqual(data_group.counted_data_items[data_item2], 1)

if __name__ == '__main__':
    unittest.main()
