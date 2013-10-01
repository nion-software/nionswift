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
Application.Application(Test.UserInterface(), catch_stdout=False)
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


class ImageView:
    def __init__(self, image_panel):
        self.image_panel = image_panel
        self.widget = None
        self.image_source = None
        self.rect = ((0,0), (640,480))
    def close(self):
        pass
    def set_focused(self, focused):
        pass
    def set_overlay_script(self, js):
        pass
    def set_underlay_script(self, js, finish_event=None):
        if finish_event:
            finish_event.set()
    def map_image_norm_to_widget(self, image_size, p):
        return (p[0]*image_size[0], p[1]*image_size[1])
    def map_widget_to_image(self, image_size, p):
        return p

class DrawingContext(object):
    def __init__(self):
        self.fillStyle = None
        self.font = None
        self.textAlign = None
        self.textBaseline = None
        self.strokeStyle = None
        self.lineWidth = None
        self.lineCap = None
        self.lineJoin = None
    def clear(self):
        pass
    def save(self):
        pass
    def restore(self):
        pass
    def beginPath(self):
        pass
    def closePath(self):
        pass
    def translate(self, x, y):
        pass
    def scale(self, x, y):
        pass
    def moveTo(self, x, y):
        pass
    def lineTo(self, x, y):
        pass
    def rect(self, a, b, c, d):
        pass
    def arc(self, a, b, c, d, e, f):
        pass
    def drawImage(self, img, a, b, c, d):
        pass
    def stroke(self):
        pass
    def fill(self):
        pass
    def fillText(self, text, x, y, maxWidth=None):
        pass
    def create_linear_gradient(self, x, y, width, height):
        return DrawingContext()
    def add_color_stop(self, a, b):
        pass

class Widget:
    def __init__(self):
        self.widget = ()
        self.drawing_context = DrawingContext()
        self.width = 640
        self.height = 480
        self.current_index = 0
        self.children = []
    def add(self, widget):
        self.children.append(widget)
    def insert(self, widget, before):
        self.children.insert(before, widget)
    def remove(self, widget):
        self.children.remove(widget)
    def add_stretch(self):
        pass
    def create_layer(self):
        return Widget()
    def draw(self):
        pass
    def save_state(self, tag):
        pass
    def restore_state(self, tag):
        pass
    def set_current_row(self, index, parent_row, parent_id):
        pass

# define a dummy user interface to use during tests
class UserInterface:
    def __init__(self):
        pass
    def create_row_widget(self, properties=None):
        return Widget()
    def create_column_widget(self, properties=None):
        return Widget()
    def create_splitter_widget(self, properties=None):
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
    def Core_out(self, str):
        return (str)
    def Core_pathToURL(self, path):
        return (path)
    def DocumentWindow_addDockWidget(self, document_window, widget, identifier, title, positions, position):
        return (document_window, widget, identifier, title, positions, position)
    def DocumentWindow_setCentralWidget(self, document_window, widget):
        pass
    def DocumentWindow_tabifyDockWidgets(self, document_controller, widget1, widget2):
        pass
    def PyItemModel_beginInsertRows(self, py_item_model, first_row, last_row, parent_row, parent_id):
        pass
    def PyItemModel_beginRemoveRows(self, py_item_model, first_row, last_row, parent_row, parent_id):
        pass
    def PyItemModel_create(self, delegate, keys):
        return (delegate, keys)
    def PyItemModel_dataChanged(self, py_item_model, row, parent_row, parent_id):
        pass
    def PyItemModel_destroy(self, py_item_model):
        pass
    def PyItemModel_endInsertRow(self, py_item_model):
        pass
    def PyItemModel_endRemoveRow(self, py_item_model):
        pass
    def PyListModel_beginInsertRows(self, py_item_model, first_row, last_row):
        pass
    def PyListModel_beginRemoveRows(self, py_item_model, first_row, last_row):
        pass
    def PyListModel_create(self, delegate, keys):
        return (delegate, keys)
    def PyListModel_dataChanged(self, py_item_model):
        pass
    def PyListModel_destroy(self, py_item_model):
        pass
    def PyListModel_endInsertRow(self, py_item_model):
        pass
    def PyListModel_endRemoveRow(self, py_item_model):
        pass
    def PyListWidget_setCurrentRow(self, widget, index):
        pass
    def PyListWidget_setModel(self, widget, py_list_model):
        pass
    def PyTreeWidget_setCurrentRow(self, widget, index, parent_row, parent_id):
        pass
    def PyTreeWidget_setModel(self, widget, py_item_model):
        pass
    def Widget_removeDockWidget(self, document_controller, dock_widget):
        pass


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
