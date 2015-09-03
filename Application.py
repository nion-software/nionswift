# futures
from __future__ import absolute_import

# standard libraries
import copy
import gettext
import logging
import os
import sys

# third party libraries
# None

# local libraries
from nion.swift import CalculationPanel
from nion.swift import DataPanel
from nion.swift import DocumentController
from nion.swift import FilterPanel
from nion.swift import HistogramPanel
from nion.swift import Inspector
from nion.swift import Panel
from nion.swift import Task
from nion.swift import Test
from nion.swift import ToolbarPanel
from nion.swift import Workspace
from nion.swift import SessionPanel
from nion.swift import NDataHandler
from nion.swift import InfoPanel
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import HardwareSource
from nion.swift.model import PlugInManager
from nion.swift.model import Storage
from nion.ui import Dialog

_ = gettext.gettext

app = None


# facilitate bootstrapping the application
class Application(object):

    def __init__(self, ui, set_global=True, resources_path=None):
        global app

        self.ui = ui
        self.ui.persistence_root = "3"  # sets of preferences
        self.resources_path = resources_path
        self.version_str = "0.5.6"

        if set_global:
            app = self  # hack to get the single instance set. hmm. better way?

        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        logger.addHandler(logging.StreamHandler())

        self.__document_controllers = []
        self.__menu_handlers = []

        self.__did_close_event_listeners = dict()
        self.__create_new_event_listeners = dict()

        workspace_manager = Workspace.WorkspaceManager()
        workspace_manager.register_panel(SessionPanel.SessionPanel, "session-panel", _("Session"), ["left", "right"], "right", {"width": 320, "height": 80})
        workspace_manager.register_panel(DataPanel.DataPanel, "data-panel", _("Data Panel"), ["left", "right"], "left", {"width": 320, "height": 400})
        workspace_manager.register_panel(HistogramPanel.HistogramPanel, "histogram-panel", _("Histogram"), ["left", "right"], "right", {"width": 320, "height": 140})
        workspace_manager.register_panel(InfoPanel.InfoPanel, "info-panel", _("Info"), ["left", "right"], "right", {"width": 320, "height": 60})
        workspace_manager.register_panel(Inspector.InspectorPanel, "inspector-panel", _("Inspector"), ["left", "right"], "right", {"width": 320})
        workspace_manager.register_panel(Task.TaskPanel, "task-panel", _("Task Panel"), ["left", "right"], "right", {"width": 320})
        workspace_manager.register_panel(Panel.OutputPanel, "output-panel", _("Output"), ["bottom"], "bottom")
        workspace_manager.register_panel(Panel.ConsolePanel, "console-panel", _("Console"), ["bottom"], "bottom")
        workspace_manager.register_panel(ToolbarPanel.ToolbarPanel, "toolbar-panel", _("Toolbar"), ["top"], "top", {"height": 30})
        workspace_manager.register_panel(CalculationPanel.CalculationPanel, "calculation-panel", _("Calculation"), ["left", "right"], "left", {"width": 320, "height": 8})
        workspace_manager.register_filter_panel(FilterPanel.FilterPanel)

    def initialize(self):
        # load plug-ins
        PlugInManager.load_plug_ins(self, get_root_dir())

    def deinitialize(self):
        # shut down hardware source manager, unload plug-ins, and really exit ui
        HardwareSource.HardwareSourceManager().close()
        PlugInManager.unload_plug_ins()
        # with open(os.path.join(self.ui.get_data_location(), "PythonConfig.ini"), 'w') as f:
        #     f.write(sys.prefix + '\n')
        self.ui.close()

    def exit(self):
        # close all document windows, but can be started again.
        for did_close_event_listener in self.__did_close_event_listeners.values():
            did_close_event_listener.close()
        for create_new_event_listener in self.__create_new_event_listeners.values():
            create_new_event_listener.close()
        for document_controller in copy.copy(self.__document_controllers):
            document_controller.close()
            self.__document_controllers.remove(document_controller)
        # document model is reference counted; when the no document controller holds a reference to the
        # document model, it will be closed.

    def choose_workspace(self):
        documents_dir = self.ui.get_document_location()
        workspace_dir, directory = self.ui.get_existing_directory_dialog(_("Choose Library Folder"), documents_dir)
        return workspace_dir

    def migrate_library(self, workspace_dir, library_path, welcome_message=True):
        """ Migrate library to latest version. """
        library_storage = DocumentModel.FilePersistentStorage(library_path, create=False)
        version = library_storage.get_version()
        if welcome_message:
            logging.debug("Library at version %s.", version)

    def start(self, skip_choose=False, fixed_workspace_dir=None):
        """
            Start a new document model.

            Looks for workspace_location persistent string. If it doesn't find it, uses a default
            workspace location.

            Then checks to see if that workspace exists. If not and if skip_choose has not been
            set to True, asks the user for a workspace location. User may choose new folder or
            existing location.

            Creates workspace in location if it doesn't exist.

            Migrates database to latest version.

            Creates document model, resources path, etc.
        """
        if fixed_workspace_dir:
            workspace_dir = fixed_workspace_dir
        else:
            documents_dir = self.ui.get_document_location()
            workspace_dir = os.path.join(documents_dir, "Nion Swift Libraries")
            workspace_dir = self.ui.get_persistent_string("workspace_location", workspace_dir)
        library_filename = "Nion Swift Workspace.nslib"
        cache_filename = "Nion Swift Cache.nscache"
        library_path = os.path.join(workspace_dir, library_filename)
        cache_path = os.path.join(workspace_dir, cache_filename)
        if not skip_choose and not os.path.exists(library_path):
            workspace_dir = self.choose_workspace()
            if not workspace_dir:
                return False
            library_path = os.path.join(workspace_dir, library_filename)
            cache_path = os.path.join(workspace_dir, cache_filename)
        welcome_message = fixed_workspace_dir is None
        if os.path.exists(library_path):
            self.migrate_library(workspace_dir, library_path, welcome_message)
        self.workspace_dir = workspace_dir
        data_reference_handler = DataReferenceHandler(workspace_dir)
        create_new_document = not os.path.exists(library_path)
        if create_new_document:
            if welcome_message:
                logging.debug("Creating new document: %s", library_path)
            library_storage = DocumentModel.FilePersistentStorage(library_path)
        else:
            if welcome_message:
                logging.debug("Using existing document %s", library_path)
            library_storage = DocumentModel.FilePersistentStorage(library_path, create=False)
        managed_object_context = DocumentModel.ManagedDataItemContext(data_reference_handler, False, False)
        counts = managed_object_context.read_data_items_version_stats()
        if counts[2] > 0:

            assert fixed_workspace_dir is None

            def do_ignore():
                self.continue_start(cache_path, create_new_document, data_reference_handler, library_storage, workspace_dir, True)

            def do_upgrade():
                self.continue_start(cache_path, create_new_document, data_reference_handler, library_storage, workspace_dir, False)

            class UpgradeDialog(Dialog.ActionDialog):
                def __init__(self, ui):
                    super(UpgradeDialog, self).__init__(ui)

                    self.add_button(_("Upgrade"), do_upgrade)

                    self.add_button(_("Ignore"), do_ignore)

                    column = self.ui.create_column_widget()
                    column.add_spacing(12)

                    row_one = self.ui.create_row_widget()
                    row_one.add_spacing(13)
                    row_one.add(self.ui.create_label_widget("{0} data items need to be updated.".format(counts[2])))
                    row_one.add_stretch()
                    row_one.add_spacing(13)
                    column.add(row_one)
                    column.add_spacing(4)

                    row_two = self.ui.create_row_widget()
                    row_two.add_spacing(13)
                    row_two.add(self.ui.create_label_widget("{0} data items are newer than this version and won't be loaded.".format(counts[1])))
                    row_two.add_stretch()
                    row_two.add_spacing(13)
                    column.add(row_two)
                    column.add_spacing(4)

                    row_three = self.ui.create_row_widget()
                    row_three.add_spacing(13)
                    row_three.add(self.ui.create_label_widget("{0} data items match this version.".format(counts[0])))
                    row_three.add_stretch()
                    row_three.add_spacing(13)
                    column.add(row_three)
                    column.add_spacing(4)

                    row_three = self.ui.create_row_widget()
                    row_three.add_spacing(13)
                    row_three.add(self.ui.create_label_widget("If you choose to upgrade, the upgraded items will not\nbe able to be loaded in earlier versions.".format(counts[0])))
                    row_three.add_stretch()
                    row_three.add_spacing(13)
                    column.add_spacing(8)
                    column.add(row_three)
                    column.add_spacing(4)

                    column.add_spacing(12)
                    column.add_stretch()

                    self.content.add(column)

            upgrade_dialog = UpgradeDialog(self.ui)
            upgrade_dialog.show()

        else:
            self.continue_start(cache_path, create_new_document, data_reference_handler, library_storage, workspace_dir, True, welcome_message=welcome_message)

        return True

    def continue_start(self, cache_path, create_new_document, data_reference_handler, library_storage, workspace_dir, ignore_older_files, welcome_message=True):
        storage_cache = Storage.DbStorageCache(cache_path)
        document_model = DocumentModel.DocumentModel(library_storage=library_storage,
                                                     data_reference_handler=data_reference_handler,
                                                     storage_cache=storage_cache, ignore_older_files=ignore_older_files)
        document_model.create_default_data_groups()
        document_model.start_dispatcher()
        PlugInManager.notify_modules("document_model_loaded", self, document_model)
        document_controller = self.create_document_controller(document_model, "library")
        if self.resources_path is not None:
            document_model.create_sample_images(self.resources_path)
        workspace_history = self.ui.get_persistent_object("workspace_history", list())
        if workspace_dir in workspace_history:
            workspace_history.remove(workspace_dir)
        workspace_history.insert(0, workspace_dir)
        self.ui.set_persistent_object("workspace_history", workspace_history)
        self.ui.set_persistent_string("workspace_location", workspace_dir)
        if welcome_message:
            logging.info("Welcome to Nion Swift.")
        if create_new_document and len(document_model.data_items) > 0:
            document_controller.selected_display_panel.set_displayed_data_item(document_model.data_items[0])
            document_controller.selected_display_panel.perform_action("set_fill_mode")

    def stop(self):
        # program is really stopping, clean up.
        self.deinitialize()

    def get_recent_workspace_file_paths(self):
        workspace_history = self.ui.get_persistent_object("workspace_history", list())
        # workspace_history = ["/Users/cmeyer/Movies/Crap/Test1", "/Users/cmeyer/Movies/Crap/Test7_new"]
        return [file_path for file_path in workspace_history if file_path != self.workspace_dir and os.path.exists(file_path)]

    def switch_library(self, recent_workspace_file_path, skip_choose=False, fixed_workspace_dir=None):
        self.exit()
        self.ui.set_persistent_string("workspace_location", recent_workspace_file_path)
        self.start(skip_choose=skip_choose, fixed_workspace_dir=fixed_workspace_dir)

    def other_libraries(self):
        workspace_dir = self.choose_workspace()
        if workspace_dir:
            self.switch_library(workspace_dir, skip_choose=True)

    def new_library(self):
        workspace_dir = self.choose_workspace()
        if workspace_dir:
            self.switch_library(workspace_dir, skip_choose=True)

    def clear_libraries(self):
        self.ui.remove_persistent_key("workspace_history")

    def create_document_controller(self, document_model, workspace_id, data_item=None):
        document_controller = DocumentController.DocumentController(self.ui, document_model, workspace_id=workspace_id, app=self)
        self.__did_close_event_listeners[document_controller] = document_controller.did_close_event.listen(self.__document_controller_did_close)
        self.__create_new_event_listeners[document_controller] = document_controller.create_new_document_controller_event.listen(self.create_document_controller)
        self.__register_document_controller(document_controller)
        # attempt to set data item / group
        if data_item:
            display_panel = document_controller.selected_display_panel
            if display_panel:
                display_panel.set_displayed_data_item(data_item)
        document_controller.document_window.show()
        return document_controller

    def __document_controller_did_close(self, document_controller):
        self.__did_close_event_listeners[document_controller].close()
        del self.__did_close_event_listeners[document_controller]
        self.__create_new_event_listeners[document_controller].close()
        del self.__create_new_event_listeners[document_controller]
        self.__document_controllers.remove(document_controller)

    def __register_document_controller(self, document_window):
        assert document_window not in self.__document_controllers
        self.__document_controllers.append(document_window)
        # when a document window is registered, tell the menu handlers
        for menu_handler in self.__menu_handlers:  # use 'handler' to avoid name collision
            menu_handler(document_window)
        return document_window

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

    def register_computation(self, computation_fn):
        DataItem.register_computation(computation_fn)

    def unregister_computation(self, computation_fn):
        DataItem.unregister_computation(computation_fn)

    def __get_menu_handlers(self):
        return copy.copy(self.__menu_handlers)
    menu_handlers = property(__get_menu_handlers)

    def run_all_tests(self):
        Test.run_all_tests()


class DataReferenceHandler(object):

    def __init__(self, workspace_dir):
        self.workspace_dir = workspace_dir
        self.__data_dir = os.path.join(self.workspace_dir, "Nion Swift Data")
        self.__file_handler = NDataHandler.NDataHandler(self.__data_dir)
        assert self.workspace_dir

    def find_data_item_tuples(self):
        tuples = []
        #logging.debug("data_dir %s", self.__data_dir)
        for root, dirs, files in os.walk(self.__data_dir):
            absolute_file_paths = [os.path.join(root, data_file) for data_file in files]
            for data_file in filter(self.__file_handler.is_matching, absolute_file_paths):
                reference_type = "relative_file"
                reference = self.__file_handler.get_reference(data_file)
                try:
                    item_uuid, properties = self.__file_handler.read_properties(reference)
                    tuples.append((item_uuid, properties, reference_type, reference))
                except Exception as e:
                    logging.error("Exception reading file: %s", data_file)
                    logging.error(str(e))
                #logging.debug("ONE %s", (uuid.UUID(item_uuid_str), properties, reference_type, reference))
        return tuples

    def load_data_reference(self, reference_type, reference):
        #logging.debug("load data reference %s %s", reference_type, reference)
        if reference_type == "relative_file":
            return self.__file_handler.read_data(reference)
        return None

    def write_data_reference(self, data, reference_type, reference, file_datetime):
        #logging.debug("write data reference %s %s", reference_type, reference)
        if reference_type == "relative_file":
            self.__file_handler.write_data(reference, data, file_datetime)
        else:
            logging.debug("Cannot write master data %s %s", reference_type, reference)
            raise NotImplementedError()

    def write_properties(self, properties, reference_type, reference, file_datetime):
        #logging.debug("write data reference %s %s", reference_type, reference)
        if reference_type == "relative_file":
            self.__file_handler.write_properties(reference, properties, file_datetime)
        else:
            logging.debug("Cannot write properties %s %s", reference_type, reference)
            raise NotImplementedError()

    def remove_data_reference(self, reference_type, reference):
        #logging.debug("remove data reference %s %s", reference_type, reference)
        if reference_type == "relative_file":
            self.__file_handler.remove(reference)
        else:
            logging.debug("Cannot remove master data %s %s", reference_type, reference)
            raise NotImplementedError()


def get_root_dir():
    # in Windows, we generally have
    # |   NionImaging.exe
    # +---nion
    # |   |   init.py
    # |   \---swift
    # |       |   ...
    # |       |   PluginManager.py
    # |       |   ...
    # +---PlugIns
    # |   \---PluginOne
    # |       |   init.py
    # |       ...
    #
    # and under Mac
    # +---MacOs
    # |       NionImaging.app
    # +---Resources
    # |   \---nion
    # |       |   init.py
    # |       \---swift
    # |           |   ...
    # |           |   PluginManager.py
    # |           |   ...
    # +---PlugIns
    # |   \---PluginOne
    # |       |   init.py
    # |       ...
    root_dir = os.path.dirname(os.path.realpath(__file__))
    path_ascend_count = 2
    for i in range(path_ascend_count):
        root_dir = os.path.dirname(root_dir)
    return root_dir


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
