# standard libraries
import datetime
import gettext
import logging
import threading

# third party libraries
# None

# local libraries
from nion.swift import DataGroup
from nion.swift import DataItem
from nion.swift import Decorators
from nion.swift import Panel

_ = gettext.gettext


class SessionPanel(Panel.Panel):

    def __init__(self, document_controller, panel_id, properties):
        super(SessionPanel, self).__init__(document_controller, panel_id, _("Session"))
        self.widget = self.ui.create_column_widget()

        session_title_row = self.ui.create_row_widget()
        session_title_row.add_spacing(12)
        session_title_row.add(self.ui.create_label_widget(_("Title"), properties={"width":60}))
        session_title_row.add(self.ui.create_line_edit_widget(properties={"width":240}))

        self.widget.add_spacing(8)
        self.widget.add(session_title_row)
        self.widget.add_stretch()

    def close(self):
        super(SessionPanel, self).close()


class Session(object):

    def __init__(self, document_model):
        self.document_model = document_model
        self.session_id = None
        self.start_new_session()
        # channel activations keep track of which channels have been activated in the UI for a particular acquisition run.
        self.__channel_activations = set()
        self.__channel_activations_mutex = threading.RLock()
        self.__periodic_queue = Decorators.TaskQueue()
        self.__data_group = None

    def periodic(self):
        self.__periodic_queue.perform_tasks()

    def __get_data_group(self):
        if self.__data_group is None:
            self.__data_group = self.document_model.get_or_create_data_group(_("Sources"))
        return self.__data_group

    # this message is received when a hardware source will start playing in this session.
    def will_start_playing(self, hardware_source):
        with self.__channel_activations_mutex:
            self.__channel_activations.clear()

    # this message is received when a hardware source stopped playing in this session.
    def did_stop_playing(self, hardware_source):
        pass

    def start_new_session(self):
        self.session_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

    # return a dictionary of data items indexed by channel
    # thread safe
    def sync_channels_to_data_items(self, channels, hardware_source):
        data_group = self.__get_data_group()
        data_item_set = {}
        # for each channel, see if a matching data item exists.
        # if it does, check to see if it matches this hardware source.
        # if no matching data item exists, create one.
        for channel in channels:
            data_item_name = "%s.%s" % (hardware_source.display_name, channel)
            # only use existing data item if it has a data buffer that matches
            data_item = DataGroup.get_data_item_in_container_by_title(data_group, data_item_name)
            # to reuse, first verify that the hardware source id, if any, matches
            if data_item:
                hardware_source_id = data_item.properties.get("hardware_source_id")
                if hardware_source_id != hardware_source.hardware_source_id:
                    data_item = None
            # next verify that that session id matches. disabled for now until re-use of data between sessions is figured out.
            #session_uuid = data_item.properties.get("session_uuid")
            #if session_uuid != self.session_uuid:
            #    data_item = None
            # if we still don't have a data item, create it.
            if not data_item:
                data_item = DataItem.DataItem()
                data_item.title = data_item_name
                with data_item.property_changes() as context:
                    context.properties["hardware_source_id"] = hardware_source.hardware_source_id
                # this function will be run on the main thread.
                # be careful about binding the parameter. cannot use 'data_item' directly.
                def append_data_item_to_data_group_task(append_data_item):
                    data_group.data_items.insert(0, append_data_item)
                self.__periodic_queue.put(lambda value=data_item: append_data_item_to_data_group_task(value))
                with self.__channel_activations_mutex:
                    self.__channel_activations.add(channel)
            with data_item.property_changes() as context:
                context.properties["session_id"] = self.session_id
            data_item_set[channel] = data_item
            # check to see if its been activated. if not, activate it.
            with self.__channel_activations_mutex:
                if channel not in self.__channel_activations:
                    # this function will be run on the main thread.
                    # be careful about binding the parameter. cannot use 'data_item' directly.
                    def activate_data_item(data_item_to_activate):
                        # TODO: if the data item is selected in the data panel, then moving it
                        # will deselect it and never reselect.
                        data_group.move_data_item(data_item_to_activate, 0)
                    self.__periodic_queue.put(lambda value=data_item: activate_data_item(value))
                    self.__channel_activations.add(channel)
        return data_item_set
