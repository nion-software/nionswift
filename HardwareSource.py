"""
This module defines a couple of classes proposed as a framework for handling live image
sources.

A HardwareSource represents a source of images.
A client accesses images through the create_port function
which changes the mode of the source, and starts it, and starts notifying the returned
port object. The port object should not do any significant processing in its on_new_image
function but should instead just notify another thread that new data is available.

The hardware source does allow processing to happen at acquisition time, by setting its
filter member to a method that takes an image and returns an image.

One idea is that there would be a Screen class, containing multiple ports, which would
contain a single pre-display processing thread. This thread would listen to messages posted
by the ports getting a new image, then get the data from the port, process to make
compatible with the Screen, then push the images into it.

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
from nion.swift import DataGroup
from nion.swift import DataItem

_ = gettext.gettext


@Decorators.singleton
class HardwareSourceManager(object):
    """
    Keeps track of all registered hardware sources.
    Also keeps track of aliases between hardware sources and logical names.
    The aliases can contain a filter to only return a subset of images.
    This way we can create an alias for the 'RonchigramCamera' to, say,
    NionCCD1010, channel 0, properties="Tuning", and HAADF Signal to
    superscan, channel 1 (we can override the properties when we create the
    port if necessary too).

    And should we alias SuperScan,0 to HAADF Signal, or SuperScan to 'ScanUnit' and let
    users know that ScanUnit,0 is HAADF? I think I prefer the former approach, and we might
    be able to do this by sepcifying a filter to the port class.

    """
    def __init__(self):
        self._all_hw_ports = []
        self._aliases = {}
        # we create a list of callbacks for when a hardware
        # source is added or removed
        self.hardware_source_added_removed = []

    def _reset(self):  # used for testing to start from scratch
        self._all_hw_ports = []
        self._aliases = {}
        self.hardware_source_added_removed = []

    def register_hardware_source(self, hw_src):
        self._all_hw_ports.append(hw_src)
        for f in self.hardware_source_added_removed:
            f(self, None)

    def unregister_hardware_source(self, hw_src):
        self._all_hw_ports.remove(hw_src)
        for f in self.hardware_source_added_removed:
            f(self, None)

    def create_port_for_name(self, owner, hw_source_name, override_props=None):
        """
        Alias for HardwareSource.create_port, with the added benefit
        of looking up aliases.

        Returns a newly created port for the hw_source_name given.
        If hw_source_name is the name of a hardware source,
        it will return that source, with the port listening for all channels.
        If hw_source_name is an alias, it will return the hardware source it
        refers to with the filter and props registered for that alias.

        Owner is an object whose string representation is used to indicate
        ownership of the hardware port, and should be set to something
        descriptive of where the port is being used.

        Eg:
        manager.make_hardware_source_alias(
            "ronchigramcamera", "Tuning", 0)
        port = manager.create_port_for_name("example_script", "ronchigramcamera")
        ...
        port.close()
        """
        if hw_source_name in self._aliases:
            hw_source_name, props, filter = self._aliases[hw_source_name]
        else:
            props, filter = "Default", None

        if override_props:
            props = override_props

        hw_source_name = str(hw_source_name)
        for w in self._all_hw_ports:
            if str(w) == hw_source_name:
                return w.create_port(owner, props, filter)
        return None

    def make_hardware_source_alias(self, alias, hardware_source, props="Default", filter=None):
        self._aliases[alias] = (str(hardware_source), props, filter)

    def get_all_sources(self, include_aliases=False):
        """
        Returns a string representation of all registered sources.
        If include_aliases is true, also includes the registered aliases.
        """
        ret = [str(s) for s in self._all_hw_ports]
        if include_aliases:
            ret += self._aliases.keys()
        return ret


class HardwareSource(object):
    """
    A hardware source provides ports, which in turn provide images.

    Ports are created based on asked-for properties. The current properties of
    the HW source are always those most recently requested, ie the properties
    of the last port created. A filter can optionally be passed to a port which
    selects which of the returned list of images to return. It should be either
    a single index or a list of indices. If None, all images are returned.

    A separate acquisition thread is used for acquiring all data and
    passing on to the ports. When a HardwareSource has no ports, this
    thread can stop running (when appropriate). The start_acquisition,
    stop_acquisition and set_from_props functions are always only ever
    called from the acquisition thread
    """
    class HWSourcePort():
        def __init__(self, name, props, parent, filter):
            self.name = name
            self.props = props
            self.parent_source = parent
            self.on_new_images = None
            self.last_images = None
            self.filter = filter
            if isinstance(self.filter, numbers.Integral):
                self.filter = (self.filter, )

        def want_image(self, props):
            """
            Return True if we will accept an image with the given properties.
            """
            return True

        def get_last_images(self):
            return self.last_images

        def _set_new_images(self, images):
            if self.filter:
                self.last_images = [ims for i, ims in enumerate(images) if i in self.filter]
            else:
                self.last_images = images
            if self.on_new_images:
                self.on_new_images(self.last_images)

        def close(self):
            """
            Closes the port. Identical to calling HardwareSource.remove_port(self).
            """
            self.parent_source.remove_port(self)

    def __init__(self):
        self.ports = []
        self.__portlock = threading.Lock()
        self.filter = None

    def create_port(self, name, props, filter=None):
        with self.__portlock:
            ret = HardwareSource.HWSourcePort(name, props, self, filter)
            start_thread = len(self.ports) == 0  # start a new thread if it's not already running (i.e. there are no current ports)
            self.ports.append(ret)
            self.set_from_props(props)
        if start_thread:
            # we should do this a little nicer. Specifically, if we start a new thread
            # the existing one could carry on two. We should make sure we can only have one
            self.acquire_thread = threading.Thread(target=self.acquire_thread_loop)
            self.acquire_thread.start()
        return ret

    def remove_port(self, lst):
        """
        Removes the port lst. Usually performed via port.close()
        """
        with self.__portlock:
            self.ports.remove(lst)

    def acquire_thread_loop(self):
        self.start_acquisition()
        try:
            last_props = None
            new_images = None

            while True:
                with self.__portlock:
                    if not self.ports:
                        break

                    if last_props != self.ports[-1].props:
                        last_props = self.ports[-1].props
                        self.set_from_props(last_props)

                    for port in self.ports:
                        # check to make sure we actually have new images,
                        # since this might be the first time through the loop.
                        # otherwise the image list gets cleared and new images
                        # get created when the images become available.
                        if port.want_image(last_props) and new_images:
                            port._set_new_images(new_images)

                new_images = self.acquire()

                # new_images should never be empty
                assert new_images
        finally:
            self.stop_acquisition()

    def start_acquisition(self):
        pass

    def stop_acquisition(self):
        pass

    # subclasses are expected to implement this function efficiently since it will
    # be repeatedly called. in practice that means that subclasses MUST sleep (directly
    # or indirectly) unless the data is immediately available, which it shouldn't be on
    # a regular basis. it is an error for this function to return an empty list of images.
    def acquire(self):
        raise NotImplementedError("HardwareSource.acquire must be implemented")

    def set_from_props(self, props):
        pass

    def __str__(self):
        return "unnamed hwsource"


class HardwareSourceDataBuffer(object):
    """
    For the given HWSource (which can either be an object with a create_port function, or a name. If
    a name, ports are created using the HardwareSourceManager.create_port_for_name function,
    and aliases can be supplied), creates a port and listens for any images.
    Manages a collection of DataItems for all images returned.
    The DataItems are owned by this, and persist while the acquisition is live,
    if the user wants to remove the data items, they should stop the acquisition
    first.

    DataItems are resued if available - we reuse them by searching through all images
    in the 'Sources' data_group, based on name (could use more advanced metadata in the
    future f necessary).

    """
    data_group_name = _("Sources")

    def __init__(self, hardware_source, document_controller):
        self.hardware_source = hardware_source
        self.document_controller = document_controller
        self.hardware_source_man = HardwareSourceManager()
        self.hardware_port = None
        self.data_group = self.document_controller.get_or_create_data_group(self.data_group_name)
        self.first_data = False
        self.last_channel_to_data_item_dict = {}
        self.__snapshots = collections.deque(maxlen=30)
        self.__current_snapshot = 0
        self.__weak_listeners = []

    def close(self):
        logging.info("Closing HardwareSourceDataBuffer for %s", str(self.hardware_source))
        if self.hardware_port is not None:
            self.pause()
            # we should be consistent about how we stop live acquisitions:
            # stopping should be identical to acquiring with no channels selected
            # and we should delete/keep data items the same in both cases.
            # esaiest way is to call on_new_images(None)
            # now that we've set hardware_port to None
            # if we do want to keep data items, it should be done in on_new_images
            self.on_new_images([])

    # Add a listener. Listeners will receive data_item_changed message when this
    # DataItem is notified of a change via the notify_data_item_changed() method.
    def add_listener(self, listener):
        assert listener is not None
        self.__weak_listeners.append(weakref.ref(listener))
    # Remove a listener.
    def remove_listener(self, listener):
        assert listener is not None
        self.__weak_listeners.remove(weakref.ref(listener))
    # Return a copy of listeners array
    def __get_listeners(self):
        return [weak_listener() for weak_listener in self.__weak_listeners]
    listeners = property(__get_listeners)
    # Send a message to the listeners
    def notify_listeners(self, fn, *args, **keywords):
        for listener in self.listeners:
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
            self.update_images(self.__snapshots[self.__current_snapshot])
            self.notify_listeners("current_snapshot_changed", self.hardware_source, self.__current_snapshot)
    current_snapshot = property(__get_current_snapshot, __set_current_snapshot)

    def __get_snapshot_count(self):
        return len(self.__snapshots)
    snapshot_count = property(__get_snapshot_count)

    def start(self):
        logging.info("Starting HardwareSourceDataBuffer for %s", str(self.hardware_source))
        if self.hardware_port is None:
            if hasattr(self.hardware_source, "create_port"):
                self.hardware_port = self.hardware_source.create_port("ui", "default")
            else:
                self.hardware_port = self.hardware_source_man.create_port_for_name(
                    "LiveHWPortToImageSource", str(self.hardware_source))
            self.hardware_port.on_new_images = self.on_new_images
            self.first_data = True

    def pause(self):
        logging.info("Pausing HardwareSourceDataBuffer for %s", str(self.hardware_source))
        if self.hardware_port is not None:
            self.hardware_port.on_new_images = None
            self.hardware_port.close()
            # finally we remove the reference to the port. on_new_images needs it around
            # above to get the name of any existing data_items
            self.hardware_port = None
        for channel in self.last_channel_to_data_item_dict.keys():
            data_item = self.last_channel_to_data_item_dict[channel]
            data_item.live_data = False

    def on_new_images(self, images):
        """
        For the array of images to show, images, go through either
        creating a new dataitem or using an existing one if the image
        is not null. The order of images is important, the channel is
        used to find the appropriate dataitem.
        """
        if not self.hardware_port:
            images = []

        # snapshots
        snapshot_count = len(self.__snapshots)
        self.__snapshots.append(images)
        if len(self.__snapshots) != snapshot_count:
            self.notify_listeners("snapshot_count_changed", self.hardware_source, len(self.__snapshots))

        # update the data on the data items
        self.update_images(images)

        # notify listeners if we change current snapshot
        current_snapshot = len(self.__snapshots) - 1
        if self.__current_snapshot != current_snapshot:
            self.__current_snapshot = current_snapshot
            self.notify_listeners("current_snapshot_changed", self.hardware_source, self.__current_snapshot)

    def update_images(self, images):
        # build useful data structures (channel -> data)
        channel_to_data_dict = {}
        channels = []
        for channel, data in enumerate(images):
            if data is not None:
                channels.append(channel)
                channel_to_data_dict[channel] = data

        # sync to data items
        new_channel_to_data_item_dict = self.document_controller.sync_channels_to_data_items(channels, self.data_group, str(self.hardware_source))

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
            new_channel_to_data_item_dict[channel].master_data = channel_to_data_dict[channel]

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
