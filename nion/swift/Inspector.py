from __future__ import annotations

# standard libraries
import asyncio
import collections
import copy
import functools
import gettext
import math
import operator
import sys
import threading
import typing
import uuid
import weakref

# third party libraries
# None

# local libraries
from nion.data import Calibration
from nion.swift import DataItemThumbnailWidget
from nion.swift import DisplayPanel
from nion.swift import EntityBrowser
from nion.swift import MimeTypes
from nion.swift import Panel
from nion.swift import Undo
from nion.swift.model import Changes
from nion.swift.model import ColorMaps
from nion.swift.model import DataItem
from nion.swift.model import DataStructure
from nion.swift.model import DisplayItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import Schema
from nion.swift.model import Symbolic
from nion.ui import CanvasItem
from nion.ui import Declarative
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
        super().__init__(Widgets.SectionWidget(ui, section_title, self.__section_content_column, "inspector/" + section_id + "/open"))
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

    def perform(self) -> None:
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

    def perform(self) -> None:
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


class ChangeDisplayItemPropertyBinding(Binding.PropertyBinding):
    def __init__(self, document_controller: DocumentController.DocumentController,
                 display_item: DisplayItem.DisplayItem, property_name: str,
                 converter: typing.Optional[Converter.ConverterLike[typing.Any, typing.Any]] = None,
                 fallback: typing.Any = None) -> None:
        super().__init__(display_item, property_name, converter=converter, fallback=fallback)
        self.__document_controller = document_controller
        self.__display_item = display_item
        self.__property_name = property_name
        self.__old_source_setter = self.source_setter
        self.source_setter = ReferenceCounting.weak_partial(ChangeDisplayItemPropertyBinding.__set_value, self)

    def __set_value(self, value: typing.Any) -> None:
        if value != getattr(self.__display_item, self.__property_name):
            command = ChangeDisplayItemPropertyCommand(self.__document_controller.document_model, typing.cast(DisplayItem.DisplayItem, self.source), self.__property_name, value)
            command.perform()
            self.__document_controller.push_undo_command(command)


class ChangeDisplayPropertyBinding(Binding.Binding):
    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, property_name: str, converter: typing.Optional[Converter.ConverterLike[typing.Any, typing.Any]] = None, fallback: typing.Any = None) -> None:
        super().__init__(display_item, converter=converter, fallback=fallback)

        self.__display_item = display_item
        self.__property_name = property_name

        def get_value() -> typing.Any:
            return display_item.get_display_property(property_name)

        def set_value(value: typing.Any) -> typing.Any:
            if value != get_value():
                command = DisplayPanel.ChangeDisplayCommand(document_controller.document_model, display_item, title=_("Change Display"), command_id="change_display_" + property_name, is_mergeable=True, **{property_name: value})
                command.perform()
                document_controller.push_undo_command(command)

        self.source_getter = get_value
        self.source_setter = set_value

        self.__property_changed_listener = display_item.display_property_changed_event.listen(ReferenceCounting.weak_partial(ChangeDisplayPropertyBinding.__property_changed, self))

    # thread safe
    def __property_changed(self, property_name_: str) -> None:
        assert not self._closed
        if property_name_ == self.__property_name:
            value = self.__display_item.get_display_property(self.__property_name)
            if value is not None:
                self.update_target(value)
            else:
                self.update_target_direct(self.fallback)


class ChangeDisplayDataChannelPropertyBinding(Binding.PropertyBinding):
    def __init__(self, document_controller: DocumentController.DocumentController,
                 display_data_channel: DisplayItem.DisplayDataChannel, property_name: str,
                 converter: typing.Optional[Converter.ConverterLike[typing.Any, typing.Any]] = None,
                 fallback: typing.Any = None) -> None:
        super().__init__(display_data_channel, property_name, converter=converter, fallback=fallback)
        self.__property_name = property_name
        self.__old_source_setter = self.source_setter

        def set_value(value: typing.Any) -> typing.Any:
            if value != getattr(display_data_channel, property_name):
                command = DisplayPanel.ChangeDisplayDataChannelCommand(document_controller.document_model, display_data_channel, title=_("Change Display"), command_id="change_display_" + property_name, is_mergeable=True, **{property_name: value})
                command.perform()
                document_controller.push_undo_command(command)

        self.source_setter = set_value


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


class DisplayDataChannelPropertyCommandModel(Model.PropertyModel[typing.Any]):

    def __init__(self, document_controller: DocumentController.DocumentController,
                 display_data_channel: DisplayItem.DisplayDataChannel, property_name: str, title: str,
                 command_id: str) -> None:
        super().__init__(getattr(display_data_channel, property_name))
        self.__property_name = property_name
        self.__display_data_channel = display_data_channel

        def property_changed_from_user(value: typing.Any) -> None:
            if value != getattr(display_data_channel, property_name):
                command = DisplayPanel.ChangeDisplayDataChannelCommand(document_controller.document_model, display_data_channel, title=title, command_id=command_id, is_mergeable=True, **{property_name: value})
                command.perform()
                document_controller.push_undo_command(command)

        self.on_value_changed = property_changed_from_user

        self.__changed_listener = display_data_channel.property_changed_event.listen(ReferenceCounting.weak_partial(DisplayDataChannelPropertyCommandModel.__property_changed_from_display, self))

    def __property_changed_from_display(self, name: str) -> None:
        if name == self.__property_name:
            self.value = getattr(self.__display_data_channel, self.__property_name)


class GraphicPropertyCommandModel(Model.PropertyModel[typing.Any]):

    def __init__(self, document_controller: DocumentController.DocumentController,
                 display_item: DisplayItem.DisplayItem, graphic: Graphics.Graphic, property_name: str, title: str,
                 command_id: str) -> None:
        super().__init__(getattr(graphic, property_name))
        self.__property_name = property_name
        self.__graphic = graphic

        def property_changed_from_user(value: typing.Any) -> None:
            if value != getattr(graphic, property_name):
                command = DisplayPanel.ChangeGraphicsCommand(document_controller.document_model, display_item, [graphic], title=title, command_id=command_id, is_mergeable=True, **{property_name: value})
                command.perform()
                document_controller.push_undo_command(command)

        self.on_value_changed = property_changed_from_user

        self.__changed_listener = graphic.property_changed_event.listen(ReferenceCounting.weak_partial(GraphicPropertyCommandModel.__property_changed_from_graphic, self))

    def __property_changed_from_graphic(self, name: str) -> None:
        if name == self.__property_name:
            self.value = getattr(self.__graphic, self.__property_name)


class InfoInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement info inspector.
    """

    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem) -> None:
        super().__init__(document_controller.ui, "info", _("Info"))
        ui = document_controller.ui
        self.widget_id = "info_inspector_section"
        # title
        TOOL_TIP_STR = _("Use empty field for automatic title.")
        self.info_section_title_row = self.ui.create_row_widget()
        title_label_widget = self.ui.create_label_widget(_("Title"), properties={"width": 60})
        title_label_widget.tool_tip = TOOL_TIP_STR
        self.info_section_title_row.add(title_label_widget)
        self.info_title_label = self.ui.create_line_edit_widget()
        self.info_title_label.bind_text(ChangeDisplayItemPropertyBinding(document_controller, display_item, "title"))
        self.info_title_label.bind_placeholder_text(Binding.PropertyBinding(display_item, "placeholder_title"))
        self.info_title_label.tool_tip = TOOL_TIP_STR
        self.info_section_title_row.add(self.info_title_label)
        self.info_section_title_row.add_spacing(8)
        # caption
        self.caption_row = self.ui.create_row_widget()

        self.caption_label_column = self.ui.create_column_widget()
        self.caption_label_column.add(self.ui.create_label_widget(_("Caption"), properties={"width": 60}))
        self.caption_label_column.add_stretch()

        self.caption_edit_stack = self.ui.create_stack_widget()

        self.caption_static_column = self.ui.create_column_widget()
        self.caption_static_text = self.ui.create_text_edit_widget(properties={"height": 60})
        self.caption_static_text.editable = False
        caption_binding = Binding.PropertyBinding(display_item, "caption")
        caption_binding.source_setter = None
        self.caption_static_text.bind_text(caption_binding)
        self.caption_static_button_row = self.ui.create_row_widget()
        self.caption_static_edit_button = self.ui.create_push_button_widget(_("Edit"))
        def begin_caption_edit() -> None:
            self.caption_editable_text.text = display_item.caption
            self.caption_static_text.unbind_text()
            self.caption_edit_stack.current_index = 1
        self.caption_static_edit_button.on_clicked = begin_caption_edit
        self.caption_static_button_row.add(self.caption_static_edit_button)
        self.caption_static_button_row.add_stretch()
        self.caption_static_column.add(self.caption_static_text)
        self.caption_static_column.add(self.caption_static_button_row)
        self.caption_static_column.add_stretch()

        self.caption_editable_column = self.ui.create_column_widget()
        self.caption_editable_text = self.ui.create_text_edit_widget(properties={"height": 60})
        self.caption_editable_button_row = self.ui.create_row_widget()
        self.caption_editable_save_button = self.ui.create_push_button_widget(_("Save"))
        self.caption_editable_cancel_button = self.ui.create_push_button_widget(_("Cancel"))
        def end_caption_edit() -> None:
            caption_binding = Binding.PropertyBinding(display_item, "caption")
            caption_binding.source_setter = None
            self.caption_static_text.bind_text(caption_binding)
            self.caption_edit_stack.current_index = 0
        def save_caption_edit() -> None:
            command = ChangeDisplayItemPropertyCommand(document_controller.document_model, display_item, "caption", self.caption_editable_text.text)
            command.perform()
            document_controller.push_undo_command(command)
            end_caption_edit()
        self.caption_editable_button_row.add(self.caption_editable_save_button)
        self.caption_editable_button_row.add(self.caption_editable_cancel_button)
        self.caption_editable_button_row.add_stretch()
        self.caption_editable_save_button.on_clicked = save_caption_edit
        self.caption_editable_cancel_button.on_clicked = end_caption_edit
        self.caption_editable_column.add(self.caption_editable_text)
        self.caption_editable_column.add(self.caption_editable_button_row)
        self.caption_editable_column.add_stretch()

        self.caption_edit_stack.add(self.caption_static_column)
        self.caption_edit_stack.add(self.caption_editable_column)

        self.caption_row.add(self.caption_label_column)
        self.caption_row.add(self.caption_edit_stack)
        self.caption_row.add_spacing(8)

        # session
        self.info_section_session_row = self.ui.create_row_widget()
        self.info_section_session_row.add(self.ui.create_label_widget(_("Session"), properties={"width": 60}))
        self.info_session_label = self.ui.create_label_widget(properties={"width": 240})
        self.info_session_label.bind_text(Binding.PropertyBinding(display_item, "session_id"))
        self.info_section_session_row.add(self.info_session_label)
        self.info_section_session_row.add_stretch()
        # date
        self.info_section_datetime_row = self.ui.create_row_widget()
        self.info_section_datetime_row.add(self.ui.create_label_widget(_("Date"), properties={"width": 60}))
        self.info_datetime_label = self.ui.create_label_widget(properties={"width": 240})
        self.info_datetime_label.bind_text(Binding.PropertyBinding(display_item, "created_local_as_string"))
        self.info_section_datetime_row.add(self.info_datetime_label)
        self.info_section_datetime_row.add_stretch()
        # add all of the rows to the section content
        self.add_widget_to_content(self.info_section_title_row)
        self.add_widget_to_content(self.caption_row)
        self.add_widget_to_content(self.info_section_session_row)
        self.add_widget_to_content(self.info_section_datetime_row)
        self.finish_widget_content()
        # add unbinders
        self._unbinder.add([display_item], [self.info_title_label.unbind_text, self.caption_static_text.unbind_text, self.info_session_label.unbind_text, self.info_datetime_label.unbind_text])


class DataInfoInspectorSection(InspectorSection):
    def __init__(self, document_controller: DocumentController.DocumentController, display_data_channel: DisplayItem.DisplayDataChannel) -> None:
        super().__init__(document_controller.ui, "data-info", _("Data Info"))
        # date
        self.info_section_datetime_row = self.ui.create_row_widget()
        self.info_section_datetime_row.add(self.ui.create_label_widget(_("Date"), properties={"width": 60}))
        self.info_datetime_label = self.ui.create_label_widget(properties={"width": 240})
        self.info_datetime_label.bind_text(Binding.PropertyBinding(display_data_channel, "created_local_as_string"))
        self.info_section_datetime_row.add(self.info_datetime_label)
        self.info_section_datetime_row.add_stretch()
        # format (size, datatype)
        self.info_section_format_row = self.ui.create_row_widget()
        self.info_section_format_row.add(self.ui.create_label_widget(_("Data"), properties={"width": 60}))
        self.info_format_label = self.ui.create_label_widget(properties={"width": 240})
        self.info_format_label.bind_text(Binding.PropertyBinding(display_data_channel, "size_and_data_format_as_string"))
        self.info_section_format_row.add(self.info_format_label)
        self.info_section_format_row.add_stretch()
        # add all of the rows to the section content
        self.add_widget_to_content(self.info_section_datetime_row)
        self.add_widget_to_content(self.info_section_format_row)
        self.finish_widget_content()
        # add unbinders
        self._unbinder.add([display_data_channel], [self.info_datetime_label.unbind_text, self.info_format_label.unbind_text])


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

    def perform(self) -> None:
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
    def __init__(self, document_model: DocumentModel.DocumentModel, display_item: DisplayItem.DisplayItem, display_layer_index: int, display_data_channel: DisplayItem.DisplayDataChannel) -> None:
        super().__init__(_("Change Display Layer Data"), command_id="change_display_layer_data", is_mergeable=True)
        self.__document_model = document_model
        self.__display_item_proxy = display_item.create_proxy()
        self.__display_layer_index = display_layer_index
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

    def perform(self) -> None:
        display_item = self.__display_item_proxy.item
        display_data_channel = self.__display_data_channel_proxy.item if self.__display_data_channel_proxy else None
        if display_item:
            old_display_data_channel = display_item.get_display_layer_display_data_channel(self.__display_layer_index)
            display_item.set_display_layer_display_data_channel(self.__display_layer_index, display_data_channel)
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


class LinePlotDisplayLayersInspectorSection(InspectorSection):
    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem) -> None:
        super().__init__(document_controller.ui, "line-plot-display-layer", _("Line Plot Display Layers"))
        ui = self.ui

        def change_label(label_edit_widget: UserInterface.LineEditWidget, display_layer: DisplayItem.DisplayLayer, label: str) -> None:
            index = display_item.display_layers.index(display_layer)
            command = ChangeDisplayLayerPropertyCommand(document_controller.document_model, display_item, index, "label", label)
            command.perform()
            document_controller.push_undo_command(command)
            label_edit_widget.select_all()

        def move_layer_forward(display_layer: DisplayItem.DisplayLayer) -> None:
            index = display_item.display_layers.index(display_layer)
            if index > 0:
                command = DisplayPanel.MoveDisplayLayerCommand(document_controller.document_model, display_item, index, display_item, index - 1)
                command.perform()
                document_controller.push_undo_command(command)

        def move_layer_backward(display_layer: DisplayItem.DisplayLayer) -> None:
            index = display_item.display_layers.index(display_layer)
            if index < len(display_item.display_layers) - 1:
                command = DisplayPanel.MoveDisplayLayerCommand(document_controller.document_model, display_item, index, display_item, index + 1)
                command.perform()
                document_controller.push_undo_command(command)

        def add_layer(display_layer: DisplayItem.DisplayLayer) -> None:
            index = display_item.display_layers.index(display_layer) + 1
            command = DisplayPanel.AddDisplayLayerCommand(document_controller.document_model, display_item, index)
            command.perform()
            document_controller.push_undo_command(command)

        def remove_layer(display_layer: DisplayItem.DisplayLayer) -> None:
            index = display_item.display_layers.index(display_layer)
            command = DisplayPanel.RemoveDisplayLayerCommand(document_controller.document_model, display_item, index)
            command.perform()
            document_controller.push_undo_command(command)

        def change_data_index(data_index_widget: UserInterface.LineEditWidget, display_layer: DisplayItem.DisplayLayer, data_index_str: str) -> None:
            data_index = Converter.IntegerToStringConverter(pass_none=True).convert_back(data_index_str)
            display_data_channel = display_item.display_data_channels[data_index] if data_index is not None else None
            if display_data_channel:
                index = display_item.display_layers.index(display_layer)
                command = ChangeDisplayLayerDisplayDataChannelCommand(document_controller.document_model, display_item, index, display_data_channel)
                command.perform()
                document_controller.push_undo_command(command)
                data_index_widget.select_all()

        def change_data_row(data_row_widget: UserInterface.LineEditWidget, display_layer: DisplayItem.DisplayLayer, data_row_str: str) -> None:
            data_row = Converter.IntegerToStringConverter().convert_back(data_row_str)
            index = display_item.display_layers.index(display_layer)
            command = ChangeDisplayLayerPropertyCommand(document_controller.document_model, display_item, index, "data_row", data_row)
            command.perform()
            document_controller.push_undo_command(command)
            data_row_widget.select_all()

        def change_fill_color(color_widget: Widgets.ColorPushButtonWidget, color_edit: UserInterface.LineEditWidget, display_layer: DisplayItem.DisplayLayer, color: str) -> None:
            index = display_item.display_layers.index(display_layer)
            command = ChangeDisplayLayerPropertyCommand(document_controller.document_model, display_item, index, "fill_color", color)
            command.perform()
            document_controller.push_undo_command(command)
            color_widget.color = color
            color_edit.text = color
            color_edit.select_all()

        def change_stroke_color(color_widget: Widgets.ColorPushButtonWidget, color_edit: UserInterface.LineEditWidget, display_layer: DisplayItem.DisplayLayer, color: str) -> None:
            index = display_item.display_layers.index(display_layer)
            command = ChangeDisplayLayerPropertyCommand(document_controller.document_model, display_item, index, "stroke_color", color)
            command.perform()
            document_controller.push_undo_command(command)
            color_widget.color = color
            color_edit.text = color
            color_edit.select_all()

        def change_stroke_width(width_widget: UserInterface.LineEditWidget, display_layer: DisplayItem.DisplayLayer, width_str: str) -> None:
            width = Converter.FloatToStringConverter(pass_none=True).convert_back(width_str)
            index = display_item.display_layers.index(display_layer)
            command = ChangeDisplayLayerPropertyCommand(document_controller.document_model, display_item, index, "stroke_width", width)
            command.perform()
            document_controller.push_undo_command(command)
            width_widget.select_all()

        class DisplayLayerWidget(Widgets.CompositeWidgetBase):
            def __init__(self, display_layer: DisplayItem.DisplayLayer) -> None:
                content_widget = document_controller.ui.create_column_widget()
                super().__init__(content_widget)
                # label
                label_edit_widget = ui.create_line_edit_widget()
                label_row = ui.create_row_widget(properties={"spacing": 12})
                self.__label_widget = ui.create_label_widget()
                self.update_label_widget(display_layer)
                label_row.add(self.__label_widget)
                label_row.add(label_edit_widget)
                label_row.add_spacing(12)
                label_edit_widget.on_editing_finished = functools.partial(change_label, label_edit_widget, display_layer)
                # move up, move down, add layer, remove layer
                move_forward_button_widget = Widgets.TextPushButtonWidget(ui, "\N{UPWARDS WHITE ARROW}")
                move_backward_button_widget = Widgets.TextPushButtonWidget(ui, "\N{DOWNWARDS WHITE ARROW}")
                add_layer_button_widget = Widgets.TextPushButtonWidget(ui, "\N{PLUS SIGN}")
                remove_layer_button_widget = Widgets.TextPushButtonWidget(ui, "\N{MINUS SIGN}")
                button_row = ui.create_row_widget()
                button_row.add(move_forward_button_widget)
                button_row.add(move_backward_button_widget)
                button_row.add_stretch()
                button_row.add(add_layer_button_widget)
                button_row.add(remove_layer_button_widget)
                button_row.add_spacing(12)
                move_forward_button_widget.on_button_clicked = functools.partial(move_layer_forward, display_layer)
                move_backward_button_widget.on_button_clicked = functools.partial(move_layer_backward, display_layer)
                add_layer_button_widget.on_button_clicked = functools.partial(add_layer, display_layer)
                remove_layer_button_widget.on_button_clicked = functools.partial(remove_layer, display_layer)
                # content: display data channel, row
                display_data_channel_index_widget = ui.create_line_edit_widget(properties={"width": 36})
                display_data_channel_index_widget.widget_id = "display_data_channel_index_widget"
                display_data_channel_row_widget = ui.create_line_edit_widget(properties={"width": 36})
                content_row = ui.create_row_widget(properties={"spacing": 12})
                content_row.add(ui.create_label_widget(_("Data Index")))
                content_row.add(display_data_channel_index_widget)
                content_row.add(ui.create_label_widget(_("Row")))
                content_row.add(display_data_channel_row_widget)
                content_row.add_stretch()
                display_data_channel_index_widget.on_editing_finished = functools.partial(change_data_index, display_data_channel_index_widget, display_layer)
                display_data_channel_row_widget.on_editing_finished = functools.partial(change_data_row, display_data_channel_row_widget, display_layer)
                # display: fill color, stroke color, label
                fill_color_widget = Widgets.ColorPushButtonWidget(ui)
                fill_color_edit = ui.create_line_edit_widget(properties={"width": 80})
                fill_color_edit.placeholder_text = _("None")
                fill_color_row = ui.create_row_widget(properties={"spacing": 8})
                fill_color_row.add(ui.create_label_widget(_("Fill Color"), properties={"width": 80}))
                fill_color_row.add(fill_color_widget)
                fill_color_row.add(fill_color_edit)
                fill_color_row.add_stretch()
                fill_color_widget.on_color_changed = functools.partial(change_fill_color, fill_color_widget, fill_color_edit, display_layer)
                fill_color_edit.on_editing_finished = functools.partial(change_fill_color, fill_color_widget, fill_color_edit, display_layer)
                stroke_color_widget = Widgets.ColorPushButtonWidget(ui)
                stroke_color_edit = ui.create_line_edit_widget(properties={"width": 80})
                stroke_color_edit.placeholder_text = _("None")
                stroke_color_row = ui.create_row_widget(properties={"spacing": 8})
                stroke_color_row.add(ui.create_label_widget(_("Stroke Color"), properties={"width": 80}))
                stroke_color_row.add(stroke_color_widget)
                stroke_color_row.add(stroke_color_edit)
                stroke_color_row.add_stretch()
                stroke_color_widget.on_color_changed = functools.partial(change_stroke_color, stroke_color_widget, stroke_color_edit, display_layer)
                stroke_color_edit.on_editing_finished = functools.partial(change_stroke_color, stroke_color_widget, stroke_color_edit, display_layer)
                stroke_width_edit = ui.create_line_edit_widget(properties={"width": 36})
                stroke_width_edit.text = str(display_layer.stroke_width) if display_layer.stroke_width is not None else None
                stroke_width_row = ui.create_row_widget(properties={"spacing": 8})
                stroke_width_row.add(ui.create_label_widget(_("Stroke Width"), properties={"width": 80, "height": 30}))
                stroke_width_row.add_spacing(44 + 8)  # color push button width + spacing to avoid collapse
                stroke_width_row.add(stroke_width_edit)
                stroke_width_row.add_stretch()
                stroke_width_edit.on_editing_finished = functools.partial(change_stroke_width, stroke_width_edit, display_layer)
                # build the inner column
                content_widget.add(label_row)
                content_widget.add(button_row)
                content_widget.add(content_row)
                content_widget.add(fill_color_row)
                content_widget.add(stroke_color_row)
                content_widget.add(stroke_width_row)
                # complex display type
                display_data_channel = display_layer.display_data_channel
                if display_data_channel:
                    complex_display_type_row, self.__complex_display_type_changed_listener = make_complex_display_type_chooser(document_controller, display_data_channel)
                else:
                    complex_display_type_row, self.__complex_display_type_changed_listener = None, None
                if complex_display_type_row:
                    content_widget.add(complex_display_type_row)
                # save for populate
                self.__label_edit_widget = label_edit_widget
                self.__display_data_channel_index_widget = display_data_channel_index_widget
                self.__display_data_channel_row_widget = display_data_channel_row_widget
                self.__fill_color_widget = fill_color_widget
                self.__fill_color_edit = fill_color_edit
                self.__stroke_color_widget = stroke_color_widget
                self.__stroke_color_edit = stroke_color_edit
                self.__stroke_width_edit = stroke_width_edit

                def display_layer_property_changed(name: str) -> None:
                    if name == "display_data_channel":
                        index = display_item.display_layers.index(display_layer)
                        display_data_channel = display_item.get_display_layer_display_data_channel(index)
                        data_index = display_item.display_data_channels.index(display_data_channel) if display_data_channel else None
                        self.__display_data_channel_index_widget.text = str(data_index) if data_index is not None else str()
                    elif name == "label":
                        self.__label_edit_widget.text = display_layer.label
                    elif name == "stroke_color":
                        self.__stroke_color_widget.color = display_layer.stroke_color
                        self.__stroke_color_edit.text = display_layer.stroke_color
                    elif name == "fill_color":
                        self.__fill_color_widget.color = display_layer.fill_color
                        self.__fill_color_edit.text = display_layer.fill_color
                    elif name == "data_row":
                        self.__display_data_channel_row_widget.text = str(display_layer.data_row) if display_layer.data_row is not None else None
                    elif name == "stroke_width":
                        self.__stroke_width_edit.text = str(display_layer.stroke_width) if display_layer.stroke_width is not None else None

                self.__display_layer_property_changed_listener = display_layer.property_changed_event.listen(display_layer_property_changed)

                display_layer_property_changed("display_data_channel")
                display_layer_property_changed("label")
                display_layer_property_changed("stroke_color")
                display_layer_property_changed("fill_color")
                display_layer_property_changed("data_row")

            def close(self) -> None:
                self.__label_edit_widget = typing.cast(typing.Any, None)
                self.__display_data_channel_index_widget = typing.cast(typing.Any, None)
                self.__display_data_channel_row_widget = typing.cast(typing.Any, None)
                self.__fill_color_widget = typing.cast(typing.Any, None)
                self.__fill_color_edit = typing.cast(typing.Any, None)
                self.__stroke_color_widget = typing.cast(typing.Any, None)
                self.__stroke_color_edit = typing.cast(typing.Any, None)
                self.__stroke_width_edit = typing.cast(typing.Any, None)
                self.__display_layer_property_changed_listener.close()
                self.__display_layer_property_changed_listener = typing.cast(typing.Any, None)
                if self.__complex_display_type_changed_listener:
                    self.__complex_display_type_changed_listener.close()
                    self.__complex_display_type_changed_listener = None
                super().close()

            def update_label_widget(self, display_layer: DisplayItem.DisplayLayer) -> None:
                index = display_item.display_layers.index(display_layer)
                self.__label_widget.text = _("Layer") + " " + str(index) + ":"

        column = ui.create_column_widget(properties={"spacing": 12})

        # button to be used when there are no display layers
        add_layer_button_widget = ui.create_push_button_widget(_("Add Layer"))
        button_row = ui.create_row_widget()
        button_row.add(add_layer_button_widget)
        button_row.add_stretch()
        add_layer_button_widget.on_clicked = functools.partial(add_layer, 0)
        column.add(button_row)

        def update_labels() -> None:
            button_row.visible = len(display_item.display_layers) == 0
            for index, display_layer in enumerate(display_item.display_layers):
                if index + 1 < len(column.children):  # test is necessary during initial construction
                    typing.cast(DisplayLayerWidget, column.children[index + 1]).update_label_widget(display_layer)

        def display_layer_inserted(name: str, display_layer: DisplayItem.DisplayLayer, index: int) -> None:
            if name == "display_layers":
                display_layer_widget = DisplayLayerWidget(display_layer)
                column.insert(display_layer_widget, index + 1)
                update_labels()

        def display_layer_removed(name: str, value: DisplayItem.DisplayLayer, index: int) -> None:
            if name == "display_layers":
                column.remove(index + 1)
                update_labels()

        self.__display_layer_inserted_listener = display_item.item_inserted_event.listen(display_layer_inserted)
        self.__display_layer_removed_listener = display_item.item_removed_event.listen(display_layer_removed)

        for index, display_layer in enumerate(display_item.display_layers):
            display_layer_inserted("display_layers", display_layer, index)

        self.add_widget_to_content(column)
        self.finish_widget_content()

    def close(self) -> None:
        self.__display_layer_inserted_listener.close()
        self.__display_layer_inserted_listener = typing.cast(typing.Any, None)
        self.__display_layer_removed_listener.close()
        self.__display_layer_removed_listener = typing.cast(typing.Any, None)
        super().close()


class ImageDataInspectorSection(InspectorSection):
    def __init__(self, document_controller: DocumentController.DocumentController, display_data_channel: DisplayItem.DisplayDataChannel, display_item: DisplayItem.DisplayItem) -> None:
        super().__init__(document_controller.ui, "image-data", _("Image Data"))
        ui = document_controller.ui

        self.widget_id = "image_data_inspector_section"

        # color map
        color_map_row, self.__color_map_changed_listener = make_color_map_chooser(document_controller, display_data_channel)

        # brightness, contrast, gamma
        brightness_row = make_brightness_control(document_controller, display_data_channel)
        contrast_row = make_contrast_control(document_controller, display_data_channel)
        adjustment_row, self.__adjustment_changed_listener = make_adjustment_chooser(document_controller, display_data_channel)

        # complex display type
        complex_display_type_row, self.__complex_display_type_changed_listener = make_complex_display_type_chooser(document_controller, display_data_channel)

        # data_range model
        self.__data_range_model = Model.PropertyModel[typing.Any]()

        # date
        self.info_section_datetime_row = self.ui.create_row_widget()
        self.info_section_datetime_row.add(self.ui.create_label_widget(_("Date"), properties={"width": 60}))
        self.info_datetime_label = self.ui.create_label_widget(properties={"width": 240})
        self.info_datetime_label.bind_text(Binding.PropertyBinding(display_data_channel, "created_local_as_string"))
        self.info_section_datetime_row.add(self.info_datetime_label)
        self.info_section_datetime_row.add_stretch()

        # format (size, datatype)
        self.info_section_format_row = self.ui.create_row_widget()
        self.info_section_format_row.add(self.ui.create_label_widget(_("Data"), properties={"width": 60}))
        self.info_format_label = self.ui.create_label_widget(properties={"width": 240})
        self.info_format_label.bind_text(Binding.PropertyBinding(display_data_channel, "size_and_data_format_as_string"))
        self.info_section_format_row.add(self.info_format_label)
        self.info_section_format_row.add_stretch()

        # configure the display limit editor
        self.display_limits_range_row = ui.create_row_widget()
        self.display_limits_range_low = ui.create_label_widget(properties={"width": 80})
        self.display_limits_range_high = ui.create_label_widget(properties={"width": 80})
        float_point_2_converter = BetterFloatToStringConverter()
        float_point_2_none_converter = BetterFloatToStringConverter(pass_none=True)
        self.display_limits_range_low.bind_text(Binding.TuplePropertyBinding(self.__data_range_model, "value", 0, converter=float_point_2_converter, fallback=_("N/A")))
        self.display_limits_range_high.bind_text(Binding.TuplePropertyBinding(self.__data_range_model, "value", 1, converter=float_point_2_converter, fallback=_("N/A")))
        self.display_limits_range_row.add(ui.create_label_widget(_("Data Range:"), properties={"width": 120}))
        self.display_limits_range_row.add(self.display_limits_range_low)
        self.display_limits_range_row.add_spacing(8)
        self.display_limits_range_row.add(self.display_limits_range_high)
        self.display_limits_range_row.add_stretch()
        self.display_limits_limit_row = ui.create_row_widget()
        self.display_limits_limit_low = ui.create_line_edit_widget(properties={"width": 80})
        self.display_limits_limit_high = ui.create_line_edit_widget(properties={"width": 80})
        self.display_limits_limit_low.placeholder_text = _("Auto")
        self.display_limits_limit_high.placeholder_text = _("Auto")

        self.__display_limits_model = DisplayDataChannelPropertyCommandModel(document_controller, display_data_channel, "display_limits", title=_("Change Display Limits"), command_id="change_display_limits")

        self.display_limits_limit_low.bind_text(Binding.TuplePropertyBinding(self.__display_limits_model, "value", 0, converter=float_point_2_none_converter))
        self.display_limits_limit_high.bind_text(Binding.TuplePropertyBinding(self.__display_limits_model, "value", 1, converter=float_point_2_none_converter))
        self.display_limits_limit_row.add(ui.create_label_widget(_("Display Limits:"), properties={"width": 120}))
        self.display_limits_limit_row.add(self.display_limits_limit_low)
        self.display_limits_limit_row.add_spacing(8)
        self.display_limits_limit_row.add(self.display_limits_limit_high)
        self.display_limits_limit_row.add_stretch()

        self.add_widget_to_content(self.info_section_datetime_row)
        self.add_widget_to_content(self.info_section_format_row)
        self.add_widget_to_content(self.display_limits_range_row)
        self.add_widget_to_content(self.display_limits_limit_row)
        self.add_widget_to_content(color_map_row)
        self.add_widget_to_content(brightness_row)
        self.add_widget_to_content(contrast_row)
        self.add_widget_to_content(adjustment_row)
        if complex_display_type_row:
            self.add_widget_to_content(complex_display_type_row)

        self.finish_widget_content()

        def handle_display_values(display_values: typing.Optional[DisplayItem.DisplayValues]) -> None:
            if display_values:
                self.__data_range_model.value = display_values.data_range

        self.__display_values_subscription = display_data_channel.subscribe_to_latest_computed_display_values(handle_display_values)

        handle_display_values(display_data_channel.get_latest_computed_display_values())

        # add unbinders
        self._unbinder.add([display_item, display_data_channel], [self.info_datetime_label.unbind_text, self.info_format_label.unbind_text, self.display_limits_range_low.unbind_text, self.display_limits_range_high.unbind_text, self.display_limits_limit_low.unbind_text, self.display_limits_limit_high.unbind_text])

    def close(self) -> None:
        self.__display_limits_model.close()
        self.__display_limits_model = typing.cast(typing.Any, None)
        self.__color_map_changed_listener.close()
        self.__color_map_changed_listener = typing.cast(typing.Any, None)
        if self.__complex_display_type_changed_listener:
            self.__complex_display_type_changed_listener.close()
            self.__complex_display_type_changed_listener = None
        self.__adjustment_changed_listener.close()
        self.__adjustment_changed_listener = typing.cast(typing.Any, None)
        self.__display_values_subscription = typing.cast(typing.Any, None)
        self.__data_range_model.close()
        self.__data_range_model = typing.cast(typing.Any, None)
        super().close()


class SessionInspectorSection(InspectorSection):

    def __init__(self, document_controller: DocumentController.DocumentController, data_item: DataItem.DataItem) -> None:
        super().__init__(document_controller.ui, "session", _("Session"))

        ui = document_controller.ui

        field_descriptions = [
            [_("Site"), _("Site Description"), "site"],
            [_("Instrument"), _("Instrument Description"), "instrument"],
            [_("Task"), _("Task Description"), "task"],
            [_("Microscopist"), _("Microscopist Name(s)"), "microscopist"],
            [_("Sample"), _("Sample Description"), "sample"],
            [_("Sample Area"), _("Sample Area Description"), "sample_area"],
            [_("Label"), _("Brief Label"), "label"],
        ]

        widget = self.ui.create_column_widget()

        def line_edit_changed(line_edit_widget: UserInterface.LineEditWidget, field_id: str, text: str) -> None:
            session_metadata = dict(data_item.session_metadata)
            session_metadata[field_id] = str(text)
            command = ChangePropertyCommand(document_controller.document_model, data_item, "session_metadata", session_metadata)
            command.perform()
            document_controller.push_undo_command(command)
            line_edit_widget.request_refocus()

        field_line_edit_widget_map = dict()

        first_field = True
        for field_description in field_descriptions:
            title, placeholder, field_id = field_description
            row = self.ui.create_row_widget()
            row.add(self.ui.create_label_widget(title, properties={"width": 100}))
            line_edit_widget = self.ui.create_line_edit_widget()
            line_edit_widget.placeholder_text = placeholder
            line_edit_widget.on_editing_finished = functools.partial(line_edit_changed, line_edit_widget, field_id)
            field_line_edit_widget_map[field_id] = line_edit_widget
            row.add(line_edit_widget)
            if not first_field:
                widget.add_spacing(4)
            first_field = False
            widget.add(row)

        def update_fields(fields: typing.Mapping[str, str]) -> None:
            for field_id, line_edit_widget in field_line_edit_widget_map.items():
                line_edit_widget.text = fields.get(field_id)

        def fields_changed(key: str) -> None:
            if key == 'session_metadata':
                widget.add_task("update_fields", functools.partial(update_fields, data_item.session_metadata))
        self.__property_changed_listener = data_item.property_changed_event.listen(fields_changed) if data_item else None

        if data_item:
            update_fields(data_item.session_metadata)

        self.add_widget_to_content(widget)
        self.finish_widget_content()

    def close(self) -> None:
        if self.__property_changed_listener:
            self.__property_changed_listener.close()
            self.__property_changed_listener = typing.cast(typing.Any, None)
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

    def perform(self) -> None:
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

    def perform(self) -> None:
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


class InspectorSectionWidget(Widgets.CompositeWidgetBase):
    def __init__(self, ui: UserInterface.UserInterface) -> None:
        self.__content_widget = ui.create_column_widget()
        super().__init__(self.__content_widget)
        self.__unbinder = Unbinder()
        self.__closeables: typing.List[DocumentModel.Closeable] = list()

    def close(self) -> None:
        self.__unbinder.close()
        for closeable in self.__closeables:
            closeable.close()
        self.__closeables = typing.cast(typing.Any, None)
        super().close()

    def add_closeable(self, closeable: DocumentModel.Closeable) -> None:
        self.__closeables.append(closeable)

    def add_closeables(self, *closeables: DocumentModel.Closeable) -> None:
        for closeable in closeables:
            self.add_closeable(closeable)

    def add_unbinder(self, items: typing.Sequence[Unbindable], unbinders: typing.Sequence[typing.Callable[[], None]]) -> None:
        self.__unbinder.add(items, unbinders)

    def add(self, widget: UserInterface.Widget) -> None:
        self.__content_widget.add(widget)

    def add_spacing(self, spacing: int) -> None:
        self.__content_widget.add_spacing(spacing)

    def find_widget_by_id(self, widget_id: str) -> typing.Optional[UserInterface.Widget]:
        return self.__content_widget.find_widget_by_id(widget_id)


def make_calibration_style_chooser(document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem) -> InspectorSectionWidget:
    ui = document_controller.ui

    calibration_styles = display_item.calibration_styles

    display_calibration_style_options = [(calibration_style.label, calibration_style.calibration_style_id) for calibration_style in calibration_styles]

    display_calibration_style_reverse_map = {p[1]: i for i, p in enumerate(display_calibration_style_options)}

    class CalibrationStyleIndexConverter(Converter.ConverterLike[str, int]):
        def convert(self, value: typing.Optional[str]) -> typing.Optional[int]:
            return display_calibration_style_reverse_map.get(value or str(), 0)

        def convert_back(self, value: typing.Optional[int]) -> typing.Optional[str]:
            if value is not None and value >= 0 and value < len(display_calibration_style_options):
                return display_calibration_style_options[value][1]
            else:
                return calibration_styles[0].label

    display_calibration_style_chooser = ui.create_combo_box_widget(items=display_calibration_style_options, item_getter=operator.itemgetter(0))
    display_calibration_style_chooser.bind_current_index(ChangeDisplayItemPropertyBinding(document_controller, display_item, "calibration_style_id", converter=CalibrationStyleIndexConverter(), fallback=0))

    widget = InspectorSectionWidget(ui)

    widget.add(display_calibration_style_chooser)

    widget.add_unbinder([display_item], [display_calibration_style_chooser.unbind_current_index])

    return widget


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
    def get_calibration_style(self, display_item: DisplayItem.DisplayItem) -> typing.Sequence[DisplayItem.CalibrationStyleLike]: ...
    def get_calibrated_style_id(self, display_item: DisplayItem.DisplayItem) -> str: ...
    def get_calibration_styles(self, display_item: DisplayItem.DisplayItem) -> typing.Sequence[DisplayItem.CalibrationStyleLike]: ...
    def get_calibrations(self, display_item: DisplayItem.DisplayItem, calibration_style: DisplayItem.CalibrationStyleLike) -> typing.Sequence[Calibration.Calibration]: ...
    def get_calibration_style_id_property_name(self) -> str: ...
    def get_calibration_styles_property_name(self) -> str: ...
    def get_display_calibrations_property_name(self) -> str: ...


class DimensionalCalibrationStyleModelAdapter(CalibrationStyleModelAdapter):
    def get_calibration_style(self, display_item: DisplayItem.DisplayItem) -> typing.Sequence[DisplayItem.CalibrationStyleLike]:
        return display_item.calibration_styles

    def get_calibrated_style_id(self, display_item: DisplayItem.DisplayItem) -> str:
        return display_item.calibration_style_id

    def get_calibration_styles(self, display_item: DisplayItem.DisplayItem) -> typing.Sequence[DisplayItem.CalibrationStyleLike]:
        return display_item.calibration_styles

    def get_calibrations(self, display_item: DisplayItem.DisplayItem, calibration_style: DisplayItem.CalibrationStyleLike) -> typing.Sequence[Calibration.Calibration]:
        return display_item.get_displayed_dimensional_calibrations_with_calibration_style(typing.cast(DisplayItem.CalibrationStyle, calibration_style))

    def get_calibration_style_id_property_name(self) -> str:
        return "calibration_style_id"

    def get_calibration_styles_property_name(self) -> str:
        return "calibration_styles"

    def get_display_calibrations_property_name(self) -> str:
        return "displayed_dimensional_calibrations"


class IntensityCalibrationStyleModelAdapter(CalibrationStyleModelAdapter):
    def get_calibration_style(self, display_item: DisplayItem.DisplayItem) -> typing.Sequence[DisplayItem.CalibrationStyleLike]:
        return display_item.intensity_calibration_styles

    def get_calibrated_style_id(self, display_item: DisplayItem.DisplayItem) -> str:
        return display_item.intensity_calibration_style_id

    def get_calibration_styles(self, display_item: DisplayItem.DisplayItem) -> typing.Sequence[DisplayItem.CalibrationStyleLike]:
        return display_item.intensity_calibration_styles

    def get_calibrations(self, display_item: DisplayItem.DisplayItem, calibration_style: DisplayItem.CalibrationStyleLike) -> typing.Sequence[Calibration.Calibration]:
        return [display_item.get_displayed_intensity_calibration_with_calibration_style(typing.cast(DisplayItem.CalibrationStyle, calibration_style))]

    def get_calibration_style_id_property_name(self) -> str:
        return "intensity_calibration_style_id"

    def get_calibration_styles_property_name(self) -> str:
        return "intensity_calibration_styles"

    def get_display_calibrations_property_name(self) -> str:
        return "displayed_intensity_calibration"


class CalibrationStyleModel(Observable.Observable):
    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, adapter: CalibrationStyleModelAdapter) -> None:
        super().__init__()
        self.__document_controller = document_controller
        self.__display_item = display_item
        self.__adapter = adapter
        self.__display_item_property_changed_listener = display_item.property_changed_event.listen(ReferenceCounting.weak_partial(CalibrationStyleModel.__handle_display_item_property_changed, self))
        self.__display_item_display_property_changed_listener = display_item.display_property_changed_event.listen(ReferenceCounting.weak_partial(CalibrationStyleModel.__handle_display_item_property_changed, self))
        self.__calibration_styles = self.__adapter.get_calibration_style(self.__display_item)

    def __handle_display_item_property_changed(self, name: str) -> None:
        if name == self.__adapter.get_calibration_style_id_property_name():
            self.notify_property_changed("calibration_style_id")
            self.notify_property_changed("index")
        if name == self.__adapter.get_calibration_styles_property_name():
            self.__calibration_styles = self.__adapter.get_calibration_style(self.__display_item)
            self.notify_property_changed("items")
            self.notify_property_changed("index")
        if name == self.__adapter.get_display_calibrations_property_name():
            self.notify_property_changed("items")

    @property
    def items(self) -> typing.List[str]:
        items = list[str]()
        for calibration_style in self.__calibration_styles:
            calibration_style_label = calibration_style.label
            if calibration_style.is_calibrated:
                calibrations = self.__adapter.get_calibrations(self.__display_item, calibration_style)
                units = [c.units or "-" for c in calibrations]
                if units and all(unit == units[0] for unit in units):
                    calibration_style_label += " (" + units[0] + ")"
                else:
                    calibration_style_label += " (" + "/".join(units) + ")"
            items.append(calibration_style_label)
        return items

    @property
    def index(self) -> typing.Optional[int]:
        calibration_style_id = self.calibration_style_id
        for i, calibration_style in enumerate(self.__calibration_styles):
            if calibration_style.calibration_style_id == calibration_style_id:
                return i
        return 0

    @index.setter
    def index(self, value: typing.Optional[int]) -> None:
        value = value or 0  # startup case
        if value != self.index:
            value = max(0, min(value, len(self.__calibration_styles) - 1))
            self.calibration_style_id = self.__calibration_styles[value].calibration_style_id

    @property
    def calibration_style_id(self) -> str:
        return self.__adapter.get_calibrated_style_id(self.__display_item)

    @calibration_style_id.setter
    def calibration_style_id(self, value: str) -> None:
        if value != self.calibration_style_id:
            command = ChangeDisplayItemPropertyCommand(self.__document_controller.document_model, self.__display_item, self.__adapter.get_calibration_style_id_property_name(), value)
            command.perform()
            self.__document_controller.push_undo_command(command)
            self.notify_property_changed("calibration_style_id")
            self.notify_property_changed("index")


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

    @property
    def _calibration_style_model(self) -> CalibrationStyleModel:
        return self.__calibration_style_model

    @property
    def _intensity_calibration_style_model(self) -> CalibrationStyleModel:
        return self.__intensity_calibration_style_model


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

    def perform(self) -> None:
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


def make_display_type_chooser(document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem) -> typing.Tuple[UserInterface.BoxWidget, Event.EventListener]:
    ui = document_controller.ui
    display_type_row = ui.create_row_widget()
    display_type_items = ((_("Default"), None), (_("Line Plot"), "line_plot"), (_("Image"), "image"), (_("Display Script"), "display_script"))
    display_type_reverse_map = {None: 0, "line_plot": 1, "image": 2, "display_script": 3}
    display_type_chooser = ui.create_combo_box_widget(items=display_type_items, item_getter=operator.itemgetter(0))

    def property_changed(name: str) -> None:
        if name == "display_type":
            display_type_chooser.current_index = display_type_reverse_map[display_item.display_type]

    listener = display_item.property_changed_event.listen(property_changed)

    def change_display_type(item: typing.Tuple[str, typing.Optional[str]]) -> None:
        if display_item.display_type != item[1]:
            command = ChangeDisplayTypeCommand(document_controller.document_model, display_item, display_type=item[1])
            command.perform()
            document_controller.push_undo_command(command)

    display_type_chooser.on_current_item_changed = change_display_type
    display_type_chooser.current_index = display_type_reverse_map.get(display_item.display_type, 0)
    display_type_row.add(ui.create_label_widget(_("Display Type:"), properties={"width": 120}))
    display_type_row.add(display_type_chooser)
    display_type_row.add_stretch()
    return display_type_row, listener


def make_color_map_chooser(document_controller: DocumentController.DocumentController, display_data_channel: DisplayItem.DisplayDataChannel) -> typing.Tuple[UserInterface.BoxWidget, Event.EventListener]:
    ui = document_controller.ui
    color_map_row = ui.create_row_widget()
    color_map_options: typing.List[typing.Tuple[str, typing.Optional[str]]] = [(_("Default"), None)]
    for color_map_key, color_map in ColorMaps.color_maps.items():
        color_map_options.append((color_map.name, color_map_key))
    color_map_reverse_map = {p[1]: i for i, p in enumerate(color_map_options)}
    color_map_chooser = ui.create_combo_box_widget(items=color_map_options, item_getter=operator.itemgetter(0))

    def property_changed(name: str) -> None:
        if name == "color_map_id":
            color_map_chooser.current_index = color_map_reverse_map[display_data_channel.color_map_id]

    listener = display_data_channel.property_changed_event.listen(property_changed)

    def change_color_map(item: typing.Tuple[str, str]) -> None:
        if display_data_channel.color_map_id != item[1]:
            command = DisplayPanel.ChangeDisplayDataChannelCommand(document_controller.document_model, display_data_channel, color_map_id=item[1], title=_("Change Color Map"), command_id="change_color_map", is_mergeable=True)
            command.perform()
            document_controller.push_undo_command(command)

    color_map_chooser.on_current_item_changed = change_color_map
    color_map_chooser.current_index = color_map_reverse_map.get(display_data_channel.color_map_id, 0)
    color_map_row.add(ui.create_label_widget(_("Color Map:"), properties={"width": 120}))
    color_map_row.add(color_map_chooser)
    color_map_row.add_stretch()
    return color_map_row, listener


def make_brightness_control(document_controller: DocumentController.DocumentController, display_data_channel: DisplayItem.DisplayDataChannel) -> UserInterface.Widget:
    ui = document_controller.ui
    row_widget = ui.create_row_widget()  # use 280 pixels in row
    label_widget = ui.create_label_widget(_("Brightness"), properties={"width": 80})
    line_edit_widget = ui.create_line_edit_widget(properties={"width": 60})
    slider_widget = ui.create_slider_widget(properties={"width": 124})
    slider_widget.minimum = 0
    slider_widget.maximum = 100
    slider_widget.bind_value(ChangeDisplayDataChannelPropertyBinding(document_controller, display_data_channel, "brightness", converter=Converter.FloatToScaledIntegerConverter(100, -1.0, 1.0)))
    line_edit_widget.bind_text(ChangeDisplayDataChannelPropertyBinding(document_controller, display_data_channel, "brightness", converter=Converter.FloatToStringConverter(format="{:.2f}")))
    row_widget.add(label_widget)
    row_widget.add_spacing(8)
    row_widget.add(slider_widget)
    row_widget.add_spacing(8)
    row_widget.add(line_edit_widget)
    row_widget.add_stretch()
    return row_widget


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


def make_contrast_control(document_controller: DocumentController.DocumentController, display_data_channel: DisplayItem.DisplayDataChannel) -> UserInterface.Widget:
    ui = document_controller.ui
    row_widget = ui.create_row_widget()  # use 280 pixels in row
    label_widget = ui.create_label_widget(_("Contrast"), properties={"width": 80})
    line_edit_widget = ui.create_line_edit_widget(properties={"width": 60})
    slider_widget = ui.create_slider_widget(properties={"width": 124})
    slider_widget.minimum = 0
    slider_widget.maximum = 100
    slider_widget.bind_value(ChangeDisplayDataChannelPropertyBinding(document_controller, display_data_channel, "contrast", converter=ContrastIntegerConverter(100)))
    line_edit_widget.bind_text(ChangeDisplayDataChannelPropertyBinding(document_controller, display_data_channel, "contrast", converter=ContrastStringConverter()))
    row_widget.add(label_widget)
    row_widget.add_spacing(8)
    row_widget.add(slider_widget)
    row_widget.add_spacing(8)
    row_widget.add(line_edit_widget)
    row_widget.add_stretch()
    return row_widget


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
        return None

    def convert_back(self, value_int: typing.Optional[int]) -> typing.Optional[float]:
        if value_int is not None:
            return math.pow(10, ((100 - value_int) - 50) / 50)
        return None


class ChangeDisplayDataChannelAdjustmentPropertyBinding(Binding.PropertyBinding):
    def __init__(self, document_controller: DocumentController.DocumentController,
                 display_data_channel: DisplayItem.DisplayDataChannel, property_name: str,
                 converter: Converter.ConverterLike[typing.Any, typing.Any],
                 default_value: typing.Any = None) -> None:
        super().__init__(display_data_channel, "adjustments")

        def set_value(value: typing.Any) -> typing.Any:
            if converter.convert_back(value) != display_data_channel.adjustments[0].get(property_name, None):
                adjustment = display_data_channel.adjustments[0]
                adjustment[property_name] = converter.convert_back(value)
                command = DisplayPanel.ChangeDisplayDataChannelCommand(document_controller.document_model, display_data_channel, title=_("Change Display"), command_id="change_display_" + property_name, is_mergeable=True, adjustments=[adjustment])
                command.perform()
                document_controller.push_undo_command(command)

        def get_value() -> typing.Any:
            if len(display_data_channel.adjustments) == 1:
                return converter.convert(display_data_channel.adjustments[0].get(property_name, default_value))
            return converter.convert(default_value)

        self.source_setter = set_value
        self.source_getter = get_value


def make_gamma_control(document_controller: DocumentController.DocumentController, display_data_channel: DisplayItem.DisplayDataChannel) -> UserInterface.Widget:
    ui = document_controller.ui
    row_widget = ui.create_row_widget()  # use 280 pixels in row
    label_widget = ui.create_label_widget(_("Gamma"), properties={"width": 80})
    line_edit_widget = ui.create_line_edit_widget(properties={"width": 60})
    slider_widget = ui.create_slider_widget(properties={"width": 124})
    slider_widget.minimum = 0
    slider_widget.maximum = 100
    slider_widget.bind_value(ChangeDisplayDataChannelAdjustmentPropertyBinding(document_controller, display_data_channel, "gamma", GammaIntegerConverter(), 1.0))
    line_edit_widget.bind_text(ChangeDisplayDataChannelAdjustmentPropertyBinding(document_controller, display_data_channel, "gamma", GammaStringConverter(), 1.0))
    row_widget.add(label_widget)
    row_widget.add_spacing(8)
    row_widget.add(slider_widget)
    row_widget.add_spacing(8)
    row_widget.add(line_edit_widget)
    row_widget.add_stretch()
    return row_widget


def make_adjustment_chooser(document_controller: DocumentController.DocumentController, display_data_channel: DisplayItem.DisplayDataChannel) -> typing.Tuple[UserInterface.Widget, typing.Any]:
    ui = document_controller.ui

    adjustment_column = ui.create_column_widget()

    adjustment_row = ui.create_row_widget()
    adjustment_options = [(_("None"), None), (_("Equalized"), "equalized"), (_("Gamma"), "gamma"), (_("Log"), "log")]
    adjustment_reverse_map = {p[1]: i for i, p in enumerate(adjustment_options)}
    adjustment_chooser = ui.create_combo_box_widget(items=adjustment_options, item_getter=operator.itemgetter(0))

    def get_current_adjustment_id() -> typing.Optional[str]:
        return display_data_channel.adjustments[0].get("type") if len(display_data_channel.adjustments) == 1 else None

    def get_current_index() -> int:
        return adjustment_reverse_map[get_current_adjustment_id()]

    def update_controls() -> None:
        adjustment_column.children[1].visible = get_current_adjustment_id() == "gamma"

    def property_changed(name: str) -> None:
        if name == "adjustments":
            adjustment_chooser.current_index = get_current_index()
            update_controls()

    listener = display_data_channel.property_changed_event.listen(property_changed)

    def change_adjustment(item: typing.Tuple[str, typing.Optional[str]]) -> None:
        if get_current_adjustment_id() != item[1]:
            adjustments = list() if item[1] is None else [{"type": item[1], "uuid": str(uuid.uuid4())}]
            command = DisplayPanel.ChangeDisplayDataChannelCommand(document_controller.document_model, display_data_channel, adjustments=adjustments)
            command.perform()
            document_controller.push_undo_command(command)

    adjustment_chooser.on_current_item_changed = change_adjustment
    adjustment_chooser.current_index = get_current_index()
    adjustment_row.add(ui.create_label_widget(_("Adjustment:"), properties={"width": 120}))
    adjustment_row.add(adjustment_chooser)
    adjustment_row.add_stretch()

    adjustment_column.add(adjustment_row)
    adjustment_column.add(make_gamma_control(document_controller, display_data_channel))

    update_controls()

    return adjustment_column, listener


def make_complex_display_type_chooser(document_controller: DocumentController.DocumentController,
                                      display_data_channel: DisplayItem.DisplayDataChannel,
                                      include_log_abs: bool = True) -> typing.Tuple[typing.Optional[UserInterface.BoxWidget], typing.Optional[Event.EventListener]]:
    if not (display_data_channel.data_item and display_data_channel.data_item.is_data_complex_type):
        return None, None
    ui = document_controller.ui
    display_type_row = ui.create_row_widget()
    display_type_options = [(_("Log Absolute"), "log-absolute")] if include_log_abs else list()
    display_type_options.extend([(_("Absolute"), "absolute"), (_("Phase"), "phase"), (_("Real"), "real"), (_("Imaginary"), "imaginary")])
    display_type_reverse_map = {p[1]: i for i, p in enumerate(display_type_options)}
    display_type_chooser = ui.create_combo_box_widget(items=display_type_options, item_getter=operator.itemgetter(0))

    def property_changed(name: str) -> None:
        if name == "complex_display_type":
            display_type_chooser.current_index = display_type_reverse_map.get(display_data_channel.complex_display_type or str(), 0)

    listener = display_data_channel.property_changed_event.listen(property_changed)

    def change_display_type(item: typing.Tuple[str, typing.Optional[str]]) -> None:
        if display_data_channel.complex_display_type != item[1]:
            command = DisplayPanel.ChangeDisplayDataChannelCommand(document_controller.document_model, display_data_channel, complex_display_type=item[1])
            command.perform()
            document_controller.push_undo_command(command)

    display_type_chooser.on_current_item_changed = change_display_type
    display_type_chooser.current_index = display_type_reverse_map.get(display_data_channel.complex_display_type or str(), 0)
    display_type_row.add(ui.create_label_widget(_("Complex Display Type:"), properties={"width": 120}))
    display_type_row.add(display_type_chooser)
    display_type_row.add_stretch()
    return display_type_row, listener


class ImageDisplayInspectorSection(InspectorSection):
    """Display type inspector."""

    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem) -> None:
        super().__init__(document_controller.ui, "display-limits", _("Image Display"))

        # display type
        display_type_row, self.__display_type_changed_listener = make_display_type_chooser(document_controller, display_item)

        self.add_widget_to_content(display_type_row)

        self.finish_widget_content()

    def close(self) -> None:
        self.__display_type_changed_listener.close()
        self.__display_type_changed_listener = typing.cast(typing.Any, None)
        super().close()


def make_legend_position(document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem) -> typing.Tuple[UserInterface.BoxWidget, Event.EventListener]:
    # This function is currently only utilized by line plots
    ui = document_controller.ui
    legend_position_row = ui.create_row_widget()
    legend_position_options = [(_("None"), None), (_("Top Left"), "top-left"), (_("Top Right"), "top-right"), (_("Outer Left"), "outer-left"), (_("Outer Right"), "outer-right")]
    legend_position_reverse_map = {p[1]: i for i, p in enumerate(legend_position_options)}
    legend_position_chooser = ui.create_combo_box_widget(items=legend_position_options, item_getter=operator.itemgetter(0))

    def property_changed(name: str) -> None:
        if name == "legend_position":
            legend_position_chooser.current_index = legend_position_reverse_map.get(display_item.get_display_property("legend_position", None), 0)

    listener = display_item.display_property_changed_event.listen(property_changed)

    def change_legend_position(item: typing.Tuple[str, typing.Optional[str]]) -> None:
        if display_item.get_display_property("legend_position", None) != item[1]:
            command = DisplayPanel.ChangeDisplayCommand(document_controller.document_model, display_item, title=_("Legend Position"), command_id="change_legend_position", is_mergeable=True, legend_position=item[1])
            command.perform()
            document_controller.push_undo_command(command)

    legend_position_chooser.on_current_item_changed = change_legend_position
    legend_position_chooser.current_index = legend_position_reverse_map.get(display_item.get_display_property("legend_position", None), 0)
    legend_position_row.add(ui.create_label_widget(_("Legend Position:"), properties={"width": 120}))
    legend_position_row.add(legend_position_chooser)
    legend_position_row.add_stretch()

    return legend_position_row, listener


class LinePlotDisplayInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement display limits inspector.
    """

    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem) -> None:
        super().__init__(document_controller.ui, "line-plot", _("Line Plot Display"))

        # display type
        display_type_row, self.__display_type_changed_listener = make_display_type_chooser(document_controller, display_item)

        float_point_2_none_converter = BetterFloatToStringConverter(pass_none=True)

        self.display_limits_limit_row = self.ui.create_row_widget()
        self.display_limits_limit_low = self.ui.create_line_edit_widget(properties={"width": 80})
        self.display_limits_limit_high = self.ui.create_line_edit_widget(properties={"width": 80})
        self.display_limits_limit_low.bind_text(ChangeDisplayPropertyBinding(document_controller, display_item, "y_min", converter=float_point_2_none_converter))
        self.display_limits_limit_high.bind_text(ChangeDisplayPropertyBinding(document_controller, display_item, "y_max", converter=float_point_2_none_converter))
        self.display_limits_limit_low.placeholder_text = _("Auto")
        self.display_limits_limit_high.placeholder_text = _("Auto")
        self.display_limits_limit_row.add(self.ui.create_label_widget(_("Display:"), properties={"width": 120}))
        self.display_limits_limit_row.add(self.display_limits_limit_low)
        self.display_limits_limit_row.add_spacing(8)
        self.display_limits_limit_row.add(self.display_limits_limit_high)
        self.display_limits_limit_row.add_stretch()

        self.channels_row = self.ui.create_row_widget()
        self.channels_left = self.ui.create_line_edit_widget(properties={"width": 80})
        self.channels_right = self.ui.create_line_edit_widget(properties={"width": 80})
        self.channels_left.bind_text(ChangeDisplayPropertyBinding(document_controller, display_item, "left_channel", converter=float_point_2_none_converter))
        self.channels_right.bind_text(ChangeDisplayPropertyBinding(document_controller, display_item, "right_channel", converter=float_point_2_none_converter))
        self.channels_left.placeholder_text = _("Auto")
        self.channels_right.placeholder_text = _("Auto")
        self.channels_row.add(self.ui.create_label_widget(_("Channels:"), properties={"width": 120}))
        self.channels_row.add(self.channels_left)
        self.channels_row.add_spacing(8)
        self.channels_row.add(self.channels_right)
        self.channels_row.add_stretch()

        class LogCheckedToCheckStateConverter(Converter.ConverterLike[str, str]):
            """ Convert between bool and checked/unchecked strings. """

            def convert(self, value: typing.Optional[str]) -> typing.Optional[str]:
                """ Convert bool to checked or unchecked string """
                return "checked" if value == "log" else "unchecked"

            def convert_back(self, value: typing.Optional[str]) -> typing.Optional[str]:
                """ Convert checked or unchecked string to bool """
                return "log" if value == "checked" else "linear"

        self.style_row = self.ui.create_row_widget()
        self.style_y_log = self.ui.create_check_box_widget(_("Log Scale (Y)"))
        self.style_y_log.bind_check_state(ChangeDisplayPropertyBinding(document_controller, display_item, "y_style", converter=LogCheckedToCheckStateConverter()))
        self.style_row.add(self.style_y_log)
        self.style_row.add_stretch()

        legend_position_row, self.__legend_position_changed_listener = make_legend_position(document_controller, display_item)

        self.add_widget_to_content(display_type_row)
        self.add_widget_to_content(self.display_limits_limit_row)
        self.add_widget_to_content(self.channels_row)
        self.add_widget_to_content(self.style_row)
        self.add_widget_to_content(legend_position_row)

        self.finish_widget_content()

        # add unbinders
        self._unbinder.add([display_item], [self.display_limits_limit_low.unbind_text, self.display_limits_limit_high.unbind_text, self.channels_left.unbind_text, self.channels_right.unbind_text, self.style_y_log.unbind_check_state])

    def close(self) -> None:
        self.__legend_position_changed_listener.close()
        self.__legend_position_changed_listener = typing.cast(typing.Any, None)
        self.__display_type_changed_listener.close()
        self.__display_type_changed_listener = typing.cast(typing.Any, None)
        super().close()


class SequenceInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement slice inspector.
    """

    def __init__(self, document_controller: DocumentController.DocumentController, display_data_channel: DisplayItem.DisplayDataChannel) -> None:
        super().__init__(document_controller.ui, "sequence", _("Sequence"))

        data_item = display_data_channel.data_item
        assert data_item

        sequence_index_row_widget = self.ui.create_row_widget()  # use 280 pixels in row
        sequence_index_label_widget = self.ui.create_label_widget(_("Index"), properties={"width": 60})
        sequence_index_line_edit_widget = self.ui.create_line_edit_widget(properties={"width": 60})
        sequence_index_slider_widget = self.ui.create_slider_widget(properties={"width": 144})
        sequence_index_slider_widget.maximum = data_item.dimensional_shape[0] - 1  # sequence_index
        sequence_index_slider_widget.bind_value(ChangeDisplayDataChannelPropertyBinding(document_controller, display_data_channel, "sequence_index"))
        sequence_index_line_edit_widget.bind_text(ChangeDisplayDataChannelPropertyBinding(document_controller, display_data_channel, "sequence_index", converter=Converter.IntegerToStringConverter()))
        sequence_index_row_widget.add(sequence_index_label_widget)
        sequence_index_row_widget.add_spacing(8)
        sequence_index_row_widget.add(sequence_index_slider_widget)
        sequence_index_row_widget.add_spacing(8)
        sequence_index_row_widget.add(sequence_index_line_edit_widget)
        sequence_index_row_widget.add_stretch()

        self.add_widget_to_content(sequence_index_row_widget)
        self.finish_widget_content()

        # for testing
        self._sequence_index_slider_widget = sequence_index_slider_widget
        self._sequence_index_line_edit_widget = sequence_index_line_edit_widget

        # add unbinders
        self._unbinder.add([display_data_channel], [sequence_index_slider_widget.unbind_value, sequence_index_line_edit_widget.unbind_text])


class CollectionIndexInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement slice inspector.
    """

    def __init__(self, document_controller: DocumentController.DocumentController, display_data_channel: DisplayItem.DisplayDataChannel) -> None:
        super().__init__(document_controller.ui, "collection-index", _("Index"))

        data_item = display_data_channel.data_item
        assert data_item

        column_widget = self.ui.create_column_widget()
        collection_index_base = 1 if data_item.is_sequence else 0
        for index in range(data_item.collection_dimension_count):
            index_row_widget = self.ui.create_row_widget()  # use 280 pixels in row
            index_label_widget = self.ui.create_label_widget("{}: {}".format(_("Index"), index), properties={"width": 60})
            index_line_edit_widget = self.ui.create_line_edit_widget(properties={"width": 60})
            index_slider_widget = self.ui.create_slider_widget(properties={"width": 144})
            index_slider_widget.maximum = data_item.dimensional_shape[collection_index_base + index] - 1

            self.__collection_index_model = DisplayDataChannelPropertyCommandModel(document_controller, display_data_channel, "collection_index", title=_("Change Collection Index"), command_id="change_collection_index")

            index_slider_widget.bind_value(Binding.TuplePropertyBinding(self.__collection_index_model, "value", index))
            index_line_edit_widget.bind_text(Binding.TuplePropertyBinding(self.__collection_index_model, "value", index, converter=Converter.IntegerToStringConverter()))
            index_row_widget.add(index_label_widget)
            index_row_widget.add_spacing(8)
            index_row_widget.add(index_slider_widget)
            index_row_widget.add_spacing(8)
            index_row_widget.add(index_line_edit_widget)
            index_row_widget.add_stretch()
            column_widget.add(index_row_widget)

            # add unbinders
            self._unbinder.add([display_data_channel], [index_slider_widget.unbind_value, index_line_edit_widget.unbind_text])

        self.add_widget_to_content(column_widget)
        self.finish_widget_content()

        # for testing
        self._column_widget = column_widget

    def close(self) -> None:
        self.__collection_index_model.close()
        self.__collection_index_model = typing.cast(typing.Any, None)
        super().close()


class SliceInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement slice inspector.
    """

    def __init__(self, document_controller: DocumentController.DocumentController, display_data_channel: DisplayItem.DisplayDataChannel) -> None:
        super().__init__(document_controller.ui, "slice", _("Slice"))

        data_item = display_data_channel.data_item
        assert data_item

        slice_center_row_widget = self.ui.create_row_widget()  # use 280 pixels in row
        slice_center_label_widget = self.ui.create_label_widget(_("Slice"), properties={"width": 60})
        slice_center_line_edit_widget = self.ui.create_line_edit_widget(properties={"width": 60})
        slice_center_slider_widget = self.ui.create_slider_widget(properties={"width": 144})
        slice_center_slider_widget.maximum = data_item.dimensional_shape[-1] - 1  # signal_index
        slice_center_slider_widget.bind_value(ChangeDisplayDataChannelPropertyBinding(document_controller, display_data_channel, "slice_center"))
        slice_center_line_edit_widget.bind_text(ChangeDisplayDataChannelPropertyBinding(document_controller, display_data_channel, "slice_center", converter=Converter.IntegerToStringConverter()))
        slice_center_row_widget.add(slice_center_label_widget)
        slice_center_row_widget.add_spacing(8)
        slice_center_row_widget.add(slice_center_slider_widget)
        slice_center_row_widget.add_spacing(8)
        slice_center_row_widget.add(slice_center_line_edit_widget)
        slice_center_row_widget.add_stretch()

        slice_width_row_widget = self.ui.create_row_widget()  # use 280 pixels in row
        slice_width_label_widget = self.ui.create_label_widget(_("Width"), properties={"width": 60})
        slice_width_line_edit_widget = self.ui.create_line_edit_widget(properties={"width": 60})
        slice_width_slider_widget = self.ui.create_slider_widget(properties={"width": 144})
        slice_width_slider_widget.maximum = data_item.dimensional_shape[-1] - 1  # signal_index
        slice_width_slider_widget.bind_value(ChangeDisplayDataChannelPropertyBinding(document_controller, display_data_channel, "slice_width"))
        slice_width_line_edit_widget.bind_text(ChangeDisplayDataChannelPropertyBinding(document_controller, display_data_channel, "slice_width", converter=Converter.IntegerToStringConverter()))
        slice_width_row_widget.add(slice_width_label_widget)
        slice_width_row_widget.add_spacing(8)
        slice_width_row_widget.add(slice_width_slider_widget)
        slice_width_row_widget.add_spacing(8)
        slice_width_row_widget.add(slice_width_line_edit_widget)
        slice_width_row_widget.add_stretch()

        # add unbinders
        self._unbinder.add([display_data_channel], [slice_center_slider_widget.unbind_value, slice_center_line_edit_widget.unbind_text, slice_width_slider_widget.unbind_value, slice_width_line_edit_widget.unbind_text])

        self.add_widget_to_content(slice_center_row_widget)
        self.add_widget_to_content(slice_width_row_widget)
        self.finish_widget_content()

        # for testing
        self._slice_center_slider_widget = slice_center_slider_widget
        self._slice_width_slider_widget = slice_width_slider_widget
        self._slice_center_line_edit_widget = slice_center_line_edit_widget
        self._slice_width_line_edit_widget = slice_width_line_edit_widget


class RadianToDegreeStringConverter(Converter.ConverterLike[float, str]):
    """
        Converter object to convert from radian value to degree string and back.
    """
    def convert(self, value: typing.Optional[float]) -> typing.Optional[str]:
        if value is not None:
            return "{0:.4f}°".format(math.degrees(value))
        return None

    def convert_back(self, value_str: typing.Optional[str]) -> typing.Optional[float]:
        if value_str is not None:
            return math.radians(Converter.FloatToStringConverter().convert_back(value_str) or 0.0)
        return None


class CalibratedValueFloatToStringConverter(Converter.ConverterLike[float, str]):
    """Converter object to convert from calibrated value to string and back.

    If uniform is true, the converter will fall back to uncalibrated value if the calibrations have
    different units.
    """
    def __init__(self, display_item: DisplayItem.DisplayItem, index: int, uniform: bool = False) -> None:
        self.__display_item = display_item
        self.__index = index
        self.__uniform = uniform

    def __get_calibration(self) -> Calibration.Calibration:
        index = self.__index
        calibrations = self.__display_item.displayed_datum_calibrations
        if self.__uniform:
            unit_set = set(calibration.units if calibration.units else '' for calibration in calibrations)
            if len(unit_set) > 1:
                return Calibration.Calibration()
        dimension_count = len(calibrations)
        if index < 0:
            index = dimension_count + index
        if index >= 0 and index < dimension_count:
            return calibrations[index]
        else:
            return Calibration.Calibration()

    def get_units(self) -> str:
        return self.__get_calibration().units

    def __get_data_size(self) -> int:
        index = self.__index
        display_data_shape = self.__display_item.display_data_shape
        dimension_count = len(display_data_shape) if display_data_shape is not None else 0
        if index < 0:
            index = dimension_count + index
        if index >= 0 and index < dimension_count and display_data_shape is not None:
            return display_data_shape[index]
        else:
            return 1

    def convert_calibrated_value_to_str(self, calibrated_value: float) -> str:
        calibration = self.__get_calibration()
        return calibration.convert_calibrated_value_to_str(calibrated_value)

    def convert_to_calibrated_value(self, value: float) -> float:
        calibration = self.__get_calibration()
        data_size = self.__get_data_size()
        return calibration.convert_to_calibrated_value(data_size * value)

    def convert_from_calibrated_value(self, calibrated_value: float) -> float:
        calibration = self.__get_calibration()
        data_size = self.__get_data_size()
        return calibration.convert_from_calibrated_value(calibrated_value) / data_size

    def convert(self, value: typing.Optional[float]) -> typing.Optional[str]:
        if value is not None:
            calibration = self.__get_calibration()
            data_size = self.__get_data_size()
            return calibration.convert_to_calibrated_value_str(data_size * value, value_range=(0, data_size), samples=data_size)
        return None

    def convert_back(self, value_str: typing.Optional[str]) -> typing.Optional[float]:
        if value_str is not None:
            calibration = self.__get_calibration()
            data_size = self.__get_data_size()
            value = Converter.FloatToStringConverter().convert_back(value_str)
            if value is not None:
                return calibration.convert_from_calibrated_value(value) / data_size
        return None


class CalibratedSizeFloatToStringConverter(Converter.ConverterLike[float, str]):
    """
        Converter object to convert from calibrated size to string and back.
        """

    def __init__(self, display_item: DisplayItem.DisplayItem, index: int, factor: float = 1.0, uniform: bool = False) -> None:
        self.__display_item = display_item
        self.__index = index
        self.__factor = factor
        self.__uniform = uniform

    def __get_calibration(self) -> Calibration.Calibration:
        index = self.__index
        calibrations = self.__display_item.displayed_datum_calibrations
        if self.__uniform:
            unit_set = set(calibration.units if calibration.units else '' for calibration in calibrations)
            if len(unit_set) > 1:
                return Calibration.Calibration()
        dimension_count = len(calibrations)
        if index < 0:
            index = dimension_count + index
        if index >= 0 and index < dimension_count:
            return self.__display_item.displayed_datum_calibrations[index]
        else:
            return Calibration.Calibration()

    def __get_data_size(self) -> int:
        index = self.__index
        display_data_shape = self.__display_item.display_data_shape
        dimension_count = len(display_data_shape) if display_data_shape else 0
        if index < 0:
            index = dimension_count + index
        if index >= 0 and index < dimension_count and display_data_shape is not None:
            return display_data_shape[index]
        else:
            return 1

    def convert_calibrated_value_to_str(self, calibrated_value: float) -> str:
        calibration = self.__get_calibration()
        return calibration.convert_calibrated_size_to_str(calibrated_value)

    def convert_to_calibrated_value(self, size: float) -> float:
        calibration = self.__get_calibration()
        data_size = self.__get_data_size()
        return calibration.convert_to_calibrated_size(data_size * size * self.__factor)

    def convert(self, value: typing.Optional[float]) -> typing.Optional[str]:
        if value is not None:
            calibration = self.__get_calibration()
            data_size = self.__get_data_size()
            return calibration.convert_to_calibrated_size_str(data_size * value * self.__factor, value_range=(0, data_size), samples=data_size)
        return None

    def convert_back(self, value_str: typing.Optional[str]) -> typing.Optional[float]:
        if value_str is not None:
            calibration = self.__get_calibration()
            data_size = self.__get_data_size()
            value = Converter.FloatToStringConverter().convert_back(value_str)
            if value is not None:
                return calibration.convert_from_calibrated_size(value) / data_size / self.__factor
        return None


class CalibratedBinding(Binding.Binding):
    def __init__(self, display_item: DisplayItem.DisplayItem, value_binding: Binding.Binding, converter: Converter.ConverterLike[float, str]) -> None:
        super().__init__(None, converter=converter)
        self.__display_item = display_item
        self.__value_binding = value_binding
        self.__converter_x = converter  # mypy bug (it uses base self.__converter type if named the same)

        self.__value_binding.target_setter = ReferenceCounting.weak_partial(CalibratedBinding.__update_target, self)

        self.__calibrations_changed_event_listener = display_item.display_property_changed_event.listen(ReferenceCounting.weak_partial(CalibratedBinding.__calibrations_changed, self))

    def __update_target(self, value: typing.Any) -> None:
        self.update_target_direct(self.get_target_value())

    def __calibrations_changed(self, key: str) -> None:
        if key == "displayed_dimensional_calibrations":
            self.__update_target(self.__display_item.displayed_datum_calibrations)

    # set the model value from the target ui element text.
    def update_source(self, target_value: typing.Any) -> None:
        converted_value = self.__converter_x.convert_back(target_value)
        self.__value_binding.update_source(converted_value)

    # get the value from the model and return it as a string suitable for the target ui element.
    # in this binding, it combines the two source bindings into one.
    def get_target_value(self) -> typing.Optional[str]:
        value = self.__value_binding.get_target_value()
        return self.__converter_x.convert(value) if value is not None else None


class CalibratedValueBinding(CalibratedBinding):
    def __init__(self, index: int, display_item: DisplayItem.DisplayItem, value_binding: Binding.Binding) -> None:
        converter = CalibratedValueFloatToStringConverter(display_item, index)
        super().__init__(display_item, value_binding, converter)


class CalibratedSizeBinding(CalibratedBinding):
    def __init__(self, index: int, display_item: DisplayItem.DisplayItem, value_binding: Binding.Binding) -> None:
        converter = CalibratedSizeFloatToStringConverter(display_item, index)
        super().__init__(display_item, value_binding, converter)


class CalibratedWidthBinding(CalibratedBinding):
    def __init__(self, display_item: DisplayItem.DisplayItem, value_binding: Binding.Binding) -> None:
        display_data_shape = display_item.display_data_shape
        factor = 1.0 / (display_data_shape[0] if display_data_shape is not None else 1)
        converter = CalibratedSizeFloatToStringConverter(display_item, 0, factor)  # width is stored in pixels. argh.
        super().__init__(display_item, value_binding, converter)


class CalibratedLengthBinding(Binding.Binding):
    def __init__(self, display_item: DisplayItem.DisplayItem, start_binding: Binding.Binding, end_binding: Binding.Binding) -> None:
        super().__init__(None)
        self.__display_item = display_item
        self.__x_converter = CalibratedValueFloatToStringConverter(display_item, 1, uniform=True)
        self.__y_converter = CalibratedValueFloatToStringConverter(display_item, 0, uniform=True)
        self.__size_converter = CalibratedSizeFloatToStringConverter(display_item, 0, uniform=True)
        self.__start_binding = start_binding
        self.__end_binding = end_binding
        self.__start_binding.target_setter = ReferenceCounting.weak_partial(CalibratedLengthBinding.__update_target, self)
        self.__end_binding.target_setter = ReferenceCounting.weak_partial(CalibratedLengthBinding.__update_target, self)
        self.__calibrations_changed_event_listener = display_item.display_property_changed_event.listen(ReferenceCounting.weak_partial(CalibratedLengthBinding.__calibrations_changed, self))

    def __update_target(self, value: typing.Any) -> None:
        self.update_target_direct(self.get_target_value())

    def __calibrations_changed(self, key: str) -> None:
        if key == "displayed_dimensional_calibrations":
            self.__update_target(self.__display_item.displayed_datum_calibrations)

    # set the model value from the target ui element text.
    def update_source(self, target_value: typing.Any) -> None:
        start = self.__start_binding.get_target_value() or Geometry.FloatPoint()
        end = self.__end_binding.get_target_value() or Geometry.FloatPoint()
        calibrated_start = Geometry.FloatPoint(y=self.__y_converter.convert_to_calibrated_value(start[0]), x=self.__x_converter.convert_to_calibrated_value(start[1]))
        calibrated_end = Geometry.FloatPoint(y=self.__y_converter.convert_to_calibrated_value(end[0]), x=self.__x_converter.convert_to_calibrated_value(end[1]))
        delta = calibrated_end - calibrated_start
        angle = -math.atan2(delta.y, delta.x)
        new_calibrated_end = calibrated_start + target_value * Geometry.FloatSize(height=-math.sin(angle), width=math.cos(angle))
        end = Geometry.FloatPoint(y=self.__y_converter.convert_from_calibrated_value(new_calibrated_end.y), x=self.__x_converter.convert_from_calibrated_value(new_calibrated_end.x))
        self.__end_binding.update_source(end)

    # get the value from the model and return it as a string suitable for the target ui element.
    # in this binding, it combines the two source bindings into one.
    def get_target_value(self) -> typing.Optional[str]:
        start = self.__start_binding.get_target_value() or Geometry.FloatPoint()
        end = self.__end_binding.get_target_value() or Geometry.FloatPoint()
        calibrated_dy = self.__y_converter.convert_to_calibrated_value(end[0]) - self.__y_converter.convert_to_calibrated_value(start[0])
        calibrated_dx = self.__x_converter.convert_to_calibrated_value(end[1]) - self.__x_converter.convert_to_calibrated_value(start[1])
        calibrated_value = math.sqrt(calibrated_dx * calibrated_dx + calibrated_dy * calibrated_dy)
        return self.__size_converter.convert_calibrated_value_to_str(calibrated_value)


class CalibratedAngleBinding(Binding.Binding):
    def __init__(self, display_item: DisplayItem.DisplayItem, start_binding: Binding.Binding, end_binding: Binding.Binding) -> None:
        super().__init__(None)
        self.__display_item = display_item
        self.__x_converter = CalibratedValueFloatToStringConverter(display_item, 1, uniform=True)
        self.__y_converter = CalibratedValueFloatToStringConverter(display_item, 0, uniform=True)
        self.__size_converter = CalibratedSizeFloatToStringConverter(display_item, 0, uniform=True)
        self.__start_binding = start_binding
        self.__end_binding = end_binding
        self.__start_binding.target_setter = ReferenceCounting.weak_partial(CalibratedAngleBinding.__update_target, self)
        self.__end_binding.target_setter = ReferenceCounting.weak_partial(CalibratedAngleBinding.__update_target, self)
        self.__calibrations_changed_event_listener = display_item.display_property_changed_event.listen(ReferenceCounting.weak_partial(CalibratedAngleBinding.__calibrations_changed, self))

    def __update_target(self, value: typing.Any) -> None:
        self.update_target_direct(self.get_target_value())

    def __calibrations_changed(self, key: str) -> None:
        if key == "displayed_dimensional_calibrations":
            self.__update_target(self.__display_item.displayed_datum_calibrations)

    # set the model value from the target ui element text.
    def update_source(self, target_value: typing.Any) -> None:
        start = self.__start_binding.get_target_value() or Geometry.FloatPoint()
        end = self.__end_binding.get_target_value() or Geometry.FloatPoint()
        calibrated_start = Geometry.FloatPoint(y=self.__y_converter.convert_to_calibrated_value(start[0]),
                                               x=self.__x_converter.convert_to_calibrated_value(start[1]))
        calibrated_dy = self.__y_converter.convert_to_calibrated_value(end[0]) - self.__y_converter.convert_to_calibrated_value(start[0])
        calibrated_dx = self.__x_converter.convert_to_calibrated_value(end[1]) - self.__x_converter.convert_to_calibrated_value(start[1])
        length = math.sqrt(calibrated_dy * calibrated_dy + calibrated_dx * calibrated_dx)
        angle = RadianToDegreeStringConverter().convert_back(target_value) or 0.0
        new_calibrated_end = calibrated_start + length * Geometry.FloatSize(height=-math.sin(angle), width=math.cos(angle))
        end = Geometry.FloatPoint(y=self.__y_converter.convert_from_calibrated_value(new_calibrated_end.y),
                                  x=self.__x_converter.convert_from_calibrated_value(new_calibrated_end.x))
        self.__end_binding.update_source(end)

    # get the value from the model and return it as a string suitable for the target ui element.
    # in this binding, it combines the two source bindings into one.
    def get_target_value(self) -> typing.Optional[str]:
        start = self.__start_binding.get_target_value() or Geometry.FloatPoint()
        end = self.__end_binding.get_target_value() or Geometry.FloatPoint()
        calibrated_dy = self.__y_converter.convert_to_calibrated_value(end[0]) - self.__y_converter.convert_to_calibrated_value(start[0])
        calibrated_dx = self.__x_converter.convert_to_calibrated_value(end[1]) - self.__x_converter.convert_to_calibrated_value(start[1])
        return RadianToDegreeStringConverter().convert(-math.atan2(calibrated_dy, calibrated_dx))


def make_point_type_inspector(document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, graphic: Graphics.Graphic) -> InspectorSectionWidget:
    ui = document_controller.ui
    graphic_widget = InspectorSectionWidget(ui)
    # create the ui
    graphic_position_row = ui.create_row_widget()
    graphic_position_row.add_spacing(20)
    graphic_position_x_row = ui.create_row_widget()
    graphic_position_x_row.add(ui.create_label_widget(_("X"), properties={"width": 26}))
    graphic_position_x_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_position_x_line_edit.widget_id = "x"
    graphic_position_x_row.add(graphic_position_x_line_edit)
    graphic_position_y_row = ui.create_row_widget()
    graphic_position_y_row.add(ui.create_label_widget(_("Y"), properties={"width": 26}))
    graphic_position_y_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_position_y_line_edit.widget_id = "y"
    graphic_position_y_row.add(graphic_position_y_line_edit)
    graphic_position_row.add(graphic_position_x_row)
    graphic_position_row.add_spacing(8)
    graphic_position_row.add(graphic_position_y_row)
    graphic_position_row.add_stretch()
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_position_row)
    graphic_widget.add_spacing(4)

    position_model = GraphicPropertyCommandModel(document_controller, display_item, graphic, "position", title=_("Change Position"), command_id="change_point_position")

    display_data_shape = display_item.display_data_shape if display_item else None
    if display_data_shape and len(display_data_shape) > 1:
        # calculate values from rectangle type graphic
        # signal_index
        position_x_binding = CalibratedValueBinding(1, display_item, Binding.TuplePropertyBinding(position_model, "value", 1))
        position_y_binding = CalibratedValueBinding(0, display_item, Binding.TuplePropertyBinding(position_model, "value", 0))
        graphic_position_x_line_edit.bind_text(position_x_binding)
        graphic_position_y_line_edit.bind_text(position_y_binding)
    else:
        graphic_position_x_line_edit.bind_text(Binding.TuplePropertyBinding(position_model, "value", 1))
        graphic_position_y_line_edit.bind_text(Binding.TuplePropertyBinding(position_model, "value", 0))

    graphic_widget.add_unbinder([display_item, graphic], [graphic_position_x_line_edit.unbind_text, graphic_position_y_line_edit.unbind_text])

    graphic_widget.add_closeable(position_model)

    return graphic_widget


def make_line_type_inspector(document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, graphic: Graphics.Graphic) -> InspectorSectionWidget:
    ui = document_controller.ui
    graphic_widget = InspectorSectionWidget(ui)
    graphic_widget.content_widget.widget_id = "line_type_inspector"
    # create the ui
    graphic_start_row = ui.create_row_widget()
    graphic_start_row.add_spacing(20)
    graphic_start_x_row = ui.create_row_widget()
    graphic_start_x_row.add(ui.create_label_widget(_("X0"), properties={"width": 26}))
    graphic_start_x_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_start_x_line_edit.widget_id = "x0"
    graphic_start_x_row.add(graphic_start_x_line_edit)
    graphic_start_y_row = ui.create_row_widget()
    graphic_start_y_row.add(ui.create_label_widget(_("Y0"), properties={"width": 26}))
    graphic_start_y_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_start_y_line_edit.widget_id = "y0"
    graphic_start_y_row.add(graphic_start_y_line_edit)
    graphic_start_row.add(graphic_start_x_row)
    graphic_start_row.add_spacing(8)
    graphic_start_row.add(graphic_start_y_row)
    graphic_start_row.add_stretch()
    graphic_end_row = ui.create_row_widget()
    graphic_end_row.add_spacing(20)
    graphic_end_x_row = ui.create_row_widget()
    graphic_end_x_row.add(ui.create_label_widget(_("X1"), properties={"width": 26}))
    graphic_end_x_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_end_x_line_edit.widget_id = "x1"
    graphic_end_x_row.add(graphic_end_x_line_edit)
    graphic_end_y_row = ui.create_row_widget()
    graphic_end_y_row.add(ui.create_label_widget(_("Y1"), properties={"width": 26}))
    graphic_end_y_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_end_y_line_edit.widget_id = "y1"
    graphic_end_y_row.add(graphic_end_y_line_edit)
    graphic_end_row.add(graphic_end_x_row)
    graphic_end_row.add_spacing(8)
    graphic_end_row.add(graphic_end_y_row)
    graphic_end_row.add_stretch()
    graphic_param_row = ui.create_row_widget()
    graphic_param_row.add_spacing(20)
    graphic_param_l_row = ui.create_row_widget()
    graphic_param_l_row.add(ui.create_label_widget(_("L"), properties={"width": 26}))
    graphic_param_l_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_param_l_line_edit.widget_id = "length"
    graphic_param_l_row.add(graphic_param_l_line_edit)
    graphic_param_a_row = ui.create_row_widget()
    graphic_param_a_row.add(ui.create_label_widget(_("A"), properties={"width": 26}))
    graphic_param_a_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_param_a_line_edit.widget_id = "angle"
    graphic_param_a_row.add(graphic_param_a_line_edit)
    graphic_param_row.add(graphic_param_l_row)
    graphic_param_row.add_spacing(8)
    graphic_param_row.add(graphic_param_a_row)
    graphic_param_row.add_stretch()
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_start_row)
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_end_row)
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_param_row)
    graphic_widget.add_spacing(4)

    start_model = GraphicPropertyCommandModel(document_controller, display_item, graphic, "start", title=_("Change Line Start"), command_id="change_line_start")

    end_model = GraphicPropertyCommandModel(document_controller, display_item, graphic, "end", title=_("Change Line End"), command_id="change_line_end")

    display_data_shape = display_item.display_data_shape if display_item else None
    if display_data_shape and len(display_data_shape) > 1:
        # configure the bindings
        # signal_index
        start_x_binding = CalibratedValueBinding(1, display_item, Binding.TuplePropertyBinding(start_model, "value", 1))
        start_y_binding = CalibratedValueBinding(0, display_item, Binding.TuplePropertyBinding(start_model, "value", 0))
        end_x_binding = CalibratedValueBinding(1, display_item, Binding.TuplePropertyBinding(end_model, "value", 1))
        end_y_binding = CalibratedValueBinding(0, display_item, Binding.TuplePropertyBinding(end_model, "value", 0))
        length_binding = CalibratedLengthBinding(display_item, ChangeGraphicPropertyBinding(document_controller, display_item, graphic, "start"), ChangeGraphicPropertyBinding(document_controller, display_item, graphic, "end"))
        angle_binding = CalibratedAngleBinding(display_item, ChangeGraphicPropertyBinding(document_controller, display_item, graphic, "start"), ChangeGraphicPropertyBinding(document_controller, display_item, graphic, "end"))
        graphic_start_x_line_edit.bind_text(start_x_binding)
        graphic_start_y_line_edit.bind_text(start_y_binding)
        graphic_end_x_line_edit.bind_text(end_x_binding)
        graphic_end_y_line_edit.bind_text(end_y_binding)
        graphic_param_l_line_edit.bind_text(length_binding)
        graphic_param_a_line_edit.bind_text(angle_binding)
    else:
        graphic_start_x_line_edit.bind_text(Binding.TuplePropertyBinding(start_model, "value", 1))
        graphic_start_y_line_edit.bind_text(Binding.TuplePropertyBinding(start_model, "value", 0))
        graphic_end_x_line_edit.bind_text(Binding.TuplePropertyBinding(end_model, "value", 1))
        graphic_end_y_line_edit.bind_text(Binding.TuplePropertyBinding(end_model, "value", 0))
        graphic_param_l_line_edit.bind_text(ChangeGraphicPropertyBinding(document_controller, display_item, graphic, "length"))
        graphic_param_a_line_edit.bind_text(ChangeGraphicPropertyBinding(document_controller, display_item, graphic, "angle", RadianToDegreeStringConverter()))

    graphic_widget.add_unbinder([display_item, graphic], [graphic_start_x_line_edit.unbind_text, graphic_start_y_line_edit.unbind_text, graphic_end_x_line_edit.unbind_text, graphic_end_y_line_edit.unbind_text, graphic_param_l_line_edit.unbind_text, graphic_param_a_line_edit.unbind_text])

    graphic_widget.add_closeables(start_model, end_model)

    return graphic_widget


def make_line_profile_inspector(document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, graphic: Graphics.Graphic) -> InspectorSectionWidget:
    graphic_widget = make_line_type_inspector(document_controller, display_item, graphic)

    ui = document_controller.ui
    # configure the bindings
    width_binding = CalibratedWidthBinding(display_item, ChangeGraphicPropertyBinding(document_controller, display_item, graphic, "width"))
    # create the ui
    graphic_width_row = ui.create_row_widget()
    graphic_width_row.add_spacing(20)
    graphic_width_row.add(ui.create_label_widget(_("Width"), properties={"width": 52}))
    graphic_width_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_width_line_edit.widget_id = "width"
    graphic_width_line_edit.bind_text(width_binding)
    graphic_width_row.add(graphic_width_line_edit)
    graphic_width_row.add_stretch()
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_width_row)
    graphic_widget.add_spacing(4)

    graphic_widget.add_unbinder([display_item, graphic], [graphic_width_line_edit.unbind_text])

    return graphic_widget


def make_rectangle_type_inspector(document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, graphic: Graphics.Graphic, graphic_name: str, rotation: bool = False) -> InspectorSectionWidget:
    ui = document_controller.ui
    graphic_widget = InspectorSectionWidget(ui)
    graphic_widget.content_widget.widget_id = "rectangle_type_inspector"
    # create the ui
    graphic_center_row = ui.create_row_widget()
    graphic_center_row.add_spacing(20)
    graphic_center_x_row = ui.create_row_widget()
    graphic_center_x_row.add(ui.create_label_widget(_("X"), properties={"width": 26}))
    graphic_center_x_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_center_x_line_edit.widget_id = "x"
    graphic_center_x_row.add(graphic_center_x_line_edit)
    graphic_center_y_row = ui.create_row_widget()
    graphic_center_y_row.add(ui.create_label_widget(_("Y"), properties={"width": 26}))
    graphic_center_y_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_center_y_line_edit.widget_id = "y"
    graphic_center_y_row.add(graphic_center_y_line_edit)
    graphic_center_row.add(graphic_center_x_row)
    graphic_center_row.add_spacing(8)
    graphic_center_row.add(graphic_center_y_row)
    graphic_center_row.add_stretch()
    graphic_size_row = ui.create_row_widget()
    graphic_size_row.add_spacing(20)
    graphic_center_w_row = ui.create_row_widget()
    graphic_center_w_row.add(ui.create_label_widget(_("W"), properties={"width": 26}))
    graphic_size_width_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_size_width_line_edit.widget_id = "width"
    graphic_center_w_row.add(graphic_size_width_line_edit)
    graphic_center_h_row = ui.create_row_widget()
    graphic_center_h_row.add(ui.create_label_widget(_("H"), properties={"width": 26}))
    graphic_size_height_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_size_height_line_edit.widget_id = "height"
    graphic_center_h_row.add(graphic_size_height_line_edit)
    graphic_size_row.add(graphic_center_w_row)
    graphic_size_row.add_spacing(8)
    graphic_size_row.add(graphic_center_h_row)
    graphic_size_row.add_stretch()
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_center_row)
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_size_row)
    graphic_widget.add_spacing(4)

    center_model = GraphicPropertyCommandModel(document_controller, display_item, graphic, "center", title=_("Change {} Center").format(graphic_name), command_id="change_" + graphic_name + "_center")

    size_model = GraphicPropertyCommandModel(document_controller, display_item, graphic, "size", title=_("Change {} Size").format(graphic_name), command_id="change_" + graphic_name + "_size")

    # calculate values from rectangle type graphic
    display_data_shape = display_item.display_data_shape if display_item else None
    if display_data_shape and len(display_data_shape) > 1:
        # signal_index
        center_x_binding = CalibratedValueBinding(1, display_item, Binding.TuplePropertyBinding(center_model, "value", 1))
        center_y_binding = CalibratedValueBinding(0, display_item, Binding.TuplePropertyBinding(center_model, "value", 0))
        size_width_binding = CalibratedSizeBinding(1, display_item, Binding.TuplePropertyBinding(size_model, "value", 1))
        size_height_binding = CalibratedSizeBinding(0, display_item, Binding.TuplePropertyBinding(size_model, "value", 0))
        graphic_center_x_line_edit.bind_text(center_x_binding)
        graphic_center_y_line_edit.bind_text(center_y_binding)
        graphic_size_width_line_edit.bind_text(size_width_binding)
        graphic_size_height_line_edit.bind_text(size_height_binding)
    else:
        graphic_center_x_line_edit.bind_text(Binding.TuplePropertyBinding(center_model, "value", 1))
        graphic_center_y_line_edit.bind_text(Binding.TuplePropertyBinding(center_model, "value", 0))
        graphic_size_width_line_edit.bind_text(Binding.TuplePropertyBinding(size_model, "value", 1))
        graphic_size_height_line_edit.bind_text(Binding.TuplePropertyBinding(size_model, "value", 0))

    graphic_widget.add_unbinder([display_item, graphic], [graphic_center_x_line_edit.unbind_text, graphic_center_y_line_edit.unbind_text, graphic_size_width_line_edit.unbind_text, graphic_size_height_line_edit.unbind_text])

    graphic_widget.add_closeables(center_model, size_model)

    if rotation:
        rotation_row = ui.create_row_widget()
        rotation_row.add_spacing(20)

        rotation_line_edit = ui.create_line_edit_widget(properties={"width": 98})
        rotation_line_edit.widget_id = "rotation"

        rotation_row2 = ui.create_row_widget()
        rotation_row2.add(ui.create_label_widget(_("Rotation (deg)")))
        rotation_row2.add_spacing(8)
        rotation_row2.add(rotation_line_edit)

        rotation_row.add(rotation_row2)
        rotation_row.add_stretch()

        graphic_widget.add(rotation_row)
        graphic_widget.add_spacing(4)

        rotation_model = GraphicPropertyCommandModel(document_controller, display_item, graphic, "rotation", title=_("Change {} Rotation").format(graphic_name), command_id="change_" + graphic_name + "_size")
        rotation_line_edit.bind_text(Binding.PropertyBinding(rotation_model, "value", converter=RadianToDegreeStringConverter()))

        graphic_widget.add_unbinder([display_item, graphic], [rotation_line_edit.unbind_text])

        graphic_widget.add_closeable(rotation_model)

    return graphic_widget


def make_spot_inspector(document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, graphic: Graphics.Graphic, graphic_name: str) -> InspectorSectionWidget:
    ui = document_controller.ui
    graphic_widget = InspectorSectionWidget(ui)
    graphic_widget.content_widget.widget_id = "spot_inspector"
    # create the ui
    graphic_center_row = ui.create_row_widget()
    graphic_center_row.add_spacing(20)
    graphic_center_x_row = ui.create_row_widget()
    graphic_center_x_row.add(ui.create_label_widget(_("X"), properties={"width": 26}))
    graphic_center_x_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_center_x_line_edit.widget_id = "x"
    graphic_center_x_row.add(graphic_center_x_line_edit)
    graphic_center_y_row = ui.create_row_widget()
    graphic_center_y_row.add(ui.create_label_widget(_("Y"), properties={"width": 26}))
    graphic_center_y_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_center_y_line_edit.widget_id = "y"
    graphic_center_y_row.add(graphic_center_y_line_edit)
    graphic_center_row.add(graphic_center_x_row)
    graphic_center_row.add_spacing(8)
    graphic_center_row.add(graphic_center_y_row)
    graphic_center_row.add_stretch()
    graphic_size_row = ui.create_row_widget()
    graphic_size_row.add_spacing(20)
    graphic_center_w_row = ui.create_row_widget()
    graphic_center_w_row.add(ui.create_label_widget(_("W"), properties={"width": 26}))
    graphic_size_width_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_size_width_line_edit.widget_id = "width"
    graphic_center_w_row.add(graphic_size_width_line_edit)
    graphic_center_h_row = ui.create_row_widget()
    graphic_center_h_row.add(ui.create_label_widget(_("H"), properties={"width": 26}))
    graphic_size_height_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_size_height_line_edit.widget_id = "height"
    graphic_center_h_row.add(graphic_size_height_line_edit)
    graphic_size_row.add(graphic_center_w_row)
    graphic_size_row.add_spacing(8)
    graphic_size_row.add(graphic_center_h_row)
    graphic_size_row.add_stretch()
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_center_row)
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_size_row)
    graphic_widget.add_spacing(4)

    center_model = GraphicPropertyCommandModel(document_controller, display_item, graphic, "center", title=_("Change {} Center").format(graphic_name), command_id="change_" + graphic_name + "_center")

    size_model = GraphicPropertyCommandModel(document_controller, display_item, graphic, "size", title=_("Change {} Size").format(graphic_name), command_id="change_" + graphic_name + "_size")

    # calculate values from rectangle type graphic
    display_data_shape = display_item.display_data_shape if display_item else None
    if display_data_shape and len(display_data_shape) > 1:
        # signal_index
        center_x_binding = CalibratedSizeBinding(1, display_item, Binding.TuplePropertyBinding(center_model, "value", 1))
        center_y_binding = CalibratedSizeBinding(0, display_item, Binding.TuplePropertyBinding(center_model, "value", 0))
        size_width_binding = CalibratedSizeBinding(1, display_item, Binding.TuplePropertyBinding(size_model, "value", 1))
        size_height_binding = CalibratedSizeBinding(0, display_item, Binding.TuplePropertyBinding(size_model, "value", 0))
        graphic_center_x_line_edit.bind_text(center_x_binding)
        graphic_center_y_line_edit.bind_text(center_y_binding)
        graphic_size_width_line_edit.bind_text(size_width_binding)
        graphic_size_height_line_edit.bind_text(size_height_binding)
    else:
        graphic_center_x_line_edit.bind_text(Binding.TuplePropertyBinding(center_model, "value", 1))
        graphic_center_y_line_edit.bind_text(Binding.TuplePropertyBinding(center_model, "value", 0))
        graphic_size_width_line_edit.bind_text(Binding.TuplePropertyBinding(size_model, "value", 1))
        graphic_size_height_line_edit.bind_text(Binding.TuplePropertyBinding(size_model, "value", 0))

    graphic_widget.add_unbinder([display_item, graphic], [graphic_center_x_line_edit.unbind_text, graphic_center_y_line_edit.unbind_text, graphic_size_width_line_edit.unbind_text, graphic_size_height_line_edit.unbind_text])

    graphic_widget.add_closeables(center_model, size_model)

    rotation_row = ui.create_row_widget()
    rotation_row.add_spacing(20)

    rotation_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    rotation_line_edit.widget_id = "rotation"

    rotation_row2 = ui.create_row_widget()
    rotation_row2.add(ui.create_label_widget(_("Rotation (deg)")))
    rotation_row2.add_spacing(8)
    rotation_row2.add(rotation_line_edit)

    rotation_row.add(rotation_row2)
    rotation_row.add_stretch()

    graphic_widget.add(rotation_row)
    graphic_widget.add_spacing(4)

    rotation_model = GraphicPropertyCommandModel(document_controller, display_item, graphic, "rotation", title=_("Change {} Rotation").format(graphic_name), command_id="change_" + graphic_name + "_size")
    rotation_line_edit.bind_text(Binding.PropertyBinding(rotation_model, "value", converter=RadianToDegreeStringConverter()))

    graphic_widget.add_unbinder([display_item, graphic], [rotation_line_edit.unbind_text])

    graphic_widget.add_closeable(rotation_model)

    return graphic_widget


def make_wedge_inspector(document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, graphic: Graphics.WedgeGraphic) -> InspectorSectionWidget:
    ui = document_controller.ui
    graphic_widget = InspectorSectionWidget(ui)
    graphic_widget.content_widget.widget_id = "wedge_inspector"
    # create the ui
    graphic_center_start_angle_row = ui.create_row_widget()
    graphic_center_start_angle_row.add_spacing(20)
    graphic_center_start_angle_row.add(ui.create_label_widget(_("Start Angle"), properties={"width": 60}))
    graphic_center_start_angle_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_center_start_angle_row.add(graphic_center_start_angle_line_edit)
    graphic_center_start_angle_row.add_stretch()
    graphic_center_end_angle_row = ui.create_row_widget()
    graphic_center_end_angle_row.add_spacing(20)
    graphic_center_end_angle_row.add(ui.create_label_widget(_("End Angle"), properties={"width": 60}))
    graphic_center_angle_measure_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_center_end_angle_row.add(graphic_center_angle_measure_line_edit)
    graphic_center_end_angle_row.add_stretch()
    graphic_widget.add(graphic_center_start_angle_row)
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_center_end_angle_row)
    graphic_widget.add_spacing(4)

    angle_interval_model = GraphicPropertyCommandModel(document_controller, display_item, graphic, "angle_interval", title=_("Change Angle Interval"), command_id="change_angle_interval")

    graphic_center_start_angle_line_edit.bind_text(Binding.TuplePropertyBinding(angle_interval_model, "value", 0, converter=RadianToDegreeStringConverter()))
    graphic_center_angle_measure_line_edit.bind_text(Binding.TuplePropertyBinding(angle_interval_model, "value", 1, converter=RadianToDegreeStringConverter()))

    graphic_widget.add_unbinder([display_item, graphic], [graphic_center_start_angle_line_edit.unbind_text, graphic_center_angle_measure_line_edit.unbind_text])

    graphic_widget.add_closeable(angle_interval_model)

    return graphic_widget


def make_annular_ring_mode_chooser(document_controller: DocumentController.DocumentController, graphic_widget: InspectorSectionWidget, display_item: DisplayItem.DisplayItem, graphic: Graphics.Graphic) -> UserInterface.ComboBoxWidget:
    ui = document_controller.ui
    annular_ring_mode_options = ((_("Band Pass"), "band-pass"), (_("Low Pass"), "low-pass"), (_("High Pass"), "high-pass"))
    annular_ring_mode_reverse_map = {"band-pass": 0, "low-pass": 1, "high-pass": 2}

    class AnnularRingModeIndexConverter(Converter.ConverterLike[str, int]):
        """Convert from flag index (-1, 0, 1) to chooser index."""
        def convert(self, value: typing.Optional[str]) -> typing.Optional[int]:
            return annular_ring_mode_reverse_map.get(value or str(), 0)

        def convert_back(self, value: typing.Optional[int]) -> typing.Optional[str]:
            if value is not None and value >= 0 and value < len(annular_ring_mode_options):
                return annular_ring_mode_options[value][1]
            else:
                return "band-pass"

    display_calibration_style_chooser = ui.create_combo_box_widget(items=annular_ring_mode_options, item_getter=operator.itemgetter(0))
    display_calibration_style_chooser.bind_current_index(ChangeGraphicPropertyBinding(document_controller, display_item, graphic, "mode", converter=AnnularRingModeIndexConverter(), fallback=0))

    graphic_widget.add_unbinder([display_item, graphic], [display_calibration_style_chooser.unbind_current_index])

    return display_calibration_style_chooser


def make_ring_inspector(document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, graphic: Graphics.Graphic) -> InspectorSectionWidget:
    ui = document_controller.ui
    graphic_widget = InspectorSectionWidget(ui)

    graphic_widget.content_widget.widget_id = "ring_inspector"

    # create the ui
    graphic_radius_1_row = ui.create_row_widget()
    graphic_radius_1_row.add_spacing(20)
    graphic_radius_1_row.add(ui.create_label_widget(_("Radius 1"), properties={"width": 60}))
    graphic_radius_1_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_radius_1_row.add(graphic_radius_1_line_edit)
    graphic_radius_1_row.add_stretch()
    graphic_radius_2_row = ui.create_row_widget()
    graphic_radius_2_row.add_spacing(20)
    graphic_radius_2_row.add(ui.create_label_widget(_("Radius 2"), properties={"width": 60}))
    graphic_radius_2_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_radius_2_row.add(graphic_radius_2_line_edit)
    graphic_radius_2_row.add_stretch()
    ring_mode_row = ui.create_row_widget()
    ring_mode_row.add_spacing(20)
    ring_mode_row.add(ui.create_label_widget(_("Mode"), properties={"width": 60}))
    chooser = make_annular_ring_mode_chooser(document_controller, graphic_widget, display_item, graphic)
    ring_mode_row.add(chooser)
    ring_mode_row.add_stretch()

    graphic_widget.add(graphic_radius_1_row)
    graphic_widget.add(graphic_radius_2_row)
    graphic_widget.add(ring_mode_row)

    graphic_radius_1_line_edit.bind_text(CalibratedSizeBinding(0, display_item, ChangeGraphicPropertyBinding(document_controller, display_item, graphic, "radius_1")))
    graphic_radius_2_line_edit.bind_text(CalibratedSizeBinding(0, display_item, ChangeGraphicPropertyBinding(document_controller, display_item, graphic, "radius_2")))

    graphic_widget.add_unbinder([display_item, graphic], [graphic_radius_1_line_edit.unbind_text, graphic_radius_2_line_edit.unbind_text])

    return graphic_widget


def make_interval_type_inspector(document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, graphic: Graphics.Graphic) -> InspectorSectionWidget:
    ui = document_controller.ui
    graphic_widget = InspectorSectionWidget(ui)
    # configure the bindings
    start_binding = CalibratedValueBinding(-1, display_item, ChangeGraphicPropertyBinding(document_controller, display_item, graphic, "start"))
    end_binding = CalibratedValueBinding(-1, display_item, ChangeGraphicPropertyBinding(document_controller, display_item, graphic, "end"))
    # create the ui
    graphic_start_row = ui.create_row_widget()
    graphic_start_row.add_spacing(20)
    graphic_start_row.add(ui.create_label_widget(_("Start"), properties={"width": 52}))
    graphic_start_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_start_line_edit.widget_id = "start"
    graphic_start_line_edit.bind_text(start_binding)
    graphic_start_row.add(graphic_start_line_edit)
    graphic_start_row.add_stretch()
    graphic_end_row = ui.create_row_widget()
    graphic_end_row.add_spacing(20)
    graphic_end_row.add(ui.create_label_widget(_("End"), properties={"width": 52}))
    graphic_end_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_end_line_edit.widget_id = "end"
    graphic_end_line_edit.bind_text(end_binding)
    graphic_end_row.add(graphic_end_line_edit)
    graphic_end_row.add_stretch()
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_start_row)
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_end_row)
    graphic_widget.add_spacing(4)

    graphic_widget.add_unbinder([display_item, graphic], [graphic_start_line_edit.unbind_text, graphic_end_line_edit.unbind_text])

    return graphic_widget


class GraphicsInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement graphics inspector.
        """

    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, selected_only: bool = False) -> None:
        super().__init__(document_controller.ui, "graphics", _("Graphics"))
        ui = document_controller.ui
        self.__document_controller = document_controller
        self.__display_item = display_item
        self.__graphics = display_item.graphics
        # ui
        header_widget = self.__create_header_widget()
        header_for_empty_list_widget = self.__create_header_for_empty_list_widget()
        # create the widgets for each graphic
        list_widget = Widgets.TableWidget(ui, lambda item: self.__create_list_item_widget(item), header_widget, header_for_empty_list_widget)
        graphics = getattr(display_item, "selected_graphics" if selected_only else "graphics")
        for index, graphic in enumerate(graphics):
            list_widget.insert_item(graphic, index)
        self.add_widget_to_content(list_widget)
        # create the display calibrations check box row
        display_calibrations_row = self.ui.create_row_widget()
        display_calibrations_row.add(self.ui.create_label_widget(_("Display"), properties={"width": 60}))
        display_calibrations_row.add(make_calibration_style_chooser(document_controller, self.__display_item))
        display_calibrations_row.add_stretch()
        self.add_widget_to_content(display_calibrations_row)
        self.finish_widget_content()
        # add unbinders
        self._unbinder.add([display_item], [])

    def __create_header_widget(self) -> UserInterface.BoxWidget:
        return self.ui.create_row_widget()

    def __create_header_for_empty_list_widget(self) -> UserInterface.BoxWidget:
        return self.ui.create_row_widget()

    # not thread safe
    def __create_list_item_widget(self, graphic: Graphics.Graphic) -> UserInterface.BoxWidget:
        # NOTE: it is not valid to access self.__graphics here. graphic may or may not be in that list due to threading.
        # graphic_section_index = self.__graphics.index(graphic)
        graphic_widget = self.ui.create_column_widget()
        # create the title row
        title_row = self.ui.create_row_widget()
        graphic_type_label = self.ui.create_label_widget(properties={"width": 100})
        label_line_edit = self.ui.create_line_edit_widget()
        label_line_edit.placeholder_text = _("None")
        label_line_edit.bind_text(Binding.PropertyBinding(graphic, "label"))
        title_row.add(graphic_type_label)
        title_row.add_spacing(8)
        title_row.add(label_line_edit)
        title_row.add_stretch()
        graphic_widget.add(title_row)
        graphic_widget.add_spacing(4)
        self._unbinder.add([graphic], [label_line_edit.unbind_text])
        section_widget: typing.Optional[InspectorSectionWidget] = None
        # create the graphic specific widget
        if isinstance(graphic, Graphics.PointGraphic):
            graphic_type_label.text = _("Point")
            section_widget = make_point_type_inspector(self.__document_controller, self.__display_item, graphic)
            graphic_widget.add(section_widget)
        elif isinstance(graphic, Graphics.LineProfileGraphic):
            graphic_type_label.text = _("Line Profile")
            section_widget = make_line_profile_inspector(self.__document_controller, self.__display_item, graphic)
            graphic_widget.add(section_widget)
        elif isinstance(graphic, Graphics.LineGraphic):
            graphic_type_label.text = _("Line")
            section_widget = make_line_type_inspector(self.__document_controller, self.__display_item, graphic)
            graphic_widget.add(section_widget)
        elif isinstance(graphic, Graphics.RectangleGraphic):
            graphic_type_label.text = _("Rectangle")
            section_widget = make_rectangle_type_inspector(self.__document_controller, self.__display_item, graphic, graphic_type_label.text, rotation=True)
            graphic_widget.add(section_widget)
        elif isinstance(graphic, Graphics.EllipseGraphic):
            graphic_type_label.text = _("Ellipse")
            section_widget = make_rectangle_type_inspector(self.__document_controller, self.__display_item, graphic, graphic_type_label.text, rotation=True)
            graphic_widget.add(section_widget)
        elif isinstance(graphic, Graphics.IntervalGraphic):
            graphic_type_label.text = _("Interval")
            section_widget = make_interval_type_inspector(self.__document_controller, self.__display_item, graphic)
            graphic_widget.add(section_widget)
        elif isinstance(graphic, Graphics.SpotGraphic):
            graphic_type_label.text = _("Spot")
            section_widget = make_spot_inspector(self.__document_controller, self.__display_item, graphic, graphic_type_label.text)
            graphic_widget.add(section_widget)
        elif isinstance(graphic, Graphics.WedgeGraphic):
            graphic_type_label.text = _("Wedge")
            section_widget = make_wedge_inspector(self.__document_controller, self.__display_item, graphic)
            graphic_widget.add(section_widget)
        elif isinstance(graphic, Graphics.RingGraphic):
            graphic_type_label.text = _("Annular Ring")
            section_widget = make_ring_inspector(self.__document_controller, self.__display_item, graphic)
            graphic_widget.add(section_widget)

        # locked row
        if section_widget:
            graphic_type_str = graphic_type_label.text or "graphic"
            lock_position_check_box = self.ui.create_check_box_widget(_("Position"))
            lock_shape_check_box = self.ui.create_check_box_widget(_("Shape"))
            lock_position_model = GraphicPropertyCommandModel(self.__document_controller, self.__display_item, graphic, "is_position_locked", title=_("Change {} Position Locked").format(graphic_type_str), command_id="change_" + graphic_type_str + "_position_locked")
            lock_shape_model = GraphicPropertyCommandModel(self.__document_controller, self.__display_item, graphic, "is_shape_locked", title=_("Change {} Shape Locked").format(graphic_type_str), command_id="change_" + graphic_type_str + "_shape_locked")
            lock_position_check_box.bind_checked(Binding.PropertyBinding(lock_position_model, "value"))
            lock_shape_check_box.bind_checked(Binding.PropertyBinding(lock_shape_model, "value"))
            self._unbinder.add([graphic], [lock_position_check_box.unbind_checked, lock_shape_check_box.unbind_checked])
            section_widget.add_closeable(lock_position_model)
            section_widget.add_closeable(lock_shape_model)
            locked_row = self.ui.create_row_widget()
            locked_row.add(self.ui.create_label_widget(_("Lock"), properties={"width": 60}))
            locked_row.add(lock_position_check_box)
            locked_row.add_spacing(12)
            locked_row.add(lock_shape_check_box)
            locked_row.add_stretch()

            def move_to_center_clicked() -> None:
                action_context = self.__document_controller._get_action_context()
                self.__document_controller.perform_action_in_context("display_panel.center_graphics", action_context)

            canvas_item = CanvasItem.TextButtonCanvasItem("\N{BULLSEYE}")
            canvas_item.text_font = "normal 13px serif"
            canvas_item.size_to_content(self.ui.get_font_metrics)
            canvas_item.on_button_clicked = move_to_center_clicked
            move_to_center_widget = self.ui.create_canvas_widget(properties={"height": canvas_item.sizing.preferred_height, "width": canvas_item.sizing.preferred_width})
            move_to_center_widget.canvas_item.add_canvas_item(canvas_item)
            move_to_center_widget.tool_tip = _("Move to Center")
            locked_row.add(move_to_center_widget)
            locked_row.add_spacing(8)

            graphic_widget.add(locked_row)

        column = self.ui.create_column_widget()
        column.add_spacing(4)
        column.add(graphic_widget)
        return column


# boolean (label)
# integer, slider (label, minimum, maximum)
# float, slider (label, minimum, maximum)
# integer, field (label, minimum, maximum)
# float, field (label, minimum, maximum, significant digits)
# complex, fields (label, significant digits)
# float, angle
# color, control
# choices, combo box
# point, region
# vector, region
# interval, region
# rectangle, region
# string, field
# float, distance
# float, duration (units)
# image


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

    def perform(self) -> None:
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
        self.slider_converter = Converter.FloatToScaledIntegerConverter(2000, 0, 100)
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
        combo_box = u.create_combo_box(items=["None", "Mapped"], current_index="@binding(combo_box_index)")
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
        u = Declarative.DeclarativeUI()
        label = u.create_label(text="@binding(variable.display_label)")
        data_source_chooser = {
            "type": "data_source_chooser",
            "display_item": "@binding(display_item)",
            "on_drop_mime_data": "drop_mime_data",
            "on_delete": "data_item_delete",
            "min_width": 80,
            "min_height": 80,
        }
        self.ui_view = u.create_column(label, data_source_chooser, spacing=8)
        self.__property_changed_listener = variable.property_changed_event.listen(self.__property_changed)

    def close(self) -> None:
        self.__property_changed_listener = typing.cast(typing.Any, None)
        super().close()

    def __property_changed(self, property_name: str) -> None:
        if property_name in ("specified_object", "secondary_specified_object"):
            self.property_changed_event.fire("display_item")

    @property
    def display_item(self) -> typing.Optional[DisplayItem.DisplayItem]:
        document_model = self.document_controller.document_model
        computation = self.computation
        variable = self.variable
        base_items = computation.get_variable_input_items(variable.name)
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
                property_model = GraphicPropertyCommandModel(self.document_controller, display_item, graphic, "center", title=_("Change {} Center").format(graphic_name), command_id="change_" + graphic_name + "_center")
                return CalibratedValueBinding(index, display_item, ClosingTuplePropertyBinding(property_model, "value", index))
            elif property in ("width", "height"):
                graphic = source
                display_item = graphic.display_item
                index = 1 if property == "width" else 0
                graphic_name = "rectangle"
                size_model = GraphicPropertyCommandModel(self.document_controller, display_item, graphic, "size", title=_("Change {} Size").format(graphic_name), command_id="change_" + graphic_name + "_size")
                return CalibratedSizeBinding(index, display_item, ClosingTuplePropertyBinding(size_model, "value", index))
            elif property in ("rotation_deg", ):
                graphic = source
                display_item = graphic.display_item
                graphic_name = "rectangle"
                rotation_model = GraphicPropertyCommandModel(self.document_controller, display_item, graphic, "rotation", title=_("Change {} Rotation").format(graphic_name), command_id="change_" + graphic_name + "_size")
                return ClosingPropertyBinding(rotation_model, "value", converter=RadianToDegreeStringConverter())
        if isinstance(source, Graphics.LineTypeGraphic):
            if property in ("start_x", "start_y"):
                graphic = source
                display_item = graphic.display_item
                index = 1 if property == "start_x" else 0
                graphic_name = "line_profile"
                property_model = GraphicPropertyCommandModel(self.document_controller, display_item, graphic, "start", title=_("Change {} Start").format(graphic_name), command_id="change_" + graphic_name + "_start")
                return CalibratedValueBinding(index, display_item, ClosingTuplePropertyBinding(property_model, "value", index))
            if property in ("end_x", "end_y"):
                graphic = source
                display_item = graphic.display_item
                index = 1 if property == "end_x" else 0
                graphic_name = "line_profile"
                property_model = GraphicPropertyCommandModel(self.document_controller, display_item, graphic, "end", title=_("Change {} End").format(graphic_name), command_id="change_" + graphic_name + "_end")
                return CalibratedValueBinding(index, display_item, ClosingTuplePropertyBinding(property_model, "value", index))
            if property == "length":
                graphic = source
                display_item = graphic.display_item
                graphic_name = "line_profile"
                property_model1 = GraphicPropertyCommandModel(self.document_controller, display_item, graphic, "start", title=_("Change {} Length").format(graphic_name), command_id="change_" + graphic_name + "_length_start")
                property_model2 = GraphicPropertyCommandModel(self.document_controller, display_item, graphic, "end", title=_("Change {} Length").format(graphic_name), command_id="change_" + graphic_name + "_length_end")
                return CalibratedLengthBinding(display_item, ClosingPropertyBinding(property_model1, "value"), ClosingPropertyBinding(property_model2, "value"))
            if property == "angle":
                graphic = source
                display_item = graphic.display_item
                graphic_name = "line_profile"
                property_model = GraphicPropertyCommandModel(self.document_controller, display_item, graphic, "angle", title=_("Change {} Angle").format(graphic_name), command_id="change_" + graphic_name + "_angle")
                return CalibratedBinding(display_item, ClosingPropertyBinding(property_model, "value"), RadianToDegreeStringConverter())
        if isinstance(source, Graphics.LineProfileGraphic):
            if property == "width":
                graphic = source
                display_item = graphic.display_item
                graphic_name = "line_profile"
                property_model = GraphicPropertyCommandModel(self.document_controller, display_item, graphic, "width", title=_("Change {} Line Width").format(graphic_name), command_id="change_" + graphic_name + "_line_width")
                return CalibratedWidthBinding(display_item, ClosingPropertyBinding(property_model, "value"))
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
                u.create_stretch(), spacing=12)
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
            graphic = computation_variable.bound_item.value if computation_variable.bound_item else None
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
    def __init__(self, document_controller: DocumentController.DocumentController, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable, variable_model: VariableValueModel) -> None:
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
            graphic = computation_variable.bound_item.value if computation_variable.bound_item else None
            return GraphicListVariableHandler(computation_inspector_context.window, computation, computation_variable, graphic)
        return None


Registry.register_component(BooleanVariableHandlerFactory(), {"variable-handler-fallback-component-factory"})
Registry.register_component(IntegerVariableHandlerFactory(), {"variable-handler-fallback-component-factory"})
Registry.register_component(RealVariableHandlerFactory(), {"variable-handler-fallback-component-factory"})
Registry.register_component(StringVariableHandlerFactory(), {"variable-handler-fallback-component-factory"})
Registry.register_component(DataSourceVariableHandlerFactory(), {"variable-handler-fallback-component-factory"})
Registry.register_component(GraphicVariableHandlerFactory(), {"variable-handler-fallback-component-factory"})
Registry.register_component(DataStructureVariableHandlerFactory(), {"variable-handler-fallback-component-factory"})
Registry.register_component(GraphicListVariableHandlerFactory(), {"variable-handler-fallback-component-factory"})


def make_computation_variable_component(computation_inspector_context: ComputationInspectorContext, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable, variable_value_model: VariableValueModel) -> typing.Optional[Declarative.HandlerLike]:
    """Make a computation variable component.

    Components registered under 'variable-handler-component-factory' should subclass the
    `VariableHandlerComponentFactory` protocol. The document controller, computation, and variable arguments should be
    considered read-only. When the component needs to modify the variable value, it should do so by setting
    'variable_value.value'. This ensures that undo is handled properly.
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
    # the window (document controller), the document model, and whether to provide link controls.

    def __init__(self, document_controller: DocumentController.DocumentController, reference_handler: typing.Optional[EntityBrowser.ReferenceHandlerContext] = None, provide_reference_links: bool = False) -> None:
        super().__init__()
        self.values["reference_handler"] = reference_handler or document_controller
        self.values["window"] = document_controller
        self.values["document_model"] = document_controller.document_model
        self.values["do_references"] = provide_reference_links

    @property
    def reference_handler(self) -> EntityBrowser.ReferenceHandlerContext:
        return typing.cast(EntityBrowser.ReferenceHandlerContext, self.values["reference_handler"])

    @property
    def window(self) -> DocumentController.DocumentController:
        return typing.cast("DocumentController.DocumentController", self.values["window"])

    @property
    def document_model(self) -> DocumentModel.DocumentModel:
        return typing.cast(DocumentModel.DocumentModel, self.values["document_model"])

    @property
    def do_references(self) -> bool:
        return typing.cast(bool, self.values.get("do_references", False))


class VariableWidget(Widgets.CompositeWidgetBase):
    """A composite widget for displaying a 'variable' control.

    Also watches for changes to the variable that require a different UI and rebuilds
    the UI if necessary.

    The content_widget for the CompositeWidgetBase is a column widget and always has
    a single child which is the UI for the variable. The child is replaced if necessary.
    """

    def __init__(self, computation_inspector_context: ComputationInspectorContext, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable) -> None:
        document_controller = computation_inspector_context.window
        self.__content_widget = document_controller.ui.create_column_widget()
        super().__init__(self.__content_widget)
        self.__unbinder = Unbinder()
        self.__make_widget_from_variable(computation_inspector_context, computation, variable)

        def rebuild_variable() -> None:
            self.__content_widget.remove_all()
            self.__make_widget_from_variable(computation_inspector_context, computation, variable)

        self.__variable_needs_rebuild_event_listener = variable.needs_rebuild_event.listen(rebuild_variable)

    def close(self) -> None:
        self.__variable_needs_rebuild_event_listener.close()
        self.__variable_needs_rebuild_event_listener = typing.cast(typing.Any, None)
        self.__unbinder.close()
        self.__unbinder = typing.cast(typing.Any, None)
        super().close()

    def __make_widget_from_variable(self, computation_inspector_context: ComputationInspectorContext, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable) -> None:
        document_controller = computation_inspector_context.window
        variable_value_model = VariableValueModel(document_controller, computation, variable)
        handler = make_computation_variable_component(computation_inspector_context, computation, variable, variable_value_model)
        if handler:
            widget = Declarative.DeclarativeWidget(document_controller.ui, document_controller.event_loop, handler)
            self.__content_widget.add(widget)


class ComputationInspectorSection(InspectorSection):
    def __init__(self, computation_inspector_context: ComputationInspectorContext, data_item: DataItem.DataItem) -> None:
        document_controller = computation_inspector_context.window
        super().__init__(document_controller.ui, "computation", _("Computation"))
        self.__computation_variable_inserted_event_listener: typing.Optional[Event.EventListener]
        self.__computation_variable_removed_event_listener: typing.Optional[Event.EventListener]
        document_model = document_controller.document_model
        computation = document_model.get_data_item_computation(data_item)
        if computation:
            label_row = self.ui.create_row_widget()
            label_widget = self.ui.create_label_widget()
            label_widget.bind_text(Binding.PropertyBinding(computation, "label"))
            label_row.add(label_widget)
            label_row.add_stretch()
            self._unbinder.add([data_item, computation], [label_widget.unbind_text])

            self._variables_column_widget = self.ui.create_column_widget()

            stretch_column = self.ui.create_column_widget()
            stretch_column.add_stretch()

            self.add_widget_to_content(label_row)
            self.add_widget_to_content(self._variables_column_widget)
            self.add_widget_to_content(stretch_column)

            def variable_inserted(name: str, index: int, variable: Symbolic.ComputationVariable) -> None:
                if name == "variables":
                    assert computation  # mypy bug: doesn't pass the 'if computation' here
                    widget_wrapper = VariableWidget(computation_inspector_context, computation, variable)
                    self._variables_column_widget.insert(widget_wrapper, index)

            def variable_removed(name: str, index: int, variable: Symbolic.ComputationVariable) -> None:
                if name == "variables":
                    self._variables_column_widget.remove(self._variables_column_widget.children[index])

            self.__computation_variable_inserted_event_listener = computation.item_inserted_event.listen(variable_inserted)
            self.__computation_variable_removed_event_listener = computation.item_removed_event.listen(variable_removed)

            for index, variable in enumerate(computation.variables):
                variable_inserted("variables", index, variable)
        else:
            none_label = self.ui.create_label_widget(_("None"))
            none_label.text_font = "italic"
            none_widget = self.ui.create_row_widget()
            none_widget.add(none_label)
            self.add_widget_to_content(none_widget)
            self.__computation_variable_inserted_event_listener = None
            self.__computation_variable_removed_event_listener = None
        self.finish_widget_content()

    def close(self) -> None:
        if self.__computation_variable_inserted_event_listener:
            self.__computation_variable_inserted_event_listener.close()
            self.__computation_variable_inserted_event_listener = None
        if self.__computation_variable_removed_event_listener:
            self.__computation_variable_removed_event_listener.close()
            self.__computation_variable_removed_event_listener = None
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

    def perform(self) -> None:
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
            self.__content_widget.add(ComputationInspectorSection(ComputationInspectorContext(self.__document_controller), data_item))


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
                    inspector_sections.append(ComputationInspectorSection(ComputationInspectorContext(document_controller), data_item))
            if len(display_item.graphics) > 0:
                inspector_sections.append(GraphicsInspectorSection(document_controller, display_item))
            def focus_default() -> None:
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


class DeclarativeDataSourceChooserConstructor:

    def __init__(self, app: Application.Application) -> None:
        self.__app = app

    def construct(self, d_type: str, ui: UserInterface.UserInterface, window: typing.Optional[Window.Window], d: Declarative.UIDescription, handler: Declarative.HandlerLike, finishes: typing.List[typing.Callable[[], None]]) -> typing.Optional[UserInterface.Widget]:
        if d_type == "data_source_chooser":
            properties = Declarative.construct_sizing_properties(d)
            thumbnail_source = DataItemThumbnailWidget.DataItemThumbnailSource(ui, window=window)

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
                Declarative.connect_attributes(widget, d, handler, finishes)

            return widget

        return None
