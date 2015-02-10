"""
This module defines a couple of classes proposed as a framework for handling live data
sources.

A HardwareSource represents a source of data elements.
"""

# system imports
import collections
from contextlib import contextmanager
import ConfigParser as configparser
import copy
import gettext
import logging
import os
import threading
import time
import traceback
import weakref

# local imports
from nion.swift.model import ImportExportManager
from nion.swift.model import Utility
from nion.ui import Observable

_ = gettext.gettext


# Keeps track of all registered hardware sources and instruments.
# Also keeps track of aliases between hardware sources and logical names.
class HardwareSourceManager(Observable.Broadcaster):
    __metaclass__ = Utility.Singleton

    def __init__(self):
        super(HardwareSourceManager, self).__init__()
        self.hardware_sources = []
        self.instruments = []
        # we create a list of callbacks for when a hardware
        # source is added or removed
        self.hardware_source_added_removed = []
        self.instrument_added_removed = []
        self.aliases_updated = []
        # aliases are shared between hardware sources and instruments
        self.__aliases = {}

    def _reset(self):  # used for testing to start from scratch
        self.hardware_sources = []
        self.hardware_source_added_removed = []
        self.instruments = []
        self.instrument_added_removed = []
        self.__aliases = {}

    def register_hardware_source(self, hardware_source):
        self.hardware_sources.append(hardware_source)
        hardware_source.add_listener(self)
        for f in self.hardware_source_added_removed:
            f()

    def unregister_hardware_source(self, hardware_source):
        hardware_source.remove_listener(self)
        self.hardware_sources.remove(hardware_source)
        for f in self.hardware_source_added_removed:
            f()

    def register_instrument(self, instrument_id, instrument):
        instrument.instrument_id = instrument_id
        self.instruments.append(instrument)
        for f in self.instrument_added_removed:
            f()

    def unregister_instrument(self, instrument_id):
        for instrument in self.instruments:
            if instrument.instrument_id == instrument_id:
                instrument.instrument_id = None
                self.instruments.remove(instrument)
                for f in self.instrument_added_removed:
                    f()
                break

    def abort_all_and_close(self):
        for hardware_source in copy.copy(self.hardware_sources):
            hardware_source.abort_playing()

    def __get_info_for_instrument_id(self, instrument_id):
        display_name = unicode()
        seen_instrument_ids = []  # prevent loops, just so we don't get into endless loop in case of user error
        while instrument_id in self.__aliases and instrument_id not in seen_instrument_ids:
            seen_instrument_ids.append(instrument_id)  # must go before next line
            instrument_id, display_name = self.__aliases[instrument_id]
        for instrument in self.instruments:
            if instrument.instrument_id == instrument_id:
                return instrument, display_name
        return None

    # may return None
    def get_instrument_by_id(self, instrument_id):
        info = self.__get_info_for_instrument_id(instrument_id)
        if info:
            instrument, display_name = info
            return instrument
        return None

    def __get_info_for_hardware_source_id(self, hardware_source_id):
        display_name = unicode()
        seen_hardware_source_ids = []  # prevent loops, just so we don't get into endless loop in case of user error
        while hardware_source_id in self.__aliases and hardware_source_id not in seen_hardware_source_ids:
            seen_hardware_source_ids.append(hardware_source_id)  # must go before next line
            hardware_source_id, display_name = self.__aliases[hardware_source_id]
        for hardware_source in self.hardware_sources:
            if hardware_source.hardware_source_id == hardware_source_id:
                return hardware_source, display_name
        return None

    def get_hardware_source_for_hardware_source_id(self, hardware_source_id):
        info = self.__get_info_for_hardware_source_id(hardware_source_id)
        if info:
            hardware_source, display_name = info
            return hardware_source
        return None

    def make_instrument_alias(self, instrument_id, alias_instrument_id, display_name):
        """
            Configure an alias.

            Callers can use the alias to refer to the instrument or hardware source.
            The alias should be lowercase, no spaces. The display name may be used to display alias to
            the user. Neither the original instrument or hardware source id and the alias id should ever
            be visible to end users.

            :param str instrument_id: the hardware source id (lowercase, no spaces)
            :param str alias_instrument_id: the alias of the hardware source id (lowercase, no spaces)
            :param str display_name: the display name for the alias
        """
        self.__aliases[alias_instrument_id] = (instrument_id, display_name)
        for f in self.aliases_updated:
            f()


class NotifyingEvent(object):

    def __init__(self):
        self.__weak_listeners = []
        self.__weak_listeners_mutex = threading.RLock()
        self.on_first_listener_added = None
        self.on_last_listener_removed = None

    def listen(self, listener_fn):
        listener = Observable.EventListener(listener_fn)
        def remove_listener(weak_listener):
            with self.__weak_listeners_mutex:
                self.__weak_listeners.remove(weak_listener)
                last = len(self.__weak_listeners) == 0
            if last and self.on_last_listener_removed:
                self.on_last_listener_removed()
        weak_listener = weakref.ref(listener, remove_listener)
        with self.__weak_listeners_mutex:
            first = len(self.__weak_listeners) == 0
            self.__weak_listeners.append(weak_listener)
        if first and self.on_first_listener_added:
            self.on_first_listener_added()
        return listener

    def fire(self, *args, **keywords):
        try:
            with self.__weak_listeners_mutex:
                listeners = [weak_listener() for weak_listener in self.__weak_listeners]
            for listener in listeners:
                listener.call(*args, **keywords)
        except Exception as e:
            import traceback
            logging.debug("Event Error: %s", e)
            traceback.print_exc()
            traceback.print_stack()


class HardwareSource(Observable.Broadcaster):
    """
    A hardware source provides ports, which in turn provide data_elements.

    A separate acquisition thread is used for acquiring all data and
    passing on to the ports. When a HardwareSource has no ports, this
    thread can stop running (when appropriate).
    """

    def __init__(self, hardware_source_id, display_name):
        super(HardwareSource, self).__init__()
        self.hardware_source_id = hardware_source_id
        self.display_name = display_name
        self.features = dict()
        self.__new_data_elements_event_listener = None
        self.__abort_signal = False  # used by acquisition thread to signal an abort caused by exception
        self.__channel_states = {}
        self.__channel_states_mutex = threading.RLock()
        self.last_channel_to_data_item_dict = {}
        self.__workspace_controller = None  # the workspace_controller when last started.
        self.frame_index = 0
        self.__acquire_thread = None
        self.__acquire_thread_break = False
        self.new_data_elements_event = NotifyingEvent()
        self.new_data_elements_event.on_first_listener_added = self.__create_acquisition_thread
        self.new_data_elements_event.on_last_listener_removed= self.__destroy_acquisition_thread
        self.playing_state_changed_event = Observable.Event()
        self.data_item_state_changed_event = Observable.Event()

    def close(self):
        self.__close_hardware_port()

    # user interfaces using hardware sources should call this periodically
    def periodic(self):
        if self.__should_abort():
            self.abort_playing()

    def __create_acquisition_thread(self):
        self.__acquire_thread_break = threading.Event()
        self.__acquire_thread = threading.Thread(target=self.__acquire_thread_loop, args=[self.__acquire_thread_break, ])
        self.__acquire_thread.start()

    def __destroy_acquisition_thread(self):
        self.__acquire_thread_break.set()
        self.__acquire_thread = None

    def __acquire_thread_loop(self, thread_break):
        try:
            self.start_acquisition()
            minimum_period = 1/20.0  # don't allow acquisition to starve main thread
            last_acquire_time = time.time() - minimum_period
        except Exception as e:
            logging.debug("Acquire error %s", e)
            traceback.print_exc()
            traceback.print_stack()
            return
        try:
            new_data_elements = None

            while True:
                if new_data_elements is not None:
                    self.new_data_elements_event.fire(new_data_elements)

                if self.__acquire_thread_break.is_set():
                    break

                # impose maximum frame rate so that acquire_data_elements can't starve main thread
                elapsed = time.time() - last_acquire_time
                time.sleep(max(0.0, minimum_period - elapsed))

                try:
                    new_data_elements = self.acquire_data_elements()
                except Exception as e:
                    self.new_data_elements_event.fire(list())
                    self.__abort_signal = True
                    # caller will print stack trace
                    raise

                # update frame_index if not supplied
                for data_element in new_data_elements:
                    data_element.setdefault("properties", dict()).setdefault("frame_index", self.frame_index)
                self.frame_index += 1

                # record the last acquisition time
                last_acquire_time = time.time()

                # new_data_elements should never be empty
                assert new_data_elements is not None
        finally:
            self.stop_acquisition()

    # subclasses can implement this method which is called when acquisition starts.
    # must be thread safe
    def start_acquisition(self):
        pass

    # subclasses can implement this method which is called when acquisition aborts.
    # must be thread safe
    def abort_acquisition(self):
        pass

    # subclasses can implement this method which is called when acquisition stops.
    # must be thread safe
    def stop_acquisition(self):
        pass

    # return whether acquisition is running
    @property
    def is_playing(self):
        return self.__new_data_elements_event_listener is not None

    # subclasses are expected to implement this function efficiently since it will
    # be repeatedly called. in practice that means that subclasses MUST sleep (directly
    # or indirectly) unless the data is immediately available, which it shouldn't be on
    # a regular basis. it is an error for this function to return an empty list of data_elements.
    # must be thread safe
    def acquire_data_elements(self):
        raise NotImplementedError()

    # call this to start acquisition
    # not thread safe
    def start_playing(self, workspace_controller):
        if not self.is_playing:
            self.__abort_signal = False
            self.__workspace_controller = workspace_controller
            self.__workspace_controller.will_start_playing(self)
            if not self.__new_data_elements_event_listener:
                self.__new_data_elements_event_listener = self.new_data_elements_event.listen(self.data_elements_changed)
                self.playing_state_changed_event.fire(True)
            self.notify_listeners("hardware_source_started", self)

    def __close_hardware_port(self):
        if self.__new_data_elements_event_listener:
            self.__new_data_elements_event_listener.close()
            self.__new_data_elements_event_listener = None
            self.data_elements_changed([])
            self.playing_state_changed_event.fire(False)

    # call this to stop acquisition immediately
    # not thread safe
    def abort_playing(self):
        if self.is_playing:
            self.abort_acquisition()
            self.__close_hardware_port()
            self.notify_listeners("hardware_source_stopped", self)
            self.__workspace_controller.did_stop_playing(self)
            # self.__workspace_controller = None  # Do not clear the workspace_controller here.

    # call this to stop acquisition gracefully
    # not thread safe
    def stop_playing(self):
        with self.__channel_states_mutex:
            for channel in self.__channel_states.keys():
                self.__channel_states[channel] = "marked"

    # if all channels are in stopped state, some controller should abort the acquisition.
    # thread safe
    def __should_abort(self):
        if self.__abort_signal:
            return True
        with self.__channel_states_mutex:
            are_all_channel_stopped = len(self.__channel_states) > 0
            for state in self.__channel_states.values():
                if state != "stopped":
                    are_all_channel_stopped = False
                    break
            return are_all_channel_stopped

    # call this to update data items. returns the new channel state.
    # thread safe
    def __update_channel(self, channel, data_item, data_element):
        with self.__channel_states_mutex:
            channel_state = self.__channel_states.get(channel)
        if channel_state != "stopped":
            sub_area = data_element.get("sub_area")
            complete = sub_area is None or data_element.get("state", "complete") == "complete"
            ImportExportManager.update_data_item_from_data_element(data_item, data_element)
            # update channel state
            if channel_state == "marked":
                channel_state = "stopped" if complete else "marked"
            else:
                channel_state = "complete" if complete else "partial"
        with self.__channel_states_mutex:
            # avoid race condition where 'marked' is set during 'update_channel_state'...
            # i.e. 'marked' can only transition to 'stopped'. leave it as 'marked' if nothing else.
            if not channel in self.__channel_states or self.__channel_states[channel] != "marked" or channel_state == "stopped":
                self.__channel_states[channel] = channel_state
        return self.__channel_states[channel]

    # this message comes from the hardware port.
    # data_elements is a list of data_elements; entries may be None
    # thread safe
    def data_elements_changed(self, data_elements):
        # TODO: deal wth overrun by asking for latest values.

        # build useful data structures (channel -> data)
        channel_to_data_element_map = {}
        channels = []
        for channel, data_element in enumerate(data_elements):
            if data_element is not None:
                channels.append(channel)
                channel_to_data_element_map[channel] = data_element

        # sync to data items
        new_channel_to_data_item_dict = self.__workspace_controller.sync_channels_to_data_items(channels, self)

        # these items are now live if we're playing right now. mark as such.
        for data_item in new_channel_to_data_item_dict.values():
            data_item.increment_data_ref_counts()
            document_model = self.__workspace_controller.document_controller.document_model
            document_model.begin_data_item_transaction(data_item)
            was_live = data_item.is_live
            document_model.begin_data_item_live(data_item)
            if not was_live:
                self.data_item_state_changed_event.fire(data_item)

        # update the data items with the new data.
        completed_data_items = []  # TODO: remove hardware_source_updated_data_items notification
        data_item_states = []
        for channel in channels:
            data_element = channel_to_data_element_map[channel]
            data_item = new_channel_to_data_item_dict[channel]
            self.__update_channel(channel, data_item, data_element)
            if self.__channel_states[channel] == "complete":
                completed_data_items.append(data_item)
            data_item_state = dict()
            data_item_state["channel"] = channel
            data_item_state["data_item"] = data_item
            data_item_state["channel_state"] = self.__channel_states[channel]
            if "sub_area" in data_element:
                data_item_state["sub_area"] = data_element["sub_area"]
            data_item_states.append(data_item_state)
        if completed_data_items:
            self.notify_listeners("hardware_source_updated_data_items", self, completed_data_items)
        self.notify_listeners("hardware_source_updated_data_item_states", self, data_item_states)

        # these items are no longer live. mark live_data as False.
        for channel, data_item in self.last_channel_to_data_item_dict.iteritems():
            # the order of these two statements is important, at least for now (12/2013)
            # when the transaction ends, the data will get written to disk, so we need to
            # make sure it's still in memory. if decrement were to come before the end
            # of the transaction, the data would be unloaded from memory, losing it forever.
            document_model = self.__workspace_controller.document_model
            document_model.end_data_item_transaction(data_item)
            document_model.end_data_item_live(data_item)
            data_item.decrement_data_ref_counts()
            if not data_item.is_live:
                self.data_item_state_changed_event.fire(data_item)

        # keep the channel to data item map around so that we know what changed between
        # last iteration and this one. also handle reference counts.
        old_channel_to_data_item_dict = self.last_channel_to_data_item_dict
        self.last_channel_to_data_item_dict = new_channel_to_data_item_dict

        # remove channel states that are no longer used.
        with self.__channel_states_mutex:
            for channel in self.__channel_states.keys():
                if not channel in channels:
                    del self.__channel_states[channel]


@contextmanager
def get_data_element_generator_by_id(hardware_source_id, sync=True, timeout=10.0):
    """
        Return a generator for data elements.

        :param bool sync: whether to wait for current frame to finish then grab next frame

        NOTE: data elements may return the same ndarray (with different data) each time it is called.
        Callers should handle appropriately.
    """

    hardware_source = HardwareSourceManager().get_hardware_source_for_hardware_source_id(hardware_source_id)

    new_data_event = threading.Event()
    new_data_elements = list()

    def receive_new_data_elements(data_elements):
        new_data_elements[:] = data_elements
        new_data_event.set()

    new_data_elements_event_listener = hardware_source.new_data_elements_event.listen(receive_new_data_elements)

    # exceptions thrown by the caller of the generator will end up here.
    # handle them by making sure to close the port.
    try:
        # the port is not guaranteed to return data immediately. wait here.
        if not new_data_event.wait(timeout):
            raise Exception("Could not start data_source " + str(hardware_source_id))

        def get_last_data_element():
            if sync:
                new_data_event.clear()
                new_data_event.wait()
            new_data_event.clear()
            new_data_event.wait()
            return new_data_elements[0]

        yield get_last_data_element
    finally:
        new_data_elements_event_listener.close()


@contextmanager
def get_data_generator_by_id(hardware_source_id, sync=True):
    """
        Return a generator for data.

        :param bool sync: whether to wait for current frame to finish then grab next frame

        NOTE: a new ndarray is created for each call.
    """
    with get_data_element_generator_by_id(hardware_source_id, sync) as data_element_generator:
        def get_last_data():
            return data_element_generator()["data"].copy()
        # error handling not necessary here - occurs above with get_data_element_generator_by_id function
        yield get_last_data


@contextmanager
def get_data_item_generator_by_id(hardware_source_id, sync=True):
    """
        Return a generator for data item.

        :param bool sync: whether to wait for current frame to finish then grab next frame

        NOTE: a new data item is created for each call.
    """
    with get_data_element_generator_by_id(hardware_source_id, sync) as data_element_generator:
        def get_last_data_item():
            return ImportExportManager.create_data_item_from_data_element(data_element_generator())
        yield get_last_data_item


def parse_hardware_aliases_config_file(config_path):
    """
        Parse config file for aliases and automatically register them.

        Returns True if alias file was found and parsed (successfully or unsuccessfully).

        Returns False if alias file was not found.

        Config file is a standard .ini file with a section
    """
    if os.path.exists(config_path):
        logging.info("Parsing alias file {:s}".format(config_path))
        try:
            config = configparser.SafeConfigParser()
            config.read(config_path)
            for section in config.sections():
                device = config.get(section, "device")
                hardware_alias = config.get(section, "hardware_alias")
                display_name = config.get(section, "display_name")
                try:
                    logging.info("Adding alias {:s} for device {:s}, display name: {:s} ".format(hardware_alias, device, display_name))
                    HardwareSourceManager().make_instrument_alias(device, hardware_alias, _(display_name))
                except Exception as e:
                    logging.info("Error creating hardware alias {:s} for device {:s} ".format(hardware_alias, device))
                    logging.info(traceback.format_exc())
        except Exception as e:
            logging.info("Error reading alias file from: " + config_path)
            logging.info(traceback.format_exc())
        return True
    return False
