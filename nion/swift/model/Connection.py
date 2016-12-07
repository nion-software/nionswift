"""
    Contains classes related to connections between library objects.
"""

# standard libraries
import copy
import functools

# third party libraries
# None

# local libraries
from nion.swift.model import Graphics
from nion.utils import Binding
from nion.utils import Converter
from nion.utils import Observable
from nion.utils import Persistence


class Connection(Observable.Observable, Persistence.PersistentObject):
    """ Represents a connection between two objects. """

    def __init__(self, type):
        super().__init__()
        self.define_type(type)
        self._closed = False

    def close(self):
        assert not self._closed
        self._closed = True

    def clone(self) -> "Connection":
        connection = copy.deepcopy(self)
        connection.uuid = self.uuid
        return connection

    def _property_changed(self, name, value):
        self.notify_property_changed(name)


class PropertyConnection(Connection):
    """ Binds the properties of two objects together. """

    def __init__(self, source=None, source_property=None, target=None, target_property=None):
        super().__init__("property-connection")
        self.define_property("source_uuid", converter=Converter.UuidToStringConverter())
        self.define_property("source_property")
        self.define_property("target_uuid", converter=Converter.UuidToStringConverter())
        self.define_property("target_property")
        # these are only set in persistent object context changed
        self.__source = source
        self.__target = target
        self.__binding = None
        self.__target_property_changed_listener = None
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

    def close(self):
        if self.__binding:
            self.__binding.close()
            self.__binding = None
        if self.__target_property_changed_listener:
            self.__target_property_changed_listener.close()
            self.__target_property_changed_listener = None
        super().close()

    @property
    def _target(self):
        return self.__target

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

    def persistent_object_context_changed(self):
        """ Override from PersistentObject. """
        super().persistent_object_context_changed()

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

            def property_changed(target, property_name):
                if property_name == self.target_property:
                    self.__set_source_from_target(getattr(target, property_name))

            assert self.__target_property_changed_listener is None
            self.__target_property_changed_listener = target.property_changed_event.listen(functools.partial(property_changed, target))
            register()

        def unregistered(source=None):
            if self.__binding:
                self.__binding.close()
                self.__binding = None
            if self.__target_property_changed_listener:
                self.__target_property_changed_listener.close()
                self.__target_property_changed_listener = None

        if self.persistent_object_context:
            self.persistent_object_context.subscribe(self.source_uuid, source_registered, unregistered)
            self.persistent_object_context.subscribe(self.target_uuid, target_registered, unregistered)
        else:
            unregistered()


class IntervalListConnection(Connection):
    """Binds the intervals on a display to the interval_descriptors on a line profile graphic.

    This is a one way connection from the display to the line profile graphic.
    """

    def __init__(self, display=None, line_profile=None):
        super().__init__("interval-list-connection")
        self.define_property("source_uuid", converter=Converter.UuidToStringConverter())
        self.define_property("target_uuid", converter=Converter.UuidToStringConverter())
        # these are only set in persistent object context changed
        self.__source = display
        self.__target = line_profile
        self.__item_inserted_event_listener = None
        self.__item_removed_event_listener = None
        self.__interval_mutated_listeners = list()
        # but setup if we were passed objects
        if display is not None:
            self.source_uuid = display.uuid
        if line_profile is not None:
            self.target_uuid = line_profile.uuid

    def close(self):
        super().close()

    def persistent_object_context_changed(self):
        """ Override from PersistentObject. """
        super().persistent_object_context_changed()

        def detach():
            for listener in self.__interval_mutated_listeners:
                listener.close()
            self.__interval_mutated_listeners = list()

        def reattach():
            detach()
            interval_descriptors = list()
            if self.__source:
                for region in self.__source.graphics:
                    if isinstance(region, Graphics.IntervalGraphic):
                        interval_descriptor = {"interval": region.interval, "color": "#F00"}
                        interval_descriptors.append(interval_descriptor)
                        self.__interval_mutated_listeners.append(region.property_changed_event.listen(lambda k: reattach()))
            if self.__target:
                self.__target.interval_descriptors = interval_descriptors

        def item_inserted(key, value, before_index):
            if key == "graphics" and self.__target:
                reattach()

        def item_removed(key, value, index):
            if key == "graphics" and self.__target:
                reattach()

        def source_registered(source):
            self.__source = source
            self.__item_inserted_event_listener = self.__source.item_inserted_event.listen(item_inserted)
            self.__item_removed_event_listener = self.__source.item_removed_event.listen(item_removed)
            reattach()

        def target_registered(target):
            self.__target = target
            reattach()

        def unregistered(source=None):
            if self.__item_inserted_event_listener:
                self.__item_inserted_event_listener.close()
                self.__item_inserted_event_listener = None
            if self.__item_removed_event_listener:
                self.__item_removed_event_listener.close()
                self.__item_removed_event_listener = None

        if self.persistent_object_context:
            self.persistent_object_context.subscribe(self.source_uuid, source_registered, unregistered)
            self.persistent_object_context.subscribe(self.target_uuid, target_registered, unregistered)
        else:
            unregistered()


def connection_factory(lookup_id):
    build_map = {
        "property-connection": PropertyConnection,
        "interval-list-connection": IntervalListConnection,
    }
    type = lookup_id("type")
    return build_map[type]() if type in build_map else None
