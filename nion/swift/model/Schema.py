from __future__ import annotations

import abc
import collections
import copy
import datetime
import json
import os
import pathlib
import typing
import uuid
import weakref

from nion.utils import Converter
from nion.utils import DateTime
from nion.utils import Observable

DictValue = typing.Union[typing.Dict[str, typing.Any], typing.List[typing.Any], typing.Tuple[typing.Any], str, float, int, bool, None]
ItemProxyEntity = typing.Optional[typing.Any]  # use this to make it easy to switch to Entity later
PersistentDictType = typing.Dict[str, DictValue]
PersistentMappingType = typing.Mapping[str, DictValue]
_WeakReferenceType = typing.Any  # Python 3.9+ fix these

ANY = "any"
STRING = "string"
BOOLEAN = "boolean"
INT = "integer"
FLOAT = "double"
LIST = "list"
DICT = "dict"
SET = "set"
TIMESTAMP = "timestamp"
UUID = "uuid"
PATH = "path"

OPTIONAL = True
REQUIRED = False

entity_types: typing.Dict[str, EntityType] = dict()


def utcnow() -> datetime.datetime:
    return DateTime.utcnow()


def register_entity_type(entity_id: str, entity: EntityType) -> None:
    entity_types[entity_id] = entity


def unregister_entity_type(entity_id: str) -> None:
    del entity_types[entity_id]


def get_entity_type(entity_id: str) -> typing.Optional[EntityType]:
    return entity_types.get(entity_id)


def build_value(type: str, value: typing.Any) -> typing.Any:
    if value is None:
        return None
    if type in (SET,):
        return set(value)
    if type in (BOOLEAN,):
        return bool(value)
    if type in (INT,):
        return int(value)
    if type in (FLOAT,):
        return float(value)
    if type in (TIMESTAMP,):
        return Converter.DatetimeToStringConverter().convert_back(value)
    if type in (UUID,):
        return Converter.UuidToStringConverter().convert_back(value)
    if type in (PATH,):
        return Converter.PathToStringConverter().convert_back(value)
    return value


def dict_value(type: str, value: typing.Any) -> DictValue:
    if value is None:
        return None
    if type in (SET,):
        return list(value)
    if type in (BOOLEAN,):
        return bool(value)
    if type in (INT,):
        return int(value)
    if type in (FLOAT,):
        return float(value)
    if type in (TIMESTAMP,):
        return Converter.DatetimeToStringConverter().convert(value)
    if type in (UUID,):
        return Converter.UuidToStringConverter().convert(value)
    if type in (PATH,):
        return Converter.PathToStringConverter().convert(value)
    return typing.cast(DictValue, value)


class ItemProxy:
    def __init__(self, item_uuid: typing.Optional[uuid.UUID]) -> None:
        self.__item_uuid = item_uuid
        self.__item = None

    def close(self) -> None:
        pass

    @property
    def item_uuid(self) -> typing.Optional[uuid.UUID]:
        return self.__item_uuid

    @item_uuid.setter
    def item_uuid(self, value: typing.Optional[uuid.UUID]) -> None:
        self.__item_uuid = value

    @property
    def item(self) -> ItemProxyEntity:
        return self.__item

    @item.setter
    def item(self, item: ItemProxyEntity) -> None:
        self.__item = item


class Accessor(typing.Protocol):
    accessor: typing.Optional[Accessor]
    field_type: FieldType

    def get_value(self, item: typing.Any) -> typing.Any: ...

    def breadcrumbs(self, item: typing.Any) -> typing.Sequence[typing.Any]: ...


class BaseAccessor(Accessor):
    def __init__(self, field_type: FieldType, field_name: str) -> None:
        self.accessor = None
        self.field_type = field_type
        self.field_name = field_name

    def __repr__(self) -> str:
        return f"{self.field_name}"

    def get_value(self, item: typing.Any) -> typing.Any:
        return item

    def breadcrumbs(self, item: typing.Any) -> typing.Sequence[typing.Any]:
        return [item]


class FieldAccessor(Accessor):
    def __init__(self, accessor: Accessor, field_type: FieldType, field_name: str) -> None:
        self.accessor = accessor
        self.field_type = field_type
        self.field_name = field_name

    def __repr__(self) -> str:
        return f"{self.accessor}.{self.field_name}"

    def get_value(self, item: typing.Any) -> typing.Any:
        return getattr(self.accessor.get_value(item), self.field_name, None)

    def breadcrumbs(self, item: typing.Any) -> typing.Sequence[typing.Any]:
        return self.accessor.breadcrumbs(item)


class IndexAccessor(Accessor):
    def __init__(self, accessor: Accessor, field_type: FieldType, index: int) -> None:
        self.accessor = accessor
        self.field_type = field_type
        self.index = index

    def __repr__(self) -> str:
        return f"{self.accessor}[{self.index}]"

    def get_value(self, item: typing.Any) -> typing.Any:
        return self.accessor.get_value(item)[self.index]

    def breadcrumbs(self, item: typing.Any) -> typing.Sequence[typing.Any]:
        return list(self.accessor.breadcrumbs(item)) + [self.get_value(item)]


class MapAccessor(Accessor):
    def __init__(self, accessor: Accessor, field_type: FieldType, key: typing.Any) -> None:
        self.accessor = accessor
        self.field_type = field_type
        self.key = key

    def __repr__(self) -> str:
        return f"{self.accessor}['{self.key}']"

    def get_value(self, item: typing.Any) -> typing.Any:
        return self.accessor.get_value(item)[self.key]

    def breadcrumbs(self, item: typing.Any) -> typing.Sequence[typing.Any]:
        return list(self.accessor.breadcrumbs(item)) + [self.get_value(item)]


class Visitor(typing.Protocol):
    def visit(self, accessor: Accessor) -> None: ...


class SupportsVisit(typing.Protocol):
    def visit(self, value: typing.Any, accessor: Accessor, visitor: Visitor) -> None: ...


class EntityContext(abc.ABC):

    @abc.abstractmethod
    def register(self, entity: Entity) -> None: ...

    @abc.abstractmethod
    def unregister(self, entity: Entity) -> None: ...

    @abc.abstractmethod
    def create_item_reference(self, item_uuid: typing.Optional[uuid.UUID] = None) -> ItemProxy: ...

    @abc.abstractmethod
    def update_item_reference_uuid(self, item_reference: ItemProxy, item_uuid: typing.Optional[uuid.UUID]) -> None: ...


class SimpleEntityContext(EntityContext):
    def __init__(self) -> None:
        self.__entity_map: typing.Dict[uuid.UUID, _WeakReferenceType] = dict()
        self.__item_proxies: typing.List[_WeakReferenceType] = list()

    def register(self, entity: Entity) -> None:
        self.__entity_map[entity.uuid] = weakref.ref(entity)
        for item_proxy_ref in self.__item_proxies:
            item_proxy = item_proxy_ref()
            if item_proxy and item_proxy.item_uuid == entity.uuid:
                item_proxy.item = entity

    def unregister(self, entity: Entity) -> None:
        self.__entity_map.pop(entity.uuid)
        for item_proxy_ref in self.__item_proxies:
            item_proxy = item_proxy_ref()
            if item_proxy and item_proxy.item_uuid == entity.uuid:
                item_proxy.item = None

    def create_item_reference(self, item_uuid: typing.Optional[uuid.UUID] = None) -> ItemProxy:
        item_proxy = ItemProxy(item_uuid)
        if item_uuid and item_uuid in self.__entity_map:
            entity_ref = self.__entity_map.get(item_uuid)
            if entity_ref:
                item_proxy.item = entity_ref()
        item_proxy_ref = weakref.ref(item_proxy)
        self.__item_proxies.append(item_proxy_ref)

        def finalize(item_proxy_ref: _WeakReferenceType, item_proxies: typing.List[_WeakReferenceType]) -> None:
            item_proxies.pop(item_proxies.index(item_proxy_ref))

        weakref.finalize(item_proxy, finalize, item_proxy_ref, self.__item_proxies)
        return item_proxy

    def update_item_reference_uuid(self, item_proxy: ItemProxy, item_uuid: typing.Optional[uuid.UUID]) -> None:
        if item_uuid and item_uuid in self.__entity_map:
            entity_ref = self.__entity_map.get(item_uuid)
            if entity_ref:
                item_proxy.item = entity_ref()
                return
        item_proxy.item = None



class Field(abc.ABC):
    """A value-holding field in an entity or another field.

    The context is used to resolve references and must be valid to read entities containing references.
    """
    def __init__(self, context: typing.Optional[EntityContext]) -> None:
        self.__context = context

    def close(self) -> None:
        pass

    @property
    def _context(self) -> typing.Optional[EntityContext]:
        return self.__context

    def set_context(self, context: typing.Optional[EntityContext]) -> None:
        """Set the context.

        The context can be changed from None to a value or a value to None.

        Subclasses should propagate the context to their sub fields.
        """
        assert (self.__context is None) != (context is None), f"{self.__context} {context}"
        self.__context = context

    @abc.abstractmethod
    def read(self, dict_value: typing.Any) -> Field: ...

    @abc.abstractmethod
    def write(self) -> DictValue: ...

    # not abstract to avoid type checking issues until mypy supports abstract properties
    @property
    def field_value(self) -> typing.Any:
        return None

    # not abstract to avoid type checking issues until mypy supports abstract properties
    def set_field_value(self, container: ItemProxyEntity, value: typing.Any) -> None:
        pass

    def field_by_key(self, key: str) -> Field:
        raise AttributeError()

    def field_by_index(self, index: int) -> Field:
        raise AttributeError()


class PropertyField(Field):
    """A value property field, which can hold a simple value."""

    def __init__(self, context: typing.Optional[EntityContext], type: str, optional: bool, default: typing.Any) -> None:
        super().__init__(context)
        self.__type = type
        self.__optional = optional
        self.__default = default
        self.__value = default

    def read(self, dict_value: typing.Any) -> Field:
        self.__value = build_value(self.__type, dict_value)
        return self

    def write(self) -> DictValue:
        return dict_value(self.__type, self.__value)

    @property
    def field_value(self) -> typing.Any:
        return self.__value

    def set_field_value(self, container: ItemProxyEntity, value: typing.Any) -> None:
        self.__value = value


class TupleField(Field):
    """A tuple property field, which can hold an indefinite tuple of simple values."""

    def __init__(self, context: typing.Optional[EntityContext], type: FieldType, optional: bool, default_values: typing.Optional[typing.Sequence[typing.Any]]) -> None:
        super().__init__(context)
        assert isinstance(type, FieldType)
        assert default_values is None or isinstance(default_values, (tuple, list))
        self.__type = type
        self.__optional = optional
        self.__default_values = list(default_values) if default_values is not None else None
        self.__fields: typing.Optional[typing.Tuple[Field, ...]] = None
        self.read(default_values)

    def close(self) -> None:
        self.__clear()
        super().close()

    def __clear(self) -> None:
        if self.__fields is not None:
            for field in self.__fields:
                field.close()
            self.__fields = None

    def set_context(self, context: typing.Optional[EntityContext]) -> None:
        super().set_context(context)
        if self.__fields:
            for field in self.__fields:
                field.set_context(context)

    def read(self, dict_value: typing.Any) -> Field:
        self.__clear()
        if isinstance(dict_value, (tuple, list)):
            self.__fields = tuple(self.__type.create_and_read(self._context, v) for v in dict_value)
        return self

    def write(self) -> DictValue:
        if self.__fields is not None:
            return list(field.write() for field in self.__fields)
        else:
            return None if self.__optional else copy.copy(self.__default_values)

    @property
    def field_value(self) -> typing.Any:
        return [field.field_value for field in self.__fields] if self.__fields else None

    def set_field_value(self, container: ItemProxyEntity, value: typing.Any) -> None:
        assert isinstance(value, (tuple, list))
        self.__fields = tuple(self.__type.create_and_read(self._context, v) for v in value)


class FixedTupleField(Field):
    """A tuple property field, which can hold a fixed length tuple of simple values."""

    def __init__(self, context: typing.Optional[EntityContext], types: typing.Sequence[FieldType], optional: bool, default_values: typing.Optional[typing.Tuple[typing.Any, ...]]) -> None:
        super().__init__(context)
        assert default_values is None or isinstance(default_values, (tuple, list))
        self.__types = types
        self.__optional = optional
        self.__default_values = list(default_values) if default_values is not None else None
        self.__fields: typing.Optional[typing.Tuple[Field, ...]] = None
        self.read(default_values)

    def close(self) -> None:
        self.__clear()
        super().close()

    def __clear(self) -> None:
        if self.__fields is not None:
            for field in self.__fields:
                field.close()
            self.__fields = None

    def set_context(self, context: typing.Optional[EntityContext]) -> None:
        super().set_context(context)
        if self.__fields:
            for field in self.__fields:
                field.set_context(context)

    def read(self, dict_value: typing.Any) -> Field:
        # TODO: the fields should be fixed
        self.__clear()
        if isinstance(dict_value, (tuple, list)):
            self.__fields = tuple(type.create_and_read(self._context, v) for type, v in zip(self.__types, dict_value))
        return self

    def write(self) -> DictValue:
        if self.__fields is not None:
            return list(field.write() for field in self.__fields)
        else:
            return None if self.__optional else copy.copy(self.__default_values)

    @property
    def field_value(self) -> typing.Any:
        return [field.field_value for field in self.__fields] if self.__fields else None

    def set_field_value(self, container: ItemProxyEntity, value: typing.Any) -> None:
        assert isinstance(value, (tuple, list))
        self.__fields = tuple(type.create_and_read(self._context, v) for type, v in zip(self.__types, value))


class RecordField(Field):
    """A record property field, which can hold a mapping of strings to simple values."""

    def __init__(self, context: typing.Optional[EntityContext], field_type_map: typing.Mapping[str, FieldType]) -> None:
        super().__init__(context)
        self.__field_type_map = field_type_map
        self.__field_map: typing.Dict[str, Field] = dict()
        for k, type in self.__field_type_map.items():
            self.__field_map[k] = type.create(context)

    def close(self) -> None:
        for field in self.__field_map.values():
            field.close()
        self.__field_map = None  # type: ignore
        super().close()

    def set_context(self, context: typing.Optional[EntityContext]) -> None:
        super().set_context(context)
        for field in self.__field_map.values():
            field.set_context(context)

    def read(self, dict_value: typing.Any) -> Field:
        if isinstance(dict_value, (dict)):
            for k, field in self.__field_map.items():
                field.read(dict_value.get(k))
        return self

    def write(self) -> DictValue:
        d = dict()
        for k, field in self.__field_map.items():
            v = field.write()
            if v is not None:
                d[k] = v
        return d

    @property
    def field_value(self) -> typing.Any:
        d = {k: field.field_value for k, field in self.__field_map.items()}
        return collections.namedtuple("record", d.keys())(*d.values())

    def set_field_value(self, container: ItemProxyEntity, value: typing.Any) -> None:
        assert isinstance(value, dict)
        for field in self.__field_map.values():
            field.close()
        for k, field_value in value.items():
            self.__field_map[k] = self.__field_type_map[k].create_and_read(self._context, field_value)


class ArrayField(Field):
    """A array of fields, which can be simple values, references, or components."""

    def __init__(self, context: typing.Optional[EntityContext], type: FieldType, optional: bool) -> None:
        super().__init__(context)
        self.__type = type
        self.__optional = optional
        self.__fields: typing.List[Field] = list()

    def close(self) -> None:
        for field in self.__fields:
            field.close()
        self.__fields = None  # type: ignore
        super().close()

    def set_context(self, context: typing.Optional[EntityContext]) -> None:
        super().set_context(context)
        for field in self.__fields:
            field.set_context(context)

    def read(self, dict_value: typing.Any) -> Field:
        if isinstance(dict_value, (tuple, list)):
            self.__fields = list(self.__type.create_and_read(self._context, item) for item in dict_value)
        else:
            self.__fields = list()
        return self

    def write(self) -> DictValue:
        if self.__fields is not None:
            l = list(field.write() for field in self.__fields)
        else:
            l = list()
        return l if l or not self.__optional else None

    @property
    def field_value(self) -> typing.Sequence[typing.Any]:
        return [field.field_value for field in self.__fields]

    def set_field_value(self, container: ItemProxyEntity, value: typing.Any) -> None:
        assert isinstance(value, (tuple, list))
        self.__fields = list(self.__type.create_and_read(self._context, v) for v in value)

    def insert_value(self, container: ItemProxyEntity, index: int, value: typing.Any) -> None:
        if isinstance(value, Entity):
            field = self.__type.create(self._context)
            field.set_field_value(container, value)  # no container yet
            self.__fields.insert(index, field)
        else:
            raise IndexError()

    def remove_value_at_index(self, index: int) -> None:
        field = self.__fields.pop(index)
        field.set_field_value(None, None)  # no container

    def field_by_index(self, index: int) -> Field:
        return self.__fields[index]


class MapField(Field):
    """A map of strings to fields, which can be simple values, references, or components."""

    def __init__(self, context: typing.Optional[EntityContext], key: FieldType, value: FieldType, optional: bool) -> None:
        super().__init__(context)
        self.__key = key
        self.__value = value
        self.__optional = optional
        self.__map: typing.Dict[str, Field] = dict()

    def close(self) -> None:
        for field in self.__map.values():
            field.close()
        self.__map = None  # type: ignore
        super().close()

    def set_context(self, context: typing.Optional[EntityContext]) -> None:
        super().set_context(context)
        for field in self.__map.values():
            field.set_context(context)

    def read(self, dict_value: typing.Any) -> Field:
        if isinstance(dict_value, dict):
            self.__map = {k: self.__value.create_and_read(self._context, v) for k, v in dict_value.items()}
        else:
            self.__map = dict()
        return self

    def write(self) -> DictValue:
        if self.__map is not None:
            d = {k: v.write() for k, v in self.__map.items()}
        else:
            d = dict()
        return d if d or not self.__optional else None

    @property
    def field_value(self) -> typing.Any:
        return {k: field.field_value for k, field in self.__map.items()}

    def set_field_value(self, container: ItemProxyEntity, value: typing.Any) -> None:
        assert isinstance(value, dict)
        self.__fields = {k: self.__value.create_and_read(self._context, v) for k, v in value.items()}

    def set_value(self, container: ItemProxyEntity, key: str, value: typing.Any) -> None:
        if isinstance(value, Entity):
            field = self.__value.create(self._context)
            field.set_field_value(container, value)  # no container yet
            self.__map[key] = field
        else:
            raise IndexError()


class ReferenceField(Field):
    """A reference field, references another entity without cascading delete."""

    def __init__(self, context: typing.Optional[EntityContext], type: EntityType) -> None:
        super().__init__(context)
        self.__type = type
        self.__reference_uuid: typing.Optional[uuid.UUID] = None
        self.__reference: typing.Optional[ItemProxy] = None  # proxy is only valid when context is valid
        self.__shadow_item: typing.Optional[Entity] = None  # used when proxy is None
        if context:
            super().set_context(None)  # unset it safely
            self.set_context(context)

    def close(self) -> None:
        if self.__reference:
            self.__reference.close()
            self.__reference = None
        super().close()

    def set_context(self, context: typing.Optional[EntityContext]) -> None:
        super().set_context(context)
        if self._context:
            if not self.__reference:
                self.__reference = self._context.create_item_reference(self.__reference_uuid if self.__reference_uuid else None)
            if self.__shadow_item:
                self.__reference.item = self.__shadow_item
                self.__shadow_item = None
        elif self.__reference:
            self.__shadow_item = self.__reference.item
            self.__reference.close()
            self.__reference = None

    def read(self, dict_value: typing.Any) -> Field:
        self.__reference_uuid = uuid.UUID(copy.deepcopy(dict_value))
        if self.__reference and self._context:
            self._context.update_item_reference_uuid(self.__reference, self.__reference_uuid)
        return self

    def write(self) -> DictValue:
        return str(self.__reference_uuid) if self.__reference_uuid else None

    @property
    def field_value(self) -> typing.Any:
        if self.__reference:
            return self.__reference.item
        else:
            return self.__shadow_item

    def set_field_value(self, container: ItemProxyEntity, value: typing.Any) -> None:
        item = typing.cast(Entity, value)
        if item:
            item_uuid = item.uuid  # prefer _get_field_value; but use direct accessor for legacy Swift PersistentObject compatibility
            self.__reference_uuid = item_uuid
            if self.__reference:
                self.__reference.item = item
            else:
                self.__shadow_item = item
        else:
            if self.__reference:
                self.__reference.item = None
            else:
                self.__shadow_item = None
            self.__reference_uuid = None


class ComponentField(Field):
    """A component field, references another entity with cascading delete."""

    def __init__(self, context: typing.Optional[EntityContext], entity_id: str) -> None:
        super().__init__(context)
        self.__type = get_entity_type(entity_id)
        self.__entity: typing.Optional[Entity] = None

    def close(self) -> None:
        if self.__entity:
            self.__entity.close()
            self.__entity = None
        super().close()

    def set_context(self, context: typing.Optional[EntityContext]) -> None:
        super().set_context(context)
        if self.__entity:
            self.__entity._set_entity_context(context)

    def read(self, dict_value: typing.Any) -> Field:
        assert self.__type
        self.__entity = self.__type.create(self._context, dict_value)
        return self

    def write(self) -> DictValue:
        return self.__entity.write_to_dict() if self.__entity else None

    @property
    def field_value(self) -> typing.Any:
        return self.__entity

    def set_field_value(self, container: ItemProxyEntity, value: typing.Any) -> None:
        assert value is None or not value._container
        if self.__entity:
            self.__entity._container = None
            if self.__entity._entity_context:
                self.__entity._set_entity_context(None)
        self.__entity = value
        if self.__entity:
            self.__entity._container = container
            if self._context:
                self.__entity._set_entity_context(self._context)

    def field_by_key(self, key: str) -> Field:
        assert self.__entity
        return self.__entity.get_field(key)


class ComponentPlaceholderField(Field):
    """Keep the dict, but otherwise be non-functional."""

    def __init__(self, context: typing.Optional[EntityContext]) -> None:
        super().__init__(context)
        self.__d = typing.cast(DictValue, None)

    def read(self, dict_value: typing.Any) -> Field:
        self.__d = copy.deepcopy(dict_value)
        return self

    def write(self) -> DictValue:
        return copy.deepcopy(self.__d)


class FieldType(abc.ABC):
    """A field type that provides the ability to create a field of a given type.

    The field class is a callable returning a field. The args and kwargs are passed to the callable.
    """
    def __init__(self, field_class: typing.Callable[..., Field], *args: typing.Any, **kwargs: typing.Any) -> None:
        assert callable(field_class)
        self.__field_class = field_class
        self.__args = args
        self.__kwargs = kwargs

    def __repr__(self) -> str:
        return self._get_repr([])

    def _get_repr(self, parents: typing.List[typing.Any]) -> str:
        raise NotImplementedError()

    def visit(self, value: typing.Any, accessor: Accessor, visitor: Visitor) -> None:
        raise NotImplementedError()

    @property
    def _field_class(self) -> typing.Callable[..., Field]:
        return self.__field_class

    @property
    def _args(self) -> typing.Tuple[typing.Any, ...]:
        return self.__args

    @property
    def _kwargs(self) -> typing.Dict[str, typing.Any]:
        return self.__kwargs

    def _call(self, context: typing.Optional[EntityContext], field_class: typing.Callable[..., Field], *args: typing.Any, **kwargs: typing.Any) -> Field:
        return field_class(context, *args, **kwargs)

    def create(self, context: typing.Optional[EntityContext]) -> Field:
        return self._call(context, self.__field_class, *self.__args, **self.__kwargs)

    def create_and_read(self, context: typing.Optional[EntityContext], dict_value: DictValue) -> Field:
        return self.create(context).read(dict_value)


class PropertyType(FieldType):
    def __init__(self, type: str, optional: bool, default: typing.Any) -> None:
        super().__init__(PropertyField, type, optional, default)
        self.type = type
        self.optional = optional
        self.default = default

    def _get_repr(self, parents: typing.List[typing.Any]) -> str:
        return self.type

    def visit(self, value: typing.Any, accessor: Accessor, visitor: Visitor) -> None:
        pass


class TupleType(FieldType):
    def __init__(self, type: FieldType, optional: bool, default: typing.Optional[typing.Sequence[typing.Any]]) -> None:
        super().__init__(TupleField, type, optional, default)
        self.type = type
        self.optional = optional

    def _get_repr(self, parents: typing.List[typing.Any]) -> str:
        if self not in parents:
            return f"tuple[{self.type}]"
        else:
            return f"tuple[self]"

    def visit(self, value: typing.Tuple[typing.Any], accessor: Accessor, visitor: Visitor) -> None:
        for index, tuple_value in enumerate(value):
            next_accessor = IndexAccessor(accessor, self.type, index)
            # inform the visitor of the tuple entry
            visitor.visit(next_accessor)
            # then visit the value
            self.type.visit(tuple_value, next_accessor, visitor)


class FixedTupleType(FieldType):
    def __init__(self, types: typing.Sequence[FieldType], optional: bool, default: typing.Optional[typing.Tuple[typing.Any, ...]]) -> None:
        super().__init__(FixedTupleField, types, optional, default)
        self.types = list(types)
        self.optional = optional

    def _get_repr(self, parents: typing.List[typing.Any]) -> str:
        types_str = ", ".join(t._get_repr(parents + [self]) if t not in parents else "self" for t in self.types)
        return f"fixed_tuple[{types_str}]"

    def visit(self, value: typing.Tuple[typing.Any], accessor: Accessor, visitor: Visitor) -> None:
        for index, tuple_value in enumerate(value):
            next_accessor = IndexAccessor(accessor, self.types[index], index)
            # inform the visitor of the tuple entry
            visitor.visit(next_accessor)
            # then visit the value
            self.types[index].visit(tuple_value, next_accessor, visitor)


class RecordType(FieldType):
    def __init__(self, field_type_map: typing.Mapping[str, FieldType]) -> None:
        super().__init__(RecordField, field_type_map)
        self.__field_type_map = dict(field_type_map)

    @property
    def _field_type_map(self) -> typing.Mapping[str, FieldType]:
        return self.__field_type_map

    def _get_repr(self, parents: typing.List[typing.Any]) -> str:
        types_str = ", ".join(f"{t}: {f._get_repr(parents + [self]) if f not in parents else 'self'}" for t, f in self.__field_type_map.items())
        return f"record[{types_str}]"

    def visit(self, value: typing.Any, accessor: Accessor, visitor: Visitor) -> None:
        for field_name, field_type in self.__field_type_map.items():
            next_accessor = FieldAccessor(accessor, field_type, field_name)
            # inform the visitor of the field
            visitor.visit(next_accessor)
            # then visit each field
            field_value = getattr(value, field_name)
            if field_value is not None:
                field_type.visit(field_value, next_accessor, visitor)


class ArrayType(FieldType):
    def __init__(self, type: FieldType, optional: bool) -> None:
        super().__init__(ArrayField, type, optional)
        self.type = type
        self.optional = optional

    def _get_repr(self, parents: typing.List[typing.Any]) -> str:
        if self not in parents:
            return f"array[{self.type._get_repr(parents + [self])}]"
        else:
            return f"array[self]"

    def visit(self, value: typing.Sequence[typing.Any], accessor: Accessor, visitor: Visitor) -> None:
        for index, array_value in enumerate(value):
            next_accessor = IndexAccessor(accessor, self.type, index)
            # inform the visitor of the tuple entry
            visitor.visit(next_accessor)
            # then visit the value
            self.type.visit(array_value, next_accessor, visitor)


class MapType(FieldType):
    def __init__(self, key: str, value_type: FieldType, optional: bool) -> None:
        super().__init__(MapField, key, value_type, optional)
        self.key = key
        self.value_type = value_type
        self.optional = optional

    def _get_repr(self, parents: typing.List[typing.Any]) -> str:
        if self not in parents:
            return f"map[{self.key}: {self.value_type._get_repr(parents + [self])}]"
        else:
            return f"map[{self.key}: self]"

    def visit(self, value: typing.Mapping[typing.Any, typing.Any], accessor: Accessor, visitor: Visitor) -> None:
        for map_key, map_value in value.items():
            next_accessor = MapAccessor(accessor, self.value_type, map_key)
            # inform the visitor of the tuple entry
            visitor.visit(next_accessor)
            # then visit the value
            self.value_type.visit(map_value, next_accessor, visitor)


class ReferenceType(FieldType):
    def __init__(self, type: typing.Optional[EntityType]) -> None:
        super().__init__(ReferenceField, type)
        self.type = type

    def _get_repr(self, parents: typing.List[typing.Any]) -> str:
        if self not in parents:
            return f"reference[{self.type._get_repr(parents + [self]) if self.type else 'None'}]"
        else:
            return f"reference[self]"

    def visit(self, value: typing.Any, accessor: Accessor, visitor: Visitor) -> None:
        pass


class ComponentType(FieldType):
    def __init__(self, entity_id: str, required: bool) -> None:
        super().__init__(ComponentField, entity_id)
        self.entity_id = entity_id
        self.required = required

    def create_and_read(self, context: typing.Optional[EntityContext], dict_value: DictValue) -> Field:
        assert isinstance(dict_value, dict)
        d = dict_value
        entity_type = get_entity_type(d["type"])
        if entity_type:
            field_type = entity_type.entity_id if entity_type else self._args[0]
            return self._call(context, self._field_class, *((field_type, ) + self._args[1:]), **self._kwargs).read(dict_value)
        else:
            return ComponentPlaceholderField(context).read(dict_value)

    def _get_repr(self, parents: typing.List[typing.Any]) -> str:
        if self not in parents:
            return f"component[{entity_types[self.entity_id]._get_repr(parents + [self])}]"
        else:
            return f"component[self]"

    def visit(self, value: Entity, accessor: Accessor, visitor: Visitor) -> None:
        entity_types[self.entity_id].visit(value, accessor, visitor)


_EntityTransform = typing.Callable[[PersistentDictType], PersistentDictType]
_EntityTransforms = typing.Tuple[_EntityTransform, _EntityTransform]


class Entity(Observable.Observable):
    """An instance of an entity type.

    To support deepcopy, subclasses must be able to be initialized with no arguments (passing entity_type to this init)
    or override deepcopy.
    """
    def __init__(self, entity_type: typing.Optional[EntityType] = None, context: typing.Optional[EntityContext] = None) -> None:
        super().__init__()
        assert entity_type, str(self.__class__)
        self.__context: typing.Optional[EntityContext] = None
        self.__entity_type = entity_type
        self.__version = entity_type._version
        self.__field_type_map = entity_type._field_type_map
        self.__field_dict : typing.Dict[str, Field] = dict()
        self.__renames = entity_type._renames
        self.__transforms = entity_type._transforms
        self._container = None
        for field_name, field_type in self.__field_type_map.items():
            self.__field_dict[field_name] = field_type.create(self.__context)
        self._set_field_value("uuid", uuid.uuid4())
        self._set_field_value("modified", utcnow())
        if context:
            self._set_entity_context(context)

    def close(self) -> None:
        pass

    def __deepcopy__(self, memo: typing.Dict[typing.Any, typing.Any]) -> Entity:
        entity_copy = self._deepcopy()
        memo[id(self)] = entity_copy
        return entity_copy

    def __repr__(self) -> str:
        return f"entity '{self.__entity_type.entity_id}' at 0x{id(self):x}"

    def _create(self, context: typing.Optional[EntityContext]) -> Entity:
        return self.__class__(self.__entity_type, context)

    def _deepcopy(self) -> Entity:
        context = SimpleEntityContext()
        entity_copy = self._create(context)
        entity_copy.read(self.write_to_dict())
        entity_copy._set_entity_context(None)
        return entity_copy

    @property
    def _entity_context(self) -> typing.Optional[EntityContext]:
        return self.__context

    def _set_entity_context(self, context: typing.Optional[EntityContext]) -> None:
        assert (self.__context is None) != (context is None), f"{self.__context} {context}"
        if self.__context:
            self.__context.unregister(self)
        self.__context = context
        if self.__context:
            self.__context.register(self)
        for field in self.__field_dict.values():
            field.set_context(context)

    def read(self, properties: PersistentMappingType) -> Entity:
        # unregister old uuid
        if self.__context:
            self.__context.unregister(self)
        properties = self.__transforms[0](dict(properties))  # transform forward
        for field_name, field_type in self.__field_type_map.items():
            d = properties.get(self.__renames.get(field_name, field_name))
            if d is not None:
                self.__field_dict[field_name].read(d)
        # register new uuid
        if self.__context:
            self.__context.register(self)
        return self

    def write(self) -> DictValue:
        return self.write_to_dict()

    def write_to_dict(self) -> PersistentDictType:
        d: typing.Dict[str, DictValue] = dict()
        d["type"] = self.__entity_type.entity_id
        if self.__version:
            d["version"] = self.__version
        for field_name, field in self.__field_dict.items():
            dd = field.write()
            if dd is not None:
                d[self.__renames.get(field_name, field_name)] = dd
        return self.__transforms[1](d)  # transform back

    @property
    def entity_type(self) -> EntityType:
        return self.__entity_type

    def _set_modified(self, modified: datetime.datetime) -> None:
        field = self.__get_field("modified")
        if field:
            field.set_field_value(self, modified)
        if self._container:
            self._container._set_modified(modified)

    def __getattr__(self, name: str) -> typing.Any:
        if name in self.__dict__.get("_Entity__field_type_map", dict()):
            return self._get_field_value(name)
        raise AttributeError(f"Unknown attribute {name}")

    def __setattr__(self, name: str, value: typing.Any) -> None:
        field_dict = self.__dict__.get("_Entity__field_dict", dict())
        if name in field_dict:
            self._set_field_value(name, value)
        else:
            super().__setattr__(name, value)

    def __get_field(self, name: str) -> typing.Optional[Field]:
        return self.__field_dict.get(name)

    def get_field(self, name: str) -> Field:
        return typing.cast(Field, self.__get_field(name))

    def _get_field_value(self, name: str) -> typing.Any:
        field = self.__get_field(name)
        if field:
            return field.field_value
        raise AttributeError()

    def _set_field_value(self, name: str, value: typing.Any) -> None:
        field = self.__get_field(name)
        if field:
            field.set_field_value(self, value)
            self._field_value_changed(name, field.write())
            if name not in ("modified", "uuid"):
                self._set_modified(utcnow())
            self.property_changed_event.fire(name)
        else:
            raise AttributeError()

    def _field_value_changed(self, name: str, value: typing.Any) -> None:
        pass

    def _get_array_item(self, name: str, index: int) -> typing.Any:
        array_field = typing.cast(typing.Optional[ArrayField], self.__get_field(name))
        if array_field:
            return array_field.field_value[index]
        else:
            raise AttributeError()

    def _get_array_items(self, name: str) -> typing.Sequence[typing.Any]:
        array_field = typing.cast(typing.Optional[ArrayField], self.__get_field(name))
        if array_field:
            return array_field.field_value
        else:
            raise AttributeError()

    def _insert_item(self, name: str, index: int, item: ItemProxyEntity) -> None:
        array_field = typing.cast(typing.Optional[ArrayField], self.__get_field(name))
        if array_field:
            array_field.insert_value(self, index, item)  # passing self for container
            self.item_inserted_event.fire(name, item, index)
        else:
            raise AttributeError()

    def _append_item(self, name: str, item: ItemProxyEntity) -> None:
        self._insert_item(name, len(self._get_field_value(name)), item)

    def _remove_item(self, name: str, item: ItemProxyEntity) -> None:
        array_field = typing.cast(typing.Optional[ArrayField], self.__get_field(name))
        if array_field:
            index = list(self._get_array_items(name)).index(item)
            array_field.remove_value_at_index(index)  # passing self for container
            self.item_removed_event.fire(name, item, index)
        else:
            raise AttributeError()

    # compatibility functions for persistent object

    def begin_reading(self) -> None:
        pass

    def read_from_dict(self, properties: PersistentMappingType) -> None:
        self.read(properties)

    def finish_reading(self) -> None:
        pass

    def about_to_be_inserted(self, container: typing.Any) -> None:
        self._container = container

    def about_to_be_removed(self, container: typing.Any) -> None:
        self._container = None

    @property
    def container(self) -> typing.Any:
        return self._container

    @property
    def persistent_object_context(self) -> typing.Any:
        return self._entity_context

    @persistent_object_context.setter
    def persistent_object_context(self, value: typing.Any) -> None:
        self._set_entity_context(value)

    @property
    def item_names(self) -> typing.List[str]:
        return [k for k, f in self.__field_type_map.items() if isinstance(f, ComponentType)]

    @property
    def relationship_names(self) -> typing.List[str]:
        return [k for k, f in self.__field_type_map.items() if isinstance(f, ArrayType)]

    def item_specifier(self) -> typing.Any:
        class ItemSpecifier:

            def __init__(self, *, item: typing.Optional[Entity] = None, item_uuid: typing.Optional[uuid.UUID] = None) -> None:
                self.__item_uuid = typing.cast(uuid.UUID, item.uuid) if item else item_uuid
                assert (self.__item_uuid is None) or isinstance(self.__item_uuid, uuid.UUID)

            def __hash__(self) -> typing.Any:
                return hash(self.__item_uuid)

            def __eq__(self, other: typing.Any) -> bool:
                if isinstance(other, self.__class__):
                    return bool(self.__item_uuid == other.__item_uuid)
                return False

            @property
            def item_uuid(self) -> typing.Optional[uuid.UUID]:
                return self.__item_uuid

            def write(self) -> typing.Optional[DictValue]:
                if self.__item_uuid:
                    return str(self.__item_uuid)
                return None

            @staticmethod
            def read(d: DictValue) -> typing.Optional[ItemSpecifier]:
                if isinstance(d, str):
                    return ItemSpecifier(item_uuid=uuid.UUID(d))
                elif isinstance(d, uuid.UUID):
                    return ItemSpecifier(item_uuid=d)
                elif isinstance(d, dict) and "item_uuid" in d:
                    return ItemSpecifier(item_uuid=uuid.UUID(d["item_uuid"]))
                elif isinstance(d, dict) and "uuid" in d:
                    return ItemSpecifier(item_uuid=uuid.UUID(d["uuid"]))
                else:
                    return None

        return ItemSpecifier(item=self)


def no_transform(x: PersistentDictType) -> PersistentDictType:
    return x


class EntityType:
    def __init__(self, entity_id: str, base: typing.Optional[EntityType], version: typing.Optional[int], field_type_map: typing.Mapping[str, FieldType], factory: typing.Optional[typing.Callable[[EntityType, typing.Optional[EntityContext]], Entity]] = None) -> None:
        self.__entity_id = entity_id
        self.__base = base
        self.__version = version
        self.__renames: typing.Dict[str, str] = dict()
        self.__transforms: _EntityTransforms = (no_transform, no_transform)
        self.__field_type_map: typing.Dict[str, FieldType] = dict()
        self.__field_type_map["uuid"] = prop(UUID)
        self.__field_type_map["modified"] = prop(TIMESTAMP)
        self.__factory = factory
        while base:
            for k, v in base._field_type_map.items():
                if not k in ("uuid", "modified"):
                    self.__field_type_map[k] = v
            for k2, v2 in base._renames.items():  # use '2' versions to satisfy mypy
                self.__renames[k2] = v2
            base = base.base
        for k, v in field_type_map.items():
            self.__field_type_map[k] = v
        register_entity_type(entity_id, self)

    def __repr__(self) -> str:
        return self._get_repr([])

    def _get_repr(self, parents: typing.List[typing.Any]) -> str:
        version_str = f", {self.__version}" if self.__version is not None else str()
        base_str = f" ({self.__base.entity_id})" if self.__base else str()
        fields_str = f" (" + ", ".join([f"{n}: {t._get_repr(parents + [self]) if t not in parents else 'self'}" for n, t in self.__field_type_map.items()]) + ")"
        r = f"entity [{self.__entity_id}{version_str}]{base_str}{fields_str}"
        return r

    def visit(self, value: Entity, accessor: Accessor, visitor: Visitor) -> None:
        for field_name, field_type in self.__field_type_map.items():
            next_accessor = FieldAccessor(accessor, field_type, field_name)
            # inform the visitor of the field
            visitor.visit(next_accessor)
            # then visit each field
            field_value = getattr(value, field_name, None)
            if field_value is not None:
                field_type.visit(field_value, next_accessor, visitor)

    @property
    def _version(self) -> typing.Optional[int]:
        return self.__version

    @property
    def _field_type_map(self) -> typing.Mapping[str, FieldType]:
        return self.__field_type_map

    @property
    def _renames(self) -> typing.Mapping[str, str]:
        return self.__renames

    @property
    def _transforms(self) -> _EntityTransforms:
        return self.__transforms

    def create(self, context: typing.Optional[EntityContext] = None, d: typing.Optional[PersistentMappingType] = None) -> Entity:
        type = d.get("type", None) if d else None
        if type:
            concrete_subclasses = self.concrete_subclasses
            if concrete_subclasses:
                for concrete_subclass in concrete_subclasses:
                    if type == concrete_subclass.entity_id:
                        return concrete_subclass.create(context, d)
        entity = self.__factory(self, context) if callable(self.__factory) else Entity(self, context)
        if d is not None:
            entity.read(d)
        return entity

    @property
    def base(self) -> typing.Optional[EntityType]:
        return self.__base

    @property
    def entity_id(self) -> str:
        return self.__entity_id

    def rename(self, field_name: str, storage_field_name: str) -> None:
        self.__renames[field_name] = storage_field_name

    def transform(self, forward: _EntityTransform, backward: _EntityTransform) -> None:
        self.__transforms = (forward, backward)

    def is_subclass_of(self, entity_type: EntityType) -> bool:
        return self.base is not None and (self.base == entity_type or self.base.is_subclass_of(entity_type))

    @property
    def subclasses(self) -> typing.List[EntityType]:
        return [entity_type for entity_type in entity_types.values() if entity_type.is_subclass_of(self)]

    @property
    def concrete_subclasses(self) -> typing.List[EntityType]:
        return [entity_type for entity_type in entity_types.values() if entity_type.is_subclass_of(self) and not entity_type.subclasses]


def prop(type: str, optional: bool = False, *, default: typing.Any = None) -> PropertyType:
    return PropertyType(type, optional, default)

def indefinite_tuple(type: FieldType, optional: bool = False, default: typing.Optional[typing.Sequence[typing.Any]] = None) -> TupleType:
    return TupleType(type, optional, default)

def fixed_tuple(types: typing.List[FieldType], optional: bool = False, default: typing.Optional[typing.Tuple[typing.Any, ...]] = None) -> FixedTupleType:
    return FixedTupleType(types, optional, default)

def record(field_type_map: typing.Dict[str, FieldType]) -> RecordType:
    return RecordType(field_type_map)

def array(type: FieldType, optional: bool = False) -> ArrayType:
    return ArrayType(type, optional)

def map(key: str, value: FieldType, optional: bool = False) -> MapType:
    return MapType(key, value, optional)

def reference(type: typing.Optional[EntityType] = None) -> ReferenceType:
    return ReferenceType(type)

def component(type: typing.Union[EntityType, str], required: bool = True) -> ComponentType:
    if isinstance(type, EntityType):
        return ComponentType(type.entity_id, required)
    else:  # str, used for forward or self references
        return ComponentType(type, required)

def entity(entity_id: str, base: typing.Optional[EntityType], version: typing.Optional[int], field_type_map: typing.Dict[str, FieldType], factory: typing.Optional[typing.Callable[[EntityType, typing.Optional[EntityContext]], Entity]] = None) -> EntityType:
    return EntityType(entity_id, base, version, field_type_map, factory)

def read_json(path: pathlib.Path) -> PersistentDictType:
    """Read the json file from path. Rename path if not readable."""
    properties = dict()
    if path and path.exists():
        try:
            with path.open("r") as fp:
                properties = json.load(fp)
        except Exception:
            os.replace(path, path.with_suffix(".bak"))
    return properties

def read_entity(entity_type: EntityType, context: EntityContext, path: pathlib.Path, o: str) -> Entity:
    """Read the entity from the path."""
    properties = read_json(path)
    return entity_type.create(context, properties)
