# futures
from __future__ import absolute_import

# standard libraries
import logging
import random
import unittest
import weakref

# third party libraries
import numpy

# local libraries
from nion.swift.model import DataItem
from nion.swift.model import Symbolic


class TestSymbolicClass(unittest.TestCase):

    def test_unary_inversion_returns_inverted_data(self):
        d = numpy.zeros((8, 8), dtype=numpy.uint32)
        d[:] = random.randint(0, 100)
        data_item = DataItem.DataItem(d)
        map = { weakref.ref(data_item): "a" }
        data_node = Symbolic.calculate("-a", map)
        data = data_node.data
        assert numpy.array_equal(data, -d)

    def test_binary_addition_returns_added_data(self):
        d1 = numpy.zeros((8, 8), dtype=numpy.uint32)
        d1[:] = random.randint(0, 100)
        data_item1 = DataItem.DataItem(d1)
        d2 = numpy.zeros((8, 8), dtype=numpy.uint32)
        d2[:] = random.randint(0, 100)
        data_item2 = DataItem.DataItem(d2)
        map = { weakref.ref(data_item1): "a", weakref.ref(data_item2): "b" }
        data_node = Symbolic.calculate("a+b", map)
        data = data_node.data
        assert numpy.array_equal(data, d1 + d2)

    def test_binary_multiplication_with_scalar_returns_multiplied_data(self):
        d = numpy.zeros((8, 8), dtype=numpy.uint32)
        d[:] = random.randint(0, 100)
        data_item = DataItem.DataItem(d)
        map = { weakref.ref(data_item): "a" }
        data_node1 = Symbolic.calculate("a * 5", map)
        data1 = data_node1.data
        data_node2 = Symbolic.calculate("5 * a", map)
        data2 = data_node2.data
        assert numpy.array_equal(data1, d * 5)
        assert numpy.array_equal(data2, d * 5)

    def test_subtract_min_returns_subtracted_min(self):
        d = numpy.zeros((8, 8), dtype=numpy.uint32)
        d[:] = random.randint(0, 100)
        data_item = DataItem.DataItem(d)
        map = { weakref.ref(data_item): "a" }
        data_node = Symbolic.calculate("a - min(a)", map)
        data = data_node.data
        assert numpy.array_equal(data, d - numpy.amin(d))

    def test_ability_to_take_slice(self):
        d = numpy.zeros((32, 8, 8), dtype=numpy.uint32)
        d[:] = random.randint(0, 100)
        data_item = DataItem.DataItem(d)
        map = { weakref.ref(data_item): "a" }
        data_node = Symbolic.calculate("a[:,4,4]", map)
        data = data_node.data
        assert numpy.array_equal(data, d[:,4,4])


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
