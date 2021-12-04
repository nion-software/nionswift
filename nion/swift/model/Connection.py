"""
    Contains classes related to connections between library objects.
"""

from __future__ import annotations

# standard libraries
import copy
import functools
import typing

# third party libraries
# None

# local libraries
from nion.swift.model import DisplayItem
from nion.swift.model import Graphics
from nion.swift.model import Persistence
from nion.utils import Binding

if typing.TYPE_CHECKING:
    from nion.swift.model import Project
    from nion.utils import Event

_SpecifierType = typing.Dict[str, typing.Any]


class Connection(Persistence.PersistentObject):
    """ Represents a connection between two objects. """

    def __init__(self, type: str, *, parent: typing.Optional[Persistence.PersistentObject] = None) -> None:
        super().__init__()
        self.define_type(type)
        self.define_property("parent_specifier", changed=self.__parent_specifier_changed, key="parent_uuid", hidden=True)
        self.__parent_reference = self.create_item_reference(item=parent)
        self.parent_specifier = Persistence.write_persistent_specifier(parent.uuid) if parent else None

    @property
    def parent_specifier(self) -> typing.Optional[Persistence._SpecifierType]:
        return typing.cast(typing.Optional[Persistence._SpecifierType], self._get_persistent_property_value("parent_specifier"))

    @parent_specifier.setter
    def parent_specifier(self, value: typing.Optional[Persistence._SpecifierType]) -> None:
        self._set_persistent_property_value("parent_specifier", value)

    @property
    def project(self) -> Project.Project:
        return typing.cast("Project.Project", self.container)

    def create_proxy(self) -> Persistence.PersistentObjectProxy[Connection]:
        return self.project.create_item_proxy(item=self)

    @property
    def item_specifier(self) -> Persistence.PersistentObjectSpecifier:
        return Persistence.PersistentObjectSpecifier(self.uuid)

    def clone(self) -> Connection:
        connection = copy.deepcopy(self)
        connection.uuid = self.uuid
        return connection

    def _property_changed(self, name: str, value: typing.Any) -> None:
        self.notify_property_changed(name)

    @property
    def parent(self) -> typing.Optional[Persistence.PersistentObject]:
        return self.__parent_reference.item

    @parent.setter
    def parent(self, parent: typing.Optional[Persistence.PersistentObject]) -> None:
        self.__parent_reference.item = parent
        self.parent_specifier = Persistence.write_persistent_specifier(parent.uuid) if parent else None

    def __parent_specifier_changed(self, name: str, d: _SpecifierType) -> None:
        self.__parent_reference.item_specifier = Persistence.read_persistent_specifier(d)


class PropertyConnection(Connection):
    """ Binds the properties of two objects together. """

    def __init__(self, source: typing.Optional[Persistence.PersistentObject] = None,
                 source_property: typing.Optional[str] = None,
                 target: typing.Optional[Persistence.PersistentObject] = None,
                 target_property: typing.Optional[str] = None, *,
                 parent: typing.Optional[Persistence.PersistentObject] = None) -> None:
        super().__init__("property-connection", parent=parent)
        self.define_property("source_specifier", Persistence.write_persistent_specifier(source.uuid) if source else None, changed=self.__source_specifier_changed, key="source_uuid", hidden=True)
        self.define_property("source_property", hidden=True)
        self.define_property("target_specifier", Persistence.write_persistent_specifier(target.uuid) if target else None, changed=self.__target_specifier_changed, key="target_uuid", hidden=True)
        self.define_property("target_property", hidden=True)
        # these are only set in persistent object context changed
        self.__binding: typing.Optional[Binding.Binding] = None
        self.__target_property_changed_listener: typing.Optional[Event.EventListener] = None
        self.__source_reference = self.create_item_reference(item=source)
        self.__target_reference = self.create_item_reference(item=target)
        # suppress messages while we're setting source or target
        self.__suppress = False
        # set up the proxies

        def configure_binding() -> None:
            if self._source and self._target:
                assert not self.__binding
                self.__binding = Binding.PropertyBinding(self._source, self.source_property)
                self.__binding.target_setter = self.__set_target_from_source
                # while reading, the data item in the display data channel will not be connected;
                # we still set its value here. when the data item becomes valid, it will update.
                self.__binding.update_target_direct(self.__binding.get_target_value())

        def release_binding() -> None:
            if self.__binding:
                self.__binding.close()
                self.__binding = None
            if self.__target_property_changed_listener:
                self.__target_property_changed_listener.close()
                self.__target_property_changed_listener = None

        self.__source_reference.on_item_registered = lambda x: configure_binding()
        self.__source_reference.on_item_unregistered = lambda x: release_binding()

        def configure_target() -> None:
            def property_changed(target: typing.Optional[Persistence.PersistentObject], property_name: str) -> None:
                if property_name == self.target_property:
                    self.__set_source_from_target(getattr(target, property_name))

            assert self.__target_property_changed_listener is None
            if self._target:
                self.__target_property_changed_listener = self._target.property_changed_event.listen(functools.partial(property_changed, self._target))
            configure_binding()

        self.__target_reference.on_item_registered = lambda x: configure_target()
        self.__target_reference.on_item_unregistered = lambda x: release_binding()

        # but set up if we were passed objects
        if source is not None:
            self.__source_reference.item = source
        if source_property:
            self.source_property = source_property
        if target is not None:
            self.__target_reference.item = target
        if target_property:
            self.target_property = target_property

        if self._target:
            configure_target()

    def close(self) -> None:
        if self.__binding:
            self.__binding.close()
            self.__binding = None
        if self.__target_property_changed_listener:
            self.__target_property_changed_listener.close()
            self.__target_property_changed_listener = None
        super().close()

    @property
    def source_specifier(self) -> typing.Optional[Persistence._SpecifierType]:
        return typing.cast(typing.Optional[Persistence._SpecifierType], self._get_persistent_property_value("source_specifier"))

    @source_specifier.setter
    def source_specifier(self, value: typing.Optional[Persistence._SpecifierType]) -> None:
        self._set_persistent_property_value("source_specifier", value)

    @property
    def target_specifier(self) -> typing.Optional[Persistence._SpecifierType]:
        return typing.cast(typing.Optional[Persistence._SpecifierType], self._get_persistent_property_value("target_specifier"))

    @target_specifier.setter
    def target_specifier(self, value: typing.Optional[Persistence._SpecifierType]) -> None:
        self._set_persistent_property_value("target_specifier", value)

    @property
    def source_property(self) -> typing.Any:
        return self._get_persistent_property_value("source_property")

    @source_property.setter
    def source_property(self, value: typing.Any) -> None:
        self._set_persistent_property_value("source_property", value)

    @property
    def target_property(self) -> typing.Any:
        return self._get_persistent_property_value("target_property")

    @target_property.setter
    def target_property(self, value: typing.Any) -> None:
        self._set_persistent_property_value("target_property", value)

    @property
    def connected_items(self) -> typing.List[typing.Optional[Persistence.PersistentObject]]:
        return [self._source, self._target]

    @property
    def _source(self) -> typing.Optional[Persistence.PersistentObject]:
        return self.__source_reference.item

    @property
    def _target(self) -> typing.Optional[Persistence.PersistentObject]:
        return self.__target_reference.item

    def __source_specifier_changed(self, name: str, d: _SpecifierType) -> None:
        self.__source_reference.item_specifier = Persistence.read_persistent_specifier(d)

    def __target_specifier_changed(self, name: str, d: _SpecifierType) -> None:
        self.__target_reference.item_specifier = Persistence.read_persistent_specifier(d)

    def __set_target_from_source(self, value: typing.Any) -> None:
        assert not self._closed
        if not self.__suppress:
            self.__suppress = True
            setattr(self._target, self.target_property, value)
            self.__suppress = False

    def __set_source_from_target(self, value: typing.Any) -> None:
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

    def __init__(self, display_item: typing.Optional[DisplayItem.DisplayItem] = None,
                 line_profile: typing.Optional[Graphics.LineProfileGraphic] = None, *,
                 parent: typing.Optional[Persistence.PersistentObject] = None) -> None:
        super().__init__("interval-list-connection", parent=parent)
        self.define_property("source_specifier", Persistence.write_persistent_specifier(display_item.uuid) if display_item else None, changed=self.__source_specifier_changed, key="source_uuid", hidden=True)
        self.define_property("target_specifier", Persistence.write_persistent_specifier(line_profile.uuid) if line_profile and line_profile.project else None, changed=self.__target_specifier_changed, key="target_uuid", hidden=True)
        # these are only set in persistent object context changed
        self.__item_inserted_event_listener: typing.Optional[Event.EventListener] = None
        self.__item_removed_event_listener: typing.Optional[Event.EventListener] = None
        self.__interval_mutated_listeners: typing.List[Event.EventListener] = list()
        self.__source_reference = self.create_item_reference(item=display_item)
        self.__target_reference = self.create_item_reference(item=line_profile)

        def detach() -> None:
            for listener in self.__interval_mutated_listeners:
                listener.close()
            self.__interval_mutated_listeners = list()

        def reattach() -> None:
            detach()
            interval_descriptors = list()
            if isinstance(self._source, DisplayItem.DisplayItem):
                for region in self._source.graphics:
                    if isinstance(region, Graphics.IntervalGraphic):
                        interval_descriptor = {"interval": region.interval, "color": "#F00"}
                        interval_descriptors.append(interval_descriptor)
                        self.__interval_mutated_listeners.append(region.property_changed_event.listen(lambda k: reattach()))
            if isinstance(self._target, Graphics.LineProfileGraphic):
                if self._target.interval_descriptors != interval_descriptors:
                    self._target.interval_descriptors = interval_descriptors

        def item_inserted(key: str, value: typing.Any, before_index: int) -> None:
            if key == "graphics" and self._target:
                reattach()

        def item_removed(key: str, value: typing.Any, index: int) -> None:
            if key == "graphics" and self._target:
                reattach()

        def source_registered(source: Persistence.PersistentObject) -> None:
            if self._source:
                self.__item_inserted_event_listener = self._source.item_inserted_event.listen(item_inserted)
                self.__item_removed_event_listener = self._source.item_removed_event.listen(item_removed)
            reattach()

        def target_registered(target: Persistence.PersistentObject) -> None:
            reattach()

        def unregistered(item: Persistence.PersistentObject) -> None:
            if self.__item_inserted_event_listener:
                self.__item_inserted_event_listener.close()
                self.__item_inserted_event_listener = None
            if self.__item_removed_event_listener:
                self.__item_removed_event_listener.close()
                self.__item_removed_event_listener = None

        self.__source_reference.on_item_registered = source_registered
        self.__source_reference.on_item_unregistered = unregistered

        self.__target_reference.on_item_registered = target_registered
        self.__target_reference.on_item_unregistered = unregistered

        # but setup if we were passed objects
        if display_item is not None:
            self.__source_reference.item = display_item
            source_registered(display_item)
        if line_profile is not None:
            self.__target_reference.item = line_profile
            target_registered(line_profile)

    @property
    def source_specifier(self) -> typing.Optional[Persistence._SpecifierType]:
        return typing.cast(typing.Optional[Persistence._SpecifierType], self._get_persistent_property_value("source_specifier"))

    @source_specifier.setter
    def source_specifier(self, value: typing.Optional[Persistence._SpecifierType]) -> None:
        self._set_persistent_property_value("source_specifier", value)

    @property
    def target_specifier(self) -> typing.Optional[Persistence._SpecifierType]:
        return typing.cast(typing.Optional[Persistence._SpecifierType], self._get_persistent_property_value("target_specifier"))

    @target_specifier.setter
    def target_specifier(self, value: typing.Optional[Persistence._SpecifierType]) -> None:
        self._set_persistent_property_value("target_specifier", value)

    @property
    def connected_items(self) -> typing.List[typing.Optional[Persistence.PersistentObject]]:
        return [self._source, self._target]

    @property
    def _source(self) -> typing.Optional[Persistence.PersistentObject]:
        return self.__source_reference.item

    @property
    def _target(self) -> typing.Optional[Persistence.PersistentObject]:
        return self.__target_reference.item

    def __source_specifier_changed(self, name: str, d: _SpecifierType) -> None:
        self.__source_reference.item_specifier = Persistence.read_persistent_specifier(d)

    def __target_specifier_changed(self, name: str, d: _SpecifierType) -> None:
        self.__target_reference.item_specifier = Persistence.read_persistent_specifier(d)


def connection_factory(lookup_id: typing.Callable[[str], str]) -> typing.Optional[Connection]:
    build_map = {
        "property-connection": PropertyConnection,
        "interval-list-connection": IntervalListConnection,
    }
    type = lookup_id("type")
    return build_map[type]() if type in build_map else None
