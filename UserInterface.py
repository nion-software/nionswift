# standard libraries
import logging
import math
import os
import Queue
import threading
import time
import uuid
import weakref

# third party libraries
import NionLib

# local libraries
from nion.swift.Decorators import ProcessingThread
from nion.swift.Decorators import queue_main_thread
from nion.swift.Decorators import queue_main_thread_sync
from nion.swift.Decorators import relative_file
from nion.swift import Graphics
from nion.swift import Image


class QtKeyboardModifiers(object):
    def __init__(self, raw_modifiers):
        self.raw_modifiers = raw_modifiers
    def __str__(self):
        return str(self.raw_modifiers)
    # shift
    def __get_shift(self):
        return (self.raw_modifiers & 0x02000000) == 0x02000000
    shift = property(__get_shift)
    def __get_only_shift(self):
        return self.raw_modifiers == 0x02000000
    only_shift = property(__get_only_shift)
    # control (command key on mac)
    def __get_control(self):
        return (self.raw_modifiers & 0x04000000) == 0x04000000
    control = property(__get_control)
    def __get_only_control(self):
        return self.raw_modifiers == 0x04000000
    only_control = property(__get_only_control)
    # alt (option key on mac)
    def __get_alt(self):
        return (self.raw_modifiers & 0x08000000) == 0x08000000
    alt = property(__get_alt)
    def __get_only_alt(self):
        return self.raw_modifiers == 0x08000000
    only_alt = property(__get_only_alt)
    # option (alt key on windows)
    def __get_option(self):
        return (self.raw_modifiers & 0x08000000) == 0x08000000
    option = property(__get_option)
    def __get_only_option(self):
        return self.raw_modifiers == 0x08000000
    only_option = property(__get_only_option)
    # meta (control key on mac)
    def __get_meta(self):
        return (self.raw_modifiers & 0x10000000) == 0x10000000
    meta = property(__get_meta)
    def __get_only_meta(self):
        return self.raw_modifiers == 0x10000000
    only_meta = property(__get_only_meta)
    # keypad
    def __get_keypad(self):
        return (self.raw_modifiers & 0x20000000) == 0x20000000
    keypad = property(__get_keypad)
    def __get_only_keypad(self):
        return self.raw_modifiers == 0x20000000
    only_keypad = property(__get_only_keypad)


class QtMimeData(object):
    def __init__(self, mime_data=None):
        self.raw_mime_data = mime_data if mime_data else NionLib.MimeData_create()
    def __get_formats(self):
        return NionLib.MimeData_formats(self.raw_mime_data)
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
            file_path = NionLib.Core_URLToPath(url)
            if file_path and len(file_path) > 0 and os.path.isfile(file_path) and os.path.exists(file_path):
                file_paths.append(file_path)
        return file_paths
    file_paths = property(__get_file_paths)
    def data_as_string(self, format):
        return NionLib.MimeData_dataAsString(self.raw_mime_data, format)
    def set_data_as_string(self, format, text):
        NionLib.MimeData_setDataAsString(self.raw_mime_data, format, text)


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

    def __init__(self, keys):
        self.py_item_model = NionLib.PyItemModel_create(self, ["index"] + keys)
        self.__next_id = 0
        self.root = self.create_item()
        self.on_item_set_data = None
        self.on_item_drop_mime_data = None
        self.on_item_mime_data = None
        self.on_remove_rows = None
        self.supported_drop_actions = 0
        self.mime_types_for_drop = []

    def close(self):
        NionLib.PyItemModel_destroy(self.py_item_model)

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
            return self.on_item_drop_mime_data(QtMimeData(raw_mime_data), action, row, parent_row, parent_id)
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
        NionLib.PyItemModel_beginInsertRows(self.py_item_model, first_row, last_row, parent_row, parent_id)

    def end_insert(self):
        NionLib.PyItemModel_endInsertRow(self.py_item_model)

    def begin_remove(self, first_row, last_row, parent_row, parent_id):
        NionLib.PyItemModel_beginRemoveRows(self.py_item_model, first_row, last_row, parent_row, parent_id)

    def end_remove(self):
        NionLib.PyItemModel_endRemoveRow(self.py_item_model)

    def data_changed(self, row, parent_row, parent_id):
        NionLib.PyItemModel_dataChanged(self.py_item_model, row, parent_row, parent_id)


class QtListModelController(object):

    NONE = 0
    COPY = 1
    MOVE = 2
    LINK = 4

    DRAG = 1
    DROP = 2

    def __init__(self, keys):
        self.py_list_model = NionLib.PyListModel_create(self, ["index"] + keys)
        self.model = []
        self.on_item_drop_mime_data = None
        self.on_item_mime_data = None
        self.on_remove_rows = None
        self.supported_drop_actions = 0
        self.mime_types_for_drop = []
    def close(self):
        NionLib.PyListModel_destroy(self.py_list_model)
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
            return self.on_item_drop_mime_data(QtMimeData(raw_mime_data), action, row, parent_row)
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
        NionLib.PyListModel_beginInsertRows(self.py_list_model, first_row, last_row)
    def end_insert(self):
        NionLib.PyListModel_endInsertRow(self.py_list_model)
    def begin_remove(self, first_row, last_row):
        NionLib.PyListModel_beginRemoveRows(self.py_list_model, first_row, last_row)
    def end_remove(self):
        NionLib.PyListModel_endRemoveRow(self.py_list_model)
    def data_changed(self):
        NionLib.PyListModel_dataChanged(self.py_list_model)


class QtDrawingContext(object):
    def __init__(self):
        self.js = ""
        self.commands = []
        self.save_count = 0
    def clear(self):
        self.js = ""
        self.commands = []
        self.save_count = 0
    def save(self):
        self.js += "ctx.save();"
        self.commands.append(("save", ))
        self.save_count = self.save_count + 1
    def restore(self):
        self.js += "ctx.restore();"
        self.commands.append(("restore", ))
        self.save_count = self.save_count - 1
    def beginPath(self):
        self.js += "ctx.beginPath();"
        self.commands.append(("beginPath", ))
    def closePath(self):
        self.js += "ctx.closePath();"
        self.commands.append(("closePath", ))
    def translate(self, x, y):
        self.js += "ctx.translate({0}, {1});".format(x, y)
        self.commands.append(("translate", float(x), float(y)))
    def scale(self, x, y):
        self.js += "ctx.scale({0}, {1});".format(x, y)
        self.commands.append(("scale", float(x), float(y)))
    def moveTo(self, x, y):
        self.js += "ctx.moveTo({0}, {1});".format(x, y)
        self.commands.append(("moveTo", float(x), float(y)))
    def lineTo(self, x, y):
        self.js += "ctx.lineTo({0}, {1});".format(x, y)
        self.commands.append(("lineTo", float(x), float(y)))
    def rect(self, a, b, c, d):
        self.js += "ctx.rect({0}, {1}, {2}, {3});".format(a, b, c, d)
        self.commands.append(("rect", float(a), float(b), float(c), float(d)))
    def arc(self, a, b, c, d, e, f):
        self.js += "ctx.arc({0}, {1}, {2}, {3}, {4}, {5});".format(a, b, c, d, e, "true" if f else "false")
        self.commands.append(("arc", float(a), float(b), float(c), float(d), float(e), bool(f)))
    def drawImage(self, img, a, b, c, d):
        self.js += "ctx.rect({0}, {1}, {2}, {3});".format(a, b, c, d)
        self.commands.append(("image", img, float(a), float(b), float(c), float(d)))
    def stroke(self):
        self.js += "ctx.stroke();"
        self.commands.append(("stroke", ))
    def fill(self):
        self.js += "ctx.fill();"
        self.commands.append(("fill", ))
    def fillText(self, text, x, y, maxWidth=None):
        self.js += "ctx.fillText('{0}', {1}, {2}{3});".format(text, x, y, ", {0}".format(maxWidth) if maxWidth else "")
        self.commands.append(("fillText", text, float(x), float(y), float(maxWidth) if maxWidth else None))
    def __get_fillStyle(self):
        raise NotImplementedError()
    def __set_fillStyle(self, a):
        if isinstance(a, QtDrawingContext.LinearGradient):
            self.js += "ctx.fillStyle = {0};".format(a.js_var)
            self.commands.append(("fillStyleGradient", int(a.command_var)))
        else:
            self.js += "ctx.fillStyle = '{0}';".format(a)
            self.commands.append(("fillStyle", str(a)))
    fillStyle = property(__get_fillStyle, __set_fillStyle)
    def __get_font(self):
        raise NotImplementedError()
    def __set_font(self, a):
        self.js += "ctx.font = '{0}';".format(a)
        self.commands.append(("font", str(a)))
    font = property(__get_font, __set_font)
    def __get_textAlign(self):
        raise NotImplementedError()
    def __set_textAlign(self, a):
        self.js += "ctx.textAlign = '{0}';".format(a)
        self.commands.append(("textAlign", str(a)))
    textAlign = property(__get_textAlign, __set_textAlign)
    def __get_textBaseline(self):
        raise NotImplementedError()
    def __set_textBaseline(self, a):
        self.js += "ctx.textBaseline = '{0}';".format(a)
        self.commands.append(("textBaseline", str(a)))
    textBaseline = property(__get_textBaseline, __set_textBaseline)
    def __get_strokeStyle(self):
        raise NotImplementedError()
    def __set_strokeStyle(self, a):
        self.js += "ctx.strokeStyle = '{0}';".format(a)
        self.commands.append(("strokeStyle", str(a)))
    strokeStyle = property(__get_strokeStyle, __set_strokeStyle)
    def __get_lineWidth(self):
        raise NotImplementedError()
    def __set_lineWidth(self, a):
        self.js += "ctx.lineWidth = {0};".format(a)
        self.commands.append(("lineWidth", float(a)))
    lineWidth = property(__get_lineWidth, __set_lineWidth)
    def __get_lineCap(self):
        raise NotImplementedError()
    def __set_lineCap(self, a):
        self.js += "ctx.lineCap = '{0}';".format(a)
        self.commands.append(("lineCap", str(a)))
    lineCap = property(__get_lineCap, __set_lineCap)
    def __get_lineJoin(self):
        raise NotImplementedError()
    def __set_lineJoin(self, a):
        self.js += "ctx.lineJoin = '{0}';".format(a)
        self.commands.append(("lineJoin", str(a)))
    lineJoin = property(__get_lineJoin, __set_lineJoin)
    class LinearGradient:
        next = 1
        def __init__(self, context, x, y, width, height):
            self.weak_context = weakref.ref(context)
            self.js_var = "grad"+str(QtDrawingContext.LinearGradient.next)
            self.command_var = QtDrawingContext.LinearGradient.next
            self.js = "var {0} = ctx.createLinearGradient({1}, {2}, {3}, {4});".format(self.js_var, x, y, width, height)
            self.commands = []
            self.commands.append(("gradient", self.command_var, float(x), float(y), float(width), float(height)))
            QtDrawingContext.LinearGradient.next = QtDrawingContext.LinearGradient.next + 1
        def add_color_stop(self, x, color):
            self.weak_context().js += "{0}.addColorStop({1}, '{2}');".format(self.js_var, x, color)
            self.weak_context().commands.append(("colorStop", self.command_var, float(x), str(color)))
    def create_linear_gradient(self, x, y, width, height):
        gradient = QtDrawingContext.LinearGradient(self, x, y, width, height)
        self.js += gradient.js
        self.commands.extend(gradient.commands)
        return gradient


class QtWidget(object):
    def __init__(self, widget_type, properties):
        self.properties = properties if properties else {}
        self.widget = NionLib.Widget_loadIntrinsicWidget(widget_type) if widget_type else None
        self.update_properties()

    def update_properties(self):
        if self.widget:
            for key in self.properties.keys():
                NionLib.Widget_setWidgetProperty(self.widget, key, self.properties[key])

    def __get_focused(self):
        return NionLib.Widget_hasFocus(self.widget)
    def __set_focused(self, focused):
        if focused != self.focused:
            if focused:
                NionLib.Widget_setFocus(self.widget, 7)
            else:
                NionLib.Widget_clearFocus(self.widget)
    focused = property(__get_focused, __set_focused)


class QtBoxWidget(QtWidget):

    def __init__(self, widget_type, properties):
        super(QtBoxWidget, self).__init__(widget_type, properties)
        self.children = []

    def count(self):
        return len(self.children)

    def index(self, child):
        assert child in self.children
        return self.children.index(child)

    def insert(self, child, before):
        if isinstance(before, numbers.Integral):
            index = before
        else:
            index = self.index(before) if before else self.count()
        self.children.insert(index, child)
        assert self.widget is not None
        assert child.widget is not None
        NionLib.Widget_insertWidget(self.widget, child.widget, index)

    def add(self, child):
        self.insert(child, None)

    def remove(self, child):
        self.children.remove(child)
        NionLib.Widget_removeWidget(child.widget)

    def add_stretch(self):
        NionLib.Widget_addStretch(self.widget)

    def add_spacing(self, spacing):
        NionLib.Widget_addSpacing(self.widget, spacing)


class QtRowWidget(QtBoxWidget):

    def __init__(self, properties):
        super(QtRowWidget, self).__init__("row", properties)


class QtColumnWidget(QtBoxWidget):

    def __init__(self, properties):
        super(QtColumnWidget, self).__init__("column", properties)


class QtSplitterWidget(QtWidget):

    def __init__(self, properties):
        super(QtSplitterWidget, self).__init__("splitter", properties)
        NionLib.Widget_setWidgetProperty(self.widget, "stylesheet", "background-color: '#FFF'")

    def add(self, child):
        NionLib.Widget_addWidget(self.widget, child.widget)

    def restore_state(self, tag):
        NionLib.Splitter_restoreState(self.widget, tag)

    def save_state(self, tag):
        NionLib.Splitter_saveState(self.widget, tag)


class QtTabWidget(QtWidget):

    def __init__(self, properties):
        super(QtTabWidget, self).__init__("group", properties)
        NionLib.Widget_setWidgetProperty(self.widget, "stylesheet", "background-color: '#FFF'")

    def add(self, child, label):
        NionLib.TabWidget_addTab(self.widget, child.widget, label)

    def restore_state(self, tag):
        pass

    def save_state(self, tag):
        pass


class QtComboBoxWidget(QtWidget):

    def __init__(self, items, properties):
        super(QtComboBoxWidget, self).__init__("combobox", properties)
        self.__on_current_text_changed = None
        self.items = items if items else []
        NionLib.ComboBox_connect(self.widget, self)

    def __get_current_text(self):
        return NionLib.ComboBox_getCurrentText(self.widget)
    def __set_current_text(self, text):
        NionLib.ComboBox_setCurrentText(self.widget, text)
    current_text = property(__get_current_text, __set_current_text)

    def __get_on_current_text_changed(self):
        return self.__on_current_text_changed
    def __set_on_current_text_changed(self, fn):
        self.__on_current_text_changed = fn
    on_current_text_changed = property(__get_on_current_text_changed, __set_on_current_text_changed)

    def __get_items(self):
        return self.__items
    def __set_items(self, items):
        NionLib.ComboBox_removeAllItems(self.widget)
        for item in items:
            NionLib.ComboBox_addItem(self.widget, item)
    items = property(__get_items, __set_items)

    # this message comes from Qt implementation
    def current_text_changed(self, text):
        if self.__on_current_text_changed:
            self.__on_current_text_changed(text)


class QtPushButtonWidget(QtWidget):

    def __init__(self, text, properties):
        super(QtPushButtonWidget, self).__init__("pushbutton", properties)
        self.__on_clicked = None
        self.text = text
        NionLib.PushButton_connect(self.widget, self)

    def __get_text(self):
        return self.__text
    def __set_text(self, text):
        self.__text = text
        NionLib.PushButton_setText(self.widget, text)
    text = property(__get_text, __set_text)

    def __get_on_clicked(self):
        return self.__on_clicked
    def __set_on_clicked(self, fn):
        self.__on_clicked = fn
    on_clicked = property(__get_on_clicked, __set_on_clicked)

    def clicked(self):
        if self.__on_clicked:
            self.__on_clicked()


class QtLabelWidget(QtWidget):

    def __init__(self, text, properties):
        super(QtLabelWidget, self).__init__("label", properties)
        self.__text = None
        self.text = text

    def __get_text(self):
        return self.__text
    def __set_text(self, text):
        self.__text = text if text else ""
        NionLib.Label_setText(self.widget, self.__text)
    text = property(__get_text, __set_text)


class QtSliderWidget(QtWidget):

    def __init__(self, properties):
        super(QtSliderWidget, self).__init__("slider", properties)
        self.__on_value_changed = None
        self.__on_slider_pressed = None
        self.__on_slider_released = None
        self.__on_slider_moved = None
        self.__pressed = False
        self.__min = 0
        self.__max = 0
        NionLib.Slider_connect(self.widget, self)
        self.minimum = self.__min
        self.maximum = self.__max

    def __get_value(self):
        return NionLib.Slider_getValue(self.widget)
    def __set_value(self, value):
        NionLib.Slider_setValue(self.widget, value)
    value = property(__get_value, __set_value)

    def __get_minimum(self):
        return self.__min
    def __set_minimum(self, value):
        self.__min = value
        NionLib.Slider_setMinimum(self.widget, value)
    minimum = property(__get_minimum, __set_minimum)

    def __get_maximum(self):
        return self.__max
    def __set_maximum(self, value):
        self.__max = value
        NionLib.Slider_setMaximum(self.widget, value)
    maximum = property(__get_maximum, __set_maximum)

    def __get_pressed(self):
        return self.__pressed
    pressed = property(__get_pressed)

    def __get_on_value_changed(self):
        return self.__on_value_changed
    def __set_on_value_changed(self, fn):
        self.__on_value_changed = fn
    on_value_changed = property(__get_on_value_changed, __set_on_value_changed)

    def __get_on_slider_pressed(self):
        return self.__on_slider_pressed
    def __set_on_slider_pressed(self, fn):
        self.__on_slider_pressed = fn
    on_slider_pressed = property(__get_on_slider_pressed, __set_on_slider_pressed)

    def __get_on_slider_released(self):
        return self.__on_slider_released
    def __set_on_slider_released(self, fn):
        self.__on_slider_released = fn
    on_slider_released = property(__get_on_slider_released, __set_on_slider_released)

    def __get_on_slider_moved(self):
        return self.__on_slider_moved
    def __set_on_slider_moved(self, fn):
        self.__on_slider_moved = fn
    on_slider_moved = property(__get_on_slider_moved, __set_on_slider_moved)

    def value_changed(self, value):
        if self.__on_value_changed:
            self.__on_value_changed(value)

    def slider_pressed(self):
        self.__pressed = True
        if self.__on_slider_pressed:
            self.__on_slider_pressed()

    def slider_released(self):
        self.__pressed = False
        if self.__on_slider_released:
            self.__on_slider_released()

    def slider_moved(self, value):
        if self.__on_slider_moved:
            self.__on_slider_moved(value)


class QtLineEditWidget(QtWidget):

    def __init__(self, properties):
        super(QtLineEditWidget, self).__init__("lineedit", properties)
        self.__on_editing_finished = None
        self.__on_text_edited = None
        self.__formatter = None
        NionLib.LineEdit_connect(self.widget, self)

    def __get_text(self):
        return NionLib.LineEdit_getText(self.widget)
    def __set_text(self, text):
        NionLib.LineEdit_setText(self.widget, text)
    text = property(__get_text, __set_text)

    def __get_formatter(self):
        return self.__formatter
    def __set_formatter(self, formatter):
        self.__formatter = formatter
        if self.__formatter:
            self.__formatter.format(self.text)
    formatter = property(__get_formatter, __set_formatter)

    def __get_on_editing_finished(self):
        return self.__on_editing_finished
    def __set_on_editing_finished(self, fn):
        self.__on_editing_finished = fn
    on_editing_finished = property(__get_on_editing_finished, __set_on_editing_finished)

    def __get_on_text_edited(self):
        return self.__on_text_edited
    def __set_on_text_edited(self, fn):
        self.__on_text_edited = fn
    on_text_edited = property(__get_on_text_edited, __set_on_text_edited)

    def select_all(self):
        NionLib.LineEdit_selectAll(self.widget)

    def editing_finished(self, text):
        if self.__formatter:
            self.__formatter.format(text)
        if self.__on_editing_finished:
            self.__on_editing_finished(text)

    def text_edited(self, text):
        if self.__on_text_edited:
            self.__on_text_edited(text)


class QtCanvasWidget(QtWidget):

    def __init__(self, properties):
        super(QtCanvasWidget, self).__init__("canvas", properties)
        NionLib.Canvas_connect(self.widget, self)
        self.__on_mouse_entered = None
        self.__on_mouse_exited = None
        self.__on_mouse_clicked = None
        self.__on_mouse_double_clicked = None
        self.__on_mouse_pressed = None
        self.__on_mouse_released = None
        self.__on_mouse_position_changed = None
        self.__on_key_pressed = None
        self.__on_size_changed = None
        self.__on_focus_changed = None
        self.width = 0
        self.height = 0
        self.__focusable = False
        self.layers = []
        self.update_properties()

    def __get_focusable(self):
        return self.__focusable
    def __set_focusable(self, focusable):
        self.__focusable = focusable
        NionLib.Canvas_setFocusPolicy(self.widget, 15 if focusable else 0)
    focusable = property(__get_focusable, __set_focusable)

    class Layer(object):
        def __init__(self, canvas):
            self.__weak_canvas = weakref.ref(canvas)
            self.__drawing_context = QtDrawingContext()

        def __get_canvas(self):
            return self.__weak_canvas()
        canvas = property(__get_canvas)

        def __get_drawing_context(self):
            return self.__drawing_context
        drawing_context = property(__get_drawing_context)

    def create_layer(self):
        layer = QtCanvasWidget.Layer(self)
        self.layers.append(layer)
        return layer

    def draw(self):
        commands = []
        for layer in self.layers:
            commands.extend(layer.drawing_context.commands)
            assert layer.drawing_context.save_count == 0
        NionLib.Canvas_draw(self.widget, commands)

    def __get_on_mouse_entered(self):
        return self.__on_mouse_entered
    def __set_on_mouse_entered(self, fn):
        self.__on_mouse_entered = fn
    on_mouse_entered = property(__get_on_mouse_entered, __set_on_mouse_entered)

    def __get_on_mouse_exited(self):
        return self.__on_mouse_exited
    def __set_on_mouse_exited(self, fn):
        self.__on_mouse_exited = fn
    on_mouse_exited = property(__get_on_mouse_exited, __set_on_mouse_exited)

    def __get_on_mouse_clicked(self):
        return self.__on_mouse_clicked
    def __set_on_mouse_clicked(self, fn):
        self.__on_mouse_clicked = fn
    on_mouse_clicked = property(__get_on_mouse_clicked, __set_on_mouse_clicked)

    def __get_on_mouse_double_clicked(self):
        return self.__on_mouse_double_clicked
    def __set_on_mouse_double_clicked(self, fn):
        self.__on_mouse_double_clicked = fn
    on_mouse_double_clicked = property(__get_on_mouse_double_clicked, __set_on_mouse_double_clicked)

    def __get_on_mouse_pressed(self):
        return self.__on_mouse_pressed
    def __set_on_mouse_pressed(self, fn):
        self.__on_mouse_pressed = fn
    on_mouse_pressed = property(__get_on_mouse_pressed, __set_on_mouse_pressed)

    def __get_on_mouse_released(self):
        return self.__on_mouse_released
    def __set_on_mouse_released(self, fn):
        self.__on_mouse_released = fn
    on_mouse_released = property(__get_on_mouse_released, __set_on_mouse_released)

    def __get_on_mouse_position_changed(self):
        return self.__on_mouse_position_changed
    def __set_on_mouse_position_changed(self, fn):
        self.__on_mouse_position_changed = fn
    on_mouse_position_changed = property(__get_on_mouse_position_changed, __set_on_mouse_position_changed)

    def __get_on_size_changed(self):
        return self.__on_size_changed
    def __set_on_size_changed(self, fn):
        self.__on_size_changed = fn
    on_size_changed = property(__get_on_size_changed, __set_on_size_changed)

    def __get_on_focus_changed(self):
        return self.__on_focus_changed
    def __set_on_focus_changed(self, fn):
        self.__on_focus_changed = fn
    on_focus_changed = property(__get_on_focus_changed, __set_on_focus_changed)

    def __get_on_key_pressed(self):
        return self.__on_key_pressed
    def __set_on_key_pressed(self, fn):
        self.__on_key_pressed = fn
    on_key_pressed = property(__get_on_key_pressed, __set_on_key_pressed)

    def mouseEntered(self):
        if self.__on_mouse_entered:
            self.__on_mouse_entered()

    def mouseExited(self):
        if self.__on_mouse_exited:
            self.__on_mouse_exited()

    def mouseClicked(self, x, y, raw_modifiers):
        if self.__on_mouse_clicked:
            self.__on_mouse_clicked(x, y, QtKeyboardModifiers(raw_modifiers))

    def mouseDoubleClicked(self, x, y, raw_modifiers):
        if self.__on_mouse_double_clicked:
            self.__on_mouse_double_clicked(x, y, QtKeyboardModifiers(raw_modifiers))

    def mousePressed(self, x, y, raw_modifiers):
        if self.__on_mouse_pressed:
            self.__on_mouse_pressed(x, y, QtKeyboardModifiers(raw_modifiers))

    def mouseReleased(self, x, y, raw_modifiers):
        if self.__on_mouse_released:
            self.__on_mouse_released(x, y, QtKeyboardModifiers(raw_modifiers))

    def mousePositionChanged(self, x, y, raw_modifiers):
        if self.__on_mouse_position_changed:
            self.__on_mouse_position_changed(x, y, QtKeyboardModifiers(raw_modifiers))

    def sizeChanged(self, width, height):
        self.width = width
        self.height = height
        if self.__on_size_changed:
            self.__on_size_changed(self.width, self.height)

    def focusIn(self):
        if self.__on_focus_changed:
            self.__on_focus_changed(True)

    def focusOut(self):
        if self.__on_focus_changed:
            self.__on_focus_changed(False)

    def keyPressed(self, text, key, raw_modifiers):
        if self.__on_key_pressed:
            return self.__on_key_pressed(text, key, QtKeyboardModifiers(raw_modifiers))
        return False


class QtTreeWidget(QtWidget):

    def __init__(self, properties):
        super(QtTreeWidget, self).__init__("pytree", properties)
        NionLib.Widget_setWidgetProperty(self.widget, "stylesheet", "* { border: none; background-color: '#EEEEEE'; } PyTreeWidget { margin-top: 4px }")
        NionLib.PyTreeWidget_connect(self.widget, self)
        self.__item_model_controller = None
        self.on_key_pressed = None
        self.on_current_item_changed = None
        self.on_item_clicked = None
        self.on_item_double_clicked = None

    def __get_item_model_controller(self):
        return self.__item_model_controller
    def __set_item_model_controller(self, item_model_controller):
        self.__item_model_controller = item_model_controller
        NionLib.PyTreeWidget_setModel(self.widget, item_model_controller.py_item_model)
    item_model_controller = property(__get_item_model_controller, __set_item_model_controller)

    def treeItemChanged(self, index, parent_row, parent_id):
        if self.on_current_item_changed:
            self.on_current_item_changed(index, parent_row, parent_id)

    def treeItemKeyPress(self, index, parent_row, parent_id, text, raw_modifiers):
        if self.on_item_key_pressed:
            return self.on_item_key_pressed(index, parent_row, parent_id, text, QtKeyboardModifiers(raw_modifiers))
        return False

    def treeItemClicked(self, index, parent_row, parent_id):
        if self.on_item_clicked:
            return self.on_item_clicked(index, parent_row, parent_id)
        return False

    def treeItemDoubleClicked(self, index, parent_row, parent_id):
        if self.on_item_double_clicked:
            return self.on_item_double_clicked(index, parent_row, parent_id)
        return False

    def set_current_row(self, index, parent_row, parent_id):
        NionLib.PyTreeWidget_setCurrentRow(self.widget, index, parent_row, parent_id)


class QtListWidget(QtWidget):

    def __init__(self, properties):
        super(QtListWidget, self).__init__("pylist", properties)
        NionLib.Widget_setWidgetProperty(self.widget, "stylesheet", "* { border: none; background-color: '#EEEEEE'; } PyListWidget { margin-top: 4px }")
        NionLib.PyListWidget_connect(self.widget, self)
        self.__list_model_controller = None
        self.__on_paint = None
        self.on_current_item_changed = None
        self.on_item_key_pressed = None
        self.on_item_clicked = None
        self.on_item_double_clicked = None
        self.__delegate = None

    def __get_list_model_controller(self):
        return self.__list_model_controller
    def __set_list_model_controller(self, list_model_controller):
        self.__list_model_controller = list_model_controller
        NionLib.PyListWidget_setModel(self.widget, list_model_controller.py_list_model)
    list_model_controller = property(__get_list_model_controller, __set_list_model_controller)

    def listItemChanged(self, index):
        if self.on_current_item_changed:
            self.on_current_item_changed(index)

    def listItemKeyPress(self, index, text, raw_modifiers):
        if self.on_item_key_pressed:
            return self.on_item_key_pressed(index, text, QtKeyboardModifiers(raw_modifiers))
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
        return NionLib.PyListWidget_getCurrentRow(self.widget)
    def __set_current_index(self, current_index):
        return NionLib.PyListWidget_setCurrentRow(self.widget, current_index)
    current_index = property(__get_current_index, __set_current_index)

    def __get_on_paint(self):
        return self.__on_paint
    def __set_on_paint(self, fn):
        self.__on_paint = fn
        if not self.__delegate:
            self.__delegate = NionLib.PyStyledDelegate_create()
            NionLib.PyStyledDelegate_connect(self.__delegate, self)
            NionLib.PyListWidget_setItemDelegate(self.widget, self.__delegate)
    on_paint = property(__get_on_paint, __set_on_paint)

    # this message comes from the styled item delegate
    def paint(self, dc, options):
        if self.__on_paint:
            drawing_context = QtDrawingContext()
            self.__on_paint(drawing_context, options)
            NionLib.DrawingContext_drawCommands(dc, drawing_context.commands)


class QtOutputWidget(QtWidget):

    def __init__(self, properties):
        super(QtOutputWidget, self).__init__("output", properties)

    def send(self, message):
        NionLib.Output_out(self.widget, message)


class QtConsoleWidget(QtWidget):

    def __init__(self, properties):
        super(QtConsoleWidget, self).__init__("console", properties)
        self.on_interpret_command = None
        NionLib.Console_setDelegate(self.widget, self)

    def interpretCommand(self, command):
        if self.on_interpret_command:
            return self.on_interpret_command(command)
        return "", 0, "?"


class QtDocumentWindow(object):

    def __init__(self, native_document_window):
        self.native_document_window = native_document_window
        self.root_widget = None
        self.has_event_loop = True

    def attach(self, root_widget):
        self.root_widget = root_widget
        NionLib.DocumentWindow_setCentralWidget(self.native_document_window, self.root_widget.widget)

    def get_file_paths_dialog(self, title, directory, filter):
        return NionLib.DocumentWindow_getFilePath(self.native_document_window, "loadmany", title, directory, filter)

    def get_save_file_path(self, title, directory, filter):
        return NionLib.DocumentWindow_getFilePath(self.native_document_window, "save", title, directory, filter)

    def create_dock_widget(self, widget, panel_id, title, positions, position):
        return QtDockWidget(self, widget, panel_id, title, positions, position)

    def tabify_dock_widgets(self, dock_widget1, dock_widget2):
        NionLib.DocumentWindow_tabifyDockWidgets(self.native_document_window, dock_widget1.native_dock_widget, dock_widget2.native_dock_widget)


class QtDockWidget(object):

    def __init__(self, document_window, widget, panel_id, title, positions, position):
        self.document_window = document_window
        self.native_dock_widget = NionLib.DocumentWindow_addDockWidget(self.document_window.native_document_window, widget.widget, panel_id, title, positions, position)

    def close(self):
        NionLib.Widget_removeDockWidget(self.document_window.native_document_window, self.native_dock_widget)


class QtAction(object):

    def __init__(self, action_id, title):
        self.action_id = action_id
        self.title = title
        self._qt_action = None
        self.qt_action_manager = None
        self.key_sequence = None

    def create(self):
        pass

    def __get_qt_action(self):
        self.create()
        return self._qt_action
    qt_action = property(__get_qt_action)

    def configure(self):
        if self.key_sequence:
            NionLib.Actions_setShortcut(self.qt_action_manager, self.action_id, self.key_sequence)


class QtApplicationAction(QtAction):

    def __init__(self, action_id, title, callback):
        super(QtApplicationAction, self).__init__(action_id, title)
        self.callback = callback

    def create(self):
        if self._qt_action is None:
            self._qt_action = NionLib.Actions_createApplicationAction(self.qt_action_manager, self.action_id, self.title, True)

    def adjustApplicationAction(self):
        NionLib.Actions_enableAction(self.qt_action_manager, self.action_id)

    def adjustDocumentAction(self, document_controller):
        pass

    def execute(self):
        self.callback()


class QtDocumentAction(QtAction):

    def __init__(self, action_id, title, callback):
        super(QtDocumentAction, self).__init__(action_id, title)
        self.callback = callback

    def create(self):
        if self._qt_action is None:
            self._qt_action = NionLib.Actions_createApplicationAction(self.qt_action_manager, self.action_id, self.title, False)

    def adjustApplicationAction(self):
        pass

    def adjustDocumentAction(self, document_controller):
        NionLib.Actions_enableAction(self.qt_action_manager, self.action_id)

    def execute(self, document_controller):
        self.callback(document_controller)


class QtPanelAction(QtAction):

    def __init__(self, action_id, title, callback):
        super(QtPanelAction, self).__init__(action_id, title)
        self.callback = callback

    def create(self):
        if self._qt_action is None:
            self._qt_action = NionLib.Actions_createApplicationAction(self.qt_action_manager, self.action_id, self.title, False)

    def adjustApplicationAction(self):
        pass

    def adjustDocumentAction(self, document_controller):
        pass # NionLib.Actions_enableAction(qt_action_manager, self.action_id)

    def execute(self, document_controller):
        self.callback(document_controller.selected_image_panel)


class QtMenu(object):

    def __init__(self, menu_id, title):
        self.menu_id = menu_id
        self.title = title
        self.qt_action_manager = None
        self.__qt_menu = None
        self.action_ids = []
        self.__action_map = {}
        self.__build_items = []  # used to delay building menus

    def __create(self):
        if self.__qt_menu is None:
            self.__qt_menu = NionLib.Actions_findMenu(self.qt_action_manager, self.menu_id)
            if not self.__qt_menu:
                self.__qt_menu = NionLib.Actions_createMenu(self.qt_action_manager, self.menu_id, self.title)

    def get_qt_menu(self):
        self.__create()
        return self.__qt_menu
    qt_menu = property(get_qt_menu)

    def createActions(self):
        for build_item in self.__build_items:
            insert_before_action_id = build_item["insert"] if "insert" in build_item else None
            if "action" in build_item:
                action = build_item["action"]
                action.qt_action_manager = self.qt_action_manager
                qt_action = action.qt_action  # need to set action.qt_action_manager before this call
                NionLib.Actions_insertAction(self.qt_action_manager, self.qt_menu, qt_action, insert_before_action_id)
                action.configure()
            else:
                NionLib.Actions_insertSeparator(self.qt_action_manager, self.qt_menu, insert_before_action_id)

    def insertAction(self, action, before_action_id):
        action_id = action.action_id
        assert action_id not in self.action_ids
        self.action_ids.append(action_id)
        self.__build_items.append({ "action": action, "insert": before_action_id })
        self.__action_map[action_id] = action
        if self.__qt_menu:
            action.qt_action_manager = self.qt_action_manager
            qt_action = action.qt_action  # need to set action.qt_action_manager before this call
            NionLib.Actions_insertAction(self.qt_action_manager, self.qt_menu, qt_action, before_action_id)

    def insertSeparator(self, before_action_id):
        self.__build_items.append({ "separator": True, "insert": before_action_id })
        if self.__qt_menu:
            action.qt_action_manager = self.qt_action_manager
            NionLib.Actions_insertSeparator(self.qt_action_manager, self.qt_menu, before_action_id)

    def adjustApplicationActions(self):
        for action_id in self.action_ids:
            action = self.__action_map[action_id]
            action.adjustApplicationAction()

    def adjustDocumentActions(self, document_controller):
        for action_id in self.action_ids:
            action = self.__action_map[action_id]
            action.adjustDocumentAction(document_controller)

    def findAction(self, action_id):
        return self.__action_map[action_id] if action_id in self.__action_map else None


class QtMenuManager(object):

    def __init__(self):
        self.menu_ids = []  # ordering of menus
        self.__menu_dicts = {}  # map from id to menu dict
        self.qt_menu_bar = None
        self.qt_action_manager = None

    def createMenus(self, qt_menu_bar, qt_action_manager):
        self.qt_menu_bar = qt_menu_bar
        self.qt_action_manager = qt_action_manager
        for menu_id in self.menu_ids:
            menu_dict = self.__menu_dicts[menu_id]
            menu = menu_dict["menu"]
            menu.qt_action_manager = self.qt_action_manager
            qt_menu = menu.qt_menu  # need to set menu.qt_action_manager before this call
            insert_before_id = menu_dict["insert"]
            NionLib.Actions_insertMenu(self.qt_action_manager, self.qt_menu_bar, qt_menu, insert_before_id)
            menu.createActions()

    # Menu will be inserted immediately if menu_bar is not None.
    # Otherwise, menu will be inserted when createMenus is called.
    def insert_menu(self, menu_id, title, before_menu_id, use_existing=True):
        assert use_existing or menu_id not in self.menu_ids
        if not use_existing or menu_id not in self.menu_ids:
            menu = QtMenu(menu_id, title)
            self.menu_ids.append(menu_id)
            self.__menu_dicts[menu_id] = { "menu": menu, "insert": before_menu_id }
            if self.qt_menu_bar and self.qt_action_manager:
                menu.qt_action_manager = self.qt_action_manager
                qt_menu = menu.qt_menu  # need to set menu.qt_action_manager before this call
                NionLib.Actions_insertMenu(self.qt_action_manager, self.qt_menu_bar, qt_menu, before_menu_id)
                menu.createActions()

    def add_menu(self, menu_id, title):
        self.insert_menu(menu_id, title, None)

    def insert_separator(self, menu_id, before_action_id):
        assert menu_id in self.__menu_dicts
        menu_dict = self.__menu_dicts[menu_id]
        menu = menu_dict["menu"]
        assert menu is not None
        menu.insertSeparator(before_action_id)

    def insert_action(self, menu_id, action, before_action_id):
        assert menu_id in self.__menu_dicts
        menu_dict = self.__menu_dicts[menu_id]
        menu = menu_dict["menu"]
        assert menu is not None
        menu.insertAction(action, before_action_id)

    def insert_application_action(self, menu_id, action_id, before_action_id, title, callback, key_sequence=None):
        action = self.findAction(action_id)
        assert action is None, "action already exists"
        action = QtApplicationAction(action_id, title, callback)
        action.key_sequence = key_sequence
        self.insert_action(menu_id, action, before_action_id)

    def insert_document_action(self, menu_id, action_id, before_action_id, title, callback, key_sequence=None, replace_existing=False):
        action = self.findAction(action_id)
        assert action is None, "action already exists"
        action = QtDocumentAction(action_id, title, callback)
        action.key_sequence = key_sequence
        self.insert_action(menu_id, action, before_action_id)

    def add_action(self, menu_id, action):
        assert not self.findAction(action.action_id)
        self.insert_action(menu_id, action, None)

    def add_application_action(self, menu_id, action_id, title, callback, key_sequence=None, replace_existing=False):
        action = self.findAction(action_id)
        assert replace_existing or (action is None), "action already exists"
        if replace_existing and action:
            action.title = title
            action.callback = callback
        else:
            action = QtApplicationAction(action_id, title, callback)
            action.key_sequence = key_sequence
            self.add_action(menu_id, action)

    def add_document_action(self, menu_id, action_id, title, callback, key_sequence=None, replace_existing=False):
        action = self.findAction(action_id)
        assert replace_existing or (action is None), "action already exists"
        if replace_existing and action:
            action.title = title
            action.callback = callback
        else:
            action = QtDocumentAction(action_id, title, callback)
            action.key_sequence = key_sequence
            self.add_action(menu_id, action)

    def add_panel_action(self, menu_id, action_id, title, callback, key_sequence=None, replace_existing=False):
        action = self.findAction(action_id)
        assert replace_existing or (action is None), "action already exists"
        if replace_existing and action:
            action.title = title
            action.callback = callback
        else:
            action = QtPanelAction(action_id, title, callback)
            action.key_sequence = key_sequence
            self.add_action(menu_id, action)

    def adjustApplicationActions(self):
        for menu_id in self.menu_ids:
            menu_dict = self.__menu_dicts[menu_id]
            menu = menu_dict["menu"]
            menu.adjustApplicationActions()

    def adjustDocumentActions(self, document_controller):
        for menu_id in self.menu_ids:
            menu_dict = self.__menu_dicts[menu_id]
            menu = menu_dict["menu"]
            menu.adjustDocumentActions(document_controller)

    # search through each menu and look for a matching action
    def findAction(self, action_id):
        for menu_id in self.menu_ids:
            menu_dict = self.__menu_dicts[menu_id]
            menu = menu_dict["menu"]
            action = menu.findAction(action_id)
            if action:
                return action
        return None

    def dispatchApplicationAction(self, action_id):
        action = self.findAction(action_id)
        if action:
            action.execute()

    def dispatchDocumentAction(self, document_controller, action_id):
        action = self.findAction(action_id)
        if action:
            action.execute(document_controller)


class QtUserInterface(object):

    # data objects

    def create_mime_data(self):
        return QtMimeData()

    def create_item_model_controller(self, keys):
        return QtItemModelController(keys)

    def create_list_model_controller(self, keys):
        return QtListModelController(keys)

    # window elements

    def create_document_window(self, native_document_window):
        return QtDocumentWindow(native_document_window)

    # user interface elements

    def create_row_widget(self, properties=None):
        return QtRowWidget(properties)

    def create_column_widget(self, properties=None):
        return QtColumnWidget(properties)

    def create_splitter_widget(self, properties=None):
        return QtSplitterWidget(properties)

    def create_tab_widget(self, properties=None):
        return QtTabWidget(properties)

    def create_combo_box_widget(self, items=None, properties=None):
        return QtComboBoxWidget(items, properties)

    def create_push_button_widget(self, text=None, properties=None):
        return QtPushButtonWidget(text, properties)

    def create_label_widget(self, text=None, properties=None):
        return QtLabelWidget(text, properties)

    def create_slider_widget(self, properties=None):
        return QtSliderWidget(properties)

    def create_line_edit_widget(self, properties=None):
        return QtLineEditWidget(properties)

    def create_canvas_widget(self, properties=None):
        return QtCanvasWidget(properties)

    def create_tree_widget(self, properties=None):
        return QtTreeWidget(properties)

    def create_list_widget(self, properties=None):
        return QtListWidget(properties)

    def create_output_widget(self, properties=None):
        return QtOutputWidget(properties)

    def create_console_widget(self, properties=None):
        return QtConsoleWidget(properties)

    # file i/o

    def load_rgba_data_from_file(self, filename):
        return NionLib.readImageToPyArray(filename)

    # persistence (associated with application)

    def get_data_location(self):
        return NionLib.Core_getLocation("data")

    def get_persistent_string(self, key, default_value=None):
        value = NionLib.Settings_getString(key)
        return value if value else default_value

    def set_persistent_string(self, key, value):
        NionLib.Settings_setString(key, value)

    # menus

    def create_menu_manager(self):
        return QtMenuManager()
