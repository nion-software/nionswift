# standard libraries
import logging
import operator
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift.model import DataItem
from nion.swift.model import DataItemsBinding


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
            data_item.add_ref()
            data_item.title = value
            binding.data_item_inserted(None, data_item, 0, False)
            data_items.append(data_item)
        self.assertEqual([d.title for d in binding.data_items], sorted([d.title for d in binding.data_items]))
        for data_item in data_items:
            data_item.remove_ref()

    def test_inserting_items_into_binding_with_sort_key_reversed_puts_them_in_correct_order(self):
        binding = DataItemsBinding.DataItemsInContainerBinding()
        binding.sort_key = operator.attrgetter("title")
        binding.sort_reverse = True
        data_items = list()
        for value in TestDataItemsBindingModule.values:
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            data_item.add_ref()
            data_item.title = value
            binding.data_item_inserted(None, data_item, 0, False)
            data_items.append(data_item)
        self.assertListEqual([d.title for d in binding.data_items], list(reversed(sorted([d.title for d in binding.data_items]))))
        for data_item in data_items:
            data_item.remove_ref()

    def test_inserting_items_into_binding_with_sort_key_and_filter_puts_them_in_correct_order(self):
        def filter(data_item):
            return not data_item.title.startswith("D")
        binding = DataItemsBinding.DataItemsInContainerBinding()
        binding.filter = filter
        binding.sort_key = operator.attrgetter("title")
        data_items = list()
        for value in TestDataItemsBindingModule.values:
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            data_item.add_ref()
            data_item.title = value
            binding.data_item_inserted(None, data_item, 0, False)
            data_items.append(data_item)
        self.assertEqual([d.title for d in binding.data_items], sorted([d.title for d in binding.data_items]))
        for data_item in data_items:
            data_item.remove_ref()

    def test_inserting_items_into_binding_index0_without_sort_key_puts_them_in_same_order(self):
        binding = DataItemsBinding.DataItemsInContainerBinding()
        data_items = list()
        for index, value in enumerate(TestDataItemsBindingModule.values):
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            data_item.add_ref()
            data_item.title = value
            binding.data_item_inserted(None, data_item, TestDataItemsBindingModule.indexes[index], False)
            data_items.append(data_item)
        self.assertEqual([d.title for d in binding.data_items], TestDataItemsBindingModule.result)
        for data_item in data_items:
            data_item.remove_ref()

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
            data_item.add_ref()
            data_item.title = value
            binding.data_item_inserted(None, data_item, indexes[index], False)
            data_items.append(data_item)
        self.assertEqual([d.title for d in binding.data_items], [v for v in result if not v.startswith("D")])
        for data_item in data_items:
            data_item.remove_ref()

    def test_filter_binding_follows_binding(self):
        binding = DataItemsBinding.DataItemsInContainerBinding()
        binding2 = DataItemsBinding.DataItemsFilterBinding(binding)
        binding.sort_key = operator.attrgetter("title")
        data_items = list()
        for value in TestDataItemsBindingModule.values:
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            data_item.add_ref()
            data_item.title = value
            binding.data_item_inserted(None, data_item, 0, False)
            data_items.append(data_item)
        self.assertEqual([d.title for d in binding.data_items], sorted([d.title for d in binding.data_items]))
        self.assertEqual([d.title for d in binding.data_items], [d.title for d in binding2.data_items])
        for data_item in data_items:
            data_item.remove_ref()


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
