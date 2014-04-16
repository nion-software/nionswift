# standard libraries
import bisect
import datetime
import gettext
import threading
import weakref

# third party libraries
# None

# local libraries
from nion.swift import Panel
from nion.swift.model import Utility
from nion.ui import Binding

_ = gettext.gettext


# TODO: Add button to convert between (filter <-> smart group) -> regular group
# TODO: Add tree browser for sessions, organized by date
# TODO: Add tree browser for date
# TODO: Add list browser for users
# TODO: Add list browser for devices
# TODO: Add checkbox browser for flagged / not flagged
# TODO: Add star browser for rating
# TODO: Add tree browser for keywords
# TODO: Add text field browser for searching


class DataItemDateTreeBinding(Binding.Binding):

    def __init__(self):
        super(DataItemDateTreeBinding, self).__init__(None)
        self.__data_item_tree = TreeNode(reversed=True)
        self.__master_data_items = list()
        self.__update_mutex = threading.RLock()

    def __get_tree_node(self):
        return self.__data_item_tree
    tree_node = property(__get_tree_node)

    # thread safe.
    def data_item_inserted(self, data_item, before_index):
        with self.__update_mutex:
            assert data_item not in self.__master_data_items
            self.__master_data_items.insert(before_index, data_item)
            data_item_datetime = Utility.get_datetime_from_datetime_item(data_item.datetime_original)
            indexes = data_item_datetime.year, data_item_datetime.month, data_item_datetime.day
            self.__data_item_tree.insert_value(indexes, data_item)

    # thread safe.
    def data_item_removed(self, data_item, index):
        with self.__update_mutex:
            assert data_item in self.__master_data_items
            del self.__master_data_items[index]
            data_item_datetime = Utility.get_datetime_from_datetime_item(data_item.datetime_original)
            indexes = data_item_datetime.year, data_item_datetime.month, data_item_datetime.day
            self.__data_item_tree.remove_value(indexes, data_item)


class DateModelController(object):

    def __init__(self, document_controller):
        self.ui = document_controller.ui
        self.item_model_controller = self.ui.create_item_model_controller(["display"])
        self.__document_controller_weakref = weakref.ref(document_controller)
        self.__date_binding = DataItemDateTreeBinding()
        self.__date_binding.tree_node.child_inserted = lambda parent_tree_node, index, tree_node: self.__insert_child(parent_tree_node, index, tree_node)
        self.__date_binding.tree_node.child_removed = lambda parent_tree_node, index: self.__remove_child(parent_tree_node, index)
        self.__date_binding.tree_node.tree_node_updated = lambda tree_node: self.__update_tree_node(tree_node)
        self.__binding = document_controller.data_items_binding
        self.__binding.inserters[id(self)] = lambda data_item, before_index: self.__date_binding.data_item_inserted(data_item, before_index)
        self.__binding.removers[id(self)] = lambda data_item, index: self.__date_binding.data_item_removed(data_item, index)
        self.__mapping = dict()
        self.__mapping[id(self.__date_binding.tree_node)] = self.item_model_controller.root

    def close(self):
        del self.__binding.inserters[id(self)]
        del self.__binding.removers[id(self)]
        self.__date_binding.close()
        for item_controller in self.__item_controllers:
            item_controller.close()
        self.__item_controllers = None
        self.item_model_controller.close()
        self.item_model_controller = None

    def periodic(self):
        for item_controller in self.__item_controllers:
            item_controller.periodic()

    def __get_document_controller(self):
        return self.__document_controller_weakref()
    document_controller = property(__get_document_controller)

    def __display_for_tree_node(self, tree_node):
        keys = tree_node.keys
        if len(keys) == 1:
            return "{0} ({1})".format(tree_node.keys[-1], tree_node.count)
        elif len(keys) == 2:
            months = (_("January"), _("February"), _("March"), _("April"), _("May"), _("June"), _("July"), _("August"), _("September"), _("October"), _("November"), _("December"))
            return "{0} ({1})".format(months[max(min(tree_node.keys[1]-1,11), 0)], tree_node.count)
        else:
            weekdays = (_("Monday"), _("Tuesday"), _("Wednesday"), _("Thursday"), _("Friday"), _("Saturday"), _("Sunday"))
            date = datetime.date(tree_node.keys[0], tree_node.keys[1], tree_node.keys[2])
            return "{0} - {1} ({2})".format(tree_node.keys[2], weekdays[date.weekday()], tree_node.count)

    def __insert_child(self, parent_tree_node, index, tree_node):
        # manage the item model
        parent_item = self.__mapping[id(parent_tree_node)]
        self.item_model_controller.begin_insert(index, index, parent_item.row, parent_item.id)
        properties = {
            "display": self.__display_for_tree_node(tree_node),
            "tree_node": tree_node
        }
        item = self.item_model_controller.create_item(properties)
        parent_item.insert_child(index, item)
        self.__mapping[id(tree_node)] = item
        self.item_model_controller.end_insert()

    def __remove_child(self, parent_tree_node, index):
        # get parent and item
        parent_item = self.__mapping[id(parent_tree_node)]
        # manage the item model
        self.item_model_controller.begin_remove(index, index, parent_item.row, parent_item.id)
        child_item = parent_item.children[index]
        parent_item.remove_child(child_item)
        self.__mapping.pop(id(child_item.data["tree_node"]))
        self.item_model_controller.end_remove()

    def __update_tree_node(self, tree_node):
        item = self.__mapping[id(tree_node)]
        item.data["display"] = self.__display_for_tree_node(tree_node)
        self.item_model_controller.data_changed(item.row, item.parent.row, item.parent.id)


class FilterPanel(object):

    def __init__(self, document_controller):

        self.ui = document_controller.ui
        self.document_controller = document_controller

        self.date_model_controller = DateModelController(document_controller)

        def date_browser_selection_changed(selected_indexes):
            keys_list = list()
            for index, parent_row, parent_id in selected_indexes:
                item_model_controller = self.date_model_controller.item_model_controller
                tree_node = item_model_controller.item_value("tree_node", index, parent_id)
                keys_list.append(tree_node.keys)
            def date_filter(data_item):
                data_item_datetime = Utility.get_datetime_from_datetime_item(data_item.datetime_original)
                indexes = data_item_datetime.year, data_item_datetime.month, data_item_datetime.day
                def matches(match_keys):
                    for index, key in enumerate(match_keys):
                        if indexes[index] != key:
                            return False
                    return True
                for keys in keys_list:
                    if matches(keys):
                        return True
                return False
            if len(keys_list) > 0:
                self.document_controller.display_filter = date_filter
            else:
                self.document_controller.display_filter = None

        date_browser_tree_widget = self.ui.create_tree_widget()
        date_browser_tree_widget.selection_mode = "extended"
        date_browser_tree_widget.item_model_controller = self.date_model_controller.item_model_controller
        date_browser_tree_widget.on_selection_changed = date_browser_selection_changed

        date_browser = self.ui.create_column_widget()
        date_browser.add(self.ui.create_label_widget(_("Date"), properties={"stylesheet": "font-weight: bold"}))
        date_browser.add(date_browser_tree_widget)
        date_browser.add_stretch()

        self.header_widget_controller = Panel.HeaderWidgetController(self.ui, _("Filter"))

        filter_row = self.ui.create_column_widget(properties={"height": 200})
        filter_row.add(self.header_widget_controller.canvas_widget)
        filter_row.add_spacing(4)
        filter_row.add(date_browser)
        filter_row.add_spacing(4)

        self.widget = filter_row

    def close(self):
        self.date_model_controller.close()

    def periodic(self):
        self.date_model_controller.periodic()


class TreeNode(object):
    def __init__(self, key=None, children=None, values=None, reversed=False):
        self.key = key
        self.count = 0
        self.reversed = reversed
        self.__weak_parent = None
        self.children = children if children is not None else list()
        self.values = values if values is not None else list()
        self.__value_reverse_mapping = dict()
        self.child_inserted = None
        self.child_removed = None
        self.tree_node_updated = None
    def __lt__(self, other):
        return self.key < other.key if not self.reversed else other.key < self.key
    def __le__(self, other):
        return self.key <= other.key if not self.reversed else other.key <= self.key
    def __eq__(self, other):
        return self.key == other.key
    def __ne__(self, other):
        return self.key != other.key
    def __gt__(self, other):
        return self.key > other.key if not self.reversed else other.key > self.key
    def __ge__(self, other):
        return self.key >= other.key if not self.reversed else other.key >= self.key
    def __hash__(self):
        return self.key.__hash__()
    def __repr__(self):
        return "{0}/{1}:{2}{3}".format(self.key, self.count, " {0}".format(self.children) if self.children else str(), " <{0}>".format(len(self.values)) if self.values else str())
    def __get_parent(self):
        return self.__weak_parent() if self.__weak_parent else None
    parent = property(__get_parent)
    def __set_parent(self, parent):
        self.__weak_parent = weakref.ref(parent) if parent else None
    def __get_keys(self):
        keys = list()
        tree_node = self
        while tree_node is not None and tree_node.key is not None:
            keys.insert(0, tree_node.key)
            tree_node = tree_node.parent
        return keys
    keys = property(__get_keys)
    def insert_value(self, keys, value):
        self.count += 1
        if not self.key:
            self.__value_reverse_mapping[value] = keys
        if len(keys) == 0:
            self.values.append(value)
        else:
            key = keys[0]
            index = bisect.bisect_left(self.children, TreeNode(key, reversed=self.reversed))
            if index == len(self.children) or self.children[index].key != key:
                new_tree_node = TreeNode(key, list(), reversed=self.reversed)
                new_tree_node.child_inserted = self.child_inserted
                new_tree_node.child_removed = self.child_removed
                new_tree_node.tree_node_updated = self.tree_node_updated
                new_tree_node.__set_parent(self)
                self.children.insert(index, new_tree_node)
                if self.child_inserted:
                    self.child_inserted(self, index, new_tree_node)
            child = self.children[index]
            child.insert_value(keys[1:], value)
            if self.tree_node_updated:
                self.tree_node_updated(child)
    def remove_value(self, keys, value):
        self.count -= 1
        if not self.key:
            keys = self.__value_reverse_mapping[value]
            del self.__value_reverse_mapping[value]
        if len(keys) == 0:
            self.values.remove(value)
        else:
            key = keys[0]
            index = bisect.bisect_left(self.children, TreeNode(key, reversed=self.reversed))
            assert index != len(self.children) and self.children[index].key == key
            self.children[index].remove_value(keys[1:], value)
            if self.tree_node_updated:
                self.tree_node_updated(self.children[index])
            if self.children[index].count == 0:
                del self.children[index]
                if self.child_removed:
                    self.child_removed(self, index)
