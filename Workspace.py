# standard libraries
import copy
import cPickle as pickle
import gettext
import logging
import sys
import threading
import time
import weakref

# third party libraries
# None

# local libraries
from nion.swift import Decorators
from nion.swift import ImagePanel
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.ui import CanvasItem


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

        self.dock_widgets = []
        self.image_panels = []

        # create the root element
        root_widget = self.ui.create_column_widget(properties={"min-width": 640, "min-height": 480})
        self.content_row = self.ui.create_column_widget()
        self.filter_panel = self.workspace_manager.create_filter_panel(document_controller)
        self.filter_row = self.filter_panel.widget
        self.image_row = self.ui.create_column_widget()
        self.content_row.add(self.filter_row)
        self.content_row.add(self.image_row, fill=True)
        self.filter_row.visible = False
        root_widget.add(self.content_row)

        # configure the document window (central widget)
        document_controller.document_window.attach(root_widget)

        visible_panels = []
        if self.workspace_id == "library":
            visible_panels = ["toolbar-panel", "data-panel", "histogram-panel", "info-panel", "inspector-panel", "processing-panel", "console-panel"]

        self.create_panels(visible_panels)

        self.__layout_id = None

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
        self.ui.set_persistent_string("Workspace/%s/Layout" % self.workspace_id, self.__layout_id)
        for dock_widget in copy.copy(self.dock_widgets):
            dock_widget.panel.close()
            dock_widget.close()
        self.dock_widgets = None

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

    def __get_layout_id(self):
        return self.__layout_id
    layout_id = property(__get_layout_id)

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
        console_dock_widget = self.find_dock_widget("console-panel")
        output_dock_widget = self.find_dock_widget("output-panel")
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

    def create_image_panel(self, element_id):
        image_panel = ImagePanel.ImagePanel(self.document_controller)
        image_panel.title = _("Image")
        image_panel.element_id = element_id
        self.image_panels.append(image_panel)
        return image_panel

    def __create_canvas_widget_from_image_panel(self, image_panel):
        image_panel.root_canvas_item = CanvasItem.RootCanvasItem(self.ui)
        image_panel.root_canvas_item.add_canvas_item(image_panel.canvas_item)
        return image_panel.root_canvas_item.canvas_widget

    def __get_primary_image_panel(self):
        return self.image_panels[0] if len(self.image_panels) > 0 else None
    primary_image_panel = property(__get_primary_image_panel)

    def __default_layout_fn(self, workspace, layout_id):
        self.canvas_item = CanvasItem.RootCanvasItem(self.ui)
        self.canvas_item.focusable = True
        if layout_id == "2x1":
            image_panel1 = self.create_image_panel("primary-image")
            image_panel2 = self.create_image_panel("secondary-image")
            layout_item = CanvasItem.SplitterCanvasItem(orientation="vertical")
            layout_item.add_canvas_item(image_panel1.canvas_item)
            layout_item.add_canvas_item(image_panel2.canvas_item)
            self.canvas_item.add_canvas_item(layout_item)
            return self.canvas_item.canvas_widget, image_panel1, layout_id
        elif layout_id == "1x2":
            image_panel = self.create_image_panel("primary-image")
            image_panel2 = self.create_image_panel("secondary-image")
            layout_item = CanvasItem.SplitterCanvasItem(orientation="horizontal")
            layout_item.add_canvas_item(image_panel.canvas_item)
            layout_item.add_canvas_item(image_panel2.canvas_item)
            self.canvas_item.add_canvas_item(layout_item)
            return self.canvas_item.canvas_widget, image_panel, layout_id
        elif layout_id == "3x1":
            image_panel1 = self.create_image_panel("primary-image")
            image_panel2 = self.create_image_panel("secondary-image")
            image_panel3 = self.create_image_panel("3rd-image")
            layout_item = CanvasItem.SplitterCanvasItem()
            layout_item.add_canvas_item(image_panel1.canvas_item)
            layout_item.add_canvas_item(image_panel2.canvas_item)
            layout_item.add_canvas_item(image_panel3.canvas_item)
            self.canvas_item.add_canvas_item(layout_item)
            return self.canvas_item.canvas_widget, image_panel1, layout_id
        elif layout_id == "2x2":
            image_panel1 = self.create_image_panel("primary-image")
            image_panel2 = self.create_image_panel("secondary-image")
            image_panel3 = self.create_image_panel("3rd-image")
            image_panel4 = self.create_image_panel("4th-image")
            layout_item = CanvasItem.SplitterCanvasItem(orientation="horizontal")
            column1 = CanvasItem.SplitterCanvasItem()
            column2 = CanvasItem.SplitterCanvasItem()
            column1.add_canvas_item(image_panel1.canvas_item)
            column1.add_canvas_item(image_panel3.canvas_item)
            column2.add_canvas_item(image_panel2.canvas_item)
            column2.add_canvas_item(image_panel4.canvas_item)
            layout_item.add_canvas_item(column1)
            layout_item.add_canvas_item(column2)
            self.canvas_item.add_canvas_item(layout_item)
            return self.canvas_item.canvas_widget, image_panel1, layout_id
        elif layout_id == "3x2":
            image_panel1 = self.create_image_panel("primary-image")
            image_panel2 = self.create_image_panel("secondary-image")
            image_panel3 = self.create_image_panel("3rd-image")
            image_panel4 = self.create_image_panel("4th-image")
            image_panel5 = self.create_image_panel("5th-image")
            image_panel6 = self.create_image_panel("6th-image")
            layout_item = CanvasItem.SplitterCanvasItem(orientation="horizontal")
            column1 = CanvasItem.SplitterCanvasItem()
            column2 = CanvasItem.SplitterCanvasItem()
            column3 = CanvasItem.SplitterCanvasItem()
            column1.add_canvas_item(image_panel1.canvas_item)
            column1.add_canvas_item(image_panel4.canvas_item)
            column2.add_canvas_item(image_panel2.canvas_item)
            column2.add_canvas_item(image_panel5.canvas_item)
            column3.add_canvas_item(image_panel3.canvas_item)
            column3.add_canvas_item(image_panel6.canvas_item)
            layout_item.add_canvas_item(column1)
            layout_item.add_canvas_item(column2)
            layout_item.add_canvas_item(column3)
            self.canvas_item.add_canvas_item(layout_item)
            return self.canvas_item.canvas_widget, image_panel1, layout_id
        else:  # default 1x1
            image_panel = self.create_image_panel("primary-image")
            self.canvas_item.add_canvas_item(image_panel.canvas_item)
            return self.canvas_item.canvas_widget, image_panel, "1x1"

    def change_layout(self, layout_id, preferred_data_items=None, adjust=None, layout_fn=None):
        if layout_id is not None and layout_id == self.__layout_id:  # check for None as special test case
            # TODO: don't change layout if new layout not requested
            pass  # return  ## tests don't pass with the check.
        # remember what's current being displayed
        old_selected_data_item = self.document_controller.selected_data_item
        old_displayed_data_items = []
        for image_panel in self.image_panels:
            if image_panel.get_displayed_data_item() is not None:
                old_displayed_data_items.append(image_panel.get_displayed_data_item())
        # remember the current layout.
        # 1321
        # first store the existing layout in the current slot
        if self.__layout_stack_current is not None:  # handle startup case
            self.__layout_stack[self.__layout_stack_current] = (self.__layout_id, [weakref.ref(data_item) for data_item in old_displayed_data_items])
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
        if layout_fn is None:
            layout_fn = self.__default_layout_fn
        content, image_panel, layout_id = layout_fn(self, layout_id)
        self.image_row.add(content)
        self.document_controller.selected_image_panel = image_panel
        if layout_id == "1x1" and adjust is None and self.document_controller.selected_image_panel is not None:
            preferred_data_items = [old_selected_data_item]
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
                for data_item in self.document_controller.document_model.data_items:
                    if data_item.data_source == last_displayed_data_item and data_item not in displayed_data_items:
                        data_item_to_display = data_item
                        break
            if not data_item_to_display:
                # TODO: make this search through the current criteria, such as group or session
                for data_item in self.document_controller.document_model.get_flat_data_item_generator():
                    if data_item not in displayed_data_items:
                        data_item_to_display = data_item
                        break
            # update the data item in the image panel to display it
            image_panel.set_displayed_data_item(data_item_to_display)
            displayed_data_items.append(data_item_to_display)
        # fill in the missing items if possible
        # save the layout id
        self.__layout_id = layout_id

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
    def display_data_item(self, primary_data_item, source_data_item=None, panel_id=None):

        def is_data_item_for_hardware_source(data_item):
            if data_item is None:
                return False
            if data_item.is_live:
                return True
            if data_item.get_metadata("hardware_source").get("hardware_source_id") and data_item.session_id == self.document_controller.document_model.session_id:
                return True
            return False

        if panel_id:
            for image_panel in self.image_panels:
                if image_panel.element_id == panel_id:
                    image_panel.set_displayed_data_item(primary_data_item)
                    return image_panel
        if source_data_item is None:
            # first look for exact match
            for image_panel in self.image_panels:
                if image_panel.get_displayed_data_item() == primary_data_item:
                    image_panel.set_displayed_data_item(primary_data_item)
                    return image_panel
            # now search for an open slot
            for image_panel in self.image_panels:
                if image_panel.get_displayed_data_item() and not is_data_item_for_hardware_source(image_panel.get_displayed_data_item()):
                    image_panel.set_displayed_data_item(primary_data_item)
                    return image_panel
            image_panel = self.image_panels[0]
            image_panel.set_displayed_data_item(primary_data_item)
            return image_panel
        elif primary_data_item is not None:
            # first look for exact match
            for image_panel in self.image_panels:
                if image_panel.get_displayed_data_item() == primary_data_item:
                    image_panel.set_displayed_data_item(primary_data_item)
                    return image_panel
            first_non_live = None
            last_non_live_before_primary = None
            matched = False
            # first search forward from primary
            for image_panel in self.image_panels:
                will_match = image_panel.get_displayed_data_item() == source_data_item
                if not is_data_item_for_hardware_source(image_panel.get_displayed_data_item()):
                    if matched:
                        image_panel.set_displayed_data_item(primary_data_item)
                        return image_panel
                    first_non_live = first_non_live if first_non_live else image_panel
                    last_non_live_before_primary = last_non_live_before_primary if will_match else image_panel
                if image_panel.get_displayed_data_item() == source_data_item:
                    matched = True
            # use one before if available
            if last_non_live_before_primary:
                image_panel = last_non_live_before_primary
                image_panel.set_displayed_data_item(primary_data_item)
                return image_panel
            # use first one if available
            if first_non_live:
                image_panel = first_non_live
                image_panel.set_displayed_data_item(primary_data_item)
                return image_panel
        return None


class AbstractWorkspaceController(object):

    """
        The workspace controller manages the workspace during acquisition.

        It creates data items for each of the channels, re-using them and displaying
        them according to policy.

        :param nion.swift.DocumentController.DocumentController document_controller: The document controller.
        :param string session_id: The session id.

        The workspace controller is typically created via the document controller at the time acquisition
        starts.
    """

    def __init__(self, document_controller, session_id):
        self.__weak_document_controller = weakref.ref(document_controller)
        self.session_id = session_id
        # this results in data_item_deleted messages
        self.document_controller.document_model.add_listener(self)

    def close(self):
        """
            Subclasses can override this method to perform close actions and must call super.

            Clients should call this to close down the workspace controller.
        """
        self.document_controller.document_model.remove_listener(self)

    def __get_document_controller(self):
        """ The document controller. """
        return self.__weak_document_controller() if self.__weak_document_controller else None
    document_controller = property(__get_document_controller)

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

        """
            Returns a mapping of channels to data items.

            Subclasses must override this method.

            :param list channels: A list of channels (strings).
            :param nion.swift.HardwareSource.HardwareSource: The hardware source.

            :return: A dict mapping channels to data items.

            This call is thread safe.
        """
        raise NotImplementedError()


class WorkspaceController(AbstractWorkspaceController):

    """
        The workspace controller manages the workspace during acquisition.

        It creates data items for each of the channels, re-using them and displaying
        them according to policy.

        :param nion.swift.DocumentController.DocumentController document_controller: The document controller.
        :param string session_id: The session id.
    """

    def __init__(self, document_controller, session_id):
        super(WorkspaceController, self).__init__(document_controller, session_id)
        # channel activations keep track of which channels have been activated in the UI for a particular acquisition run.
        self.__channel_activations = set()  # maps hardware_source_id to a set of activated channels
        self.__channel_data_items = dict()  # maps channel to data item
        self.__mutex = threading.RLock()

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

    def sync_channels_to_data_items(self, channels, hardware_source):

        document_model = self.document_controller.document_model

        # these functions will be run on the main thread.
        # be careful about binding the parameter. cannot use 'data_item' directly.
        def append_data_item(append_data_item):
            document_model.append_data_item(append_data_item)
        def activate_data_item(data_item_to_activate):
            if self.document_controller:
                self.document_controller.set_data_item_selection(data_item_to_activate)

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
            if data_item and data_item.has_master_data and data_item.session_id != self.session_id:
                do_copy = True
            # finally, verify that this data item is live. if it isn't live, copy it and add the
            # copy to the group, but re-use the original. this helps preserve the users display
            # choices. for the copy, delete derived data. keep only the master.
            if data_item and data_item.has_master_data and not data_item.is_live:
                do_copy = True
            if do_copy:
                data_item_copy = copy.deepcopy(data_item)
                data_item.session_id = self.session_id  # immediately update the session id
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
            if data_item.session_id != self.session_id:
                data_item.session_id = self.session_id
            with self.__mutex:
                self.__channel_data_items[channel_key] = data_item
                data_items[channel] = data_item
                # check to see if its been activated. if not, activate it.
                if channel_key not in self.__channel_activations:
                    self.document_controller.queue_main_thread_task(lambda value=data_item: activate_data_item(value))
                    self.__channel_activations.add(channel_key)

        return data_items


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
