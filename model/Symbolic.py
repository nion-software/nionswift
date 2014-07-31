"""
    Provide symbolic math services.
    
    The goal is to provide a module (namespace) where users can be provided with variables representing
    data items (directly or indirectly via reference to workspace panels).
    
    DataNodes represent data items, operations, numpy arrays, and constants.
"""

# standard libraries
import logging
import numbers
import operator
import uuid

# third party libraries
import numpy

# local libraries
from nion.swift.model import DataItem
from nion.swift.model import Operation


class DataNode(object):

    def __init__(self, inputs=None):
        self.inputs = inputs if inputs is not None else list()
        self.scalar = None

    @classmethod
    def make(cls, value):
        if isinstance(value, DataNode):
            return value
        elif isinstance(value, numbers.Integral):
            return ScalarDataNode(value)
        elif isinstance(value, numbers.Rational):
            return ScalarDataNode(value)
        elif isinstance(value, numbers.Real):
            return ScalarDataNode(value)
        elif isinstance(value, numbers.Complex):
            return ScalarDataNode(value)
        elif isinstance(value, DataItem.DataItem):
            return DataItemDataNode(value)
        assert False
        return None

    def __get_data(self):
        data_list = list()
        for input in self.inputs:
            data = input.data
            data = data if data is not None else input.scalar
            data_list.append(data)
        return self._get_data(data_list)
    data = property(__get_data)

    def _get_data(self, data_list):
        return None  # fall back on scalar

    def __abs__(self):
        return UnaryOperationDataNode([self], operator.abs)

    def __neg__(self):
        return UnaryOperationDataNode([self], operator.neg)

    def __pos__(self):
        return UnaryOperationDataNode([self], operator.pos)

    def __add__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], operator.add)

    def __radd__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], operator.add)

    def __sub__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], operator.sub)

    def __rsub__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], operator.sub)

    def __mul__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], operator.mul)

    def __rmul__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], operator.mul)

    def __div__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], operator.div)

    def __rdiv__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], operator.div)

    def __truediv__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], operator.truediv)

    def __rtruediv__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], operator.truediv)

    def __floordiv__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], operator.floordiv)

    def __rfloordiv__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], operator.floordiv)

    def __mod__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], operator.mod)

    def __rmod__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], operator.mod)

    def __pow__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], operator.pow)

    def __rpow__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], operator.pow)

    def __complex__(self):
        return ScalarDataNode(numpy.astype(numpy.complex128))

    def __int__(self):
        return ScalarDataNode(numpy.astype(numpy.uint32))

    def __long__(self):
        return ScalarDataNode(numpy.astype(numpy.int64))

    def __float__(self):
        return ScalarDataNode(numpy.astype(numpy.float64))

    def __getitem__(self, key):
        def take_slice(data):
            return data[key].copy()
        return UnaryOperationDataNode([self], take_slice)


def min(data_node):
    return ScalarDataNode(numpy.amin(data_node.data))

def max(data_node):
    return ScalarDataNode(numpy.amax(data_node.data))

def median(data_node):
    return ScalarDataNode(numpy.median(data_node.data))

def average(data_node):
    return ScalarDataNode(numpy.average(data_node.data))

def mean(data_node):
    return ScalarDataNode(numpy.mean(data_node.data))

def std(data_node):
    return ScalarDataNode(numpy.std(data_node.data))

def var(data_node):
    return ScalarDataNode(numpy.var(data_node.data))


class ScalarDataNode(DataNode):

    def __init__(self, value):
        super(ScalarDataNode, self).__init__()
        self.scalar = value


class UnaryOperationDataNode(DataNode):

    def __init__(self, inputs, fn):
        super(UnaryOperationDataNode, self).__init__(inputs=inputs)
        self.__fn = fn

    def _get_data(self, data_list):
        return self.__fn(data_list[0])


class BinaryOperationDataNode(DataNode):

    def __init__(self, inputs, fn):
        super(BinaryOperationDataNode, self).__init__(inputs=inputs)
        self.__fn = fn

    def _get_data(self, data_list):
        return self.__fn(data_list[0], data_list[1])


class DataItemDataNode(DataNode):

    def __init__(self, data_item):
        super(DataItemDataNode, self).__init__()
        self.__data_item = data_item

    def _get_data(self, data_list):
        return self.__data_item.data


def execute_code_lines(code_lines, g, l):
    """ Execute a list of code lines in the g, l globals, locals context. """


def calculate(calculation_script, weak_data_item_variable_map):
    code_lines = []
    code_lines.append("from nion.swift.model.Symbolic import *")
    g = dict()
    l = dict()
    for data_item_ref in weak_data_item_variable_map:
        data_item = data_item_ref()
        if data_item:
            data_item_var = weak_data_item_variable_map[data_item_ref]
            g[data_item_var] = DataNode.make(data_item)
    code_lines.append("result = {0}".format(calculation_script))
    code = "\n".join(code_lines)
    exec(code, g, l)
    return l["result"]



#d1 = DataNode(title="data1")
#d2 = DataNode(title="data2")

#print((d1 + d2).crop(((0.25, 0.25), (0.5, 0.5))) - 120)
#print d1
#print 3 + d1 + d2
#print -d1

# -r100
# r100 * 10
# r100 - min(r100)
