"""
    Provide symbolic math services.

    The goal is to provide a module (namespace) where users can be provided with variables representing
    data items (directly or indirectly via reference to workspace panels).

    DataNodes represent data items, operations, numpy arrays, and constants.
"""

# standard libraries
import ast
import threading
import time
import typing
import uuid
import weakref

# third party libraries

# local libraries
from nion.utils import Converter
from nion.utils import Event
from nion.utils import Observable
from nion.utils import Persistence


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

    def __property_changed(self, name, value):
        self.notify_property_changed(name)
        if name in ("specifier", "specifiers"):
            self.needs_rebind_event.fire()

    def bind(self, resolve_object_specifier):
        if self.specifier:
            self.bound_item = resolve_object_specifier(self.specifier)
        elif self.specifiers is not None:
            bound_items = [resolve_object_specifier(specifier) for specifier in self.specifiers]
            bound_items = [bound_item for bound_item in bound_items if bound_item is not None]
            self.bound_item = bound_items
        else:
            self.bound_item = None


class ComputationVariable(Observable.Observable, Persistence.PersistentObject):
    """Tracks a variable used in a computation.

    A variable has user visible name, a label used in the script, a value type.

    Scalar value types have a value, a default, and optional min and max values. The control type is used to
    specify the preferred UI control (e.g. checkbox vs. input field).

    Specifier value types have a specifier which can be resolved to a specific object.
    """
    def __init__(self, name: str=None, *, property_name: str=None, value_type: str=None, value=None, value_default=None, value_min=None, value_max=None, control_type: str=None, specifier: dict=None, label: str=None, secondary_specifier: dict=None):  # defaults are None for factory
        super().__init__()
        self.define_type("variable")
        self.define_property("name", name, changed=self.__property_changed)
        self.define_property("property_name", property_name, changed=self.__property_changed)
        self.define_property("label", label if label else name, changed=self.__property_changed)
        self.define_property("value_type", value_type, changed=self.__property_changed)
        self.define_property("value", value, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer)
        self.define_property("value_default", value_default, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer)
        self.define_property("value_min", value_min, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer)
        self.define_property("value_max", value_max, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer)
        self.define_property("specifier", specifier, changed=self.__property_changed)
        self.define_property("secondary_specifier", secondary_specifier, changed=self.__property_changed)
        self.define_property("control_type", control_type, changed=self.__property_changed)
        self.changed_event = Event.Event()
        self.variable_type_changed_event = Event.Event()
        self.needs_rebind_event = Event.Event()  # an event to be fired when the computation needs to rebind
        self.needs_rebuild_event = Event.Event()  # an event to be fired when the UI needs a rebuild
        self.__bound_item = None
        self.__bound_item_changed_event_listener = None

    def __repr__(self):
        return "{} ({} {} {} {} {})".format(super().__repr__(), self.name, self.label, self.value, self.specifier, self.secondary_specifier)

    def read_from_dict(self, properties: dict) -> None:
        # ensure that value_type is read first
        value_type_property = self._get_persistent_property("value_type")
        value_type_property.read_from_dict(properties)
        super().read_from_dict(properties)

    def write_to_dict(self) -> dict:
        return super().write_to_dict()

    def save_properties(self):
        return self.value, self.specifier, self.secondary_specifier

    def restore_properties(self, properties):
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
    def bound_variable(self):
        """Return an object with a value property and a changed_event.

        The value property returns the value of the variable. The changed_event is fired
        whenever the value changes.
        """
        class BoundVariable:
            def __init__(self, variable):
                self.__variable = variable
                self.changed_event = Event.Event()
                def property_changed(key):
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

    @property
    def bound_item(self):
        return self.__bound_item

    @bound_item.setter
    def bound_item(self, value):
        self.__bound_item = value
        if self.__bound_item:
            def fire_changed_event():
                self.changed_event.fire()
            self.__bound_item_changed_event_listener = self.__bound_item.changed_event.listen(fire_changed_event)
        else:
            if self.__bound_item_changed_event_listener:
                self.__bound_item_changed_event_listener.close()
                self.__bound_item_changed_event_listener = None
            if self.__bound_item:
                self.__bound_item.close()

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
                specifier["type"] = "data_item"
                if value_type in ("data", "display_data"):
                    specifier["property"] = value_type
                else:
                    specifier.pop("property", None)
                self.specifier = specifier
                self.secondary_specifier = self.secondary_specifier or {"version": 1}
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


class ComputationContext:
    def __init__(self, computation, context):
        self.__computation = weakref.ref(computation)
        self.__context = context

    def resolve_object_specifier(self, object_specifier, secondary_specifier=None, property_name=None):
        """Resolve the object specifier.

        First lookup the object specifier in the enclosing computation. If it's not found,
        then lookup in the computation's context. Otherwise it should be a value type variable.
        In that case, return the bound variable.
        """
        variable = self.__computation().resolve_variable(object_specifier)
        if not variable:
            return self.__context.resolve_object_specifier(object_specifier, secondary_specifier, property_name)
        elif variable.specifier is None:
            return variable.bound_variable
        return None


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
        self._about_to_be_removed = False
        self._closed = False
        self.define_type("computation")
        self.define_property("source_uuid", converter=Converter.UuidToStringConverter())
        self.define_property("original_expression", expression)
        self.define_property("error_text", changed=self.__error_changed)
        self.define_property("label", changed=self.__label_changed)
        self.define_property("processing_id")  # see note above
        self.define_relationship("variables", variable_factory)
        self.define_relationship("results", result_factory)
        self.__source = None
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
        self.target_output = None
        self._inputs = set()  # used by document model for tracking dependencies
        self._outputs = set()

    def close(self):
        assert self._about_to_be_removed
        assert not self._closed
        self._closed = True
        self.__container_weak_ref = None

    @property
    def container(self):
        return self.__container_weak_ref()

    def about_to_be_inserted(self, container):
        assert self.__container_weak_ref is None
        self.__container_weak_ref = weakref.ref(container)

    def about_to_be_removed(self):
        # called before close and before item is removed from its container
        self.about_to_be_removed_event.fire()
        assert not self._about_to_be_removed
        self._about_to_be_removed = True
        self.__container_weak_ref = None

    def insert_model_item(self, container, name, before_index, item):
        if self.__container_weak_ref:
            self.container.insert_model_item(container, name, before_index, item)
        else:
            container.insert_item(name, before_index, item)

    def remove_model_item(self, container, name, item, *, safe: bool=False) -> typing.Optional[typing.Sequence]:
        if self.__container_weak_ref:
            return self.container.remove_model_item(container, name, item, safe=safe)
        else:
            container.remove_item(name, item)
            return None

    def read_from_dict(self, properties):
        super().read_from_dict(properties)

    @property
    def source(self):
        return self.__source

    @source.setter
    def source(self, source):
        self.__source = source
        self.source_uuid = source.uuid if source else None

    def persistent_object_context_changed(self):
        super().persistent_object_context_changed()

        def register():
            if self.__source is not None:
                pass

        def source_registered(source):
            self.__source = source
            register()

        def unregistered(source=None):
            pass

        if self.persistent_object_context:
            self.persistent_object_context.subscribe(self.source_uuid, source_registered, unregistered)
        else:
            unregistered()

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

    def create_input(self, name: str, object_specifier: dict, property_name: str, label: str=None) -> ComputationVariable:
        variable = ComputationVariable(name, specifier=object_specifier, property_name=property_name, label=label)
        self.add_variable(variable)
        return variable

    def create_object(self, name: str, object_specifier: dict, label: str=None, secondary_specifier: dict=None) -> ComputationVariable:
        variable = ComputationVariable(name, specifier=object_specifier, label=label, secondary_specifier=secondary_specifier)
        self.add_variable(variable)
        return variable

    def create_result(self, name: str=None, object_specifier: dict=None, specifiers: typing.Sequence[dict]=None, label: str=None) -> ComputationOutput:
        result = ComputationOutput(name, specifier=object_specifier, specifiers=specifiers, label=label)
        self.append_item("results", result)
        self.__bind_result(result)
        self.computation_mutated_event.fire()
        return result

    def resolve_variable(self, object_specifier: dict) -> typing.Optional[ComputationVariable]:
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
                kwargs[
                    variable.name] = api_object if api_object else resolved_object  # use api only if resolved_object is an api style object
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
            self.__unbind_variable(variable)
            self.__bind_variable(variable)

        self.__variable_needs_rebind_event_listeners[variable.uuid] = variable.needs_rebind_event.listen(rebind)

        variable_specifier = variable.variable_specifier
        if not variable_specifier:
            return

        variable.bound_item = self.__computation_context.resolve_object_specifier(variable_specifier, variable.secondary_specifier, variable.property_name)

    def __unbind_variable(self, variable: ComputationVariable) -> None:
        self.__variable_changed_event_listeners[variable.uuid].close()
        del self.__variable_changed_event_listeners[variable.uuid]
        self.__variable_needs_rebind_event_listeners[variable.uuid].close()
        del self.__variable_needs_rebind_event_listeners[variable.uuid]
        variable.bound_item = None

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

        result.bind(self.__computation_context.resolve_object_specifier)

    def __unbind_result(self, result: ComputationOutput) -> None:
        self.__result_needs_rebind_event_listeners[result.uuid].close()
        del self.__result_needs_rebind_event_listeners[result.uuid]
        result.bound_item = None

    def bind(self, context) -> None:
        """Bind a context to this computation.

        The context allows the computation to convert object specifiers to actual objects.
        """

        # make a computation context based on the enclosing context.
        self.__computation_context = ComputationContext(self, context)

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

    def _get_variable(self, variable_name):
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

    def get_referenced_object(self, name: str):
        for result in self.results:
            if result.name == name:
                if isinstance(result.bound_item, list):
                    return [bound_item.value for bound_item in result.bound_item]
                if result.bound_item:
                    return result.bound_item.value
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
