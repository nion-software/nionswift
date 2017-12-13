"""
    FilterPanel contains classes the implement the tracking of filters for the data panel.
"""

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
from nion.utils import ListModel

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


class FilterController:

    """
        The FilterController creates, updates, and provides access to an item model controller.

        An item model controller is the controller associated with the UI system for displaying trees.

        The item model controller represents the years, months, and days available within the list of
        data items.
    """

    def __init__(self, document_controller):
        self.ui = document_controller.ui
        self.__periodic_listener = document_controller.add_periodic(1.0, self.__periodic)
        self.item_model_controller = self.ui.create_item_model_controller(["display"])
        self.__document_controller_weakref = weakref.ref(document_controller)

        self.__data_item_tree = TreeNode(reversed=True)
        self.__data_item_tree_mutex = threading.RLock()

        self.__data_item_tree.child_inserted = self.__insert_child
        self.__data_item_tree.child_removed = self.__remove_child
        self.__data_item_tree.tree_node_updated = self.__update_tree_node

        # thread safe.
        def data_item_inserted(key, data_item, before_index):
            """
                This method will be called from the data item list model, which comes from the document controller to
                notify that the list of data items in the document has changed.
                This method breaks the date-related metadata out into a list of indexes which are then displayed
                in tree format for the date browser. in this case, the indexes are added.
            """
            assert threading.current_thread() == threading.main_thread()
            with self.__data_item_tree_mutex:
                created_local = data_item.created_local
                indexes = created_local.year, created_local.month, created_local.day
                self.__data_item_tree.insert_value(indexes, data_item)

        # thread safe.
        def data_item_removed(key, data_item, index):
            """
                This method will be called from the data item list model, which comes from the document controller to
                notify that the list of data items in the document has changed.
                This method breaks the date-related metadata out into a list of indexes which are then displayed
                in tree format for the date browser. in this case, the indexes are removed.
            """
            assert threading.current_thread() == threading.main_thread()
            with self.__data_item_tree_mutex:
                created = data_item.created_local
                indexes = created.year, created.month, created.day
                self.__data_item_tree.remove_value(indexes, data_item)

        # connect the data_items_model from the document controller to self.
        # when data items are inserted or removed from the document controller, the inserter and remover methods
        # will be called.
        self.__data_items_model = document_controller.data_items_model

        self.__library_item_inserted_listener = self.__data_items_model.item_inserted_event.listen(data_item_inserted)
        self.__library_item_removed_listener = self.__data_items_model.item_removed_event.listen(data_item_removed)

        self.__mapping = dict()
        self.__mapping[id(self.__data_item_tree)] = self.item_model_controller.root
        self.__node_counts_dirty = False

        self.__date_filter = None
        self.__text_filter = None

        for index, data_item in enumerate(self.__data_items_model.data_items):
            data_item_inserted("data_items", data_item, index)

    def close(self):
        # Close the data model controller. Un-listen to the data item list model and close the item model controller.
        self.__library_item_inserted_listener.close()
        self.__library_item_inserted_listener = None
        self.__library_item_removed_listener.close()
        self.__library_item_removed_listener = None
        self.__periodic_listener.close()
        self.__periodic_listener = None
        self.item_model_controller.close()
        self.item_model_controller = None

    @property
    def document_controller(self):
        return self.__document_controller_weakref()

    def __periodic(self):
        self.update_all_nodes()

    def __display_for_tree_node(self, tree_node):
        """ Return the text display for the given tree node. Based on number of keys associated with tree node. """
        keys = tree_node.keys
        if len(keys) == 1:
            return "{0} ({1})".format(tree_node.keys[-1], tree_node.count)
        elif len(keys) == 2:
            months = (_("January"), _("February"), _("March"), _("April"), _("May"), _("June"), _("July"), _("August"),
                      _("September"), _("October"), _("November"), _("December"))
            return "{0} ({1})".format(months[max(min(tree_node.keys[1]-1, 11), 0)], tree_node.count)
        else:
            weekdays = (_("Monday"), _("Tuesday"), _("Wednesday"), _("Thursday"), _("Friday"), _("Saturday"), _("Sunday"))
            date = datetime.date(tree_node.keys[0], tree_node.keys[1], tree_node.keys[2])
            return "{0} - {1} ({2})".format(tree_node.keys[2], weekdays[date.weekday()], tree_node.count)

    def __insert_child(self, parent_tree_node, index, tree_node):
        """
            Called from the root tree node when a new node is inserted into tree. This method creates properties
            to represent the node for display and inserts it into the item model controller.
        """
        # manage the item model
        parent_item = self.__mapping[id(parent_tree_node)]
        self.item_model_controller.begin_insert(index, index, parent_item.row, parent_item.id)
        properties = {
            "display": self.__display_for_tree_node(tree_node),
            "tree_node": tree_node  # used for removal and other lookup
        }
        item = self.item_model_controller.create_item(properties)
        parent_item.insert_child(index, item)
        self.__mapping[id(tree_node)] = item
        self.item_model_controller.end_insert()

    def __remove_child(self, parent_tree_node, index):
        """
            Called from the root tree node when a node is removed from the tree. This method removes it into the
            item model controller.
        """
        # get parent and item
        parent_item = self.__mapping[id(parent_tree_node)]
        # manage the item model
        self.item_model_controller.begin_remove(index, index, parent_item.row, parent_item.id)
        child_item = parent_item.children[index]
        parent_item.remove_child(child_item)
        self.__mapping.pop(id(child_item.data["tree_node"]))
        self.item_model_controller.end_remove()

    def __update_tree_node(self, tree_node):
        """ Mark the fact that tree node counts need updating when convenient. """
        self.__node_counts_dirty = True

    def update_all_nodes(self):
        """ Update all tree item displays if needed. Usually for count updates. """
        item_model_controller = self.item_model_controller
        if item_model_controller:
            if self.__node_counts_dirty:
                for item in self.__mapping.values():
                    if "tree_node" in item.data:  # don't update the root node
                        tree_node = item.data["tree_node"]
                        item.data["display"] = self.__display_for_tree_node(tree_node)
                        item_model_controller.data_changed(item.row, item.parent.row, item.parent.id)
                self.__node_counts_dirty = False

    def date_browser_selection_changed(self, selected_indexes):
        """
            Called to handle selection changes in the tree widget.

            This method should be connected to the on_selection_changed event. This method builds a list
            of keys represented by all selected items. It then provides date_filter to filter data items
            based on the list of keys. It then sets the filter into the document controller.

            :param selected_indexes: The selected indexes
            :type selected_indexes: list of ints
        """
        partial_date_filters = list()

        for index, parent_row, parent_id in selected_indexes:
            item_model_controller = self.item_model_controller
            tree_node = item_model_controller.item_value("tree_node", index, parent_id)
            partial_date_filters.append(ListModel.PartialDateFilter("created_local", *tree_node.keys))

        if len(partial_date_filters) > 0:
            self.__date_filter = ListModel.OrFilter(partial_date_filters)
        else:
            self.__date_filter = None

        self.__update_filter()

    def text_filter_changed(self, text):
        """
            Called to handle changes to the text filter.

            :param text: The text for the filter.
        """
        text = text.strip() if text else None

        if text is not None:
            self.__text_filter = ListModel.TextFilter("text_for_filter", text)
        else:
            self.__text_filter = None

        self.__update_filter()

    def __update_filter(self):
        """
            Create a combined filter. Set the resulting filter into the document controller.
        """
        filters = list()
        if self.__date_filter:
            filters.append(self.__date_filter)
        if self.__text_filter:
            filters.append(self.__text_filter)
        self.document_controller.display_filter = ListModel.AndFilter(filters)


class FilterPanel:

    """
        A object to hold the widget for the filter panel.
    """

    def __init__(self, document_controller):

        ui = document_controller.ui
        self.document_controller = document_controller

        self.__filter_controller = self.document_controller.filter_controller

        date_browser_tree_widget = ui.create_tree_widget()
        date_browser_tree_widget.selection_mode = "extended"
        date_browser_tree_widget.item_model_controller = self.__filter_controller.item_model_controller
        date_browser_tree_widget.on_selection_changed = self.__filter_controller.date_browser_selection_changed

        date_browser = ui.create_column_widget()
        date_browser.add(ui.create_label_widget(_("Date"), properties={"stylesheet": "font-weight: bold"}))
        date_browser.add(date_browser_tree_widget)
        date_browser.add_stretch()

        header_canvas_item = Panel.HeaderCanvasItem(document_controller, _("Filter"))

        header_widget = ui.create_canvas_widget(properties={"height": header_canvas_item.header_height})
        header_widget.canvas_item.add_canvas_item(header_canvas_item)

        filter_bar_row = ui.create_row_widget()
        filter_bar_row.add(ui.create_label_widget(_("Search")))
        filter_text_widget = ui.create_line_edit_widget(properties={"width": 160})
        filter_text_widget.placeholder_text = _("No Filter")
        filter_text_widget.on_text_edited = self.__filter_controller.text_filter_changed
        clear_filter_text_widget = ui.create_push_button_widget(_("Clear"))
        def clear_filter():
            filter_text_widget.text = ""
            self.__filter_controller.text_filter_changed("")
        clear_filter_text_widget.on_clicked = clear_filter
        filter_bar_row.add_spacing(8)
        filter_bar_row.add(filter_text_widget)
        filter_bar_row.add_spacing(8)
        filter_bar_row.add(clear_filter_text_widget)
        filter_bar_row.add_stretch()

        filter_column = ui.create_column_widget(properties={"height": 180})
        filter_column.add(header_widget)
        filter_column.add_spacing(4)
        filter_column.add(filter_bar_row)
        filter_column.add_spacing(4)
        filter_column.add(date_browser)
        filter_column.add_spacing(4)

        self.widget = filter_column


class TreeNode:

    """
        Represents a node in a tree, used for implementing data item filters.

        Tracks cumulative child count.
    """

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
        return "{0}/{1}:{2}{3}".format(self.key, self.count, " {0}".format(self.children) if self.children else str(),
                                       " <{0}>".format(len(self.values)) if self.values else str())

    def __get_parent(self):
        """
            Return the parent tree node, if any. Read only.

            :return: The parent tree node
            :rtype: :py:class:`nion.swift.FilterPanel.TreeNode`
        """
        return self.__weak_parent() if self.__weak_parent else None
    parent = property(__get_parent)

    def __set_parent(self, parent):
        """ Set the parent tree node. Private. """
        self.__weak_parent = weakref.ref(parent) if parent else None

    def __get_keys(self):
        """ Return the keys associated with this node by adding its key and then adding parent keys recursively. """
        keys = list()
        tree_node = self
        while tree_node is not None and tree_node.key is not None:
            keys.insert(0, tree_node.key)
            tree_node = tree_node.parent
        return keys
    keys = property(__get_keys)

    def insert_value(self, keys, value):
        """
            Insert a value (data item) into this tree node and then its
            children. This will be called in response to a new data item being
            inserted into the document. Also updates the tree node's cumulative
            child count.
        """
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
        """
            Remove a value (data item) from this tree node and its children.
            Also updates the tree node's cumulative child count.
        """
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
