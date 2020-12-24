from __future__ import annotations

# standard libraries
import copy
import functools
import gettext
import math
import operator
import sys
import threading
import typing
import uuid

# third party libraries
# None

# local libraries
from nion.data import Calibration
from nion.swift import DataItemThumbnailWidget
from nion.swift import DisplayPanel
from nion.swift import MimeTypes
from nion.swift import Panel
from nion.swift import Undo
from nion.swift.model import ColorMaps
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import Symbolic
from nion.ui import CanvasItem
from nion.ui import Declarative
from nion.ui import UserInterface
from nion.ui import Widgets
from nion.utils import Binding
from nion.utils import Converter
from nion.utils import Geometry
from nion.utils import Model
from nion.utils import Observable

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController


_ = gettext.gettext


class InspectorPanel(Panel.Panel):
    """Inspect the current selection.

    The current selection will be a list of selection specifiers, which is itself a list of containers
    enclosing other containers or objects.
    """

    def __init__(self, document_controller, panel_id, properties):
        super().__init__(document_controller, panel_id, _("Inspector"))

        # the currently selected display item
        self.__display_item = None

        self.__display_inspector = None
        self.request_focus = False

        # listen for selected display binding changes
        self.__data_item_will_be_removed_event_listener = None
        self.__display_item_changed_event_listener = document_controller.focused_display_item_changed_event.listen(self.__display_item_changed)
        self.__set_display_item(None)

        def scroll_area_focus_changed(focused):
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

        self.__display_changed_listener = None
        self.__display_graphic_selection_changed_event_listener = None
        self.__display_about_to_be_removed_listener = None
        self.__data_shape = None
        self.__display_type = None
        self.__display_data_shape = None

    def close(self):
        # disconnect self as listener
        self.__display_item_changed_event_listener.close()
        self.__display_item_changed_event_listener = None
        # close the property controller. note: this will close and create
        # a new data item inspector; so it should go before the final
        # data item inspector close, which is below.
        self.__set_display_item(None)
        self.__display_inspector = None
        self.document_controller.clear_task("update_display" + str(id(self)))
        self.document_controller.clear_task("update_display_inspector" + str(id(self)))
        # finish closing
        super().close()

    def _get_inspector_sections(self):
        return self.__display_inspector._get_inspectors() if self.__display_inspector else None

    # close the old data item inspector, and create a new one
    # not thread safe.
    def __update_display_inspector(self):
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

        def rebuild_display_inspector():
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

            def display_item_about_to_be_removed():
                self.document_controller.clear_task("update_display_inspector" + str(id(self)))

            def display_graphic_selection_changed(graphic_selection):
                # not really a recursive call; only delayed
                # this may come in on a thread (superscan probe position connection closing). delay even more.
                self.document_controller.add_task("update_display_inspector" + str(id(self)), self.__update_display_inspector)

            def display_changed():
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
        if not self.document_controller.document_model.are_display_items_equal(self.__display_item, display_item):
            self.__display_item = display_item
            self.__update_display_inspector()
        if self.request_focus:
            if self.__display_inspector:
                self.__display_inspector.focus_default()
            self.request_focus = False

    # this message is received from the data item binding.
    # mark the data item as needing updating.
    # thread safe.
    def __display_item_changed(self, display_item: DisplayItem.DisplayItem) -> None:
        data_item = display_item.data_item if display_item else None
        def data_item_will_be_removed(data_item_to_be_removed):
            if data_item_to_be_removed == data_item:
                self.document_controller.clear_task("update_display" + str(id(self)))
                self.document_controller.clear_task("update_display_inspector" + str(id(self)))
                if self.__data_item_will_be_removed_event_listener:
                    self.__data_item_will_be_removed_event_listener.close()
                    self.__data_item_will_be_removed_event_listener = None
        def update_display():
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


class Unbinder:
    def __init__(self):
        self.__unbinders = list()
        self.__listener_map = dict()

    def close(self) -> None:
        for listener in self.__listener_map.values():
            listener.close()
        self.__listener_map = None

    def add(self, items, unbinders: typing.Sequence[typing.Callable[[], None]]) -> None:
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

    def __init__(self, ui, section_id, section_title):
        self.__section_content_column = ui.create_column_widget()
        super().__init__(Widgets.SectionWidget(ui, section_title, self.__section_content_column, "inspector/" + section_id + "/open"))
        self.ui = ui  # for use in subclasses
        self._unbinder = Unbinder()

    def close(self) -> None:
        self._unbinder.close()
        super().close()

    def add_widget_to_content(self, widget):
        """Subclasses should call this to add content in the section's top level column."""
        self.__section_content_column.add_spacing(4)
        self.__section_content_column.add(widget)

    def finish_widget_content(self):
        """Subclasses should all this after calls to add_widget_content."""
        pass

    @property
    def _section_content_for_test(self):
        return self.__section_content_column


class ChangeDisplayItemPropertyCommand(Undo.UndoableCommand):
    def __init__(self, document_model, display_item: DisplayItem.DisplayItem, property_name: str, value):
        super().__init__(_("Change Display Item Info"), command_id="change_property_" + property_name, is_mergeable=True)
        self.__document_model = document_model
        self.__display_item_proxy = display_item.create_proxy()
        self.__property_name = property_name
        self.__new_display_layers = value
        self.__old_display_layers = getattr(display_item, property_name)
        self.initialize()

    def close(self):
        self.__document_model = None
        self.__display_item_proxy.close()
        self.__display_item_proxy = None
        self.__property_name = None
        self.__new_display_layers = None
        self.__old_display_layers = None
        super().close()

    def perform(self):
        display_item = self.__display_item_proxy.item
        setattr(display_item, self.__property_name, self.__new_display_layers)

    def _get_modified_state(self):
        display_item = self.__display_item_proxy.item
        return display_item.modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state) -> None:
        display_item = self.__display_item_proxy.item
        display_item.modified_state, self.__document_model.modified_state = modified_state

    def _compare_modified_states(self, state1, state2) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return state1[0] == state2[0]

    def _undo(self) -> None:
        display_item = self.__display_item_proxy.item
        self.__new_display_layers = getattr(display_item, self.__property_name)
        setattr(display_item, self.__property_name, self.__old_display_layers)

    def _redo(self) -> None:
        self.perform()

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, ChangePropertyCommand) and self.command_id and self.command_id == command.command_id and self.__display_item_proxy.item == command.__display_item_proxy.item


class ChangePropertyCommand(Undo.UndoableCommand):
    def __init__(self, document_model, data_item: DataItem.DataItem, property_name: str, value):
        super().__init__(_("Change Data Item Info"), command_id="change_property_" + property_name, is_mergeable=True)
        self.__document_model = document_model
        self.__data_item_proxy = data_item.create_proxy()
        self.__property_name = property_name
        self.__new_value = value
        self.__old_value = getattr(data_item, property_name)
        self.initialize()

    def close(self):
        self.__document_model = None
        self.__data_item_proxy.close()
        self.__data_item_proxy = None
        self.__property_name = None
        self.__new_value = None
        self.__old_value = None
        super().close()

    def perform(self):
        data_item = self.__data_item_proxy.item
        setattr(data_item, self.__property_name, self.__new_value)

    def _get_modified_state(self):
        data_item = self.__data_item_proxy.item
        return data_item.modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state) -> None:
        data_item = self.__data_item_proxy.item
        data_item.modified_state, self.__document_model.modified_state = modified_state

    def _compare_modified_states(self, state1, state2) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return state1[0] == state2[0]

    def _undo(self) -> None:
        data_item = self.__data_item_proxy.item
        self.__new_value = getattr(data_item, self.__property_name)
        setattr(data_item, self.__property_name, self.__old_value)

    def _redo(self) -> None:
        self.perform()

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, ChangePropertyCommand) and self.command_id and self.command_id == command.command_id and self.__data_item_uuid == command.__data_item_uuid


class ChangeDisplayItemPropertyBinding(Binding.PropertyBinding):
    def __init__(self, document_controller, display_item: DisplayItem.DisplayItem, property_name: str, converter=None, fallback=None):
        super().__init__(display_item, property_name, converter=converter, fallback=fallback)
        self.__property_name = property_name
        self.__old_source_setter = self.source_setter

        def set_value(value):
            if value != getattr(display_item, property_name):
                command = ChangeDisplayItemPropertyCommand(document_controller.document_model, self.source, self.__property_name, value)
                command.perform()
                document_controller.push_undo_command(command)

        self.source_setter = set_value


class ChangeDisplayPropertyBinding(Binding.Binding):
    def __init__(self, document_controller, display_item: DisplayItem.DisplayItem, property_name: str, converter=None, fallback=None):
        super().__init__(display_item, converter=converter, fallback=fallback)

        def get_value():
            return display_item.get_display_property(property_name)

        def set_value(value):
            if value != get_value():
                command = DisplayPanel.ChangeDisplayCommand(document_controller.document_model, display_item, title=_("Change Display"), command_id="change_display_" + property_name, is_mergeable=True, **{property_name: value})
                command.perform()
                document_controller.push_undo_command(command)

        self.source_getter = get_value
        self.source_setter = set_value

        # thread safe
        def property_changed(property_name_: str) -> None:
            assert not self._closed
            if property_name_ == property_name:
                value = display_item.get_display_property(property_name)
                if value is not None:
                    self.update_target(value)
                else:
                    self.update_target_direct(self.fallback)

        self.__property_changed_listener = display_item.display_property_changed_event.listen(property_changed)

    def close(self):
        self.__property_changed_listener.close()
        self.__property_changed_listener = None
        super().close()


class ChangeDisplayDataChannelPropertyBinding(Binding.PropertyBinding):
    def __init__(self, document_controller, display_data_channel: DisplayItem.DisplayDataChannel, property_name: str, converter=None, fallback=None):
        super().__init__(display_data_channel, property_name, converter=converter, fallback=fallback)
        self.__property_name = property_name
        self.__old_source_setter = self.source_setter

        def set_value(value):
            if value != getattr(display_data_channel, property_name):
                command = DisplayPanel.ChangeDisplayDataChannelCommand(document_controller.document_model, display_data_channel, title=_("Change Display"), command_id="change_display_" + property_name, is_mergeable=True, **{self.__property_name: value})
                command.perform()
                document_controller.push_undo_command(command)

        self.source_setter = set_value


class ChangeGraphicPropertyBinding(Binding.PropertyBinding):
    def __init__(self, document_controller, display_item: DisplayItem.DisplayItem, graphic: Graphics.Graphic, property_name: str, converter=None, fallback=None):
        super().__init__(graphic, property_name, converter=converter, fallback=fallback)
        self.__display_item_proxy = display_item.create_proxy()
        self.__graphic_proxy = graphic.create_proxy()
        self.__document_controller = document_controller
        self.__property_name = property_name
        self.__old_source_setter = self.source_setter
        self.__old_source_getter = self.source_getter
        self.source_setter = self.__set_value
        self.source_getter = self.__get_value

    def close(self) -> None:
        self.__display_item_proxy.close()
        self.__display_item_proxy = None
        self.__graphic_proxy.close()
        self.__graphic_proxy = None
        super().close()

    def __get_value(self):
        display_item = self.__display_item_proxy.item
        graphic = self.__graphic_proxy.item
        if display_item and graphic:
            return getattr(graphic, self.__property_name)
        return None

    def __set_value(self, value):
        display_item = self.__display_item_proxy.item
        graphic = self.__graphic_proxy.item
        if display_item and graphic:
            if value != getattr(graphic, self.__property_name):
                command = DisplayPanel.ChangeGraphicsCommand(self.__document_controller.document_model, display_item, [graphic], title=_("Change Display Type"), command_id="change_display_" + self.__property_name, is_mergeable=True, **{self.__property_name: value})
                command.perform()
                self.__document_controller.push_undo_command(command)


class DisplayDataChannelPropertyCommandModel(Model.PropertyModel):

    def __init__(self, document_controller, display_data_channel: DisplayItem.DisplayDataChannel, property_name, title, command_id):
        super().__init__(getattr(display_data_channel, property_name))

        def property_changed_from_user(value):
            if value != getattr(display_data_channel, property_name):
                command = DisplayPanel.ChangeDisplayDataChannelCommand(document_controller.document_model, display_data_channel, title=title, command_id=command_id, is_mergeable=True, **{property_name: value})
                command.perform()
                document_controller.push_undo_command(command)

        self.on_value_changed = property_changed_from_user

        def property_changed_from_display(name):
            if name == property_name:
                self.value = getattr(display_data_channel, property_name)

        self.__changed_listener = display_data_channel.property_changed_event.listen(property_changed_from_display)

    def close(self):
        self.__changed_listener.close()
        self.__changed_listener = None
        super().close()


class GraphicPropertyCommandModel(Model.PropertyModel):

    def __init__(self, document_controller, display_item: DisplayItem.DisplayItem, graphic, property_name, title, command_id):
        super().__init__(getattr(graphic, property_name))

        def property_changed_from_user(value):
            if value != getattr(graphic, property_name):
                command = DisplayPanel.ChangeGraphicsCommand(document_controller.document_model, display_item, [graphic], title=title, command_id=command_id, is_mergeable=True, **{property_name: value})
                command.perform()
                document_controller.push_undo_command(command)

        self.on_value_changed = property_changed_from_user

        def property_changed_from_graphic(name):
            if name == property_name:
                self.value = getattr(graphic, property_name)

        self.__changed_listener = graphic.property_changed_event.listen(property_changed_from_graphic)

    def close(self):
        self.__changed_listener.close()
        self.__changed_listener = None
        super().close()


class InfoInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement info inspector.
    """

    def __init__(self, document_controller, display_item: DisplayItem.DisplayItem):
        super().__init__(document_controller.ui, "info", _("Info"))
        ui = document_controller.ui
        self.widget_id = "info_inspector_section"
        # title
        self.info_section_title_row = self.ui.create_row_widget()
        self.info_section_title_row.add(self.ui.create_label_widget(_("Title"), properties={"width": 60}))
        self.info_title_label = self.ui.create_line_edit_widget()
        self.info_title_label.bind_text(ChangeDisplayItemPropertyBinding(document_controller, display_item, "title"))
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
        def begin_caption_edit():
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
        def end_caption_edit():
            caption_binding = Binding.PropertyBinding(display_item, "caption")
            caption_binding.source_setter = None
            self.caption_static_text.bind_text(caption_binding)
            self.caption_edit_stack.current_index = 0
        def save_caption_edit():
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
    def __init__(self, document_controller, display_data_channel):
        super().__init__(document_controller.ui, "data_info", _("Data Info"))
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
    def __init__(self, document_model: DocumentModel.DocumentModel, display_item: DisplayItem.DisplayItem, display_layer_index: int, property_name: str, value):
        super().__init__(_("Change Display Layer Info"), command_id="change_display_layer_" + property_name, is_mergeable=True)
        self.__document_model = document_model
        self.__display_item_proxy = display_item.create_proxy()
        self.__display_layer_index = display_layer_index
        self.__property_name = property_name
        self.__value = value
        self.__old_properties = display_item.save_properties()
        self.initialize()

    def close(self):
        self.__document_model = None
        self.__display_item_proxy.close()
        self.__display_item_proxy = None
        self.__property_name = None
        self.__value = None
        self.__old_properties = None
        super().close()

    def perform(self):
        display_item = typing.cast(DisplayItem.DisplayItem, self.__display_item_proxy.item)
        display_item._set_display_layer_property(self.__display_layer_index, self.__property_name, self.__value)

    def _get_modified_state(self):
        display_item = typing.cast(DisplayItem.DisplayItem, self.__display_item_proxy.item)
        return display_item.modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state) -> None:
        display_item = typing.cast(DisplayItem.DisplayItem, self.__display_item_proxy.item)
        display_item.modified_state, self.__document_model.modified_state = modified_state

    def _compare_modified_states(self, state1, state2) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return state1[0] == state2[0]

    def _undo(self) -> None:
        display_item = typing.cast(DisplayItem.DisplayItem, self.__display_item_proxy.item)
        display_item.restore_properties(self.__old_properties)

    def _redo(self) -> None:
        self.perform()

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, ChangeDisplayLayerPropertyCommand) and self.command_id and self.command_id == command.command_id and self.__display_item_proxy.item == command.__display_item_proxy.item


class ChangeDisplayLayerDisplayDataChannelCommand(Undo.UndoableCommand):
    def __init__(self, document_model: DocumentModel.DocumentModel, display_item: DisplayItem.DisplayItem, display_layer_index: int, display_data_channel: DisplayItem.DisplayDataChannel):
        super().__init__(_("Change Display Layer Data"), command_id="change_display_layer_data", is_mergeable=True)
        self.__document_model = document_model
        self.__display_item_proxy = display_item.create_proxy()
        self.__display_layer_index = display_layer_index
        self.__display_data_channel_proxy = display_data_channel.create_proxy()
        self.initialize()

    def close(self):
        self.__document_model = None
        self.__display_item_proxy.close()
        self.__display_item_proxy = None
        self.__display_data_channel_proxy.close()
        self.__display_data_channel_proxy = None
        super().close()

    def perform(self):
        display_item = typing.cast(DisplayItem.DisplayItem, self.__display_item_proxy.item)
        display_data_channel = typing.cast(DisplayItem.DisplayItem, self.__display_data_channel_proxy.item)
        old_display_data_channel = display_item.get_display_layer_display_data_channel(self.__display_layer_index)
        display_item.set_display_layer_display_data_channel(self.__display_layer_index, display_data_channel)
        self.__display_data_channel_proxy.item = old_display_data_channel

    def _get_modified_state(self):
        display_item = typing.cast(DisplayItem.DisplayItem, self.__display_item_proxy.item)
        return display_item.modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state) -> None:
        display_item = typing.cast(DisplayItem.DisplayItem, self.__display_item_proxy.item)
        display_item.modified_state, self.__document_model.modified_state = modified_state

    def _compare_modified_states(self, state1, state2) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return state1[0] == state2[0]

    def _undo(self) -> None:
        self.perform()

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, ChangeDisplayLayerPropertyCommand) and self.command_id and self.command_id == command.command_id and self.__display_item_proxy.item == command.__display_item_proxy.item


class LinePlotDisplayLayersInspectorSection(InspectorSection):
    def __init__(self, document_controller, display_item: DisplayItem.DisplayItem):
        super().__init__(document_controller.ui, "line_plot_display_layer", _("Line Plot Display Layers"))
        ui = typing.cast(UserInterface.UserInterface, self.ui)

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

        def change_data_index(data_index_widget: UserInterface.LineEditWidget, display_layer: DisplayItem.DisplayLayer, data_index: int) -> None:
            display_data_channel = display_item.display_data_channels[data_index] if data_index is not None else None
            index = display_item.display_layers.index(display_layer)
            command = ChangeDisplayLayerDisplayDataChannelCommand(document_controller.document_model, display_item, index, display_data_channel)
            command.perform()
            document_controller.push_undo_command(command)
            data_index_widget.select_all()

        def change_data_row(data_row_widget: UserInterface.LineEditWidget, display_layer: DisplayItem.DisplayLayer, data_row: str) -> None:
            data_row = int(data_row) if data_row.isdigit() else 0
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

        class DisplayLayerWidget(Widgets.CompositeWidgetBase):
            def __init__(self, display_layer: DisplayItem.DisplayLayer):
                super().__init__(document_controller.ui.create_column_widget())
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
                move_forward_button_widget = TextPushButtonWidget(ui, "\N{UPWARDS WHITE ARROW}")
                move_backward_button_widget = TextPushButtonWidget(ui, "\N{DOWNWARDS WHITE ARROW}")
                add_layer_button_widget = TextPushButtonWidget(ui, "\N{PLUS SIGN}")
                remove_layer_button_widget = TextPushButtonWidget(ui, "\N{MINUS SIGN}")
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
                # build the inner column
                self.content_widget.add(label_row)
                self.content_widget.add(button_row)
                self.content_widget.add(content_row)
                self.content_widget.add(fill_color_row)
                self.content_widget.add(stroke_color_row)
                # complex display type
                display_data_channel = display_layer.display_data_channel
                if display_data_channel:
                    complex_display_type_row, self.__complex_display_type_changed_listener = make_complex_display_type_chooser(document_controller, display_data_channel)
                else:
                    complex_display_type_row, self.__complex_display_type_changed_listener = None, None
                if complex_display_type_row:
                    self.content_widget.add(complex_display_type_row)
                # save for populate
                self.__label_edit_widget = label_edit_widget
                self.__display_data_channel_index_widget = display_data_channel_index_widget
                self.__display_data_channel_row_widget = display_data_channel_row_widget
                self.__fill_color_widget = fill_color_widget
                self.__fill_color_edit = fill_color_edit
                self.__stroke_color_widget = stroke_color_widget
                self.__stroke_color_edit = stroke_color_edit

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

                self.__display_layer_property_changed_listener = display_layer.property_changed_event.listen(display_layer_property_changed)

                display_layer_property_changed("display_data_channel")
                display_layer_property_changed("label")
                display_layer_property_changed("stroke_color")
                display_layer_property_changed("fill_color")
                display_layer_property_changed("data_row")

            def close(self):
                self.__label_edit_widget = None
                self.__display_data_channel_index_widget = None
                self.__display_data_channel_row_widget = None
                self.__fill_color_widget = None
                self.__fill_color_edit = None
                self.__stroke_color_widget = None
                self.__stroke_color_edit = None
                if self.__display_layer_property_changed_listener:
                    self.__display_layer_property_changed_listener.close()
                    self.__display_layer_property_changed_listener = None
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

    def close(self):
        if self.__display_layer_inserted_listener:
            self.__display_layer_inserted_listener.close()
            self.__display_layer_inserted_listener = None
        if self.__display_layer_removed_listener:
            self.__display_layer_removed_listener.close()
            self.__display_layer_removed_listener = None
        super().close()


class ImageDataInspectorSection(InspectorSection):
    def __init__(self, document_controller, display_data_channel: DisplayItem.DisplayDataChannel, display_item: DisplayItem.DisplayItem):
        super().__init__(document_controller.ui, "display-limits", _("Image Data"))
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
        self.__data_range_model = Model.PropertyModel()

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
        float_point_2_converter = Converter.FloatToStringConverter(format="{0:#.5g}")
        float_point_2_none_converter = Converter.FloatToStringConverter(format="{0:#.5g}", pass_none=True)
        self.display_limits_range_low.bind_text(Binding.TuplePropertyBinding(self.__data_range_model, "value", 0, float_point_2_converter, fallback=_("N/A")))
        self.display_limits_range_high.bind_text(Binding.TuplePropertyBinding(self.__data_range_model, "value", 1, float_point_2_converter, fallback=_("N/A")))
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

        self.display_limits_limit_low.bind_text(Binding.TuplePropertyBinding(self.__display_limits_model, "value", 0, float_point_2_none_converter))
        self.display_limits_limit_high.bind_text(Binding.TuplePropertyBinding(self.__display_limits_model, "value", 1, float_point_2_none_converter))
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

        def handle_next_calculated_display_values():
            calculated_display_values = display_data_channel.get_calculated_display_values(True)
            if calculated_display_values:
                self.__data_range_model.value = calculated_display_values.data_range

        self.__next_calculated_display_values_listener = display_data_channel.add_calculated_display_values_listener(handle_next_calculated_display_values)

        # add unbinders
        self._unbinder.add([display_item, display_data_channel], [self.info_datetime_label.unbind_text, self.info_format_label.unbind_text, self.display_limits_range_low.unbind_text, self.display_limits_range_high.unbind_text, self.display_limits_limit_low.unbind_text, self.display_limits_limit_high.unbind_text])

    def close(self):
        self.__display_limits_model.close()
        self.__display_limits_model = None
        self.__color_map_changed_listener.close()
        self.__color_map_changed_listener = None
        if self.__complex_display_type_changed_listener:
            self.__complex_display_type_changed_listener.close()
            self.__complex_display_type_changed_listener = None
        self.__adjustment_changed_listener.close()
        self.__adjustment_changed_listener = None
        self.__next_calculated_display_values_listener.close()
        self.__next_calculated_display_values_listener = None
        self.__data_range_model.close()
        self.__data_range_model = None
        super().close()


class SessionInspectorSection(InspectorSection):

    def __init__(self, document_controller, data_item):
        super().__init__(document_controller.ui, "session", _("Session"))

        ui = document_controller.ui

        field_descriptions = [
            [_("Site"), _("Site Description"), "site"],
            [_("Instrument"), _("Instrument Description"), "instrument"],
            [_("Task"), _("Task Description"), "task"],
            [_("Microscopist"), _("Microscopist Name(s)"), "microscopist"],
            [_("Sample"), _("Sample Description"), "sample"],
            [_("Sample Area"), _("Sample Area Description"), "sample_area"],
        ]

        widget = self.ui.create_column_widget()

        def line_edit_changed(line_edit_widget, field_id, text):
            session_metadata = data_item.session_metadata
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

        def update_fields(fields):
            for field_id, line_edit_widget in field_line_edit_widget_map.items():
                line_edit_widget.text = fields.get(field_id)

        def fields_changed(key):
            if key == 'session_metadata':
                widget.add_task("update_fields", functools.partial(update_fields, data_item.session_metadata))
        self.__property_changed_listener = data_item.property_changed_event.listen(fields_changed) if data_item else None

        if data_item:
            update_fields(data_item.session_metadata)

        self.add_widget_to_content(widget)
        self.finish_widget_content()

    def close(self):
        if self.__property_changed_listener:
            self.__property_changed_listener.close()
            self.__property_changed_listener = None
        super().close()


class ChangeIntensityCalibrationCommand(Undo.UndoableCommand):
    def __init__(self, document_model, data_item: DataItem.DataItem, intensity_calibration: Calibration.Calibration):
        super().__init__(_("Change Intensity Calibration"), command_id="change_intensity_calibration", is_mergeable=True)
        self.__document_model = document_model
        self.__data_item_proxy = data_item.create_proxy()
        self.__new_intensity_calibration = intensity_calibration
        self.__old_intensity_calibration = data_item.intensity_calibration
        self.initialize()

    def close(self):
        self.__document_model = None
        self.__data_item_proxy.close()
        self.__data_item_proxy = None
        self.__new_intensity_calibration = None
        self.__old_intensity_calibration = None
        super().close()

    def perform(self):
        data_item = self.__data_item_proxy.item
        data_item.set_intensity_calibration(self.__new_intensity_calibration)

    def _get_modified_state(self):
        data_item = self.__data_item_proxy.item
        return data_item.modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state) -> None:
        data_item = self.__data_item_proxy.item
        data_item.modified_state, self.__document_model.modified_state = modified_state

    def _compare_modified_states(self, state1, state2) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return state1[0] == state2[0]

    def _undo(self) -> None:
        data_item = self.__data_item_proxy.item
        self.__new_intensity_calibration = data_item.intensity_calibration
        data_item.set_intensity_calibration(self.__old_intensity_calibration)

    def _redo(self) -> None:
        self.perform()

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, ChangeIntensityCalibrationCommand) and self.command_id and self.command_id == command.command_id and self.__data_item_uuid == command.__data_item_uuid


class ChangeDimensionalCalibrationsCommand(Undo.UndoableCommand):
    def __init__(self, document_model, data_item: DataItem.DataItem, dimensional_calibrations: typing.List[Calibration.Calibration]):
        super().__init__(_("Change Intensity Calibration"), command_id="change_intensity_calibration", is_mergeable=True)
        self.__document_model = document_model
        self.__data_item_proxy = data_item.create_proxy()
        self.__new_dimensional_calibrations = dimensional_calibrations
        self.__old_dimensional_calibrations = data_item.dimensional_calibrations
        self.initialize()

    def close(self):
        self.__document_model = None
        self.__data_item_proxy.close()
        self.__data_item_proxy = None
        super().close()

    def perform(self):
        data_item = self.__data_item_proxy.item
        data_item.set_dimensional_calibrations(self.__new_dimensional_calibrations)

    def _get_modified_state(self):
        data_item = self.__data_item_proxy.item
        return data_item.modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state) -> None:
        data_item = self.__data_item_proxy.item
        data_item.modified_state, self.__document_model.modified_state = modified_state

    def _compare_modified_states(self, state1, state2) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return state1[0] == state2[0]

    def _undo(self) -> None:
        data_item = self.__data_item_proxy.item
        self.__new_dimensional_calibrations = data_item.dimensional_calibrations
        data_item.set_dimensional_calibrations(self.__old_dimensional_calibrations)

    def _redo(self) -> None:
        self.perform()

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, ChangeDimensionalCalibrationsCommand) and self.command_id and self.command_id == command.command_id and self.__data_item_uuid == command.__data_item_uuid


class CalibrationToObservable(Observable.Observable):
    """Provides observable calibration object.

    Clients can get/set/observer offset, scale, and unit properties.

    The function setter will take a calibration argument. A typical function setter might be
    data_source.set_dimensional_calibration(0, calibration).
    """

    def __init__(self, calibration, setter_fn):
        super().__init__()
        self.__calibration = calibration
        self.__cached_value = Calibration.Calibration()
        self.__setter_fn = setter_fn
        def update_calibration(calibration):
            if self.__cached_value is not None:
                if calibration.offset != self.__cached_value.offset:
                    self.notify_property_changed("offset")
                if calibration.scale != self.__cached_value.scale:
                    self.notify_property_changed("scale")
                if calibration.units != self.__cached_value.units:
                    self.notify_property_changed("units")
            self.__cached_value = calibration
        update_calibration(calibration)

    def close(self):
        self.__cached_value = None
        self.__setter_fn = None

    def copy_from(self, calibration):
        self.__cached_value = calibration
        self.notify_property_changed("offset")
        self.notify_property_changed("scale")
        self.notify_property_changed("units")

    @property
    def offset(self):
        return self.__cached_value.offset

    @offset.setter
    def offset(self, value):
        calibration = self.__cached_value
        calibration.offset = value
        self.__setter_fn(calibration)
        self.notify_property_changed("offset")

    @property
    def scale(self):
        return self.__cached_value.scale

    @scale.setter
    def scale(self, value):
        calibration = self.__cached_value
        calibration.scale = value
        self.__setter_fn(calibration)
        self.notify_property_changed("scale")

    @property
    def units(self):
        return self.__cached_value.units

    @units.setter
    def units(self, value):
        calibration = self.__cached_value
        calibration.units = value
        self.__setter_fn(calibration)
        self.notify_property_changed("units")


class InspectorSectionWidget(Widgets.CompositeWidgetBase):
    def __init__(self, ui):
        super().__init__(ui.create_column_widget())
        self.__unbinder = Unbinder()
        self.__closeables = list()

    def close(self):
        self.__unbinder.close()
        for closeable in self.__closeables:
            closeable.close()
        self.__closeables = None
        super().close()

    def add_closeable(self, closeable) -> None:
        self.__closeables.append(closeable)

    def add_closeables(self, *closeables) -> None:
        for closeable in closeables:
            self.add_closeable(closeable)

    def add_unbinder(self, items, unbinders: typing.Sequence[typing.Callable[[], None]]) -> None:
        self.__unbinder.add(items, unbinders)

    def add(self, widget) -> None:
        self.content_widget.add(widget)

    def add_spacing(self, spacing: int) -> None:
        self.content_widget.add_spacing(spacing)

    def find_widget_by_id(self, widget_id: str):
        return self.content_widget.find_widget_by_id(widget_id)


def make_calibration_style_chooser(document_controller, display_item: DisplayItem.DisplayItem) -> InspectorSectionWidget:
    ui = document_controller.ui

    calibration_styles = DisplayItem.get_calibration_styles()

    display_calibration_style_options = [(calibration_style.label, calibration_style.calibration_style_id) for calibration_style in calibration_styles]

    display_calibration_style_reverse_map = {p[1]: i for i, p in enumerate(display_calibration_style_options)}

    class CalibrationStyleIndexConverter:
        def convert(self, value):
            return display_calibration_style_reverse_map.get(value, 0)
        def convert_back(self, value):
            if value >= 0 and value < len(display_calibration_style_options):
                return display_calibration_style_options[value][1]
            else:
                return calibration_styles[0].label

    display_calibration_style_chooser = ui.create_combo_box_widget(items=display_calibration_style_options, item_getter=operator.itemgetter(0))
    display_calibration_style_chooser.bind_current_index(ChangeDisplayItemPropertyBinding(document_controller, display_item, "calibration_style_id", converter=CalibrationStyleIndexConverter(), fallback=0))

    widget = InspectorSectionWidget(ui)

    widget.add(display_calibration_style_chooser)

    widget.add_unbinder([display_item], [display_calibration_style_chooser.unbind_current_index])

    return widget


def make_calibration_row_widget(ui, data_item: DataItem.DataItem, calibration_observable, label: str=None) -> InspectorSectionWidget:
    """Called when an item (calibration_observable) is inserted into the list widget. Returns a widget."""
    widget = InspectorSectionWidget(ui)
    calibration_row = ui.create_row_widget()
    row_label = ui.create_label_widget(label, properties={"width": 60})
    row_label.widget_id = "label"
    offset_field = ui.create_line_edit_widget(properties={"width": 60})
    offset_field.widget_id = "offset"
    scale_field = ui.create_line_edit_widget(properties={"width": 60})
    scale_field.widget_id = "scale"
    units_field = ui.create_line_edit_widget(properties={"width": 60})
    units_field.widget_id = "units"
    float_point_4_converter = Converter.FloatToStringConverter(format="{0:.4f}")
    offset_field.bind_text(Binding.PropertyBinding(calibration_observable, "offset", converter=float_point_4_converter))
    scale_field.bind_text(Binding.PropertyBinding(calibration_observable, "scale", converter=float_point_4_converter))
    units_field.bind_text(Binding.PropertyBinding(calibration_observable, "units"))
    # notice the binding of calibration_index below.
    calibration_row.add(row_label)
    calibration_row.add_spacing(12)
    calibration_row.add(offset_field)
    calibration_row.add_spacing(12)
    calibration_row.add(scale_field)
    calibration_row.add_spacing(12)
    calibration_row.add(units_field)
    calibration_row.add_stretch()
    widget.add(calibration_row)
    widget.add_unbinder([data_item], [offset_field.unbind_text, scale_field.unbind_text, units_field.unbind_text])
    return widget


class CalibrationsInspectorSection(InspectorSection):
    """Calibration inspector."""

    def __init__(self, document_controller, display_data_channel: DisplayItem.DisplayDataChannel, display_item: DisplayItem.DisplayItem):
        super().__init__(document_controller.ui, "calibrations", _("Calibrations"))
        self.__document_controller = document_controller
        self.__display_data_channel = display_data_channel
        self.__display_item = display_item
        self.__calibration_observables = list()
        ui = document_controller.ui
        header_widget = self.__create_header_widget()
        header_for_empty_list_widget = self.__create_header_for_empty_list_widget()
        self.__list_widget = Widgets.TableWidget(ui, lambda item: self.__create_list_item_widget(ui, item), header_widget, header_for_empty_list_widget)
        self.__list_widget.widget_id = "calibration_list_widget"
        self.add_widget_to_content(self.__list_widget)

        data_item = self.__display_data_channel.data_item

        # create the intensity row
        intensity_calibration = (data_item.intensity_calibration if data_item else None) or Calibration.Calibration()

        def change_intensity_calibration(intensity_calibration):
            command = ChangeIntensityCalibrationCommand(document_controller.document_model, data_item, intensity_calibration)
            command.perform()
            document_controller.push_undo_command(command)

        self.__intensity_calibration_observable = CalibrationToObservable(intensity_calibration, change_intensity_calibration)
        intensity_row = make_calibration_row_widget(ui, data_item, self.__intensity_calibration_observable, _("Intensity"))

        def handle_data_item_changed():
            # handle threading specially for tests
            if threading.current_thread() != threading.main_thread():
                self.content_widget.add_task("update_calibration_list" + str(id(self)), self.__build_calibration_list)
            else:
                self.__build_calibration_list()

        self.__data_item_changed_event_listener = data_item.data_item_changed_event.listen(handle_data_item_changed) if data_item else None
        self.__build_calibration_list()

        self.add_widget_to_content(intensity_row)
        # create the display calibrations check box row
        self.display_calibrations_row = self.ui.create_row_widget()
        self.display_calibrations_row.add(self.ui.create_label_widget(_("Display"), properties={"width": 60}))
        self.display_calibrations_row.add(make_calibration_style_chooser(document_controller, self.__display_item))
        self.display_calibrations_row.add_stretch()
        self.add_widget_to_content(self.display_calibrations_row)
        self.finish_widget_content()

    def close(self):
        if self.__data_item_changed_event_listener:
            self.__data_item_changed_event_listener.close()
            self.__data_item_changed_event_listener = None
        # close the bound calibrations
        self.__intensity_calibration_observable.close()
        self.__intensity_calibration_observable = None
        for calibration_observable in self.__calibration_observables:
            calibration_observable.close()
        self.__calibration_observables = list()
        super().close()

    # not thread safe
    def __build_calibration_list(self):
        data_item = self.__display_data_channel.data_item
        dimensional_calibrations = (data_item.dimensional_calibrations if data_item else None) or list()
        while len(dimensional_calibrations) < self.__list_widget.list_item_count:
            self.__list_widget.remove_item(len(self.__calibration_observables) - 1)
            self.__calibration_observables[-1].close()
            self.__calibration_observables.pop(-1)
        while len(dimensional_calibrations) > self.__list_widget.list_item_count:
            index = self.__list_widget.list_item_count

            def change_dimensional_calibration(index, dimensional_calibration):
                dimensional_calibrations = data_item.dimensional_calibrations
                dimensional_calibrations[index] = dimensional_calibration
                command = ChangeDimensionalCalibrationsCommand(self.__document_controller.document_model, data_item, dimensional_calibrations)
                command.perform()
                self.__document_controller.push_undo_command(command)

            calibration_observable = CalibrationToObservable(dimensional_calibrations[index], functools.partial(change_dimensional_calibration, index))
            self.__calibration_observables.append(calibration_observable)
            self.__list_widget.insert_item(calibration_observable, index)
        assert len(dimensional_calibrations) == self.__list_widget.list_item_count
        for index, (dimensional_calibration, calibration_observable) in enumerate(zip(dimensional_calibrations, self.__calibration_observables)):
            calibration_observable.copy_from(dimensional_calibration)
            if self.__list_widget.list_item_count == 1:
                row_label_text = _("Channel")
            elif self.__list_widget.list_item_count == 2:
                row_label_text = (_("Y"), _("X"))[index]
            else:
                row_label_text = str(index)
            self.__list_widget.list_items[index].find_widget_by_id("label").text = row_label_text
        self.__intensity_calibration_observable.copy_from((data_item.intensity_calibration if data_item else None) or Calibration.Calibration())

    # not thread safe
    def __create_header_widget(self):
        header_row = self.ui.create_row_widget()
        axis_header_label = self.ui.create_label_widget("Axis", properties={"width": 60})
        offset_header_label = self.ui.create_label_widget(_("Offset"), properties={"width": 60})
        scale_header_label = self.ui.create_label_widget(_("Scale"), properties={"width": 60})
        units_header_label = self.ui.create_label_widget(_("Units"), properties={"width": 60})
        header_row.add(axis_header_label)
        header_row.add_spacing(12)
        header_row.add(offset_header_label)
        header_row.add_spacing(12)
        header_row.add(scale_header_label)
        header_row.add_spacing(12)
        header_row.add(units_header_label)
        header_row.add_stretch()
        return header_row

    # not thread safe
    def __create_header_for_empty_list_widget(self):
        label_widget = self.ui.create_label_widget(_("None"))
        label_widget.text_font = "italic"
        header_for_empty_list_row = self.ui.create_row_widget()
        header_for_empty_list_row.add(label_widget)
        return header_for_empty_list_row

    # not thread safe.
    def __create_list_item_widget(self, ui, calibration_observable):
        """Called when an item (calibration_observable) is inserted into the list widget. Returns a widget."""
        data_item = self.__display_data_channel.data_item
        calibration_row = make_calibration_row_widget(ui, data_item, calibration_observable)
        column = ui.create_column_widget()
        column.add_spacing(4)
        column.add(calibration_row)
        return column


class ChangeDisplayTypeCommand(Undo.UndoableCommand):

    def __init__(self, document_model, display_item: DisplayItem.DisplayItem, display_type: str):
        super().__init__(_("Change Display Type"), command_id="change_display_type", is_mergeable=True)
        self.__document_model = document_model
        self.__display_item_proxy = display_item.create_proxy()
        self.__old_display_type = display_item.display_type
        self.__display_type = display_type
        self.initialize()

    def close(self):
        self.__document_model = None
        self.__display_item_proxy.close()
        self.__display_item_proxy = None
        self.__old_display_type = None
        super().close()

    def perform(self):
        display_item = self.__display_item_proxy.item
        display_item.display_type = self.__display_type

    def _get_modified_state(self):
        display_item = self.__display_item_proxy.item
        return display_item.modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state):
        display_item = self.__display_item_proxy.item
        display_item.modified_state, self.__document_model.modified_state = modified_state

    def _compare_modified_states(self, state1, state2) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return state1[0] == state2[0]

    def _undo(self):
        display_item = self.__display_item_proxy.item
        old_display_type = self.__old_display_type
        self.__old_display_type = display_item.display_type
        display_item.display_type = old_display_type

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, ChangeDisplayTypeCommand) and self.command_id and self.command_id == command.command_id and self.__display_item_proxy.item == command.__display_item_proxy.item


def make_display_type_chooser(document_controller, display_item: DisplayItem.DisplayItem):
    ui = document_controller.ui
    display_type_row = ui.create_row_widget()
    display_type_items = ((_("Default"), None), (_("Line Plot"), "line_plot"), (_("Image"), "image"), (_("Display Script"), "display_script"))
    display_type_reverse_map = {None: 0, "line_plot": 1, "image": 2, "display_script": 3}
    display_type_chooser = ui.create_combo_box_widget(items=display_type_items, item_getter=operator.itemgetter(0))

    def property_changed(name):
        if name == "display_type":
            display_type_chooser.current_index = display_type_reverse_map[display_item.display_type]

    listener = display_item.property_changed_event.listen(property_changed)

    def change_display_type(item):
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


def make_color_map_chooser(document_controller, display_data_channel: DisplayItem.DisplayDataChannel):
    ui = document_controller.ui
    color_map_row = ui.create_row_widget()
    color_map_options = [(_("Default"), None)]
    for color_map_key, color_map in ColorMaps.color_maps.items():
        color_map_options.append((color_map.name, color_map_key))
    color_map_reverse_map = {p[1]: i for i, p in enumerate(color_map_options)}
    color_map_chooser = ui.create_combo_box_widget(items=color_map_options, item_getter=operator.itemgetter(0))

    def property_changed(name):
        if name == "color_map_id":
            color_map_chooser.current_index = color_map_reverse_map[display_data_channel.color_map_id]

    listener = display_data_channel.property_changed_event.listen(property_changed)

    def change_color_map(item):
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


class ContrastStringConverter:

    def convert(self, value: float) -> str:
        return f"{value:0.2f}" if value >= 1 else f"1 / {1/value:0.2f}"

    def convert_back(self, value_str: str) -> float:
        value_str = ''.join(value_str.split())
        if value_str.startswith("1/"):
            return 1 / Converter.FloatToStringConverter().convert_back(value_str[2:])
        else:
            return Converter.FloatToStringConverter().convert_back(value_str)


class ContrastIntegerConverter:
    def __init__(self, n: int):
        self.n = n

    def convert(self, value):
        return int(math.log10(value) * self.n // 2) + (self.n // 2)

    def convert_back(self, value_int):
        return math.pow(10, (value_int - self.n // 2) / (self.n // 2))


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


class GammaStringConverter:

    def convert(self, value: float) -> str:
        return f"{value:0.2f}" if value >= 1 else f"1 / {1/value:0.3f}"

    def convert_back(self, value_str: str) -> float:
        value_str = ''.join(value_str.split())
        if value_str.startswith("1/"):
            return 1 / Converter.FloatToStringConverter().convert_back(value_str[2:])
        else:
            return Converter.FloatToStringConverter().convert_back(value_str)


class GammaIntegerConverter:
    # gamma ranges from 1/N to N

    def convert(self, value: float) -> int:
        return 100 - int(math.log(value, 10) * 50 + 50)

    def convert_back(self, value_int: int) -> float:
        return math.pow(10, ((100 - value_int) - 50) / 50)


class ChangeDisplayDataChannelAdjustmentPropertyBinding(Binding.PropertyBinding):
    def __init__(self, document_controller, display_data_channel: DisplayItem.DisplayDataChannel, property_name: str, converter, default_value):
        super().__init__(display_data_channel, "adjustments")

        def set_value(value):
            if converter.convert_back(value) != display_data_channel.adjustments[0].get(property_name, None):
                adjustment = display_data_channel.adjustments[0]
                adjustment[property_name] = converter.convert_back(value)
                command = DisplayPanel.ChangeDisplayDataChannelCommand(document_controller.document_model, display_data_channel, title=_("Change Display"), command_id="change_display_" + property_name, is_mergeable=True, adjustments=[adjustment])
                command.perform()
                document_controller.push_undo_command(command)

        def get_value():
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

    def change_adjustment(item) -> None:
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


def make_complex_display_type_chooser(document_controller, display_data_channel: DisplayItem.DisplayDataChannel, include_log_abs=True):
    if not (display_data_channel.data_item and display_data_channel.data_item.is_data_complex_type):
        return None, None
    ui = document_controller.ui
    display_type_row = ui.create_row_widget()
    display_type_options = [(_("Log Absolute"), "log-absolute")] if include_log_abs else list()
    display_type_options.extend([(_("Absolute"), "absolute"), (_("Real"), "real"), (_("Imaginary"), "imaginary")])
    display_type_reverse_map = {p[1]: i for i, p in enumerate(display_type_options)}
    display_type_chooser = ui.create_combo_box_widget(items=display_type_options, item_getter=operator.itemgetter(0))

    def property_changed(name):
        if name == "complex_display_type":
            display_type_chooser.current_index = display_type_reverse_map[display_data_channel.complex_display_type]

    listener = display_data_channel.property_changed_event.listen(property_changed)

    def change_display_type(item):
        if display_data_channel.complex_display_type != item[1]:
            command = DisplayPanel.ChangeDisplayDataChannelCommand(document_controller.document_model, display_data_channel, complex_display_type=item[1])
            command.perform()
            document_controller.push_undo_command(command)

    display_type_chooser.on_current_item_changed = change_display_type
    display_type_chooser.current_index = display_type_reverse_map.get(display_data_channel.complex_display_type, 0)
    display_type_row.add(ui.create_label_widget(_("Complex Display Type:"), properties={"width": 120}))
    display_type_row.add(display_type_chooser)
    display_type_row.add_stretch()
    return display_type_row, listener


class ImageDisplayInspectorSection(InspectorSection):
    """Display type inspector."""

    def __init__(self, document_controller, display_item: DisplayItem.DisplayItem):
        super().__init__(document_controller.ui, "display-limits", _("Image Display"))

        # display type
        display_type_row, self.__display_type_changed_listener = make_display_type_chooser(document_controller, display_item)

        self.add_widget_to_content(display_type_row)

        self.finish_widget_content()

    def close(self):
        self.__display_type_changed_listener.close()
        self.__display_type_changed_listener = None
        super().close()


def make_legend_position(document_controller, display_item: DisplayItem.DisplayItem):
    ui = document_controller.ui
    legend_position_row = ui.create_row_widget()
    legend_position_options = [(_("None"), None), (_("Top Left"), "top-left"), (_("Top Right"), "top-right")]
    legend_position_reverse_map = {p[1]: i for i, p in enumerate(legend_position_options)}
    legend_position_chooser = ui.create_combo_box_widget(items=legend_position_options, item_getter=operator.itemgetter(0))

    def property_changed(name):
        if name == "legend_position":
            legend_position_chooser.current_index = legend_position_reverse_map[display_item.get_display_property("legend_position", None)]

    listener = display_item.display_property_changed_event.listen(property_changed)

    def change_legend_position(item):
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

    def __init__(self, document_controller, display_item: DisplayItem.DisplayItem):
        super().__init__(document_controller.ui, "line-plot", _("Line Plot Display"))

        # display type
        display_type_row, self.__display_type_changed_listener = make_display_type_chooser(document_controller, display_item)

        float_point_2_none_converter = Converter.FloatToStringConverter(format="{0:#.5g}", pass_none=True)

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

        class LogCheckedToCheckStateConverter:
            """ Convert between bool and checked/unchecked strings. """

            def convert(self, value):
                """ Convert bool to checked or unchecked string """
                return "checked" if value == "log" else "unchecked"

            def convert_back(self, value):
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

    def close(self):
        self.__legend_position_changed_listener.close()
        self.__legend_position_changed_listener = None
        self.__display_type_changed_listener.close()
        self.__display_type_changed_listener = None
        super().close()


class SequenceInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement slice inspector.
    """

    def __init__(self, document_controller, display_data_channel: DisplayItem.DisplayDataChannel):
        super().__init__(document_controller.ui, "sequence", _("Sequence"))

        data_item = display_data_channel.data_item

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

    def __init__(self, document_controller, display_data_channel: DisplayItem.DisplayDataChannel):
        super().__init__(document_controller.ui, "collection-index", _("Index"))

        data_item = display_data_channel.data_item

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

    def close(self):
        self.__collection_index_model.close()
        self.__collection_index_model = None
        super().close()


class SliceInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement slice inspector.
    """

    def __init__(self, document_controller, display_data_channel: DisplayItem.DisplayDataChannel):
        super().__init__(document_controller.ui, "slice", _("Slice"))

        data_item = display_data_channel.data_item

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


class RadianToDegreeStringConverter:
    """
        Converter object to convert from radian value to degree string and back.
    """
    def convert(self, value):
        return "{0:.4f}°".format(math.degrees(value))
    def convert_back(self, str):
        return math.radians(Converter.FloatToStringConverter().convert_back(str))


class CalibratedValueFloatToStringConverter:
    """
        Converter object to convert from calibrated value to string and back.
    """
    def __init__(self, display_item: DisplayItem.DisplayItem, index):
        self.__display_item = display_item
        self.__index = index
    def __get_calibration(self):
        index = self.__index
        calibrations = self.__display_item.displayed_datum_calibrations
        dimension_count = len(calibrations)
        if index < 0:
            index = dimension_count + index
        if index >= 0 and index < dimension_count:
            return calibrations[index]
        else:
            return Calibration.Calibration()
    def __get_data_size(self):
        index = self.__index
        display_data_shape = self.__display_item.display_data_shape
        dimension_count = len(display_data_shape) if display_data_shape is not None else 0
        if index < 0:
            index = dimension_count + index
        if index >= 0 and index < dimension_count:
            return display_data_shape[index]
        else:
            return 1.0
    def convert_calibrated_value_to_str(self, calibrated_value):
        calibration = self.__get_calibration()
        return calibration.convert_calibrated_value_to_str(calibrated_value)
    def convert_to_calibrated_value(self, value):
        calibration = self.__get_calibration()
        data_size = self.__get_data_size()
        return calibration.convert_to_calibrated_value(data_size * value)
    def convert_from_calibrated_value(self, calibrated_value):
        calibration = self.__get_calibration()
        data_size = self.__get_data_size()
        return calibration.convert_from_calibrated_value(calibrated_value) / data_size
    def convert(self, value):
        calibration = self.__get_calibration()
        data_size = self.__get_data_size()
        return calibration.convert_to_calibrated_value_str(data_size * value, value_range=(0, data_size), samples=data_size)
    def convert_back(self, str):
        calibration = self.__get_calibration()
        data_size = self.__get_data_size()
        return calibration.convert_from_calibrated_value(Converter.FloatToStringConverter().convert_back(str)) / data_size


class CalibratedSizeFloatToStringConverter:
    """
        Converter object to convert from calibrated size to string and back.
        """
    def __init__(self, display_item: DisplayItem.DisplayItem, index, factor=1.0):
        self.__display_item = display_item
        self.__index = index
        self.__factor = factor
    def __get_calibration(self):
        index = self.__index
        calibrations = self.__display_item.displayed_datum_calibrations
        dimension_count = len(calibrations)
        if index < 0:
            index = dimension_count + index
        if index >= 0 and index < dimension_count:
            return self.__display_item.displayed_datum_calibrations[index]
        else:
            return Calibration.Calibration()
    def __get_data_size(self):
        index = self.__index
        display_data_shape = self.__display_item.display_data_shape
        dimension_count = len(display_data_shape) if display_data_shape else 0
        if index < 0:
            index = dimension_count + index
        if index >= 0 and index < dimension_count:
            return display_data_shape[index]
        else:
            return 1.0
    def convert_calibrated_value_to_str(self, calibrated_value):
        calibration = self.__get_calibration()
        return calibration.convert_calibrated_size_to_str(calibrated_value)
    def convert_to_calibrated_value(self, size):
        calibration = self.__get_calibration()
        data_size = self.__get_data_size()
        return calibration.convert_to_calibrated_size(data_size * size * self.__factor)
    def convert(self, size):
        calibration = self.__get_calibration()
        data_size = self.__get_data_size()
        return calibration.convert_to_calibrated_size_str(data_size * size * self.__factor, value_range=(0, data_size), samples=data_size)
    def convert_back(self, str):
        calibration = self.__get_calibration()
        data_size = self.__get_data_size()
        return calibration.convert_from_calibrated_size(Converter.FloatToStringConverter().convert_back(str)) / data_size / self.__factor


class CalibratedBinding(Binding.Binding):
    def __init__(self, display_item: DisplayItem.DisplayItem, value_binding, converter):
        super().__init__(None, converter=converter)
        self.__value_binding = value_binding
        def update_target(value):
            self.update_target_direct(self.get_target_value())
        self.__value_binding.target_setter = update_target
        def calibrations_changed(k):
            if k == "displayed_dimensional_calibrations":
                update_target(display_item.displayed_datum_calibrations)
        self.__calibrations_changed_event_listener = display_item.display_property_changed_event.listen(calibrations_changed)
    def close(self):
        self.__value_binding.close()
        self.__value_binding = None
        self.__calibrations_changed_event_listener.close()
        self.__calibrations_changed_event_listener = None
        super().close()
    # set the model value from the target ui element text.
    def update_source(self, target_value):
        converted_value = self.converter.convert_back(target_value)
        self.__value_binding.update_source(converted_value)
    # get the value from the model and return it as a string suitable for the target ui element.
    # in this binding, it combines the two source bindings into one.
    def get_target_value(self):
        value = self.__value_binding.get_target_value()
        return self.converter.convert(value) if value is not None else None


class CalibratedValueBinding(CalibratedBinding):
    def __init__(self, index, display_item: DisplayItem.DisplayItem, value_binding):
        converter = CalibratedValueFloatToStringConverter(display_item, index)
        super().__init__(display_item, value_binding, converter)


class CalibratedSizeBinding(CalibratedBinding):
    def __init__(self, index, display_item: DisplayItem.DisplayItem, value_binding):
        converter = CalibratedSizeFloatToStringConverter(display_item, index)
        super().__init__(display_item, value_binding, converter)


class CalibratedWidthBinding(CalibratedBinding):
    def __init__(self, display_item: DisplayItem.DisplayItem, value_binding):
        factor = 1.0 / display_item.display_data_shape[0]
        converter = CalibratedSizeFloatToStringConverter(display_item, 0, factor)  # width is stored in pixels. argh.
        super().__init__(display_item, value_binding, converter)


class CalibratedLengthBinding(Binding.Binding):
    def __init__(self, display_item: DisplayItem.DisplayItem, start_binding, end_binding):
        super().__init__(None)
        self.__x_converter = CalibratedValueFloatToStringConverter(display_item, 1)
        self.__y_converter = CalibratedValueFloatToStringConverter(display_item, 0)
        self.__size_converter = CalibratedSizeFloatToStringConverter(display_item, 0)
        self.__start_binding = start_binding
        self.__end_binding = end_binding
        def update_target(value):
            self.update_target_direct(self.get_target_value())
        self.__start_binding.target_setter = update_target
        self.__end_binding.target_setter = update_target
        def calibrations_changed(k):
            if k == "displayed_dimensional_calibrations":
                update_target(display_item.displayed_datum_calibrations)
        self.__calibrations_changed_event_listener = display_item.display_property_changed_event.listen(calibrations_changed)
    def close(self):
        self.__start_binding.close()
        self.__start_binding = None
        self.__end_binding.close()
        self.__end_binding = None
        self.__calibrations_changed_event_listener.close()
        self.__calibrations_changed_event_listener = None
        super().close()
    # set the model value from the target ui element text.
    def update_source(self, target_value):
        start = self.__start_binding.get_target_value()
        end = self.__end_binding.get_target_value()
        calibrated_start = Geometry.FloatPoint(y=self.__y_converter.convert_to_calibrated_value(start[0]), x=self.__x_converter.convert_to_calibrated_value(start[1]))
        calibrated_end = Geometry.FloatPoint(y=self.__y_converter.convert_to_calibrated_value(end[0]), x=self.__x_converter.convert_to_calibrated_value(end[1]))
        delta = calibrated_end - calibrated_start
        angle = -math.atan2(delta.y, delta.x)
        new_calibrated_end = calibrated_start + target_value * Geometry.FloatSize(height=-math.sin(angle), width=math.cos(angle))
        end = Geometry.FloatPoint(y=self.__y_converter.convert_from_calibrated_value(new_calibrated_end.y), x=self.__x_converter.convert_from_calibrated_value(new_calibrated_end.x))
        self.__end_binding.update_source(end)
    # get the value from the model and return it as a string suitable for the target ui element.
    # in this binding, it combines the two source bindings into one.
    def get_target_value(self):
        start = self.__start_binding.get_target_value()
        end = self.__end_binding.get_target_value()
        calibrated_dy = self.__y_converter.convert_to_calibrated_value(end[0]) - self.__y_converter.convert_to_calibrated_value(start[0])
        calibrated_dx = self.__x_converter.convert_to_calibrated_value(end[1]) - self.__x_converter.convert_to_calibrated_value(start[1])
        calibrated_value = math.sqrt(calibrated_dx * calibrated_dx + calibrated_dy * calibrated_dy)
        return self.__size_converter.convert_calibrated_value_to_str(calibrated_value)


def make_point_type_inspector(document_controller, display_item: DisplayItem.DisplayItem, graphic) -> InspectorSectionWidget:
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


def make_line_type_inspector(document_controller, display_item: DisplayItem.DisplayItem, graphic) -> InspectorSectionWidget:
    ui = document_controller.ui
    graphic_widget = InspectorSectionWidget(ui)
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
        angle_binding = ChangeGraphicPropertyBinding(document_controller, display_item, graphic, "angle", RadianToDegreeStringConverter())
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


def make_line_profile_inspector(document_controller, display_item: DisplayItem.DisplayItem, graphic) -> InspectorSectionWidget:
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


def make_rectangle_type_inspector(document_controller, display_item: DisplayItem.DisplayItem, graphic, graphic_name: str, rotation: bool = False) -> InspectorSectionWidget:
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


def make_spot_inspector(document_controller, display_item: DisplayItem.DisplayItem, graphic, graphic_name: str) -> InspectorSectionWidget:
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


def make_wedge_inspector(document_controller, display_item: DisplayItem.DisplayItem, graphic: Graphics.WedgeGraphic) -> InspectorSectionWidget:
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

    graphic_center_start_angle_line_edit.bind_text(Binding.TuplePropertyBinding(angle_interval_model, "value", 0, RadianToDegreeStringConverter()))
    graphic_center_angle_measure_line_edit.bind_text(Binding.TuplePropertyBinding(angle_interval_model, "value", 1, RadianToDegreeStringConverter()))

    graphic_widget.add_unbinder([display_item, graphic], [graphic_center_start_angle_line_edit.unbind_text, graphic_center_angle_measure_line_edit.unbind_text])

    graphic_widget.add_closeable(angle_interval_model)

    return graphic_widget


def make_annular_ring_mode_chooser(document_controller, graphic_widget: InspectorSectionWidget, display_item: DisplayItem.DisplayItem, graphic: Graphics.RingGraphic):
    ui = document_controller.ui
    annular_ring_mode_options = ((_("Band Pass"), "band-pass"), (_("Low Pass"), "low-pass"), (_("High Pass"), "high-pass"))
    annular_ring_mode_reverse_map = {"band-pass": 0, "low-pass": 1, "high-pass": 2}

    class AnnularRingModeIndexConverter:
        """
            Convert from flag index (-1, 0, 1) to chooser index.
        """
        def convert(self, value):
            return annular_ring_mode_reverse_map.get(value, 0)
        def convert_back(self, value):
            if value >= 0 and value < len(annular_ring_mode_options):
                return annular_ring_mode_options[value][1]
            else:
                return "band-pass"

    display_calibration_style_chooser = ui.create_combo_box_widget(items=annular_ring_mode_options, item_getter=operator.itemgetter(0))
    display_calibration_style_chooser.bind_current_index(ChangeGraphicPropertyBinding(document_controller, display_item, graphic, "mode", converter=AnnularRingModeIndexConverter(), fallback=0))

    graphic_widget.add_unbinder([display_item, graphic], [display_calibration_style_chooser.unbind_current_index])

    return display_calibration_style_chooser


def make_ring_inspector(document_controller, display_item: DisplayItem.DisplayItem, graphic) -> InspectorSectionWidget:
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


def make_interval_type_inspector(document_controller, display_item: DisplayItem.DisplayItem, graphic) -> InspectorSectionWidget:
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

    def __init__(self, document_controller, display_item: DisplayItem.DisplayItem, selected_only=False):
        super().__init__(document_controller.ui, "graphics", _("Graphics"))
        ui = document_controller.ui
        self.__document_controller = document_controller
        self.__display_item = display_item
        self.__graphics = display_item.graphics
        # ui
        header_widget = self.__create_header_widget()
        header_for_empty_list_widget = self.__create_header_for_empty_list_widget()
        # create the widgets for each graphic
        # TODO: do not use dynamic list object in graphics inspector; the dynamic aspect is not utilized.
        list_widget = Widgets.TableWidget(ui, lambda item: self.__create_list_item_widget(item), header_widget, header_for_empty_list_widget)
        list_widget.bind_items(Binding.ListBinding(display_item, "selected_graphics" if selected_only else "graphics"))
        self.add_widget_to_content(list_widget)
        # create the display calibrations check box row
        display_calibrations_row = self.ui.create_row_widget()
        display_calibrations_row.add(self.ui.create_label_widget(_("Display"), properties={"width": 60}))
        display_calibrations_row.add(make_calibration_style_chooser(document_controller, self.__display_item))
        display_calibrations_row.add_stretch()
        self.add_widget_to_content(display_calibrations_row)
        self.finish_widget_content()
        # add unbinders
        self._unbinder.add([display_item], [list_widget.unbind_items])

    def __create_header_widget(self):
        return self.ui.create_row_widget()

    def __create_header_for_empty_list_widget(self):
        return self.ui.create_row_widget()

    # not thread safe
    def __create_list_item_widget(self, graphic):
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
        # create the graphic specific widget
        if isinstance(graphic, Graphics.PointGraphic):
            graphic_type_label.text = _("Point")
            graphic_widget.add(make_point_type_inspector(self.__document_controller, self.__display_item, graphic))
        elif isinstance(graphic, Graphics.LineProfileGraphic):
            graphic_type_label.text = _("Line Profile")
            graphic_widget.add(make_line_profile_inspector(self.__document_controller, self.__display_item, graphic))
        elif isinstance(graphic, Graphics.LineGraphic):
            graphic_type_label.text = _("Line")
            graphic_widget.add(make_line_type_inspector(self.__document_controller, self.__display_item, graphic))
        elif isinstance(graphic, Graphics.RectangleGraphic):
            graphic_type_label.text = _("Rectangle")
            graphic_widget.add(make_rectangle_type_inspector(self.__document_controller, self.__display_item, graphic, graphic_type_label.text, rotation=True))
        elif isinstance(graphic, Graphics.EllipseGraphic):
            graphic_type_label.text = _("Ellipse")
            graphic_widget.add(make_rectangle_type_inspector(self.__document_controller, self.__display_item, graphic, graphic_type_label.text, rotation=True))
        elif isinstance(graphic, Graphics.IntervalGraphic):
            graphic_type_label.text = _("Interval")
            graphic_widget.add(make_interval_type_inspector(self.__document_controller, self.__display_item, graphic))
        elif isinstance(graphic, Graphics.SpotGraphic):
            graphic_type_label.text = _("Spot")
            graphic_widget.add(make_spot_inspector(self.__document_controller, self.__display_item, graphic, graphic_type_label.text))
        elif isinstance(graphic, Graphics.WedgeGraphic):
            graphic_type_label.text = _("Wedge")
            graphic_widget.add(make_wedge_inspector(self.__document_controller, self.__display_item, graphic))
        elif isinstance(graphic, Graphics.RingGraphic):
            graphic_type_label.text = _("Annular Ring")
            graphic_widget.add(make_ring_inspector(self.__document_controller, self.__display_item, graphic))
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

    def __init__(self, document_model, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable, *, title: str=None, command_id: str=None, is_mergeable: bool=False, **kwargs):
        super().__init__(title if title else _("Change Computation Variable"), command_id=command_id, is_mergeable=is_mergeable)
        self.__document_model = document_model
        self.__computation_proxy = computation.create_proxy()
        self.__variable_index = computation.variables.index(variable)
        self.__properties = variable.save_properties()
        self.__value_dict = kwargs
        self.initialize()

    def close(self):
        self.__document_model = None
        self.__computation_proxy.close()
        self.__computation_proxy = None
        self.__variable_index = None
        self.__properties = None
        self.__value_dict = None
        super().close()

    def perform(self):
        computation = self.__computation_proxy.item
        variable = computation.variables[self.__variable_index]
        for key, value in self.__value_dict.items():
            setattr(variable, key, value)

    def _get_modified_state(self):
        computation = self.__computation_proxy.item
        variable = computation.variables[self.__variable_index]
        return variable.modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state):
        computation = self.__computation_proxy.item
        variable = computation.variables[self.__variable_index]
        variable.modified_state, self.__document_model.modified_state = modified_state

    def _compare_modified_states(self, state1, state2) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return state1[0] == state2[0]

    def _undo(self):
        computation = self.__computation_proxy.item
        variable = computation.variables[self.__variable_index]
        properties = self.__properties
        self.__properties = variable.save_properties()
        variable.restore_properties(properties)

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, ChangeComputationVariableCommand) and self.command_id and self.command_id == command.command_id and self.__computation_proxy.item == command.__computation_proxy.item and self.__variable_index == command.__variable_index


class ChangeComputationVariablePropertyBinding(Binding.PropertyBinding):
    def __init__(self, document_controller, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable, property_name: str, converter=None, fallback=None):
        super().__init__(variable, property_name, converter=converter, fallback=fallback)
        self.__property_name = property_name
        self.__old_source_setter = self.source_setter

        def set_value(value):
            if value != getattr(variable, property_name):
                command = ChangeComputationVariableCommand(document_controller.document_model, computation, variable, title=_("Change Computation"), command_id="change_computation_" + property_name, is_mergeable=True, **{self.__property_name: value})
                command.perform()
                document_controller.push_undo_command(command)

        self.source_setter = set_value


def make_checkbox(document_controller, unbinder: Unbinder, computation, variable):
    ui = document_controller.ui
    column = ui.create_column_widget()
    row = ui.create_row_widget()
    check_box_widget = ui.create_check_box_widget(variable.display_label)
    check_box_widget.widget_id = "value"
    check_box_widget.bind_checked(ChangeComputationVariablePropertyBinding(document_controller, computation, variable, "value"))
    row.add(check_box_widget)
    row.add_stretch()
    column.add(row)
    column.add_spacing(4)
    unbinder.add([computation], [check_box_widget.unbind_checked])
    return column, []


def make_slider_int(document_controller, unbinder: Unbinder, computation, variable, converter):
    ui = document_controller.ui
    column = ui.create_column_widget()
    row = ui.create_row_widget()
    label_widget = ui.create_label_widget(variable.display_label, properties={"width": 80})
    label_widget.bind_text(Binding.PropertyBinding(variable, "display_label"))
    slider_widget = ui.create_slider_widget()
    slider_widget.minimum = int(variable.value_min)
    slider_widget.maximum = int(variable.value_max)
    slider_widget.bind_value(ChangeComputationVariablePropertyBinding(document_controller, computation, variable, "value"))
    slider_widget.widget_id = "slider_value"
    line_edit_widget = ui.create_line_edit_widget(properties={"width": 60})
    line_edit_widget.widget_id = "value"
    line_edit_widget.bind_text(ChangeComputationVariablePropertyBinding(document_controller, computation, variable, "value", converter=converter))
    row.add(label_widget)
    row.add_spacing(8)
    row.add(slider_widget)
    row.add_spacing(8)
    row.add(line_edit_widget)
    row.add_spacing(8)
    column.add(row)
    column.add_spacing(4)
    unbinder.add([computation], [label_widget.unbind_text, slider_widget.unbind_value, line_edit_widget.unbind_text])
    return column, []


def make_slider_float(document_controller, unbinder: Unbinder, computation, variable, converter):
    ui = document_controller.ui
    column = ui.create_column_widget()
    row = ui.create_row_widget()
    label_widget = ui.create_label_widget(variable.display_label, properties={"width": 80})
    label_widget.bind_text(Binding.PropertyBinding(variable, "display_label"))
    f_converter = Converter.FloatToScaledIntegerConverter(1000, variable.value_min, variable.value_max)
    slider_widget = ui.create_slider_widget()
    slider_widget.widget_id = "value"
    slider_widget.minimum = 0
    slider_widget.maximum = 1000
    slider_widget.bind_value(ChangeComputationVariablePropertyBinding(document_controller, computation, variable, "value", converter=f_converter))
    line_edit_widget = ui.create_line_edit_widget(properties={"width": 60})
    line_edit_widget.bind_text(ChangeComputationVariablePropertyBinding(document_controller, computation, variable, "value", converter=converter))
    row.add(label_widget)
    row.add_spacing(8)
    row.add(slider_widget)
    row.add_spacing(8)
    row.add(line_edit_widget)
    row.add_spacing(8)
    column.add(row)
    column.add_spacing(4)
    unbinder.add([computation], [label_widget.unbind_text, slider_widget.unbind_value, line_edit_widget.unbind_text])
    return column, []


def make_field(document_controller, unbinder: Unbinder, computation, variable, converter):
    ui = document_controller.ui
    column = ui.create_column_widget()
    row = ui.create_row_widget()
    label_widget = ui.create_label_widget(variable.display_label, properties={"width": 80})
    label_widget.bind_text(Binding.PropertyBinding(variable, "display_label"))
    line_edit_widget = ui.create_line_edit_widget(properties={"width": 60})
    line_edit_widget.widget_id = "value"
    line_edit_widget.bind_text(ChangeComputationVariablePropertyBinding(document_controller, computation, variable, "value", converter=converter))
    row.add(label_widget)
    row.add_spacing(8)
    row.add(line_edit_widget)
    row.add_stretch()
    column.add(row)
    column.add_spacing(4)
    unbinder.add([computation], [label_widget.unbind_text, line_edit_widget.unbind_text])
    return column, []


def make_choice(document_controller, unbinder: Unbinder, computation, variable, converter):
    ui = typing.cast(UserInterface.UserInterface, document_controller.ui)
    column = ui.create_column_widget()
    row = ui.create_row_widget()
    label_widget = ui.create_label_widget(variable.display_label, properties={"width": 80})
    label_widget.bind_text(Binding.PropertyBinding(variable, "display_label"))
    choices = [(_("None"), "none"), (_("Mapped"), "mapped")]
    choice_widget = ui.create_combo_box_widget(items=choices, item_getter=operator.itemgetter(0))

    class ChoiceConverter:
        def convert(self, value: str) -> int:
            for index, choice in enumerate(choices):
                if choice[1] == value:
                    return index
            return 0
        def convert_back(self, value: int) -> str:
            if value >= 0 and value < len(choices):
                return choices[value][1]
            else:
                return "none"

    choice_widget.bind_current_index(ChangeComputationVariablePropertyBinding(document_controller, computation, variable, "value", converter=ChoiceConverter()))
    row.add(label_widget)
    row.add_spacing(8)
    row.add(choice_widget)
    row.add_stretch()
    column.add(row)
    column.add_spacing(4)
    unbinder.add([computation], [label_widget.unbind_text, choice_widget.unbind_current_index])
    return column, []


def make_image_chooser(document_controller, computation: Symbolic.Computation, variable: Symbolic.ComputationVariable):
    ui = document_controller.ui
    widget = InspectorSectionWidget(ui)
    document_model = document_controller.document_model
    column = ui.create_column_widget()
    row = ui.create_row_widget()
    label_column = ui.create_column_widget()
    label_widget = ui.create_label_widget(variable.display_label, properties={"width": 80})
    label_widget.bind_text(Binding.PropertyBinding(variable, "display_label"))
    label_column.add(label_widget)
    label_column.add_stretch()
    row.add(label_column)
    row.add_spacing(8)
    computation_input = computation.get_input(variable.name)
    data_item = computation_input.data_item if computation_input and not isinstance(computation_input, DataItem.DataItem) else None

    def drop_mime_data(mime_data, x, y):
        display_item = MimeTypes.mime_data_get_display_item(mime_data, document_model)
        data_item = display_item.data_item if display_item else None
        if data_item:
            specified_object = display_item.get_display_data_channel_for_data_item(data_item)
            command = ChangeComputationVariableCommand(document_controller.document_model, computation, variable, specified_object=specified_object, title=_("Change Computation Input"))
            command.perform()
            document_controller.push_undo_command(command)
            return "copy"
        return None

    def data_item_delete():
        command = ChangeComputationVariableCommand(document_controller.document_model, computation, variable, specified_object=None, title=_("Change Computation Input"))
        command.perform()
        document_controller.push_undo_command(command)

    display_item = document_model.get_display_item_for_data_item(data_item)
    data_item_thumbnail_source = DataItemThumbnailWidget.DataItemThumbnailSource(ui, display_item=display_item)
    data_item_chooser_widget = DataItemThumbnailWidget.ThumbnailWidget(ui, data_item_thumbnail_source, Geometry.IntSize(80, 80))

    def thumbnail_widget_drag(mime_data, thumbnail, hot_spot_x, hot_spot_y):
        # use this convoluted base object for drag so that it doesn't disappear after the drag.
        column.drag(mime_data, thumbnail, hot_spot_x, hot_spot_y)

    data_item_chooser_widget.on_drag = thumbnail_widget_drag
    data_item_chooser_widget.on_drop_mime_data = drop_mime_data
    data_item_chooser_widget.on_delete = data_item_delete

    def property_changed(key):
        if key == "specifier":
            computation_input = computation.get_input(variable.name)
            data_item = computation_input.data_item if computation_input else None
            display_item = document_model.get_display_item_for_data_item(data_item)
            data_item_thumbnail_source.set_display_item(display_item)

    property_changed_listener = variable.property_changed_event.listen(property_changed)
    row.add(data_item_chooser_widget)
    row.add_stretch()
    column.add(row)
    column.add_spacing(4)

    widget.add(column)
    widget.add_unbinder([computation], [label_widget.unbind_text])
    widget.add_closeable(property_changed_listener)

    return widget


class VariableWidget(Widgets.CompositeWidgetBase):
    """A composite widget for displaying a 'variable' control.

    Also watches for changes to the variable that require a different UI and rebuilds
    the UI if necessary.

    The content_widget for the CompositeWidgetBase is a column widget and always has
    a single child which is the UI for the variable. The child is replaced if necessary.
    """

    def __init__(self, document_controller, computation, variable):
        super().__init__(document_controller.ui.create_column_widget())
        self.closeables = list()
        self.__unbinder = Unbinder()
        self.__make_widget_from_variable(document_controller, computation, variable)

        def rebuild_variable():
            self.content_widget.remove_all()
            self.__make_widget_from_variable(document_controller, computation, variable)

        self.__variable_needs_rebuild_event_listener = variable.needs_rebuild_event.listen(rebuild_variable)

    def close(self):
        for closeable in self.closeables:
            closeable.close()
        self.__variable_needs_rebuild_event_listener.close()
        self.__variable_needs_rebuild_event_listener = None
        self.__unbinder.close()
        self.__unbinder = None
        super().close()

    def __make_widget_from_variable(self, document_controller, computation, variable):
        ui = document_controller.ui
        if variable.variable_type == "boolean":
            widget, closeables = make_checkbox(document_controller, self.__unbinder, computation, variable)
            self.content_widget.add(widget)
            self.closeables.extend(closeables)
        elif variable.variable_type == "integral" and (True or variable.control_type == "slider") and variable.has_range:
            widget, closeables = make_slider_int(document_controller, self.__unbinder, computation, variable, Converter.IntegerToStringConverter())
            self.content_widget.add(widget)
            self.closeables.extend(closeables)
        elif variable.variable_type == "integral":
            widget, closeables = make_field(document_controller, self.__unbinder, computation, variable, Converter.IntegerToStringConverter())
            self.content_widget.add(widget)
            self.closeables.extend(closeables)
        elif variable.variable_type == "real" and (True or variable.control_type == "slider") and variable.has_range:
            widget, closeables = make_slider_float(document_controller, self.__unbinder, computation, variable, Converter.FloatToStringConverter())
            self.content_widget.add(widget)
            self.closeables.extend(closeables)
        elif variable.variable_type == "real":
            widget, closeables = make_field(document_controller, self.__unbinder, computation, variable, Converter.FloatToStringConverter())
            self.content_widget.add(widget)
            self.closeables.extend(closeables)
        elif variable.variable_type in Symbolic.ComputationVariable.data_item_types:
            self.content_widget.add(make_image_chooser(document_controller, computation, variable))
        elif variable.variable_type == "string" and variable.control_type == "choice":
            widget, closeables = make_choice(document_controller, self.__unbinder, computation, variable, None)
            self.content_widget.add(widget)
            self.closeables.extend(closeables)
        elif variable.variable_type == "string":
            widget, closeables = make_field(document_controller, self.__unbinder, computation, variable, None)
            self.content_widget.add(widget)
            self.closeables.extend(closeables)


class ComputationInspectorSection(InspectorSection):
    def __init__(self, document_controller, data_item: DataItem.DataItem):
        super().__init__(document_controller.ui, "computation", _("Computation"))
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

            def variable_inserted(index: int, variable: Symbolic.ComputationVariable) -> None:
                widget_wrapper = VariableWidget(document_controller, computation, variable)
                self._variables_column_widget.insert(widget_wrapper, index)

            def variable_removed(index: int, variable: Symbolic.ComputationVariable) -> None:
                self._variables_column_widget.remove(self._variables_column_widget.children[index])

            self.__computation_variable_inserted_event_listener = computation.variable_inserted_event.listen(variable_inserted)
            self.__computation_variable_removed_event_listener = computation.variable_removed_event.listen(variable_removed)

            for index, variable in enumerate(computation.variables):
                variable_inserted(index, variable)
        else:
            none_label = self.ui.create_label_widget(_("None"))
            none_label.text_font = "italic"
            none_widget = self.ui.create_row_widget()
            none_widget.add(none_label)
            self.add_widget_to_content(none_widget)
            self.__computation_variable_inserted_event_listener = None
            self.__computation_variable_removed_event_listener = None
        self.finish_widget_content()

    def close(self):
        if self.__computation_variable_inserted_event_listener:
            self.__computation_variable_inserted_event_listener.close()
            self.__computation_variable_inserted_event_listener = None
        if self.__computation_variable_removed_event_listener:
            self.__computation_variable_removed_event_listener.close()
            self.__computation_variable_removed_event_listener = None
        super().close()


from nion.utils import Event

class TextButtonCell:

    def __init__(self, text: str):
        super().__init__()
        self.update_event = Event.Event()
        self.__text = text

    def paint_cell(self, drawing_context, rect, style):

        # disabled (default is enabled)
        # checked, partial (default is unchecked)
        # hover, active (default is none)

        drawing_context.text_baseline = "middle"
        drawing_context.text_align = "center"
        drawing_context.fill_style = "#000"
        drawing_context.fill_text(self.__text, rect.center.x, rect.center.y)

        overlay_color = None
        if "disabled" in style:
            overlay_color = "rgba(255, 255, 255, 0.5)"
        else:
            if "active" in style:
                overlay_color = "rgba(128, 128, 128, 0.5)"
            elif "hover" in style:
                overlay_color = "rgba(128, 128, 128, 0.1)"

        drawing_context.fill_style = "#444"
        drawing_context.fill()
        drawing_context.stroke_style = "#444"
        drawing_context.stroke()

        if overlay_color:
            rect_args = rect[0][1], rect[0][0], rect[1][1], rect[1][0]
            drawing_context.begin_path()
            drawing_context.rect(*rect_args)
            drawing_context.fill_style = overlay_color
            drawing_context.fill()


class TextButtonCanvasItem(CanvasItem.CellCanvasItem):

    def __init__(self, text: str):
        super().__init__()
        self.cell = TextButtonCell(text)
        self.wants_mouse_events = True
        self.on_button_clicked = None

    def close(self):
        self.on_button_clicked = None
        super().close()

    def mouse_entered(self):
        self._mouse_inside = True

    def mouse_exited(self):
        self._mouse_inside = False

    def mouse_pressed(self, x, y, modifiers):
        self._mouse_pressed = True

    def mouse_released(self, x, y, modifiers):
        self._mouse_pressed = False

    def mouse_clicked(self, x, y, modifiers):
        if self.enabled:
            if self.on_button_clicked:
                self.on_button_clicked()
        return True


class TextPushButtonWidget(Widgets.CompositeWidgetBase):
    def __init__(self, ui, text: str):
        super().__init__(ui.create_column_widget())
        self.on_button_clicked = None
        font = "normal 11px serif"
        font_metrics = ui.get_font_metrics(font, text)
        text_button_canvas_item = TextButtonCanvasItem(text)
        text_button_canvas_item.sizing.set_fixed_size(Geometry.IntSize(height=font_metrics.height + 6, width=font_metrics.width + 6))

        def button_clicked():
            if callable(self.on_button_clicked):
                self.on_button_clicked()

        text_button_canvas_item.on_button_clicked = button_clicked

        text_button_canvas_widget = ui.create_canvas_widget(properties={"height": 20, "width": 20})
        text_button_canvas_widget.canvas_item.add_canvas_item(text_button_canvas_item)
        # ugh. this is a partially working stop-gap when a canvas item is in a widget it will not get mouse exited reliably
        text_button_canvas_widget.on_mouse_exited = text_button_canvas_item.root_container.canvas_widget.on_mouse_exited

        self.content_widget.add(text_button_canvas_widget)


class RemoveDisplayDataChannelCommand(Undo.UndoableCommand):

    def __init__(self, document_controller, display_item: DisplayItem.DisplayItem, display_data_channel: DisplayItem.DisplayDataChannel):
        super().__init__(_("Remove Data Item"))
        self.__document_controller = document_controller
        self.__display_item_proxy = display_item.create_proxy()
        self.__old_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
        self.__new_workspace_layout = None
        self.__display_data_channel_index = display_item.display_data_channels.index(display_data_channel)
        self.__old_display_properties = display_item.save_properties()
        self.__undelete_logs = list()
        self.initialize()

    def close(self):
        self.__document_controller = None
        self.__display_item_proxy.close()
        self.__display_item_proxy = None
        self.__old_workspace_layout = None
        self.__new_workspace_layout = None
        self.__display_data_channel_index = None
        self.__old_display_properties = None
        for undelete_log in self.__undelete_logs:
            undelete_log.close()
        self.__undelete_logs = None
        super().close()

    def perform(self):
        display_item = self.__display_item_proxy.item
        display_data_channel = display_item.display_data_channels[self.__display_data_channel_index]
        self.__undelete_logs.append(display_item.remove_display_data_channel(display_data_channel, safe=True))

    def _get_modified_state(self):
        display_item = self.__display_item_proxy.item
        return display_item.modified_state, self.__document_controller.document_model.modified_state

    def _set_modified_state(self, modified_state):
        display_item = self.__display_item_proxy.item
        display_item.modified_state, self.__document_controller.document_model.modified_state = modified_state

    def _undo(self):
        self.__new_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
        for undelete_log in reversed(self.__undelete_logs):
            self.__document_controller.document_model.undelete_all(undelete_log)
            undelete_log.close()
        self.__undelete_logs.clear()
        self.__document_controller.workspace_controller.reconstruct(self.__old_workspace_layout)
        display_item = self.__display_item_proxy.item
        display_item.restore_properties(self.__old_display_properties)

    def _redo(self):
        self.perform()
        self.__document_controller.workspace_controller.reconstruct(self.__new_workspace_layout)


class DataItemLabelWidget(Widgets.CompositeWidgetBase):
    def __init__(self, ui, document_controller, display_item: DisplayItem.DisplayItem, index: int):
        super().__init__(ui.create_column_widget())

        remove_icon = "\N{MULTIPLICATION X}" if sys.platform != "darwin" else "\N{BALLOT X}"
        remove_display_data_channel_button = TextPushButtonWidget(ui, remove_icon)

        section_title_row = ui.create_row_widget()
        section_title_label_widget = ui.create_label_widget()
        section_title_label_widget.text_font = "bold"
        section_title_label_widget.text = "{} #{}".format(_("Data"), index)
        section_title_row.add_spacing(20)
        section_title_row.add(section_title_label_widget)
        section_title_row.add_stretch()
        section_title_row.add(remove_display_data_channel_button)
        section_title_row.add_spacing(20)

        self.content_widget.add(section_title_row)
        self.content_widget.add_spacing(4)

        display_data_channel = display_item.display_data_channels[index]

        def remove_display_data_channel():
            command = RemoveDisplayDataChannelCommand(document_controller, display_item, display_data_channel)
            command.perform()
            document_controller.push_undo_command(command)

        remove_display_data_channel_button.on_button_clicked = remove_display_data_channel


class DataItemGroupWidget(Widgets.CompositeWidgetBase):
    def __init__(self, ui, document_controller, display_item: DisplayItem.DisplayItem, index: int):
        super().__init__(ui.create_column_widget())

        self.on_rebuild_display_data_channels = None

        self.__ui = ui
        self.__document_controller = document_controller
        self.__display_item = display_item
        self.__index = index

        self.__build()

        self.__display_item_item_inserted = None
        self.__display_item_item_removed = None

        def display_item_item_inserted(key, value, before_index):
            if key == "display_data_channels":
                if callable(self.on_rebuild_display_data_channels):
                    self.on_rebuild_display_data_channels()

        def display_item_item_removed(key, value, index):
            if key == "display_data_channels":
                if callable(self.on_rebuild_display_data_channels):
                    self.on_rebuild_display_data_channels()

        self.__display_item_item_inserted = self.__display_item.item_inserted_event.listen(display_item_item_inserted)
        self.__display_item_item_removed = self.__display_item.item_removed_event.listen(display_item_item_removed)

    def close(self):
        self.__detach_listeners()
        self.__ui = None
        self.__document_controller = None
        self.__display_item = None
        super().close()

    def __detach_listeners(self):
        if self.__display_item_item_inserted:
            self.__display_item_item_inserted.close()
            self.__display_item_item_inserted = None
        if self.__display_item_item_removed:
            self.__display_item_item_removed.close()
            self.__display_item_item_removed = None

    def __build(self):
        if len(self.__display_item.display_data_channels) > 1:
            self.content_widget.add(DataItemLabelWidget(self.__ui, self.__document_controller, self.__display_item, self.__index))
        display_data_channel = self.__display_item.display_data_channels[self.__index]
        data_item = display_data_channel.data_item
        self.content_widget.add(DataInfoInspectorSection(self.__document_controller, display_data_channel))
        self.content_widget.add(CalibrationsInspectorSection(self.__document_controller, display_data_channel, self.__display_item))
        self.content_widget.add(SessionInspectorSection(self.__document_controller, data_item))
        if display_data_channel.is_sequence:
            self.content_widget.add(SequenceInspectorSection(self.__document_controller, display_data_channel))
        if display_data_channel.is_sliced:
            self.content_widget.add(SliceInspectorSection(self.__document_controller, display_data_channel))
        elif display_data_channel.is_collection:
            self.content_widget.add(CollectionIndexInspectorSection(self.__document_controller, display_data_channel))
        self.content_widget.add(ComputationInspectorSection(self.__document_controller, data_item))


class DisplayInspector(Widgets.CompositeWidgetBase):
    """A class to manage creation of a widget representing an inspector for a display item.

    A new data item inspector is created whenever the display item changes, but not when the content of the items
    within the display item mutate.
    """

    def __init__(self, ui, document_controller, display_item: DisplayItem.DisplayItem):
        super().__init__(ui.create_column_widget())

        self.ui = ui
        self.__unbinder = Unbinder()

        self.on_rebuild = None

        content_widget = self.content_widget
        content_widget.add_spacing(4)
        if display_item:
            title_row = self.ui.create_row_widget()
            title_label_widget = self.ui.create_label_widget()
            title_label_widget.text_font = "bold"
            title_label_widget.bind_text(Binding.PropertyBinding(display_item, "title"))
            title_row.add_spacing(20)
            title_row.add(title_label_widget)
            title_row.add_stretch()
            content_widget.add(title_row)
            content_widget.add_spacing(4)
            self.__unbinder.add([display_item], [title_label_widget.unbind_text])

        self.__focus_default = None
        inspector_sections = list()
        if display_item and display_item.graphic_selection.has_selection:
            inspector_sections.append(GraphicsInspectorSection(document_controller, display_item, selected_only=True))
            def focus_default():
                pass
            self.__focus_default = focus_default
        elif display_item and display_item.used_display_type == "line_plot":
            inspector_sections.append(InfoInspectorSection(document_controller, display_item))
            inspector_sections.append(LinePlotDisplayInspectorSection(document_controller, display_item))
            for index, display_data_channel in enumerate(display_item.display_data_channels):
                data_item_group_widget = DataItemGroupWidget(self.ui, document_controller, display_item, index)
                def rebuild():
                    if callable(self.on_rebuild):
                        self.on_rebuild()
                data_item_group_widget.on_rebuild_display_data_channels = rebuild
                data_item_group_widget.on_rebuild_display_layers = rebuild
                inspector_sections.append(data_item_group_widget)
            line_plot_display_layers_inspector_section = LinePlotDisplayLayersInspectorSection(document_controller, display_item)
            inspector_sections.append(line_plot_display_layers_inspector_section)
            if len(display_item.graphics) > 0:
                inspector_sections.append(GraphicsInspectorSection(document_controller, display_item))
            def focus_default():
                inspector_sections[0].info_title_label.focused = True
                inspector_sections[0].info_title_label.request_refocus()
            self.__focus_default = focus_default
        elif display_item and display_item.used_display_type == "image":
            inspector_sections.append(InfoInspectorSection(document_controller, display_item))
            inspector_sections.append(ImageDisplayInspectorSection(document_controller, display_item))
            for display_data_channel in display_item.display_data_channels:
                data_item = display_data_channel.data_item
                inspector_sections.append(ImageDataInspectorSection(document_controller, display_data_channel, display_item))
                inspector_sections.append(CalibrationsInspectorSection(document_controller, display_data_channel, display_item))
                inspector_sections.append(SessionInspectorSection(document_controller, data_item))
                if display_data_channel.is_sequence:
                    inspector_sections.append(SequenceInspectorSection(document_controller, display_data_channel))
                if display_data_channel.is_sliced:
                    inspector_sections.append(SliceInspectorSection(document_controller, display_data_channel))
                elif display_data_channel.is_collection:
                    inspector_sections.append(CollectionIndexInspectorSection(document_controller, display_data_channel))
                inspector_sections.append(ComputationInspectorSection(document_controller, data_item))
            if len(display_item.graphics) > 0:
                inspector_sections.append(GraphicsInspectorSection(document_controller, display_item))
            def focus_default():
                inspector_sections[0].info_title_label.focused = True
                inspector_sections[0].info_title_label.request_refocus()
            self.__focus_default = focus_default
        elif display_item:
            inspector_sections.append(InfoInspectorSection(document_controller, display_item))
            for display_data_channel in display_item.display_data_channels:
                data_item = display_data_channel.data_item
                inspector_sections.append(DataInfoInspectorSection(document_controller, display_data_channel))
                inspector_sections.append(SessionInspectorSection(document_controller, data_item))
            def focus_default():
                inspector_sections[0].info_title_label.focused = True
                inspector_sections[0].info_title_label.request_refocus()
            self.__focus_default = focus_default

        for inspector_section in inspector_sections:
            content_widget.add(inspector_section)

        content_widget.add_stretch()

    def close(self) -> None:
        self.__unbinder.close()
        self.__unbinder = None
        super().close()

    def _get_inspectors(self):
        """ Return a copy of the list of inspectors. """
        return copy.copy(self.content_widget.children[:-1])

    def focus_default(self):
        if self.__focus_default:
            self.__focus_default()


class DeclarativeImageChooserConstructor:

    def __init__(self, app):
        self.__app = app

    def construct(self, d_type: str, ui: UserInterface.UserInterface, window, d: typing.Mapping, handler, finishes: typing.Sequence[typing.Callable[[], None]] = None):
        if d_type == "image_chooser":
            properties = Declarative.construct_sizing_properties(d)
            thumbnail_source = DataItemThumbnailWidget.DataItemThumbnailSource(ui, window=window)

            def drop_mime_data(mime_data: UserInterface.MimeData, x: int, y: int) -> typing.Optional[str]:
                document_model = self.__app.document_model
                display_item = MimeTypes.mime_data_get_display_item(mime_data, document_model)
                thumbnail_source.display_item = display_item
                if display_item:
                    return "copy"
                return None

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


class DeclarativeDataSourceChooserConstructor:

    def __init__(self, app):
        self.__app = app

    def construct(self, d_type: str, ui: UserInterface.UserInterface, window, d: typing.Mapping, handler, finishes: typing.Sequence[typing.Callable[[], None]] = None) -> typing.Optional[UserInterface.Widget]:
        if d_type == "data_source_chooser":
            properties = Declarative.construct_sizing_properties(d)
            thumbnail_source = DataItemThumbnailWidget.DataItemThumbnailSource(ui, window=window)

            def drop_mime_data(mime_data: UserInterface.MimeData, x: int, y: int) -> typing.Optional[str]:
                on_drop_mime_data_method = d.get("on_drop_mime_data")
                if callable(getattr(handler, on_drop_mime_data_method, None)):
                    return getattr(handler, on_drop_mime_data_method)(mime_data, x, y)
                return None

            def data_item_delete():
                on_delete_method = d.get("on_delete")
                if callable(getattr(handler, on_delete_method, None)):
                    return getattr(handler, on_delete_method)()

            widget = DataItemThumbnailWidget.ThumbnailWidget(ui, thumbnail_source, properties=properties, is_expanding=True)
            widget.on_drag = widget.drag
            widget.on_drop_mime_data = drop_mime_data
            widget.on_delete = data_item_delete

            if handler:
                Declarative.connect_name(widget, d, handler)
                Declarative.connect_reference_value(thumbnail_source, d, handler, "display_item", finishes)
                Declarative.connect_attributes(widget, d, handler, finishes)

            return widget

        return None
