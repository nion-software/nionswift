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
    def __init__(self, ui, mime_data):
        self.ui = ui
        self.raw_mime_data = mime_data
    def __get_formats(self):
        return self.ui.MimeData_formats(self.raw_mime_data)
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
            file_path = self.ui.Core_URLToPath(url)
            if file_path and len(file_path) > 0 and os.path.isfile(file_path) and os.path.exists(file_path):
                file_paths.append(file_path)
        return file_paths
    file_paths = property(__get_file_paths)
    def data_as_string(self, format):
        return self.ui.MimeData_dataAsString(self.raw_mime_data, format)
    def set_data_as_string(self, format, text):
        self.ui.MimeData_setDataAsString(self.raw_mime_data, format, text)


class ItemModel(object):

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
        def removeAllChildren(self):
            self.children = []
        def appendChild(self, item):
            item.parent = self
            self.children.append(item)
        def insertChild(self, before_index, item):
            item.parent = self
            self.children.insert(before_index, item)
        def removeChild(self, item):
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

    def __init__(self, document_controller, keys):
        self.__document_controller_weakref = weakref.ref(document_controller)
        self.__keys = keys
        self.py_item_model = self.ui.PyItemModel_create(self, ["index"] + keys)
        self.__next_id = 0
        self.root = self.createItem()

    def __get_document_controller(self):
        return self.__document_controller_weakref()
    document_controller = property(__get_document_controller)

    def __get_ui(self):
        return self.document_controller.ui
    ui = property(__get_ui)

    def close(self):
        self.ui.PyItemModel_destroy(self.py_item_model)

    def createItem(self, data=None):
        item = ItemModel.Item(data)
        item.id = self.__next_id
        self.__next_id = self.__next_id + 1
        return item

    def itemFromId(self, item_id, parent=None):
        item = []  # nonlocal in Python 3.1+
        def fn(parent, index, child):
            if child.id == item_id:
                item.append(child)
                return True
        self.traverse(fn)
        return item[0] if item else None

    def itemCount(self, parent_id):
        parent = self.itemFromId(parent_id)
        assert parent is not None
        return len(parent.children)

    # itemId returns the id of the item within the parent
    def itemId(self, index, parent_id):
        parent = self.itemFromId(parent_id)
        assert parent is not None
        if index >= 0 and index < len(parent.children):
            return parent.children[index].id
        return 0  # invalid id

    def itemParent(self, index, item_id):
        if item_id == 0:
            return [-1, 0]
        child = self.itemFromId(item_id)
        parent = child.parent
        if parent == self.root:
            return [-1, 0]
        return [parent.row, parent.id]

    def itemValue(self, role, index, item_id):
        child = self.itemFromId(item_id)
        if role == "index":
            return index
        if role in child.data:
            return child.data[role]
        return None

    def itemKeyPress(self, index, parent_row, parent_id, text, raw_modifiers):
        if hasattr(self, "item_key_press"):
            return self.item_key_press(text, QtKeyboardModifiers(raw_modifiers), index, parent_row, parent_id)
        return False

    def itemSetData(self, index, parent_row, parent_id, data):
        if hasattr(self, "item_set_data"):
            return self.item_set_data(data, index, parent_row, parent_id)
        return False

    def itemChanged(self, index, parent_row, parent_id):
        if hasattr(self, "item_changed"):
            self.item_changed(index, parent_row, parent_id)

    def itemClicked(self, index, parent_row, parent_id):
        if hasattr(self, "item_clicked"):
            return self.item_clicked(index, parent_row, parent_id)
        return False

    def itemDoubleClicked(self, index, parent_row, parent_id):
        if hasattr(self, "item_double_clicked"):
            return self.item_double_clicked(index, parent_row, parent_id)
        return False

    def itemDropMimeData(self, raw_mime_data, action, row, parent_row, parent_id):
        if hasattr(self, "item_drop_mime_data"):
            return self.item_drop_mime_data(QtMimeData(self.ui, raw_mime_data), action, row, parent_row, parent_id)
        return False

    def itemMimeData(self, row, parent_row, parent_id):
        if hasattr(self, "item_mime_data"):
            mime_data = self.item_mime_data(row, parent_row, parent_id)
            return mime_data.raw_mime_data if mime_data else None
        return None

    def removeRows(self, row, count, parent_row, parent_id):
        if hasattr(self, "remove_rows"):
            return self.remove_rows(row, count, parent_row, parent_id)
        return False

    def supportedDropActions(self):
        if hasattr(self, "supported_drop_actions"):
            return self.supported_drop_actions
        return 0

    def mimeTypesForDrop(self):
        if hasattr(self, "mime_types_for_drop"):
            return self.mime_types_for_drop
        return []


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

    def beginInsert(self, first_row, last_row, parent_row, parent_id):
        self.ui.PyItemModel_beginInsertRows(self.py_item_model, first_row, last_row, parent_row, parent_id)

    def endInsert(self):
        self.ui.PyItemModel_endInsertRow(self.py_item_model)

    def beginRemove(self, first_row, last_row, parent_row, parent_id):
        self.ui.PyItemModel_beginRemoveRows(self.py_item_model, first_row, last_row, parent_row, parent_id)

    def endRemove(self):
        self.ui.PyItemModel_endRemoveRow(self.py_item_model)

    def dataChanged(self, row, parent_row, parent_id):
        self.ui.PyItemModel_dataChanged(self.py_item_model, row, parent_row, parent_id)


class ListModel(object):

    NONE = 0
    COPY = 1
    MOVE = 2
    LINK = 4

    DRAG = 1
    DROP = 2

    def __init__(self, ui, keys):
        self.ui = ui
        self.__keys = keys
        self.py_list_model = self.ui.PyListModel_create(self, ["index"] + keys)
        self.model = []
    def close(self):
        self.ui.PyListModel_destroy(self.py_list_model)
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
    def replaceModel(self, values):
        self.model = values
        self.ui.PyListModel_dataChanged(self.py_list_model)
    def beginInsert(self, first_row, last_row):
        self.ui.PyListModel_beginInsertRows(self.py_list_model, first_row, last_row)
    def endInsert(self):
        self.ui.PyListModel_endInsertRow(self.py_list_model)
    def beginRemove(self, first_row, last_row):
        self.ui.PyListModel_beginRemoveRows(self.py_list_model, first_row, last_row)
    def endRemove(self):
        self.ui.PyListModel_endRemoveRow(self.py_list_model)
    def dataChanged(self):
        self.ui.PyListModel_dataChanged(self.py_list_model)
    def itemDropMimeData(self, raw_mime_data, action, row, parent_row):
        if hasattr(self, "item_drop_mime_data"):
            return self.item_drop_mime_data(QtMimeData(self.ui, raw_mime_data), action, row, parent_row)
        return False
    def itemMimeData(self, row):
        if hasattr(self, "item_mime_data"):
            mime_data = self.item_mime_data(row)
            return mime_data.raw_mime_data if mime_data else None
        return None
    def removeRows(self, row, count):
        if hasattr(self, "remove_rows"):
            return self.remove_rows(row, count)
        return False
    def supportedDropActions(self):
        if hasattr(self, "supported_drop_actions"):
            return self.supported_drop_actions
        return 0
    def mimeTypesForDrop(self):
        if hasattr(self, "mime_types_for_drop"):
            return self.mime_types_for_drop
        return []


class DrawingContext(object):
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
        if isinstance(a, DrawingContext.LinearGradient):
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
            self.js_var = "grad"+str(DrawingContext.LinearGradient.next)
            self.command_var = DrawingContext.LinearGradient.next
            self.js = "var {0} = ctx.createLinearGradient({1}, {2}, {3}, {4});".format(self.js_var, x, y, width, height)
            self.commands = []
            self.commands.append(("gradient", self.command_var, float(x), float(y), float(width), float(height)))
            DrawingContext.LinearGradient.next = DrawingContext.LinearGradient.next + 1
        def add_color_stop(self, x, color):
            self.weak_context().js += "{0}.addColorStop({1}, '{2}');".format(self.js_var, x, color)
            self.weak_context().commands.append(("colorStop", self.command_var, float(x), str(color)))
    def create_linear_gradient(self, x, y, width, height):
        gradient = DrawingContext.LinearGradient(self, x, y, width, height)
        self.js += gradient.js
        self.commands.extend(gradient.commands)
        return gradient


class QtWidget(object):
    def __init__(self, ui, widget_type, properties):
        self.ui = ui
        self.properties = properties if properties else {}
        self.widget = self.ui.Widget_loadIntrinsicWidget(widget_type) if widget_type else None
        self.update_properties()

    def update_properties(self):
        if self.widget:
            for key in self.properties.keys():
                self.ui.Widget_setWidgetProperty(self.widget, key, self.properties[key])


class QtBoxWidget(QtWidget):

    def __init__(self, ui, widget_type, properties):
        super(QtBoxWidget, self).__init__(ui, widget_type, properties)
        self.children = []

    def count(self):
        return len(self.children)

    def index(self, child):
        assert child in self.children
        return self.children.index(child)

    def insert(self, child, before):
        index = self.index(before) if before else self.count()
        self.children.insert(index, child)
        assert self.widget is not None
        assert child.widget is not None
        NionLib.Widget_insertWidget(self.widget, child.widget, index)

    def add(self, child):
        self.insert(child, None)

    def add_stretch(self):
        NionLib.Widget_addStretch(self.widget)


class QtRowWidget(QtBoxWidget):

    def __init__(self, ui, properties):
        super(QtRowWidget, self).__init__(ui, "row", properties)


class QtColumnWidget(QtBoxWidget):

    def __init__(self, ui, properties):
        super(QtColumnWidget, self).__init__(ui, "column", properties)


class QtSplitterWidget(QtWidget):

    def __init__(self, ui, properties):
        super(QtSplitterWidget, self).__init__(ui, "splitter", properties)
        NionLib.Widget_setWidgetProperty(self.widget, "stylesheet", "background-color: '#FFF'")

    def add(self, child):
        NionLib.Widget_addWidget(self.widget, child.widget)

    def restore_state(self, tag):
        NionLib.Splitter_restoreState(self.widget, tag)

    def save_state(self, tag):
        NionLib.Splitter_saveState(self.widget, tag)


class QtComboBoxWidget(QtWidget):

    def __init__(self, ui, items, properties):
        super(QtComboBoxWidget, self).__init__(ui, "combobox", properties)
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

    def __init__(self, ui, text, properties):
        super(QtPushButtonWidget, self).__init__(ui, "pushbutton", properties)
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

    def __init__(self, ui, text, properties):
        super(QtLabelWidget, self).__init__(ui, "label", properties)
        self.__text = None
        self.text = text

    def __get_text(self):
        return self.__text
    def __set_text(self, text):
        self.__text = text if text else ""
        NionLib.Label_setText(self.widget, self.__text)
    text = property(__get_text, __set_text)


class QtSliderWidget(QtWidget):

    def __init__(self, ui, properties):
        super(QtSliderWidget, self).__init__(ui, "slider", properties)
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


class QtCanvasWidget(QtWidget):

    # TODO: get rid of document_controller usage here
    def __init__(self, ui, properties):
        super(QtCanvasWidget, self).__init__(ui, "canvas", properties)
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
        # load the Qml and associate it with this panel.
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

    def __get_focused(self):
        return NionLib.Canvas_hasFocus(self.widget)
    def __set_focused(self, focused):
        if focused != self.focused:
            if focused:
                NionLib.Canvas_setFocus(self.widget, 7)
            else:
                NionLib.Canvas_clearFocus(self.widget)
    focused = property(__get_focused, __set_focused)

    class Layer(object):
        def __init__(self, canvas):
            self.__weak_canvas = weakref.ref(canvas)
            self.__drawing_context = DrawingContext()

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

    def __init__(self, ui, properties):
        super(QtTreeWidget, self).__init__(ui, "pytree", properties)
        NionLib.Widget_setWidgetProperty(self.widget, "stylesheet", "* { border: none; background-color: '#EEEEEE'; } PyTreeWidget { margin-top: 4px }")
        NionLib.PyTreeWidget_connect(self.widget, self)
        self.__model = None

    def __get_model(self):
        return self.__model
    def __set_model(self, model):
        self.__model = model
        NionLib.PyTreeWidget_setModel(self.widget, model.py_item_model)
    model = property(__get_model, __set_model)

    def treeItemKeyPress(self, index, parent_row, parent_id, text, raw_modifiers):
        return self.model.itemKeyPress(index, parent_row, parent_id, text, raw_modifiers)

    def treeItemChanged(self, index, parent_row, parent_id):
        self.model.itemChanged(index, parent_row, parent_id)

    def treeItemClicked(self, index, parent_row, parent_id):
        return self.model.itemClicked(index, parent_row, parent_id)

    def treeItemDoubleClicked(self, index, parent_row, parent_id):
        return self.model.itemDoubleClicked(index, parent_row, parent_id)

    def set_current_row(self, index, parent_row, parent_id):
        NionLib.PyTreeWidget_setCurrentRow(self.widget, index, parent_row, parent_id)


class QtListWidget(QtWidget):

    def __init__(self, ui, properties):
        super(QtListWidget, self).__init__(ui, "pylist", properties)
        NionLib.Widget_setWidgetProperty(self.widget, "stylesheet", "* { border: none; background-color: '#EEEEEE'; } PyListWidget { margin-top: 4px }")
        NionLib.PyListWidget_connect(self.widget, self)
        self.__model = None
        self.__on_paint = None
        self.__delegate = None

    def __get_model(self):
        return self.__model
    def __set_model(self, model):
        self.__model = model
        NionLib.PyListWidget_setModel(self.widget, model.py_list_model)
    model = property(__get_model, __set_model)

    def listItemKeyPress(self, index, text, raw_modifiers):
        return self.model.itemKeyPress(index, text, raw_modifiers)

    def listItemChanged(self, index):
        self.model.itemChanged(index)

    def listItemClicked(self, index):
        return self.model.itemClicked(index)

    def listItemDoubleClicked(self, index):
        return self.model.itemDoubleClicked(index)

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
            self.__on_paint(dc, options)


class QtUserInterface(object):

    # Higher level UI objects

    def create_mime_data(self):
        return QtMimeData(self, self.MimeData_create())

    def create_row_widget(self, properties=None):
        return QtRowWidget(self, properties)

    def create_column_widget(self, properties=None):
        return QtColumnWidget(self, properties)

    def create_splitter_widget(self, properties=None):
        return QtSplitterWidget(self, properties)

    def create_combo_box_widget(self, items=None, properties=None):
        return QtComboBoxWidget(self, items, properties)

    def create_push_button_widget(self, text=None, properties=None):
        return QtPushButtonWidget(self, text, properties)

    def create_label_widget(self, text=None, properties=None):
        return QtLabelWidget(self, text, properties)

    def create_slider_widget(self, properties=None):
        return QtSliderWidget(self, properties)

    def create_canvas_widget(self, properties=None):
        return QtCanvasWidget(self, properties)

    def create_tree_widget(self, properties=None):
        return QtTreeWidget(self, properties)

    def create_list_widget(self, properties=None):
        return QtListWidget(self, properties)

    def load_rgba_data_from_file(self, filename):
        return NionLib.readImageToPyArray(filename)

    # Actions sub-module for menus and actions

    def Actions_createApplicationAction(self, qt_action_manager, action_id, title, is_application):
        return NionLib.Actions_createApplicationAction(qt_action_manager, action_id, title, is_application)

    def Actions_createMenu(self, qt_action_manager, menu_id, title):
        return NionLib.Actions_createMenu(qt_action_manager, menu_id, title)

    def Actions_enableAction(self, qt_action_manager, action_id):
        NionLib.Actions_enableAction(qt_action_manager, action_id)

    def Actions_findAction(self, qt_action_manager, action_id):
        return NionLib.Actions_findAction(qt_action_manager, action_id)

    def Actions_findMenu(self, qt_action_manager, menu_id):
        return NionLib.Actions_findMenu(qt_action_manager, menu_id)

    def Actions_insertAction(self, qt_action_manager, qt_menu, qt_action, insert_before_action_id):
        NionLib.Actions_insertAction(qt_action_manager, qt_menu, qt_action, insert_before_action_id)

    def Actions_insertSeparator(self, qt_action_manager, qt_menu, insert_before_action_id):
        NionLib.Actions_insertSeparator(qt_action_manager, qt_menu, insert_before_action_id)

    def Actions_insertMenu(self, action_manager, qt_menu_bar, qt_menu, insert_before_id):
        NionLib.Actions_insertMenu(action_manager, qt_menu_bar, qt_menu, insert_before_id)

    def Actions_setShortcut(self, qt_action_manager, action_id, key_sequence):
        NionLib.Actions_setShortcut(qt_action_manager, action_id, key_sequence)

    # Output and miscellaneous

    def Console_setDelegate(self, widget, delegate):
        NionLib.Console_setDelegate(widget, delegate)

    def Core_out(self, str):
        return NionLib.Core_out(str)

    def Core_pathToURL(self, path):
        return NionLib.Core_pathToURL(path)

    def Core_URLToPath(self, url):
        return NionLib.Core_URLToPath(url)

    def Core_getLocation(self, location):
        return NionLib.Core_getLocation(location)

    def Output_out(self, widget, message):
        NionLib.Output_out(widget, message)

    # General document window commands

    def DocumentWindow_addDockWidget(self, document_window, widget, identifier, title, positions, position):
        return NionLib.DocumentWindow_addDockWidget(document_window, widget, identifier, title, positions, position)

    def DocumentWindow_loadQmlWidget(self, document_window, filename, panel, context_properties):
        return NionLib.DocumentWindow_loadQmlWidget(document_window, filename, panel, context_properties)

    def DocumentWindow_registerThumbnailProvider(self, document_window, uuid_str, data_item):
        NionLib.DocumentWindow_registerThumbnailProvider(document_window, uuid_str, data_item)

    def DocumentWindow_setCentralWidget(self, document_window, widget):
        NionLib.DocumentWindow_setCentralWidget(document_window, widget)

    def DocumentWindow_tabifyDockWidgets(self, document_controller, widget1, widget2):
        NionLib.DocumentWindow_tabifyDockWidgets(document_controller, widget1, widget2)

    def DocumentWindow_unregisterThumbnailProvider(self, document_window, uuid_str):
        NionLib.DocumentWindow_unregisterThumbnailProvider(document_window, uuid_str)

    # Opens a file dialog. mode should be one of 'load', 'save' or 'loadmany'.
    def DocumentWindow_getFilePath(self, document_window, mode, caption, dir, filter):
        return NionLib.DocumentWindow_getFilePath(document_window, mode, caption, dir, filter)

    # Send images to an image display

    def ImageDisplayController_sendImage(self, controller_id, rgba_image):
        return NionLib.ImageDisplayController_sendImage(NionLib.idc, controller_id, rgba_image)

    # Mime data

    def MimeData_create(self):
        return NionLib.MimeData_create()

    def MimeData_formats(self, mime_data):
        return NionLib.MimeData_formats(mime_data)

    def MimeData_dataAsString(self, mime_data, format):
        return NionLib.MimeData_dataAsString(mime_data, format)

    def MimeData_setDataAsString(self, mime_data, format, text):
        return NionLib.MimeData_setDataAsString(mime_data, format, text)

    # PyControl is used to manage a parameter for an operation

    def PyControl_connect(self, widget, object, property):
        NionLib.PyControl_connect(widget, object, property)

    def PyControl_setFloatValue(self, widget, value):
        NionLib.PyControl_setFloatValue(widget, value)

    def PyControl_setIntegerValue(self, widget, value):
        NionLib.PyControl_setIntegerValue(widget, value)

    def PyControl_setStringValue(self, widget, value):
        NionLib.PyControl_setStringValue(widget, value)

    def PyControl_setTitle(self, widget, title):
        NionLib.PyControl_setTitle(widget, title)

    # PyItemModel is a tree model

    def PyItemModel_beginInsertRows(self, py_item_model, first_row, last_row, parent_row, parent_id):
        NionLib.PyItemModel_beginInsertRows(py_item_model, first_row, last_row, parent_row, parent_id)

    def PyItemModel_beginRemoveRows(self, py_item_model, first_row, last_row, parent_row, parent_id):
        NionLib.PyItemModel_beginRemoveRows(py_item_model, first_row, last_row, parent_row, parent_id)

    def PyItemModel_create(self, delegate, keys):
        return NionLib.PyItemModel_create(delegate, keys)

    def PyItemModel_dataChanged(self, py_item_model, row, parent_row, parent_id):
        NionLib.PyItemModel_dataChanged(py_item_model, row, parent_row, parent_id)

    def PyItemModel_destroy(self, py_item_model):
        NionLib.PyItemModel_destroy(py_item_model)

    def PyItemModel_endInsertRow(self, py_item_model):
        NionLib.PyItemModel_endInsertRow(py_item_model)

    def PyItemModel_endRemoveRow(self, py_item_model):
        NionLib.PyItemModel_endRemoveRow(py_item_model)

    # PyListModel is a list model

    def PyListModel_beginInsertRows(self, py_item_model, first_row, last_row):
        NionLib.PyListModel_beginInsertRows(py_item_model, first_row, last_row)

    def PyListModel_beginRemoveRows(self, py_item_model, first_row, last_row):
        NionLib.PyListModel_beginRemoveRows(py_item_model, first_row, last_row)

    def PyListModel_create(self, delegate, keys):
        return NionLib.PyListModel_create(delegate, keys)

    def PyListModel_dataChanged(self, py_item_model):
        NionLib.PyListModel_dataChanged(py_item_model)

    def PyListModel_destroy(self, py_item_model):
        NionLib.PyListModel_destroy(py_item_model)

    def PyListModel_endInsertRow(self, py_item_model):
        NionLib.PyListModel_endInsertRow(py_item_model)

    def PyListModel_endRemoveRow(self, py_item_model):
        NionLib.PyListModel_endRemoveRow(py_item_model)

    # PyListWidget

    def PyListWidget_getCurrentRow(self, widget):
        return NionLib.PyListWidget_getCurrentRow(widget)

    def PyListWidget_setCurrentRow(self, widget, index):
        NionLib.PyListWidget_setCurrentRow(widget, index)

    def PyListWidget_setModel(self, widget, py_list_model):
        NionLib.PyListWidget_setModel(widget, py_list_model)

    # PyStack/PyStackGroup for presenting operations

    def PyStack_content(self, widget):
        return NionLib.PyStack_content(widget)

    def PyStackGroup_connect(self, stack_group_widget, delegate, enabled_method, add_method, remove_method):
        NionLib.PyStackGroup_connect(stack_group_widget, delegate, enabled_method, add_method, remove_method)

    def PyStackGroup_content(self, stack_group_widget):
        return NionLib.PyStackGroup_content(stack_group_widget)

    def PyStackGroup_setEnabled(self, stack_group_widget, enabled):
        NionLib.PyStackGroup_setEnabled(stack_group_widget, enabled)

    def PyStackGroup_setTitle(self, stack_group_widget, title):
        NionLib.PyStackGroup_setTitle(stack_group_widget, title)

    # PyTreeWidget to view a PyItemModel

    def PyTreeWidget_setCurrentRow(self, widget, index, parent_row, parent_id):
        NionLib.PyTreeWidget_setCurrentRow(widget, index, parent_row, parent_id)

    def PyTreeWidget_setModel(self, widget, py_item_model):
        NionLib.PyTreeWidget_setModel(widget, py_item_model)

    # Settings

    def Settings_setString(self, key, value):
        NionLib.Settings_setString(key, value)

    def Settings_getString(self, key):
        return NionLib.Settings_getString(key)

    # Splitter

    def Splitter_restoreState(self, splitter, identifier):
        NionLib.Splitter_restoreState(splitter, identifier)

    def Splitter_saveState(self, splitter, identifier):
        NionLib.Splitter_saveState(splitter, identifier)

    # TabWidget to present tabs

    def TabWidget_addTab(self, tab_widget, widget, tab_label):
        NionLib.TabWidget_addTab(tab_widget, widget, tab_label)

    # General Widget methods

    def Widget_addOverlay(self, widget, overlay):
        NionLib.Widget_addOverlay(widget, overlay)

    def Widget_addSpacing(self, container, spacing):
        NionLib.Widget_addSpacing(container, spacing)

    def Widget_addStretch(self, container):
        NionLib.Widget_addStretch(container)

    def Widget_addWidget(self, widget, child_widget):
        NionLib.Widget_addWidget(widget, child_widget)

    def Widget_adjustSize(self, widget):
        NionLib.Widget_adjustSize(widget)

    def Widget_getWidgetProperty(self, widget, property):
        return NionLib.Widget_getWidgetProperty(widget, property)

    def Widget_insertWidget(self, widget, child_widget, index):
        NionLib.Widget_insertWidget(widget, child_widget, index)

    def Widget_loadIntrinsicWidget(self, type):
        return NionLib.Widget_loadIntrinsicWidget(type)

    def Widget_removeAll(self, container):
        NionLib.Widget_removeAll(container)

    def Widget_removeDockWidget(self, document_controller, dock_widget):
        NionLib.Widget_removeDockWidget(document_controller, dock_widget)

    def Widget_removeWidget(self, widget):
        NionLib.Widget_removeWidget(widget)

    def Widget_setContextProperty(self, widget, property, value):
        NionLib.Widget_setContextProperty(widget, property, value)

    def Widget_setWidgetProperty(self, widget, key, value):
        NionLib.Widget_setWidgetProperty(widget, key, value)
