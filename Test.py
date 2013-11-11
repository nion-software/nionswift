# standard libraries
import importlib
import inspect
import logging
import os
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import PlugInManager

"""
Running tests without Qt:

import Application
import Test
Application.Application(Test.UserInterface())
Test.run_all_tests()
Test.run_test("TestApplicationClass")
"""



suites = []
suite_dict = {}
alltests = None

def appendTestSuites(suites):
    suites.append(suites)

# scan through directory and look for tests (files ending in test.py)
# load the module and add the tests
def load_tests():
    global suites
    global suite_dict
    global alltests

    localpath = os.path.dirname(os.path.realpath(__file__))
    for file in os.listdir(os.path.join(localpath, "test")):
        if file.endswith("_test.py"):
            module_name = "nion.swift.test." + file.replace(".py", "")
            module = importlib.import_module(module_name)
            for maybe_a_class in inspect.getmembers(module):
                if inspect.isclass(maybe_a_class[1]) and maybe_a_class[0].startswith("Test"):
                    test_name = maybe_a_class[0]
                    # It is a class... add it to the test suite.
                    cls = getattr(module, test_name)
                    suite = unittest.TestLoader().loadTestsFromTestCase(cls)
                    suites.append(suite)
                    suite_dict[test_name] = suite

    suites.extend(PlugInManager.testSuites())

    alltests = unittest.TestSuite(suites)

def run_all_tests():
    unittest.TextTestRunner(verbosity=2).run(alltests)

def run_test(test_name):
    unittest.TextTestRunner(verbosity=2).run(suite_dict[test_name])


class DrawingContext(object):
    def __init__(self):
        self.fill_style = None
        self.font = None
        self.text_align = None
        self.text_baseline = None
        self.stroke_style = None
        self.line_width = None
        self.line_cap = None
        self.line_join = None
    def copy_from(self, drawing_context):
        pass
    def clear(self):
        pass
    def save(self):
        pass
    def restore(self):
        pass
    def begin_path(self):
        pass
    def close_path(self):
        pass
    def translate(self, x, y):
        pass
    def scale(self, x, y):
        pass
    def move_to(self, x, y):
        pass
    def line_to(self, x, y):
        pass
    def rect(self, a, b, c, d):
        pass
    def arc(self, a, b, c, d, e, f):
        pass
    def draw_image(self, img, a, b, c, d):
        pass
    def stroke(self):
        pass
    def fill(self):
        pass
    def fill_text(self, text, x, y, maxWidth=None):
        pass
    def create_linear_gradient(self, x, y, width, height):
        return DrawingContext()
    def add_color_stop(self, a, b):
        pass

class Layer:
    def __init__(self):
        self.drawing_context = DrawingContext()

class Widget:
    def __init__(self):
        self.widget = ()
        self.drawing_context = DrawingContext()
        self.width = 640
        self.height = 480
        self.current_index = 0
        self.children = []
        self.index = -1
        self.parent_row = -1
        self.parent_id = 0
        self.current_index = -1
        self.viewport = ((0, 0), (480, 640))
        self.layers = []
        self.layers.append(Layer())
        self.focused = False
    def close(self):
        pass
    def add(self, widget, fill=False, alignment=None):
        self.children.append(widget)
    def insert(self, widget, before, fill=False, alignment=None):
        self.children.insert(before, widget)
    def remove(self, widget):
        self.children.remove(widget)
    def add_stretch(self):
        pass
    def add_spacing(self, spacing):
        pass
    def create_layer(self):
        return Widget()
    def create_drawing_context(self):
        return DrawingContext()
    def draw(self):
        pass
    def save_state(self, tag):
        pass
    def restore_state(self, tag):
        pass
    def set_current_row(self, index, parent_row, parent_id):
        self.index = index
        self.parent_row = parent_row
        self.parent_id = parent_id
    def scroll_to(self, x, y):
        pass
    def add_overlay(self, overlay):
        pass
    def show(self):
        pass
    def hide(self):
        pass

class Menu:
    def __init__(self):
        pass
    def add_menu_item(self, title, callback, key_sequence=None, role=None):
        pass
    def add_separator(self):
        pass

class DocumentWindow:
    def __init__(self):
        self.has_event_loop = False
        self.widget = None
    def attach(self, widget):
        self.widget = widget
    def create_dock_widget(self, widget, panel_id, title, positions, position):
        return Widget()
    def tabify_dock_widgets(self, dock_widget1, dock_widget2):
        pass
    def add_menu(self, title):
        return Menu()

class ItemModelController:
    DRAG = 0
    DROP = 1
    class Item(object):
        def __init__(self, data=None):
            self.children = []
            self.parent = None
            self.id = None
            self.data = data if data else {}
        def insert_child(self, before_index, item):
            item.parent = self
            self.children.insert(before_index, item)
        def remove_child(self, item):
            item.parent = None
            self.children.remove(item)
        def child(self, index):
            return self.children[index]
        def __get_row(self):
            if self.parent:
                return self.parent.children.index(self)
            return -1
        row = property(__get_row)
    def __init__(self):
        self.__next_id = 0
        self.root = self.create_item()
    def close(self):
        pass
    def create_item(self, data=None):
        item = ItemModelController.Item(data)
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
    def begin_insert(self, first_row, last_row, parent_row, parent_id):
        pass
    def end_insert(self):
        pass
    def begin_remove(self, first_row, last_row, parent_row, parent_id):
        pass
    def end_remove(self):
        pass
    def data_changed(self, row, parent_row, parent_id):
        pass
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

class ListModelController:
    DRAG = 0
    DROP = 1
    def __init__(self):
        self.model = []
    def close(self):
        pass
    def begin_insert(self, first_row, last_row):
        pass
    def end_insert(self):
        pass
    def begin_remove(self, first_row, last_row):
        pass
    def end_remove(self):
        pass
    def data_changed(self):
        pass


class Key(object):
    def __init__(self, text, key, raw_modifiers):
        self.text = text
        self.key = key
        self.modifiers = KeyboardModifiers()

    def __get_is_delete(self):
        return self.text == "delete"
    is_delete = property(__get_is_delete)


# define a dummy user interface to use during tests
class UserInterface:
    def __init__(self):
        pass
    def create_mime_data(self):
        return None
    def create_item_model_controller(self, keys):
        return ItemModelController()
    def create_list_model_controller(self, keys):
        return ListModelController()
    def create_document_window(self):
        return DocumentWindow()
    def tabify_dock_widgets(self, document_controller, dock_widget1, dock_widget2):
        pass
    def create_row_widget(self, properties=None):
        return Widget()
    def create_column_widget(self, properties=None):
        return Widget()
    def create_splitter_widget(self, orientation="vertical", properties=None):
        return Widget()
    def create_tab_widget(self, properties=None):
        return Widget()
    def create_stack_widget(self, properties=None):
        return Widget()
    def create_scroll_area_widget(self, properties=None):
        return Widget()
    def create_combo_box_widget(self, items=None, properties=None):
        return Widget()
    def create_push_button_widget(self, text=None, properties=None):
        return Widget()
    def create_label_widget(self, text=None, properties=None):
        return Widget()
    def create_slider_widget(self, properties=None):
        return Widget()
    def create_line_edit_widget(self, properties=None):
        return Widget()
    def create_canvas_widget(self, properties=None):
        return Widget()
    def create_tree_widget(self, properties=None):
        return Widget()
    def create_list_widget(self, properties=None):
        return Widget()
    def create_output_widget(self, properties=None):
        return Widget()
    def create_console_widget(self, properties=None):
        return Widget()
    def load_rgba_data_from_file(self, filename):
        return numpy.zeros((20,20), numpy.uint32)
    def get_persistent_string(self, key, default_value=None):
        return default_value
    def set_persistent_string(self, key, value):
        pass
    def get_data_location(self):
        pass
    def create_key_by_id(self, key_id):
        return Key(key_id, 0, 0)


class KeyboardModifiers(object):
    def __init__(self, shift=False, control=False, alt=False, meta=False, keypad=False):
        self.__shift = shift
        self.__control = control
        self.__alt = alt
        self.__meta = meta
        self.__keypad = keypad
    # shift
    def __get_shift(self):
        return self.__shift
    shift = property(__get_shift)
    def __get_only_shift(self):
        return self.__shift and not self.__control and not self.__alt and not self.__meta
    only_shift = property(__get_only_shift)
    # control (command key on mac)
    def __get_control(self):
        return self.__control
    control = property(__get_control)
    def __get_only_control(self):
        return self.__control and not self.__shift and not self.__alt and not self.__meta
    only_control = property(__get_only_control)
    # alt (option key on mac)
    def __get_alt(self):
        return self.__alt
    alt = property(__get_alt)
    def __get_only_alt(self):
        return self.__alt and not self.__control and not self.__shift and not self.__meta
    only_alt = property(__get_only_alt)
    # option (alt key on windows)
    def __get_option(self):
        return self.__alt
    option = property(__get_option)
    def __get_only_option(self):
        return self.__alt and not self.__control and not self.__shift and not self.__meta
    only_option = property(__get_only_option)
    # meta (control key on mac)
    def __get_meta(self):
        return self.__meta
    meta = property(__get_meta)
    def __get_only_meta(self):
        return self.__meta and not self.__control and not self.__shift and not self.__alt
    only_meta = property(__get_only_meta)
    # keypad
    def __get_keypad(self):
        return self.__keypad
    keypad = property(__get_keypad)
    def __get_only_keypad(self):
        return self.__keypad
    only_keypad = property(__get_only_keypad)
