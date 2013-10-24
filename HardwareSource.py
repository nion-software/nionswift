"""
This module defines a couple of classes proposed as a framework for handling live data
sources.

A HardwareSource represents a source of data elements.
A client accesses data_elements through the create_port function
which changes the mode of the source, and starts it, and starts notifying the returned
port object. The port object should not do any significant processing in its on_new_data_elements
function but should instead just notify another thread that new data is available.

The hardware source does allow processing to happen at acquisition time, by setting its
filter member to a method that takes a data element and returns a data element.

One idea is that there would be a Screen class, containing multiple ports, which would
contain a single pre-display processing thread. This thread would listen to messages posted
by the ports getting a new data element, then get the data from the port, process to make
compatible with the Screen, then push the data_elements into it.

There's also a LoggableCodeBlock class showing one way of combining functionality with
a full description of the code being called. It allows expressions to be added one
at a time and can be called like any function. It currently prints out the function
it's calling, but could be adapted to log it, or to produce a script with the same
functionality.
"""

# system imports
import collections
import copy
import gettext
import logging
import numbers
import threading
import weakref

# local imports
from nion.swift import Decorators
from nion.swift import DataItem

_ = gettext.gettext


@Decorators.singleton
class HardwareSourceManager(object):
    """
    Keeps track of all registered hardware sources.
    Also keeps track of aliases between hardware sources and logical names.
    The aliases can contain a filter to only return a subset of data_elements.
    This way we can create an alias for the 'RonchigramCamera' to, say,
    NionCCD1010, channel 0, properties="Tuning", and HAADF Signal to
    superscan, channel 1 (we can override the properties when we create the
    port if necessary too).

    And should we alias SuperScan,0 to HAADF Signal, or SuperScan to 'ScanUnit' and let
    users know that ScanUnit,0 is HAADF? I think I prefer the former approach, and we might
    be able to do this by sepcifying a filter to the port class.

    """
    def __init__(self):
        self.hardware_sources = []
        self._aliases = {}
        # we create a list of callbacks for when a hardware
        # source is added or removed
        self.hardware_source_added_removed = []

    def _reset(self):  # used for testing to start from scratch
        self.hardware_sources = []
        self._aliases = {}
        self.hardware_source_added_removed = []

    def register_hardware_source(self, hw_src):
        self.hardware_sources.append(hw_src)
        for f in self.hardware_source_added_removed:
            f(self, None)

    def unregister_hardware_source(self, hw_src):
        self.hardware_sources.remove(hw_src)
        for f in self.hardware_source_added_removed:
            f(self, None)

    def create_port_for_hardware_source_id(self, hardware_source_id, override_properties=None):
        """
        Alias for HardwareSource.create_port, with the added benefit
        of looking up aliases.

        Returns a newly created port for the given hardware_source_id.
        it will return that source, with the port listening for all channels.
        If hardware_source_id is an alias, it will return the hardware source it
        refers to with the filter and properties registered for that alias.

        Eg:
        manager.make_hardware_source_alias("existing_hw_src_id", "new_hw_src_id", _("New Camera"))
        port = manager.create_port_for_hardware_source_id("ronchigramcamera")
        ...
        port.close()
        """

        display_name, properties, filter = (unicode(), None, None)

        seen_hardware_source_ids = []  # prevent loops, just so we don't get into endless loop in case of user error
        while hardware_source_id in self._aliases and hardware_source_id not in seen_hardware_source_ids:
            seen_hardware_source_ids.append(hardware_source_id)  # must go before next line
            hardware_source_id, display_name, properties, filter = self._aliases[hardware_source_id]

        if override_properties:
            properties = override_properties

        for hardware_source in self.hardware_sources:
            if hardware_source.hardware_source_id == hardware_source_id:
                return hardware_source.create_port(properties, filter)
        return None

    def make_hardware_source_alias(self, hardware_source_id, alias_hardware_source_id, display_name, properties=None, filter=None):
        if isinstance(filter, numbers.Integral):
            filter = (filter, )
        self._aliases[alias_hardware_source_id] = (hardware_source_id, display_name, properties, filter)


class HardwareSourcePort(object):

    def __init__(self, hardware_source, properties, filter):
        self.properties = properties
        self.hardware_source = hardware_source
        self.on_new_data_elements = None
        self.last_data_elements = None
        self.filter = filter
        if isinstance(self.filter, numbers.Integral):
            self.filter = (self.filter, )

    def want_data_element(self, properties):
        """
            Return True if we will accept a data element with the given properties.
            """
        return True

    def get_last_data_elements(self):
        return self.last_data_elements

    def _set_new_data_elements(self, data_elements):
        if self.filter:
            self.last_data_elements = [data_element for i, data_element in enumerate(data_elements) if i in self.filter]
        else:
            self.last_data_elements = data_elements
        if self.on_new_data_elements:
            self.on_new_data_elements(self.last_data_elements)

    def close(self):
        """
            Closes the port. Identical to calling HardwareSource.remove_port(self).
            """
        self.hardware_source.remove_port(self)


class HardwareSource(object):
    """
    A hardware source provides ports, which in turn provide data_elements.

    Ports are created based on asked-for properties. The current properties of
    the HW source are always those most recently requested, ie the properties
    of the last port created. A filter can optionally be passed to a port which
    selects which of the returned list of data_elements to return. It should be either
    a single index or a list of indices. If None, all data_elements are returned.

    A separate acquisition thread is used for acquiring all data and
    passing on to the ports. When a HardwareSource has no ports, this
    thread can stop running (when appropriate). The start_acquisition,
    stop_acquisition, and set_from_properties functions are always only ever
    called from the acquisition thread
    """

    def __init__(self, hardware_source_id, display_name):
        self.ports = []
        self.__portlock = threading.Lock()
        self.filter = None
        self.hardware_source_id = hardware_source_id
        self.display_name = display_name

    def create_port(self, properties=None, filter=None):
        with self.__portlock:
            port = HardwareSourcePort(self, properties, filter)
            start_thread = len(self.ports) == 0  # start a new thread if it's not already running (i.e. there are no current ports)
            self.ports.append(port)
            self.set_from_properties(properties)
        if start_thread:
            # we should do this a little nicer. Specifically, if we start a new thread
            # the existing one could carry on two. We should make sure we can only have one
            self.acquire_thread = threading.Thread(target=self.acquire_thread_loop)
            self.acquire_thread.start()
        return port

    def remove_port(self, lst):
        """
        Removes the port lst. Usually performed via port.close()
        """
        with self.__portlock:
            self.ports.remove(lst)

    def acquire_thread_loop(self):
        self.start_acquisition()
        try:
            last_properties = None
            new_data_elements = None

            while True:
                with self.__portlock:
                    if not self.ports:
                        break

                    if last_properties != self.ports[-1].properties:
                        last_properties = self.ports[-1].properties
                        self.set_from_properties(last_properties)

                    for port in self.ports:
                        # check to make sure we actually have new data elements,
                        # since this might be the first time through the loop.
                        # otherwise the data element list gets cleared and new data elements
                        # get created when the data elements become available.
                        if port.want_data_element(last_properties) and new_data_elements:
                            port._set_new_data_elements(new_data_elements)

                new_data_elements = self.acquire_data_elements()

                # new_data_elements should never be empty
                assert new_data_elements
        finally:
            self.stop_acquisition()

    def start_acquisition(self):
        pass

    def stop_acquisition(self):
        pass

    # subclasses are expected to implement this function efficiently since it will
    # be repeatedly called. in practice that means that subclasses MUST sleep (directly
    # or indirectly) unless the data is immediately available, which it shouldn't be on
    # a regular basis. it is an error for this function to return an empty list of data_elements.
    def acquire_data_elements(self):
        raise NotImplementedError()

    def set_from_properties(self, properties):
        pass

    def __str__(self):
        raise NotImplementedError()


class HardwareSourceDataBuffer(object):
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
    data_group_name = _("Sources")

    def __init__(self, hardware_source, document_controller):
        self.hardware_source = hardware_source
        self.document_controller = document_controller
        self.hardware_source_man = HardwareSourceManager()
        self.hardware_port = None
        self.data_group = self.document_controller.document_model.get_or_create_data_group(self.data_group_name)
        self.first_data = False
        self.last_channel_to_data_item_dict = {}
        self.__snapshots = collections.deque(maxlen=30)
        self.__current_snapshot = 0
        self.__weak_listeners = []
        self.__weak_listeners_mutex = threading.RLock()

    def close(self):
        logging.info("Closing HardwareSourceDataBuffer for %s", self.hardware_source.hardware_source_id)
        if self.hardware_port is not None:
            self.pause()
            # we should be consistent about how we stop live acquisitions:
            # stopping should be identical to acquiring with no channels selected
            # and we should delete/keep data items the same in both cases.
            # esaiest way is to call on_new_data_elements(None)
            # now that we've set hardware_port to None
            # if we do want to keep data items, it should be done in on_new_data_elements
            self.on_new_data_elements([])

    # Add a listener. Listeners will receive data_item_changed message when this
    # DataItem is notified of a change via the notify_data_item_changed() method.
    def add_listener(self, listener):
        with self.__weak_listeners_mutex:
            assert listener is not None
            self.__weak_listeners.append(weakref.ref(listener))
    # Remove a listener.
    def remove_listener(self, listener):
        with self.__weak_listeners_mutex:
            assert listener is not None
            self.__weak_listeners.remove(weakref.ref(listener))
    # Send a message to the listeners
    def notify_listeners(self, fn, *args, **keywords):
        with self.__weak_listeners_mutex:
            listeners = [weak_listener() for weak_listener in self.__weak_listeners]
        for listener in listeners:
            if hasattr(listener, fn):
                getattr(listener, fn)(*args, **keywords)

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
            self.update_data_elements(self.__snapshots[self.__current_snapshot])
            self.notify_listeners("current_snapshot_changed", self.hardware_source, self.__current_snapshot)
    current_snapshot = property(__get_current_snapshot, __set_current_snapshot)

    def __get_snapshot_count(self):
        return len(self.__snapshots)
    snapshot_count = property(__get_snapshot_count)

    def start(self):
        logging.info("Starting HardwareSourceDataBuffer for %s", self.hardware_source.hardware_source_id)
        if self.hardware_port is None:
            if hasattr(self.hardware_source, "create_port"):
                self.hardware_port = self.hardware_source.create_port()
            else:
                self.hardware_port = self.hardware_source_man.create_port_for_hardware_source_id(self.hardware_source.hardware_source_id)
            self.hardware_port.on_new_data_elements = self.on_new_data_elements
            self.first_data = True
            self.notify_listeners("playing_state_changed", self.hardware_source, True)

    def pause(self):
        logging.info("Pausing HardwareSourceDataBuffer for %s", self.hardware_source.hardware_source_id)
        if self.hardware_port is not None:
            self.hardware_port.on_new_data_elements = None
            self.hardware_port.close()
            # finally we remove the reference to the port. on_new_data_elements needs it around
            # above to get the name of any existing data_items
            self.hardware_port = None
            self.notify_listeners("playing_state_changed", self.hardware_source, False)
        for channel in self.last_channel_to_data_item_dict.keys():
            data_item = self.last_channel_to_data_item_dict[channel]
            data_item.live_data = False

    def on_new_data_elements(self, data_elements):
        if not self.hardware_port:
            data_elements = []

        # snapshots
        snapshot_count = len(self.__snapshots)
        self.__snapshots.append(data_elements)
        if len(self.__snapshots) != snapshot_count:
            self.notify_listeners("snapshot_count_changed", self.hardware_source, len(self.__snapshots))

        # update the data on the data items
        self.update_data_elements(data_elements)

        # notify listeners if we change current snapshot
        current_snapshot = len(self.__snapshots) - 1
        if self.__current_snapshot != current_snapshot:
            self.__current_snapshot = current_snapshot
            self.notify_listeners("current_snapshot_changed", self.hardware_source, self.__current_snapshot)

    def update_data_elements(self, data_elements):
        # build useful data structures (channel -> data)
        channel_to_data_element_map = {}
        channels = []
        for channel, data_element in enumerate(data_elements):
            if data_element is not None:
                channels.append(channel)
                channel_to_data_element_map[channel] = data_element

        # sync to data items
        new_channel_to_data_item_dict = self.document_controller.sync_channels_to_data_items(channels, self.data_group, self.hardware_source.display_name)

        # these items are now live if we're playing right now. mark as such.
        for channel in list(set(new_channel_to_data_item_dict.keys())-set(self.last_channel_to_data_item_dict.keys())):
            data_item = new_channel_to_data_item_dict[channel]
            data_item.live_data = self.is_playing

        # select the preferred item.
        # TODO: better mechanism for selecting preferred item at start of acquisition.
        if self.first_data:
            data_item = new_channel_to_data_item_dict[0]
            self.document_controller.select_data_item(self.data_group, data_item)
            self.first_data = False

        # update the data items with the new data.
        for channel in channels:
            data_element = channel_to_data_element_map[channel]
            data_item = new_channel_to_data_item_dict[channel]
            data_item.master_data = data_element["data"]
            if "data_range" in data_element:
                data_item.data_range = data_element.get("data_range")
            if "spatial_calibration" in data_element:
                spatial_calibration = data_element.get("spatial_calibration")
                if len(spatial_calibration) == len(data_item.spatial_shape):
                    for dimension, dimension_calibration in enumerate(spatial_calibration):
                        origin = float(dimension_calibration[0])
                        scale = float(dimension_calibration[1])
                        units = unicode(dimension_calibration[2])
                        if scale != 0.0:
                            data_item.calibrations[dimension].origin = origin
                            data_item.calibrations[dimension].scale = scale
                            data_item.calibrations[dimension].units = units
            if "properties" in data_element:
                properties = data_item.grab_properties()
                for key, value in data_element.get("properties").iteritems():
                    properties[key] = value
                data_item.release_properties(properties)

        # these items are no longer live. mark live_data as False.
        for channel in list(set(self.last_channel_to_data_item_dict.keys())-set(new_channel_to_data_item_dict.keys())):
            data_item = self.last_channel_to_data_item_dict[channel]
            data_item.live_data = False

        # keep the channel to data item map around so that we know what changed between
        # last iteration and this one. also handle reference counts.
        old_channel_to_data_item_dict = copy.copy(self.last_channel_to_data_item_dict)
        self.last_channel_to_data_item_dict = copy.copy(new_channel_to_data_item_dict)
        for data_item in self.last_channel_to_data_item_dict.values():
            data_item.add_ref()
        for data_item in old_channel_to_data_item_dict.values():
            data_item.remove_ref()
