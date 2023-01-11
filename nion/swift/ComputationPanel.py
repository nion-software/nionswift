from __future__ import annotations

# standard libraries
import asyncio
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
from nion.swift import NotificationDialog
from nion.swift import Undo
from nion.swift.model import Changes
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import Model as DataModel
from nion.swift.model import Notification
from nion.swift.model import Persistence
from nion.swift.model import Schema
from nion.swift.model import Symbolic
from nion.swift.model import WorkspaceLayout
from nion.ui import CanvasItem
from nion.ui import Declarative
from nion.ui import Dialog
from nion.ui import DrawingContext
from nion.ui import UserInterface
from nion.ui import Widgets
from nion.ui import Window
from nion.utils import Binding
from nion.utils import Converter
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import ListModel
from nion.utils import Model
from nion.utils import Observable
from nion.utils import ReferenceCounting
from nion.utils import Registry
from nion.utils.ReferenceCounting import weak_partial

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController
    from nion.swift.model import Connection
    from nion.swift.model import DataGroup
    from nion.swift.model import DataStructure
    from nion.swift.model import DocumentModel
    from nion.swift.model import Project
    from nion.ui import Application

_DocumentControllerWeakRefType = typing.Callable[[], "DocumentController.DocumentController"]

_ = gettext.gettext

T = typing.TypeVar('T')


class AddVariableCommand(Undo.UndoableCommand):

    def __init__(self, document_model: DocumentModel.DocumentModel, computation: Symbolic.Computation,
                 name: typing.Optional[str] = None, value_type: typing.Optional[str] = None, value: typing.Any = None,
                 value_default: typing.Any = None, value_min: typing.Any = None, value_max: typing.Any = None,
                 control_type: typing.Optional[str] = None,
                 specified_item: typing.Optional[Persistence.PersistentObject] = None,
                 label: typing.Optional[str] = None):
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
        self.__specified_item = specified_item
        self.__label = label
        self.__variable_index = 0
        self.initialize()

    def close(self) -> None:
        self.__computation_proxy.close()
        self.__computation_proxy = typing.cast(typing.Any, None)
        self.__name = None
        self.__value_type = None
        self.__value = None
        self.__value_default = None
        self.__value_min = None
        self.__value_max = None
        self.__control_type = None
        self.__specified_item = None
        self.__label = None
        self.__variable = None
        super().close()

    def perform(self) -> None:
        computation = self.__computation_proxy.item
        if computation:
            variable = computation.create_variable(self.__name, self.__value_type, self.__value, self.__value_default, self.__value_min, self.__value_max, self.__control_type, self.__specified_item, self.__label)
            self.__variable_index = computation.variables.index(variable)

    def _get_modified_state(self) -> typing.Any:
        computation = self.__computation_proxy.item
        computation_modified_state = computation.modified_state if computation else None
        return computation_modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        computation = self.__computation_proxy.item
        if computation:
            computation.modified_state = modified_state[0]
        self.__document_model.modified_state = modified_state[1]

    def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return bool(state1[0] == state2[0])

    def _undo(self) -> None:
        computation = self.__computation_proxy.item
        if computation:
            variable = computation.variables[self.__variable_index]
            computation.remove_variable(variable)

    def _redo(self) -> None:
        self.perform()


class RemoveVariableCommand(Undo.UndoableCommand):

    def __init__(self, document_model: DocumentModel.DocumentModel, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable) -> None:
        super().__init__(_("Remove Computation Variable"))
        self.__document_model = document_model
        self.__computation_proxy = computation.create_proxy()
        self.__variable_index = computation.variables.index(variable)
        self.__variable_dict = variable.write_to_dict()
        self.initialize()

    def close(self) -> None:
        self.__computation_proxy.close()
        self.__computation_proxy = typing.cast(typing.Any, None)
        self.__variable_dict = typing.cast(typing.Any, None)
        super().close()

    def perform(self) -> None:
        computation = self.__computation_proxy.item
        if computation:
            variable = computation.variables[self.__variable_index]
            computation.remove_variable(variable)

    def _get_modified_state(self) -> typing.Any:
        computation = self.__computation_proxy.item
        computation_modified_state = computation.modified_state if computation else None
        return computation_modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        computation = self.__computation_proxy.item
        if computation:
            computation.modified_state = modified_state[0]
        self.__document_model.modified_state = modified_state[1]

    def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return bool(state1[0] == state2[0])

    def _undo(self) -> None:
        computation = self.__computation_proxy.item
        if computation:
            variable = Symbolic.ComputationVariable()
            variable.begin_reading()
            variable.read_from_dict(self.__variable_dict)
            variable.finish_reading()
            computation.insert_variable(self.__variable_index, variable)

    def _redo(self) -> None:
        computation = self.__computation_proxy.item
        if computation:
            computation.remove_variable(computation.variables[self.__variable_index])


class CreateComputationCommand(Undo.UndoableCommand):

    def __init__(self, document_model: DocumentModel.DocumentModel, data_item: DataItem.DataItem) -> None:
        super().__init__(_("Create Computation"))
        self.__document_model = document_model
        self.__data_item_proxy = data_item.create_proxy()

    def close(self) -> None:
        self.__document_model = typing.cast(typing.Any, None)
        self.__data_item_proxy.close()
        self.__data_item_proxy = typing.cast(typing.Any, None)
        super().close()

    @property
    def _computation(self) -> Symbolic.Computation:
        return self.__document_model.create_computation()

    def perform(self) -> None:
        data_item = self.__data_item_proxy.item
        if data_item:
            computation = self.__document_model.create_computation()
            self.__document_model.set_data_item_computation(data_item, computation)

    def _get_modified_state(self) -> typing.Any:
        return self.__document_model.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        self.__document_model.modified_state = modified_state

    def _undo(self) -> None:
        data_item = self.__data_item_proxy.item
        if data_item:
            self.__document_model.set_data_item_computation(data_item, None)


class ChangeComputationCommand(Undo.UndoableCommand):

    def __init__(self, document_model: DocumentModel.DocumentModel, computation: Symbolic.Computation, *,
                 title: typing.Optional[str] = None, command_id: typing.Optional[str] = None,
                 is_mergeable: bool = False, **kwargs: typing.Any) -> None:
        super().__init__(title if title else _("Change Computation"), command_id=command_id, is_mergeable=is_mergeable)
        self.__document_model = document_model
        self.__computation_proxy = computation.create_proxy()
        self.__properties = {key: getattr(computation, key) for key in kwargs.keys()}
        self.__value_dict = kwargs
        self.initialize()

    def close(self) -> None:
        self.__properties = dict()
        self.__computation_proxy.close()
        self.__computation_proxy = typing.cast(typing.Any, None)
        self.__value_dict = typing.cast(typing.Any, None)
        super().close()

    def perform(self) -> None:
        computation = self.__computation_proxy.item
        if computation:
            for key, value in self.__value_dict.items():
                setattr(computation, key, value)

    def _get_modified_state(self) -> typing.Any:
        computation = self.__computation_proxy.item
        computation_modified_state = computation.modified_state if computation else None
        return computation_modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        computation = self.__computation_proxy.item
        if computation:
            computation.modified_state = modified_state[0]
        self.__document_model.modified_state = modified_state[1]

    def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return bool(state1[0] == state2[0])

    def _undo(self) -> None:
        computation = self.__computation_proxy.item
        if computation:
            properties = self.__properties
            self.__properties = computation.write_to_dict()
            # NOTE: use read_properties_from_dict (read properties only), not read_from_dict (used for initialization).
            computation.read_properties_from_dict(properties)

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, ChangeComputationCommand) and bool(self.command_id) and self.command_id == command.command_id and self.__computation_proxy.item == command.__computation_proxy.item


def select_computation(document_model: DocumentModel.DocumentModel, display_item: typing.Optional[DisplayItem.DisplayItem]) -> typing.Optional[Symbolic.Computation]:
    if display_item:
        match_items: typing.Set[Persistence.PersistentObject] = set()
        match_items.add(display_item)
        match_items.update(display_item.data_items)
        match_items.update(display_item.graphics)
        computations: typing.Set[Symbolic.Computation] = set()
        for computation in document_model.computations:
            if set(computation.output_items).intersection(match_items):
                computations.add(computation)
        return next(iter(computations)) if len(computations) == 1 else None
    return None


class ComputationModel:
    """Represents a computation. Tracks a computation for changes to it and its content.

    Provides read/write access to the computation_text via the property.

    Provides a computation_text_changed event, always fired on UI thread.
    """

    def __init__(self, document_controller: DocumentController.DocumentController):
        self.__weak_document_controller = typing.cast(_DocumentControllerWeakRefType, weakref.ref(document_controller))
        self.__display_item: typing.Optional[DisplayItem.DisplayItem] = None
        self.__computation: typing.Optional[Symbolic.Computation] = None
        self.__set_display_item(None)
        self.__computation_changed_or_mutated_event_listener: typing.Optional[Event.EventListener] = None
        self.__computation_variable_inserted_event_listener: typing.Optional[Event.EventListener] = None
        self.__computation_variable_removed_event_listener: typing.Optional[Event.EventListener] = None
        self.__computation_property_changed_event_listener: typing.Optional[Event.EventListener] = None
        self.__computation_label: typing.Optional[str] = None
        self.__computation_text: typing.Optional[str] = None
        self.__error_text: typing.Optional[str] = None
        self.__variable_property_changed_event_listeners: typing.Dict[uuid.UUID, Event.EventListener] = dict()
        self.computation_label_changed_event = Event.Event()
        self.computation_text_changed_event = Event.Event()
        self.error_text_changed_event = Event.Event()
        self.variable_inserted_event = Event.Event()
        self.variable_removed_event = Event.Event()
        self.variable_property_changed_event = Event.Event()

    def close(self) -> None:
        self.__set_display_item(None)

    @property
    def document_controller(self) -> DocumentController.DocumentController:
        return self.__weak_document_controller()

    @property
    def display_item(self) -> typing.Optional[DisplayItem.DisplayItem]:
        return self.__display_item

    @property
    def computation(self) -> typing.Optional[Symbolic.Computation]:
        return self.__computation

    def set_display_item(self, display_item: typing.Optional[DisplayItem.DisplayItem]) -> None:
        self.__set_display_item(display_item)

    def add_variable(self, name: typing.Optional[str] = None, value_type: typing.Optional[str] = None,
                     value: typing.Any = None, value_default: typing.Any = None, value_min: typing.Any = None,
                     value_max: typing.Any = None, control_type: typing.Optional[str] = None,
                     specified_item: typing.Optional[Persistence.PersistentObject] = None,
                     label: typing.Optional[str] = None) -> None:
        computation = self.computation
        if computation:
            command = AddVariableCommand(self.document_controller.document_model, computation, name, value_type, value, value_default, value_min, value_max, control_type, specified_item, label)
            command.perform()
            self.document_controller.push_undo_command(command)

    def remove_variable(self, variable: Symbolic.ComputationVariable) -> None:
        computation = self.computation
        if computation:
            command = RemoveVariableCommand(self.document_controller.document_model, computation, variable)
            command.perform()
            self.document_controller.push_undo_command(command)

    @property
    def computation_label(self) -> typing.Optional[str]:
        return self.__computation_label

    @computation_label.setter
    def computation_label(self, label: typing.Optional[str]) -> None:
        computation = self.computation
        if computation:
            command = ChangeComputationCommand(self.document_controller.document_model, computation, command_id="computation_change_label", is_mergeable=True, label=label)
            command.perform()
            self.document_controller.push_undo_command(command)

    @property
    def computation_text(self) -> typing.Optional[str]:
        return self.__computation_text

    @computation_text.setter
    def computation_text(self, computation_text: typing.Optional[str]) -> None:
        computation = self.computation
        if computation:
            command = ChangeComputationCommand(self.document_controller.document_model, computation, command_id="computation_change_label", is_mergeable=True, expression=computation_text)
            command.perform()
            self.document_controller.push_undo_command(command)

    @property
    def error_text(self) -> typing.Optional[str]:
        return self.__error_text

    def __update_computation_label(self, computation_label: typing.Optional[str]) -> None:
        if self.__computation_label != computation_label:
            self.__computation_label = computation_label
            self.computation_label_changed_event.fire(self.__computation_label)

    def __update_computation_text(self, computation_text: typing.Optional[str]) -> None:
        if self.__computation_text != computation_text:
            self.__computation_text = computation_text
            self.computation_text_changed_event.fire(self.__computation_text)

    def __update_error_text(self, error_text: typing.Optional[str]) -> None:
        if self.__error_text != error_text:
            self.__error_text = error_text
            self.error_text_changed_event.fire(self.__error_text)

    def __update_computation_display(self) -> None:
        def update_computation_display() -> None:
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

    def __computation_item_inserted(self, name: str, index: int, variable: Symbolic.ComputationVariable) -> None:
        if name == "variables":
            self.variable_inserted_event.fire(index, variable)
            def handle_property_changed(key: str) -> None:
                self.__update_computation_display()
                self.variable_property_changed_event.fire(variable)
            self.__variable_property_changed_event_listeners[variable.uuid] = variable.property_changed_event.listen(handle_property_changed)

    def __computation_item_removed(self, name: str, index: int, variable: Symbolic.ComputationVariable) -> None:
        if name == "variables":
            self.variable_removed_event.fire(index, variable)
            self.__variable_property_changed_event_listeners[variable.uuid].close()
            del self.__variable_property_changed_event_listeners[variable.uuid]

    # not thread safe
    def __set_display_item(self, display_item: typing.Optional[DisplayItem.DisplayItem]) -> None:
        if bool(self.__display_item != display_item):
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
                    self.__computation_item_removed("variables", 0, variable)
            document_model = self.document_controller.document_model
            self.__display_item = display_item
            self.__computation = select_computation(document_model, display_item)
            computation = self.computation
            if computation:
                def computation_updated(computation: Symbolic.Computation) -> None:
                    if computation == self.computation:
                        self.__update_computation_display()
                def property_changed(property: str) -> None:
                    if property == "error_text":
                        self.__update_computation_display()
                self.__computation_changed_or_mutated_event_listener = document_model.computation_updated_event.listen(computation_updated)
                self.__computation_variable_inserted_event_listener = computation.item_inserted_event.listen(self.__computation_item_inserted)
                self.__computation_variable_removed_event_listener = computation.item_removed_event.listen(self.__computation_item_removed)
                self.__computation_property_changed_event_listener = computation.property_changed_event.listen(property_changed)
            self.__update_computation_display()
            if computation:
                for index, variable in enumerate(computation.variables):
                    self.__computation_item_inserted("variables", index, variable)


class ChangeVariableBinding(Binding.PropertyBinding):
    def __init__(self, document_controller: DocumentController.DocumentController, computation: Symbolic.Computation,
                 variable: Symbolic.ComputationVariable, property_name: str,
                 converter: typing.Optional[Converter.ConverterLike[typing.Any, typing.Any]] = None,
                 fallback: typing.Any = None) -> None:
        super().__init__(variable, property_name, converter=converter, fallback=fallback)
        self.__document_controller = document_controller
        self.__computation = computation
        self.__variable = variable
        self.__property_name = property_name
        self.__old_source_setter = self.source_setter
        self.source_setter = ReferenceCounting.weak_partial(ChangeVariableBinding.__set_value, self)

    def __set_value(self, value: typing.Any) -> None:
        if value != getattr(self.__variable, self.__property_name):
            command = Inspector.ChangeComputationVariableCommand(self.__document_controller.document_model, self.__computation, typing.cast(Symbolic.ComputationVariable, self.source), **{self.__property_name: value})
            command.perform()
            self.__document_controller.push_undo_command(command)


class ComputationPanelSection:

    def __init__(self, document_controller: DocumentController.DocumentController, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable, on_remove: typing.Optional[typing.Callable[[], None]], queue_task_fn: typing.Callable[[typing.Callable[[], None]], None]) -> None:
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

        def make_label_row(ui: UserInterface.UserInterface, label: str) -> UserInterface.BoxWidget:
            label_row = ui.create_row_widget()
            label_row.add_spacing(8)
            label_row.add(ui.create_label_widget(label))
            label_row.add_stretch()
            return label_row

        def make_name_type_row(ui: UserInterface.UserInterface, variable: Symbolic.ComputationVariable, on_change_type_fn: typing.Callable[[typing.Any], None], on_remove_fn: typing.Optional[typing.Callable[[], None]]) -> UserInterface.BoxWidget:
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

        def make_boolean_row(ui: UserInterface.UserInterface, variable: Symbolic.ComputationVariable, on_change_type_fn: typing.Callable[[typing.Any], None], on_remove_fn: typing.Optional[typing.Callable[[], None]]) -> UserInterface.BoxWidget:
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

        def make_number_row(ui: UserInterface.UserInterface, variable: Symbolic.ComputationVariable, converter: typing.Optional[Converter.ConverterLike[typing.Any, typing.Any]], on_change_type_fn: typing.Callable[[typing.Any], None], on_remove_fn: typing.Optional[typing.Callable[[], None]]) -> UserInterface.BoxWidget:
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

        def make_string_row(ui: UserInterface.UserInterface, variable: Symbolic.ComputationVariable, converter: typing.Optional[Converter.ConverterLike[typing.Any, typing.Any]], on_change_type_fn: typing.Callable[[typing.Any], None], on_remove_fn: typing.Optional[typing.Callable[[], None]]) -> UserInterface.BoxWidget:
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

        def make_specifier_row(ui: UserInterface.UserInterface, variable: Symbolic.ComputationVariable, on_change_type_fn: typing.Callable[[typing.Any], None], on_remove_fn: typing.Optional[typing.Callable[[], None]]) -> UserInterface.BoxWidget:
            column = ui.create_column_widget()

            name_type_row = make_name_type_row(ui, variable, on_change_type_fn, on_remove_fn)

            label_text_edit = ui.create_line_edit_widget()
            label_text_edit.bind_text(ChangeVariableBinding(document_controller, computation, variable, "label"))

            display_row = ui.create_row_widget()
            display_row.add_spacing(8)
            display_row.add(ui.create_label_widget(_("Label")))
            display_row.add_spacing(8)
            display_row.add(label_text_edit)
            display_row.add_stretch()

            column.add(name_type_row)
            column.add(display_row)

            return column

        def make_empty_row(ui: UserInterface.UserInterface, variable: Symbolic.ComputationVariable, on_change_type_fn: typing.Callable[[typing.Any], None], on_remove_fn: typing.Optional[typing.Callable[[], None]]) -> UserInterface.BoxWidget:
            column = ui.create_column_widget()
            name_type_row = make_name_type_row(ui, variable, on_change_type_fn, on_remove_fn)
            column.add(name_type_row)
            return column

        stack = ui.create_column_widget()

        section_widget.add(stack)
        section_widget.add_spacing(4)

        def toggle() -> None:
            twist_down_canvas_item.checked = not twist_down_canvas_item.checked
            stack.visible = twist_down_canvas_item.checked
        section_open = False
        twist_down_canvas_item.checked = section_open
        stack.visible = section_open
        twist_down_canvas_item.on_button_clicked = toggle

        def change_type(variable_type: str) -> None:
            command = Inspector.ChangeComputationVariableCommand(document_controller.document_model, computation, variable, title=_("Remove Input Data Item"), variable_type=variable_type)
            command.perform()
            document_controller.push_undo_command(command)

        def select_stack(stack: UserInterface.BoxWidget, variable: Symbolic.ComputationVariable) -> None:
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
                stack.add(make_specifier_row(ui, variable, change_type, on_remove))
            elif variable_type == "graphic":
                stack.add(make_specifier_row(ui, variable, change_type, on_remove))
            else:
                stack.add(make_empty_row(ui, variable, change_type, on_remove))

        def do_select_stack() -> None:
            # select stack will remove the inspector widgets, so delay it until the
            # current event (combo box changed) has finished by queueing it.
            queue_task_fn(functools.partial(select_stack, stack, variable))

        self.__variable_type_changed_event_listener = variable.variable_type_changed_event.listen(do_select_stack)

        select_stack(stack, variable)

        self.widget = section_widget

    def close(self) -> None:
        self.__variable_type_changed_event_listener.close()
        self.__variable_type_changed_event_listener = typing.cast(typing.Any, None)


def drop_mime_data(document_controller: DocumentController.DocumentController, computation: Symbolic.Computation,
                   variable: Symbolic.ComputationVariable, mime_data: UserInterface.MimeData, x: int, y: int) -> str:
    display_item, graphic = MimeTypes.mime_data_get_data_source(mime_data, document_controller.document_model)
    data_item = display_item.data_item if display_item else None
    if data_item and display_item:
        properties = {"variable_type": "data_source", "secondary_specified_object": graphic, "specified_object": display_item.get_display_data_channel_for_data_item(data_item)}
        command = Inspector.ChangeComputationVariableCommand(document_controller.document_model, computation, variable, title=_("Set Input Data Source"), **properties)  # type: ignore
        command.perform()
        document_controller.push_undo_command(command)
        return "copy"
    display_item = MimeTypes.mime_data_get_display_item(mime_data, document_controller.document_model)
    data_item = display_item.data_item if display_item else None
    if data_item and display_item:
        properties = {"variable_type": "data_source", "secondary_specified_object": None, "specified_object": display_item.get_display_data_channel_for_data_item(data_item)}
        command = Inspector.ChangeComputationVariableCommand(document_controller.document_model, computation, variable, title=_("Set Input Data Source"), **properties)  # type: ignore
        command.perform()
        document_controller.push_undo_command(command)
        return "copy"
    return "ignore"


def data_item_delete(document_controller: DocumentController.DocumentController, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable) -> None:
    command = Inspector.ChangeComputationVariableCommand(document_controller.document_model, computation, variable, title=_("Remove Input Data Source"), specified_object=None)
    command.perform()
    document_controller.push_undo_command(command)


def make_image_chooser(document_controller: DocumentController.DocumentController,
                       computation: Symbolic.Computation,
                       variable: Symbolic.ComputationVariable,
                       drag_fn: typing.Callable[[UserInterface.MimeData, typing.Optional[DrawingContext.RGBA32Type], typing.Optional[int], typing.Optional[int]], None]) -> typing.Tuple[UserInterface.BoxWidget, typing.Sequence[Event.EventListener]]:
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

    def thumbnail_widget_drag(mime_data: UserInterface.MimeData, thumbnail: typing.Optional[DrawingContext.RGBA32Type], hot_spot_x: int, hot_spot_y: int) -> None:
        # use this convoluted base object for drag so that it doesn't disappear after the drag.
        drag_fn(mime_data, thumbnail, hot_spot_x, hot_spot_y)

    data_item_chooser_widget.on_drag = thumbnail_widget_drag
    data_item_chooser_widget.on_delete = functools.partial(data_item_delete, document_controller, computation, variable)
    data_item_chooser_widget.on_drop_mime_data = functools.partial(drop_mime_data, document_controller, computation, variable)

    def property_changed(key: str) -> None:
        if key == "specified_object":
            computation_input = computation.get_input(variable.name)
            data_item = computation_input.data_item if computation_input else None
            display_item = document_model.get_display_item_for_data_item(data_item)
            if display_item:
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
        assert display_item

        ui = document_controller.ui
        super().__init__(ui, _("Edit Computation"), parent_window=document_controller, persistent_id="EditComputationDialog" + str(display_item.uuid))

        self.ui = ui
        self.document_controller = document_controller

        self.__computation_model = ComputationModel(document_controller)

        self.__sections: typing.List[ComputationPanelSection] = list()

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
        text_edit.placeholder = _("No Computation")
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

        def add_object_pressed() -> None:
            document_model = document_controller.document_model
            self.__computation_model.add_variable("".join([random.choice(string.ascii_lowercase) for _ in range(4)]), specified_item=document_model.data_items[0])

        add_object_button.on_clicked = add_object_pressed

        def add_variable_pressed() -> None:
            self.__computation_model.add_variable("".join([random.choice(string.ascii_lowercase) for _ in range(4)]), value_type="integral", value=0)

        add_variable_button.on_clicked = add_variable_pressed

        def update_pressed() -> None:
            if text_edit.text:
                self.__computation_model.computation_text = text_edit.text

        update_button.on_clicked = update_pressed
        def editing_finished(text: str) -> None:
            if self.__computation_model:
                self.__computation_model.computation_label = text
        label_edit_widget.on_editing_finished = editing_finished

        def computation_label_changed(text: str) -> None:
            label_edit_widget.text = text
            if label_edit_widget.focused:
                label_edit_widget.request_refocus()

        self.__computation_label_changed_event_listener = self.__computation_model.computation_label_changed_event.listen(computation_label_changed)

        def computation_text_changed(computation_text: str) -> None:
            text_edit.text = computation_text

        self.__computation_text_changed_event_listener = self.__computation_model.computation_text_changed_event.listen(computation_text_changed)

        def error_text_changed(error_text: str) -> None:
            error_label.text = error_text

        self.__error_text_changed_event_listener = self.__computation_model.error_text_changed_event.listen(error_text_changed)

        self.__listeners: typing.List[Event.EventListener] = list()

        def rebuild_data_item_row() -> None:
            self.__data_item_row.remove_all()
            for listener in self.__listeners:
                listener.close()
            self.__listeners = list()
            self.__data_item_row.add_spacing(8)
            for section in self.__sections:
                variable = section.variable
                if variable.variable_type in ("data_source", ):
                    computation = self.__computation_model.computation
                    assert computation
                    widget, listeners = make_image_chooser(document_controller, computation, variable, self.content.drag)
                    self.__listeners.extend(listeners)
                    self.__data_item_row.add(widget)
                    self.__data_item_row.add_spacing(8)
            self.__data_item_row.add_stretch()
            target_column = ui.create_column_widget(properties={"width": 80})

            def thumbnail_widget_drag(mime_data: UserInterface.MimeData, thumbnail: typing.Optional[DrawingContext.RGBA32Type], hot_spot_x: int, hot_spot_y: int) -> None:
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
            def remove_variable() -> None:
                self.__computation_model.remove_variable(variable)

            computation = self.__computation_model.computation
            assert computation
            section = ComputationPanelSection(document_controller, computation, variable, remove_variable, self.document_controller.queue_task)
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

    def close(self) -> None:
        self.document_controller.clear_task(str(id(self)))
        for listener in self.__listeners:
            listener.close()
        self.__listeners = list()
        self.__computation_label_changed_event_listener.close()
        self.__computation_label_changed_event_listener = typing.cast(typing.Any, None)
        self.__computation_text_changed_event_listener.close()
        self.__computation_text_changed_event_listener = typing.cast(typing.Any, None)
        self.__error_text_changed_event_listener.close()
        self.__error_text_changed_event_listener = typing.cast(typing.Any, None)
        self.__variable_inserted_event_listener.close()
        self.__variable_inserted_event_listener = typing.cast(typing.Any, None)
        self.__variable_removed_event_listener.close()
        self.__variable_removed_event_listener = typing.cast(typing.Any, None)
        self.__computation_model.close()
        self.__computation_model = typing.cast(typing.Any, None)
        super().close()

    def size_changed(self, width: int, height: int) -> None:
        self.__error_label.size = Geometry.IntSize(height=self.__error_label.size.height, width=self.__text_edit.size.width)

    @property
    def _sections_for_testing(self) -> typing.Sequence[ComputationPanelSection]:
        return self.__sections

    @property
    def _variable_column_for_testing(self) -> UserInterface.BoxWidget:
        return self.__variable_column

    @property
    def _text_edit_for_testing(self) -> UserInterface.TextEditWidget:
        return self.__text_edit

    @property
    def _error_label_for_testing(self) -> UserInterface.LabelWidget:
        return self.__error_label

    @property
    def _computation_model_for_testing(self) -> ComputationModel:
        return self.__computation_model


class VariableHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable):
        super().__init__()
        self.document_controller = document_controller
        self.computation = computation
        self.variable = variable
        variable_model = Inspector.VariableValueModel(document_controller, computation, variable)
        # use 2000 below to avoid a match slider, which gives rise to a bizarre slider bug https://bugreports.qt.io/browse/QTBUG-77368
        # also must be a multiple of inspector slider to avoid
        self.slider_converter = Converter.FloatToScaledIntegerConverter(2000, 0, 100)
        self.float_str_converter = Converter.FloatToStringConverter()
        self.int_str_converter = Converter.IntegerToStringConverter()
        self.property_changed_event = Event.Event()
        self.__variable_component: typing.Optional[Declarative.HandlerLike] = Inspector.make_computation_variable_component(document_controller, computation, variable, variable_model)
        u = Declarative.DeclarativeUI()
        if self.__variable_component:
            self.ui_view = u.create_column(u.create_component_instance("component"), spacing=8)
        else:
            label = u.create_label(text="@binding(variable.display_label)")
            self.ui_view = u.create_column(label, u.create_label(text=_("Missing") + " " + f"[{variable.variable_type}]"), spacing=8)

    def create_handler(self, component_id: str, container: typing.Optional[Symbolic.ComputationVariable] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if component_id == "component":
            assert self.__variable_component
            return self.__variable_component
        return None


class ResultHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController, computation: Symbolic.Computation, result: Symbolic.ComputationOutput):
        super().__init__()
        self.document_controller = document_controller
        self.computation = computation
        self.result = result
        self.ui_view = self.__make_component_content(result)

    @property
    def display_item(self) -> typing.Optional[DisplayItem.DisplayItem]:
        document_model = self.document_controller.document_model
        result_items = self.result.output_items
        if len(result_items) == 1 and isinstance(result_items[0], DataItem.DataItem):
            return document_model.get_best_display_item_for_data_item(result_items[0])
        return None

    def __make_component_content(self, result: Symbolic.ComputationOutput) -> Declarative.UIDescription:
        u = Declarative.DeclarativeUI()
        label = u.create_label(text="@binding(result.label)")
        result_items = result.output_items
        if len(result_items) == 1 and isinstance(result_items[0], DataItem.DataItem):
            data_source_chooser = {
                "type": "data_source_chooser",
                "display_item": "@binding(display_item)",
                "min_width": 80,
                "min_height": 80,
            }
            return u.create_column(label, data_source_chooser, spacing=8)
        return u.create_column(label)


class RemoveComputationCommand(Undo.UndoableCommand):

    def __init__(self, document_controller: DocumentController.DocumentController, computation: Symbolic.Computation):
        super().__init__(_("Remove Computation"))
        self.__document_controller = document_controller
        workspace_controller = self.__document_controller.workspace_controller
        assert workspace_controller
        self.__old_workspace_layout: typing.Optional[Persistence.PersistentDictType] = workspace_controller.deconstruct()
        self.__new_workspace_layout: typing.Optional[Persistence.PersistentDictType] = None
        self.__computation_index = document_controller.document_model.computations.index(computation)
        self.__undelete_logs: typing.List[Changes.UndeleteLog] = list()
        self.initialize()

    def close(self) -> None:
        self.__document_controller = typing.cast(typing.Any, None)
        self.__old_workspace_layout = None
        self.__new_workspace_layout = None
        for undelete_log in self.__undelete_logs:
            undelete_log.close()
        self.__undelete_logs = typing.cast(typing.Any, None)
        super().close()

    def perform(self) -> None:
        document_model = self.__document_controller.document_model
        computation = document_model.computations[self.__computation_index]
        self.__undelete_logs.append(document_model.remove_computation_with_log(computation))

    def _get_modified_state(self) -> typing.Any:
        return self.__document_controller.document_model.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        self.__document_controller.document_model.modified_state = modified_state

    def _undo(self) -> None:
        workspace_controller = self.__document_controller.workspace_controller
        if workspace_controller:
            self.__new_workspace_layout = workspace_controller.deconstruct()
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
                undelete_log.close()
            self.__undelete_logs.clear()
            if self.__old_workspace_layout is not None:
                workspace_controller.reconstruct(self.__old_workspace_layout)

    def _redo(self) -> None:
        self.perform()
        workspace_controller = self.__document_controller.workspace_controller
        if workspace_controller and self.__new_workspace_layout is not None:
            workspace_controller.reconstruct(self.__new_workspace_layout)


class ComputationHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController, computation: Symbolic.Computation):
        super().__init__()
        self.document_controller = document_controller
        self.computation = computation
        self.computation_inputs_model = ListModel.FilteredListModel(container=computation, master_items_key="variables")
        self.computation_inputs_model.filter = ListModel.PredicateFilter(lambda v: v.variable_type in Symbolic.Computation.data_source_types)
        self.computation_parameters_model = ListModel.FilteredListModel(container=computation, master_items_key="variables")
        self.computation_parameters_model.filter = ListModel.PredicateFilter(lambda v: v.variable_type not in Symbolic.Computation.data_source_types)
        self.is_custom = computation.expression is not None
        self.delete_state_model = Model.PropertyModel(0)
        self.error_state_model = Model.PropertyModel(0)
        self.__error_state_listener = computation.property_changed_event.listen(ReferenceCounting.weak_partial(ComputationHandler.__property_changed, self))
        self.__is_error = self.computation.error_text is not None and self.computation.error_text != str()
        self.ui_view = self.__make_ui()
        self.__property_changed("error_text")

    def close(self) -> None:
        self.computation_inputs_model.close()
        self.computation_inputs_model = typing.cast(typing.Any, None)
        self.computation_parameters_model.close()
        self.computation_parameters_model = typing.cast(typing.Any, None)
        super().close()

    def __make_ui(self) -> Declarative.UIDescriptionResult:
        u = Declarative.DeclarativeUI()
        label = u.create_label(text=self.computation.label)
        source_line = u.create_component_instance("source_component")
        status = u.create_label(text="@binding(computation.status)", color="@binding(status_color)", max_width=300)
        inputs = u.create_column(items="computation_inputs_model.items", item_component_id="variable", spacing=8, size_policy_vertical="expanding")
        results = u.create_column(items="computation.results", item_component_id="result", spacing=8, size_policy_vertical="expanding")
        input_output_row = u.create_row(
            u.create_column(inputs),
            u.create_column(results),
            spacing=12,
            size_policy_vertical="expanding"
        )
        parameters = u.create_column(items="computation_parameters_model.items", item_component_id="variable", spacing=8)
        if sys.platform == "darwin":
            note = u.create_row(u.create_label(text=_("Use Command+Shift+E to edit data item script.")), visible="@binding(is_custom)")
        else:
            note = u.create_row(u.create_label(text=_("Use Ctrl+Shift+E to edit data item script.")), visible="@binding(is_custom)")
        delete_row = u.create_row(u.create_stretch(), u.create_push_button(text=_("Delete"), spacing=12, on_clicked="handle_delete"))
        delete_confirm_row = u.create_row(u.create_stretch(),
                                          u.create_label(text=_("Are you sure?")),
                                          u.create_push_button(text=_("Delete"), on_clicked="handle_confirm_delete"),
                                          u.create_push_button(text=_("Cancel"), on_clicked="handle_cancel_delete"),
                                          spacing=12)
        delete_control_row = u.create_row(u.create_stack(delete_row, delete_confirm_row, current_index="@binding(delete_state_model.value)"))
        controls = u.create_row(u.create_column(status, note, delete_control_row, u.create_stretch(), spacing=12), u.create_stretch())
        inspector_column = u.create_column(label, source_line, u.create_column(input_output_row, parameters, u.create_divider(orientation="horizontal"), controls, spacing=12), spacing=12)
        error_column = u.create_column(
            u.create_stack(
                u.create_column(u.create_row(u.create_label(text=_("No Error")), u.create_stretch()), u.create_stretch()),
                u.create_column(u.create_row(u.create_label(text=_("Error")), u.create_stretch()),
                                u.create_row(u.create_label(text="@binding(computation.status)", color="@binding(status_color)", max_width=300), u.create_stretch()),
                                u.create_text_edit(editable=False, placeholder_text=_("No stack trace."), text="@binding(computation.error_stack_trace)"),
                                u.create_stretch(),
                                spacing=8),
                current_index="@binding(error_state_model.value)"
            )
        )
        return u.create_tabs(
            u.create_tab(_("Edit"), inspector_column),
            u.create_tab(_("Errors"), error_column),
            style="minimal"
        )

    def __property_changed(self, key: str) -> None:
        if key == "error_text":
            self.__is_error = self.computation.error_text is not None and self.computation.error_text != str()
            self.notify_property_changed("status_color")
            self.error_state_model.value = 1 if self.__is_error else 0

    @property
    def status_color(self) -> str:
        return "red" if self.__is_error else "black"

    def handle_delete(self, widget: Declarative.UIWidget) -> None:
        self.delete_state_model.value = 1

    def handle_confirm_delete(self, widget: Declarative.UIWidget) -> None:
        command = RemoveComputationCommand(self.document_controller, self.computation)
        command.perform()
        self.document_controller.push_undo_command(command)
        self.delete_state_model.value = 0

    def handle_cancel_delete(self, widget: Declarative.UIWidget) -> None:
        self.delete_state_model.value = 0

    def create_handler(self, component_id: str, container: typing.Optional[Symbolic.ComputationVariable] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if component_id == "variable":
            return VariableHandler(self.document_controller, self.computation, typing.cast(Symbolic.ComputationVariable, item))
        elif component_id == "result":
            return ResultHandler(self.document_controller, self.computation, typing.cast(Symbolic.ComputationOutput, item))
        elif component_id == "source_component":
            return ReferenceHandler(self.document_controller, _("Source"), self.computation.source)
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

    def __init__(self, document_controller: DocumentController.DocumentController, computation: Symbolic.Computation) -> None:
        super().__init__()

        self.__document_controller = document_controller

        # close any previous computation inspector associated with the window
        previous_window = getattr(document_controller, "_computation_inspector", None)
        if isinstance(previous_window, InspectComputationDialog):
            previous_window.close_window()
        setattr(document_controller, "_computation_inspector", self)

        # define models that manage the state of the UI
        self.stack_index_model = Model.PropertyModel(0)
        self.stack_page_model = Model.PropertyModel(str())
        self.computation_model = Model.PropertyModel[Symbolic.Computation]()

        # configure the models
        self.computation_model.value = computation
        self.stack_index_model.value = 1 if self.computation_model.value else 0
        self.stack_page_model.value = ["empty", "single"][self.stack_index_model.value]

        # list for computation being removed
        def remove_computation() -> None:
            self.computation_model.value = None
            self.stack_index_model.value = 0
            self.stack_page_model.value = "empty"

        self.__computation_about_to_be_removed_event_listener = computation.about_to_be_removed_event.listen(remove_computation) if computation else None

        u = Declarative.DeclarativeUI()
        main_page = u.create_column(u.create_component_instance("@binding(stack_page_model.value)"), u.create_stretch())
        window = u.create_window(main_page, title=_("Computation"), margin=12, window_style="tool")
        self.run(window, parent_window=document_controller, persistent_id="computation_inspector")
        self.__document_controller.register_dialog(self.window)

    def close(self) -> None:
        if self.__computation_about_to_be_removed_event_listener:
            self.__computation_about_to_be_removed_event_listener.close()
            self.__computation_about_to_be_removed_event_listener = None
        setattr(self.__document_controller, "_computation_inspector", None)
        super().close()

    def get_resource(self, resource_id: str, container: typing.Optional[Symbolic.ComputationVariable] = None, item: typing.Any = None) -> typing.Optional[Declarative.UIDescription]:
        if resource_id == "empty":
            u = Declarative.DeclarativeUI()
            content = u.create_column(u.create_label(text=_("No computation.")))
            component = u.define_component(content=content)
            return component
        return None

    def create_handler(self, component_id: str, container: typing.Optional[Symbolic.ComputationVariable] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if component_id == "empty":
            return Declarative.Handler()
        if component_id == "single":
            computation = self.computation_model.value
            assert computation
            return ComputationHandler(self.__document_controller, computation)
        return None


class ComputationErrorNotificationHandler(Declarative.Handler):
    """Declarative component handler for a section in a multiple acquire method component."""

    def __init__(self, app: Application.BaseApplication, notification: Symbolic.ComputationErrorNotification) -> None:
        super().__init__()
        self.app = app
        self.notification = notification
        u = Declarative.DeclarativeUI()
        self.ui_view = u.create_row(
            u.create_column(
                u.create_row(
                    u.create_label(text="@binding(notification.task_name)", color="#3366CC"),
                    u.create_stretch(),
                    {"type": "notification_char_button", "text": " \N{MULTIPLICATION X} ", "on_clicked": "handle_dismiss"},
                    spacing=8
                ),
                u.create_row(
                    {"type": "notification_char_button", "text": "Edit Computation...", "on_clicked": "handle_edit"},
                    u.create_stretch(),
                    spacing=8
                ),
                u.create_row(
                    u.create_label(text="@binding(notification.text)", word_wrap=True, width=440),
                    u.create_stretch(),
                    spacing=8
                ),
                u.create_divider(orientation="horizontal"),
                spacing=4,
            ),
        )

    def handle_dismiss(self, widget: Declarative.UIWidget) -> None:
        self.notification.dismiss()

    def handle_edit(self, widget: Declarative.UIWidget) -> None:
        computation = self.notification.computation
        for window in self.app.windows:
            document_model = typing.cast(typing.Optional["DocumentModel.DocumentModel"], getattr(window, "document_model", None))
            if document_model and computation in document_model.computations:
                InspectComputationDialog(typing.cast("DocumentController.DocumentController", window), computation)


class ComputationErrorNotificationComponentFactory(NotificationDialog.NotificationComponentFactory):
    def make_component(self, app: Application.BaseApplication, notification: Notification.Notification) -> typing.Optional[Declarative.HandlerLike]:
        if isinstance(notification, Symbolic.ComputationErrorNotification):
            return ComputationErrorNotificationHandler(app, notification)
        return None

Registry.register_component(ComputationErrorNotificationComponentFactory(), {"notification-component-factory"})


class ReferenceHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController, label: str, item: typing.Optional[Persistence.PersistentObject]) -> None:
        super().__init__()
        self.document_controller = document_controller
        self.label = label
        self.item = item
        self.ui_view = self.__make_ui()

    def __make_ui(self) -> Declarative.UIDescriptionResult:
        u = Declarative.DeclarativeUI()
        if self.item:
            label = u.create_label(text=self.item.__class__.__name__)
            link = u.create_push_button(text="\N{RIGHTWARDS BLACK ARROW}", on_clicked="handle_link",
                                        border_color="transparent", background_color="rgba(0,0,0,0.0)", style="minimal",
                                        size_policy_horizontal="maximum")
            label_section = u.create_row(label, link)
        else:
            label_section = u.create_label(text=_("None"))
        return u.create_row(
            u.create_label(text=self.label, width=60),
            label_section,
            u.create_stretch(),
            spacing=12)

    def handle_link(self, item: Declarative.UIWidget) -> None:
        if self.item:
            self.document_controller.open_project_item(self.item)


class EntityPropertyHandler(Declarative.Handler):
    def __init__(self, name: str, value_type: Schema.PropertyType, value_model: Model.PropertyModel[typing.Any]) -> None:
        super().__init__()
        self.value_model = value_model
        self.ui_view = self._make_ui(name, value_type)
        self.int_converter = Converter.IntegerToStringConverter()
        self.float_converter = Converter.FloatToStringConverter()
        self.date_converter = Converter.DatetimeToStringConverter(is_local=True, format="%Y-%m-%d %H:%M:%S %Z")
        self.uuid_converter = Converter.UuidToStringConverter()

    def _make_ui(self, name: str, value_type: Schema.PropertyType) -> Declarative.UIDescriptionResult:
        u = Declarative.DeclarativeUI()
        if value_type.type == Schema.STRING:
            return u.create_row(u.create_label(text=name, width=60),
                                u.create_label(text=f"@binding(value_model.value)"),
                                u.create_stretch(), spacing=12)
        elif value_type.type == Schema.BOOLEAN:
            return u.create_row(u.create_label(text=name, width=60),
                                u.create_check_box(text=f"@binding(value_model.value)"),
                                u.create_stretch(), spacing=12)
        elif value_type.type == Schema.INT:
            return u.create_row(u.create_label(text=name, width=60),
                                u.create_label(text=f"@binding(value_model.value, converter=int_converter)"),
                                u.create_stretch(), spacing=12)
        elif value_type.type == Schema.FLOAT:
            return u.create_row(u.create_label(text=name, width=60),
                                u.create_label(text=f"@binding(value_model.value, converter=float_converter)"),
                                u.create_stretch(), spacing=12)
        elif value_type.type == Schema.TIMESTAMP:
            return u.create_row(u.create_label(text=name, width=60),
                                u.create_label(text=f"@binding(value_model.value, converter=date_converter)"),
                                u.create_stretch(), spacing=12)
        elif value_type.type == Schema.UUID:
            return u.create_row(u.create_label(text=name, width=60),
                                u.create_label(text=f"@binding(value_model.value, converter=uuid_converter)"),
                                u.create_stretch(), spacing=12)
        return u.create_row(u.create_label(text=name, width=60),
                            u.create_label(text=str(type(value_type))),
                            u.create_stretch(),
                            spacing=12)


class EntityTupleModel(Observable.Observable):
    # takes a property model and generates item inserted/removed events when the value changes.
    # observers can treat this as a dynamic list with 'items' key.

    def __init__(self, value_model: Model.PropertyModel[typing.Any]) -> None:
        super().__init__()
        self.items: typing.List[typing.Any] = list()

        def property_changed(tuple_model: EntityTupleModel, property_name: str) -> None:
            # check if changed property matches property name for this object
            if property_name == "value":
                while tuple_model.items:
                    item = tuple_model.items.pop()
                    tuple_model.notify_remove_item("items", item, len(tuple_model.items))
                items = typing.cast(typing.List[typing.Any], value_model.value)
                for index, item in enumerate(items or tuple()):
                    tuple_model.items.append((index, item))
                    tuple_model.notify_insert_item("items", tuple_model.items[-1], len(tuple_model.items))

        self.__listener = value_model.property_changed_event.listen(weak_partial(property_changed, self))

        property_changed(self, "value")


class EntityTupleHandler(Declarative.Handler):
    def __init__(self, name: str, indent: int, value_type: Schema.FieldType, value_model: Model.PropertyModel[typing.Any]) -> None:
        super().__init__()
        self.value_model = value_model
        self.value_type = value_type
        self.indent = indent
        self.tuple_model = EntityTupleModel(value_model)
        u = Declarative.DeclarativeUI()
        # the items in tuple_model (tuples an index and a value of value_type) will get passed to create_handler in the
        # item parameter. this is accomplished by passing items to create_column below. the item_component_id is
        # used to match this column with the request for a handler.
        self.ui_view = u.create_column(
            u.create_row(u.create_spacing(indent), u.create_label(text=name, width=60), u.create_stretch()),
            u.create_row(u.create_spacing(indent * 4),
                         u.create_column(items="tuple_model.items", item_component_id="entity_field", spacing=8)),
            spacing = 8,
        )

    def create_handler(self, component_id: str, container: typing.Optional[ListModel.ListModel[typing.Any]] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        # item is a tuple of type index, self.value_type
        if component_id == "entity_field" and item is not None:
            index, item_ = item
            return make_field_handler(str(index), self.indent, self.value_type, Model.PropertyModel(item_))
        return None


class EntityArrayHandler(Declarative.Handler):
    def __init__(self, name: str, indent: int, value_type: Schema.FieldType, value_model: Model.PropertyModel[typing.Any]) -> None:
        super().__init__()
        self.value_model = value_model
        self.value_type = value_type
        self.indent = indent
        self.tuple_model = EntityTupleModel(value_model)
        u = Declarative.DeclarativeUI()
        # the items in tuple_model (tuples an index and a value of value_type) will get passed to create_handler in the
        # item parameter. this is accomplished by passing items to create_column below. the item_component_id is
        # used to match this column with the request for a handler.
        self.ui_view = u.create_column(
            u.create_row(u.create_spacing(indent), u.create_label(text=name, width=60), u.create_stretch()),
            u.create_row(u.create_spacing(indent * 4),
                         u.create_column(items="tuple_model.items", item_component_id="entity_field", spacing=8)),
            spacing = 8,
        )

    def create_handler(self, component_id: str, container: typing.Optional[ListModel.ListModel[typing.Any]] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        # item is a tuple of type index, self.value_type
        if component_id == "entity_field" and item is not None:
            index, item_ = item
            return make_field_handler(str(index), self.indent, self.value_type, Model.PropertyModel(item_))
        return None


class EntityValueIndexModel(Model.PropertyModel[T], typing.Generic[T]):
    # NOTE: read only

    def __init__(self, value_model: Model.PropertyModel[T], index: int) -> None:
        assert value_model.value is not None
        super().__init__(getattr(value_model, "value")[index])
        self.__value_model = value_model

        def property_changed(property_model: EntityValueIndexModel[T], value_model: Model.PropertyModel[T], property_name: str) -> None:
            # check if changed property matches property name for this object
            if property_name == "value":
                property_model.value = getattr(value_model, property_name)[index]

        self.__listener = self.__value_model.property_changed_event.listen(weak_partial(property_changed, self, self.__value_model))


class EntityFieldsHandler(Declarative.Handler):
    def __init__(self, name: str, indent: int, field_list: typing.Sequence[typing.Tuple[str, Schema.FieldType, Model.PropertyModel[typing.Any]]]) -> None:
        super().__init__()
        self.indent = indent
        self.field_list = list(field_list)
        u = Declarative.DeclarativeUI()
        # the items in field_list (field-name/value-type/property-model) will get passed to create_handler in the
        # item parameter. this is accomplished by passing items to create_column below. the item_component_id is
        # used to match this column with the request for a handler.
        self.ui_view = u.create_column(
            u.create_row(u.create_spacing(indent), u.create_label(text=name, width=60), u.create_stretch()),
            u.create_row(u.create_spacing(indent * 4),
                         u.create_column(items="field_list", item_component_id="entity_field", spacing=8)),
            spacing = 8,
        )

    def create_handler(self, component_id: str, container: typing.Optional[Symbolic.ComputationVariable] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        # item is a tuple of field name, value type, and value model. it comes from the field list passed during init.
        if component_id == "entity_field" and item is not None:
            field_name, value_type, value_model = typing.cast(typing.Tuple[str, Schema.FieldType, Model.PropertyModel[typing.Any]], item)
            return make_field_handler(field_name, self.indent, value_type, value_model)
        return None


class MaybePropertyChangedPropertyModel(Model.PropertyModel[typing.Any]):
    """Observes a property on another item and makes it a standard property model.

    When the observed property changes, update this value.

    When this value changes, update the observed property.
    """

    def __init__(self, observable: Observable.Observable, property_name: str) -> None:
        super().__init__(getattr(observable, property_name, None))
        self.__observable = observable
        self.__property_name = property_name

        def property_changed(property_model: MaybePropertyChangedPropertyModel, observable: Observable.Observable, property_name: str, property_name_: str) -> None:
            # check if changed property matches property name for this object
            if property_name_ == property_name:
                property_model.value = getattr(observable, property_name)

        if hasattr(self.__observable, "property_changed_event"):
            self.__listener = self.__observable.property_changed_event.listen(weak_partial(property_changed, self, observable, property_name))

    def _set_value(self, value: typing.Optional[T]) -> None:
        super()._set_value(value)
        # set the property on the observed object. this will trigger a property changed, but will be ignored since
        # the value doesn't change.
        setattr(self.__observable, self.__property_name, value)


class DummyHandler(Declarative.HandlerLike):
    def __init__(self, field_name: str, text: str) -> None:
        u = Declarative.DeclarativeUI()
        self.ui_view = u.create_row(u.create_label(text=field_name, width=60), u.create_label(text=text), u.create_stretch(), spacing=12)

    def close(self) -> None:
        pass


class HasFieldTypeMap(typing.Protocol):
    @property
    def _field_type_map(self) -> typing.Mapping[str, Schema.FieldType]: raise NotImplementedError()


def make_record_handler(item: Observable.Observable, name: str, indent: int, entity_type: HasFieldTypeMap) -> EntityFieldsHandler:
    field_list = [(n, t, MaybePropertyChangedPropertyModel(item, n)) for n, t in entity_type._field_type_map.items()]
    return EntityFieldsHandler(name, indent, field_list)


def make_field_handler(field_name: str, indent: int, value_type: Schema.FieldType, value_model: Model.PropertyModel[typing.Any]) -> typing.Optional[Declarative.HandlerLike]:
    # when item type is property type, create an entity property handler, passing the value type and property model directly.
    if isinstance(value_type, Schema.PropertyType):
        return EntityPropertyHandler(field_name, value_type, value_model)

    # when item type is tuple type, create an entity tuple handler, passing the value type of the tuple and the property model directly.
    # the tuple handler will watch for changes to the property model and update its internal list accordingly.
    if isinstance(value_type, Schema.TupleType):
        return EntityTupleHandler(field_name, indent + 1, value_type.type, value_model)

    # when item type is fixed tuple type, make a list of field-name/value-type/property-model tuples, creating
    # entity value index models to access the individual fields, and recursively create another entity fields
    # handler with the list.
    if isinstance(value_type, Schema.FixedTupleType):
        field_list = [(str(i), t, EntityValueIndexModel(value_model, i)) for i, t in enumerate(value_type.types)]
        return EntityFieldsHandler(field_name, indent + 1, field_list)

    # when item type is record type, use make_record_handler to where the item is the value of the value_model passed
    # to this function.
    if isinstance(value_type, Schema.RecordType):
        if value_model.value is not None:
            return make_record_handler(value_model.value, field_name, indent + 1, value_type)
        else:
            return DummyHandler(field_name, "NONE")

    # when item type is array type, create an entity array handler, passing the value type of the array and the property model directly.
    # the array handler will watch for changes to either the property model or the list value of the property model and update its
    # internal list accordingly.
    if isinstance(value_type, Schema.ArrayType):
        return EntityArrayHandler(field_name, indent + 1, value_type.type, value_model)

    # fall through to a dummy handler.
    return DummyHandler(field_name, str(value_type))


class DataItemHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController, data_item: DataItem.DataItem):
        super().__init__()
        self.document_controller = document_controller
        self.item = data_item
        self.ui_view = self._make_ui()
        self.uuid_converter = Converter.UuidToStringConverter()
        self.date_converter = Converter.DatetimeToStringConverter(is_local=True, format="%Y-%m-%d %H:%M:%S %Z")

    @property
    def display_item(self) -> typing.Optional[DisplayItem.DisplayItem]:
        document_model = self.document_controller.document_model
        return document_model.get_best_display_item_for_data_item(self.item)

    def _make_ui(self) -> Declarative.UIDescriptionResult:
        u = Declarative.DeclarativeUI()
        label = u.create_label(text=self.item.title)
        uuid_row = u.create_row(u.create_label(text="UUID:", width=60), u.create_label(text="@binding(item.uuid, converter=uuid_converter)"), u.create_stretch(), spacing=12)
        modified_row = u.create_row(u.create_label(text="Modified:", width=60), u.create_label(text="@binding(item.modified, converter=date_converter)"), u.create_label(text="(local)"), u.create_stretch(), spacing=12)
        source_line = u.create_component_instance("source_component")
        data_source_chooser = {
            "type": "data_source_chooser",
            "display_item": "@binding(display_item)",
            "min_width": 80,
            "min_height": 80,
        }
        inspector_column = u.create_column(label,
                                           uuid_row,
                                           modified_row,
                                           source_line,
                                           data_source_chooser,
                                           u.create_stretch(),
                                           spacing=12)
        entity_component = u.create_scroll_area(u.create_column(u.create_component_instance("entity_component"), u.create_stretch()))
        return u.create_tabs(
            u.create_tab(_("Data Item"), inspector_column),
            u.create_tab(_("Details"), entity_component),
            style="minimal"
        )

    def create_handler(self, component_id: str, container: typing.Optional[Symbolic.ComputationVariable] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if component_id == "source_component":
            return ReferenceHandler(self.document_controller, _("Source"), self.item.source)
        if component_id == "entity_component":
            return make_record_handler(self.item, DataModel.DataItem.entity_id, 0, DataModel.DataItem)
        return None


class ItemInspectorHandlerFactory(typing.Protocol):
    def make_component(self, item: typing.Any) -> typing.Optional[Declarative.HandlerLike]: ...


class DisplayItemInspectorHandler(Declarative.Handler):
    def __init__(self, display_item: DisplayItem.DisplayItem) -> None:
        super().__init__()

        self.display_item = display_item

        data_source_chooser = {
            "type": "data_source_chooser",
            "display_item": "@binding(display_item)",
            "min_width": 80,
            "min_height": 80,
        }

        self.ui_view = data_source_chooser


class DisplayItemInspectorHandlerFactory(ItemInspectorHandlerFactory):
    def make_component(self, item: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if isinstance(item, DisplayItem.DisplayItem):
            return DisplayItemInspectorHandler(item)
        return None


Registry.register_component(DisplayItemInspectorHandlerFactory(), {"item-inspector-handler-factory"})


class ItemPageHandler(Declarative.Handler):
    def __init__(self,
                 item: typing.Any,
                 entity_type: Schema.EntityType,
                 title: str,
                 item_title_getter: typing.Optional[typing.Callable[[typing.Any], str]] = None) -> None:
        super().__init__()
        self.item = item
        self.__title = title
        self.__entity_type = entity_type
        self.__item_title_getter = item_title_getter
        self.__item_inspector_handler: typing.Optional[Declarative.HandlerLike] = None
        self.uuid_converter = Converter.UuidToStringConverter()
        self.date_converter = Converter.DatetimeToStringConverter(is_local=True, format="%Y-%m-%d %H:%M:%S %Z")
        self.ui_view = self._make_ui()

    def _make_ui(self) -> Declarative.UIDescriptionResult:
        u = Declarative.DeclarativeUI()
        entity_component = u.create_scroll_area(u.create_column(u.create_component_instance("entity_component"), u.create_stretch()))
        for component in Registry.get_components_by_type("item-inspector-handler-factory"):
            item_inspector_handler_factory = typing.cast(ItemInspectorHandlerFactory, component)
            item_inspector_handler = item_inspector_handler_factory.make_component(self.item)
            if item_inspector_handler:
                label = u.create_label(text=self.__item_title_getter(self.item) if self.__item_title_getter else self.__entity_type.entity_id)
                uuid_row = u.create_row(u.create_label(text="UUID:", width=60), u.create_label(text="@binding(item.uuid, converter=uuid_converter)"), u.create_stretch(), spacing=12)
                modified_row = u.create_row(u.create_label(text="Modified:", width=60), u.create_label(text="@binding(item.modified, converter=date_converter)"), u.create_label(text="(local)"), u.create_stretch(), spacing=12)
                self.__item_inspector_handler = item_inspector_handler
                inspector_column = u.create_column(label,
                                                   uuid_row,
                                                   modified_row,
                                                   u.create_component_instance("item_inspector_component"),
                                                   u.create_stretch(),
                                                   spacing=12)
                return u.create_tabs(
                    u.create_tab(self.__title, inspector_column),
                    u.create_tab(_("Details"), entity_component),
                    style="minimal"
                )
        return u.create_tabs(
            u.create_tab(_("Details"), entity_component),
            style="minimal"
        )

    def create_handler(self, component_id: str, container: typing.Optional[Symbolic.ComputationVariable] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if component_id == "entity_component":
            return make_record_handler(self.item, self.__entity_type.entity_id, 0, self.__entity_type)
        if component_id == "item_inspector_component":
            return self.__item_inspector_handler
        return None


class DataStructureHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController, data_structure: DataStructure.DataStructure):
        super().__init__()
        self.document_controller = document_controller
        self.data_structure = data_structure
        self.ui_view = self.__make_ui()
        self.uuid_converter = Converter.UuidToStringConverter()
        self.date_converter = Converter.DatetimeToStringConverter(is_local=True, format="%Y-%m-%d %H:%M:%S %Z")

    def __make_ui(self) -> Declarative.UIDescriptionResult:
        u = Declarative.DeclarativeUI()
        label = u.create_label(text=self.data_structure.structure_type)
        uuid_row = u.create_row(u.create_label(text="UUID:", width=60), u.create_label(text="@binding(data_structure.uuid, converter=uuid_converter)"), u.create_stretch(), spacing=12)
        modified_row = u.create_row(u.create_label(text="Modified:", width=60), u.create_label(text="@binding(data_structure.modified, converter=date_converter)"), u.create_label(text="(local)"), u.create_stretch(), spacing=12)
        entity = self.data_structure.entity
        source_line = u.create_component_instance("source_component")
        if entity and entity.entity_type:
            entity_component = u.create_component_instance("entity_component")
        else:
            label2 = u.create_label(text=entity.entity_type.entity_id if entity else "NO ENTITY")
            label3 = u.create_label(text=str(entity.entity_type._field_type_map) if entity else str(self.data_structure.write_to_dict()["properties"]), max_width=300)
            entity_component = u.create_column(label2, label3, spacing=12)
        return u.create_column(label,
                               uuid_row,
                               modified_row,
                               source_line,
                               entity_component,
                               u.create_stretch(),
                               spacing=12)

    def create_handler(self, component_id: str, container: typing.Optional[Symbolic.ComputationVariable] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if component_id == "source_component":
            return ReferenceHandler(self.document_controller, _("Source"), self.data_structure.source)
        if component_id == "entity_component":
            entity = self.data_structure.entity
            assert entity
            # note: use data structure as the base item of the entity field handler since the entity is not quite
            # properly connected to the data structure. setting a value on the data structure does not send a property
            # changed value from the entity.
            return make_record_handler(self.data_structure, entity.entity_type.entity_id, 0, entity.entity_type)
        return None


DynamicWidgetConstructorFn = typing.Callable[[typing.Any], typing.Optional[Declarative.HandlerLike]]


class DynamicWidget(UserInterface.Widget):
    """Widget which only adds content when the produce when produce_widget is called."""
    def __init__(self, ui: UserInterface.UserInterface, event_loop: asyncio.AbstractEventLoop, component_fn: DynamicWidgetConstructorFn) -> None:
        self.__ui = ui
        self.__event_loop = event_loop
        self.__component_fn = component_fn
        self.__widget = ui.create_column_widget()
        super().__init__(Widgets.CompositeWidgetBehavior(self.__widget))

    def produce_widget(self, item: typing.Any) -> None:
        if self.__widget.child_count == 0:
            handler = self.__component_fn(item)
            if handler:
                self.__widget.add(Declarative.DeclarativeWidget(self.__ui, self.__event_loop, handler))


class DynamicHandler(Declarative.Handler):
    """Dynamic handler which contains a dynamic widget and only makes the widget when produce_widget is called."""
    def __init__(self, item: typing.Any, component_fn: DynamicWidgetConstructorFn) -> None:
        super().__init__()
        self.__item = item
        self.component_fn = component_fn
        self.ui_view = {"type": "dynamic", "name": "dynamic_widget"}
        self.dynamic_widget: typing.Optional[DynamicWidget] = None

    def produce_widget(self) -> None:
        if self.dynamic_widget:
            self.dynamic_widget.produce_widget(self.__item)


class DynamicDeclarativeWidgetConstructor:
    def construct(self, d_type: str, ui: UserInterface.UserInterface, window: typing.Optional[Window.Window],
                  d: Declarative.UIDescription, handler: Declarative.HandlerLike,
                  finishes: typing.List[typing.Callable[[], None]]) -> typing.Optional[UserInterface.Widget]:
        if d_type == "dynamic":
            assert window
            widget = DynamicWidget(ui, window.event_loop, typing.cast(DynamicHandler, handler).component_fn)
            if "name" in d:
                setattr(handler, d["name"], widget)
            return widget
        return None


Registry.register_component(DynamicDeclarativeWidgetConstructor(), {"declarative_constructor"})


class MasterDetailHandler(Declarative.Handler):

    def __init__(self, model: Observable.Observable, items_key: str, component_fn: DynamicWidgetConstructorFn,
                 title_getter: typing.Callable[[typing.Any], str]) -> None:
        super().__init__()

        self.__component_fn = component_fn

        # the items for which the details are displayed.
        self.items_model = model

        self.titles_model = ListModel.MappedListModel(container=self.items_model,
                                                      master_items_key=items_key,
                                                      map_fn=title_getter)

        self.__labels_property_model = ListModel.ListPropertyModel(self.titles_model)

        # set up a shadow list following the model/items_key

        def make_shadow(item: typing.Any) -> typing.Any:
            return DynamicHandler(item, component_fn)

        self.shadow_items = ListModel.MappedListModel(container=self.items_model,
                                                      master_items_key=items_key,
                                                      map_fn=make_shadow)

        # the selected item in the items_model
        self.index_model = Model.PropertyModel(0)

        u = Declarative.DeclarativeUI()

        item_list = u.create_list_box(items_ref="@binding(titles_model.items)",
                                      current_index="@binding(index_model.value)",
                                      width=160, min_height=480,
                                      size_policy_vertical="expanding")

        item_stack = u.create_stack(items=f"items_model.{items_key}", item_component_id="detail", current_index="@binding(index_model.value)")

        self.ui_view = u.create_row(u.create_column(item_list), u.create_column(item_stack), spacing=12)

        self._detail_components: typing.Dict[typing.Any, typing.Optional[Declarative.HandlerLike]] = dict()

        def index_changed(property: str) -> None:
            if property == "value":
                self.__update_dynamic_widget()

        self.__listener = self.index_model.property_changed_event.listen(index_changed)

    def __update_dynamic_widget(self) -> None:
        index = self.index_model.value or 0
        if 0 <= index < len(self.shadow_items.items):
            typing.cast(DynamicHandler, self.shadow_items.items[index]).produce_widget()

    def init_handler(self) -> None:
        self.__update_dynamic_widget()

    def create_handler(self, component_id: str, container: typing.Optional[ListModel.ListModel[Declarative.HandlerLike]] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if component_id == "detail":
            assert container
            handler = typing.cast(Declarative.HandlerLike, self.shadow_items.items[container.items.index(item)])
            self._detail_components[item] = handler
            return handler
        return None

    def get_binding(self, source: Observable.Observable, property: str, converter: typing.Optional[Converter.ConverterLike[typing.Any, typing.Any]]) -> typing.Optional[Binding.Binding]:
        if source == self.titles_model and property == "items":
            return Binding.PropertyBinding(self.__labels_property_model, "value", converter=converter)
        return None


class ProjectItemsEntry:
    def __init__(self, title: str, document_model: Observable.Observable, master_items_key: str, component_fn: DynamicWidgetConstructorFn,
                 title_getter: typing.Callable[[typing.Any], str]) -> None:
        model = ListModel.FilteredListModel(container=document_model, master_items_key=master_items_key)
        model.sort_key = operator.attrgetter("modified")
        model.sort_reverse = True
        self.model = model
        self.items_key = "items"
        self.component_fn = component_fn
        self.title_getter = title_getter
        self.label = title


def make_master_detail(project_item_handler: ProjectItemsEntry) -> Declarative.HandlerLike:
    return MasterDetailHandler(project_item_handler.model, project_item_handler.items_key, project_item_handler.component_fn, project_item_handler.title_getter)


class ProjectItemsContent(Declarative.Handler):

    def __init__(self, item: typing.Any) -> None:
        super().__init__()
        self.__item = item
        u = Declarative.DeclarativeUI()
        self.ui_view = u.create_component_instance(identifier="content")
        self._master_detail_handler = make_master_detail(self.__item)

    def create_handler(self, component_id: str, container: typing.Optional[Symbolic.ComputationVariable] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if component_id == "content":
            return self._master_detail_handler
        return None


ProjectExtra = Schema.entity("project_extra", None, 3, {
    "title": Schema.prop(Schema.STRING),
    "workspace": Schema.reference(DataModel.Workspace),
    "data_item_references": Schema.map(Schema.STRING, Schema.reference(DataModel.DataItem)),
    "mapped_items": Schema.array(Schema.reference(DataModel.DataItem), Schema.OPTIONAL),
    "project_data_folders": Schema.array(Schema.prop(Schema.PATH)),
})


class ProjectItemsDialog(Declarative.WindowHandler):

    def __init__(self, document_controller: DocumentController.DocumentController) -> None:
        super().__init__()

        self.__document_controller = document_controller

        self.dialog_id = "project_items"

        self.items_model = ListModel.ListModel[ProjectItemsEntry]()

        def create_computation_handler(item: Symbolic.Computation) -> typing.Optional[Declarative.HandlerLike]:
            return ComputationHandler(document_controller, item)

        def create_data_structure_handler(item: DataStructure.DataStructure) -> typing.Optional[Declarative.HandlerLike]:
            return DataStructureHandler(document_controller, item)

        def create_data_item_handler(item: DataItem.DataItem) -> typing.Optional[Declarative.HandlerLike]:
            return DataItemHandler(document_controller, item)

        def create_display_item_handler(item: DisplayItem.DisplayItem) -> typing.Optional[Declarative.HandlerLike]:
            return ItemPageHandler(item, DataModel.DisplayItem, _("Display Item"), operator.attrgetter("title"))

        def create_connection_handler(item: Connection.Connection) -> typing.Optional[Declarative.HandlerLike]:
            return ItemPageHandler(item, DataModel.Connection, _("Connection"))

        def create_data_group_handler(item: DataGroup.DataGroup) -> typing.Optional[Declarative.HandlerLike]:
            return ItemPageHandler(item, DataModel.DataGroup, _("Data Group"), operator.attrgetter("title"))

        def create_project_handler(item: Project.Project) -> typing.Optional[Declarative.HandlerLike]:
            return ItemPageHandler(item, ProjectExtra, _("Project"), operator.attrgetter("title"))

        def create_workspace_handler(item: WorkspaceLayout.WorkspaceLayout) -> typing.Optional[Declarative.HandlerLike]:
            return ItemPageHandler(item, DataModel.Workspace, _("Workspace"), operator.attrgetter("name"))

        self.items_model.append_item(
            ProjectItemsEntry(_("Computations"), document_controller.document_model, "computations",
                              create_computation_handler, operator.attrgetter("label")))
        self.items_model.append_item(
            ProjectItemsEntry(_("Data Structures"), document_controller.document_model, "data_structures",
                              create_data_structure_handler, operator.attrgetter("structure_type")))
        self.items_model.append_item(
            ProjectItemsEntry(_("Data Items"), document_controller.document_model, "data_items",
                              create_data_item_handler, operator.attrgetter("title")))
        self.items_model.append_item(
            ProjectItemsEntry(_("Display Items"), document_controller.document_model, "display_items",
                              create_display_item_handler, operator.attrgetter("title")))
        self.items_model.append_item(
            ProjectItemsEntry(_("Connections"), document_controller.document_model, "connections",
                              create_connection_handler, lambda x: str(x.uuid)))
        self.items_model.append_item(
            ProjectItemsEntry(_("Data Groups"), document_controller.document_model, "data_groups",
                              create_data_group_handler, operator.attrgetter("title")))
        self.items_model.append_item(
            ProjectItemsEntry(_("Projects"), typing.cast(typing.Any, document_controller.app).profile, "projects",
                              create_project_handler, operator.attrgetter("title")))
        self.items_model.append_item(
            ProjectItemsEntry(_("Workspaces"), document_controller.project, "workspaces",
                              create_workspace_handler, operator.attrgetter("name")))

        # close any previous list dialog associated with the window
        previous_window = getattr(document_controller, f"_{self.dialog_id}_dialog", None)
        if isinstance(previous_window, ProjectItemsDialog):
            previous_window.close_window()
        setattr(document_controller, f"_{self.dialog_id}_dialog", self)

        self.__master_detail_handler = MasterDetailHandler(self.items_model, "items", typing.cast(DynamicWidgetConstructorFn, ProjectItemsContent), operator.attrgetter("label"))

        u = Declarative.DeclarativeUI()

        window = u.create_window(u.create_component_instance(identifier="content"), title=_("Project Items (Computations)"), margin=12, window_style="tool")
        self.run(window, parent_window=document_controller, persistent_id=self.dialog_id)
        self.__document_controller.register_dialog(self.window)

    def close(self) -> None:
        setattr(self.__document_controller, f"_{self.dialog_id}_dialog", None)
        super().close()

    def create_handler(self, component_id: str, container: typing.Optional[Symbolic.ComputationVariable] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if component_id == "content":
            return self.__master_detail_handler
        return None

    def open_project_item(self, item: Persistence.PersistentObject) -> None:
        for index, project_items in enumerate(self.items_model.items):
            if item in project_items.model.items:
                self.__master_detail_handler.index_model.value = index
                item_index = project_items.model.items.index(item)
                content_handler = typing.cast(ProjectItemsContent, self.__master_detail_handler._detail_components[self.items_model._items[self.__master_detail_handler.index_model.value]])
                detail_handler = typing.cast(MasterDetailHandler, content_handler._master_detail_handler)
                detail_handler.index_model.value = item_index
        print(f"open project item {item}")
