# standard libraries
import copy
import datetime
import gettext
import threading
import time
import typing
import uuid
import weakref

# local libraries
from nion.data import DataAndMetadata
from nion.swift.model import Cache
from nion.swift.model import DataItem
from nion.swift.model import Display
from nion.swift.model import Graphics
from nion.swift.model import Utility
from nion.utils import Event
from nion.utils import Observable
from nion.utils import Persistence


_ = gettext.gettext


class DisplayItem(Observable.Observable, Persistence.PersistentObject):
    def __init__(self, item_uuid=None):
        super().__init__()
        self.uuid = item_uuid if item_uuid else self.uuid
        self.__container_weak_ref = None
        self.define_property("created", datetime.datetime.utcnow(), converter=DataItem.DatetimeToStringConverter(), changed=self.__property_changed)
        # windows utcnow has a resolution of 1ms, this sleep can guarantee unique times for all created times during a particular test.
        # this is not my favorite solution since it limits library item creation to 1000/s but until I find a better solution, this is my compromise.
        time.sleep(0.001)
        self.define_property("title", hidden=True, changed=self.__property_changed)
        self.define_property("caption", hidden=True, changed=self.__property_changed)
        self.define_property("description", hidden=True, changed=self.__property_changed)
        self.define_property("session_id", hidden=True, changed=self.__property_changed)
        self.define_property("data_item_references", list(), changed=self.__property_changed)
        self.define_item("display", Display.display_factory, self.__display_changed)
        self.__data_items = list()
        self.__data_item_will_change_listeners = list()
        self.__data_item_did_change_listeners = list()
        self.__data_item_item_changed_listeners = list()
        self.__data_item_data_item_changed_listeners = list()
        self.__data_item_data_changed_listeners = list()
        self.__data_item_description_changed_listeners = list()
        self.__suspendable_storage_cache = None
        self.__display_item_change_count = 0
        self.__display_item_change_count_lock = threading.RLock()
        self.__display_ref_count = 0
        self.item_changed_event = Event.Event()
        self.about_to_be_removed_event = Event.Event()
        self._about_to_be_removed = False
        self._closed = False
        self.set_item("display", Display.Display())
        self.__display_about_to_be_removed_listener = self.display.about_to_be_removed_event.listen(self.about_to_be_removed_event.fire)

    def close(self):
        self.__display_about_to_be_removed_listener.close()
        self.__display_about_to_be_removed_listener = None
        self.set_item("display", None)
        for data_item_will_change_listener in self.__data_item_will_change_listeners:
            data_item_will_change_listener.close()
        self.__data_item_will_change_listeners = list()
        for data_item_did_change_listener in self.__data_item_did_change_listeners:
            data_item_did_change_listener.close()
        self.__data_item_did_change_listeners = list()
        for data_item_item_changed_listener in self.__data_item_item_changed_listeners:
            data_item_item_changed_listener.close()
        self.__data_item_item_changed_listeners = list()
        for data_item_data_item_changed_listener in self.__data_item_data_item_changed_listeners:
            data_item_data_item_changed_listener.close()
        self.__data_item_data_item_changed_listeners = list()
        for data_item_data_item_content_changed_listener in self.__data_item_data_changed_listeners:
            data_item_data_item_content_changed_listener.close()
        self.__data_item_data_changed_listeners = list()
        for data_item_description_changed_listener in self.__data_item_description_changed_listeners:
            data_item_description_changed_listener.close()
        self.__data_item_description_changed_listeners = list()
        self.__data_items = list()
        assert self._about_to_be_removed
        assert not self._closed
        self._closed = True
        self.__container_weak_ref = None

    def __copy__(self):
        assert False

    def __deepcopy__(self, memo):
        display_item_copy = self.__class__()
        # metadata
        display_item_copy._set_persistent_property_value("title", self._get_persistent_property_value("title"))
        display_item_copy._set_persistent_property_value("caption", self._get_persistent_property_value("caption"))
        display_item_copy._set_persistent_property_value("description", self._get_persistent_property_value("description"))
        display_item_copy._set_persistent_property_value("session_id", self._get_persistent_property_value("session_id"))
        display_item_copy.created = self.created
        # display
        display_item_copy.display = copy.deepcopy(self.display)
        display_item_copy.data_item_references = copy.deepcopy(self.data_item_references)
        memo[id(self)] = display_item_copy
        return display_item_copy

    @property
    def container(self):
        return self.__container_weak_ref()

    def about_to_close(self):
        self.__disconnect_data_sources()

    def about_to_be_inserted(self, container):
        assert self.__container_weak_ref is None
        self.__container_weak_ref = weakref.ref(container)

    def about_to_be_removed(self):
        # called before close and before item is removed from its container
        self.about_to_be_removed_event.fire()
        assert not self._about_to_be_removed
        self._about_to_be_removed = True

    def insert_model_item(self, container, name, before_index, item):
        """Insert a model item. Let this item's container do it if possible; otherwise do it directly.

        Passing responsibility to this item's container allows the library to easily track dependencies.
        However, if this item isn't yet in the library hierarchy, then do the operation directly.
        """
        if self.__container_weak_ref:
            self.container.insert_model_item(container, name, before_index, item)
        else:
            container.insert_item(name, before_index, item)

    def remove_model_item(self, container, name, item, *, safe: bool=False) -> typing.Optional[typing.Sequence]:
        """Remove a model item. Let this item's container do it if possible; otherwise do it directly.

        Passing responsibility to this item's container allows the library to easily track dependencies.
        However, if this item isn't yet in the library hierarchy, then do the operation directly.
        """
        if self.__container_weak_ref:
            return self.container.remove_model_item(container, name, item, safe=safe)
        else:
            container.remove_item(name, item)
            return None

    # call this when the listeners need to be updated (via data_item_content_changed).
    # Calling this method will send the data_item_content_changed method to each listener by using the method
    # data_item_changes.
    def _notify_display_item_content_changed(self):
        with self.display_item_changes():
            pass

    # override from storage to watch for changes to this library item. notify observers.
    def notify_property_changed(self, key):
        super().notify_property_changed(key)
        self._notify_display_item_content_changed()

    def __property_changed(self, name, value):
        self.notify_property_changed(name)

    def clone(self) -> "DisplayItem":
        display_item = self.__class__()
        display_item.uuid = self.uuid
        display_item.display = self.display.clone()
        return display_item

    def snapshot(self):
        """Return a new library item which is a copy of this one with any dynamic behavior made static."""
        display_item = self.__class__()
        # metadata
        display_item._set_persistent_property_value("title", self._get_persistent_property_value("title"))
        display_item._set_persistent_property_value("caption", self._get_persistent_property_value("caption"))
        display_item._set_persistent_property_value("description", self._get_persistent_property_value("description"))
        display_item._set_persistent_property_value("session_id", self._get_persistent_property_value("session_id"))
        display_item.created = self.created
        display_item.display = copy.deepcopy(self.display)
        return display_item

    def set_storage_cache(self, storage_cache):
        self.__suspendable_storage_cache = Cache.SuspendableCache(storage_cache)
        self.display.set_storage_cache(self._suspendable_storage_cache)

    @property
    def _suspendable_storage_cache(self):
        return self.__suspendable_storage_cache

    def read_from_dict(self, properties):
        super().read_from_dict(properties)
        if self.created is None:  # invalid timestamp -- set property to now but don't trigger change
            timestamp = datetime.datetime.now()
            self._get_persistent_property("created").value = timestamp

    @property
    def properties(self):
        """ Used for debugging. """
        if self.persistent_object_context:
            return self.persistent_object_context.get_properties(self)
        return dict()

    def __display_changed(self, name, old_display, new_display):
        if new_display != old_display:
            if old_display:
                if self.__display_ref_count > 0:
                    old_display._relinquish_master()
                old_display.about_to_be_removed()
                old_display.close()
            if new_display:
                new_display.about_to_be_inserted(self)
                new_display.title = self.displayed_title
                if self.__display_ref_count > 0:
                    new_display._become_master()

    def display_item_changes(self):
        # return a context manager to batch up a set of changes so that listeners
        # are only notified after the last change is complete.
        display_item = self
        class ContextManager:
            def __enter__(self):
                display_item._begin_display_item_changes()
                return self
            def __exit__(self, type, value, traceback):
                display_item._end_display_item_changes()
        return ContextManager()

    def _begin_display_item_changes(self):
        with self.__display_item_change_count_lock:
            self.__display_item_change_count += 1

    def _end_display_item_changes(self):
        with self.__display_item_change_count_lock:
            self.__display_item_change_count -= 1
            change_count = self.__display_item_change_count
        # if the change count is now zero, it means that we're ready to notify listeners.
        if change_count == 0:
            self.display._item_changed()
            self._update_displays()  # this ensures that the display will validate

    def increment_display_ref_count(self, amount: int=1):
        """Increment display reference count to indicate this library item is currently displayed."""
        display_ref_count = self.__display_ref_count
        self.__display_ref_count += amount
        if display_ref_count == 0:
            display = self.display
            if display:
                display._become_master()
        for data_item in self.data_items:
            for _ in range(amount):
                data_item.increment_data_ref_count()

    def decrement_display_ref_count(self, amount: int=1):
        """Decrement display reference count to indicate this library item is no longer displayed."""
        assert not self._closed
        self.__display_ref_count -= amount
        if self.__display_ref_count == 0:
            display = self.display
            if display:
                display._relinquish_master()
        for data_item in self.data_items:
            for _ in range(amount):
                data_item.decrement_data_ref_count()

    @property
    def _display_ref_count(self):
        return self.__display_ref_count

    def __data_item_will_change(self):
        self._begin_display_item_changes()

    def __data_item_did_change(self):
        self._end_display_item_changes()

    def _item_changed(self):
        # this event is only triggered when the data item changed live state; everything else goes through
        # the data changed messages.
        self.display._item_changed()

    def _update_displays(self):
        xdata_list = [data_item.xdata if data_item else None for data_item in self.data_items]
        self.display.update_xdata_list(xdata_list)
        self.display.title = self.displayed_title

    def _description_changed(self):
        self.display.title = self.displayed_title

    def __get_used_value(self, key: str, default_value):
        if self._get_persistent_property_value(key) is not None:
            return self._get_persistent_property_value(key)
        if self.data_item and getattr(self.data_item, key, None):
            return getattr(self.data_item, key)
        return default_value

    def __set_cascaded_value(self, key: str, value) -> None:
        if self.data_item:
            self._set_persistent_property_value(key, None)
            setattr(self.data_item, key, value)
        else:
            self._set_persistent_property_value(key, value)
            self._description_changed()

    @property
    def text_for_filter(self) -> str:
        return " ".join([self.displayed_title, self.caption, self.description])

    @property
    def displayed_title(self):
        if self.data_item and getattr(self.data_item, "displayed_title", None):
            return self.data_item.displayed_title
        else:
            return self.title

    @property
    def title(self) -> str:
        return self.__get_used_value("title", DataItem.UNTITLED_STR)

    @title.setter
    def title(self, value: str) -> None:
        self.__set_cascaded_value("title", str(value) if value is not None else str())

    @property
    def caption(self) -> str:
        return self.__get_used_value("caption", str())

    @caption.setter
    def caption(self, value: str) -> None:
        self.__set_cascaded_value("caption", str(value) if value is not None else str())

    @property
    def description(self) -> str:
        return self.__get_used_value("description", str())

    @description.setter
    def description(self, value: str) -> None:
        self.__set_cascaded_value("description", str(value) if value is not None else str())

    @property
    def session_id(self) -> str:
        return self.__get_used_value("session_id", str())

    @session_id.setter
    def session_id(self, value: str) -> None:
        self.__set_cascaded_value("session_id", str(value) if value is not None else str())

    def connect_data_items(self, lookup_data_item):
        self.__data_items = [lookup_data_item(uuid.UUID(data_item_reference)) for data_item_reference in self.data_item_references]
        for data_item in self.__data_items:
            self.__data_item_will_change_listeners.append(data_item.will_change_event.listen(self.__data_item_will_change) if data_item else None)
            self.__data_item_did_change_listeners.append(data_item.did_change_event.listen(self.__data_item_did_change) if data_item else None)
            self.__data_item_item_changed_listeners.append(data_item.item_changed_event.listen(self._item_changed) if data_item else None)
            self.__data_item_data_item_changed_listeners.append(data_item.data_item_changed_event.listen(self._item_changed) if data_item else None)
            self.__data_item_data_changed_listeners.append(data_item.data_changed_event.listen(self._item_changed) if data_item else None)
            self.__data_item_description_changed_listeners.append(data_item.description_changed_event.listen(self._description_changed) if data_item else None)
        self._update_displays()  # this ensures that the display will validate

    def append_data_item(self, data_item):
        self.insert_data_item(len(self.data_items), data_item)

    def insert_data_item(self, before_index, data_item):
        data_item_references = self.data_item_references
        data_item_references.insert(before_index, str(data_item.uuid))
        self.__data_items.insert(before_index, data_item)
        self.__data_item_will_change_listeners.insert(before_index, data_item.will_change_event.listen(self.__data_item_will_change))
        self.__data_item_did_change_listeners.insert(before_index, data_item.did_change_event.listen(self.__data_item_did_change))
        self.__data_item_item_changed_listeners.insert(before_index, data_item.item_changed_event.listen(self._item_changed))
        self.__data_item_data_item_changed_listeners.insert(before_index, data_item.data_item_changed_event.listen(self._item_changed))
        self.__data_item_data_changed_listeners.insert(before_index, data_item.data_changed_event.listen(self._item_changed))
        self.__data_item_description_changed_listeners.insert(before_index, data_item.description_changed_event.listen(self._description_changed))
        self.data_item_references = data_item_references

    def remove_data_item(self, data_item):
        data_item_references = self.data_item_references
        data_item_references.remove(str(data_item.uuid))
        index = self.__data_items.index(data_item)
        self.__data_item_will_change_listeners[index].close()
        del self.__data_item_will_change_listeners[index]
        self.__data_item_did_change_listeners[index].close()
        del self.__data_item_did_change_listeners[index]
        self.__data_item_item_changed_listeners[index].close()
        del self.__data_item_item_changed_listeners[index]
        self.__data_item_data_item_changed_listeners[index].close()
        del self.__data_item_data_item_changed_listeners[index]
        self.__data_item_data_changed_listeners[index].close()
        del self.__data_item_data_changed_listeners[index]
        self.__data_item_description_changed_listeners[index].close()
        del self.__data_item_description_changed_listeners[index]
        del self.__data_items[index]
        self.data_item_references = data_item_references

    @property
    def data_items(self) -> typing.Sequence[DataItem.DataItem]:
        return self.__data_items

    @property
    def data_item(self) -> typing.Optional[DataItem.DataItem]:
        return self.__data_items[0] if len(self.__data_items) == 1 else None

    @property
    def graphics(self) -> typing.Sequence[Graphics.Graphic]:
        return self.display.graphics

    def insert_graphic(self, before_index: int, graphic: Graphics.Graphic) -> None:
        self.display.insert_graphic(before_index, graphic)

    def add_graphic(self, graphic: Graphics.Graphic) -> None:
        self.display.add_graphic(graphic)

    def remove_graphic(self, graphic: Graphics.Graphic, *, safe: bool=False) -> typing.Optional[typing.Sequence]:
        return self.display.remove_graphic(graphic, safe=safe)

    @property
    def graphic_selection(self):
        return self.display.graphic_selection

    @property
    def size_and_data_format_as_string(self) -> str:
        return self.data_item.size_and_data_format_as_string

    @property
    def date_for_sorting(self):
        data_item_dates = [data_item.date_for_sorting for data_item in self.data_items]
        if len(data_item_dates):
            return max(data_item_dates)
        return self.created

    @property
    def date_for_sorting_local_as_string(self) -> str:
        return self.data_item.date_for_sorting_local_as_string

    @property
    def created_local(self) -> datetime.datetime:
        created_utc = self.created
        tz_minutes = Utility.local_utcoffset_minutes(created_utc)
        return created_utc + datetime.timedelta(minutes=tz_minutes)

    @property
    def is_live(self) -> bool:
        return any(data_item.is_live for data_item in self.data_items)

    @property
    def category(self) -> str:
        return "temporary" if any(data_item.category == "temporary" for data_item in self.data_items) else "persistent"

    @property
    def status_str(self) -> str:
        if self.data_item.is_live:
            live_metadata = self.data_item.metadata.get("hardware_source", dict())
            frame_index_str = str(live_metadata.get("frame_index", str()))
            partial_str = "{0:d}/{1:d}".format(live_metadata.get("valid_rows"), self.data_item.dimensional_shape[0]) if "valid_rows" in live_metadata else str()
            return "{0:s} {1:s} {2:s}".format(_("Live"), frame_index_str, partial_str)
        return str()

    @property
    def display_type(self) -> str:
        return self.display.display_type

    @display_type.setter
    def display_type(self, value: str) -> None:
        self.display.display_type = value

    @property
    def legend_labels(self) -> typing.Sequence[str]:
        return self.display.legend_labels

    @legend_labels.setter
    def legend_labels(self, value: typing.Sequence[str]) -> None:
        self.display.legend_labels = value

    def view_to_intervals(self, data_and_metadata: DataAndMetadata.DataAndMetadata, intervals: typing.List[typing.Tuple[float, float]]) -> None:
        self.display.view_to_intervals(data_and_metadata, intervals)
