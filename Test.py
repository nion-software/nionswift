# standard libraries
import importlib
import inspect
import logging
import os
import unittest

# third party libraries
import numpy

# local libraries
import PlugInManager

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
    def close(self):
        pass
    def draw_graphics(self, image_size, graphics, graphic_selection, mapping):
        pass
    def set_focused(self, focused):
        pass
    def set_underlay_script(self, js):
        pass
    def map_image_norm_to_widget(self, image_size, p):
        return (p[0]*image_size[0], p[1]*image_size[1])
    def map_mouse_to_image(self, image_size, p):
        return p

# define a dummy user interface to use during tests
class UserInterface:
    def __init__(self):
        pass
    def create_image_view(self, image_panel):
        return ImageView(image_panel)
    def Console_setDelegate(self, widget, delegate):
        pass
    def Core_out(self, str):
        return (str)
    def Core_pathToURL(self, path):
        return (path)
    def Core_URLToPath(self, url):
        return (url)
    def DocumentWindow_addDockWidget(self, document_window, widget, identifier, title, positions, position):
        return (document_window, widget, identifier, title, positions, position)
    def DocumentWindow_loadQmlWidget(self, document_window, filename, panel, context_properties):
        return (document_window, filename, panel, context_properties)
    def DocumentWindow_registerThumbnailProvider(self, document_window, uuid_str, data_item):
        pass
    def DocumentWindow_setCentralWidget(self, document_window, widget):
        pass
    def DocumentWindow_tabifyDockWidgets(self, document_controller, widget1, widget2):
        pass
    def DocumentWindow_unregisterThumbnailProvider(self, document_window, uuid_str):
        pass
    def Drawing_clearShapes(self, drawing):
        pass
    def Drawing_addShape(self, drawing, values):
        pass
    def Histogram_setData(self, histogram, data):
        pass
    def Histogram_setLeftRight(self, histogram, left, right):
        pass
    def Histogram_setDelegate(self, histogram, delegate):
        pass
    def ImageDisplayController_sendImage(self, controller_id, rgba_image):
        return 0
    def Output_out(self, widget, message):
        pass  # print message
    def readImageToPyArray(self, filename):
        return numpy.zeros((20,20), numpy.uint32)
    def PyControl_connect(self, widget, object, property):
        pass
    def PyControl_setFloatValue(self, widget, value):
        pass
    def PyControl_setIntegerValue(self, widget, value):
        pass
    def PyControl_setStringValue(self, widget, value):
        pass
    def PyControl_setTitle(self, widget, title):
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
    def DocumentWindow_loadQmlWidget(self, document_window, filename, panel, context_properties):
        return (document_window, filename, panel, context_properties)
    def Splitter_restoreState(self, splitter, identifier):
        pass
    def Splitter_saveState(self, splitter, identifier):
        pass
    def Widget_addOverlay(self, widget, overlay):
        pass
    def Widget_addSpacing(self, container, spacing):
        pass
    def Widget_addStretch(self, container):
        pass
    def Widget_addWidget(self, widget, child_widget):
        pass
    def Widget_adjustSize(self, widget):
        pass
    def Widget_getWidgetProperty(self, widget, property):
        return None
    def Widget_insertWidget(self, widget, child_widget, index):
        pass
    def Widget_loadIntrinsicWidget(self, type):
        return (type)
    def Widget_removeAll(self, container):
        pass
    def Widget_removeDockWidget(self, document_controller, dock_widget):
        pass
    def Widget_removeWidget(self, widget):
        pass
    def Widget_setContextProperty(self, widget, property, value):
        pass
    def Widget_setWidgetProperty(self, widget, key, value):
        pass
    def Widget_unloadWidget(self, widget):
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
