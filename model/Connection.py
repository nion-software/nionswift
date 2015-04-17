"""
    Contains classes related to connections between library objects.
"""

# standard libraries
import copy
import logging
import uuid
import weakref

# third party libraries
# None

# local libraries
from nion.ui import Binding
from nion.ui import Observable


class Connection(Observable.Observable, Observable.Broadcaster, Observable.ManagedObject):
    """ Represents a connection between two objects. """

    def __init__(self, type):
        super(Connection, self).__init__()
        self.define_type(type)

    def about_to_be_removed(self):
        pass

    def _property_changed(self, name, value):
        self.notify_set_property(name, value)


class UuidToStringConverter(object):
    def convert(self, value):
        return str(value)
    def convert_back(self, value):
        return uuid.UUID(value)


class PropertyConnection(Connection):
    """ Binds the properties of two objects together. """

    def __init__(self, source=None, source_property=None, target=None, target_property=None):
        super(PropertyConnection, self).__init__("property-connection")
        self.define_property("source_uuid", converter=UuidToStringConverter())
        self.define_property("source_property")
        self.define_property("target_uuid", converter=UuidToStringConverter())
        self.define_property("target_property")
        # these are only set in managed object context changed
        self.__source = source
        self.__target = target
        self.__binding = None
        # suppress messages while we're setting source or target
        self.__suppress = False
        # but setup if we were passed objects
        if source is not None:
            self.source_uuid = source.uuid
        if source_property:
            self.source_property = source_property
        if target is not None:
            self.target_uuid = target.uuid
        if target_property:
            self.target_property = target_property

    def __set_target_from_source(self, value):
        if not self.__suppress:
            self.__suppress = True
            setattr(self.__target, self.target_property, value)
            self.__suppress = False

    def __set_source_from_target(self, value):
        if not self.__suppress:
            self.__suppress = True
            if self.__binding:
                self.__binding.update_source(value)
            self.__suppress = False

    def managed_object_context_changed(self):
        super(PropertyConnection, self).managed_object_context_changed()
        """ Override from ManagedObject. """
        def register():
            if self.__source is not None and self.__target is not None:
                self.__binding = Binding.PropertyBinding(self.__source, self.source_property)
                self.__binding.target_setter = self.__set_target_from_source
                self.__binding.update_target_direct(self.__binding.get_target_value())
        def source_registered(source):
            self.__source = source
            register()
        def target_registered(target):
            self.__target = target
            self.__target.add_observer(self)
            register()
        def unregistered(source=None):
            if self.__binding:
                self.__binding.close()
                self.__binding = None
            if self.__target is not None:
                    self.__target.remove_observer(self)
        if self.managed_object_context:
            self.managed_object_context.subscribe(self.source_uuid, source_registered, unregistered)
            self.managed_object_context.subscribe(self.target_uuid, target_registered, unregistered)
        else:
            unregistered()

    def property_changed(self, sender, property_name, value):
        """
            This message comes from the target since this object is an observer.
            Updates the source.
        """
        if sender == self.__target and property_name == self.target_property:
            self.__set_source_from_target(value)



def connection_factory(lookup_id):
    build_map = {
        "property-connection": PropertyConnection,
    }
    type = lookup_id("type")
    return build_map[type]() if type in build_map else None
