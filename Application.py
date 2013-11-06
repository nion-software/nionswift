# standard libraries
import copy
import gettext
import importlib
import logging
import os
import sys

# third party libraries
import numpy

# local libraries
from nion.swift import DataPanel
from nion.swift import DocumentController
from nion.swift import DocumentModel
from nion.swift import HardwareSource
from nion.swift import HistogramPanel
from nion.swift import ImagePanel
from nion.swift import Inspector
from nion.swift import Panel
from nion.swift import PlugInManager
from nion.swift import Storage
from nion.swift import Test
from nion.swift import Workspace

_ = gettext.gettext

app = None


# facilitate bootstrapping the application
class Application(object):
    def __init__(self, ui, set_global=True):
        global app

        self.ui = ui

        if set_global:
            app = self  # hack to get the single instance set. hmm. better way?

        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        logger.addHandler(logging.StreamHandler())

        self.__document_controllers = []
        self.__menu_handlers = []

        workspace_manager = Workspace.WorkspaceManager()
        workspace_manager.register_panel(ImagePanel.ImagePanel, "image-panel", _("Image Panel"), ["central"], "central")
        workspace_manager.register_panel(DataPanel.DataPanel, "data-panel", _("Data Panel"), ["left", "right"], "left", {"width": 300, "height": 400})
        workspace_manager.register_panel(HistogramPanel.HistogramPanel, "histogram-panel", _("Histogram"), ["left", "right"], "right", {"width": 300, "height": 80})
        workspace_manager.register_panel(ImagePanel.InfoPanel, "info-panel", _("Info"), ["left", "right"], "right", {"width": 300, "height": 96})
        workspace_manager.register_panel(Inspector.InspectorPanel, "inspector-panel", _("Inspector"), ["left", "right"], "right", {"width": 300, "height": 320})
        workspace_manager.register_panel(Inspector.ProcessingPanel, "processing-panel", _("Processing Panel"), ["left", "right"], "right", {"width": 300})
        workspace_manager.register_panel(Panel.OutputPanel, "output-panel", _("Output"), ["bottom"], "bottom")
        workspace_manager.register_panel(Panel.ConsolePanel, "console-panel", _("Console"), ["bottom"], "bottom")

    def initialize(self):
        PlugInManager.loadPlugIns()
        Test.load_tests()  # after plug-ins are loaded

    def start(self):
        documents_dir = self.ui.get_data_location()
        db_filename = os.path.join(documents_dir, "Swift Workspace.nswrk")
        cache_filename = os.path.join(documents_dir, "Swift Cache.nscache")
        create_new_document = not os.path.exists(db_filename)
        if create_new_document:
            logging.debug("Creating new document: %s", db_filename)
            storage_writer = Storage.DbStorageWriter(db_filename, cache_filename, create=True)
            storage_cache = Storage.DictStorageCache()
            document_model = DocumentModel.DocumentModel(storage_writer, storage_cache)
            document_model.create_default_data_groups()
            document_model.create_test_images()
        else:
            logging.debug("Using existing document %s", db_filename)
            storage_writer = Storage.DbStorageWriter(db_filename, cache_filename)
            storage_reader = Storage.DbStorageReader(db_filename)
            storage_cache = Storage.DictStorageCache()
            document_model = DocumentModel.DocumentModel(storage_writer, storage_cache, storage_reader)
            document_model.create_default_data_groups()
        document_controller = self.create_document_controller(document_model, "library")
        logging.info("Welcome to Nion Swift.")
        return document_controller

    def create_document_controller(self, document_model, workspace_id, data_panel_selection=None):
        document_controller = DocumentController.DocumentController(self.ui, document_model, workspace_id=workspace_id)
        document_controller.add_listener(self)
        self.register_document_controller(document_controller)
        # attempt to set data item / group
        if data_panel_selection:
            image_panel = document_controller.selected_image_panel
            if image_panel:
                image_panel.data_panel_selection = data_panel_selection
        document_controller.document_window.show()
        return document_controller

    def document_controller_did_close(self, document_controller):
        document_controller.remove_listener(self)
        self.unregister_document_controller(document_controller)

    def register_document_controller(self, document_window):
        assert document_window not in self.__document_controllers
        self.__document_controllers.append(document_window)
        # when a document window is registered, tell the menu handlers
        for menu_handler in self.__menu_handlers:  # use 'handler' to avoid name collision
            menu_handler(document_window)
        return document_window
    def unregister_document_controller(self, document_controller):
        self.__document_controllers.remove(document_controller)
    def __get_document_controllers(self):
        return copy.copy(self.__document_controllers)
    document_controllers = property(__get_document_controllers)

    def register_menu_handler(self, new_menu_handler):
        assert new_menu_handler not in self.__menu_handlers
        self.__menu_handlers.append(new_menu_handler)
        # when a menu handler is registered, let it immediately know about existing menu handlers
        for document_controller in self.__document_controllers:
            new_menu_handler(document_controller)
        # return the menu handler so that it can be used to unregister (think: lambda)
        return new_menu_handler
    def unregister_menu_handler(self, menu_handler):
        self.__menu_handlers.remove(menu_handler)
    def __get_menu_handlers(self):
        return copy.copy(self.__menu_handlers)
    menu_handlers = property(__get_menu_handlers)

    def run_all_tests(self):
        Test.run_all_tests()


def print_stack_all():
    import traceback
    logging.debug("*** STACKTRACE - START ***")
    code = []
    for threadId, stack in sys._current_frames().items():
        sub_code = []
        sub_code.append("# ThreadID: %s" % threadId)
        for filename, lineno, name, line in traceback.extract_stack(stack):
            sub_code.append('File: "%s", line %d, in %s' % (filename, lineno, name))
            if line:
                sub_code.append("  %s" % (line.strip()))
        if not sub_code[-1].endswith("waiter.acquire()") and \
           not sub_code[-1].endswith("traceback.extract_stack(stack):") and \
           not sub_code[-1].endswith("self.__cond.release()") and \
           not sub_code[-1].endswith("_sleep(delay)") and \
           not "thread_event.wait" in sub_code[-1] and \
           not "time.sleep" in sub_code[-1] and \
           not "_wait_semaphore.acquire" in sub_code[-1]:
            code.extend(sub_code)
    for line in code:
            logging.debug(line)
    logging.debug("*** STACKTRACE - END ***")


def sample_stack_all(count=10, interval=0.1):
    import time
    for i in range(count):
        print_stack_all()
        time.sleep(interval)
