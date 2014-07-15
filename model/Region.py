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
from nion.swift.model import Graphics
from nion.swift.model import Operation
from nion.ui import Binding
from nion.ui import Observable


class Region(Observable.Observable, Observable.Broadcaster, Observable.ManagedObject):
    # Regions are associated with exactly one data item.

    def __init__(self, type):
        super(Region, self).__init__()
        self.__weak_data_item = None
        self.define_type(type)
        # TODO: add unit type to region (relative, absolute, calibrated)

    # subclasses should override __deepcopy__ and deepcopy_from as necessary
    def __deepcopy__(self, memo):
        region = self.__class__()
        region.deepcopy_from(self, memo)
        memo[id(self)] = region
        return region

    def about_to_be_removed(self):
        pass

    def __get_data_item(self):
        return self.__weak_data_item() if self.__weak_data_item else None
    data_item = property(__get_data_item)

    # called from data item when added/removed.
    def _set_data_item(self, data_item):
        self.__weak_data_item = weakref.ref(data_item) if data_item else None

    def _property_changed(self, name, value):
        self.notify_set_property(name, value)

    def __get_graphic(self):
        return None
    graphic = property(__get_graphic)


class PointRegion(Region):

    def __init__(self):
        super(PointRegion, self).__init__("point-region")
        self.define_property("position", (0.5, 0.5), changed=self._property_changed)
        self.__graphic = Graphics.PointGraphic()
        self.__graphic.color = "#FF0"
        self.__graphic.add_listener(self)
        self.__position_binding = RegionPropertyToGraphicBinding(self, "position", self.__graphic, "position")

    def __get_graphic(self):
        return self.__graphic
    graphic = property(__get_graphic)

    def remove_region_graphic(self, region_graphic):
        # message from the graphic when its being removed
        self.notify_listeners("remove_region_because_graphic_removed", self)


class LineRegion(Region):

    def __init__(self):
        super(LineRegion, self).__init__("line-region")
        self.define_property("start", (0.0, 0.0), changed=self._property_changed)
        self.define_property("end", (1.0, 1.0), changed=self._property_changed)
        self.define_property("width", 1.0, changed=self._property_changed)
        self.__graphic = Operation.LineProfileGraphic()
        self.__graphic.color = "#FF0"
        self.__graphic.add_listener(self)
        self.__start_binding = RegionPropertyToGraphicBinding(self, "start", self.__graphic, "start")
        self.__end_binding = RegionPropertyToGraphicBinding(self, "end", self.__graphic, "end")
        self.__width_binding = RegionPropertyToGraphicBinding(self, "width", self.__graphic, "width")

    def __get_graphic(self):
        return self.__graphic
    graphic = property(__get_graphic)

    def remove_region_graphic(self, region_graphic):
        # message from the graphic when its being removed
        self.notify_listeners("remove_region_because_graphic_removed", self)


class RectRegion(Region):

    def __init__(self):
        super(RectRegion, self).__init__("rectangle-region")
        self.define_property("center", (0.0, 0.0), changed=self._property_changed)
        self.define_property("size", (1.0, 1.0), changed=self._property_changed)
        # TODO: add rotation property to rect region
        self.__graphic = Graphics.RectangleGraphic()
        self.__graphic.color = "#FF0"
        self.__graphic.add_listener(self)
        self.__center_binding = RegionPropertyToGraphicBinding(self, "center", self.__graphic, "center")
        self.__size_binding = RegionPropertyToGraphicBinding(self, "size", self.__graphic, "size")

    def __get_graphic(self):
        return self.__graphic
    graphic = property(__get_graphic)

    def remove_region_graphic(self, region_graphic):
        # message from the graphic when its being removed
        self.notify_listeners("remove_region_because_graphic_removed", self)

    def __get_bounds(self):
        center = self.center
        size = self.size
        return (center[0] - size[0] * 0.5, center[1] - size[1] * 0.5), size
    def __set_bounds(self, bounds):
        self.center = bounds[0][0] + bounds[1][0] * 0.5, bounds[0][1] + bounds[1][1] * 0.5
        self.size = bounds[1]
    bounds = property(__get_bounds, __set_bounds)

    def _property_changed(self, name, value):
        # override to implement dependency. argh.
        self.notify_set_property(name, value)
        self.notify_set_property("bounds", self.bounds)


class IntervalRegion(Region):

    def __init__(self):
        super(IntervalRegion, self).__init__("interval-region")
        self.define_property("start", 0.0, changed=self._property_changed)
        self.define_property("end", 1.0, changed=self._property_changed)
        self.__graphic = Graphics.IntervalGraphic()
        self.__graphic.color = "#FF0"
        self.__graphic.add_listener(self)
        self.__start_binding = RegionPropertyToGraphicBinding(self, "start", self.__graphic, "start")
        self.__end_binding = RegionPropertyToGraphicBinding(self, "end", self.__graphic, "end")

    def __get_graphic(self):
        return self.__graphic
    graphic = property(__get_graphic)

    def remove_region_graphic(self, region_graphic):
        # message from the graphic when its being removed
        self.notify_listeners("remove_region_because_graphic_removed", self)


class RegionPropertyToGraphicBinding(Binding.PropertyBinding):

    """
        Binds a property of an operation item to a property of a graphic item.
    """

    def __init__(self, region, region_property_name, graphic, graphic_property_name):
        super(RegionPropertyToGraphicBinding, self).__init__(region, region_property_name)
        self.__graphic = graphic
        self.__graphic.add_observer(self)
        self.__graphic_property_name = graphic_property_name
        self.__region_property_name = region_property_name
        self.target_setter = lambda value: setattr(self.__graphic, graphic_property_name, value)

    def close(self):
        self.__graphic.remove_observer(self)
        self.__graphic = None
        super(RegionPropertyToGraphicBinding, self).close()

    # watch for property changes on the graphic.
    def property_changed(self, sender, property_name, property_value):
        super(RegionPropertyToGraphicBinding, self).property_changed(sender, property_name, property_value)
        if sender == self.__graphic and property_name == self.__graphic_property_name:
            old_property_value = getattr(self.source, self.__region_property_name)
            # to prevent message loops, check to make sure it changed
            if property_value != old_property_value:
                self.update_source(property_value)


def region_factory(vault, parent):
    build_map = {
        "point-region": PointRegion,
        "line-region": LineRegion,
        "rectangle-region": RectRegion,
        "interval-region": IntervalRegion,
    }
    type = vault.get_value(parent, "type")
    return build_map[type]() if type in build_map else None
