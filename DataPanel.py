# standard libraries
import copy
import functools
import gettext
import logging
import threading
import time
import uuid
import weakref

# third party libraries
# None

# local libraries
from nion.swift import Panel
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.ui import CanvasItem
from nion.ui import Geometry
from nion.ui import GridCanvasItem
from nion.ui import Observable
from nion.ui import Selection

_ = gettext.gettext


"""
    The data panel has two parts:

    (1) a selection of what collection is displayed, which may be a data group, smart data group,
    or the whole document. If the whole document, then an optional filter may also be applied.
    "within the last 24 hours" would be an example filter.

    (2) the list of data items from the collection. the user may further refine the list of
    items by filtering by additional criteria. the user also chooses the sorting on the list of
    data items.

"""


# persistently store a data specifier
class DataPanelSelection(object):
    def __init__(self, data_group=None, data_item=None, filter_id=None):
        self.__data_group = data_group
        self.__data_item = data_item
        self.__filter_id = filter_id
    def __get_data_group(self):
        return self.__data_group
    data_group = property(__get_data_group)
    def __get_data_item(self):
        return self.__data_item
    data_item = property(__get_data_item)
    def __get_filter_id(self):
        return self.__filter_id
    filter_id = property(__get_filter_id)
    def __str__(self):
        return "(%s,%s)" % (str(self.data_group), str(self.data_item))


class DisplayItem(object):

    def __init__(self, data_item, dispatch_task, ui):
        self.data_item = data_item
        self.dispatch_task = dispatch_task
        self.ui = ui
        # add listener for data_item_content_changed, which handles items not handled by thumbnail, such as the
        # reference display
        data_item.add_listener(self)
        # grab the display specifier and if there is a display, add a listener to that also for
        # display_processor_needs_recompute, display_processor_data_updated, which handle thumbnail updating.
        display_specifier = data_item.primary_display_specifier
        if display_specifier.display:
            display_specifier.display.add_listener(self)
        self.needs_update_event = Observable.Event()

    def close(self):
        # remove the listener.
        display_specifier = self.data_item.primary_display_specifier
        if display_specifier.display:
            display_specifier.display.remove_listener(self)
        self.data_item.remove_listener(self)

    @property
    def thumbnail(self):
        display = self.data_item.primary_display_specifier.display
        if display:
            display.get_processor("thumbnail").recompute_if_necessary(self.dispatch_task, self.ui)
            return display.get_processed_data("thumbnail")
        return None

    @property
    def title_str(self):
        data_item = self.data_item
        return data_item.displayed_title

    @property
    def format_str(self):
        data_item = self.data_item
        display_specifier = data_item.primary_display_specifier
        buffered_data_source = display_specifier.buffered_data_source
        if buffered_data_source:
            data_and_calibration = buffered_data_source.data_and_calibration
            if data_and_calibration:
                return data_and_calibration.size_and_data_format_as_string
        return str()

    @property
    def datetime_str(self):
        data_item = self.data_item
        return data_item.created_local_as_string

    @property
    def status_str(self):
        data_item = self.data_item
        if data_item.is_live:
            display_specifier = data_item.primary_display_specifier
            buffered_data_source = display_specifier.buffered_data_source
            if buffered_data_source:
                data_and_calibration = buffered_data_source.data_and_calibration
                if data_and_calibration:
                    live_metadata = buffered_data_source.metadata.get("hardware_source", dict())
                    frame_index_str = str(live_metadata.get("frame_index", str()))
                    partial_str = "{0:d}/{1:d}".format(live_metadata.get("valid_rows"), data_and_calibration.dimensional_shape[-1]) if "valid_rows" in live_metadata else str()
                    return "{0:s} {1:s} {2:s}".format(_("Live"), frame_index_str, partial_str)
        return str()

    def get_mime_data(self):
        data_item = self.data_item
        mime_data = self.ui.create_mime_data()
        mime_data.set_data_as_string("text/data_item_uuid", str(data_item.uuid))
        return mime_data

    def drag_started(self, x, y, modifiers):
        data_item = self.data_item
        mime_data = self.get_mime_data()
        display_specifier = data_item.primary_display_specifier
        display = display_specifier.display
        thumbnail_data = display.get_processed_data("thumbnail") if display else None
        return mime_data, thumbnail_data

    # data_item_content_changed is received from data items tracked in this model. the connection is established
    # in add_data_item using add_listener.
    def data_item_content_changed(self, data_item, changes):
        self.needs_update_event.fire()

    # notification from display
    def display_processor_needs_recompute(self, display, processor):
        if processor == display.get_processor("thumbnail"):
            processor.recompute_if_necessary(self.dispatch_task, self.ui)

    # notification from display
    def display_processor_data_updated(self, display, processor):
        if processor == display.get_processor("thumbnail"):
            self.needs_update_event.fire()


class DataListController(object):
    """Control a list of display items in a list widget.

    The following properties are available:
        selected_indexes (r/o)

    The following methods can be called:
        close()
        periodic()
        set_selected_index(index)
        set_display_items(display_items) - used to initialize the data items, ui thread
        display_item_inserted(display_item, before_index) - ui thread
        display_item_removed(index) - ui thread

    The controller provides the following callbacks:
        on_delete_display_items(display_items)
        on_selection_changed(display_items)
        on_display_item_double_clicked(display_item)
        on_focus_changed(focused)
        on_context_menu_event(display_item, x, y, gx, gy)

    Display items should respond to these properties and methods and events:
        (method) close()
        (property, read-only) thumbnail
        (property, read-only) title_str
        (property, read-only) datetime_str
        (property, read-only) format_str
        (property, read-only) status_str
        (method) get_mime_data()
        (method) drag_started(x, y, modifiers), returns mime_data, thumbnail_data
    """

    def __init__(self, ui):
        self.ui = ui
        self.list_model_controller = self.ui.create_list_model_controller(["display"])
        self.list_model_controller.on_item_mime_data = self.__item_mime_data
        self.list_model_controller.supported_drop_actions = self.list_model_controller.DRAG | self.list_model_controller.DROP
        # changed data items keep track of items whose content has changed
        # the content changed messages may come from a thread so have to be
        # moved to the main thread via this object.
        self.__changed_display_items = False
        self.__changed_display_items_mutex = threading.RLock()
        self.__changed_display_items_last = 0
        self.on_delete_display_items = None
        self.on_selection_changed = None
        self.on_display_item_double_clicked = None
        self.on_focus_changed = None
        self.on_context_menu_event = None

        def list_widget_key_pressed(indexes, key):
            if key.is_delete:
                self._delete_pressed(indexes)
            return False

        def list_widget_selection_changed(indexes):
            if self.on_selection_changed:
                self.on_selection_changed([self.__display_items[index] for index in indexes])

        def list_widget_item_double_clicked(index):
            if self.on_display_item_double_clicked:
                self.on_display_item_double_clicked(self.__display_items[index])

        def list_widget_on_focus_changed(focused):
            if self.on_focus_changed:
                self.on_focus_changed(focused)

        def list_widget_context_menu_event(x, y, gx, gy):
            index = self.list_widget.get_row_at_pos(x, y)
            display_item = self.__display_items[index] if 0 < index < len(self.__display_items) else None
            if display_item and self.on_context_menu_event:
                self.on_context_menu_event(display_item, x, y, gx, gy)

        self.list_widget = self.ui.create_list_widget(properties={"min-height": 240})
        self.list_widget.selection_mode = "extended"
        self.list_widget.list_model_controller = self.list_model_controller
        self.list_widget.on_paint = self.paint
        self.list_widget.on_selection_changed = list_widget_selection_changed
        self.list_widget.on_key_pressed = list_widget_key_pressed
        self.list_widget.on_display_item_double_clicked = list_widget_item_double_clicked
        self.list_widget.on_focus_changed = list_widget_on_focus_changed
        self.list_widget.on_context_menu_event = list_widget_context_menu_event

        self.widget = self.list_widget

    def close(self):
        for display_item_needs_update_listener in self.__display_item_needs_update_listeners:
            display_item_needs_update_listener.close()
        self.__display_item_needs_update_listeners = None
        self.__display_items = None
        self.list_model_controller.close()
        self.list_model_controller = None

    def periodic(self):
        # handle the 'changed' stuff
        with self.__changed_display_items_mutex:
            current_time = time.time()
            if current_time - self.__changed_display_items_last > 0.5:
                changed_display_items = self.__changed_display_items
                self.__changed_display_items = False
                self.__changed_display_items_last = current_time
            else:
                changed_display_items = False
        if changed_display_items:
            self.list_model_controller.data_changed()

    @property
    def selected_indexes(self):
        return self.list_widget.selected_indexes

    def set_selected_index(self, index):
        self.list_widget.current_index = index

    # return a dict with key value pairs. these methods are here for testing only.
    def _get_model_data(self, index):
        return self.list_model_controller.model[index]

    def _get_model_data_count(self):
        return len(self.list_model_controller.model)

    # this message comes from the canvas item when delete key is pressed
    def _delete_pressed(self, indexes):
        if self.on_delete_display_items:
            self.on_delete_display_items([self.__display_items[index] for index in indexes])

    def __display_item_needs_update(self):
        with self.__changed_display_items_mutex:
            self.__changed_display_items = True

    # call this method to initialize the display items
    # not thread safe
    def set_display_items(self, display_items):
        self.__display_items = copy.copy(display_items)
        self.__display_item_needs_update_listeners = [display_item.needs_update_event.listen(self.__display_item_needs_update) for display_item in self.__display_items]

    # call this method to insert a display item
    # not thread safe
    def display_item_inserted(self, display_item, before_index):
        self.__display_items.insert(before_index, display_item)
        self.__display_item_needs_update_listeners.insert(before_index, display_item.needs_update_event.listen(self.__display_item_needs_update))
        # do the insert
        properties = { "display": display_item.title_str }
        self.list_model_controller.begin_insert(before_index, before_index)
        self.list_model_controller.model.insert(before_index, properties)
        self.list_model_controller.end_insert()

    # call this method to remove a display item (by index)
    # not thread safe
    def display_item_removed(self, index):
        self.__display_item_needs_update_listeners[index].close()
        del self.__display_item_needs_update_listeners[index]
        del self.__display_items[index]
        # manage the item model
        self.list_model_controller.begin_remove(index, index)
        del self.list_model_controller.model[index]
        self.list_model_controller.end_remove()

    def __item_mime_data(self, row):
        display_item = self.__display_items[row]
        return display_item.get_mime_data()

    # this message comes from the styled item delegate
    # data items are actually hierarchical in nature,
    def paint(self, drawing_context, options):
        rect = ((options["rect"]["top"], options["rect"]["left"]), (options["rect"]["height"], options["rect"]["width"]))
        index = options["index"]["row"]
        display_item = self.__display_items[index]
        drawing_context.save()
        try:
            thumbnail_data = display_item.thumbnail
            if thumbnail_data is not None:
                draw_rect = ((rect[0][0] + 4, rect[0][1] + 4), (72, 72))
                draw_rect = Geometry.fit_to_size(draw_rect, thumbnail_data.shape)
                drawing_context.draw_image(thumbnail_data, draw_rect[0][1], draw_rect[0][0], draw_rect[1][1], draw_rect[1][0])
            drawing_context.fill_style = "#000"
            drawing_context.fill_text(display_item.title_str, rect[0][1] + 4 + 72 + 4, rect[0][0] + 4 + 12)
            drawing_context.font = "11px italic"
            drawing_context.fill_text(display_item.format_str, rect[0][1] + 4 + 72 + 4, rect[0][0] + 4 + 12 + 15)
            drawing_context.font = "11px italic"
            drawing_context.fill_text(display_item.datetime_str, rect[0][1] + 4 + 72 + 4, rect[0][0] + 4 + 12 + 15 + 15)
            drawing_context.font = "11px italic"
            drawing_context.fill_text(display_item.status_str, rect[0][1] + 4 + 72 + 4, rect[0][0] + 4 + 12 + 15 + 15 + 15)
        finally:
            drawing_context.restore()


class DataGridController(object):
    """Control a grid of display items in a grid widget.

    The following properties are available:
        selected_indexes (r/o)

    The following methods can be called:
        close()
        periodic()
        set_selected_index(index)
        set_display_items(display_items) - used to initialize the data items, ui thread
        display_item_inserted(display_item, before_index) - ui thread
        display_item_removed(index) - ui thread

    The controller provides the following callbacks:
        on_delete_display_items(display_items)
        on_selection_changed(display_items)
        on_display_item_double_clicked(display_item)
        on_focus_changed(focused)
        on_context_menu_event(display_item, x, y, gx, gy)

    Display items should respond to these properties and methods and events:
        (method) close()
        (property, read-only) thumbnail
        (property, read-only) title_str
        (property, read-only) datetime_str
        (property, read-only) format_str
        (property, read-only) status_str
        (method) get_mime_data()
        (method) drag_started(x, y, modifiers), returns mime_data, thumbnail_data
    """

    def __init__(self, ui):
        super(DataGridController, self).__init__()
        self.ui = ui
        self.root_canvas_item = CanvasItem.RootCanvasItem(ui)
        self.on_delete_display_items = None

        class GridCanvasItemDelegate(object):
            def __init__(self, data_grid_controller):
                self.__data_grid_controller = data_grid_controller

            @property
            def item_count(self):
                return self.__data_grid_controller.display_item_count

            def get_item_thumbnail(self, index):
                return self.__data_grid_controller.get_display_item_thumbnail(index)

            def is_item_selected(self, index):
                return self.__data_grid_controller.selection.contains(index)

            def extend_selection(self, index):
                self.__data_grid_controller.selection.extend(index)

            def toggle_selection(self, index):
                self.__data_grid_controller.selection.toggle(index)

            def set_selection(self, index):
                self.__data_grid_controller.selection.set(index)

            def on_context_menu_event(self, index, x, y, gx, gy):
                self.__data_grid_controller.context_menu_event(index, x, y, gx, gy)

            def on_delete_pressed(self):
                self.__data_grid_controller._delete_pressed()

            def on_drag_started(self, index, x, y, modifiers):
                self.__data_grid_controller.drag_started(index, x, y, modifiers)

        self.icon_view_canvas_item = GridCanvasItem.GridCanvasItem(GridCanvasItemDelegate(self))
        def icon_view_canvas_item_focus_changed(focused):
            self.icon_view_canvas_item.update()
            if self.on_focus_changed:
                self.on_focus_changed(focused)
        self.icon_view_canvas_item.on_focus_changed = icon_view_canvas_item_focus_changed
        self.scroll_area_canvas_item = CanvasItem.ScrollAreaCanvasItem(self.icon_view_canvas_item)
        self.scroll_bar_canvas_item = CanvasItem.ScrollBarCanvasItem(self.scroll_area_canvas_item)
        self.scroll_group_canvas_item = CanvasItem.CanvasItemComposition()
        self.scroll_group_canvas_item.layout = CanvasItem.CanvasItemRowLayout()
        self.scroll_group_canvas_item.add_canvas_item(self.scroll_area_canvas_item)
        self.scroll_group_canvas_item.add_canvas_item(self.scroll_bar_canvas_item)
        self.root_canvas_item.add_canvas_item(self.scroll_group_canvas_item)
        self.widget = self.root_canvas_item.canvas_widget
        self.selection = Selection.IndexedSelection()
        def selection_changed():
            self.selected_indexes = list(self.selection.indexes)
            if self.on_selection_changed:
                self.on_selection_changed([self.__display_items[index] for index in list(self.selection.indexes)])
            self.icon_view_canvas_item.update()
        self.__selection_changed_listener = self.selection.changed_event.listen(selection_changed)
        self.selected_indexes = list()
        self.on_selection_changed = None
        self.on_context_menu_event = None
        self.on_focus_changed = None

        # changed data items keep track of items whose content has changed
        # the content changed messages may come from a thread so have to be
        # moved to the main thread via this object.
        self.__changed_display_items = False
        self.__changed_display_items_mutex = threading.RLock()

    def close(self):
        self.__selection_changed_listener.close()
        self.__selection_changed_listener = None
        for display_item_needs_update_listener in self.__display_item_needs_update_listeners:
            display_item_needs_update_listener.close()
        self.__display_item_needs_update_listeners = None
        self.__display_items = None
        self.on_selection_changed = None
        self.on_context_menu_event = None
        self.on_focus_changed = None
        self.root_canvas_item.close()

    def periodic(self):
        # handle the 'changed' stuff
        with self.__changed_display_items_mutex:
            changed_display_items = self.__changed_display_items
            self.__changed_display_items = False
        if changed_display_items:
            self.icon_view_canvas_item.update()

    def set_selected_index(self, index):
        self.selection.set(index)

    # this message comes from the canvas item when delete key is pressed
    def _delete_pressed(self):
        if self.on_delete_display_items:
            self.on_delete_display_items([self.__display_items[index] for index in self.selection.indexes])

    @property
    def display_item_count(self):
        return len(self.__display_items)

    def get_display_item_thumbnail(self, index):
        return self.__display_items[index].thumbnail

    def context_menu_event(self, index, x, y, gx, gy):
        if self.on_context_menu_event:
            display_item = self.__display_items[index]
            self.on_context_menu_event(display_item, x, y, gx, gy)

    def drag_started(self, index, x, y, modifiers):
        mime_data, thumbnail_data = self.__display_items[index].drag_started(x, y, modifiers)
        if mime_data and thumbnail_data is not None:
            self.root_canvas_item.canvas_widget.drag(mime_data, thumbnail_data)

    def __display_item_needs_update(self):
        with self.__changed_display_items_mutex:
            self.__changed_display_items = True

    # call this method to initialize the display items
    # not thread safe
    def set_display_items(self, display_items):
        self.__display_items = copy.copy(display_items)
        self.__display_item_needs_update_listeners = [display_item.needs_update_event.listen(self.__display_item_needs_update) for display_item in self.__display_items]

    # call this method to insert a display item
    # not thread safe
    def display_item_inserted(self, display_item, before_index):
        self.__display_items.insert(before_index, display_item)
        self.__display_item_needs_update_listeners.insert(before_index, display_item.needs_update_event.listen(self.__display_item_needs_update))
        # update the selection object. this won't change the selection; only adjust the existing indexes.
        self.selection.insert_index(before_index)
        # tell the icon view to update.
        self.icon_view_canvas_item.update()

    # call this method to remove a display item (by index)
    # not thread safe
    def display_item_removed(self, index):
        self.__display_item_needs_update_listeners[index].close()
        del self.__display_item_needs_update_listeners[index]
        del self.__display_items[index]
        self.selection.insert_index(index)
        self.icon_view_canvas_item.update()


class DataPanel(Panel.Panel):

    class LibraryModelController(object):
        """Controller for a list of top level library items."""

        def __init__(self, ui, item_controllers):
            """
            item_controllers is a list of objects that have a title property and a on_title_changed callback that gets
            invoked (on the ui thread) when the title changes externally.
            """
            self.ui = ui
            self.item_model_controller = self.ui.create_item_model_controller(["display"])
            self.item_model_controller.on_item_drop_mime_data = lambda mime_data, action, row, parent_row, parent_id: self.item_drop_mime_data(mime_data, action, row, parent_row, parent_id)
            self.item_model_controller.supported_drop_actions = self.item_model_controller.DRAG | self.item_model_controller.DROP
            self.item_model_controller.mime_types_for_drop = ["text/uri-list", "text/data_item_uuid"]
            self.on_receive_files = None
            self.__item_controllers = list()
            self.__item_count = 0
            # build the items
            for item_controller in item_controllers:
                self.__append_item_controller(item_controller)

        def close(self):
            self.__item_controllers = None
            self.item_model_controller.close()
            self.item_model_controller = None
            self.on_receive_files = None

        # not thread safe. must be called on ui thread.
        def __append_item_controller(self, item_controller):
            parent_item = self.item_model_controller.root
            self.item_model_controller.begin_insert(self.__item_count, self.__item_count, parent_item.row, parent_item.id)
            item = self.item_model_controller.create_item()
            parent_item.insert_child(self.__item_count, item)
            self.item_model_controller.end_insert()
            # not thread safe. must be called on ui thread.
            def title_changed(title):
                item.data["display"] = title
                self.item_model_controller.data_changed(item.row, item.parent.row, item.parent.id)
            item_controller.on_title_changed = title_changed
            title_changed(item_controller.title)
            self.__item_controllers.append(item_controller)
            self.__item_count += 1

        def item_drop_mime_data(self, mime_data, action, row, parent_row, parent_id):
            if mime_data.has_file_paths:
                if row >= 0:  # only accept drops ONTO items, not BETWEEN items
                    return self.item_model_controller.NONE
                if self.on_receive_files and self.on_receive_files(mime_data.file_paths):
                    return self.item_model_controller.COPY
            return self.item_model_controller.NONE


    # a tree model of the data groups. this class watches for changes to the data groups contained in the document controller
    # and responds by updating the item model controller associated with the data group tree view widget. it also handles
    # drag and drop and keeps the current selection synchronized with the image panel.

    class DataGroupModelController(object):

        def __init__(self, document_controller):
            self.ui = document_controller.ui
            self.item_model_controller = self.ui.create_item_model_controller(["display", "edit"])
            self.item_model_controller.on_item_set_data = self.item_set_data
            self.item_model_controller.on_item_drop_mime_data = self.item_drop_mime_data
            self.item_model_controller.on_item_mime_data = self.item_mime_data
            self.item_model_controller.on_remove_rows = self.remove_rows
            self.item_model_controller.supported_drop_actions = self.item_model_controller.DRAG | self.item_model_controller.DROP
            self.item_model_controller.mime_types_for_drop = ["text/uri-list", "text/data_item_uuid", "text/data_group_uuid"]
            self.__document_controller_weakref = weakref.ref(document_controller)
            self.document_controller.document_model.add_observer(self)
            self.__mapping = { document_controller.document_model: self.item_model_controller.root }
            self.on_receive_files = None
            # add items that already exist
            data_groups = document_controller.document_model.data_groups
            for index, data_group in enumerate(data_groups):
                self.item_inserted(document_controller.document_model, "data_groups", data_group, index)

        def close(self):
            # cheap way to unlisten to everything
            for object in self.__mapping.keys():
                if isinstance(object, DataGroup.DataGroup):
                    object.remove_listener(self)
                    object.remove_observer(self)
            self.document_controller.document_model.remove_observer(self)
            self.item_model_controller.close()
            self.item_model_controller = None
            self.on_receive_files = None

        def log(self, parent_id=-1, indent=""):
            parent_id = parent_id if parent_id >= 0 else self.item_model_controller.root.id
            for index, child in enumerate(self.item_model_controller.item_from_id(parent_id).children):
                value = child.data["display"] if "display" in child.data else "---"
                logging.debug(indent + str(index) + ": (" + str(child.id) + ") " + value)
                self.log(child.id, indent + "  ")

        def __get_document_controller(self):
            return self.__document_controller_weakref()
        document_controller = property(__get_document_controller)

        # these two methods support the 'count' display for data groups. they count up
        # the data items that are children of the container (which can be a data group
        # or a document controller) and also data items in all of their child groups.
        def __append_data_item_flat(self, container, data_items):
            if isinstance(container, DataItem.DataItem):
                data_items.append(container)
            if hasattr(container, "data_items"):
                for child_data_item in container.data_items:
                    self.__append_data_item_flat(child_data_item, data_items)
        def __get_data_item_count_flat(self, container):
            data_items = []
            self.__append_data_item_flat(container, data_items)
            return len(data_items)

        # this message is received when a data item is inserted into one of the
        # groups we're observing.
        def item_inserted(self, container, key, object, before_index):
            if key == "data_groups":
                # manage the item model
                parent_item = self.__mapping[container]
                self.item_model_controller.begin_insert(before_index, before_index, parent_item.row, parent_item.id)
                count = self.__get_data_item_count_flat(object)
                properties = {
                    "display": str(object) + (" (%i)" % count),
                    "edit": object.title,
                    "data_group": object
                }
                item = self.item_model_controller.create_item(properties)
                parent_item.insert_child(before_index, item)
                self.__mapping[object] = item
                object.add_observer(self)
                object.add_listener(self)
                self.item_model_controller.end_insert()
                # recursively insert items that already exist
                data_groups = object.data_groups
                for index, child_data_group in enumerate(data_groups):
                    self.item_inserted(object, "data_groups", child_data_group, index)

        # this message is received when a data item is removed from one of the
        # groups we're observing.
        def item_removed(self, container, key, object, index):
            if key == "data_groups":
                assert isinstance(object, DataGroup.DataGroup)
                # get parent and item
                parent_item = self.__mapping[container]
                # manage the item model
                self.item_model_controller.begin_remove(index, index, parent_item.row, parent_item.id)
                object.remove_listener(self)
                object.remove_observer(self)
                parent_item.remove_child(parent_item.children[index])
                self.__mapping.pop(object)
                self.item_model_controller.end_remove()

        def __update_item_count(self, data_group):
            assert isinstance(data_group, DataGroup.DataGroup)
            count = self.__get_data_item_count_flat(data_group)
            item = self.__mapping[data_group]
            item.data["display"] = str(data_group) + (" (%i)" % count)
            item.data["edit"] = data_group.title
            self.item_model_controller.data_changed(item.row, item.parent.row, item.parent.id)

        def property_changed(self, data_group, key, value):
            if key == "title":
                self.__update_item_count(data_group)

        # this method if called when one of our listened to data groups changes
        def data_item_inserted(self, container, data_item, before_index, moving):
            self.__update_item_count(container)

        # this method if called when one of our listened to data groups changes
        def data_item_removed(self, container, data_item, index, moving):
            self.__update_item_count(container)

        def item_set_data(self, data, index, parent_row, parent_id):
            data_group = self.item_model_controller.item_value("data_group", index, parent_id)
            if data_group:
                data_group.title = data
                return True
            return False

        def get_data_group(self, index, parent_row, parent_id):
            return self.item_model_controller.item_value("data_group", index, parent_id)

        def get_data_group_of_parent(self, parent_row, parent_id):
            parent_item = self.item_model_controller.item_from_id(parent_id)
            return parent_item.data["data_group"] if "data_group" in parent_item.data else None

        def get_data_group_index(self, data_group):
            item = None
            data_group_item = self.__mapping.get(data_group)
            parent_item = data_group_item.parent if data_group_item else self.item_model_controller.root
            assert parent_item is not None
            for child in parent_item.children:
                child_data_group = child.data.get("data_group")
                if child_data_group == data_group:
                    item = child
                    break
            if item:
                return item.row, item.parent.row, item.parent.id
            else:
                return -1, -1, 0

        def item_drop_mime_data(self, mime_data, action, row, parent_row, parent_id):
            data_group = self.get_data_group_of_parent(parent_row, parent_id)
            container = self.document_controller.document_model if parent_row < 0 and parent_id == 0 else data_group
            if data_group and mime_data.has_file_paths:
                if row >= 0:  # only accept drops ONTO items, not BETWEEN items
                    return self.item_model_controller.NONE
                if self.on_receive_files and self.on_receive_files(mime_data.file_paths, data_group, len(data_group.data_items)):
                    return self.item_model_controller.COPY
            if data_group and mime_data.has_format("text/data_item_uuid"):
                if row >= 0:  # only accept drops ONTO items, not BETWEEN items
                    return self.item_model_controller.NONE
                # if the data item exists in this document, then it is copied to the
                # target group. if it doesn't exist in this document, then it is coming
                # from another document and can't be handled here.
                data_item_uuid = uuid.UUID(mime_data.data_as_string("text/data_item_uuid"))
                data_item = self.document_controller.document_model.get_data_item_by_key(data_item_uuid)
                if data_item:
                    data_group.append_data_item(data_item)
                    return action
                return self.item_model_controller.NONE
            if mime_data.has_format("text/data_group_uuid"):
                data_group_uuid = uuid.UUID(mime_data.data_as_string("text/data_group_uuid"))
                data_group = self.document_controller.document_model.get_data_group_by_uuid(data_group_uuid)
                if data_group:
                    data_group_copy = copy.deepcopy(data_group)
                    if row >= 0:
                        container.insert_data_group(row, data_group_copy)
                    else:
                        container.append_data_group(data_group_copy)
                    return action
            return self.item_model_controller.NONE

        def item_mime_data(self, index, parent_row, parent_id):
            data_group = self.get_data_group(index, parent_row, parent_id)
            if data_group:
                mime_data = self.ui.create_mime_data()
                mime_data.set_data_as_string("text/data_group_uuid", str(data_group.uuid))
                return mime_data
            return None

        def remove_rows(self, row, count, parent_row, parent_id):
            data_group = self.get_data_group_of_parent(parent_row, parent_id)
            container = self.document_controller.document_model if parent_row < 0 and parent_id == 0 else data_group
            for i in range(count):
                del container.data_groups[row]
            return True

    def __init__(self, document_controller, panel_id, properties):
        super(DataPanel, self).__init__(document_controller, panel_id, _("Data Items"))

        self.__focused = False
        self.__selection = DataPanelSelection()
        self.__selected_data_items = list()
        self.__closing = False
        self.__block1 = False

        class LibraryItemController(object):

            def __init__(self, base_title, binding):
                self.__base_title = base_title
                self.__count = 0
                self.__binding = binding
                self.on_title_changed = None

                # not thread safe. must be called on ui thread.
                def data_item_inserted(data_item, before_index):
                    self.__count += 1
                    if self.on_title_changed:
                        document_controller.queue_task(functools.partial(self.on_title_changed, self.title))

                # not thread safe. must be called on ui thread.
                def data_item_removed(data_item, index):
                    self.__count -= 1
                    if self.on_title_changed:
                        document_controller.queue_task(functools.partial(self.on_title_changed, self.title))

                self.__binding.inserters[id(self)] = data_item_inserted
                self.__binding.removers[id(self)] = data_item_removed
                self.__count = len(self.__binding.data_items)

            @property
            def title(self):
                return self.__base_title + (" (%i)" % self.__count)

            def close(self):
                del self.__binding.inserters[id(self)]
                del self.__binding.removers[id(self)]

        all_items_binding = document_controller.create_data_item_binding(None, None)
        all_items_controller = LibraryItemController(_("All"), all_items_binding)
        latest_items_binding = document_controller.create_data_item_binding(None, "latest-session")
        latest_items_controller = LibraryItemController(_("Latest Session"), latest_items_binding)
        self.__item_controllers = [all_items_controller, latest_items_controller]

        self.library_model_controller = DataPanel.LibraryModelController(document_controller.ui, self.__item_controllers)
        self.library_model_controller.on_receive_files = self.library_model_receive_files

        self.data_group_model_controller = DataPanel.DataGroupModelController(document_controller)
        self.data_group_model_controller.on_receive_files = lambda file_paths, data_group, index: self.data_group_model_receive_files(file_paths, data_group, index)

        ui = document_controller.ui

        def library_widget_selection_changed(selected_indexes):
            if not self.__block1:
                index = selected_indexes[0][0] if len(selected_indexes) > 0 else -1
                if index == 1:
                    self.update_data_panel_selection(DataPanelSelection(filter_id="latest-session"))
                else:
                    self.update_data_panel_selection(DataPanelSelection())

        self.library_widget = ui.create_tree_widget(properties={"height": 24 + 18 * 2})
        self.library_widget.item_model_controller = self.library_model_controller.item_model_controller
        self.library_widget.on_selection_changed = library_widget_selection_changed
        self.library_widget.on_focus_changed = self.__set_focused

        def data_group_widget_selection_changed(selected_indexes):
            if not self.__block1:
                if len(selected_indexes) > 0:
                    index, parent_row, parent_id = selected_indexes[0]
                    data_group = self.data_group_model_controller.get_data_group(index, parent_row, parent_id)
                else:
                    data_group = None
                self.update_data_panel_selection(DataPanelSelection(data_group, None))

        def data_group_widget_key_pressed(index, parent_row, parent_id, key):
            if key.is_delete:
                data_group = self.data_group_model_controller.get_data_group(index, parent_row, parent_id)
                if data_group:
                    container = self.data_group_model_controller.get_data_group_of_parent(parent_row, parent_id)
                    container = container if container else self.document_controller.document_model
                    self.document_controller.remove_data_group_from_container(data_group, container)
            return False

        self.data_group_widget = ui.create_tree_widget()
        self.data_group_widget.item_model_controller = self.data_group_model_controller.item_model_controller
        self.data_group_widget.on_selection_changed = data_group_widget_selection_changed
        self.data_group_widget.on_item_key_pressed = data_group_widget_key_pressed
        self.data_group_widget.on_focus_changed = self.__set_focused

        library_label_row = ui.create_row_widget()
        library_label = ui.create_label_widget(_("Library"), properties={"stylesheet": "font-weight: bold"})
        library_label_row.add_spacing(8)
        library_label_row.add(library_label)
        library_label_row.add_stretch()

        collections_label_row = ui.create_row_widget()
        collections_label = ui.create_label_widget(_("Collections"), properties={"stylesheet": "font-weight: bold"})
        collections_label_row.add_spacing(8)
        collections_label_row.add(collections_label)
        collections_label_row.add_stretch()

        library_section_widget = ui.create_column_widget()
        library_section_widget.add_spacing(4)
        library_section_widget.add(library_label_row)
        library_section_widget.add(self.library_widget)

        collections_section_widget = ui.create_column_widget()
        collections_section_widget.add_spacing(4)
        collections_section_widget.add(collections_label_row)
        collections_section_widget.add(self.data_group_widget)

        master_widget = ui.create_column_widget()
        master_widget.add(library_section_widget)
        master_widget.add(collections_section_widget)
        master_widget.add_stretch()

        def delete_display_items(display_items):
            for display_item in display_items:
                data_item = display_item.data_item
                container = self.document_controller.data_items_binding.container
                container = DataGroup.get_data_item_container(container, data_item)
                if container and data_item in container.data_items:
                    container.remove_data_item(data_item)

        # this message is received when the current item changes in the widget
        def selection_changed(display_items):
            if not self.__block1:
                data_item = display_items[0].data_item if len(display_items) == 1 else None
                self.__selection = DataPanelSelection(self.__selection.data_group, data_item, self.__selection.filter_id)
                if self.focused:
                    self.document_controller.notify_selected_display_specifier_changed(DataItem.DisplaySpecifier.from_data_item(data_item))
                    self.__selected_data_items = [display_item.data_item for display_item in display_items]
                    self.document_controller.set_selected_data_items(self.__selected_data_items)
                self.document_controller.set_browser_data_item(data_item)
                self.save_state()

        def display_item_double_clicked(display_item):
            data_item = display_item.data_item
            self.document_controller.new_window("data", DataPanelSelection(self.__selection.data_group, data_item, self.__selection.filter_id))

        def data_grid_context_menu_event(display_item, x, y, gx, gy):
            data_item = display_item.data_item
            container = self.document_controller.data_items_binding.container
            container = DataGroup.get_data_item_container(container, data_item)
            self.document_controller.show_context_menu_for_data_item(container, data_item, gx, gy)

        self.data_list_controller = DataListController(document_controller.ui)
        self.data_list_controller.on_selection_changed = selection_changed
        self.data_list_controller.on_context_menu_event = data_grid_context_menu_event
        self.data_list_controller.on_display_item_double_clicked = display_item_double_clicked
        self.data_list_controller.on_focus_changed = self.__set_focused
        self.data_list_controller.on_delete_display_items = delete_display_items

        self.data_grid_controller = DataGridController(document_controller.ui)
        self.data_grid_controller.on_selection_changed = selection_changed
        self.data_grid_controller.on_context_menu_event = data_grid_context_menu_event
        self.data_grid_controller.on_focus_changed = self.__set_focused
        self.data_grid_controller.on_delete_display_items = delete_display_items

        def data_item_inserted(data_item, before_index):
            display_item = DisplayItem(data_item, self.document_controller.document_model.dispatch_task, self.ui)
            self.__display_items.insert(before_index, display_item)
            self.data_list_controller.display_item_inserted(display_item, before_index)
            self.data_grid_controller.display_item_inserted(display_item, before_index)

        def data_item_removed(index):
            self.data_list_controller.display_item_removed(index)
            self.data_grid_controller.display_item_removed(index)
            self.__display_items[index].close()
            del self.__display_items[index]

        self.__binding = document_controller.filtered_data_items_binding
        self.__binding.inserters[id(self)] = lambda data_item, before_index: self.document_controller.queue_task(functools.partial(data_item_inserted, data_item, before_index))
        self.__binding.removers[id(self)] = lambda data_item, index: self.document_controller.queue_task(functools.partial(data_item_removed, index))

        dispatch_task_fn = self.document_controller.document_model.dispatch_task
        self.__display_items = [DisplayItem(data_item, dispatch_task_fn, self.ui) for data_item in self.__binding.data_items]
        self.data_list_controller.set_display_items(self.__display_items)
        self.data_grid_controller.set_display_items(self.__display_items)

        self.buttons_canvas_item = CanvasItem.RootCanvasItem(ui, properties={"height": 20, "width": 44})
        self.buttons_canvas_item.layout = CanvasItem.CanvasItemRowLayout(spacing=4)

        list_icon_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(":/Graphics/list_icon_20.png"))
        grid_icon_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(":/Graphics/grid_icon_20.png"))

        list_icon_button.sizing.set_fixed_size(Geometry.IntSize(20, 20))
        grid_icon_button.sizing.set_fixed_size(Geometry.IntSize(20, 20))

        list_icon_button.background_color = "#CCC"

        self.buttons_canvas_item.add_canvas_item(list_icon_button)
        self.buttons_canvas_item.add_canvas_item(grid_icon_button)

        search_widget = ui.create_row_widget()
        search_widget.add_spacing(8)
        search_widget.add(ui.create_label_widget(_("Filter")))
        search_widget.add_spacing(8)
        search_line_edit = ui.create_line_edit_widget()
        search_line_edit.placeholder_text = _("No Filter")
        # search_line_edit.clear_button_enabled = True  # Qt 5.3 doesn't signal text edited or editing finished when clearing. useless so disabled.
        search_line_edit.on_text_edited = self.document_controller.filter_controller.text_filter_changed
        search_line_edit.on_editing_finished = self.document_controller.filter_controller.text_filter_changed
        search_widget.add(search_line_edit)
        search_widget.add_spacing(6)
        search_widget.add(self.buttons_canvas_item.canvas_widget)
        search_widget.add_spacing(8)

        self.data_view_widget = ui.create_stack_widget()
        self.data_view_widget.add(self.data_list_controller.widget)
        self.data_view_widget.add(self.data_grid_controller.widget)
        self.data_view_widget.current_index = 0

        def tab_changed(index):
            self.data_view_widget.current_index = index
            if index == 0:  # switching to data list?
                selected_display_items = [self.__display_items[index] for index in self.data_list_controller.selected_indexes]
                selection_changed(selected_display_items)
                list_icon_button.background_color = "#CCC"
                grid_icon_button.background_color = None
            elif index == 1:  # switching to data grid?
                selected_display_items = [self.__display_items[index] for index in self.data_grid_controller.selected_indexes]
                selection_changed(selected_display_items)
                list_icon_button.background_color = None
                grid_icon_button.background_color = "#CCC"

        list_icon_button.on_button_clicked = lambda: tab_changed(0)
        grid_icon_button.on_button_clicked = lambda: tab_changed(1)

        slave_widget = ui.create_column_widget()
        slave_widget.add(self.data_view_widget)
        slave_widget.add_spacing(6)
        slave_widget.add(search_widget)
        slave_widget.add_spacing(6)

        self.splitter = ui.create_splitter_widget("vertical", properties)
        self.splitter.orientation = "vertical"
        self.splitter.add(master_widget)
        self.splitter.add(slave_widget)
        self.splitter.restore_state("window/v1/data_panel_splitter")

        self.widget = self.splitter

        # connect self as listener. this will result in calls to update_data_panel_selection
        self.document_controller.add_listener(self)
        self.document_controller.weak_data_panel = weakref.ref(self)

        # restore selection
        self.restore_state()

    def close(self):
        self.__closing = True
        del self.__binding.inserters[id(self)]
        del self.__binding.removers[id(self)]
        # binding should not be closed since it isn't created in this object
        self.splitter.save_state("window/v1/data_panel_splitter")
        self.update_data_panel_selection(DataPanelSelection())
        # close the models
        self.data_group_model_controller.close()
        self.data_group_model_controller = None
        for item_controller in self.__item_controllers:
            item_controller.close()
        self.library_model_controller.close()
        self.library_model_controller = None
        self.data_list_controller.close()
        self.data_list_controller = None
        self.data_grid_controller.close()
        self.data_grid_controller = None
        # disconnect self as listener
        self.document_controller.weak_data_panel = None
        self.document_controller.remove_listener(self)
        # display items
        for display_item in self.__display_items:
            display_item.close()
        self.__display_items = None
        # finish closing
        super(DataPanel, self).close()

    def periodic(self):
        super(DataPanel, self).periodic()
        self.data_list_controller.periodic()
        self.data_grid_controller.periodic()

    def restore_state(self):
        data_group_uuid_str = self.ui.get_persistent_string("selected_data_group")
        data_item_uuid_str = self.ui.get_persistent_string("selected_data_item")
        filter_id = self.ui.get_persistent_string("selected_filter_id")
        data_group_uuid = uuid.UUID(data_group_uuid_str) if data_group_uuid_str else None
        data_item_uuid = uuid.UUID(data_item_uuid_str) if data_item_uuid_str else None
        data_group = self.document_controller.document_model.get_data_group_by_uuid(data_group_uuid)
        data_item = self.document_controller.document_model.get_data_item_by_uuid(data_item_uuid)
        self.update_data_panel_selection(DataPanelSelection(data_group, data_item, filter_id))

    def save_state(self):
        if not self.__closing:
            data_panel_selection = self.__selection
            if data_panel_selection.data_group:
                self.ui.set_persistent_string("selected_data_group", str(data_panel_selection.data_group.uuid))
            else:
                self.ui.remove_persistent_key("selected_data_group")
            if data_panel_selection.data_item:
                self.ui.set_persistent_string("selected_data_item", str(data_panel_selection.data_item.uuid))
            else:
                self.ui.remove_persistent_key("selected_data_item")
            if data_panel_selection.filter_id:
                self.ui.set_persistent_string("selected_filter_id", str(data_panel_selection.filter_id))
            else:
                self.ui.remove_persistent_key("selected_filter_id")

    # the focused property gets set from on_focus_changed on the data item widget. when gaining focus,
    # make sure the document controller knows what is selected so it can update the inspector.
    def __get_focused(self):
        return self.__focused
    def __set_focused(self, focused):
        self.__focused = focused
        if not self.__closing:
            if focused:
                self.document_controller.notify_selected_display_specifier_changed(DataItem.DisplaySpecifier.from_data_item(self.__selection.data_item))
                self.document_controller.set_selected_data_items(self.__selected_data_items)
            else:
                self.document_controller.notify_selected_display_specifier_changed(DataItem.DisplaySpecifier())
                self.document_controller.set_selected_data_items([])
            self.document_controller.set_browser_data_item(self.__selection.data_item)
    focused = property(__get_focused, __set_focused)

    @property
    def data_item(self):
        return self.__selection.data_item

    # if the data_panel_selection gets changed, the data group tree and data item list need
    # to be updated to reflect the new selection. care needs to be taken to not introduce
    # update cycles.
    # three areas where this method is used are when starting acquisition, when quitting and
    # restarting, and after adding an operation to a data item.
    # not thread safe.
    def update_data_panel_selection(self, data_panel_selection):
        # block. why? so we don't get infinite loops.
        saved_block1 = self.__block1
        self.__block1 = True
        data_group = data_panel_selection.data_group
        data_item = data_panel_selection.data_item
        filter_id = data_panel_selection.filter_id
        # first select the right row in the library or data group widget
        if data_group:
            index, parent_row, parent_id = self.data_group_model_controller.get_data_group_index(data_group)
            self.library_widget.clear_current_row()
            self.data_group_widget.set_current_row(index, parent_row, parent_id)
        else:
            self.data_group_widget.clear_current_row()
            if filter_id == "latest-session":
                self.library_widget.set_current_row(1, -1, 0)  # select the 'latest' group
            else:
                self.library_widget.set_current_row(0, -1, 0)  # select the 'all' group
        # update the data group that the data item model is tracking. the changes will be queued to the ui thread even
        # though this is already on the ui thread.
        self.document_controller.set_data_group_or_filter(data_group, filter_id)
        # when the data group or filter is changed above, it will generate a new list of items to be displayed in the
        # data browser and that new list will be queued in case it is called on a background thread (it isn't in this
        # case). call periodic to actually sync the changes to the data browser ui.
        self.document_controller.periodic()
        # update the data item selection by determining the new index of the item, if any.
        # TODO: updating the current selection is not done correctly here

        data_item_index = -1
        for index in range(len(self.__display_items)):
            if data_item == self.__display_items[index].data_item:
                data_item_index = index
                break

        if self.data_view_widget.current_index == 0:
            self.data_list_controller.set_selected_index(data_item_index)
        else:
            self.data_grid_controller.set_selected_index(data_item_index)
        self.__selection = data_panel_selection
        # save the users selection
        self.save_state()
        # unblock
        self.__block1 = saved_block1

    def library_model_receive_files(self, file_paths, threaded=True):
        def receive_files_complete(received_data_items):
            def select_library_all():
                self.update_data_panel_selection(DataPanelSelection(data_item=received_data_items[0]))
            if len(received_data_items) > 0:
                self.queue_task(select_library_all)
        index = len(self.document_controller.document_model.data_items)
        self.document_controller.receive_files(file_paths, None, index, threaded, receive_files_complete)
        return True

    # receive files dropped into the data group.
    # this message comes from the data group model, which is why it is named the way it is.
    def data_group_model_receive_files(self, file_paths, data_group, index, threaded=True):
        def receive_files_complete(received_data_items):
            def select_data_group_and_data_item():
                self.update_data_panel_selection(DataPanelSelection(data_group=data_group, data_item=received_data_items[0]))
            if len(received_data_items) > 0:
                if threaded:
                    self.queue_task(select_data_group_and_data_item)
                else:
                    select_data_group_and_data_item()
        self.document_controller.receive_files(file_paths, data_group, index, threaded, receive_files_complete)
        return True
