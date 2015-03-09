"""
    A versioned interface to Swift.

    on_xyz methods are used when a callback needs a return value and has only a single listener.

    events are used when a callback is optional and may have multiple listeners.

    Versions numbering follows semantic version numbering: http://semver.org/
"""

# standard libraries
import datetime
import gettext

# third party libraries
# None

# local libraries
from nion.swift.model import Calibration
from nion.swift.model import DataItem
from nion.swift.model import HardwareSource
from nion.swift.model import Image
from nion.swift.model import ImportExportManager
from nion.swift.model import PlugInManager
from nion.swift.model import Operation
from nion.swift.model import Region
from nion.swift.model import Utility
from nion.swift import Application
from nion.swift import Panel
from nion.swift import Workspace
from nion.ui import CanvasItem
from nion.ui import Geometry


__all__ = ["get_api"]


_ = gettext.gettext


class FacadeCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self):
        super(FacadeCanvasItem, self).__init__()
        self.on_repaint = None

    def _repaint(self, drawing_context):
        if self.on_repaint:
            self.on_repaint(drawing_context, Geometry.IntSize.make(self.canvas_size))


class FacadeRootCanvasItem(CanvasItem.RootCanvasItem):

    def __init__(self, ui, canvas_item, properties):
        super(FacadeRootCanvasItem, self).__init__(ui, properties)
        self.__canvas_item = canvas_item

    @property
    def _widget(self):
        return self.canvas_widget

    @property
    def on_repaint(self):
        return self.__canvas_item.on_repaint

    @on_repaint.setter
    def on_repaint(self, value):
        self.__canvas_item.on_repaint = value


class FacadeColumnWidget(object):

    def __init__(self, ui):
        self.__ui = ui
        self.__column_widget = self.__ui.create_column_widget()

    @property
    def _widget(self):
        return self.__column_widget

    def add_spacing(self, spacing):
        self.__column_widget.add_spacing(spacing)

    def add_stretch(self):
        self.__column_widget.add_stretch()

    def add(self, widget):
        self.__column_widget.add(widget._widget)


class FacadeRowWidget(object):

    def __init__(self, ui):
        self.__ui = ui
        self.__row_widget = self.__ui.create_row_widget()

    @property
    def _widget(self):
        return self.__row_widget

    def add_spacing(self, spacing):
        self.__row_widget.add_spacing(spacing)

    def add_stretch(self):
        self.__row_widget.add_stretch()

    def add(self, widget):
        self.__row_widget.add(widget._widget)


class FacadeLabelWidget(object):

    def __init__(self, ui):
        self.__ui = ui
        self.__label_widget = self.__ui.create_label_widget()

    @property
    def _widget(self):
        return self.__label_widget

    @property
    def text(self):
        return self.__label_widget.text

    @text.setter
    def text(self, value):
        self.__label_widget.text = value


class FacadeLineEditWidget(object):

    def __init__(self, ui):
        self.__ui = ui
        self.__line_edit_widget = self.__ui.create_line_edit_widget()

    @property
    def _widget(self):
        return self.__line_edit_widget

    @property
    def text(self):
        return self.__line_edit_widget.text

    @text.setter
    def text(self, value):
        self.__line_edit_widget.text = value

    @property
    def on_editing_finished(self):
        return self.__line_edit_widget.on_editing_finished

    @on_editing_finished.setter
    def on_editing_finished(self, value):
        self.__line_edit_widget.on_editing_finished = value

    def select_all(self):
        self.__line_edit_widget.select_all()


class FacadePushButtonWidget(object):

    def __init__(self, ui):
        self.__ui = ui
        self.__push_button_widget = self.__ui.create_push_button_widget()

    @property
    def _widget(self):
        return self.__push_button_widget

    @property
    def text(self):
        return self.__push_button_widget.text

    @text.setter
    def text(self, value):
        self.__push_button_widget.text = value

    @property
    def on_clicked(self):
        return self.__push_button_widget.on_clicked

    @on_clicked.setter
    def on_clicked(self, value):
        self.__push_button_widget.on_clicked = value


class FacadeUserInterface(object):

    def __init__(self, ui_version, ui):
        actual_version = "1.0.0"
        if Utility.compare_versions(ui_version, actual_version) > 0:
            raise NotImplementedError("UI API requested version %s is greater than %s." % (ui_version, actual_version))
        self.__ui = ui

    def create_canvas_widget(self, height=None):
        properties = dict()
        if height is not None:
            properties["min-height"] = height
            properties["max-height"] = height
        canvas_item = FacadeCanvasItem()
        root_canvas_item = FacadeRootCanvasItem(self.__ui, canvas_item, properties=properties)
        root_canvas_item.add_canvas_item(canvas_item)
        return root_canvas_item

    def create_column_widget(self):
        return FacadeColumnWidget(self.__ui)

    def create_row_widget(self):
        return FacadeRowWidget(self.__ui)

    def create_label_widget(self, text=None):
        label_widget = FacadeLabelWidget(self.__ui)
        label_widget.text = text
        return label_widget

    def create_line_edit_widget(self, text=None):
        line_edit_widget = FacadeLineEditWidget(self.__ui)
        line_edit_widget.text = text
        return line_edit_widget

    def create_push_button_widget(self, text=None):
        push_button_widget = FacadePushButtonWidget(self.__ui)
        push_button_widget.text = text
        return push_button_widget


class FacadePanel(Panel.Panel):

    def __init__(self, document_controller, panel_id, properties):
        super(FacadePanel, self).__init__(document_controller, panel_id, panel_id)
        self.on_close = None

    def close(self):
        if self.on_close:
            self.on_close()


class FacadeRegion(object):

    def __init__(self, region):
        self.__region = region

    @property
    def _region(self):
        return self.__region

    @property
    def type(self):
        return self.__region.type

    @property
    def label(self):
        return self.__region.label

    @label.setter
    def label(self, value):
        self.__region.label = value

    def get_property(self, property):
        return getattr(self.__region, property)

    def set_property(self, property, value):
        setattr(self.__region, property, value)

    # position, start, end, vector, center, size, bounds, angle


class FacadeDataItem(object):

    def __init__(self, data_item):
        self.__data_item = data_item

    @property
    def _data_item(self):
        return self.__data_item

    @property
    def data(self):
        return self.__data_item.maybe_data_source.data_and_metadata.data

    @property
    def data_and_metadata(self):
        return self.__data_item.maybe_data_source.data_and_metadata

    @property
    def regions(self):
        return [FacadeRegion(region) for region in self.__data_item.maybe_data_source.regions]

    def add_point_region(self, y, x):
        region = Region.PointRegion()
        region.position = Geometry.FloatPoint(y, x)
        self.__data_item.maybe_data_source.add_region(region)
        return FacadeRegion(region)

    def add_rectangle_region(self, center_y, center_x, height, width):
        region = Region.RectRegion()
        region.center = Geometry.FloatPoint(center_y, center_x)
        region.size = Geometry.FloatSize(height, width)
        self.__data_item.maybe_data_source.add_region(region)
        return FacadeRegion(region)

    def add_ellipse_region(self, center_y, center_x, height, width):
        region = Region.EllipseRegion()
        region.center = Geometry.FloatPoint(center_y, center_x)
        region.size = Geometry.FloatSize(height, width)
        self.__data_item.maybe_data_source.add_region(region)
        return FacadeRegion(region)

    def add_line_region(self, start_y, start_x, end_y, end_x):
        region = Region.LineRegion()
        region.start = Geometry.FloatPoint(start_y, start_x)
        region.end = Geometry.FloatPoint(end_y, end_x)
        self.__data_item.maybe_data_source.add_region(region)
        return FacadeRegion(region)

    def add_interval_region(self, start, end):
        region = Region.IntervalRegion()
        region.start = start
        region.end = end
        self.__data_item.maybe_data_source.add_region(region)
        return FacadeRegion(region)

    def remove_region(self, region):
        self.__data_item.maybe_data_source.remove_region(region._region)


class FacadeDisplayPanel(object):

    def __init__(self):
        pass

    @property
    def display(self):
        raise AttributeError()


class FacadeDisplay(object):

    def __init__(self):
        pass

    @property
    def data_item(self):
        raise AttributeError()

    @property
    def data_item_list(self):
        raise AttributeError()


class FacadeDataGroup(object):

    def __init__(self, data_group):
        self.__data_group = data_group

    def add_data_item(self, data_item):
        self.__data_group.append_data_item(data_item._data_item)

    def remove_data_item(self, data_item):
        raise NotImplementedError()

    def remove_all_data_items(self):
        raise NotImplementedError()

    @property
    def data_items(self):
        raise AttributeError()


class FacadeMonitor(object):

    def __init__(self):
        self.on_data_and_metadata_list_available = None  # frame_index, data_and_metadata_list, frame_parameters
        self.on_start_playing = None
        self.on_stop_playing = None
        self.on_start_recording = None
        self.on_stop_recording = None

    def close(self):
        pass


class FacadeRecordTask(object):

    def __init__(self):
        pass

    def close(self):
        pass

    def grab(self):
        pass

    def cancel(self):
        pass


class FacadeViewTask(object):

    def __init__(self, hardware_source):
        self.__hardware_source = hardware_source
        self.__was_playing = self.__hardware_source.is_playing
        if not self.__was_playing:
            self.__hardware_source.start_playing()
        self.on_will_start_frame = None  # prepare the hardware here
        self.on_did_finish_frame = None  # restore the hardware here, modify the data_and_metadata here

    def close(self):
        if not self.__was_playing:
            self.__hardware_source.stop_playing()

    def grab_immediate(self):
        return self.grab_next_to_finish()

    def grab_next_to_finish(self):
        data_elements = self.__hardware_source.get_next_data_elements_to_finish()
        return [HardwareSource.convert_data_element_to_data_and_metadata(data_element) for data_element in data_elements]

    def grab_next_to_start(self):
        data_elements = self.__hardware_source.get_next_data_elements_to_start()
        return [HardwareSource.convert_data_element_to_data_and_metadata(data_element) for data_element in data_elements]


class FacadeHardwareSource(object):

    def __init__(self, hardware_source):
        self.__hardware_source = hardware_source

    def create_monitor(self):
        pass

    def start_playing(self):
        self.__hardware_source.start_playing()

    def create_record_task(self, frame_parameters=None, start=True):
        pass

    def create_view_task(self, frame_parameters=None, priority=None, start=True):
        """Create a view task for this hardware source.

        :param frame_parameters: The frame parameters for the view. Pass None for defaults.
        :type frame_parameters: :py:class:`FrameParameters`
        :param priority: Pass None for low priority. Pass 1 for high priority.
        :param start: A boolean indicating whether to immediately start the view.

        Callers should call close on task when finished.

        See :py:class:`ViewTask` for examples of how to use.
        """
        assert frame_parameters is None
        assert priority is None
        assert start is True
        return FacadeViewTask(self.__hardware_source)

    def get_frame_info(self, data_and_metadata):
        pass


class FacadeDocumentController(object):

    def __init__(self, document_controller):
        self.__document_controller = document_controller

    @property
    def _document_controller(self):
        return self.__document_controller

    def add_data(self, data, title=None):
        return self.create_data_item_from_data(data, title)

    @property
    def target_display_panel(self):
        raise AttributeError()

    @property
    def target_display(self):
        raise AttributeError()

    @property
    def target_data_item(self):
        return FacadeDataItem(self.__document_controller.selected_display_specifier.data_item)

    def create_data_item_from_data(self, data, title=None):
        return FacadeDataItem(self.__document_controller.add_data(data, title))

    def create_data_item_from_data_and_metadata(self, data_and_calibration, title=None):
        data_item = DataItem.DataItem()
        if title is not None:
            data_item.title = title
        buffered_data_source = DataItem.BufferedDataSource(data_and_calibration.data)
        buffered_data_source.set_metadata(data_and_calibration.metadata)
        buffered_data_source.set_intensity_calibration(data_and_calibration.intensity_calibration)
        buffered_data_source.set_dimensional_calibrations(data_and_calibration.dimensional_calibrations)
        buffered_data_source.created = data_and_calibration.timestamp
        data_item.append_data_source(buffered_data_source)
        self.__document_controller.document_model.append_data_item(data_item)
        return FacadeDataItem(data_item)

    def create_task_context_manager(self, title, task_type):
        return self.__document_controller.create_task_context_manager(title, task_type)

    def get_or_create_data_group(self, title):
        return FacadeDataGroup(self.__document_controller.document_model.get_or_create_data_group(title))

    def queue_task(self, fn):
        self.__document_controller.queue_task(fn)

    """
    data_item = document_controller.create_data_item_from_data(some_data)
    data_item2 = document_controller.create_data_item_from_data_node(DataNode.make(data_item) * 3)
    document_controller.add_data_node_to_data_item(data_item, DataNode.make(data_item2) / 3)
    document_controller.add_operation_to_data_item(data_item, "crop-operation", { "bounds": rect })
    """

class DataAndMetadataIOHandlerInterface(object):
    """An interface for an IO handler delegate. Implement each of the methods and properties, as required."""

    @property
    def io_hander_name(self):
        """Name of the IO handler. This will appear to the user.

        :rtype: str

        .. versionadded:: 1.0
        """
        raise AttributeError()

    @property
    def io_handler_extensions(self):
        """List of extensions handled by the IO handler.

        :rtype: list of str

        .. versionadded:: 1.0
        """
        raise AttributeError()

    def read_data_and_metadata(self, extension, file_path):
        """Read data from the file_path and return it in a data_and_metadata object.

        .. versionadded:: 1.0

        :param extension: The extension of the file_path, e.g. "tif".
        :param file_path: The path to the file.
        :return: The data and metadata that was read.
        :rtype: :py:class:`DataAndMetadata`
        """
        raise NotImplementedError()

    def can_write_data_and_metadata(self, data_and_metadata, extension):
        """Return whether the data_and_metadata can be written to a file with the given extension.

        .. versionadded:: 1.0

        :param data_and_metadata: The data to write.
        :type data_and_metadata: :py:class:`DataAndMetadata`
        :param extension: The extension of the file, e.g. "tif".
        :return: Whether the file can be written.
        :rtype: boolean

        Implementers should not ask for data from the data_and_metadata object as this may affect performance.
        """
        raise NotImplementedError()

    def write_data_and_metadata(self, data_and_calibration, file_path, extension):
        """Write the data_and_metadata to the file_path with the given extension.

        .. versionadded:: 1.0

        :param data_and_metadata: A :py:class:`DataAndCalibration` object.
        :param file_path: The path to the file.
        :param extension: The extension of the file, e.g. "tif".
        """
        raise NotImplementedError()


class API_1(object):
    """An interface to Nion Swift.

    This should not be instantiated directly. Use Facade.get_api(version) instead.
    """

    # GOALS
    # Provide an API for any plug-in available
    # Provide an API for anything the user can do
    # Provide programmatic access for creating new extensions

    # RULES
    # clients should not be required to directly instantiate or subclass any classes
    # versions should be passed wherever a sub-system might be versioned separately

    # NAMING
    # add, insert, remove (not append)

    # MIGRATING
    # Allowed: add keyword arguments to end of existing methods as long as the default doesn't change functionality.
    # Allowed: add methods as long as they are optional.

    def __init__(self, ui_version):
        super(API_1, self).__init__()
        self.__ui_version = ui_version

    def create_calibration(self, offset=None, scale=None, units=None):
        """Create a calibration object with offset, scale, and units.

        .. versionadded:: 1.0

        :param offset: The offset of the calibration.
        :param scale: The scale of the calibration.
        :param units: The units of the calibration as a string.
        :return: The calibration object.
        """
        return Calibration.Calibration(offset, scale, units)

    def create_data_and_metadata_from_data(self, data, intensity_calibration=None, dimensional_calibrations=None, metadata=None, timestamp=None):
        """Create a data_and_metadata object from data.

        .. versionadded:: 1.0

        :param data: an ndarray of data.
        :param intensity_calibration: An optional calibration object.
        :param dimensional_calibrations: An optional list of calibration objects.
        :param metadata: A dict of metadata.
        :param timestamp: A datetime object.
        """
        data_shape_and_dtype = Image.spatial_shape_from_data(data), data.dtype
        if intensity_calibration is None:
            intensity_calibration = Calibration.Calibration()
        if dimensional_calibrations is None:
            dimensional_calibrations = list()
            for _ in data_shape_and_dtype[0]:
                dimensional_calibrations.append(Calibration.Calibration())
        if metadata is None:
            metadata = dict()
        timestamp = timestamp if timestamp else datetime.datetime.utcnow()
        return Operation.DataAndCalibration(lambda: data, data_shape_and_dtype, intensity_calibration, dimensional_calibrations, metadata, timestamp)

    def create_data_and_metadata_io_handler(self, io_handler_delegate):
        """Create an I/O handler that reads and writes a single data_and_metadata.

        .. versionadded:: 1.0

        :param io_handler_delegate: A delegate object :py:class:`DataAndMetadataIOHandlerInterface`
        """
        class DelegateIOHandler(ImportExportManager.ImportExportHandler):
            def __init__(self):
                super(DelegateIOHandler, self).__init__(io_handler_delegate.io_handler_name, io_handler_delegate.io_handler_extensions)

            def read_data_elements(self, ui, extension, file_path):
                data_and_calibration = io_handler_delegate.read_data_and_metadata(extension, file_path)
                data_element = dict()
                data_element["data"] = data_and_calibration.data
                dimensional_calibrations = list()
                for calibration in data_and_calibration.dimensional_calibrations:
                    dimensional_calibrations.append({ "offset": calibration.offset, "scale": calibration.scale, "units": calibration.units })
                data_element["spatial_calibrations"] = dimensional_calibrations
                calibration = data_and_calibration.intensity_calibration
                data_element["intensity_calibration"] = { "offset": calibration.offset, "scale": calibration.scale, "units": calibration.units }
                data_element["properties"] = data_and_calibration.metadata.get("hardware_source", dict())
                return [data_element]

            def can_write(self, data_item, extension):
                return data_item.maybe_data_source and io_handler_delegate.can_write_data_and_metadata(data_item.maybe_data_source.data_and_calibration, extension)

            def write(self, ui, data_item, file_path, extension):
                data_and_calibration = data_item.maybe_data_source.data_and_calibration
                data = data_and_calibration.data
                if data is not None:
                    io_handler_delegate.write_data_and_metadata(data_and_calibration, file_path, extension)

        class IOHandlerReference(object):

            def __init__(self):
                self.__io_handler_delegate = io_handler_delegate
                self.__io_handler = DelegateIOHandler()
                ImportExportManager.ImportExportManager().register_io_handler(self.__io_handler)

            def __del__(self):
                self.close()

            def close(self):
                if self.__io_handler_delegate:
                    io_handler_delegate_close_fn = getattr(self.__io_handler_delegate, "close", None)
                    if io_handler_delegate_close_fn:
                       io_handler_delegate_close_fn()
                    ImportExportManager.ImportExportManager().unregister_io_handler(self.__io_handler)
                    self.__io_handler_delegate = None

        return IOHandlerReference()

    def create_menu_item(self, menu_item_handler):

        # the build_menus function will be called whenever a new document window is created.
        # it will be passed the document_controller.
        def build_menus(document_controller):
            menu_id = getattr(menu_item_handler, "menu_id", None)
            if menu_id is None:
                menu_id = "script_menu"
                menu_name = _("Scripts")
                menu_before_id = "window_menu"
            else:
                menu_name = getattr(menu_item_handler, "menu_name", None)
                menu_before_id = getattr(menu_item_handler, "menu_before_id", None)
            if menu_name is not None and menu_before_id is not None:
                menu = document_controller.get_or_create_menu(menu_id, menu_name, menu_before_id)
            else:
                menu = document_controller.get_menu(menu_id)
            key_sequence = getattr(menu_item_handler, "menu_item_key_sequence", None)
            if menu:
                facade_document_controller = FacadeDocumentController(document_controller)
                menu.add_menu_item(menu_item_handler.menu_item_name, lambda: menu_item_handler.menu_item_execute(
                    facade_document_controller), key_sequence=key_sequence)

        class MenuItemReference(object):

            def __init__(self):
                self.__menu_item_handler = menu_item_handler
                Application.app.register_menu_handler(build_menus)

            def __del__(self):
                self.close()

            def close(self):
                if self.__menu_item_handler:
                    menu_item_handler_close_fn = getattr(self.__menu_item_handler, "close", None)
                    if menu_item_handler_close_fn:
                       menu_item_handler_close_fn()
                    Application.app.unregister_menu_handler(build_menus)
                    self.__menu_item_handler = None

        return MenuItemReference()


    def create_hardware_source(self, hardware_source_delegate):

        class FacadeHardwareSource(HardwareSource.HardwareSource):

            def __init__(self):
                super(FacadeHardwareSource, self).__init__(hardware_source_delegate.hardware_source_id, hardware_source_delegate.hardware_source_name)

            def start_acquisition(self):
                hardware_source_delegate.start_acquisition()

            def acquire_data_elements(self):
                data_and_calibration = hardware_source_delegate.acquire_data_and_metadata()
                data_element = {
                    "version": 1,
                    "data": data_and_calibration.data,
                    "properties": {
                        "hardware_source_name": hardware_source_delegate.hardware_source_name,
                        "hardware_source_id": hardware_source_delegate.hardware_source_id,
                    }
                }
                return [data_element]

            def stop_acquisition(self):
                hardware_source_delegate.stop_acquisition()

        class HardwareSourceReference(object):

            def __init__(self):
                self.__hardware_source_delegate = hardware_source_delegate
                self.__hardware_source = FacadeHardwareSource()
                HardwareSource.HardwareSourceManager().register_hardware_source(self.__hardware_source)

            def __del__(self):
                self.close()

            def close(self):
                if self.__hardware_source_delegate:
                    hardware_source_delegate_close_fn = getattr(self.__hardware_source_delegate, "close", None)
                    if hardware_source_delegate_close_fn:
                       hardware_source_delegate_close_fn()
                    HardwareSource.HardwareSourceManager().unregister_hardware_source(self.__hardware_source)
                    self.__hardware_source_delegate = None

        return HardwareSourceReference()

    def create_panel(self, panel_delegate):
        """Create a utility panel that can be attached to a window.

        .. versionadded:: 1.0

         The panel_delegate should respond to the following:
            (property, read-only) panel_id
            (property, read-only) panel_name
            (property, read-only) panel_positions (a list from "top", "bottom", "left", "right", "all")
            (property, read-only) panel_position (from "top", "bottom", "left", "right", "none")
            (method, required) create_panel_widget(ui), returns a widget
            (method, optional) close()
        """

        panel_id = panel_delegate.panel_id
        panel_name = panel_delegate.panel_name
        panel_positions = getattr(panel_delegate, "panel_positions", ["left", "right"])
        panel_position = getattr(panel_delegate, "panel_position", "none")
        properties = getattr(panel_delegate, "panel_properties", None)

        workspace_manager = Workspace.WorkspaceManager()

        def create_facade_panel(document_controller, panel_id, properties):
            panel = FacadePanel(document_controller, panel_id, properties)
            ui = FacadeUserInterface(self.__ui_version, document_controller.ui)
            document_controller = FacadeDocumentController(document_controller)
            panel.widget = panel_delegate.create_panel_widget(ui, document_controller)._widget
            return panel

        class PanelReference(object):

            def __init__(self):
                self.__panel_delegate = panel_delegate
                workspace_manager.register_panel(create_facade_panel, panel_id, panel_name, panel_positions, panel_position, properties)

            def __del__(self):
                self.close()

            def close(self):
                if self.__panel_delegate:
                    panel_delegate_close_fn = getattr(self.__panel_delegate, "close", None)
                    if panel_delegate_close_fn:
                       panel_delegate_close_fn()
                    workspace_manager.unregister_panel(panel_id)
                    self.__panel_delegate = None

        return PanelReference()

    def create_unary_operation(self, unary_operation_delegate):

        class DelegateOperation(Operation.Operation):
            def __init__(self):
                super(DelegateOperation, self).__init__(unary_operation_delegate.operation_name, unary_operation_delegate.operation_id, unary_operation_delegate.operation_description)
                self.region_types = dict()
                self.region_bindings = dict()
                operation_region_bindings = getattr(unary_operation_delegate, "operation_region_bindings", dict())
                for operation_region_id, binding_description in operation_region_bindings.iteritems():
                    self.region_types[operation_region_id] = binding_description["type"]
                    for binding in binding_description["bindings"]:
                        for from_key, to_key in binding.iteritems():
                            self.region_bindings[operation_region_id] = [Operation.RegionBinding(from_key, to_key)]

            def get_processed_data_and_calibration(self, data_and_calibrations, values):
                # doesn't do any bounds checking
                return unary_operation_delegate.get_processed_data_and_metadata(data_and_calibrations[0], values)

        def apply_operation(document_controller):
            display_specifier = document_controller.selected_display_specifier
            buffered_data_source = display_specifier.buffered_data_source if display_specifier else None
            data_and_metadata = buffered_data_source.data_and_calibration if buffered_data_source else None
            if data_and_metadata and unary_operation_delegate.can_apply_to_data(data_and_metadata):
                operation = Operation.OperationItem(unary_operation_delegate.operation_id)
                for operation_region_id in getattr(unary_operation_delegate, "operation_region_bindings", dict()).keys():
                    operation.establish_associated_region(operation_region_id, buffered_data_source)
                return document_controller.add_processing_operation(display_specifier.buffered_data_source_specifier, operation, prefix=unary_operation_delegate.operation_prefix)
            return DataItem.DisplaySpecifier()

        def build_menus(document_controller):
            """ Make menu item for this operation. """
            document_controller.processing_menu.add_menu_item(unary_operation_delegate.operation_name, lambda: apply_operation(document_controller))

        class OperationReference(object):

            def __init__(self):
                self.__unary_operation_delegate = unary_operation_delegate
                Operation.OperationManager().register_operation(unary_operation_delegate.operation_id, lambda: DelegateOperation())
                Application.app.register_menu_handler(build_menus) # called on import to make the menu entry for this plugin

            def __del__(self):
                self.close()

            def close(self):
                if self.__unary_operation_delegate:
                    unary_operation_delegate_close_fn = getattr(self.__unary_operation_delegate, "close", None)
                    if unary_operation_delegate_close_fn:
                       unary_operation_delegate_close_fn()
                    Operation.OperationManager().unregister_operation(unary_operation_delegate.operation_id)
                    Application.app.unregister_menu_handler(build_menus)
                    self.__unary_operation_delegate = None

        return OperationReference()

    def get_hardware_source_by_id(self, hardware_source_id, version):
        # TODO: Handle how this returns an actual API.
        return FacadeHardwareSource(HardwareSource.HardwareSourceManager().get_hardware_source_for_hardware_source_id(hardware_source_id))

    def raise_requirements_exception(self, reason):
        raise PlugInManager.RequirementsException(reason)


def get_api(version, ui_version):
    """Get a versioned interface matching the given version and ui_version.

    version is a string in the form "1.0.2".
    """
    actual_version = "1.0.0"
    if Utility.compare_versions(version, actual_version) > 0:
        raise NotImplementedError("API requested version %s is greater than %s." % (version, actual_version))
    return API_1(ui_version)


# this will be called when Facade is imported. this allows the plug-in manager access to the api_broker.
# for this to work, Facade must be imported early in the startup process.
def initialize():
    PlugInManager.register_api_broker_fn(get_api)


# TODO: facade panels never get closed
