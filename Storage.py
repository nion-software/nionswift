# standard libraries
import collections
import copy
import cPickle as pickle
import functools
import logging
import Queue
import sqlite3
import StringIO
import threading
import uuid
import weakref

# third party libraries
# None

# local libraries
# None


class MutableRelationship(collections.MutableSequence):

    def __init__(self, parent, relationship_name):
        self.store = list()
        self.relationship_name = relationship_name
        self.parent_weak_ref = weakref.ref(parent)

    def __copy__(self):
        return copy.copy(self.store)

    def __len__(self):
        return len(self.store)

    def __getitem__(self, index):
        return self.store[index]

    def __setitem__(self, index, value):
        raise IndexError()

    def __delitem__(self, index):
        # get value
        value = self.store[index]
        # unobserve
        value.remove_observer(self.parent_weak_ref())
        # do actual removal
        del self.store[index]
        # keep storage up-to-date
        self.parent_weak_ref().notify_remove_item(self.relationship_name, value, index)
        # ref count
        value.remove_ref()

    def __iter__(self):
        return iter(self.store)

    def insert(self, index, value):
        assert value not in self.store
        # ref count
        value.add_ref()
        # insert in internal list
        self.store.insert(index, value)
        # observe
        value.add_observer(self.parent_weak_ref())
        # keep storage up-to-date
        self.parent_weak_ref().notify_insert_item(self.relationship_name, value, index)


class MutableMapping(collections.MutableMapping):

    def __init__(self, parent, property_name):
        self.mapping = dict()
        self.property_name = property_name
        self.parent_weak_ref = weakref.ref(parent) if parent else None

    def __copy__(self):
        return copy.copy(self.mapping)

    def __len__(self):
        return len(self.mapping)

    def __iter__(self):
        return iter(self.mapping)

    def __contains__(self, item):
        return item in self.mapping

    def __getitem__(self, key):
        return self.mapping[key]

    def __setitem__(self, key, value):
        self.mapping[key] = value
        print("set %s = %s" % (key, value))

    def __delitem__(self, key):
        del self.mapping[key]
        print("del %s" % key)


#
# StorageBase is reference counted. Clients should always
# add_ref and remove_ref when storing these objects.
# about_to_delete will be called when reference count
# reaches zero during a remove_ref.
#
# StorageBase supports observers and listeners.
#
# Observers can watch all serializable changes to the object by
# adding themselves as an observer and then overriding one or more
# of the following methods:
#   property_changed(object, key, value)
#   item_set(object, key, value)
#   item_cleared(object, key)
#   data_set(object, key, data)
#   item_inserted(object, key, value, before_index)
#   item_removed(object, key, value, index)
#
# Listeners listen to any notifications broadcast. They
# take the form of specific method calls on the listeners.
#
# Connections are automatically controlled listeners. They
# will be removed when the reference count goes to zero.
#
class StorageBase(object):

    def __init__(self):
        self.__storage_writer = None
        self.__storage_cache = None
        self.storage_properties = []
        self.storage_relationships = []
        self.storage_items = []
        self.storage_data_keys = []
        self.storage_type = None
        self.__cache = dict()
        self.__cache_dirty = dict()
        self.__weak_observers = []
        self.__weak_listeners = []
        self.__weak_listeners_mutex = threading.RLock()
        self.__weak_parents = []
        self.__ref_count = 0
        self.__ref_count_mutex = threading.RLock()  # access to the image
        self.__uuid = uuid.uuid4()

    def __del__(self):
        # There should not be listeners or references at this point.
        assert len(self.__weak_observers) == 0, 'Observable still has observers'
        assert len(self.__weak_listeners) == 0, 'Observable still has listeners'
        assert len(self.__weak_parents) == 0, 'Observable still has parents'
        assert self.__ref_count == 0, 'Observable still has references'

    # Give subclasses a chance to clean up. This gets called when reference
    # count goes to 0, but before deletion.
    def about_to_delete(self):
        pass

    # Anytime you store a reference to this item, call add_ref.
    # This allows the class to disconnect from its own sources
    # automatically when the reference count goes to zero.
    def add_ref(self):
        with self.__ref_count_mutex:
            self.__ref_count += 1

    # Anytime you give up a reference to this item, call remove_ref.
    def remove_ref(self):
        with self.__ref_count_mutex:
            assert self.__ref_count > 0, 'DataItem has no references'
            self.__ref_count -= 1
            if self.__ref_count == 0:
                self.about_to_delete()

    # Return the reference count, which should represent the number
    # of places that this DataItem is stored by a caller.
    def __get_ref_count(self):
        return self.__ref_count
    ref_count = property(__get_ref_count)

    # uuid property. read only.
    def __get_uuid(self):
        return self.__uuid
    uuid = property(__get_uuid)
    # set is used by document controller
    def _set_uuid(self, uuid):
        self.__uuid = uuid

    # Add a listener. Listeners will receive data_item_changed message when this
    # DataItem is notified of a change via the notify_data_item_changed() method.
    def add_listener(self, listener):
        with self.__weak_listeners_mutex:
            assert listener is not None
            self.__weak_listeners.append(weakref.ref(listener))

    # Remove a listener.
    def remove_listener(self, listener):
        with self.__weak_listeners_mutex:
            assert listener is not None
            self.__weak_listeners.remove(weakref.ref(listener))

    # Send a message to the listeners
    def notify_listeners(self, fn, *args, **keywords):
        try:
            with self.__weak_listeners_mutex:
                listeners = [weak_listener() for weak_listener in self.__weak_listeners]
            for listener in listeners:
                if hasattr(listener, fn):
                    getattr(listener, fn)(*args, **keywords)
        except Exception as e:
            import traceback
            traceback.print_exc()
            logging.debug("Notify Error: %s", e)

    # Add a parent. Parents will receive data_item_changed message when this
    # DataItem is notified of a change via the notify_data_item_changed() method.
    def add_parent(self, parent):
        assert parent is not None
        self.__weak_parents.append(weakref.ref(parent))

    # Remove a parent.
    def remove_parent(self, parent):
        assert parent is not None
        self.__weak_parents.remove(weakref.ref(parent))

    # Return a copy of parents array
    def get_weak_parents(self):
        return self.__weak_parents  # TODO: Return a copy
    def __get_parents(self):
        return [weak_parent() for weak_parent in self.__weak_parents]
    parents = property(__get_parents)

    # Send a message to the parents
    def notify_parents(self, fn, *args, **keywords):
        for parent in self.parents:
            if hasattr(parent, fn):
                getattr(parent, fn)(*args, **keywords)

    def __get_storage_writer(self):
        return self.__storage_writer
    def __set_storage_writer(self, storage_writer):
        self.__storage_writer = storage_writer
        for item_key in self.storage_items:
            item = self.get_storage_item(item_key)
            if item:
                item.storage_writer = storage_writer
        for relationship_key in self.storage_relationships:
            count = self.get_storage_relationship_count(relationship_key)
            for index in range(count):
                item = self.get_storage_relationship(relationship_key, index)
                item.storage_writer = storage_writer
    storage_writer = property(__get_storage_writer, __set_storage_writer)

    def __get_storage_cache(self):
        return self.__storage_cache
    def __set_storage_cache(self, storage_cache):
        self.__storage_cache = storage_cache
        for item_key in self.storage_items:
            item = self.get_storage_item(item_key)
            if item:
                item.storage_cache = storage_cache
        for relationship_key in self.storage_relationships:
            count = self.get_storage_relationship_count(relationship_key)
            for index in range(count):
                item = self.get_storage_relationship(relationship_key, index)
                item.storage_cache = storage_cache
        for key, value in self.__cache.iteritems():
            if self.storage_cache:
                self.storage_cache.set_cached_value(self, key, value, self.__cache_dirty.get(key, False))
        self.__cache.clear()
        self.__cache_dirty.clear()
    storage_cache = property(__get_storage_cache, __set_storage_cache)

    def get_storage_property(self, key):
        if hasattr(self, key):
            return getattr(self, key)
        if hasattr(self, "get_" + key):
            return getattr(self, "get_" + key)()
        if hasattr(self, "_get_" + key):
            return getattr(self, "_get_" + key)()
        logging.debug("get_storage_property: %s missing %s", self, key)
        raise NotImplementedError()

    def get_storage_item(self, key):
        if hasattr(self, key):
            return getattr(self, key)
        if hasattr(self, "get_" + key):
            return getattr(self, "get_" + key)()
        if hasattr(self, "_get_" + key):
            return getattr(self, "_get_" + key)()
        logging.debug("get_storage_item: %s missing %s", self, key)
        raise NotImplementedError()

    def get_storage_data(self, key):
        if hasattr(self, key):
            return getattr(self, key)
        if hasattr(self, "get_" + key):
            return getattr(self, "get_" + key)()
        if hasattr(self, "_get_" + key):
            return getattr(self, "_get_" + key)()
        logging.debug("get_storage_data: %s missing %s", self, key)
        raise NotImplementedError()

    def get_storage_relationship_count(self, key):
        if hasattr(self, key):
            return len(getattr(self, key))
        logging.debug("get_storage_relationship_count: %s missing %s", self, key)
        raise NotImplementedError()

    def get_storage_relationship(self, key, index):
        if hasattr(self, key):
            return getattr(self, key)[index]
        logging.debug("get_storage_relationship: %s missing %s[%d]", self, key, index)
        raise NotImplementedError()

    def get_storage_relationship_all(self, key):
        if hasattr(self, key):
            return getattr(self, key)
        if hasattr(self, "get_" + key):
            return getattr(self, "get_" + key)()
        if hasattr(self, "_get_" + key):
            return getattr(self, "_get_" + key)()
        return [self.get_storage_relationship(key, i) for i in range(self.get_storage_relationship_count(key))]

    # implement observer/notification mechanism

    def add_observer(self, observer):
        self.__weak_observers.append(weakref.ref(observer))

    def remove_observer(self, observer):
        self.__weak_observers.remove(weakref.ref(observer))

    def notify_set_property(self, key, value):
        if self.storage_writer:
            self.storage_writer.set_property(self, key, value)
        for weak_observer in self.__weak_observers:
            observer = weak_observer()
            if observer and getattr(observer, "property_changed", None):
                observer.property_changed(self, key, value)

    def notify_set_item(self, key, item):
        assert item is not None
        if self.storage_writer:
            item.storage_writer = self.storage_writer
            self.storage_writer.set_item(self, key, item)
        if self.storage_cache:
            item.storage_cache = self.storage_cache
        if item:
            item.add_parent(self)
        for weak_observer in self.__weak_observers:
            observer = weak_observer()
            if observer and getattr(observer, "item_set", None):
                observer.item_set(self, key, value)

    def notify_clear_item(self, key):
        item = self.get_storage_item(key)
        if item:
            if self.storage_writer:
                self.storage_writer.clear_item(self, key)
                item.storage_writer = None
            if self.storage_cache:
                item.storage_cache = None
            item.remove_parent(self)
            for weak_observer in self.__weak_observers:
                observer = weak_observer()
                if observer and getattr(observer, "item_cleared", None):
                    observer.item_cleared(self, key)

    def notify_set_data(self, key, data):
        if self.storage_writer:
            self.storage_writer.set_data(self, key, data)
        for weak_observer in self.__weak_observers:
            observer = weak_observer()
            if observer and getattr(observer, "data_set", None):
                observer.data_set(self, key, data)

    def notify_insert_item(self, key, value, before_index):
        assert value is not None
        if self.storage_writer:
            value.storage_writer = self.storage_writer
            self.storage_writer.insert_item(self, key, value, before_index)
        if self.storage_cache:
            value.storage_cache = self.storage_cache
        value.add_parent(self)
        for weak_observer in self.__weak_observers:
            observer = weak_observer()
            if observer and getattr(observer, "item_inserted", None):
                observer.item_inserted(self, key, value, before_index)

    def notify_remove_item(self, key, value, index):
        assert value is not None
        if self.storage_writer:
            self.storage_writer.remove_item(self, key, index)
            value.storage_writer = None
        if self.storage_cache:
            value.storage_cache = None
        value.remove_parent(self)
        for weak_observer in self.__weak_observers:
            observer = weak_observer()
            if observer and getattr(observer, "item_removed", None):
                observer.item_removed(self, key, value, index)

    def rewrite(self):
        assert self.storage_writer is not None
        self.storage_writer.begin_rewrite()
        self.storage_writer.set_root(self)
        self.write()
        self.storage_writer.end_rewrite()

    def write(self):
        assert self.storage_writer is not None
        for property_key in self.storage_properties:
            value = self.get_storage_property(property_key)
            if value:
                self.storage_writer.set_property(self, property_key, value)
        for item_key in self.storage_items:
            item = self.get_storage_item(item_key)
            if item:
                item.storage_writer = self.storage_writer
                item.storage_cache = self.storage_cache
                self.storage_writer.set_item(self, item_key, item)
        for data_key in self.storage_data_keys:
            data = self.get_storage_data(data_key)
            if data is not None:
                self.storage_writer.set_data(self, data_key, data)
        for relationship_key in self.storage_relationships:
            count = self.get_storage_relationship_count(relationship_key)
            for index in range(count):
                item = self.get_storage_relationship(relationship_key, index)
                item.storage_writer = self.storage_writer
                item.storage_cache = self.storage_cache
                self.storage_writer.insert_item(self, relationship_key, item, index)
        if self.storage_writer:
            self.storage_writer.set_type(self, self.storage_type)

    def set_cached_value(self, key, value, dirty=False):
        if self.storage_cache:
            self.storage_cache.set_cached_value(self, key, value, dirty)
        else:
            self.__cache[key] = value
            self.__cache_dirty[key] = False

    def get_cached_value(self, key, default_value=None):
        if self.storage_cache:
            return self.storage_cache.get_cached_value(self, key, default_value)
        return self.__cache.get(key, default_value)

    def remove_cached_value(self, key):
        if self.storage_cache:
            self.storage_cache.remove_cached_value(self, key)
        else:
            if key in self.__cache:
                del self.__cache[key]
            if key in self.__cache_dirty:
                del self.__cache_dirty[key]

    def is_cached_value_dirty(self, key):
        if self.storage_cache:
            return self.storage_cache.is_cached_value_dirty(self, key)
        return self.__cache_dirty[key] if key in self.__cache_dirty else True

    def set_cached_value_dirty(self, key, dirty=True):
        if self.storage_cache:
            self.storage_cache.set_cached_value_dirty(self, key, dirty)
        else:
            self.__cache_dirty[key] = dirty

# design considerations: fast, threaded, future proof, object oriented items
# two techniques:
# - model objects know about storage, explicitly manage storage
# - model objects have listener architecture, storage listens to each
# overall design can use a combination of the two techniques. the parent must
# act as a storage liason if the listener architecture is used.
# in addition to actively communicating changes to storage, the items must be
# able to create themselves from storage and be able to write themselves to
# storage.
# objects in storage must be able to provide type, uuid, constructor, write
# changes to the object model are only allowed on the main thread. this allows
# everything to be serialized properly.
# blob support
# db revision support
# save thumbnails?
# save processed data?
# TODO: revisit core data design from Apple
class DictStorageWriter(object):

    def __init__(self):
        self.__node_map = {}
        self.disconnected = False

    def __get_node_map(self):
        return self.__node_map
    node_map = property(__get_node_map)

    def set_root(self, root):
        if self.disconnected:
            return
        self.__make_node(root.uuid)

    def log(self):
        for key in self.__node_map.keys():
            logging.debug("%s %s: %s", type(self.__node_map[key]), key, self.__node_map[key])

    def save_file(self, db_filename):
        pickle.dump(self.__node_map, open(db_filename, "wb"))

    def begin_rewrite(self):
        self.__node_map = {}

    def end_rewrite(self):
        pass

    def __make_node(self, uuid):
        if uuid in self.__node_map:
            return self.__node_map[uuid]
        else:
            node = {}
            node["ref-count"] = 0
            self.__node_map[uuid] = node
            return node

    def find_node_or_none(self, item):
        return self.__node_map[item.uuid] if item.uuid in self.__node_map else None

    def find_node(self, item):
        return self.__node_map[item.uuid]

    def __add_node_ref(self, uuid):
        self.__node_map[uuid]["ref-count"] += 1

    def __remove_node_ref(self, uuid):
        node = self.__node_map[uuid]
        node["ref-count"] -= 1
        if node["ref-count"] == 0:
            # first remove the items
            items = node.get("items", {})
            for item_key in items.keys():
                item_uuid = items[item_key]
                self.__remove_node_ref(item_uuid)
                del items[item_key]
            # next remove the relationships
            relationships = node.get("relationships", {})
            for relationship_key in relationships.keys():
                list = relationships[relationship_key]
                for item_uuid in list:
                    self.__remove_node_ref(item_uuid)
                del relationships[relationship_key]
            del self.__node_map[uuid]

    def set_type(self, item, type):
        if self.disconnected:
            return
        # get the item node
        item_node = self.find_node(item)
        # write to it
        item_node["type"] = type

    def set_item(self, parent, key, item):
        if self.disconnected:
            return
        # make a node in storage
        node = self.__make_node(item.uuid)
        # write item to the new node
        item.write()
        # get the parent node
        parent_node = self.find_node(parent)
        # insert new node in parent
        items = parent_node.setdefault("items", {})
        items[key] = item.uuid
        self.__add_node_ref(item.uuid)

    def clear_item(self, parent, key):
        if self.disconnected:
            return
        # get the parent node
        parent_node = self.find_node(parent)
        # find the node we will remove
        items = parent_node["items"]
        item_uuid = items[key]
        del items[key]
        self.__remove_node_ref(item_uuid)

    def insert_item(self, parent, key, item, before):
        if self.disconnected:
            return
        # make a node in storage
        node = self.__make_node(item.uuid)
        # write item to the new node
        item.write()
        # get the parent node
        parent_node = self.find_node(parent)
        # insert new node in parent
        relationships = parent_node.setdefault("relationships", {})
        list = relationships.setdefault(key, [])
        list.insert(before, item.uuid)
        self.__add_node_ref(item.uuid)

    def remove_item(self, parent, key, index):
        if self.disconnected:
            return
        # get the parent node
        parent_node = self.find_node(parent)
        # find the node we will remove
        relationships = parent_node["relationships"]
        list = relationships[key]
        item_uuid = list[index]
        del list[index]
        self.__remove_node_ref(item_uuid)

    def set_property(self, item, key, value):
        if self.disconnected:
            return
        # get the item node
        item_node = self.find_node(item)
        # write to it
        properties = item_node.setdefault("properties", {})
        properties[key] = value

    def set_data(self, parent, key, data):
        if self.disconnected:
            return
        # get the parent node
        parent_node = self.find_node(parent)
        # insert new node in parent
        data_arrays = parent_node.setdefault("data_arrays", {})
        data_arrays[key] = data


class DictStorageReader(object):
    def __init__(self, node_map=None):
        self.__node_map = node_map if node_map else {}
        self.__item_map = {}
        self.need_rewrite = False

    def log(self):
        for key in self.__node_map.keys():
            logging.debug("%s: %s", key, self.__node_map[key])

    def load_file(self, db_filename):
        self.__node_map = pickle.load(open(db_filename, "rb"))

    def find_root_node(self, type):
        for item in self.__node_map:
            if self.__node_map[item]["type"] == type:
                return self.__node_map[item], item
        return None

    def build_item(self, uuid_):
        item = None
        if uuid_ not in self.__item_map:
            node = self.__node_map[uuid_]
            from nion.swift import DataGroup
            from nion.swift import DataItem
            from nion.swift import Graphics
            from nion.swift import Operation
            build_map = {
                "data-group": DataGroup.DataGroup,
                "smart-data-group": DataGroup.SmartDataGroup,
                "data-item": DataItem.DataItem,
                "calibration": DataItem.Calibration,
                "line-graphic": Graphics.LineGraphic,
                "rect-graphic": Graphics.RectangleGraphic,
                "ellipse-graphic": Graphics.EllipseGraphic,
                "fft-operation": Operation.FFTOperation,
                "inverse-fft-operation": Operation.IFFTOperation,
                "invert-operation": Operation.InvertOperation,
                "gaussian-blur-operation": Operation.GaussianBlurOperation,
                "resample-operation": Operation.Resample2dOperation,
                "crop-operation": Operation.Crop2dOperation,
                "histogram-operation": Operation.HistogramOperation,
                "line-profile-operation": Operation.LineProfileOperation,
                "convert-to-scalar-operation": Operation.ConvertToScalarOperation,
            }
            type = node["type"]
            if type in build_map:
                item = build_map[type].build(self, node)
                item._set_uuid(uuid_)
            if item:
                self.__item_map[uuid_] = item
            else:
                logging.debug("Unable to build %s", type)
        else:
            item = self.__item_map[uuid_]
        return item

    def has_data(self, parent_node, key):
        return "data_arrays" in parent_node and key in parent_node["data_arrays"]

    def has_item(self, parent_node, key):
        return "items" in parent_node and key in parent_node["items"]

    def has_relationship(self, parent_node, key):
        return "relationships" in parent_node and key in parent_node["relationships"]

    def get_item(self, parent_node, key, default_value=None):
        items = parent_node["items"]
        if key in items:
            return self.build_item(items[key])
        else:
            return default_value

    def get_items(self, parent_node, key):
        relationships = parent_node["relationships"] if "relationships" in parent_node else {}
        if key in relationships:
            return [self.build_item(uuid) for uuid in relationships[key]]
        else:
            return []

    def get_property(self, parent_node, key, default_value=None):
        properties = parent_node["properties"] if "properties" in parent_node else {}
        if key in properties:
            return properties[key]
        else:
            return default_value

    def get_data(self, parent_node, key, default_value=None):
        data_items = parent_node["data_arrays"] if "data_arrays" in parent_node else {}
        if key in data_items:
            data = data_items[key]
            assert (data.shape is not None) if data is not None else True  # cheap way to ensure data is an ndarray
            return data_items[key]
        else:
            return default_value



class DbStorageWriter(object):

    def __init__(self, db_filename):
        self.conn = sqlite3.connect(db_filename, check_same_thread=False)
        self.disconnected = False
        self.create()
        self.migrate()

    def close(self):
        pass

    def execute(self, c, stmt, args=None, log=False):
        if args:
            c.execute(stmt, args)
            if log:
                logging.debug("%s [%s]", stmt, args)
        else:
            c.execute(stmt)
            if log:
                logging.debug("%s", stmt)

    def to_string(self):
        # save out to string
        string_file = StringIO.StringIO()
        for line in self.conn.iterdump():
            string_file.write('%s\n' % line)
        string_file.seek(0)
        self.last_to_string = string_file.read()
        return self.last_to_string

    def print_counts(self):
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) FROM nodes")
        logging.debug("nodes: %s", c.fetchone()[0])
        c.execute("SELECT COUNT(*) FROM properties")
        logging.debug("properties: %s", c.fetchone()[0])
        c.execute("SELECT COUNT(*) FROM data")
        logging.debug("data: %s", c.fetchone()[0])
        c.execute("SELECT COUNT(*) FROM relationships")
        logging.debug("relationships: %s", c.fetchone()[0])

    def begin_rewrite(self):
        c = self.conn.cursor()
        self.execute(c, "DELETE FROM nodes")
        self.execute(c, "DELETE FROM properties")
        self.execute(c, "DELETE FROM data")
        self.execute(c, "DELETE FROM relationships")

    def end_rewrite(self):
        self.conn.commit()

    def set_root(self, root):
        self.__make_node(root.uuid)

    def create(self):
        if not self.disconnected:
            c = self.conn.cursor()
            self.execute(c, "CREATE TABLE IF NOT EXISTS nodes(uuid STRING, type STRING, refcount INTEGER, PRIMARY KEY(uuid))")
            self.execute(c, "CREATE TABLE IF NOT EXISTS properties(uuid STRING, key STRING, value BLOB, PRIMARY KEY(uuid, key))")
            self.execute(c, "CREATE TABLE IF NOT EXISTS data(uuid STRING, key STRING, data BLOB, PRIMARY KEY(uuid, key))")
            self.execute(c, "CREATE TABLE IF NOT EXISTS relationships(parent_uuid STRING, key STRING, item_index INTEGER, item_uuid STRING, PRIMARY KEY(parent_uuid, key, item_index))")
            self.execute(c, "CREATE TABLE IF NOT EXISTS items(parent_uuid STRING, key STRING, item_uuid STRING, PRIMARY KEY(parent_uuid, key))")
            self.conn.commit()

    def migrate(self):
        # do this whether disconnected or not
        c = self.conn.cursor()
        self.execute(c, "SELECT name FROM sqlite_master WHERE type='table' AND name='items'")
        if c.fetchone() is None:
            self.execute(c, "CREATE TABLE IF NOT EXISTS items(parent_uuid STRING, key STRING, item_uuid STRING, PRIMARY KEY(parent_uuid, key))")
        self.conn.commit()

    # keep. used for testing
    def find_node_or_none(self, item):
        return self.find_node(item)

    # keep. used for testing
    def find_node(self, item):
        c = self.conn.cursor()
        self.execute(c, "SELECT * FROM nodes WHERE uuid = ?", (str(item.uuid), ))
        node = c.fetchone()
        return node

    def __make_node(self, uuid):
        c = self.conn.cursor()
        self.execute(c, "SELECT * FROM nodes WHERE uuid = ?", (str(uuid), ))
        node = c.fetchone()
        if node:
            return node
        else:
            self.execute(c, "INSERT INTO nodes (uuid, type, refcount) VALUES (?, NULL, 0)", (str(uuid), ))
            self.execute(c, "SELECT * FROM nodes WHERE uuid = ?", (str(uuid), ))
            node = c.fetchone()
            return node

    def __add_node_ref(self, uuid_):
        c = self.conn.cursor()
        self.execute(c, "UPDATE nodes SET refcount=refcount+1 WHERE uuid = ?", (str(uuid_), ))

    def __remove_node_ref(self, uuid_):
        c = self.conn.cursor()
        self.execute(c, "UPDATE nodes SET refcount=refcount-1 WHERE uuid = ?", (str(uuid_), ))
        self.execute(c, "SELECT refcount FROM nodes WHERE uuid = ?", (str(uuid_), ))
        refcount = c.fetchone()[0]
        if refcount == 0:
            # remove properties
            self.execute(c, "DELETE FROM properties WHERE uuid = ?", (str(uuid_), ))
            # remove data
            self.execute(c, "DELETE FROM data WHERE uuid = ?", (str(uuid_), ))
            # remove single items
            if False:  # not implemented yet
                items = node.get("items", {})
                for item_key in items.keys():
                    item_uuid = items[item_key]
                    self.__remove_node_ref(item_uuid)
                    del items[item_key]
            # remove relationships.
            self.execute(c, "SELECT item_uuid FROM relationships WHERE parent_uuid = ?", (str(uuid_), ))
            for item_uuid in c.fetchall():
                self.__remove_node_ref(uuid.UUID(item_uuid[0]))
            self.execute(c, "DELETE FROM relationships WHERE parent_uuid = ?", (str(uuid_), ))
            self.execute(c, "DELETE FROM nodes WHERE uuid = ?", (str(uuid_), ))

    def set_type(self, item, type):
        if not self.disconnected:
            c = self.conn.cursor()
            self.execute(c, "UPDATE nodes SET type=? WHERE uuid = ?", (type, str(item.uuid), ))
            self.conn.commit()

    def set_item(self, parent, key, item):
        if not self.disconnected:
            c = self.conn.cursor()
            node = self.__make_node(item.uuid)
            item.write()
            self.execute(c, "INSERT INTO items (parent_uuid, key, item_uuid) VALUES (?, ?, ?)", (str(parent.uuid), key, str(item.uuid), ))
            self.__add_node_ref(item.uuid)
            self.conn.commit()

    def clear_item(self, parent, key):
        if not self.disconnected:
            c = self.conn.cursor()
            self.execute(c, "SELECT item_uuid FROM items WHERE parent_uuid=? AND key=?", (str(parent.uuid), key, ))
            item_uuid = uuid.UUID(c.fetchone()[0])
            self.execute(c, "DELETE FROM items WHERE parent_uuid=? AND key=?", (str(parent.uuid), key, ))
            self.__remove_node_ref(item_uuid)
            self.conn.commit()

    # don't let incorrect item_indexes go into database
    def __item_index_integrity_check(self, c, parent_uuid):
        self.execute(c, "SELECT COUNT(*), MAX(item_index), MIN(item_index) FROM relationships WHERE parent_uuid=? and key='data_items'", (str(parent_uuid), ))
        results = c.fetchone()
        if results[0] > 0:
            assert results[2] == 0
            assert results[1] == results[0] - 1

    def insert_item(self, parent, key, item, before):
        if not self.disconnected:
            c = self.conn.cursor()
            node = self.__make_node(item.uuid)
            item.write()
            # 1 2 3 ^ 4 5 6 => 1 2 3 -5 -6 -7 => 1 2 3 5 6 7 => 1 2 3 4 5 6 7
            self.execute(c, "UPDATE relationships SET item_index = -(item_index + 1) WHERE parent_uuid=? AND key=? AND item_index >= ?", (str(parent.uuid), key, before, ))
            self.execute(c, "UPDATE relationships SET item_index = -item_index WHERE parent_uuid=? AND key=? AND item_index < -?", (str(parent.uuid), key, before, ))
            self.execute(c, "INSERT INTO relationships (parent_uuid, key, item_index, item_uuid) VALUES (?, ?, ?, ?)", (str(parent.uuid), key, before, str(item.uuid), ))
            self.__add_node_ref(item.uuid)
            self.__item_index_integrity_check(c, parent.uuid)
            self.conn.commit()

    def remove_item(self, parent, key, index):
        if not self.disconnected:
            c = self.conn.cursor()
            self.execute(c, "SELECT item_uuid FROM relationships WHERE parent_uuid=? AND key=? AND item_index=?", (str(parent.uuid), key, index, ))
            item_uuid = uuid.UUID(c.fetchone()[0])
            self.execute(c, "DELETE FROM relationships WHERE parent_uuid=? AND key=? AND item_index=?", (str(parent.uuid), key, index, ))
            # 1 2 3 (4) 5 6 7 => 1 2 3 -4 -5 -6 => 1 2 3 4 5 6
            self.execute(c, "UPDATE relationships SET item_index = -(item_index - 1) WHERE parent_uuid=? AND key=? AND item_index > ?", (str(parent.uuid), key, index, ))
            self.execute(c, "UPDATE relationships SET item_index = -item_index WHERE parent_uuid=? AND key=? AND item_index <= -?", (str(parent.uuid), key, index, ))
            self.__remove_node_ref(item_uuid)
            self.__item_index_integrity_check(c, parent.uuid)
            self.conn.commit()

    def set_property(self, item, key, value):
        if not self.disconnected:
            c = self.conn.cursor()
            self.execute(c, "INSERT OR REPLACE INTO properties (uuid, key, value) VALUES (?, ?, ?)", (str(item.uuid), key, sqlite3.Binary(pickle.dumps(value, pickle.HIGHEST_PROTOCOL)), ))
            self.conn.commit()

    def set_data(self, parent, key, data):
        if not self.disconnected:
            c = self.conn.cursor()
            self.execute(c, "INSERT OR REPLACE INTO data (uuid, key, data) VALUES (?, ?, ?)", (str(parent.uuid), key, sqlite3.Binary(pickle.dumps(data, pickle.HIGHEST_PROTOCOL)), ))
            self.conn.commit()


class DbStorageWriterProxy(object):

    def __init__(self, db_filename):
        self.storage_writer = None
        self.queue = Queue.Queue()
        self.__started_event = threading.Event()
        self.__thread = threading.Thread(target=self.__run, args=[db_filename])
        self.__thread.daemon = True
        self.__thread.start()
        self.__started_event.wait()

    def close(self):
        self.queue.put(None)

    def __run(self, db_filename):
        self.storage_writer = DbStorageWriter(db_filename)
        self.__started_event.set()
        while True:
            action = self.queue.get()
            item = action[0]
            event = action[1]
            action_name = action[2]
            if item:
                try:
                    #logging.debug("EXECUTE %s", action_name)
                    item()
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    logging.debug("DB Error: %s", e)
                finally:
                    #logging.debug("FINISH")
                    event.set()
            self.queue.task_done()
            if not item:
                break

    def __get_disconnected(self):
        return self.storage_writer.disconnected
    def __set_disconnected(self, disconnected):
        self.storage_writer.disconnected = disconnected
    disconnected = property(__get_disconnected, __set_disconnected)

    def to_string(self):
        event = threading.Event()
        self.queue.put((functools.partial(DbStorageWriter.to_string, self.storage_writer), event, "to_string"))
        event.wait()
        str = self.storage_writer.last_to_string
        self.storage_writer.last_to_string = None
        return str

    def create(self):
        event = threading.Event()
        self.queue.put((functools.partial(DbStorageWriter.create, self.storage_writer), event, "create"))
        #event.wait()

    def begin_rewrite(self):
        event = threading.Event()
        self.queue.put((functools.partial(DbStorageWriter.begin_rewrite, self.storage_writer), event, "begin_rewrite"))
        #event.wait()

    def end_rewrite(self):
        event = threading.Event()
        self.queue.put((functools.partial(DbStorageWriter.end_rewrite, self.storage_writer), event, "end_rewrite"))
        #event.wait()

    def set_root(self, root):
        event = threading.Event()
        self.queue.put((functools.partial(DbStorageWriter.set_root, self.storage_writer, root), event, "set_root"))
        #event.wait()

    def set_type(self, item, type):
        event = threading.Event()
        self.queue.put((functools.partial(DbStorageWriter.set_type, self.storage_writer, item, type), event, "set_type"))
        #event.wait()

    def set_item(self, parent, key, item):
        event = threading.Event()
        self.queue.put((functools.partial(DbStorageWriter.set_item, self.storage_writer, parent, key, item), event, "set_item"))
        #event.wait()

    def clear_item(self, parent, key):
        event = threading.Event()
        self.queue.put((functools.partial(DbStorageWriter.clear_item, self.storage_writer, parent, key), event, "clear_item"))
        #event.wait()

    def insert_item(self, parent, key, item, before):
        event = threading.Event()
        self.queue.put((functools.partial(DbStorageWriter.insert_item, self.storage_writer, parent, key, item, before), event, "insert_item"))
        #event.wait()

    def remove_item(self, parent, key, index):
        event = threading.Event()
        self.queue.put((functools.partial(DbStorageWriter.remove_item, self.storage_writer, parent, key, index), event, "remove_item"))
        #event.wait()

    def set_property(self, item, key, value):
        event = threading.Event()
        self.queue.put((functools.partial(DbStorageWriter.set_property, self.storage_writer, item, key, value), event, "set_property"))
        #event.wait()

    def set_data(self, parent, key, data):
        event = threading.Event()
        self.queue.put((functools.partial(DbStorageWriter.set_data, self.storage_writer, parent, key, data), event, "set_data"))
        #event.wait()


class DbStorageReader(object):

    def __init__(self, db_filename):
        self.conn = sqlite3.connect(db_filename)
        self.__item_map = {}
        self.need_rewrite = False

    def from_string(self, str):
        self.conn.cursor().executescript(str)
        self.conn.commit()
        self.conn.row_factory = sqlite3.Row

    def print_counts(self):
        c = self.conn.cursor()
        if False:
            c.execute("SELECT * FROM nodes")
            for row in c.fetchall():
                logging.debug(str(row))
                for key in row.keys():
                    logging.debug("%s: %s", key, row[key])
        c.execute("SELECT COUNT(*) FROM nodes")
        logging.debug("nodes: %s", c.fetchone()[0])
        c.execute("SELECT COUNT(*) FROM properties")
        logging.debug("properties: %s", c.fetchone()[0])
        c.execute("SELECT COUNT(*) FROM data")
        logging.debug("data: %s", c.fetchone()[0])
        c.execute("SELECT COUNT(*) FROM relationships")
        logging.debug("relationships: %s", c.fetchone()[0])

    def find_root_node(self, type):
        c = self.conn.cursor()
        c.execute("SELECT uuid FROM nodes WHERE type=? AND refcount=0", (type, ))
        uuid_ = c.fetchone()[0]
        return uuid_, uuid.UUID(uuid_)

    def build_item(self, uuid_):
        item = None
        if uuid_ not in self.__item_map:
            from nion.swift import DataGroup
            from nion.swift import DataItem
            from nion.swift import Graphics
            from nion.swift import Operation
            build_map = {
                "data-group": DataGroup.DataGroup,
                "smart-data-group": DataGroup.SmartDataGroup,
                "data-item": DataItem.DataItem,
                "calibration": DataItem.Calibration,
                "line-graphic": Graphics.LineGraphic,
                "rect-graphic": Graphics.RectangleGraphic,
                "ellipse-graphic": Graphics.EllipseGraphic,
                "fft-operation": Operation.FFTOperation,
                "inverse-fft-operation": Operation.IFFTOperation,
                "invert-operation": Operation.InvertOperation,
                "gaussian-blur-operation": Operation.GaussianBlurOperation,
                "resample-operation": Operation.Resample2dOperation,
                "crop-operation": Operation.Crop2dOperation,
                "histogram-operation": Operation.HistogramOperation,
                "line-profile-operation": Operation.LineProfileOperation,
                "convert-to-scalar-operation": Operation.ConvertToScalarOperation,
            }
            c = self.conn.cursor()
            c.execute("SELECT type FROM nodes WHERE uuid=?", (uuid_, ))
            type = c.fetchone()[0]
            if type in build_map:
                item = build_map[type].build(self, uuid_)
                item._set_uuid(uuid.UUID(uuid_))
            if item:
                self.__item_map[uuid_] = item
            else:
                logging.debug("Unable to build %s", type)
        else:
            item = self.__item_map[uuid_]
        return item

    def has_data(self, parent_node, key):
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) FROM data WHERE uuid=? AND key=?", (str(parent_node), key, ))
        return c.fetchone()[0] > 0

    def has_item(self, parent_node, key):
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) FROM items WHERE uuid=? AND key=?", (str(parent_node), key, ))
        return c.fetchone()[0] > 0

    def has_relationship(self, parent_node, key):
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) FROM relationships WHERE parent_uuid=? AND key=?", (str(parent_node), key, ))
        return c.fetchone()[0] > 0

    def get_item(self, parent_node, key, default_value=None):
        c = self.conn.cursor()
        c.execute("SELECT item_uuid FROM items WHERE parent_uuid=? AND key=?", (str(parent_node), key, ))
        value_row = c.fetchone()
        if value_row is not None:
            item = self.build_item(value_row[0])
            return item
        return default_value

    def get_items(self, parent_node, key):
        c = self.conn.cursor()
        c.execute("SELECT item_uuid FROM relationships WHERE parent_uuid=? AND key=? ORDER BY item_index ASC", (str(parent_node), key, ))
        items = []
        for row in c.fetchall():
            item = self.build_item(row[0])
            if item:
                if item not in items:  # this is a recoverable error condition
                    items.append(item)
                else:
                    logging.debug("Duplicate item %s (%s)", item, parent_node)
                    self.need_rewrite = True
        #items = [self.build_item(row[0]) for row in c.fetchall()]
        return items

    def get_property(self, parent_node, key, default_value=None):
        c = self.conn.cursor()
        c.execute("SELECT value FROM properties WHERE uuid=? AND key=?", (parent_node, key, ))
        value_row = c.fetchone()
        if value_row is not None:
            return pickle.loads(str(value_row[0]))
        else:
            return default_value

    def get_data(self, parent_node, key, default_value=None):
        c = self.conn.cursor()
        c.execute("SELECT data FROM data WHERE uuid=? AND key=?", (parent_node, key, ))
        data_row = c.fetchone()
        if data_row:
            return pickle.loads(str(data_row[0]))
        else:
            return default_value


class DictStorageCache(object):
    def __init__(self):
        self.__cache = dict()
        self.__cache_dirty = dict()

    def set_cached_value(self, object, key, value, dirty=False):
        cache = self.__cache.setdefault(object.uuid, dict())
        cache_dirty = self.__cache_dirty.setdefault(object.uuid, dict())
        cache[key] = value
        cache_dirty[key] = False

    def get_cached_value(self, object, key, default_value=None):
        cache = self.__cache.setdefault(object.uuid, dict())
        return cache.get(key, default_value)

    def remove_cached_value(self, object, key):
        cache = self.__cache.setdefault(object.uuid, dict())
        cache_dirty = self.__cache_dirty.setdefault(object.uuid, dict())
        if key in cache:
            del cache[key]
        if key in cache_dirty:
            del cache_dirty[key]

    def is_cached_value_dirty(self, object, key):
        cache_dirty = self.__cache_dirty.setdefault(object.uuid, dict())
        return cache_dirty[key] if key in cache_dirty else True

    def set_cached_value_dirty(self, object, key, dirty=True):
        cache_dirty = self.__cache_dirty.setdefault(object.uuid, dict())
        cache_dirty[key] = dirty


class DbStorageCache(object):
    def __init__(self, cache_filename):
        self.queue = Queue.Queue()
        self.__started_event = threading.Event()
        self.__thread = threading.Thread(target=self.__run, args=[cache_filename])
        self.__thread.daemon = True
        self.__thread.start()
        self.__started_event.wait()

    def close(self):
        self.queue.put(None)

    def __run(self, cache_filename):
        self.conn = sqlite3.connect(cache_filename)
        self.create()
        self.__started_event.set()
        while True:
            action = self.queue.get()
            item = action[0]
            result = action[1]
            event = action[2]
            action_name = action[3]
            if item:
                try:
                    #logging.debug("EXECUTE %s", action_name)
                    if result is not None:
                        result.append(item())
                    else:
                        item()
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    logging.debug("DB Error: %s", e)
                finally:
                    #logging.debug("FINISH")
                    if event:
                        event.set()
            self.queue.task_done()
            if not item:
                break

    def create(self):
        c = self.conn.cursor()
        self.execute(c, "CREATE TABLE IF NOT EXISTS cache(uuid STRING, key STRING, value BLOB, dirty INTEGER, PRIMARY KEY(uuid, key))")
        self.conn.commit()

    def execute(self, c, stmt, args=None, log=False):
        if args:
            c.execute(stmt, args)
            if log:
                logging.debug("%s [%s]", stmt, args)
        else:
            c.execute(stmt)
            if log:
                logging.debug("%s", stmt)

    def __set_cached_value(self, object, key, value, dirty=False):
        c = self.conn.cursor()
        self.execute(c, "INSERT OR REPLACE INTO cache (uuid, key, value, dirty) VALUES (?, ?, ?, ?)", (str(object.uuid), key, sqlite3.Binary(pickle.dumps(value, pickle.HIGHEST_PROTOCOL)), 1 if dirty else 0))
        self.conn.commit()

    def __get_cached_value(self, object, key, default_value=None):
        c = self.conn.cursor()
        self.execute(c, "SELECT value FROM cache WHERE uuid=? AND key=?", (str(object.uuid), key))
        value_row = c.fetchone()
        if value_row is not None:
            return pickle.loads(str(value_row[0]))
        else:
            return default_value

    def __remove_cached_value(self, object, key):
        c = self.conn.cursor()
        self.execute(c, "DELETE FROM cache WHERE uuid=? AND key=?", (str(object.uuid), key))
        self.conn.commit()

    def __is_cached_value_dirty(self, object, key):
        c = self.conn.cursor()
        self.execute(c, "SELECT dirty FROM cache WHERE uuid=? AND key=?", (str(object.uuid), key))
        value_row = c.fetchone()
        if value_row is not None:
            return value_row[0] != 0
        else:
            return True

    def __set_cached_value_dirty(self, object, key, dirty=True):
        c = self.conn.cursor()
        self.execute(c, "UPDATE cache SET dirty=? WHERE uuid=? AND key=?", (1 if dirty else 0, str(object.uuid), key))
        self.conn.commit()

    def set_cached_value(self, object, key, value, dirty=False):
        event = threading.Event()
        self.queue.put((functools.partial(self.__set_cached_value, object, key, value, dirty), None, event, "set_cached_value"))
        event.wait()

    def get_cached_value(self, object, key, default_value=None):
        event = threading.Event()
        result = list()
        self.queue.put((functools.partial(self.__get_cached_value, object, key, default_value), result, event, "get_cached_value"))
        event.wait()
        return result[0] if len(result) > 0 else None

    def remove_cached_value(self, object, key):
        event = threading.Event()
        self.queue.put((functools.partial(self.__remove_cached_value, object, key), None, event, "remove_cached_value"))
        event.wait()

    def is_cached_value_dirty(self, object, key):
        event = threading.Event()
        result = list()
        self.queue.put((functools.partial(self.__is_cached_value_dirty, object, key), result, event, "is_cached_value_dirty"))
        event.wait()
        return result[0]

    def set_cached_value_dirty(self, object, key, dirty=True):
        event = threading.Event()
        self.queue.put((functools.partial(self.__set_cached_value_dirty, object, key, dirty), None, event, "set_cached_value_dirty"))
        event.wait()
