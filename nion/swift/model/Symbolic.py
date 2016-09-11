"""
    Provide symbolic math services.

    The goal is to provide a module (namespace) where users can be provided with variables representing
    data items (directly or indirectly via reference to workspace panels).

    DataNodes represent data items, operations, numpy arrays, and constants.
"""

# standard libraries
import ast
import functools
import threading
import time
import typing
import uuid
import weakref

# third party libraries

# local libraries
from nion.data import Context
from nion.data import DataAndMetadata
from nion.utils import Converter
from nion.utils import Event
from nion.utils import Observable
from nion.utils import Persistence


def data_by_uuid(context, data_item_uuid):
    return context.resolve_object_specifier(context.get_data_item_specifier(data_item_uuid, "data")).value


def region_by_uuid(context, region_uuid):
    return context.resolve_object_specifier(context.get_region_specifier(region_uuid)).value


def region_mask(data_and_metadata, region):
    dimensional_shape = data_and_metadata.dimensional_shape[0:2]  # signal_index
    mask = region.get_mask(dimensional_shape)
    return DataAndMetadata.DataAndMetadata.from_data(mask)


class ComputationVariableType:
    """Defines a type of a computation variable beyond the built-in types."""
    def __init__(self, type_id: str, label: str, object_type):
        self.type_id = type_id
        self.label = label
        self.object_type = object_type
        self.object_remove_event = Event.Event()
        self.__objects = dict()  # type: typing.Dict[uuid.UUID, typing.Any]

    def get_object_by_uuid(self, object_uuid: uuid.UUID):
        return self.__objects.get(object_uuid)

    def register_object(self, object):
        assert object.uuid not in self.__objects
        self.__objects[object.uuid] = object

    def unregister_object(self, object):
        assert object.uuid in self.__objects
        del self.__objects[object.uuid]
        self.object_remove_event.fire(object)


class ComputationVariable(Observable.Observable, Persistence.PersistentObject):
    """Tracks a variable used in a computation.

    A variable has user visible name, a label used in the script, a value type.

    Scalar value types have a value, a default, and optional min and max values. The control type is used to
    specify the preferred UI control (e.g. checkbox vs. input field).

    Specifier value types have a specifier which can be resolved to a specific object.
    """
    def __init__(self, name: str=None, value_type: str=None, value=None, value_default=None, value_min=None, value_max=None, control_type: str=None, specifier: dict=None, label: str=None):  # defaults are None for factory
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
        self.define_property("control_type", control_type, changed=self.__property_changed)
        self.define_property("cascade_delete", changed=self.__property_changed)
        self.changed_event = Event.Event()
        self.variable_type_changed_event = Event.Event()

    def __repr__(self):
        return "{} ({} {} {} {})".format(super().__repr__(), self.name, self.label, self.value, self.specifier)

    def read_from_dict(self, properties: dict) -> None:
        # ensure that value_type is read first
        value_type_property = self._get_persistent_property("value_type")
        value_type_property.read_from_dict(properties)
        super().read_from_dict(properties)

    def write_to_dict(self) -> dict:
        return super().write_to_dict()

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
    def bound_variable(self):
        """Return an object with a value property and a changed_event.

        The value property returns the value of the variable. The changed_event is fired
        whenever the value changes.
        """
        class BoundVariable(object):
            def __init__(self, variable):
                self.__variable = variable
                self.changed_event = Event.Event()
                self.deleted_event = Event.Event()
                def property_changed(key, value):
                    if key == "value":
                        self.changed_event.fire()
                self.__variable_property_changed_listener = variable.property_changed_event.listen(property_changed)
            @property
            def value(self):
                return self.__variable.value
            def close(self):
                self.__variable_property_changed_listener.close()
                self.__variable_property_changed_listener = None
        return BoundVariable(self)

    def __property_changed(self, name, value):
        self.notify_set_property(name, value)
        if name in ["name", "label"]:
            self.notify_set_property("display_label", self.display_label)
        if name in ("specifier"):
            self.notify_set_property("specifier_uuid_str", self.specifier_uuid_str)
        self.changed_event.fire()

    def control_type_default(self, value_type: str) -> None:
        mapping = {"boolean": "checkbox", "integral": "slider", "real": "field", "complex": "field", "string": "field"}
        return mapping.get(value_type)

    @property
    def variable_type(self) -> str:
        if self.value_type is not None:
            return self.value_type
        elif self.specifier is not None:
            specifier_type = self.specifier.get("type")
            specifier_property = self.specifier.get("property")
            return specifier_property or specifier_type
        return None

    data_types = ("data_item", "data", "display_data")

    @variable_type.setter
    def variable_type(self, value_type: str) -> None:
        if value_type != self.variable_type:
            if value_type in ("boolean", "integral", "real", "complex", "string"):
                self.specifier = None
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
            elif value_type in ComputationVariable.data_types:
                self.value_type = None
                self.control_type = None
                self.value_default = None
                self.value_min = None
                self.value_max = None
                specifier = self.specifier or {"version": 1}
                if not specifier.get("type") in ComputationVariable.data_types:
                    specifier.pop("uuid", None)
                specifier["type"] = "data_item"
                if value_type in ("data", "display_data"):
                    specifier["property"] = value_type
                else:
                    specifier.pop("property", None)
                self.specifier = specifier
            elif value_type in ("region"):
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
            elif value_type in ComputationVariable.get_extension_types():
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
    def display_label(self):
        return self.label or self.name

    @property
    def has_range(self):
        return self.value_type is not None and self.value_min is not None and self.value_max is not None

    # handle extension types

    extension_types = list()  # type: typing.List[ComputationVariableType]

    @classmethod
    def get_extension_type_items(cls):
        """Return a list of type_id / label tuples."""
        type_items = list()
        for computation_variable_type in ComputationVariable.extension_types:
            type_items.append((computation_variable_type.type_id, computation_variable_type.label))
        return type_items

    @classmethod
    def get_extension_types(cls):
        """Return a list of type_ids."""
        return [computation_variable_type.type_id for computation_variable_type in ComputationVariable.extension_types]

    @classmethod
    def get_extension_object_specifier(cls, object):
        for computation_variable_type in ComputationVariable.extension_types:
            if isinstance(object, computation_variable_type.object_type):
                return {"version": 1, "type": computation_variable_type.type_id, "uuid": str(object.uuid)}
        return None

    @classmethod
    def resolve_extension_object_specifier(cls, specifier: dict):
        if specifier.get("version") == 1:
            specifier_type = specifier["type"]
            for computation_variable_type in ComputationVariable.extension_types:
                if computation_variable_type.type_id == specifier_type:
                    specifier_uuid_str = specifier.get("uuid")
                    object_uuid = uuid.UUID(specifier_uuid_str) if specifier_uuid_str else None
                    object = computation_variable_type.get_object_by_uuid(object_uuid)
                    class BoundObject:
                        def __init__(self, object):
                            self.__object = object
                            self.changed_event = Event.Event()
                            self.deleted_event = Event.Event()
                            def remove_object(object):
                                if self.__object == object:
                                    self.deleted_event.fire()
                            def property_changed(property_name_being_changed, value):
                                self.changed_event.fire()
                            self.__remove_object_listener = computation_variable_type.object_remove_event.listen(remove_object)
                            self.__property_changed_listener = self.__object.property_changed_event.listen(property_changed)
                        def close(self):
                            self.__property_changed_listener.close()
                            self.__property_changed_listener = None
                            self.__remove_object_listener.close()
                            self.__remove_object_listener = None
                        @property
                        def value(self):
                            return self.__object
                    if object:
                        return BoundObject(object)
        return None

    @classmethod
    def register_computation_variable_type(cls, computation_variable_type: ComputationVariableType) -> None:
        ComputationVariable.extension_types.append(computation_variable_type)

    @classmethod
    def unregister_computation_variable_type(cls, computation_variable_type: ComputationVariableType) -> None:
        ComputationVariable.extension_types.remove(computation_variable_type)



def variable_factory(lookup_id):
    build_map = {
        "variable": ComputationVariable,
    }
    type = lookup_id("type")
    return build_map[type]() if type in build_map else None


class ComputationContext(object):
    def __init__(self, computation, context):
        self.__computation = weakref.ref(computation)
        self.__context = context

    def get_data_item_specifier(self, data_item_uuid, property_name: str=None):
        """Supports data item lookup by uuid."""
        return self.__context.get_object_specifier(self.__context.get_data_item_by_uuid(data_item_uuid), property_name)

    def get_region_specifier(self, region_uuid):
        """Supports region lookup by uuid."""
        for data_item in self.__context.data_items:
            for data_source in data_item.data_sources:
                for display in data_source.displays:
                    for region in display.graphics:
                        if region.uuid == region_uuid:
                            return self.__context.get_object_specifier(region)
        return None

    def resolve_object_specifier(self, object_specifier):
        """Resolve the object specifier.

        First lookup the object specifier in the enclosing computation. If it's not found,
        then lookup in the computation's context. Otherwise it should be a value type variable.
        In that case, return the bound variable.
        """
        variable = self.__computation().resolve_variable(object_specifier)
        if not variable:
            return self.__context.resolve_object_specifier(object_specifier)
        elif variable.specifier is None:
            return variable.bound_variable
        return None


class Computation(Observable.Observable, Persistence.PersistentObject):
    """A computation on data and other inputs.

    Watches for changes to the sources and fires a needs_update_event
    when a new computation needs to occur.

    Call parse_expression first to establish the computation. Bind will be automatically called.

    Call bind to establish connections after reloading. Call unbind to release connections.

    Listen to needs_update_event and call evaluate in response to perform
    computation (on thread).

    The computation will listen to any bound items established in the bind method. When those
    items signal a change, the needs_update_event will be fired.

    The processing_id is used to specify a computation that may be updated with a different script
    in the future. For instance, the line profile processing via the UI will produce a somewhat
    complicated computation expression. By recording processing_id, if the computation expression
    evolves to a better version in the future, it can be replaced with the newer version by knowing
    that the intention of the original expression was a line profile from the UI.

    The processing_id is cleared if the user changes the script expression.
    """

    def __init__(self, expression: str=None):
        super().__init__()
        self.define_type("computation")
        self.define_property("original_expression", expression)
        self.define_property("error_text", changed=self.__error_changed)
        self.define_property("evaluate_error")
        self.define_property("label", changed=self.__label_changed)
        self.define_property("processing_id")  # see note above
        self.define_relationship("variables", variable_factory)
        self.__variable_changed_event_listeners = dict()
        self.__bound_items = dict()
        self.__bound_item_changed_event_listeners = dict()
        self.__bound_item_deleted_event_listeners = dict()
        self.__variable_property_changed_listener = dict()
        self.__evaluate_lock = threading.RLock()
        self.__data_and_metadata = None
        self.last_evaluate_data_time = 0
        self.needs_update = expression is not None
        self.needs_update_event = Event.Event()
        self.cascade_delete_event = Event.Event()
        self.computation_mutated_event = Event.Event()
        self.variable_inserted_event = Event.Event()
        self.variable_removed_event = Event.Event()
        self._evaluation_count_for_test = 0
        self.__needs_parse = True

    def read_from_dict(self, properties):
        super().read_from_dict(properties)

    def __error_changed(self, name, value):
        if self.error_text != value:
            self.notify_set_property(name, value)
            self.computation_mutated_event.fire()

    def __label_changed(self, name, value):
        self.notify_set_property(name, value)
        self.computation_mutated_event.fire()

    def add_variable(self, variable: ComputationVariable) -> None:
        count = self.item_count("variables")
        self.append_item("variables", variable)
        self.__bind_variable(variable)
        self.__parse_expression(self.expression)
        self.variable_inserted_event.fire(count, variable)
        self.computation_mutated_event.fire()
        self.__needs_parse = True
        self.needs_update = True
        self.needs_update_event.fire()

    def remove_variable(self, variable: ComputationVariable) -> None:
        self.__unbind_variable(variable)
        index = self.item_index("variables", variable)
        self.remove_item("variables", variable)
        self.__parse_expression(self.expression)
        self.variable_removed_event.fire(index, variable)
        self.computation_mutated_event.fire()

    def create_variable(self, name: str=None, value_type: str=None, value=None, value_default=None, value_min=None, value_max=None, control_type: str=None, specifier: dict=None, label: str=None) -> ComputationVariable:
        variable = ComputationVariable(name, value_type, value, value_default, value_min, value_max, control_type, specifier, label)
        self.add_variable(variable)
        return variable

    def create_object(self, name: str, object_specifier: dict, cascade_delete: bool=False, label: str=None) -> ComputationVariable:
        variable = ComputationVariable(name, specifier=object_specifier, label=label)
        self.add_variable(variable)
        variable.cascade_delete = cascade_delete
        return variable

    def resolve_variable(self, object_specifier: dict) -> ComputationVariable:
        uuid_str = object_specifier.get("uuid")
        uuid_ = Converter.UuidToStringConverter().convert_back(uuid_str) if uuid_str else None
        if uuid_:
            for variable in self.variables:
                if variable.uuid == uuid_:
                    return variable
        return None

    @property
    def expression(self) -> str:
        return self.original_expression

    @expression.setter
    def expression(self, value: str) -> None:
        if value != self.original_expression:
            self.__parse_expression(value)
            self.original_expression = value
            self.processing_id = None
            self.needs_update = True
            self.needs_update_event.fire()
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

    def __parse_expression(self, expression):
        if expression:
            computation_variable_map = dict()
            for variable in self.variables:
                variable_specifier = variable.variable_specifier
                if variable_specifier:
                    computation_variable_map[variable.name] = variable_specifier
            expression_lines = expression.split("\n")
            computation_context = self.__computation_context

            Computation.parse_names(expression)

            code_lines = []
            code_lines.append("import uuid")
            g = Context.context().g
            g["data_by_uuid"] = functools.partial(data_by_uuid, computation_context)
            g["region_by_uuid"] = functools.partial(region_by_uuid, computation_context)
            g["region_mask"] = region_mask
            l = dict()
            for variable_name, object_specifier in computation_variable_map.items():
                resolved_object = computation_context.resolve_object_specifier(object_specifier)
                g[variable_name] = resolved_object.value if resolved_object else None
            expression_lines = expression_lines[:-1] + ["result = {0}".format(expression_lines[-1]), ]
            code_lines.extend(expression_lines)
            code = "\n".join(code_lines)
            try:
                compiled = compile(code, "expr", "exec")
                exec(compiled, g, l)
                data_and_metadata, error_text = l["result"], None
            except Exception as e:
                # import sys, traceback
                # traceback.print_exc()
                # traceback.format_exception(*sys.exc_info())
                data_and_metadata, error_text = None, str(e)  # use this instead of giving user too much information from stack trace

            self.__data_and_metadata = data_and_metadata
            self.error_text = error_text
            self.__needs_parse = False

    def evaluate(self) -> DataAndMetadata.DataAndMetadata:
        """Evaluate the computation and return data and metadata."""
        self._evaluation_count_for_test += 1
        self.needs_update = False
        if self.__needs_parse:
            self.__parse_expression(self.expression)
        return self.__data_and_metadata

    def evaluate_data(self) -> DataAndMetadata.DataAndMetadata:
        try:
            data_and_metadata = self.evaluate()
            self.evaluate_error = None
            self.last_evaluate_data_time = time.perf_counter()
            return data_and_metadata
        except Exception as e:
            self.evaluate_error = str(e)

    def __bind_variable(self, variable: ComputationVariable) -> None:
        def needs_update():
            self.__needs_parse = True
            self.needs_update = True
            self.needs_update_event.fire()

        def deleted():
            if variable.cascade_delete:
                self.cascade_delete_event.fire()

        self.__variable_changed_event_listeners[variable.uuid] = variable.changed_event.listen(needs_update)

        variable_specifier = variable.variable_specifier
        if not variable_specifier:
            return

        bound_item = self.__computation_context.resolve_object_specifier(variable_specifier)

        self.__bound_items[variable.uuid] = bound_item

        self.__variable_property_changed_listener[variable.uuid] = variable.property_changed_event.listen(lambda k, v: needs_update())
        if bound_item:
            self.__bound_item_changed_event_listeners[variable.uuid] = bound_item.changed_event.listen(needs_update)
            self.__bound_item_deleted_event_listeners[variable.uuid] = bound_item.deleted_event.listen(deleted)

    def __unbind_variable(self, variable: ComputationVariable) -> None:
        self.__variable_changed_event_listeners[variable.uuid].close()
        del self.__variable_changed_event_listeners[variable.uuid]
        if variable.uuid in self.__bound_items:
            bound_item = self.__bound_items[variable.uuid]
            if bound_item:
                bound_item.close()
            del self.__bound_items[variable.uuid]
        if variable.uuid in self.__bound_item_changed_event_listeners:
            self.__bound_item_changed_event_listeners[variable.uuid].close()
            del self.__bound_item_changed_event_listeners[variable.uuid]
        if variable.uuid in self.__bound_item_deleted_event_listeners:
            self.__bound_item_deleted_event_listeners[variable.uuid].close()
            del self.__bound_item_deleted_event_listeners[variable.uuid]
        if variable.uuid in self.__variable_property_changed_listener:
            self.__variable_property_changed_listener[variable.uuid].close()
            del self.__variable_property_changed_listener[variable.uuid]

    def bind(self, context) -> None:
        """Bind a context to this computation.

        The context allows the computation to convert object specifiers to actual objects.
        """

        # make a computation context based on the enclosing context.
        self.__computation_context = ComputationContext(self, context)

        # normally I would think re-bind should not be valid; but for testing, the expression
        # is often evaluated and bound. it also needs to be bound a new data item is added to a document
        # model. so special case to see if it already exists. this may prove troublesome down the road.
        if len(self.__bound_items) == 0:  # check if already bound
            for variable in self.variables:
                self.__bind_variable(variable)

    def unbind(self):
        """Unlisten and close each bound item."""
        for variable in self.variables:
            self.__unbind_variable(variable)

    def _set_variable_value(self, variable_name, value):
        for variable in self.variables:
            if variable.name == variable_name:
                variable.value = value
