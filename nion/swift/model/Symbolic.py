"""
    Provide symbolic math services.

    The goal is to provide a module (namespace) where users can be provided with variables representing
    data items (directly or indirectly via reference to workspace panels).

    DataNodes represent data items, operations, numpy arrays, and constants.
"""

# standard libraries
import copy
import functools
import threading
import uuid

# third party libraries
import numpy

# local libraries
from nion.data import Context
from nion.data import DataAndMetadata
from nion.ui import Event
from nion.ui import Observable
from nion.ui import Persistence


def data_by_uuid(context, data_item_uuid):
    return context.resolve_object_specifier(context.get_data_item_specifier(data_item_uuid, "data")).value


def region_by_uuid(context, region_uuid):
    return context.resolve_object_specifier(context.get_region_specifier(region_uuid)).value


def parse_expression(expression_lines, variable_map, context) -> DataAndMetadata.DataAndMetadata:
    code_lines = []
    code_lines.append("import uuid")
    g = Context.context().g
    g["data_by_uuid"] = functools.partial(data_by_uuid, context)
    g["region_by_uuid"] = functools.partial(region_by_uuid, context)
    l = dict()
    for variable_name, object_specifier in variable_map.items():
        if object_specifier["type"] == "data_item":
            g[variable_name] = context.resolve_object_specifier(object_specifier).value
        elif object_specifier["type"] == "region":
            g[variable_name] = context.resolve_object_specifier(object_specifier).value
        elif object_specifier["type"] == "variable":
            g[variable_name] = context.resolve_object_specifier(object_specifier).value
        else:
            pass # reference_node = ReferenceDataNode(object_specifier=object_specifier)
    expression_lines = expression_lines[:-1] + ["result = {0}".format(expression_lines[-1]), ]
    code_lines.extend(expression_lines)
    code = "\n".join(code_lines)
    try:
        exec(code, g, l)
    except Exception as e:
        import traceback
        traceback.print_stack()
        print(e)
        return None, str(e)
    return l["result"], None


class ComputationVariable(Observable.Observable, Persistence.PersistentObject):
    def __init__(self, name: str=None, value_type: str=None, value=None, value_default=None, value_min=None, value_max=None, control_type: str=None, specifier: dict=None):  # defaults are None for factory
        super(ComputationVariable, self).__init__()
        self.define_type("variable")
        self.define_property("name", name, changed=self.__property_changed)
        self.define_property("label", name, changed=self.__property_changed)
        self.define_property("value_type", value_type, changed=self.__property_changed)
        self.define_property("value", value, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer)
        self.define_property("value_default", value_default, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer)
        self.define_property("value_min", value_min, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer)
        self.define_property("value_max", value_max, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer)
        self.define_property("specifier", specifier, changed=self.__property_changed)
        self.define_property("control_type", control_type, changed=self.__property_changed)
        self.variable_type_changed_event = Event.Event()

    def read_from_dict(self, properties: dict) -> None:
        # ensure that value_type is read first
        value_type_property = self._get_persistent_property("value_type")
        value_type_property.read_from_dict(properties)
        super(ComputationVariable, self).read_from_dict(properties)

    def write_to_dict(self) -> dict:
        return super(ComputationVariable, self).write_to_dict()

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
        if self.value_type is not None:
            return {"type": "variable", "version": 1, "uuid": str(self.uuid)}
        else:
            return self.specifier

    @property
    def bound_variable(self):
        class BoundVariable(object):
            def __init__(self, variable):
                self.__variable = variable
                self.changed_event = Event.Event()
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

    def control_type_default(self, value_type: str) -> None:
        mapping = {"boolean": "checkbox", "integral": "slider", "real": "field", "complex": "field", "string": "field"}
        return mapping.get(value_type)

    @property
    def variable_type(self) -> str:
        if self.value_type is not None:
            return self.value_type
        elif self.specifier is not None:
            return self.specifier.get("type")
        return None

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
            elif value_type in ("data_item", "region"):
                self.value_type = None
                self.control_type = None
                self.value_default = None
                self.value_min = None
                self.value_max = None
                self.specifier = {"type": value_type, "version": 1}
            self.variable_type_changed_event.fire()

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


class ComputationContext(object):
    def __init__(self, computation, context):
        self.__computation = computation
        self.__context = context

    def get_data_item_specifier(self, data_item_uuid, property_name: str=None):
        """Supports data item lookup by uuid."""
        return self.__context.get_object_specifier(self.__context.get_data_item_by_uuid(data_item_uuid), property_name)

    def get_region_specifier(self, region_uuid):
        """Supports region lookup by uuid."""
        for data_item in self.__context.data_items:
            for data_source in data_item.data_sources:
                for region in data_source.regions:
                    if region.uuid == region_uuid:
                        return self.__context.get_object_specifier(region)
        return None

    def resolve_object_specifier(self, object_specifier):
        """Resolve the object specifier, returning a bound variable.

        Ask the computation for the variable associated with the object specifier. If it doesn't exist, let the
        enclosing context handle it. Otherwise, check to see if the variable directly includes a value (i.e. has no
        specifier). If so, let the variable return the bound variable directly. Otherwise (again) let the enclosing
        context resolve, but use the specifier in the variable.

        Structuring this method this way allows the variable to provide a second level of indirection. The computation
        can store variable specifiers only. The variable specifiers can hold values directly or specifiers to the
        enclosing context. This isolates the computation further from the enclosing context.
        """
        variable = self.__computation.resolve_variable(object_specifier)
        if not variable:
            return self.__context.resolve_object_specifier(object_specifier)
        elif variable.specifier is None:
            return variable.bound_variable
        else:
            # BoundVariable is used here to watch for changes to the variable in addition to watching for changes
            # to the context of the variable. Fire changed_event for either type of change.
            class BoundVariable:
                def __init__(self, variable, context):
                    self.__bound_object_changed_listener = None
                    self.__variable = variable
                    self.changed_event = Event.Event()
                    def update_bound_object():
                        if self.__bound_object_changed_listener:
                            self.__bound_object_changed_listener.close()
                            self.__bound_object_changed_listener = None
                        self.__bound_object = context.resolve_object_specifier(self.__variable.specifier)
                        if self.__bound_object:
                            def bound_object_changed():
                                self.changed_event.fire()
                            self.__bound_object_changed_listener = self.__bound_object.changed_event.listen(bound_object_changed)
                    def property_changed(key, value):
                        if key == "specifier":
                            update_bound_object()
                            self.changed_event.fire()
                    self.__variable_property_changed_listener = variable.property_changed_event.listen(property_changed)
                    update_bound_object()
                def close(self):
                    self.__variable_property_changed_listener.close()
                    self.__variable_property_changed_listener = None
                    if self.__bound_object_changed_listener:
                        self.__bound_object_changed_listener.close()
                        self.__bound_object_changed_listener = None
            return BoundVariable(variable, self.__context)


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
    """

    def __init__(self):
        super(Computation, self).__init__()
        self.define_type("computation")
        self.define_property("original_expression")
        self.define_property("error_text")
        self.define_property("label", changed=self.__label_changed)
        self.define_relationship("variables", variable_factory)
        self.__bound_items = dict()
        self.__bound_item_listeners = dict()
        self.__evaluate_lock = threading.RLock()
        self.__evaluating = False
        self.__data_and_metadata = None
        self.needs_update = False
        self.needs_update_event = Event.Event()
        self.computation_mutated_event = Event.Event()
        self.variable_inserted_event = Event.Event()
        self.variable_removed_event = Event.Event()
        self._evaluation_count_for_test = 0

    def read_from_dict(self, properties):
        super(Computation, self).read_from_dict(properties)

    def __label_changed(self, name, value):
        self.notify_set_property(name, value)
        self.computation_mutated_event.fire()

    def add_variable(self, variable: ComputationVariable) -> None:
        count = self.item_count("variables")
        self.append_item("variables", variable)
        self.variable_inserted_event.fire(count, variable)
        self.computation_mutated_event.fire()

    def remove_variable(self, variable: ComputationVariable) -> None:
        index = self.item_index("variables", variable)
        self.remove_item("variables", variable)
        self.variable_removed_event.fire(index, variable)
        self.computation_mutated_event.fire()

    def create_variable(self, name: str=None, value_type: str=None, value=None, value_default=None, value_min=None, value_max=None, control_type: str=None, specifier: dict=None) -> ComputationVariable:
        variable = ComputationVariable(name, value_type, value, value_default, value_min, value_max, control_type, specifier)
        self.add_variable(variable)
        return variable

    def create_object(self, name: str, object_specifier: dict) -> ComputationVariable:
        variable = ComputationVariable(name, specifier=object_specifier)
        self.add_variable(variable)
        return variable

    def resolve_variable(self, object_specifier: dict) -> ComputationVariable:
        uuid_str = object_specifier.get("uuid")
        uuid_ = uuid.UUID(uuid_str) if uuid_str else None
        if uuid_:
            for variable in self.variables:
                if variable.uuid == uuid_:
                    return variable
        return None

    def parse_expression(self, context, expression, variable_map):
        """Parse the expression."""
        self.unbind()
        old_error_text = self.error_text
        self.original_expression = expression
        computation_context = ComputationContext(self, context)
        computation_variable_map = copy.copy(variable_map)
        for variable in self.variables:
            computation_variable_map[variable.name] = variable.variable_specifier
        self.__data_and_metadata, self.error_text = parse_expression(expression.split("\n"), computation_variable_map, computation_context)
        if self.__data_and_metadata:
            self.bind(context)
        if self.__data_and_metadata or old_error_text != self.error_text:
            self.needs_update = True
            self.needs_update_event.fire()
            self.computation_mutated_event.fire()

    def reparse(self, context, variable_map):
        self.parse_expression(context, self.original_expression, variable_map)

    def begin_evaluate(self) -> bool:
        print("BEGIN {}".format(self))
        """Begin an evaluation transaction. Returns true if ok to proceed."""
        with self.__evaluate_lock:
            evaluating = self.__evaluating
            self.__evaluating = True
            return not evaluating

    def end_evaluate(self) -> None:
        print("END {}".format(self))
        """End an evaluation transaction. Not required if begin_evaluation returns False."""
        self.__evaluating = False

    def evaluate(self) -> DataAndMetadata.DataAndMetadata:
        print("EVAL {}".format(self))
        """Evaluate the computation and return data and metadata."""
        self._evaluation_count_for_test += 1
        self.needs_update = False
        return self.__data_and_metadata

    def bind(self, context) -> None:
        print("BIND {}".format(self))
        """Ask the data node for all bound items, then watch each for changes."""

        # make a computation context based on the enclosing context.
        computation_context = ComputationContext(self, context)

        # self.parse_expression(context, self.original_expression, dict())

        # normally I would think re-bind should not be valid; but for testing, the expression
        # is often evaluated and bound. it also needs to be bound a new data item is added to a document
        # model. so special case to see if it already exists. this may prove troublesome down the road.
        if len(self.__bound_items) == 0:  # check if already bound
            if self.__data_and_metadata:  # ensure not error condition

                def needs_update():
                    self.needs_update = True
                    self.needs_update_event.fire()

                for bound_item_uuid, bound_item in self.__bound_items.items():
                    self.__bound_item_listeners[bound_item_uuid] = bound_item.changed_event.listen(needs_update)

    def unbind(self):
        """Unlisten and close each bound item."""
        for bound_item, bound_item_listener in zip(self.__bound_items.values(), self.__bound_item_listeners.values()):
            bound_item.close()
            bound_item_listener.close()
        self.__bound_items = dict()
        self.__bound_item_listeners = dict()
