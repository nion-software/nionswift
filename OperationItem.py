# standard libraries
import copy
import gettext
import math

# third party libraries
# None

# local libraries
from nion.swift import DataItem
from nion.swift import Graphics
from nion.swift import Operation
from nion.swift import Storage
from nion.ui import UserInterfaceUtility

_ = gettext.gettext


class LineProfileGraphic(Graphics.LineTypeGraphic):
    def __init__(self):
        super(LineProfileGraphic, self).__init__("line-profile-graphic", _("Line Profile"))
        self.storage_properties += ["width"]
        self.__width = 1.0
    # accessors
    def __get_width(self):
        return self.__width
    def __set_width(self, width):
        self.__width = width
        self.notify_set_property("width", self.__width)
    width = property(__get_width, __set_width)
    def draw(self, ctx, mapping, is_selected=False):
        p1 = mapping.map_point_image_norm_to_widget(self.start)
        p2 = mapping.map_point_image_norm_to_widget(self.end)
        ctx.save()
        ctx.begin_path()
        ctx.move_to(p1[1], p1[0])
        ctx.line_to(p2[1], p2[0])
        if self.start_arrow_enabled:
            self.draw_arrow(ctx, p2, p1)
        if self.end_arrow_enabled:
            self.draw_arrow(ctx, p1, p2)
        ctx.line_width = 1
        ctx.stroke_style = self.color
        ctx.stroke()
        if self.width > 1.0:
            half_width = self.width * 0.5
            length = math.sqrt(math.pow(p2[0] - p1[0],2) + math.pow(p2[1] - p1[1], 2))
            dy = (p2[0] - p1[0]) / length
            dx = (p2[1] - p1[1]) / length
            ctx.save()
            ctx.begin_path()
            ctx.move_to(p1[1] + dy * half_width, p1[0] - dx * half_width)
            ctx.line_to(p2[1] + dy * half_width, p2[0] - dx * half_width)
            ctx.line_to(p2[1] - dy * half_width, p2[0] + dx * half_width)
            ctx.line_to(p1[1] - dy * half_width, p1[0] + dx * half_width)
            ctx.close_path()
            ctx.line_width = 1
            ctx.line_dash = 2
            ctx.stroke_style = self.color
            ctx.stroke()
            ctx.restore()
        ctx.restore()
        if is_selected:
            self.draw_marker(ctx, p1)
            self.draw_marker(ctx, p2)


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
        self.storage_properties += ["operation_id", "enabled", "values"]  # "dtype", "shape"

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
        self.__graphics = list()
        self.__bindings = list()
        if self.operation_id == "line-profile-operation":
            graphic = LineProfileGraphic()
            graphic.color = "#FF0"
            graphic.end_arrow_enabled = True
            self.__graphics.append(graphic)
            self.__bindings.append(OperationPropertyToGraphicBinding(self, "start", graphic, "start"))
            self.__bindings.append(OperationPropertyToGraphicBinding(self, "end", graphic, "end"))
            self.__bindings.append(OperationPropertyToGraphicBinding(self, "integration_width", graphic, "width"))
        elif self.operation_id == "crop-operation":
            graphic = Graphics.RectangleGraphic()
            graphic.color = "#FF0"
            self.__graphics.append(graphic)
            self.__bindings.append(OperationPropertyToGraphicBinding(self, "bounds", graphic, "bounds"))

    def about_to_delete(self):
        self.__graphics = None
        for binding in self.__bindings:
            binding.close()
        self.__bindings = None

    @classmethod
    def build(cls, datastore, item_node, uuid_):
        operation_id = datastore.get_property(item_node, "operation_id")
        operation_item = cls(operation_id)
        operation_item.enabled = datastore.get_property(item_node, "enabled", True)
        values = datastore.get_property(item_node, "values", dict())
        # copy one by one to keep default values for missing keys
        for key in values.keys():
            operation_item.set_property(key, values[key])
        return operation_item

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
                    self.set_property(property_id, default_value)

    # clients call this to perform processing
    def process_data(self, data):
        if self.operation:
            return self.operation.get_processed_data(data)
        else:
            return data.copy()

    # graphics

    def __get_graphics(self):
        return self.__graphics
    graphics = property(__get_graphics)

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
            return intensity_calibration_item

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
        operation_item = self.__class__(self.operation_id)
        operation_item.deepcopy_from(self, memo)
        memo[id(self)] = operation_item
        return operation_item

    def deepcopy_from(self, operation_item, memo):
        values = copy.deepcopy(operation_item.values)
        # copy one by one to keep default values for missing keys
        for key in values.keys():
            self.set_property(key, values[key])
        self.__enabled = operation_item.enabled

    # override and watch for changes to this object and notify listeners if it changes
    def notify_set_property(self, key, value):
        super(OperationItem, self).notify_set_property(key, value)
        self.notify_listeners("operation_changed", self)


class OperationPropertyBinding(UserInterfaceUtility.Binding):

    """
        Binds to a property of an operation item.

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
    def queue_update_target(self, new_value):
        # perform on the main thread
        self.add_task("update_target", lambda: self.update_target(new_value))

    # thread safe
    def property_changed(self, sender, property, property_value):
        if sender == self.source and property == "values":
            values = property_value
            new_value = values.get(self.__property_name)
            old_value = self.__values.get(self.__property_name)
            if new_value != old_value:
                self.queue_update_target(new_value)
                self.__values = copy.copy(self.source.values)


class OperationPropertyToGraphicBinding(OperationPropertyBinding):

    """
        Binds a property of an operation item to a property of a graphic item.
    """

    def __init__(self, operation, operation_property_name, graphic, graphic_property_name):
        super(OperationPropertyToGraphicBinding, self).__init__(operation, operation_property_name)
        self.__graphic = graphic
        self.__graphic.add_observer(self)
        self.__graphic_property_name = graphic_property_name
        self.__operation_property_name = operation_property_name
        self.target_setter = lambda value: setattr(self.__graphic, graphic_property_name, value)

    def close(self):
        self.__graphic.remove_observer(self)
        self.__graphic = None
        super(OperationPropertyToGraphicBinding, self).close()

    # thread safe. perform immediately for this binding. no queueing.
    def queue_update_target(self, new_value):
        self.update_target(new_value)

    # watch for property changes on the graphic.
    def property_changed(self, sender, property_name, property_value):
        super(OperationPropertyToGraphicBinding, self).property_changed(sender, property_name, property_value)
        if sender == self.__graphic and property_name == self.__graphic_property_name:
            old_property_value = self.source.get_property(self.__operation_property_name)
            # to prevent message loops, check to make sure it changed
            if property_value != old_property_value:
                self.update_source(property_value)
