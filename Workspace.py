# standard libraries
import copy
import functools
import gettext
import logging
import threading
import time
import uuid
import weakref

# third party libraries
# None

# local libraries
from nion.swift import DisplayPanel
from nion.swift.model import DataItem
from nion.swift.model import HardwareSource
from nion.swift.model import ImportExportManager
from nion.swift.model import Utility
from nion.swift.model import WorkspaceLayout
from nion.ui import CanvasItem


_ = gettext.gettext


class WorkspaceController(object):
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
        # this results in data_item_deleted messages
        self.document_controller.document_model.add_listener(self)

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
        document_controller.document_window.attach(root_widget)

        visible_panels = []
        if self.workspace_id == "library":
            visible_panels = ["toolbar-panel", "data-panel", "histogram-panel", "info-panel", "inspector-panel", "processing-panel", "console-panel"]

        self.create_panels(visible_panels)

        self.__workspace = None

        # channel activations keep track of which channels have been activated in the UI for a particular acquisition run.
        self.__channel_data_items = dict()  # maps channel to data item
        self.__mutex = threading.RLock()

        self.__channels_data_updated_event_listeners = dict()
        self.__last_channel_to_data_item_dicts = dict()

        self.__hardware_source_added_event_listener = HardwareSource.HardwareSourceManager().hardware_source_added_event.listen(self.__hardware_source_added)
        self.__hardware_source_removed_event_listener = HardwareSource.HardwareSourceManager().hardware_source_removed_event.listen(self.__hardware_source_removed)

        for hardware_source in HardwareSource.HardwareSourceManager().hardware_sources:
            self.__hardware_source_added(hardware_source)

    def close(self):
        for message_box_widget in copy.copy(self.__message_boxes.values()):
            self.message_column.remove(message_box_widget)
        self.__message_boxes.clear()
        if self.__workspace:
            # TODO: remove this; it should be updated whenever the workspace changes anyway.
            self.__workspace.layout = self._deconstruct(self.__canvas_item.canvas_items[0])
        for display_panel in self.display_panels:
            display_panel.close()
        self.display_panels = []
        if self.__canvas_item:
            self.__canvas_item.close()
            self.__canvas_item = None
        self.__workspace = None
        # closing dock widgets is currently a mess due to the call to self.document_controller.periodic in
        # DataPanel.update_data_panel_selection. work in progress. to avoid weird callbacks, copy the dock widgets
        # before closing, then clear the list, and handle the 'None' case in periodic. not nice.
        dock_widgets_copy = copy.copy(self.dock_widgets)
        self.dock_widgets = None
        for dock_widget in dock_widgets_copy:
            dock_widget.panel.close()
            dock_widget.close()
        self.__content_column = None
        self.filter_panel = None
        self.filter_row = None
        self.image_row = None
        self.__channel_data_items = None
        self.document_controller.document_model.remove_listener(self)

    def periodic(self):
        # for each of the panels too
        ts = []
        t0 = time.time()
        for dock_widget in self.dock_widgets if self.dock_widgets else list():
            start = time.time()
            dock_widget.panel.periodic()
            time1 = time.time()
            dock_widget.periodic()
            time2 = time.time()
            elapsed = time.time() - start
            if elapsed > 0.15:
                logging.debug("panel %s %s", dock_widget.panel, elapsed)
            ts.append("{0}: panel {1}ms / widget {2}ms".format(str(dock_widget.panel), (time1-start)*1000, (time2-time1)*1000))
        if time.time() - t0 > 0.003:
            pass # logging.debug("{0} --> {1}".format(time.time() - t0, " /// ".join(ts)))

    def restore_geometry_state(self):
        geometry = self.ui.get_persistent_string("Workspace/%s/Geometry" % self.workspace_id)
        state = self.ui.get_persistent_string("Workspace/%s/State" % self.workspace_id)
        return geometry, state

    def save_geometry_state(self, geometry, state):
        self.ui.set_persistent_string("Workspace/%s/Geometry" % self.workspace_id, geometry)
        self.ui.set_persistent_string("Workspace/%s/State" % self.workspace_id, state)

    @property
    def document_controller(self):
        return self.__document_controller_weakref()

    @property
    def document_model(self):
        return self.document_controller.document_model

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

        # clean up panels (tabify console/output)
        console_dock_widget = self._find_dock_widget("console-panel")
        output_dock_widget = self._find_dock_widget("output-panel")
        if console_dock_widget is not None and output_dock_widget is not None:
            document_controller.document_window.tabify_dock_widgets(console_dock_widget, output_dock_widget)

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
            print "Exception creating panel '" + panel_id + "': " + str(e)
            traceback.print_exc()
            traceback.print_stack()
            return None

    def __create_display_panel(self):
        display_panel = DisplayPanel.DisplayPanel(self.document_controller)
        display_panel.title = _("Image")
        return display_panel

    def get_display_panel(self, display_panel_id):
        for display_panel in self.display_panels:
            if display_panel.display_panel_id == display_panel_id:
                return display_panel
        return None

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
            display_panel = self.__create_display_panel()
            display_panels.append(display_panel)
            if desc.get("selected", False):
                selected_display_panel = display_panel
            display_panel.restore_contents(desc)
            item = display_panel.canvas_item
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
            if display_panel.canvas_item == canvas_item:
                return display_panel
        return None

    def _deconstruct(self, canvas_item):
        if isinstance(canvas_item, CanvasItem.SplitterCanvasItem):
            children = [self._deconstruct(child_canvas_item) for child_canvas_item in canvas_item.canvas_items]
            return { "type": "splitter", "orientation": canvas_item.orientation, "splits": copy.copy(canvas_item.splits), "children": children }
        display_panel = self.__get_display_panel_by_canvas_item(canvas_item)
        if display_panel:
            desc = { "type": "image" }
            if display_panel._is_selected():
                desc["selected"] = True
            display_panel.save_contents(desc)
            return desc
        return None

    def change_workspace(self, workspace):
        assert workspace is not None
        # save the current workspace
        if self.__workspace:
            self.__workspace.layout = self._deconstruct(self.__canvas_item.canvas_items[0])
        # remove existing layout and canvas item
        for display_panel in self.display_panels:
            display_panel.close()
        self.display_panels = []
        for child in copy.copy(self.image_row.children):
            self.image_row.remove(child)
        if self.__canvas_item:
            self.__canvas_item.close()
            self.__canvas_item = None
        # store the new workspace
        self.__workspace = workspace
        # create new layout and canvas item
        self.__canvas_item = CanvasItem.RootCanvasItem(self.ui)
        self.__canvas_item.focusable = True
        display_panels = list()  # to be populated by _construct
        document_model = self.document_controller.document_model
        canvas_item, selected_display_panel = self._construct(self.__workspace.layout, display_panels, document_model.get_data_item_by_uuid)
        self.display_panels.extend(display_panels)
        for display_panel in self.display_panels:
            display_panel.workspace_controller = self
        self.__canvas_item.add_canvas_item(canvas_item)
        self.image_row.add(self.__canvas_item.canvas_widget)
        self.document_controller.selected_display_panel = selected_display_panel
        document_model.workspace_uuid = workspace.uuid

    def restore(self, workspace_uuid):
        """
            Restore the workspace to the given workspace_uuid.

            If workspace_uuid is None then create a new workspace and use it.
        """
        workspace = next((workspace for workspace in self.document_controller.document_model.workspaces if workspace.uuid == workspace_uuid), None)
        if workspace is None:
            workspace = self.new_workspace()
        self.change_workspace(workspace)
        #self.restore_content()

    def change_to_previous_workspace(self):
        workspace_uuid = self.document_controller.document_model.workspace_uuid
        workspace = next((workspace for workspace in self.document_controller.document_model.workspaces if workspace.uuid == workspace_uuid), None)
        workspace_index = self.document_controller.document_model.workspaces.index(workspace)
        workspace_index = (workspace_index - 1) % len(self.document_controller.document_model.workspaces)
        self.change_workspace(self.document_controller.document_model.workspaces[workspace_index])

    def change_to_next_workspace(self):
        workspace_uuid = self.document_controller.document_model.workspace_uuid
        workspace = next((workspace for workspace in self.document_controller.document_model.workspaces if workspace.uuid == workspace_uuid), None)
        workspace_index = self.document_controller.document_model.workspaces.index(workspace)
        workspace_index = (workspace_index + 1) % len(self.document_controller.document_model.workspaces)
        self.change_workspace(self.document_controller.document_model.workspaces[workspace_index])

    def new_workspace(self, name=None, layout=None, workspace_id=None):
        """ Create a new workspace, insert into document_model, and return it. """
        workspace = WorkspaceLayout.Workspace()
        self.document_controller.document_model.append_workspace(workspace)
        workspace.layout = layout if layout is not None else { "type": "image", "selected": True }
        workspace.name = name if name is not None else _("Workspace")
        if workspace_id:
            workspace.workspace_id = workspace_id
        return workspace

    def ensure_workspace(self, name, layout, workspace_id):
        """Looks for a workspace with workspace_id.

        If none is found, create a new one, add it, and change to it.
        """
        workspace = next((workspace for workspace in self.document_controller.document_model.workspaces if workspace.workspace_id == workspace_id), None)
        if not workspace:
            workspace = self.new_workspace(name=name, layout=layout, workspace_id=workspace_id)
        self.change_workspace(workspace)

    def create_workspace(self):
        """ Pose a dialog to name and create a workspace. """

        def create_clicked(text):
            if len(text) > 0:
                self.change_workspace(self.new_workspace(name=text))

        self.pose_get_string_message_box("create_workspace", caption=_("Enter a name for the workspace"),
                                         text=_("Workspace"), accepted_fn=create_clicked,
                                         accepted_text=_("Create"))

    def rename_workspace(self):
        """ Pose a dialog to rename the workspace. """

        def rename_clicked(text):
            if len(text) > 0:
                self.__workspace.name = text

        self.pose_get_string_message_box("rename_workspace", caption=_("Enter new name for workspace"),
                                         text=self.__workspace.name, accepted_fn=rename_clicked,
                                         accepted_text=_("Rename"))

    def remove_workspace(self):
        """ Pose a dialog to confirm removal then remove workspace. """

        def confirm_clicked():
            if len(self.document_controller.document_model.workspaces) > 1:
                workspace = self.__workspace
                self.change_to_previous_workspace()
                self.document_controller.document_model.remove_workspace(workspace)

        caption = _("Remove workspace named '{0}'?").format(self.__workspace.name)
        self.pose_confirmation_message_box("remove_workspace", caption, confirm_clicked,
                                           accepted_text=_("Remove Workspace"))

    def pose_get_string_message_box(self, message_box_id, caption, text, accepted_fn, rejected_fn=None, accepted_text=None, rejected_text=None):
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
            self.message_column.remove(message_box_widget)
            del self.__message_boxes[message_box_id]

        def accept_button_clicked():
            accepted_fn(string_edit_widget.text)
            self.message_column.remove(message_box_widget)
            del self.__message_boxes[message_box_id]

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

    def pose_confirmation_message_box(self, message_box_id, caption, accepted_fn, rejected_fn=None, accepted_text=None, rejected_text=None, display_rejected=True):
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

    def __replace_displayed_data_item(self, display_panel, data_item):
        """ Used in drag/drop support. """
        self.document_controller.replaced_data_item = display_panel.display_specifier.data_item
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display_panel.replace_displayed_data_item_and_display(display_specifier)

    def handle_drag_enter(self, display_panel, mime_data):
        if mime_data.has_format("text/data_item_uuid"):
            return "copy"
        if mime_data.has_format("text/uri-list"):
            return "copy"
        return "ignore"

    def handle_drag_leave(self, display_panel):
        return False

    def handle_drag_move(self, display_panel, mime_data, x, y):
        if mime_data.has_format("text/data_item_uuid"):
            return "copy"
        if mime_data.has_format("text/uri-list"):
            return "copy"
        return "ignore"

    def handle_drop(self, display_panel, mime_data, region, x, y):
        if mime_data.has_format("text/data_item_uuid"):
            data_item_uuid = uuid.UUID(mime_data.data_as_string("text/data_item_uuid"))
            data_item = self.document_controller.document_model.get_data_item_by_key(data_item_uuid)
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
                    self.queue_task(update_displayed_data_item)
            index = len(self.document_controller.document_model.data_items)
            self.document_controller.receive_files(mime_data.file_paths, None, index, threaded=True, completion_fn=receive_files_complete)
            return "copy"
        return "ignore"

    def insert_display_panel(self, display_panel, region, data_item=None):
        orientation = "vertical" if region == "right" or region == "left" else "horizontal"
        container = display_panel.canvas_item.container
        if isinstance(container, CanvasItem.SplitterCanvasItem):
            # check if trying to drag on non-axis edge of splitter
            if container.orientation != orientation:
                splitter_canvas_item = CanvasItem.SplitterCanvasItem(orientation=orientation)
                container.wrap_canvas_item(display_panel.canvas_item, splitter_canvas_item)
                container = splitter_canvas_item
        if not isinstance(container, CanvasItem.SplitterCanvasItem):  # special case where top level item is the image panel
            splitter_canvas_item = CanvasItem.SplitterCanvasItem(orientation=orientation)
            container.wrap_canvas_item(display_panel.canvas_item, splitter_canvas_item)
            container = splitter_canvas_item
        index = container.canvas_items.index(display_panel.canvas_item)
        if isinstance(container, CanvasItem.SplitterCanvasItem):
            # modify the existing splitter
            old_split = container.splits[index]
            new_index_adj = 1 if region == "right" or region == "bottom" else 0
            new_display_panel = self.__create_display_panel()
            self.display_panels.insert(self.display_panels.index(display_panel) + new_index_adj, new_display_panel)
            new_display_panel.workspace_controller = self
            if data_item:
                new_display_panel.set_displayed_data_item(data_item)
            container.insert_canvas_item(index + new_index_adj, new_display_panel.canvas_item)
            self.document_controller.selected_display_panel = new_display_panel
            # adjust the splits
            splits = list(container.splits)
            splits[index] = old_split * 0.5
            splits[index + 1] = old_split * 0.5
            container.splits = splits

    def remove_display_panel(self, display_panel):
        container = display_panel.canvas_item.container
        if isinstance(container, CanvasItem.SplitterCanvasItem):
            if len(container.canvas_items) > 0:
                index = container.canvas_items.index(display_panel.canvas_item)
                container.remove_canvas_item(display_panel.canvas_item)
                self.display_panels.remove(display_panel)
                if len(container.canvas_items) == 1:
                    container.unwrap_canvas_item(container.canvas_items[0])

    def selected_display_panel_changed(self, selected_display_panel):
        for display_panel in self.display_panels:
            display_panel.set_selected(display_panel == selected_display_panel)

    def data_item_deleted(self, data_item):
        with self.__mutex:
            for channel_key in self.__channel_data_items.keys():
                if self.__channel_data_items[channel_key] == data_item:
                    del self.__channel_data_items[channel_key]
                    break

    def setup_channel(self, hardware_source_id, channel_id, view_id, data_item):
        with self.__mutex:
            metadata = data_item.data_sources[0].metadata
            hardware_source_metadata = metadata.setdefault("hardware_source", dict())
            hardware_source_metadata["hardware_source_id"] = hardware_source_id
            if channel_id:
                hardware_source_metadata["channel_id"] = channel_id
            if view_id:
                hardware_source_metadata["view_id"] = view_id
            data_item.data_sources[0].set_metadata(metadata)
            if channel_id is not None:
                channel_key = hardware_source_id + "_" + str(channel_id) + "_" + view_id
            else:
                channel_key = hardware_source_id + "_" + view_id
            self.__channel_data_items[channel_key] = data_item

    def __channels_data_updated(self, hardware_source, acquisition_task, channels_data):

        # sync to data items
        hardware_source_id = hardware_source.hardware_source_id
        display_name = hardware_source.display_name
        channel_to_data_item_dict = self.__sync_channels_to_data_items(channels_data, hardware_source_id, acquisition_task.view_id, display_name, not acquisition_task.is_continuous)

        # these items are now live if we're playing right now. mark as such.
        for data_item in channel_to_data_item_dict.values():
            data_item.increment_data_ref_counts()
            document_model = self.document_model
            document_model.begin_data_item_transaction(data_item)
            document_model.begin_data_item_live(data_item)

        # update the data items with the new data.
        data_elements = []
        data_item_states = []
        for channel_data in channels_data:
            channel_index = channel_data.index
            data_item = channel_to_data_item_dict[channel_index]
            # until the whole pipeline is cleaned up, recreate the data_element. guh.
            data_element = HardwareSource.convert_data_and_metadata_to_data_element(channel_data.data_and_calibration)
            if channel_data.sub_area:
                data_element["sub_area"] = channel_data.sub_area
            ImportExportManager.update_data_item_from_data_element(data_item, data_element)
            data_elements.append(data_element)
            data_item_state = dict()
            if channel_data.channel_id is not None:
                data_item_state["channel_id"] = channel_data.channel_id
            data_item_state["data_item"] = data_item
            data_item_state["channel_state"] = channel_data.state
            if channel_data.sub_area:
                data_item_state["sub_area"] = channel_data.sub_area
            data_item_states.append(data_item_state)
        # temporary until things get cleaned up
        hardware_source.data_item_states_changed_event.fire(data_item_states)
        hardware_source.data_item_states_changed(data_item_states)

        last_channel_to_data_item_dict = self.__last_channel_to_data_item_dicts.setdefault(hardware_source.hardware_source_id + str(acquisition_task.is_continuous), dict())

        # these items are no longer live. mark live_data as False.
        for data_item in last_channel_to_data_item_dict.values():
            # the order of these two statements is important, at least for now (12/2013)
            # when the transaction ends, the data will get written to disk, so we need to
            # make sure it's still in memory. if decrement were to come before the end
            # of the transaction, the data would be unloaded from memory, losing it forever.
            document_model = self.document_model
            document_model.end_data_item_transaction(data_item)
            document_model.end_data_item_live(data_item)
            data_item.decrement_data_ref_counts()

        # keep the channel to data item map around so that we know what changed between
        # last iteration and this one. also handle reference counts.
        last_channel_to_data_item_dict.clear()
        last_channel_to_data_item_dict.update(channel_to_data_item_dict)

        complete = len(channels_data) > 0 and all([channel_data.state == "complete" for channel_data in channels_data])

        # let listeners know too (if there are data_elements).
        if complete:
            if acquisition_task.is_continuous:
                hardware_source.viewed_data_elements_available_event.fire(data_elements)
            else:
                hardware_source.recorded_data_elements_available_event.fire(data_elements)

    def __hardware_source_added(self, hardware_source):
        channels_data_updated_event_listener = hardware_source.channels_data_updated_event.listen(functools.partial(self.__channels_data_updated, hardware_source))
        self.__channels_data_updated_event_listeners[hardware_source.hardware_source_id] = channels_data_updated_event_listener

    def __hardware_source_removed(self, hardware_source):
        self.__channels_data_updated_event_listeners[hardware_source.hardware_source_id].close()
        del self.__channels_data_updated_event_listeners[hardware_source.hardware_source_id]

    def __sync_channels_to_data_items(self, channels, hardware_source_id, view_id, display_name, is_recording):

        # TODO: self.__channel_data_items never gets cleared

        # data items are matched based on hardware_source_id, channel_id, and view_id.
        # view_id is an extra parameter that can be incremented to trigger new data items. it may be None.

        document_model = self.document_controller.document_model
        session_id = document_model.session_id

        # these functions will be run on the main thread.
        # be careful about binding the parameter. cannot use 'data_item' directly.
        def append_data_item(append_data_item):
            document_model.append_data_item(append_data_item)

        data_items = {}

        # for each channel, see if a matching data item exists.
        # if it does, check to see if it matches this hardware source.
        # if no matching data item exists, create one.
        for channel in channels:
            do_copy = False

            channel_index = channel.index
            channel_id = channel.channel_id
            channel_name = channel.name

            if channel_id is not None:
                channel_key = hardware_source_id + "_" + str(channel_id) + "_" + view_id
            else:
                channel_key = hardware_source_id + "_" + view_id

            with self.__mutex:
                data_item = self.__channel_data_items.get(channel_key)

            buffered_data_source = data_item.maybe_data_source if data_item else None

            # to reuse, first verify that the hardware source id, if any, matches
            if buffered_data_source:
                hardware_source_metadata = buffered_data_source.metadata.get("hardware_source", dict())
                existing_hardware_source_id = hardware_source_metadata.get("hardware_source_id")
                existing_channel_id = hardware_source_metadata.get("channel_id")
                existing_view_id = hardware_source_metadata.get("view_id")
                if existing_hardware_source_id != hardware_source_id or existing_channel_id != channel_id:
                    data_item = None
                if existing_view_id != view_id:
                    data_item = None
            # if everything but session or live state matches, copy it and re-use. this keeps the users display
            # preferences intact.
            if data_item and buffered_data_source and buffered_data_source.has_data and data_item.session_id != session_id:
                do_copy = True
            # finally, verify that this data item is live. if it isn't live, copy it and add the copy to the group,
            # but re-use the original. this helps preserve the users display choices. for the copy, delete derived data.
            # keep only the master.
            if data_item and buffered_data_source and buffered_data_source.has_data and not data_item.is_live:
                do_copy = True
            if do_copy:
                data_item_copy = copy.deepcopy(data_item)
                data_item.session_id = session_id  # immediately update the session id
                buffered_data_source = data_item.data_sources[0]
                metadata = buffered_data_source.metadata
                hardware_source_metadata = metadata.setdefault("hardware_source", dict())
                hardware_source_metadata["hardware_source_id"] = hardware_source_id
                hardware_source_metadata["channel_index"] = channel_index
                if channel_id is not None:
                    hardware_source_metadata["channel_id"] = channel_id
                if channel_name is not None:
                    hardware_source_metadata["channel_name"] = channel_name
                if view_id:
                    hardware_source_metadata["view_id"] = view_id
                buffered_data_source.set_metadata(metadata)
                self.document_controller.queue_main_thread_task(lambda value=data_item_copy: append_data_item(value))
            # if we still don't have a data item, create it.
            if not data_item:
                data_item = DataItem.DataItem()
                data_item.title = "%s (%s)" % (display_name, channel_name) if channel_name else display_name
                if is_recording:
                    metadata = data_item.metadata
                    metadata["assessed"] = False
                    data_item.set_metadata(metadata)
                buffered_data_source = DataItem.BufferedDataSource()
                data_item.append_data_source(buffered_data_source)
                metadata = buffered_data_source.metadata
                hardware_source_metadata = metadata.setdefault("hardware_source", dict())
                hardware_source_metadata["hardware_source_id"] = hardware_source_id
                hardware_source_metadata["channel_index"] = channel_index
                if channel_id is not None:
                    hardware_source_metadata["channel_id"] = channel_id
                if channel_name is not None:
                    hardware_source_metadata["channel_name"] = channel_name
                if view_id:
                    hardware_source_metadata["view_id"] = view_id
                buffered_data_source.set_metadata(metadata)
                self.document_controller.queue_main_thread_task(lambda value=data_item: append_data_item(value))
            # update the session, but only if necessary (this is an optimization to prevent unnecessary display updates)
            if data_item.session_id != session_id:
                data_item.session_id = session_id
            with self.__mutex:
                self.__channel_data_items[channel_key] = data_item
                data_items[channel_index] = data_item

        return data_items


class WorkspaceManager(object):
    __metaclass__ = Utility.Singleton

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
                print "Exception creating panel '" + panel_id + "': " + str(e)
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
        return self.__panel_tuples.keys()
    panel_ids = property(__get_panel_ids)
