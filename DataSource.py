# standard libraries
import copy
import gettext
import logging
import threading
import uuid
import weakref

# third party libraries
import numpy

# local libraries
from Decorators import singleton

_ = gettext.gettext


# Use the singleton to control access to DataSourceManager.
@singleton
class DataSourceManager(object):
    def __init__(self):
        self.data_source_factories = []
        self.__data_source_factory_map = {}
        self.__observers = []

    # Useful for testing.
    def reset_(self, values):
        new_values = self.data_source_factories
        self.data_source_factories = values
        self.__data_source_factory_map = {}
        for data_source_factory in self.data_source_factories:
            self.__data_source_factory_map[data_source_factory.id] = data_source_factory
        return new_values

    def getDataSourceFactoryById(self, id):
        return self.__data_source_factory_map[id]

    def registerDataSourceFactory(self, data_source_factory):
        assert id not in self.__data_source_factory_map
        self.data_source_factories.append(data_source_factory)
        self.__data_source_factory_map[data_source_factory.id] = data_source_factory
        for observer in self.__observers:
            observer()

    def unregisterDataSourceFactory(self, id):
        assert id in self.__data_source_factory_map
        data_source_factory = self.__data_source_factory_map[id]
        self.data_source_factories.remove(data_source_factory)
        del self.__data_source_factory_map[id]
        for observer in self.__observers:
            observer()

    # TODO: Without storing a weakref, this probably causes a leak
    def addObserver(self, fn):
        self.__observers.append(fn)
