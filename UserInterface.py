"""
Provides a user interface object that can render to an Qt host.
"""

# futures
from __future__ import absolute_import
from __future__ import division

# standard libraries
import binascii
import collections
import copy
import logging
import numbers
import os
import threading
import weakref

# conditional imports
import sys
if sys.version < '3':
    import cPickle as pickle
else:
    import pickle

# third party libraries
# none

# local libraries
from nion.ui import DrawingContext
from nion.ui import Geometry
from nion.ui import Unicode


class QtKeyboardModifiers(object):
    def __init__(self, raw_modifiers):
        self.raw_modifiers = raw_modifiers

    def __str__(self):
        return "shift:{} control:{} alt:{} option:{} meta:{}".format(self.shift, self.control, self.alt, self.option,
                                                                     self.meta)

    # shift
    @property
    def shift(self):
        return (self.raw_modifiers & 0x02000000) == 0x02000000

    @property
    def only_shift(self):
        return self.raw_modifiers == 0x02000000

    # control (command key on mac)
    @property
    def control(self):
        return (self.raw_modifiers & 0x04000000) == 0x04000000

    @property
    def only_control(self):
        return self.raw_modifiers == 0x04000000

    # alt (option key on mac)
    @property
    def alt(self):
        return (self.raw_modifiers & 0x08000000) == 0x08000000

    @property
    def only_alt(self):
        return self.raw_modifiers == 0x08000000

    # option (alt key on windows)
    @property
    def option(self):
        return (self.raw_modifiers & 0x08000000) == 0x08000000

    @property
    def only_option(self):
        return self.raw_modifiers == 0x08000000

    # meta (control key on mac)
    @property
    def meta(self):
        return (self.raw_modifiers & 0x10000000) == 0x10000000

    @property
    def only_meta(self):
        return self.raw_modifiers == 0x10000000

    # keypad
    @property
    def keypad(self):
        return (self.raw_modifiers & 0x20000000) == 0x20000000

    @property
    def only_keypad(self):
        return self.raw_modifiers == 0x20000000


class QtKey(object):
    def __init__(self, text, key, raw_modifiers):
        self.text = text
        self.key = key
        self.modifiers = QtKeyboardModifiers(raw_modifiers)

    @property
    def is_delete(self):
        return len(self.text) == 1 and (ord(self.text[0]) == 127 or ord(self.text[0]) == 8)

    @property
    def is_enter_or_return(self):
        return len(self.text) == 1 and (ord(self.text[0]) == 3 or ord(self.text[0]) == 13)

    @property
    def is_arrow(self):
        return self.key in (0x1000012, 0x1000013, 0x1000014, 0x1000015)

    @property
    def is_left_arrow(self):
        return self.key == 0x1000012

    @property
    def is_up_arrow(self):
        return self.key == 0x1000013

    @property
    def is_right_arrow(self):
        return self.key == 0x1000014

    @property
    def is_down_arrow(self):
        return self.key == 0x1000015


class QtMimeData(object):
    def __init__(self, proxy, mime_data=None):
        self.proxy = proxy
        self.raw_mime_data = mime_data if mime_data else self.proxy.MimeData_create()
    def __get_formats(self):
        return self.proxy.MimeData_formats(self.raw_mime_data)
    formats = property(__get_formats)
    def has_format(self, format):
        return format in self.formats
    def __get_has_urls(self):
        return "text/uri-list" in self.formats
    has_urls = property(__get_has_urls)
    has_file_paths = property(__get_has_urls)
    def __get_urls(self):
        raw_urls = self.data_as_string("text/uri-list")
        return raw_urls.splitlines() if raw_urls and len(raw_urls) > 0 else []
    urls = property(__get_urls)
    def __get_file_paths(self):
        urls = self.urls
        file_paths = []
        for url in urls:
            file_path = self.proxy.Core_URLToPath(url)
            if file_path and len(file_path) > 0 and os.path.exists(file_path) and os.path.isfile(file_path):
                file_paths.append(file_path)
        return file_paths
    file_paths = property(__get_file_paths)
    def data_as_string(self, format):
        return self.proxy.MimeData_dataAsString(self.raw_mime_data, format)
    def set_data_as_string(self, format, text):
        self.proxy.MimeData_setDataAsString(self.raw_mime_data, format, text)


# pobj
class QtItemModelController(object):

    NONE = 0
    COPY = 1
    MOVE = 2
    LINK = 4

    DRAG = 1
    DROP = 2

    class Item(object):
        def __init__(self, data=None):
            self.id = None
            self.data = data if data else {}
            self.weak_parent = None
            self.children = []
        def __str__(self):
            return "Item %i (row %i parent %s)" % (self.id, self.row, self.parent)
        def remove_all_children(self):
            self.children = []
        def append_child(self, item):
            item.parent = self
            self.children.append(item)
        def insert_child(self, before_index, item):
            item.parent = self
            self.children.insert(before_index, item)
        def remove_child(self, item):
            item.parent = None
            self.children.remove(item)
        def child(self, index):
            return self.children[index]
        def __get_row(self):
            parent = self.weak_parent() if self.weak_parent else None
            if parent:
                return parent.children.index(self)
            return -1
        row = property(__get_row)
        def __get_parent(self):
            return self.weak_parent() if self.weak_parent else None
        def __set_parent(self, parent):
            self.weak_parent = weakref.ref(parent) if parent else None
        parent = property(__get_parent, __set_parent)

    def __init__(self, proxy, keys):
        self.proxy = proxy
        self.py_item_model = self.proxy.ItemModel_create(["index"] + keys)
        self.proxy.ItemModel_connect(self.py_item_model, self)
        self.__next_id = 0
        self.root = self.create_item()
        self.on_item_set_data = None
        self.on_item_drop_mime_data = None
        self.on_item_mime_data = None
        self.on_remove_rows = None
        self.supported_drop_actions = 0
        self.mime_types_for_drop = []

    def close(self):
        self.proxy.ItemModel_destroy(self.py_item_model)
        self.proxy = None
        self.py_item_model = None
        self.root = None
        self.on_item_set_data = None
        self.on_item_drop_mime_data = None
        self.on_item_mime_data = None
        self.on_remove_rows = None

    # these methods must be invoked from the client

    def create_item(self, data=None):
        item = QtItemModelController.Item(data)
        item.id = self.__next_id
        self.__next_id = self.__next_id + 1
        return item

    def item_from_id(self, item_id, parent=None):
        item = []  # nonlocal in Python 3.1+
        def fn(parent, index, child):
            if child.id == item_id:
                item.append(child)
                return True
        self.traverse(fn)
        return item[0] if item else None

    def __item_id(self, index, parent_id):
        parent = self.item_from_id(parent_id)
        assert parent is not None
        if index >= 0 and index < len(parent.children):
            return parent.children[index].id
        return 0  # invalid id

    def item_value_for_item_id(self, role, index, item_id):
        child = self.item_from_id(item_id)
        if role == "index":
            return index
        if role in child.data:
            return child.data[role]
        return None

    def item_value(self, role, index, parent_id):
        return self.item_value_for_item_id(role, index, self.__item_id(index, parent_id))

    # these methods are invoked from Qt

    def itemCount(self, parent_id):
        parent = self.item_from_id(parent_id)
        assert parent is not None
        return len(parent.children)

    # itemId returns the id of the item within the parent
    def itemId(self, index, parent_id):
        return self.__item_id(index, parent_id)

    def itemParent(self, index, item_id):
        if item_id == 0:
            return [-1, 0]
        child = self.item_from_id(item_id)
        parent = child.parent
        if parent == self.root:
            return [-1, 0]
        return [parent.row, parent.id]

    def itemValue(self, role, index, item_id):
        return self.item_value_for_item_id(role, index, item_id)

    def itemSetData(self, index, parent_row, parent_id, data):
        if self.on_item_set_data:
            return self.on_item_set_data(data, index, parent_row, parent_id)
        return False

    def itemDropMimeData(self, raw_mime_data, action, row, parent_row, parent_id):
        if self.on_item_drop_mime_data:
            return self.on_item_drop_mime_data(QtMimeData(self.proxy, raw_mime_data), action, row, parent_row, parent_id)
        return False

    def itemMimeData(self, row, parent_row, parent_id):
        if self.on_item_mime_data:
            mime_data = self.on_item_mime_data(row, parent_row, parent_id)
            return mime_data.raw_mime_data if mime_data else None
        return None

    def removeRows(self, row, count, parent_row, parent_id):
        if self.on_remove_rows:
            return self.on_remove_rows(row, count, parent_row, parent_id)
        return False

    def supportedDropActions(self):
        return self.supported_drop_actions

    def mimeTypesForDrop(self):
        return self.mime_types_for_drop


#abc (None, 0)
#    def (abc, 0)
#    ghi (abc, 1)
#        jkl (ghi, 0)
#        mno (ghi, 1)
#    pqr (abc, 2)
#        stu (pqr, 0)
#    vwx (abc, 3)

    def traverse_depth_first(self, fn, parent):
        real_parent = parent if parent else self.root
        for index, child in enumerate(real_parent.children):
            if self.traverse_depth_first(fn, child):
                return True
            if fn(parent, index, child):
                return True
        return False

    def traverse(self, fn):
        if not fn(None, 0, self.root):
            self.traverse_depth_first(fn, self.root)

    def begin_insert(self, first_row, last_row, parent_row, parent_id):
        self.proxy.ItemModel_beginInsertRows(self.py_item_model, first_row, last_row, parent_row, parent_id)

    def end_insert(self):
        self.proxy.ItemModel_endInsertRow(self.py_item_model)

    def begin_remove(self, first_row, last_row, parent_row, parent_id):
        self.proxy.ItemModel_beginRemoveRows(self.py_item_model, first_row, last_row, parent_row, parent_id)

    def end_remove(self):
        self.proxy.ItemModel_endRemoveRow(self.py_item_model)

    def data_changed(self, row, parent_row, parent_id):
        self.proxy.ItemModel_dataChanged(self.py_item_model, row, parent_row, parent_id)


# pobj
# supported drop actions are what is allowed for a drag originated with this item and dropped into another item.
class QtListModelController(object):

    NONE = 0
    COPY = 1
    MOVE = 2
    LINK = 4

    DRAG = 1
    DROP = 2

    def __init__(self, proxy, keys):
        self.proxy = proxy
        self.py_list_model = self.proxy.ListModel_create(["index"] + keys)
        self.proxy.ListModel_connect(self.py_list_model, self)
        self.model = []
        self.on_item_drop_mime_data = None
        self.on_item_mime_data = None
        self.on_remove_rows = None
        self.supported_drop_actions = 0
        self.mime_types_for_drop = []
    def close(self):
        self.proxy.ListModel_destroy(self.py_list_model)
        self.proxy = None
        self.py_list_model = None
        self.model = None
        self.on_item_drop_mime_data = None
        self.on_item_mime_data = None
        self.on_remove_rows = None
    # these methods are invoked from Qt
    def itemCount(self):
        return len(self.model)
    def itemValue(self, role, index):
        if role == "index":
            return index
        properties = self.model[index]
        if role in properties:
            value = properties[role]
            return value
        else:
            #print "Unknown key %s" % role
            return None
    def itemDropMimeData(self, raw_mime_data, action, row, parent_row):
        if self.on_item_drop_mime_data:
            return self.on_item_drop_mime_data(QtMimeData(self.proxy, raw_mime_data), action, row, parent_row)
        return False
    def itemMimeData(self, row):
        if self.on_item_mime_data:
            mime_data = self.on_item_mime_data(row)
            return mime_data.raw_mime_data if mime_data else None
        return None
    def removeRows(self, row, count):
        if self.on_remove_rows:
            return self.on_remove_rows(row, count)
        return False
    def supportedDropActions(self):
        return self.supported_drop_actions
    def mimeTypesForDrop(self):
        return self.mime_types_for_drop
    # these methods must be invoked from the client when the model changes
    def begin_insert(self, first_row, last_row):
        self.proxy.ListModel_beginInsertRows(self.py_list_model, first_row, last_row)
    def end_insert(self):
        self.proxy.ListModel_endInsertRow(self.py_list_model)
    def begin_remove(self, first_row, last_row):
        self.proxy.ListModel_beginRemoveRows(self.py_list_model, first_row, last_row)
    def end_remove(self):
        self.proxy.ListModel_endRemoveRow(self.py_list_model)
    def data_changed(self):
        self.proxy.ListModel_dataChanged(self.py_list_model)


class QtDrag(object):
    def __init__(self, proxy, widget, mime_data, thumbnail, hot_spot_x, hot_spot_y, drag_finished_fn):
        self.proxy = proxy
        self.__raw_drag = self.proxy.Drag_create(widget, mime_data.raw_mime_data)
        self.proxy.Drag_connect(self.__raw_drag, self)
        if thumbnail is not None:
            width = thumbnail.shape[1]
            height = thumbnail.shape[0]
            rgba_data = self.proxy.encode_data(thumbnail)
            hot_spot_x = hot_spot_x if hot_spot_x is not None else width // 2
            hot_spot_y = hot_spot_y if hot_spot_y is not None else height // 2
            self.proxy.Drag_setThumbnail(self.__raw_drag, width, height, rgba_data, hot_spot_x, hot_spot_y)
        self.on_drag_finished = drag_finished_fn

    def close(self):
        pass

    def execute(self):
        return self.proxy.Drag_exec(self.__raw_drag)

    def dragFinished(self, action):
        if self.on_drag_finished:
            self.on_drag_finished(action)


class QtWidget(object):
    def __init__(self, proxy, widget_type, properties):
        self.proxy = proxy
        self.properties = properties if properties else {}
        self.widget = self.proxy.Widget_loadIntrinsicWidget(widget_type) if widget_type else None
        self.__root_container = None  # the document window
        self.update_properties()
        self.__visible = True
        self.__enabled = True
        self.__tool_tip = None
        self.on_context_menu_event = None
        self.on_focus_changed = None

    # subclasses should override to clear their variables.
    # subclasses should NOT call Qt code to delete anything here... that is done by the Qt code
    def close(self):
        if self.widget:
            self.proxy.Widget_removeWidget(self.widget)
            self.widget = None
        self.on_context_menu_event = None
        self.on_focus_changed = None
        self.__root_container = None
        self.proxy = None

    @property
    def root_container(self):
        return self.__root_container

    def _set_root_container(self, root_container):
        self.__root_container = root_container

    # not thread safe
    def periodic(self):
        pass

    # thread safe
    # tasks are run periodically. if another task causes a widget to close,
    # the outstanding task may try to use a closed widget. any methods called
    # in a task need to verify that the widget is not yet closed. this can be
    # mitigated in several ways: 1) clear the task if possible; 2) do not queue
    # the task if widget is already closed; 3) check during task to make sure
    # widget was not already closed.
    def add_task(self, key, task):
        root_container = self.root_container
        if root_container:
            root_container.add_task(key + str(id(self)), task)

    # thread safe
    def clear_task(self, key):
        root_container = self.root_container
        if root_container:
            root_container.clear_task(key + str(id(self)))

    # thread safe
    def queue_task(self, task):
        root_container = self.root_container
        if root_container:
            root_container.queue_task(task)

    def update_properties(self):
        if self.widget:
            for key in self.properties.keys():
                self.proxy.Widget_setWidgetProperty(self.widget, key, self.proxy.encode_variant(self.properties[key]))

    @property
    def focused(self):
        return self.proxy.Widget_hasFocus(self.widget)

    @focused.setter
    def focused(self, focused):
        if focused != self.focused:
            if focused:
                self.proxy.Widget_setFocus(self.widget, 7)
            else:
                self.proxy.Widget_clearFocus(self.widget)

    @property
    def visible(self):
        return self.__visible

    @visible.setter
    def visible(self, visible):
        if visible != self.__visible:
            self.proxy.Widget_setVisible(self.widget, visible)
            self.__visible = visible

    @property
    def enabled(self):
        return self.__enabled

    @enabled.setter
    def enabled(self, enabled):
        if enabled != self.__enabled:
            self.proxy.Widget_setEnabled(self.widget, enabled)
            self.__enabled = enabled

    @property
    def size(self):
        raise NotImplementedError()

    @size.setter
    def size(self, size):
        self.proxy.Widget_setWidgetSize(self.widget, int(size[1]), int(size[0]))

    @property
    def tool_tip(self):
        return self.__tool_tip

    @tool_tip.setter
    def tool_tip(self, tool_tip):
        if tool_tip != self.__tool_tip:
            self.proxy.Widget_setToolTip(self.widget, Unicode.u(tool_tip) if tool_tip else Unicode.u())
            self.__tool_tip = tool_tip

    def drag(self, mime_data, thumbnail=None, hot_spot_x=None, hot_spot_y=None, drag_finished_fn=None):
        def drag_finished(action):
            if drag_finished_fn:
                drag_finished_fn(action)
        drag = QtDrag(self.proxy, self.widget, mime_data, thumbnail, hot_spot_x, hot_spot_y, drag_finished)
        drag.execute()

    def contextMenuEvent(self, x, y, gx, gy):
        if self.on_context_menu_event:
            self.on_context_menu_event(x, y, gx, gy)

    def focusIn(self):
        if self.on_focus_changed:
            self.on_focus_changed(True)

    def focusOut(self):
        if self.on_focus_changed:
            self.on_focus_changed(False)

    def map_to_global(self, p):
        gx, gy = self.proxy.Widget_mapToGlobal(self.widget, p.x, p.y)
        return Geometry.IntPoint(x=gx, y=gy)


class QtBoxWidget(QtWidget):

    def __init__(self, proxy, widget_type, properties):
        super(QtBoxWidget, self).__init__(proxy, widget_type, properties)
        self.children = []
        self.spacer_count = 0

    def close(self):
        for child in self.children:
            child.close()
        self.children = None
        super(QtBoxWidget, self).close()

    def _set_root_container(self, root_container):
        super(QtBoxWidget, self)._set_root_container(root_container)
        for child in self.children:
            child._set_root_container(root_container)

    def periodic(self):
        super(QtBoxWidget, self).periodic()
        for child in self.children:
            child.periodic()

    def count(self):
        return len(self.children)

    def index(self, child):
        assert child in self.children
        return self.children.index(child)

    def insert(self, child, before, fill=False, alignment=None):
        if isinstance(before, numbers.Integral):
            index = before
        else:
            index = self.index(before) if before else self.count() + self.spacer_count
        self.children.insert(index, child)
        child._set_root_container(self.root_container)
        assert self.widget is not None
        assert child.widget is not None
        self.proxy.Widget_insertWidget(self.widget, child.widget, index, fill, alignment)

    def add(self, child, fill=False, alignment=None):
        self.insert(child, None, fill, alignment)

    def remove(self, child):
        if isinstance(child, numbers.Integral):
            child = self.children[child]
        child._set_root_container(None)
        self.children.remove(child)
        child.close()

    def remove_all(self):
        while self.count() > 0:
            self.remove(0)

    def add_stretch(self):
        self.spacer_count += 1
        self.proxy.Widget_addStretch(self.widget)

    def add_spacing(self, spacing):
        self.spacer_count += 1
        self.proxy.Widget_addSpacing(self.widget, spacing)


class QtRowWidget(QtBoxWidget):

    def __init__(self, proxy, properties):
        super(QtRowWidget, self).__init__(proxy, "row", properties)


class QtColumnWidget(QtBoxWidget):

    def __init__(self, proxy, properties):
        super(QtColumnWidget, self).__init__(proxy, "column", properties)


class QtSplitterWidget(QtWidget):

    def __init__(self, proxy, orientation, properties):
        super(QtSplitterWidget, self).__init__(proxy, "splitter", properties)
        self.children = []
        self.orientation = orientation

    def close(self):
        for child in self.children:
            child.close()
        self.children = None
        super(QtSplitterWidget, self).close()

    def _set_root_container(self, root_container):
        super(QtSplitterWidget, self)._set_root_container(root_container)
        for child in self.children:
            child._set_root_container(root_container)

    def periodic(self):
        super(QtSplitterWidget, self).periodic()
        for child in self.children:
            child.periodic()

    def __get_orientation(self):
        return self.__orientation
    def __set_orientation(self, orientation):
        self.__orientation = orientation
        self.proxy.Splitter_setOrientation(self.widget, self.__orientation)
    orientation = property(__get_orientation, __set_orientation)

    def add(self, child):
        self.proxy.Widget_addWidget(self.widget, child.widget)
        self.children.append(child)
        child._set_root_container(self.root_container)

    def restore_state(self, tag):
        self.proxy.Splitter_restoreState(self.widget, tag)

    def save_state(self, tag):
        self.proxy.Splitter_saveState(self.widget, tag)


class QtTabWidget(QtWidget):

    def __init__(self, proxy, properties):
        properties = copy.copy(properties) if properties is not None else dict()
        properties["stylesheet"] = "background-color: '#FFF'"
        super(QtTabWidget, self).__init__(proxy, "tab", properties)
        self.children = []
        self.on_current_index_changed = None
        self.proxy.TabWidget_connect(self.widget, self)

    def close(self):
        for child in self.children:
            child.close()
        self.children = None
        self.on_current_index_changed = None
        super(QtTabWidget, self).close()

    def _set_root_container(self, root_container):
        super(QtTabWidget, self)._set_root_container(root_container)
        for child in self.children:
            child._set_root_container(root_container)

    def periodic(self):
        super(QtTabWidget, self).periodic()
        for child in self.children:
            child.periodic()

    def add(self, child, label):
        self.proxy.TabWidget_addTab(self.widget, child.widget, Unicode.u(label))
        self.children.append(child)
        child._set_root_container(self.root_container)

    def restore_state(self, tag):
        pass

    def save_state(self, tag):
        pass

    def currentTabChanged(self, index):
        if self.on_current_index_changed:
            self.on_current_index_changed(index)


class QtStackWidget(QtWidget):

    def __init__(self, proxy, properties):
        super(QtStackWidget, self).__init__(proxy, "stack", properties)
        self.children = []
        self.__current_index = -1

    def close(self):
        for child in self.children:
            child.close()
        self.children = None
        super(QtStackWidget, self).close()

    def _set_root_container(self, root_container):
        super(QtStackWidget, self)._set_root_container(root_container)
        for child in self.children:
            child._set_root_container(root_container)

    def periodic(self):
        super(QtStackWidget, self).periodic()
        for child in self.children:
            child.periodic()

    def add(self, child):
        self.proxy.StackWidget_addWidget(self.widget, child.widget)
        self.children.append(child)
        child._set_root_container(self.root_container)

    def restore_state(self, tag):
        pass

    def save_state(self, tag):
        pass

    def get_current_index(self):
        return self.__current_index
    def set_current_index(self, index):
        self.__current_index = index
        self.proxy.StackWidget_setCurrentIndex(self.widget, index)
    current_index = property(get_current_index, set_current_index)


class QtScrollAreaWidget(QtWidget):

    def __init__(self, proxy, properties):
        super(QtScrollAreaWidget, self).__init__(proxy, "scrollarea", properties)
        self.__content = None
        self.on_size_changed = None
        self.on_viewport_changed = None
        self.viewport = ((0, 0), (0, 0))
        self.width = 0
        self.height = 0
        self.proxy.ScrollArea_connect(self.widget, self)

    def close(self):
        self.__content.close()
        self.__content = None
        self.on_size_changed = None
        self.on_viewport_changed = None
        super(QtScrollAreaWidget, self).close()

    def _set_root_container(self, root_container):
        super(QtScrollAreaWidget, self)._set_root_container(root_container)
        self.__content._set_root_container(root_container)

    def periodic(self):
        super(QtScrollAreaWidget, self).periodic()
        self.__content.periodic()

    def __get_content(self):
        return self.__content
    def __set_content(self, content):
        self.proxy.ScrollArea_setWidget(self.widget, content.widget)
        self.__content = content
        content._set_root_container(self.root_container)
    content = property(__get_content, __set_content)

    def restore_state(self, tag):
        pass

    def save_state(self, tag):
        pass

    def sizeChanged(self, width, height):
        self.width = width
        self.height = height
        if self.on_size_changed:
            self.on_size_changed(self.width, self.height)

    def viewportChanged(self, left, top, width, height):
        self.viewport = ((top, left), (height, width))
        if self.on_viewport_changed:
            self.on_viewport_changed(self.viewport)

    def scroll_to(self, x, y):
        self.proxy.ScrollArea_setHorizontal(self.widget, float(x))
        self.proxy.ScrollArea_setVertical(self.widget, float(y))

    def set_scrollbar_policies(self, horizontal_policy, vertical_policy):
        self.proxy.ScrollArea_setScrollbarPolicies(self.widget, horizontal_policy, vertical_policy)

    def info(self):
        self.proxy.ScrollArea_info(self.widget)


class QtComboBoxWidget(QtWidget):

    def __init__(self, proxy, items, item_getter, properties):
        super(QtComboBoxWidget, self).__init__(proxy, "combobox", properties)
        self.item_getter = item_getter
        self.items = items if items else []
        self.proxy.ComboBox_connect(self.widget, self)
        self.on_current_text_changed = None
        self.on_current_item_changed = None
        self.__binding = None

    def close(self):
        if self.__binding:
            self.__binding.close()
            self.__binding = None
        self.clear_task("update_current_index")
        self.item_getter = None
        self.__items = None
        self.on_current_text_changed = None
        self.on_current_item_changed = None
        super(QtComboBoxWidget, self).close()

    def __get_current_text(self):
        return self.proxy.ComboBox_getCurrentText(self.widget)
    def __set_current_text(self, text):
        self.proxy.ComboBox_setCurrentText(self.widget, Unicode.u(text))
    current_text = property(__get_current_text, __set_current_text)

    def __get_current_item(self):
        current_text = self.current_text
        for item in self.items:
            if current_text == Unicode.u(self.item_getter(item) if self.item_getter else item):
                return item
        return None
    def __set_current_item(self, item):
        item_string = Unicode.u(self.item_getter(item) if self.item_getter else item)
        if self.widget:  # may be called as task, so verify it hasn't closed yet
            self.proxy.ComboBox_setCurrentText(self.widget, item_string)
    current_item = property(__get_current_item, __set_current_item)

    def __get_items(self):
        return self.__items
    def __set_items(self, items):
        self.proxy.ComboBox_removeAllItems(self.widget)
        self.__items = list()
        for item in items:
            item_string = Unicode.u(self.item_getter(item) if self.item_getter else item)
            self.proxy.ComboBox_addItem(self.widget, item_string)
            self.__items.append(item)
    items = property(__get_items, __set_items)

    # this message comes from Qt implementation
    def currentTextChanged(self, text):
        if self.on_current_text_changed:
            self.on_current_text_changed(text)
        if self.on_current_item_changed:
            self.on_current_item_changed(self.current_item)

    def bind_current_index(self, binding):
        if self.__binding:
            self.__binding.close()
            self.__binding = None
        self.current_item = self.__items[binding.get_target_value()]
        self.__binding = binding
        def update_current_index(current_index):
            item = self.__items[current_index]
            if self.widget:
                self.add_task("update_current_index", lambda: self.__set_current_item(item))
        self.__binding.target_setter = update_current_index
        self.on_current_item_changed = lambda item: self.__binding.update_source(self.__items.index(item))


class QtPushButtonWidget(QtWidget):

    def __init__(self, proxy, text, properties):
        super(QtPushButtonWidget, self).__init__(proxy, "pushbutton", properties)
        self.on_clicked = None
        self.text = text
        self.icon = None
        self.proxy.PushButton_connect(self.widget, self)

    def close(self):
        self.on_clicked = None
        super(QtPushButtonWidget, self).close()

    def __get_text(self):
        return self.__text
    def __set_text(self, text):
        self.__text = self.proxy.encode_text(text)
        self.proxy.PushButton_setText(self.widget, self.__text)
    text = property(__get_text, __set_text)

    def __get_icon(self):
        return self.__icon
    def __set_icon(self, rgba_image):
        self.__icon = rgba_image
        self.__width = rgba_image.shape[1] if rgba_image is not None else 0
        self.__height = rgba_image.shape[0] if rgba_image is not None else 0
        rgba_data = self.proxy.encode_data(rgba_image)
        self.proxy.PushButton_setIcon(self.widget, self.__width, self.__height, rgba_data)
    # bgra
    icon = property(__get_icon, __set_icon)

    def clicked(self):
        if self.on_clicked:
            self.on_clicked()


class QtCheckBoxWidget(QtWidget):

    def __init__(self, proxy, text, properties):
        super(QtCheckBoxWidget, self).__init__(proxy, "checkbox", properties)
        self.on_checked_changed = None
        self.on_check_state_changed = None
        self.text = text
        self.proxy.CheckBox_connect(self.widget, self)
        self.__binding = None

    def close(self):
        if self.__binding:
            self.__binding.close()
            self.__binding = None
        self.clear_task("update_check_state")
        self.on_checked_changed = None
        self.on_check_state_changed = None
        super(QtCheckBoxWidget, self).close()

    @property
    def text(self):
        return self.__text

    @text.setter
    def text(self, value):
        self.__text = value
        self.proxy.CheckBox_setText(self.widget, Unicode.u(value))

    @property
    def checked(self):
        return self.check_state == "checked"

    @checked.setter
    def checked(self, value):
        self.check_state = "checked" if value else "unchecked"

    @property
    def tristate(self):
        return self.proxy.CheckBox_getIsTristate(self.widget)

    @tristate.setter
    def tristate(self, value):
        self.proxy.CheckBox_setIsTristate(self.widget, bool(value))

    @property
    def check_state(self):
        return self.proxy.CheckBox_getCheckState(self.widget)

    @check_state.setter
    def check_state(self, value):
        if self.widget:  # may be called as task, so verify it hasn't closed yet
            self.proxy.CheckBox_setCheckState(self.widget, str(value))

    def stateChanged(self, check_state):
        if self.on_checked_changed:
            self.on_checked_changed(check_state == "checked")
        if self.on_check_state_changed:
            self.on_check_state_changed(check_state)

    # bind to state. takes ownership of binding.
    def bind_checked(self, binding):
        if self.__binding:
            self.__binding.close()
            self.__binding = None
        self.checked = binding.get_target_value()
        self.__binding = binding
        def update_checked(checked):
            if self.widget:
                self.add_task("update_checked", lambda: setattr(self, "checked", checked))
        self.__binding.target_setter = update_checked
        self.on_checked_changed = lambda checked: self.__binding.update_source(checked)

    # bind to state. takes ownership of binding.
    def bind_check_state(self, binding):
        if self.__binding:
            self.__binding.close()
            self.__binding = None
        self.check_state = binding.get_target_value()
        self.__binding = binding
        def update_check_state(check_state):
            if self.widget:
                self.add_task("update_check_state", lambda: setattr(self, "check_state", check_state))
        self.__binding.target_setter = update_check_state
        self.on_check_state_changed = lambda check_state: self.__binding.update_source(check_state)


class QtLabelWidget(QtWidget):

    def __init__(self, proxy, text, properties):
        super(QtLabelWidget, self).__init__(proxy, "label", properties)
        self.__text = None
        self.text = text
        self.__binding = None

    def close(self):
        if self.__binding:
            self.__binding.close()
            self.__binding = None
        self.clear_task("update_text")
        super(QtLabelWidget, self).close()

    def __get_text(self):
        return self.__text
    def __set_text(self, text):
        self.__text = text if text else ""
        if self.widget:  # may be called as task, so verify it hasn't closed yet
            self.proxy.Label_setText(self.widget, Unicode.u(self.__text))
    text = property(__get_text, __set_text)

    # bind to text. takes ownership of binding.
    def bind_text(self, binding):
        if self.__binding:
            self.__binding.close()
            self.__binding = None
        self.text = binding.get_target_value()
        self.__binding = binding
        def update_text(text):
            if self.widget:
                self.add_task("update_text", lambda: self.__set_text(text))
        self.__binding.target_setter = update_text


class QtSliderWidget(QtWidget):

    def __init__(self, proxy, properties):
        super(QtSliderWidget, self).__init__(proxy, "slider", properties)
        self.on_value_changed = None
        self.on_slider_pressed = None
        self.on_slider_released = None
        self.on_slider_moved = None
        self.__pressed = False
        self.__min = 0
        self.__max = 0
        self.proxy.Slider_connect(self.widget, self)
        self.minimum = self.__min
        self.maximum = self.__max
        self.__binding = None

    def close(self):
        if self.__binding:
            self.__binding.close()
            self.__binding = None
        self.clear_task("update_value")
        self.on_value_changed = None
        self.on_slider_pressed = None
        self.on_slider_released = None
        self.on_slider_moved = None
        super(QtSliderWidget, self).close()

    def __get_value(self):
        return self.proxy.Slider_getValue(self.widget)
    def __set_value(self, value):
        if self.widget:  # may be called as task, so verify it hasn't closed yet
            self.proxy.Slider_setValue(self.widget, value)
    value = property(__get_value, __set_value)

    def __get_minimum(self):
        return self.__min
    def __set_minimum(self, value):
        self.__min = value
        self.proxy.Slider_setMinimum(self.widget, value)
    minimum = property(__get_minimum, __set_minimum)

    def __get_maximum(self):
        return self.__max
    def __set_maximum(self, value):
        self.__max = value
        self.proxy.Slider_setMaximum(self.widget, value)
    maximum = property(__get_maximum, __set_maximum)

    def __get_pressed(self):
        return self.__pressed
    pressed = property(__get_pressed)

    def value_changed(self, value):
        if self.on_value_changed:
            self.on_value_changed(value)

    def slider_pressed(self):
        self.__pressed = True
        if self.on_slider_pressed:
            self.on_slider_pressed()

    def slider_released(self):
        self.__pressed = False
        if self.on_slider_released:
            self.on_slider_released()

    def slider_moved(self, value):
        if self.on_slider_moved:
            self.on_slider_moved(value)

    # bind to value. takes ownership of binding.
    def bind_value(self, binding):
        if self.__binding:
            self.__binding.close()
            self.__binding = None
        self.value = binding.get_target_value()
        self.__binding = binding
        def update_value(value):
            if self.widget:
                self.add_task("update_value", lambda: self.__set_value(value))
        self.__binding.target_setter = update_value
        self.on_value_changed = lambda value: self.__binding.update_source(value)


class QtLineEditWidget(QtWidget):

    def __init__(self, proxy, properties):
        super(QtLineEditWidget, self).__init__(proxy, "lineedit", properties)
        self.on_editing_finished = None
        self.on_escape_pressed = None
        self.on_return_pressed = None
        self.on_text_edited = None
        self.__formatter = None
        self.proxy.LineEdit_connect(self.widget, self)
        self.__binding = None
        self.__clear_button_enabled = False

    def close(self):
        if self.__binding:
            self.__binding.close()
            self.__binding = None
        self.clear_task("update_text")
        self.__formatter = None
        self.on_editing_finished = None
        self.on_escape_pressed = None
        self.on_return_pressed = None
        self.on_text_edited = None
        super(QtLineEditWidget, self).close()

    def __get_text(self):
        return self.proxy.LineEdit_getText(self.widget)
    def __set_text(self, text):
        self.proxy.LineEdit_setText(self.widget, Unicode.u(text) if text is not None else Unicode.u())
    text = property(__get_text, __set_text)

    def __get_placeholder_text(self):
        return self.proxy.LineEdit_getPlaceholderText(self.widget)
    def __set_placeholder_text(self, text):
        self.proxy.LineEdit_setPlaceholderText(self.widget, Unicode.u(text))
    placeholder_text = property(__get_placeholder_text, __set_placeholder_text)

    def __get_clear_button_enabled(self):
        return self.__clear_button_enabled
    def __set_clear_button_enabled(self, enabled):
        self.__clear_button_enabled = enabled
        self.proxy.LineEdit_setClearButtonEnabled(self.widget, enabled)
    clear_button_enabled = property(__get_clear_button_enabled, __set_clear_button_enabled)

    def __get_editable(self):
        return self.proxy.LineEdit_getEditable(self.widget)
    def __set_editable(self, editable):
        self.proxy.LineEdit_setEditable(self.widget, editable)
    editable = property(__get_editable, __set_editable)

    def __get_formatter(self):
        return self.__formatter
    def __set_formatter(self, formatter):
        self.__formatter = formatter
        if self.__formatter:
            self.__formatter.format(self.text)
    formatter = property(__get_formatter, __set_formatter)

    def select_all(self):
        self.proxy.LineEdit_selectAll(self.widget)

    def editing_finished(self, text):
        if self.__formatter:
            self.__formatter.format(text)
        if self.on_editing_finished:
            self.on_editing_finished(text)

    def escapePressed(self):
        if self.on_escape_pressed:
            self.on_escape_pressed()
            return True
        return False

    def returnPressed(self):
        if self.on_return_pressed:
            self.on_return_pressed()
            return True
        return False

    def text_edited(self, text):
        if self.on_text_edited:
            self.on_text_edited(text)

    # bind to text. takes ownership of binding.
    def bind_text(self, binding):
        if self.__binding:
            self.__binding.close()
            self.__binding = None
        self.text = binding.get_target_value()
        def update_field(text):
            if self.widget:  # may be called as task, so verify it hasn't closed yet
                self.text = text
                if self.focused:
                    self.select_all()
        self.__binding = binding
        def update_text(text):
            if self.widget:
                self.add_task("update_text", lambda: update_field(text))
        self.__binding.target_setter = update_text
        self.on_editing_finished = lambda text: self.__binding.update_source(text)

    def unbind_text(self):
        self.__binding = None
        self.on_editing_finished = None


class QtTextEditWidget(QtWidget):

    def __init__(self, proxy, properties):
        super(QtTextEditWidget, self).__init__(proxy, "textedit", properties)
        self.on_text_changed = None
        self.proxy.TextEdit_connect(self.widget, self)
        self.__binding = None
        self.__in_update = False

    def close(self):
        if self.__binding:
            self.__binding.close()
            self.__binding = None
        self.clear_task("update_text")
        self.on_text_changed = None
        super(QtTextEditWidget, self).close()

    def __get_text(self):
        return self.proxy.TextEdit_getText(self.widget)
    def __set_text(self, text):
        self.proxy.TextEdit_setText(self.widget, Unicode.u(text) if text is not None else Unicode.u())
    text = property(__get_text, __set_text)

    def __get_placeholder_text(self):
        return self.proxy.TextEdit_getPlaceholderText(self.widget)
    def __set_placeholder_text(self, text):
        self.proxy.TextEdit_setPlaceholderText(self.widget, Unicode.u(text))
    placeholder_text = property(__get_placeholder_text, __set_placeholder_text)

    def __get_editable(self):
        return self.proxy.TextEdit_getEditable(self.widget)
    def __set_editable(self, editable):
        self.proxy.TextEdit_setEditable(self.widget, editable)
    editable = property(__get_editable, __set_editable)

    def select_all(self):
        self.proxy.TextEdit_selectAll(self.widget)

    def textChanged(self):
        if self.on_text_changed:
            self.on_text_changed(self.text)

    # bind to text. takes ownership of binding.
    def bind_text(self, binding):
        if self.__binding:
            self.__binding.close()
            self.__binding = None
        self.text = binding.get_target_value()
        def update_field(text):
            if self.widget:  # may be called as task, so verify it hasn't closed yet
                self.text = text
                if self.focused:
                    pass # self.select_all()
        self.__binding = binding
        def update_text(text):
            if not self.__in_update and self.widget:
                self.add_task("update_text", lambda: update_field(text))
        self.__binding.target_setter = update_text
        def on_text_changed(text):
            self.__in_update = True
            self.__binding.update_source(text)
            self.__in_update = False
        self.on_text_changed = on_text_changed

    def unbind_text(self):
        self.__binding = None
        self.on_text_changed = None


class QtDrawingContextStorage(object):

    def __init__(self):
        self.__storage = dict()
        self.__keys_to_remove = list()

    def close(self):
        self.__storage = None

    def mark(self):
        self.__keys_to_remove = list(self.__storage.keys())

    def clean(self):
        list(map(self.__storage.__delitem__, self.__keys_to_remove))

    def begin_layer(self, drawing_context, layer_id):
        self.__storage.setdefault(layer_id, dict())["start"] = len(drawing_context.commands)

    def end_layer(self, drawing_context, layer_id):
        start = self.__storage.get(layer_id, dict())["start"]
        self.__storage.setdefault(layer_id, dict())["commands"] = copy.copy(drawing_context.commands[start:])

    def draw_layer(self, drawing_context, layer_id):
        commands = self.__storage.get(layer_id, dict())["commands"]
        drawing_context.commands.extend(commands)
        self.__keys_to_remove.remove(layer_id)


class QtCanvasWidget(QtWidget):

    def __init__(self, proxy, properties):
        super(QtCanvasWidget, self).__init__(proxy, "canvas", properties)
        self.proxy.Canvas_connect(self.widget, self)
        self.on_periodic = None
        self.on_mouse_entered = None
        self.on_mouse_exited = None
        self.on_mouse_clicked = None
        self.on_mouse_double_clicked = None
        self.on_mouse_pressed = None
        self.on_mouse_released = None
        self.on_mouse_position_changed = None
        self.on_grabbed_mouse_position_changed = None
        self.on_wheel_changed = None
        self.on_key_pressed = None
        self.on_size_changed = None
        self.on_drag_enter = None
        self.on_drag_leave = None
        self.on_drag_move = None
        self.on_drop = None
        self.width = 0
        self.height = 0
        self.__focusable = False
        self.__draw_mutex = threading.Lock()  # don't delete while drawing

    def close(self):
        with self.__draw_mutex:
            self.on_periodic = None
            self.on_mouse_entered = None
            self.on_mouse_exited = None
            self.on_mouse_clicked = None
            self.on_mouse_double_clicked = None
            self.on_mouse_pressed = None
            self.on_mouse_released = None
            self.on_mouse_position_changed = None
            self.on_grabbed_mouse_position_changed = None
            self.on_wheel_changed = None
            self.on_key_pressed = None
            self.on_size_changed = None
            self.on_drag_enter = None
            self.on_drag_leave = None
            self.on_drag_move = None
            self.on_drop = None
            super(QtCanvasWidget, self).close()

    def periodic(self):
        super(QtCanvasWidget, self).periodic()
        if self.on_periodic:
            self.on_periodic()

    @property
    def canvas_size(self):
        return (self.height, self.width)

    @property
    def focusable(self):
        return self.__focusable

    @focusable.setter
    def focusable(self, focusable):
        self.__focusable = focusable
        self.proxy.Canvas_setFocusPolicy(self.widget, 15 if focusable else 0)

    def create_drawing_context(self, storage=None):
        return DrawingContext.DrawingContext(storage)

    def create_drawing_context_storage(self):
        return QtDrawingContextStorage()

    def draw(self, drawing_context, drawing_context_storage):
        # thread safe. take care to make sure widget hasn't been deleted from underneath.
        with self.__draw_mutex:
            if self.widget:
                self.proxy.Canvas_draw(self.widget, self.proxy.convert_drawing_commands(drawing_context.commands), drawing_context_storage)

    def set_cursor_shape(self, cursor_shape):
        cursor_shape = cursor_shape or "arrow"
        self.proxy.Canvas_setCursorShape(self.widget, cursor_shape)

    def mouseEntered(self):
        if self.on_mouse_entered:
            self.on_mouse_entered()

    def mouseExited(self):
        if self.on_mouse_exited:
            self.on_mouse_exited()

    def mouseClicked(self, x, y, raw_modifiers):
        if self.on_mouse_clicked:
            self.on_mouse_clicked(x, y, QtKeyboardModifiers(raw_modifiers))

    def mouseDoubleClicked(self, x, y, raw_modifiers):
        if self.on_mouse_double_clicked:
            self.on_mouse_double_clicked(x, y, QtKeyboardModifiers(raw_modifiers))

    def mousePressed(self, x, y, raw_modifiers):
        if self.on_mouse_pressed:
            self.on_mouse_pressed(x, y, QtKeyboardModifiers(raw_modifiers))

    def mouseReleased(self, x, y, raw_modifiers):
        if self.on_mouse_released:
            self.on_mouse_released(x, y, QtKeyboardModifiers(raw_modifiers))

    def mousePositionChanged(self, x, y, raw_modifiers):
        if self.on_mouse_position_changed:
            self.on_mouse_position_changed(x, y, QtKeyboardModifiers(raw_modifiers))

    def grabbedMousePositionChanged(self, dx, dy, raw_modifiers):
        if self.on_grabbed_mouse_position_changed:
            self.on_grabbed_mouse_position_changed(dx, dy, QtKeyboardModifiers(raw_modifiers))

    def wheelChanged(self, dx, dy, is_horizontal):
        if self.on_wheel_changed:
            self.on_wheel_changed(dx, dy, is_horizontal)

    def sizeChanged(self, width, height):
        self.width = width
        self.height = height
        if self.on_size_changed:
            self.on_size_changed(self.width, self.height)

    def keyPressed(self, text, key, raw_modifiers):
        if self.on_key_pressed:
            return self.on_key_pressed(QtKey(text, key, raw_modifiers))
        return False

    def dragEnterEvent(self, raw_mime_data):
        if self.on_drag_enter:
            return self.on_drag_enter(QtMimeData(self.proxy, raw_mime_data))
        return "ignore"

    def dragLeaveEvent(self):
        if self.on_drag_leave:
            return self.on_drag_leave()
        return "ignore"

    def dragMoveEvent(self, raw_mime_data, x, y):
        if self.on_drag_move:
            return self.on_drag_move(QtMimeData(self.proxy, raw_mime_data), x, y)
        return "ignore"

    def dropEvent(self, raw_mime_data, x, y):
        if self.on_drop:
            return self.on_drop(QtMimeData(self.proxy, raw_mime_data), x, y)
        return "ignore"

    def grab_gesture(self, gesture_type):
        self.proxy.Widget_grabGesture(self.widget, gesture_type)

    def release_gesture(self, gesture_type):
        self.proxy.Widget_ungrabGesture(self.widget, gesture_type)

    def panGesture(self, delta_x, delta_y):
        if self.on_pan_gesture:
            self.on_pan_gesture(delta_x, delta_y)

    def grab_mouse(self):
        self.proxy.Canvas_grabMouse(self.widget)

    def release_mouse(self):
        self.proxy.Canvas_releaseMouse(self.widget)


# pobj
class QtTreeWidget(QtWidget):

    def __init__(self, proxy, properties):
        properties = copy.copy(properties) if properties is not None else dict()
        properties["stylesheet"] = "* { border: none; background-color: '#EEEEEE'; } TreeWidget { margin-top: 4px }"
        super(QtTreeWidget, self).__init__(proxy, "pytree", properties)
        self.proxy.TreeWidget_connect(self.widget, self)
        self.__item_model_controller = None
        self.on_key_pressed = None
        self.on_selection_changed = None
        self.on_current_item_changed = None
        self.on_item_clicked = None
        self.on_item_double_clicked = None
        self.on_item_key_pressed = None
        self.on_focus_changed = None
        self.__selection_mode = "single"

    def close(self):
        self.__item_model_controller = None
        self.on_key_pressed = None
        self.on_selection_changed = None
        self.on_current_item_changed = None
        self.on_item_clicked = None
        self.on_item_double_clicked = None
        self.on_item_key_pressed = None
        self.on_focus_changed = None
        super(QtTreeWidget, self).close()

    def __get_selection_mode(self):
        return self.__selection_mode
    def __set_selection_mode(self, selection_mode):
        self.__selection_mode = selection_mode
        self.proxy.TreeWidget_setSelectionMode(self.widget, selection_mode)
    selection_mode = property(__get_selection_mode, __set_selection_mode)

    def __get_item_model_controller(self):
        return self.__item_model_controller
    def __set_item_model_controller(self, item_model_controller):
        self.__item_model_controller = item_model_controller
        self.proxy.TreeWidget_setModel(self.widget, item_model_controller.py_item_model)
    item_model_controller = property(__get_item_model_controller, __set_item_model_controller)

    def keyPressed(self, indexes, text, key, raw_modifiers):
        if self.on_key_pressed:
            return self.on_key_pressed(indexes, QtKey(text, key, raw_modifiers))
        return False

    def treeItemChanged(self, index, parent_row, parent_id):
        if self.on_current_item_changed:
            self.on_current_item_changed(index, parent_row, parent_id)

    def treeSelectionChanged(self, selected_indexes):
        if self.on_selection_changed:
            self.on_selection_changed(selected_indexes)

    def treeItemKeyPressed(self, index, parent_row, parent_id, text, key, raw_modifiers):
        if self.on_item_key_pressed:
            return self.on_item_key_pressed(index, parent_row, parent_id, QtKey(text, key, raw_modifiers))
        return False

    def treeItemClicked(self, index, parent_row, parent_id):
        if self.on_item_clicked:
            return self.on_item_clicked(index, parent_row, parent_id)
        return False

    def treeItemDoubleClicked(self, index, parent_row, parent_id):
        if self.on_item_double_clicked:
            return self.on_item_double_clicked(index, parent_row, parent_id)
        return False

    def focusIn(self):
        if self.on_focus_changed:
            self.on_focus_changed(True)

    def focusOut(self):
        if self.on_focus_changed:
            self.on_focus_changed(False)

    def set_current_row(self, index, parent_row, parent_id):
        self.proxy.TreeWidget_setCurrentRow(self.widget, index, parent_row, parent_id)

    def clear_current_row(self):
        self.proxy.TreeWidget_setCurrentRow(self.widget, -1, -1, 0)


# pobj
class QtListWidget(QtWidget):

    def __init__(self, proxy, properties):
        properties = copy.copy(properties) if properties is not None else dict()
        properties["stylesheet"] = "* { border: none; background-color: '#EEEEEE'; } ListWidget { margin-top: 4px }"
        super(QtListWidget, self).__init__(proxy, "pylist", properties)
        self.proxy.ListWidget_connect(self.widget, self)
        self.__list_model_controller = None
        self.__on_paint = None
        self.on_current_item_changed = None
        self.on_selection_changed = None
        self.on_key_pressed = None
        self.on_item_key_pressed = None
        self.on_item_clicked = None
        self.on_item_double_clicked = None
        self.on_item_size = None
        self.on_focus_changed = None
        self.__delegate = None
        self.__selection_mode = "single"
        self.selected_indexes = list()
        self.drawing_context = DrawingContext.DrawingContext()

    def close(self):
        self.__list_model_controller = None
        self.__on_paint = None
        self.on_current_item_changed = None
        self.on_selection_changed = None
        self.on_key_pressed = None
        self.on_item_key_pressed = None
        self.on_item_clicked = None
        self.on_item_double_clicked = None
        self.on_item_size = None
        self.on_focus_changed = None
        self.__delegate = None
        super(QtListWidget, self).close()

    def __get_selection_mode(self):
        return self.__selection_mode
    def __set_selection_mode(self, selection_mode):
        self.__selection_mode = selection_mode
        self.proxy.ListWidget_setSelectionMode(self.widget, selection_mode)
    selection_mode = property(__get_selection_mode, __set_selection_mode)

    def __get_list_model_controller(self):
        return self.__list_model_controller
    def __set_list_model_controller(self, list_model_controller):
        self.__list_model_controller = list_model_controller
        self.proxy.ListWidget_setModel(self.widget, list_model_controller.py_list_model)
    list_model_controller = property(__get_list_model_controller, __set_list_model_controller)

    def set_selected_indexes(self, selected_indexes):
        self.proxy.ListWidget_setSelectedIndexes(self.widget, selected_indexes)

    def keyPressed(self, indexes, text, key, raw_modifiers):
        if self.on_key_pressed:
            return self.on_key_pressed(indexes, QtKey(text, key, raw_modifiers))
        return False

    def listItemChanged(self, index):
        if self.on_current_item_changed:
            self.on_current_item_changed(index)

    def listSelectionChanged(self, selected_indexes):
        self.selected_indexes = copy.copy(selected_indexes)
        if self.on_selection_changed:
            self.on_selection_changed(selected_indexes)

    def listItemKeyPressed(self, index, text, key, raw_modifiers):
        if self.on_item_key_pressed:
            return self.on_item_key_pressed(index, QtKey(text, key, raw_modifiers))
        return False

    def listItemClicked(self, index):
        if self.on_item_clicked:
            return self.on_item_clicked(index)
        return False

    def listItemDoubleClicked(self, index):
        if self.on_item_double_clicked:
            return self.on_item_double_clicked(index)
        return False

    def __get_current_index(self):
        return self.proxy.ListWidget_getCurrentRow(self.widget)
    def __set_current_index(self, current_index):
        if current_index != self.current_index:
            self.proxy.ListWidget_setCurrentRow(self.widget, current_index)
    current_index = property(__get_current_index, __set_current_index)

    def __get_on_paint(self):
        return self.__on_paint
    def __set_on_paint(self, fn):
        self.__on_paint = fn
        if not self.__delegate:
            self.__delegate = self.proxy.StyledDelegate_create()
            self.proxy.StyledDelegate_connect(self.__delegate, self)
            self.proxy.ListWidget_setItemDelegate(self.widget, self.__delegate)
    on_paint = property(__get_on_paint, __set_on_paint)

    # this message comes from the styled item delegate
    def paint(self, dc, options):
        if self.__on_paint:
            self.drawing_context.clear()
            self.__on_paint(self.drawing_context, options)
            # for the thrift version, this will not work. ugh.
            self.proxy.DrawingContext_drawCommands(dc, self.proxy.convert_drawing_commands(self.drawing_context.commands))

    # message from styled item delegate
    def sizeHint(self, row, parent_row, parent_id):
        if self.on_item_size:
            return self.on_item_size(row)
        return (200, 80)

    def focusIn(self):
        if self.on_focus_changed:
            self.on_focus_changed(True)

    def focusOut(self):
        if self.on_focus_changed:
            self.on_focus_changed(False)

    def get_row_at_pos(self, x, y):
        return self.proxy.ListWidget_getRowAtPoint(self.widget, x, y)

class QtNewListWidget(QtColumnWidget):

    def __init__(self, proxy, ui, create_list_item_widget, header_widget, header_for_empty_list_widget, properties):
        super(QtNewListWidget, self).__init__(proxy, properties)
        self.ui = ui
        self.__binding = None
        self.content_section = self.ui.create_column_widget()
        header_column = self.ui.create_column_widget()
        self.header_widget = header_widget
        self.header_for_empty_list_widget = header_for_empty_list_widget
        if self.header_widget:
            header_column.add(self.header_widget)
        if self.header_for_empty_list_widget:
            header_column.add(self.header_for_empty_list_widget)
        self.add(header_column)
        content_column = self.ui.create_column_widget()
        content_column.add(self.content_section)
        content_column.add_stretch()
        self.add(content_column)
        self.add_stretch()
        self.create_list_item_widget = create_list_item_widget

    def close(self):
        if self.__binding:
            self.__binding.close()
            self.__binding = None
        self.content_section = None
        self.header_widget = None
        self.header_for_empty_list_widget = None
        self.create_list_item_widget = None
        super(QtNewListWidget, self).close()

    def insert_item(self, item, before_index):
        if self.create_list_item_widget:  # item may be closed while this call is pending on main thread.
            item_row = self.create_list_item_widget(item)
            self.content_section.insert(item_row, before_index)
            self.__sync_header()

    def remove_item(self, index):
        self.content_section.remove(index)
        self.__sync_header()

    def __sync_header(self):
        # select the right header item
        has_content = self.content_section.count() > 0
        if self.header_widget:
            self.header_widget.visible = has_content
        if self.header_for_empty_list_widget:
            self.header_for_empty_list_widget.visible = not has_content

    def bind_items(self, binding):
        if self.__binding:
            self.__binding.close()
            self.__binding = None
        self.__binding = binding
        def insert_item(item, before_index):
            self.queue_task(lambda: self.insert_item(item, before_index))
        def remove_item(index):
            self.queue_task(lambda: self.remove_item(index))
        self.__binding.inserter = insert_item
        self.__binding.remover = remove_item
        for index, item in enumerate(binding.items):
            self.insert_item(item, index)
        self.__sync_header()


class QtOutputWidget(QtWidget):

    def __init__(self, proxy, properties):
        super(QtOutputWidget, self).__init__(proxy, "output", properties)

    def send(self, message):
        self.proxy.Output_out(self.widget, Unicode.u(message))


# pobj
class QtConsoleWidget(QtWidget):

    def __init__(self, proxy, properties):
        super(QtConsoleWidget, self).__init__(proxy, "console", properties)
        self.on_interpret_command = None
        self.proxy.Console_connect(self.widget, self)

    def close(self):
        self.on_interpret_command = None
        super(QtConsoleWidget, self).close()

    def interpretCommand(self, command):
        if self.on_interpret_command:
            return self.on_interpret_command(command)
        return "", 0, "?"

    def insert_lines(self, lines):
        self.proxy.Console_insertFromStringList(self.widget, lines)


class QtAction(object):

    def __init__(self, proxy, native_action=None):
        self.proxy = proxy
        self.native_action = native_action
        self.on_triggered = None
        self.__title = Unicode.u()
        self.__checked = False
        self.__enabled = True

    def close(self):
        self.proxy = None
        self.native_action = None
        self.on_triggered = None
        super(QtAction, self).close()

    def create(self, document_window, title, key_sequence, role):
        self.__title = Unicode.u(title)
        self.native_action = self.proxy.Action_create(document_window.native_document_window, self.__title, key_sequence, role)
        self.proxy.Action_connect(self.native_action, self)

    # public method to trigger button
    def trigger(self):
        if self.on_triggered:
            self.on_triggered()

    # comes from the Qt code
    def triggered(self):
        self.trigger()

    @property
    def title(self):
        return self.__title

    @title.setter
    def title(self, value):
        self.__title = Unicode.u(value)
        self.proxy.Action_setTitle(self.native_action, self.__title)

    @property
    def checked(self):
        return self.__checked

    @checked.setter
    def checked(self, checked):
        self.__checked = checked
        self.proxy.Action_setChecked(self.native_action, self.__checked)

    @property
    def enabled(self):
        return self.__enabled

    @enabled.setter
    def enabled(self, enabled):
        self.__enabled = enabled
        self.proxy.Action_setEnabled(self.native_action, self.__enabled)


class QtMenu(object):

    def __init__(self, proxy, document_window, native_menu):
        self.proxy = proxy
        self.document_window = document_window
        self.native_menu = native_menu
        self.proxy.Menu_connect(self.native_menu, self)
        self.on_about_to_show = None
        self.on_about_to_hide = None

    def destroy(self):
        self.proxy.Menu_destroy(self.native_menu)
        self.native_menu = None
        self.on_about_to_show = None
        self.on_about_to_hide = None

    def aboutToShow(self):
        if self.on_about_to_show:
            self.on_about_to_show()

    def aboutToHide(self):
        if self.on_about_to_hide:
            self.on_about_to_hide()

    def add_menu_item(self, title, callback, key_sequence=None, role=None):
        action = QtAction(self.proxy)
        action.create(self.document_window, title, key_sequence, role)
        action.on_triggered = callback
        self.proxy.Menu_addAction(self.native_menu, action.native_action)
        return action

    def add_action(self, action):
        self.proxy.Menu_addAction(self.native_menu, action.native_action)

    def add_sub_menu(self, title, menu):
        self.proxy.Menu_addMenu(self.native_menu, Unicode.u(title), menu.native_menu)

    def add_separator(self):
        self.proxy.Menu_addSeparator(self.native_menu)

    def insert_menu_item(self, title, before_action, callback, key_sequence=None, role=None):
        action = QtAction(self.proxy)
        action.create(self.document_window, title, key_sequence, role)
        action.on_triggered = callback
        self.proxy.Menu_insertAction(self.native_menu, action.native_action, before_action.native_action)
        return action

    def insert_separator(self, before_action):
        self.proxy.Menu_insertSeparator(self.native_menu, before_action.native_action)

    def remove_action(self, action):
        self.proxy.Menu_removeAction(self.native_menu, action.native_action)

    def popup(self, gx, gy):
        self.proxy.Menu_popup(self.native_menu, gx, gy)


class QtDocumentWindow(object):

    def __init__(self, proxy, title):
        self.proxy = proxy
        self.native_document_window = self.proxy.DocumentWindow_create(title)
        self.proxy.DocumentWindow_connect(self.native_document_window, self)
        self.root_widget = None
        self.has_event_loop = True
        self.window_style = "window"
        self.on_periodic = None
        self.on_queue_task = None
        self.on_add_task = None
        self.on_clear_task = None
        self.on_about_to_show = None
        self.on_about_to_close = None
        self.on_activation_changed = None
        self.__title = Unicode.u()

    def close(self):
        # this is a callback and should not be invoked directly from Python;
        # call request_close instead.
        self.native_document_window = None
        self.root_widget.close()
        self.root_widget = None
        self.on_periodic = None
        self.on_queue_task = None
        self.on_add_task = None
        self.on_clear_task = None
        self.on_about_to_show = None
        self.on_about_to_close = None
        self.on_activation_changed = None
        self.proxy = None

    def request_close(self):
        self.proxy.DocumentWindow_close(self.native_document_window)

    # attach the root widget to this window
    # the root widget must respond to _set_root_container
    def attach(self, root_widget):
        self.root_widget = root_widget
        self.root_widget._set_root_container(self)
        self.proxy.DocumentWindow_setCentralWidget(self.native_document_window, self.root_widget.widget)

    def queue_task(self, task):
        if self.on_queue_task:
            self.on_queue_task(task)

    def add_task(self, key, task):
        if self.on_add_task:
            self.on_add_task(key + str(id(self)), task)

    def clear_task(self, key):
        if self.on_clear_task:
            self.on_clear_task(key + str(id(self)))

    def get_file_paths_dialog(self, title, directory, filter, selected_filter=None):
        selected_filter = selected_filter if selected_filter else Unicode.u()
        file_paths, filter, directory = self.proxy.DocumentWindow_getFilePath(self.native_document_window, "loadmany", Unicode.u(title), Unicode.u(directory), Unicode.u(filter), Unicode.u(selected_filter))
        return file_paths, filter, directory

    def get_file_path_dialog(self, title, directory, filter, selected_filter=None):
        selected_filter = selected_filter if selected_filter else Unicode.u()
        file_path, filter, directory = self.proxy.DocumentWindow_getFilePath(self.native_document_window, "load", Unicode.u(title), Unicode.u(directory), Unicode.u(filter), Unicode.u(selected_filter))
        return file_path, filter, directory

    def get_save_file_path(self, title, directory, filter, selected_filter=None):
        selected_filter = selected_filter if selected_filter else Unicode.u()
        file_path, filter, directory = self.proxy.DocumentWindow_getFilePath(self.native_document_window, "save", Unicode.u(title), Unicode.u(directory), Unicode.u(filter), Unicode.u(selected_filter))
        return file_path, filter, directory

    def create_dock_widget(self, widget, panel_id, title, positions, position):
        return QtDockWidget(self.proxy, self, widget, panel_id, title, positions, position)

    def tabify_dock_widgets(self, dock_widget1, dock_widget2):
        self.proxy.DocumentWindow_tabifyDockWidgets(self.native_document_window, dock_widget1.native_dock_widget, dock_widget2.native_dock_widget)

    # call show to display the window.
    def show(self, size=None, position=None):
        if size is not None:
            self.proxy.DocumentWindow_setSize(self.native_document_window, size.width, size.height)
        if position is not None:
            self.proxy.DocumentWindow_setPosition(self.native_document_window, position.x, position.y)
        self.proxy.DocumentWindow_show(self.native_document_window, self.window_style)

    @property
    def title(self):
        return self.__title

    @title.setter
    def title(self, value):
        self.__title = value
        self.proxy.DocumentWindow_setTitle(self.native_document_window, Unicode.u(value))

    # periodic is called periodically from the user interface object to service the window.
    def periodic(self):
        if self.root_widget:
            self.root_widget.periodic()
        if self.native_document_window and self.on_periodic:
            self.on_periodic()

    def aboutToShow(self):
        if self.on_about_to_show:
            self.on_about_to_show()

    def activationChanged(self, activated):
        if self.on_activation_changed:
            self.on_activation_changed(activated)

    def aboutToClose(self, geometry, state):
        if self.on_about_to_close:
            self.on_about_to_close(geometry, state)

    def add_menu(self, title):
        native_menu = self.proxy.DocumentWindow_addMenu(self.native_document_window, Unicode.u(title))
        menu = QtMenu(self.proxy, self, native_menu)
        return menu

    def insert_menu(self, title, before_menu):
        native_menu = self.proxy.DocumentWindow_insertMenu(self.native_document_window, Unicode.u(title), before_menu.native_menu)
        menu = QtMenu(self.proxy, self, native_menu)
        return menu

    def restore(self, geometry, state):
        self.proxy.DocumentWindow_restore(self.native_document_window, geometry, state)


class QtDockWidget(object):

    def __init__(self, proxy, document_window, widget, panel_id, title, positions, position):
        self.proxy = proxy
        self.document_window = document_window
        self.widget = widget
        self.widget._set_root_container(self)
        self.native_dock_widget = self.proxy.DocumentWindow_addDockWidget(self.document_window.native_document_window, widget.widget, panel_id, Unicode.u(title), positions, position)

    def close(self):
        self.proxy.DocumentWindow_removeDockWidget(self.document_window.native_document_window, self.native_dock_widget)
        self.widget.close()
        self.document_window = None
        self.widget = None
        self.native_dock_widget = None
        self.proxy = None

    def queue_task(self, task):
        self.document_window.queue_task(task)

    def add_task(self, key, task):
        self.document_window.add_task(key + str(id(self)), task)

    def clear_task(self, key):
        self.document_window.clear_task(key + str(id(self)))

    def periodic(self):
        self.widget.periodic()

    def __get_toggle_action(self):
        return QtAction(self.proxy, self.proxy.DockWidget_getToggleAction(self.native_dock_widget))
    toggle_action = property(__get_toggle_action)

    def show(self):
        self.proxy.Widget_show(self.native_dock_widget)

    def hide(self):
        self.proxy.Widget_hide(self.native_dock_widget)


QtFontMetrics = collections.namedtuple("FontMetrics", ["width", "height", "ascent", "descent", "leading"])


class QtUserInterface(object):

    def __init__(self, proxy):
        self.proxy = proxy
        self.periodic_items = list()
        self.persistence_root = "0"

    def close(self):
        self.proxy.Application_close()
        self.periodic_items = None
        self.proxy = None

    def periodic(self):
        for periodic_item in self.periodic_items:
            periodic_item.periodic()

    # data objects

    def create_mime_data(self):
        return QtMimeData(self.proxy)

    def create_item_model_controller(self, keys):
        return QtItemModelController(self.proxy, keys)

    def create_list_model_controller(self, keys):
        return QtListModelController(self.proxy, keys)

    # window elements

    def create_document_window(self, title=None):
        document_window = QtDocumentWindow(self.proxy, title)
        self.periodic_items.append(document_window)
        return document_window

    def destroy_document_window(self, document_window):
        if document_window in self.periodic_items:
            self.periodic_items.remove(document_window)

    # user interface elements

    def create_row_widget(self, properties=None):
        return QtRowWidget(self.proxy, properties)

    def create_column_widget(self, properties=None):
        return QtColumnWidget(self.proxy, properties)

    def create_splitter_widget(self, orientation="vertical", properties=None):
        return QtSplitterWidget(self.proxy, orientation, properties)

    def create_tab_widget(self, properties=None):
        return QtTabWidget(self.proxy, properties)

    def create_stack_widget(self, properties=None):
        return QtStackWidget(self.proxy, properties)

    def create_scroll_area_widget(self, properties=None):
        return QtScrollAreaWidget(self.proxy, properties)

    def create_combo_box_widget(self, items=None, item_getter=None, properties=None):
        return QtComboBoxWidget(self.proxy, items, item_getter, properties)

    def create_push_button_widget(self, text=None, properties=None):
        return QtPushButtonWidget(self.proxy, text, properties)

    def create_check_box_widget(self, text=None, properties=None):
        return QtCheckBoxWidget(self.proxy, text, properties)

    def create_label_widget(self, text=None, properties=None):
        return QtLabelWidget(self.proxy, text, properties)

    def create_slider_widget(self, properties=None):
        return QtSliderWidget(self.proxy, properties)

    def create_line_edit_widget(self, properties=None):
        return QtLineEditWidget(self.proxy, properties)

    def create_text_edit_widget(self, properties=None):
        return QtTextEditWidget(self.proxy, properties)

    def create_canvas_widget(self, properties=None):
        return QtCanvasWidget(self.proxy, properties)

    def create_tree_widget(self, properties=None):
        return QtTreeWidget(self.proxy, properties)

    def create_list_widget(self, properties=None):
        return QtListWidget(self.proxy, properties)

    def create_new_list_widget(self, create_list_item_widget, header_widget=None, header_for_empty_list_widget=None, properties=None):
        return QtNewListWidget(self.proxy, self, create_list_item_widget, header_widget, header_for_empty_list_widget, properties)

    def create_output_widget(self, properties=None):
        return QtOutputWidget(self.proxy, properties)

    def create_console_widget(self, properties=None):
        return QtConsoleWidget(self.proxy, properties)

    # file i/o

    def load_rgba_data_from_file(self, filename):
        # returns data packed as uint32
        return self.proxy.decode_data(self.proxy.Core_readImageToBinary(Unicode.u(filename)))

    def save_rgba_data_to_file(self, data, filename, format):
        return self.proxy.Core_writeBinaryToImage(data.shape[1], data.shape[0], data, Unicode.u(filename), str(format))

    def get_existing_directory_dialog(self, title, directory):
        existing_directory, filter, directory = self.proxy.DocumentWindow_getFilePath(None, "directory", Unicode.u(title), Unicode.u(directory), Unicode.u(), Unicode.u())
        return existing_directory, directory

    # persistence (associated with application)

    def get_data_location(self):
        return self.proxy.Core_getLocation("data")

    def get_document_location(self):
        return self.proxy.Core_getLocation("documents")

    def get_temporary_location(self):
        return self.proxy.Core_getLocation("temporary")

    def get_persistent_string(self, key, default_value=None):
        key = "/".join([self.persistence_root, key])
        value = self.proxy.Settings_getString(key)
        return value if value else default_value

    def set_persistent_string(self, key, value):
        key = "/".join([self.persistence_root, key])
        self.proxy.Settings_setString(key, value)

    def get_persistent_object(self, key, default_value=None):
        key = "/".join([self.persistence_root, key])
        value = self.get_persistent_string(key)
        return pickle.loads(binascii.unhexlify(value.encode("utf-8"))) if value else default_value

    def set_persistent_object(self, key, value):
        key = "/".join([self.persistence_root, key])
        self.set_persistent_string(key, binascii.hexlify(pickle.dumps(value, 0)).decode("utf-8"))

    def remove_persistent_key(self, key):
        key = "/".join([self.persistence_root, key])
        self.proxy.Settings_remove(key)

    # clipboard

    def clipboard_clear(self):
        self.proxy.Clipboard_clear()

    def clipboard_mime_data(self):
        return QtMimeData(self.proxy, self.proxy.Clipboard_mimeData())

    def clipboard_set_mime_data(self, mime_data):
        self.proxy.Clipboard_setMimeData(mime_data.raw_mime_data)

    def clipboard_set_text(self, text):
        self.proxy.Clipboard_setText(text)

    def clipboard_text(self):
        return self.proxy.Clipboard_text()

    # misc

    def create_offscreen_drawing_context(self):
        return DrawingContext.DrawingContext()

    def create_rgba_image(self, drawing_context, width, height):
        return self.proxy.decode_data(self.proxy.DrawingContext_paintRGBA(self.proxy.convert_drawing_commands(drawing_context.commands), width, height))

    def get_font_metrics(self, font, text):
        return self.proxy.decode_font_metrics(self.proxy.Core_getFontMetrics(font, text))

    def create_context_menu(self, document_window):
        context_menu = QtMenu(self.proxy, document_window, self.proxy.Menu_create())
        # the original code would destroy the menu when it was being hidden.
        # this caused crashes (right-click, Export...). the menu seems to be
        # still in use at the time it is hidden on Windows. so, delay its
        # destruction.
        context_menu.on_about_to_hide = lambda: document_window.queue_task(context_menu.destroy)
        return context_menu

    def create_sub_menu(self, document_window):
        sub_menu = QtMenu(self.proxy, document_window, self.proxy.Menu_create())
        return sub_menu
