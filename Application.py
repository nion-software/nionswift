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
        workspace_manager.registerPanel(ImagePanel.ImagePanel, "image-panel", _("Image Panel"), ["central"], "central")
        workspace_manager.registerPanel(DataPanel.DataPanel, "data-panel", _("Data Panel"), ["left", "right"], "left", {"width": 300, "height": 400})
        workspace_manager.registerPanel(HistogramPanel.HistogramPanel, "histogram-panel", _("Histogram"), ["left", "right"], "right", {"width": 300, "height": 80})
        workspace_manager.registerPanel(ImagePanel.InfoPanel, "info-panel", _("Info"), ["left", "right"], "right", {"width": 300, "height": 96})
        workspace_manager.registerPanel(ImagePanel.InspectorPanel, "inspector-panel", _("Inspector"), ["left", "right"], "right", {"width": 300, "height": 320})
        workspace_manager.registerPanel(Inspector.ProcessingPanel, "processing-panel", _("Processing Panel"), ["left", "right"], "right", {"width": 300})
        workspace_manager.registerPanel(Panel.OutputPanel, "output-panel", _("Output"), ["bottom"], "bottom")
        workspace_manager.registerPanel(Panel.ConsolePanel, "console-panel", _("Console"), ["bottom"], "bottom")

    def initialize(self):
        PlugInManager.loadPlugIns()
        Test.load_tests()  # after plug-ins are loaded

    def start(self):
        documents_dir = self.ui.get_data_location()
        filename = os.path.join(documents_dir, "Swift Workspace.nswrk")
        #filename = ":memory:"
        create_new_document = not os.path.exists(filename)
        if create_new_document:
            logging.debug("Creating new document: %s", filename)
            storage_writer = Storage.DbStorageWriter(filename, create=True)
            document_model = DocumentModel.DocumentModel(storage_writer)
            document_model.create_default_data_groups()
            document_model.create_test_images()
        else:
            logging.debug("Using existing document %s", filename)
            storage_writer = Storage.DbStorageWriter(filename)
            storage_reader = Storage.DbStorageReader(filename)
            document_model = DocumentModel.DocumentModel(storage_writer, storage_reader)
            document_model.create_default_data_groups()
        document_controller = self.create_document_controller(document_model)
        logging.info("Welcome to Nion Swift.")
        return document_controller

    def create_document_controller(self, document_model):
        document_controller = DocumentController.DocumentController(self.ui, document_model)
        document_controller.add_listener(self)
        self.register_document_controller(document_controller)
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
