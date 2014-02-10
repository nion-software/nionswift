# standard libraries
import calendar
import collections
import copy
import datetime
import gettext
import importlib
import logging
import os
import cPickle as pickle
import sqlite3
import sys
import time
import uuid

# third party libraries
import numpy

# local libraries
from nion.swift import DataItem
from nion.swift import DataPanel
from nion.swift import DocumentController
from nion.swift import DocumentModel
from nion.swift import FilterPanel
from nion.swift import HardwareSource
from nion.swift import HistogramPanel
from nion.swift import ImagePanel
from nion.swift import Inspector
from nion.swift import Panel
from nion.swift import PlugInManager
from nion.swift import Session
from nion.swift import Storage
from nion.swift import Task
from nion.swift import Test
from nion.swift import Utility
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
        workspace_manager.register_panel(Session.SessionPanel, "session-panel", _("Session"), ["left", "right"], "right", {"width": 320, "height": 80})
        workspace_manager.register_panel(DataPanel.DataPanel, "data-panel", _("Data Panel"), ["left", "right"], "left", {"width": 320, "height": 400})
        workspace_manager.register_panel(HistogramPanel.HistogramPanel, "histogram-panel", _("Histogram"), ["left", "right"], "right", {"width": 320, "height": 80})
        workspace_manager.register_panel(ImagePanel.InfoPanel, "info-panel", _("Info"), ["left", "right"], "right", {"width": 320, "height": 96})
        workspace_manager.register_panel(Inspector.InspectorPanel, "inspector-panel", _("Inspector"), ["left", "right"], "right", {"width": 320})
        workspace_manager.register_panel(Task.TaskPanel, "task-panel", _("Task Panel"), ["left", "right"], "right", {"width": 320})
        workspace_manager.register_panel(Inspector.ProcessingPanel, "processing-panel", _("Processing Panel"), ["left", "right"], "right", {"width": 320})
        workspace_manager.register_panel(Panel.OutputPanel, "output-panel", _("Output"), ["bottom"], "bottom")
        workspace_manager.register_panel(Panel.ConsolePanel, "console-panel", _("Console"), ["bottom"], "bottom")
        workspace_manager.register_filter_panel(FilterPanel.FilterPanel)

    def initialize(self):
        PlugInManager.loadPlugIns()
        Test.load_tests()  # after plug-ins are loaded

    def start(self):
        documents_dir = self.ui.get_document_location()
        workspace_dir = os.path.join(documents_dir, "Nion Swift Workspace")
        workspace_dir = self.ui.get_persistent_string("workspace_location", workspace_dir)
        db_filename = os.path.join(workspace_dir, "Nion Swift Workspace.nswrk")
        cache_filename = os.path.join(workspace_dir, "Nion Swift Cache.nscache")
        create_new_document = not os.path.exists(db_filename)
        if create_new_document:
            workspace_dir, directory = self.ui.get_existing_directory_dialog(_("Choose Workspace Location"), documents_dir)
            if not workspace_dir:
                return False
            db_filename = os.path.join(workspace_dir, "Nion Swift Workspace.nswrk")
            cache_filename = os.path.join(workspace_dir, "Nion Swift Cache.nscache")
            create_new_document = not os.path.exists(db_filename)
        data_reference_handler = DataReferenceHandler(workspace_dir)
        if create_new_document:
            logging.debug("Creating new document: %s", db_filename)
            datastore = Storage.DbDatastoreProxy(data_reference_handler, db_filename)
            storage_cache = Storage.DbStorageCache(cache_filename)
            document_model = DocumentModel.DocumentModel(datastore, storage_cache)
            document_model.create_default_data_groups()
            document_model.create_test_images()
        else:
            logging.debug("Using existing document %s", db_filename)
            datastore = Storage.DbDatastoreProxy(data_reference_handler, db_filename, create=False)
            version = datastore.get_version()
            logging.debug("Database at version %s.", version)
            c = datastore.conn.cursor()
            if version == 0:
                logging.debug("Database too old, version %s", version)
                sys.exit()
            if version == 1:
                # apply a backwards compatible change
                c.execute("SELECT uuid FROM nodes WHERE type='data-item'")
                data_item_uuids = []
                for row in c.fetchall():
                    data_item_uuids.append(row[0])
                data_item_uuids_to_update = []
                for data_item_uuid in data_item_uuids:
                    c.execute("SELECT COUNT(*) FROM items WHERE parent_uuid=? AND key='intrinsic_intensity_calibration'", (data_item_uuid, ))
                    if c.fetchone()[0] == 0:
                        c.execute("SELECT COUNT(*) FROM data WHERE uuid=? AND key='master_data'", (data_item_uuid, ))
                        if c.fetchone()[0] > 0:
                            data_item_uuids_to_update.append(data_item_uuid)
                if len(data_item_uuids_to_update) > 0:
                    logging.debug("Update data version 1 (%s/%s intensity_calibration)", len(data_item_uuids_to_update), len(data_item_uuids))
                for data_item_uuid in data_item_uuids_to_update:
                    # create an empty 'intrinsic_intensity_calibration' for each data item
                    calibration_uuid = str(uuid.uuid4())
                    c.execute("INSERT INTO items (parent_uuid, key, item_uuid) VALUES (?, 'intrinsic_intensity_calibration', ?)", (str(data_item_uuid), calibration_uuid))
                    c.execute("INSERT INTO nodes (uuid, type, refcount) VALUES (?, 'calibration', 1)", (str(calibration_uuid), ))
            if version == 1:
                logging.debug("Updating database from version 1 to version 2.")
                c.execute("SELECT uuid, type FROM nodes WHERE type like '%-operation'")
                operation_uuids = []
                operation_types = {}
                for row in c.fetchall():
                    operation_uuids.append(row[0])
                    operation_types[row[0]] = row[1]
                c.execute("UPDATE nodes SET type='operation' WHERE type like '%-operation'")
                for operation_uuid in operation_uuids:
                    operation_id_data = sqlite3.Binary(pickle.dumps(operation_types[operation_uuid], pickle.HIGHEST_PROTOCOL))
                    c.execute("INSERT INTO properties (uuid, key, value) VALUES (?, 'operation_id', ?)", (str(operation_uuid), operation_id_data))
                c.execute("UPDATE version SET version = ?", (2, ))
                version = 2
            if version == 2:
                logging.debug("Updating database from version 2 to version 3.")
                c.execute("SELECT uuid FROM nodes WHERE type='document'")
                document_uuid = c.fetchone()[0]
                c.execute("SELECT uuid FROM nodes WHERE type='data-item'")
                data_item_uuids = []
                for row in c.fetchall():
                    data_item_uuids.append(row[0])
                index = 0
                for data_item_uuid in data_item_uuids:
                    c.execute("SELECT COUNT(*) FROM data WHERE uuid=?", (data_item_uuid, ))
                    count = c.fetchone()[0]
                    if count == 1:
                        c.execute("INSERT INTO relationships (parent_uuid, key, item_index, item_uuid) VALUES (?, 'data_items', ?, ?)", (document_uuid, index, data_item_uuid))
                        c.execute("UPDATE nodes SET refcount=refcount+1 WHERE uuid = ?", (data_item_uuid, ))
                        index += 1
                c.execute("UPDATE version SET version = ?", (3, ))
                version = 3
            if version == 3:
                logging.debug("Updating database from version 3 to version 4.")
                c.execute("CREATE TABLE IF NOT EXISTS data_references(uuid STRING, key STRING, shape BLOB, dtype BLOB, reference_type STRING, reference STRING, PRIMARY KEY(uuid, key))")
                c.execute("INSERT INTO data_references (uuid, key, shape, dtype, reference_type, reference) SELECT uuid, key, shape, dtype, 'relative_file', relative_file FROM data")
                c.execute("DROP TABLE data")
                c.execute("UPDATE version SET version = ?", (4, ))
                datastore.conn.commit()
                c.execute("VACUUM")
                version = 4
            if version > 4:
                logging.debug("Database too new, version %s", version)
                sys.exit()
            datastore.conn.commit()
            datastore.check_integrity()
            storage_cache = Storage.DbStorageCache(cache_filename)
            document_model = DocumentModel.DocumentModel(datastore, storage_cache)
            document_model.create_default_data_groups()
        document_controller = self.create_document_controller(document_model, "library")
        self.ui.set_persistent_string("workspace_location", workspace_dir)
        logging.info("Welcome to Nion Swift.")
        return True

    def create_document_controller(self, document_model, workspace_id, data_panel_selection=None):
        document_controller = DocumentController.DocumentController(self.ui, document_model, workspace_id=workspace_id)
        document_controller.add_listener(self)
        self.register_document_controller(document_controller)
        # attempt to set data item / group
        if data_panel_selection:
            image_panel = document_controller.selected_image_panel
            if image_panel:
                image_panel.data_item = data_panel_selection.data_item
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


class DataReferenceHandler(object):

    def __init__(self, workspace_dir):
        self.workspace_dir = workspace_dir

    def load_data_reference(self, reference_type, reference):
        #logging.debug("load data reference %s %s", reference_type, reference)
        if reference_type == "relative_file":
            assert self.workspace_dir
            data_file_path = reference
            absolute_file_path = os.path.join(self.workspace_dir, "Nion Swift Data", data_file_path)
            #logging.debug("READ data file %s for %s", absolute_file_path, key)
            if os.path.isfile(absolute_file_path):
                return pickle.load(open(absolute_file_path, "rb"))
        return None

    def write_data_reference(self, data, reference_type, reference, file_datetime):
        #logging.debug("write data reference %s %s", reference_type, reference)
        assert data is not None
        if reference_type == "relative_file":
            data_file_path = reference
            data_file_datetime = file_datetime
            data_directory = os.path.join(self.workspace_dir, "Nion Swift Data")
            absolute_file_path = os.path.join(self.workspace_dir, "Nion Swift Data", data_file_path)
            #logging.debug("WRITE data file %s for %s", absolute_file_path, key)
            Storage.db_make_directory_if_needed(os.path.dirname(absolute_file_path))
            pickle.dump(data, open(absolute_file_path, "wb"), pickle.HIGHEST_PROTOCOL)
            # convert to utc time. this is temporary until datetime is cleaned up (again) and we can get utc directly from datetime.
            timestamp = calendar.timegm(data_file_datetime.timetuple()) + (datetime.datetime.utcnow() - datetime.datetime.now()).total_seconds()
            os.utime(absolute_file_path, (time.time(), timestamp))
        else:
            logging.debug("Cannot write master data %s %s", reference_type, reference)
            raise NotImplementedError()

    def remove_data_reference(self, reference_type, reference):
        #logging.debug("remove data reference %s %s", reference_type, reference)
        if reference_type == "relative_file":
            data_file_path = reference
            data_directory = os.path.join(self.workspace_dir, "Nion Swift Data")
            absolute_file_path = os.path.join(self.workspace_dir, "Nion Swift Data", data_file_path)
            #logging.debug("DELETE data file %s", absolute_file_path)
            if os.path.isfile(absolute_file_path):
                os.remove(absolute_file_path)


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
