# standard libraries
import copy
import cPickle as pickle
import gettext
import logging
import sys
import threading
import time
import uuid
import weakref

# third party libraries
# None

# local libraries
from nion.swift import ImagePanel
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import Utility
from nion.swift.model import WorkspaceLayout
from nion.ui import CanvasItem
from nion.ui import Geometry


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
        self.image_panels = []

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
        self.__channel_activations = set()  # maps hardware_source_id to a set of activated channels
        self.__channel_data_items = dict()  # maps channel to data item
        self.__mutex = threading.RLock()

    def close(self):
        for message_box_widget in copy.copy(self.__message_boxes.values()):
            self.message_column.remove(message_box_widget)
        self.__message_boxes.clear()
        if self.__workspace:
            # TODO: remove this; it should be updated whenever the workspace changes anyway.
            self.__workspace.layout = self._deconstruct(self.__canvas_item.canvas_items[0])
        for image_panel in self.image_panels:
            image_panel.close()
        self.image_panels = []
        if self.__canvas_item:
            self.__canvas_item.close()
            self.__canvas_item = None
        self.__workspace = None
        for dock_widget in copy.copy(self.dock_widgets):
            dock_widget.panel.close()
            dock_widget.close()
        self.dock_widgets = None
        self.__content_column = None
        self.filter_panel = None
        self.filter_row = None
        self.image_row = None
        self.__channel_activations = None
        self.__channel_data_items = None
        self.document_controller.document_model.remove_listener(self)

    def periodic(self):
        # for each of the panels too
        ts = []
        t0 = time.time()
        for dock_widget in self.dock_widgets:
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

    def __get_document_controller(self):
        return self.__document_controller_weakref()
    document_controller = property(__get_document_controller)

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

    def __create_image_panel(self):
        image_panel = ImagePanel.ImagePanel(self.document_controller)
        image_panel.title = _("Image")
        return image_panel

    def __get_primary_image_panel(self):
        return self.image_panels[0] if len(self.image_panels) > 0 else None
    primary_image_panel = property(__get_primary_image_panel)

    def _construct(self, desc, image_panels, lookup_data_item):
        selected_image_panel = None
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
            image_panel = self.__create_image_panel()
            image_panels.append(image_panel)
            if desc.get("selected", False):
                selected_image_panel = image_panel
            image_panel.restore_contents(desc)
            item = image_panel.canvas_item
        if container:
            children = desc.get("children", list())
            for child_desc in children:
                child_canvas_item, child_selected_image_panel = self._construct(child_desc, image_panels, lookup_data_item)
                container.add_canvas_item(child_canvas_item)
                selected_image_panel = child_selected_image_panel if child_selected_image_panel else selected_image_panel
            post_children_adjust()
            return container, selected_image_panel
        return item, selected_image_panel

    def __get_image_panel_by_canvas_item(self, canvas_item):
        for image_panel in self.image_panels:
            if image_panel.canvas_item == canvas_item:
                return image_panel
        return None

    def _deconstruct(self, canvas_item):
        if isinstance(canvas_item, CanvasItem.SplitterCanvasItem):
            children = [self._deconstruct(child_canvas_item) for child_canvas_item in canvas_item.canvas_items]
            return { "type": "splitter", "orientation": canvas_item.orientation, "splits": copy.copy(canvas_item.splits), "children": children }
        image_panel = self.__get_image_panel_by_canvas_item(canvas_item)
        if image_panel:
            desc = { "type": "image" }
            if image_panel._is_selected():
                desc["selected"] = True
            image_panel.save_contents(desc)
            return desc
        return None

    def change_workspace(self, workspace):
        assert workspace is not None
        # save the current workspace
        if self.__workspace:
            # TODO: remove this; it should be updated whenever the workspace changes anyway.
            self.__workspace.layout = self._deconstruct(self.__canvas_item.canvas_items[0])
        # remove existing layout and canvas item
        for image_panel in self.image_panels:
            image_panel.close()
        self.image_panels = []
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
        image_panels = list()  # to be populated by _construct
        document_model = self.document_controller.document_model
        canvas_item, selected_image_panel = self._construct(self.__workspace.layout, image_panels, document_model.get_data_item_by_uuid)
        self.image_panels.extend(image_panels)
        for image_panel in self.image_panels:
            image_panel.workspace_controller = self
        self.__canvas_item.add_canvas_item(canvas_item)
        self.image_row.add(self.__canvas_item.canvas_widget)
        self.document_controller.selected_image_panel = selected_image_panel
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

    def new_workspace(self, name=None, layout=None):
        """ Create a new workspace, insert into document_model, and return it. """
        workspace = WorkspaceLayout.Workspace()
        self.document_controller.document_model.append_workspace(workspace)
        workspace.layout = layout if layout is not None else { "type": "image", "selected": True }
        workspace.name = name if name is not None else _("Workspace")
        return workspace

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

    def __replace_displayed_data_item(self, image_panel, data_item):
        """ Used in drag/drop support. """
        self.document_controller.replaced_data_item = image_panel.get_displayed_data_item()
        buffered_data_source = data_item.maybe_data_source if data_item else None
        display = buffered_data_source.displays[0] if buffered_data_source else None
        image_panel.replace_displayed_data_item_and_display(data_item, buffered_data_source, display)

    def handle_drag_enter(self, image_panel, mime_data):
        if mime_data.has_format("text/data_item_uuid"):
            return "copy"
        if mime_data.has_format("text/uri-list"):
            return "copy"
        return "ignore"

    def handle_drag_leave(self, image_panel):
        return False

    def handle_drag_move(self, image_panel, mime_data, x, y):
        if mime_data.has_format("text/data_item_uuid"):
            return "copy"
        if mime_data.has_format("text/uri-list"):
            return "copy"
        return "ignore"

    def handle_drop(self, image_panel, mime_data, region, x, y):
        if mime_data.has_format("text/data_item_uuid"):
            data_item_uuid = uuid.UUID(mime_data.data_as_string("text/data_item_uuid"))
            data_item = self.document_controller.document_model.get_data_item_by_key(data_item_uuid)
            if data_item:
                if region == "right" or region == "left" or region == "top" or region == "bottom":
                    self.insert_image_panel(image_panel, region, data_item)
                else:
                    self.__replace_displayed_data_item(image_panel, data_item)
                return "copy"
        if mime_data.has_format("text/uri-list"):
            def receive_files_complete(received_data_items):
                def update_displayed_data_item():
                    self.__replace_displayed_data_item(image_panel, received_data_items[0])
                if len(received_data_items) > 0:
                    self.queue_task(update_displayed_data_item)
            index = len(self.document_controller.document_model.data_items)
            self.document_controller.receive_files(mime_data.file_paths, None, index, threaded=True, completion_fn=receive_files_complete)
            return "copy"
        return "ignore"

    def insert_image_panel(self, image_panel, region, data_item=None):
        orientation = "vertical" if region == "right" or region == "left" else "horizontal"
        container = image_panel.canvas_item.container
        if isinstance(container, CanvasItem.SplitterCanvasItem):
            # check if trying to drag on non-axis edge of splitter
            if container.orientation != orientation:
                splitter_canvas_item = CanvasItem.SplitterCanvasItem(orientation=orientation)
                container.wrap_canvas_item(image_panel.canvas_item, splitter_canvas_item)
                container = splitter_canvas_item
        if not isinstance(container, CanvasItem.SplitterCanvasItem):  # special case where top level item is the image panel
            splitter_canvas_item = CanvasItem.SplitterCanvasItem(orientation=orientation)
            container.wrap_canvas_item(image_panel.canvas_item, splitter_canvas_item)
            container = splitter_canvas_item
        index = container.canvas_items.index(image_panel.canvas_item)
        if isinstance(container, CanvasItem.SplitterCanvasItem):
            # modify the existing splitter
            old_split = container.splits[index]
            new_index_adj = 1 if region == "right" or region == "bottom" else 0
            new_image_panel = self.__create_image_panel()
            self.image_panels.insert(self.image_panels.index(image_panel) + new_index_adj, new_image_panel)
            new_image_panel.workspace_controller = self
            if data_item:
                new_image_panel.set_displayed_data_item(data_item)
            container.insert_canvas_item(index + new_index_adj, new_image_panel.canvas_item)
            self.document_controller.selected_image_panel = new_image_panel
            # adjust the splits
            splits = list(container.splits)
            splits[index] = old_split * 0.5
            splits[index + 1] = old_split * 0.5
            container.splits = splits

    def remove_image_panel(self, image_panel):
        container = image_panel.canvas_item.container
        if isinstance(container, CanvasItem.SplitterCanvasItem):
            if len(container.canvas_items) > 0:
                index = container.canvas_items.index(image_panel.canvas_item)
                container.remove_canvas_item(image_panel.canvas_item)
                self.image_panels.remove(image_panel)
                if len(container.canvas_items) == 1:
                    container.unwrap_canvas_item(container.canvas_items[0])

    def selected_image_panel_changed(self, selected_image_panel):
        for image_panel in self.image_panels:
            image_panel.set_selected(image_panel == selected_image_panel)

    def data_item_deleted(self, data_item):
        with self.__mutex:
            for channel_key in self.__channel_data_items.keys():
                if self.__channel_data_items[channel_key] == data_item:
                    del self.__channel_data_items[channel_key]
                    break

    def setup_channel(self, hardware_source, channel, data_item):
        with self.__mutex:
            channel_key = hardware_source.hardware_source_id + "_" + str(channel)
            self.__channel_data_items[channel_key] = data_item
            self.__channel_activations.add(channel_key)

    def will_start_playing(self, hardware_source):
        """
                Signal that the hardware source has started playing.

                Subclasses should override this to perform any action when the hardware source
                starts playing.

                This method will only be called from the UI thread.

                :param nion.swift.HardwareSource.HardwareSource: The hardware source.
            """
        pass

    def did_stop_playing(self, hardware_source):
        """
                Signal that the hardware source has stopped playing.

                Subclasses should override this to perform any action before the hardware source
                stops playing.

                This method will only be called from the UI thread.

                :param nion.swift.HardwareSource.HardwareSource: The hardware source.
            """
        pass

    def sync_channels_to_data_items(self, channels, hardware_source):

        document_model = self.document_controller.document_model
        assert document_model
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

            channel_key = hardware_source.hardware_source_id + "_" + str(channel)

            with self.__mutex:
                data_item = self.__channel_data_items.get(channel_key)

            # to reuse, first verify that the hardware source id, if any, matches
            if data_item:
                hardware_source_id = data_item.get_metadata("hardware_source").get("hardware_source_id")
                hardware_source_channel_id = data_item.get_metadata("hardware_source").get("hardware_source_channel_id")
                if hardware_source_id != hardware_source.hardware_source_id or hardware_source_channel_id != channel:
                    data_item = None
            # if everything but session or live-ness matches, copy it and re-use.
            # this keeps the users display preferences intact.
            if data_item and data_item.maybe_data_source and data_item.maybe_data_source.has_data and data_item.session_id != session_id:
                do_copy = True
            # finally, verify that this data item is live. if it isn't live, copy it and add the
            # copy to the group, but re-use the original. this helps preserve the users display
            # choices. for the copy, delete derived data. keep only the master.
            if data_item and data_item.maybe_data_source and data_item.maybe_data_source.has_data and not data_item.is_live:
                do_copy = True
            if do_copy:
                data_item_copy = copy.deepcopy(data_item)
                data_item.session_id = session_id  # immediately update the session id
                self.document_controller.queue_main_thread_task(lambda value=data_item_copy: append_data_item(value))
            # if we still don't have a data item, create it.
            if not data_item:
                data_item = DataItem.DataItem()
                data_item.title = "%s.%s" % (hardware_source.display_name, channel)
                with data_item.open_metadata("hardware_source") as metadata:
                    metadata["hardware_source_id"] = hardware_source.hardware_source_id
                    metadata["hardware_source_channel_id"] = channel
                self.document_controller.queue_main_thread_task(lambda value=data_item: append_data_item(value))
                with self.__mutex:
                    self.__channel_activations.discard(channel_key)
            # update the session, but only if necessary (this is an optimization to prevent unnecessary display updates)
            if data_item.session_id != session_id:
                data_item.session_id = session_id
            with self.__mutex:
                self.__channel_data_items[channel_key] = data_item
                data_items[channel] = data_item
                # check to see if its been activated. if not, activate it.
                if channel_key not in self.__channel_activations:
                    self.__channel_activations.add(channel_key)

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
