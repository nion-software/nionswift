# standard libraries
import bisect
import collections
import gettext
import logging

# third party libraries
# None

# local libraries
from nion.swift import Panel
from nion.ui import UserInterfaceUtility

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

class FilterPanel(object):

    def __init__(self, document_controller):

        self.ui = document_controller.ui
        self.document_controller = document_controller

        def toggle_filter(check_state):
            data_panel_dock_widget = self.document_controller.workspace.find_dock_widget("data-panel")
            if data_panel_dock_widget:
                data_panel = data_panel_dock_widget.panel
                def g_filter(data_item):
                    return data_item.title.startswith("G")
                logging.debug("data panel %s %s", data_panel, check_state)
                if check_state == "unchecked":
                    data_panel.display_filter = None
                else:
                    data_panel.display_filter = g_filter

        filter_row = self.ui.create_column_widget()
        filter_column = self.ui.create_row_widget()
        filter_column.add_spacing(12)
        filter_check_box = self.ui.create_check_box_widget(_("Check Me"))
        filter_check_box.on_check_state_changed = toggle_filter
        filter_column.add(filter_check_box)
        filter_column.add_stretch()

        self.header_widget_controller = Panel.HeaderWidgetController(self.ui, _("Filter"))

        filter_row.add(self.header_widget_controller.canvas_widget)
        filter_row.add_spacing(4)
        filter_row.add(filter_column)
        filter_row.add_spacing(4)

        self.widget = filter_row


def index(a, x):
    'Locate the leftmost value exactly equal to x'
    i = bisect.bisect_left(a, x)
    if i != len(a) and a[i] == x:
        return i
    raise ValueError


def contains(a, x):
    'Returns whether list contains value exactly equal to x'
    i = bisect.bisect_left(a, x)
    return i != len(a) and a[i] == x


def find(a, x):
    'Index the leftmost value exactly equal to x or -1'
    i = bisect.bisect_left(a, x)
    if i != len(a) and a[i] == x:
        return i
    return -1


class TreeNode(object):
    def __init__(self, key=None, children=None, values=None):
        self.key = key
        self.count = 0
        self.children = children if children is not None else list()
        self.values = values if values is not None else list()
        self.__value_reverse_mapping = dict()
    def __lt__(self, other):
        return self.key < other.key
    def __le__(self, other):
        return self.key <= other.key
    def __eq__(self, other):
        return self.key == other.key
    def __ne__(self, other):
        return self.key != other.key
    def __gt__(self, other):
        return self.key > other.key
    def __ge__(self, other):
        return self.key >= other.key
    def __hash__(self):
        return self.key.__hash__()
    def __repr__(self):
        return "{0}/{1}:{2}{3}".format(self.key, self.count, " {0}".format(self.children) if self.children else str(), " <{0}>".format(self.values) if self.values else str())
    def insert_value(self, keys, value):
        self.count += 1
        if not self.key:
            self.__value_reverse_mapping[value] = keys
        if len(keys) == 0:
            self.values.append(value)
        else:
            key = keys[0]
            index = bisect.bisect_left(self.children, TreeNode(key))
            if index == len(self.children) or self.children[index].key != key:
                self.children.insert(index, TreeNode(key, list()))
            self.children[index].insert_value(keys[1:], value)
    def remove_value(self, keys, value):
        self.count -= 1
        if not self.key:
            keys = self.__value_reverse_mapping[value]
            del self.__value_reverse_mapping[value]
        if len(keys) == 0:
            self.values.remove(value)
        else:
            key = keys[0]
            index = bisect.bisect_left(self.children, TreeNode(key))
            assert index != len(self.children) and self.children[index].key == key
            self.children[index].remove_value(keys[1:], value)
            if self.children[index].count == 0:
                del self.children[index]


class DataItemDateTreeBinding(UserInterfaceUtility.Binding):

    def __init__(self):
        super(DataItemDateTreeBinding, self).__init__(None)
        self.__data_item_tree = TreeNode()
        self.__master_data_items = list()
        self.__update_mutex = threading.RLock()

    # thread safe.
    def data_item_inserted(self, data_item, before_index):
        with self.__update_mutex:
            assert data_item not in self.__master_data_items
            self.__master_data_items.insert(before_index, data_item)
            data_item_datetime = Utility.get_datetime_from_datetime_element(data_item.datetime_original)
            indexes = data_item_datetime.year, data_item_datetime.month, data_item_datetime.day
            self.__data_item_tree.insert_value(indexes, data_item)

    # thread safe.
    def data_item_removed(self, data_item, index):
        with self.__update_mutex:
            assert data_item in self.__master_data_items
            del self.__master_data_items[index]
            data_item_datetime = Utility.get_datetime_from_datetime_element(data_item.datetime_original)
            indexes = data_item_datetime.year, data_item_datetime.month, data_item_datetime.day
            self.__data_item_tree.remove_value(indexes, data_item)
