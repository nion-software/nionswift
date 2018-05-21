"""
This module defines classes for handling live data sources.

A HardwareSource represents a source of data and metadata frames.

An AcquisitionTask tracks the state for a particular acquisition of a frame or sequence of frames.

The HardwareSourceManager allows callers to register and unregister hardware sources.

This module also defines individual functions that can be used to collect data from hardware sources.
"""

# system imports
import configparser
import contextlib
import copy
import enum
import functools
import gettext
import logging
import os
import threading
import time
import typing
import traceback
import uuid

# library imports
import numpy

# local imports
from nion.data import Core
from nion.data import DataAndMetadata
from nion.swift.model import DataItem
from nion.swift.model import Graphics
from nion.swift.model import ImportExportManager
from nion.swift.model import Utility
from nion.utils import Event
from nion.utils import Observable
from nion.utils import Persistence

_ = gettext.gettext


# Keeps track of all registered hardware sources and instruments.
# Also keeps track of aliases between hardware sources and logical names.
class HardwareSourceManager(metaclass=Utility.Singleton):
    def __init__(self):
        super().__init__()
        self.hardware_sources = list()
        self.instruments = list()
        # we create a list of callbacks for when a hardware
        # source is added or removed
        self.hardware_source_added_event = Event.Event()
        self.hardware_source_removed_event = Event.Event()
        self.instrument_added_event = Event.Event()
        self.instrument_removed_event = Event.Event()
        self.aliases_updated = list()
        # aliases are shared between hardware sources and instruments
        self.__aliases = dict()

    def close(self):
        self._close_hardware_sources()
        self._close_instruments()

    def _close_instruments(self):
        for instrument in self.instruments:
            if hasattr(instrument, "close"):
                instrument.close()
        self.instruments = []

    def _close_hardware_sources(self):
        for hardware_source in self.hardware_sources:
            if hasattr(hardware_source, "close"):
                hardware_source.close()
        self.hardware_sources = []

    def _reset(self):  # used for testing to start from scratch
        self.hardware_sources = []
        self.instruments = []
        self.hardware_source_added_event = Event.Event()
        self.hardware_source_removed_event = Event.Event()
        self.instrument_added_event = Event.Event()
        self.instrument_removed_event = Event.Event()
        self.__aliases = {}

    def register_hardware_source(self, hardware_source):
        self.hardware_sources.append(hardware_source)
        self.hardware_source_added_event.fire(hardware_source)

    def unregister_hardware_source(self, hardware_source):
        self.hardware_sources.remove(hardware_source)
        self.hardware_source_removed_event.fire(hardware_source)

    def register_instrument(self, instrument_id, instrument):
        instrument.instrument_id = instrument_id
        self.instruments.append(instrument)
        self.instrument_added_event.fire(instrument)

    def unregister_instrument(self, instrument_id):
        for instrument in self.instruments:
            if instrument.instrument_id == instrument_id:
                instrument.instrument_id = None
                self.instruments.remove(instrument)
                self.instrument_removed_event.fire(instrument)
                break

    def abort_all_and_close(self):
        for hardware_source in copy.copy(self.hardware_sources):
            hardware_source.abort_playing()

    def get_all_instrument_ids(self):
        instrument_ids = set()
        instrument_ids.update(list(instrument.instrument_id for instrument in self.instruments))
        for alias in self.__aliases.keys():
            resolved_alias = self.get_instrument_by_id(alias)
            if resolved_alias:
                instrument_ids.add(alias)
        return instrument_ids

    def get_all_hardware_source_ids(self):
        hardware_source_ids = set()
        hardware_source_ids.update(list(hardware_source.hardware_source_id for hardware_source in self.hardware_sources))
        for alias in self.__aliases.keys():
            resolved_alias = self.get_hardware_source_for_hardware_source_id(alias)
            if resolved_alias:
                hardware_source_ids.add(alias)
        return hardware_source_ids

    def __get_info_for_instrument_id(self, instrument_id):
        display_name = str()
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
        display_name = str()
        seen_hardware_source_ids = []  # prevent loops, just so we don't get into endless loop in case of user error
        while hardware_source_id in self.__aliases and hardware_source_id not in seen_hardware_source_ids:
            seen_hardware_source_ids.append(hardware_source_id)  # must go before next line
            hardware_source_id, display_name = self.__aliases[hardware_source_id]
        for hardware_source in self.hardware_sources:
            if hardware_source.hardware_source_id == hardware_source_id:
                return hardware_source, display_name
        return None

    def get_hardware_source_for_hardware_source_id(self, hardware_source_id: str) -> "HardwareSource":
        info = self.__get_info_for_hardware_source_id(hardware_source_id)
        if info:
            hardware_source, display_name = info
            return hardware_source
        return None

    def make_instrument_alias(self, instrument_id, alias_instrument_id, display_name):
        """ Configure an alias.

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


class AcquisitionTask:
    """Basic acquisition task carries out acquisition repeatedly during an acquisition loop, keeping track of state.

    The caller controls the state of the task by calling the following methods:
        execute: start or continue acquisition, should be called repeatedly until is_finished is True
        suspend: suspend the state of acquisition
        resume: resume a suspended state of acquisition
        stop: notify that acquisition should stop after end of current frame
        abort: notify that acquisition should abort as soon as possible

    In addition the caller can query the state of acquisition using the following method:
        is_finished: whether acquisition has finished or not

    Finally, the caller can listen to the following events:
        data_elements_changed_event(data_elements, is_continuous, view_id, is_complete, is_stopping):
            fired when data elements change. the state of acquisition is passed too.

    Subclasses can override these methods to implement the acquisition:
        _start_acquisition: called once at the beginning of this task
        _abort_acquisition: called from thread when the caller has requested to abort acquisition; guaranteed to be called synchronously.
        _request_abort_acquisition: called from UI when the called has requested to abort acquisition; may be called asynchronously.
        _suspend_acquisition: called when the caller has requested to suspend acquisition
        _resume_acquisition: called when the caller has requested to resume a suspended acquisition
        _mark_acquisition: marks the acquisition to stop at end of current frame
        _acquire_data_elements: return list of data elements, with metadata indicating completion status
        _stop_acquisition: final call to indicate acquisition has stopped; subclasses should synchronize stop here
    """

    def __init__(self, continuous: bool):
        self.__started = False
        self.__finished = False
        self.__is_suspended = False
        self.__aborted = False
        self.__is_stopping = False
        self.__is_continuous = continuous
        self.__last_acquire_time = None
        self.__minimum_period = 1/1000.0
        self.__frame_index = 0
        self.__view_id = str(uuid.uuid4()) if not continuous else None
        self._test_acquire_exception = None
        self._test_acquire_hook = None
        self.start_event = Event.Event()
        self.stop_event = Event.Event()
        self.data_elements_changed_event = Event.Event()
        self.finished_callback_fn = None  # hack to determine when 'record' mode finishes.

    def __mark_as_finished(self):
        self.__finished = True
        self.data_elements_changed_event.fire(list(), self.__view_id, False, self.__is_stopping)

    # called from the hardware source
    # note: abort, suspend and execute are always called from the same thread, ensuring that
    # one can't be executing when the other is called.
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
            # logging.debug("%s started", self)
        if self.__is_suspended:
            try:
                self._resume_acquisition()
            finally:
                self.__is_suspended = False
        if not self.__finished:
            try:
                # if aborted, abort here
                if self.__aborted:
                    # logging.debug("%s aborted", self)
                    self._abort_acquisition()
                    # logging.debug("%s stopped", self)
                    self._mark_acquisition()
                    self._stop_acquisition()
                    self.__mark_as_finished()
                # otherwise execute the task
                else:
                    complete = self.__execute_acquire_data_elements()
                    # logging.debug("%s executed %s", self, complete)
                    if complete and (self.__is_stopping or not self.__is_continuous):
                        # logging.debug("%s finished", self)
                        self._stop_acquisition()
                        self.__mark_as_finished()
            except Exception as e:
                # the task is finished if it doesn't execute
                # logging.debug("exception")
                self._stop_acquisition()
                self.__mark_as_finished()
                raise

    # called from the hardware source
    # note: abort, suspend and execute are always called from the same thread, ensuring that
    # one can't be executing when the other is called.
    def suspend(self) -> None:
        if not self.__is_suspended:
            self.__is_suspended = True
            self._suspend_acquisition()

    @property
    def is_finished(self):
        return self.__finished

    # called from the hardware source
    # note: abort, suspend and execute are always called from the same thread, ensuring that
    # one can't be executing when the other is called.
    def abort(self):
        self.__aborted = True
        self._request_abort_acquisition()

    # called from the hardware source
    def stop(self):
        self.__is_stopping = True
        self._mark_acquisition()

    def __start(self):
        if not self._start_acquisition():
            self.abort()
        self.__last_acquire_time = time.time() - self.__minimum_period

    def __execute_acquire_data_elements(self):
        # with Utility.trace(): # (min_elapsed=0.0005, discard="anaconda"):
        # impose maximum frame rate so that acquire_data_elements can't starve main thread
        elapsed = time.time() - self.__last_acquire_time
        time.sleep(max(0.0, self.__minimum_period - elapsed))

        if self._test_acquire_hook:
            self._test_acquire_hook()

        partial_data_elements = self._acquire_data_elements()
        assert partial_data_elements is not None  # data_elements should never be empty

        # update frame_index if not supplied
        for data_element in partial_data_elements:
            data_element.setdefault("properties", dict()).setdefault("frame_index", self.__frame_index)

        data_elements = copy.copy(partial_data_elements)

        # record the last acquisition time
        self.__last_acquire_time = time.time()

        # figure out whether all data elements are complete
        complete = True
        for data_element in data_elements:
            sub_area = data_element.get("sub_area")
            state = data_element.get("state", "complete")
            if not (sub_area is None or state == "complete"):
                complete = False
                break

        # notify that data elements have changed. at this point data_elements may contain data stored in low level code.
        self.data_elements_changed_event.fire(data_elements, self.__view_id, complete, self.__is_stopping)

        if complete:
            self.__frame_index += 1

        return complete

    # override these routines. the default implementation is to
    # call back to the hardware source.

    # subclasses can implement to start acquisition. it is called once.
    # return True if successful, False if not.
    # called synchronously from execute thread.
    # must be thread safe
    def _start_acquisition(self) -> bool:
        self.start_event.fire()
        return True

    # subclasses can implement this method to abort acquisition.
    # aborted tasks will still get marked, stopped, and send out final
    # data_elements_changed_events and finished_events.
    # called synchronously from execute thread.
    # must be thread safe
    def _abort_acquisition(self) -> None:
        pass

    # subclasses can implement this method which is called when acquisition abort is requested.
    # this is useful if a flag/event needs to be set to break out of the acquisition loop.
    # this method may be called asynchronously from the other methods.
    # must be thread safe. it may be called from either UI thread or a thread.
    def _request_abort_acquisition(self) -> None:
        pass

    # subclasses can implement this method which is called when acquisition is suspended for higher priority acquisition.
    # if a view starts during a record, it will start in a suspended state and resume will be called without a prior
    # suspend.
    # called synchronously from execute thread.
    # must be thread safe
    def _suspend_acquisition(self) -> None:
        pass

    # subclasses can implement this method which is called when acquisition is resumed from higher priority acquisition.
    # if a view starts during a record, it will start in a suspended state and resume will be called without a prior
    # suspend.
    # called synchronously from execute thread.
    # must be thread safe
    def _resume_acquisition(self) -> None:
        pass

    # subclasses can implement this method which is called when acquisition is marked for stopping.
    # subclasses that feature a continuous mode will need implement this method so that continuous
    # mode is marked for stopping at the end of the current frame.
    # called synchronously from execute thread.
    # must be thread safe
    def _mark_acquisition(self) -> None:
        pass

    # subclasses can implement this method which is called to stop acquisition.
    # no more data is expected to be generated after this call.
    # called synchronously from execute thread.
    # must be thread safe
    def _stop_acquisition(self) -> None:
        self.stop_event.fire()

    # subclasses are expected to implement this function efficiently since it will
    # be repeatedly called. in practice that means that subclasses MUST sleep (directly
    # or indirectly) unless the data is immediately available, which it shouldn't be on
    # a regular basis. it is an error for this function to return an empty list of data_elements.
    # this method can throw exceptions, it will result in the acquisition loop being aborted.
    # returns a tuple of a list of data elements.
    # called synchronously from execute thread.
    # must be thread safe
    def _acquire_data_elements(self):
        raise NotImplementedError()


class DataChannel:
    """A channel of raw data from a hardware source.

    The channel buffer is an interface to the stream of data from a hardware source to a client
    of that stream.

    The client can listen to the following events from the channel:
        * data_channel_updated_event
        * data_channel_start_event
        * data_channel_stop_event

    All events will be fired the acquisition thread.

    The client can access the following properties of the channel:
        * channel_id
        * name
        * state
        * src_channel_index
        * sub_area
    """
    def __init__(self, hardware_source: "HardwareSource", index: int, channel_id: str=None, name: str=None, src_channel_index: int=None, processor=None):
        self.__hardware_source = hardware_source
        self.__index = index
        self.__channel_id = channel_id
        self.__name = name
        self.__src_channel_index = src_channel_index
        self.__processor = processor
        self.__start_count = False
        self.__state = None
        self.__sub_area = None
        self.__data_and_metadata = None
        self.is_dirty = False
        self.data_channel_updated_event = Event.Event()
        self.data_channel_start_event = Event.Event()
        self.data_channel_stop_event = Event.Event()

    @property
    def index(self):
        return self.__index

    @property
    def channel_id(self):
        return self.__channel_id

    @property
    def name(self):
        return self.__name

    @property
    def state(self):
        return self.__state

    @property
    def sub_area(self):
        return self.__sub_area

    @property
    def src_channel_index(self):
        return self.__src_channel_index

    @property
    def processor(self):
        return self.__processor

    @property
    def data_and_metadata(self):
        return self.__data_and_metadata

    @property
    def is_started(self):
        return self.__start_count > 0

    def update(self, data_and_metadata: DataAndMetadata.DataAndMetadata, state: str, sub_area, view_id) -> None:
        """Called from hardware source when new data arrives."""
        self.__state = state
        self.__sub_area = sub_area

        hardware_source_id = self.__hardware_source.hardware_source_id
        channel_index = self.index
        channel_id = self.channel_id
        channel_name = self.name
        metadata = copy.deepcopy(data_and_metadata.metadata)
        hardware_source_metadata = dict()
        hardware_source_metadata["hardware_source_id"] = hardware_source_id
        hardware_source_metadata["channel_index"] = channel_index
        if channel_id is not None:
            hardware_source_metadata["channel_id"] = channel_id
        if channel_name is not None:
            hardware_source_metadata["channel_name"] = channel_name
        if view_id:
            hardware_source_metadata["view_id"] = view_id
        metadata.setdefault("hardware_source", dict()).update(hardware_source_metadata)

        data = data_and_metadata.data
        master_data = self.__data_and_metadata.data if self.__data_and_metadata else None
        data_matches = master_data is not None and data.shape == master_data.shape and data.dtype == master_data.dtype
        if data_matches and sub_area is not None:
            top = sub_area[0][0]
            bottom = sub_area[0][0] + sub_area[1][0]
            left = sub_area[0][1]
            right = sub_area[0][1] + sub_area[1][1]
            if top > 0 or left > 0 or bottom < data.shape[0] or right < data.shape[1]:
                master_data = numpy.copy(master_data)
                master_data[top:bottom, left:right] = data[top:bottom, left:right]
            else:
                master_data = numpy.copy(data)
        else:
            master_data = numpy.copy(data)

        data_descriptor = data_and_metadata.data_descriptor
        intensity_calibration = data_and_metadata.intensity_calibration if data_and_metadata else None
        dimensional_calibrations = data_and_metadata.dimensional_calibrations if data_and_metadata else None
        timestamp = data_and_metadata.timestamp
        new_extended_data = DataAndMetadata.new_data_and_metadata(master_data, intensity_calibration=intensity_calibration, dimensional_calibrations=dimensional_calibrations, metadata=metadata, timestamp=timestamp, data_descriptor=data_descriptor)

        self.__data_and_metadata = new_extended_data

        self.data_channel_updated_event.fire(new_extended_data)
        self.is_dirty = True

    def start(self):
        """Called from hardware source when data starts streaming."""
        old_start_count = self.__start_count
        self.__start_count += 1
        if old_start_count == 0:
            self.data_channel_start_event.fire()

    def stop(self):
        """Called from hardware source when data stops streaming."""
        self.__start_count -= 1
        if self.__start_count == 0:
            self.data_channel_stop_event.fire()


class HardwareSource:
    """Represents a source of data and metadata frames.

    The hardware source generates data on a background thread.
    """

    def __init__(self, hardware_source_id, display_name):
        super().__init__()
        self.__hardware_source_id = hardware_source_id
        self.__display_name = display_name
        self.__data_channels = list()  # type: typing.List[DataChannel]
        self.features = dict()
        self.data_channel_states_updated = Event.Event()
        self.xdatas_available_event = Event.Event()
        self.abort_event = Event.Event()
        self.acquisition_state_changed_event = Event.Event()
        self.data_item_states_changed_event = Event.Event()
        self.property_changed_event = Event.Event()
        self.call_soon_event = Event.Event()
        self.__break_for_closing = False
        self.__acquire_thread_trigger = threading.Event()
        self.__tasks = dict()  # type: typing.Dict[str, AcquisitionTask]
        self.__data_elements_changed_event_listeners = dict()
        self.__start_event_listeners = dict()
        self.__stop_event_listeners = dict()
        self.__acquire_thread = threading.Thread(target=self.__acquire_thread_loop)
        self.__acquire_thread.daemon = True
        self.__acquire_thread.start()
        self._test_acquire_exception = None
        self._test_acquire_hook = None

    def close(self):
        self.close_thread()

    @property
    def hardware_source_id(self):
        return self.__hardware_source_id

    @hardware_source_id.setter
    def hardware_source_id(self, value):
        self.__hardware_source_id = value
        self.property_changed_event.fire("hardware_source_id")

    @property
    def display_name(self):
        return self.__display_name

    @display_name.setter
    def display_name(self, value):
        self.__display_name = value
        self.property_changed_event.fire("display_name")

    def close_thread(self):
        if self.__acquire_thread:
            # when overriding hardware source close, the acquisition loop may still be running
            # so nothing can be changed here that will make the acquisition loop fail.
            self.__break_for_closing = True
            self.__acquire_thread_trigger.set()
            # acquire_thread should always be non-null here, otherwise close was called twice.
            self.__acquire_thread.join()
            self.__acquire_thread = None

    def _call_soon(self, fn):
        self.call_soon_event.fire_any(fn)

    def __acquire_thread_loop(self):
        # acquire_thread_trigger should be set whenever the task list change.
        while self.__acquire_thread_trigger.wait():
            self.__acquire_thread_trigger.clear()
            # record task gets highest priority
            break_for_closing = self.__break_for_closing
            suspend_task_id_list = list()
            task_id = None
            if self.__tasks.get('idle'):
                task_id = 'idle'
            if self.__tasks.get('view'):
                task_id = 'view'
                suspend_task_id_list.append('idle')
            if self.__tasks.get('record'):
                task_id = 'record'
                suspend_task_id_list.append('idle')
                suspend_task_id_list.append('view')
            if task_id:
                task = self.__tasks[task_id]
                if break_for_closing:
                    # abort the task, but execute one last time to make sure stop
                    # gets called.
                    task.abort()
                    self.abort_event.fire()
                try:
                    for suspend_task_id in suspend_task_id_list:
                        suspend_task = self.__tasks.get(suspend_task_id)
                        if suspend_task:
                            suspend_task.suspend()
                    task.execute()
                except Exception as e:
                    task.abort()
                    self.abort_event.fire()
                    if callable(self._test_acquire_exception):
                        self._test_acquire_exception(e)
                    else:
                        import traceback
                        logging.debug("{} Error: {}".format(task_id.capitalize(), e))
                        traceback.print_exc()
                if task.is_finished:
                    del self.__tasks[task_id]
                    self.__data_elements_changed_event_listeners[task_id].close()
                    del self.__data_elements_changed_event_listeners[task_id]
                    self.__start_event_listeners[task_id].close()
                    del self.__start_event_listeners[task_id]
                    self.__stop_event_listeners[task_id].close()
                    del self.__stop_event_listeners[task_id]
                    self.acquisition_state_changed_event.fire(False)
                self.__acquire_thread_trigger.set()
            if break_for_closing:
                break

    # subclasses can implement this method which is called when the data items used for acquisition change.
    # NOTE: this is called from DocumentModel!
    def data_item_states_changed(self, data_item_states):
        pass

    # subclasses should implement this method to create a continuous-style acquisition task.
    # create the view task
    # will be called from the UI thread and should return quickly.
    def _create_acquisition_view_task(self):
        raise NotImplementedError()

    # subclasses can implement this method to get notification that the view task has been changed.
    # subclasses may have a need to access the view task and this method can help keep track of the
    # current view task.
    # will be called from the UI thread and should return quickly.
    def _view_task_updated(self, view_task):
        pass

    # subclasses should implement this method to create a non-continuous-style acquisition task.
    # create the view task
    # will be called from the UI thread and should return quickly.
    def _create_acquisition_record_task(self):
        raise NotImplementedError()

    # subclasses can implement this method to get notification that the record task has been changed.
    # subclasses may have a need to access the record task and this method can help keep track of the
    # current record task.
    # will be called from the UI thread and should return quickly.
    def _record_task_updated(self, record_task):
        pass

    # data_elements is a list of data_elements; may be an empty list
    # data_elements optionally include 'channel_id', 'state', and 'sub_area'.
    # the 'channel_id' will be used to determine channel index if applicable. default will be None / channel 0.
    # the 'state' may be 'partial', 'complete', or 'marked' (requested stop at end of frame). default is 'complete'.
    # the 'sub_area' will be used to determine valid sub-area if applicable.
    # beyond these three items, the data element will be converted to xdata using convert_data_element_to_data_and_metadata.
    # thread safe
    def __data_elements_changed(self, task, data_elements, view_id, is_complete, is_stopping):
        xdatas = list()
        data_channels = list()
        for data_element in data_elements:
            assert data_element is not None
            channel_id = data_element.get("channel_id")
            # find channel_index for channel_id
            channel_index = next((data_channel.index for data_channel in self.__data_channels if data_channel.channel_id == channel_id), 0)
            data_and_metadata = ImportExportManager.convert_data_element_to_data_and_metadata(data_element)
            # data_and_metadata data may still point to low level code memory at this point.
            channel_state = data_element.get("state", "complete")
            if channel_state != "complete" and is_stopping:
                channel_state = "marked"
            sub_area = data_element.get("sub_area")
            data_channel = self.__data_channels[channel_index]
            # data_channel.update will make a copy of the data_and_metadata
            data_channel.update(data_and_metadata, channel_state, sub_area, view_id)
            data_channels.append(data_channel)
            xdatas.append(data_channel.data_and_metadata)
        # update channel buffers with processors
        for data_channel in self.__data_channels:
            src_channel_index = data_channel.src_channel_index
            if src_channel_index is not None:
                src_data_channel = self.__data_channels[src_channel_index]
                if src_data_channel.is_dirty and src_data_channel.state == "complete":
                    processed_data_and_metadata = data_channel.processor.process(src_data_channel.data_and_metadata)
                    data_channel.update(processed_data_and_metadata, "complete", None, view_id)
                data_channels.append(data_channel)
                xdatas.append(data_channel.data_and_metadata)
        # all channel buffers are clean now
        for data_channel in self.__data_channels:
            data_channel.is_dirty = False

        self.data_channel_states_updated.fire(data_channels)
        if is_complete:
            # xdatas are may still be pointing to memory in low level code here
            self.xdatas_available_event.fire(xdatas)
            # hack to allow record to know when its data is finished
            if callable(task.finished_callback_fn):
                task.finished_callback_fn(xdatas)

    def __start(self):
        for data_channel in self.__data_channels:
            data_channel.start()

    def __stop(self):
        for data_channel in self.__data_channels:
            data_channel.stop()

    # return whether task is running
    def is_task_running(self, task_id: str) -> bool:
        return task_id in self.__tasks

    # call this to start the task running
    # not thread safe
    def start_task(self, task_id: str, task: AcquisitionTask) -> None:
        assert not task in self.__tasks.values()
        assert not task_id in self.__tasks
        assert task_id in ('idle', 'view', 'record')
        self.__data_elements_changed_event_listeners[task_id] = task.data_elements_changed_event.listen(functools.partial(self.__data_elements_changed, task))
        self.__start_event_listeners[task_id] = task.start_event.listen(self.__start)
        self.__stop_event_listeners[task_id] = task.stop_event.listen(self.__stop)
        self.__tasks[task_id] = task
        # TODO: sync the thread start by waiting for an event on the task which gets set when the acquire thread starts executing the task
        self.__acquire_thread_trigger.set()
        self.acquisition_state_changed_event.fire(True)

    # call this to stop task immediately
    # not thread safe
    def abort_task(self, task_id: str) -> None:
        task = self.__tasks.get(task_id)
        assert task is not None
        task.abort()
        self.abort_event.fire()

    # call this to stop acquisition gracefully
    # not thread safe
    def stop_task(self, task_id: str) -> None:
        task = self.__tasks.get(task_id)
        assert task is not None
        task.stop()

    # return whether acquisition is running
    @property
    def is_playing(self):
        return self.is_task_running('view')

    # call this to start acquisition
    # not thread safe
    def start_playing(self, sync_timeout=None):
        if not self.is_playing:
            view_task = self._create_acquisition_view_task()
            view_task._test_acquire_hook = self._test_acquire_hook
            self._view_task_updated(view_task)
            self.start_task('view', view_task)
        if sync_timeout is not None:
            start = time.time()
            while not self.is_playing:
                time.sleep(0.01)  # 10 msec
                assert time.time() - start < float(sync_timeout)

    # call this to stop acquisition immediately
    # not thread safe
    def abort_playing(self, sync_timeout=None):
        if self.is_playing:
            self.abort_task('view')
            self._view_task_updated(None)
        if sync_timeout is not None:
            start = time.time()
            while self.is_playing:
                time.sleep(0.01)  # 10 msec
                assert time.time() - start < float(sync_timeout)

    # call this to stop acquisition gracefully
    # not thread safe
    def stop_playing(self, sync_timeout=None):
        if self.is_playing:
            self.stop_task('view')
            self._view_task_updated(None)
        if sync_timeout is not None:
            start = time.time()
            while self.is_playing:
                time.sleep(0.01)  # 10 msec
                assert time.time() - start < float(sync_timeout)

    # return whether acquisition is running
    @property
    def is_recording(self):
        return self.is_task_running('record')

    # call this to start acquisition
    # thread safe
    def start_recording(self, sync_timeout=None, finished_callback_fn=None):
        if not self.is_recording:
            record_task = self._create_acquisition_record_task()
            record_task.finished_callback_fn = finished_callback_fn
            self._record_task_updated(record_task)
            self.start_task('record', record_task)
        if sync_timeout is not None:
            start = time.time()
            while not self.is_recording:
                time.sleep(0.01)  # 10 msec
                assert time.time() - start < float(sync_timeout)

    # call this to stop acquisition immediately
    # not thread safe
    def abort_recording(self, sync_timeout=None):
        if self.is_recording:
            self.abort_task('record')
            self._record_task_updated(None)
        if sync_timeout is not None:
            start = time.time()
            while self.is_recording:
                time.sleep(0.01)  # 10 msec
                assert time.time() - start < float(sync_timeout)

    # call this to stop acquisition gracefully
    # not thread safe
    def stop_recording(self, sync_timeout=None):
        if self.is_recording:
            self.stop_task('record')
            self._record_task_updated(None)
        if sync_timeout is not None:
            start = time.time()
            while self.is_recording:
                time.sleep(0.01)  # 10 msec
                assert time.time() - start < float(sync_timeout)

    def get_next_xdatas_to_finish(self, timeout=None) -> typing.List[DataAndMetadata.DataAndMetadata]:
        new_data_event = threading.Event()
        new_xdatas = list()

        def receive_new_xdatas(xdatas):
            new_xdatas[:] = xdatas
            new_data_event.set()

        def abort():
            new_data_event.set()

        with contextlib.closing(self.xdatas_available_event.listen(receive_new_xdatas)):
            with contextlib.closing(self.abort_event.listen(abort)):
                # wait for the current frame to finish
                if not new_data_event.wait(timeout):
                    raise Exception("Could not start data_source " + str(self.hardware_source_id))

                return new_xdatas

    def get_next_xdatas_to_start(self, timeout: float=None) -> typing.List[DataAndMetadata.DataAndMetadata]:
        new_data_event = threading.Event()
        new_xdatas = list()

        def receive_new_xdatas(xdatas):
            new_xdatas[:] = xdatas
            new_data_event.set()

        def abort():
            new_data_event.set()

        with contextlib.closing(self.xdatas_available_event.listen(receive_new_xdatas)):
            with contextlib.closing(self.abort_event.listen(abort)):
                # wait for the current frame to finish
                if not new_data_event.wait(timeout):
                    raise Exception("Could not start data_source " + str(self.hardware_source_id))

                new_data_event.clear()

                if len(new_xdatas) > 0:
                    new_data_event.wait(timeout)

                return new_xdatas

    @property
    def data_channel_count(self) -> int:
        return len(self.__data_channels)

    @property
    def data_channels(self) -> typing.List[DataChannel]:
        return self.__data_channels

    def add_data_channel(self, channel_id: str=None, name: str=None):
        self.__data_channels.append(DataChannel(self, len(self.__data_channels), channel_id, name))

    def add_channel_processor(self, channel_index: int, processor):
        self.__data_channels.append(DataChannel(self, len(self.__data_channels), processor.processor_id, None, channel_index, processor))

    def clean_data_item(self, data_item: DataItem.DataItem, data_channel: DataChannel) -> None:
        """Clean the data item associated with this data channel.

        Invoked when the hardware source is registered with the document model. Useful for
        removing old graphics and otherwise cleaning up the data item at startup.
        """
        pass

    def get_property(self, name):
        return getattr(self, name)

    def set_property(self, name, value):
        setattr(self, name, value)

    def get_api(self, version):
        actual_version = "1.0.0"
        if Utility.compare_versions(version, actual_version) > 0:
            raise NotImplementedError("Hardware Source API requested version %s is greater than %s." % (version, actual_version))

        class HardwareSourceFacade:
            def __init__(self):
                pass

        return HardwareSourceFacade()


class SumProcessor(Observable.Observable, Persistence.PersistentObject):
    def __init__(self, bounds, processor_id=None, label=None):
        super().__init__()
        self.__bounds = bounds
        self.__processor_id = processor_id or "summed"
        self.__label = label or _("Summed")
        self.__crop_graphic = None
        self.__crop_listener = None
        self.__remove_listener = None
        self.__data_item_changed_event_listener = None

    @property
    def label(self):
        return self.__label

    @property
    def processor_id(self):
        return self.__processor_id

    @property
    def bounds(self):
        return self.__bounds

    @bounds.setter
    def bounds(self, value):
        if self.__bounds != value:
            self.__bounds = value
            self.notify_property_changed("bounds")
            if self.__crop_graphic:
                self.__crop_graphic.bounds = value

    def process(self, data_and_metadata: Core.DataAndMetadata) -> Core.DataAndMetadata:
        if data_and_metadata.datum_dimension_count > 1 and data_and_metadata.data_shape[0] > 1:
            summed = Core.function_sum(Core.function_crop(data_and_metadata, self.__bounds), 0)
            summed._set_metadata(data_and_metadata.metadata)
            return summed
        elif len(data_and_metadata.data_shape) > 1:
            summed = Core.function_sum(data_and_metadata, 0)
            summed._set_metadata(data_and_metadata.metadata)
            return summed
        else:
            return copy.deepcopy(data_and_metadata)

    def connect(self, data_item_reference):
        """Connect to the data item reference, creating a crop graphic if necessary.

        If the data item reference does not yet have an associated data item, add a
        listener and wait for the data item to be set, then connect.
        """
        data_item = data_item_reference.data_item
        if data_item:
            self.__connect_data_item(data_item)
        else:
            def data_item_changed():
                self.__data_item_changed_event_listener.close()
                self.connect(data_item_reference)  # ugh. recursive mess.
            self.__data_item_changed_event_listener = data_item_reference.data_item_changed_event.listen(data_item_changed)

    def __connect_data_item(self, data_item):
        assert threading.current_thread() == threading.main_thread()
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        crop_graphic = None
        for graphic in display_specifier.display.graphics:
            if graphic.graphic_id == self.__processor_id:
                crop_graphic = graphic
                break
        def close_all():
            self.__crop_graphic = None
            if self.__crop_listener:
                self.__crop_listener.close()
                self.__crop_listener = None
            if self.__remove_listener:
                self.__remove_listener.close()
                self.__remove_listener = None
        if not crop_graphic:
            close_all()
            crop_graphic = Graphics.RectangleGraphic()
            crop_graphic.bounds = self.bounds
            crop_graphic.is_bounds_constrained = True
            crop_graphic.graphic_id = self.__processor_id
            crop_graphic.label = _("Crop")
            display_specifier.display.add_graphic(crop_graphic)
        if not self.__crop_listener:
            def property_changed(k):
                if k == "bounds":
                    self.bounds = crop_graphic.bounds
            def graphic_removed(k, v, i):
                if v == crop_graphic:
                    close_all()
            self.__crop_listener = crop_graphic.property_changed_event.listen(property_changed)
            self.__remove_listener = display_specifier.display.item_removed_event.listen(graphic_removed)
            self.__crop_graphic = crop_graphic


@contextlib.contextmanager
def get_data_generator_by_id(hardware_source_id, sync=True):
    """
        Return a generator for data.

        :param bool sync: whether to wait for current frame to finish then collect next frame

        NOTE: a new ndarray is created for each call.
    """
    hardware_source = HardwareSourceManager().get_hardware_source_for_hardware_source_id(hardware_source_id)
    def get_last_data():
        return hardware_source.get_next_xdatas_to_finish()[0].data.copy()
    yield get_last_data


def convert_data_element_to_data_and_metadata(data_element) -> DataAndMetadata.DataAndMetadata:
    # TODO: remove this after customers have all stopped using it.
    return ImportExportManager.convert_data_element_to_data_and_metadata(data_element)


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
            config = configparser.ConfigParser()
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


class DataChannelBuffer:
    """A fixed size buffer for a list of hardware source data channels.

    The buffer takes care of waiting until all channels in the list have produced
    a full frame of data, then stores it if it matches criteria (for instance every
    n seconds). Clients can retrieve earliest or latest data.

    Possible uses: record every frame, record every nth frame, record frame periodically,
      frame averaging, spectrum imaging.
    """

    class State(enum.Enum):
        idle = 0
        started = 1
        paused = 2

    def __init__(self, data_channels: typing.List[DataChannel], buffer_size=16):
        self.__state_lock = threading.RLock()
        self.__state = DataChannelBuffer.State.idle
        self.__buffer_size = buffer_size
        self.__buffer_lock = threading.RLock()
        self.__buffer = list()
        self.__done_events = list()
        self.__active_channel_ids = set()
        self.__latest = dict()
        self.__data_channel_updated_listeners = list()
        self.__data_channel_start_listeners = list()
        self.__data_channel_stop_listeners = list()
        self.__data_channels = data_channels
        for data_channel in self.__data_channels:
            data_channel_updated_listener = data_channel.data_channel_updated_event.listen(functools.partial(self.__data_channel_updated, data_channel))
            self.__data_channel_updated_listeners.append(data_channel_updated_listener)
            data_channel_start_listener = data_channel.data_channel_start_event.listen(functools.partial(self.__data_channel_start, data_channel))
            self.__data_channel_start_listeners.append(data_channel_start_listener)
            data_channel_stop_listener = data_channel.data_channel_stop_event.listen(functools.partial(self.__data_channel_stop, data_channel))
            self.__data_channel_stop_listeners.append(data_channel_stop_listener)
            if data_channel.is_started:
                self.__active_channel_ids.add(data_channel.channel_id)

    def close(self) -> None:
        for listener in self.__data_channel_updated_listeners:
            listener.close()
        for listener in self.__data_channel_start_listeners:
            listener.close()
        for listener in self.__data_channel_stop_listeners:
            listener.close()
        self.__data_channel_updated_listeners = None
        self.__data_channel_start_listeners = None
        self.__data_channel_stop_listeners = None

    def __data_channel_updated(self, data_channel: DataChannel, data_and_metadata: DataAndMetadata.DataAndMetadata) -> None:
        if self.__state == DataChannelBuffer.State.started:
            if data_channel.state == "complete":
                with self.__buffer_lock:
                    self.__latest[data_channel.channel_id] = data_and_metadata
                    if set(self.__latest.keys()).issuperset(self.__active_channel_ids):
                        data_and_metadata_list = list()
                        for data_channel in self.__data_channels:
                            if data_channel.channel_id in self.__latest:
                                data_and_metadata_list.append(copy.deepcopy(self.__latest[data_channel.channel_id]))
                        self.__buffer.append(data_and_metadata_list)
                        self.__latest = dict()
                        if len(self.__buffer) > self.__buffer_size:
                            self.__buffer.pop(0)
                        for done_event in self.__done_events:
                            done_event.set()
                        self.__done_events = list()

    def __data_channel_start(self, data_channel: DataChannel) -> None:
        self.__active_channel_ids.add(data_channel.channel_id)

    def __data_channel_stop(self, data_channel: DataChannel) -> None:
        self.__active_channel_ids.remove(data_channel.channel_id)

    def grab_latest(self, timeout: float=None) -> typing.List[DataAndMetadata.DataAndMetadata]:
        """Grab the most recent data from the buffer, blocking until one is available. Clear earlier data."""
        timeout = timeout if timeout is not None else 10.0
        with self.__buffer_lock:
            if len(self.__buffer) == 0:
                done_event = threading.Event()
                self.__done_events.append(done_event)
                self.__buffer_lock.release()
                done = done_event.wait(timeout)
                self.__buffer_lock.acquire()
                if not done:
                    raise Exception("Could not grab latest.")
            result = self.__buffer[-1]
            self.__buffer = list()
            return result

    def grab_earliest(self, timeout: float=None) -> typing.List[DataAndMetadata.DataAndMetadata]:
        """Grab the earliest data from the buffer, blocking until one is available."""
        timeout = timeout if timeout is not None else 10.0
        with self.__buffer_lock:
            if len(self.__buffer) == 0:
                done_event = threading.Event()
                self.__done_events.append(done_event)
                self.__buffer_lock.release()
                done = done_event.wait(timeout)
                self.__buffer_lock.acquire()
                if not done:
                    raise Exception("Could not grab latest.")
            return self.__buffer.pop(0)

    def grab_next(self, timeout: float=None) -> typing.List[DataAndMetadata.DataAndMetadata]:
        """Grab the next data to finish from the buffer, blocking until one is available."""
        with self.__buffer_lock:
            self.__buffer = list()
        return self.grab_latest(timeout)

    def grab_following(self, timeout: float=None) -> typing.List[DataAndMetadata.DataAndMetadata]:
        """Grab the next data to start from the buffer, blocking until one is available."""
        self.grab_next(timeout)
        return self.grab_next(timeout)

    def start(self) -> None:
        """Start recording.

        Thread safe and UI safe."""
        with self.__state_lock:
            self.__state = DataChannelBuffer.State.started

    def pause(self) -> None:
        """Pause recording.

        Thread safe and UI safe."""
        with self.__state_lock:
            if self.__state == DataChannelBuffer.State.started:
                self.__state = DataChannelBuffer.State.paused

    def resume(self) -> None:
        """Resume recording after pause.

        Thread safe and UI safe."""
        with self.__state_lock:
            if self.__state == DataChannelBuffer.State.paused:
                self.__state = DataChannelBuffer.State.started

    def stop(self) -> None:
        """Stop or abort recording.

        Thread safe and UI safe."""
        with self.__state_lock:
            self.__state = DataChannelBuffer.State.idle


def matches_hardware_source(hardware_source_id, channel_id, document_model, data_item):
    if not document_model.get_data_item_computation(data_item):
        hardware_source_metadata = data_item.metadata.get("hardware_source", dict())
        data_item_hardware_source_id = hardware_source_metadata.get("hardware_source_id")
        data_item_channel_id = hardware_source_metadata.get("channel_id")
        return data_item.category == "temporary" and hardware_source_id == data_item_hardware_source_id and channel_id == data_item_channel_id
    return False
