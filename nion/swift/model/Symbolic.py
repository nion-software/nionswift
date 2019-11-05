"""
    Provide symbolic math services.

    The goal is to provide a module (namespace) where users can be provided with variables representing
    data items (directly or indirectly via reference to workspace panels).

    DataNodes represent data items, operations, numpy arrays, and constants.
"""

# standard libraries
import ast
import contextlib
import copy
import functools
import threading
import time
import typing
import uuid
import weakref

# third party libraries
import numpy

# local libraries
from nion.data import Core
from nion.data import DataAndMetadata
from nion.swift.model import Changes
from nion.swift.model import DataItem
from nion.swift.model import DataStructure
from nion.swift.model import Graphics
from nion.utils import Converter
from nion.utils import Event
from nion.utils import ListModel
from nion.utils import Observable
from nion.utils import Persistence

if typing.TYPE_CHECKING:
    from nion.swift.model import Project


class ComputationVariableType:
    """Defines a type of a computation variable beyond the built-in types."""
    def __init__(self, type_id: str, label: str, object_type):
        self.type_id = type_id
        self.label = label
        self.object_type = object_type
        self.__objects = dict()  # type: typing.Dict[uuid.UUID, typing.Any]

    def get_object_by_uuid(self, object_uuid: uuid.UUID):
        return self.__objects.get(object_uuid)

    def register_object(self, object):
        assert object.uuid not in self.__objects
        self.__objects[object.uuid] = object

    def unregister_object(self, object):
        assert object.uuid in self.__objects
        del self.__objects[object.uuid]


class ComputationOutput(Observable.Observable, Persistence.PersistentObject):
    """Tracks an output of a computation."""

    def __init__(self, name: str=None, specifier: dict=None, specifiers: typing.Sequence[dict]=None, label: str=None):  # defaults are None for factory
        super().__init__()
        self.define_type("output")
        self.define_property("name", name, changed=self.__property_changed)
        self.define_property("label", label if label else name, changed=self.__property_changed)
        self.define_property("specifier", specifier, changed=self.__property_changed)
        self.define_property("specifiers", specifiers, changed=self.__property_changed)
        self.needs_rebind_event = Event.Event()  # an event to be fired when the computation needs to rebind
        self.bound_item = None
        self.__needs_rebind_event_listeners = list()

    def close(self):
        # TODO: this is not called
        for needs_rebind_event_listener in self.__needs_rebind_event_listeners:
            needs_rebind_event_listener.close()
        self.__needs_rebind_event_listeners = None

    def __property_changed(self, name, value):
        self.notify_property_changed(name)
        if name in ("specifier", "specifiers"):
            self.needs_rebind_event.fire()

    def __unbind(self):
        # self.specifier = None
        self.bound_item = None

    def bind(self, resolve_object_specifier_fn):
        if self.specifier:
            self.bound_item = resolve_object_specifier_fn(self.specifier)
            if self.bound_item:
                self.__needs_rebind_event_listeners.append(self.bound_item.needs_rebind_event.listen(self.__unbind))
        elif self.specifiers is not None:
            bound_items = [resolve_object_specifier_fn(specifier) for specifier in self.specifiers]
            bound_items = [bound_item for bound_item in bound_items if bound_item is not None]
            for bound_item in bound_items:
                self.__needs_rebind_event_listeners.append(bound_item.needs_rebind_event.listen(self.__unbind))
            self.bound_item = bound_items
        else:
            self.bound_item = None

    @property
    def output_items(self) -> typing.Set:
        item = self.bound_item
        if isinstance(item, list):
            return {list_item.value for list_item in item}
        elif item:
            return {item.value}
        return set()


class ComputationVariable(Observable.Observable, Persistence.PersistentObject):
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
    def __init__(self, name: str=None, *, property_name: str=None, value_type: str=None, value=None, value_default=None, value_min=None, value_max=None, control_type: str=None, specifier: dict=None, label: str=None, secondary_specifier: dict=None, items: typing.List["ComputationItem"]=None):  # defaults are None for factory
        super().__init__()
        self.define_type("variable")
        self.define_property("name", name, changed=self.__property_changed)
        self.define_property("label", label if label else name, changed=self.__property_changed)
        self.define_property("value_type", value_type, changed=self.__property_changed)
        self.define_property("value", value, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer)
        self.define_property("value_default", value_default, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer)
        self.define_property("value_min", value_min, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer)
        self.define_property("value_max", value_max, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer)
        self.define_property("specifier", specifier, changed=self.__property_changed)
        self.define_property("secondary_specifier", secondary_specifier, changed=self.__property_changed)
        self.define_property("property_name", property_name, changed=self.__property_changed)
        self.define_property("control_type", control_type, changed=self.__property_changed)
        item_specifiers = [DataStructure.get_object_specifier(item.item, item.type) if item else None for item in items] if items is not None else None
        self.define_property("object_specifiers", copy.deepcopy(item_specifiers) if item_specifiers is not None else None, changed=self.__property_changed)
        self.changed_event = Event.Event()
        self.variable_type_changed_event = Event.Event()
        self.needs_rebind_event = Event.Event()  # an event to be fired when the computation needs to rebind
        self.needs_rebuild_event = Event.Event()  # an event to be fired when the UI needs a rebuild
        self.__bound_items_model = None
        self.__bound_items_model_item_inserted_event_listener = None
        self.__bound_items_model_item_removed_event_listener = None
        self.__bound_item = None
        self.__bound_item_changed_event_listener = None
        self.__bound_item_removed_event_listener = None
        self.__bound_item_child_removed_event_listener = None

    def close(self):
        # TODO: this is not called
        if self.__bound_items_model_item_inserted_event_listener:
            self.__bound_items_model_item_inserted_event_listener.close()
            self.__bound_items_model_item_inserted_event_listener = None
        if self.__bound_items_model_item_removed_event_listener:
            self.__bound_items_model_item_removed_event_listener.close()
            self.__bound_items_model_item_removed_event_listener = None

    def __repr__(self):
        return "{} ({} {} {} {} {})".format(super().__repr__(), self.name, self.label, self.value, self.specifier, self.secondary_specifier)

    def read_from_dict(self, properties: dict) -> None:
        # used for persistence
        # ensure that value_type is read first
        value_type_property = self._get_persistent_property("value_type")
        value_type_property.read_from_dict(properties)
        super().read_from_dict(properties)

    def write_to_dict(self) -> dict:
        # used for persistence. left here since read_from_dict is defined.
        return super().write_to_dict()

    def connect_items(self, bound_items: typing.List) -> None:
        self.disconnect_items()

        bound_items_model = ListModel.ListModel(items=bound_items) if bound_items is not None else None
        self.__bound_items_model = bound_items_model
        self.__bound_items_model_item_inserted_event_listener = None
        self.__bound_items_model_item_removed_event_listener = None
        if bound_items_model is not None:

            def item_inserted(key, value, index):
                # self.changed_event.fire()  # implicit when setting object_specifiers
                object_specifiers = self.object_specifiers
                object_specifiers.insert(index, copy.deepcopy(value.specifier))
                self.object_specifiers = object_specifiers
                self.bound_item.item_inserted(index, self.__bound_items_model.items[index])
                self.needs_rebind_event.fire()

            def item_removed(key, value, index):
                # self.changed_event.fire()  # implicit when setting object_specifiers
                object_specifiers = self.object_specifiers
                object_specifiers.pop(index)
                self.object_specifiers = object_specifiers
                self.bound_item.item_removed(index)
                self.needs_rebind_event.fire()

            self.__bound_items_model_item_inserted_event_listener = self.__bound_items_model.item_inserted_event.listen(item_inserted)
            self.__bound_items_model_item_removed_event_listener = self.__bound_items_model.item_removed_event.listen(item_removed)

    def disconnect_items(self) -> None:
        if self.__bound_items_model:
            self.__bound_items_model.close()
            self.__bound_items_model = None
            self.__bound_items_model_item_inserted_event_listener.close()
            self.__bound_items_model_item_inserted_event_listener = None
            self.__bound_items_model_item_removed_event_listener.close()
            self.__bound_items_model_item_removed_event_listener = None

    def save_properties(self):
        # used for undo
        return self.value, self.specifier, self.secondary_specifier

    def restore_properties(self, properties):
        # used for undo
        self.value = properties[0]
        self.specifier = properties[1]
        self.secondary_specifier = properties[2]

    def __value_reader(self, persistent_property, properties):
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

    def __value_writer(self, persistent_property, properties, value):
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
    def variable_specifier(self) -> dict:
        """Return the variable specifier for this variable.

        The specifier can be used to lookup the value of this variable in a computation context.
        """
        if self.value_type is not None:
            return {"type": "variable", "version": 1, "uuid": str(self.uuid), "x-name": self.name, "x-value": self.value}
        else:
            return self.specifier

    @property
    def bound_variable(self) -> "BoundItemBase":
        """Return an object with a value property and a changed_event.

        The value property returns the value of the variable. The changed_event is fired
        whenever the value changes.
        """

        class BoundVariable(BoundItemBase):
            def __init__(self, variable):
                super().__init__(None)
                self.valid = True
                self.__variable = variable

                def property_changed(key):
                    if key == "value":
                        self.changed_event.fire()

                self.__variable_property_changed_listener = variable.property_changed_event.listen(property_changed)

            @property
            def value(self):
                return self.__variable.value

            @property
            def base_objects(self):
                return set()

            def close(self):
                self.__variable_property_changed_listener.close()
                self.__variable_property_changed_listener = None
                super().close()

        return BoundVariable(self)

    @property
    def bound_item(self):
        return self.__bound_item

    @bound_item.setter
    def bound_item(self, bound_item):
        if self.__bound_item_changed_event_listener:
            self.__bound_item_changed_event_listener.close()
            self.__bound_item_changed_event_listener = None
        if self.__bound_item_removed_event_listener:
            self.__bound_item_removed_event_listener.close()
            self.__bound_item_removed_event_listener = None
        if self.__bound_item_child_removed_event_listener:
            self.__bound_item_child_removed_event_listener.close()
            self.__bound_item_child_removed_event_listener = None
        if self.__bound_item:
            self.__bound_item.close()
        self.__bound_item = bound_item
        if self.__bound_item:
            self.__bound_item_changed_event_listener = self.__bound_item.changed_event.listen(self.changed_event.fire)
            self.__bound_item_removed_event_listener = self.__bound_item.needs_rebind_event.listen(self.needs_rebind_event.fire)
            # if hasattr(self.__bound_item, "child_removed_event"):
            #     self.__bound_item_child_removed_event_listener = self.__bound_item.child_removed_event.listen(self.bound_items_model.remove_item)

    @property
    def bound_items_model(self):
        return self.__bound_items_model

    @property
    def input_items(self) -> typing.Set:
        return self.bound_item.base_objects if self.bound_item else set()

    @property
    def direct_input_items(self) -> typing.Set:
        return self.bound_item.base_objects if self.bound_item and not getattr(self.bound_item, "is_list", False) else set()

    def __property_changed(self, name, value):
        self.notify_property_changed(name)
        if name in ["name", "label"]:
            self.notify_property_changed("display_label")
        if name in ("specifier"):
            self.notify_property_changed("specifier_uuid_str")
            self.needs_rebind_event.fire()
        if name in ("secondary_specifier"):
            self.notify_property_changed("secondary_specifier_uuid_str")
            self.needs_rebind_event.fire()
        self.changed_event.fire()
        if name in ["value_type", "value_min", "value_max", "control_type"]:
            self.needs_rebuild_event.fire()

    def notify_property_changed(self, key):
        # whenever a property changed event is fired, also fire the changed_event
        # is there a test for this? not that I can find.
        super().notify_property_changed(key)
        self.changed_event.fire()

    def control_type_default(self, value_type: str) -> None:
        mapping = {"boolean": "checkbox", "integral": "slider", "real": "field", "complex": "field", "string": "field"}
        return mapping.get(value_type)

    @property
    def variable_type(self) -> typing.Optional[str]:
        if self.value_type is not None:
            return self.value_type
        elif self.specifier is not None:
            specifier_type = self.specifier.get("type")
            specifier_property = self.specifier.get("property")
            return specifier_property or specifier_type
        return None

    data_item_types = ("data_item", "data", "display_data")  # used for backward compatibility

    @variable_type.setter
    def variable_type(self, value_type: str) -> None:
        if value_type != self.variable_type:
            if value_type in ("boolean", "integral", "real", "complex", "string"):
                self.specifier = None
                self.secondary_specifier = None
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
                specifier = self.specifier or {"version": 1}
                if not specifier.get("type") in ComputationVariable.data_item_types:
                    specifier.pop("uuid", None)
                specifier["type"] = "data_source"
                if value_type in ("data", "display_data"):
                    specifier["property"] = value_type
                else:
                    specifier.pop("property", None)
                self.specifier = specifier
                self.secondary_specifier = self.secondary_specifier or {"version": 1}
            elif value_type in ("graphic"):
                self.value_type = None
                self.control_type = None
                self.value_default = None
                self.value_min = None
                self.value_max = None
                specifier = self.specifier or {"version": 1}
                specifier["type"] = value_type
                specifier.pop("uuid", None)
                specifier.pop("property", None)
                self.specifier = specifier
                self.secondary_specifier = None
            self.variable_type_changed_event.fire()

    @property
    def specifier_uuid_str(self):
        return self.specifier.get("uuid") if self.specifier else None

    @specifier_uuid_str.setter
    def specifier_uuid_str(self, value):
        converter = Converter.UuidToStringConverter()
        value = converter.convert(converter.convert_back(value))
        if self.specifier_uuid_str != value and self.specifier:
            specifier = self.specifier
            if value:
                specifier["uuid"] = value
            else:
                specifier.pop("uuid", None)
            self.specifier = specifier

    @property
    def secondary_specifier_uuid_str(self):
        return self.secondary_specifier.get("uuid") if self.secondary_specifier else None

    @secondary_specifier_uuid_str.setter
    def secondary_specifier_uuid_str(self, value):
        converter = Converter.UuidToStringConverter()
        value = converter.convert(converter.convert_back(value))
        if self.secondary_specifier_uuid_str != value and self.secondary_specifier:
            secondary_specifier = self.secondary_specifier
            if value:
                secondary_specifier["uuid"] = value
            else:
                secondary_specifier.pop("uuid", None)
            self.secondary_specifier = secondary_specifier

    @property
    def display_label(self):
        return self.label or self.name

    @property
    def has_range(self):
        return self.value_type is not None and self.value_min is not None and self.value_max is not None


def variable_factory(lookup_id):
    build_map = {
        "variable": ComputationVariable,
    }
    type = lookup_id("type")
    return build_map[type]() if type in build_map else None


def result_factory(lookup_id):
    return ComputationOutput()


class BoundItemBase:

    def __init__(self, specifier):
        self.specifier = specifier
        self.changed_event = Event.Event()
        self.needs_rebind_event = Event.Event()
        self.property_changed_event = Event.Event()
        self.valid = False

    def close(self) -> None:
        pass

    @property
    def value(self):
        return None

    @property
    def base_objects(self) -> typing.Set:
        return set()


class BoundData(BoundItemBase):

    def __init__(self, project, specifier):
        super().__init__(specifier)

        specifier_uuid_str = specifier.get("uuid")
        object_uuid = uuid.UUID(specifier_uuid_str) if specifier_uuid_str else None

        self.__item_proxy = project.create_item_proxy(item_uuid=object_uuid)
        self.__data_changed_event_listener = None

        def maintain_data_source():
            if self.__data_changed_event_listener:
                self.__data_changed_event_listener.close()
                self.__data_changed_event_listener = None
            object = self._object
            if object:
                self.__data_changed_event_listener = object.data_changed_event.listen(self.changed_event.fire)
            self.valid = object is not None

        def item_registered(item):
            maintain_data_source()

        def item_unregistered(item):
            maintain_data_source()
            self.needs_rebind_event.fire()

        self.__item_proxy.on_item_registered = item_registered
        self.__item_proxy.on_item_unregistered = item_unregistered

        maintain_data_source()

    def close(self):
        if self.__data_changed_event_listener:
            self.__data_changed_event_listener.close()
            self.__data_changed_event_listener = None
        self.__item_proxy.close()
        self.__item_proxy = None
        super().close()

    @property
    def base_objects(self):
        return {self._object}

    @property
    def value(self):
        return self._object.xdata

    @property
    def _object(self):
        data_item = self.__item_proxy.item
        if not isinstance(data_item, DataItem.DataItem):
            display_data_channel = data_item
            data_item = display_data_channel.data_item if display_data_channel else None
        return data_item


class BoundDisplayDataChannelBase(BoundItemBase):

    def __init__(self, project, specifier, secondary_specifier):
        super().__init__(specifier)

        specifier_uuid_str = specifier.get("uuid")
        object_uuid = uuid.UUID(specifier_uuid_str) if specifier_uuid_str else None

        secondary_uuid_str = secondary_specifier.get("uuid") if secondary_specifier else None
        secondary_uuid = uuid.UUID(secondary_uuid_str) if secondary_uuid_str else None

        self.__item_proxy = project.create_item_proxy(item_uuid=object_uuid)
        self.__graphic_proxy = project.create_item_proxy(item_uuid=secondary_uuid)
        self.__display_values_changed_event_listener = None

        def maintain_data_source():
            if self.__display_values_changed_event_listener:
                self.__display_values_changed_event_listener.close()
                self.__display_values_changed_event_listener = None
            display_data_channel = self._display_data_channel
            if display_data_channel:
                self.__display_values_changed_event_listener = display_data_channel.add_calculated_display_values_listener(self.changed_event.fire, send=False)
            self.valid = self.__display_values_changed_event_listener is not None

        def item_registered(item):
            maintain_data_source()

        def item_unregistered(item):
            maintain_data_source()
            self.needs_rebind_event.fire()

        self.__item_proxy.on_item_registered = item_registered
        self.__item_proxy.on_item_unregistered = item_unregistered

        self.__graphic_proxy.on_item_registered = item_registered
        self.__graphic_proxy.on_item_unregistered = item_unregistered

        maintain_data_source()

    def close(self):
        if self.__display_values_changed_event_listener:
            self.__display_values_changed_event_listener.close()
            self.__display_values_changed_event_listener = None
        self.__item_proxy.close()
        self.__item_proxy = None
        self.__graphic_proxy.close()
        self.__graphic_proxy = None
        super().close()

    @property
    def base_objects(self):
        objects = {self._display_data_channel.container, self._display_data_channel.data_item}
        if self._graphic:
            objects.add(self._graphic)
        return objects

    @property
    def _display_data_channel(self):
        return self.__item_proxy.item

    @property
    def _graphic(self):
        return self.__graphic_proxy.item


class BoundDataSource(BoundItemBase):

    def __init__(self, project, specifier, secondary_specifier):
        super().__init__(specifier)

        specifier_uuid_str = specifier.get("uuid")
        object_uuid = uuid.UUID(specifier_uuid_str) if specifier_uuid_str else None

        secondary_uuid_str = secondary_specifier.get("uuid") if secondary_specifier else None
        secondary_uuid = uuid.UUID(secondary_uuid_str) if secondary_uuid_str else None

        self.__item_proxy = project.create_item_proxy(item_uuid=object_uuid)
        self.__graphic_proxy = project.create_item_proxy(item_uuid=secondary_uuid)
        self.__data_source = None

        def maintain_data_source():
            if self.__data_source:
                self.__data_source.close()
                self.__data_source = None
            display_data_channel = self.__item_proxy.item
            if display_data_channel and display_data_channel.data_item:
                self.__data_source = DataItem.DataSource(display_data_channel, self.__graphic_proxy.item, self.changed_event)
            self.valid = self.__data_source is not None

        def item_registered(item):
            maintain_data_source()

        def item_unregistered(item):
            maintain_data_source()
            self.needs_rebind_event.fire()

        self.__item_proxy.on_item_registered = item_registered
        self.__item_proxy.on_item_unregistered = item_unregistered

        self.__graphic_proxy.on_item_registered = item_registered
        self.__graphic_proxy.on_item_unregistered = item_unregistered

        maintain_data_source()

    def close(self):
        if self.__data_source:
            self.__data_source.close()
            self.__data_source = None
        self.__item_proxy.close()
        self.__item_proxy = None
        self.__graphic_proxy.close()
        self.__graphic_proxy = None
        super().close()

    @property
    def value(self):
        return self.__data_source

    @property
    def base_objects(self):
        objects = {self.__data_source.data_item}
        if self.__data_source.graphic:
            objects.add(self.__data_source.graphic)
        return objects


class BoundDataItem(BoundItemBase):

    def __init__(self, project, specifier):
        super().__init__(specifier)

        specifier_uuid_str = specifier.get("uuid")
        object_uuid = uuid.UUID(specifier_uuid_str) if specifier_uuid_str else None

        self.__item_proxy = project.create_item_proxy(item_uuid=object_uuid)
        self.__data_item_changed_event_listener = None

        def item_registered(item):
            self.__data_item_changed_event_listener = item.data_item_changed_event.listen(self.changed_event.fire)

        def item_unregistered(item):
            self.__data_item_changed_event_listener.close()
            self.__data_item_changed_event_listener = None
            self.needs_rebind_event.fire()

        self.__item_proxy.on_item_registered = item_registered
        self.__item_proxy.on_item_unregistered = item_unregistered

        if self.__item_proxy.item:
            item_registered(self.__item_proxy.item)
            self.valid = True
        else:
            self.valid = False

    def close(self):
        if self.__data_item_changed_event_listener:
            self.__data_item_changed_event_listener.close()
            self.__data_item_changed_event_listener = None
        self.__item_proxy.close()
        self.__item_proxy = None
        super().close()

    @property
    def value(self):
        return self.__item_proxy.item

    @property
    def base_objects(self):
        return {self.value}


class BoundDisplayData(BoundDisplayDataChannelBase):

    @property
    def value(self):
        return self._display_data_channel.get_calculated_display_values(True).display_data_and_metadata if self._display_data_channel else None


class BoundCroppedData(BoundDisplayDataChannelBase):

    @property
    def value(self):
        xdata = self._display_data_channel.data_item.xdata
        graphic = self._graphic
        if graphic:
            if hasattr(graphic, "bounds"):
                return Core.function_crop(xdata, graphic.bounds)
            if hasattr(graphic, "interval"):
                return Core.function_crop_interval(xdata, graphic.interval)
        return xdata


class BoundCroppedDisplayData(BoundDisplayDataChannelBase):

    @property
    def value(self):
        xdata = self._display_data_channel.get_calculated_display_values(True).display_data_and_metadata
        graphic = self._graphic
        if graphic:
            if hasattr(graphic, "bounds"):
                return Core.function_crop(xdata, graphic.bounds)
            if hasattr(graphic, "interval"):
                return Core.function_crop_interval(xdata, graphic.interval)
        return xdata


class BoundFilterData(BoundDisplayDataChannelBase):

    @property
    def value(self):
        display_item = self._display_data_channel.container
        # no display item is a special case for cascade removing graphics from computations. ugh.
        # see test_new_computation_becomes_unresolved_when_xdata_input_is_removed_from_document.
        if display_item:
            shape = self._display_data_channel.get_calculated_display_values(True).display_data_and_metadata.data_shape
            mask = numpy.zeros(shape)
            for graphic in display_item.graphics:
                if isinstance(graphic, (Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic, Graphics.LatticeGraphic)):
                    mask = numpy.logical_or(mask, graphic.get_mask(shape))
            return DataAndMetadata.DataAndMetadata.from_data(mask)
        return None

    @property
    def base_objects(self):
        data_item = self._display_data_channel.data_item
        display_item = self._display_data_channel.container
        objects = {data_item, display_item}
        graphics = display_item.graphics if display_item else list()
        for graphic in graphics:
            if isinstance(graphic, (Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic, Graphics.LatticeGraphic)):
                objects.add(graphic)
        return objects


class BoundFilteredData(BoundDisplayDataChannelBase):

    @property
    def value(self):
        display_item = self._display_data_channel.container
        # no display item is a special case for cascade removing graphics from computations. ugh.
        # see test_new_computation_becomes_unresolved_when_xdata_input_is_removed_from_document.
        if display_item:
            xdata = self._display_data_channel.data_item.xdata
            if xdata.is_data_2d and xdata.is_data_complex_type:
                shape = xdata.data_shape
                mask = numpy.zeros(shape)
                for graphic in display_item.graphics:
                    if isinstance(graphic, (Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic, Graphics.LatticeGraphic)):
                        mask = numpy.logical_or(mask, graphic.get_mask(shape))
                return Core.function_fourier_mask(xdata, DataAndMetadata.DataAndMetadata.from_data(mask))
            return xdata
        return None

    @property
    def base_objects(self):
        data_item = self._display_data_channel.data_item
        display_item = self._display_data_channel.container
        objects = {data_item, display_item}
        graphics = display_item.graphics if display_item else list()
        for graphic in graphics:
            if isinstance(graphic, (Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic, Graphics.LatticeGraphic)):
                objects.add(graphic)
        return objects


class BoundDataStructure(BoundItemBase):

    def __init__(self, project, specifier, property_name: str):
        super().__init__(specifier)

        specifier_uuid_str = specifier.get("uuid")
        object_uuid = uuid.UUID(specifier_uuid_str) if specifier_uuid_str else None

        self.__property_name = property_name

        self.__item_proxy = project.create_item_proxy(item_uuid=object_uuid)
        self.__changed_listener = None

        def data_structure_changed(property_name):
            self.changed_event.fire()
            if property_name == self.__property_name:
                self.property_changed_event.fire(property_name)

        def item_registered(item):
            self.__changed_listener = item.data_structure_changed_event.listen(data_structure_changed)

        def item_unregistered(item):
            self.__changed_listener.close()
            self.__changed_listener = None
            self.needs_rebind_event.fire()

        self.__item_proxy.on_item_registered = item_registered
        self.__item_proxy.on_item_unregistered = item_unregistered

        if self.__item_proxy.item:
            item_registered(self.__item_proxy.item)
            self.valid = True
        else:
            self.valid = False

    def close(self):
        if self.__changed_listener:
            self.__changed_listener.close()
            self.__changed_listener = None
        self.__item_proxy.close()
        self.__item_proxy = None
        super().close()

    @property
    def value(self):
        if self.__property_name:
            return self.__object.get_property_value(self.__property_name)
        return self.__object

    @property
    def base_objects(self):
        return {self.__object}

    @property
    def __object(self):
        return self.__item_proxy.item


class BoundGraphic(BoundItemBase):

    def __init__(self, project, specifier, property_name: str):
        super().__init__(specifier)

        specifier_uuid_str = specifier.get("uuid")
        object_uuid = uuid.UUID(specifier_uuid_str) if specifier_uuid_str else None

        self.__property_name = property_name

        self.__item_proxy = project.create_item_proxy(item_uuid=object_uuid)
        self.__changed_listener = None

        def property_changed(property_name):
            self.changed_event.fire()
            if property_name == self.__property_name:
                self.property_changed_event.fire(property_name)

        def item_registered(item):
            self.__changed_listener = item.property_changed_event.listen(property_changed)

        def item_unregistered(item):
            self.__changed_listener.close()
            self.__changed_listener = None
            self.needs_rebind_event.fire()

        self.__item_proxy.on_item_registered = item_registered
        self.__item_proxy.on_item_unregistered = item_unregistered

        if self.__item_proxy.item:
            item_registered(self.__item_proxy.item)
            self.valid = True
        else:
            self.valid = False

    def close(self):
        if self.__changed_listener:
            self.__changed_listener.close()
            self.__changed_listener = None
        self.__item_proxy.close()
        self.__item_proxy = None
        super().close()

    @property
    def value(self):
        if self.__property_name:
            return getattr(self.__object, self.__property_name)
        return self.__object

    @property
    def base_objects(self):
        return {self.__object}

    @property
    def __object(self):
        return self.__item_proxy.item


class ComputationItem:
    def __init__(self, *, item=None, type: str=None, secondary_item=None, items: typing.List["ComputationItem"] = None):
        self.item = item
        self.type = type
        self.secondary_item = secondary_item
        self.items = items


def make_item(item, *, type: str=None, secondary_item=None) -> ComputationItem:
    return ComputationItem(item=item, type=type, secondary_item=secondary_item)


def make_item_list(items, *, type: str=None) -> ComputationItem:
    items = [make_item(item, type=type) if not isinstance(item, ComputationItem) else item for item in items]
    return ComputationItem(items=items)


class BoundList:

    def __init__(self, bound_items: typing.List):
        self.__bound_items = list()
        self.changed_event = Event.Event()
        self.needs_rebind_event = Event.Event()
        self.child_removed_event = Event.Event()
        self.property_changed_event = Event.Event()
        self.is_list = True
        self.__changed_listeners = list()
        self.__needs_rebind_listeners = list()
        self.__resolved = True
        for index, bound_item in enumerate(bound_items):
            self.item_inserted(index, bound_item)

    def close(self):
        while len(self.__bound_items) > 0:
            self.item_removed(0)
        self.__bound_items = None
        self.__resolved_items = None
        self.__changed_listeners = None

    @property
    def value(self):
        return [bound_item.value for bound_item in self.__bound_items] if self.__resolved else None

    @property
    def base_objects(self):
        # return the base objects in a stable order
        base_objects = list()
        for bound_item in self.__bound_items:
            if bound_item:
                for base_object in bound_item.base_objects:
                    if not base_object in base_objects:
                        base_objects.append(base_object)
        return base_objects

    def item_inserted(self, index, bound_item):
        self.__bound_items.insert(index, bound_item)
        self.__changed_listeners.insert(index, bound_item.changed_event.listen(self.changed_event.fire) if bound_item else None)
        self.__needs_rebind_listeners.insert(index, bound_item.needs_rebind_event.listen(functools.partial(self.child_removed_event.fire, index)) if bound_item else None)
        self.__resolved = self.__resolved and bound_item is not None

    def item_removed(self, index):
        bound_item = self.__bound_items.pop(index)
        if bound_item:
            bound_item.close()
        changed_listener = self.__changed_listeners.pop(index)
        if changed_listener:
            changed_listener.close()
        needs_rebind_listener = self.__needs_rebind_listeners.pop(index)
        if needs_rebind_listener:
            needs_rebind_listener.close()

class Computation(Observable.Observable, Persistence.PersistentObject):
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

    def __init__(self, expression: str=None):
        super().__init__()
        self.__container_weak_ref = None
        self.about_to_be_removed_event = Event.Event()
        self.about_to_cascade_delete_event = Event.Event()
        self._about_to_be_removed = False
        self._closed = False
        self.define_type("computation")
        self.define_property("source_uuid", converter=Converter.UuidToStringConverter(), changed=self.__source_uuid_changed)
        self.define_property("original_expression", expression)
        self.define_property("error_text", hidden=True, changed=self.__error_changed)
        self.define_property("label", changed=self.__label_changed)
        self.define_property("processing_id")  # see note above
        self.define_relationship("variables", variable_factory)
        self.define_relationship("results", result_factory)
        self.__source_proxy = self.create_item_proxy()
        self.__variable_changed_event_listeners = dict()
        self.__variable_needs_rebind_event_listeners = dict()
        self.__result_needs_rebind_event_listeners = dict()
        self.last_evaluate_data_time = 0
        self.needs_update = expression is not None
        self.computation_mutated_event = Event.Event()
        self.computation_output_changed_event = Event.Event()
        self.variable_inserted_event = Event.Event()
        self.variable_removed_event = Event.Event()
        self.is_initial_computation_complete = threading.Event()  # helpful for waiting for initial computation
        self._evaluation_count_for_test = 0
        self._inputs = set()  # used by document model for tracking dependencies
        self._outputs = set()
        self.pending_project = None  # used for new computations to tell them where they'll end up

    def close(self) -> None:
        self.__source_proxy.close()
        self.__source_proxy = None
        assert self._about_to_be_removed
        assert not self._closed
        self._closed = True
        self.__container_weak_ref = None
        super().close()

    @property
    def container(self):
        return self.__container_weak_ref() if self.__container_weak_ref else None

    @property
    def project(self) -> "Project.Project":
        return typing.cast("Project.Project", self.container)

    def create_proxy(self) -> Persistence.PersistentObjectProxy:
        return self.project.create_item_proxy(item=self)

    def prepare_cascade_delete(self) -> typing.List:
        cascade_items = list()
        self.about_to_cascade_delete_event.fire(cascade_items)
        return cascade_items

    def about_to_be_inserted(self, container):
        assert self.__container_weak_ref is None
        self.__container_weak_ref = weakref.ref(container)

    def about_to_be_removed(self):
        # called before close and before item is removed from its container
        self.about_to_be_removed_event.fire()
        assert not self._about_to_be_removed
        self._about_to_be_removed = True
        self.__container_weak_ref = None

    def read_properties_from_dict(self, d):
        if "source_uuid" in d:
            self.source_uuid = uuid.UUID(d["source_uuid"])
        self.original_expression = d.get("original_expression", self.original_expression)
        self.error_text = d.get("error_text", self.error_text)
        self.label = d.get("label", self.label)
        self.processing_id = d.get("processing_id", self.processing_id)

    def insert_model_item(self, container, name, before_index, item):
        if self.__container_weak_ref:
            self.container.insert_model_item(container, name, before_index, item)
        else:
            container.insert_item(name, before_index, item)

    def remove_model_item(self, container, name, item, *, safe: bool=False) -> Changes.UndeleteLog:
        if self.__container_weak_ref:
            return self.container.remove_model_item(container, name, item, safe=safe)
        else:
            container.remove_item(name, item)
            return Changes.UndeleteLog()

    def read_from_dict(self, properties):
        super().read_from_dict(properties)

    # override this so it can be short circuited if self.pending_project is available.
    # this is used to check inputs/outputs for circular dependencies before the computation is added to the project.
    def _get_related_item(self, item_uuid: uuid.UUID) -> typing.Optional[Persistence.PersistentObject]:
        related_item = super()._get_related_item(item_uuid)
        if related_item is None and self.pending_project:
            related_item = self.pending_project._get_related_item(item_uuid)
        return related_item

    @property
    def source(self):
        return self.__source_proxy.item

    @source.setter
    def source(self, source):
        self.__source_proxy.item = source
        self.source_uuid = source.uuid if source else None

    def __source_uuid_changed(self, name: str, item_uuid: uuid.UUID) -> None:
        self.__source_proxy.item_uuid = item_uuid

    @property
    def error_text(self) -> typing.Optional[str]:
        return self._get_persistent_property_value("error_text")

    @error_text.setter
    def error_text(self, value):
        modified_state = self.modified_state
        self._set_persistent_property_value("error_text", value)
        self.modified_state = modified_state

    def __error_changed(self, name, value):
        self.notify_property_changed(name)
        self.computation_mutated_event.fire()

    def __label_changed(self, name, value):
        self.notify_property_changed(name)
        self.computation_mutated_event.fire()

    def add_variable(self, variable: ComputationVariable) -> None:
        self.insert_variable(len(self.variables), variable)

    def insert_variable(self, index: int, variable: ComputationVariable) -> None:
        self.insert_item("variables", index, variable)
        if self.persistent_object_context:
            self.__bind_variable(variable)
        self.variable_inserted_event.fire(index, variable)
        self.computation_mutated_event.fire()
        self.needs_update = True

    def remove_variable(self, variable: ComputationVariable) -> None:
        self.__unbind_variable(variable)
        index = self.item_index("variables", variable)
        self.remove_item("variables", variable)
        self.variable_removed_event.fire(index, variable)
        self.computation_mutated_event.fire()
        self.needs_update = True

    def create_variable(self, name: str=None, value_type: str=None, value=None, value_default=None, value_min=None, value_max=None, control_type: str=None, specifier: dict=None, label: str=None) -> ComputationVariable:
        variable = ComputationVariable(name, value_type=value_type, value=value, value_default=value_default, value_min=value_min, value_max=value_max, control_type=control_type, specifier=specifier, label=label)
        self.add_variable(variable)
        return variable

    def create_input_item(self, name: str, input_item: ComputationItem, *, property_name: str=None, label: str=None) -> ComputationVariable:
        if input_item.items is not None:
            variable = ComputationVariable(name, items=input_item.items, label=label)
            self.add_variable(variable)
            return variable
        else:
            specifier = DataStructure.get_object_specifier(input_item.item, input_item.type)
            secondary_specifier = DataStructure.get_object_specifier(input_item.secondary_item) if input_item.secondary_item else None
            variable = ComputationVariable(name, specifier=specifier, secondary_specifier=secondary_specifier, property_name=property_name, label=label)
            self.add_variable(variable)
            return variable

    def create_output_item(self, name: str, output_item: ComputationItem=None, *, label: str=None) -> ComputationOutput:
        if output_item and output_item.items is not None:
            specifiers = [DataStructure.get_object_specifier(item.item) for item in output_item.items]
            result = ComputationOutput(name, specifiers=specifiers, label=label)
            self.append_item("results", result)
            if self.persistent_object_context:
                self.__bind_result(result)
            self.computation_mutated_event.fire()
            return result
        elif output_item:
            assert not output_item.type
            assert not output_item.secondary_item
            specifier = DataStructure.get_object_specifier(output_item.item)
            result = ComputationOutput(name, specifier=specifier, label=label)
            self.append_item("results", result)
            if self.persistent_object_context:
                self.__bind_result(result)
            self.computation_mutated_event.fire()
            return result

    def remove_item_from_objects(self, name: str, index: int) -> None:
        variable = self._get_variable(name)
        variable.bound_items_model.remove_item(index)

    def insert_item_into_objects(self, name: str, index: int, input_item: ComputationItem) -> None:
        variable = self._get_variable(name)
        specifier = DataStructure.get_object_specifier(input_item.item, input_item.type)
        variable.bound_items_model.insert_item(index, self.__resolve_object_specifier(specifier))

    def list_item_removed(self, object) -> typing.Optional[typing.Tuple[int, int, dict]]:
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
                for index, (object_specifier, bound_item) in enumerate(zip(variable.object_specifiers, variable.bound_items_model.items)):
                    base_objects = bound_item.base_objects if bound_item else list()
                    if object in base_objects:
                        variables_index = self.variables.index(variable)
                        variable.bound_items_model.remove_item(index)
                        return (index, variables_index, copy.deepcopy(object_specifier))
        return None

    def __resolve_variable(self, object_specifier: dict) -> typing.Optional[ComputationVariable]:
        if object_specifier:
            uuid_str = object_specifier.get("uuid")
            uuid_ = Converter.UuidToStringConverter().convert_back(uuid_str) if uuid_str else None
            if uuid_:
                for variable in self.variables:
                    if variable.uuid == uuid_:
                        return variable
        return None

    def __resolve_object_specifier(self, specifier, secondary_specifier=None, property_name=None) -> typing.Optional[BoundItemBase]:
        """Resolve the object specifier.

        First lookup the object specifier in the enclosing computation. If it's not found,
        then lookup in the computation's context. Otherwise it should be a value type variable.
        In that case, return the bound variable.
        """
        bound_item = None
        variable = self.__resolve_variable(specifier)
        if not variable:
            if specifier and specifier.get("version") == 1:
                specifier_type = specifier["type"]
                project = self.container or self.pending_project
                if specifier_type == "data_source":
                    bound_item = BoundDataSource(project, specifier, secondary_specifier)
                elif specifier_type == "data_item":
                    bound_item = BoundDataItem(project, specifier)
                elif specifier_type == "xdata":
                    bound_item = BoundData(project, specifier)
                elif specifier_type == "display_xdata":
                    bound_item = BoundDisplayData(project, specifier, secondary_specifier)
                elif specifier_type == "cropped_xdata":
                    bound_item = BoundCroppedData(project, specifier, secondary_specifier)
                elif specifier_type == "cropped_display_xdata":
                    bound_item = BoundCroppedDisplayData(project, specifier, secondary_specifier)
                elif specifier_type == "filter_xdata":
                    bound_item = BoundFilterData(project, specifier, secondary_specifier)
                elif specifier_type == "filtered_xdata":
                    bound_item = BoundFilteredData(project, specifier, secondary_specifier)
                elif specifier_type == "structure":
                    bound_item = BoundDataStructure(project, specifier, property_name)
                elif specifier_type == "graphic":
                    bound_item = BoundGraphic(project, specifier, property_name)
        elif variable.specifier is None:
            bound_item = variable.bound_variable
        if bound_item and not bound_item.valid:
            bound_item.close()
            bound_item = None
        return bound_item

    @property
    def expression(self) -> str:
        return self.original_expression

    @expression.setter
    def expression(self, value: str) -> None:
        if value != self.original_expression:
            self.original_expression = value
            self.processing_id = None
            self.needs_update = True
            self.computation_mutated_event.fire()

    @classmethod
    def parse_names(cls, expression):
        """Return the list of identifiers used in the expression."""
        names = set()
        try:
            ast_node = ast.parse(expression, "ast")

            class Visitor(ast.NodeVisitor):
                def visit_Name(self, node):
                    names.add(node.id)

            Visitor().visit(ast_node)
        except Exception:
            pass
        return names

    def __resolve_inputs(self, api) -> typing.Tuple[typing.Dict, bool]:
        kwargs = dict()
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
            if result.specifier and not result.bound_item:
                is_resolved = False
            if result.specifiers and not all(result.bound_item):
                is_resolved = False
        return kwargs, is_resolved

    def evaluate(self, api) -> typing.Tuple[typing.Callable, str]:
        compute_obj = None
        error_text = None
        needs_update = self.needs_update
        self.needs_update = False
        if needs_update:
            kwargs, is_resolved = self.__resolve_inputs(api)
            if is_resolved:
                compute_class = _computation_types.get(self.processing_id)
                if compute_class:
                    try:
                        api_computation = api._new_api_object(self)
                        api_computation.api = api
                        compute_obj = compute_class(api_computation)
                        compute_obj.execute(**kwargs)
                    except Exception as e:
                        # import sys, traceback
                        # traceback.print_exc()
                        # traceback.format_exception(*sys.exc_info())
                        compute_obj = None
                        error_text = str(e) or "Unable to evaluate script."  # a stack trace would be too much information right now
                else:
                    compute_obj = None
                    error_text = "Missing computation (" + self.processing_id + ")."
            else:
                error_text = "Missing parameters."
            self._evaluation_count_for_test += 1
            self.last_evaluate_data_time = time.perf_counter()
        return compute_obj, error_text

    def evaluate_with_target(self, api, target) -> str:
        assert target is not None
        error_text = None
        needs_update = self.needs_update
        self.needs_update = False
        if needs_update:
            variables = dict()
            for variable in self.variables:
                bound_object = variable.bound_item
                if bound_object is not None:
                    resolved_object = bound_object.value if bound_object else None
                    # in the ideal world, we could clone the object/data and computations would not be
                    # able to modify the input objects; reality, though, dictates that performance is
                    # more important than this protection. so use the resolved object directly.
                    api_object = api._new_api_object(resolved_object) if resolved_object else None
                    variables[variable.name] = api_object if api_object else resolved_object  # use api only if resolved_object is an api style object

            expression = self.original_expression
            if expression:
                error_text = self.__execute_code(api, expression, target, variables)

            self._evaluation_count_for_test += 1
            self.last_evaluate_data_time = time.perf_counter()
        return error_text

    def __execute_code(self, api, expression, target, variables) -> typing.Optional[str]:
        code_lines = []
        g = variables
        g["api"] = api
        g["target"] = target
        l = dict()
        expression_lines = expression.split("\n")
        code_lines.extend(expression_lines)
        code = "\n".join(code_lines)
        try:
            # print(code)
            compiled = compile(code, "expr", "exec")
            exec(compiled, g, l)
        except Exception as e:
            # print(code)
            # import sys, traceback
            # traceback.print_exc()
            # traceback.format_exception(*sys.exc_info())
            return str(e) or "Unable to evaluate script."  # a stack trace would be too much information right now
        return None

    def mark_update(self):
        self.needs_update = True
        self.computation_mutated_event.fire()

    @property
    def is_resolved(self):
        if not all(not v.specifier or v.bound_item for v in self.variables):
            return False
        for result in self.results:
            if result.specifier and not result.bound_item:
                return False
            if result.specifiers and not all(result.bound_item):
                return False
        return True

    def undelete_variable_item(self, name: str, index: int, specifier: typing.Dict) -> None:
        for variable in self.variables:
            if variable.name == name:
                variable.bound_items_model.insert_item(index, self.__resolve_object_specifier(specifier))

    def __bind_variable(self, variable: ComputationVariable) -> None:
        # bind the variable. the variable has a reference to another object in the library.
        # this method finds that object and stores it into the variable. it also sets up
        # listeners to notify this computation that the variable or the object referenced
        # by the variable has changed in a way that the computation needs re-execution,
        # and that the variable needs rebinding, which must be done from this class.

        def needs_update():
            self.needs_update = True
            self.computation_mutated_event.fire()

        self.__variable_changed_event_listeners[variable.uuid] = variable.changed_event.listen(needs_update)

        def rebind():
            self.needs_update = True
            self.__unbind_variable(variable)
            self.__bind_variable(variable)

        self.__variable_needs_rebind_event_listeners[variable.uuid] = variable.needs_rebind_event.listen(rebind)

        if variable.object_specifiers is not None:
            bound_items = list()
            for object_specifier in variable.object_specifiers:
                bound_item = self.__resolve_object_specifier(object_specifier)
                bound_items.append(bound_item)
            variable.connect_items(bound_items)
            variable.bound_item = BoundList(bound_items)
        else:
            variable.bound_item = self.__resolve_object_specifier(variable.variable_specifier, variable.secondary_specifier, variable.property_name)

    def __unbind_variable(self, variable: ComputationVariable) -> None:
        self.__variable_changed_event_listeners[variable.uuid].close()
        del self.__variable_changed_event_listeners[variable.uuid]
        self.__variable_needs_rebind_event_listeners[variable.uuid].close()
        del self.__variable_needs_rebind_event_listeners[variable.uuid]
        variable.bound_item = None
        variable.disconnect_items()

    def __bind_result(self, result: ComputationOutput) -> None:
        # bind the result. the result has an optional reference to another object in the library.
        # this method finds that object and stores it into the result. it also sets up
        # a listener to notify this computation that the result or the object referenced
        # by the result needs rebinding, which must be done from this class.

        def rebind():
            self.__unbind_result(result)
            self.__bind_result(result)
            self.computation_output_changed_event.fire()

        self.__result_needs_rebind_event_listeners[result.uuid] = result.needs_rebind_event.listen(rebind)

        result.bind(self.__resolve_object_specifier)

    def __unbind_result(self, result: ComputationOutput) -> None:
        self.__result_needs_rebind_event_listeners[result.uuid].close()
        del self.__result_needs_rebind_event_listeners[result.uuid]
        result.bound_item = None

    def bind(self, context) -> None:
        """Bind a context to this computation.

        The context allows the computation to convert object specifiers to actual objects.
        """

        # make a computation context based on the enclosing context.
        assert self.persistent_object_context

        # re-bind is not valid. be careful to set the computation after the data item is already in document.
        for variable in self.variables:
            assert variable.bound_item is None
        for result in self.results:
            assert result.bound_item is None

        # bind the variables
        for variable in self.variables:
            self.__bind_variable(variable)

        # bind the results
        for result in self.results:
            self.__bind_result(result)

    def unbind(self):
        """Unlisten and close each bound item."""
        for variable in self.variables:
            self.__unbind_variable(variable)
        for result in self.results:
            self.__unbind_result(result)

    def get_preliminary_input_items(self) -> typing.Set:
        input_items = set()
        for variable in self.variables:
            if variable.object_specifiers is not None:
                for object_specifier in variable.object_specifiers:
                    bound_item = self.__resolve_object_specifier(object_specifier)
                    if bound_item:
                        with contextlib.closing(bound_item):
                            input_items.update(bound_item.base_objects)
            else:
                bound_item = self.__resolve_object_specifier(variable.variable_specifier, variable.secondary_specifier, variable.property_name)
                if bound_item:
                    with contextlib.closing(bound_item):
                        input_items.update(bound_item.base_objects)
        return input_items

    def get_preliminary_output_items(self) -> typing.Set:
        output_items = set()
        for result in self.results:
            if result.specifier:
                bound_item = self.__resolve_object_specifier(result.specifier)
                if bound_item:
                    with contextlib.closing(bound_item):
                        output_items.update(bound_item.base_objects)
            elif result.specifiers is not None:
                for specifier in result.specifiers:
                    bound_item = self.__resolve_object_specifier(specifier)
                    if bound_item:
                        with contextlib.closing(bound_item):
                            output_items.update(bound_item.base_objects)
        return output_items

    @property
    def input_items(self) -> typing.Set:
        input_items = set()
        for variable in self.variables:
            input_items.update(variable.input_items)
        return input_items

    @property
    def direct_input_items(self) -> typing.Set:
        input_items = set()
        for variable in self.variables:
            input_items.update(variable.direct_input_items)
        return input_items

    @property
    def output_items(self) -> typing.Set:
        output_items = set()
        for result in self.results:
            output_items.update(result.output_items)
        return output_items

    def set_input_item(self, name: str, input_item: ComputationItem) -> None:
        for variable in self.variables:
            if variable.name == name:
                assert input_item.item
                assert input_item.type is None
                assert input_item.secondary_item is None
                assert input_item.items is None
                variable.specifier = DataStructure.get_object_specifier(input_item.item)

    def set_output_item(self, name:str, output_item: ComputationItem) -> None:
        for result in self.results:
            if result.name == name:
                if output_item and output_item.items is not None:
                    result.specifiers = [DataStructure.get_object_specifier(o.item) for o in output_item.items]
                else:
                    if output_item:
                        assert output_item.item
                        assert output_item.type is None
                        assert output_item.secondary_item is None
                    result.specifier = DataStructure.get_object_specifier(output_item.item) if output_item else None

    def get_input(self, name: str):
        for variable in self.variables:
            if variable.name == name:
                return variable.bound_item.value if variable.bound_item else None
        return None

    def get_output(self, name: str):
        for result in self.results:
            if result.name == name:
                if isinstance(result.bound_item, list):
                    return [bound_item.value for bound_item in result.bound_item]
                if result.bound_item:
                    return result.bound_item.value
        return None

    def set_input_value(self, name: str, value) -> None:
        for variable in self.variables:
            if variable.name == name:
                variable.value = value

    def get_input_value(self, name: str):
        for variable in self.variables:
            if variable.name == name:
                return variable.bound_variable.value if variable.bound_variable else None
        return None

    def get_input_base_items(self, name: str) -> typing.Optional[typing.Set]:
        for variable in self.variables:
            if variable.name == name:
                return variable.bound_item.base_objects if variable.bound_item else None
        return None

    def _get_variable(self, variable_name) -> ComputationVariable:
        for variable in self.variables:
            if variable.name == variable_name:
                return variable
        return None

    def _set_variable_value(self, variable_name, value):
        for variable in self.variables:
            if variable.name == variable_name:
                variable.value = value

    def _has_variable(self, variable_name: str) -> bool:
        for variable in self.variables:
            if variable.name == variable_name:
                return True
        return False

    def _clear_referenced_object(self, name: str) -> None:
        for result in self.results:
            if result.name == name:
                if result.bound_item:
                    self.__unbind_result(result)
                index = self.item_index("results", result)
                self.remove_item("results", result)
                # self.result_removed_event.fire(index, result)
                self.computation_mutated_event.fire()
                self.needs_update = True

    def _get_reference(self, name: str):
        for result in self.results:
            if result.name == name:
                return result
        return None

    def update_script(self, processing_descriptions) -> None:
        processing_id = self.processing_id
        processing_description = processing_descriptions.get(processing_id)
        if processing_description:
            src_names = list()
            src_texts = list()
            source_dicts = processing_description["sources"]
            for i, source_dict in enumerate(source_dicts):
                src_names.append(source_dict["name"])
                use_display_data = source_dict.get("use_display_data", True)
                xdata_property = "display_xdata" if use_display_data else "xdata"
                if source_dict.get("croppable"):
                    xdata_property = "cropped_" + xdata_property
                elif source_dict.get("use_filtered_data", False):
                    xdata_property = "filtered_" + xdata_property
                data_expression = source_dict["name"] + "." + xdata_property
                src_texts.append(data_expression)
            script = processing_description.get("script")
            if not script:
                expression = processing_description.get("expression")
                if expression:
                    script = xdata_expression(expression)
            script = script.format(**dict(zip(src_names, src_texts)))
            self._get_persistent_property("original_expression").value = script

# for computations

_computation_types = dict()

def register_computation_type(computation_type_id: str, compute_class: typing.Callable) -> None:
    _computation_types[computation_type_id] = compute_class

# for testing

def xdata_expression(expression: str=None) -> str:
    return "import numpy\nimport uuid\nfrom nion.data import xdata_1_0 as xd\ntarget.xdata = " + expression

def data_expression(expression: str=None) -> str:
    return "import numpy\nimport uuid\nfrom nion.data import xdata_1_0 as xd\ntarget.data = " + expression
