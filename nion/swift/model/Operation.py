# futures
from __future__ import absolute_import
from __future__ import division

# standard libraries
import collections
import copy
import functools
import gettext
import threading
import uuid
import weakref

# third party libraries
import numpy

# local libraries
from nion.data import Core
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift.model import Region
from nion.swift.model import Symbolic
from nion.swift.model import Utility
from nion.ui import Binding
from nion.ui import Converter
from nion.ui import Event
from nion.ui import Observable
from nion.ui import Persistence

_ = gettext.gettext


RegionBinding = collections.namedtuple("RegionBinding", ["operation_property", "region_property"])


class DataItemDataSource(Observable.Observable, Observable.Broadcaster, Persistence.PersistentObject):

    def __init__(self, buffered_data_source=None):
        super(DataItemDataSource, self).__init__()
        self.define_type("data-item-data-source")
        buffered_data_source_uuid = buffered_data_source.uuid if buffered_data_source else None
        self.define_property("buffered_data_source_uuid", buffered_data_source_uuid, converter=Converter.UuidToStringConverter())
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
        self.request_remove_data_item_because_operation_removed_event = Event.Event()  # required, but unused
        self._about_to_be_removed = False
        self._closed = False

    def close(self):
        self.set_buffered_data_source(None)
        self.set_data_item_manager(None)
        assert self._about_to_be_removed
        assert not self._closed
        self._closed = True

    def about_to_be_removed(self):
        # called before close and before item is removed from its container
        assert not self._about_to_be_removed
        self._about_to_be_removed = True

    def will_remove_operation_region(self, region):
        if self.__buffered_data_source and region in self.__buffered_data_source.regions:
            self.__buffered_data_source.will_remove_operation_region(region)

    @property
    def ordered_operation_data_sources(self):
        return []

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


class OperationItem(Observable.Observable, Observable.Broadcaster, Persistence.PersistentObject):
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

        self.__regions = list()
        self.__remove_region_listeners = list()

        self.__data_item_manager = None
        self.__data_item_manager_lock = threading.RLock()

        self.__data_source_publisher = Observable.Publisher()
        def send_data_sources(subscriber):
            self.__data_source_publisher.notify_next_value(self.data_sources, subscriber)
        self.__data_source_publisher.on_subscribe = send_data_sources

        self.__request_remove_listeners = list()

        self.request_remove_data_item_because_operation_removed_event = Event.Event()

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

        self._about_to_be_removed = False
        self._closed = False

    def __deepcopy__(self, memo):
        deepcopy = self.__class__(self.operation_id)
        deepcopy.deepcopy_from(self, memo)
        memo[id(self)] = deepcopy
        return deepcopy

    def close(self):
        for data_source in self.data_sources:
            data_source.close()
        for remove_region_listener in self.__remove_region_listeners:
            remove_region_listener.close()
        self.__remove_region_listeners = None
        assert self._about_to_be_removed
        assert not self._closed
        self._closed = True

    def about_to_be_removed(self):
        # called before close and before item is removed from its container
        for data_source in self.data_sources:
            data_source.about_to_be_removed()
        for region in self.__regions:
            # this is a hack because graphics can cause operations to be
            # deleted in multiple ways. there are tests to account for the
            # various ways, but there is probably a better way to handle this
            # in the long run.
            self.will_remove_operation_region(region)
        assert not self._about_to_be_removed
        self._about_to_be_removed = True

    def will_remove_operation_region(self, region):
        for data_source in self.data_sources:
            data_source.will_remove_operation_region(region)

    def persistent_object_context_changed(self):
        """ Override from PersistentObject. """
        super(OperationItem, self).persistent_object_context_changed()
        for region_connection_id in self.region_connections:
            def registered(region_connection_id, region):
                self.__set_region(region_connection_id, region)
            def unregistered(region=None):
                for binding in self.__bindings:
                    binding.close()
                self.__bindings = list()
            if self.persistent_object_context:
                self.persistent_object_context.subscribe(self.region_connections[region_connection_id], functools.partial(registered, region_connection_id), unregistered)
            else:
                unregistered()

    def read_from_dict(self, properties):
        super(OperationItem, self).read_from_dict(properties)
        self.persistent_object_context_changed()

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

    # remove a reference to the given data source
    def remove_data_source(self, data_source):
        self.remove_item("data_sources", data_source)

    def __data_source_inserted(self, name, before_index, data_source):
        dependent_data_item = self.__weak_dependent_data_item() if self.__weak_dependent_data_item else None
        data_source.set_dependent_data_item(dependent_data_item)
        data_source.set_data_item_manager(self.__data_item_manager)
        def notify_request_remove_data_item_because_operation_removed():
            self.request_remove_data_item_because_operation_removed_event.fire()
        request_remove_listener = data_source.request_remove_data_item_because_operation_removed_event.listen(notify_request_remove_data_item_because_operation_removed)
        self.__request_remove_listeners.insert(before_index, request_remove_listener)
        self.__data_source_publisher.notify_next_value(self.data_sources)

    def __data_source_removed(self, name, index, data_source):
        data_source.set_dependent_data_item(None)
        data_source.set_data_item_manager(None)
        request_remove_listener = self.__request_remove_listeners[index]
        request_remove_listener.close()
        self.__request_remove_listeners.remove(request_remove_listener)
        self.__data_source_publisher.notify_next_value(self.data_sources)

    class OperationPublisher(Observable.Publisher):

        def __init__(self, operation_item):
            super(OperationItem.OperationPublisher, self).__init__()
            self.__operation_item = operation_item
            self.__property_changed_listener = operation_item.property_changed_event.listen(self.__property_changed)
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
            self.__property_changed_listener.close()
            self.__property_changed_listener = None
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

        def __property_changed(self, property, property_value):
            if property == "values":
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
            def notify_request_remove_data_item_because_operation_removed():
                self.request_remove_data_item_because_operation_removed_event.fire()
            remove_region_listener = region.remove_region_because_graphic_removed_event.listen(notify_request_remove_data_item_because_operation_removed)
            self.__remove_region_listeners.append(remove_region_listener)
            # save this to remove region if this object gets removed.
            self.__regions.append(region)

    def establish_associated_region(self, region_connection_id, buffered_data_source, region=None) -> Region.Region:
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
        data_and_calibration = DataAndMetadata.DataAndMetadata(get_data, data_shape_and_dtype, intensity_calibration,
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
        return max([data_source.timestamp for data_source in data_sources])


class FFTOperation(Operation):

    def __init__(self):
        super(FFTOperation, self).__init__(_("FFT"), "fft-operation")

    def get_processed_data_and_calibration(self, data_and_calibrations, values):
        data_and_metadata = Core.function_fft(*data_and_calibrations)
        return data_and_metadata if data_and_metadata else None


class IFFTOperation(Operation):

    def __init__(self):
        super(IFFTOperation, self).__init__(_("Inverse FFT"), "inverse-fft-operation")

    def get_processed_data_and_calibration(self, data_and_calibrations, values):
        data_and_metadata = Core.function_ifft(*data_and_calibrations)
        return data_and_metadata if data_and_metadata else None


class AutoCorrelateOperation(Operation):

    def __init__(self):
        super(AutoCorrelateOperation, self).__init__(_("Auto Correlate"), "auto-correlate-operation")

    def get_processed_data_and_calibration(self, data_and_calibrations, values):
        data_and_metadata = Core.function_autocorrelate(*data_and_calibrations)
        return data_and_metadata if data_and_metadata else None


class CrossCorrelateOperation(Operation):

    def __init__(self):
        super(CrossCorrelateOperation, self).__init__(_("Cross Correlate"), "cross-correlate-operation")

    def get_processed_data_and_calibration(self, data_and_calibrations, values):
        data_and_metadata = Core.function_crosscorrelate(*data_and_calibrations)
        return data_and_metadata if data_and_metadata else None


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

    def get_processed_data_and_calibration(self, data_and_calibrations, values):
        data_and_metadata = Core.function_sobel(*data_and_calibrations)
        return data_and_metadata if data_and_metadata else None


class LaplaceOperation(Operation):

    def __init__(self):
        super(LaplaceOperation, self).__init__(_("Laplace"), "laplace-operation")

    def get_processed_data_and_calibration(self, data_and_calibrations, values):
        data_and_metadata = Core.function_laplace(*data_and_calibrations)
        return data_and_metadata if data_and_metadata else None


class GaussianBlurOperation(Operation):

    def __init__(self):
        description = [
            { "name": _("Radius"), "property": "sigma", "type": "scalar", "default": 0.3 }
        ]
        super(GaussianBlurOperation, self).__init__(_("Gaussian Blur"), "gaussian-blur-operation", description)

    def get_processed_data_and_calibration(self, data_and_calibrations, values):
        data_and_metadata = Core.function_gaussian_blur(data_and_calibrations[0], values.get("sigma") * 10.0)
        return data_and_metadata if data_and_metadata else None


class MedianFilterOperation(Operation):

    def __init__(self):
        description = [
            { "name": _("Size"), "property": "size", "type": "integer-field", "default": 3 }
        ]
        super(MedianFilterOperation, self).__init__(_("Median Filter"), "median-filter-operation", description)

    def get_processed_data_and_calibration(self, data_and_calibrations, values):
        data_and_metadata = Core.function_median_filter(data_and_calibrations[0], values.get("size"))
        return data_and_metadata if data_and_metadata else None


class UniformFilterOperation(Operation):

    def __init__(self):
        description = [
            { "name": _("Size"), "property": "size", "type": "integer-field", "default": 3 }
        ]
        super(UniformFilterOperation, self).__init__(_("Uniform Filter"), "uniform-filter-operation", description)

    def get_processed_data_and_calibration(self, data_and_calibrations, values):
        data_and_metadata = Core.function_uniform_filter(data_and_calibrations[0], values.get("size"))
        return data_and_metadata if data_and_metadata else None


class TransposeFlipOperation(Operation):

    def __init__(self):
        description = [
            { "name": _("Transpose"), "property": "transpose", "type": "boolean-checkbox", "default": False },
            { "name": _("Flip Horizontal"), "property": "flip_horizontal", "type": "boolean-checkbox", "default": False },
            { "name": _("Flip Vertical"), "property": "flip_vertical", "type": "boolean-checkbox", "default": False }
        ]
        super(TransposeFlipOperation, self).__init__(_("Transpose/Flip"), "transpose-flip-operation", description)

    def get_processed_data_and_calibration(self, data_and_calibrations, values):
        data_and_metadata = Core.function_transpose_flip(data_and_calibrations[0], bool(values.get("transpose")), bool(values.get("flip_horizontal")), bool(values.get("flip_vertical")))
        return data_and_metadata if data_and_metadata else None


class Crop2dOperation(Operation):

    def __init__(self):
        description = [
            { "name": _("Bounds"), "property": "bounds", "type": "rectangle", "default": ((0.0, 0.0), (1.0, 1.0)) }
        ]
        super(Crop2dOperation, self).__init__(_("Crop"), "crop-operation", description)
        self.region_types = {"crop": "rectangle-region"}
        self.region_bindings = {"crop": [RegionBinding("bounds", "bounds")]}

    def get_processed_data_and_calibration(self, data_and_calibrations, values):
        data_and_metadata = Core.function_crop(data_and_calibrations[0], values.get("bounds"))
        return data_and_metadata if data_and_metadata else None


class Slice3dOperation(Operation):

    def __init__(self):
        description = [
            { "name": _("Slice Center"), "property": "slice_center", "type": "slice-center-field", "default": 0 },
            { "name": _("Slice Width"), "property": "slice_width", "type": "slice-width-field", "default": 1 }
        ]
        super(Slice3dOperation, self).__init__(_("Slice"), "slice-operation", description)

    def get_processed_data_and_calibration(self, data_and_calibrations, values):
        data_and_metadata = Core.function_slice_sum(data_and_calibrations[0], values.get("slice_center"), values.get("slice_width"))
        return data_and_metadata if data_and_metadata else None


class Pick3dOperation(Operation):

    def __init__(self):
        description = [
            { "name": _("Position"), "property": "position", "type": "point", "default": (0.5, 0.5) },
        ]
        super(Pick3dOperation, self).__init__(_("Pick"), "pick-operation", description)
        self.region_types = {"pick": "point-region"}
        self.region_bindings = {"pick": [RegionBinding("position", "position")]}

    def get_processed_data_and_calibration(self, data_and_calibrations, values):
        data_and_metadata = Core.function_pick(data_and_calibrations[0], values.get("position"))
        return data_and_metadata if data_and_metadata else None


class Projection2dOperation(Operation):

    def __init__(self):
        # hardcoded to axis 0 right now
        super(Projection2dOperation, self).__init__(_("Projection"), "projection-operation")

    def get_processed_data_and_calibration(self, data_and_calibrations, values):
        data_and_metadata = Core.function_project(data_and_calibrations[0])
        return data_and_metadata if data_and_metadata else None


class Resample2dOperation(Operation):

    def __init__(self):
        description = [
            {"name": _("Width"), "property": "width", "type": "integer-field", "default": None},
            {"name": _("Height"), "property": "height", "type": "integer-field", "default": None},
        ]
        super(Resample2dOperation, self).__init__(_("Resample"), "resample-operation", description)

    def get_processed_data_and_calibration(self, data_and_calibrations, values):
        dimensional_shape = data_and_calibrations[0].dimensional_shape
        if dimensional_shape and len(dimensional_shape) == 2:
            resample_shape = values.get("height", dimensional_shape[0]), values.get("width", dimensional_shape[1])
            data_and_metadata = Core.function_resample_2d(data_and_calibrations[0], resample_shape)
            return data_and_metadata if data_and_metadata else None
        else:
            return None

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

    def get_processed_data_and_calibration(self, data_and_calibrations, values):
        data_and_metadata = Core.function_histogram(data_and_calibrations[0], self.bins)
        return data_and_metadata if data_and_metadata else None


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

    def get_processed_data_and_calibration(self, data_and_calibrations, values):
        data_and_metadata = Core.function_line_profile(data_and_calibrations[0], values.get("vector"), values.get("integration_width"))
        return data_and_metadata if data_and_metadata else None


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


class NodeOperation(Operation):

    def __init__(self):
        super(NodeOperation, self).__init__(_("Computation"), "node-operation")

    def get_processed_data(self, data_sources, values):
        index_mapping = values.get("data_mapping")

        def resolve(uuid):
            return data_sources[index_mapping[str(uuid)]]  # data_sources are instances of DataAndMetadata

        data_node = Symbolic.DataNode.factory(values.get("data_node"))
        return data_node.evaluate(resolve).data


class OperationManager(metaclass=Utility.Singleton):

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
        self.__property_changed_listener = source.property_changed_event.listen(self.__property_changed)
        self.source_setter = lambda value: self.source.set_property(self.__property_name, value)
        self.source_getter = lambda: self.source.get_property(self.__property_name)
        # use this to know when a specific property changes
        self.__values = copy.copy(source.values)

    def close(self):
        self.__property_changed_listener.close()
        self.__property_changed_listener = None
        super(OperationPropertyBinding, self).close()

    # thread safe
    def __property_changed(self, property, property_value):
        if property == "values":
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
        self.__property_changed_listener = source.property_changed_event.listen(self.__property_changed)
        def validate_and_set(value):
            value = min(value, self.source.data_item.maybe_data_source.dimensional_shape[0])
            value = max(value, 0)
            self.source.set_property(self.__property_name, value)
        self.source_setter = validate_and_set
        self.source_getter = lambda: self.source.get_property(self.__property_name)
        # use this to know when a specific property changes
        self.__values = copy.copy(source.values)

    def close(self):
        self.__property_changed_listener.close()
        self.__property_changed_listener = None
        super(SliceOperationPropertyBinding, self).close()

    # thread safe
    def __property_changed(self, property, property_value):
        if property == "values":
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
        self.__property_changed_listener = region.property_changed_event.listen(self.__property_changed)
        self.__region_property_name = region_property_name
        self.__operation_property_name = operation_property_name
        self.target_setter = lambda value: setattr(self.__region, region_property_name, value)

    def close(self):
        self.__property_changed_listener.close()
        self.__property_changed_listener = None
        self.__region = None
        super(OperationPropertyToRegionBinding, self).close()

    # watch for property changes on the region.
    def __property_changed(self, property_name, property_value):
        if property_name == self.__region_property_name:
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
OperationManager().register_operation("node-operation", lambda: NodeOperation())


def operation_item_factory(lookup_id):
    return OperationItem(lookup_id("operation_id"))
