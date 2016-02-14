# futures
from __future__ import absolute_import

# standard libraries
import copy
import gettext
import json
import logging
import weakref

# third party libraries
# None

# local libraries
from nion.swift.model import DataItem
from nion.swift import Panel
from nion.ui import CanvasItem
from nion.ui import Event
from nion.ui import Geometry
from nion.ui import TreeCanvasItem

_ = gettext.gettext


class MetadataModel(object):
    """Represents metadata. Tracks a display specifier for changes to it and its metadata content.

    Provides read/write access to metadata via the property.

    Provides a metadata_changed event, always fired on UI thread.
    """

    def __init__(self, document_controller, display_specifier_binding):
        self.__weak_document_controller = weakref.ref(document_controller)
        self.__display_specifier = DataItem.DisplaySpecifier()
        # thread safe.
        def data_item_changed(data_item):
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            def update_display_specifier():
                self.__set_display_specifier(display_specifier)
            self.document_controller.add_task("update_display_specifier" + str(id(self)), update_display_specifier)
        self.__data_item_changed_event_listener = display_specifier_binding.data_item_changed_event.listen(data_item_changed)
        self.__set_display_specifier(DataItem.DisplaySpecifier())
        self.__metadata_changed_event_listener = None
        self.__metadata = None
        self.metadata_changed_event = Event.Event()

    def close(self):
        self.document_controller.clear_task("update_display_specifier" + str(id(self)))
        self.__data_item_changed_event_listener.close()
        self.__data_item_changed_event_listener = None
        self.__set_display_specifier(DataItem.DisplaySpecifier())

    @property
    def document_controller(self):
        return self.__weak_document_controller()

    @property
    def metadata(self):
        return self.__metadata

    @metadata.setter
    def metadata(self, metadata):
        buffered_data_source = self.__display_specifier.buffered_data_source
        if buffered_data_source:
            buffered_data_source.set_metadata(metadata)

    def __metadata_changed(self, buffered_data_source):
        if buffered_data_source:
            metadata = buffered_data_source.metadata
            if self.__metadata != metadata:
                self.__metadata = metadata
                self.metadata_changed_event.fire(self.__metadata)

    # not thread safe
    def __set_display_specifier(self, display_specifier):
        if self.__display_specifier != display_specifier:
            if self.__metadata_changed_event_listener:
                self.__metadata_changed_event_listener.close()
                self.__metadata_changed_event_listener = None
            self.__display_specifier = copy.copy(display_specifier)
            # update the expression text
            buffered_data_source = self.__display_specifier.buffered_data_source
            if buffered_data_source:
                metadata = buffered_data_source.metadata
                def metadata_changed():
                    self.__metadata_changed(buffered_data_source)
                self.__metadata_changed_event_listener = buffered_data_source.metadata_changed_event.listen(metadata_changed)
            self.__metadata_changed(buffered_data_source)


class MetadataEditorTreeDelegate:
    def __init__(self, metadata):
        self.__metadata = metadata
        self.__expanded_value_paths = set()

    @property
    def metadata(self):
        return self.__metadata

    @metadata.setter
    def metadata(self, value):
        self.__metadata = value

    def __is_expanded(self, value_path):
        return json.dumps(value_path) in self.__expanded_value_paths

    def toggle_is_expanded(self, value_path):
        value_path_key = json.dumps(value_path)
        if value_path_key in self.__expanded_value_paths:
            self.__expanded_value_paths.remove(value_path_key)
        else:
            self.__expanded_value_paths.add(value_path_key)

    def build_items(self, get_font_metrics_fn, item_width):
        items = list()
        text_font = "normal 12px monospace"

        def visit_value(value_path, value):
            if isinstance(value, dict):
                is_expanded = self.__is_expanded(value_path)
                format_str = "{} {{{}}}"
                text_item = CanvasItem.StaticTextCanvasItem(format_str.format(value_path[-1], len(value)))
                text_item.font = text_font
                text_item.size_to_content(get_font_metrics_fn)
                items.append((text_item, "parent", is_expanded, value_path))
                if is_expanded:
                    visit_dict(value, value_path)
            elif isinstance(value, list) or isinstance(value, tuple):
                is_expanded = self.__is_expanded(value_path)
                format_str = "{} ({})"
                text_item = CanvasItem.StaticTextCanvasItem(format_str.format(value_path[-1], len(value)))
                text_item.font = text_font
                text_item.size_to_content(get_font_metrics_fn)
                items.append((text_item, "parent", is_expanded, value_path))
                if is_expanded:
                    visit_list(value, value_path)
            else:
                text_item = CanvasItem.StaticTextCanvasItem("{}: {}".format(value_path[-1], value))
                text_item.font = text_font
                text_item.size_to_content(get_font_metrics_fn)
                items.append((text_item, "child", None, value_path))

        def visit_list(l, path):
            for index, value in enumerate(l):
                value_path = path + (index,)
                visit_value(value_path, value)

        def visit_dict(d, path):
            for key in sorted(d.keys()):
                value = d[key]
                value_path = path + (key,)
                visit_value(value_path, value)

        visit_dict(self.__metadata, ())

        return items


class MetadataPanel(Panel.Panel):
    """Provide a panel to edit metadata."""

    def __init__(self, document_controller, panel_id, properties):
        super(MetadataPanel, self).__init__(document_controller, panel_id, _("Metadata"))

        ui = self.ui

        self.__display_binding = document_controller.create_selected_data_item_binding()
        self.__metadata_model = MetadataModel(document_controller, self.__display_binding)

        delegate = MetadataEditorTreeDelegate(dict())

        metadata_editor_widget = ui.create_canvas_widget()
        metadata_editor_canvas_item = TreeCanvasItem.TreeCanvasItem(ui.get_font_metrics, delegate)
        metadata_editor_widget.canvas_item.add_canvas_item(metadata_editor_canvas_item)

        column = self.ui.create_column_widget()
        column.add_spacing(6)
        column.add(metadata_editor_widget)
        column.add_spacing(6)

        def metadata_changed(metadata):
            delegate.metadata = metadata
            metadata_editor_canvas_item.reconstruct()

        self.__metadata_changed_event_listener = self.__metadata_model.metadata_changed_event.listen(metadata_changed)

        self.widget = column

        self.__metadata_editor_canvas_item = metadata_editor_canvas_item

    def close(self):
        self.__metadata_changed_event_listener.close()
        self.__metadata_changed_event_listener = None
        self.__metadata_model.close()
        self.__metadata_model = None
        self.__display_binding.close()
        self.__display_binding = None
        super(MetadataPanel, self).close()

    @property
    def _metadata_editor_canvas_item_for_testing(self):
        return self.__metadata_editor_canvas_item

    @property
    def _metadata_model_for_testing(self):
        return self.__metadata_model
