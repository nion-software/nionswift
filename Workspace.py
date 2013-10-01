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
from nion.swift.Decorators import singleton
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


    class Element(object):

        def __init__(self, ui, element_id, properties = None):
            self.ui = ui
            self.element_id = element_id
            self.properties = properties if properties else {}
            self.__weak_container = None
            self.__ref_count = 0

        # Anytime you store a reference to this item, call add_ref.
        # This allows the class to delete its widget when the reference count goes to zero.
        def add_ref(self):
            self.__ref_count += 1

        # Anytime you give up a reference to this item, call remove_ref.
        def remove_ref(self):
            assert self.__ref_count > 0, 'DataItem has no references'
            self.__ref_count -= 1
            if self.__ref_count == 0:
                self.close()

        def descendent(self, element_id):
            if self.element_id == element_id:
                return self
            return None

        def __get_container(self):
            return self.__weak_container() if self.__weak_container else None
        def __set_container(self, container):
            assert container is None or self.__weak_container is None
            self.__weak_container = weakref.ref(container) if container else None
        container = property(__get_container, __set_container)

        def close(self):
            pass


    class Tab(Element):

        # element_id should be unique within the root
        # label should be localized
        # content should be a panel
        # properties is an optional dictionary
        def __init__(self, ui, element_id, label, content, properties = None):
            super(Workspace.Tab, self).__init__(ui, element_id, properties)
            self.label = label
            self.content = content
            self.content.add_ref()
            self.content.container = self
            self.widget = content.widget

        def close(self):
            self.content.container = None
            self.content.remove_ref()
            Workspace.Element.close(self)


    class Box(Element):

        def __init__(self, ui, element_id, properties = None):
            super(Workspace.Box, self).__init__(ui, element_id, properties)
            self.children = []
            self.properties = properties if properties else {}
            self.widget = None

        def descendent(self, element_id):
            if self.element_id == element_id:
                return self
            for child in self.children:
                descendent = child.descendent(element_id)
                if descendent:
                    return descendent
            return None

        def childCount(self):
            return len(self.children)

        def indexOfChild(self, child):
            assert child in self.children
            return self.children.index(child)

        def insertChildAfter(self, child, after):
            index = self.indexOfChild(after)+1
            self.children.insert(index, child)
            child.add_ref()
            child.container = self
            assert self.widget is not None
            assert child.widget is not None
            self.ui.Widget_insertWidget(self.widget, child.widget, index)

        def insertChildBefore(self, child, before):
            index = self.indexOfChild(before)
            self.children.insert(index, child)
            child.add_ref()
            child.container = self
            assert self.widget is not None
            assert child.widget is not None
            self.ui.Widget_insertWidget(self.widget, child.widget, index)

        def addChild(self, child):
            self.children.append(child)
            child.add_ref()
            child.container = self
            assert self.widget is not None
            # temporarily check for child.widget while Qt code is isolated
            if child.widget:
                assert child.widget is not None
                self.ui.Widget_addWidget(self.widget, child.widget)

        def removeChild(self, child):
            assert child in self.children
            self.children.remove(child)
            child.remove_ref()
            child.container = None

        def removeAllChildren(self):
            for child in self.children:
                child.remove_ref()
                child.container = None
            self.children = []

        def close(self):
            self.removeAllChildren()
            self.ui.Widget_removeWidget(self.widget)
            Workspace.Element.close(self)


    class Row(Box):

        def __init__(self, ui, element_id, properties = None):
            super(Workspace.Row, self).__init__(ui, element_id, properties)
            self.widget = self.ui.Widget_loadIntrinsicWidget("row")
            for key in self.properties.keys():
                self.ui.Widget_setWidgetProperty(self.widget, key, self.properties[key])


    class Column(Box):

        def __init__(self, ui, element_id, properties = None):
            super(Workspace.Column, self).__init__(ui, element_id, properties)
            self.widget = self.ui.Widget_loadIntrinsicWidget("column")
            for key in self.properties.keys():
                self.ui.Widget_setWidgetProperty(self.widget, key, self.properties[key])


    def __create_element(self, dict, document_controller):
        #logging.debug("PARSING %s", str(dict))
        element_id = dict["id"]
        if dict["type"] == "row":
            properties = {}
            if "properties" in dict:
                properties = dict["properties"]
            row = Workspace.Row(document_controller.ui, element_id, properties)
            for child_dict in dict["children"]:
                row.addChild(self.__create_element(child_dict, document_controller))
            return row
        if dict["type"] == "column":
            properties = {}
            if "properties" in dict:
                properties = dict["properties"]
            column = Workspace.Column(document_controller.ui, element_id, properties)
            for child_dict in dict["children"]:
                column.addChild(self.__create_element(child_dict, document_controller))
            return column
        if dict["type"] == "tab":
            panel_id = dict["content"]
            label = dict["title"]
            properties = dict["properties"] if "properties" in dict else None
            workspace_manager = WorkspaceManager()
            content = workspace_manager.create_panel_content(panel_id, document_controller)
            assert content is not None, "content is None [%s]" % panel_id
            # temporarily check for content.widget while Qt code is isolated
            if content.widget:
                assert content.widget is not None, "content widget is None [%s]" % panel_id
                if properties:
                    for key in properties.keys():
                        self.ui.Widget_setWidgetProperty(content.widget, key, properties[key])
                self.ui.Widget_setWidgetProperty(content.widget, "title", label)
            return Workspace.Tab(document_controller.ui, element_id, label, content)

    def __descendent(self, dict, test_element_id):
        element_id = dict["id"]
        if element_id == test_element_id:
            return dict
        if dict["type"] == "row" or dict["type"] == "column":
            for child_dict in dict["children"]:
                result = self.__descendent(child_dict, test_element_id)
                if result:
                    return result
            return None
        return None


    def __init__(self, document_controller):
        self.__document_controller_weakref = weakref.ref(document_controller)

        self.ui = self.document_controller.ui

        self.workspace_manager = WorkspaceManager()

        header_height = 20 if sys.platform == "win32" else 22

        self.desc = {
            "type": "column",
            "id": "content-column",
            "properties": { "spacing": 0 },
            "children": [
                {
                    "type": "tab",
                    "id": "primary-header",
                    "content": "header-panel",
                    "title": _("Data Visualization"),
                    "properties": { "height": header_height, "platform": sys.platform }
                },
                {
                    "type": "row",
                    "id": "image-row",
                    "properties": { "spacing": 0 },
                    "children": [
                        {
                            "type": "tab",
                            "id": "primary-image",
                            "content": "image-panel",
                            "title": _("Image"),
                        }
                    ]
                },
            ]
        }

        self.panels = []

        # create the root element
        self.root = self.__create_element(self.desc, document_controller)
        self.root.add_ref()

        # configure the document window (central widget)
        self.ui.DocumentWindow_setCentralWidget(document_controller.document_window, self.root.widget)

        self.ui.Widget_setWidgetProperty(self.root.widget, "min-width", 640)
        self.ui.Widget_setWidgetProperty(self.root.widget, "min-height", 480)

        self.image_panel_tabs = []

        self.create_panels()

        layout_id = self.ui.Settings_getString("Workspace/Layout")

        self.change_layout(layout_id)

        self.restore_content()

    def close(self):
        content_map = {}
        for image_panel_tab in self.image_panel_tabs:
            content_map[image_panel_tab.element_id] = image_panel_tab.content.save_content()
        self.ui.Settings_setString("Workspace/Content", pickle.dumps(content_map))
        self.ui.Settings_setString("Workspace/Layout", self.__current_layout_id)
        for panel in copy.copy(self.panels):
            panel.close()
        self.panels = []

    def restore_content(self):
        content_string = self.ui.Settings_getString("Workspace/Content")
        if content_string:
            content_map = pickle.loads(content_string)
            for image_panel_tab in self.image_panel_tabs:
                if image_panel_tab.element_id in content_map:
                    image_panel_tab.content.restore_content(content_map[image_panel_tab.element_id], self.document_controller)

    def __get_document_controller(self):
        return self.__document_controller_weakref()
    document_controller = property(__get_document_controller)

    def find_panel(self, panel_id):
        for panel in self.panels:
            if panel.panel_id == panel_id:
                return panel
        if self.root:
            return self.root.descendent(panel_id)
        return None

    def create_panels(self):
        # get the document controller
        document_controller = self.document_controller

        # add registered panels
        for panel_id in self.workspace_manager.panel_ids:
            title, positions, position, properties = self.workspace_manager.get_panel_info(panel_id)
            if position != "central":
                self.create_panel(document_controller, panel_id, title, positions, position, properties)

        # clean up panels (tabify console/output)
        self.ui.DocumentWindow_tabifyDockWidgets(document_controller.document_window, self.find_panel("console-panel").widget, self.find_panel("output-panel").widget)

    def create_panel(self, document_controller, panel_id, title, positions, position, properties=None):
        panel = self.workspace_manager.create_panel_content(panel_id, document_controller)
        if properties:
            for key in properties.keys():
                self.ui.Widget_setWidgetProperty(panel.widget, key, properties[key])
        assert panel is not None, "panel is None [%s]" % panel_id
        assert panel.widget is not None, "panel widget is None [%s]" % panel_id
        panel.dock_widget = self.ui.DocumentWindow_addDockWidget(document_controller.document_window, panel.widget, panel_id, title, positions, position)
        self.panels.append(panel)
        panel.add_ref()

    def __create_column(self):
        desc = {
            "type": "column",
            "id": "",
            "properties": { "spacing": 0 },
            "children": []
        }
        return self.__create_element(desc, self.document_controller)

    def __create_image_panel_element(self, image_panel_id=None):
        desc = {
            "type": "tab",
            "id": image_panel_id if image_panel_id else "",
            "content": "image-panel",
            "title": _("Image"),
        }
        return self.__create_element(desc, self.document_controller)

    def change_layout(self, layout_id):
        # remember what's current being displayed
        old_data_panel_selections = []
        for image_panel_tab in self.image_panel_tabs:
            old_data_panel_selections.append(image_panel_tab.content.data_panel_selection)
        # remove existing layout
        image_row = self.find_panel("image-row")
        image_row.removeAllChildren()
        self.image_panel_tabs = []
        # create the new layout
        if layout_id == "2x1":
            element = self.__create_image_panel_element("primary-image")
            self.image_panel_tabs.append(element)
            image_row.addChild(element)
            element2 = self.__create_image_panel_element("secondary-image")
            self.image_panel_tabs.append(element2)
            image_row.addChild(element2)
            self.document_controller.selected_image_panel = element.content
        elif layout_id == "3x1":
            element = self.__create_image_panel_element("primary-image")
            self.image_panel_tabs.append(element)
            image_row.addChild(element)
            element2 = self.__create_image_panel_element("secondary-image")
            self.image_panel_tabs.append(element2)
            image_row.addChild(element2)
            element3 = self.__create_image_panel_element("3rd-image")
            self.image_panel_tabs.append(element3)
            image_row.addChild(element3)
            self.document_controller.selected_image_panel = element.content
        elif layout_id == "2x2":
            column1 = self.__create_column()
            column2 = self.__create_column()
            image_row.addChild(column1)
            image_row.addChild(column2)
            element = self.__create_image_panel_element("primary-image")
            self.image_panel_tabs.append(element)
            column1.addChild(element)
            element2 = self.__create_image_panel_element("secondary-image")
            self.image_panel_tabs.append(element2)
            column1.addChild(element2)
            element3 = self.__create_image_panel_element("3rd-image")
            self.image_panel_tabs.append(element3)
            column2.addChild(element3)
            element4 = self.__create_image_panel_element("4th-image")
            self.image_panel_tabs.append(element4)
            column2.addChild(element4)
            self.document_controller.selected_image_panel = element.content
        else:  # default 1x1
            element = self.__create_image_panel_element("primary-image")
            self.image_panel_tabs.append(element)
            image_row.addChild(element)
            self.document_controller.selected_image_panel = element.content
        # restore what was displayed
        displayed_data_items = []
        last_data_panel_selection = None
        for index, image_panel_tab in enumerate(self.image_panel_tabs):
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
            else:
                # search for next undisplayed data item
                for data_group in self.document_controller.data_groups:
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
            image_panel_tab.content.data_panel_selection = data_panel_selection
        # fill in the missing items if possible
        # save the layout id
        self.__current_layout_id = layout_id


@singleton
class WorkspaceManager(object):
    """
        The WorkspaceManager object keeps a list of workspaces and a list of panel
        types. It also creates workspace objects.
        """
    def __init__(self):
        self.__panel_tuples = {}
        self.__workspace_tuples = {}

    def registerPanel(self, panel_class, panel_id, name, positions, position, properties=None):
        panel_tuple = panel_class, panel_id, name, positions, position, properties
        self.__panel_tuples[panel_id] = panel_tuple

    def unregisterPanel(self, panel_id):
        del self.__panel_tuples[panel_id]

    def create_panel_content(self, panel_id, document_controller):
        if panel_id in self.__panel_tuples:
            tuple = self.__panel_tuples[panel_id]
            cls = tuple[0]
            try:
                panel = cls(document_controller, panel_id)
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

    def registerWorkspace(self, workspace):
        workspace_tuple = workspace, workspace.id, workspace.name
        self.__workspace_tuples[workspace.id] = workspace_tuple

    def unregisterWorkspace(self, id):
        del self.__workspace_tuples[id]

    def get_workspace(self):
        tuple = self.__workspace_tuples["default"]
        return tuple[0]
    workspace = property(get_workspace)
