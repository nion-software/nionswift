from __future__ import annotations

# standard libraries
import asyncio
import collections
import copy
import functools
import gettext
import math
import pkgutil
import sys
import threading
import typing
import uuid

# third party libraries
# None

# local libraries
from nion.data import Calibration
from nion.swift import ComputationInspector
from nion.swift import DataItemThumbnailWidget
from nion.swift import DisplayPanel
from nion.swift import EntityBrowser
from nion.swift import GraphicsInspector
from nion.swift import MimeTypes
from nion.swift import Panel
from nion.swift import Undo
from nion.swift.model import Changes
from nion.swift.model import ColorMaps
from nion.swift.model import DataItem
from nion.swift.model import DataStructure
from nion.swift.model import DisplayInfo
from nion.swift.model import DisplayItem
from nion.swift.model import DocumentModel
from nion.swift.model import Feature
from nion.swift.model import Graphics
from nion.swift.model import Observer
from nion.swift.model import Schema
from nion.swift.model import Symbolic
from nion.ui import Bitmap
from nion.ui import CanvasItem
from nion.ui import Declarative
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
from nion.utils import Stream
from nion.utils import Validator

if typing.TYPE_CHECKING:
    from nion.swift import Application
    from nion.swift import DocumentController
    from nion.swift.model import Persistence
    from nion.data import DataAndMetadata
    from nion.utils import Selection

_ImageDataType = Calibration._ImageDataType


_ = gettext.gettext


class InspectorPanel(Panel.Panel):
    """Inspect the current selection.

    The current selection will be a list of selection specifiers, which is itself a list of containers
    enclosing other containers or objects.
    """

    def __init__(self, document_controller: DocumentController.DocumentController, panel_id: str, properties: Persistence.PersistentDictType) -> None:
        super().__init__(document_controller, panel_id, _("Inspector"))

        # the currently selected display item
        self.__display_item: typing.Optional[DisplayItem.DisplayItem] = None

        self.__display_inspector: typing.Optional[DisplayInspector] = None

        # listen for selected display binding changes
        self.__data_item_will_be_removed_event_listener: typing.Optional[Event.EventListener] = None
        self.__display_item_changed_event_listener = document_controller.focused_display_item_changed_event.listen(self.__display_item_changed)
        self.__set_display_item(None)

        def scroll_area_focus_changed(focused: bool) -> None:
            # ensure that clicking outside of controls but in the scroll area refocuses the display panel.
            if focused:
                scroll_area.request_refocus()

        # top level widget in this inspector is a scroll area.
        # content of the scroll area is the column, to which inspectors
        # can be added.
        scroll_area = self.ui.create_scroll_area_widget(properties)
        scroll_area.set_scrollbar_policies("off", "needed")
        scroll_area.on_focus_changed = scroll_area_focus_changed
        self.column = self.ui.create_column_widget()
        scroll_area.content = self.column
        self.widget = scroll_area

        self.__display_changed_listener: typing.Optional[Event.EventListener] = None
        self.__display_graphic_selection_changed_event_listener: typing.Optional[Event.EventListener] = None
        self.__display_about_to_be_removed_listener: typing.Optional[Event.EventListener] = None
        self.__data_shape: typing.Optional[DataAndMetadata.ShapeType] = None
        self.__display_type: typing.Optional[str] = None
        self.__display_data_shape: typing.Optional[DataAndMetadata.ShapeType] = None

    def close(self) -> None:
        if self.__data_item_will_be_removed_event_listener:
            self.__data_item_will_be_removed_event_listener.close()
            self.__data_item_will_be_removed_event_listener = None
        # disconnect self as listener
        self.__display_item_changed_event_listener.close()
        self.__display_item_changed_event_listener = typing.cast(typing.Any, None)
        # close the property controller. note: this will close and create
        # a new data item inspector; so it should go before the final
        # data item inspector close, which is below.
        self.__set_display_item(None)
        self.__display_inspector = None
        self.document_controller.clear_task("update_display" + str(id(self)))
        self.document_controller.clear_task("update_display_inspector" + str(id(self)))
        # finish closing
        super().close()

    def _get_inspector_sections(self) -> typing.Sequence[InspectorSection]:
        return self.__display_inspector._get_inspectors() if self.__display_inspector else list()

    # close the old data item inspector, and create a new one
    # not thread safe.
    def __update_display_inspector(self) -> None:
        self.column.remove_all()
        if self.__display_inspector:
            if self.__display_changed_listener:
                self.__display_changed_listener.close()
                self.__display_changed_listener = None
            if self.__display_graphic_selection_changed_event_listener:
                self.__display_graphic_selection_changed_event_listener.close()
                self.__display_graphic_selection_changed_event_listener = None
            if self.__display_about_to_be_removed_listener:
                self.__display_about_to_be_removed_listener.close()
                self.__display_about_to_be_removed_listener = None
            self.__display_inspector = None

        data_item = self.__display_item.data_item if self.__display_item else None
        display_data_channel = self.__display_item.display_data_channel if self.__display_item else None

        def rebuild_display_inspector() -> None:
            self.document_controller.add_task("update_display_inspector" + str(id(self)), self.__update_display_inspector)

        self.__display_inspector = DisplayInspector(self.ui, self.document_controller, self.__display_item)
        self.__display_inspector.on_rebuild = rebuild_display_inspector

        new_data_shape = data_item.data_shape if data_item else ()
        new_display_data_shape = display_data_channel.display_data_shape if display_data_channel else ()
        new_display_data_shape = new_display_data_shape if new_display_data_shape is not None else ()
        new_display_type = self.__display_item.display_type if self.__display_item else None

        self.__data_shape = new_data_shape
        self.__display_type = new_display_type
        self.__display_data_shape = new_display_data_shape

        # this ugly item below, which adds a listener for a changing selection and then calls
        # back to this very method, is here to make sure the inspectors get updated when the
        # user changes the selection.
        if self.__display_item:

            def display_item_about_to_be_removed() -> None:
                self.document_controller.clear_task("update_display_inspector" + str(id(self)))

            def display_graphic_selection_changed(graphic_selection: Selection.IndexedSelection) -> None:
                # not really a recursive call; only delayed
                # this may come in on a thread (superscan probe position connection closing). delay even more.
                self.document_controller.add_task("update_display_inspector" + str(id(self)), self.__update_display_inspector)

            def display_changed() -> None:
                # not really a recursive call; only delayed
                # this may come in on a thread (superscan probe position connection closing). delay even more.
                display_data_channel = self.__display_item.display_data_channel if self.__display_item else None
                new_data_shape = data_item.data_shape if data_item else ()
                new_display_data_shape = display_data_channel.display_data_shape if display_data_channel else ()
                new_display_data_shape = new_display_data_shape if new_display_data_shape is not None else ()
                new_display_type = self.__display_item.display_type if self.__display_item else None
                if self.__data_shape != new_data_shape or self.__display_type != new_display_type or self.__display_data_shape != new_display_data_shape:
                    self.document_controller.add_task("update_display_inspector" + str(id(self)), self.__update_display_inspector)

            self.__display_changed_listener = self.__display_item.display_changed_event.listen(display_changed)
            self.__display_graphic_selection_changed_event_listener = self.__display_item.graphic_selection_changed_event.listen(display_graphic_selection_changed)
            self.__display_about_to_be_removed_listener = self.__display_item.about_to_be_removed_event.listen(display_item_about_to_be_removed)

        self.column.add_stretch()
        self.column.insert(self.__display_inspector, 0)

    # not thread safe
    def __set_display_item(self, display_item: typing.Optional[DisplayItem.DisplayItem]) -> None:
        if self.__display_item != display_item:
            self.__display_item = display_item
            self.__update_display_inspector()

    # this message is received from the data item binding.
    # mark the data item as needing updating.
    # thread safe.
    def __display_item_changed(self, display_item: DisplayItem.DisplayItem) -> None:
        data_item = display_item.data_item if display_item else None
        def data_item_will_be_removed(data_item_to_be_removed: DataItem.DataItem) -> None:
            if data_item_to_be_removed == data_item:
                self.document_controller.clear_task("update_display" + str(id(self)))
                self.document_controller.clear_task("update_display_inspector" + str(id(self)))
                if self.__data_item_will_be_removed_event_listener:
                    self.__data_item_will_be_removed_event_listener.close()
                    self.__data_item_will_be_removed_event_listener = None
        def update_display() -> None:
            self.__set_display_item(display_item)
            if self.__data_item_will_be_removed_event_listener:
                self.__data_item_will_be_removed_event_listener.close()
                self.__data_item_will_be_removed_event_listener = None
        # handle the case where the selected display binding changes and then the item is removed before periodic has
        # had a chance to update display. in that case, when periodic finally gets called, we need to make sure that
        # update display has been canceled somehow. this barely passes the smell test.
        if display_item and display_item.data_item:
            if self.__data_item_will_be_removed_event_listener:
                self.__data_item_will_be_removed_event_listener.close()
                self.__data_item_will_be_removed_event_listener = None
            self.__data_item_will_be_removed_event_listener = self.document_controller.document_model.data_item_will_be_removed_event.listen(data_item_will_be_removed)
        self.document_controller.add_task("update_display" + str(id(self)), update_display)


class Unbindable(typing.Protocol):
    @property
    def about_to_be_removed_event(self) -> Event.Event: raise NotImplementedError()


class Unbinder:
    def __init__(self) -> None:
        self.__unbinders: typing.List[typing.Callable[[], None]] = list()
        self.__listener_map: typing.Dict[Unbindable, Event.EventListener] = dict()

    def close(self) -> None:
        for listener in self.__listener_map.values():
            listener.close()
        self.__listener_map = typing.cast(typing.Any, None)

    def add(self, items: typing.Sequence[Unbindable], unbinders: typing.Sequence[typing.Callable[[], None]]) -> None:
        for item in items:
            if item and item not in self.__listener_map:
                self.__listener_map[item] = item.about_to_be_removed_event.listen(self.__unbind)
        self.__unbinders.extend(unbinders)

    def __unbind(self) -> None:
        for unbinder in self.__unbinders:
            unbinder()


class InspectorSection(Widgets.CompositeWidgetBase):
    """A class to manage creation of a widget representing a twist down inspector section.

    Represent a section in the inspector. The section is composed of a title in bold and then content. Subclasses should
    use add_widget_to_content to add items to the content portion of the section, then call finish_widget_content to
    properly handle the stretch at the bottom of the section.

    The content of the section will be associated with a subset of the content of a display specifier. The section is
    responsible for watching for mutations to that subset of content and updating appropriately.
    """

    def __init__(self, ui: UserInterface.UserInterface, section_id: str, section_title: str) -> None:
        self.__section_content_column = ui.create_column_widget()
        section_widget = Widgets.SectionWidget(ui, section_title, self.__section_content_column, "inspector/" + section_id + "/open")

        # create a persistent bool model to store the expanded state of the section.
        # this is used to remember the state of the section when the inspector is closed and reopened.
        # the section id is used to create a unique key for the persistent bool model.
        # the default state is expanded.
        # bind the expanded state to the section widget expanded property.
        self.__persistent_expanded_state = ui.create_persistent_bool_model("inspector-section-expanded." + section_id, True)
        self.__expanded_state_binding = Binding.PropertyBinding(self.__persistent_expanded_state, "value")
        section_widget.bind_expanded(self.__expanded_state_binding)

        super().__init__(section_widget)
        self.ui = ui  # for use in subclasses
        self._unbinder = Unbinder()

    def close(self) -> None:
        self._unbinder.close()
        super().close()

    def add_widget_to_content(self, widget: UserInterface.Widget) -> None:
        """Subclasses should call this to add content in the section's top level column."""
        self.__section_content_column.add_spacing(4)
        self.__section_content_column.add(widget)

    def finish_widget_content(self) -> None:
        """Subclasses should all this after calls to add_widget_content."""
        pass

    @property
    def _section_content_for_test(self) -> UserInterface.BoxWidget:
        return self.__section_content_column


class ChangeDisplayItemPropertyCommand(Undo.UndoableCommand):
    def __init__(self, document_model: DocumentModel.DocumentModel, display_item: DisplayItem.DisplayItem, property_name: str, value: typing.Any) -> None:
        super().__init__(_("Change Display Item Info"), command_id="change_property_" + property_name, is_mergeable=True)
        self.__document_model = document_model
        self.__display_item_proxy = display_item.create_proxy()
        self.__property_name = property_name
        self.__new_display_layers = value
        self.__old_display_layers = getattr(display_item, property_name)
        self.initialize()

    def close(self) -> None:
        self.__document_model = typing.cast(typing.Any, None)
        self.__display_item_proxy.close()
        self.__display_item_proxy = typing.cast(typing.Any, None)
        self.__new_display_layers = None
        self.__old_display_layers = None
        super().close()

    def _perform(self) -> None:
        display_item = self.__display_item_proxy.item
        setattr(display_item, self.__property_name, self.__new_display_layers)

    def _get_modified_state(self) -> typing.Any:
        display_item = self.__display_item_proxy.item
        return display_item.modified_state if display_item else None, self.__document_model.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        display_item = self.__display_item_proxy.item
        if display_item:
            display_item.modified_state = modified_state[0]
        self.__document_model.modified_state = modified_state[1]

    def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return bool(state1[0] == state2[0])

    def _undo(self) -> None:
        display_item = self.__display_item_proxy.item
        self.__new_display_layers = getattr(display_item, self.__property_name)
        setattr(display_item, self.__property_name, self.__old_display_layers)

    def _redo(self) -> None:
        self.perform()

    @property
    def __display_item_uuid(self) -> typing.Optional[uuid.UUID]:
        display_item = self.__display_item_proxy.item
        return display_item.uuid if display_item else None

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, self.__class__) and bool(self.command_id) and self.command_id == command.command_id and self.__display_item_uuid == command.__display_item_uuid


class ChangePropertyCommand(Undo.UndoableCommand):
    def __init__(self, document_model: DocumentModel.DocumentModel, data_item: DataItem.DataItem, property_name: str, value: typing.Any) -> None:
        super().__init__(_("Change Data Item Info"), command_id="change_property_" + property_name, is_mergeable=True)
        self.__document_model = document_model
        self.__data_item_proxy = data_item.create_proxy()
        self.__property_name = property_name
        self.__new_value = value
        self.__old_value = getattr(data_item, property_name)
        self.initialize()

    def close(self) -> None:
        self.__document_model = typing.cast(typing.Any, None)
        self.__data_item_proxy.close()
        self.__data_item_proxy = typing.cast(typing.Any, None)
        self.__new_value = None
        self.__old_value = None
        super().close()

    def _perform(self) -> None:
        data_item = self.__data_item_proxy.item
        setattr(data_item, self.__property_name, self.__new_value)

    def _get_modified_state(self) -> typing.Any:
        data_item = self.__data_item_proxy.item
        return data_item.modified_state if data_item else None, self.__document_model.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        data_item = self.__data_item_proxy.item
        if data_item:
            data_item.modified_state = modified_state[0]
        self.__document_model.modified_state = modified_state[1]

    def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return bool(state1[0] == state2[0])

    def _undo(self) -> None:
        data_item = self.__data_item_proxy.item
        self.__new_value = getattr(data_item, self.__property_name)
        setattr(data_item, self.__property_name, self.__old_value)

    def _redo(self) -> None:
        self.perform()

    @property
    def __data_item_uuid(self) -> typing.Optional[uuid.UUID]:
        data_item = self.__data_item_proxy.item if self.__data_item_proxy else None
        return data_item.uuid if data_item else None

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, self.__class__) and bool(self.command_id) and self.command_id == command.command_id and self.__data_item_uuid == command.__data_item_uuid


class DisplayDataChannelPropertyCommandModel(Model.PropertyChangedPropertyModel[typing.Any]):
    """Display data channel property command model.

    This model makes undoable changes to a display data channel property.

    The value of the display data channel property appears as the 'value' property of this model.
    """

    def __init__(self, document_controller: DocumentController.DocumentController,
                 display_data_channel: DisplayItem.DisplayDataChannel, property_name: str, title: str,
                 command_id: str) -> None:
        super().__init__(display_data_channel, property_name)
        self.__document_controller = document_controller
        self.__title = title
        self.__command_id = command_id

    def _set_property_value(self, value: typing.Optional[typing.Any]) -> None:
        if value != self._get_property_value():
            document_controller = self.__document_controller
            display_data_channel = typing.cast(DisplayItem.DisplayDataChannel, self._observable)
            property_name = self._property_name
            title = self.__title
            command_id = self.__command_id
            command = DisplayPanel.ChangeDisplayDataChannelCommand(document_controller.document_model, display_data_channel,
                                                                   title=title, command_id=command_id, is_mergeable=True,
                                                                   **{property_name: value})
            command.perform()
            document_controller.push_undo_command(command)


class DisplayDataChannelAdjustmentPropertyCommandModel(Model.PropertyChangedPropertyModel[typing.Any]):
    """Display data channel property command model.

    This model makes undoable changes to a display data channel property.

    The value of the display data channel property appears as the 'value' property of this model.
    """

    def __init__(self, document_controller: DocumentController.DocumentController,
                 display_data_channel: DisplayItem.DisplayDataChannel, property_name: str, default_value: typing.Any = None) -> None:
        super().__init__(display_data_channel, "adjustments")
        self.__document_controller = document_controller
        self.__default_value = default_value
        self.__adjustment_name = property_name

    def _set_property_value(self, value: typing.Optional[typing.Any]) -> None:
        document_controller = self.__document_controller
        display_data_channel = typing.cast(DisplayItem.DisplayDataChannel, self._observable)
        property_name = self.__adjustment_name
        if value != display_data_channel.adjustments[0].get(property_name, None):
            adjustment = display_data_channel.adjustments[0]
            adjustment[property_name] = value
            command = DisplayPanel.ChangeDisplayDataChannelCommand(document_controller.document_model, display_data_channel, title=_("Change Display"), command_id="change_display_" + property_name, is_mergeable=True, adjustments=[adjustment])
            command.perform()
            document_controller.push_undo_command(command)

    def _get_property_value(self) -> typing.Optional[typing.Any]:
        display_data_channel = typing.cast(DisplayItem.DisplayDataChannel, self._observable)
        property_name = self.__adjustment_name
        if len(display_data_channel.adjustments) == 1:
            return display_data_channel.adjustments[0].get(property_name, self.__default_value)
        return self.__default_value


class DisplayItemPropertyCommandModel(Model.PropertyChangedPropertyModel[typing.Any]):
    def __init__(self, document_controller: DocumentController.DocumentController,
                 display_item: DisplayItem.DisplayItem, property_name: str) -> None:
        super().__init__(display_item, property_name)
        self.__display_item = display_item
        self.__document_controller = document_controller
        self.__property_name = property_name

    def _set_property_value(self, value: typing.Optional[typing.Any]) -> None:
        if value != self._get_property_value():
            command = ChangeDisplayItemPropertyCommand(self.__document_controller.document_model, self.__display_item, self.__property_name, value)
            command.perform()
            self.__document_controller.push_undo_command(command)

    def _get_property_value(self) -> typing.Optional[typing.Any]:
        return getattr(self.__display_item, self.__property_name)


class DisplayItemDisplayPropertyCommandModel(Model.PropertyModel[typing.Any]):
    """Display item channel property command model.

    This model makes undoable changes to a display item property.
    """

    def __init__(self, document_controller: DocumentController.DocumentController,
                 display_item: DisplayItem.DisplayItem, property_name: str) -> None:
        super().__init__()
        self.__display_item = display_item
        self.__document_controller = document_controller
        self.__property_name = property_name
        # avoid using display_properties_changed event, as it is not guaranteed to be called when the display
        # properties change. instead just listen for display item property changes, respond to 'display_properties'
        # changing. then let the PropertyModel machinery check for changes and send out notifications.
        self.__listener = display_item.property_changed_event.listen(ReferenceCounting.weak_partial(DisplayItemDisplayPropertyCommandModel.__display_property_changed, self))
        self.value = self._get_property_value()

    def __display_property_changed(self, key: str) -> None:
        if key == "display_properties":
            # the PropertyModel does a similar check when setting the property value. but here we don't want to set
            # the property value since that will trigger a command. this is being received as an outside change and
            # should not post an undo command that can be undone. if the value change is received from the UI,
            # then it should post an undo command.
            value = self._get_property_value()
            if self.value is None:
                not_equal = value is not None
            elif value is None:
                not_equal = self.value is not None
            else:
                not_equal = value != self.value
            if not_equal:
                super()._set_value(self._get_property_value())

    def _set_value(self, value: typing.Optional[typing.Any]) -> None:
        # override this to generate the command. the _set_value sets the PropertyModel value, the command sets the
        # actual value in the display item.
        super()._set_value(value)
        command = DisplayPanel.ChangeDisplayCommand(self.__document_controller.document_model, self.__display_item,
                                                    title=_("Change Display"),
                                                    command_id="change_display_" + self.__property_name, is_mergeable=True,
                                                    **{self.__property_name: value})
        command.perform()
        self.__document_controller.push_undo_command(command)

    def _get_property_value(self) -> typing.Optional[typing.Any]:
        return self.__display_item.get_display_property(self.__property_name)


class InfoInspectorHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem):
        super().__init__()
        self._display_item = display_item
        self._title_model = DisplayItemPropertyCommandModel(document_controller, display_item, "title")
        self._placeholder_title_model = DisplayItemPropertyCommandModel(document_controller, display_item, "placeholder_title")
        self._caption_model = DisplayItemPropertyCommandModel(document_controller, display_item, "caption")
        self._editable_caption_model = Model.PropertyModel[str](display_item.caption)
        self._caption_current_index = Model.PropertyModel[int](0)
        self._session_id_model = Model.PropertyChangedPropertyModel[str](display_item, "session_id")
        self._created_local_as_string_model = DisplayItemPropertyCommandModel(document_controller, display_item, "created_local_as_string")
        self.info_title_label: typing.Optional[UserInterface.Widget] = None

        u = Declarative.DeclarativeUI()

        TOOL_TIP_STR = _("Use empty field for automatic title.")

        self.ui_view = u.create_column(
            u.create_row(
                u.create_label(text=_("Title"), width=60, tool_tip=TOOL_TIP_STR),
                u.create_line_edit(name="info_title_label", text="@binding(_title_model.value)", placeholder_text="@binding(_placeholder_title_model.value)", tool_tip=TOOL_TIP_STR),
                u.create_spacing(8)
            ),
            u.create_row(
                u.create_column(
                    u.create_label(text=_("Caption"), width=60),
                    u.create_stretch()
                ),
                u.create_stack(
                    u.create_column(
                        u.create_text_edit(height=60, editable=False, text="@binding(_caption_model.value)"),
                        u.create_row(
                            u.create_push_button(text=_("Edit"), on_clicked="_begin_caption_edit"),
                            u.create_stretch()
                        ),
                    ),
                    u.create_column(
                        u.create_text_edit(height=60, text="@binding(_editable_caption_model.value)"),
                        u.create_row(
                            u.create_push_button(text=_("Save"), on_clicked="_save_caption_edit"),
                            u.create_push_button(text=_("Cancel"), on_clicked="_end_caption_edit"),
                            u.create_stretch()
                        )
                    ),
                    current_index="@binding(_caption_current_index.value)"
                ),
                u.create_spacing(8)
            ),
            u.create_row(
                u.create_label(text=_("Session"), width=60),
                u.create_label(text="@binding(_session_id_model.value)", width=240),
                u.create_stretch()
            ),
            u.create_row(
                u.create_label(text=_("Date"), width=60),
                u.create_label(text="@binding(_created_local_as_string_model.value)"),
            ),
            spacing=4
        )

    def _begin_caption_edit(self, widget: UserInterface.Widget) -> None:
        self._editable_caption_model.value = self._display_item.caption
        self._caption_current_index.value = 1

    def _save_caption_edit(self, widget: UserInterface.Widget) -> None:
        new_caption = self._editable_caption_model.value
        self._caption_model.value = new_caption if new_caption is not None else str()
        self._caption_current_index.value = 0

    def _end_caption_edit(self, widget: UserInterface.Widget) -> None:
        self._editable_caption_model.value = self._display_item.caption
        self._caption_current_index.value = 0


class InfoInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement info inspector.
    """

    def __init__(self, document_controller: DocumentController.DocumentController,
                 display_item: DisplayItem.DisplayItem) -> None:
        super().__init__(document_controller.ui, "info", _("Info"))
        self.widget_id = "info_inspector_section"

        self._info_section_handler = InfoInspectorHandler(document_controller, display_item)
        widget = Declarative.DeclarativeWidget(document_controller.ui, document_controller.event_loop, self._info_section_handler)
        self.add_widget_to_content(widget)

        self.info_title_label = self._info_section_handler.info_title_label


class DataInfoInspectorSectionHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController, display_data_channel: DisplayItem.DisplayDataChannel):
        super().__init__()

        self._created_local_as_string_model = DisplayDataChannelPropertyCommandModel(document_controller, display_data_channel, "created_local_as_string", title=_("Created Local"), command_id="created_local_changed")
        self._size_and_data_format_as_string = DisplayDataChannelPropertyCommandModel(document_controller, display_data_channel, "size_and_data_format_as_string", title=_("Size And Data Format"), command_id="size_and_data_format_changed")

        u = Declarative.DeclarativeUI()

        self.ui_view = u.create_column(
            u.create_row(
                u.create_label(text=_("Date"), width=60),
                u.create_label(text="@binding(_created_local_as_string_model.value)", width=240),
                u.create_stretch()
            ),
            u.create_row(
                u.create_label(text=_("Data"), width=60),
                u.create_label(text="@binding(_size_and_data_format_as_string.value)", width=240),
                u.create_stretch()
            ),
            spacing=4,
            margin_bottom=4
        )


class DataInfoInspectorSection(InspectorSection):
    def __init__(self, document_controller: DocumentController.DocumentController, display_data_channel: DisplayItem.DisplayDataChannel) -> None:
        super().__init__(document_controller.ui, "data-info", _("Data Info"))
        self._data_info_handler = DataInfoInspectorSectionHandler(document_controller, display_data_channel)
        widget = Declarative.DeclarativeWidget(document_controller.ui, document_controller.event_loop, self._data_info_handler)

        self.add_widget_to_content(widget)


class ChangeDisplayLayerPropertyCommand(Undo.UndoableCommand):
    def __init__(self, document_model: DocumentModel.DocumentModel, display_item: DisplayItem.DisplayItem, display_layer_index: int, property_name: str, value: typing.Any) -> None:
        super().__init__(_("Change Display Layer Info"), command_id="change_display_layer_" + property_name, is_mergeable=True)
        self.__document_model = document_model
        self.__display_item_proxy = display_item.create_proxy()
        self.__display_layer_index = display_layer_index
        self.__property_name = property_name
        self.__value = value
        self.__old_properties = display_item.save_properties()
        self.initialize()

    def close(self) -> None:
        self.__document_model = typing.cast(typing.Any, None)
        self.__display_item_proxy.close()
        self.__display_item_proxy = typing.cast(typing.Any, None)
        super().close()

    def _perform(self) -> None:
        display_item = self.__display_item_proxy.item
        if display_item:
            display_item._set_display_layer_property(self.__display_layer_index, self.__property_name, self.__value)

    def _get_modified_state(self) -> typing.Any:
        display_item = self.__display_item_proxy.item
        return display_item.modified_state if display_item else None, self.__document_model.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        display_item = self.__display_item_proxy.item
        if display_item:
            display_item.modified_state = modified_state[0]
        self.__document_model.modified_state = modified_state[1]

    def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return bool(state1[0] == state2[0])

    def _undo(self) -> None:
        display_item = self.__display_item_proxy.item
        if display_item:
            display_item.restore_properties(self.__old_properties)

    def _redo(self) -> None:
        self.perform()

    @property
    def __display_item_uuid(self) -> typing.Optional[uuid.UUID]:
        display_item = self.__display_item_proxy.item
        return display_item.uuid if display_item else None

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, self.__class__) and bool(self.command_id) and self.command_id == command.command_id and self.__display_item_uuid == command.__display_item_uuid


class ChangeDisplayLayerDisplayDataChannelCommand(Undo.UndoableCommand):
    def __init__(self, document_model: DocumentModel.DocumentModel, display_item: DisplayItem.DisplayItem, display_layer: DisplayItem.DisplayLayer, display_data_channel: DisplayItem.DisplayDataChannel) -> None:
        super().__init__(_("Change Display Layer Data"), command_id="change_display_layer_data", is_mergeable=True)
        self.__document_model = document_model
        self.__display_item_proxy = display_item.create_proxy()
        self.__display_layer_uuid = display_layer.uuid
        self.__display_data_channel_proxy = display_data_channel.create_proxy() if display_data_channel else None
        self.initialize()

    def close(self) -> None:
        self.__document_model = typing.cast(typing.Any, None)
        self.__display_item_proxy.close()
        self.__display_item_proxy = typing.cast(typing.Any, None)
        if self.__display_data_channel_proxy:
            self.__display_data_channel_proxy.close()
            self.__display_data_channel_proxy = None
        super().close()

    def _perform(self) -> None:
        display_item = self.__display_item_proxy.item
        display_data_channel = self.__display_data_channel_proxy.item if self.__display_data_channel_proxy else None
        if display_item:
            display_layer = display_item.get_display_layer_by_uuid(self.__display_layer_uuid)
            assert display_layer
            old_display_data_channel = display_layer.display_data_channel
            assert display_data_channel is None or display_data_channel in display_item.display_data_channels
            display_layer.display_data_channel = display_data_channel
            if old_display_data_channel:
                if not self.__display_data_channel_proxy:
                    self.__display_data_channel_proxy = old_display_data_channel.create_proxy() if old_display_data_channel else None
                else:
                    self.__display_data_channel_proxy.item = old_display_data_channel
            elif self.__display_data_channel_proxy:
                self.__display_data_channel_proxy.close()
                self.__display_data_channel_proxy = None

    def _get_modified_state(self) -> typing.Any:
        display_item = self.__display_item_proxy.item
        return display_item.modified_state if display_item else None, self.__document_model.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        display_item = self.__display_item_proxy.item
        if display_item:
            display_item.modified_state = modified_state[0]
        self.__document_model.modified_state = modified_state[1]

    def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return bool(state1[0] == state2[0])

    def _undo(self) -> None:
        self.perform()

    @property
    def __display_item_uuid(self) -> typing.Optional[uuid.UUID]:
        display_item = self.__display_item_proxy.item
        return display_item.uuid if display_item else None

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, self.__class__) and bool(self.command_id) and self.command_id == command.command_id and self.__display_item_uuid == command.__display_item_uuid


class DisplayLayerPropertyCommandModel(Model.PropertyChangedPropertyModel[typing.Any]):
    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, display_layer: DisplayItem.DisplayLayer, property_name: str):
        super().__init__(display_layer, property_name)
        self.__document_controller = document_controller
        self.__display_item = display_item
        self.__display_layer = display_layer
        self.__property_name = property_name

    def _get_property_value(self) -> typing.Any:
        return getattr(self.__display_layer, self.__property_name)

    def _set_property_value(self, property_value: typing.Any) -> None:
        if property_value != self._get_property_value():
            index = self.__display_item.display_layers.index(self.__display_layer)
            command = ChangeDisplayLayerPropertyCommand(self.__document_controller.document_model, self.__display_item, index,
                                                        self.__property_name, property_value)
            command.perform()
            self.__document_controller.push_undo_command(command)


class LinePlotDisplayLayerHandler(Declarative.Handler):
    def __init__(self, line_plot_display_layer_model: LinePlotDisplayLayerModel):
        super().__init__()
        self._line_plot_display_layer_model = line_plot_display_layer_model
        self.integer_to_string_converter = Converter.IntegerToStringConverter()
        self.float_to_string_converter = Converter.FloatToStringConverter()

        u = Declarative.DeclarativeUI()
        self.ui_view = u.create_column(
            u.create_row(
                u.create_label(text=_("Layer")),
                u.create_line_edit(text="@binding(_line_plot_display_layer_model.label_model.value)", placeholder_text="@binding(_line_plot_display_layer_model.placeholder_label_model.value)"),
                u.create_spacing(12),
                spacing=12
            ),
            u.create_row(
                {"type": "nionswift.text_push_button",
                 "text": "\N{UPWARDS WHITE ARROW}",
                 "on_button_clicked": "_move_layer_forward",
                 "tool_tip": _("Move layer up.")},
                {"type": "nionswift.text_push_button",
                 "text": "\N{DOWNWARDS WHITE ARROW}",
                 "on_button_clicked": "_move_layer_backward",
                 "tool_tip": _("Move layer down.")},
                u.create_stretch(),
                {"type": "nionswift.text_push_button",
                 "text": "\N{PLUS SIGN}",
                 "on_button_clicked": "_add_layer",
                 "tool_tip": _("Add layer.")},
                {"type": "nionswift.text_push_button",
                 "text": "\N{MINUS SIGN}",
                 "on_button_clicked": "_remove_layer",
                 "tool_tip": _("Remove layer.")},
                u.create_spacing(12)
            ),
            u.create_row(
                u.create_label(text=_("Data Index")),
                u.create_line_edit(text="@binding(_line_plot_display_layer_model.data_index_model.value, converter=integer_to_string_converter)"),
                u.create_label(text=_("Row")),
                u.create_line_edit(text="@binding(_line_plot_display_layer_model.data_row_model.value, converter=integer_to_string_converter)"),
                u.create_stretch(),
                spacing=12
            ),
            u.create_row(
                u.create_label(text=_("Fill Color"), width=80, text_alignment_vertical="vcenter", text_alignment_horizontal="right"),
                u.create_line_edit(text="@binding(_line_plot_display_layer_model.fill_color_model.value)", placeholder_text=_("None"), width=80),
                {"type": "nionswift.color_chooser", "color": "@binding(_line_plot_display_layer_model.fill_color_model.value)"},
                u.create_stretch(),
                spacing=8
            ),
            u.create_row(
                u.create_label(text=_("Stroke Color"), width=80, text_alignment_vertical="vcenter", text_alignment_horizontal="right"),
                u.create_line_edit(text="@binding(_line_plot_display_layer_model.stroke_color_model.value)", placeholder_text=_("None"), width=80),
                {"type": "nionswift.color_chooser", "color": "@binding(_line_plot_display_layer_model.stroke_color_model.value)"},
                u.create_stretch(),
                spacing=8
            ),
            u.create_row(
                u.create_label(text=_("Stroke Width"), width=80, height=30, text_alignment_vertical="vcenter", text_alignment_horizontal="right"),
                u.create_line_edit(text="@binding(_line_plot_display_layer_model.stroke_width_model.value, converter=float_to_string_converter)", width=36),
                u.create_stretch(),
                spacing=8
            ),
            u.create_row(
                u.create_label(text=_("Graph Style"), width=80, text_alignment_vertical="vcenter", text_alignment_horizontal="right"),
                u.create_combo_box(items=self._line_plot_display_layer_model.graph_style_items,
                                   current_index="@binding(_line_plot_display_layer_model.current_graph_style_index_model.value)"),
                u.create_stretch(),
                spacing=8
            ),
            u.create_row(
                u.create_label(text=_("Complex Display"), width=120),
                u.create_combo_box(items=self._line_plot_display_layer_model.display_type_items,
                                   current_index="@binding(_line_plot_display_layer_model.current_display_type_index_model.value)"),
                u.create_stretch(),
                visible="@binding(_line_plot_display_layer_model.is_data_complex)"
            )
        )

    def _move_layer_forward(self) -> None:
        index = self._line_plot_display_layer_model.display_item.display_layers.index(self._line_plot_display_layer_model.display_layer)
        if index > 0:
            command = DisplayPanel.MoveDisplayLayerCommand(self._line_plot_display_layer_model.document_controller.document_model,
                                                           self._line_plot_display_layer_model.display_item,
                                                           index,
                                                           self._line_plot_display_layer_model.display_item,
                                                           index - 1)
            command.perform()
            self._line_plot_display_layer_model.document_controller.push_undo_command(command)

    def _move_layer_backward(self) -> None:
        index = self._line_plot_display_layer_model.display_item.display_layers.index(self._line_plot_display_layer_model.display_layer)
        if index < len(self._line_plot_display_layer_model.display_item.display_layers) - 1:
            command = DisplayPanel.MoveDisplayLayerCommand(self._line_plot_display_layer_model.document_controller.document_model,
                                                           self._line_plot_display_layer_model.display_item,
                                                           index,
                                                           self._line_plot_display_layer_model.display_item,
                                                           index + 1)
            command.perform()
            self._line_plot_display_layer_model.document_controller.push_undo_command(command)

    def _add_layer(self) -> None:
        # add new layer after current layer
        index = self._line_plot_display_layer_model.display_item.display_layers.index(self._line_plot_display_layer_model.display_layer) + 1
        command = DisplayPanel.AddDisplayLayerCommand(self._line_plot_display_layer_model.document_controller.document_model,
                                                      self._line_plot_display_layer_model.display_item,
                                                      index)
        command.perform()
        self._line_plot_display_layer_model.document_controller.push_undo_command(command)

    def _remove_layer(self) -> None:
        index = self._line_plot_display_layer_model.display_item.display_layers.index(self._line_plot_display_layer_model.display_layer)
        command = DisplayPanel.RemoveDisplayLayerCommand(self._line_plot_display_layer_model.document_controller.document_model,
                                                         self._line_plot_display_layer_model.display_item,
                                                         index)
        command.perform()
        self._line_plot_display_layer_model.document_controller.push_undo_command(command)


class LinePlotDisplayLayerModel(Observable.Observable):
    def __init__(self, document_controller: DocumentController.DocumentController,
                 display_item: DisplayItem.DisplayItem, display_layer: DisplayItem.DisplayLayer) -> None:
        super().__init__()
        self.document_controller = document_controller
        self.display_item = display_item
        self.display_layer = display_layer
        self.label_model = DisplayLayerPropertyCommandModel(document_controller, display_item, display_layer, "label")

        # to follow changes to the title, we need to observe the display data channel for changes to the data item,
        # and then observe the data item for changes to the title, and then update the placeholder label model when
        # the title changes. to accomplish this, we create a chain of observers using the ObserverBuilder and then
        # use the Observer.ItemValueModel as the model.
        oo = Observer.ObserverBuilder()
        oo.source(display_layer).prop("display_data_channel").prop("data_item").prop("title")
        self.placeholder_label_model = Observer.ItemValueModel(oo.make_observable())

        index = display_item.display_layers.index(display_layer)
        display_data_channel = display_item.get_display_layer_display_data_channel(index)
        data_index = display_item.display_data_channels.index(display_data_channel) if display_data_channel else None
        self.data_index_model = Model.PropertyModel(data_index)

        self.data_row_model = DisplayLayerPropertyCommandModel(document_controller, display_item, display_layer, "data_row")
        self.fill_color_model = DisplayLayerPropertyCommandModel(document_controller, display_item, display_layer, "fill_color")
        self.stroke_color_model = DisplayLayerPropertyCommandModel(document_controller, display_item, display_layer, "stroke_color")
        self.stroke_width_model = DisplayLayerPropertyCommandModel(document_controller, display_item, display_layer, "stroke_width")

        self.graph_style_items = [_("Bar"), _("Line")]
        self._graph_style_flags = ["bar", "line"]
        self._graph_style_reverse_map = {p: i for i, p in enumerate(self._graph_style_flags)}
        current_graph_style = display_layer.graph_style or "bar"
        self.current_graph_style_index_model = Model.PropertyModel[int](self._graph_style_reverse_map.get(current_graph_style, 0))

        self.display_type_items = [_("Log Absolute"), _("Absolute"), _("Phase"), _("Real"), _("Imaginary")]
        self._display_type_flags = ["log-absolute", "absolute", "phase", "real", "imaginary"]
        self._display_type_reverse_map = {p: i for i, p in enumerate(self._display_type_flags)}

        current_flag = display_data_channel.complex_display_type if display_data_channel and display_data_channel.complex_display_type else str()
        self.current_display_type_index_model = Model.PropertyModel[int](self._display_type_reverse_map.get(current_flag, 0))

        self.__data_index_listener = self.data_index_model.property_changed_event.listen(
            ReferenceCounting.weak_partial(LinePlotDisplayLayerModel.__on_data_index_changed, self))
        self.__display_type_index_listener_model = self.current_display_type_index_model.property_changed_event.listen(
            ReferenceCounting.weak_partial(LinePlotDisplayLayerModel.__on_display_type_index_changed, self))
        self.__graph_style_index_listener_model = self.current_graph_style_index_model.property_changed_event.listen(
            ReferenceCounting.weak_partial(LinePlotDisplayLayerModel.__on_graph_style_index_changed, self))

    @property
    def is_data_complex(self) -> bool:
        if self.display_layer.display_data_channel and self.display_layer.display_data_channel.data_item:
            return self.display_layer.display_data_channel.data_item.is_data_complex_type
        return False

    def __on_data_index_changed(self, property: str) -> None:
        if property == "value":
            display_data_channel = self.display_item.display_data_channels[self.data_index_model.value] if self.data_index_model.value is not None else None
            if display_data_channel:
                command = ChangeDisplayLayerDisplayDataChannelCommand(self.document_controller.document_model,
                                                                      self.display_item,
                                                                      self.display_layer,
                                                                      display_data_channel)
                command.perform()
                self.document_controller.push_undo_command(command)

    def __on_display_type_index_changed(self, property: str) -> None:
        if property == "value":
            new_type = self._display_type_flags[self.current_display_type_index_model.value or 0]
            assert self.display_layer.display_data_channel
            command = DisplayPanel.ChangeDisplayDataChannelCommand(self.document_controller.document_model,
                                                                   self.display_layer.display_data_channel,
                                                                   complex_display_type=new_type)
            command.perform()
            self.document_controller.push_undo_command(command)

    def __on_graph_style_index_changed(self, property: str) -> None:
        if property == "value":
            new_style = self._graph_style_flags[self.current_graph_style_index_model.value or 0]
            index = self.display_item.display_layers.index(self.display_layer)
            if self.display_item.get_display_layer_property(index, "graph_style") != new_style:
                command = ChangeDisplayLayerPropertyCommand(self.document_controller.document_model,
                                                            self.display_item, index, "graph_style", new_style)
                command.perform()
                self.document_controller.push_undo_command(command)

    def __on_display_layer_list_changed(self, key: str, value: typing.Any, index: int) -> None:
        # changes affect all indices after index of change
        if key == "items":
            self.notify_property_changed("index")


class LinePlotDisplayLayersSectionHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, display_layer_list_model: ListModel.ObservedListModel[DisplayItem.DisplayLayer]) -> None:
        super().__init__()
        self.__document_controller = document_controller
        self.__display_item = display_item
        self._line_plot_display_layer_models = display_layer_list_model
        self._line_plot_display_layer_handlers: list[LinePlotDisplayLayerHandler] = []
        self._show_no_layers_model = Stream.MapStream(Stream.ValueStream(ListModel.ListPropertyModel(self._line_plot_display_layer_models)), lambda x: not x)

        u = Declarative.DeclarativeUI()
        self.ui_view = u.create_column(
            u.create_column(items="_line_plot_display_layer_models.items", item_component_id="line_plot_display_layer", spacing=4),
            u.create_row(
                u.create_push_button(text=_("Add Layer")),
                u.create_stretch(),
                visible="@binding(_show_no_layers_model.value)"
            )
        )

    def create_handler(self, component_id: str, container: typing.Optional[Symbolic.ComputationVariable] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if component_id == "line_plot_display_layer":
            line_plot_display_layer_model = LinePlotDisplayLayerModel(self.__document_controller, self.__display_item, typing.cast(DisplayItem.DisplayLayer, item))
            handler = LinePlotDisplayLayerHandler(line_plot_display_layer_model)
            self._line_plot_display_layer_handlers.append(handler)
            return handler
        return None

    def add_layer(self) -> None:
        command = DisplayPanel.AddDisplayLayerCommand(self.__document_controller.document_model,
                                                      self.__display_item,
                                                      0)
        command.perform()
        self.__document_controller.push_undo_command(command)


class LinePlotDisplayLayersInspectorSection(InspectorSection):
    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem) -> None:
        super().__init__(document_controller.ui, "line-plot-display-layer", _("Line Plot Display Layers"))
        self.widget_id = "line_plot_display_layers_inspector_section"
        self.__document_controller = document_controller
        self.__display_item = display_item
        display_layer_list_model = ListModel.ObservedListModel[DisplayItem.DisplayLayer](self.__display_item, "display_layers")
        self._handler = LinePlotDisplayLayersSectionHandler(self.__document_controller, self.__display_item, display_layer_list_model)
        self.__widget = Declarative.DeclarativeWidget(self.__document_controller.ui, self.__document_controller.event_loop, self._handler)
        self.add_widget_to_content(self.__widget)


class ImageDisplayLimitsModel(Observable.Observable):
    def __init__(self, display_data_channel: DisplayItem.DisplayDataChannel, display_limits_model: Model.PropertyModel[typing.Tuple[int, ...]], index: int) -> None:
        super().__init__()
        data_item = display_data_channel.data_item

        assert data_item
        self.__display_data_channel = display_data_channel
        self.__data_item = data_item
        self.__index = index
        self.__display_limits_model = display_limits_model
        self.__display_limits_model_listener = self.__display_limits_model.property_changed_event.listen(
            ReferenceCounting.weak_partial(ImageDisplayLimitsModel.__handle_limits_changed, self))
        self.__last_value = self.value

    def __handle_limits_changed(self, property_name: str) -> None:
        if property_name == "value":
            if self.value != self.__last_value:
                self.__last_value = self.value
                self.notify_property_changed("value")

    @property
    def display_data_channel(self) -> DisplayItem.DisplayDataChannel:
        return self.__display_data_channel

    @property
    def index(self) -> int:
        return self.__index

    @property
    def value(self) -> typing.Optional[int]:
        tuple_value = self.__display_limits_model.value
        return tuple_value[self.__index] if tuple_value else None

    @value.setter
    def value(self, value: int) -> None:
        tuple_value = self.__display_limits_model.value
        display_limits = list(tuple_value) if tuple_value else []
        while len(display_limits) <= self.__index:
            display_limits.append(0)
        display_limits[self.__index] = value
        self.__display_limits_model.value = tuple(display_limits)
        self.__last_value = self.value


class ImageDataInspectorModel(Observable.Observable):
    def __init__(self, document_controller: DocumentController.DocumentController, display_data_channel: DisplayItem.DisplayDataChannel, display_item: DisplayItem.DisplayItem) -> None:
        super().__init__()
        self._document_controller = document_controller
        self._display_data_channel = display_data_channel
        self._display_item = display_item

        self.info_datetime_model = DisplayDataChannelPropertyCommandModel(document_controller, display_data_channel, "created_local_as_string", title=_("Created Date Time"), command_id="change_created_local_as_string")

        self.size_and_data_format_model = DisplayDataChannelPropertyCommandModel(document_controller, display_data_channel, "size_and_data_format_as_string", title=_("Size and Data Format"), command_id="change_size_and_data_format_as_string")

        self.data_range_low_model = Model.PropertyModel[float]()
        self.data_range_high_model = Model.PropertyModel[float]()

        def update_data_range_models(display_info: DisplayInfo.DisplayInfo | None) -> None:
            if display_info:
                display_data_info = display_info.display_data_info
                if display_data_info:
                    data_range = display_data_info.data_range
                    if data_range is not None:
                        self.data_range_low_model.value = data_range[0]
                        self.data_range_high_model.value = data_range[1]

        self.__display_info_action = Stream.ValueStreamAction(display_item.display_info_stream, update_data_range_models)

        update_data_range_models(display_item.display_info)

        display_limits_model = DisplayDataChannelPropertyCommandModel(document_controller, display_data_channel, "display_limits", title=_("Change Display Limits"), command_id="change_display_limits")
        self.display_limits_low_model = ImageDisplayLimitsModel(display_data_channel, display_limits_model, 0)
        self.display_limits_high_model = ImageDisplayLimitsModel(display_data_channel, display_limits_model, 1)

        self.color_map_items: typing.List[str] = [_("Default")]
        self._color_map_flags: typing.List[typing.Optional[str]] = [None]
        for color_map_key, color_map in ColorMaps.color_maps.items():
            self.color_map_items.append(color_map.name)
            self._color_map_flags.append(color_map_key)
        self._color_map_reverse_map = {p: i for i, p in enumerate(self._color_map_flags)}
        color_map_index = self._color_map_reverse_map.get(self._display_data_channel.color_map_id, 0)
        self.current_colormap_index = Model.PropertyModel[int](color_map_index)

        self.brightness_model = DisplayDataChannelPropertyCommandModel(document_controller, display_data_channel, "brightness", title=_("Change Brightness"), command_id="change_brightness")

        self.contrast_model = DisplayDataChannelPropertyCommandModel(document_controller, display_data_channel, "contrast", title=_("Change Contrast"), command_id="change_contrast")

        self.adjustment_options_items: typing.List[str] = [_("None"), _("Equalized"), _("Gamma"), _("Log")]
        self._adjustment_options_flags: typing.List[typing.Optional[str]] = [None, "equalized", "gamma", "log"]
        self._adjustment_options_reverse_map = {p: i for i, p in enumerate(self._adjustment_options_flags)}
        self.current_adjustment_options_index = Model.PropertyModel[int](self.get_current_adjustment_index())
        self.show_gamma_controls = Model.PropertyModel[bool](self._get_gamma_visibility())

        self.gamma_model = DisplayDataChannelAdjustmentPropertyCommandModel(document_controller, display_data_channel, "gamma", 1.0)

        self.listener = self._display_data_channel.property_changed_event.listen(ReferenceCounting.weak_partial(ImageDataInspectorModel.__property_changed, self))

    def _get_gamma_visibility(self) -> bool:
        return self.get_current_adjustment_id() == "gamma"

    def _update_gamma_visibility(self) -> None:
        self.show_gamma_controls.value = self._get_gamma_visibility()

    def get_current_adjustment_id(self) -> typing.Optional[str]:
        return self._display_data_channel.adjustments[0].get("type") if len(self._display_data_channel.adjustments) == 1 else None

    def get_current_adjustment_index(self) -> int:
        return self._adjustment_options_reverse_map[self.get_current_adjustment_id()]

    def __property_changed(self, name: str) -> None:
        if name == "color_map_id":
            self.current_colormap_index.value = self._color_map_reverse_map[self._display_data_channel.color_map_id]
        if name == "adjustments":
            self.current_adjustment_options_index.value = self.get_current_adjustment_index()
            self._update_gamma_visibility()

    def change_color_map(self, widget: Declarative.UIWidget, current_index: int) -> None:
        current_color_map = self._color_map_flags[current_index]
        if self._display_data_channel.color_map_id != current_color_map:
            command = DisplayPanel.ChangeDisplayDataChannelCommand(self._document_controller.document_model,
                                                                   self._display_data_channel,
                                                                   color_map_id=current_color_map,
                                                                   title=_("Change Color Map"),
                                                                   command_id="change_color_map", is_mergeable=True)
            command.perform()
            self._document_controller.push_undo_command(command)

    def change_adjustment_option(self, widget: Declarative.UIWidget, current_index: int) -> None:
        adjustment_option = self._adjustment_options_flags[current_index]
        if self.get_current_adjustment_id() != adjustment_option:
            adjustments = list() if adjustment_option is None else [{"type": adjustment_option, "uuid": str(uuid.uuid4())}]
            command = DisplayPanel.ChangeDisplayDataChannelCommand(self._document_controller.document_model,
                                                                   self._display_data_channel, adjustments=adjustments)
            command.perform()
            self._document_controller.push_undo_command(command)
            self._update_gamma_visibility()


class ImageDataInspectorHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController, display_data_channel: DisplayItem.DisplayDataChannel, display_item: DisplayItem.DisplayItem) -> None:
        super().__init__()
        self._model = ImageDataInspectorModel(document_controller, display_data_channel, display_item)
        self._float_point_2_converter = BetterFloatToStringConverter()
        self._float_point_2_none_converter = BetterFloatToStringConverter(pass_none=True)
        self._float_to_scaled_integer_converter = Converter.FloatToScaledIntegerConverter(100, -1.0, 1.0)
        self._float_to_string_converter = Converter.FloatToStringConverter(format="{:.2f}")
        self._contrast_integer_converter = ContrastIntegerConverter(100)
        self._contrast_string_converter = ContrastStringConverter()
        self._gamma_integer_converter = GammaIntegerConverter()
        self._gamma_string_converter = GammaStringConverter()

        # for test purposes
        self.display_limits_limit_low: typing.Optional[Declarative.UIWidget] = None
        self.display_limits_limit_high: typing.Optional[Declarative.UIWidget] = None

        u = Declarative.DeclarativeUI()

        self.ui_view = u.create_column(
            u.create_row(
                u.create_label(text=_("Date"), width=60),
                u.create_label(text="@binding(_model.info_datetime_model.value)", width=240),
                u.create_stretch()
            ),
            u.create_row(
                u.create_label(text=_("Data"), width=60),
                u.create_label(text="@binding(_model.size_and_data_format_model.value)", width=240),
                u.create_stretch()
            ),
            u.create_row(
                u.create_label(text=_("Data Range"), width=120),
                u.create_label(text="@binding(_model.data_range_low_model.value, converter=_float_point_2_converter)", fallback=_("N/A"), width=80),
                u.create_spacing(8),
                u.create_label(text="@binding(_model.data_range_high_model.value, converter=_float_point_2_converter)", fallback=_("N/A"), width=80),
                u.create_stretch()
            ),
            u.create_row(
                u.create_label(text=_("Display Limits"), width=120),
                u.create_line_edit(text="@binding(_model.display_limits_low_model.value, converter=_float_point_2_none_converter)", placeholder_text=_("Auto"), width=80, name="display_limits_limit_low"),
                u.create_spacing(8),
                u.create_line_edit(text="@binding(_model.display_limits_high_model.value, converter=_float_point_2_none_converter)", placeholder_text=_("Auto"), width=80, name="display_limits_limit_high"),
                u.create_stretch()
            ),
            u.create_row(
                u.create_label(text=_("Color Map"), width=120),
                # note: specify maximum width on color map combo box since it is constructed dynamically and may have long names
                u.create_combo_box(items=self._model.color_map_items, on_current_index_changed="_change_color_map", current_index="@binding(_model.current_colormap_index.value)", width=120),
                u.create_stretch()
            ),
            u.create_row(
                u.create_label(text=_("Brightness"), width=80),
                u.create_slider(value="@binding(_model.brightness_model.value, converter=_float_to_scaled_integer_converter)", minimum=0, maximum=100, width=124),
                u.create_line_edit(text="@binding(_model.brightness_model.value, converter=_float_to_string_converter)", width=60),
                u.create_stretch(),
                spacing=8
            ),
            u.create_row(
                u.create_label(text=_("Contrast"), width=80),
                u.create_slider(value="@binding(_model.contrast_model.value, converter=_contrast_integer_converter)", minimum=0, maximum=100, width=124),
                u.create_line_edit(text="@binding(_model.contrast_model.value, converter=_contrast_string_converter)", width=60),
                u.create_stretch(),
                spacing=8
            ),
            u.create_row(
                u.create_label(text=_("Adjustment"), width=120),
                u.create_combo_box(items=self._model.adjustment_options_items, on_current_index_changed="_change_adjustment_option", current_index="@binding(_model.current_adjustment_options_index.value)"),
                u.create_stretch(),
            ),
            u.create_row(
                u.create_label(text=_("Gamma"), width=80),
                u.create_slider(value="@binding(_model.gamma_model.value, converter=_gamma_integer_converter)", minimum=0, maximum=100, width=124),
                u.create_line_edit(text="@binding(_model.gamma_model.value, converter=_gamma_string_converter)", width=60),
                u.create_stretch(),
                spacing=8,
                visible="@binding(_model.show_gamma_controls.value)"
            ),
            spacing=4
        )

    def _change_color_map(self, widget: Declarative.UIWidget, current_index: int) -> None:
        self._model.change_color_map(widget, current_index)

    def _change_adjustment_option(self, widget: Declarative.UIWidget, current_index: int) -> None:
        self._model.change_adjustment_option(widget, current_index)


class ComplexDisplayTypeChooserHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController, display_data_channel: DisplayItem.DisplayDataChannel) -> None:
        super().__init__()
        self._document_controller = document_controller
        self._display_data_channel = display_data_channel
        self._display_type_items = (_("Log Absolute"), _("Absolute"), _("Phase"), _("Real"), _("Imaginary"))
        self._display_type_flags = ("log-absolute", "absolute", "phase", "real", "imaginary")
        self._display_type_reverse_map = {p: i for i, p in enumerate(self._display_type_flags)}
        self._current_index = self._display_type_reverse_map.get(display_data_channel.complex_display_type or str(), 0)

        u = Declarative.DeclarativeUI()

        self.ui_view = u.create_row(
            u.create_label(text=_("Complex Display"), width=120),
            u.create_combo_box(items=self._display_type_items, on_current_index_changed="change_display_type", current_index="@binding(_current_index)"),
            u.create_stretch()
        )

    def change_display_type(self, widget: Declarative.UIWidget, current_index: int) -> None:
        current_display_type = self._display_type_flags[current_index]
        if self._display_data_channel.complex_display_type != current_display_type:
            command = DisplayPanel.ChangeDisplayDataChannelCommand(self._document_controller.document_model,
                                                                   self._display_data_channel, complex_display_type=current_display_type)
            command.perform()
            self._document_controller.push_undo_command(command)


class ImageDataInspectorSection(InspectorSection):
    def __init__(self, document_controller: DocumentController.DocumentController, display_data_channel: DisplayItem.DisplayDataChannel, display_item: DisplayItem.DisplayItem) -> None:
        super().__init__(document_controller.ui, "image-data", _("Image Data"))
        ui = document_controller.ui

        self.widget_id = "image_data_inspector_section"

        self.image_data_inspector_handler = ImageDataInspectorHandler(document_controller, display_data_channel, display_item)
        image_data_inspector_widget = Declarative.DeclarativeWidget(document_controller.ui, document_controller.event_loop, self.image_data_inspector_handler)

        self.add_widget_to_content(image_data_inspector_widget)

        if display_data_channel.data_item and display_data_channel.data_item.is_data_complex_type:
            complex_display_widget = Declarative.DeclarativeWidget(document_controller.ui, document_controller.event_loop, ComplexDisplayTypeChooserHandler(document_controller, display_data_channel))
            self.add_widget_to_content(complex_display_widget)

        self.finish_widget_content()


class SessionInspectorModel(Observable.Observable):
    def __init__(self, document_controller: DocumentController.DocumentController, data_item: DataItem.DataItem) -> None:
        super().__init__()
        self.__document_controller = document_controller
        self.__data_item = data_item

        self.site_model = Model.PropertyModel[str](self.__data_item.session.get("site", str()))
        self.site_model.on_value_changed = functools.partial(self._update_metadata, "site")
        self.instrument_model = Model.PropertyModel[str](self.__data_item.session.get("instrument", str()))
        self.instrument_model.on_value_changed = functools.partial(self._update_metadata, "instrument")
        self.task_model = Model.PropertyModel[str](self.__data_item.session.get("task", str()))
        self.task_model.on_value_changed = functools.partial(self._update_metadata, "task")
        self.microscopist_model = Model.PropertyModel[str](self.__data_item.session.get("microscopist", str()))
        self.microscopist_model.on_value_changed = functools.partial(self._update_metadata, "microscopist")
        self.sample_model = Model.PropertyModel[str](self.__data_item.session.get("sample", str()))
        self.sample_model.on_value_changed = functools.partial(self._update_metadata, "sample")
        self.sample_area_model = Model.PropertyModel[str](self.__data_item.session.get("sample_area", str()))
        self.sample_area_model.on_value_changed = functools.partial(self._update_metadata, "sample_area")
        self.label_model = Model.PropertyModel[str](self.__data_item.session.get("label", str()))
        self.label_model.on_value_changed = functools.partial(self._update_metadata, "label")

        self.__property_changed_listener = data_item.property_changed_event.listen(ReferenceCounting.weak_partial(SessionInspectorModel.__fields_changed, self)) if data_item else None

    def _update_metadata(self, field_id: str, new_value: typing.Optional[str]) -> None:
        session_metadata = dict(self.__data_item.session_metadata)
        session_metadata[field_id] = new_value
        command = ChangePropertyCommand(self.__document_controller.document_model, self.__data_item, "session_metadata",
                                        session_metadata)
        command.perform()
        self.__document_controller.push_undo_command(command)

    def __fields_changed(self, key: str) -> None:
        if key == "session_metadata":
            self.site_model.value = self.__data_item.session.get("site", str())
            self.instrument_model.value = self.__data_item.session.get("instrument", str())
            self.task_model.value = self.__data_item.session.get("task", str())
            self.microscopist_model.value = self.__data_item.session.get("microscopist", str())
            self.sample_model.value = self.__data_item.session.get("sample", str())
            self.sample_area_model.value = self.__data_item.session.get("sample_area", str())
            self.label_model.value = self.__data_item.session.get("label", str())


class SessionInspectorHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController, data_item: DataItem.DataItem) -> None:
        super().__init__()
        self._session_model = SessionInspectorModel(document_controller, data_item)
        u = Declarative.DeclarativeUI()

        self.ui_view = u.create_column(
            u.create_row(
                u.create_label(text=_("Site"), width=100),
                u.create_line_edit(text="@binding(_session_model.site_model.value)", placeholder_text=_("Site Description"))
            ),
            u.create_spacing(4),
            u.create_row(
                u.create_label(text=_("Instrument"), width=100),
                u.create_line_edit(text="@binding(_session_model.instrument_model.value)", placeholder_text=_("Instrument Description"))
            ),
            u.create_spacing(4),
            u.create_row(
                u.create_label(text=_("Task"), width=100),
                u.create_line_edit(text="@binding(_session_model.task_model.value)", placeholder_text=_("Task Description"))
            ),
            u.create_spacing(4),
            u.create_row(
                u.create_label(text=_("Microscopist"), width=100),
                u.create_line_edit(text="@binding(_session_model.microscopist_model.value)", placeholder_text=_("Microscopist Name(s)"))
            ),
            u.create_spacing(4),
            u.create_row(
                u.create_label(text=_("Sample"), width=100),
                u.create_line_edit(text="@binding(_session_model.sample_model.value)", placeholder_text=_("Sample Description"))
            ),
            u.create_spacing(4),
            u.create_row(
                u.create_label(text=_("Sample Area"), width=100),
                u.create_line_edit(text="@binding(_session_model.sample_area_model.value)", placeholder_text=_("Sample Area Description"))
            ),
            u.create_spacing(4),
            u.create_row(
                u.create_label(text=_("Label"), width=100),
                u.create_line_edit(text="@binding(_session_model.label_model.value)", placeholder_text=_("Brief Label"))
            )
        )


class SessionInspectorSection(InspectorSection):
    def __init__(self, document_controller: DocumentController.DocumentController, data_item: DataItem.DataItem) -> None:
        super().__init__(document_controller.ui, "session", _("Session"))

        self._session_inspector_handler = SessionInspectorHandler(document_controller, data_item)
        widget = Declarative.DeclarativeWidget(document_controller.ui, document_controller.event_loop, self._session_inspector_handler)
        self.add_widget_to_content(widget)
        self.finish_widget_content()

    def close(self) -> None:
        self._session_inspector_handler.close()
        super().close()


class ChangeIntensityCalibrationCommand(Undo.UndoableCommand):
    def __init__(self, document_model: DocumentModel.DocumentModel, data_item: DataItem.DataItem, intensity_calibration: Calibration.Calibration) -> None:
        super().__init__(_("Change Intensity Calibration"), command_id="change_intensity_calibration", is_mergeable=True)
        self.__document_model = document_model
        self.__data_item_proxy = data_item.create_proxy()
        self.__new_intensity_calibration: typing.Optional[Calibration.Calibration] = intensity_calibration
        self.__old_intensity_calibration: typing.Optional[Calibration.Calibration] = data_item.intensity_calibration
        self.initialize()

    def close(self) -> None:
        self.__document_model = typing.cast(typing.Any, None)
        self.__data_item_proxy.close()
        self.__data_item_proxy = typing.cast(typing.Any, None)
        self.__new_intensity_calibration = typing.cast(typing.Any, None)
        self.__old_intensity_calibration = typing.cast(typing.Any, None)
        super().close()

    def _perform(self) -> None:
        data_item = self.__data_item_proxy.item
        if data_item and self.__new_intensity_calibration is not None:
            data_item.set_intensity_calibration(self.__new_intensity_calibration)

    def _get_modified_state(self) -> typing.Any:
        data_item = self.__data_item_proxy.item
        return data_item.modified_state if data_item else None, self.__document_model.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        data_item = self.__data_item_proxy.item
        if data_item:
            data_item.modified_state = modified_state[0]
        self.__document_model.modified_state = modified_state[1]

    def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return bool(state1[0] == state2[0])

    def _undo(self) -> None:
        data_item = self.__data_item_proxy.item
        assert data_item
        self.__new_intensity_calibration = data_item.intensity_calibration
        if self.__old_intensity_calibration is not None:
            data_item.set_intensity_calibration(self.__old_intensity_calibration)

    def _redo(self) -> None:
        self.perform()

    @property
    def __data_item_uuid(self) -> typing.Optional[uuid.UUID]:
        data_item = self.__data_item_proxy.item if self.__data_item_proxy else None
        return data_item.uuid if data_item else None

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, self.__class__) and bool(self.command_id) and self.command_id == command.command_id and self.__data_item_uuid == command.__data_item_uuid


class ChangeDimensionalCalibrationsCommand(Undo.UndoableCommand):
    def __init__(self, document_model: DocumentModel.DocumentModel, data_item: DataItem.DataItem, dimensional_calibrations: DataAndMetadata.CalibrationListType) -> None:
        super().__init__(_("Change Intensity Calibration"), command_id="change_intensity_calibration", is_mergeable=True)
        self.__document_model = document_model
        self.__data_item_proxy = data_item.create_proxy()
        self.__new_dimensional_calibrations = list(dimensional_calibrations)
        self.__old_dimensional_calibrations = list(data_item.dimensional_calibrations)
        self.initialize()

    def close(self) -> None:
        self.__document_model = typing.cast(typing.Any, None)
        self.__data_item_proxy.close()
        self.__data_item_proxy = typing.cast(typing.Any, None)
        super().close()

    def _perform(self) -> None:
        data_item = self.__data_item_proxy.item
        if data_item:
            data_item.set_dimensional_calibrations(self.__new_dimensional_calibrations)

    def _get_modified_state(self) -> typing.Any:
        data_item = self.__data_item_proxy.item
        return data_item.modified_state if data_item else None, self.__document_model.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        data_item = self.__data_item_proxy.item
        if data_item:
            data_item.modified_state = modified_state[0]
        self.__document_model.modified_state = modified_state[1]

    def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return bool(state1[0] == state2[0])

    def _undo(self) -> None:
        data_item = self.__data_item_proxy.item
        assert data_item
        self.__new_dimensional_calibrations = list(data_item.dimensional_calibrations)
        data_item.set_dimensional_calibrations(self.__old_dimensional_calibrations)

    def _redo(self) -> None:
        self.perform()

    @property
    def __data_item_uuid(self) -> typing.Optional[uuid.UUID]:
        data_item = self.__data_item_proxy.item if self.__data_item_proxy else None
        return data_item.uuid if data_item else None

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, self.__class__) and bool(self.command_id) and self.command_id == command.command_id and self.__data_item_uuid == command.__data_item_uuid


class BetterFloatToStringConverter(Converter.FloatToStringConverter):
    def __init__(self, *, pass_none: bool = False) -> None:
        super().__init__(pass_none=pass_none)
        self.__pass_none = pass_none

    def convert(self, value: typing.Optional[float]) -> typing.Optional[str]:
        if value is None:
            return None if self.__pass_none else str()
        if math.isfinite(value) and value != 0.0:
            mag = math.floor(math.log10(abs(value)))
            if mag < 0:
                return "{0:0.4g}".format(value)
            elif mag > 5:
                result = "{0:0.3e}".format(value)
                while not ".0e" in result:
                    last_result = result
                    result = result.replace("0e", "e")
                    if last_result == result:
                        break
                return result
            else:
                result = "{0:.4f}".format(value)
                while result.endswith("0") and not result.endswith(".0"):
                    result = result[:-1]
                return result
        result = "{0:f}".format(value)
        while result.endswith("0") and not result.endswith(".0"):
            result = result[:-1]
        return result


class CalibrationModel(Observable.Observable):
    def __init__(self, axis_name: str, calibration: Calibration.Calibration, setter_fn: typing.Callable[[Calibration.Calibration], None]) -> None:
        super().__init__()
        self.__axis_name = axis_name
        self.__calibration = calibration
        self.__converter = BetterFloatToStringConverter()
        self.__setter_fn = setter_fn

    @property
    def axis_name(self) -> str:
        return self.__axis_name

    @axis_name.setter
    def axis_name(self, value: str) -> None:
        if self.__axis_name != value:
            self.__axis_name = value
            self.notify_property_changed("axis_name")

    @property
    def offset(self) -> float:
        return self.__calibration.offset

    @offset.setter
    def offset(self, value: float) -> None:
        if self.__calibration.offset != value:
            self.__calibration.offset = value
            self.__setter_fn(self.__calibration)
            self.notify_property_changed("offset")
            self.notify_property_changed("offset_str")

    @property
    def offset_str(self) -> str:
        return self.__converter.convert(self.__calibration.offset) or "0.0"

    @offset_str.setter
    def offset_str(self, value: str) -> None:
        self.offset = self.__converter.convert_back(value) or 0.0

    @property
    def scale(self) -> float:
        return self.__calibration.scale

    @scale.setter
    def scale(self, value: float) -> None:
        if self.__calibration.scale != value:
            self.__calibration.scale = value
            self.__setter_fn(self.__calibration)
            self.notify_property_changed("scale")
            self.notify_property_changed("scale_str")

    @property
    def scale_str(self) -> str:
        return self.__converter.convert(self.__calibration.scale) or str()

    @scale_str.setter
    def scale_str(self, value: str) -> None:
        self.scale = self.__converter.convert_back(value) or 0.0

    @property
    def units(self) -> typing.Optional[str]:
        return self.__calibration.units

    @units.setter
    def units(self, value: typing.Optional[str]) -> None:
        if self.__calibration.units != value:
            self.__calibration.units = value if value else str()
            self.__setter_fn(self.__calibration)
            self.notify_property_changed("units")


class CalibrationHandler(Declarative.Handler):
    def __init__(self, calibration_model: CalibrationModel) -> None:
        super().__init__()
        self._calibration_model = calibration_model
        u = Declarative.DeclarativeUI()
        self.ui_view = u.create_row(
            u.create_label(text="@binding(_calibration_model.axis_name)", width=60),
            u.create_line_edit(text="@binding(_calibration_model.offset_str)", width=60),
            u.create_line_edit(text="@binding(_calibration_model.scale_str)", width=60),
            u.create_line_edit(text="@binding(_calibration_model.units)", width=60),
            u.create_stretch(),
            spacing=12
        )


class CalibrationStyleModelAdapter(typing.Protocol):
    def get_calibrations(self, display_calibration_info: DisplayItem.DisplayCalibrationInfo, calibration_style: DisplayItem.CalibrationStyle) -> typing.Sequence[Calibration.Calibration]: ...
    def get_calibration_style(self, display_calibration_info: DisplayItem.DisplayCalibrationInfo) -> DisplayItem.CalibrationStyle: ...
    def get_calibration_styles(self, display_calibration_info: DisplayItem.DisplayCalibrationInfo) -> typing.Sequence[DisplayItem.CalibrationStyle]: ...
    def get_calibration_style_id_property_name(self) -> str: ...


class DimensionalCalibrationStyleModelAdapter(CalibrationStyleModelAdapter):
    def get_calibrations(self, display_calibration_info: DisplayItem.DisplayCalibrationInfo, calibration_style: DisplayItem.CalibrationStyle) -> typing.Sequence[Calibration.Calibration]:
        return display_calibration_info.get_dimensional_calibrations_for_calibration_style(calibration_style)

    def get_calibration_style(self, display_calibration_info: DisplayItem.DisplayCalibrationInfo) -> DisplayItem.CalibrationStyle:
        return display_calibration_info.calibration_style

    def get_calibration_styles(self, display_calibration_info: DisplayItem.DisplayCalibrationInfo) -> typing.Sequence[DisplayItem.CalibrationStyle]:
        return display_calibration_info.calibration_styles

    def get_calibration_style_id_property_name(self) -> str:
        return "calibration_style_id"


class IntensityCalibrationStyleModelAdapter(CalibrationStyleModelAdapter):
    def get_calibrations(self, display_calibration_info: DisplayItem.DisplayCalibrationInfo, calibration_style: DisplayItem.CalibrationStyle) -> typing.Sequence[Calibration.Calibration]:
        return display_calibration_info.get_intensity_calibrations_for_calibration_style(calibration_style)

    def get_calibration_style(self, display_calibration_info: DisplayItem.DisplayCalibrationInfo) -> DisplayItem.CalibrationStyle:
        return display_calibration_info.intensity_calibration_style

    def get_calibration_styles(self, display_calibration_info: DisplayItem.DisplayCalibrationInfo) -> typing.Sequence[DisplayItem.CalibrationStyle]:
        return display_calibration_info.intensity_calibration_styles

    def get_calibration_style_id_property_name(self) -> str:
        return "intensity_calibration_style_id"


class CalibrationStyleModel(Observable.Observable):
    """A model represents the calibration styles available and chosen calibration style for a display item.

    The items property is a read-only sequence of strings representing the available calibration styles for the display item.

    The index property is a read/write integer and will update the display item to use the selected calibration style when set.

    The adapter is used to adapt this model to either dimensional or intensity calibrations.
    """
    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, adapter: CalibrationStyleModelAdapter) -> None:
        super().__init__()
        self.__document_controller = document_controller
        self.__display_item = display_item
        self.__adapter = adapter
        self.__last_display_calibration_info: DisplayItem.DisplayCalibrationInfo | None = None
        self.__index: int | None = None
        self.__items: tuple[str, ...] = tuple()
        self.__calibration_styles: tuple[DisplayItem.CalibrationStyle, ...] = tuple()
        display_info_stream = display_item.display_info_stream
        self.__display_info_stream_action = Stream.ValueStreamAction(display_info_stream, ReferenceCounting.weak_partial(self.__class__.__handle_display_info_changed, self))
        self.__handle_display_info_changed(display_info_stream.value)

    def __handle_display_info_changed(self, display_info: DisplayInfo.DisplayInfo | None) -> None:
        display_calibration_info = display_info.display_calibration_info if display_info else None
        if self.__last_display_calibration_info != display_calibration_info:
            calibration_style = self.__adapter.get_calibration_style(display_calibration_info) if display_calibration_info else None
            calibration_styles = self.__adapter.get_calibration_styles(display_calibration_info) if display_calibration_info else tuple()
            index = calibration_styles.index(calibration_style) if calibration_style in calibration_styles else None
            items = list[str]()
            for calibration_style_ in calibration_styles:
                calibration_style_label = calibration_style_.label
                if calibration_style_.is_calibrated:
                    calibrations = self.__adapter.get_calibrations(display_calibration_info, calibration_style_) if display_calibration_info else tuple()
                    units = [c.units or "-" for c in calibrations]
                    if units and all(unit == units[0] for unit in units):
                        calibration_style_label += " (" + units[0] + ")"
                    else:
                        calibration_style_label += " (" + "/".join(units) + ")"
                items.append(calibration_style_label)
            items_tuple = tuple(items)
            if items_tuple != self.__items:
                self.__items = items_tuple
                self.notify_property_changed("items")
            if index != self.__index:
                self.__index = index
                self.notify_property_changed("index")
            self.__calibration_styles = tuple(calibration_styles)
            self.__last_display_calibration_info = display_calibration_info

    @property
    def items(self) -> typing.Sequence[str]:
        return self.__items

    @property
    def index(self) -> int | None:
        return self.__index

    @index.setter
    def index(self, value: int | None) -> None:
        value = value or 0  # startup case
        if value != self.index:
            value = max(0, min(value, len(self.__calibration_styles) - 1))
            calibration_style_id = self.__calibration_styles[value].calibration_style_id
            command = ChangeDisplayItemPropertyCommand(self.__document_controller.document_model, self.__display_item, self.__adapter.get_calibration_style_id_property_name(), calibration_style_id)
            command.perform()
            self.__document_controller.push_undo_command(command)


class CalibrationSectionHandler(Declarative.Handler):
    def __init__(self, dimensional_calibrations_model: ListModel.ListModel[CalibrationModel], intensity_calibration_model: CalibrationModel, calibration_style_model: CalibrationStyleModel, intensity_calibration_style_model: CalibrationStyleModel) -> None:
        super().__init__()
        self._dimensional_calibrations_model = dimensional_calibrations_model
        self.__intensity_calibration_model = intensity_calibration_model
        self._calibration_style_model = calibration_style_model
        self._intensity_calibration_style_model = intensity_calibration_style_model
        u = Declarative.DeclarativeUI()
        self.ui_view = u.create_column(
            u.create_row(
                u.create_label(width=60),
                u.create_label(text=_("Offset"), width=60),
                u.create_label(text=_("Scale"), width=60),
                u.create_label(text=_("Units"), width=60),
                u.create_stretch(),
                spacing=12
            ),
            u.create_column(items=f"_dimensional_calibrations_model.items", item_component_id="calibration", spacing=4),
            u.create_row(u.create_label(text=_("Display"), width=60), u.create_combo_box(items_ref="@binding(_calibration_style_model.items)", current_index="@binding(_calibration_style_model.index)"), u.create_stretch()),
            u.create_component_instance(identifier="intensity_calibration"),
            u.create_row(u.create_label(text=_("Display"), width=60), u.create_combo_box(items_ref="@binding(_intensity_calibration_style_model.items)", current_index="@binding(_intensity_calibration_style_model.index)"), u.create_stretch()),
            spacing=4
        )

    def create_handler(self, component_id: str, container: typing.Optional[Symbolic.ComputationVariable] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if component_id == "calibration" and item:
            calibration_model = typing.cast(CalibrationModel, item)
            return CalibrationHandler(calibration_model)
        if component_id == "intensity_calibration":
            return CalibrationHandler(self.__intensity_calibration_model)
        return None


class CalibrationsInspectorSection(InspectorSection):
    def __init__(self, document_controller: DocumentController.DocumentController, display_data_channel: DisplayItem.DisplayDataChannel, display_item: DisplayItem.DisplayItem) -> None:
        super().__init__(document_controller.ui, "calibrations", _("Calibrations"))
        self.__document_controller = document_controller
        self.__display_data_channel = display_data_channel
        self.__event_loop = document_controller.event_loop
        self.__pending_call: typing.Optional[asyncio.Handle] = None

        # allow setup of the calibration models without updating data item
        self.__enabled_ref: list[bool] = [False]

        self.__calibration_style_model = CalibrationStyleModel(document_controller, display_item, DimensionalCalibrationStyleModelAdapter())
        self.__intensity_calibration_style_model = CalibrationStyleModel(document_controller, display_item, IntensityCalibrationStyleModelAdapter())

        data_item = display_data_channel.data_item
        assert data_item

        def change_intensity_calibration(enabled_ref: list[bool], intensity_calibration: Calibration.Calibration) -> None:
            if enabled_ref[0] and data_item:
                command = ChangeIntensityCalibrationCommand(document_controller.document_model, data_item, intensity_calibration)
                command.perform()
                document_controller.push_undo_command(command)

        self.__dimensional_calibrations_model = ListModel.ListModel[CalibrationModel]()
        self.__intensity_calibration_model = CalibrationModel(str(), Calibration.Calibration(), functools.partial(change_intensity_calibration, self.__enabled_ref))
        widget = Declarative.DeclarativeWidget(document_controller.ui, document_controller.event_loop, CalibrationSectionHandler(self.__dimensional_calibrations_model, self.__intensity_calibration_model, self.__calibration_style_model, self.__intensity_calibration_style_model))

        self.__data_item_changed_event_listener = data_item.data_item_changed_event.listen(ReferenceCounting.weak_partial(CalibrationsInspectorSection.__handle_data_item_changed, self)) if data_item else None

        self.__handle_data_item_changed()

        self.add_widget_to_content(widget)

    def __handle_data_item_changed(self) -> None:
        # handle threading specially for tests
        if threading.current_thread() != threading.main_thread():
            if self.__pending_call:
                self.__pending_call.cancel()
            self.__pending_call = self.__event_loop.call_soon_threadsafe(ReferenceCounting.weak_partial(CalibrationsInspectorSection.__build_calibration_list, self))
        else:
            self.__build_calibration_list()

    def __build_calibration_list(self) -> None:
        self.__enabled_ref[0] = False
        data_item = self.__display_data_channel.data_item
        dimensional_calibrations = (data_item.dimensional_calibrations if data_item else None) or list()
        while len(dimensional_calibrations) < len(self.__dimensional_calibrations_model.items):
            self.__dimensional_calibrations_model.remove_item(-1)
        while len(dimensional_calibrations) > len(self.__dimensional_calibrations_model.items):
            index = len(self.__dimensional_calibrations_model.items)

            # the models are updated using a tricky behavior. we update the latest data item, which is stored in
            # self.__data_item_ref list. use a list so the callback functions don't need a reference to self (which would
            # delay garbage collection).

            def change_dimensional_calibration(enabled_ref: list[bool], document_controller: DocumentController.DocumentController, index: int, dimensional_calibration: Calibration.Calibration) -> None:
                if enabled_ref[0] and data_item:
                    dimensional_calibrations = list(data_item.dimensional_calibrations)
                    dimensional_calibrations[index] = dimensional_calibration
                    command = ChangeDimensionalCalibrationsCommand(document_controller.document_model, data_item, dimensional_calibrations)
                    command.perform()
                    document_controller.push_undo_command(command)

            calibration_model = CalibrationModel(str(), Calibration.Calibration(), functools.partial(change_dimensional_calibration, self.__enabled_ref, self.__document_controller, index))
            self.__dimensional_calibrations_model.append_item(calibration_model)
        assert len(dimensional_calibrations) == len(self.__dimensional_calibrations_model.items)
        for index, (dimensional_calibration, calibration_model) in enumerate(zip(dimensional_calibrations, self.__dimensional_calibrations_model.items)):
            calibration_model.offset = dimensional_calibration.offset
            calibration_model.scale = dimensional_calibration.scale
            calibration_model.units = dimensional_calibration.units
            if len(self.__dimensional_calibrations_model.items) == 1:
                calibration_model.axis_name = _("Channel")
            elif len(self.__dimensional_calibrations_model.items) == 2:
                calibration_model.axis_name = (_("Y"), _("X"))[index]
            else:
                calibration_model.axis_name = str(index)
        intensity_calibration = (data_item.intensity_calibration if data_item else None) or Calibration.Calibration()
        self.__intensity_calibration_model.axis_name = _("Intensity")
        self.__intensity_calibration_model.offset = intensity_calibration.offset
        self.__intensity_calibration_model.scale = intensity_calibration.scale
        self.__intensity_calibration_model.units = intensity_calibration.units
        self.__enabled_ref[0] = True

    @property
    def _dimensional_calibrations_model(self) -> ListModel.ListModel[CalibrationModel]:
        return self.__dimensional_calibrations_model

    @property
    def _intensity_calibration_model(self) -> CalibrationModel:
        return self.__intensity_calibration_model


class ChangeDisplayTypeCommand(Undo.UndoableCommand):

    def __init__(self, document_model: DocumentModel.DocumentModel, display_item: DisplayItem.DisplayItem, display_type: typing.Optional[str]) -> None:
        super().__init__(_("Change Display Type"), command_id="change_display_type", is_mergeable=True)
        self.__document_model = document_model
        self.__display_item_proxy = display_item.create_proxy()
        self.__old_display_type = display_item.display_type
        self.__display_type = display_type
        self.initialize()

    def close(self) -> None:
        self.__document_model = typing.cast(typing.Any, None)
        self.__display_item_proxy.close()
        self.__display_item_proxy = typing.cast(typing.Any, None)
        self.__old_display_type = None
        super().close()

    def _perform(self) -> None:
        display_item = self.__display_item_proxy.item
        if display_item:
            display_item.display_type = self.__display_type

    def _get_modified_state(self) -> typing.Any:
        display_item = self.__display_item_proxy.item
        return display_item.modified_state if display_item else None, self.__document_model.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        display_item = self.__display_item_proxy.item
        if display_item:
            display_item.modified_state = modified_state[0]
        self.__document_model.modified_state = modified_state[1]

    def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return bool(state1[0] == state2[0])

    def _undo(self) -> None:
        display_item = self.__display_item_proxy.item
        if display_item:
            old_display_type = self.__old_display_type
            self.__old_display_type = display_item.display_type
            display_item.display_type = old_display_type

    @property
    def __display_item_uuid(self) -> typing.Optional[uuid.UUID]:
        display_item = self.__display_item_proxy.item
        return display_item.uuid if display_item else None

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, self.__class__) and bool(self.command_id) and self.command_id == command.command_id and self.__display_item_uuid == command.__display_item_uuid


class ScaleMarkerOptionsHandler(Declarative.Handler):
    def __init__(self, display_item: DisplayItem.DisplayItem, document_controller: DocumentController.DocumentController) -> None:
        super().__init__()
        self._scale_marker_location_items = (_("Bottom Left"), _("Bottom Right"))
        self._scale_marker_location_reverse_map = {"bottom-left": 0, "bottom-right": 1}
        self._scale_marker_location_flags = ("bottom-left", "bottom-right")
        if display_item.get_display_property("show_scale_info_text") is None:
            display_item.set_display_property("show_scale_info_text", True)

        self._show_info_text_model = DisplayItemDisplayPropertyCommandModel(
            document_controller,
            display_item,
            "show_scale_info_text"
        )
        self.notify_property_changed("show_scale_info_text")

        self._scale_marker_position_model = DisplayItemDisplayPropertyCommandModel(
            document_controller,
            display_item,
            "scale_marker_position"
        )

        self._current_index = self._scale_marker_location_reverse_map.get(self._scale_marker_position_model.value or "bottom-left", 0)

        self._scale_marker_text_color_model = DisplayItemDisplayPropertyCommandModel(
            document_controller,
            display_item,
            "scale_marker_text_color"
        )

        self._scale_marker_background_color_model = DisplayItemDisplayPropertyCommandModel(
            document_controller,
            display_item,
            "scale_marker_background_color"
        )

        u = Declarative.DeclarativeUI()

        self.ui_view = u.create_column(
            u.create_row(
                u.create_label(text=_("Scale Marker"), text_alignment_vertical="vcenter", text_alignment_horizontal="right", width=100),
                u.create_combo_box(
                    items=self._scale_marker_location_items,
                    on_current_index_changed="change_scale_marker_location",
                    current_index="@binding(_current_index)"
                ),
                u.create_stretch(),
                spacing=8
            ),
            u.create_row(
                u.create_label(text=_("Text Color"),text_alignment_vertical="vcenter", text_alignment_horizontal="right", width=100),
                u.create_line_edit(text="@binding(_scale_marker_text_color_model.value)", placeholder_text=_("Default"), width=100),
                {"type": "nionswift.color_chooser", "color": "@binding(_scale_marker_text_color_model.value)"},
                u.create_stretch(),
                spacing=8
            ),
            u.create_row(
                u.create_label(text=_("Background"),text_alignment_vertical="vcenter", text_alignment_horizontal="right", width=100),
                u.create_line_edit(text="@binding(_scale_marker_background_color_model.value)", placeholder_text=_("Default"), width=100),
                {"type": "nionswift.color_chooser", "color": "@binding(_scale_marker_background_color_model.value)"},
                u.create_stretch(),
                spacing=8
            )
        )

    def change_scale_marker_location(self, widget: Declarative.UIWidget, current_index: int) -> None:
        self._scale_marker_position_model.value = self._scale_marker_location_flags[current_index]


class DisplayTypeChooserHandler(Declarative.Handler):
    def __init__(self, display_item: DisplayItem.DisplayItem, document_controller: DocumentController.DocumentController) -> None:
        super().__init__()
        self._document_controller = document_controller
        self._display_item = display_item
        self._display_type_items = (_("Default"), _("Line Plot"), _("Image"))
        self._display_type_flags = (None, "line_plot", "image")
        self._display_type_reverse_map = {None: 0, "line_plot": 1, "image": 2}
        self._current_index = self._display_type_reverse_map[self._display_item.display_type]

        u = Declarative.DeclarativeUI()

        self.ui_view = u.create_row(
            u.create_label(text=_("Display Type"), text_alignment_vertical="vcenter", text_alignment_horizontal="right", width=100),
            u.create_combo_box(items=self._display_type_items, on_current_index_changed="change_display_type", current_index="@binding(_current_index)"),
            u.create_stretch(),
            spacing=8
        )

    def change_display_type(self,  widget: Declarative.UIWidget, current_index: int) -> None:
        current_display_type = self._display_type_flags[current_index]
        if self._display_item.display_type != current_display_type:
            command = ChangeDisplayTypeCommand(self._document_controller.document_model, self._display_item, display_type=current_display_type)
            command.perform()
            self._document_controller.push_undo_command(command)



class ContrastStringConverter(Converter.ConverterLike[float, str]):

    def convert(self, value: typing.Optional[float]) -> typing.Optional[str]:
        if value is not None:
            return f"{value:0.2f}" if value >= 1 else f"1 / {1 / value:0.2f}" if value > 0 else f"{0.0:0.2f}"
        return None

    def convert_back(self, value_str: typing.Optional[str]) -> typing.Optional[float]:
        if value_str is not None:
            value_str = ''.join(value_str.split())
            if value_str.startswith("1/"):
                value = Converter.FloatToStringConverter().convert_back(value_str[2:]) or 0.0
                return 1 / value
            else:
                return Converter.FloatToStringConverter().convert_back(value_str)
        return None


class ContrastIntegerConverter(Converter.ConverterLike[float, int]):
    def __init__(self, n: int) -> None:
        self.n = n

    def convert(self, value: typing.Optional[float]) -> typing.Optional[int]:
        if value is not None:
            return int(math.log10(value) * self.n // 2) + (self.n // 2) if value > 0 else self.n
        return None

    def convert_back(self, value_int: typing.Optional[int]) -> typing.Optional[float]:
        if value_int is not None:
            return math.pow(10, (value_int - self.n // 2) / (self.n // 2))
        return None


class GammaStringConverter(Converter.ConverterLike[float, str]):

    def convert(self, value: typing.Optional[float]) -> typing.Optional[str]:
        if value is not None:
            return f"{value:0.2f}" if value >= 1 else f"1 / {1 / value:0.3f}" if value > 0 else f"{0.0:0.2f}"
        return None

    def convert_back(self, value_str: typing.Optional[str]) -> typing.Optional[float]:
        if value_str is not None:
            value_str = ''.join(value_str.split())
            if value_str.startswith("1/"):
                value = Converter.FloatToStringConverter().convert_back(value_str[2:]) or 0.0
                return 1 / value
            else:
                return Converter.FloatToStringConverter().convert_back(value_str)
        return None


class GammaIntegerConverter(Converter.ConverterLike[float, int]):
    # gamma ranges from 1/N to N

    def convert(self, value: typing.Optional[float]) -> typing.Optional[int]:
        if value is not None:
            return 100 - int(math.log(value, 10) * 50 + 50) if value > 0 else 0
        return 0

    def convert_back(self, value_int: typing.Optional[int]) -> typing.Optional[float]:
        if value_int is not None:
            return math.pow(10, ((100 - value_int) - 50) / 50)
        return None


class ImageDisplayInspectorSection(InspectorSection):
    """Display type inspector."""

    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem) -> None:
        super().__init__(document_controller.ui, "display-limits", _("Image Display"))
        self.__image_display_handler = DisplayTypeChooserHandler(display_item, document_controller)

        widget = Declarative.DeclarativeWidget(document_controller.ui, document_controller.event_loop,
                                               self.__image_display_handler)

        self.add_widget_to_content(widget)

        if Feature.FeatureManager().is_feature_enabled("feature.scale_marker_customization"):
            scale_marker_widget = Declarative.DeclarativeWidget(document_controller.ui, document_controller.event_loop, ScaleMarkerOptionsHandler(display_item, document_controller))
            self.add_widget_to_content(scale_marker_widget)


class LegendPositionChooserHandler(Declarative.Handler):
    def __init__(self, display_item: DisplayItem.DisplayItem, document_controller: DocumentController.DocumentController) -> None:
        super().__init__()
        self._document_controller = document_controller
        self._display_item = display_item
        self._legend_position_items = (_("None"), _("Top Left"), _("Top Right"), _("Outer Left"), _("Outer Right"))
        self._legend_position_flags = (None, "top-left", "top-right", "outer-left", "outer-right")
        self._legend_position_reverse_map = {p: i for i, p in enumerate(self._legend_position_flags)}
        self._current_index = self._legend_position_reverse_map.get(display_item.get_display_property("legend_position", None), 0)

        u = Declarative.DeclarativeUI()

        self.ui_view = u.create_row(
            u.create_label(text=_("Legend Position"), width=120),
            u.create_combo_box(items=self._legend_position_items, on_current_index_changed="change_legend_position", current_index="@binding(_current_index)"),
            u.create_stretch()
        )

    def change_legend_position(self,  widget: Declarative.UIWidget, current_index: int) -> None:
        current_legend_position = self._legend_position_flags[current_index]
        old_legend_position = self._display_item.get_display_property("legend_position", None)
        if old_legend_position != current_legend_position:
            command = DisplayPanel.ChangeDisplayCommand(self._document_controller.document_model, self._display_item,
                                                        title=_("Legend Position"), command_id="change_legend_position",
                                                        is_mergeable=True, legend_position=current_legend_position)
            command.perform()
            self._document_controller.push_undo_command(command)


class LinePlotDisplaySectionHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem):
        super().__init__()

        self._y_min_model = DisplayItemDisplayPropertyCommandModel(document_controller, display_item, "y_min")
        self._y_max_model = DisplayItemDisplayPropertyCommandModel(document_controller, display_item, "y_max")
        self._left_channel_model = DisplayItemDisplayPropertyCommandModel(document_controller, display_item, "left_channel")
        self._right_channel_model = DisplayItemDisplayPropertyCommandModel(document_controller, display_item, "right_channel")
        self._y_style_model = DisplayItemDisplayPropertyCommandModel(document_controller, display_item, "y_style")

        self._float_to_string_converter = BetterFloatToStringConverter(pass_none=True)

        class LogCheckedToCheckStateConverter(Converter.ConverterLike[str, bool]):
            """ Convert between bool and checked/unchecked strings. """

            def convert(self, value: typing.Optional[str]) -> typing.Optional[bool]:
                """ Convert bool to checked or unchecked string """
                return value == "log"

            def convert_back(self, value: typing.Optional[bool]) -> typing.Optional[str]:
                """ Convert checked or unchecked string to bool """
                return "log" if value else "linear"

        self._log_checked_to_check_state_converter = LogCheckedToCheckStateConverter()

        u = Declarative.DeclarativeUI()

        self.ui_view = u.create_column(
            u.create_row(
                u.create_label(text=_("Display"), width=120),
                u.create_line_edit(text="@binding(_y_min_model.value, converter=_float_to_string_converter)", width=72, placeholder_text=_("Auto"), name="y_min_field"),
                u.create_spacing(8),
                u.create_line_edit(text="@binding(_y_max_model.value, converter=_float_to_string_converter)", width=72, placeholder_text=_("Auto"), name="y_max_field"),
                u.create_stretch()
            ),
            u.create_row(
                u.create_label(text=_("Channels"), width=120),
                u.create_line_edit(text="@binding(_left_channel_model.value, converter=_float_to_string_converter)", width=72, placeholder_text=_("Auto"), name="left_channel_field"),
                u.create_spacing(8),
                u.create_line_edit(text="@binding(_right_channel_model.value, converter=_float_to_string_converter)", width=72, placeholder_text=_("Auto"), name="right_channel_field"),
                u.create_stretch()
            ),
            u.create_row(
                u.create_check_box(text=_("Log Scale (Y)"), checked="@binding(_y_style_model.value, converter=_log_checked_to_check_state_converter)", name="log_scale_check_box"),
                u.create_stretch()
            )
        )


class LinePlotDisplayInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement display limits inspector.
    """

    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem) -> None:
        super().__init__(document_controller.ui, "line-plot", _("Line Plot Display"))

        self.widget_id = "line_plot_display_inspector_section"

        self._display_type_chooser = DisplayTypeChooserHandler(display_item, document_controller)
        display_type_chooser_widget = Declarative.DeclarativeWidget(document_controller.ui, document_controller.event_loop, self._display_type_chooser)

        self._line_plot_display_section_handler = LinePlotDisplaySectionHandler(document_controller, display_item)
        widget = Declarative.DeclarativeWidget(document_controller.ui, document_controller.event_loop, self._line_plot_display_section_handler)

        self._legend_position_chooser = LegendPositionChooserHandler(display_item, document_controller)
        legend_position_chooser_widget = Declarative.DeclarativeWidget(document_controller.ui, document_controller.event_loop, self._legend_position_chooser)

        self.add_widget_to_content(display_type_chooser_widget)
        self.add_widget_to_content(widget)
        self.add_widget_to_content(legend_position_chooser_widget)

        self.finish_widget_content()


class SequenceSectionHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController, display_data_channel: DisplayItem.DisplayDataChannel) -> None:
        super().__init__()

        data_item = display_data_channel.data_item
        assert data_item

        self.sequence_index_model = DisplayDataChannelPropertyCommandModel(document_controller, display_data_channel, "sequence_index", title=_("Change Sequence Index"), command_id="change_sequence_index")
        self.sequence_index_maximum = data_item.dimensional_shape[0] -1  if display_data_channel.data_item else 0

        u = Declarative.DeclarativeUI()

        self._int_to_string_converter = Converter.IntegerToStringConverter()

        self.ui_view = u.create_row(
            u.create_label(text="Index", width=60),
            u.create_spacing(8),
            u.create_slider(value="@binding(sequence_index_model.value)", maximum=self.sequence_index_maximum, width=144),
            u.create_spacing(8),
            u.create_line_edit(text="@binding(sequence_index_model.value, converter=_int_to_string_converter)", width=60),
            u.create_stretch()
        )


class SequenceInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement slice inspector.
    """

    def __init__(self, document_controller: DocumentController.DocumentController, display_data_channel: DisplayItem.DisplayDataChannel) -> None:
        super().__init__(document_controller.ui, "sequence", _("Sequence"))

        self._sequence_section_handler = SequenceSectionHandler(document_controller, display_data_channel)

        widget = Declarative.DeclarativeWidget(document_controller.ui, document_controller.event_loop,
                                               self._sequence_section_handler)
        self.add_widget_to_content(widget)


class CollectionIndexModel(Observable.Observable):
    def __init__(self, display_data_channel: DisplayItem.DisplayDataChannel, collection_index_model: Model.PropertyModel[typing.Tuple[int, ...]], index: int) -> None:
        super().__init__()

        data_item = display_data_channel.data_item

        assert data_item
        self.__display_data_channel = display_data_channel
        self.__data_item = data_item
        self.__index = index
        self.__collection_index_base = 1 if self.__data_item.is_sequence else 0
        self.__collection_index_model = collection_index_model
        self.__collection_index_model_listener = self.__collection_index_model.property_changed_event.listen(
            ReferenceCounting.weak_partial(CollectionIndexModel.__handle_collection_index_changed, self))
        self.__last_value = self.value

    def __handle_collection_index_changed(self, property_name: str) -> None:
        if property_name == "value":
            if self.value != self.__last_value:
                self.__last_value = self.value
                self.notify_property_changed("value")

    @property
    def display_data_channel(self) -> DisplayItem.DisplayDataChannel:
        return self.__display_data_channel

    @property
    def index_maximum(self) -> int:
        return self.__data_item.dimensional_shape[self.__collection_index_base + self.__index] - 1

    @property
    def index(self) -> int:
        return self.__index

    @property
    def value(self) -> int:
        tuple_value = self.__collection_index_model.value
        return tuple_value[self.__index] if tuple_value else 0

    @value.setter
    def value(self, value: int) -> None:
        tuple_value = self.__collection_index_model.value
        collection_index = list(tuple_value) if tuple_value else []
        collection_index[self.__index] = value
        self.__collection_index_model.value = tuple(collection_index)
        self.__last_value = self.value


class CollectionIndexHandler(Declarative.Handler):
    def __init__(self, collection_model: CollectionIndexModel) -> None:
        super().__init__()

        self._collection_model = collection_model
        self._int_to_string_converter = Converter.IntegerToStringConverter()

        u = Declarative.DeclarativeUI()
        self.ui_view = u.create_row(
                u.create_label(text="{}: {}".format(_("Index"), self._collection_model.index), width=60),
                u.create_spacing(8),
                u.create_line_edit(text="@binding(_collection_model.value, converter=_int_to_string_converter)", width=60),
                u.create_spacing(8),
                u.create_slider(value="@binding(_collection_model.value)", maximum=self._collection_model.index_maximum, width=144),
                u.create_stretch()
            )


class CollectionIndexSectionHandler(Declarative.Handler):
    def __init__(self, collections_models: typing.Sequence[CollectionIndexModel]) -> None:
        super().__init__()

        self._collection_index_models = collections_models
        u = Declarative.DeclarativeUI()

        self.ui_view = u.create_column(items=f"_collection_index_models", item_component_id="collection_index", spacing=4)

    def create_handler(self, component_id: str, container: typing.Optional[Symbolic.ComputationVariable] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        collection_index_model = typing.cast(CollectionIndexModel, item)
        return CollectionIndexHandler(collection_index_model)


class CollectionIndexInspectorSection(InspectorSection):
    def __init__(self, document_controller: DocumentController.DocumentController, display_data_channel: DisplayItem.DisplayDataChannel) -> None:
        super().__init__(document_controller.ui, "collection-index", _("Index"))
        self.__document_controller = document_controller
        self.__display_data_channel = display_data_channel
        self.__event_loop = document_controller.event_loop
        self.__pending_call: typing.Optional[asyncio.Handle] = None
        self.__enable_ref: list[bool] = [False]

        data_item = display_data_channel.data_item
        assert data_item

        self.__collection_index_models: list[CollectionIndexModel] = []

        self.__collection_index_model = DisplayDataChannelPropertyCommandModel(document_controller,
                                                                               display_data_channel, "collection_index",
                                                                               title=_("Change Collection Index"),
                                                                               command_id="change_collection_index")

        for index in range(data_item.collection_dimension_count):
            self.__collection_index_models.append(CollectionIndexModel(display_data_channel, self.__collection_index_model, index))

        widget = Declarative.DeclarativeWidget(document_controller.ui, document_controller.event_loop,
                                               CollectionIndexSectionHandler(self.__collection_index_models))
        self.__data_item_changed_event_listener = data_item.data_item_changed_event.listen(
            ReferenceCounting.weak_partial(CollectionIndexInspectorSection.__handle_data_item_changed,
                                           self)) if data_item else None
        self.__handle_data_item_changed()
        self.add_widget_to_content(widget)

    def __handle_data_item_changed(self) -> None:
        if threading.current_thread() != threading.main_thread():
            if self.__pending_call:
                self.__pending_call.cancel()

    def close(self) -> None:
        self.__collection_index_model.close()
        self.__collection_index_model = typing.cast(typing.Any, None)
        super().close()


class SliceSectionHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController, display_data_channel: DisplayItem.DisplayDataChannel):
        super().__init__()

        self.slice_center_model = DisplayDataChannelPropertyCommandModel(document_controller, display_data_channel, "slice_center", title=_("Change Slice"), command_id="change_slice_center")
        self.slice_width_model = DisplayDataChannelPropertyCommandModel(document_controller, display_data_channel, "slice_width", title=_("Change Slice"), command_id="change_slice_width")

        self.slice_center_maximum = display_data_channel.data_item.dimensional_shape[-1] - 1 if display_data_channel.data_item else 0
        self.slice_width_maximum = display_data_channel.data_item.dimensional_shape[-1] if display_data_channel.data_item else 0

        self._int_to_string_converter = Converter.IntegerToStringConverter()

        u = Declarative.DeclarativeUI()
        self.ui_view = u.create_column(
            u.create_row(
                u.create_label(text=_("Slice"), width=60),
                u.create_spacing(8),
                u.create_line_edit(width=60,
                                   text="@binding(slice_center_model.value, converter=_int_to_string_converter)"),
                u.create_spacing(8),
                u.create_slider(width=144, maximum=self.slice_center_maximum,
                                value="@binding(slice_center_model.value)"),
                u.create_stretch()
            ),
            u.create_row(
                u.create_label(text=_("Width"), width=60),
                u.create_spacing(8),
                u.create_line_edit(width=60,
                                   text="@binding(slice_width_model.value, converter=_int_to_string_converter)"),
                u.create_spacing(8),
                u.create_slider(width=144, minimum=1, maximum=self.slice_width_maximum,
                                value="@binding(slice_width_model.value)"),
                u.create_stretch()
            )
        )


class SliceInspectorSection(InspectorSection):
    def __init__(self, document_controller: DocumentController.DocumentController, display_data_channel: DisplayItem.DisplayDataChannel) -> None:
        super().__init__(document_controller.ui, "slice", _("Slice"))
        self.__document_controller = document_controller
        self.__display_data_channel = display_data_channel
        self.__event_loop = document_controller.event_loop
        self.__pending_call: typing.Optional[asyncio.Handle] = None
        self.__enable_ref: list[bool] = [False]

        data_item = display_data_channel.data_item
        assert data_item

        self._slice_section_handler = SliceSectionHandler(document_controller, display_data_channel)

        widget = Declarative.DeclarativeWidget(document_controller.ui, document_controller.event_loop, self._slice_section_handler)
        self.__data_item_changed_event_listener = data_item.data_item_changed_event.listen(ReferenceCounting.weak_partial(SliceInspectorSection.__handle_data_item_changed, self)) if data_item else None
        self.__handle_data_item_changed()
        self.add_widget_to_content(widget)

    def __handle_data_item_changed(self) -> None:
        if threading.current_thread() != threading.main_thread():
            if self.__pending_call:
                self.__pending_call.cancel()


class GraphicsInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement graphics inspector.
        """

    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, selected_only: bool = False) -> None:
        super().__init__(document_controller.ui, "graphics", _("Graphics"))
        self.widget_id = "graphics_inspector_section"
        self.__document_controller = document_controller
        self.__display_item = display_item
        graphics_model = ListModel.ObservedListModel[DisplayItem.DisplayLayer](self.__display_item, "selected_graphics" if selected_only else "graphics")
        self._handler = GraphicsInspector.GraphicsSectionHandler(self.__document_controller, self.__display_item, graphics_model)
        self.__widget = Declarative.DeclarativeWidget(self.__document_controller.ui, self.__document_controller.event_loop, self._handler)
        self.add_widget_to_content(self.__widget)


class ComputationInspectorSection(InspectorSection):
    """Displays a computation's inputs, parameters, and status.

    Shares its implementation with the computation editor dialog (see ComputationPanel.ComputationHandler)
    via ComputationInspectorHandler, so both UIs stay in sync with a single implementation.

    The inspector panel is narrow and does not scroll horizontally, so this section always uses the
    compact layout, regardless of the context passed by the caller.
    """

    def __init__(self, computation_inspector_context: ComputationInspector.ComputationInspectorContext, data_item: DataItem.DataItem) -> None:
        document_controller = computation_inspector_context.window
        super().__init__(document_controller.ui, "computation", _("Computation"))
        compact_inspector_context = ComputationInspector.ComputationInspectorContext(document_controller,
                                                                                     computation_inspector_context.reference_handler,
                                                                                     computation_inspector_context.do_references,
                                                                                     compact=True)
        document_model = document_controller.document_model
        computation = document_model.get_data_item_computation(data_item)
        if computation:
            self.__computation_inspector_handler: typing.Optional[ComputationInspector.ComputationInspectorHandler] = ComputationInspector.ComputationInspectorHandler(compact_inspector_context, computation)
            widget = Declarative.DeclarativeWidget(document_controller.ui, document_controller.event_loop, self.__computation_inspector_handler)
            self.add_widget_to_content(widget)
        else:
            self.__computation_inspector_handler = None
            none_label = self.ui.create_label_widget(_("None"))
            none_label.text_font = "italic"
            none_widget = self.ui.create_row_widget()
            none_widget.add(none_label)
            self.add_widget_to_content(none_widget)
        self.finish_widget_content()

    def close(self) -> None:
        self.__computation_inspector_handler = None
        super().close()


class RemoveDisplayDataChannelCommand(Undo.UndoableCommand):

    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, display_data_channel: DisplayItem.DisplayDataChannel) -> None:
        super().__init__(_("Remove Data Item"))
        self.__document_controller = document_controller
        self.__display_item_proxy = display_item.create_proxy()
        workspace_controller = self.__document_controller.workspace_controller
        self.__old_workspace_layout: typing.Optional[Persistence.PersistentDictType] = workspace_controller.deconstruct() if workspace_controller else None
        self.__new_workspace_layout: typing.Optional[Persistence.PersistentDictType] = None
        self.__display_data_channel_index = display_item.display_data_channels.index(display_data_channel)
        self.__old_display_properties = display_item.save_properties()
        self.__undelete_logs: typing.List[Changes.UndeleteLog] = list()
        self.initialize()

    def close(self) -> None:
        self.__document_controller = typing.cast(typing.Any, None)
        self.__display_item_proxy.close()
        self.__display_item_proxy = typing.cast(typing.Any, None)
        self.__old_workspace_layout = None
        self.__new_workspace_layout = None
        self.__old_display_properties = typing.cast(typing.Any, None)
        for undelete_log in self.__undelete_logs:
            undelete_log.close()
        self.__undelete_logs = typing.cast(typing.Any, None)
        super().close()

    def _perform(self) -> None:
        display_item = self.__display_item_proxy.item
        if display_item:
            display_data_channel = display_item.display_data_channels[self.__display_data_channel_index]
            self.__undelete_logs.append(display_item.remove_display_data_channel(display_data_channel, safe=True))

    def _get_modified_state(self) -> typing.Any:
        display_item = self.__display_item_proxy.item
        return display_item.modified_state if display_item else None, self.__document_controller.document_model.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        display_item = self.__display_item_proxy.item
        if display_item:
            display_item.modified_state = modified_state[0]
        self.__document_controller.document_model.modified_state = modified_state[1]

    def _undo(self) -> None:
        workspace_controller = self.__document_controller.workspace_controller
        assert workspace_controller
        self.__new_workspace_layout = workspace_controller.deconstruct()
        for undelete_log in reversed(self.__undelete_logs):
            self.__document_controller.document_model.undelete_all(undelete_log)
            undelete_log.close()
        self.__undelete_logs.clear()
        if self.__old_workspace_layout is not None:
            workspace_controller.reconstruct(self.__old_workspace_layout)
        display_item = self.__display_item_proxy.item
        if display_item:
            display_item.restore_properties(self.__old_display_properties)

    def _redo(self) -> None:
        self.perform()
        workspace_controller = self.__document_controller.workspace_controller
        if workspace_controller and self.__new_workspace_layout is not None:
            workspace_controller.reconstruct(self.__new_workspace_layout)


class DataItemLabelWidget(Widgets.CompositeWidgetBase):
    def __init__(self, ui: UserInterface.UserInterface, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, index: int) -> None:
        content_widget = ui.create_column_widget()
        super().__init__(content_widget)

        remove_icon = "\N{MULTIPLICATION X}" if sys.platform != "darwin" else "\N{BALLOT X}"
        remove_display_data_channel_button = Widgets.TextPushButtonWidget(ui, remove_icon)

        section_title_row = ui.create_row_widget()
        section_title_label_widget = ui.create_label_widget()
        section_title_label_widget.text_font = "bold"
        section_title_label_widget.text = "{} #{}".format(_("Data"), index)
        section_title_row.add_spacing(20)
        section_title_row.add(section_title_label_widget)
        section_title_row.add_stretch()
        section_title_row.add(remove_display_data_channel_button)
        section_title_row.add_spacing(20)

        content_widget.add(section_title_row)
        content_widget.add_spacing(4)

        display_data_channel = display_item.display_data_channels[index]

        def remove_display_data_channel() -> None:
            command = RemoveDisplayDataChannelCommand(document_controller, display_item, display_data_channel)
            command.perform()
            document_controller.push_undo_command(command)

        remove_display_data_channel_button.on_button_clicked = remove_display_data_channel


class DataItemGroupWidget(Widgets.CompositeWidgetBase):
    def __init__(self, ui: UserInterface.UserInterface, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, index: int) -> None:
        self.__content_widget = ui.create_column_widget()
        super().__init__(self.__content_widget)

        self.on_rebuild_display_data_channels: typing.Optional[typing.Callable[[], None]] = None

        self.__ui = ui
        self.__document_controller = document_controller
        self.__display_item = display_item
        self.__index = index

        self.__build()

        self.__display_item_item_inserted = None
        self.__display_item_item_removed = None

        def display_item_item_inserted(key: str, value: typing.Any, before_index: int) -> None:
            if key == "display_data_channels":
                if callable(self.on_rebuild_display_data_channels):
                    self.on_rebuild_display_data_channels()

        def display_item_item_removed(key: str, value: typing.Any, index: int) -> None:
            if key == "display_data_channels":
                if callable(self.on_rebuild_display_data_channels):
                    self.on_rebuild_display_data_channels()

        self.__display_item_item_inserted = self.__display_item.item_inserted_event.listen(display_item_item_inserted)
        self.__display_item_item_removed = self.__display_item.item_removed_event.listen(display_item_item_removed)

    def close(self) -> None:
        self.__detach_listeners()
        self.__document_controller = typing.cast(typing.Any, None)
        self.__display_item = typing.cast(typing.Any, None)
        self.__ui = typing.cast(typing.Any, None)
        super().close()

    def __detach_listeners(self) -> None:
        if self.__display_item_item_inserted:
            self.__display_item_item_inserted.close()
            self.__display_item_item_inserted = None
        if self.__display_item_item_removed:
            self.__display_item_item_removed.close()
            self.__display_item_item_removed = None

    def __build(self) -> None:
        if len(self.__display_item.display_data_channels) > 1:
            self.__content_widget.add(DataItemLabelWidget(self.__ui, self.__document_controller, self.__display_item, self.__index))
        display_data_channel = self.__display_item.display_data_channels[self.__index]
        data_item = display_data_channel.data_item
        if data_item:
            self.__content_widget.add(DataInfoInspectorSection(self.__document_controller, display_data_channel))
            self.__content_widget.add(CalibrationsInspectorSection(self.__document_controller, display_data_channel, self.__display_item))
            self.__content_widget.add(SessionInspectorSection(self.__document_controller, data_item))
            if display_data_channel.is_sequence:
                self.__content_widget.add(SequenceInspectorSection(self.__document_controller, display_data_channel))
            if display_data_channel.is_sliced:
                self.__content_widget.add(SliceInspectorSection(self.__document_controller, display_data_channel))
            elif display_data_channel.is_collection:
                self.__content_widget.add(CollectionIndexInspectorSection(self.__document_controller, display_data_channel))
            self.__content_widget.add(ComputationInspectorSection(ComputationInspector.ComputationInspectorContext(self.__document_controller), data_item))


class DisplayInspector(Widgets.CompositeWidgetBase):
    """A class to manage creation of a widget representing an inspector for a display item.

    A new data item inspector is created whenever the display item changes, but not when the content of the items
    within the display item mutate.
    """

    def __init__(self, ui: UserInterface.UserInterface, document_controller: DocumentController.DocumentController, display_item: typing.Optional[DisplayItem.DisplayItem]) -> None:
        self.__content_widget = ui.create_column_widget()
        super().__init__(self.__content_widget)

        self.ui = ui
        self.__unbinder = Unbinder()

        self.on_rebuild: typing.Optional[typing.Callable[[], None]] = None

        self.__content_widget.add_spacing(4)
        if display_item:
            title_row = self.ui.create_row_widget()
            title_label_widget = self.ui.create_label_widget()
            title_label_widget.text_font = "bold"
            title_label_widget.bind_text(Binding.PropertyBinding(display_item, "displayed_title"))
            title_row.add_spacing(20)
            title_row.add(title_label_widget)
            title_row.add_stretch()
            self.__content_widget.add(title_row)
            self.__content_widget.add_spacing(4)
            self.__unbinder.add([display_item], [title_label_widget.unbind_text])

        self.__focus_default = None
        inspector_sections: typing.List[UserInterface.Widget] = list()
        if display_item and display_item.graphic_selection.has_selection:
            inspector_sections.append(GraphicsInspectorSection(document_controller, display_item, selected_only=True))
            def focus_default() -> None:
                pass
            self.__focus_default = focus_default
        elif display_item and display_item.used_display_type == "line_plot":
            info_inspector_section = InfoInspectorSection(document_controller, display_item)
            inspector_sections.append(info_inspector_section)
            inspector_sections.append(LinePlotDisplayInspectorSection(document_controller, display_item))
            for index, display_data_channel in enumerate(display_item.display_data_channels):
                data_item_group_widget = DataItemGroupWidget(self.ui, document_controller, display_item, index)
                def rebuild() -> None:
                    if callable(self.on_rebuild):
                        self.on_rebuild()
                data_item_group_widget.on_rebuild_display_data_channels = rebuild
                inspector_sections.append(data_item_group_widget)
            line_plot_display_layers_inspector_section = LinePlotDisplayLayersInspectorSection(document_controller, display_item)
            inspector_sections.append(line_plot_display_layers_inspector_section)
            if len(display_item.graphics) > 0:
                inspector_sections.append(GraphicsInspectorSection(document_controller, display_item))
            def focus_default() -> None:
                if info_inspector_section.info_title_label is not None:
                    info_inspector_section.info_title_label.focused = True
                    info_inspector_section.info_title_label.request_refocus()
            self.__focus_default = focus_default
        elif display_item and display_item.used_display_type == "image":
            info_inspector_section = InfoInspectorSection(document_controller, display_item)
            inspector_sections.append(info_inspector_section)
            inspector_sections.append(ImageDisplayInspectorSection(document_controller, display_item))
            for display_data_channel in display_item.display_data_channels:
                data_item = display_data_channel.data_item
                if data_item:
                    inspector_sections.append(ImageDataInspectorSection(document_controller, display_data_channel, display_item))
                    inspector_sections.append(CalibrationsInspectorSection(document_controller, display_data_channel, display_item))
                    inspector_sections.append(SessionInspectorSection(document_controller, data_item))
                    if display_data_channel.is_sequence:
                        inspector_sections.append(SequenceInspectorSection(document_controller, display_data_channel))
                    if display_data_channel.is_sliced:
                        inspector_sections.append(SliceInspectorSection(document_controller, display_data_channel))
                    elif display_data_channel.is_collection:
                        inspector_sections.append(CollectionIndexInspectorSection(document_controller, display_data_channel))
                    inspector_sections.append(ComputationInspectorSection(ComputationInspector.ComputationInspectorContext(document_controller), data_item))
            if len(display_item.graphics) > 0:
                inspector_sections.append(GraphicsInspectorSection(document_controller, display_item))
            def focus_default() -> None:
                if info_inspector_section.info_title_label is not None:
                    info_inspector_section.info_title_label.focused = True
                    info_inspector_section.info_title_label.request_refocus()
            self.__focus_default = focus_default
        elif display_item:
            info_inspector_section = InfoInspectorSection(document_controller, display_item)
            inspector_sections.append(info_inspector_section)
            for display_data_channel in display_item.display_data_channels:
                data_item = display_data_channel.data_item
                inspector_sections.append(DataInfoInspectorSection(document_controller, display_data_channel))
                if data_item:
                    inspector_sections.append(SessionInspectorSection(document_controller, data_item))
            def focus_default() -> None:
                if info_inspector_section.info_title_label is not None:
                    info_inspector_section.info_title_label.focused = True
                    info_inspector_section.info_title_label.request_refocus()
            self.__focus_default = focus_default

        for inspector_section in inspector_sections:
            self.__content_widget.add(inspector_section)

        self.__content_widget.add_stretch()

    def close(self) -> None:
        self.__unbinder.close()
        self.__unbinder = typing.cast(typing.Any, None)
        super().close()

    def _get_inspectors(self) -> typing.Sequence[InspectorSection]:
        """ Return a copy of the list of inspectors. """
        return typing.cast(typing.Sequence[InspectorSection], copy.copy(self.__content_widget.children[:-1]))

    def focus_default(self) -> None:
        if self.__focus_default:
            self.__focus_default()


class DeclarativeImageChooserConstructor:

    def __init__(self, app: Application.Application) -> None:
        self.__app = app

    def construct(self, d_type: str, ui: UserInterface.UserInterface, window: typing.Optional[Window.Window], d: Declarative.UIDescription, handler: Declarative.HandlerLike, finishes: typing.List[typing.Callable[[], None]]) -> typing.Optional[UserInterface.Widget]:
        if d_type == "image_chooser":
            properties = Declarative.construct_sizing_properties(d)
            thumbnail_source = DataItemThumbnailWidget.DataItemThumbnailSource(ui, window=window)

            def drop_mime_data(mime_data: UserInterface.MimeData, x: int, y: int) -> str:
                document_model = self.__app.document_model
                display_item = MimeTypes.mime_data_get_display_item(mime_data, document_model)
                if display_item:
                    thumbnail_source.display_item = display_item
                    if display_item:
                        return "copy"
                return "ignore"

            def data_item_delete() -> None:
                thumbnail_source.display_item = None

            widget = DataItemThumbnailWidget.ThumbnailWidget(ui, thumbnail_source, properties=properties)
            widget.on_drag = widget.drag
            widget.on_drop_mime_data = drop_mime_data
            widget.on_delete = data_item_delete

            if handler:
                Declarative.connect_name(widget, d, handler)
                Declarative.connect_reference_value(thumbnail_source, d, handler, "display_item", finishes)
                Declarative.connect_attributes(widget, d, handler, finishes)

            return widget

        return None


class CroppedOverlayGraphicCanvasItemComposer(CanvasItem.BaseComposer):
    def __init__(self, canvas_item: CanvasItem.AbstractCanvasItem, layout_sizing: CanvasItem.Sizing, cache: CanvasItem.ComposerCache, is_crop_enabled: bool) -> None:
        super().__init__(canvas_item, layout_sizing, cache)
        self.__crop_enabled = is_crop_enabled

    def _repaint(self, drawing_context: DrawingContext.DrawingContext, canvas_bounds: Geometry.IntRect, composer_cache: CanvasItem.ComposerCache) -> None:
        is_crop_enabled = self.__crop_enabled
        with drawing_context.saver():
            drawing_context.translate(canvas_bounds.left, canvas_bounds.top)
            drawing_context.rect(canvas_bounds.left, canvas_bounds.top, canvas_bounds.width, canvas_bounds.height)
            drawing_context.line_join = "miter"
            drawing_context.fill_style = "gray"
            drawing_context.fill()
            drawing_context.stroke_style = "white"
            drawing_context.line_width = 1.2
            drawing_context.stroke()
            if is_crop_enabled:
                drawing_context.rect(canvas_bounds.center.x - 1, canvas_bounds.center.y - 1, canvas_bounds.width / 2, canvas_bounds.height / 2)
                drawing_context.line_width = 1.2
                drawing_context.stroke_style = "white"
                drawing_context.stroke()


class CroppedOverlayGraphicCanvasItem(CanvasItem.AbstractCanvasItem):
    def __init__(self, handle_clicked: typing.Callable[[], None]) -> None:
        super().__init__()
        self.wants_mouse_events = True
        self.update_sizing(self.sizing.with_fixed_size(Geometry.IntSize(11, 11)))
        self.__is_croppable = False
        self.__crop_enabled = False
        self.__handle_clicked = handle_clicked
        self.__update_tool_tip()

    @property
    def is_croppable(self) -> bool:
        return self.__is_croppable

    @is_croppable.setter
    def is_croppable(self, value: bool) -> None:
        self.__is_croppable = value
        self.__update_tool_tip()

    def set_crop_enabled(self, crop_enabled: bool) -> None:
        self.__crop_enabled = crop_enabled
        self.update()
        self.__update_tool_tip()

    def __update_tool_tip(self) -> None:
        if self.is_croppable:
            if self.__crop_enabled:
                self.tool_tip = _("Cropped. Click to remove or assign selected rectangle as crop.")
            else:
                self.tool_tip = _("Uncropped. Click to auto create or assign selected rectangle as crop.")
        else:
            self.tool_tip = str()

    def mouse_clicked(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        self.__handle_clicked()
        return False

    def _get_composer(self, composer_cache: CanvasItem.ComposerCache) -> typing.Optional[CanvasItem.BaseComposer]:
        return CroppedOverlayGraphicCanvasItemComposer(self, self.sizing, composer_cache, self.__crop_enabled)


class CroppedOverlayCanvasItem(CanvasItem.CanvasItemComposition):
    def __init__(self) -> None:
        super().__init__()
        self.__crop_enabled = False

        self.on_crop_enabled_clicked: typing.Optional[typing.Callable[[], None]] = None

        def get_crop_enabled() -> bool:
            return self.__crop_enabled

        def set_crop_enabled(value: bool) -> None:
            if value != self.__crop_enabled:
                self.__crop_enabled = value
                self.__graphic_canvas_item.set_crop_enabled(value)

        self.__crop_enabled_binding_helper = UserInterface.BindablePropertyHelper[bool](get_crop_enabled, set_crop_enabled)

        def handle_clicked() -> None:
            if callable(self.on_crop_enabled_clicked):
                self.on_crop_enabled_clicked()

        self.__graphic_canvas_item = CroppedOverlayGraphicCanvasItem(handle_clicked)

        self.layout = CanvasItem.CanvasItemRowLayout()
        composition = CanvasItem.CanvasItemComposition()
        composition.layout = CanvasItem.CanvasItemColumnLayout()
        composition.add_stretch()
        composition.add_canvas_item(self.__graphic_canvas_item)
        composition.add_spacing(4)
        self.add_stretch()
        self.add_canvas_item(composition)
        self.add_spacing(4)

    @property
    def is_croppable(self) -> bool:
        return self.__graphic_canvas_item.is_croppable

    @is_croppable.setter
    def is_croppable(self, value: bool) -> None:
        self.__graphic_canvas_item.is_croppable = value

    @property
    def crop_enabled(self) -> bool:
        return self.__crop_enabled_binding_helper.value

    @crop_enabled.setter
    def crop_enabled(self, value: bool) -> None:
        self.__crop_enabled_binding_helper.value = value

    def bind_crop_enabled(self, binding: Binding.Binding) -> None:
        self.__crop_enabled_binding_helper.bind_value(binding)

    def unbind_crop_enabled(self) -> None:
        self.__crop_enabled_binding_helper.unbind_value()


class DeclarativeDataSourceChooserConstructor:

    def __init__(self, app: Application.Application) -> None:
        self.__app = app

    def construct(self, d_type: str, ui: UserInterface.UserInterface, window: typing.Optional[Window.Window], d: Declarative.UIDescription, handler: Declarative.HandlerLike, finishes: typing.List[typing.Callable[[], None]]) -> typing.Optional[UserInterface.Widget]:
        if d_type == "data_source_chooser":
            properties = Declarative.construct_sizing_properties(d)
            cropped_overlay = CroppedOverlayCanvasItem()
            thumbnail_source = DataItemThumbnailWidget.DataItemThumbnailSource(ui, window=window, overlay_canvas_items=[cropped_overlay])

            def drop_mime_data(mime_data: UserInterface.MimeData, x: int, y: int) -> str:
                on_drop_mime_data_method = typing.cast(typing.Optional[str], d.get("on_drop_mime_data"))
                if on_drop_mime_data_method and callable(getattr(handler, on_drop_mime_data_method, None)):
                    return typing.cast(str, getattr(handler, on_drop_mime_data_method)(mime_data, x, y))
                return "ignore"

            def data_item_delete() -> None:
                on_delete_method = typing.cast(typing.Optional[str], d.get("on_delete"))
                if on_delete_method and callable(getattr(handler, on_delete_method, None)):
                    getattr(handler, on_delete_method)()

            widget = DataItemThumbnailWidget.ThumbnailWidget(ui, thumbnail_source, properties=properties)
            widget.on_drag = widget.drag
            widget.on_drop_mime_data = drop_mime_data
            widget.on_delete = data_item_delete

            if handler:
                Declarative.connect_name(widget, d, handler)
                Declarative.connect_reference_value(thumbnail_source, d, handler, "display_item", finishes)
                Declarative.connect_reference_value(cropped_overlay, d, handler, "is_croppable", finishes, value_type=bool)
                Declarative.connect_reference_value(cropped_overlay, d, handler, "crop_enabled", finishes, value_type=bool)
                Declarative.connect_event(widget, cropped_overlay, d, handler, "on_crop_enabled_clicked", [])
                Declarative.connect_attributes(widget, d, handler, finishes)

            return widget

        return None


class DeclarativeTextPushButtonWidgetConstructor:
    def __init__(self, app: Application.Application) -> None:
        self.__app = app

    def construct(self, d_type: str, ui: UserInterface.UserInterface, window: typing.Optional[Window.Window], d: Declarative.UIDescription, handler: Declarative.HandlerLike, finishes: typing.List[typing.Callable[[], None]]) -> typing.Optional[UserInterface.Widget]:
        if d_type == "nionswift.text_push_button":
            text = d.get("text", "")
            widget = Widgets.TextPushButtonWidget(ui, text)

            if handler:
                Declarative.connect_name(widget, d, handler)
                Declarative.connect_reference_value(widget, d, handler, "on_button_clicked", finishes)
                Declarative.connect_event(widget, widget, d, handler, "on_clicked", [])
                Declarative.connect_attributes(widget, d, handler, finishes)

            return widget

        return None


class DeclarativeColorChooserConstructor:
    def __init__(self, app: Application.Application) -> None:
        self.__app = app

    def construct(self, d_type: str, ui: UserInterface.UserInterface, window: typing.Optional[Window.Window], d: Declarative.UIDescription, handler: Declarative.HandlerLike, finishes: typing.List[typing.Callable[[], None]]) -> typing.Optional[UserInterface.Widget]:
        if d_type == "nionswift.color_chooser":
            widget = Widgets.ColorPushButtonWidget(ui)

            if handler:
                Declarative.connect_name(widget, d, handler)
                Declarative.connect_reference_value(widget, d, handler, "color", finishes)
                Declarative.connect_reference_value(widget, d, handler, "on_color_changed", finishes)
                Declarative.connect_attributes(widget, d, handler, finishes)

            return widget

        return None


Feature.FeatureManager().add_feature(Feature.Feature("feature.scale_marker_customization", "Scale marker customization (position, color, background).", False))


# Temporary backward compatibility aliases.
#
# The computation inspector UI moved to ComputationInspector. These are the two names that existing
# plugins use, so they remain importable from this module to keep those plugins working against this
# release. They are temporary and are to be removed once those plugins have been updated to import
# from ComputationInspector. New code must use ComputationInspector directly.
VariableHandlerComponentFactory = ComputationInspector.VariableHandlerComponentFactory
VariableValueModel = ComputationInspector.VariableValueModel
