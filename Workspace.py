# standard libraries
import copy
import cPickle as pickle
import gettext
import logging
import sys
import time
import weakref

# third party libraries
# None

# local libraries
from nion.swift import DataItem
from nion.swift import Decorators
from nion.ui import UserInterface


_ = gettext.gettext


class Workspace(object):
    """
        The Workspace object keeps the overall layout of the window. It contains
        root item which contains tab groups arranged into boxes (rows and columns).
        The boxes contain other boxes or tab groups. Tab groups contain tabs which contain
        a single panel.

        The Workspace is able to save/restore itself from a text stream. It is also able to
        record changes to the workspace from the enclosing application. When restoring its
        layout, it is able to handle cases where the size/shape of the window is different
        from its original size/shape when saved.
    """

    def __init__(self, document_controller, workspace_id):
        self.__document_controller_weakref = weakref.ref(document_controller)

        self.ui = self.document_controller.ui

        self.workspace_manager = WorkspaceManager()

        self.workspace_id = workspace_id

        header_height = 20 if sys.platform == "win32" else 22

        self.dock_widgets = []
        self.image_panels = []

        # create the root element
        root_widget = self.ui.create_column_widget(properties={"min-width": 640, "min-height": 480})
        self.content_row = self.ui.create_column_widget()
        self.filter_row = self.workspace_manager.create_filter_panel(document_controller).widget
        self.image_row = self.ui.create_column_widget()
        self.content_row.add(self.filter_row)
        self.content_row.add(self.image_row, fill=True)
        self.filter_row.visible = False
        root_widget.add(self.content_row)

        # configure the document window (central widget)
        document_controller.document_window.attach(root_widget)

        visible_panels = []
        if self.workspace_id == "library":
            visible_panels = ["image-panel", "toolbar-panel", "data-panel", "histogram-panel", "info-panel", "inspector-panel", "processing-panel", "output-panel"]

        self.create_panels(visible_panels)

        self.__current_layout_id = None

        self.__layout_stack = list()
        self.__layout_stack_current = None

        layout_id = self.ui.get_persistent_string("Workspace/%s/Layout" % self.workspace_id)

        self.change_layout(layout_id)

        self.restore_content()

    def close(self):
        content_map = {}
        for image_panel in self.image_panels:
            content_map[image_panel.element_id] = image_panel.save_content()
        self.ui.set_persistent_string("Workspace/%s/Content" % self.workspace_id, pickle.dumps(content_map))
        self.ui.set_persistent_string("Workspace/%s/Layout" % self.workspace_id, self.__current_layout_id)
        for dock_widget in copy.copy(self.dock_widgets):
            dock_widget.panel.close()
            dock_widget.close()
        self.dock_widgets = []
        self.filter_row.close()

    def periodic(self):
        # for each of the panels too
        for dock_widget in self.dock_widgets:
            start = time.time()
            dock_widget.panel.periodic()
            dock_widget.periodic()
            elapsed = time.time() - start
            if elapsed > 0.05:
                logging.debug("panel %s %s", dock_widget.panel, elapsed)
        self.filter_row.periodic()

    def restore_geometry_state(self):
        geometry = self.ui.get_persistent_string("Workspace/%s/Geometry" % self.workspace_id)
        state = self.ui.get_persistent_string("Workspace/%s/State" % self.workspace_id)
        return geometry, state

    def save_geometry_state(self, geometry, state):
        self.ui.set_persistent_string("Workspace/%s/Geometry" % self.workspace_id, geometry)
        self.ui.set_persistent_string("Workspace/%s/State" % self.workspace_id, state)

    def restore_content(self):
        content_string = self.ui.get_persistent_string("Workspace/%s/Content" % self.workspace_id)
        if content_string:
            content_map = pickle.loads(content_string)
            for image_panel in self.image_panels:
                if image_panel.element_id in content_map:
                    image_panel.restore_content(content_map[image_panel.element_id], self.document_controller)

    def __get_document_controller(self):
        return self.__document_controller_weakref()
    document_controller = property(__get_document_controller)

    def __get_current_layout_id(self):
        return self.__current_layout_id
    current_layout_id = property(__get_current_layout_id)

    def find_dock_widget(self, panel_id):
        for dock_widget in self.dock_widgets:
            if dock_widget.panel.panel_id == panel_id:
                return dock_widget
        return None

    def create_panels(self, visible_panels=None):
        # get the document controller
        document_controller = self.document_controller

        # add registered panels
        for panel_id in self.workspace_manager.panel_ids:
            title, positions, position, properties = self.workspace_manager.get_panel_info(panel_id)
            if position != "central":
                dock_widget = self.create_panel(document_controller, panel_id, title, positions, position, properties)
                if dock_widget:  # could have failed to create due to exception
                    if visible_panels is None or panel_id in visible_panels:
                        dock_widget.show()
                    else:
                        dock_widget.hide()

        # clean up panels (tabify console/output)
        document_controller.document_window.tabify_dock_widgets(self.find_dock_widget("console-panel"), self.find_dock_widget("output-panel"))

    def create_panel(self, document_controller, panel_id, title, positions, position, properties):
        try:
            panel = self.workspace_manager.create_panel_content(panel_id, document_controller, properties)
            assert panel is not None, "panel is None [%s]" % panel_id
            assert panel.widget is not None, "panel widget is None [%s]" % panel_id
            dock_widget = document_controller.document_window.create_dock_widget(panel.widget, panel_id, title, positions, position)
            dock_widget.panel = panel
            self.dock_widgets.append(dock_widget)
            return dock_widget
        except Exception, e:
            import traceback
            traceback.print_exc()
            print "Exception creating panel '" + panel_id + "': " + str(e)
            return None

    def __create_image_panel(self, element_id):
        image_panel = self.workspace_manager.create_panel_content("image-panel", self.document_controller)
        image_panel.title = _("Image")
        image_panel.element_id = element_id
        self.image_panels.append(image_panel)
        return image_panel

    def __get_primary_image_panel(self):
        return self.image_panels[0] if len(self.image_panels) > 0 else None
    primary_image_panel = property(__get_primary_image_panel)

    def change_layout(self, layout_id, preferred_data_items=None, adjust=None):
        # remember what's current being displayed
        old_selected_data_item = self.document_controller.selected_data_item
        old_displayed_data_items = []
        for image_panel in self.image_panels:
            if image_panel.data_item is not None:
                old_displayed_data_items.append(image_panel.data_item)
        # remember the current layout.
        # 1321
        # first store the existing layout in the current slot
        if self.__layout_stack_current is not None:  # handle startup case
            self.__layout_stack[self.__layout_stack_current] = (self.__current_layout_id, [weakref.ref(data_item) for data_item in old_displayed_data_items])
        # now insert new layout placeholder
        if adjust is not None:
            self.__layout_stack_current += adjust
            self.__layout_stack[self.__layout_stack_current] = None
        else:
            del self.__layout_stack[0:self.__layout_stack_current]
            self.__layout_stack.insert(0, None)
            self.__layout_stack_current = 0
        # remove existing layout
        for image_panel in copy.copy(self.image_panels):
            image_panel.close()
        self.image_panels = []
        for child in copy.copy(self.image_row.children):
            self.image_row.remove(child)
        # create the new layout
        if layout_id == "2x1":
            image_row = self.ui.create_splitter_widget("horizontal")
            image_panel = self.__create_image_panel("primary-image")
            image_row.add(image_panel.widget)
            image_panel2 = self.__create_image_panel("secondary-image")
            image_row.add(image_panel2.widget)
            self.image_row.add(image_row)
            self.document_controller.selected_image_panel = image_panel
        elif layout_id == "1x2":
            image_column = self.ui.create_splitter_widget("vertical")
            image_panel = self.__create_image_panel("primary-image")
            image_column.add(image_panel.widget)
            image_panel2 = self.__create_image_panel("secondary-image")
            image_column.add(image_panel2.widget)
            self.image_row.add(image_column)
            self.document_controller.selected_image_panel = image_panel
        elif layout_id == "3x1":
            image_row = self.ui.create_splitter_widget("horizontal")
            image_panel = self.__create_image_panel("primary-image")
            image_row.add(image_panel.widget)
            image_panel2 = self.__create_image_panel("secondary-image")
            image_row.add(image_panel2.widget)
            image_panel3 = self.__create_image_panel("3rd-image")
            image_row.add(image_panel3.widget)
            self.image_row.add(image_row)
            self.document_controller.selected_image_panel = image_panel
        elif layout_id == "2x2":
            image_row = self.ui.create_splitter_widget("horizontal")
            image_column1 = self.ui.create_splitter_widget("vertical")
            image_column2 = self.ui.create_splitter_widget("vertical")
            image_row.add(image_column1)
            image_row.add(image_column2)
            image_panel = self.__create_image_panel("primary-image")
            image_column1.add(image_panel.widget)
            image_panel2 = self.__create_image_panel("secondary-image")
            image_column1.add(image_panel2.widget)
            image_panel3 = self.__create_image_panel("3rd-image")
            image_column2.add(image_panel3.widget)
            image_panel4 = self.__create_image_panel("4th-image")
            image_column2.add(image_panel4.widget)
            self.image_row.add(image_row)
            self.document_controller.selected_image_panel = image_panel
        elif layout_id == "3x2":
            image_row = self.ui.create_splitter_widget("horizontal")
            image_column1 = self.ui.create_splitter_widget("vertical")
            image_column2 = self.ui.create_splitter_widget("vertical")
            image_column3 = self.ui.create_splitter_widget("vertical")
            image_row.add(image_column1)
            image_row.add(image_column2)
            image_row.add(image_column3)
            image_panel = self.__create_image_panel("primary-image")
            image_column1.add(image_panel.widget)
            image_panel2 = self.__create_image_panel("secondary-image")
            image_column1.add(image_panel2.widget)
            image_panel3 = self.__create_image_panel("3rd-image")
            image_column2.add(image_panel3.widget)
            image_panel4 = self.__create_image_panel("4th-image")
            image_column2.add(image_panel4.widget)
            image_panel5 = self.__create_image_panel("5th-image")
            image_column3.add(image_panel5.widget)
            image_panel6 = self.__create_image_panel("6th-image")
            image_column3.add(image_panel6.widget)
            self.image_row.add(image_row)
            self.document_controller.selected_image_panel = image_panel
        else:  # default 1x1
            image_panel = self.__create_image_panel("primary-image")
            self.image_row.add(image_panel.widget)
            if adjust is None and self.document_controller.selected_image_panel is not None:
                preferred_data_items = [old_selected_data_item]
            self.document_controller.selected_image_panel = image_panel
            layout_id = "1x1"  # set this in case it was something else
        # restore what was displayed
        displayed_data_items = []
        # use the preferred data items first
        preferred_data_items = copy.copy(list(preferred_data_items)) if preferred_data_items is not None else list()
        # then for each data item that was already displayed, use it if it's not already in the list
        for old_displayed_data_item in old_displayed_data_items:
            if old_displayed_data_item not in preferred_data_items:
                preferred_data_items.append(old_displayed_data_item)
        # last displayed data item is used to display derived data, if present
        last_displayed_data_item = None
        for index, image_panel in enumerate(self.image_panels):
            data_item_to_display = None
            if len(preferred_data_items) > index and preferred_data_items[index] is not None:
                data_item_to_display = preferred_data_items[index]
                last_displayed_data_item = data_item_to_display
            elif last_displayed_data_item:
                # search for derived data items
                for data_item in last_displayed_data_item.data_items:
                    if data_item not in displayed_data_items:
                        data_item_to_display = data_item
                        break
            if not data_item_to_display:
                # TODO: make this search through the current criteria, such as group or session
                for data_item in self.document_controller.document_model.get_flat_data_item_generator():
                    if data_item not in displayed_data_items:
                        data_item_to_display = data_item
                        break
            # update the data item in the image panel to display it
            image_panel.data_item = data_item_to_display
            displayed_data_items.append(data_item_to_display)
        # fill in the missing items if possible
        # save the layout id
        self.__current_layout_id = layout_id

    def debugit(self):
        logging.debug("self.__layout_stack_current %s", self.__layout_stack_current)
        logging.debug("self.__layout_stack %s", self.__layout_stack)

    def change_to_previous_layout(self):
        if self.__layout_stack_current is not None and self.__layout_stack_current + 1 < len(self.__layout_stack):
            layout_id, preferred_weak_data_items = self.__layout_stack[self.__layout_stack_current + 1]
            preferred_data_items = [preferred_weak_data_item() for preferred_weak_data_item in preferred_weak_data_items]
            self.change_layout(layout_id, preferred_data_items, adjust=1)

    def change_to_next_layout(self):
        if self.__layout_stack_current is not None and self.__layout_stack_current > 0:
            layout_id, preferred_weak_data_items = self.__layout_stack[self.__layout_stack_current - 1]
            preferred_data_items = [preferred_weak_data_item() for preferred_weak_data_item in preferred_weak_data_items]
            self.change_layout(layout_id, preferred_data_items, adjust=-1)

    # display the primary and secondary data item. if only primary is supplied, this
    # method will look for the first non-live slot and place the new data item there.
    # if there is not a non-live slot, it will be placed in the first slot.
    # if primary and secondary are supplied, this method will choose the first non-live
    # slot after the primary. if none, then the first before it. if none, then it will
    # not be displayed.
    # returns the image panel in which the data is placed.
    # TODO: HANDLE CASE WHERE IT IS ALREADY DISPLAYED
    # TODO: PREFER TO USE ACQUISITION SLOTS FIRST, THEN PAUSED ONES
    def display_data_item(self, primary_data_item, source_data_item=None):

        def is_data_item_for_hardware_source(data_item):
            if data_item.is_live:
                return True
            if data_item.properties.get("hardware_source_id") and data_item.session_id == self.document_controller.document_model.session.session_id:
                return True
            return False

        if not source_data_item:
            # first look for exact match
            for image_panel in self.image_panels:
                if image_panel.data_item == primary_data_item:
                    image_panel.set_data_item(primary_data_item)
                    return image_panel
            # now search for an open slot
            for image_panel in self.image_panels:
                if image_panel.data_item and not is_data_item_for_hardware_source(image_panel.data_item):
                    image_panel.set_data_item(primary_data_item)
                    return image_panel
            image_panel = self.image_panels[0]
            image_panel.set_data_item(primary_data_item)
            return image_panel
        elif primary_data_item:
            # first look for exact match
            for image_panel in self.image_panels:
                if image_panel.data_item == primary_data_item:
                    image_panel.set_data_item(primary_data_item)
                    return image_panel
            first_non_live = None
            last_non_live_before_primary = None
            matched = False
            # first search forward from primary
            for image_panel in self.image_panels:
                if image_panel.data_item == source_data_item:
                    matched = True
                if image_panel.data_item and not is_data_item_for_hardware_source(image_panel.data_item):
                    if matched:
                        image_panel.set_data_item(primary_data_item)
                        return image_panel
                    first_non_live = first_non_live if first_non_live else image_panel
                    last_non_live_before_primary = last_non_live_before_primary if matched else image_panel
            # use one before if available
            if last_non_live_before_primary:
                image_panel = last_non_live_before_primary
                image_panel.set_data_item(primary_data_item)
                return image_panel
            # use first one if available
            if first_non_live:
                image_panel = first_non_live
                image_panel.set_data_item(primary_data_item)
                return image_panel
        return None


class WorkspaceManager(object):
    __metaclass__ = Decorators.Singleton

    """
        The WorkspaceManager object keeps a list of workspaces and a list of panel
        types. It also creates workspace objects.
        """
    def __init__(self):
        self.__panel_tuples = {}

    def register_panel(self, panel_class, panel_id, name, positions, position, properties=None):
        panel_tuple = panel_class, panel_id, name, positions, position, properties
        self.__panel_tuples[panel_id] = panel_tuple

    def unregister_panel(self, panel_id):
        del self.__panel_tuples[panel_id]

    def create_panel_content(self, panel_id, document_controller, properties=None):
        if panel_id in self.__panel_tuples:
            tuple = self.__panel_tuples[panel_id]
            cls = tuple[0]
            try:
                properties = properties if properties else {}
                panel = cls(document_controller, panel_id, properties)
                return panel
            except Exception, e:
                import traceback
                traceback.print_exc()
                print "Exception creating panel '" + panel_id + "': " + str(e)
        return None

    def register_filter_panel(self, filter_panel_class):
        self.__filter_panel_class = filter_panel_class

    def create_filter_panel(self, document_controller):
        return self.__filter_panel_class(document_controller)

    def get_panel_info(self, panel_id):
        assert panel_id in self.__panel_tuples
        tuple = self.__panel_tuples[panel_id]
        return tuple[2], tuple[3], tuple[4], tuple[5]

    def __get_panel_ids(self):
        return self.__panel_tuples.keys()
    panel_ids = property(__get_panel_ids)
