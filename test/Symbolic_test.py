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
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Operation
from nion.swift.model import Symbolic


class TestSymbolicClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

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
        d = numpy.zeros((4, 8, 8), dtype=numpy.uint32)
        d[:] = random.randint(0, 100)
        data_item = DataItem.DataItem(d)
        map = { weakref.ref(data_item): "a" }
        data_node = Symbolic.calculate("a[:,4,4]", map)
        data = data_node.data
        assert numpy.array_equal(data, d[:,4,4])

    def test_ability_to_write_read_basic_nodes(self):
        d = numpy.zeros((8, 8), dtype=numpy.uint32)
        d[:] = random.randint(0, 100)
        data_item = DataItem.DataItem(d)
        map = { weakref.ref(data_item): "a" }
        data_node = Symbolic.calculate("-a * 5", map)
        dd = data_node.write()
        def resolve(uuid):
            return {data_item.maybe_data_source.uuid: data_item.maybe_data_source}[uuid]
        data_node2 = Symbolic.DataNode.factory(dd, resolve)
        data = data_node.data
        data2 = data_node2.data
        assert numpy.array_equal(data, -d * 5)
        assert numpy.array_equal(data, data2)

    def test_x(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        d = numpy.zeros((8, 8), dtype=numpy.uint32)
        d[:] = random.randint(0, 100)
        data_item = DataItem.DataItem(d)
        document_model.append_data_item(data_item)
        map = { weakref.ref(data_item): "a" }
        data_node = Symbolic.calculate("-a * 5", map)
        if data_node:
            operation_item = Operation.OperationItem("node-operation")
            operation_item.set_property("data_node", data_node.write())
            data_sources = data_node.data_sources
            operation_data_sources = list()
            for data_source in data_sources:
                data_source = Operation.DataItemDataSource(data_source)
                operation_data_sources.append(data_source)
            for operation_data_source in operation_data_sources:
                operation_item.add_data_source(operation_data_source)
            data_item = DataItem.DataItem()
            data_item.set_operation(operation_item)
            document_controller.document_model.append_data_item(data_item)
            document_controller.display_data_item(DataItem.DisplaySpecifier.from_data_item(data_item))
            document_model.recompute_all()


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
