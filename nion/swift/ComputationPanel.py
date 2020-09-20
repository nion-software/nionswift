from __future__ import annotations

# standard libraries
import copy
import functools
import gettext
import operator
import random
import string
import sys
import typing
import uuid
import weakref

# third party libraries
# None

# local libraries
from nion.swift import DataItemThumbnailWidget
from nion.swift import Inspector
from nion.swift import MimeTypes
from nion.swift import Undo
from nion.swift.model import DataItem
from nion.swift.model import DataStructure
from nion.swift.model import DisplayItem
from nion.swift.model import Graphics
from nion.swift.model import Schema
from nion.swift.model import Symbolic
from nion.ui import CanvasItem
from nion.ui import Declarative
from nion.ui import Dialog
from nion.ui import UserInterface
from nion.ui import Window
from nion.utils import Binding
from nion.utils import Converter
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import ListModel
from nion.utils import Model
from nion.utils import Observable

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController
    from nion.swift.model import DocumentModel

_ = gettext.gettext


class AddVariableCommand(Undo.UndoableCommand):

    def __init__(self, document_model, computation: Symbolic.Computation, name: str=None, value_type: str=None, value=None, value_default=None, value_min=None, value_max=None, control_type: str=None, specifier: dict=None, label: str=None):
        super().__init__(_("Add Computation Variable"))
        self.__document_model = document_model
        self.__computation_proxy = computation.create_proxy()
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
        self.__computation_proxy.close()
        self.__computation_proxy = None
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
        computation = self.__computation_proxy.item
        variable = computation.create_variable(self.__name, self.__value_type, self.__value, self.__value_default, self.__value_min, self.__value_max, self.__control_type, self.__specifier, self.__label)
        self.__variable_index = computation.variables.index(variable)

    def _get_modified_state(self):
        computation = self.__computation_proxy.item
        return computation.modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state) -> None:
        computation = self.__computation_proxy.item
        computation.modified_state, self.__document_model.modified_state = modified_state

    def _compare_modified_states(self, state1, state2) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return state1[0] == state2[0]

    def _undo(self):
        computation = self.__computation_proxy.item
        variable = computation.variables[self.__variable_index]
        computation.remove_variable(variable)

    def _redo(self):
        self.perform()


class RemoveVariableCommand(Undo.UndoableCommand):

    def __init__(self, document_model, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable):
        super().__init__(_("Remove Computation Variable"))
        self.__document_model = document_model
        self.__computation_proxy = computation.create_proxy()
        self.__variable_index = computation.variables.index(variable)
        self.__variable_dict = variable.write_to_dict()
        self.initialize()

    def close(self):
        self.__computation_proxy.close()
        self.__computation_proxy = None
        self.__variable_index = None
        self.__variable_dict = None
        super().close()

    def perform(self):
        computation = self.__computation_proxy.item
        variable = computation.variables[self.__variable_index]
        computation.remove_variable(variable)

    def _get_modified_state(self):
        computation = self.__computation_proxy.item
        return computation.modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state) -> None:
        computation = self.__computation_proxy.item
        computation.modified_state, self.__document_model.modified_state = modified_state

    def _compare_modified_states(self, state1, state2) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return state1[0] == state2[0]

    def _undo(self):
        computation = self.__computation_proxy.item
        variable = Symbolic.ComputationVariable()
        variable.begin_reading()
        variable.read_from_dict(self.__variable_dict)
        variable.finish_reading()
        computation.insert_variable(self.__variable_index, variable)

    def _redo(self):
        computation = self.__computation_proxy.item
        computation.remove_variable(computation.variables[self.__variable_index])


class CreateComputationCommand(Undo.UndoableCommand):

    def __init__(self, document_model, data_item):
        super().__init__(_("Create Computation"))
        self.__document_model = document_model
        self.__data_item_proxy = data_item.create_proxy()

    def close(self):
        self.__document_model = None
        self.__data_item_proxy.close()
        self.__data_item_proxy = None
        super().close()

    @property
    def _computation(self) -> Symbolic.Computation:
        return self.__document_model.create_computation()

    def perform(self):
        data_item = self.__data_item_proxy.item
        computation = self.__document_model.create_computation()
        self.__document_model.set_data_item_computation(data_item, computation)

    def _get_modified_state(self):
        return self.__document_model.modified_state

    def _set_modified_state(self, modified_state) -> None:
        self.__document_model.modified_state = modified_state

    def _undo(self):
        data_item = self.__data_item_proxy.item
        self.__document_model.set_data_item_computation(data_item, None)


class ChangeComputationCommand(Undo.UndoableCommand):

    def __init__(self, document_model, computation: Symbolic.Computation, *, title: str=None, command_id: str=None, is_mergeable: bool=False, **kwargs):
        super().__init__(title if title else _("Change Computation"), command_id=command_id, is_mergeable=is_mergeable)
        self.__document_model = document_model
        self.__computation_proxy = computation.create_proxy()
        self.__properties = {key: getattr(computation, key) for key in kwargs.keys()}
        self.__value_dict = kwargs
        self.initialize()

    def close(self):
        self.__properties = None
        self.__computation_proxy.close()
        self.__computation_proxy = None
        self.__properties = None
        self.__value_dict = None
        super().close()

    def perform(self):
        computation = self.__computation_proxy.item
        for key, value in self.__value_dict.items():
            setattr(computation, key, value)

    def _get_modified_state(self):
        computation = self.__computation_proxy.item
        return computation.modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state) -> None:
        computation = self.__computation_proxy.item
        computation.modified_state, self.__document_model.modified_state = modified_state

    def _compare_modified_states(self, state1, state2) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return state1[0] == state2[0]

    def _undo(self):
        computation = self.__computation_proxy.item
        properties = self.__properties
        self.__properties = computation.write_to_dict()
        # NOTE: use read_properties_from_dict (read properties only), not read_from_dict (used for initialization).
        computation.read_properties_from_dict(properties)

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, ChangeComputationCommand) and self.command_id and self.command_id == command.command_id and self.__computation_proxy.item == command.__computation_proxy.item


def select_computation(document_model: DocumentModel.DocumentModel, display_item: DisplayItem.DisplayItem) -> typing.Optional[Symbolic.Computation]:
    if display_item:
        match_items = set()
        match_items.add(display_item)
        match_items.update(display_item.data_items)
        match_items.update(display_item.graphics)
        computations = set()
        for computation in document_model.computations:
            if computation.output_items.intersection(match_items):
                computations.add(computation)
        return next(iter(computations)) if len(computations) == 1 else None
    return None


class ComputationModel:
    """Represents a computation. Tracks a display specifier for changes to it and its computation content.

    Provides read/write access to the computation_text via the property.

    Provides a computation_text_changed event, always fired on UI thread.
    """

    def __init__(self, document_controller: DocumentController.DocumentController):
        self.__weak_document_controller = weakref.ref(document_controller)
        self.__display_item = None
        self.__computation = None
        self.__set_display_item(None)
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
        self.__set_display_item(None)

    @property
    def document_controller(self) -> DocumentController.DocumentController:
        return self.__weak_document_controller()

    @property
    def display_item(self):
        return self.__display_item

    @property
    def computation(self):
        return self.__computation

    def set_display_item(self, display_item):
        self.__set_display_item(display_item)

    def add_variable(self, name: str=None, value_type: str=None, value=None, value_default=None, value_min=None, value_max=None, control_type: str=None, specifier: dict=None, label: str=None) -> None:
        computation = self.computation
        if computation:
            command = AddVariableCommand(self.document_controller.document_model, computation, name, value_type, value, value_default, value_min, value_max, control_type, specifier, label)
            command.perform()
            self.document_controller.push_undo_command(command)

    def remove_variable(self, variable: Symbolic.ComputationVariable) -> None:
        computation = self.computation
        if computation:
            command = RemoveVariableCommand(self.document_controller.document_model, computation, variable)
            command.perform()
            self.document_controller.push_undo_command(command)

    @property
    def computation_label(self):
        return self.__computation_label

    @computation_label.setter
    def computation_label(self, label):
        computation = self.computation
        if computation:
            command = ChangeComputationCommand(self.document_controller.document_model, computation, command_id="computation_change_label", is_mergeable=True, label=label)
            command.perform()
            self.document_controller.push_undo_command(command)

    @property
    def computation_text(self):
        return self.__computation_text

    @computation_text.setter
    def computation_text(self, computation_text):
        computation = self.computation
        if computation:
            command = ChangeComputationCommand(self.document_controller.document_model, computation, command_id="computation_change_label", is_mergeable=True, expression=computation_text)
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

    def __update_computation_display(self) -> None:
        def update_computation_display():
            label = None
            expression = None
            error_text = None
            computation = self.computation
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
    def __set_display_item(self, display_item):
        if self.__display_item != display_item:
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
            computation = self.computation
            if computation:
                for index, variable in enumerate(computation.variables):
                    self.__variable_removed(0, variable)
            document_model = self.document_controller.document_model
            self.__display_item = display_item
            self.__computation = select_computation(document_model, display_item)
            computation = self.computation
            if computation:
                def computation_updated(computation):
                    if computation == self.computation:
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
                command = Inspector.ChangeComputationVariableCommand(document_controller.document_model, computation, self.source, **{self.__property_name: value})
                command.perform()
                document_controller.push_undo_command(command)

        self.source_setter = set_value


class ComputationPanelSection:

    def __init__(self, document_controller: DocumentController.DocumentController, computation, variable, on_remove, queue_task_fn):
        ui = document_controller.ui

        self.variable = variable

        section_widget = ui.create_column_widget()
        section_title_row = ui.create_row_widget()

        twist_down_canvas_item = CanvasItem.TwistDownCanvasItem()
        twist_down_canvas_widget = ui.create_canvas_widget(properties={"height": 20, "width": 20})
        twist_down_canvas_widget.canvas_item.add_canvas_item(twist_down_canvas_item)
        section_title_row.add(twist_down_canvas_widget)
        twist_down_label_widget = ui.create_label_widget(variable.name)
        twist_down_label_widget.text_font = "bold"
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

            type_items = [("boolean", _("Boolean")), ("integral", _("Integer")), ("real", _("Real")), ("string", _("String")),("data_source", _("Data Source")), ("graphic", _("Graphic"))]
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

        def make_string_row(ui, variable: Symbolic.ComputationVariable, converter, on_change_type_fn, on_remove_fn):
            name_type_row = make_name_type_row(ui, variable, on_change_type_fn, on_remove_fn)

            value_text_edit = ui.create_line_edit_widget()

            value_default_text_edit = ui.create_line_edit_widget()

            value_row = ui.create_row_widget()
            value_row.add_spacing(8)
            value_row.add(value_text_edit)
            value_row.add_spacing(4)
            value_row.add(value_default_text_edit)
            value_row.add_stretch()

            label_text_edit = ui.create_line_edit_widget()
            label_text_edit.bind_text(ChangeVariableBinding(document_controller, computation, variable, "label"))

            display_row = ui.create_row_widget()
            display_row.add_spacing(8)
            display_row.add(label_text_edit)
            display_row.add_stretch()

            column = ui.create_column_widget()
            column.add(make_label_row(ui, _("Variable Name / Type")))
            column.add(name_type_row)
            column.add(make_label_row(ui, _("Value / Default")))
            column.add(value_row)
            column.add(make_label_row(ui, _("Label")))
            column.add(display_row)

            value_text_edit.bind_text(ChangeVariableBinding(document_controller, computation, variable, "value", converter=converter))
            value_default_text_edit.bind_text(ChangeVariableBinding(document_controller, computation, variable, "value_default", converter=converter))

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
            command = Inspector.ChangeComputationVariableCommand(document_controller.document_model, computation, variable, title=_("Remove Input Data Item"), variable_type=variable_type)
            command.perform()
            document_controller.push_undo_command(command)

        def select_stack(stack, variable):
            stack.remove_all()
            variable_type = variable.variable_type
            if variable_type == "boolean":
                stack.add(make_boolean_row(ui, variable, change_type, on_remove))
            elif variable_type == "integral":
                stack.add(make_number_row(ui, variable, Converter.IntegerToStringConverter(), change_type, on_remove))
            elif variable_type == "real":
                stack.add(make_number_row(ui, variable, Converter.FloatToStringConverter(), change_type, on_remove))
            elif variable_type == "string":
                stack.add(make_string_row(ui, variable, None, change_type, on_remove))
            elif variable_type == "data_source":
                stack.add(make_specifier_row(ui, variable, change_type, on_remove, include_secondary=True))
            elif variable_type == "graphic":
                stack.add(make_specifier_row(ui, variable, change_type, on_remove))
            else:
                stack.add(make_empty_row(ui, variable, change_type, on_remove))

        def do_select_stack():
            # select stack will remove the inspector widgets, so delay it until the
            # current event (combo box changed) has finished by queueing it.
            queue_task_fn(functools.partial(select_stack, stack, variable))

        self.__variable_type_changed_event_listener = variable.variable_type_changed_event.listen(do_select_stack)

        select_stack(stack, variable)

        self.widget = section_widget

    def close(self):
        self.__variable_type_changed_event_listener.close()
        self.__variable_type_changed_event_listener = None


def drop_mime_data(document_controller, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable, mime_data: UserInterface.MimeData, x: int, y: int) -> typing.Optional[str]:
    project = computation.project  # all variables/specifiers will go into the same project as the computation
    display_item, graphic = MimeTypes.mime_data_get_data_source(mime_data, document_controller.document_model)
    data_item = display_item.data_item if display_item else None
    if data_item:
        variable_specifier = DataStructure.get_object_specifier(display_item.get_display_data_channel_for_data_item(data_item), project=project)
        secondary_specifier = None
        if graphic:
            secondary_specifier = DataStructure.get_object_specifier(graphic, project=project)
        properties = {"variable_type": "data_source", "secondary_specifier": secondary_specifier, "specifier": variable_specifier}
        command = Inspector.ChangeComputationVariableCommand(document_controller.document_model, computation, variable, title=_("Set Input Data Source"), **properties)
        command.perform()
        document_controller.push_undo_command(command)
        return "copy"
    display_item = MimeTypes.mime_data_get_display_item(mime_data, document_controller.document_model)
    data_item = display_item.data_item if display_item else None
    if data_item:
        variable_specifier = DataStructure.get_object_specifier(display_item.get_display_data_channel_for_data_item(data_item), project=project)
        properties = {"variable_type": "data_source", "secondary_specifier": dict(), "specifier": variable_specifier}
        command = Inspector.ChangeComputationVariableCommand(document_controller.document_model, computation, variable, title=_("Set Input Data Source"), **properties)
        command.perform()
        document_controller.push_undo_command(command)
        return "copy"
    return None


def data_item_delete(document_controller, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable) -> None:
    variable_specifier = {"type": variable.variable_type, "version": 1, "uuid": str(uuid.uuid4())}
    command = Inspector.ChangeComputationVariableCommand(document_controller.document_model, computation, variable, title=_("Remove Input Data Source"), specifier=variable_specifier)
    command.perform()
    document_controller.push_undo_command(command)


def make_image_chooser(document_controller, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable, drag_fn):
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
    data_item = computation.get_input(variable.name).data_item

    display_item = document_model.get_display_item_for_data_item(data_item)
    data_item_thumbnail_source = DataItemThumbnailWidget.DataItemThumbnailSource(ui, display_item=display_item)
    data_item_chooser_widget = DataItemThumbnailWidget.ThumbnailWidget(ui, data_item_thumbnail_source, Geometry.IntSize(80, 80))

    def thumbnail_widget_drag(mime_data, thumbnail, hot_spot_x, hot_spot_y):
        # use this convoluted base object for drag so that it doesn't disappear after the drag.
        drag_fn(mime_data, thumbnail, hot_spot_x, hot_spot_y)

    data_item_chooser_widget.on_drag = thumbnail_widget_drag
    data_item_chooser_widget.on_delete = functools.partial(data_item_delete, document_controller, computation, variable)
    data_item_chooser_widget.on_drop_mime_data = functools.partial(drop_mime_data, document_controller, computation, variable)

    def property_changed(key):
        if key == "specifier":
            computation_input = computation.get_input(variable.name)
            data_item = computation_input.data_item if computation_input else None
            display_item = document_model.get_display_item_for_data_item(data_item)
            data_item_thumbnail_source.set_display_item(display_item)

    property_changed_listener = variable.property_changed_event.listen(property_changed)
    column.add_spacing(4)
    column.add(data_item_chooser_widget)
    column.add(label_row)
    column.add_spacing(4)
    return column, [property_changed_listener]


class EditComputationDialog(Dialog.ActionDialog):

    def __init__(self, document_controller: DocumentController.DocumentController, data_item: DataItem.DataItem):

        display_item = document_controller.document_model.get_display_item_for_data_item(data_item)

        ui = document_controller.ui
        super().__init__(ui, _("Edit Computation"), parent_window=document_controller, persistent_id="EditComputationDialog" + str(display_item.uuid))

        self.ui = ui
        self.document_controller = document_controller

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
        error_label = ui.create_label_widget("\n", properties={"min-width": 120})
        error_label.text_color = "red"
        error_label.word_wrap = True
        error_row.add_spacing(8)
        error_row.add(error_label)
        error_row.add_spacing(8)

        self.__text_edit = text_edit  # for testing
        self.__error_label = error_label  # for testing

        update_button = ui.create_push_button_widget(_("Update"))
        button_row = ui.create_row_widget()
        button_row.add_stretch()
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

        def update_pressed():
            if text_edit.text:
                self.__computation_model.computation_text = text_edit.text

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
                if variable.variable_type in ("data_source", ):
                    widget, listeners = make_image_chooser(document_controller, self.__computation_model.computation, variable, self.content.drag)
                    self.__listeners.extend(listeners)
                    self.__data_item_row.add(widget)
                    self.__data_item_row.add_spacing(8)
            self.__data_item_row.add_stretch()
            target_column = ui.create_column_widget(properties={"width": 80})

            def thumbnail_widget_drag(mime_data, thumbnail, hot_spot_x, hot_spot_y):
                # use this convoluted base object for drag so that it doesn't disappear after the drag.
                self.content.drag(mime_data, thumbnail, hot_spot_x, hot_spot_y)

            data_item_thumbnail_source = DataItemThumbnailWidget.DataItemThumbnailSource(ui, display_item=display_item)  # TODO: never closed
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
        self._update_button = update_button

        self.__computation_model.set_display_item(display_item)

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


class ClosingTuplePropertyBinding(Binding.TuplePropertyBinding):
    def __init__(self, source, property_name: str, tuple_index: int, converter=None, fallback=None):
        super().__init__(source, property_name, tuple_index, converter, fallback)
        self.__source = source

    def close(self):
        super().close()
        self.__source.close()
        self.__source = None


class ClosingPropertyBinding(Binding.PropertyBinding):
    def __init__(self, source, property_name: str, *, converter=None, validator=None, fallback=None):
        super().__init__(source, property_name, converter=converter, validator=validator, fallback=fallback)
        self.__source = source

    def close(self):
        super().close()
        self.__source.close()
        self.__source = None


class GraphicHandler:
    def __init__(self, document_controller: DocumentController.DocumentController, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable, graphic: Graphics.Graphic):
        self.document_controller = document_controller
        self.computation = computation
        self.variable = variable
        self.graphic = graphic

    def get_binding(self, source, property: str, converter) -> typing.Optional[Binding.Binding]:
        # override the regular property binding and converter to handle displayed coordinates and undo commands.
        if isinstance(source, Graphics.IntervalGraphic):
            if property in ("start", "end"):
                graphic = source
                display_item = graphic.container
                return Inspector.CalibratedValueBinding(-1, display_item, Inspector.ChangeGraphicPropertyBinding(self.document_controller, display_item, graphic, property))
        if isinstance(source, Graphics.RectangleGraphic):
            if property in ("center_x", "center_y"):
                graphic = source
                display_item = graphic.container
                index = 1 if property == "center_x" else 0
                graphic_name = "rectangle"
                center_model = Inspector.GraphicPropertyCommandModel(self.document_controller, display_item, graphic, "center", title=_("Change {} Center").format(graphic_name), command_id="change_" + graphic_name + "_center")
                return Inspector.CalibratedValueBinding(index, display_item, ClosingTuplePropertyBinding(center_model, "value", index))
            elif property in ("width", "height"):
                graphic = source
                display_item = graphic.container
                index = 1 if property == "width" else 0
                graphic_name = "rectangle"
                size_model = Inspector.GraphicPropertyCommandModel(self.document_controller, display_item, graphic, "size", title=_("Change {} Size").format(graphic_name), command_id="change_" + graphic_name + "_size")
                return Inspector.CalibratedSizeBinding(index, display_item, ClosingTuplePropertyBinding(size_model, "value", index))
            elif property in ("rotation_deg", ):
                graphic = source
                display_item = graphic.container
                graphic_name = "rectangle"
                rotation_model = Inspector.GraphicPropertyCommandModel(self.document_controller, display_item, graphic, "rotation", title=_("Change {} Rotation").format(graphic_name), command_id="change_" + graphic_name + "_size")
                return ClosingPropertyBinding(rotation_model, "value", converter=Inspector.RadianToDegreeStringConverter())
        return None

    @classmethod
    def make_component_content(cls, graphic: Graphics.Graphic) -> Declarative.UIDescription:
        u = Declarative.DeclarativeUI()
        if isinstance(graphic, Graphics.IntervalGraphic):
            graphic_row = u.create_row(
                u.create_label(text=_("Start")),
                u.create_line_edit(text="@binding(graphic.start)", width=90),
                u.create_label(text=_("End")),
                u.create_line_edit(text="@binding(graphic.end)", width=90),
                u.create_stretch(), spacing=12)
            return graphic_row
        if isinstance(graphic, Graphics.RectangleGraphic):
            position_row = u.create_row(
                u.create_label(text=_("X"), width=24),
                u.create_line_edit(text="@binding(graphic.center_x)", width=90),
                u.create_label(text=_("Y"), width=24),
                u.create_line_edit(text="@binding(graphic.center_y)", width=90),
                u.create_stretch(), spacing=12)
            size_row = u.create_row(
                u.create_label(text=_("W"), width=24),
                u.create_line_edit(text="@binding(graphic.width)", width=90),
                u.create_label(text=_("H"), width=24),
                u.create_line_edit(text="@binding(graphic.height)", width=90),
                u.create_stretch(), spacing=12)
            rotation_row = u.create_row(
                u.create_label(text=_("Rotation (deg)")),
                u.create_line_edit(text="@binding(graphic.rotation_deg)", width=90),
                u.create_stretch(), spacing=12)
            return u.create_column( position_row, size_row, rotation_row, spacing=8)
        return u.create_label(text=_("Unsupported Graphic") + f" {graphic.type}")


class DataStructureHandler(Observable.Observable):
    def __init__(self, document_controller: DocumentController.DocumentController, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable, data_structure: DataStructure.DataStructure):
        super().__init__()
        self.document_controller = document_controller
        self.computation = computation
        self.variable = variable
        self.data_structure = data_structure
        self.__entity_choice = None
        self.__entity_types = list()
        self.__entity_choices = list()
        base_entity_type = Schema.get_entity_type(self.variable.entity_id)
        if base_entity_type:
            self.__entity_types = base_entity_type.subclasses

            def name(entity_id: str) -> str:
                entity_name = DataStructure.DataStructure.entity_names[entity_id]
                entity_package_name = DataStructure.DataStructure.entity_package_names[entity_id]
                return f"{entity_name} ({entity_package_name})"

            self.__entity_choices = [name(entity_type.entity_id) for entity_type in self.__entity_types] + ["-", _("None")]
            # configure the initial value
            entity = self.data_structure.entity
            if entity:
                entity_id = entity.entity_type.entity_id
                for index, entity_type in enumerate(self.__entity_types):
                    if entity_id == entity_type.entity_id:
                        self.__entity_choice = index
                        break
            # set initial value to None if nothing else is selected
            if self.__entity_choice is None:
                self.__entity_choice = len(self.__entity_types) + 1

    @property
    def entity_choices(self) -> typing.List[str]:
        return self.__entity_choices

    @property
    def entity_choice(self) -> int:
        return self.__entity_choice

    @entity_choice.setter
    def entity_choice(self, value: int) -> None:
        if 0 <= value < len(self.__entity_types):
            self.__entity_choice = value
            self.property_changed_event.fire("entity_choice")
            self.data_structure.structure_type = self.__entity_types[value].entity_id
        else:
            self.__entity_choice = len(self.__entity_types) + 1
            self.property_changed_event.fire("entity_choice")
            self.data_structure.structure_type = self.variable.entity_id


class VariableHandler:
    def __init__(self, document_controller: DocumentController.DocumentController, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable):
        self.document_controller = document_controller
        self.computation = computation
        self.variable = variable
        # use 2000 below to avoid a match slider, which gives rise to a bizarre slider bug https://bugreports.qt.io/browse/QTBUG-77368
        # also must be a multiple of inspector slider to avoid
        self.slider_converter = Converter.FloatToScaledIntegerConverter(2000, 0, 100)
        self.float_str_converter = Converter.FloatToStringConverter()
        self.int_str_converter = Converter.IntegerToStringConverter()
        self.property_changed_event = Event.Event()
        self.__specifier_changed_listener = variable.property_changed_event.listen(self.__variable_property_changed)

    def close(self) -> None:
        self.__specifier_changed_listener.close()
        self.__specifier_changed_listener = None

    def __variable_property_changed(self, property_name: str) -> None:
        if property_name in ("specifier", "secondary_specifier"):
            self.property_changed_event.fire("display_item")
        elif property_name == "value":
            self.property_changed_event.fire("variable_value")
            self.property_changed_event.fire("combo_box_index")

    @property
    def variable_value(self):
        return self.variable.value

    @variable_value.setter
    def variable_value(self, value):
        document_controller = self.document_controller
        computation = self.computation
        variable = self.variable
        if value != variable.value:
            command = Inspector.ChangeComputationVariableCommand(document_controller.document_model, computation, variable, value=value)
            command.perform()
            document_controller.push_undo_command(command)

    @property
    def combo_box_index(self):
        if self.variable.value == "mapped":
            return 1
        return 0

    @combo_box_index.setter
    def combo_box_index(self, value):
        if value == 1:
            self.variable.value = "mapped"
        else:
            self.variable.value = "none"

    @property
    def display_item(self) -> typing.Optional[DisplayItem.DisplayItem]:
        document_model = self.document_controller.document_model
        computation = self.computation
        variable = self.variable
        base_items = computation.get_input_base_items(variable.name)
        display_item = None
        for base_item in base_items:
            if isinstance(base_item, DataItem.DataItem):
                if display_item:  # check if there are more than one
                    return None
                display_item = document_model.get_display_item_for_data_item(base_item)
        return display_item

    @display_item.setter
    def display_item(self, value: DisplayItem.DisplayItem) -> None:
        pass  # handled separately

    def drop_mime_data(self, mime_data: UserInterface.MimeData, x: int, y: int) -> typing.Optional[str]:
        return drop_mime_data(self.document_controller, self.computation, self.variable, mime_data, x, y)

    def data_item_delete(self):
        data_item_delete(self.document_controller, self.computation, self.variable)

    def create_handler(self, component_id: str, container=None, item=None, **kwargs):
        if component_id == "graphic":
            graphic = self.variable.bound_item.value if self.variable.bound_item else None
            return GraphicHandler(self.document_controller, self.computation, self.variable, graphic)
        if component_id == "graphic_item":
            graphic = typing.cast(Graphics.Graphic, item.value) if item and item.value else None
            return GraphicHandler(self.document_controller, self.computation, self.variable, graphic)
        if component_id == "structure":
            data_structure = self.variable.bound_item.value if self.variable.bound_item else None
            return DataStructureHandler(self.document_controller, self.computation, self.variable, data_structure)
        return None

    def get_resource(self, resource_id: str, container=None, item=None) -> typing.Optional[Declarative.UIDescription]:
        u = Declarative.DeclarativeUI()
        if resource_id == "graphic":
            graphic = self.variable.bound_item.value if self.variable.bound_item else None
            return u.define_component(GraphicHandler.make_component_content(graphic))
        if resource_id == "graphic_item":
            graphic = typing.cast(Graphics.Graphic, item.value) if item and item.value else None
            graphic_content = GraphicHandler.make_component_content(graphic)
            label_row = u.create_row(
                u.create_label(text="@binding(variable.display_label)"),
                u.create_label(text=f"#{container.items.index(item)}"),
                u.create_stretch(), spacing=8)
            return u.define_component(u.create_column(label_row, graphic_content, spacing=8))
        if resource_id == "structure":
            entity_id = self.variable.entity_id
            if entity_id:
                return u.define_component(u.create_row(
                    u.create_label(text="@binding(variable.display_label)"),
                    u.create_combo_box(items_ref="entity_choices", current_index="@binding(entity_choice)"),
                    u.create_stretch(), spacing=8))
            return u.define_component(u.create_column())
        return None

    @classmethod
    def make_component_content(cls, variable: Symbolic.ComputationVariable) -> Declarative.UIDescription:
        u = Declarative.DeclarativeUI()
        label = u.create_label(text="@binding(variable.display_label)")
        if variable.variable_type == "boolean":
            checkbox = u.create_check_box(text="@binding(variable.display_label)", checked="@binding(variable_value)")
            return u.create_column(checkbox)
        elif variable.variable_type == "integral" and (True or variable.control_type == "slider") and variable.has_range:
            slider = u.create_slider(value="@binding(variable_value)", minimum=variable.value_min, maximum=variable.value_max)
            line_edit = u.create_line_edit(text="@binding(variable_value, converter=int_str_converter)", width=60)
            return u.create_column(label, slider, line_edit, spacing=8)
        elif variable.variable_type == "integral":
            line_edit = u.create_line_edit(text="@binding(variable_value, converter=int_str_converter)", width=60)
            return u.create_column(label, line_edit, spacing=8)
        elif variable.variable_type == "real" and (True or variable.control_type == "slider") and variable.has_range:
            slider = u.create_slider(value="@binding(variable_value, converter=slider_converter)", minimum=0, maximum=2000)
            line_edit = u.create_line_edit(text="@binding(variable_value, converter=float_str_converter)", width=60)
            return u.create_column(label, slider, line_edit, spacing=8)
        elif variable.variable_type == "real":
            line_edit = u.create_line_edit(text="@binding(variable_value, converter=float_str_converter)", width=60)
            return u.create_column(label, line_edit, spacing=8)
        elif variable.variable_type == "string" and variable.control_type == "choice":
            combo_box = u.create_combo_box(items=["None", "Mapped"], current_index="@binding(combo_box_index)")
            return u.create_column(label, combo_box, spacing=8)
        elif variable.variable_type == "string":
            line_edit = u.create_line_edit(text="@binding(variable_value)", width=60)
            return u.create_column(label, line_edit, spacing=8)
        elif variable.variable_type in Symbolic.Computation.data_source_types:
            data_source_chooser = {
                "type": "data_source_chooser",
                "display_item": "@binding(display_item)",
                "on_drop_mime_data": "drop_mime_data",
                "on_delete": "data_item_delete",
                "min_width": 80,
                "min_height": 80,
            }
            return u.create_column(label, data_source_chooser, spacing=8)
        elif variable.variable_type == "graphic":
            return u.create_column(label, u.create_component_instance("graphic"), spacing=8)
        elif variable.variable_type == "structure":
            return u.create_column(label, u.create_component_instance("structure"), spacing=8)
        elif variable.bound_items_model:
            return u.create_column(u.create_column(items="variable.bound_items_model.items", item_component_id="graphic_item", spacing=8), spacing=8)
        else:
            return u.create_column(label, u.create_label(text=_("Missing") + " " + f"[{variable.variable_type}]"), spacing=8)


class ResultHandler:
    def __init__(self, document_controller: DocumentController.DocumentController, computation: Symbolic.Computation, result: Symbolic.ComputationOutput):
        self.document_controller = document_controller
        self.computation = computation
        self.result = result

    @property
    def display_item(self) -> typing.Optional[DisplayItem.DisplayItem]:
        document_model = self.document_controller.document_model
        output_item = list(self.result.output_items)[0]
        if isinstance(output_item, DataItem.DataItem):
            return document_model.get_best_display_item_for_data_item(output_item)
        return None

    @classmethod
    def make_component_content(cls, result: Symbolic.ComputationOutput) -> Declarative.UIDescription:
        u = Declarative.DeclarativeUI()
        label = u.create_label(text="@binding(result.label)")
        result_items = list(result.output_items)
        if len(result_items) == 1 and isinstance(result_items[0], DataItem.DataItem):
            data_source_chooser = {
                "type": "data_source_chooser",
                "display_item": "@binding(display_item)",
                "min_width": 80,
                "min_height": 80,
            }
            return u.create_column(label, data_source_chooser, spacing=8)
        return u.create_column(label)


class ComputationHandler:
    def __init__(self, document_controller: DocumentController.DocumentController, computation: Symbolic.Computation):
        self.document_controller = document_controller
        self.computation = computation
        self.computation_inputs_model = ListModel.FilteredListModel(container=computation, master_items_key="variables")
        self.computation_inputs_model.filter = ListModel.PredicateFilter(lambda v: v.variable_type in Symbolic.Computation.data_source_types)
        self.computation_parameters_model = ListModel.FilteredListModel(container=computation, master_items_key="variables")
        self.computation_parameters_model.filter = ListModel.PredicateFilter(lambda v: v.variable_type not in Symbolic.Computation.data_source_types)
        self.is_custom = computation.expression is not None

    def close(self) -> None:
        self.computation_inputs_model.close()
        self.computation_inputs_model = None
        self.computation_parameters_model.close()
        self.computation_parameters_model = None

    def create_handler(self, component_id: str, container=None, item=None, **kwargs):
        if component_id == "variable":
            return VariableHandler(self.document_controller, self.computation, item)
        elif component_id == "result":
            return ResultHandler(self.document_controller, self.computation, item)
        return None

    def get_resource(self, resource_id: str, container=None, item=None) -> typing.Optional[Declarative.UIDescription]:
        u = Declarative.DeclarativeUI()
        if resource_id == "variable":
            return u.define_component(VariableHandler.make_component_content(typing.cast(Symbolic.ComputationVariable, item)))
        if resource_id == "result":
            return u.define_component(ResultHandler.make_component_content(typing.cast(Symbolic.ComputationOutput, item)))
        return None


class InspectComputationDialog(Declarative.WindowHandler):
    # handle computations being removed - inspector contents may become invalid
    # implement a chooser for which computation. order by graphic selection first.
    # error display
    # use api computation?
    # improve window placement to be next to selected display panel or data panel
    # data sources should show crop/interval display/editor if present
    # data sources should indicate masking if used
    # data sources should tool tip info about name, size, data type, calibrated size, etc.
    # fall back to description registered for processing id (i.e. label, type, etc.)
    # description/help for overall function and individual parameters
    # dynamic combo box
    # progress bar

    def __init__(self, document_controller: DocumentController.DocumentController, computation: Symbolic.Computation):
        super().__init__()

        self.__document_controller = document_controller

        # close any previous computation inspector associated with the window
        previous_computation_inspector = getattr(document_controller, "_computation_inspector", None)
        if isinstance(previous_computation_inspector, InspectComputationDialog):
            previous_computation_inspector.close_window()
        document_controller._computation_inspector = self

        # define models that manage the state of the UI
        self.stack_index_model = Model.PropertyModel(0)
        self.stack_page_model = Model.PropertyModel(str())
        self.computation_model = Model.PropertyModel()

        # configure the models
        self.computation_model.value = computation
        self.stack_index_model.value = 1 if self.computation_model.value else 0
        self.stack_page_model.value = ["empty", "single"][self.stack_index_model.value]

        # list for computation being removed
        def remove_computation():
            self.computation_model.value = None
            self.stack_index_model.value = 0
            self.stack_page_model.value = "empty"

        self.__computation_about_to_be_removed_event_listener = computation.about_to_be_removed_event.listen(remove_computation) if computation else None

        self.__run_inspector(document_controller)

    def close(self) -> None:
        if self.__computation_about_to_be_removed_event_listener:
            self.__computation_about_to_be_removed_event_listener.close()
            self.__computation_about_to_be_removed_event_listener = None
        self.__document_controller._computation_inspector = None
        super().close()

    def __run_inspector(self, parent_window: Window) -> None:
        u = Declarative.DeclarativeUI()
        main_page = u.create_column(u.create_component_instance("@binding(stack_page_model.value)"), min_width=320 - 24)
        window = u.create_window(main_page, title=_("Computation"), margin=12, window_style="tool")
        self.run(window, parent_window=parent_window, persistent_id="computation_inspector")
        self.__document_controller.register_dialog(self.window)

    def get_resource(self, resource_id: str, container=None, item=None) -> typing.Optional[Declarative.UIDescription]:
        if resource_id == "empty":
            u = Declarative.DeclarativeUI()
            content = u.create_column(u.create_label(text=_("No computation.")), u.create_stretch())
            component = u.define_component(content=content)
            return component
        if resource_id == "single":
            computation = self.computation_model.value
            u = Declarative.DeclarativeUI()
            label = u.create_label(text=computation.label)
            inputs = u.create_column(items="computation_inputs_model.items", item_component_id="variable", spacing=8)
            results = u.create_column(items="computation.results", item_component_id="result", spacing=8)
            row = u.create_row(
                u.create_column(inputs),
                u.create_column(results),
                spacing=12,
            )
            parameters = u.create_column(items="computation_parameters_model.items", item_component_id="variable", spacing=8)
            if sys.platform == "darwin":
                note = u.create_row(u.create_label(text=_("Use Command+Shift+E to edit data item script.")), u.create_stretch(), visible="@binding(is_custom)")
            else:
                note = u.create_row(u.create_label(text=_("Use Ctrl+Shift+E to edit data item script.")), u.create_stretch(), visible="@binding(is_custom)")
            component = u.define_component(content=u.create_column(label, row, parameters, note, spacing=12))
            return component
        return None

    def create_handler(self, component_id: str, container=None, item=None, **kwargs):
        if component_id == "empty":
            class Handler: pass
            return Handler()
        if component_id == "single":
            return ComputationHandler(self.__document_controller, self.computation_model.value)
        return None
