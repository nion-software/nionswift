"""
    Provide symbolic math services.

    The goal is to provide a module (namespace) where users can be provided with variables representing
    data items (directly or indirectly via reference to workspace panels).

    DataNodes represent data items, operations, numpy arrays, and constants.
"""
from __future__ import annotations

# standard libraries
import ast
import contextlib
import copy
import datetime
import difflib
import enum
import functools
import gettext
import sys
import threading
import time
import traceback
import typing
import uuid

# local libraries
from nion.data import Core
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift.model import Activity
from nion.swift.model import DataItem
from nion.swift.model import DataStructure
from nion.swift.model import DisplayItem
from nion.swift.model import Graphics
from nion.swift.model import Model
from nion.swift.model import Notification
from nion.swift.model import Persistence
from nion.swift.model import PlugInManager
from nion.swift.model import Schema
from nion.swift.model import Utility
from nion.utils import DateTime
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import Observable
from nion.utils import Process
from nion.utils import ReferenceCounting

if typing.TYPE_CHECKING:
    from nion.swift.model import Project

computation_min_period = 0.0
computation_min_factor = 0.0


_APIComputation = typing.Any

_ = gettext.gettext


def update_diff_notify(o: Observable.Observable, name: str, before_items: typing.List[Persistence.PersistentObject], after_items: typing.List[Persistence.PersistentObject]) -> None:
    assert all(bi is not None for bi in after_items)
    after_items = copy.copy(after_items)
    s = difflib.SequenceMatcher(None, before_items, after_items)
    # opcodes will describe how to make first list equal to the second list
    adjust = 0
    for tag, i1, i2, j1, j2 in s.get_opcodes():
        if tag == "delete":
            for index in range(i1, i2):
                o.notify_remove_item(name, before_items.pop(i1 + adjust), i1 + adjust)
            adjust -= (i2 - i1)
        elif tag == "replace":
            for index in range(i1, i2):
                o.notify_remove_item(name, before_items.pop(i1 + adjust), i1 + adjust)
            for index in range(j1, j2):
                before_items.insert(i1 + adjust + (index - j1), after_items[index])
                o.notify_insert_item(name, after_items[index], i1 + adjust + (index - j1))
            adjust += (j2 - j1) - (i2 - i1)
        elif tag == "insert":
            for index in range(j1, j2):
                before_items.insert(i1 + adjust + (index - j1), after_items[index])
                o.notify_insert_item(name, after_items[index], i1 + adjust + (index - j1))
            adjust += (j2 - j1)
    assert before_items == after_items


class ComputationOutput(Persistence.PersistentObject):
    """Tracks an output of a computation."""

    def __init__(self, name: typing.Optional[str] = None, specifier: typing.Optional[Specifier] = None,
                 specifiers: typing.Optional[typing.Sequence[Specifier]] = None,
                 label: typing.Optional[str] = None) -> None:  # defaults are None for factory
        super().__init__()
        self.define_type("output")
        self.define_property("name", name, changed=self.__property_changed, hidden=True)
        self.define_property("label", label if label else name, hidden=True, changed=self.__property_changed)
        self.define_item("specifier", typing.cast(Persistence._PersistentObjectFactoryFn, specifier_factory), changed=self.__specifier_changed, hidden=True)
        self.define_relationship("specifiers", typing.cast(Persistence._PersistentObjectFactoryFn, specifier_factory), insert=self.__specifier_inserted, remove=self.__specifier_removed, hidden=True)
        self.__bound_item: typing.Optional[BoundItemBase] = None
        self.__bound_item_base_item_inserted_event_listener: typing.Optional[Event.EventListener] = None
        self.__bound_item_base_item_removed_event_listener: typing.Optional[Event.EventListener] = None
        if specifier:
            self.specifier = specifier
        if specifiers is not None:  # form a list even if it is empty
            self.specifiers = specifiers

    def close(self) -> None:
        self.unbind()
        # continue closing
        super().close()

    def persistent_object_context_changed(self) -> None:
        if self.container:
            self.bind()

    @property
    def bound_item(self) -> typing.Optional[BoundItemBase]:
        return self.__bound_item

    @bound_item.setter
    def bound_item(self, bound_item: typing.Optional[BoundItemBase]) -> None:
        if self.__bound_item_base_item_inserted_event_listener:
            self.__bound_item_base_item_inserted_event_listener.close()
            self.__bound_item_base_item_inserted_event_listener = None
        if self.__bound_item_base_item_removed_event_listener:
            self.__bound_item_base_item_removed_event_listener.close()
            self.__bound_item_base_item_removed_event_listener = None
        if self.__bound_item:
            self.__bound_item.close()
        self.__bound_item = bound_item
        if self.__bound_item:
            self.__bound_item_base_item_inserted_event_listener = self.__bound_item.item_inserted_event.listen(self.item_inserted_event.fire)
            self.__bound_item_base_item_removed_event_listener = self.__bound_item.item_removed_event.listen(self.item_removed_event.fire)
            for index, base_item in enumerate(self.__bound_item.base_items):
                self.notify_insert_item("base_items", base_item, index)
        self.notify_property_changed("bound_item")

    @property
    def specifier(self) -> typing.Optional[Specifier]:
        return typing.cast(typing.Optional[Specifier], self.get_item("specifier"))

    @specifier.setter
    def specifier(self, value: typing.Optional[Specifier]) -> None:
        self.set_item("specifier", value)

    @property
    def specifiers(self) -> typing.Sequence[typing.Optional[Specifier]]:
        return typing.cast(typing.Sequence[typing.Optional[Specifier]], self._get_relationship_values("specifiers"))

    @specifiers.setter
    def specifiers(self, value: typing.Sequence[typing.Optional[Specifier]]) -> None:
        needs_binding = True
        while len(self.specifiers):
            self.remove_item("specifiers", typing.cast(Persistence.PersistentObject, self.specifiers[-1]))
            needs_binding = False
        for specifier in value:
            self.append_item("specifiers", typing.cast(Persistence.PersistentObject, specifier))
            needs_binding = False
        if needs_binding and self.container:
            self.bind()

    def __property_changed(self, name: str, value: typing.Any) -> None:
        self.notify_property_changed(name)

    def __specifier_changed(self, name: str, old_value: typing.Any, new_value: typing.Any) -> None:
        # rebind first, so that property changed listeners get the right value
        if self.container:
            self.bind()
        # notify
        self.notify_property_changed(name)

    def __specifier_inserted(self, name: str, before_index: int, variable: ComputationVariable) -> None:
        # rebind first, so that property changed listeners get the right value
        if self.container:
            self.bind()
        # notify
        self.notify_property_changed(name)

    def __specifier_removed(self, name: str, index: int, variable: ComputationVariable) -> None:
        # rebind first, so that property changed listeners get the right value
        if self.container:
            self.bind()
        # notify
        self.notify_property_changed(name)

    def bind(self) -> None:
        if self.specifier:
            self.bound_item = self.specifier.get_bound_item(self)
        else:
            self.bound_item = BoundList([object_specifier.get_bound_item(self) if object_specifier else None for object_specifier in self.specifiers])

    def unbind(self) -> None:
        self.bound_item = None

    @property
    def output_items(self) -> typing.List[Persistence.PersistentObject]:
        bound_item = self.bound_item
        if isinstance(bound_item, BoundList):
            return [item.value for item in bound_item.get_items() if item and item.value is not None]
        elif bound_item and bound_item.value is not None:
            return [bound_item.value]
        return list()

    @property
    def is_resolved(self) -> bool:
        if not self.specifier and not self.specifiers:
            return True  # nothing specified, so it is valid
        bound_item = self.bound_item
        if isinstance(bound_item, BoundList):
            return all(bound_item.get_items())
        return bound_item is not None and bound_item.value is not None

    @property
    def name(self) -> typing.Optional[str]:
        return typing.cast(typing.Optional[str], self._get_persistent_property_value("name"))

    @name.setter
    def name(self, value: typing.Optional[str]) -> None:
        self._set_persistent_property_value("name", value)

    @property
    def label(self) -> str:
        # for registered computations, the computation class takes precedence in defining the labels.
        computation = self.container
        if isinstance(computation, Computation) and computation.processing_id:
            compute_class = _computation_types.get(computation.processing_id)
            if compute_class:
                label = typing.cast(typing.Optional[str], getattr(compute_class, "outputs", dict()).get(self.name, dict()).get("label", str()))
                if label:
                    return label
        # not a registered computation, fall back to label or name.
        return typing.cast(str, self._get_persistent_property_value("label") or self.name or str())

    @label.setter
    def label(self, value: str) -> None:
        self._set_persistent_property_value("label", value)


class Specifier(Schema.Entity):
    def __init__(self, entity_type: typing.Optional[Schema.EntityType] = None,
                 context: typing.Optional[Schema.EntityContext] = None, *, version: typing.Optional[int] = None,
                 reference: typing.Optional[Persistence.PersistentObject] = None) -> None:
        super().__init__(entity_type or Model.Specifier, context)
        self.persistent_storage = None
        if version is not None:
            self._set_field_value("version", version)
        if reference is not None:
            self._set_field_value("reference", reference)

    def __eq__(self, other: typing.Any) -> bool:
        if isinstance(other, self.__class__):
            return self.write() == other.write()
        return False

    def __hash__(self) -> typing.Any:
        return hash(self.uuid)

    @property
    def variable_type(self) -> ComputationVariableType:
        return _map_identifier_to_variable_type[self.entity_type.entity_id]

    @property
    def version(self) -> int:
        return typing.cast(int, self._get_field_value("version"))

    @property
    def reference(self) -> typing.Optional[Persistence.PersistentObject]:
        return typing.cast(Persistence.PersistentObject, self._get_field_value("reference"))

    @reference.setter
    def reference(self, value: typing.Optional[Persistence.PersistentObject]) -> None:
        self._set_field_value("reference", value)

    @property
    def reference_uuid(self) -> typing.Optional[uuid.UUID]:
        reference = self.reference
        return reference.uuid if reference else typing.cast(Schema.ReferenceField, self.get_field("reference")).reference_uuid

    def get_bound_item(self, container: Persistence.PersistentObject, secondary_specifier: typing.Optional[Specifier] = None, property_name: typing.Optional[str] = None) -> typing.Optional[BoundItemBase]:
        raise NotImplementedError()

    # standard overrides from entity to fit within persistent object architecture

    def _field_value_changed(self, name: str, value: typing.Any) -> None:
        # this is called when a property changes. to be compatible with the older
        # persistent object structure, check if persistent storage exists and pass
        # the message along to persistent storage.
        persistent_storage = typing.cast(Persistence.PersistentStorageInterface, getattr(self, "persistent_storage", None))
        if persistent_storage:
            if value is not None:
                persistent_storage.set_property(typing.cast(Persistence.PersistentObject, self), name, value)
            else:
                persistent_storage.clear_property(typing.cast(Persistence.PersistentObject, self), name)


class EmptySpecifier(Specifier):
    def __init__(self, entity_type: typing.Optional[Schema.EntityType] = None, context: typing.Optional[Schema.EntityContext] = None, *, version: typing.Optional[int] = None, reference: typing.Optional[Persistence.PersistentObject] = None) -> None:
        super().__init__(Model.EmptySpecifier, context, version=version, reference=reference)

    def get_bound_item(self, container: Persistence.PersistentObject, secondary_specifier: typing.Optional[Specifier] = None, property_name: typing.Optional[str] = None) -> typing.Optional[BoundItemBase]:
        return None


class DataSourceSpecifier(Specifier):
    def __init__(self, entity_type: typing.Optional[Schema.EntityType] = None, context: typing.Optional[Schema.EntityContext] = None, *, version: typing.Optional[int] = None, reference: typing.Optional[Persistence.PersistentObject] = None) -> None:
        super().__init__(Model.DataSourceSpecifier, context, version=version, reference=reference)

    def get_bound_item(self, container: Persistence.PersistentObject, secondary_specifier: typing.Optional[Specifier] = None, property_name: typing.Optional[str] = None) -> typing.Optional[BoundItemBase]:
        return BoundDataSource(container, self, secondary_specifier)


class DataItemSpecifier(Specifier):
    def __init__(self, entity_type: typing.Optional[Schema.EntityType] = None, context: typing.Optional[Schema.EntityContext] = None, *, version: typing.Optional[int] = None, reference: typing.Optional[Persistence.PersistentObject] = None) -> None:
        super().__init__(Model.DataItemSpecifier, context, version=version, reference=reference)

    def get_bound_item(self, container: Persistence.PersistentObject, secondary_specifier: typing.Optional[Specifier] = None, property_name: typing.Optional[str] = None) -> typing.Optional[BoundItemBase]:
        return BoundDataItem(container, self)


class GraphicSpecifier(Specifier):
    def __init__(self, entity_type: typing.Optional[Schema.EntityType] = None, context: typing.Optional[Schema.EntityContext] = None, *, version: typing.Optional[int] = None, reference: typing.Optional[Persistence.PersistentObject] = None) -> None:
        super().__init__(Model.GraphicSpecifier, context, version=version, reference=reference)

    def get_bound_item(self, container: Persistence.PersistentObject, secondary_specifier: typing.Optional[Specifier] = None, property_name: typing.Optional[str] = None) -> typing.Optional[BoundItemBase]:
        return BoundGraphic(container, self, property_name)


class StructureSpecifier(Specifier):
    def __init__(self, entity_type: typing.Optional[Schema.EntityType] = None, context: typing.Optional[Schema.EntityContext] = None, *, version: typing.Optional[int] = None, reference: typing.Optional[Persistence.PersistentObject] = None) -> None:
        super().__init__(Model.StructureSpecifier, context, version=version, reference=reference)

    def get_bound_item(self, container: Persistence.PersistentObject, secondary_specifier: typing.Optional[Specifier] = None, property_name: typing.Optional[str] = None) -> typing.Optional[BoundItemBase]:
        return BoundDataStructure(container, self, property_name)


class DataSpecifier(Specifier):
    def __init__(self, entity_type: typing.Optional[Schema.EntityType] = None, context: typing.Optional[Schema.EntityContext] = None, *, version: typing.Optional[int] = None, reference: typing.Optional[Persistence.PersistentObject] = None) -> None:
        super().__init__(Model.DataSpecifier, context, version=version, reference=reference)

    def get_bound_item(self, container: Persistence.PersistentObject, secondary_specifier: typing.Optional[Specifier] = None, property_name: typing.Optional[str] = None) -> typing.Optional[BoundItemBase]:
        return BoundData(container, self)


class DisplayDataSpecifier(Specifier):
    def __init__(self, entity_type: typing.Optional[Schema.EntityType] = None, context: typing.Optional[Schema.EntityContext] = None, *, version: typing.Optional[int] = None, reference: typing.Optional[Persistence.PersistentObject] = None) -> None:
        super().__init__(Model.DisplayDataSpecifier, context, version=version, reference=reference)

    def get_bound_item(self, container: Persistence.PersistentObject, secondary_specifier: typing.Optional[Specifier] = None, property_name: typing.Optional[str] = None) -> typing.Optional[BoundItemBase]:
        return BoundDisplayData(container, self, secondary_specifier)


class CroppedDataSpecifier(Specifier):
    def __init__(self, entity_type: typing.Optional[Schema.EntityType] = None, context: typing.Optional[Schema.EntityContext] = None, *, version: typing.Optional[int] = None, reference: typing.Optional[Persistence.PersistentObject] = None) -> None:
        super().__init__(Model.CroppedDataSpecifier, context, version=version, reference=reference)

    def get_bound_item(self, container: Persistence.PersistentObject, secondary_specifier: typing.Optional[Specifier] = None, property_name: typing.Optional[str] = None) -> typing.Optional[BoundItemBase]:
        return BoundCroppedData(container, self, secondary_specifier)


class CroppedDisplayDataSpecifier(Specifier):
    def __init__(self, entity_type: typing.Optional[Schema.EntityType] = None, context: typing.Optional[Schema.EntityContext] = None, *, version: typing.Optional[int] = None, reference: typing.Optional[Persistence.PersistentObject] = None) -> None:
        super().__init__(Model.CroppedDisplayDataSpecifier, context, version=version, reference=reference)

    def get_bound_item(self, container: Persistence.PersistentObject, secondary_specifier: typing.Optional[Specifier] = None, property_name: typing.Optional[str] = None) -> typing.Optional[BoundItemBase]:
        return BoundCroppedDisplayData(container, self, secondary_specifier)


class FilterDataSpecifier(Specifier):
    def __init__(self, entity_type: typing.Optional[Schema.EntityType] = None, context: typing.Optional[Schema.EntityContext] = None, *, version: typing.Optional[int] = None, reference: typing.Optional[Persistence.PersistentObject] = None) -> None:
        super().__init__(Model.FilterDataSpecifier, context, version=version, reference=reference)

    def get_bound_item(self, container: Persistence.PersistentObject, secondary_specifier: typing.Optional[Specifier] = None, property_name: typing.Optional[str] = None) -> typing.Optional[BoundItemBase]:
        return BoundFilterData(container, self, secondary_specifier)


class FilteredDataSpecifier(Specifier):
    def __init__(self, entity_type: typing.Optional[Schema.EntityType] = None, context: typing.Optional[Schema.EntityContext] = None, *, version: typing.Optional[int] = None, reference: typing.Optional[Persistence.PersistentObject] = None) -> None:
        super().__init__(Model.FilteredDataSpecifier, context, version=version, reference=reference)

    def get_bound_item(self, container: Persistence.PersistentObject, secondary_specifier: typing.Optional[Specifier] = None, property_name: typing.Optional[str] = None) -> typing.Optional[BoundItemBase]:
        return BoundFilteredData(container, self, secondary_specifier)


def specifier_factory(lookup_id: typing.Callable[[str], str]) -> typing.Optional[Specifier]:
    build_map: typing.Dict[str, typing.Callable[[], Specifier]] = {
        Model.DataSourceSpecifier.entity_id: DataSourceSpecifier,
        Model.DataItemSpecifier.entity_id: DataItemSpecifier,
        Model.GraphicSpecifier.entity_id: GraphicSpecifier,
        Model.StructureSpecifier.entity_id: StructureSpecifier,
        Model.DataSpecifier.entity_id: DataSpecifier,
        Model.DisplayDataSpecifier.entity_id: DisplayDataSpecifier,
        Model.CroppedDataSpecifier.entity_id: CroppedDataSpecifier,
        Model.CroppedDisplayDataSpecifier.entity_id: CroppedDisplayDataSpecifier,
        Model.FilterDataSpecifier.entity_id: FilterDataSpecifier,
        Model.FilteredDataSpecifier.entity_id: FilteredDataSpecifier,
    }
    type = lookup_id("type")
    return build_map[type]() if type in build_map else None


def read_specifier(d: typing.Optional[Persistence.PersistentDictType]) -> typing.Optional[Specifier]:
    if d is not None:
        dd = d  # work around mypy issue by assigning new variable with known non-none value.
        specifier = specifier_factory(lambda n: dd.get(n, None))
        if specifier:
            specifier.read(d)
        return specifier
    return None


def get_object_specifier(object: typing.Optional[Persistence.PersistentObject], object_type: typing.Optional[str] = None,
                         project: typing.Optional[Project.Project] = None) -> typing.Optional[Specifier]:
    # project is passed for testing only
    if isinstance(object, DataItem.DataItem) and not object_type:
        return DataItemSpecifier(version=1, reference=object)
    if isinstance(object, (DisplayItem.DisplayDataChannel, DataItem.DataItem)):
        if object_type == "xdata":
            return DataSpecifier(version=1, reference=object)
        elif object_type == "display_xdata":
            return DisplayDataSpecifier(version=1, reference=object)
        if object_type == "cropped_xdata":
            return CroppedDataSpecifier(version=1, reference=object)
        elif object_type == "cropped_display_xdata":
            return CroppedDisplayDataSpecifier(version=1, reference=object)
        if object_type == "filter_xdata":
            return FilterDataSpecifier(version=1, reference=object)
        elif object_type == "filtered_xdata":
            return FilteredDataSpecifier(version=1, reference=object)
    if isinstance(object, DisplayItem.DisplayDataChannel):
        return DataSourceSpecifier(version=1, reference=object)
    elif isinstance(object, Graphics.Graphic):
        return GraphicSpecifier(version=1, reference=object)
    elif isinstance(object, DataStructure.DataStructure):
        return StructureSpecifier(version=1, reference=object)
    return None


class ComputationVariableType(enum.Enum):
    BOOLEAN = "boolean"
    INTEGRAL = "integral"
    REAL = "real"
    COMPLEX = "complex"
    STRING = "string"
    DATA_SOURCE = "data_source"
    DATA_ITEM = "data_item"
    GRAPHIC = "graphic-specifier"
    STRUCTURE = "structure"
    DATA = "xdata"
    DISPLAY_DATA = "display_xdata"
    CROPPED_DATA = "cropped_xdata"
    CROPPED_DISPLAY_DATA = "cropped_display_xdata"
    FILTER_DATA = "filter_xdata"
    FILTERED_DATA = "filtered_xdata"


_map_variable_type_to_identifier = {
    ComputationVariableType.BOOLEAN: "boolean",
    ComputationVariableType.INTEGRAL: "integral",
    ComputationVariableType.REAL: "real",
    ComputationVariableType.COMPLEX: "complex",
    ComputationVariableType.STRING: "string",
    ComputationVariableType.DATA_SOURCE: "data_source",
    ComputationVariableType.DATA_ITEM: "data_item",
    ComputationVariableType.GRAPHIC: "graphic-specifier",
    ComputationVariableType.STRUCTURE: "structure",
    ComputationVariableType.DATA: "xdata",
    ComputationVariableType.DISPLAY_DATA: "display_xdata",
    ComputationVariableType.CROPPED_DATA: "cropped_xdata",
    ComputationVariableType.CROPPED_DISPLAY_DATA: "cropped_display_xdata",
    ComputationVariableType.FILTER_DATA: "filter_xdata",
    ComputationVariableType.FILTERED_DATA: "filtered_xdata",
}


_map_identifier_to_variable_type = {
    "boolean": ComputationVariableType.BOOLEAN,
    "integral": ComputationVariableType.INTEGRAL,
    "real": ComputationVariableType.REAL,
    "complex": ComputationVariableType.COMPLEX,
    "string": ComputationVariableType.STRING,
    "data_source": ComputationVariableType.DATA_SOURCE,
    "data_item": ComputationVariableType.DATA_ITEM,
    "graphic-specifier": ComputationVariableType.GRAPHIC,
    "structure": ComputationVariableType.STRUCTURE,
    "xdata": ComputationVariableType.DATA,
    "display_xdata": ComputationVariableType.DISPLAY_DATA,
    "cropped_xdata": ComputationVariableType.CROPPED_DATA,
    "cropped_display_xdata": ComputationVariableType.CROPPED_DISPLAY_DATA,
    "filter_xdata": ComputationVariableType.FILTER_DATA,
    "filtered_xdata": ComputationVariableType.FILTERED_DATA,
}

_data_source_types = (
    ComputationVariableType.DATA_SOURCE,
    ComputationVariableType.DATA_ITEM,
    ComputationVariableType.DATA,
    ComputationVariableType.DISPLAY_DATA,
    ComputationVariableType.CROPPED_DATA,
    ComputationVariableType.CROPPED_DISPLAY_DATA,
    ComputationVariableType.FILTER_DATA,
    ComputationVariableType.FILTERED_DATA
)


class VariableSpecifierLike(typing.Protocol):
    def get_bound_item(self, container: Persistence.PersistentObject, secondary_specifier: typing.Optional[Specifier] = None, property_name: typing.Optional[str] = None) -> typing.Optional[BoundItemBase]:
        ...


class ComputationVariable(Persistence.PersistentObject):
    """Tracks a variable (value or object) used in a computation.

    A variable has user visible name, a label used in the script, a value type.

    Scalar value types have a value, a default, and optional min and max values. The control type is used to
    specify the preferred UI control (e.g. checkbox vs. input field).

    Specifier value types have a specifier/secondary_specifier/property_name which can be resolved to a part of a
    specific object. The specifier indicates the object and the part of the object to be used (e.g., a data item and the
    masked data of that data item). The secondary specifier is used to augment the first object (e.g. a crop graphic on
    an image). The property name is also used to augment the specifier (e.g., a field of a data structure or graphic).

    The object provides four events: changed, fired when anything changes; variable_type_changed, fired when the
    variable type changes; needs_rebind, fired when a specifier changes and the variable needs rebinding to the context;
    and needs_rebuild, fired when the UI needs rebuilding. variable_type_changed and needs_rebuild are specific to the
    inspector and shouldn't be used elsewhere.

    Clients can ask for the bound_variable which supplies an object that provides a read-only value property and a
    changed_event. This object can be used to watch for changes to the value type portion of this object.

    Clients can also get/set the bound_item, which must be an object that provides a read-only value property and a
    changed_event.  This object can be used to watch for changes to the object portion of this object.
    """

    def __init__(self, name: typing.Optional[str] = None, *, property_name: typing.Optional[str] = None,
                 value_type: typing.Optional[ComputationVariableType] = None, value: typing.Any = None, value_default: typing.Any = None,
                 value_min: typing.Any = None, value_max: typing.Any = None, control_type: typing.Optional[str] = None,
                 specifier: typing.Optional[Specifier] = None, label: typing.Optional[str] = None,
                 secondary_specifier: typing.Optional[Specifier] = None,
                 items: typing.Optional[typing.List[ComputationItem]] = None) -> None:  # defaults are None for factory
        super().__init__()
        self.define_type("variable")
        # setup
        # contemplating changes here? remember that this is mainly a place to store a value and track changes
        # to the value. this is not a place to specify how the value is presented, even though there are some
        # existing fields (control_type) for that which are leftovers from the original implementation.
        self.define_property("name", name, changed=self.__property_changed, hidden=True)
        self.define_property("label", label if label else name, changed=self.__property_changed, hidden=True)
        self.define_property("value_type", _map_variable_type_to_identifier.get(value_type, None) if value_type else None, changed=self.__property_changed, hidden=True)
        self.define_property("value", value, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer, hidden=True)
        self.define_property("value_default", value_default, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer, hidden=True)
        self.define_property("value_min", value_min, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer, hidden=True)
        self.define_property("value_max", value_max, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer, hidden=True)
        self.define_property("property_name", property_name, changed=self.__property_changed, hidden=True)
        self.define_property("control_type", control_type, changed=self.__property_changed, hidden=True)
        self.define_item("specifier", typing.cast(Persistence._PersistentObjectFactoryFn, specifier_factory), changed=self.__specifier_changed, hidden=True)
        self.define_item("secondary_specifier", typing.cast(Persistence._PersistentObjectFactoryFn, specifier_factory), changed=self.__specifier_changed, hidden=True)
        self.define_relationship("object_specifiers", typing.cast(Persistence._PersistentObjectFactoryFn, specifier_factory), insert=self.__specifier_inserted, remove=self.__specifier_removed, hidden=True)
        self.data_event = Event.Event()
        self.variable_type_changed_event = Event.Event()
        self.needs_rebuild_event = Event.Event()  # an event to be fired when the UI needs a rebuild
        self.__bound_item: typing.Optional[BoundItemBase] = None
        self.__bound_item_changed_event_listener: typing.Optional[Event.EventListener] = None
        self.__bound_item_base_item_inserted_event_listener: typing.Optional[Event.EventListener] = None
        self.__bound_item_base_item_removed_event_listener: typing.Optional[Event.EventListener] = None
        if specifier:
            self.specifier = specifier
        if secondary_specifier:
            self.secondary_specifier = secondary_specifier
        if items is not None:  # form a list even if it is empty
            self.object_specifiers = [get_object_specifier(item.item, item.type) if item and item.item else EmptySpecifier() for item in items] if items is not None else None

    def close(self) -> None:
        self.unbind()
        # continue closing
        super().close()

    def __repr__(self) -> str:
        return "{} ({} {} {} {} {})".format(super().__repr__(), self.name, self.label, self.value, self.specifier, self.secondary_specifier)

    def read_from_dict(self, properties: Persistence.PersistentDictType) -> None:
        # used for persistence
        # ensure that value_type is read first
        value_type_property = self._get_persistent_property("value_type")
        value_type_property.read_from_dict(properties)
        super().read_from_dict(properties)

    def write_to_dict(self) -> Persistence.PersistentDictType:
        # used for persistence. left here since read_from_dict is defined.
        return super().write_to_dict()

    def persistent_object_context_changed(self) -> None:
        if self.container:
            self.bind()

    @property
    def name(self) -> str:
        return typing.cast(str, self._get_persistent_property_value("name"))

    @name.setter
    def name(self, value: str) -> None:
        self._set_persistent_property_value("name", value)

    @property
    def label(self) -> typing.Optional[str]:
        return typing.cast(typing.Optional[str], self._get_persistent_property_value("label"))

    @label.setter
    def label(self, value: typing.Optional[str]) -> None:
        self._set_persistent_property_value("label", value)

    @property
    def value_type(self) -> typing.Optional[ComputationVariableType]:
        return _map_identifier_to_variable_type.get(self._get_persistent_property_value("value_type"), None)

    @value_type.setter
    def value_type(self, value: typing.Optional[ComputationVariableType]) -> None:
        self._set_persistent_property_value("value_type", _map_variable_type_to_identifier.get(value, None) if value else None)

    @property
    def control_type(self) -> typing.Optional[str]:
        return typing.cast(typing.Optional[str], self._get_persistent_property_value("control_type"))

    @control_type.setter
    def control_type(self, value: typing.Optional[str]) -> None:
        self._set_persistent_property_value("control_type", value)

    @property
    def property_name(self) -> typing.Optional[str]:
        return typing.cast(typing.Optional[str], self._get_persistent_property_value("property_name"))

    @property_name.setter
    def property_name(self, value: typing.Optional[str]) -> None:
        self._set_persistent_property_value("property_name", value)

    @property
    def value(self) -> typing.Any:
        return typing.cast(typing.Any, self._get_persistent_property_value("value"))

    @value.setter
    def value(self, value: typing.Any) -> None:
        self._set_persistent_property_value("value", value)

    @property
    def value_default(self) -> typing.Any:
        return typing.cast(typing.Any, self._get_persistent_property_value("value_default"))

    @value_default.setter
    def value_default(self, value: typing.Any) -> None:
        self._set_persistent_property_value("value_default", value)

    @property
    def value_min(self) -> typing.Any:
        return typing.cast(typing.Any, self._get_persistent_property_value("value_min"))

    @value_min.setter
    def value_min(self, value: typing.Any) -> None:
        self._set_persistent_property_value("value_min", value)

    @property
    def value_max(self) -> typing.Any:
        return typing.cast(typing.Any, self._get_persistent_property_value("value_max"))

    @value_max.setter
    def value_max(self, value: typing.Any) -> None:
        self._set_persistent_property_value("value_max", value)

    @property
    def specifier(self) -> typing.Optional[Specifier]:
        return typing.cast(typing.Optional[Specifier], self.get_item("specifier"))

    @specifier.setter
    def specifier(self, value: typing.Optional[Specifier]) -> None:
        self.set_item("specifier", value)

    @property
    def secondary_specifier(self) -> typing.Optional[Specifier]:
        return typing.cast(typing.Optional[Specifier], self.get_item("secondary_specifier"))

    @secondary_specifier.setter
    def secondary_specifier(self, value: typing.Optional[Specifier]) -> None:
        self.set_item("secondary_specifier", value)

    @property
    def object_specifiers(self) -> typing.Sequence[typing.Optional[Specifier]]:
        return typing.cast(typing.Sequence[typing.Optional[Specifier]], self._get_relationship_values("object_specifiers"))

    @object_specifiers.setter
    def object_specifiers(self, value: typing.Sequence[typing.Optional[Specifier]]) -> None:
        needs_binding = True
        while len(self.object_specifiers):
            self.remove_item("object_specifiers", typing.cast(Persistence.PersistentObject, self.object_specifiers[-1]))
            needs_binding = False
        for specifier in value:
            self.append_item("object_specifiers", typing.cast(Persistence.PersistentObject, specifier))
            needs_binding = False
        if needs_binding and self.container:
            self.bind()

    def bind(self) -> None:
        if self.value_type is not None or self.specifier:
            variable_specifier = self._variable_specifier
            if variable_specifier:
                self.bound_item = variable_specifier.get_bound_item(self, self.secondary_specifier, self.property_name)
            else:
                self.bound_item = None
        else:
            self.bound_item = BoundList(
                [object_specifier.get_bound_item(self) if object_specifier else None for object_specifier in
                 self.object_specifiers])

    def unbind(self) -> None:
        self.bound_item = None

    @property
    def _bound_items(self) -> typing.Sequence[typing.Optional[BoundItemBase]]:
        bound_item = self.bound_item
        assert isinstance(bound_item, BoundList)
        return bound_item.get_items()

    def _insert_specifier_in_list(self, index: int, specifier: Specifier) -> None:
        self.insert_item("object_specifiers", index, typing.cast(Persistence.PersistentObject, specifier))

    def _remove_item_from_list(self, index: int) -> None:
        self.remove_item("object_specifiers", typing.cast(Persistence.PersistentObject, self.object_specifiers[index]))

    def save_properties(self) -> typing.Tuple[typing.Any, typing.Optional[Specifier], typing.Optional[Specifier]]:
        # used for undo
        return self.value, copy.deepcopy(self.specifier), copy.deepcopy(self.secondary_specifier)

    def restore_properties(self, properties: typing.Tuple[typing.Any, typing.Optional[Specifier], typing.Optional[Specifier]]) -> None:
        # used for undo
        self.value = properties[0]
        self.specifier = properties[1]
        self.secondary_specifier = properties[2]

    def __value_reader(self, persistent_property: Persistence.PersistentProperty, properties: Persistence.PersistentDictType) -> typing.Any:
        value_type = self.value_type
        raw_value = properties.get(persistent_property.key)
        if raw_value is not None:
            if value_type == ComputationVariableType.BOOLEAN:
                return bool(raw_value)
            elif value_type == ComputationVariableType.INTEGRAL:
                return int(raw_value)
            elif value_type == ComputationVariableType.REAL:
                return float(raw_value)
            elif value_type == ComputationVariableType.COMPLEX:
                return complex(*raw_value)
            elif value_type == ComputationVariableType.STRING:
                return str(raw_value)
        return None

    def __value_writer(self, persistent_property: Persistence.PersistentProperty, properties: Persistence.PersistentDictType, value: typing.Any) -> None:
        value_type = self.value_type
        if value is not None:
            if value_type == ComputationVariableType.BOOLEAN:
                properties[persistent_property.key] = bool(value)
            if value_type == ComputationVariableType.INTEGRAL:
                properties[persistent_property.key] = int(value)
            if value_type == ComputationVariableType.REAL:
                properties[persistent_property.key] = float(value)
            if value_type == ComputationVariableType.COMPLEX:
                properties[persistent_property.key] = complex(value).real, complex(value).imag
            if value_type == ComputationVariableType.STRING:
                properties[persistent_property.key] = str(value)

    @property
    def _variable_specifier(self) -> typing.Optional[VariableSpecifierLike]:
        """Return the variable specifier for this variable.

        The specifier can be used to look up the value of this variable in a computation context.
        """
        if self.value_type is not None:
            class VariableSpecifier(VariableSpecifierLike):
                def __init__(self, computation_variable: ComputationVariable) -> None:
                    self.__computation_variable = computation_variable

                def get_bound_item(self, container: Persistence.PersistentObject,
                                   secondary_specifier: typing.Optional[Specifier] = None,
                                   property_name: typing.Optional[str] = None) -> typing.Optional[BoundItemBase]:
                    return self.__computation_variable.bound_variable

            return VariableSpecifier(self)
        else:
            return self.specifier

    @property
    def specified_object(self) -> typing.Optional[Persistence.PersistentObject]:
        bound_item = self.__bound_item
        return bound_item.value if bound_item else None

    @specified_object.setter
    def specified_object(self, value: typing.Optional[Persistence.PersistentObject]) -> None:
        if value:
            self.specifier = get_object_specifier(value)
        else:
            self.specifier = None

    @property
    def secondary_specified_object(self) -> typing.Optional[Persistence.PersistentObject]:
        return typing.cast(typing.Optional[Persistence.PersistentObject], getattr(self.__bound_item, "_graphic", None))

    @secondary_specified_object.setter
    def secondary_specified_object(self, value: typing.Optional[Persistence.PersistentObject]) -> None:
        if value:
            self.secondary_specifier = get_object_specifier(value)
        else:
            self.secondary_specifier = None

    @property
    def bound_variable(self) -> BoundItemBase:
        """Return an object with a value property and a changed_event.

        The value property returns the value of the variable. The changed_event is fired
        whenever the value changes.
        """

        class BoundVariable(BoundItemBase):
            def __init__(self, variable: ComputationVariable) -> None:
                super().__init__(None)
                self.valid = True
                self.__variable = variable

                def property_changed(key: str) -> None:
                    if key == "value":
                        self.data_event.fire(BoundDataEventType.VARIABLE)

                self.__variable_property_changed_listener = variable.property_changed_event.listen(property_changed)

            @property
            def value(self) -> typing.Any:
                return self.__variable.value

            def close(self) -> None:
                self.__variable_property_changed_listener.close()
                self.__variable_property_changed_listener = typing.cast(typing.Any, None)
                super().close()

        return BoundVariable(self)

    @property
    def bound_item(self) -> typing.Optional[BoundItemBase]:
        return self.__bound_item

    @bound_item.setter
    def bound_item(self, bound_item: typing.Optional[BoundItemBase]) -> None:
        if self.__bound_item_changed_event_listener:
            self.__bound_item_changed_event_listener.close()
            self.__bound_item_changed_event_listener = None
        if self.__bound_item_base_item_inserted_event_listener:
            self.__bound_item_base_item_inserted_event_listener.close()
            self.__bound_item_base_item_inserted_event_listener = None
        if self.__bound_item_base_item_removed_event_listener:
            self.__bound_item_base_item_removed_event_listener.close()
            self.__bound_item_base_item_removed_event_listener = None
        if self.__bound_item:
            self.__bound_item.close()
        self.__bound_item = bound_item
        if self.__bound_item:
            def handle_data_event(event: BoundDataEventType) -> None:
                self.data_event.fire(event)

            self.__bound_item_changed_event_listener = self.__bound_item.data_event.listen(handle_data_event)
            self.__bound_item_base_item_inserted_event_listener = self.__bound_item.item_inserted_event.listen(self.item_inserted_event.fire)
            self.__bound_item_base_item_removed_event_listener = self.__bound_item.item_removed_event.listen(self.item_removed_event.fire)
            for index, base_item in enumerate(self.__bound_item.base_items):
                self.notify_insert_item("base_items", base_item, index)
        self.notify_property_changed("bound_item")

    @property
    def is_resolved(self) -> bool:
        if not self.specifier:
            return True  # nothing specified, so it is valid
        bound_item = self.bound_item
        if isinstance(bound_item, BoundList):
            return all(bound_item.get_items())
        return bound_item is not None and bound_item.value is not None

    @property
    def is_list(self) -> bool:
        return isinstance(self.bound_item, BoundList)

    @property
    def input_items(self) -> typing.List[Persistence.PersistentObject]:
        return self.bound_item.base_items if self.bound_item else list()

    @property
    def direct_input_items(self) -> typing.List[Persistence.PersistentObject]:
        return self.bound_item.base_items if self.bound_item and not getattr(self.bound_item, "is_list", False) else list()

    def __property_changed(self, name: str, value: typing.Any) -> None:
        # send the primary property changed event
        self.notify_property_changed(name)
        # now send out dependent property changed events
        if name in ["name", "label"]:
            self.notify_property_changed("display_label")
        # send out the changed event
        self.data_event.fire(BoundDataEventType.UNSPECIFIED)
        # finally send out the rebuild event for the inspectors
        if name in ["value_type", "value_min", "value_max", "control_type"]:
            self.needs_rebuild_event.fire()

    def __specifier_changed(self, name: str, old_value: typing.Any, new_value: typing.Any) -> None:
        # rebind first, so that property changed listeners get the right value
        # TODO: is this needed if the specifier is used directly in the bound item? (it is not now, but might be in the future)
        if name in ("specifier", "secondary_specifier"):
            if self.container:
                if self.specifier:
                    self.bound_item = self.specifier.get_bound_item(self.container, self.secondary_specifier, self.property_name)
                else:
                    self.bound_item = None
        # notify
        if name in ("specifier"):
            self.notify_property_changed("specified_object")
        if name in ("secondary_specifier"):
            self.notify_property_changed("secondary_specified_object")
        # send out the changed event
        self.data_event.fire(BoundDataEventType.UNSPECIFIED)

    def __specifier_inserted(self, name: str, before_index: int, specifier: typing.Optional[Specifier]) -> None:
        # update the bound list
        if self.container:
            self.bind()
            # self.notify_insert_item("_bound_items", bound_item, before_index)
        # notify
        self.notify_property_changed("specified_objects")
        # send out the changed event
        self.data_event.fire(BoundDataEventType.UNSPECIFIED)

    def __specifier_removed(self, name: str, index: int, specifier: typing.Optional[Specifier]) -> None:
        # update the bound list
        if self.container:
            self.bind()
            # self.notify_remove_item("_bound_items", value, index)
        # notify
        self.notify_property_changed("specified_objects")
        # send out the changed event
        self.data_event.fire(BoundDataEventType.UNSPECIFIED)

    def notify_property_changed(self, key: str) -> None:
        # whenever a property changed event is fired, also fire the changed_event
        # is there a test for this? not that I can find.
        super().notify_property_changed(key)
        if key not in ("bound_item",):
            self.data_event.fire(BoundDataEventType.UNSPECIFIED)

    def get_control_type_default(self, value_type: ComputationVariableType) -> typing.Optional[str]:
        mapping = {
            ComputationVariableType.BOOLEAN: "checkbox",
            ComputationVariableType.INTEGRAL: "slider",
            ComputationVariableType.REAL: "field",
            ComputationVariableType.COMPLEX: "field",
            ComputationVariableType.STRING: "field"
        }
        return mapping.get(value_type, None)

    data_item_types = ("data_item", "data", "display_data", "data_source")  # used for backward compatibility

    @property
    def variable_type(self) -> typing.Optional[ComputationVariableType]:
        if self.value_type is not None:
            return self.value_type
        elif self.specifier is not None:
            return self.specifier.variable_type
        return None

    @variable_type.setter
    def variable_type(self, value_type: typing.Optional[ComputationVariableType]) -> None:
        if value_type != self.variable_type:
            if value_type in (ComputationVariableType.BOOLEAN, ComputationVariableType.INTEGRAL, ComputationVariableType.REAL, ComputationVariableType.COMPLEX, ComputationVariableType.STRING):
                self.specifier = None
                self.secondary_specifier = None
                self.value_type = value_type
                self.control_type = self.get_control_type_default(value_type)
                if value_type == ComputationVariableType.BOOLEAN:
                    self.value_default = True
                elif value_type == ComputationVariableType.INTEGRAL:
                    self.value_default = 0
                elif value_type == ComputationVariableType.REAL:
                    self.value_default = 0.0
                elif value_type == ComputationVariableType.COMPLEX:
                    self.value_default = 0 + 0j
                else:
                    self.value_default = None
                self.value_min = None
                self.value_max = None
            else:
                def lookup(property_name: str) -> str:
                    return _map_variable_type_to_identifier.get(value_type, str()) if value_type else str()

                specifier = specifier_factory(lookup)
                if specifier:
                    self.value_type = None
                    self.control_type = None
                    self.value_default = None
                    self.value_min = None
                    self.value_max = None
                    self.specifier = specifier
                    self.secondary_specifier = None
            self.variable_type_changed_event.fire()

    @property
    def specifier_reference(self) -> typing.Optional[Persistence.PersistentObject]:
        return self.specifier.reference if self.specifier else None

    @specifier_reference.setter
    def specifier_reference(self, reference: typing.Optional[Persistence.PersistentObject]) -> None:
        if self.specifier:
            self.specifier.reference = reference

    @property
    def secondary_specifier_reference(self) -> typing.Optional[Persistence.PersistentObject]:
        return self.secondary_specifier.reference if self.secondary_specifier else None

    @secondary_specifier_reference.setter
    def secondary_specifier_reference(self, reference: typing.Optional[Persistence.PersistentObject]) -> None:
        if self.secondary_specifier:
            self.secondary_specifier.reference = reference

    @property
    def display_label(self) -> str:
        # for registered computations, the computation class takes precedence in defining the labels.
        computation = self.container
        if isinstance(computation, Computation):
            processing_id = computation.processing_id
            compute_class = _computation_types.get(processing_id) if processing_id else None
            if compute_class:
                label = typing.cast(typing.Optional[str], getattr(compute_class, "inputs", dict()).get(self.name, dict()).get("label", str()))
                if label:
                    return label
        # not a registered computation, fall back to label or name.
        return self.label or self.name or str()

    @property
    def entity_id(self) -> typing.Optional[str]:
        computation = self.container
        if isinstance(computation, Computation):
            processing_id = computation.processing_id
            compute_class = _computation_types.get(processing_id) if processing_id else None
            if compute_class:
                label = typing.cast(typing.Optional[str], getattr(compute_class, "inputs", dict()).get(self.name, dict()).get("entity_id", str()))
                if label:
                    return label
        return None

    @property
    def has_range(self) -> bool:
        return self.value_type is not None and self.value_min is not None and self.value_max is not None


def variable_factory(lookup_id: typing.Callable[[str], str]) -> typing.Optional[ComputationVariable]:
    build_map = {
        "variable": ComputationVariable,
    }
    type = lookup_id("type")
    return build_map[type]() if type in build_map else None


def result_factory(lookup_id: typing.Callable[[str], str]) -> ComputationOutput:
    return ComputationOutput()


class DataSource:
    def __init__(self, display_data_channel: DisplayItem.DisplayDataChannel, graphic: typing.Optional[Graphics.Graphic], xdata: typing.Optional[DataAndMetadata.DataAndMetadata] = None) -> None:
        self.__display_data_channel = display_data_channel
        self.__display_item = typing.cast("DisplayItem.DisplayItem", display_data_channel.container) if display_data_channel else None
        self.__data_item = display_data_channel.data_item if display_data_channel else None
        self.__graphic = graphic
        self.__xdata = xdata

    def close(self) -> None:
        pass

    @property
    def display_data_channel(self) -> DisplayItem.DisplayDataChannel:
        return self.__display_data_channel

    @property
    def _display_values(self) -> typing.Optional[DisplayItem.DisplayValues]:
        return self.__display_data_channel.get_latest_display_values()

    @property
    def display_item(self) -> typing.Optional[DisplayItem.DisplayItem]:
        return self.__display_item

    @property
    def data_item(self) -> typing.Optional[DataItem.DataItem]:
        return self.__data_item

    @property
    def graphic(self) -> typing.Optional[Graphics.Graphic]:
        return self.__graphic

    @property
    def data(self) -> typing.Optional[DataAndMetadata._ImageDataType]:
        return self.xdata.data if self.xdata else None

    @property
    def xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        if self.__xdata is not None:
            return self.__xdata
        if self.data_item:
            return self.data_item.xdata
        return None

    @property
    def element_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        display_data_channel = self.__display_data_channel
        if display_data_channel:
            if self.__xdata is not None:
                return Core.function_convert_to_scalar(self.__xdata, display_data_channel.complex_display_type)
            else:
                display_values = self._display_values
                if display_values:
                    return display_values.element_data_and_metadata
        return None

    @property
    def display_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        display_data_channel = self.__display_data_channel
        if display_data_channel:
            if self.__xdata is not None:
                return Core.function_convert_to_scalar(self.__xdata, display_data_channel.complex_display_type)
            else:
                display_values = self._display_values
                if display_values:
                    return display_values.display_data_and_metadata
        return None

    @property
    def display_rgba(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        display_data_channel = self.__display_data_channel
        if display_data_channel:
            if self.__xdata is not None:
                return self.xdata
            else:
                display_values = self._display_values
                if display_values:
                    display_rgba = display_values.display_rgba
                    return DataAndMetadata.new_data_and_metadata(Image.get_byte_view(display_rgba)) if display_rgba is not None else None
        return None

    @property
    def normalized_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        display_data_channel = self.__display_data_channel
        if display_data_channel:
            if self.__xdata is not None:
                display_xdata = self.display_xdata
                if display_xdata:
                    return Core.function_rescale(display_xdata, (0, 1))
                else:
                    return None
            else:
                display_values = self._display_values
                if display_values:
                    return display_values.normalized_data_and_metadata
        return None

    @property
    def adjusted_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        display_data_channel = self.__display_data_channel
        if display_data_channel:
            if self.__xdata is not None:
                return self.normalized_xdata
            else:
                display_values = self._display_values
                if display_values:
                    return display_values.adjusted_data_and_metadata
        return None

    @property
    def transformed_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        display_data_channel = self.__display_data_channel
        if display_data_channel:
            if self.__xdata is not None:
                return self.normalized_xdata
            else:
                display_values = self._display_values
                if display_values:
                    return display_values.transformed_data_and_metadata
        return None

    def __cropped_xdata(self, xdata: typing.Optional[DataAndMetadata.DataAndMetadata]) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        data_item = self.data_item
        graphic = self.__graphic
        if data_item:
            if isinstance(graphic, Graphics.RectangleTypeGraphic) and xdata and xdata.is_data_2d:
                if graphic.rotation:
                    return Core.function_crop_rotated(xdata, graphic.bounds.as_tuple(), graphic.rotation)
                else:
                    return Core.function_crop(xdata, graphic.bounds.as_tuple())
            if isinstance(graphic, Graphics.IntervalGraphic) and xdata and xdata.is_data_1d:
                return Core.function_crop_interval(xdata, graphic.interval)
        return xdata

    @property
    def cropped_element_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return self.__cropped_xdata(self.element_xdata)

    @property
    def cropped_display_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return self.__cropped_xdata(self.display_xdata)

    @property
    def cropped_normalized_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return self.__cropped_xdata(self.normalized_xdata)

    @property
    def cropped_adjusted_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return self.__cropped_xdata(self.adjusted_xdata)

    @property
    def cropped_transformed_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return self.__cropped_xdata(self.transformed_xdata)

    @property
    def cropped_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        data_item = self.data_item
        if data_item:
            xdata = self.xdata
            graphic = self.__graphic
            if xdata and graphic:
                if isinstance(graphic, Graphics.RectangleTypeGraphic):
                    if graphic.rotation:
                        return Core.function_crop_rotated(xdata, graphic.bounds.as_tuple(), graphic.rotation)
                    else:
                        return Core.function_crop(xdata, graphic.bounds.as_tuple())
                if isinstance(graphic, Graphics.IntervalGraphic):
                    return Core.function_crop_interval(xdata, graphic.interval)
            return xdata
        return None

    @property
    def filtered_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        xdata = self.xdata
        if self.__display_item and xdata and xdata.is_data_2d:
            display_xdata = self.display_xdata
            if display_xdata:
                shape = display_xdata.data_shape
                calibrated_origin = Geometry.FloatPoint(y=self.__display_item.datum_calibrations[0].convert_from_calibrated_value(0.0),
                                                        x=self.__display_item.datum_calibrations[1].convert_from_calibrated_value(0.0))
                if xdata.is_data_complex_type:
                    return Core.function_fourier_mask(xdata, DataAndMetadata.DataAndMetadata.from_data(Graphics.create_mask_data(self.__display_item.graphics, shape, calibrated_origin)))
                else:
                    return DataAndMetadata.DataAndMetadata.from_data(Graphics.create_mask_data(self.__display_item.graphics, shape, calibrated_origin)) * display_xdata
        return xdata

    @property
    def filter_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        xdata = self.xdata
        if self.__display_item and xdata and xdata.is_data_2d:
            display_xdata = self.display_xdata
            if display_xdata:
                shape = display_xdata.data_shape
                calibrated_origin = Geometry.FloatPoint(y=self.__display_item.datum_calibrations[0].convert_from_calibrated_value(0.0),
                                                        x=self.__display_item.datum_calibrations[1].convert_from_calibrated_value(0.0))
                return DataAndMetadata.DataAndMetadata.from_data(Graphics.create_mask_data(self.__display_item.graphics, shape, calibrated_origin))
        return None


class MonitoredDataSource(DataSource):
    def __init__(self, display_data_channel: DisplayItem.DisplayDataChannel, graphic: typing.Optional[Graphics.Graphic], data_event: Event.Event) -> None:
        super().__init__(display_data_channel, graphic)
        self.__display_item = typing.cast("DisplayItem.DisplayItem", display_data_channel.container)
        self.__graphic = graphic
        self.__data_event = data_event  # not public since it is passed in
        self.__data_item = display_data_channel.data_item

        self.__data_changed_event_listener: typing.Optional[Event.EventListener] = None

        def handle_data() -> None:
            self.__data_event.fire(BoundDataEventType.DATA)

        if self.__data_item:
            self.__data_changed_event_listener = self.__data_item.data_changed_event.listen(handle_data)

        def handle_display_values(display_values: typing.Optional[DisplayItem.DisplayValues]) -> None:
            self.__data_event.fire(BoundDataEventType.DISPLAY_DATA)

        self.__display_values_subscription = display_data_channel.subscribe_to_latest_display_values(handle_display_values)
        self.__property_changed_listener: typing.Optional[Event.EventListener] = None

        def property_changed(key: str) -> None:
            self.__data_event.fire(BoundDataEventType.GRAPHIC)

        if self.__graphic:
            self.__property_changed_listener = self.__graphic.property_changed_event.listen(property_changed)

        # when a graphic changes, if it's used in the mask or fourier_mask role, send out the changed event.
        def filter_property_changed(graphic: Graphics.Graphic, key: str) -> None:
            if key == "role" or graphic.used_role in ("mask", "fourier_mask"):
                self.__data_event.fire(BoundDataEventType.FILTER)

        self.__graphic_property_changed_listeners: typing.List[typing.Optional[Event.EventListener]] = list()

        # when a new graphic is inserted, track it
        def graphic_inserted(key: str, graphic: Graphics.Graphic, before_index: int) -> None:
            if key == "graphics":
                property_changed_listener = None
                if isinstance(graphic, (Graphics.PointTypeGraphic, Graphics.LineTypeGraphic, Graphics.RectangleTypeGraphic, Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic, Graphics.LatticeGraphic)):
                    property_changed_listener = graphic.property_changed_event.listen(functools.partial(filter_property_changed, graphic))
                    filter_property_changed(graphic, "label")  # dummy non-role value
                self.__graphic_property_changed_listeners.insert(before_index, property_changed_listener)

        # when a graphic is removed, untrack it
        def graphic_removed(key: str, graphic: Graphics.Graphic, index: int) -> None:
            if key == "graphics":
                property_changed_listener = self.__graphic_property_changed_listeners.pop(index)
                if property_changed_listener:
                    property_changed_listener.close()
                    filter_property_changed(graphic, "label")  # dummy non-role value

        self.__graphic_inserted_event_listener = self.__display_item.item_inserted_event.listen(graphic_inserted) if self.__display_item else None
        self.__graphic_removed_event_listener = self.__display_item.item_removed_event.listen(graphic_removed) if self.__display_item else None

        # set up initial tracking
        for graphic in self.__display_item.graphics if self.__display_item else list():
            property_changed_listener = None
            if isinstance(graphic, (Graphics.PointTypeGraphic, Graphics.LineTypeGraphic, Graphics.RectangleTypeGraphic, Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic, Graphics.LatticeGraphic)):
                property_changed_listener = graphic.property_changed_event.listen(functools.partial(filter_property_changed, graphic))
            self.__graphic_property_changed_listeners.append(property_changed_listener)

    def close(self) -> None:
        # shut down the trackers
        self.__graphic_property_changed_listeners = list()
        self.__graphic_inserted_event_listener = None
        self.__graphic_removed_event_listener = None
        self.__data_changed_event_listener = None
        self.__property_changed_listener = None
        self.__display_values_subscription = typing.cast(typing.Any, None)
        self.__display_item = None
        self.__graphic = typing.cast(typing.Any, None)
        self.__data_event = typing.cast(typing.Any, None)


class BoundDataEventType(enum.Enum):
    DATA = "data"
    DISPLAY_DATA = "display_data"
    CROP_REGION = "crop"
    FILTER = "filter"
    VARIABLE = "variable"
    GRAPHIC = "graphic"
    STRUCTURE = "structure"
    UNSPECIFIED = "unknown"


class BoundItemBase(Observable.Observable):
    # note: base objects are different from items temporarily while the notification machinery is put in place

    count = 0

    def __init__(self, specifier: typing.Optional[Specifier]) -> None:
        super().__init__()
        BoundItemBase.count += 1
        self.specifier = specifier
        self.data_event = Event.Event()
        self.valid = False
        self.__base_items: typing.List[Persistence.PersistentObject] = list()

    def close(self) -> None:
        BoundItemBase.count -= 1

    @property
    def value(self) -> typing.Any:
        return None

    @property
    def base_items(self) -> typing.List[Persistence.PersistentObject]:
        return self.__base_items

    def _update_base_items(self, base_items: typing.List[Persistence.PersistentObject]) -> None:
        update_diff_notify(self, "base_items", self.__base_items, base_items)


class BoundData(BoundItemBase):

    def __init__(self, container: Persistence.PersistentObject, specifier: DataSpecifier) -> None:
        super().__init__(specifier)

        self.__item_reference = container.create_item_reference(item_specifier=Persistence.read_persistent_specifier(specifier.reference_uuid))
        self.__data_changed_event_listener: typing.Optional[Event.EventListener] = None

        def handle_data() -> None:
            self.data_event.fire(BoundDataEventType.DATA)

        def maintain_data_source() -> None:
            if self.__data_changed_event_listener:
                self.__data_changed_event_listener.close()
                self.__data_changed_event_listener = None
            item = self._item
            if item:
                self.__data_changed_event_listener = item.data_changed_event.listen(handle_data)
            self.valid = item is not None
            self._update_base_items(list(self._get_base_items()))

        def item_registered(item: Persistence.PersistentObject) -> None:
            maintain_data_source()

        def item_unregistered(item: Persistence.PersistentObject) -> None:
            maintain_data_source()

        self.__item_reference.on_item_registered = item_registered
        self.__item_reference.on_item_unregistered = item_unregistered

        maintain_data_source()

    def close(self) -> None:
        if self.__data_changed_event_listener:
            self.__data_changed_event_listener.close()
            self.__data_changed_event_listener = None
        self.__item_reference.on_item_registered = None
        self.__item_reference.on_item_unregistered = None
        super().close()

    def _get_base_items(self) -> typing.List[Persistence.PersistentObject]:
        return [self._item] if self._item else list()

    @property
    def value(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return self._item.xdata if self._item else None

    @property
    def _item(self) -> typing.Optional[DataItem.DataItem]:
        item = self.__item_reference.item
        if isinstance(item, DisplayItem.DisplayDataChannel):
            item = item.data_item
        return typing.cast(typing.Optional[DataItem.DataItem], item)


class BoundDisplayDataChannelBase(BoundItemBase):

    def __init__(self, container: Persistence.PersistentObject, specifier: Specifier, secondary_specifier: typing.Optional[Specifier]) -> None:
        super().__init__(specifier)

        self.__item_reference = container.create_item_reference(item_specifier=Persistence.read_persistent_specifier(specifier.reference_uuid if specifier else None))
        self.__graphic_reference = container.create_item_reference(item_specifier=Persistence.read_persistent_specifier(secondary_specifier.reference_uuid if secondary_specifier else None))
        self.__display_values_subscription: typing.Optional[DisplayItem.DisplayValuesSubscription] = None

        def handle_display_values(display_values: typing.Optional[DisplayItem.DisplayValues]) -> None:
            self.data_event.fire(BoundDataEventType.DISPLAY_DATA)

        def maintain_data_source() -> None:
            self.__display_values_subscription = None
            display_data_channel = self._display_data_channel
            if display_data_channel:
                self.__display_values_subscription = display_data_channel.subscribe_to_latest_display_values(handle_display_values)
            self.valid = self.__display_values_subscription is not None
            self._update_base_items(self._get_base_items())

        def item_registered(item: Persistence.PersistentObject) -> None:
            maintain_data_source()

        def item_unregistered(item: Persistence.PersistentObject) -> None:
            maintain_data_source()

        self.__item_reference.on_item_registered = item_registered
        self.__item_reference.on_item_unregistered = item_unregistered

        self.__graphic_reference.on_item_registered = item_registered
        self.__graphic_reference.on_item_unregistered = item_unregistered

        maintain_data_source()

    def close(self) -> None:
        self.__display_values_subscription = None
        self.__item_reference.on_item_registered = None
        self.__item_reference.on_item_unregistered = None
        self.__graphic_reference.on_item_registered = None
        self.__graphic_reference.on_item_unregistered = None
        super().close()

    def _get_base_items(self) -> typing.List[Persistence.PersistentObject]:
        base_items = list()
        if self._display_data_channel:
            if self._display_data_channel.container:
                base_items.append(self._display_data_channel.container)
            if self._display_data_channel.data_item:
                base_items.append(self._display_data_channel.data_item)
        if self._graphic:
            base_items.append(self._graphic)
        return base_items

    @property
    def _display_data_channel(self) -> typing.Optional[DisplayItem.DisplayDataChannel]:
        return typing.cast(typing.Optional[DisplayItem.DisplayDataChannel], self.__item_reference.item)

    @property
    def _display_values(self) -> typing.Optional[DisplayItem.DisplayValues]:
        return self._display_data_channel.get_latest_display_values() if self._display_data_channel else None

    @property
    def _graphic(self) -> typing.Optional[Graphics.Graphic]:
        return typing.cast(typing.Optional[Graphics.Graphic], self.__graphic_reference.item)


class BoundDataSource(BoundItemBase):

    def __init__(self, container: Persistence.PersistentObject, specifier: DataSourceSpecifier, secondary_specifier: typing.Optional[Specifier]) -> None:
        super().__init__(specifier)

        self.__item_reference = container.create_item_reference(item_specifier=Persistence.read_persistent_specifier(specifier.reference_uuid if specifier else None))
        self.__graphic_reference = container.create_item_reference(item_specifier=Persistence.read_persistent_specifier(secondary_specifier.reference_uuid if secondary_specifier else None))
        self.__data_source: typing.Optional[DataSource] = None

        def maintain_data_source() -> None:
            if self.__data_source:
                self.__data_source.close()
                self.__data_source = None
            display_data_channel = self._display_data_channel
            if display_data_channel and display_data_channel.data_item:
                graphic = self._graphic
                self.__data_source = MonitoredDataSource(display_data_channel, graphic, self.data_event)
            self.valid = self.__data_source is not None
            self._update_base_items(self._get_base_items())

        def item_registered(item: Persistence.PersistentObject) -> None:
            maintain_data_source()

        def item_unregistered(item: Persistence.PersistentObject) -> None:
            maintain_data_source()

        self.__item_reference.on_item_registered = item_registered
        self.__item_reference.on_item_unregistered = item_unregistered

        self.__graphic_reference.on_item_registered = item_registered
        self.__graphic_reference.on_item_unregistered = item_unregistered

        maintain_data_source()

    def close(self) -> None:
        if self.__data_source:
            self.__data_source.close()
            self.__data_source = None
        self.__item_reference.on_item_registered = None
        self.__item_reference.on_item_unregistered = None
        self.__graphic_reference.on_item_registered = None
        self.__graphic_reference.on_item_unregistered = None
        super().close()

    @property
    def value(self) -> typing.Optional[DataSource]:
        return self.__data_source

    def _get_base_items(self) -> typing.List[Persistence.PersistentObject]:
        base_items: typing.List[Persistence.PersistentObject] = list()
        if self.__data_source:
            if self.__data_source.data_item:
                base_items.append(self.__data_source.data_item)
            if self.__data_source.graphic:
                base_items.append(self.__data_source.graphic)
        return base_items

    @property
    def _display_data_channel(self) -> typing.Optional[DisplayItem.DisplayDataChannel]:
        return typing.cast(typing.Optional[DisplayItem.DisplayDataChannel], self.__item_reference.item)

    @property
    def _graphic(self) -> typing.Optional[Graphics.Graphic]:
        return typing.cast(typing.Optional[Graphics.Graphic], self.__graphic_reference.item)


class BoundDataItem(BoundItemBase):

    def __init__(self, container: Persistence.PersistentObject, specifier: DataItemSpecifier) -> None:
        super().__init__(specifier)

        self.__item_reference = container.create_item_reference(item_specifier=Persistence.read_persistent_specifier(specifier.reference_uuid if specifier else None))
        self.__data_item_changed_event_listener: typing.Optional[Event.EventListener] = None

        def item_registered(item: Persistence.PersistentObject) -> None:
            assert isinstance(item, DataItem.DataItem)

            def handle_data_item_changed() -> None:
                self.data_event.fire(BoundDataEventType.DATA)

            self.__data_item_changed_event_listener = item.data_item_changed_event.listen(handle_data_item_changed)
            self._update_base_items(self._get_base_items())

        def item_unregistered(item: Persistence.PersistentObject) -> None:
            if self.__data_item_changed_event_listener:
                self.__data_item_changed_event_listener.close()
                self.__data_item_changed_event_listener = None
            self._update_base_items(self._get_base_items())

        self.__item_reference.on_item_registered = item_registered
        self.__item_reference.on_item_unregistered = item_unregistered

        if self.__item_reference.item:
            item_registered(self.__item_reference.item)
            self.valid = True
        else:
            self.valid = False

    def close(self) -> None:
        if self.__data_item_changed_event_listener:
            self.__data_item_changed_event_listener.close()
            self.__data_item_changed_event_listener = None
        self.__item_reference.on_item_registered = None
        self.__item_reference.on_item_unregistered = None
        self.__item_reference = typing.cast(typing.Any, None)
        super().close()

    @property
    def value(self) -> typing.Optional[DataItem.DataItem]:
        return self._data_item

    def _get_base_items(self) -> typing.List[Persistence.PersistentObject]:
        return [self._data_item] if self._data_item else list()

    @property
    def _data_item(self) -> typing.Optional[DataItem.DataItem]:
        return typing.cast(typing.Optional[DataItem.DataItem], self.__item_reference.item if self.__item_reference else None)


class BoundDisplayData(BoundDisplayDataChannelBase):

    @property
    def value(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        display_values = self._display_values if self._display_data_channel else None
        return display_values.display_data_and_metadata if display_values else None


class BoundCroppedData(BoundDisplayDataChannelBase):

    @property
    def value(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        data_item = self._display_data_channel.data_item if self._display_data_channel else None
        xdata = data_item.xdata if data_item else None
        graphic = self._graphic
        if graphic and xdata:
            if isinstance(graphic, Graphics.RectangleTypeGraphic):
                return Core.function_crop(xdata, graphic.bounds.as_tuple())
            if isinstance(graphic, Graphics.IntervalGraphic):
                return Core.function_crop_interval(xdata, graphic.interval)
        return xdata


class BoundCroppedDisplayData(BoundDisplayDataChannelBase):

    @property
    def value(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        display_values = self._display_values if self._display_data_channel else None
        xdata = display_values.display_data_and_metadata if display_values else None
        graphic = self._graphic
        if xdata and graphic:
            if isinstance(graphic, Graphics.RectangleTypeGraphic):
                return Core.function_crop(xdata, graphic.bounds.as_tuple())
            if isinstance(graphic, Graphics.IntervalGraphic):
                return Core.function_crop_interval(xdata, graphic.interval)
        return xdata


class BoundFilterLikeData(BoundItemBase):

    def __init__(self, container: Persistence.PersistentObject, specifier: Specifier, secondary_specifier: typing.Optional[Specifier]) -> None:
        super().__init__(specifier)

        self.__item_reference = container.create_item_reference(item_specifier=Persistence.read_persistent_specifier(specifier.reference_uuid if specifier else None))
        self.__display_values_subscription: typing.Optional[DisplayItem.DisplayValuesSubscription] = None
        self.__display_item_item_inserted_event_listener: typing.Optional[Event.EventListener] = None
        self.__display_item_item_removed_event_listener: typing.Optional[Event.EventListener] = None

        def handle_display_values(display_values: typing.Optional[DisplayItem.DisplayValues]) -> None:
            self.data_event.fire(BoundDataEventType.DISPLAY_DATA)

        def maintain_data_source() -> None:
            self.__display_values_subscription = None
            if self.__display_item_item_inserted_event_listener:
                self.__display_item_item_inserted_event_listener.close()
                self.__display_item_item_inserted_event_listener = None
            if self.__display_item_item_removed_event_listener:
                self.__display_item_item_removed_event_listener.close()
                self.__display_item_item_removed_event_listener = None
            display_data_channel = self._display_data_channel
            if display_data_channel:
                self.__display_values_subscription = display_data_channel.subscribe_to_latest_display_values(handle_display_values)
                display_item = typing.cast(typing.Optional[DisplayItem.DisplayItem], display_data_channel.container)
                if display_item:
                    def maintain(name: str, value: typing.Any, index: int) -> None:
                        if name == "graphics":
                            maintain_data_source()

                    self.__display_item_item_inserted_event_listener = display_item.item_inserted_event.listen(maintain)
                    self.__display_item_item_removed_event_listener = display_item.item_removed_event.listen(maintain)
            self.valid = self.__display_values_subscription is not None
            self._update_base_items(self._get_base_items())

        def item_registered(item: Persistence.PersistentObject) -> None:
            maintain_data_source()

        def item_unregistered(item: Persistence.PersistentObject) -> None:
            maintain_data_source()

        self.__item_reference.on_item_registered = item_registered
        self.__item_reference.on_item_unregistered = item_unregistered

        maintain_data_source()

    def close(self) -> None:
        self.__display_values_subscription = None
        if self.__display_item_item_inserted_event_listener:
            self.__display_item_item_inserted_event_listener.close()
            self.__display_item_item_inserted_event_listener = None
        if self.__display_item_item_removed_event_listener:
            self.__display_item_item_removed_event_listener.close()
            self.__display_item_item_removed_event_listener = None
        self.__item_reference.on_item_registered = None
        self.__item_reference.on_item_unregistered = None
        super().close()

    def _get_base_items(self) -> typing.List[Persistence.PersistentObject]:
        base_items: typing.List[Persistence.PersistentObject] = list()
        if self._display_data_channel:
            data_item = self._display_data_channel.data_item
            display_item = self._display_data_channel.display_item
            if data_item and display_item:
                base_items.append(display_item)
                base_items.append(data_item)
                graphics = display_item.graphics
                for graphic in graphics:
                    if isinstance(graphic, (Graphics.PointTypeGraphic, Graphics.LineTypeGraphic, Graphics.RectangleTypeGraphic, Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic, Graphics.LatticeGraphic)):
                        base_items.append(graphic)
        return base_items

    @property
    def _display_data_channel(self) -> typing.Optional[DisplayItem.DisplayDataChannel]:
        return typing.cast(typing.Optional[DisplayItem.DisplayDataChannel], self.__item_reference.item if self.__item_reference else None)

    @property
    def _display_values(self) -> typing.Optional[DisplayItem.DisplayValues]:
        return self._display_data_channel.get_latest_display_values() if self._display_data_channel else None


class BoundFilterData(BoundFilterLikeData):

    @property
    def value(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        display_data_channel = self._display_data_channel
        if display_data_channel:
            display_item = display_data_channel.display_item
            # no display item is a special case for cascade removing graphics from computations. ugh.
            # see test_new_computation_becomes_unresolved_when_xdata_input_is_removed_from_document.
            if display_item:
                display_values = self._display_values
                if display_values:
                    display_data_and_metadata = display_values.display_data_and_metadata
                    if display_data_and_metadata:
                        shape = display_data_and_metadata.data_shape
                        calibrated_origin = Geometry.FloatPoint(y=display_item.datum_calibrations[0].convert_from_calibrated_value(0.0),
                                                                x=display_item.datum_calibrations[1].convert_from_calibrated_value(0.0))
                        mask = Graphics.create_mask_data(display_item.graphics, shape, calibrated_origin)
                        return DataAndMetadata.DataAndMetadata.from_data(mask)
        return None


class BoundFilteredData(BoundFilterLikeData):

    @property
    def value(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        display_data_channel = self._display_data_channel
        if display_data_channel:
            data_item = display_data_channel.data_item
            display_item = display_data_channel.display_item
            # no display item is a special case for cascade removing graphics from computations. ugh.
            # see test_new_computation_becomes_unresolved_when_xdata_input_is_removed_from_document.
            if display_item and data_item:
                xdata = data_item.xdata
                if xdata and xdata.is_data_2d and xdata.is_data_complex_type:
                    shape = xdata.data_shape
                    calibrated_origin = Geometry.FloatPoint(y=display_item.datum_calibrations[0].convert_from_calibrated_value(0.0),
                                                            x=display_item.datum_calibrations[1].convert_from_calibrated_value(0.0))
                    mask = Graphics.create_mask_data(display_item.graphics, shape, calibrated_origin)
                    return Core.function_fourier_mask(xdata, DataAndMetadata.DataAndMetadata.from_data(mask))
                return xdata
        return None


class BoundDataStructure(BoundItemBase):

    def __init__(self, container: Persistence.PersistentObject, specifier: StructureSpecifier, property_name: typing.Optional[str]) -> None:
        super().__init__(specifier)

        self.__property_name = property_name

        self.__item_reference = container.create_item_reference(item_specifier=Persistence.read_persistent_specifier(specifier.reference_uuid if specifier else None))
        self.__changed_listener: typing.Optional[Event.EventListener] = None
        self.__property_changed_listener: typing.Optional[Event.EventListener] = None

        def data_structure_changed(property_name: str) -> None:
            self.data_event.fire(BoundDataEventType.STRUCTURE)

        def item_registered(item: Persistence.PersistentObject) -> None:
            assert isinstance(item, DataStructure.DataStructure)
            self.__changed_listener = item.data_structure_changed_event.listen(data_structure_changed)
            self.__property_changed_listener = item.property_changed_event.listen(data_structure_changed)
            self._update_base_items(self._get_base_items())

        def item_unregistered(item: Persistence.PersistentObject) -> None:
            if self.__changed_listener:
                self.__changed_listener.close()
                self.__changed_listener = None
            if self.__property_changed_listener:
                self.__property_changed_listener.close()
                self.__property_changed_listener = None
            self._update_base_items(self._get_base_items())

        self.__item_reference.on_item_registered = item_registered
        self.__item_reference.on_item_unregistered = item_unregistered

        if self.__item_reference.item:
            item_registered(self.__item_reference.item)
            self.valid = True
        else:
            self.valid = False

    def close(self) -> None:
        if self.__changed_listener:
            self.__changed_listener.close()
            self.__changed_listener = None
        self.__item_reference.on_item_registered = None
        self.__item_reference.on_item_unregistered = None
        super().close()

    @property
    def value(self) -> typing.Any:
        if self.__object and self.__property_name:
            return self.__object.get_property_value(self.__property_name)
        return self.__object

    def _get_base_items(self) -> typing.List[Persistence.PersistentObject]:
        return [self.__object] if self.__object else list()

    @property
    def __object(self) -> typing.Optional[DataStructure.DataStructure]:
        return typing.cast(typing.Optional[DataStructure.DataStructure], self.__item_reference.item if self.__item_reference else None)


class BoundGraphic(BoundItemBase):

    def __init__(self, container: Persistence.PersistentObject, specifier: GraphicSpecifier, property_name: typing.Optional[str]) -> None:
        super().__init__(specifier)

        self.__property_name = property_name

        self.__item_reference = container.create_item_reference(item_specifier=Persistence.read_persistent_specifier(specifier.reference_uuid if specifier else None))
        self.__changed_listener: typing.Optional[Event.EventListener] = None

        def property_changed(property_name: str) -> None:
            # temporary hack to improve performance of line profile. long term solution will be to
            # have the computation decide what is a valid reason for recomputing.
            # see the test test_adjusting_interval_on_line_profile_does_not_trigger_recompute
            if not property_name in ("interval_descriptors",):
                self.data_event.fire(BoundDataEventType.GRAPHIC)

        def item_registered(item: Persistence.PersistentObject) -> None:
            self.__changed_listener = item.property_changed_event.listen(property_changed)
            self._update_base_items(self._get_base_items())

        def item_unregistered(item: Persistence.PersistentObject) -> None:
            if self.__changed_listener:
                self.__changed_listener.close()
                self.__changed_listener = None
            self._update_base_items(self._get_base_items())

        self.__item_reference.on_item_registered = item_registered
        self.__item_reference.on_item_unregistered = item_unregistered

        if self.__item_reference.item:
            item_registered(self.__item_reference.item)
            self.valid = True
        else:
            self.valid = False

    def close(self) -> None:
        if self.__changed_listener:
            self.__changed_listener.close()
            self.__changed_listener = None
        self.__item_reference.on_item_registered = None
        self.__item_reference.on_item_unregistered = None
        super().close()

    @property
    def value(self) -> typing.Any:
        if self.__property_name:
            return getattr(self.__object, self.__property_name)
        return self.__object

    def _get_base_items(self) -> typing.List[Persistence.PersistentObject]:
        return [self.__object] if self.__object else list()

    @property
    def __object(self) -> typing.Optional[Graphics.Graphic]:
        return typing.cast(Graphics.Graphic, self.__item_reference.item if self.__item_reference else None)

    @property
    def _graphic(self) -> typing.Optional[Graphics.Graphic]:
        return self.__object


class ComputationItem:
    def __init__(self, *, item: typing.Optional[Persistence.PersistentObject] = None, type: typing.Optional[str] = None,
                 secondary_item: typing.Optional[Persistence.PersistentObject] = None,
                 items: typing.Optional[typing.Sequence[ComputationItem]] = None) -> None:
        self.item = item
        self.type = type
        self.secondary_item = secondary_item
        self.items = list(items) if items is not None else None


def make_item(item: typing.Optional[Persistence.PersistentObject], *, type: typing.Optional[str] = None, secondary_item: typing.Optional[Persistence.PersistentObject] = None) -> ComputationItem:
    return ComputationItem(item=item, type=type, secondary_item=secondary_item)


def make_item_list(items: typing.Sequence[Persistence.PersistentObject], *, type: typing.Optional[str] = None) -> ComputationItem:
    computation_items: typing.List[ComputationItem] = list()
    for item in items:
        if isinstance(item, ComputationItem):
            computation_items.append(item)
        else:
            computation_items.append(make_item(item, type=type))
    return ComputationItem(items=computation_items)


class BoundList(BoundItemBase):

    def __init__(self, bound_items: typing.Sequence[typing.Optional[BoundItemBase]]) -> None:
        super().__init__(None)
        self.__bound_items: typing.List[typing.Optional[BoundItemBase]] = list()
        self.is_list = True
        self.__changed_listeners: typing.List[typing.Optional[Event.EventListener]] = list()
        self.__inserted_listeners: typing.List[typing.Optional[Event.EventListener]] = list()
        self.__removed_listeners: typing.List[typing.Optional[Event.EventListener]] = list()
        for index, bound_item in enumerate(bound_items):
            self.item_inserted(index, bound_item)

    def close(self) -> None:
        while len(self.__bound_items) > 0:
            self.item_removed(0)
        self.__bound_items = typing.cast(typing.Any, None)
        self.__resolved_items = None
        self.__changed_listeners = typing.cast(typing.Any, None)
        self.__inserted_listeners = typing.cast(typing.Any, None)
        self.__removed_listeners = typing.cast(typing.Any, None)
        super().close()

    @property
    def value(self) -> typing.List[typing.Any]:
        return [bound_item.value if bound_item else None for bound_item in self.__bound_items]

    def _get_base_items(self) -> typing.List[Persistence.PersistentObject]:
        base_items: typing.List[Persistence.PersistentObject] = list()
        for bound_item in self.__bound_items:
            if bound_item:
                for base_object in bound_item.base_items:
                    if not base_object in base_items:
                        base_items.append(base_object)
        return base_items

    def get_items(self) -> typing.List[typing.Optional[BoundItemBase]]:
        return copy.copy(self.__bound_items)

    def item_inserted(self, index: int, bound_item: typing.Optional[BoundItemBase]) -> None:
        self.__bound_items.insert(index, bound_item)

        def handle_bound_items_changed(name: str, index: int, value: typing.Any) -> None:
            if name == "base_items":
                self._update_base_items(self._get_base_items())

        self.__changed_listeners.insert(index, bound_item.data_event.listen(self.data_event.fire) if bound_item else None)
        self.__inserted_listeners.insert(index, bound_item.item_inserted_event.listen(handle_bound_items_changed) if bound_item else None)
        self.__removed_listeners.insert(index, bound_item.item_removed_event.listen(handle_bound_items_changed) if bound_item else None)
        self._update_base_items(self._get_base_items())

    def item_removed(self, index: int) -> None:
        bound_item = self.__bound_items.pop(index)
        if bound_item:
            bound_item.close()
        changed_listener = self.__changed_listeners.pop(index)
        if changed_listener:
            changed_listener.close()
        inserted_listener = self.__inserted_listeners.pop(index)
        if inserted_listener:
            inserted_listener.close()
        removed_listener = self.__removed_listeners.pop(index)
        if removed_listener:
            removed_listener.close()
        self._update_base_items(self._get_base_items())



class ComputationErrorNotification(Notification.Notification):
    def __init__(self, computation: Computation) -> None:
        super().__init__("nion.computation.error", "\N{WARNING SIGN} Computation Error", "The computation is in an error state.", computation.error_text or str())
        self.computation = computation


class Computation(Persistence.PersistentObject):
    """A computation on data and other inputs.

    Watches for changes to the sources and fires a computation_mutated_event
    when a new computation needs to occur.

    Call parse_expression first to establish the computation. Bind will be automatically called.

    Call bind to establish connections after reloading. Call unbind to release connections.

    Listen to computation_mutated_event and call evaluate in response to perform
    computation (on thread).

    The computation will listen to any bound items established in the bind method. When those
    items signal a change, the computation_mutated_event will be fired.

    The processing_id is used to specify a computation that may be updated with a different script
    in the future. For instance, the line profile processing via the UI will produce a somewhat
    complicated computation expression. By recording processing_id, if the computation expression
    evolves to a better version in the future, it can be replaced with the newer version by knowing
    that the intention of the original expression was a line profile from the UI.

    The processing_id is cleared if the user changes the script expression.
    """

    def __init__(self, expression: typing.Optional[str] = None) -> None:
        super().__init__()
        self.define_type("computation")
        self.define_property("source_specifier", changed=self.__source_specifier_changed, key="source_uuid", hidden=True)
        self.define_property("original_expression", expression, hidden=True)
        self.define_property("error_text", changed=self.__error_changed, hidden=True)
        self.define_property("label", changed=self.__label_changed, hidden=True)
        self.define_property("processing_id", hidden=True)  # see note above
        self.define_relationship("variables", variable_factory, insert=self.__variable_inserted, remove=self.__variable_removed, hidden=True)
        self.define_relationship("results", result_factory, insert=self.__result_inserted, remove=self.__result_removed, hidden=True)
        self.attributes: Persistence.PersistentDictType = dict()  # not persistent, defined by underlying class
        self.__source_reference = self.create_item_reference()
        self.__variable_changed_event_listeners: typing.List[Event.EventListener] = list()
        self.__variable_base_item_inserted_event_listeners: typing.List[Event.EventListener] = list()
        self.__variable_base_item_removed_event_listeners: typing.List[Event.EventListener] = list()
        self.__result_base_item_inserted_event_listeners: typing.List[Event.EventListener] = list()
        self.__result_base_item_removed_event_listeners: typing.List[Event.EventListener] = list()
        self.__processor: typing.Optional[ComputationProcessor] = None
        self.last_evaluate_data_time = 0.0
        self.needs_update = expression is not None
        self.computation_mutated_event = Event.Event()
        self.computation_output_changed_event = Event.Event()
        self.is_initial_computation_complete = threading.Event()  # helpful for waiting for initial computation
        self._evaluation_count_for_test = 0
        self.__input_items: typing.List[Persistence.PersistentObject] = list()
        self.__direct_input_items: typing.List[Persistence.PersistentObject] = list()
        self.__output_items: typing.List[Persistence.PersistentObject] = list()
        self._inputs: typing.Set[Persistence.PersistentObject] = set()  # used by document model for tracking dependencies
        self._outputs: typing.Set[Persistence.PersistentObject] = set()
        self.pending_project: typing.Optional[Project.Project] = None  # used for new computations to tell them where they'll end up
        self.__elapsed_time: typing.Optional[float] = None
        self.__last_timestamp: typing.Optional[datetime.datetime] = None
        self.__error_stack_trace = str()
        self.__error_notification: typing.Optional[Notification.Notification] = None

    @property
    def variables(self) -> typing.Sequence[ComputationVariable]:
        return typing.cast(typing.Sequence[ComputationVariable], self._get_relationship_values("variables"))

    @property
    def results(self) -> typing.Sequence[ComputationOutput]:
        return typing.cast(typing.Sequence[ComputationOutput], self._get_relationship_values("results"))

    @property
    def project(self) -> Project.Project:
        return typing.cast("Project.Project", self.container)

    def create_proxy(self) -> Persistence.PersistentObjectProxy[Computation]:
        return self.project.create_item_proxy(item=self)

    @property
    def item_specifier(self) -> Persistence.PersistentObjectSpecifier:
        return Persistence.PersistentObjectSpecifier(self.uuid)

    def read_from_dict(self, properties: PersistentDictType) -> None:
        super().read_from_dict(properties)
        processing_id = self.processing_id
        self.__processor = _processors.get(processing_id) if processing_id else None

    def read_properties_from_dict(self, d: Persistence.PersistentDictType) -> None:
        self.__source_reference.item_specifier = Persistence.read_persistent_specifier(d.get("source_uuid", None))
        self.original_expression = d.get("original_expression", self.original_expression)
        self.error_text = d.get("error_text", self.error_text)
        self.label = d.get("label", self.label)
        self.processing_id = d.get("processing_id", self.processing_id)

    @property
    def source(self) -> typing.Optional[Persistence.PersistentObject]:
        return self.__source_reference.item

    @source.setter
    def source(self, source: typing.Optional[Persistence.PersistentObject]) -> None:
        self.__source_reference.item = source
        self.source_specifier = Persistence.write_persistent_specifier(source.uuid) if source else None

    def is_valid_with_removals(self, items: typing.Set[Persistence.PersistentObject]) -> bool:
        for variable in self.variables:
            if variable.object_specifiers:
                input_items = set(variable.input_items)
                # if removing items results in no bound items and at least some items are in bound items, computation
                # is no longer valid. all items of at least one set have been removed. do not remove computations with
                # empty bound items that already exist.
                if not (input_items - items) and input_items.intersection(items):
                    return False
        return True

    def __source_specifier_changed(self, name: str, d: Persistence.PersistentDictType) -> None:
        self.__source_reference.item_specifier = Persistence.read_persistent_specifier(d)

    @property
    def processing_id(self) -> typing.Optional[str]:
        return typing.cast(typing.Optional[str], self._get_persistent_property_value("processing_id"))

    @processing_id.setter
    def processing_id(self, value: typing.Optional[str]) -> None:
        self._set_persistent_property_value("processing_id", value)
        self.__processor = _processors.get(value) if value else None

    @property
    def label(self) -> typing.Optional[str]:
        label = typing.cast(typing.Optional[str], self._get_persistent_property_value("label"))
        if not label:
            processing_id = self.processing_id
            compute_class = _computation_types.get(processing_id) if processing_id else None
            if compute_class:
                label = typing.cast(typing.Optional[str], getattr(compute_class, "label", None))
        return label

    @label.setter
    def label(self, value: typing.Optional[str]) -> None:
        self._set_persistent_property_value("label", value)

    def get_computation_attribute(self, attribute: str, default: typing.Any = None) -> typing.Any:
        """Returns the attribute for the computation."""
        processing_id = self.processing_id
        compute_class = _computation_types.get(processing_id) if processing_id else None
        if compute_class:
            return getattr(compute_class, "attributes", dict()).get(attribute, default)
        return default

    @property
    def source_specifier(self) -> typing.Optional[Persistence._SpecifierType]:
        return typing.cast(typing.Optional[Persistence._SpecifierType], self._get_persistent_property_value("source_specifier"))

    @source_specifier.setter
    def source_specifier(self, value: typing.Optional[Persistence._SpecifierType]) -> None:
        self._set_persistent_property_value("source_specifier", value)

    @property
    def original_expression(self) -> typing.Optional[str]:
        return typing.cast(typing.Optional[str], self._get_persistent_property_value("original_expression"))

    @original_expression.setter
    def original_expression(self, value: typing.Optional[str]) -> None:
        self._set_persistent_property_value("original_expression", value)

    @property
    def error_text(self) -> typing.Optional[str]:
        return typing.cast(typing.Optional[str], self._get_persistent_property_value("error_text"))

    @error_text.setter
    def error_text(self, value: typing.Optional[str]) -> None:
        modified_state = self.modified_state
        self._set_persistent_property_value("error_text", value)
        self.modified_state = modified_state
        if value:
            self.__error_notification = ComputationErrorNotification(self)
            Notification.notify(self.__error_notification)
        elif self.__error_notification:
            self.__error_notification.dismiss()
            self.__error_notification = None

    @property
    def error_stack_trace(self) -> str:
        return self.__error_stack_trace

    @error_stack_trace.setter
    def error_stack_trace(self, value: str) -> None:
        if self.__error_stack_trace != value:
            self.__error_stack_trace = value
            self.notify_property_changed("error_stack_trace")

    def update_status(self, error_text: typing.Optional[str], error_stack_trace: typing.Optional[str], elapsed_time: typing.Optional[float]) -> None:
        self.__elapsed_time = elapsed_time
        self.__last_timestamp = DateTime.utcnow()
        if self.error_text != error_text:
            self.error_text = error_text
        error_stack_trace = error_stack_trace or str()
        if self.error_stack_trace != error_stack_trace:
            self.error_stack_trace = error_stack_trace
        self.notify_property_changed("status")

    @property
    def status(self) -> str:
        if self.error_text:
            return _("Error: ") + self.error_text
        if self.__elapsed_time and self.__last_timestamp:
            local_modified_datetime = self.__last_timestamp + datetime.timedelta(minutes=Utility.local_utcoffset_minutes(self.__last_timestamp))
            time_str = local_modified_datetime.strftime('%Y-%m-%d %H:%M:%S')
            return f"Last: {time_str} ({round(self.__elapsed_time * 1000)}ms)"
        return str()

    def __error_changed(self, name: str, value: typing.Optional[str]) -> None:
        self.notify_property_changed(name)
        self.computation_mutated_event.fire()

    def __label_changed(self, name: str, value: typing.Optional[str]) -> None:
        self.notify_property_changed(name)
        self.computation_mutated_event.fire()

    def __get_output_items(self) -> typing.List[Persistence.PersistentObject]:
        output_items = list()
        for result in self.results:
            output_items.extend(result.output_items)
        return output_items

    def __result_inserted(self, name: str, before_index: int, result: ComputationOutput) -> None:
        assert name == "results"

        def handle_result_item_inserted(name: str, value: typing.Any, index: int) -> None:
            if name == "base_items":
                update_diff_notify(self, "output_items", self.__output_items, self.__get_output_items())
                self.computation_output_changed_event.fire()

        def handle_result_item_removed(name: str, value: typing.Any, index: int) -> None:
            if name == "base_items":
                update_diff_notify(self, "output_items", self.__output_items, self.__get_output_items())

        self.__result_base_item_inserted_event_listeners.insert(before_index, result.item_inserted_event.listen(handle_result_item_inserted))
        self.__result_base_item_removed_event_listeners.insert(before_index, result.item_removed_event.listen(handle_result_item_removed))

        result.bind()

        update_diff_notify(self, "output_items", self.__output_items, self.__get_output_items())

    def __result_removed(self, name: str, index: int, result: ComputationOutput) -> None:
        assert name == "results"
        self.__result_base_item_inserted_event_listeners.pop(index).close()
        self.__result_base_item_removed_event_listeners.pop(index).close()
        result.unbind()
        update_diff_notify(self, "output_items", self.__output_items, self.__get_output_items())

    def __get_input_items(self) -> typing.List[Persistence.PersistentObject]:
        input_items = list()
        for variable in self.variables:
            input_items.extend(variable.input_items)
        return input_items

    def __get_direct_input_items(self) -> typing.List[Persistence.PersistentObject]:
        input_items = list()
        for variable in self.variables:
            input_items.extend(variable.direct_input_items)
        return input_items

    def __variable_inserted(self, name: str, before_index: int, variable: ComputationVariable) -> None:
        assert name == "variables"

        def needs_update(variable: ComputationVariable, event_type: BoundDataEventType) -> None:
            if not self.__processor or self.__processor.needs_update_for_event(variable.name, event_type):
                self.needs_update = True
            self.computation_mutated_event.fire()

        self.__variable_changed_event_listeners.insert(before_index, variable.data_event.listen(functools.partial(needs_update, variable)))

        def handle_variable_item_inserted(variable: ComputationVariable, name: str, value: typing.Any, index: int) -> None:
            if name == "base_items":
                update_diff_notify(self, "input_items", self.__input_items, self.__get_input_items())
                update_diff_notify(self, "direct_input_items", self.__direct_input_items, self.__get_direct_input_items())
                needs_update(variable, BoundDataEventType.UNSPECIFIED)

        def handle_variable_item_removed(variable: ComputationVariable, name: str, value: typing.Any, index: int) -> None:
            if name == "base_items":
                update_diff_notify(self, "input_items", self.__input_items, self.__get_input_items())
                update_diff_notify(self, "direct_input_items", self.__direct_input_items, self.__get_direct_input_items())
                needs_update(variable, BoundDataEventType.UNSPECIFIED)

        self.__variable_base_item_inserted_event_listeners.insert(before_index, variable.item_inserted_event.listen(functools.partial(handle_variable_item_inserted, variable)))
        self.__variable_base_item_removed_event_listeners.insert(before_index, variable.item_removed_event.listen(functools.partial(handle_variable_item_removed, variable)))

        variable.bind()

        if not self._is_reading:
            self.computation_mutated_event.fire()
            self.needs_update = True
            self.notify_insert_item("variables", variable, before_index)

        update_diff_notify(self, "input_items", self.__input_items, self.__get_input_items())
        update_diff_notify(self, "direct_input_items", self.__direct_input_items, self.__get_direct_input_items())

    def __variable_removed(self, name: str, index: int, variable: ComputationVariable) -> None:
        assert name == "variables"
        self.__variable_changed_event_listeners.pop(index).close()
        self.__variable_base_item_inserted_event_listeners.pop(index).close()
        self.__variable_base_item_removed_event_listeners.pop(index).close()
        variable.unbind()
        self.computation_mutated_event.fire()
        self.needs_update = True
        self.notify_remove_item("variables", variable, index)
        update_diff_notify(self, "input_items", self.__input_items, self.__get_input_items())
        update_diff_notify(self, "direct_input_items", self.__direct_input_items, self.__get_direct_input_items())

    def add_variable(self, variable: ComputationVariable) -> None:
        self.insert_variable(len(self.variables), variable)

    def insert_variable(self, index: int, variable: ComputationVariable) -> None:
        self.insert_item("variables", index, variable)

    def remove_variable(self, variable: ComputationVariable) -> None:
        self.remove_item("variables", variable)

    def create_variable(self, name: typing.Optional[str] = None, value_type: typing.Optional[ComputationVariableType | str] = None,
                        value: typing.Any = None, value_default: typing.Any = None, value_min: typing.Any = None,
                        value_max: typing.Any = None, control_type: typing.Optional[str] = None,
                        specified_item: typing.Optional[Persistence.PersistentObject] = None,
                        label: typing.Optional[str] = None) -> ComputationVariable:
        specifier = get_object_specifier(specified_item)
        value_type_e = value_type if isinstance(value_type, ComputationVariableType) else (_map_identifier_to_variable_type[value_type] if value_type else None)
        variable = ComputationVariable(name, value_type=value_type_e, value=value, value_default=value_default,
                                       value_min=value_min, value_max=value_max, control_type=control_type,
                                       specifier=specifier, label=label)
        self.add_variable(variable)
        return variable

    def create_input_item(self, name: str, input_item: ComputationItem, *, property_name: typing.Optional[str] = None,
                          label: typing.Optional[str] = None, _item_specifier: typing.Optional[Specifier] = None) -> ComputationVariable:
        # Note: _item_specifier is only for testing
        if input_item.items is not None:
            variable = ComputationVariable(name, items=input_item.items, label=label)
            self.add_variable(variable)
            return variable
        else:
            specifier = _item_specifier or get_object_specifier(input_item.item, input_item.type)
            secondary_specifier = get_object_specifier(input_item.secondary_item) if input_item.secondary_item else None
            variable = ComputationVariable(name, specifier=specifier, secondary_specifier=secondary_specifier, property_name=property_name, label=label)
            self.add_variable(variable)
            return variable

    def create_output_item(self, name: str, output_item: typing.Optional[ComputationItem] = None, *,
                           label: typing.Optional[str] = None,
                           _item_specifier: typing.Optional[Specifier] = None) -> typing.Optional[ComputationOutput]:
        # Note: _item_specifier is only for testing
        if output_item and output_item.items is not None:
            specifiers = [get_object_specifier(item.item) for item in output_item.items]
            result = ComputationOutput(name, specifiers=specifiers, label=label)  # type: ignore
            self.append_item("results", result)
            self.computation_mutated_event.fire()
            return result
        elif output_item:
            assert not output_item.type
            assert not output_item.secondary_item
            specifier = _item_specifier or get_object_specifier(output_item.item)
            result = ComputationOutput(name, specifier=specifier, label=label)
            self.append_item("results", result)
            self.computation_mutated_event.fire()
            return result
        return None

    def remove_item_from_objects(self, name: str, index: int) -> None:
        variable = self._get_variable(name)
        if variable:
            variable._remove_item_from_list(index)

    def insert_item_into_objects(self, name: str, index: int, input_item: ComputationItem) -> None:
        variable = self._get_variable(name)
        specifier = get_object_specifier(input_item.item, input_item.type)
        if variable and specifier is not None:
            variable._insert_specifier_in_list(index, specifier)

    def list_item_removed(self, object: typing.Any) -> typing.Optional[typing.Tuple[int, int, typing.Optional[Specifier]]]:
        # when an item is removed from the library, this method is called for each computation.
        # if the item being removed matches a variable item, mark the computation as needing an update.
        # if the item is contained in a list variable, create undelete entries and return them.
        # undelete_entries = list()
        for variable in self.variables:
            # check if the bound item matches the object. mark for update if so.
            # TODO: really needed?
            if variable.bound_item and variable.bound_item.value == object:
                self.needs_update = True
            # check if the bound item is a list and item in list matches the object. if so, create
            # an undelete entry for the variable. undelete entry describes how to reconstitute
            # the list item.
            if variable.object_specifiers:
                for index, (object_specifier, bound_item) in enumerate(zip(variable.object_specifiers, variable._bound_items)):
                    base_items = bound_item.base_items if bound_item else list()
                    if object in base_items:
                        object_specifier_copy = copy.deepcopy(object_specifier)
                        variables_index = self.variables.index(variable)
                        variable._remove_item_from_list(index)
                        return (index, variables_index, object_specifier_copy)
        return None

    @property
    def expression(self) -> typing.Optional[str]:
        return self.original_expression

    @expression.setter
    def expression(self, value: typing.Optional[str]) -> None:
        if value != self.original_expression:
            self.original_expression = value
            self.processing_id = None
            self.__processor = None
            self.needs_update = True
            self.computation_mutated_event.fire()

    @classmethod
    def parse_names(cls, expression: str) -> typing.Set[str]:
        """Return the list of identifiers used in the expression."""
        names: typing.Set[str] = set()
        try:
            ast_node = ast.parse(expression, "ast")

            class Visitor(ast.NodeVisitor):
                def visit_Name(self, node: typing.Any) -> None:
                    names.add(node.id)

            Visitor().visit(ast_node)
        except Exception:
            pass
        return names

    def __resolve_inputs(self, api: typing.Any) -> typing.Tuple[typing.Dict[str, typing.Any], bool]:
        kwargs: typing.Dict[str, typing.Any] = dict()
        is_resolved = True
        for variable in self.variables:
            bound_object = variable.bound_item
            if bound_object is not None:
                resolved_object = bound_object.value if bound_object else None
                # in the ideal world, we could clone the object/data and computations would not be
                # able to modify the input objects; reality, though, dictates that performance is
                # more important than this protection. so use the resolved object directly.
                api_object = api._new_api_object(resolved_object) if resolved_object else None
                kwargs[variable.name] = api_object if api_object else resolved_object  # use api only if resolved_object is an api style object
                is_resolved = resolved_object is not None
            else:
                is_resolved = False
        for result in self.results:
            is_resolved = is_resolved and result.is_resolved
        return kwargs, is_resolved

    def evaluate(self, api: typing.Any) -> typing.Optional[ComputationExecutor]:
        executor: typing.Optional[ComputationExecutor] = None
        needs_update = self.needs_update
        self.needs_update = False
        if needs_update:
            if self.expression:
                executor = ScriptExpressionComputationExecutor(self, api)
            else:
                executor = RegisteredComputationExecutor(self, api)
            kwargs, is_resolved = self.__resolve_inputs(api)
            if is_resolved:
                executor.execute(**kwargs)
            else:
                executor.error_text = _("Missing parameters.")
            self._evaluation_count_for_test += 1
            self.last_evaluate_data_time = time.perf_counter()
        return executor

    @property
    def is_resolved(self) -> bool:
        for variable in self.variables:
            if not variable.is_resolved:
                return False
        for result in self.results:
            if not result.is_resolved:
                return False
        return True

    def undelete_variable_item(self, name: str, index: int, specifier: Specifier) -> None:
        variable = self._get_variable(name)
        if variable:
            variable._insert_specifier_in_list(index, specifier)

    def get_preliminary_input_items(self) -> typing.Set[Persistence.PersistentObject]:
        input_items: typing.Set[Persistence.PersistentObject] = set()
        container = self if self.persistent_object_context else self.pending_project or self
        for variable in self.variables:
            if variable.object_specifiers:
                for object_specifier in variable.object_specifiers:
                    bound_item = object_specifier.get_bound_item(container) if object_specifier else None
                    if bound_item:
                        with contextlib.closing(bound_item):
                            input_items.update(set(bound_item.base_items))
            else:
                if variable._variable_specifier:
                    bound_item = variable._variable_specifier.get_bound_item(container, variable.secondary_specifier, variable.property_name)
                    if bound_item:
                        with contextlib.closing(bound_item):
                            input_items.update(set(bound_item.base_items))
        return input_items

    def get_preliminary_output_items(self) -> typing.Set[Persistence.PersistentObject]:
        output_items: typing.Set[Persistence.PersistentObject] = set()
        container = self if self.persistent_object_context else self.pending_project or self
        for result in self.results:
            if result.specifier:
                bound_item = result.specifier.get_bound_item(container) if result.specifier else None
                if bound_item:
                    with contextlib.closing(bound_item):
                        output_items.update(set(bound_item.base_items))
            else:
                for specifier in result.specifiers:
                    bound_item = specifier.get_bound_item(container) if specifier else None
                    if bound_item:
                        with contextlib.closing(bound_item):
                            output_items.update(set(bound_item.base_items))
        return output_items

    @property
    def input_items(self) -> typing.List[Persistence.PersistentObject]:
        return self.__input_items

    @property
    def direct_input_items(self) -> typing.List[Persistence.PersistentObject]:
        return self.__direct_input_items

    @property
    def output_items(self) -> typing.List[Persistence.PersistentObject]:
        return self.__output_items

    def set_input_item(self, name: str, input_item: ComputationItem) -> None:
        variable = self._get_variable(name)
        if variable:
            assert input_item.item
            assert input_item.type is None
            assert input_item.secondary_item is None
            assert input_item.items is None
            variable.specifier = get_object_specifier(input_item.item)

    def set_output_item(self, name:str, output_item: typing.Optional[ComputationItem]) -> None:
        result = self._get_output(name)
        if result:
            if output_item and output_item.items is not None:
                result.specifiers = [get_object_specifier(o.item) for o in output_item.items]
            else:
                if output_item:
                    assert output_item.item
                    assert output_item.type is None
                    assert output_item.secondary_item is None
                result.specifier = get_object_specifier(output_item.item) if output_item else None

    def get_input(self, name: str) -> typing.Any:
        variable = self._get_variable(name)
        return variable.bound_item.value if variable and variable.bound_item else None

    def get_output(self, name: str) -> typing.Any:
        result = self._get_output(name)
        if result:
            if isinstance(result.bound_item, BoundList):
                return result.output_items
            elif result.bound_item:
                return result.bound_item.value
            else:
                return None
        return None

    def set_input_value(self, name: str, value: typing.Any) -> None:
        variable = self._get_variable(name)
        if variable:
            variable.value = value

    def get_input_value(self, name: str) -> typing.Any:
        variable = self._get_variable(name)
        assert variable
        with contextlib.closing(variable.bound_variable) as bound_variable:
            return bound_variable.value if variable and bound_variable else None

    def get_variable_input_items(self, name: str) -> typing.Set[Persistence.PersistentObject]:
        variable = self._get_variable(name)
        return set(variable.input_items) if variable else set()

    def _get_variable(self, name: str) -> typing.Optional[ComputationVariable]:
        for variable in self.variables:
            if variable.name == name:
                return variable
        return None

    def _get_output(self, name: str) -> typing.Optional[ComputationOutput]:
        for result in self.results:
            if result.name == name:
                return result
        return None

    def _has_variable(self, name: str) -> bool:
        variable = self._get_variable(name)
        return variable is not None

    def _clear_referenced_object(self, name: str) -> None:
        result = self._get_output(name)
        if result:
            self.remove_item("results", result)
            self.computation_mutated_event.fire()
            self.needs_update = True

    def update_script(self) -> None:
        processing_id = self.processing_id
        processor = _processors.get(processing_id) if processing_id else None
        if processor:
            if expression := processor.expression:
                src_names = [processing_description_source.name for processing_description_source in processor.sources]
                script = xdata_expression(expression)
                script = script.format(**dict(zip(src_names, src_names)))
                self._get_persistent_property("original_expression").value = script

    def reset(self) -> None:
        self.needs_update = False

    def recompute(self) -> typing.Optional[ComputationExecutor]:
        # evaluate the computation in a thread safe manner
        # returns a list of functions that must be called on the main thread to finish the recompute action
        # threadsafe
        if self.needs_update:
            try:
                api = PlugInManager.api_broker_fn("~1.0", None)
                executor = self.evaluate(api)
                if executor:
                    throttle_time = max(computation_min_period - (time.perf_counter() - self.last_evaluate_data_time), 0) if not executor.error_text else 0.0
                    time.sleep(max(throttle_time, min(executor.last_execution_time * computation_min_factor, 1.0)))
                    return executor
            except Exception as e:
                import traceback
                traceback.print_exc()
        return None


class ComputationExecutor:

    def __init__(self, computation: Computation) -> None:
        self.__computation: typing.Optional[Computation] = computation
        self.error_text: typing.Optional[str] = None
        self.error_stack_trace = str()
        self.__last_execution_time: float = 0.0
        self.__aborted = False
        self.__activity_lock = threading.RLock()
        self.__activity: typing.Optional[ComputationActivity] = ComputationActivity(computation)
        self.__activity.state = "computing"
        Activity.append_activity(self.__activity)

        def computation_deleted(computation_executor: ComputationExecutor) -> None:
            computation_executor.__computation = None

        # handle case where computation gets deleted during execute and execute has an error.
        self.__about_to_close_event_listener = self.__computation.about_to_close_event.listen(ReferenceCounting.weak_partial(computation_deleted, self))

    def close(self) -> None:
        self.__about_to_close_event_listener = typing.cast(typing.Any, None)
        if self.__activity:
            Activity.activity_finished(self.__activity)
            self.__activity = None

    def mark_initial_computation_complete(self) -> None:
        if self.__computation:
            self.__computation.is_initial_computation_complete.set()

    @property
    def computation(self) -> typing.Optional[Computation]:
        return self.__computation

    def _execute(self, **kwargs: typing.Any) -> None: raise NotImplementedError()

    def _commit(self) -> None: raise NotImplementedError()

    def execute(self, **kwargs: typing.Any) -> None:
        try:
            with Process.audit(f"execute.{self.__computation.processing_id if self.__computation else 'unknown'}"):
                start_time = time.perf_counter()
                self._execute(**kwargs)
                self.__last_execution_time = time.perf_counter() - start_time
        except Exception as e:
            self.__last_execution_time = 0.0
            self.error_stack_trace = "".join(traceback.format_exception(*sys.exc_info()))
            self.error_text = str(e) or "Unable to evaluate script."  # a stack trace would be too much information right now

    def commit(self) -> None:
        if not self.error_text and not self.__aborted:
            try:
                self._commit()
            finally:
                if self.__activity:
                    Activity.activity_finished(self.__activity)
                    self.__activity = None
        if self.__computation:
            self.__computation.update_status(self.error_text, self.error_stack_trace, self.__last_execution_time)

    def abort(self) -> None:
        self.__aborted = True
        with self.__activity_lock:
            if self.__activity:
                Activity.activity_finished(self.__activity)
                self.__activity = None

    @property
    def last_execution_time(self) -> float:
        return self.__last_execution_time

    @property
    def _target_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return None


class ScriptExpressionComputationExecutor(ComputationExecutor):

    class DataItemTarget:
        def __init__(self) -> None:
            self.__xdata: typing.Optional[DataAndMetadata.DataAndMetadata] = None
            self.data_modified = datetime.datetime.min

        @property
        def xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
            return self.__xdata

        @xdata.setter
        def xdata(self, value: typing.Optional[DataAndMetadata._DataAndMetadataLike]) -> None:
            self.__xdata = DataAndMetadata.promote_ndarray(value) if value is not None else None
            self.data_modified = DateTime.utcnow()

        @property
        def data(self) -> DataAndMetadata._ImageDataType:
            return typing.cast(DataAndMetadata._ImageDataType, None)

        @data.setter
        def data(self, value: DataAndMetadata._ImageDataType) -> None:
            self.xdata = DataAndMetadata.new_data_and_metadata(value)

    def __init__(self, computation: Computation, api: typing.Any) -> None:
        super().__init__(computation)
        assert computation.expression
        expression = computation.expression
        data_item = typing.cast(typing.Optional[DataItem.DataItem], computation.get_output("target"))
        self.__api = api
        self.__expression = expression
        self.__data_item = data_item or DataItem.new_data_item(None)
        self.__xdata: typing.Optional[DataAndMetadata.DataAndMetadata] = None
        self.__data_item_created = False
        if not data_item:
            self.__data_item_created = True
        self.__data_item_target = ScriptExpressionComputationExecutor.DataItemTarget()
        self.__data_item_data_modified = self.__data_item.data_modified or datetime.datetime.min

    def close(self) -> None:
        if self.__data_item_created:
            self.__data_item.close()
            self.__data_item = typing.cast(typing.Any, None)
            self.__data_item_created = False
        super().close()

    def _execute(self, **kwargs: typing.Any) -> None:
        assert self.__data_item_target is not None
        if self.__expression:
            code_lines = []
            g = kwargs
            g["api"] = self.__api
            g["target"] = self.__data_item_target
            l: typing.Dict[str, typing.Any] = dict()
            expression_lines = self.__expression.split("\n")
            code_lines.extend(expression_lines)
            code = "\n".join(code_lines)
            compiled = compile(code, "expr", "exec")
            exec(compiled, g, l)

    def _commit(self) -> None:
        # commit the result item clones back into the document. this method is guaranteed to run at
        # periodic and shouldn't do anything too time-consuming.
        data_item_clone_data_modified = self.__data_item_target.data_modified or datetime.datetime.min
        with self.__data_item.data_item_changes(), self.__data_item.data_source_changes():
            # note: use data_modified, but Windows doesn't have high enough time resolution
            # on fast machines, so ensure that any data_modified timestamp is created using
            # DateTime.utcnow() / Schema.utcnow().
            if data_item_clone_data_modified > self.__data_item_data_modified:
                self.__data_item.set_xdata(self.__data_item_target.xdata)
        if self.__data_item_created:
            self.__xdata = self.__data_item.xdata
            self.__data_item.close()
            self.__data_item = typing.cast(typing.Any, None)
            self.__data_item_created = False

    @property
    def _target_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return self.__data_item.xdata if self.__data_item else self.__xdata


PersistentDictType = typing.Dict[str, typing.Any]


class ComputationProcessorRequirement(typing.Protocol):
    def is_data_item_valid(self, data_item: DataItem.DataItem) -> bool: ...


class ComputationProcessorRequirementDataRank(ComputationProcessorRequirement):
    def __init__(self, values: typing.Sequence[int]) -> None:
        self.values = list(values)

    @classmethod
    def from_dict(cls, d: PersistentDictType) -> ComputationProcessorRequirementDataRank:
        return cls(d["values"])

    def is_data_item_valid(self, data_item: DataItem.DataItem) -> bool:
        return data_item.datum_dimension_count in self.values


class ComputationProcessorRequirementDatumCalibrations(ComputationProcessorRequirement):
    def __init__(self, requires_equal: bool) -> None:
        self.requires_equal = requires_equal

    @classmethod
    def from_dict(cls, d: PersistentDictType) -> ComputationProcessorRequirementDatumCalibrations:
        requires_equal = d.get("units") == "equal"
        return cls(requires_equal)

    def is_data_item_valid(self, data_item: DataItem.DataItem) -> bool:
        if self.requires_equal:
            xdata = data_item.xdata
            if not xdata or len(set([calibration.units for calibration in xdata.datum_dimensional_calibrations])) != 1:
                return False
        return True


class ComputationProcessorRequirementDimensionality(ComputationProcessorRequirement):
    def __init__(self, min_dimension: typing.Optional[int], max_dimension: typing.Optional[int]) -> None:
        self.min_dimension = min_dimension
        self.max_dimension = max_dimension

    @classmethod
    def from_dict(cls, d: PersistentDictType) -> ComputationProcessorRequirementDimensionality:
        min_dimension = d.get("min")
        max_dimension = d.get("max")
        return cls(min_dimension, max_dimension)

    def is_data_item_valid(self, data_item: DataItem.DataItem) -> bool:
        dimensionality = len(data_item.dimensional_shape)
        if self.min_dimension is not None and dimensionality < self.min_dimension:
            return False
        if self.max_dimension is not None and dimensionality > self.max_dimension:
            return False
        return True


class ComputationProcessorRequirementIsRGBType(ComputationProcessorRequirement):
    def is_data_item_valid(self, data_item: DataItem.DataItem) -> bool:
        return data_item.is_data_rgb_type


class ComputationProcessorRequirementIsSequence(ComputationProcessorRequirement):
    def is_data_item_valid(self, data_item: DataItem.DataItem) -> bool:
        return data_item.is_sequence


class ComputationProcessorRequirementIsNavigable(ComputationProcessorRequirement):
    def is_data_item_valid(self, data_item: DataItem.DataItem) -> bool:
        return data_item.is_sequence or data_item.is_collection


class ComputationProcessorRequirementBooleanOperator(enum.Enum):
    NOT = "not"
    AND = "and"
    OR = "or"


class ComputationProcessorRequirementBoolean(ComputationProcessorRequirement):
    def __init__(self, operator: ComputationProcessorRequirementBooleanOperator, operands: typing.Sequence[ComputationProcessorRequirement]) -> None:
        self.operator = operator
        self.operands = list(operands)

    @classmethod
    def from_dict(cls, d: PersistentDictType) -> ComputationProcessorRequirementBoolean:
        operator = ComputationProcessorRequirementBooleanOperator(d["operator"])
        operands = [create_computation_processor_requirement(operand) for operand in d["operands"]]
        return cls(operator, operands)

    def is_data_item_valid(self, data_item: DataItem.DataItem) -> bool:
        operator = self.operator
        for operand in self.operands:
            requirement_satisfied = operand.is_data_item_valid(data_item)
            if operator == ComputationProcessorRequirementBooleanOperator.NOT:
                return not requirement_satisfied
            if operator == ComputationProcessorRequirementBooleanOperator.AND and not requirement_satisfied:
                return False
            if operator == ComputationProcessorRequirementBooleanOperator.OR and requirement_satisfied:
                return True
        else:
            if operator == ComputationProcessorRequirementBooleanOperator.OR:
                return False
        return True


def create_computation_processor_requirement(d: PersistentDictType) -> ComputationProcessorRequirement:
    requirement_type = d.get("type", None)
    if requirement_type == "datum_rank":
        return ComputationProcessorRequirementDataRank.from_dict(d)
    if requirement_type == "datum_calibrations":
        return ComputationProcessorRequirementDatumCalibrations.from_dict(d)
    if requirement_type == "dimensionality":
        return ComputationProcessorRequirementDimensionality.from_dict(d)
    if requirement_type == "is_rgb_type":
        return ComputationProcessorRequirementIsRGBType()
    if requirement_type == "is_sequence":
        return ComputationProcessorRequirementIsSequence()
    if requirement_type == "is_navigable":
        return ComputationProcessorRequirementIsNavigable()
    if requirement_type == "bool":
        return ComputationProcessorRequirementBoolean.from_dict(d)
    raise ValueError(f"Unknown requirement type: {requirement_type}")


class ComputationProcsesorRegionTypeEnum(enum.Enum):
    POINT = "point"
    LINE = "line"
    RECTANGLE = "rectangle"
    ELLIPSE = "ellipse"
    SPOT = "spot"
    INTERVAL = "interval"
    CHANNEL = "channel"


class ComputationProcessorRegion:
    def __init__(self, region_type: ComputationProcsesorRegionTypeEnum, params: typing.Mapping[str, typing.Any], name: str) -> None:
        self.region_type = region_type
        self.params = dict(params)
        self.name = name

    @classmethod
    def from_dict(cls, d: PersistentDictType) -> ComputationProcessorRegion:
        region_type = ComputationProcsesorRegionTypeEnum(d["type"])
        params = d.get("params", dict())
        name = d["name"]
        return cls(region_type, params, name)


class ComputationProcessorSource:
    def __init__(self, name: str, label: str, data_type: typing.Optional[str], requirements: typing.Sequence[ComputationProcessorRequirement], regions: typing.Sequence[ComputationProcessorRegion], is_croppable: bool) -> None:
        self.name = name
        self.label = label
        self.data_type = data_type
        self.requirements = list(requirements)
        self.regions = list(regions)
        self.is_croppable = is_croppable

    @classmethod
    def from_dict(cls, d: PersistentDictType) -> ComputationProcessorSource:
        name = d["name"]
        label = d["label"]
        data_type = d.get("data_type", None)
        requirements = [create_computation_processor_requirement(requirement_d) for requirement_d in d.get("requirements", list())]
        regions = [ComputationProcessorRegion.from_dict(region_d) for region_d in d.get("regions", list())]
        is_croppable = d.get("croppable", False)
        return cls(name, label, data_type, requirements, regions, is_croppable)

    def needs_update_for_event(self, event_type: BoundDataEventType) -> bool:
        if self.data_type == 'xdata':
            if self.is_croppable:
                return event_type in (BoundDataEventType.UNSPECIFIED, BoundDataEventType.DATA, BoundDataEventType.CROP_REGION)
            else:
                return event_type in (BoundDataEventType.UNSPECIFIED, BoundDataEventType.DATA)
        return True


class ComputationProcessorParameter:
    def __init__(self, param_type: ComputationVariableType, name: str, label: typing.Optional[str], value: typing.Any, value_default: typing.Optional[typing.Any], value_min: typing.Optional[typing.Any], value_max: typing.Optional[typing.Any], control_type: typing.Optional[str]) -> None:
        self.param_type = param_type
        self.name = name
        self.label = label
        self.value = value
        self.value_default = value_default
        self.value_min = value_min
        self.value_max = value_max
        self.control_type = control_type

    @classmethod
    def from_dict(cls, d: PersistentDictType) -> ComputationProcessorParameter:
        param_type = _map_identifier_to_variable_type[d["type"]]
        name = d["name"]
        label = d.get("label", None)
        value = d["value"]
        value_default = d.get("value_default", None)
        value_min = d.get("value_min", None)
        value_max = d.get("value_max", None)
        control_type = d.get("control_type", None)
        return cls(param_type, name, label, value, value_default, value_min, value_max, control_type)


class ComputationProcessor:
    def __init__(self, expression: typing.Optional[str], title: typing.Optional[str], sources: typing.Sequence[ComputationProcessorSource], parameters: typing.Sequence[ComputationProcessorParameter], attributes: typing.Mapping[str, typing.Any], out_regions: typing.Sequence[ComputationProcessorRegion]) -> None:
        self.expression: typing.Optional[str] = expression
        self.title: typing.Optional[str] = title
        self.sources = list(sources)
        self.parameters = list(parameters)
        self.attributes = dict(attributes)
        self.out_regions = list(out_regions)

    @classmethod
    def from_dict(cls, d: PersistentDictType) -> ComputationProcessor:
        expression = d.get("expression", None)
        title = d.get("title", None)
        sources = [ComputationProcessorSource.from_dict(source_d) for source_d in d.get("sources", list())]
        parameters = [ComputationProcessorParameter.from_dict(parameter_d) for parameter_d in d.get("parameters", list())]
        attributes = d.get("attributes", dict())
        out_regions = [ComputationProcessorRegion.from_dict(region_d) for region_d in d.get("out_regions", list())]
        return cls(expression, title, sources, parameters, attributes, out_regions)

    def needs_update_for_event(self, input_key: str, event_type: BoundDataEventType) -> bool:
        for source in self.sources:
            if source.name == input_key:
                return source.needs_update_for_event(event_type)
        return True


class RegisteredComputationExecutor(ComputationExecutor):
    def __init__(self, computation: Computation, api: typing.Any) -> None:
        super().__init__(computation)
        processing_id = computation.processing_id
        api_computation = api._new_api_object(computation)
        api_computation.api = api
        compute_class = _computation_types.get(processing_id) if processing_id else None
        self.__computation_handler = compute_class(api_computation) if compute_class else None
        if not self.__computation_handler:
            self.error_text = "Missing computation (" + (processing_id or "unknown") + ")."

    def _execute(self, **kwargs: typing.Any) -> None:
        if self.__computation_handler:
            self.__computation_handler.execute(**kwargs)

    def _commit(self) -> None:
        if self.__computation_handler:
            self.__computation_handler.commit()


class ComputationActivity(Activity.Activity):
    def __init__(self, computation: Computation) -> None:
        super().__init__("computation", computation.label or computation.processing_id or str())
        self.computation = computation
        self.__state = "pending"

    @property
    def state(self) -> str:
        return self.__state

    @state.setter
    def state(self, value: str) -> None:
        self.__state = value
        self.notify_property_changed("state")
        self.notify_property_changed("displayed_title")

    @property
    def displayed_title(self) -> str:
        return self.title + " (" + self.state + ")"


# processors

_processors = dict[str, ComputationProcessor]()


# for computations

class ComputationHandlerLike(typing.Protocol):
    def execute(self, **kwargs: typing.Any) -> None: ...
    def commit(self) -> None: ...

_computation_types: typing.Dict[str, typing.Callable[[_APIComputation], ComputationHandlerLike]] = dict()

def register_computation_type(computation_type_id: str, compute_class: typing.Callable[[_APIComputation], ComputationHandlerLike]) -> None:
    _computation_types[computation_type_id] = compute_class


# for testing

def xdata_expression(expression: str) -> str:
    return "import numpy\nimport uuid\nfrom nion.data import xdata_1_0 as xd\ntarget.xdata = " + expression


def data_expression(expression: str) -> str:
    return "import numpy\nimport uuid\nfrom nion.data import xdata_1_0 as xd\ntarget.data = " + expression


def evaluate_data(computation: Computation) -> DataAndMetadata.DataAndMetadata:
    api = PlugInManager.api_broker_fn("~1.0", None)
    computation_executor = computation.evaluate(api)
    if computation_executor:
        computation_executor.commit()
        computation_executor.close()
        computation.error_text = computation_executor.error_text
    return typing.cast(DataAndMetadata.DataAndMetadata, computation_executor._target_xdata if computation_executor else None)
