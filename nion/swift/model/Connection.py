"""
    Contains classes related to connections between library objects.
"""

# standard libraries
import copy
import functools
import typing
import uuid
import weakref

# third party libraries
# None

# local libraries
from nion.swift.model import Graphics
from nion.swift.model import Persistence
from nion.utils import Binding
from nion.utils import Converter
from nion.utils import Event
from nion.utils import Observable

if typing.TYPE_CHECKING:
    from nion.swift.model import Project


class Connection(Observable.Observable, Persistence.PersistentObject):
    """ Represents a connection between two objects. """

    def __init__(self, type, *, parent=None):
        super().__init__()
        self.about_to_cascade_delete_event = Event.Event()
        self.define_type(type)
        self.define_property("parent_specifier", changed=self.__parent_specifier_changed, key="parent_uuid")
        self.__parent_proxy = self.create_item_proxy(item=parent)
        self.parent_specifier = parent.project.create_specifier(parent).write() if parent else None

    def close(self) -> None:
        self.__parent_proxy.close()
        self.__parent_proxy = None
        super().close()

    @property
    def project(self) -> "Project.Project":
        return typing.cast("Project.Project", self.container)

    def create_proxy(self) -> Persistence.PersistentObjectProxy:
        return self.project.create_item_proxy(item=self)

    @property
    def item_specifier(self) -> Persistence.PersistentObjectSpecifier:
        return Persistence.PersistentObjectSpecifier(item_uuid=self.uuid, context_uuid=self.project.uuid)

    def prepare_cascade_delete(self) -> typing.List:
        cascade_items = list()
        self.about_to_cascade_delete_event.fire(cascade_items)
        return cascade_items

    def clone(self) -> "Connection":
        connection = copy.deepcopy(self)
        connection.uuid = self.uuid
        return connection

    def _property_changed(self, name, value):
        self.notify_property_changed(name)

    @property
    def parent(self):
        return self.__parent_proxy.item

    @parent.setter
    def parent(self, parent):
        self.__parent_proxy.item = parent
        self.parent_specifier = parent.project.create_specifier(parent).write() if parent else None

    def __parent_specifier_changed(self, name: str, d: typing.Dict) -> None:
        self.__parent_proxy.item_specifier = Persistence.PersistentObjectSpecifier.read(d)


class PropertyConnection(Connection):
    """ Binds the properties of two objects together. """

    def __init__(self, source=None, source_property=None, target=None, target_property=None, *, parent=None):
        super().__init__("property-connection", parent=parent)
        self.define_property("source_specifier", source.project.create_specifier(source).write() if source else None, changed=self.__source_specifier_changed, key="source_uuid")
        self.define_property("source_property")
        self.define_property("target_specifier", target.project.create_specifier(target).write() if target else None, changed=self.__target_specifier_changed, key="target_uuid")
        self.define_property("target_property")
        # these are only set in persistent object context changed
        self.__binding = None
        self.__target_property_changed_listener = None
        self.__source_proxy = self.create_item_proxy(item=source)
        self.__target_proxy = self.create_item_proxy(item=target)
        # suppress messages while we're setting source or target
        self.__suppress = False
        # set up the proxies

        def configure_binding():
            if self._source and self._target:
                assert not self.__binding
                self.__binding = Binding.PropertyBinding(self._source, self.source_property)
                self.__binding.target_setter = self.__set_target_from_source
                # while reading, the data item in the display data channel will not be connected;
                # we still set its value here. when the data item becomes valid, it will update.
                self.__binding.update_target_direct(self.__binding.get_target_value())

        def release_binding():
            if self.__binding:
                self.__binding.close()
                self.__binding = None
            if self.__target_property_changed_listener:
                self.__target_property_changed_listener.close()
                self.__target_property_changed_listener = None

        self.__source_proxy.on_item_registered = lambda x: configure_binding()
        self.__source_proxy.on_item_unregistered = lambda x: release_binding()

        def configure_target() -> None:
            def property_changed(target, property_name):
                if property_name == self.target_property:
                    self.__set_source_from_target(getattr(target, property_name))

            assert self.__target_property_changed_listener is None
            self.__target_property_changed_listener = self._target.property_changed_event.listen(functools.partial(property_changed, self._target))
            configure_binding()

        self.__target_proxy.on_item_registered = lambda x: configure_target()
        self.__target_proxy.on_item_unregistered = lambda x: release_binding()

        # but set up if we were passed objects
        if source is not None:
            self.__source_proxy.item = source
        if source_property:
            self.source_property = source_property
        if target is not None:
            self.__target_proxy.item = target
        if target_property:
            self.target_property = target_property

        if self._target:
            configure_target()

    def close(self):
        if self.__binding:
            self.__binding.close()
            self.__binding = None
        if self.__target_property_changed_listener:
            self.__target_property_changed_listener.close()
            self.__target_property_changed_listener = None
        self.__source_proxy.close()
        self.__source_proxy = None
        self.__target_proxy.close()
        self.__target_proxy = None
        super().close()

    @property
    def connected_items(self) -> typing.List:
        return [self._source, self._target]

    @property
    def _source(self):
        return self.__source_proxy.item

    @property
    def _target(self):
        return self.__target_proxy.item

    def __source_specifier_changed(self, name: str, d: typing.Dict) -> None:
        self.__source_proxy.item_specifier = Persistence.PersistentObjectSpecifier.read(d)

    def __target_specifier_changed(self, name: str, d: typing.Dict) -> None:
        self.__target_proxy.item_specifier = Persistence.PersistentObjectSpecifier.read(d)

    def __set_target_from_source(self, value):
        assert not self._closed
        if not self.__suppress:
            self.__suppress = True
            setattr(self._target, self.target_property, value)
            self.__suppress = False

    def __set_source_from_target(self, value):
        assert not self._closed
        if not self.__suppress:
            self.__suppress = True
            if self.__binding:
                self.__binding.update_source(value)
            self.__suppress = False


class IntervalListConnection(Connection):
    """Binds the intervals on a display to the interval_descriptors on a line profile graphic.

    This is a one way connection from the display to the line profile graphic.
    """

    def __init__(self, display_item=None, line_profile=None, *, parent=None):
        super().__init__("interval-list-connection", parent=parent)
        self.define_property("source_specifier", display_item.project.create_specifier(display_item).write() if display_item else None, changed=self.__source_specifier_changed, key="source_uuid")
        self.define_property("target_specifier", line_profile.project.create_specifier(line_profile).write() if line_profile else None, changed=self.__target_specifier_changed, key="target_uuid")
        # these are only set in persistent object context changed
        self.__item_inserted_event_listener = None
        self.__item_removed_event_listener = None
        self.__interval_mutated_listeners = list()
        self.__source_proxy = self.create_item_proxy(item=display_item)
        self.__target_proxy = self.create_item_proxy(item=line_profile)

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
            self.__item_inserted_event_listener = self.__source.item_inserted_event.listen(item_inserted)
            self.__item_removed_event_listener = self.__source.item_removed_event.listen(item_removed)
            reattach()

        def target_registered(target):
            reattach()

        def unregistered(item):
            if self.__item_inserted_event_listener:
                self.__item_inserted_event_listener.close()
                self.__item_inserted_event_listener = None
            if self.__item_removed_event_listener:
                self.__item_removed_event_listener.close()
                self.__item_removed_event_listener = None

        self.__source_proxy.on_item_registered = source_registered
        self.__source_proxy.on_item_unregistered = unregistered

        self.__target_proxy.on_item_registered = target_registered
        self.__target_proxy.on_item_unregistered = unregistered

        # but setup if we were passed objects
        if display_item is not None:
            self.__source_proxy.item = display_item
            source_registered(display_item)
        if line_profile is not None:
            self.__target_proxy.item = line_profile
            target_registered(line_profile)

    def close(self):
        self.__source_proxy.close()
        self.__source_proxy = None
        self.__target_proxy.close()
        self.__target_proxy = None
        super().close()

    @property
    def connected_items(self) -> typing.List:
        return [self.__source, self.__target]

    @property
    def __source(self):
        return self.__source_proxy.item

    @property
    def __target(self):
        return self.__target_proxy.item

    def __source_specifier_changed(self, name: str, d: typing.Dict) -> None:
        self.__source_proxy.item_specifier = Persistence.PersistentObjectSpecifier.read(d)

    def __target_specifier_changed(self, name: str, d: typing.Dict) -> None:
        self.__target_proxy.item_specifier = Persistence.PersistentObjectSpecifier.read(d)


def connection_factory(lookup_id):
    build_map = {
        "property-connection": PropertyConnection,
        "interval-list-connection": IntervalListConnection,
    }
    type = lookup_id("type")
    return build_map[type]() if type in build_map else None
