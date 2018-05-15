# standard libraries
import copy
import functools
import gettext
import json
import operator
import random
import string
import uuid
import weakref

# third party libraries
# None

# local libraries
from nion.swift import DataItemThumbnailWidget
from nion.swift import Undo
from nion.swift.model import DataItem
from nion.swift.model import Symbolic
from nion.ui import CanvasItem
from nion.ui import Dialog
from nion.utils import Binding
from nion.utils import Converter
from nion.utils import Event
from nion.utils import Geometry

_ = gettext.gettext


class ComputationModel:
    """Represents a computation. Tracks a display specifier for changes to it and its computation content.

    Provides read/write access to the computation_text via the property.

    Provides a computation_text_changed event, always fired on UI thread.
    """

    def __init__(self, document_controller):
        self.__weak_document_controller = weakref.ref(document_controller)
        self.__display_specifier = DataItem.DisplaySpecifier()
        self.__set_display_specifier(DataItem.DisplaySpecifier())
        self.__computation_changed_or_mutated_event_listener = None
        self.__computation_variable_inserted_event_listener = None
        self.__computation_variable_removed_event_listener = None
        self.__computation_property_changed_event_listener = None
        self.__computation_label = None
        self.__computation_text = None
        self.__error_text = None
        self.__object_property_changed_event_listeners = dict()
        self.__variable_property_changed_event_listeners = dict()
        self.computation_label_changed_event = Event.Event()
        self.computation_text_changed_event = Event.Event()
        self.error_text_changed_event = Event.Event()
        self.variable_inserted_event = Event.Event()
        self.variable_removed_event = Event.Event()
        self.variable_property_changed_event = Event.Event()

    def close(self):
        self.__set_display_specifier(DataItem.DisplaySpecifier())

    @property
    def document_controller(self):
        return self.__weak_document_controller()

    @property
    def display_specifier(self):
        return self.__display_specifier

    @property
    def __computation(self):
        if self.__display_specifier.data_item:
            return self.document_controller.document_model.get_data_item_computation(self.__display_specifier.data_item)
        return None

    @property
    def computation(self):
        return self.__computation

    def set_data_item(self, data_item):
        self.__set_display_specifier(DataItem.DisplaySpecifier.from_data_item(data_item))

    class AddVariableCommand(Undo.UndoableCommand):

        def __init__(self, document_model, computation: Symbolic.Computation, name: str=None, value_type: str=None, value=None, value_default=None, value_min=None, value_max=None, control_type: str=None, specifier: dict=None, label: str=None):
            super().__init__(_("Add Computation Variable"))
            self.__document_model = document_model
            self.__computation_uuid = computation.uuid
            self.__name = name
            self.__value_type = value_type
            self.__value = value
            self.__value_default = value_default
            self.__value_min = value_min
            self.__value_max = value_max
            self.__control_type = control_type
            self.__specifier = specifier
            self.__label = label
            self.__variable_index = None
            self.initialize()

        def close(self):
            self.__computation_uuid = None
            self.__name = None
            self.__value_type = None
            self.__value = None
            self.__value_default = None
            self.__value_min = None
            self.__value_max = None
            self.__control_type = None
            self.__specifier = None
            self.__label = None
            self.__variable = None
            super().close()

        def perform(self):
            computation = self.__document_model.get_computation_by_uuid(self.__computation_uuid)
            variable = computation.create_variable(self.__name, self.__value_type, self.__value, self.__value_default, self.__value_min, self.__value_max, self.__control_type, self.__specifier, self.__label)
            self.__variable_index = computation.variables.index(variable)

        def _get_modified_state(self):
            computation = self.__document_model.get_computation_by_uuid(self.__computation_uuid)
            return computation.modified_state

        def _set_modified_state(self, modified_state) -> None:
            computation = self.__document_model.get_computation_by_uuid(self.__computation_uuid)
            computation.modified_state = modified_state

        def _undo(self):
            computation = self.__document_model.get_computation_by_uuid(self.__computation_uuid)
            variable = computation.variables[self.__variable_index]
            computation.remove_variable(variable)

        def _redo(self):
            self.perform()

    class RemoveVariableCommand(Undo.UndoableCommand):

        def __init__(self, document_model, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable):
            super().__init__(_("Remove Computation Variable"))
            self.__document_model = document_model
            self.__computation_uuid = computation.uuid
            self.__variable_index = computation.variables.index(variable)
            self.__variable_dict = variable.write_to_dict()
            self.initialize()

        def close(self):
            self.__computation_uuid = None
            self.__variable_index = None
            self.__variable_dict = None
            super().close()

        def perform(self):
            computation = self.__document_model.get_computation_by_uuid(self.__computation_uuid)
            variable = computation.variables[self.__variable_index]
            computation.remove_variable(variable)

        def _get_modified_state(self):
            computation = self.__document_model.get_computation_by_uuid(self.__computation_uuid)
            return computation.modified_state

        def _set_modified_state(self, modified_state) -> None:
            computation = self.__document_model.get_computation_by_uuid(self.__computation_uuid)
            computation.modified_state = modified_state

        def _undo(self):
            computation = self.__document_model.get_computation_by_uuid(self.__computation_uuid)
            variable = Symbolic.ComputationVariable()
            variable.read_from_dict(self.__variable_dict)
            computation.insert_variable(self.__variable_index, variable)

        def _redo(self):
            computation = self.__document_model.get_computation_by_uuid(self.__computation_uuid)
            computation.remove_variable(computation.variables[self.__variable_index])

    class CreateComputationCommand(Undo.UndoableCommand):

        def __init__(self, document_model, data_item):
            super().__init__(_("Create Computation"))
            self.__document_model = document_model
            self.__data_item_uuid = data_item.uuid
            self.__computation_uuid = None

        def close(self):
            self.__document_model = None
            self.__data_item_uuid = None
            self.__computation_uuid = None
            super().close()

        @property
        def _computation(self) -> Symbolic.Computation:
            return self.__document_model.create_computation()

        def perform(self):
            data_item = self.__document_model.get_data_item_by_uuid(self.__data_item_uuid)
            computation = self.__document_model.create_computation()
            self.__document_model.set_data_item_computation(data_item, computation)
            self.__computation_uuid = computation.uuid

        def _get_modified_state(self):
            return self.__document_model.modified_state

        def _set_modified_state(self, modified_state) -> None:
            self.__document_model.modified_state = modified_state

        def _undo(self):
            data_item = self.__document_model.get_data_item_by_uuid(self.__data_item_uuid)
            self.__document_model.set_data_item_computation(data_item, None)

    class ChangeComputationCommand(Undo.UndoableCommand):

        def __init__(self, document_model, computation: Symbolic.Computation, *, title: str=None, command_id: str=None, is_mergeable: bool=False, **kwargs):
            super().__init__(title if title else _("Change Computation"), command_id=command_id, is_mergeable=is_mergeable)
            self.__document_model = document_model
            self.__computation_uuid = computation.uuid
            self.__properties = {key: getattr(computation, key) for key in kwargs.keys()}
            self.__value_dict = kwargs
            self.initialize()

        def close(self):
            self.__properties = None
            self.__computation_uuid = None
            self.__properties = None
            self.__value_dict = None
            super().close()

        def perform(self):
            computation = self.__document_model.get_computation_by_uuid(self.__computation_uuid)
            for key, value in self.__value_dict.items():
                setattr(computation, key, value)

        def _get_modified_state(self):
            computation = self.__document_model.get_computation_by_uuid(self.__computation_uuid)
            return computation.modified_state

        def _set_modified_state(self, modified_state) -> None:
            computation = self.__document_model.get_computation_by_uuid(self.__computation_uuid)
            computation.modified_state = modified_state

        def _undo(self):
            computation = self.__document_model.get_computation_by_uuid(self.__computation_uuid)
            properties = self.__properties
            self.__properties = computation.write_to_dict()
            computation.read_from_dict(properties)

        def can_merge(self, command: Undo.UndoableCommand) -> bool:
            return isinstance(command, ComputationModel.ChangeComputationCommand) and self.command_id and self.command_id == command.command_id and self.__computation_uuid == command.__computation_uuid

    class ChangeVariableCommand(Undo.UndoableCommand):

        def __init__(self, document_model, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable, *, title: str=None, command_id: str=None, is_mergeable: bool=False, **kwargs):
            super().__init__(title if title else _("Change Computation Variable"), command_id=command_id, is_mergeable=is_mergeable)
            self.__document_model = document_model
            self.__computation_uuid = computation.uuid
            self.__variable_index = computation.variables.index(variable)
            self.__property_keys = kwargs.keys()
            self.__properties = copy.deepcopy(kwargs)
            self.initialize()

        def close(self):
            self.__properties = None
            self.__computation_uuid = None
            self.__properties = None
            self.__property_keys = None
            super().close()

        def perform(self):
            computation = self.__document_model.get_computation_by_uuid(self.__computation_uuid)
            variable = computation.variables[self.__variable_index]
            properties = self.__properties
            self.__properties = {key: getattr(variable, key) for key in self.__property_keys}
            for key, value in properties.items():
                setattr(variable, key, value)

        def _get_modified_state(self):
            computation = self.__document_model.get_computation_by_uuid(self.__computation_uuid)
            return computation.modified_state

        def _set_modified_state(self, modified_state) -> None:
            computation = self.__document_model.get_computation_by_uuid(self.__computation_uuid)
            computation.modified_state = modified_state

        def _undo(self):
            computation = self.__document_model.get_computation_by_uuid(self.__computation_uuid)
            variable = computation.variables[self.__variable_index]
            properties = self.__properties
            self.__properties = {key: getattr(variable, key) for key in self.__property_keys}
            for key, value in properties.items():
                setattr(variable, key, value)

        def can_merge(self, command: Undo.UndoableCommand) -> bool:
            return isinstance(command, ComputationModel.ChangeVariableCommand) and self.command_id and self.command_id == command.command_id and self.__computation_uuid == command.__computation_uuid and self.__variable_index == command.__variable_index

    def add_variable(self, name: str=None, value_type: str=None, value=None, value_default=None, value_min=None, value_max=None, control_type: str=None, specifier: dict=None, label: str=None) -> None:
        computation = self.__computation
        if computation:
            command = ComputationModel.AddVariableCommand(self.document_controller.document_model, computation, name, value_type, value, value_default, value_min, value_max, control_type, specifier, label)
            command.perform()
            self.document_controller.push_undo_command(command)

    def remove_variable(self, variable: Symbolic.ComputationVariable) -> None:
        computation = self.__computation
        if computation:
            command = ComputationModel.RemoveVariableCommand(self.document_controller.document_model, computation, variable)
            command.perform()
            self.document_controller.push_undo_command(command)

    @property
    def computation_label(self):
        return self.__computation_label

    @computation_label.setter
    def computation_label(self, label):
        data_item = self.__display_specifier.data_item
        if data_item:
            computation = self.document_controller.document_model.get_data_item_computation(data_item)
            if not computation:
                command = ComputationModel.CreateComputationCommand(self.document_controller.document_model, data_item)
                command.perform()
                self.document_controller.push_undo_command(command)
                computation = command._computation
            command = ComputationModel.ChangeComputationCommand(self.document_controller.document_model, computation, command_id="computation_change_label", is_mergeable=True, label=label)
            command.perform()
            self.document_controller.push_undo_command(command)

    @property
    def computation_text(self):
        return self.__computation_text

    @computation_text.setter
    def computation_text(self, computation_text):
        data_item = self.__display_specifier.data_item
        if data_item:
            computation = self.document_controller.document_model.get_data_item_computation(data_item)
            if not computation:
                command = ComputationModel.CreateComputationCommand(self.document_controller.document_model, data_item)
                command.perform()
                self.document_controller.push_undo_command(command)
                computation = command._computation
            command = ComputationModel.ChangeComputationCommand(self.document_controller.document_model, computation, command_id="computation_change_label", is_mergeable=True, expression=computation_text)
            command.perform()
            self.document_controller.push_undo_command(command)

    @property
    def error_text(self):
        return self.__error_text

    def __update_computation_label(self, computation_label):
        if self.__computation_label != computation_label:
            self.__computation_label = computation_label
            self.computation_label_changed_event.fire(self.__computation_label)

    def __update_computation_text(self, computation_text):
        if self.__computation_text != computation_text:
            self.__computation_text = computation_text
            self.computation_text_changed_event.fire(self.__computation_text)

    def __update_error_text(self, error_text):
        if self.__error_text != error_text:
            self.__error_text = error_text
            self.error_text_changed_event.fire(self.__error_text)

    def clear(self):
        document_model = self.document_controller.document_model
        document_model.set_data_item_computation(self.__display_specifier.data_item, None)

    def __update_computation_display(self) -> None:
        def update_computation_display():
            label = None
            expression = None
            error_text = None
            computation = self.__computation
            if computation:
                error_text = computation.error_text
                expression = computation.expression
                label = computation.label
            self.__update_computation_label(label)
            self.__update_computation_text(expression)
            self.__update_error_text(error_text)
        self.document_controller.queue_task(update_computation_display)

    def __variable_inserted(self, index: int, variable: Symbolic.ComputationVariable) -> None:
        self.variable_inserted_event.fire(index, variable)
        def handle_property_changed(key: str) -> None:
            self.__update_computation_display()
            self.variable_property_changed_event.fire(variable)
        self.__variable_property_changed_event_listeners[variable.uuid] = variable.property_changed_event.listen(handle_property_changed)

    def __variable_removed(self, index: int, variable: Symbolic.ComputationVariable) -> None:
        self.variable_removed_event.fire(index, variable)
        self.__variable_property_changed_event_listeners[variable.uuid].close()
        del self.__variable_property_changed_event_listeners[variable.uuid]

    # not thread safe
    def __set_display_specifier(self, display_specifier):
        if self.__display_specifier != display_specifier:
            if self.__computation_changed_or_mutated_event_listener:
                self.__computation_changed_or_mutated_event_listener.close()
                self.__computation_changed_or_mutated_event_listener = None
            if self.__computation_variable_inserted_event_listener:
                self.__computation_variable_inserted_event_listener.close()
                self.__computation_variable_inserted_event_listener = None
            if self.__computation_variable_removed_event_listener:
                self.__computation_variable_removed_event_listener.close()
                self.__computation_variable_removed_event_listener = None
            if self.__computation_property_changed_event_listener:
                self.__computation_property_changed_event_listener.close()
                self.__computation_property_changed_event_listener = None
            computation = self.__computation
            if computation:
                for index, variable in enumerate(computation.variables):
                    self.__variable_removed(0, variable)
            self.__display_specifier = copy.copy(display_specifier)
            computation = self.__computation
            if computation:
                document_model = self.document_controller.document_model
                def computation_updated(data_item, computation):
                    if data_item == self.__display_specifier.data_item:
                        self.__update_computation_display()
                def property_changed(property):
                    if property == "error_text":
                        self.__update_computation_display()
                self.__computation_changed_or_mutated_event_listener = document_model.computation_updated_event.listen(computation_updated)
                self.__computation_variable_inserted_event_listener = computation.variable_inserted_event.listen(self.__variable_inserted)
                self.__computation_variable_removed_event_listener = computation.variable_removed_event.listen(self.__variable_removed)
                self.__computation_property_changed_event_listener = computation.property_changed_event.listen(property_changed)
            self.__update_computation_display()
            if computation:
                for index, variable in enumerate(computation.variables):
                    self.__variable_inserted(index, variable)


class ChangeVariableBinding(Binding.PropertyBinding):
    def __init__(self, document_controller, computation, variable, property_name: str, converter=None, fallback=None):
        super().__init__(variable, property_name, converter=converter, fallback=fallback)
        self.__property_name = property_name
        self.__old_source_setter = self.source_setter

        def set_value(value):
            if value != getattr(variable, property_name):
                command = ComputationModel.ChangeVariableCommand(document_controller.document_model, computation, self.source, **{self.__property_name: value})
                command.perform()
                document_controller.push_undo_command(command)

        self.source_setter = set_value


class ComputationPanelSection:

    def __init__(self, document_controller, computation, variable, on_remove, queue_task_fn):
        ui = document_controller.ui

        self.variable = variable

        section_widget = ui.create_column_widget()
        section_title_row = ui.create_row_widget()

        twist_down_canvas_item = CanvasItem.TwistDownCanvasItem()
        twist_down_canvas_widget = ui.create_canvas_widget(properties={"height": 20, "width": 20})
        twist_down_canvas_widget.canvas_item.add_canvas_item(twist_down_canvas_item)
        section_title_row.add(twist_down_canvas_widget)
        twist_down_label_widget = ui.create_label_widget(variable.name, properties={"stylesheet": "font-weight: bold"})
        twist_down_label_widget.bind_text(Binding.PropertyBinding(variable, "name"))
        section_title_row.add(twist_down_label_widget)
        section_title_row.add_stretch()
        section_widget.add(section_title_row)

        # boolean, integral, real, data item, region

        def make_label_row(ui, label):
            label_row = ui.create_row_widget()
            label_row.add_spacing(8)
            label_row.add(ui.create_label_widget(label))
            label_row.add_stretch()
            return label_row

        def make_name_type_row(ui, variable: Symbolic.ComputationVariable, on_change_type_fn, on_remove_fn):
            name_text_edit = ui.create_line_edit_widget()
            name_text_edit.bind_text(ChangeVariableBinding(document_controller, computation, variable, "name"))

            type_items = [("boolean", _("Boolean")), ("integral", _("Integer")), ("real", _("Real")), ("data_item", _("Data Item")), ("region", _("Region"))]
            type_combo_box = ui.create_combo_box_widget(items=type_items, item_getter=operator.itemgetter(1))

            remove_button = ui.create_push_button_widget(_("X"))

            name_type_row = ui.create_row_widget()
            name_type_row.add_spacing(8)
            name_type_row.add(name_text_edit)
            name_type_row.add_spacing(8)
            name_type_row.add(type_combo_box)
            name_type_row.add_spacing(8)
            name_type_row.add(remove_button)
            name_type_row.add_stretch()

            variable_type = variable.variable_type
            type_combo_box.current_item = next((i for i in type_items if i[0] == variable_type), None)
            type_combo_box.on_current_item_changed = lambda item: on_change_type_fn(item[0])
            remove_button.on_clicked = on_remove_fn

            return name_type_row

        def make_boolean_row(ui, variable: Symbolic.ComputationVariable, on_change_type_fn, on_remove_fn):
            name_type_row = make_name_type_row(ui, variable, on_change_type_fn, on_remove_fn)

            value_check_box = ui.create_check_box_widget(_("Value"))

            value_row = ui.create_row_widget()
            value_row.add_spacing(8)
            value_row.add(value_check_box)
            value_row.add_stretch()

            label_text_edit = ui.create_line_edit_widget()
            label_text_edit.bind_text(ChangeVariableBinding(document_controller, computation, variable, "label"))

            display_row = ui.create_row_widget()
            display_row.add_spacing(8)
            display_row.add(ui.create_label_widget(_("Label")))
            display_row.add_spacing(8)
            display_row.add(label_text_edit)
            display_row.add_stretch()

            column = ui.create_column_widget()
            column.add(make_label_row(ui, _("Variable Name / Type")))
            column.add(name_type_row)
            column.add(value_row)
            column.add(display_row)

            value_check_box.bind_checked(ChangeVariableBinding(document_controller, computation, variable, "value"))

            return column

        def make_number_row(ui, variable: Symbolic.ComputationVariable, converter, on_change_type_fn, on_remove_fn):
            name_type_row = make_name_type_row(ui, variable, on_change_type_fn, on_remove_fn)

            value_text_edit = ui.create_line_edit_widget()

            value_default_text_edit = ui.create_line_edit_widget()

            value_min_text_edit = ui.create_line_edit_widget()

            value_max_text_edit = ui.create_line_edit_widget()

            value_row = ui.create_row_widget()
            value_row.add_spacing(8)
            value_row.add(value_text_edit)
            value_row.add_spacing(4)
            value_row.add(value_default_text_edit)
            value_row.add_spacing(4)
            value_row.add(value_min_text_edit)
            value_row.add_spacing(4)
            value_row.add(value_max_text_edit)
            value_row.add_stretch()

            label_text_edit = ui.create_line_edit_widget()
            label_text_edit.bind_text(ChangeVariableBinding(document_controller, computation, variable, "label"))

            display_items = [("field", _("Field")), ("slider", _("Slider"))]
            display_combo_box = ui.create_combo_box_widget(items=display_items, item_getter=operator.itemgetter(1))

            display_row = ui.create_row_widget()
            display_row.add_spacing(8)
            display_row.add(label_text_edit)
            # display_row.add_spacing(4)
            # display_row.add(display_combo_box)
            display_row.add_stretch()

            column = ui.create_column_widget()
            column.add(make_label_row(ui, _("Variable Name / Type")))
            column.add(name_type_row)
            column.add(make_label_row(ui, _("Value / Default / Min / Max")))
            column.add(value_row)
            column.add(make_label_row(ui, _("Label / Display Type")))
            column.add(display_row)

            value_text_edit.bind_text(ChangeVariableBinding(document_controller, computation, variable, "value", converter=converter))
            value_default_text_edit.bind_text(ChangeVariableBinding(document_controller, computation, variable, "value_default", converter=converter))
            value_min_text_edit.bind_text(ChangeVariableBinding(document_controller, computation, variable, "value_min", converter=converter))
            value_max_text_edit.bind_text(ChangeVariableBinding(document_controller, computation, variable, "value_max", converter=converter))

            # display_combo_box.on_current_item_changed ... handle undo
            # display_combo_box.current_item = display_items[1]

            return column

        def make_specifier_row(ui, variable: Symbolic.ComputationVariable, on_change_type_fn, on_remove_fn, *, include_secondary=False):
            column = ui.create_column_widget()

            name_type_row = make_name_type_row(ui, variable, on_change_type_fn, on_remove_fn)

            def make_uuid_row(label, binding_identifier):
                uuid_text_edit = ui.create_line_edit_widget()
                uuid_row = ui.create_row_widget()
                uuid_row.add_spacing(8)
                uuid_row.add(ui.create_label_widget(label))
                uuid_row.add_spacing(8)
                uuid_row.add(uuid_text_edit)
                uuid_row.add_spacing(8)
                uuid_text_edit.bind_text(ChangeVariableBinding(document_controller, computation, variable, binding_identifier))
                return uuid_row

            label_text_edit = ui.create_line_edit_widget()
            label_text_edit.bind_text(ChangeVariableBinding(document_controller, computation, variable, "label"))

            display_row = ui.create_row_widget()
            display_row.add_spacing(8)
            display_row.add(ui.create_label_widget(_("Label")))
            display_row.add_spacing(8)
            display_row.add(label_text_edit)
            display_row.add_stretch()

            column.add(name_type_row)
            column.add(make_uuid_row(_("Data Item UUID"), "specifier_uuid_str"))
            if include_secondary:
                column.add(make_uuid_row(_("Region UUID"), "secondary_specifier_uuid_str"))
            column.add(display_row)

            return column

        def make_empty_row(ui, variable: Symbolic.ComputationVariable, on_change_type_fn, on_remove_fn):
            column = ui.create_column_widget()
            name_type_row = make_name_type_row(ui, variable, on_change_type_fn, on_remove_fn)
            column.add(name_type_row)
            return column

        stack = ui.create_column_widget()

        section_widget.add(stack)
        section_widget.add_spacing(4)

        def toggle():
            twist_down_canvas_item.checked = not twist_down_canvas_item.checked
            stack.visible = twist_down_canvas_item.checked
        section_open = False
        twist_down_canvas_item.checked = section_open
        stack.visible = section_open
        twist_down_canvas_item.on_button_clicked = toggle

        def change_type(variable_type):
            command = ComputationModel.ChangeVariableCommand(document_controller.document_model, computation, variable, title=_("Remove Input Data Item"), variable_type=variable_type)
            command.perform()
            document_controller.push_undo_command(command)

        def select_stack(stack, variable, specifier):
            stack.remove_all()
            variable_type = variable.variable_type
            if variable_type == "boolean":
                stack.add(make_boolean_row(ui, variable, change_type, on_remove))
            elif variable_type == "integral":
                stack.add(make_number_row(ui, variable, Converter.IntegerToStringConverter(), change_type, on_remove))
            elif variable_type == "real":
                stack.add(make_number_row(ui, variable, Converter.FloatToStringConverter(), change_type, on_remove))
            elif variable_type == "data_item":
                stack.add(make_specifier_row(ui, variable, change_type, on_remove, include_secondary=True))
            elif variable_type == "region":
                stack.add(make_specifier_row(ui, variable, change_type, on_remove))
            else:
                stack.add(make_empty_row(ui, variable, change_type, on_remove))

        def do_select_stack():
            # select stack will remove the inspector widgets, so delay it until the
            # current event (combo box changed) has finished by queueing it.
            queue_task_fn(functools.partial(select_stack, stack, variable, variable.specifier))

        self.__variable_type_changed_event_listener = variable.variable_type_changed_event.listen(do_select_stack)

        select_stack(stack, variable, variable.specifier)

        self.widget = section_widget

    def close(self):
        self.__variable_type_changed_event_listener.close()
        self.__variable_type_changed_event_listener = None


def make_image_chooser(document_controller, computation, variable, drag_fn):
    ui = document_controller.ui
    document_model = document_controller.document_model
    # drag_fn is necessary because it is unsafe to start a drag on the column containing the thumbnail
    # since dragging onto itself may delete the column during the drag.
    column = ui.create_column_widget(properties={"width": 80})
    label_row = ui.create_row_widget()
    label_widget = ui.create_label_widget(variable.display_label, properties={"width": 80})
    label_widget.bind_text(Binding.PropertyBinding(variable, "display_label"))
    label_row.add_stretch()
    label_row.add(label_widget)
    label_row.add_stretch()
    base_variable_specifier = copy.copy(variable.specifier)

    bound_data_source = document_model.resolve_object_specifier(base_variable_specifier)
    data_item = bound_data_source.value.data_item if bound_data_source else None

    def drop_mime_data(mime_data, x, y):
        data_source_mime_str = mime_data.data_as_string(DataItem.DataSource.DATA_SOURCE_MIME_TYPE)
        if data_source_mime_str:
            data_source_mime_data = json.loads(data_source_mime_str)
            data_item_uuid = uuid.UUID(data_source_mime_data["data_item_uuid"])
            data_item = document_model.get_data_item_by_key(data_item_uuid)
            variable_specifier = document_model.get_object_specifier(data_item)
            secondary_specifier = None
            if "graphic_uuid" in data_source_mime_data:
                graphic_uuid = uuid.UUID(data_source_mime_data["graphic_uuid"])
                graphic = document_model.get_graphic_by_uuid(graphic_uuid)
                if graphic:
                    secondary_specifier = document_model.get_object_specifier(graphic)
            properties = {"variable_type": "data_item", "secondary_specifier": secondary_specifier, "specifier": variable_specifier}
            command = ComputationModel.ChangeVariableCommand(document_controller.document_model, computation, variable, title=_("Remove Input Data Item"), **properties)
            command.perform()
            document_controller.push_undo_command(command)
            return "copy"
        if mime_data.has_format("text/data_item_uuid"):
            data_item_uuid = uuid.UUID(mime_data.data_as_string("text/data_item_uuid"))
            data_item = document_model.get_data_item_by_key(data_item_uuid)
            variable_specifier = document_model.get_object_specifier(data_item)
            properties = {"variable_type": "data_item", "secondary_specifier": dict(), "specifier": variable_specifier}
            command = ComputationModel.ChangeVariableCommand(document_controller.document_model, computation, variable, title=_("Remove Input Data Item"), **properties)
            command.perform()
            document_controller.push_undo_command(command)
            return "copy"
        return None

    def data_item_delete():
        variable_specifier = {"type": variable.variable_type, "version": 1, "uuid": str(uuid.uuid4())}
        command = ComputationModel.ChangeVariableCommand(document_controller.document_model, computation, variable, title=_("Remove Input Data Item"), specifier=variable_specifier)
        command.perform()
        document_controller.push_undo_command(command)

    data_item_thumbnail_source = DataItemThumbnailWidget.DataItemThumbnailSource(ui, data_item=data_item)
    data_item_chooser_widget = DataItemThumbnailWidget.ThumbnailWidget(ui, data_item_thumbnail_source, Geometry.IntSize(80, 80))

    def thumbnail_widget_drag(mime_data, thumbnail, hot_spot_x, hot_spot_y):
        # use this convoluted base object for drag so that it doesn't disappear after the drag.
        drag_fn(mime_data, thumbnail, hot_spot_x, hot_spot_y)

    data_item_chooser_widget.on_drag = thumbnail_widget_drag
    data_item_chooser_widget.on_delete = data_item_delete
    data_item_chooser_widget.on_drop_mime_data = drop_mime_data

    def property_changed(key):
        if key == "specifier":
            base_variable_specifier = copy.copy(variable.specifier)
            bound_data_item = document_model.resolve_object_specifier(base_variable_specifier)
            data_item = bound_data_item.value if bound_data_item else None
            data_item_thumbnail_source.set_data_item(data_item)

    property_changed_listener = variable.property_changed_event.listen(property_changed)
    column.add_spacing(4)
    column.add(data_item_chooser_widget)
    column.add(label_row)
    column.add_spacing(4)
    return column, [property_changed_listener]


class EditComputationDialog(Dialog.ActionDialog):

    def __init__(self, document_controller, data_item):
        ui = document_controller.ui
        super().__init__(ui, _("Edit Computation"), app=document_controller.app, parent_window=document_controller, persistent_id="EditComputationDialog" + str(data_item.uuid))

        self.ui = ui
        self.document_controller = document_controller
        self.data_item = data_item

        self._create_menus()

        self.__computation_model = ComputationModel(document_controller)

        self.__sections = list()

        label_edit_widget = ui.create_line_edit_widget(properties={"min-width": 120})
        label_edit_widget.placeholder_text = _("Computation Label")

        label_row = ui.create_row_widget()
        label_row.add_spacing(8)
        label_row.add(ui.create_label_widget(_("Description")))
        label_row.add_spacing(8)
        label_row.add(label_edit_widget)
        label_row.add_spacing(8)
        label_row.add_stretch()

        buttons_row = ui.create_row_widget()
        add_variable_button = ui.create_push_button_widget(_("Add Variable"))
        add_object_button = ui.create_push_button_widget(_("Add Object"))
        buttons_row.add(add_variable_button)
        buttons_row.add_spacing(8)
        buttons_row.add(add_object_button)
        buttons_row.add_spacing(8)
        buttons_row.add_stretch()

        # sizing in widget space (Qt) is difficult to get right and there seems to be bugs.
        # in this case, two different elements are used to effectively make a minimum window
        # size -- the text edit widget for the height and the error row for the width.
        # if both are done on the text edit widget itself, which would be preferred, Qt seems
        # to give up on layout when the scroll bar appears for too many lines.

        text_edit_row = ui.create_row_widget()
        text_edit = ui.create_text_edit_widget(properties={"min-height": 180})
        text_edit.placeholder_text = _("No Computation")
        text_edit_row.add_spacing(8)
        text_edit_row.add(text_edit)
        text_edit_row.add_spacing(8)

        error_row = ui.create_row_widget(properties={"min-width": 400})  # the stylesheet allows it to shrink. guh.
        error_label = ui.create_label_widget("\n", properties={"stylesheet": "color: red", "min-width": 120})
        error_label.word_wrap = True
        error_row.add_spacing(8)
        error_row.add(error_label)
        error_row.add_spacing(8)

        self.__text_edit = text_edit  # for testing
        self.__error_label = error_label  # for testing

        new_button = ui.create_push_button_widget(_("New"))
        update_button = ui.create_push_button_widget(_("Update"))
        button_row = ui.create_row_widget()
        button_row.add_stretch()
        button_row.add(new_button)
        button_row.add_spacing(8)
        button_row.add(update_button)
        button_row.add_spacing(8)

        self.__data_item_row = ui.create_row_widget()

        self.__variable_column = ui.create_column_widget()

        def add_object_pressed():
            document_model = document_controller.document_model
            object_specifier = document_model.get_object_specifier(document_model.data_items[0])
            self.__computation_model.add_variable("".join([random.choice(string.ascii_lowercase) for _ in range(4)]), specifier=object_specifier)

        add_object_button.on_clicked = add_object_pressed

        def add_variable_pressed():
            self.__computation_model.add_variable("".join([random.choice(string.ascii_lowercase) for _ in range(4)]), value_type="integral", value=0)

        add_variable_button.on_clicked = add_variable_pressed

        def new_pressed():
            document_controller.processing_computation(text_edit.text)

        def update_pressed():
            if text_edit.text:
                self.__computation_model.computation_text = text_edit.text
            else:
                self.__computation_model.clear()

        new_button.on_clicked = new_pressed
        update_button.on_clicked = update_pressed
        def editing_finished(text):
            if self.__computation_model:
                self.__computation_model.computation_label = text
        label_edit_widget.on_editing_finished = editing_finished

        def computation_label_changed(text):
            label_edit_widget.text = text
            if label_edit_widget.focused:
                label_edit_widget.request_refocus()

        self.__computation_label_changed_event_listener = self.__computation_model.computation_label_changed_event.listen(computation_label_changed)

        def computation_text_changed(computation_text):
            text_edit.text = computation_text

        self.__computation_text_changed_event_listener = self.__computation_model.computation_text_changed_event.listen(computation_text_changed)

        def error_text_changed(error_text):
            error_label.text = error_text

        self.__error_text_changed_event_listener = self.__computation_model.error_text_changed_event.listen(error_text_changed)

        self.__listeners = list()

        def rebuild_data_item_row():
            self.__data_item_row.remove_all()
            for listener in self.__listeners:
                listener.close()
            self.__listeners = list()
            self.__data_item_row.add_spacing(8)
            for section in self.__sections:
                variable = section.variable
                if variable.variable_type in ("data_item", ):
                    widget, listeners = make_image_chooser(document_controller, self.__computation_model.computation, variable, self.content.drag)
                    self.__listeners.extend(listeners)
                    self.__data_item_row.add(widget)
                    self.__data_item_row.add_spacing(8)
            self.__data_item_row.add_stretch()
            target_column = ui.create_column_widget(properties={"width": 80})

            def thumbnail_widget_drag(mime_data, thumbnail, hot_spot_x, hot_spot_y):
                # use this convoluted base object for drag so that it doesn't disappear after the drag.
                self.content.drag(mime_data, thumbnail, hot_spot_x, hot_spot_y)

            data_item_thumbnail_source = DataItemThumbnailWidget.DataItemThumbnailSource(ui, data_item=data_item)  # TODO: never closed
            data_item_chooser_widget = DataItemThumbnailWidget.ThumbnailWidget(ui, data_item_thumbnail_source, Geometry.IntSize(80, 80))
            data_item_chooser_widget.on_drag = thumbnail_widget_drag
            target_column.add_spacing(4)
            target_column.add(data_item_chooser_widget)
            target_column.add(ui.create_label_widget(_("Target"), properties={"width": 80}))
            target_column.add_spacing(4)
            self.__data_item_row.add(target_column)
            self.__data_item_row.add_spacing(8)

        def variable_inserted(index: int, variable: Symbolic.ComputationVariable) -> None:
            def remove_variable():
                self.__computation_model.remove_variable(variable)
            section = ComputationPanelSection(document_controller, self.__computation_model.computation, variable, remove_variable, self.document_controller.queue_task)
            self.__variable_column.insert(section.widget, index)
            self.__sections.insert(index, section)
            rebuild_data_item_row()

        def variable_removed(index: int, variable: Symbolic.ComputationVariable) -> None:
            self.__variable_column.remove(self.__variable_column.children[index])
            if self.__sections[index]:
                self.__sections[index].close()
            del self.__sections[index]
            rebuild_data_item_row()

        def variable_property_changed(variable: Symbolic.ComputationVariable) -> None:
            rebuild_data_item_row()

        self.__variable_inserted_event_listener = self.__computation_model.variable_inserted_event.listen(variable_inserted)
        self.__variable_removed_event_listener = self.__computation_model.variable_removed_event.listen(variable_removed)
        self.__variable_property_changed_event_listener = self.__computation_model.variable_property_changed_event.listen(variable_property_changed)

        # for testing
        self._new_button = new_button
        self._update_button = update_button

        self.__computation_model.set_data_item(data_item)

        column = self.content
        column.add_spacing(6)
        column.add(label_row)
        column.add(self.__data_item_row)
        column.add(self.__variable_column)
        column.add(buttons_row)
        column.add_spacing(6)
        column.add(text_edit_row)
        column.add_spacing(6)
        column.add(error_row)
        column.add_spacing(6)
        column.add(button_row)
        column.add_spacing(6)

    def close(self):
        self.document_controller.clear_task(str(id(self)))
        for listener in self.__listeners:
            listener.close()
        self.__listeners = list()
        self.__computation_label_changed_event_listener.close()
        self.__computation_label_changed_event_listener = None
        self.__computation_text_changed_event_listener.close()
        self.__computation_text_changed_event_listener = None
        self.__error_text_changed_event_listener.close()
        self.__error_text_changed_event_listener = None
        self.__variable_inserted_event_listener.close()
        self.__variable_inserted_event_listener = None
        self.__variable_removed_event_listener.close()
        self.__variable_removed_event_listener = None
        self.__computation_model.close()
        self.__computation_model = None
        super().close()

    def size_changed(self, width, height):
        self.__error_label.size = Geometry.IntSize(height=self.__error_label.size.height, width=self.__text_edit.size.width)

    @property
    def _sections_for_testing(self):
        return self.__sections

    @property
    def _variable_column_for_testing(self):
        return self.__variable_column

    @property
    def _text_edit_for_testing(self):
        return self.__text_edit

    @property
    def _error_label_for_testing(self):
        return self.__error_label

    @property
    def _computation_model_for_testing(self):
        return self.__computation_model
