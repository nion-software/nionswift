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
from Decorators import queue_main_thread
import Graphics
import Image


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
    def __init__(self, document_controller, keys):
        self.__document_controller_weakref = weakref.ref(document_controller)
        self.__keys = keys
        self.py_list_model = self.ui.PyListModel_create(self, ["index"] + keys)
        self.model = []
    def __get_document_controller(self):
        return self.__document_controller_weakref()
    document_controller = property(__get_document_controller)
    def __get_ui(self):
        return self.document_controller.ui
    ui = property(__get_ui)
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


class QtImageViewDisplayThread(object):
    def __init__(self, ui, image_view, uuid):
        self.ui = ui
        self.__image_view_weakref = weakref.ref(image_view)
        self.controller_id = str(uuid)
        self.__data_item = None
        self.__thread_break = False
        self.__thread_ended_event = threading.Event()
        self.__has_data_item = threading.Event()
        self.__weak_data_item = None
        self.__has_data_item_lock = threading.Lock()
        self.display_thread = threading.Thread(target=self._display_process_thread)
        self.display_thread.start()

    def close(self):
        with self.__has_data_item_lock:
            self.__thread_break = True
            self.__has_data_item.set()
        self.__thread_ended_event.wait()

    def __get_image_view(self):
        return self.__image_view_weakref()
    image_view = property(__get_image_view)

    delay_queue = property(lambda self: self.image_view.document_controller.delay_queue)

    @queue_main_thread
    def __set_image_source(self, url):
        image_view = self.image_view
        if image_view and image_view.widget:
            self.ui.Widget_setWidgetProperty(image_view.widget, "imageSource", url)

    def __get_data_item(self):
        return self.__data_item
    def __set_data_item(self, data_item):
        if self.__data_item:
            self.__data_item.remove_listener(self)
            self.__data_item.remove_ref()
            self.__data_item = None
        if data_item:
            self.__data_item = data_item
            self.__data_item.add_ref()
            self.__data_item.add_listener(self)
        self.data_item_changed(self.__data_item, {"property": "source"})
    data_item = property(__get_data_item, __set_data_item)

    def process(self):
        data_item = self.data_item
        weak_data_item = weakref.ref(data_item) if data_item else None
        with self.__has_data_item_lock:
            self.__weak_data_item = weak_data_item
            self.__has_data_item.set()

    def data_item_changed(self, data_item, info):
        if data_item == self.data_item:  # TODO: until threading issues are worked out
            assert data_item == self.data_item
            self.process()

    def _display_process_thread(self):
        while True:
            self.__has_data_item.wait()
            weak_data_item = None
            thread_break = False
            with self.__has_data_item_lock:
                weak_data_item = self.__weak_data_item
                thread_break = self.__thread_break
                self.__has_data_item.clear()
            if thread_break:
                break
            try:
                data_item = weak_data_item() if weak_data_item else None
                # grab the image if there is one
                image_data = None
                if data_item:
                    image_data = data_item.data
                # make an rgb image and send it
                rgba_image = None
                if Image.is_data_2d(image_data):
                    image_data = Image.scalarFromArray(image_data)
                    rgba_image = Image.createRGBAImageFromArray(image_data, display_limits=data_item.display_limits)
                else:
                    rgba_image = Image.createRGBAImageFromColor((480, 640), 255, 255, 255, 0)
                image_id = self.ui.ImageDisplayController_sendImage(self.controller_id, rgba_image)
                self.__set_image_source("image://idc/"+self.controller_id+"/"+str(image_id))
            except Exception as e:
                logging.debug("Display thread exception %s", e)
        self.__thread_ended_event.set()


class DrawingContext(object):
    def __init__(self):
        self.js = ""
    def save(self):
        self.js += "ctx.save();"
    def restore(self):
        self.js += "ctx.restore();"
    def beginPath(self):
        self.js += "ctx.beginPath();"
    def closePath(self):
        self.js += "ctx.closePath();"
    def translate(self, x, y):
        self.js += "ctx.translate({0}, {1});".format(x, y)
    def scale(self, x, y):
        self.js += "ctx.scale({0}, {1});".format(x, y)
    def moveTo(self, x, y):
        self.js += "ctx.moveTo({0}, {1});".format(x, y)
    def lineTo(self, x, y):
        self.js += "ctx.lineTo({0}, {1});".format(x, y)
    def arc(self, a, b, c, d, e, f):
        self.js += "ctx.arc({0}, {1}, {2}, {3}, {4}, {5});".format(a, b, c, d, e, "true" if f else "false")
    def stroke(self):
        self.js += "ctx.stroke();"
    def fill(self):
        self.js += "ctx.fill();"
    def fillText(self, text, x, y, maxWidth=None):
        self.js += "ctx.fillText('{0}', {1}, {2}{3});".format(text, x, y, ", {0}".format(maxWidth) if maxWidth else "")
    def __get_fillStyle(self):
        raise NotImplementedError()
    def __set_fillStyle(self, a):
        self.js += "ctx.fillStyle = '{0}';".format(a)
    fillStyle = property(__get_fillStyle, __set_fillStyle)
    def __get_font(self):
        raise NotImplementedError()
    def __set_font(self, a):
        self.js += "ctx.font = '{0}';".format(a)
    font = property(__get_font, __set_font)
    def __get_strokeStyle(self):
        raise NotImplementedError()
    def __set_strokeStyle(self, a):
        self.js += "ctx.strokeStyle = '{0}';".format(a)
    strokeStyle = property(__get_strokeStyle, __set_strokeStyle)
    def __get_lineWidth(self):
        raise NotImplementedError()
    def __set_lineWidth(self, a):
        self.js += "ctx.lineWidth = {0};".format(a)
    lineWidth = property(__get_lineWidth, __set_lineWidth)


class QtImageView(object):

    def __init__(self, image_panel):
        self.__image_panel_weakref = weakref.ref(image_panel)
        # load the Qml and associate it with this panel.
        context_properties = { }
        qml_filename = self._relativeFile("ImageView.qml")
        self.__uuid = uuid.uuid4()
        self.widget = self.ui.DocumentWindow_loadQmlWidget(self.document_controller.document_window, qml_filename, self, context_properties)
        self.rect = ((0, 0), (0, 0))
        self.display_thread = QtImageViewDisplayThread(self.ui, self, self.uuid)
        self.display_thread.process()

    def close(self):
        self.ui.Widget_unloadWidget(self.widget)
        self.widget = None
        self.display_thread.close()  # required before destructing display thread
        self.display_thread = None

    # uuid property. read only.
    def __get_uuid(self):
        return self.__uuid
    uuid = property(__get_uuid)

    # access for the property. this allows C++ to get the value.
    def get_uuid_str(self):
        return str(self.uuid)

    def __get_image_panel(self):
        return self.__image_panel_weakref()
    image_panel = property(__get_image_panel)

    def __get_document_controller(self):
        return self.image_panel.document_controller if self.image_panel else None
    document_controller = property(__get_document_controller)

    def __get_ui(self):
        return self.document_controller.ui if self.document_controller else None
    ui = property(__get_ui)

    def _relativeFile(self, filename):
        dir = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))
        return os.path.join(dir, filename)

    delay_queue = property(lambda self: self.document_controller.delay_queue)

    @queue_main_thread
    def set_underlay_script(self, js):
        if self.ui:
            self.ui.Widget_setWidgetProperty(self.widget, "underlay", js)

    @queue_main_thread
    def set_overlay_script(self, js):
        if self.ui:
            self.ui.Widget_setWidgetProperty(self.widget, "overlay", js)

    def draw_graphics(self, image_size, graphics, graphic_selection, mapping):
        rect = self.rect
        ctx = DrawingContext()
        ctx.save()
        if image_size and graphics:
            for graphic_index, graphic in enumerate(graphics):
                graphic.draw(ctx, mapping, graphic_selection.contains(graphic_index))
        ctx.restore()
        self.set_overlay_script(ctx.js)

    # messages come from qml

    def resized(self, x, y, width, height):
        self.rect = ((y, x), (height, width))
        if self.image_panel:
            self.image_panel.resized(self.rect)
    def keyPressed(self, text, key, raw_modifiers):
        # ugly hack to get qml to pass modifiers cleanly to mouse functions
        self.ui.Widget_setWidgetProperty(self.widget, "modifiers", raw_modifiers)
        return self.image_panel.key_pressed(text, key, QtKeyboardModifiers(raw_modifiers))
    def mouseEntered(self):
        self.image_panel.mouse_entered()
    def mouseExited(self):
        self.image_panel.mouse_exited()
    def mouseClicked(self, y, x, raw_modifiers):
        self.image_panel.mouse_clicked((y, x), QtKeyboardModifiers(raw_modifiers))
    def mousePressed(self, y, x, raw_modifiers):
        self.image_panel.mouse_pressed((y, x), QtKeyboardModifiers(raw_modifiers))
    def mouseReleased(self, y, x, raw_modifiers):
        self.image_panel.mouse_released((y, x), QtKeyboardModifiers(raw_modifiers))
    def mousePositionChanged(self, y, x, raw_modifiers):
        self.image_panel.mouse_position_changed((y, x), QtKeyboardModifiers(raw_modifiers))
    def display_changed(self):
        self.image_panel.display_changed()

    def __get_data_item(self):
        return self.display_thread.data_item
    def __set_data_item(self, data_item):
        # handle the display thread
        self.display_thread.data_item = data_item
    data_item = property(__get_data_item, __set_data_item)

    def set_focused(self, focused):
        self.ui.Widget_setContextProperty(self.widget, "focused", focused)

    # map from image normalized coordinates to widget coordinates
    def map_image_norm_to_widget(self, image_size, p):
        if image_size:
            image_rect = Graphics.fit_to_size(self.rect, image_size)
            zoom = self.ui.Widget_getWidgetProperty(self.widget, "zoom")
            tx = self.ui.Widget_getWidgetProperty(self.widget, "translateX")
            ty = self.ui.Widget_getWidgetProperty(self.widget, "translateY")
            image_y = image_rect[0][0] + ty*zoom - 0.5*image_rect[1][0]*(zoom - 1)
            image_x = image_rect[0][1] + tx*zoom - 0.5*image_rect[1][1]*(zoom - 1)
            image_rect = ((image_y, image_x), (image_rect[1][0]*zoom, image_rect[1][1]*zoom))
            return (p[0]*image_rect[1][0] + image_rect[0][0], p[1]*image_rect[1][1] + image_rect[0][1])
        return None

    # map from widget coordinates to image coordinates
    def map_mouse_to_image(self, image_size, p):
        if image_size:
            widget_width = self.ui.Widget_getWidgetProperty(self.widget, "imageWidth")
            widget_height = self.ui.Widget_getWidgetProperty(self.widget, "imageHeight")
            if widget_height > 0 and widget_width > 0:
                widget_aspect = float(widget_width) / float(widget_height)
                image_aspect = float(image_size[1]) / float(image_size[0])
                # scale maps from widget to image size
                scale = image_size[0] / widget_height if widget_aspect > image_aspect else image_size[1] / widget_width
                image_y = (p[0] - widget_height * 0.5) * scale + 0.5 * image_size[0]
                image_x = (p[1] - widget_width * 0.5) * scale + 0.5 * image_size[1]
                return (image_y, image_x) # c-indexing
        return None


class QtUserInterface(object):

    # Higher level UI objects

    def create_image_view(self, image_panel):
        return QtImageView(image_panel)

    def create_mime_data(self):
        return QtMimeData(self, self.MimeData_create())

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

    def readImageToPyArray(self, filename):
        return NionLib.readImageToPyArray(filename)

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

    # Drawing

    def Drawing_clearShapes(self, drawing):
        NionLib.Drawing_clearShapes(drawing)

    def Drawing_addShape(self, drawing, values):
        NionLib.Drawing_addShape(drawing, values)

    # Histogram

    def Histogram_setData(self, histogram, data):
        NionLib.Histogram_setData(histogram, data)

    def Histogram_setLeftRight(self, histogram, left, right):
        NionLib.Histogram_setLeftRight(histogram, left, right)

    def Histogram_setDelegate(self, histogram, delegate):
        NionLib.Histogram_setDelegate(histogram, delegate)

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

    def Widget_unloadWidget(self, widget):
        NionLib.Widget_unloadWidget(widget)
