"""
    Contains classes related to regions of data items.
"""

# standard libraries
import copy
import logging
import uuid
import weakref

# third party libraries
# None

# local libraries
from nion.ui import Observable


class Region(Observable.Observable, Observable.Broadcaster, Observable.ActiveSerializable):
    # Regions are associated with exactly one data item.

    def __init__(self, type):
        super(Region, self).__init__()
        self.__weak_data_item = None
        region_uuid = uuid.uuid4()
        self.define_type(type)
        class UuidToStringConverter(object):
            def convert(self, value):
                return str(value) if value is not None else None
            def convert_back(self, value):
                return uuid.UUID(value) if value is not None else None
        self.define_property(Observable.Property("uuid", region_uuid, read_only=True, converter=UuidToStringConverter()))
        # TODO: add unit type to region (relative, absolute, calibrated)

    # subclasses should override __deepcopy__ and deepcopy_from as necessary
    def __deepcopy__(self, memo):
        region = self.__class__()
        region.deepcopy_from(self, memo)
        memo[id(self)] = region
        return region

    def __get_data_item(self):
        return self.__weak_data_item() if self.__weak_data_item else None
    data_item = property(__get_data_item)

    # called from data item when added/removed.
    def _set_data_item(self, data_item):
        self.__weak_data_item = weakref.ref(data_item) if data_item else None

    def _property_changed(self, name, value):
        self.notify_set_property(name, value)


class PointRegion(Region):

    def __init__(self):
        super(PointRegion, self).__init__("point-region")
        self.define_property(Observable.Property("position", (0.5, 0.5), changed=self._property_changed))


class LineRegion(Region):

    def __init__(self):
        super(LineRegion, self).__init__("line-region")
        self.define_property(Observable.Property("start", (0.0, 0.0), changed=self._property_changed))
        self.define_property(Observable.Property("end", (1.0, 1.0), changed=self._property_changed))
        self.define_property(Observable.Property("width", 1.0, changed=self._property_changed))


class RectRegion(Region):

    def __init__(self):
        super(RectRegion, self).__init__("rect-region")
        self.define_property(Observable.Property("center", (0.0, 0.0), changed=self._property_changed))
        self.define_property(Observable.Property("size", (1.0, 1.0), changed=self._property_changed))
        # TODO: add rotation property to rect region


def region_factory(vault):
    build_map = {
        "point-region": PointRegion,
        "line-region": LineRegion,
        "rect-region": RectRegion,
    }
    type = vault.get_value("type")
    return build_map[type]() if type in build_map else None
