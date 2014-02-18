# standard libraries
import copy
import gettext
import logging
import math
import sys
import threading
import uuid
import weakref

# third party libraries
import numpy
import scipy
import scipy.fftpack
import scipy.ndimage

# local libraries
from nion.imaging import Image
from nion.imaging import Operation
from nion.swift import Decorators
from nion.swift.Decorators import timeit
from nion.swift import DataItem
from nion.swift import Graphics
from nion.swift import Storage
from nion.ui import UserInterfaceUtility

_ = gettext.gettext


class OperationItem(Storage.StorageBase):
    """
        OperationItem represents an operation on numpy data array.
        Pass in a description during construction. The description
        should describe what parameters are editable and how they
        are connected to the operation.
    """
    def __init__(self, operation_id):
        Storage.StorageBase.__init__(self)

        self.storage_type = "operation"

        # an operation gets one chance to find its behavior. if the behavior doesn't exist
        # then it will simply provide null data according to the saved parameters. if there
        # are no saved parameters, defaults are used.
        self.operation = Operation.OperationManager().build_operation(operation_id)

        self.name = self.operation.name if self.operation else _("Unavailable Operation")
        self.__enabled = True

        # operation_id is immutable
        self.operation_id = operation_id

        # manage properties
        self.description = self.operation.description if self.operation else []
        self.properties = [description_entry["property"] for description_entry in self.description]
        self.values = {}

        # manage graphics
        self.graphic = None

        self.storage_properties += ["operation_id", "enabled", "values"]  # "dtype", "shape"
        self.storage_items += ["graphic"]

    # called when remove_ref causes ref_count to go to 0
    def about_to_delete(self):
        self.set_graphic("graphic", None)
        super(OperationItem, self).about_to_delete()

    @classmethod
    def build(cls, datastore, item_node, uuid_):
        operation_id = datastore.get_property(item_node, "operation_id")
        operation = cls(operation_id)
        operation.enabled = datastore.get_property(item_node, "enabled", True)
        operation.values = datastore.get_property(item_node, "values", dict())
        graphic = datastore.get_item(item_node, "graphic")
        operation.set_graphic("graphic", graphic)
        return operation

    def create_editor(self, ui):
        return None

    # enabled property
    def __get_enabled(self):
        return self.__enabled
    def __set_enabled(self, enabled):
        self.__enabled = enabled
        self.notify_set_property("enabled", enabled)
    enabled = property(__get_enabled, __set_enabled)

    # get a property.
    def get_property(self, property_id, default_value=None):
        if property_id in self.values:
            return self.values[property_id]
        if default_value is not None:
            return default_value
        for description_entry in self.description:
            if description_entry["property"] == property_id:
                return description_entry.get("default")
        return None

    # set a property.
    def set_property(self, property_id, value):
        self.values[property_id] = value
        if self.operation:
            setattr(self.operation, property_id, value)
        self.notify_set_property("values", self.values)

    # update the default value for this operation.
    def __set_property_default(self, property_id, default_value):
        for description_entry in self.description:
            if description_entry["property"] == property_id:
                description_entry["default"] = default_value
                if property_id not in self.values or self.values[property_id] is None:
                    self.values[property_id] = default_value
                    if self.operation:
                        setattr(self.operation, property_id, default_value)

    # clients call this to perform processing
    def process_data(self, data):
        if self.operation:
            return self.operation.get_processed_data(data)
        else:
            return data.copy()

    # calibrations

    def get_processed_calibration_items(self, data_shape, data_dtype, source_calibration_items):
        if self.operation:
            calibrations = [calibration_item.calibration for calibration_item in source_calibration_items]
            calibrations = self.operation.get_processed_spatial_calibrations(data_shape, data_dtype, calibrations)
            return [DataItem.CalibrationItem(calibration=calibration) for calibration in calibrations]
        else:
            return source_calibration_items

    def get_processed_intensity_calibration_item(self, data_shape, data_dtype, intensity_calibration_item):
        if self.operation:
            return DataItem.CalibrationItem(calibration=self.operation.get_processed_intensity_calibration(data_shape, data_dtype, intensity_calibration_item.calibration))
        else:
            return source_calibrations

    # data shape and type
    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        if self.operation:
            return self.operation.get_processed_data_shape_and_dtype(data_shape, data_dtype)
        return data_shape, data_dtype

    # default value handling.
    def update_data_shape_and_dtype(self, data_shape, data_dtype):
        if self.operation:
            default_values = self.operation.property_defaults_for_data_shape_and_dtype(data_shape, data_dtype)
            for property, default_value in default_values.iteritems():
                self.__set_property_default(property, default_value)

    # subclasses should override __deepcopy__ and deepcopy_from as necessary
    def __deepcopy__(self, memo):
        operation = self.__class__(self.operation_id)
        operation.deepcopy_from(self, memo)
        memo[id(self)] = operation
        return operation

    def deepcopy_from(self, operation, memo):
        values = copy.deepcopy(operation.values)
        # copy one by one to keep default values for missing keys
        for key in values.keys():
            self.values[key] = values[key]
        # TODO: Check use of memo here.
        if operation.graphic:
            self.set_graphic("graphic", operation.graphic)
        else:
            self.set_graphic("graphic", None)
        self.__enabled = operation.enabled

    def notify_set_property(self, key, value):
        super(OperationItem, self).notify_set_property(key, value)
        self.notify_listeners("operation_changed", self)

    def get_storage_item(self, key):
        if key == "graphic":
            return self.graphic
        return super(OperationItem, self).get_storage_item(key)

    def get_graphic(self, key):
        return self.get_storage_item(key)

    def set_graphic(self, key, graphic):
        if key == "graphic":
            if self.graphic:
                self.notify_clear_item("graphic")
                self.graphic.remove_observer(self)
                self.graphic.remove_ref()
                self.graphic = None
            if graphic:
                self.graphic = graphic
                graphic.add_observer(self)
                graphic.add_ref()
                self.notify_set_item("graphic", graphic)
                self.__sync_graphic()

    def __sync_graphic(self):
        for description_entry in self.description:
            type = description_entry["type"]
            property_id = description_entry["property"]
            if type == "line" and isinstance(self.graphic, Graphics.LineGraphic):
                value = self.graphic.start, self.graphic.end
                self.values[property_id] = value
                if self.operation:
                    setattr(self.operation, property_id, value)
            elif type == "rectangle" and isinstance(self.graphic, Graphics.RectangleGraphic):
                value = self.graphic.bounds
                self.values[property_id] = value
                if self.operation:
                    setattr(self.operation, property_id, value)

    # watch for changes to graphic item and try to associate with the description. hacky.
    def property_changed(self, object, key, value):
        if object is not None and object == self.graphic:
            self.__sync_graphic()
            self.notify_listeners("operation_changed", self)


class OperationPropertyBinding(UserInterfaceUtility.Binding):

    """
        Binds to a property of an operation object.

        This object records the 'values' property of the operation. Then it
        watches for changes to 'values' which match the watched property.
    """

    def __init__(self, source, property_name, converter=None):
        super(OperationPropertyBinding, self).__init__(source,  converter)
        self.__property_name = property_name
        self.source_setter = lambda value: self.source.set_property(self.__property_name, value)
        self.source_getter = lambda: self.source.get_property(self.__property_name)
        # use this to know when a specific property changes
        self.__values = copy.copy(source.values)

    # thread safe
    def property_changed(self, sender, property, property_value):
        if sender == self.source and property == "values":
            values = property_value
            new_value = values.get(self.__property_name)
            old_value = self.__values.get(self.__property_name)
            if new_value != old_value:
                # perform on the main thread
                self.add_task("update_target", lambda: self.update_target(new_value))
                self.__values = copy.copy(self.source.values)
