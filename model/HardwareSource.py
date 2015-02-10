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
import Queue as queue
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


class AcquisitionTask(object):

    """Basic acquisition task carries out acquisition repeatedly during acquisition loop, keeping track of state.

    The execute() method is performed repeatedly during the acquisition loop. It keeps track of the acquisition
    state, calling _start(), _abort(), _execute(), and _stop() as required.

    The caller can control the loop by calling abort() and stop().
    """

    def __init__(self, hardware_source, workspace_controller, continuous):
        self.__hardware_source = hardware_source
        self.__workspace_controller = workspace_controller
        self.__started = False
        self.__finished = False
        self.__aborted = False
        self.__stopped = False
        self.__continuous = continuous
        self.__last_acquire_time = None
        self.__minimum_period = 1/20.0
        self.__frame_index = 0
        self.__last_channel_to_data_item_dict = {}
        self.finished_event = Observable.Event()

    def __mark_as_finished(self):
        self.__finished = True
        self.__data_elements_changed(list())
        self.finished_event.fire()

    def execute(self):
        # first start the task
        if not self.__started:
            try:
                self.__start()
            except Exception as e:
                # the task is finished if it doesn't start
                self.__mark_as_finished()
                raise
            self.__started = True
            # logging.debug("started")
        if not self.__finished:
            try:
                # if aborted, abort here
                if self.__aborted:
                    # logging.debug("aborted")
                    self.__abort_acquisition()
                    self.__stop_acquisition()
                    self.__mark_as_finished()
                # otherwise execute the task
                else:
                    complete = self.__execute()
                    # logging.debug("executed %s", complete)
                    if complete and (self.__stopped or not self.__continuous):
                        # logging.debug("finished")
                        self.__stop_acquisition()
                        self.__mark_as_finished()
            except Exception as e:
                # the task is finished if it doesn't execute
                # logging.debug("exception")
                self.__mark_as_finished()
                raise

    @property
    def is_finished(self):
        return self.__finished

    def abort(self):
        self.__aborted = True

    def stop(self):
        self.__stopped = True

    @property
    def is_aborted(self):
        return self.__aborted

    @property
    def is_stopping(self):
        return self.__stopped

    def __start(self):
        self.__start_acquisition()
        self.__last_acquire_time = time.time() - self.__minimum_period

    def __execute(self):
        # impose maximum frame rate so that acquire_data_elements can't starve main thread
        elapsed = time.time() - self.__last_acquire_time
        time.sleep(max(0.0, self.__minimum_period - elapsed))

        data_elements = self.__acquire_data_elements()

        # update frame_index if not supplied
        for data_element in data_elements:
            data_element.setdefault("properties", dict()).setdefault("frame_index", self.__frame_index)
        self.__frame_index += 1

        # record the last acquisition time
        self.__last_acquire_time = time.time()

        # data_elements should never be empty
        assert data_elements is not None
        self.__data_elements_changed(data_elements)

        # figure out whether all data elements are complete
        complete = True
        for data_element in data_elements:
            sub_area = data_element.get("sub_area")
            state = data_element.get("state", "complete")
            if not (sub_area is None or state == "complete"):
                complete = False
                break
        return complete

    def __start_acquisition(self):
        self.__hardware_source.start_acquisition()

    def __abort_acquisition(self):
        self.__hardware_source.abort_acquisition()

    def __stop_acquisition(self):
        self.__hardware_source.stop_acquisition()
        self.__data_elements_changed(list())

    def __acquire_data_elements(self):
        return self.__hardware_source.acquire_data_elements()

    # this message comes from the hardware port.
    # data_elements is a list of data_elements; may be an empty list
    # thread safe
    def __data_elements_changed(self, data_elements):
        # TODO: deal wth overrun by asking for latest values.

        # build useful data structures (channel -> data)
        channel_to_data_element_map = {}
        channels = []
        for channel, data_element in enumerate(data_elements):
            if data_element is not None:
                channels.append(channel)
                channel_to_data_element_map[channel] = data_element

        # sync to data items
        channel_to_data_item_dict = self.__workspace_controller.sync_channels_to_data_items(channels, self.__hardware_source.hardware_source_id, self.__hardware_source.display_name)

        # these items are now live if we're playing right now. mark as such.
        for data_item in channel_to_data_item_dict.values():
            data_item.increment_data_ref_counts()
            document_model = self.__workspace_controller.document_model
            document_model.begin_data_item_transaction(data_item)
            document_model.begin_data_item_live(data_item)

        # update the data items with the new data.
        data_item_states = []
        for channel in channels:
            data_element = channel_to_data_element_map[channel]
            data_item = channel_to_data_item_dict[channel]
            ImportExportManager.update_data_item_from_data_element(data_item, data_element)
            channel_state = data_element.get("state", "complete")
            if channel_state != "complete":
                channel_state = channel_state if not self.is_finished else "marked"
            data_item_state = dict()
            data_item_state["channel"] = channel
            data_item_state["data_item"] = data_item
            data_item_state["channel_state"] = channel_state
            if "sub_area" in data_element:
                data_item_state["sub_area"] = data_element["sub_area"]
            data_item_states.append(data_item_state)
        self.__hardware_source.notify_listeners("hardware_source_updated_data_item_states", data_item_states)

        # these items are no longer live. mark live_data as False.
        for channel, data_item in self.__last_channel_to_data_item_dict.iteritems():
            # the order of these two statements is important, at least for now (12/2013)
            # when the transaction ends, the data will get written to disk, so we need to
            # make sure it's still in memory. if decrement were to come before the end
            # of the transaction, the data would be unloaded from memory, losing it forever.
            document_model = self.__workspace_controller.document_model
            document_model.end_data_item_transaction(data_item)
            document_model.end_data_item_live(data_item)
            data_item.decrement_data_ref_counts()

        # keep the channel to data item map around so that we know what changed between
        # last iteration and this one. also handle reference counts.
        self.__last_channel_to_data_item_dict = channel_to_data_item_dict

        # let listeners know too
        if self.__continuous:
            self.__hardware_source.viewed_data_elements_available_event.fire(data_elements)
        else:
            self.__hardware_source.recorded_data_elements_available_event.fire(data_elements)


class HardwareSource(Observable.Broadcaster):
    """Represent a piece of hardware and provide the means to acquire data from it in view or record mode."""

    def __init__(self, hardware_source_id, display_name):
        super(HardwareSource, self).__init__()
        self.hardware_source_id = hardware_source_id
        self.display_name = display_name
        self.features = dict()
        self.viewed_data_elements_available_event = Observable.Event()
        self.recorded_data_elements_available_event = Observable.Event()
        self.playing_state_changed_event = Observable.Event()
        self.recording_state_changed_event = Observable.Event()
        self.__acquire_thread_break = False
        self.__acquire_thread_trigger = threading.Event()
        self.__view_task = None
        self.__record_task = None
        self.__view_task_finished_event_listener = None
        self.__record_task_finished_event_listener = None
        self.__acquire_thread = threading.Thread(target=self.__acquire_thread_loop)
        self.__acquire_thread.daemon = True
        self.__acquire_thread.start()

    def close(self):
        self.__acquire_thread_break = True
        self.__acquire_thread_trigger.set()
        self.__acquire_thread = None

    def __acquire_thread_loop(self):
        while self.__acquire_thread_trigger.wait():
            self.__acquire_thread_trigger.clear()
            # record task gets highest priority
            acquire_thread_break = self.__acquire_thread_break
            if self.__record_task:
                if acquire_thread_break:
                    self.__record_task.abort()
                try:
                    self.__record_task.execute()
                except Exception as e:
                    import traceback
                    logging.debug("Acquisition Error: %s", e)
                    traceback.print_exc()
                    traceback.print_stack()
                if self.__record_task.is_finished:
                    self.__record_task = None
                self.__acquire_thread_trigger.set()
            # view task gets next priority
            elif self.__view_task:
                if acquire_thread_break:
                    self.__view_task.abort()
                try:
                    self.__view_task.execute()
                except Exception as e:
                    import traceback
                    logging.debug("Acquisition Error: %s", e)
                    traceback.print_exc()
                    traceback.print_stack()
                if self.__view_task.is_finished:
                    self.__view_task = None
                self.__acquire_thread_trigger.set()
            if acquire_thread_break:
                break

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

    # subclasses are expected to implement this function efficiently since it will
    # be repeatedly called. in practice that means that subclasses MUST sleep (directly
    # or indirectly) unless the data is immediately available, which it shouldn't be on
    # a regular basis. it is an error for this function to return an empty list of data_elements.
    # must be thread safe
    def acquire_data_elements(self):
        raise NotImplementedError()

    # create the view task
    def create_acquisition_view_task(self, workspace_controller):
        return AcquisitionTask(self, workspace_controller, True)

    # create the view task
    def create_acquisition_record_task(self, workspace_controller):
        return AcquisitionTask(self, workspace_controller, False)

    # return whether acquisition is running
    @property
    def is_playing(self):
        acquire_thread_view = self.__view_task  # assignment for lock free thread safety
        return acquire_thread_view is not None and not acquire_thread_view.is_finished

    # call this to start acquisition
    # not thread safe
    def start_playing(self, workspace_controller):
        if not self.is_playing:
            acquisition_task = self.create_acquisition_view_task(workspace_controller)
            def acquire_thread_view_finished():
                self.playing_state_changed_event.fire(False)
                self.__view_task_finished_event_listener.close()
                self.__view_task_finished_event_listener = None
            def queue_acquire_thread():
                workspace_controller.document_controller.queue_task(acquire_thread_view_finished)
            self.__view_task_finished_event_listener = acquisition_task.finished_event.listen(queue_acquire_thread)
            self.__view_task = acquisition_task
            self.__acquire_thread_trigger.set()
            self.playing_state_changed_event.fire(True)

    # call this to stop acquisition immediately
    # not thread safe
    def abort_playing(self):
        acquire_thread_view = self.__view_task
        if acquire_thread_view:
            acquire_thread_view.abort()

    # call this to stop acquisition gracefully
    # not thread safe
    def stop_playing(self):
        acquire_thread_view = self.__view_task
        if acquire_thread_view:
            acquire_thread_view.stop()

    # return whether acquisition is running
    @property
    def is_recording(self):
        acquire_thread_record = self.__record_task  # assignment for lock free thread safety
        return acquire_thread_record is not None and not acquire_thread_record.is_finished

    # call this to start acquisition
    # not thread safe
    def start_recording(self, workspace_controller):
        if not self.is_recording:
            acquisition_task = self.create_acquisition_record_task(workspace_controller)
            def acquire_thread_record_finished():
                self.recording_state_changed_event.fire(False)
                self.__record_task_finished_event_listener.close()
                self.__record_task_finished_event_listener = None
            def queue_acquire_thread():
                workspace_controller.document_controller.queue_task(acquire_thread_record_finished)
            self.__record_task_finished_event_listener = acquisition_task.finished_event.listen(queue_acquire_thread)
            self.__record_task = acquisition_task
            self.__acquire_thread_trigger.set()
            self.recording_state_changed_event.fire(True)

    # call this to stop acquisition immediately
    # not thread safe
    def abort_recording(self):
        acquire_thread_record = self.__record_task
        if acquire_thread_record:
            acquire_thread_record.abort()

    # call this to stop acquisition gracefully
    # not thread safe
    def stop_recording(self):
        acquire_thread_record = self.__record_task
        if acquire_thread_record:
            acquire_thread_record.stop()


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

    viewed_data_elements_available_event_listener = hardware_source.viewed_data_elements_available_event.listen(receive_new_data_elements)

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
        viewed_data_elements_available_event_listener.close()


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
