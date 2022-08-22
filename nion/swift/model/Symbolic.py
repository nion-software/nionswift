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
import gettext
import threading
import time
import typing
import uuid

# local libraries
from nion.data import Core
from nion.data import DataAndMetadata
from nion.swift.model import Activity
from nion.swift.model import DataItem
from nion.swift.model import DataStructure
from nion.swift.model import DisplayItem
from nion.swift.model import Graphics
from nion.swift.model import Persistence
from nion.swift.model import PlugInManager
from nion.utils import Converter
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import Observable

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


def create_bound_item(container: Persistence.PersistentObject,
                      specifier: typing.Optional[Persistence.PersistentDictType],
                      secondary_specifier: typing.Optional[Persistence.PersistentDictType] = None,
                      property_name: typing.Optional[str] = None) -> typing.Optional[BoundItemBase]:
    bound_item: typing.Optional[BoundItemBase] = None
    if specifier and specifier.get("version") == 1:
        specifier_type = specifier["type"]
        if specifier_type == "data_source":
            bound_item = BoundDataSource(container, specifier, secondary_specifier)
        elif specifier_type == "data_item":
            bound_item = BoundDataItem(container, specifier)
        elif specifier_type == "xdata":
            bound_item = BoundData(container, specifier)
        elif specifier_type == "display_xdata":
            bound_item = BoundDisplayData(container, specifier, secondary_specifier)
        elif specifier_type == "cropped_xdata":
            bound_item = BoundCroppedData(container, specifier, secondary_specifier)
        elif specifier_type == "cropped_display_xdata":
            bound_item = BoundCroppedDisplayData(container, specifier, secondary_specifier)
        elif specifier_type == "filter_xdata":
            bound_item = BoundFilterData(container, specifier, secondary_specifier)
        elif specifier_type == "filtered_xdata":
            bound_item = BoundFilteredData(container, specifier, secondary_specifier)
        elif specifier_type == "structure":
            bound_item = BoundDataStructure(container, specifier, property_name)
        elif specifier_type == "graphic":
            bound_item = BoundGraphic(container, specifier, property_name)
    return bound_item


class ComputationOutput(Persistence.PersistentObject):
    """Tracks an output of a computation."""

    def __init__(self, name: typing.Optional[str] = None, specifier: typing.Optional[Persistence.PersistentDictType] = None,
                 specifiers: typing.Optional[typing.Sequence[Persistence.PersistentDictType]] = None,
                 label: typing.Optional[str] = None) -> None:  # defaults are None for factory
        super().__init__()
        self.define_type("output")
        self.define_property("name", name, changed=self.__property_changed, hidden=True)
        self.define_property("label", label if label else name, hidden=True, changed=self.__property_changed)
        self.define_property("specifier", specifier, hidden=True, changed=self.__property_changed)
        self.define_property("specifiers", specifiers, hidden=True, changed=self.__property_changed)
        self.__bound_item: typing.Optional[BoundItemBase] = None
        self.__bound_item_base_item_inserted_event_listener: typing.Optional[Event.EventListener] = None
        self.__bound_item_base_item_removed_event_listener: typing.Optional[Event.EventListener] = None

    def close(self) -> None:
        self.bound_item = None
        super().close()

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
    def _specifier(self) -> typing.Optional[Persistence.PersistentDictType]:
        return typing.cast(typing.Optional[Persistence.PersistentDictType], self._get_persistent_property_value("specifier"))

    @_specifier.setter
    def _specifier(self, value: typing.Optional[Persistence.PersistentDictType]) -> None:
        self._set_persistent_property_value("specifier", value)

    @property
    def _specifiers(self) -> typing.Optional[typing.Sequence[typing.Optional[Persistence.PersistentDictType]]]:
        return typing.cast(typing.Optional[typing.Sequence[Persistence.PersistentDictType]], self._get_persistent_property_value("specifiers"))

    @_specifiers.setter
    def _specifiers(self, value: typing.Optional[typing.Sequence[typing.Optional[Persistence.PersistentDictType]]]) -> None:
        self._set_persistent_property_value("specifiers", value)

    def __property_changed(self, name: str, value: typing.Any) -> None:
        self.notify_property_changed(name)
        if name in ("specifier", "specifiers"):
            if self.container:
                self.bind()

    def bind(self) -> None:
        if self._specifier:
            self.bound_item = create_bound_item(self, self._specifier)
        elif self._specifiers is not None:
            self.bound_item = BoundList([create_bound_item(self, object_specifier) for object_specifier in self._specifiers])
        else:
            self.bound_item = None

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
        if not self._specifier and not self._specifiers:
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
                 value_type: typing.Optional[str] = None, value: typing.Any = None, value_default: typing.Any = None,
                 value_min: typing.Any = None, value_max: typing.Any = None, control_type: typing.Optional[str] = None,
                 specifier: typing.Optional[Persistence.PersistentDictType] = None, label: typing.Optional[str] = None,
                 secondary_specifier: typing.Optional[Persistence.PersistentDictType] = None,
                 items: typing.Optional[typing.List[ComputationItem]] = None) -> None:  # defaults are None for factory
        super().__init__()
        self.define_type("variable")
        # contemplating changes here? remember that this is mainly a place to store a value and track changes
        # to the value. this is not a place to specify how the value is presented, even though there are some
        # existing fields (control_type) to do that that are leftovers from the original implementation.
        self.define_property("name", name, changed=self.__property_changed, hidden=True)
        self.define_property("label", label if label else name, changed=self.__property_changed, hidden=True)
        self.define_property("value_type", value_type, changed=self.__property_changed, hidden=True)
        self.define_property("value", value, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer, hidden=True)
        self.define_property("value_default", value_default, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer, hidden=True)
        self.define_property("value_min", value_min, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer, hidden=True)
        self.define_property("value_max", value_max, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer, hidden=True)
        self.define_property("specifier", specifier, changed=self.__property_changed, hidden=True)
        self.define_property("secondary_specifier", secondary_specifier, changed=self.__property_changed, hidden=True)
        self.define_property("property_name", property_name, changed=self.__property_changed, hidden=True)
        self.define_property("control_type", control_type, changed=self.__property_changed, hidden=True)
        item_specifiers = [DataStructure.get_object_specifier(item.item, item.type) if item and item.item else None for item in items] if items is not None else None
        self.define_property("object_specifiers", copy.deepcopy(item_specifiers) if item_specifiers is not None else None, changed=self.__property_changed, hidden=True)
        self.changed_event = Event.Event()
        self.variable_type_changed_event = Event.Event()
        self.needs_rebuild_event = Event.Event()  # an event to be fired when the UI needs a rebuild
        self.__bound_item: typing.Optional[BoundItemBase] = None
        self.__bound_item_changed_event_listener: typing.Optional[Event.EventListener] = None
        self.__bound_item_base_item_inserted_event_listener: typing.Optional[Event.EventListener] = None
        self.__bound_item_base_item_removed_event_listener: typing.Optional[Event.EventListener] = None

    def __repr__(self) -> str:
        return "{} ({} {} {} {} {})".format(super().__repr__(), self.name, self.label, self.value, self._specifier, self._secondary_specifier)

    def read_from_dict(self, properties: Persistence.PersistentDictType) -> None:
        # used for persistence
        # ensure that value_type is read first
        value_type_property = self._get_persistent_property("value_type")
        value_type_property.read_from_dict(properties)
        super().read_from_dict(properties)

    def write_to_dict(self) -> Persistence.PersistentDictType:
        # used for persistence. left here since read_from_dict is defined.
        return super().write_to_dict()

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
    def value_type(self) -> typing.Optional[str]:
        return typing.cast(typing.Optional[str], self._get_persistent_property_value("value_type"))

    @value_type.setter
    def value_type(self, value: typing.Optional[str]) -> None:
        self._set_persistent_property_value("value_type", value)

    @property
    def control_type(self) -> typing.Optional[str]:
        return typing.cast(typing.Optional[str], self._get_persistent_property_value("control_type"))

    @control_type.setter
    def control_type(self, value: typing.Optional[str]) -> None:
        self._set_persistent_property_value("control_type", value)

    @property
    def object_specifiers(self) -> typing.Optional[typing.Sequence[typing.Optional[Persistence.PersistentDictType]]]:
        return typing.cast(typing.Optional[typing.Sequence[typing.Optional[Persistence.PersistentDictType]]], self._get_persistent_property_value("object_specifiers"))

    @object_specifiers.setter
    def object_specifiers(self, value: typing.Optional[typing.Sequence[typing.Optional[Persistence.PersistentDictType]]]) -> None:
        self._set_persistent_property_value("object_specifiers", value)

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
    def _specifier(self) -> typing.Optional[Persistence.PersistentDictType]:
        return typing.cast(typing.Optional[Persistence.PersistentDictType], self._get_persistent_property_value("specifier"))

    @_specifier.setter
    def _specifier(self, value: typing.Optional[Persistence.PersistentDictType]) -> None:
        self._set_persistent_property_value("specifier", value)

    @property
    def _secondary_specifier(self) -> typing.Optional[Persistence.PersistentDictType]:
        return typing.cast(typing.Optional[Persistence.PersistentDictType], self._get_persistent_property_value("secondary_specifier"))

    @_secondary_specifier.setter
    def _secondary_specifier(self, value: typing.Optional[Persistence.PersistentDictType]) -> None:
        self._set_persistent_property_value("secondary_specifier", value)

    def bind(self) -> None:
        if self.object_specifiers is not None:
            self.bound_item = BoundList([create_bound_item(self, object_specifier) for object_specifier in self.object_specifiers])
        else:
            uuid_str = self._variable_specifier.get("uuid") if self._variable_specifier else None
            uuid_ = Converter.UuidToStringConverter().convert_back(uuid_str) if uuid_str else None
            if uuid_ == self.uuid:
                self.bound_item = self.bound_variable
            else:
                self.bound_item = create_bound_item(self, self._variable_specifier, self._secondary_specifier, self.property_name)

    def unbind(self) -> None:
        self.bound_item = None

    @property
    def _bound_items(self) -> typing.Sequence[typing.Optional[BoundItemBase]]:
        bound_item = self.bound_item
        assert isinstance(bound_item, BoundList)
        return bound_item.get_items()

    def _insert_specifier_in_list(self, index: int, specifier: Persistence.PersistentDictType) -> None:
        bound_item = create_bound_item(self, specifier)
        assert bound_item
        # self.changed_event.fire()  # implicit when setting object_specifiers
        object_specifiers = list(self.object_specifiers or list())
        object_specifiers.insert(index, copy.deepcopy(bound_item.specifier))
        self.object_specifiers = object_specifiers
        bound_list = self.bound_item
        assert isinstance(bound_list, BoundList)
        bound_list.item_inserted(index, bound_item)
        self.notify_insert_item("_bound_items", bound_item, index)

    def _remove_item_from_list(self, index: int) -> None:
        # self.changed_event.fire()  # implicit when setting object_specifiers
        object_specifiers = list(self.object_specifiers or list())
        object_specifiers.pop(index)
        self.object_specifiers = object_specifiers
        bound_list = self.bound_item
        assert isinstance(bound_list, BoundList)
        value = bound_list.get_items()[index]
        bound_list.item_removed(index)
        self.notify_remove_item("_bound_items", value, index)

    def save_properties(self) -> typing.Tuple[typing.Any, typing.Optional[Persistence.PersistentDictType], typing.Optional[Persistence.PersistentDictType]]:
        # used for undo
        return self.value, self._specifier, self._secondary_specifier

    def restore_properties(self, properties: typing.Tuple[typing.Any, typing.Optional[Persistence.PersistentDictType], typing.Optional[Persistence.PersistentDictType]]) -> None:
        # used for undo
        self.value = properties[0]
        self._specifier = properties[1]
        self._secondary_specifier = properties[2]

    def __value_reader(self, persistent_property: Persistence.PersistentProperty, properties: Persistence.PersistentDictType) -> typing.Any:
        value_type = self.value_type
        raw_value = properties.get(persistent_property.key)
        if raw_value is not None:
            if value_type == "boolean":
                return bool(raw_value)
            elif value_type == "integral":
                return int(raw_value)
            elif value_type == "real":
                return float(raw_value)
            elif value_type == "complex":
                return complex(*raw_value)
            elif value_type == "string":
                return str(raw_value)
        return None

    def __value_writer(self, persistent_property: Persistence.PersistentProperty, properties: Persistence.PersistentDictType, value: typing.Any) -> None:
        value_type = self.value_type
        if value is not None:
            if value_type == "boolean":
                properties[persistent_property.key] = bool(value)
            if value_type == "integral":
                properties[persistent_property.key] = int(value)
            if value_type == "real":
                properties[persistent_property.key] = float(value)
            if value_type == "complex":
                properties[persistent_property.key] = complex(value).real, complex(value).imag
            if value_type == "string":
                properties[persistent_property.key] = str(value)

    @property
    def _variable_specifier(self) -> typing.Optional[Persistence.PersistentDictType]:
        """Return the variable specifier for this variable.

        The specifier can be used to lookup the value of this variable in a computation context.
        """
        if self.value_type is not None:
            return {"type": "variable", "version": 1, "uuid": str(self.uuid), "x-name": self.name, "x-value": self.value}
        else:
            return self._specifier

    @property
    def specified_object(self) -> typing.Optional[Persistence.PersistentObject]:
        bound_item = self.__bound_item
        return bound_item.value if bound_item else None

    @specified_object.setter
    def specified_object(self, value: typing.Optional[Persistence.PersistentObject]) -> None:
        if value:
            self._specifier = DataStructure.get_object_specifier(value)
        else:
            self._specifier = {"type": "data_source", "version": 1, "uuid": str(uuid.uuid4())}

    @property
    def secondary_specified_object(self) -> typing.Optional[Persistence.PersistentObject]:
        return typing.cast(typing.Optional[Persistence.PersistentObject], getattr(self.__bound_item, "_graphic", None))

    @secondary_specified_object.setter
    def secondary_specified_object(self, value: typing.Optional[Persistence.PersistentObject]) -> None:
        if value:
            self._secondary_specifier = DataStructure.get_object_specifier(value)
        else:
            self._secondary_specifier = None

    @property
    def bound_variable(self) -> BoundItemBase:
        """Return an object with a value property and a changed_event.

        The value property returns the value of the variable. The changed_event is fired
        whenever the value changes.
        """

        class BoundVariable(BoundItemBase):
            def __init__(self, variable: ComputationVariable) -> None:
                super().__init__(dict())
                self.valid = True
                self.__variable = variable

                def property_changed(key: str) -> None:
                    if key == "value":
                        self.changed_event.fire()

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
            self.__bound_item_changed_event_listener = self.__bound_item.changed_event.listen(self.changed_event.fire)
            self.__bound_item_base_item_inserted_event_listener = self.__bound_item.item_inserted_event.listen(self.item_inserted_event.fire)
            self.__bound_item_base_item_removed_event_listener = self.__bound_item.item_removed_event.listen(self.item_removed_event.fire)
            for index, base_item in enumerate(self.__bound_item.base_items):
                self.notify_insert_item("base_items", base_item, index)
        self.notify_property_changed("bound_item")

    @property
    def is_resolved(self) -> bool:
        if not self._specifier:
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
        # rebind first, so that property changed listeners get the right value
        if name in ("specifier", "secondary_specifier"):
            if self.container:
                self.bound_item = create_bound_item(self.container, self._specifier, self._secondary_specifier, self.property_name)
        # send the primary property changed event
        self.notify_property_changed(name)
        # now send out dependent property changed events
        if name in ["name", "label"]:
            self.notify_property_changed("display_label")
        if name in ("specifier"):
            self.notify_property_changed("specified_object")
        if name in ("secondary_specifier"):
            self.notify_property_changed("secondary_specified_object")
        # send out the changed event
        self.changed_event.fire()
        # finally send out the rebuild event for the inspectors
        if name in ["value_type", "value_min", "value_max", "control_type"]:
            self.needs_rebuild_event.fire()

    def notify_property_changed(self, key: str) -> None:
        # whenever a property changed event is fired, also fire the changed_event
        # is there a test for this? not that I can find.
        super().notify_property_changed(key)
        if key not in ("bound_item",):
            self.changed_event.fire()

    def control_type_default(self, value_type: str) -> typing.Optional[str]:
        mapping = {"boolean": "checkbox", "integral": "slider", "real": "field", "complex": "field", "string": "field"}
        return mapping.get(value_type, None)

    data_item_types = ("data_item", "data", "display_data", "data_source")  # used for backward compatibility

    @property
    def variable_type(self) -> typing.Optional[str]:
        if self.value_type is not None:
            return self.value_type
        elif self._specifier is not None:
            specifier_type = self._specifier.get("type")
            specifier_property = self._specifier.get("property")
            return specifier_property or specifier_type
        return None

    @variable_type.setter
    def variable_type(self, value_type: typing.Optional[str]) -> None:
        if value_type != self.variable_type:
            if value_type in ("boolean", "integral", "real", "complex", "string"):
                self._specifier = None
                self._secondary_specifier = None
                self.value_type = value_type
                self.control_type = self.control_type_default(value_type)
                if value_type == "boolean":
                    self.value_default = True
                elif value_type == "integral":
                    self.value_default = 0
                elif value_type == "real":
                    self.value_default = 0.0
                elif value_type == "complex":
                    self.value_default = 0 + 0j
                else:
                    self.value_default = None
                self.value_min = None
                self.value_max = None
            elif value_type in ComputationVariable.data_item_types:
                self.value_type = None
                self.control_type = None
                self.value_default = None
                self.value_min = None
                self.value_max = None
                specifier: Persistence.PersistentDictType = self._specifier if self._specifier else {"version": 1}
                if not specifier.get("type") in ComputationVariable.data_item_types:
                    specifier.pop("uuid", None)
                specifier["type"] = "data_source"
                if value_type in ("data", "display_data"):
                    specifier["property"] = value_type
                else:
                    specifier.pop("property", None)
                self._specifier = specifier
                self._secondary_specifier = self._secondary_specifier or {"version": 1}
            elif value_type in ("graphic",):
                self.value_type = None
                self.control_type = None
                self.value_default = None
                self.value_min = None
                self.value_max = None
                specifier = self._specifier or {"version": 1}
                specifier["type"] = value_type
                specifier.pop("uuid", None)
                specifier.pop("property", None)
                self._specifier = specifier
                self._secondary_specifier = None
            self.variable_type_changed_event.fire()

    @property
    def _specifier_uuid_str(self) -> typing.Optional[str]:
        return self._specifier.get("uuid") if self._specifier else None

    @_specifier_uuid_str.setter
    def _specifier_uuid_str(self, value: typing.Optional[str]) -> None:
        converter = Converter.UuidToStringConverter()
        value = converter.convert(converter.convert_back(value))
        if self._specifier_uuid_str != value and self._specifier:
            specifier = self._specifier
            if value:
                specifier["uuid"] = value
            else:
                specifier.pop("uuid", None)
            self._specifier = specifier

    @property
    def _secondary_specifier_uuid_str(self) -> typing.Optional[str]:
        return self._secondary_specifier.get("uuid") if self._secondary_specifier else None

    @_secondary_specifier_uuid_str.setter
    def _secondary_specifier_uuid_str(self, value: typing.Optional[str]) -> None:
        converter = Converter.UuidToStringConverter()
        value = converter.convert(converter.convert_back(value))
        if self._secondary_specifier_uuid_str != value and self._secondary_specifier:
            secondary_specifier = self._secondary_specifier
            if value:
                secondary_specifier["uuid"] = value
            else:
                secondary_specifier.pop("uuid", None)
            self._secondary_specifier = secondary_specifier

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


class BoundItemBase(Observable.Observable):
    # note: base objects are different from items temporarily while the notification machinery is put in place

    def __init__(self, specifier: Persistence.PersistentDictType) -> None:
        super().__init__()
        self.specifier = specifier
        self.changed_event = Event.Event()
        self.valid = False
        self.__base_items: typing.List[Persistence.PersistentObject] = list()

    def close(self) -> None:
        pass

    @property
    def value(self) -> typing.Any:
        return None

    @property
    def base_items(self) -> typing.List[Persistence.PersistentObject]:
        return self.__base_items

    def _update_base_items(self, base_items: typing.List[Persistence.PersistentObject]) -> None:
        update_diff_notify(self, "base_items", self.__base_items, base_items)


class BoundData(BoundItemBase):

    def __init__(self, container: Persistence.PersistentObject, specifier: Persistence.PersistentDictType) -> None:
        super().__init__(specifier)

        self.__item_reference = container.create_item_reference(item_specifier=Persistence.read_persistent_specifier(specifier))
        self.__data_changed_event_listener: typing.Optional[Event.EventListener] = None

        def maintain_data_source() -> None:
            if self.__data_changed_event_listener:
                self.__data_changed_event_listener.close()
                self.__data_changed_event_listener = None
            item = self._item
            if item:
                self.__data_changed_event_listener = item.data_changed_event.listen(self.changed_event.fire)
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

    def __init__(self, container: Persistence.PersistentObject, specifier: Persistence.PersistentDictType, secondary_specifier: typing.Optional[Persistence.PersistentDictType]) -> None:
        super().__init__(specifier)

        self.__item_reference = container.create_item_reference(item_specifier=Persistence.read_persistent_specifier(specifier))
        self.__graphic_reference = container.create_item_reference(item_specifier=Persistence.read_persistent_specifier(secondary_specifier))
        self.__display_values_changed_event_listener = None

        def maintain_data_source() -> None:
            if self.__display_values_changed_event_listener:
                self.__display_values_changed_event_listener.close()
                self.__display_values_changed_event_listener = None
            display_data_channel = self._display_data_channel
            if display_data_channel:
                self.__display_values_changed_event_listener = display_data_channel.add_calculated_display_values_listener(self.changed_event.fire, send=False)
            self.valid = self.__display_values_changed_event_listener is not None
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
        if self.__display_values_changed_event_listener:
            self.__display_values_changed_event_listener.close()
            self.__display_values_changed_event_listener = None
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
    def _graphic(self) -> typing.Optional[Graphics.Graphic]:
        return typing.cast(typing.Optional[Graphics.Graphic], self.__graphic_reference.item)


class BoundDataSource(BoundItemBase):

    def __init__(self, container: Persistence.PersistentObject, specifier: Persistence.PersistentDictType, secondary_specifier: typing.Optional[Persistence.PersistentDictType]) -> None:
        super().__init__(specifier)

        self.__item_reference = container.create_item_reference(item_specifier=Persistence.read_persistent_specifier(specifier))
        self.__graphic_reference = container.create_item_reference(item_specifier=Persistence.read_persistent_specifier(secondary_specifier))
        self.__data_source: typing.Optional[DataItem.DataSource] = None

        def maintain_data_source() -> None:
            if self.__data_source:
                self.__data_source.close()
                self.__data_source = None
            display_data_channel = self._display_data_channel
            if display_data_channel and display_data_channel.data_item:
                graphic = self._graphic
                self.__data_source = DataItem.MonitoredDataSource(display_data_channel, graphic, self.changed_event)
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
    def value(self) -> typing.Optional[DataItem.DataSource]:
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

    def __init__(self, container: Persistence.PersistentObject, specifier: Persistence.PersistentDictType) -> None:
        super().__init__(specifier)

        self.__item_reference = container.create_item_reference(item_specifier=Persistence.read_persistent_specifier(specifier))
        self.__data_item_changed_event_listener: typing.Optional[Event.EventListener] = None

        def item_registered(item: Persistence.PersistentObject) -> None:
            assert isinstance(item, DataItem.DataItem)
            self.__data_item_changed_event_listener = item.data_item_changed_event.listen(self.changed_event.fire)
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
        display_values = self._display_data_channel.get_calculated_display_values() if self._display_data_channel else None
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
        display_values = self._display_data_channel.get_calculated_display_values() if self._display_data_channel else None
        xdata = display_values.display_data_and_metadata if display_values else None
        graphic = self._graphic
        if xdata and graphic:
            if isinstance(graphic, Graphics.RectangleTypeGraphic):
                return Core.function_crop(xdata, graphic.bounds.as_tuple())
            if isinstance(graphic, Graphics.IntervalGraphic):
                return Core.function_crop_interval(xdata, graphic.interval)
        return xdata


class BoundFilterLikeData(BoundItemBase):

    def __init__(self, container: Persistence.PersistentObject, specifier: Persistence.PersistentDictType, secondary_specifier: typing.Optional[Persistence.PersistentDictType]) -> None:
        super().__init__(specifier)

        self.__item_reference = container.create_item_reference(item_specifier=Persistence.read_persistent_specifier(specifier))
        self.__display_values_changed_event_listener: typing.Optional[Event.EventListener] = None
        self.__display_item_item_inserted_event_listener: typing.Optional[Event.EventListener] = None
        self.__display_item_item_removed_event_listener: typing.Optional[Event.EventListener] = None

        def maintain_data_source() -> None:
            if self.__display_values_changed_event_listener:
                self.__display_values_changed_event_listener.close()
                self.__display_values_changed_event_listener = None
            if self.__display_item_item_inserted_event_listener:
                self.__display_item_item_inserted_event_listener.close()
                self.__display_item_item_inserted_event_listener = None
            if self.__display_item_item_removed_event_listener:
                self.__display_item_item_removed_event_listener.close()
                self.__display_item_item_removed_event_listener = None
            display_data_channel = self._display_data_channel
            if display_data_channel:
                self.__display_values_changed_event_listener = display_data_channel.add_calculated_display_values_listener(self.changed_event.fire, send=False)
                display_item = typing.cast(typing.Optional[DisplayItem.DisplayItem], display_data_channel.container)
                if display_item:
                    def maintain(name: str, value: typing.Any, index: int) -> None:
                        if name == "graphics":
                            maintain_data_source()

                    self.__display_item_item_inserted_event_listener = display_item.item_inserted_event.listen(maintain)
                    self.__display_item_item_removed_event_listener = display_item.item_removed_event.listen(maintain)
            self.valid = self.__display_values_changed_event_listener is not None
            self._update_base_items(self._get_base_items())

        def item_registered(item: Persistence.PersistentObject) -> None:
            maintain_data_source()

        def item_unregistered(item: Persistence.PersistentObject) -> None:
            maintain_data_source()

        self.__item_reference.on_item_registered = item_registered
        self.__item_reference.on_item_unregistered = item_unregistered

        maintain_data_source()

    def close(self) -> None:
        if self.__display_values_changed_event_listener:
            self.__display_values_changed_event_listener.close()
            self.__display_values_changed_event_listener = None
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


class BoundFilterData(BoundFilterLikeData):

    @property
    def value(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        display_data_channel = self._display_data_channel
        if display_data_channel:
            display_item = display_data_channel.display_item
            # no display item is a special case for cascade removing graphics from computations. ugh.
            # see test_new_computation_becomes_unresolved_when_xdata_input_is_removed_from_document.
            if display_item:
                display_values = display_data_channel.get_calculated_display_values()
                if display_values:
                    display_data_and_metadata = display_values.display_data_and_metadata
                    if display_data_and_metadata:
                        shape = display_data_and_metadata.data_shape
                        calibrated_origin = Geometry.FloatPoint(y=display_item.datum_calibrations[0].convert_from_calibrated_value(0.0),
                                                                x=display_item.datum_calibrations[1].convert_from_calibrated_value(0.0))
                        mask = DataItem.create_mask_data(display_item.graphics, shape, calibrated_origin)
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
                    mask = DataItem.create_mask_data(display_item.graphics, shape, calibrated_origin)
                    return Core.function_fourier_mask(xdata, DataAndMetadata.DataAndMetadata.from_data(mask))
                return xdata
        return None


class BoundDataStructure(BoundItemBase):

    def __init__(self, container: Persistence.PersistentObject, specifier: Persistence.PersistentDictType, property_name: typing.Optional[str]) -> None:
        super().__init__(specifier)

        self.__property_name = property_name

        self.__item_reference = container.create_item_reference(item_specifier=Persistence.read_persistent_specifier(specifier))
        self.__changed_listener: typing.Optional[Event.EventListener] = None
        self.__property_changed_listener: typing.Optional[Event.EventListener] = None

        def data_structure_changed(property_name: str) -> None:
            self.changed_event.fire()

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

    def __init__(self, container: Persistence.PersistentObject, specifier: Persistence.PersistentDictType, property_name: typing.Optional[str]) -> None:
        super().__init__(specifier)

        self.__property_name = property_name

        self.__item_reference = container.create_item_reference(item_specifier=Persistence.read_persistent_specifier(specifier))
        self.__changed_listener: typing.Optional[Event.EventListener] = None

        def property_changed(property_name: str) -> None:
            # temporary hack to improve performance of line profile. long term solution will be to
            # have the computation decide what is a valid reason for recomputing.
            # see the test test_adjusting_interval_on_line_profile_does_not_trigger_recompute
            if not property_name in ("interval_descriptors",):
                self.changed_event.fire()

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
    computaton_items: typing.List[ComputationItem] = list()
    for item in items:
        if isinstance(item, ComputationItem):
            computaton_items.append(item)
        else:
            computaton_items.append(make_item(item, type=type))
    return ComputationItem(items=computaton_items)


class BoundList(BoundItemBase):

    def __init__(self, bound_items: typing.Sequence[typing.Optional[BoundItemBase]]) -> None:
        super().__init__(dict())
        self.__bound_items: typing.List[typing.Optional[BoundItemBase]] = list()
        self.changed_event = Event.Event()
        self.child_removed_event = Event.Event()
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

        self.__changed_listeners.insert(index, bound_item.changed_event.listen(self.changed_event.fire) if bound_item else None)
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
            if variable.object_specifiers is not None:
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

        def needs_update() -> None:
            self.needs_update = True
            self.computation_mutated_event.fire()

        self.__variable_changed_event_listeners.insert(before_index, variable.changed_event.listen(needs_update))

        def handle_variable_item_inserted(name: str, value: typing.Any, index: int) -> None:
            if name == "base_items":
                update_diff_notify(self, "input_items", self.__input_items, self.__get_input_items())
                update_diff_notify(self, "direct_input_items", self.__direct_input_items, self.__get_direct_input_items())
                needs_update()

        def handle_variable_item_removed(name: str, value: typing.Any, index: int) -> None:
            if name == "base_items":
                update_diff_notify(self, "input_items", self.__input_items, self.__get_input_items())
                update_diff_notify(self, "direct_input_items", self.__direct_input_items, self.__get_direct_input_items())
                needs_update()

        self.__variable_base_item_inserted_event_listeners.insert(before_index, variable.item_inserted_event.listen(handle_variable_item_inserted))
        self.__variable_base_item_removed_event_listeners.insert(before_index, variable.item_removed_event.listen(handle_variable_item_removed))

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

    def create_variable(self, name: typing.Optional[str] = None, value_type: typing.Optional[str] = None,
                        value: typing.Any = None, value_default: typing.Any = None, value_min: typing.Any = None,
                        value_max: typing.Any = None, control_type: typing.Optional[str] = None,
                        specified_item: typing.Optional[Persistence.PersistentObject] = None,
                        label: typing.Optional[str] = None) -> ComputationVariable:
        specifier = DataStructure.get_object_specifier(specified_item)
        variable = ComputationVariable(name, value_type=value_type, value=value, value_default=value_default,
                                       value_min=value_min, value_max=value_max, control_type=control_type,
                                       specifier=specifier, label=label)
        self.add_variable(variable)
        return variable

    def create_input_item(self, name: str, input_item: ComputationItem, *, property_name: typing.Optional[str] = None,
                          label: typing.Optional[str] = None, _item_specifier: typing.Optional[Persistence.PersistentDictType] = None) -> ComputationVariable:
        # Note: _item_specifier is only for testing
        if input_item.items is not None:
            variable = ComputationVariable(name, items=input_item.items, label=label)
            self.add_variable(variable)
            return variable
        else:
            specifier = _item_specifier or DataStructure.get_object_specifier(input_item.item, input_item.type)
            secondary_specifier = DataStructure.get_object_specifier(input_item.secondary_item) if input_item.secondary_item else None
            variable = ComputationVariable(name, specifier=specifier, secondary_specifier=secondary_specifier, property_name=property_name, label=label)
            self.add_variable(variable)
            return variable

    def create_output_item(self, name: str, output_item: typing.Optional[ComputationItem] = None, *,
                           label: typing.Optional[str] = None,
                           _item_specifier: typing.Optional[Persistence.PersistentDictType] = None) -> typing.Optional[ComputationOutput]:
        # Note: _item_specifier is only for testing
        if output_item and output_item.items is not None:
            specifiers = [DataStructure.get_object_specifier(item.item) for item in output_item.items]
            result = ComputationOutput(name, specifiers=specifiers, label=label)  # type: ignore  # mypy bug with Union/None
            self.append_item("results", result)
            self.computation_mutated_event.fire()
            return result
        elif output_item:
            assert not output_item.type
            assert not output_item.secondary_item
            specifier = _item_specifier or DataStructure.get_object_specifier(output_item.item)
            result = ComputationOutput(name, specifier=specifier, label=label)  # type: ignore  # mypy bug with Union/None
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
        specifier = DataStructure.get_object_specifier(input_item.item, input_item.type)
        if variable and specifier is not None:
            variable._insert_specifier_in_list(index, specifier)

    def list_item_removed(self, object: typing.Any) -> typing.Optional[typing.Tuple[int, int, typing.Optional[Persistence.PersistentDictType]]]:
        # when an item is removed from the library, this method is called for each computation.
        # if the item being removed matches a variable item, mark the computation as needing an update.
        # if the item is contained in a list variable, create the undelete entries and return them.
        # undelete_entries = list()
        for variable in self.variables:
            # check if the bound item matches the object. mark for update if so.
            # TODO: really needed?
            if variable.bound_item and variable.bound_item.value == object:
                self.needs_update = True
            # check if the bound item is a list and item in list matches the object. if so, create
            # an undelete entry for the variable. the undelete entry describes how to reconstitute
            # the list item.
            if variable.object_specifiers is not None:
                for index, (object_specifier, bound_item) in enumerate(zip(variable.object_specifiers, variable._bound_items)):
                    base_items = bound_item.base_items if bound_item else list()
                    if object in base_items:
                        variables_index = self.variables.index(variable)
                        variable._remove_item_from_list(index)
                        return (index, variables_index, copy.deepcopy(object_specifier))
        return None

    data_source_types = ("data_source", "data_item", "xdata", "display_xdata", "cropped_xdata", "cropped_display_xdata", "filter_xdata", "filtered_xdata")

    @property
    def expression(self) -> typing.Optional[str]:
        return self.original_expression

    @expression.setter
    def expression(self, value: typing.Optional[str]) -> None:
        if value != self.original_expression:
            self.original_expression = value
            self.processing_id = None
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

    def undelete_variable_item(self, name: str, index: int, specifier: Persistence.PersistentDictType) -> None:
        variable = self._get_variable(name)
        if variable:
            variable._insert_specifier_in_list(index, specifier)

    def get_preliminary_input_items(self) -> typing.Set[Persistence.PersistentObject]:
        input_items: typing.Set[Persistence.PersistentObject] = set()
        container = self if self.persistent_object_context else self.pending_project or self
        for variable in self.variables:
            if variable.object_specifiers is not None:
                for object_specifier in variable.object_specifiers:
                    bound_item = create_bound_item(container, object_specifier)
                    if bound_item:
                        with contextlib.closing(bound_item):
                            input_items.update(set(bound_item.base_items))
            else:
                bound_item = create_bound_item(container, variable._variable_specifier, variable._secondary_specifier, variable.property_name)
                if bound_item:
                    with contextlib.closing(bound_item):
                        input_items.update(set(bound_item.base_items))
        return input_items

    def get_preliminary_output_items(self) -> typing.Set[Persistence.PersistentObject]:
        output_items: typing.Set[Persistence.PersistentObject] = set()
        container = self if self.persistent_object_context else self.pending_project or self
        for result in self.results:
            if result._specifier:
                bound_item = create_bound_item(container, result._specifier)
                if bound_item:
                    with contextlib.closing(bound_item):
                        output_items.update(set(bound_item.base_items))
            elif result._specifiers is not None:
                for specifier in result._specifiers:
                    bound_item = create_bound_item(container, specifier)
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
            variable._specifier = DataStructure.get_object_specifier(input_item.item)

    def set_output_item(self, name:str, output_item: typing.Optional[ComputationItem]) -> None:
        result = self._get_output(name)
        if result:
            if output_item and output_item.items is not None:
                result._specifiers = [DataStructure.get_object_specifier(o.item) for o in output_item.items]
            else:
                if output_item:
                    assert output_item.item
                    assert output_item.type is None
                    assert output_item.secondary_item is None
                result._specifier = DataStructure.get_object_specifier(output_item.item) if output_item else None

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
        return variable.bound_variable.value if variable and variable.bound_variable else None

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

    def update_script(self, processing_descriptions: typing.Mapping[str, Persistence.PersistentDictType]) -> None:
        processing_id = self.processing_id
        processing_description = processing_descriptions.get(processing_id) if processing_id else None
        if processing_description:
            expression = processing_description.get("expression")
            if expression:
                src_names = list()
                source_dicts = processing_description["sources"]
                for i, source_dict in enumerate(source_dicts):
                    src_names.append(source_dict["name"])
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
        self.__computation = computation
        self.error_text: typing.Optional[str] = None
        self.__last_execution_time: float = 0.0
        self.__aborted = False
        self.__activity_lock = threading.RLock()
        self.__activity: typing.Optional[ComputationActivity] = ComputationActivity(computation)
        self.__activity.state = "computing"
        Activity.append_activity(self.__activity)

    def close(self) -> None:
        if self.__activity:
            Activity.activity_finished(self.__activity)
            self.__activity = None

    @property
    def computation(self) -> Computation:
        return self.__computation

    def _execute(self, **kwargs: typing.Any) -> None: raise NotImplementedError()

    def _commit(self) -> None: raise NotImplementedError()

    def execute(self, **kwargs: typing.Any) -> None:
        try:
            start_time = time.perf_counter()
            self._execute(**kwargs)
            self.__last_execution_time = time.perf_counter() - start_time
        except Exception as e:
            # import sys, traceback
            # traceback.print_exc()
            # traceback.format_exception(*sys.exc_info())
            self.__last_execution_time = 0.0
            self.error_text = str(e) or "Unable to evaluate script."  # a stack trace would be too much information right now

    def commit(self) -> None:
        if not self.error_text and not self.__aborted:
            try:
                self._commit()
            finally:
                if self.__activity:
                    Activity.activity_finished(self.__activity)
                    self.__activity = None
        if self.__computation.error_text != self.error_text:
            self.__computation.error_text = self.error_text

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
            self.data_modified = DataItem.DataItem.utcnow()

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
            # DataItem.utcnow() / Schema.utcnow().
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
