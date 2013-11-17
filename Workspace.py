# standard libraries
import copy
import cPickle as pickle
import gettext
import logging
import sys
import weakref

# third party libraries
# None

# local libraries
from nion.swift import DataItem
from nion.swift import Decorators
from nion.swift import UserInterface


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
        self.image_row = self.ui.create_column_widget()
        root_widget.add(self.image_row)

        # configure the document window (central widget)
        document_controller.document_window.attach(root_widget)

        visible_panels = []
        if self.workspace_id == "library":
            visible_panels = ["image-panel", "data-panel", "histogram-panel", "info-panel", "inspector-panel", "processing-panel", "output-panel"]

        self.create_panels(visible_panels)

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

    def change_layout(self, layout_id):
        # remember what's current being displayed
        old_data_panel_selections = []
        for image_panel in self.image_panels:
            old_data_panel_selections.append(image_panel.data_panel_selection)
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
        else:  # default 1x1
            image_panel = self.__create_image_panel("primary-image")
            self.image_row.add(image_panel.widget)
            self.document_controller.selected_image_panel = image_panel
            layout_id = "1x1"  # set this in case it was something else
        # restore what was displayed
        displayed_data_items = []
        last_data_panel_selection = None
        for index, image_panel in enumerate(self.image_panels):
            data_panel_selection = None
            if len(old_data_panel_selections) > index and old_data_panel_selections[index] and not old_data_panel_selections[index].is_empty:
                data_panel_selection = old_data_panel_selections[index]
                last_data_panel_selection = data_panel_selection
            elif last_data_panel_selection and not last_data_panel_selection.is_empty:
                # search for derived data items
                for data_item in last_data_panel_selection.data_item.data_items:
                    if data_item not in displayed_data_items:
                        data_panel_selection = DataItem.DataItemSpecifier(last_data_panel_selection.data_group, data_item)
                        break
                # search for another item in the group
                if not data_panel_selection:
                    for data_item in last_data_panel_selection.data_group.data_items:
                        if data_item not in displayed_data_items:
                            data_panel_selection = DataItem.DataItemSpecifier(last_data_panel_selection.data_group, data_item)
                            break
                # search in another group
                if not data_panel_selection:
                    for data_group in self.document_controller.document_model.data_groups:
                        for data_item in data_group.data_items:
                            if data_item not in displayed_data_items:
                                data_panel_selection = DataItem.DataItemSpecifier(data_group, data_item)
                                break
            else:
                # search for next undisplayed data item
                for data_group in self.document_controller.document_model.data_groups:
                    if data_panel_selection:
                        break
                    for data_item in data_group.data_items:
                        if data_item not in displayed_data_items:
                            data_panel_selection = DataItem.DataItemSpecifier(data_group, data_item)
                            break
            if not data_panel_selection:
                data_panel_selection = DataItem.DataItemSpecifier()
            if not data_panel_selection.is_empty:
                displayed_data_items.append(data_panel_selection.data_item)
            image_panel.data_panel_selection = data_panel_selection
        # fill in the missing items if possible
        # save the layout id
        self.__current_layout_id = layout_id


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

    def get_panel_info(self, panel_id):
        assert panel_id in self.__panel_tuples
        tuple = self.__panel_tuples[panel_id]
        return tuple[2], tuple[3], tuple[4], tuple[5]

    def __get_panel_ids(self):
        return self.__panel_tuples.keys()
    panel_ids = property(__get_panel_ids)
