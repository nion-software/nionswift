# standard libraries
import logging
import unittest
import uuid

# third party libraries
# None

# local libraries
from nion.swift import Application
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Storage
from nion.ui import Test


class ObjectWithUUID(object):

    def __init__(self):
        self.uuid = uuid.uuid4()


class TestObjectStoreClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_object_store_calls_register_on_already_registered_object(self):
        global was_registered
        object_store = DocumentModel.ObjectStore()
        object1 = ObjectWithUUID()
        object_store.register(object1)
        was_registered = False
        def registered(object):
            global was_registered
            was_registered = True
        object_store.subscribe(object1.uuid, registered, None)
        self.assertTrue(was_registered)

    def test_object_store_calls_register_when_object_becomes_registered(self):
        global was_registered
        object_store = DocumentModel.ObjectStore()
        object1 = ObjectWithUUID()
        was_registered = False
        def registered(object):
            global was_registered
            was_registered = True
        object_store.subscribe(object1.uuid, registered, None)
        object_store.register(object1)
        self.assertTrue(was_registered)

    def test_object_store_calls_unregister_when_object_becomes_unregistered(self):
        global was_registered
        object_store = DocumentModel.ObjectStore()
        object1 = ObjectWithUUID()
        was_registered = False
        def registered(object):
            global was_registered
            was_registered = True
        def unregistered(object):
            global was_registered
            was_registered = False
        object_store.subscribe(object1.uuid, registered, unregistered)
        object_store.register(object1)
        self.assertTrue(was_registered)
        object1 = None
        self.assertFalse(was_registered)


class TestDocumentModelClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_remove_data_items_on_document_model(self):
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
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
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
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

if __name__ == '__main__':
    unittest.main()
