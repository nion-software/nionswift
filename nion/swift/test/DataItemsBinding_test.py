# standard libraries
import contextlib
import logging
import operator
import random
import threading
import time
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift import Facade
from nion.utils import ListModel
from nion.utils import Selection


Facade.initialize()


class TestDataItemsModelModule(unittest.TestCase):

    values = ["DEF", "ABC", "GHI", "DFG", "ACD", "GIJ"]
    indexes = [0, 0, 1, 1, 2, 4]
    result = ["ABC", "DFG", "ACD", "GHI", "GIJ", "DEF"]

    def test_inserting_items_into_model_index0_with_sort_key_puts_them_in_correct_order(self):
        list_model = ListModel.ListModel("data_items")
        filtered_data_items = ListModel.FilteredListModel(items_key="data_items")
        filtered_data_items.container = list_model
        filtered_data_items.sort_key = operator.attrgetter("title")
        data_items = list()
        for value in TestDataItemsModelModule.values:
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            data_item.title = value
            list_model.insert_item(0, data_item)
            data_items.append(data_item)
        self.assertEqual([d.title for d in filtered_data_items.items], sorted([d.title for d in filtered_data_items.items]))

    def test_inserting_items_into_model_with_sort_key_reversed_puts_them_in_correct_order(self):
        list_model = ListModel.ListModel("data_items")
        filtered_data_items = ListModel.FilteredListModel(items_key="data_items")
        filtered_data_items.container = list_model
        filtered_data_items.sort_key = operator.attrgetter("title")
        filtered_data_items.sort_reverse = True
        data_items = list()
        for value in TestDataItemsModelModule.values:
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            data_item.title = value
            list_model.insert_item(0, data_item)
            data_items.append(data_item)
        self.assertListEqual([d.title for d in filtered_data_items.items], list(reversed(sorted([d.title for d in filtered_data_items.items]))))

    def test_inserting_items_into_model_with_sort_key_and_filter_puts_them_in_correct_order(self):
        list_model = ListModel.ListModel("data_items")
        filtered_data_items = ListModel.FilteredListModel(items_key="data_items")
        filtered_data_items.container = list_model
        filtered_data_items.filter = ListModel.StartsWithFilter("title", "D")
        filtered_data_items.sort_key = operator.attrgetter("title")
        data_items = list()
        for value in TestDataItemsModelModule.values:
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            data_item.title = value
            list_model.insert_item(0, data_item)
            data_items.append(data_item)
        self.assertEqual([d.title for d in filtered_data_items.items], sorted([d.title for d in filtered_data_items.items]))

    def test_inserting_items_into_model_index0_without_sort_key_puts_them_in_same_order(self):
        list_model = ListModel.ListModel("data_items")
        filtered_data_items = ListModel.FilteredListModel(items_key="data_items")
        filtered_data_items.container = list_model
        data_items = list()
        for index, value in enumerate(TestDataItemsModelModule.values):
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            data_item.title = value
            list_model.insert_item(TestDataItemsModelModule.indexes[index], data_item)
            data_items.append(data_item)
        self.assertEqual([d.title for d in filtered_data_items.items], TestDataItemsModelModule.result)

    def test_inserting_items_into_model_index0_without_sort_key__but_with_filter_puts_them_in_same_order(self):
        values = ["DEF", "ABC", "GHI", "DFG", "ACD", "GIJ"]
        indexes = [0, 0, 1, 1, 2, 4]
        result = ["ABC", "DFG", "ACD", "GHI", "GIJ", "DEF"]
        list_model = ListModel.ListModel("data_items")
        filtered_data_items = ListModel.FilteredListModel(items_key="data_items")
        filtered_data_items.container = list_model
        filtered_data_items.filter = ListModel.NotFilter(ListModel.StartsWithFilter("title", "D"))
        data_items = list()
        for index, value in enumerate(values):
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            data_item.title = value
            list_model.insert_item(indexes[index], data_item)
            data_items.append(data_item)
        self.assertEqual([d.title for d in filtered_data_items.items], [v for v in result if not v.startswith("D")])

    def test_filter_model_follows_model(self):
        list_model = ListModel.ListModel("data_items")
        selection = Selection.IndexedSelection()
        filtered_data_items = ListModel.FilteredListModel(items_key="data_items")
        filtered_data_items.container = list_model
        filtered_data_items.sort_key = operator.attrgetter("title")
        filtered_data_items2 = ListModel.FilteredListModel(items_key="data_items", container=filtered_data_items, selection=selection)
        data_items = list()
        for value in TestDataItemsModelModule.values:
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            data_item.title = value
            list_model.insert_item(0, data_item)
            data_items.append(data_item)
        self.assertEqual([d.title for d in filtered_data_items.items], sorted([d.title for d in filtered_data_items.items]))
        self.assertEqual([d.title for d in filtered_data_items.items], [d.title for d in filtered_data_items2.items])

    def test_filter_model_inits_with_source_model(self):
        list_model = ListModel.ListModel("data_items")
        filtered_data_items = ListModel.FilteredListModel(items_key="data_items")
        filtered_data_items.container = list_model
        filtered_data_items.sort_key = operator.attrgetter("title")
        data_items = list()
        for value in TestDataItemsModelModule.values:
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            data_item.title = value
            list_model.insert_item(0, data_item)
            data_items.append(data_item)
        self.assertEqual([d.title for d in filtered_data_items.items], sorted([d.title for d in filtered_data_items.items]))
        selection = Selection.IndexedSelection()
        filtered_data_items2 = ListModel.FilteredListModel(items_key="data_items", container=filtered_data_items, selection=selection)
        self.assertEqual([d.title for d in filtered_data_items.items], [d.title for d in filtered_data_items2.items])

    def test_sorted_model_updates_when_transaction_started(self):
        def sort_by_date_key(data_item):
            """ A sort key to for the modification date field of a data item. """
            return data_item.is_live, data_item.created
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            filtered_data_items = ListModel.FilteredListModel(items_key="data_items")
            filtered_data_items.container = document_model
            filtered_data_items.sort_key = sort_by_date_key
            filtered_data_items.sort_reverse = True
            for value in TestDataItemsModelModule.values:
                data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
                data_item.title = value
                document_model.append_data_item(data_item)
            live_data_item = filtered_data_items.items[2]
            with document_model.data_item_live(live_data_item):
                self.assertEqual(filtered_data_items.items.index(live_data_item), 0)

    def test_sorted_filtered_model_updates_when_data_item_enters_filter(self):
        def sort_by_date_key(data_item):
            return data_item.created
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            filtered_data_items = ListModel.FilteredListModel(items_key="data_items")
            filtered_data_items.container = document_model
            filtered_data_items.filter = ListModel.EqFilter("is_live", True)
            filtered_data_items.sort_key = sort_by_date_key
            for _ in range(4):
                data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
            self.assertEqual(len(filtered_data_items.items), 0)
            with document_model.data_item_live(document_model.data_items[0]):
                document_model.data_items[0].library_item_changed_event.fire()
                self.assertEqual(len(filtered_data_items.items), 1)
                with document_model.data_item_live(document_model.data_items[2]):
                    document_model.data_items[2].library_item_changed_event.fire()
                    self.assertEqual(len(filtered_data_items.items), 2)
                    self.assertTrue(filtered_data_items.items.index(document_model.data_items[0]) < filtered_data_items.items.index(document_model.data_items[2]))

    def test_unsorted_filtered_model_updates_when_data_item_enters_filter(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            filtered_data_items = ListModel.FilteredListModel(items_key="data_items")
            filtered_data_items.container = document_model
            filtered_data_items.filter = ListModel.EqFilter("is_live", True)
            for _ in range(4):
                data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
            self.assertEqual(len(filtered_data_items.items), 0)
            with document_model.data_item_live(document_model.data_items[0]):
                document_model.data_items[0].library_item_changed_event.fire()
                self.assertEqual(len(filtered_data_items.items), 1)
                with document_model.data_item_live(document_model.data_items[2]):
                    document_model.data_items[2].library_item_changed_event.fire()
                    self.assertEqual(len(filtered_data_items.items), 2)

    def test_sorted_filtered_model_updates_when_data_item_exits_filter(self):
        def sort_by_date_key(data_item):
            return data_item.created
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            filtered_data_items = ListModel.FilteredListModel(items_key="data_items")
            filtered_data_items.container = document_model
            filtered_data_items.filter = ListModel.NotFilter(ListModel.EqFilter("is_live", True))
            filtered_data_items.sort_key = sort_by_date_key
            for _ in range(4):
                data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
            self.assertEqual(len(filtered_data_items.items), 4)
            with document_model.data_item_live(document_model.data_items[0]):
                document_model.data_items[0].library_item_changed_event.fire()
                self.assertEqual(len(filtered_data_items.items), 3)

    def test_filtered_model_updates_when_source_model_has_data_item_that_updates(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            filtered_data_items = ListModel.FilteredListModel(items_key="data_items")
            filtered_data_items.container = document_model
            for _ in range(4):
                data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
            self.assertEqual(len(filtered_data_items.items), 4)
            selection = Selection.IndexedSelection()
            filtered_data_items2 = ListModel.FilteredListModel(items_key="data_items", container=filtered_data_items, selection=selection)
            filtered_data_items2.filter = ListModel.EqFilter("is_live", True)
            self.assertEqual(len(filtered_data_items2.items), 0)
            with document_model.data_item_live(document_model.data_items[0]):
                document_model.data_items[0].library_item_changed_event.fire()
                self.assertEqual(len(filtered_data_items.items), 4)  # verify assumption
                self.assertEqual(len(filtered_data_items2.items), 1)  # verify assumption
                self.assertTrue(document_model.data_items[0] in filtered_data_items2.items)

    def test_random_filtered_model_updates(self):
        list_model = ListModel.ListModel("data_items")
        filtered_data_items = ListModel.FilteredListModel(items_key="data_items")
        filtered_data_items.container = list_model
        data_items = list()
        cc = 30
        for _ in range(cc):
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            list_model.insert_item(0, data_item)
            data_items.append(data_item)
        selection = Selection.IndexedSelection()
        filtered_data_items2 = ListModel.FilteredListModel(items_key="data_items", container=filtered_data_items, selection=selection)
        import random
        for xx in range(10):
            c1 = [n for n in range(cc)]
            c2 = [n for n in range(cc) if random.randint(0,100) > 20]
            random.shuffle(c1)
            random.shuffle(c2)
            def is_live_filter(data_item):
                return data_items.index(data_item) in c1
            def is_live_filter2(data_item):
                return data_items.index(data_item) in c2
            filtered_data_items.sort_key = lambda x: data_items.index(x)
            with filtered_data_items.changes():
                filtered_data_items.filter = ListModel.PredicateFilter(is_live_filter)
                filtered_data_items.filter = ListModel.PredicateFilter(is_live_filter2)
            self.assertEqual(set(c2), set([data_items.index(d) for d in filtered_data_items2.items]))

    def slow_test_threaded_filtered_model_updates(self):
        for _ in range(1000):
            list_model = ListModel.ListModel("data_items")
            filtered_data_items = ListModel.FilteredListModel(items_key="data_items")
            data_items = list()
            cc = 30
            for _ in range(cc):
                data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
                data_items.append(data_item)
            c1 = [n for n in range(cc) if random.randint(0,100) > 50]
            def is_live_filter(data_item):
                return data_items.index(data_item) in c1
            filtered_data_items.container = list_model
            filtered_data_items.sort_key = lambda x: data_items.index(x)
            selection = Selection.IndexedSelection()
            filtered_data_items2 = ListModel.FilteredListModel(items_key="data_items", container=filtered_data_items, selection=selection)
            filtered_data_items2.filter = ListModel.PredicateFilter(is_live_filter)
            finished = threading.Event()
            def update_randomly():
                for _ in range(cc):
                    data_item = random.choice(filtered_data_items._get_master_items())
                    data_item.library_item_changed_event.fire()
                finished.set()
            list_model.insert_item(0, data_items[0])
            threading.Thread(target = update_randomly).start()
            for index in range(1, cc):
                list_model.insert_item(index, data_items[index])
            finished.wait()
            filtered_data_items2.close()
            filtered_data_items.close()

    def test_data_items_sorted_by_data_modified_date(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            filtered_data_items = ListModel.FilteredListModel(items_key="data_items")
            filtered_data_items.container = document_model
            filtered_data_items.sort_key = DataItem.sort_by_date_key
            for _ in range(4):
                data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                time.sleep(0.01)
            self.assertEqual(len(filtered_data_items.items), 4)
            self.assertEqual(list(document_model.data_items), filtered_data_items.items)
            with document_model.data_items[0].data_ref() as dr:
                dr.data += 1
            self.assertEqual([document_model.data_items[1], document_model.data_items[2], document_model.data_items[3], document_model.data_items[0]], filtered_data_items.items)

    def test_processed_data_items_sorted_by_source_data_modified_date(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            filtered_data_items = ListModel.FilteredListModel(items_key="data_items")
            filtered_data_items.container = document_model
            filtered_data_items.sort_key = DataItem.sort_by_date_key
            for _ in range(4):
                data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                time.sleep(0.01)
            data_item = document_model.get_invert_new(document_model.data_items[0])
            document_model.recompute_all()
            self.assertEqual(len(filtered_data_items.items), 5)
            # new data item should be last
            self.assertEqual(filtered_data_items.items.index(document_model.data_items[4]), 4)
            self.assertEqual(filtered_data_items.items.index(document_model.data_items[0]), 0)
            self.assertEqual(list(document_model.data_items[2:5]), filtered_data_items.items[2:])  # rest of list matches

    def test_and_filter(self):
        f1 = ListModel.Filter(True)
        f2 = ListModel.Filter(True)
        f3 = ListModel.Filter(False)
        f4 = ListModel.Filter(False)
        self.assertTrue(ListModel.AndFilter([f1, f2]).matches(None))
        self.assertFalse(ListModel.AndFilter([f2, f3]).matches(None))
        self.assertTrue(ListModel.OrFilter([f2, f3]).matches(None))
        self.assertFalse(ListModel.OrFilter([f3, f4]).matches(None))


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
