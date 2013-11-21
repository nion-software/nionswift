"""
This module defines a couple of classes proposed as a framework for handling live data
sources.

A HardwareSource represents a source of data elements.
A client accesses data_elements through the create_port function
which changes the mode of the source, and starts it, and starts notifying the returned
port object. The port object should not do any significant processing in its on_new_data_elements
function but should instead just notify another thread that new data is available.
"""

# system imports
import collections
from contextlib import contextmanager
import copy
import gettext
import logging
import numbers
import Queue as queue
import threading
import time
import uuid
import weakref

# local imports
from nion.swift import Decorators
from nion.swift import DataGroup
from nion.swift import DataItem
from nion.swift import ImportExportManager
from nion.swift import Storage

_ = gettext.gettext


# Keeps track of all registered hardware sources and instruments.
# Also keeps track of aliases between hardware sources and logical names.
class HardwareSourceManager(Storage.Broadcaster):
    __metaclass__ = Decorators.Singleton

    def __init__(self):
        super(HardwareSourceManager, self).__init__()
        self.hardware_sources = []
        self.__hardware_source_aliases = {}
        self.instruments = {}
        # we create a list of callbacks for when a hardware
        # source is added or removed
        self.hardware_source_added_removed = []
        self.instrument_added_removed = []

    def _reset(self):  # used for testing to start from scratch
        self.hardware_sources = []
        self.__hardware_source_aliases = {}
        self.hardware_source_added_removed = []
        self.instruments = {}
        self.instrument_added_removed = []

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
        self.instruments[instrument_id] = instrument
        for f in self.instrument_added_removed:
            f()

    def unregister_instrument(self, instrument_id):
        self.instruments.remove(instrument_id)
        for f in self.instrument_added_removed:
            f()

    # handle acquisition style devices

    # not thread safe
    def start_hardware_source(self, hardware_source, mode=None):
        if not isinstance(hardware_source, HardwareSource):
            hardware_source = self.get_hardware_source_for_hardware_source_id(hardware_source)
        assert hardware_source is not None
        hardware_source.start_playing(mode)

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

    # may return None
    def get_instrument_by_id(self, instrument_id):
        return self.instruments.get(instrument_id)

    def __get_info_for_hardware_source_id(self, hardware_source_id):
        display_name = unicode()
        seen_hardware_source_ids = []  # prevent loops, just so we don't get into endless loop in case of user error
        while hardware_source_id in self.__hardware_source_aliases and hardware_source_id not in seen_hardware_source_ids:
            seen_hardware_source_ids.append(hardware_source_id)  # must go before next line
            hardware_source_id, display_name = self.__hardware_source_aliases[hardware_source_id]
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

    def make_hardware_source_alias(self, hardware_source_id, alias_hardware_source_id, display_name):
        self.__hardware_source_aliases[alias_hardware_source_id] = (hardware_source_id, display_name)


class HardwareSourcePort(object):

    def __init__(self, hardware_source):
        self.hardware_source = hardware_source
        self.on_new_data_elements = None
        self.last_data_elements = None

    def get_last_data_elements(self):
        return self.last_data_elements

    def _set_new_data_elements(self, data_elements):
        self.last_data_elements = data_elements
        if self.on_new_data_elements:
            self.on_new_data_elements(self.last_data_elements)

    def close(self):
        self.hardware_source.remove_port(self)


class HardwareSource(Storage.Broadcaster):
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
        self.__data_buffer = None
        self.__channel_states = {}
        self.__channel_states_mutex = threading.RLock()
        # channel activations keep track of which channels have been activated in the UI for a particular acquisition run.
        self.__channel_activations = set()
        self.__channel_activations_mutex = threading.RLock()
        self.last_channel_to_data_item_dict = {}
        self.__periodic_queue = queue.Queue()
        # TODO: hack to get data group and session working. not sure how to handle this in the long run.
        self.data_group = None
        self.session_uuid = uuid.uuid4()
        self.frame_index = 0
        self.__mode = None
        self.__mode_data = dict()
        self.__mode_lock = threading.RLock()

    def close(self):
        if self.__data_buffer:
            self.__data_buffer.remove_listener(self)
            self.__data_buffer = None

    # user interfaces using hardware sources should call this periodically
    def periodic(self):
        if self.__should_abort():
            self.abort_playing()
        try:
            task = self.__periodic_queue.get(False)
        except queue.Empty:
            had_task = False
        else:
            task()
            self.__periodic_queue.task_done()

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
    def set_mode(self, mode):
        pass

    # mode property. thread safe.
    def __get_mode(self):
        return self.__mode
    def __set_mode(self, mode):
        self.set_mode(mode)
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
            import traceback
            traceback.print_exc()
            return
        try:
            new_data_elements = None

            while True:
                with self.__portlock:

                    if not self.ports:
                        break

                    # check to make sure we actually have new data elements,
                    # since this might be the first time through the loop.
                    # otherwise the data element list gets cleared and new data elements
                    # get created when the data elements become available.

                    for port in self.ports:
                        if new_data_elements is not None:
                            port._set_new_data_elements(new_data_elements)

                # impose maximum frame rate so that acquire_data_elements can't starve main thread
                elapsed = time.time() - last_acquire_time
                time.sleep(max(0.0, minimum_period - elapsed))

                new_data_elements = self.acquire_data_elements()

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

    # subclasses can implement this method which is called when acquisition stops.
    # must be thread safe
    def stop_acquisition(self):
        pass

    # subclasses are expected to implement this function efficiently since it will
    # be repeatedly called. in practice that means that subclasses MUST sleep (directly
    # or indirectly) unless the data is immediately available, which it shouldn't be on
    # a regular basis. it is an error for this function to return an empty list of data_elements.
    # must be thread safe
    def acquire_data_elements(self):
        raise NotImplementedError()

    def __str__(self):
        raise NotImplementedError()

    # call this to start acquisition
    # not thread safe
    def start_playing(self, mode=None):
        if not self.data_buffer.is_playing:
            self.data_buffer.start()
            self.notify_listeners("hardware_source_started", self)

    # call this to stop acquisition immediately
    # not thread safe
    def abort_playing(self):
        if self.data_buffer.is_playing:
            self.data_buffer.stop()
            self.notify_listeners("hardware_source_stopped", self)
            with self.__channel_activations_mutex:
                self.__channel_activations.clear()

    # call this to stop acquisition gracefully
    # not thread safe
    def stop_playing(self):
        with self.__channel_states_mutex:
            for channel in self.__channel_states.keys():
                self.__channel_states[channel] = "marked"

    # if all channels are in stopped state, some controller should abort the acquisition.
    # thread safe
    def __should_abort(self):
        with self.__channel_states_mutex:
            are_all_channel_stopped = len(self.__channel_states) > 0
            for channel, state in self.__channel_states.iteritems():
                if state != "stopped":
                    are_all_channel_stopped = False
                    break
            return are_all_channel_stopped

    # call this to update data items
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
    # thread safe
    def data_elements_changed(self, hardware_source, data_elements):
        # TODO: deal wth overrun by asking for latest values.

        # TODO: get the data group here. how?
        data_group = self.data_group

        # build useful data structures (channel -> data)
        channel_to_data_element_map = {}
        channels = []
        for channel, data_element in enumerate(data_elements):
            if data_element is not None:
                channels.append(channel)
                channel_to_data_element_map[channel] = data_element

        # sync to data items
        new_channel_to_data_item_dict = self.__sync_channels_to_data_items(channels, data_group, self.display_name)

        # these items are now live if we're playing right now. mark as such.
        for data_item in new_channel_to_data_item_dict.values():
            data_item.begin_transaction()

        # update the data items with the new data.
        for channel in channels:
            data_element = channel_to_data_element_map[channel]
            data_item = new_channel_to_data_item_dict[channel]
            self.__update_channel(channel, data_item, data_element)

        # these items are no longer live. mark live_data as False.
        for channel, data_item in self.last_channel_to_data_item_dict.iteritems():
            data_item.end_transaction()

        # keep the channel to data item map around so that we know what changed between
        # last iteration and this one. also handle reference counts.
        old_channel_to_data_item_dict = self.last_channel_to_data_item_dict
        self.last_channel_to_data_item_dict = new_channel_to_data_item_dict
        for data_item in self.last_channel_to_data_item_dict.values():
            data_item.add_ref()
        for data_item in old_channel_to_data_item_dict.values():
            data_item.remove_ref()

        # remove channel states that are no longer used.
        # cem 2013-11-16: this is untested and channel shutdown during acquisition may not work as expected.
        with self.__channel_states_mutex:
            for channel in self.__channel_states.keys():
                if not channel in channels:
                    del self.__channel_states[channel]

    def __sync_channels_to_data_items(self, channels, data_group, prefix):
        data_item_set = {}
        for channel in channels:
            data_item_name = "%s.%s" % (prefix, channel)
            # only use existing data item if it has a data buffer that matches
            data_item = DataGroup.get_data_item_in_container_by_title(data_group, data_item_name)
            # to reuse, first verify that the hardware source id, if any, matches
            if data_item:
                hardware_source_id = data_item.properties.get("hardware_source_id")
                if hardware_source_id != self.hardware_source_id:
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
                    context.properties["hardware_source_id"] = self.hardware_source_id
                    context.properties["session_uuid"] = self.session_uuid
                # this function will be run on the main thread.
                # be careful about binding the parameter. cannot use 'data_item' directly.
                def append_data_item_to_data_group_task(append_data_item):
                    data_group.data_items.insert(0, append_data_item)
                self.__periodic_queue.put(lambda value=data_item: append_data_item_to_data_group_task(value))
                with self.__channel_activations_mutex:
                    self.__channel_activations.add(channel)
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


class HardwareSourceDataBuffer(Storage.Broadcaster):
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
        self.__snapshots = collections.deque(maxlen=30)
        self.__current_snapshot = 0

    def close(self):
        logging.debug("Closing HardwareSourceDataBuffer for %s", self.hardware_source.hardware_source_id)
        if self.hardware_port is not None:
            self.pause()
            # we should be consistent about how we stop live acquisitions:
            # stopping should be identical to acquiring with no channels selected
            # and we should delete/keep data items the same in both cases.
            # esaiest way is to call on_new_data_elements(None)
            # now that we've set hardware_port to None
            # if we do want to keep data items, it should be done in on_new_data_elements
            self.on_new_data_elements([])

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
        logging.debug("Starting HardwareSourceDataBuffer for %s", self.hardware_source.hardware_source_id)
        if self.hardware_port is None:
            self.hardware_port = self.hardware_source.create_port(mode)
            self.hardware_port.on_new_data_elements = self.on_new_data_elements
            self.notify_listeners("playing_state_changed", self.hardware_source, True)

    # must be called on the UI thread
    def stop(self):
        logging.debug("Stopping HardwareSourceDataBuffer for %s", self.hardware_source.hardware_source_id)
        if self.hardware_port is not None:
            self.hardware_port.on_new_data_elements = None
            self.hardware_port.close()
            self.hardware_port = None
            self.on_new_data_elements([])
            self.notify_listeners("playing_state_changed", self.hardware_source, False)

    # thread safe
    # this will typically be called on the acquisition thread
    def on_new_data_elements(self, data_elements):
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
def get_data_element_generator_by_id(hardware_source_id):
    port = __find_hardware_port_by_id(hardware_source_id)
    def get_last_data_element():
        return port.get_last_data_elements()[0]
    # exceptions thrown by the caller of the generator will end up here.
    # handle them by making sure to close the port.
    try:
        yield get_last_data_element
    finally:
        port.close()


@contextmanager
def get_data_generator_by_id(hardware_source_id):
    with get_data_element_generator_by_id(hardware_source_id) as data_element_generator:
        def get_last_data():
            return data_element_generator()["data"]
        yield get_last_data


@contextmanager
def get_data_item_generator_by_id(hardware_source_id):
    with get_data_element_generator_by_id(hardware_source_id) as data_element_generator:
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
