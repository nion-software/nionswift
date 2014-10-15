# standard libraries
import logging
import operator
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift.model import DataItem
from nion.swift.model import DataItemsBinding
from nion.swift.model import Utility


class TestDataItemsBindingModule(unittest.TestCase):

    values = ["DEF", "ABC", "GHI", "DFG", "ACD", "GIJ"]
    indexes = [0, 0, 1, 1, 2, 4]
    result = ["ABC", "DFG", "ACD", "GHI", "GIJ", "DEF"]

    def test_inserting_items_into_binding_index0_with_sort_key_puts_them_in_correct_order(self):
        binding = DataItemsBinding.DataItemsInContainerBinding()
        binding.sort_key = operator.attrgetter("title")
        data_items = list()
        for value in TestDataItemsBindingModule.values:
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            data_item.title = value
            binding.data_item_inserted(None, data_item, 0, False)
            data_items.append(data_item)
        self.assertEqual([d.title for d in binding.data_items], sorted([d.title for d in binding.data_items]))

    def test_inserting_items_into_binding_with_sort_key_reversed_puts_them_in_correct_order(self):
        binding = DataItemsBinding.DataItemsInContainerBinding()
        binding.sort_key = operator.attrgetter("title")
        binding.sort_reverse = True
        data_items = list()
        for value in TestDataItemsBindingModule.values:
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            data_item.title = value
            binding.data_item_inserted(None, data_item, 0, False)
            data_items.append(data_item)
        self.assertListEqual([d.title for d in binding.data_items], list(reversed(sorted([d.title for d in binding.data_items]))))

    def test_inserting_items_into_binding_with_sort_key_and_filter_puts_them_in_correct_order(self):
        def filter(data_item):
            return not data_item.title.startswith("D")
        binding = DataItemsBinding.DataItemsInContainerBinding()
        binding.filter = filter
        binding.sort_key = operator.attrgetter("title")
        data_items = list()
        for value in TestDataItemsBindingModule.values:
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            data_item.title = value
            binding.data_item_inserted(None, data_item, 0, False)
            data_items.append(data_item)
        self.assertEqual([d.title for d in binding.data_items], sorted([d.title for d in binding.data_items]))

    def test_inserting_items_into_binding_index0_without_sort_key_puts_them_in_same_order(self):
        binding = DataItemsBinding.DataItemsInContainerBinding()
        data_items = list()
        for index, value in enumerate(TestDataItemsBindingModule.values):
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            data_item.title = value
            binding.data_item_inserted(None, data_item, TestDataItemsBindingModule.indexes[index], False)
            data_items.append(data_item)
        self.assertEqual([d.title for d in binding.data_items], TestDataItemsBindingModule.result)

    def test_inserting_items_into_binding_index0_without_sort_key__but_with_filter_puts_them_in_same_order(self):
        values = ["DEF", "ABC", "GHI", "DFG", "ACD", "GIJ"]
        indexes = [0, 0, 1, 1, 2, 4]
        result = ["ABC", "DFG", "ACD", "GHI", "GIJ", "DEF"]
        def filter(data_item):
            return not data_item.title.startswith("D")
        binding = DataItemsBinding.DataItemsInContainerBinding()
        binding.filter = filter
        data_items = list()
        for index, value in enumerate(values):
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            data_item.title = value
            binding.data_item_inserted(None, data_item, indexes[index], False)
            data_items.append(data_item)
        self.assertEqual([d.title for d in binding.data_items], [v for v in result if not v.startswith("D")])

    def test_filter_binding_follows_binding(self):
        binding = DataItemsBinding.DataItemsInContainerBinding()
        binding2 = DataItemsBinding.DataItemsFilterBinding(binding)
        binding.sort_key = operator.attrgetter("title")
        data_items = list()
        for value in TestDataItemsBindingModule.values:
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            data_item.title = value
            binding.data_item_inserted(None, data_item, 0, False)
            data_items.append(data_item)
        self.assertEqual([d.title for d in binding.data_items], sorted([d.title for d in binding.data_items]))
        self.assertEqual([d.title for d in binding.data_items], [d.title for d in binding2.data_items])

    def test_filter_binding_inits_with_source_binding(self):
        binding = DataItemsBinding.DataItemsInContainerBinding()
        binding.sort_key = operator.attrgetter("title")
        data_items = list()
        for value in TestDataItemsBindingModule.values:
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            data_item.title = value
            binding.data_item_inserted(None, data_item, 0, False)
            data_items.append(data_item)
        self.assertEqual([d.title for d in binding.data_items], sorted([d.title for d in binding.data_items]))
        binding2 = DataItemsBinding.DataItemsFilterBinding(binding)
        self.assertEqual([d.title for d in binding.data_items], [d.title for d in binding2.data_items])

    def test_sorted_binding_updates_when_transaction_started(self):
        def sort_by_date_key(data_item):
            """ A sort key to for the datetime_original field of a data item. """
            return data_item.is_live, Utility.get_datetime_from_datetime_item(data_item.datetime_original)
        binding = DataItemsBinding.DataItemsInContainerBinding()
        binding.sort_key = sort_by_date_key
        binding.sort_reverse = True
        data_items = list()
        for value in TestDataItemsBindingModule.values:
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            data_item.title = value
            binding.data_item_inserted(None, data_item, 0, False)
            data_items.append(data_item)
        live_data_item = binding.data_items[2]
        live_data_item.begin_live()
        try:
            self.assertEqual(binding.data_items.index(live_data_item), 0)
        finally:
            live_data_item.end_live()

    def test_sorted_filtered_binding_updates_when_data_item_enters_filter(self):
        def is_live_filter(data_item):
            return data_item.is_live
        def sort_by_date_key(data_item):
            return Utility.get_datetime_from_datetime_item(data_item.datetime_original)
        binding = DataItemsBinding.DataItemsInContainerBinding()
        binding.filter = is_live_filter
        binding.sort_key = sort_by_date_key
        data_items = list()
        for _ in range(4):
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            binding.data_item_inserted(None, data_item, 0, False)
            data_items.append(data_item)
        self.assertEqual(len(binding.data_items), 0)
        with data_items[0].live():
            binding.data_item_content_changed(data_items[0], [DataItem.METADATA])
            self.assertEqual(len(binding.data_items), 1)
            with data_items[2].live():
                binding.data_item_content_changed(data_items[2], [DataItem.METADATA])
                self.assertEqual(len(binding.data_items), 2)
                self.assertTrue(binding.data_items.index(data_items[0]) < binding.data_items.index(data_items[2]))

    def test_unsorted_filtered_binding_updates_when_data_item_enters_filter(self):
        def is_live_filter(data_item):
            return data_item.is_live
        binding = DataItemsBinding.DataItemsInContainerBinding()
        binding.filter = is_live_filter
        data_items = list()
        for _ in range(4):
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            binding.data_item_inserted(None, data_item, 0, False)
            data_items.append(data_item)
        self.assertEqual(len(binding.data_items), 0)
        with data_items[0].live():
            binding.data_item_content_changed(data_items[0], [DataItem.METADATA])
            self.assertEqual(len(binding.data_items), 1)
            with data_items[2].live():
                binding.data_item_content_changed(data_items[2], [DataItem.METADATA])
                self.assertEqual(len(binding.data_items), 2)

    def test_sorted_filtered_binding_updates_when_data_item_exits_filter(self):
        def is_not_live_filter(data_item):
            return not data_item.is_live
        def sort_by_date_key(data_item):
            return Utility.get_datetime_from_datetime_item(data_item.datetime_original)
        binding = DataItemsBinding.DataItemsInContainerBinding()
        binding.filter = is_not_live_filter
        binding.sort_key = sort_by_date_key
        data_items = list()
        for _ in range(4):
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            binding.data_item_inserted(None, data_item, 0, False)
            data_items.append(data_item)
        self.assertEqual(len(binding.data_items), 4)
        with data_items[0].live():
            binding.data_item_content_changed(data_items[0], [DataItem.METADATA])
            self.assertEqual(len(binding.data_items), 3)

    def test_filtered_binding_updates_when_source_binding_has_data_item_that_updates(self):
        binding = DataItemsBinding.DataItemsInContainerBinding()
        data_items = list()
        for _ in range(4):
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            binding.data_item_inserted(None, data_item, 0, False)
            data_items.append(data_item)
        self.assertEqual(len(binding.data_items), 4)
        filter_binding = DataItemsBinding.DataItemsFilterBinding(binding)
        def is_live_filter(data_item):
            return data_item.is_live
        filter_binding.filter = is_live_filter
        self.assertEqual(len(filter_binding.data_items), 0)
        with data_items[0].live():
            binding.data_item_content_changed(data_items[0], [DataItem.METADATA])
            self.assertEqual(len(binding.data_items), 4)  # verify assumption
            self.assertTrue(data_items[0] in filter_binding.data_items)

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
