"""
This module defines a couple of classes proposed as a framework for handling live data
sources.

A HardwareSource represents a source of data elements.
A client accesses data_elements through the create_port function
which changes the mode of the source, and starts it, and starts notifying the returned
port object. The port object should not do any significant processing in its new_data_elements
function but should instead just notify another thread that new data is available.
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

    # handle acquisition style devices

    # not thread safe
    def start_hardware_source(self, workspace_controller, hardware_source, mode=None):
        if not isinstance(hardware_source, HardwareSource):
            hardware_source = self.get_hardware_source_for_hardware_source_id(hardware_source)
        assert hardware_source is not None
        hardware_source.start_playing(workspace_controller, mode)

    # not thread safe
    def abort_hardware_source(self, hardware_source):
        if not isinstance(hardware_source, HardwareSource):
            hardware_source = self.get_hardware_source_for_hardware_source_id(hardware_source)
        assert hardware_source is not None
        hardware_source.abort_playing()

    # not thread safe
    def stop_hardware_source(self, hardware_source):
        if not isinstance(hardware_source, HardwareSource):
            hardware_source = self.get_hardware_source_for_hardware_source_id(hardware_source)
        assert hardware_source is not None
        hardware_source.stop_playing()

    # not thread safe
    def get_hardware_source_settings(self, hardware_source, mode):
        if not isinstance(hardware_source, HardwareSource):
            hardware_source = self.get_hardware_source_for_hardware_source_id(hardware_source)
        assert hardware_source is not None
        return hardware_source.get_mode_settings(mode)

    # not thread safe
    def set_hardware_source_settings(self, hardware_source, mode, mode_data):
        if not isinstance(hardware_source, HardwareSource):
            hardware_source = self.get_hardware_source_for_hardware_source_id(hardware_source)
        assert hardware_source is not None
        hardware_source.set_mode_settings(mode, mode_data)

    # not thread safe
    def get_hardware_source_mode(self, hardware_source):
        if not isinstance(hardware_source, HardwareSource):
            hardware_source = self.get_hardware_source_for_hardware_source_id(hardware_source)
        assert hardware_source is not None
        return hardware_source.mode

    # not thread safe
    def set_hardware_source_mode(self, hardware_source, mode):
        if not isinstance(hardware_source, HardwareSource):
            hardware_source = self.get_hardware_source_for_hardware_source_id(hardware_source)
        assert hardware_source is not None
        hardware_source.mode = mode

    # pass on messages from hardware sources to hardware source manager listeners

    def hardware_source_started(self, hardware_source):
        self.notify_listeners("hardware_source_started", hardware_source)

    def hardware_source_stopped(self, hardware_source):
        self.notify_listeners("hardware_source_stopped", hardware_source)

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

    # Create_port, resolving aliases for the hardware_source_id.
    def create_port_for_hardware_source_id(self, hardware_source_id):
        info = self.__get_info_for_hardware_source_id(hardware_source_id)
        if info:
            hardware_source, display_name = info
            return hardware_source.create_port()
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


class HardwareSourcePort(object):

    def __init__(self, hardware_source):
        self.hardware_source = hardware_source
        self.on_new_data_elements = None
        self.last_data_elements = None
        self.__finished_event = threading.Event()

    def close(self):
        self.hardware_source.remove_port(self)
        self.on_new_data_elements = None

    def get_last_data_elements(self):
        return self.last_data_elements

    # thread safe.
    def get_new_data_elements(self, sync):
        if sync:
            # wait for the last frame to finish
            self.__finished_event.clear()
            self.__finished_event.wait()
        # wait for the new frame to arrive
        self.__finished_event.clear()
        self.__finished_event.wait()
        return self.last_data_elements

    # thread safe.
    def _set_new_data_elements(self, data_elements):
        self.last_data_elements = data_elements
        if self.on_new_data_elements:
            self.on_new_data_elements(self.last_data_elements)
        self.__finished_event.set()


class HardwareSource(Observable.Broadcaster):
    """
    A hardware source provides ports, which in turn provide data_elements.

    A separate acquisition thread is used for acquiring all data and
    passing on to the ports. When a HardwareSource has no ports, this
    thread can stop running (when appropriate).
    """

    def __init__(self, hardware_source_id, display_name):
        super(HardwareSource, self).__init__()
        self.ports = []
        self.__portlock = threading.Lock()
        self.hardware_source_id = hardware_source_id
        self.display_name = display_name
        self.features = dict()
        self.__data_buffer = None
        self.__abort_signal = False  # used by acquisition thread to signal an abort caused by exception
        self.__channel_states = {}
        self.__channel_states_mutex = threading.RLock()
        self.last_channel_to_data_item_dict = {}
        self.__workspace_controller = None  # the workspace_controller when last started.
        self.frame_index = 0
        self.__mode = None
        self.__mode_data = dict()
        self.__mode_lock = threading.RLock()

    def close(self):
        if self.__data_buffer:
            self.__data_buffer.remove_listener(self)
            self.__data_buffer.close()
            self.__data_buffer = None

    # user interfaces using hardware sources should call this periodically
    def periodic(self):
        if self.__should_abort():
            self.abort_playing()

    def __get_data_buffer(self):
        if not self.__data_buffer:
            self.__data_buffer = HardwareSourceDataBuffer(self)
            self.__data_buffer.add_listener(self)
        return self.__data_buffer
    data_buffer = property(__get_data_buffer)

    # get mode settings. thread safe.
    def get_mode_settings(self, mode):
        with self.__mode_lock:
            return copy.copy(self.__mode_data.get(self.__mode))

    # set mode settings. thread safe.
    def set_mode_settings(self, mode, mode_data):
        with self.__mode_lock:
            __mode_data[self.__mode] = copy.copy(mode_data)

    # subclasses may override this to respond to mode changes
    def mode_changed(self, mode):
        pass

    # mode property. thread safe.
    def __get_mode(self):
        return self.__mode
    def __set_mode(self, mode):
        self.mode_changed(mode)
        self.__mode = mode
    mode = property(__get_mode, __set_mode)

    # only a single acquisition thread is created per hardware source
    def create_port(self, mode=None):
        with self.__portlock:
            port = HardwareSourcePort(self)
            start_thread = len(self.ports) == 0  # start a new thread if it's not already running (i.e. there are no current ports)
            self.ports.append(port)
        if start_thread:
            # we should do this a little nicer. Specifically, if we start a new thread
            # the existing one could carry on two. We should make sure we can only have one
            with self.__mode_lock:
                mode = mode if mode else self.__mode
                mode_data = self.get_mode_settings(mode)
            self.acquire_thread = threading.Thread(target=self.acquire_thread_loop, args=(mode, mode_data))
            self.acquire_thread.start()
        return port

    def remove_port(self, lst):
        """
        Removes the port lst. Usually performed via port.close()
        """
        with self.__portlock:
            self.ports.remove(lst)

    def acquire_thread_loop(self, mode, mode_data):
        try:
            self.start_acquisition(mode, mode_data)
            minimum_period = 1/20.0  # don't allow acquisition to starve main thread
            last_acquire_time = time.time() - minimum_period
        except Exception as e:
            logging.debug("Acquire error %s", e)
            traceback.print_exc()
            traceback.print_stack()
            return
        try:
            new_data_elements = None

            # return whether to break out of loop
            def update_ports(updated_data_elements):
                with self.__portlock:
                    if not self.ports:
                        return False
                    # check to make sure we actually have new data elements,
                    # since this might be the first time through the loop.
                    # otherwise the data element list gets cleared and new data elements
                    # get created when the data elements become available.
                    for port in self.ports:
                        if updated_data_elements is not None:
                            port._set_new_data_elements(updated_data_elements)
                    return True

            while True:
                if not update_ports(new_data_elements):
                    break

                # impose maximum frame rate so that acquire_data_elements can't starve main thread
                elapsed = time.time() - last_acquire_time
                time.sleep(max(0.0, minimum_period - elapsed))

                try:
                    new_data_elements = self.acquire_data_elements()
                except Exception as e:
                    update_ports([])
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
    def start_acquisition(self, mode, mode_data):
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
    def __is_playing(self):
        return self.data_buffer.is_playing
    is_playing = property(__is_playing)

    # subclasses are expected to implement this function efficiently since it will
    # be repeatedly called. in practice that means that subclasses MUST sleep (directly
    # or indirectly) unless the data is immediately available, which it shouldn't be on
    # a regular basis. it is an error for this function to return an empty list of data_elements.
    # must be thread safe
    def acquire_data_elements(self):
        raise NotImplementedError()

    # call this to start acquisition
    # not thread safe
    def start_playing(self, workspace_controller, mode=None):
        if not self.data_buffer.is_playing:
            self.__abort_signal = False
            self.__workspace_controller = workspace_controller
            self.__workspace_controller.will_start_playing(self)
            self.data_buffer.start()
            self.notify_listeners("hardware_source_started", self)

    # call this to stop acquisition immediately
    # not thread safe
    def abort_playing(self):
        if self.data_buffer.is_playing:
            self.abort_acquisition()
            self.data_buffer.stop()
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
        new_channel_state = self.__update_channel_state(channel_state, data_item, data_element)
        with self.__channel_states_mutex:
            # avoid race condition where 'marked' is set during 'update_channel_state'...
            # i.e. 'marked' can only transition to 'stopped'. leave it as 'marked' if nothing else.
            if not channel in self.__channel_states or self.__channel_states[channel] != "marked" or new_channel_state == "stopped":
                self.__channel_states[channel] = new_channel_state
        return self.__channel_states[channel]

    # update channel state.
    # channel state during normal acquisition: started -> (partial -> complete) -> stopped
    # channel state during stop: started -> (partial -> complete) -> marked -> stopped
    # thread safe
    def __update_channel_state(self, channel_state, data_item, data_element):
        if channel_state == "stopped":
            return channel_state
        sub_area = data_element.get("sub_area")
        complete = sub_area is None or data_element.get("state", "complete") == "complete"
        ImportExportManager.update_data_item_from_data_element(data_item, data_element)
        # update channel state
        if channel_state == "marked":
            channel_state = "stopped" if complete else "marked"
        else:
            channel_state = "complete" if complete else "partial"
        return channel_state

    # this message comes from the data buffer.
    # data_elements is a list of data_elements; entries may be None
    # thread safe
    def data_elements_changed(self, hardware_source, data_elements):
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
            self.__workspace_controller.document_controller.document_model.begin_data_item_transaction(data_item)
            self.__workspace_controller.document_controller.document_model.begin_data_item_live(data_item)

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
            self.__workspace_controller.document_model.end_data_item_transaction(data_item)
            self.__workspace_controller.document_model.end_data_item_live(data_item)
            data_item.decrement_data_ref_counts()

        # keep the channel to data item map around so that we know what changed between
        # last iteration and this one. also handle reference counts.
        old_channel_to_data_item_dict = self.last_channel_to_data_item_dict
        self.last_channel_to_data_item_dict = new_channel_to_data_item_dict

        # remove channel states that are no longer used.
        with self.__channel_states_mutex:
            for channel in self.__channel_states.keys():
                if not channel in channels:
                    del self.__channel_states[channel]


class HardwareSourceDataBuffer(Observable.Broadcaster):
    """
    For the given HWSource (which can either be an object with a create_port function, or a name. If
    a name, ports are created using the HardwareSourceManager.create_port_for_hardware_source_id function,
    and aliases can be supplied), creates a port and listens for any data_elements.
    Manages a collection of DataItems for all data_elements returned.
    The DataItems are owned by this, and persist while the acquisition is live,
    if the user wants to remove the data items, they should stop the acquisition
    first.

    DataItems are resued if available - we reuse them by searching through all data_elements
    in the 'Sources' data_group, based on name (could use more advanced metadata in the
    future f necessary).

    """

    def __init__(self, hardware_source):
        super(HardwareSourceDataBuffer, self).__init__()
        assert hardware_source
        self.hardware_source = hardware_source
        self.hardware_port = None
        self.__snapshots = collections.deque(maxlen=1)
        self.__current_snapshot = 0

    def close(self):
        # logging.debug("Closing HardwareSourceDataBuffer for %s", self.hardware_source.hardware_source_id)
        if self.hardware_port is not None:
            self.stop()
            # we should be consistent about how we stop live acquisitions:
            # stopping should be identical to acquiring with no channels selected
            # and we should delete/keep data items the same in both cases.
            # easiest way is to call new_data_elements(None)
            # now that we've set hardware_port to None
            # if we do want to keep data items, it should be done in new_data_elements
            self.new_data_elements([])

    def __get_is_playing(self):
        return self.hardware_port is not None
    is_playing = property(__get_is_playing)

    def __get_current_snapshot(self):
        return self.__current_snapshot
    def __set_current_snapshot(self, current_snapshot):
        assert not self.is_playing
        if current_snapshot < 0:
            current_snapshot = 0
        elif current_snapshot >= len(self.__snapshots):
            current_snapshot = len(self.__snapshots) - 1
        if self.__current_snapshot != current_snapshot:
            self.__current_snapshot = current_snapshot
            self.notify_listeners("data_elements_changed", self.hardware_source, self.__snapshots[self.__current_snapshot])
            self.notify_listeners("current_snapshot_changed", self.hardware_source, self.__current_snapshot)
    current_snapshot = property(__get_current_snapshot, __set_current_snapshot)

    def __get_snapshot_count(self):
        return len(self.__snapshots)
    snapshot_count = property(__get_snapshot_count)

    def __get_snapshots(self):
        return self.__snapshots
    snapshots = property(__get_snapshots)

    # must be called on the UI thread
    def start(self, mode=None):
        # logging.debug("Starting HardwareSourceDataBuffer for %s", self.hardware_source.hardware_source_id)
        if self.hardware_port is None:
            self.hardware_port = self.hardware_source.create_port(mode)
            self.hardware_port.on_new_data_elements = self.new_data_elements
            self.notify_listeners("playing_state_changed", self.hardware_source, True)

    # must be called on the UI thread
    def stop(self):
        # logging.debug("Stopping HardwareSourceDataBuffer for %s", self.hardware_source.hardware_source_id)
        if self.hardware_port is not None:
            self.hardware_port.on_new_data_elements = None
            self.hardware_port.close()
            self.hardware_port = None
            self.new_data_elements([])
            self.notify_listeners("playing_state_changed", self.hardware_source, False)

    # thread safe
    # this will typically be called on the acquisition thread
    # data_elements is a list of data_elements; entries may be None
    def new_data_elements(self, data_elements):
        if not self.hardware_port:
            data_elements = []

        # snapshots
        snapshot_count = len(self.__snapshots)
        self.__snapshots.append(data_elements)
        if len(self.__snapshots) != snapshot_count:
            self.notify_listeners("snapshot_count_changed", self.hardware_source, len(self.__snapshots))

        # update the data on the data items
        self.notify_listeners("data_elements_changed", self.hardware_source, data_elements)

        # notify listeners if we change current snapshot
        current_snapshot = len(self.__snapshots) - 1
        if self.__current_snapshot != current_snapshot:
            self.__current_snapshot = current_snapshot
            self.notify_listeners("current_snapshot_changed", self.hardware_source, self.__current_snapshot)


@contextmanager
def get_data_element_generator_by_id(hardware_source_id, sync=True):
    """
        Return a generator for data elements.

        :param bool sync: whether to wait for current frame to finish then grab next frame

        NOTE: data elements may return the same ndarray (with different data) each time it is called.
        Callers should handle appropriately.
    """
    port = __find_hardware_port_by_id(hardware_source_id)
    def get_last_data_element():
        return port.get_new_data_elements(sync)[0]
    # exceptions thrown by the caller of the generator will end up here.
    # handle them by making sure to close the port.
    try:
        yield get_last_data_element
    finally:
        port.close()


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


# Creates a port for the hardware source, and waits until it has received data
def __find_hardware_port_by_id(hardware_source_id):

    port = HardwareSourceManager().create_port_for_hardware_source_id(hardware_source_id)

    # our port is not guaranteed to return data straight away. We
    # can either let the tuning handle this or wait here.
    max_times = 20
    while port.get_last_data_elements() is None and max_times > 0:
        time.sleep(0.1)
    if port.get_last_data_elements() is None:
        logging.warn("Could not start data_source %s", image_source_name)
    return port


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
