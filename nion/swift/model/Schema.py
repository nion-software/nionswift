from __future__ import annotations

import abc
import copy
import datetime
import json
import os
import pathlib
import typing
import uuid

from nion.utils import Converter
from nion.utils import Observable


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


def register_entity_type(entity_id: str, entity: EntityType) -> None:
    entity_types[entity_id] = entity

def get_entity_type(entity_id: str) -> EntityType:
    return entity_types[entity_id]

def build_value(type: str, value) -> typing.Any:
    if value is None:
        return None
    if type in (SET, ):
        return set(value)
    if type in (BOOLEAN, ):
        return bool(value)
    if type in (INT, ):
        return int(value)
    if type in (FLOAT, ):
        return float(value)
    if type in (TIMESTAMP):
        return Converter.DatetimeToStringConverter().convert_back(value)
    if type in (UUID):
        return Converter.UuidToStringConverter().convert_back(value)
    if type in (PATH):
        return Converter.PathToStringConverter().convert_back(value)
    return value


def dict_value(type: str, value):
    if value is None:
        return None
    if type in (SET, ):
        return list(value)
    if type in (BOOLEAN, ):
        return bool(value)
    if type in (INT, ):
        return int(value)
    if type in (FLOAT, ):
        return float(value)
    if type in (TIMESTAMP):
        return Converter.DatetimeToStringConverter().convert(value)
    if type in (UUID):
        return Converter.UuidToStringConverter().convert(value)
    if type in (PATH):
        return Converter.PathToStringConverter().convert(value)
    return value


DictValue = typing.Optional[typing.Union[typing.Dict, typing.List, typing.Tuple, str, int]]


ItemProxyEntity = typing.Optional[typing.Any]  # use this to make it easy to switch to Entity later


class ItemProxy:
    def __init__(self):
        self.__item = None

    def close(self) -> None:
        pass

    @property
    def item(self) -> ItemProxyEntity:
        return self.__item

    @item.setter
    def item(self, item: ItemProxyEntity) -> None:
        self.__item = item


class EntityContext(abc.ABC):

    @abc.abstractmethod
    def create_item_proxy(self) -> ItemProxy: ...


class SimpleEntityContext(EntityContext):

    def create_item_proxy(self) -> ItemProxy:
        return ItemProxy()


class Field(abc.ABC):
    def close(self) -> None:
        pass

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


class PropertyField(Field):
    def __init__(self, context: EntityContext, type: str, optional: bool, default):
        self.__context = context
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
    def __init__(self, context: EntityContext, type: FieldType, optional: bool, default_values):
        assert isinstance(type, FieldType)
        assert default_values is None or isinstance(default_values, (tuple, list))
        self.__context = context
        self.__type = type
        self.__optional = optional
        self.__default_values = list(default_values) if default_values is not None else None
        self.__fields: typing.Optional[typing.Tuple[Field, ...]] = None
        self.read(default_values)

    def close(self) -> None:
        self.__clear()
        super().close()

    def __clear(self):
        if self.__fields is not None:
            for field in self.__fields:
                field.close()
            self.__fields = None

    def read(self, dict_value: typing.Any) -> Field:
        self.__clear()
        if isinstance(dict_value, (tuple, list)):
            self.__fields = tuple(self.__type.create_and_read(self.__context, v) for v in dict_value)
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
        self.__fields = tuple(self.__type.create_and_read(self.__context, v) for v in value)


class FixedTupleField(Field):
    def __init__(self, context: EntityContext, types: typing.Sequence[FieldType], optional: bool, default_values):
        assert default_values is None or isinstance(default_values, (tuple, list))
        self.__context = context
        self.__types = types
        self.__optional = optional
        self.__default_values = list(default_values) if default_values is not None else None
        self.__fields: typing.Optional[typing.Tuple[Field, ...]] = None
        self.read(default_values)

    def close(self) -> None:
        self.__clear()
        super().close()

    def __clear(self):
        if self.__fields is not None:
            for field in self.__fields:
                field.close()
            self.__fields = None

    def read(self, dict_value: typing.Any) -> Field:
        # TODO: the fields should be fixed
        self.__clear()
        if isinstance(dict_value, (tuple, list)):
            self.__fields = tuple(type.create_and_read(self.__context, v) for type, v in zip(self.__types, dict_value))
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
        self.__fields = tuple(type.create_and_read(self.__context, v) for type, v in zip(self.__types, value))


class RecordField(Field):
    def __init__(self, context: EntityContext, field_type_map: typing.Mapping[str, FieldType]):
        self.__context = context
        self.__field_type_map = field_type_map
        self.__field_map: typing.Dict[str, Field] = dict()

    def close(self) -> None:
        for field in self.__field_map.values():
            field.close()
        self.__field_map = None  # type: ignore
        super().close()

    def read(self, dict_value: typing.Any) -> Field:
        if isinstance(dict_value, (dict)):
            self.__field_map = {k: type.create_and_read(self.__context, dict_value.get(k)) for k, type in self.__field_type_map.items()}
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
        return None

    def set_field_value(self, container: ItemProxyEntity, value: typing.Any) -> None:
        pass


class ArrayField(Field):
    def __init__(self, context: EntityContext, type: FieldType, optional: bool):
        self.__context = context
        self.__type = type
        self.__optional = optional
        self.__fields: typing.List[Field] = list()

    def close(self) -> None:
        for field in self.__fields:
            field.close()
        self.__fields = None  # type: ignore
        super().close()

    def read(self, dict_value: typing.Any) -> Field:
        if isinstance(dict_value, (tuple, list)):
            self.__fields = list(self.__type.create_and_read(self.__context, item) for item in dict_value)
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
    def field_value(self) -> typing.Any:
        return [field.field_value for field in self.__fields]

    def set_field_value(self, container: ItemProxyEntity, value: typing.Any) -> None:
        assert isinstance(value, (tuple, list))
        self.__fields = list(self.__type.create_and_read(self.__context, v) for v in value)

    def insert_value(self, container: ItemProxyEntity, index: int, value: typing.Any) -> None:
        if isinstance(value, Entity):
            assert not value._container
            field = self.__type.create(self.__context)
            field.set_field_value(container, value)  # no container yet
            self.__fields.insert(index, field)
        else:
            raise IndexError()

    def remove_value_at_index(self, index: int) -> None:
        field = self.__fields.pop(index)
        field.set_field_value(None, field.field_value)  # no container


class MapField(Field):
    def __init__(self, context: EntityContext, key: FieldType, value: FieldType, optional: bool):
        self.__context = context
        self.__key = key
        self.__value = value
        self.__optional = optional
        self.__map: typing.Dict[str, Field] = dict()

    def close(self) -> None:
        for field in self.__map.values():
            field.close()
        self.__map = None  # type: ignore
        super().close()

    def read(self, dict_value: typing.Any) -> Field:
        if isinstance(dict_value, dict):
            self.__map = {k: self.__value.create_and_read(self.__context, v) for k, v in dict_value.items()}
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
        self.__fields = {k: self.__value.create_and_read(self.__context, v) for k, v in value.items()}


class ReferenceField(Field):
    def __init__(self, context: EntityContext, type: EntityType):
        self.__context = context
        self.__type = type
        self.__reference: typing.Optional[str] = None
        self.__proxy = context.create_item_proxy()

    def close(self) -> None:
        self.__proxy.close()
        self.__proxy = None  # type: ignore
        super().close()

    def read(self, dict_value: typing.Any) -> Field:
        self.__reference = copy.deepcopy(dict_value)
        return self

    def write(self) -> DictValue:
        return copy.deepcopy(self.__reference)

    @property
    def field_value(self) -> typing.Any:
        return self.__proxy.item

    def set_field_value(self, container: ItemProxyEntity, value: typing.Any) -> None:
        item = typing.cast(Entity, value)
        if item:
            item_uuid = item.uuid  # prefer _get_field_value; but use direct accessor for legacy Swift PersistentObject compatibility
            self.__reference = str(item_uuid)
            self.__proxy.item = item
        else:
            self.__reference = None
            self.__proxy.item = None


class ComponentField(Field):
    def __init__(self, context: EntityContext, entity_id: str):
        self.__context = context
        self.__type = get_entity_type(entity_id)
        self.__field: typing.Optional[Entity] = None
        self.__value: ItemProxyEntity = None

    def close(self) -> None:
        if self.__field:
            self.__field.close()
            self.__field = None
        super().close()

    def read(self, dict_value: typing.Any) -> Field:
        self.__field = self.__type.create(self.__context)
        self.__field.read(dict_value)
        return self

    def write(self) -> DictValue:
        return self.__field.write_to_dict() if self.__field else None

    @property
    def field_value(self) -> typing.Any:
        return self.__value

    def set_field_value(self, container: ItemProxyEntity, value: typing.Any) -> None:
        if self.__value:
            self.__value._container = None
        self.__value = value
        if self.__value:
            self.__value._container = container


class FieldType(abc.ABC):
    def __init__(self, field_class: typing.Callable[..., Field], *args, **kwargs):
        assert callable(field_class)
        self.__field_class = field_class
        self.__args = args
        self.__kwargs = kwargs

    @property
    def _field_class(self) -> typing.Callable[..., Field]:
        return self.__field_class

    @property
    def _args(self):
        return self.__args

    @property
    def _kwargs(self):
        return self.__kwargs

    def _call(self, context: EntityContext, field_class: typing.Callable[..., Field], *args, **kwargs) -> Field:
        return field_class(context, *args, **kwargs)

    def create(self, context: EntityContext) -> Field:
        return self._call(context, self.__field_class, *self.__args, **self.__kwargs)

    def create_and_read(self, context: EntityContext, dict_value: DictValue) -> Field:
        return self.create(context).read(dict_value)


class PropertyType(FieldType):
    def __init__(self, type: str, optional: bool, default):
        super().__init__(PropertyField, type, optional, default)
        self.type = type
        self.optional = optional
        self.default = default


class TupleType(FieldType):
    def __init__(self, type: FieldType, optional: bool, default):
        super().__init__(TupleField, type, optional, default)
        self.type = type
        self.optional = optional


class FixedTupleType(FieldType):
    def __init__(self, types: typing.Sequence[FieldType], optional: bool, default):
        super().__init__(FixedTupleField, types, optional, default)
        self.types = list(types)
        self.optional = optional


class RecordType(FieldType):
    def __init__(self, field_type_map: typing.Mapping[str, FieldType]):
        super().__init__(RecordField, field_type_map)
        self.__field_type_map = dict(field_type_map)


class ArrayType(FieldType):
    def __init__(self, type: FieldType, optional: bool):
        super().__init__(ArrayField, type, optional)
        self.type = type
        self.optional = optional


class MapType(FieldType):
    def __init__(self, key: FieldType, value: FieldType, optional: bool):
        super().__init__(MapField, key, value, optional)
        self.key = key
        self.value = value
        self.optional = optional


class ReferenceType(FieldType):
    def __init__(self, type: typing.Optional[EntityType]):
        super().__init__(ReferenceField, type)
        self.type = type


class ComponentType(FieldType):
    def __init__(self, entity_id: str):
        super().__init__(ComponentField, entity_id)
        self.entity_id = entity_id

    def create_and_read(self, context: EntityContext, dict_value: DictValue) -> Field:
        assert isinstance(dict_value, dict)
        d = dict_value
        entity_type = get_entity_type(d["type"])
        assert entity_type
        field_type = entity_type.entity_id if entity_type else self._args[0]
        return self._call(context, self._field_class, *((field_type, ) + self._args[1:]), **self._kwargs).read(dict_value)


class Entity(Observable.Observable):
    """An instance of an entity type.

    """
    def __init__(self, *,
                 type: EntityType,
                 version: typing.Optional[int],
                 context: EntityContext,
                 field_type_map: typing.Mapping[str, FieldType],
                 renames: typing.Mapping[str, str]):
        super().__init__()
        self.__context = context
        self.__entity_type = type
        self.__version = version
        self.__field_type_map = field_type_map
        self.__field_dict : typing.Dict[str, Field] = dict()
        self.__renames = renames
        self._container = None
        self._set_field_value("uuid", uuid.uuid4())
        self._set_field_value("modified", datetime.datetime.utcnow())

    def close(self) -> None:
        pass

    def read(self, properties: typing.Mapping) -> Entity:
        self.__field_dict = dict()
        for field_name, field_type in self.__field_type_map.items():
            d = properties.get(self.__renames.get(field_name, field_name))
            self.__field_dict[field_name] = field_type.create_and_read(self.__context, d)
        return self

    def write_to_dict(self) -> typing.Dict:
        d: typing.Dict[str, DictValue] = dict()
        d["type"] = self.__entity_type.entity_id
        if self.__version:
            d["version"] = self.__version
        for field_name, field in self.__field_dict.items():
            dd = field.write()
            if dd is not None:
                d[self.__renames.get(field_name, field_name)] = dd
        return d

    @property
    def entity_type(self) -> EntityType:
        return self.__entity_type

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
        if not name in self.__field_dict and name in self.__field_type_map:
            self.__field_dict[name] = self.__field_type_map[name].create(self.__context)
        return self.__field_dict.get(name)

    def _get_field_value(self, name: str) -> typing.Any:
        field = self.__get_field(name)
        if field:
            return field.field_value
        raise AttributeError()

    def _set_field_value(self, name: str, value: typing.Any) -> None:
        field = self.__get_field(name)
        if field:
            field.set_field_value(self, value)
            self.property_changed_event.fire(name)
        else:
            raise AttributeError()

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
        else:
            raise AttributeError()

    def _append_item(self, name: str, item: ItemProxyEntity) -> None:
        self._insert_item(name, len(self._get_field_value(name)), item)

    def _remove_item(self, name: str, item: ItemProxyEntity) -> None:
        array_field = typing.cast(typing.Optional[ArrayField], self.__get_field(name))
        if array_field:
            index = typing.cast(typing.List, self._get_array_items(name)).index(item)
            array_field.remove_value_at_index(index)  # passing self for container
        else:
            raise AttributeError()


class EntityType:
    def __init__(self, entity_id: str, base: typing.Optional[EntityType], version: typing.Optional[int], field_type_map: typing.Mapping[str, FieldType]):
        self.__entity_id = entity_id
        self.__base = base
        self.__version = version
        self.__renames: typing.Dict[str, str] = dict()
        self.__field_type_map: typing.Dict[str, FieldType] = dict()
        self.__field_type_map["uuid"] = prop(UUID)
        self.__field_type_map["modified"] = prop(TIMESTAMP)
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

    @property
    def _field_type_map(self) -> typing.Mapping[str, FieldType]:
        return self.__field_type_map

    @property
    def _renames(self) -> typing.Mapping[str, str]:
        return self.__renames

    def create(self, context: EntityContext, d: typing.Optional[typing.Dict] = None) -> Entity:
        entity = Entity(**self.entity_init_kwargs(context))
        if d is not None:
            entity.read(d)
        return entity

    def entity_init_kwargs(self, context: EntityContext) -> typing.Dict[str, typing.Any]:
        return {
            "type": self,
            "version": self.__version,
            "context": context,
            "field_type_map": self.__field_type_map,
            "renames": self.__renames,
        }

    @property
    def base(self) -> typing.Optional[EntityType]:
        return self.__base

    @property
    def entity_id(self) -> str:
        return self.__entity_id

    def rename(self, field_name: str, storage_field_name: str) -> None:
        self.__renames[field_name] = storage_field_name

    def is_subclass_of(self, entity_type: EntityType) -> bool:
        return self.base is not None and (self.base == entity_type or self.base.is_subclass_of(entity_type))

    @property
    def subclasses(self) -> typing.List[EntityType]:
        return [entity_type for entity_type in entity_types.values() if entity_type.is_subclass_of(self)]

    @property
    def concrete_subclasses(self) -> typing.List[EntityType]:
        return [entity_type for entity_type in entity_types.values() if entity_type.is_subclass_of(self) and not entity_type.subclasses]


def prop(type: str, optional: bool=False, *, default=None) -> PropertyType:
    return PropertyType(type, optional, default)

def indefinite_tuple(type: FieldType, optional: bool=False, default=None) -> TupleType:
    return TupleType(type, optional, default)

def fixed_tuple(types: typing.List[FieldType], optional: bool = False, default=None) -> FixedTupleType:
    return FixedTupleType(types, optional, default)

def record(field_type_map: typing.Dict[str, FieldType]) -> RecordType:
    return RecordType(field_type_map)

def array(type: FieldType, optional: bool = False) -> ArrayType:
    return ArrayType(type, optional)

def map(key: FieldType, value: FieldType, optional: bool = False) -> MapType:
    return MapType(key, value, optional)

def reference(type: typing.Optional[EntityType] = None) -> ReferenceType:
    return ReferenceType(type)

def component(type: typing.Union[EntityType, str]) -> ComponentType:
    if isinstance(type, EntityType):
        return ComponentType(type.entity_id)
    else:  # str, used for forward or self references
        return ComponentType(type)

def entity(entity_id: str, base: typing.Optional[EntityType], version: typing.Optional[int], field_type_map: typing.Dict[str, FieldType]) -> EntityType:
    return EntityType(entity_id, base, version, field_type_map)

def read_json(path: pathlib.Path) -> typing.Dict:
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
