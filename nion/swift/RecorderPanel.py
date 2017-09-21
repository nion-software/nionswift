# standard libraries
import gettext
import numpy
import time

# third party libraries
# None

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.ui import Dialog
from nion.utils import Binding
from nion.utils import Converter
from nion.utils import Geometry
from nion.utils import Model
from nion.swift import DataItemThumbnailWidget
from nion.swift.model import DataItem

_ = gettext.gettext


class RecorderDialog(Dialog.ActionDialog):

    def __init__(self, document_controller, data_item):
        ui = document_controller.ui
        super().__init__(ui, _("Recorder"), app=document_controller.app, parent_window=document_controller, persistent_id="Recorder" + str(data_item.uuid))

        self.ui = ui
        self.document_controller = document_controller

        self.__data_item = data_item

        self._create_menus()

        self.__record_button = ui.create_push_button_widget(_("Record"))

        def thumbnail_widget_drag(mime_data, thumbnail, hot_spot_x, hot_spot_y):
            # use this convoluted base object for drag so that it doesn't disappear after the drag.
            self.content.drag(mime_data, thumbnail, hot_spot_x, hot_spot_y)

        data_item_thumbnail_source = DataItemThumbnailWidget.DataItemThumbnailSource(ui, data_item)
        data_item_chooser_widget = DataItemThumbnailWidget.DataItemThumbnailWidget(ui, data_item_thumbnail_source, Geometry.IntSize(48, 48))
        data_item_chooser_widget.on_drag = thumbnail_widget_drag

        self.__recording_interval_property = Model.PropertyModel(1000)
        self.__recording_count_property = Model.PropertyModel(20)

        recording_period_widget = ui.create_line_edit_widget(properties={"width": 60})
        recording_period_widget.bind_text(Binding.PropertyBinding(self.__recording_interval_property, "value", converter=Converter.IntegerToStringConverter()))

        recording_count_widget = ui.create_line_edit_widget(properties={"width": 60})
        recording_count_widget.bind_text(Binding.PropertyBinding(self.__recording_count_property, "value", converter=Converter.IntegerToStringConverter()))

        row0 = ui.create_row_widget()
        row0.add_stretch()
        row0.add_spacing(8)
        row0.add(self.__record_button)
        row0.add_spacing(8)

        row1 = ui.create_row_widget()
        row1.add(ui.create_label_widget(_("Interval")))
        row1.add_spacing(8)
        row1.add(recording_period_widget)
        row1.add_spacing(4)
        row1.add(ui.create_label_widget(_("msec")))
        row1.add_spacing(8)
        row1.add_stretch()

        row2 = ui.create_row_widget()
        row2.add(ui.create_label_widget(_("Frames")))
        row2.add_spacing(8)
        row2.add(recording_count_widget)
        row2.add_spacing(8)
        row2.add_stretch()

        column1 = ui.create_column_widget()
        column1.add(row1)
        column1.add_spacing(4)
        column1.add(row2)
        column1.add_spacing(4)
        column1.add(row0)

        button_row = ui.create_row_widget()
        button_row.add_spacing(8)
        button_row.add(data_item_chooser_widget)
        button_row.add_spacing(8)
        button_row.add_stretch()
        button_row.add_spacing(8)
        button_row.add(column1)
        button_row.add_spacing(8)

        self.__recording_state = "stopped"
        self.__recording_last = 0.0
        self.__recording_index = 0
        self.__recording_data_item = None
        self.__recording_transacted = False

        self.__recording_interval = self.__recording_interval_property.value / 1000
        self.__recording_count = self.__recording_count_property.value

        def record_pressed():
            if self.__recording_state == "recording":
                self.__stop_recording()
            else:
                self.__begin_recording()

        self.__record_button.on_clicked = record_pressed

        column = self.content
        column.add_spacing(6)
        column.add(button_row)
        column.add_spacing(6)

        def data_item_content_changed():
            is_live = data_item.is_live
            self.__record_button.enabled = is_live
            if not is_live:
                self.__stop_recording()

        def data_item_deleted(data_item):
            if data_item == self.__recording_data_item:
                self.__stop_recording()
            if data_item == self.__data_item:
                self.__stop_recording()
                self.request_close()

        self.__data_item_content_changed_event_listener = data_item.data_item_content_changed_event.listen(data_item_content_changed)
        self.__data_item_deleted_event_listener = self.document_controller.document_model.data_item_deleted_event.listen(data_item_deleted)

        data_item_content_changed()

    def close(self):
        self.__data_item_content_changed_event_listener.close()
        self.__data_item_content_changed_event_listener = None
        self.__data_item_deleted_event_listener.close()
        self.__data_item_deleted_event_listener = None
        super().close()

    def periodic(self):
        super().periodic()
        if self.__recording_state == "recording":
            current_time = time.time()
            if current_time - self.__recording_last > self.__recording_interval:
                self.__recording_last = current_time
                # first create an empty data item to hold the recorded data if it doesn't already exist
                if not self.__recording_data_item:
                    data_item = DataItem.DataItem(large_format=True)
                    data_item.ensure_data_source()
                    data_item.title = _("Recording of ") + self.__data_item.title
                    self.document_controller.document_model.append_data_item(data_item)
                    self.__recording_data_item = data_item
                    self.__recording_transacted = False
                # next grab the current data and stop if it is a sequence (can't record sequences)
                current_xdata = self.__data_item.xdata
                if current_xdata.is_sequence:
                    self.__stop_recording()
                    return
                # now record the new data. it may or may not be a new frame at this point.
                last_xdata = self.__recording_data_item.xdata
                self.__recording_index += 1
                if current_xdata and last_xdata and current_xdata.data_shape == self.__recording_data_item.data_shape[1:]:
                    # continue, append the new data to existing data and update existing data item
                    intensity_calibration = last_xdata.intensity_calibration
                    dimensional_calibrations = last_xdata.dimensional_calibrations
                    data_descriptor = last_xdata.data_descriptor
                    sequence_xdata = DataAndMetadata.new_data_and_metadata(numpy.vstack([last_xdata.data, [current_xdata.data]]), intensity_calibration=intensity_calibration, dimensional_calibrations=dimensional_calibrations, data_descriptor=data_descriptor)
                    self.__recording_data_item.set_xdata(sequence_xdata)
                elif current_xdata and not last_xdata:
                    # first acquisition, create the sequence
                    intensity_calibration = current_xdata.intensity_calibration
                    dimensional_calibrations = [Calibration.Calibration(scale=self.__recording_interval, units="s")] + list(current_xdata.dimensional_calibrations)
                    data_descriptor = DataAndMetadata.DataDescriptor(True, current_xdata.data_descriptor.collection_dimension_count, current_xdata.data_descriptor.datum_dimension_count)
                    sequence_xdata = DataAndMetadata.new_data_and_metadata(current_xdata.data[numpy.newaxis, ...], intensity_calibration=intensity_calibration, dimensional_calibrations=dimensional_calibrations, data_descriptor=data_descriptor)
                    self.__recording_data_item.set_xdata(sequence_xdata)
                    self.__recording_data_item._enter_transaction_state()
                    self.__recording_transacted = True
                else:
                    # something is amiss. stop.
                    self.__stop_recording()
                    return
            # finally -- check if we've reached the maximum count
            if self.__recording_index >= self.__recording_count:
                self.__stop_recording()

    def __begin_recording(self):
        self.__recording_state = "recording"
        self.__recording_last = 0.0
        self.__recording_index = 0
        self.__recording_interval = self.__recording_interval_property.value / 1000
        self.__recording_count = self.__recording_count_property.value
        self.__record_button.text = _("Stop")

    def __stop_recording(self):
        if self.__recording_state == "recording":
            self.__recording_state = "stopped"
            self.__recording_last = 0.0
            self.__recording_index = 0
            if self.__recording_data_item and self.__recording_transacted:
                self.__recording_data_item._exit_transaction_state()
                self.__recording_data_item = None
                self.__recording_transacted = False
            self.__record_button.text = _("Record")
