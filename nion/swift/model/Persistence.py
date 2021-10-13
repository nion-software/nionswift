"""
A collection of persistence classes.
"""
from __future__ import annotations

# standard libraries
import abc
import copy
import datetime
import logging
import numpy
import numpy.typing
import re
import typing
import uuid
import weakref

# third party libraries
# None

# local libraries
from nion.utils import Converter
from nion.utils import Event
from nion.utils import Observable
from nion.swift.model import Changes
from nion.swift.model import Utility


PersistentDictType = typing.Dict[str, typing.Any]

_NDArray = numpy.typing.NDArray[typing.Any]


class PersistentContainerType(typing.Protocol):
    def insert_item(self, name: str, before_index: int, item: PersistentObject) -> None: ...
    def remove_item(self, name: str, item: PersistentObject) -> None: ...


_PropertyMakeFn = typing.Callable[[], typing.Any]
_PropertyValidateFn = typing.Callable[[typing.Any], typing.Any]
_PropertyChangedFn = typing.Callable[[str, typing.Any], None]
_PropertyReadFn = typing.Callable[["PersistentProperty", PersistentDictType], typing.Any]
_PropertyWriterFn = typing.Callable[["PersistentProperty", PersistentDictType, typing.Any], None]
_PropertyConverterType = Converter.ConverterLike[typing.Any, typing.Any]  # Utility.CleanValue?
_PersistentObjectFactoryFn = typing.Callable[[typing.Callable[[str], str]], typing.Optional["PersistentObject"]]

class PersistentProperty:

    """
        Represents a persistent property.

        converter converts from value to json value
    """

    def __init__(self, name: str, value: typing.Any = None, make: typing.Optional[_PropertyMakeFn] = None,
                 read_only: bool = False, hidden: bool = False, recordable: bool = True,
                 validate: typing.Optional[_PropertyValidateFn] = None,
                 converter: typing.Optional[_PropertyConverterType] = None,
                 changed: typing.Optional[_PropertyChangedFn] = None, key: typing.Optional[str] = None,
                 reader: typing.Optional[_PropertyReadFn] = None,
                 writer: typing.Optional[_PropertyWriterFn] = None) -> None:
        super().__init__()
        self.name = name
        self.key = key if key else name
        self.value: typing.Any = value
        self.make = make
        self.read_only = read_only
        self.hidden = hidden
        self.recordable = recordable
        self.validate = validate
        self.converter = converter
        self.reader = reader
        self.writer = writer
        self.convert_get_fn = typing.cast(typing.Callable[[Utility.DirtyValue], Utility.CleanValue], converter.convert if converter else copy.deepcopy)  # optimization
        self.convert_set_fn = typing.cast(typing.Callable[[Utility.CleanValue], Utility.DirtyValue], converter.convert_back if converter else lambda value: value)  # optimization
        self.changed = changed

    def close(self) -> None:
        self.make = None
        self.validate = None
        self.converter = None
        self.reader = None
        self.writer = None
        self.convert_get_fn = typing.cast(typing.Any, None)
        self.convert_set_fn = typing.cast(typing.Any, None)
        self.changed = None

    def set_value(self, value: typing.Any) -> None:
        if self.validate:
            value = self.validate(value)
        else:
            value = copy.deepcopy(value)
        self.value = value
        if self.changed:
            self.changed(self.name, value)

    @property
    def json_value(self) -> Utility.CleanValue:
        return self.convert_get_fn(self.value)

    @json_value.setter
    def json_value(self, json_value: Utility.CleanValue) -> None:
        self.set_value(self.convert_set_fn(json_value))

    def read_from_dict(self, properties: PersistentDictType) -> None:
        if self.reader:
            value = self.reader(self, properties)
            if value is not None:
                self.set_value(value)
        else:
            if self.key in properties:
                if self.make:
                    value = self.make()
                    value.read_dict(properties[self.key])
                    self.set_value(value)
                else:
                    self.json_value = properties[self.key]

    def write_to_dict(self, properties: PersistentDictType) -> None:
        if self.writer:
            self.writer(self, properties, self.value)
        else:
            if self.make:
                value = self.value
                if value is not None:
                    value_dict = value.write_dict()
                    properties[self.key] = value_dict
                else:
                    properties.pop(self.key, None)  # remove key
            else:
                value = self.json_value
                if value is not None:
                    properties[self.key] = value
                else:
                    properties.pop(self.key, None)  # remove key


class PersistentPropertySpecial(PersistentProperty):

    def __init__(self, name: str, value: typing.Any = None, make: typing.Optional[_PropertyMakeFn] = None,
                 read_only: bool = False, hidden: bool = False, recordable: bool = True,
                 validate: typing.Optional[_PropertyValidateFn] = None,
                 converter: typing.Optional[_PropertyConverterType] = None,
                 changed: typing.Optional[_PropertyChangedFn] = None, key: typing.Optional[str] = None,
                 reader: typing.Optional[_PropertyReadFn] = None,
                 writer: typing.Optional[_PropertyWriterFn] = None) -> None:
        super().__init__(name, value, make, read_only, hidden, recordable, validate, converter, changed, key, reader, writer)
        self.__value = value

    @property
    def value(self) -> typing.Any:
        return copy.deepcopy(self.__value)

    @value.setter
    def value(self, value: typing.Any) -> None:
        self.__value = value


class PersistentItem:

    def __init__(self, name: str, factory: _PersistentObjectFactoryFn,
                 item_changed: typing.Optional[typing.Callable[[str, typing.Any, typing.Any], None]] = None,
                 hidden: bool = False) -> None:
        super().__init__()
        self.name = name
        self.factory = factory
        self.item_changed = item_changed
        self.hidden = hidden
        self.value: typing.Any = None
        self.persistent_object_context: typing.Optional[PersistentObjectContext] = None

    def close(self) -> None:
        self.item_changed = None


class PersistentRelationship:

    def __init__(self, name: str,
                 factory: _PersistentObjectFactoryFn,
                 insert: typing.Optional[typing.Callable[[str, int, typing.Any], None]] = None,
                 remove: typing.Optional[typing.Callable[[str, int, typing.Any], None]] = None,
                 key: typing.Optional[str] = None,
                 hidden: bool = False) -> None:
        super().__init__()
        self.name = name
        self.factory = factory
        self.insert = insert
        self.remove = remove
        self.key = key
        self.hidden = hidden
        self.values: typing.List[PersistentObject] = list()
        self.index: typing.Dict[uuid.UUID, PersistentObject] = dict()

    def close(self) -> None:
        self.insert = None
        self.remove = None

    @property
    def storage_key(self) -> str:
        return self.key if self.key else self.name


class PersistentStorageInterface(abc.ABC):

    @abc.abstractmethod
    def get_storage_properties(self) -> typing.Optional[PersistentDictType]: ...

    @abc.abstractmethod
    def get_properties(self, object: typing.Any) -> typing.Optional[PersistentDictType]: ...

    @abc.abstractmethod
    def insert_item(self, parent: PersistentObject, name: str, before_index: int, item: PersistentObject) -> None: ...

    @abc.abstractmethod
    def remove_item(self, parent: PersistentObject, name: str, index: int, item: PersistentObject) -> None: ...

    @abc.abstractmethod
    def set_item(self, parent: PersistentObject, name: str, item: PersistentObject) -> None: ...

    @abc.abstractmethod
    def set_property(self, object: PersistentObject, name: str, value: typing.Any) -> None: ...

    @abc.abstractmethod
    def clear_property(self, object: PersistentObject, name: str) -> None: ...

    @abc.abstractmethod
    def read_external_data(self, item: PersistentObject, name: str) -> typing.Any: ...

    @abc.abstractmethod
    def write_external_data(self, item: PersistentObject, name: str, value: _NDArray) -> None: ...

    @abc.abstractmethod
    def reserve_external_data(self, item: PersistentObject, name: str, data_shape: typing.Tuple[int, ...], data_dtype: numpy.typing.DTypeLike) -> None: ...

    @abc.abstractmethod
    def enter_write_delay(self, object: PersistentObject) -> None: ...

    @abc.abstractmethod
    def exit_write_delay(self, object: PersistentObject) -> None: ...

    @abc.abstractmethod
    def is_write_delayed(self, item: PersistentObject) -> bool: ...

    @abc.abstractmethod
    def rewrite_item(self, item: PersistentObject) -> None: ...


class PersistentObjectContext:
    """Provides a common context to track available persistent objects.

    All objects participating in this context should register and unregister themselves with this context at appropriate
    times.

    Other objects can listen to the registration_event to know when a specific object is registered or unregistered.
    """

    def __init__(self) -> None:
        # Python 3.9+: weakref typing
        self.__objects: typing.Dict[PersistentObjectSpecifier, typing.Any] = dict()
        self.registration_event = Event.Event()
        self.__registration_changed_map: typing.Dict[uuid.UUID, typing.Dict[typing.Any, typing.Callable[[typing.Optional[PersistentObject], typing.Optional[PersistentObject]], None]]] = dict()

    def unregister_registration_changed_fn(self, uuid_: uuid.UUID, key: typing.Any) -> None:
        registration_changed_key_map = self.__registration_changed_map.get(uuid_, dict())
        registration_changed_key_map.pop(key)
        if not registration_changed_key_map:
            self.__registration_changed_map.pop(uuid_, None)

    def register_registration_changed_fn(self, uuid_: uuid.UUID, key: typing.Any, registration_changed_fn: typing.Callable[[typing.Optional[PersistentObject], typing.Optional[PersistentObject]], None]) -> None:
        registration_changed_key_map = self.__registration_changed_map.setdefault(uuid_, dict())
        registration_changed_key_map[key] = registration_changed_fn

    def register(self, object: PersistentObject) -> None:
        # print(f"register {object} {item_specifier.write()} {len(self.__objects) + 1}")
        # assert item_specifier not in self.__objects
        item_specifier = object.item_specifier
        self.__objects[item_specifier] = weakref.ref(object)
        self.registration_event.fire(object, None)
        registration_changed_key_map = self.__registration_changed_map.get(object.uuid, dict())
        for registration_changed_fn in list(registration_changed_key_map.values()):
            if callable(registration_changed_fn):
                registration_changed_fn(object, None)

    def unregister(self, object: PersistentObject) -> None:
        # print(f"unregister {object} {item_specifier.write()} {len(self.__objects) - 1}")
        # assert item_specifier in self.__objects
        item_specifier = object.item_specifier
        if item_specifier in self.__objects:
            self.__objects.pop(item_specifier)
            self.registration_event.fire(None, object)
            registration_changed_key_map = self.__registration_changed_map.get(object.uuid, dict())
            for registration_changed_fn in list(registration_changed_key_map.values()):
                if callable(registration_changed_fn):
                    registration_changed_fn(None, object)

    def get_registered_object(self, item_specifier: PersistentObjectSpecifier) -> typing.Optional[PersistentObject]:
        object_weakref = self.__objects.get(item_specifier, None)
        return object_weakref() if object_weakref else None

    def create_item_reference(self, item_uuid: typing.Optional[uuid.UUID] = None, item: typing.Optional[PersistentObject] = None) -> PersistentObjectReference:
        item_specifier = PersistentObjectSpecifier(item_uuid=item_uuid) if item_uuid else None
        return PersistentObjectReference(self, item_specifier, item)


_SpecifierType = typing.Union[typing.Mapping[str, typing.Any], str, uuid.UUID]
_SpecifierDictType = typing.Union[PersistentDictType, str, uuid.UUID]


class PersistentObjectSpecifier:

    def __init__(self, *, item: typing.Optional[PersistentObject] = None, item_uuid: typing.Optional[uuid.UUID] = None) -> None:
        self.__item_uuid = item.uuid if item else item_uuid
        assert (self.__item_uuid is None) or isinstance(self.__item_uuid, uuid.UUID)

    def __hash__(self) -> typing.Any:
        return hash(self.__item_uuid)

    def __eq__(self, other: typing.Any) -> bool:
        if isinstance(other, self.__class__):
            return self.__item_uuid == other.__item_uuid
        return False

    @property
    def item_uuid(self) -> typing.Optional[uuid.UUID]:
        return self.__item_uuid

    def write(self) -> typing.Optional[_SpecifierType]:
        if self.__item_uuid:
            return str(self.__item_uuid)
        return None

    @staticmethod
    def read(d: typing.Optional[_SpecifierType]) -> typing.Optional[PersistentObjectSpecifier]:
        if isinstance(d, str):
            return PersistentObjectSpecifier(item_uuid=uuid.UUID(d))
        elif isinstance(d, uuid.UUID):
            return PersistentObjectSpecifier(item_uuid=d)
        elif isinstance(d, dict) and "item_uuid" in d:
            return PersistentObjectSpecifier(item_uuid=uuid.UUID(d["item_uuid"]))
        elif isinstance(d, dict) and "uuid" in d:
            return PersistentObjectSpecifier(item_uuid=uuid.UUID(d["uuid"]))
        return None


class PersistentObjectProxy:
    count = 0  # useful for detecting leaks in tests

    def __init__(self, persistent_object: PersistentObject, item_specifier: typing.Optional[PersistentObjectSpecifier], item: typing.Optional[PersistentObject]) -> None:
        PersistentObjectProxy.count += 1
        self.__persistent_object = persistent_object
        self.__item_specifier = item_specifier if item_specifier else PersistentObjectSpecifier(item=item) if item else None
        self.__item = item
        self.__persistent_object_context: typing.Optional[PersistentObjectContext] = None
        self.__registered_change_uuid: typing.Optional[uuid.UUID] = None
        self.on_item_registered: typing.Optional[typing.Callable[[PersistentObject], None]] = None
        self.on_item_unregistered: typing.Optional[typing.Callable[[PersistentObject], None]] = None
        self.__persistent_object_context_changed_listener = persistent_object.persistent_object_context_changed_event.listen(self.__persistent_object_context_changed)
        self.__persistent_object_context_changed()

    def close(self) -> None:
        if self.__persistent_object_context_changed_listener:
            self.__persistent_object_context_changed_listener.close()
            self.__persistent_object_context_changed_listener = typing.cast(typing.Any, None)
        self.__item = None
        self.__item_specifier = None
        self.__update_persistent_object_context()
        self.__persistent_object = typing.cast(typing.Any, None)
        self.on_item_registered = None
        self.on_item_unregistered = None
        PersistentObjectProxy.count -= 1

    @property
    def item(self) -> typing.Optional[PersistentObject]:
        return self.__item

    @item.setter
    def item(self, item: typing.Optional[PersistentObject]) -> None:
        self.__item = item
        self.__item_specifier = PersistentObjectSpecifier(item=item) if item else None
        self.__persistent_object_context_changed()

    @property
    def item_specifier(self) -> typing.Optional[PersistentObjectSpecifier]:
        return self.__item_specifier

    @item_specifier.setter
    def item_specifier(self, item_specifier: PersistentObjectSpecifier) -> None:
        self.__item_specifier = item_specifier
        self.__item = None
        self.__persistent_object_context_changed()

    def __update_persistent_object_context(self) -> None:
        if self.__persistent_object_context:
            if self.__registered_change_uuid:
                self.__persistent_object_context.unregister_registration_changed_fn(self.__registered_change_uuid, self)
                self.__registered_change_uuid = None
            self.__persistent_object_context = None
        if self.__item_specifier and self.__persistent_object.persistent_object_context:
            self.__persistent_object_context = self.__persistent_object.persistent_object_context
            self.__registered_change_uuid = self.__item_specifier.item_uuid
            if self.__registered_change_uuid:
                self.__persistent_object_context.register_registration_changed_fn(self.__registered_change_uuid, self, self.__change_registration)

    def __change_registration(self, registered_object: typing.Optional[PersistentObject], unregistered_object: typing.Optional[PersistentObject]) -> None:
        if registered_object and not self.__item and self.__item_specifier and registered_object.uuid == self.__item_specifier.item_uuid:
            if self.__persistent_object.persistent_object_context:
                item = self.__persistent_object.persistent_object_context.get_registered_object(self.__item_specifier)
                if item:
                    self.__item = item
                    if callable(self.on_item_registered):
                        self.on_item_registered(registered_object)
        if unregistered_object and unregistered_object == self.__item:
            self.__item = None
            if callable(self.on_item_unregistered):
                self.on_item_unregistered(unregistered_object)

    def __persistent_object_context_changed(self) -> None:
        if self.__persistent_object.persistent_object_context:
            if self.__item_specifier and not self.__item:
                item = self.__persistent_object.persistent_object_context.get_registered_object(self.__item_specifier)
                if item:
                    self.__change_registration(item, None)
        self.__update_persistent_object_context()


class PersistentObjectReference:
    count = 0  # useful for detecting leaks in tests

    def __init__(self, persistent_object_context: typing.Optional[PersistentObjectContext], item_specifier: typing.Optional[PersistentObjectSpecifier], item: typing.Optional[PersistentObject]) -> None:
        PersistentObjectReference.count += 1
        self.__persistent_object_context: typing.Optional[PersistentObjectContext] = None
        self.__item_specifier = item_specifier if item_specifier else PersistentObjectSpecifier(item=item) if item else None
        self.__item = item
        self.__registered_change_uuid: typing.Optional[uuid.UUID] = None
        self.on_item_registered: typing.Optional[typing.Callable[[PersistentObject], None]] = None
        self.on_item_unregistered: typing.Optional[typing.Callable[[PersistentObject], None]] = None
        self.set_persistent_object_context(persistent_object_context)

    def close(self) -> None:
        self.set_persistent_object_context(None)
        self.__item = None
        self.__item_specifier = None
        self.__persistent_object = None
        self.on_item_registered = None
        self.on_item_unregistered = None
        PersistentObjectReference.count -= 1

    @property
    def item(self) -> typing.Optional[PersistentObject]:
        return self.__item

    @item.setter
    def item(self, item: typing.Optional[PersistentObject]) -> None:
        self.__item = item
        self.__item_specifier = PersistentObjectSpecifier(item=item) if item else None
        self.__persistent_object_context_changed()

    @property
    def item_specifier(self) -> typing.Optional[PersistentObjectSpecifier]:
        return self.__item_specifier

    @item_specifier.setter
    def item_specifier(self, item_specifier: PersistentObjectSpecifier) -> None:
        self.__item_specifier = item_specifier
        self.__item = None
        self.__persistent_object_context_changed()

    def set_persistent_object_context(self, persistent_object_context: typing.Optional[PersistentObjectContext]) -> None:
        if self.__persistent_object_context:
            if self.__registered_change_uuid:  # use 2nd line to satisfy PyCharm type checker
                self.__persistent_object_context.unregister_registration_changed_fn(self.__registered_change_uuid, self)
                self.__registered_change_uuid = None
        self.__persistent_object_context = persistent_object_context
        if self.__persistent_object_context:
            if self.__item_specifier:
                item_uuid = self.__item_specifier.item_uuid
                assert item_uuid is not None
                self.__registered_change_uuid = item_uuid
                self.__persistent_object_context.register_registration_changed_fn(item_uuid, self, self.__change_registration)
        self.__persistent_object_context_changed()

    def __change_registration(self, registered_object: typing.Optional[PersistentObject], unregistered_object: typing.Optional[PersistentObject]) -> None:
        if registered_object and not self.__item and self.__item_specifier and registered_object.uuid == self.__item_specifier.item_uuid:
            if self.__persistent_object_context:
                item = self.__persistent_object_context.get_registered_object(self.__item_specifier)
                if item:
                    self.__item = item
                    if callable(self.on_item_registered):
                        self.on_item_registered(registered_object)
        if unregistered_object and unregistered_object == self.__item:
            self.__item = None
            if callable(self.on_item_unregistered):
                self.on_item_unregistered(unregistered_object)

    def __persistent_object_context_changed(self) -> None:
        if self.__persistent_object_context:
            if self.__item_specifier and not self.__item:
                item = self.__persistent_object_context.get_registered_object(self.__item_specifier)
                if item:
                    self.__change_registration(item, None)


class PersistentObjectParent:
    """ Track the parent of a persistent object. """

    def __init__(self, parent: PersistentObject, relationship_name: typing.Optional[str] = None, item_name: typing.Optional[str] = None) -> None:
        self.__weak_parent = weakref.ref(parent)
        self.relationship_name = relationship_name
        self.item_name = item_name

    @property
    def parent(self) -> typing.Optional[PersistentObject]:
        return self.__weak_parent()


class PersistentObject(Observable.Observable):
    """
        Base class for objects being stored in a PersistentObjectContext.

        Subclasses can define properties, items, and relationships. Changes to those items will
        be persisted to the PersistentObjectContext.

        Keeps track of modified field automatically.

        Properties are single values, items are a one-to-one between objects, relationships are
        one-to-many between objects.

        Properties can have validators, converters, change notifications, and more.
        They are created using the define_property method.

        Items have set notifications and more. They are created using the
        define_item method.

        Relationships have change notifications and more. They are created using
        the define_relationship method.

        Subclasses can set the uuid after init. It should not be changed at other times.

        The persistent_object_context property must be set explicitly for top level objects of the
        PersistentObjectContext. Objects contained in the items and relationships will be have their
        persistent_object_context managed when they are inserted into or removed from another persistent object.

        It is an error to add an object as an item or relationship more than once. Items can be
        removed and added again, though.

        Objects must be able to read from and write themselves to a dict.

        The persistent_object_context property will be valid after (but not during) reading.

        After reading, an object may immediately update itself to a newer version using the persistent object
        context.
    """
    count = 0  # useful for detecting leaks in tests

    def __init__(self) -> None:
        super().__init__()
        PersistentObject.count += 1
        self.__type: typing.Optional[str] = None
        self.__properties: typing.Dict[str, PersistentProperty] = dict()
        self.__items: typing.Dict[str, PersistentItem] = dict()
        self.__relationships: typing.Dict[str, PersistentRelationship] = dict()
        # Python 3.9+: typed weakref
        self.__container_weak_ref: typing.Optional[typing.Any] = None
        self._closed = False
        self.about_to_close_event = Event.Event()
        self._about_to_be_removed = False
        self.about_to_be_removed_event = Event.Event()
        self._is_reading = False
        self.__persistent_object_context: typing.Optional[PersistentObjectContext] = None
        # uuid as a property is too slow, so make it direct
        self.uuid = uuid.uuid4()
        self.__modified_count = 0
        self.modified_state = 0
        self.__modified = datetime.datetime.utcnow()
        self.persistent_object_parent: typing.Optional[PersistentObjectParent] = None
        self.__persistent_dict: typing.Optional[PersistentDictType] = None
        self.__persistent_storage: typing.Optional[PersistentStorageInterface] = None
        self.persistent_object_context_changed_event = Event.Event()
        self.__item_references: typing.List[PersistentObjectReference] = list()

    def close(self) -> None:
        self.about_to_close_event.fire()
        assert not self._closed
        self._closed = True
        for item_reference in self.__item_references:
            item_reference.close()
        self.close_items()
        self.close_relationships()
        self.__container_weak_ref = None
        self.__persistent_object_context = None
        self.undefine_properties()
        self.undefine_items()
        self.undefine_relationships()
        PersistentObject.count -= 1

    def __deepcopy__(self, memo: typing.Dict[typing.Any, typing.Any]) -> PersistentObject:
        deepcopy = self.__class__()
        deepcopy.deepcopy_from(self, memo)
        memo[id(self)] = deepcopy
        return deepcopy

    def deepcopy_from(self, item: PersistentObject, memo: typing.Dict[typing.Any, typing.Any]) -> None:
        for key in self.__properties.keys():
            value = item._get_persistent_property_value(key)
            new_value = copy.deepcopy(value)
            self._set_persistent_property_value(key, new_value)
        for key in self.__items.keys():
            self.set_item(key, copy.deepcopy(getattr(item, key)))
        for key in self.__relationships.keys():
            for child_item in getattr(item, key):
                self.append_item(key, copy.deepcopy(child_item, memo))

    @property
    def container(self) -> typing.Optional[PersistentObject]:
        return self.__container_weak_ref() if self.__container_weak_ref else None

    def insert_model_item(self, container: PersistentContainerType, name: str, before_index: int, item: PersistentObject) -> None:
        """Insert a model item. Let this item's container do it if possible; otherwise do it directly.

        Passing responsibility to this item's container allows the library to easily track dependencies.
        However, if this item isn't yet in the library hierarchy, then do the operation directly.
        """
        if self.container:
            self.container.insert_model_item(container, name, before_index, item)
        else:
            container.insert_item(name, before_index, item)

    def remove_model_item(self, container: PersistentContainerType, name: str, item: PersistentObject, *, safe: bool = False) -> Changes.UndeleteLog:
        """Remove a model item. Let this item's container do it if possible; otherwise do it directly.

        Passing responsibility to this item's container allows the library to easily track dependencies.
        However, if this item isn't yet in the library hierarchy, then do the operation directly.
        """
        if self.container:
            return self.container.remove_model_item(container, name, item, safe=safe)
        else:
            container.remove_item(name, item)
            return Changes.UndeleteLog()

    def about_to_be_inserted(self, container: PersistentObject) -> None:
        assert self.__container_weak_ref is None
        self.__container_weak_ref = weakref.ref(container)

    def about_to_be_removed(self, container: PersistentObject) -> None:
        # called before close and before item is removed from its container
        for item in self.__items.values():
            item.value.about_to_be_removed(self)
        for relationship in self.__relationships.values():
            for relationship_item in reversed(relationship.values):
                relationship_item.about_to_be_removed(self)
        self.about_to_be_removed_event.fire()
        assert not self._about_to_be_removed
        self._about_to_be_removed = True
        self.__container_weak_ref = None

    @property
    def item_specifier(self) -> PersistentObjectSpecifier:
        return PersistentObjectSpecifier(item_uuid=self.uuid)

    def define_root_context(self) -> None:
        """Define this item to be the root context."""
        self.__persistent_object_context = PersistentObjectContext()

    def set_storage_system(self, storage_system: PersistentStorageInterface) -> None:
        """Set the storage system for this item."""
        self.persistent_dict = storage_system.get_storage_properties()
        self.persistent_storage = storage_system

    def update_storage_system(self) -> None:
        """Update the storage system properties by re-reading from storage.

        Useful when reloading.
        """
        assert self.persistent_storage
        self.persistent_dict = self.persistent_storage.get_storage_properties()

    def update_item_context(self, item: PersistentObject) -> None:
        """Update the context on the item."""
        item.persistent_object_context = self.persistent_object_context

    def persistent_object_context_changed(self) -> None:
        """ Subclasses can override this to be notified when the persistent object context changes. """
        pass

    @property
    def persistent_object_context(self) -> typing.Optional[PersistentObjectContext]:
        """ Return the persistent object context. """
        return self.__persistent_object_context

    @persistent_object_context.setter
    def persistent_object_context(self, persistent_object_context: PersistentObjectContext) -> None:
        """ Set the persistent object context and propagate it to contained objects. """
        assert self.__persistent_object_context is None or persistent_object_context is None  # make sure persistent object context is handled cleanly
        old_persistent_object_context = self.__persistent_object_context
        self.__persistent_object_context = persistent_object_context
        for item_reference in self.__item_references:
            item_reference.set_persistent_object_context(persistent_object_context)
        for item in self.__items.values():
            if item.value:
                item.value.persistent_object_context = persistent_object_context
        for relationship in self.__relationships.values():
            for relationship_item in relationship.values:
                if relationship_item:
                    relationship_item.persistent_object_context = persistent_object_context
        if old_persistent_object_context:
            old_persistent_object_context.unregister(self)
        if persistent_object_context:
            self.__item_specifier = self.item_specifier
            persistent_object_context.register(self)
        self.persistent_object_context_changed()
        self.persistent_object_context_changed_event.fire()

    @property
    def persistent_dict(self) -> typing.Optional[PersistentDictType]:
        return self.__persistent_dict

    @persistent_dict.setter
    def persistent_dict(self, persistent_dict: typing.Optional[PersistentDictType]) -> None:
        self.__persistent_dict = persistent_dict
        for key in self.__items.keys():
            item = self.__items[key].value
            if item:
                item.persistent_dict = self._get_item_persistent_dict(item, key) if persistent_dict is not None else None
                item.persistent_storage = self.persistent_storage if persistent_dict is not None else None
        for key in self.__relationships.keys():
            for index, item in enumerate(self.__relationships[key].values):
                item.persistent_dict = self._get_relationship_persistent_dict(item, key, index) if persistent_dict is not None else None
                item.persistent_storage = self.persistent_storage if persistent_dict is not None else None

    @property
    def persistent_storage(self) -> typing.Optional[PersistentStorageInterface]:
        return self.__persistent_storage

    @persistent_storage.setter
    def persistent_storage(self, persistent_storage: PersistentStorageInterface) -> None:
        self.__persistent_storage = persistent_storage
        for key in self.__items.keys():
            item = self.__items[key].value
            if item:
                item.persistent_storage = persistent_storage
        for key in self.__relationships.keys():
            for index, item in enumerate(self.__relationships[key].values):
                item.persistent_storage = persistent_storage

    def _get_item_persistent_dict(self, item: typing.Any, key: str) -> typing.Optional[PersistentDictType]:
        return self.persistent_dict[key] if self.persistent_dict is not None else None

    def _get_relationship_persistent_dict(self, item: PersistentObject, key: str, index: int) -> typing.Optional[PersistentDictType]:
        return self.persistent_dict[key][index] if self.persistent_dict is not None else None

    def _get_relationship_persistent_dict_by_uuid(self, item: PersistentObject, key: str) -> typing.Optional[PersistentDictType]:
        if self.persistent_dict:
            item_uuid = str(item.uuid)
            for item_d in self.persistent_dict.get(key, list()):
                # if uuid.UUID(item_d.get("uuid")) == item.uuid:
                #     return item_d
                if item_d.get("uuid") == item_uuid:  # a little dangerous, comparing the uuid str's, significantly faster
                    return typing.cast(PersistentDictType, item_d)
        return None

    def define_type(self, type: str) -> None:
        self.__type = type

    def define_property(self, name: str, value: typing.Any = None, make: typing.Optional[_PropertyMakeFn] = None,
                        read_only: bool = False, hidden: bool = False, recordable: bool = True,
                        copy_on_read: bool = False, validate: typing.Optional[_PropertyValidateFn] = None,
                        converter: typing.Optional[_PropertyConverterType] = None,
                        changed: typing.Optional[_PropertyChangedFn] = None, key: typing.Optional[str] = None,
                        reader: typing.Optional[_PropertyReadFn] = None,
                        writer: typing.Optional[_PropertyWriterFn] = None) -> None:
        """ key is what is stored on disk; name is what is used when accessing the property from code. """
        if copy_on_read:
            self.__properties[name] = PersistentPropertySpecial(name, value, make, read_only, hidden, recordable, validate, converter, changed, key, reader, writer)
        else:
            self.__properties[name] = PersistentProperty(name, value, make, read_only, hidden, recordable, validate, converter, changed, key, reader, writer)

    def define_item(self, name: str, factory: _PersistentObjectFactoryFn,
                    item_changed: typing.Optional[typing.Callable[[str, typing.Any, typing.Any], None]] = None,
                    hidden: bool = False) -> None:
        self.__items[name] = PersistentItem(name, factory, item_changed, hidden)

    def define_relationship(self, name: str,
                            factory: _PersistentObjectFactoryFn,
                            insert: typing.Optional[typing.Callable[[str, int, typing.Any], None]] = None,
                            remove: typing.Optional[typing.Callable[[str, int, typing.Any], None]] = None,
                            key: typing.Optional[str] = None, hidden: bool = False) -> None:
        self.__relationships[name] = PersistentRelationship(name, factory, insert, remove, key, hidden)

    def close_items(self) -> None:
        for item in self.__items.values():
            if item.value:
                if self.persistent_object_context:  # only clear it if it's been set
                    item.value.persistent_object_context = None
                item.value.close()

    def close_relationships(self) -> None:
        for relationship in self.__relationships.values():
            for item in reversed(relationship.values):
                if item:
                    if self.persistent_object_context:  # only clear it if it's been set
                        item.persistent_object_context = None
                    item.close()

    def undefine_properties(self) -> None:
        for property in self.__properties.values():
            property.close()
        self.__properties.clear()

    def undefine_items(self) -> None:
        for item in self.__items.values():
            item.close()
        self.__items.clear()

    def undefine_relationships(self) -> None:
        for relationship in self.__relationships.values():
            relationship.close()
        self.__relationships.clear()

    def get_storage_properties(self) -> typing.Optional[PersistentDictType]:
        """ Return a copy of the properties for the object as a dict. """
        assert self.persistent_storage
        return copy.deepcopy(self.persistent_storage.get_properties(self))

    @property
    def property_names(self) -> typing.Sequence[str]:
        return list(self.__properties.keys())

    @property
    def key_names(self) -> typing.Sequence[str]:
        return [property.key for property in self.__properties.values()]

    @property
    def type(self) -> str:
        return self.__type or str()

    @property
    def modified(self) -> datetime.datetime:
        return self.__modified

    @property
    def modified_count(self) -> int:
        return self.__modified_count

    def _set_modified(self, modified: datetime.datetime) -> None:
        # for testing
        self.__update_modified(modified)
        if self.persistent_object_context:
            self.property_changed("uuid", str(self.uuid))  # dummy write

    @property
    def item_names(self) -> typing.Sequence[str]:
        return list(self.__items.keys())

    @property
    def relationship_names(self) -> typing.Sequence[str]:
        return list(self.__relationships.keys())

    def begin_reading(self) -> None:
        self._is_reading = True

    def read_from_dict(self, properties: PersistentDictType) -> None:
        """ Read from a dict. """
        # uuid is handled specially for performance reasons
        if "uuid" in properties:
            self.uuid = uuid.UUID(properties["uuid"])
        if "modified" in properties:
            self.__modified = datetime.datetime(*list(map(int, re.split('[^\d]', properties["modified"]))))  # type: ignore
        # iterate the defined properties
        for key in self.__properties.keys():
            property = self.__properties[key]
            property.read_from_dict(properties)
        for key in self.__items.keys():
            item_dict = typing.cast(PersistentDictType, properties.get(key))
            if item_dict:
                factory = self.__items[key].factory
                # the object has not been constructed yet, but we needs its
                # type or id to construct it. so we need to look it up by key/index/name.
                # to minimize the interface to the factory methods, just pass a closure
                # which looks up by name.
                def lookup_id(name: str, default: typing.Optional[str] = None) -> str:
                    return item_dict.get(name, default)

                item = factory(lookup_id)
                if item is None:
                    logging.debug("Unable to read %s", key)
                assert item is not None
                # read the item from the dict
                item.begin_reading()
                item.read_from_dict(item_dict)
                self.__set_item(key, item)
                item.persistent_dict = self._get_item_persistent_dict(item, key)
                item.persistent_storage = self.persistent_storage
        for key in self.__relationships.keys():
            storage_key = self.__relationships[key].storage_key
            for item_dict in properties.get(storage_key, list()):
                factory = self.__relationships[key].factory
                # the object has not been constructed yet, but we needs its
                # type or id to construct it. so we need to look it up by key/index/name.
                # to minimize the interface to the factory methods, just pass a closure
                # which looks up by name.
                def lookup_id(name: str, default: typing.Optional[str] = None) -> str:
                    return item_dict.get(name, default)

                item = factory(lookup_id)
                if item is None:
                    logging.debug("Unable to read %s", key)
                assert item is not None
                # read the item from the dict
                item.begin_reading()
                item.read_from_dict(item_dict)
                # insert it into the relationship dict
                before_index = len(self.__relationships[key].values)
                self.load_item(key, before_index, item)

    def finish_reading(self) -> None:
        for key in self.__items.keys():
            item = self.__items[key].value
            if item:
                item.finish_reading()
        for key in self.__relationships.keys():
            for item in self.__relationships[key].values:
                item.finish_reading()
        self._is_reading = False

    def write_to_dict(self) -> PersistentDictType:
        """ Write the object to a dict and return it. """
        properties: PersistentDictType = dict()
        if self.__type:
            properties["type"] = self.__type
        properties["uuid"] = str(self.uuid)
        for key in self.__properties.keys():
            property = self.__properties[key]
            property.write_to_dict(properties)
        for key in self.__items.keys():
            item = self.__items[key].value
            if item:
                properties[key] = item.write_to_dict()
        for key in self.__relationships.keys():
            storage_key = self.__relationships[key].storage_key
            items_list = properties.setdefault(storage_key, list())
            for item in self.__relationships[key].values:
                items_list.append(item.write_to_dict())
        return properties

    def _update_persistent_object_context_property(self, name: str) -> None:
        """Update the property given by name in the persistent object context."""
        if self.persistent_object_context:
            properties: PersistentDictType = dict()
            self.__properties[name].write_to_dict(properties)
            if properties:
                for property_key, property_value in properties.items():
                    self.property_changed(property_key, property_value)
            else:
                self.clear_property(name)

    def __update_modified(self, modified: datetime.datetime) -> None:
        self.__modified_count += 1
        self.modified_state += 1
        self.__modified = modified
        parent = self.persistent_object_parent.parent if self.persistent_object_parent else None
        if parent:
            parent.__update_modified(modified)

    def _get_persistent_property(self, name: str) -> PersistentProperty:
        """ Subclasses can call this to get a property descriptor. """
        return self.__properties[name]

    def _get_persistent_property_value(self, name: str, default: typing.Any = None) -> typing.Any:
        """ Subclasses can call this to get a hidden property. """
        property = self.__properties.get(name)
        return property.value if property else default

    def _set_persistent_property_value(self, name: str, value: typing.Any) -> None:
        """ Subclasses can call this to set a hidden property. """
        property = self.__properties[name]
        property.set_value(value)
        self.__update_modified(datetime.datetime.utcnow())
        self._update_persistent_object_context_property(name)

    def _update_persistent_property(self, name: str, value: typing.Any) -> None:
        """ Subclasses can call this to notify that a custom property was updated. """
        self.__update_modified(datetime.datetime.utcnow())
        if self.persistent_object_context:
            self.property_changed(name, value)

    def _get_relationship_values(self, name: str) -> typing.Sequence[typing.Any]:
        return copy.copy(self.__relationships[name].values)

    def _is_persistent_property_recordable(self, name: str) -> bool:
        property = self.__properties.get(name)
        return (property.recordable and not property.read_only) if (property is not None) else False

    def __getattr__(self, name: str) -> typing.Any:
        # Handle property objects that are not hidden.
        property = self.__properties.get(name)
        if property and not property.hidden:
            return self._get_persistent_property_value(name)
        if name in self.__items and not self.__items[name].hidden:
            return self.__items[name].value
        if name in self.__relationships and not self.__relationships[name].hidden:
            return self._get_relationship_values(name)
        raise AttributeError("%r object has no attribute %r" % (self.__class__, name))

    OBSERVABLE_FIELDS = (
        "property_changed_event",
        "item_set_event",
        "item_cleared_event",
        "item_inserted_event",
        "item_removed_event",
        "item_added_event",
        "item_discarded_event",
        "item_content_changed_event",
        )

    def __setattr__(self, name: str, value: typing.Any) -> None:
        # Check for private properties of this class
        if name.startswith("_PersistentObject__") or name in PersistentObject.OBSERVABLE_FIELDS:
            super().__setattr__(name, value)
        # Otherwise check for defined properties.
        else:
            property = self.__properties.get(name)
            # if the property is hidden, fall through and give regular style property a chance to handle it
            if property and not property.hidden:
                # if the property is not hidden and it is read only, throw an exception
                if not property.read_only:
                    property.set_value(value)
                    self.__update_modified(datetime.datetime.utcnow())
                    self._update_persistent_object_context_property(name)
                else:
                    raise AttributeError()
            else:
                super().__setattr__(name, value)

    def __set_item(self, name: str, value: typing.Any) -> None:
        """ Set item into item storage and notify. Does not set into persistent storage or update modified. Item can be None. """
        item = self.__items[name]
        old_value = item.value
        item.value = value
        if value:
            value.persistent_object_parent = PersistentObjectParent(self, item_name=name)
            value.persistent_object_context = self.persistent_object_context
        if item.item_changed:
            item.item_changed(name, old_value, value)

    def get_item(self, name: str) -> typing.Any:
        """ Get item from persistent storage. """
        item = self.__items[name]
        return item.value

    def set_item(self, name: str, value: typing.Any) -> None:
        """ Set item into persistent storage and then into item storage and notify. """
        item = self.__items[name]
        old_value = item.value
        item.value = value
        self.__update_modified(datetime.datetime.utcnow())
        if value:
            value.persistent_object_parent = PersistentObjectParent(self, item_name=name)
        # the persistent_object_parent and item need to be established before
        # calling item_changed.
        if self.persistent_object_context:
            self.item_set(name, value)  # this will also update item's persistent_object_context
        if value:
            value.persistent_object_context = self.persistent_object_context
        else:
            value.persistent_object_context = None
        if item.item_changed:
            item.item_changed(name, old_value, value)

    def load_item(self, name: str, before_index: int, item: PersistentObject) -> None:
        """ Load item in persistent storage and then into relationship storage, but don't update modified or notify persistent storage. """
        item.persistent_dict = self._get_relationship_persistent_dict_by_uuid(item, name) or dict()
        item.persistent_storage = self.persistent_storage
        relationship = self.__relationships[name]
        relationship.values.insert(before_index, item)
        relationship.index[item.uuid] = item
        item.about_to_be_inserted(self)
        item.persistent_object_parent = PersistentObjectParent(self, relationship_name=name)
        if self.persistent_object_context:  # when item is not top level, self will not have persistent object context
            item.persistent_object_context = self.persistent_object_context
        if relationship.insert:
            relationship.insert(name, before_index, item)

    def unload_item(self, name: str, index: int) -> None:
        """ Unload item from relationship storage and persistent storage, but don't update modified or notify persistent storage. """
        relationship = self.__relationships[name]
        item = relationship.values.pop(index)
        relationship.index.pop(item.uuid)
        item.about_to_be_removed(self)
        if relationship.remove:
            relationship.remove(name, index, item)
        item.persistent_object_context = None
        item.persistent_object_parent = None
        item.persistent_storage = None
        item.persistent_dict = None
        item.close()

    def insert_item(self, name: str, before_index: int, item: PersistentObject) -> None:
        """ Insert item in persistent storage and then into relationship storage and notify. """
        relationship = self.__relationships[name]
        relationship.values.insert(before_index, item)
        relationship.index[item.uuid] = item
        self.__update_modified(datetime.datetime.utcnow())
        item.persistent_object_parent = PersistentObjectParent(self, relationship_name=name)
        # the persistent_object_parent and relationship need to be established before
        # calling item_inserted.
        item.about_to_be_inserted(self)
        if self.persistent_object_context:
            self.item_inserted(name, before_index, item)  # this will also update item's persistent_object_context
            item.persistent_object_context = self.persistent_object_context
        if relationship.insert:
            relationship.insert(name, before_index, item)

    def append_item(self, name: str, item: PersistentObject) -> None:
        """ Append item and append to persistent storage. """
        self.insert_item(name, len(self.__relationships[name].values), item)

    def remove_item(self, name: str, item: PersistentObject) -> None:
        """ Remove item and remove from persistent storage. """
        item.about_to_be_removed(self)
        relationship = self.__relationships[name]
        item_index = relationship.values.index(item)
        relationship.values.remove(item)
        relationship.index.pop(item.uuid)
        self.__update_modified(datetime.datetime.utcnow())
        if relationship.remove:
            relationship.remove(name, item_index, item)
        if self.persistent_object_context:  # only clear if self has a context; it won't if it is still being constructed
            item.persistent_object_context = None
        if self.persistent_object_context:
            self.item_removed(name, item_index, item)  # this will also update item's persistent_object_context
        item.persistent_object_parent = None
        item.close()

    def extend_items(self, name: str, items: typing.Sequence[PersistentObject]) -> None:
        """ Append multiple items and add to persistent storage. """
        for item in items:
            self.append_item(name, item)

    def item_count(self, name: str) -> int:
        """Return the count of items in the relationship specified by name."""
        relationship = self.__relationships[name]
        return len(relationship.values)

    def item_index(self, name: str, item: PersistentObject) -> int:
        """Return the index of item within the relationship specified by name."""
        relationship = self.__relationships[name]
        return relationship.values.index(item)

    def get_item_by_uuid(self, name: str, uuid: uuid.UUID) -> typing.Optional[PersistentObject]:
        """Return the item from the index by uuid."""
        relationship = self.__relationships[name]
        return relationship.index.get(uuid)

    def item_inserted(self, name: str, before_index: int, item: PersistentObject) -> None:
        """ Call this to notify this context that the item before before_index has just been inserted into the parent in
        the relationship with the given name. """
        assert self.persistent_storage
        self.persistent_storage.insert_item(self, name, before_index, item)

    def item_removed(self, name: str, index: int, item: PersistentObject) -> None:
        """ Call this to notify this context that the item at item_index has been removed from the parent in the
        relationship with the given name. """
        assert self.persistent_storage
        self.persistent_storage.remove_item(self, name, index, item)

    def item_set(self, name: str, item: PersistentObject) -> None:
        """ Call this to notify this context that an item with name has been set on the parent. """
        assert self.persistent_storage
        self.persistent_storage.set_item(self, name, item)

    def property_changed(self, name: str, value: typing.Any) -> None:
        """ Call this to notify this context that a property with name has changed to value on object. """
        assert self.persistent_storage
        self.persistent_storage.set_property(self, name, value)

    def clear_property(self, name: str) -> None:
        """ Call this to notify this context that a property with name has been removed on object. """
        assert self.persistent_storage
        self.persistent_storage.clear_property(self, name)

    def read_external_data(self, name: str) -> typing.Any:
        """ Call this to notify read external data with name from an item in persistent storage. """
        assert self.persistent_storage
        return self.persistent_storage.read_external_data(self, name)

    def write_external_data(self, name: str, value: typing.Any) -> None:
        """ Call this to notify write external data value with name to an item in persistent storage. """
        assert self.persistent_storage
        self.persistent_storage.write_external_data(self, name, value)

    def reserve_external_data(self, name: str, data_shape: typing.Tuple[int, ...], data_dtype: numpy.typing.DTypeLike) -> None:
        """ Call this to notify reserve external data value with name to an item in persistent storage. """
        assert self.persistent_storage
        self.persistent_storage.reserve_external_data(self, name, data_shape, numpy.dtype(data_dtype))

    def enter_write_delay(self) -> None:
        """ Call this to notify this context that the object should be write delayed. """
        assert self.persistent_storage
        self.persistent_storage.enter_write_delay(self)

    def exit_write_delay(self) -> None:
        """ Call this to notify this context that the object should no longer be write delayed. """
        assert self.persistent_storage
        self.persistent_storage.exit_write_delay(self)

    @property
    def is_write_delayed(self) -> bool:
        assert self.persistent_storage
        return self.persistent_storage.is_write_delayed(self)

    def rewrite(self) -> None:
        """ Call this to write an item that was write delayed. """
        assert self.persistent_storage
        self.persistent_storage.rewrite_item(self)

    def create_item_proxy(self, *, item_uuid: typing.Optional[uuid.UUID] = None, item_specifier: typing.Optional[PersistentObjectSpecifier] = None, item: typing.Optional[PersistentObject] = None) -> PersistentObjectProxy:
        """Create an item proxy by uuid or directly using the item."""
        item_specifier = item_specifier or (PersistentObjectSpecifier(item_uuid=item_uuid) if item_uuid else None)
        return PersistentObjectProxy(self, item_specifier, item)

    def create_item_reference(self, *, item_uuid: typing.Optional[uuid.UUID] = None, item_specifier: typing.Optional[PersistentObjectSpecifier] = None, item: typing.Optional[PersistentObject] = None) -> PersistentObjectReference:
        """Create an item proxy by uuid or directly using the item."""
        item_specifier = item_specifier or (PersistentObjectSpecifier(item_uuid=item_uuid) if item_uuid else None)
        item_reference = PersistentObjectReference(self.persistent_object_context, item_specifier, item)
        self.__item_references.append(item_reference)
        return item_reference

    def destroy_item_reference(self, item_reference: PersistentObjectReference) -> None:
        self.__item_references.remove(item_reference)

    def resolve_item_specifier(self, item_specifier: PersistentObjectSpecifier) -> typing.Optional[PersistentObject]:
        """Return the resolve item specifier."""
        if self.persistent_object_context:
            return self.persistent_object_context.get_registered_object(item_specifier)
        return None
