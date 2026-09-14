from __future__ import annotations

# standard libraries
import asyncio
import collections
import datetime
import gettext
import math
import sys
import typing
import uuid
import weakref

# third party libraries
# None

# local libraries
from nion.data import Calibration
from nion.swift import DisplayPanel
from nion.swift import EntityBrowser
from nion.swift import GraphicsInspector
from nion.swift import MimeTypes
from nion.swift import Undo
from nion.swift.model import DataItem
from nion.swift.model import DataStructure
from nion.swift.model import DisplayInfo
from nion.swift.model import DisplayItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import Persistence
from nion.swift.model import Schema
from nion.swift.model import Symbolic
from nion.swift.model import Utility
from nion.ui import Declarative
from nion.ui import UserInterface
from nion.utils import Binding
from nion.utils import Converter
from nion.utils import Geometry
from nion.utils import ListModel
from nion.utils import Model
from nion.utils import Observable
from nion.utils import ReferenceCounting
from nion.utils import Registry
from nion.utils import Stream
from nion.utils import Validator

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController

_ = gettext.gettext


class ChangeComputationVariableCommand(Undo.UndoableCommand):

    def __init__(self, document_model: DocumentModel.DocumentModel, computation: Symbolic.Computation,
                 variable: Symbolic.ComputationVariable, *, title: typing.Optional[str] = None,
                 command_id: typing.Optional[str] = None, is_mergeable: bool = False, **kwargs: typing.Any) -> None:
        super().__init__(title if title else _("Change Computation Variable"), command_id=command_id, is_mergeable=is_mergeable)
        self.__document_model = document_model
        self.__computation_proxy = computation.create_proxy()
        self.__variable_index = computation.variables.index(variable)
        self.__properties = variable.save_properties()
        self.__value_dict = kwargs
        self.initialize()

    def close(self) -> None:
        self.__document_model = typing.cast(typing.Any, None)
        self.__computation_proxy.close()
        self.__computation_proxy = typing.cast(typing.Any, None)
        self.__variable_index = typing.cast(typing.Any, None)
        if self.__properties[1]:
            self.__properties[1].close()
        if self.__properties[2]:
            self.__properties[2].close()
        self.__properties = typing.cast(typing.Any, None)
        self.__value_dict = typing.cast(typing.Any, None)
        super().close()

    def _perform(self) -> None:
        computation = self.__computation_proxy.item
        if computation:
            variable = computation.variables[self.__variable_index]
            for key, value in self.__value_dict.items():
                setattr(variable, key, value)

    def _get_modified_state(self) -> typing.Any:
        computation = self.__computation_proxy.item
        variable = computation.variables[self.__variable_index] if computation else None
        return variable.modified_state if variable else None, self.__document_model.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        computation = self.__computation_proxy.item
        variable = computation.variables[self.__variable_index] if computation else None
        if variable:
            variable.modified_state = modified_state[0]
        self.__document_model.modified_state = modified_state[1]

    def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return bool(state1[0] == state2[0])

    def _undo(self) -> None:
        computation = self.__computation_proxy.item
        if computation:
            variable = computation.variables[self.__variable_index]
            properties = self.__properties
            self.__properties = variable.save_properties()
            variable.restore_properties(properties)

    @property
    def __computation_uuid(self) -> typing.Optional[uuid.UUID]:
        computation = self.__computation_proxy.item if self.__computation_proxy else None
        return computation.uuid if computation else None

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, self.__class__) and bool(self.command_id) and self.command_id == command.command_id and self.__computation_uuid == command.__computation_uuid and self.__variable_index == command.__variable_index


class VariableHandlerComponentFactory(typing.Protocol):
    # keep this around until no one is using it. new variable handler components should preference VariableHandlerComponentFactory2.
    def make_variable_handler(self, document_controller: DocumentController.DocumentController, computation: Symbolic.Computation, computation_variable: Symbolic.ComputationVariable, variable_model: VariableValueModel) -> typing.Optional[Declarative.HandlerLike]: ...


class VariableHandlerComponentFactory2(typing.Protocol):
    def make_variable_handler(self, computation_inspector_context: ComputationInspectorContext, computation: Symbolic.Computation, computation_variable: Symbolic.ComputationVariable, variable_model: VariableValueModel, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]: ...


class VariableValueModel(Observable.Observable):
    def __init__(self, document_controller: DocumentController.DocumentController, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable) -> None:
        super().__init__()
        self.__document_controller = document_controller
        self.__computation = computation
        self.__variable = variable
        self.__variable_listener = variable.property_changed_event.listen(ReferenceCounting.weak_partial(VariableValueModel.__property_changed, self))

    def __property_changed(self, key: str) -> None:
        self.notify_property_changed(key)

    @property
    def value(self) -> typing.Any:
        return self.__variable.value

    @value.setter
    def value(self, value: typing.Any) -> None:
        document_controller = self.__document_controller
        computation = self.__computation
        variable = self.__variable
        if value != variable.value:
            command = ChangeComputationVariableCommand(document_controller.document_model, computation, variable, value=value)
            command.perform()
            document_controller.push_undo_command(command)


class BooleanVariableHandler(Declarative.Handler):
    def __init__(self, computation_variable: Symbolic.ComputationVariable, variable_model: VariableValueModel) -> None:
        super().__init__()
        self.variable = computation_variable
        self.variable_model = variable_model
        u = Declarative.DeclarativeUI()
        checkbox = u.create_check_box(text="@binding(variable.display_label)", checked="@binding(variable_model.value)", widget_id="value")
        self.ui_view = checkbox


class BooleanVariableHandlerFactory(VariableHandlerComponentFactory2):
    def make_variable_handler(self, computation_inspector_context: ComputationInspectorContext, computation: Symbolic.Computation, computation_variable: Symbolic.ComputationVariable, variable_model: VariableValueModel, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if computation_variable.variable_type == Symbolic.ComputationVariableType.BOOLEAN:
            return BooleanVariableHandler(computation_variable, variable_model)
        return None


class IntegerSliderVariableHandler(Declarative.Handler):
    def __init__(self, variable: Symbolic.ComputationVariable, variable_model: VariableValueModel) -> None:
        super().__init__()
        self.variable = variable
        self.variable_model = variable_model
        self.int_str_converter = Converter.IntegerToStringConverter()
        u = Declarative.DeclarativeUI()
        label = u.create_label(text="@binding(variable.display_label)")
        slider = u.create_slider(value="@binding(variable_model.value)", minimum=variable.value_min, maximum=variable.value_max, widget_id="slider_value")
        line_edit = u.create_line_edit(text="@binding(variable_model.value, converter=int_str_converter)", width=60, widget_id="value")
        self.ui_view = u.create_column(label, slider, line_edit, spacing=8)


class IntegerVariableHandler(Declarative.Handler):
    def __init__(self, variable: Symbolic.ComputationVariable, variable_model: VariableValueModel) -> None:
        super().__init__()
        self.variable = variable
        self.variable_model = variable_model
        self.int_str_converter = Converter.IntegerToStringConverter()
        u = Declarative.DeclarativeUI()
        label = u.create_label(text="@binding(variable.display_label)")
        line_edit = u.create_line_edit(text="@binding(variable_model.value, converter=int_str_converter)", width=60, widget_id="value")
        self.ui_view = u.create_column(label, line_edit, spacing=8)


class IntegerVariableHandlerFactory(VariableHandlerComponentFactory2):
    def make_variable_handler(self, computation_inspector_context: ComputationInspectorContext, computation: Symbolic.Computation, computation_variable: Symbolic.ComputationVariable, variable_model: VariableValueModel, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if computation_variable.variable_type == Symbolic.ComputationVariableType.INTEGRAL and computation_variable.has_range:
            return IntegerSliderVariableHandler(computation_variable, variable_model)
        elif computation_variable.variable_type == Symbolic.ComputationVariableType.INTEGRAL:
            return IntegerVariableHandler(computation_variable, variable_model)
        return None


class RealSliderVariableHandler(Declarative.Handler):
    def __init__(self, variable: Symbolic.ComputationVariable, variable_model: VariableValueModel) -> None:
        super().__init__()
        self.variable = variable
        self.variable_model = variable_model
        self.slider_converter = Converter.FloatToScaledIntegerConverter(2000, variable.value_min, variable.value_max)
        self.float_str_converter = Converter.FloatToStringConverter()
        u = Declarative.DeclarativeUI()
        label = u.create_label(text="@binding(variable.display_label)")
        slider = u.create_slider(value="@binding(variable_model.value, converter=slider_converter)", minimum=0, maximum=2000, widget_id="slider_value")
        line_edit = u.create_line_edit(text="@binding(variable_model.value, converter=float_str_converter)", width=60, widget_id="value")
        self.ui_view = u.create_column(label, slider, line_edit, spacing=8)


class RealVariableHandler(Declarative.Handler):
    def __init__(self, variable: Symbolic.ComputationVariable, variable_model: VariableValueModel) -> None:
        super().__init__()
        self.variable = variable
        self.variable_model = variable_model
        self.float_str_converter = Converter.FloatToStringConverter()
        u = Declarative.DeclarativeUI()
        label = u.create_label(text="@binding(variable.display_label)")
        line_edit = u.create_line_edit(text="@binding(variable_model.value, converter=float_str_converter)", width=60, widget_id="value")
        self.ui_view = u.create_column(label, line_edit, spacing=8)


class RealVariableHandlerFactory(VariableHandlerComponentFactory2):
    def make_variable_handler(self, computation_inspector_context: ComputationInspectorContext, computation: Symbolic.Computation, computation_variable: Symbolic.ComputationVariable, variable_model: VariableValueModel, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if computation_variable.variable_type == Symbolic.ComputationVariableType.REAL and computation_variable.has_range:
            return RealSliderVariableHandler(computation_variable, variable_model)
        elif computation_variable.variable_type == Symbolic.ComputationVariableType.REAL:
            return RealVariableHandler(computation_variable, variable_model)
        return None


class ChoiceVariableHandler(Declarative.Handler):
    def __init__(self, variable: Symbolic.ComputationVariable, variable_model: VariableValueModel) -> None:
        super().__init__()
        self.variable = variable
        self.variable_model = variable_model
        self.float_str_converter = Converter.FloatToStringConverter()
        u = Declarative.DeclarativeUI()
        label = u.create_label(text="@binding(variable.display_label)")
        combo_box = u.create_row(u.create_combo_box(items=[_("None"), _("Mapped")], current_index="@binding(combo_box_index)"), u.create_stretch())
        self.ui_view = u.create_column(label, combo_box, spacing=8)
        self.__variable_listener = variable.property_changed_event.listen(ReferenceCounting.weak_partial(ChoiceVariableHandler.__property_changed, self))

    def close(self) -> None:
        self.__variable_listener = typing.cast(typing.Any, None)
        super().close()

    def __property_changed(self, key: str) -> None:
        self.notify_property_changed("combo_box_index")

    @property
    def combo_box_index(self) -> int:
        if self.variable_model.value == "mapped":
            return 1
        return 0

    @combo_box_index.setter
    def combo_box_index(self, value: int) -> None:
        if value == 1:
            self.variable_model.value = "mapped"
        else:
            self.variable_model.value = "none"


class StringVariableHandler(Declarative.Handler):
    def __init__(self, variable: Symbolic.ComputationVariable, variable_model: VariableValueModel) -> None:
        super().__init__()
        self.variable = variable
        self.variable_model = variable_model
        u = Declarative.DeclarativeUI()
        label = u.create_label(text="@binding(variable.display_label)")
        line_edit = u.create_line_edit(text="@binding(variable_model.value)", width=60, widget_id="value")
        self.ui_view = u.create_column(label, line_edit, spacing=8)


class StringVariableHandlerFactory(VariableHandlerComponentFactory2):
    def make_variable_handler(self, computation_inspector_context: ComputationInspectorContext, computation: Symbolic.Computation, computation_variable: Symbolic.ComputationVariable, variable_model: VariableValueModel, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if computation_variable.variable_type == Symbolic.ComputationVariableType.STRING and computation_variable.control_type == "choice":
            return ChoiceVariableHandler(computation_variable, variable_model)
        if computation_variable.variable_type == Symbolic.ComputationVariableType.STRING:
            return StringVariableHandler(computation_variable, variable_model)
        return None


class DataSourceVariableHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable, variable_model: VariableValueModel) -> None:
        super().__init__()
        self.document_controller = document_controller
        self.computation = computation
        self.variable = variable
        self.variable_model = variable_model
        self.is_croppable = False
        if computation_processor := computation.computation_processor:
            if source_description := computation_processor.get_source(variable.name):
                self.is_croppable = source_description.is_croppable
        u = Declarative.DeclarativeUI()
        label = u.create_label(text="@binding(variable.display_label)")
        data_source_chooser = {
            "type": "data_source_chooser",
            "display_item": "@binding(display_item)",
            "on_drop_mime_data": "drop_mime_data",
            "on_delete": "data_item_delete",
            "min_width": 80,
            "min_height": 80,
            "is_croppable": "@binding(is_croppable)",
            "crop_enabled": "@binding(crop_enabled)",
            "on_crop_enabled_clicked": "handle_toggle_crop_enabled"
        }
        axis_set_chooser = u.create_column(
            u.create_label(text=_("Input Operation")),
            u.create_combo_box(items_ref="input_operation_items", current_index="@binding(input_operation_index)"),
            u.create_stretch(),
            # Show input operation choices only when this source can iterate across axis sets.
            visible = "@binding(variable.is_iterable)"
        )
        self.ui_view = u.create_column(label, data_source_chooser, axis_set_chooser, spacing=8)
        self.__property_changed_listener = variable.property_changed_event.listen(self.__property_changed)

    def close(self) -> None:
        self.__property_changed_listener = typing.cast(typing.Any, None)
        super().close()

    def __property_changed(self, property_name: str) -> None:
        if property_name in ("specified_object", "secondary_specified_object"):
            self.property_changed_event.fire("display_item")
        if property_name in ("secondary_specified_object",):
            self.property_changed_event.fire("crop_enabled")

    def handle_toggle_crop_enabled(self, widget: Declarative.UIWidget) -> None:
        display_item = self.display_item
        selected_graphic = display_item.selected_graphic if display_item else None
        selected_crop_graphic = selected_graphic if isinstance(selected_graphic, Graphics.RectangleTypeGraphic) else None
        all_graphics = display_item.graphics if display_item else list()
        all_rect_graphics = (graphic for graphic in all_graphics if isinstance(graphic, Graphics.RectangleTypeGraphic))
        first_rect_graphic = next(all_rect_graphics, None)
        selected_crop_graphic = selected_crop_graphic if selected_crop_graphic else first_rect_graphic
        # implement the toggle logic.
        # if there is a selected crop graphic, and it is not already assigned rectangle, assign it, replacing the old one.
        # otherwise, if there is a selected crop graphic, and it is already assigned rectangle, remove it. (toggle)
        # otherwise, if there is no selected crop graphic, add a new crop rectangle and assign it.
        # this behavior allows the user to toggle the selected rectangle on/off, select a new rectangle and assign it,
        # or add a new rectangle or use the first known rectangle and assign it.
        if selected_crop_graphic and selected_crop_graphic != self.variable.secondary_specified_object:
            self.assign_crop_rectangle(selected_crop_graphic)
        elif self.variable.secondary_specified_object:
            self.remove_crop_rectangle()
        else:
            self.add_crop_rectangle()

    def handle_new_crop(self, widget: Declarative.UIWidget) -> None:
        self.add_crop_rectangle()

    def handle_remove_crop(self, widget: Declarative.UIWidget) -> None:
        self.remove_crop_rectangle()

    def handle_assign_crop(self, widget: Declarative.UIWidget) -> None:
        display_item = self.display_item
        selected_graphic = display_item.selected_graphic if display_item else None
        selected_crop_graphic = selected_graphic if isinstance(selected_graphic, Graphics.RectangleTypeGraphic) else None
        if selected_crop_graphic:
            self.assign_crop_rectangle(selected_crop_graphic)

    def remove_crop_rectangle(self) -> None:
        document_controller = self.document_controller
        computation = self.computation
        variable = self.variable
        display_item = self.display_item
        data_item = display_item.data_item if display_item else None
        if data_item and display_item:
            properties = {"variable_type": "data_source", "secondary_specified_object": None,
                          "specified_object": display_item.get_display_data_channel_for_data_item(data_item)}
            command = ChangeComputationVariableCommand(document_controller.document_model, computation,
                                                       variable, title=_("Set Input Data Source"),
                                                       **properties)  # type: ignore
            command.perform()
            document_controller.push_undo_command(command)

    def add_crop_rectangle(self) -> None:
        document_controller = self.document_controller
        computation = self.computation
        variable = self.variable
        display_item = self.display_item
        data_item = display_item.data_item if display_item else None
        if data_item and display_item:
            graphic = Graphics.RectangleGraphic()
            graphic.bounds = Geometry.FloatRect(Geometry.FloatPoint(0.25, 0.25), Geometry.FloatSize(0.5, 0.5))
            command = DisplayPanel.InsertGraphicsCommand(document_controller, display_item, [graphic])
            command.perform()
            document_controller.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            properties = {"variable_type": "data_source", "secondary_specified_object": graphic,
                          "specified_object": display_item.get_display_data_channel_for_data_item(data_item)}
            command = ChangeComputationVariableCommand(document_controller.document_model, computation,
                                                       variable, title=_("Set Input Data Source"),
                                                       **properties)  # type: ignore
            command.perform()
            document_controller.push_undo_command(command)

    def assign_crop_rectangle(self, crop_graphic: Graphics.RectangleTypeGraphic) -> None:
        document_controller = self.document_controller
        computation = self.computation
        variable = self.variable
        display_item = self.display_item
        data_item = display_item.data_item if display_item else None
        if data_item and display_item:
            properties = {"variable_type": "data_source", "secondary_specified_object": crop_graphic,
                          "specified_object": display_item.get_display_data_channel_for_data_item(data_item)}
            command = ChangeComputationVariableCommand(document_controller.document_model, computation,
                                                       variable, title=_("Set Input Data Source"),
                                                       **properties)  # type: ignore
            command.perform()
            document_controller.push_undo_command(command)

    @property
    def data_item(self) -> typing.Optional[DataItem.DataItem]:
        computation = self.computation
        variable = self.variable
        base_items = computation.get_variable_input_items(variable.name)
        data_item = None
        for base_item in base_items:
            if isinstance(base_item, DataItem.DataItem):
                if data_item:  # check if there are more than one
                    return None
                data_item = base_item
        return data_item

    @property
    def display_item(self) -> typing.Optional[DisplayItem.DisplayItem]:
        data_item = self.data_item
        if data_item:
            document_model = self.document_controller.document_model
            return document_model.get_display_item_for_data_item(data_item)
        return None

    @display_item.setter
    def display_item(self, value: DisplayItem.DisplayItem) -> None:
        pass  # handled separately

    @property
    def crop_enabled(self) -> bool:
        return self.variable.secondary_specified_object is not None

    @crop_enabled.setter
    def crop_enabled(self, value: bool) -> None:
        pass

    @property
    def input_operation_items_state(self) -> tuple[typing.Sequence[tuple[Symbolic.ComputationInputOperation, str]], int | None]:
        """Build selectable input operation choices and current selection for iterable data-source inputs."""
        display_item = self.display_item
        choices = list[tuple[Symbolic.ComputationInputOperation, str]]()
        computation_processor = self.computation.computation_processor
        processor_data_input = computation_processor.get_source(self.variable.name) if computation_processor else None
        display_info = display_item.display_info_stream.value if display_item else None
        display_data_info = display_info.display_data_info if display_info else None
        data_metadata = display_data_info.data_metadata if display_data_info else None
        element_data_and_metadata = display_data_info.element_data_and_metadata if display_data_info else None
        element_data_metadata = element_data_and_metadata.data_metadata if element_data_and_metadata else None
        # for each type of input, check whether it meets the requirements of the processor data input
        if element_data_metadata and processor_data_input:
            if Symbolic._check_requirements(element_data_metadata, processor_data_input.requirements):
                operation_name = _("Displayed Data")
                choices.append((Symbolic.ComputationInputOperation.create_display_operation(), f"{operation_name} {element_data_metadata.data_shape}"))
        if data_metadata and processor_data_input:
            axis_set_data_metadata_list = Symbolic.get_axis_set_data_metadata_list(data_metadata)
            if "datum" in axis_set_data_metadata_list and Symbolic._check_requirements(axis_set_data_metadata_list["datum"], processor_data_input.requirements):
                operation_name = _("Datum Axes")
                axis_set_data_metadata = axis_set_data_metadata_list["datum"]
                choices.append((Symbolic.ComputationInputOperation.create_axis_set_operation("datum"), f"{operation_name} {axis_set_data_metadata.data_shape}"))
            if "collection" in axis_set_data_metadata_list and Symbolic._check_requirements(axis_set_data_metadata_list["collection"], processor_data_input.requirements):
                operation_name = _("Collection Axes")
                axis_set_data_metadata = axis_set_data_metadata_list["collection"]
                choices.append((Symbolic.ComputationInputOperation.create_axis_set_operation("collection"), f"{operation_name} {axis_set_data_metadata.data_shape}"))
            if "sequence" in axis_set_data_metadata_list and Symbolic._check_requirements(axis_set_data_metadata_list["sequence"], processor_data_input.requirements):
                operation_name = _("Sequence Axes")
                axis_set_data_metadata = axis_set_data_metadata_list["sequence"]
                choices.append((Symbolic.ComputationInputOperation.create_axis_set_operation("sequence"), f"{operation_name} {axis_set_data_metadata.data_shape}"))
            if Symbolic._check_requirements(data_metadata, processor_data_input.requirements):
                operation_name = _("None")
                choices.append((Symbolic.ComputationInputOperation(), f"{operation_name} {data_metadata.data_shape}"))
        selection: int | None = None
        input_operation = self.variable.input_operation
        for index, choice in enumerate(choices):
            if choice[0].operation_id == input_operation.operation_id:
                selection = index
                break
        return tuple(choices), selection

    @property
    def input_operation_items(self) -> typing.Sequence[str]:
        choices, _ = self.input_operation_items_state
        return [choice[1] for choice in choices]

    @property
    def input_operation_index(self) -> int | None:
        _, selection = self.input_operation_items_state
        return selection

    @input_operation_index.setter
    def input_operation_index(self, value: int | None) -> None:
        choices, _selected_index = self.input_operation_items_state
        if value is not None and 0 <= value < len(choices):
            input_operation = choices[value][0]
            document_controller = self.document_controller
            computation = self.computation
            variable = self.variable
            command = ChangeComputationVariableCommand(document_controller.document_model, computation, variable, title=_("Change Input Operation"), input_operation=input_operation)
            command.perform()
            document_controller.push_undo_command(command)

    def drop_mime_data(self, mime_data: UserInterface.MimeData, x: int, y: int) -> typing.Optional[str]:
        # return drop_mime_data(self.document_controller, self.computation, self.variable, mime_data, x, y)
        document_controller = self.document_controller
        computation = self.computation
        variable = self.variable
        display_item, graphic = MimeTypes.mime_data_get_data_source(mime_data, document_controller.document_model)
        data_item = display_item.data_item if display_item else None
        if data_item and display_item:
            properties = {"variable_type": "data_source", "secondary_specified_object": graphic,
                          "specified_object": display_item.get_display_data_channel_for_data_item(data_item)}
            command = ChangeComputationVariableCommand(document_controller.document_model, computation,
                                                       variable, title=_("Set Input Data Source"),
                                                       **properties)  # type: ignore
            command.perform()
            document_controller.push_undo_command(command)
            return "copy"
        display_item = MimeTypes.mime_data_get_display_item(mime_data, document_controller.document_model)
        data_item = display_item.data_item if display_item else None
        if data_item and display_item:
            properties = {"variable_type": "data_source", "secondary_specified_object": None,
                          "specified_object": display_item.get_display_data_channel_for_data_item(data_item)}
            command = ChangeComputationVariableCommand(document_controller.document_model, computation,
                                                       variable, title=_("Set Input Data Source"),
                                                       **properties)  # type: ignore
            command.perform()
            document_controller.push_undo_command(command)
            return "copy"
        return "ignore"

    def data_item_delete(self) -> None:
        document_controller = self.document_controller
        computation = self.computation
        variable = self.variable
        command = ChangeComputationVariableCommand(document_controller.document_model, computation, variable,
                                                   title=_("Remove Input Data Source"), specified_object=None)
        command.perform()
        document_controller.push_undo_command(command)


class DataSourceVariableHandlerFactory(VariableHandlerComponentFactory2):
    def make_variable_handler(self, computation_inspector_context: ComputationInspectorContext, computation: Symbolic.Computation, computation_variable: Symbolic.ComputationVariable, variable_model: VariableValueModel, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if computation_variable.variable_type in Symbolic._data_source_types:
            return DataSourceVariableHandler(computation_inspector_context.window, computation, computation_variable, variable_model)
        return None


class ClosingTuplePropertyBinding(Binding.TuplePropertyBinding):
    def __init__(self, source: Observable.Observable, property_name: str, tuple_index: int,
                 converter: typing.Optional[typing.Optional[Converter.ConverterLike[typing.Any, typing.Any]]] = None,
                 fallback: typing.Any = None) -> None:
        super().__init__(source, property_name, tuple_index, converter=converter, fallback=fallback)

        def finalize(source: Observable.Observable) -> None:
            source.close()  # type: ignore  # observable closeable

        weakref.finalize(self, finalize, source)


class ClosingPropertyBinding(Binding.PropertyBinding):
    def __init__(self, source: Observable.Observable, property_name: str, *,
                 converter: typing.Optional[Converter.ConverterLike[typing.Any, typing.Any]] = None,
                 validator: typing.Optional[Validator.ValidatorLike[typing.Any]] = None,
                 fallback: typing.Optional[typing.Any] = None) -> None:
        super().__init__(source, property_name, converter=converter, validator=validator, fallback=fallback)

        def finalize(source: Observable.Observable) -> None:
            source.close()  # type: ignore  # observable closeable

        weakref.finalize(self, finalize, source)


class ChangeGraphicPropertyBinding(Binding.PropertyBinding):
    def __init__(self, document_controller: DocumentController.DocumentController,
                 display_item: DisplayItem.DisplayItem, graphic: Graphics.Graphic, property_name: str,
                 converter: typing.Optional[Converter.ConverterLike[typing.Any, typing.Any]] = None,
                 fallback: typing.Any = None) -> None:
        super().__init__(graphic, property_name, converter=converter, fallback=fallback)
        self.__display_item_proxy = display_item.create_proxy()
        self.__graphic_proxy = graphic.create_proxy()
        self.__document_controller = document_controller
        self.__property_name = property_name
        self.__old_source_setter = self.source_setter
        self.__old_source_getter = self.source_getter
        self.source_setter = ReferenceCounting.weak_partial(ChangeGraphicPropertyBinding.__set_value, self)
        self.source_getter = ReferenceCounting.weak_partial(ChangeGraphicPropertyBinding.__get_value, self)

        def finalize(display_item_proxy: Persistence.PersistentObjectProxy[DisplayItem.DisplayItem], graphic_proxy: Persistence.PersistentObjectProxy[Graphics.Graphic]) -> None:
            display_item_proxy.close()
            graphic_proxy.close()

        weakref.finalize(self, finalize, self.__display_item_proxy, self.__graphic_proxy)

    def __get_value(self) -> typing.Any:
        display_item = self.__display_item_proxy.item
        graphic = self.__graphic_proxy.item
        if display_item and graphic:
            return getattr(graphic, self.__property_name)
        return None

    def __set_value(self, value: typing.Any) -> None:
        display_item = self.__display_item_proxy.item
        graphic = self.__graphic_proxy.item
        if display_item and graphic:
            if value != getattr(graphic, self.__property_name):
                command = DisplayPanel.ChangeGraphicsCommand(self.__document_controller.document_model, display_item, [graphic], title=_("Change Display Type"), command_id="change_display_" + self.__property_name, is_mergeable=True, **{self.__property_name: value})
                command.perform()
                self.__document_controller.push_undo_command(command)


class CalibratedBinding(Binding.Binding):
    """A abstract calibrated dimension value binding.

    Takes a value binding and a display item, and combines them to convert between the binding value and the calibrated string for a UI element.

    The display item is monitored for changes to the calibration info, and the target value is updated when the calibration info changes.

    Subclasses must override the two conversion methods.
    """
    def __init__(self, display_item: DisplayItem.DisplayItem, value_binding: Binding.Binding, dimension_index: int) -> None:
        super().__init__(None)
        display_info = display_item.display_info
        self.__display_calibration_info = display_info.display_calibration_info if display_info else None
        self.__dimension_index = dimension_index
        self.__display_item_listener = Stream.ValueStreamAction(display_item.display_info_stream, ReferenceCounting.weak_partial(self.__class__.__handle_display_info_changed, self))
        self.__value_binding = value_binding
        self.__value_binding.target_setter = ReferenceCounting.weak_partial(self.__class__.__update_target, self)

    def __update_target(self, value: typing.Any) -> None:
        self.update_target_direct(self.get_target_value())

    def __handle_display_info_changed(self, display_info: DisplayInfo.DisplayInfo | None) -> None:
        display_calibration_info = display_info.display_calibration_info if display_info else None
        self.__display_calibration_info = display_calibration_info
        if display_calibration_info:
            self.__update_target(display_calibration_info.displayed_display_data_calibrations)

    def __get_calibration_and_data_size(self) -> DisplayItem.CalibrationAndDataSize:
        if self.__display_calibration_info:
            return self.__display_calibration_info.get_dimension_calibration_and_data_size(self.__dimension_index)
        else:
            return DisplayItem.CalibrationAndDataSize(Calibration.Calibration(), 1)

    # set the model value from the target ui element text.
    def update_source(self, target_value: typing.Any) -> None:
        calibration_and_data_size = self.__get_calibration_and_data_size()
        calibration = calibration_and_data_size.calibration
        data_size = calibration_and_data_size.data_size
        converted_value = self._convert_str_to_value(calibration, self.__display_calibration_info, data_size, target_value)
        self.__value_binding.update_source(converted_value)

    # get the value from the model and return it as a string suitable for the target ui element.
    # in this binding, it combines the two source bindings into one.
    def get_target_value(self) -> typing.Optional[str]:
        value = self.__value_binding.get_target_value()
        calibration_and_data_size = self.__get_calibration_and_data_size()
        calibration = calibration_and_data_size.calibration
        data_size = calibration_and_data_size.data_size
        return self._convert_value_to_str(calibration, self.__display_calibration_info, data_size, value) if value is not None else None

    def _convert_str_to_value(self, calibration: Calibration.Calibration, display_calibration_info: DisplayItem.DisplayCalibrationInfo | None, data_size: int, value_str: str | None) -> float | None:
        """Subclasses must override this method to convert from the string to the model value, using the calibration and data size as needed."""
        raise NotImplementedError()

    def _convert_value_to_str(self, calibration: Calibration.Calibration, display_calibration_info: DisplayItem.DisplayCalibrationInfo | None, data_size: int, value: float | None) -> str | None:
        """Subclasses must override this method to convert from the model value to the string, using the calibration and data size as needed."""
        raise NotImplementedError()


class CalibratedValueBinding(CalibratedBinding):
    def __init__(self, index: int, display_item: DisplayItem.DisplayItem, value_binding: Binding.Binding) -> None:
        super().__init__(display_item, value_binding, index)

    def _convert_str_to_value(self, calibration: Calibration.Calibration, display_calibration_info: DisplayItem.DisplayCalibrationInfo | None, data_size: int, value_str: str | None) -> float | None:
        if value_str is not None:
            value = Converter.FloatToStringConverter().convert_back(value_str)
            if value is not None:
                return calibration.convert_from_calibrated_value(value) / data_size
        return None

    def _convert_value_to_str(self, calibration: Calibration.Calibration, display_calibration_info: DisplayItem.DisplayCalibrationInfo | None, data_size: int, value: float | None) -> str | None:
        if value is not None:
            return calibration.convert_to_calibrated_value_str(data_size * value, value_range=(0, data_size), samples=data_size)
        return None


class CalibratedSizeBinding(CalibratedBinding):
    def __init__(self, index: int, display_item: DisplayItem.DisplayItem, value_binding: Binding.Binding) -> None:
        super().__init__(display_item, value_binding, index)

    def _convert_str_to_value(self, calibration: Calibration.Calibration, display_calibration_info: DisplayItem.DisplayCalibrationInfo | None, data_size: int, value_str: str | None) -> float | None:
        if value_str is not None:
            value = Converter.FloatToStringConverter().convert_back(value_str)
            if value is not None:
                return calibration.convert_from_calibrated_size(value) / data_size
        return None

    def _convert_value_to_str(self, calibration: Calibration.Calibration, display_calibration_info: DisplayItem.DisplayCalibrationInfo | None, data_size: int, value: float | None) -> str | None:
        if value is not None:
            return calibration.convert_to_calibrated_size_str(data_size * value, value_range=(0, data_size), samples=data_size)
        return None


class CalibratedWidthBinding(CalibratedBinding):
    def __init__(self, display_item: DisplayItem.DisplayItem, value_binding: Binding.Binding) -> None:
        super().__init__(display_item, value_binding, 0)

    def _convert_str_to_value(self, calibration: Calibration.Calibration, display_calibration_info: DisplayItem.DisplayCalibrationInfo | None, data_size: int, value_str: str | None) -> float | None:
        if value_str is not None:
            value = Converter.FloatToStringConverter().convert_back(value_str)
            if value is not None:
                display_data_shape = display_calibration_info.display_data_shape if display_calibration_info else None
                factor = 1.0 / (display_data_shape[0] if display_data_shape is not None else 1)
                return calibration.convert_from_calibrated_size(value) / data_size / factor
        return None

    def _convert_value_to_str(self, calibration: Calibration.Calibration, display_calibration_info: DisplayItem.DisplayCalibrationInfo | None, data_size: int, value: float | None) -> str | None:
        if value is not None:
            display_data_shape = display_calibration_info.display_data_shape if display_calibration_info else None
            factor = 1.0 / (display_data_shape[0] if display_data_shape is not None else 1)
            return calibration.convert_to_calibrated_size_str(data_size * value * factor, value_range=(0, data_size), samples=data_size)
        return None


class CalibratedAngleBinding(CalibratedBinding):
    # NOTE: the angle can change depending on the calibrations

    def __init__(self, display_item: DisplayItem.DisplayItem, value_binding: Binding.Binding) -> None:
        super().__init__(display_item, value_binding, 0)

    def _convert_str_to_value(self, calibration: Calibration.Calibration, display_calibration_info: DisplayItem.DisplayCalibrationInfo | None, data_size: int, value_str: str | None) -> float | None:
        return GraphicsInspector.RadianToDegreeStringConverter().convert_back(value_str) if value_str is not None else None

    def _convert_value_to_str(self, calibration: Calibration.Calibration, display_calibration_info: DisplayItem.DisplayCalibrationInfo | None, data_size: int, value: float | None) -> str | None:
        return GraphicsInspector.RadianToDegreeStringConverter().convert(value) if value is not None else None


class CalibratedLengthBinding(Binding.Binding):
    def __init__(self, display_item: DisplayItem.DisplayItem, start_binding: Binding.Binding, end_binding: Binding.Binding) -> None:
        super().__init__(None)
        display_info = display_item.display_info
        self.__display_calibration_info = display_info.display_calibration_info if display_info else None
        self.__display_item_listener = Stream.ValueStreamAction(display_item.display_info_stream, ReferenceCounting.weak_partial(self.__class__.__handle_display_info_changed, self))
        self.__start_binding = start_binding
        self.__end_binding = end_binding
        self.__start_binding.target_setter = ReferenceCounting.weak_partial(self.__class__.__update_target, self)
        self.__end_binding.target_setter = ReferenceCounting.weak_partial(self.__class__.__update_target, self)

    def __update_target(self, value: typing.Any) -> None:
        self.update_target_direct(self.get_target_value())

    def __handle_display_info_changed(self, display_info: DisplayInfo.DisplayInfo | None) -> None:
        display_calibration_info = display_info.display_calibration_info if display_info else None
        self.__display_calibration_info = display_calibration_info
        if display_calibration_info:
            self.__update_target(display_calibration_info.displayed_display_data_calibrations)

    def __get_calibration_and_data_size(self, dimension_index: int) -> DisplayItem.CalibrationAndDataSize:
        if self.__display_calibration_info:
            return self.__display_calibration_info.get_dimension_calibration_and_data_size(dimension_index, uniform=True)
        else:
            return DisplayItem.CalibrationAndDataSize(Calibration.Calibration(), 1)

    # set the model value from the target ui element text.
    def update_source(self, target_value: typing.Any) -> None:
        start = self.__start_binding.get_target_value() or Geometry.FloatPoint()
        end = self.__end_binding.get_target_value() or Geometry.FloatPoint()
        y_calibration_and_data_size = self.__get_calibration_and_data_size(0)
        x_calibration_and_data_size = self.__get_calibration_and_data_size(1)
        calibrated_start = Geometry.FloatPoint(y=y_calibration_and_data_size.calibration.convert_to_calibrated_value(start.y * y_calibration_and_data_size.data_size),
                                               x=x_calibration_and_data_size.calibration.convert_to_calibrated_value(start.x * x_calibration_and_data_size.data_size))
        calibrated_end = Geometry.FloatPoint(y=y_calibration_and_data_size.calibration.convert_to_calibrated_value(end.y * y_calibration_and_data_size.data_size),
                                             x=x_calibration_and_data_size.calibration.convert_to_calibrated_value(end.x * x_calibration_and_data_size.data_size))
        delta = calibrated_end - calibrated_start
        angle = -math.atan2(delta.y, delta.x)
        new_calibrated_end = calibrated_start + target_value * Geometry.FloatSize(height=-math.sin(angle), width=math.cos(angle))
        end = Geometry.FloatPoint(y=y_calibration_and_data_size.calibration.convert_from_calibrated_value(new_calibrated_end.y) / y_calibration_and_data_size.data_size,
                                  x=x_calibration_and_data_size.calibration.convert_from_calibrated_value(new_calibrated_end.x) / x_calibration_and_data_size.data_size)
        self.__end_binding.update_source(end)

    # get the value from the model and return it as a string suitable for the target ui element.
    # in this binding, it combines the two source bindings into one.
    def get_target_value(self) -> typing.Optional[str]:
        start = self.__start_binding.get_target_value() or Geometry.FloatPoint()
        end = self.__end_binding.get_target_value() or Geometry.FloatPoint()
        y_calibration_and_data_size = self.__get_calibration_and_data_size(0)
        x_calibration_and_data_size = self.__get_calibration_and_data_size(1)
        calibrated_start = Geometry.FloatPoint(y=y_calibration_and_data_size.calibration.convert_to_calibrated_value(start.y * y_calibration_and_data_size.data_size),
                                               x=x_calibration_and_data_size.calibration.convert_to_calibrated_value(start.x * x_calibration_and_data_size.data_size))
        calibrated_end = Geometry.FloatPoint(y=y_calibration_and_data_size.calibration.convert_to_calibrated_value(end.y * y_calibration_and_data_size.data_size),
                                             x=x_calibration_and_data_size.calibration.convert_to_calibrated_value(end.x * x_calibration_and_data_size.data_size))
        calibrated_distance = Geometry.distance(calibrated_end, calibrated_start)
        return y_calibration_and_data_size.calibration.convert_calibrated_size_to_str(calibrated_distance)


class GraphicHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable, graphic: Graphics.Graphic):
        super().__init__()
        self.document_controller = document_controller
        self.computation = computation
        self.variable = variable
        self.graphic = graphic
        u = Declarative.DeclarativeUI()
        graphic_content = self.__make_component_content(graphic)
        label_row = u.create_row(
            u.create_label(text="@binding(variable.display_label)"),
            # u.create_label(text=f"#{variable._bound_items.index(item)}"),
            u.create_stretch(), spacing=8)
        self.ui_view = u.create_column(label_row, graphic_content, spacing=8)

    def get_binding(self, source: Persistence.PersistentObject, property: str, converter: typing.Optional[Converter.ConverterLike[typing.Any, typing.Any]]) -> typing.Optional[Binding.Binding]:
        # override the regular property binding and converter to handle displayed coordinates and undo commands.
        graphic: Graphics.Graphic
        if isinstance(source, Graphics.IntervalGraphic):
            if property in ("start", "end"):
                graphic = source
                display_item = graphic.display_item
                return CalibratedValueBinding(-1, display_item, ChangeGraphicPropertyBinding(self.document_controller, display_item, graphic, property))
        if isinstance(source, Graphics.RectangleGraphic):
            if property in ("center_x", "center_y"):
                graphic = source
                display_item = graphic.display_item
                index = 1 if property == "center_x" else 0
                graphic_name = "rectangle"
                property_model = GraphicsInspector.GraphicPropertyCommandModel[tuple[float, ...]](self.document_controller, display_item, graphic, "center", title=_("Change {} Center").format(graphic_name), command_id="change_" + graphic_name + "_center")
                return CalibratedValueBinding(index, display_item, ClosingTuplePropertyBinding(property_model, "value", index))
            elif property in ("width", "height"):
                graphic = source
                display_item = graphic.display_item
                index = 1 if property == "width" else 0
                graphic_name = "rectangle"
                size_model = GraphicsInspector.GraphicPropertyCommandModel[tuple[float, ...]](self.document_controller, display_item, graphic, "size", title=_("Change {} Size").format(graphic_name), command_id="change_" + graphic_name + "_size")
                return CalibratedSizeBinding(index, display_item, ClosingTuplePropertyBinding(size_model, "value", index))
            elif property in ("rotation_deg", ):
                graphic = source
                display_item = graphic.display_item
                graphic_name = "rectangle"
                rotation_model = GraphicsInspector.GraphicPropertyCommandModel[float](self.document_controller, display_item, graphic, "rotation", title=_("Change {} Rotation").format(graphic_name), command_id="change_" + graphic_name + "_size")
                return ClosingPropertyBinding(rotation_model, "value", converter=GraphicsInspector.RadianToDegreeStringConverter())
        if isinstance(source, Graphics.LineTypeGraphic):
            if property in ("start_x", "start_y"):
                graphic = source
                display_item = graphic.display_item
                index = 1 if property == "start_x" else 0
                graphic_name = "line_profile"
                property_model = GraphicsInspector.GraphicPropertyCommandModel[tuple[float, ...]](self.document_controller, display_item, graphic, "start", title=_("Change {} Start").format(graphic_name), command_id="change_" + graphic_name + "_start")
                return CalibratedValueBinding(index, display_item, ClosingTuplePropertyBinding(property_model, "value", index))
            if property in ("end_x", "end_y"):
                graphic = source
                display_item = graphic.display_item
                index = 1 if property == "end_x" else 0
                graphic_name = "line_profile"
                property_model = GraphicsInspector.GraphicPropertyCommandModel[tuple[float, ...]](self.document_controller, display_item, graphic, "end", title=_("Change {} End").format(graphic_name), command_id="change_" + graphic_name + "_end")
                return CalibratedValueBinding(index, display_item, ClosingTuplePropertyBinding(property_model, "value", index))
            if property == "length":
                graphic = source
                display_item = graphic.display_item
                graphic_name = "line_profile"
                property_model1 = GraphicsInspector.GraphicPropertyCommandModel[tuple[float, ...]](self.document_controller, display_item, graphic, "start", title=_("Change {} Length").format(graphic_name), command_id="change_" + graphic_name + "_length_start")
                property_model2 = GraphicsInspector.GraphicPropertyCommandModel[tuple[float, ...]](self.document_controller, display_item, graphic, "end", title=_("Change {} Length").format(graphic_name), command_id="change_" + graphic_name + "_length_end")
                return CalibratedLengthBinding(display_item, ClosingPropertyBinding(property_model1, "value"), ClosingPropertyBinding(property_model2, "value"))
            if property == "angle":
                graphic = source
                display_item = graphic.display_item
                graphic_name = "line_profile"
                property_model_f = GraphicsInspector.GraphicPropertyCommandModel[float](self.document_controller, display_item, graphic, "angle", title=_("Change {} Angle").format(graphic_name), command_id="change_" + graphic_name + "_angle")
                return CalibratedAngleBinding(display_item, ClosingPropertyBinding(property_model_f, "value"))
        if isinstance(source, Graphics.LineProfileGraphic):
            if property == "width":
                graphic = source
                display_item = graphic.display_item
                graphic_name = "line_profile"
                property_model_f = GraphicsInspector.GraphicPropertyCommandModel[float](self.document_controller, display_item, graphic, "width", title=_("Change {} Line Width").format(graphic_name), command_id="change_" + graphic_name + "_line_width")
                return CalibratedWidthBinding(display_item, ClosingPropertyBinding(property_model_f, "value"))
        return None

    def __make_component_content(self, graphic: Graphics.Graphic) -> Declarative.UIDescription:
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
                u.create_stretch(),
                spacing=12)
            return u.create_column(position_row, size_row, rotation_row, spacing=8)
        if isinstance(graphic, Graphics.LineProfileGraphic):
            start_row = u.create_row(
                u.create_label(text=_("X0"), width=24),
                u.create_line_edit(text="@binding(graphic.start_x)", width=90),
                u.create_label(text=_("Y0"), width=24),
                u.create_line_edit(text="@binding(graphic.start_y)", width=90),
                u.create_stretch(), spacing=12)
            end_row = u.create_row(
                u.create_label(text=_("X1"), width=24),
                u.create_line_edit(text="@binding(graphic.end_x)", width=90),
                u.create_label(text=_("Y1"), width=24),
                u.create_line_edit(text="@binding(graphic.end_y)", width=90),
                u.create_stretch(), spacing=12)
            length_row = u.create_row(
                u.create_label(text=_("Length"), width=24),
                u.create_line_edit(text="@binding(graphic.length)", width=90),
                u.create_label(text=_("Angle"), width=24),
                u.create_line_edit(text="@binding(graphic.angle)", width=90),
                u.create_stretch(), spacing=12)
            line_width_row = u.create_row(
                u.create_label(text=_("Width"), width=24),
                u.create_line_edit(text="@binding(graphic.width)", width=90),
                u.create_stretch(), spacing=12)
            return u.create_column(start_row, end_row, length_row, line_width_row, spacing=8)
        return u.create_label(text=_("Unsupported Graphic") + f" {graphic}")


class GraphicVariableHandlerFactory(VariableHandlerComponentFactory2):
    def make_variable_handler(self, computation_inspector_context: ComputationInspectorContext, computation: Symbolic.Computation, computation_variable: Symbolic.ComputationVariable, variable_model: VariableValueModel, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if computation_variable.variable_type == Symbolic.ComputationVariableType.GRAPHIC:
            graphic = typing.cast(typing.Optional[Graphics.Graphic], computation_variable.bound_item.value if computation_variable.bound_item else None)
            if graphic:
                return GraphicHandler(computation_inspector_context.window, computation, computation_variable, graphic)
        return None


class DataStructureHandler(Declarative.Handler):
    def __init__(self, computation_inspector_context: ComputationInspectorContext, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable, data_structure: DataStructure.DataStructure):
        super().__init__()
        self.computation_inspector_context = computation_inspector_context
        self.computation = computation
        self.variable = variable
        self.data_structure = data_structure
        self.__entity_choice = None
        self.__entity_types = list()
        self.__entity_choices = list()
        variable_entity_id = self.variable.entity_id or str()
        base_entity_type = Schema.get_entity_type(variable_entity_id)
        u = Declarative.DeclarativeUI()
        if base_entity_type:
            self.__entity_types = base_entity_type.subclasses

            entity_info_list = [(DataStructure.DataStructure.entity_names[entity_type.entity_id],
                                 DataStructure.DataStructure.entity_package_names[entity_type.entity_id])
                                 for entity_type in self.__entity_types]

            counts = collections.Counter([entity_info[0] for entity_info in entity_info_list])

            def name(entity_id: str) -> str:
                entity_name = DataStructure.DataStructure.entity_names[entity_id]
                entity_package_name = DataStructure.DataStructure.entity_package_names[entity_id]
                return f"{entity_name} ({entity_package_name})" if counts[entity_name] > 1 else entity_name

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
            label = u.create_label(text="@binding(variable.display_label)")
            # the link is optional (for now) - it does not appear in the standard computation panel.
            link = u.create_push_button(text="\N{RIGHTWARDS BLACK ARROW}", on_clicked="handle_link", border_color="transparent", background_color="rgba(0,0,0,0.0)", style="minimal", size_policy_horizontal="maximum")
            self.ui_view = u.create_row(
                u.create_row(label, *([link] if computation_inspector_context.do_references else []), u.create_stretch()),
                u.create_combo_box(items_ref="entity_choices", current_index="@binding(entity_choice)"),
                u.create_stretch(), spacing=8)
        else:
            self.ui_view = u.create_column()

        def property_changed(name: str) -> None:
            if name == "structure_type":
                entity_id = self.data_structure.structure_type
                for index, entity_type in enumerate(self.__entity_types):
                    if entity_type.entity_id == entity_id:
                        if self.__entity_choice != index:
                            self.__entity_choice = index
                            self.property_changed_event.fire("entity_choice")
                        return
                if self.__entity_choice != len(self.__entity_types) + 1:
                    self.__entity_choice = len(self.__entity_types) + 1
                    self.property_changed_event.fire("entity_choice")

        self.__property_changed_listener = self.data_structure.property_changed_event.listen(property_changed)

    def close(self) -> None:
        self.__property_changed_listener = typing.cast(typing.Any, None)
        super().close()

    @property
    def entity_choices(self) -> typing.List[str]:
        return self.__entity_choices

    @property
    def entity_choice(self) -> int:
        return self.__entity_choice or 0

    @entity_choice.setter
    def entity_choice(self, value: int) -> None:
        if 0 <= value < len(self.__entity_types):
            self.data_structure.structure_type = self.__entity_types[value].entity_id
        else:
            assert self.variable.entity_id
            self.data_structure.structure_type = self.variable.entity_id

    def handle_link(self, item: Declarative.UIWidget) -> None:
        # when the user clicks the link associated with the referenced component, open the referenced item in the project items dialog.
        bound_item = self.variable.bound_item
        if bound_item and len(bound_item.base_items) > 0:
            self.computation_inspector_context.reference_handler.open_project_item(bound_item.base_items[0])


class DataStructurePropertyVariableHandler(Declarative.Handler):
    # used to display a data structure property. this is a hack and may not be needed once new data structures
    # are in place that have a guaranteed schema.
    def __init__(self, computation_inspector_context: ComputationInspectorContext, variable: Symbolic.ComputationVariable) -> None:
        super().__init__()
        self.computation_inspector_context = computation_inspector_context
        self.variable = variable
        u = Declarative.DeclarativeUI()
        label = u.create_label(text="@binding(variable.display_label)")
        # the link is optional (for now) - it does not appear in the standard computation panel.
        link = u.create_push_button(text="\N{RIGHTWARDS BLACK ARROW}", on_clicked="handle_link", border_color="transparent", background_color="rgba(0,0,0,0.0)", style="minimal", size_policy_horizontal="maximum")
        line_edit = u.create_label(text="@binding(variable_value)", width=300)
        self.ui_view = u.create_column(u.create_row(label, *([link] if computation_inspector_context.do_references else []), u.create_stretch()), line_edit, u.create_stretch(), spacing=8)
        self.__variable_listener = variable.property_changed_event.listen(ReferenceCounting.weak_partial(DataStructurePropertyVariableHandler.__property_changed, self))
        if variable.bound_item:
            def handle_variable_event(handler: DataStructurePropertyVariableHandler, event_type: Symbolic.BoundDataEventType) -> None:
                handler.__changed()

            self.__bound_item_listener = variable.data_event.listen(
                ReferenceCounting.weak_partial(handle_variable_event, self))

    @property
    def variable_value(self) -> str:
        return str(self.variable.bound_item.value) if self.variable.bound_item else str()

    def __property_changed(self, key: str) -> None:
        self.notify_property_changed("variable_value")

    def __changed(self) -> None:
        self.notify_property_changed("variable_value")

    def handle_link(self, item: Declarative.UIWidget) -> None:
        # when the user clicks the link associated with the referenced component, open the referenced item in the project items dialog.
        bound_item = self.variable.bound_item
        if bound_item and len(bound_item.base_items) > 0:
            self.computation_inspector_context.reference_handler.open_project_item(bound_item.base_items[0])


class ConstantVariableHandler(Declarative.Handler):
    # used to display a constant string
    def __init__(self, variable: Symbolic.ComputationVariable, value: str) -> None:
        super().__init__()
        self.variable = variable
        self.variable_value = value
        u = Declarative.DeclarativeUI()
        label = u.create_label(text="@binding(variable.display_label)")
        line_edit = u.create_label(text="@binding(variable_value)", width=300)
        self.ui_view = u.create_column(label, line_edit, spacing=8)


class DataStructureVariableHandlerFactory(VariableHandlerComponentFactory2):
    def make_variable_handler(self, computation_inspector_context: ComputationInspectorContext, computation: Symbolic.Computation, computation_variable: Symbolic.ComputationVariable, variable_model: VariableValueModel, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if computation_variable.variable_type == Symbolic.ComputationVariableType.STRUCTURE:
            if computation_variable.property_name:
                return DataStructurePropertyVariableHandler(computation_inspector_context, computation_variable)
            else:
                data_structure = computation_variable.bound_item.value if computation_variable.bound_item else None
                if isinstance(data_structure, DataStructure.DataStructure):
                    return DataStructureHandler(computation_inspector_context, computation, computation_variable, data_structure)
                else:
                    return ConstantVariableHandler(computation_variable, _("N/A"))
        return None


class GraphicListVariableHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable) -> None:
        super().__init__()
        self.document_controller = document_controller
        self.computation = computation
        self.variable = variable
        u = Declarative.DeclarativeUI()
        self.ui_view = u.create_column(items="variable._bound_items", item_component_id="graphic_item", spacing=8)

    def create_handler(self, component_id: str, container: typing.Optional[Symbolic.ComputationVariable] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if component_id == "graphic_item" and item and item.value:
            graphic = typing.cast(Graphics.Graphic, item.value)
            return GraphicHandler(self.document_controller, self.computation, self.variable, graphic)
        return None


class GraphicListVariableHandlerFactory(VariableHandlerComponentFactory2):
    def make_variable_handler(self, computation_inspector_context: ComputationInspectorContext, computation: Symbolic.Computation, computation_variable: Symbolic.ComputationVariable, variable_model: VariableValueModel, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if computation_variable.is_list:
            return GraphicListVariableHandler(computation_inspector_context.window, computation, computation_variable)
        return None


# Register the default computation variable component factories.
Registry.register_component(BooleanVariableHandlerFactory(), {"variable-handler-fallback-component-factory"})
Registry.register_component(IntegerVariableHandlerFactory(), {"variable-handler-fallback-component-factory"})
Registry.register_component(RealVariableHandlerFactory(), {"variable-handler-fallback-component-factory"})
Registry.register_component(StringVariableHandlerFactory(), {"variable-handler-fallback-component-factory"})
Registry.register_component(DataSourceVariableHandlerFactory(), {"variable-handler-fallback-component-factory"})
Registry.register_component(GraphicVariableHandlerFactory(), {"variable-handler-fallback-component-factory"})
Registry.register_component(DataStructureVariableHandlerFactory(), {"variable-handler-fallback-component-factory"})
Registry.register_component(GraphicListVariableHandlerFactory(), {"variable-handler-fallback-component-factory"})


def make_computation_variable_component(computation_inspector_context: ComputationInspectorContext, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable, variable_value_model: VariableValueModel) -> Declarative.HandlerLike | None:
    """Make a computation variable component and return the declarative handler.

    A computation variable component is a Declarative.HandlerLike which represents a ComputationVariable in the UI
    and allows the user to view and edit the variable's value via a VariableValueModel.

    This function uses the registry to find factories that can create a component for the variable. Factories are
    registered under the 'variable-handler-component-factory' type for primary handlers and
    'variable-handler-fallback-component-factory' for fallback handlers. Primary factories are queried first and have
    higher priority than fallback factories. The first factory to return a component for the variable is used. If no
    factory returns a component, None is returned and the variable will not be displayed.

    The components returned by the factories should not modify the ComputationVariable, Computation, or DocumentModel
    directly. Instead, they should use the VariableValueModel to get and set the variable's value. This ensures that
    undo/redo and other features work correctly.
    """
    document_controller = computation_inspector_context.window
    for component in Registry.get_components_by_type("variable-handler-component-factory"):
        computation_variable_handler = typing.cast(VariableHandlerComponentFactory, component)
        variable_component = computation_variable_handler.make_variable_handler(document_controller, computation, variable, variable_value_model)
        if variable_component:
            return variable_component
    for component in Registry.get_components_by_type("variable-handler-fallback-component-factory"):
        computation_variable_handler2 = typing.cast(VariableHandlerComponentFactory2, component)
        variable_component = computation_variable_handler2.make_variable_handler(computation_inspector_context, computation, variable, variable_value_model)
        if variable_component:
            return variable_component
    return None


class ComputationInspectorContext(EntityBrowser.Context):
    # a context for the inspectors (not consistently available in all inspectors yet)
    # allows access to a reference handler (when the user clicks links on referenced components),
    # the window (document controller), the document model, whether to provide link controls,
    # and whether the UI is hosted in a narrow container such as the inspector panel (compact).

    def __init__(self, document_controller: DocumentController.DocumentController, reference_handler: typing.Optional[EntityBrowser.ReferenceHandlerContext] = None, provide_reference_links: bool = False, compact: bool = False) -> None:
        super().__init__()
        self.values["reference_handler"] = reference_handler or document_controller
        self.values["window"] = document_controller
        self.values["event_loop"] = document_controller.event_loop
        self.values["document_model"] = document_controller.document_model
        self.values["do_references"] = provide_reference_links
        self.values["compact"] = compact

    @property
    def reference_handler(self) -> EntityBrowser.ReferenceHandlerContext:
        return typing.cast(EntityBrowser.ReferenceHandlerContext, self.values["reference_handler"])

    @property
    def window(self) -> DocumentController.DocumentController:
        return typing.cast("DocumentController.DocumentController", self.values["window"])

    @property
    def event_loop(self) -> asyncio.AbstractEventLoop:
        return typing.cast(asyncio.AbstractEventLoop, self.values["event_loop"])

    @property
    def document_model(self) -> DocumentModel.DocumentModel:
        return typing.cast(DocumentModel.DocumentModel, self.values["document_model"])

    @property
    def do_references(self) -> bool:
        return typing.cast(bool, self.values.get("do_references", False))

    @property
    def compact(self) -> bool:
        # whether the UI is hosted in a narrow container, such as the inspector panel, in which case
        # the UI should avoid side-by-side columns and dialog-sized fixed widths.
        return typing.cast(bool, self.values.get("compact", False))


class VariableHandler(Declarative.Handler):
    """A declarative handler that displays the control for a single computation variable.

    Watches the variable for changes that require a different UI (e.g. a change of variable
    type) and rebuilds its component in place if necessary.
    """

    def __init__(self, computation_inspector_context: ComputationInspectorContext, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable) -> None:
        super().__init__()
        self.__computation_inspector_context = computation_inspector_context
        self.__computation = computation
        self.__variable = variable
        self.__rebuild_count = 0
        u = Declarative.DeclarativeUI()
        self.ui_view = u.create_column(u.create_component_instance("@binding(component_identifier)"), spacing=8)
        self.__variable_needs_rebuild_event_listener = variable.needs_rebuild_event.listen(self.__rebuild)

    def close(self) -> None:
        self.__variable_needs_rebuild_event_listener.close()
        self.__variable_needs_rebuild_event_listener = typing.cast(typing.Any, None)
        super().close()

    @property
    def component_identifier(self) -> str:
        return f"component_{self.__rebuild_count}"

    def __rebuild(self) -> None:
        self.__rebuild_count += 1
        self.notify_property_changed("component_identifier")

    def create_handler(self, component_id: str, container: typing.Optional[Symbolic.ComputationVariable] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        computation_inspector_context = self.__computation_inspector_context
        computation = self.__computation
        variable = self.__variable
        variable_model = VariableValueModel(computation_inspector_context.window, computation, variable)
        variable_component = make_computation_variable_component(computation_inspector_context, computation, variable, variable_model)
        if variable_component:
            return variable_component
        return ConstantVariableHandler(variable, _("Missing") + " " + f"[{variable.variable_type}]")


class ResultHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController, computation: Symbolic.Computation, result: Symbolic.ComputationOutput) -> None:
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


class ComputationInspectorModel(Observable.Observable):
    """A model for the computation inspector.

    Provides the following static properties:
    - computation_inputs_model: a ListModel of the computation data source inputs
    - computation_parameters_model: a ListModel of the computation parameter inputs
    - is_custom: a boolean indicating whether the computation is custom (has a script expression)

    Provides the following dynamic properties that are updated based on the computation state:
    - error_state_model: a PropertyModel that is 1 if there is an error and 0 otherwise
    - update_button_enabled: whether the update button should be enabled, i.e. when the computation is not up-to-date
    - progress_value: the progress of the computation as an integer between 0 and 100, or 0 if there is no progress information
    - is_stoppable: whether the computation is currently stoppable
    - last_computed_status: a string indicating the last computed status, primarily the timestamp and duration
    - status: a string indicating the current status of the computation, such as computing or up-to-date
    - status_color: a color string, red for error, black for success

    The model tries to be stable during fast updates.

    The model also tries to avoid in between states during initial computation progress.
    """

    def __init__(self, computation: Symbolic.Computation, event_loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()
        self.computation = computation
        self.__event_loop = event_loop
        self.computation_inputs_model = ListModel.FilteredListModel(container=computation, master_items_key="variables")
        self.computation_inputs_model.filter = ListModel.PredicateFilter(lambda v: v.variable_type in Symbolic._data_source_types)
        self.computation_parameters_model = ListModel.FilteredListModel(container=computation, master_items_key="variables")
        self.computation_parameters_model.filter = ListModel.PredicateFilter(lambda v: v.variable_type not in Symbolic._data_source_types)
        self.is_custom = computation.expression is not None

        # configure the is_stoppable stream that is True when the computation is stoppable. used to enable button.
        # the low level value is debounced and exposed as the is_stoppable property to avoid rapid changes during fast updates.
        # the debounced listener is used to trigger property changed notifications.
        self.__is_stoppable_stream = Stream.ValueStream(False)
        self.__is_stoppable_debounced_stream = Stream.DebounceStream(self.__is_stoppable_stream, 0.5, self.__event_loop)
        self.__is_stoppable_debounced_stream_listener = Stream.ValueStreamAction(self.__is_stoppable_debounced_stream, ReferenceCounting.weak_partial(ComputationInspectorModel.__is_stoppable_changed, self))

        # configure the status stream that gives a user-friendly status string.
        # the debounced listener is used to trigger property changed notifications.
        self.__status_stream = Stream.ValueStream(str())
        self.__status_debounced_stream = Stream.DebounceStream(self.__status_stream, 0.5, self.__event_loop)
        self.__status_debounced_stream_listener = Stream.ValueStreamAction(self.__status_debounced_stream, ReferenceCounting.weak_partial(ComputationInspectorModel.__status_changed, self))

        # configure a listener for changes to the computation properties that affect the model state.
        self.__computation_property_changed_listener = computation.property_changed_event.listen(ReferenceCounting.weak_partial(ComputationInspectorModel.__computation_property_changed, self))

        self.error_state_model = Model.PropertyModel(0)
        self.__is_error = self.computation.error_text is not None and self.computation.error_text != str()

    def close(self) -> None:
        self.computation_inputs_model.close()
        self.computation_inputs_model = typing.cast(typing.Any, None)
        self.computation_parameters_model.close()
        self.computation_parameters_model = typing.cast(typing.Any, None)

    def finish_init(self) -> None:
        self.__computation_property_changed("error_text")

    def __computation_property_changed(self, key: str) -> None:
        # observe computation property changes, update the model state, and send out property changed notifications as needed.

        def update_status_str() -> None:
            # this will update the status string and after a short delay send the notification,
            # which allows it to avoid rapid changes during fast updates and also ensures that the final status is shown after the initial computation finishes.
            self.__status_stream.value = self.__get_status_str()

        if key in ("last_computed_status", "error_text", "last_computed_elapsed_time", "last_computed_elapsed_time"):
            self.__is_error = self.computation.error_text is not None and self.computation.error_text != str()
            self.notify_property_changed("last_computed_status")
            update_status_str()
            self.notify_property_changed("status_color")
            self.error_state_model.value = 1 if self.__is_error else 0
        if key in ("needs_update", ):
            update_status_str()
        if key in ("progress", ):
            self.notify_property_changed("progress_value")
            computation = self.computation
            progress = computation.progress
            self.__is_stoppable_stream.value = progress is not None
            update_status_str()
        if key in ("last_computed_status", "auto_update", "needs_update"):
            self.notify_property_changed("update_button_enabled")

    def __is_stoppable_changed(self, value: bool | None) -> None:
        self.notify_property_changed("is_stoppable")

    def __status_changed(self, value: bool | None) -> None:
        self.notify_property_changed("status")

    @property
    def update_button_enabled(self) -> bool:
        return (not self.computation.auto_update and self.computation.needs_update) or self.computation.last_computed_status != Symbolic.ComputationResultStatusEnum.SUCCESS

    @property
    def progress_value(self) -> int:
        computation = self.computation
        progress = computation.progress
        if progress is not None:
            return round(progress * 100)
        else:
            return 0

    @property
    def is_stoppable(self) -> bool:
        return self.__is_stoppable_debounced_stream.value or False

    @property
    def last_computed_status(self) -> str:
        # return a string like "2023-01-01 12:34:56 (123ms)" or "Error" or "Unknown"
        computation = self.computation
        if computation.error_text:
            return computation.error_text
        last_computed_elapsed_time = computation.last_computed_elapsed_time
        last_computed_timestamp = computation.last_computed_timestamp
        if last_computed_elapsed_time is not None and last_computed_timestamp:
            local_modified_datetime = last_computed_timestamp + datetime.timedelta(minutes=Utility.local_utcoffset_minutes(last_computed_timestamp))
            time_str = local_modified_datetime.strftime('%Y-%m-%d %H:%M:%S')
            return f"{time_str} ({round(last_computed_elapsed_time * 1000)}ms)"
        return _("Unknown")

    def __get_status_str(self) -> str:
        # return a string like "Computing (50%)", "Needs Update", "Up to Date" or "Error"
        computation = self.computation
        progress = computation.progress
        status_str: str
        if progress is not None and progress > 0.0:
            computing_str = f"Computing ({round(progress * 100)}%)"
            if computation.needs_update:
                status_str = computing_str + ", " + _("Needs Update")
            else:
                status_str = computing_str
        elif computation.last_computed_status == Symbolic.ComputationResultStatusEnum.ERROR:
            return _("Error")
        elif computation.last_computed_status == Symbolic.ComputationResultStatusEnum.CANCELLED:
            status_str = _("Stopped")
            if computation.needs_update:
                status_str += ", " + _("Needs Update")
            return status_str
        elif computation.last_computed_status == Symbolic.ComputationResultStatusEnum.PENDING:
            status_str = _("Pending")
            if computation.needs_update:
                status_str += ", " + _("Needs Update")
            return status_str
        elif computation.needs_update:
            status_str = _("Needs Update")
        else:
            status_str = _("Up to Date")
        return status_str

    @property
    def status(self) -> str:
        return self.__status_stream.value or str()

    @property
    def status_color(self) -> str:
        return "red" if self.__is_error else "black"


class ComputationErrorInspectorHandler(Declarative.Handler):
    def __init__(self, computation_inspector_context: ComputationInspectorContext, computation: Symbolic.Computation) -> None:
        super().__init__()
        self.model = ComputationInspectorModel(computation, computation_inspector_context.event_loop)
        self.ui_view = self.__make_ui()
        self.model.finish_init()

    def close(self) -> None:
        self.model.close()
        self.model = typing.cast(typing.Any, None)
        super().close()

    def __make_ui(self) -> Declarative.UIDescriptionResult:
        u = Declarative.DeclarativeUI()
        error_column = u.create_column(
            u.create_stack(
                u.create_column(u.create_row(u.create_label(text=_("No Error")), u.create_stretch()), u.create_stretch()),
                u.create_column(u.create_row(u.create_label(text=_("Error")), u.create_stretch()),
                                u.create_row(u.create_label(text="@binding(model.status)", color="@binding(model.status_color)", max_width=300), u.create_stretch()),
                                u.create_text_edit(editable=False, placeholder_text=_("No stack trace."), text="@binding(model.computation.error_stack_trace)"),
                                u.create_stretch(),
                                spacing=8),
                current_index="@binding(model.error_state_model.value)"
            )
        )
        return error_column


class ComputationInspectorHandler(Declarative.Handler):
    def __init__(self, computation_inspector_context: ComputationInspectorContext, computation: Symbolic.Computation) -> None:
        super().__init__()
        self.__computation_inspector_context = computation_inspector_context
        self.document_controller = computation_inspector_context.window
        self.model = ComputationInspectorModel(computation, computation_inspector_context.event_loop)
        self.delete_state_model = Model.PropertyModel(0)
        self.ui_view = self.__make_ui()
        self.model.finish_init()

    def close(self) -> None:
        self.model.close()
        self.model = typing.cast(typing.Any, None)
        super().close()

    def __make_ui(self) -> Declarative.UIDescriptionResult:
        # the compact layout is used when hosted in a narrow container such as the inspector panel: the
        # results are omitted (the container already displays them) and fixed widths are relaxed in favor
        # of word wrapping, since the inspector panel does not scroll horizontally.
        compact = self.__computation_inspector_context.compact
        u = Declarative.DeclarativeUI()
        label = u.create_label(text="@binding(model.computation.label)", word_wrap=compact, widget_id="computation_label")
        source_line = [u.create_component_instance("source_component")] if self.__computation_inspector_context.do_references else []
        auto_update = u.create_check_box(text=_("Auto Update"), checked="@binding(model.computation.auto_update)")
        update_button = u.create_push_button(text=_("Update"), on_clicked="update_computation", enabled="@binding(model.update_button_enabled)")
        auto_update_row = u.create_row(auto_update, update_button, u.create_stretch(), spacing=12)
        if compact:
            progress = u.create_progress_bar(value="@binding(model.progress_value)", height=8)
        else:
            progress = u.create_progress_bar(value="@binding(model.progress_value)", width=160, height=8)
        stop_button = u.create_push_button(text=_("Stop"), visible="@binding(model.is_stoppable)", on_clicked="stop_computation")
        control_row = u.create_row(progress, stop_button, u.create_stretch(), spacing=12)
        last_computed_row = u.create_row(u.create_label(text=_("Last Computed: ")), u.create_label(text="@binding(model.last_computed_status)", word_wrap=compact), u.create_stretch())
        if compact:
            status = u.create_label(text="@binding(model.status)", word_wrap=True)
        else:
            status = u.create_label(text="@binding(model.status)", max_width=300)
        inputs = u.create_column(items="model.computation_inputs_model.items", item_component_id="variable", spacing=8, size_policy_vertical="expanding")
        if compact:
            input_output_row = u.create_column(inputs)
        else:
            results = u.create_column(items="model.computation.results", item_component_id="result", spacing=8, size_policy_vertical="expanding")
            input_output_row = u.create_row(
                u.create_column(u.create_column(inputs), u.create_stretch()),
                u.create_column(u.create_column(results), u.create_stretch()),
                spacing=12,
                size_policy_vertical="expanding"
            )
        parameters = u.create_column(items="model.computation_parameters_model.items", item_component_id="variable", spacing=8)
        if sys.platform == "darwin":
            note = u.create_row(u.create_label(text=_("Use Command+Shift+E to edit data item script."), word_wrap=compact), visible="@binding(model.is_custom)")
        else:
            note = u.create_row(u.create_label(text=_("Use Ctrl+Shift+E to edit data item script."), word_wrap=compact), visible="@binding(model.is_custom)")
        controls = u.create_row(u.create_column(last_computed_row, status, auto_update_row, control_row, note, u.create_stretch(), spacing=12), u.create_stretch())
        inspector_column = u.create_column(label, *source_line, u.create_column(input_output_row, parameters, u.create_divider(orientation="horizontal"), controls, spacing=12), spacing=12)
        return inspector_column

    def update_computation(self, widget: UserInterface.PushButtonWidget) -> None:
        self.model.computation.needs_update = True
        self.document_controller.document_model._start_computation(self.model.computation)

    def stop_computation(self, widget: UserInterface.PushButtonWidget) -> None:
        self.model.computation.stop()

    def create_handler(self, component_id: str, container: typing.Optional[Symbolic.ComputationVariable] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if component_id == "variable":
            return VariableHandler(self.__computation_inspector_context, self.model.computation, typing.cast(Symbolic.ComputationVariable, item))
        elif component_id == "result":
            return ResultHandler(self.document_controller, self.model.computation, typing.cast(Symbolic.ComputationOutput, item))
        elif component_id == "source_component":
            return EntityBrowser.ReferenceHandler(self.__computation_inspector_context, _("Source"), self.model.computation.source)
        return None

