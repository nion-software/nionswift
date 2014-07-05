# standard libraries
import calendar
import copy
import datetime
import gettext
import json
import logging
import os
import cPickle as pickle
import sqlite3
import struct
import sys
import time
import uuid

# third party libraries
import numpy

# local libraries
from nion.swift import DataPanel
from nion.swift import DocumentController
from nion.swift import FilterPanel
from nion.swift import HistogramPanel
from nion.swift import ImagePanel
from nion.swift import Inspector
from nion.swift import Panel
from nion.swift import Task
from nion.swift import Test
from nion.swift import ToolbarPanel
from nion.swift import Workspace
from nion.swift import SessionPanel
from nion.swift import NDataHandler
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import ImportExportManager
from nion.swift.model import PlugInManager
from nion.swift.model import Storage
from nion.swift.model import Utility

_ = gettext.gettext

app = None


# facilitate bootstrapping the application
class Application(object):

    def __init__(self, ui, set_global=True, resources_path=None):
        global app

        self.ui = ui
        self.resources_path = resources_path
        self.version_str = "0.3.0"

        if set_global:
            app = self  # hack to get the single instance set. hmm. better way?

        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        logger.addHandler(logging.StreamHandler())

        self.__document_controllers = []
        self.__menu_handlers = []

        workspace_manager = Workspace.WorkspaceManager()
        workspace_manager.register_panel(ImagePanel.ImagePanel, "image-panel", _("Image Panel"), ["central"], "central")
        workspace_manager.register_panel(SessionPanel.SessionPanel, "session-panel", _("Session"), ["left", "right"], "right", {"width": 320, "height": 80})
        workspace_manager.register_panel(DataPanel.DataPanel, "data-panel", _("Data Panel"), ["left", "right"], "left", {"width": 320, "height": 400})
        workspace_manager.register_panel(HistogramPanel.HistogramPanel, "histogram-panel", _("Histogram"), ["left", "right"], "right", {"width": 320, "height": 140})
        workspace_manager.register_panel(ImagePanel.InfoPanel, "info-panel", _("Info"), ["left", "right"], "right", {"width": 320, "height": 60})
        workspace_manager.register_panel(Inspector.InspectorPanel, "inspector-panel", _("Inspector"), ["left", "right"], "right", {"width": 320})
        workspace_manager.register_panel(Task.TaskPanel, "task-panel", _("Task Panel"), ["left", "right"], "right", {"width": 320})
        workspace_manager.register_panel(Panel.OutputPanel, "output-panel", _("Output"), ["bottom"], "bottom")
        workspace_manager.register_panel(Panel.ConsolePanel, "console-panel", _("Console"), ["bottom"], "bottom")
        workspace_manager.register_panel(ToolbarPanel.ToolbarPanel, "toolbar-panel", _("Toolbar"), ["top"], "top", {"height": 30})
        workspace_manager.register_filter_panel(FilterPanel.FilterPanel)

    def initialize(self):
        PlugInManager.load_plug_ins(self, get_root_dir())
        Test.load_tests()  # after plug-ins are loaded

    def choose_workspace(self):
        documents_dir = self.ui.get_document_location()
        workspace_dir, directory = self.ui.get_existing_directory_dialog(_("Choose Workspace Folder"), documents_dir)
        return workspace_dir

    def start(self, skip_choose=False):
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
        documents_dir = self.ui.get_document_location()
        workspace_dir = os.path.join(documents_dir, "Nion Swift Workspace")
        workspace_dir = self.ui.get_persistent_string("workspace_location", workspace_dir)
        db_filename = os.path.join(workspace_dir, "Nion Swift Workspace.nswrk")
        cache_filename = os.path.join(workspace_dir, "Nion Swift Cache.nscache")
        if not skip_choose and not os.path.exists(db_filename):
            workspace_dir = self.choose_workspace()
            if not workspace_dir:
                return False
            db_filename = os.path.join(workspace_dir, "Nion Swift Workspace.nswrk")
            cache_filename = os.path.join(workspace_dir, "Nion Swift Cache.nscache")
        self.workspace_dir = workspace_dir
        data_reference_handler = DataReferenceHandler(self.ui, workspace_dir)
        create_new_document = not os.path.exists(db_filename)
        if create_new_document:
            logging.debug("Creating new document: %s", db_filename)
            datastore = Storage.DbDatastoreProxy(data_reference_handler, db_filename)
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
        if version == 4:
            logging.debug("Updating database from version 4 to version 5.")
            c.execute("SELECT nodes.uuid, items.item_uuid FROM nodes, items WHERE nodes.type='operation' AND nodes.uuid = items.parent_uuid")
            operation_item_and_graphic_item_uuids = []
            for row in c.fetchall():
                operation_item_and_graphic_item_uuids.append((row[0], row[1]))
            for operation_item_uuid, graphic_item_uuid in operation_item_and_graphic_item_uuids:
                c.execute("SELECT value FROM properties WHERE uuid = ? and key = 'bounds'", (graphic_item_uuid, ))
                result = c.fetchone()
                bounds = pickle.loads(str(result[0])) if result else None
                c.execute("SELECT value FROM properties WHERE uuid = ? and key = 'start'", (graphic_item_uuid, ))
                result = c.fetchone()
                start = pickle.loads(str(result[0])) if result else None
                c.execute("SELECT value FROM properties WHERE uuid = ? and key = 'end'", (graphic_item_uuid, ))
                result = c.fetchone()
                end = pickle.loads(str(result[0])) if result else None
                c.execute("SELECT value FROM properties WHERE uuid = ? and key = 'values'", (operation_item_uuid, ))
                result = c.fetchone()
                values = pickle.loads(str(result[0])) if result else dict()
                if start is not None:
                    values["start"] = start
                if end is not None:
                    values["end"] = end
                if bounds is not None:
                    values["bounds"] = bounds
                values_data = sqlite3.Binary(pickle.dumps(values, pickle.HIGHEST_PROTOCOL))
                c.execute("INSERT OR REPLACE INTO properties (uuid, key, value) VALUES (?, 'values', ?)", (operation_item_uuid, values_data))
                datastore.destroy_node_ref(graphic_item_uuid)
            c.execute("UPDATE version SET version = ?", (5, ))
            datastore.conn.commit()
            version = 5
        if version == 5:
            logging.debug("Updating database from version 5 to version 6.")
            c.execute("SELECT nodes.uuid FROM nodes WHERE nodes.type='data-item'")
            # find each node that has 'data-item' for type
            data_item_uuids = []
            for row in c.fetchall():
                data_item_uuids.append(row[0])
            for data_item_uuid in data_item_uuids:
                # for each data-item node, create a new node with 'display' for type.
                display_uuid = str(uuid.uuid4())
                c.execute("INSERT INTO nodes (uuid, type, refcount) VALUES (?, 'display', 1)", (display_uuid, ))
                # make an entry in 'relationships' relating each new 'display' to node
                c.execute("INSERT INTO relationships (parent_uuid, key, item_index, item_uuid) VALUES (?, 'displays', ?, ?)", (data_item_uuid, 0, display_uuid))
                # for each display property with parent matching node, switch it to "display'
                c.execute("SELECT key, value FROM properties WHERE uuid=? AND key IN ('display_limits', 'display_calibrated_values')", (data_item_uuid, ))
                display_properties = dict()
                for row in c.fetchall():
                    display_properties[row[0]] = pickle.loads(str(row[1]))
                c.execute("DELETE FROM properties WHERE uuid=? AND key IN ('display_limits', 'display_calibrated_values')", (data_item_uuid, ))
                display_properties_data = sqlite3.Binary(pickle.dumps(display_properties, pickle.HIGHEST_PROTOCOL))
                c.execute("INSERT INTO properties (uuid, key, value) VALUES (?, 'properties', ?)", (display_uuid, display_properties_data))
                # for each display relationship with parent matching node, switch it to 'display'
                c.execute("UPDATE relationships SET parent_uuid=? WHERE parent_uuid=? AND key IN ('graphics')", (display_uuid, data_item_uuid))
            c.execute("UPDATE version SET version = ?", (6, ))
            datastore.conn.commit()
            version = 6
        if version == 6:
            logging.debug("Updating database from version 6 to version 7.")
            c.execute("SELECT uuid FROM nodes WHERE type='document'")
            document_uuid = c.fetchone()[0]
            c.execute("SELECT MAX(item_index) FROM relationships WHERE parent_uuid=? AND key='data_items'", (document_uuid, ))
            data_item_index = int(c.fetchone()[0]) + 1
            c.execute("SELECT relationships.parent_uuid, relationships.item_uuid FROM relationships, nodes WHERE relationships.parent_uuid = nodes.uuid AND nodes.type = 'data-item' AND relationships.key = 'data_items'")
            parent_item_pairs = list()
            for row in c.fetchall():
                parent_item_pairs.append((row[0], row[1]))
            for parent_item_pair in parent_item_pairs:
                parent_uuid, item_uuid = parent_item_pair
                c.execute("SELECT value FROM properties WHERE uuid=? AND key='properties'", (item_uuid, ))
                result = c.fetchone()
                properties = pickle.loads(str(result[0])) if result else dict()
                properties["data_source_uuid"] = parent_uuid
                properties_data = sqlite3.Binary(pickle.dumps(properties, pickle.HIGHEST_PROTOCOL))
                c.execute("INSERT OR REPLACE INTO properties (uuid, key, value) VALUES (?, 'properties', ?)", (item_uuid, properties_data))
                c.execute("UPDATE relationships SET parent_uuid=?, item_index=? WHERE parent_uuid=? AND item_uuid=? AND key='data_items'", (document_uuid, data_item_index, parent_uuid, item_uuid))
                data_item_index += 1
            c.execute("UPDATE version SET version = ?", (7, ))
            datastore.conn.commit()
            version = 7
        if version == 7:
            logging.debug("Updating database from version 7 to version 8.")
            c.execute("SELECT uuid FROM nodes WHERE type='display'")
            parent_uuids = list()
            for row in c.fetchall():
                parent_uuids.append(row[0])
            for parent_uuid in parent_uuids:
                # grab the existing properties from the data item
                c.execute("SELECT value FROM properties WHERE uuid=? AND key='properties'", (parent_uuid, ))
                result = c.fetchone()
                properties = pickle.loads(str(result[0])) if result else dict()
                # find the graphic relationships
                c.execute("SELECT item_uuid FROM relationships WHERE parent_uuid=? AND key='graphics' ORDER BY item_index ASC", (parent_uuid, ))
                item_uuids = list()
                for row in c.fetchall():
                    item_uuids.append(row[0])
                for index, item_uuid in enumerate(item_uuids):
                    graphic_dict = dict()
                    c.execute("SELECT type FROM nodes WHERE uuid=?", (item_uuid, ))
                    result = c.fetchone()
                    graphic_dict["type"] = result[0]
                    c.execute("SELECT key, value FROM properties WHERE uuid=?", (item_uuid, ))
                    for row in c.fetchall():
                        key = row[0]
                        value = pickle.loads(str(row[1]))
                        graphic_dict[key] = value
                    graphic_list = properties.setdefault("graphics", list())
                    graphic_list.append(graphic_dict)
                    c.execute("DELETE FROM nodes WHERE uuid=?", (item_uuid, ))
                    c.execute("DELETE FROM properties WHERE uuid=?", (item_uuid, ))
                # update the properties
                properties_data = sqlite3.Binary(pickle.dumps(properties, pickle.HIGHEST_PROTOCOL))
                c.execute("INSERT OR REPLACE INTO properties (uuid, key, value) VALUES (?, 'properties', ?)", (parent_uuid, properties_data))
            c.execute("SELECT uuid FROM nodes WHERE type='data-item'")
            parent_uuids = list()
            for row in c.fetchall():
                parent_uuids.append(row[0])
            for parent_uuid in parent_uuids:
                # grab the existing properties from the data item
                c.execute("SELECT value FROM properties WHERE uuid=? AND key='properties'", (parent_uuid, ))
                result = c.fetchone()
                properties = pickle.loads(str(result[0])) if result else dict()
                # find the spatial calibration relationships
                c.execute("SELECT item_uuid FROM relationships WHERE parent_uuid=? AND key='calibrations' ORDER BY item_index ASC", (parent_uuid, ))
                item_uuids = list()
                for row in c.fetchall():
                    item_uuids.append(row[0])
                for index, item_uuid in enumerate(item_uuids):
                    c.execute("SELECT key, value FROM properties WHERE uuid=?", (item_uuid, ))
                    calibration_dict = dict()
                    for row in c.fetchall():
                        key = row[0]
                        value = pickle.loads(str(row[1]))
                        calibration_dict[key] = value
                    spatial_calibration_list = properties.setdefault("intrinsic_spatial_calibrations", list())
                    spatial_calibration_list.append(calibration_dict)
                    c.execute("DELETE FROM nodes WHERE uuid=?", (item_uuid, ))
                    c.execute("DELETE FROM properties WHERE uuid=?", (item_uuid, ))
                # find the intensity calibration items
                c.execute("SELECT item_uuid FROM items WHERE key='intrinsic_intensity_calibration' AND parent_uuid=?", (parent_uuid, ))
                result = c.fetchone()
                if result is not None:
                    item_uuid = result[0]
                    # find the intensity calibration relationships
                    c.execute("SELECT key, value FROM properties WHERE uuid=?", (item_uuid, ))
                    calibration_dict = dict()
                    for row in c.fetchall():
                        key = row[0]
                        value = pickle.loads(str(row[1]))
                        calibration_dict[key] = value
                    if calibration_dict:
                        properties["intrinsic_intensity_calibration"] = calibration_dict
                    c.execute("DELETE FROM properties WHERE uuid=?", (item_uuid, ))
                # look for the title
                c.execute("SELECT value FROM properties WHERE uuid=? AND key='title'", (parent_uuid, ))
                result = c.fetchone()
                if result is not None:
                    title = pickle.loads(str(result[0]))
                    properties["title"] = title
                # look for the datetime_original
                c.execute("SELECT value FROM properties WHERE uuid=? AND key='datetime_original'", (parent_uuid, ))
                result = c.fetchone()
                if result is not None:
                    datetime_original = pickle.loads(str(result[0]))
                    properties["datetime_original"] = datetime_original
                # look for the datetime_modified
                c.execute("SELECT value FROM properties WHERE uuid=? AND key='datetime_modified'", (parent_uuid, ))
                result = c.fetchone()
                if result is not None:
                    datetime_modified = pickle.loads(str(result[0]))
                    properties["datetime_modified"] = datetime_modified
                # look for the datetime_modified
                c.execute("SELECT value FROM properties WHERE uuid=? AND key='source_file_path'", (parent_uuid, ))
                result = c.fetchone()
                if result is not None:
                    source_file_path = unicode(pickle.loads(str(result[0])))
                    if source_file_path:
                        source_file_path = unicode(os.path.normpath(source_file_path))
                    properties["source_file_path"] = source_file_path
                c.execute("DELETE FROM properties WHERE uuid=? AND key='title'", (parent_uuid, ))
                c.execute("DELETE FROM properties WHERE uuid=? AND key='datetime_original'", (parent_uuid, ))
                c.execute("DELETE FROM properties WHERE uuid=? AND key='datetime_modified'", (parent_uuid, ))
                c.execute("DELETE FROM properties WHERE uuid=? AND key='source_file_path'", (parent_uuid, ))
                c.execute("DELETE FROM properties WHERE uuid=? AND key='param'", (parent_uuid, ))
                # look for operations
                c.execute("SELECT item_uuid FROM relationships WHERE parent_uuid=? AND key='operations' ORDER BY item_index ASC", (parent_uuid, ))
                item_uuids = list()
                for row in c.fetchall():
                    item_uuids.append(row[0])
                for index, item_uuid in enumerate(item_uuids):
                    c.execute("SELECT key, value FROM properties WHERE uuid=?", (item_uuid, ))
                    operation_dict = dict()
                    for row in c.fetchall():
                        key = row[0]
                        value = pickle.loads(str(row[1]))
                        operation_dict[key] = value
                    operation_list = properties.setdefault("operations", list())
                    operation_list.append(operation_dict)
                    c.execute("DELETE FROM nodes WHERE uuid=?", (item_uuid, ))
                    c.execute("DELETE FROM properties WHERE uuid=?", (item_uuid, ))
                # look for displays
                c.execute("SELECT item_uuid FROM relationships WHERE parent_uuid=? AND key='displays' ORDER BY item_index ASC", (parent_uuid, ))
                item_uuids = list()
                for row in c.fetchall():
                    item_uuids.append(row[0])
                for index, item_uuid in enumerate(item_uuids):
                    c.execute("SELECT key, value FROM properties WHERE uuid=?", (item_uuid, ))
                    display_dict = dict()
                    for row in c.fetchall():
                        key = row[0]
                        value = pickle.loads(str(row[1]))
                        display_dict[key] = value
                    display_list = properties.setdefault("displays", list())
                    # fix up the display properties
                    if "properties" in display_dict:
                        for key in display_dict["properties"].keys():
                            display_dict[key] = display_dict["properties"][key]
                        del display_dict["properties"]
                    display_list.append(display_dict)
                    c.execute("DELETE FROM nodes WHERE uuid=?", (item_uuid, ))
                    c.execute("DELETE FROM properties WHERE uuid=?", (item_uuid, ))
                # change around some properties
                if "data_source_uuid" in properties:
                    properties["data_sources"] = [properties["data_source_uuid"]]
                    del properties["data_source_uuid"]
                # migrate the metadata
                top_level_keys = ("metadata", "intrinsic_intensity_calibration", "intrinsic_spatial_calibrations", "datetime_original",
                                  "datetime_modified", "title", "caption", "rating", "flag", "source_file_path", "session_id", "data_sources",
                                  "operations", "displays")
                metadata = properties.get("metadata", dict())
                for key in properties.keys():
                    if not key in top_level_keys:
                        metadata_group = metadata.setdefault("hardware_source", dict())
                        metadata_group[key] = properties[key]
                        del properties[key]
                for key in metadata:
                    properties[key] = metadata[key]
                # update the properties
                properties_data = sqlite3.Binary(pickle.dumps(properties, pickle.HIGHEST_PROTOCOL))
                c.execute("INSERT OR REPLACE INTO properties (uuid, key, value) VALUES (?, 'properties', ?)", (parent_uuid, properties_data))
                c.execute("DELETE FROM properties WHERE key!='properties' AND uuid=?", (parent_uuid, ))
            c.execute("DELETE FROM relationships WHERE key='graphics'")
            c.execute("DELETE FROM relationships WHERE key='calibrations'")
            c.execute("DELETE FROM relationships WHERE key='intrinsic_calibrations'")
            c.execute("DELETE FROM relationships WHERE key='operations'")
            c.execute("DELETE FROM relationships WHERE key='displays'")
            c.execute("DELETE FROM items WHERE key='intrinsic_intensity_calibration'")
            c.execute("DELETE FROM items WHERE key='calibration'")
            c.execute("DELETE FROM nodes WHERE type='calibration'")
            c.execute("DELETE FROM properties WHERE key!='properties' AND key!='title'")
            c.execute("UPDATE version SET version = ?", (8, ))
            datastore.conn.commit()
            version = 8
        if version == 8:
            logging.debug("Updating database from version 8 to version 9.")
            c.execute("SELECT uuid FROM nodes WHERE type='data-group'")
            parent_uuids = list()
            for row in c.fetchall():
                parent_uuids.append(row[0])
            for parent_uuid in parent_uuids:
                # find the data item relationships
                c.execute("SELECT item_uuid FROM relationships WHERE parent_uuid=? AND key='data_items' ORDER BY item_index ASC", (parent_uuid, ))
                item_uuids = list()
                for row in c.fetchall():
                    item_uuids.append(uuid.UUID(row[0]))
                data_item_uuids_data = sqlite3.Binary(pickle.dumps(item_uuids, pickle.HIGHEST_PROTOCOL))
                c.execute("INSERT OR REPLACE INTO properties (uuid, key, value) VALUES (?, 'data_item_uuids', ?)", (parent_uuid, data_item_uuids_data))
                for item_uuid in item_uuids:
                    c.execute("UPDATE nodes SET refcount=refcount-1 WHERE uuid = ?", (str(item_uuid), ))
                c.execute("DELETE FROM relationships WHERE parent_uuid=? AND key='data_items'", (parent_uuid, ))
            c.execute("SELECT uuid FROM nodes WHERE type='document'")
            parent_uuids = list()
            for row in c.fetchall():
                parent_uuids.append(row[0])
            for parent_uuid in parent_uuids:
                # find the data item relationships
                c.execute("SELECT item_uuid FROM relationships WHERE parent_uuid=? AND key='data_items' ORDER BY item_index ASC", (parent_uuid, ))
                item_uuids = list()
                for row in c.fetchall():
                    item_uuids.append(uuid.UUID(row[0]))
                for item_uuid in item_uuids:
                    c.execute("UPDATE nodes SET refcount=refcount-1 WHERE uuid = ?", (str(item_uuid), ))
                c.execute("DELETE FROM relationships WHERE parent_uuid=? AND key='data_items'", (parent_uuid, ))
            c.execute("UPDATE version SET version = ?", (9, ))
            datastore.conn.commit()
            version = 9
        if version == 9:
            logging.debug("Updating database from version 9 to version 10.")
            c.execute("SELECT uuid FROM nodes WHERE type='data-item'")
            parent_uuids = list()
            for row in c.fetchall():
                parent_uuids.append(row[0])
            all_properties = dict()
            existing_references = dict()
            for parent_uuid in parent_uuids:
                # grab the existing properties from the data item
                c.execute("SELECT value FROM properties WHERE uuid=? AND key='properties'", (parent_uuid, ))
                result = c.fetchone()
                properties = pickle.loads(str(result[0])) if result else dict()
                all_properties[parent_uuid] = properties
            for parent_uuid in parent_uuids:
                properties = all_properties[parent_uuid]
                # read the data shape and dtype, if any
                c.execute("SELECT shape, dtype, reference FROM data_references WHERE uuid=? AND key='master_data'", (str(parent_uuid), ))
                result = c.fetchone()
                existing_reference = None
                if result is not None:
                    properties["master_data_shape"] = pickle.loads(str(result[0]))
                    properties["master_data_dtype"] = str(pickle.loads(str(result[1])))
                    existing_reference = os.path.splitext(result[2])[0]
                    existing_reference = existing_reference.replace("master_", "")
                    c.execute("UPDATE data_references SET reference=? WHERE uuid=? AND key='master_data'", (existing_reference, str(parent_uuid), ))
                properties["uuid"] = str(parent_uuid)
                # update the properties
                properties_data = sqlite3.Binary(pickle.dumps(properties, pickle.HIGHEST_PROTOCOL))
                c.execute("INSERT OR REPLACE INTO properties (uuid, key, value) VALUES (?, 'properties', ?)", (parent_uuid, properties_data))
                # write properties to a file
                def get_default_reference(uuid_, datetime_item, session_id):
                    # uuid_.bytes.encode('base64').rstrip('=\n').replace('/', '_')
                    # and back: uuid_ = uuid.UUID(bytes=(slug + '==').replace('_', '/').decode('base64'))
                    # also:
                    def encode(uuid_, alphabet):
                        result = str()
                        uuid_int = uuid_.int
                        while uuid_int:
                            uuid_int, digit = divmod(uuid_int, len(alphabet))
                            result += alphabet[digit]
                        return result
                    encoded_uuid_str = encode(uuid_, "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890")  # 25 character results
                    datetime_item = datetime_item if datetime_item else Utility.get_current_datetime_item()
                    datetime_ = Utility.get_datetime_from_datetime_item(datetime_item)
                    datetime_ = datetime_ if datetime_ else datetime.datetime.now()
                    path_components = datetime_.strftime("%Y-%m-%d").split('-')
                    session_id = session_id if session_id else datetime_.strftime("%Y%m%d-000000")
                    path_components.append(session_id)
                    path_components.append("data_" + encoded_uuid_str)
                    return os.path.join(*path_components)
                existing_references[parent_uuid] = existing_reference
                data_reference_handler = DataReferenceHandler(self.ui, workspace_dir)
                if existing_reference and "data_sources" in properties:
                    history = properties.setdefault("history", dict())
                    history_list = history.setdefault("list", list())
                    history_list.append(properties["data_sources"])
                    del properties["data_sources"]
                if "session_uuid" in properties.get("hardware_source", dict()):
                    del properties.get("hardware_source")["session_uuid"]
            for parent_uuid in parent_uuids:
                properties = all_properties[parent_uuid]
                operation_id = "operations" in properties and properties["operations"][0]["operation_id"]
                if operation_id in ["line-profile-operation", "crop-operation"]:
                    region_uuid_str = str(uuid.uuid4())
                    properties["operations"][0]["region_uuid"] = region_uuid_str
                    source_properties = all_properties.get(properties["data_sources"][0])
                    if source_properties is not None:
                        if operation_id == "line-profile-operation":
                            region = dict()
                            region["type"] = "line-region"
                            region["uuid"] = region_uuid_str
                            region["start"] = properties["operations"][0].get("values", dict()).get("start", (0.25, 0.25))
                            region["end"] = properties["operations"][0].get("values", dict()).get("end", (0.75, 0.75))
                            region["width"] = properties["operations"][0].get("values", dict()).get("width", 1.0)
                            source_properties.setdefault("regions", list()).append(region)
                        elif operation_id == "crop-operation":
                            region = dict()
                            region["type"] = "rectangle-region"
                            region["uuid"] = region_uuid_str
                            bounds = properties["operations"][0].get("values", dict()).get("bounds", ((0.0, 0.0), (1.0, 1.0)))
                            region["center"] = bounds[0][0] + bounds[1][0] * 0.5, bounds[0][1] + bounds[1][1] * 0.5
                            region["size"] = bounds[1]
                            source_properties.setdefault("regions", list()).append(region)
            for parent_uuid in parent_uuids:
                properties = all_properties[parent_uuid]
                existing_reference = existing_references[parent_uuid]
                properties = ImportExportManager.clean_dict(properties)
                if existing_reference:
                    data_file_path = existing_reference
                else:
                    data_file_path = get_default_reference(uuid.UUID(parent_uuid), properties.get("datetime_original"), properties.get("session_id"))
                reference = os.path.splitext(data_file_path)[0]
                file_datetime = Utility.get_datetime_from_datetime_item(properties.get("datetime_original"))
                data_reference_handler.write_properties(properties, "relative_file", reference, file_datetime)
                if existing_reference:
                    nsdata_path = os.path.join(workspace_dir, "Nion Swift Data", existing_reference.replace("data_", "master_data_") + ".nsdata")
                    logging.info(nsdata_path)
                    if os.path.exists(nsdata_path):
                        data = pickle.load(open(nsdata_path, "rb"))
                        data_reference_handler.write_data_reference(data, "relative_file", reference, file_datetime)
                        os.remove(nsdata_path)
            c.execute("UPDATE version SET version = ?", (10, ))
            datastore.conn.commit()
            version = 10
        # NOTE: version must be changed here and in Storage.py
        if version > 10:
            logging.debug("Database too new, version %s", version)
            sys.exit()
        datastore.conn.commit()
        datastore.check_integrity()
        storage_cache = Storage.DbStorageCache(cache_filename)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_model.create_default_data_groups()
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
        logging.info("Welcome to Nion Swift.")
        if create_new_document and len(document_model.data_items) > 0:
            document_controller.selected_image_panel.set_displayed_data_item(document_model.data_items[0])
            document_controller.selected_image_panel.image_canvas_item.set_fill_mode()
        return True

    def get_recent_workspace_file_paths(self):
        workspace_history = self.ui.get_persistent_object("workspace_history", list())
        # workspace_history = ["/Users/cmeyer/Movies/Crap/Test1", "/Users/cmeyer/Movies/Crap/Test7_new"]
        return [file_path for file_path in workspace_history if file_path != self.workspace_dir and os.path.exists(file_path)]

    def switch_workspace(self, recent_workspace_file_path, skip_choose=False):
        for document_controller in self.__document_controllers:
            document_controller.document_window.close()
        self.ui.set_persistent_string("workspace_location", recent_workspace_file_path)
        self.start(skip_choose=skip_choose)

    def other_workspace(self):
        workspace_dir = self.choose_workspace()
        if workspace_dir:
            self.switch_workspace(workspace_dir, skip_choose=True)

    def new_workspace(self):
        workspace_dir = self.choose_workspace()
        if workspace_dir:
            self.switch_workspace(workspace_dir, skip_choose=True)

    def clear_workspaces(self):
        self.ui.remove_persistent_key("workspace_history")

    def create_document_controller(self, document_model, workspace_id, data_panel_selection=None):
        document_controller = DocumentController.DocumentController(self.ui, document_model, workspace_id=workspace_id, app=self)
        document_controller.add_listener(self)
        self.register_document_controller(document_controller)
        # attempt to set data item / group
        if data_panel_selection:
            image_panel = document_controller.selected_image_panel
            if image_panel:
                image_panel.set_displayed_data_item(data_panel_selection.data_item)
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

    def register_data_item_computation(self, computation_fn):
        DataItem.register_data_item_computation(computation_fn)

    def unregister_data_item_computation(self, computation_fn):
        DataItem.unregister_data_item_computation(computation_fn)

    def __get_menu_handlers(self):
        return copy.copy(self.__menu_handlers)
    menu_handlers = property(__get_menu_handlers)

    def run_all_tests(self):
        Test.run_all_tests()


class DataReferenceHandler(object):

    def __init__(self, ui, workspace_dir):
        self.ui = ui
        self.workspace_dir = workspace_dir
        self.__data_dir = os.path.join(self.workspace_dir, "Nion Swift Data")
        self.__file_handler = NDataHandler.NDataHandler(self.__data_dir)
        assert self.workspace_dir

    def find_data_item_tuples(self):
        tuples = []
        #logging.debug("data_dir %s", self.__data_dir)
        for root, dirs, files in os.walk(self.__data_dir):
            absolute_file_paths = [os.path.join(root, data_file) for data_file in files]
            data_files = filter(self.__file_handler.is_matching, absolute_file_paths)
            for data_file in data_files:
                reference_type = "relative_file"
                reference = self.__file_handler.get_reference(data_file)
                try:
                    item_uuid, properties = self.__file_handler.read_properties(reference)
                    tuples.append((item_uuid, properties, reference_type, reference))
                except Exception, e:
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
