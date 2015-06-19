# futures
from __future__ import absolute_import
from __future__ import division

# standard libraries
import base64
import collections
import copy
import datetime
import functools
import gettext
import logging
import math
import re
import threading
import uuid
import weakref

# third party libraries
import numpy
import scipy
import scipy.fftpack
import scipy.ndimage
import scipy.ndimage.filters
import scipy.ndimage.fourier
import scipy.signal

# local libraries
from nion.swift.model import Calibration
from nion.swift.model import Image
from nion.swift.model import Region
from nion.swift.model import Utility
from nion.ui import Binding
from nion.ui import Geometry
from nion.ui import Observable

_ = gettext.gettext


RegionBinding = collections.namedtuple("RegionBinding", ["operation_property", "region_property"])


class DataAndCalibration(object):
    """Represent the ability to calculate data and provide immediate calibrations."""

    def __init__(self, data_fn, data_shape_and_dtype, intensity_calibration, dimensional_calibrations, metadata, timestamp):
        self.data_fn = data_fn
        self.data_shape_and_dtype = data_shape_and_dtype
        self.intensity_calibration = intensity_calibration
        self.dimensional_calibrations = dimensional_calibrations
        self.timestamp = timestamp
        self.metadata = copy.deepcopy(metadata)

    @classmethod
    def from_rpc_dict(cls, d):
        if d is None:
            return None
        data = numpy.loads(base64.b64decode(d["data"].encode('utf-8')))
        data_shape_and_dtype = Image.spatial_shape_from_data(data), data.dtype
        intensity_calibration = Calibration.from_rpc_dict(d.get("intensity_calibration"))
        if "dimensional_calibrations" in d:
            dimensional_calibrations = [Calibration.from_rpc_dict(dc) for dc in d.get("dimensional_calibrations")]
        else:
            dimensional_calibrations = None
        metadata = d.get("metadata")
        timestamp = datetime.datetime(*list(map(int, re.split('[^\d]', d.get("timestamp"))))) if "timestamp" in d else None
        return DataAndCalibration(lambda: data, data_shape_and_dtype, intensity_calibration, dimensional_calibrations, metadata, timestamp)

    @property
    def rpc_dict(self):
        d = dict()
        data = self.data
        if data is not None:
            d["data"] = base64.b64encode(numpy.ndarray.dumps(data)).decode('utf=8')
        if self.intensity_calibration:
            d["intensity_calibration"] = self.intensity_calibration.rpc_dict
        if self.dimensional_calibrations:
            d["dimensional_calibrations"] = [dimensional_calibration.rpc_dict for dimensional_calibration in self.dimensional_calibrations]
        if self.timestamp:
            d["timestamp"] = self.timestamp.isoformat()
        if self.metadata:
            d["metadata"] = copy.copy(self.metadata)
        return d

    @property
    def data(self):
        return self.data_fn()

    @property
    def data_shape(self):
        data_shape_and_dtype = self.data_shape_and_dtype
        return data_shape_and_dtype[0] if data_shape_and_dtype is not None else None

    @property
    def data_dtype(self):
        data_shape_and_dtype = self.data_shape_and_dtype
        return data_shape_and_dtype[1] if data_shape_and_dtype is not None else None

    @property
    def dimensional_shape(self):
        data_shape_and_dtype = self.data_shape_and_dtype
        if data_shape_and_dtype is not None:
            data_shape, data_dtype = self.data_shape_and_dtype
            return Image.dimensional_shape_from_shape_and_dtype(data_shape, data_dtype)
        return None

    def get_intensity_calibration(self):
        return self.intensity_calibration

    def get_dimensional_calibration(self, index):
        return self.dimensional_calibrations[index]

    @property
    def is_data_1d(self):
        data_shape_and_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_1d(*data_shape_and_dtype) if data_shape_and_dtype else False

    @property
    def is_data_2d(self):
        data_shape_and_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_2d(*data_shape_and_dtype) if data_shape_and_dtype else False

    @property
    def is_data_3d(self):
        data_shape_and_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_3d(*data_shape_and_dtype) if data_shape_and_dtype else False

    @property
    def is_data_rgb(self):
        data_shape_and_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_rgb(*data_shape_and_dtype) if data_shape_and_dtype else False

    @property
    def is_data_rgba(self):
        data_shape_and_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_rgba(*data_shape_and_dtype) if data_shape_and_dtype else False

    @property
    def is_data_rgb_type(self):
        data_shape_and_dtype = self.data_shape_and_dtype
        return (Image.is_shape_and_dtype_rgb(*data_shape_and_dtype) or Image.is_shape_and_dtype_rgba(*data_shape_and_dtype)) if data_shape_and_dtype else False

    @property
    def is_data_scalar_type(self):
        data_shape_and_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_scalar_type(*data_shape_and_dtype) if data_shape_and_dtype else False

    @property
    def is_data_complex_type(self):
        data_shape_and_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_complex_type(*data_shape_and_dtype) if data_shape_and_dtype else False

    def get_data_value(self, pos):
        data = self.data
        if self.is_data_1d:
            if data is not None:
                return data[pos[0]]
        elif self.is_data_2d:
            if data is not None:
                return data[pos[0], pos[1]]
        elif self.is_data_3d:
            if data is not None:
                return data[pos[0], pos[1], pos[2]]
        return None

    @property
    def size_and_data_format_as_string(self):
        dimensional_shape = self.dimensional_shape
        data_dtype = self.data_dtype
        if dimensional_shape is not None and data_dtype is not None:
            spatial_shape_str = " x ".join([str(d) for d in dimensional_shape])
            if len(dimensional_shape) == 1:
                spatial_shape_str += " x 1"
            dtype_names = {
                numpy.int8: _("Integer (8-bit)"),
                numpy.int16: _("Integer (16-bit)"),
                numpy.int32: _("Integer (32-bit)"),
                numpy.int64: _("Integer (64-bit)"),
                numpy.uint8: _("Unsigned Integer (8-bit)"),
                numpy.uint16: _("Unsigned Integer (16-bit)"),
                numpy.uint32: _("Unsigned Integer (32-bit)"),
                numpy.uint64: _("Unsigned Integer (64-bit)"),
                numpy.float32: _("Real (32-bit)"),
                numpy.float64: _("Real (64-bit)"),
                numpy.complex64: _("Complex (2 x 32-bit)"),
                numpy.complex128: _("Complex (2 x 64-bit)"),
            }
            if self.is_data_rgb_type:
                data_size_and_data_format_as_string = _("RGB (8-bit)") if self.is_data_rgb else _("RGBA (8-bit)")
            else:
                if not self.data_dtype.type in dtype_names:
                    logging.debug("Unknown dtype %s", self.data_dtype.type)
                data_size_and_data_format_as_string = dtype_names[self.data_dtype.type] if self.data_dtype.type in dtype_names else _("Unknown Data Type")
            return "{0}, {1}".format(spatial_shape_str, data_size_and_data_format_as_string)
        return _("No Data")


class _UuidToStringConverter(object):
    def convert(self, value):
        return str(value)
    def convert_back(self, value):
        return uuid.UUID(value)


class DataItemDataSource(Observable.Observable, Observable.Broadcaster, Observable.ManagedObject):

    def __init__(self, buffered_data_source=None):
        super(DataItemDataSource, self).__init__()
        self.define_type("data-item-data-source")
        buffered_data_source_uuid = buffered_data_source.uuid if buffered_data_source else None
        self.define_property("buffered_data_source_uuid", buffered_data_source_uuid, converter=_UuidToStringConverter())
        self.__subscription = None
        self.__buffered_data_source = None
        self.__buffered_data_source_set_changed_listener = None
        self.__weak_dependent_data_item = None
        # create a publisher of data_and_calibration objects.
        # when a subscriber subscribes to the publisher, be sure to publish the first data value
        self.__publisher = Observable.Publisher()
        self.__publisher.on_subscribe = self.__notify_next_data_and_calibration
        # set the data item
        self.set_buffered_data_source(buffered_data_source)

    def close(self):
        self.set_buffered_data_source(None)
        self.set_data_item_manager(None)

    def about_to_be_removed(self):
        pass

    def will_remove_operation_region(self, region):
        if self.__buffered_data_source and region in self.__buffered_data_source.regions:
            self.__buffered_data_source.will_remove_operation_region(region)

    @property
    def ordered_operation_data_sources(self):
        return []

    @property
    def ordered_data_item_data_sources(self):
        return [self.source_data_item]

    def set_dependent_data_item(self, new_dependent_data_item):
        """Set the dependent data item. The dependent data item depends on this data source."""
        old_dependent_data_item = self.__get_dependent_data_item()
        self.__weak_dependent_data_item = weakref.ref(new_dependent_data_item) if new_dependent_data_item else None
        source_data_item = self.source_data_item
        if source_data_item:
            if new_dependent_data_item:
                source_data_item.add_dependent_data_item(new_dependent_data_item)
            elif old_dependent_data_item:
                source_data_item.remove_dependent_data_item(old_dependent_data_item)

    def __get_dependent_data_item(self):
        return self.__weak_dependent_data_item() if self.__weak_dependent_data_item else None

    @property
    def source_data_item(self):
        if self.__buffered_data_source:
            return self.__buffered_data_source._data_item
        return None

    def set_buffered_data_source(self, buffered_data_source):
        """Set the buffered_data_source associated with this reference."""
        dependent_data_item = self.__get_dependent_data_item()
        if self.__subscription:
            self.__subscription.close()
            self.__subscription = None
        source_data_item = self.source_data_item
        if source_data_item:
            if dependent_data_item:
                source_data_item.remove_dependent_data_item(dependent_data_item)
        self.__buffered_data_source = buffered_data_source
        source_data_item = self.source_data_item
        if self.__buffered_data_source:
            def next_value(data_and_calibration):
                # called when the buffered data source publishes new data.
                self.__publisher.notify_next_value(data_and_calibration)
            # make a subscriber to call next_value when buffered data source publishes new data.
            subscriber = Observable.Subscriber(next_value)
            # store the subscription while its in use.
            self.__subscription = self.__buffered_data_source.get_data_and_calibration_publisher().subscribex(subscriber)
        if source_data_item:
            if dependent_data_item:
                source_data_item.add_dependent_data_item(dependent_data_item)

    @property
    def buffered_data_source(self):
        return self.__buffered_data_source

    def set_data_item_manager(self, data_item_manager):
        # When this object is inserted into a container, it will get get a data_item_manager. The data_item_manager is
        # used to watch for the matching buffered_data_source becoming available.

        # get rid of current buffered_data_source_set_changed listener, if any
        if self.__buffered_data_source_set_changed_listener:
            self.__buffered_data_source_set_changed_listener.close()
            self.__buffered_data_source_set_changed_listener  = None

        # define function to handle buffered_data_source_set_changed
        def buffered_data_source_set_changed(new_buffered_data_sources, old_buffered_data_sources):
            for item in old_buffered_data_sources:
                if item.uuid == self.buffered_data_source_uuid:
                    self.set_buffered_data_source(None)
            for item in new_buffered_data_sources:
                if item.uuid == self.buffered_data_source_uuid:
                    self.set_buffered_data_source(item)

        if data_item_manager:
            # listen for the set of buffered_data_sources changing.
            self.__buffered_data_source_set_changed_listener = data_item_manager.buffered_data_source_set_changed_event.listen(buffered_data_source_set_changed)

            # initialize with existing buffered_data_sources
            buffered_data_source_set_changed(data_item_manager.buffered_data_source_set, set())

    def __notify_next_data_and_calibration(self, subscriber=None):
        """Grab the data_and_calibration from the data item and pass it to subscribers."""
        data_and_calibration = self.__buffered_data_source.data_and_calibration if self.__buffered_data_source else None
        self.__publisher.notify_next_value(data_and_calibration, subscriber)

    def get_data_and_calibration_publisher(self):
        """Return the data and calibration publisher. This is a required method for data sources."""
        return self.__publisher


def data_source_list_factory(lookup_id):
    type = lookup_id("type")
    if type == "data-item-data-source":
        return DataItemDataSource()
    elif type == "operation":
        return operation_item_factory(lookup_id)
    else:
        return None


class OperationItem(Observable.Observable, Observable.Broadcaster, Observable.ManagedObject):
    """
        OperationItems compute new data from other data items, regions, and metadata.

        Operations are only ever associated with one data item at once. They are not shared.

        Operations are split into data computation, which might be slow, and computations
        of metadata such as calibrations, data shapes, data sizes, and other metadata,
        which are fast.

        Metadata is important to calculate quickly since it may be used from the UI, to
        enable/disable menu items, for instance.

        Operations can utilize regions as part of their input. The regions have their values bound
        to the values in the operation.

        The operation_id property identifies the Operation object responsible for doing the computation.

        The values property holds a dict of values that specify how the Operation object should operate.

        The data_sources property holds a list of data sources. Data sources can be data items or other operations.

        The region_connections property holds a dict mapping region identifiers to region UUID's.

        Operations should return None for calibrations, metadata, or data when error conditions such as
        invalid data arise.
        """
    def __init__(self, operation_id):
        super(OperationItem, self).__init__()

        self.__weak_dependent_data_item = None

        self.__weak_regions = []

        self.__data_item_manager = None
        self.__data_item_manager_lock = threading.RLock()

        self.__data_source_publisher = Observable.Publisher()
        def send_data_sources(subscriber):
            self.__data_source_publisher.notify_next_value(self.data_sources, subscriber)
        self.__data_source_publisher.on_subscribe = send_data_sources

        class UuidMapToStringConverter(object):
            def convert(self, value):
                d = dict()
                for k in value:
                    d[k] = str(value[k])
                return d
            def convert_back(self, value):
                d = dict()
                for k in value:
                    d[k] = uuid.UUID(value[k])
                return d

        self.define_type("operation")

        self.define_property("operation_id", operation_id, read_only=True)
        self.define_property("values", dict(), changed=self.__property_changed, validate=self.__validate_values)
        self.define_property("region_connections", dict(), converter=UuidMapToStringConverter())
        self.define_relationship("data_sources", data_source_list_factory, insert=self.__data_source_inserted, remove=self.__data_source_removed)

        # an operation gets one chance to find its behavior. if the behavior doesn't exist
        # then it will simply provide null data according to the saved parameters. if there
        # are no saved parameters, defaults are used.
        self.operation = OperationManager().build_operation(operation_id)

        self.__bindings = list()

        self.name = self.operation.name if self.operation else _("Unavailable Operation")

        # manage properties
        self.description = self.operation.description if self.operation else []
        self.properties = [description_entry["property"] for description_entry in self.description]

    def __deepcopy__(self, memo):
        deepcopy = self.__class__(self.operation_id)
        deepcopy.deepcopy_from(self, memo)
        memo[id(self)] = deepcopy
        return deepcopy

    def close(self):
        for data_source in self.data_sources:
            data_source.close()

    def about_to_be_removed(self):
        """ When the operation is about to be removed, remove the region on data source, if any. """
        for data_source in self.data_sources:
            data_source.about_to_be_removed()
        for region in [weak_region() for weak_region in self.__weak_regions]:
            # this is a hack because graphics can cause operations to be
            # deleted in multiple ways. there are tests to account for the
            # various ways, but there is probably a better way to handle this
            # in the long run.
            if region:
                self.will_remove_operation_region(region)

    def will_remove_operation_region(self, region):
        for data_source in self.data_sources:
            data_source.will_remove_operation_region(region)

    def managed_object_context_changed(self):
        """ Override from ManagedObject. """
        super(OperationItem, self).managed_object_context_changed()
        for region_connection_id in self.region_connections:
            def registered(region_connection_id, region):
                self.__set_region(region_connection_id, region)
            def unregistered(region=None):
                for binding in self.__bindings:
                    binding.close()
                self.__bindings = list()
            if self.managed_object_context:
                self.managed_object_context.subscribe(self.region_connections[region_connection_id], functools.partial(registered, region_connection_id), unregistered)
            else:
                unregistered()

    def read_from_dict(self, properties):
        super(OperationItem, self).read_from_dict(properties)
        self.managed_object_context_changed()

    # called from data item when added/removed.
    def set_dependent_data_item(self, data_item):
        self.__weak_dependent_data_item = weakref.ref(data_item) if data_item else None
        for data_source in self.data_sources:
            data_source.set_dependent_data_item(data_item)

    def get_data_source_publisher(self):
        return self.__data_source_publisher

    def __validate_values(self, values):
        return Utility.clean_item_no_list(values)

    # add a reference to the given data source
    def add_data_source(self, data_source):
        assert isinstance(data_source, DataItemDataSource) or isinstance(data_source, OperationItem)
        self.append_item("data_sources", data_source)
        data_source.add_listener(self)  # for request_remove_data_item_because_operation_removed

    # remove a reference to the given data source
    def remove_data_source(self, data_source):
        data_source.remove_listener(self)
        self.remove_item("data_sources", data_source)

    def __data_source_inserted(self, name, before_index, data_source):
        dependent_data_item = self.__weak_dependent_data_item() if self.__weak_dependent_data_item else None
        data_source.set_dependent_data_item(dependent_data_item)
        data_source.set_data_item_manager(self.__data_item_manager)
        self.__data_source_publisher.notify_next_value(self.data_sources)

    def __data_source_removed(self, name, index, data_source):
        data_source.set_dependent_data_item(None)
        data_source.set_data_item_manager(None)
        self.__data_source_publisher.notify_next_value(self.data_sources)

    class OperationPublisher(Observable.Publisher):

        def __init__(self, operation_item):
            super(OperationItem.OperationPublisher, self).__init__()
            self.__operation_item = operation_item
            self.__operation_item.add_observer(self)
            self.__subscriptions = list()
            self.__data_and_calibrations = list()

            # subscribe to the data sources list
            def data_sources_changed(data_sources):
                old_subscriptions = self.__subscriptions

                self.__subscriptions = list()
                self.__data_and_calibrations = list()

                for index, data_source in enumerate(data_sources):

                    def next_value(value_index, value):
                        self.__data_and_calibrations[value_index] = value
                        self.notify_next_data()

                    self.__data_and_calibrations.append(None)  # must be valid when subscribex is called since next_value will be called immediately.
                    subscriber = Observable.Subscriber(functools.partial(next_value, index))
                    subscription = data_source.get_data_and_calibration_publisher().subscribex(subscriber)
                    self.__subscriptions.append(subscription)

                for subscription in old_subscriptions:
                    subscription.close()

            self.__data_sources_subscription = self.__operation_item.get_data_source_publisher().subscribex(Observable.Subscriber(data_sources_changed))

        def close(self):
            for subscription in self.__subscriptions:
                subscription.close()
            self.__subscriptions = list()
            self.__data_sources_subscription.close()
            self.__data_sources_subscription = None
            self.__operation_item.remove_observer(self)
            super(OperationItem.OperationPublisher, self).close()

        def subscribex(self, subscriber):
            # override from Publisher
            subscription = super(OperationItem.OperationPublisher, self).subscribex(subscriber)
            self.notify_next_data()
            return subscription

        def notify_next_data(self):
            """Send out the next value message."""
            data_and_calibrations = self.__data_and_calibrations
            if all(data_and_calibrations) and len(data_and_calibrations) > 0:
                operation = self.__operation_item.operation
                if operation:
                    values = self.__operation_item.get_realized_values(data_and_calibrations)
                    data_and_calibration = operation.get_processed_data_and_calibration(data_and_calibrations, values)
                    self.notify_next_value(data_and_calibration)

        def property_changed(self, sender, property, property_value):
            if sender == self.__operation_item and property == "values":
                self.notify_next_data()

    def get_data_and_calibration_publisher(self):
        return OperationItem.OperationPublisher(self)

    def __property_changed(self, name, value):
        self.notify_set_property(name, value)

    def __set_region(self, region_connection_id, region):
        # When region becomes available, establish bindings. Also add listener to watch for its deletion.
        if self.operation:
            for operation_property, region_property in self.operation.region_bindings[region_connection_id]:
                self.__bindings.append(OperationPropertyToRegionBinding(self, operation_property, region, region_property))
                self.set_property(operation_property, getattr(region, region_property))
            assert region.type == self.operation.region_types[region_connection_id]
            region.add_listener(self)
            # save this to remove region if this object gets removed.
            self.__weak_regions.append(weakref.ref(region))

    def establish_associated_region(self, region_connection_id, buffered_data_source, region=None):
        """
            Associate the region with this operation, update its initial values, and connect it to this operation.

            This must be called before operation is added to data item.

            The region can be None in which case a default version is created and added to the data item.
        """
        if self.operation:
            if region is None:
                region_type = self.operation.region_types[region_connection_id]
                if region_type == "point-region":
                    region = Region.PointRegion()
                    region.position = (0.5, 0.5)
                elif region_type == "line-region":
                    region = Region.LineRegion()
                    region.start = (0.2, 0.2)
                    region.end = (0.8, 0.8)
                elif region_type == "rectangle-region":
                    region = Region.RectRegion()
                    region.bounds = ((0.25, 0.25), (0.5, 0.5))
                elif region_type == "ellipse-region":
                    region = Region.EllipseRegion()
                    region.bounds = ((0.25, 0.25), (0.5, 0.5))
                elif region_type == "interval-region":
                    region = Region.IntervalRegion()
                    region.start = 0.25
                    region.end = 0.75
                assert region
                assert region.type == self.operation.region_types[region_connection_id]
                buffered_data_source.add_region(region)
            assert region
            assert region.type == self.operation.region_types[region_connection_id]
            # copy the properties from the operation to the region
            for operation_property, region_property in self.operation.region_bindings[region_connection_id]:
                setattr(region, region_property, self.get_property(operation_property))
            self.region_connections[region_connection_id] = region.uuid
        return region

    # this message comes from the region.
    # it is generated when the user deletes a region graphic
    # that informs the display which notifies the graphic which
    # notifies the operation which notifies this data item. ugh.
    def remove_region_because_graphic_removed(self, region):
        self.notify_listeners("request_remove_data_item_because_operation_removed", self)  # goes to buffered data source

    # this message comes from our own data sources. pass it on.
    def request_remove_data_item_because_operation_removed(self, region):
        self.notify_listeners("request_remove_data_item_because_operation_removed", self)  # goes to buffered data source

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
        old_value = self.get_property(property_id)
        if isinstance(old_value, list) or isinstance(old_value, tuple) or isinstance(value, list) or isinstance(value, tuple):
            old_value = Utility.clean_item_no_list(old_value)
            value = Utility.clean_item_no_list(value)
        if value != old_value:
            values = self.values
            values[property_id] = value
            self.values = values

    def get_realized_values(self, data_sources):
        values = copy.deepcopy(self.values)
        default_values = self.operation.property_defaults_for_data_shape_and_dtype(data_sources)
        for property in default_values.keys():
            if values.get(property) is None:
                values[property] = default_values[property]
        return values

    @property
    def ordered_operation_data_sources(self):
        data_sources = list()
        data_sources.append(self)
        for data_source in self.data_sources:
            data_sources.extend(data_source.ordered_operation_data_sources)
        return data_sources

    @property
    def ordered_data_item_data_sources(self):
        data_sources = list()
        for data_source in self.data_sources:
            data_sources.extend(data_source.ordered_data_item_data_sources)
        return data_sources

    def set_data_item_manager(self, data_item_manager):
        with self.__data_item_manager_lock:
            self.__data_item_manager = data_item_manager
            for data_source in self.data_sources:
                data_source.set_data_item_manager(self.__data_item_manager)

    def deepcopy_from(self, operation_item, memo):
        super(OperationItem, self).deepcopy_from(operation_item, memo)
        values = operation_item.values
        # copy one by one to keep default values for missing keys
        for key in values.keys():
            self.set_property(key, values[key])


class Operation(object):

    def __init__(self, name, operation_id, description=None):
        self.name = name
        self.operation_id = operation_id
        self.description = description if description else []
        self.region_types = dict()
        self.region_bindings = dict()

    def get_processed_data_and_calibration(self, data_and_calibrations, values):

        def get_data():
            return self.get_processed_data(data_and_calibrations, values)

        data_shape_and_dtype = self.get_processed_data_shape_and_dtype(data_and_calibrations, values)
        intensity_calibration = self.get_processed_intensity_calibration(data_and_calibrations, values)
        dimensional_calibrations = self.get_processed_dimensional_calibrations(data_and_calibrations, values)
        metadata = self.get_processed_metadata(data_and_calibrations, values)
        timestamp = self.get_processed_timestamp(data_and_calibrations, values)
        data_and_calibration = DataAndCalibration(get_data, data_shape_and_dtype, intensity_calibration,
                                                  dimensional_calibrations, metadata, timestamp)

        return data_and_calibration

    # public method to do processing.
    def get_processed_data(self, data_sources, values):
        raise NotImplementedError()
        # double check that data is a copy and not the original.
        # if data is not None:
        #     assert(id(new_data) != id(data))
        # if new_data is not None and new_data.base is not None:
        #     assert(id(new_data.base) != id(data))

    # subclasses that change the type or shape of the data must override
    def get_processed_data_shape_and_dtype(self, data_sources, values):
        if len(data_sources) > 0:
            return data_sources[0].data_shape_and_dtype
        return None

    # intensity calibration
    def get_processed_intensity_calibration(self, data_sources, values):
        if len(data_sources) > 0:
            return data_sources[0].intensity_calibration
        return None

    # spatial calibrations
    def get_processed_dimensional_calibrations(self, data_sources, values):
        if len(data_sources) > 0:
            return data_sources[0].dimensional_calibrations
        return None

    # default value handling. this gives the operation a chance to update default
    # values when the data shape or dtype changes.
    def property_defaults_for_data_shape_and_dtype(self, data_sources):
        property_defaults = dict()
        for description_entry in self.description:
            default_value = description_entry.get("default")
            if default_value is not None:
                property_defaults[description_entry["property"]] = default_value
        return property_defaults

    def get_processed_metadata(self, data_sources, values):
        if len(data_sources) > 0:
            return data_sources[0].metadata
        return None

    def get_processed_timestamp(self, data_sources, values):
        return datetime.datetime.utcnow()


class FFTOperation(Operation):

    def __init__(self):
        super(FFTOperation, self).__init__(_("FFT"), "fft-operation")

    def get_processed_data(self, data_sources, values):
        assert(len(data_sources) == 1)
        data = data_sources[0].data
        data_shape = data_sources[0].data_shape
        if data is None or not Image.is_data_valid(data):
            return None
        # scaling: numpy.sqrt(numpy.mean(numpy.absolute(data_copy)**2)) == numpy.sqrt(numpy.mean(numpy.absolute(data_copy_fft)**2))
        # see https://gist.github.com/endolith/1257010
        if Image.is_data_1d(data):
            scaling = 1.0 / numpy.sqrt(data_shape[0])
            return scipy.fftpack.fftshift(scipy.fftpack.fft(data) * scaling)
        elif Image.is_data_2d(data):
            data_copy = data.copy()  # let other threads use data while we're processing
            scaling = 1.0 / numpy.sqrt(data_shape[1] * data_shape[0])
            return scipy.fftpack.fftshift(scipy.fftpack.fft2(data_copy) * scaling)
        else:
            raise NotImplementedError()

    def get_processed_data_shape_and_dtype(self, data_sources, values):
        data_shape = data_sources[0].data_shape
        data_dtype = data_sources[0].data_dtype
        if not Image.is_shape_and_dtype_valid(data_shape, data_dtype):
            return None
        return data_shape, numpy.dtype(numpy.complex128)

    def get_processed_dimensional_calibrations(self, data_sources, values):
        data_shape = data_sources[0].data_shape
        data_dtype = data_sources[0].data_dtype
        dimensional_calibrations = data_sources[0].dimensional_calibrations
        if not Image.is_shape_and_dtype_valid(data_shape, data_dtype) or dimensional_calibrations is None:
            return None
        assert len(dimensional_calibrations) == len(Image.dimensional_shape_from_shape_and_dtype(data_shape, data_dtype))
        return [Calibration.Calibration(0.0,
                                     1.0 / (dimensional_calibrations[i].scale * data_shape[i]),
                                     "1/" + dimensional_calibrations[i].units) for i in range(len(dimensional_calibrations))]


class IFFTOperation(Operation):

    def __init__(self):
        super(IFFTOperation, self).__init__(_("Inverse FFT"), "inverse-fft-operation")

    def get_processed_data(self, data_sources, values):
        assert(len(data_sources) == 1)
        data = data_sources[0].data
        data_shape = data_sources[0].data_shape
        if data is None or not Image.is_data_valid(data):
            return None
        # scaling: numpy.sqrt(numpy.mean(numpy.absolute(data_copy)**2)) == numpy.sqrt(numpy.mean(numpy.absolute(data_copy_fft)**2))
        # see https://gist.github.com/endolith/1257010
        if Image.is_data_1d(data):
            scaling = numpy.sqrt(data_shape[0])
            return scipy.fftpack.fftshift(scipy.fftpack.ifft(data) * scaling)
        elif Image.is_data_2d(data):
            data_copy = data.copy()  # let other threads use data while we're processing
            scaling = numpy.sqrt(data_shape[1] * data_shape[0])
            return scipy.fftpack.ifft2(scipy.fftpack.ifftshift(data_copy) * scaling)
        else:
            raise NotImplementedError()

    def get_processed_dimensional_calibrations(self, data_sources, values):
        data_shape = data_sources[0].data_shape
        data_dtype = data_sources[0].data_dtype
        dimensional_calibrations = data_sources[0].dimensional_calibrations
        if not Image.is_shape_and_dtype_valid(data_shape, data_dtype) or dimensional_calibrations is None:
            return None
        assert len(dimensional_calibrations) == len(Image.dimensional_shape_from_shape_and_dtype(data_shape, data_dtype))
        return [Calibration.Calibration(0.0,
                                     1.0 / (dimensional_calibrations[i].scale * data_shape[i]),
                                     "1/" + dimensional_calibrations[i].units) for i in range(len(dimensional_calibrations))]


class AutoCorrelateOperation(Operation):

    def __init__(self):
        super(AutoCorrelateOperation, self).__init__(_("Auto Correlate"), "auto-correlate-operation")

    def get_processed_data(self, data_sources, values):
        assert(len(data_sources) == 1)
        data = data_sources[0].data
        if not Image.is_data_valid(data):
            return None
        if Image.is_data_2d(data):
            data_copy = data.copy()  # let other threads use data while we're processing
            data_std = data_copy.std(dtype=numpy.float64)
            if data_std != 0.0:
                data_norm = (data_copy - data_copy.mean(dtype=numpy.float64)) / data_std
            else:
                data_norm = data_copy
            scaling = 1.0 / (data_norm.shape[0] * data_norm.shape[1])
            data_norm = numpy.fft.rfft2(data_norm)
            return numpy.fft.fftshift(numpy.fft.irfft2(data_norm * numpy.conj(data_norm))) * scaling
            # this gives different results. why? because for some reason scipy pads out to 1023 and does calculation.
            # see https://github.com/scipy/scipy/blob/master/scipy/signal/signaltools.py
            # return scipy.signal.fftconvolve(data_copy, numpy.conj(data_copy), mode='same')
        return None


class CrossCorrelateOperation(Operation):

    def __init__(self):
        super(CrossCorrelateOperation, self).__init__(_("Cross Correlate"), "cross-correlate-operation")

    def get_processed_data(self, data_sources, values):
        if len(data_sources) == 2:
            data1 = data_sources[0].data
            data2 = data_sources[1].data
            if data1 is None or data2 is None:
                return None
            if Image.is_data_2d(data1) and Image.is_data_2d(data2):
                data_std1 = data1.std(dtype=numpy.float64)
                if data_std1 != 0.0:
                    norm1 = (data1 - data1.mean(dtype=numpy.float64)) / data_std1
                else:
                    norm1 = data1
                data_std2 = data2.std(dtype=numpy.float64)
                if data_std2 != 0.0:
                    norm2 = (data2 - data2.mean(dtype=numpy.float64)) / data_std2
                else:
                    norm2 = data2
                scaling = 1.0 / (norm1.shape[0] * norm1.shape[1])
                return numpy.fft.fftshift(numpy.fft.irfft2(numpy.fft.rfft2(norm1) * numpy.conj(numpy.fft.rfft2(norm2)))) * scaling
                # this gives different results. why? because for some reason scipy pads out to 1023 and does calculation.
                # see https://github.com/scipy/scipy/blob/master/scipy/signal/signaltools.py
                # return scipy.signal.fftconvolve(data1.copy(), numpy.conj(data2.copy()), mode='same')
        return None


class InvertOperation(Operation):

    def __init__(self):
        super(InvertOperation, self).__init__(_("Invert"), "invert-operation")

    def get_processed_data(self, data_sources, values):
        assert(len(data_sources) == 1)
        data = data_sources[0].data
        if not Image.is_data_valid(data):
            return None
        if Image.is_data_rgba(data) or Image.is_data_rgb(data):
            if Image.is_data_rgba(data):
                inverted = 255 - data[:]
                inverted[...,3] = data[...,3]
                return inverted
            else:
                return 255 - data[:]
        else:
            return -data[:]


class SobelOperation(Operation):

    def __init__(self):
        super(SobelOperation, self).__init__(_("Sobel"), "sobel-operation")

    def get_processed_data(self, data_sources, values):
        assert(len(data_sources) == 1)
        data = data_sources[0].data
        if not Image.is_data_valid(data):
            return None
        if Image.is_shape_and_dtype_rgb(data.shape, data.dtype):
            rgb = numpy.empty(data.shape[:-1] + (3,), numpy.uint8)
            rgb[..., 0] = scipy.ndimage.sobel(data[..., 0])
            rgb[..., 1] = scipy.ndimage.sobel(data[..., 1])
            rgb[..., 2] = scipy.ndimage.sobel(data[..., 2])
            return rgb
        elif Image.is_shape_and_dtype_rgba(data.shape, data.dtype):
            rgba = numpy.empty(data.shape[:-1] + (4,), numpy.uint8)
            rgba[..., 0] = scipy.ndimage.sobel(data[..., 0])
            rgba[..., 1] = scipy.ndimage.sobel(data[..., 1])
            rgba[..., 2] = scipy.ndimage.sobel(data[..., 2])
            rgba[..., 3] = data[..., 3]
            return rgba
        else:
            return scipy.ndimage.sobel(data)


class LaplaceOperation(Operation):

    def __init__(self):
        super(LaplaceOperation, self).__init__(_("Laplace"), "laplace-operation")

    def get_processed_data(self, data_sources, values):
        assert(len(data_sources) == 1)
        data = data_sources[0].data
        if not Image.is_data_valid(data):
            return None
        if Image.is_shape_and_dtype_rgb(data.shape, data.dtype):
            rgb = numpy.empty(data.shape[:-1] + (3,), numpy.uint8)
            rgb[..., 0] = scipy.ndimage.laplace(data[..., 0])
            rgb[..., 1] = scipy.ndimage.laplace(data[..., 1])
            rgb[..., 2] = scipy.ndimage.laplace(data[..., 2])
            return rgb
        elif Image.is_shape_and_dtype_rgba(data.shape, data.dtype):
            rgba = numpy.empty(data.shape[:-1] + (4,), numpy.uint8)
            rgba[..., 0] = scipy.ndimage.laplace(data[..., 0])
            rgba[..., 1] = scipy.ndimage.laplace(data[..., 1])
            rgba[..., 2] = scipy.ndimage.laplace(data[..., 2])
            rgba[..., 3] = data[..., 3]
            return rgba
        else:
            return scipy.ndimage.laplace(data)


class GaussianBlurOperation(Operation):

    def __init__(self):
        description = [
            { "name": _("Radius"), "property": "sigma", "type": "scalar", "default": 0.3 }
        ]
        super(GaussianBlurOperation, self).__init__(_("Gaussian Blur"), "gaussian-blur-operation", description)

    def get_processed_data(self, data_sources, values):
        assert(len(data_sources) == 1)
        data = data_sources[0].data
        if not Image.is_data_valid(data):
            return None
        return scipy.ndimage.gaussian_filter(data, sigma=10*values.get("sigma"))


class MedianFilterOperation(Operation):

    def __init__(self):
        description = [
            { "name": _("Size"), "property": "size", "type": "integer-field", "default": 3 }
        ]
        super(MedianFilterOperation, self).__init__(_("Median Filter"), "median-filter-operation", description)

    def get_processed_data(self, data_sources, values):
        assert(len(data_sources) == 1)
        data = data_sources[0].data
        if not Image.is_data_valid(data):
            return None
        size = max(min(values.get("size"), 999), 1)
        if Image.is_shape_and_dtype_rgb(data.shape, data.dtype):
            rgb = numpy.empty(data.shape[:-1] + (3,), numpy.uint8)
            rgb[..., 0] = scipy.ndimage.median_filter(data[..., 0], size=size)
            rgb[..., 1] = scipy.ndimage.median_filter(data[..., 1], size=size)
            rgb[..., 2] = scipy.ndimage.median_filter(data[..., 2], size=size)
            return rgb
        elif Image.is_shape_and_dtype_rgba(data.shape, data.dtype):
            rgba = numpy.empty(data.shape[:-1] + (4,), numpy.uint8)
            rgba[..., 0] = scipy.ndimage.median_filter(data[..., 0], size=size)
            rgba[..., 1] = scipy.ndimage.median_filter(data[..., 1], size=size)
            rgba[..., 2] = scipy.ndimage.median_filter(data[..., 2], size=size)
            rgba[..., 3] = data[..., 3]
            return rgba
        else:
            return scipy.ndimage.median_filter(data, size=size)


class UniformFilterOperation(Operation):

    def __init__(self):
        description = [
            { "name": _("Size"), "property": "size", "type": "integer-field", "default": 3 }
        ]
        super(UniformFilterOperation, self).__init__(_("Uniform Filter"), "uniform-filter-operation", description)

    def get_processed_data(self, data_sources, values):
        assert(len(data_sources) == 1)
        data = data_sources[0].data
        if not Image.is_data_valid(data):
            return None
        size = max(min(values.get("size"), 999), 1)
        if Image.is_shape_and_dtype_rgb(data.shape, data.dtype):
            rgb = numpy.empty(data.shape[:-1] + (3,), numpy.uint8)
            rgb[..., 0] = scipy.ndimage.uniform_filter(data[..., 0], size=size)
            rgb[..., 1] = scipy.ndimage.uniform_filter(data[..., 1], size=size)
            rgb[..., 2] = scipy.ndimage.uniform_filter(data[..., 2], size=size)
            return rgb
        elif Image.is_shape_and_dtype_rgba(data.shape, data.dtype):
            rgba = numpy.empty(data.shape[:-1] + (4,), numpy.uint8)
            rgba[..., 0] = scipy.ndimage.uniform_filter(data[..., 0], size=size)
            rgba[..., 1] = scipy.ndimage.uniform_filter(data[..., 1], size=size)
            rgba[..., 2] = scipy.ndimage.uniform_filter(data[..., 2], size=size)
            rgba[..., 3] = data[..., 3]
            return rgba
        else:
            return scipy.ndimage.uniform_filter(data, size=size)


class TransposeFlipOperation(Operation):

    def __init__(self):
        description = [
            { "name": _("Transpose"), "property": "transpose", "type": "boolean-checkbox", "default": False },
            { "name": _("Flip Horizontal"), "property": "flip_horizontal", "type": "boolean-checkbox", "default": False },
            { "name": _("Flip Vertical"), "property": "flip_vertical", "type": "boolean-checkbox", "default": False }
        ]
        super(TransposeFlipOperation, self).__init__(_("Transpose/Flip"), "transpose-flip-operation", description)

    def get_processed_dimensional_calibrations(self, data_sources, values):
        if len(data_sources) > 0:
            dimensional_calibrations = data_sources[0].dimensional_calibrations
            if values.get("transpose"):
                dimensional_calibrations = list(reversed(data_sources[0].dimensional_calibrations))
            else:
                dimensional_calibrations = data_sources[0].dimensional_calibrations
            return dimensional_calibrations
        return None

    def get_processed_data_shape_and_dtype(self, data_sources, values):
        if len(data_sources) > 0:
            data_shape = data_sources[0].data_shape
            data_dtype = data_sources[0].data_dtype
            if not Image.is_shape_and_dtype_valid(data_shape, data_dtype):
                return None
            if values.get("transpose"):
                if Image.is_shape_and_dtype_rgb_type(data_shape, data_dtype):
                    data_shape = list(reversed(data_shape[0:2])) + [data_shape[-1],]
                else:
                    data_shape = list(reversed(data_shape))
            return data_shape, data_dtype
        return None

    def get_processed_data(self, data_sources, values):
        assert(len(data_sources) == 1)
        data = data_sources[0].data
        data_id = id(data)
        if not Image.is_data_valid(data):
            return None
        flip_horizontal = values.get("flip_horizontal")
        flip_vertical = values.get("flip_vertical")
        transpose = values.get("transpose")
        if transpose:
            if Image.is_shape_and_dtype_rgb_type(data.shape, data.dtype):
                data = numpy.transpose(data, [1,0,2])
            else:
                data = numpy.transpose(data, [1,0])
        if flip_horizontal:
            data = numpy.fliplr(data)
        if flip_vertical:
            data = numpy.flipud(data)
        if id(data) == data_id:  # ensure real data, not a view
            data = data.copy()
        return data


class Crop2dOperation(Operation):

    def __init__(self):
        description = [
            { "name": _("Bounds"), "property": "bounds", "type": "rectangle", "default": ((0.0, 0.0), (1.0, 1.0)) }
        ]
        super(Crop2dOperation, self).__init__(_("Crop"), "crop-operation", description)
        self.region_types = {"crop": "rectangle-region"}
        self.region_bindings = {"crop": [RegionBinding("bounds", "bounds")]}

    def get_processed_dimensional_calibrations(self, data_sources, values):
        data_shape = data_sources[0].data_shape
        data_dtype = data_sources[0].data_dtype
        dimensional_calibrations = data_sources[0].dimensional_calibrations
        if not Image.is_shape_and_dtype_valid(data_shape, data_dtype) or dimensional_calibrations is None:
            return None
        cropped_dimensional_calibrations = list()
        bounds = values.get("bounds")
        for index, dimensional_calibration in enumerate(dimensional_calibrations):
            cropped_calibration = Calibration.Calibration(dimensional_calibration.offset + data_shape[index] * bounds[0][index] * dimensional_calibration.scale,
                                                          dimensional_calibration.scale,
                                                          dimensional_calibration.units)
            cropped_dimensional_calibrations.append(cropped_calibration)
        return cropped_dimensional_calibrations

    def get_processed_data_shape_and_dtype(self, data_sources, values):
        data_shape = data_sources[0].data_shape
        data_dtype = data_sources[0].data_dtype
        if not Image.is_shape_and_dtype_valid(data_shape, data_dtype):
            return None
        bounds = values.get("bounds")
        bounds_int = ((int(data_shape[0] * bounds[0][0]), int(data_shape[1] * bounds[0][1])), (int(data_shape[0] * bounds[1][0]), int(data_shape[1] * bounds[1][1])))
        if Image.is_shape_and_dtype_rgb_type(data_shape, data_dtype):
            return bounds_int[1] + (data_shape[-1], ), data_dtype
        else:
            return bounds_int[1], data_dtype

    def get_processed_data(self, data_sources, values):
        assert(len(data_sources) == 1)
        data = data_sources[0].data
        if not Image.is_data_valid(data):
            return None
        data_shape = data_sources[0].data_shape
        bounds = values.get("bounds")
        bounds_int = ((int(data_shape[0] * bounds[0][0]), int(data_shape[1] * bounds[0][1])), (int(data_shape[0] * bounds[1][0]), int(data_shape[1] * bounds[1][1])))
        return data[bounds_int[0][0]:bounds_int[0][0] + bounds_int[1][0], bounds_int[0][1]:bounds_int[0][1] + bounds_int[1][1]].copy()


class Slice3dOperation(Operation):

    def __init__(self):
        description = [
            { "name": _("Slice Center"), "property": "slice_center", "type": "slice-center-field", "default": 0 },
            { "name": _("Slice Width"), "property": "slice_width", "type": "slice-width-field", "default": 1 }
        ]
        super(Slice3dOperation, self).__init__(_("Slice"), "slice-operation", description)

    def get_processed_data_shape_and_dtype(self, data_sources, values):
        data_shape = data_sources[0].data_shape
        data_dtype = data_sources[0].data_dtype
        if not Image.is_shape_and_dtype_valid(data_shape, data_dtype):
            return None
        return data_shape[1:], data_dtype

    def get_processed_data(self, data_sources, values):
        assert(len(data_sources) == 1)
        data = data_sources[0].data
        if not Image.is_data_valid(data):
            return None
        shape = data.shape
        slice_center = values.get("slice_center")
        slice_width = values.get("slice_width")
        slice_start = slice_center + 1 - slice_width
        slice_start = max(slice_start, 0)
        slice_end = slice_start + slice_width
        slice_end = min(shape[0], slice_end)
        return numpy.average(data[slice_start:slice_end,:], 0)

    def get_processed_dimensional_calibrations(self, data_sources, values):
        return data_sources[0].dimensional_calibrations[1:]


class Pick3dOperation(Operation):

    def __init__(self):
        description = [
            { "name": _("Position"), "property": "position", "type": "point", "default": (0.5, 0.5) },
        ]
        super(Pick3dOperation, self).__init__(_("Pick"), "pick-operation", description)
        self.region_types = {"pick": "point-region"}
        self.region_bindings = {"pick": [RegionBinding("position", "position")]}

    def get_processed_data_shape_and_dtype(self, data_sources, values):
        data_shape = data_sources[0].data_shape
        data_dtype = data_sources[0].data_dtype
        if not Image.is_shape_and_dtype_valid(data_shape, data_dtype):
            return None
        return (data_shape[0], ), data_dtype

    def get_processed_data(self, data_sources, values):
        assert(len(data_sources) == 1)
        data = data_sources[0].data
        if not Image.is_data_valid(data):
            return None
        data_shape = data_sources[0].data_shape
        position = values.get("position")
        position = Geometry.FloatPoint.make(position)
        position_i = Geometry.IntPoint(y=position.y * data_shape[1], x=position.x * data_shape[2])
        if position_i.y >= 0 and position_i.y < data_shape[1] and position_i.x >= 0 and position_i.x < data_shape[2]:
            return data[:, position_i[0], position_i[1]].copy()
        else:
            return numpy.zeros((data_shape[0], ), dtype=data.dtype)


class Projection2dOperation(Operation):

    def __init__(self):
        # hardcoded to axis 0 right now
        super(Projection2dOperation, self).__init__(_("Projection"), "projection-operation")

    def get_processed_dimensional_calibrations(self, data_sources, values):
        dimensional_calibrations = data_sources[0].dimensional_calibrations
        if dimensional_calibrations is None:
            return None
        return copy.deepcopy(dimensional_calibrations)[1:]

    def get_processed_data_shape_and_dtype(self, data_sources, values):
        data_shape = data_sources[0].data_shape
        data_dtype = data_sources[0].data_dtype
        if not Image.is_shape_and_dtype_valid(data_shape, data_dtype):
            return None
        return data_shape[1:], data_dtype

    def get_processed_data(self, data_sources, values):
        assert(len(data_sources) == 1)
        data = data_sources[0].data
        if not Image.is_data_valid(data):
            return None
        if Image.is_shape_and_dtype_rgb_type(data.shape, data.dtype):
            if Image.is_shape_and_dtype_rgb(data.shape, data.dtype):
                rgb_image = numpy.empty(data.shape[1:], numpy.uint8)
                rgb_image[:,0] = numpy.average(data[...,0], 0)
                rgb_image[:,1] = numpy.average(data[...,1], 0)
                rgb_image[:,2] = numpy.average(data[...,2], 0)
                return rgb_image
            else:
                rgba_image = numpy.empty(data.shape[1:], numpy.uint8)
                rgba_image[:,0] = numpy.average(data[...,0], 0)
                rgba_image[:,1] = numpy.average(data[...,1], 0)
                rgba_image[:,2] = numpy.average(data[...,2], 0)
                rgba_image[:,3] = numpy.average(data[...,3], 0)
                return rgba_image
        else:
            return numpy.average(data, 0)


class Resample2dOperation(Operation):

    def __init__(self):
        description = [
            {"name": _("Width"), "property": "width", "type": "integer-field", "default": None},
            {"name": _("Height"), "property": "height", "type": "integer-field", "default": None},
        ]
        super(Resample2dOperation, self).__init__(_("Resample"), "resample-operation", description)

    def get_processed_data(self, data_sources, values):
        assert(len(data_sources) == 1)
        data = data_sources[0].data
        if not Image.is_data_valid(data):
            return None
        if Image.is_data_2d(data):
            height = values.get("height", data.shape[0])
            width = values.get("width", data.shape[1])
            if data.shape[1] == width and data.shape[0] == height:
                return data.copy()
            return Image.scaled(data, (height, width))
        return None

    def get_processed_dimensional_calibrations(self, data_sources, values):
        data_shape = data_sources[0].data_shape
        data_dtype = data_sources[0].data_dtype
        dimensional_calibrations = data_sources[0].dimensional_calibrations
        if not Image.is_shape_and_dtype_valid(data_shape, data_dtype) or dimensional_calibrations is None:
            return None
        assert len(dimensional_calibrations) == 2
        height = values.get("height", data_shape[0])
        width = values.get("width", data_shape[1])
        dimensions = (height, width)
        return [Calibration.Calibration(dimensional_calibrations[i].offset,
                                     dimensional_calibrations[i].scale * data_shape[i] / dimensions[i],
                                     dimensional_calibrations[i].units) for i in range(len(dimensional_calibrations))]

    def get_processed_data_shape_and_dtype(self, data_sources, values):
        data_shape = data_sources[0].data_shape
        data_dtype = data_sources[0].data_dtype
        if not Image.is_shape_and_dtype_valid(data_shape, data_dtype):
            return None
        height = values.get("height", data_shape[0])
        width = values.get("width", data_shape[1])
        if Image.is_shape_and_dtype_rgb_type(data_shape, data_dtype):
            return (height, width, data_shape[-1]), data_dtype
        else:
            return (height, width), data_dtype

    def property_defaults_for_data_shape_and_dtype(self, data_sources):
        property_defaults = super(Resample2dOperation, self).property_defaults_for_data_shape_and_dtype(data_sources)
        data_shape = data_sources[0].data_shape
        data_dtype = data_sources[0].data_dtype
        if Image.is_shape_and_dtype_valid(data_shape, data_dtype):
            property_defaults["height"] = data_shape[0]
            property_defaults["width"] = data_shape[1]
        return property_defaults


class HistogramOperation(Operation):

    def __init__(self):
        super(HistogramOperation, self).__init__(_("Histogram"), "histogram-operation")
        self.bins = 256

    def get_processed_data_shape_and_dtype(self, data_sources, values):
        return (self.bins, ), numpy.dtype(numpy.int)

    def get_processed_data(self, data_sources, values):
        assert(len(data_sources) == 1)
        data = data_sources[0].data
        if not Image.is_data_valid(data):
            return None
        histogram_data = numpy.histogram(data, bins=self.bins)
        return histogram_data[0].astype(numpy.int)


class LineProfileOperation(Operation):

    def __init__(self):
        description = [
            { "name": _("Vector"), "property": "vector", "type": "vector", "default": ((0.25, 0.25), (0.75, 0.75)) },
            { "name": _("Integration Width"), "property": "integration_width", "type": "integer-field", "default": 1 }
        ]
        super(LineProfileOperation, self).__init__(_("Line Profile"), "line-profile-operation", description)
        self.region_types = {"line": "line-region"}
        self.region_bindings = {"line": [RegionBinding("vector", "vector"),
                                         RegionBinding("integration_width", "width")]}

    def get_processed_data_shape_and_dtype(self, data_sources, values):
        data_shape = data_sources[0].data_shape
        data_dtype = data_sources[0].data_dtype
        if not Image.is_shape_and_dtype_valid(data_shape, data_dtype):
            return None
        start, end = values.get("vector")
        shape = data_shape
        start_data = (int(shape[0]*start[0]), int(shape[1]*start[1]))
        end_data = (int(shape[0]*end[0]), int(shape[1]*end[1]))
        length = int(math.sqrt((end_data[1] - start_data[1])**2 + (end_data[0] - start_data[0])**2))
        if Image.is_shape_and_dtype_rgb_type(data_shape, data_dtype):
            return (length, ), numpy.dtype(numpy.double)
        else:
            return (length, ), numpy.dtype(numpy.double)

    def get_processed_dimensional_calibrations(self, data_sources, values):
        dimensional_calibrations = data_sources[0].dimensional_calibrations
        if dimensional_calibrations is None or len(dimensional_calibrations) != 2:
            return None
        return [Calibration.Calibration(0.0, dimensional_calibrations[1].scale, dimensional_calibrations[1].units)]

    # calculate grid of coordinates. returns n coordinate arrays for each row.
    # start and end are in data coordinates.
    # n is a positive integer, not zero
    def __coordinates(self, start, end, n):
        assert n > 0 and int(n) == n
        # n=1 => 0
        # n=2 => -0.5, 0.5
        # n=3 => -1, 0, 1
        # n=4 => -1.5, -0.5, 0.5, 1.5
        length = math.sqrt(math.pow(end[0] - start[0], 2) + math.pow(end[1] - start[1], 2))
        l = math.floor(length)
        a = numpy.linspace(0, length, l)  # along
        t = numpy.linspace(-(n-1)*0.5, (n-1)*0.5, n)  # transverse
        dy = (end[0] - start[0]) / length
        dx = (end[1] - start[1]) / length
        ix, iy = numpy.meshgrid(a, t)
        yy = start[0] + dy * ix + dx * iy
        xx = start[1] + dx * ix - dy * iy
        return xx, yy

    # xx, yy = __coordinates(None, (4,4), (8,4), 3)

    def get_processed_data(self, data_sources, values):
        assert(len(data_sources) == 1)
        data = data_sources[0].data
        if not Image.is_data_valid(data):
            return None
        assert Image.is_data_2d(data)
        if Image.is_data_rgb_type(data):
            data = Image.convert_to_grayscale(data, numpy.double)
        start, end = values.get("vector")
        integration_width = int(values.get("integration_width"))
        shape = data.shape
        integration_width = min(max(shape[0], shape[1]), integration_width)  # limit integration width to sensible value
        start_data = (int(shape[0]*start[0]), int(shape[1]*start[1]))
        end_data = (int(shape[0]*end[0]), int(shape[1]*end[1]))
        length = math.sqrt(math.pow(end_data[1] - start_data[1], 2) + math.pow(end_data[0] - start_data[0], 2))
        if length > 1.0:
            spline_order_lookup = { "nearest": 0, "linear": 1, "quadratic": 2, "cubic": 3 }
            method = "nearest"
            spline_order = spline_order_lookup[method]
            xx, yy = self.__coordinates(start_data, end_data, integration_width)
            samples = scipy.ndimage.map_coordinates(data, (yy, xx), order=spline_order)
            if len(samples.shape) > 1:
                return numpy.sum(samples, 0) / integration_width
            else:
                return samples
        return numpy.zeros((1))


class ConvertToScalarOperation(Operation):

    def __init__(self):
        super(ConvertToScalarOperation, self).__init__(_("Convert to Scalar"), "convert-to-scalar-operation")

    def get_processed_data(self, data_sources, values):
        assert(len(data_sources) == 1)
        data = data_sources[0].data
        if not Image.is_data_valid(data):
            return None
        if Image.is_data_rgba(data) or Image.is_data_rgb(data):
            return Image.convert_to_grayscale(data, numpy.double)
        elif Image.is_data_complex_type(data):
            return Image.scalar_from_array(data)
        else:
            return data.copy()

    def get_processed_data_shape_and_dtype(self, data_sources, values):
        data_shape = data_sources[0].data_shape
        data_dtype = data_sources[0].data_dtype
        if not Image.is_shape_and_dtype_valid(data_shape, data_dtype):
            return None
        if Image.is_shape_and_dtype_rgb_type(data_shape, data_dtype):
            return data_shape[:-1], numpy.dtype(numpy.double)
        elif Image.is_shape_and_dtype_complex_type(data_shape, data_dtype):
            if Image.is_shape_and_dtype_complex64(data_shape, data_dtype):
                return data_shape, numpy.dtype(numpy.float32)
            else:
                return data_shape, numpy.dtype(numpy.float64)
        else:
            return data_shape, data_dtype


class OperationManager(Utility.Singleton("OperationManagerSingleton", (object, ), {})):
    # __metaclass__ = Utility.Singleton
    # TODO: Fix metaclass in Python 3

    def __init__(self):
        self.__operations = dict()

    def register_operation(self, operation_id, create_operation_fn):
        self.__operations[operation_id] = create_operation_fn

    def unregister_operation(self, operation_id):
        del self.__operations[operation_id]

    def build_operation(self, operation_id):
        if operation_id in self.__operations:
            return self.__operations[operation_id]()
        return None


class OperationPropertyBinding(Binding.Binding):

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
    def property_changed(self, sender, property, property_value):
        if sender == self.source and property == "values":
            values = property_value
            new_value = values.get(self.__property_name)
            old_value = self.__values.get(self.__property_name)
            if new_value != old_value:
                self.update_target(new_value)
                self.__values = copy.copy(self.source.values)


class SliceOperationPropertyBinding(Binding.Binding):

    """
        Binds to a property of an operation item.

        This object records the 'values' property of the operation. Then it
        watches for changes to 'values' which match the watched property.
        """

    def __init__(self, source, property_name, converter=None):
        super(SliceOperationPropertyBinding, self).__init__(source,  converter)
        self.__property_name = property_name
        def validate_and_set(value):
            value = min(value, self.source.data_item.maybe_data_source.dimensional_shape[0])
            value = max(value, 0)
            self.source.set_property(self.__property_name, value)
        self.source_setter = validate_and_set
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
                self.update_target(new_value)
                self.__values = copy.copy(self.source.values)


class OperationPropertyToRegionBinding(OperationPropertyBinding):

    """
        Binds a property of an operation item to a property of a graphic item.
    """

    def __init__(self, operation, operation_property_name, region, region_property_name):
        super(OperationPropertyToRegionBinding, self).__init__(operation, operation_property_name)
        self.__region = region
        self.__region.add_observer(self)
        self.__region_property_name = region_property_name
        self.__operation_property_name = operation_property_name
        self.target_setter = lambda value: setattr(self.__region, region_property_name, value)

    def close(self):
        self.__region.remove_observer(self)
        self.__region = None
        super(OperationPropertyToRegionBinding, self).close()

    # watch for property changes on the region.
    def property_changed(self, sender, property_name, property_value):
        super(OperationPropertyToRegionBinding, self).property_changed(sender, property_name, property_value)
        if sender == self.__region and property_name == self.__region_property_name:
            old_property_value = self.source.get_property(self.__operation_property_name)
            # to prevent message loops, check to make sure it changed
            if property_value != old_property_value:
                self.update_source(property_value)


OperationManager().register_operation("fft-operation", lambda: FFTOperation())
OperationManager().register_operation("inverse-fft-operation", lambda: IFFTOperation())
OperationManager().register_operation("auto-correlate-operation", lambda: AutoCorrelateOperation())
OperationManager().register_operation("cross-correlate-operation", lambda: CrossCorrelateOperation())
OperationManager().register_operation("invert-operation", lambda: InvertOperation())
OperationManager().register_operation("sobel-operation", lambda: SobelOperation())
OperationManager().register_operation("laplace-operation", lambda: LaplaceOperation())
OperationManager().register_operation("gaussian-blur-operation", lambda: GaussianBlurOperation())
OperationManager().register_operation("median-filter-operation", lambda: MedianFilterOperation())
OperationManager().register_operation("uniform-filter-operation", lambda: UniformFilterOperation())
OperationManager().register_operation("transpose-flip-operation", lambda: TransposeFlipOperation())
OperationManager().register_operation("crop-operation", lambda: Crop2dOperation())
OperationManager().register_operation("slice-operation", lambda: Slice3dOperation())
OperationManager().register_operation("pick-operation", lambda: Pick3dOperation())
OperationManager().register_operation("projection-operation", lambda: Projection2dOperation())
OperationManager().register_operation("resample-operation", lambda: Resample2dOperation())
OperationManager().register_operation("histogram-operation", lambda: HistogramOperation())
OperationManager().register_operation("line-profile-operation", lambda: LineProfileOperation())
OperationManager().register_operation("convert-to-scalar-operation", lambda: ConvertToScalarOperation())


def operation_item_factory(lookup_id):
    return OperationItem(lookup_id("operation_id"))
