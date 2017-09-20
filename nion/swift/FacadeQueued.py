import threading


all_classes = {
    "API",
    "Application",
    "DataGroup",
    "DataItem",
    "Display",
    "DisplayPanel",
    "DocumentWindow",
    "Graphic",
    "HardwareSource",
    "Instrument",
    "Library"
}


def convert_to_facade(x, q):
    if isinstance(x, list):
        return [convert_to_facade(xx, q) for xx in x]
    if isinstance(x, tuple):
        return (convert_to_facade(xx, q) for xx in x)
    if isinstance(x, dict):
        return {k: convert_to_facade(v, q) for k, v in x.items()}
    class_name = x.__class__.__name__
    if class_name == "API_1":
        f = API(x, None)
        f._queue_task = q
        return f
    if class_name in all_classes:
        f = globals()[class_name](x, None)
        f._queue_task = q
        return f
    return x

def convert_from_facade(x):
    if isinstance(x, list):
        return [convert_from_facade(xx) for xx in x]
    if isinstance(x, tuple):
        return (convert_from_facade(xx) for xx in x)
    if isinstance(x, dict):
        return {k: convert_from_facade(v) for k, v in x.items()}
    class_name = x.__class__.__name__
    if class_name in all_classes:
        return getattr(x, "_proxy")
    return x

def queued(method):
    def queued(*args, **kwargs):
        result_ref = []
        exception_ref = []
        finished_event = threading.Event()
        target = args[0]
        def run():
            try:
                result_ref.append(convert_to_facade(method(*args, **kwargs), target._queue_task))
            except Exception as e:
                exception_ref.append(e)
            finally:
                finished_event.set()
        getattr(target, "_queue_task")(run)  # avoid type errors below
        finished_event.wait()
        if len(exception_ref) > 0:
            raise exception_ref[0]
        return result_ref[0]
    return queued

@queued
def call_method(target, method_name, *args, **kwargs):
    object = convert_from_facade(target)
    args = convert_from_facade(args)
    kwargs = convert_from_facade(kwargs)
    return getattr(object, method_name)(*args, **kwargs)

def call_threadsafe_method(target, method_name, *args, **kwargs):
    object = convert_from_facade(target)
    args = convert_from_facade(args)
    kwargs = convert_from_facade(kwargs)
    return getattr(object, method_name)(*args, **kwargs)

@queued
def get_property(target, property_name):
    return getattr(target._proxy, property_name)

@queued
def set_property(target, property_name, value):
    return setattr(target._proxy, property_name, value)

### the section below is copied from PlugIns/Connection/NionLib/nionlib/Classes.py


class Graphic:

    def __init__(self, proxy, specifier):
        self._proxy = proxy
        self.specifier = specifier

    def get_property(self, property):
        return call_method(self, 'get_property', property)

    def mask_xdata_with_shape(self, shape):
        return call_method(self, 'mask_xdata_with_shape', shape)

    def set_property(self, property, value):
        call_method(self, 'set_property', property, value)

    @property
    def angle(self):
        return get_property(self, 'angle')

    @angle.setter
    def angle(self, value):
        set_property(self, 'angle', value)

    @property
    def bounds(self):
        return get_property(self, 'bounds')

    @bounds.setter
    def bounds(self, value):
        set_property(self, 'bounds', value)

    @property
    def center(self):
        return get_property(self, 'center')

    @center.setter
    def center(self, value):
        set_property(self, 'center', value)

    @property
    def end(self):
        return get_property(self, 'end')

    @end.setter
    def end(self, value):
        set_property(self, 'end', value)

    @property
    def graphic_id(self):
        return get_property(self, 'graphic_id')

    @graphic_id.setter
    def graphic_id(self, value):
        set_property(self, 'graphic_id', value)

    @property
    def graphic_type(self):
        return get_property(self, 'graphic_type')

    @property
    def interval(self):
        return get_property(self, 'interval')

    @interval.setter
    def interval(self, value):
        set_property(self, 'interval', value)

    @property
    def label(self):
        return get_property(self, 'label')

    @label.setter
    def label(self, value):
        set_property(self, 'label', value)

    @property
    def position(self):
        return get_property(self, 'position')

    @position.setter
    def position(self, value):
        set_property(self, 'position', value)

    @property
    def region(self):
        return get_property(self, 'region')

    @property
    def size(self):
        return get_property(self, 'size')

    @size.setter
    def size(self, value):
        set_property(self, 'size', value)

    @property
    def start(self):
        return get_property(self, 'start')

    @start.setter
    def start(self, value):
        set_property(self, 'start', value)

    @property
    def type(self):
        return get_property(self, 'type')

    @property
    def uuid(self):
        return get_property(self, 'uuid')

    @property
    def vector(self):
        return get_property(self, 'vector')

    @vector.setter
    def vector(self, value):
        set_property(self, 'vector', value)


class DataItem:

    def __init__(self, proxy, specifier):
        self._proxy = proxy
        self.specifier = specifier

    def _repr_svg_(self):
        return call_method(self, 'data_item_to_svg')

    def add_channel_region(self, position):
        return call_method(self, 'add_channel_region', position)

    def add_ellipse_region(self, center_y, center_x, height, width):
        return call_method(self, 'add_ellipse_region', center_y, center_x, height, width)

    def add_interval_region(self, start, end):
        return call_method(self, 'add_interval_region', start, end)

    def add_line_region(self, start_y, start_x, end_y, end_x):
        return call_method(self, 'add_line_region', start_y, start_x, end_y, end_x)

    def add_point_region(self, y, x):
        return call_method(self, 'add_point_region', y, x)

    def add_rectangle_region(self, center_y, center_x, height, width):
        return call_method(self, 'add_rectangle_region', center_y, center_x, height, width)

    def delete_metadata_value(self, key):
        call_method(self, 'delete_metadata_value', key)

    def get_metadata_value(self, key):
        return call_method(self, 'get_metadata_value', key)

    def has_metadata_value(self, key):
        return call_method(self, 'has_metadata_value', key)

    def mask_xdata(self):
        return call_method(self, 'mask_xdata')

    def remove_region(self, graphic):
        call_method(self, 'remove_region', graphic)

    def set_data(self, data):
        call_method(self, 'set_data', data)

    def set_data_and_metadata(self, data_and_metadata):
        call_method(self, 'set_data_and_metadata', data_and_metadata)

    def set_dimensional_calibrations(self, dimensional_calibrations):
        call_method(self, 'set_dimensional_calibrations', dimensional_calibrations)

    def set_intensity_calibration(self, intensity_calibration):
        call_method(self, 'set_intensity_calibration', intensity_calibration)

    def set_metadata(self, metadata):
        call_method(self, 'set_metadata', metadata)

    def set_metadata_value(self, key, value):
        call_method(self, 'set_metadata_value', key, value)

    @property
    def created(self):
        return get_property(self, 'created')

    @property
    def data(self):
        return get_property(self, 'data')

    @data.setter
    def data(self, value):
        set_property(self, 'data', value)

    @property
    def data_and_metadata(self):
        return get_property(self, 'data_and_metadata')

    @property
    def dimensional_calibrations(self):
        return get_property(self, 'dimensional_calibrations')

    @property
    def display(self):
        return get_property(self, 'display')

    @property
    def display_xdata(self):
        return get_property(self, 'display_xdata')

    @property
    def graphics(self):
        return get_property(self, 'graphics')

    @property
    def intensity_calibration(self):
        return get_property(self, 'intensity_calibration')

    @property
    def metadata(self):
        return get_property(self, 'metadata')

    @property
    def modified(self):
        return get_property(self, 'modified')

    @property
    def regions(self):
        return get_property(self, 'regions')

    @property
    def title(self):
        return get_property(self, 'title')

    @title.setter
    def title(self, value):
        set_property(self, 'title', value)

    @property
    def uuid(self):
        return get_property(self, 'uuid')

    @property
    def xdata(self):
        return get_property(self, 'xdata')

    @xdata.setter
    def xdata(self, value):
        set_property(self, 'xdata', value)


class DisplayPanel:

    def __init__(self, proxy, specifier):
        self._proxy = proxy
        self.specifier = specifier

    def set_data_item(self, data_item):
        call_method(self, 'set_data_item', data_item)

    @property
    def data_item(self):
        return get_property(self, 'data_item')


class Display:

    def __init__(self, proxy, specifier):
        self._proxy = proxy
        self.specifier = specifier

    def get_graphic_by_id(self, graphic_id):
        return call_method(self, 'get_graphic_by_id', graphic_id)

    @property
    def data_item(self):
        return get_property(self, 'data_item')

    @property
    def display_type(self):
        return get_property(self, 'display_type')

    @display_type.setter
    def display_type(self, value):
        set_property(self, 'display_type', value)

    @property
    def graphics(self):
        return get_property(self, 'graphics')

    @property
    def selected_graphics(self):
        return get_property(self, 'selected_graphics')

    @property
    def uuid(self):
        return get_property(self, 'uuid')


class DataGroup:

    def __init__(self, proxy, specifier):
        self._proxy = proxy
        self.specifier = specifier

    def add_data_item(self, data_item):
        call_method(self, 'add_data_item', data_item)

    @property
    def uuid(self):
        return get_property(self, 'uuid')


class Library:

    def __init__(self, proxy, specifier):
        self._proxy = proxy
        self.specifier = specifier

    def copy_data_item(self, data_item):
        return call_method(self, 'copy_data_item', data_item)

    def create_data_item(self, title=None):
        return call_method(self, 'create_data_item', title=title)

    def create_data_item_from_data(self, data, title=None):
        return call_method(self, 'create_data_item_from_data', data, title=title)

    def create_data_item_from_data_and_metadata(self, data_and_metadata, title=None):
        return call_method(self, 'create_data_item_from_data_and_metadata', data_and_metadata, title=title)

    def data_ref_for_data_item(self, data_item):
        return call_method(self, 'data_ref_for_data_item', data_item)

    def delete_library_value(self, key):
        call_method(self, 'delete_library_value', key)

    def get_data_item_by_uuid(self, data_item_uuid):
        return call_method(self, 'get_data_item_by_uuid', data_item_uuid)

    def get_data_item_for_hardware_source(self, hardware_source, channel_id=None, processor_id=None, create_if_needed=False, large_format=False):
        return call_method(self, 'get_data_item_for_hardware_source', hardware_source, channel_id=channel_id, processor_id=processor_id, create_if_needed=create_if_needed, large_format=large_format)

    def get_dependent_data_items(self, data_item):
        return call_method(self, 'get_dependent_data_items', data_item)

    def get_graphic_by_uuid(self, graphic_uuid):
        return call_method(self, 'get_graphic_by_uuid', graphic_uuid)

    def get_library_value(self, key):
        return call_method(self, 'get_library_value', key)

    def get_or_create_data_group(self, title):
        return call_method(self, 'get_or_create_data_group', title)

    def get_source_data_items(self, data_item):
        return call_method(self, 'get_source_data_items', data_item)

    def has_library_value(self, key):
        return call_method(self, 'has_library_value', key)

    def set_library_value(self, key, value):
        call_method(self, 'set_library_value', key, value)

    def snapshot_data_item(self, data_item):
        return call_method(self, 'snapshot_data_item', data_item)

    @property
    def data_item_count(self):
        return get_property(self, 'data_item_count')

    @property
    def data_items(self):
        return get_property(self, 'data_items')

    @property
    def uuid(self):
        return get_property(self, 'uuid')


class DocumentWindow:

    def __init__(self, proxy, specifier):
        self._proxy = proxy
        self.specifier = specifier

    def add_data(self, data, title=None):
        return call_method(self, 'add_data', data, title=title)

    def create_data_item_from_data(self, data, title=None):
        return call_method(self, 'create_data_item_from_data', data, title=title)

    def create_data_item_from_data_and_metadata(self, data_and_metadata, title=None):
        return call_method(self, 'create_data_item_from_data_and_metadata', data_and_metadata, title=title)

    def display_data_item(self, data_item, source_display_panel=None, source_data_item=None):
        return call_method(self, 'display_data_item', data_item, source_display_panel=source_display_panel, source_data_item=source_data_item)

    def get_display_panel_by_id(self, identifier):
        return call_method(self, 'get_display_panel_by_id', identifier)

    def get_or_create_data_group(self, title):
        return call_method(self, 'get_or_create_data_group', title)

    def queue_task(self, fn):
        call_method(self, 'queue_task', fn)

    def show_confirmation_message_box(self, caption, accepted_fn, rejected_fn=None, accepted_text=None, rejected_text=None, display_rejected=False):
        call_method(self, 'show_confirmation_message_box', caption, accepted_fn, rejected_fn=rejected_fn, accepted_text=accepted_text, rejected_text=rejected_text, display_rejected=display_rejected)

    def show_get_string_message_box(self, caption, text, accepted_fn, rejected_fn=None, accepted_text=None, rejected_text=None):
        call_method(self, 'show_get_string_message_box', caption, text, accepted_fn, rejected_fn=rejected_fn, accepted_text=accepted_text, rejected_text=rejected_text)

    def show_modeless_dialog(self, item, handler=None):
        return call_method(self, 'show_modeless_dialog', item, handler=handler)

    @property
    def all_display_panels(self):
        return get_property(self, 'all_display_panels')

    @property
    def library(self):
        return get_property(self, 'library')

    @property
    def target_data_item(self):
        return get_property(self, 'target_data_item')

    @property
    def target_display(self):
        return get_property(self, 'target_display')


class Application:

    def __init__(self, proxy, specifier):
        self._proxy = proxy
        self.specifier = specifier

    @property
    def document_controllers(self):
        return get_property(self, 'document_controllers')

    @property
    def document_windows(self):
        return get_property(self, 'document_windows')

    @property
    def library(self):
        return get_property(self, 'library')


class API:

    def __init__(self, proxy, specifier):
        self._proxy = proxy
        self.specifier = specifier

    def create_calibration(self, offset=None, scale=None, units=None):
        return call_method(self, 'create_calibration', offset=offset, scale=scale, units=units)

    def create_data_and_metadata(self, data, intensity_calibration=None, dimensional_calibrations=None, metadata=None, timestamp=None, data_descriptor=None):
        return call_method(self, 'create_data_and_metadata', data, intensity_calibration=intensity_calibration, dimensional_calibrations=dimensional_calibrations, metadata=metadata, timestamp=timestamp, data_descriptor=data_descriptor)

    def create_data_and_metadata_from_data(self, data, intensity_calibration=None, dimensional_calibrations=None, metadata=None, timestamp=None):
        return call_method(self, 'create_data_and_metadata_from_data', data, intensity_calibration=intensity_calibration, dimensional_calibrations=dimensional_calibrations, metadata=metadata, timestamp=timestamp)

    def create_data_and_metadata_io_handler(self, io_handler_delegate):
        return call_method(self, 'create_data_and_metadata_io_handler', io_handler_delegate)

    def create_data_descriptor(self, is_sequence, collection_dimension_count, datum_dimension_count):
        return call_method(self, 'create_data_descriptor', is_sequence, collection_dimension_count, datum_dimension_count)

    def create_hardware_source(self, hardware_source_delegate):
        return call_method(self, 'create_hardware_source', hardware_source_delegate)

    def create_menu_item(self, menu_item_handler):
        return call_method(self, 'create_menu_item', menu_item_handler)

    def create_panel(self, panel_delegate):
        return call_method(self, 'create_panel', panel_delegate)

    def get_all_hardware_source_ids(self):
        return call_method(self, 'get_all_hardware_source_ids')

    def get_all_instrument_ids(self):
        return call_method(self, 'get_all_instrument_ids')

    def get_hardware_source_by_id(self, hardware_source_id, version):
        return call_method(self, 'get_hardware_source_by_id', hardware_source_id, version)

    def get_instrument_by_id(self, instrument_id, version):
        return call_method(self, 'get_instrument_by_id', instrument_id, version)

    def queue_task(self, fn):
        call_method(self, 'queue_task', fn)

    @property
    def application(self):
        return get_property(self, 'application')

    @property
    def library(self):
        return get_property(self, 'library')


class HardwareSource:

    def __init__(self, proxy, specifier):
        self._proxy = proxy
        self.specifier = specifier

    def abort_playing(self):
        call_method(self, 'abort_playing')

    def abort_recording(self):
        call_method(self, 'abort_recording')

    def close(self):
        call_method(self, 'close')

    def create_record_task(self, frame_parameters=None, channels_enabled=None):
        return call_method(self, 'create_record_task', frame_parameters=frame_parameters, channels_enabled=channels_enabled)

    def create_view_task(self, frame_parameters=None, channels_enabled=None, buffer_size=1):
        return call_method(self, 'create_view_task', frame_parameters=frame_parameters, channels_enabled=channels_enabled, buffer_size=buffer_size)

    def get_default_frame_parameters(self):
        return call_method(self, 'get_default_frame_parameters')

    def get_frame_parameters(self):
        return call_method(self, 'get_frame_parameters')

    def get_frame_parameters_for_profile_by_index(self, profile_index):
        return call_method(self, 'get_frame_parameters_for_profile_by_index', profile_index)

    def get_property_as_bool(self, name):
        return call_method(self, 'get_property_as_bool', name)

    def get_property_as_float(self, name):
        return call_method(self, 'get_property_as_float', name)

    def get_property_as_float_point(self, name):
        return call_method(self, 'get_property_as_float_point', name)

    def get_property_as_int(self, name):
        return call_method(self, 'get_property_as_int', name)

    def get_property_as_str(self, name):
        return call_method(self, 'get_property_as_str', name)

    def grab_next_to_finish(self, timeout=None):
        return call_threadsafe_method(self, 'grab_next_to_finish', timeout=timeout)

    def grab_next_to_start(self, frame_parameters=None, channels_enabled=None, timeout=None):
        return call_threadsafe_method(self, 'grab_next_to_start', frame_parameters=frame_parameters, channels_enabled=channels_enabled, timeout=timeout)

    def record(self, frame_parameters=None, channels_enabled=None, timeout=None):
        return call_threadsafe_method(self, 'record', frame_parameters=frame_parameters, channels_enabled=channels_enabled, timeout=timeout)

    def set_frame_parameters(self, frame_parameters):
        call_method(self, 'set_frame_parameters', frame_parameters)

    def set_frame_parameters_for_profile_by_index(self, profile_index, frame_parameters):
        call_method(self, 'set_frame_parameters_for_profile_by_index', profile_index, frame_parameters)

    def set_property_as_bool(self, name, value):
        call_threadsafe_method(self, 'set_property_as_bool', name, value)

    def set_property_as_float(self, name, value):
        call_threadsafe_method(self, 'set_property_as_float', name, value)

    def set_property_as_float_point(self, name, value):
        call_threadsafe_method(self, 'set_property_as_float_point', name, value)

    def set_property_as_int(self, name, value):
        call_threadsafe_method(self, 'set_property_as_int', name, value)

    def set_property_as_str(self, name, value):
        call_threadsafe_method(self, 'set_property_as_str', name, value)

    def start_playing(self, frame_parameters=None, channels_enabled=None):
        call_method(self, 'start_playing', frame_parameters=frame_parameters, channels_enabled=channels_enabled)

    def start_recording(self, frame_parameters=None, channels_enabled=None):
        return call_method(self, 'start_recording', frame_parameters=frame_parameters, channels_enabled=channels_enabled)

    def stop_playing(self):
        call_method(self, 'stop_playing')

    @property
    def is_playing(self):
        return get_property(self, 'is_playing')

    @property
    def is_recording(self):
        return get_property(self, 'is_recording')

    @property
    def profile_index(self):
        return get_property(self, 'profile_index')

    @profile_index.setter
    def profile_index(self, value):
        set_property(self, 'profile_index', value)


class Instrument:

    def __init__(self, proxy, specifier):
        self._proxy = proxy
        self.specifier = specifier

    def close(self):
        call_method(self, 'close')

    def get_control_output(self, name):
        return call_method(self, 'get_control_output', name)

    def get_control_state(self, name):
        return call_method(self, 'get_control_state', name)

    def get_property_as_bool(self, name):
        return call_method(self, 'get_property_as_bool', name)

    def get_property_as_float(self, name):
        return call_method(self, 'get_property_as_float', name)

    def get_property_as_float_point(self, name):
        return call_method(self, 'get_property_as_float_point', name)

    def get_property_as_int(self, name):
        return call_method(self, 'get_property_as_int', name)

    def get_property_as_str(self, name):
        return call_method(self, 'get_property_as_str', name)

    def set_control_output(self, name, value, *, options=None):
        call_method(self, 'set_control_output', name, value, options=options)

    def set_property_as_bool(self, name, value):
        call_method(self, 'set_property_as_bool', name, value)

    def set_property_as_float(self, name, value):
        call_method(self, 'set_property_as_float', name, value)

    def set_property_as_float_point(self, name, value):
        call_method(self, 'set_property_as_float_point', name, value)

    def set_property_as_int(self, name, value):
        call_method(self, 'set_property_as_int', name, value)

    def set_property_as_str(self, name, value):
        call_method(self, 'set_property_as_str', name, value)
