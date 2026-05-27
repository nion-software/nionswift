# Nion Swift Persistent Object Model

This document defines persistent object model concepts. Specific methods and parameters are documented in the code itself.

The persistent object model is the set of objects that hold the state of the application and are persistent, i.e. written to storage and reloaded. It also describes the properties of the objects and the relationships to other objects. Within Swift, the persistent object model consists of objects such as data items, display items, and computations.

Persistent objects are defined by a schema configured in their `__init__` method. The schema defines properties and relationships to other persistent objects. Relationships can be one-to-one or one-to-many, and one-to-many relationships are ordered. Within Swift, the `Model.py` module also provides a description of the persistent object model.

Persistent objects store a `"type"` property that determines the class during load. This acts as the discriminator for polymorphic objects.

Persistent objects have a unique identifier that is used to reference the object in relationships and for persistence. The unique identifier is automatically generated when the object is created.

Persistent objects also have a `modified` timestamp that is automatically updated whenever the object is modified. The modified timestamp can be used to determine when an object was last changed.

Properties have a Python type, a persistent value representation, and accessor methods that convert between the persistent value representation and the Python type. See "Persistent Object Properties" below.

When a persistent object is modified, the changes are automatically written to storage. When the application is restarted, the objects are automatically loaded from storage. The persistence mechanism supports versioning and migration of objects as the schema evolves over time.

Changes to model objects trigger change events: property change events and item inserted/removed events. Other model objects and UI may be listeners for those change events and respond accordingly. These events are defined in the `nion.utils.Observable.Observable` base class.

Persistent objects can have read-only dependent values that are computed from property values. The persistent object is responsible for triggering a property change event for the dependent value when the underlying property values change. The dependent value is not stored in persistence, but is computed at runtime.

## Implementation

Persistent objects are implemented as subclasses of `nion.swift.model.Persistence.PersistentObject`. The `PersistentObject` base class provides the core functionality for persistence, change events, relationship and lifecycle management, and unique identifiers. Subclasses define their schema in the `__init__` method using the `define_type`, `define_property`, `define_item`, and `define_relationship` methods.

The `define_property` method is used to define non-relationship properties (property values). It takes parameters that specify the storage key, the initial persistent value representation, a validator function, a reader and writer function, and a method to handle property changes.

The `define_relationship` method is used to define one-to-many relationships to other persistent objects. It takes parameters that specify the storage key, a factory method used when reading related persistent objects from storage, and methods to handle insertion and removal of the related persistent objects.

The `define_item` method is used to define a one-to-one relationship to another persistent object. It takes parameters that specify the storage key, a factory method used when reading the related persistent object from storage, and a method to handle setting and clearing the related persistent object.

The persistent objects do not automatically expose the properties and relationships as attributes of the Python object. Instead, the persistent objects must define custom getter and setter methods for the properties and getter, setter, insert, and remove methods for the relationships. A property can be read-only by defining only a getter method.

The getter and setter methods can use `nion.swift.model.Persistence.PersistentObject._get_persistent_property_value` to get the persistent value representation for a property, and `nion.swift.model.Persistence.PersistentObject._set_persistent_property_value` to set the value for a property from its persistent value representation.

The getter and setter methods for one-to-many relationships can use `nion.swift.model.Persistence.PersistentObject._get_relationship_values` to get the related persistent objects.

The persistent object should define methods for inserting and removing related persistent objects for one-to-many relationships. Those methods can use `nion.swift.model.Persistence.PersistentObject.insert_model_item` and `nion.swift.model.Persistence.PersistentObject.remove_model_item` to manage the relationships and trigger change events.

The getter and setter methods for one-to-one relationships can use `nion.swift.model.Persistence.PersistentObject.get_item` to get the related persistent object and `nion.swift.model.Persistence.PersistentObject.set_item` to set the related persistent object.

The properties should be named as nouns and should fit the sentence "The [object] has a [property]". The relationships should be named as plural nouns and should fit the sentence "The [object] has [relationship]". The one-to-one relationships should be named as nouns and should fit the sentence "The [object] has a [relationship]".

The getter, setter, insert, remove, and item methods should be grouped together in the class implementation and appear in the order they are defined in `__init__`.

Note for AI-assisted coding: `define_property` should pass `hidden=True`. This will be default in future versions.

## Threading

Persistent objects can be read and modified at any time from the main thread, including during async methods. The persistent objects can also be read from other threads, although care must be taken to ensure the objects are in a consistent state.

## Undo

In order to support undo, modifications to the established model objects should generally be initiated through undoable commands.

## Handling Change Events

Observers can directly listen to property changes and relationship changes using the events defined in the `nion.utils.Observable.Observable` base class.

Change notifications occur after the change has occurred. Dependent property change notifications occur after the primary property has been updated.

Additional tools for handling change events include `nion.utils.Model.ValueModel` and `nion.utils.Stream.AbstractStream`.

Value models can observe persistent objects and provide abstracted read/write behavior. They can be chained to create event processing pipelines.

Streams can observe persistent objects or value model objects for read-only change propagation. Streams emit events when observed properties change and can be chained for transformation.

## Persistent Object Properties

A property has a Python type, a persistent value representation, and accessor methods that convert between the persistent value representation and the Python type. The persistent value representation is used for storage and must be composed exclusively of nested dicts, lists, strings, numbers, booleans, and None values, while the property value is the runtime representation used in the application.

The accessor methods convert between the persistent value representation and the Python type. The getter method converts the persistent value representation to the Python type, and the setter method converts the Python type to the persistent value representation.

The Python type can be the same as the persistent value representation, but it can also be a different type. For example, a property that represents a point in 2D space could have a persistent value representation of a list of two numbers, and a Python type of `Geometry.FloatPoint`. It can also be a dataclass, named tuple, custom class, enums, etc.

The Python type should be self-contained and not hold references to other persistent objects. If the property value needs to reference other persistent objects, either a one-to-many or a one-to-one relationship should be used instead.

If the Python type is mutable, reading it and modifying it will not automatically write it to storage. The persistent object will only be updated when the property value is set.

A common scenario is to have a Python class (or `dataclass`) as the Python type for a property. The class can define methods to convert to and from a persistent value representation. The persistent object can implement accessor methods that use those class methods to convert between the persistent value representation and the Python type.

If the type is polymorphic, the persistent value representation should include a discriminator to indicate the type of the value.

The class does not usually need an explicit unique identifier like a persistent object, since it is stored as part of the persistent object and not referenced in relationships.

The class may optionally be versioned. In this case, a `"version"` discriminator can optionally be included in the persistent value representation to indicate the version of the value. The lack of a version typically means "first version".

A property that is a list could also generate change events for items being added and removed from the list, similar to a one-to-many relationship. In this case, the persistent object would need to define custom methods for handling item changes to trigger the appropriate change events.

## Backwards Compatibility

The persistence mechanism supports versioning and migration of objects as the schema evolves over time. When loading objects, the system can detect the version of the persisted data and apply necessary transformations to ensure compatibility with the current schema.

It is acceptable to use default values for new properties when loading older persistent objects that do not have those properties. However, care should be taken to ensure that the default values do not lead to inconsistent states or unintended behavior.

It is not required to maintain backwards compatibility for persistent objects if loading persistent objects with new fields in older versions works correctly by ignoring the new fields; exceptions may apply.

## Cascade Behavior

Relationships define ownership and lifecycle behavior between objects. Cascade rules should be explicit so insertion, removal, and deletion preserve model consistency.

## Example Persistent Object Implementation

```python
import typing

from nion.swift.model import Changes
from nion.swift.model import Graphics
from nion.swift.model import Persistence
from nion.utils import Geometry


class ExamplePersistentObject(Persistence.PersistentObject):
    def __init__(self):
        super().__init__()
        self.define_type("ExamplePersistentObject")
        
        # all properties, one-to-one relationships, and one-to-many-relationships should be hidden. this will be default in future versions.
        
        # all properties should use the changed method to trigger change notifications for dependent properties.
        
        # define name property. no validator.
        self.define_property("name", "", changed=self.__property_changed, hidden=True)

        # define index property. use validator to ensure index is non-negative.
        self.define_property("index", 0, validate=self.__validate_index, changed=self.__property_changed, hidden=True)
        
        # define a position property. pass the internal storage format.
        self.define_property("position", (3.0, 4.0), changed=self.__property_changed, hidden=True)

        # define a relationship.
        self.define_relationship("related_items", related_item_factory, insert=self.__insert_related_item, remove=self.__remove_related_item, hidden=True)

        self.define_item("single_item", single_item_factory, changed=self.__item_changed, hidden=True)

    def __validate_index(self, value: int) -> int:
        return value if value >= 0 else 0

    # handle property changed by notifying listeners of the property change.
    def __property_changed(self, property_name: str, value: typing.Any) -> None:
        self.notify_property_changed(property_name)

    # handle item changed by notifying listeners of the property and item change. this method has a different signature from property changed.
    def __item_changed(self, component_name: str, old_value: Graphics.Graphic | None, new_value: Graphics.Graphic | None) -> None:
        if old_value != new_value:
            self.notify_property_changed(component_name)
            if new_value:
                self.notify_set_item(component_name, new_value)
            else:
                self.notify_clear_item(component_name)

    # handle insert related item.
    def __insert_related_item(self, before_index: int, item: Graphics.Graphic) -> None:
        # notify the relationship of the item being inserted, so listeners can observe the individual item change.
        self.notify_insert_item("related_items", item, before_index)
        # notify as a property, too, so listeners can treat the relationship as a whole.
        self.notify_property_changed("related_items")
        
    # handle remove related item.
    def __remove_related_item(self, index: int, item: Graphics.Graphic) -> None:
        # notify the relationship of the item being removed, so listeners can observe the individual item change.
        self.notify_remove_item("related_items", item, index)
        # notify as a property, too, so listeners can treat the relationship as a whole.
        self.notify_property_changed("related_items")

    @property
    def name(self) -> str | None:
        return typing.cast(str | None, self._get_persistent_property_value("name"))

    @name.setter
    def name(self, value: str | None) -> None:
        self._set_persistent_property_value("name", value)

    @property
    def index(self) -> int | None:
        return typing.cast(int | None, self._get_persistent_property_value("index"))
    
    @index.setter
    def index(self, value: int | None) -> None:
        self._set_persistent_property_value("index", value)

    @property
    def position(self) -> Geometry.FloatPoint | None:
        position_tuple = typing.cast(Geometry.PointFloatTuple | None, self._get_persistent_property_value("position"))
        return Geometry.FloatPoint.make(position_tuple) if position_tuple is not None else None

    @position.setter
    def position(self, value: Geometry.FloatPoint | None) -> None:
        self._set_persistent_property_value("position", tuple(value) if value is not None else None)

    @property
    def related_items(self) -> typing.Sequence[Graphics.Graphic]:
        return typing.cast(typing.Sequence[Graphics.Graphic], self._get_relationship_values("related_items"))
    
    @property
    def single_item(self) -> Graphics.Graphic | None:
        return typing.cast(Graphics.Graphic | None, self.get_item("single_item"))
    
    @single_item.setter
    def single_item(self, value: Graphics.Graphic | None) -> None:
        self.set_item("single_item", value)
    
    def insert_related_item(self, before_index: int, item: Graphics.Graphic) -> None:
        self.insert_model_item(self, "related_items", before_index, item)
    
    def remove_related_item(self, graphic: Graphics.Graphic, *, safe: bool = False) -> Changes.UndeleteLog:
        return self.remove_model_item(self, "related_items", graphic, safe=safe)
    
        
def related_item_factory(lookup_id: typing.Callable[[str], str]) -> Graphics.Graphic:
    return Graphics.factory(lookup_id)


def single_item_factory(lookup_id: typing.Callable[[str], str]) -> Graphics.Graphic:
    return Graphics.factory(lookup_id)
```

## Example Polymorphic Python Object Implementation

```python
import enum
import typing


PersistentDictType = typing.Mapping[str, typing.Any]


class ShapeType(enum.Enum):
    RECTANGLE = "rectangle"
    LINE = "line"


class Shape:
    def __init__(self, shape_type: ShapeType) -> None:
        self.shape_type = shape_type

    def to_dict(self) -> dict[str, typing.Any]:
        return {
            "type": self.shape_type.value
        }

    @classmethod
    def from_dict(cls, d: PersistentDictType) -> Shape | None:
        input_type = d.get("type", None)
        match input_type:
            case ShapeType.RECTANGLE.value:
                return RectangleShape(d)
            case ShapeType.LINE.value:
                return LineShape(d)
            case _:
                return None


class RectangleShape(Shape):
    def __init__(self, d: PersistentDictType) -> None:
        super().__init__(ShapeType.RECTANGLE)
        self.width = d.get("width", 0.0)
        self.height = d.get("height", 0.0)

    def to_dict(self) -> dict[str, typing.Any]:
        d = super().to_dict()
        if self.width:
            d["width"] = self.width
        if self.height:
            d["height"] = self.height
        return d


class LineShape(Shape):
    def __init__(self, d: PersistentDictType) -> None:
        super().__init__(ShapeType.LINE)
        self.length = d.get("length", 0.0)

    def to_dict(self) -> dict[str, typing.Any]:
        d = super().to_dict()
        if self.length:
            d["length"] = self.length
        return d
```
