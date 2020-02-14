"""
A collection of persistence classes.
"""

# standard libraries
import abc
import copy
import datetime
import logging
import re
import typing
import uuid
import weakref


# third party libraries
# None

# local libraries
from nion.utils import Event


class PersistentProperty:

    """
        Represents a persistent property.

        converter converts from value to json value
    """

    def __init__(self, name, value=None, make=None, read_only=False, hidden=False, recordable=True, validate=None, converter=None, changed=None, key=None, reader=None, writer=None):
        super(PersistentProperty, self).__init__()
        self.name = name
        self.key = key if key else name
        self.value = value
        self.make = make
        self.read_only = read_only
        self.hidden = hidden
        self.recordable = recordable
        self.validate = validate
        self.converter = converter
        self.reader = reader
        self.writer = writer
        self.convert_get_fn = converter.convert if converter else copy.deepcopy  # optimization
        self.convert_set_fn = converter.convert_back if converter else lambda value: value  # optimization
        self.changed = changed

    def close(self) -> None:
        self.make = None
        self.validate = None
        self.converter = None
        self.reader = None
        self.writer = None
        self.convert_get_fn = None
        self.convert_set_fn = None
        self.changed = None

    def set_value(self, value):
        if self.validate:
            value = self.validate(value)
        else:
            value = copy.deepcopy(value)
        self.value = value
        if self.changed:
            self.changed(self.name, value)

    @property
    def json_value(self):
        return self.convert_get_fn(self.value)

    @json_value.setter
    def json_value(self, json_value):
        self.set_value(self.convert_set_fn(json_value))

    def read_from_dict(self, properties):
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

    def write_to_dict(self, properties):
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

    def __init__(self, name, value=None, make=None, read_only=False, hidden=False, recordable=True, validate=None, converter=None, changed=None, key=None, reader=None, writer=None):
        super().__init__(name, value, make, read_only, hidden, recordable, validate, converter, changed, key, reader, writer)
        self.__value = value

    @property
    def value(self):
        return copy.deepcopy(self.__value)

    @value.setter
    def value(self, value):
        self.__value = value


class PersistentItem:

    def __init__(self, name, factory, item_changed=None, hidden=False):
        super(PersistentItem, self).__init__()
        self.name = name
        self.factory = factory
        self.item_changed = item_changed
        self.hidden = hidden
        self.value = None

    def close(self) -> None:
        self.item_changed = None


class PersistentRelationship:

    def __init__(self, name, factory, insert=None, remove=None, key=None):
        super().__init__()
        self.name = name
        self.factory = factory
        self.insert = insert
        self.remove = remove
        self.key = key
        self.values = list()
        self.index = dict()

    def close(self) -> None:
        self.insert = None
        self.remove = None

    @property
    def storage_key(self):
        return self.key if self.key else self.name


class PersistentStorageInterface(abc.ABC):

    @abc.abstractmethod
    def get_storage_properties(self) -> typing.Dict: ...

    @abc.abstractmethod
    def get_properties(self, object) -> typing.Dict: ...

    @abc.abstractmethod
    def insert_item(self, parent, name: str, before_index: int, item) -> None: ...

    @abc.abstractmethod
    def remove_item(self, parent, name: str, index: int, item) -> None: ...

    @abc.abstractmethod
    def set_item(self, parent, name, item): ...

    @abc.abstractmethod
    def set_property(self, object, name, value): ...

    @abc.abstractmethod
    def clear_property(self, object, name): ...

    @abc.abstractmethod
    def read_external_data(self, item, name: str): ...

    @abc.abstractmethod
    def write_external_data(self, item, name: str, value) -> None: ...

    @abc.abstractmethod
    def enter_write_delay(self, object) -> None: ...

    @abc.abstractmethod
    def exit_write_delay(self, object) -> None: ...

    @abc.abstractmethod
    def is_write_delayed(self, data_item) -> bool: ...

    @abc.abstractmethod
    def rewrite_item(self, item) -> None: ...


class PersistentObjectContext:
    """Provides a common context to track available persistent objects.

    All objects participating in this context should register and unregister themselves with this context at appropriate
    times.

    Other objects can listen to the registration_event to know when a specific object is registered or unregistered.
    """

    def __init__(self):
        self.__objects = dict()
        self.registration_event = Event.Event()

    def register(self, object: "PersistentObject", item_specifier: "PersistentObjectSpecifier") -> None:
        # print(f"register {object} {item_specifier.write()} {len(self.__objects) + 1}")
        # assert item_specifier not in self.__objects
        self.__objects[item_specifier] = weakref.ref(object)
        self.registration_event.fire(object, None)

    def unregister(self, object: "PersistentObject", item_specifier: "PersistentObjectSpecifier") -> None:
        # print(f"unregister {object} {item_specifier.write()} {len(self.__objects) - 1}")
        # assert item_specifier in self.__objects
        if item_specifier in self.__objects:
            self.__objects.pop(item_specifier)
            self.registration_event.fire(None, object)

    def get_registered_object(self, item_specifier: "PersistentObjectSpecifier") -> typing.Optional["PersistentObject"]:
        object_weakref = self.__objects.get(item_specifier, None)
        return object_weakref() if object_weakref else None


class PersistentObjectSpecifier:

    def __init__(self, *, item: "PersistentObject" = None, item_uuid: uuid.UUID = None, context: "PersistentObject" = None, context_uuid: uuid.UUID = None):
        self.__item_uuid = item.uuid if item else item_uuid
        self.__context_uuid = context.uuid if context else context_uuid
        assert (self.__item_uuid is None) or isinstance(self.__item_uuid, uuid.UUID)

    def __hash__(self):
        return hash((self.__context_uuid, self.__item_uuid))

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.__item_uuid == other.__item_uuid and self.__context_uuid == other.__context_uuid
        return False

    @property
    def item_uuid(self) -> typing.Optional[uuid.UUID]:
        return self.__item_uuid

    @property
    def context_uuid(self) -> typing.Optional[uuid.UUID]:
        return self.__context_uuid

    def write(self) -> typing.Optional[typing.Union[typing.Dict, str]]:
        if self.__item_uuid:
            if not self.__context_uuid:
                return str(self.__item_uuid)
            else:
                return {"item_uuid": str(self.__item_uuid), "context_uuid": str(self.__context_uuid)}
        return None

    @staticmethod
    def read(d: typing.Union[typing.Mapping, str, uuid.UUID]) -> typing.Optional["PersistentObjectSpecifier"]:
        if isinstance(d, str):
            return PersistentObjectSpecifier(item_uuid=uuid.UUID(d))
        elif isinstance(d, uuid.UUID):
            return PersistentObjectSpecifier(item_uuid=d)
        elif isinstance(d, dict) and "item_uuid" in d and "context_uuid" in d:
            return PersistentObjectSpecifier(item_uuid=uuid.UUID(d["item_uuid"]), context_uuid=uuid.UUID(d["context_uuid"]))
        elif isinstance(d, dict) and "item_uuid" in d:
            return PersistentObjectSpecifier(item_uuid=uuid.UUID(d["item_uuid"]))
        elif isinstance(d, dict) and "uuid" in d:
            return PersistentObjectSpecifier(item_uuid=uuid.UUID(d["uuid"]), context_uuid=uuid.UUID(d["context_uuid"]) if "context_uuid" in d else None)
        else:
            return None


class PersistentObjectProxy:

    def __init__(self, persistent_object: "PersistentObject", item_specifier: typing.Optional[PersistentObjectSpecifier], item: typing.Optional["PersistentObject"]):
        self.__persistent_object = persistent_object
        self.__item_specifier = item_specifier if item_specifier else PersistentObjectSpecifier(item=item) if item else None
        self.__item = item
        self.__registration_listener = None
        self.on_item_registered = None
        self.on_item_unregistered = None

        self.__persistent_object_context_changed_listener = persistent_object.persistent_object_context_changed_event.listen(self.__persistent_object_context_changed)

        # watch for our context being removed
        self.__persistent_object_about_to_be_removed_listener = persistent_object.about_to_be_removed_event.listen(self.close)

        self.__persistent_object_context_changed()

    def close(self):
        if self.__registration_listener:
            self.__registration_listener.close()
            self.__registration_listener = None
        if self.__persistent_object_context_changed_listener:
            self.__persistent_object_context_changed_listener.close()
            self.__persistent_object_context_changed_listener = None
        if self.__persistent_object_about_to_be_removed_listener:
            self.__persistent_object_about_to_be_removed_listener.close()
            self.__persistent_object_about_to_be_removed_listener = None
        self.__item = None
        self.__persistent_object = None
        self.on_item_registered = None
        self.on_item_unregistered = None

    @property
    def item(self) -> typing.Optional["PersistentObject"]:
        return self.__item

    @item.setter
    def item(self, item: typing.Optional["PersistentObject"]) -> None:
        if self.__registration_listener:
            self.__registration_listener.close()
            self.__registration_listener = None
        self.__item = item
        self.__item_specifier = PersistentObjectSpecifier(item=item) if item else None
        self.__persistent_object_context_changed()

    @property
    def item_specifier(self) -> PersistentObjectSpecifier:
        return self.__item_specifier

    @item_specifier.setter
    def item_specifier(self, item_specifier: PersistentObjectSpecifier) -> None:
        if self.__registration_listener:
            self.__registration_listener.close()
            self.__registration_listener = None
        self.__item_specifier = item_specifier
        self.__item = None
        self.__persistent_object_context_changed()

    def __change_registration(self, registered_object: typing.Optional["PersistentObject"], unregistered_object: typing.Optional["PersistentObject"]) -> None:
        if registered_object and not self.__item and self.__item_specifier and self.__persistent_object._matches_related_item(registered_object, self.__item_specifier):
            item = self.__persistent_object._get_related_item(self.__item_specifier)
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
                item = self.__persistent_object._get_related_item(self.__item_specifier)
                if item:
                    self.__change_registration(item, None)
            self.__registration_listener = self.__persistent_object.persistent_object_context.registration_event.listen(self.__change_registration)
        elif self.__registration_listener:
            self.__registration_listener.close()
            self.__registration_listener = None


class PersistentObjectParent:
    """ Track the parent of a persistent object. """

    def __init__(self, parent: "PersistentObject", relationship_name: str=None, item_name: str=None):
        self.__weak_parent = weakref.ref(parent)
        self.relationship_name = relationship_name
        self.item_name = item_name

    @property
    def parent(self) -> "PersistentObject":
        return self.__weak_parent()


class PersistentObject:
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

    def __init__(self):
        super().__init__()
        self.__type = None
        self.__properties = dict()
        self.__items = dict()
        self.__relationships = dict()
        self.__container_weak_ref = None
        self._closed = False
        self.about_to_close_event = Event.Event()
        self._about_to_be_removed = False
        self.about_to_be_removed_event = Event.Event()
        self._is_reading = False
        self.__persistent_object_context = None
        # uuid as a property is too slow, so make it direct
        self.uuid = uuid.uuid4()
        self.__modified_count = 0
        self.modified_state = 0
        self.__modified = datetime.datetime.utcnow()
        self.persistent_object_parent = None
        self.__persistent_dict = None
        self.__persistent_storage = None
        self.persistent_object_context_changed_event = Event.Event()

    def close(self) -> None:
        self.about_to_close_event.fire()
        assert not self._closed
        self._closed = True
        self.close_items()
        self.close_relationships()
        self.__container_weak_ref = None
        self.__persistent_object_context = None
        self.undefine_properties()
        self.undefine_items()
        self.undefine_relationships()

    def __deepcopy__(self, memo):
        deepcopy = self.__class__()
        deepcopy.deepcopy_from(self, memo)
        memo[id(self)] = deepcopy
        return deepcopy

    def deepcopy_from(self, item, memo):
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
    def container(self):
        return self.__container_weak_ref() if self.__container_weak_ref else None

    def about_to_be_inserted(self, container):
        assert self.__container_weak_ref is None
        self.__container_weak_ref = weakref.ref(container)

    def about_to_be_removed(self, container):
        # called before close and before item is removed from its container
        for item in self.__items.values():
            item.value.about_to_be_removed(self)
        for relationship in self.__relationships.values():
            for item in reversed(relationship.values):
                item.about_to_be_removed(self)
        self.about_to_be_removed_event.fire()
        assert not self._about_to_be_removed
        self._about_to_be_removed = True
        self.__container_weak_ref = None

    @property
    def item_specifier(self) -> "PersistentObjectSpecifier":
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
        self.persistent_dict = self.persistent_storage.get_storage_properties()

    def update_item_context(self, item: "PersistentObject") -> None:
        """Update the context on the item."""
        item.persistent_object_context = self.persistent_object_context

    def persistent_object_context_changed(self) -> None:
        """ Subclasses can override this to be notified when the persistent object context changes. """
        pass

    @property
    def persistent_object_context(self) -> PersistentObjectContext:
        """ Return the persistent object context. """
        return self.__persistent_object_context

    @persistent_object_context.setter
    def persistent_object_context(self, persistent_object_context: PersistentObjectContext) -> None:
        """ Set the persistent object context and propagate it to contained objects. """
        assert self.__persistent_object_context is None or persistent_object_context is None  # make sure persistent object context is handled cleanly
        old_persistent_object_context = self.__persistent_object_context
        self.__persistent_object_context = persistent_object_context
        for item in self.__items.values():
            if item.value:
                item.value.persistent_object_context = persistent_object_context
        for relationship in self.__relationships.values():
            for item in relationship.values:
                if item:
                    item.persistent_object_context = persistent_object_context
        if old_persistent_object_context:
            old_persistent_object_context.unregister(self, self.__item_specifier)
        if persistent_object_context:
            self.__item_specifier = self.item_specifier
            persistent_object_context.register(self, self.__item_specifier)
        self.persistent_object_context_changed()
        self.persistent_object_context_changed_event.fire()

    @property
    def persistent_dict(self) -> typing.Dict:
        return self.__persistent_dict

    @persistent_dict.setter
    def persistent_dict(self, persistent_dict: typing.Dict) -> None:
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
    def persistent_storage(self) -> PersistentStorageInterface:
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

    def _get_item_persistent_dict(self, item, key: str) -> typing.Optional[typing.Dict]:
        return self.persistent_dict[key] if self.persistent_dict is not None else None

    def _get_relationship_persistent_dict(self, item, key: str, index: int) -> typing.Optional[typing.Dict]:
        return self.persistent_dict[key][index] if self.persistent_dict is not None else None

    def _get_relationship_persistent_dict_by_uuid(self, item, key: str) -> typing.Optional[typing.Dict]:
        if self.persistent_dict:
            for item_d in self.persistent_dict.get(key, list()):
                if uuid.UUID(item_d.get("uuid")) == item.uuid:
                    return item_d
        return None

    def _get_related_item(self, item_specifier: PersistentObjectSpecifier) -> typing.Optional["PersistentObject"]:
        if self.persistent_object_parent and self.persistent_object_parent.parent:
            return self.persistent_object_parent.parent._get_related_item(item_specifier)
        if self.persistent_object_context:
            return self.persistent_object_context.get_registered_object(item_specifier)
        return None

    def _matches_related_item(self, item: "PersistentObject", item_specifier: PersistentObjectSpecifier) -> bool:
        return item.uuid == item_specifier.item_uuid

    def define_type(self, type):
        self.__type = type

    def define_property(self, name: str, value=None, make=None, read_only: bool=False, hidden: bool=False, recordable: bool=True, copy_on_read: bool=False, validate=None, converter=None, changed=None, key=None, reader=None, writer=None):
        """ key is what is stored on disk; name is what is used when accessing the property from code. """
        if copy_on_read:
            self.__properties[name] = PersistentPropertySpecial(name, value, make, read_only, hidden, recordable, validate, converter, changed, key, reader, writer)
        else:
            self.__properties[name] = PersistentProperty(name, value, make, read_only, hidden, recordable, validate, converter, changed, key, reader, writer)

    def define_item(self, name, factory, item_changed=None, hidden=False):
        self.__items[name] = PersistentItem(name, factory, item_changed, hidden)

    def define_relationship(self, name, factory, insert=None, remove=None, key=None):
        self.__relationships[name] = PersistentRelationship(name, factory, insert, remove, key)

    def close_items(self) -> None:
        for item in self.__items.values():
            if item.value:
                item.value.persistent_object_context = None
                item.value.close()

    def close_relationships(self) -> None:
        for relationship in self.__relationships.values():
            for item in reversed(relationship.values):
                if item:
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

    def get_storage_properties(self) -> typing.Dict:
        """ Return a copy of the properties for the object as a dict. """
        return copy.deepcopy(self.persistent_storage.get_properties(self))

    @property
    def property_names(self):
        return list(self.__properties.keys())

    @property
    def key_names(self):
        return [property.key for property in self.__properties.values()]

    @property
    def type(self):
        return self.__type

    @property
    def modified(self):
        return self.__modified

    @property
    def modified_count(self):
        return self.__modified_count

    def _set_modified(self, modified):
        # for testing
        self.__update_modified(modified)
        if self.persistent_object_context:
            self.property_changed("uuid", str(self.uuid))  # dummy write

    @property
    def item_names(self):
        return list(self.__items.keys())

    @property
    def relationship_names(self):
        return list(self.__relationships.keys())

    def begin_reading(self):
        self._is_reading = True

    def read_from_dict(self, properties):
        """ Read from a dict. """
        # uuid is handled specially for performance reasons
        if "uuid" in properties:
            self.uuid = uuid.UUID(properties["uuid"])
        if "modified" in properties:
            self.__modified = datetime.datetime(*list(map(int, re.split('[^\d]', properties["modified"]))))
        # iterate the defined properties
        for key in self.__properties.keys():
            property = self.__properties[key]
            property.read_from_dict(properties)
        for key in self.__items.keys():
            item_dict = properties.get(key)
            if item_dict:
                factory = self.__items[key].factory
                # the object has not been constructed yet, but we needs its
                # type or id to construct it. so we need to look it up by key/index/name.
                # to minimize the interface to the factory methods, just pass a closure
                # which looks up by name.
                def lookup_id(name, default=None):
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
                def lookup_id(name, default=None):
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

    def finish_reading(self):
        for key in self.__items.keys():
            item = self.__items[key].value
            if item:
                item.finish_reading()
        for key in self.__relationships.keys():
            for item in self.__relationships[key].values:
                item.finish_reading()
        self._is_reading = False

    def write_to_dict(self):
        """ Write the object to a dict and return it. """
        properties = dict()
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

    def _update_persistent_object_context_property(self, name):
        """
            Update the property given by name in the persistent object context.

            Subclasses can override this to provide custom writing behavior, such
            as delaying write until an appropriate time for performance reasons.
        """
        property = self.__properties[name]
        if self.persistent_object_context:
            properties = dict()
            property.write_to_dict(properties)
            if properties:
                for property_key in properties:
                    self.property_changed(property_key, properties[property_key])
            else:
                self.clear_property(name)

    def __update_modified(self, modified):
        self.__modified_count += 1
        self.modified_state += 1
        self.__modified = modified
        parent = self.persistent_object_parent.parent if self.persistent_object_parent else None
        if parent:
            parent.__update_modified(modified)

    def _get_persistent_property(self, name):
        """ Subclasses can call this to get a property descriptor. """
        return self.__properties[name]

    def _get_persistent_property_value(self, name, default=None):
        """ Subclasses can call this to get a hidden property. """
        property = self.__properties.get(name)
        return property.value if property else default

    def _set_persistent_property_value(self, name, value):
        """ Subclasses can call this to set a hidden property. """
        property = self.__properties[name]
        property.set_value(value)
        self.__update_modified(datetime.datetime.utcnow())
        self._update_persistent_object_context_property(name)

    def _update_persistent_property(self, name: str, value) -> None:
        """ Subclasses can call this to notify that a custom property was updated. """
        self.__update_modified(datetime.datetime.utcnow())
        if self.persistent_object_context:
            self.property_changed(name, value)

    def _is_persistent_property_recordable(self, name) -> bool:
        property = self.__properties.get(name)
        return (property.recordable and not property.read_only) if (property is not None) else False

    def __getattr__(self, name):
        # Handle property objects that are not hidden.
        property = self.__properties.get(name)
        if property and not property.hidden:
            return property.value
        if name in self.__items and not self.__items[name].hidden:
            return self.__items[name].value
        if name in self.__relationships:
            return copy.copy(self.__relationships[name].values)
        raise AttributeError("%r object has no attribute %r" % (self.__class__, name))

    def __setattr__(self, name, value):
        # Check for private properties of this class
        if name.startswith("_PersistentObject__"):
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

    def __set_item(self, name, value):
        """ Set item into item storage and notify. Does not set into persistent storage or update modified. Item can be None. """
        item = self.__items[name]
        old_value = item.value
        item.value = value
        if value:
            value.persistent_object_parent = PersistentObjectParent(self, item_name=name)
            value.persistent_object_context = self.persistent_object_context
        if item.item_changed:
            item.item_changed(name, old_value, value)

    def get_item(self, name):
        """ Get item from persistent storage. """
        item = self.__items[name]
        return item.value

    def set_item(self, name, value):
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

    def load_item(self, name: str, before_index: int, item: "PersistentObject") -> None:
        """ Load item in persistent storage and then into relationship storage, but don't update modified or notify persistent storage. """
        item.persistent_dict = self._get_relationship_persistent_dict_by_uuid(item, name)
        item.persistent_storage = self.persistent_storage
        relationship = self.__relationships[name]
        relationship.values.insert(before_index, item)
        relationship.index[item.uuid] = item
        item.about_to_be_inserted(self)
        item.persistent_object_parent = PersistentObjectParent(self, relationship_name=name)
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

    def insert_item(self, name, before_index, item):
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

    def append_item(self, name, item):
        """ Append item and append to persistent storage. """
        self.insert_item(name, len(self.__relationships[name].values), item)

    def remove_item(self, name, item):
        """ Remove item and remove from persistent storage. """
        item.about_to_be_removed(self)
        relationship = self.__relationships[name]
        item_index = relationship.values.index(item)
        relationship.values.remove(item)
        relationship.index.pop(item.uuid)
        self.__update_modified(datetime.datetime.utcnow())
        if relationship.remove:
            relationship.remove(name, item_index, item)
        item.persistent_object_context = None
        if self.persistent_object_context:
            self.item_removed(name, item_index, item)  # this will also update item's persistent_object_context
        item.persistent_object_parent = None
        item.close()

    def extend_items(self, name, items):
        """ Append multiple items and add to persistent storage. """
        for item in items:
            self.append_item(name, item)

    def item_count(self, name: str) -> int:
        """Return the count of items in the relationship specified by name."""
        relationship = self.__relationships[name]
        return len(relationship.values)

    def item_index(self, name: str, item: object) -> int:
        """Return the index of item within the relationship specified by name."""
        relationship = self.__relationships[name]
        return relationship.values.index(item)

    def get_item_by_uuid(self, name: str, uuid: uuid.UUID) -> typing.Optional["PersistentObject"]:
        """Return the item from the index by uuid."""
        relationship = self.__relationships[name]
        return relationship.index.get(uuid)

    def item_inserted(self, name: str, before_index: int, item: "PersistentObject") -> None:
        """ Call this to notify this context that the item before before_index has just been inserted into the parent in
        the relationship with the given name. """
        self.persistent_storage.insert_item(self, name, before_index, item)

    def item_removed(self, name: str, index: int, item: "PersistentObject") -> None:
        """ Call this to notify this context that the item at item_index has been removed from the parent in the
        relationship with the given name. """
        self.persistent_storage.remove_item(self, name, index, item)

    def item_set(self, name: str, item: "PersistentObject") -> None:
        """ Call this to notify this context that an item with name has been set on the parent. """
        self.persistent_storage.set_item(self, name, item)

    def property_changed(self, name: str, value) -> None:
        """ Call this to notify this context that a property with name has changed to value on object. """
        self.persistent_storage.set_property(self, name, value)

    def clear_property(self, name: str) -> None:
        """ Call this to notify this context that a property with name has been removed on object. """
        self.persistent_storage.clear_property(self, name)

    def read_external_data(self, name: str):
        """ Call this to notify read external data with name from an item in persistent storage. """
        return self.persistent_storage.read_external_data(self, name)

    def write_external_data(self, name: str, value) -> None:
        """ Call this to notify write external data value with name to an item in persistent storage. """
        self.persistent_storage.write_external_data(self, name, value)

    def enter_write_delay(self) -> None:
        """ Call this to notify this context that the object should be write delayed. """
        self.persistent_storage.enter_write_delay(self)

    def exit_write_delay(self) -> None:
        """ Call this to notify this context that the object should no longer be write delayed. """
        self.persistent_storage.exit_write_delay(self)

    @property
    def is_write_delayed(self) -> bool:
        return self.persistent_storage.is_write_delayed(self)

    def rewrite(self) -> None:
        """ Call this to write an item that was write delayed. """
        self.persistent_storage.rewrite_item(self)

    def create_item_proxy(self, *, item_uuid: uuid.UUID = None, item_specifier: PersistentObjectSpecifier = None, item: "PersistentObject" = None) -> PersistentObjectProxy:
        """Create an item proxy by uuid or directly using the item."""
        item_specifier = item_specifier or (PersistentObjectSpecifier(item_uuid=item_uuid) if item_uuid else None)
        return PersistentObjectProxy(self, item_specifier, item)

    def resolve_item_specifier(self, item_specifier: PersistentObjectSpecifier) -> typing.Optional["PersistentObject"]:
        """Return the resolve item specifier."""
        return self._get_related_item(item_specifier)
