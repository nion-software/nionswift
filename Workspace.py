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

    def __create_header_widget(self):
        header_height = 20 if sys.platform == "win32" else 22
        canvas = self.ui.create_canvas_widget(properties={"height": header_height})
        layer = canvas.create_layer()
        canvas.on_size_changed = lambda width, height: self.__header_size_changed(canvas, layer, width, height)
        self.__update_header(canvas, layer)
        return canvas

    def __update_header(self, canvas, layer):

        ctx = layer.drawing_context

        ctx.clear()

        ctx.save()
        ctx.beginPath()
        ctx.moveTo(0, 0)
        ctx.lineTo(0, canvas.height)
        ctx.lineTo(canvas.width, canvas.height)
        ctx.lineTo(canvas.width, 0)
        ctx.closePath()
        gradient = ctx.create_linear_gradient(0, 0, 0, canvas.height);
        gradient.add_color_stop(0, '#ededed');
        gradient.add_color_stop(1, '#cacaca');
        ctx.fillStyle = gradient
        ctx.fill()
        ctx.restore()

        ctx.save()
        ctx.beginPath()
        # line is adjust 1/2 pixel down to align to pixel boundary
        ctx.moveTo(0, 0.5)
        ctx.lineTo(canvas.width, 0.5)
        ctx.strokeStyle = '#FFF'
        ctx.stroke()
        ctx.restore()

        ctx.save()
        ctx.beginPath()
        # line is adjust 1/2 pixel down to align to pixel boundary
        ctx.moveTo(0, canvas.height-0.5)
        ctx.lineTo(canvas.width, canvas.height-0.5)
        ctx.strokeStyle = '#b0b0b0'
        ctx.stroke()
        ctx.restore()

        ctx.save()
        ctx.font = 'normal 11px serif'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillStyle = '#000'
        ctx.fillText(_("Data Visualization"), canvas.width/2, canvas.height/2+1)
        ctx.restore()

        canvas.draw()

    def __header_size_changed(self, canvas, layer, width, height):
        if width > 0 and height > 0:
            self.__update_header(canvas, layer)

    def __init__(self, document_controller):
        self.__document_controller_weakref = weakref.ref(document_controller)

        self.ui = self.document_controller.ui

        self.workspace_manager = WorkspaceManager()

        header_height = 20 if sys.platform == "win32" else 22

        self.dock_widgets = []
        self.image_panels = []

        # create the root element
        root_widget = self.ui.create_column_widget(properties={"min-width": 640, "min-height": 480})
        self.image_row = self.ui.create_column_widget()
        root_widget.add(self.__create_header_widget())
        root_widget.add(self.image_row)

        # configure the document window (central widget)
        document_controller.document_window.attach(root_widget)

        self.create_panels()

        layout_id = self.ui.get_persistent_string("Workspace/Layout")

        self.change_layout(layout_id)

        self.restore_content()

    def close(self):
        content_map = {}
        for image_panel in self.image_panels:
            content_map[image_panel.element_id] = image_panel.save_content()
        self.ui.set_persistent_string("Workspace/Content", pickle.dumps(content_map))
        self.ui.set_persistent_string("Workspace/Layout", self.__current_layout_id)
        for dock_widget in copy.copy(self.dock_widgets):
            dock_widget.panel.close()
            dock_widget.close()
        self.dock_widgets = []

    def restore_content(self):
        content_string = self.ui.get_persistent_string("Workspace/Content")
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

    def create_panels(self):
        # get the document controller
        document_controller = self.document_controller

        # add registered panels
        for panel_id in self.workspace_manager.panel_ids:
            title, positions, position, properties = self.workspace_manager.get_panel_info(panel_id)
            if position != "central":
                self.create_panel(document_controller, panel_id, title, positions, position, properties)

        # clean up panels (tabify console/output)
        document_controller.document_window.tabify_dock_widgets(self.find_dock_widget("console-panel"), self.find_dock_widget("output-panel"))

    def create_panel(self, document_controller, panel_id, title, positions, position, properties=None):
        panel = self.workspace_manager.create_panel_content(panel_id, document_controller, properties)
        assert panel is not None, "panel is None [%s]" % panel_id
        assert panel.widget is not None, "panel widget is None [%s]" % panel_id
        dock_widget = document_controller.document_window.create_dock_widget(panel.widget, panel_id, title, positions, position)
        dock_widget.panel = panel
        self.dock_widgets.append(dock_widget)

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
            image_row = self.ui.create_row_widget()
            image_panel = self.__create_image_panel("primary-image")
            image_row.add(image_panel.widget)
            image_panel2 = self.__create_image_panel("secondary-image")
            image_row.add(image_panel2.widget)
            self.image_row.add(image_row)
            self.document_controller.selected_image_panel = image_panel
        elif layout_id == "3x1":
            image_row = self.ui.create_row_widget()
            image_panel = self.__create_image_panel("primary-image")
            image_row.add(image_panel.widget)
            image_panel2 = self.__create_image_panel("secondary-image")
            image_row.add(image_panel2.widget)
            image_panel3 = self.__create_image_panel("3rd-image")
            image_row.add(image_panel3.widget)
            self.image_row.add(image_row)
            self.document_controller.selected_image_panel = image_panel
        elif layout_id == "2x2":
            image_row = self.ui.create_row_widget()
            image_column1 = self.ui.create_column_widget()
            image_column2 = self.ui.create_column_widget()
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
                    for data_group in self.document_controller.data_groups:
                        for data_item in data_group.data_items:
                            if data_item not in displayed_data_items:
                                data_panel_selection = DataItem.DataItemSpecifier(data_group, data_item)
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
            image_panel.data_panel_selection = data_panel_selection
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

    def registerWorkspace(self, workspace):
        workspace_tuple = workspace, workspace.id, workspace.name
        self.__workspace_tuples[workspace.id] = workspace_tuple

    def unregisterWorkspace(self, id):
        del self.__workspace_tuples[id]

    def get_workspace(self):
        tuple = self.__workspace_tuples["default"]
        return tuple[0]
    workspace = property(get_workspace)
