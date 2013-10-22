# standard libraries
import logging
import numbers
import os
import weakref

# third party libraries
# none

# local libraries
# none


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


class QtKey(object):
    def __init__(self, text, key, raw_modifiers):
        self.text = text
        self.key = key
        self.modifiers = QtKeyboardModifiers(raw_modifiers)

    def __get_is_delete(self):
        return len(self.text) == 1 and (ord(self.text[0]) == 127 or ord(self.text[0]) == 8)
    is_delete = property(__get_is_delete)


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
            if file_path and len(file_path) > 0 and os.path.isfile(file_path) and os.path.exists(file_path):
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
        self.py_item_model = self.proxy.PyItemModel_create(["index"] + keys)
        self.proxy.PyItemModel_connect(self.py_item_model, self)
        self.__next_id = 0
        self.root = self.create_item()
        self.on_item_set_data = None
        self.on_item_drop_mime_data = None
        self.on_item_mime_data = None
        self.on_remove_rows = None
        self.supported_drop_actions = 0
        self.mime_types_for_drop = []

    def close(self):
        self.proxy.PyItemModel_destroy(self.py_item_model)

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
        self.proxy.PyItemModel_beginInsertRows(self.py_item_model, first_row, last_row, parent_row, parent_id)

    def end_insert(self):
        self.proxy.PyItemModel_endInsertRow(self.py_item_model)

    def begin_remove(self, first_row, last_row, parent_row, parent_id):
        self.proxy.PyItemModel_beginRemoveRows(self.py_item_model, first_row, last_row, parent_row, parent_id)

    def end_remove(self):
        self.proxy.PyItemModel_endRemoveRow(self.py_item_model)

    def data_changed(self, row, parent_row, parent_id):
        self.proxy.PyItemModel_dataChanged(self.py_item_model, row, parent_row, parent_id)


# pobj
class QtListModelController(object):

    NONE = 0
    COPY = 1
    MOVE = 2
    LINK = 4

    DRAG = 1
    DROP = 2

    def __init__(self, proxy, keys):
        self.proxy = proxy
        self.py_list_model = self.proxy.PyListModel_create(["index"] + keys)
        self.proxy.PyListModel_connect(self.py_list_model, self)
        self.model = []
        self.on_item_drop_mime_data = None
        self.on_item_mime_data = None
        self.on_remove_rows = None
        self.supported_drop_actions = 0
        self.mime_types_for_drop = []
    def close(self):
        self.proxy.PyListModel_destroy(self.py_list_model)
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
        self.proxy.PyListModel_beginInsertRows(self.py_list_model, first_row, last_row)
    def end_insert(self):
        self.proxy.PyListModel_endInsertRow(self.py_list_model)
    def begin_remove(self, first_row, last_row):
        self.proxy.PyListModel_beginRemoveRows(self.py_list_model, first_row, last_row)
    def end_remove(self):
        self.proxy.PyListModel_endRemoveRow(self.py_list_model)
    def data_changed(self):
        self.proxy.PyListModel_dataChanged(self.py_list_model)


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
    def begin_path(self):
        self.js += "ctx.beginPath();"
        self.commands.append(("beginPath", ))
    def close_path(self):
        self.js += "ctx.closePath();"
        self.commands.append(("closePath", ))
    def translate(self, x, y):
        self.js += "ctx.translate({0}, {1});".format(x, y)
        self.commands.append(("translate", float(x), float(y)))
    def scale(self, x, y):
        self.js += "ctx.scale({0}, {1});".format(x, y)
        self.commands.append(("scale", float(x), float(y)))
    def move_to(self, x, y):
        self.js += "ctx.moveTo({0}, {1});".format(x, y)
        self.commands.append(("moveTo", float(x), float(y)))
    def line_to(self, x, y):
        self.js += "ctx.lineTo({0}, {1});".format(x, y)
        self.commands.append(("lineTo", float(x), float(y)))
    def rect(self, a, b, c, d):
        self.js += "ctx.rect({0}, {1}, {2}, {3});".format(a, b, c, d)
        self.commands.append(("rect", float(a), float(b), float(c), float(d)))
    def arc(self, a, b, c, d, e, f):
        self.js += "ctx.arc({0}, {1}, {2}, {3}, {4}, {5});".format(a, b, c, d, e, "true" if f else "false")
        self.commands.append(("arc", float(a), float(b), float(c), float(d), float(e), bool(f)))
    def draw_image(self, img, a, b, c, d):
        self.js += "ctx.rect({0}, {1}, {2}, {3});".format(a, b, c, d)
        assert str(img.dtype) == 'uint32'
        self.commands.append(("image", img, float(a), float(b), float(c), float(d)))
    def stroke(self):
        self.js += "ctx.stroke();"
        self.commands.append(("stroke", ))
    def sleep(self, duration):
        self.commands.append(("sleep", duration))
    def fill(self):
        self.js += "ctx.fill();"
        self.commands.append(("fill", ))
    def fill_text(self, text, x, y, maxWidth=None):
        self.js += "ctx.fillText('{0}', {1}, {2}{3});".format(text.encode(errors='ignore'), x, y, ", {0}".format(maxWidth) if maxWidth else "")
        self.commands.append(("fillText", unicode(text), float(x), float(y), float(maxWidth) if maxWidth else None))
    def __get_fill_style(self):
        raise NotImplementedError()
    def __set_fill_style(self, a):
        if isinstance(a, QtDrawingContext.LinearGradient):
            self.js += "ctx.fillStyle = {0};".format(a.js_var)
            self.commands.append(("fillStyleGradient", int(a.command_var)))
        else:
            self.js += "ctx.fillStyle = '{0}';".format(a)
            self.commands.append(("fillStyle", str(a)))
    fill_style = property(__get_fill_style, __set_fill_style)
    def __get_font(self):
        raise NotImplementedError()
    def __set_font(self, a):
        self.js += "ctx.font = '{0}';".format(a)
        self.commands.append(("font", str(a)))
    font = property(__get_font, __set_font)
    def __get_text_align(self):
        raise NotImplementedError()
    def __set_text_align(self, a):
        self.js += "ctx.textAlign = '{0}';".format(a)
        self.commands.append(("textAlign", str(a)))
    text_align = property(__get_text_align, __set_text_align)
    def __get_text_baseline(self):
        raise NotImplementedError()
    def __set_text_baseline(self, a):
        self.js += "ctx.textBaseline = '{0}';".format(a)
        self.commands.append(("textBaseline", str(a)))
    text_baseline = property(__get_text_baseline, __set_text_baseline)
    def __get_stroke_style(self):
        raise NotImplementedError()
    def __set_stroke_style(self, a):
        self.js += "ctx.strokeStyle = '{0}';".format(a)
        self.commands.append(("strokeStyle", str(a)))
    stroke_style = property(__get_stroke_style, __set_stroke_style)
    def __get_line_width(self):
        raise NotImplementedError()
    def __set_line_width(self, a):
        self.js += "ctx.lineWidth = {0};".format(a)
        self.commands.append(("lineWidth", float(a)))
    line_width = property(__get_line_width, __set_line_width)
    def __get_line_cap(self):
        raise NotImplementedError()
    def __set_line_cap(self, a):
        self.js += "ctx.lineCap = '{0}';".format(a)
        self.commands.append(("lineCap", str(a)))
    line_cap = property(__get_line_cap, __set_line_cap)
    def __get_line_join(self):
        raise NotImplementedError()
    def __set_line_join(self, a):
        self.js += "ctx.lineJoin = '{0}';".format(a)
        self.commands.append(("lineJoin", str(a)))
    line_join = property(__get_line_join, __set_line_join)
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
    def __init__(self, proxy, widget_type, properties):
        self.proxy = proxy
        self.properties = properties if properties else {}
        self.widget = self.proxy.Widget_loadIntrinsicWidget(widget_type) if widget_type else None
        self.update_properties()

    # subclasses should override to clear their variable.
    # subclsases should NOT call Qt code to delete anything here... that is done by the Qt code
    def close(self):
        self.widget = None

    def update_properties(self):
        if self.widget:
            for key in self.properties.keys():
                self.proxy.Widget_setWidgetProperty(self.widget, key, self.properties[key])

    def __get_focused(self):
        return self.proxy.Widget_hasFocus(self.widget)
    def __set_focused(self, focused):
        if focused != self.focused:
            if focused:
                self.proxy.Widget_setFocus(self.widget, 7)
            else:
                self.proxy.Widget_clearFocus(self.widget)
    focused = property(__get_focused, __set_focused)

    def __get_size(self):
        raise NotImplementedError()
    def __set_size(self, size):
        self.proxy.Widget_setWidgetSize(self.widget, int(size[1]), int(size[0]))
    size = property(__get_size, __set_size)

    def add_overlay(self, overlay):
        self.proxy.Widget_addOverlay(self.widget, overlay.widget)


class QtBoxWidget(QtWidget):

    def __init__(self, proxy, widget_type, properties):
        super(QtBoxWidget, self).__init__(proxy, widget_type, properties)
        self.children = []

    def close(self):
        for child in self.children:
            child.close()

    def count(self):
        return len(self.children)

    def index(self, child):
        assert child in self.children
        return self.children.index(child)

    def insert(self, child, before, fill=False, alignment=None):
        if isinstance(before, numbers.Integral):
            index = before
        else:
            index = self.index(before) if before else self.count()
        self.children.insert(index, child)
        assert self.widget is not None
        assert child.widget is not None
        self.proxy.Widget_insertWidget(self.widget, child.widget, index, fill, alignment)

    def add(self, child, fill=False, alignment=None):
        self.insert(child, None, fill, alignment)

    def remove(self, child):
        self.children.remove(child)
        self.proxy.Widget_removeWidget(child.widget)
        child.close()

    def add_stretch(self):
        self.proxy.Widget_addStretch(self.widget)

    def add_spacing(self, spacing):
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

    def __get_orientation(self):
        return self.__orientation
    def __set_orientation(self, orientation):
        self.__orientation = orientation
        self.proxy.Splitter_setOrientation(self.widget, self.__orientation)
    orientation = property(__get_orientation, __set_orientation)

    def add(self, child):
        self.proxy.Widget_addWidget(self.widget, child.widget)
        self.children.append(child)

    def restore_state(self, tag):
        self.proxy.Splitter_restoreState(self.widget, tag)

    def save_state(self, tag):
        self.proxy.Splitter_saveState(self.widget, tag)


class QtTabWidget(QtWidget):

    def __init__(self, proxy, properties):
        super(QtTabWidget, self).__init__(proxy, "group", properties)
        self.proxy.Widget_setWidgetProperty(self.widget, "stylesheet", "background-color: '#FFF'")
        self.children = []

    def close(self):
        for child in self.children:
            child.close()

    def add(self, child, label):
        self.proxy.TabWidget_addTab(self.widget, child.widget, unicode(label))
        self.children.append(child)

    def restore_state(self, tag):
        pass

    def save_state(self, tag):
        pass


class QtStackWidget(QtWidget):

    def __init__(self, proxy, properties):
        super(QtStackWidget, self).__init__(proxy, "stack", properties)
        self.children = []
        self.__current_index = -1

    def close(self):
        for child in self.children:
            child.close()

    def add(self, child):
        self.proxy.StackWidget_addWidget(self.widget, child.widget)
        self.children.append(child)

    def restore_state(self, tag):
        pass

    def save_state(self, tag):
        pass

    def __get_current_index(self):
        return self.__current_index
    def __set_current_index(self, index):
        self.__current_index = index
        self.proxy.StackWidget_setCurrentIndex(self.widget, index)
    current_index = property(__get_current_index, __set_current_index)


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

    def __get_content(self):
        return self.__content
    def __set_content(self, content):
        self.proxy.ScrollArea_setWidget(self.widget, content.widget)
        self.__content = content
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

    def info(self):
        self.proxy.ScrollArea_info(self.widget)


class QtComboBoxWidget(QtWidget):

    def __init__(self, proxy, items, properties):
        super(QtComboBoxWidget, self).__init__(proxy, "combobox", properties)
        self.__on_current_text_changed = None
        self.items = items if items else []
        self.proxy.ComboBox_connect(self.widget, self)

    def __get_current_text(self):
        return self.proxy.ComboBox_getCurrentText(self.widget)
    def __set_current_text(self, text):
        self.proxy.ComboBox_setCurrentText(self.widget, unicode(text))
    current_text = property(__get_current_text, __set_current_text)

    def __get_on_current_text_changed(self):
        return self.__on_current_text_changed
    def __set_on_current_text_changed(self, fn):
        self.__on_current_text_changed = fn
    on_current_text_changed = property(__get_on_current_text_changed, __set_on_current_text_changed)

    def __get_items(self):
        return self.__items
    def __set_items(self, items):
        self.proxy.ComboBox_removeAllItems(self.widget)
        for item in items:
            self.proxy.ComboBox_addItem(self.widget, unicode(item))
    items = property(__get_items, __set_items)

    # this message comes from Qt implementation
    def current_text_changed(self, text):
        if self.__on_current_text_changed:
            self.__on_current_text_changed(text)


class QtPushButtonWidget(QtWidget):

    def __init__(self, proxy, text, properties):
        super(QtPushButtonWidget, self).__init__(proxy, "pushbutton", properties)
        self.__on_clicked = None
        self.text = text
        self.proxy.PushButton_connect(self.widget, self)

    def __get_text(self):
        return self.__text
    def __set_text(self, text):
        self.__text = text
        self.proxy.PushButton_setText(self.widget, unicode(text))
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

    def __init__(self, proxy, text, properties):
        super(QtLabelWidget, self).__init__(proxy, "label", properties)
        self.__text = None
        self.text = text

    def __get_text(self):
        return self.__text
    def __set_text(self, text):
        self.__text = text if text else ""
        self.proxy.Label_setText(self.widget, unicode(self.__text))
    text = property(__get_text, __set_text)


class QtSliderWidget(QtWidget):

    def __init__(self, proxy, properties):
        super(QtSliderWidget, self).__init__(proxy, "slider", properties)
        self.__on_value_changed = None
        self.__on_slider_pressed = None
        self.__on_slider_released = None
        self.__on_slider_moved = None
        self.__pressed = False
        self.__min = 0
        self.__max = 0
        self.proxy.Slider_connect(self.widget, self)
        self.minimum = self.__min
        self.maximum = self.__max

    def __get_value(self):
        return self.proxy.Slider_getValue(self.widget)
    def __set_value(self, value):
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

    def __init__(self, proxy, properties):
        super(QtLineEditWidget, self).__init__(proxy, "lineedit", properties)
        self.__on_editing_finished = None
        self.__on_text_edited = None
        self.__formatter = None
        self.proxy.LineEdit_connect(self.widget, self)

    def __get_text(self):
        return self.proxy.LineEdit_getText(self.widget)
    def __set_text(self, text):
        self.proxy.LineEdit_setText(self.widget, unicode(text))
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
        self.proxy.LineEdit_selectAll(self.widget)

    def editing_finished(self, text):
        if self.__formatter:
            self.__formatter.format(text)
        if self.__on_editing_finished:
            self.__on_editing_finished(text)

    def text_edited(self, text):
        if self.__on_text_edited:
            self.__on_text_edited(text)


class QtCanvasWidget(QtWidget):

    def __init__(self, proxy, properties):
        super(QtCanvasWidget, self).__init__(proxy, "canvas", properties)
        self.proxy.Canvas_connect(self.widget, self)
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

    def __get_canvas_size(self):
        return (self.height, self.width)
    canvas_size = property(__get_canvas_size)

    def __get_focusable(self):
        return self.__focusable
    def __set_focusable(self, focusable):
        self.__focusable = focusable
        self.proxy.Canvas_setFocusPolicy(self.widget, 15 if focusable else 0)
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
        self.proxy.Canvas_draw(self.widget, commands)

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
            return self.__on_key_pressed(QtKey(text, key, raw_modifiers))
        return False


# pobj
class QtTreeWidget(QtWidget):

    def __init__(self, proxy, properties):
        super(QtTreeWidget, self).__init__(proxy, "pytree", properties)
        self.proxy.Widget_setWidgetProperty(self.widget, "stylesheet", "* { border: none; background-color: '#EEEEEE'; } PyTreeWidget { margin-top: 4px }")
        self.proxy.PyTreeWidget_connect(self.widget, self)
        self.__item_model_controller = None
        self.on_key_pressed = None
        self.on_current_item_changed = None
        self.on_item_clicked = None
        self.on_item_double_clicked = None

    def __get_item_model_controller(self):
        return self.__item_model_controller
    def __set_item_model_controller(self, item_model_controller):
        self.__item_model_controller = item_model_controller
        self.proxy.PyTreeWidget_setModel(self.widget, item_model_controller.py_item_model)
    item_model_controller = property(__get_item_model_controller, __set_item_model_controller)

    def treeItemChanged(self, index, parent_row, parent_id):
        if self.on_current_item_changed:
            self.on_current_item_changed(index, parent_row, parent_id)

    def treeItemKeyPress(self, index, parent_row, parent_id, text, key, raw_modifiers):
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

    def set_current_row(self, index, parent_row, parent_id):
        self.proxy.PyTreeWidget_setCurrentRow(self.widget, index, parent_row, parent_id)


# pobj
class QtListWidget(QtWidget):

    def __init__(self, proxy, properties):
        super(QtListWidget, self).__init__(proxy, "pylist", properties)
        self.proxy.Widget_setWidgetProperty(self.widget, "stylesheet", "* { border: none; background-color: '#EEEEEE'; } PyListWidget { margin-top: 4px }")
        self.proxy.PyListWidget_connect(self.widget, self)
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
        self.proxy.PyListWidget_setModel(self.widget, list_model_controller.py_list_model)
    list_model_controller = property(__get_list_model_controller, __set_list_model_controller)

    def listItemChanged(self, index):
        if self.on_current_item_changed:
            self.on_current_item_changed(index)

    def listItemKeyPress(self, index, text, key, raw_modifiers):
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
        return self.proxy.PyListWidget_getCurrentRow(self.widget)
    def __set_current_index(self, current_index):
        return self.proxy.PyListWidget_setCurrentRow(self.widget, current_index)
    current_index = property(__get_current_index, __set_current_index)

    def __get_on_paint(self):
        return self.__on_paint
    def __set_on_paint(self, fn):
        self.__on_paint = fn
        if not self.__delegate:
            self.__delegate = self.proxy.PyStyledDelegate_create()
            self.proxy.PyStyledDelegate_connect(self.__delegate, self)
            self.proxy.PyListWidget_setItemDelegate(self.widget, self.__delegate)
    on_paint = property(__get_on_paint, __set_on_paint)

    # this message comes from the styled item delegate
    def paint(self, dc, options):
        if self.__on_paint:
            drawing_context = QtDrawingContext()
            self.__on_paint(drawing_context, options)
            self.proxy.DrawingContext_drawCommands(dc, drawing_context.commands)


class QtOutputWidget(QtWidget):

    def __init__(self, proxy, properties):
        super(QtOutputWidget, self).__init__(proxy, "output", properties)

    def send(self, message):
        self.proxy.Output_out(self.widget, unicode(message))


# pobj
class QtConsoleWidget(QtWidget):

    def __init__(self, proxy, properties):
        super(QtConsoleWidget, self).__init__(proxy, "console", properties)
        self.on_interpret_command = None
        self.proxy.Console_connect(self.widget, self)

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

    def create(self, document_window, title, key_sequence, role):
        self.native_action = self.proxy.Action_create(document_window.native_document_window, unicode(title), key_sequence, role)
        self.proxy.Action_connect(self.native_action, self)

    def triggered(self):
        if self.on_triggered:
            self.on_triggered()

class QtMenu(object):

    def __init__(self, proxy, document_window, native_menu):
        self.proxy = proxy
        self.document_window = document_window
        self.native_menu = native_menu
        self.proxy.Menu_connect(self.native_menu, self)
        self.on_about_to_show = None

    def aboutToShow(self):
        if self.on_about_to_show:
            self.on_about_to_show()

    def add_menu_item(self, title, callback, key_sequence=None, role=None):
        action = QtAction(self.proxy)
        action.create(self.document_window, title, key_sequence, role)
        action.on_triggered = callback
        self.proxy.Menu_addAction(self.native_menu, action.native_action)
        return action

    def add_action(self, action):
        self.proxy.Menu_addAction(self.native_menu, action.native_action)

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


class QtDocumentWindow(object):

    def __init__(self, proxy):
        self.proxy = proxy
        self.native_document_window = self.proxy.DocumentWindow_create()
        self.proxy.DocumentWindow_connect(self.native_document_window, self)
        self.root_widget = None
        self.has_event_loop = True
        self.on_periodic = None
        self.on_about_to_show = None
        self.on_about_to_close = None

    def attach(self, root_widget):
        self.root_widget = root_widget
        self.proxy.DocumentWindow_setCentralWidget(self.native_document_window, self.root_widget.widget)

    def get_file_paths_dialog(self, title, directory, filter):
        return self.proxy.DocumentWindow_getFilePath(self.native_document_window, "loadmany", unicode(title), unicode(directory), unicode(filter))

    def get_save_file_path(self, title, directory, filter):
        return self.proxy.DocumentWindow_getFilePath(self.native_document_window, "save", unicode(title), unicode(directory), unicode(filter))

    def create_dock_widget(self, widget, panel_id, title, positions, position):
        return QtDockWidget(self.proxy, self, widget, panel_id, title, positions, position)

    def tabify_dock_widgets(self, dock_widget1, dock_widget2):
        self.proxy.DocumentWindow_tabifyDockWidgets(self.native_document_window, dock_widget1.native_dock_widget, dock_widget2.native_dock_widget)

    def show(self):
        self.proxy.DocumentWindow_show(self.native_document_window)

    def periodic(self):
        if self.on_periodic:
            self.on_periodic()

    def aboutToShow(self):
        if self.on_about_to_show:
            self.on_about_to_show()

    def aboutToClose(self, geometry, state):
        if self.on_about_to_close:
            self.on_about_to_close(geometry, state)

    def close(self):
        self.proxy.DocumentWindow_close(self.native_document_window)
        self.root_widget.close()

    def add_menu(self, title):
        native_menu = self.proxy.DocumentWindow_addMenu(self.native_document_window, unicode(title))
        menu = QtMenu(self.proxy, self, native_menu)
        return menu

    def insert_menu(self, title, before_menu):
        native_menu = self.proxy.DocumentWindow_insertMenu(self.native_document_window, unicode(title), before_menu.native_menu)
        menu = QtMenu(self.proxy, self, native_menu)
        return menu

    def restore(self, geometry, state):
        self.proxy.DocumentWindow_restore(self.native_document_window, geometry, state)


class QtDockWidget(object):

    def __init__(self, proxy, document_window, widget, panel_id, title, positions, position):
        self.proxy = proxy
        self.document_window = document_window
        self.widget = widget
        self.native_dock_widget = self.proxy.DocumentWindow_addDockWidget(self.document_window.native_document_window, widget.widget, panel_id, unicode(title), positions, position)

    def close(self):
        self.proxy.Widget_removeDockWidget(self.document_window.native_document_window, self.native_dock_widget)
        self.widget.close()

    def __get_toggle_action(self):
        return QtAction(self.proxy, self.proxy.DockWidget_getToggleAction(self.native_dock_widget))
    toggle_action = property(__get_toggle_action)

    def show(self):
        self.proxy.Widget_show(self.native_dock_widget)

    def hide(self):
        self.proxy.Widget_close(self.native_dock_widget)


class QtUserInterface(object):

    def __init__(self, proxy):
        self.proxy = proxy

    def close(self):
        self.proxy.Application_close()

    # data objects

    def create_mime_data(self):
        return QtMimeData(self.proxy)

    def create_item_model_controller(self, keys):
        return QtItemModelController(self.proxy, keys)

    def create_list_model_controller(self, keys):
        return QtListModelController(self.proxy, keys)

    # window elements

    def create_document_window(self):
        return QtDocumentWindow(self.proxy)

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

    def create_combo_box_widget(self, items=None, properties=None):
        return QtComboBoxWidget(self.proxy, items, properties)

    def create_push_button_widget(self, text=None, properties=None):
        return QtPushButtonWidget(self.proxy, text, properties)

    def create_label_widget(self, text=None, properties=None):
        return QtLabelWidget(self.proxy, text, properties)

    def create_slider_widget(self, properties=None):
        return QtSliderWidget(self.proxy, properties)

    def create_line_edit_widget(self, properties=None):
        return QtLineEditWidget(self.proxy, properties)

    def create_canvas_widget(self, properties=None):
        return QtCanvasWidget(self.proxy, properties)

    def create_tree_widget(self, properties=None):
        return QtTreeWidget(self.proxy, properties)

    def create_list_widget(self, properties=None):
        return QtListWidget(self.proxy, properties)

    def create_output_widget(self, properties=None):
        return QtOutputWidget(self.proxy, properties)

    def create_console_widget(self, properties=None):
        return QtConsoleWidget(self.proxy, properties)

    # file i/o

    def load_rgba_data_from_file(self, filename):
        return self.proxy.Core_readImageToPyArray(unicode(filename))

    def save_rgba_data_to_file(self, data, filename, format):
        return self.proxy.Core_writePyArrayToImage(data, unicode(filename), str(format))

    # persistence (associated with application)

    def get_data_location(self):
        return self.proxy.Core_getLocation("data")

    def get_persistent_string(self, key, default_value=None):
        value = self.proxy.Settings_getString(key)
        return value if value else default_value

    def set_persistent_string(self, key, value):
        self.proxy.Settings_setString(key, value)

    def get_persistent_byte_array(self, key, default_value=None):
        value = self.proxy.Settings_getByteArray(key)
        return value if value else default_value

    def set_persistent_byte_array(self, key, value):
        self.proxy.Settings_setByteArray(key, value)

    # misc

    def create_key_by_id(self, key_id):
        if key_id == "delete": return QtKey(chr(127), 0, 0)
        return None
