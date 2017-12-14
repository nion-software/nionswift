# standard libraries
import copy
import gettext
import json
import uuid
import weakref

# third party libraries
# None

# local libraries
from nion.swift import DisplayPanel
from nion.swift.model import Utility
from nion.swift.model import WorkspaceLayout
from nion.ui import CanvasItem


_ = gettext.gettext


class Workspace:
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

        self.dock_widgets = []
        self.display_panels = []

        self.__canvas_item = None

        # create the root element
        root_widget = self.ui.create_column_widget(properties={"min-width": 640, "min-height": 480})
        self.__content_column = self.ui.create_column_widget()
        self.message_column = self.ui.create_column_widget()
        self.filter_panel = self.workspace_manager.create_filter_panel(document_controller)
        self.filter_row = self.filter_panel.widget
        self.image_row = self.ui.create_column_widget()
        self.__content_column.add(self.message_column)
        self.__content_column.add(self.filter_row)
        self.__content_column.add(self.image_row, fill=True)
        self.filter_row.visible = False
        root_widget.add(self.__content_column)

        self.__message_boxes = dict()

        # configure the document window (central widget)
        document_controller.attach_widget(root_widget)

        visible_panels = []
        if self.workspace_id == "library":
            visible_panels = ["toolbar-panel", "data-panel", "histogram-panel", "info-panel", "inspector-panel"]

        self.create_panels(visible_panels)

        self.__workspace = None

    def close(self):
        for message_box_widget in copy.copy(list(self.__message_boxes.values())):
            self.message_column.remove(message_box_widget)
        self.__message_boxes.clear()
        if self.__workspace:
            # TODO: remove this; it should be updated whenever the workspace changes anyway.
            self.__workspace.layout = self._deconstruct(self.__canvas_item.canvas_items[0])
        self.display_panels = []
        self.__canvas_item = None
        self.__workspace = None
        dock_widgets_copy = copy.copy(self.dock_widgets)
        self.dock_widgets = None
        for dock_widget in dock_widgets_copy:
            dock_widget.panel.close()
            # dock_widget.close()  # closed by the panel
        self.__content_column = None
        self.filter_row = None
        self.image_row = None
        self.document_controller.detach_widget()

    def periodic(self):
        for dock_widget in self.dock_widgets if self.dock_widgets else list():
            dock_widget.panel.periodic()
            dock_widget.periodic()

    def restore_geometry_state(self):
        geometry = self.ui.get_persistent_string("Workspace/%s/Geometry" % self.workspace_id)
        state = self.ui.get_persistent_string("Workspace/%s/State" % self.workspace_id)
        return geometry, state

    def save_geometry_state(self, geometry, state):
        # ugh. this has the side effect of saving the layout when the geometry state is saved.
        # TODO: make the saving of internal layout independent of _deconstruct
        self.__workspace.layout = self._deconstruct(self.__canvas_item.canvas_items[0])
        self.ui.set_persistent_string("Workspace/%s/Geometry" % self.workspace_id, geometry)
        self.ui.set_persistent_string("Workspace/%s/State" % self.workspace_id, state)

    @property
    def document_controller(self):
        return self.__document_controller_weakref()

    @property
    def document_model(self):
        return self.document_controller.document_model

    @property
    def _canvas_item(self):
        return self.__canvas_item

    def _find_dock_widget(self, dock_widget_id):
        for dock_widget in self.dock_widgets:
            if dock_widget.panel.panel_id == dock_widget_id:
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

    def create_panel(self, document_controller, panel_id, title, positions, position, properties):
        try:
            panel = self.workspace_manager.create_panel_content(panel_id, document_controller, properties)
            assert panel is not None, "panel is None [%s]" % panel_id
            assert panel.widget is not None, "panel widget is None [%s]" % panel_id
            dock_widget = document_controller.create_dock_widget(panel.widget, panel_id, title, positions, position)
            dock_widget.panel = panel
            dock_widget.on_size_changed = panel.size_changed
            dock_widget.on_focus_changed = panel.focus_changed
            dock_widget.does_retain_focus = False
            def register_ui_activity():
                self.document_controller._register_ui_activity()
            dock_widget.on_ui_activity = register_ui_activity
            self.dock_widgets.append(dock_widget)
            return dock_widget
        except Exception as e:
            import traceback
            print("Exception creating panel '" + panel_id + "': " + str(e))
            traceback.print_exc()
            traceback.print_stack()
            return None

    def __create_display_panel(self, d):
        return DisplayPanel.DisplayPanel(self.document_controller, d)

    def display_data_item_in_display_panel(self, data_item, display_panel_id):
        for display_panel in self.display_panels:
            if display_panel.display_panel_id == display_panel_id:
                display_panel.set_display_panel_data_item(data_item)

    def _construct(self, desc, display_panels, lookup_data_item):
        selected_display_panel = None
        type = desc["type"]
        container = None
        item = None
        post_children_adjust = lambda: None
        if type == "container":
            container = CanvasItem.CanvasItemComposition()
        elif type == "splitter":
            container = CanvasItem.SplitterCanvasItem(orientation=desc.get("orientation"))
            def splitter_post_children_adjust():
                splits = desc.get("splits")
                if splits is not None:
                    container.splits = splits
            post_children_adjust = splitter_post_children_adjust
        elif type == "image":
            display_panel = self.__create_display_panel(desc)
            display_panels.append(display_panel)
            if desc.get("selected", False):
                selected_display_panel = display_panel
            item = display_panel
        if container:
            children = desc.get("children", list())
            for child_desc in children:
                child_canvas_item, child_selected_display_panel = self._construct(child_desc, display_panels, lookup_data_item)
                container.add_canvas_item(child_canvas_item)
                selected_display_panel = child_selected_display_panel if child_selected_display_panel else selected_display_panel
            post_children_adjust()
            return container, selected_display_panel
        return item, selected_display_panel

    def __get_display_panel_by_canvas_item(self, canvas_item):
        for display_panel in self.display_panels:
            if display_panel == canvas_item:
                return display_panel
        return None

    def _deconstruct(self, canvas_item):
        if isinstance(canvas_item, CanvasItem.SplitterCanvasItem):
            children = [self._deconstruct(child_canvas_item) for child_canvas_item in canvas_item.canvas_items]
            return { "type": "splitter", "orientation": canvas_item.orientation, "splits": copy.copy(canvas_item.splits), "children": children }
        if isinstance(canvas_item, DisplayPanel.DisplayPanel):
            display_panel = canvas_item
            desc = { "type": "image" }
            if display_panel._is_selected():
                desc["selected"] = True
            desc.update(display_panel.save_contents())
            return desc
        return None

    def change_workspace(self, workspace):
        assert workspace is not None
        # save the current workspace
        if self.__workspace:
            self.__workspace.layout = self._deconstruct(self.__canvas_item.canvas_items[0])
            self.__workspace = None
        # remove existing layout and canvas item
        self.display_panels = []
        for child in copy.copy(self.image_row.children):
            self.image_row.remove(child)
        # create new layout and canvas item
        self.__canvas_item = CanvasItem.CanvasItemComposition()
        canvas_widget = self.ui.create_canvas_widget()
        canvas_widget.canvas_item.add_canvas_item(self.__canvas_item)
        self._canvas_widget = canvas_widget  # only for testing
        # root canvas item should NOT be focusable or else it will grab focus in cases where no children have it.
        # no point in the root canvas item having focus.
        # self.__canvas_item.focusable = True
        # now construct the workspace
        document_model = self.document_model
        try:
            display_panels = list()  # to be populated by _construct
            canvas_item, selected_display_panel = self._construct(workspace.layout, display_panels, document_model.get_data_item_by_uuid)
            # store the new workspace
            if canvas_item:
                self.__workspace = workspace
                self.display_panels.extend(display_panels)
                self.__canvas_item.add_canvas_item(canvas_item)
                self.image_row.add(canvas_widget)
        except Exception as e:
            import traceback
            traceback.print_exc()
            traceback.print_stack()
        if self.__workspace == None:  # handle error condition by creating known simple workspace and replacing bad one
            workspace.layout = { "type": "image", "selected": True }
            display_panels = list()  # to be populated by _construct
            canvas_item, selected_display_panel = self._construct(workspace.layout, display_panels, document_model.get_data_item_by_uuid)
            # store the new workspace
            if canvas_item:
                self.__workspace = workspace
                self.display_panels.extend(display_panels)
                self.__canvas_item.add_canvas_item(canvas_item)
                self.image_row.add(canvas_widget)
        self.document_controller.selected_display_panel = selected_display_panel
        document_model.workspace_uuid = workspace.uuid

    def restore(self, workspace_uuid):
        """
            Restore the workspace to the given workspace_uuid.

            If workspace_uuid is None then create a new workspace and use it.
        """
        workspace = next((workspace for workspace in self.document_model.workspaces if workspace.uuid == workspace_uuid), None)
        if workspace is None:
            workspace = self.new_workspace()
        self.change_workspace(workspace)
        #self.restore_content()

    def change_to_previous_workspace(self):
        workspace_uuid = self.document_model.workspace_uuid
        workspace = next((workspace for workspace in self.document_model.workspaces if workspace.uuid == workspace_uuid), None)
        workspace_index = self.document_model.workspaces.index(workspace)
        workspace_index = (workspace_index - 1) % len(self.document_model.workspaces)
        self.change_workspace(self.document_model.workspaces[workspace_index])

    def change_to_next_workspace(self):
        workspace_uuid = self.document_model.workspace_uuid
        workspace = next((workspace for workspace in self.document_model.workspaces if workspace.uuid == workspace_uuid), None)
        workspace_index = self.document_model.workspaces.index(workspace)
        workspace_index = (workspace_index + 1) % len(self.document_model.workspaces)
        self.change_workspace(self.document_model.workspaces[workspace_index])

    def new_workspace(self, name=None, layout=None, workspace_id=None):
        """ Create a new workspace, insert into document_model, and return it. """
        workspace = WorkspaceLayout.WorkspaceLayout()
        self.document_model.append_workspace(workspace)
        workspace.layout = layout if layout is not None else { "type": "image", "selected": True }
        workspace.name = name if name is not None else _("Workspace")
        if workspace_id:
            workspace.workspace_id = workspace_id
        return workspace

    def ensure_workspace(self, name, layout, workspace_id):
        """Looks for a workspace with workspace_id.

        If none is found, create a new one, add it, and change to it.
        """
        workspace = next((workspace for workspace in self.document_model.workspaces if workspace.workspace_id == workspace_id), None)
        if not workspace:
            workspace = self.new_workspace(name=name, layout=layout, workspace_id=workspace_id)
        self.change_workspace(workspace)

    def create_workspace(self):
        """ Pose a dialog to name and create a workspace. """

        def create_clicked(text):
            if len(text) > 0:
                self.change_workspace(self.new_workspace(name=text))

        self.pose_get_string_message_box(caption=_("Enter a name for the workspace"), text=_("Workspace"),
                                         accepted_fn=create_clicked, accepted_text=_("Create"),
                                         message_box_id="create_workspace")

    def rename_workspace(self):
        """ Pose a dialog to rename the workspace. """

        def rename_clicked(text):
            if len(text) > 0:
                self.__workspace.name = text

        self.pose_get_string_message_box(caption=_("Enter new name for workspace"), text=self.__workspace.name,
                                         accepted_fn=rename_clicked, accepted_text=_("Rename"),
                                         message_box_id="rename_workspace")

    def remove_workspace(self):
        """ Pose a dialog to confirm removal then remove workspace. """

        def confirm_clicked():
            if len(self.document_model.workspaces) > 1:
                workspace = self.__workspace
                self.change_to_previous_workspace()
                self.document_model.remove_workspace(workspace)

        caption = _("Remove workspace named '{0}'?").format(self.__workspace.name)
        self.pose_confirmation_message_box(caption, confirm_clicked, accepted_text=_("Remove Workspace"),
                                           message_box_id="remove_workspace")

    def pose_get_string_message_box(self, caption, text, accepted_fn, rejected_fn=None, accepted_text=None, rejected_text=None, message_box_id=None):
        message_box_id = message_box_id if message_box_id else str(uuid.uuid4())
        if message_box_id in self.__message_boxes:
            return None
        if accepted_text is None: accepted_text = _("OK")
        if rejected_text is None: rejected_text = _("Cancel")
        message_box_widget = self.ui.create_column_widget()  # properties={"stylesheet": "background: #FFD"}
        caption_row = self.ui.create_row_widget()
        caption_row.add_spacing(12)
        caption_row.add(self.ui.create_label_widget(caption))
        caption_row.add_stretch()
        inside_row = self.ui.create_row_widget()

        def reject_button_clicked():
            if rejected_fn: rejected_fn()
            async def remove_widget():
                self.message_column.remove(message_box_widget)
            self.document_controller.event_loop.create_task(remove_widget())
            del self.__message_boxes[message_box_id]
            return False

        def accept_button_clicked():
            accepted_fn(string_edit_widget.text)
            async def remove_widget():
                self.message_column.remove(message_box_widget)
            self.document_controller.event_loop.create_task(remove_widget())
            del self.__message_boxes[message_box_id]
            return False

        string_edit_widget = self.ui.create_line_edit_widget()
        string_edit_widget.text = text
        string_edit_widget.on_return_pressed = accept_button_clicked
        string_edit_widget.on_escape_pressed = reject_button_clicked
        reject_button = self.ui.create_push_button_widget(rejected_text)
        reject_button.on_clicked = reject_button_clicked
        accepted_button = self.ui.create_push_button_widget(accepted_text)
        accepted_button.on_clicked = accept_button_clicked
        inside_row.add_spacing(12)
        inside_row.add(string_edit_widget)
        inside_row.add_spacing(12)
        inside_row.add(reject_button)
        inside_row.add_spacing(12)
        inside_row.add(accepted_button)
        inside_row.add_stretch()
        message_box_widget.add_spacing(6)
        message_box_widget.add(caption_row)
        message_box_widget.add_spacing(4)
        message_box_widget.add(inside_row)
        message_box_widget.add_spacing(4)
        self.message_column.add(message_box_widget)
        string_edit_widget.select_all()
        string_edit_widget.focused = True
        self.__message_boxes[message_box_id] = message_box_widget
        return message_box_widget

    def pose_confirmation_message_box(self, caption, accepted_fn, rejected_fn=None, accepted_text=None, rejected_text=None, display_rejected=True, message_box_id=None):
        message_box_id = message_box_id if message_box_id else str(uuid.uuid4())
        if message_box_id in self.__message_boxes:
            return None
        if accepted_text is None: accepted_text = _("OK")
        if rejected_text is None: rejected_text = _("Cancel")
        message_box_widget = self.ui.create_column_widget()  # properties={"stylesheet": "background: #FFD"}

        def reject_button_clicked():
            if rejected_fn: rejected_fn()
            self.message_column.remove(message_box_widget)
            del self.__message_boxes[message_box_id]

        def accept_button_clicked():
            accepted_fn()
            self.message_column.remove(message_box_widget)
            del self.__message_boxes[message_box_id]

        reject_button = self.ui.create_push_button_widget(rejected_text)
        reject_button.on_clicked = reject_button_clicked
        accepted_button = self.ui.create_push_button_widget(accepted_text)
        accepted_button.on_clicked = accept_button_clicked
        caption_row = self.ui.create_row_widget()
        caption_row.add_spacing(12)
        caption_row.add(self.ui.create_label_widget(caption))
        if display_rejected:
            caption_row.add_spacing(12)
            caption_row.add(reject_button)
        caption_row.add_spacing(12)
        caption_row.add(accepted_button)
        caption_row.add_stretch()
        message_box_widget.add_spacing(6)
        message_box_widget.add(caption_row)
        message_box_widget.add_spacing(4)
        self.message_column.add(message_box_widget)
        self.__message_boxes[message_box_id] = message_box_widget
        return message_box_widget

    def handle_drag_enter(self, display_panel, mime_data):
        if mime_data.has_format("text/data_item_uuid"):
            return "copy"
        if mime_data.has_format("text/uri-list"):
            return "copy"
        if mime_data.has_format(DisplayPanel.DISPLAY_PANEL_MIME_TYPE):
            return "copy"
        return "ignore"

    def handle_drag_leave(self, display_panel):
        return False

    def handle_drag_move(self, display_panel, mime_data, x, y):
        if mime_data.has_format("text/data_item_uuid"):
            return "copy"
        if mime_data.has_format("text/uri-list"):
            return "copy"
        if mime_data.has_format(DisplayPanel.DISPLAY_PANEL_MIME_TYPE):
            return "copy"
        return "ignore"

    def handle_drop(self, display_panel, mime_data, region, x, y):
        document_model = self.document_model
        if mime_data.has_format(DisplayPanel.DISPLAY_PANEL_MIME_TYPE):
            d = json.loads(mime_data.data_as_string(DisplayPanel.DISPLAY_PANEL_MIME_TYPE))
            if region == "right" or region == "left" or region == "top" or region == "bottom":
                self.insert_display_panel(display_panel, region, None, d)
            else:
                self.__replace_displayed_data_item(display_panel, None, d)
            return "move"
        if mime_data.has_format("text/data_item_uuid"):
            data_item_uuid = uuid.UUID(mime_data.data_as_string("text/data_item_uuid"))
            data_item = document_model.get_data_item_by_key(data_item_uuid)
            if data_item:
                if region == "right" or region == "left" or region == "top" or region == "bottom":
                    self.insert_display_panel(display_panel, region, data_item)
                else:
                    self.__replace_displayed_data_item(display_panel, data_item)
                return "copy"
        if mime_data.has_format("text/uri-list"):
            def receive_files_complete(received_data_items):
                def update_displayed_data_item():
                    self.__replace_displayed_data_item(display_panel, received_data_items[0])
                if len(received_data_items) > 0:
                    self.document_controller.queue_task(update_displayed_data_item)
            index = len(document_model.data_items)
            self.document_controller.receive_files(document_model, mime_data.file_paths, None, index, threaded=True, completion_fn=receive_files_complete)
            return "copy"
        return "ignore"

    def __replace_displayed_data_item(self, display_panel, data_item, d=None):
        """ Used in drag/drop support. """
        self.document_controller.replaced_display_panel_content = display_panel.save_contents()
        if data_item:
            display_panel.set_display_panel_data_item(data_item, detect_controller=True)
        elif d is not None:
            display_panel.change_display_panel_content(d)
        display_panel.request_focus()

    def insert_display_panel(self, display_panel, region, data_item=None, d=None):
        assert isinstance(display_panel, DisplayPanel.DisplayPanel)
        orientation = "vertical" if region == "right" or region == "left" else "horizontal"
        container = display_panel.container
        if isinstance(container, CanvasItem.SplitterCanvasItem):
            # check if trying to drag on non-axis edge of splitter
            if container.orientation != orientation:
                splitter_canvas_item = CanvasItem.SplitterCanvasItem(orientation=orientation)
                container.wrap_canvas_item(display_panel, splitter_canvas_item)
                container = splitter_canvas_item
        if not isinstance(container, CanvasItem.SplitterCanvasItem):  # special case where top level item is the image panel
            splitter_canvas_item = CanvasItem.SplitterCanvasItem(orientation=orientation)
            container.wrap_canvas_item(display_panel, splitter_canvas_item)
            container = splitter_canvas_item
        index = container.canvas_items.index(display_panel)
        if isinstance(container, CanvasItem.SplitterCanvasItem):
            # modify the existing splitter
            old_split = container.splits[index]
            new_index_adj = 1 if region == "right" or region == "bottom" else 0
            new_display_panel = self.__create_display_panel(dict())
            self.display_panels.insert(self.display_panels.index(display_panel) + new_index_adj, new_display_panel)
            if data_item:
                new_display_panel.set_display_panel_data_item(data_item, detect_controller=True)
            elif d is not None:
                new_display_panel.change_display_panel_content(d)
            container.insert_canvas_item(index + new_index_adj, new_display_panel)
            self.document_controller.selected_display_panel = new_display_panel
            # adjust the splits
            splits = list(container.splits)
            splits[index] = old_split * 0.5
            splits[index + 1] = old_split * 0.5
            container.splits = splits
            new_display_panel.request_focus()

    def remove_display_panel(self, display_panel):
        # first make sure the display panel has no content
        display_panel.change_display_panel_content({"type": "image", "display-panel-type": "empty-display-panel"})
        # now remove it
        container = display_panel.container
        if isinstance(container, CanvasItem.SplitterCanvasItem):
            if len(container.canvas_items) > 0:
                self.display_panels.remove(display_panel)
                container.remove_canvas_item(display_panel)
                if len(container.canvas_items) == 1:
                    container.unwrap_canvas_item(container.canvas_items[0])

    def selected_display_panel_changed(self, selected_display_panel):
        for display_panel in self.display_panels:
            display_panel.set_selected(display_panel == selected_display_panel)


class WorkspaceManager(metaclass=Utility.Singleton):

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
            except Exception as e:
                import traceback
                print("Exception creating panel '" + panel_id + "': " + str(e))
                traceback.print_exc()
                traceback.print_stack()
        return None

    def register_filter_panel(self, filter_panel_class):
        self.__filter_panel_class = filter_panel_class

    def create_filter_panel(self, document_controller):
        return self.__filter_panel_class(document_controller) if self.__filter_panel_class else None

    def get_panel_info(self, panel_id):
        assert panel_id in self.__panel_tuples
        tuple = self.__panel_tuples[panel_id]
        return tuple[2], tuple[3], tuple[4], tuple[5]

    def __get_panel_ids(self):
        return list(self.__panel_tuples.keys())
    panel_ids = property(__get_panel_ids)
